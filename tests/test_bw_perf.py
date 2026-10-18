"""Speed fixes: each keeps its output and is checked against the unoptimised result."""
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


def test_secret_values_read_once_per_display_and_serialize(monkeypatch):
    monkeypatch.setenv('BW_FIXTURE_KEY', 'swordfish-123456')
    calls = []
    real = secrets.secret_values
    monkeypatch.setattr(secrets, 'secret_values', lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(base, 'secret_values', secrets.secret_values)
    value = {'rows': [{'a': 'x swordfish-123456 LEGO', 'b': ['swordfish-123456', 7]} for _ in range(50)], 'c': 'plain'}
    shown = admin.display(value)
    assert len(calls) == 1
    assert shown['rows'][0]['a'] == 'x [set] ' and shown['rows'][0]['b'] == ['[set]', 7] and shown['c'] == 'plain'
    from brickwork.core import api_reads
    monkeypatch.setattr(api_reads, 'secret_values', secrets.secret_values)
    del calls[:]
    out = api_reads.serialize({'rows': [{'name': 'swordfish-123456'} for _ in range(50)]})
    assert len(calls) == 1 and out['rows'][0]['name'] == '[set]'
    assert base.redact('a swordfish-123456', []) == 'a swordfish-123456' and base.redact('a swordfish-123456') == 'a [set]'


def test_detail_properties_scope_equals_whole_store(store):
    with admin.database(store) as db:
        whole = collection.properties(db)
        for kind, number in (('S', '1'), ('S', '2'), ('P', '3001'), ('M', 'fig1')):
            assert collection.properties(db, kind, [number])[kind, number] == whole[kind, number]
        assert set(collection.properties(db, 'S', ['1'])) == {('S', '1')}
        scoped = collection.properties(db, identities={('S', '2'), ('P', '3001', 4)[:2]})
        assert set(scoped) == {('S', '2'), ('P', '3001')} and scoped[('S', '2')] == whole[('S', '2')]


def test_wish_listing_reads_only_wish_identities_with_identical_output(store):
    with admin.database(store) as db:
        rows = collection.listing(db, 'S', wishes=True)
        whole_prices, whole_props = dict(collection.prices(db)), dict(collection.properties(db))
        assert len(rows) == 2 and len(whole_prices) == 6 and all(row['prices'] for row in rows)
        for row in rows:
            key = row['item_type'], row['item_no'], row['color_id']
            assert row['prices'] == whole_prices[key]
            assert row['properties'] == whole_props[row['item_type'], row['item_no']]
        scope = {(r['item_type'], r['item_no'], r['color_id']) for r in rows}
        assert set(collection.prices(db, scope=scope)) == scope
        # The unscoped observation read and the scoped one agree on every wish.
        everything = planning.display_prices(db, collection.listing(db, 'S', wishes=True))
        scoped = planning.display_prices(db, collection.listing(db, 'S', wishes=True), scoped=True)
        assert json.dumps(everything, default=str, sort_keys=True) == json.dumps(scoped, default=str, sort_keys=True)
        statements = []
        db.set_trace_callback(statements.append)
        planning.wishes(db)
        db.set_trace_callback(None)
        flat = [' '.join(statement.split()) for statement in statements]
        reads = [q for q in flat if 'FROM item_properties' in q or 'FROM price_observations o' in q or 'FROM price_current p' in q]
        # #26 adds one batched read of the Brickset availability dates for the retail line.
        assert len(reads) == 4 and all('json_each' in q for q in reads)


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


def test_pictures_state_matches_the_original_query(store):
    original = pictures.HELD + '''
        SELECT h.item_type, count(*) total, sum(EXISTS(SELECT 1 FROM item_images im WHERE im.item_type=h.item_type AND im.item_no=h.item_no
            AND (im.color_id IS h.color_id OR im.color_id IS NULL) AND im.copy_id IS NULL AND im.stock_id IS NULL AND im.local_path IS NOT NULL)) present
        FROM held h JOIN items i USING(item_type,item_no) GROUP BY h.item_type'''
    with admin.database(store) as db, db:
        db.execute("INSERT INTO item_images(item_type,item_no,color_id,source,kind,local_path) VALUES('S','1',NULL,'bricklink','render','data/images/1.png')")
        db.execute("INSERT INTO item_images(item_type,item_no,color_id,source,kind,local_path) VALUES('P','3001',4,'rebrickable','render','data/images/2.png')")
        db.execute("INSERT INTO item_images(item_type,item_no,color_id,source,kind,local_path) VALUES('P','3002',5,'rebrickable','render','data/images/3.png')")
    with admin.database(store, read_only=True) as db:
        expected = {r[0]: (r[1], r[2]) for r in db.execute(original)}
        state = pictures.state(db)
        got = {row['kind']: (row['total'], row['with_picture']) for row in state['summary'] if row['total']}
        assert got == expected and expected['S'] == (2, 1) and expected['P'] == (1, 1)
        assert state['summary'][0]['sources']['bricklink'] == 1


def test_versioned_static_is_immutable_and_unversioned_is_not(app):
    client = logged_in(app)
    html = client.get('/manage/appearance').get_data(as_text=True)
    versioned = re.search(r'(/static/[^"\']+\?v=\d+)', html)[1]
    response = client.get(versioned)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'public, max-age=31536000, immutable'
    assert 'cookie' not in response.headers.get('Vary', '').lower() and 'Set-Cookie' not in response.headers
    assert 'X-Bw-Static-Immutable' not in response.headers
    plain = client.get(versioned.split('?')[0])
    assert 'immutable' not in plain.headers.get('Cache-Control', '')


def test_service_worker_precache_drops_splash_and_lockup_pngs():
    from pathlib import Path
    source = Path('static/web/toni/sw.js').read_text()
    assets = json.loads(re.search(r'const ASSETS = (\[.*?\]);', source, re.S)[1])
    assert not [a for a in assets if '/splash/' in a or re.search(r'lockup-.*\.png$', a)]
    manifest = Path('static/brickwork/manifest.webmanifest').read_text()
    assert '/static/brickwork/icons/icon-1024.png' in manifest and '/static/brickwork/icons/icon-1024.png' in assets
    assert all(Path(a.lstrip('/')).is_file() for a in assets)


def test_copy_parts_cover_index_is_added_once_and_not_pending(store):
    with admin.database(store) as db:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert 'copy_parts_identity_cover' in names and not upgrade_api.perf_indexes_missing(db)
        db.execute('DROP INDEX copy_parts_identity_cover')
        # A missing performance index is a hint for writable stores only, never pending for a read-only one.
        assert upgrade_api.perf_indexes_missing(db) and not upgrade.pending(db, writable=False)
        assert upgrade.pending(db, writable=True)
        upgrade_api.upgrade_indexes(db); upgrade_api.upgrade_indexes(db)
        assert not upgrade_api.perf_indexes_missing(db) and not upgrade.pending(db, writable=True)
        plan = ' '.join(r[3] for r in db.execute("EXPLAIN QUERY PLAN SELECT copy_id FROM copy_parts WHERE item_type='P' AND item_no='3001' AND color_id IS 4"))
        assert 'copy_parts_identity_cover' in plan



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


def test_api_public_reads_the_secret_list_once_per_response(monkeypatch):
    from brickwork.api import serializers
    calls = []
    monkeypatch.setattr(secrets, 'secret_values', lambda: calls.append(1) or [])
    rows = [{'id': str(i), 'name': f'Shelf {i}'} for i in range(40)]
    serializers.public(rows, ['Storage'])
    assert len(calls) == 1
