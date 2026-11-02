"""Performance bench: the app's hot paths on a synthetic collection of realistic size, offline.

    python scripts/bench.py                     # build (or reuse) the bench store, time every path, print the table
    python scripts/bench.py --runs 9 --only api # fewer paths: a substring of the path names
    python scripts/bench.py --hashes            # print the sha256 of each output instead of timing (tests/test_bench_outputs.py)

The store is seeded through the test builders of `tests/app4.py` (the fixture catalogue builder, `Coll`) with invented data only:
`syn` numbers and names, a seeded random generator, a frozen clock and deterministic ids, so two builds are the same file content.
At scale 1: about 3,000 catalogue sets, 4,000 parts and 600 figures; a collection of 1,200 set copies and 300 loose figures, 8,000
loose part lines (about 40,000 parts) in 300 lots, 200 wishes over 5 lists and about 20,000 price observations. Times are the median
of `--runs` warm requests through Flask's test client; `sql` counts the statements every connection of the request ran.
"""
from contextlib import closing, contextmanager
import argparse
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import statistics
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FROZEN = _dt.datetime(2026, 11, 2, 12, 0, 0, tzinfo=_dt.timezone.utc)
BOOTSTRAP = 'synthetic-bootstrap'
PASSWORD = 'synthetic-password'


# ---------- a frozen clock and deterministic ids ----------

class _Frozen(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN if tz else FROZEN.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN.replace(tzinfo=None)

    @classmethod
    def today(cls):
        return FROZEN.replace(tzinfo=None)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):
        return FROZEN.date()


@contextmanager
def frozen(seed=131):
    """Every `datetime`/`date` name bound in a loaded `brickwork` or `tests` module reads FROZEN, `time.time` is fixed, and `uuid.uuid4`
    is a seeded sequence: outputs that show ages, stamps or new ids are the same on every run and every day."""
    saved = []
    ids = random.Random(seed)
    real_uuid4, real_time = uuid.uuid4, time.time

    def patch(owner, name, value):
        saved.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)
    for name, module in list(sys.modules.items()):
        if module is None or not (name.startswith('brickwork') or name.startswith('tests') or name.startswith('scripts')):
            continue
        if getattr(module, 'datetime', None) is _dt.datetime:
            patch(module, 'datetime', _Frozen)
        if getattr(module, 'date', None) is _dt.date:
            patch(module, 'date', _FrozenDate)
    patch(uuid, 'uuid4', lambda: uuid.UUID(int=ids.getrandbits(128), version=4))
    patch(time, 'time', lambda: FROZEN.timestamp())
    try:
        yield
    finally:
        for owner, name, value in reversed(saved):
            setattr(owner, name, value)
        uuid.uuid4, time.time = real_uuid4, real_time


# ---------- the synthetic catalogue and collection ----------

def _counts(scale):
    n = lambda x: max(1, int(x * scale))
    return dict(themes=n(40), colours=n(30), parts=n(4000), figures=n(600), sets=n(3000), copies=n(1200), loose_figures=n(300),
                stock_lines=n(8000), lots=n(300), storages=n(30), wishes=n(200), lists=5, observations=n(20000))


