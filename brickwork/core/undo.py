"""Undo on the 4.0 store: the dispatcher and the two SQL predicates (M.8a, issue #110; design 2.4 invariant 11, 5).

4.0's `event` log starts fresh and is append-only; "undone" is a row in `event_undo(event_id, undo_event_id)` that the undoing
operation writes in the same transaction as its own event. There is no 3.3 undo JSON to read: a receipt is an event whose
`(entity_kind, field)` has a registered undoer, and the undoer reads the receipt in the event's `new_value`.

Pieces register the undoers of what they write (`register`), at import time, as they are ported; M.8a registers the one store4
already owns (a part list switch). `undone_sql` / `undoable_sql` are the predicates event pages and histories embed.
"""
from dataclasses import dataclass
import re

from ..store4.errors import Store4Error
from . import errors
from .transaction import transaction

_NAME = re.compile(r'[a-z0-9_]+')


@dataclass(frozen=True)
class Undoer:
    handler: object            # handler(db, event_row, via, actor) -> dict(event_id=<undo event id>, ...), inside the open transaction
    admin: bool = False        # undoing needs the admin scope, as making the change did


REGISTRY = {}


def register(entity_kind, field, handler, *, admin=False):
    """Make events `(entity_kind, field)` undoable by `handler`. Registering the same pair twice is a programming error."""
    if not (_NAME.fullmatch(entity_kind) and _NAME.fullmatch(field)):
        raise ValueError('an undoable event is named by lowercase words')
    if (entity_kind, field) in REGISTRY:
        raise ValueError(f'{entity_kind}:{field} already has an undoer')
    REGISTRY[(entity_kind, field)] = Undoer(handler, admin)


def undone_sql(alias='e'):
    """Predicate: the event has been undone (a row in `event_undo`). Uses the primary key of event_undo."""
    return f'EXISTS(SELECT 1 FROM event_undo u WHERE u.event_id={alias}.id)'


def undoable_sql(alias='e'):
    """Predicate: the event has a registered undoer. It does not say whether it was undone already: combine with `undone_sql`."""
    names = [f"{k}:{f}" for k, f in sorted(REGISTRY)]
    if not names:
        return '0'
    return f"({alias}.entity_kind||':'||{alias}.field IN ({','.join(repr(n) for n in names)}))"


def is_undone(db, event_id):
    return db.execute('SELECT 1 FROM event_undo WHERE event_id=?', (event_id,)).fetchone() is not None


def undo_event(db, event_id, *, via='app', actor=None, identity=None):
    """Undo one event by its registered undoer, in one transaction (a savepoint inside the caller's).

    Returns `dict(undone_event_id, already_undone, undo_event_id)`. Unknown event -> NotFound; no undoer -> NotUndoable; an undoer
    that refuses (the rows changed since) -> UndoBlocked with its message. `identity` (an API token's) is checked for the admin
    scope only when the undoer needs it; the web passes none."""
    with transaction(db):
        event = db.execute('SELECT * FROM event WHERE id=?', (event_id,)).fetchone()
        if event is None:
            raise errors.NotFound()
        undoer = REGISTRY.get((event['entity_kind'], event['field']))
        if is_undone(db, event_id):
            return dict(undone_event_id=event_id, already_undone=True, undo_event_id=None)
        if undoer is None:
            raise errors.NotUndoable()
        if undoer.admin and identity is not None:
            from . import tokens
            if not tokens.permits(identity, 'admin'):
                raise errors.Forbidden()
        try:
            result = undoer.handler(db, event, via, actor)
        except errors.BrickWorkError:
            raise
        except (Store4Error, ValueError) as exc:
            raise errors.UndoBlocked(str(exc)) from None
    return dict(undone_event_id=event_id, already_undone=False, undo_event_id=(result or {}).get('event_id'))


def _undo_switch(db, event, via, actor):
    from ..store4 import copies
    return copies.undo_switch_in(db, event['id'], via=via, actor=actor)


register('copy', 'part_list_switch', _undo_switch)


# Each module below registers the undoers of what it writes (they import this module first when they are the entry).
from . import add, checker, collection  # noqa: E402,F401
