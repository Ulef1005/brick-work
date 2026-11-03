"""The MCP server on API v2 (M.11e, issue #113). Ported from test_bw_api_m7, test_bw_wishlists_api (its MCP half) and test_bw_throttle_mcp.

The tools are generated from `openapi-v2.yaml`; one tool call is one `/api/v2` request. The new premise of 4.0 is decision 7: a tool takes an item
as a number and a provider, never as a Brick Work id; the adapter looks the number up (`GET /lookup`) and passes the id on. Invented data."""
from contextlib import closing
import ast
import json
import re

import anyio
import jsonschema
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
import pytest
from starlette.testclient import TestClient

from brickwork.core import tokens
from brickwork.core.connect import connect
from brickwork.core.mcp import Adapter, contract
from brickwork.core.mcp.client import HTTPClient, InProcessClient
from brickwork.core.mcp.server import http_app, protocol
from tests.api2 import BOOTSTRAP, CONTRACT, call, events, row, rows, stored_token, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401

DEFINITIONS = Adapter(None).tools
READS = [n for n, (m, _, _) in DEFINITIONS.items() if m == 'GET']
WRITES = [n for n, (m, _, _) in DEFINITIONS.items() if m != 'GET']
RED, WHITE = 5, 1                                           # BrickLink colour numbers of the fixture's red and white


@pytest.fixture
def adapter(app4, v2, world):
    return Adapter(InProcessClient(app4, BOOTSTRAP), allow_write=True)


def run_tool(adapter, name, args):
    async def run():
        async with create_connected_server_and_client_session(protocol(lambda: adapter)) as session:
            return await session.call_tool(name, args)
    return anyio.run(run)


def payload(result):
    return json.loads(result.content[0].text)


# ---------- the surface is the contract's ----------

def test_the_tool_surface_is_generated_from_the_v2_contract():
    marked = {op['x-mcp-tool']: (method.upper(), path) for path, methods in CONTRACT['paths'].items()
              for method, op in methods.items() if isinstance(op, dict) and 'x-mcp-tool' in op}
    assert {n: (m, p) for n, (m, p, _) in DEFINITIONS.items()} == marked
    assert len(READS) + len(WRITES) == 65
    for name, (method, path, op) in DEFINITIONS.items():
        assert op['security'] == [{'bearerAuth': ['read' if method == 'GET' else 'write']}], name   # admin work is never a tool
        assert op['summary'], name
    assert len(contract()['x-mcp']['resources']) == 8


def test_no_tool_takes_a_brick_work_item_id():
    adapter = Adapter(None)
    for name, (method, path, op) in DEFINITIONS.items():
        schema = adapter.schema(op)
        text = json.dumps(schema)
        assert 'Brick Work item id' not in text and 'item_id' not in schema['properties'], name
        item = adapter.item_parameter(op)
        if item:
            assert {'provider', 'kind', 'no'} <= set(schema['properties']) and {'kind', 'no'} <= set(schema['required']), name
            assert item['name'] not in schema['properties'] or item['name'] == 'id' and '{id}' in path and path.count('{') > 1, name
        for key, value in schema['properties'].items():
            if key == 'item':                                   # an item in a body: provider, kind and key, no id
                assert set(value['properties']) == {'provider', 'kind', 'key'} and value['required'] == ['kind', 'key'], name
    # the by-id item paths are exactly the marked ones
    assert sorted(n for n, (m, p, op) in DEFINITIONS.items() if Adapter(None).item_parameter(op)) == [
        'get_item', 'get_prices', 'import_item', 'record_price', 'refresh_price', 'set_figure_missing']
    # a tool never shows the id member of an ItemKey, anywhere in its body
    for name in ('add_copies', 'add_stock', 'add_wish', 'take_for_gap'):
        assert 'id' not in adapter.schema(DEFINITIONS[name][2])['properties']['item']['properties']


