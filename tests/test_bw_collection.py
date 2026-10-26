"""Collection routes use the migrated fixture, with bounded read/save queries."""
from io import BytesIO
import json
import re
from pathlib import Path
import sqlite3

from bs4 import BeautifulSoup
from PIL import Image
import pytest

from brickwork.core import admin, collection, workbench, checker
from brickwork.core.importer.migrate import migrate
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.test_bw_admin import reset_shell_metadata_after_test


@pytest.fixture
def bw(legacy, monkeypatch):
    migrate(**legacy)
    monkeypatch.setenv('BW_DB_PATH',str(legacy['out_db']))
    return legacy['out_db']


def token(client):
    client.get('/collection/sets')
    with client.session_transaction() as s: return s['bw_add_csrf']


def post(client,csrf,action,**data):
    return client.post('/collection/save/'+action,json=dict(csrf_token=csrf,**data))


def test_edit_flags_manual_derived_archive_undo(app,bw):
    client=logged_in(app);csrf=token(client)
    with admin.database(bw) as db:
        old=dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
        with db: checker.checked_flag(db,create=True)
        flags=[r[0] for r in db.execute("SELECT id FROM flags WHERE kind='status' AND name='Set is checked'")]
        assert flags
    r=post(client,csrf,'save',entity='copy',ids=['copy'],values=dict(condition='U',completeness='C',completeness_source='manual',storage_id='',flags=flags,note='New note'))
    assert r.status_code==200,r.json
    with admin.database(bw) as db:
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='C'
        assert db.execute('SELECT via FROM events WHERE id=?',(r.json['event_id'],)).fetchone()[0]=='app'
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db: assert dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())==old
    r=post(client,csrf,'save',entity='copy',ids=['copy'],values=dict(completeness_source='derived',completeness='C',flags=flags))
    assert r.status_code==200
    with admin.database(bw) as db: assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='I'
    archived=post(client,csrf,'archive',entity='copy',ids=['copy'],values={})
    assert archived.json['message']=='Set deleted'
    assert client.get('/collection/item/S/new-set?copy=copy').status_code==404
    assert post(client,csrf,'undo',event_id=archived.json['event_id']).status_code==200
    assert client.get('/collection/item/S/new-set?copy=copy').status_code==200
    with admin.database(bw) as db:
        assert db.execute("SELECT count(*) FROM copy_parts WHERE copy_id='copy'").fetchone()[0]>0
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_wish_colour_quantity_and_conflict(app,bw):
    with admin.database(bw) as db,db:
        w=db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity,condition) VALUES('P','bl-part',11,2,'any')").lastrowid
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity) VALUES('P','bl-part',0,1)")
    client=logged_in(app);csrf=token(client)
    assert client.get('/collection/wishes/'+str(w)).status_code==200
    r=post(client,csrf,'save',entity='wish',ids=[w],values={'quantity':7,'max_price':'0.1200','condition':'used'})
    assert r.status_code==200
    with admin.database(bw) as db: assert tuple(db.execute('SELECT color_id,quantity,max_price FROM wishlist WHERE id=?',(w,)).fetchone())==(11,7,'0.1200')
    assert post(client,csrf,'save',entity='wish',ids=[w],values={'color_id':0}).status_code==400
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200


def test_lot_storage_bulk_and_places(app,bw):
    with admin.database(bw) as db,db:
        db.execute("INSERT INTO lots(id,name,note) VALUES('lot','Pile A','Private lot note')")
        db.execute("INSERT INTO storages(id,name,archived_at) VALUES('archived','Old place','2026-01-01')")
        db.execute("UPDATE loose_stock SET lot_id='lot' WHERE id='loose-part'")
    client=logged_in(app);csrf=token(client)
    r=client.get('/collection/lots/lot')
    assert r.status_code==200 and b'Private lot note' in r.data
    html=client.get('/collection/P').get_data(as_text=True)
    soup=BeautifulSoup(html,'html.parser')
    assert not soup.select('[data-bc-filter="storage"] option[value="archived"]')
    assert post(client,csrf,'save',entity='stock',ids=['loose-part'],values={'storage_id':'archived'}).status_code==400
    r=post(client,csrf,'save',entity='stock',ids=['loose-part'],values={'storage_id':'','condition':'U','lot_id':'lot'})
    assert r.status_code==200
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    r=post(client,csrf,'save',entity='lot',ids=['lot'],values={'name':'Pile B'})
    assert r.status_code==200
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db:
        places=collection.purchase_places(db)
        assert places[0]['totals']['Currency not recorded']==collection.Decimal('12.345')


