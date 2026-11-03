"""A part list switch (store4 owns it) is undone through the app's dispatcher, `core.undo` (M.8a, issue #110)."""
import pytest

from brickwork.core import errors, undo
from tests.test_store4_copies import q
from tests.test_store4_switch import V1, V2, add, db, key, live, switch   # noqa: F401  (fixtures and helpers)


def test_the_dispatcher_undoes_a_switch_once(db, key):
    cid = add(db, V1)['copy']['id']
    before = live(db, cid)
    event = switch(db, cid, V2)['event_id']
    assert live(db, cid) != before
    assert q(db, f'SELECT {undo.undoable_sql()}, {undo.undone_sql()} FROM event e WHERE e.id=?', event) == [(1, 0)]
    result = undo.undo_event(db, event, via='cli', actor='t')
    assert result['already_undone'] is False and result['undone_event_id'] == event
    assert live(db, cid) == before
    assert q(db, f'SELECT {undo.undone_sql()} FROM event e WHERE e.id=?', event) == [(1,)]
    assert q(db, 'SELECT event_id, undo_event_id FROM event_undo') == [(event, result['undo_event_id'])]
    assert undo.undo_event(db, event) == {'undone_event_id': event, 'already_undone': True, 'undo_event_id': None}


def test_the_dispatcher_blocks_an_undo_after_a_later_change(db, key):
    cid = add(db, V1)['copy']['id']
    event = switch(db, cid, V2)['event_id']
    db.execute('UPDATE copy_part SET missing=1 WHERE copy_id=? AND retired_at IS NULL AND quantity>0', (cid,))
    db.commit()
    with pytest.raises(errors.UndoBlocked, match='changed after the switch'):
        undo.undo_event(db, event)
    assert q(db, 'SELECT count(*) FROM event_undo') == [(0,)]
