"""#595: Separate Added via labels for API, CLI and MCP channels (schema 4.8 provenance)."""
from contextlib import closing

import pytest

from brickwork.core import mcp, stock
from brickwork.core.connect import connect
from brickwork.core.mcp import client as mcp_client
from brickwork.core.sources.base import audit_origin
from brickwork.core.transaction import transaction
from brickwork.store4 import origins
from brickwork.store4.errors import Store4Error
from tests.api2 import app4, coll, stored_token, v2  # noqa: F401
from tests.app4 import Coll, make_pair
from tests.test_bw_sync import EXTRA
from tests.test_origins import GEAR, added_via, pair, store  # noqa: F401


def _find_create_operation(spec, item_id, item_key):
    """Find an API v2 POST route creating a copy, wish or stock row and build a valid request."""
    def is_item_key(schema):
        return isinstance(schema, dict) and (
            schema.get('x-mcp-item') == 'key'
            or any(isinstance(s, dict) and s.get('x-mcp-item') == 'key' for s in schema.get('allOf', []))
        )

    for suffixes, table in ((('/copies',), 'copy'), (('/wishes', '/wishlist'), 'wish'), (('/stock', '/loose'), 'stock')):
        candidates = sorted(
            (p for p, m in spec['paths'].items() if p.endswith(suffixes) and 'post' in m),
            key=len,
        )
        for raw_path in candidates:
            op = mcp.resolve(spec, spec['paths'][raw_path]['post'])
            path = raw_path
            for param in op.get('parameters', []):
                if param['in'] == 'path':
                    path = path.replace('{' + param['name'] + '}', str(item_id))
            body = {}
            schema = op.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
            if schema:
                if 'oneOf' in schema or 'anyOf' in schema:
                    branches = schema.get('oneOf') or schema.get('anyOf')
                    schema = next(
                        (b for b in branches if isinstance(b, dict) and (
                            is_item_key(b) or any(is_item_key(v) for v in b.get('properties', {}).values())
                        )),
                        branches[0],
                    )
                if is_item_key(schema):
                    body.update(item_key)
                else:
                    props = dict(schema.get('properties', {}))
                    required = set(schema.get('required', []))
                    for part in schema.get('allOf', []):
                        if isinstance(part, dict):
                            props.update(part.get('properties', {}))
                            required.update(part.get('required', []))
                    item_prop = next((k for k, v in props.items() if is_item_key(v)), None)
                    if item_prop is not None:
                        body[item_prop] = item_key
                    elif 'item_id' in props:
                        body['item_id'] = item_id
                    for name in required:
                        if name in body:
                            continue
                        ps = props.get(name, {})
                        if name == 'item_id':
                            body[name] = item_id
                        elif ps.get('enum'):
                            body[name] = ps['enum'][0]
                        elif ps.get('type') == 'integer':
                            body[name] = 1
                        elif ps.get('type') == 'string':
                            body[name] = item_key.get(name, item_key['key'])
            return path, body, table
    raise AssertionError('no create endpoint for copy, wish or stock in openapi-v2.yaml')


def test_channel_origins_match_table_and_labels(store):
    rows_by_id = dict(store.execute('SELECT id, kind FROM origin').fetchall())
    expected = {'api': 'Via the API', 'cli': 'Via the CLI', 'mcp': 'Via MCP'}
    for name, text in expected.items():
        assert rows_by_id[name] == 'channel'
        assert origins.ORIGINS[name] == 'channel'
        assert origins.LABELS[name] == text
        assert origins.label(name) == text
    assert rows_by_id == origins.ORIGINS
    assert set(origins.LABELS) == set(origins.ORIGINS) | {None}


def test_body_for_mcp_row_gives_via_mcp_label():
    assert origins.body('mcp', []) == {
        'added_via': 'mcp',
        'added_via_label': 'Via MCP',
        'last_synced_from': [],
    }


def test_channel_context_and_validation():
    assert origins.current() == 'hand'
    with audit_origin('api'):
        assert origins.current() == 'api'
        with audit_origin('app'):
            assert origins.current() == 'hand'
        assert origins.current() == 'api'
        with origins.channel('mcp'):
            assert origins.current() == 'mcp'
        assert origins.current() == 'api'
        with origins.channel(None):
            assert origins.current() == 'hand'
        assert origins.current() == 'api'
    assert origins.current() == 'hand'
    for bad in ('hand', 'rebrickable', 'bricklink_xml', 'unknown'):
        with pytest.raises(Store4Error):
            with origins.channel(bad):
                pass


