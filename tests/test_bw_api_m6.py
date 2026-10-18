"""M6 synthetic documents, atomic allocations and every Undo dispatcher owner."""
from contextlib import closing
import json
import os
import sqlite3

import pytest

from tests.test_bw_api_m1 import app, call, create as token_create
from tests.test_bw_api_m2 import populated
from tests.test_bw_api_m3 import write, dbrows
from tests.test_bw_api_m1_contract import CONTRACT, validate
from brickwork.core import admin, api_reads, api_writes, checker, ledger, orders, part_inventory
from brickwork.core.connect import connect
from brickwork.core.receipts import KINDS

XML='<INVENTORY><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>100-1</ITEMID><QTY>3</QTY><CONDITION>U</CONDITION><PRICE>1.00</PRICE></ITEM></INVENTORY>'


def send(app,path,body=None,key=None,method='post'):
    response=write(app,path,method,body,key=key or path.replace('/','-').replace('.','-'))
    assert response.status_code==200,response.text
    return response.json


def imported(app,source='xml',text=XML):
    result=send(app,'/orders/documents',dict(source=source,text=text))
    return result,result['data']['order_id'],result['data']['document_id']


def saved(app):
    result,oid,did=imported(app)
    for action in ('review','save'):
        send(app,f'/orders/{oid}/documents/{did}/phase',dict(action=action),key=action)
    line=call(app,f'/orders/{oid}').json['data']['lines'][0]['id']
    return oid,did,line


def test_document_flow_contract_replay_audit_and_undo(populated):
    before=len(dbrows('events'))
    result,oid,did=imported(populated)
    assert len(dbrows('events'))==before+1
    validate(result,CONTRACT['paths']['/orders/documents']['post']['responses']['200']['content']['application/json']['schema'])
    assert result['event_id']==result['data']['event_id']
    replay=send(populated,'/orders/documents',dict(source='xml',text=XML))
    assert replay['idempotent_replay']
    duplicate=send(populated,'/orders/documents',dict(source='xml',text=XML),key='duplicate')
    assert duplicate['data']['duplicate']
    assert len(dbrows('events'))==before+2
    match=send(populated,f'/orders/{oid}/lines/1',dict(item_type='S',item_no='100-1'),method='patch')
    assert send(populated,f"/events/{match['event_id']}/undo")['data']['already_undone'] is False
    for action in ('review','reopen','review','save'):
        send(populated,f'/orders/{oid}/documents/{did}/phase',dict(action=action),key=action+str(len(dbrows('events'))))
    for held in (True,False):
        send(populated,f'/orders/{oid}/lines/1/hold',dict(held=held),key='held'+str(held),method='put')
    receipt=send(populated,f'/orders/{oid}/received',dict(counts={'1':2}))
    allocated=send(populated,f'/orders/{oid}/allocate',dict(chosen=[dict(line_id=1,target_type='stock',quantity=2)]))
    blocked=write(populated,f"/events/{receipt['event_id']}/undo",key='blocked')
    assert (blocked.status_code,blocked.json['code'])==(409,'undo_blocked')
    assert 'MINQTY>1' in call(populated,f'/orders/{oid}/short.xml').text
    send(populated,f'/orders/{oid}/reconcile')
    for suffix,shape in [('allocation-review','OrderReview'),('allocations','Allocation'),('history','OrderHistory')]:
        response=call(populated,f'/orders/{oid}/{suffix}')
        assert response.status_code==200,response.text
        validate(response.json,{'$ref':'#/components/schemas/ListOf'+shape})
        assert response.json['data']
    assert any(r['id']==allocated['event_id'] for r in call(populated,f'/orders/{oid}/history').json['data'])
    send(populated,f"/events/{allocated['event_id']}/undo")
    again=send(populated,f"/events/{allocated['event_id']}/undo",key='again')
    assert again['data']['already_undone']
    send(populated,f"/events/{receipt['event_id']}/undo")
    assert dbrows('line_receipts')[0]['received']==0
    assert dbrows('allocations')[0]['state']=='undone'
    assert all(r['via']=='api' and r['actor']=='bootstrap' for r in dbrows('events')[before:])


def test_email_and_bricklink_pull(populated,monkeypatch):
    result,oid,did=imported(populated,'email','[Used] Synthetic set (x3) ... EUR 1.00 each = EUR 3.00')
    assert result['data']['order_id']==oid


def test_pull_uses_source_client_and_replays_before_network(populated,monkeypatch):
    calls=[]
    def pull(db,number):
        calls.append(number)
        return orders.parse_xml(XML)
    monkeypatch.setattr(orders,'api_data',pull)
    data=dict(source='api',number='123456')
    result=send(populated,'/orders/documents',data)
    assert send(populated,'/orders/documents',data)['idempotent_replay']
    assert calls==['123456']
    assert len(dbrows('order_documents'))==1
    send(populated,f"/events/{result['event_id']}/undo")
    assert dbrows('order_documents')[0]['phase']=='undone'


