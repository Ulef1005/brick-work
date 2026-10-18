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


@pytest.mark.parametrize('path',['/','/collection/sets','/collection/M','/collection/P','/collection/I','/collection/O','/collection/G','/collection/B','/collection/C','/collection/%3F','/collection/wishes'])
def test_lists_in_shell(app,bw,path):
    client=logged_in(app);r=client.get(path)
    assert r.status_code==200,r.get_data(as_text=True)
    assert r.headers['Cache-Control']=='no-store'
    soup=BeautifulSoup(r.data,'html.parser')
    assert soup.select_one('[data-web-ui="toni"]')
    assert soup.select_one('[data-bc-search]') and soup.select_one('[data-bc-sort]')
    assert soup.select_one('a[href="/collection/sets"]')
    assert b'https://example.test/part' not in r.data


def test_purchase_places_in_shell(app,bw):
    r=logged_in(app).get('/collection/purchase-places')
    assert r.status_code==200 and r.headers['Cache-Control']=='no-store'
    soup=BeautifulSoup(r.data,'html.parser')
    assert soup.select_one('[data-web-ui="toni"]') and soup.select_one('a[href="/collection/sets"]')
    assert any(l['href'].split('?')[0].endswith('bw-storage.css') for l in soup.select('link[rel=stylesheet]'))
    assert any(x['src'].split('?')[0].endswith('bw-ledger.js') for x in soup.select('script[src]'))
    assert soup.select_one('[data-search]') and soup.select_one('[data-sort]') and soup.select_one('[data-filters]') and soup.select_one('[data-rows] [data-row]')
    assert b'https://example.test/part' not in r.data


@pytest.mark.parametrize('kind',['S','M','P','G','?','I','O','B','C'])
def test_shared_detail_modules(app,bw,kind):
    with admin.database(bw) as db:
        item=db.execute('SELECT * FROM items WHERE item_type=?',(kind,)).fetchone()
        if not item:
            with db: db.execute('INSERT INTO items(item_type,item_no,name) VALUES(?,?,?)',(kind,'fixture-item','Fixture item'))
            number='fixture-item'
        else: number=item['item_no']
        colour=11 if kind=='P' else None
    r=logged_in(app).get('/collection/item/'+('%3F' if kind=='?' else kind)+'/'+number,query_string={'colour':colour} if colour is not None else {})
    assert r.status_code==200,r.get_data(as_text=True)
    soup=BeautifulSoup(r.data,'html.parser')
    assert [x['data-module'] for x in soup.select('[data-module]')]==(['status','consists','used-in','prices','matching','wanted','info'] if kind in ('M','?') else ['info','prices','matching'] if kind=='P' else ['info','prices','consists'] if kind=='S' else ['info','prices','consists','matching'])
    layout=soup.select_one('.bc-detail-layout')
    assert [child.name for child in layout.find_all(recursive=False)]==(['div','aside'] if kind in ('M','?') else ['aside','div'])
    assert layout.select_one('aside [data-module=info]')
    assert not layout.select('.bc-own-photos,.bc-detail-instances')
    panel=soup.select_one('dialog#bc-edit')
    if panel:
        sections=[h.get_text() for h in panel.select('.bc-edit-section > h3')]
        assert any(x.startswith('Instances') for x in sections) and 'Own photos' in sections
    message=soup.select_one('[data-bc-message]')
    assert message['role']=='status' and not message.has_attr('hidden')
    if kind=='?': assert 'placeholder' in soup.get_text() and 'Unresolved' in soup.get_text()


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


def test_jump_has_only_new_collection_links(app,bw):
    client=logged_in(app)
    r=client.get('/collection/jump?q=new-set')
    assert r.status_code==200,r.json
    copies=r.json['results'][0]['copies']
    assert copies[0]['url'].startswith('/collection/item/S/new-set?copy=')
    assert copies[0]['check_url']=='/workbench/check-parts/copy'
    r=client.get('/collection/jump?q=bl-part')
    assert r.status_code==200,r.json
    assert r.json['results'][0]['url'].startswith('/collection/item/P/bl-part?colour=11')
    assert r.headers['Cache-Control']=='no-store'
    assert b'data-url="/collection/jump"' in client.get('/').data


def test_metadata_priority_prices_ranges_and_consolidation(bw):
    with admin.database(bw) as db,db:
        db.execute("INSERT OR REPLACE INTO item_properties VALUES('P','bl-part','material','bricklink','ABS',NULL,'2026-10-01')")
        db.execute("INSERT OR REPLACE INTO item_properties VALUES('P','bl-part','material','rebrickable','Other',NULL,'2026-10-02')")
        priority=json.loads(db.execute("SELECT value FROM settings WHERE key='source_priority'").fetchone()[0]);priority['metadata']['P']=['bricklink','rebrickable']
        db.execute("UPDATE settings SET value=? WHERE key='source_priority'",(json.dumps(priority),))
        o=db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,sold,min,max,source,observed_at) VALUES('P','bl-part',11,'U','sold','EUR','3',8,'1','5','bricklink','2022-01-01')").lastrowid
        db.execute("UPDATE price_current SET observation_id=? WHERE item_type='P' AND item_no='bl-part'",(o,))
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('second-part','P','bl-part',11,2,NULL)")
        d=collection.detail(db,'P','bl-part',colour=11)
        assert d['properties']['material']['value']=='ABS'
        assert d['properties']['material']['alternatives'][0]['value']=='Other'
        assert d['prices'][0]['range']==50 and d['prices'][0]['stale']
        assert sum(r['quantity'] for r in d['consolidated'])==5
        assert sum(len(r['lines']) for r in d['consolidated'])==2


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


def test_detail_links_are_canonical_and_no_nested_links(app,bw):
    from urllib.parse import quote
    client=logged_in(app)
    with admin.database(bw) as db:
        targets=[(r['item_type'],r['item_no']) for r in db.execute('SELECT * FROM items')]
    for kind,number in targets:
        r=client.get('/collection/item/'+quote(kind,safe='')+'/'+quote(number,safe=''),query_string={'colour':11} if kind=='P' else {})
        if r.status_code==200:
            soup=BeautifulSoup(r.data,'html.parser')
            assert not soup.select('a a'),(kind,number)


def test_parts_listing_matches_gate_baseline_and_query_count(bw):
    from pathlib import Path
    expected = json.loads((Path(__file__).parent / 'fixtures/brickwork/collection-parts.json').read_text())
    with admin.database(bw) as db:
        queries = []
        db.set_trace_callback(queries.append)
        try:
            actual = collection.listing(db, 'P')
        finally:
            db.set_trace_callback(None)
        assert actual == expected
        assert len(queries) == 14  # Includes one bulk market source-priority read.
        # Unrelated catalogue rows must not reach Python or trigger file checks.
        property_reads = [q for q in queries if 'FROM item_properties' in q]
        assert len(property_reads) == 1 and 'item_type=' in property_reads[0]
        image_reads = [q for q in queries if 'FROM item_images' in q]
        assert len(image_reads) == 1 and 'json_each' in image_reads[0]


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


def test_parts_listing_preserves_unfiltered_instance_order(bw, monkeypatch):
    with admin.database(bw) as db, db:
        for number in ['z-part', 'a-part', 'part-10', 'part-2']:
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P',?,?)",(number,number))
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity) VALUES(?,'P',?,11,1)",(number,number))
    with admin.database(bw) as db:
        actual = collection.listing(db,'P')
        original = collection.instances
        with monkeypatch.context() as patch:
            patch.setattr(collection,'instances',lambda db,kind=None:original(db))
            expected = collection.listing(db,'P')
        assert actual == expected
        assert [r['item_no'] for r in actual][:5] == ['bl-part','z-part','a-part','part-10','part-2']


def test_merge_does_not_invent_unrecorded_quantity(bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,condition) VALUES('unknown-quantity','P','bl-part',11,'N')")
    with admin.database(bw) as db:
        before = collection.snapshot(db,'loose_stock',['loose-part','unknown-quantity'])
        with pytest.raises(ValueError, match='quantity is not recorded'):
            collection.save(db,'stock',['loose-part'],{'condition':'N'})
        assert collection.snapshot(db,'loose_stock',['loose-part','unknown-quantity']) == before


def test_collection_response_budget(app, bw):
    """Large migrated fixture, route bytes and SQL cost (also a local benchmark)."""
    import time
    from statistics import median
    with admin.database(bw) as db, db:
        for kind, count in [('P', 7441), ('S', 195), ('M', 600)]:
            db.executemany('INSERT INTO items(item_type,item_no,name) VALUES(?,?,?)',
                [(kind, f'bench-{n}', f'Collection item {n}') for n in range(count)])
            if kind == 'S':
                db.executemany("INSERT INTO copies(id,item_type,set_no,completeness_source) VALUES(?,'S',?,'derived')",
                    [(f'bench-S-{n}',f'bench-{n}') for n in range(count)])
            else:
                db.executemany('INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,?,?,?,1,\'U\')',
                    [(f'bench-{kind}-{n}',kind,f'bench-{n}',11 if kind=='P' else None) for n in range(count)])
    client = logged_in(app)
    for kind in ['P','S','M']:
        times=[]
        for _ in range(5):
            start=time.perf_counter(); response=client.get('/collection/'+kind)
            times.append(time.perf_counter()-start)
        print(f'Collection {kind}: {median(times):.6f}s, {len(response.data)} bytes')
        assert response.status_code == 200
        if kind == 'P':
            part_bytes = len(response.data)
    assert part_bytes < 1_500_000
    with admin.database(bw) as db:
        queries=[];db.set_trace_callback(queries.append)
        collection.listing(db,'P'); collection.options(db)
        db.set_trace_callback(None)
        assert len(queries)==19  # Includes one bulk market source-priority read.


