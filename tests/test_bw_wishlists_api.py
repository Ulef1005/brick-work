"""The MCP half of the wishlist API test (still the 3.3 text, waits for M.11e).

M.11b ported the reads of this file and M.11c (issue #113) its writes and the CLI to API v2 (tests/test_api2_write_collection.py,
tests/test_api2_read_money.py, tests/test_cli_wishlists.py). What is left is the check that the MCP server offers the wishlist tools and
exports through them: M.11e regenerates the MCP from the v2 contract and ports it. (`write` and `dbrows` are the helpers test_bw_api_m3 had.)"""
from contextlib import closing
import os
from xml.etree import ElementTree as ET

from tests.test_bw_api_m1 import app, call
from tests.test_bw_api_m2 import populated
from brickwork.core.connect import connect
from brickwork.core.mcp import Adapter
from brickwork.core.mcp.client import InProcessClient


def write(app,path,method='post',body=None,key='synthetic-operation',extra=None,token='synthetic-bootstrap'):
    headers={'Authorization':'Bearer '+token,**(extra or {})}
    if key is not None:headers['Idempotency-Key']=key
    return app.test_client().open('/api/v1'+path,method=method,headers=headers,**({'json':body} if body is not None else {}))


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
