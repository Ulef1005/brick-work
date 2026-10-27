"""Part to Inventory on the 4.0 store (M.8e, issue #110): the page, the batch save and its Undo.

The recognition call (`/workbench/part-to-inventory/detect`, Brickognize) is Identify's (M.8h) and still answers 503; a test builds the
signed proposal the detect route would hand out (`proposal`). Gone with 3.3: the transport-mock and budget assertions
(`test_figures_budget_*`, the detect validation of `test_validation_atomicity_*`), which belong to the source client (M.8f/M.8h).
"""
import base64
import io
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image
import pytest

from brickwork.core import part_inventory as inventory
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)


def photo():
    output = io.BytesIO()
    Image.new('RGB', (24, 24), 'white').save(output, format='PNG')
    return output.getvalue()


def candidate(coll, key='3001', kind='parts'):
    return coll.item(kind, key)


def proposal(app4, client, world, coll, *, item=None, colour=None, quantity=2, piece='piece-1'):
    """What the signed detect reply carries for one piece, and the choice the review makes."""
    from brickwork.web.views import bw_add_signer
    item = item or world.brick
    token = csrf(client)
    shown = [dict(item_id=item, kind='part', score=.91)]
    with app4.test_request_context():
        signed = bw_add_signer().dumps(dict(id=piece, owner=token, candidates=shown, photo=base64.b64encode(photo()).decode()))
    return dict(token=signed, chosen=dict(item_id=item, color_id=world.red if colour is None else colour, quantity=quantity))


def test_flow_shell_capture_batch_lot_photos_undo(world, coll, app4, client):
    token = csrf(client)
    page = client.get('/workbench/part-to-inventory')
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store'
    html = page.get_data(as_text=True)
    for text in ['data-web-ui="toni"', 'Not available yet', 'Keep photos', '/workbench/part-to-inventory']:
        assert text in html
    piece = proposal(app4, client, world, coll)
    result = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[piece], new_lot=dict(name='Pile test'), keep_photos=True))
    assert result.status_code == 200, result.json
    event = result.json['event']
    assert result.json['lot']['name'] == 'Pile test' and result.json['lot']['id'] and result.json['lot']['created_date']
    db = coll.db
    receipt = json.loads(db.execute('SELECT new_value FROM event WHERE id=?', (event,)).fetchone()[0])
    stock = db.execute('SELECT * FROM stock WHERE id=?', (receipt['stock'][0]['id'],)).fetchone()
    assert (stock['quantity'], stock['color_id'], stock['condition'], stock['lot_id'], stock['item_id']) == (2, world.red, 'used', receipt['lot'], world.brick)
    own = db.execute('SELECT * FROM photo WHERE stock_id=?', (stock['id'],)).fetchone()
    assert own and (coll.db.execute('PRAGMA database_list').fetchone()[2] and Path(db.execute('PRAGMA database_list').fetchone()[2]).parent / own['local_path']).is_file()
    assert db.execute('SELECT count(*) FROM identification_action WHERE identification_id=?', ('piece-1',)).fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='part_inventory' AND via!='app'").fetchone()[0] == 0
    assert client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[piece], keep_photos=False)).json['event'] == event      # a retry
    undone = client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=token, event=event))
    assert undone.status_code == 200, undone.json
    assert client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=token, event=event)).status_code == 200
    assert db.execute('SELECT archived_at FROM stock WHERE id=?', (stock['id'],)).fetchone()[0]
    assert db.execute('SELECT archived_at FROM lot WHERE id=?', (receipt['lot'],)).fetchone()[0]
    assert db.execute('SELECT archived_at FROM photo WHERE id=?', (own['id'],)).fetchone()[0], 'the photo row is archived; the file is the person\'s'
    assert db.execute('SELECT archived_at FROM identification WHERE id=?', ('piece-1',)).fetchone()[0]
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_validation_atomicity_and_limits(world, coll, app4, client):
    token = csrf(client)
    piece = proposal(app4, client, world, coll)
    url = '/workbench/part-to-inventory/save'
    for pieces in [[], [piece] * 7, [piece, piece], [{**piece, 'token': 'tampered'}], [{**piece, 'chosen': {**piece['chosen'], 'color_id': None}}],
                   [{**piece, 'chosen': {**piece['chosen'], 'item_id': world.plate}}], [{**piece, 'chosen': {**piece['chosen'], 'item_id': 'x'}}],
                   [{**piece, 'chosen': {**piece['chosen'], 'quantity': 0}}]]:
        before = coll.db.execute('SELECT count(*) FROM stock').fetchone()[0]
        assert client.post(url, json=dict(csrf_token=token, pieces=pieces, new_lot={'name': 'Bad lot'})).status_code == 400
        assert coll.db.execute('SELECT count(*) FROM stock').fetchone()[0] == before
        assert not coll.db.execute("SELECT 1 FROM lot WHERE name='Bad lot'").fetchone()
    assert client.post(url, json=dict(csrf_token=token, pieces=[piece], destination='lot')).status_code == 400, 'a lot destination needs a lot'
    assert client.post(url, json=dict(pieces=[piece])).status_code == 400, 'no CSRF token'


