"""Capture through audited source transport on the migration fixture."""
from contextlib import closing
import io
import json
import subprocess
from pathlib import Path

from PIL import Image
import pytest

from brickwork.core.connect import connect
from brickwork.core import part_inventory as inventory
from brickwork.core.sources import base
from tests.test_bw_add import bw, app, legacy, apps, client_token


def photo():
    output = io.BytesIO()
    Image.new('RGB', (24, 24), 'white').save(output, format='PNG')
    return output.getvalue()


def detect(client, csrf):
    return client.post('/workbench/part-to-inventory/detect', data=dict(csrf_token=csrf, endpoint='parts', file=(io.BytesIO(photo()), 'piece.png')))


def proposal(client, csrf):
    reply = detect(client, csrf)
    assert reply.status_code == 200, reply.json
    return dict(token=reply.json['token'], chosen=dict(item_type='P', item_no='bl-part', color_id=11, quantity=2))


@pytest.fixture
def source(monkeypatch):
    requests = []
    def transport(request):
        requests.append(request.full_url)
        return json.dumps(dict(items=[dict(type='part', id='bl-part', score=.91), dict(type='part', id='unknown', score=.8)]))
    monkeypatch.setattr(base, 'transport', transport)
    return requests


def test_flow_shell_capture_batch_lot_photos_undo(app, bw, source):
    client, csrf, _ = client_token(app)
    page = client.get('/workbench/part-to-inventory')
    assert page.status_code == 200
    assert page.headers['Cache-Control'] == 'no-store'
    html = page.get_data(as_text=True)
    for text in ['data-web-ui="toni"', 'Not available yet', 'Keep photos', '/workbench/part-to-inventory']:
        assert text in html
    piece = proposal(client, csrf)
    assert source == ['https://api.brickognize.com/predict/parts/']
    result = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=csrf, pieces=[piece], new_lot=dict(name='Pile test'), keep_photos=True))
    assert result.status_code == 200, result.json
    event = result.json['event']
    assert result.json['lot']['name'] == 'Pile test' and result.json['lot']['id']
    with closing(connect(bw)) as db:
        receipt = json.loads(db.execute('SELECT new_value FROM events WHERE id=?', (event,)).fetchone()[0])
        stock = db.execute('SELECT * FROM loose_stock WHERE id=?', (receipt['stock'][0],)).fetchone()
        assert (stock['quantity'], stock['color_id'], stock['condition'], stock['lot_id']) == (2, 11, 'U', receipt['lot'])
        image = db.execute('SELECT * FROM item_images WHERE stock_id=?', (stock['id'],)).fetchone()
        assert image['kind'] == 'own'
        assert (bw.parent / image['local_path']).is_file()
        assert db.execute('SELECT count(*) FROM identification_actions WHERE identification_id=?', (receipt['identifications'][0]['id'],)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM source_records WHERE source='brickognize' AND kind='predict'").fetchone()[0]
        assert db.execute("SELECT count(*) FROM events WHERE entity LIKE 'part_inventory:%' AND via!='app'").fetchone()[0] == 0
    assert client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=csrf, pieces=[piece], keep_photos=False)).json['event'] == event
    undone = client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=csrf, event=event))
    assert undone.status_code == 200, undone.json
    assert client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=csrf, event=event)).status_code == 200
    with closing(connect(bw)) as db:
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?', (stock['id'],)).fetchone()[0]
        assert db.execute('SELECT archived_at FROM lots WHERE id=?', (receipt['lot'],)).fetchone()[0]
        assert db.execute('SELECT 1 FROM identifications WHERE id=?', (receipt['identifications'][0]['id'],)).fetchone()
        assert receipt['identifications'][0]['id'] != stock['id']
        assert receipt['identifications'][0]['stock_id'] == stock['id']


