"""#60: a fresh install works without BW_AUTHENTICATION_KEY, and no password needs an explicit opt-in."""
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask

from brickwork.app import setup_app
from brickwork.core.connect import connect
from brickwork.settings import exposure_problem
from brickwork.web.auth import session_key

ROOT = Path(__file__).resolve().parents[1]


def fresh(tmp_path, monkeypatch, **env):
    for key in list(os.environ):
        if key.startswith('BW_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    connect(tmp_path / 'brickwork.db').close()
    app = Flask('first-run', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config['TESTING'] = True
    return app


def test_pages_work_without_a_session_key(tmp_path, monkeypatch):
    app = fresh(tmp_path, monkeypatch, BW_ALLOW_NO_LOGIN='1')
    assert app.secret_key and len(app.secret_key) >= 32
    assert app.test_client().get('/collection/sets').status_code == 200
    key = tmp_path / 'session.key'
    assert key.read_text().strip() == app.secret_key
    assert key.stat().st_mode & 0o777 == 0o600


def test_login_works_without_a_session_key(tmp_path, monkeypatch):
    app = fresh(tmp_path, monkeypatch, BW_AUTHENTICATION_PASSWORD='synthetic-password')
    client = app.test_client()
    assert client.post('/login', data={'password': 'synthetic-password'}).status_code == 302
    assert client.get('/collection/sets').status_code == 200


def test_the_key_survives_a_restart_and_a_set_key_wins(tmp_path, monkeypatch):
    first = fresh(tmp_path, monkeypatch, BW_ALLOW_NO_LOGIN='1').secret_key
    assert fresh(tmp_path, monkeypatch, BW_ALLOW_NO_LOGIN='1').secret_key == first
    assert fresh(tmp_path, monkeypatch, BW_ALLOW_NO_LOGIN='1', BW_AUTHENTICATION_KEY='synthetic-session').secret_key == 'synthetic-session'


def test_without_a_writable_folder_the_key_is_in_memory(tmp_path, monkeypatch):
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'missing' / 'brickwork.db'))
    assert len(session_key()) >= 32
    assert not (tmp_path / 'missing').exists()


def test_exposure_needs_a_password_or_an_opt_in():
    assert 'BW_ALLOW_NO_LOGIN' in exposure_problem({'AUTHENTICATION_PASSWORD': '', 'ALLOW_NO_LOGIN': False})
    assert exposure_problem({'AUTHENTICATION_PASSWORD': 'x', 'ALLOW_NO_LOGIN': False}) is None
    assert exposure_problem({'AUTHENTICATION_PASSWORD': '', 'ALLOW_NO_LOGIN': True}) is None


def test_the_wsgi_entry_refuses_an_open_install(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith('BW_')}
    env.update(BW_DB_PATH=str(tmp_path / 'brickwork.db'), BW_EMBEDDED_WORKER='0', PYTHONPATH=str(ROOT))
    code = 'import sys; sys.modules["gevent"] = type(sys)("gevent"); m = type(sys)("gevent.monkey"); m.patch_all = lambda: None; sys.modules["gevent.monkey"] = m; sys.modules["gevent"].monkey = m; import wsgi'
    refused = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert refused.returncode != 0 and 'BW_ALLOW_NO_LOGIN' in refused.stderr
    allowed = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=dict(env, BW_ALLOW_NO_LOGIN='1'), capture_output=True, text=True)
    assert allowed.returncode == 0, allowed.stderr


def test_compose_publishes_on_this_computer_only():
    assert '"127.0.0.1:3333:3333"' in (ROOT / 'compose.yaml').read_text()
