"""Named wishlist invariants, portable formats and transport receipts."""
from contextlib import closing
import csv
import io
import json
import sqlite3
from xml.etree import ElementTree as ET

import pytest
from bs4 import BeautifulSoup

from brickwork.core import add, collection, errors, upgrade, wishlists
from brickwork.core.connect import connect
from tests.test_bw_add import bw, app, legacy, client_token, post_confirm
from tests.web_fixtures import logged_in, apps


@pytest.fixture
def store(tmp_path):
    with closing(connect(tmp_path/'lists.db')) as db:
        with db:
            db.execute("INSERT INTO colors(color_id,name) VALUES(4,'Red')")
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P','bl-part','Part'),('S','bl-set','Set'),('S','unknown','Unmapped')")
            db.execute("INSERT INTO wishlist(item_type,item_no,color_id,quantity,condition,note,max_price,max_price_currency) VALUES('P','bl-part',4,3,'any','A & B < C','1.25','EUR')")
            db.execute("INSERT INTO wishlist(item_type,item_no,quantity,condition) VALUES('S','bl-set',2,'new')")
        yield db


def test_upgrade_default_idempotent_and_readonly(tmp_path):
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE wishlist(id INTEGER PRIMARY KEY,item_type TEXT,item_no TEXT,color_id INTEGER,archived_at TEXT); CREATE UNIQUE INDEX wishlist_live_key ON wishlist(item_type,item_no,color_id IS NULL,coalesce(color_id,0)) WHERE archived_at IS NULL; INSERT INTO wishlist VALUES(1,'S','1',NULL,NULL);")
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    assert upgrade.wishlists_pending(db)
    with pytest.raises(sqlite3.OperationalError): upgrade.upgrade_wishlists(db)
    db.close()
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        assert upgrade.upgrade_wishlists(db)
        assert db.execute('SELECT list_id FROM wishlist').fetchone()[0]=='default'
        assert db.execute('SELECT name FROM wishlists').fetchone()[0]=='Wishlist'
        assert not upgrade.upgrade_wishlists(db)
    with closing(connect(tmp_path/'fresh.db')) as db:
        assert not upgrade.wishlists_pending(db)


def test_per_list_key_create_rename_archive_restore_and_undo(store):
    db=store
    target,event=wishlists.save(db,data={'name':'Holiday','note':'Gift'})
    assert wishlists.require(db,target)['name']=='Holiday'
    _,rename=wishlists.save(db,target,{'name':'Winter'})
    collection.undo(db,rename)
    assert wishlists.require(db,target)['name']=='Holiday'
    copy_event=wishlists.transfer(db,[1,2],target,copy=True)
    copied=collection.snapshot(db,'wishlist',[3,4])
    assert len(copied)==2 and all(r['list_id']==target for r in copied)
    with pytest.raises(sqlite3.IntegrityError), db:
        db.execute("INSERT INTO wishlist(item_type,item_no,color_id,list_id) VALUES('P','bl-part',4,?)",(target,))
    _,arch=wishlists.save(db,target,action='archive')
    assert not db.execute('SELECT 1 FROM wishlist WHERE list_id=? AND archived_at IS NULL',(target,)).fetchone()
    _,restore=wishlists.save(db,target,action='restore')
    assert db.execute('SELECT count(*) FROM wishlist WHERE list_id=? AND archived_at IS NULL',(target,)).fetchone()[0]==2
    collection.undo(db,restore)
    collection.undo(db,arch)
    assert collection.snapshot(db,'wishlist',[3,4])==copied
    collection.undo(db,copy_event)
    assert all(r['archived_at'] for r in collection.snapshot(db,'wishlist',[3,4]))
    collection.undo(db,event)
    assert db.execute('SELECT archived_at FROM wishlists WHERE id=?',(target,)).fetchone()[0]


def test_archive_preserves_previously_archived_wishes(store):
    target,_=wishlists.save(store,data={'name':'Other'})
    wishlists.transfer(store,[1,2],target)
    collection.save(store,'wish',[1],{},archive=True)
    stamp=store.execute('SELECT archived_at FROM wishlist WHERE id=1').fetchone()[0]
    wishlists.save(store,target,action='archive')
    wishlists.save(store,target,action='restore')
    assert store.execute('SELECT archived_at FROM wishlist WHERE id=1').fetchone()[0]==stamp
    assert store.execute('SELECT archived_at FROM wishlist WHERE id=2').fetchone()[0] is None


