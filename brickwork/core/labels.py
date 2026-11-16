"""Storage labels: one source for web previews, downloads, API and MCP links."""
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
import ipaddress
import json
import math
import threading
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

from .transaction import transaction

DPI = 300
ROOT = Path(__file__).resolve().parents[2]


def px(mm):
    return round(mm * DPI / 25.4)


@dataclass(frozen=True)
class Layout:
    title: str
    width: float
    height: float
    columns: int
    rows: int
    left: float
    top: float
    gap: float = 0

    @property
    def capacity(self):
        return self.columns * self.rows


LAYOUTS = {
    'a4-21': Layout('A4 · 21 labels, 63.5 × 38.1 mm', 63.5, 38.1, 3, 7, 7.25, 15.15, 2.5),
    'a4-14': Layout('A4 · 14 labels, 99.1 × 38.1 mm', 99.1, 38.1, 2, 7, 4.65, 15.15, 2.5),
    'tape-62': Layout('Label tape · 62 mm, one label per image', 62, 45, 1, 1, 0, 0),
}


def validate_address(value):
    value = str(value).strip().rstrip('/')
    parsed = urlsplit(value)
    if value and (any(c.isspace() for c in value) or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                  or '?' in value or '#' in value or '@' in parsed.netloc or parsed.path not in ('', '/')):
        raise ValueError('Use an HTTP or HTTPS address without a path, password or query')
    try:
        parsed.port
    except ValueError:
        raise ValueError('Use a valid port') from None
    return value


def address(db, request_host):
    row = db.execute("SELECT value FROM main.setting WHERE key='labels_address'").fetchone()
    value = validate_address(row[0] if row and row[0] else request_host)
    host = urlsplit(value).hostname or ''
    warning = host.lower() == 'localhost' or host.lower().endswith('.localhost')
    try:
        ipaddress.ip_address(host)
        warning = True
    except ValueError:
        pass
    return dict(value=value, warning=warning)


def save_address(db, value):
    from .admin import audit
    value = validate_address(value)
    with transaction(db):
        old = db.execute("SELECT value FROM main.setting WHERE key='labels_address'").fetchone()
        if value == validate_address(old[0] if old and old[0] else ''):
            return None
        db.execute("INSERT OR REPLACE INTO main.setting(key,value) VALUES('labels_address',?)", (value,))
        audit(db, 'settings', 'save', {'setting': {'labels_address': old[0] if old else None}, 'freshness': {}},
              {'setting': {'labels_address': value}, 'freshness': {}})
        return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def selection(db, ids):
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > 200 or any(not isinstance(i, str) for i in ids):
        raise ValueError('Choose between 1 and 200 storages')
    rows = {r['id']: dict(r) for r in db.execute('''SELECT id,name,short_id FROM main.storage
        WHERE archived_at IS NULL AND id IN (SELECT value FROM json_each(?))''', (json.dumps(ids),))}
    if len(rows) != len(ids):
        raise ValueError('Choose active storages')
    return [rows[i] for i in ids]


def plan(db, ids, layout, request_host):
    if layout not in LAYOUTS:
        raise ValueError('Choose a label layout')
    rows = selection(db, ids)
    return dict(storages=rows, layout=layout, pages=math.ceil(len(rows) / LAYOUTS[layout].capacity), address=address(db, request_host))


UNAVAILABLE_MESSAGE = 'The PDF was not made. Nothing was changed. Retry makes it again.'


def qr_module():
    from .errors import LabelsUnavailable
    try:
        import segno
    except ImportError:
        raise LabelsUnavailable(UNAVAILABLE_MESSAGE) from None
    return segno


def qr_matrix(payload):
    segno = qr_module()
    return tuple(tuple(row) for row in segno.make(payload, error='m', micro=False, boost_error=False).matrix)


