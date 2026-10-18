"""#11 Import from BrickTracker pages: upload, preview, import, Undo; the older path stays. Invented data."""
from contextlib import closing
import io
import os
import re
import shutil
import sqlite3

from bs4 import BeautifulSoup

from brickwork.core.connect import connect
from tests.importer.test_importer import legacy  # noqa: F401
from tests.web_fixtures import app, apps, logged_in  # noqa: F401


def prepared(app, legacy):
    with closing(sqlite3.connect(legacy['app_db'])) as db:
        db.execute('PRAGMA user_version=27')
    store = os.environ['BW_DB_PATH']
    with closing(connect(store)):
        pass
    shutil.copy(legacy['catalogues'] / 'blcat.db', os.path.join(os.path.dirname(store), 'bricklink-catalog.db'))
    client = logged_in(app)
    client.get('/manage/import-legacy')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    return client, token, legacy['app_db'].read_bytes()


def page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_upload_preview_import_and_undo(app, legacy):
    client, token, data = prepared(app, legacy)
    upload = page(client.get('/manage/import-legacy'))
    assert upload.select_one('form[enctype="multipart/form-data"] input[type=file][name=file]')
    assert upload.select_one('details.sy-advanced form[action$="/migrate"]')
    response = client.post('/manage/import-legacy/upload', data={'csrf_token': token, 'file': (io.BytesIO(data), 'app.db')},
                           content_type='multipart/form-data')
    assert response.status_code == 302 and '/manage/import-legacy/plan/' in response.location
    preview = page(client.get(response.location))
    assert preview.h1.get_text(strip=True) == 'Preview · app.db'
    ticks = {i['value']: i.has_attr('checked') for i in preview.select('input[name=tick]')}
    assert ticks['copy:copy'] and ticks['stock:loose-part']
    assert 'go to Unresolved figures' in preview.select_one('.bt-summary').get_text()
    assert not list((legacy['app_db'].parent / 'data' / 'imports' / 'uploads').glob('*')) if (legacy['app_db'].parent / 'data' / 'imports' / 'uploads').exists() else True
    plan_id = response.location.rsplit('/', 1)[1]
    keep = [k for k in ticks if k != 'stock:loose-part']
    response = client.post(f'/manage/import-legacy/plan/{plan_id}/apply', data={'csrf_token': token, 'tick': keep})
    assert response.status_code == 302 and 'event=' in response.location
    done = page(client.get(response.location))
    assert 'Imported · 1 sets' in done.get_text()
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute("SELECT count(*) FROM copies WHERE archived_at IS NULL").fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM loose_stock WHERE id='loose-part'").fetchone()
    event = re.search(r'event=(\d+)', response.location)[1]
    client.post('/manage/import-legacy/undo', data={'csrf_token': token, 'event': event})
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute("SELECT count(*) FROM copies WHERE archived_at IS NULL").fetchone()[0] == 0


def test_not_a_bricktracker_file(app, legacy):
    client, token, _ = prepared(app, legacy)
    response = client.post('/manage/import-legacy/upload', data={'csrf_token': token, 'file': (io.BytesIO(b'not sqlite'), 'x.db')},
                           content_type='multipart/form-data')
    assert response.status_code == 302 and response.location.endswith('/manage/import-legacy')
    assert page(client.get(response.location)).select_one('.bk-banner.bk-warning')


def test_first_run_has_the_import_step(app):
    connect(os.environ['BW_DB_PATH']).close()
    soup = page(logged_in(app).get('/collection/sets'))
    steps = soup.select('[data-first-run] .fr-step')
    assert len(steps) == 4 and steps[3].h3.get_text() == 'Or import from BrickTracker'
