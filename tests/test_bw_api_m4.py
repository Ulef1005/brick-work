"""M4 direct checker writes and manual observations, entirely offline."""
from contextlib import closing
from copy import deepcopy
import json
import os

import pytest

from tests.test_bw_api_m1 import app, call, create as token_create
from tests.test_bw_api_m2 import populated
from tests.test_bw_api_m3 import write, dbrows
from tests.test_bw_api_m1_contract import CONTRACT, validate
from brickwork.core import admin, checker, completeness
from brickwork.core.connect import connect

CASES = [
 ('/copies/c1/parts/1','patch',{'missing':0,'damaged':0,'checked':True},'copy_parts','/copies/{id}/parts/{part_id}'),
 ('/copies/c1/parts/bulk','post',{'items':[{'item_no':'3001','color_id':4,'missing':0}]},'copy_parts','/copies/{id}/parts/bulk'),
 ('/copies/c1/figures/M/fig1','patch',{'missing':0},'copy_minifigs','/copies/{id}/figures/{type}/{no}'),
 ('/copies/c1/checked','put',{'checked':True},'copies','/copies/{id}/checked'),
 ('/stock/m1/parts','patch',{'parts':[{'item_no':'3001','color_id':4,'spare':0,'missing':0,'damaged':1}]},'loose_minifig_parts','/stock/{id}/parts'),
 ('/items/P/3001/prices','post',{'color_id':4,'condition':'used','guide':'manual','price':'3.50','currency':'EUR'},'price_observations','/items/{type}/{no}/prices'),
 ('/prices/observations','post',{'items':[{'item_type':'P','item_no':'3001','color_id':4,'condition':'used','guide':'valuation','price':'4.50','currency':'EUR'}]},'price_observations','/prices/observations'),
]


@pytest.mark.parametrize('path,method,body,table,template',CASES)
def test_write_contract_audit_replay_undo(populated,path,method,body,table,template):
    before=dbrows(table); events=dbrows('events')
    response=write(populated,path,method,body)
    expected=201 if template=='/items/{type}/{no}/prices' else 200
    assert response.status_code==expected,response.text
    op=CONTRACT['paths'][template][method]
    validate(body,op['requestBody']['content']['application/json']['schema'])
    validate(response.json,op['responses'][str(expected)]['content']['application/json']['schema'])
    assert len(dbrows('events'))==len(events)+1
    assert (dbrows('events')[-1]['via'],dbrows('events')[-1]['actor'])==('api','bootstrap')
    identifier=response.json['event_id']
    assert call(populated,f'/events/{identifier}').json['data']['undoable']
    assert write(populated,path,method,body).json['idempotent_replay']
    assert len(dbrows('events'))==len(events)+1
    altered=deepcopy(body)
    if 'missing' in altered:altered['missing']=1
    else:altered['synthetic_unknown']=True
    # Schema validation can reject malformed replay bodies before replay lookup.
    assert write(populated,path,method,altered).status_code in (409,422)
    undone=write(populated,f'/events/{identifier}/undo',key='synthetic-undo')
    assert undone.status_code==200,undone.text
    if table=='price_observations':
        assert all(r['error']=='undone' for r in dbrows(table)[len(before):])
    else:assert dbrows(table)==before
    assert len(dbrows('events'))==len(events)+2


@pytest.mark.parametrize('path,method,body,table,template',CASES)
def test_write_atomic_failure(populated,monkeypatch,path,method,body,table,template):
    tables=['copies','copy_parts','copy_minifigs','loose_minifig_parts','item_flags','flags','price_observations','price_current','events']
    before={t:dbrows(t) for t in tables}
    real=admin.audit
    def fail(db,entity,field,*args,**kwargs):
        if entity=='bw_api':raise RuntimeError('Synthetic failure')
        return real(db,entity,field,*args,**kwargs)
    monkeypatch.setattr(admin,'audit',fail)
    response=write(populated,path,method,body)
    assert response.status_code==500,response.text
    assert {t:dbrows(t) for t in tables}==before


@pytest.mark.parametrize('path,method,body,table,template',CASES)
def test_scopes_read_only_archives_and_missing(populated,monkeypatch,path,method,body,table,template):
    token=token_create(populated,'synthetic-reader',['read']).json['data']['secret']
    before=dbrows(table)
    assert write(populated,path,method,body,token=token).status_code==403
    monkeypatch.setenv('BW_READ_ONLY','1')
    assert write(populated,path,method,body).status_code==403
    assert dbrows(table)==before
    monkeypatch.delenv('BW_READ_ONLY')
    if path.startswith(('/copies/','/stock/')):
        missing=path.replace('/c1','/absent').replace('/m1','/absent')
        assert write(populated,missing,method,body).status_code==404
        archive=write(populated,'/copies/c1' if path.startswith('/copies') else '/stock/m1','delete',key='archive')
        assert archive.status_code==200,archive.text
        assert write(populated,path,method,body).json['code']=='archived'