def catalogue_rows(scale, rng):
    """`extra_dump` and `extra_parts` (BrickLink links) for the fixture catalogue builder: invented `syn` rows."""
    c = _counts(scale)
    themes = [[7000 + i, f'Syn theme {i}', ''] for i in range(c['themes'])]
    colours = [[2000 + i, f'Syn colour {i}', f'{rng.randrange(0x1000000):06X}', 'False', 10, 10, 1990, 2026] for i in range(c['colours'])]
    colour_ids = [4, 15, 0, 14] + [r[0] for r in colours]
    parts = [[f'syn{i}', f'Syn part {i}', 11, 'Plastic'] for i in range(c['parts'])]
    links = [[f'syn{i}', '', 'bricklink', 'P', f'synbl{i}', 'matched', 'external_ids', 0] for i in range(c['parts'])]
    figures, sets, inventories, inv_parts, inv_figs = [], [], [], [], []
    inventory = 900000
    for i in range(c['figures']):
        key = f'fig-9{i:05d}'
        figures.append([key, f'Syn figure {i}', 4, ''])
        inventory += 1
        inventories.append([inventory, 1, key])
        for p in rng.sample(range(c['parts']), 4):
            inv_parts.append([inventory, f'syn{p}', rng.choice(colour_ids), 1, 'False', ''])
    for i in range(c['sets']):
        key = f'syn{i}-1'
        lines = rng.randint(15, 60)
        sets.append([key, f'Syn set {i}', rng.randint(1980, 2026), rng.choice(themes)[0], lines * 3, ''])
        inventory += 1
        inventories.append([inventory, 1, key])
        for p in rng.sample(range(c['parts']), lines):
            inv_parts.append([inventory, f'syn{p}', rng.choice(colour_ids), rng.randint(1, 6), 'True' if rng.random() < 0.05 else 'False', ''])
        for f in rng.sample(range(c['figures']), rng.choice((0, 0, 1, 2, 3))):
            inv_figs.append([inventory, f'fig-9{f:05d}', 1])
    dump = dict(themes=themes, colors=colours, parts=parts, minifigs=figures, sets=sets, inventories=inventories,
                inventory_parts=inv_parts, inventory_minifigs=inv_figs)
    return dump, links


