"""Review 5 frame contracts on a 4.0 collection (M.8i part 1, issue #110): the instruction screens. The Add frames moved to `test_bw_add.py` (M.8c).

A PDF belongs to a set; a booklet shows the files of the set with its number."""
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup

from brickwork.core import admin
from brickwork.web import admin_ops
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parents[1]


def test_instruction_review_header_and_upload(client, coll, world, pair):
    total = coll.db.execute("SELECT count(*) FROM item WHERE kind='instructions'").fetchone()[0]
    soup = BeautifulSoup(client.get('/manage/instructions').data, 'html.parser')
    assert soup.select_one('.bw-page-head h1').text == f'0 of {total} booklets have a PDF'
    assert soup.select_one('.bw-page-head p').text == 'Fetch, upload or rename'
    assert not soup.select('[data-bw-search], [data-bw-filter], [data-bw-sort]')
    disclosure = soup.select_one('.bw-instructions-upload')
    assert disclosure.name == 'details' and not disclosure.has_attr('open')
    assert disclosure.select_one('summary').text == 'Upload a PDF'
    assert {i['name'] for i in disclosure.select('[name]')} == {'csrf_token', 'action', 'item_type', 'item_no', 'label', 'file'}
    token = disclosure.select_one('[name=csrf_token]')['value']
    for label in ['Booklet one', 'Booklet two']:
        result = client.post('/manage/instructions', data=dict(csrf_token=token, action='upload', item_type='I', item_no='1000-1', label=label,
                                                             file=(BytesIO(b'%PDF-1.4\nreview fixture'), 'booklet.pdf')))
        assert result.status_code == 302
    identifier = coll.db.execute('SELECT id FROM instruction_file ORDER BY id').fetchone()[0]
    assert coll.db.execute("SELECT count(*) FROM event WHERE field='attach' AND via='app'").fetchone()[0] == 2
    result = client.post('/manage/instructions', data=dict(csrf_token=token, action='rename', id=identifier, label='Renamed booklet'))
    assert result.status_code == 302
    soup = BeautifulSoup(client.get('/manage/instructions').data, 'html.parser')
    assert soup.select_one('.bw-page-head h1').text == f'1 of {total} booklets have a PDF'
    # 4.9e: one row per booklet identity (both files sit under it).
    assert len(soup.select('[data-bw-row]')) == total
    assert soup.select_one(f'[name=id][value="{identifier}"]').find_parent('form').select_one('[name=label]')['value'] == 'Renamed booklet'
    assert client.get(f'/manage/instructions/{identifier}/download').data.startswith(b'%PDF')
    event = coll.db.execute("SELECT old_value,new_value,via FROM event WHERE field='label' ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(event) == ('Booklet one', 'Renamed booklet', 'app')


def test_instruction_long_list_and_bounded_queries(client, coll, world, pair, monkeypatch):
    queries = []
    original = admin.connect

    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(queries.append)
        return db
    # Files of a set no booklet names are listed apart; there are 100, then 300.
    coll.db.executemany("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,?,?,'2026-10-26T00:00:00.000Z')",
                        [(world.gate, f'data/instructions/file-{n}.pdf', f'Booklet {n}') for n in range(100)])
    coll.db.commit()
    monkeypatch.setattr(admin, 'connect', traced)
    small = admin_ops.tools_read('instructions')
    count = len(queries)
    assert len(small['files']) == 100 and small['coverage']['covered'] == 0
    coll.db.executemany("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,?,?,'2026-10-26T00:00:00.000Z')",
                        [(world.gate, f'data/instructions/file-{n}.pdf', f'Booklet {n}') for n in range(100, 300)])
    coll.db.commit()
    queries.clear()
    large = admin_ops.tools_read('instructions')
    assert len(queries) == count and count < 8
    assert len(large['files']) == 300 and large['coverage'] == small['coverage']
    soup = BeautifulSoup(client.get('/manage/instructions').data, 'html.parser')
    assert soup.select_one('[data-bw-search]')['placeholder'] == 'Number or name'
    assert not soup.select('[data-bw-filter], [data-bw-sort], .bw-toolbar')
    assert len(soup.select('[data-bw-row]')) == 300 + large['coverage']['total']