def test_validation_atomicity_queue_limit_and_failures(app, bw, source, monkeypatch):
    client, csrf, _ = client_token(app)
    assert client.post('/workbench/part-to-inventory/detect', data=dict(csrf_token=csrf, file=(io.BytesIO(b'bad'), 'bad.png'))).status_code == 400
    assert client.post('/workbench/part-to-inventory/detect', data={}).status_code == 400
    piece = proposal(client, csrf)
    url = '/workbench/part-to-inventory/save'
    for pieces in [[], [piece]*7, [piece,piece], [{**piece, 'token':'tampered'}], [{**piece, 'chosen':{**piece['chosen'], 'color_id':None}}], [{**piece, 'chosen':{**piece['chosen'], 'item_no':'unknown'}}]]:
        with closing(connect(bw)) as db:
            before = db.execute('SELECT count(*) FROM loose_stock').fetchone()[0]
        assert client.post(url, json=dict(csrf_token=csrf,pieces=pieces,new_lot={'name':'Bad lot'})).status_code == 400
        with closing(connect(bw)) as db:
            assert db.execute('SELECT count(*) FROM loose_stock').fetchone()[0] == before
            assert not db.execute("SELECT 1 FROM lots WHERE name='Bad lot'").fetchone()
    monkeypatch.setattr(base, 'transport', lambda _: json.dumps({'items':[]}))
    assert 'Nothing identified' in detect(client, csrf).json['error']


def test_existing_lot_no_photos_changed_stock_blocks_undo(app, bw, source):
    client,csrf,_ = client_token(app)
    with closing(connect(bw)) as db,db:
        db.execute("INSERT INTO lots(id,name) VALUES('existing','Existing')")
    result=client.post('/workbench/part-to-inventory/save',json=dict(csrf_token=csrf,pieces=[proposal(client,csrf)],lot_id='existing',condition='N',keep_photos=False))
    assert result.status_code==200
    with closing(connect(bw)) as db,db:
        receipt=json.loads(db.execute('SELECT new_value FROM events WHERE id=?',(result.json['event'],)).fetchone()[0])
        assert not db.execute('SELECT 1 FROM item_images WHERE stock_id=?',(receipt['stock'][0],)).fetchone()
        db.execute('UPDATE loose_stock SET quantity=7 WHERE id=?',(receipt['stock'][0],))
    assert client.post('/workbench/part-to-inventory/undo',json=dict(csrf_token=csrf,event=result.json['event'])).status_code==400


def test_query_cost_list_and_batch_on_hundreds_of_rows(bw):
    import base64
    with closing(connect(bw)) as db:
        with db:
            db.executemany('INSERT INTO lots(id,name) VALUES(?,?)',[(f'lot-{i}',f'Pile {i}') for i in range(300)])
            db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,lot_id) VALUES(?,'P','bl-part',11,1,'U',?)",[(f'cost-{i}',f'lot-{i}') for i in range(300)])
        queries=[]
        db.set_trace_callback(queries.append)
        assert len(inventory.options(db)['lots']) == 300
        assert len(queries)==3
        queries.clear()
        pieces=[dict(id=f'piece-{i}', candidates=[dict(item_type='P',item_no='bl-part',score=.9)],chosen=dict(item_type='P',item_no='bl-part',color_id=11),photo=base64.b64encode(photo()).decode()) for i in range(6)]
        inventory.save(db,pieces,batch='cost',keep_photos=False)
        db.set_trace_callback(None)
        assert len(queries)<200
        receipt = json.loads(db.execute("SELECT new_value FROM events WHERE entity='part_inventory:cost' AND field='receipt'").fetchone()[0])
        assert len(set(receipt['stock'])) == 1
        assert db.execute('SELECT quantity FROM loose_stock WHERE id=?', (receipt['stock'][0],)).fetchone()[0] == 9
        assert [c['created'] for c in receipt['stock_changes']] == [False] * 6
        inventory.undo(db, db.execute("SELECT id FROM events WHERE entity='part_inventory:cost' AND field='receipt'").fetchone()[0])
        assert db.execute('SELECT quantity,archived_at FROM loose_stock WHERE id=?', (receipt['stock'][0],)).fetchone()[:] == (3, None)


