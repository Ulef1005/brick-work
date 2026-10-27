"""Review 5 frame contracts on the migrated database fixture (M.8d: the instruction screens). The Add frames moved to `test_bw_add.py` (M.8c)."""
from pathlib import Path
from bs4 import BeautifulSoup
from tests.test_bw_collection import bw
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.test_bw_admin import reset_shell_metadata_after_test

ROOT = Path(__file__).resolve().parents[1]


def test_instruction_review_header_and_upload(app, bw):
    from io import BytesIO
    from brickwork.core import admin
    client = logged_in(app)
    with admin.database(bw) as db:
        booklet = db.execute("SELECT item_no FROM items WHERE item_type='I' LIMIT 1").fetchone()[0]
        total = db.execute("SELECT count(*) FROM items WHERE item_type='I'").fetchone()[0]
    soup = BeautifulSoup(client.get('/manage/instructions').data, 'html.parser')
    assert soup.select_one('.bw-page-head h1').text == f'0 of {total} booklets have a PDF'
    assert soup.select_one('.bw-page-head p').text == 'Fetch, upload or rename'
    assert not soup.select('[data-bw-search], [data-bw-filter], [data-bw-sort]')
    disclosure = soup.select_one('.bw-instructions-upload')
    assert disclosure.name == 'details' and not disclosure.has_attr('open')
    assert disclosure.select_one('summary').text == 'Upload a PDF'
    assert {i['name'] for i in disclosure.select('[name]')} == {'csrf_token', 'action', 'item_type', 'item_no', 'label', 'file'}
    csrf = disclosure.select_one('[name=csrf_token]')['value']
    for label in ['Booklet one', 'Booklet two']:
        result = client.post('/manage/instructions', data=dict(csrf_token=csrf, action='upload',
            item_type='I', item_no=booklet, label=label,
            file=(BytesIO(b'%PDF-1.4\nreview fixture'), 'booklet.pdf')))
        assert result.status_code == 302
    with admin.database(bw) as db:
        identifier = db.execute("SELECT id FROM instruction_files WHERE item_type='I'").fetchone()[0]
        assert db.execute("SELECT count(*) FROM events WHERE field='attach' AND via='app'").fetchone()[0] == 2
    result = client.post('/manage/instructions', data=dict(csrf_token=csrf, action='rename', id=identifier, label='Renamed booklet'))
    assert result.status_code == 302
    soup = BeautifulSoup(client.get('/manage/instructions').data, 'html.parser')
    assert soup.select_one('.bw-page-head h1').text == f'1 of {total} booklets have a PDF'
    # 4.9e: one row per booklet identity (both files sit under it).
    assert len(soup.select('[data-bw-row]')) == total
    assert soup.select_one(f'[name=id][value="{identifier}"]').find_parent('form').select_one('[name=label]')['value'] == 'Renamed booklet'
    assert client.get(f'/manage/instructions/{identifier}/download').data.startswith(b'%PDF')
    with admin.database(bw) as db:
        event = db.execute("SELECT old_value,new_value,via FROM events WHERE field='label' ORDER BY id DESC LIMIT 1").fetchone()
        assert tuple(event) == ('"Booklet one"', '"Renamed booklet"', 'app')


def test_instruction_long_list_and_bounded_queries(app, bw, monkeypatch):
    from brickwork.core import admin
    from brickwork.web import admin_ops
    original = admin.connect
    queries = []
    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(queries.append)
        return db
    with admin.database(bw) as db, db:
        db.executemany("INSERT INTO instruction_files(item_type,set_no,path,label) VALUES('S','new-set',?,?)",
                       [(f'file-{n}.pdf', f'Booklet {n}') for n in range(100)])
    monkeypatch.setattr(admin, 'connect', traced)
    small = admin_ops.tools_read('instructions')
    count = len(queries)
    assert len(small['files']) == 100 and small['coverage']['covered'] == 0
    with admin.database(bw) as db, db:
        db.executemany("INSERT INTO instruction_files(item_type,set_no,path,label) VALUES('S','new-set',?,?)",
                       [(f'file-{n}.pdf', f'Booklet {n}') for n in range(100, 300)])
    queries.clear()
    large = admin_ops.tools_read('instructions')
    assert len(queries) == count and count < 8
    assert len(large['files']) == 300 and large['coverage'] == small['coverage']
    soup = BeautifulSoup(logged_in(app).get('/manage/instructions').data, 'html.parser')
    assert soup.select_one('[data-bw-search]')['placeholder'] == 'Number or name'
    assert not soup.select('[data-bw-filter], [data-bw-sort], .bw-toolbar')
    assert len(soup.select('[data-bw-row]')) == 300 + large['coverage']['total']
