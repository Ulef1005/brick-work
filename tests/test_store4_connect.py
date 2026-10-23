"""Two-file connection of the 4.0 store: initialisation, refusals and the binding checks, with invented files."""
from contextlib import closing
import os
import sqlite3
import uuid

import pytest

from brickwork.core.connect import connect as connect33
from brickwork.store4 import identity
from brickwork.store4.connect import connect, create_catalogue, has_catalogue
from brickwork.store4.errors import CatalogueError, CatalogueMismatch, SchemaMismatch, Unsupported
from tests.store4_fixtures import activate, make_catalogue, pair


def test_new_file_gets_the_schema_and_meta(tmp_path):
    with closing(connect(tmp_path / 'brickwork.db', tmp_path / 'catalogue.db')) as db:
        meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
        assert meta['schema_version'] == '4.0'
        assert str(uuid.UUID(meta['install_id'])) == meta['install_id']
        assert meta['created_at'].endswith('Z')
        assert 'catalogue_id' not in meta
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert db.execute('SELECT id FROM color ORDER BY id').fetchall()[0]['id'] == 1
        assert not has_catalogue(db)
    with closing(connect(tmp_path / 'brickwork.db', tmp_path / 'catalogue.db')) as again:
        assert again.execute("SELECT value FROM meta WHERE key='install_id'").fetchone()[0] == meta['install_id']


def test_refuses_a_33_file_and_other_versions(tmp_path):
    old = tmp_path / 'old.db'
    with closing(connect33(old)):
        pass
    with pytest.raises(SchemaMismatch, match='3.3 file must be migrated'):
        connect(old, tmp_path / 'catalogue.db')
    with pytest.raises(SchemaMismatch):
        connect(old, tmp_path / 'catalogue.db', read_only=True)
    with closing(sqlite3.connect(old)) as raw:     # untouched: still a 3.3 file
        assert raw.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.3'
    odd = tmp_path / 'odd.db'
    with closing(connect(odd, tmp_path / 'catalogue.db')) as db:
        db.execute("UPDATE meta SET value='4.1' WHERE key='schema_version'")
        db.commit()
    with pytest.raises(SchemaMismatch, match="'4.1'"):
        connect(odd, tmp_path / 'catalogue.db')


def test_a_refused_file_keeps_its_journal_mode(tmp_path):
    plain = tmp_path / 'plain.db'
    with closing(sqlite3.connect(plain)) as raw:
        raw.execute('CREATE TABLE schema_meta(version TEXT)')
        raw.execute("INSERT INTO schema_meta VALUES('3.3')")
        raw.commit()
    with pytest.raises(SchemaMismatch):
        connect(plain, tmp_path / 'catalogue.db')
    with closing(sqlite3.connect(plain)) as raw:
        assert raw.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'


def test_environment_is_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, 'sqlite_version_info', (3, 36, 1))
    monkeypatch.setattr(sqlite3, 'sqlite_version', '3.36.1')
    with pytest.raises(Unsupported, match='3.36.1'):
        connect(tmp_path / 'brickwork.db', tmp_path / 'catalogue.db')
    assert not (tmp_path / 'brickwork.db').exists()


def test_failed_initialisation_leaves_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr('brickwork.store4.connect.now', lambda: None)      # NOT NULL meta value
    with pytest.raises(sqlite3.IntegrityError):
        connect(tmp_path / 'brickwork.db', tmp_path / 'catalogue.db')
    assert not list(tmp_path.iterdir())


def test_read_only_collection_and_catalogue(tmp_path):
    col, cat = pair(tmp_path)
    with closing(connect(col, cat, read_only=True)) as db:
        assert has_catalogue(db)
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute("INSERT INTO meta VALUES('x', 'y')")
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute("INSERT INTO catalogue.meta VALUES('x', 'y')")
    with closing(connect(col, cat)) as db:            # a writable collection still cannot write the catalogue
        db.execute("INSERT INTO meta VALUES('x', 'y')")
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute("INSERT INTO catalogue.meta VALUES('x', 'y')")
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute('DELETE FROM catalogue.item')
    with pytest.raises(sqlite3.OperationalError):
        connect(tmp_path / 'absent.db', cat, read_only=True)
    assert not (tmp_path / 'absent.db').exists()


def test_catalogue_must_be_delete_mode_and_a_catalogue(tmp_path):
    col, cat = pair(tmp_path)
    with closing(sqlite3.connect(cat)) as raw:
        raw.execute('PRAGMA journal_mode=WAL')
    with pytest.raises(CatalogueError, match='journal_mode=wal'):
        connect(col, cat)
    with closing(sqlite3.connect(cat)) as raw:
        raw.execute('PRAGMA journal_mode=DELETE')
        raw.execute("UPDATE meta SET value='catalogue-3' WHERE key='schema_version'")
        raw.commit()
    with pytest.raises(CatalogueError, match='not a Brick Work catalogue'):
        connect(col, cat)
    other = tmp_path / 'other.db'
    with closing(sqlite3.connect(other)) as raw:
        raw.execute('CREATE TABLE t(x)')
    with pytest.raises(CatalogueError, match='not a Brick Work catalogue'):
        connect(col, other)