def test_list_records_are_script_safe_and_display_only(app, bw):
    name = '</script><img src=x onerror="alert(1)"> & a name'
    with admin.database(bw) as db, db:
        db.execute("UPDATE items SET name=? WHERE item_type='P' AND item_no='bl-part'", (name,))
    response = logged_in(app).get('/collection/P')
    soup = BeautifulSoup(response.data, 'html.parser')
    data = json.loads(soup.select_one('[data-bc-records]').string)
    assert not soup.select('[data-bc-row]')
    assert not soup.select('img[onerror]')
    decoded = [dict(zip(data['fields'], [r.get(str(i)) for i in range(len(data['fields']))])) for r in data['rows']]
    assert any(r['name'] == name for r in decoded)
    assert 'note' not in data['fields'] and 'instances' not in data['fields']


def test_list_payload_preserves_colour_zero():
    from brickwork.core.list_records import payload
    data=json.loads(str(payload([{'item_type':'P','item_no':'zero','color_id':0}])))
    assert data['rows'][0][str(data['fields'].index('color_id'))] == 0


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


@pytest.mark.parametrize('missing,damaged,label',[(0,0,''),(3,0,'3 missing'),(0,1,'1 damaged'),(3,1,'3 missing · 1 damaged')])
def test_defect_formatter_and_browser_payload(missing,damaged,label):
    from brickwork.core.list_records import payload
    assert collection.defects(missing,damaged) == label
    data=json.loads(payload([dict(item_type='P',item_no='3022',missing=missing,damaged=damaged)]))
    assert data['rows'][0].get(str(data['fields'].index('defects')), '') == label


@pytest.mark.parametrize('name',[None,'Named part'])
def test_identity_macro_and_detail_heading(app,bw,name):
    with admin.database(bw) as db, db:
        db.execute("UPDATE items SET name=?,category=NULL,year=1968 WHERE item_no='bl-part'",(name,))
        db.execute("UPDATE colors SET rgb='FFFFFF' WHERE color_id=11")
    client=logged_in(app)
    soup=BeautifulSoup(client.get('/collection/item/P/bl-part?colour=11').data,'html.parser')
    hero=soup.select_one('.bc-detail-hero')
    assert hero.get_text(' ',strip=True).split().count('bl-part') == 1
    assert hero.h1.get_text() == (name or 'bl-part').replace(' ', '\u00a0')
    assert '· 1968' not in hero.get_text()
    assert 'background:#FFFFFF' in str(hero.select_one('.bc-colour'))
    assert 'color:#1A1816' in str(hero.select_one('.bc-colour'))
    assert not hero.select_one('.bc-colour-tile')
    assert '−0 missing' not in soup.get_text()
    with app.test_request_context():
        macro=app.jinja_env.get_template('web/toni/brickwork/collection_modules.html').module.identity
        row=dict(item_type='S',item_no='312-3',name=name,year=1968,category=None,theme=None)
        identity=BeautifulSoup(str(macro(row)),'html.parser')
        assert identity.get_text(' ',strip=True).split().count('312-3') == 1
        assert identity.select_one('strong') is not None if name else identity.select_one('strong') is None
        assert identity.select_one('.secondary').get_text() == '1968'


def test_missing_static_falls_back(app):
    from brickwork.web.ui import bw_static
    with app.test_request_context():
        assert bw_static('web/toni/missing-45u.css').endswith('/static/web/toni/missing-45u.css')


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


def test_review_collection_controls_and_source_disclosure(app, bw):
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/').data, 'html.parser')
    assert soup.select_one('.bc-status-strip')
    assert [b['data-bc-status'] for b in soup.select('[data-bc-status]')] == ['', 'S', 'C', 'I', 'unknown']
    assert len(soup.select('.bc-toolbar [data-bc-search]')) == 1
    assert soup.select_one('[data-bc-panel] [data-bc-group]')
    assert soup.select_one('[data-bc-sort-panel] [data-bc-direction]')
    assert soup.select_one('[data-bc-view=grid]')['aria-label'] == 'Grid'
    with admin.database(bw) as db, db:
        db.execute("INSERT OR REPLACE INTO item_properties VALUES('S','new-set','source_modified_at','rebrickable','Recorded timestamp',NULL,'2026-10-08')")
        db.execute("INSERT OR REPLACE INTO item_properties VALUES('S','new-set','name','rebrickable','Alternative name',NULL,'2026-10-08')")
        for name in ['Set is checked', 'Box present', 'Instructions present']:
            db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,'status',1)", (name, name))
            db.execute("INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES('copy','copy',?)", (name,))
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    info = soup.select_one('[data-module=info]')
    assert not info.select_one('.bc-source-details')
    disclosure = soup.select_one('#bc-edit .bc-source-details')
    assert disclosure and not disclosure.has_attr('open')
    assert 'Recorded timestamp' in disclosure.get_text()
    assert 'Alternative name' in disclosure.get_text()
    visible = info.find('dl', recursive=False)
    facts = {f.dt.get_text(): f.dd.get_text() for f in visible.select('.bc-fact')}
    assert facts['Parts check'] == 'Checked' and facts['Box'] == facts['Instructions'] == 'Yes'
    assert [b.get_text() for b in soup.select('[data-bc-tab]')][1:] == ['Minifigures', 'Instructions & Box']
    assert soup.select_one('[data-bc-tab=parts] .bc-tab-count')
    assert soup.select_one('[data-module=consists] [aria-label="Copy progress"]')
    soup = BeautifulSoup(client.get('/collection/item/P/bl-part?colour=11').data, 'html.parser')
    assert not soup.select('[data-module=consists]')
    assert soup.select_one('[data-module=prices]').find_next('section')['data-module'] == 'matching'


@pytest.mark.parametrize('viewer', ['read_only', 'anonymous'])
def test_run4_readonly_source_details(app, bw, viewer):
    with admin.database(bw) as db, db:
        db.execute("INSERT OR REPLACE INTO item_properties VALUES('S','new-set','source_modified_at','rebrickable','Recorded timestamp',NULL,'2026-10-08')")
        db.execute("INSERT OR REPLACE INTO item_properties VALUES('S','new-set','name','rebrickable','Alternative name',NULL,'2026-10-08')")
        expected = collection.detail(db, 'S', 'new-set', copy_id='copy')['properties']
    if viewer == 'read_only':
        app.config['BW_READ_ONLY'] = True
        client = logged_in(app)
    else:
        # Collection pages need a session (see test_auth_guard); an anonymous viewer is sent to the login page.
        anonymous = app.test_client().get('/collection/item/S/new-set?copy=copy')
        assert anonymous.status_code == 302 and '/login' in anonymous.location
        return
    response = client.get('/collection/item/S/new-set?copy=copy')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    action = soup.select_one('[data-module=info] [data-bw-open=bc-edit]')
    assert action.get_text(strip=True) == 'Details' and action.select_one('svg')
    dialog = soup.select_one('#bc-edit')
    disclosure = dialog.select_one('.bc-source-details')
    assert not disclosure.has_attr('open')
    assert 'Recorded timestamp' in disclosure.get_text()
    assert 'Alternative name' in disclosure.get_text()
    for prop in expected.values():
        for recorded in [prop, *prop.get('alternatives', [])]:
            assert str(recorded['value']) in disclosure.get_text()
            assert recorded['source'] in disclosure.get_text()
            if recorded['fetched_at']:
                assert recorded['fetched_at'] in disclosure.get_text()
    assert not dialog.select('form, input, select, textarea, [data-bw-open=bc-delete]')
    assert [b.get_text(strip=True) for b in dialog.select('button')] == ['Close']
    assert not soup.select_one('#bc-delete')


def test_collection_money_formatter_is_shared_and_lossless():
    from brickwork.web.ui import bw_age, bw_collection_records, bw_price_order
    from brickwork.web.formatting import money
    assert money('189.0', 'EUR', fixed=True) == '€189.00'
    assert money('12.5144', 'EUR', fixed=True) == '€12.51'
    assert money('0', 'USD', fixed=True) == '$0.00'
    assert bw_age('2026-10-08T23:00:00Z') == '8 Oct'
    assert bw_age(None) == 'Age not recorded'
    row = dict(item_type='S', item_no='312-3', price=dict(currency='EUR', price='12.5144', age='2026-10-08', stale=True))
    data = json.loads(bw_collection_records([row]))
    price = data['rows'][0][str(data['fields'].index('price'))]
    assert price == ['EUR', '12.5144', '2026-10-08', True, '€12.51', '8 Oct']
    assert [p['condition'] for p in bw_price_order([{'condition':None}, {'condition':'N'}, {'condition':'U'}])] == ['U','N',None]