def test_the_contract_marks_every_item_id_path_parameter():
    """The rule is the contract's, not a list in the adapter: every tool path parameter that is an item id is marked."""
    for name, (method, path, op) in DEFINITIONS.items():
        for p in op.get('parameters', []):
            if p['in'] == 'path' and re.search(r'item id', p.get('description', '')):
                assert p.get('x-mcp-item'), name
    assert CONTRACT['components']['parameters']['Path_figure_item_id']['name'] == 'item_id'
    figure = DEFINITIONS['set_figure_missing'][2]
    assert [p['name'] for p in figure['parameters'] if p['in'] == 'path'] == ['id', 'item_id']


# ---------- numbers, not ids ----------

def test_an_item_is_read_by_its_number_in_either_provider(adapter, world):
    got = adapter.call_tool('get_item', {'kind': 'part', 'no': '3001'})
    assert not got.isError and payload(got)['id'] == world.brick
    assert payload(adapter.call_tool('get_item', {'provider': 'rebrickable', 'kind': 'minifigure', 'no': 'fig-000004'}))['id'] == world.figure
    assert payload(adapter.call_tool('get_item', {'provider': 'bricklink', 'kind': 'minifigure', 'no': 'syn-fig-0004'}))['id'] == world.figure
    assert payload(adapter.call_tool('get_item', {'kind': 'set', 'no': '1000-1'}))['id'] == world.keep
    # bricklink is the default provider: a Rebrickable figure number is not a BrickLink one
    refused = adapter.call_tool('get_item', {'kind': 'minifigure', 'no': 'fig-000004'})
    assert refused.isError and payload(refused)['code'] == 'not_found'


def test_no_and_key_are_described_as_one_number():
    # A path item is `no`, a body item's member is `key` (the API's name); one description says they are the same number.
    adapter = Adapter(None)
    by_no = adapter.schema(DEFINITIONS['get_item'][2])['properties']['no']['description']
    by_key = adapter.schema(DEFINITIONS['add_wish'][2])['properties']['item']['properties']['key']['description']
    assert by_no == by_key and '`key`' in by_no and '`no`' in by_no


def test_a_lookup_refusal_is_the_tools_error_unchanged(adapter, coll):
    missing = adapter.call_tool('get_item', {'kind': 'part', 'no': 'nope'})
    direct = adapter.client.request('GET', '/lookup', query={'provider': 'bricklink', 'kind': 'part', 'key': 'nope'})
    assert missing.isError and payload(missing) == direct[1] and direct[0] == 404
    one, two = coll.item('parts', '3001'), coll.item('parts', '3023')
    coll.link(one, 'twin', kind='P')
    coll.link(two, 'twin', kind='P')
    ambiguous = adapter.call_tool('get_item', {'kind': 'part', 'no': 'twin'})
    assert ambiguous.isError and payload(ambiguous)['code'] == 'ambiguous'
    assert sorted(c['id'] for c in payload(ambiguous)['candidates']) == sorted([one, two])
    assert payload(ambiguous) == adapter.client.request('GET', '/lookup', query={'provider': 'bricklink', 'kind': 'part', 'key': 'twin'})[1]
    # a write whose item is ambiguous writes nothing and asks for no second call
    refused = adapter.call_tool('record_price', {'kind': 'part', 'no': 'twin', 'condition': 'used', 'guide': 'manual', 'price': '1', 'currency': 'EUR'})
    assert refused.isError and payload(refused)['code'] == 'ambiguous'


def test_the_number_is_resolved_before_the_call_and_the_id_goes_in_the_path(adapter, world):
    seen = []
    real = adapter.client.request
    adapter.client.request = lambda method, path, **kwargs: (seen.append((method, path, kwargs.get('query'))), real(method, path, **kwargs))[1]
    adapter.call_tool('get_prices', {'kind': 'part', 'no': '3001', 'color': RED})
    assert seen == [('GET', '/lookup', {'provider': 'bricklink', 'kind': 'part', 'key': '3001', 'color': RED}),
                    ('GET', f'/items/{world.brick}/prices', {'color': RED})]


