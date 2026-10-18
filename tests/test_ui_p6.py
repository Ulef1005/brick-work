"""UI-P6: Tools & Admin shell, hub tiles, system pages, no old breadcrumb."""
import pytest
from bs4 import BeautifulSoup

from tests.web_fixtures import app, apps, logged_in
from tests.test_bw_admin import bw  # noqa: F401  (fixture)

PAGES = ['tools', 'catalogues', 'jobs', 'refresh', 'unresolved', 'statistics', 'values',
         'database', 'settings', 'appearance', 'history', 'instructions', 'tokens']
HUB_TARGETS = ['/manage/refresh', '/manage/catalogues', '/manage/jobs', '/manage/instructions',
               '/manage/history', '/manage/unresolved', '/manage/statistics', '/manage/values',
               '/manage/tokens', '/manage/database', '/manage/settings', '/manage/appearance']


def soup_of(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


@pytest.mark.parametrize('page', PAGES)
def test_p6_pages_have_header_and_no_breadcrumb(app, bw, page):
    soup = soup_of(logged_in(app), '/manage/' + page)
    assert not soup.select('.breadcrumb')
    assert soup.select_one('main h1')
    if page == 'tokens':
        assert soup.select_one('main .bw-back')
    elif page == 'tools':
        head = soup.select_one('.bw-page-head')
        assert head.h1.get_text() == 'Tools & Admin' and not head.select('.bw-back')
    else:
        head = soup.select_one('.bw-page-head')
        assert head and head.select_one('a.bw-back[href="/manage/tools"]')


def test_p6_hub_tiles_link_to_every_page(app, bw):
    soup = soup_of(logged_in(app), '/manage/tools')
    hrefs = [a['href'] for a in soup.select('.bw-hub a.bw-hub-row')]
    for target in HUB_TARGETS:
        assert target in hrefs, target
    assert any(h.endswith('/manage/import-legacy') or 'import' in h for h in hrefs)
    labels = [h.get_text() for h in soup.select('.bw-hub h2.bw-label')]
    assert labels == ['Refresh', 'Instructions', 'Reports', 'Insight', 'Administration']
    assert ' stale' in soup.select_one('.bw-hub').get_text()


def test_p6_settings_controls(app, bw):
    soup = soup_of(logged_in(app), '/manage/settings')
    assert not soup.select('select[name=retail_country]')
    assert soup.select('.bw-seg input[name=retail_country][value=DE]')
    assert soup.select('.bw-seg input[name=scope]')
    assert soup.select('input[type=checkbox][role=switch][name=types]')


def test_p6_missing_page_system_page(app):
    response = logged_in(app).get('/missing')
    assert response.status_code == 404
    soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    assert soup.select_one('.system-page h1').get_text() == 'That page is not here'
    assert 'Back to sets' in soup.select_one('.system-page .button.primary').get_text()
    assert 'Page not found' in soup.select_one('.system-code').get_text()
    assert not soup.select('.breadcrumb')


def test_p6_error_system_page_and_exception_details(app):
    @app.route('/boom')
    def boom():
        raise KeyError('set 7286-1')
    app.config['TESTING'] = False
    app.config['PROPAGATE_EXCEPTIONS'] = False
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/boom').get_data(as_text=True), 'html.parser')
    assert soup.select_one('.system-page h1').get_text() == 'Something went wrong'
    assert soup.select_one('.system-code').get_text() == 'server · 500'
    assert not soup.select('.system-trace') and 'KeyError' not in str(soup)
    app.config['DEBUG'] = True
    response = client.get('/boom')
    soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    assert response.status_code == 500
    assert 'KeyError' in soup.select_one('.system-code').get_text()
    assert 'Traceback' in soup.select_one('.system-trace').get_text()


def test_p6_import_page_header(app, bw):
    soup = soup_of(logged_in(app), '/manage/import-legacy')
    assert not soup.select('.breadcrumb')
    assert soup.select_one('.bw-page-head h1').get_text() == 'Import from BrickTracker'
    assert soup.select_one('.bw-page-head a.bw-back[href="/manage/tools"]')


def test_hub_rows_say_what_each_option_does(app, bw):
    # Every Tools & Admin row has a title and one short sentence under it.
    soup = soup_of(logged_in(app), '/manage/tools')
    rows = soup.select('a.bw-hub-row')
    assert rows and all(r.select_one('.bw-hub-text>.bw-hub-title') for r in rows)
    notes = [r.select_one('.bw-hub-note') for r in rows]
    assert all(n and n.get_text(strip=True).endswith('.') for n in notes)
    assert all(len(n.get_text().split()) <= 16 for n in notes)
