"""M1 auth, lifecycle, paging and offline standalone contracts (synthetic data)."""
from contextlib import closing
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import socket
import subprocess

from flask import Flask, abort
import pytest

from brickwork.api import register
from brickwork.core import tokens
from brickwork.core.connect import connect
from brickwork.core.listing import filter_rows, paginate
from brickwork.core.sources.base import now


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv('BW_READ_ONLY', raising=False)
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
    with closing(connect(tmp_path / 'brickwork.db')): pass
    app = Flask(__name__)
    app.config.update(TESTING=True)
    register(app)
    return app


def call(app, path, method='get', token='synthetic-bootstrap', **kwargs):
    return getattr(app.test_client(), method)('/api/v1' + path, headers={'Authorization': 'Bearer ' + token}, **kwargs)


def create(app, name='synthetic-client', scopes=None):
    return call(app, '/tokens', 'post', json={'name': name, 'scopes': scopes or ['read']})


@pytest.mark.parametrize('header', [{}, {'Authorization': 'Bearer wrong'}, {'X-Web-Token': 'synthetic-bootstrap'}])
def test_auth_headers(app, header):
    response = app.test_client().get('/api/v1/me', headers=header)
    assert response.status_code == 401
    assert response.content_type == 'application/problem+json'
    assert response.json['code'] == 'unauthorized'
    assert response.headers['WWW-Authenticate'] == 'Bearer'


def test_disabled_and_public(app, monkeypatch):
    monkeypatch.delenv('BW_API_TOKEN')
    assert call(app, '/me').json['code'] == 'api_disabled'
    assert app.test_client().get('/api/v1/health').status_code == 200
    assert app.test_client().get('/api/v1/openapi.yaml').status_code == 200


def test_lifecycle_and_audit(app, monkeypatch, caplog):
    created = create(app)
    assert created.status_code == 201
    value = created.json['data']; secret = value['secret']; identifier = value['token']['id']
    assert call(app, '/me', token=secret).json['data']['name'] == 'synthetic-client'
    assert call(app, '/tokens', token=secret).status_code == 403
    listing = call(app, '/tokens')
    assert secret not in listing.text and 'hash' not in listing.text
    assert listing.json['data'][0]['last_used_at']
    import os
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        row = db.execute('SELECT * FROM api_tokens').fetchone()
        assert row['hash'] == hashlib.sha256(secret.encode()).hexdigest()
        assert secret not in json.dumps(dict(row))
        before = row['last_used_at']
        assert [tuple(r) for r in db.execute('SELECT via,actor FROM events')] == [('api', 'bootstrap')]
    call(app, '/me', token=secret)
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute('SELECT last_used_at FROM api_tokens').fetchone()[0] == before
    assert call(app, '/tokens/' + identifier, 'delete').status_code == 200
    assert call(app, '/me', token=secret).status_code == 401
    assert call(app, '/tokens/' + identifier, 'delete').status_code == 409
    assert call(app, '/tokens/bootstrap', 'delete').status_code == 404
    assert call(app, '/me').status_code == 200
    assert secret not in caplog.text


@pytest.mark.parametrize('scope', ['read', 'write', 'admin'])
def test_scope_matrix(app, scope):
    secret = create(app, scopes=[scope]).json['data']['secret']
    assert call(app, '/version', token=secret).status_code == 200
    assert call(app, '/tokens', token=secret).status_code == (200 if scope == 'admin' else 403)


def test_expiry_and_constant_time(app, monkeypatch):
    secret = create(app).json['data']['secret']
    import os
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute('UPDATE api_tokens SET expires_at=?', ((now() - timedelta(seconds=1)).isoformat(),))
    calls = []
    original = tokens.hmac.compare_digest
    def spy(a, b):
        calls.append((a, b)); return original(a, b)
    monkeypatch.setattr(tokens.hmac, 'compare_digest', spy)
    assert call(app, '/me', token=secret).status_code == 401
    assert call(app, '/me', token='wrong').status_code == 401
    assert call(app, '/me').status_code == 200
    assert len(calls) == 5 and all(len(a) == len(b) == 64 for a, b in calls)