@pytest.mark.parametrize('kind', ['S', 'M', 'P', 'I'])
def test_collection_payload_built_once_per_request(app, bw, monkeypatch, kind):
    from brickwork.web import ui
    from brickwork.core import list_records
    from types import SimpleNamespace
    original = ui.bw_collection_records
    original_dumps = list_records.json.dumps
    serializations = []
    def dumps(*args, **kwargs):
        serializations.append(1)
        return original_dumps(*args, **kwargs)
    monkeypatch.setattr(list_records, 'json', SimpleNamespace(dumps=dumps))
    calls = []
    def counted(rows):
        calls.append(len(rows))
        return original(rows)
    monkeypatch.setattr(ui, 'bw_collection_records', counted)
    response = logged_in(app).get('/collection/' + kind)
    assert response.status_code == 200
    assert len(calls) == 1
    assert len(serializations) == 1
    soup = BeautifulSoup(response.data, 'html.parser')
    assert len(soup.select('[data-bc-records]')) == 1


def test_collection_intrinsic_width_and_detail_flow_css():
    import re
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
    def rule(selector):
        return re.findall(re.escape(selector) + r'\s*\{([^}]+)\}', css)[-1]
    assert 'min-width:0' in rule('#bw-collection')
    assert 'min-width:0' in rule('#bw-collection [data-bc-list]')
    assert 'max-width:100%' in rule('#bw-collection .bc-status-chips')
    assert 'overflow-x:hidden' not in css
    assert 'display:flex;flex-direction:column' in rule('#bw-collection .bc-detail-aside>.bc-module')
    assert 'flex:none' in rule('#bw-collection .bc-detail-aside>.bc-module>*')
    assert 'flex:none' in rule('#bw-collection .bc-price>*')
    assert 'display:block' in rule('#bw-collection .bc-fact small')


def test_set_inventory_panel_contains_controls_and_empty_state(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set').data, 'html.parser')
    section = soup.select_one('[data-module=consists]')
    inventory = section.select_one('[data-bc-tab-inventory]')
    assert inventory.select_one('[data-bc-rows]')
    assert not inventory.select_one('.bc-toolbar')
    assert not inventory.select_one('[data-bc-count]')
    assert not inventory.select_one('[data-bc-tab-extras]')
    assert section.select_one('[data-bc-tab-extras]').has_attr('hidden')


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


def test_collection_chromium_geometry(collection_chromium_geometry):
    assert collection_chromium_geometry['identityMeasurements']


def test_49a_chromium_geometry_measured(collection_chromium_geometry):
    """c1 uncropped set image, c14 one-line 24 px figure pill, c15 identity width, c11/c12 progress captions."""
    measured = collection_chromium_geometry['review49a']
    assert {m['width'] for m in measured} == {360, 390, 768, 1024, 1440}
    for m in measured:
        assert m['hero']['objectFit'] != 'cover' and m['hero']['objectFit'] == 'contain', m
        assert m['pill']['height'] == 24 and m['pill']['lines'] == 1, m
        assert m['figure']['linkWidth'] >= 150 and m['figure']['wordSplit'] is False, m
        assert all(m['missingCard'].values()), m
        assert m['progress']['presentBeforeMissing'] and m['progress']['captionsBelowCoverage'], m


def test_47f_chromium_geometry_identity_minimum(collection_chromium_geometry):
    """Present identities keep 150 px; missing cards keep the kit column budget."""
    measurements = collection_chromium_geometry['identityMeasurements']
    assert [measurement['width'] for measurement in measurements] == [360, 390, 768, 820]
    for measurement in measurements:
        assert measurement['rows']
        assert {row['missing'] for row in measurement['rows']} == {False, True}
        for row in measurement['rows']:
            # Frame 1d: 16 px padding each side, 96 px picture, 16 px gap;
            # allow 1 px for fractional layout rounding.
            minimum = row['cardWidth'] - 2 * 16 - 96 - 16 - 1 if row['missing'] else 150
            assert row['width'] >= minimum, (measurement['width'], row, minimum)


def test_run2_sets_filter_mapping_toolbar_and_subtitle(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO price_observations(item_type,item_no,condition,guide,currency,price,source,observed_at) VALUES('S','new-set','U','sold','EUR','12','bricklink','2026-10-08')")
        oid=db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute("INSERT INTO price_current(item_type,item_no,condition,guide,currency,observation_id) VALUES('S','new-set','U','sold','EUR',?)", (oid,))
    soup=BeautifulSoup(logged_in(app).get('/collection/sets').data, 'html.parser')
    assert soup.select_one('.bc-heading>.button.primary').get_text(strip=True)=='Add'
    assert 'prices are used averages from BrickLink' in soup.select_one('.bc-heading').get_text()
    toolbar=soup.select_one('.bc-toolbar')
    assert toolbar.select_one('[data-bc-search]') and toolbar.select_one('[data-bc-count]') and toolbar.select_one('.bc-view-switch')
    panel=soup.select_one('[data-bc-panel]')
    assert [h.get_text() for h in panel.select('h4')]==['Status','Condition','Copies','Tags','Has','View']
    for key in ['type','condition','status','colour','problem','flags','storage','place','lot','duplicates','stock','category','theme','year']:
        assert panel.select_one('[data-bc-filter='+key+']')
    assert [b['data-value'] for b in panel.select('[data-bc-pick=has]')]==['Box present','Instructions present']
    assert panel.select_one('.bc-other-filters [data-bc-filter=problem]')


def test_run2_prices_freshest_priority_records_and_real_history(app,bw,monkeypatch):
    from datetime import datetime, timezone
    from brickwork.core import collection_prices
    monkeypatch.setattr(collection_prices,'now',lambda:datetime(2026,10,14,tzinfo=timezone.utc))
    with admin.database(bw) as db, db:
        db.execute("DELETE FROM price_current WHERE item_type='S' AND item_no='new-set'")
        db.execute("DELETE FROM price_observations WHERE item_type='S' AND item_no='new-set'")
        def observation(condition,guide,price,date,source='bricklink',currency='EUR',slot=None,error=None):
            db.execute('''INSERT INTO price_observations(item_type,item_no,condition,guide,currency,price,min,max,sold,source,observed_at,slot,error)
                VALUES('S','new-set',?,?,?,?,'1','50',7,?,?,?,?)''',(condition,guide,currency,price,source,date,slot,error))
        # Same series twice, an older record, a newer other source, a valuation,
        # and unlike currencies/slots/invalid dates: none become invented points.
        observation('U','sold','10','2026-05-01')
        observation('U','sold','12','2026-10-08')
        observation('U','sold','99','2025-10-01')
        observation('U','sold','45','2026-10-09','rebrickable')
        observation('N','sold','20','2026-10-08')
        observation('N','valuation','30','2026-10-09','brickset')
        observation('U','sold','13','2026-10-10',currency='USD',error='Unavailable')
        observation('U','sold','14','bad date')
        observation('U','sold','15','2026-09-10',slot='boxed')
        observation('U','stock','18','2026-10-11')
    client=logged_in(app)
    soup=BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data,'html.parser')
    card=soup.select_one('[data-module=prices]')
    rows=card.select('[data-bc-condition-prices] .bc-price')
    assert [r.strong.get_text() for r in rows]==['Used','New']
    assert '12.00' in rows[0].get_text() and '20.00' in rows[1].get_text()
    records=card.select_one('.bc-price-records')
    assert not records.has_attr('open') and len(records.select('.bc-price'))==10
    assert '45.00' in records.get_text() and 'Unavailable' in records.get_text()
    assert 'Set estimate' in card.select_one('.bc-price-footer').get_text()
    assert '19.23' in card.select_one('.bc-price-footer').get_text()  # Migrated copy override wins.
    assert '30.00' in records.get_text()  # Source valuation stays available.
    chart=card.select_one('[data-bc-price-history]')
    assert chart and len(chart.select('circle'))==2
    assert '2026-05-01' in chart.get_text() and '2026-10-08' in chart.get_text()
    assert '2025-10-01' not in chart.get_text() and '45.00' not in chart.get_text()
    assert 'Axis starts at €10.00.' in chart.get_text()
    assert card.select_one('[data-bc-condition-prices]').find_next_sibling()==chart
    # Source setting controls condition selection, not an arbitrary source name.
    with admin.database(bw) as db, db:
        db.execute("INSERT OR REPLACE INTO settings VALUES('source_priority',?)",(json.dumps({'market_price':{'*':['rebrickable','bricklink']}}),))
    soup=BeautifulSoup(client.get('/collection/item/S/new-set').data,'html.parser')
    assert '45.00' in soup.select_one('[data-bc-condition-prices] .bc-price').get_text()
    assert not soup.select_one('[data-bc-price-history]')  # One point in selected series.


@pytest.mark.parametrize('state',['missing','present','unchecked','empty'])
def test_run2_missing_inventory_projection_and_no_invented_progress(app,bw,state):
    with admin.database(bw) as db, db:
        db.execute("UPDATE copy_minifigs SET missing=0 WHERE copy_id='copy'")
        db.execute("UPDATE copy_parts SET missing=0,damaged=0,checked=1 WHERE copy_id='copy'")
        if state=='missing':
            db.execute("UPDATE copy_parts SET missing=1,damaged=1 WHERE id=(SELECT id FROM copy_parts WHERE copy_id='copy' AND parent_minifig IS NULL LIMIT 1)")
        elif state=='unchecked':
            db.execute("UPDATE copy_parts SET missing=NULL,damaged=NULL,checked=0 WHERE copy_id='copy'")
        elif state=='empty':
            db.execute("DELETE FROM copy_parts WHERE copy_id='copy'")
            db.execute("DELETE FROM copy_minifigs WHERE copy_id='copy'")
        detail=collection.detail(db,'S','new-set',copy_id='copy')
        assert detail['progress']['known']==(state not in ('unchecked','empty'))
        if state=='missing':
            assert any(r['deficit']==2 for r in detail['consists'])
            assert detail['progress']['can_take'] <= detail['progress']['missing']
            assert sum(r['can_take'] for r in detail['consists']) <= sum({r['source_id']:r['have'] for r in detail['matches']}.values())
        else:
            assert not any(r['deficit'] for r in detail['consists'])
    soup=BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data,'html.parser')
    progress=soup.select_one('[aria-label="Copy progress"]')
    assert 'primary' in progress.select_one('a.button')['class']
    assert not soup.select_one('[data-module=consists]>.actions a')
    if state in ('unchecked','empty'):
        assert progress.h3.get_text() == 'Parts not checked'
        assert not progress.select_one('.bc-progress-subline')
        assert 'parts present' not in progress.get_text() and 'all 0' not in progress.get_text()
    else:
        p = detail['progress']
        assert progress.select_one('.bc-progress-subline').get_text() == f"{p['different']} different parts · all checked"
    if state=='missing':
        assert 'can be taken' in progress.get_text() and 'to order' in progress.get_text()
        assert soup.select_one('.bc-missing-card') and soup.select_one('[data-bc-present]')
    else:
        assert not soup.select_one('.bc-missing-card')


