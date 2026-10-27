"""Identity admin of Tools & Admin (M.8i part 2, issue #110): Unresolved figures, resolving a match, loading candidate pictures.

Split off from test_bw_admin.py, test_bw_perf_admin.py and test_bw_admin_csrf.py by M.8i part 1, which ports the rest of Tools & Admin. These
tests are still the 3.3 text (`id_match`, `loose_stock`, `copy_minifigs`); part 2 rewrites them with the identity pieces (design 3.6, 3.8:
the list reads `item_link WHERE status='to_check'` and `item_provider_status`) and takes the file out of the quarantine."""
from contextlib import closing
import json
import sqlite3

import pytest

from brickwork.core.connect import connect
from brickwork.core import admin
from brickwork.web import admin_ops
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps


@pytest.fixture
def bw(app, tmp_path, monkeypatch):
    path = tmp_path / 'brickwork.db'
    monkeypatch.setenv('BW_DB_PATH', str(path))
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'private-fixture-key')
    with closing(connect(path)) as db, db:
        db.execute("INSERT OR IGNORE INTO sources VALUES('rebrickable','Rebrickable','api',1,NULL)")
        db.execute("INSERT OR IGNORE INTO sources VALUES('bricklink','BrickLink','api',1,NULL)")
        db.execute("INSERT OR REPLACE INTO source_freshness VALUES('bricklink','prices',7)")
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','1','Set one')")
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('?','rb:figure','Unknown figure')")
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('M','candidate','Candidate')")
        db.execute("INSERT INTO copies(id,set_no,completeness) VALUES('copy','1','I')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity) VALUES('stock','?','rb:figure',2)")
        db.execute("INSERT INTO copy_minifigs VALUES('copy','?','rb:figure',1,1,NULL)")
        db.execute("INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,quantity,source) VALUES('S','1','?','rb:figure',1,'rebrickable')")
        evidence = json.dumps([{'item_type':'M','item_no':'candidate','score':0.9}])
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','minifigure','fig','?','rb:figure','unmatched',?)", (evidence,))
        db.execute("INSERT INTO identifications(id,created_at,has_thumb,candidates,missing_count) VALUES('identify','2026-10-12',0,'[]',0)")
    return path


def test_unresolved_page_lists_the_unmatched_figure_and_pick_resolves_it(app, bw):
    client = logged_in(app)
    assert 'Unknown figure' in client.get('/manage/unresolved').get_data(as_text=True)
    client.get('/manage/catalogues')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    assert client.post('/manage/unresolved', data={'csrf_token': token, 'source': 'rebrickable', 'kind': 'minifigure', 'source_id': 'fig',
                                                  'action': 'pick', 'candidate': '["M","candidate"]'}).status_code == 302


def test_resolve_all_reference_paths_and_leave(bw):
    with admin.database(bw) as db:
        admin.resolve(db,'rebrickable','minifigure','fig')
        assert db.execute('SELECT status FROM id_match').fetchone()[0] == 'to_check'
        admin.resolve(db,'rebrickable','minifigure','fig',('M','candidate'))
        assert tuple(db.execute('SELECT item_type,item_no FROM loose_stock').fetchone()) == ('M','candidate')
        assert tuple(db.execute('SELECT item_type,minifig_no FROM copy_minifigs').fetchone()) == ('M','candidate')
        assert tuple(db.execute('SELECT child_item_type,child_item_no FROM inventory_lines').fetchone()) == ('M','candidate')
        assert db.execute('SELECT status FROM id_match').fetchone()[0] == 'manual'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute("SELECT count(*) FROM events WHERE via='app'").fetchone()[0] == 2


def test_resolve_rolls_back_on_error(bw):
    with admin.database(bw) as db:
        db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'no'); END")
        with pytest.raises(sqlite3.IntegrityError):
            admin.resolve(db,'rebrickable','minifigure','fig',('M','candidate'))
        assert db.execute('SELECT item_type FROM loose_stock').fetchone()[0] == '?'
        assert db.execute('SELECT status FROM id_match').fetchone()[0] == 'unmatched'
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 0


def test_unresolved_migrated_evidence_and_polymorphic_flags(bw):
    with admin.database(bw) as db:
        assert admin.candidates([{'ordinal':0,'record':{'parts_json':json.dumps([{'bricklink':['a','b']}])}}], 'inventory-child')[0]['item_type'] == 'P'
        with db:
            db.execute("INSERT INTO wishlist(item_type,item_no) VALUES('?','rb:figure')")
            db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('tag','Display','tag',1)")
            db.execute("INSERT INTO item_flags VALUES('wishlist',CAST((SELECT id FROM wishlist WHERE item_no='rb:figure') AS TEXT),'tag')")
        admin.resolve(db,'rebrickable','minifigure','fig',('M','candidate'))
        assert db.execute('SELECT entity_id FROM item_flags').fetchone()[0] == str(db.execute('SELECT id FROM wishlist').fetchone()[0])
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_images_queue_pipeline_and_local_reference(bw,app):
    from brickwork.core.pipeline import Pipeline
    from brickwork.core.sources.base import audit_origin
    from pathlib import Path
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO source_records VALUES('rebrickable','rebrickable_minifigures','fig',?,NULL,'legacy')",
                   (json.dumps({'records':[{'record':{'name':'Reference figure','image':'https://cdn.rebrickable.com/reference.png'}}]}),))
    with app.app_context():
        queued = admin_ops.tools_write('images',source='rebrickable',kind='minifigure',source_id='fig')
    with admin.database(bw) as db, audit_origin('app'):
        p = Pipeline(db,image_http=lambda _: (Path(__file__).parent/'fixtures/brickwork/import-image.png').read_bytes(),emit=lambda *a: None)
        for job in queued:
            assert p.run(job)['state'] == 'done'
        assert len(db.execute('SELECT * FROM item_images').fetchall()) == 2
        assert all(r['via'] == 'app' for r in db.execute('SELECT via FROM events'))
        assert admin.unresolved(db)[0]['name'] == 'Reference figure'
        assert admin.unresolved(db)[0]['image'] is not None
    assert 'https://cdn.rebrickable.com/reference.png' not in logged_in(app).get('/manage/unresolved').get_data(as_text=True)


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


@pytest.mark.parametrize('action', ['pick', 'leave', 'images'])
@pytest.mark.parametrize('token', [None, 'wrong'])
def test_unresolved_csrf_rejects_before_dispatch_without_writes(app, bw, monkeypatch, action, token):
    client = logged_in(app)
    client.get('/manage/unresolved')
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid CSRF reached an admin write or worker')
    monkeypatch.setattr(admin_ops, 'tools_write', forbidden)
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', forbidden)
    data = {'action': action}
    if token is not None:
        data['csrf_token'] = token
    assert client.post('/manage/unresolved', data=data).status_code == 400