def test_matching_transfer_completes_and_undo(app,bw):
    with admin.database(bw) as db,db:
        db.execute("UPDATE copies SET completeness_source='derived',completeness='I'")
        db.execute('UPDATE copy_parts SET missing=0,damaged=0')
        db.execute('UPDATE copy_minifigs SET missing=0')
        p=db.execute("SELECT id FROM copy_parts WHERE item_type='P' AND item_no='bl-part' AND parent_minifig IS NULL").fetchone()[0]
        db.execute('UPDATE copy_parts SET missing=1 WHERE id=?',(p,))
        checked=checker.checked_flag(db,create=True)
        db.execute("INSERT OR IGNORE INTO item_flags VALUES('copy','copy',?)",(checked,))
    client=logged_in(app);csrf=token(client)
    r=client.get('/collection/item/P/bl-part?colour=11')
    assert r.status_code==200 and b'Completes set' in r.data
    r=post(client,csrf,'transfer',source_id='loose-part',copy_id='copy',target='part',target_id=p,quantity=1)
    assert r.status_code==200,r.json
    with admin.database(bw) as db: assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='C'
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db: assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(p,)).fetchone()[0]==1


def test_own_photo_caption_lightbox_undo(app,bw):
    client=logged_in(app);csrf=token(client)
    buffer=BytesIO();Image.new('RGB',(4,3),'white').save(buffer,'PNG')
    r=client.post('/collection/save/photo',data={'csrf_token':csrf,'entity':'copy','identifier':'copy','caption':'At home','photo':(BytesIO(buffer.getvalue()),'home.png')})
    assert r.status_code==200,r.json
    with admin.database(bw) as db:
        image=dict(db.execute("SELECT * FROM item_images WHERE kind='own'").fetchone())
        assert (bw.parent/image['local_path']).is_file()
        assert image['taken_at'] is None # Upload time does not establish when the photo was taken.
    html=client.get('/collection/item/S/new-set?copy=copy').get_data(as_text=True)
    assert 'At home' in html and 'bc-lightbox' in html
    panel=BeautifulSoup(html,'html.parser').select_one('dialog#bc-edit')
    assert panel.select_one('.bc-own-photos form[data-bc-action=photo] [data-bc-photo-file]') and 'At home' in panel.select_one('.bc-own-photos').get_text()
    assert client.get('/manage/images/'+str(image['id'])).status_code==200
    c=post(client,csrf,'caption',identifier=image['id'],caption='Finished')
    assert c.status_code==200
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==400
    assert post(client,csrf,'undo',event_id=c.json['event_id']).status_code==200
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db: assert not db.execute("SELECT 1 FROM item_images WHERE kind='own'").fetchone()
    assert (bw.parent/image['local_path']).is_file() # Photo bytes are retained, association reversed.


def test_readonly_csrf_validation_and_receipt_rollback(app,bw):
    client=logged_in(app);csrf=token(client)
    assert post(client,'wrong','archive',entity='copy',ids=['copy']).status_code==400
    app.config['BW_READ_ONLY']=True
    assert b'Read only' in client.get('/collection/P').data
    assert post(client,csrf,'archive',entity='copy',ids=['copy']).status_code==403
    app.config['BW_READ_ONLY']=False
    with admin.database(bw) as db:
        db.execute("CREATE TRIGGER reject_collection BEFORE INSERT ON events WHEN new.entity='bw_collection' BEGIN SELECT RAISE(ABORT,'receipt failed'); END")
        with pytest.raises(sqlite3.IntegrityError): collection.save(db,'copy',['copy'],{'note':'Must roll back'})
        assert db.execute("SELECT note FROM copies WHERE id='copy'").fetchone()[0]=='Private note'


