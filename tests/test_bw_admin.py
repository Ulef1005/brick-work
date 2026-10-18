"""New-store routes, audit transactions and referenced-identity cutover."""
from contextlib import closing
import json
import sqlite3

import pytest

from brickwork.core.connect import connect
from brickwork.core import admin
from brickwork.web import admin_ops
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.importer.test_importer import legacy


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


@pytest.mark.parametrize('page', ['tools','catalogues','jobs','refresh','unresolved','statistics','values','database','settings','appearance','history','instructions'])
def test_routes_in_shell_no_keys(app, bw, page):
    result = logged_in(app).get('/manage/' + page)
    assert result.status_code == 200
    html = result.get_data(as_text=True)
    assert 'data-web-ui="toni"' in html and 'Tools &amp; Admin' in html
    assert 'private-fixture-key' not in html
    assert result.headers['Cache-Control'] == 'no-store'


def test_value_audit_and_rollback(bw):
    with admin.database(bw) as db:
        admin.value_write(db,'tags','add',name='Display')
        row = admin.value_rows(db,'tags')[0]
        assert db.execute("SELECT via FROM events ORDER BY id DESC").fetchone()[0] == 'app'
        db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'no'); END")
        with pytest.raises(sqlite3.IntegrityError):
            admin.value_write(db,'tags','rename',identifier=row['id'],name='Changed')
        assert admin.value_rows(db,'tags')[0]['name'] == 'Display'


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


def test_settings_rollback_and_queue(bw):
    with admin.database(bw) as db:
        config = admin.settings(db)
        with pytest.raises(ValueError):
            admin.save_settings(db,'US',config['priority'],[('bricklink','prices','-1')])
        assert admin.settings(db)['retail_country'] == 'DE'
        queued = admin.queue_refresh(db,admin.stale_prices(db))
        assert len(queued) == 1
        assert admin.jobs(db)[0]['steps'][0]['name'] == 'market_price'
        assert admin.jobs(db)[0]['steps'][0]['state'] == 'queued'
        assert db.execute("SELECT via FROM events WHERE field='queued'").fetchone()[0] == 'app'
        assert admin.queue_refresh(db,admin.stale_prices(db)) == []


def test_write_routes_and_export(app,bw):
    client = logged_in(app)
    client.get('/manage/catalogues')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    assert client.post('/manage/values',data={'csrf_token':token,'group':'owners','action':'add','name':'Ulf'}).status_code == 302
    assert client.post('/manage/unresolved',data={'csrf_token':token,'source':'rebrickable','kind':'minifigure','source_id':'fig','action':'pick','candidate':'["M","candidate"]'}).status_code == 302
    response = client.get('/manage/database/export')
    assert response.status_code == 200 and response.data.startswith(b'SQLite format 3')
    with closing(sqlite3.connect(':memory:')) as snapshot:
        snapshot.deserialize(response.data)
        assert snapshot.execute("SELECT count(*) FROM events WHERE field='export' AND via='app'").fetchone()[0] == 1


def test_missing_store_is_visible(app, tmp_path, monkeypatch):
    path = tmp_path / 'absent.db'
    monkeypatch.setenv('BW_DB_PATH',str(path))
    response = logged_in(app).get('/manage/tools')
    assert 'database is not available' in response.get_data(as_text=True)
    assert not path.exists()


def test_route_data_is_new_store(app, bw):
    client = logged_in(app)
    assert 'Unknown figure' in client.get('/manage/unresolved').get_data(as_text=True)
    assert '1 of 1 copies are incomplete' in client.get('/manage/statistics').get_data(as_text=True)
    assert 'Set one' in client.get('/manage/refresh').get_data(as_text=True)
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO jobs(source,kind,state,error,created_at,updated_at) VALUES('brickset','getSets','failed','private-fixture-key','2026-10-12','2026-10-12')")
    html = client.get('/manage/catalogues').get_data(as_text=True)
    assert 'private-fixture-key' not in html and '[set]' in html


