"""Change a variant on the 4.0 store (issue #151): the owned rows of one catalogue figure move to another of the same kind, BrickLink's number becomes
the other's preferred link, one event and one receipt, and Undo puts every table back byte for byte. Invented data only, no network."""
import json

import pytest

from brickwork.store4 import crosscheck
from brickwork.store4 import merge as moves
from brickwork.store4 import variant
from brickwork.store4.errors import MergeRefused
from tests.app4 import RICH, STAMP, coll, make_pair, table_digest, world  # noqa: F401  (the fixtures)

NUMBER = 'syn-fig-0004'                                          # the fixture catalogue's BrickLink number of fig-000004 (matched, preferred)


@pytest.fixture
def pair(tmp_path):
    """The rich fixture catalogue plus a reissue of the figure, `fig-000005`, with a part list of its own."""
    extra = {'minifigs': [['fig-000005', 'Syn Reissue Figure', 1, '']], 'inventories': [*RICH['inventories'], [99001, 1, 'fig-000005']],
             'inventory_parts': [*RICH['inventory_parts'], [99001, '3023', 15, 1, 'False', '']]}
    return make_pair(tmp_path, rich=True, extra_dump=extra)


def figures(coll, world):
    """`world.figure` (fig-000004: stock x1, a figure line in both copies of 1000-1) is the old variant `a`; `fig-000001` the reissue `b`.
    BrickLink's `syn-fig-0004` is `a`'s preferred number and a link to check on `b`; `a` is also wished."""
    a, b = world.figure, coll.item('minifigs', 'fig-000005')
    coll.project(b)
    assert (NUMBER, 'matched', 1) in links(coll.db, a)
    coll.link(b, NUMBER, kind='M', status='to_check')
    wish = coll.add_wish(a, quantity=2)
    return a, b, wish


def checks_ok(db):
    return [c for c in crosscheck.run(db) if not c['ok']] == []


def links(db, item):
    return {(r['provider_key'], r['status'], r['preferred']) for r in db.execute("SELECT * FROM main.item_link WHERE item_id=? AND provider='bricklink'", (item,))}


def test_a_change_moves_stock_wish_and_figure_lines_keeps_ids_and_the_copies_part_list(coll, world):
    db = coll.db
    a, b, wish = figures(coll, world)
    copy_lines = [tuple(r) for r in db.execute('SELECT id, copy_id, quantity, missing FROM main.copy_figure WHERE item_id=? ORDER BY id', (a,))]
    parts = [tuple(r) for r in db.execute('SELECT * FROM main.copy_part WHERE copy_figure_id IN (SELECT id FROM main.copy_figure WHERE item_id=?) ORDER BY id', (a,))]
    assert copy_lines and parts
    before = table_digest(db)
    result = variant.change_variant(db, a, b, via='cli')
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    # ids and history stay; only the item changes
    assert [tuple(r) for r in db.execute('SELECT id, copy_id, quantity, missing FROM main.copy_figure WHERE item_id=? ORDER BY id', (b,))] == copy_lines
    assert [tuple(r) for r in db.execute('SELECT * FROM main.copy_part WHERE copy_figure_id IN (SELECT id FROM main.copy_figure WHERE item_id=?) ORDER BY id', (b,))] == parts
    assert db.execute('SELECT count(*) FROM main.copy_figure WHERE item_id=?', (a,)).fetchone()[0] == 0
    assert db.execute('SELECT item_id FROM main.stock WHERE id=?', (world.stock_figure,)).fetchone()[0] == b
    assert db.execute('SELECT item_id, quantity FROM main.wish WHERE id=?', (wish,)).fetchone()[:] == (b, 2)
    # b's catalogue has no such list (another digest), so the lines say `migrated` and keep their lines; nothing names a list b lacks
    assert {tuple(r) for r in db.execute('SELECT inventory_source, inventory_version FROM main.copy_figure WHERE item_id=?', (b,))} == {('migrated', None)}
    assert tuple(db.execute('SELECT inventory_source, inventory_version FROM main.stock WHERE id=?', (world.stock_figure,)).fetchone()) == ('migrated', None)
    # BrickLink's number: b's to_check link is confirmed and preferred, a's stops being confirmed
    assert links(db, b) == {(NUMBER, 'manual', 1)} and links(db, a) == {(NUMBER, 'to_check', 0)}
    assert (result['from'], result['to'], result['number']) == (a, b, NUMBER) and result['counts']['item_link'] == {'changed': 2}
    # a stays a plain catalogue item
    assert tuple(db.execute('SELECT origin, merged_into FROM main.item WHERE id=?', (a,)).fetchone()) == ('catalogue', None)
    event = db.execute('SELECT * FROM main.event WHERE id=?', (result['event_id'],)).fetchone()
    assert (event['entity_kind'], event['entity_id'], event['field'], event['old_value'], event['via']) == ('item', str(b), 'change_variant', str(a), 'cli')
    assert json.loads(event['new_value'])['changes'] and checks_ok(db)
    assert table_digest(db) != before