@pytest.mark.parametrize('kind',list(collection.TYPES))
def test_list_and_batch_save_query_count_is_constant(bw,kind):
    with admin.database(bw) as db:
        def grow(start,end):
            with db:
                db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P','bl-part',11,1,'U')",[(f'cost-{n}',) for n in range(start,end)])
                db.executemany("INSERT INTO copies(id,item_type,set_no,completeness_source) VALUES(?,'S','new-set','derived')",[(f'copy-{n}',) for n in range(start,end)])
        def measured(call):
            queries=[];db.set_trace_callback(queries.append)
            try: result=call()
            finally: db.set_trace_callback(None)
            return len(queries),result
        grow(0,100)
        small,rows=measured(lambda:collection.listing(db,kind))
        save_small,event=measured(lambda:collection.save(db,'stock',[f'cost-{n}' for n in range(100)],{'storage_id':None}))
        collection.undo(db,event)
        copy_small,event=measured(lambda:collection.save(db,'copy',[f'copy-{n}' for n in range(100)],{'condition':'U'}))
        collection.undo(db,event)
        grow(100,300)
        large,_=measured(lambda:collection.listing(db,kind))
        save_large,_=measured(lambda:collection.save(db,'stock',[f'cost-{n}' for n in range(300)],{'storage_id':None}))
        copy_large,_=measured(lambda:collection.save(db,'copy',[f'copy-{n}' for n in range(300)],{'condition':'U'}))
        assert large==small and large<25
        assert save_large==save_small and save_large<20
        assert copy_large==copy_small and copy_large<20


def test_loose_minifigure_gaps_share_transfer_and_undo(app,bw):
    with admin.database(bw) as db,db:
        db.execute("UPDATE loose_minifig_parts SET missing=1,damaged=0,spare=0 WHERE stock_id='loose-figure'")
        part=dict(db.execute("SELECT * FROM loose_minifig_parts WHERE stock_id='loose-figure'").fetchone())
        assert part['item_no']=='bl-part' and part['color_id']==11
    with admin.database(bw) as db:
        assert any(r['target']=='stock-part' for r in workbench.matches(db)),workbench.gaps(db)
    client=logged_in(app);csrf=token(client)
    r=client.get('/collection/item/M/bl-figure?stock=loose-figure')
    assert r.status_code==200 and b'Loose minifigure' in r.data and b'Take 1' in r.data
    payload=dict(source_id='loose-part',copy_id='loose-figure',target='stock-part',target_id=['P','bl-part',11,0],quantity=1)
    r=post(client,csrf,'transfer',**payload)
    assert r.status_code==200,r.json
    with admin.database(bw) as db:
        assert db.execute("SELECT missing FROM loose_minifig_parts WHERE stock_id='loose-figure'").fetchone()[0]==0
        assert db.execute("SELECT copy_id FROM match_history WHERE kind='stock-part'").fetchone()[0] is None
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert post(client,csrf,'transfer',**payload).status_code==400
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db: assert db.execute("SELECT missing FROM loose_minifig_parts WHERE stock_id='loose-figure'").fetchone()[0]==1


def test_matching_and_jump_queries_are_bounded(bw):
    with admin.database(bw) as db:
        def measured(call):
            queries=[];db.set_trace_callback(queries.append)
            try: call()
            finally: db.set_trace_callback(None)
            return len(queries)
        small=measured(lambda:workbench.matches(db));search_small=measured(lambda:collection.search(db,'part'))
        with db:
            db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P','bl-part',11,1,'U')",[(f'bounded-{n}',) for n in range(300)])
        assert measured(lambda:workbench.matches(db))==small
        assert measured(lambda:collection.search(db,'part'))==search_small
        assert small<30 and search_small<20


def test_new_lot_preserves_quantity_and_undo_archives_lot(app,bw):
    client=logged_in(app);csrf=token(client)
    r=post(client,csrf,'lot',ids=['loose-part'],name='Pile C',note='Receipt note',storage_id='store')
    assert r.status_code==200,r.json
    with admin.database(bw) as db:
        lot=db.execute("SELECT lot_id FROM loose_stock WHERE id='loose-part'").fetchone()[0]
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='loose-part'").fetchone()[0]==3
        assert db.execute('SELECT name FROM lots WHERE id=?',(lot,)).fetchone()[0]=='Pile C'
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db:
        assert db.execute("SELECT lot_id FROM loose_stock WHERE id='loose-part'").fetchone()[0] is None
        assert db.execute('SELECT archived_at FROM lots WHERE id=?',(lot,)).fetchone()[0]


@pytest.mark.parametrize('field,start,end', [
    ('storage_id', None, 'store'), ('lot_id', None, 'merge-lot'), ('condition', None, 'U')])
