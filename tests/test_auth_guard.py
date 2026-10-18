"""Every web route requires login when a password is set; the public list is explicit."""
import json
import re

from tests.web_fixtures import app, apps, logged_in

PUBLIC_ENDPOINTS = {'login.login', 'login.do_login', 'login.logout', 'static',
                    'web.web_manifest', 'web.shell_worker'}


def concrete(rule):
    values = {}
    for argument in rule.arguments:
        values[argument] = 1 if type(rule._converters[argument]).__name__ == 'IntegerConverter' else 'x'
    return rule.build(values, append_unknown=False)[1]


def test_every_web_route_requires_login(app):
    app.config['PROPAGATE_EXCEPTIONS'] = False
    anonymous = app.test_client()
    checked, open_routes = [], []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC_ENDPOINTS or rule.rule.startswith(('/api/', '/mcp')):
            continue
        path = concrete(rule)
        for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
            response = anonymous.open(path, method=method)
            guarded = response.status_code == 401 or (response.status_code == 302 and '/login' in response.location)
            checked.append((method, rule.rule))
            if not guarded:
                open_routes.append((method, rule.rule, response.status_code))
    assert len(checked) > 40
    assert not open_routes, "OPEN: " + repr(open_routes)


def test_public_routes_are_exactly_the_documented_ones(app):
    client = app.test_client()
    assert client.get('/login').status_code == 200
    assert client.get('/manifest.webmanifest').status_code == 200
    assert client.get('/sw.js').status_code == 200
    assert client.get('/static/web/toni/shell.css').status_code == 200
    unauthenticated = client.get('/api/v1/health')
    assert unauthenticated.status_code != 302  # the API has its own token authentication


def test_login_disabled_leaves_routes_open(tmp_path, monkeypatch, apps):
    monkeypatch.delenv('BW_AUTHENTICATION_PASSWORD', raising=False)
    open_app = apps('toni')
    open_app.config['LOGIN_DISABLED'] = True
    assert open_app.test_client().get('/collection/jump?q=x').status_code != 302