def test_a_colour_scoped_number_resolves_with_the_tools_colour(adapter, coll):
    # BrickLink links can be colour-scoped (one number, a different item per colour), so the tool's colour takes part in the lookup.
    one, two = coll.item('parts', '3001'), coll.item('parts', '3023')
    coll.link(one, 'legs', colour=coll.colour(4))                  # Rebrickable red is BrickLink red (RED)
    coll.link(two, 'legs', colour=coll.colour(15))                 # Rebrickable white is BrickLink white (WHITE)
    assert payload(adapter.call_tool('get_prices', {'kind': 'part', 'no': 'legs'}))['code'] == 'ambiguous'
    seen = []
    real = adapter.client.request
    adapter.client.request = lambda method, path, **kwargs: (seen.append((method, path)), real(method, path, **kwargs))[1]
    red = adapter.call_tool('get_prices', {'kind': 'part', 'no': 'legs', 'color': RED})
    assert not red.isError, payload(red)
    assert seen == [('GET', '/lookup'), ('GET', f'/items/{one}/prices')]


def test_record_price_takes_the_providers_colour_and_stores_the_brick_work_one(adapter, world, coll, pair):
    # Decision 7: no tool takes a Brick Work id, colours included. The tool's colour is BrickLink's (the provider's); the lookup maps it.
    made = adapter.call_tool('record_price', {'kind': 'part', 'no': '3001', 'color': RED, 'condition': 'used', 'guide': 'manual',
                                              'price': '0.25', 'currency': 'EUR'})
    assert not made.isError, payload(made)
    stored = row(pair, "SELECT color_id FROM price_observation WHERE item_id=? AND guide='manual' ORDER BY id DESC", (world.brick,))
    assert stored['color_id'] == coll.colour(4)


def test_a_redirect_is_the_tools_error_not_an_empty_success(adapter, world):
    # The MCP clients never follow a redirect; a merged item's 307 between the lookup and the read is reported, not swallowed.
    moved = {'code': 'moved', 'status': 307, 'survivor': world.brick, 'detail': 'merged'}
    real = adapter.client.request
    adapter.client.request = lambda method, path, **kwargs: (307, moved) if path.startswith('/items/') else real(method, path, **kwargs)
    result = adapter.call_tool('get_prices', {'kind': 'part', 'no': '3001'})
    assert result.isError and payload(result) == moved


def test_prices_are_read_recorded_and_refreshed_by_number(adapter, world, pair):
    seen = adapter.call_tool('get_prices', {'kind': 'set', 'no': '1000-1'})
    assert not seen.isError and [r['observation']['price'] for r in payload(seen)['current']] == ['30.00']
    made = adapter.call_tool('record_price', {'kind': 'set', 'no': '1000-1', 'condition': 'new', 'guide': 'manual', 'price': '41.50', 'currency': 'EUR'})
    assert not made.isError, payload(made)
    assert row(pair, "SELECT price FROM price_observation WHERE item_id=? AND guide='manual'", (world.keep,))['price'] in ('41.50', 41.5)
    assert '41.50' in [r['price'] for r in payload(adapter.call_tool('get_prices', {'kind': 'set', 'no': '1000-1'}))['records']]
    assert events(pair, 'id=?', (payload(made)['event_id'],))[0]['via'] == 'api'
    # the provider also names the colour space of a price read (decision 4)
    rebrickable = adapter.call_tool('get_prices', {'provider': 'rebrickable', 'kind': 'part', 'no': '3001', 'color': 4})
    bricklink = adapter.call_tool('get_prices', {'kind': 'part', 'no': '3001', 'color': RED})
    assert not rebrickable.isError and payload(rebrickable) == payload(bricklink)


def test_a_figure_of_a_copy_is_marked_by_its_number(adapter, world, pair):
    done = adapter.call_tool('set_figure_missing', {'id': world.copy_a, 'provider': 'rebrickable', 'kind': 'minifigure', 'no': 'fig-000004', 'missing': 1})
    assert not done.isError, payload(done)
    assert row(pair, 'SELECT missing FROM copy_figure WHERE copy_id=? AND item_id=?', (world.copy_a, world.figure))['missing'] == 1
    absent = adapter.call_tool('set_figure_missing', {'id': world.copy_a, 'kind': 'minifigure', 'no': 'nope', 'missing': 0})
    assert absent.isError and payload(absent)['code'] == 'not_found'


