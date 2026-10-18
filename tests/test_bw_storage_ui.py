"""Storage rebuild to 12c: table, contents panel, select and move, sheets, empty states, purchase locations."""
from contextlib import closing
import shutil
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup

from brickwork.core import ledger
from brickwork.core.connect import connect
from tests.test_bw_add import app, bw, legacy, apps, client_token
from tests.test_bw_orders_storage import trace


def page(client, url='/workbench/storage'):
    response = client.get(url)
    assert response.status_code == 200, response.text[-1500:]
    return BeautifulSoup(response.text, 'html.parser')


def text(node):
    return ' '.join(node.get_text(' ').split())


def test_table_rows_do_not_run_together_and_select_the_first_storage(app, bw):
    client, _, _ = client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO storages(id,name) VALUES('second','Single Carton Box')")
        db.execute("INSERT INTO storages(id,name) VALUES('empty','Original Box on Display')")
    soup = page(client)
    rows = soup.select('.st-table [data-row]')
    # Each storage is its own anchor row (the old list ran 0 pieces and the next name into one line).
    assert len(rows) >= 4 and all(r.name == 'a' for r in rows)
    names = [r.select_one('.st-name strong').get_text() for r in rows]
    assert {'Single Carton Box', 'Original Box on Display', 'Not stored'} <= set(names)
    assert names[-1] == 'Not stored'
    for row in rows:
        assert row.select_one('.st-name strong') and len(row.select('.st-num')) == 3
    head = [text(n) for n in soup.select('.st-thead [role=columnheader]')]
    assert head == ['Storage', 'Sets', 'Figures', 'Part lots']
    selected = soup.select('.st-row.is-selected')
    assert len(selected) == 1 and selected[0]['aria-current'] == 'page'
    assert soup.select_one('.st-pane h1').get_text() == selected[0].select_one('strong').get_text()
    summary = text(soup.select_one('.st-head p'))
    assert summary.startswith(f'{len([n for n in names if n != "Not stored"])} storages · ')
    assert 'sets' in summary and 'figures' in summary and 'part lots' in summary
    # The list count skips the Not stored row too, so header and list agree.
    assert [r.select_one('strong').get_text() for r in rows if r.has_attr('data-uncounted')] == ['Not stored']


def test_contents_panel_groups_sets_figures_and_part_lots(app, bw):
    client, _, _ = client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("UPDATE copies SET storage_id='store',condition='U' WHERE id='copy'")
        db.execute("UPDATE loose_stock SET storage_id='store' WHERE id='loose-part'")
        db.execute("INSERT INTO lots(id,name,storage_id) VALUES('lot','Grey lot','store')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition,storage_id) VALUES('fig','M','bl-figure',1,'U','store')")
    soup = page(client, '/workbench/storage/store')
    groups = {g['data-group']: g for g in soup.select('.st-group')}
    assert set(groups) >= {'set', 'figure', 'part'}
    assert 'Sets · 1' in text(groups['set'].select_one('h2'))
    assert 'Used' in text(groups['set'])  # condition shown on the set row
    assert 'Minifigures' in text(groups['figure'].select_one('h2')) and groups['figure'].select_one('.st-pill').get_text() == 'Used'
    part = groups['part']
    assert 'Grey lot' in text(part) and 'Lot ·' in text(part)  # lots sit with the part lots
    assert part.select_one('.bw-colour') is not None  # loose part keeps its colour chip
    assert '×' in text(part)
    for img in soup.select('.st-pic img'):
        assert img['alt'] == '' and 'cover' not in str(img)
    # Counts line, Select and Edit are present; every row carries a selectable id.
    assert 'sets ·' in text(soup.select_one('.st-detail-head p'))
    assert soup.select_one('[data-select]').get_text() == 'Select'
    assert soup.select_one('[data-open=st-edit]')
    for box in soup.select('.st-check'):
        assert box['data-selection'] and box['aria-label'].startswith('Select ')
    # The first-storage default and the explicit route show the same contents.
    entities = {__import__('json').loads(b['data-selection'])['entity'] for b in soup.select('.st-check')}
    assert entities == {'copy', 'stock', 'lot'}


