"""Prices screen on the 4.0 store (M.8f, issue #110): a light shell, compact records, observations on demand, one projection per request,
and the refresh behind its Update buttons. Items are addressed by id. Invented data."""
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import shutil
import subprocess

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection_prices, planning
from brickwork.core.connect import connect
from brickwork.core.sources.base import now
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)

ROOT = Path(__file__).parents[1]


def records(client):
    data = client.get('/planning/prices/records').get_json()
    return [dict(zip(data['fields'], row)) for row in data['rows']]


def add_price(coll, item, *, colour=None, condition='used', guide='sold', source='bricklink', price='10', observed=None, current=True, slot=None,
              error=None, voided=None, region='eu'):
    """An observation; with `current` also the `price_current` row that makes it the one shown for its key."""
    coll.project(item)
    stamp = observed or now().isoformat()
    identifier = coll.db.execute('''INSERT INTO price_observation(item_id,color_id,condition,guide,slot,region,currency,price,source,observed_at,error,voided_at)
        VALUES(?,?,?,?,?,?,'EUR',?,?,?,?,?)''', (item, colour, condition, guide, slot, region, price, source, stamp, error, voided)).lastrowid
    if current:
        coll.db.execute('''INSERT OR REPLACE INTO price_current(item_id,color_id,condition,guide,slot,region,currency,observation_id) VALUES(?,?,?,?,?,?,'EUR',?)''',
                        (item, colour, condition, guide, slot, region, identifier))
    coll.db.commit()
    return identifier


def test_shell_has_no_rows_and_stays_light(coll, world, client):
    response = client.get('/planning/prices')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    soup = BeautifulSoup(response.data, 'html.parser')
    assert not soup.select('[data-bp-row]') and soup.select_one('[data-bp-rows]')
    assert len(response.data) < 100_000
    scripts = [s['src'] for s in soup.select('script[src]')]
    assert any('bw-prices.js' in s for s in scripts) and not any('bw-collection.js' in s for s in scripts)
    root = soup.select_one('#bw-planning')
    assert root['data-records-url'] == '/planning/prices/records' and root['data-details-url'] == '/planning/prices/details'
    assert root['data-item-base'] == '/collection/item/0' and root['data-editable'] == 'true'
    for name in ('[data-bp-lookup]', '[data-bp-search]', '[data-bp-sort]', '[data-bp-refresh-all]', '[data-bp-chip=stale]', '[data-bp-chip=collection]', '#bp-filters [data-bp-filter=stale]'):
        assert soup.select_one(name), name
    assert soup.select_one('a[href="/manage/jobs"]')
    # The chips are on the page before the records arrive: their later appearance would shift the layout.
    assert not [b for b in soup.select('.bp-visible-chips button') if b.has_attr('hidden')]
    assert '[data-bp-rows][aria-busy=true] { min-height:100dvh; }' in (ROOT / 'static/web/toni/bw-planning.css').read_text()
    assert client.get('/planning/prices?kind=Z').status_code == 400
    assert BeautifulSoup(client.get('/planning/prices?kind=P').data, 'html.parser').select_one('#bw-planning')['data-kind'] == 'P'
    types = [b['data-value'] for b in soup.select('[data-bp-chip=type]')]
    assert types == ['S', 'M', 'P']                                            # only the kinds that have a price (world prices a set, a figure and a part)


