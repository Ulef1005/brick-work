"""Prices screen: a light shell, compact records, observations on demand, one projection per request."""
import json
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection, planning
from brickwork.core.sources.base import now
from tests.test_bw_collection import bw, token
from tests.importer.test_importer import legacy
from tests.test_bw_admin import reset_shell_metadata_after_test
from tests.web_fixtures import app, apps, logged_in

ROOT = Path(__file__).parents[1]


def records(client):
    data = client.get('/planning/prices/records').get_json()
    return [dict(zip(data['fields'], row)) for row in data['rows']]


def add_price(db, kind, number, *, colour=None, condition='U', guide='sold', source='bricklink', price='10', observed=None, current=True, slot=None, error=None):
    db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES(?,?,?)", (kind, number, 'Item ' + number))
    identifier = db.execute("""INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,slot,region,currency,price,source,observed_at,error)
        VALUES(?,?,?,?,?,?,'eu','EUR',?,?,?,?)""", (kind, number, colour, condition, guide, slot, price, source, observed or now().isoformat(), error)).lastrowid
    if current:
        db.execute("""INSERT OR REPLACE INTO price_current(item_type,item_no,color_id,condition,guide,slot,region,currency,observation_id)
            VALUES(?,?,?,?,?,?,'eu','EUR',?)""", (kind, number, colour, condition, guide, slot, identifier))
    return identifier


def test_shell_has_no_rows_and_stays_light(app, bw):
    client = logged_in(app)
    response = client.get('/planning/prices')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    soup = BeautifulSoup(response.data, 'html.parser')
    assert not soup.select('[data-bp-row]') and soup.select_one('[data-bp-rows]')
    assert len(response.data) < 100_000
    scripts = [s['src'] for s in soup.select('script[src]')]
    assert any('bw-prices.js' in s for s in scripts) and not any('bw-collection.js' in s for s in scripts)
    root = soup.select_one('#bw-planning')
    assert root['data-records-url'] == '/planning/prices/records' and root['data-details-url'] == '/planning/prices/details'
    assert root['data-item-base'].endswith('/TYPE/NUMBER') and root['data-editable'] == 'true'
    for name in ('[data-bp-lookup]', '[data-bp-search]', '[data-bp-sort]', '[data-bp-refresh-all]', '[data-bp-chip=stale]', '[data-bp-chip=collection]', '#bp-filters [data-bp-filter=stale]'):
        assert soup.select_one(name), name
    assert soup.select_one('a[href="/manage/jobs"]')
    # The chips are on the page before the records arrive: their later appearance would shift the layout.
    assert not [b for b in soup.select('.bp-visible-chips button') if b.has_attr('hidden')]
    assert '[data-bp-rows][aria-busy=true] { min-height:100dvh; }' in (ROOT / 'static/web/toni/bw-planning.css').read_text()
    assert client.get('/planning/prices?kind=Z').status_code == 400
    assert BeautifulSoup(client.get('/planning/prices?kind=P').data, 'html.parser').select_one('#bw-planning')['data-kind'] == 'P'


def test_records_are_compact_positional_and_complete(app, bw):
    client = logged_in(app)
    with admin.database(bw) as db, db:
        add_price(db, 'S', 'rec-1', price='1234.5', observed=(now() - timedelta(days=1)).isoformat())
        add_price(db, 'S', 'rec-2', guide='stock', condition='N', price='7')
    response = client.get('/planning/prices/records')
    assert response.status_code == 200 and response.mimetype == 'application/json' and response.headers['Cache-Control'] == 'no-store'
    data = response.get_json()
    assert data['fields'] == planning.PRICE_FIELDS and all(len(row) == len(data['fields']) for row in data['rows'])
    with admin.database(bw, read_only=True) as db:
        identities = db.execute('SELECT count(*) FROM (SELECT DISTINCT item_type,item_no,color_id FROM price_current)').fetchone()[0]
    assert len(data['rows']) == identities
    rows = {r['number']: r for r in records(client)}
    assert rows['rec-1']['price'] == '€1,234.50' and not rows['rec-1']['listings'] and rows['rec-1']['age'] and not rows['rec-1']['price_stale']
    assert rows['rec-2']['price'] == '€7.00' and rows['rec-2']['listings']
    # Only display text reaches the browser: no observation lists, no raw numbers.
    assert 'price_records' not in response.get_data(as_text=True) and '1234.5"' not in response.get_data(as_text=True)


def test_records_state_owned_wanted_stale_and_refresh_capability(app, bw):
    with admin.database(bw) as db, db:
        add_price(db, 'S', 'old-set', observed=(now() - timedelta(days=900)).isoformat())
        add_price(db, '?', 'odd-1')
        db.execute("INSERT INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',30) ON CONFLICT(source,kind) DO UPDATE SET max_age_days=30")
        owned = db.execute("SELECT set_no FROM copies WHERE item_type='S' AND archived_at IS NULL LIMIT 1").fetchone()[0]
        add_price(db, 'S', owned, price='3')
        wish = db.execute("SELECT item_type,item_no FROM wishlist WHERE archived_at IS NULL LIMIT 1").fetchone()
        add_price(db, wish[0], wish[1], price='4')
    rows = {r['number']: r for r in records(logged_in(app))}
    assert rows['old-set']['stale'] and rows['old-set']['price_stale'] and 'stale' not in rows['old-set']['age']
    assert rows[owned]['owned']
    assert rows[wish[1]]['wanted']
    assert rows['odd-1']['unresolved']  # these rows get no Update button: the client offers refresh to resolved rows only


