"""M7's protocol surface is generated from OpenAPI and uses only API routes."""
import ast
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
import pytest
from starlette.testclient import TestClient

from tests.test_bw_api_m1 import app, call, create
from tests.test_bw_api_m2 import populated
from brickwork.core.connect import connect
from brickwork.core.mcp import Adapter, CONTRACT, contract
from brickwork.core.mcp.client import InProcessClient, HTTPClient
from brickwork.core.mcp.server import http_app, protocol

TOKEN = 'synthetic-bootstrap'
DEFINITIONS = Adapter(None).tools
READS = [n for n, (m, _, _) in DEFINITIONS.items() if m == 'GET']
WRITES = [n for n, (m, _, _) in DEFINITIONS.items() if m != 'GET']


@pytest.fixture
def adapter(populated, monkeypatch):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE id_match SET status='matched'")
    with sqlite3.connect(Path(os.environ['BW_DB_PATH']).with_name('bricklink-catalog.db')) as db:
        db.execute("INSERT INTO items VALUES('P','3001','Synthetic brick','Synthetic',2025,'synthetic brick')")
    return Adapter(InProcessClient(populated, TOKEN), allow_write=True)


def run_tool(adapter, name, args):
    async def run():
        async with create_connected_server_and_client_session(protocol(lambda: adapter)) as session:
            return await session.call_tool(name, args)
    return anyio.run(run)


def payload(result):
    return json.loads(result.content[0].text)


def test_generated_surface():
    md = CONTRACT.with_name('api-v1.md').read_text()
    tables = md.split('### 7.4')[1].split('### 7.6')[0]
    rows = re.findall(r'\| `([a-z_]+)` \|.*?\| `(GET|POST|PATCH|PUT|DELETE) ([^`]+)` \|', tables)
    assert {n: (m, p) for n, m, p in rows} == {n: (m, p) for n, (m, p, _) in DEFINITIONS.items()}
    assert len(READS) == 31 and len(WRITES) == 30
    for name, (method, path, op) in DEFINITIONS.items():
        assert op['security'] == [{'bearerAuth': ['read' if method == 'GET' else 'write']}]
        assert op['summary'] and op['x-backing']
    assert len(contract()['x-mcp']['resources']) == 8


@pytest.mark.parametrize('scope', ['read', 'write', 'admin'])
@pytest.mark.parametrize('flag', [False, True])
def test_gate_and_direct_call(app, scope, flag):
    token = create(app, scopes=[scope]).json['data']['secret']
    adapter = Adapter(InProcessClient(app, token), allow_write=flag)
    assert {t.name for t in adapter.list_tools()} == set(READS + (WRITES if flag and scope != 'read' else []))
    if not flag or scope == 'read':
        result = run_tool(adapter, 'create_storage', {'name': 'Synthetic'})
        assert result.isError and payload(result)['code'] == 'forbidden'
        assert all(row['id'] == 'unstored' for row in call(app, '/storages').json['data'])


def test_revocation_and_read_only(app, monkeypatch):
    response = create(app, scopes=['write']).json['data']
    adapter = Adapter(InProcessClient(app, response['secret']), allow_write=True)
    assert 'create_storage' in {t.name for t in adapter.list_tools()}
    monkeypatch.setenv('BW_READ_ONLY', '1')
    assert payload(run_tool(adapter, 'create_storage', {'name': 'Synthetic'}))['code'] == 'read_only_instance'
    monkeypatch.delenv('BW_READ_ONLY')
    call(app, '/tokens/' + str(response['token']['id']), 'delete')
    assert {t.name for t in adapter.list_tools()} == set(READS)
    assert payload(run_tool(adapter, 'create_storage', {'name': 'Synthetic'}))['code'] == 'forbidden'


@pytest.mark.parametrize('name', READS)
def test_every_read_round_trip(adapter, name):
    args = {}
    for p in DEFINITIONS[name][2].get('parameters', []):
        if p['in'] == 'path':
            args[p['name']] = {'source': 'rebrickable', 'type': 'S', 'no': '100-1', 'id': 'default' if name.startswith('export_wishlist_') else 1 if name == 'get_order' else 'c1'}[p['name']]
    result = run_tool(adapter, name, args)
    assert not result.isError, payload(result)
    assert result.content


