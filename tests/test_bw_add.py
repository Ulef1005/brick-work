"""Add on the 4.0 store (M.8c, issue #110): search, review, confirm, undo and the jobs an Add queues. Invented data, no network.

The fixture catalogue is `tests/app4.py`'s rich one: sets 1000-1 (two figures, a spare), 1000-2 and 2070-1 (two versions), parts 3001 and
3023, the figure fig-000004 (BrickLink M syn-fig-0004), a gear item. A BrickLink key is a fake one and BrickLink's reply a fake transport."""
from contextlib import closing
import io
import json
import sqlite3
import shutil

from bs4 import BeautifulSoup
from flask import Flask
import pytest

from brickwork.app import setup_app
from brickwork.core import add, drainer, pipeline
from brickwork.core.connect import connect
from brickwork.store4 import bricklink_api, copies, jobs, rebrickable_api
from tests.app4 import BROWSER_PASSWORD, app4, client, coll, pair, read, world  # noqa: F401 (fixtures)
from tests.store4_mint_fixtures import build_catalogue
from tests.test_store4_bricklink_subsets import entry, reply
from tests.web_fixtures import ROOT, logged_in


@pytest.fixture
def csrf(client):
    assert client.get('/manage/add').status_code == 200
    with client.session_transaction() as session:
        return session['bw_add_csrf']


@pytest.fixture
def key(monkeypatch):
    for name in bricklink_api.KEY_ENVS:
        monkeypatch.setenv(name, 'x')


def review(client, csrf, text='1000-1', **data):
    return client.post('/manage/add/review', json=dict(csrf_token=csrf, type=data.pop('type', 'set'), where=data.pop('where', 'owned'),
                                                        mode=data.pop('mode', 'paste'), text=text, **data))


def confirm(client, csrf, proposal, **edits):
    items = json.loads(json.dumps(proposal['items']))
    for item in items:
        item.update(edits)
    return client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=items))


def undo(client, csrf, batch):
    return client.post('/manage/add/undo', json=dict(csrf_token=csrf, batch=batch))


def counts(read):
    with read() as db:
        return {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('item', 'copy', 'stock', 'wish', 'event', 'job')}