@pytest.mark.parametrize('setting', ['env', 'config'])
def test_read_only(app, monkeypatch, setting):
    if setting == 'env': monkeypatch.setenv('BW_READ_ONLY', 'true')
    else: app.config['BW_READ_ONLY'] = True
    assert create(app).json['code'] == 'read_only_instance'
    assert call(app, '/tokens', 'options').status_code == 403
    assert call(app, '/health', 'head').status_code == 403
    assert call(app, '/version').json['data']['read_only'] is True


def test_errors_and_atomic_validation(app):
    assert call(app, '/unknown').json['code'] == 'not_found'
    assert create(app).status_code == 201
    assert create(app).status_code == 409
    assert create(app, scopes=['invalid']).status_code == 422
    assert call(app, '/tokens', 'post', data='{', content_type='application/json').status_code == 400
    assert call(app, '/tokens', 'post', json=[]).status_code == 400
    assert call(app, '/tokens?unknown=x').json['code'] == 'unknown_filter'
    for query in ('limit=0', 'limit=201', 'limit=bad', 'cursor=bad'):
        assert call(app, '/tokens?' + query).status_code == 400
    assert call(app, '/tokens?direction=bad').status_code == 400
    assert len(call(app, '/tokens').json['data']) == 1


def test_method_not_allowed(app):
    response = call(app, '/tokens', 'put')
    assert response.status_code == response.json['status'] == 405
    assert response.json['code'] == 'method_not_allowed'
    assert response.content_type == 'application/problem+json'
    assert set(response.headers['Allow'].split(', ')) == {'GET', 'HEAD', 'POST', 'OPTIONS'}


@pytest.mark.parametrize('status,code', [
    (400, 'bad_request'), (401, 'unauthorized'), (403, 'forbidden'),
    (404, 'not_found'), (409, 'conflict'), (410, 'bad_request'),
    (412, 'bad_request'), (413, 'payload_too_large'),
    (415, 'unsupported_media_type'), (422, 'bad_request'),
    (429, 'bad_request'), (500, 'internal_error'), (502, 'internal_error'),
])
def test_http_exception_status(app, status, code):
    # Replace a blueprint view so abort() goes through its real error handler.
    def fail():
        abort(status, description='Synthetic private detail')
    app.view_functions['brickwork_api.get_me'] = fail
    response = call(app, '/me')
    assert response.status_code == response.json['status'] == status
    assert response.json['code'] == code
    assert response.content_type == 'application/problem+json'
    assert 'private detail' not in response.text
    if status == 401:
        assert response.headers['WWW-Authenticate'] == 'Bearer'


def test_token_list_query_count(app, monkeypatch):
    import os
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.executemany('INSERT INTO api_tokens VALUES(?,?,?,?,?,NULL,NULL,NULL)',
                       [(str(i), f'Synthetic {i}', '0' * 64, '["read"]', now().isoformat()) for i in range(350)])
    import brickwork.api as api
    real = api.connect; queries = []
    def traced(path):
        db = real(path); db.set_trace_callback(queries.append); return db
    monkeypatch.setattr(api, 'connect', traced)
    response = call(app, '/tokens?limit=200')
    assert response.status_code == 200 and len(response.json['data']) == 200
    assert len(queries) <= 4
    cursor = response.json['page']['next_cursor']
    assert len(call(app, '/tokens?limit=200&cursor=' + cursor).json['data']) == 150


def test_cli_tokens(app, capsys):
    from brickwork.web.cli import main
    assert main(['token', 'create', '--name', 'synthetic-cli', '--scope', 'read,write', '--expires', '90d']) == 0
    value = json.loads(capsys.readouterr().out)
    assert main(['token', 'list']) == 0
    assert value['secret'] not in capsys.readouterr().out
    assert main(['token', 'revoke', value['token']['id']]) == 0
    capsys.readouterr()
    assert call(app, '/me', token=value['secret']).status_code == 401


def undo(app, event, key='synthetic-undo'):
    return app.test_client().post(f'/api/v1/events/{event}/undo', headers={
        'Authorization': 'Bearer synthetic-bootstrap', 'Idempotency-Key': key})


