"""Add on a real v3 migrated collection; all transports are offline."""
from contextlib import closing
import io
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from brickwork.core import add
from brickwork.core.connect import connect
from brickwork.core.importer.migrate import migrate
from brickwork.core.pipeline import Pipeline
from brickwork.core.sources import base
from brickwork.core.sources.bricklink_catalogue import load
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps

FIXTURES = Path(__file__).parent / 'fixtures/brickwork'


@pytest.fixture
def bw(app, legacy, monkeypatch):
    migrate(**legacy)
    path = legacy['out_db']
    monkeypatch.setenv('BW_DB_PATH', str(path))
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', lambda: None)
    with closing(connect(path)) as db, db:
        load(FIXTURES, path.with_name('bricklink-catalog.db'), db)
        db.execute("UPDATE colors SET rgb='ABCDEF' WHERE color_id=11")
    # Synthetic catalogue identities match the migration fixture's canonical keys.
    with sqlite3.connect(path.with_name('bricklink-catalog.db')) as cat, cat:
        cat.executemany('INSERT OR IGNORE INTO items VALUES(?,?,?,?,?,NULL)',
            [(k,n,name,name.lower(),None) for k,n,name in [('S','new-set','Synthetic set'),('P','bl-part','Synthetic part'),('M','bl-figure','Synthetic figure')]])
    return path


def client_token(app):
    client = logged_in(app)
    response = client.get('/manage/add')
    assert response.status_code == 200
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    return client, token, response


def preview(client, csrf, **data):
    return client.post('/manage/add/review', json=dict(csrf_token=csrf,type='S',where='owned',mode='paste',text='new-set',**data))


def post_confirm(client, csrf, review, **extra):
    return client.post('/manage/add/confirm',json=dict(csrf_token=csrf,token=review['token'],items=review['items'],**extra))


def counts(path):
    with closing(connect(path, read_only=True)) as db:
        return {t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('items','copies','loose_stock','wishlist','events')}


def test_shell_search_eight_types_and_no_preview_writes(app,bw):
    client,csrf,response = client_token(app)
    html=response.get_data(as_text=True)
    assert 'data-web-ui="toni"' in html and 'One page for everything. Nothing is saved before you confirm.' in html
    assert 'href="/manage/add"' in html
    assert 'Keep photo' in html and 'Catalog' in html and 'Gear' in html and 'Book' in html
    assert response.headers['Cache-Control']=='no-store'
    before=counts(bw)
    for kind in add.TYPES:
        result=client.get('/manage/add/search',query_string={'type':kind,'sort':'name'})
        assert result.status_code==200 and result.json['count']>=1
        assert all(r['item_type']==kind for r in result.json['items'])
    result=client.get('/manage/add/search',query_string={'type':'S','q':'synthetic'})
    assert any(r['item_no']=='new-set' for r in result.json['items'])
    review=preview(client,csrf).json
    assert review['items'][0]['owned']==1
    assert counts(bw)==before
    assert client.post('/manage/add/confirm',json={'csrf_token':csrf,'items':review['items']}).status_code==400
    assert counts(bw)==before


def test_paste_duplicate_notice_confirm_pipeline_and_undo(app,bw):
    client,csrf,_=client_token(app)
    review=client.post('/manage/add/review',json={'csrf_token':csrf,'type':'S','where':'owned','mode':'paste','text':'new-set x2\nunknown\ninvalid!'}).json
    assert len(review['unresolved'])==2 and review['items'][0]['quantity']==2
    assert post_confirm(client,csrf,review).status_code==400
    review['items'][0]['decision']='another'
    review['items'][0]['completeness']='C'
    result=post_confirm(client,csrf,review)
    assert result.status_code==200
    receipt=result.json['receipts'][0]
    assert len(receipt['copies'])==2
    with closing(connect(bw)) as db:
        job=Pipeline(db).status(receipt['job_id'])
        assert len(job['steps'])==6 and job['state']=='queued'
        assert db.execute("SELECT via FROM events WHERE entity='bw_add' AND field='receipt'").fetchone()[0]=='app'
        for identifier in receipt['copies']:
            assert db.execute('SELECT completeness,completeness_source FROM copies WHERE id=?',(identifier,)).fetchone()[:]==('C','manual')
            assert db.execute('SELECT count(*) FROM copy_parts WHERE copy_id=?',(identifier,)).fetchone()[0]==0
    # A lost response cannot create a second batch.
    assert post_confirm(client,csrf,review).json==result.json
    result=client.post('/manage/add/undo',json={'csrf_token':csrf,'batch':result.json['batch']})
    assert result.json['message']=='Undone'
    with closing(connect(bw)) as db:
        assert all(db.execute('SELECT archived_at FROM copies WHERE id=?',(i,)).fetchone()[0] for i in receipt['copies'])
        before=db.execute('SELECT count(*) FROM events').fetchone()[0]
    client.post('/manage/add/undo',json={'csrf_token':csrf,'batch':receipt['batch']})
    with closing(connect(bw)) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0]==before


