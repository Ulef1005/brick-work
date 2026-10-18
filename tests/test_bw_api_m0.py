"""M0 contracts, with synthetic values and no network transports."""
from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from brickwork.core import admin, collection, errors, price_settings, secrets, upgrade
from brickwork.core.connect import connect
from brickwork.core.sources.base import audit_origin, write


def old_store(path):
    db = sqlite3.connect(path)
    db.executescript(Path('brickwork/core/schema.sql').read_text())
    db.executemany('INSERT INTO events(entity,field,old_value,new_value,at,via) VALUES(?,?,?,?,?,?)',
                   [('synthetic', 'saved', 'old', 'new', '2026-01-01', via)
                    for via in ('app', 'cli', 'house-api', 'import', 'migration')])
    db.execute('CREATE TABLE price_settings(id INTEGER PRIMARY KEY, bricklink_region TEXT, bricklink_currency TEXT, incomplete_discount_pct INTEGER)')
    db.execute("INSERT INTO price_settings VALUES(1,'all','USD',25)")
    db.commit()
    before = db.execute('SELECT * FROM events ORDER BY id').fetchall()
    db.close()
    return before


def test_upgrade_twice_preserves_events_and_guards(tmp_path):
    path = tmp_path / 'synthetic.db'
    before = old_store(path)
    assert upgrade.upgrade(path)['api_v1'] is True
    assert upgrade.upgrade(path)['api_v1'] is False
    with closing(connect(path)) as db:
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.3'
        expected = [(*r[:-1], 'api' if r[-1] == 'house-api' else r[-1], None) for r in before]
        assert [tuple(r) for r in db.execute('SELECT * FROM events ORDER BY id')] == expected
        for sql in ("UPDATE events SET field='changed' WHERE id=1", 'DELETE FROM events WHERE id=1',
                    "INSERT OR REPLACE INTO events(id,entity,field,at,via) VALUES(1,'other','field','now','api')"):
            with pytest.raises(sqlite3.IntegrityError, match='append-only'), db:
                db.execute(sql)
        with pytest.raises(sqlite3.IntegrityError), db:
            db.execute("INSERT INTO events(entity,field,at,via) VALUES('x','x','now','unknown')")
        assert price_settings.read(db)['bricklink_currency'] == 'USD'
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='price_settings'").fetchone()


@pytest.mark.parametrize('read_only', [False, True])
def test_connect_upgrades_and_new_store_is_33(tmp_path, read_only):
    path = tmp_path / 'synthetic.db'
    old_store(path)
    with closing(connect(path, read_only=read_only)) as db:
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.3'
    with closing(connect(tmp_path / 'fresh.db')) as db:
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.3'


