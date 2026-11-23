"""#551 review fixes: kind moves keep synced_from ids and allow undo of same-id re-inserts."""
import uuid

import pytest

from brickwork.core import stock
from brickwork.core.transaction import transaction
from brickwork.store4 import identity, merge, origins
from tests.test_origins import GEAR, pair, store, synced  # noqa: F401


def _gear_id(store):
    return store.execute(
        'SELECT id FROM main.item WHERE born_key=? UNION SELECT id FROM catalogue.item WHERE born_key=?',
        (GEAR, GEAR),
    ).fetchone()[0]


def test_non_set_stock_kind_move_with_synced_from_undoes_without_refusal(store):
    gear = _gear_id(store)
    with transaction(store):
        row = stock.add_loose(store, item_id=gear, quantity=1, condition='new')
        entry = origins.touch(store, 'stock', row['id'], 'brickset', at='2026-11-22T10:00:00.000Z')
    with transaction(store):
        moved = merge.move_kind_in(store, gear, 'book', via='app')
    assert store.execute('SELECT kind FROM stock WHERE id=?', (row['id'],)).fetchone()[0] == 'book'
    assert synced(store) == [('stock', 'brickset', '')]
    with transaction(store):
        merge.undo_kind_move_in(store, moved['event_id'], via='app')
    assert store.execute('SELECT kind FROM stock WHERE id=?', (row['id'],)).fetchone()[0] == 'gear'
    assert store.execute('SELECT id, stock_id, site FROM synced_from').fetchone()[:] == (entry['id'], row['id'], 'brickset')


def test_synced_wish_moved_gear_to_set_undoes_without_refusal(store):
    gear = _gear_id(store)
    wish_id = str(uuid.uuid4())
    stamp = '2026-11-22T10:00:00.000Z'
    with transaction(store):
        if store.execute('SELECT 1 FROM main.item WHERE id=?', (gear,)).fetchone() is None:
            identity.project(store, gear)
        store.execute(
            '''INSERT INTO main.wish(id, wishlist_id, kind, item_id, color_id, quantity, condition,
               max_price, max_price_currency, qty_filled_manual, note, added_at, updated_at, added_via)
               VALUES(?, 'default', 'gear', ?, NULL, 1, 'any', NULL, NULL, NULL, NULL, ?, ?, 'hand')''',
            (wish_id, gear, stamp, stamp),
        )
        entry = origins.touch(store, 'wish', wish_id, 'brickset', at=stamp)
    with transaction(store):
        moved = merge.move_kind_in(store, gear, 'set', via='app')
    assert store.execute('SELECT kind FROM wish WHERE id=?', (wish_id,)).fetchone()[0] == 'set'
    assert ('wish', 'brickset', '') in synced(store)
    with transaction(store):
        merge.undo_kind_move_in(store, moved['event_id'], via='app')
    assert store.execute('SELECT kind FROM wish WHERE id=?', (wish_id,)).fetchone()[0] == 'gear'
    assert store.execute('SELECT id, wish_id, site FROM synced_from WHERE id=?', (entry['id'],)).fetchone()[:] == (
        entry['id'], wish_id, 'brickset')


def test_stock_to_set_keeps_synced_from_id_so_pull_untouch_restores_and_removes_it(store):
    gear = _gear_id(store)
    with transaction(store):
        row = stock.add_loose(store, item_id=gear, quantity=1, condition='new')
        first = origins.touch(store, 'stock', row['id'], 'brickset', at='2026-11-22T10:00:00.000Z', list_key='7', list_name='Shelf')
        second = origins.touch(store, 'stock', row['id'], 'brickset', at='2026-11-22T11:00:00.000Z', list_key='7', list_name='Top shelf')
    assert first['id'] == second['id']
    with transaction(store):
        merge.move_kind_in(store, gear, 'set', via='app')
    (made,) = store.execute('SELECT id FROM copy WHERE item_id=? AND archived_at IS NULL', (gear,)).fetchall()
    assert store.execute('SELECT id, copy_id, stock_id FROM synced_from').fetchone()[:] == (first['id'], made['id'], None)
    with transaction(store):
        assert origins.untouch(store, second) is True
    assert store.execute('SELECT id, copy_id, list_name, synced_at FROM synced_from').fetchone()[:] == (
        first['id'], made['id'], 'Shelf', '2026-11-22T10:00:00.000Z')
    with transaction(store):
        assert origins.untouch(store, first) is True
    assert synced(store) == []


def test_later_sync_on_new_copy_still_refuses_undo_of_kind_move(store):
    gear = _gear_id(store)
    with transaction(store):
        row = stock.add_loose(store, item_id=gear, quantity=1, condition='new')
        entry = origins.touch(store, 'stock', row['id'], 'brickset', at='2026-11-22T10:00:00.000Z')
    with transaction(store):
        moved = merge.move_kind_in(store, gear, 'set', via='app')
    (made,) = store.execute('SELECT id FROM copy WHERE item_id=? AND archived_at IS NULL', (gear,)).fetchall()
    with transaction(store):
        later = origins.touch(store, 'copy', made['id'], 'rebrickable', at='2026-11-22T11:00:00.000Z')
    with pytest.raises(merge.MergeRefused, match='undo that sync first'):
        with transaction(store):
            merge.undo_kind_move_in(store, moved['event_id'], via='app')
    with transaction(store):
        assert origins.untouch(store, later) is True
    with transaction(store):
        merge.undo_kind_move_in(store, moved['event_id'], via='app')
    assert store.execute('SELECT id, stock_id, copy_id, site FROM synced_from').fetchone()[:] == (
        entry['id'], row['id'], None, 'brickset')
