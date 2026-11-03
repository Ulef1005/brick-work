"""Merge, unmerge and the kind move on the 4.0 store (M.8i part 2, issue #110; design 3.5, 3.6): what moves, where two rows meet, what is
refused, and that unmerge and the kind move's undo put every table back byte for byte. Invented data only, no network."""
import json

import pytest

from brickwork.store4 import merge as moves
from brickwork.store4.errors import MergeRefused
from tests.app4 import STAMP, app4, client, coll, csrf, pair, read, table_digest, world  # noqa: F401  (the fixtures)


def merged_world(coll, world):
    """`world.local_part` (BrickLink-born x999, red, stock x5 used) set up to meet `world.brick` (3001) on every unique key."""
    local, brick, red = world.local_part, world.brick, world.red
    coll.add_stock('part', brick, colour=red, quantity=2, condition='used')                         # meets the local stock on the merge key
    coll.add_wish(local, colour=red, quantity=1, condition='used')
    coll.add_wish(brick, colour=red, quantity=2, condition='new')                                   # meets it on the live wish key
    coll.price(local, '1.00', colour=red, condition='used', key='P:x999/5')                         # the same price_current key as the brick's
    coll.price(local, '3.00', colour=world.white, condition='used', key='P:x999/1')                 # a key only the loser holds
    coll.prop(local, 'theme', 'Local theme', source='bricklink')
    coll.prop(brick, 'theme', 'Brick theme', source='bricklink')
    coll.prop(local, 'weight', '2.5', source='bricklink')
    coll.link(local, '3001', kind='P', status='matched')                                            # the survivor holds this link already
    coll.link(local, '3001a', kind='P', status='inferred', preferred=1)
    coll.link(brick, '3001b', kind='P', status='inferred', preferred=1)                             # the survivor's own preferred link
    coll.link(local, '3001', kind='parts', provider='rebrickable', status='to_check')               # a migration candidate: the merge decides it
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'rebrickable','to_check','migration',NULL,?)",
             (local, STAMP))
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','unmatched','no_match',NULL,?)",
             (local, STAMP))
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','unmatched','no_match',NULL,?)",
             (brick, STAMP))
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/a.png',?)", (local, STAMP))
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/b.png',?)", (brick, STAMP))
    coll.sql("INSERT INTO price_watch(item_id,color_id,condition,origin) VALUES(?,?,'used','test')", (local, red))
    coll.sql("INSERT INTO price_watch(item_id,color_id,condition,origin) VALUES(?,?,'used','test')", (brick, red))
    return local, brick


def count(db, table, **where):
    clause = ' AND '.join(f'{k}=?' for k in where) or '1'
    return db.execute(f'SELECT count(*) FROM main.{table} WHERE {clause}', tuple(where.values())).fetchone()[0]


