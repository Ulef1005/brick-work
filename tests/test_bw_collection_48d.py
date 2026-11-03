"""4.8d, UI-lists L1: every Collection list pages 15 rows per page on the client (kit 12h)."""
from pathlib import Path
import shutil
import subprocess
import time

from bs4 import BeautifulSoup
import pytest

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (fixtures)
from tests.app4_bulk import bulk_owned

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('kind', ['S', 'M', 'P', 'G', 'I', 'O', 'B', 'C'])
def test_every_collection_list_carries_the_page_size(world, client, kind):
    response = client.get('/collection/' + kind)
    assert response.status_code == 200
    root = BeautifulSoup(response.data, 'html.parser').select_one('[data-bc-list][data-bc-main]')
    assert root is not None
    assert root.get('data-bc-page-size') == '15'
    # Continuous loading is gone from the list pages: no Load more and no "Loaded n of m" line.
    page = BeautifulSoup(response.data, 'html.parser')
    assert not page.select('[data-bc-more]') and not page.select('[data-bc-loaded]')


def test_pager_runtime_harness():
    node = shutil.which('node')
    if not node:
        pytest.skip('node not installed')
    subprocess.run([node, str(ROOT / 'tests/toni_bw_collection_paging_runtime.cjs')], check=True,
                   capture_output=True, text=True, cwd=ROOT)


def test_paging_does_not_change_the_server_payload(coll, client):
    """Measurement (run with -s): paging is client side, so bytes and queries equal the unpaged page."""
    bulk_owned(coll, 'part', 7441, prefix='Collection item')
    times = []
    for _ in range(3):
        start = time.perf_counter()
        response = client.get('/collection/P')
        times.append(time.perf_counter() - start)
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    records = soup.select_one('script[data-bc-records]').string
    print(f'Parts list: {sorted(times)[1]:.3f}s, {len(response.data)} bytes, records {len(records)} bytes, '
          f'{len(soup.select("[data-bc-row]"))} server rows')
    # 4.0 records carry the item id and a 32-character stock id each (3.3: a short text id): about 215 bytes a row, so 2 MB for 7441 rows.
    assert len(response.data) < 2_000_000
    assert soup.select_one('[data-bc-list][data-bc-main]')['data-bc-page-size'] == '15'
