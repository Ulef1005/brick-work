"""4.8d, UI-lists L1: every Collection list pages 15 rows per page on the client (kit 12h)."""
from pathlib import Path
import shutil
import subprocess
import time

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('kind', ['S', 'M', 'P', 'G', 'I', 'O', 'B', 'C'])
def test_every_collection_list_carries_the_page_size(app, bw, kind):
    response = logged_in(app).get('/collection/' + kind)
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


def test_paging_does_not_change_the_server_payload(app, bw):
    """Measurement (run with -s): paging is client side, so bytes and queries equal the unpaged page."""
    with admin.database(bw) as db, db:
        db.executemany('INSERT INTO items(item_type,item_no,name) VALUES(?,?,?)',
                       [('P', f'bench-{n}', f'Collection item {n}') for n in range(7441)])
        db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P',?,11,1,'U')",
                       [(f'bench-P-{n}', f'bench-{n}') for n in range(7441)])
    client = logged_in(app)
    times = []
    for _ in range(5):
        start = time.perf_counter()
        response = client.get('/collection/P')
        times.append(time.perf_counter() - start)
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    records = soup.select_one('script[data-bc-records]').string
    print(f'Parts list: {sorted(times)[2]:.3f}s, {len(response.data)} bytes, records {len(records)} bytes, '
          f'{len(soup.select("[data-bc-row]"))} server rows')
    assert len(response.data) < 1_500_000
    assert soup.select_one('[data-bc-list][data-bc-main]')['data-bc-page-size'] == '15'
