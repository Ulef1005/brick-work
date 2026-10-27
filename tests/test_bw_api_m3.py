"""M3 writes use existing rules, one audit event, and offline core receipt Undo."""
from contextlib import closing
import json
import os
import socket
import sqlite3
import time

import pytest

from tests.test_bw_api_m1 import app, call, create as token_create
from tests.test_bw_api_m2 import populated
from tests.test_bw_api_m1_contract import CONTRACT, validate as contract_validate
from brickwork.core import api_pages, api_reads, api_writes, admin, collection
from brickwork.core.connect import connect


def write(app,path,method='post',body=None,key='synthetic-operation',extra=None,token='synthetic-bootstrap'):
    headers={'Authorization':'Bearer '+token,**(extra or {})}
    if key is not None:headers['Idempotency-Key']=key
    return app.test_client().open('/api/v1'+path,method=method,headers=headers,**({'json':body} if body is not None else {}))


def dbrows(table):
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        return [dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]


CASES=[
 ('/copies/c1','patch',{'note':'Synthetic note'},'copies'),
 ('/copies/c1','delete',None,'copies'),
 ('/copies/c1/flags','put',{'flags':[]},'item_flags'),
 ('/copies/c1/pin','put',{'pinned':True},'copies'),
 ('/stock/t1','patch',{'note':'Synthetic note'},'loose_stock'),
 ('/stock/t1','delete',None,'loose_stock'),
 ('/stock/t1/flags','put',{'flags':['f1']},'item_flags'),
 ('/wishes/1','patch',{'max_price':'10.00','max_price_currency':'EUR'},'wishlist'),
 ('/wishes/1','delete',None,'wishlist'),
 ('/wishes/1/flags','put',{'flags':['f1']},'item_flags'),
 ('/storages/s1','patch',{'name':'Synthetic renamed'},'storages'),
 ('/storages/s1/contents','post',{'selections':[{'entity':'copy','id':'c1'}]},'copies'),
 ('/lots/l1','patch',{'name':'Synthetic renamed'},'lots'),
 ('/lots/l1','delete',None,'lots'),
 ('/places/p1','patch',{'name':'Synthetic renamed'},'purchase_locations'),
 ('/places/p1','delete',None,'purchase_locations'),
 ('/flags/f1','patch',{'name':'Synthetic renamed'},'flags'),
 ('/flags/f1','delete',None,'flags'),
 ('/instruction-files/1','patch',{'label':'Synthetic renamed'},'instruction_files'),
 ('/instruction-files/1','delete',None,'instruction_files'),
 ('/copies/c1/take','post',{'item_type':'P','item_no':'3001','color_id':4,'quantity':1},'copy_parts'),
 ('/stock/t1/give','post',{'copy_id':'c1','target':'part','target_id':1,'quantity':1},'copy_parts'),
]


@pytest.mark.parametrize('path,method,body,table',CASES)
def test_write_replay_undo_exact(populated,path,method,body,table):
    # Resolve synthetic matching evidence for transfers.
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:db.execute("UPDATE id_match SET status='matched'")
    before=dbrows(table); count=len(dbrows('events'))
    response=write(populated,path,method,body)
    assert response.status_code==200,response.text
    assert len(dbrows('events'))==count+1
    event=dbrows('events')[-1]
    assert (event['via'],event['actor'])==('api','bootstrap')
    assert call(populated,'/events/'+str(event['id'])).json['data']['undoable']
    replay=write(populated,path,method,body)
    assert replay.status_code==200 and replay.json['idempotent_replay']
    assert len(dbrows('events'))==count+1
    undone=write(populated,f"/events/{response.json['event_id']}/undo",key='synthetic-undo')
    assert undone.status_code==200,undone.text
    assert dbrows(table)==before
    assert len(dbrows('events'))==count+2
    assert call(populated,'/events/'+str(event['id'])).json['data']['undone']
    repeated=write(populated,f"/events/{response.json['event_id']}/undo",key='synthetic-another-undo')
    assert repeated.json['data']['already_undone'] is True


