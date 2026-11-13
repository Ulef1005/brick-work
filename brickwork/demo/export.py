"""Render the demo routes to a static site with the real templates, CSS and JavaScript.

The app runs in-process on a synthetic store (dataset.py) under the site's base path, so every
`url_for` link already carries it. Pages are crawled from fixed seeds and only along the routes the
demo includes; links to anything else become "not part of the demo". The JSON the pages read (the
Prices records and their details) is saved beside them. A small script (shim.js), loaded first on
every page, answers those reads from the saved files and every write with "not saved".
"""
from contextlib import closing
import hashlib
import html
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from . import checks, clock, dataset, real, showcase
from .privacy import pattern

ROOT = Path(__file__).resolve().parents[2]
NOTE = 'Demo with sample data: changes are not saved'
SEEDS = ['/collection/sets', '/collection/M', '/collection/P', '/collection/G', '/collection/B', '/collection/C', '/collection/purchase-places',
         '/workbench/check-parts', '/workbench/part-picker', '/workbench/part-to-inventory', '/workbench/match', '/workbench/orders',
         '/workbench/what-is-this', '/workbench/storage',
         '/planning/wishlist', '/planning/prices', '/planning/complete-sets',
         '/manage/add', '/manage/tools', '/manage/statistics', '/manage/sync', '/manage/catalogues', '/manage/tokens', '/manage/jobs',
         '/manage/refresh', '/manage/appearance', '/manage/history', '/manage/values']
# Routes the crawl may follow from a seed (the agreed demo routes and their own sub-pages).
FOLLOW = [re.compile(p) for p in (
    r'^/collection/(sets|M|P|G|B|C|purchase-places)$',
    r'^/collection/item/[1-9][0-9]*(\?colour=[0-9]+)?$',
    r'^/collection/wishes/wish-[A-Za-z0-9._%-]+$',
    r'^/workbench/check-parts(/[0-9a-f-]{36}(\?run=1)?)?$',
    r'^/workbench/(part-picker|part-to-inventory|match|what-is-this)$',
    r'^/workbench/orders(/[1-9][0-9]*)?$',
    r'^/planning/(wishlist|prices|complete-sets)$',
    r'^/workbench/storage(/[^/?]+)?$',
    r'^/manage/(add|tools|statistics|sync|catalogues|tokens|jobs|refresh|appearance|history|values)$',
)]
LIMIT = 3000   # a safety stop, never a silent cut: reaching it raises (the whole demo is about 1,300 pages)
HOST_PATH = re.compile(r'/var/folders|/private/var|/private/tmp|/tmp/|/home/[a-z]|/Users/[A-Za-z]|\btmp[a-z0-9_]{8}\b')
NEUTRAL_ROOT = '/srv/brick-work'   # what the pages that print the store and media paths show instead of the build's scratch folder
ATTRIBUTE = re.compile(r'(\s(?:href|src|action|poster|content|data-[\w-]+)=")([^"]*)(")')
# Links a visitor may follow (the app's catalogue links); nothing outside is ever loaded (src).
LINKS_OK = re.compile(r'^https://(github\.com/Ulef1005/brick-work|ulef1005\.github\.io/brick-work/\Z|(www\.)?bricklink\.com/|brickset\.com/|rebrickable\.com/)')


def key_of(url, base):
    """The app route (path plus sorted query) of a URL under `base`, or None."""
    parts = urlsplit(html.unescape(url))
    if parts.scheme or parts.netloc or not parts.path.startswith(base):
        return None
    path = '/' + parts.path[len(base):].lstrip('/')
    query = urlencode(sorted(parse_qsl(parts.query)))
    return path.rstrip('/') or '/' if not query else (path.rstrip('/') or '/') + '?' + query


def file_of(key):
    path, _, query = key.partition('?')
    folder = path.strip('/')
    if query:
        name = re.sub(r'[^A-Za-z0-9._-]', '-', query.replace('=', '-').replace('&', '_'))
        if len(name) > 100:   # a long query (the Part Runner with every incomplete copy ticked) would not fit a file name
            name = name[:40] + '-' + hashlib.sha1(query.encode()).hexdigest()[:16]
        folder += '/_' + name
    return (folder + '/' if folder else '') + 'index.html'


