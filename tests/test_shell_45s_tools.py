"""Deployed file versions on the Tools & Admin page: split out of test_shell_45s_later.py in M.8g (issue #110); still the 3.3 text, waits for
Tools & Admin (M.8i)."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from tests.test_bw_collection import bw
from tests.web_fixtures import app, logged_in
from tests.test_bw_admin import reset_shell_metadata_after_test


def test_brickwork_assets_have_deployed_file_versions(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/manage/tools').data, 'html.parser')
    assets = soup.select('script[src],link[rel="stylesheet"]')
    assert assets
    for asset in assets:
        url = urlsplit(asset.get('src') or asset['href'])
        assert parse_qs(url.query)['v'] == [str((Path(app.static_folder) / url.path.removeprefix('/static/')).stat().st_mtime_ns)]