def test_existing_lot_no_photos_changed_stock_blocks_undo(world, coll, app4, client):
    token = csrf(client)
    result = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[proposal(app4, client, world, coll)], lot_id=world.bag, condition='N', keep_photos=False))
    assert result.status_code == 200
    db = coll.db
    receipt = json.loads(db.execute('SELECT new_value FROM event WHERE id=?', (result.json['event'],)).fetchone()[0])
    stock_id = receipt['stock'][0]['id']
    assert db.execute('SELECT lot_id,condition FROM stock WHERE id=?', (stock_id,)).fetchone()[:] == (world.bag, 'new')
    assert not db.execute('SELECT 1 FROM photo WHERE stock_id=?', (stock_id,)).fetchone()
    coll.sql('UPDATE stock SET quantity=7 WHERE id=?', (stock_id,))
    refused = client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=token, event=result.json['event']))
    assert refused.status_code == 400 and 'changed' in refused.json['error']


def test_a_batch_that_meets_existing_stock_adds_to_it_and_undo_takes_it_back(world, coll):
    db = coll.db
    coll.sql('UPDATE stock SET lot_id=NULL, storage_id=NULL WHERE id=?', (world.stock_brick,))              # the world's red 3001 now has the batch's merge key
    pieces = [dict(id=f'piece-{i}', candidates=[dict(item_id=world.brick, score=.9)], chosen=dict(item_id=world.brick, color_id=world.red, quantity=1)) for i in range(6)]
    queries = []
    db.set_trace_callback(queries.append)
    event = inventory.save(db, pieces, batch='cost', condition='used', keep_photos=False)
    db.set_trace_callback(None)
    assert len(queries) < 200
    receipt = json.loads(db.execute('SELECT new_value FROM event WHERE id=?', (event,)).fetchone()[0])
    assert len({c['id'] for c in receipt['stock']}) == 1 and db.execute('SELECT quantity FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[0] == 9
    assert [c['created'] for c in receipt['stock']] == [False] * 6
    inventory.undo(db, event)
    assert db.execute('SELECT quantity,archived_at FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[:] == (3, None)


def test_options_cost_does_not_grow_with_the_lots(world, coll):
    db = coll.db
    for i in range(60):
        coll.lot(f'Pile {i}')
    queries = []
    db.set_trace_callback(queries.append)
    assert len(inventory.options(db)['lots']) == 61
    db.set_trace_callback(None)
    assert len(queries) == 3


def test_page_renders_3f_structure_without_old_controls(world, coll, client):
    coll.lot('Pile A')
    html = client.get('/workbench/part-to-inventory').get_data(as_text=True)
    main = html[html.index('id="bw-inventory"'):]
    # Old chrome is gone: breadcrumb, fieldset and native dropdowns.
    assert 'class="breadcrumb"' not in html
    assert '<fieldset' not in main and '<select' not in main and '<legend' not in main
    # Camera row and recognition switch above the tabs; Local model is shown as not available.
    assert main.index('data-camera') < main.index('Recognition') < main.index('data-tab="capture"') < main.index('data-panel="capture"')
    assert 'role="listbox"' in main and 'Local model' in main and main.count('Not available yet') >= 1
    assert 'disabled aria-disabled="true"' in main and 'Brickognize</button>' in main
    for marker_text in ['data-panel="capture"', 'data-panel="queue"', 'data-panel="review"', 'data-panel="results"', 'class="guide"', 'data-slot', 'data-file', 'Add a saved photo', 'Enable camera',
                        'Take a picture or add a saved photo to begin.', 'Empty queue', 'Start reviewing', 'Review inventory batch', 'Loose parts', 'Assign to a lot', 'New lot', 'Keep photos', 'Used', 'data-undo']:
        assert marker_text in main, marker_text
    for marker_text in ['data-tab="queue"', 'data-tab="review"', 'data-tab="results"', 'data-endpoint="figs"', 'data-filter="error"', 'data-sort="name"', 'data-lot-option', 'Pile A']:
        assert marker_text in main, marker_text
    assert 'bw-inventory.css' in html and 'bw-inventory.js' in html
    assert 'data-notice data-kind="info" hidden' in html


def test_candidates_come_from_typed_numbers_and_to_check_ones_are_listed_apart(world, coll):
    db = coll.db
    rows, unresolved = inventory.candidates(db, [dict(item_type='P', item_no='3001', score=.91), dict(item_type='P', item_no='nonsense', score=.5), dict(item_type='S', item_no='x', score=.4)])
    assert [r['item_id'] for r in rows] == [world.brick] and rows[0]['score'] == .91 and rows[0]['owned_summary']['total'] == 5
    assert [u['item_no'] for u in unresolved] == ['nonsense'] and unresolved[0]['reason'] == 'Unknown catalogue identity'
    coll.link(world.brick, '3001a', status='to_check')
    rows, unresolved = inventory.candidates(db, [dict(item_type='P', item_no='3001', score=.91)])
    assert not rows and unresolved[0]['reason'] == 'To check'
    queries = []
    db.set_trace_callback(queries.append)
    inventory.candidates(db, [dict(item_type='P', item_no='3001', score=.91)] * 9)
    db.set_trace_callback(None)
    assert len(queries) < 120


def test_detect_is_identify_and_not_yet_here(world, client):
    token = csrf(client)
    response = client.post('/workbench/part-to-inventory/detect', data=dict(csrf_token=token, endpoint='parts', file=(io.BytesIO(photo()), 'piece.png')))
    assert response.status_code == 503


def test_lot_destination_and_expired_proposals(world, coll, app4, client, monkeypatch):
    from itsdangerous import TimestampSigner
    import time
    token = csrf(client)
    clock = [int(time.time())]
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: clock[0])
    piece = proposal(app4, client, world, coll)
    before = [list(coll.db.execute('SELECT * FROM ' + table)) for table in ('event', 'stock', 'identification')]
    clock[0] += 3601
    response = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[piece]))
    assert response.status_code == 400 and response.json['error'] == 'This batch expired after an hour · identify the pieces again'
    assert [list(coll.db.execute('SELECT * FROM ' + table)) for table in ('event', 'stock', 'identification')] == before
    clock[0] = int(time.time())
    piece = proposal(app4, client, world, coll, piece='piece-2')
    saved = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[piece], keep_photos=False))
    assert saved.status_code == 200
    clock[0] += 3601
    assert client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=token, event=saved.json['event'])).status_code == 200, 'Undo does not expire with the proposal'