def test_transfer_conflict_atomic_and_guarded_undo(store):
    target,_=wishlists.save(store,data={'name':'Target'})
    event=wishlists.transfer(store,[1,2],target)
    assert store.execute('SELECT count(*) FROM wishlist WHERE list_id=?',(target,)).fetchone()[0]==2
    collection.undo(store,event)
    assert all(r['list_id']=='default' for r in collection.snapshot(store,'wishlist',[1,2]))
    wishlists.transfer(store,[1],target,copy=True)
    before=collection.snapshot(store,'wishlist',[1,2])
    with pytest.raises(errors.Conflict): wishlists.transfer(store,[1,2],target)
    assert collection.snapshot(store,'wishlist',[1,2])==before
    event=wishlists.transfer(store,[2],target)
    collection.save(store,'wish',[2],{'note':'Later'})
    with pytest.raises(ValueError,match='later'): collection.undo(store,event)
    with pytest.raises(ValueError): wishlists.transfer(store,[2,2],target)


def test_creation_undo_refuses_later_wishes(store):
    target,event=wishlists.save(store,data={'name':'Target'})
    wishlists.transfer(store,[1],target)
    with pytest.raises(ValueError,match='wishes first'): collection.undo(store,event)
    assert wishlists.require(store,target)


def test_export_bricklink_structure_currency_and_entities(store):
    wishlists.save(store,'default',{'bricklink_id':'123'})
    result=wishlists.export(store,'default')
    assert not result['content'].startswith('<?xml')
    root=ET.fromstring(result['content']); assert root.tag=='INVENTORY'
    part=root.find('ITEM'); assert part.findtext('ITEMID')=='bl-part'
    assert part.findtext('COLOR')=='4' and part.findtext('MINQTY')=='3'
    assert part.findtext('REMARKS')=='A & B < C'
    assert part.findtext('MAXPRICE')=='1.25' and part.find('CONDITION') is None
    assert part.findtext('NOTIFY')=='N' and part.findtext('WANTEDLISTID')=='123'
    collection.save(store,'wish',[1],{'max_price_currency':'USD'})
    result=wishlists.export(store,'all')
    assert ET.fromstring(result['content']).find('ITEM/MAXPRICE') is None
    assert result['summary']['notes'][0]['id']==1


def mapping(db,kind,source_id,item_type=None,item_no=None,color=None):
    db.execute("INSERT OR REPLACE INTO id_match(source,kind,source_id,item_type,item_no,color_id,status,evidence_json) VALUES('rebrickable',?,?,?,?,?,'matched','{}')",(kind,source_id,item_type,item_no,color))


def test_rebrickable_translation_and_unmapped_summary(store):
    with store:
        mapping(store,'set','rb-set-1','S','bl-set')
        mapping(store,'part','rb-part','P','bl-part')
        mapping(store,'color','99',color=4)
        store.execute("INSERT INTO wishlist(item_type,item_no,quantity) VALUES('S','unknown',5)")
    sets=wishlists.export(store,'all',format='rebrickable',kind='sets')
    assert list(csv.reader(io.StringIO(sets['content'])))==[['Set Number','Quantity'],['rb-set-1','2']]
    assert any(r['item_no']=='unknown' and 'mapping' in r['reason'] for r in sets['summary']['omitted'])
    parts=wishlists.export(store,'all',format='rebrickable',kind='parts')
    assert list(csv.reader(io.StringIO(parts['content'])))==[['Part','Color','Quantity'],['rb-part','99','3']]
    with store: mapping(store,'part','ambiguous','P','bl-part')
    assert wishlists.export(store,format='rebrickable')['summary']['exported']==0


def test_query_counts_flat(store):
    def count():
        statements=[];store.set_trace_callback(statements.append)
        wishlists.listing(store);wishlists.export(store);wishlists.export(store,format='rebrickable')
        store.set_trace_callback(None)
        return len(statements)
    baseline=count()
    for i in range(20):
        target,_=wishlists.save(store,data={'name':str(i)})
        wishlists.transfer(store,[1,2],target,copy=True)
    assert count()==baseline