def test_a_merge_moves_every_reference_and_resolves_every_meeting_as_the_rules_say(coll, world):
    db = coll.db
    local, brick = merged_world(coll, world)
    before = table_digest(db)
    result = moves.merge(db, local, brick, via='cli')
    row = db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()
    assert row[0] == brick and tuple(db.execute('SELECT old_id,new_id FROM main.item_redirect').fetchone()) == (local, brick)
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    for table in ('stock', 'wish', 'price_observation', 'price_current', 'item_property', 'item_link', 'item_provider_status', 'picture', 'price_watch'):
        assert count(db, table, item_id=local) == 0, table
    # stock: summed into the survivor's live row, the loser's archived under the survivor's id
    live = db.execute("SELECT quantity FROM main.stock WHERE item_id=? AND color_id=? AND condition='used' AND lot_id IS NULL AND storage_id IS NULL AND archived_at IS NULL",
                      (brick, world.red)).fetchall()
    assert [r[0] for r in live] == [7]
    assert db.execute('SELECT archived_at IS NOT NULL FROM main.stock WHERE id=?', (world.stock_local,)).fetchone()[0] == 1
    # wishes: summed, the loser's archived
    assert [r[0] for r in db.execute('SELECT quantity FROM main.wish WHERE item_id=? AND archived_at IS NULL AND color_id=?', (brick, world.red))] == [3]
    # prices: the observations all move, the survivor's price_current stays and the loser's other key comes over
    assert count(db, 'price_observation', item_id=brick) == 3
    assert {tuple(r) for r in db.execute('SELECT color_id, condition FROM main.price_current WHERE item_id=?', (brick,))} == {(world.red, 'used'), (world.white, 'used')}
    assert db.execute('SELECT o.price FROM main.price_current c JOIN main.price_observation o ON o.id=c.observation_id WHERE c.item_id=? AND c.color_id=?',
                      (brick, world.red)).fetchone()[0] == '0.40'
    # properties and pictures: the survivor's stay, the loser's other keys come over
    assert {r[0]: r[1] for r in db.execute('SELECT key, value FROM main.item_property WHERE item_id=?', (brick,))} == {'theme': 'Brick theme', 'weight': '2.5'}
    assert count(db, 'picture', item_id=brick) == 1 and count(db, 'price_watch', item_id=brick) == 1
    # links: the doubled one is dropped, the to_check guess is decided, the other moves, and the survivor keeps its one preferred link
    links = {(r['provider'], r['provider_key'], r['status'], r['preferred']) for r in db.execute('SELECT * FROM main.item_link WHERE item_id=?', (brick,))}
    assert ('bricklink', '3001a', 'inferred', 0) in links and ('bricklink', '3001b', 'inferred', 1) in links
    assert not any(l[0] == 'rebrickable' for l in links) and sum(1 for l in links if l[1] == '3001') == 1
    # statuses: the to_check one is gone, the no_match twins are one
    assert [tuple(r) for r in db.execute('SELECT status, reason FROM main.item_provider_status WHERE item_id=?', (brick,))] == [('unmatched', 'no_match')]
    # the loser's born number still finds the survivor
    assert ('bricklink', 'x999', 'inferred', 0) in links
    event = db.execute('SELECT * FROM main.event WHERE id=?', (result['event_id'],)).fetchone()
    assert (event['entity_kind'], event['entity_id'], event['field'], event['old_value']) == ('item', str(brick), 'merge', str(local))
    merge = db.execute('SELECT * FROM main.item_merge WHERE id=?', (result['merge_id'],)).fetchone()
    assert (merge['survivor_id'], merge['merged_id'], merge['event_id'], merge['undone_at']) == (brick, local, result['event_id'], None)
    assert json.loads(merge['receipt_json'])
    undone = moves.unmerge(db, result['merge_id'], via='cli')
    assert table_digest(db) == before
    assert db.execute('SELECT undone_at IS NOT NULL, undo_event_id FROM main.item_merge WHERE id=?', (result['merge_id'],)).fetchone()[:] == (1, undone['event_id'])
    assert db.execute('SELECT undo_event_id FROM main.event_undo WHERE event_id=?', (result['event_id'],)).fetchone()[0] == undone['event_id']
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_a_merge_of_a_catalogue_item_the_catalogue_retired_works_and_unmerges(coll, world):
    db = coll.db
    coll.sql("UPDATE item SET catalogue_retired_at=? WHERE id=?", (STAMP, world.plate))
    before = table_digest(db)
    result = moves.merge(db, world.plate, world.brick, via='app')
    assert count(db, 'stock', item_id=world.plate) == 0 and db.execute('SELECT merged_into FROM main.item WHERE id=?', (world.plate,)).fetchone()[0] == world.brick
    assert ('rebrickable', 'parts', '3023') in {(r['provider'], r['provider_kind'], r['provider_key']) for r in db.execute('SELECT * FROM main.item_link WHERE item_id=?', (world.brick,))}
    moves.unmerge(db, result['merge_id'], via='app')
    assert table_digest(db) == before


def test_a_merge_projects_a_survivor_that_is_only_in_the_catalogue(coll, world):
    db = coll.db
    only = coll.item('parts', '970c22')
    assert db.execute('SELECT 1 FROM main.item WHERE id=?', (only,)).fetchone() is None
    local = coll.local('part', 'Another local part', born_key='y1')
    result = moves.merge(db, local, only, via='cli')
    assert db.execute('SELECT origin FROM main.item WHERE id=?', (only,)).fetchone()[0] == 'catalogue'
    assert ('bricklink', 'y1') in {(r['provider'], r['provider_key']) for r in db.execute('SELECT * FROM main.item_link WHERE item_id=?', (only,))}
    moves.unmerge(db, result['merge_id'], via='cli')
    assert db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()[0] is None


