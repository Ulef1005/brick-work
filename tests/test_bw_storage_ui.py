"""Storage rebuild to 12c on the 4.0 store (M.8e, issue #110): table, contents panel, select and move, sheets, empty states, purchase locations.

Gone with 3.3: `test_storage_api_reports_figures_and_part_lots` (the API serializer fields are M.11's) and the `placeholder` figure of the
counts test (a figure with no number is an unidentified minifigure now).
"""
import json
import shutil
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from brickwork.core import ledger
from tests.app4 import STAMP, app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)


def page(client, url='/workbench/storage'):
    response = client.get(url)
    assert response.status_code == 200, response.text[-1500:]
    return BeautifulSoup(response.text, 'html.parser')


def text(node):
    return ' '.join(node.get_text(' ').split())


def test_table_rows_do_not_run_together_and_select_the_first_storage(world, coll, client):
    coll.storage('Single Carton Box')
    coll.storage('Original Box on Display')
    soup = page(client)
    rows = soup.select('.st-table [data-row]')
    # Each storage is its own anchor row (the old list ran 0 pieces and the next name into one line).
    assert len(rows) >= 4 and all(r.name == 'a' for r in rows)
    names = [r.select_one('.st-name strong').get_text() for r in rows]
    assert {'Single Carton Box', 'Original Box on Display', 'Shelf A', 'Not stored'} <= set(names) and names[-1] == 'Not stored'
    for row in rows:
        assert row.select_one('.st-name strong') and len(row.select('.st-num')) == 3
    assert [text(n) for n in soup.select('.st-thead [role=columnheader]')] == ['Storage', 'Sets', 'Figures', 'Part lots']
    selected = soup.select('.st-row.is-selected')
    assert len(selected) == 1 and selected[0]['aria-current'] == 'page'
    assert soup.select_one('.st-pane h1').get_text() == selected[0].select_one('strong').get_text()
    summary = text(soup.select_one('.st-head p'))
    assert summary.startswith(f'{len([n for n in names if n != "Not stored"])} storages · ')
    assert 'sets' in summary and 'figures' in summary and 'part lots' in summary
    assert [r.select_one('strong').get_text() for r in rows if r.has_attr('data-uncounted')] == ['Not stored']


def test_contents_panel_groups_sets_figures_and_part_lots(world, coll, client):
    coll.sql('UPDATE stock SET storage_id=? WHERE id=?', (world.shelf, world.stock_figure))
    soup = page(client, f'/workbench/storage/{world.shelf}')
    groups = {g['data-group']: g for g in soup.select('.st-group')}
    assert set(groups) >= {'set', 'figure', 'part'}
    assert 'Sets · 1' in text(groups['set'].select_one('h2'))
    assert 'Used' in text(groups['set'])                                     # condition shown on the set row
    assert 'Minifigures' in text(groups['figure'].select_one('h2')) and groups['figure'].select_one('.st-pill').get_text() == 'Used'
    part = groups['part']
    assert 'Bag' in text(part) and 'Lot ·' in text(part)                      # lots sit with the part lots
    assert part.select_one('.bw-colour') is not None                          # a loose part keeps its colour chip
    assert '×' in text(part)
    for img in soup.select('.st-pic img'):
        assert img['alt'] == '' and 'cover' not in str(img)
    assert 'sets ·' in text(soup.select_one('.st-detail-head p'))
    assert soup.select_one('[data-select]').get_text() == 'Select' and soup.select_one('[data-open=st-edit]')
    for box in soup.select('.st-check'):
        assert box['data-selection'] and box['aria-label'].startswith('Select ')
    assert {json.loads(b['data-selection'])['entity'] for b in soup.select('.st-check')} == {'copy', 'stock', 'lot'}
    # The first-storage default and the explicit route show the same contents.
    first = page(client)
    assert [b['data-selection'] for b in first.select('.st-check')] == [b['data-selection'] for b in soup.select('.st-check')]