WRITE_ARGS = {
 'post_wishlists': {'name':'Synthetic wishlist'},
 'patch_wishlists_id': {'id':'default','name':'Synthetic renamed'},
 'delete_wishlists_id': {'id':'default'},
 'post_wishlists_id_restore': {'id':'default'},
 'post_wishlists_id_transfer': {'id':'default','ids':[1]},
 'import_item': {'type': 'S', 'no': '100-1'},
 'add_copies': {'item_no': '100-1', 'quantity': 1, 'decision': 'another'},
 'update_copy': {'id': 'c1', 'fields': {'note': 'Synthetic note'}},
 'archive_copy': {'id': 'c1'},
 'set_copy_checked': {'id': 'c1', 'checked': True},
 'take_for_gap': {'id': 'c1', 'item_type': 'P', 'item_no': '3001', 'color_id': 4, 'quantity': 1},
 'set_part_missing': {'id': 'c1', 'part_id': 1, 'missing': 1, 'damaged': 0},
 'set_figure_missing': {'id': 'c1', 'type': 'M', 'no': 'fig1', 'missing': 0},
 'add_stock': {'item_type': 'P', 'item_no': '3001', 'color_id': 4, 'quantity': 1},
 'update_stock': {'id': 't1', 'fields': {'note': 'Synthetic note'}},
 'give_from_stock': {'id': 't1', 'copy_id': 'c1', 'target': 'part', 'target_id': 1, 'quantity': 1},
 'record_price': {'type': 'S', 'no': '100-1', 'condition': 'used', 'guide': 'manual', 'price': '12', 'currency': 'EUR'},
 'refresh_price': {'type': 'S', 'no': '100-1'},
 'add_wish': {'item_type': 'S', 'item_no': '100-1', 'quantity': 1, 'decision': 'another'},
 'update_wish': {'id': 1, 'fields': {'note': 'Synthetic note'}},
 'archive_wish': {'id': 1},
 'wish_to_owned': {'id': 1},
 'create_storage': {'name': 'Synthetic new storage'},
 'move_to_storage': {'id': 's1', 'selections': [{'entity': 'copy', 'id': 'c1'}]},
 'plan_sync_pull': {'source': 'rebrickable'},
 'apply_sync_pull': {'source': 'rebrickable'},
 'plan_sync_send': {'source': 'rebrickable'},
 'import_order': {'source': 'xml', 'text': '<INVENTORY><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>100-1</ITEMID><QTY>1</QTY><CONDITION>U</CONDITION></ITEM></INVENTORY>'},
 'undo_event': {},
 'retry_job': {'id': 1},
}


class SyncStub:
    """The remote side of a sync: one owned set, nothing wanted."""
    def fetch(self, link):
        return dict(owned={'100-1': 2}, wanted={}, per_list={'1': {'100-1': 2}}, owned_lists=[1], names={})

    def lists(self):
        return [dict(id=1, name='Synthetic', sets=1)]


@pytest.mark.parametrize('name', WRITES)
def test_every_write_round_trip(adapter, name, monkeypatch):
    args = WRITE_ARGS[name]
    if 'sync' in name:
        from brickwork.core.sync import adapters as sync_adapters
        monkeypatch.setattr(sync_adapters, 'adapter', lambda db, source, http=None: SyncStub())
    if name == 'apply_sync_pull':
        plan = payload(run_tool(adapter, 'plan_sync_pull', {'source': 'rebrickable'}))
        args = {'source': 'rebrickable', 'plan_id': plan['data']['id']}
    if name == 'post_wishlists_id_restore':
        run_tool(adapter, 'delete_wishlists_id', {'id':'default'})
    if name == 'retry_job':
        made = run_tool(adapter, 'import_item', {'type': 'S', 'no': '100-1'})
        job = payload(made)['data']['id']
        with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
            db.execute("UPDATE jobs SET state='failed' WHERE id=?", (job,))
            db.execute("UPDATE import_steps SET state='failed' WHERE job_id=?", (job,))
        args = {'id': job}
    if name == 'undo_event':
        made = run_tool(adapter, 'create_storage', {'name': 'Synthetic undo'})
        args = {'id': payload(made)['event_id']}
    result = run_tool(adapter, name, args)
    assert not result.isError, payload(result)
    value = payload(result)
    assert 'event_id' in value and 'undo_url' in value


