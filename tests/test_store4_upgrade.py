"""In-place upgrades of older collections: 4.0 to 4.1 (#131: a wish's max price with box) and 4.1 to 4.2 (#167: the owner identity of a job claim;
#155: why an order line is not placed), with invented files."""
from contextlib import closing
import hashlib
from pathlib import Path
import re
import sqlite3

import pytest

from brickwork.store4.connect import HERE, SCHEMA_VERSION, UPGRADES, connect, upgrade

NEW = ('max_price_boxed', 'max_price_boxed_currency')
TABLES = ('wish', 'job_owner', 'order_line')


def old_sql(*, drop_41):
    """Today's schema without what the later steps add: the 4.2 lines (marked `-- 4.2`), and with `drop_41` the 4.1 ones too."""
    lines = (HERE / 'brickwork.sql').read_text().splitlines(keepends=True)
    kept = ''.join(line for line in lines if '-- 4.2' not in line and not (drop_41 and 'max_price_boxed' in line))
    assert len(kept) < sum(map(len, lines))
    return re.sub(r',(\s*\n\))', r'\1', kept)                  # the last column of job_owner lost its successor: no comma before the paren


def make_old(path, version):
    """A file as an older Brick Work made it, with one wish with a max, a job with its owner and an order line."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript('BEGIN;\n' + old_sql(drop_41=version == '4.0'))
        db.executemany('INSERT INTO meta(key, value) VALUES(?, ?)', [('schema_version', version), ('install_id', 'x'), ('created_at', 'y')])
        db.execute("INSERT INTO item(id,origin,kind,born_provider,born_namespace,born_key,name,kind_source,created_at,updated_at)"
                   " VALUES(1000000001,'local','set',NULL,NULL,NULL,'Syn set','manual','2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')")
        db.execute("INSERT INTO wish(id,kind,item_id,max_price,max_price_currency,added_at,updated_at)"
                   " VALUES('w1','set',1000000001,'40.00','EUR','2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')")
        db.execute("INSERT INTO job(id,source,kind,state,via,created_at,updated_at)"
                   " VALUES(1,'import','item','running','app','2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')")
        db.execute("INSERT INTO job_owner(job_id,pid,claimed_at) VALUES(1,4242,'2026-10-26T12:00:00.000Z')")
        db.execute("INSERT INTO purchase_order(id,created_at,updated_at) VALUES(1,'2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')")
        db.execute("INSERT INTO order_document(id,order_id,source,digest,phase,created_at,updated_at)"
                   " VALUES(1,1,'email','d','draft','2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')")
        db.execute("INSERT INTO order_line(id,order_id,document_id,line_no,state,qty,updated_at)"
                   " VALUES(1,1,1,1,'held',2,'2026-10-26T12:00:00.000Z')")
        db.commit()
    return path


def make_40(path):
    return make_old(path, '4.0')


def make_41(path):
    return make_old(path, '4.1')


def shape(db, table='wish'):
    return [tuple(r)[1:] for r in db.execute(f'PRAGMA main.table_xinfo({table})')]


def test_the_version_is_42_and_the_steps_chain_from_40():
    assert SCHEMA_VERSION == '4.2' and list(UPGRADES) == ['4.0', '4.1'] and UPGRADES['4.0'][0] == '4.1' and UPGRADES['4.1'][0] == '4.2'


def test_a_40_file_is_upgraded_on_open_and_keeps_its_wishes(tmp_path):
    path = make_40(tmp_path / 'brickwork.db')
    with closing(connect(path, tmp_path / 'catalogue.db')) as db:
        meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
        assert meta['schema_version'] == '4.2' and meta['upgraded_to_4.1'].endswith('Z') and meta['upgraded_to_4.2'].endswith('Z')
        row = db.execute('SELECT * FROM wish').fetchone()
        assert (row['max_price'], row['max_price_currency'], row['max_price_boxed'], row['max_price_boxed_currency']) == ('40.00', 'EUR', None, None)
        with pytest.raises(sqlite3.IntegrityError):                       # the pair rule holds on an upgraded file too
            db.execute("UPDATE wish SET max_price_boxed='55.00'")
        db.execute("UPDATE wish SET max_price_boxed='55.00', max_price_boxed_currency='EUR'")


def test_a_41_file_is_upgraded_and_keeps_its_claims_and_order_lines(tmp_path):
    path = make_41(tmp_path / 'brickwork.db')
    with closing(connect(path, tmp_path / 'catalogue.db')) as db:
        meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
        assert meta['schema_version'] == '4.2' and meta['upgraded_to_4.2'].endswith('Z') and 'upgraded_to_4.1' not in meta
        assert tuple(db.execute('SELECT job_id, pid, claimed_at, boot_id, start_ticks FROM job_owner').fetchone()) == (1, 4242, '2026-10-26T12:00:00.000Z', None, None)
        assert tuple(db.execute('SELECT id, state, qty, unplaced_reason FROM order_line').fetchone()) == (1, 'held', 2, None)


@pytest.mark.parametrize('make', [make_40, make_41])
def test_an_upgraded_table_matches_a_new_one(tmp_path, make):
    with closing(connect(make(tmp_path / 'old.db'), tmp_path / 'catalogue.db')) as upgraded, \
            closing(connect(tmp_path / 'new.db', tmp_path / 'catalogue.db')) as new:
        assert [shape(upgraded, t) for t in TABLES] == [shape(new, t) for t in TABLES]
        assert [r[0] for r in shape(new)][-2:] == list(NEW)
        assert [r[0] for r in shape(new, 'job_owner')][-2:] == ['boot_id', 'start_ticks'] and shape(new, 'order_line')[-1][0] == 'unplaced_reason'
        sql = [db.execute("SELECT sql FROM sqlite_master WHERE name='wish'").fetchone()[0] for db in (upgraded, new)]
        assert all(s.count('CHECK((max_price_boxed IS NULL) = (max_price_boxed_currency IS NULL))') == 1 for s in sql)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_a_read_only_open_never_writes_and_a_write_open_upgrades_once(tmp_path):
    from brickwork.store4.errors import UpgradeFailed
    path = make_40(tmp_path / 'brickwork.db')
    before = digest(path)
    with pytest.raises(UpgradeFailed, match='open it read-write once'):
        connect(path, tmp_path / 'catalogue.db', read_only=True)
    assert digest(path) == before                                         # refused, and left exactly as it was
    connect(path, tmp_path / 'catalogue.db').close()
    with closing(connect(path, tmp_path / 'catalogue.db', read_only=True)) as db:
        assert {r[1] for r in db.execute('PRAGMA table_xinfo(wish)')} >= set(NEW)
    assert upgrade(path) == '4.2'                                         # nothing left to do: no second ALTER
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT count(*) FROM pragma_table_xinfo('wish') WHERE name LIKE 'max_price_boxed%'").fetchone()[0] == 2


def test_app_start_upgrades_and_a_read_only_instance_refuses(tmp_path, monkeypatch):
    from brickwork.core.connect import OldStore, upgrade as start_upgrade
    path = make_40(tmp_path / 'brickwork.db')
    start_upgrade(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.2'
    start_upgrade(path)                                                   # current: a no-op
    old = make_40(tmp_path / 'other.db')
    monkeypatch.setenv('BW_READ_ONLY', '1')
    monkeypatch.setenv('BW_DB_PATH', str(old))
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    from flask import Flask
    from brickwork.app import setup_app
    before = digest(old)
    with pytest.raises(OldStore, match='open it read-write once'):
        setup_app(Flask('read-only-start'))
    assert digest(old) == before


def test_a_failed_step_leaves_the_file_at_40(tmp_path, monkeypatch):
    path = make_40(tmp_path / 'brickwork.db')
    broken = ('4.1', (UPGRADES['4.0'][1][0], 'ALTER TABLE no_such_table ADD COLUMN x TEXT'))
    monkeypatch.setitem(UPGRADES, '4.0', broken)
    with pytest.raises(sqlite3.OperationalError):
        upgrade(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'
        assert 'max_price_boxed' not in {r[1] for r in raw.execute('PRAGMA table_xinfo(wish)')}


def test_a_failed_second_step_leaves_the_file_at_41(tmp_path, monkeypatch):
    path = make_40(tmp_path / 'brickwork.db')
    monkeypatch.setitem(UPGRADES, '4.1', ('4.2', (UPGRADES['4.1'][1][0], 'ALTER TABLE no_such_table ADD COLUMN x TEXT')))
    with pytest.raises(sqlite3.OperationalError):
        upgrade(path)
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.1'
        assert 'max_price_boxed' in {r[1] for r in raw.execute('PRAGMA table_xinfo(wish)')}
        assert 'boot_id' not in {r[1] for r in raw.execute('PRAGMA table_xinfo(job_owner)')}


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


@pytest.mark.parametrize('error,hint', [('attempt to write a readonly database', 'make it writable'),
                                         ('database is locked', 'another process holds the file')])
def test_a_failed_upgrade_says_open_again_never_migrate(tmp_path, monkeypatch, error, hint):
    from brickwork.core.connect import OldStore, connect as core_connect
    from brickwork.store4 import connect as store4_connect
    from brickwork.store4.errors import UpgradeFailed
    path = make_40(tmp_path / 'brickwork.db')

    def failing(path):
        raise sqlite3.OperationalError(error)
    monkeypatch.setattr(store4_connect, 'upgrade', failing)
    with pytest.raises(UpgradeFailed, match=hint):
        connect(path, tmp_path / 'catalogue.db')
    with pytest.raises(OldStore) as refused:
        core_connect(path, require_catalogue=False)
    assert 'could not be upgraded' in str(refused.value) and 'migrate' not in str(refused.value)


def test_undo_of_a_change_recorded_before_the_upgrade(tmp_path):
    """A receipt and a RowLog written on 4.0 lack the added columns; after the upgrade they undo like new ones."""
    from brickwork.core import collection
    from brickwork.store4.rowlog import RowLog
    path = make_40(tmp_path / 'brickwork.db')
    raw = sqlite3.connect(path)                                           # the 4.0 app: no upgrade, rows without the new columns
    raw.row_factory = sqlite3.Row
    event = collection.save(raw, 'wish', ['w1'], dict(max_price='45'))
    raw.commit()
    log = RowLog(raw)
    log.update('wish', log.select('wish', 'id=?', ('w1',))[0], note='Logged on 4.0')
    raw.commit()
    changes = log.changes
    assert 'max_price_boxed' not in changes[0]['a']
    raw.close()
    with closing(connect(path, tmp_path / 'catalogue.db')) as db:
        log = RowLog(db, changes)
        assert log.verify() is None
        log.restore()
        db.commit()
        assert db.execute("SELECT note, max_price_boxed FROM wish WHERE id='w1'").fetchone()[:] == (None, None)
        collection.undo(db, event)
        db.commit()
        assert db.execute("SELECT max_price, max_price_currency FROM wish WHERE id='w1'").fetchone()[:] == ('40.00', 'EUR')