def test_run2_detail_query_count_is_bounded_with_hundreds_of_lines(bw):
    with admin.database(bw) as db:
        def measured():
            queries=[];db.set_trace_callback(queries.append)
            try: collection.detail(db,'S','new-set',copy_id='copy')
            finally: db.set_trace_callback(None)
            return len(queries)
        before=measured()
        original=dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' LIMIT 1").fetchone())
        columns=list(original)
        with db:
            db.executemany('INSERT INTO copy_parts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',
                [tuple(dict(original,id=None).values()) for i in range(300)])
        assert measured()==before


@pytest.mark.parametrize('dates,condition,currency,expected',[
    ([], 'U','EUR',False),
    (['2026-10-08'], 'U','EUR',False),
    (['2026-10-08','2026-10-08'], 'U','EUR',False),
    (['2026-03-01','2026-10-08'], 'U','EUR',False),
    (['2026-05-01','2026-10-08'], 'N','EUR',False),
    (['2026-05-01','2026-10-08'], 'U','EUR',True),
    (['2026-05-01','2026-10-08'], 'U',None,True),
])
def test_run2_history_eligibility(app,bw,monkeypatch,dates,condition,currency,expected):
    from datetime import datetime, timezone
    from brickwork.core import collection_prices
    monkeypatch.setattr(collection_prices,'now',lambda:datetime(2026,10,14,tzinfo=timezone.utc))
    with admin.database(bw) as db, db:
        db.execute("DELETE FROM price_current WHERE item_type='S' AND item_no='new-set'")
        db.execute("DELETE FROM price_observations WHERE item_type='S' AND item_no='new-set'")
        db.executemany("INSERT INTO price_observations(item_type,item_no,condition,guide,currency,price,source,observed_at) VALUES('S','new-set',?,'sold',?,'10','bricklink',?)",[(condition,currency,date) for date in dates])
    soup=BeautifulSoup(logged_in(app).get('/collection/item/S/new-set').data,'html.parser')
    chart=soup.select_one('[data-bc-price-history]')
    assert bool(chart)==expected
    if expected:
        if currency is None:
            assert 'currency not recorded' in chart.get_text().lower()
        assert len({p['cy'] for p in chart.select('circle')})==1  # Real equal averages form a flat line.
    else:
        # #32: one usable date shows the single-point state as text; nothing usable shows nothing.
        single=soup.select_one('[data-bc-price-single]')
        if single:
            assert condition=='U' and 'Single price point' in single.get_text() and not single.select('svg')  # one date inside six months
        else:
            assert 'Used average over six months' not in soup.get_text()


def test_run2_collection_style_contract():
    """Confirmed visual rules; geometry is re-measured by the UI reviewer."""
    import re
    from pathlib import Path
    css=Path('static/web/toni/bw-collection.css').read_text()
    def rule(selector):
        return re.search(re.escape(selector)+r'\s*\{([^}]+)',css).group(1)
    assert 'display:none' in rule('body:has(#bw-collection[data-bc-collection-list]) .shell-add')
    assert '.bc-heading>.button { display:none' not in css
    assert 'width:89px' in rule('#bw-collection .bc-heading>.button')
    assert 'var(--tw-accent-soft)' in rule('#bw-collection .bc-view-switch button[aria-pressed=true]')
    assert 'border:0' in rule('#bw-collection[data-type=S] .bc-card>.bc-picture')
    assert 'text-decoration:none' in rule('#bw-collection .bc-row a,#bw-collection .bc-card a')
    assert 'outline:2px solid var(--tw-accent)' in rule('#bw-collection .bc-row a:focus-visible,#bw-collection .bc-card a:focus-visible')
    assert 'border-left:.5px solid var(--tw-divider)' in css
    assert not re.search(r'(?:^|[;{])\s*order\s*:',css)
    assert 'display:contents' not in css


@pytest.mark.parametrize('maximum', ['', 'abc'])
def test_superseded_corrupt_price_records_render(app, bw, maximum):
    with admin.database(bw) as db:
        with db:
            for record_maximum, observed in [(maximum, '2020-01-01T00:00:00+00:00'), ('5', 123)]:
                db.execute("""INSERT INTO price_observations(item_type,item_no,condition,guide,source,price,min,max,sold,observed_at)
                    VALUES('S','new-set','U','sold','bricklink','2','1',?,3,?)""", (record_maximum, observed))
        decorated = collection.decorate_prices([dict(condition='U', guide='sold', slot='', item_type='S',
            price='2', min='1', max=maximum, sold=3, observed_at='2020-01-01', max_age_days=1),
            dict(condition='U', guide='sold', slot='', item_type='S', price='2', min='1', max='5',
                 sold=3, observed_at=123, max_age_days=1)])
        assert decorated[0]['stale'] is True and decorated[0]['range'] is None
        assert decorated[1]['stale'] is False and decorated[1]['range'] == 25
    response = logged_in(app).get('/collection/item/S/new-set')
    assert response.status_code == 200
    records = BeautifulSoup(response.data, 'html.parser').select_one('.bc-price-records')
    assert records and len(records.select('.bc-price')) >= 2


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


def test_run4_info_css_contract():
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
    assert '.bc-fact dt { color:var(--tw-text-muted)' in css
    assert '.bc-fact dd { font-size:15px;line-height:20px;font-weight:500' in css
    assert '[data-module=info]>p.secondary { font-size:13px;line-height:18px' in css
    assert 'min-width:81px;min-height:44px' in css
    assert '.bc-source-details summary::before' not in css
    assert '.bc-source-details[open]>summary::before' not in css


@pytest.mark.parametrize('kind,number,query', [('S','new-set','?copy=copy'), ('P','bl-part','?colour=11')])
def test_run4_single_and_multiple_prices(app, bw, kind, number, query):
    with admin.database(bw) as db, db:
        db.execute('DELETE FROM price_current WHERE item_type=? AND item_no=?', (kind,number))
        db.execute('DELETE FROM price_observations WHERE item_type=? AND item_no=?', (kind,number))
        db.executemany('''INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,min,max,sold,source,observed_at)
            VALUES(?,?,?,?,'sold','EUR',?,?,?,?, 'bricklink','2026-10-08')''',
            [(kind,number,11 if kind=='P' else None,'U','10','5','15',3),
             (kind,number,11 if kind=='P' else None,'N','20','20','20',1)])
    soup = BeautifulSoup(logged_in(app).get('/collection/item/'+kind+'/'+number+query).data, 'html.parser')
    prices = soup.select_one('[data-module=prices]')
    assert 'Window not recorded' not in prices.get_text()
    if kind == 'S':
        assert 'With box: not set' in prices.select_one('.bc-price-footer').get_text()
    used,new = prices.select('[data-bc-condition-prices] .bc-price')
    assert 'avg' in used.get_text() and used.select_one('.bc-range')
    assert 'min €5.00' in used.get_text() and 'max €15.00' in used.get_text()
    assert 'avg' not in new.get_text() and not new.select_one('.bc-range')
    assert 'min ' not in new.get_text() and 'max ' not in new.get_text()
    assert '€20.00' in new.get_text()
    for record in prices.select('.bc-price-records .bc-price'):
        if '1 sold' in record.get_text():
            assert 'avg' not in record.get_text() and not record.select_one('.bc-range')


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