@pytest.mark.parametrize('age_days, stale', [(29, False), (30, False), (31, True)])
def test_stale_follows_the_source_freshness_in_whole_days(bw, age_days, stale):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',30) ON CONFLICT(source,kind) DO UPDATE SET max_age_days=30")
        add_price(db, 'S', 'edge', observed=(now() - timedelta(days=age_days, hours=1)).isoformat())
        row = next(r for r in planning.priced_items(db) if r['item_no'] == 'edge')
    # More than max_age whole days old is stale: 31 days and an hour is 31 whole days, 30 days and an hour is 30.
    assert row['stale'] is stale and row['display_price']['stale'] is stale


def test_display_price_matches_the_all_observation_selection(bw):
    """The lean projection must choose what the full-history selection chooses."""
    with admin.database(bw) as db, db:
        add_price(db, 'S', 'sel', source='rebrickable', price='99', observed='2026-10-09T10:00:00+00:00')
        add_price(db, 'S', 'sel', source='bricklink', price='12', observed='2026-10-08T10:00:00+00:00', current=False)
        add_price(db, 'S', 'sel', source='bricklink', price='10', observed='2026-10-01T10:00:00+00:00', current=False)
        add_price(db, 'S', 'sel', condition='N', guide='stock', price='20', observed='2026-10-07T10:00:00+00:00')
        add_price(db, 'S', 'sel', condition='N', guide='sold', price='21', observed='2026-10-06T10:00:00+00:00', current=False)
        add_price(db, 'S', 'sel', condition='N', guide='sold', slot='boxed', price='500', observed='2026-10-10T10:00:00+00:00')
        add_price(db, 'S', 'sel', condition='N', guide='sold', price='600', observed='2026-10-11T10:00:00+00:00', error='blocked', current=False)
        add_price(db, 'S', 'only-stock', condition=None, guide='stock', price='5')
        add_price(db, 'S', 'only-retail', condition='N', guide='retail', source='brickset', price='50')
        fast = {(r['item_type'], r['item_no'], r['color_id']): r for r in planning.priced_items(db)}
        market = collection.prices(db)  # the old projection's fallback reads the current market quotes
        slow_input = [dict(item_type=k[0], item_no=k[1], color_id=k[2], prices=market[k]) for k in fast]
        slow = {(r['item_type'], r['item_no'], r['color_id']): r for r in planning.display_prices(db, slow_input)}
    assert len(fast) > 3
    ident = lambda p: (p or {}).get('id') or (p or {}).get('observation_id')  # the old fallback returns a price_current row
    mismatches = [(k, ident(fast[k]['display_price']), ident(slow[k]['display_price'])) for k in fast
                  if ident(fast[k]['display_price']) != ident(slow[k]['display_price'])]
    assert not mismatches
    assert fast['S', 'sel', None]['display_price']['price'] == '12'  # priority, then freshest: not rebrickable's 99
    assert fast['S', 'only-retail', None]['display_price'] is None and fast['S', 'only-stock', None]['display_price']['price'] == '5'


def details(client, **query):
    return client.get('/planning/prices/details', query_string=query)


def test_details_are_scoped_to_one_identity(app, bw):
    client = logged_in(app)
    with admin.database(bw) as db, db:
        db.execute('INSERT OR IGNORE INTO colors(color_id,name) VALUES(11,?),(5,?)', ('Black', 'Red'))
        add_price(db, 'P', 'det-1', colour=11, price='1.5')
        add_price(db, 'P', 'det-1', colour=11, price='1.2', observed='2026-09-01T00:00:00+00:00', current=False)
        add_price(db, 'P', 'det-1', colour=5, price='8.25')
        add_price(db, 'P', 'det-2', colour=11, price='77')
    black = details(client, kind='P', number='det-1', colour=11)
    assert black.status_code == 200 and black.headers['Cache-Control'] == 'no-store'
    text = json.dumps(black.get_json(), ensure_ascii=False)
    assert '€1.50' in text and '€1.20' in text and '€8.25' not in text and '€77' not in text
    body = black.get_json()
    assert set(body) == {'context', 'selected', 'conditions', 'groups', 'empty'} and not body['empty']
    assert body['groups'][0]['label'] == 'Market · BrickLink' and len(body['groups'][0]['quotes']) == 2
    assert '€8.25' in json.dumps(details(client, kind='P', number='det-1', colour=5).get_json(), ensure_ascii=False)
    # Without a colour only colourless observations belong to the identity.
    assert details(client, kind='P', number='det-1').get_json()['empty'] is True