def test_token_undo_and_replay(app):
    created = create(app)
    secret = created.json['data']['secret']
    identifier = created.json['data']['token']['id']
    revoked = call(app, '/tokens/' + identifier, 'delete')
    assert call(app, '/me', token=secret).status_code == 401
    undone = undo(app, revoked.json['event_id'])
    assert undone.status_code == 200
    assert call(app, '/me', token=secret).status_code == 200
    assert undo(app, revoked.json['event_id']).json['idempotent_replay'] is True
    assert undo(app, created.json['event_id']).json['code'] == 'idempotency_conflict'
    assert call(app, f"/events/{created.json['event_id']}/undo", 'post').json['code'] == 'idempotency_key_required'
    assert undo(app, created.json['event_id'], 'second-undo').status_code == 200
    assert call(app, '/me', token=secret).status_code == 401
    assert undo(app, created.json['event_id'], 'third-undo').json['data']['already_undone'] is True


def test_undo_creation_archives_token(app):
    created = create(app)
    assert undo(app, created.json['event_id']).status_code == 200
    assert call(app, '/me', token=created.json['data']['secret']).status_code == 401
    assert call(app, '/tokens').json['data'][0]['revoked_at']


def test_undo_errors(app):
    assert undo(app, 999).status_code == 404
    created = create(app)
    event = created.json['event_id']
    assert undo(app, event, 'invalid key').status_code == 400
    call(app, '/tokens/' + created.json['data']['token']['id'], 'delete')
    assert undo(app, event).json['code'] == 'undo_blocked'


def test_token_write_rollback(app, monkeypatch):
    def fail(*args, **kwargs): raise RuntimeError('Synthetic audit failure')
    monkeypatch.setattr(tokens, 'audit', fail)
    assert create(app).status_code == 500
    assert call(app, '/tokens').json['data'] == []


def test_database_and_redacted_errors(app, monkeypatch):
    import brickwork.api as api
    import sqlite3
    def fail(*args, **kwargs): raise sqlite3.OperationalError('Synthetic private detail')
    monkeypatch.setattr(api, 'connect', fail)
    response = call(app, '/health')
    assert response.status_code == 503 and response.json['code'] == 'db_unavailable'
    assert 'private detail' not in response.text
    def invalid(*args, **kwargs): raise ValueError('Synthetic validation synthetic-bootstrap')
    monkeypatch.setattr(api, 'connect', invalid)
    response = call(app, '/health')
    assert response.status_code == 422 and 'Synthetic validation' in response.json['detail']
    assert 'synthetic-bootstrap' not in response.text


def test_missing_database_health_is_public_problem(app, monkeypatch, tmp_path):
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'missing.db'))
    assert call(app, '/health').json['code'] == 'not_set_up'
    assert not (tmp_path / 'missing.db').exists()


def test_stored_auth_without_bootstrap(app, monkeypatch):
    value = create(app).json['data']
    monkeypatch.delenv('BW_API_TOKEN')
    assert call(app, '/me', token=value['secret']).status_code == 200
    assert call(app, '/me', token='wrong').json['code'] == 'unauthorized'


@pytest.mark.parametrize('payload', [
    {'name': 'bootstrap', 'scopes': ['admin']},
    {'name': ' bootstrap ', 'scopes': ['admin']},
    {'name': 'Synthetic', 'scopes': []},
    {'name': 'Synthetic', 'scopes': ['read'], 'expires_at': '2020-01-01T00:00:00+00:00'},
    {'name': 'Synthetic', 'scopes': ['read'], 'expires_at': '2099-01-01T00:00:00'},
    {'name': 'Synthetic', 'scopes': ['read'], 'unknown': True},
])
def test_invalid_token_fields(app, payload):
    assert call(app, '/tokens', 'post', json=payload).status_code == 422
    assert call(app, '/tokens').json['data'] == []


def test_undo_nonreceipt(app, monkeypatch):
    created = create(app)
    response = undo(app, created.json['event_id'])
    assert undo(app, response.json['event_id'], 'undo-undo').json['code'] == 'not_undoable'


def test_cli_error_is_safe(app, capsys):
    from brickwork.web.cli import main
    assert main(['token', 'create', '--name', 'bootstrap', '--scope', 'admin']) == 1
    assert 'Token error:' in capsys.readouterr().err
