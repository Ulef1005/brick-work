"""Order API receipts, history and Undo, waiting for API v2 (split out of `test_bw_orders_storage.py` by M.8h, issue #110).

M.8h ported the order flows of that file to the 4.0 store; these four tests belong to the API (`core/api_writes`, `core/api_orders`, the
`bw_api` event bundle), which M.11 rewrites. They are the 3.3 text, untouched, and wait here with their 3.3 helpers. Not collected: see
`tests/quarantine.py`. The allocation-target upgrade test has no 4.0 counterpart (4.0 starts with the columns): M.11 keeps its API half
(`target_type` of an allocation in the list answer)."""
from contextlib import closing
import json

from brickwork.core import orders, ledger
from brickwork.core.connect import connect
from tests.test_bw_add import app, bw, legacy, apps, client_token
from tests.test_bw_orders_storage import saved


def test_api_receipts_undo_through_web(app, bw, monkeypatch):
    from tests.test_bw_api_m3 import write
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    client, csrf, _ = client_token(app)
    with closing(connect(bw)) as db:
        oid, _, lid = saved(db)
        destination, _ = ledger.storage_save(db, None, 'Destination')
    cases = [
        ('storage', f'/storages/{destination}/contents', dict(selections=[dict(entity='copy', id='copy')]), '/workbench/storage'),
        ('orders', f'/orders/{oid}/received', dict(counts={str(lid):2}), f'/workbench/orders/{oid}'),
    ]
    for route, path, body, page in cases:
        response = write(app, path, body=body, key=route)
        assert response.status_code == 200, response.text
        event = response.json['event_id']
        assert f'data-undo-event="{event}"' in client.get(page).text
        url = f'/workbench/{route}/action/undo'
        assert client.post(url, json=dict(csrf_token=csrf, event_id=event)).status_code == 200
        with closing(connect(bw)) as db:
            if route == 'storage':
                assert db.execute("SELECT storage_id FROM copies WHERE id='copy'").fetchone()[0] == 'store'
            else:
                assert db.execute('SELECT received FROM line_receipts WHERE line_id=?', (lid,)).fetchone()[0] == 0
            before = db.execute('SELECT count(*) FROM events').fetchone()[0]
        again = client.post(url, json=dict(csrf_token=csrf, event_id=event))
        assert again.status_code == 400 and 'already been undone' in again.json['message']
        with closing(connect(bw)) as db:
            assert db.execute('SELECT count(*) FROM events').fetchone()[0] == before


def test_history_sql_filters_and_bounds_api_events(bw, monkeypatch):
    import time
    from brickwork.core import admin
    with closing(connect(bw)) as db, db:
        receipt = dict(entity='bw_ledger', field='receipt', new_value=json.dumps(dict(action='move', storage_id='target', changes=[])))
        for i in range(10000):
            admin.audit(db, 'bw_api', 'op:history-'+str(i), new=dict(receipts=[dict(receipt, new_value=json.dumps(dict(action='move', storage_id='other', changes=[])))]))
        for _ in range(210):
            admin.audit(db, 'bw_api', 'receipt', new=dict(receipts=[receipt, receipt]))
        # Only matching, bounded receipts may cross into Python, even with 10k irrelevant operations.
        real_loads = json.loads
        decoded = []
        def loads(value, *args, **kw):
            decoded.append(value)
            return real_loads(value, *args, **kw)
        monkeypatch.setattr(ledger.json, 'loads', loads)
        trace = []
        db.set_trace_callback(trace.append)
        start = time.monotonic()
        rows = ledger.history(db, storage_id='target')
        elapsed = time.monotonic()-start
        db.set_trace_callback(None)
        assert len(rows) == len(decoded) == 200
        assert all(r['receipt_count'] == 2 and r['undo_available'] for r in rows)
        assert len(trace) == 1
        assert elapsed < 2, elapsed
        assert 'json_each' in trace[0] and 'json_valid' in trace[0]
        plan = ' '.join(str(tuple(r)) for r in db.execute('EXPLAIN QUERY PLAN '+trace[0]))
        assert 'events_api_receipts' in plan


def test_allocation_target_upgrade_is_idempotent_and_preserves_unknown(app, bw, monkeypatch):
    from brickwork.core import upgrade
    from brickwork.api.serializers import public
    from tests.test_bw_api_m1_contract import validate
    with closing(connect(bw)) as db, db:
        oid, _, lid = saved(db)
        for kind, copy in [('missing_part', 'copy'), ('loose_part', None), ('unknown', None)]:
            db.execute('INSERT INTO allocations(order_id,line_id,kind,copy_id,qty,state) VALUES(?,?,?,?,1,\'applied\')', (oid, lid, kind, copy))
        assert upgrade.pending(db)
        upgrade.upgrade_connection(db)
        assert not upgrade.pending(db)
        before = [dict(r) for r in db.execute('SELECT * FROM allocations')]
        assert [r['target_type'] for r in before] == ['copy', 'stock', None]
        for row in before:
            validate(public(row, 'Allocation'), {'$ref': '#/components/schemas/Allocation'})
        upgrade.upgrade_connection(db)
        assert before == [dict(r) for r in db.execute('SELECT * FROM allocations')]
    from tests.test_bw_api_m1 import call
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    response = call(app, f'/orders/{oid}/allocations')
    assert response.status_code == 200, response.text
    validate(response.json, {'$ref': '#/components/schemas/ListOfAllocation'})
    assert next(r for r in response.json['data'] if r['kind'] == 'unknown')['target_type'] is None


def test_web_undo_reverses_every_bundled_ledger_receipt(app, bw):
    from brickwork.core import api_writes
    client, csrf, _ = client_token(app)
    with closing(connect(bw)) as db:
        def bundle():
            ledger.storage_save(db, 'store', 'First rename')
            ledger.storage_save(db, 'store', 'Second rename')
            return dict(message='Saved'), 200
        result, _ = api_writes.execute(db, method='PATCH', path='/synthetic-bundle', body={},
            key='bundle', required=True, token_name='synthetic', action=bundle)
        original = json.loads(db.execute('SELECT new_value FROM events WHERE id=?', (result['event_id'],)).fetchone()[0])['receipts'][0]
        name = json.loads(original['new_value'])['changes'][0]['old'][0]['name']
    page = client.get('/workbench/storage').text
    assert 'Undo reverses all 2 receipts in this API operation' in page
    response = client.post('/workbench/storage/action/undo', json=dict(csrf_token=csrf, event_id=result['event_id']))
    assert response.status_code == 200, response.text
    with closing(connect(bw)) as db:
        assert db.execute("SELECT name FROM storages WHERE id='store'").fetchone()[0] == name
