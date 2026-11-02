"""In-place upgrade of a 4.0 collection to 4.1 (#131: a wish's max price with box), with invented files."""
from contextlib import closing
import sqlite3

import pytest

from brickwork.store4.connect import HERE, SCHEMA_VERSION, UPGRADES, connect, upgrade

NEW = ('max_price_boxed', 'max_price_boxed_currency')


def make_40(path):
    """A 4.0 file as setup made it before #131: today's schema without the line the 4.1 step adds, and one wish with a max."""
    lines = (HERE / 'brickwork.sql').read_text().splitlines(keepends=True)
    old = ''.join(line for line in lines if 'max_price_boxed' not in line)
    assert len(old) < sum(map(len, lines))
    with closing(sqlite3.connect(path)) as db:
        db.executescript('BEGIN;\n' + old)
        db.executemany('INSERT INTO meta(key, value) VALUES(?, ?)', [('schema_version', '4.0'), ('install_id', 'x'), ('created_at', 'y')])
        db.execute("INSERT INTO item(id,origin,kind,born_provider,born_namespace,born_key,name,kind_source,created_at,updated_at)"
                   " VALUES(1000000001,'local','set',NULL,NULL,NULL,'Syn set','manual','2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')")
        db.execute("INSERT INTO wish(id,kind,item_id,max_price,max_price_currency,added_at,updated_at)"
                   " VALUES('w1','set',1000000001,'40.00','EUR','2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')")
        db.commit()
    return path


def shape(db):
    return [tuple(r)[1:] for r in db.execute('PRAGMA main.table_xinfo(wish)')]


def test_the_version_is_41_and_the_only_step_is_from_40():
    assert SCHEMA_VERSION == '4.1' and list(UPGRADES) == ['4.0'] and UPGRADES['4.0'][0] == '4.1'


def test_a_40_file_is_upgraded_on_open_and_keeps_its_wishes(tmp_path):
    path = make_40(tmp_path / 'brickwork.db')
    with closing(connect(path, tmp_path / 'catalogue.db')) as db:
        meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
        assert meta['schema_version'] == '4.1' and meta['upgraded_to_4.1'].endswith('Z')
        row = db.execute('SELECT * FROM wish').fetchone()
        assert (row['max_price'], row['max_price_currency'], row['max_price_boxed'], row['max_price_boxed_currency']) == ('40.00', 'EUR', None, None)
        with pytest.raises(sqlite3.IntegrityError):                       # the pair rule holds on an upgraded file too
            db.execute("UPDATE wish SET max_price_boxed='55.00'")
        db.execute("UPDATE wish SET max_price_boxed='55.00', max_price_boxed_currency='EUR'")


def test_an_upgraded_wish_table_matches_a_new_one(tmp_path):
    with closing(connect(make_40(tmp_path / 'old.db'), tmp_path / 'catalogue.db')) as upgraded, \
            closing(connect(tmp_path / 'new.db', tmp_path / 'catalogue.db')) as new:
        assert shape(upgraded) == shape(new) and [r[0] for r in shape(new)][-2:] == list(NEW)
        sql = [db.execute("SELECT sql FROM sqlite_master WHERE name='wish'").fetchone()[0] for db in (upgraded, new)]
        assert all(s.count('CHECK((max_price_boxed IS NULL) = (max_price_boxed_currency IS NULL))') == 1 for s in sql)


def test_a_read_only_open_upgrades_first_and_an_upgrade_runs_once(tmp_path):
    path = make_40(tmp_path / 'brickwork.db')
    with closing(connect(path, tmp_path / 'catalogue.db', read_only=True)) as db:
        assert {r[1] for r in db.execute('PRAGMA table_xinfo(wish)')} >= set(NEW)
    assert upgrade(path) == '4.1'                                         # nothing left to do: no second ALTER
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT count(*) FROM pragma_table_xinfo('wish') WHERE name LIKE 'max_price_boxed%'").fetchone()[0] == 2


def test_a_failed_step_leaves_the_file_at_40(tmp_path, monkeypatch):
    path = make_40(tmp_path / 'brickwork.db')
    broken = ('4.1', (UPGRADES['4.0'][1][0], 'ALTER TABLE no_such_table ADD COLUMN x TEXT'))
    monkeypatch.setitem(UPGRADES, '4.0', broken)
    with pytest.raises(sqlite3.OperationalError):
        upgrade(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'
        assert 'max_price_boxed' not in {r[1] for r in raw.execute('PRAGMA table_xinfo(wish)')}


def test_a_stale_40_file_is_refused_before_anything_writes_to_it(tmp_path):
    from brickwork.store4.errors import StaleSchema
    path = make_40(tmp_path / 'brickwork.db')
    with closing(sqlite3.connect(path)) as raw:                          # rebuild item_link as before #124: no AUTOINCREMENT
        sql = raw.execute("SELECT sql FROM sqlite_master WHERE name='item_link'").fetchone()[0]
        raw.executescript('PRAGMA foreign_keys=OFF; DROP TABLE item_link; ' + sql.replace('AUTOINCREMENT', '') + ';')
    with pytest.raises(StaleSchema):
        connect(path, tmp_path / 'catalogue.db')
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'
        assert 'max_price_boxed' not in {r[1] for r in raw.execute('PRAGMA table_xinfo(wish)')}


def test_a_failed_upgrade_says_open_again_never_migrate(tmp_path):
    from brickwork.core.connect import OldStore, connect as core_connect
    from brickwork.store4.errors import UpgradeFailed
    path = make_40(tmp_path / 'brickwork.db')
    path.chmod(0o444)
    try:
        with pytest.raises(UpgradeFailed, match='make it writable'):
            connect(path, tmp_path / 'catalogue.db', read_only=True)
        with pytest.raises(OldStore) as refused:
            core_connect(path, read_only=True, require_catalogue=False)
        assert 'could not be upgraded' in str(refused.value) and 'migrate' not in str(refused.value)
    finally:
        path.chmod(0o644)
