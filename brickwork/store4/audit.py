"""Shared by activation and reconcile: one transaction, and the append-only event log."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import uuid

from .connect import has_catalogue, now
from .errors import CatalogueError, Store4Error


def need_catalogue(db, what):
    if not has_catalogue(db):
        raise CatalogueError(f'{what} needs the catalogue, which is not attached')


@contextmanager
def transaction(db, what):
    """One write transaction, taken up front; commit on success, roll back on any failure. Not nestable: the operation
    owns its transaction, as the builder owns its file."""
    if db.in_transaction:
        raise Store4Error(f'{what} runs in its own transaction; commit or roll back the open one first')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()                                         # inside the protected block: a failing commit rolls back too
    except BaseException:
        db.rollback()
        raise


def value_text(v):
    """How an event stores a value: None as NULL, a string as it is, a dict or list as sorted JSON, anything else as str(). The one
    rule for every writer of `event` (store4's `Events` and the app's `core.admin.audit`), so readers never guess the encoding."""
    return v if v is None or isinstance(v, str) else json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else str(v)


# The operation the running code belongs to (a web request, an API write, a worker pass); `core.admin` sets it and re-exports it, store4 only
# reads it, so every event a writer here emits joins the caller's operation without any signature carrying the key.
OPERATION_KEY = ContextVar('brickwork_operation_key', default=None)


class Events:
    """Writes events for one run; every event of the run shares the operation key: the caller's `operation_key`, else the
    ambient `OPERATION_KEY` (an API write names its events by its own key), else a fresh one."""

    def __init__(self, db, via, actor, operation_key=None):
        self.db, self.via, self.actor = db, via, actor
        self.operation_key = operation_key or OPERATION_KEY.get() or uuid.uuid4().hex
        self.count = 0

    def write(self, entity_kind, entity_id, field, old=None, new=None):
        text = value_text
        self.db.execute('''INSERT INTO event(at, via, actor, entity_kind, entity_id, field, old_value, new_value, operation_key)
                           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (now(), self.via, self.actor, entity_kind, None if entity_id is None else str(entity_id), field,
                         text(old), text(new), self.operation_key))
        self.count += 1