@pytest.mark.parametrize('case', ['live_catalogue', 'merged_survivor', 'kind', 'self', 'merged_loser', 'unknown'])
def test_the_refusals_leave_nothing_changed(coll, world, case):
    db = coll.db
    before = table_digest(db)
    local, brick = world.local_part, world.brick
    if case == 'live_catalogue':
        args, message = (world.plate, brick), 'live catalogue item'
    elif case == 'merged_survivor':
        other, third = coll.local('part', 'Gone', born_key='gone'), coll.local('part', 'Third', born_key='third')
        moves.merge(db, other, local, via='cli')
        before = table_digest(db)
        args, message = (third, other), 'merged itself'
    elif case == 'kind':
        args, message = (local, world.keep), 'its own kind'
    elif case == 'self':
        args, message = (local, local), 'into itself'
    elif case == 'merged_loser':
        other = coll.local('part', 'Gone', born_key='gone')
        moves.merge(db, other, local, via='cli')
        before = table_digest(db)
        args, message = (other, brick), 'merged already'
    else:
        args, message = (999999999, brick), 'not in this collection'
    with pytest.raises(MergeRefused, match=message):
        moves.merge(db, *args, via='cli')
    assert table_digest(db) == before and not db.in_transaction


def test_a_copy_that_holds_lines_for_both_items_is_refused_by_name(coll, world):
    db = coll.db
    coll.sql("INSERT INTO copy_part(copy_id,item_id,color_id,quantity) VALUES(?,?,?,1)", (world.copy_a, world.local_part, world.red))
    before = table_digest(db)
    with pytest.raises(MergeRefused, match=f'copy {world.copy_a} holds a part line for both items'):
        moves.merge(db, world.local_part, world.brick, via='cli')
    assert table_digest(db) == before
    coll.sql("UPDATE copy_part SET color_id=? WHERE copy_id=? AND item_id=?", (world.white, world.copy_a, world.local_part))
    result = moves.merge(db, world.local_part, world.brick, via='cli')                      # another colour is another line: no meeting
    assert count(db, 'copy_part', item_id=world.local_part) == 0
    moves.unmerge(db, result['merge_id'], via='cli')


def test_fetched_lists_come_over_after_the_survivors_and_are_not_latest_beside_one(coll, world):
    db = coll.db
    local = coll.local('set', 'Local set', born_key='9999-1')
    survivor = world.gate
    for item, seq, latest in ((survivor, 1, 0), (survivor, 2, 1), (local, 1, 0), (local, 2, 1)):
        coll.sql("INSERT INTO fetched_inventory(item_id,source,seq,is_latest,fetched_at,digest,part_lines,figure_lines) VALUES(?,'bricklink',?,?,?,'d',0,0)",
                 (item, seq, latest, STAMP))
    first = db.execute('SELECT id FROM fetched_inventory WHERE item_id=? AND seq=2', (local,)).fetchone()[0]
    coll.sql("""INSERT INTO copy(id,item_id,inventory_source,fetched_inventory_id,inventory_digest,created_at,updated_at) VALUES('local-copy',?,'bricklink',?,'d',?,?)""",
             (local, first, STAMP, STAMP))
    before = table_digest(db)
    result = moves.merge(db, local, survivor, via='cli')
    rows = [tuple(r) for r in db.execute('SELECT seq, is_latest FROM main.fetched_inventory WHERE item_id=? ORDER BY seq', (survivor,))]
    assert rows == [(1, 0), (2, 1), (3, 0), (4, 0)]
    assert db.execute("SELECT item_id FROM main.copy WHERE id='local-copy'").fetchone()[0] == survivor
    moves.unmerge(db, result['merge_id'], via='cli')
    assert table_digest(db) == before


def test_unmerge_is_refused_after_a_later_change_and_after_it_ran(coll, world):
    db = coll.db
    local, brick = merged_world(coll, world)
    result = moves.merge(db, local, brick, via='cli')
    coll.sql("UPDATE stock SET quantity=quantity+1 WHERE item_id=? AND color_id=? AND condition='used' AND lot_id IS NULL AND storage_id IS NULL AND archived_at IS NULL", (brick, world.red))
    after = table_digest(db)
    with pytest.raises(MergeRefused, match='stock changed since the merge'):
        moves.unmerge(db, result['merge_id'], via='cli')
    assert table_digest(db) == after and db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()[0] == brick
    coll.sql("UPDATE stock SET quantity=quantity-1 WHERE item_id=? AND color_id=? AND condition='used' AND lot_id IS NULL AND storage_id IS NULL AND archived_at IS NULL", (brick, world.red))
    moves.unmerge(db, result['merge_id'], via='cli')
    with pytest.raises(MergeRefused, match='undone already'):
        moves.unmerge(db, result['merge_id'], via='cli')
    with pytest.raises(MergeRefused, match='does not exist'):
        moves.unmerge(db, 999, via='cli')


