"""Storage archive and guarded Undo against the real migration fixture."""
from contextlib import closing
import json
import sqlite3

import pytest
from bs4 import BeautifulSoup

from brickwork.core import admin, ledger, orders, part_inventory
from brickwork.core.connect import connect
from tests.test_bw_add import app, bw, legacy, apps, client_token
from tests.test_bw_orders_storage import saved, trace


def test_empty_archive_and_creation_undo(bw):
    with closing(connect(bw)) as db:
        location, created = ledger.storage_save(db, None, 'Empty box')
        archive = ledger.storage_archive(db, location)
        assert location not in {r['id'] for r in ledger.storages(db)}
        with pytest.raises(ValueError, match='unavailable'):
            ledger.storage_detail(db, location)
        ledger.undo(db, archive)
        assert ledger.storage_detail(db, location)['location']['name'] == 'Empty box'
        assert next(r for r in ledger.history(db) if r['id'] == created)['undo_available']
        ledger.undo(db, created)
        ledger.undo(db, created)  # Idempotent.
        assert db.execute('SELECT archived_at FROM storages WHERE id=?', (location,)).fetchone()[0]
        assert db.execute('SELECT count(*) FROM storages WHERE id=?', (location,)).fetchone()[0] == 1


def test_occupied_archive_atomic_receipt_restore_and_lots(bw):
    with closing(connect(bw)) as db:
        with db:
            db.execute("UPDATE loose_stock SET storage_id='store' WHERE id='loose-part'")
            db.execute("INSERT INTO lots(id,name,storage_id) VALUES('lot','Lot','store')")
            db.execute("INSERT INTO copies(id,item_type,set_no,storage_id,archived_at) VALUES('historical-copy','S','new-set','store','old')")
            db.execute("UPDATE loose_stock SET storage_id='store',archived_at='old' WHERE id='instruction'")
        before = ledger.storage_detail(db, 'store')['location']
        assert before['copies'] == 1 and before['entries'] == 1 and before['pieces'] > 0
        snapshots = {t: [dict(r) for r in db.execute('SELECT * FROM '+t)] for t in ('copies','loose_stock','lots','storages')}
        count = db.execute('SELECT count(*) FROM events').fetchone()[0]
        with pytest.raises(ValueError, match='Move the items'):
            ledger.storage_archive(db, 'store')
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == count
        event = ledger.storage_archive(db, 'store', move_to_unstored=True)
        receipt = json.loads(db.execute('SELECT new_value FROM events WHERE id=?',(event,)).fetchone()[0])
        assert {c['table'] for c in receipt['changes']} == set(snapshots)
        for table in ('copies','loose_stock','lots'):
            assert not db.execute('SELECT 1 FROM '+table+" WHERE storage_id='store' AND archived_at IS NULL").fetchone()
        assert all(r[0] == 'app' for r in db.execute('SELECT via FROM events WHERE id>?',(count,)))
        ledger.undo(db, event)
        for table, original in snapshots.items():
            assert [dict(r) for r in db.execute('SELECT * FROM '+table)] == original
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_creation_and_archive_undo_conflicts(bw):
    with closing(connect(bw)) as db:
        location, created = ledger.storage_save(db, None, 'New box')
        moved = ledger.move(db, location, [dict(entity='copy',id='copy')])
        with pytest.raises(ValueError, match='Move the items'):
            ledger.undo(db, created)
        ledger.undo(db, moved)
        ledger.undo(db, created)
        archive = ledger.storage_archive(db, 'store', move_to_unstored=True)
        edit = ledger.move(db, None, [dict(entity='copy',id='copy')])
        with pytest.raises(ValueError, match='changed after saving'):
            ledger.undo(db, archive)
        ledger.undo(db, edit)
        ledger.undo(db, archive)
        # A later archive must not let Undo move a live item into a hidden location.
        moved = ledger.move(db, None, [dict(entity='copy',id='copy')])
        archive = ledger.storage_archive(db, 'store')
        with pytest.raises(ValueError, match='unavailable'):
            ledger.undo(db, moved)
        ledger.undo(db, archive)
        ledger.undo(db, moved)


def test_archive_event_failure_rolls_back_every_move(bw):
    with closing(connect(bw)) as db:
        with db:
            db.execute("UPDATE loose_stock SET storage_id='store' WHERE id='loose-part'")
        db.execute("CREATE TRIGGER reject_archive BEFORE INSERT ON events WHEN NEW.entity='bw_ledger' BEGIN SELECT RAISE(ABORT,'no'); END")
        count = db.execute('SELECT count(*) FROM events').fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            ledger.storage_archive(db, 'store', move_to_unstored=True)
        assert db.execute("SELECT archived_at FROM storages WHERE id='store'").fetchone()[0] is None
        assert db.execute("SELECT storage_id FROM copies WHERE id='copy'").fetchone()[0] == 'store'
        assert db.execute("SELECT storage_id FROM loose_stock WHERE id='loose-part'").fetchone()[0] == 'store'
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == count