@pytest.mark.parametrize('path,method,body',[
 ('/copies/c1/parts/1','patch',{'missing':-1}),
 ('/copies/c1/parts/1','patch',{'missing':5}),
 ('/copies/c1/parts/1','patch',{'missing':True}),
 ('/copies/c1/parts/1','patch',{}),
 ('/copies/c1/figures/M/fig1','patch',{'missing':2}),
 ('/copies/c1/parts/bulk','post',{'items':[{'item_no':'3001','color_id':4,'missing':3}],'mode':'add'}),
 ('/copies/c1/parts/bulk','post',{'items':[]}),
 ('/stock/m1/parts','patch',{'parts':[{'item_no':'3001','color_id':4,'spare':0,'missing':2}]}),
 ('/stock/m1/parts','patch',{'parts':[{'item_no':'3001','color_id':4,'spare':0}]}),
 ('/stock/t1/parts','patch',{'parts':[{'item_no':'3001','color_id':4,'spare':0,'missing':0}]}),
 ('/prices/observations','post',{'items':[]}),
 ('/prices/observations','post',{'items':[{'item_type':'P','item_no':'3001','condition':'used','guide':'manual','price':'1.00','currency':'EUR'}]}),
 ('/items/P/3001/prices','post',{'color_id':4,'condition':'used','guide':'manual','price':'1.00','currency':'EUR','observed_at':'2026-10-01'}),
])
def test_invalid_bounds_rollback(populated,path,method,body):
    tables=['copy_parts','copy_minifigs','copies','price_observations','price_current','events']
    before={t:dbrows(t) for t in tables}
    response=write(populated,path,method,body)
    assert response.status_code==422,response.text
    assert {t:dbrows(t) for t in tables}==before


def test_bulk_set_add_preview_and_skips(populated):
    before=dbrows('copy_parts');events=dbrows('events')
    body={'items':[{'item_no':'3001','color_id':4,'missing':1},{'item_no':'absent','color_id':4,'missing':1}],'mode':'add','dry_run':True}
    result=write(populated,'/copies/c1/parts/bulk',body=body)
    assert result.status_code==200,result.text
    assert result.json['data']['applied']==1 and len(result.json['data']['skipped'])==1
    assert result.json['event_id'] is None and result.json['undo_url'] is None
    assert dbrows('copy_parts')==before and dbrows('events')==events
    body['dry_run']=False
    result=write(populated,'/copies/c1/parts/bulk',body=body)
    assert result.status_code==200,result.text
    assert dbrows('copy_parts')[0]['missing']==3
    body['mode']='set'
    assert write(populated,'/copies/c1/parts/bulk',body=body,key='set').status_code==200
    assert dbrows('copy_parts')[0]['missing']==1
    assert write(populated,'/copies/c1/parts/bulk',body=body,key=None).status_code==428


def test_marking_undo_blocked(populated):
    first=write(populated,'/copies/c1/parts/1','patch',{'missing':0})
    second=write(populated,'/copies/c1/parts/1','patch',{'missing':1},key='second')
    blocked=write(populated,f"/events/{first.json['event_id']}/undo",key='undo-first')
    assert blocked.status_code==409 and blocked.json['code']=='undo_blocked'
    assert write(populated,f"/events/{second.json['event_id']}/undo",key='undo-second').status_code==200
    assert write(populated,f"/events/{first.json['event_id']}/undo",key='undo-first').status_code==200


def test_figure_components_stay_on_figure_and_checker_parity(populated):
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        db.execute("UPDATE copy_parts SET missing=0,damaged=0")
        db.execute("UPDATE copy_minifigs SET missing=0")
        db.execute("INSERT INTO copy_parts(copy_id,parent_minifig_type,parent_minifig,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES('c1','M','fig1','P','3001',4,2,0,0,0)")
    assert write(populated,'/copies/c1/checked','put',{'checked':True}).json['data']['derived']=='complete'
    result=write(populated,'/copies/c1/parts/2','patch',{'missing':1,'checked':True},key='figure-part')
    assert result.status_code==200,result.text
    assert call(populated,'/copies/c1/completeness').json['data']['derived']=='complete'
    figures=call(populated,'/copies/c1/figures').json['data']
    assert figures[0]['parts_missing']==1
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        view=checker.write(db,'c1',{'action':'start','operation':'start'},'.',figure=('M','fig1'))
        checker.write(db,'c1',{'action':'answer','operation':'answer','session':view['session']['id'],'token':'p:2','found':0},'.',figure=('M','fig1'))
        assert completeness.derived_state(db,'c1')=='C'
        assert db.execute('SELECT missing FROM copy_parts WHERE id=2').fetchone()[0]==2
        assert db.execute('SELECT completeness FROM copies WHERE id=?',('c1',)).fetchone()[0]=='C'
    assert write(populated,'/copies/c1/parts/2','patch',{'missing':2},key='same-part').status_code==200
    assert call(populated,'/copies/c1/completeness').json['data']['derived']=='complete'
    assert write(populated,'/copies/c1/figures/M/fig1','patch',{'missing':1},key='whole-missing').status_code==200
    assert call(populated,'/copies/c1/completeness').json['data']['derived']=='incomplete'