def test_stock_edit_merges_and_undo_restores_exact_rows(app, bw, field, start, end):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO lots(id,name) VALUES('merge-lot','Merge lot')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,note) VALUES('destination','P','bl-part',11,7,'U','Destination note')")
        db.execute('UPDATE loose_stock SET '+field+'=? WHERE id=?', (end, 'destination'))
        db.execute('UPDATE loose_stock SET '+field+'=? WHERE id=?', (start, 'loose-part'))
        before = collection.snapshot(db, 'loose_stock', ['destination', 'loose-part'])
    client = logged_in(app); csrf = token(client)
    response = post(client, csrf, 'save', entity='stock', ids=['loose-part'], values={field: end})
    assert response.status_code == 200, response.json
    assert response.json['message'] == 'Merged into existing stock'
    assert response.json['merged_ids'] == ['destination']
    assert 'stock=destination' in response.json['url']
    assert client.get(response.json['url']).status_code == 200
    with admin.database(bw) as db:
        rows = collection.snapshot(db, 'loose_stock', ['destination', 'loose-part'])
        assert rows[0]['quantity'] == 10 and rows[0]['note'] == 'Destination note'
        assert rows[1]['archived_at'] and rows[1]['quantity'] == 3
        events = db.execute("SELECT * FROM events WHERE field='merge' ORDER BY entity").fetchall()
        assert [r['entity'] for r in events] == ['stock:destination', 'stock:loose-part']
        assert all(r['via']=='app' for r in events)
        assert [json.loads(r['old_value']) for r in events] == before
        assert [json.loads(r['new_value']) for r in events] == rows
    assert post(client, csrf, 'undo', event_id=response.json['event_id']).status_code == 200
    with admin.database(bw) as db:
        assert collection.snapshot(db, 'loose_stock', ['destination', 'loose-part']) == before


def test_minifigure_edit_never_merges_and_archive_does_not_merge(bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition,storage_id) VALUES('other-figure','M','bl-figure',4,'U','store')")
    with admin.database(bw) as db:
        before = collection.snapshot(db, 'loose_stock', ['loose-figure', 'other-figure'])
        event = collection.save(db, 'stock', ['loose-figure'], {'storage_id':'store'})
        rows = collection.snapshot(db, 'loose_stock', ['loose-figure', 'other-figure'])
        assert all(not r['archived_at'] for r in rows)
        assert [r['quantity'] for r in rows] == [2,4]
        assert collection.merge_result(db,event) == []
        collection.undo(db,event)
        assert collection.snapshot(db, 'loose_stock', ['loose-figure', 'other-figure']) == before
        event = collection.save(db,'stock',['loose-figure'],{},archive=True)
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='other-figure'").fetchone()[0] == 4
        collection.undo(db,event)


@pytest.mark.parametrize('count', [100,300])
def test_bulk_collisions_merge_in_constant_queries_and_undo(bw,count):
    with admin.database(bw) as db, db:
        db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,storage_id) VALUES(?,'P','bl-part',11,2,'N','store')", [(f'merge-{n:03}',) for n in range(count)])
    with admin.database(bw) as db:
        ids = [f'merge-{n:03}' for n in range(count)]
        before = collection.snapshot(db,'loose_stock',ids)
        queries = []; db.set_trace_callback(queries.append)
        try:
            event = collection.save(db,'stock',list(reversed(ids)),{'storage_id':None})
        finally:
            db.set_trace_callback(None)
        from itertools import groupby
        assert len([q for q, _ in groupby(queries)]) == 11
        rows = collection.snapshot(db,'loose_stock',ids)
        assert rows[0]['quantity'] == 2*count and not rows[0]['archived_at']
        assert all(r['archived_at'] for r in rows[1:])
        assert db.execute("SELECT count(*) FROM events WHERE field='merge'").fetchone()[0] == count
        # A later destination edit blocks Undo atomically.
        later = collection.save(db,'stock',[ids[0]],{'note':'Later'})
        with pytest.raises(ValueError, match='undo the later save first'):
            collection.undo(db,event)
        collection.undo(db,later)
        collection.undo(db,event)
        assert collection.snapshot(db,'loose_stock',ids) == before