@pytest.mark.parametrize('path,method,body,table',CASES)
def test_failure_rolls_back_domain_and_receipt(populated,monkeypatch,path,method,body,table):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:db.execute("UPDATE id_match SET status='matched'")
    before=dbrows(table);events=dbrows('events')
    real=admin.audit
    def failing(db,entity,field,*args,**kwargs):
        if entity=='bw_api' and field.startswith('op:'):raise RuntimeError('Synthetic injected failure')
        return real(db,entity,field,*args,**kwargs)
    monkeypatch.setattr(admin,'audit',failing)
    response=write(populated,path,method,body)
    assert response.status_code==500,response.text
    assert dbrows(table)==before and dbrows('events')==events


@pytest.mark.parametrize('resource,identifier',[('copies','c1'),('stock','t1'),('wishes','1')])
def test_if_match_and_archive_restore(populated,resource,identifier):
    path='/'+resource+'/'+identifier
    tag=call(populated,path).headers['ETag']; before=dbrows('events')
    assert write(populated,path,'patch',{'note':'Synthetic'},extra={'If-Match':'"stale"'}).status_code==412
    assert dbrows('events')==before
    assert write(populated,path,'patch',{'note':'Synthetic'},key='synthetic-save',extra={'If-Match':tag}).status_code==200
    assert write(populated,path,'delete',key='synthetic-archive',extra={'If-Match':tag}).status_code==412
    assert write(populated,path,'delete',key='synthetic-archive').status_code==200
    assert write(populated,path,'patch',{'note':'Synthetic'},key='synthetic-archived').json['code']=='archived'
    restored=write(populated,path+'/restore',key='synthetic-restore')
    assert restored.status_code==200,restored.text
    assert call(populated,path).json['data']['archived_at'] is None
    assert write(populated,f"/events/{restored.json['event_id']}/undo",key='synthetic-undo-restore').status_code==200
    assert call(populated,path).json['data']['archived_at']


@pytest.mark.parametrize('path,body,table',[
 ('/copies',{'item_no':'100-1','quantity':2,'storage_id':'s1'},'copies'),
 ('/stock',{'item_type':'S','item_no':'100-1','quantity':2,'note':'Synthetic'},'loose_stock'),
 ('/wishes',{'item_type':'S','item_no':'100-1','max_price':'12.00','max_price_currency':'EUR','condition':'any','decision':'another'},'wishlist'),
 ('/storages',{'name':'Synthetic new'},'storages'),
 ('/places',{'name':'Synthetic new'},'purchase_locations'),
 ('/flags',{'name':'Synthetic new','kind':'owner'},'flags'),
 ('/lots',{'name':'Synthetic new','stock_ids':['t1']},'lots'),
])
def test_creates_and_undo(populated,path,body,table):
    if path=='/copies':body['decision']='another'
    count=len(dbrows('events'))
    response=write(populated,path,body=body)
    assert response.status_code==201,response.text
    assert len(dbrows('events'))==count+1
    replay=write(populated,path,body=body)
    assert replay.status_code==201 and replay.json['idempotent_replay']
    undo=write(populated,f"/events/{response.json['event_id']}/undo",key='synthetic-undo')
    assert undo.status_code==200,undo.text
    assert len(dbrows('events'))==count+2


def test_idempotency_required_conflict_scope(populated):
    body={'item_no':'100-1','decision':'another'}
    assert write(populated,'/copies',body=body,key=None).status_code==428
    first=write(populated,'/copies',body=body)
    assert first.status_code==201,first.text
    assert write(populated,'/copies',body=dict(body,quantity=2)).status_code==409
    assert write(populated,'/copies',body=body,key='bad key').status_code==400
    token=token_create(populated,'synthetic-writer',['write']).json['data']['secret']
    assert write(populated,'/copies',body=body,token=token).status_code==201
    saved=json.loads(dbrows('events')[-1]['new_value'])
    assert saved['token_name']=='synthetic-writer'


@pytest.fixture(autouse=True)
def spawned(monkeypatch):
    """API writes now wake the embedded drainer when a job is due (#121); keep its thread out of these tests."""
    from brickwork.api import operations
    started = []
    monkeypatch.setattr(operations, 'spawn', started.append)
    return started


@pytest.fixture(autouse=True)
def complete_synthetic_catalogue(populated):
    import sqlite3
    from pathlib import Path
    with sqlite3.connect(Path(os.environ['BW_DB_PATH']).with_name('bricklink-catalog.db')) as db:
        db.executemany('INSERT INTO items VALUES(?,?,?,?,?,?)',[
            ('P','3001','Synthetic brick','Synthetic',2025,'synthetic brick'),
            ('I','100-1','Synthetic booklet','Synthetic',2024,'synthetic booklet')])