def test_price_void_recomputes_latest_nonvoid_by_full_key(populated):
    body={'color_id':4,'condition':'used','guide':'manual','slot':'estimate','price':'1.25','currency':'EUR'}
    first=write(populated,'/items/P/3001/prices',body=body,key='first')
    second=write(populated,'/items/P/3001/prices',body=dict(body,price='2.50'),key='second')
    third=write(populated,'/items/P/3001/prices',body=dict(body,currency='USD',price='3.75'),key='third')
    assert first.status_code==second.status_code==third.status_code==201,second.text
    assert write(populated,f"/events/{second.json['event_id']}/undo",key='undo-second').status_code==200
    current=dbrows('price_current')
    assert next(r['observation_id'] for r in current if r['guide']=='manual' and r['currency']=='EUR')==first.json['data']['id']
    assert next(r['observation_id'] for r in current if r['guide']=='manual' and r['currency']=='USD')==third.json['data']['id']
    assert write(populated,f"/events/{first.json['event_id']}/undo",key='undo-first').status_code==200
    assert not any(r['guide']=='manual' and r['currency']=='EUR' for r in dbrows('price_current'))
    assert len(dbrows('price_observations'))==4


def test_price_batch_failure_and_limit(populated):
    item={'item_type':'P','item_no':'3001','color_id':4,'condition':'used','guide':'manual','price':'1.00','currency':'EUR'}
    before=dbrows('price_observations');events=dbrows('events')
    result=write(populated,'/prices/observations',body={'items':[item,dict(item,color_id=999)]})
    assert result.status_code==422,result.text
    assert dbrows('price_observations')==before and dbrows('events')==events
    assert write(populated,'/prices/observations',body={'items':[item]*501}).status_code==422
    assert write(populated,'/prices/observations',body={'items':[item]},key=None).status_code==428
    result=write(populated,'/prices/observations',body={'items':[item,dict(item,price='2.00')]})
    assert result.status_code==200,result.text
    assert write(populated,f"/events/{result.json['event_id']}/undo",key='undo-batch').status_code==200
    assert len(dbrows('price_current'))==1  # Original market observation survives.


def test_manual_price_receipt_undone_only_after_undo(populated):
    from brickwork.core import api_reads, manual_prices
    item=dict(item_type='P',item_no='3001',color_id=4,condition='used',guide='manual',price='1.00',currency='EUR')
    with closing(connect(os.environ['BW_DB_PATH'])) as db,db:
        manual_prices.record(db,[item])
        event=db.execute("SELECT * FROM events WHERE entity='bw_manual_prices' AND field='receipt'").fetchone()
        probe=lambda: db.execute(f"SELECT {api_reads.undone_sql('e')},{api_reads.undoable_sql('e')} FROM events e WHERE id=?",(event['id'],)).fetchone()
        assert tuple(probe())==(0,1)
        manual_prices.undo(db,event)
        assert tuple(probe())==(1,1)


def test_clear_checked_without_flag_is_noop(populated):
    flags=dbrows('flags');links=dbrows('item_flags')
    result=write(populated,'/copies/c1/checked','put',{'checked':False},key='clear')
    assert result.status_code==200,result.text
    assert result.json['data']['derived'] in ('complete','incomplete','unknown')
    assert dbrows('flags')==flags and dbrows('item_flags')==links
    assert write(populated,f"/events/{result.json['event_id']}/undo",key='undo-clear').status_code==200
    assert dbrows('flags')==flags
    assert write(populated,'/copies/c1/checked','put',{'checked':True},key='set').status_code==200
    assert len(dbrows('flags'))==len(flags)+1


@pytest.mark.parametrize('kind',[None,'Z'])
def test_price_item_type_validation(populated,kind):
    item={'item_type':kind,'item_no':'3001','color_id':4,'condition':'used','guide':'manual','price':'1.00','currency':'EUR'}
    before=dbrows('price_observations')
    assert write(populated,'/prices/observations',body={'items':[item]}).status_code==422
    assert write(populated,'/prices/observations',body={'items':[dict(item,item_type='P'),item]},key='two').status_code==422
    single={k:v for k,v in item.items() if k not in ('item_type','item_no')}
    assert write(populated,'/items/Z/3001/prices',body=single,key='single').status_code==422
    assert dbrows('price_observations')==before
    from brickwork.core import errors, manual_prices
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        with pytest.raises(errors.ValidationFailed):
            manual_prices.record(db,[{k:v for k,v in item.items() if k!='item_type'}])
