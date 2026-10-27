"""The Workbench on the 4.0 store (M.8e, issue #110): gaps, the Matcher, the Part Picker, Take and Give, Found it, booklets and their Undo.

Rewritten from the 3.3 file of the same name on `tests/app4.py` fixtures. What changed with the model: a gap and its stock meet by item id
(and colour), booklets and boxes by the set's BrickLink number; every move writes one `workbench` receipt event and `stock_transfer` rows
that name it; retired lines are never gaps; a loose figure's gaps are its `stock_part` rows. The 3.3 tests whose premise is gone are listed
at the end, each with its reason.
"""
from contextlib import closing
import json
import sqlite3

import pytest

from brickwork.core import collection, errors, workbench as w
from brickwork.core.connect import connect
from tests.app4 import STAMP, app4, client, coll, csrf, pair, post, read, world  # noqa: F401 (fixtures)


def part_line(db, copy, item, colour):
    return db.execute('SELECT id FROM copy_part WHERE copy_id=? AND item_id=? AND color_id=? AND copy_figure_id IS NULL AND retired_at IS NULL', (copy, item, colour)).fetchone()[0]


def stock_quantity(db, stock_id):
    return db.execute('SELECT quantity FROM stock WHERE id=?', (stock_id,)).fetchone()[0]


def line_state(db, line_id):
    r = db.execute('SELECT missing,damaged FROM copy_part WHERE id=?', (line_id,)).fetchone()
    return r[0], r[1]


def targets(rows, kind):
    return [r for r in rows if r['target'] == kind]


def derived_copy(coll, **fields):
    """A used copy of 1000-1 whose completeness follows its gaps: checked, booklet and box present, nothing missing yet."""
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived', **fields)
    for name in ('Set is checked', 'Instructions present', 'Box present'):
        coll.tag('copy', copy, coll.flag(name, 'status'))
    return copy


def test_gaps_of_the_world_are_lines_booklets_and_boxes(world, coll):
    found = w.gaps(coll.db)
    parts = targets(found, 'part')
    assert [(g['copy_id'], g['number_text'], g['color_name'], g['need']) for g in parts] == [(world.copy_a, '3001', 'Red', 1)]
    assert parts[0]['copy']['label'] == 'Set 1' and parts[0]['copy']['set_no'] == '1000-1'
    # A booklet and a box gap for every set copy that lacks the status flag, each on its own copy.
    for kind in ('instructions', 'box'):
        assert {g['copy_id'] for g in targets(found, kind)} == {world.copy_a, world.copy_b, world.copy_c}
    assert {g['name'] for g in targets(found, 'box')} == {'Box missing'}
    assert {g['key'] for g in targets(found, 'box') if g['copy_id'] == world.copy_c} == {('box', '2070-1')}
    # No status flag by that name, no gap of that kind.
    coll.sql("UPDATE flag SET archived_at=? WHERE name='Box present'", (STAMP,))
    assert not targets(w.gaps(coll.db), 'box')


def test_retired_spare_archived_and_figure_lines_are_not_set_gaps(world, coll):
    db = coll.db
    plate = part_line(db, world.copy_a, world.plate, world.white)
    coll.mark(world.copy_a, '3023', '15', missing=1)
    assert any(g['target_id'] == plate for g in w.gaps(db))
    coll.retire_line(world.copy_a, '3023', '15')
    assert not any(g['target_id'] == plate for g in w.gaps(db)), 'a retired line is no line'
    coll.sql('UPDATE copy_part SET retired_at=NULL, is_spare=1 WHERE id=?', (plate,))
    assert not any(g['target_id'] == plate for g in w.gaps(db)), 'a spare is not a gap'
    coll.sql('UPDATE copy_part SET is_spare=0 WHERE id=?', (plate,))
    coll.sql('UPDATE copy_part SET missing=1 WHERE copy_id=? AND copy_figure_id IS NOT NULL', (world.copy_a,))
    assert {g['target_id'] for g in targets(w.gaps(db), 'part')} == {plate, part_line(db, world.copy_a, world.brick, world.red)}, 'a figure part is no set gap'
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', (STAMP, world.copy_a))
    assert not [g for g in w.gaps(db) if g['copy_id'] == world.copy_a]


