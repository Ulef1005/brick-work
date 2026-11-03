"""Shared rail reserves theme space while all navigation remains scrollable (ported from test_shell_45s, M.8b).

Run on the screens ported so far: the home screen, the Sets screen and the wish list (`/collection/wishes`). The paths of screens still
answering 503 stay in `test_shell_45s.py` with their pieces."""
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import pytest

from brickwork.web import ui
from tests.app4 import app4, client, coll, pair, read, world

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path', ['/', '/collection/sets', '/collection/wishes'])
def test_shared_rail_column_and_scroll_contract(app4, client, world, path):
    app = app4
    response = client.get(path)
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


@pytest.mark.parametrize('path', ['/', '/collection/sets'])
def test_brickwork_assets_have_deployed_file_versions(client, world, path):
    soup = BeautifulSoup(client.get(path).data, 'html.parser')
    assets = soup.select('script[src],link[rel="stylesheet"]')
    assert assets
    for asset in assets:
        url = urlsplit(asset.get('src') or asset['href'])
        assert parse_qs(url.query)['v'] == [str((ROOT / 'static' / url.path.removeprefix('/static/')).stat().st_mtime_ns)]


def test_asset_url_changes_with_deployed_file_mtime(app4, monkeypatch):
    from types import SimpleNamespace
    original = Path.stat
    clock = [101]

    def stat(path, *args, **kwargs):
        if path.name == 'bw-planning.js':
            return SimpleNamespace(st_mtime_ns=clock[0])
        return original(path, *args, **kwargs)
    with app4.test_request_context('/'):
        monkeypatch.setattr(Path, 'stat', stat)
        first = ui.bw_static('web/toni/bw-planning.js')
        clock[0] = 102
        second = ui.bw_static('web/toni/bw-planning.js')
        assert first.endswith('?v=101') and second.endswith('?v=102')
