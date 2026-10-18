"""Only standalone browser/API routes survive, with no URL aliases."""
from pathlib import Path
import re

from tests.web_fixtures import app, apps, logged_in  # noqa: F401


def test_route_manifest_and_retired_paths(app):
    rules = {}
    for rule in app.url_map.iter_rules():
        rules.setdefault(rule.rule, []).append(rule)
    old_prefix = '/' + 'ho' + 'use'
    assert not any(path.startswith(old_prefix) for path in rules)
    table = Path('docs/brickwork/cutover-4.11j.md').read_text()
    rows = re.findall(r'\| (GET|POST|GET, POST) \| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \|', table)
    assert rows
    for methods, old, new, backing in rows:
        assert old == old_prefix + new
        assert new in rules
        assert any(set(methods.split(', ')) <= rule.methods and rule.endpoint == 'web.' + backing for rule in rules[new])
    client = app.test_client()
    for path in (old_prefix + '/collection/sets', old_prefix + '/workbench/matcher',
                 old_prefix + '/api/v1/health', old_prefix + '/api/settings',
                 '/sets/', '/admin/', '/prices/example/refresh-bricklink'):
        response = client.get(path)
        assert response.status_code == 404, (path, response.status_code)
        assert 'Location' not in response.headers
    assert client.get('/api/v1/health').json['code'] == 'not_set_up'
    assert set(app.blueprints) == {'web', 'login', 'brickwork_api'}


def test_static_shell_contains_only_live_assets(app):
    response = app.test_client().get('/sw.js')
    assert response.status_code == 200
    assets = re.findall(r'"(/static/[^"\n]+)"', response.text)
    assert assets
    for path in assets:
        assert app.test_client().get(path).status_code == 200, path
    page = logged_in(app).get('/manage/add').text
    assert 'socket.io' not in page
    assert 'bw-add.js' in page and 'import-progress.js' in page