def test_run4_price_css_contract():
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
    assert '.bc-price { border-bottom:.5px solid var(--tw-divider)' in css
    assert '.bc-price>.actions>strong { font-size:15px;font-weight:600' in css
    assert '.bc-price-footer { display:flex;justify-content:space-between;align-items:center' in css


@pytest.mark.parametrize('kind,number,query,parent', [('S','new-set','?copy=copy','Sets'), ('P','bl-part','?colour=11','Parts')])
def test_run4_detail_navigation_and_identity(app, bw, kind, number, query, parent):
    with admin.database(bw) as db, db:
        db.execute("UPDATE items SET year=2011,category='City / Police' WHERE item_type=? AND item_no=?", (kind,number))
    soup = BeautifulSoup(logged_in(app).get('/collection/item/'+kind+'/'+number+query).data, 'html.parser')
    back = soup.select_one('.bc-detail-back')
    assert back.span.get_text() == parent
    assert back.select_one('svg path')['d'] == 'M15 6l-6 6 6 6'
    assert back['href'] == '/collection/'+kind
    assert soup.select_one('.header .shell-add .icon')
    hero = soup.select_one('.bc-detail-hero')
    assert not hero.select('[data-bw-open=bc-edit], [data-bw-open=bc-delete]')
    if kind == 'S':
        assert [x.get_text() for x in hero.select('.bc-identity>span')] == ['new-set','2011','City / Police']
        assert hero.select_one('.bc-phone-links').parent.find_next_sibling()['class'] == ['bc-hero-status']
        assert hero.select_one('.bc-hero-status .bc-desktop-links')
        assert 'Source not recorded' not in hero.get_text()


def test_run4_recorded_external_links_and_missing_ambiguous_ids(app, bw):
    client = logged_in(app)
    def links():
        soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
        return {a.get_text(strip=True):a['href'] for a in soup.select('.bc-external-links a')}
    assert links() == {'BrickLink':'https://www.bricklink.com/v2/catalog/catalogitem.page?S=new-set'}
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO item_properties VALUES('S','new-set','setID','brickset','12345',NULL,'2026-10-08')")
    assert 'Brickset' not in links()
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('brickset','set_number','7286-2','S','new-set','matched','{}')")
    assert links()['Brickset'] == 'https://brickset.com/sets/7286-2'
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('brickset','set_number','7286-3','S','new-set','matched','{}')")
    assert 'Brickset' not in links()
    with admin.database(bw) as db:
        assert collection.external_links(db,dict(item_type='?',unresolved=True)) == []
        # Query strings are encoded; even unusual recorded catalogue numbers cannot inject parameters.
        encoded = collection.external_links(db,dict(item_type='S',item_no='a&b=1',properties={}))
        assert encoded == [('BrickLink','https://www.bricklink.com/v2/catalog/catalogitem.page?S=a%26b%3D1')]


def test_run4_instruction_files_are_in_extras(app, bw):
    with admin.database(bw) as db, db:
        identifier = db.execute("INSERT INTO instruction_files(item_type,set_no,path,label) VALUES('S','new-set','local/guide.pdf','Recorded guide')").lastrowid
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data,'html.parser')
    extras = soup.select_one('[data-bc-tab-extras]')
    assert 'Open PDF · Recorded guide' in extras.get_text()
    assert str(identifier) in extras.select_one('a.button')['href']
    assert extras.select_one('a[href="/manage/instructions"]')
    assert not soup.select_one('[data-module=info]').select('a')


def test_run4_navigation_css_contract():
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
    shell = Path('static/web/toni/shell.css').read_text()
    assert '.header .shell-add { width:44px;min-height:44px;background:transparent;border-color:transparent;color:var(--tw-accent-text)' in shell
    assert '.bc-detail-back { display:flex;align-items:center;gap:2px;min-height:44px;text-decoration:none' in css
    assert 'body:has(.bc-detail-hero) .layout>main { padding-top:0' in css
    # Beat the earlier body:has(#bw-collection) selector (one ID), not just source order.
    assert 'body:has(#bw-collection .bc-detail-hero) .layout>main,' in css
    assert '#bw-collection[data-type=M] .bc-detail-hero { margin-top:0' in css
    assert '.bc-hero-picture { width:100%;aspect-ratio:4/3' in css
    assert '.bc-picture img { display:block;width:100%;height:100%;object-fit:contain' in css
    assert '.bc-external-links a { display:inline-flex;align-items:center;gap:4px;min-height:44px' in css
    assert '.bc-identity>span+span::before { content:" · ";white-space:pre;margin:0' in css



def test_run4_set_identity_keeps_to_check(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('brickset','set_number','uncertain','S','new-set','to_check','{}')")
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data,'html.parser')
    hero = soup.select_one('.bc-detail-hero')
    assert 'To check · Unresolved figures' in hero.get_text()
    assert not hero.select_one('.bc-external-links')


@pytest.mark.parametrize('checked', [0, 1])
def test_46o_consists_text_and_reading_order(app, bw, checked):
    with admin.database(bw) as db, db:
        db.execute("UPDATE copy_parts SET missing=1,damaged=1,checked=? WHERE copy_id='copy'", (checked,))
        detail = collection.detail(db, 'S', 'new-set', copy_id='copy')
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    module = soup.select_one('[data-module=consists]')
    progress = module.select_one('[aria-label="Copy progress"]')
    p = detail['progress']
    assert progress.h3.get_text() == f"{p['missing']} parts missing, {p['can_take']} in loose stock"
    assert progress.select_one('.bc-progress-present').get_text() == f"{p['total']-p['missing']} of {p['total']} parts present"
    assert progress.select_one('.bc-progress-subline').get_text() == f"{p['different']} different parts · " + (f"all checked" if checked else f"0 checked")
    assert [n.get_text() for n in progress.select('.bc-progress-stats span')] == [f"{p['missing']} missing", f"{p['can_take']} can be taken", f"{max(p['missing']-p['can_take'],0)} to order"]
    stats = ' '.join(n.get_text() for n in progress.select('.bc-progress-stats span'))
    assert not any(dash in stats for dash in ['-', '−', '–', '—'])
    assert 'checked' not in stats and 'or damaged' not in stats
    assert f"{p['checked']} checked" in module.select_one('.bc-inventory-details').get_text()
    assert not module.select_one('[data-bc-missing] h3')
    assert module.select_one('[data-bc-missing]')['aria-label'] == 'Missing parts'
    cards = module.select('.bc-missing-card')
    gaps = [r for r in detail['consists'] if r['deficit'] and not r.get('minifig_no')]
    assert len(cards) == len(gaps)
    for card, part in zip(cards, gaps):
        identity = card.select_one('.bc-missing-identity')
        children = identity.find_all(recursive=False)
        if identity.strong:
            assert [n.name for n in children][:2] == ['strong', 'span']
        else:
            assert children[0]['class'] == ['bc-missing-meta']
        meta = identity.select_one('.bc-missing-meta')
        if meta.select_one('.bc-colour'):
            assert meta.find_all(recursive=False)[0]['class'] == ['bc-colour']
            if part.get('rgb'):
                assert meta.select_one('.bc-colour')['style'] == f"background:#{part['rgb']};color:{part['ink']}"
        assert meta.find_all(recursive=False)[-1]['class'] == ['mono']
        count = card.select_one('.bc-missing-count')
        assert count.get_text().startswith('needs ')
        assert ' missing' in count.get_text() and '−' not in count.get_text()
        assert 'checked' not in count.get_text()
        loose = card.select_one('.bc-loose-stock')
        assert bool(loose) == bool(part['can_take'])
        if loose:
            assert loose.get_text() == f"{part['can_take']} in loose stock"
    for card, part in zip(cards, gaps):
        state = ('checked' if part['checked'] else 'not checked') if part.get('checked') is not None else 'Check state not recorded'
        assert state in soup.select_one('.bc-inventory-details').get_text()


@pytest.mark.parametrize('selection', ['wish', 'copyless', 'copy', 'unchecked-copy'])
def test_46o_inventory_summary_requires_recorded_copy_checks(app, bw, selection):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,color_id,quantity,source) VALUES('S','new-set','P','bl-part',11,3,'bricklink')")
        path = '/collection/item/S/new-set'
        if selection == 'wish':
            wish = db.execute("SELECT id FROM wishlist WHERE item_type='S' AND item_no='new-set' AND archived_at IS NULL").fetchone()[0]
            path = '/collection/wishes/' + str(wish)
        elif selection == 'copyless':
            db.execute("UPDATE copies SET archived_at='2026-10-14' WHERE set_no='new-set'")
        elif selection == 'copy':
            db.execute("UPDATE copy_parts SET missing=0,damaged=0,checked=1 WHERE copy_id='copy'")
        else:
            db.execute("UPDATE copy_parts SET missing=NULL,damaged=NULL,checked=0 WHERE copy_id='copy'")
            db.execute("UPDATE copy_minifigs SET missing=NULL WHERE copy_id='copy'")
        detail = collection.detail(db, 'S', 'new-set', wish_id=wish if selection=='wish' else None)
    response = logged_in(app).get(path)
    assert response.status_code == 200
    module = BeautifulSoup(response.data, 'html.parser').select_one('[data-module=consists]')
    summary = module.select_one('.bc-inventory-details')
    if selection == 'copy':
        assert summary.summary.get_text() == f"Details · {detail['progress']['checked']} checked"
    else:
        assert summary.summary.get_text() == 'Details · Check state not recorded'
        assert '0 checked' not in summary.get_text()
    assert not summary.select('li, [data-bc-row]')