def test_create_catalogue_is_empty_and_journal_delete(tmp_path):
    with closing(create_catalogue(tmp_path / 'c.db')) as c:
        assert c.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
        assert c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == 'catalogue-4.0'
        assert c.execute('SELECT count(*) FROM item').fetchone()[0] == 0
    with pytest.raises(FileExistsError):
        create_catalogue(tmp_path / 'c.db')


FIX = 'catalogue rebuild'


def test_binding_unbound_and_matching_are_allowed(tmp_path):
    col, cat = pair(tmp_path)
    with closing(connect(col, cat)) as db:                       # no catalogue_id yet: written by build activation
        assert has_catalogue(db)
    activate(col, catalogue_id='cat-A', catalogue_item_high_water='20', catalogue_color_high_water='7')
    with closing(connect(col, cat)) as db:
        assert has_catalogue(db)
    activate(col, catalogue_item_high_water='5')                 # a catalogue that has grown since is fine
    with closing(connect(col, cat)):
        pass


def test_binding_refuses_another_catalogue(tmp_path):
    col, cat = pair(tmp_path)
    activate(col, builds=(), catalogue_id='cat-B')
    with pytest.raises(CatalogueMismatch, match=FIX) as err:
        connect(col, cat)
    assert 'restore brickwork.db and catalogue.db from the same archive' in str(err.value)


def test_binding_refuses_a_catalogue_without_an_id_for_a_bound_collection(tmp_path):
    col, cat = pair(tmp_path)
    with closing(sqlite3.connect(cat)) as raw:
        raw.execute("DELETE FROM meta WHERE key='catalogue_id'")
        raw.commit()
    activate(col, builds=(), catalogue_id='cat-A')
    with pytest.raises(CatalogueMismatch, match=FIX):
        connect(col, cat)


def test_binding_refuses_a_catalogue_lacking_an_activated_build(tmp_path):
    col, cat = pair(tmp_path)
    activate(col, builds=(3,))
    with pytest.raises(CatalogueMismatch, match=FIX) as err:
        connect(col, cat)
    assert '[3]' in str(err.value)


@pytest.mark.parametrize('meta', [{'catalogue_item_high_water': '21'}, {'catalogue_color_high_water': '8'}])
def test_binding_refuses_an_older_catalogue(tmp_path, meta):
    col, cat = pair(tmp_path)
    activate(col, builds=(), **meta)
    with pytest.raises(CatalogueMismatch, match=FIX) as err:
        connect(col, cat)
    assert 'older' in str(err.value)


def test_a_refused_connection_is_closed_and_a_second_attempt_works(tmp_path):
    col, cat = pair(tmp_path)
    activate(col, builds=(), catalogue_id='cat-B')
    for _ in range(2):
        with pytest.raises(CatalogueMismatch):
            connect(col, cat)


def test_projected_item_is_readable_without_the_catalogue(tmp_path):
    col, cat = pair(tmp_path)
    with closing(connect(col, cat)) as db:
        identity.project(db, 12)
        db.commit()
    with closing(connect(col, tmp_path / 'gone.db', read_only=True)) as db:
        assert not has_catalogue(db)
        row = db.execute('SELECT name, born_key FROM item WHERE id=12').fetchone()
        assert row['born_key'] == '970c03'
        assert db.execute('SELECT count(*) FROM item_link WHERE item_id=12').fetchone()[0] == 2
        assert identity.resolve(db, 12, 4)[:2] == ('P', '970c00')
    with closing(connect(col, tmp_path / 'gone.db')) as db:
        with pytest.raises(CatalogueError, match='not attached'):
            identity.project(db, 11)
        assert identity.project(db, 12) == 12                    # already projected: no catalogue needed


def test_a_concurrent_first_opener_keeps_the_winners_file(tmp_path, monkeypatch):
    target = tmp_path / 'brickwork.db'
    real_link = os.link

    def racing_link(src, dst):                                   # another opener finishes first, then this one links
        monkeypatch.setattr('os.link', real_link)
        with closing(connect(target, tmp_path / 'catalogue.db')) as winner:
            winner.execute("INSERT INTO meta VALUES('winner', '1')")
            winner.commit()
        real_link(src, dst)

    monkeypatch.setattr('os.link', racing_link)
    with closing(connect(target, tmp_path / 'catalogue.db')) as db:
        assert db.execute("SELECT value FROM meta WHERE key='winner'").fetchone()[0] == '1'
    assert not [p.name for p in tmp_path.iterdir() if p.name.endswith('.new')]   # the loser's temporary file is gone
