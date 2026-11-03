"""The core writers M.11c added beside the code they belong to (issue #113): marks outside a check session (`checker.mark`, `set_checked`,
`mark_stock_parts`), the BrickLink part-list preference in `admin.patch_settings`, a colour-scoped manual link (`identity_admin.add_link`), a PDF
attached to a set named by id (`admin.attach_instruction`), the request check of the write transport (`api2.writes.validate`) and the Undo of a
whole write. Also the undone predicate's query plan, ported from test_bw_core_fixes_api. Invented data."""
from contextlib import closing
import json

import pytest

from brickwork.api2 import writes
from brickwork.core import admin, checker, errors, identity_admin, undo
from brickwork.core.connect import connect
from tests.app4 import app4, coll, pair, table_digest, world  # noqa: F401


def one(db, sql, *params):
    return db.execute(sql, params).fetchone()


def part_line(db, copy_id, born_key, colour_key):
    return one(db, '''SELECT p.id, p.quantity FROM main.copy_part p JOIN main.item i ON i.id=p.item_id JOIN main.color c ON c.id=p.color_id
                      WHERE p.copy_id=? AND i.born_key=? AND c.born_key=? AND p.copy_figure_id IS NULL AND p.is_spare=0''', copy_id, born_key, colour_key)


# ---------- marks outside a check session ----------

def test_a_mark_sets_counts_follows_the_derived_completeness_and_is_one_undoable_event(coll, world):
    db, copy = coll.db, world.copy_a
    coll.sql("UPDATE copy SET completeness_source='derived' WHERE id=?", (copy,))
    line = part_line(db, copy, '3001', '4')
    before = table_digest(db)
    event = checker.mark(db, copy, [(f'p:{line["id"]}', {'missing': 0, 'damaged': 0, 'checked': True})])
    stored = one(db, 'SELECT * FROM main.event WHERE id=?', event)
    assert (stored['entity_kind'], stored['entity_id'], stored['field']) == ('part_check', copy, 'save')
    assert one(db, 'SELECT missing, damaged, checked FROM main.copy_part WHERE id=?', line['id'])[:] == (0, 0, 1)
    assert one(db, 'SELECT completeness FROM main.copy WHERE id=?', copy)[0] == 'complete'              # the one missing brick is back
    assert one(db, f'SELECT {undo.undoable_sql()} FROM main.event e WHERE e.id=?', event)[0] == 1
    undo.undo_event(db, event, via='cli')
    assert table_digest(db) == before


def test_a_mark_is_checked_against_the_lines_quantity_and_the_copy(coll, world):
    db, copy = coll.db, world.copy_a
    line = part_line(db, copy, '3001', '4')
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', ('2026-10-01T00:00:00.000Z', world.copy_c))
    before = table_digest(db)
    for fields in ({'missing': line['quantity'] + 1}, {'damaged': -1}, {'missing': True}, {'checked': 1}, {}):
        with pytest.raises(errors.ValidationFailed):
            checker.mark(db, copy, [(f'p:{line["id"]}', fields)])
    with pytest.raises(errors.NotFound):
        checker.mark(db, copy, [('p:999999', {'missing': 0})])
    with pytest.raises(errors.ValidationFailed):
        figure = one(db, 'SELECT id FROM main.copy_figure WHERE copy_id=?', copy)[0]
        checker.mark(db, copy, [(f'f:{figure}', {'damaged': 1})])                                      # a whole figure has a missing count only
    with pytest.raises(ValueError):
        checker.mark(db, world.copy_b, [(f'p:{line["id"]}', {'missing': 0})])                          # the line belongs to another copy: not found
    with pytest.raises(ValueError):
        checker.mark(db, world.copy_c, [])                                                             # an archived copy takes no marks
    assert table_digest(db) == before                                                                  # each refusal wrote nothing, event included