def test_items_in_a_body_go_by_number_and_never_by_id(adapter, world, pair):
    with pytest.raises(jsonschema.ValidationError):             # the schema has no id: the tool refuses before any request
        adapter.call_tool('add_copies', {'item': {'id': world.duplo}})
    assert run_tool(adapter, 'add_copies', {'item': {'id': world.duplo}}).isError
    made = adapter.call_tool('add_copies', {'item': {'kind': 'set', 'key': '1000-2'}, 'quantity': 1, 'decision': 'another'})
    assert not made.isError, payload(made)
    assert row(pair, 'SELECT item_id FROM copy WHERE id=?', (payload(made)['data']['ids'][0],))['item_id'] == world.gate
    stock = adapter.call_tool('add_stock', {'item': {'provider': 'rebrickable', 'kind': 'part', 'key': '3023'}, 'color': 4, 'quantity': 2})
    assert not stock.isError, payload(stock)
    wish = adapter.call_tool('add_wish', {'item': {'kind': 'set', 'key': '2070-1'}, 'quantity': 1, 'decision': 'another'})
    assert not wish.isError, payload(wish)
    take = adapter.call_tool('take_for_gap', {'id': world.copy_a, 'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 1})
    assert not take.isError, payload(take)
    unknown = adapter.call_tool('add_wish', {'item': {'kind': 'set', 'key': '99999-1'}, 'quantity': 1})
    assert unknown.isError and payload(unknown)['code'] == 'unidentified'


def test_collection_records_keep_their_ids(adapter, world):
    assert payload(adapter.call_tool('get_copy', {'id': world.copy_a}))['id'] == world.copy_a
    got = adapter.call_tool('update_copy', {'id': world.copy_a, 'fields': {'note': 'Synthetic note'}})
    assert not got.isError and payload(got)['data']['note'] == 'Synthetic note'
    listed = payload(adapter.call_tool('list_copies', {'number': '1000-1'}))
    assert {c['id'] for c in listed['data']} == {world.copy_a, world.copy_b}               # the list tools filter by number and provider
    assert payload(adapter.call_tool('lookup_item', {'kind': 'set', 'key': '1000-1'}))['id'] == world.keep
    assert payload(adapter.call_tool('get_set_by_number', {'no': '1000-1'}))['id'] == world.keep


# ---------- the gate ----------

@pytest.mark.parametrize('scope', ['read', 'write', 'admin'])
@pytest.mark.parametrize('flag', [False, True])
def test_gate_and_direct_call(app4, v2, pair, world, scope, flag):
    adapter = Adapter(InProcessClient(app4, stored_token(pair, [scope], 'gate-' + scope)), allow_write=flag)
    assert {t.name for t in adapter.list_tools()} == set(READS + (WRITES if flag and scope != 'read' else []))
    if not flag or scope == 'read':
        result = run_tool(adapter, 'create_storage', {'name': 'Synthetic'})
        assert result.isError and payload(result)['code'] == 'forbidden'
        assert all(s['name'] != 'Synthetic' for s in call(v2, '/storages').json['data'])


def test_revocation_and_read_only(app4, v2, pair, world, monkeypatch):
    with closing(connect(pair)) as db:
        made, _ = tokens.create(db, 'revocable', ['write'])
    adapter = Adapter(InProcessClient(app4, made['secret']), allow_write=True)
    assert 'create_storage' in {t.name for t in adapter.list_tools()}
    monkeypatch.setenv('BW_READ_ONLY', '1')
    assert payload(run_tool(adapter, 'create_storage', {'name': 'Synthetic'}))['code'] == 'read_only_instance'
    monkeypatch.delenv('BW_READ_ONLY')
    assert call(v2, '/tokens/' + made['token']['id'], 'delete').status_code in (200, 204)
    assert {t.name for t in adapter.list_tools()} == set(READS)
    assert payload(run_tool(adapter, 'create_storage', {'name': 'Synthetic'}))['code'] == 'forbidden'


# ---------- every tool reaches its operation ----------

def read_arguments(w, pair):
    rebrickable = {'source': 'rebrickable'}
    return {
        'get_wishlists': {}, 'export_wishlist_xml': {'id': 'default'}, 'export_wishlist_csv': {'id': 'default'}, 'search_catalogue': {'q': '1000'},
        'get_item': {'kind': 'set', 'no': '1000-1'}, 'list_copies': {}, 'get_copy': {'id': w.copy_a}, 'get_copy_completeness': {'id': w.copy_a},
        'list_copy_parts': {'id': w.copy_a}, 'list_copy_figures': {'id': w.copy_a}, 'list_stock': {}, 'list_minifigures': {}, 'list_gaps': {},
        'list_matches': {}, 'list_instruction_files': {}, 'get_prices': {'kind': 'set', 'no': '1000-1'}, 'list_stale_prices': {}, 'list_wishes': {},
        'list_storages': {}, 'list_lots': {}, 'list_places': {}, 'list_flags': {}, 'get_planning_ranking': {}, 'list_orders': {},
        'get_order': {'id': 99999}, 'list_events': {}, 'list_jobs': {}, 'get_sources': {}, 'get_sync_status': rebrickable, 'get_settings': {},
        'get_statistics': {}, 'get_set_by_number': {'no': '1000-1'}, 'get_part_by_number': {'no': '3001'},
        'get_minifigure_by_number': {'no': 'syn-fig-0004'}, 'lookup_item': {'kind': 'set', 'key': '1000-1'}}


def test_every_read_tool_has_a_round_trip_case(world, pair):
    assert set(read_arguments(world, pair)) == set(READS)


@pytest.mark.parametrize('name', READS)
def test_every_read_round_trip(adapter, world, pair, name):
    result = run_tool(adapter, name, read_arguments(world, pair)[name])
    if name == 'get_order':
        assert result.isError and payload(result)['code'] == 'not_found'              # no order in the fixture: the API's own answer
    else:
        assert not result.isError, payload(result)
    assert result.content


def write_arguments(w, pair, v2):
    brick = row(pair, 'SELECT id FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL LIMIT 1', (w.copy_a,))['id']
    extra = write(v2, '/wishlists', body={'name': 'Extra'}).json['data']['id']
    gone = write(v2, '/wishlists', body={'name': 'Gone'}).json['data']['id']
    write(v2, f'/wishlists/{gone}', 'delete')
    return {
        'post_wishlists': {'name': 'Synthetic wishlist'}, 'patch_wishlists_id': {'id': extra, 'name': 'Synthetic renamed'},
        'delete_wishlists_id': {'id': extra}, 'post_wishlists_id_restore': {'id': gone},
        'post_wishlists_id_transfer': {'id': extra, 'ids': [w.wish_part]},
        'import_item': {'kind': 'part', 'no': '3001'},
        'add_copies': {'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another'},
        'update_copy': {'id': w.copy_a, 'fields': {'note': 'Synthetic note'}}, 'archive_copy': {'id': w.copy_b},
        'set_copy_checked': {'id': w.copy_c, 'checked': True},
        'take_for_gap': {'id': w.copy_a, 'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 1},
        'set_part_missing': {'id': w.copy_a, 'part_id': brick, 'missing': 0, 'damaged': 1},
        'set_figure_missing': {'id': w.copy_a, 'provider': 'rebrickable', 'kind': 'minifigure', 'no': 'fig-000004', 'missing': 1},
        'add_stock': {'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 1},
        'update_stock': {'id': w.stock_brick, 'fields': {'note': 'Synthetic note'}},
        'give_from_stock': {'id': w.stock_brick, 'copy_id': w.copy_a, 'target': 'part', 'target_id': brick, 'quantity': 1},
        'record_price': {'kind': 'set', 'no': '1000-1', 'condition': 'used', 'guide': 'manual', 'price': '12', 'currency': 'EUR'},
        'refresh_price': {'kind': 'set', 'no': '1000-1'},
        'add_wish': {'item': {'kind': 'set', 'key': '2070-1'}, 'quantity': 1, 'decision': 'another'},
        'update_wish': {'id': w.wish_part, 'fields': {'note': 'Synthetic note'}}, 'archive_wish': {'id': w.wish_set},
        'wish_to_owned': {'id': w.wish_part, 'quantity': 1}, 'create_storage': {'name': 'Synthetic new storage'},
        'move_to_storage': {'id': w.shelf, 'selections': [{'entity': 'copy', 'id': w.copy_b}]},
        'plan_sync_pull': {'source': 'rebrickable'}, 'apply_sync_pull': {'source': 'rebrickable', 'plan_id': 'absent'},
        'plan_sync_send': {'source': 'rebrickable'},
        'import_order': {'source': 'xml', 'text': '<INVENTORY><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>1000-1</ITEMID><QTY>1</QTY><CONDITION>U</CONDITION></ITEM></INVENTORY>'},
        'undo_event': {'id': 1}, 'retry_job': {'id': 99999},
    }


# What the API itself answers for the writes whose set-up is another module's business (a connected source, a failed job, an event with no Undo):
# a problem with its own code, never a gate, a placeholder or a crash. The writes are tested for real in tests/test_api2_write_*.py.
API_REFUSALS = {'plan_sync_pull': 'source_not_configured', 'plan_sync_send': 'source_not_configured', 'apply_sync_pull': 'validation_failed',
                'retry_job': 'not_found', 'undo_event': 'not_undoable'}


def test_every_write_tool_has_a_round_trip_case(world, pair, v2):
    assert set(write_arguments(world, pair, v2)) == set(WRITES)


@pytest.mark.parametrize('name', WRITES)
def test_every_write_round_trip(adapter, v2, world, pair, name):
    args = write_arguments(world, pair, v2)[name]
    result = run_tool(adapter, name, args)
    value = payload(result)
    if result.isError:
        assert API_REFUSALS.get(name) == value['code'], value
    else:
        assert 'event_id' in value and 'undo_url' in value, value


def test_replay_etag_validation_errors_and_pages(adapter, world):
    args = {'name': 'Synthetic replay', 'idempotency_key': 'synthetic-stable-key'}
    first = payload(run_tool(adapter, 'create_storage', args))
    second = payload(run_tool(adapter, 'create_storage', args))
    assert first['event_id'] == second['event_id'] and second['idempotent_replay']
    assert payload(run_tool(adapter, 'update_copy', {'id': world.copy_a, 'fields': {'note': 'Synthetic'}, 'if_match': '"stale"'}))['code'] == 'precondition_failed'
    assert run_tool(adapter, 'update_copy', {'id': world.copy_a, 'fields': {'condition': 'invalid'}}).isError
    assert payload(run_tool(adapter, 'get_copy', {'id': 'absent'}))['code'] == 'not_found'
    assert 'page' in payload(run_tool(adapter, 'list_copies', {'limit': 1}))


def test_a_write_through_a_tool_is_audited_as_the_token_and_replays(adapter, world, pair):
    args = {'kind': 'set', 'no': '1000-1', 'condition': 'used', 'guide': 'manual', 'price': '17', 'currency': 'EUR', 'idempotency_key': 'synthetic-price'}
    made, replay = payload(run_tool(adapter, 'record_price', args)), payload(run_tool(adapter, 'record_price', args))
    assert replay['idempotent_replay'] and replay['event_id'] == made['event_id']
    event = events(pair, 'id=?', (made['event_id'],))[0]
    assert (event['via'], event['actor']) == ('api', 'bootstrap')
    assert payload(run_tool(adapter, 'undo_event', {'id': made['event_id']}))['data']['already_undone'] is False


# ---------- the wishlist tools and exports (from test_bw_wishlists_api) ----------

def test_the_wishlist_tools_create_and_export(adapter, world, pair):
    names = {t.name for t in adapter.list_tools()}
    assert {'get_wishlists', 'post_wishlists', 'patch_wishlists_id', 'post_wishlists_id_transfer', 'export_wishlist_xml', 'export_wishlist_csv'} <= names
    target = payload(adapter.call_tool('post_wishlists', {'name': 'New'}))['data']['id']
    created = adapter.call_tool('add_wish', {'item': {'kind': 'set', 'key': '1000-1'}, 'list_id': target, 'condition': 'any', 'decision': 'another'})
    assert not created.isError, payload(created)
    wish = payload(adapter.call_tool('list_wishes', {'list': target}))['data'][0]
    assert wish['list_id'] == target and wish['condition'] == 'any'
    output = adapter.call_tool('export_wishlist_xml', {'id': target, 'summary': True})
    assert not output.isError and output.structuredContent['summary']['exported'] == 1
    assert not adapter.call_tool('post_wishlists', {'name': 'MCP'}).isError


# ---------- resources ----------

def test_every_resource_resolves(adapter, world):
    resources = contract()['x-mcp']['resources']
    operations = {op['operationId'] for methods in CONTRACT['paths'].values() for op in methods.values() if isinstance(op, dict)}
    for template, target in resources.items():
        assert (target if isinstance(target, str) else target['operation']) in operations, template

    async def run():
        async with create_connected_server_and_client_session(protocol(lambda: adapter)) as session:
            assert len((await session.list_resources()).resources) == 6
            assert len((await session.list_resource_templates()).resourceTemplates) == 2
            for template in resources:
                uri = (template.replace('{id}', world.copy_a).replace('{provider}', 'bricklink').replace('{kind}', 'set').replace('{no}', '1000-1'))
                result = await session.read_resource(uri)
                assert result.contents[0].text, template
    anyio.run(run)


def test_the_item_resource_is_a_lookup_by_number(adapter, world):
    assert json.loads(adapter.read_resource('brickwork://items/bricklink/part/3001'))['data']['id'] == world.brick
    assert json.loads(adapter.read_resource('brickwork://items/rebrickable/minifigure/fig-000004'))['data']['id'] == world.figure
    assert 'openapi: 3.1' in adapter.read_resource('brickwork://openapi')
    with pytest.raises(McpError, match=r'not_found.*404'):
        adapter.read_resource('brickwork://items/bricklink/part/nope')


def test_a_missing_copy_resource_is_an_mcp_error(adapter):
    with pytest.raises(McpError, match=r'not_found.*404'):
        adapter.read_resource('brickwork://copies/missing')

    async def run():
        async with create_connected_server_and_client_session(protocol(lambda: adapter)) as session:
            with pytest.raises(McpError, match=r'not_found.*404'):
                await session.read_resource('brickwork://copies/missing')
    anyio.run(run)


# ---------- transports ----------

def test_http_transport_and_token_isolation(app4, v2, pair, world):
    read = stored_token(pair, ['read'], 'http-reader')
    with TestClient(http_app(app4, allow_write=True)) as client:
        assert client.get('/api/v1/health').status_code == 200

        def rpc(token, method, params=None):
            return client.post('/mcp', headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream'},
                               json={'jsonrpc': '2.0', 'id': 1, 'method': method, **({'params': params} if params is not None else {})})
        assert rpc('invalid', 'tools/list').status_code == 401
        init = rpc(BOOTSTRAP, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'synthetic', 'version': '1'}})
        assert init.status_code == 200, init.text
        assert len(rpc(BOOTSTRAP, 'tools/list').json()['result']['tools']) == len(READS) + len(WRITES)
        assert len(rpc(read, 'tools/list').json()['result']['tools']) == len(READS)
        denied = rpc(read, 'tools/call', {'name': 'create_storage', 'arguments': {'name': 'Synthetic'}})
        assert denied.json()['result']['isError']
        made = rpc(BOOTSTRAP, 'tools/call', {'name': 'create_storage', 'arguments': {'name': 'Synthetic'}})
        assert not made.json()['result']['isError'], made.text
        assert 'Synthetic' in rpc(read, 'tools/call', {'name': 'list_storages', 'arguments': {}}).text
        by_number = rpc(read, 'tools/call', {'name': 'get_item', 'arguments': {'kind': 'set', 'no': '1000-1'}})
        assert not by_number.json()['result']['isError'] and world.keep == json.loads(by_number.json()['result']['content'][0]['text'])['id']
    with TestClient(http_app(app4)) as client:
        result = client.post('/mcp', headers={'Authorization': 'Bearer ' + BOOTSTRAP, 'Accept': 'application/json, text/event-stream'},
                             json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        assert len(result.json()['result']['tools']) == len(READS)


def test_no_domain_imports():
    forbidden = {'collection', 'add', 'workbench', 'checker', 'orders'}
    from pathlib import Path
    for path in Path(__file__).resolve().parents[1].joinpath('brickwork/core/mcp').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, 'module', '') or '']
                assert not any(set(n.split('.')) & forbidden for n in names)


def test_the_clients_speak_v2(app4, v2, world, monkeypatch):
    import requests
    assert InProcessClient(app4, BOOTSTRAP).request('GET', '/me')[0] == 200
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"data": {"name": "Synthetic"}}'
        return response
    monkeypatch.setattr(requests, 'request', request)
    result = HTTPClient('http://127.0.0.1:5000/api/v2', BOOTSTRAP).request('GET', '/me')
    assert result[1]['data']['name'] == 'Synthetic'
    assert calls[0][1] == 'http://127.0.0.1:5000/api/v2/me' and calls[0][2]['allow_redirects'] is False
    assert calls[0][2]['headers']['Authorization'] == 'Bearer ' + BOOTSTRAP
    from brickwork.core.mcp import server
    assert server.run.__kwdefaults__['api_url'] == 'http://127.0.0.1:5000/api/v2'


