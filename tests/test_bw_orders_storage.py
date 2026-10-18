"""Orders and storage on the real v3 migration fixture; transports are offline."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from brickwork.core import orders, ledger
from brickwork.core.connect import connect
from tests.test_bw_add import app, bw, legacy, apps, client_token
from tests.test_bw_workbench import gaps

XML='<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>bl-part</ITEMID><COLOR>11</COLOR><QTY>3</QTY><CONDITION>U</CONDITION><PRICE>0.12</PRICE></ITEM></INVENTORY>'


def saved(db, text=XML):
    result=orders.import_document(db,'xml',text)
    oid,did=result['order_id'],result['document_id']
    orders.phase(db,oid,did,'review');orders.phase(db,oid,did,'save')
    return oid,did,orders.detail(db,oid)['saved'][0]['id']


def test_routes_shell_resume_and_storage_flow(app,bw):
    client,csrf,_=client_token(app)
    for url in ['/workbench/orders','/workbench/storage','/workbench/storage/store','/workbench/storage/unstored']:
        response=client.get(url)
        assert response.status_code==200, response.text[-2000:]
        assert 'data-web-ui="toni"' in response.text
        assert 'href="/workbench/orders"' in response.text
        assert 'href="/workbench/storage"' in response.text
        assert response.headers['Cache-Control']=='no-store'
        from bs4 import BeautifulSoup
        current=BeautifulSoup(response.text,'html.parser').select('[aria-current=page]')
        expected='/workbench/orders' if 'orders' in url else '/workbench/storage'
        assert any(n.get('href')==expected for n in current)
    r=client.post('/workbench/orders/action/import',json=dict(csrf_token=csrf,source='xml',text=XML))
    assert r.status_code==200, r.json
    oid=r.json['order_id'];did=r.json['document_id']
    assert 'Resume review' in client.get(r.json['url']).text
    assert client.post('/workbench/orders/action/import',json=dict(csrf_token=csrf,source='xml',text=XML)).json['duplicate']
    for action in ('review','save'):
        assert client.post('/workbench/orders/action/'+action,json=dict(csrf_token=csrf,order_id=oid,document_id=did)).status_code==200
    with closing(connect(bw)) as db:
        lid=orders.detail(db,oid)['saved'][0]['id']
    r=client.post('/workbench/orders/action/received',json=dict(csrf_token=csrf,order_id=oid,counts={str(lid):2}))
    assert r.status_code==200
    assert '1 short' in client.get('/workbench/orders/'+str(oid)).text
    assert 'MINQTY>1' in client.get('/workbench/orders/'+str(oid)+'/short.xml').text
    for action in ('hold','hold'):
        r=client.post('/workbench/orders/action/'+action,json=dict(csrf_token=csrf,order_id=oid,line_id=lid,held=action=='hold'))
        assert r.status_code==200
        assert client.post('/workbench/orders/action/undo',json=dict(csrf_token=csrf,event_id=r.json['event_id'])).status_code==200
    move=client.post('/workbench/storage/action/move',json=dict(csrf_token=csrf,storage_id=None,selections=[dict(entity='copy',id='copy')]))
    assert move.status_code==200
    with closing(connect(bw)) as db:
        assert db.execute("SELECT storage_id FROM copies WHERE id='copy'").fetchone()[0] is None
        assert db.execute('SELECT via FROM events WHERE id=?',(move.json['event_id'],)).fetchone()[0]=='app'
    assert client.post('/workbench/storage/action/undo',json=dict(csrf_token=csrf,event_id=move.json['event_id'])).status_code==200
    edit=client.post('/workbench/storage/action/save',json=dict(csrf_token=csrf,id='store',name='Box 1'))
    assert edit.status_code==200
    assert 'Box 1' in client.get(edit.json['url']).text
    assert client.post('/workbench/storage/action/undo',json=dict(csrf_token=csrf,event_id=edit.json['event_id'])).status_code==200
    assert client.post('/workbench/storage/action/archive',json=dict(csrf_token=csrf,id='store')).status_code==400


def test_copy_and_stock_allocation_manual_derived_undo(gaps):
    path,part=gaps
    with closing(connect(path)) as db:
        oid,did,lid=saved(db)
        received=orders.received(db,oid,{lid:3})
        allocated=orders.allocate(db,oid,[dict(line_id=lid,target_type='copy',copy_id='copy',target='part',target_id=part,quantity=2),dict(line_id=lid,target_type='stock',quantity=1,storage_id='store')])
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(part,)).fetchone()[0]==1
        targets=[dict(r) for r in db.execute('SELECT * FROM allocations WHERE order_id=?',(oid,))]
        assert {r['target_type'] for r in targets}=={'copy','stock'}
        stock=next(r['target_stock_id'] for r in targets if r['target_type']=='stock')
        assert db.execute('SELECT quantity FROM loose_stock WHERE id=?',(stock,)).fetchone()[0]==1
        with pytest.raises(ValueError):ledger.undo(db,received)
        with pytest.raises(ValueError):orders.allocate(db,oid,[dict(line_id=lid,target_type='stock',quantity=1)])
        reconciled=orders.reconcile(db,oid)
        ledger.undo(db,reconciled);ledger.undo(db,allocated)
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(part,)).fetchone()[0]==3
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?',(stock,)).fetchone()[0]
        assert {r[0] for r in db.execute('SELECT state FROM allocations WHERE order_id=?',(oid,))}=={'undone'}
        ledger.undo(db,received)
        assert orders.detail(db,oid)['received']==0
        with db:db.execute("UPDATE copies SET completeness_source='manual',completeness='S' WHERE id='copy'")
        orders.received(db,oid,{lid:3})
        allocated=orders.allocate(db,oid,[dict(line_id=lid,target_type='copy',copy_id='copy',target='part',target_id=part,quantity=3)])
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='S'
        ledger.undo(db,allocated)


def test_matching_pairing_reopen_and_hold(bw):
    with closing(connect(bw)) as db:
        oid,did,lid=saved(db)
        unknown=XML.replace('bl-part','unknown')
        result=orders.import_document(db,'xml',unknown,choice=oid)
        other=result['document_id'];row=next(r for r in orders.lines(db,oid) if r['document_id']==other)
        assert row['item_no'] is None and 'unknown' in row['raw_text']
        with pytest.raises(ValueError):orders.phase(db,oid,other,'review')
        event=orders.match(db,oid,row['id'],'P','bl-part',11)
        assert orders.detail(db,oid)['lines'][-1]['state']=='confirmed'
        ledger.undo(db,event)
        orders.match(db,oid,row['id'],'P','bl-part',11)
        reviewed=orders.phase(db,oid,other,'review')
        orders.phase(db,oid,other,'reopen');orders.phase(db,oid,other,'review')
        orders.phase(db,oid,other,'save',{str(row['id']):lid})
        assert orders.detail(db,oid)['ordered']==3
        orders.received(db,oid,{lid:3})
        hold=orders.hold(db,oid,lid,True)
        with pytest.raises(ValueError):orders.allocate(db,oid,[dict(line_id=lid,target_type='stock',quantity=1)])
        with pytest.raises(ValueError):orders.reconcile(db,oid)
        ledger.undo(db,hold)
        orders.allocate(db,oid,[dict(line_id=lid,target_type='stock',quantity=3)])
        assert len(orders.detail(db,oid)['allocations'])==1


def test_email_api_and_xml_preserve_raw_and_duplicates(bw,monkeypatch):
    with closing(connect(bw)) as db:
        text='* Batch #1 (submitted Oct 12, 2026)\n[Used] Invented blue Synthetic part (x3) ... EUR 0.12 each = EUR 0.36'
        result=orders.import_document(db,'email',text)
        row=orders.lines(db,result['order_id'])[0]
        assert row['item_no']=='bl-part' and row['batch']==1 and row['submitted']=='Oct 12, 2026'
        assert row['color_id']==11 and row['line_total']=='0.36'
        assert orders.import_document(db,'email',text)['duplicate']
        monkeypatch.setattr(orders.BrickLink,'list_orders',lambda self:[dict(order_id=123,store_name='Test store',cost=dict(grand_total='4.00',currency_code='EUR'))])
        monkeypatch.setattr(orders.BrickLink,'order_items',lambda self,n:[[dict(item=dict(type='PART',no='bl-part',name='Synthetic part'),color_id=11,new_or_used='N',quantity=2,unit_price='2.00')]])
        result=orders.import_document(db,'api',number=123)
        assert orders.detail(db,result['order_id'])['order']['cost']=='4.00'
        assert orders.import_document(db,'api',number=123)['duplicate']
        with pytest.raises(ValueError):orders.import_document(db,'xml','<!DOCTYPE INVENTORY>'+XML)
        with pytest.raises(ValueError):orders.import_document(db,'xml',XML.replace('0.12','nan'))


def test_atomic_failures_security_conflicts_and_creation_undo(app,bw):
    client,csrf,_=client_token(app)
    assert client.post('/workbench/orders/action/import',json=dict(source='xml',text=XML)).status_code==400
    assert client.post('/workbench/storage/action/move',json=dict(csrf_token=csrf,storage_id=None,selections=[]),headers={'Origin':'https://other.test'}).status_code==403
    with closing(connect(bw)) as db:
        oid,did,lid=saved(db)
        received=orders.received(db,oid,{lid:3})
        allocation=orders.allocate(db,oid,[dict(line_id=lid,target_type='stock',quantity=2)])
        stock=db.execute('SELECT target_stock_id FROM allocations WHERE order_id=?',(oid,)).fetchone()[0]
        with db:db.execute('UPDATE loose_stock SET quantity=1 WHERE id=?',(stock,))
        with pytest.raises(ValueError):ledger.undo(db,allocation)
        location,event=ledger.storage_save(db,None,'New box')
        ledger.undo(db,event)
        assert db.execute('SELECT archived_at FROM storages WHERE id=?',(location,)).fetchone()[0]
        db.execute("CREATE TRIGGER reject_ledger BEFORE INSERT ON events WHEN NEW.entity='bw_ledger' BEGIN SELECT RAISE(ABORT,'no'); END")
        before=orders.detail(db,oid)['received']
        with pytest.raises(sqlite3.IntegrityError):orders.received(db,oid,{lid:2})
        assert orders.detail(db,oid)['received']==before
        with pytest.raises(sqlite3.IntegrityError):ledger.move(db,None,[dict(entity='copy',id='copy')])
        assert db.execute("SELECT storage_id FROM copies WHERE id='copy'").fetchone()[0]=='store'
        with pytest.raises(sqlite3.IntegrityError):orders.import_document(db,'xml',XML.replace('<QTY>3','<QTY>2'))


def trace(db, call):
    statements=[];db.set_trace_callback(statements.append)
    try:call()
    finally:db.set_trace_callback(None)
    return len(statements)


def test_query_cost_hundreds_of_lines_and_storage_items(bw):
    with closing(connect(bw)) as db:
        body=XML[XML.index('<ITEM>'):XML.index('</ITEM>')+7]
        document='<INVENTORY>'+body*300+'</INVENTORY>'
        count=trace(db,lambda:orders.import_document(db,'xml',document))
        assert count<4000 # linear writes and audit, not row × row
        oid=db.execute('SELECT max(id) FROM orders').fetchone()[0]
        did=orders.detail(db,oid)['documents'][0]['id']
        assert trace(db,lambda:orders.detail(db,oid))<15
        assert trace(db,lambda:orders.listing(db))<3
        assert trace(db,lambda:orders.destinations(db,orders.detail(db,oid)['saved']))<35
        assert trace(db,lambda:orders.phase(db,oid,did,'review'))<1000
        orders.phase(db,oid,did,'save')
        rows=orders.detail(db,oid)['saved']
        assert trace(db,lambda:orders.received(db,oid,{r['id']:3 for r in rows}))<3000
        assert trace(db,lambda:orders.allocate(db,oid,[dict(line_id=r['id'],target_type='stock',quantity=3) for r in rows]))<4000
        assert trace(db,lambda:ledger.storages(db))<3
        assert trace(db,lambda:ledger.storage_detail(db,None))<9
        stock=ledger.storage_detail(db,None)['rows']
        assert trace(db,lambda:ledger.move(db,'store',[dict(entity=r['entity'],id=r['id']) for r in stock]))<2000
        assert trace(db,lambda:ledger.storage_save(db,'store','Renamed'))<15


def test_ledger_runtime():
    subprocess.run([shutil.which('node'),str(Path(__file__).with_name('toni_bw_ledger_runtime.cjs'))],check=True,capture_output=True,text=True)


def test_document_undo_dependency_order_and_preserved_provenance(bw):
    with closing(connect(bw)) as db:
        result=orders.import_document(db,'xml',XML)
        oid,did=result['order_id'],result['document_id']
        review=orders.phase(db,oid,did,'review')
        save=orders.phase(db,oid,did,'save')
        lid=orders.detail(db,oid)['saved'][0]['id']
        received=orders.received(db,oid,{lid:2})
        with pytest.raises(ValueError,match='received'):ledger.undo(db,save)
        ledger.undo(db,received);ledger.undo(db,save);ledger.undo(db,review);ledger.undo(db,result['event_id'])
        assert orders.detail(db,oid)['documents'][0]['phase']=='undone'
        assert orders.detail(db,oid)['lines'][0]['raw_text']
        assert not orders.detail(db,oid)['saved']
        assert orders.import_document(db,'xml',XML)['duplicate']


def test_copy_status_guard_and_batched_same_copy_query_cost(gaps):
    path,part=gaps
    with closing(connect(path)) as db:
        body=XML[XML.index('<ITEM>'):XML.index('</ITEM>')+7].replace('<QTY>3','<QTY>1')
        result=orders.import_document(db,'xml','<INVENTORY>'+body*300+'</INVENTORY>')
        oid,did=result['order_id'],result['document_id']
        orders.phase(db,oid,did,'review');orders.phase(db,oid,did,'save')
        rows=orders.detail(db,oid)['saved']
        with db:db.execute('UPDATE copy_parts SET missing=300,quantity=300 WHERE id=?',(part,))
        orders.received(db,oid,{r['id']:1 for r in rows})
        calls=[];db.set_trace_callback(calls.append)
        event=orders.allocate(db,oid,[dict(line_id=r['id'],target_type='copy',quantity=1,copy_id='copy',target='part',target_id=part) for r in rows])
        db.set_trace_callback(None)
        assert len(calls)<7000
        assert sum('SUM(' in s.upper() and 'COPY_PARTS' in s.upper() for s in calls)<5
        with db:db.execute("DELETE FROM item_flags WHERE entity_type='copy' AND entity_id='copy' AND flag_id='test_checked'")
        with pytest.raises(ValueError,match='copy status'):ledger.undo(db,event)
        with db:db.execute("INSERT INTO item_flags VALUES('copy','copy','test_checked')")
        assert trace(db,lambda:ledger.undo(db,event))<2500


def test_physical_instructions_whole_figure_and_box_flags(gaps):
    path,part=gaps
    with sqlite3.connect(path.with_name('bricklink-catalog.db')) as cat:
        cat.executemany('INSERT OR IGNORE INTO items VALUES(?,?,?,?,?,NULL)',[(k,'new-set','Synthetic physical '+k,'synthetic physical '+k,None) for k in ('I','O')])
    with closing(connect(path)) as db:
        for kind,number,target,target_id,flag in [('I','new-set','instructions','new-set','test_instr'),('O','new-set','box','new-set','test_box'),('M','bl-figure','figure','bl-figure',None)]:
            text=XML.replace('<ITEMTYPE>P','<ITEMTYPE>'+kind).replace('bl-part',number).replace('<QTY>3','<QTY>1')
            with db:
                if kind=='M':db.execute("UPDATE copy_minifigs SET missing=1 WHERE item_type='M'")
            oid,did,lid=saved(db,text)
            orders.received(db,oid,{lid:1})
            event=orders.allocate(db,oid,[dict(line_id=lid,target_type='copy',copy_id='copy',target=target,target_id=target_id,quantity=1)])
            if flag:assert db.execute('SELECT 1 FROM item_flags WHERE flag_id=?',(flag,)).fetchone()
            else:assert db.execute("SELECT missing FROM copy_minifigs WHERE item_type='M'").fetchone()[0]==0
            ledger.undo(db,event)
            if flag:assert not db.execute('SELECT 1 FROM item_flags WHERE flag_id=?',(flag,)).fetchone()
            else:assert db.execute("SELECT missing FROM copy_minifigs WHERE item_type='M'").fetchone()[0]==1


def test_raw_document_and_known_currency_survive_link_and_undo(bw):
    with closing(connect(bw)) as db:
        oid,did,lid=saved(db)
        text='Store note: keep the original email\n[Used] Invented blue Synthetic part (x3) ... EUR 0.12 each = EUR 0.36\nPrivate trailing note'
        result=orders.import_document(db,'email',text,choice=oid)
        assert orders.get(db,oid)['currency']=='EUR'
        source=db.execute("SELECT payload FROM source_records WHERE kind='order_document:email'").fetchone()[0]
        assert json.loads(source)['text']==text
        ledger.undo(db,result['event_id'])
        assert db.execute("SELECT payload FROM source_records WHERE kind='order_document:email'").fetchone()[0]==source
        assert orders.get(db,oid)['currency'] is None


def test_orders_destination_dict_copy_identity(app, gaps):
    from bs4 import BeautifulSoup
    path, _ = gaps
    with closing(connect(path)) as db:
        oid, _, lid = saved(db)
        orders.received(db, oid, {str(lid): 3})
        destination = orders.destinations(db, orders.detail(db, oid)['saved'])[lid][0]
        assert isinstance(destination, dict) and 'copy' in destination
        number = destination['copy']['set_no']
        label = destination['copy']['label']
        need = destination['need']
    client, _, _ = client_token(app)
    response = client.get('/workbench/orders/' + str(oid))
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, 'html.parser')
    allocation = soup.select_one('[data-allocation]').parent
    assert f'{number} · {label} · {need} missing' in allocation.text


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