def test_records_are_compact_positional_and_complete(coll, world, client):
    add_price(coll, world.gate, price='1234.5', observed=(now() - timedelta(days=1)).isoformat())
    add_price(coll, world.duplo, guide='stock', condition='new', price='7')
    response = client.get('/planning/prices/records')
    assert response.status_code == 200 and response.mimetype == 'application/json' and response.headers['Cache-Control'] == 'no-store'
    data = response.get_json()
    assert data['fields'] == planning.PRICE_FIELDS and data['fields'][-1] == 'item_id' and all(len(row) == len(data['fields']) for row in data['rows'])
    identities = coll.db.execute('SELECT count(*) FROM (SELECT DISTINCT item_id, color_id FROM price_current)').fetchone()[0]
    assert len(data['rows']) == identities
    rows = {r['item_id']: r for r in records(client)}
    assert rows[world.gate]['price'] == '€1,234.50' and not rows[world.gate]['listings'] and rows[world.gate]['age'] and not rows[world.gate]['price_stale']
    assert rows[world.duplo]['price'] == '€7.00' and rows[world.duplo]['listings']
    assert rows[world.gate]['number'] == '1000-2' and rows[world.gate]['type'] == 'S' and rows[world.brick]['colour'] == 'Red'
    # Only display text reaches the browser: no observation lists, no raw numbers.
    assert 'price_records' not in response.get_data(as_text=True) and '1234.5"' not in response.get_data(as_text=True)


def test_records_state_owned_wanted_stale_and_refresh_capability(coll, world, client):
    coll.sql("INSERT OR REPLACE INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',30)")
    old = coll.item('sets', '2070-1')
    add_price(coll, old, observed=(now() - timedelta(days=900)).isoformat())
    add_price(coll, world.mystery, price='3')
    rows = {r['item_id']: r for r in records(client)}
    assert rows[old]['stale'] and rows[old]['price_stale'] and 'stale' not in rows[old]['age'] and rows[old]['owned']
    assert rows[world.keep]['owned'] and not rows[world.keep]['wanted']
    add_price(coll, world.gate, price='4')
    assert {r['item_id']: r for r in records(client)}[world.gate]['wanted']
    assert rows[world.mystery]['unresolved'] and rows[world.mystery]['name'] == 'Mystery thing'      # no Update button for these rows


@pytest.mark.parametrize('age_days, stale', [(29, False), (30, False), (31, True)])
def test_stale_follows_the_source_freshness_in_whole_days(coll, world, read, age_days, stale):
    coll.sql("INSERT OR REPLACE INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',30)")
    item = coll.item('sets', '2070-1')
    add_price(coll, item, observed=(now() - timedelta(days=age_days, hours=1)).isoformat())
    with read() as db:
        row = next(r for r in planning.priced_items(db) if r['item_id'] == item)
    # More than max_age whole days old is stale: 31 days and an hour is 31 whole days, 30 days and an hour is 30.
    assert row['stale'] is stale and row['display_price']['stale'] is stale


def test_display_price_is_what_the_full_history_selection_chooses(coll, world, read):
    """The lean projection must choose what the full-history selection (the details of the same identity) chooses."""
    item = coll.item('parts', '3023')
    red = coll.colour('4')
    add_price(coll, item, colour=red, source='rebrickable', price='99', observed='2026-10-09T10:00:00+00:00')
    add_price(coll, item, colour=red, source='bricklink', price='12', observed='2026-10-08T10:00:00+00:00', current=False)
    add_price(coll, item, colour=red, source='bricklink', price='10', observed='2026-10-01T10:00:00+00:00', current=False)
    add_price(coll, item, colour=red, condition='new', guide='stock', price='20', observed='2026-10-07T10:00:00+00:00')
    add_price(coll, item, colour=red, condition='new', guide='sold', price='21', observed='2026-10-06T10:00:00+00:00', current=False)
    add_price(coll, item, colour=red, condition='new', guide='sold', slot='boxed', price='500', observed='2026-10-10T10:00:00+00:00')
    add_price(coll, item, colour=red, condition='new', guide='sold', price='600', observed='2026-10-11T10:00:00+00:00', error='blocked', current=False)
    add_price(coll, item, colour=red, condition='new', guide='sold', price='700', observed='2026-10-12T10:00:00+00:00', voided='2026-10-13T00:00:00.000Z', current=False)
    only_stock, white = coll.item('parts', '3901'), coll.colour('15')
    add_price(coll, only_stock, colour=white, condition=None, guide='stock', price='5')
    only_retail = coll.item('sets', '2070-1')
    add_price(coll, only_retail, condition='new', guide='retail', source='brickset', price='50')
    from brickwork.core import collection
    with read() as db:
        fast = {(r['item_id'], r['color_id']): r for r in planning.priced_items(db)}
        priorities = collection_prices.priority(db)
        history = collection.decorate_prices(db.execute('''SELECT o.*, i.kind, f.max_age_days FROM price_observation o JOIN item i ON i.id=o.item_id
            LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices' WHERE o.item_id=? AND o.color_id IS ? AND o.voided_at IS NULL
            ORDER BY o.observed_at DESC, o.id DESC''', (item, red)))
        oracle = collection_prices.choose(collection_prices.condition_rows(history, 'part', priorities), 'part', priorities)
        assert len(fast) > 3 and fast[item, red]['display_price']['id'] == oracle['id']
        assert fast[item, red]['display_price']['price'] == '12'                  # priority, then freshest: not rebrickable's 99, not the voided 700
        assert fast[only_retail, None]['display_price'] is None and fast[only_stock, white]['display_price']['price'] == '5'