def app_on(tmp_path, monkeypatch, name):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', BROWSER_PASSWORD)
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
    app = Flask(name, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config.update(TESTING=True, SECRET_KEY='synthetic-session')
    return logged_in(app)


# ---------- the page and the search ----------

def test_the_page_and_searches_write_nothing(world, client, csrf, read):
    html = client.get('/manage/add')
    soup = BeautifulSoup(html.get_data(as_text=True), 'html.parser')
    text = soup.get_text()
    assert 'Nothing is saved before you confirm' in text and html.headers['Cache-Control'] == 'no-store'
    assert [i['value'] for i in soup.select('input[name=type]')] == list(add.KIND_NAMES)
    assert 'Photo' in text and 'Keep photo' in text                              # Brickognize's photo mode (M.8h)
    assert soup.select_one('input[name=type][value=set]').has_attr('checked')
    assert BeautifulSoup(client.get('/manage/add?type=P&where=loose').get_data(as_text=True), 'html.parser').select_one('input[name=type][value=part]').has_attr('checked')
    before = counts(read)
    for kind in add.KIND_NAMES:
        result = client.get('/manage/add/search', query_string={'type': kind, 'sort': 'name'})
        assert result.status_code == 200 and all(r['kind'] == kind for r in result.json['items'])
    assert client.get('/manage/add/search', query_string={'type': 'gear'}).json['count'] == 1
    assert review(client, csrf).status_code == 200
    assert counts(read) == before


def test_search_takes_both_numbers_names_sizes_and_local_items(world, client, coll):
    def found(kind, q, sort='number'):
        result = client.get('/manage/add/search', query_string={'type': kind, 'q': q, 'sort': sort}).json
        return [r['number'] for r in result['items']], result['count']
    assert found('part', '3001') == (['3001'], 1)
    assert found('part', '310.3stk01') == (['003402'], 1)                        # a BrickLink number finds the Rebrickable-born part
    assert found('part', 'brick 2 x 4') == (['3001'], 1)                         # a size is its size key in any order, the words name prefixes
    assert found('part', '4x2') == (['3001'], 1)
    assert found('part', 'x2')[1] == 3                                           # a partial size: any part with that dimension (2x4, 2x2x4, 1x2)
    assert found('set', 'castle') == (['1000-1', '1000-2'], 2)
    assert found('set', 'castle', 'name')[0] == ['1000-2', '1000-1']             # Gate before Keep
    assert found('part', 'only on bricklink') == (['x999'], 1)                   # a local BrickLink-born item is found by its name
    assert found('part', 'x999') == (['x999'], 1) and found('set', 'zzzz') == ([], 0)
    gear = client.get('/manage/add/search', query_string={'type': 'gear', 'q': 'mystery'}).json['items']
    assert (gear[0]['name'], gear[0]['number'], gear[0]['unidentified'], gear[0]['label']) == ('Mystery thing', None, True, 'Mystery thing')
    row = client.get('/manage/add/search', query_string={'type': 'set', 'q': '1000-1'}).json['items'][0]
    assert (row['owned'], row['wished'], row['to_check'], row['type_name'], row['label']) == (2, False, False, 'Set', '1000-1')
    part = client.get('/manage/add/search', query_string={'type': 'part', 'q': '973c27h01'}).json['items'][0]
    assert (part['number'], part['also'], part['label']) == ('973c27h01', '973c001', '973c27h01 · BrickLink 973c001')
    assert client.get('/manage/add/search', query_string={'type': 'X'}).status_code == 400


def test_a_wished_and_a_to_check_row_are_marked(world, client, coll):
    row = client.get('/manage/add/search', query_string={'type': 'set', 'q': '1000-2'}).json['items'][0]
    assert row['wished'] and row['wished_by_list'] == {'default': [None]}
    coll.link(world.mystery, 'x-mystery', kind='G', status='to_check')
    assert client.get('/manage/add/search', query_string={'type': 'gear', 'q': 'mystery'}).json['items'][0]['to_check'] is True


# ---------- no activated catalogue ----------

def test_a_collection_with_no_active_catalogue_names_the_fix(tmp_path, monkeypatch):
    (tmp_path / 'cat').mkdir()
    shutil.copy(build_catalogue(tmp_path / 'cat'), tmp_path / 'catalogue.db')
    with closing(connect(tmp_path / 'brickwork.db', require_catalogue=False)):
        pass                                                                  # a fresh `setup` file; the catalogue is hand-copied, never activated
    client = app_on(tmp_path, monkeypatch, 'no-activation')
    page = client.get('/manage/add')
    assert page.status_code == 200 and 'python -m brickwork.store4 catalogue reconcile' in page.get_data(as_text=True)
    with client.session_transaction() as session:
        csrf = session['bw_add_csrf']
    for result in (client.get('/manage/add/search', query_string={'type': 'set', 'q': 'x'}), review(client, csrf)):
        assert result.status_code == 400 and 'catalogue reconcile' in result.json['error']


def test_a_collection_with_no_catalogue_file_says_where_to_get_one(tmp_path, monkeypatch):
    with closing(connect(tmp_path / 'brickwork.db', require_catalogue=False)):
        pass
    page = app_on(tmp_path, monkeypatch, 'no-catalogue').get('/manage/add')
    assert page.status_code == 200 and 'catalogue download' in page.get_data(as_text=True)


# ---------- a set becomes copies ----------

def test_a_set_becomes_copies_with_the_preselected_list_and_undo_archives_them(world, client, csrf, read):
    proposal = review(client, csrf, '1000-1 x2\n2070-1').json
    assert proposal['unresolved'] == [] and [r['quantity'] for r in proposal['items']] == [2, 1]
    assert proposal['items'][0]['import_notes'] == ['Part list: Rebrickable version 1 of 1, latest']
    assert confirm(client, csrf, proposal).status_code == 400                     # both are owned already: choose another copy or skip
    items = proposal['items']
    items[0].update(decision='another', completeness='complete')
    items[1].update(decision='another', condition='new')
    result = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=items))
    assert result.status_code == 200
    first, second = result.json['receipts']
    assert len(first['copies']) == 2 and len(second['copies']) == 1 and first['stock'] is None
    with read() as db:
        new = db.execute('SELECT * FROM copy WHERE id IN (?, ?)', first['copies']).fetchall()
        assert {(c['inventory_source'], c['completeness'], c['completeness_source'], c['condition']) for c in new} == {('rebrickable', 'complete', 'manual', 'used')}
        duplo = db.execute('SELECT * FROM copy WHERE id=?', (second['copies'][0],)).fetchone()
        latest = db.execute('SELECT version FROM catalogue.inventory WHERE item_id=? AND is_latest=1', (world.duplo,)).fetchone()[0]
        assert (duplo['inventory_source'], duplo['inventory_version'], duplo['condition']) == ('rebrickable', latest, 'new')
        live = lambda cid: db.execute('SELECT count(*) FROM copy_part WHERE copy_id=? AND retired_at IS NULL', (cid,)).fetchone()[0]
        assert live(first['copies'][0]) == live(world.copy_a) > 0                 # materialised in the same transaction as the copy
        receipts = db.execute("SELECT * FROM event WHERE entity_kind='add' AND field='receipt' AND entity_id=? ORDER BY id", (result.json['batch'],)).fetchall()
        assert len(receipts) == 2 and receipts[0]['via'] == 'app' and json.loads(receipts[0]['new_value'])['copies'] == first['copies']
        job = pipeline.Pipeline(db).status(first['job_id'])
        assert (job['state'], [s['name'] for s in job['steps']], job['item_id']) == ('queued', list(pipeline.STEPS), world.keep)
    # A lost response cannot create a second batch.
    again = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=items))
    assert [r['copies'] for r in again.json['receipts']] == [first['copies'], second['copies']]
    with read() as db:
        assert db.execute('SELECT count(*) FROM copy').fetchone()[0] == 3 + 3
    assert undo(client, csrf, result.json['batch']).json['message'] == 'Undone'
    with read() as db:
        assert db.execute('SELECT count(*) FROM copy WHERE archived_at IS NULL').fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM event_undo u JOIN event e ON e.id=u.event_id WHERE e.entity_kind='add'").fetchone()[0] == 2
        before = db.execute('SELECT count(*) FROM event').fetchone()[0]
    assert undo(client, csrf, result.json['batch']).json['message'] == 'Undone'
    with read() as db:
        assert db.execute('SELECT count(*) FROM event').fetchone()[0] == before