def test_replay_etag_validation_errors_and_pages(adapter):
    args = {'name': 'Synthetic replay', 'idempotency_key': 'synthetic-stable-key'}
    first = payload(run_tool(adapter, 'create_storage', args))
    second = payload(run_tool(adapter, 'create_storage', args))
    assert first['event_id'] == second['event_id'] and second['idempotent_replay']
    assert payload(run_tool(adapter, 'update_copy', {'id': 'c1', 'fields': {'note': 'Synthetic'}, 'if_match': '"stale"'}))['code'] == 'precondition_failed'
    invalid = run_tool(adapter, 'update_copy', {'id': 'c1', 'fields': {'condition': 'invalid'}})
    assert invalid.isError
    assert payload(run_tool(adapter, 'get_copy', {'id': 'absent'}))['code'] == 'not_found'
    assert 'page' in payload(run_tool(adapter, 'list_copies', {'limit': 1}))


def test_resources(adapter):
    async def run():
        async with create_connected_server_and_client_session(protocol(lambda: adapter)) as session:
            assert len((await session.list_resources()).resources) == 6
            assert len((await session.list_resource_templates()).resourceTemplates) == 2
            for template in contract()['x-mcp']['resources']:
                uri = template.replace('{id}', 'c1').replace('{type}', 'S').replace('{no}', '100-1')
                result = await session.read_resource(uri)
                assert result.contents[0].text
    anyio.run(run)


def test_http_transport_and_token_isolation(app):
    read = create(app).json['data']['secret']
    with TestClient(http_app(app, allow_write=True)) as client:
        assert client.get('/api/v1/health').status_code == 200
        def rpc(token, method, params=None):
            return client.post('/mcp', headers={'Authorization': 'Bearer ' + token,
                'Accept': 'application/json, text/event-stream'}, json={'jsonrpc': '2.0', 'id': 1,
                    'method': method, **({'params': params} if params is not None else {})})
        assert rpc('invalid', 'tools/list').status_code == 401
        init = rpc(TOKEN, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'synthetic', 'version': '1'}})
        assert init.status_code == 200, init.text
        assert len(rpc(TOKEN, 'tools/list').json()['result']['tools']) == len(READS)+len(WRITES)
        assert len(rpc(read, 'tools/list').json()['result']['tools']) == len(READS)
        denied = rpc(read, 'tools/call', {'name': 'create_storage', 'arguments': {'name': 'Synthetic'}})
        assert denied.json()['result']['isError']
        made = rpc(TOKEN, 'tools/call', {'name': 'create_storage', 'arguments': {'name': 'Synthetic'}})
        assert not made.json()['result']['isError'], made.text
        result = rpc(read, 'tools/call', {'name': 'list_storages', 'arguments': {}})
        assert 'Synthetic' in result.text
    with TestClient(http_app(app)) as client:
        result = client.post('/mcp', headers={'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/json, text/event-stream'},
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        assert len(result.json()['result']['tools']) == len(READS)


def test_no_domain_imports():
    forbidden = {'collection', 'add', 'workbench', 'checker', 'orders'}
    for path in CONTRACT.parents[2].joinpath('brickwork/core/mcp').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, 'module', '') or '']
                assert not any(set(n.split('.')) & forbidden for n in names)


def test_http_client(monkeypatch):
    import requests
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"data": {"name": "Synthetic"}}'
        return response
    monkeypatch.setattr(requests, 'request', request)
    result = HTTPClient('http://127.0.0.1:5000/api/v1', TOKEN).request('GET', '/me')
    assert result[1]['data']['name'] == 'Synthetic'
    assert calls[0][2]['allow_redirects'] is False
    assert calls[0][2]['headers']['Authorization'] == 'Bearer ' + TOKEN