def test_select_mode_markup_and_move_of_set_and_lot_with_undo(world, coll, client):
    token = csrf(client)
    target = coll.storage('Target box')
    soup = page(client, f'/workbench/storage/{world.shelf}')
    form = soup.select_one('form[data-action=move]')
    assert form.select_one('[data-bar]').has_attr('hidden') and form.select_one('[data-move-open]').has_attr('disabled')
    assert 'Move to another storage' in text(form.select_one('[data-bar]'))
    sheet = form.select_one('dialog#st-move')                                # the sheet sits inside the form, so its select is submitted with the selection
    assert [o.get_text() for o in sheet.select('option')][0] == 'Not stored'
    assert 'Target box' in text(sheet) and 'Move selected items' in text(sheet)
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=token, storage_id=target, selections=[dict(entity='copy', id=world.copy_a), dict(entity='lot', id=world.bag)]))
    assert move.status_code == 200, move.json
    db = coll.db
    assert db.execute('SELECT storage_id FROM copy WHERE id=?', (world.copy_a,)).fetchone()[0] == target
    assert db.execute('SELECT storage_id FROM lot WHERE id=?', (world.bag,)).fetchone()[0] == target
    event = db.execute('SELECT via,new_value FROM event WHERE id=?', (move.json['event_id'],)).fetchone()
    assert event['via'] == 'app' and '"table": "lot"' in event['new_value']
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=move.json['event_id'])).status_code == 200
    assert db.execute('SELECT storage_id FROM copy WHERE id=?', (world.copy_a,)).fetchone()[0] == world.shelf
    assert db.execute('SELECT storage_id FROM lot WHERE id=?', (world.bag,)).fetchone()[0] == world.shelf
    assert client.post('/workbench/storage/action/move', json=dict(csrf_token=token, storage_id=target, selections=[dict(entity='lot', id='missing')])).status_code == 400
    assert client.post('/workbench/storage/action/move', json=dict(csrf_token=token, storage_id=target, selections=[dict(entity='wish', id='1')])).status_code == 400


def test_add_and_edit_sheets_keep_every_function(world, coll, client):
    token = csrf(client)
    soup = page(client, f'/workbench/storage/{world.shelf}')
    add = soup.select_one('dialog#st-add form[data-action=save]')
    assert add and add.select_one('input[name=name][required]') and 'Add storage' in text(add)
    assert add.get('data-context') is None                                   # no id: creates
    edit = soup.select_one('dialog#st-edit')
    assert json.loads(edit.select_one('form#st-edit-form')['data-context']) == {'id': world.shelf}
    assert edit.select_one('input[name=name]')['value'] == 'Shelf A'
    archive = edit.select_one('form[data-action=archive]')
    assert archive.select_one('input[name=move_to_unstored]') and archive.select_one('.bw-archive')
    assert soup.select_one('[data-open=st-add]') and soup.select_one('[data-open=st-edit]')
    # Create, rename and archive still go through one transaction with an event.
    made = client.post('/workbench/storage/action/save', json=dict(csrf_token=token, name='Drawer 14'))
    assert made.status_code == 200 and made.json['url'].startswith('/workbench/storage/')
    assert coll.db.execute('SELECT 1 FROM event WHERE id=?', (made.json['event_id'],)).fetchone()
    assert 'Drawer 14' in page(client, made.json['url']).select_one('.st-pane h1').get_text()
    gone = client.post('/workbench/storage/action/archive', json=dict(csrf_token=token, id=made.json['url'].rsplit('/', 1)[1]))
    assert gone.status_code == 200
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=gone.json['event_id'])).status_code == 200


def test_empty_storage_and_no_storages_states(world, coll, client):
    void = coll.storage('Box 5')
    soup = page(client, f'/workbench/storage/{void}')
    empty = soup.select_one('.st-pane .st-empty')
    assert text(empty.select_one('h2')) == 'Box 5 is empty.' and 'select mode' in text(empty)
    assert empty.select_one('a.st-outline').get_text().startswith('Go to ')
    assert not soup.select('[data-select]') and not soup.select('.st-group')  # nothing to select
    coll.sql('UPDATE copy SET storage_id=NULL')
    coll.sql('UPDATE stock SET storage_id=NULL')
    coll.sql('UPDATE lot SET storage_id=NULL')
    coll.sql('UPDATE storage SET archived_at=?', (STAMP,))
    soup = page(client)
    solo = soup.select_one('.st-solo')
    assert text(solo.select_one('h2')) == 'No storages yet.' and 'Add a box, drawer or shelf' in text(solo)
    assert solo.select_one('button[data-open=st-add]') and soup.select_one('dialog#st-add')
    assert 'Not stored' in text(solo.select_one('.st-note'))                  # the unassigned items stay reachable
    assert page(client, '/workbench/storage/unstored').select_one('.st-pane h1').get_text() == 'Not stored'


