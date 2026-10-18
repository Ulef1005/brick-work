from contextlib import closing
import os
import json
from xml.etree import ElementTree as ET

from tests.test_bw_api_m1 import app, call
from tests.test_bw_api_m2 import populated
from tests.test_bw_api_m3 import write, dbrows
from tests.test_bw_api_m1_contract import validate
from brickwork.core.connect import connect
from brickwork.core.mcp import Adapter
from brickwork.core.mcp.client import InProcessClient
from brickwork.web.cli import main


def test_api_list_lifecycle_transfer_and_receipt(populated):
    app=populated
    before=len(dbrows('events'))
    created=write(app,'/wishlists',body={'name':'Holiday'})
    assert created.status_code==201,created.text
    assert len(dbrows('events'))==before+1
    target=created.json['data']['id']
    validate(created.json,{'$ref':'#/components/schemas/WrittenWishlist'})
    assert write(app,'/wishlists',body={'name':'Holiday'}).json['idempotent_replay']
    renamed=write(app,'/wishlists/'+target,'patch',{'name':'Gifts'},key='rename')
    assert renamed.status_code==200 and renamed.json['data']['name']=='Gifts'
    moved=write(app,'/wishlists/'+target+'/transfer',body={'ids':[1]},key='move')
    assert moved.status_code==200,moved.text
    assert moved.json['data']['event_id']==moved.json['event_id']
    assert call(app,'/wishes?list=default').json['data']==[]
    assert call(app,'/wishes?list='+target).json['data'][0]['list_id']==target
    assert write(app,f"/events/{moved.json['event_id']}/undo",key='undo-move').status_code==200
    copied=write(app,'/wishlists/'+target+'/transfer',body={'ids':[1],'copy':True},key='copy')
    assert copied.status_code==200,copied.text
    assert len(call(app,'/wishes').json['data'])==2
    archived=write(app,'/wishlists/'+target,'delete',key='archive')
    assert archived.status_code==200,archived.text
    assert len(call(app,'/wishlists').json['data'])==1
    assert len(call(app,'/wishlists?archived=true').json['data'])==2
    restored=write(app,'/wishlists/'+target+'/restore',key='restore')
    assert restored.status_code==200,restored.text
    assert len(call(app,'/wishes?list='+target).json['data'])==1
    assert write(app,f"/events/{restored.json['event_id']}/undo",key='undo-restore').status_code==200


def test_api_wish_create_list_filter_export_summary_and_mcp(populated):
    app=populated
    target=write(app,'/wishlists',body={'name':'New'}).json['data']['id']
    created=write(app,'/wishes',body={'item_type':'S','item_no':'100-1','list_id':target,'condition':'any','decision':'another'},key='new-wish')
    assert created.status_code==201,created.text
    wish=call(app,'/wishes?list='+target).json['data'][0]
    assert wish['list_id']==target and wish['condition']=='any'
    download=call(app,'/wishlists/'+target+'/export.xml')
    assert download.status_code==200,download.text
    assert ET.fromstring(download.text).findtext('ITEM/ITEMID')=='100-1'
    summary=call(app,'/wishlists/'+target+'/export.csv?kind=sets&summary=true')
    assert summary.status_code==200 and summary.json['data']['summary']['omitted'][0]['item_no']=='100-1'
    adapter=Adapter(InProcessClient(app,'synthetic-bootstrap'),allow_write=True)
    names={t.name for t in adapter.list_tools()}
    assert {'get_wishlists','post_wishlists','patch_wishlists_id','post_wishlists_id_transfer','export_wishlist_xml','export_wishlist_csv'} <= names
    output=adapter.call_tool('export_wishlist_xml',{'id':target,'summary':True})
    assert not output.isError and output.structuredContent['summary']['exported']==1
    assert not adapter.call_tool('post_wishlists',{'name':'MCP'}).isError


def test_cli_lists_and_export(populated,capsys):
    assert main(['wishlist','create','CLI','--json'])==0
    result=json.loads(capsys.readouterr().out);target=result['id']
    assert main(['wishlist','copy',target,'1','--json'])==0
    event=json.loads(capsys.readouterr().out)['event_id']
    assert main(['wishlist','export','CLI','--format','bricklink'])==0
    output=capsys.readouterr()
    assert ET.fromstring(output.out).findtext('ITEM/ITEMID')=='3001'
    assert json.loads(output.err)['exported']==1
    assert main(['wishlist','export','all','--format','rebrickable','--kind','parts','--json'])==0
    assert json.loads(capsys.readouterr().out)['content'].startswith('Part,Color,Quantity')
    assert main(['wishlist','undo',str(event)])==0
    capsys.readouterr()
    assert main(['wishlist','archive',target,'--json'])==0
    capsys.readouterr()
    assert main(['wishlist','restore',target,'--json'])==0


def test_list_writes_readonly_and_rollback(populated,monkeypatch):
    app=populated
    before=dbrows('wishlists')
    monkeypatch.setenv('BW_READ_ONLY','true')
    assert write(app,'/wishlists',body={'name':'No'}).status_code==403
    assert call(app,'/wishlists/all/export.xml').status_code==200
    monkeypatch.delenv('BW_READ_ONLY')
    from brickwork.core import admin
    real=admin.audit
    def fail(db,entity,field,*args,**kwargs):
        if entity=='bw_api':raise RuntimeError('Injected')
        return real(db,entity,field,*args,**kwargs)
    monkeypatch.setattr(admin,'audit',fail)
    assert write(app,'/wishlists',body={'name':'Fail'}).status_code==500
    assert dbrows('wishlists')==before
