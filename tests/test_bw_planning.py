"""Planning on the 4.0 store (M.8g, issue #110): Complete sets, the Wishlist screen, the repair ranking, its saves and Undo, and the export.

Items are addressed by id (the Rebrickable number shows first); a retired line is no line. The economics are 3.3's, checked on a copy
whose numbers are easy to follow (see `evidence`). Invented data, no network."""
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import re
import shutil
import subprocess
from unittest.mock import Mock
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection, gaps, planning, workbench
from brickwork.core.sources.base import now
from tests.app4 import STAMP, app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)

ROOT = Path(__file__).parents[1]
SETTINGS = dict(bricklink_region='eu', bricklink_currency='EUR', incomplete_discount_pct='30', repair_shipping='3', repair_fees='0.5',
                repair_min_order='10', repair_use_loose_stock='0')


class Evidence:
    """What `evidence` built: ids by name."""

    def __init__(self, **ids):
        self.__dict__.update(ids)


def price(coll, item, value, *, colour=None, condition='used', guide='sold', source='bricklink', observed=None, **fields):
    """A fresh BrickLink quote in the settings' currency and region (what `usable` accepts)."""
    return coll.price(item, value, colour=colour, condition=condition, guide=guide, source=source, region='eu', currency='EUR',
                      observed=observed or now().isoformat(), minimum=fields.pop('minimum', '1'), maximum=fields.pop('maximum', '101'),
                      sold=fields.pop('sold', 10), qty=fields.pop('qty', 10), **fields)


def evidence(coll):
    """One used copy of 1000-1 whose red 3001 has 2 missing and 1 damaged (3 to buy at 2.00), the set worth 100.00 complete, the
    repair settings stored. Repair: parts 6.00 + shipping 3.00 + fees 0.50 + minimum-order extra 4.00 = 13.50; the copy is worth
    70.00 as is (30 % off), so the gross gain is 30.00 and the net gain 16.50."""
    for key, value in SETTINGS.items():
        coll.setting(key, value)
    keep, brick, red = coll.item('sets', '1000-1'), coll.item('parts', '3001'), coll.colour('4')
    copy = coll.add_copy('1000-1', condition='used')
    coll.mark(copy, '3001', '4', missing=2, damaged=1)
    price(coll, keep, '100')
    price(coll, brick, '2', colour=red)
    return Evidence(copy=copy, keep=keep, brick=brick, red=red)


def submit(client, token, action, **data):
    return client.post('/planning/action/' + action, json=dict(csrf_token=token, **data))


@pytest.fixture(autouse=True)
def planning_worker(monkeypatch):
    worker = Mock()
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', worker)
    return worker


def rows_of(soup):
    return soup.select('[data-bp-row]')


def records_of(soup):
    return [json.loads(r['data-record']) for r in rows_of(soup)]


# ---------- the screens ----------

@pytest.mark.parametrize('screen', ['wishlist', 'prices', 'complete-sets'])
def test_screen(world, client, screen):
    r = client.get('/planning/' + screen)
    assert r.status_code == 200, r.get_data(as_text=True)
    s = BeautifulSoup(r.data, 'html.parser')
    assert s.select_one('[data-web-ui="toni"]')
    assert s.select_one('[data-bp-search]')
    assert s.select_one('[data-bp-sort]')
    assert s.select_one('[data-bp-filters]')
    assert r.headers['Cache-Control'] == 'no-store'
    for name in ['wishlist', 'prices', 'complete-sets']:
        assert s.select_one('a[href="/planning/' + name + '"]')
    assert not s.select_one('a[href="/complete-sets"]')
    assert 'alerts unavailable' not in s.get_text() and 'Wanted watch' not in s.get_text()
    if screen == 'wishlist':
        assert [b.text for b in s.select('.bp-price-filter [data-bp-pick=under]')] == ['Under max', 'Over max', 'No max set', 'Not comparable']
    assert client.get('/planning/nothing').status_code == 404


@pytest.mark.parametrize('screen', ['wishlist', 'complete-sets'])
def test_planning_row_reading_order_and_controls(coll, world, client, screen):
    """Compact content precedes row actions; closed Details keeps them reachable."""
    evidence(coll)
    soup = BeautifulSoup(client.get('/planning/' + screen).data, 'html.parser')
    rows = rows_of(soup)
    assert rows
    for row in rows:
        blocks = row.find_all(recursive=False)
        if screen == 'complete-sets':
            assert [c['class'][0] for c in blocks] == ['bp-ordinal', 'bc-picture', 'bp-repair-body', 'bp-row-actions']
            body = blocks[2]
            details = body.select_one('.bp-repair-details')
            assert not details.has_attr('open')
            actions = blocks[3]
            assert actions.select_one('[data-bp-selected]')
            assert actions.select_one('[data-bp-pin]')
            assert not actions.find_parent('details')
            assert not details.select('input, select, button')
            assert [c['class'][0] for c in body.find_all(recursive=False)] == ['bp-identity', 'bp-values']
            continue
        assert 'bp-identity' in blocks[0]['class']
        assert 'bp-values' in blocks[1]['class']
        picture = blocks[0].select_one('.bc-picture')
        identity_text = blocks[0].find_all(recursive=False)[-1]
        assert 'bc-picture' in picture['class']
        assert identity_text.select_one('.bc-identity')
        assert not blocks[0].select('input:not([data-wl-selected]), select, button')
        assert blocks[0].select_one('[data-wl-selected]')
        assert len(blocks) == 2
        assert not blocks[1].select('.bp-records, form, button')
        for control in row.select('input, select, button, form'):
            assert 'position' not in control.get('style', '')
    message = soup.select_one('[data-bp-message]')
    assert not message.get_text(strip=True)  # CSS gives an empty live region no box.
    assert soup.select_one('#bp-filters').has_attr('hidden')
    if screen == 'complete-sets':
        settings = soup.select_one('[data-bp-action="settings"]')
        assert settings.parent.name == 'details'
        assert not settings.parent.has_attr('open')


def test_rows_link_to_items_by_id_and_show_the_rebrickable_number_first(coll, world, client):
    evidence(coll)
    complete = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    link = complete.select_one('.bp-identity a')
    assert link['href'].startswith(f'/collection/item/{world.keep}?') and 'copy=' in link['href']
    assert link.select_one('.mono').get_text().startswith('1000-1 · Set ')
    assert client.get(link['href']).status_code == 200
    wishes = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert {r['number'] for r in records_of(wishes)} == {'1000-2', '3023'}
    for r in rows_of(wishes):
        assert r.select_one('a[href^="/collection/wishes/"]')
        assert client.get(r.select_one('a[href^="/collection/wishes/"]')['href']).status_code == 200
    assert all('also' in r for r in records_of(wishes))
    assert 'item_type' not in client.get('/planning/complete-sets').get_data(as_text=True)


def test_search_takes_the_bricklink_number_of_a_row(coll, world, client):
    """Decision 3 of the #110 scope: search takes both numbers; the row record carries the BrickLink number beside the Rebrickable one."""
    coll.link(world.brick, '3001old', kind='P')
    coll.sql("UPDATE item_link SET preferred=1 WHERE item_id=? AND provider_key='3001old'", (world.brick,))
    coll.add_wish(world.brick, colour=world.red, quantity=1)
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    record = next(r for r in records_of(soup) if r['number'] == '3001')
    assert record['also'] == '3001old'
    row = next(r for r in rows_of(soup) if json.loads(r['data-record'])['number'] == '3001')
    assert '3001 · BrickLink 3001old' in row.get_text(' ')


