"""Synthetic standalone browser fixtures shared by core route tests."""
from pathlib import Path
from flask import Flask
import pytest
from brickwork.app import setup_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def apps(tmp_path, monkeypatch):
    def create(mode=None):
        monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
        monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', 'synthetic-password')
        monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
        app = Flask('browser-tests', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
        setup_app(app)
        app.config.update(TESTING=True, SECRET_KEY='synthetic-session')
        return app
    return create


@pytest.fixture
def app(apps):
    return apps('toni')


def logged_in(app):
    from brickwork.web.auth import SESSION_PASSWORD, password_mark
    client = app.test_client()
    with app.app_context():
        mark = password_mark(app.config['AUTHENTICATION_PASSWORD'])
    with client.session_transaction() as session:
        session['_user_id'] = 'admin'
        session['_fresh'] = True
        session[SESSION_PASSWORD] = mark
    return client