def test_an_earlier_merge_cannot_be_undone_under_a_later_one(coll, world):
    db = coll.db
    a = coll.local('part', 'Local A', born_key='a1')
    coll.add_stock('part', a, colour=world.red, quantity=1, condition='new')
    first = moves.merge(db, a, world.local_part, via='cli')
    second = moves.merge(db, world.local_part, world.brick, via='cli')
    with pytest.raises(MergeRefused):
        moves.unmerge(db, first['merge_id'], via='cli')
    moves.unmerge(db, second['merge_id'], via='cli')
    moves.unmerge(db, first['merge_id'], via='cli')


def test_a_merge_inside_a_transaction_that_fails_leaves_nothing(coll, world):
    db = coll.db
    before = table_digest(db)
    db.execute('BEGIN IMMEDIATE')
    moves.merge_in(db, world.local_part, world.brick, via='cli')
    db.rollback()
    assert table_digest(db) == before
    with pytest.raises(Exception):
        moves.merge_in(db, world.local_part, world.brick, via='cli')                         # needs the caller's transaction


# ---------- the kind move ----------

def add_status(coll, item, to):
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','kind_differs',?,?)",
             (item, json.dumps({'from': 'gear', 'to': to}), STAMP))


def test_a_gear_item_becomes_a_book_with_its_stock_and_wish_and_back(coll, world):
    db = coll.db
    coll.add_wish(world.mystery, quantity=1)
    add_status(coll, world.mystery, 'book')
    before = table_digest(db)
    result = moves.move_kind(db, world.mystery, 'book', via='app')
    assert (result['from'], result['to']) == ('gear', 'book')
    assert tuple(db.execute('SELECT kind, kind_source FROM main.item WHERE id=?', (world.mystery,)).fetchone()) == ('book', 'bricklink')
    assert [tuple(r) for r in db.execute('SELECT id, kind, quantity FROM main.stock WHERE item_id=?', (world.mystery,))] == [(world.stock_mystery, 'book', 2)]
    assert db.execute('SELECT kind FROM main.wish WHERE item_id=?', (world.mystery,)).fetchone()[0] == 'book'
    assert count(db, 'item_provider_status', item_id=world.mystery) == 0
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    db.execute('BEGIN IMMEDIATE')
    moves.undo_kind_move_in(db, result['event_id'], via='app')
    db.commit()
    assert table_digest(db) == before


def test_a_kind_chosen_by_hand_is_manual(coll, world):
    moves.move_kind(coll.db, world.mystery, 'catalog', via='app')
    assert coll.db.execute('SELECT kind_source FROM main.item WHERE id=?', (world.mystery,)).fetchone()[0] == 'manual'


def test_a_set_becomes_gear_and_its_copy_stock_with_flags_and_photos(coll, world):
    db = coll.db
    item = coll.local('set', 'A promo item', born_key='promo-1')
    flag = coll.flag('Shelf piece')
    coll.sql("""INSERT INTO copy(id,item_id,inventory_source,condition,storage_id,purchase_price,purchase_currency,note,pinned,created_at,updated_at)
                VALUES('promo-copy',?,'none','used',?,'4.00','EUR','a note',1,?,?)""", (item, world.shelf, STAMP, STAMP))
    coll.tag('copy', 'promo-copy', flag)
    coll.sql("INSERT INTO photo(id,item_id,copy_id,local_path,created_at) VALUES('photo-1',?,'promo-copy','data/images/own/p.jpg',?)", (item, STAMP))
    before = table_digest(db)
    result = moves.move_kind(db, item, 'gear', via='app')
    stock = db.execute('SELECT * FROM main.stock WHERE item_id=?', (item,)).fetchall()
    assert len(stock) == 1 and (stock[0]['kind'], stock[0]['quantity'], stock[0]['condition'], stock[0]['purchase_price'], stock[0]['note']) == ('gear', 1, 'used', '4.00', 'a note')
    assert count(db, 'copy', item_id=item) == 0
    assert [r[0] for r in db.execute('SELECT flag_id FROM main.stock_flag WHERE stock_id=?', (stock[0]['id'],))] == [flag]
    assert tuple(db.execute("SELECT copy_id, stock_id FROM main.photo WHERE id='photo-1'").fetchone()) == (None, stock[0]['id'])
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    db.execute('BEGIN IMMEDIATE')
    moves.undo_kind_move_in(db, result['event_id'], via='app')
    db.commit()
    assert table_digest(db) == before


