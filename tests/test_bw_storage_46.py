"""#46 (Ulf: A): storage type, parent and note; purchase location kind; derived Orders and Last used."""
from contextlib import closing
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import ledger, upgrade
from brickwork.core.connect import connect
from tests.test_bw_add import app, bw, legacy, apps, client_token  # noqa: F401


def test_upgrade_adds_columns_once(tmp_path):
    path = tmp_path / 'old.db'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE storages(id TEXT PRIMARY KEY NOT NULL, name TEXT, archived_at TEXT)')
        db.execute('CREATE TABLE purchase_locations(id TEXT PRIMARY KEY NOT NULL, name TEXT, archived_at TEXT)')
        db.execute("INSERT INTO storages VALUES('s','Shelf',NULL)")
        db.commit()
        assert upgrade.storage_fields_pending(db)
        assert upgrade.upgrade_storage_fields(db) is True
        assert not upgrade.storage_fields_pending(db) and upgrade.upgrade_storage_fields(db) is False
        assert {r[1] for r in db.execute('PRAGMA table_info(storages)')} >= {'type', 'parent_id', 'note'}
        assert db.execute('SELECT name,type FROM storages').fetchone() == ('Shelf', None)


def test_nesting_cycle_guard_archive_and_undo(bw):
    with closing(connect(bw)) as db:
        shelf, _ = ledger.storage_save(db, None, 'Shelf B', type='Shelf')
        box, event = ledger.storage_save(db, None, 'Box 3', type='Box', parent_id=shelf, note='Top row')
        row = next(r for r in ledger.storages(db) if r['id'] == box)
        assert (row['type'], row['parent_name'], row['note']) == ('Box', 'Shelf B', 'Top row')
        with pytest.raises(ValueError, match='inside itself'):
            ledger.storage_save(db, shelf, 'Shelf B', parent_id=box)
        with pytest.raises(ValueError, match='storage type'):
            ledger.storage_save(db, box, 'Box 3', type='Crate')
        with pytest.raises(ValueError, match='inside this one'):
            ledger.storage_archive(db, shelf)
        _, edit = ledger.storage_save(db, box, 'Box 3', type='Drawer')  # parent and note kept
        row = next(r for r in ledger.storages(db) if r['id'] == box)
        assert (row['type'], row['parent_id'], row['note']) == ('Drawer', shelf, 'Top row')
        ledger.undo(db, edit)
        assert next(r for r in ledger.storages(db) if r['id'] == box)['type'] == 'Box'


def test_place_kind_and_derived_columns(bw):
    from brickwork.core import collection
    with closing(connect(bw)) as db:
        with db:
            db.execute("INSERT INTO purchase_locations(id,name) VALUES('corner','Brick Corner')")
            db.execute("INSERT INTO orders(id,store,date_ordered) VALUES(91,'brick corner','2026-09-21T10:00:00')")
            db.execute("UPDATE copies SET purchase_location_id='corner',purchase_date='2026-09-28' WHERE id='copy'")
        event = ledger.place_kind(db, 'corner', 'Shop')
        place = next(r for r in collection.purchase_places(db) if r['id'] == 'corner')
        assert (place['kind'], place['orders'], place['last_used']) == ('Shop', 1, '2026-09-28')
        with pytest.raises(ValueError, match='Choose a kind'):
            ledger.place_kind(db, 'corner', 'Garage')
        ledger.undo(db, event)
        assert next(r for r in collection.purchase_places(db) if r['id'] == 'corner')['kind'] is None


def test_pages_show_type_parent_and_kind(app, bw):
    client, _, _ = client_token(app)
    with closing(connect(bw)) as db:
        shelf, _ = ledger.storage_save(db, None, 'Shelf B', type='Shelf')
        box, _ = ledger.storage_save(db, None, 'Box 3', type='Box', parent_id=shelf, note='Top row')
    soup = BeautifulSoup(client.get('/workbench/storage/' + box).text, 'html.parser')
    row = next(r for r in soup.select('.st-row') if 'Box 3' in r.get_text())
    assert row.select_one('.st-name .mono-soft').get_text() == 'Box · Shelf B'
    assert soup.select_one('.st-detail-head .mono-soft').get_text() == 'Box · in Shelf B'
    assert soup.select_one('.st-note-text').get_text() == 'Top row'
    edit = soup.select_one('#st-edit-form')
    assert edit.select_one('select[name=type] option[selected]').get_text() == 'Box'
    assert edit.select_one('select[name=parent_id] option[selected]')['value'] == shelf
    assert box not in [o['value'] for o in edit.select('select[name=parent_id] option')]
    add = soup.select_one('#st-add-form')
    assert add.select_one('select[name=parent_id] option').get_text() == 'Nothing, top level'
    assert 'Storages can sit inside each other.' in add.get_text()


def test_api_create_with_fields(app, bw, monkeypatch):
    from flask import Flask
    from brickwork.api import register
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    monkeypatch.setenv('BW_DB_PATH', str(bw))
    monkeypatch.delenv('BW_READ_ONLY', raising=False)
    api = Flask(__name__)
    api.config.update(TESTING=True)
    register(api)
    c = api.test_client()
    h = {'Authorization': 'Bearer synthetic-bootstrap'}
    shelf = c.post('/api/v1/storages', json={'name': 'Shelf B', 'type': 'Shelf'}, headers=dict(h, **{'Idempotency-Key': 'st-1'}))
    assert shelf.status_code == 201, shelf.json
    shelf_id = shelf.json['data']['id']
    box = c.post('/api/v1/storages', json={'name': 'Box 3', 'type': 'Box', 'parent_id': shelf_id}, headers=dict(h, **{'Idempotency-Key': 'st-2'}))
    assert box.status_code == 201, box.json
    listed = {r['name']: r for r in c.get('/api/v1/storages', headers=h).json['data']}
    assert listed['Box 3']['parent_name'] == 'Shelf B' and listed['Box 3']['type'] == 'Box'
    bad = c.post('/api/v1/storages', json={'name': 'X', 'type': 'Crate'}, headers=dict(h, **{'Idempotency-Key': 'st-3'}))
    assert bad.status_code == 422