def build(target, scale=1.0, seed=131):
    """Build the bench store in the empty folder `target` (brickwork.db, catalogue.db) and return a dict of chosen ids for the paths."""
    from tests.app4 import Coll, make_pair
    from brickwork.core.connect import connect
    target = Path(target)
    rng = random.Random(seed)
    c = _counts(scale)
    with frozen(seed):
        dump, links = catalogue_rows(scale, rng)
        pair = make_pair(target, rich=True, extra_dump=dump, extra_parts=links)
        with closing(connect(pair)) as db:
            coll = Coll(db)
            colours = [coll.colour(k) for k in ('4', '15', '0', '14')] + [coll.colour(str(2000 + i)) for i in range(c['colours'])]
            storages = [coll.storage(f'Syn shelf {i}', type='Shelf') for i in range(c['storages'])]
            places = [coll.place(f'Syn shop {i}', kind='Shop') for i in range(5)]
            lots = [coll.lot(f'Syn bag {i}', storage_id=rng.choice(storages)) for i in range(c['lots'])]
            tags = [coll.flag(f'syn tag {i}', 'tag') for i in range(8)]
            set_keys = [f'syn{i}-1' for i in range(c['sets'])]
            owned_sets = rng.sample(set_keys, min(len(set_keys), int(c['copies'] * 0.9)))
            owned_sets += rng.sample(owned_sets, c['copies'] - len(owned_sets))          # some sets held twice
            copies = []
            for key in owned_sets:
                cid = coll.add_copy(key, condition=rng.choice(('new', 'used', 'used')), completeness=rng.choice(('complete', 'incomplete', 'sealed', None)),
                                    storage=rng.choice(storages), place=rng.choice(places) if rng.random() < 0.3 else None,
                                    price=f'{rng.randint(5, 300)}.00' if rng.random() < 0.5 else None, currency='EUR', date='2024-05-01')
                copies.append(cid)
                if rng.random() < 0.3:
                    coll.tag('copy', cid, rng.choice(tags))
                if rng.random() < 0.2:
                    db.execute('UPDATE copy_part SET missing=1 WHERE rowid=(SELECT rowid FROM copy_part WHERE copy_id=? AND retired_at IS NULL LIMIT 1)', (cid,))
                    db.commit()
            figure_ids = [coll.item('minifigs', f'fig-9{i:05d}') for i in range(c['figures'])]
            for item in rng.sample(figure_ids, min(len(figure_ids), c['loose_figures'])):
                coll.add_stock('minifigure', item, quantity=1, condition='used', storage=rng.choice(storages))
            part_ids = [coll.item('parts', f'syn{i}') for i in range(c['parts'])]
            stock, keys = [], set()
            while len(stock) < c['stock_lines']:
                key = (rng.choice(part_ids), rng.choice(colours), rng.choice(('new', 'used')), rng.choice(lots))
                if key in keys:                                                           # one line per part, colour, condition and lot
                    continue
                keys.add(key)
                stock.append(coll.add_stock('part', key[0], colour=key[1], quantity=rng.randint(1, 9), condition=key[2], lot=key[3]))
            lists = ['default']
            for i in range(1, c['lists']):
                identifier = f'synlist{i}'
                db.execute("INSERT INTO wishlist(id,name,sort,created_at) VALUES(?,?,?,'2026-10-20T12:00:00.000Z')", (identifier, f'Syn list {i}', i))
                lists.append(identifier)
            db.commit()
            wished = []
            for i in range(c['wishes']):
                kind = 'set' if i % 10 < 6 else 'part' if i % 10 < 9 else 'minifigure'
                item = coll.item('sets', rng.choice(set_keys)) if kind == 'set' else rng.choice(part_ids) if kind == 'part' else rng.choice(figure_ids)
                maximum = f'{rng.randint(1, 200)}.00' if rng.random() < 0.6 else None
                try:
                    wid = coll.add_wish(item, colour=rng.choice(colours) if kind == 'part' else None, quantity=rng.randint(1, 4), wishlist=lists[i % len(lists)],
                                        condition=rng.choice(('new', 'used', 'any')), max_price=maximum, currency='EUR')
                except Exception:                                                         # the same item twice in a list: skip it
                    db.rollback()
                    continue
                wished.append((wid, item, kind))
            # prices: a history of used and new, sold and stock quotes for owned and wished items, and a quote with box for some sets
            owned_items = [r[0] for r in db.execute('SELECT DISTINCT item_id FROM copy')]
            priced = [(i, None) for i in owned_items] + [(i, None) for _, i, k in wished if k != 'part']
            priced += [(r[0], r[1]) for r in db.execute("SELECT DISTINCT item_id, color_id FROM stock WHERE kind='part' LIMIT ?", (int(c['observations'] * 0.15),))]
            made, days = 0, 0
            while made < c['observations']:
                days += 1
                for item, colour in priced:
                    if made >= c['observations']:
                        break
                    observed = (FROZEN - _dt.timedelta(days=days * 9 + rng.randint(0, 5))).strftime('%Y-%m-%dT%H:%M:%S.000Z')
                    base = rng.randint(5, 300) if colour is None else rng.randint(1, 90) / 100
                    for condition, guide in (('used', 'sold'), ('new', 'sold'), ('used', 'stock')):
                        coll.price(item, f'{base * (0.9 + rng.random() / 5):.2f}', colour=colour, condition=condition, guide=guide, region='eu',
                                   observed=observed, minimum=f'{base * 0.7:.2f}', maximum=f'{base * 1.3:.2f}', sold=rng.randint(1, 30))
                        made += 1
                    if colour is None and days == 1 and rng.random() < 0.3:
                        coll.price(item, f'{base * 1.4:.2f}', guide='valuation', slot='boxed', source='brickset', observed=observed)
                        made += 1
            db.commit()
            ids = dict(copy=copies[0], set_item=coll.item('sets', owned_sets[0]), wish=wished[0][0], part=part_ids[0], colour=colours[0],
                       lot=lots[0], storage=storages[0], stock=stock[0], figure=figure_ids[0], set_key=owned_sets[0])
    (target / 'ids.json').write_text(json.dumps(ids, sort_keys=True))
    return ids


# ---------- the paths ----------

