"""Connections to the new store, never to either legacy database."""
import os
from pathlib import Path
import sqlite3
import time
from threading import RLock

_INITIALIZE_LOCK = RLock()

# Paths whose upgrade could not be written -> (monotonic time, mtime_ns) of the failed attempt.
# A failing upgrade is not retried per request: only after RETRY_SECONDS or when the file changes.
_FAILED = {}
RETRY_SECONDS = 300


def connect(path='brickwork.db', *, read_only=False):
    from . import upgrade
    path = Path(path)
    needs_lock = not path.exists()
    if not needs_lock:
        # Probe without the process lock; ordinary current-store requests never take it.
        probe = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            has_schema = probe.execute("SELECT 1 FROM sqlite_master WHERE name='schema_meta'").fetchone()
            needs_lock = not has_schema or upgrade.pending(probe, writable=os.access(path, os.W_OK))
        finally:
            probe.close()
    if needs_lock:
        with _INITIALIZE_LOCK:
            # _connect checks file existence and pending upgrades again under the lock.
            return _connect(path, read_only=read_only)
    # The probe above already found nothing pending: do not scan for it a second time.
    return _connect(path, read_only=read_only, probed=True)


def _connect(path, *, read_only=False, probed=False):
    """Open a WAL connection with enforced foreign keys; initialize new files."""
    path = Path(path)
    new = not path.exists()
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) if read_only else sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        if read_only:
            db.execute('PRAGMA query_only=ON')
        else:
            db.execute('PRAGMA journal_mode=WAL')
        if new and not read_only:
            db.executescript(Path(__file__).with_name('schema.sql').read_text())
        elif not new:
            from . import upgrade
            if not probed and upgrade.pending(db, writable=os.access(path, os.W_OK)):
                if read_only:
                    # A read-only handle cannot upgrade: do it once on a short writable handle, then reopen.
                    # If that is impossible (locked or unwritable file) readers still work without the column.
                    key, mtime = str(path.resolve()), path.stat().st_mtime_ns
                    failed = _FAILED.get(key)
                    if failed and failed[1] == mtime and time.monotonic() - failed[0] < RETRY_SECONDS:
                        return db
                    try:
                        upgrade.upgrade(path)
                    except sqlite3.Error:
                        _FAILED[key] = (time.monotonic(), path.stat().st_mtime_ns)
                        return db
                    _FAILED.pop(key, None)
                    db.close()
                    return connect(path, read_only=True)
                upgrade.upgrade_connection(db)
        if new and not read_only:
            from . import upgrade
            upgrade.upgrade_connection(db)
        return db
    except BaseException:
        db.close()
        raise
