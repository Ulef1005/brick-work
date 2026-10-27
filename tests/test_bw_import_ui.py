"""#11 Import from BrickTracker pages on a 4.0 collection: upload, preview, import, Undo (M.8j, issue #110). Invented data.

The "Build a new database instead" form and its path checks (#61) went with `brickwork migrate` (decision 4 of #110)."""
from contextlib import closing
import io
import re

from bs4 import BeautifulSoup

from brickwork.core.connect import connect
from tests.app4 import app4, client, pair  # noqa: F401  (fixtures)
from tests.importer.test_bricktracker_import import upstream


def page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def token(client):
    client.get('/manage/import-legacy')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def count(pair, table):
    with closing(connect(pair, read_only=True)) as db:
        return db.execute(f'SELECT count(*) FROM {table} WHERE archived_at IS NULL').fetchone()[0]


def test_upload_preview_import_and_undo(client, pair, tmp_path):
    csrf = token(client)
    data = upstream(tmp_path / 'app.db').read_bytes()
    upload = page(client.get('/manage/import-legacy'))
    assert upload.select_one('form[enctype="multipart/form-data"] input[type=file][name=file]')
    assert not upload.select('details.sy-advanced') and not upload.select('form[action$="/migrate"]')
    response = client.post('/manage/import-legacy/upload', data={'csrf_token': csrf, 'file': (io.BytesIO(data), 'app.db')}, content_type='multipart/form-data')
    assert response.status_code == 302 and '/manage/import-legacy/plan/' in response.location
    preview = page(client.get(response.location))
    assert preview.h1.get_text(strip=True) == 'Preview · app.db'
    ticks = {i['value']: i.has_attr('checked') for i in preview.select('input[name=tick]')}
    assert ticks['copy:copy-1'] and ticks['copy:copy-2'] and ticks['stock:loose-1'] and ticks['lot:lot-1']
    assert '3 items left out' in preview.select_one('.bt-summary').get_text()
    assert 'The catalogue does not know' in preview.get_text() and '999999-1' in preview.get_text()
    assert not list((pair.parent / 'data' / 'imports' / 'uploads').glob('*'))               # the upload is deleted either way
    plan_id = response.location.rsplit('/', 1)[1]
    keep = [k for k in ticks if k != 'stock:loose-1']
    response = client.post(f'/manage/import-legacy/plan/{plan_id}/apply', data={'csrf_token': csrf, 'tick': keep})
    assert response.status_code == 302 and 'event=' in response.location
    done = page(client.get(response.location))
    assert 'Imported · 2 sets' in done.get_text()
    assert count(pair, 'copy') == 2
    with closing(connect(pair, read_only=True)) as db:
        assert not db.execute("SELECT 1 FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key='3001' AND s.kind='part' AND s.archived_at IS NULL").fetchone()
    event = re.search(r'event=(\d+)', response.location)[1]
    client.post('/manage/import-legacy/undo', data={'csrf_token': csrf, 'event': event})
    assert count(pair, 'copy') == 0 and count(pair, 'wish') == 0


def test_not_a_bricktracker_file(client):
    csrf = token(client)
    response = client.post('/manage/import-legacy/upload', data={'csrf_token': csrf, 'file': (io.BytesIO(b'not sqlite'), 'x.db')}, content_type='multipart/form-data')
    assert response.status_code == 302 and response.location.endswith('/manage/import-legacy')
    assert page(client.get(response.location)).select_one('.bk-banner.bk-warning')


def test_the_migrate_route_is_gone(client):
    csrf = token(client)
    assert client.post('/manage/import-legacy/migrate', data={'csrf_token': csrf, 'app': 'old.db'}).status_code in (404, 405)


def test_first_run_has_the_import_step(client):
    soup = page(client.get('/collection/sets'))
    steps = soup.select('[data-first-run] .fr-step')
    assert len(steps) == 4 and steps[3].h3.get_text() == 'Or import from BrickTracker'


def test_the_page_header(client):
    """Moved here from test_ui_p6_import.py (UI-P6): the Import from BrickTracker page header."""
    soup = page(client.get('/manage/import-legacy'))
    assert not soup.select('.breadcrumb')
    assert soup.select_one('.bw-page-head h1').get_text() == 'Import from BrickTracker'
    assert soup.select_one('.bw-page-head a.bw-back[href="/manage/tools"]')
