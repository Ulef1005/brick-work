"""Core review fixes on the 4.0 store (M.8d, issue #110): the shared check flag, wish conflicts on restore and Undo, the undone predicate, keyed reads.

What moved: the part inventory resave tests to `test_bw_core_fixes_part_inventory.py` (M.8e) and the API read tests to
`test_bw_core_fixes_api.py` (M.11). What went with its premise: the connect-time upgrade and statistics tests (the 3.2/3.3 upgrade code is
gone since M.8a), the legacy checker receipt (4.0 starts a fresh log) and the Add undo tests (covered by the Add tests of M.8c)."""
import json

import pytest

from brickwork.core import checker, collection, errors, undo
from tests.app4 import coll, pair, world  # noqa: F401 (fixtures)
from tests.test_bw_checker import answer_all, mutate, start


def test_h1_undo_of_first_checked_mark_keeps_the_shared_flag(coll):
    db = coll.db
    a, b = coll.add_copy('1000-1', completeness_source='derived'), coll.add_copy('1000-1', completeness_source='derived')
    flags = []
    for copy in (a, b):
        answer_all(db, copy, start(db, copy))
        mutate(db, copy, 'finish', checked=True)
        flags.append(checker.session(db, copy)['undo'][-1])
    mutate(db, a, 'undo')
    assert not checker.checked(db, a) and checker.checked(db, b)
    assert db.execute("SELECT completeness FROM copy WHERE id=?", (b,)).fetchone()[0] == 'complete'
    rows = db.execute("SELECT id, archived_at FROM flag WHERE name='Set is checked'").fetchall()
    assert len(rows) == 1 and rows[0]['archived_at'] is None
    # The flag is not part of the receipt, only the link: Undo can only ever remove A's association.
    receipt = json.loads(db.execute('SELECT new_value FROM event WHERE id=?', (flags[0],)).fetchone()[0])
    assert 'flags' not in receipt and receipt['checked_flag'] is True


def test_l3_wish_restore_over_a_live_duplicate_is_a_conflict(world, coll):
    db, w = coll.db, world
    collection.save(db, 'wish', [w.wish_part], {}, archive=True)
    coll.add_wish(w.plate, colour=w.white, quantity=3)
    with pytest.raises(errors.Conflict):
        collection.restore(db, 'wish', w.wish_part)
    assert db.execute('SELECT archived_at FROM wish WHERE id=?', (w.wish_part,)).fetchone()[0] is not None


def test_l3_undo_of_wish_archive_over_a_live_duplicate_is_a_conflict(world, coll):
    db, w = coll.db, world
    event = collection.save(db, 'wish', [w.wish_part], {}, archive=True)
    coll.add_wish(w.plate, colour=w.white, quantity=3)
    with pytest.raises(errors.Conflict):
        collection.undo(db, event)
    assert db.execute('SELECT count(*) FROM event_undo').fetchone()[0] == 0


def test_m3_undone_predicate_uses_the_event_undo_key(coll):
    db = coll.db
    plan = ' '.join(r[3] for r in db.execute(f'EXPLAIN QUERY PLAN SELECT e.*,{undo.undone_sql()} undone FROM event e WHERE e.id=?', (1,)))
    # SQLite picks the plan; the point is that the undone lookup never scans the event table.
    assert 'SCAN' not in plan and 'SEARCH u USING INTEGER PRIMARY KEY' in plan, plan


def test_m3_undone_predicate_semantics(world, coll):
    db, w = coll.db, world
    first = collection.save(db, 'copy', [w.copy_a], {'note': 'one'})
    second = collection.save(db, 'copy', [w.copy_a], {'note': 'two'})
    collection.undo(db, second)
    undone = {r[0]: r[1] for r in db.execute(f'SELECT e.id,{undo.undone_sql()} FROM event e WHERE e.id IN (?,?)', (first, second))}
    assert undone == {first: 0, second: 1}
    undoable = {r[0] for r in db.execute(f'SELECT e.id FROM event e WHERE {undo.undoable_sql()}')}
    assert {first, second} <= undoable


@pytest.mark.parametrize('name', ['copy', 'stock'])
def test_m4_keyed_instance_equals_the_full_collection_row(world, coll, name):
    db, w = coll.db, world
    ids = {'copy': [w.copy_a, w.copy_b, w.copy_c], 'stock': [w.stock_brick, w.stock_plate, w.stock_figure, w.stock_mystery]}[name]
    coll.sql("UPDATE copy SET archived_at='2026-01-01T00:00:00.000Z' WHERE id=?", (w.copy_c,))
    full = {r['id']: r for r in collection.instances(db, 'set' if name == 'copy' else None, include_archived=True) if r['entity'] == name}
    for identifier in ids:
        assert collection.instance(db, name, identifier) == full[identifier]
    assert collection.instance(db, name, 'nope') is None
    statements = []
    db.set_trace_callback(statements.append)
    collection.instance(db, name, ids[0])
    db.set_trace_callback(None)
    assert not any('FROM copy c JOIN item' in s and 'WHERE c.id' not in s for s in statements)    # no query reads the whole collection


def test_flag_order_is_stable_between_keyed_and_bulk_reads(world, coll):
    db, w = coll.db, world
    for name in ('zz', 'aa', 'mm'):
        flag = coll.flag(name.upper(), 'tag')
        coll.tag('copy', w.copy_b, flag)
        coll.tag('stock', w.stock_plate, flag)
    for entity, identifier in (('copy', w.copy_b), ('stock', w.stock_plate)):
        full = next(r for r in collection.instances(db, 'set' if entity == 'copy' else 'part') if r['id'] == identifier)
        keyed = collection.instance(db, entity, identifier)
        assert [f['name'] for f in keyed['flags']] == [f['name'] for f in full['flags']] == ['AA', 'MM', 'ZZ']
        assert keyed == full


def test_l7_checker_rows_batch_identities_and_pictures(coll):
    db = coll.db
    copy = coll.add_copy('1000-1')
    for n in range(30):
        item = coll.local('part', f'Extra {n}', born_key=f'x{n}')
        coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity) VALUES(?,?,?,1)', (copy, item, coll.colour('4')))
    coll.link(coll.local('part', 'Pending one', born_key='pending'), 'pending-bl', status='to_check')
    pending = db.execute("SELECT item_id FROM item_link WHERE status='to_check'").fetchone()[0]
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity) VALUES(?,?,?,1)', (copy, pending, coll.colour('4')))
    statements = []
    db.set_trace_callback(statements.append)
    result = checker.rows(db, copy)
    db.set_trace_callback(None)
    assert len(result) >= 33
    unresolved = {r['name']: r['unresolved'] for r in result if r['kind'] == 'part'}
    assert unresolved['Pending one'] is True and sum(r['unresolved'] for r in result) == 1
    assert all('image' in r for r in result)
    assert sum('FROM picture' in s for s in statements) == 1
    assert len(statements) < 15