def test_matches_are_exact_by_item_colour_and_usable_stock(world, coll):
    db = coll.db
    rows = targets(w.matches(db), 'part')
    assert {r['source_id'] for r in rows} == {world.stock_brick, world.stock_brick_new}
    assert [r['suggested'] for r in rows] == [1, 1] and {r['have'] for r in rows} == {3, 2}
    assert all(r['key'] == (world.brick, world.red) for r in rows)
    # Another colour of the same part, a damaged row and a row with nothing left are not offered.
    coll.sql('UPDATE stock SET color_id=? WHERE id=?', (world.white, world.stock_brick_new))
    coll.sql("UPDATE stock SET condition='damaged' WHERE id=?", (world.stock_brick,))
    assert not targets(w.matches(db), 'part')
    coll.sql("UPDATE stock SET condition='used', quantity=0 WHERE id=?", (world.stock_brick,))
    assert not targets(w.matches(db), 'part')
    # A stock row's own missing and damaged counts come off what it can give.
    coll.sql('UPDATE stock SET quantity=3, missing=1, damaged=1 WHERE id=?', (world.stock_brick,))
    assert [r['have'] for r in targets(w.matches(db), 'part')] == [1]


def test_a_local_item_never_meets_a_catalogue_gap_and_a_to_check_link_does_not_block(world, coll):
    db = coll.db
    # The BrickLink-only part in stock is another item than the catalogue's 3001: it is not offered for the red 3001 gap.
    assert world.local_part not in {r['item_id'] for r in w.matches(db)}
    # A link still to check names a candidate, not a doubt about the Rebrickable id: the exact match stays offered, the row carries the mark.
    coll.link(world.brick, '3001a', status='to_check')
    rows = targets(w.matches(db), 'part')
    assert rows and all(r['unresolved'] for r in rows)


def test_matches_complete_a_checked_copy_with_one_gap(world, coll):
    db = coll.db
    assert all(r['completes'] for r in targets(w.matches(db), 'part')), 'the world copy is checked and misses one line'
    coll.sql('DELETE FROM copy_flag WHERE copy_id=? AND flag_id=?', (world.copy_a, world.checked))
    assert not any(r['completes'] for r in targets(w.matches(db), 'part')), 'an unchecked copy is not completed by a match'
    coll.tag('copy', world.copy_a, world.checked)
    coll.mark(world.copy_a, '3023', '15', missing=1)
    assert not any(r['completes'] for r in targets(w.matches(db), 'part')), 'two gaps: one match does not complete the copy'


def test_group_matches_cap_stock_within_each_copy(world, coll):
    db = coll.db
    coll.mark(world.copy_a, '3023', '15', missing=2)
    all_gaps = w.gaps(db)
    groups = w.group_matches(db, w.matches(db, all_gaps=all_gaps), all_gaps)
    group = next(g for g in groups if g['copy']['id'] == world.copy_a)
    assert group['missing'] == 1 + 2 + 2 and group['covered'] == 1 + 2 + 1, 'part, plate and the missing booklet and box; the stock covers the first three'
    assert group['kinds'] == ['P', 'I'] and group['owned_copy']
    assert groups[0]['copy']['id'] == world.copy_a, 'the copy the stock covers best comes first'