def test_merge_receipt_failure_rolls_back_destination_and_source(bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('rollback-destination','P','bl-part',11,5,'U')")
        db.execute("UPDATE loose_stock SET condition=NULL WHERE id='loose-part'")
        db.execute("CREATE TRIGGER reject_merge BEFORE INSERT ON events WHEN new.field='merge' BEGIN SELECT RAISE(ABORT,'merge receipt failed'); END")
    with admin.database(bw) as db:
        before = collection.snapshot(db,'loose_stock',['loose-part','rollback-destination'])
        with pytest.raises(sqlite3.IntegrityError):
            collection.save(db,'stock',['loose-part'],{'condition':'U'})
        assert collection.snapshot(db,'loose_stock',['loose-part','rollback-destination']) == before


def test_merge_does_not_invent_unrecorded_quantity(bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,condition) VALUES('unknown-quantity','P','bl-part',11,'N')")
    with admin.database(bw) as db:
        before = collection.snapshot(db,'loose_stock',['loose-part','unknown-quantity'])
        with pytest.raises(ValueError, match='quantity is not recorded'):
            collection.save(db,'stock',['loose-part'],{'condition':'N'})
        assert collection.snapshot(db,'loose_stock',['loose-part','unknown-quantity']) == before


@pytest.mark.parametrize('missing,damaged,checks,expected', [
    ((2, 3), (1, 2), (1, 0), (5, 3, 1)),
    ((None, 3), (None, None), (0, 1), (3, None, 0)),
    ((None, None), (0, None), (None, 1), (None, 0, None)),
    ((0, 0), (None, 1), (1, 1), (0, 1, 1)),
])
def test_stock_merge_defects_and_checked_exact_undo(bw, missing, damaged, checks, expected):
    with admin.database(bw) as db:
        with db:
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('destination','P','bl-part',11,7,'U')")
            db.execute("UPDATE loose_stock SET condition='N' WHERE id='loose-part'")
            for i, identifier in enumerate(('destination', 'loose-part')):
                db.execute('UPDATE loose_stock SET missing=?,damaged=?,checked=? WHERE id=?',
                           (missing[i], damaged[i], checks[i], identifier))
        before = collection.snapshot(db, 'loose_stock', ['destination', 'loose-part'])
        receipt = collection.save(db, 'stock', ['loose-part'], {'condition': 'U'})
        destination = db.execute("SELECT missing,damaged,checked FROM loose_stock WHERE id='destination'").fetchone()
        assert tuple(destination) == expected
        collection.undo(db, receipt)
        assert collection.snapshot(db, 'loose_stock', ['destination', 'loose-part']) == before


@pytest.mark.parametrize('count',[150,300])
def test_catalogue_name_refresh_retained_fallback_and_bounded_reads(bw,count):
    from brickwork.core.names import refresh
    with admin.database(bw) as db:
        catalogue=bw.with_name('bricklink-catalog.db')
        with sqlite3.connect(catalogue) as cat:
            cat.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT)')
            cat.executemany('INSERT INTO items VALUES(?,?,?)', [('P',f'part-{i}',f'Part {i}') for i in range(count)])
            cat.execute("INSERT INTO items VALUES('P','bl-part','Canonical part')")
        with db:
            db.executemany('INSERT INTO items(item_type,item_no) VALUES(?,?)',[('P',f'part-{i}') for i in range(count)])
            db.execute("UPDATE items SET name=NULL")
        queries=[]
        db.set_trace_callback(queries.append)
        try:
            from brickwork.core.sources.base import audit_origin
            with db, audit_origin('app'):
                refresh(db,catalogue)
        finally:
            db.set_trace_callback(None)
        assert len(queries)<65*(count+10)
        assert len([q for q in queries if q.lstrip().upper().startswith('SELECT')]) < 10
        assert db.execute("SELECT name FROM items WHERE item_no='bl-part'").fetchone()[0] == 'Canonical part'
        assert db.execute("SELECT name FROM items WHERE item_no='bl-figure'").fetchone()[0] == 'Invented rb-figure'
        event=db.execute("SELECT old_value,new_value FROM events WHERE entity='item-name:P:bl-part' AND via='app'").fetchone()
        assert json.loads(event['old_value'])['item']['name'] is None
        assert json.loads(event['new_value'])['name'] == 'Canonical part'


def test_colours_trigger_uses_source_client_and_app_events(app,bw,monkeypatch):
    from brickwork.core.sources.bricklink import BrickLink
    seen=[]
    def mocked(self,path,params=None,normalize=None,job_id=None):
        seen.append(path)
        with self.db:
            return normalize([dict(color_id=11,color_name='Blue',color_type='Solid',color_code='aBcDeF')])
    monkeypatch.setattr(BrickLink,'call',mocked)
    client=logged_in(app)
    response=client.post('/manage/catalogues',data={'action':'colours','csrf_token':token(client)})
    assert response.status_code==302
    assert seen==['/colors']
    with admin.database(bw) as db:
        assert db.execute('SELECT rgb FROM colors WHERE color_id=11').fetchone()[0]=='ABCDEF'
        row=db.execute("SELECT old_value,new_value FROM events WHERE entity='color:11' AND via='app'").fetchone()
        assert json.loads(row['new_value'])['rgb']=='ABCDEF'
    assert '1 with RGB' in client.get('/manage/catalogues').get_data(as_text=True)