def test_the_in_process_client_carries_the_caller_address(app4, v2, monkeypatch):
    """#48, from test_bw_throttle.py: each MCP client counts on its own in the token back-off."""
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '2')
    for _ in range(2):
        InProcessClient(app4, 'wrong', remote_addr='10.9.2.1').request('GET', '/me')
    assert InProcessClient(app4, BOOTSTRAP, remote_addr='10.9.2.1').request('GET', '/me')[0] == 429
    assert InProcessClient(app4, BOOTSTRAP, remote_addr='10.9.2.2').request('GET', '/me')[0] == 200


def test_stdio_offline_token_file(app4, v2, pair, world, tmp_path, monkeypatch):
    import os
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    path = tmp_path / 'synthetic-token'
    path.write_text(stored_token(pair, ['write'], 'stdio-writer'))
    # The child also blocks sockets, so this exercises the standalone path offline.
    code = "import socket; socket.socket.connect=lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network disabled')); from brickwork.web.cli import main; main()"
    params = StdioServerParameters(command=sys.executable, env=dict(os.environ, BW_DB_PATH=str(pair), BW_EMBEDDED_WORKER='0'),
                                   args=['-c', code, 'mcp', '--in-process', '--allow-write', '--token-file', str(path)])

    async def run():
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                assert len((await session.list_tools()).tools) == len(READS) + len(WRITES)
                made = await session.call_tool('create_storage', {'name': 'Synthetic stdio'})
                assert not made.isError
                assert payload(made)['event_id']
                found = await session.call_tool('get_item', {'kind': 'set', 'no': '1000-1'})
                assert not found.isError and payload(found)['id'] == world.keep
    anyio.run(run)
    assert any(s['name'] == 'Synthetic stdio' for s in call(v2, '/storages').json['data'])


def test_cli_flags_and_environment(app4, v2, pair, monkeypatch, tmp_path):
    from brickwork.web.cli import build_parser, main
    from brickwork.core.mcp import server
    assert build_parser().parse_args(['mcp']).api_url == 'http://127.0.0.1:5000/api/v2'
    received = []
    received_run = server.run
    monkeypatch.setattr(server, 'run', lambda **kwargs: received.append(kwargs))
    assert main(['mcp', '--in-process', '--allow-write', '--token-file', 'synthetic-token']) == 0
    assert received[0]['in_process'] and received[0]['allow_write'] and received[0]['token_file'] == 'synthetic-token'
    captured = []
    monkeypatch.setattr(server.anyio, 'run', lambda func, adapter: captured.append(adapter))
    monkeypatch.setenv('BW_MCP_WRITE', '1')
    token_file = tmp_path / 'synthetic-read-token'
    token_file.write_text(stored_token(pair, ['read'], 'cli-reader'))
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