def test_stdio_offline_token_file(app, tmp_path):
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    token = create(app, scopes=['write']).json['data']['secret']
    path = tmp_path / 'synthetic-token'
    path.write_text(token)
    # The child also blocks sockets, so this exercises the standalone path offline.
    code = "import socket; socket.socket.connect=lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network disabled')); from brickwork.web.cli import main; main()"
    params = StdioServerParameters(command=sys.executable, env=dict(os.environ), args=['-c', code, 'mcp', '--in-process', '--allow-write', '--token-file', str(path)])
    async def run():
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                assert len((await session.list_tools()).tools) == len(READS)+len(WRITES)
                made = await session.call_tool('create_storage', {'name': 'Synthetic stdio'})
                assert not made.isError
                assert payload(made)['event_id']
    anyio.run(run)
    assert any(row['name'] == 'Synthetic stdio' for row in call(app, '/storages').json['data'])


def test_queue_identity_audit_replay_and_failure(adapter):
    from tests.test_bw_api_m1_contract import validate, CONTRACT as API_CONTRACT
    name = 'import_item'
    args = {'type': 'S', 'no': '100-1', 'idempotency_key': 'synthetic-import'}
    made = payload(run_tool(adapter, name, args))
    replay = payload(run_tool(adapter, name, args))
    assert replay['idempotent_replay'] and replay['event_id'] == made['event_id']
    validate(made, API_CONTRACT['paths']['/items/{type}/{no}/import']['post']['responses']['202']['content']['application/json']['schema'])
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        row = db.execute('SELECT via,actor FROM events WHERE id=?', (made['event_id'],)).fetchone()
        assert tuple(row) == ('api', 'bootstrap')
        before = db.execute('SELECT count(*) FROM jobs').fetchone()[0]
    assert made['undo_url'] is None
    assert payload(run_tool(adapter, 'undo_event', {'id': made['event_id']}))['code'] == 'not_undoable'
    failed = run_tool(adapter, name, {'type': 'S', 'no': 'absent'})
    assert failed.isError and payload(failed)['code'] == 'not_found'
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == before
        assert db.execute("SELECT 1 FROM items WHERE item_no='absent'").fetchone() is None


def test_cli_flags_and_environment(app, monkeypatch, tmp_path):
    from brickwork.web.cli import main
    from brickwork.core.mcp import server
    received = []
    received_run = server.run
    monkeypatch.setattr(server, 'run', lambda **kwargs: received.append(kwargs))
    assert main(['mcp', '--in-process', '--allow-write', '--token-file', 'synthetic-token']) == 0
    assert received[0]['in_process'] and received[0]['allow_write']
    assert received[0]['token_file'] == 'synthetic-token'
    captured = []
    monkeypatch.setattr(server.anyio, 'run', lambda func, adapter: captured.append(adapter))
    monkeypatch.setenv('BW_MCP_WRITE', '1')
    token_file = tmp_path / 'synthetic-read-token'
    token_file.write_text(create(app).json['data']['secret'])
    received_run(in_process=True, token_file=token_file)
    assert captured[0].allow_write
    assert {t.name for t in captured[0].list_tools()} == set(READS)


@pytest.mark.parametrize('arguments', [None, {}])
def test_no_argument_read(adapter, arguments):
    result = adapter.call_tool('list_storages', arguments)
    assert not result.isError
    assert payload(result)['data']
    assert not adapter.call_tool('list_storages').isError


def test_protocol_read_without_arguments(adapter):
    async def run():
        async with create_connected_server_and_client_session(protocol(lambda: adapter)) as session:
            result = await session.call_tool('list_storages')
            assert not result.isError
            assert payload(result)['data']
    anyio.run(run)


def test_missing_copy_resource_is_mcp_error(adapter):
    from mcp.shared.exceptions import McpError
    with pytest.raises(McpError, match=r'not_found.*404'):
        adapter.read_resource('brickwork://copies/missing')

    async def run():
        async with create_connected_server_and_client_session(protocol(lambda: adapter)) as session:
            with pytest.raises(McpError, match=r'not_found.*404'):
                await session.read_resource('brickwork://copies/missing')
    anyio.run(run)


@pytest.mark.parametrize('status', [199, 301, 401, 500])
def test_resource_rejects_all_non_success_statuses(status):
    from mcp.shared.exceptions import McpError
    class Client:
        def request(self, method, path):
            return status, {'code': 'synthetic_problem'}
    with pytest.raises(McpError, match=f'synthetic_problem.*{status}'):
        Adapter(Client()).read_resource('brickwork://summary')