def test_transfer_writes_one_receipt_stock_transfer_rows_and_undoes(world, coll):
    db = coll.db
    copy = derived_copy(coll)
    coll.mark(copy, '3001', '4', missing=2)
    line = part_line(db, copy, world.brick, world.red)
    event = w.transfer(db, world.stock_brick, copy, 'part', line, 2)
    assert stock_quantity(db, world.stock_brick) == 1 and line_state(db, line) == (0, 0)
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (copy,)).fetchone()[0] == 'complete', 'a derived copy follows its gaps'
    moves = [dict(r) for r in db.execute('SELECT * FROM stock_transfer')]
    assert len(moves) == 1
    move = moves[0]
    assert (move['kind'], move['stock_id'], move['copy_id'], move['copy_part_id'], move['item_id'], move['color_id'], move['quantity'], move['event_id']) == \
        ('part', world.stock_brick, copy, line, world.brick, world.red, 2, event)
    assert json.loads(move['source_snapshot'])['quantity'] == 3 and 'color_key' not in json.loads(move['source_snapshot'])
    assert tuple(db.execute('SELECT entity_kind,field,via FROM event WHERE id=?', (event,)).fetchone()) == ('workbench', 'transfer', 'app')
    assert [(h['action'], h['quantity'], h['label']) for h in w.history(db)] == [('transfer', 2, '3001')]
    # Nothing left to give for that gap: refused, nothing written.
    with pytest.raises(errors.StaleMatch):
        w.transfer(db, world.stock_brick, copy, 'part', line, 1)
    assert stock_quantity(db, world.stock_brick) == 1
    assert collection.undo(db, event)['undo_event_id']
    assert stock_quantity(db, world.stock_brick) == 3 and line_state(db, line) == (2, 0)
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (copy,)).fetchone()[0] == 'incomplete'
    assert db.execute('SELECT count(*) FROM stock_transfer').fetchone()[0] == 1, 'the transfer row stays as provenance'
    assert collection.undo(db, event)['already_undone'] and w.history(db) == []
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_a_manual_completeness_stays_what_the_person_set(world, coll):
    db = coll.db
    line = part_line(db, world.copy_a, world.brick, world.red)
    w.transfer(db, world.stock_brick, world.copy_a, 'part', line, 1)
    assert tuple(db.execute('SELECT completeness,completeness_source FROM copy WHERE id=?', (world.copy_a,)).fetchone()) == ('incomplete', 'manual')


def test_undo_is_refused_after_a_later_change_of_the_same_rows(world, coll):
    db = coll.db
    copy = derived_copy(coll)
    coll.mark(copy, '3001', '4', missing=3)
    line = part_line(db, copy, world.brick, world.red)
    first = w.transfer(db, world.stock_brick, copy, 'part', line, 1)
    second = w.transfer(db, world.stock_brick, copy, 'part', line, 1)
    with pytest.raises(errors.UndoBlocked):
        collection.undo(db, first)
    collection.undo(db, second)
    collection.undo(db, first)
    assert stock_quantity(db, world.stock_brick) == 3 and line_state(db, line) == (3, 0)


def test_transfer_rejects_a_stale_or_foreign_request_and_writes_nothing(world, coll):
    db = coll.db
    line = part_line(db, world.copy_a, world.brick, world.red)
    events = db.execute('SELECT count(*) FROM event').fetchone()[0]
    for args in [(world.stock_plate, world.copy_a, 'part', line, 1),                      # another item
                 (world.stock_brick, world.copy_a, 'part', line, 2),                      # more than missing
                 (world.stock_brick, world.copy_a, 'part', 999, 1),                       # not a line
                 (world.stock_brick, world.copy_b, 'part', line, 1),                      # a line of another copy
                 (world.stock_brick, world.copy_a, 'figure', line, 1),
                 ('nothing', world.copy_a, 'part', line, 1)]:
        with pytest.raises(ValueError):
            w.transfer(db, *args)
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', (STAMP, world.copy_a))
    with pytest.raises(errors.StaleMatch):
        w.transfer(db, world.stock_brick, world.copy_a, 'part', line, 1)
    assert db.execute('SELECT count(*) FROM event').fetchone()[0] == events and stock_quantity(db, world.stock_brick) == 3
    assert db.execute('SELECT count(*) FROM stock_transfer').fetchone()[0] == 0


def test_a_failing_event_rolls_back_every_move(world, coll):
    db = coll.db
    line = part_line(db, world.copy_a, world.brick, world.red)
    db.execute("CREATE TRIGGER reject_workbench BEFORE INSERT ON event WHEN NEW.entity_kind='workbench' BEGIN SELECT RAISE(ABORT,'fixture'); END")
    db.commit()
    with pytest.raises(sqlite3.DatabaseError):
        w.transfer(db, world.stock_brick, world.copy_a, 'part', line, 1)
    assert stock_quantity(db, world.stock_brick) == 3 and line_state(db, line) == (1, 0)


