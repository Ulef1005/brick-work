"""API v2 transport (M.11a, issue #113): authentication, scopes, the throttle, read-only, the meta endpoints, errors and the 501 placeholders.

Ported to v2 from the transport tests of test_bw_api_m1 and test_app_factory (and the contract-file test of test_runtime_contract); the
v1 line only answers 410 (tests/test_standalone_smoke.py)."""
from pathlib import Path

import pytest

from brickwork import api2
from brickwork.api2 import operations
from brickwork.core import throttle
from brickwork.core.errors import API_V1_RETIRED
from tests.api2 import BOOTSTRAP, PREFIX, call, stored_token, v2  # noqa: F401
from tests.api2 import app4, coll, pair  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


# --- meta
def test_health_needs_no_token_and_names_v2(v2):
    response = v2.get(PREFIX + '/health')
    assert response.status_code == 200
    assert response.json['data'] == {'status': 'ok', 'api': '2.0.0', 'app': response.json['data']['app'], 'schema': '4.0'}
    assert response.headers['Cache-Control'] == 'no-store'


def test_version_me_and_openapi(v2):
    version = call(v2, '/version')
    assert version.status_code == 200
    assert version.json['data']['api'] == '2.0.0' and version.json['data']['read_only'] is False
    assert call(v2, '/me').json['data'] == {'name': 'bootstrap', 'scopes': ['admin'], 'expires_at': None}
    served = v2.get(PREFIX + '/openapi.yaml')                                 # no token
    assert served.status_code == 200 and served.mimetype == 'application/yaml'
    assert served.get_data(as_text=True) == (ROOT / 'docs/brickwork/openapi-v2.yaml').read_text()


def test_the_v1_line_is_gone_and_names_v2(v2):
    gone = v2.get('/api/v1/copies')
    assert gone.status_code == 410 and gone.json['code'] == 'api_retired'
    assert gone.json['detail'] == API_V1_RETIRED
    assert '/api/v2' in gone.json['detail'] and 'api-v2.md' in gone.json['detail']
    assert v2.get('/api/v1/health').status_code == 200                        # release tracking still reads it


# --- authentication and scopes
def test_a_token_is_needed_and_a_wrong_one_refused(v2):
    for path in ('/version', '/me', '/items/1', '/copies', '/tokens'):
        refused = call(v2, path, token=None)
        assert refused.status_code == 401, path
        assert refused.mimetype == 'application/problem+json' and refused.json['code'] == 'unauthorized'
        assert refused.headers['WWW-Authenticate'] == 'Bearer'
    throttle.API.clients.clear()                                              # five failures in a row would back the client off
    assert call(v2, '/me', token='wrong').status_code == 401


def test_no_token_configured_is_503_api_disabled(app4, monkeypatch):
    monkeypatch.delenv('BW_API_TOKEN', raising=False)
    refused = call(app4.test_client(), '/me', token='anything')
    assert refused.status_code == 503 and refused.json['code'] == 'api_disabled'


def test_scopes_come_from_the_contract(v2, pair):
    reader = stored_token(pair, ['read'], 'reader')
    writer = stored_token(pair, ['read', 'write'], 'writer')
    assert call(v2, '/me', token=reader).status_code == 200
    # a write operation needs write: 403 for read, then 501 (not yet implemented) once the scope passes
    refused = call(v2, '/copies', 'post', token=reader, json={})
    assert refused.status_code == 403 and refused.json['code'] == 'forbidden'
    assert call(v2, '/copies', 'post', token=writer, json={}).status_code == 501
    # admin operations need admin, even to read
    for method, path in (('get', '/tokens'), ('get', '/database/check'), ('patch', '/settings')):
        assert call(v2, path, method, token=writer, json={}).status_code == 403, path
        assert call(v2, path, method, json={}).status_code == 501, path
    # the scope of every operation is the one the contract names
    spec = operations()
    assert spec['patch_settings']['scope'] == 'admin' and spec['get_copies']['scope'] == 'read' and spec['post_copies']['scope'] == 'write'


def test_an_expired_or_revoked_token_is_refused(v2, pair):
    from contextlib import closing
    from brickwork.core import tokens
    from brickwork.core.connect import connect
    with closing(connect(pair)) as db:
        created, _ = tokens.create(db, 'short-lived', ['read'])
        tokens.revoke(db, created['token']['id'])
    assert call(v2, '/me', token=created['secret']).status_code == 401


def test_failed_token_checks_back_off_per_client(v2, monkeypatch):
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '2')
    for _ in range(2):
        assert call(v2, '/me', token='wrong').status_code == 401
    refused = call(v2, '/me')
    assert refused.status_code == 429 and refused.json['code'] == 'too_many_attempts'
    assert int(refused.headers['Retry-After']) >= 1 and refused.json['retry_after'] >= 1
    assert call(v2, '/me', environ_base={'REMOTE_ADDR': '10.0.0.9'}).status_code == 200


def test_read_only_refuses_every_write_whatever_the_scope(v2, app4):
    app4.config['BW_READ_ONLY'] = True
    assert call(v2, '/me').status_code == 200 and call(v2, '/items/1').status_code == 200
    for method, path in (('post', '/copies'), ('patch', '/settings'), ('delete', '/copies/x'), ('post', '/items/1/merge')):
        refused = call(v2, path, method, json={})
        assert refused.status_code == 403 and refused.json['code'] == 'read_only_instance', path


# --- the 501 placeholders
def pending():
    return [(o['method'], o['path'], o['piece']) for o in operations().values() if o['piece'] not in api2.DONE]


def test_every_operation_of_a_later_piece_answers_501_with_its_piece(v2):
    wrong = []
    for method, template, piece in pending():
        path = template
        for name in ('id', 'item_id', 'part_id', 'line_id', 'doc_id', 'color_id', 'source', 'code', 'no'):
            path = path.replace('{' + name + '}', '1')
        throttle.API.clients.clear()                                          # the unauthenticated probe below is a failed check
        response = call(v2, path, method.lower(), json={} if method != 'GET' else None)
        unauthenticated = call(v2, path, method.lower(), token=None)
        ok = (response.status_code == 501 and response.mimetype == 'application/problem+json' and response.json['error'] == 'not_implemented'
              and response.json['code'] == 'not_implemented' and response.json['piece'] == piece and unauthenticated.status_code == 401)
        if not ok:
            wrong.append((method, path, response.status_code))
    assert not wrong, wrong


def test_the_501_list_is_the_contract_minus_the_done_pieces():
    spec = operations()
    assert {p for _, _, p in pending()} == {'M.11b', 'M.11c', 'M.11d'}
    assert len(spec) - len(pending()) == 9