def test_materializes_inventory_once_and_retry_snapshot(app,bw,monkeypatch):
    client,csrf,_=client_token(app)
    review=preview(client,csrf).json
    review['items'][0]['decision']='another'
    receipt=post_confirm(client,csrf,review).json['receipts'][0]
    from tests.test_brickwork_pipeline import assert_safe_yields
    with closing(connect(bw)) as db, base.audit_origin('app'), app.app_context():
        turns = assert_safe_yields(monkeypatch, db)
        p=Pipeline(db)
        p.handlers={(s,source):lambda *args:None for s in ('identity','inventory','matching','pictures','metadata','market_price') for source in ('bricklink:local','bricklink:api','bricklink:subsets','bricklink','rebrickable','brickset','part_resolutions','manual')}
        with db:
            db.execute("INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,color_id,quantity,extra_quantity,source) VALUES('S','new-set','P','bl-part',11,2,1,'bricklink')")
        assert p.run(receipt['job_id'])['state']=='done'
        rows=db.execute('SELECT spare,quantity,checked FROM copy_parts WHERE copy_id=?',(receipt['copies'][0],)).fetchall()
        assert [r[:] for r in rows]==[(0,2,0),(1,1,0)]
        add.materialize(db,'S','new-set')
        assert turns
        assert db.execute('SELECT count(*) FROM copy_parts WHERE copy_id=?',(receipt['copies'][0],)).fetchone()[0]==2
    response=client.get('/manage/add/jobs/'+str(receipt['job_id']))
    assert response.json['events'][-1]['message']=='Import complete'
    assert 'payload' not in response.get_data(as_text=True)


def test_xml_csv_unresolved_colour_and_loose(app,bw,monkeypatch):
    client,csrf,_=client_token(app)
    xml=b'<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>bl-part</ITEMID><COLOR>11</COLOR><QTY>3</QTY></ITEM><ITEM><ITEMTYPE>M</ITEMTYPE><ITEMID>unknown</ITEMID></ITEM></INVENTORY>'
    result=client.post('/manage/add/review',data={'csrf_token':csrf,'mode':'file','where':'loose','type':'P','file':(io.BytesIO(xml),'inventory.xml')})
    assert result.status_code==200 and len(result.json['unresolved'])==1
    review=result.json
    review['items'][0]['decision']='another'
    assert review['items'][0]['color_id']==11
    receipt=post_confirm(client,csrf,review).json['receipts'][0]
    with closing(connect(bw)) as db:
        assert db.execute('SELECT color_id,quantity FROM loose_stock WHERE id=?',(receipt['stock'][0],)).fetchone()[:]==(11,6)
        assert receipt['stock_changes'][0]['old'][0]['quantity'] == 3
        assert receipt['stock_changes'][0]['quantity'] == 3
    csv=b'part_num,color_id,quantity\nrb-part,71,4\nrb-new,71,2\n'
    monkeypatch.setattr('brickwork.core.sources.rebrickable.Rebrickable.part',lambda self,n: {'part_num':n,'external_ids':{'BrickLink':['bl-part','other-part']}})
    result=client.post('/manage/add/review',data={'csrf_token':csrf,'mode':'file','where':'loose','type':'P','file':(io.BytesIO(csv),'parts.csv')})
    assert result.status_code==200
    assert result.json['items'][0]['item_no']=='bl-part' and result.json['items'][0]['color_id']==11
    assert result.json['unresolved'][0]['number']=='rb-new'
    assert add.file_rows(b'<INVENTORY><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>new-set</ITEMID><MINQTY>2</MINQTY></ITEM></INVENTORY>','wanted.xml','P')[0]['quantity']==2


