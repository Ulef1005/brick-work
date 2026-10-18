"""Generate request/response and reachable-status checks from implemented YAML ops.

Install requirements-dev.txt to enable this harness. Dependency absence is reported
as an explicit skip so unrelated offline tests remain runnable.
"""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import re
import sqlite3

import pytest

yaml = pytest.importorskip('yaml', reason='M1 contract validation needs PyYAML (requirements-dev.txt)')
jsonschema = pytest.importorskip('jsonschema', reason='M1 contract validation needs jsonschema (requirements-dev.txt)')

from tests.test_bw_api_m1 import app, call, create
from brickwork.core.connect import connect
from brickwork.core import errors
from scripts.check_api_contract import load_yaml

CONTRACT = load_yaml(Path('docs/brickwork/openapi-v1.yaml').read_text())
OPERATIONS = [(path, method, op) for path, methods in CONTRACT['paths'].items()
              for method, op in methods.items() if isinstance(op, dict) and op.get('x-milestone') == 'M1']
CASES = [(path, method, op, status) for path, method, op in OPERATIONS
         for status in op['responses'] if status != 'default']


@pytest.mark.parametrize('text', [
    'openapi: 3.1.0\nopenapi: 3.0.0\n',
    'paths:\n  /tokens:\n    post:\n      responses:\n        "401": {}\n        "401": {}\n',
])
def test_contract_rejects_duplicate_keys(text):
    with pytest.raises(yaml.constructor.ConstructorError, match='duplicate key'):
        load_yaml(text)


def test_contract_checker_rejects_duplicate_keys(tmp_path, monkeypatch, capsys):
    from scripts import check_api_contract
    contract = tmp_path / 'docs/brickwork/openapi-v1.yaml'
    contract.parent.mkdir(parents=True)
    contract.write_text('paths: {}\npaths: {}\n')
    monkeypatch.setattr(check_api_contract, 'ROOT', tmp_path)
    assert check_api_contract.main() == 1
    assert 'duplicate key' in capsys.readouterr().err


def test_contract_error_codes():
    assert CONTRACT['x-error-status'] == errors.HTTP_STATUS
    assert set(CONTRACT['components']['schemas']['Problem']['properties']['code']['enum']) == set(errors.HTTP_STATUS)


def resolve(value):
    while '$ref' in value:
        target = CONTRACT
        for piece in value['$ref'][2:].split('/'):
            target = target[piece]
        value = target
    return value


def strict_responses(contract):
    """Close every reachable response object; explicit free maps stay open."""
    contract = deepcopy(contract)
    seen = set()
    def visit(schema):
        if not isinstance(schema, dict):
            return
        if '$ref' in schema:
            ref = schema['$ref']
            if ref in seen:
                return
            seen.add(ref)
            target = contract
            for piece in ref[2:].split('/'):
                target = target[piece]
            visit(target)
        if 'object' in schema.get('type', []) or 'properties' in schema:
            schema.setdefault('additionalProperties', False)
        for key in ('properties', '$defs'):
            for child in schema.get(key, {}).values():
                visit(child)
        visit(schema.get('items'))
        visit(schema.get('additionalProperties'))
        for key in ('allOf', 'anyOf', 'oneOf'):
            for child in schema.get(key, []):
                visit(child)
    for methods in contract['paths'].values():
        for op in methods.values():
            if isinstance(op, dict) and op.get('x-milestone') in ('M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7'):
                for response in op['responses'].values():
                    visit(response)
                    if '$ref' in response:
                        response = contract['components']['responses'][response['$ref'].split('/')[-1]]
                    for media in response.get('content', {}).values():
                        visit(media['schema'])
    return contract


STRICT_CONTRACT = strict_responses(CONTRACT)
RESPONSE_SCHEMAS = {}
for path, methods in CONTRACT['paths'].items():
    for method, operation in methods.items():
        if not isinstance(operation, dict) or operation.get('x-milestone') not in ('M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7'):
            continue
        for status, response in operation['responses'].items():
            original = resolve(response)
            strict = STRICT_CONTRACT['paths'][path][method]['responses'][status]
            if '$ref' in strict:
                strict = STRICT_CONTRACT['components']['responses'][strict['$ref'].split('/')[-1]]
            for media, definition in original.get('content', {}).items():
                RESPONSE_SCHEMAS[id(definition['schema'])] = strict['content'][media]['schema']


def validate(value, schema):
    # Resolve against the closed copy without changing the served YAML contract.
    validator = jsonschema.Draft202012Validator(
        {**RESPONSE_SCHEMAS.get(id(schema), schema), 'components': STRICT_CONTRACT['components']},
        format_checker=jsonschema.FormatChecker())
    issues = list(validator.iter_errors(value))
    assert not issues, '\n'.join(f"{list(e.absolute_path)}: {e.message}" for e in issues)


