"""Storage labels: one source for web previews, downloads, API and MCP links."""
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
import ipaddress
import json
import math
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops, ImageDraw, ImageFont

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


LINE_GAP = 6   # px between name lines


def fit_name(name, size, floor, width, height, count):
    """The largest face from `size` down to `floor` (2 px steps) at which the whole name fits in `count` lines of `width` within
    `height`, and those lines. Only when the floor cannot hold it all is the last line cut with an ellipsis (Ulf, 2026-11-19: "the copy
    must not be cut-off, maybe smaller font size?")."""
    for step in range(size, floor - 1, -2):
        face = font(step)
        lines = name_lines(name, face, width, count + 1)
        # `count + 1` lines leave room to see an overflow: only then does name_lines add its ellipsis, so a name that itself ends
        # in '…' still fits, and an empty name is no lines at all.
        if len(lines) <= count and len(lines) * (step + LINE_GAP) - LINE_GAP <= height:
            return face, lines
    face = font(floor)
    rows = max(1, min(count, (height + LINE_GAP) // (floor + LINE_GAP)))
    return face, name_lines(name, face, width, rows)


SVG = '{http://www.w3.org/2000/svg}'
MARK_X_MIN_SIZE = 32   # the small mark drops its cut-out X below this many pixels (Ulf's approved rule)
_TRANSFORM = re.compile(r'^translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)\s*\)\s*rotate\(\s*(-?[\d.]+)\s*\)\s*scale\(\s*(-?[\d.]+)\s*\)$')


def _transform(text):
    """`translate(tx ty) rotate(0) scale(s)` as (tx, ty, s); any other form, or a rotation, is an error rather than a guess."""
    found = _TRANSFORM.match((text or 'translate(0 0) rotate(0) scale(1)').strip())
    if not found or float(found[3]) != 0 or float(found[4]) <= 0:
        raise ValueError(f'mark-line.svg: unsupported transform {text!r}')
    return float(found[1]), float(found[2]), float(found[4])


def _then(outer, inner):
    return outer[0] + outer[2] * inner[0], outer[1] + outer[2] * inner[1], outer[2] * inner[2]


@lru_cache(maxsize=1)
def _mark_svg():
    """Parse static/brickwork/mark-line.svg: (viewbox size, plates, cut). A plate is (x, y, width, height, rx, masked) in viewBox units;
    the cut is (segments in the plate's own units, stroke width) of the mask's X."""
    root = ET.parse(ROOT / 'static/brickwork/mark-line.svg').getroot()
    box = [float(v) for v in root.get('viewBox', '').split()]
    if len(box) != 4 or box[0] != 0 or box[1] != 0 or box[2] != box[3] or box[2] <= 0:
        raise ValueError('mark-line.svg: expected a square viewBox from 0 0')
    defs = [e for e in root if e.tag == SVG + 'defs']
    rects = [e for d in defs for e in d if e.tag == SVG + 'rect']
    masks = [e for d in defs for e in d if e.tag == SVG + 'mask']
    if len(defs) != 1 or len(rects) != 1 or len(masks) != 1 or len(defs[0]) != 2:
        raise ValueError('mark-line.svg: expected one rect and one mask in defs')
    rect, mask = rects[0], masks[0]
    unit = tuple(float(rect.get(k, 0)) for k in ('x', 'y', 'width', 'height', 'rx'))
    paths = [e for e in mask if e.tag == SVG + 'path']
    if len(paths) != 1 or len(mask) != 2:
        raise ValueError('mark-line.svg: expected the mask to hold one rect and one path')
    numbers = re.findall(r'[-+]?\d*\.?\d+', paths[0].get('d', ''))
    if re.sub(r'[-+\d.\sML,]', '', paths[0].get('d', '')) or len(numbers) % 4:
        raise ValueError('mark-line.svg: the mask path must be M/L line segments only')
    points = [float(v) for v in numbers]
    cut = (tuple(tuple(points[i:i + 4]) for i in range(0, len(points), 4)), float(paths[0].get('stroke-width', 1)))
    plates = []

    def walk(element, matrix, masked):
        for child in element:
            if child.tag == SVG + 'defs':
                continue
            here = _then(matrix, _transform(child.get('transform'))) if child.tag in (SVG + 'g', SVG + 'use') else matrix
            flag = masked
            if child.get('mask'):
                if child.get('mask') != f'url(#{mask.get("id")})':
                    raise ValueError('mark-line.svg: unknown mask')
                if child.tag != SVG + 'use' or child.get('transform'):   # the cut is placed in the use's parent space only
                    raise ValueError('mark-line.svg: a mask only on a use without its own transform')
                flag = True
            if child.tag == SVG + 'g':
                walk(child, here, flag)
            elif child.tag == SVG + 'use':
                if child.get('href', child.get('{http://www.w3.org/1999/xlink}href')) != f'#{rect.get("id")}':
                    raise ValueError('mark-line.svg: a use that is not the plate')
                tx, ty, scale = here
                plates.append((tx + scale * unit[0], ty + scale * unit[1], scale * unit[2], scale * unit[3], scale * unit[4], flag, scale, tx, ty))
            else:
                raise ValueError(f'mark-line.svg: unknown element {child.tag}')
    walk(root, (0.0, 0.0, 1.0), False)
    if not plates:
        raise ValueError('mark-line.svg: no plates')
    return box[2], tuple(plates), cut


def mark_rects():
    """The shipped mark's plates as plain tuples in viewBox units: (x, y, width, height, rx, masked)."""
    return tuple(plate[:6] for plate in _mark_svg()[1])


def mark(image, xy, size):
    """Rasterise the shipped monochrome mark in black: three rounded plates, the third with its X cut out (from MARK_X_MIN_SIZE px up)."""
    viewbox, plates, (segments, stroke) = _mark_svg()
    side, grid = math.ceil(size), 4   # drawn 4x as a mask, then scaled down, for smooth edges
    unit = side * grid / viewbox
    total = Image.new('L', (side * grid,) * 2, 0)
    for x, y, w, h, rx, masked, scale, tx, ty in plates:
        layer = Image.new('L', total.size, 0)
        draw = ImageDraw.Draw(layer)
        draw.rounded_rectangle((x * unit, y * unit, (x + w) * unit - 1, (y + h) * unit - 1), radius=rx * unit, fill=255)
        if masked and size >= MARK_X_MIN_SIZE:
            width = stroke * scale * unit
            for x1, y1, x2, y2 in segments:
                p1, p2 = ((tx + scale * x1) * unit, (ty + scale * y1) * unit), ((tx + scale * x2) * unit, (ty + scale * y2) * unit)
                draw.line((p1, p2), fill=0, width=round(width))
                for cx, cy in (p1, p2):   # round caps
                    draw.ellipse((cx - width / 2, cy - width / 2, cx + width / 2, cy + width / 2), fill=0)
        total = ImageChops.lighter(total, layer)
    image.paste('black', (round(xy[0]), round(xy[1])), total.resize((side, side), Image.LANCZOS))


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
        width = image.width - px(30)
        face, lines = fit_name(row['name'], 40, 26, width, image.height - qr.height - pad * 3, 2)
        y = pad
        for line in lines:
            draw.text((px(10), y), line, font=face, fill='black')
            y += face.size + LINE_GAP
        draw.text((image.width - px(19), pad), row['short_id'], font=font(23, True), fill='black')
    else:
        image.paste(qr, (image.width - qr.width - pad, (image.height - qr.height)//2))
        width = image.width - qr.width - pad * 3
        mark(image, (pad, px(3)), px(8))
        size = 56 if layout == 'a4-21' else 69
        face, lines = fit_name(row['name'], size, round(size * 0.6), width, px(30) - px(12) - pad, 3)
        y = px(12)
        for line in lines:
            draw.text((pad, y), line, font=face, fill='black')
            y += face.size + LINE_GAP
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
    rows, address = found['storages'], found['address']['value']
    if len(rows) == 1:
        label(rows[0], found['layout'], address, matrix_factory).save(out, 'PNG', dpi=(DPI, DPI))
        return out.getvalue(), 'image/png', rows[0]['short_id'] + '.png'
    with ZipFile(out, 'w') as archive:
        # Each label is made, written and dropped in turn: 200 of them at once are about 230 MB.
        for row in rows:
            data = BytesIO()
            label(row, found['layout'], address, matrix_factory).save(data, 'PNG', dpi=(DPI, DPI))
            archive.writestr(row['short_id'] + '.png', data.getvalue())
    return out.getvalue(), 'application/zip', 'storage-labels.zip'


def require_address(db, found):
    """API and MCP only: refuse labels whose QR codes would point at localhost or an IP the phone cannot open."""
    from .errors import BrickWorkError
    saved = db.execute("SELECT value FROM main.setting WHERE key='labels_address'").fetchone()
    if found['address']['warning'] and not (saved and saved[0]):
        raise BrickWorkError('Set the label address in Settings first')