@pytest.mark.parametrize('kind,flag', [('instructions', 'Instructions present'), ('box', 'Box present')])
def test_a_booklet_or_box_is_matched_by_the_sets_bricklink_number(world, coll, kind, flag):
    db = coll.db
    stock_id = coll.add_stock('box', coll.local('box', 'Syn Castle Keep box', born_key='1000-1'), quantity=1) if kind == 'box' else world.stock_booklet
    rows = [r for r in w.matches(db) if r['target'] == kind]
    assert {r['copy_id'] for r in rows} == {world.copy_a, world.copy_b}, 'both copies of 1000-1 miss it; the Duplo copy has another number'
    assert all(r['source_id'] == stock_id and r['have'] == 1 and not r['completes'] for r in rows)
    flag_id = coll.flag(flag, 'status')
    event = w.transfer(db, stock_id, world.copy_a, kind, world.copy_a, 1)
    assert db.execute('SELECT 1 FROM copy_flag WHERE copy_id=? AND flag_id=?', (world.copy_a, flag_id)).fetchone()
    assert stock_quantity(db, stock_id) == 0
    move = db.execute('SELECT kind,copy_id,item_id FROM stock_transfer').fetchone()
    assert tuple(move) == (kind, world.copy_a, db.execute('SELECT item_id FROM stock WHERE id=?', (stock_id,)).fetchone()[0])
    with pytest.raises(ValueError):
        w.transfer(db, stock_id, world.copy_a, kind, world.copy_a, 1)
    collection.undo(db, event)
    assert not db.execute('SELECT 1 FROM copy_flag WHERE copy_id=? AND flag_id=?', (world.copy_a, flag_id)).fetchone()
    assert stock_quantity(db, stock_id) == 1


def test_a_missing_figure_is_filled_with_its_parts_and_undone_together(world, coll):
    db = coll.db
    figure = coll.item('minifigs', 'fig-000004')
    coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    coll.sql('UPDATE copy_part SET missing=1 WHERE copy_figure_id=1 AND id IN (4,5)')
    rows = targets(w.matches(db), 'figure')
    assert len(rows) == 1 and rows[0]['source_id'] == world.stock_figure and rows[0]['key'] == (figure, None)
    event = w.transfer(db, world.stock_figure, world.copy_a, 'figure', rows[0]['target_id'], 1)
    assert db.execute('SELECT missing FROM copy_figure WHERE id=1').fetchone()[0] == 0
    assert db.execute('SELECT sum(missing) FROM copy_part WHERE copy_figure_id=1').fetchone()[0] == 0, 'the figure carries its parts'
    assert stock_quantity(db, world.stock_figure) == 0
    assert tuple(db.execute('SELECT kind,copy_figure_id FROM stock_transfer').fetchone()) == ('figure', 1)
    collection.undo(db, event)
    assert db.execute('SELECT missing FROM copy_figure WHERE id=1').fetchone()[0] == 1
    assert db.execute('SELECT sum(missing) FROM copy_part WHERE copy_figure_id=1').fetchone()[0] == 2


def test_a_loose_figure_with_a_defective_part_is_not_offered(world, coll):
    db = coll.db
    coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    assert targets(w.matches(db), 'figure')
    coll.sql('UPDATE stock_part SET damaged=1 WHERE id=1')
    assert not targets(w.matches(db), 'figure')