def test_gear_becomes_a_set_one_copy_per_piece_and_undo_restores(coll, world):
    db = coll.db
    coll.add_wish(world.mystery, quantity=1)
    before = table_digest(db)
    result = moves.move_kind(db, world.mystery, 'set', via='app')
    copies = db.execute('SELECT * FROM main.copy WHERE item_id=?', (world.mystery,)).fetchall()
    assert len(copies) == 2 and {c['inventory_source'] for c in copies} == {'none'} and {c['condition'] for c in copies} == {'new'}
    assert count(db, 'stock', item_id=world.mystery) == 0 and db.execute('SELECT kind FROM main.wish WHERE item_id=?', (world.mystery,)).fetchone()[0] == 'set'
    db.execute('BEGIN IMMEDIATE')
    moves.undo_kind_move_in(db, result['event_id'], via='app')
    db.commit()
    assert table_digest(db) == before


def test_the_kind_move_refuses_what_it_would_lose(coll, world):
    db = coll.db
    before = table_digest(db)
    for item, kind, message in ((world.brick, 'gear', 'only set'), (world.mystery, 'gear', 'a gear already'), (world.mystery, 'part', 'only set'),
                                (world.keep, 'gear', 'has copy part rows'), (world.mystery, 'nonsense', 'only set')):
        with pytest.raises(MergeRefused, match=message):
            moves.move_kind(db, item, kind, via='app')
    assert table_digest(db) == before and not db.in_transaction
    coll.sql("UPDATE stock SET condition='damaged' WHERE id=?", (world.stock_mystery,))
    with pytest.raises(MergeRefused, match='damaged'):
        moves.move_kind(db, world.mystery, 'set', via='app')


def test_a_kind_move_undo_is_refused_after_a_later_change(coll, world):
    db = coll.db
    result = moves.move_kind(db, world.mystery, 'book', via='app')
    coll.sql("UPDATE stock SET quantity=9 WHERE item_id=?", (world.mystery,))
    db.execute('BEGIN IMMEDIATE')
    with pytest.raises(MergeRefused, match='changed since the kind move'):
        moves.undo_kind_move_in(db, result['event_id'], via='app')
    db.rollback()


def test_every_table_that_names_an_item_is_handled_by_the_merge():
    """The schema decides: a new table with an item reference must be added to the merge (or this fails)."""
    import sqlite3
    from pathlib import Path
    db = sqlite3.connect(':memory:')
    db.executescript((Path(moves.__file__).parent / 'brickwork.sql').read_text())
    named = {(t, fk[3]) for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
             for fk in db.execute(f'PRAGMA foreign_key_list("{t}")') if fk[2] == 'item'}
    handled = set(moves.MOVES) | {(t, 'item_id') for t, _ in moves.SHADOWED} | {(t, 'item_id') for t in ('stock', 'wish', 'item_link', 'item_provider_status', 'fetched_inventory')}
    assert named - handled == {('item', 'merged_into'), ('item_merge', 'merged_id'), ('item_merge', 'survivor_id'), ('item_redirect', 'new_id'), ('item_redirect', 'old_id')}


# ---------- Codex review of part 2 ----------

def test_a_row_added_to_a_moved_copy_after_the_merge_blocks_unmerge(coll, world):
    """Finding 1: a photo added to a moved copy names the survivor and the copy, not the loser; putting the copy back would strand it."""
    db = coll.db
    local = coll.local('set', 'Local set', born_key='9999-1')
    coll.sql("INSERT INTO copy(id,item_id,inventory_source,created_at,updated_at) VALUES('local-copy',?,'none',?,?)", (local, STAMP, STAMP))
    result = moves.merge(db, local, world.gate, via='cli')
    coll.sql("INSERT INTO photo(id,item_id,copy_id,local_path,created_at) VALUES('late',?,'local-copy','data/images/own/late.jpg',?)", (world.gate, STAMP))
    after = table_digest(db)
    with pytest.raises(MergeRefused, match='photo changed since the merge'):
        moves.unmerge(db, result['merge_id'], via='cli')
    assert table_digest(db) == after and db.execute("SELECT item_id FROM main.copy WHERE id='local-copy'").fetchone()[0] == world.gate
    coll.sql("DELETE FROM photo WHERE id='late'")
    moves.unmerge(db, result['merge_id'], via='cli')                                                  # nothing added: it goes back
    assert db.execute("SELECT item_id FROM main.copy WHERE id='local-copy'").fetchone()[0] == local


