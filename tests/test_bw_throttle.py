"""#48: failed web logins and API token checks back off per client; nothing submitted is logged."""
import logging

from flask import Flask
import pytest

from brickwork.core import throttle
from tests.test_bw_api_m1 import app as api_app  # noqa: F401
from tests.web_fixtures import app, apps  # noqa: F401


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_threshold_doubling_cap_reset_and_isolation(monkeypatch):
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '3')
    monkeypatch.setenv('BW_LOGIN_MAX_DELAY', '8')
    clock = Clock()
    t = throttle.Throttle('Test', clock=clock)
    for _ in range(2):
        t.fail('a')
    assert t.wait('a') == 0
    waits = []
    for _ in range(6):
        t.fail('a')
        waits.append(t.wait('a'))
    assert waits == [1, 2, 4, 8, 8, 8]
    assert t.wait('b') == 0
    clock.now += 8
    assert t.wait('a') == 0
    t.succeed('a')
    t.fail('a')
    assert t.wait('a') == 0


def test_cap_drops_the_oldest(monkeypatch):
    monkeypatch.setattr(throttle, 'CAP', 3)
    clock = Clock()
    t = throttle.Throttle('Test', clock=clock)
    for name in 'abcd':
        clock.now += 1
        t.fail(name)
    assert set(t.clients) == {'b', 'c', 'd'}


@pytest.fixture
def web(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '2')
    return app


def test_web_login_backoff_message_and_no_password_in_logs(web, caplog):
    caplog.set_level(logging.DEBUG)
    client = web.test_client()
    for _ in range(2):
        assert client.post('/login', data={'password': 'wrong-guess-123'}).status_code == 302
    blocked = client.post('/login', data={'password': 'synthetic-password'})
    assert blocked.status_code == 429 and b'Too many attempts' in blocked.data
    assert 'wrong-guess-123' not in caplog.text and 'synthetic-password' not in caplog.text
    assert 'Login failed for 127.0.0.1' in caplog.text
    other = web.test_client()
    assert other.post('/login', data={'password': 'synthetic-password'}, environ_base={'REMOTE_ADDR': '10.0.0.9'}).status_code == 302
    throttle.LOGIN.clients.clear()
    assert client.post('/login', data={'password': 'synthetic-password'}).headers['Location'] == '/'


def test_api_429_retry_after_and_valid_token_elsewhere(api_app, monkeypatch):
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '2')
    client = api_app.test_client()
    for _ in range(2):
        assert client.get('/api/v1/me', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    refused = client.get('/api/v1/me', headers={'Authorization': 'Bearer synthetic-bootstrap'})
    assert refused.status_code == 429 and refused.json['code'] == 'too_many_attempts'
    assert int(refused.headers['Retry-After']) >= 1 and refused.json['retry_after'] >= 1
    elsewhere = client.get('/api/v1/me', headers={'Authorization': 'Bearer synthetic-bootstrap'},
                           environ_base={'REMOTE_ADDR': '10.0.0.9'})
    assert elsewhere.status_code == 200


def test_forwarded_for_is_ignored_without_trusted_proxies(web):
    client = web.test_client()
    for n in range(2):
        client.post('/login', data={'password': 'wrong'}, headers={'X-Forwarded-For': f'10.9.0.{n}'})
    blocked = client.post('/login', data={'password': 'synthetic-password'}, headers={'X-Forwarded-For': '10.9.0.99'})
    assert blocked.status_code == 429


def test_forwarded_for_is_used_with_one_trusted_proxy(apps, monkeypatch):  # noqa: F811
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '2')
    monkeypatch.setenv('BW_TRUSTED_PROXIES', '1')
    client = apps('toni').test_client()
    for _ in range(2):
        client.post('/login', data={'password': 'wrong'}, headers={'X-Forwarded-For': '10.9.0.1'})
    assert client.post('/login', data={'password': 'synthetic-password'}, headers={'X-Forwarded-For': '10.9.0.1'}).status_code == 429
    assert client.post('/login', data={'password': 'synthetic-password'}, headers={'X-Forwarded-For': '10.9.0.2'}).status_code == 302


def test_api_forwarded_for_is_ignored_by_default(api_app, monkeypatch):  # noqa: F811
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '2')
    from brickwork.app import setup_app
    full = Flask('proxy-default')
    setup_app(full)
    client = full.test_client()
    for n in range(3):
        client.get('/api/v1/me', headers={'Authorization': 'Bearer wrong', 'X-Forwarded-For': f'10.9.1.{n}'})
    assert client.get('/api/v1/me', headers={'Authorization': 'Bearer wrong', 'X-Forwarded-For': '10.9.1.50'}).status_code == 429


def test_mcp_in_process_client_carries_the_caller_address(api_app, monkeypatch):  # noqa: F811
    from brickwork.core.mcp.client import InProcessClient
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '2')
    for _ in range(2):
        InProcessClient(api_app, 'wrong', remote_addr='10.9.2.1').request('GET', '/me')
    assert InProcessClient(api_app, 'synthetic-bootstrap', remote_addr='10.9.2.1').request('GET', '/me')[0] == 429
    assert InProcessClient(api_app, 'synthetic-bootstrap', remote_addr='10.9.2.2').request('GET', '/me')[0] == 200
