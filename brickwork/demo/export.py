"""Render the demo routes to a static site with the real templates, CSS and JavaScript.

The app runs in-process on a synthetic store (dataset.py) under the site's base path, so every
`url_for` link already carries it. Pages are crawled from fixed seeds and only along the routes the
demo includes; links to anything else become "not part of the demo". The JSON the pages read (the
Prices records and their details) is saved beside them. A small script (shim.js), loaded first on
every page, answers those reads from the saved files and every write with "not saved".
"""
import html
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from . import dataset

ROOT = Path(__file__).resolve().parents[2]
NOTE = 'Demo with sample data: changes are not saved'
SEEDS = ['/collection/sets', '/collection/M', '/collection/P', '/collection/item/P/3001?colour=4',
         '/workbench/check-parts', '/workbench/part-picker', '/workbench/part-to-inventory',
         '/planning/wishlist', '/planning/prices', '/planning/complete-sets', '/workbench/storage']
# Routes the crawl may follow from a seed (the agreed demo routes and their own sub-pages).
FOLLOW = [re.compile(p) for p in (
    r'^/collection/(sets|M|P)$',
    r'^/collection/item/S/[^/?]+$',
    r'^/workbench/check-parts(/[0-9a-f-]{36}(\?run=1)?)?$',
    r'^/workbench/(part-picker|part-to-inventory)$',
    r'^/planning/(wishlist|prices|complete-sets)$',
    r'^/workbench/storage(/[^/?]+)?$',
)]
LIMIT = 120
ATTRIBUTE = re.compile(r'(\s(?:href|src|action|poster|content|data-[\w-]+)=")([^"]*)(")')
# Links a visitor may follow (the app's catalogue links); nothing outside is ever loaded (src).
LINKS_OK = re.compile(r'^https://(github\.com/Ulef1005/brick-work|(www\.)?bricklink\.com/|brickset\.com/|rebrickable\.com/)')
PRIVATE = re.compile(r'example-home\.test|192\.168\.\d+\.\d+|/Users/[A-Za-z]|/home/[a-z]|op://|\btest instance\b', re.I)


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
        folder += '/_' + re.sub(r'[^A-Za-z0-9._-]', '-', query.replace('=', '-').replace('&', '_'))
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
            if not isinstance(record, dict) or 'type' not in record or 'number' not in record:
                continue
            query = [('kind', record['type']), ('number', record['number'])]
            if record.get('color_id') is not None:
                query.append(('colour', str(record['color_id'])))
            key = '/planning/prices/details?' + urlencode(sorted(query))
            reply = get('/planning/prices/details?' + urlencode(query))
            if reply.status_code == 200:
                out[key] = reply.get_data(as_text=True)
    return out


def render(client, base, data):
    with client:
        # Every owned set's page too: the lists link to them from rows their script builds.
        owned = dict.fromkeys('/collection/item/S/' + c['set'] for c in json.loads((data / 'sets.json').read_text(encoding='utf-8')))
        pages, skipped = crawl(client, base, SEEDS + list(owned))
        more, extra_skipped = crawl(client, base, follow_ups(pages))
        pages.update(more)
        skipped.update(extra_skipped)
        saved = reads(client, base)
    return pages, skipped, saved


def rewrite(text, base, pages):
    def attribute(match):
        start, value, end = match.groups()
        if value.startswith('/static/'):
            return start + base + value[1:] + end
        key = key_of(value, base)
        if key is None or key.startswith('/static/') or '/static/' in value:
            return match.group(0)
        if key in pages:
            return start + base + file_of(key).removesuffix('index.html') + end
        if start.strip().startswith('data-'):
            return match.group(0)  # endpoint templates; the shim answers them at run time
        return start + '#demo-not-included' + end
    text = ATTRIBUTE.sub(attribute, text)
    text = re.sub(r'<link rel="manifest"[^>]*>', '', text)  # the demo is not an installable app
    shim = f'<script src="{base}demo-shim.js"></script>'
    return re.sub(r'<head([^>]*)>', lambda m: m.group(0) + shim, text, count=1)


def check(out):
    """Private patterns and outside URLs in src/href attributes; returns the findings."""
    findings = []
    for path in sorted(out.rglob('*.html')) + [out / 'demo-shim.js']:
        text = path.read_text(encoding='utf-8')
        for number, line in enumerate(text.splitlines(), 1):
            if PRIVATE.search(line):
                findings.append(f'{path.relative_to(out)}:{number}: private pattern')
        for url in re.findall(r'\ssrc="(https?://[^"]+)"', text):
            findings.append(f'{path.relative_to(out)}: loads from outside {url}')
        for url in re.findall(r'\shref="(https?://[^"]+)"', text):
            if not LINKS_OK.match(html.unescape(url)):
                findings.append(f'{path.relative_to(out)}: outside link {url}')
    return findings


def export(out, base='/brick-work/demo/', data=dataset.DATA):
    """Build the demo into `out` (which must not exist). Returns the manifest; raises on findings."""
    out = Path(out)
    if out.exists():
        raise FileExistsError(out)
    if not base.startswith('/') or not base.endswith('/'):
        raise ValueError('base must start and end with /')
    with tempfile.TemporaryDirectory() as scratch:
        store = Path(scratch) / 'brickwork.db'
        counts = dataset.build(store, data)
        saved_env = {k: os.environ.get(k) for k in ('BW_DB_PATH', 'BW_EMBEDDED_WORKER', 'BW_ALLOW_NO_LOGIN', 'BW_AUTHENTICATION_PASSWORD')}
        try:
            client = make_app(store).test_client()
            pages, skipped, saved = render(client, base, data)
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    out.mkdir(parents=True)
    shutil.copytree(ROOT / 'static', out / 'static')
    for key, text in pages.items():
        target = out / file_of(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewrite(text, base, pages), encoding='utf-8')
    gets = {}
    for index, (key, text) in enumerate(sorted(saved.items())):
        name = f'data/{index:04d}.json'
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(text, encoding='utf-8')
        gets[key] = name
    manifest = dict(base=base, note=NOTE, pages={k: file_of(k).removesuffix('index.html') for k in sorted(pages)},
                    gets=gets, skipped=skipped, counts=counts)
    shim = (Path(__file__).with_name('shim.js').read_text(encoding='utf-8')
            .replace('/*MANIFEST*/null', json.dumps({k: manifest[k] for k in ('base', 'note', 'pages', 'gets')})))
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
