"""#46 (Ulf: A) on the 4.0 store (M.8e, issue #110): storage type, parent and note; purchase location kind; derived Orders and Last used.

Gone with 3.3: `test_upgrade_adds_columns_once` (the columns are in the 4.0 schema, no upgrade exists) and `test_api_create_with_fields`
(API v1 answers 410 until M.11, which carries the storage endpoints).
"""
from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection, ledger
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def test_nesting_cycle_guard_archive_and_undo(coll):
    db = coll.db
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


def test_place_kind_and_derived_columns(world, coll):
    db = coll.db
    corner = coll.place('Brick Corner')
    coll.sql("INSERT INTO purchase_order(id,store,date_ordered,created_at,updated_at) VALUES(91,'brick corner','2026-09-21T10:00:00','2026-09-21','2026-09-21')")
    coll.sql("UPDATE copy SET place_id=?, purchase_date='2026-09-28' WHERE id=?", (corner, world.copy_b))
    event = ledger.place_kind(db, corner, 'Shop')
    place = next(r for r in collection.purchase_places(db) if r['id'] == corner)
    assert (place['kind'], place['orders'], place['last_used']) == ('Shop', 1, '2026-09-28')
    with pytest.raises(ValueError, match='Choose a kind'):
        ledger.place_kind(db, corner, 'Garage')
    with pytest.raises(ValueError, match='unavailable'):
        ledger.place_kind(db, 'nowhere', 'Shop')
    ledger.undo(db, event)
    assert next(r for r in collection.purchase_places(db) if r['id'] == corner)['kind'] is None


def test_pages_show_type_parent_and_kind(coll, client):
    db = coll.db
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
