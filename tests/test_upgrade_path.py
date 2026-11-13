"""The upgrade path of an install that started on 0.5.x (issue #80): a 3.3 collection through `migrate4`, then the in-place steps 4.0 to 4.1
(0.7.0), 4.1 to 4.2 (0.9.0) and 4.2 to 4.3, with the rows counted at every stage and the result held to the app's own `brickwork check`.

One gap, said plainly: `migrate4` of this tree writes the current schema (4.3), not the 4.0 it wrote in 0.6.0, so no real 4.0 file can be made
here. The 4.0 stage is the migrated file taken back to 4.0 shape: the tables of the 4.0 schema (today's `brickwork.sql` without the lines the 4.1
and 4.2 steps add and the 4.3 CHECK change reversed, as `test_store4_upgrade` does) filled with every row of the migrated file. The steps themselves are the real ones. The 0.5.0
shape of the 3.3 file is `tests/legacy33` (the real 3.3 schema) filled by `store4_migrate_fixtures`. 0.7.0 to 0.8.1 changed no schema."""
from contextlib import closing
import shutil
import sqlite3

import pytest

from brickwork.core.admin import check_all, check_ok
from brickwork.store4 import connect as connect_module
from brickwork.store4.connect import SCHEMA_VERSION, connect
from brickwork.store4.errors import UpgradeFailed
from brickwork.store4.migrate_run import run
from tests.store4_migrate_fixtures import build_33
from tests.store4_mint_fixtures import FIXTURES, build_catalogue
from tests.test_store4_upgrade import old_sql

STEPS = {'4.1': ('wish', ('max_price_boxed', 'max_price_boxed_currency')),
         '4.2': ('order_line', ('unplaced_reason',))}


@pytest.fixture
def catalogue(tmp_path):
    (tmp_path / 'cat').mkdir()
    return build_catalogue(tmp_path / 'cat')


@pytest.fixture
def mappings(tmp_path):
    shutil.copytree(FIXTURES / 'mappings', tmp_path / 'maps')
    return tmp_path / 'maps'


def counts(db):
    """Rows per table, for every table of the file but `meta` (the schema's own tables, not SQLite's)."""
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: db.execute(f'SELECT COUNT(*) FROM main."{name}"').fetchone()[0] for name in names if name != 'meta'}   # each step adds a meta row


def version(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]


def columns(path, table):
    with closing(sqlite3.connect(path)) as db:
        return [r[1] for r in db.execute(f'PRAGMA main.table_xinfo({table})')]


def take_back_to_40(migrated, out):
    """The 4.0 shape of a migrated file: the 4.0 tables with all its rows, the columns of the later steps left out."""
    with closing(sqlite3.connect(out)) as db:
        db.executescript(old_sql(drop_41=True))
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('ATTACH ? AS src', (f'file:{migrated}?mode=ro',))
        for (name,) in db.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            db.execute(f'DELETE FROM main."{name}"')                  # the schema's own seed rows: the migrated file brings its copies
            shared = [r[1] for r in db.execute(f'PRAGMA main.table_xinfo({name})')
                      if r[1] in {s[1] for s in db.execute(f'PRAGMA src.table_xinfo({name})')} and not r[6]]   # r[6]: hidden/generated columns
            cols = ', '.join(f'"{c}"' for c in shared)
            db.execute(f'INSERT INTO main."{name}"({cols}) SELECT {cols} FROM src."{name}"')
        db.execute("UPDATE main.meta SET value='4.0' WHERE key='schema_version'")
        db.commit()
        db.execute('DETACH src')
        db.execute('PRAGMA journal_mode=WAL')
    return out


def test_a_050_collection_reaches_the_current_schema_step_by_step(tmp_path, catalogue, mappings, monkeypatch):
    # 0.5.0 (schema 3.3) to 4.x: migrate4 on a copy; the 3.3 file is never changed
    old = tmp_path / 'brickwork-3.3.db'
    build_33(old)
    with closing(sqlite3.connect(old)) as db:
        copies_33, stock_33, wishes_33 = (db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('copies', 'loose_stock', 'wishlist'))
    assert copies_33 and stock_33 and wishes_33
    digest = old.read_bytes()
    result = run(old, catalogue, mappings, tmp_path / 'out' / 'brickwork.db', tmp_path / 'out' / 'report')
    assert result.published and old.read_bytes() == digest

    migrated = result.out
    assert version(migrated) == SCHEMA_VERSION == '4.3'
    with closing(sqlite3.connect(migrated)) as db:
        carried = counts(db)
    assert carried['copy'] == copies_33 and carried['wish'] == wishes_33 and carried['stock'] >= stock_33 > 0
    assert carried['event'] >= 1 and carried['item'] and carried['copy_part']

    # 4.0: the migrated file in the shape 0.6.0 wrote
    (tmp_path / 'data').mkdir()
    live = take_back_to_40(migrated, tmp_path / 'data' / 'brickwork.db')
    assert version(live) == '4.0'
    for _, (table, added) in STEPS.items():
        assert not set(added) & set(columns(live, table))
    with closing(sqlite3.connect(live)) as db:
        at_40 = counts(db)
    assert at_40 == carried                                     # every row came across; only the later columns are missing
    with pytest.raises(UpgradeFailed):                          # a read-only open never upgrades (the app's read-only instance)
        connect(live, catalogue, read_only=True)
    assert version(live) == '4.0'

    # 4.0 to 4.1 (0.7.0): the first step alone
    with monkeypatch.context() as patch:
        patch.setattr(connect_module, 'UPGRADES', {'4.0': connect_module.UPGRADES['4.0']})
        assert connect_module.upgrade(live) == '4.1'
    assert version(live) == '4.1'
    assert set(STEPS['4.1'][1]) <= set(columns(live, 'wish')) and not set(STEPS['4.2'][1]) & set(columns(live, 'order_line'))
    with closing(sqlite3.connect(live)) as db:
        assert counts(db) == carried
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key='upgraded_to_4.1'").fetchone()[0] == 1

    # 4.1 through 4.2 (0.9.0) to 4.3: the first read-write open of the app does the rest
    with closing(connect(live, catalogue)) as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.3'
        assert counts(db) == carried
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key='upgraded_to_4.2'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key='upgraded_to_4.3'").fetchone()[0] == 1
        checked = check_all(db)                                 # what `brickwork check` runs
        assert check_ok(checked), checked
        assert checked['integrity_check'] == ['ok'] and checked['foreign_key_check'] == []
    assert version(live) == '4.3'
    for _, (table, added) in STEPS.items():
        assert set(added) <= set(columns(live, table))

    # the upgraded file has the tables and columns of a fresh 4.3 file, and opening it again changes nothing
    (tmp_path / 'fresh').mkdir()
    with closing(connect(tmp_path / 'fresh' / 'brickwork.db', catalogue)) as fresh, closing(sqlite3.connect(live)) as db:
        for name in counts(db):
            assert set(columns(live, name)) == {r[1] for r in fresh.execute(f'PRAGMA main.table_xinfo({name})')}, name
    with closing(connect(live, catalogue)) as db:
        assert counts(db) == carried
