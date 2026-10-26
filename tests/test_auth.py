"""Browser login: password mode, redirect guard, logout and the empty-password switch-off."""
from pathlib import Path

import pytest

from tests.web_fixtures import app, apps, logged_in  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'synthetic-password'


def test_protected_page_redirects_to_login_with_next(app):
    response = app.test_client().get('/collection/jump?q=x')
    assert response.status_code == 302 and '/login' in response.location


def test_wrong_and_empty_password_are_refused(app):
    client = app.test_client()
    for password in ('wrong', ''):
        response = client.post('/login', data={'password': password})
        assert response.status_code == 302 and 'wrong_password=True' in response.location
    assert client.get('/collection/jump?q=x').status_code == 302


def test_login_then_logout(app):
    client = app.test_client()
    response = client.post('/login?next=/collection/sets', data={'password': PASSWORD})
    assert response.status_code == 302 and response.location.endswith('/collection/sets')
    assert client.get('/collection/sets').status_code == 200
    assert client.get('/logout').status_code == 302
    after = client.get('/collection/sets')
    assert after.status_code == 302 and '/login' in after.location


@pytest.mark.parametrize('target', ['https://evil.example/x', '//evil.example/x', 'javascript:alert(1)',
                                    'tools', '\\\\evil.example'])
def test_redirect_guard_falls_back_to_root(app, target):
    response = app.test_client().post('/login', query_string={'next': target}, data={'password': PASSWORD})
    assert response.status_code == 302
    assert response.location in ('/', 'http://localhost/')


def test_editable_follows_the_login_state(app):
    from brickwork.web.views import bw_collection_editable
    with app.test_client() as anonymous:
        anonymous.get('/login')
        assert not bw_collection_editable()
    with logged_in(app) as client:
        client.get('/collection/sets')
        assert bw_collection_editable()


def test_empty_password_switches_login_off(tmp_path, monkeypatch):
    from flask import Flask
    from brickwork.app import setup_app
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', '')
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
    open_app = Flask('open-test', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(open_app)
    assert open_app.config['LOGIN_DISABLED'] is True
    client = open_app.test_client()
    assert client.get('/collection/jump?q=x').status_code != 302
    assert client.get('/login').status_code == 200
    assert 'Authentication disabled' in client.get('/login').get_data(as_text=True)
    from brickwork.web.views import bw_collection_editable
    with open_app.test_client() as anonymous:
        anonymous.get('/login')
        assert bw_collection_editable()


def test_password_set_enables_login(app):
    assert app.config['LOGIN_DISABLED'] is False