def test_upgrade_rolls_back_everything(tmp_path):
    path = tmp_path / 'synthetic.db'; before = old_store(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE api_tokens(collision TEXT)')
    with pytest.raises(sqlite3.OperationalError):
        upgrade.upgrade(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM events ORDER BY id').fetchall() == before
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.2'
        with pytest.raises(sqlite3.IntegrityError, match='append-only'):
            db.execute('DELETE FROM events')


def test_origin_and_actor(tmp_path):
    with closing(connect(tmp_path / 'synthetic.db')) as db:
        with db:
            admin.audit(db, 'test', 'web')
            with audit_origin('api', actor='synthetic-client'):
                admin.audit(db, 'test', 'api')
                write(db, "INSERT INTO settings VALUES('synthetic','value')")
            admin.audit(db, 'test', 'web-again')
        assert [tuple(r) for r in db.execute('SELECT via,actor FROM events')] == [
            ('app', None), ('api', 'synthetic-client'), ('api', 'synthetic-client'), ('app', None)]
        with pytest.raises(ValueError):
            with audit_origin('unknown'): pass


@pytest.mark.parametrize('group,table', [('purchase-places', 'purchase_locations'), ('tags', 'flags')])
def test_archive_and_undo_preserve_references(tmp_path, group, table):
    with closing(connect(tmp_path / 'synthetic.db')) as db:
        admin.value_write(db, group, 'add', name='Synthetic value')
        row = admin.value_rows(db, group)[0]; identifier = row['id']
        with db:
            db.execute("INSERT INTO items(item_type,item_no) VALUES('S','synthetic-set')")
            db.execute("INSERT INTO copies(id,set_no,purchase_location_id) VALUES('copy','synthetic-set',?)", (identifier if table == 'purchase_locations' else None,))
            if table == 'flags':
                db.execute("INSERT INTO item_flags VALUES('copy','copy',?)", (identifier,))
        event = admin.value_write(db, group, 'delete', identifier, confirmed=True)
        assert admin.value_rows(db, group) == []
        assert identifier not in [r['id'] for r in collection.options(db)['places' if table == 'purchase_locations' else 'flags']]
        if table == 'flags':
            assert db.execute('SELECT flag_id FROM item_flags').fetchone()[0] == identifier
        else:
            assert db.execute('SELECT purchase_location_id FROM copies').fetchone()[0] == identifier
        collection.undo(db, event); collection.undo(db, event)
        assert admin.value_rows(db, group)[0]['archived_at'] is None
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_price_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv('BW_PRICE_SETTINGS_LOCK', '0')
    with closing(connect(tmp_path / 'synthetic.db')) as db:
        saved = price_settings.save(db, dict(bricklink_currency='USD', bricklink_region='all', incomplete_discount_pct=25))
        assert price_settings.read(db) == saved
        assert saved['changed_at']
        assert db.execute("SELECT value FROM settings WHERE key='bricklink_currency'").fetchone()[0] == 'USD'
        before = price_settings.read(db)
        with pytest.raises(errors.ValidationFailed): price_settings.save(db, dict(incomplete_discount_pct=100))
        assert price_settings.read(db) == before


def test_error_codes_match_contract():
    text = Path('docs/brickwork/api-v1.md').read_text().split('## Appendix A:')[1].split('## Appendix B:')[0]
    import re
    assert dict((code, int(status)) for code, status in re.findall(r'\| `([a-z_]+)` \| (\d+) \|', text)) == errors.HTTP_STATUS
    for code, status in errors.HTTP_STATUS.items():
        cls = getattr(errors, ''.join(w.capitalize() for w in code.split('_')))
        assert cls().code == code and cls().status == status


def fernet_key(monkeypatch):
    from cryptography import fernet
    key = fernet.Fernet.generate_key().decode()
    monkeypatch.setenv('BW_SECRET_KEY', key)
    return fernet


def test_secret_round_trip_and_no_plaintext(tmp_path, monkeypatch):
    fernet_key(monkeypatch)
    path = tmp_path / 'synthetic.db'; plaintext = 'synthetic-credential-never-persist'
    ciphertext = secrets.encrypt(plaintext)
    assert secrets.decrypt(ciphertext) == plaintext
    with closing(connect(path)) as db:
        with db: db.execute('INSERT INTO source_keys VALUES(?,?,?,NULL)', ('brickset', ciphertext, '2026-01-01'))
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    for file in tmp_path.iterdir(): assert plaintext.encode() not in file.read_bytes()


def test_wrong_secret_fails_safely(monkeypatch):
    fernet = fernet_key(monkeypatch)
    ciphertext = secrets.encrypt('synthetic-credential')
    monkeypatch.setenv('BW_SECRET_KEY', fernet.Fernet.generate_key().decode())
    with pytest.raises(errors.ValidationFailed, match='cannot be decrypted'): secrets.decrypt(ciphertext)


def test_missing_secret_disables_entry(monkeypatch):
    monkeypatch.delenv('BW_SECRET_KEY', raising=False)
    with pytest.raises(errors.SourceNotConfigured, match='Key entry is disabled'): secrets.encrypt('synthetic-credential')


@pytest.mark.parametrize('group,table', [('purchase-places', 'purchase_locations'), ('tags', 'flags')])
def test_value_list_query_count_is_bounded(tmp_path, group, table):
    with closing(connect(tmp_path / 'synthetic.db')) as db:
        with db:
            if table == 'flags':
                db.executemany("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,'tag',1)",
                               [(f'flag-{i}', f'Synthetic flag {i}') for i in range(350)])
            else:
                db.executemany('INSERT INTO purchase_locations(id,name) VALUES(?,?)',
                               [(f'place-{i}', f'Synthetic place {i}') for i in range(350)])
        statements = []; db.set_trace_callback(statements.append)
        try: assert len(admin.value_rows(db, group)) == 350
        finally: db.set_trace_callback(None)
        assert len(statements) <= 5


def test_contract_yaml_records_m0_decisions():
    text = Path('docs/brickwork/openapi-v1.yaml').read_text()
    for path in ('/copies/{id}/photos', '/stock/{id}/photos', '/identifications',
                 '/identifications/{id}', '/identifications/{id}/thumb', '/sources/{source}/key'):
        assert f'  "{path}":' in text
    statuses = text.split('x-error-status:\n', 1)[1].split('servers:', 1)[0]
    import re
    assert {code: int(status) for code, status in re.findall(r'^  ([a-z_]+): (\d+)$', statuses, re.M)} == errors.HTTP_STATUS
    assert 'actor=token name' in text
    assert 'origin:' in text and 'saved_at:' in text and 'writeOnly: true' in text
    import re
    assert not re.search(r'        (?:condition|completeness):\n(?:(?:          |            ).*\n)*?            - "[NUDSCI]"', text)


def test_existing_planning_numeric_settings_still_read(tmp_path):
    with closing(connect(tmp_path / 'synthetic.db')) as db:
        with db:
            db.executemany('INSERT INTO settings VALUES(?,?)', [
                ('incomplete_discount_pct', '25.5'), ('repair_use_loose_stock', '1.0'),
                ('bricklink_region', 'EU')])
        assert price_settings.read(db)['incomplete_discount_pct'] == 25.5
        assert price_settings.read(db)['repair_use_loose_stock'] is True
        # A separate preference change preserves the planning service's stored values.
        saved = price_settings.save(db, {'repair_shipping': '4.00'})
        assert saved['bricklink_region'] == 'EU'
        assert saved['incomplete_discount_pct'] == 25.5
        assert saved['repair_use_loose_stock'] is True


@pytest.mark.parametrize('read_only', [False, True])
def test_current_connect_never_takes_initialize_lock(tmp_path, monkeypatch, read_only):
    import importlib
    connections = importlib.import_module('brickwork.core.connect')
    path = tmp_path / 'current.db'
    connect(path).close()

    class ForbiddenLock:
        def __enter__(self):
            raise AssertionError('Current store acquired initialization lock')

    monkeypatch.setattr(connections, '_INITIALIZE_LOCK', ForbiddenLock())
    with closing(connect(path, read_only=read_only)) as db:
        assert db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.3'


def test_concurrent_fresh_connects(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    path = tmp_path / 'fresh.db'

    def create():
        barrier.wait(timeout=10)
        with closing(connect(path)) as db:
            return db.execute('SELECT version FROM schema_meta').fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        assert [future.result(timeout=15) for future in futures] == ['3.3', '3.3']
    with closing(connect(path)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert list(db.execute('PRAGMA foreign_key_check')) == []
        assert db.execute('SELECT count(*) FROM schema_meta').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM sources').fetchone()[0] == 6


@pytest.mark.parametrize('key,bad', [
    (key, bad) for key in price_settings.DEFAULTS.keys() - {'changed_at'}
    for bad in [None, 'not-a-number', 'NaN', 'Infinity', '-1']])
def test_bad_stored_price_settings_default_and_overwrite(tmp_path, caplog, key, bad):
    with closing(connect(tmp_path / 'settings.db')) as db:
        with db:
            db.execute('INSERT INTO settings VALUES(?,?)', (key, bad))
        assert price_settings.read(db)[key] == price_settings.DEFAULTS[key]
        assert key in caplog.text and 'using default' in caplog.text
        # Even replacing invalid storage with its fallback default must persist.
        price_settings.save(db, {key: price_settings.DEFAULTS[key]})
        assert db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()[0] is not None
        caplog.clear()
        assert price_settings.read(db)[key] == price_settings.DEFAULTS[key]
        assert not caplog.records


def test_web_and_pipeline_paths_agree_with_other_database(tmp_path, monkeypatch):
    from flask import Flask
    from brickwork.core.pipeline import database_path
    from brickwork.web.admin_ops import brickwork_path
    monkeypatch.delenv('BW_DB_PATH', raising=False)
    app = Flask(__name__)
    app.config['DATABASE_PATH'] = str(tmp_path / 'elsewhere' / 'app.db')
    with app.app_context():
        assert brickwork_path() == database_path() == Path('data/brickwork.db')
        app.config['BRICKWORK_DB_PATH'] = str(tmp_path / 'configured.db')
        assert brickwork_path() == database_path() == tmp_path / 'configured.db'
        monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'environment.db'))
        assert brickwork_path() == database_path() == tmp_path / 'environment.db'