def test_storage_delete_requires_empty_location_and_archives(bw):
    with admin.database(bw) as db:
        admin.value_write(db,'storages','add',name='Box one')
        identifier = admin.value_rows(db,'storages')[0]['id']
        with db:
            db.execute('UPDATE copies SET storage_id=?', (identifier,))
        assert admin.value_rows(db,'storages')[0]['count'] == 1
        with pytest.raises(ValueError):
            admin.value_write(db,'storages','delete',identifier=identifier)
        assert db.execute('SELECT storage_id FROM copies').fetchone()[0] == identifier
        with pytest.raises(ValueError, match='Move the items'):
            admin.value_write(db,'storages','delete',identifier=identifier,confirmed=True)
        from brickwork.core import ledger
        ledger.move(db,None,[dict(entity='copy',id=r[0]) for r in db.execute('SELECT id FROM copies')])
        event = admin.value_write(db,'storages','delete',identifier=identifier,confirmed=True)
        assert db.execute('SELECT archived_at FROM storages WHERE id=?',(identifier,)).fetchone()[0]
        ledger.undo(db,event)
        assert db.execute('SELECT storage_id FROM copies').fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM copies').fetchone()[0] == 1


def test_instruction_upload_rename_download_and_rollback(app,bw):
    import io
    client = logged_in(app)
    client.get('/manage/instructions')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    content = b'%PDF-1.4\nsynthetic fixture'
    result = client.post('/manage/instructions',data={'csrf_token':token,'action':'upload','item_type':'S','item_no':'1',
        'label':'Booklet one','file':(io.BytesIO(content),'booklet.pdf')})
    assert result.status_code == 302
    with admin.database(bw) as db:
        row = db.execute('SELECT * FROM instruction_files').fetchone()
        assert db.execute("SELECT via FROM events WHERE field='attach'").fetchone()[0] == 'app'
        admin.instruction_rename(db,row['id'],'Booklet two')
    assert client.get(f"/manage/instructions/{row['id']}/download").data == content
    with admin.database(bw) as db:
        db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'no'); END")
        with pytest.raises(sqlite3.IntegrityError):
            admin.instruction_upload(db,bw.parent,'S','1','Fail',b'%PDF-1.4\nnew fixture')
        assert db.execute('SELECT count(*) FROM instruction_files').fetchone()[0] == 1
    assert len(list((bw.parent/'data/instructions').glob('*.pdf'))) == 1


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


def test_stale_freshness_and_archives(bw):
    from datetime import timedelta
    from brickwork.core.sources.base import now
    with admin.database(bw) as db:
        assert len(admin.stale_prices(db)) == 1
        with db:
            db.execute("INSERT INTO price_observations(item_type,item_no,guide,source,observed_at) VALUES('S','1','sold','bricklink',?)", ((now()-timedelta(days=2)).isoformat(),))
        assert admin.stale_prices(db) == []
        config=admin.settings(db)
        admin.save_settings(db,'DE',config['priority'],[('bricklink','prices','1')])
        assert len(admin.stale_prices(db)) == 1
        with db:
            db.execute("UPDATE copies SET archived_at='2026-10-12'")
        assert admin.stale_prices(db) == []


def test_post_rejects_cross_origin_and_auth(app,bw):
    assert app.test_client().post('/manage/values',data={}).status_code == 302
    assert logged_in(app).post('/manage/values',headers={'Origin':'https://other.invalid'},data={}).status_code == 403


@pytest.fixture(autouse=True)
def reset_shell_metadata_after_test():
    yield


def test_history_presents_candidates_without_raw_json(app,bw):
    with admin.database(bw) as db, db:
        db.execute('UPDATE identifications SET candidates=?',
            (json.dumps([{'id':'candidate','type':'minifig','score':0.92,'name':'Candidate figure'}]),))
    html=logged_in(app).get('/manage/history').get_data(as_text=True)
    assert 'Candidate figure' in html and '0.92 match' in html
    assert '<pre>' not in html


def test_history_dates_are_short_stamps_not_iso(app,bw):
    import re
    with admin.database(bw) as db, db:
        db.execute("UPDATE identifications SET created_at='2026-10-04T14:41:00.400000+00:00'")
    html=logged_in(app).get('/manage/history').get_data(as_text=True)
    from bs4 import BeautifulSoup
    visible=BeautifulSoup(html,'html.parser').select_one('main').get_text(' ')
    assert not re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', visible)
    assert '4 Oct · 14:41' in html or '04 Oct · 14:41' in html


