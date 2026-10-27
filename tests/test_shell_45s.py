"""Shared rail reserves theme space while all navigation remains scrollable, on the ported Workbench screens (M.8e, issue #110).

The planning, prices and Tools and Admin paths of the 3.3 file are in `test_shell_45s_later.py` (M.8g)."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import pytest

from brickwork.web import ui
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)

PORTED = ['/workbench/storage', '/workbench/part-picker', '/workbench/matcher', '/workbench/part-to-inventory']


@pytest.mark.parametrize('path', PORTED)
def test_shared_rail_column_and_scroll_contract(world, app4, client, path):
    response = client.get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    rail = soup.select_one('.layout > .rail')
    nav, theme = rail.find_all(recursive=False)
    assert nav.name == 'nav' and nav['aria-label'] == 'Main'
    assert theme['class'] == ['rail-theme']
    assert [b['data-theme-mode'] for b in theme.select('button')] == ['system', 'light', 'dark']
    assert not nav.select('.theme-segments')
    with app4.test_request_context(path):
        # The same logged-in view as the page: counts (and the item kinds they add) show only after login.
        from flask import session
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session['_user_id'] = 'admin'
        session[SESSION_PASSWORD] = password_mark(app4.config['AUTHENTICATION_PASSWORD'])
        groups = ui.navigation()
    assert len(nav.select('.navgroup')) == len(groups)
    assert len(nav.select('a')) == sum(len(links) for _, links in groups)
    for target in ['/workbench/orders', '/workbench/storage', '/planning/wishlist', '/manage/tools']:
        assert nav.select_one(f'a[href="{target}"]')
    # Shell rules load after page assets and apply at both rail widths.
    assert urlsplit(soup.select('link[rel="stylesheet"]')[-1]['href']).path.endswith('/shell.css')


@pytest.mark.parametrize('path', ['/workbench/part-to-inventory', '/workbench/storage'])
def test_brickwork_assets_have_deployed_file_versions(world, app4, client, path):
    soup = BeautifulSoup(client.get(path).data, 'html.parser')
    assets = soup.select('script[src],link[rel="stylesheet"]')
    assert assets
    for asset in assets:
        url = urlsplit(asset.get('src') or asset['href'])
        assert parse_qs(url.query)['v'] == [str((Path(app4.static_folder) / url.path.removeprefix('/static/')).stat().st_mtime_ns)]
