"""The shell navigation lists the active group in the sub row and every group in the top bar (ported from test_shell_45s, M.8b; the sidebar went with #492).

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
def test_shell_navigation_follows_the_active_group(app4, client, world, path):
    app = app4
    response = client.get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    nav = soup.select_one('header.top nav.tabs')
    assert nav['aria-label'] == 'Main'
    assert not soup.select('.layout > .rail, .rail-theme')       # no sidebar, no theme picker in the shell (the theme is the Appearance page)
    with app.test_request_context(path):
        # The same logged-in view as the page: counts (and the item kinds they add) show only after login.
        from flask import session
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session['_user_id'] = 'admin'
        session[SESSION_PASSWORD] = password_mark(app.config['AUTHENTICATION_PASSWORD'])
        groups = ui.navigation()
    assert [a.text for a in nav.select('a.tab')] == [name for name, _ in groups]
    active = [links for name, links in groups if name == nav.select_one('a.tab.on').text][0]
    for row in ('nav.sub', 'nav.psub'):
        assert [a['href'] for a in soup.select(f'{row} a')] == [link['url'] for link in active]
    # Every group is reachable from the top bar: each tab points at the first entry of its group.
    assert [a['href'] for a in nav.select('a.tab')] == [links[0]['url'] for _, links in groups]
    # Shell rules load after the page assets.
    assert urlsplit(soup.select('link[rel="stylesheet"]')[-1]['href']).path.endswith(('/shell.css', '/b-prime.css'))


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