def qr_image(matrix):
    # The module square alone is at least 20 mm; four additional modules on every side stay white.
    scale = math.ceil(px(20) / len(matrix))
    image = Image.new('RGB', ((len(matrix) + 8) * scale,) * 2, 'white')
    draw = ImageDraw.Draw(image)
    for y, row in enumerate(matrix):
        for x, on in enumerate(row):
            if on:
                draw.rectangle(((x + 4) * scale, (y + 4) * scale, (x + 5) * scale - 1, (y + 5) * scale - 1), fill='black')
    return image


_fonts = threading.local()


def font(size, mono=False):
    # Loaded once per thread and size: a FreeType face is not safe to share between threads.
    cache = _fonts.__dict__.setdefault('faces', {})
    if (size, mono) not in cache:
        name = 'geist-mono-latin-400-normal.woff2' if mono else 'inter-latin-600-normal.woff2'
        cache[size, mono] = ImageFont.truetype(str(ROOT / 'static/web/toni/fonts' / name), size)
    return cache[size, mono]


def name_lines(name, face, width, count=2):
    # Character wrapping also handles a single long word and preserves umlauts.
    lines, rest = [], name
    while rest and len(lines) < count:
        n = 1
        while n <= len(rest) and face.getlength(rest[:n]) <= width:
            n += 1
        n = max(1, n - 1)
        if n < len(rest) and ' ' in rest[:n]:
            n = rest.rfind(' ', 0, n) or n
        lines.append(rest[:n].strip())
        rest = rest[n:].lstrip()
    if rest:
        while lines[-1] and face.getlength(lines[-1] + '…') > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += '…'
    return lines


@lru_cache(maxsize=1)
def mark_rects():
    """The shipped mark's rectangles as plain tuples: (x, y, width, height, stroke-width, rx, dasharray or None)."""
    root = ET.parse(ROOT / 'static/brickwork/mark-line.svg').getroot()
    return tuple((*(float(rect.get(k)) for k in ('x', 'y', 'width', 'height')), float(rect.get('stroke-width', '3.2')),
                  float(rect.get('rx', 0)), rect.get('stroke-dasharray')) for rect in root.iter('{http://www.w3.org/2000/svg}rect'))


def mark(image, xy, size):
    """Rasterise the shipped monochrome line mark's rectangles and cross in black."""
    draw = ImageDraw.Draw(image)
    unit = size / 96
    for x, y, w, h, stroke_width, rx, dasharray in mark_rects():
        box = (xy[0] + x * unit, xy[1] + y * unit, xy[0] + (x + w) * unit, xy[1] + (y + h) * unit)
        stroke = max(1, round(stroke_width * unit))
        radius = rx * unit
        if dasharray:
            # Follow the rounded perimeter, keeping the SVG's dash spacing through corners.
            points = []
            for cx, cy, start in ((box[2]-radius,box[1]+radius,-90), (box[2]-radius,box[3]-radius,0),
                                  (box[0]+radius,box[3]-radius,90), (box[0]+radius,box[1]+radius,180)):
                for step in range(9):
                    angle = math.radians(start + step * 90 / 8)
                    points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
            points.append(points[0])
            dash, gap = (float(v)*unit for v in dasharray.split())
            distance = 0.0
            for a, b in zip(points, points[1:]):
                length = math.dist(a,b)
                steps = max(1, math.ceil(length * 2))
                for step in range(steps):
                    if (distance + length * step / steps) % (dash + gap) < dash:
                        t, u = step / steps, (step + 1) / steps
                        draw.line((a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t,
                                   a[0]+(b[0]-a[0])*u, a[1]+(b[1]-a[1])*u), fill='black', width=stroke)
                distance += length
        else:
            draw.rounded_rectangle(box, radius=radius, outline='black', width=stroke)
    for line in ((60,27,66,33), (60,33,66,27)):
        draw.line(tuple(xy[i % 2] + v * unit for i,v in enumerate(line)), fill='black', width=max(1,round(2.4*unit)))