def test_select_mode_markup_and_move_of_set_figure_and_lot_with_undo(app, bw):
    client, csrf, _ = client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO storages(id,name) VALUES('target','Target box')")
        db.execute("UPDATE copies SET storage_id='store' WHERE id='copy'")
        db.execute("INSERT INTO lots(id,name,storage_id) VALUES('lot','Grey lot','store')")
    soup = page(client, '/workbench/storage/store')
    form = soup.select_one('form[data-action=move]')
    assert form.select_one('[data-bar]').has_attr('hidden') and form.select_one('[data-move-open]').has_attr('disabled')
    assert 'Move to another storage' in text(form.select_one('[data-bar]'))
    sheet = form.select_one('dialog#st-move')  # the sheet sits inside the form, so its select is submitted with the selection
    assert [o.get_text() for o in sheet.select('option')][0] == 'Not stored'
    assert 'Target box' in text(sheet) and 'Move selected items' in text(sheet)
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id='target',
        selections=[dict(entity='copy', id='copy'), dict(entity='lot', id='lot')]))
    assert move.status_code == 200, move.json
    with closing(connect(bw)) as db:
        assert db.execute("SELECT storage_id FROM copies WHERE id='copy'").fetchone()[0] == 'target'
        assert db.execute("SELECT storage_id FROM lots WHERE id='lot'").fetchone()[0] == 'target'
        event = db.execute('SELECT via,new_value FROM events WHERE id=?', (move.json['event_id'],)).fetchone()
        assert event['via'] == 'app' and '"lots"' in event['new_value']
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=csrf, event_id=move.json['event_id'])).status_code == 200
    with closing(connect(bw)) as db:
        assert db.execute("SELECT storage_id FROM copies WHERE id='copy'").fetchone()[0] == 'store'
        assert db.execute("SELECT storage_id FROM lots WHERE id='lot'").fetchone()[0] == 'store'
    bad = client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id='target', selections=[dict(entity='lot', id='missing')]))
    assert bad.status_code == 400
    assert client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id='target', selections=[dict(entity='wish', id='1')])).status_code == 400


def test_add_and_edit_sheets_keep_every_function(app, bw):
    client, csrf, _ = client_token(app)
    soup = page(client, '/workbench/storage/store')
    add = soup.select_one('dialog#st-add form[data-action=save]')
    assert add and add.select_one('input[name=name][required]') and 'Add storage' in text(add)
    assert add.get('data-context') is None  # no id: creates
    edit = soup.select_one('dialog#st-edit')
    assert edit.select_one('form#st-edit-form')['data-context'] == '{"id": "store"}'
    assert edit.select_one('input[name=name]')['value']
    archive = edit.select_one('form[data-action=archive]')
    assert archive.select_one('input[name=move_to_unstored]') and archive.select_one('.bw-archive')
    assert soup.select_one('[data-open=st-add]') and soup.select_one('[data-open=st-edit]')
    # Create, rename and archive still go through one transaction with an events row.
    made = client.post('/workbench/storage/action/save', json=dict(csrf_token=csrf, name='Drawer 14'))
    assert made.status_code == 200 and made.json['url'].startswith('/workbench/storage/')
    with closing(connect(bw)) as db:
        assert db.execute('SELECT 1 FROM events WHERE id=?', (made.json['event_id'],)).fetchone()
    assert 'Drawer 14' in page(client, made.json['url']).select_one('.st-pane h1').get_text()
    gone = client.post('/workbench/storage/action/archive', json=dict(csrf_token=csrf, id=made.json['url'].rsplit('/', 1)[1]))
    assert gone.status_code == 200
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=csrf, event_id=gone.json['event_id'])).status_code == 200