def test_the_preselection_follows_the_pinned_version_and_a_set_with_no_list_gets_none(world, client, csrf, coll, read):
    versions = [r['version'] for r in coll.db.execute('SELECT version FROM catalogue.inventory WHERE item_id=? ORDER BY version', (world.duplo,))]
    assert len(versions) == 2
    copies.set_part_list_preference(coll.db, world.duplo, {'source': 'rebrickable', 'version': versions[0]}, via='cli')
    proposal = review(client, csrf, '2070-1').json
    assert proposal['items'][0]['import_notes'][0].startswith('Part list: Rebrickable version 1 of 2')
    receipt = confirm(client, csrf, proposal, decision='another').json['receipts'][0]
    with read() as db:
        assert db.execute('SELECT inventory_version FROM copy WHERE id=?', (receipt['copies'][0],)).fetchone()[0] == versions[0]
    # An unidentified set has no part list at all.
    receipt = confirm(client, csrf, review(client, csrf, '99999-9').json, decision='unidentified').json['receipts'][0]
    with read() as db:
        copy = db.execute('SELECT * FROM copy WHERE id=?', (receipt['copies'][0],)).fetchone()
        assert (copy['inventory_source'], copy['inventory_digest'], db.execute('SELECT count(*) FROM copy_part WHERE copy_id=?', (copy['id'],)).fetchone()[0]) == ('none', None, 0)


def test_a_marked_copy_cannot_be_undone(world, client, csrf, coll, read):
    batch = confirm(client, csrf, review(client, csrf, '1000-2').json, decision='another').json
    copy_id = batch['receipts'][0]['copies'][0]
    coll.mark(copy_id, '3001', '4', missing=1)
    refused = undo(client, csrf, batch['batch'])
    assert refused.status_code == 400 and 'undo the later save first' in refused.json['error']
    with read() as db:
        assert db.execute('SELECT archived_at FROM copy WHERE id=?', (copy_id,)).fetchone()[0] is None
        assert db.execute("SELECT count(*) FROM event_undo u JOIN event e ON e.id=u.event_id WHERE e.entity_kind='add'").fetchone()[0] == 0


# ---------- BrickLink's list, pending, settled through the Add flow ----------

def test_bricklink_pending_settles_end_to_end_through_add(world, client, csrf, key, coll, read, pair, monkeypatch):
    coll.setting('prefer_bricklink_inventory', 'true')
    proposal = review(client, csrf, '1000-2').json
    assert "Part list: BrickLink's" in proposal['items'][0]['import_notes'][0]
    confirmed = confirm(client, csrf, proposal, decision='another').json['receipts'][0]
    copy_id = confirmed['copies'][0]
    assert [p['copy_id'] for p in confirmed['pending']] == [copy_id]
    with read() as db:
        copy = db.execute('SELECT * FROM copy WHERE id=?', (copy_id,)).fetchone()
        assert (copy['inventory_source'], copy['inventory_pending']) == ('rebrickable', 'bricklink')
        assert db.execute('SELECT kind FROM job WHERE id=?', (copy['pending_job_id'],)).fetchone()[0] == 'bricklink_subsets'
        assert drainer.pending(db) and drainer.poll_delay(db) == 1
    served = []
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'bricklink', lambda url, headers: (served.append(url), (200, reply(entry('3001', 5, 2), entry('3023', 1, 1))))[1])
    drainer.drain_once(pair)                                                # both runners: the fetch job, then the pipeline job
    assert len(served) == 1
    with read() as db:
        copy = db.execute('SELECT * FROM copy WHERE id=?', (copy_id,)).fetchone()
        assert (copy['inventory_source'], copy['inventory_pending']) == ('bricklink', None)       # settled: switched automatically (unmarked)
        assert {r['state'] for r in db.execute('SELECT state FROM job')} == {'done'}
        assert db.execute("SELECT count(*) FROM job WHERE kind='item' AND state='done'").fetchone()[0] == 1
        assert drainer.poll_delay(db) is None and not drainer.pending(db)
    assert undo(client, csrf, confirmed['batch']).json['message'] == 'Undone'
    with read() as db:
        assert db.execute('SELECT archived_at IS NOT NULL FROM copy WHERE id=?', (copy_id,)).fetchone()[0] == 1