def test_loose_figure_gaps_are_filled_by_loose_parts_and_undone(world, coll):
    db = coll.db
    coll.sql('UPDATE stock_part SET missing=1 WHERE id=1')                  # the loose figure misses one of its parts
    part = db.execute('SELECT item_id,color_id FROM stock_part WHERE id=1').fetchone()
    stock_id = coll.add_stock('part', part['item_id'], colour=part['color_id'], quantity=2)
    gap = targets(w.gaps(db), 'stock-part')
    assert len(gap) == 1 and gap[0]['copy_id'] == world.stock_figure and gap[0]['copy']['label'] == 'Loose minifigure'
    rows = [r for r in w.matches(db) if r['target'] == 'stock-part']
    assert [(r['source_id'], r['suggested']) for r in rows] == [(stock_id, 1)] and not rows[0]['completes']
    event = w.transfer(db, stock_id, world.stock_figure, 'stock-part', gap[0]['target_id'], 1)
    assert db.execute('SELECT missing FROM stock_part WHERE id=1').fetchone()[0] == 0 and stock_quantity(db, stock_id) == 1
    assert tuple(db.execute('SELECT kind,copy_id,stock_part_id,stock_id FROM stock_transfer').fetchone()) == ('stock-part', None, 1, stock_id)
    collection.undo(db, event)
    assert db.execute('SELECT missing FROM stock_part WHERE id=1').fetchone()[0] == 1 and stock_quantity(db, stock_id) == 2


def test_take_spans_two_sources_in_one_receipt(world, coll):
    db = coll.db
    copy = derived_copy(coll)
    coll.mark(copy, '3001', '4', missing=4)
    coll.sql('UPDATE stock SET quantity=2 WHERE id=?', (world.stock_brick,))
    line = part_line(db, copy, world.brick, world.red)
    event = w.take_for_gap(db, copy, world.brick, world.red, 4)
    assert stock_quantity(db, world.stock_brick) == 0 and stock_quantity(db, world.stock_brick_new) == 0
    assert line_state(db, line) == (0, 0)
    assert db.execute('SELECT sum(quantity) FROM stock_transfer WHERE event_id=?', (event,)).fetchone()[0] == 4
    assert db.execute('SELECT count(DISTINCT event_id) FROM stock_transfer').fetchone()[0] == 1
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (copy,)).fetchone()[0] == 'complete'
    collection.undo(db, event)
    assert stock_quantity(db, world.stock_brick) == 2 and stock_quantity(db, world.stock_brick_new) == 2 and line_state(db, line) == (4, 0)


def test_take_more_than_missing_or_than_stock_writes_nothing(world, coll):
    db = coll.db
    copy = derived_copy(coll)
    coll.mark(copy, '3001', '4', missing=4)
    events = db.execute('SELECT count(*) FROM event').fetchone()[0]
    with pytest.raises(ValueError, match='Only 4 are missing'):
        w.take_for_gap(db, copy, world.brick, world.red, 5)
    coll.sql('UPDATE stock SET quantity=1 WHERE id=?', (world.stock_brick,))
    with pytest.raises(ValueError, match='Only 3 are left'):
        w.take_for_gap(db, copy, world.brick, world.red, 4)
    with pytest.raises(ValueError, match='Nothing is missing'):
        w.take_for_gap(db, world.copy_c, world.brick, world.red, 1)
    with pytest.raises(ValueError, match='colour'):
        w.take_for_gap(db, copy, world.brick, None, 1)
    coll.sql('UPDATE stock SET quantity=0')
    with pytest.raises(ValueError, match='Nothing is left'):
        w.take_for_gap(db, copy, world.brick, world.red, 1)
    assert db.execute('SELECT count(*) FROM event').fetchone()[0] == events and db.execute('SELECT count(*) FROM stock_transfer').fetchone()[0] == 0


def test_take_a_whole_figure_ignores_a_defective_loose_figure(world, coll):
    db = coll.db
    copy = derived_copy(coll)
    coll.mark_figure(copy, 'fig-000004', missing=1)
    figure = coll.item('minifigs', 'fig-000004')
    sound = coll.add_stock('minifigure', figure, quantity=1)
    coll.sql('UPDATE stock_part SET damaged=1 WHERE stock_id=?', (world.stock_figure,))             # the world's loose figure is defective
    event = w.take_for_gap(db, copy, figure, None, 1)
    assert db.execute('SELECT missing FROM copy_figure WHERE copy_id=?', (copy,)).fetchone()[0] == 0
    assert stock_quantity(db, world.stock_figure) == 1 and stock_quantity(db, sound) == 0, 'the defective figure stayed'
    with pytest.raises(ValueError, match='Nothing is missing'):
        w.take_for_gap(db, copy, figure, None, 1)
    collection.undo(db, event)
    assert stock_quantity(db, sound) == 1


