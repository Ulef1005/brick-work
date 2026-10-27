"""Speed fixes of Tools & Admin on the 4.0 store (M.8i part 1, issue #110): the hub counts and the database check.

The unresolved list's tests (the hub count and the records it reads) moved to `test_bw_admin_identity.py` with part 2."""
from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)


def test_hub_counts_equal_list_lengths(coll, world):
    stale = admin.stale_prices(coll.db)
    assert len({r['item_id'] for r in stale}) == 7
    coll.sql("INSERT INTO job(source,kind,state,via,created_at,updated_at) VALUES('bricklink','item','done','app','2026-10-01T00:00:00.000Z','2026-10-01T00:00:00.000Z')")
    assert admin.count_jobs(coll.db) == len(admin.jobs(coll.db)) == 1


def test_the_hub_shows_the_counts(client, world):
    text = BeautifulSoup(client.get('/manage/tools').data, 'html.parser').select_one('.bw-hub').get_text(' ')
    assert '7 stale' in text


def test_database_page_does_not_check_on_get_and_runs_on_button(client, coll, world, monkeypatch):
    def forbidden(db):
        raise AssertionError('the check must not run on GET')
    original = admin.check
    monkeypatch.setattr(admin, 'check', forbidden)
    page = client.get('/manage/database')
    soup = BeautifulSoup(page.data, 'html.parser')
    assert page.status_code == 200 and 'not checked yet' in soup.get_text()
    form = next(f for f in soup.select('form[method=post]') if f.select_one('[name=action][value=check]'))
    assert form.select_one('button').get_text(strip=True) == 'Run integrity check'
    token = form.select_one('[name=csrf_token]')['value']
    # No token, no check, no write.
    before = coll.db.execute('SELECT count(*) FROM event').fetchone()[0]
    assert client.post('/manage/database', data={'action': 'check'}).status_code == 400
    assert coll.db.execute('SELECT count(*) FROM event').fetchone()[0] == before
    assert admin.last_check(coll.db) is None
    monkeypatch.setattr(admin, 'check', original)
    page = client.post('/manage/database', data={'action': 'check', 'csrf_token': token}, follow_redirects=True)
    assert page.status_code == 200 and b'Database check finished' in page.data
    text = BeautifulSoup(page.data, 'html.parser').get_text(' ', strip=True)
    assert 'Database checks passed' in text and 'Last checked' in text and 'Rows by table' in text and 'Catalogue integrity' in text
    stored = admin.last_check(coll.db)
    assert stored['integrity_check'] == ['ok'] and stored['catalogue_integrity_check'] == ['ok'] and stored['row_counts']['copy'] == 3
    assert coll.db.execute("SELECT value FROM setting WHERE key='maintenance:database_check'").fetchone() is not None
    event = coll.db.execute('SELECT entity_kind,field,new_value,via FROM event ORDER BY id DESC LIMIT 1').fetchone()
    assert tuple(event) == ('database', 'check', 'ok', 'app')
    # A later GET shows the stored result without running anything.
    monkeypatch.setattr(admin, 'check', forbidden)
    again = BeautifulSoup(client.get('/manage/database').data, 'html.parser').get_text(' ', strip=True)
    assert 'Last checked' in again and 'Database checks passed' in again


def test_database_check_records_foreign_key_findings(coll, world):
    db = coll.db
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute("INSERT INTO stock_flag(stock_id,flag_id) VALUES('nope',?)", (world.tag,))
    db.commit()
    result = admin.run_check(db)
    assert result['foreign_key_total'] == 1 and result['foreign_key_check'][0]['table'] == 'stock_flag'
    assert admin.last_check(db)['foreign_key_total'] == 1
    assert db.execute("SELECT new_value FROM event WHERE entity_kind='database' AND field='check'").fetchone()[0] == 'needs attention'


def test_the_check_keeps_the_findings_it_stores_bounded(coll, world, monkeypatch):
    monkeypatch.setattr(admin, 'CHECK_FINDINGS_STORED', 2)
    db = coll.db
    db.execute('PRAGMA foreign_keys=OFF')
    db.executemany("INSERT INTO stock_flag(stock_id,flag_id) VALUES(?,?)", [(f'nope{n}', world.tag) for n in range(5)])
    db.commit()
    stored = admin.run_check(db)
    assert stored['foreign_key_total'] == 5 and len(stored['foreign_key_check']) == 2


def test_read_only_instance_checks_the_database_without_storing(app4, client, coll, world):
    soup = BeautifulSoup(client.get('/manage/database').data, 'html.parser')
    token = soup.select_one('[name=csrf_token]')['value']
    before = coll.db.execute('SELECT count(*) FROM event').fetchone()[0]
    app4.config['BW_READ_ONLY'] = True
    try:
        page = client.post('/manage/database', data={'action': 'check', 'csrf_token': token}, follow_redirects=True)
    finally:
        app4.config['BW_READ_ONLY'] = False
    assert page.status_code == 200 and b'not stored, this instance is read-only' in page.data
    assert coll.db.execute('SELECT count(*) FROM event').fetchone()[0] == before
    assert admin.last_check(coll.db) is None
