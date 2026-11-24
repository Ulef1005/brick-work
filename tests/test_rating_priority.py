"""#690 schema 4.9: copy.rating and wish.priority. Invented data."""
from contextlib import closing
import sqlite3

import pytest

from brickwork.core import collection, own_export, own_import
from brickwork.core.connect import connect
from tests.app4 import app4, coll, make_pair, pair, world  # noqa: F401


def test_the_columns_start_empty_and_the_checks_hold(coll, world):
    assert coll.db.execute('SELECT rating FROM main.copy WHERE id=?', (world.copy_a,)).fetchone()[0] is None
    assert coll.db.execute('SELECT priority FROM main.wish WHERE id=?', (world.wish_set,)).fetchone()[0] is None
    for bad in (0, 6):
        with pytest.raises(sqlite3.IntegrityError):
            coll.db.execute('UPDATE main.copy SET rating=? WHERE id=?', (bad, world.copy_a))
        with pytest.raises(sqlite3.IntegrityError):
            coll.db.execute('UPDATE main.wish SET priority=? WHERE id=?', (bad, world.wish_set))


def test_a_rating_and_a_priority_save_clear_and_undo(coll, world):
    event = collection.save(coll.db, 'copy', [world.copy_a], dict(rating=4))
    assert coll.db.execute('SELECT rating FROM main.copy WHERE id=?', (world.copy_a,)).fetchone()[0] == 4
    collection.undo(coll.db, event)
    assert coll.db.execute('SELECT rating FROM main.copy WHERE id=?', (world.copy_a,)).fetchone()[0] is None
    collection.save(coll.db, 'wish', [world.wish_set], dict(priority=1))
    assert coll.db.execute('SELECT priority FROM main.wish WHERE id=?', (world.wish_set,)).fetchone()[0] == 1
    collection.save(coll.db, 'wish', [world.wish_set], dict(priority=''))
    assert coll.db.execute('SELECT priority FROM main.wish WHERE id=?', (world.wish_set,)).fetchone()[0] is None


@pytest.mark.parametrize('value', [0, 6, True, 2.5, 'four'])
def test_a_value_outside_one_to_five_is_refused(coll, world, value):
    with pytest.raises(ValueError):
        collection.save(coll.db, 'copy', [world.copy_a], dict(rating=value))
    with pytest.raises(ValueError):
        collection.save(coll.db, 'wish', [world.wish_set], dict(priority=value))


def test_the_own_file_round_trips_both_values(coll, world, tmp_path):
    collection.save(coll.db, 'copy', [world.copy_a], dict(rating=5))
    collection.save(coll.db, 'wish', [world.wish_set], dict(priority=2))
    content = own_export.build(coll.db)['content']
    empty = tmp_path / 'empty'
    empty.mkdir()
    with closing(connect(make_pair(empty, rich=True))) as db:
        planned = own_import.plan(db, content)
        own_import.apply(db, planned['id'], via='cli', actor='test')
        assert sorted(r[0] for r in db.execute('SELECT rating FROM main.copy WHERE rating IS NOT NULL')) == [5]
        assert sorted(r[0] for r in db.execute('SELECT priority FROM main.wish WHERE priority IS NOT NULL')) == [2]


def test_the_import_plan_refuses_a_rating_out_of_range():
    assert own_import._value_problem('copy', {'rating': 6}) == 'Rating must be 1 to 5'
    assert own_import._value_problem('wish', {'kind': 'set', 'quantity': 1, 'priority': 0}) == 'Priority must be 1 to 5'
    assert own_import._value_problem('copy', {'rating': 3}) is None


def test_a_rating_counts_as_a_change_for_the_undo_of_an_add_and_an_old_receipt_still_reads(coll, world):
    from brickwork.core import add
    one = coll.add_copy('1000-1')
    snapshot = dict(coll.db.execute('SELECT * FROM main.copy WHERE id=?', (one,)).fetchone())
    old = {k: v for k, v in snapshot.items() if k != 'rating'}                    # a receipt written before 4.9
    assert add._copy_untouched(coll.db, one, old)
    coll.db.execute('UPDATE main.copy SET rating=3 WHERE id=?', (one,))
    assert not add._copy_untouched(coll.db, one, snapshot)
    assert not add._copy_untouched(coll.db, one, old)