def test_photo_candidates_explicit_choice_keep_and_source_audit(app,bw,monkeypatch):
    client,csrf,_=client_token(app)
    calls=[]
    def http(request):
        calls.append(request)
        return {'items':[{'type':'set','id':'new-set','score':.9},{'type':'part','id':'bl-part','score':.6}]}
    monkeypatch.setattr(base,'transport',http)
    before=counts(bw)
    response=client.post('/manage/add/review',data={'csrf_token':csrf,'mode':'photo','where':'loose','type':'S','file':(io.BytesIO((FIXTURES/'import-image.png').read_bytes()),'photo.png')})
    assert response.status_code==200 and response.json['candidates']
    review=response.json
    assert review['items'][0]['score']==.9
    assert counts(bw)['loose_stock']==before['loose_stock']
    assert post_confirm(client,csrf,review).status_code==400
    review['items']=[review['items'][0]]
    review['items'][0]['decision']='another'
    receipt=post_confirm(client,csrf,review,candidate=0,keep_photo=True).json['receipts'][0]
    assert calls[0].full_url=='https://api.brickognize.com/predict/'
    with closing(connect(bw)) as db:
        image=db.execute("SELECT * FROM item_images WHERE kind='own'").fetchone()
        assert image['stock_id']==receipt['stock'][0]
        assert (bw.parent/image['local_path']).is_file()
        assert db.execute("SELECT count(*) FROM source_records WHERE source='brickognize' AND kind='predict'").fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM events WHERE entity='source:source_records' AND via='app'").fetchone()[0]>=1
    assert client.get('/manage/images/'+str(image['id'])).status_code==200


def test_guard_tamper_csrf_and_atomic_event_rollback(app,bw):
    client,csrf,_=client_token(app)
    assert client.post('/manage/add/review',json={'text':'new-set'}).status_code==400
    review=preview(client,csrf).json
    assert post_confirm(client,csrf,{**review,'token':review['token']+'tamper'}).status_code==400
    review['items'][0]['decision']='another'
    before=counts(bw)
    with closing(connect(bw)) as db, db:
        db.execute("CREATE TRIGGER reject_add BEFORE INSERT ON events WHEN NEW.entity='bw_add' BEGIN SELECT RAISE(ABORT,'no'); END")
    assert post_confirm(client,csrf,review).status_code==400
    after=counts(bw)
    assert all(after[k]==before[k] for k in ('items','copies','loose_stock','wishlist'))


def test_catalogue_skips_hidden_appledouble(tmp_path):
    directory=tmp_path/'catalogue';shutil.copytree(FIXTURES,directory)
    (directory/'._Sets.xml').write_bytes(b'not xml')
    (directory/'.hidden.xml').write_text('<invalid/>')
    with closing(connect(tmp_path/'brickwork.db')) as db:
        metadata=load(directory,tmp_path/'bricklink-catalog.db',db)
        assert set(metadata['counts'])==set(add.TYPES)
        assert not any(row['name'].startswith('.') for row in metadata['sources'])