def test_undo_before_the_fetch_ends_clears_the_pending_state(world, client, csrf, key, coll, read):
    coll.setting('prefer_bricklink_inventory', 'true')
    batch = confirm(client, csrf, review(client, csrf, '1000-2').json, decision='another').json
    assert undo(client, csrf, batch['batch']).json['message'] == 'Undone'
    with read() as db:
        copy = db.execute('SELECT * FROM copy WHERE id=?', (batch['receipts'][0]['copies'][0],)).fetchone()
        assert copy['archived_at'] and copy['inventory_pending'] is None and copy['pending_job_id'] is None


# ---------- loose stock, figures, wishes ----------

def test_loose_parts_merge_and_undo_restores_the_quantity(world, client, csrf, read):
    proposal = review(client, csrf, '3001 x4', type='part', where='loose').json
    assert proposal['items'][0]['kind'] == 'part' and proposal['items'][0]['color_id'] is None
    assert confirm(client, csrf, proposal).status_code == 400                    # a part needs a colour
    result = confirm(client, csrf, proposal, color_id=world.red, condition='used', decision='another')
    assert result.status_code == 200
    stock_id = result.json['receipts'][0]['stock']
    with read() as db:
        row = db.execute('SELECT * FROM stock WHERE id=?', (stock_id,)).fetchone()
        assert (row['kind'], row['quantity'], row['storage_id'], row['lot_id']) == ('part', 4, None, None)     # the world's used row has a lot: another key
        assert row['id'] != world.stock_brick
    again = confirm(client, csrf, review(client, csrf, '3001 x2', type='part', where='loose').json, color_id=world.red, condition='used', decision='another').json
    assert again['receipts'][0]['stock'] == stock_id
    with read() as db:
        assert db.execute('SELECT quantity FROM stock WHERE id=?', (stock_id,)).fetchone()[0] == 6
        assert db.execute('SELECT count(*) FROM stock WHERE archived_at IS NULL AND item_id=? AND color_id=?', (world.brick, world.red)).fetchone()[0] == 3
    refused = undo(client, csrf, result.json['batch'])                            # the later add onto the same row is still there
    assert refused.status_code == 400 and 'Stock changed since this save' in refused.json['error']
    assert undo(client, csrf, again['batch']).status_code == 200
    with read() as db:
        assert db.execute('SELECT quantity, archived_at FROM stock WHERE id=?', (stock_id,)).fetchone()[:] == (4, None)
    assert undo(client, csrf, result.json['batch']).status_code == 200
    with read() as db:
        assert db.execute('SELECT archived_at IS NOT NULL FROM stock WHERE id=?', (stock_id,)).fetchone()[0] == 1


def test_a_figure_added_loose_carries_its_part_list_times_the_quantity(world, client, csrf, read):
    receipt = confirm(client, csrf, review(client, csrf, 'fig-000004 x2', type='minifigure', where='loose').json, decision='another').json['receipts'][0]
    with read() as db:
        row = db.execute('SELECT * FROM stock WHERE id=?', (receipt['stock'],)).fetchone()
        latest = db.execute('SELECT id, version, digest FROM catalogue.inventory WHERE item_id=? AND is_latest=1', (world.figure,)).fetchone()
        assert (row['kind'], row['quantity'], row['inventory_source'], row['inventory_version'], row['inventory_digest']) == ('minifigure', 2, 'rebrickable', latest['version'], latest['digest'])
        parts = {(p['item_id'], p['color_id'], p['is_spare']): p['quantity'] for p in db.execute('SELECT * FROM stock_part WHERE stock_id=?', (receipt['stock'],))}
        want = {(p['item_id'], p['color_id'], p['is_spare']): p['quantity'] * 2 for p in db.execute('SELECT * FROM catalogue.inventory_part WHERE inventory_id=?', (latest['id'],))}
        assert parts == want and parts
    second = confirm(client, csrf, review(client, csrf, 'fig-000004', type='minifigure', where='loose').json, decision='another').json
    assert second['receipts'][0]['stock'] != receipt['stock']                    # a figure never merges
    assert undo(client, csrf, second['batch']).status_code == 200
    with read() as db:
        assert db.execute('SELECT archived_at IS NOT NULL FROM stock WHERE id=?', (second['receipts'][0]['stock'],)).fetchone()[0] == 1


def test_a_gear_item_added_as_owned_goes_to_stock_without_a_colour(world, client, csrf, read):
    unknown = review(client, csrf, 'bag-7', type='gear').json
    receipt = confirm(client, csrf, unknown, decision='unidentified', condition='new').json['receipts'][0]
    with read() as db:
        row = db.execute('SELECT * FROM stock WHERE id=?', (receipt['stock'],)).fetchone()
        assert (row['kind'], row['color_id'], row['condition'], row['quantity']) == ('gear', None, 'new', 1)
        assert db.execute('SELECT name, born_key FROM item WHERE id=?', (row['item_id'],)).fetchone()[:] == ('bag-7', None)


