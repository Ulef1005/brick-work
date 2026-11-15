"""Storage labels: one source for web previews, downloads, API and MCP links."""
from dataclasses import dataclass
from io import BytesIO
import ipaddress
import json
import math
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
    if value and (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                  or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
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
        db.execute("INSERT OR REPLACE INTO main.setting(key,value) VALUES('labels_address',?)", (value,))
        audit(db, 'settings', 'save', {'labels_address': old[0] if old else None}, {'labels_address': value})


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


def qr_matrix(payload):
    import segno                         # optional until the image installs the pinned runtime dependency
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


def font(size, mono=False):
    name = 'geist-mono-latin-400-normal.woff2' if mono else 'inter-latin-600-normal.woff2'
    return ImageFont.truetype(str(ROOT / 'static/web/toni/fonts' / name), size)


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


def mark(image, xy, size):
    """Rasterise the shipped monochrome line mark's rectangles and cross in black."""
    root = ET.parse(ROOT / 'static/brickwork/mark-line.svg').getroot()
    draw = ImageDraw.Draw(image)
    unit = size / 96
    for rect in root.iter('{http://www.w3.org/2000/svg}rect'):
        x, y, w, h = (float(rect.get(k)) for k in ('x', 'y', 'width', 'height'))
        box = (xy[0] + x * unit, xy[1] + y * unit, xy[0] + (x + w) * unit, xy[1] + (y + h) * unit)
        draw.rounded_rectangle(box, radius=float(rect.get('rx', 0)) * unit, outline='black', width=max(1, round(3.2 * unit)))
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
        face = font(30)
        width = image.width - px(30)
        draw.text((px(10), pad), name_lines(row['name'], face, width, 1)[0], font=face, fill='black')
        draw.text((image.width - px(19), pad), row['short_id'], font=font(23, True), fill='black')
    else:
        image.paste(qr, (image.width - qr.width - pad, (image.height - qr.height)//2))
        width = image.width - qr.width - pad * 3
        mark(image, (pad, px(3)), px(8))
        face = font(42 if layout == 'a4-21' else 52)
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
            draw.rectangle((x, y, x + px(spec.width), y + px(spec.height)), outline='#B9B2A5', width=1)
    return image


def download(found, *, matrix_factory=qr_matrix):
    out = BytesIO()
    if found['layout'] != 'tape-62':
        images = [page_image(found, i, matrix_factory=matrix_factory) for i in range(found['pages'])]
        images[0].save(out, 'PDF', resolution=DPI, save_all=True, append_images=images[1:])
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
