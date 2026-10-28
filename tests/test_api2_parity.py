"""The v2 contract, the routes and the MCP agree (M.11e, issue #113). Ported from test_bw_api_parity (every operation has a route and every route is
in the contract) and the file-level tests of test_bw_api_m1_contract (the strict YAML loader, the closed response schemas); the per-operation
response checks of that file generated tests from the v1 M1 table, and `tests/api2.validate` has checked every v2 answer against the contract
since M.11b. Moved here from M.9: the parity test of the v2 surface."""
import copy
import re

import jsonschema
import pytest
import yaml

from brickwork import api2
from brickwork.core.mcp import Adapter, contract
from brickwork.core.mcp.client import InProcessClient
from scripts import check_api_contract
from scripts.check_api_contract import load_yaml, v2_routes
from tests.api2 import BOOTSTRAP, CONTRACT, _closed, v2  # noqa: F401
from tests.api2 import app4, coll, pair  # noqa: F401

OPERATIONS = {(method.upper(), path): op for path, methods in CONTRACT['paths'].items() for method, op in methods.items() if isinstance(op, dict)}


# ---------- every operation is implemented, and the routes are the contract's ----------

def test_every_operation_has_a_route_and_every_route_is_in_the_contract():
    routes = v2_routes()
    assert sorted(set(OPERATIONS) - set(routes)) == [], 'in the contract without a route'
    assert sorted(set(routes) - set(OPERATIONS)) == [], 'routed but not in the contract'
    assert len(OPERATIONS) == 188


def test_no_operation_answers_501():
    routes = v2_routes()
    placeholders = sorted(key for key, (_, view) in routes.items() if getattr(view, 'piece', None))
    assert placeholders == []
    assert api2.pending(api2.operations()) == []
    assert {op['x-piece'] for op in OPERATIONS.values()} <= set(api2.DONE)
    # the route's view is the contract's operation: the endpoint is the operationId
    for key, (endpoint, _) in routes.items():
        assert endpoint.split('.', 1)[1] == OPERATIONS[key]['operationId'], key


# ---------- the MCP is the contract's ----------

def tools_of_contract():
    return {op['x-mcp-tool']: key for key, op in OPERATIONS.items() if 'x-mcp-tool' in op}


def test_every_tool_maps_to_one_operation_and_the_names_are_unique():
    names = [op['x-mcp-tool'] for op in OPERATIONS.values() if 'x-mcp-tool' in op]
    assert len(names) == len(set(names)) == 65
    assert re.fullmatch(r'[a-z][a-z0-9_]*', ''.join(sorted(set(names))).replace('_', ''))
    adapter = Adapter(None)
    assert {name: (method, path) for name, (method, path, _) in adapter.tools.items()} == {n: (m, p) for n, (m, p) in tools_of_contract().items()}
    for name, (method, path, op) in adapter.tools.items():
        assert OPERATIONS[(method, path)]['operationId'] == op['operationId'], name
        assert (method, path) in v2_routes(), name


def test_the_tool_list_of_a_server_is_the_contracts_tool_set(app4, v2):
    everything = Adapter(InProcessClient(app4, BOOTSTRAP), allow_write=True).list_tools()
    assert sorted(t.name for t in everything) == sorted(tools_of_contract())
    reads = Adapter(InProcessClient(app4, BOOTSTRAP), allow_write=False).list_tools()
    assert sorted(t.name for t in reads) == sorted(n for n, (method, _) in tools_of_contract().items() if method == 'GET')
    for tool in everything:
        jsonschema.Draft202012Validator.check_schema(tool.inputSchema)
        assert tool.description and tool.annotations.readOnlyHint == (tools_of_contract()[tool.name][0] == 'GET')


def test_every_resource_template_names_an_operation_and_uses_its_variables():
    resources = contract()['x-mcp']['resources']
    ids = {op['operationId']: op for op in OPERATIONS.values()}
    for template, target in resources.items():
        operation, query = (target, {}) if isinstance(target, str) else (target['operation'], target.get('query', {}))
        assert operation in ids and ids[operation]['security'] in ([], [{'bearerAuth': ['read']}]), template      # a resource only reads
        variables = set(re.findall(r'\{([^}]+)\}', template))
        path = next(p for (m, p), op in OPERATIONS.items() if op['operationId'] == operation)
        used = set(re.findall(r'\{([^}]+)\}', path)) | {v for text in query.values() for v in re.findall(r'\{([^}]+)\}', text)}
        assert variables == used, template                      # every variable of the URI goes somewhere, and nothing is left unfilled
    assert resources['brickwork://items/{provider}/{kind}/{no}']['operation'] == 'get_lookup'


# ---------- the contract file ----------

@pytest.mark.parametrize('text', [
    'openapi: 3.1.0\nopenapi: 3.0.0\n',
    'paths:\n  /tokens:\n    post:\n      responses:\n        "401": {}\n        "401": {}\n',
])
def test_contract_rejects_duplicate_keys(text):
    with pytest.raises(yaml.constructor.ConstructorError, match='duplicate key'):
        load_yaml(text)


def test_contract_checker_rejects_duplicate_keys(tmp_path, monkeypatch, capsys):
    contract_file = tmp_path / 'docs/brickwork/openapi-v2.yaml'
    contract_file.parent.mkdir(parents=True)
    contract_file.write_text('paths: {}\npaths: {}\n')
    monkeypatch.setattr(check_api_contract, 'ROOT', tmp_path)
    assert check_api_contract.check_v2(False) == 1
    assert 'duplicate key' in capsys.readouterr().err


def test_the_closed_schemas_close_nested_refs_nullable_and_inline_objects():
    schema = {'type': 'object', 'properties': {
        'nested': {'type': ['object', 'null'], 'properties': {'known': {'type': 'string'}}},
        'free': {'type': 'object', 'additionalProperties': True},
        'rows': {'type': 'array', 'items': {'$ref': '#/components/schemas/Row'}}}}
    spec = {'paths': {'/example': {'get': {'responses': {'200': {'content': {'application/json': {'schema': schema}}}}}}},
            'components': {'schemas': {'Row': {'type': 'object', 'properties': {'id': {'type': 'integer'}}}}}}
    closed = _closed(copy.deepcopy(spec))
    response = closed['paths']['/example']['get']['responses']['200']['content']['application/json']['schema']
    validator = jsonschema.Draft202012Validator({**response, 'components': closed['components']})
    validator.validate({'nested': {'known': 'yes'}, 'free': {'arbitrary': 1}, 'rows': [{'id': 1}]})
    for invalid in ({'extra': True}, {'nested': {'extra': True}}, {'rows': [{'extra': True}]}):
        with pytest.raises(jsonschema.ValidationError, match='Additional properties'):
            validator.validate(invalid)
    assert 'additionalProperties' not in schema                 # the served contract is unchanged
