"""The frozen 3.3 inputs of the migration tests (`tests/legacy33`).

M.8a deleted `core/connect.py`, `core/schema.sql` and the 3.2 -> 3.3 upgrade, so there is no longer a second definition to compare
with: `schema-3.3.sql` and the upgraded fixtures are the definition. These tests only prove the helpers keep working."""
from contextlib import closing
import sqlite3

import pytest

from tests.legacy33 import FIXTURES, create_33, regression_33


def test_create_33_makes_a_3_3_file(tmp_path):
    with closing(create_33(tmp_path / 'frozen.db')) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite\\_%' ESCAPE '\\'").fetchone()[0] > 50
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.3'


def test_create_33_refuses_an_existing_file(tmp_path):
    (tmp_path / 'x.db').write_bytes(b'')
    with pytest.raises(FileExistsError):
        create_33(tmp_path / 'x.db')


@pytest.mark.parametrize('fixture', sorted(FIXTURES.glob('*.db')), ids=lambda p: p.name)
def test_each_frozen_fixture_opens_and_is_3_x(fixture, tmp_path):
    work = regression_33(fixture, tmp_path / 'live.db')
    with closing(sqlite3.connect(work)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0] in ('3.2', '3.3')
