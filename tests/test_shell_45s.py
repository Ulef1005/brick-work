"""The shell navigation lists the active group in the sub row and every group in the top bar, on the ported Workbench and planning screens (M.8e, M.8g; issue #110).

The Tools and Admin path of the 3.3 file is in `test_shell_45s_tools.py` (M.8i)."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import pytest

from brickwork.web import ui
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)

PORTED = ['/workbench/storage', '/workbench/part-picker', '/workbench/matcher', '/workbench/part-to-inventory',
          '/planning/wishlist', '/planning/prices', '/planning/complete-sets']


@pytest.mark.parametrize('path', PORTED)
def test_shell_navigation_follows_the_active_group(world, app4, client, path):
    response = client.get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    nav = soup.select_one('header.top nav.tabs')
    assert nav['aria-label'] == 'Main'
    assert not soup.select('.layout > .rail, .rail-theme')       # no sidebar, no theme picker in the shell (the theme is the Appearance page)
    with app4.test_request_context(path):
        # The same logged-in view as the page: counts (and the item kinds they add) show only after login.
        from flask import session
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session['_user_id'] = 'admin'
        session[SESSION_PASSWORD] = password_mark(app4.config['AUTHENTICATION_PASSWORD'])
        groups = ui.navigation()
    assert [a.text for a in nav.select('a.tab')] == [name for name, _ in groups]
    active = [links for name, links in groups if name == nav.select_one('a.tab.on').text][0]
    for row in ('nav.sub', 'nav.psub'):
        assert [a['href'] for a in soup.select(f'{row} a')] == [link['url'] for link in active]
    # Every group is reachable from the top bar: each tab points at the first entry of its group.
    assert [a['href'] for a in nav.select('a.tab')] == [links[0]['url'] for _, links in groups]
    # Shell rules load after the page assets.
    assert urlsplit(soup.select('link[rel="stylesheet"]')[-1]['href']).path.endswith(('/shell.css', '/b-prime.css'))


@pytest.mark.parametrize('path', ['/workbench/part-to-inventory', '/workbench/storage', '/planning/prices', '/planning/wishlist', '/planning/complete-sets'])
def test_brickwork_assets_have_deployed_file_versions(world, app4, client, path):
    soup = BeautifulSoup(client.get(path).data, 'html.parser')
    assets = soup.select('script[src],link[rel="stylesheet"]')
    assert assets
    for asset in assets:
        url = urlsplit(asset.get('src') or asset['href'])
        assert parse_qs(url.query)['v'] == [str((Path(app4.static_folder) / url.path.removeprefix('/static/')).stat().st_mtime_ns)]