def test_history_stays_reachable_and_undo_works(world, client):
    token = csrf(client)
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=token, storage_id=None, selections=[dict(entity='copy', id=world.copy_a)]))
    assert move.status_code == 200
    history = page(client).select_one('details.st-history')
    assert history.select_one('summary').get_text() == 'History'
    assert history.select_one(f'[data-undo-event="{move.json["event_id"]}"]')
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=move.json['event_id'])).status_code == 200
    assert not page(client).select_one(f'details.st-history [data-undo-event="{move.json["event_id"]}"]')
    again = client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=move.json['event_id']))
    assert again.status_code == 400 and 'already' in again.json['message']
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=1)).status_code == 400, 'not a storage save'


def test_purchase_locations_page(world, coll, client):
    response = client.get('/collection/purchase-places')
    assert response.headers['Cache-Control'] == 'no-store'
    soup = BeautifulSoup(response.text, 'html.parser')
    assert soup.select_one('[data-web-ui="toni"]') and soup.select_one('a[href="/collection/sets"]')
    assert text(soup.select_one('h1')) == 'Purchase locations' and 'Where things came from' in text(soup)
    tabs = soup.select('.pl-tabs nav a')
    assert [text(a) for a in tabs] == ['Storages', 'Purchase locations'] and tabs[1]['aria-current'] == 'page' and tabs[0]['href'] == '/workbench/storage'
    assert 'values' in soup.select_one('a.pl-add')['href'] and 'purchase-places' in soup.select_one('a.pl-add')['href']
    row = next(r for r in soup.select('.st-row') if 'Shop' in r.get_text())
    nums = [n.get_text() for n in row.select('.st-num')]
    assert nums[:2] == ['—', '1'] and '€12.50' in text(row)                    # Orders (derived), Copies
    assert row.select_one('a.pl-name')['href'].endswith(f'?place={world.shop}')
    assert [o.get_text() for o in row.select('select[name=kind] option')][:3] == ['Not set', 'BrickLink store', 'Online shop']


def test_storage_counts_and_queries(world, coll):
    db = coll.db
    coll.sql('UPDATE stock SET storage_id=? WHERE id=?', (world.shelf, world.stock_figure))

    def trace(call):
        seen = []
        db.set_trace_callback(seen.append)
        call()
        db.set_trace_callback(None)
        return len(seen)
    shelf = next(r for r in ledger.storages(db) if r['id'] == world.shelf)
    assert shelf['figures'] == 1 and shelf['part_lots'] >= 1 and shelf['other'] == 0
    assert trace(lambda: ledger.storages(db)) == 1
    assert trace(lambda: ledger.storage_view(db, world.shelf)) < 20
    view = ledger.storage_view(db, world.shelf)
    assert view['total'] == len(view['sets']) + len(view['figures']) + len(view['part_lots']) + len(view['other'])
    assert [r['id'] for r in view['rows']] == [r['id'] for r in ledger.storage_detail(db, world.shelf)['rows']]


def test_storage_runtime():
    if not shutil.which('node'):
        pytest.skip('node is not installed')
    subprocess.run([shutil.which('node'), str(Path(__file__).with_name('toni_bw_storage_runtime.cjs'))], check=True, capture_output=True, text=True)


def test_lot_move_carries_its_parts_and_one_undo_restores_both(world, coll, client):
    token = csrf(client)
    target = coll.storage('Target box')
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=token, storage_id=target, selections=[dict(entity='lot', id=world.bag)]))
    assert move.status_code == 200, move.json
    db = coll.db
    assert db.execute('SELECT storage_id FROM lot WHERE id=?', (world.bag,)).fetchone()[0] == target
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[0] == target, 'the lot carries its parts'
    view = ledger.storage_view(db, target)
    assert {r['id'] for r in view['part_lots']} >= {world.bag, world.stock_brick}
    assert world.stock_brick not in {r['id'] for r in ledger.storage_view(db, world.shelf)['part_lots']}
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=move.json['event_id'])).status_code == 200
    assert db.execute('SELECT storage_id FROM lot WHERE id=?', (world.bag,)).fetchone()[0] == world.shelf
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[0] == world.shelf


