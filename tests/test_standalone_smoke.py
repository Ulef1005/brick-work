"""Standalone installation contract on the 4.0 store: real app and CLI, a fixture catalogue built offline, no sockets (M.8a, #110).

What renders without ported modules: `/` and `/collection/sets` (the first-run page on an empty collection), the install files and the
login page; every other browser screen answers 503 until its piece ports it. API v1 answers 410, except `/api/v1/health`."""
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3

import pytest
from flask import Flask

from brickwork.app import setup_app
from brickwork.core.connect import OldStore, connect
from brickwork.core.errors import API_V1_RETIRED
from brickwork.version import __version__
from brickwork.web.cli import main
from tests.legacy33 import create_33
from tests.store4_mint_fixtures import build_catalogue

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def offline(monkeypatch):
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise AssertionError('Standalone smoke attempted an outbound connection')
    for method in ('connect', 'connect_ex'):
        monkeypatch.setattr(socket.socket, method, blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    for key in list(os.environ):
        if key.startswith('BW_'):
            monkeypatch.delenv(key)
    return attempts


def make_app(path, monkeypatch):
    monkeypatch.setenv('BW_DB_PATH', str(path))
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_KEY', 'synthetic-session')
    app = Flask('standalone-smoke', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config['TESTING'] = True
    return app


def test_standalone_smoke(tmp_path, monkeypatch, offline, capsys):
    path = tmp_path / 'data' / 'brickwork.db'
    bootstrap = secrets.token_urlsafe(32)
    monkeypatch.setenv('BW_DB_PATH', str(path))
    monkeypatch.setenv('BW_API_TOKEN', bootstrap)
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_KEY', 'synthetic-session')
    # setup makes a fresh 4.0 collection and says where the catalogue comes from
    assert main(['setup']) == 0
    said = capsys.readouterr().out
    assert path.is_file() and 'missing' in said and 'catalogue download' in said
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'
    with pytest.raises(Exception, match='No catalogue at .*catalogue.db'):
        connect(path)
    # the fixture catalogue, built offline, goes beside the collection
    (tmp_path / 'cat').mkdir()
    shutil.copy(build_catalogue(tmp_path / 'cat'), path.with_name('catalogue.db'))
    app = make_app(path, monkeypatch)
    client = app.test_client()
    # health is the one v1 route that answers: no token, the app version and the 4.0 schema
    health = client.get('/api/v1/health')
    assert health.status_code == 200, health.text
    assert health.json['data'] == {'status': 'ok', 'api': '1.0.0', 'app': __version__, 'schema': '4.0'}
    # every other v1 route is gone, with or without a token, and says why
    for method, route in (('get', '/version'), ('get', '/me'), ('get', '/copies'), ('post', '/copies'), ('get', '/events'),
                          ('post', '/events/1/undo'), ('get', '/openapi.yaml'), ('get', '/does-not-exist')):
        response = getattr(client, method)('/api/v1' + route, headers={'Authorization': 'Bearer ' + bootstrap})
        assert response.status_code == 410, (route, response.status_code)
        assert response.mimetype == 'application/problem+json'
        assert response.json['code'] == 'api_retired' and API_V1_RETIRED in response.json['detail']
    assert client.get('/api/v1/copies').status_code == 410                       # not even a token is asked for
    # the first-run page is what renders on an empty collection
    for route in ('/', '/collection/sets'):
        first_run = client.get(route)
        assert first_run.status_code == 200, route
        html = first_run.get_data(as_text=True)
        assert 'data-first-run' in html and 'Nothing here yet.' in html and 'href="/manage/catalogues"' in html
        assert html.count('class="fr-step"') + html.count('class="fr-step ') == 4
    assert 'Cache-Control' in client.get('/').headers
    # a screen that is not ported yet says so, in the app's own shell
    held = client.get('/manage/tools')
    assert held.status_code == 503 and 'not on the 4.0 store yet' in held.get_data(as_text=True)
    assert client.get('/manifest.webmanifest').status_code == 200
    assert client.get('/login').status_code == 200
    # the MCP server talks v1 and refuses with the same explanation
    assert main(['mcp']) == 1
    assert API_V1_RETIRED in capsys.readouterr().err
    assert {f.name for f in path.parent.glob('*.db')} == {'brickwork.db', 'catalogue.db'}
    assert offline == []


def test_a_3_3_collection_is_refused_with_the_fix_named(tmp_path, monkeypatch, offline):
    path = tmp_path / 'data' / 'brickwork.db'
    path.parent.mkdir()
    create_33(path).close()
    (tmp_path / 'cat').mkdir()
    shutil.copy(build_catalogue(tmp_path / 'cat'), path.with_name('catalogue.db'))
    before = path.read_bytes()
    with pytest.raises(OldStore, match=r'python -m brickwork\.store4 migrate'):
        connect(path)
    with pytest.raises(OldStore, match='3.2/3.3'):
        connect(path, read_only=True)
    with pytest.raises(OldStore):
        make_app(path, monkeypatch)                                                # the app does not boot on it
    assert main(['setup']) == 1                                                     # BW_DB_PATH names it: setup refuses too
    assert path.read_bytes() == before                                              # refused means untouched
    assert offline == []
