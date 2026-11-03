"""Core review fixes about the part inventory save (M.8e, issue #110): moved out of test_bw_core_fixes.py in M.8d, rewritten on 4.0.

The 3.3 test ran every case twice, once for a web Undo and once for an API Undo that persisted only a `bw_api` event naming the receipt.
That second path is gone: web, CLI and API undo through the one `undo_event` dispatcher and the one predicate (`event_undo`), so a
receipt is undone exactly when a row says so.
"""
import pytest

from brickwork.core import part_inventory, undo
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def one_piece_event(coll, world, batch):
    piece = dict(id='piece-' + batch, candidates=[dict(item_id=world.brick, score=.9)], chosen=dict(item_id=world.brick, color_id=world.red, quantity=2))
    return part_inventory.save(coll.db, [piece], batch=batch, keep_photos=False)


def test_resave_after_undo_adds_and_the_new_receipt_is_live(world, coll):
    db = coll.db
    stock = lambda: db.execute('SELECT coalesce(sum(quantity),0) FROM stock WHERE archived_at IS NULL AND item_id=? AND color_id=?', (world.brick, world.red)).fetchone()[0]
    base = stock()
    first = one_piece_event(coll, world, 'b')
    assert stock() == base + 2
    part_inventory.undo(db, first)
    assert stock() == base and undo.is_undone(db, first)
    second = one_piece_event(coll, world, 'b')
    assert second != first and stock() == base + 2
    assert not undo.is_undone(db, second), 'the newer receipt is not read as undone by the older undo event'
    assert one_piece_event(coll, world, 'b') == second, 'replay of the live save'
    assert stock() == base + 2


def test_a_second_undo_of_the_same_receipt_does_nothing(world, coll):
    first = one_piece_event(coll, world, 'c')
    assert part_inventory.undo(coll.db, first)['already_undone'] is False
    assert part_inventory.undo(coll.db, first)['already_undone'] is True
    with pytest.raises(ValueError, match='batch receipt'):
        part_inventory.undo(coll.db, 1)
