"""Storage archive and guarded Undo on the 4.0 store (M.8e, issue #110).

Moved to later pieces (their premise is theirs): the `admin.value_write` part of the 3.3 route test (M.8i). Its order-allocation part is
`test_allocated_stock_follows_a_storage_archive` in `tests/test_bw_orders_storage.py` (M.8h).
"""
import json
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import errors, ledger, part_inventory
from tests.app4 import STAMP, app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)


def tables(db):
    return {t: [dict(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY id')] for t in ('copy', 'stock', 'lot', 'storage')}


def test_empty_archive_and_creation_undo(coll):
    db = coll.db
    location, created = ledger.storage_save(db, None, 'Empty box')
    archive = ledger.storage_archive(db, location)
    assert location not in {r['id'] for r in ledger.storages(db)}
    with pytest.raises(ValueError, match='unavailable'):
        ledger.storage_detail(db, location)
    ledger.undo(db, archive)
    assert ledger.storage_detail(db, location)['location']['name'] == 'Empty box'
    assert next(r for r in ledger.history(db) if r['id'] == created)['undo_available']
    ledger.undo(db, created)
    assert ledger.undo(db, created)['already_undone']                    # idempotent
    assert db.execute('SELECT archived_at FROM storage WHERE id=?', (location,)).fetchone()[0]
    assert db.execute('SELECT count(*) FROM storage WHERE id=?', (location,)).fetchone()[0] == 1, 'archived, never deleted'


def test_occupied_archive_atomic_receipt_restore_and_lots(world, coll):
    db = coll.db
    coll.sql('UPDATE copy SET archived_at=?, storage_id=? WHERE id=?', ('old', world.shelf, world.copy_c))          # an archived copy is not "in" the storage
    before = ledger.storage_detail(db, world.shelf)['location']
    assert before['copies'] == 1 and before['entries'] == 1 and before['pieces'] == 3 and before['lots'] == 1
    snapshots = tables(db)
    events = db.execute('SELECT count(*) FROM event').fetchone()[0]
    with pytest.raises(ValueError, match='Move the items'):
        ledger.storage_archive(db, world.shelf)
    assert db.execute('SELECT count(*) FROM event').fetchone()[0] == events
    event = ledger.storage_archive(db, world.shelf, move_to_unstored=True)
    receipt = json.loads(db.execute('SELECT new_value FROM event WHERE id=?', (event,)).fetchone()[0])
    assert {t['table'] for t in receipt} == {'copy', 'stock', 'lot', 'storage'}
    for table in ('copy', 'stock', 'lot'):
        assert not db.execute(f"SELECT 1 FROM {table} WHERE storage_id=? AND archived_at IS NULL", (world.shelf,)).fetchone()
    assert all(r[0] == 'app' for r in db.execute('SELECT via FROM event WHERE id>?', (events,)))
    ledger.undo(db, event)
    assert tables(db) == snapshots
    assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_creation_and_archive_undo_conflicts(world, coll):
    db = coll.db
    location, created = ledger.storage_save(db, None, 'New box')
    moved = ledger.move(db, location, [dict(entity='copy', id=world.copy_b)])
    with pytest.raises(errors.UndoBlocked, match='Move the items'):
        ledger.undo(db, created)
    ledger.undo(db, moved)
    ledger.undo(db, created)
    archive = ledger.storage_archive(db, world.shelf, move_to_unstored=True)
    elsewhere, _ = ledger.storage_save(db, None, 'Elsewhere')
    edit = ledger.move(db, elsewhere, [dict(entity='copy', id=world.copy_a)])
    with pytest.raises(errors.UndoBlocked, match='changed'):
        ledger.undo(db, archive)
    ledger.undo(db, edit)
    ledger.undo(db, archive)
    # A later archive must not let Undo move a live item into a hidden location.
    coll.sql('UPDATE stock SET storage_id=NULL')
    coll.sql('UPDATE lot SET storage_id=NULL')
    moved = ledger.move(db, None, [dict(entity='copy', id=world.copy_a)])
    archive = ledger.storage_archive(db, world.shelf)
    with pytest.raises(errors.UndoBlocked, match='unavailable'):
        ledger.undo(db, moved)
    ledger.undo(db, archive)
    ledger.undo(db, moved)


def test_archive_event_failure_rolls_back_every_move(world, coll):
    db = coll.db
    db.execute("CREATE TRIGGER reject_archive BEFORE INSERT ON event WHEN NEW.entity_kind='ledger' BEGIN SELECT RAISE(ABORT,'no'); END")
    db.commit()
    events = db.execute('SELECT count(*) FROM event').fetchone()[0]
    with pytest.raises(sqlite3.DatabaseError):
        ledger.storage_archive(db, world.shelf, move_to_unstored=True)
    assert db.execute('SELECT archived_at FROM storage WHERE id=?', (world.shelf,)).fetchone()[0] is None
    assert db.execute('SELECT storage_id FROM copy WHERE id=?', (world.copy_a,)).fetchone()[0] == world.shelf
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[0] == world.shelf
    assert db.execute('SELECT count(*) FROM event').fetchone()[0] == events


def test_routes_archive_counts_and_every_reader_of_storages(world, coll, client):
    token = csrf(client)
    page = client.get(f'/workbench/storage/{world.shelf}')
    assert page.status_code == 200 and 'data-web-ui="toni"' in page.text
    form = BeautifulSoup(page.text, 'html.parser').select_one('form[data-action=archive]')
    assert form and form.select_one('input[name=move_to_unstored]')
    assert '1 copies · 1 loose entries · 3 pieces · 1 lots' in form.parent.get_text()
    blocked = client.post('/workbench/storage/action/archive', json=dict(csrf_token=token, id=world.shelf))
    assert blocked.status_code == 400 and 'Move the items' in blocked.json['message']
    archived = client.post('/workbench/storage/action/archive', json=dict(csrf_token=token, id=world.shelf, move_to_unstored='yes'))
    assert archived.status_code == 200 and archived.json['url'] == '/workbench/storage'
    listing = client.get(archived.json['url'])
    assert f'data-undo-event="{archived.json["event_id"]}"' in listing.text
    assert f'href="/workbench/storage/{world.shelf}"' not in listing.text
    for url in ['/workbench/storage/unstored', '/workbench/part-to-inventory', '/manage/add']:
        response = client.get(url)
        assert response.status_code == 200
        assert not BeautifulSoup(response.text, 'html.parser').select(f'option[value="{world.shelf}"]')
    db = coll.db
    assert world.shelf not in {r['id'] for r in part_inventory.options(db)['storages']}
    with pytest.raises(ValueError):
        ledger.storage_save(db, world.shelf, 'Hidden')
    with pytest.raises(ValueError):
        ledger.move(db, world.shelf, [dict(entity='copy', id=world.copy_a)])
    events = db.execute('SELECT count(*) FROM event').fetchone()[0]
    piece = dict(id='forged-photo', chosen=dict(item_id=world.brick, color_id=world.red), candidates=[dict(item_id=world.brick)])
    with pytest.raises(ValueError, match='unavailable'):
        part_inventory.save(db, [piece], batch='forged', new_lot=dict(name='Hidden lot', storage_id=world.shelf), keep_photos=False)
    assert db.execute('SELECT count(*) FROM event').fetchone()[0] == events and not db.execute("SELECT 1 FROM lot WHERE name='Hidden lot'").fetchone()
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=archived.json['event_id'])).status_code == 200
    assert f'href="/workbench/storage/{world.shelf}"' in client.get('/workbench/storage').text
    created = client.post('/workbench/storage/action/save', json=dict(csrf_token=token, name='Empty route box'))
    assert created.status_code == 200
    identifier = created.json['url'].rsplit('/', 1)[1]
    empty_archive = client.post('/workbench/storage/action/archive', json=dict(csrf_token=token, id=identifier))
    assert empty_archive.status_code == 200
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=empty_archive.json['event_id'])).status_code == 200
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=token, event_id=created.json['event_id'])).status_code == 200
    assert db.execute('SELECT archived_at FROM storage WHERE id=?', (identifier,)).fetchone()[0]