def test_a_wish_is_added_raised_and_undone(world, client, csrf, read):
    proposal = review(client, csrf, '2070-1', where='wishlist').json
    assert proposal['items'][0]['condition'] == 'used'
    batch = confirm(client, csrf, proposal, condition='any', decision='another').json
    wish_id = batch['receipts'][0]['wish']
    with read() as db:
        wish = db.execute('SELECT * FROM wish WHERE id=?', (wish_id,)).fetchone()
        assert (wish['kind'], wish['condition'], wish['quantity'], wish['wishlist_id']) == ('set', 'any', 1, 'default')
    again = review(client, csrf, '2070-1 x2', where='wishlist').json
    assert confirm(client, csrf, again).status_code == 400                       # already on the wishlist: choose
    raised = confirm(client, csrf, again, decision='another').json
    assert raised['receipts'][0]['wish'] == wish_id
    with read() as db:
        assert db.execute('SELECT quantity FROM wish WHERE id=?', (wish_id,)).fetchone()[0] == 3
    assert undo(client, csrf, raised['batch']).status_code == 200
    with read() as db:
        assert db.execute('SELECT quantity, archived_at FROM wish WHERE id=?', (wish_id,)).fetchone()[:] == (1, None)
    assert undo(client, csrf, batch['batch']).status_code == 200
    with read() as db:
        assert db.execute('SELECT archived_at IS NOT NULL FROM wish WHERE id=?', (wish_id,)).fetchone()[0] == 1


def test_a_wanted_list_file_resolves_creates_lists_and_undoes(world, client, csrf, read):
    xml = ('<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID><COLOR>5</COLOR><MINQTY>3</MINQTY><CONDITION>N</CONDITION>'
           '<MAXPRICE>0.5000</MAXPRICE><WANTEDLISTID>777</WANTEDLISTID></ITEM><ITEM><ITEMTYPE>Q</ITEMTYPE><ITEMID>1</ITEMID></ITEM></INVENTORY>')
    response = client.post('/manage/add/review', data=dict(csrf_token=csrf, type='part', where='wishlist', mode='file', list_id='default',
                                                           file=(io.BytesIO(xml.encode()), 'wanted.xml')), content_type='multipart/form-data')
    proposal = response.json
    row = proposal['items'][0]
    assert (row['kind'], row['color_id'], row['quantity'], row['condition'], row['list_id']) == ('part', world.red, 3, 'new', 'new-bl:777')
    assert row['max_price'] == '0.5000' and len(proposal['unresolved']) == 1 and 'item type' in proposal['unresolved'][0]['reason']
    batch = confirm(client, csrf, proposal, decision='another').json            # 3001 red is in stock already: a wish for more is a choice
    with read() as db:
        listing = db.execute("SELECT * FROM wishlist WHERE bricklink_id='777'").fetchone()
        wish = db.execute('SELECT * FROM wish WHERE id=?', (batch['receipts'][0]['wish'],)).fetchone()
        assert listing['name'] == 'BrickLink 777' and (wish['wishlist_id'], wish['color_id'], wish['max_price']) == (listing['id'], world.red, '0.5000')
    assert undo(client, csrf, batch['batch']).status_code == 200
    with read() as db:
        assert db.execute("SELECT archived_at IS NOT NULL FROM wishlist WHERE bricklink_id='777'").fetchone()[0] == 1


def test_a_rebrickable_csv_resolves_by_born_numbers_and_colour_ids(world, client, csrf):
    csv_text = 'part_num,color_id,quantity\n3023,15,4\n9999x,15,1\n'
    response = client.post('/manage/add/review', data=dict(csrf_token=csrf, type='part', where='loose', mode='file',
                                                           file=(io.BytesIO(csv_text.encode()), 'parts.csv')), content_type='multipart/form-data')
    proposal = response.json
    assert [(r['number'], r['color_id'], r['quantity']) for r in proposal['items'] if not r.get('unknown')] == [('3023', world.white, 4)]
    assert [r['number'] for r in proposal['items'] if r.get('unknown')] == ['9999x']
    # a known colour stays with an unknown part, so Add as unidentified needs no second choice (Codex on M.8c)
    assert [r['color_id'] for r in proposal['items'] if r.get('unknown')] == [world.white]


# ---------- an unknown number: both offers ----------

def test_an_unknown_set_number_offers_fetch_and_unidentified(world, client, csrf, read, monkeypatch):
    monkeypatch.delenv(rebrickable_api.KEY_ENV, raising=False)
    proposal = review(client, csrf, '99999-9 x2').json
    row = proposal['items'][0]
    assert (row['unknown'], row['item_id'], row['number'], row['kind']) == (True, None, '99999-9', 'set')
    assert row['offers']['unidentified'] is True and row['offers']['fetch'] == {'available': False, 'why': 'Add a Rebrickable key in Tools & Admin first'}
    assert 'add a Rebrickable key' in row['offers']['help']
    before = counts(read)
    assert confirm(client, csrf, proposal).status_code == 400                    # an unknown number needs a choice
    assert confirm(client, csrf, proposal, decision='fetch').status_code == 400   # fetching needs a key
    assert counts(read) == before