@pytest.fixture
def collection_chromium_geometry(app, bw, tmp_path):
    """Measure shipped shell/page CSS, including native disclosure layout."""
    import subprocess
    from pathlib import Path
    import os
    executable = os.environ.get('BW_COLLECTION_CHROME')
    if not executable:
        pytest.skip('Set BW_COLLECTION_CHROME for opt-in browser geometry verification')
    chrome = Path(executable)
    with admin.database(bw) as db, db:
        db.execute("UPDATE copies SET note=?,condition='U' WHERE id='copy'", ('Long private note ' * 30,))
        add_47f_inventory_parts(db)
        add_49a_long_figure(db)
        db.execute("UPDATE copy_parts SET missing=1 WHERE copy_id='copy' AND item_no='bl-part' AND parent_minifig IS NULL")
        original = dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
        db.execute('INSERT INTO copies('+','.join(original)+') VALUES('+','.join('?' for _ in original)+')', tuple(dict(original, id='chip-copy-1').values()))
        db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,sold,min,max,source,observed_at) VALUES('S','new-set',NULL,'U','sold','EUR','25',2,'1','50','bricklink','2022-01-01')")
    client = logged_in(app)
    for kind in ['S', 'M', 'P', 'I', 'detail']:
        route = '/collection/item/S/new-set?copy=copy' if kind == 'detail' else '/collection/' + kind
        response = client.get(route)
        assert response.status_code == 200
        soup = BeautifulSoup(response.data, 'html.parser')
        for link in soup.select('link[rel=stylesheet]'):
            from urllib.parse import urlsplit
            css_path = Path(urlsplit(link['href']).path.lstrip('/'))
            style = soup.new_tag('style')
            style.string = css_path.read_text()
            link.replace_with(style)
        for script in soup.select('script'):
            if script.get('type') == 'application/json':
                continue
            if 'formatting.js' in script.get('src', ''):
                script.attrs.clear()
                script.string = Path('static/web/toni/formatting.js').read_text()
                soup.body.append(script.extract())
            elif 'bw-collection.js' in script.get('src', ''):
                script.attrs.clear()
                script.string = Path('static/web/toni/bw-collection.js').read_text()
                # Defer until the fixture DOM exists.
                soup.body.append(script.extract())
            else:
                script.decompose()
        (tmp_path / (kind + '.html')).write_text(str(soup))
    result = subprocess.run(['node', 'tests/toni_bw_collection_geometry.cjs', str(chrome), str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[0])


def test_run4_info_edit_instructions_and_archive(app, bw):
    client = logged_in(app)
    csrf = token(client)
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    info = soup.select_one('[data-module=info]')
    assert info.h2.get_text() == 'Info'
    assert info.select_one('.bc-info-edit .icon')
    assert not info.select('.bc-source-details, a')
    assert len(soup.select('.bc-info-edit[data-bw-open=bc-edit]')) == 1
    assert soup.select_one('#bc-edit .bc-source-details')
    assert soup.select_one('#bc-edit [data-bw-open=bc-delete]').get_text() == 'Delete set'
    assert not soup.select_one('.bc-detail-hero [data-bw-open=bc-delete]')
    extras = soup.select_one('[data-bc-tab-extras]')
    assert extras.has_attr('hidden')
    assert extras.select_one('a[href="/manage/instructions"]')
    archive = soup.select_one('#bc-delete form')
    assert archive['data-bc-action'] == 'archive'
    assert json.loads(archive['data-identity']) == {'entity': 'copy', 'ids': ['copy']}
    assert soup.select_one('#bc-delete [data-bw-close]').get_text() == 'Keep it'
    response = post(client, csrf, 'archive', entity='copy', ids=['copy'])
    assert response.status_code == 200
    with admin.database(bw) as db:
        assert db.execute("SELECT archived_at FROM copies WHERE id='copy'").fetchone()[0]
        event = db.execute('SELECT * FROM events WHERE id=?', (response.json['event_id'],)).fetchone()
        assert event['via'] == 'app'
    assert post(client, csrf, 'undo', event_id=response.json['event_id']).status_code == 200
    with admin.database(bw) as db:
        assert db.execute("SELECT archived_at FROM copies WHERE id='copy'").fetchone()[0] is None


def test_run4_estimate_existing_save_event_undo(app, bw):
    with admin.database(bw) as db:
        old = tuple(db.execute("SELECT current_value,current_value_currency FROM copies WHERE id='copy'").fetchone())
    client = logged_in(app)
    csrf = token(client)
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    footer = soup.select_one('.bc-price-footer')
    assert 'With box:' in footer.get_text() and '5.00' in footer.get_text()
    assert footer.select_one('[data-bw-open=bc-edit]')['data-bc-focus'] == 'current_value'
    assert soup.select_one('#bc-edit input[name=current_value]')
    response = post(client, csrf, 'save', entity='copy', ids=['copy'], values={'current_value':'0','current_value_currency':'EUR'})
    assert response.status_code == 200
    with admin.database(bw) as db:
        event = db.execute('SELECT * FROM events WHERE id=?', (response.json['event_id'],)).fetchone()
        assert event['via'] == 'app'
        assert db.execute("SELECT current_value FROM copies WHERE id='copy'").fetchone()[0] == '0'
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data,'html.parser')
    assert '€0.00' in soup.select_one('.bc-price-footer').get_text()
    assert 'Age not recorded' in soup.select_one('.bc-price-footer').get_text()
    assert post(client, csrf, 'undo', event_id=response.json['event_id']).status_code == 200
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data,'html.parser')
    assert '€0.00' not in soup.select_one('.bc-price-footer').get_text()
    with admin.database(bw) as db:
        assert tuple(db.execute("SELECT current_value,current_value_currency FROM copies WHERE id='copy'").fetchone()) == old