def details(client, **query):
    return client.get('/planning/prices/details', query_string=query)


def test_details_are_scoped_to_one_identity(coll, world, client):
    item, other = coll.item('parts', '3023'), coll.item('parts', '3001')
    red, white = coll.colour('4'), coll.colour('15')
    add_price(coll, item, colour=red, price='1.5')
    add_price(coll, item, colour=red, price='1.2', observed='2026-09-01T00:00:00+00:00', current=False)
    add_price(coll, item, colour=white, price='8.25')
    add_price(coll, other, colour=red, price='77')
    add_price(coll, item, colour=red, price='99', voided='2026-10-01T00:00:00.000Z', current=False)
    first = details(client, item_id=item, colour=red)
    assert first.status_code == 200 and first.headers['Cache-Control'] == 'no-store'
    text = json.dumps(first.get_json(), ensure_ascii=False)
    assert '€1.50' in text and '€1.20' in text and '€8.25' not in text and '€77' not in text and '€99' not in text
    body = first.get_json()
    assert set(body) == {'context', 'selected', 'conditions', 'groups', 'empty'} and not body['empty']
    assert body['groups'][0]['label'] == 'Market · BrickLink' and len(body['groups'][0]['quotes']) == 2
    assert '€8.25' in json.dumps(details(client, item_id=item, colour=white).get_json(), ensure_ascii=False)
    # Without a colour only colourless observations belong to the identity.
    assert details(client, item_id=item).get_json()['empty'] is True


@pytest.mark.parametrize('query, status', [
    (dict(), 400), (dict(item_id='x'), 400), (dict(item_id='0'), 400), (dict(item_id='1', colour='red'), 400),
    (dict(item_id='999999'), 404), (dict(item_id='1', colour='9' * 30), 400), (dict(item_id='1', colour='-1'), 400), (dict(kind='S', number='1000-1'), 400)])
def test_details_reject_bad_requests(coll, client, query, status):
    assert details(client, **query).status_code == status


def test_new_routes_require_login_and_do_not_write(coll, world, app4, client, read):
    anonymous = app4.test_client()
    for path in ('/planning/prices/records', f'/planning/prices/details?item_id={world.keep}'):
        response = anonymous.get(path)
        assert response.status_code == 401 or (response.status_code == 302 and '/login' in response.location)
    assert anonymous.post('/planning/prices/records').status_code in (302, 401, 405)
    tables = ('event', 'job', 'price_observation', 'setting')
    with read() as db:
        before = [db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables]
    client.get('/planning/prices'); client.get('/planning/prices/records'); details(client, item_id=world.keep)
    with read() as db:
        assert before == [db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables]


def test_a_read_only_database_serves_the_records(world, client, pair):
    pair.chmod(0o444)
    try:
        assert client.get('/planning/prices/records').status_code == 200
    finally:
        pair.chmod(0o644)