def test_phone_tap_targets_on_complete_sets_and_used_in():
    from pathlib import Path
    planning=Path('static/web/toni/bw-planning.css').read_text()
    collection=Path('static/web/toni/bw-collection.css').read_text()
    assert '.bp-complete-sets .bp-select,#bw-planning .bp-complete-sets [data-bp-pin] { min-height:44px' in planning
    assert '.bc-used-identity a { min-height:44px' in collection


def test_wishlist_price_refresh_preserves_colour_and_condition(bw):
    from brickwork.core.pipeline import Pipeline
    from brickwork.core.sources.base import now
    with admin.database(bw) as db:
        with db:
            db.execute("INSERT INTO items(item_type,item_no) VALUES('P','wish-part')")
            db.execute('INSERT INTO colors(color_id) VALUES(0),(11),(12)')
            db.execute("INSERT INTO wishlist(item_type,item_no,color_id,condition) VALUES('P','wish-part',11,'new'),('P','wish-part',0,'used')")
            db.execute("INSERT INTO wishlist(item_type,item_no,color_id,archived_at) VALUES('P','wish-part',12,'old')")
            db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,source,observed_at) VALUES('P','wish-part',11,'U','sold','bricklink',?)", (now().isoformat(),))
        stale=[r for r in admin.stale_prices(db) if r['item_no']=='wish-part']
        assert {(r['color_id'],r['condition']) for r in stale}=={(11,'N'),(0,'U')}
        assert set(Pipeline(db).colors('P','wish-part'))=={0,11}
        with db:
            db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,source,observed_at) VALUES('P','wish-part',11,'N','sold','bricklink',?)", (now().isoformat(),))
        assert [(r['color_id'],r['condition']) for r in admin.stale_prices(db) if r['item_no']=='wish-part']==[(0,'U')]


@pytest.fixture
def migrated_bw(legacy, monkeypatch):
    from brickwork.core.importer.migrate import migrate
    migrate(**legacy)
    monkeypatch.setenv('BW_DB_PATH', str(legacy['out_db']))
    return legacy['out_db']


@pytest.mark.parametrize(('page','form','operation','label'), [
    ('catalogues', {'action':'load'}, 'catalogue', 'Catalogue load'),
    ('catalogues', {'action':'colours'}, 'colours', 'Colour load'),
    ('catalogues', {'action':'source','source':'bricklink'}, 'source', 'Source toggle'),
    ('refresh', {}, 'refresh', 'Price refresh'),
])
def test_source_failure_names_action(app, migrated_bw, monkeypatch, page, form, operation, label):
    from brickwork.core.sources.base import SourceError
    def fail(actual, **kwargs):
        assert actual == operation
        raise SourceError('Source is unavailable')
    monkeypatch.setattr(admin_ops, 'tools_write', fail)
    client = logged_in(app)
    client.get('/manage/' + page)
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    response = client.post('/manage/' + page, data={**form, 'csrf_token':token}, follow_redirects=True)
    assert label + ' · Source is unavailable' in response.get_data(as_text=True)


