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
    '/workbench/storage', '/planning/wishlist',
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


@pytest.mark.parametrize('path', ['/planning/prices', '/workbench/part-to-inventory',
                                 '/manage/tools', '/workbench/storage'])
def test_brickwork_assets_have_deployed_file_versions(app, bw, path):
    from urllib.parse import parse_qs
    soup = BeautifulSoup(logged_in(app).get(path).data, 'html.parser')
    assets = soup.select('script[src],link[rel="stylesheet"]')
    assert assets
    for asset in assets:
        url = urlsplit(asset.get('src') or asset['href'])
        assert parse_qs(url.query)['v'] == [str((Path(app.static_folder) / url.path.removeprefix('/static/')).stat().st_mtime_ns)]