@pytest.mark.parametrize('path,body,table',[
 ('/found',{'item_type':'P','item_no':'3001','color_id':4,'destination':'loose','quantity':2},'loose_stock'),
 ('/stock/booklets',{'text':'100-1','quantity':1},'loose_stock'),
 ('/wishes/1/to-owned',{},'wishlist'),
])
def test_quantity_creates(populated,path,body,table):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:db.execute("UPDATE id_match SET status='matched'")
    before=dbrows(table);events=dbrows('events')
    assert write(populated,path,body=body,key=None).status_code==428
    result=write(populated,path,body=body)
    assert result.status_code==200,result.text
    assert len(dbrows('events'))==len(events)+1
    undone=write(populated,f"/events/{result.json['event_id']}/undo",key='synthetic-undo')
    assert undone.status_code==200,undone.text
    if table=='wishlist':assert dbrows(table)==before
    else:assert all(r in dbrows(table) for r in before)


@pytest.mark.parametrize('resource,identifier,table',[('storages','s1','storages'),('places','p1','purchase_locations'),('flags','f1','flags'),('lots','l1','lots'),('instruction-files','1','instruction_files')])
def test_all_restores(populated,resource,identifier,table):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        db.execute('UPDATE '+table+" SET archived_at='2026-10-01T00:00:00+00:00' WHERE id=?",(identifier,))
    before=dbrows(table)
    restored=write(populated,f'/{resource}/{identifier}/restore')
    assert restored.status_code==200,restored.text
    undone=write(populated,f"/events/{restored.json['event_id']}/undo",key='synthetic-undo')
    assert undone.status_code==200,undone.text
    assert dbrows(table)==before


def test_instruction_upload(populated,monkeypatch):
    import io
    from pathlib import Path
    headers={'Authorization':'Bearer synthetic-bootstrap','Idempotency-Key':'synthetic-pdf'}
    def upload():
        return populated.test_client().post('/api/v1/instruction-files',headers=headers,data={
            'item_type':'S','item_no':'100-1','label':'Synthetic PDF','file':(io.BytesIO(b'%PDF-1.4\n%%EOF'),'synthetic.pdf')})
    before=dbrows('events')
    result=upload()
    assert result.status_code==201,result.text
    assert result.json['data']['content_url']
    assert len(dbrows('events'))==len(before)+1
    assert upload().json['idempotent_replay']
    undone=write(populated,f"/events/{result.json['event_id']}/undo",key='synthetic-undo')
    assert undone.status_code==200,undone.text
    assert dbrows('instruction_files')[-1]['archived_at']


@pytest.mark.parametrize('path,method,body,table',CASES)
def test_write_contract(populated,path,method,body,table):
    import re
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:db.execute("UPDATE id_match SET status='matched'")
    template=re.sub(r'/(c1|t1|p1|s1|l1|f1|1)(?=/|$)','/{id}',path)
    op=CONTRACT['paths'][template][method]
    result=write(populated,path,method,body)
    assert result.status_code==200,result.text
    contract_validate(result.json,op['responses']['200']['content']['application/json']['schema'])


@pytest.mark.parametrize('path,body,table',[
 ('/copies',{'item_no':'100-1','decision':'another','quantity':2},'copies'),
 ('/stock',{'item_type':'S','item_no':'100-1','quantity':2},'loose_stock'),
 ('/wishes',{'item_type':'S','item_no':'100-1','decision':'another','max_price':'8.00','max_price_currency':'EUR'},'wishlist'),
 ('/storages',{'name':'Synthetic create'},'storages'),
 ('/places',{'name':'Synthetic create'},'purchase_locations'),
 ('/flags',{'name':'Synthetic create','kind':'tag'},'flags'),
 ('/lots',{'stock_ids':['t1'],'name':'Synthetic create'},'lots'),
 ('/found',{'item_type':'P','item_no':'3001','color_id':4,'destination':'loose','quantity':1},'loose_stock'),
 ('/stock/booklets',{'text':'100-1'},'loose_stock'),
 ('/wishes/1/to-owned',{},'wishlist'),
])
def test_create_failure_is_atomic(populated,monkeypatch,path,body,table):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:db.execute("UPDATE id_match SET status='matched'")
    tables=['items','copies','loose_stock','wishlist','lots','storages','purchase_locations','flags','jobs','events','settings']
    before={t:dbrows(t) for t in tables}
    real=admin.audit
    def failing(db,entity,field,*a,**kw):
        if entity=='bw_api' and field.startswith('op:'):raise RuntimeError('Synthetic injected failure')
        return real(db,entity,field,*a,**kw)
    monkeypatch.setattr(admin,'audit',failing)
    result=write(populated,path,body=body)
    assert result.status_code==500,result.text
    assert {t:dbrows(t) for t in tables}==before


