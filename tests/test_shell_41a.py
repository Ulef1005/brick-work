"""App shell, read-only rail and Home Screen contracts, on a 4.0 collection (M.8b, issue #110)."""
import json
import re
from urllib.parse import urlsplit
from pathlib import Path

import pytest
from flask import render_template

from brickwork.web.ui import navigation, navigation_counts
from tests.app4 import app4, client, coll, pair, read, world

ROOT = Path(__file__).resolve().parents[1]


def test_groups_order_and_copy_chooser(app4, client, world):
    app = app4
    with app.test_request_context('/sets/'):
        from flask import session
        session['_user_id'] = 'admin'
        session['_fresh'] = True
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session[SESSION_PASSWORD] = password_mark(app.config['AUTHENTICATION_PASSWORD'])
        app.preprocess_request()
        groups = navigation()
        assert [(name, [link['title'] for link in links]) for name, links in groups] == [
            ('Collection', ['Sets', 'Minifigures', 'Parts', 'Instructions', 'Boxes', 'Gear']),
            ('Workbench', ['Part to Inventory', 'Check Set Parts', 'Part Picker', 'Matcher', 'Orders', 'Storage']),
            ('Planning', ['Wishlist', 'Prices', 'Complete sets']),
            ('Manage', ['Add', 'Tools & Admin'])]
        check = groups[1][1][1]
        assert not check.get('chooser') and check['endpoint'] == 'web.bw_check_parts'
        assert check['url'] == '/workbench/check-parts'
    first = client.get('/collection/jump?q=1000-1').json['results'][0]['copies'][0]
    assert first['check_url'] == '/workbench/check-parts/' + first['id']
    app.config['HIDE_ALL_SETS'] = True
    with app.test_request_context('/tools'):
        app.preprocess_request()
        assert not any(link['title'] in ('Sets', 'Check Set Parts') for _, links in navigation() for link in links)


def test_counts_read_only_one_query_per_request(app4, world, monkeypatch):
    app = app4
    from contextlib import contextmanager
    from brickwork.core import admin
    original = admin.database
    statements = []
    @contextmanager
    def traced(*args, **kwargs):
        with original(*args, **kwargs) as db:
            db.set_trace_callback(statements.append)
            yield db
    monkeypatch.setattr(admin, 'database', traced)
    with app.test_request_context('/'):
        app.preprocess_request()
        first = navigation_counts()
        # 4.0 tables: sets are distinct items with a live copy, loose kinds add their quantities, gear counts items, wishes are rows.
        assert first['Sets'] == 2 and first['Minifigures'] == 1 and first['Parts'] == 12 and first['Instructions'] == 1 and first['Wishlist'] == 2
        assert first['Gear'] == 1 and 'Boxes' not in first and 'Unresolved items' not in first
        assert navigation_counts() is first
        navigation()
        assert len(statements) == 1 and statements[0].lstrip().startswith("SELECT 'Sets'")


@pytest.mark.parametrize('theme,color', [('', '#FAFAF8'), ('?theme=dark', '#1A1816')])
def test_manifest_fields_and_assets(app4, theme, color):
    app = app4
    response = app.test_client().get('/manifest.webmanifest' + theme)
    assert response.status_code == 200 and response.mimetype == 'application/manifest+json'
    data = response.json
    assert (data['name'], data['short_name'], data['start_url'], data['scope'], data['display']) == ('Brick Work', 'Brick Work', '/', '/', 'standalone')
    assert data['theme_color'] == data['background_color'] == color
    assert {'192x192','512x512'} <= {icon['sizes'] for icon in data['icons']}
    assert any(icon['purpose'] == 'maskable' for icon in data['icons'])
    for icon in data['icons']:
        assert app.test_client().get(icon['src']).status_code == 200


def test_service_worker_exclusions_and_precache(app4):
    app = app4
    response = app.test_client().get('/sw.js')
    assert response.status_code == 200 and response.headers['Service-Worker-Allowed'] == '/'
    assert response.headers['Cache-Control'] == 'no-cache'
    source = response.get_data(as_text=True)
    assert "request.method !== 'GET'" in source
    assert '/api/' in source and '/socket.io' in source
    assert 'uploads?' in source and 'data|' in source
    assert "request.mode === 'navigate'" in source and 'fetch(request).catch' in source
    assert "name.startsWith('brickwork-shell-')" in source
    assets = json.loads(re.search(r'const ASSETS = (\[.*?\]);', source, re.S)[1])
    assert '/static/web/toni/offline.html' in assets
    icons = ROOT / 'static/brickwork/icons-ui'
    assert {f'/static/brickwork/icons-ui/{icon.name}' for icon in icons.glob('*.svg')} <= set(assets)
    for asset in assets:
        assert (ROOT / asset.lstrip('/')).is_file(), asset
    assert not any('/data/' in asset or '/api/' in asset for asset in assets)