def test_fetch_from_rebrickable_queues_the_job_and_add_as_unidentified_makes_a_local_item(world, client, csrf, read, monkeypatch):
    monkeypatch.setenv(rebrickable_api.KEY_ENV, 'x')
    row = review(client, csrf, '99999-9').json['items'][0]
    assert row['offers']['fetch'] == {'available': True, 'why': None} and 'fetch it from Rebrickable' in row['offers']['help']
    batch = confirm(client, csrf, review(client, csrf, '99999-9').json, decision='fetch').json
    receipt = batch['receipts'][0]
    assert receipt['fetch_job'] and receipt['job_id'] is None and receipt['copies'] == []
    with read() as db:
        job = jobs.status(db, receipt['fetch_job'])
        assert (job['kind'], job['state'], job['number'], job['item_id']) == ('rebrickable_set', 'queued', '99999-9', None)
        assert db.execute('SELECT count(*) FROM copy').fetchone()[0] == 3 and drainer.pending(db)
    assert undo(client, csrf, batch['batch']).status_code == 200                  # nothing to archive yet
    # Add as unidentified: a local set named as typed, the typed number a to_check BrickLink link, a copy with no list.
    batch = confirm(client, csrf, review(client, csrf, '99999-9 x2').json, decision='unidentified').json
    receipt = batch['receipts'][0]
    assert len(receipt['copies']) == 2
    with read() as db:
        item = db.execute('SELECT * FROM item WHERE id=?', (receipt['item_id'],)).fetchone()
        assert (item['origin'], item['kind'], item['name'], item['born_key'], item['id'] >= 1_000_000_000) == ('local', 'set', '99999-9', None, True)
        links = db.execute('SELECT * FROM item_link WHERE item_id=?', (item['id'],)).fetchall()
        assert [(l['provider'], l['provider_kind'], l['provider_key'], l['status']) for l in links] == [('bricklink', 'S', '99999-9', 'to_check')]
    assert client.get(f'/collection/item/{item["id"]}').status_code == 200        # it works on every screen
    # The same typed number is the same item again.
    again = confirm(client, csrf, review(client, csrf, '99999-9').json, decision='unidentified').json['receipts'][0]
    assert again['item_id'] == receipt['item_id']
    assert undo(client, csrf, batch['batch']).status_code == 200
    with read() as db:
        assert db.execute('SELECT count(*) FROM copy WHERE item_id=? AND archived_at IS NULL', (receipt['item_id'],)).fetchone()[0] == 1


def test_a_dotted_unknown_set_number_offers_only_unidentified(world, client, csrf):
    # Rebrickable cannot have a dotted set number: no fetch offer, and no TypeError on the missing one (Codex on M.8c)
    row = review(client, csrf, 'custom.1').json['items'][0]
    assert (row['unknown'], row['offers']['fetch'], row['offers']['help']) == (True, None, 'Not in the catalogue · add it as unidentified')
    assert confirm(client, csrf, review(client, csrf, 'custom.1').json, decision='unidentified').status_code == 200


def test_a_failed_fetch_job_is_retried_from_add(world, client, csrf, read, monkeypatch, pair):
    # Retry dispatches by the job's kind: a Fetch from Rebrickable job is store4's, not the pipeline's (Codex on M.8c)
    monkeypatch.setenv(rebrickable_api.KEY_ENV, 'x')
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', lambda: None)
    job = confirm(client, csrf, review(client, csrf, '99999-9').json, decision='fetch').json['receipts'][0]['fetch_job']
    with closing(sqlite3.connect(pair)) as db, db:
        db.execute("UPDATE job SET state='failed', error='down', error_code='source_error', attempts=3 WHERE id=?", (job,))
    assert client.post(f'/manage/add/jobs/{job}/retry', json=dict(csrf_token=csrf)).json == {'message': 'Queued'}
    with read() as db:
        assert tuple(db.execute('SELECT state, error, attempts FROM job WHERE id=?', (job,)).fetchone()) == ('queued', None, 0)


def test_an_unknown_part_offers_only_unidentified_and_a_part_needs_a_colour(world, client, csrf):
    proposal = review(client, csrf, 'zzz1', type='part', where='wishlist').json
    row = proposal['items'][0]
    assert row['offers']['fetch'] is None and row['offers']['help'] == 'Not in the catalogue · add it as unidentified'
    assert confirm(client, csrf, proposal, decision='unidentified').status_code == 400
    assert confirm(client, csrf, proposal, decision='unidentified', color_id=world.red).status_code == 200