def test_46o_inventory_merges_lines_and_retains_metadata(app, bw):
    with admin.database(bw) as db, db:
        original = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' LIMIT 1").fetchone())
        db.execute("DELETE FROM copy_parts WHERE copy_id='copy'")
        db.execute("DELETE FROM copy_minifigs WHERE copy_id='copy'")
        columns = list(original)
        rows = [dict(original, id=None, parent_minifig=None, parent_minifig_type=None,
                     missing=1 if i==0 else 0, damaged=1 if i==0 else 0,
                     checked=1, spare=1 if i==0 else 0) for i in range(300)]
        db.executemany('INSERT INTO copy_parts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',
                       [tuple(r[c] for c in columns) for r in rows])
        detail = collection.detail(db, 'S', 'new-set', copy_id='copy')
    response = logged_in(app).get('/collection/item/S/new-set?copy=copy')
    assert response.status_code == 200
    module = BeautifulSoup(response.data, 'html.parser').select_one('[data-module=consists]')
    # 4.8a: the spare line (index 0) is not part of the set list; 299 lines merge.
    assert len(detail['consists']) == 1
    assert [len(p['contexts']) for p in detail['consists']] == [299]
    assert len(module.select('[data-bc-row], li')) == 1
    assert len(module.select('[data-bc-context]')) == 299
    summary = module.select_one('.bc-inventory-details')
    assert '1 spare line · not listed or counted' in summary.get_text()
    assert not summary.select('ul, li')
    assert not module.select_one('.bc-missing-card')
    card = module.select_one('article.bc-row')
    metadata = module.select_one('.bc-inventory-context').get_text()
    assert 'checked' in metadata and 'spare' not in metadata
    part = detail['consists'][0]
    assert not part['spare'] and part['deficit'] == 0
    assert detail['progress']['missing'] == 0
    assert detail['progress']['spare_lines'] == 1
    assert part['item_no'] in metadata
    for field in ('theme', 'category', 'year', 'source', 'fetched_at'):
        if part.get(field) and (field != 'category' or not part.get('theme')):
            assert str(part[field]) in metadata


def test_46o_consists_css_contract():
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
    contracts = {
        '.bc-progress-heading h3': 'font:600 22px/28px var(--tw-font)',
        '.bc-progress-subline': 'font:400 14px/20px var(--tw-font)',
        '.bc-progress-present': 'font:400 12px/16px var(--tw-mono)',
        '.bc-loose-stock': 'font:400 13px var(--tw-mono)',
        '.bc-progress-stats': 'font:400 12px/16px var(--tw-mono)',
        '[data-module=consists] [data-bc-count]': 'font:400 13px/18px var(--tw-font)',
        '.bc-missing-identity strong': 'font:600 15px/20px var(--tw-font)',
        '.bc-missing-meta .bc-colour': 'height:22px',
        '.bc-missing-meta .mono': 'font:400 12px var(--tw-mono)',
        '.bc-missing-count': 'font:500 13px var(--tw-mono)',
        '.bc-missing-card>.bc-picture': 'width:96px;height:96px',
        '[data-bc-present]>summary': 'min-height:56px',
    }
    for selector, declaration in contracts.items():
        rule = css.split('#bw-collection '+selector+' {')[-1].split('}')[0]
        assert declaration in rule, selector
    import re
    assert not re.search(r'(?:[;{]\s*)order\s*:', css.split('/* 4.6o')[1])
    assert 'display:contents' not in css.split('/* 4.6o')[1]