def test_page_renders_3f_structure_without_old_controls(app, bw):
    with closing(connect(bw)) as db:
        with db:
            db.execute('INSERT INTO lots(id,name) VALUES(?,?)', ('lot-a', 'Pile A'))
    client, _, _ = client_token(app)
    html = client.get('/workbench/part-to-inventory').get_data(as_text=True)
    main = html[html.index('id="bw-inventory"'):]
    # Old chrome is gone: breadcrumb, fieldset and native dropdowns.
    assert 'class="breadcrumb"' not in html
    assert '<fieldset' not in main and '<select' not in main and '<legend' not in main
    # Camera row and recognition switch above the tabs; Local model is shown as not available.
    assert main.index('data-camera') < main.index('Recognition') < main.index('data-tab="capture"') < main.index('data-panel="capture"')
    assert 'role="listbox"' in main and 'Local model' in main and main.count('Not available yet') >= 1
    assert 'disabled aria-disabled="true"' in main and 'Brickognize</button>' in main
    # Capture, queue, review and results panels, viewfinder with guide, saved photo, batch sheet.
    for marker_text in ['data-panel="capture"', 'data-panel="queue"', 'data-panel="review"', 'data-panel="results"', 'class="guide"', 'data-slot', 'data-file', 'Add a saved photo', 'Enable camera',
                        'Take a picture or add a saved photo to begin.', 'Empty queue', 'Start reviewing', 'Review inventory batch', 'Loose parts', 'Assign to a lot', 'New lot', 'Keep photos', 'Used', 'data-undo']:
        assert marker_text in main, marker_text
    # Tabs with counts, identify switch, filter and sort switches, lot picker lists the lot.
    for marker_text in ['data-tab="queue"', 'data-tab="review"', 'data-tab="results"', 'data-endpoint="figs"', 'data-filter="error"', 'data-sort="name"', 'data-lot-option', 'Pile A']:
        assert marker_text in main, marker_text
    assert 'bw-inventory.css' in html and 'bw-inventory.js' in html


def test_page_shows_server_error_notice(app, bw):
    client, _, _ = client_token(app)
    html = client.get('/workbench/part-to-inventory').get_data(as_text=True)
    assert 'data-notice data-kind="info" hidden' in html


def test_browser_runtime():
    subprocess.run(['node',str(Path(__file__).with_name('toni_bw_inventory_runtime.cjs'))],check=True,capture_output=True,text=True)


def test_figures_budget_unresolved_and_local_images(app, bw, source, monkeypatch):
    client, csrf, _ = client_token(app)
    monkeypatch.setattr(base, 'transport', lambda request: {'items': [dict(type='minifig', id='bl-figure', score=.9)]})
    reply = client.post('/workbench/part-to-inventory/detect', data=dict(
        csrf_token=csrf, endpoint='figs', file=(io.BytesIO(photo()), 'figure.png')))
    assert reply.status_code == 200
    assert reply.json['candidates'][0]['item_type'] == 'M'
    result = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=csrf,
        pieces=[dict(token=reply.json['token'], chosen=dict(item_type='M', item_no='bl-figure', color_id=11))], keep_photos=False))
    assert result.status_code == 200
    with closing(connect(bw)) as db, db:
        # v3 local paths are trusted; the image route handles a deleted file.
        image_id = db.execute("INSERT INTO item_images(item_type,item_no,source,kind,url,local_path) VALUES('P','bl-part','rebrickable','render','https://example.invalid/part','data/images/missing.jpg')").lastrowid
        queries = []
        db.set_trace_callback(queries.append)
        rows, unresolved = inventory.candidates(db, [dict(item_type='P', item_no='bl-part', score=.91)] * 9)
        db.set_trace_callback(None)
        assert rows[0]['image'] == image_id
        assert len(queries) < 120
        db.execute("UPDATE id_match SET status='to_check' WHERE item_type='P' AND item_no='bl-part'")
        rows, unresolved = inventory.candidates(db, [dict(item_type='P', item_no='bl-part', score=.91)])
        assert not rows and unresolved[0]['reason'] == 'To check'
    monkeypatch.setenv('BW_BRICKOGNIZE_DAILY_BUDGET', '1')
    assert 'budget' in detect(client, csrf).json['error'].lower()


