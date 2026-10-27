"""UI-P6: the Import from BrickTracker page header. Split off from test_ui_p6.py by M.8i part 1, which ports the rest of Tools & Admin; the
importer and its page are rewritten by M.8j (still the 3.3 text)."""
from bs4 import BeautifulSoup

from tests.web_fixtures import app, apps, logged_in
from tests.test_bw_admin_identity import bw  # noqa: F401  (fixture: still the 3.3 collection)


def soup_of(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def test_p6_import_page_header(app, bw):
    soup = soup_of(logged_in(app), '/manage/import-legacy')
    assert not soup.select('.breadcrumb')
    assert soup.select_one('.bw-page-head h1').get_text() == 'Import from BrickTracker'
    assert soup.select_one('.bw-page-head a.bw-back[href="/manage/tools"]')
