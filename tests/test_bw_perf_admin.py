"""Speed fixes of Tools & Admin (the hub counts, the unresolved list, the database check): split out of test_bw_perf.py by M.8f, waiting for M.8i.

3.3 form; M.8i rewrites them on the 4.0 store with the Tools & Admin screens."""
from contextlib import closing
import json
import re
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection, pictures, planning, secrets, upgrade_api, upgrade
from brickwork.core.connect import connect
from brickwork.core.sources import base
from tests.web_fixtures import app, apps, logged_in


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / 'brickwork.db'
    monkeypatch.setenv('BW_DB_PATH', str(path))
    with closing(connect(path)) as db, db:
        db.execute("INSERT OR IGNORE INTO sources VALUES('bricklink','BrickLink','api',1,NULL)")
        db.execute("INSERT OR IGNORE INTO sources VALUES('rebrickable','Rebrickable','api',1,NULL)")
        for kind, number, name in (('S', '1', 'One'), ('S', '2', 'Two'), ('S', '3', 'Three'), ('M', 'fig1', 'Fig'), ('P', '3001', 'Brick'), ('P', '3002', 'Other brick'), ('?', 'rb:x', 'Unknown')):
            db.execute('INSERT INTO items(item_type,item_no,name) VALUES(?,?,?)', (kind, number, name))
        for colour in (4, 5):
            db.execute('INSERT INTO colors(color_id,name) VALUES(?,?)', (colour, f'Colour {colour}'))
        db.execute("INSERT INTO copies(id,set_no,completeness) VALUES('c1','1','C')")
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity) VALUES('S','2',NULL,1)")
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity) VALUES('P','3001',4,2)")
        for kind, number, colour, price in (('S', '1', None, '10'), ('S', '2', None, '20'), ('S', '3', None, '30'), ('P', '3001', 4, '1'), ('P', '3001', 5, '2'), ('P', '3002', 4, '3')):
            db.execute("""INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,source,observed_at)
                VALUES(?,?,?,'U','sold','EUR',?,'bricklink','2026-10-01T00:00:00+00:00')""", (kind, number, colour, price))
            db.execute("""INSERT INTO price_current(item_type,item_no,color_id,condition,guide,currency,observation_id)
                SELECT item_type,item_no,color_id,condition,guide,currency,id FROM price_observations WHERE id=last_insert_rowid()""")
        for kind, number in (('S', '1'), ('S', '2'), ('S', '3'), ('P', '3001'), ('P', '3002')):
            for key in ('theme', 'year'):
                db.execute("INSERT INTO item_properties VALUES(?,?,?,'bricklink',?,NULL,'2026-10-01')", (kind, number, key, kind + number + key))
    return path


def test_hub_counts_equal_list_lengths(store):
    with admin.database(store) as db, db:
        db.execute("INSERT INTO copy_minifigs VALUES('c1','?','rb:x',1,0,NULL)")
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','minifigure','x','?','rb:x','unmatched','[]')")
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','minifigure','y','M','fig1','unmatched','[]')")
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','minifigure','z','?','rb:x','matched','[]')")
        db.execute("INSERT INTO jobs(source,kind,state,created_at,updated_at) VALUES('bricklink','import','done','2026-10-01','2026-10-01')")
    with admin.database(store, read_only=True) as db:
        assert admin.count_unresolved(db) == len(admin.unresolved(db)) == 1
        assert admin.count_jobs(db) == len(admin.jobs(db))


def test_unresolved_reads_only_the_records_it_shows(store):
    payload = json.dumps({'name': 'Real name', 'set_img_url': 'https://example.test/x.png'})
    with admin.database(store) as db, db:
        db.execute("INSERT INTO copy_minifigs VALUES('c1','?','rb:x',1,0,NULL)")
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','minifigure','x','?','rb:x','unmatched','[]')")
    with admin.database(store) as db, db:
        def put(source_id, text):
            db.execute("INSERT INTO source_records VALUES('rebrickable','minifigure',?,?,'2026-10-01','received')", (source_id, text))
        put('x', payload)
        for number in range(20):
            put(f'other{number}', 'z' * 5000)
        seen = []
        db.set_trace_callback(seen.append)
        result = admin.unresolved(db)
        db.set_trace_callback(None)
    assert len(result) == 1 and result[0]['name'] == 'Real name' and result[0]['reference_url'] == 'https://example.test/x.png'
    assert not any(re.search(r'FROM source_records\s+ORDER BY', ' '.join(s.split())) for s in seen)


def test_database_page_does_not_check_on_get_and_runs_on_button(app, store, monkeypatch):
    def forbidden(db):
        raise AssertionError('the check must not run on GET')
    monkeypatch.setattr(admin, 'check', forbidden)
    client = logged_in(app)
    page = client.get('/manage/database')
    soup = BeautifulSoup(page.data, 'html.parser')
    assert page.status_code == 200 and 'not checked yet' in soup.get_text()
    form = next(f for f in soup.select('form[method=post]') if f.select_one('[name=action][value=check]'))
    assert form.select_one('button').get_text(strip=True) == 'Run integrity check'
    token = form.select_one('[name=csrf_token]')['value']
    # No token, no check, no write.
    with admin.database(store) as db:
        before = db.execute('SELECT count(*) FROM events').fetchone()[0]
    assert client.post('/manage/database', data={'action': 'check'}).status_code == 400
    with admin.database(store) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == before
        assert admin.last_check(db) is None
    monkeypatch.undo()
    monkeypatch.setenv('BW_DB_PATH', str(store))
    page = client.post('/manage/database', data={'action': 'check', 'csrf_token': token}, follow_redirects=True)
    assert page.status_code == 200 and b'Database check finished' in page.data
    text = BeautifulSoup(page.data, 'html.parser').get_text(' ', strip=True)
    assert 'Database checks passed' in text and 'Last checked' in text and 'Rows by table' in text
    with admin.database(store) as db:
        assert admin.last_check(db)['integrity_check'] == ['ok']
        event = db.execute('SELECT entity,field,new_value,via FROM events ORDER BY id DESC LIMIT 1').fetchone()
        assert tuple(event) == ('database', 'check', '"ok"', 'app')
    # A later GET shows the stored result without running anything.
    monkeypatch.setattr(admin, 'check', forbidden)
    again = BeautifulSoup(client.get('/manage/database').data, 'html.parser').get_text(' ', strip=True)
    assert 'Last checked' in again and 'Database checks passed' in again


def test_database_check_records_foreign_key_findings(store):
    with admin.database(store) as db:
        db.execute('PRAGMA foreign_keys=OFF')
        with db:
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity) VALUES('nope','P','3001',4,1)")
        result = admin.run_check(db)
        assert result['foreign_key_total'] == 1 and result['foreign_key_check'][0]['table'] == 'copy_parts'
        assert admin.last_check(db)['foreign_key_total'] == 1
        assert db.execute("SELECT new_value FROM events WHERE entity='database' AND field='check'").fetchone()[0] == '"needs attention"'


def test_read_only_instance_checks_the_database_without_storing(app, store, monkeypatch):
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/manage/database').data, 'html.parser')
    token = soup.select_one('[name=csrf_token]')['value']
    with admin.database(store) as db:
        before = db.execute('SELECT count(*) FROM events').fetchone()[0]
    app.config['BW_READ_ONLY'] = True
    try:
        page = client.post('/manage/database', data={'action': 'check', 'csrf_token': token}, follow_redirects=True)
    finally:
        app.config['BW_READ_ONLY'] = False
    assert page.status_code == 200 and b'not stored, this instance is read-only' in page.data
    with admin.database(store) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == before
        assert admin.last_check(db) is None