def test_a_photo_that_was_there_at_the_merge_does_not_block_unmerge(coll, world):
    db = coll.db
    local = coll.local('set', 'Local set', born_key='9999-1')
    coll.sql("INSERT INTO copy(id,item_id,inventory_source,created_at,updated_at) VALUES('local-copy',?,'none',?,?)", (local, STAMP, STAMP))
    coll.sql("INSERT INTO photo(id,item_id,copy_id,local_path,created_at) VALUES('early',?,'local-copy','data/images/own/e.jpg',?)", (local, STAMP))
    before = table_digest(db)
    result = moves.merge(db, local, world.gate, via='cli')
    moves.unmerge(db, result['merge_id'], via='cli')
    assert table_digest(db) == before


@pytest.mark.parametrize('quantity', [5, 1])
def test_an_archived_stock_row_makes_one_copy_per_piece_and_undo_restores_it(coll, world, quantity):
    """Finding 2: an archived row of 5 used to become one archived copy and lose 4 pieces."""
    db = coll.db
    coll.sql("UPDATE stock SET quantity=?, archived_at=? WHERE id=?", (quantity, STAMP, world.stock_mystery))
    before = table_digest(db)
    result = moves.move_kind(db, world.mystery, 'set', via='app')
    assert count(db, 'copy', item_id=world.mystery) == quantity and count(db, 'copy', item_id=world.mystery, archived_at=STAMP) == quantity
    db.execute('BEGIN IMMEDIATE')
    moves.undo_kind_move_in(db, result['event_id'], via='app')
    db.commit()
    assert table_digest(db) == before


def test_a_stock_row_of_none_is_refused_and_archived_pieces_with_a_price_too(coll, world):
    db = coll.db
    coll.sql("UPDATE stock SET quantity=0 WHERE id=?", (world.stock_mystery,))
    with pytest.raises(MergeRefused, match='holds none'):
        moves.move_kind(db, world.mystery, 'set', via='app')
    coll.sql("UPDATE stock SET quantity=3, archived_at=?, purchase_price='9.00', purchase_currency='EUR' WHERE id=?", (STAMP, world.stock_mystery))
    with pytest.raises(MergeRefused, match='split the row first'):
        moves.move_kind(db, world.mystery, 'set', via='app')


@pytest.mark.parametrize(('state', 'retry', 'refused'), [('queued', None, True), ('running', None, True), ('waiting_for_budget', None, True),
                                                         ('failed', '2026-10-27T13:00:00.000Z', True), ('failed', None, False), ('done', None, False)])
def test_a_job_in_flight_holds_back_a_merge_an_unmerge_and_a_kind_move(coll, world, state, retry, refused):
    """Finding 3: a worker holding the old id would write to a merged item and be rejected by the guards."""
    db = coll.db

    def job(item):
        return coll.sql("INSERT INTO job(source,kind,item_id,state,retry_at,via,created_at,updated_at) VALUES('bricklink','item',?,?,?,'app',?,?)",
                        (item, state, retry, STAMP, STAMP)).lastrowid
    first = job(world.local_part)
    if refused:
        before = table_digest(db)
        with pytest.raises(MergeRefused, match=f'job {first} '):
            moves.merge(db, world.local_part, world.brick, via='cli')
        assert table_digest(db) == before
        coll.sql('DELETE FROM job WHERE id=?', (first,))
    else:
        moves.unmerge(db, moves.merge(db, world.local_part, world.brick, via='cli')['merge_id'], via='cli')
        coll.sql('DELETE FROM job WHERE id=?', (first,))
    merged = moves.merge(db, world.local_part, world.brick, via='cli')
    second = job(world.brick)
    if refused:
        with pytest.raises(MergeRefused, match=f'job {second} '):
            moves.unmerge(db, merged['merge_id'], via='cli')
        with pytest.raises(MergeRefused, match=f'job {second} '):
            moves.move_kind(db, world.brick, 'gear', via='app')
    coll.sql('DELETE FROM job WHERE id=?', (second,))
    moves.unmerge(db, merged['merge_id'], via='cli')
    third = job(world.mystery)
    if refused:
        with pytest.raises(MergeRefused, match=f'job {third} '):
            moves.move_kind(db, world.mystery, 'book', via='app')
    else:
        moves.move_kind(db, world.mystery, 'book', via='app')