def test_xml_import_preview_target_metadata_confirm_undo(app,bw):
    client,csrf,_=client_token(app)
    xml=b'<WANTEDLIST><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>bl-part</ITEMID><COLOR>11</COLOR><MINQTY>7</MINQTY><QTYFILLED>2</QTYFILLED><MAXPRICE>1.40</MAXPRICE><CONDITION>X</CONDITION><REMARKS>A &amp; B</REMARKS><WANTEDLISTID>1234</WANTEDLISTID></ITEM></WANTEDLIST>'
    response=client.post('/manage/add/review',data={'csrf_token':csrf,'where':'wishlist','type':'P','mode':'file','file':(io.BytesIO(xml),'list.xml')})
    assert response.status_code==200,response.text
    preview=response.json; row=preview['items'][0]
    assert row['list_id']=='new-bl:1234' and row['note']=='A & B' and row['quantity']==7
    assert row['max_price']=='1.40' and 'QTYFILLED' in ' '.join(row['import_notes'])
    with closing(connect(bw)) as db: assert len(wishlists.listing(db))==1
    row['decision']='another'
    response=post_confirm(client,csrf,preview)
    assert response.status_code==200,response.text
    batch=response.json['batch']
    with closing(connect(bw)) as db:
        target=next(l for l in wishlists.listing(db) if l['bricklink_id']=='1234')
        wish=dict(db.execute('SELECT * FROM wishlist WHERE list_id=?',(target['id'],)).fetchone())
        assert (wish['condition'],wish['quantity'],wish['note'],wish['max_price'])==('any',7,'A & B','1.40')
        assert wish['qty_filled_manual']==2  # #35: QTYFILLED kept as the line's filled quantity
        add.undo(db,batch)
        assert not db.execute('SELECT 1 FROM wishlists WHERE id=? AND archived_at IS NULL',(target['id'],)).fetchone()


@pytest.mark.parametrize('header,row,kind',[('set_num,quantity','new-set,2','S'),('part_num,color_id,quantity','rb-part,99,2','P'),('Part,Color,Quantity','rb-part,99,2','P')])
def test_csv_import_chosen_list(app,bw,header,row,kind):
    with closing(connect(bw)) as db:
        target,_=wishlists.save(db,data={'name':'CSV'})
        with db:
            mapping(db,'set','new-set','S','new-set')
            mapping(db,'part','rb-part','P','bl-part')
            mapping(db,'color','99',color=11)
        proposal=add.resolve(db,add.file_rows((header+'\n'+row+'\n').encode(),'list.csv',kind),'wishlist',list_id=target)
        assert not proposal['unresolved'] and proposal['items'][0]['list_id']==target
        proposal['items'][0]['decision']='another'
        validated=add.validate_edits(db,proposal['items'],proposal['items'])
        add.confirm(db,validated,batch='csv',guard=False)
        assert db.execute('SELECT quantity FROM wishlist WHERE list_id=?',(target,)).fetchone()[0]==2


@pytest.mark.parametrize('empty',[False,True])
def test_render_list_switcher_manage_detail_export_and_readonly(app,bw,empty):
    with closing(connect(bw)) as db:
        target,_=wishlists.save(db,data={'name':'Holiday'})
        if empty: db.execute('UPDATE wishlist SET archived_at=\'old\'');db.commit()
    client=logged_in(app)
    response=client.get('/planning/wishlist');soup=BeautifulSoup(response.data,'html.parser')
    assert not soup.select_one('[role=alert]'),response.text
    assert soup.select_one('nav[aria-label=Wishlists]') and 'Holiday' in soup.text
    assert soup.select_one('#bw-manage-wishlists') and soup.select_one('[data-wl-export]')
    selected=client.get('/planning/wishlist?list='+target)
    assert not BeautifulSoup(selected.data,'html.parser').select('[data-bp-row]')
    download=client.get('/planning/wishlists/all/export.xml?summary=true')
    assert download.status_code==200 and 'summary' in download.json
    if not empty:
        with closing(connect(bw)) as db: identifier=db.execute('SELECT id FROM wishlist WHERE archived_at IS NULL LIMIT 1').fetchone()[0]
        detail=client.get('/collection/wishes/'+str(identifier))
        assert 'Move wish' in detail.text and 'Copy wish' in detail.text
    app.config['BW_READ_ONLY']=True
    readonly=client.get('/planning/wishlist')
    assert 'Manage lists' not in readonly.text and 'data-wl-export ' in readonly.text
    app.config.pop('BW_READ_ONLY',None)


def test_upgrade_with_enforced_foreign_keys_and_flag_guards(bw):
    with closing(connect(bw)) as db:
        with db:
            before=[dict(r) for r in db.execute('SELECT * FROM wishlist ORDER BY id')]
            db.execute('DROP INDEX wishlist_live_key')
            db.execute('ALTER TABLE wishlist DROP COLUMN list_id')
            db.execute('DROP TABLE wishlists')
        assert upgrade.upgrade_wishlists(db)
        assert [dict(r) for r in db.execute('SELECT * FROM wishlist ORDER BY id')]==before
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='item_flags_wishlist_insert'").fetchone()
        with pytest.raises(sqlite3.IntegrityError), db:
            db.execute("INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES('wishlist','nonexistent','bad')")