def test_storage_list_and_archive_cost_hundreds_of_rows(world, coll):
    db = coll.db

    def trace(call):
        seen = []
        db.set_trace_callback(seen.append)
        call()
        db.set_trace_callback(None)
        return len(seen)
    db.executemany('INSERT INTO storage(id,name,created_at,archived_at) VALUES(?,?,?,?)', [(f's{i}', f'Box {i}', STAMP, 'archived' if i % 2 else None) for i in range(300)])
    db.commit()
    assert trace(lambda: ledger.storages(db)) == 1
    assert len(ledger.storages(db)) == 150 + 1 + 1, '150 active boxes, Shelf A and Not stored'
    created = []
    assert trace(lambda: created.append(ledger.storage_save(db, None, 'Trace box'))) < 25
    location, event = created[0]
    renamed = []
    assert trace(lambda: renamed.append(ledger.storage_save(db, location, 'Renamed trace box'))) < 25
    assert trace(lambda: ledger.undo(db, renamed[0][1])) < 30
    assert trace(lambda: ledger.undo(db, event)) < 30
    for i in range(300):
        coll.add_copy('2070-1', storage=world.shelf)
    events = []
    assert trace(lambda: events.append(ledger.storage_archive(db, world.shelf, move_to_unstored=True))) < 100, 'a bulk update, not a statement per row'
    assert trace(lambda: ledger.undo(db, events[0])) < 3 * 300 + 50, 'Undo puts each row back with its own statement: linear in the rows'