def test_upload_failure_removes_new_bytes(populated,monkeypatch):
    import io
    from pathlib import Path
    before=dbrows('instruction_files');events=dbrows('events')
    root=Path(os.environ['BW_DB_PATH']).parent/'data/instructions'
    files=set(root.iterdir())
    real=admin.audit
    def failing(db,entity,field,*a,**kw):
        if entity=='bw_api':raise RuntimeError('Synthetic injected failure')
        return real(db,entity,field,*a,**kw)
    monkeypatch.setattr(admin,'audit',failing)
    result=populated.test_client().post('/api/v1/instruction-files',headers={
        'Authorization':'Bearer synthetic-bootstrap','Idempotency-Key':'synthetic-upload'},data={
        'item_type':'S','item_no':'100-1','label':'Synthetic PDF','file':(io.BytesIO(b'%PDF-1.4\nsynthetic failure\n%%EOF'),'synthetic.pdf')})
    assert result.status_code==500,result.text
    assert set(root.iterdir())==files
    assert dbrows('instruction_files')==before and dbrows('events')==events


def test_undo_later_save_blocked_and_partial_wish(populated):
    result=write(populated,'/copies/c1','patch',{'note':'Synthetic first'})
    write(populated,'/copies/c1','patch',{'note':'Synthetic later'},key='synthetic-later')
    assert write(populated,f"/events/{result.json['event_id']}/undo",key='synthetic-undo').json['code']=='undo_blocked'
    created=write(populated,'/copies',body={'item_no':'100-1','decision':'another'},key='synthetic-create')
    copy_id=created.json['data']['ids'][0]
    assert write(populated,'/copies/'+copy_id,'patch',{'note':'Synthetic later'},key='synthetic-later-copy').status_code==200
    assert write(populated,f"/events/{created.json['event_id']}/undo",key='synthetic-undo-create').json['code']=='undo_blocked'
    before=dbrows('wishlist')
    moved=write(populated,'/wishes/1/to-owned',body={'quantity':1},key='synthetic-move')
    assert moved.status_code==200,moved.text
    assert dbrows('wishlist')[0]['quantity']==1
    assert write(populated,f"/events/{moved.json['event_id']}/undo",key='synthetic-undo-wish').status_code==200
    assert dbrows('wishlist')==before


def test_storage_archive_moves_and_undo(populated):
    tables=['storages','copies','loose_stock','lots']
    before={t:dbrows(t) for t in tables}
    result=write(populated,'/storages/s1?move_to_unstored=true','delete')
    assert result.status_code==200,result.text
    assert write(populated,f"/events/{result.json['event_id']}/undo",key='synthetic-undo').status_code==200
    assert {t:dbrows(t) for t in tables}==before


def test_generated_write_manifest():
    from pathlib import Path
    from scripts.generate_api_writes import generated
    assert Path('brickwork/api/write_contract.json').read_text()==generated()


def test_receipt_ttl_and_read_scope(populated):
    from datetime import timedelta
    from brickwork.core.sources.base import now
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        admin.audit(db,'bw_api','op:synthetic-old',new={'token_name':'bootstrap'})
        # events are append-only: an old receipt is inserted with its original timestamp.
        db.execute("INSERT INTO events(entity,field,new_value,at,via,actor) VALUES('bw_api','op:synthetic-expired','{}',?,'api','bootstrap')",((now()-timedelta(days=31)).isoformat(),))
    assert write(populated,'/copies/c1','patch',{'note':'Synthetic'},key='synthetic-expired').status_code==200
    token=token_create(populated,'synthetic-reader',['read']).json['data']['secret']
    assert write(populated,'/places',body={'name':'Synthetic'},token=token).status_code==403


