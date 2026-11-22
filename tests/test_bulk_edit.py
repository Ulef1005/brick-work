"""#58: bulk edit of copies and loose stock (`collection.bulk_update`): several fields in one save, tags and statuses added, removed or replaced, a
500 cap, the counts a preview shows, one receipt so one Undo, and "Checked on Rebrickable" (#489) taken off as one copy's save takes it off.
Invented data on the fixture world of `tests/app4.py`."""
import json

import pytest

from brickwork.core import collection, undo
from tests.app4 import STAMP, coll, pair, table_digest, world  # noqa: F401 (fixtures)


def row(db, table, identifier):
    return dict(db.execute(f'SELECT * FROM main.{table} WHERE id=?', (identifier,)).fetchone())


def flags(db, table, identifier):
    link, column = collection.ENTITY_FLAGS[table], collection.LINK_TABLES[collection.ENTITY_FLAGS[table]]
    return {r[0] for r in db.execute(f'SELECT flag_id FROM main.{link} WHERE {column}=?', (identifier,))}


def by_field(result):
    return {f['field']: (f['changes'], f['already']) for f in result['fields']}


def test_several_fields_on_three_copies_are_one_event_and_one_undo_puts_every_row_back(coll, world):
    db = coll.db
    copies = [world.copy_a, world.copy_b, world.copy_c]
    before = table_digest(db)
    result = collection.bulk_update(db, 'copy', copies, {'storage_id': world.shelf, 'condition': 'used', 'place_id': world.shop,
                                                          'tags': {'mode': 'add', 'ids': [world.tag]}})
    assert result['rows'] == 3 and result['changed'] == 2 and result['event_id']   # copy A has every value already
    assert by_field(result) == {'storage_id': (2, 1), 'condition': (1, 2), 'place_id': (2, 1), 'tags': (2, 1)}
    for copy_id in copies:
        r = row(db, 'copy', copy_id)
        assert (r['storage_id'], r['condition'], r['place_id']) == (world.shelf, 'used', world.shop) and world.tag in flags(db, 'copy', copy_id)
    assert db.execute('SELECT count(*) FROM main.event WHERE id>?', (result['event_id'] - 1,)).fetchone()[0] == 1
    undo.undo_event(db, result['event_id'], via='cli')
    assert table_digest(db) == before


def test_replace_swaps_only_flags_of_that_kind_and_remove_leaves_the_others(coll, world):
    db = coll.db
    other = coll.flag('vintage', 'tag')
    collection.bulk_update(db, 'copy', [world.copy_a], {'tags': {'mode': 'replace', 'ids': [other]}})
    assert flags(db, 'copy', world.copy_a) == {other, world.checked}                 # the status stays
    collection.bulk_update(db, 'copy', [world.copy_a, world.copy_b], {'statuses': {'mode': 'add', 'ids': [world.box]}})
    assert world.box in flags(db, 'copy', world.copy_b)
    collection.bulk_update(db, 'copy', [world.copy_a, world.copy_b], {'statuses': {'mode': 'remove', 'ids': [world.box]}})
    assert flags(db, 'copy', world.copy_a) == {other, world.checked} and flags(db, 'copy', world.copy_b) == set()


def test_a_status_by_its_system_name_is_made_when_missing(coll, world):
    db = coll.db
    db.execute("UPDATE main.flag SET name='Box (old)' WHERE id=?", (world.box,))
    collection.bulk_update(db, 'copy', [world.copy_c], {'statuses': {'mode': 'add', 'ids': ['system:Box present']}})
    made = db.execute("SELECT id FROM main.flag WHERE name='Box present' AND system=1").fetchone()[0]
    assert made in flags(db, 'copy', world.copy_c)


def test_completeness_on_many_copies_becomes_their_own_and_takes_off_checked_on_rebrickable(coll, world):
    db = coll.db
    db.execute("UPDATE main.copy SET checked_by='rebrickable' WHERE id IN (?, ?)", (world.copy_a, world.copy_c))
    result = collection.bulk_update(db, 'copy', [world.copy_a, world.copy_b, world.copy_c], {'completeness': 'complete'})
    assert by_field(result) == {'completeness': (2, 1)}
    a, b, c = (row(db, 'copy', i) for i in (world.copy_a, world.copy_b, world.copy_c))
    assert (a['completeness'], a['completeness_source'], a['checked_by']) == ('complete', 'manual', None)
    assert (b['completeness'], b['completeness_source']) == ('complete', 'manual')
    assert c['checked_by'] == 'rebrickable'                                           # already complete: nothing changed, the label stays
    undo.undo_event(db, result['event_id'], via='cli')
    assert row(db, 'copy', world.copy_a)['checked_by'] == 'rebrickable'