def test_undo_restores_every_row_and_link_exactly_and_the_checks_stay_ok(coll, world):
    db = coll.db
    a, b, _ = figures(coll, world)
    before = table_digest(db)
    result = variant.change_variant(db, a, b, via='app')
    assert checks_ok(db)
    db.execute('BEGIN IMMEDIATE')
    undo = variant.undo_change_variant_in(db, result['event_id'], via='app')
    db.commit()
    assert table_digest(db) == before and checks_ok(db) and db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert db.execute('SELECT undo_event_id FROM main.event_undo WHERE event_id=?', (result['event_id'],)).fetchone()[0] == undo['event_id']
    db.execute('BEGIN IMMEDIATE')
    with pytest.raises(MergeRefused, match='undone already'):
        variant.undo_change_variant_in(db, result['event_id'], via='app')
    db.rollback()


def test_undo_is_refused_after_a_later_change(coll, world):
    db = coll.db
    a, b, _ = figures(coll, world)
    result = variant.change_variant(db, a, b, via='cli')
    coll.sql('UPDATE stock SET quantity=quantity+1 WHERE id=?', (world.stock_figure,))
    after = table_digest(db)
    db.execute('BEGIN IMMEDIATE')
    with pytest.raises(MergeRefused, match='stock changed since the change of variant'):
        variant.undo_change_variant_in(db, result['event_id'], via='cli')
    db.rollback()
    assert table_digest(db) == after


def test_a_new_number_is_added_when_the_other_variant_holds_none(coll, world):
    db = coll.db
    a, b = world.figure, coll.project(coll.item('minifigs', 'fig-000005'))     # projected already: Undo does not unproject
    coll.sql("UPDATE item_link SET status='manual', origin='user' WHERE item_id=? AND provider_key=?", (a, NUMBER))
    before = table_digest(db)
    result = variant.change_variant(db, a, b, via='cli')
    assert links(db, b) == {(NUMBER, 'manual', 1)} and links(db, a) == {(NUMBER, 'to_check', 0)} and result['counts']['item_link'] == {'inserted': 1, 'changed': 1}
    db.execute('BEGIN IMMEDIATE')
    variant.undo_change_variant_in(db, result['event_id'], via='cli')
    db.commit()
    assert table_digest(db) == before


def test_without_a_number_on_either_side_only_the_rows_move(coll, world):
    db = coll.db
    a, b = world.figure, coll.item('minifigs', 'fig-000005')
    coll.sql("DELETE FROM item_link WHERE item_id=? AND provider='bricklink'", (a,))
    result = variant.change_variant(db, a, b, via='cli')
    assert result['number'] is None and 'item_link' not in result['counts'] and db.execute('SELECT item_id FROM main.stock WHERE id=?', (world.stock_figure,)).fetchone()[0] == b