def test_two_lines_marked_together_are_one_event_and_a_retired_line_is_no_line(coll, world):
    db, copy = coll.db, world.copy_a
    brick, plate = part_line(db, copy, '3001', '4'), part_line(db, copy, '3023', '15')
    event = checker.mark(db, copy, [(f'p:{brick["id"]}', {'missing': 0}), (f'p:{plate["id"]}', {'missing': 1})])
    assert one(db, "SELECT count(*) FROM main.event WHERE entity_kind='part_check'")[0] == 1
    assert [tuple(r) for r in db.execute('SELECT missing FROM main.copy_part WHERE id IN (?,?) ORDER BY id', (brick['id'], plate['id']))] == [(0,), (1,)]
    undo.undo_event(db, event, via='cli')
    assert [tuple(r) for r in db.execute('SELECT missing FROM main.copy_part WHERE id IN (?,?) ORDER BY id', (brick['id'], plate['id']))] == [(1,), (0,)]
    coll.retire_line(copy, '3023', '15')
    with pytest.raises(errors.NotFound):
        checker.mark(db, copy, [(f'p:{plate["id"]}', {'missing': 0})])


def test_the_checked_flag_is_made_when_wanted_and_a_clear_without_it_writes_no_flag(coll):
    db = coll.db
    copy = coll.add_copy('1000-1')
    assert one(db, "SELECT count(*) FROM main.flag WHERE name='Set is checked'")[0] == 0
    cleared = checker.set_checked(db, copy, False)
    assert one(db, "SELECT count(*) FROM main.flag WHERE name='Set is checked'")[0] == 0 and one(db, 'SELECT id FROM main.event WHERE id=?', cleared)
    wanted = checker.set_checked(db, copy, True)
    flag = one(db, "SELECT id, system FROM main.flag WHERE name='Set is checked'")
    assert flag['system'] == 1 and checker.checked(db, copy)
    undo.undo_event(db, wanted, via='cli')
    assert not checker.checked(db, copy)
    undo.undo_event(db, cleared, via='cli')


def test_the_parts_of_a_loose_minifigure_are_marked_in_one_collection_receipt(coll, world):
    db = coll.db
    line = one(db, 'SELECT * FROM main.stock_part WHERE stock_id=? AND is_spare=0 LIMIT 1', world.stock_figure)
    before = table_digest(db)
    event = checker.mark_stock_parts(db, world.stock_figure, [(line['item_id'], line['color_id'], 0, {'missing': 1, 'checked': True})])
    assert one(db, 'SELECT entity_kind, field FROM main.event WHERE id=?', event)[:] == ('collection', 'save')
    assert one(db, 'SELECT missing, checked FROM main.stock_part WHERE id=?', line['id'])[:] == (1, 1)
    undo.undo_event(db, event, via='cli')
    assert table_digest(db) == before
    for edits, expected in (([(line['item_id'], line['color_id'], 0, {'missing': line['quantity'] + 1})], errors.ValidationFailed),
                            ([(line['item_id'], line['color_id'], 0, {'missing': 0}), (line['item_id'], line['color_id'], 0, {'missing': 0})], errors.ValidationFailed),
                            ([(world.keep, 1, 0, {'missing': 0})], errors.NotFound)):
        with pytest.raises(expected):
            checker.mark_stock_parts(db, world.stock_figure, edits)
    with pytest.raises(errors.ValidationFailed):
        checker.mark_stock_parts(db, world.stock_brick, [(line['item_id'], line['color_id'], 0, {'missing': 0})])      # a part line is not a figure
    with pytest.raises(errors.NotFound):
        checker.mark_stock_parts(db, 'nope', [])


# ---------- settings ----------