def paths(ids):
    """(name, kind, target): kind 'web' (a logged-in browser GET), 'api' (API v2 GET with the bootstrap token), 'mcp' (a tool call)."""
    web = [('web collection sets', '/collection/sets'), ('web collection parts', '/collection/P'),
           ('web collection minifigures', '/collection/M'), ('web collection wishes', '/collection/wishes'),
           ('web item page (set copy)', f"/collection/item/{ids['set_item']}?copy={ids['copy']}"),
           ('web wish page', f"/collection/wishes/{ids['wish']}"), ('web lot page', f"/collection/lots/{ids['lot']}"),
           ('web workbench check parts', '/workbench/check-parts'), ('web workbench matcher', '/workbench/matcher'),
           ('web workbench storage', '/workbench/storage'),
           ('web planning wishlist', '/planning/wishlist'), ('web planning prices', '/planning/prices'),
           ('web planning price records', '/planning/prices/records'), ('web planning complete sets', '/planning/complete-sets'),
           ('web search jump', '/collection/jump?q=syn%20set%2012'), ('web add search', '/manage/add/search?type=set&q=syn&sort=number'),
           ('web export wishlist csv', '/lists/wishlist.csv'), ('web export wishlist bl xml', '/planning/wishlists/default/export.xml?kind=sets')]
    api = [('api copies', '/copies?limit=200'), ('api stock', '/stock?limit=200'), ('api minifigures', '/minifigures?limit=200'),
           ('api wishes', '/wishes?limit=200'), ('api prices', '/prices?limit=200'), ('api items search', '/items?q=syn%20set%201&limit=50'),
           ('api catalogue search', '/catalogue/items?q=syn&limit=50'), ('api gaps', '/gaps?limit=200'),
           ('api copy', f"/copies/{ids['copy']}"), ('api copy parts', f"/copies/{ids['copy']}/parts"), ('api wish', f"/wishes/{ids['wish']}"),
           ('api item detail', f"/items/{ids['set_item']}/detail"), ('api item prices', f"/items/{ids['set_item']}/prices"),
           ('api lots', '/lots?limit=200'), ('api storages', '/storages'), ('api ranking', '/planning/ranking?limit=50'),
           ('api export wishlist csv', '/export/wishlist.csv')]
    mcp = [('mcp get_set_by_number', ('get_set_by_number', {'no': ids['set_key'], 'provider': 'rebrickable'})), ('mcp list_wishes', ('list_wishes', {'limit': 50})),
           ('mcp list_copies', ('list_copies', {'limit': 50}))]
    return [(n, 'web', t) for n, t in web] + [(n, 'api', t) for n, t in api] + [(n, 'mcp', t) for n, t in mcp]


class Statements:
    """Counts the SQL statements of every connection `store4.connect` opens while active."""

    def __init__(self):
        self.count = 0
        self.active = False

    def install(self):
        from brickwork.store4 import connect as store4_connect
        real = store4_connect._open

        def traced(path, read_only):
            db = real(path, read_only)
            db.set_trace_callback(self._seen)
            return db
        store4_connect._open = traced

    def _seen(self, _statement):
        if self.active:
            self.count += 1


@contextmanager
def environment(store):
    """The app's settings for the bench store, put back as they were afterwards (the hash test runs inside the suite)."""
    wanted = dict(BW_EMBEDDED_WORKER='0', BW_AUTHENTICATION_PASSWORD=PASSWORD, BW_DB_PATH=str(Path(store) / 'brickwork.db'), BW_API_TOKEN=BOOTSTRAP)
    before = {k: os.environ.get(k) for k in wanted}
    os.environ.update(wanted)
    try:
        yield
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def app_for(store):
    """The real app on the bench store (no worker, password login), a logged-in browser and an API v2 client; inside `environment`."""
    from flask import Flask
    from brickwork.app import setup_app
    from tests.web_fixtures import ROOT as TEMPLATE_ROOT, logged_in
    app = Flask('bench', template_folder=str(TEMPLATE_ROOT / 'templates'), static_folder=str(TEMPLATE_ROOT / 'static'))
    setup_app(app)
    app.config.update(TESTING=True, SECRET_KEY='synthetic-session')
    return app, logged_in(app), app.test_client()


VOLATILE = [(re.compile(rb'\b\d+ms\b'), b'#ms'),                                          # the footer's render time
            (re.compile(rb'(\?v=)\d+'), rb'\1#'),                                        # the static files' version (their mtime)
            (re.compile(rb'(name="csrf_token"[^>]*value=")[^"]*'), rb'\1#'), (re.compile(rb'(value=")[^"]*("[^>]*name="csrf_token")'), rb'\1#\2'),
            (re.compile(rb'(csrf[-_]token"?\s*[:=]\s*["\'])[^"\']*'), rb'\1#'), (re.compile(rb'(data-csrf=")[^"]*'), rb'\1#')]


def normalise(body):
    for pattern, replacement in VOLATILE:
        body = pattern.sub(replacement, body)
    return body