@pytest.mark.parametrize('case', ['kind', 'self', 'merged_from', 'merged_to', 'unknown', 'set'])
def test_the_refusals_leave_nothing_changed(coll, world, case):
    db = coll.db
    a, b, _ = figures(coll, world)
    if case == 'kind':
        args, message = (a, world.brick), 'its own kind'
    elif case == 'self':
        args, message = (a, a), 'become itself'
    elif case == 'merged_from':
        other = coll.local('minifigure', 'Gone', born_key='gone')
        moves.merge(db, other, a, via='cli')
        args, message = (other, b), 'merged already'
    elif case == 'merged_to':
        other = coll.local('minifigure', 'Gone', born_key='gone')
        moves.merge(db, other, b, via='cli')
        args, message = (a, other), 'is merged'
    elif case == 'set':
        args, message = (world.keep, world.gate), 'set cannot change variant'
    else:
        args, message = (999999999, b), 'not in this collection'
    before = table_digest(db)
    with pytest.raises(MergeRefused, match=message):
        variant.change_variant(db, *args, via='cli')
    assert table_digest(db) == before and not db.in_transaction


def test_a_job_in_flight_for_either_item_is_refused(coll, world):
    db = coll.db
    a, b, _ = figures(coll, world)
    coll.sql("INSERT INTO job(source,kind,item_id,state,via,created_at,updated_at) VALUES('bricklink','item',?,'queued','app',?,?)", (b, STAMP, STAMP))
    before = table_digest(db)
    with pytest.raises(MergeRefused, match='still in flight'):
        variant.change_variant(db, a, b, via='cli')
    assert table_digest(db) == before


def test_a_copy_with_a_figure_line_for_both_variants_is_refused_by_name(coll, world):
    db = coll.db
    a, b, _ = figures(coll, world)
    coll.sql("INSERT INTO copy_figure(copy_id,item_id,inventory_source,inventory_digest,quantity,missing,updated_at) VALUES(?,?,'migrated','d',1,0,?)", (world.copy_a, b, STAMP))
    before = table_digest(db)
    with pytest.raises(MergeRefused, match=f'copy {world.copy_a} holds a figure line for both items'):
        variant.change_variant(db, a, b, via='cli')
    assert table_digest(db) == before


def test_stock_and_wishes_that_would_meet_a_live_row_are_refused_not_summed(coll, world):
    db = coll.db
    a, b, wish = figures(coll, world)
    other = coll.add_wish(b, quantity=1)
    before = table_digest(db)
    with pytest.raises(MergeRefused, match=f'wish {wish} would meet wish {other}'):
        variant.change_variant(db, a, b, via='cli')
    assert table_digest(db) == before
    coll.sql('UPDATE wish SET archived_at=? WHERE id=?', (STAMP, other))
    p, q, stock_a = world.plate, world.brick, world.stock_plate        # the same rule for loose parts: white new plates meet white new bricks
    stock_b = coll.add_stock('part', q, colour=world.white, quantity=3, condition='new')
    before = table_digest(db)
    with pytest.raises(MergeRefused, match=f'stock {stock_a} would meet stock {stock_b}'):
        variant.change_variant(db, p, q, via='cli')
    assert table_digest(db) == before


def test_a_row_holding_a_fetched_part_list_of_the_old_variant_is_refused(coll, world):
    db = coll.db
    a, b, _ = figures(coll, world)
    coll.sql("INSERT INTO fetched_inventory(item_id,source,seq,is_latest,fetched_at,digest,part_lines,figure_lines) VALUES(?,'bricklink',1,1,?,'d',0,0)", (a, STAMP))
    fetched_id = db.execute('SELECT id FROM main.fetched_inventory WHERE item_id=?', (a,)).fetchone()[0]
    coll.sql("UPDATE stock SET inventory_source='rebrickable_api', inventory_version=NULL, fetched_inventory_id=? WHERE id=?", (fetched_id, world.stock_figure))
    before = table_digest(db)
    with pytest.raises(MergeRefused, match='holds a fetched part list'):
        variant.change_variant(db, a, b, via='cli')
    assert table_digest(db) == before