@pytest.mark.parametrize('query, status', [
    (dict(), 400), (dict(kind='P'), 400), (dict(kind='Z', number='1'), 400), (dict(kind='P', number='1', colour='red'), 400),
    (dict(kind='P', number='missing'), 404), (dict(kind='P', number='1', colour='9'*30), 400), (dict(kind='P', number='1', colour='-1'), 400)])
def test_details_reject_bad_requests(app, bw, query, status):
    assert details(logged_in(app), **query).status_code == status


def test_new_routes_require_login_and_do_not_write(app, bw):
    anonymous = app.test_client()
    for path in ('/planning/prices/records', '/planning/prices/details?kind=S&number=x'):
        response = anonymous.get(path)
        assert response.status_code == 401 or (response.status_code == 302 and '/login' in response.location)
    assert anonymous.post('/planning/prices/records').status_code in (302, 401, 405)
    client = logged_in(app)
    with admin.database(bw, read_only=True) as db:
        before = [db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('events', 'jobs', 'price_observations', 'settings')]
    client.get('/planning/prices'); client.get('/planning/prices/records'); details(client, kind='S', number='new-set')
    with admin.database(bw, read_only=True) as db:
        assert before == [db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('events', 'jobs', 'price_observations', 'settings')]


def test_read_only_database_serves_the_records(app, bw, monkeypatch):
    bw.chmod(0o444)
    try:
        assert logged_in(app).get('/planning/prices/records').status_code == 200
    finally:
        bw.chmod(0o644)


def test_statement_counts_stay_flat_as_prices_grow(app, bw, monkeypatch):
    client = logged_in(app)
    statements = []
    original = admin.connect

    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db
    monkeypatch.setattr(admin, 'connect', traced)

    def count(path):
        statements.clear()
        assert client.get(path).status_code == 200
        return len([s for s in statements if s.lstrip().upper().startswith('SELECT')])
    small = (count('/planning/prices'), count('/planning/prices/records'), count('/planning/prices/details?kind=S&number=new-set'))
    with admin.database(bw) as db, db:
        for i in range(60):
            add_price(db, 'S', f'grow-{i}', price=str(i + 1))
            add_price(db, 'S', f'grow-{i}', condition='N', price=str(i + 2), observed='2026-10-01T00:00:00+00:00', current=False)
    assert (count('/planning/prices'), count('/planning/prices/records'), count('/planning/prices/details?kind=S&number=new-set')) == small


def test_refresh_flow_still_queues_the_row_identity(app, bw):
    client = logged_in(app)
    csrf = token(client)
    row = next(r for r in records(client) if not r['unresolved'] and r['type'] != '?')
    response = client.post('/planning/action/refresh', json=dict(csrf_token=csrf, items=[[row['type'], row['number']]]))
    assert response.status_code == 200 and response.get_json()['jobs']
    assert 'queued' in response.get_json()['message']
    assert client.post('/planning/action/refresh', json=dict(csrf_token=csrf, items=[['?', 'x']])).status_code == 400
    assert client.post('/planning/action/refresh', json=dict(csrf_token='wrong', items=[[row['type'], row['number']]])).status_code in (400, 403)


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is not installed')
def test_prices_runtime_harness():
    result = subprocess.run(['node', 'tests/toni_bw_prices_runtime.cjs'], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'prices runtime ok' in result.stdout


def test_prices_assets_are_precached_and_pager_css_is_shared():
    worker = (ROOT / 'static/web/toni/sw.js').read_text()
    assert '/static/web/toni/bw-prices.js' in worker
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    assert ':is(#bw-collection,#bw-planning,#bw-workbench) .bc-pager' in css and ':is(#bw-collection,#bw-planning,#bw-workbench) .bc-pager .bc-page-number[aria-current=page]' in css


def test_no_condition_fallback_uses_current_quotes_only(bw):
    with admin.database(bw) as db, db:
        old = add_price(db, 'P', 'nocond', condition=None, source='bricklink', price='5',
                        observed=(now() - timedelta(days=150)).isoformat(), current=False)
        current = add_price(db, 'P', 'nocond', condition=None, source='manual', price='7')
    with admin.database(bw) as db:
        row = next(r for r in planning.priced_items(db) if r['item_no'] == 'nocond')
        assert row['display_price']['id'] == current and row['display_price']['id'] != old
        assert planning.price_details(db, 'P', 'nocond')['selected'].endswith('€7.00') or '7' in planning.price_details(db, 'P', 'nocond')['selected']


def test_duplicate_source_prefixes_rank_by_first_occurrence(bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT OR REPLACE INTO settings VALUES('source_priority',?)",
                   (json.dumps({'market_price': {'*': ['bricklink:sold', 'manual', 'bricklink:stock']}}),))
        bl = add_price(db, 'P', 'dup', source='bricklink', price='3')
        add_price(db, 'P', 'dup', source='manual', price='4', guide='sold', condition='N')
    with admin.database(bw) as db:
        row = next(r for r in planning.priced_items(db) if r['item_no'] == 'dup')
        assert row['display_price']['id'] == bl
