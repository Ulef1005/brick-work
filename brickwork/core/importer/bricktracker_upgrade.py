"""Upgrade a copy of a BrickTracker database to the newest upstream schema this importer knows.

The user's file is opened read-only and copied with SQLite's backup API (consistent even with a
WAL); the vendored upstream migrations then run on the copy only, exactly as upstream applies them:
the SQL file (rendered with the Python step's context where upstream has one), then
`PRAGMA user_version = N`.
"""
from contextlib import closing
from importlib import import_module
from pathlib import Path
import sqlite3

MIGRATIONS = Path(__file__).with_name('bricktracker_migrations')
NEWEST = max(int(p.stem) for p in (MIGRATIONS / 'sql').glob('[0-9][0-9][0-9][0-9].sql'))


class _Upstream:
    """The slice of upstream's BrickSQL that its migration steps use: a cursor with named rows."""

    def __init__(self, db):
        db.row_factory = sqlite3.Row
        self.cursor = db.cursor()


def version(db):
    return db.execute('PRAGMA user_version').fetchone()[0]


def _tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def check(db):
    """The upstream schema version of an open database, or ValueError when it is not one this importer can read."""
    found = version(db)
    tables = _tables(db)
    if found > NEWEST:
        raise ValueError(f'This BrickTracker database is newer (schema {found}) than this import knows (schema {NEWEST}). '
                         'Update Brick Work, or export from BrickTracker in an older version.')
    if not tables & {'bricktracker_sets', 'sets', 'wishlist'}:
        raise ValueError('This is not a BrickTracker database: it has no sets or wishlist table.')
    return found


def _render(text, context):
    if '{%' not in text and '{{' not in text:
        return text
    from jinja2 import Template
    return Template(text).render(**context)


def upgrade(db):
    """Apply the vendored migrations after the database's version, in order. Returns (from, to)."""
    return apply(db, check(db))


def apply(db, start, stop=NEWEST):
    """Run migrations start+1..stop on `db` without checking it (an empty file gives a fresh upstream install)."""
    for number in range(start + 1, stop + 1):
        name = f'{number:04d}'
        context = {}
        step = MIGRATIONS / 'py' / f'm{name}.py'
        if step.is_file():
            module = import_module(f'{__package__}.bricktracker_migrations.py.m{name}')
            context = getattr(module, f'migration_{name}')(_Upstream(db)) or {}
            db.row_factory = None
        db.executescript(_render((MIGRATIONS / 'sql' / f'{name}.sql').read_text(), context))
        db.execute(f'PRAGMA user_version = {number}')
        db.commit()
    return start, stop


def upgraded_copy(source, target):
    """Copy `source` (never written) to `target` and upgrade the copy. Returns (from, to)."""
    source, target = Path(source), Path(target)
    if not source.is_file():
        raise ValueError('BrickTracker database not found')
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src:
        try:
            check(src)
        except sqlite3.DatabaseError:
            raise ValueError('This file is not a SQLite database') from None
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    with closing(sqlite3.connect(target)) as db:
        return upgrade(db)