def test_wishlist_duplicate_skip_and_quantity_preserved(app,bw):
    client,csrf,_=client_token(app)
    review=client.post('/manage/add/review',json={'csrf_token':csrf,'type':'G','where':'wishlist','mode':'paste','text':'123-1 x3'}).json
    result=post_confirm(client,csrf,review)
    assert result.status_code==200
    with closing(connect(bw)) as db:
        assert db.execute("SELECT quantity,note FROM wishlist WHERE item_type='G' AND item_no='123-1'").fetchone()[:]==(3,None)
    duplicate=client.post('/manage/add/review',json={'csrf_token':csrf,'type':'G','where':'wishlist','mode':'paste','text':'123-1'}).json
    assert duplicate['items'][0]['wished']
    assert post_confirm(client,csrf,duplicate).status_code==400
    duplicate['items'][0]['decision']='skip'
    assert post_confirm(client,csrf,duplicate).json['receipts']==[]
    client.post('/manage/add/undo',json={'csrf_token':csrf,'batch':result.json['batch']})
    with closing(connect(bw)) as db:
        assert db.execute("SELECT archived_at FROM wishlist WHERE item_type='G' AND item_no='123-1'").fetchone()[0]


def test_part_colour_guard_search_confirmation_and_jobs_retry(app,bw):
    client,csrf,_=client_token(app)
    review=client.post('/manage/add/review',json={'csrf_token':csrf,'type':'P','where':'loose','mode':'search','items':[{'item_type':'P','item_no':'123-1','name':'Forged name'}]}).json
    assert review['items'][0]['name']!='Forged name'
    assert post_confirm(client,csrf,review).status_code==400
    review['items'][0]['color_id']=11
    response=post_confirm(client,csrf,review)
    assert response.status_code==200
    job=response.json['receipts'][0]['job_id']
    with closing(connect(bw)) as db, db:
        db.execute("UPDATE jobs SET state='failed' WHERE id=?",(job,))
        db.execute("UPDATE import_steps SET state='failed',error='Fixture failure' WHERE job_id=? AND name='pictures'",(job,))
    result=client.get(f'/manage/add/jobs/{job}')
    assert any(e['retry'] for e in result.json['events'] if e['step'])
    assert client.post(f'/manage/add/jobs/{job}/retry',json={'csrf_token':csrf,'step':'pictures'}).status_code==200
    with closing(connect(bw)) as db:
        assert db.execute("SELECT state FROM import_steps WHERE job_id=? AND name='pictures'",(job,)).fetchone()[0]=='queued'


def test_photo_budget_and_not_keep(app,bw,monkeypatch):
    client,csrf,_=client_token(app)
    monkeypatch.setattr(base,'transport',lambda request:{'items':[{'type':'set','id':'new-set','score':.9},{'type':'part','id':'not-in-catalogue','score':.4}]})
    photo=(FIXTURES/'import-image.png').read_bytes()
    def photo_review():
        return client.post('/manage/add/review',data={'csrf_token':csrf,'mode':'photo','where':'loose','type':'S','file':(io.BytesIO(photo),'photo.png')})
    review=photo_review().json
    assert review['unresolved'][0]['number']=='not-in-catalogue'
    review['items'][0]['decision']='another'
    response=post_confirm(client,csrf,review,candidate=0,keep_photo=False)
    assert response.status_code==200
    with closing(connect(bw)) as db:
        assert db.execute("SELECT count(*) FROM item_images WHERE kind='own'").fetchone()[0]==0
    monkeypatch.setenv('BW_BRICKOGNIZE_DAILY_BUDGET','1')
    assert photo_review().status_code==400
    with closing(connect(bw)) as db:
        assert db.execute("SELECT state FROM jobs WHERE source='brickognize' ORDER BY id DESC LIMIT 1").fetchone()[0]=='waiting_for_budget'


def test_partial_batch_retry_does_not_repeat_committed_item(app,bw):
    client,csrf,_=client_token(app)
    review=client.post('/manage/add/review',json={'csrf_token':csrf,'type':'S','where':'loose','mode':'paste','text':'123-1\nnew-set'}).json
    review['items'][1]['decision']='another'
    with closing(connect(bw)) as db, db:
        db.execute("CREATE TRIGGER reject_second BEFORE INSERT ON loose_stock WHEN NEW.item_no='new-set' BEGIN SELECT RAISE(ABORT,'fixture'); END")
    before=counts(bw)['loose_stock']
    assert post_confirm(client,csrf,review).status_code==400
    assert counts(bw)['loose_stock']==before+1
    with closing(connect(bw)) as db, db:
        db.execute('DROP TRIGGER reject_second')
    result=post_confirm(client,csrf,review)
    assert result.status_code==200 and len(result.json['receipts'])==2
    assert counts(bw)['loose_stock']==before+2