def make_app(store):
    os.environ.update(BW_DB_PATH=str(store), BW_EMBEDDED_WORKER='0', BW_ALLOW_NO_LOGIN='1', BW_AUTHENTICATION_PASSWORD='')
    from flask import Flask
    from ..app import setup_app
    app = Flask('brick-work-demo', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config.update(SECRET_KEY='demo-only', TESTING=True)
    return app


def crawl(client, base, seeds):
    pages, queue, skipped = {}, list(seeds), {}
    while queue and len(pages) < LIMIT:
        key = queue.pop(0)
        if key in pages or key in skipped:
            continue
        response = client.get(key, base_url='http://demo.invalid' + base.rstrip('/'))
        if response.status_code != 200 or not response.mimetype == 'text/html':
            skipped[key] = response.status_code
            continue
        text = response.get_data(as_text=True)
        pages[key] = text
        for _, value, _ in ATTRIBUTE.findall(text):
            found = key_of(value, base)
            if found and found not in pages and any(p.match(found) for p in FOLLOW):
                queue.append(found)
    left = sorted({k for k in queue if k not in pages and k not in skipped})
    if left:
        raise RuntimeError(f'demo crawl reached its limit of {LIMIT} pages with {len(left)} still to visit, for example {left[0]}: raise LIMIT or narrow FOLLOW')
    return pages, skipped


def follow_ups(pages):
    """Pages reached by a form rather than a link: each copy's running check (Start) and the Part
    Picker's picking view for its default choice of sets (Continue)."""
    keys = [k + '?run=1' for k in pages if re.fullmatch(r'/workbench/check-parts/[0-9a-f-]{36}', k)]
    picker = pages.get('/workbench/part-picker', '')
    # With nothing ticked the page's script ticks every copy ("All incomplete sets").
    chosen = sorted(re.findall(r'<input type="checkbox" name="copy" value="([^"]+)"', picker))
    if chosen:
        keys.append('/workbench/part-picker?' + urlencode([('copy', c) for c in chosen]))
    return [k for k in keys if k not in pages]


def reads(client, base):
    """The JSON the pages fetch: Prices records and one details reply per record."""
    out = {}
    get = lambda key: client.get(key, base_url='http://demo.invalid' + base.rstrip('/'), headers={'Accept': 'application/json'})
    records = get('/planning/prices/records')
    if records.status_code == 200:
        out['/planning/prices/records'] = records.get_data(as_text=True)
        data = records.get_json()
        rows = data.get('rows', data) if isinstance(data, dict) else data
        fields = data.get('fields') if isinstance(data, dict) else None
        for row in rows if isinstance(rows, list) else []:
            record = dict(zip(fields, row)) if fields and isinstance(row, list) else row
            if not isinstance(record, dict) or not record.get('item_id'):
                continue
            query = [('item_id', str(record['item_id']))]
            if record.get('color_id') is not None:
                query.append(('colour', str(record['color_id'])))
            key = '/planning/prices/details?' + urlencode(sorted(query))
            reply = get('/planning/prices/details?' + urlencode(query))
            if reply.status_code == 200:
                out[key] = reply.get_data(as_text=True)
    return out


def item_pages(store):
    """The item pages the lists link to from rows their script builds: every owned set, one item of each other kind that is held loose
    (a few figures, gear, books, catalogs), and some parts in one colour each."""
    from ..core.connect import connect
    with closing(connect(store, read_only=True)) as db:
        sets = ['/collection/item/%d' % r[0] for r in db.execute('SELECT DISTINCT item_id FROM copy WHERE archived_at IS NULL ORDER BY item_id')]
        other = ['/collection/item/%d' % r[0] for kind, limit in (('minifigure', 6), ('gear', 5), ('book', 4), ('catalog', 3))
                 for r in db.execute('SELECT DISTINCT item_id FROM stock WHERE kind=? AND archived_at IS NULL ORDER BY item_id LIMIT ?', (kind, limit))]
        parts = db.execute("SELECT item_id, color_id FROM stock WHERE kind='part' AND archived_at IS NULL ORDER BY item_id, color_id LIMIT 4").fetchall()
    return sets + other + ['/collection/item/%d?colour=%d' % tuple(part) for part in parts]


def render(client, base, data, store):
    with client:
        pages, skipped = crawl(client, base, SEEDS + item_pages(store))
        more, extra_skipped = crawl(client, base, follow_ups(pages))
        pages.update(more)
        skipped.update(extra_skipped)
        saved = reads(client, base)
    return pages, skipped, saved


def pictures_of(store):
    """{picture id: bytes} of the demo world's pictures (the showcase's own PNG illustrations, design/demo-art/, or the real sets' JPEGs): the pages ask for
    /manage/images/<id>?w=..., and a static site answers every query with the one file, `<id>.png` or `<id>.jpg` (shim.js maps the URLs the pages' scripts build)."""
    from ..core.connect import connect
    root = Path(store).resolve().parent
    with closing(connect(store, read_only=True)) as db:
        return {r[0]: (root / r[1]).read_bytes() for r in db.execute('SELECT id, local_path FROM picture ORDER BY id') if (root / r[1]).is_file()}


def extension(content):
    """The file extension a picture's bytes call for: `png` for a PNG (the showcase's illustrations), `jpg` for a JPEG (the real sets' pictures)."""
    return 'png' if content[:8] == b'\x89PNG\r\n\x1a\n' else 'jpg'


def rewrite(text, base, pages, types=None):
    """`types` names the extension of each picture that is not a PNG ({picture id: 'jpg'}); the rest are `<id>.png`."""
    types = types or {}

    def attribute(match):
        start, value, end = match.groups()
        if value.startswith('/static/'):
            return start + base + value[1:] + end
        key = key_of(value, base)
        if key is None or key.startswith('/static/') or '/static/' in value:
            return match.group(0)
        picture = re.match(r'^/manage/images/([0-9]+)', key)
        if picture:                                     # one file per picture, whatever width the page asks for; the pages' own image base ends in 0
            return match.group(0) if picture[1] == '0' else start + base + 'manage/images/' + picture[1] + '.' + types.get(picture[1], 'png') + end
        if key in pages:
            return start + base + file_of(key).removesuffix('index.html') + end
        if start.strip().startswith('data-'):
            return match.group(0)  # endpoint templates; the shim answers them at run time
        return start + '#demo-not-included' + end
    text = ATTRIBUTE.sub(attribute, text)
    # srcset lists one URL per width; the demo has the one file
    text = re.sub(r'(\ssrcset=")([^"]*)(")', lambda m: m.group(1) + re.sub(r'(/manage/images/([1-9][0-9]*))\?w=[0-9]+', lambda w: w[1] + '.' + types.get(w[2], 'png'), m.group(2)) + m.group(3), text)
    text = re.sub(r'<link rel="manifest"[^>]*>', '', text)  # the demo is not an installable app
    shim = f'<script src="{base}demo-shim.js"></script>'
    return re.sub(r'<head([^>]*)>', lambda m: m.group(0) + shim, text, count=1)


def neutral(text, hidden, version):
    """A page or reply with the build's scratch folder shown as NEUTRAL_ROOT and the asset cache-buster made content-derived (the same in every build)."""
    for folder in hidden:
        text = text.replace(folder, NEUTRAL_ROOT)
    return re.sub(r'(\.(?:css|js|png|svg|ico|woff2?))\?v=[0-9]+', lambda m: m.group(1) + '?v=' + version, text)


def static_version(folder):
    digest = hashlib.sha1()
    for path in sorted(p for p in Path(folder).rglob('*') if p.is_file() and not any(part.startswith('.') or part == '__pycache__' for part in p.relative_to(folder).parts)):
        digest.update(str(path.relative_to(folder)).encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()[:12]


TEXT = ('.html', '.json', '.js', '.css', '.svg', '.webmanifest', '.txt')


def check(out):
    """Private patterns, host paths and outside URLs; returns the findings. Every text file of the export is scanned for private and host-path patterns
    (pages, saved replies, the shim, the app's scripts and styles); src/href attributes are checked in the pages and the shim."""
    findings, private = [], pattern()
    for path in sorted(p for p in out.rglob('*') if p.is_file() and p.suffix in TEXT):
        text = path.read_text(encoding='utf-8', errors='replace')
        for number, line in enumerate(text.splitlines(), 1):
            if private.search(line):
                findings.append(f'{path.relative_to(out)}:{number}: private pattern')
            if HOST_PATH.search(line):
                findings.append(f'{path.relative_to(out)}:{number}: host path')
    for path in sorted(out.rglob('*.html')) + [out / 'demo-shim.js']:
        text = path.read_text(encoding='utf-8')
        for url in re.findall(r'\ssrc="(https?://[^"]+)"', text):
            findings.append(f'{path.relative_to(out)}: loads from outside {url}')
        for url in re.findall(r'\shref="(https?://[^"]+)"', text):
            if not LINKS_OK.match(html.unescape(url)):
                findings.append(f'{path.relative_to(out)}: outside link {url}')
    return findings


def export(out, base='/brick-work/demo/', data=dataset.DATA, rich=True, world='showcase'):
    """Build the demo into `out` (which must not exist). Returns the manifest; raises on findings. `rich` adds the showcase layer
    (showcase.py) to the design test data's world; the screen gate renders the world without it. `world='real'` builds the real-sets world instead (real.py, #332)."""
    layer, plan = (real.layer(), real.CHECKS) if world == 'real' else (showcase.layer(data), showcase.CHECKS)
    out = Path(out)
    if out.exists():
        raise FileExistsError(out)
    if not base.startswith('/') or not base.endswith('/'):
        raise ValueError('base must start and end with /')
    with tempfile.TemporaryDirectory() as scratch:
        store = Path(scratch) / 'brickwork.db'
        hidden = sorted({str(scratch), str(Path(scratch).resolve()), os.path.realpath(scratch)}, key=len, reverse=True)
        counts = dataset.build(store, data, layer if rich else None)
        saved_env = {k: os.environ.get(k) for k in ('BW_DB_PATH', 'BW_EMBEDDED_WORKER', 'BW_ALLOW_NO_LOGIN', 'BW_AUTHENTICATION_PASSWORD')}
        patched = []
        try:
            client = make_app(store).test_client()
            for key in SEEDS + item_pages(store)[:6]:   # every module a page imports lazily is imported before the clock stops
                client.get(key, base_url='http://demo.invalid' + base.rstrip('/'))
            patched = clock.freeze_clock()              # prices go stale after a week and pages show relative dates: the demo's "now" is fixed
            counts['checks'] = checks.stage(store, plan if rich else None)
            pages, skipped, saved = render(client, base, data, store)
            images = pictures_of(store)
            counts['pictures'] = len(images)
        finally:
            clock.thaw_clock(patched)
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    out.mkdir(parents=True)
    shutil.copytree(ROOT / 'static', out / 'static')
    version = static_version(out / 'static')
    (out / 'manage' / 'images').mkdir(parents=True)
    types = {str(identifier): extension(content) for identifier, content in images.items() if extension(content) != 'png'}
    for identifier, content in images.items():
        (out / 'manage' / 'images' / f'{identifier}.{extension(content)}').write_bytes(content)
    for key, text in pages.items():
        target = out / file_of(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(neutral(rewrite(text, base, pages, types), hidden, version), encoding='utf-8')
    gets = {}
    for index, (key, text) in enumerate(sorted(saved.items())):
        name = f'data/{index:04d}.json'
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(neutral(text, hidden, version), encoding='utf-8')
        gets[key] = name
    counts['crawl_limit'] = LIMIT
    manifest = dict(base=base, note=NOTE, pages={k: file_of(k).removesuffix('index.html') for k in sorted(pages)},
                    gets=gets, skipped=skipped, counts=counts, **({'pictures': types} if types else {}))
    shim = (Path(__file__).with_name('shim.js').read_text(encoding='utf-8')
            .replace('/*MANIFEST*/null', json.dumps({k: manifest[k] for k in ('base', 'note', 'pages', 'gets', 'pictures') if k in manifest})))
    (out / 'demo-shim.js').write_text(shim, encoding='utf-8')
    start = base + manifest['pages']['/collection/sets']
    (out / 'index.html').write_text(f'<!doctype html><meta charset="utf-8"><title>Brick Work demo</title>'
                                    f'<meta http-equiv="refresh" content="0; url={start}"><a href="{start}">Open the demo</a>\n',
                                    encoding='utf-8')
    (out / 'demo-manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    findings = check(out)
    if findings:
        raise RuntimeError('demo export not clean:\n' + '\n'.join(findings[:50]))
    return manifest