def snap(db, table, ids):
    return [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE id IN (SELECT value FROM json_each(?)) ORDER BY id', (json.dumps(ids),))]


def test_moving_stock_onto_the_same_key_merges_and_one_undo_restores_both(world, coll):
    db = coll.db
    away = coll.storage('Away')
    mine = coll.add_stock('part', world.brick, colour=world.red, quantity=4, condition='used', storage=world.shelf, missing=1, checked=1)
    there = coll.add_stock('part', world.brick, colour=world.red, quantity=2, condition='used', storage=away, missing=2, checked=1)
    before = snap(db, 'stock', [mine, there])
    event = ledger.move(db, away, [dict(entity='stock', id=mine)])
    merged = db.execute('SELECT quantity,missing,checked FROM stock WHERE id=?', (there,)).fetchone()
    assert tuple(merged) == (6, 3, 1) and db.execute('SELECT archived_at IS NOT NULL FROM stock WHERE id=?', (mine,)).fetchone()[0]
    assert db.execute("SELECT count(*) FROM stock WHERE item_id=? AND color_id=? AND condition='used' AND storage_id=? AND archived_at IS NULL", (world.brick, world.red, away)).fetchone()[0] == 1
    ledger.undo(db, event)
    assert snap(db, 'stock', [mine, there]) == before
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_a_lot_move_merges_its_carried_parts_too(world, coll):
    db = coll.db
    away = coll.storage('Away')
    twin = coll.add_stock('part', world.brick, colour=world.red, quantity=1, condition='used', lot=world.bag, storage=away)
    before = snap(db, 'stock', [world.stock_brick, twin])
    event = ledger.move(db, away, [dict(entity='lot', id=world.bag)])
    assert db.execute('SELECT quantity FROM stock WHERE id=?', (twin,)).fetchone()[0] == 4
    ledger.undo(db, event)
    assert snap(db, 'stock', [world.stock_brick, twin]) == before


def test_archive_to_not_stored_merges_into_unstored_stock_and_undo_restores_both(world, coll):
    db = coll.db
    plain = world.stock_brick_new                                                   # new red 3001, 2, not stored
    coll.sql('UPDATE stock SET missing=1 WHERE id=?', (plain,))
    inside = coll.add_stock('part', world.brick, colour=world.red, quantity=3, condition='new', storage=world.shelf, damaged=1)
    before = snap(db, 'stock', [plain, inside])
    event = ledger.storage_archive(db, world.shelf, move_to_unstored=True)
    assert tuple(db.execute('SELECT quantity,missing,damaged FROM stock WHERE id=?', (plain,)).fetchone()) == (5, 1, 1)
    assert db.execute('SELECT archived_at IS NOT NULL FROM stock WHERE id=?', (inside,)).fetchone()[0]
    assert db.execute('SELECT archived_at IS NOT NULL FROM storage WHERE id=?', (world.shelf,)).fetchone()[0]
    ledger.undo(db, event)
    assert snap(db, 'stock', [plain, inside]) == before
    assert db.execute('SELECT archived_at FROM storage WHERE id=?', (world.shelf,)).fetchone()[0] is None


def test_a_loose_figure_is_not_in_the_merge_key_and_never_merges(world, coll):
    db = coll.db
    away = coll.storage('Away')
    figure = coll.item('minifigs', 'fig-000004')
    there = coll.add_stock('minifigure', figure, quantity=1, condition='used', storage=away)
    here = coll.add_stock('minifigure', figure, quantity=1, condition='used', storage=world.shelf)
    event = ledger.move(db, away, [dict(entity='stock', id=here)])
    assert [r[0] for r in db.execute('SELECT quantity FROM stock WHERE id IN (?,?) AND archived_at IS NULL ORDER BY id', (there, here))] == [1, 1]
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (here,)).fetchone()[0] == away
    ledger.undo(db, event)
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (here,)).fetchone()[0] == world.shelf