def test_the_bricklink_preference_is_a_whitelisted_setting_with_its_own_event(coll):
    db = coll.db
    assert admin.patch_settings(db, {'prefer_bricklink_inventory': True})['retail_country']
    assert one(db, "SELECT value FROM main.setting WHERE key='prefer_bricklink_inventory'")[0] == 'true'
    count = one(db, 'SELECT count(*) FROM main.event')[0]
    admin.patch_settings(db, {'prefer_bricklink_inventory': True})
    assert one(db, 'SELECT count(*) FROM main.event')[0] == count                                      # already so: no event
    admin.patch_settings(db, {'prefer_bricklink_inventory': False})
    assert one(db, "SELECT value FROM main.setting WHERE key='prefer_bricklink_inventory'") is None
    with pytest.raises(errors.ValidationFailed):
        admin.patch_settings(db, {'prefer_bricklink_inventory': 'yes'})
    with pytest.raises(errors.UnsupportedSetting):
        admin.patch_settings(db, {'bricklink_key': 'x'})


# ---------- identity ----------

def test_a_link_for_one_colour_is_its_own_row_and_another_items_unscoped_link_may_sit_beside_it(coll, world):
    db = coll.db
    scoped = identity_admin.add_link(db, world.brick, '3001s', world.red)
    assert one(db, 'SELECT color_id, status, origin, preferred FROM main.item_link WHERE item_id=? AND provider_key=?', world.brick, '3001s')[:] == (world.red, 'manual', 'user', 0)
    assert one(db, "SELECT field FROM main.event WHERE id=?", scoped['event_id'])[0] == 'add'
    identity_admin.add_link(db, world.brick, '3001s')                                                  # the same number for every colour: a second row
    assert one(db, 'SELECT count(*) FROM main.item_link WHERE item_id=? AND provider_key=?', world.brick, '3001s')[0] == 2
    with pytest.raises(errors.Conflict):
        identity_admin.add_link(db, world.brick, '3001s', world.red)                                   # there already
    with pytest.raises(errors.Conflict):
        identity_admin.add_link(db, world.plate, '3001s', world.red)                                   # another item holds it for that colour
    identity_admin.add_link(db, world.plate, '3001s', world.white)                                     # for another colour it may
    with pytest.raises(errors.ValidationFailed):
        identity_admin.add_link(db, world.brick, '3001t', 99999)


# ---------- a PDF named by item id ----------

def test_a_pdf_belongs_to_the_set_a_set_or_its_booklet_names(coll, world, tmp_path):
    db = coll.db
    assert admin.instruction_set_of(db, world.keep) == world.keep
    assert admin.instruction_set_of(db, world.local_booklet) == world.keep
    for item in (world.brick, world.mystery, 987654321):
        with pytest.raises(ValueError):
            admin.instruction_set_of(db, item)
    root = tmp_path / 'media'
    identifier = admin.attach_instruction(db, root, world.keep, 'Booklet', b'%PDF-1.4\n%%EOF', undoable=True)
    assert one(db, 'SELECT item_id, label FROM main.instruction_file WHERE id=?', identifier)[:] == (world.keep, 'Booklet')
    assert len(list((root / 'data/instructions').glob('*.pdf'))) == 1
    for content, label in ((b'no', 'x'), (b'%PDF-1.4', ''), (b'%PDF-' + b'0' * (20 * 1024 * 1024), 'x')):
        with pytest.raises(ValueError):
            admin.attach_instruction(db, root, world.keep, label, content)


# ---------- the request check ----------

SCHEMA = {'type': 'object', 'properties': {'n': {'type': 'integer', 'minimum': 0}, 's': {'type': ['string', 'null'], 'pattern': '^[A-Z]{3}$'},
                                           'e': {'type': 'string', 'enum': ['a', 'b']}, 'l': {'type': 'array', 'minItems': 1, 'maxItems': 2, 'items': {'type': 'integer'}},
                                           'f': {'type': 'number'}, 'b': {'type': 'boolean'},
                                           'm': {'type': 'object', 'additionalProperties': {'type': 'array', 'items': {'type': 'string'}}}}, 'required': ['n']}