def test_statement_counts_stay_flat_as_prices_grow(coll, world, client, monkeypatch):
    statements = []
    from brickwork.core import admin
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
    small = (count('/planning/prices'), count('/planning/prices/records'), count(f'/planning/prices/details?item_id={world.keep}'))
    for i in range(12):
        item = coll.local('set', f'Grow {i}', born_key=f'grow-{i}')
        add_price(coll, item, price=str(i + 1))
        add_price(coll, item, condition='new', price=str(i + 2), observed='2026-10-01T00:00:00+00:00', current=False)
    assert (count('/planning/prices'), count('/planning/prices/records'), count(f'/planning/prices/details?item_id={world.keep}')) == small


def test_refresh_flow_queues_the_item_ids(coll, world, client, read):
    token = csrf(client)
    row = next(r for r in records(client) if not r['unresolved'])
    response = client.post('/planning/action/refresh', json=dict(csrf_token=token, items=[row['item_id']]))
    assert response.status_code == 200 and len(response.get_json()['jobs']) == 1 and 'queued' in response.get_json()['message']
    with read() as db:
        job = db.execute('SELECT kind, item_id, state, via FROM job WHERE id=?', (response.get_json()['jobs'][0],)).fetchone()
        steps = [r[0] for r in db.execute('SELECT name FROM job_step WHERE job_id=?', (response.get_json()['jobs'][0],))]
    assert tuple(job) == ('item', row['item_id'], 'queued', 'app') and steps == ['market_price']
    again = client.post('/planning/action/refresh', json=dict(csrf_token=token, items=[row['item_id']]))
    assert again.status_code == 200 and again.get_json()['jobs'] == []                  # an unfinished job is not doubled
    for bad in ([], ['x'], [[row['item_id'], 'x']], [0], [999999], [world.mystery], list(range(1, 2002))):
        assert client.post('/planning/action/refresh', json=dict(csrf_token=token, items=bad)).status_code == 400, bad
    assert client.post('/planning/action/refresh', json=dict(csrf_token='wrong', items=[row['item_id']])).status_code in (400, 403)


def test_the_planning_screens_and_actions_are_all_ported(world, client):
    assert client.get('/planning/wishlist').status_code == 200 and client.get('/planning/complete-sets').status_code == 200
    token = csrf(client)
    assert client.post('/planning/action/export', json=dict(csrf_token=token, ids=[])).status_code == 400      # a real answer, not "not on the 4.0 store yet"
    assert client.get('/planning/nothing').status_code == 404


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


def test_no_condition_fallback_uses_current_quotes_only(coll, world, read):
    item = coll.item('parts', '3023')
    red = coll.colour('4')
    old = add_price(coll, item, colour=red, condition=None, source='bricklink', price='5', observed=(now() - timedelta(days=150)).isoformat(), current=False)
    current = add_price(coll, item, colour=red, condition=None, source='manual', price='7')
    with read() as db:
        row = next(r for r in planning.priced_items(db) if r['item_id'] == item and r['color_id'] == red)
        assert row['display_price']['id'] == current and row['display_price']['id'] != old
        assert planning.price_details(db, item, red)['selected'].endswith('€7.00')


def test_duplicate_source_prefixes_rank_by_first_occurrence(coll, world, read):
    coll.setting('source_priority', json.dumps({'market_price': {'*': ['bricklink:sold', 'manual', 'bricklink:stock']}}))
    item = coll.item('parts', '3023')
    red = coll.colour('4')
    bricklink = add_price(coll, item, colour=red, source='bricklink', price='3')
    add_price(coll, item, colour=red, source='manual', price='4', guide='sold', condition='new')
    with read() as db:
        row = next(r for r in planning.priced_items(db) if r['item_id'] == item and r['color_id'] == red)
        assert row['display_price']['id'] == bricklink


def test_a_voided_price_is_not_listed_or_chosen(coll, world, client):
    item = coll.item('sets', '2070-1')
    add_price(coll, item, price='9', voided='2026-10-01T00:00:00.000Z')
    assert item not in {r['item_id'] for r in records(client)}
    assert details(client, item_id=item).get_json()['empty'] is True