def test_46s_merged_part_transfers_keep_every_row_and_undo(bw):
    with admin.database(bw) as db, db:
        original = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_type='P' LIMIT 1").fetchone())
        db.execute("DELETE FROM copy_parts WHERE copy_id='copy'")
        db.execute("DELETE FROM copy_minifigs WHERE copy_id='copy'")
        columns = list(original)
        for n in range(4):
            row = dict(original, id=None, parent_minifig_type=None, parent_minifig=None,
                       quantity=1, missing=1, damaged=0, checked=1, spare=0)
            db.execute('INSERT INTO copy_parts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', tuple(row[c] for c in columns))
        db.execute("UPDATE loose_stock SET item_type=?,item_no=?,color_id=?,quantity=4,missing=0,damaged=0 WHERE id='loose-part'", (original['item_type'],original['item_no'],original['color_id']))
        d = collection.detail(db, 'S', 'new-set', copy_id='copy')
        assert len(d['consists']) == 1
        assert d['consists'][0]['can_take'] == 4
        assert len(d['matches']) == 4
        ids = {p['id'] for p in d['consists'][0]['contexts']}
        assert {m['target_id'] for m in d['matches']} == ids
        db.commit()
        events = []
        for match in d['matches']:
            events.append(workbench.transfer(db, match['source_id'], 'copy', match['target'], match['target_id'], 1))
        assert db.execute("SELECT sum(missing) FROM copy_parts WHERE copy_id='copy'").fetchone()[0] == 0
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='loose-part'").fetchone()[0] == 0
        for event in reversed(events):
            assert db.execute('SELECT via FROM events WHERE id=?', (event,)).fetchone()[0] == 'app'
            workbench.undo(db, event)
        assert db.execute("SELECT sum(missing) FROM copy_parts WHERE copy_id='copy'").fetchone()[0] == 4
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='loose-part'").fetchone()[0] == 4



def add_47f_inventory_parts(db):
    """Reported identities added to the migrated inventory for layout checks."""
    db.execute("UPDATE colors SET name='Black',rgb='05131D' WHERE color_id=11")
    db.execute("INSERT OR IGNORE INTO colors(color_id,name,rgb) VALUES(12,'Trans-Clear','FCFCFC')")
    for number, name, colour, quantity in [
        ('7b', 'Tire Smooth Small Dually', 11, 8),
        ('3001old', 'Brick 2 x 4 without Cross Support', 12, 1),
    ]:
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P',?,?)", (number, name))
        db.execute("UPDATE items SET name=? WHERE item_type='P' AND item_no=?", (name, number))
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,checked,spare) VALUES('copy','P',?,?,?,0,0,0,0)", (number, colour, quantity))