def test_list_filtered_rows_keep_prices_counts_and_labels(app,bw):
    with closing(connect(bw)) as db:
        target,_=wishlists.save(db,data={'name':'Price watch'})
        source=db.execute('SELECT id FROM wishlist WHERE archived_at IS NULL ORDER BY id LIMIT 1').fetchone()[0]
        wishlists.transfer(db,[source],target,copy=True)
        chosen=db.execute('SELECT id FROM wishlist WHERE list_id=? AND archived_at IS NULL',(target,)).fetchone()[0]
        collection.save(db,'wish',[chosen],{'max_price':'12.00','max_price_currency':'EUR'})
    client=logged_in(app)
    soup=BeautifulSoup(client.get('/planning/wishlist?list='+target).data,'html.parser')
    rows=soup.select('[data-bp-row]')
    assert len(rows)==1 and json.loads(rows[0]['data-record'])['id']==chosen
    assert soup.select_one('a[aria-current=page][href$="'+target+'"]')
    assert '€12.00' in rows[0].text and soup.select_one('[data-bp-pick=under]')
    assert any('Price watch' in r.text for r in BeautifulSoup(client.get('/planning/wishlist').data,'html.parser').select('[data-bp-row]'))


def test_old_collection_receipt_still_undoes_in_default_list(store):
    before=collection.snapshot(store,'wishlist',[1])
    event=collection.save(store,'wish',[1],{'quantity':9})
    saved=dict(store.execute('SELECT * FROM events WHERE id=?',(event,)).fetchone())
    for key in ('old_value','new_value'):
        changes=json.loads(saved[key])
        for change in changes:
            for row in change['rows']: row.pop('list_id',None)
        saved[key]=json.dumps(changes)
    collection.undo(store,event,receipt=saved)
    assert collection.snapshot(store,'wishlist',[1])==before


def test_list_archive_receipt_failure_rolls_back_wishes(store):
    before=collection.snapshot(store,'wishlist',[1,2])
    store.execute("CREATE TRIGGER refuse_list_receipt BEFORE INSERT ON events WHEN new.entity='bw_collection' BEGIN SELECT RAISE(ABORT,'receipt refused'); END")
    with pytest.raises(sqlite3.IntegrityError): wishlists.save(store,'default',action='archive')
    assert collection.snapshot(store,'wishlist',[1,2])==before
    assert wishlists.require(store)['archived_at'] is None


def test_undo_move_requires_live_source_list(store):
    target,_=wishlists.save(store,data={'name':'Other'})
    event=wishlists.transfer(store,[1],target)
    wishlists.save(store,'default',action='archive')
    with pytest.raises(ValueError,match='destination wishlist'): collection.undo(store,event)
    assert store.execute('SELECT list_id FROM wishlist WHERE id=1').fetchone()[0]==target


def test_copy_retains_flags_and_undo_detaches_only_copied_flags(store):
    target,_=wishlists.save(store,data={'name':'Copy'})
    with store:
        store.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('gift','Gift','tag',1)")
        store.execute("INSERT INTO item_flags VALUES('wishlist','1','gift')")
    event=wishlists.transfer(store,[1,2],target,copy=True)
    assert [r[0] for r in store.execute("SELECT entity_id FROM item_flags WHERE flag_id='gift' ORDER BY entity_id")]==['1','3']
    collection.undo(store,event)
    assert [r[0] for r in store.execute("SELECT entity_id FROM item_flags WHERE flag_id='gift'")]==['1']


def test_archiving_selected_list_keeps_manage_and_undo_reachable(app,bw):
    client,csrf,_=client_token(app)
    with closing(connect(bw)) as db: target,_=wishlists.save(db,data={'name':'Temporary'})
    archived=client.post('/planning/wishlists/archive',json={'csrf_token':csrf,'id':target})
    assert archived.status_code==200
    soup=BeautifulSoup(client.get('/planning/wishlist?list='+target).data,'html.parser')
    assert not soup.select_one('[role=alert]')
    assert soup.select_one('[data-wl-undo]') and soup.select_one('[data-wl-action=restore]')
    assert client.post('/planning/wishlists/undo',json={'csrf_token':csrf,'event_id':archived.json['event_id']}).status_code==200