def test_part_wishlist_preserves_colour_condition_and_restores_archive(app,bw):
    client,csrf,_=client_token(app)
    with closing(connect(bw)) as db, db:
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P','123-1','Part')")
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity,note,condition,archived_at,updated_at) VALUES('P','123-1',11,7,'Keep this note','any','2020-01-01','2020-01-01')")
    review=client.post('/manage/add/review',json={'csrf_token':csrf,'type':'P','where':'wishlist','mode':'paste','text':'123-1 x2'}).json
    review['items'][0].update(color_id=11,condition='N')
    result=post_confirm(client,csrf,review)
    assert result.status_code==200
    with closing(connect(bw)) as db:
        wish=db.execute("SELECT * FROM wishlist WHERE item_type='P' AND item_no='123-1'").fetchone()
        assert wish['condition']=='new' and wish['archived_at'] is None
        assert wish['note']=='Keep this note'
        assert wish['color_id']==11 and wish['quantity']==2
    client.post('/manage/add/undo',json={'csrf_token':csrf,'batch':result.json['batch']})
    with closing(connect(bw)) as db:
        assert db.execute("SELECT note,condition,archived_at,quantity FROM wishlist WHERE item_type='P' AND item_no='123-1'").fetchone()[:]==('Keep this note','any','2020-01-01',7)


def test_part_wish_xml_quantity_duplicates_colour_and_undo(app,bw):
    client,csrf,_=client_token(app)
    xml=b'<WANTEDLIST><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>123-1</ITEMID><COLOR>11</COLOR><MINQTY>3</MINQTY></ITEM></WANTEDLIST>'
    review=client.post('/manage/add/review',data={'csrf_token':csrf,'type':'P','where':'wishlist','mode':'file','file':(io.BytesIO(xml),'wanted.xml')}).json
    review['items'][0]['note']='User note'
    first=post_confirm(client,csrf,review)
    assert first.status_code==200
    duplicate=client.post('/manage/add/review',data={'csrf_token':csrf,'type':'P','where':'wishlist','mode':'file','file':(io.BytesIO(xml),'wanted.xml')}).json
    assert duplicate['items'][0]['wished']
    assert post_confirm(client,csrf,duplicate).status_code==400
    duplicate['items'][0]['decision']='another'
    second=post_confirm(client,csrf,duplicate)
    assert second.status_code==200
    with closing(connect(bw)) as db:
        assert db.execute("SELECT color_id,quantity,note FROM wishlist WHERE item_no='123-1'").fetchone()[:] == (11,6,'User note')
        assert Pipeline(db).colors('P','123-1')==[11]
    assert client.post('/manage/add/undo',json={'csrf_token':csrf,'batch':second.json['batch']}).status_code==200
    different=client.post('/manage/add/review',json={'csrf_token':csrf,'type':'P','where':'wishlist','mode':'search','items':[{'item_type':'P','item_no':'123-1','color_id':0,'quantity':2}]}).json
    assert not different['items'][0]['wished']
    assert post_confirm(client,csrf,different).status_code==200
    with closing(connect(bw)) as db:
        assert [tuple(r) for r in db.execute("SELECT color_id,quantity,note FROM wishlist WHERE item_no='123-1' ORDER BY id")] == [(11,3,'User note'),(0,2,None)]
        assert all(r[0]=='app' for r in db.execute("SELECT via FROM events WHERE field IN ('added','undo_add')"))
    with app.test_request_context('/'):
        from brickwork.web.ui import navigation_counts
        assert navigation_counts()['Wishlist']==3  # legacy migrated set plus two colours


def test_49e_add_search_has_no_chip_count_or_sort_caption(app, bw):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(client_token(app)[2].get_data(as_text=True), 'html.parser')
    for selector in ['[data-chips]', '[data-result-count]', '.bw-add-result-sort']:
        assert soup.select_one('[data-mode=search] ' + selector).has_attr('hidden')