@pytest.mark.parametrize('count', [1, 2, 30])
def test_46s_copy_chips(app, bw, count):
    with admin.database(bw) as db, db:
        original = dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
        columns = list(original)
        for n in range(1, count):
            row = dict(original, id=f'chip-copy-{n}')
            db.execute('INSERT INTO copies('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', tuple(row[c] for c in columns))
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    chips = soup.select('.bc-copy-chip')
    assert len(chips) == (count if count>1 else 0)
    assert 'Choose copy' not in soup.get_text()
    if chips:
        assert len(soup.select('.bc-copy-chip[aria-current=page]')) == 1
        other = next(c for c in chips if not c.has_attr('aria-current'))
        switched = BeautifulSoup(client.get(other['href']).data, 'html.parser')
        assert switched.select_one('.bc-copy-chip[aria-current=page]')['href'] == other['href']
        assert soup.select_one('[data-bw-open=bc-copies]').get_text() == 'Copy details'


@pytest.mark.parametrize('checked', [False, True])
def test_46s_shared_figure_parts(app, bw, checked):
    with admin.database(bw) as db, db:
        original = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_type='P' LIMIT 1").fetchone())
        db.execute("DELETE FROM copy_parts WHERE copy_id='copy'")
        db.execute("DELETE FROM copy_minifigs WHERE copy_id='copy'")
        columns = list(original)
        for n in range(4):
            number = f'figure-{n}'
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('M',?,?)", (number, f'Figure {n}'))
            db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('copy','M',?,1,?)", (number, 0 if checked else None))
            row = dict(original, id=None, parent_minifig_type='M', parent_minifig=number,
                       quantity=1, missing=1 if checked else None, damaged=0 if checked else None,
                       checked=int(checked), spare=0)
            db.execute('INSERT INTO copy_parts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', tuple(row[c] for c in columns))
        # Include a separate direct requirement in the same required projection.
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P','direct-part','Direct part')")
        row = dict(original, item_no='direct-part', id=None, parent_minifig_type=None, parent_minifig=None,
                   quantity=3, missing=2 if checked else None, damaged=0 if checked else None,
                   checked=int(checked), spare=0)
        db.execute('INSERT INTO copy_parts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', tuple(row[c] for c in columns))
        # Same identity in another colour must remain separate.
        row.update(item_no=original['item_no'], color_id=0, quantity=1, missing=1 if checked else None)
        db.execute('INSERT INTO copy_parts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', tuple(row[c] for c in columns))
        d = collection.detail(db, 'S', 'new-set', copy_id='copy')
        # 4.8a (supersedes the 4.6s counting rule): figure component rows are not set
        # parts. Only the two direct lines remain, and each figure line carries its
        # own parts count.
        parts = [p for p in d['consists'] if p['item_type']=='P']
        assert len(parts) == 2
        assert all(not p['contexts'][0].get('parent_minifig') for p in parts)
        assert d['progress']['total'] == 4
        assert d['progress']['missing'] == (3 if checked else 0)
        assert d['progress']['different'] == 2
        assert d['progress']['lines'] == 2
        figures = [p for p in d['consists'] if p['item_type']=='M']
        assert len(figures) == 4
        assert all(f['parts_lines'] == 1 and f['parts_missing'] == (1 if checked else 0) for f in figures)
        # The checker still exposes every original writable set ID, never figure rows.
        checker_ids = {r['id'] for r in checker.rows(db, 'copy', None, images=False, decorate=False) if r['kind']=='part'}
        assert {r['id'] for p in parts for r in p['contexts'] if 'id' in r} == checker_ids
        assert db.execute("SELECT count(*) FROM copy_parts WHERE parent_minifig IS NOT NULL").fetchone()[0] == 4
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    assert len(soup.select('[data-bc-context]')) == 2 + 4
    pills = [a.get_text() for a in soup.select('.bc-figure-status')]
    assert len(pills) == 4
    if checked:
        assert all(t.startswith('1 part missing') for t in pills)
        assert not soup.select('a.bc-figure-status')
        assert all('/figure/M/figure-' in a['href'] for a in soup.select('a.bc-check-figure'))
    else:
        assert all(t.startswith('Present') for t in pills)
        assert soup.select_one('[aria-label="Copy progress"] h3').get_text() == 'Parts not checked'
        assert not soup.select_one('.bc-progress-present')
        assert not soup.select_one('.bc-missing-card')


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



def test_46s_disclosure_marker_has_standalone_shape_and_open_rotation():
    from pathlib import Path
    import re
    import xml.etree.ElementTree as ET
    css = Path('static/web/toni/remaining.css').read_text()
    selector = 'html[data-web-ui="toni"] details.kit-disclosure'
    closed = re.search(re.escape(selector + '>summary::before') + r'\{([^}]+)\}', css)[1]
    opened = re.search(re.escape(selector + '[open]>summary::before') + r'\{([^}]+)\}', css)[1]
    assert 'width:16px;height:16px' in closed
    assert 'background:currentColor' in closed
    assert "mask:url('icons/chevron-right.svg') center/contain no-repeat" in closed
    assert 'transform:rotate(0deg)' in closed and 'transform:rotate(90deg)' in opened
    assert 'gap:var(--tw-s-2)' in css  # 8 px between icon and label
    # An inline SVG fragment without xmlns is not an SVG image when used as a mask.
    root = ET.parse('static/web/toni/icons/chevron-right.svg').getroot()
    assert root.tag == '{http://www.w3.org/2000/svg}svg'
    assert root.attrib['viewBox'] == '0 0 24 24'
    assert root.attrib['stroke-width'] == '1.6'
    assert root.attrib['stroke-linecap'] == root.attrib['stroke-linejoin'] == 'round'
    assert root.find('{http://www.w3.org/2000/svg}path').attrib['d'] == 'M9.5 6l6 6-6 6'
    collection_css = Path('static/web/toni/bw-collection.css').read_text()
    assert 'summary::before' not in collection_css



def test_46s_copy_chip_and_identity_css_values():
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
    assert '.bc-copy-chip { height:36px;min-height:0;padding:0 14px;border-radius:10px;background:var(--tw-surface);color:var(--tw-text-2)' in css
    assert '.bc-copy-chip[aria-current=page] { background:var(--tw-accent-soft);color:var(--tw-accent-text)' in css
    assert '.bc-hero-status { align-items:center;flex-wrap:wrap;gap:8px' in css
    assert '.bc-hero-picture { width:100%;aspect-ratio:4/3' in css
    assert '.bc-detail-hero h1 { font:600 28px/34px var(--tw-font);letter-spacing:-.3px' in css
    assert '.bc-detail-hero { gap:16px;margin:0 0 24px' in css
    assert 'body:has(#bw-collection[data-type=S] .bc-detail-hero) .layout>main { padding-top:16px' in css



def test_46s_partially_checked_merge_retains_recorded_defects():
    rows = [dict(item_type='P',item_no='part',color_id=11,id=n,quantity=1,
                 missing=1 if n==0 else None,damaged=1 if n==0 else None,
                 checked=1 if n==0 else 0,deficit=2 if n==0 else 0,can_take=0)
            for n in range(4)]
    group, = workbench.merged_inventory(rows)
    assert group['quantity'] == 4
    assert group['missing'] == group['damaged'] == 1
    assert group['deficit'] == 2
    assert group['missing_recorded'] is False
    assert group['checked'] == 0
    assert len(group['contexts']) == 4


def test_46s_loose_set_chip(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition) VALUES('loose-set','S','new-set',1,'U')")
    client = logged_in(app)
    for query, selected in [('copy=copy', 'Set 1'), ('stock=loose-set', 'Loose set')]:
        response = client.get('/collection/item/S/new-set?' + query)
        assert response.status_code == 200
        soup = BeautifulSoup(response.data, 'html.parser')
        chips = soup.select('.bc-copy-chip')
        assert [c.get_text() for c in chips] == ['Set 1', 'Loose set']
        assert 'copy=copy' in chips[0]['href']
        assert 'stock=loose-set' in chips[1]['href']
        assert 'copy=' not in chips[1]['href']
        current, = soup.select('.bc-copy-chip[aria-current=page]')
        assert current.get_text() == selected


@pytest.mark.parametrize('context', ['direct', 'figure', 'whole-figure', 'spare'])
def test_46s_required_card_counts_agree(app, bw, context):
    with admin.database(bw) as db, db:
        original = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_type='P' LIMIT 1").fetchone())
        db.execute("DELETE FROM copy_parts WHERE copy_id='copy'")
        db.execute("DELETE FROM copy_minifigs WHERE copy_id='copy'")
        row = dict(original, id=None, parent_minifig=None, parent_minifig_type=None,
                   quantity=2, missing=1, damaged=0, checked=1, spare=0)
        if context in ('figure', 'whole-figure'):
            db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('copy','M','bl-figure',1,?)", (int(context=='whole-figure'),))
            row.update(parent_minifig='bl-figure', parent_minifig_type='M')
        columns = list(row)
        sql = 'INSERT INTO copy_parts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')'
        db.execute(sql, tuple(row[c] for c in columns))
        if context == 'spare':
            row['spare'] = 1
            db.execute(sql, tuple(row[c] for c in columns))
        # Ensure the only required part gap has one available replacement.
        db.execute('UPDATE loose_stock SET quantity=0')
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('count-stock',?,?,?,1,'U')", (row['item_type'], row['item_no'], row['color_id']))
        detail = collection.detail(db, 'S', 'new-set', copy_id='copy')
        p = detail['progress']
        # 4.8a: figure component rows and spares are not set parts.
        expected = int(context in ('direct', 'spare'))
        counted = (2, expected, expected, expected, 1, 1) if expected else (0, 0, 0, 0, 0, 0)
        assert (p['total'], p['missing'], p['can_take'], p['different'], p['lines'], p['checked_lines']) == counted
        required = [r for r in detail['consists'] if r['item_type']=='P' and not r['spare']]
        assert sum(r['deficit'] for r in required) == p['missing']
        assert sum(r['can_take'] for r in required) == p['can_take']
        parts = [r for r in detail['consists'] if r['item_type']=='P']
        assert len(parts) == expected and not any(r['spare'] for r in parts)
        assert p['spare_lines'] == int(context == 'spare')
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    progress = soup.select_one('[aria-label="Copy progress"]')
    if not expected:
        assert progress.h3.get_text() == 'Parts not checked'
        assert soup.select_one('.bc-tab-count, [data-bc-tab=parts] .bc-tab-count').get_text() == '0'
        return
    assert progress.h3.get_text() == f'{expected} parts missing, {expected} in loose stock'
    assert progress.select_one('.bc-progress-subline').get_text() == '1 different parts · all checked'
    assert [s.get_text() for s in progress.select('.bc-progress-stats span')] == [f'{expected} missing', f'{expected} can be taken', '0 to order']
    part_cards = [c for c in soup.select('[data-bc-inventory-rows] > article') if c.select_one('.bc-missing-count') and 'needs 2' in c.get_text()]
    assert sum('bc-missing-card' in c.get('class', []) for c in part_cards) == expected == len(part_cards)


def test_47f_inventory_phone_layout_contract(app, bw):
    """The shared row keeps its identity line and unbroken colour labels."""
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
    fix = css.split('/* 4.7f')[1]
    assert '@media(max-width:1023px)' in fix
    assert '>a:first-of-type { flex:1 0 calc(100% - 68px)' in fix
    assert '.bc-colour { white-space:nowrap;flex-shrink:0' in fix
    assert '.bc-inventory-row-details[open] { flex-basis:100%;min-width:0' in fix
    assert '.bc-missing-card>.bc-inventory-row-details[open] { grid-column:1 / -1' in fix
    with admin.database(bw) as db, db:
        add_47f_inventory_parts(db)
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set').data, 'html.parser')
    rows = soup.select('[data-bc-inventory-rows] article.bc-inventory-row[data-bc-row]')
    assert rows
    for row in rows:
        assert 'bc-inventory-row' in row['class']
        assert row.select_one(':scope > a .bc-identity, :scope > a .bc-missing-identity')
        assert not row.select_one(':scope > .bc-inventory-row-details')
        assert soup.select_one('.bc-inventory-context')


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


def test_47f_phone_identity_width_from_css_and_real_dom(app, bw):
    """CSS/DOM proof: nonshrinking basis reserves a complete phone identity line.

    Chromium additionally measures actual rectangles in the opt-in geometry test.
    Use the narrower 310 px content width (20 px page and module insets each).
    """
    import re
    from pathlib import Path
    with admin.database(bw) as db, db:
        add_47f_inventory_parts(db)
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set').data, 'html.parser')
    css = Path('static/web/toni/bw-collection.css').read_text().split('/* 4.7f')[1]
    phone = css.split('@media(max-width:1023px) {')[1]
    basis = re.search(r'>a:first-of-type \{ flex:1 0 calc\(100% - (\d+)px\)', phone)
    assert basis, 'identity must have a nonshrinking basis within the phone media rule'
    reserved_width = 390 - 2*20 - 2*20 - int(basis[1])
    for name in ['Tire Smooth Small Dually', 'Brick 2 x 4 without Cross Support']:
        identity = next(n for n in soup.select('.bc-inventory-row > a:first-of-type .bc-identity') if name in n.get_text().replace('\xa0', ' '))
        assert reserved_width >= 150, (name, reserved_width)
        chip = identity.select_one('.bc-colour')
        assert chip and chip.get_text(strip=True) in ['Black', 'Trans-Clear']
        assert '.bc-colour { white-space:nowrap;flex-shrink:0;' in phone