def test_routes_archive_counts_and_all_picker_readers(app,bw):
    client, csrf, _ = client_token(app)
    page = client.get('/workbench/storage/store')
    assert page.status_code == 200 and 'data-web-ui="toni"' in page.text
    soup = BeautifulSoup(page.text, 'html.parser')
    form = soup.select_one('form[data-action=archive]')
    assert form and form.select_one('input[name=move_to_unstored]')
    assert '1 copies · 0 loose entries · 0 pieces' in form.parent.get_text()
    blocked = client.post('/workbench/storage/action/archive',json=dict(csrf_token=csrf,id='store'))
    assert blocked.status_code == 400 and 'Move the items' in blocked.json['message']
    archived = client.post('/workbench/storage/action/archive',json=dict(csrf_token=csrf,id='store',move_to_unstored='yes'))
    assert archived.status_code == 200 and archived.json['url'] == '/workbench/storage'
    listing = client.get(archived.json['url'])
    assert 'data-undo-event="'+str(archived.json['event_id'])+'"' in listing.text
    assert 'href="/workbench/storage/store"' not in listing.text
    for url in ['/workbench/storage/unstored','/workbench/part-to-inventory','/manage/add']:
        response = client.get(url)
        assert response.status_code == 200
        assert not BeautifulSoup(response.text,'html.parser').select('option[value=store]')
    with closing(connect(bw)) as db:
        assert 'store' not in {r['id'] for r in part_inventory.options(db)['storages']}
        assert 'store' not in {r['id'] for r in admin.value_rows(db,'storages')}
        with pytest.raises(ValueError): ledger.storage_save(db,'store','Hidden')
        with pytest.raises(ValueError): ledger.move(db,'store',[dict(entity='copy',id='copy')])
        before = db.execute('SELECT count(*) FROM events').fetchone()[0]
        piece = dict(id='forged-photo', chosen=dict(item_type='P',item_no='bl-part',color_id=11),
                     candidates=[dict(item_type='P',item_no='bl-part')])
        with pytest.raises(ValueError, match='unavailable'):
            part_inventory.save(db,[piece],batch='forged',new_lot=dict(name='Hidden lot',storage_id='store'),keep_photos=False)
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == before
        assert not db.execute("SELECT 1 FROM lots WHERE name='Hidden lot'").fetchone()
        oid, _, line = saved(db)
        orders.received(db,oid,{line:3})
        with pytest.raises(ValueError):
            orders.allocate(db,oid,[dict(line_id=line,target_type='stock',quantity=1,storage_id='store')])
    order_page = client.get('/workbench/orders/'+str(oid))
    assert order_page.status_code == 200
    assert not BeautifulSoup(order_page.text,'html.parser').select('option[value=store]')
    undone = client.post('/workbench/storage/action/undo',json=dict(csrf_token=csrf,event_id=archived.json['event_id']))
    assert undone.status_code == 200
    assert 'href="/workbench/storage/store"' in client.get('/workbench/storage').text
    created = client.post('/workbench/storage/action/save',json=dict(csrf_token=csrf,name='Empty route box'))
    assert created.status_code == 200
    identifier = created.json['url'].rsplit('/',1)[1]
    empty_archive = client.post('/workbench/storage/action/archive',json=dict(csrf_token=csrf,id=identifier))
    assert empty_archive.status_code == 200
    assert client.post('/workbench/storage/action/undo',json=dict(csrf_token=csrf,event_id=empty_archive.json['event_id'])).status_code == 200
    assert client.post('/workbench/storage/action/undo',json=dict(csrf_token=csrf,event_id=created.json['event_id'])).status_code == 200
    with closing(connect(bw)) as db:
        assert db.execute('SELECT archived_at FROM storages WHERE id=?',(identifier,)).fetchone()[0]


def test_admin_delete_archives_and_retains_provenance(bw):
    with closing(connect(bw)) as db:
        with pytest.raises(ValueError, match='Move the items'):
            admin.value_write(db,'storages','delete','store',confirmed=True)
        location, _ = ledger.storage_save(db,None,'Admin box')
        event = admin.value_write(db,'storages','delete',location,confirmed=True)
        assert db.execute('SELECT archived_at FROM storages WHERE id=?',(location,)).fetchone()[0]
        ledger.undo(db,event)
        assert ledger.storage_detail(db,location)


def test_storage_list_and_archive_cost_hundreds_of_rows(bw):
    with closing(connect(bw)) as db:
        with db:
            db.executemany('INSERT INTO storages(id,name,archived_at) VALUES(?,?,?)',
                           [(str(i), 'Box '+str(i), 'archived' if i%2 else None) for i in range(300)])
            db.executemany("INSERT INTO copies(id,item_type,set_no,storage_id) VALUES(?,'S','new-set','store')",[(str(i),) for i in range(300)])
        assert trace(db,lambda:ledger.storages(db)) == 1
        assert trace(db,lambda:admin.value_rows(db,'storages')) == 5
        assert len(ledger.storages(db)) == 152  # 150 active boxes, Shelf, Not stored.
        created=[]
        assert trace(db,lambda:created.append(ledger.storage_save(db,None,'Trace box'))) < 15
        location,event = created[0]
        renamed=[]
        assert trace(db,lambda:renamed.append(ledger.storage_save(db,location,'Renamed trace box'))) < 15
        assert trace(db,lambda:ledger.undo(db,renamed[0][1])) < 20
        assert trace(db,lambda:ledger.undo(db,event)) < 20
        events=[]
        assert trace(db,lambda:events.append(ledger.storage_archive(db,'store',move_to_unstored=True))) < 2000
        assert trace(db,lambda:ledger.undo(db,events[0])) < 2000