def test_removing_set_is_checked_takes_off_checked_on_rebrickable(coll, world):
    db = coll.db
    db.execute("UPDATE main.copy SET checked_by='rebrickable' WHERE id=?", (world.copy_a,))
    collection.bulk_update(db, 'copy', [world.copy_a], {'statuses': {'mode': 'remove', 'ids': [world.checked]}})
    assert row(db, 'copy', world.copy_a)['checked_by'] is None


def test_nothing_to_change_writes_nothing(coll, world):
    db = coll.db
    last = db.execute('SELECT max(id) FROM main.event').fetchone()[0]
    result = collection.bulk_update(db, 'copy', [world.copy_a], {'storage_id': world.shelf, 'tags': {'mode': 'add', 'ids': [world.tag]}})
    assert result['event_id'] is None and result['changed'] == 0 and by_field(result) == {'storage_id': (0, 1), 'tags': (0, 1)}
    assert db.execute('SELECT max(id) FROM main.event').fetchone()[0] == last


def test_loose_stock_takes_storage_condition_and_tags_and_undo_restores_a_merge(coll, world):
    db = coll.db
    before = table_digest(db)
    result = collection.bulk_update(db, 'stock', [world.stock_brick_new, world.stock_plate],
                                    {'condition': 'used', 'tags': {'mode': 'add', 'ids': [world.tag]}})
    assert by_field(result) == {'condition': (2, 0), 'tags': (2, 0)}
    undo.undo_event(db, result['event_id'], via='cli')
    assert table_digest(db) == before


def test_archive_many_is_one_undo(coll, world):
    db = coll.db
    before = table_digest(db)
    result = collection.bulk_update(db, 'copy', [world.copy_b, world.copy_c], {'archive': True})
    assert all(row(db, 'copy', i)['archived_at'] for i in (world.copy_b, world.copy_c))
    undo.undo_event(db, result['event_id'], via='cli')
    assert table_digest(db) == before


@pytest.mark.parametrize('ids, changes, message', [
    (None, {'condition': 'new'}, 'Choose collection instances'),
    ('dup', {'condition': 'new'}, 'Choose collection instances'),
    ('a', {}, 'Choose a change to save'),
    ('a', {'note': 'x'}, 'not edited in bulk: note'),
    ('a', {'archive': True, 'condition': 'new'}, 'Archive on its own'),
    ('a', {'completeness': 'half'}, 'Choose completeness'),
    ('a', {'tags': {'mode': 'merge', 'ids': []}}, 'Choose add, remove or replace'),
    ('a', {'tags': {'mode': 'add', 'ids': []}}, 'Choose the tags to add'),
    ('a', {'tags': {'mode': 'add', 'ids': ['nope']}}, 'Unknown tag'),
    ('a', {'condition': 'mint'}, 'Choose a condition'),
])
def test_a_bad_bulk_edit_is_refused_and_writes_nothing(coll, world, ids, changes, message):
    db = coll.db
    ids = {'a': [world.copy_a], 'dup': [world.copy_a, world.copy_a], None: []}[ids]
    before = table_digest(db)
    with pytest.raises(ValueError, match=message):
        collection.bulk_update(db, 'copy', ids, changes)
    assert table_digest(db) == before


def test_more_than_500_is_refused_with_the_cap_in_words(coll, world):
    with pytest.raises(ValueError, match='500 is the most one edit changes'):
        collection.bulk_update(coll.db, 'copy', [str(n) for n in range(501)], {'condition': 'new'})


def test_completeness_is_for_copies_only(coll, world):
    with pytest.raises(ValueError, match='not edited in bulk: completeness'):
        collection.bulk_update(coll.db, 'stock', [world.stock_plate], {'completeness': 'complete'})


def test_one_copy_save_is_unchanged_by_the_refactor(coll, world):
    db = coll.db
    event = collection.save(db, 'copy', [world.copy_b], {'note': 'Bulk'})
    assert row(db, 'copy', world.copy_b)['note'] == 'Bulk'
    payload = json.loads(db.execute('SELECT new_value FROM main.event WHERE id=?', (event,)).fetchone()[0])
    assert [p['table'] for p in payload] == ['copy']


def test_stock_that_merges_into_another_row_with_a_tag_is_undone_whole(coll, world):
    db = coll.db
    target = coll.add_stock('part', world.brick, colour=world.red, quantity=4, condition='used', storage=world.shelf)
    before = table_digest(db)
    result = collection.bulk_update(db, 'stock', [world.stock_brick_new], {'condition': 'used', 'storage_id': world.shelf,
                                                                          'tags': {'mode': 'add', 'ids': [world.tag]}})
    assert row(db, 'stock', target)['quantity'] == 6 and row(db, 'stock', world.stock_brick_new)['archived_at']
    undo.undo_event(db, result['event_id'], via='cli')
    assert table_digest(db) == before