def runner(store):
    """A function `run(kind, target) -> bytes` on the store."""
    app, browser, api = app_for(store)
    adapter = None

    def run(kind, target):
        nonlocal adapter
        if kind == 'web':
            response = browser.get(target)
            assert response.status_code == 200, (target, response.status_code)
            return response.data
        if kind == 'api':
            response = api.get('/api/v2' + target, headers={'Authorization': 'Bearer ' + BOOTSTRAP})
            assert response.status_code == 200, (target, response.status_code, response.get_data(as_text=True)[:300])
            return response.data
        if adapter is None:
            from brickwork.core.mcp import Adapter
            from brickwork.core.mcp.client import InProcessClient
            adapter = Adapter(InProcessClient(app, BOOTSTRAP))
        import anyio
        from mcp.shared.memory import create_connected_server_and_client_session
        from brickwork.core.mcp.server import protocol
        name, args = target

        async def call():
            async with create_connected_server_and_client_session(protocol(lambda: adapter)) as session:
                return await session.call_tool(name, args)
        result = anyio.run(call)
        assert not result.isError, (name, result.content[0].text[:300])
        return result.content[0].text.encode()
    return run


def store_at(cache, scale):
    """A fresh working copy of the cached bench store (built on first use)."""
    cache = Path(cache) / f'scale-{scale:g}'
    if not (cache / 'ids.json').exists():
        if cache.exists():
            shutil.rmtree(cache)
        cache.mkdir(parents=True)
        started = time.perf_counter()
        build(cache, scale)
        print(f'built the bench store in {time.perf_counter() - started:.0f} s at {cache}', file=sys.stderr)
    work = Path(tempfile.mkdtemp(prefix='bw-bench-'))
    for name in ('brickwork.db', 'catalogue.db', 'ids.json'):
        shutil.copy(cache / name, work / name)
    return work, json.loads((work / 'ids.json').read_text())


def hashes(store, ids):
    """{path name: sha256 of its normalised output} with the clock frozen."""
    with environment(store), frozen():
        run = runner(store)
        return {name: hashlib.sha256(normalise(run(kind, target))).hexdigest() for name, kind, target in paths(ids)}


def timings(store, ids, runs, only=None):
    with environment(store):
        return _timings(store, ids, runs, only)


def _timings(store, ids, runs, only):
    counter = Statements()
    counter.install()
    started = time.perf_counter()
    run = runner(store)
    start_ms = (time.perf_counter() - started) * 1000
    rows = [('app start (setup_app)', start_ms, start_ms, None, None)]
    for name, kind, target in paths(ids):
        if only and only not in name:
            continue
        body = run(kind, target)                                                     # warm-up
        times = []
        for _ in range(runs):
            counter.count, counter.active = 0, True
            t = time.perf_counter()
            run(kind, target)
            times.append((time.perf_counter() - t) * 1000)
            counter.active = False
        rows.append((name, statistics.median(times), max(times), counter.count, len(body)))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--scale', type=float, default=1.0)
    parser.add_argument('--only', default=None, help='time only the paths whose name contains this text')
    parser.add_argument('--cache', default=os.environ.get('BW_BENCH_CACHE', str(Path(tempfile.gettempdir()) / 'bw-bench-cache')))
    parser.add_argument('--hashes', action='store_true', help='print the output hashes instead of timing')
    parser.add_argument('--json', action='store_true', help='print the table as JSON')
    args = parser.parse_args(argv)
    store, ids = store_at(args.cache, args.scale)
    try:
        if args.hashes:
            print(json.dumps(hashes(store, ids), indent=1, sort_keys=True))
            return 0
        rows = timings(store, ids, args.runs, args.only)
        if args.json:
            print(json.dumps([dict(path=r[0], median_ms=round(r[1], 1), max_ms=round(r[2], 1), sql=r[3], bytes=r[4]) for r in rows], indent=1))
            return 0
        print(f"{'path':<32} {'median ms':>10} {'max ms':>9} {'sql':>7} {'bytes':>9}")
        for name, median, worst, sql, size in rows:
            print(f"{name:<32} {median:>10.1f} {worst:>9.1f} {'' if sql is None else sql:>7} {'' if size is None else size:>9}")
    finally:
        shutil.rmtree(store, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