def test_empty_storage_and_no_storages_states(app, bw):
    client, csrf, _ = client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO storages(id,name) VALUES('void','Box 5')")
        db.execute("UPDATE copies SET storage_id='store' WHERE id='copy'")
    soup = page(client, '/workbench/storage/void')
    empty = soup.select_one('.st-pane .st-empty')
    assert text(empty.select_one('h2')) == 'Box 5 is empty.'
    assert 'select mode' in text(empty)
    assert empty.select_one('a.st-outline').get_text().startswith('Go to ')
    assert not soup.select('[data-select]') and not soup.select('.st-group')  # nothing to select
    with closing(connect(bw)) as db, db:
        db.execute("UPDATE copies SET storage_id=NULL")
        db.execute("UPDATE loose_stock SET storage_id=NULL")
        db.execute("UPDATE lots SET storage_id=NULL")
        db.execute("UPDATE storages SET archived_at='old'")
    soup = page(client)
    solo = soup.select_one('.st-solo')
    assert text(solo.select_one('h2')) == 'No storages yet.'
    assert 'Add a box, drawer or shelf' in text(solo)
    assert solo.select_one('button[data-open=st-add]') and soup.select_one('dialog#st-add')
    assert 'Not stored' in text(solo.select_one('.st-note'))  # the unassigned items stay reachable
    assert page(client, '/workbench/storage/unstored').select_one('.st-pane h1').get_text() == 'Not stored'


def test_history_stays_reachable_and_undo_works(app, bw):
    client, csrf, _ = client_token(app)
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id=None, selections=[dict(entity='copy', id='copy')]))
    assert move.status_code == 200
    soup = page(client)
    history = soup.select_one('details.st-history')
    assert history.select_one('summary').get_text() == 'History'
    assert history.select_one(f'[data-undo-event="{move.json["event_id"]}"]')


def test_purchase_locations_page(app, bw):
    client, _, _ = client_token(app)
    response = client.get('/collection/purchase-places')
    assert response.headers['Cache-Control'] == 'no-store'
    soup = BeautifulSoup(response.text, 'html.parser')
    assert soup.select_one('[data-web-ui="toni"]') and soup.select_one('a[href="/collection/sets"]')
    assert text(soup.select_one('h1')) == 'Purchase locations'
    assert 'Where things came from' in text(soup)
    tabs = soup.select('.pl-tabs nav a')
    assert [text(a) for a in tabs] == ['Storages', 'Purchase locations'] and tabs[1]['aria-current'] == 'page'
    assert tabs[0]['href'] == '/workbench/storage'
    assert 'values' in soup.select_one('a.pl-add')['href'] and 'purchase-places' in soup.select_one('a.pl-add')['href']
    assert any(a.get('aria-current') == 'page' and a['href'] == '/workbench/storage' for a in soup.select('[aria-current=page]'))
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO purchase_locations(id,name) VALUES('corner','Brick Corner')")
        db.execute("UPDATE copies SET purchase_location_id='corner',purchase_price='12.5',purchase_currency='EUR' WHERE id='copy'")
    soup = page(client, '/collection/purchase-places')
    row = next(r for r in soup.select('.st-row') if 'Brick Corner' in r.get_text())
    nums = [n.get_text() for n in row.select('.st-num')]
    assert nums[:2] == ['—', '1'] and '€12.50' in text(row)  # Orders (derived), Copies
    assert row.select_one('a.pl-name')['href'].endswith('?place=corner')
    assert [o.get_text() for o in row.select('select[name=kind] option')][:3] == ['Not set', 'BrickLink store', 'Online shop']


def test_storage_counts_and_queries(bw):
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO lots(id,name,storage_id) VALUES('lot','Lot','store')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id) VALUES('fig','M','bl-figure',1,'store')")
    with closing(connect(bw)) as db:
        store = next(r for r in ledger.storages(db) if r['id'] == 'store')
        assert store['figures'] == 1 and store['part_lots'] >= 1 and store['other'] == 0
        assert trace(db, lambda: ledger.storages(db)) == 1
        assert trace(db, lambda: ledger.storage_view(db, 'store')) < 12
        view = ledger.storage_view(db, 'store')
        assert view['total'] == len(view['sets']) + len(view['figures']) + len(view['part_lots']) + len(view['other'])
        assert [r['id'] for r in view['rows']] == [r['id'] for r in ledger.storage_detail(db, 'store')['rows']]


