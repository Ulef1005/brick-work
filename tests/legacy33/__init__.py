"""The 3.3 collection format, frozen for the 4.0 migration tests (M.8 preparation, issue #110).

M.8 deletes `brickwork/core` (`connect.py`, `schema.sql`, `upgrade.py`); the migration tests still need 3.3 inputs, so they
build them here instead of through `brickwork.core.connect`:

- `create_33(path)`: a fresh, empty 3.3 file, `schema-3.3.sql` (the DDL and seed rows a fresh `core.connect` produced), returned as
  an open connection configured like `core.connect`'s (WAL, foreign keys on, `sqlite3.Row`).
- `regression_33(fixture, dest)`: a regression fixture (`tests/regression/fixtures/v3.*.db`, which stay as they are) in its 3.3
  form. `core.connect` upgrades an older file on open (3.2 -> 3.3, the additive column and wishlist steps); `fixtures/` holds each
  fixture as that upgrade left it, so no test needs the upgrade code."""
from pathlib import Path
import shutil
import sqlite3

HERE = Path(__file__).parent
SCHEMA = HERE / 'schema-3.3.sql'
FIXTURES = HERE / 'fixtures'


def create_33(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA.read_text())
        return db
    except BaseException:
        db.close()
        raise


def regression_33(fixture, dest):
    """Copy the 3.3 form of regression fixture `fixture` (a path or a file name) to `dest`; returns `dest`."""
    shutil.copy(FIXTURES / Path(fixture).name, dest)
    return dest
