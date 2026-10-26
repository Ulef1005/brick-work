"""Error routing and install metadata through the real application factory (ported from test_app_factory, M.8b).

The two API v1 tests stay in `test_app_factory.py` for M.11: v1 answers 410 on 4.0, its problem+json routing comes back with v2."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from tests.app4 import app4, client, coll, pair, read, world

ROOT = Path(__file__).resolve().parents[1]


def test_unknown_web_path_is_the_html_page(client):
    response = client.get('/no-such-page')
    assert response.status_code == 404
    assert response.mimetype == 'text/html'
    assert 'Page not found' in response.get_data(as_text=True)
    assert 'data-web-ui="toni"' in response.get_data(as_text=True)


def test_manifest_urls_all_resolve(client):
    manifest = client.get('/manifest.webmanifest').json
    urls = [manifest['start_url'], manifest['scope']]
    urls += [icon['src'] for icon in manifest['icons']]
    for url in urls:
        assert client.get(urlsplit(url).path).status_code == 200, url
    # A shortcut opens a screen; one not on the 4.0 store yet answers 503 (never 404), the others 200.
    shortcuts = [shortcut['url'] for shortcut in manifest['shortcuts']]
    assert '/manage/add' in shortcuts
    for url in shortcuts:
        assert client.get(urlsplit(url).path).status_code in (200, 503), url
    stored = json.loads((ROOT / 'static/brickwork/manifest.webmanifest').read_text())
    assert [s['url'] for s in stored['shortcuts']] == [s['url'] for s in manifest['shortcuts']]