def test_service_worker_cache_version_tracks_asset_bytes(tmp_path, monkeypatch):
    from flask import Flask
    from brickwork.web import ui
    from brickwork.web.views import shell_worker

    monkeypatch.setattr(ui, 'ROOT', tmp_path)
    static = tmp_path / 'static/web/toni'
    static.mkdir(parents=True)
    worker = static / 'sw.js'
    worker.write_text("const CACHE = 'brickwork-shell-4.1a-__ASSET_VERSION__';\n"
                      'const ASSETS = ["/static/web/toni/b.js", '
                      '"/static/web/toni/a.css"];')
    (static / 'a.css').write_bytes(b'body { color: black; }')
    asset = static / 'b.js'
    asset.write_bytes(b'original')

    def start_app():
        application = Flask(__name__)
        application.add_url_rule('/sw.js', view_func=shell_worker)
        return application.test_client()

    def cache_name(client):
        response = client.get('/sw.js')
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-cache'
        source = response.get_data(as_text=True)
        assert '__ASSET_VERSION__' not in source
        return re.search(r"const CACHE = '(brickwork-shell-4\.1a-[0-9a-f]{16})';", source)[1]

    client = start_app()
    original = cache_name(client)
    assert cache_name(start_app()) == original
    # Manifest order does not change the sorted-path content hash.
    worker.write_text(worker.read_text().replace(
        '"/static/web/toni/b.js", "/static/web/toni/a.css"',
        '"/static/web/toni/a.css", "/static/web/toni/b.js"'))
    assert cache_name(start_app()) == original
    asset.write_bytes(b'modified')
    # An existing app keeps its in-process result until the next app start.
    assert cache_name(client) == original
    changed = cache_name(start_app())
    assert changed != original
    assert cache_name(start_app()) == changed


def test_system_pages_in_shell(app4, client):
    app = app4
    missing = client.get('/missing')
    assert missing.status_code == 404
    html = missing.get_data(as_text=True)
    assert 'Page not found' in html
    assert 'data-web-ui="toni"' in html and 'class="mobile-bottom"' in html
    assert 'web/toni/shell.css' in html and 'id="global-jump"' in html
    with app.test_request_context('/missing'):
        app.preprocess_request()
        html = render_template('web/toni/error.html', error='example')
    assert 'Your data is safe. Try again.' in html
    assert 'data-web-ui="toni"' in html and 'id="global-jump"' in html


def test_worker_and_manifest_routes_are_installed(app4):
    app = app4
    assert 'web.web_manifest' in app.view_functions
    assert 'web.shell_worker' in app.view_functions


def test_home_screen_head_and_local_token_source(client):
    html = client.get('/').get_data(as_text=True)
    assert 'apple-mobile-web-app-capable" content="yes"' in html
    assert 'apple-mobile-web-app-status-bar-style" content="default"' in html
    assert 'viewport-fit=cover' in html
    assert 'web/toni/pwa.js' in html
    assert html.count('apple-touch-startup-image') == 6
    for source in re.findall(r'href="(/static/brickwork/[^"]+)"', html):
        assert (ROOT / urlsplit(source).path.lstrip('/')).is_file()
    tokens = (ROOT / 'static/web/toni/tokens-v2.css').read_text()
    assert '@import' not in tokens and 'fonts.googleapis' not in tokens
    css = (ROOT / 'static/web/toni/shell.css').read_text()
    assert 'grid-template-columns:232px' in css and 'grid-template-columns:64px' in css
    assert 'max-width:1023.98px' in css and 'repeat(4,minmax(0,1fr))' in css
    assert 'var(--tw-safe-top)' in css and 'var(--tw-safe-bottom)' in css


def test_checker_link_keeps_permissions(app4):
    app = app4
    from flask import session
    with app.test_request_context('/tools'):
        app.preprocess_request()
        assert not any(link.get('chooser') for _, links in navigation() for link in links)
    with app.test_request_context('/tools'):
        session['_user_id'] = 'admin'
        session['_fresh'] = True
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session[SESSION_PASSWORD] = password_mark(app.config['AUTHENTICATION_PASSWORD'])
        app.preprocess_request()
        assert not any(link.get('chooser') for _, links in navigation() for link in links)