def test_storage_runtime():
    subprocess.run([shutil.which('node'), str(Path(__file__).with_name('toni_bw_storage_runtime.cjs'))], check=True, capture_output=True, text=True)


def test_lot_move_carries_its_parts_and_one_undo_restores_both(app, bw):
    client, csrf, _ = client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO storages(id,name) VALUES('target','Target box')")
        db.execute("INSERT INTO lots(id,name,storage_id) VALUES('lot','Grey lot','store')")
        db.execute("UPDATE loose_stock SET lot_id='lot',storage_id='store' WHERE id='loose-part'")
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id='target', selections=[dict(entity='lot', id='lot')]))
    assert move.status_code == 200, move.json
    with closing(connect(bw)) as db:
        assert db.execute("SELECT storage_id FROM lots WHERE id='lot'").fetchone()[0] == 'target'
        assert db.execute("SELECT storage_id FROM loose_stock WHERE id='loose-part'").fetchone()[0] == 'target'
        target = ledger.storage_view(db, 'target')
        assert {r['id'] for r in target['part_lots']} >= {'lot', 'loose-part'}
        assert 'loose-part' not in {r['id'] for r in ledger.storage_view(db, 'store')['part_lots']}
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=csrf, event_id=move.json['event_id'])).status_code == 200
    with closing(connect(bw)) as db:
        assert db.execute("SELECT storage_id FROM lots WHERE id='lot'").fetchone()[0] == 'store'
        assert db.execute("SELECT storage_id FROM loose_stock WHERE id='loose-part'").fetchone()[0] == 'store'


def test_lot_carry_is_scoped_to_the_lots_storage_and_bounded(app, bw):
    client, csrf, _ = client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO storages(id,name) VALUES('target','Target box')")
        db.execute("INSERT INTO storages(id,name) VALUES('elsewhere','Elsewhere')")
        db.execute("INSERT INTO lots(id,name,storage_id) VALUES('lot','Grey lot','store')")
        db.execute("UPDATE loose_stock SET lot_id='lot',storage_id='elsewhere' WHERE id='loose-part'")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id,lot_id) VALUES('inside','P','bl-part',1,'store','lot')")
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id='target', selections=[dict(entity='lot', id='lot')]))
    assert move.status_code == 200, move.json
    with closing(connect(bw)) as db:
        assert db.execute("SELECT storage_id FROM loose_stock WHERE id='inside'").fetchone()[0] == 'target'
        assert db.execute("SELECT storage_id FROM loose_stock WHERE id='loose-part'").fetchone()[0] == 'elsewhere'
    # Carried parts count against the 1000 limit and nothing is written when it is exceeded.
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO lots(id,name,storage_id) VALUES('big','Big lot','store')")
        db.executemany("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id,lot_id) VALUES(?,'P','bl-part',1,'store','big')", [(f'b{i}',) for i in range(1000)])
    over = client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id='target', selections=[dict(entity='lot', id='big')]))
    assert over.status_code == 400 and over.json['message'] == 'This lot holds 1000 parts · move it in parts or archive the storage'
    with closing(connect(bw)) as db:
        assert db.execute("SELECT storage_id FROM lots WHERE id='big'").fetchone()[0] == 'store'
        assert db.execute("SELECT count(*) FROM loose_stock WHERE lot_id='big' AND storage_id='store'").fetchone()[0] == 1000