def test_several_matches_are_never_guessed(world, client, csrf, coll):
    coll.link(world.brick, 'dup-key', kind='P')
    coll.link(world.plate, 'dup-key', kind='P')
    proposal = review(client, csrf, 'dup-key', type='part', where='loose').json
    assert proposal['items'] == [] and 'matches 2 items' in proposal['unresolved'][0]['reason']


# ---------- the review is checked, not trusted ----------

def test_edits_are_validated_and_skip_adds_nothing(world, client, csrf, read):
    proposal = review(client, csrf, '2070-1').json
    before = counts(read)
    for bad in (dict(where='nowhere'), dict(condition='mint'), dict(completeness='perfect'), dict(quantity='0'), dict(storage_id='nope')):
        assert confirm(client, csrf, proposal, decision='another', **bad).status_code == 400, bad
    assert counts(read) == before
    skipped = confirm(client, csrf, proposal, decision='skip')
    assert skipped.status_code == 200 and skipped.json['receipts'] == [] and counts(read) == before
    forged = dict(csrf_token=csrf, token=proposal['token'] + 'x', items=proposal['items'])
    assert client.post('/manage/add/confirm', json=forged).status_code == 400
    assert client.post('/manage/add/review', json=dict(type='set', where='owned', mode='paste', text='1000-1')).status_code == 400   # no CSRF token
    assert review(client, csrf, '', mode='photo').status_code == 400


def test_a_review_sent_again_after_a_row_was_saved_changes_nothing_for_it(world, client, csrf, read):
    proposal = review(client, csrf, '1000-2\n2070-1').json
    items = proposal['items']
    for item in items:
        item['decision'] = 'another'
    first = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=items))
    again = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=items))
    assert first.status_code == again.status_code == 200
    assert [r['copies'] for r in again.json['receipts']] == [r['copies'] for r in first.json['receipts']]
    assert counts(read)['copy'] == 3 + 2


# ---------- the jobs the Add queued ----------

def test_the_job_endpoint_reports_steps_without_payloads_and_retry_requeues(world, client, csrf, read, pair):
    receipt = confirm(client, csrf, review(client, csrf, '1000-2').json, decision='another').json['receipts'][0]
    events = client.get(f'/manage/add/jobs/{receipt["job_id"]}').json['events']
    assert [e['step'] for e in events] == [*pipeline.STEPS, None] and events[-1]['message'] == 'Import queued'
    assert client.get('/manage/add/jobs/99999').status_code == 404
    drainer.drain_once(pair)
    events = client.get(f'/manage/add/jobs/{receipt["job_id"]}').json['events']
    assert events[-1]['state'] == 'done' and events[-1]['message'] == 'Import complete'
    assert {e['step']: e['message'] for e in events}['pictures'].startswith('skipped')
    assert client.post(f'/manage/add/jobs/{receipt["job_id"]}/retry', json=dict(csrf_token=csrf)).json == {'message': 'Queued'}


# ---------- the page's frames, links into it and the shell ----------

def page(client, route):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_the_wanted_link_of_a_figure_uses_the_review_confirm_and_undo(world, client, csrf, coll, monkeypatch):
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', lambda: None)
    route = f'/collection/item/{world.figure}'
    link = page(client, route).select_one('[data-module=wanted] a')
    assert link['href'] == '/manage/add?type=minifigure&where=wishlist&number=fig-000004'
    target = page(client, link['href'])
    assert target.select_one('input[name=type][checked]')['value'] == 'minifigure'
    assert target.select_one('input[name=where][checked]')['value'] == 'wishlist'
    assert target.select_one('input[name=mode][checked]')['value'] == 'paste'
    assert target.select_one('[data-paste]').get_text() == 'fig-000004'
    proposal = review(client, csrf, 'fig-000004', type='minifigure', where='wishlist').json
    assert len(proposal['items']) == 1
    confirmed = confirm(client, csrf, proposal, decision='another')            # one is in stock already: a wish for more is a choice
    assert confirmed.status_code == 200, confirmed.json
    wanted = lambda: page(client, route).select_one('[data-module=wanted]').get_text()
    assert 'On the wishlist' in wanted()
    coll.sql("UPDATE wish SET max_price='11408.95', max_price_currency='EUR' WHERE item_id=?", (world.figure,))
    assert '€11,408.95' in wanted()
    # A later edit of the wish blocks the Undo of the add; it never restores over the edit.
    blocked = undo(client, csrf, confirmed.json['batch'])
    assert blocked.status_code == 400 and 'undo the later save first' in blocked.json['error']
    assert '€11,408.95' in wanted()
    coll.sql("UPDATE wish SET max_price=NULL, max_price_currency=NULL WHERE item_id=?", (world.figure,))
    assert undo(client, csrf, confirmed.json['batch']).status_code == 200
    assert 'Not on the wishlist' in wanted()