def test_found_destinations_and_the_manual_status(world, coll):
    db = coll.db
    copy = derived_copy(coll)
    coll.mark(copy, '3001', '4', missing=3)
    line = part_line(db, copy, world.brick, world.red)
    event = w.found(db, world.brick, world.red, 'set', {str(line): 2}, 2)
    assert line_state(db, line) == (1, 0)
    later = w.found(db, world.brick, world.red, 'set', {str(line): 1}, 1)
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (copy,)).fetchone()[0] == 'complete'
    with pytest.raises(errors.UndoBlocked):
        collection.undo(db, event)
    collection.undo(db, later)
    collection.undo(db, event)
    assert line_state(db, line) == (3, 0) and db.execute('SELECT completeness FROM copy WHERE id=?', (copy,)).fetchone()[0] == 'incomplete'
    with pytest.raises(errors.StaleMatch):
        w.found(db, world.brick, world.red, 'set', {str(line): 4}, 4)
    with pytest.raises(ValueError):
        w.found(db, world.brick, world.red, 'set', {str(line): 1}, 2)                 # the assignment must add up to the count
    with pytest.raises(ValueError):
        w.found(db, world.brick, None, 'loose', {}, 1)
    held = db.execute('SELECT sum(quantity) FROM stock WHERE item_id=? AND color_id=? AND archived_at IS NULL', (world.brick, world.red)).fetchone()[0]
    loose = w.found(db, world.brick, world.red, 'loose', {}, 4)
    assert db.execute('SELECT sum(quantity) FROM stock WHERE item_id=? AND color_id=? AND archived_at IS NULL', (world.brick, world.red)).fetchone()[0] == held + 4
    collection.undo(db, loose)
    assert db.execute('SELECT sum(quantity) FROM stock WHERE item_id=? AND color_id=? AND archived_at IS NULL', (world.brick, world.red)).fetchone()[0] == held
    missing = db.execute('SELECT sum(missing) FROM copy_part').fetchone()[0]
    listed = w.found(db, world.brick, world.red, 'list', {}, 2)
    assert db.execute('SELECT sum(missing) FROM copy_part').fetchone()[0] == missing
    assert [(h['action'], h['quantity']) for h in w.history(db)] == [('found', 2)]
    collection.undo(db, listed)


def listed_booklets(pair, *numbers):
    """Booklet numbers the BrickLink item list names (catalogue `bricklink_item`, type I); the offline fixture catalogue has none."""
    with sqlite3.connect(pair.with_name('catalogue.db')) as db:
        build = db.execute('SELECT max(id) FROM build').fetchone()[0]
        db.executemany("INSERT INTO bricklink_item(item_type,item_no,name,name_key,build_id) VALUES('I',?,?,?,?)", [(n, 'Booklet ' + n, 'booklet ' + n, build) for n in numbers])


def test_booklets_add_to_stock_create_the_item_once_and_undo(world, coll, pair):
    listed_booklets(pair, '6081-1', '7286-1', '6090-2')
    coll.db.close()
    with closing(connect(pair)) as db:
        event = w.booklets(db, '6081\n7286-1, 2\n6090', 3)
        rows = {r['born_key']: r['quantity'] for r in db.execute("SELECT i.born_key,s.quantity FROM stock s JOIN item i ON i.id=s.item_id WHERE s.kind='instructions' AND s.archived_at IS NULL")}
        assert rows['6081-1'] == 3 and rows['7286-1'] == 2 and rows['6090-2'] == 3
        made = db.execute("SELECT origin,born_provider,born_namespace,name FROM item WHERE born_key='6081-1'").fetchone()
        assert tuple(made) == ('local', 'bricklink', 'I', 'Booklet 6081-1')
        assert db.execute("SELECT status FROM item_link WHERE provider_key='6081-1' AND provider_kind='I'").fetchone()[0] == 'matched'
        again = w.booklets(db, '6081', 1)
        assert db.execute("SELECT quantity FROM stock WHERE item_id=(SELECT id FROM item WHERE born_key='6081-1') AND archived_at IS NULL").fetchone()[0] == 4
        collection.undo(db, again)
        collection.undo(db, event)
        assert not db.execute("SELECT 1 FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key IN ('6081-1','7286-1','6090-2') AND s.archived_at IS NULL AND s.quantity>0").fetchone()
        assert db.execute("SELECT count(*) FROM item WHERE born_key='6081-1'").fetchone()[0] == 1, 'the item an add created stays'
        assert w.history(db) == []