def add_49a_long_figure(db):
    """4.9a: a figure with a long name and one missing component, for the Minifigures tab geometry."""
    name = 'Cavalry Soldier with Breastplate and Plumed Helmet'
    db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('M','long-fig',?)", (name,))
    db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('copy','M','long-fig',1,0)")
    template = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_type='P' AND parent_minifig IS NULL AND spare=0 LIMIT 1").fetchone())
    db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P','long-fig-torso','Torso')")
    row = dict(template, id=None, item_no='long-fig-torso', quantity=1, missing=1, damaged=0, checked=0, parent_minifig='long-fig', parent_minifig_type='M')
    db.execute('INSERT INTO copy_parts(' + ','.join(row) + ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values()))


def test_47e_part_facts_matching_and_quantity(app, bw):
    scanner = 'Parts inventory scanner event e5f5a61a-bdc7-41eb-a325-18af6d86de13'
    with admin.database(bw) as db, db:
        db.execute("UPDATE loose_stock SET note=? WHERE item_type='P'", (scanner,))
        db.execute("UPDATE copy_minifigs SET missing=0")
        db.execute("UPDATE copy_parts SET missing=1,damaged=0 WHERE item_type='P' AND item_no='bl-part' AND parent_minifig IS NULL")
        detail = collection.detail(db, 'P', 'bl-part', colour=11)
        assert detail['matches']
    soup = BeautifulSoup(logged_in(app).get('/collection/item/P/bl-part?colour=11').data, 'html.parser')
    assert [n.get_text() for n in soup.select('[data-module=info] dt')][:4] == ['Condition', 'Damaged', 'Quantity', 'Storage']
    assert soup.select_one('.bc-quantity-pill:not(.bc-condition-pill)').get_text() == '×'+str(sum(r['quantity'] for r in detail['instances']))
    matching = soup.select_one('[data-module=matching]')
    assert matching.h3.get_text() == detail['matching_headline']
    assert 'Loose stock against recorded gaps' not in matching.get_text()
    assert scanner not in matching.get_text()
    assert matching.select_one('[data-bc-row][title]')['title'] == scanner
    assert collection.matching_note(scanner+' · Keep in drawer') == 'Keep in drawer'
    assert collection.matching_note(scanner) == ''
    assert collection.matching_note('Parts inventory scanner event e5f5a61abdc741eba32518af6d86de13a1b2 · Note') == 'Note'
    assert collection.matching_note('Parts inventory scanner event e5f5a61abdc741eba32518af6d86de13a1b2.') == ''
    assert collection.matching_note('Keep in drawer') == 'Keep in drawer'


def test_47e_edit_omits_source_and_manual_override_still_saves(app, bw):
    client = logged_in(app)
    csrf = token(client)
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    assert not soup.select_one('#bc-edit [name=completeness_source]')
    assert soup.select_one('#bc-edit [name=completeness]')
    with admin.database(bw) as db:
        before = dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
    response = post(client, csrf, 'save', entity='copy', ids=['copy'], values={'completeness':'C'})
    assert response.status_code == 200
    with admin.database(bw) as db:
        row = db.execute("SELECT completeness,completeness_source FROM copies WHERE id='copy'").fetchone()
        assert tuple(row) == ('C', 'manual')
        assert db.execute('SELECT via FROM events WHERE id=?', (response.json['event_id'],)).fetchone()[0] == 'app'
    assert post(client, csrf, 'undo', event_id=response.json['event_id']).status_code == 200
    with admin.database(bw) as db:
        assert dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone()) == before


def test_ui16_matching_leaves_set_detail_and_edit_panel_holds_instances_and_photos(app,bw):
    client=logged_in(app)
    set_page=BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data,'html.parser')
    assert not set_page.select('[data-module=matching]')
    for url in ('/collection/item/S/new-set?copy=copy','/collection/item/P/bl-part?colour=11','/collection/item/M/bl-figure?stock=loose-figure'):
        soup=BeautifulSoup(client.get(url).data,'html.parser')
        assert bool(soup.select('[data-module=matching]'))==(not url.startswith('/collection/item/S'))
        layout=soup.select_one('.bc-detail-layout')
        assert not layout.select('.bc-own-photos') and not [h for h in layout.select('h2') if h.get_text().startswith('Instances')]
        panel=soup.select_one('dialog#bc-edit')
        headings=[h.get_text() for h in panel.select('.bc-edit-section > h3')]
        assert any(h.startswith('Instances') for h in headings) and 'Own photos' in headings
        assert panel.select_one('form[data-bc-action=save]') and panel.select_one('.bc-own-photos form[data-bc-action=photo]')
        assert panel.select_one('.bc-edit-section[data-bc-list] [data-bc-rows]')