def label(row, layout, base, matrix_factory=qr_matrix):
    tape = layout == 'tape-62'
    spec = LAYOUTS[layout]
    image = Image.new('RGB', (px(spec.width), px(spec.height)), 'white')
    qr = qr_image(matrix_factory(base + '/workbench/storage/' + row['id']))
    draw = ImageDraw.Draw(image)
    pad = px(2)
    if tape:
        image.paste(qr, ((image.width - qr.width)//2, image.height - qr.height - pad))
        mark(image, (pad, pad), px(7))
        face = font(40)
        width = image.width - px(30)
        draw.text((px(10), pad), name_lines(row['name'], face, width, 1)[0], font=face, fill='black')
        draw.text((image.width - px(19), pad), row['short_id'], font=font(23, True), fill='black')
    else:
        image.paste(qr, (image.width - qr.width - pad, (image.height - qr.height)//2))
        width = image.width - qr.width - pad * 3
        mark(image, (pad, px(3)), px(8))
        face = font(56 if layout == 'a4-21' else 69)
        y = px(12)
        for line in name_lines(row['name'], face, width):
            draw.text((pad, y), line, font=face, fill='black')
            y += face.size + 6
        draw.text((pad, px(30)), row['short_id'], font=font(28, True), fill='black')
    return image


def page_image(found, page=0, *, guides=False, matrix_factory=qr_matrix):
    spec = LAYOUTS[found['layout']]
    if not 0 <= page < found['pages']:
        raise ValueError('Choose a preview sheet')
    if found['layout'] == 'tape-62':
        return label(found['storages'][page], found['layout'], found['address']['value'], matrix_factory)
    image = Image.new('RGB', (px(210), px(297)), 'white')
    draw = ImageDraw.Draw(image)
    rows = found['storages'][page * spec.capacity:(page + 1) * spec.capacity]
    for i in range(spec.capacity):
        x, y = px(spec.left + (i % spec.columns) * (spec.width + spec.gap)), px(spec.top + (i // spec.columns) * spec.height)
        if i < len(rows):
            image.paste(label(rows[i], found['layout'], found['address']['value'], matrix_factory), (x, y))
        if guides:
            right, bottom = x + px(spec.width) - 1, y + px(spec.height) - 1
            for start in range(x, right, 24):
                for edge in (y, bottom):
                    draw.line((start, edge, min(start + 12, right), edge), fill='#B9B2A5', width=3)
            for start in range(y, bottom, 24):
                for edge in (x, right):
                    draw.line((edge, start, edge, min(start + 12, bottom)), fill='#B9B2A5', width=3)
    return image


def download(found, *, matrix_factory=qr_matrix):
    out = BytesIO()
    if found['layout'] != 'tape-62':
        # One page in memory at a time: a full page is about 26 MB, so 15 pages at once are not affordable.
        # Pillow's append mode adds each page to the file; the pages are the same images as before.
        for i in range(found['pages']):
            page_image(found, i, matrix_factory=matrix_factory).save(out, 'PDF', resolution=DPI, quality=95, append=bool(i))
        return out.getvalue(), 'application/pdf', 'storage-labels.pdf'
    images = [(r['short_id'] + '.png', label(r, found['layout'], found['address']['value'], matrix_factory)) for r in found['storages']]
    if len(images) == 1:
        images[0][1].save(out, 'PNG', dpi=(DPI, DPI))
        return out.getvalue(), 'image/png', images[0][0]
    with ZipFile(out, 'w') as archive:
        for name, image in images:
            data = BytesIO()
            image.save(data, 'PNG', dpi=(DPI, DPI))
            archive.writestr(name, data.getvalue())
    return out.getvalue(), 'application/zip', 'storage-labels.zip'


def require_address(db, found):
    """API and MCP only: refuse labels whose QR codes would point at localhost or an IP the phone cannot open."""
    from .errors import BrickWorkError
    saved = db.execute("SELECT value FROM main.setting WHERE key='labels_address'").fetchone()
    if found['address']['warning'] and not (saved and saved[0]):
        raise BrickWorkError('Set the label address in Settings first')
