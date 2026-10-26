"""`test_migrates_to_4` (design 8.11; issue #110, M.8a): every frozen 3.3 store from history goes through the real migration command
(`python -m brickwork.store4 migrate`, i.e. `migrate_run.run`) against the fixture catalogue and must PASS its own independent proof.

This replaces the 3.3 upgrade regression (`test_upgrades`): the app no longer opens or upgrades a 3.x file. The 3.2 fixture only has to be
refused, with the 3.3 file named as the thing to migrate from. A real store can be checked the same way:
BW_REGRESSION_DB=/path/to/brickwork.db (a copy is used; the file is never opened for writing)."""
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3

import pytest

from brickwork.store4 import cli
from brickwork.store4.connect import connect
from brickwork.store4.migrate import MigrationError
from brickwork.store4.migrate_run import run
from tests.legacy33 import FIXTURES
from tests.store4_mint_fixtures import FIXTURES as CATALOGUE_FIXTURES, build_catalogue

V33 = sorted(FIXTURES.glob('v3.3-*.db'))
V32 = Path(__file__).parent / 'fixtures' / 'v3.2-b835cc6.db'               # the original 3.2 file, not its 3.3 upgrade


@pytest.fixture
def world(tmp_path):
    (tmp_path / 'cat').mkdir()
    catalogue = build_catalogue(tmp_path / 'cat')
    shutil.copytree(CATALOGUE_FIXTURES / 'mappings', tmp_path / 'maps')
    return catalogue, tmp_path / 'maps'


def copy_of(source, tmp_path):
    work = tmp_path / 'brickwork.db'
    shutil.copy(source, work)
    with closing(sqlite3.connect(work)) as db:
        db.execute('PRAGMA journal_mode=DELETE')                              # the migration refuses a file with a WAL
    return work


def migrate(source, tmp_path, catalogue, mappings):
    return run(copy_of(source, tmp_path), catalogue, mappings, tmp_path / 'out' / 'brickwork-4.db', tmp_path / 'out' / 'report')


@pytest.mark.parametrize('fixture', V33, ids=[f.stem for f in V33])
def test_migrates_to_4(fixture, tmp_path, world):
    catalogue, mappings = world
    res = migrate(fixture, tmp_path, catalogue, mappings)
    assert res.result == 'PASS', [(n, p['first_differences'][:2]) for n, p in res.proof['parts'].items() if p['differences']]
    assert res.published and res.out.exists()
    with closing(connect(res.out, catalogue, read_only=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'


def test_the_command_line_migrates_too(tmp_path, world, capsys):
    catalogue, mappings = world
    work = copy_of(V33[0], tmp_path)
    code = cli.main(['migrate', '--in', str(work), '--catalogue', str(catalogue), '--mappings', str(mappings),
                     '--out', str(tmp_path / 'cli' / 'brickwork-4.db'), '--report', str(tmp_path / 'cli' / 'report')])
    assert code == 0, capsys.readouterr()
    assert (tmp_path / 'cli' / 'brickwork-4.db').exists()


def test_a_3_2_file_is_refused(tmp_path, world):
    catalogue, mappings = world
    with pytest.raises(MigrationError, match='not 3.3'):
        migrate(V32, tmp_path, catalogue, mappings)
    assert not (tmp_path / 'out' / 'brickwork-4.db').exists()