@pytest.mark.parametrize('missing,stock', [(0, 0), (2, 0), (2, 1), (2, 20)])
def test_47e_inventory_counts_and_coverage(app, bw, missing, stock):
    with admin.database(bw) as db, db:
        db.execute("UPDATE copy_parts SET missing=?,damaged=0,checked=1 WHERE copy_id='copy'", (missing,))
        db.execute("UPDATE loose_stock SET quantity=? WHERE item_type='P'", (stock,))
        detail = collection.detail(db, 'S', 'new-set', copy_id='copy')
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    p = detail['progress']
    assert soup.select_one('[data-bc-tab=parts] .bc-tab-count').get_text() == str(p['total'])
    assert not soup.select_one('[data-bc-tab=figures] .bc-tab-count')
    coverage = soup.select_one('.bc-coverage')
    to_order = max(p['missing']-p['can_take'], 0)
    assert bool(coverage) == bool(p['can_take'] or to_order)
    if coverage:
        assert coverage['aria-label'] == f"{p['can_take']} in loose stock, {to_order} to order"
        assert bool(coverage.select_one('i')) == bool(p['can_take'])
        assert bool(coverage.select_one('.bc-progress-outline')) == bool(to_order)
    if p['missing']:
        assert soup.select_one('.bc-progress:not(.bc-coverage) .bc-progress-outline')


def test_47e_price_metadata_keeps_provenance_in_title(app, bw):
    with admin.database(bw) as db, db:
        db.execute("UPDATE price_observations SET source='bricklink',region='eu',sold=7 WHERE item_type='S' AND item_no='new-set'")
        db.execute("INSERT INTO price_observations(item_type,item_no,condition,guide,currency,price,sold,min,max,source,region,observed_at) VALUES('S','new-set','U','sold','EUR','12',7,'10','14','bricklink','eu','2026-10-08')")
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    captions = soup.select('.bc-price>.secondary')
    assert captions
    for caption in captions:
        assert caption['title'] == 'bricklink · eu'
        assert 'bricklink' not in caption.get_text() and 'eu' not in caption.get_text()
    assert soup.select_one('[data-bc-condition-prices] .bc-price>.secondary').get_text().startswith('7 sold · ')


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


@pytest.mark.parametrize('rows,expected', [
    ([], 'Nothing to complete'),
    ([(1,False),(1,False)], 'Fits 1 set, completes none'),
    ([(1,True),(1,True)], 'Completes 1 set'),
    ([(1,True),(2,False)], 'Completes 1 set, fits 1 more'),
    ([(1,True),(2,True),(3,False)], 'Completes 2 sets, fits 1 more'),
    ([(1,False),(2,False)], 'Fits 2 sets, completes none'),
])
def test_47e_matching_headline_counts_copies_once(rows, expected):
    matches = [dict(copy_id=copy, completes=complete, target='part') for copy,complete in rows]
    matches.append(dict(copy_id='loose-figure', completes=False, target='stock-part'))
    assert collection.matching_headline(matches) == expected


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


def test_47e_part_names_display_only_on_detail_and_cards(app, bw):
    from brickwork.web.formatting import part_name, nowrap_tail
    name = 'Bracket 1 x 2 - 1 x 2 Inverted'
    expected = 'Bracket 1 x 2 · 1 x 2\u00a0Inverted'
    assert nowrap_tail(part_name(name)) == expected
    assert part_name('600-2') == '600-2'
    assert part_name('Plate - Modified') == 'Plate - Modified'
    with admin.database(bw) as db, db:
        db.execute("UPDATE items SET name=? WHERE item_type='P' AND item_no='bl-part'", (name,))
        db.execute("UPDATE copy_minifigs SET missing=0")
        db.execute("UPDATE copy_parts SET missing=1,damaged=0 WHERE item_type='P' AND item_no='bl-part' AND parent_minifig IS NULL")
        event_count = db.execute('SELECT count(*) FROM events').fetchone()[0]
    client = logged_in(app)
    part = BeautifulSoup(client.get('/collection/item/P/bl-part?colour=11').data, 'html.parser')
    assert part.h1.get_text() == expected
    sets = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser')
    assert expected in [n.get_text() for n in sets.select('.bc-missing-identity strong')]
    # Lists keep the original raw record for search and editing; JS formats its label.
    listing = client.get('/collection/P').get_data(as_text=True)
    assert name in listing
    with admin.database(bw) as db:
        assert db.execute("SELECT name FROM items WHERE item_type='P' AND item_no='bl-part'").fetchone()[0] == name
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == event_count


def test_47e_fix1_copy_chip_resets_toni_link_min_height():
    css = Path('static/web/toni/bw-collection.css').read_text()
    rule = re.search(r'#bw-collection \.bc-copy-chip \{([^}]*)\}', css).group(1)
    assert 'height:36px' in rule and 'min-height:0' in rule  # beats toni.css main a min-height
    assert re.search(r'@media\(max-width:767px\) \{ #bw-collection \.bc-copy-chip \{ min-height:44px; \} \}', css)


def test_47e_fix1_part_name_digits_are_ascii_in_python_and_js():
    from brickwork.web import formatting
    arabic = '\u0661'  # ARABIC-INDIC DIGIT ONE
    name = f'Brick - {arabic} x 2'
    assert formatting.part_name(name) == name
    assert formatting.part_name('Brick - 1 x 2') == 'Brick · 1 x 2'
    js = Path('static/web/toni/formatting.js').read_text()
    assert '\\d' not in js.split('const nowrapTail')[0] and '(?=[0-9])' in js


def test_47e_fix1_picture_caption_and_alt_use_display_part_name(app):
    template = "{% from 'web/toni/brickwork/collection_modules.html' import picture %}{{ picture(row) }}"
    with app.test_request_context('/'):
        part = BeautifulSoup(app.jinja_env.from_string(template).render(row={'item_type': 'P', 'item_no': 'p', 'name': 'Brick 1 x 2 - 1 x 2', 'image': 1, 'color_name': 'Red'}), 'html.parser')
        button = part.select_one('button')
        assert button['data-caption'] == 'Brick 1 x 2 \u00b7 1 x 2 \u00b7 Red' and button.img['alt'] == button['data-caption']
        moc = BeautifulSoup(app.jinja_env.from_string(template).render(row={'item_type': 'S', 'item_no': 's', 'name': 'Set - 1 x 2', 'image': 1}), 'html.parser')
        assert moc.select_one('button')['data-caption'] == 'Set - 1 x 2'


@pytest.mark.parametrize('kind,number,query', [('S','new-set','?copy=copy'), ('M','price-figure',''), ('P','bl-part','?colour=11')])
@pytest.mark.parametrize('sold', [None, 0, 1, 8])
def test_r2_price_sale_count_wording(app, bw, kind, number, query, sold):
    with admin.database(bw) as db, db:
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES(?,?,?)", (kind,number,'Price fixture'))
        db.execute('DELETE FROM price_current WHERE item_type=? AND item_no=?', (kind,number))
        db.execute('DELETE FROM price_observations WHERE item_type=? AND item_no=?', (kind,number))
        db.execute("""INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,min,max,sold,source,observed_at)
            VALUES(?,?,?,'U','sold','EUR','10','5','15',?,'bricklink','2026-10-08')""", (kind,number,11 if kind=='P' else None,sold))
    soup = BeautifulSoup(logged_in(app).get('/collection/item/'+kind+'/'+number+query).data, 'html.parser')
    captions = soup.select('[data-module=prices] .bc-price>.secondary')
    assert captions
    for caption in captions:
        assert caption.get_text().startswith('Sold count not recorded · ' if sold is None else f'{sold} sold · ')
        assert 'Count not recorded sold' not in caption.get_text()


def test_r2_colour_chooser_uses_readable_shared_chip(app, bw):
    with admin.database(bw) as db, db:
        db.execute("UPDATE colors SET name='Black',rgb='05131D' WHERE color_id=11")
        db.execute("INSERT OR IGNORE INTO colors(color_id,name,rgb) VALUES(12,'White','FFFFFF')")
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity) VALUES('P','bl-part',12,1)")
    soup = BeautifulSoup(logged_in(app).get('/collection/item/P/bl-part').data, 'html.parser')
    chips = {n.text: n['style'] for n in soup.select('.bc-colour-chooser .bc-colour')}
    assert chips['Black'] == 'background:#05131D;color:#FAFAF8'
    assert chips['White'] == 'background:#FFFFFF;color:#1A1816'


def test_r2_component_identity_and_placeholder_tile(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('M','r2-figure','Figure'),('P','r2-vest','Minifigure Vest'),('?','fig-004441:3',NULL)")
        db.execute("INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,color_id,quantity,source) VALUES('M','r2-figure','P','r2-vest',11,1,'bricklink'),('M','r2-figure','?','fig-004441:3',NULL,1,'bricklink')")
    soup = BeautifulSoup(logged_in(app).get('/collection/item/M/r2-figure').data, 'html.parser')
    rows = soup.select('.bc-figure-components .bc-row')
    assert len(rows) == 2
    for row in rows:
        identity = row.select_one('.bc-component-name .bc-missing-identity')
        assert identity.strong and identity.select_one('.bc-missing-meta .mono')
    placeholder = next(row for row in rows if row.select_one('[data-item-no="fig-004441:3"]'))
    assert placeholder.select_one('.bc-picture').get_text(strip=True) == 'No image'
    assert 'Placeholder' in placeholder.select_one('.bc-component-name').get_text()
    assert 'fig-004441:3' in placeholder.select_one('.bc-missing-meta').get_text()


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