def test_lot_carry_is_scoped_to_the_lots_storage_and_bounded(world, coll, client):
    token = csrf(client)
    target, elsewhere = coll.storage('Target box'), coll.storage('Elsewhere')
    away = coll.add_stock('part', world.plate, colour=world.white, quantity=1, condition='used', lot=world.bag, storage=elsewhere)
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=token, storage_id=target, selections=[dict(entity='lot', id=world.bag)]))
    assert move.status_code == 200, move.json
    db = coll.db
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[0] == target
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (away,)).fetchone()[0] == elsewhere, 'a part of the lot kept elsewhere stays'
    # Carried parts count against the 1000 limit and nothing is written when it is exceeded.
    big = coll.lot('Big lot', storage_id=world.shelf)
    ids = [coll.local('part', f'Bulk {i}', born_key=f'bulk{i}') for i in range(1000)]
    db.executemany("INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,lot_id,storage_id,created_at,updated_at) VALUES(?,'part',?,?,1,'used',?,?,?,?)",
                   [(f'b{i}', item, world.red, big, world.shelf, STAMP, STAMP) for i, item in enumerate(ids)])
    db.commit()
    over = client.post('/workbench/storage/action/move', json=dict(csrf_token=token, storage_id=target, selections=[dict(entity='lot', id=big)]))
    assert over.status_code == 400 and over.json['message'] == 'This lot holds 1000 parts · move it in parts or archive the storage'
    assert db.execute('SELECT storage_id FROM lot WHERE id=?', (big,)).fetchone()[0] == world.shelf
    assert db.execute('SELECT count(*) FROM stock WHERE lot_id=? AND storage_id=?', (big, world.shelf)).fetchone()[0] == 1000


def test_counts_by_type_without_double_counting_and_other_group(world, coll, client):
    mix = coll.storage('Mixed')
    lot = coll.lot('Lot of ten', storage_id=mix)
    inside = [coll.add_stock('part', coll.local('part', f'In {i}', born_key=f'in{i}'), colour=world.red, quantity=4, condition='used', lot=lot, storage=mix) for i in range(10)]
    coll.add_stock('part', world.brick, colour=world.red, quantity=2, condition='new', storage=mix)
    unknown = coll.add_stock('minifigure', coll.local('minifigure', 'Unknown figure'), quantity=1, condition='used', storage=mix, source='none')
    gear = coll.add_stock('gear', coll.local('gear', 'Gear thing'), quantity=1, condition='new', storage=mix)
    away = coll.storage('Away')
    coll.add_stock('part', world.plate, colour=world.white, quantity=7, condition='used', lot=lot, storage=away)         # a part of the lot that sits elsewhere
    db = coll.db
    counts = {r['id']: r for r in ledger.storages(db)}
    assert (counts[mix]['part_lots'], counts[mix]['figures'], counts[mix]['other']) == (2, 1, 1)           # the lot, one free part; the figure; the gear
    assert counts[away]['part_lots'] == 1, 'a loose part there, not part of the lot here'
    view = ledger.storage_view(db, mix)
    lot_row = next(r for r in view['part_lots'] if r['entity'] == 'lot')
    assert (lot_row['entries'], lot_row['quantity']) == (10, 40)                                              # only parts in the lot's own storage
    assert [r['id'] for r in view['other']] == [gear] and unknown in {r['id'] for r in view['figures']}
    assert all(r['item_type'] in ('P', 'L') for r in view['part_lots'])
    assert {r['id'] for r in view['part_lots'] if r.get('lot') == lot} == set(inside)
    soup = page(client, f'/workbench/storage/{mix}')
    groups = {g['data-group']: g for g in soup.select('.st-group')}
    assert set(groups) == {'figure', 'part', 'other'}
    assert 'Part lots · 2' in text(groups['part'].select_one('h2')), 'the ten parts are the lot, not ten more'
    assert len(groups['part'].select(f'[data-lot="{lot}"]')) == 10
    assert 'Gear thing' in text(groups['other']) and 'Other · 1' in text(groups['other'].select_one('h2'))
    row = next(r for r in soup.select('.st-row') if r.select_one('strong').get_text() == 'Mixed')
    assert text(row.select('.st-num')[2]) == '2'


def test_lot_move_undo_refused_when_the_lot_gained_parts(world, coll, client):
    token = csrf(client)
    target = coll.storage('Target box')
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=token, storage_id=target, selections=[dict(entity='lot', id=world.bag)]))
    assert move.status_code == 200
    later = coll.add_stock('part', world.plate, colour=world.white, quantity=1, condition='used', lot=world.bag, storage=target)
    undo = client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=move.json['event_id']))
    assert undo.status_code == 400 and 'gained parts' in undo.json['message']
    assert coll.db.execute('SELECT storage_id FROM lot WHERE id=?', (world.bag,)).fetchone()[0] == target
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', (STAMP, later))
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=move.json['event_id'])).status_code == 200


def test_storages_page_loads_the_storage_list_once(world, client, monkeypatch):
    seen = []
    original = ledger.storages
    monkeypatch.setattr(ledger, 'storages', lambda db: (seen.append(1), original(db))[1])
    assert client.get('/workbench/storage').status_code == 200
    assert client.get(f'/workbench/storage/{world.shelf}').status_code == 200
    assert len(seen) == 2                                                     # one per request
