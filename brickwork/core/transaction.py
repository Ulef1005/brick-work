"""Composable core transactions, including rollback of newly installed files."""
from contextlib import contextmanager
from contextvars import ContextVar
import sqlite3

_SCOPES = ContextVar('core_transaction_scopes', default=())


def on_rollback(db, callback):
    for connection, callbacks in reversed(_SCOPES.get()):
        if connection is db:
            callbacks.append(callback)
            return
    raise RuntimeError('Rollback callback needs a managed transaction')


@contextmanager
def transaction(db):
    callbacks=[]
    parents=_SCOPES.get()
    token=_SCOPES.set((*parents,(db,callbacks)))
    try:
        if db.in_transaction:
            db.execute('SAVEPOINT core_write')
            try:
                yield
            except BaseException:
                db.execute('ROLLBACK TO core_write')
                db.execute('RELEASE core_write')
                raise
            else:
                db.execute('RELEASE core_write')
        else:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield
    except BaseException:
        for callback in reversed(callbacks): callback()
        raise
    else:
        for connection, outer_callbacks in reversed(parents):
            if connection is db:
                outer_callbacks.extend(callbacks)
                break
    finally:
        _SCOPES.reset(token)


def schema(db, text):
    """Execute additive DDL without sqlite3.executescript's implicit COMMIT."""
    statement = ''
    for line in text.splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ''
    if statement.strip(): db.execute(statement)
