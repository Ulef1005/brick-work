"""Shared rail reserves theme space while all navigation remains scrollable."""
import re
from pathlib import Path
from urllib.parse import urlsplit

from brickwork.web import ui

from bs4 import BeautifulSoup
import pytest

from tests.test_bw_collection import bw
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.test_bw_admin import reset_shell_metadata_after_test

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path', [
    '/', '/workbench/storage', '/planning/wishlist',
    '/planning/prices', '/planning/complete-sets',
])
def test_shared_rail_column_and_scroll_contract(app, bw, path):
    response = logged_in(app).get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    rail = soup.select_one('.layout > .rail')
    nav, theme = rail.find_all(recursive=False)
    assert nav.name == 'nav' and nav['aria-label'] == 'Main'
    assert theme['class'] == ['rail-theme']
    assert [b['data-theme-mode'] for b in theme.select('button')] == [
        'system', 'light', 'dark']
    assert not nav.select('.theme-segments')
    with app.test_request_context(path):
        # The same logged-in view as the page: counts (and the item kinds they add) show only after login.
        from flask import session
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session['_user_id'] = 'admin'
        session[SESSION_PASSWORD] = password_mark(app.config['AUTHENTICATION_PASSWORD'])
        groups = ui.navigation()
    assert len(nav.select('.navgroup')) == len(groups)
    assert len(nav.select('a')) == sum(len(links) for _, links in groups)
    for target in ['/workbench/orders', '/workbench/storage',
                   '/planning/wishlist', '/manage/tools']:
        assert nav.select_one(f'a[href="{target}"]')
    # Shell rules load after page assets and apply at both rail widths.
    assert urlsplit(soup.select('link[rel="stylesheet"]')[-1]['href']).path.endswith('/shell.css')


def test_rail_css_source_checks():
    # These assertions inspect CSS source; browser geometry is checked after deploy.
    css = (ROOT / 'static/web/toni/shell.css').read_text()

    def rule(selector):
        body = re.search(re.escape(selector) + r'\{([^}]+)\}', css)[1]
        return dict(declaration.split(':', 1) for declaration in body.split(';')
                    if declaration)

    column = rule('.rail')
    assert column['display'] == 'flex' and column['flex-direction'] == 'column'
    assert column['height'] == 'calc(100dvh - 56px - var(--tw-safe-top))'
    assert column['min-height'] == '0'
    scrolling = rule('.rail>nav')
    assert scrolling['display'] == 'flex' and scrolling['flex-direction'] == 'column'
    assert scrolling['flex'] == '1 1 0' and scrolling['min-height'] == '0'
    assert scrolling['overflow-y'] == 'auto' and scrolling['overflow-x'] == 'hidden'
    assert rule('.rail .navgroup')['flex'] == 'none'
    assert rule('.rail-theme')['flex'] == 'none'
    assert '@media(max-width:1023.98px){.layout' in css
    assert '.rail{display:none}' in css


@pytest.mark.parametrize('path', ['/', '/planning/prices', '/workbench/part-to-inventory',
                                 '/manage/tools', '/workbench/storage'])
def test_brickwork_assets_have_deployed_file_versions(app, bw, path):
    from urllib.parse import parse_qs
    soup = BeautifulSoup(logged_in(app).get(path).data, 'html.parser')
    assets = soup.select('script[src],link[rel="stylesheet"]')
    assert assets
    for asset in assets:
        url = urlsplit(asset.get('src') or asset['href'])
        assert parse_qs(url.query)['v'] == [str((Path(app.static_folder) / url.path.removeprefix('/static/')).stat().st_mtime_ns)]


def test_asset_url_changes_with_deployed_file_mtime(app, monkeypatch):
    from types import SimpleNamespace
    original = Path.stat
    clock = [101]
    def stat(path, *args, **kwargs):
        if path.name == 'bw-planning.js':
            return SimpleNamespace(st_mtime_ns=clock[0])
        return original(path, *args, **kwargs)
    with app.test_request_context('/'):
        monkeypatch.setattr(Path, 'stat', stat)
        first = ui.bw_static('web/toni/bw-planning.js')
        clock[0] = 102
        second = ui.bw_static('web/toni/bw-planning.js')
        assert first.endswith('?v=101') and second.endswith('?v=102')