def test_booklets_reject_unknown_and_ambiguous_lines_without_writes(world, coll, pair):
    listed_booklets(pair, '6080-1', '6080-2')
    coll.db.close()
    with closing(connect(pair)) as db:
        before = {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('item', 'stock', 'event')}
        with pytest.raises(ValueError, match='Line 1: 6080 · ambiguous; enter the full booklet number.*Line 3: 123456-1 · unknown booklet number'):
            w.booklets(db, '6080\n6080-1\n123456-1', 1)
        with pytest.raises(ValueError, match='use a set number'):
            w.booklets(db, 'not a number!', 1)
        with pytest.raises(ValueError, match='Line 1: 1000-2.*unknown booklet number'):       # a set's own number does not name its booklet
            w.booklets(db, '1000-2', 1)
        with pytest.raises(ValueError):
            w.booklets(db, '6080-1\n' * 201, 1)
        with pytest.raises(ValueError):
            w.booklets(db, '6080-1', 100)
        assert before == {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in before}


def test_picker_groups_parts_orders_by_keys_and_names_the_disabled_ones(world, coll):
    db = coll.db
    copy = derived_copy(coll)
    coll.mark(copy, '3001', '4', missing=1)
    coll.mark(copy, '3023', '15', missing=2)
    coll.mark(world.copy_a, '3023', '15', missing=1)
    rows = w.picker(db, [world.copy_a, copy])
    assert {(r['number_text'], r['total']) for r in rows} == {('3001', 2), ('3023', 3)}
    brick = next(r for r in rows if r['number_text'] == '3001')
    assert brick['completes'] == 0, 'both copies miss two parts: no single part completes one'
    assert {n['copy_id'] for n in brick['needs']} == {world.copy_a, copy}
    keys = {k['key']: k['reason'] for k in w.picker_keys(rows)}
    assert keys['size'] == 'No part sizes are recorded' and keys['storage'] == ''
    assert brick['rank_storage'] == 'Shelf A'                                  # 3001 red in stock lives in Shelf A
    coll.mark(copy, '3023', '15', missing=0)
    single = w.picker(db, [copy])
    assert [(r['number_text'], r['total'], r['completes']) for r in single] == [('3001', 1, 1)]
    assert w.picker(db, []) == []
    # Unknown keys are ignored and a disabled key never orders.
    assert [r['item_id'] for r in w.picker(db, [world.copy_a, copy], ['size', 'nonsense'])] == [r['item_id'] for r in w.picker(db, [world.copy_a, copy], [])]


def test_picker_category_is_the_items_projected_category(world, coll):
    db = coll.db
    coll.sql("UPDATE item SET category_name='Plates' WHERE id=?", (world.brick,))
    rows = w.picker(db, [world.copy_a])
    assert rows[0]['category'] == 'Plates'
    assert {k['key']: k['reason'] for k in w.picker_keys(rows)}['category'] == ''
    coll.sql("UPDATE item SET category_name='  ' WHERE id=?", (world.brick,))
    again = w.picker(db, [world.copy_a])
    assert again[0]['category'] is None and {k['key']: k['reason'] for k in w.picker_keys(again)}['category'] == 'No category is recorded for these parts'