@pytest.mark.parametrize('resource',['jobs'])
def test_operational_pages_bounded(populated,resource):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        if resource=='jobs':
            db.executemany("INSERT INTO jobs(source,kind,state,created_at,updated_at) VALUES('bricklink','prices','done','2026-10-01T00:00:00+00:00','2026-10-01T00:00:00+00:00')",[()]*400)
        else:
            db.executemany("INSERT INTO price_current(item_type,item_no,color_id,condition,guide,slot,currency,observation_id) VALUES('P','3001',4,'U','sold',?,'EUR',1)",[(str(i),) for i in range(400)])
        statements=[];db.set_trace_callback(statements.append)
        result=api_pages.page(db,resource,{'limit':'1'})
        assert len(result['data'])==1 and result['page']['next_cursor']
        assert len(statements)<=3


@pytest.mark.parametrize('changes',[{'condition':'damaged'},{'storage_id':'s1'},{'lot_id':'l1'}])
def test_new_stock_does_not_relocate_existing_quantity(populated,changes):
    before=dbrows('loose_stock')
    result=write(populated,'/stock',body=dict(item_type='P',item_no='3001',color_id=4,quantity=2,**changes))
    assert result.status_code==201,result.text
    after=dbrows('loose_stock')
    assert next(r for r in after if r['id']=='t1')==next(r for r in before if r['id']=='t1')
    added=next(r for r in after if r['id']==result.json['data']['ids'][0])
    assert added['quantity']==2


def test_stock_merge_remains_one_event(populated):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('synthetic-merge','P','3001',4,2,'U')")
    before=dbrows('loose_stock'); count=len(dbrows('events'))
    result=write(populated,'/stock/synthetic-merge','patch',{'storage_id':'s1','lot_id':'l1'})
    assert result.status_code==200,result.text
    assert len(dbrows('events'))==count+1
    assert result.json['data']['merged_ids']==['t1']
    assert write(populated,f"/events/{result.json['event_id']}/undo",key='synthetic-undo').status_code==200
    assert dbrows('loose_stock')==before


@pytest.mark.parametrize('resource,identifier,table',[('copies','c1','copies'),('stock','t1','loose_stock'),('wishes','1','wishlist'),('storages','s1','storages'),('places','p1','purchase_locations'),('flags','f1','flags'),('lots','l1','lots'),('instruction-files','1','instruction_files')])
def test_restore_rollback(populated,monkeypatch,resource,identifier,table):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        db.execute('UPDATE '+table+" SET archived_at='2026-10-01T00:00:00+00:00' WHERE id=?",(identifier,))
    before=dbrows(table);events=dbrows('events')
    real=admin.audit
    def failing(db,entity,field,*a,**kw):
        if entity=='bw_api':raise RuntimeError('Synthetic injected failure')
        return real(db,entity,field,*a,**kw)
    monkeypatch.setattr(admin,'audit',failing)
    assert write(populated,f'/{resource}/{identifier}/restore').status_code==500
    assert dbrows(table)==before and dbrows('events')==events


def test_if_match_is_checked_inside_core_transaction(populated):
    from brickwork.core import errors
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        tag=api_reads.entity_etag(db,'copy','c1')
        collection.save(db,'copy',['c1'],{'note':'Synthetic newer'})
        with pytest.raises(errors.PreconditionFailed):
            collection.save(db,'copy',['c1'],{'note':'Synthetic stale'},expect=[tag])
        assert db.execute("SELECT note FROM copies WHERE id='c1'").fetchone()[0]=='Synthetic newer'


def test_additive_schema_indexes_idempotent(populated):
    from brickwork.core import upgrade_api
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        before=dbrows('events')
        upgrade_api.upgrade_indexes(db);upgrade_api.upgrade_indexes(db)
        assert not upgrade_api.indexes_pending(db)
        assert 'archived_at' in {r[1] for r in db.execute('PRAGMA table_info(instruction_files)')}
        assert dbrows('events')==before


def test_manifest_all_write_errors(populated):
    from brickwork.api.writes import SPEC
    for op in SPEC['operations']:
        path=op['path'].replace('{id}',{'copies':'c1','stock':'t1','wishes':'1','lots':'l1','storages':'s1','places':'p1','flags':'f1','instruction-files':'1'}.get(op['resource'],'1')).replace('{part_id}','1').replace('{line_id}','1').replace('{doc_id}','1').replace('{type}','P').replace('{no}','3001')
        response=write(populated,path,op['method'],token='invalid')
        assert response.status_code==401,(path,response.text)
        if op.get('schema') and not op['multipart']:
            response=write(populated,path,op['method'],{'synthetic_unknown':True})
            assert response.status_code==422,(path,response.text)
        elif not op['multipart']:
            response=write(populated,path,op['method'],{'synthetic_unknown':True})
            assert response.status_code==400,(path,response.text)


