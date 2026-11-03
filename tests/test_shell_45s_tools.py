"""Deployed file versions on the Tools & Admin page (on the 4.0 store: M.8i part 1). Split out of test_shell_45s_later.py in M.8g."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)


def test_brickwork_assets_have_deployed_file_versions(app4, client, world):
    soup = BeautifulSoup(client.get('/manage/tools').data, 'html.parser')
    assets = soup.select('script[src],link[rel="stylesheet"]')
    assert assets
    for asset in assets:
        url = urlsplit(asset.get('src') or asset['href'])
        assert parse_qs(url.query)['v'] == [str((Path(app4.static_folder) / url.path.removeprefix('/static/')).stat().st_mtime_ns)]