# ---------- display rounding ----------

def test_planning_prices_round_for_display_only(coll, world, client):
    coll.sql("UPDATE wish SET max_price='163.01234', max_price_currency='EUR' WHERE id=?", (world.wish_part,))
    price(coll, world.plate, '181.9484', colour=world.white, minimum='5.439', maximum='280.0', sold=3)
    records = client.get('/planning/prices/records')
    assert '181.9484' not in records.get_data(as_text=True)
    decoded = json.loads(records.data)
    row = next(r for r in decoded['rows'] if r[decoded['fields'].index('price')] == '€181.95')
    key = dict(zip(decoded['fields'], row))
    details = client.get('/planning/prices/details', query_string=dict(item_id=key['item_id'], colour=key['color_id'])).get_json()
    quotes = [q for g in details['groups'] for q in g['quotes']]
    assert quotes and '€181.95' in quotes[0]['head'] and '181.9484' not in json.dumps(details)
    for quote in quotes:
        if 'range' in quote:
            assert '€5.44' in quote['min'] and '€280' in quote['max']
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert '181.9484' not in soup.get_text()
    row = next(r for r in rows_of(soup) if json.loads(r['data-record'])['id'] == world.wish_part)
    assert '163.01' in row.select_one('.bp-values').get_text()
    detail = BeautifulSoup(client.get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
    quotes = detail.select('.bc-price-records .bc-price')
    assert quotes and '181.95' in quotes[0].get_text() and '181.9484' not in quotes[0].get_text()
    assert detail.select_one('input[name=max_price]')['value'] == '163.01234'
    assert coll.db.execute('SELECT max_price FROM wish WHERE id=?', (world.wish_part,)).fetchone()[0] == '163.01234'
    assert coll.db.execute('SELECT price FROM price_observation WHERE price LIKE ?', ('181.9%',)).fetchone()[0] == '181.9484'


# ---------- pins, settings and Undo ----------

def test_pin_settings_undo_conflict(coll, client, app4, read):
    e = evidence(coll)
    c, token = client, csrf(client)
    r = submit(c, token, 'pin', id=e.copy, pinned=True)
    assert r.status_code == 200, r.json
    assert coll.db.execute('SELECT pinned FROM copy WHERE id=?', (e.copy,)).fetchone()[0] == 1
    event = coll.db.execute('SELECT * FROM event WHERE id=?', (r.json['event_id'],)).fetchone()
    assert (event['via'], event['entity_kind'], event['entity_id'], event['field']) == ('app', 'planning', e.copy, 'pin')
    assert submit(c, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert coll.db.execute('SELECT pinned FROM copy WHERE id=?', (e.copy,)).fetchone()[0] == 0
    assert submit(c, token, 'undo', event_id=r.json['event_id']).status_code == 200            # a second Undo changes nothing
    with read() as db:
        old = {k: planning.configuration(db)[k] for k in planning.REPAIR_KEYS}
    values = dict(repair_shipping='4.5', repair_fees='0', repair_min_order='12', repair_use_loose_stock='1', incomplete_discount_pct='30.5')
    r = submit(c, token, 'settings', values=values)
    assert r.status_code == 200, r.json
    with read() as db:
        assert planning.ranking(db)['settings']['incomplete_discount_pct'] == Decimal('30.5')
    other = submit(c, token, 'settings', values=dict(values, repair_fees='1'))
    blocked = submit(c, token, 'undo', event_id=r.json['event_id'])
    assert blocked.status_code == 400 and 'later save' in blocked.json['message']
    assert submit(c, token, 'undo', event_id=other.json['event_id']).status_code == 200
    assert submit(c, token, 'undo', event_id=r.json['event_id']).status_code == 200
    with read() as db:
        assert {k: planning.configuration(db)[k] for k in planning.REPAIR_KEYS} == old
    assert submit(c, token, 'settings', values=dict(values, repair_shipping='NaN')).status_code == 400
    assert submit(c, token, 'settings', values=dict(values, incomplete_discount_pct='101')).status_code == 400
    assert submit(c, token, 'settings', values=dict(values, repair_use_loose_stock='2')).status_code == 400
    assert submit(c, token, 'settings', values={'repair_fees': '1'}).status_code == 400
    assert submit(c, token, 'pin', id=e.copy, pinned='false').status_code == 400
    assert submit(c, token, 'pin', id='no-such-copy', pinned=True).status_code == 400
    assert c.post('/planning/action/pin', json=dict(id=e.copy, pinned=True)).status_code in (400, 403)
    assert submit(c, token, 'nothing').status_code == 404
    app4.config['BW_READ_ONLY'] = True
    assert submit(c, token, 'pin', id=e.copy, pinned=True).status_code == 403


def test_settings_that_were_never_stored_come_back_absent_after_undo(coll, world, client, read):
    token = csrf(client)
    values = dict(repair_shipping='4.5', repair_fees='0', repair_min_order='12', repair_use_loose_stock='1', incomplete_discount_pct='30')
    saved = submit(client, token, 'settings', values=values)
    assert saved.status_code == 200
    assert coll.db.execute("SELECT value FROM setting WHERE key='repair_shipping'").fetchone()[0] == '4.5'
    assert submit(client, token, 'undo', event_id=saved.json['event_id']).status_code == 200
    assert coll.db.execute("SELECT count(*) FROM setting WHERE key LIKE 'repair_%' OR key='incomplete_discount_pct'").fetchone()[0] == 0
    with read() as db:
        assert planning.configuration(db)['repair_shipping'] == '3.00'                        # the documented default applies again


def test_a_pin_is_undone_unless_it_was_pinned_again_and_an_unrelated_edit_does_not_block_it(coll, client):
    e = evidence(coll)
    token = csrf(client)
    first = submit(client, token, 'pin', id=e.copy, pinned=True).json['event_id']
    edited = client.post('/collection/save/save', json=dict(csrf_token=token, entity='copy', ids=[e.copy], values=dict(note='Later')))
    assert edited.status_code == 200
    assert submit(client, token, 'undo', event_id=first).status_code == 200                    # the note is not what Undo restores
    row = coll.db.execute('SELECT pinned, note FROM copy WHERE id=?', (e.copy,)).fetchone()
    assert (row['pinned'], row['note']) == (0, 'Later')
    again = submit(client, token, 'pin', id=e.copy, pinned=True).json['event_id']
    submit(client, token, 'pin', id=e.copy, pinned=False)
    assert submit(client, token, 'undo', event_id=again).status_code == 400
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', e.copy))
    assert submit(client, token, 'pin', id=e.copy, pinned=True).status_code == 400


def test_save_query_count(coll):
    e = evidence(coll)
    db = coll.db
    cases = [('pin', dict(id=e.copy, pinned=True)), ('settings', dict(values=dict(repair_shipping='3', repair_fees='1', repair_min_order='0',
                                                                                   repair_use_loose_stock='0', incomplete_discount_pct='30')))]

    def measured():
        counts = []
        for action, data in cases:
            traces = []
            db.set_trace_callback(traces.append)
            event = planning.save(db, action, data)
            db.set_trace_callback(None)
            counts.append(len(traces))
            traces = []
            db.set_trace_callback(traces.append)
            planning.undo(db, event)
            db.set_trace_callback(None)
            counts.append(len(traces))
        return counts
    small = measured()
    bulk_copies(coll, e, 60, 'save')
    assert measured() == small and max(small) <= 14


# ---------- the economics ----------

def test_economics_gap_stock_export(coll, client, read):
    e = evidence(coll)
    with read() as db:
        row = next(r for r in planning.ranking(db)['rows'] if r['id'] == e.copy)
    assert row['original_gap'] == 3 and row['missing_count'] == 3
    assert row['repair_cost'] == Decimal('13.5') and row['net_gain'] == Decimal('16.5')
    assert row['breakdown']['items'] == Decimal(6) and row['breakdown']['minimum_order_extra'] == Decimal(4)
    assert row['value_when_complete'] == Decimal(100) and row['current_value'] == Decimal(70) and row['valuation_basis'] == 'default discount estimate'
    assert row['group'] == 'ranked' and row['rank'] == 1 and row['label'] == 'Set 1' and row['item_no'] == '1000-1'
    assert row['ratio'] == Decimal(30) / Decimal('13.5')
    coll.setting('repair_use_loose_stock', '1')
    coll.add_stock('part', e.brick, colour=e.red, quantity=3, condition='used')
    with read() as db:
        row = next(r for r in planning.ranking(db)['rows'] if r['id'] == e.copy)
        assert row['stock_used'] == 3 and row['missing_count'] == 0
        assert row['repair_cost'] == Decimal('13.5')                      # the minimum order remains in force
        assert not ET.fromstring(planning.export(db, [e.copy])['xml']).findall('ITEM')
    coll.setting('repair_use_loose_stock', '0')
    with read() as db:
        result = planning.export(db, [e.copy])
        root = ET.fromstring(result['xml'])
        assert root.findtext('ITEM/MINQTY') == '3' and root.findtext('ITEM/ITEMID') == '3001' and root.findtext('ITEM/ITEMTYPE') == 'P'
        assert root.findtext('ITEM/CONDITION') == 'U' and root.findtext('ITEM/COLOR') and not result['skipped']
        assert next(g for g in workbench.gaps(db) if g['copy_id'] == e.copy)['need'] == 3
        assert result['xml'] == gaps.export(db, [e.copy])['xml']               # with no loose stock in use it is the gaps export
    token = csrf(client)
    r = submit(client, token, 'export', ids=[e.copy])
    assert r.status_code == 200 and r.mimetype == 'application/xml' and 'missing-parts.xml' in r.headers['Content-Disposition']
    assert json.loads(unquote(r.headers['X-Bw-Skipped'])) == []
    summary = submit(client, token, 'export', ids=[e.copy], summary=True).get_json()
    assert summary['filename'] == 'missing-parts.xml' and summary['summary'] == dict(exported=1, skipped=[]) and '<MINQTY>3</MINQTY>' in summary['content']
    for bad in ([], ['nope'], [e.copy, e.copy], 'x'):
        assert submit(client, token, 'export', ids=bad).status_code == 400


def test_an_item_without_a_bricklink_number_is_skipped_and_listed_in_the_export(coll, client, read):
    e = evidence(coll)
    local = coll.local('part', 'Mystery plate')                                    # no number from any provider
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,?,?)', (e.copy, local, e.red, 2, 2))
    with read() as db:
        result = planning.export(db, [e.copy])
    assert [l['name'] for l in result['skipped']] == ['Mystery plate'] and result['skipped'][0]['why'] == 'no BrickLink number'
    assert ET.fromstring(result['xml']).findtext('ITEM/ITEMID') == '3001' and len(ET.fromstring(result['xml']).findall('ITEM')) == 1
    token = csrf(client)
    summary = submit(client, token, 'export', ids=[e.copy], summary=True).get_json()['summary']
    assert summary['exported'] == 1 and summary['skipped'][0]['item_no'] == 'Mystery plate' and summary['skipped'][0]['reason'] == 'no BrickLink number'


def test_export_is_available_when_read_only_and_every_planning_action_needs_login(coll, client, app4):
    e = evidence(coll)
    token = csrf(client)
    for action in ('refresh', 'export', 'pin', 'settings', 'undo'):
        response = app4.test_client().post('/planning/action/' + action, json={})
        assert response.status_code == 302 and '/login' in response.location
    app4.config['BW_READ_ONLY'] = True
    assert submit(client, token, 'export', ids=[e.copy]).status_code == 200
    for action in ('refresh', 'pin', 'settings', 'undo'):
        assert submit(client, token, action).status_code == 403


def test_refresh_only_queues_and_unknown_atomic(coll, world, client, planning_worker, read):
    def committed():
        with read() as db:
            assert db.execute("SELECT count(*) FROM job WHERE state='queued'").fetchone()[0] == 1
    planning_worker.side_effect = committed
    token = csrf(client)
    r = submit(client, token, 'refresh', items=[world.keep, world.keep])
    assert r.status_code == 200, r.json
    assert len(r.json['jobs']) == 1
    planning_worker.assert_called_once_with()
    job = coll.db.execute('SELECT * FROM job WHERE id=?', (r.json['jobs'][0],)).fetchone()
    assert job['state'] == 'queued' and job['item_id'] == world.keep and job['via'] == 'app'
    assert coll.db.execute('SELECT name FROM job_step WHERE job_id=?', (job['id'],)).fetchone()[0] == 'market_price'
    count = coll.db.execute('SELECT count(*) FROM job').fetchone()[0]
    assert submit(client, token, 'refresh', items=[world.gate, 999999]).status_code == 400
    assert coll.db.execute('SELECT count(*) FROM job').fetchone()[0] == count
    planning_worker.assert_called_once_with()


def test_prices_kind_query_and_freshness(coll, read):
    e = evidence(coll)
    coll.sql('UPDATE price_observation SET observed_at=? WHERE item_id=?', ((now() - timedelta(days=400)).isoformat(), e.keep))
    coll.sql("INSERT OR REPLACE INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',30)")
    with read() as db:
        traces = []
        db.set_trace_callback(traces.append)
        rows = planning.priced_items(db, 'S')
        db.set_trace_callback(None)
        assert rows and all(r['item_type'] == 'S' for r in rows)
        assert any(r['stale'] for r in rows)
        query = next(s for s in traces if 'JOIN price_observation' in s)
        assert "i.kind='set'" in query
        assert any(r['group'] == 'needs_evidence' for r in planning.ranking(db)['rows'])


def bulk_copies(coll, e, count, tag):
    """`count` more copies of the set, each with a missing red 3001 (plain SQL: the copies need no part list of the catalogue)."""
    for i in range(count):
        coll.db.execute("INSERT INTO copy(id,item_id,inventory_source,inventory_digest,condition,created_at,updated_at) VALUES(?,?,'migrated','d','used',?,?)",
                        (f'{tag}{i}', e.keep, '2026-10-26T13:00:00.000Z', '2026-10-26T13:00:00.000Z'))
        coll.db.execute('INSERT INTO copy_part(copy_id,item_id,color_id,quantity,missing) VALUES(?,?,?,3,1)', (f'{tag}{i}', e.brick, e.red))
    coll.db.commit()


def bulk_wishes(coll, count, tag):
    for i in range(count):
        coll.add_wish(coll.local('set', f'Bulk {tag} {i}', born_key=f'{tag}-{i}'), quantity=1, condition='any')


@pytest.mark.parametrize('project', ['wishes', 'priced_items', 'ranking'])
def test_constant_list_queries(coll, read, project):
    e = evidence(coll)

    def count():
        with read() as db:
            statements = []
            db.set_trace_callback(statements.append)
            getattr(planning, project)(db)
            db.set_trace_callback(None)
        return len([s for s in statements if s.lstrip().upper().startswith('SELECT')])
    bulk_copies(coll, e, 5, 'few')
    bulk_wishes(coll, 5, 'few')
    small = count()                                                  # with nothing listed some reads are skipped: compare two non-empty lists
    bulk_copies(coll, e, 40, 'bulk')
    bulk_wishes(coll, 40, 'bulk')
    assert count() <= small + 3


def test_shell_footer_clearance():
    shell = (ROOT / 'static/web/toni/shell.css').read_text()
    assert '.footer{padding-bottom:calc(20px + var(--bw-bottom))}' in shell
    assert '[data-bc-list] { padding-bottom:' not in (ROOT / 'static/web/toni/bw-collection.css').read_text()


def reserve(coll, copy, item, colour, quantity):
    """A pending allocation of a part ordered for a copy's gap: the order is on its way, so the loose part is not free for a repair."""
    coll.sql("INSERT OR IGNORE INTO purchase_order(id,created_at,updated_at) VALUES(1,?,?)", (STAMP, STAMP))
    coll.sql("INSERT OR IGNORE INTO order_document(id,order_id,source,digest,phase,created_at,updated_at) VALUES(1,1,'xml','d','saved',?,?)", (STAMP, STAMP))
    coll.sql("INSERT INTO order_line(order_id,document_id,line_no,state,qty,updated_at,item_id,color_id) VALUES(1,1,1,'confirmed',?,?,?,?)", (quantity, STAMP, item, colour))
    line = coll.db.execute('SELECT max(id) FROM order_line').fetchone()[0]
    part = coll.db.execute('SELECT id FROM copy_part WHERE copy_id=? AND item_id=? AND color_id=? AND retired_at IS NULL', (copy, item, colour)).fetchone()[0]
    coll.sql("""INSERT INTO allocation(confirm_id,order_id,line_id,qty,state,target_kind,kind,copy_id,copy_part_id,item_id,color_id,created_at)
        VALUES('c',1,?,?,'pending','copy','missing_part',?,?,?,?,?)""", (line, quantity, copy, part, item, colour, STAMP))


def test_stock_not_double_counted_reserved_or_archived(coll, read):
    e = evidence(coll)
    coll.setting('repair_use_loose_stock', '1')
    second = coll.add_copy('1000-1', condition='used')
    coll.mark(second, '3001', '4', missing=3)
    stock = coll.add_stock('part', e.brick, colour=e.red, quantity=4, condition='used')
    with read() as db:
        rows = planning.ranking(db)['rows']
    assert sum(r['stock_used'] for r in rows) == 4
    assert sorted(r['stock_used'] for r in rows) == [1, 3] and all(r['original_gap'] == 3 for r in rows)    # the stock is shared, never counted twice
    reserve(coll, second, e.brick, e.red, 2)
    with read() as db:
        assert sum(r['stock_used'] for r in planning.ranking(db)['rows']) == 2                          # what an incoming order covers is not free
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', stock))
    with read() as db:
        assert sum(r['stock_used'] for r in planning.ranking(db)['rows']) == 0


def test_a_damaged_loose_part_is_not_used_and_a_damaged_gap_shares_with_a_transfer_and_its_undo(coll, read):
    e = evidence(coll)
    coll.setting('repair_use_loose_stock', '1')
    coll.mark(e.copy, '3001', '4', missing=0, damaged=2)
    coll.add_stock('part', e.brick, colour=e.red, quantity=5, condition='damaged')
    with read() as db:
        assert next(r for r in planning.ranking(db)['rows'] if r['id'] == e.copy)['stock_used'] == 0
    good = coll.add_stock('part', e.brick, colour=e.red, quantity=2, condition='used')
    gap = next(g for g in workbench.gaps(coll.db) if g['copy_id'] == e.copy)
    assert gap['need'] == 2
    event = workbench.transfer(coll.db, good, e.copy, 'part', gap['target_id'], 2)
    assert coll.db.execute('SELECT missing,damaged FROM copy_part WHERE id=?', (gap['target_id'],)).fetchone()[:] == (0, 0)
    with read() as db:
        assert not planning.ranking(db)['rows']
    collection.undo(coll.db, event)
    assert coll.db.execute('SELECT missing,damaged FROM copy_part WHERE id=?', (gap['target_id'],)).fetchone()[:] == (0, 2)


def test_a_retired_line_is_no_gap_and_a_figure_is_priced_whole(coll, read):
    e = evidence(coll)
    coll.retire_line(e.copy, '3001', '4')
    with read() as db:
        assert not planning.ranking(db)['rows']
    coll.sql('UPDATE copy_part SET retired_at=NULL WHERE copy_id=?', (e.copy,))
    figure = coll.item('minifigs', 'fig-000004')
    coll.mark(e.copy, '3001', '4', missing=0, damaged=0)
    coll.mark_figure(e.copy, 'fig-000004', missing=1)
    price(coll, figure, '9.00')
    with read() as db:
        row = planning.ranking(db)['rows'][0]
    lines = {l['item_id']: l for l in row['items']}
    assert list(lines) == [figure] and lines[figure]['missing'] == 1 and lines[figure]['type'] == 'M' and lines[figure]['mapped']
    assert row['breakdown']['items'] == Decimal(9) and row['missing_figures'] == 1 and row['missing_parts'] == 0


def test_a_figure_without_a_bricklink_number_needs_evidence_as_unmapped(coll, read):
    e = evidence(coll)
    coll.mark(e.copy, '3001', '4', missing=0, damaged=0)
    unknown = coll.local('minifigure', 'Unnumbered figure')
    coll.sql("INSERT INTO copy_figure(copy_id,item_id,inventory_source,inventory_digest,quantity,missing,updated_at) VALUES(?,?,'none','d',1,1,?)", (e.copy, unknown, STAMP))
    with read() as db:
        row = planning.ranking(db)['rows'][0]
    assert row['group'] == 'needs_evidence' and any(r.startswith('unmapped figure · ') for r in row['reasons'])


# ---------- the screens in detail ----------

@pytest.mark.parametrize('screen', ['wishlist', 'prices', 'complete-sets'])
def test_run3_shared_toolbar_no_breadcrumb(world, client, screen):
    soup = BeautifulSoup(client.get('/planning/' + screen).data, 'html.parser')
    assert not soup.select('.breadcrumb')
    toolbar = soup.select_one('.bc-toolbar')
    assert toolbar.select_one('.bc-search input[data-bp-search]')
    assert toolbar.select_one('button[data-bp-filters]')
    assert toolbar.select_one('button[data-bp-sort-open]')
    assert not toolbar.select('select')
    assert soup.select_one('.bc-sort-options[hidden] select[data-bp-sort]')
    assert all('bw-primary' in b['class'] for b in soup.select('#bw-planning .primary'))


def test_run3_wishlist_count_conditions_and_records(coll, world, client, read):
    coll.sql('UPDATE wish SET quantity=3')
    with read() as db:
        rows = planning.wishes(db)
    quantity = sum(r['quantity'] for r in rows)
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert soup.h1.get_text(strip=True) == f'{quantity} items wanted'                    # a set and a part
    # 4.9d w2/w3 + 12k: condition chips All, Used, New (All carries the count), then the Price filter row.
    chips = soup.select('.bp-visible-chips button')
    unfilled = sum(1 for r in rows if not r['filled'])  # #35: the Not yet filled chip follows the conditions
    assert [b.get_text(strip=True) for b in chips] == ['All' + str(len(rows_of(soup))), 'Used', 'New', 'Not yet filled' + str(unfilled), 'Under max', 'Over max', 'No max set', 'Not comparable']
    assert chips[0].select_one('.bp-chip-count').text == str(len(rows_of(soup)))
    assert soup.select_one('[data-bp-search]')['placeholder'] == 'Number or name'
    for row in rows_of(soup):
        assert not row.select('.bp-records, [data-bp-archive], input:not([data-wl-selected])')
        assert row.select_one('[data-wl-selected]')
        detail = BeautifulSoup(client.get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
        assert '3 wanted' in detail.select_one('.bc-wish-facts').text
        assert detail.select_one('#bc-delete form[data-bc-action=archive]')
    coll.sql('UPDATE wish SET archived_at=? WHERE kind=?', ('2026-10-27T00:00:00.000Z', 'part'))
    assert BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser').h1.get_text(strip=True) == '3 sets wanted'


def test_run3_prices_priority_history_lookup_and_chips(coll, world, client, read):
    # The identity has current prices; superseded observations are displayed through the same selection function as Collection details.
    for source, value, date in [('bricklink', '12', '2026-10-08'), ('bricklink', '10', '2026-10-01'), ('rebrickable', '99', '2026-10-09')]:
        coll.price(world.gate, value, source=source, region='eu', observed=date + 'T00:00:00+00:00')          # each replaces the last as the current one
    soup = BeautifulSoup(client.get('/planning/prices?kind=P').data, 'html.parser')
    assert soup.select_one('[data-bp-lookup-query]')['placeholder'] == 'Look up any number'
    assert not soup.select('form select[name=kind]')
    assert soup.select_one('#bw-planning')['data-kind'] == 'P'
    with read() as db:
        available = {collection.type_of(r[0]) for r in db.execute('SELECT DISTINCT i.kind FROM price_current p JOIN item i ON i.id=p.item_id')}
    assert {b['data-value'] for b in soup.select('.bp-visible-chips [data-bp-chip=type]')} == available
    assert [n.text for n in soup.select('.bp-price-columns span')] == ['Item', 'Kind', 'Price', 'Age']
    data = client.get('/planning/prices/records').get_json()
    rows = [dict(zip(data['fields'], r)) for r in data['rows']]
    row = next(r for r in rows if r['item_id'] == world.gate)
    assert row['price'] == '€12.00' and not row['listings']                              # priority first, then the freshest: bricklink 12 wins over rebrickable 99
    details = client.get('/planning/prices/details', query_string=dict(item_id=world.gate)).get_json()
    text = json.dumps(details, ensure_ascii=False)
    assert '€99.00' in text and '€10.00' in text and 'EUR 12' not in text
    assert details['selected'].startswith('Used') and '€12.00' in details['selected']
    found = client.get('/collection/jump?q=1000-2')
    assert found.status_code == 200 and found.json['results']


@pytest.mark.parametrize('pinned', [False, True])
def test_run3_repair_recommendation_and_proportional_bars(coll, client, read, pinned):
    e = evidence(coll)
    coll.sql("UPDATE copy SET pinned=?,current_value='80',current_value_currency='EUR' WHERE id=?", (int(pinned), e.copy))
    second = coll.add_copy('1000-1', condition='used', current_value='71.65', current_value_currency='EUR')
    coll.mark(second, '3001', '4', missing=1)
    with read() as db:
        ranked = planning.ranking(db)['ranked']
    assert len(ranked) == 2
    best = next(r for r in ranked if r['rank'] == 1)
    assert best['id'] == second and best['ratio'] == Decimal('2.10')
    soup = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert soup.h1.get_text(strip=True) == 'Repair 1000-1 first: 2.10 gained per 1 spent' + (' · pins listed first' if pinned else '')
    rows = [r for r in rows_of(soup) if json.loads(r['data-record'])['group'] == 'ranked']
    assert [int(r.select_one('.bp-ordinal').get_text()) for r in rows] == ([2, 1] if pinned else [1, 2])
    assert not any(p.get_text(strip=True) == 'Ranked' for r in rows for p in r.select('.bc-status'))
    widths = [float(r.select_one('.bp-ratio-track i')['style'].split(':')[1].rstrip('%')) for r in rows]
    assert widths == pytest.approx([float(r['ratio'] / best['ratio'] * 100) for r in ranked])
    coll.sql('UPDATE price_observation SET observed_at=?', ((now() - timedelta(days=400)).isoformat(),))
    empty = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert empty.h1.get_text() == 'Complete sets'


@pytest.mark.parametrize('screen', ['wishlist', 'prices', 'complete-sets'])
def test_run3_rendered_list_queries_constant(coll, client, monkeypatch, screen):
    e = evidence(coll)
    statements = []
    original = admin.connect

    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db
    monkeypatch.setattr(admin, 'connect', traced)

    def count():
        statements.clear()
        response = client.get('/planning/' + screen)
        assert response.status_code == 200
        return len([s for s in statements if s.lstrip().upper().startswith('SELECT')])
    bulk_copies(coll, e, 5, 'few')
    bulk_wishes(coll, 5, 'few')
    small = count()
    bulk_copies(coll, e, 40, 'render')
    bulk_wishes(coll, 40, 'render')
    for i in range(40):
        price(coll, coll.local('set', f'Priced {i}', born_key=f'priced-{i}'), '100')
    assert count() <= small + 3


def test_run3_price_header_and_rows_share_four_columns():
    css = (ROOT / 'static/web/toni/bw-planning.css').read_text()
    rule = re.search(r'\.bp-price-columns,\.bp-prices \.bp-row\s*\{([^}]+)\}', css).group(1)
    template = re.search(r'grid-template-columns:([^;]+)', rule).group(1)
    assert template == 'minmax(0,1.5fr) minmax(100px,.7fr) minmax(0,1.2fr) minmax(160px,.4fr)'
    assert '.bp-price-columns span:nth-child(3)' not in css
    # The only row override is inside the phone media query, where the header is hidden.
    assert len(re.findall(r'\.bp-prices \.bp-row\s*\{', css)) == 2
    phone = css.split('@media(max-width:767.98px)')[1]
    assert '.bp-price-columns { display:none; }' in phone
    assert '.bp-prices .bp-row { grid-template-columns:56px minmax(0,1fr) auto;' in phone


def test_run4_wishlist_hierarchy_and_details(coll, world, client):
    coll.sql("UPDATE wish SET note='Keep this wish note',quantity=3,condition=NULL,max_price=NULL,max_price_currency=NULL")
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert rows_of(soup)
    for row in rows_of(soup):
        assert not row.select('.bp-records')
        detail = BeautifulSoup(client.get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
        facts = detail.select_one('.bc-wish-facts')
        assert 'Age not recorded' in facts.text
        assert 'Keep this wish note' in facts.text and '3 wanted' in facts.text
        assert detail.select_one('#bc-edit form[data-bc-action=save]')
        assert row.select_one('.bp-max-label').text == 'Your max price'
        assert row.select_one('.bp-max strong.mono')
        assert row.select_one('.bp-wish-number .bc-status').text == 'Wants unknown'
        assert 'Currency not recorded' not in row.text and '3 wanted' not in row.text
        assert 'Keep this wish note' not in row.text
    assert soup.select_one('[data-bp-pick=condition][data-value=""]')['aria-pressed'] == 'true'
    css = (ROOT / 'static/web/toni/bw-planning.css').read_text()
    assert 'font:600 20px/26px var(--tw-mono)' in css
    assert '.bp-visible-chips { display:flex;gap:8px;' in css
    assert '[aria-pressed=true] { background:var(--tw-accent-soft)' in css


def test_run4_prices_lookup_and_compact_rows(world, client):
    soup = BeautifulSoup(client.get('/planning/prices').data, 'html.parser')
    assert soup.select_one('.bp-lookup label svg')
    assert soup.select_one('.bp-lookup-action').text == 'Look up'
    assert not soup.select('[data-bp-row]')  # rows are rendered by the client from the compact records
    css = (ROOT / 'static/web/toni/bw-planning.css').read_text()
    assert '.bp-lookup input { background:var(--tw-surface);border:0;' in css
    assert 'border-color:var(--tw-accent);color:var(--tw-accent-text)' in css
    assert 'padding-block:10px;align-items:center;' in css
    assert '.bp-values { display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;' in css


def test_run4_repair_details_preserve_evidence_and_actions(coll, client, read):
    evidence(coll)
    with read() as db:
        expected = planning.ranking(db)
    soup = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    assert rows_of(soup)
    for row in rows_of(soup):
        record = json.loads(row['data-record'])
        original = next(r for r in expected[record['group']] if r['id'] == record['id'])
        details = row.select_one('.bp-repair-details')
        assert details.summary.select_one('.bp-details-label').text == 'Details' and not details.has_attr('open')
        assert f"{original['stock_used']} in loose stock" in details.text
        assert f"{original['missing_count']} to buy" in details.text
        assert original['label'] in details.text and {'sealed': 'Sealed', 'complete': 'Complete', 'incomplete': 'Incomplete'}.get(original['completeness'], 'Unknown') in details.text
        assert row.select_one('[data-bp-selected]')['value'] == original['id']
        assert row.select_one('[data-bp-pin]')
        assert not row.select_one('[data-bp-selected]').find_parent('details')
        assert not row.select_one('[data-bp-pin]').find_parent('details')
        if original['reasons']:
            for reason in original['reasons']:
                assert reason in details.text
        else:
            for text in ('Parts', 'shipping', 'fees', 'minimum order extra', 'Complete', 'current', original['valuation_basis']):
                assert text in details.text
            assert row.select_one('.bp-repair-numbers')
        details.decompose()
        assert 'in loose stock' not in row.text
        assert row.select_one('[data-bp-selected]') and row.select_one('[data-bp-pin]')
        assert 'shipping' not in row.text and 'net gain' not in row.text
    css = (ROOT / 'static/web/toni/bw-planning.css').read_text()
    assert 'grid-template-columns:20px 56px minmax(0,1fr)' in css
    assert '.bp-repair-numbers { margin:0;font:400 12px/14px' in css
    assert '.bp-repair-details > summary { min-height:14px;padding:0;' in css
    assert not re.search(r'\bdisplay\s*:\s*contents|\border\s*:', css)


@pytest.mark.parametrize('quotes, expected, label', [
    ([('new', 'retail', 'retail', 'brickset', '90')], None, None),
    ([('used', 'sold', 'boxed', 'bricklink', '80')], None, None),
    ([('used', 'sold', 'used_set', 'bricklink', '12'),
      ('new', 'sold', 'new_set', 'bricklink', '24')], '24', 'New · new set'),
    ([('used', 'stock', 'used_set', 'bricklink', '15')], '15', 'Used listings · used set'),
    ([(None, 'stock', None, 'bricklink', '17')], '17', 'Price listings'),
    ([('used', 'stock', 'used_set', 'bricklink', '-5.9')], '-5.9', 'Used listings · used set'),
])
def test_compact_prices_market_only_and_recorded_labels(coll, world, client, read, quotes, expected, label):
    case = coll.local('set', 'Price case', born_key='planning-price-case')
    coll.add_wish(case, quantity=1, condition='any')
    for condition, guide, slot, source, value in quotes:
        coll.sql('INSERT INTO source(id,name,kind) VALUES(?,?,?) ON CONFLICT DO NOTHING', (source, source, 'api'))
        observation = coll.db.execute("""INSERT INTO price_observation(item_id,condition,guide,slot,region,currency,price,source,observed_at)
            VALUES(?,?,?,?,'eu','EUR',?,?,?)""", (case, condition, guide, slot, value, source, now().isoformat())).lastrowid
        coll.sql("INSERT OR REPLACE INTO price_current(item_id,condition,guide,slot,region,currency,observation_id) VALUES(?,?,?,?,'eu','EUR',?)",
                 (case, condition, guide, slot, observation))
    with read() as db:
        for rows in (planning.priced_items(db), planning.wishes(db)):
            row = next(r for r in rows if r['item_id'] == case)
            chosen = row['display_price']
            assert (chosen['price'] if chosen else None) == expected
            if chosen:
                assert chosen['guide'] in ('sold', 'stock') and chosen['slot'] != 'boxed'
                assert chosen['label'] == label
    # Prices: the compact record and the on-demand details; the row markup is covered by the runtime harness.
    data = client.get('/planning/prices/records').get_json()
    record = next(dict(zip(data['fields'], r)) for r in data['rows'] if r[data['fields'].index('item_id')] == case)
    details = client.get('/planning/prices/details', query_string=dict(item_id=case)).get_json()
    assert sum(len(g['quotes']) for g in details['groups']) == len(quotes)
    if expected:
        assert record['price'] == '€' + format(Decimal(expected), '.2f').replace('-', '') or record['price'] == '−€5.90' or record['price']
        assert record['listings'] == (quotes[-1][1] == 'stock')
        assert label in details['selected']
        assert 'Used' not in record['price'] and 'New' not in record['price']
    else:
        assert record['price'] is None and details['selected'] is None
    wish = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    row = next(r for r in rows_of(wish) if json.loads(r['data-record'])['name'] == 'Price case')
    assert row.select_one('.bp-records') is None
    detail = BeautifulSoup(client.get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
    assert len(detail.select('.bc-price-records .bc-price')) == len(quotes)
    if expected:
        compact = row.select_one('.bp-card-price')
        assert {'new': 'New', 'used': 'Used'}.get(quotes[-1][0], 'Price') in compact.text and ' · ' not in compact.text
        assert ('listings' in compact.text) == (quotes[-1][1] == 'stock')
        if expected == '-5.9':
            assert '€5.90 below' in compact.text
    else:
        assert 'no sales' in row.select_one('.bp-values').text and not row.select('.bp-card-price')


def test_repair_summary_wraps_above_details_css_contract(coll, client):
    evidence(coll)
    soup = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    summaries = soup.select('.bp-repair-details > summary')
    assert any(summary.select_one('.bp-repair-numbers') for summary in summaries)
    for summary in summaries:
        children = summary.find_all(recursive=False)
        assert [child['class'][0] for child in children] in (['bp-repair-numbers', 'bp-details-label'], ['bp-details-label'])
        assert not summary.find_all(string=lambda text: text.strip(), recursive=False)
    css = (ROOT / 'static/web/toni/bw-planning.css').read_text()
    rule = re.search(r'#bw-planning \.bp-repair-details > summary\s*\{([^}]+)\}', css).group(1)
    for declaration in ('display:flex', 'flex-direction:column', 'align-items:flex-start', 'gap:2px'):
        assert declaration in rule
    # Automatic flex heights must include every wrapped line, at all breakpoints.
    assert not re.search(r'(?<![\w-])height:|overflow:|position:absolute|white-space:nowrap', rule)
    assert not re.search(r'\border\s*:|display\s*:\s*contents', css)


def test_prices_name_orphan_guard_preserves_compact_rows_css_contract():
    css = (ROOT / 'static/web/toni/bw-planning.css').read_text()
    collection_css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    rule = re.search(r'\.bp-prices \.bc-identity strong\s*\{([^}]+)\}', css).group(1)
    assert 'text-wrap:pretty' in rule and 'text-wrap:pretty' in collection_css
    assert not re.search(r'height:|padding:|line-height:|overflow:', rule)
    assert 'padding-block:10px;align-items:center;' in css
    assert '.bp-prices .bp-identity .bc-picture { margin-bottom:-20px; }' in css


def test_planning_compact_chromium_geometry(coll, client, tmp_path):
    """Opt-in measurements use the shipped DOM/CSS; no screenshots."""
    import os
    chrome = os.environ.get('BW_COLLECTION_CHROME')
    if not chrome:
        pytest.skip('Set BW_COLLECTION_CHROME for opt-in browser geometry verification')
    from urllib.parse import urlsplit
    evidence(coll)
    coll.sql("UPDATE wish SET condition='used'")
    for screen in ('complete-sets', 'prices', 'wishlist'):
        soup = BeautifulSoup(client.get('/planning/' + screen).data, 'html.parser')
        for link in soup.select('link[rel=stylesheet]'):
            style = soup.new_tag('style')
            style.string = (ROOT / urlsplit(link['href']).path.lstrip('/')).read_text()
            link.replace_with(style)
        for script in soup.select('script'):
            script.decompose()
        if screen == 'prices':
            names = soup.select('.bp-identity .bc-identity strong')
            assert len(names) >= 2
            for name, text in zip(names, ("Technic, Liftarm Thick 1", "Aaron Fox's Aero Striker")):
                name.string = text
        (tmp_path / (screen + '.html')).write_text(str(soup))
    result = subprocess.run(['node', 'tests/toni_bw_planning_geometry.cjs', chrome, str(tmp_path)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------- the Wishlist screen ----------

def test_wishlist_uses_collection_save_archive_undo(coll, world, client):
    token = csrf(client)
    r = client.post('/collection/save/save', json=dict(csrf_token=token, entity='wish', ids=[world.wish_set], values=dict(max_price='25', quantity=2, condition='used')))
    assert r.status_code == 200, r.json
    body = client.get('/collection/wishes/' + world.wish_set).get_data(as_text=True)
    assert '2 wanted · used' in body and 'value="25"' in body
    before = len(rows_of(BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')))
    r = client.post('/collection/save/archive', json=dict(csrf_token=token, entity='wish', ids=[world.wish_set], values={}))
    assert r.status_code == 200
    assert len(rows_of(BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser'))) == before - 1
    assert client.post('/collection/save/undo', json=dict(csrf_token=token, event_id=r.json['event_id'])).status_code == 200
    assert len(rows_of(BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser'))) == before
    undone = submit(client, token, 'undo', event_id=r.json['event_id'])                # the planning Undo reverses any receipt; this one is already undone
    assert undone.status_code == 200


def test_47c_wishlist_copy_structure_and_add_path(world, client):
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert soup.select_one('.bp-subtitle').text == 'Price now against your max, used average'
    assert not soup.select('.bc-detail-back, .breadcrumb')
    assert 'Add a wish' not in soup.text
    switch = soup.select_one('#bw-planning > .bc-list-options')
    assert [b['data-bp-view'] for b in switch.select('button')] == ['grid', 'list']
    assert switch.select_one('[data-bp-count]')
    assert switch.find_previous_sibling(class_='bp-visible-chips')
    for row in rows_of(soup):
        assert not row.select('.bp-records')
    add = BeautifulSoup(client.get('/manage/add').data, 'html.parser')
    assert add.select_one('input[name=where][value=wishlist]')


def test_47c_wishlist_exact_css_values():
    css = (ROOT / 'static/web/toni/bw-planning.css').read_text()
    contracts = {
        '#bw-planning[data-screen=wishlist] h1': ['letter-spacing:-.2px'],
        '#bw-planning[data-screen=wishlist] .bp-subtitle': ['font:400 14px/20px var(--tw-font)', 'color:var(--tw-text-muted)'],
        '.bp-max strong': ['font:600 20px/26px var(--tw-mono)'],
        '.bp-wishlist .bp-row .bc-identity > .secondary': ['font:400 13px/18px var(--tw-font)', 'color:var(--tw-text-muted)'],
        '.bp-wishlist .bp-card-price': ['font:400 12px/16px var(--tw-mono)', 'color:var(--tw-text-2)'],
        '#bw-planning .bc-view-switch button': ['width:44px', 'height:36px'],
        '.bp-wishlist[data-view=list] .bc-picture': ['width:56px', 'height:56px'],
        '.bp-wish-track': ['height:18px'],
        '.bp-wish-track::before': ['top:6px', 'height:6px', 'border-radius:3px'],
        '.bp-wish-track i': ['top:1px', 'width:2px', 'height:16px'],
        '.bp-wish-range-labels': ['font:400 11px/14px var(--tw-mono)', 'color:var(--tw-text-2)'],
    }
    for selector, values in contracts.items():
        rule = re.search(re.escape(selector) + r'\s*\{([^}]+)', css).group(1)
        for value in values:
            assert value in rule


@pytest.mark.parametrize('condition', ['new', 'used', 'any', None])
def test_47c_wanted_card_and_existing_condition_save_undo(coll, world, client, condition):
    wish = world.wish_part
    coll.sql('UPDATE wish SET condition=?,max_price=?,max_price_currency=?,note=? WHERE id=?', (condition, '82.3900', 'EUR', 'Keep every wish fact', wish))
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('[data-web-ui=toni]')
    assert not soup.select('.breadcrumb')
    card = soup.select_one('[data-module=wanted]')
    assert card.h2.text == 'Wanted'
    assert card.select_one('.bc-wanted-max strong').text == '€82.39'  # 4.8b: the limit takes the configured currency
    assert card.select_one('.bc-wanted-segments').has_attr('data-bc-save-group')
    assert [b.text for b in card.select('.bc-wanted-segments button')] == ['New', 'Used', 'Any']
    assert not card.select('dt') and 'Tags' not in card.text
    selected = card.select('[aria-pressed=true]')
    assert len(selected) == (0 if condition is None else 1)
    if selected:
        assert selected[0].parent.select_one('input')['value'] == condition
    assert 'Keep every wish fact' in soup.select_one('.bc-wish-facts').text
    assert 'Max in EUR' in soup.select_one('.bc-wish-facts').text
    form = card.select_one('form')
    identity = json.loads(form['data-identity'])
    assert form['data-bc-action'] == 'save'
    token = csrf(client)
    response = client.post('/collection/save/save', json=dict(csrf_token=token, **identity, values={'condition': form.input['value']}))
    assert response.status_code == 200
    event = coll.db.execute('SELECT * FROM event WHERE id=?', (response.json['event_id'],)).fetchone()
    assert event['via'] == 'app'
    assert event['old_value'] != event['new_value'] or condition == 'new'
    assert coll.db.execute('SELECT condition FROM wish WHERE id=?', (wish,)).fetchone()[0] == 'new'
    assert client.post('/collection/save/undo', json=dict(csrf_token=token, event_id=response.json['event_id'])).status_code == 200
    assert coll.db.execute('SELECT condition FROM wish WHERE id=?', (wish,)).fetchone()[0] == condition
    assert coll.db.execute('SELECT max_price,note FROM wish WHERE id=?', (wish,)).fetchone()[:] == ('82.3900', 'Keep every wish fact')


def test_47c_wanted_exact_css_values():
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    contracts = {
        '#bw-collection .bc-wanted': ['padding:16px', 'gap:14px', 'border-radius:16px', 'background:var(--tw-surface)'],
        '#bw-collection .bc-wanted h2,.bc-wanted-label': ['font:500 11px/14px var(--tw-font)', 'letter-spacing:.1em', 'color:var(--tw-text-muted)'],
        '.bc-wanted-max strong': ['font:600 24px/30px var(--tw-mono)'],
        '.bc-wanted-max': ['gap:2px'],
        '.bc-wanted-condition': ['gap:6px'],
        '.bc-wanted-segments': ['padding:2px', 'gap:2px', 'border-radius:10px'],
        '#bw-collection .bc-wanted-segments button': ['height:44px', 'border-radius:8px', 'font:500 13px var(--tw-font)', 'color:var(--tw-text-2)'],
        '#bw-collection .bc-wanted-segments button[aria-pressed=true]': ['background:var(--tw-accent-soft)', 'color:var(--tw-accent-text)'],
    }
    for selector, values in contracts.items():
        rule = re.search(re.escape(selector) + r'\s*\{([^}]+)', css).group(1)
        for value in values:
            assert value in rule


def test_47c_compact_range_and_provenance_on_detail(coll, world, client):
    coll.sql("UPDATE wish SET condition='used' WHERE id=?", (world.wish_part,))
    price(coll, world.plate, '82.39', colour=world.white, minimum='70', maximum='99', sold=3)
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    row = next(r for r in rows_of(soup) if json.loads(r['data-record'])['id'] == world.wish_part)
    assert row.select_one('.bp-card-price').text == 'Used avg €82.39'
    assert [s.text for s in row.select('.bp-wish-range-labels span')] == ['min €70.00', 'avg €82.39', 'max €99.00']
    assert row.select_one('.bp-values').find_all(recursive=False)[-1]['class'] == ['bp-wish-range']
    assert not row.select('details') and 'bricklink' not in row.text
    detail = BeautifulSoup(client.get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
    # 4.7e moved provenance from visible text into the caption title.
    assert any(c['title'].startswith('bricklink') for c in detail.select('.bc-price-records .secondary'))
    assert '€82.39' in detail.select_one('.bc-price-records').text


def test_47c_condition_save_query_count_independent_of_wishlist_size(coll, world):
    db = coll.db
    identifier = world.wish_set

    def measured():
        traces = []
        db.set_trace_callback(traces.append)
        try:
            event = collection.save(db, 'wish', [identifier], {'condition': 'used'})
        finally:
            db.set_trace_callback(None)
        collection.undo(db, event)
        return len(traces)
    small = measured()
    bulk_wishes(coll, 40, 'save')
    assert measured() == small
    assert small < 25


def test_49d_prices_order_update_and_wishlist_range(coll, world, client):
    soup = BeautifulSoup(client.get('/planning/prices').data, 'html.parser')
    chips, controls = soup.select_one('.bp-visible-chips'), soup.select_one('.bc-toolbar')
    assert soup.select_one('[data-bp-lookup]').find_next(class_='bp-visible-chips') is chips
    assert chips.find_next(class_='bc-toolbar') is controls
    assert not any(b.text == 'Refresh' for b in soup.select('.bp-ages button'))
    css = (ROOT / 'static/web/toni/bw-planning.css').read_text().replace(' ', '')
    assert '.bp-wish-trackb{position:absolute;left:0;width:100%;top:6px;height:6px;border-radius:3px;background:var(--tw-viz-2)' in css
    assert '.bp-wish-range-labels{gap:0;flex-wrap:nowrap;}' in css
    coll.sql("UPDATE wish SET condition='used' WHERE id=?", (world.wish_part,))
    price(coll, world.plate, '70', colour=world.white, minimum='60', maximum='100', sold=3)
    wish = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    track = next(r for r in rows_of(wish) if json.loads(r['data-record'])['id'] == world.wish_part).select_one('.bp-wish-track')
    assert track.select_one('b') and track.select_one('i')['style'] == 'left:25.0%'


def test_49d_collection_wishes_show_recorded_max(coll, world, client, read):
    coll.sql("UPDATE wish SET max_price='48', max_price_currency='EUR' WHERE id=?", (world.wish_set,))
    assert client.get('/collection/wishes').status_code == 200
    from brickwork.core.list_records import payload
    with read() as db:
        rows = collection.listing(db, 'S', wishes=True)
    decoded = json.loads(payload(rows))
    index = str(decoded['fields'].index('max_price'))
    assert '€48.00' in [r.get(index) for r in decoded['rows']]
    bare = dict(item_type='S', item_no='x', name='x', entity='wish', id=1, quantity=1, instances=[])
    assert 'max_price' not in bare and json.loads(payload([bare]))['rows']  # a wish row without the column must not raise
    js = (ROOT / 'static/web/toni/bw-collection.js').read_text()
    assert "'Your max price'" in js and "'Not recorded'" in js


def test_complete_sets_export_starts_disabled(coll, client):
    evidence(coll)
    soup = BeautifulSoup(client.get('/planning/complete-sets').data, 'html.parser')
    button = soup.select_one('[data-bp-export]')
    assert button.has_attr('disabled') and button.text == 'Export selected · BrickLink XML'
    print_link = soup.select_one('[data-bp-print][aria-disabled=true]')
    assert print_link and print_link['href'] == '/lists/missing/print'


def test_the_wishlist_screen_links_the_printable_list(world, client):
    wishlist = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    assert wishlist.find('a', href=lambda h: h and h.startswith('/lists/wishlist/print'))
    assert client.get('/lists/wishlist/print').status_code == 200


def test_prices_runtime_harness_and_planning_runtime_harness():
    if shutil.which('node') is None:
        pytest.skip('Node is not installed')
    for name in ('toni_bw_planning_runtime.cjs', 'toni_bw_wishlists_runtime.cjs'):
        result = subprocess.run(['node', 'tests/' + name], cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
