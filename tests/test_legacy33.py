"""The frozen 3.3 inputs equal what `brickwork.core.connect` makes today.

TEMPORARY: this test imports `brickwork.core`, so it is deleted together with `core/connect.py` and `core/schema.sql` in M.8a
(issue #110). Until then it proves `tests/legacy33` is the same format; after that, `schema-3.3.sql` is the only definition."""
from contextlib import closing
import shutil
import sqlite3

import pytest

from brickwork.core.connect import connect as connect_core
from tests.legacy33 import FIXTURES, create_33
from tests.test_store4_migrate import REGRESSION


def master(path):
    """Every schema object (type, name, table, sql) except SQLite's own and the FTS shadow tables; ANALYZE output is not DDL."""
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
                          " AND name NOT GLOB 'search_index_*' ORDER BY type, name").fetchall()
        seeds = {t: db.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                 for t in ('sources', 'source_freshness', 'schema_meta', 'wishlists')}
    seeds['wishlists'] = [r[:5] + r[6:] for r in seeds['wishlists']]            # created_at is the clock at creation
    return rows, seeds


def test_a_fresh_core_file_and_create_33_have_the_same_schema(tmp_path):
    connect_core(tmp_path / 'core.db').close()
    create_33(tmp_path / 'frozen.db').close()
    core, frozen = master(tmp_path / 'core.db'), master(tmp_path / 'frozen.db')
    assert len(core[0]) > 50
    assert frozen[0] == core[0]
    assert frozen[1] == core[1]


def test_create_33_refuses_an_existing_file(tmp_path):
    (tmp_path / 'x.db').write_bytes(b'')
    with pytest.raises(FileExistsError):
        create_33(tmp_path / 'x.db')


@pytest.mark.parametrize('fixture', REGRESSION, ids=lambda p: p.name)
def test_each_frozen_fixture_is_what_the_core_upgrade_on_open_makes(fixture, tmp_path):
    shutil.copy(fixture, tmp_path / 'live.db')
    connect_core(tmp_path / 'live.db').close()
    assert master(FIXTURES / fixture.name)[0] == master(tmp_path / 'live.db')[0]
