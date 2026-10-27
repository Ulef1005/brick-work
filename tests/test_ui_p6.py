"""UI-P6 on the 4.0 store (M.8i part 1, issue #110): Tools & Admin shell, hub tiles, system pages, no old breadcrumb.

The Import from BrickTracker page header (M.8j) moved to `test_ui_p6_import.py`."""
import pytest
from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

PAGES = ['tools', 'about', 'catalogues', 'jobs', 'refresh', 'unresolved', 'statistics', 'values',
         'database', 'settings', 'appearance', 'history', 'instructions', 'tokens']
HUB_TARGETS = ['/manage/about', '/manage/refresh', '/manage/catalogues', '/manage/jobs', '/manage/instructions',
               '/manage/history', '/manage/unresolved', '/manage/statistics', '/manage/values',
               '/manage/tokens', '/manage/database', '/manage/settings', '/manage/appearance']


def soup_of(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


@pytest.mark.parametrize('page', PAGES)
def test_p6_pages_have_header_and_no_breadcrumb(client, world, page):
    soup = soup_of(client, '/manage/' + page)
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


def test_p6_hub_tiles_link_to_every_page(client, world):
    soup = soup_of(client, '/manage/tools')
    hrefs = [a['href'] for a in soup.select('.bw-hub a.bw-hub-row')]
    for target in HUB_TARGETS:
        assert target in hrefs, target
    assert any(h.endswith('/manage/import-legacy') or 'import' in h for h in hrefs)
    labels = [h.get_text() for h in soup.select('.bw-hub h2.bw-label')]
    assert labels == ['Refresh', 'Instructions', 'Reports', 'Insight', 'Administration']
    assert ' stale' in soup.select_one('.bw-hub').get_text()


def test_p6_settings_controls(client, world):
    soup = soup_of(client, '/manage/settings')
    assert not soup.select('select[name=retail_country]')
    assert soup.select('.bw-seg input[name=retail_country][value=DE]')
    assert soup.select('.bw-seg input[name=scope]')
    assert soup.select('input[type=checkbox][role=switch][name=types]')
    assert not soup.select('.bw-seg input[name=source]')                                # a refresh follows the source order: no source to pick


def test_p6_missing_page_system_page(client):
    response = client.get('/missing')
    assert response.status_code == 404
    soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    assert soup.select_one('.system-page h1').get_text() == 'That page is not here'
    assert 'Back to sets' in soup.select_one('.system-page .button.primary').get_text()
    assert 'Page not found' in soup.select_one('.system-code').get_text()
    assert not soup.select('.breadcrumb')


def test_p6_error_system_page_and_exception_details(app4, client):
    @app4.route('/boom')
    def boom():
        raise KeyError('set 7286-1')
    app4.config['TESTING'] = False
    app4.config['PROPAGATE_EXCEPTIONS'] = False
    soup = BeautifulSoup(client.get('/boom').get_data(as_text=True), 'html.parser')
    assert soup.select_one('.system-page h1').get_text() == 'Something went wrong'
    assert soup.select_one('.system-code').get_text() == 'server · 500'
    assert not soup.select('.system-trace') and 'KeyError' not in str(soup)
    app4.config['DEBUG'] = True
    response = client.get('/boom')
    soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    assert response.status_code == 500
    assert 'KeyError' in soup.select_one('.system-code').get_text()
    assert 'Traceback' in soup.select_one('.system-trace').get_text()


def test_hub_rows_say_what_each_option_does(client, world):
    # Every Tools & Admin row has a title and one short sentence under it.
    soup = soup_of(client, '/manage/tools')
    rows = soup.select('a.bw-hub-row')
    assert rows and all(r.select_one('.bw-hub-text>.bw-hub-title') for r in rows)
    notes = [r.select_one('.bw-hub-note') for r in rows]
    assert all(n and n.get_text(strip=True).endswith('.') for n in notes)
    assert all(len(n.get_text().split()) <= 16 for n in notes)


def test_about_carries_the_notices(client, world):
    # BrickLink's API terms want its notice on the application, verbatim; the LEGO disclaimer as in the README.
    soup = soup_of(client, '/manage/about')
    assert soup.select_one('[data-about-bricklink]').get_text() == (
        "The term 'BrickLink' is a trademark of the LEGO Group BrickLink. This application uses the BrickLink API "
        "but is not endorsed or certified by LEGO BrickLink, Inc.")
    assert soup.select_one('[data-about-lego]').get_text().startswith('LEGO® is a trademark of the LEGO Group of companies')
    assert soup.select_one('a[href="https://github.com/Ulef1005/brick-work"]')