@pytest.mark.parametrize('via, expected', [
    ('api', 'api'),
    ('cli', 'cli'),
    ('app', 'hand'),
    ('import', 'hand'),
    ('migration', 'hand'),
])
def test_audit_origin_sets_channel_on_new_rows(store, via, expected):
    gear = store.execute('SELECT id FROM catalogue.item WHERE born_key=?', (GEAR,)).fetchone()[0]
    with audit_origin(via), transaction(store):
        made = stock.add_loose(store, item_id=gear, quantity=1, condition='new')
    assert added_via(store, 'stock')[made['id']] == expected
    assert origins.current() == 'hand'


def test_adding_wins_over_channel(store):
    gear = store.execute('SELECT id FROM catalogue.item WHERE born_key=?', (GEAR,)).fetchone()[0]
    with audit_origin('api'), origins.adding('rebrickable'), transaction(store):
        made = stock.add_loose(store, item_id=gear, quantity=1, condition='new')
    assert added_via(store, 'stock')[made['id']] == 'rebrickable'
    with origins.adding('rebrickable'), audit_origin('cli'):
        assert origins.current() == 'rebrickable'
    assert origins.current() == 'hand'


def test_mcp_clients_send_channel_header(monkeypatch):
    seen = []

    class FakeHTTPResponse:
        status_code = 200
        headers = {'Content-Type': 'application/json'}
        text = '{"data": {}}'

        def json(self):
            return {'data': {}}

    def fake_request(method, url, **kwargs):
        seen.append((method, url, kwargs['headers']))
        return FakeHTTPResponse()

    monkeypatch.setattr(mcp_client.requests, 'request', fake_request)
    status, data = mcp_client.HTTPClient('http://127.0.0.1:3333/api/v2', 'tok').request(
        'POST', '/copies', body={'x': 1}, headers={'Idempotency-Key': 'k1'}
    )
    assert status == 200 and data == {'data': {}}
    assert seen == [('POST', 'http://127.0.0.1:3333/api/v2/copies', {
        'Authorization': 'Bearer tok',
        'X-Brickwork-Channel': 'mcp',
        'Idempotency-Key': 'k1',
    })]

    inproc_seen = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def open(self, path, **kwargs):
            inproc_seen.append((path, kwargs['headers']))

            class Resp:
                status_code = 200
                is_json = True

                def get_json(self, silent=True):
                    return {'data': {}}

            return Resp()

    class FakeApp:
        def test_client(self):
            return FakeClient()

    status, data = mcp_client.InProcessClient(FakeApp(), 'tok').request(
        'GET', '/me', headers={'X-Extra': '1'}
    )
    assert status == 200 and data == {'data': {}}
    assert inproc_seen == [('/api/v2/me', {
        'Authorization': 'Bearer tok',
        'X-Brickwork-Channel': 'mcp',
        'X-Extra': '1',
    })]


class TestApiChannels:
    @pytest.fixture
    def pair(self, tmp_path):
        path = make_pair(tmp_path, rich=True, extra_dump=EXTRA)
        with closing(connect(path)) as db:
            Coll(db).add_copy('2070-1')
        return path

    def test_api_v2_writes_use_api_or_mcp_channel(self, app4, v2, pair):
        with closing(connect(pair, read_only=True)) as db:
            item_id, provider, kind, key = db.execute(
                "SELECT id, born_provider, kind, born_key FROM item WHERE born_key='2070-1'"
            ).fetchone()
        path, body, table = _find_create_operation(
            mcp.contract(), item_id, {'provider': provider, 'kind': kind, 'key': key}
        )
        body = {**body, 'decision': 'another'}   # 2070-1 is owned already; the API adds another copy
        token = stored_token(pair, ['read', 'write'], 'writer')

        def snapshot():
            with closing(connect(pair, read_only=True)) as db:
                return added_via(db, table)

        for key_id, extra_headers, expected in (
            ('ch-api', {}, 'api'),
            ('ch-mcp', {'X-Brickwork-Channel': 'mcp'}, 'mcp'),
            ('ch-ignored', {'X-Brickwork-Channel': 'cli'}, 'api'),
        ):
            before = set(snapshot())
            res = v2.post(
                '/api/v2' + path,
                headers={'Authorization': 'Bearer ' + token, 'Idempotency-Key': key_id, **extra_headers},
                json=body,
            )
            assert res.status_code in (200, 201), res.json
            after = snapshot()
            new_ids = set(after) - before
            assert len(new_ids) == 1
            assert after[next(iter(new_ids))] == expected
            assert origins.current() == 'hand'

        before = set(snapshot())
        status, payload = mcp_client.InProcessClient(app4, token).request(
            'POST', path, body=body, headers={'Idempotency-Key': 'ch-inproc'}
        )
        assert status in (200, 201), payload
        after = snapshot()
        new_ids = set(after) - before
        assert len(new_ids) == 1
        assert after[next(iter(new_ids))] == 'mcp'
        assert origins.current() == 'hand'