@pytest.mark.parametrize('value,fine', [
    ({'n': 0}, True), ({'n': 3, 's': None, 'e': 'a', 'l': [1], 'f': 1, 'b': True, 'm': {'x': ['y']}}, True), ({'n': 1.5, }, False), ({'n': True}, False), ({'n': -1}, False),
    ({}, False), ({'n': 1, 'x': 1}, False), ({'n': 1, 's': 'abcd'}, False), ({'n': 1, 's': 'ABC'}, True), ({'n': 1, 'e': 'c'}, False), ({'n': 1, 'l': []}, False),
    ({'n': 1, 'l': [1, 2, 3]}, False), ({'n': 1, 'l': ['a']}, False), ({'n': 1, 'f': 'x'}, False), ({'n': 1, 'b': 1}, False), ({'n': 1, 'm': {'x': 'y'}}, False),
    ({'n': 1, 'm': {'x': [1]}}, False)])
def test_the_request_check_reads_the_contract_vocabulary(value, fine):
    saved = dict(writes.SCHEMAS)
    try:
        if fine:
            assert writes.validate(value, SCHEMA) == value
        else:
            with pytest.raises(errors.ValidationFailed):
                writes.validate(value, SCHEMA)
    finally:
        writes.SCHEMAS.clear()
        writes.SCHEMAS.update(saved)


def test_an_item_key_is_by_id_or_by_kind_and_key_never_both_or_neither():
    key = {'$ref': '#/components/schemas/ItemKey'}
    for fine in ({'id': 5}, {'kind': 'set', 'key': '1000-1'}, {'provider': 'rebrickable', 'kind': 'part', 'key': '3001'}):
        assert writes.validate(fine, key) == fine
    for bad in ({}, {'id': 5, 'kind': 'set', 'key': '1'}, {'kind': 'set'}, {'key': '1'}, {'id': 'five'}, {'provider': 'lego', 'kind': 'set', 'key': '1'}, {'kind': 'planet', 'key': '1'}):
        with pytest.raises(errors.ValidationFailed):
            writes.validate(bad, key)


# ---------- Undo of a whole write ----------

def test_undo_reaches_back_over_the_events_of_one_v2_write_only(coll, world):
    db = coll.db
    from brickwork.core import collection
    from brickwork.core.admin import operation
    with operation(writes.PREFIX + 'one'):
        first = collection.save(db, 'copy', [world.copy_b], {'note': 'one'})
        second = collection.save(db, 'wish', [world.wish_part], {'note': 'two'})
    with operation('web-request'):
        third = collection.save(db, 'copy', [world.copy_c], {'note': 'three'})
        fourth = collection.save(db, 'copy', [world.copy_a], {'note': 'four'})
    undone, last, already = writes.undo_operation(db, second, via='cli', actor=None, identity=None)
    assert (undone, already) == (second, False) and undo.is_undone(db, first) and undo.is_undone(db, second)
    undone, last, already = writes.undo_operation(db, fourth, via='cli', actor=None, identity=None)
    assert not undo.is_undone(db, third) and undo.is_undone(db, fourth)                                # a web request's events are undone one by one
    assert writes.undo_operation(db, fourth, via='cli', actor=None, identity=None)[2] is True
    with pytest.raises(errors.NotFound):
        writes.undo_operation(db, 999999, via='cli', actor=None, identity=None)


# ---------- the undone predicate ----------

def test_the_undone_predicate_uses_the_undo_tables_key_and_means_what_it_says(coll, world):
    db = coll.db
    from brickwork.core import collection
    first = collection.save(db, 'copy', [world.copy_b], {'note': 'one'})
    second = collection.save(db, 'copy', [world.copy_c], {'note': 'two'})
    undo.undo_event(db, first, via='cli')
    plan = ' '.join(r[3] for r in db.execute(f'EXPLAIN QUERY PLAN SELECT e.*, {undo.undone_sql()} FROM main.event e WHERE e.id=?', (first,)))
    assert 'SCAN event_undo' not in plan and 'SCAN u' not in plan, plan
    flags = {r['id']: r['undone'] for r in db.execute(f'SELECT e.id, {undo.undone_sql()} AS undone FROM main.event e WHERE e.id IN (?, ?)', (first, second))}
    assert flags == {first: 1, second: 0}
