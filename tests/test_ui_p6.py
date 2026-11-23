"""UI-P6 on the 4.0 store (M.8i part 1, issue #110): Tools & Admin shell, hub tiles, system pages, no old breadcrumb.

The Import from BrickTracker page header (M.8j) moved to `test_ui_p6_import.py`."""
import pytest
from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

PAGES = ['tools', 'about', 'catalogues', 'jobs', 'refresh', 'unresolved', 'statistics', 'values',
         'database', 'settings', 'appearance', 'history', 'instructions', 'tokens']
HUB_TARGETS = ['/manage/about', '/manage/catalogues', '/manage/jobs', '/manage/instructions',
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
    hrefs = [a['href'].split('#')[0] for a in soup.select('.bw-hub a.bw-hub-row')]
    for target in HUB_TARGETS:
        assert target in hrefs, target
    assert any(h.endswith('/manage/import-legacy') or 'import' in h for h in hrefs)
    labels = [h.get_text() for h in soup.select('.bw-hub h2.bw-label')]
    assert labels == ['Refresh', 'Your collection', 'Settings', 'Maintenance', 'About']         # #460: groups by what you do; the intro card has no heading
    cards = [(next(c.select_one('.bw-hub-eyebrow').stripped_strings), c.select_one('.bw-hub-title').get_text()) for c in soup.select('.bw-hub-top a.bw-hub-card')]
    assert cards == [('Get started', 'Get started')]                 # #83: while set-up is open the card is on top, the whole card a link


def test_493_hub_is_built_to_frame_01(client, world):
    soup = soup_of(client, '/manage/tools')
    assert soup.select_one('.bw-hub-head .bw-hub-kicker').get_text() == 'Manage'      # #493: the page names its place above the heading
    assert [c.get_text() for c in soup.select('.bw-refresh-cell .bw-refresh-label')] == ['Prices', 'Pictures']
    tape = soup.select_one('.bw-hub-top a.bw-hub-card .bw-hub-eyebrow')
    assert tape.select_one('.bw-hub-signal').get_text().endswith('done')          # the progress sits on the tape, not in the card body
    assert soup.select_one('.bw-refresh-fig .bw-refresh-num') is not None and soup.select_one('.bw-refresh-fig .bw-refresh-line') is not None

def test_p6_settings_controls(client, world):
    soup = soup_of(client, '/manage/settings')
    assert not soup.select('select[name=retail_country]')
    assert soup.select('.bw-seg input[name=retail_country][value=DE]')
    assert not soup.select('.bw-seg input[name=scope]') and not soup.select('[data-picture-dialog]')          # #460: the picture dialog is on Tools & Admin
    assert soup_of(client, '/manage/tools').select('.bw-seg input[name=scope]')
    assert not soup.select('.bw-seg input[name=source]')                                # a refresh follows the source order: no source to pick


HEADINGS = {'A': 'This page is the missing piece', 'B': 'Drawer 404 is empty', 'C': 'We looked everywhere'}   # the approved 404 pages (#503, 23.11.)


@pytest.mark.parametrize('variant', ['A', 'B', 'C'])
def test_each_404_version_renders(client, monkeypatch, variant):
    """Every version keeps the shell, Back to sets and the code line; only the heading, the lead and the picture change."""
    import brickwork.app as application
    monkeypatch.setattr(application.random, 'choice', lambda options: variant)
    response = client.get('/missing')
    assert response.status_code == 404
    soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    page = soup.select_one('.system-page.sys-page')
    assert page['data-system-variant'] == variant
    assert page.select_one('h1').get_text() == HEADINGS[variant]
    assert page.select_one('.sys-lead').get_text()
    assert [a.get_text() for a in page.select('.sys-actions a')] == ['Back to sets']
    assert page.select_one('.sys-code').get_text() == 'Page not found · 404'
    assert page.select_one('.sys-art svg, .sys-art .sys-checklist')
    assert not soup.select('.breadcrumb')


def test_the_404_rotation_reaches_every_version(app4):
    """The page is picked at random per response, so over many responses each version comes up; `?variant=` is honoured only by the
    screen gate's app (SYSTEM_VARIANT_FROM_QUERY)."""
    from brickwork.app import not_found_variant, NOT_FOUND_VARIANTS
    with app4.test_request_context('/missing?variant=C'):
        seen = {not_found_variant(app4) for _ in range(300)}
        assert seen == set(NOT_FOUND_VARIANTS)
        app4.config['SYSTEM_VARIANT_FROM_QUERY'] = True
        assert {not_found_variant(app4) for _ in range(20)} == {'C'}
    app4.config['SYSTEM_VARIANT_FROM_QUERY'] = False


def test_a_503_keeps_its_own_code_and_message(app4, client):
    """The database-unavailable views render the error page with status 503: the drawer, the code line and the variant name that
    status, and the message says what is wrong (review of #635)."""
    from flask import render_template
    @app4.route('/db-gone')
    def db_gone():
        return render_template('web/toni/error.html', error='Brick Work database is not available. Check BW_DB_PATH and try again.', status=503), 503
    response = client.get('/db-gone')
    assert response.status_code == 503
    page = BeautifulSoup(response.get_data(as_text=True), 'html.parser').select_one('.system-page.sys-page')
    assert page['data-system-variant'] == '503'
    assert page.select_one('.sys-code').get_text() == 'Brick Work database is not available. Check BW_DB_PATH and try again. · 503'
    assert '503 · JAMMED' in page.select_one('.sys-art').get_text()


def test_an_unknown_404_variant_falls_back_to_the_first(app4, client):
    from flask import render_template
    @app4.route('/odd-variant')
    def odd_variant():
        return render_template('web/toni/error.html', error='Page not found', status=404, variant=None), 404
    html = client.get('/odd-variant').get_data(as_text=True)
    assert HEADINGS['A'] in html and 'data-system-variant="A"' in html


def test_p6_error_system_page_and_exception_details(app4, client):
    @app4.route('/boom')
    def boom():
        raise KeyError('set 7286-1')
    app4.config['TESTING'] = False
    app4.config['PROPAGATE_EXCEPTIONS'] = False
    soup = BeautifulSoup(client.get('/boom').get_data(as_text=True), 'html.parser')
    page = soup.select_one('.system-page.sys-page')
    assert page.select_one('h1').get_text() == 'This drawer is stuck'
    assert page.select_one('.sys-lead').get_text() == 'Your data is safe. Try again.'
    assert [a.get_text() for a in page.select('.sys-actions a')] == ['Try again', 'Back to sets']
    assert page.select_one('.sys-code').get_text() == 'Something went wrong · 500'
    assert '500 · JAMMED' in page.select_one('.sys-art').get_text()
    assert not soup.select('.system-trace') and 'KeyError' not in str(soup)
    app4.config['DEBUG'] = True
    response = client.get('/boom')
    soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    assert response.status_code == 500
    assert 'KeyError' in soup.select_one('.sys-code').get_text()
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
