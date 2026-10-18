"""Catalogues & keys page: write-only key entry, CSRF and no secret in any rendered page."""
from contextlib import closing
import json
import logging
import re
import secrets as token_source
import sqlite3
from unittest.mock import Mock

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import secrets
from brickwork.core.connect import connect
from brickwork.core.sources import base
from tests.test_bw_admin import bw
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps

PAGES = ['tools', 'catalogues', 'jobs', 'refresh', 'unresolved', 'statistics', 'values', 'database', 'settings', 'appearance', 'history', 'instructions']
BL_ENV = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')


def fake():
    return token_source.token_hex(14)


@pytest.fixture
def keyed(app, bw, monkeypatch):
    monkeypatch.delenv('BW_BRICKSET_API_KEY', raising=False)
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY', raising=False)
    for name in BL_ENV: monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    secrets.forget()
    return app


def token(client):
    client.get('/manage/catalogues')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def stored(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT source,ciphertext,archived_at FROM source_keys ORDER BY source').fetchall()


def test_page_has_write_only_password_forms(keyed, bw):
    html = logged_in(keyed).get('/manage/catalogues').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    fields = [i for i in soup.find_all('input') if (i.get('name') or '').startswith('key:')]
    assert {i['name'] for i in fields} == {'key:consumer_key', 'key:consumer_secret', 'key:token_value', 'key:token_secret', 'key:key'}
    assert all(i['type'] == 'password' and i.get('autocomplete') == 'off' and not i.has_attr('value') for i in fields)
    for form in soup.find_all('form'):
        if form.find('input', {'name': 'action'}) and form.find('input', {'name': 'action'})['value'].startswith('key_'):
            assert len(form.find_all('input', {'name': 'csrf_token'})) == 1 and form['method'] == 'post'
    assert 'Brickognize' not in ''.join(str(f.parent) for f in fields)


def test_page_says_entry_is_disabled_without_the_secret(keyed, bw, monkeypatch):
    monkeypatch.delenv('BW_SECRET_KEY')
    html = logged_in(keyed).get('/manage/catalogues').get_data(as_text=True)
    assert 'Key entry is disabled' in html and 'name="key:key"' not in html
    client = logged_in(keyed)
    response = client.post('/manage/catalogues', data={'csrf_token': token(client), 'action': 'key_save', 'source': 'rebrickable', 'key:key': fake()}, follow_redirects=True)
    assert 'Key entry is disabled' in response.get_data(as_text=True) and not stored(bw)


def test_save_replace_test_and_remove_never_echo_values(keyed, bw, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    client = logged_in(keyed)
    csrf = token(client)
    first, second = fake(), fake()
    seen = []
    def post(**data):
        response = client.post('/manage/catalogues', data={'csrf_token': csrf, **data}, follow_redirects=True)
        seen.append(response.get_data(as_text=True))
        assert response.status_code == 200
        return seen[-1]
    assert 'Saved' in post(action='key_save', source='rebrickable', **{'key:key': first})
    (source, cipher, archived), = stored(bw)
    assert source == 'rebrickable' and first not in cipher and archived is None
    assert 'Stored (encrypted)' in seen[-1] and '>Remove<' in seen[-1] and '>Replace<' in seen[-1]
    post(action='key_save', source='rebrickable', **{'key:key': second})
    with closing(sqlite3.connect(bw)) as db:
        event = db.execute("SELECT via,actor,new_value FROM events WHERE entity='source_key:rebrickable' ORDER BY id").fetchall()
        assert [e[:2] for e in event] == [('app', None), ('app', None)] and cipher not in json.dumps(event)
    # Validation messages do not repeat the submitted value.
    bad = 'x y ' + fake()
    assert bad not in post(action='key_save', source='rebrickable', **{'key:key': bad})
    # A test call is a single budgeted request and shows only a fixed success text.
    calls = []
    def transport(request):
        calls.append(request)
        return json.dumps({'id': 0, 'name': 'Black'})
    monkeypatch.setattr(base, 'transport', transport)
    assert 'The key works' in post(action='key_test', source='rebrickable')
    assert len(calls) == 1 and calls[0].headers['Authorization'] == 'key ' + second
    assert 'Saved' in post(action='key_remove', source='rebrickable')
    assert stored(bw)[0][2] is not None
    for text in seen:
        assert first not in text and second not in text and bad not in text
    assert first not in caplog.text and second not in caplog.text


def test_unknown_source_and_keyless_source_are_refused(keyed, bw):
    client = logged_in(keyed)
    csrf = token(client)
    for source in ('nonesuch', 'brickognize'):
        response = client.post('/manage/catalogues', data={'csrf_token': csrf, 'action': 'key_save', 'source': source, 'key:key': fake()}, follow_redirects=True)
        assert response.status_code == 200 and not stored(bw)


@pytest.mark.parametrize('action', ['key_save', 'key_remove', 'key_test'])
@pytest.mark.parametrize('csrf', [None, 'wrong'])
def test_key_actions_reject_bad_csrf_without_writes(keyed, bw, action, csrf, monkeypatch):
    monkeypatch.setattr(base, 'transport', Mock(side_effect=AssertionError('no outbound call')))
    client = logged_in(keyed)
    client.get('/manage/catalogues')
    data = {'action': action, 'source': 'rebrickable', 'key:key': fake()}
    if csrf is not None: data['csrf_token'] = csrf
    with closing(sqlite3.connect(bw)) as db:
        before = list(db.iterdump())
    response = client.post('/manage/catalogues', data=data)
    assert response.status_code == 400 and b'Invalid CSRF token' in response.data
    with closing(sqlite3.connect(bw)) as db:
        assert list(db.iterdump()) == before


def test_read_only_instance_cannot_change_keys(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    keyed.config['BW_READ_ONLY'] = True
    response = client.post('/manage/catalogues', data={'csrf_token': csrf, 'action': 'key_save', 'source': 'rebrickable', 'key:key': fake()})
    assert response.status_code == 403 and not stored(bw)


def test_environment_key_is_shown_as_such(keyed, bw, monkeypatch):
    value = fake()
    monkeypatch.setenv('BW_BRICKSET_API_KEY', value)
    html = logged_in(keyed).get('/manage/catalogues').get_data(as_text=True)
    assert 'Environment' in html and 'Set by environment' in html and value not in html


def test_no_secret_in_any_manage_page_or_log(keyed, bw, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    env_values = {}
    for name in (*BL_ENV, 'BW_BRICKSET_API_KEY'):
        env_values[name] = fake()
        monkeypatch.setenv(name, env_values[name])
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-' + fake())
    stored_value = fake()
    client = logged_in(keyed)
    csrf = token(client)
    pages = []
    pages.append(client.post('/manage/catalogues', data={'csrf_token': csrf, 'action': 'key_save', 'source': 'rebrickable', 'key:key': stored_value}, follow_redirects=True).get_data(as_text=True))
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'detail': 'Invalid ' + request.headers['Authorization']}))
    pages.append(client.post('/manage/catalogues', data={'csrf_token': csrf, 'action': 'key_test', 'source': 'rebrickable'}, follow_redirects=True).get_data(as_text=True))
    for page in PAGES:
        response = client.get('/manage/' + page)
        assert response.status_code == 200, (page, response.headers.get('Location'))
        pages.append(response.get_data(as_text=True))
    export = client.get('/manage/database/export')
    assert export.status_code == 200 and export.data.startswith(b'SQLite format 3')
    with closing(sqlite3.connect(bw)) as db:
        ciphertext = db.execute('SELECT ciphertext FROM source_keys').fetchone()[0]
    needles = [stored_value, ciphertext, *env_values.values(), monkeypatch_secret(monkeypatch)]
    needles += [v[:8] for v in needles[:1] + list(env_values.values())] + [v[-8:] for v in needles[:1] + list(env_values.values())]
    for text in pages + [caplog.text]:
        for needle in needles:
            assert needle and needle not in text
    # The export is a snapshot without the stored key, plaintext or encrypted.
    for needle in needles:
        assert needle.encode() not in export.data


def monkeypatch_secret(monkeypatch):
    import os
    return os.environ['BW_SECRET_KEY']


def test_embedded_worker_flag_stops_every_path(keyed, bw, monkeypatch):
    from brickwork.web import views
    from brickwork.core import drainer
    spawned = []
    monkeypatch.setattr(drainer, 'spawn', spawned.append)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT OR IGNORE INTO sources(source,name,kind) VALUES('import','Import','manual')")
        db.execute("INSERT INTO jobs(source,kind,state,created_at,updated_at) VALUES('import','item','queued','2026-10-12','2026-10-12')")
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    with keyed.test_request_context():
        assert views.bw_start_worker() is False
    views.bw_resume_imports(keyed)
    from brickwork.api import operations
    started = []
    monkeypatch.setattr(operations, 'spawn', started.append)
    with keyed.test_request_context():
        assert operations.start_worker() is False
    assert not spawned
    assert not started
    monkeypatch.delenv('BW_EMBEDDED_WORKER')
    views.bw_resume_imports(keyed)
    assert len(spawned) == 1
    with keyed.test_request_context():
        assert views.bw_start_worker() is True            # one drainer per app
    assert len(spawned) == 1