@pytest.mark.parametrize('query', ['type=X', 'type=X&where=X', 'type=&where=', 'type=zzz'])
def test_add_invalid_initial_radios_fall_back(world, client, query):
    soup = page(client, '/manage/add?' + query)
    assert [r['value'] for r in soup.select('input[name=type][checked]')] == ['set']
    assert [r['value'] for r in soup.select('input[name=where][checked]')] == ['owned']


def test_add_review_frames(world, client):
    soup = page(client, '/manage/add')
    assert not soup.select('.breadcrumb')
    root = soup.select_one('#bw-add')
    assert root.select_one('header h1').text == 'Add'
    where = root.select_one('input[name=where]').find_parent('div')
    assert 'bw-add-continuous' in where['class']
    assert [i['value'] for i in where.select('input')] == ['owned', 'loose', 'wishlist']
    assert not root.select('[data-filters], [data-filter-panel], [data-type-filter]')
    assert root.select_one('fieldset[aria-label=How]') and not root.select_one('fieldset[aria-label=How] legend')
    assert [i['value'] for i in root.select('fieldset[aria-label=How] input')] == ['search', 'paste', 'file', 'photo']
    assert root.select_one('.bw-add-search-field input[aria-label]')
    assert root.select_one('[data-candidates][hidden]') and root.select_one('[data-mode=photo][hidden] input[type=file][accept="image/*"]')       # the photo mode's candidates (M.8h)


def test_the_rail_marks_add_current(world, client, app4):
    from brickwork.web.ui import navigation
    with app4.test_request_context('/manage/add'):
        from flask import session
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session['_user_id'] = 'admin'
        session['_fresh'] = True
        session[SESSION_PASSWORD] = password_mark(app4.config['AUTHENTICATION_PASSWORD'])
        app4.preprocess_request()
        links = [link for _, links in navigation() for link in links]
        assert [link['title'] for link in links if link['active']] == ['Add']
    html = client.get('/manage/add').get_data(as_text=True)
    assert 'id="global-jump"' in html and 'aria-current="page"' in html


def test_a_collection_that_is_not_set_up_shows_the_notice(tmp_path, monkeypatch):
    (tmp_path / 'not-set-up').mkdir()
    client = app_on(tmp_path / 'not-set-up', monkeypatch, 'not-set-up')
    page_ = client.get('/manage/add')
    assert page_.status_code == 200 and 'database is not available' in page_.get_data(as_text=True)
    assert client.get('/manage/add/search', query_string={'type': 'set', 'q': 'x'}).status_code == 400


def test_a_row_is_all_or_nothing(world, client, csrf, coll, read):
    """The copy, its figure and part lines, the pipeline job and the receipt commit together: a receipt that cannot be written leaves none."""
    proposal = review(client, csrf, '1000-1\n2070-1').json
    before = counts(read)
    with coll.db:
        coll.db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON event WHEN NEW.entity_kind='add' AND NEW.field='receipt' BEGIN SELECT RAISE(ABORT,'receipt rejected'); END")
    refused = confirm(client, csrf, proposal, decision='another')
    assert refused.status_code == 400 and refused.json['receipts'] == []
    with read() as db:
        assert counts(read) == before
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    with coll.db:
        coll.db.execute('DROP TRIGGER reject_receipt')
    assert confirm(client, csrf, proposal, decision='another').status_code == 200


def test_undo_of_an_add_is_refused_when_a_loose_figure_gap_was_filled(world, coll, read):
    """Review of M.8j: the same gap as the import's Undo: a Give changes only the figure's part lines."""
    from brickwork.core import add, workbench
    db = coll.db
    figure = coll.item('minifigs', 'fig-000004')
    row = dict(item_id=figure, kind='minifigure', where='loose', quantity=1, condition='used', color_id=None, decision='add', lot_id=None, storage_id=None)
    with db:
        db.execute('BEGIN IMMEDIATE')
        change = __import__('brickwork.core.stock', fromlist=['x']).add_loose(db, item_id=figure, quantity=1, condition='used')
    stock_id = change['id']
    part = db.execute('SELECT * FROM stock_part WHERE stock_id=? AND is_spare=0 LIMIT 1', (stock_id,)).fetchone()
    db.execute('UPDATE stock_part SET missing=1 WHERE id=?', (part['id'],))
    db.commit()
    with db:
        db.execute('BEGIN IMMEDIATE')
        change['after'] = dict(db.execute('SELECT * FROM stock WHERE id=?', (stock_id,)).fetchone())
        change['parts'] = __import__('brickwork.core.stock', fromlist=['x']).part_digest(db, stock_id)
    supplier = coll.add_stock('part', part['item_id'], colour=part['color_id'], quantity=2, condition=None)
    workbench.transfer(db, supplier, stock_id, 'stock-part', part['id'], 1)
    with pytest.raises(ValueError, match='changed since'):
        with db:
            db.execute('BEGIN IMMEDIATE')
            __import__('brickwork.core.stock', fromlist=['x']).undo_added(db, change)