def test_scoped_gaps_are_the_whole_store_gaps_of_the_relevant_copies(world, coll):
    db = coll.db
    coll.mark(world.copy_a, '3023', '15', missing=1)
    coll.mark(world.copy_b, '3001', '4', missing=2)
    whole = w.gaps(db)
    scope = w.relevant(db, world.brick, world.red, 'part')
    assert scope[0] == {world.copy_a, world.copy_b} and scope[1] == set()
    scoped = w.gaps(db, only=scope)
    assert scoped == [g for g in whole if g['copy_id'] in scope[0]]
    # A booklet can fill any set copy, so every copy is relevant to it.
    assert w.relevant(db, world.local_booklet, None, 'instructions')[0] == {world.copy_a, world.copy_b, world.copy_c}
    # The matches of a scoped read are the whole read's for the same copies.
    assert [(m['target_id'], m['source_id']) for m in w.matches(db, all_gaps=scoped)] == \
        [(m['target_id'], m['source_id']) for m in w.matches(db, all_gaps=whole) if m['copy_id'] in scope[0]]


def test_only_workbench_receipts_are_undone_through_the_workbench(world, coll):
    db = coll.db
    line = part_line(db, world.copy_a, world.brick, world.red)
    event = w.transfer(db, world.stock_brick, world.copy_a, 'part', line, 1)
    other = collection.save(db, 'copy', [world.copy_b], {'note': 'x'})
    with pytest.raises(ValueError):
        w.undo(db, other)
    with pytest.raises(ValueError):
        w.undo(db, 99999)
    assert w.undo(db, event)['undo_event_id']


# Gone with the 3.3 model (the reason each):
# - test_to_check_visible_but_never_consumed: a link still "to check" no longer blocks a match, it marks the row (the module docstring);
#   covered by test_a_local_item_never_meets_a_catalogue_gap_and_a_to_check_link_does_not_block.
# - test_multiple_lineages_one_copy_undo: two rows of one part and colour in a copy cannot exist (`copy_part_key` is unique per line).
# - test_shared_completeness_damage_checked_figures_and_spares: the rule is `store4.copies.derived_completeness`, shared by the checker
#   and the workbench through `completeness.derived_state`; it is tested with the checker (test_bw_checker) and here through the derived
#   copy of test_transfer_writes_one_receipt_stock_transfer_rows_and_undoes.
# - test_matching_queries_grow_linearly_and_transfer_is_local, test_picker_run3_*query_counts, test_carried_empty_gap_snapshot...: the 3.3
#   read model and its statement-count budgets; the 4.0 reads are batched by `collection.decorate` (see test_bw_listspeed).
# - the picker/matcher markup tests (`run3`, `review4`, `review5`, `run6`, `audit`): kept as page tests in test_bw_workbench_ui.py.


def test_giving_one_of_two_missing_figures_clears_one_figures_component_defects(world, coll):
    """A component row's quantity already counts every figure of the line (head 2 for two figures): one figure covers half of it."""
    db = coll.db
    coll.sql('UPDATE copy_figure SET quantity=2, missing=2 WHERE copy_id=?', (world.copy_a,))
    coll.sql('UPDATE copy_part SET missing=quantity WHERE copy_figure_id=1')
    assert db.execute('SELECT min(quantity) FROM copy_part WHERE copy_figure_id=1').fetchone()[0] == 2
    gap = targets(w.gaps(db), 'figure')[0]
    assert gap['need'] == 2
    coll.sql('UPDATE stock SET quantity=2 WHERE id=?', (world.stock_figure,))
    event = w.transfer(db, world.stock_figure, world.copy_a, 'figure', gap['target_id'], 1)
    assert db.execute('SELECT missing FROM copy_figure WHERE id=1').fetchone()[0] == 1
    assert [r[0] for r in db.execute('SELECT missing FROM copy_part WHERE copy_figure_id=1 ORDER BY id')] == [1, 1, 1, 1]
    w.take_for_gap(db, world.copy_a, gap['item_id'], None, 1)
    assert db.execute('SELECT missing FROM copy_figure WHERE id=1').fetchone()[0] == 0
    assert db.execute('SELECT sum(missing) FROM copy_part WHERE copy_figure_id=1').fetchone()[0] == 0