def test_counts_by_type_without_double_counting_and_other_group(app, bw):
    client, _, _ = client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO storages(id,name) VALUES('mix','Mixed')")
        db.execute("INSERT INTO lots(id,name,storage_id) VALUES('lot','Lot of ten','mix')")
        db.executemany("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id,lot_id) VALUES(?,'P','bl-part',4,'mix','lot')", [(f'in{i}',) for i in range(10)])
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id) VALUES('free','P','bl-part',2,'mix')")
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('?','ph-1','Placeholder figure')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id) VALUES('ph','?','ph-1',1,'mix')")
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('G','gear-1','Gear thing')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id) VALUES('gear','G','gear-1',1,'mix')")
        # A part of the lot that sits elsewhere is a loose part there, not part of the lot here.
        db.execute("INSERT INTO storages(id,name) VALUES('away','Away')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id,lot_id) VALUES('apart','P','bl-part',7,'away','lot')")
    with closing(connect(bw)) as db:
        counts = {r['id']: r for r in ledger.storages(db)}
        assert (counts['mix']['part_lots'], counts['mix']['figures'], counts['mix']['other']) == (2, 1, 1)  # the lot, one free part; placeholder; gear
        assert counts['away']['part_lots'] == 1
        view = ledger.storage_view(db, 'mix')
        lot = next(r for r in view['part_lots'] if r['entity'] == 'lot')
        assert (lot['entries'], lot['quantity']) == (10, 40)  # only parts in the lot's own storage
        assert [r['id'] for r in view['other']] == ['gear'] and 'ph' in {r['id'] for r in view['figures']}
        assert all(r['item_type'] in ('P', 'L') for r in view['part_lots'])
        assert {r['id'] for r in view['part_lots'] if r.get('lot') == 'lot'} == {f'in{i}' for i in range(10)}
    soup = page(client, '/workbench/storage/mix')
    groups = {g['data-group']: g for g in soup.select('.st-group')}
    assert set(groups) == {'figure', 'part', 'other'}
    assert 'Part lots · 2' in text(groups['part'].select_one('h2'))  # the ten parts are the lot, not ten more
    assert len(groups['part'].select('[data-lot=lot]')) == 10
    assert 'Unknown colour' not in text(groups['other']) and 'Gear thing' in text(groups['other'])
    assert 'Other · 1' in text(groups['other'].select_one('h2'))
    row = next(r for r in soup.select('.st-row') if r.select_one('strong').get_text() == 'Mixed')
    assert text(row.select('.st-num')[2]) == '2'


def test_lot_move_undo_refused_when_the_lot_gained_parts(app, bw):
    client, csrf, _ = client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO storages(id,name) VALUES('target','Target box')")
        db.execute("INSERT INTO lots(id,name,storage_id) VALUES('lot','Grey lot','store')")
        db.execute("UPDATE loose_stock SET lot_id='lot',storage_id='store' WHERE id='loose-part'")
    move = client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id='target', selections=[dict(entity='lot', id='lot')]))
    assert move.status_code == 200
    with closing(connect(bw)) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,storage_id,lot_id) VALUES('later','P','bl-part',1,'target','lot')")
    undo = client.post('/workbench/storage/action/undo', json=dict(csrf_token=csrf, event_id=move.json['event_id']))
    assert undo.status_code == 400 and 'gained parts' in undo.json['message']
    with closing(connect(bw)) as db:
        assert db.execute("SELECT storage_id FROM lots WHERE id='lot'").fetchone()[0] == 'target'
    with closing(connect(bw)) as db, db:
        db.execute("DELETE FROM loose_stock WHERE id='later'")
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=csrf, event_id=move.json['event_id'])).status_code == 200


def test_storages_page_loads_the_storage_list_once(app, bw):
    client, _, _ = client_token(app)
    seen = []
    original = ledger.storages
    import brickwork.core.ledger as module
    module.storages = lambda db: (seen.append(1), original(db))[1]
    try:
        assert client.get('/workbench/storage').status_code == 200
        assert client.get('/workbench/storage/store').status_code == 200
    finally:
        module.storages = original
    assert len(seen) == 2  # one per request


def test_storage_api_reports_figures_and_part_lots(app, bw):
    from brickwork.api.serializers import FIELDS
    assert {'figures', 'part_lots'} <= set(FIELDS['Storage'])
