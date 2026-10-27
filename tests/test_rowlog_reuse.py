"""A freed rowid taken by a later insert must not make a merge, an unmerge or a kind move's Undo refuse (issue #124).

`RowLog` used to find a row by its rowid. SQLite hands the highest freed rowid of a table without AUTOINCREMENT to the next insert, so
a row inserted after a merge could take the rowid of a row the merge had deleted, and `verify` saw "a row there". Now a table with a
declared key is located by that key, and the integer keys that are rowids (`item_link.id`, `picture.id`) are AUTOINCREMENT, so a freed id
is never handed out again. Invented data only, no network."""
import json

import pytest

from brickwork.store4 import merge as moves
from tests.app4 import STAMP, app4, client, coll, pair, table_digest, world  # noqa: F401  (the fixtures)


def local_with_link(coll, name, link_key):
    """An unidentified local part (a merge adds no link for its number) whose `to_check` link is the newest row of `item_link`, so a
    merge of it frees the highest rowid."""
    item = coll.local('part', name)
    coll.link(item, link_key, kind='parts', provider='rebrickable', status='to_check')
    return item


def newest_link_id(db):
    return db.execute('SELECT max(id) FROM main.item_link').fetchone()[0]


def add_status(coll, item, to):
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','kind_differs',?,?)",
             (item, json.dumps({'from': 'gear', 'to': to}), STAMP))


def test_a_link_inserted_between_a_merge_and_its_unmerge_does_not_block(coll, world):
    db = coll.db
    a = local_with_link(coll, 'Local A', 'ra')
    freed = newest_link_id(db)
    result = moves.merge(db, a, world.brick, via='cli')
    assert db.execute('SELECT count(*) FROM main.item_link WHERE id=?', (freed,)).fetchone()[0] == 0
    coll.link(world.plate, 'new-link', kind='P')                           # an unrelated link, anywhere
    moves.unmerge(db, result['merge_id'], via='cli')
    assert db.execute('SELECT item_id FROM main.item_link WHERE id=?', (freed,)).fetchone()[0] == a
    assert db.execute("SELECT id FROM main.item_link WHERE provider_key='new-link'").fetchone()[0] != freed          # the freed id was not handed out again


def test_merge_a_then_merge_b_then_unmerge_a_succeeds(coll, world):
    db = coll.db
    a = local_with_link(coll, 'Local A', 'ra')
    b = coll.local('part', 'Local B', born_key='b1')                       # its merge adds a link for its number: the next insert
    first = moves.merge(db, a, world.brick, via='cli')
    moves.merge(db, b, world.brick, via='cli')
    moves.unmerge(db, first['merge_id'], via='cli')                       # B's merge touched other rows: A's receipt still holds
    assert db.execute('SELECT merged_into FROM main.item WHERE id=?', (a,)).fetchone()[0] is None
    assert db.execute('SELECT merged_into FROM main.item WHERE id=?', (b,)).fetchone()[0] == world.brick


def test_a_kind_move_with_a_status_row_undoes_after_an_insert_into_the_same_table(coll, world):
    db = coll.db
    add_status(coll, world.mystery, 'book')                              # keyed (item_id, provider, reason), rowid hidden
    link_item = coll.local('part', 'Local C', born_key='c1')
    before = table_digest(db)
    result = moves.move_kind(db, world.mystery, 'book', via='app')
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','unmatched','no_match',NULL,?)",
             (link_item, STAMP))                                         # takes the freed hidden rowid
    db.execute('BEGIN IMMEDIATE')
    moves.undo_kind_move_in(db, result['event_id'], via='app')
    db.commit()
    assert db.execute("SELECT count(*) FROM main.item_provider_status WHERE item_id=? AND reason='kind_differs'", (world.mystery,)).fetchone()[0] == 1
    assert db.execute('SELECT kind FROM main.item WHERE id=?', (world.mystery,)).fetchone()[0] == 'gear'
    assert before['stock'] == table_digest(db)['stock']


def test_a_kind_move_undoes_after_a_new_stock_row_took_the_freed_rowid(coll, world):
    db = coll.db
    # gear -> set deletes the item's stock rows (uuid keys; the newest stock row has the highest hidden rowid)
    item = world.mystery
    before = table_digest(db)
    result = moves.move_kind(db, item, 'set', via='app')
    assert db.execute('SELECT count(*) FROM main.stock WHERE item_id=?', (item,)).fetchone()[0] == 0
    coll.add_stock('part', world.plate, colour=world.white, quantity=1, condition='used')   # takes the freed hidden rowid
    db.execute('BEGIN IMMEDIATE')
    moves.undo_kind_move_in(db, result['event_id'], via='app')
    db.commit()
    assert db.execute('SELECT count(*) FROM main.stock WHERE item_id=?', (item,)).fetchone()[0] == 1
    assert before['wish'] == table_digest(db)['wish']


def test_a_kind_move_with_copies_undoes_after_a_new_copy_took_the_freed_rowid(coll, world):
    db = coll.db
    item = coll.local('set', 'A promo item', born_key='promo-1')
    coll.sql("INSERT INTO copy(id,item_id,inventory_source,condition,pinned,created_at,updated_at) VALUES('promo-copy',?,'none','used',0,?,?)", (item, STAMP, STAMP))
    before = table_digest(db)
    result = moves.move_kind(db, item, 'gear', via='app')
    coll.sql("INSERT INTO copy(id,item_id,inventory_source,condition,pinned,created_at,updated_at) VALUES('later-copy',?,'none','used',0,?,?)", (world.keep, STAMP, STAMP))
    db.execute('BEGIN IMMEDIATE')
    moves.undo_kind_move_in(db, result['event_id'], via='app')
    db.commit()
    assert db.execute("SELECT count(*) FROM main.copy WHERE id IN ('promo-copy','later-copy')").fetchone()[0] == 2
    assert before['stock'] == table_digest(db)['stock']
