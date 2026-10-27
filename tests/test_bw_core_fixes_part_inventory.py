"""Core review fixes about the part inventory save (M.8e): moved out of test_bw_core_fixes.py in M.8d; still the 3.3 text."""
from contextlib import closing
import json
import os

import pytest

from brickwork.core import add, api_reads, checker, collection, completeness, errors, upgrade, upgrade_api, workbench
from brickwork.core.connect import connect


@pytest.fixture
def db(tmp_path):
    with closing(connect(tmp_path / 'bw.db')) as handle:
        yield handle


def one_piece_event(db, batch, monkeypatch):
    from brickwork.core import part_inventory
    monkeypatch.setattr(add, 'lookup', lambda handle, kind, number: dict(item_type=kind, item_no=number, name='Part'))
    with db:
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P','pp','Part')")
        db.execute("INSERT OR IGNORE INTO colors VALUES(4,'Red','Solid','FF0000')")
    candidates = [dict(item_type='P', item_no='pp', name='Part', score=.9)]
    piece = dict(id='piece-' + batch, candidates=candidates, photo='', chosen=dict(item_type='P', item_no='pp', color_id=4, quantity=2))
    return part_inventory.save(db, [piece], batch=batch, keep_photos=False)


@pytest.mark.parametrize('how', ['web', 'api'])
def test_part_inventory_resave_after_either_undo_adds_and_new_receipt_is_live(db, how, monkeypatch):
    from brickwork.core import part_inventory, admin
    stock = lambda: db.execute("SELECT coalesce(sum(quantity),0) FROM loose_stock WHERE archived_at IS NULL AND item_no='pp'").fetchone()[0]
    first = one_piece_event(db, 'b', monkeypatch)
    assert stock() == 2
    if how == 'web':
        part_inventory.undo(db, first)
    else:
        # An API Undo persists only a bw_api event naming the receipt (the same-entity undo is bundled away).
        with db:
            pass
        from brickwork.core.audit_bundle import capture
        with capture():
            part_inventory.undo(db, first)
        with db:
            admin.audit(db, 'bw_api', 'undo', new=dict(undone_event_id=first))
        assert not db.execute("SELECT 1 FROM events WHERE entity='part_inventory:b' AND field='undo'").fetchone()
    assert stock() == 0
    second = one_piece_event(db, 'b', monkeypatch)
    assert second != first and stock() == 2
    live = db.execute(f'SELECT {api_reads.undone_sql()} FROM events e WHERE e.id=?', (second,)).fetchone()[0]
    assert live == 0  # the newer receipt is not read as undone by the older undo event
    assert db.execute(f'SELECT {api_reads.undone_sql()} FROM events e WHERE e.id=?', (first,)).fetchone()[0] == 1
    assert one_piece_event(db, 'b', monkeypatch) == second  # replay of the live save


def test_part_inventory_resave_after_api_only_undo_event(db, monkeypatch):
    """Only the bw_api event exists (no same-entity undo event): save must still add again."""
    from brickwork.core import admin
    from brickwork.core import part_inventory
    from brickwork.core.audit_bundle import capture
    first = one_piece_event(db, 'c', monkeypatch)
    with capture():
        part_inventory.undo(db, first)
    with db:
        admin.audit(db, 'bw_api', 'undo', new=dict(undone_event_id=first))
    assert one_piece_event(db, 'c', monkeypatch) != first