def test_lot_destination_required_and_invalid_engine(app, bw, source):
    client, csrf, _ = client_token(app)
    piece = proposal(client, csrf)
    assert client.post('/workbench/part-to-inventory/save', json=dict(
        csrf_token=csrf, pieces=[piece], destination='lot')).status_code == 400
    assert client.post('/workbench/part-to-inventory/detect', data=dict(
        csrf_token=csrf, endpoint='local', file=(io.BytesIO(photo()), 'part.png'))).status_code == 400


def test_expired_proposal_has_specific_feedback_and_no_writes(app, bw, source, monkeypatch):
    from itsdangerous import TimestampSigner
    client, csrf, _ = client_token(app)
    import time
    clock = [int(time.time())]
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: clock[0])
    piece = proposal(client, csrf)
    with closing(connect(bw)) as db:
        before = [list(db.execute('SELECT * FROM ' + table)) for table in ('events', 'loose_stock', 'identifications')]
    clock[0] += 3601
    response = client.post('/workbench/part-to-inventory/save',
                           json=dict(csrf_token=csrf, pieces=[piece]))
    assert response.status_code == 400
    assert response.json['error'] == 'This batch expired after an hour · identify the pieces again'
    with closing(connect(bw)) as db:
        assert [list(db.execute('SELECT * FROM ' + table)) for table in ('events', 'loose_stock', 'identifications')] == before


def test_undo_does_not_expire_with_proposal(app, bw, source, monkeypatch):
    from itsdangerous import TimestampSigner
    client, csrf, _ = client_token(app)
    import time
    clock = [int(time.time())]
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: clock[0])
    piece = proposal(client, csrf)
    saved = client.post('/workbench/part-to-inventory/save',
                        json=dict(csrf_token=csrf, pieces=[piece], keep_photos=False))
    assert saved.status_code == 200
    clock[0] += 3601
    undone = client.post('/workbench/part-to-inventory/undo',
                         json=dict(csrf_token=csrf, event=saved.json['event']))
    assert undone.status_code == 200


def test_save_after_undo_adds_again_and_undo_archives_identifications(app, bw, source):
    client, csrf, _ = client_token(app)
    live = "SELECT coalesce(sum(quantity),0) FROM loose_stock WHERE archived_at IS NULL AND item_no='bl-part'"
    with closing(connect(bw)) as db:
        base = db.execute(live).fetchone()[0]
    piece = proposal(client, csrf)
    first = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=csrf, pieces=[piece], keep_photos=False))
    assert first.status_code == 200, first.json
    assert client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=csrf, event=first.json['event'])).status_code == 200
    with closing(connect(bw)) as db:
        ident = json.loads(db.execute('SELECT new_value FROM events WHERE id=?', (first.json['event'],)).fetchone()[0])['identifications'][0]['id']
        assert db.execute('SELECT archived_at FROM identifications WHERE id=?', (ident,)).fetchone()[0]
        assert db.execute(live).fetchone()[0] == base
    again = client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=csrf, pieces=[piece], keep_photos=False))
    assert again.status_code == 200, again.json
    assert again.json['event'] != first.json['event']
    with closing(connect(bw)) as db:
        assert db.execute(live).fetchone()[0] == base + 2
        assert db.execute('SELECT archived_at FROM identifications WHERE id=?', (ident,)).fetchone()[0] is None
    # The live save is replayable and undoable on its own; the older undo does not cover it.
    assert client.post('/workbench/part-to-inventory/save', json=dict(csrf_token=csrf, pieces=[piece], keep_photos=False)).json['event'] == again.json['event']
    assert client.post('/workbench/part-to-inventory/undo', json=dict(csrf_token=csrf, event=again.json['event'])).status_code == 200
    with closing(connect(bw)) as db:
        assert db.execute(live).fetchone()[0] == base