@pytest.mark.parametrize('api_pull',[False,True])
def test_import_rolls_back_if_final_audit_fails(populated,monkeypatch,api_pull):
    before={t:dbrows(t) for t in ('orders','order_documents','order_lines','events')}
    monkeypatch.setattr(orders,'api_data',lambda db,n:orders.parse_xml(XML))
    real=admin.audit
    def fail(db,entity,*a,**kw):
        if entity=='bw_api':raise RuntimeError('Synthetic audit failure')
        return real(db,entity,*a,**kw)
    monkeypatch.setattr(admin,'audit',fail)
    response=write(populated,'/orders/documents',body=dict(source='api',number='123456') if api_pull else dict(source='xml',text=XML))
    assert response.status_code==500
    assert {t:dbrows(t) for t in before}==before


def test_atomic_allocation_retry(populated):
    oid,did,line=saved(populated)
    send(populated,f'/orders/{oid}/received',dict(counts={str(line):2}))
    choices=[dict(line_id=line,target_type='stock',quantity=1),dict(line_id=line,target_type='stock',quantity=2)]
    response=write(populated,f'/orders/{oid}/allocate',body=dict(chosen=choices))
    assert response.status_code==422
    assert not dbrows('allocations')
    assert len(dbrows('loose_stock'))==2
    send(populated,f'/orders/{oid}/allocations/retry',dict(chosen=choices[:1]))
    assert len(dbrows('allocations'))==1


@pytest.mark.parametrize('suffix',['allocation-review','allocations','history'])
def test_lists_constant_queries(populated,suffix):
    oid,did,line=saved(populated)
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        def count():
            trace=[];db.set_trace_callback(trace.append)
            {'allocation-review':orders.allocation_review,'allocations':orders.allocation_history,'history':lambda db,o:ledger.history(db,order_id=o)}[suffix](db,oid)
            db.set_trace_callback(None)
            return len([q for q in trace if q.lstrip().upper().startswith(('SELECT','WITH'))])
        small=count()
        with db:
            db.executemany('INSERT INTO order_lines(order_id,document_id,line_no,item_type,item_no,condition,qty,state) VALUES(?,?,?,\'S\',\'100-1\',\'U\',1,\'matched\')',[(oid,did,i) for i in range(2,302)])
        assert count()==small
    assert len(call(populated,f'/orders/{oid}/{suffix}?limit=200').json['data'])<=200


@pytest.mark.parametrize('entity,field',[(entity,field) for entity,fields in KINDS.items() for field in fields]+[('bw_token','create'),('bw_token','revoke'),('checker:synthetic','checker:answer')])
def test_every_advertised_kind_has_dispatcher(populated,monkeypatch,entity,field):
    from brickwork.core import collection, workbench, planning, add, manual_prices, tokens, keys, source_ops, identify
    from brickwork.core.importer import bricktracker as bricktracker_import
    from brickwork.core import sync as sync_module
    owners={'bw_collection':(collection,'undo'),'bw_workbench':(workbench,'undo'),'bw_ledger':(ledger,'undo'),'bw_planning':(planning,'undo'),'bw_add':(add,'undo'),'bw_manual_prices':(manual_prices,'undo'),'source_key:':(keys,'undo'),'source:':(source_ops,'undo_toggle'),'identification:':(identify,'undo'),'part_inventory:':(part_inventory,'undo'),'bw_token':(tokens,'undo'),'checker:synthetic':(checker,'write'),'bw_import':(bricktracker_import,'undo'),'bw_sync':(sync_module,'undo')}
    owner,name=owners[entity];seen=[]
    def undo(*a,**kw):
        seen.append(True)
        return ({'undone_event_id':event},None,None)
    monkeypatch.setattr(owner,name,undo)
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        event=db.execute('SELECT coalesce(max(id),0)+1 FROM events').fetchone()[0]
        value=dict(batch='synthetic',session={'undo':[event]})
        admin.audit(db,entity+'synthetic' if entity.endswith(':') else entity,field,None,value)
        assert api_reads.events(db,event)[0]['undoable']
        api_writes.undo_event(db,event,{'name':'bootstrap','scopes':['admin']},'synthetic')
        assert seen


def test_part_inventory_and_checker_real_undo(populated):
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        # A synthetic part-inventory batch uses the web receipt shape.
        from brickwork.core.stock import add_loose
        changes=[]
        with db:
            db.execute('BEGIN IMMEDIATE')
            identifier,_=add_loose(db,changes,item_type='P',item_no='3001',color_id=4,quantity=1,condition='N')
            admin.audit(db,'part_inventory:synthetic','receipt',None,dict(stock=[identifier],stock_changes=changes,identifications=[],lot=None))
            event=db.execute('SELECT max(id) FROM events').fetchone()[0]
        result=send(populated,f'/events/{event}/undo')
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?',(identifier,)).fetchone()[0]
        assert not call(populated,f'/events/{event}').json['data']['undoable']
        checker.write(db,'c1',dict(action='start',operation='synthetic-start'),os.path.dirname(os.environ['BW_DB_PATH']))
        event=db.execute('SELECT max(id) FROM events').fetchone()[0]
    send(populated,f'/events/{event}/undo')
    assert not any(r['key']=='checker:c1' for r in dbrows('settings'))