@pytest.mark.parametrize('action', ['colours','load'])
def test_colour_validation_message_survives_transport(app, migrated_bw, monkeypatch, action):
    from brickwork.core.sources import base
    from brickwork.core.sources.bricklink import BrickLink
    for key in BrickLink.credentials:
        monkeypatch.setenv(key, 'fixture-key')
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    monkeypatch.setattr(base, 'transport', lambda _: {'meta':{'code':200}, 'data':[
        dict(color_id=11,color_name='Changed',color_type='Solid',color_code='000000'),
        dict(color_id=12,color_name='Bad',color_type='Solid',color_code='private-invalid-code')]})
    original = admin_ops.tools_write
    monkeypatch.setattr(admin_ops, 'tools_write', lambda op, **kw: None if op == 'catalogue' else original(op, **kw))
    with admin.database(migrated_bw) as db:
        before = [tuple(r) for r in db.execute('SELECT * FROM colors ORDER BY color_id')]
        events = db.execute("SELECT count(*) FROM events WHERE entity LIKE 'color:%'").fetchone()[0]
    client = logged_in(app)
    client.get('/manage/catalogues')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    response = client.post('/manage/catalogues', data={'action':action,'csrf_token':token}, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert 'Invalid BrickLink colour code' in html
    assert 'private-invalid-code' not in html
    assert 'Nothing was saved.' not in html
    with admin.database(migrated_bw) as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM colors ORDER BY color_id')] == before
        assert db.execute("SELECT count(*) FROM events WHERE entity LIKE 'color:%'").fetchone()[0] == events


@pytest.mark.parametrize('error', [ValueError, KeyError, TypeError])
def test_admin_internal_validation_message_stays_private(app, migrated_bw, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error('private-internal-detail')
    monkeypatch.setattr(admin_ops, 'tools_write', fail)
    client = logged_in(app)
    client.get('/manage/catalogues')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    response = client.post('/manage/catalogues', data={'action':'colours','csrf_token':token}, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert 'Nothing was saved. Check the values and try again.' in html
    assert 'private-internal-detail' not in html


def test_49e_instruction_files_list_every_booklet_identity(app, bw):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db, db:
        for number, name in [('b-1', 'Booklet one'), ('b-2', 'Booklet two'), ('b-3', 'Booklet three'), ('b-4', 'Booklet four')]:
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I',?,?)", (number, name))
    html = logged_in(app).get('/manage/instructions').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.select_one('.bw-page-head h1').get_text() == '0 of 4 booklets have a PDF'
    rows = soup.select('[data-bw-rows] .bw-booklet')
    assert [r.select_one('.bw-booklet-no').get_text() for r in rows] == ['b-1', 'b-2', 'b-3', 'b-4']
    assert [r.select_one('.bw-booklet-name').get_text() for r in rows][0] == 'Booklet one'
    assert all(r.select_one('.bw-booklet-pill').get_text() == 'No PDF' for r in rows)
    assert 'No instruction files attached yet' not in html
    # w22, w23: no breadcrumb row and no helper paragraph.
    assert not soup.select('nav.breadcrumb, .breadcrumb')
    assert 'Coverage counts recorded booklet identities' not in html
    # w25, w26: Fetch missing above Upload a PDF; summary restyled past the disclosure chevron rules.
    actions = soup.select_one('.bw-instructions-actions')
    assert [e.get_text() for e in actions.select('button.bw-instructions-fetch, summary')] == ['Fetch missing', 'Upload a PDF']
    assert not actions.select('summary.button')


def test_49e_instruction_booklet_with_pdf_and_fetch_missing(app, bw):
    import io
    from bs4 import BeautifulSoup
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I','b-1','Booklet one')")
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I','b-2','Booklet two')")
    client = logged_in(app)
    client.get('/manage/instructions')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    assert client.post('/manage/instructions', data={'csrf_token': token, 'action': 'upload', 'item_type': 'I',
        'item_no': 'b-1', 'label': 'Booklet', 'file': (io.BytesIO(b'%PDF-1.4\nfixture'), 'b.pdf')}).status_code == 302
    soup = BeautifulSoup(client.get('/manage/instructions').get_data(as_text=True), 'html.parser')
    assert soup.select_one('.bw-page-head h1').get_text() == '1 of 2 booklets have a PDF'
    pills = {r.select_one('.bw-booklet-no').get_text(): r.select_one('.bw-booklet-pill').get_text() for r in soup.select('.bw-booklet')}
    assert pills == {'b-1': 'PDF available', 'b-2': 'No PDF'}
    assert soup.select_one('.bw-booklet a.button').get_text() == 'Download PDF'
    # Fetch missing queues the existing identity step for booklets without a PDF only.
    assert client.post('/manage/instructions', data={'csrf_token': token, 'action': 'fetch_missing'}).status_code == 302
    with admin.database(bw) as db:
        jobs = [tuple(r) for r in db.execute("SELECT item_type,item_no,state FROM jobs WHERE source='import'")]
        assert jobs == [('I', 'b-2', 'queued')]
        assert [r[0] for r in db.execute("SELECT name FROM import_steps")] == ['identity']
        assert db.execute("SELECT count(*) FROM instruction_files").fetchone()[0] == 1


def test_49e_instruction_page_query_count_is_flat(app, bw):
    with admin.database(bw) as db, db:
        for n in range(300):
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I',?,?)", (f'q-{n:03}', f'Booklet {n}'))
    from brickwork.web import admin_ops
    from brickwork.core.admin import database
    statements = []
    original = admin_ops.brickwork_path()
    with database(original, read_only=True) as db:
        db.set_trace_callback(statements.append)
        admin_ops.tools_read('instructions', 'owners')
    assert len([s for s in statements if s.lstrip().upper().startswith('SELECT')]) < 10


def test_49e_instruction_css_values():
    css = open('static/web/toni/bw-admin.css').read()
    for value in ['.bw-booklet-row{display:flex;align-items:center;gap:12px;min-height:80px}',
                  '.bw-booklet-name{font:600 15px/20px var(--tw-font)}',
                  '.bw-booklet-no{font:400 12px/16px var(--tw-mono);color:var(--tw-text-muted)}',
                  'height:24px;padding:0 10px;border-radius:999px;background:var(--tw-success-soft);font:500 12px var(--tw-font)',
                  'height:56px;min-height:56px;padding:0 16px;border-radius:10px;border:.5px solid var(--tw-accent)']:
        assert value in css


def _csrf(client):
    client.get('/manage/instructions')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def test_49e_fetch_missing_skips_invalid_numbers_and_flashes_info(app, bw):
    with admin.database(bw) as db, db:
        for number in ['good-1', 'bad number!', 'good-2']:
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I',?,?)", (number, number))
    client = logged_in(app)
    result = client.post('/manage/instructions', data={'csrf_token': _csrf(client), 'action': 'fetch_missing'})
    assert result.status_code == 302
    with admin.database(bw) as db:
        assert sorted(r[0] for r in db.execute("SELECT item_no FROM jobs WHERE source='import'")) == ['good-1', 'good-2']
    with client.session_transaction() as session:
        category, message = session['_flashes'][-1]
    assert category == 'info'
    assert message.startswith('Queued 2 identity refreshes, 1 skipped (invalid number: bad number!)')
    assert 'no PDFs are downloaded' in message


def test_49e_fetch_missing_refused_when_read_only(app, bw, monkeypatch):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I','b-1','One')")
    client = logged_in(app)
    token = _csrf(client)
    app.config['BW_READ_ONLY'] = True
    try:
        assert client.post('/manage/instructions', data={'csrf_token': token, 'action': 'fetch_missing'}).status_code == 403
    finally:
        app.config['BW_READ_ONLY'] = False
    with admin.database(bw) as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE source='import'").fetchone()[0] == 0


def test_49e_zero_booklets_shows_no_fetch_button_and_search_finds_fallback_name(app, bw):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(logged_in(app).get('/manage/instructions').get_data(as_text=True), 'html.parser')
    assert soup.select_one('.bw-page-head h1').get_text() == '0 of 0 booklets have a PDF'
    assert not soup.select('.bw-instructions-fetch')
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I','nameless',NULL)")
    soup = BeautifulSoup(logged_in(app).get('/manage/instructions').get_data(as_text=True), 'html.parser')
    row = soup.select_one('.bw-booklet')
    assert row.select_one('.bw-booklet-name').get_text() == 'Instructions' and row['data-name'] == 'nameless Instructions'
    assert not soup.select_one('.bw-instructions-fetch').has_attr('disabled')


def test_49e_booklet_picture_ignores_own_photos(app, bw):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I','b-1','One')")
        db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path,fetched_at) VALUES('I','b-1','bricklink','booklet','data/images/cat.jpg','2026-01-01')")
        catalogue = db.execute('SELECT max(id) FROM item_images').fetchone()[0]
        db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path,fetched_at,copy_id) VALUES('I','b-1','bricklink','own','data/images/own.jpg','2026-02-01','copy')")
    soup = BeautifulSoup(logged_in(app).get('/manage/instructions').get_data(as_text=True), 'html.parser')
    img = soup.select_one('.bw-booklet img')
    assert img['src'].split('?')[0].endswith(f'/{catalogue}') and img['loading'] == 'lazy' and img.has_attr('data-bw-fallback')