def test_save_after_undo_adds_again_and_undo_archives_identifications(world, coll, app4, client):
    token = csrf(client)
    live = "SELECT coalesce(sum(quantity),0) FROM stock WHERE archived_at IS NULL AND item_id=? AND color_id=?"
    base = coll.db.execute(live, (world.brick, world.red)).fetchone()[0]
    piece = proposal(app4, client, world, coll)
    first = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[piece], keep_photos=False))
    assert first.status_code == 200, first.json
    assert client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=token, event=first.json['event'])).status_code == 200
    assert coll.db.execute('SELECT archived_at FROM identification WHERE id=?', ('piece-1',)).fetchone()[0]
    assert coll.db.execute(live, (world.brick, world.red)).fetchone()[0] == base
    again = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[piece], keep_photos=False))
    assert again.status_code == 200 and again.json['event'] != first.json['event']
    assert coll.db.execute(live, (world.brick, world.red)).fetchone()[0] == base + 2
    assert coll.db.execute('SELECT archived_at FROM identification WHERE id=?', ('piece-1',)).fetchone()[0] is None
    # The live save is replayable and undoable on its own; the older undo does not cover it.
    assert client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=token, pieces=[piece], keep_photos=False)).json['event'] == again.json['event']
    assert client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=token, event=again.json['event'])).status_code == 200
    assert coll.db.execute(live, (world.brick, world.red)).fetchone()[0] == base


def test_browser_runtime():
    if not shutil.which('node'):
        pytest.skip('node is not installed')
    subprocess.run(['node', str(Path(__file__).with_name('toni_bw_inventory_runtime.cjs'))], check=True, capture_output=True, text=True)