def test_api_copy_uses_existing_inventory_materializer(populated):
    from brickwork.core import add
    result=write(populated,'/copies',body={'item_no':'100-1','decision':'another'})
    identifier=result.json['data']['ids'][0]
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        add.materialize(db,'S','100-1')
        add.materialize(db,'S','100-1')
        rows=list(db.execute('SELECT * FROM copy_parts WHERE copy_id=?',(identifier,)))
        assert len(rows)==1 and rows[0]['quantity']==4


def test_queued_import_keeps_api_actor_offline(populated):
    from brickwork.core.pipeline import Pipeline
    result=write(populated,'/copies',body={'item_no':'100-1','decision':'another'})
    assert result.status_code==201
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        job=dict(db.execute("SELECT * FROM jobs WHERE source='import' ORDER BY id DESC LIMIT 1").fetchone())
        assert json.loads(job['payload'])['actor']=='bootstrap'
        handlers={(r['name'],source):(lambda *a:None) for r in db.execute('SELECT * FROM import_steps WHERE job_id=?',(job['id'],)) for source in json.loads(r['sources'])}
        pipeline=Pipeline(db,handlers=handlers,emit=lambda *a:None)
        after=db.execute('SELECT max(id) FROM events').fetchone()[0]
        assert pipeline.run(job['id'])['state']=='done'
        events=[dict(r) for r in db.execute('SELECT * FROM events WHERE id>?',(after,))]
        assert events and all((r['via'],r['actor'])==('api','bootstrap') for r in events)


WRITE_OPS = [(path, method, op) for path, methods in CONTRACT['paths'].items()
             for method, op in methods.items() if method in ('post', 'put', 'patch', 'delete')
             and op.get('x-milestone') in ('M1', 'M3')]


@pytest.mark.parametrize('tag', ['*', '"wrong-etag"'])
@pytest.mark.parametrize('path,method,op', WRITE_OPS, ids=[f'{m} {p}' for p, m, _ in WRITE_OPS])
def test_every_write_if_match(populated, path, method, op, tag):
    ids = {'copies':'c1', 'stock':'t1', 'wishes':'1', 'lots':'l1', 'storages':'s1',
           'places':'p1', 'flags':'f1', 'instruction-files':'1'}
    url = path.replace('{id}', ids.get(path.split('/')[1], '1'))
    supported = any(p.get('$ref') == '#/components/parameters/IfMatch' for p in op.get('parameters', []))
    body = next((body for route, verb, body, _ in CASES if route == url and verb == method), None)
    before = dbrows('events')
    response = write(populated, url, method, body, extra={'If-Match': tag})
    expected = (200 if tag == '*' else 412) if supported else 400
    assert response.status_code == expected, (method, url, response.text)
    if not supported:
        assert response.json['code'] == 'bad_request'
    if expected != 200:
        assert dbrows('events') == before


@pytest.mark.parametrize('path,body',[('/copies',{'item_no':'100-1','decision':'another'}),('/wishes/1/to-owned',{'quantity':1})])
def test_a_write_that_queues_a_catalogue_import_wakes_the_worker(populated, spawned, path, body):
    """#121: a wish moved to owned through the API queued import job 1602 and nothing drained it."""
    result=write(populated,path,body=body,key='synthetic-wake')
    assert result.status_code in (200,201),result.text
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE source='import' AND state='queued'").fetchone()[0]>=1
    assert len(spawned)==1
    populated.extensions['bw_import_worker_active']=False
    assert write(populated,path,body=body,key='synthetic-wake').json['idempotent_replay'] is True and len(spawned)==1


def test_a_worker_that_cannot_start_does_not_turn_a_committed_write_into_an_error(populated, monkeypatch):
    from brickwork.api import operations
    def refuse(target): raise RuntimeError("can't start new thread")
    monkeypatch.setattr(operations, 'spawn', refuse)
    result=write(populated,'/copies',body={'item_no':'100-1','decision':'another'},key='synthetic-no-thread')
    assert result.status_code==201,result.text
    assert populated.extensions.get('bw_import_worker_active') is False