def test_route_manifest(app):
    expected = {(path, method.upper(), op['operationId']) for path, methods in CONTRACT['paths'].items() for method, op in methods.items() if isinstance(op, dict) and op.get('x-milestone') in ('M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7')}
    actual = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith('brickwork_api.'):
            path = re.sub(r'<(?:int:)?([^>]+)>', r'{\1}', rule.rule.removeprefix('/api/v1'))
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                actual.add((path, method, rule.endpoint.split('.', 1)[1]))
    assert actual == expected


@pytest.mark.parametrize('path,method,operation,status', CASES,
                         ids=[op['operationId'] + ':' + status for _, _, op, status in CASES])
def test_generated_contract(app, monkeypatch, tmp_path, path, method, operation, status):
    requested_status = int(status)
    headers = {'Authorization': 'Bearer synthetic-bootstrap'}
    body = None
    if method == 'post' and path == '/tokens':
        body = {'name': 'synthetic-contract', 'scopes': ['read']}
    if '{id}' in path:
        created = create(app).json
        identifier = created['data']['token']['id'] if method == 'delete' else str(created['event_id'])
        path = path.replace('{id}', identifier)
    if path.endswith('/undo'):
        headers['Idempotency-Key'] = 'synthetic-contract-undo'
    if 200 <= requested_status < 300 and body is not None:
        validate(body, operation['requestBody']['content']['application/json']['schema'])
    if requested_status == 400:
        if method == 'get': path += '?limit=invalid'
        elif path.endswith('/undo'): headers['Idempotency-Key'] = 'invalid key'
        else: body = []
    elif requested_status == 401:
        headers = {}
    elif requested_status == 403:
        if method != 'get': monkeypatch.setenv('BW_READ_ONLY', 'true')
        else:
            secret = create(app).json['data']['secret']
            headers['Authorization'] = 'Bearer ' + secret
    elif requested_status == 404:
        path = re.sub(r'/[^/]+(/undo)?$', lambda m: '/999999' + (m[1] or ''), path)
    elif requested_status == 409:
        if method == 'post' and path == '/tokens':
            create(app, name='synthetic-contract')
        elif method == 'delete':
            app.test_client().delete('/api/v1' + path, headers=headers)
        else:
            created = create(app, name='synthetic-conflict').json
            call(app, '/tokens/' + created['data']['token']['id'], 'delete')
            path = '/events/' + str(created['event_id']) + '/undo'
    elif requested_status == 422:
        body = {'name': '', 'scopes': ['read']}
    elif requested_status == 428:
        headers.pop('Idempotency-Key')
    elif requested_status == 503:
        if path == '/health': monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'missing.db'))
        else:
            monkeypatch.delenv('BW_API_TOKEN')
            # Do not retain the setup credential for a delete or undo operation.
            import os
            with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
                db.execute('DELETE FROM api_tokens')
    response = app.test_client().open('/api/v1' + path, method=method.upper(), headers=headers, json=body)
    assert response.status_code == requested_status, response.text
    definition = resolve(operation['responses'][status])
    media = response.content_type.split(';')[0]
    assert media in definition['content']
    if media == 'application/yaml':
        assert load_yaml(response.text) == CONTRACT
    else:
        validate(response.json, definition['content'][media]['schema'])


def test_strict_loader_closes_nested_refs_nullable_and_inline_objects():
    schema = {'type': 'object', 'properties': {
        'nested': {'type': ['object', 'null'], 'properties': {'known': {'type': 'string'}}},
        'free': {'type': 'object', 'additionalProperties': True},
        'rows': {'type': 'array', 'items': {'$ref': '#/components/schemas/Row'}}}}
    contract = {'paths': {'/example': {'get': {'x-milestone': 'M2', 'responses': {
        '200': {'content': {'application/json': {'schema': schema}}}}}}},
        'components': {'schemas': {'Row': {'type': 'object', 'properties': {'id': {'type': 'integer'}}}}}}
    closed = strict_responses(contract)
    response = closed['paths']['/example']['get']['responses']['200']['content']['application/json']['schema']
    validator = jsonschema.Draft202012Validator({**response, 'components': closed['components']})
    validator.validate({'nested': {'known': 'yes'}, 'free': {'arbitrary': 1}, 'rows': [{'id': 1}]})
    for invalid in ({'extra': True}, {'nested': {'extra': True}}, {'rows': [{'extra': True}]}):
        with pytest.raises(jsonschema.ValidationError, match='Additional properties'):
            validator.validate(invalid)
    assert 'additionalProperties' not in schema  # The served contract is unchanged.