@pytest.mark.parametrize('path,body,method',[
 ('/orders/documents',{'source':'xml','text':'bad'},'post'),
 ('/orders/1/received',{'counts':{'1':True}},'post'),
 ('/orders/1/allocate',{'chosen':[]},'post'),
 ('/orders/1/allocations/retry',{'chosen':[]},'post'),
 ('/orders/1/reconcile',None,'post'),
 ('/orders/1/documents/999/phase',{'action':'review'},'post'),
 ('/orders/1/lines/999',{'item_type':'S','item_no':'100-1'},'patch'),
 ('/orders/1/lines/999/hold',{'held':True},'put'),
])
def test_order_errors_scopes_and_atomicity(populated,path,body,method):
    before=dbrows('events')
    response=write(populated,path,method,body)
    assert response.status_code in (404,422),response.text
    assert dbrows('events')==before
    reader=token_create(populated,'synthetic-reader',['read']).json['data']['secret']
    assert write(populated,path,method,body,token=reader).status_code==403


def test_bricklink_transport_budget_credentials_and_replay(populated,monkeypatch):
    from brickwork.core.sources import base
    from brickwork.core.sources.bricklink import BrickLink
    for name in BrickLink.credentials:monkeypatch.setenv(name,'synthetic-'+name.lower())
    monkeypatch.setattr(base.time,'sleep',lambda _:None)
    requests=[]
    def transport(request):
        requests.append(request.full_url)
        data=([[dict(item=dict(type='SET',no='100-1',name='Synthetic set'),new_or_used='U',quantity=3,unit_price='1.00')]]
              if request.full_url.endswith('/items') else [dict(order_id=123456,store_name='Synthetic store',cost=dict(grand_total='3.00',currency_code='EUR'))])
        return json.dumps(dict(meta=dict(code=200),data=data))
    monkeypatch.setattr(base,'transport',transport)
    result=send(populated,'/orders/documents',dict(source='api',number='123456'))
    assert len(requests)==2
    assert send(populated,'/orders/documents',dict(source='api',number='123456'))['idempotent_replay']
    assert len(requests)==2
    assert all(os.environ[name] not in json.dumps(result) for name in BrickLink.credentials)
    send(populated,f"/events/{result['event_id']}/undo")
    assert dbrows('order_documents')[0]['phase']=='undone'
    assert len(dbrows('jobs'))==3  # fixture plus the two budgeted source calls


@pytest.mark.parametrize('kind',['part_inventory','checker'])
def test_real_undo_blocked_is_atomic(populated,kind):
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        if kind=='checker':
            checker.write(db,'c1',dict(action='start',operation='start-synthetic'),os.path.dirname(os.environ['BW_DB_PATH']))
            event=db.execute('SELECT max(id) FROM events').fetchone()[0]
            with db:db.execute("UPDATE copies SET completeness='C' WHERE id='c1'")
        else:
            from brickwork.core.stock import add_loose
            from brickwork.core.transaction import transaction
            with transaction(db):
                changes=[]
                identifier,_=add_loose(db,changes,item_type='P',item_no='3001',color_id=4,quantity=1,condition='N')
                admin.audit(db,'part_inventory:synthetic','receipt',None,dict(stock=[identifier],stock_changes=changes,identifications=[],lot=None))
            event=db.execute('SELECT max(id) FROM events').fetchone()[0]
            with db:db.execute('UPDATE loose_stock SET quantity=99 WHERE id=?',(identifier,))
    before={t:dbrows(t) for t in ('events','copies','copy_parts','settings','loose_stock')}
    response=write(populated,f'/events/{event}/undo')
    assert (response.status_code,response.json['code'])==(409,'undo_blocked')
    assert {t:dbrows(t) for t in before}==before


@pytest.mark.parametrize('entity,field,value',[('unknown','receipt',{}),('bw_ledger','change',{}),('sourceXkey:synthetic','save',{}),('bw_api','receipt',{'receipts':[{'entity':'unknown','field':'receipt'}]}),('bw_api','undo',{'undone_event_id':1,'receipts':[]}),('checker:synthetic','checker:undo',{'session':{'undo':[]}})])
def test_unsupported_receipts_never_advertised(populated,entity,field,value):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        admin.audit(db,entity,field,None,value)
        event=db.execute('SELECT max(id) FROM events').fetchone()[0]
    assert not call(populated,f'/events/{event}').json['data']['undoable']
    response=write(populated,f'/events/{event}/undo')
    assert (response.status_code,response.json['code'])==(409,'not_undoable')


def test_checker_web_undo_reflected_in_events(populated):
    from pathlib import Path
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        root=Path(os.environ['BW_DB_PATH']).parent
        checker.write(db,'c1',dict(action='start',operation='start-synthetic'),root)
        event=db.execute('SELECT max(id) FROM events').fetchone()[0]
        checker.write(db,'c1',dict(action='undo',operation='undo-synthetic',session=checker.session(db,'c1')['id']),root)
    result=call(populated,f'/events/{event}').json['data']
    assert result['undone'] and not result['undoable']
    assert send(populated,f'/events/{event}/undo')['data']['already_undone']
