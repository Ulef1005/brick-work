"""Shared admin services (CLI and browser) on the 4.0 store (M.8i part 1, issue #110): no network."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
from unittest.mock import Mock

from flask import Flask
import pytest
import requests

from brickwork.core import admin
from brickwork.core.sources import base
from brickwork.web import admin_ops as ops
from tests.app4 import coll, pair  # noqa: F401  (the fixtures)
from tests.sources4 import keyed, unkeyed


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, 'request', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(base, 'transport', Mock(side_effect=AssertionError('network forbidden')))
    unkeyed(monkeypatch)


@pytest.fixture
def where(tmp_path, monkeypatch):
    """A folder with no collection in it yet (BW_DB_PATH names the file the CLI would open)."""
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
    return tmp_path


def snapshot(directory):
    return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in Path(directory).rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm'))}


READ_COMMANDS = [['check'], ['catalogue', 'status'], ['sources', 'status'], ['settings', 'show']]


@pytest.mark.parametrize('command', READ_COMMANDS)
def test_read_commands_require_setup(where, monkeypatch, capsys, command):
    from brickwork.web import cli
    monkeypatch.setattr(cli, 'application_context', lambda operation: Flask('x').app_context())
    before = snapshot(where)
    code = cli.main(command)
    error = capsys.readouterr().err
    if command in (['catalogue', 'status'], ['sources', 'status']):
        assert code == 0  # reads the files that exist and the environment only
    else:
        assert code == 1 and error.startswith('Web error: ')
    assert snapshot(where) == before
    assert not (where / 'brickwork.db').exists()


@pytest.mark.parametrize('command', READ_COMMANDS)
def test_cli_reads_wal_database_without_writes(where, monkeypatch, command):
    from brickwork.web import cli
    assert ops.setup()['setup'] == 'ok'
    with closing(sqlite3.connect(where / 'brickwork.db')) as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before = snapshot(where)
    statements = []
    original = sqlite3.connect

    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, 'connect', traced)
    monkeypatch.setattr(cli, 'application_context', lambda operation: Flask('x').app_context())
    assert cli.main(['--json', *command]) == 0
    assert snapshot(where) == before
    writes = [s for s in statements if s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP'))
              and s != 'CREATE VIRTUAL TABLE t USING fts5(x)']          # store4.connect's FTS5 probe, on an in-memory database
    assert not writes, writes


def test_setup_creates_a_4_0_collection_and_names_the_catalogue(where):
    result = ops.setup()
    assert result['catalogue'] == 'missing' and 'catalogue download' in result['next'] and result['database'] == str(where / 'brickwork.db')
    with closing(sqlite3.connect(where / 'brickwork.db')) as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'
        assert db.execute('SELECT count(*) FROM source_freshness').fetchone()[0] == 15


def test_a_3_3_file_is_refused_by_setup_and_every_service(where):
    from brickwork.core import errors
    (where / 'brickwork.db').write_bytes(b'')
    with closing(sqlite3.connect(where / 'brickwork.db')) as db:
        db.execute('CREATE TABLE schema_meta(key TEXT, value TEXT)')
        db.commit()
    for service in (ops.setup, ops.brickwork_check, ops.settings_show):
        with pytest.raises(errors.NotSetUp, match='brickwork migrate4|store4 migrate'):
            service()


def test_catalogue_commands_are_store4s(where, monkeypatch):
    from brickwork.store4 import cli as store4
    calls = []
    monkeypatch.setattr(store4, 'do_import_bricklink', lambda paths, directory: calls.append((paths.collection, paths.catalogue, directory)) or {'bricklink': 'ok'})
    assert ops.catalogue_import_bricklink('lists-dir') == {'bricklink': 'ok'}
    assert calls == [(where / 'brickwork.db', where / 'catalogue.db', 'lists-dir')]
    status = ops.catalogue_status()
    assert status['catalogue'] is None and status['collection'] is None and status['data'] == str(where)


def test_catalogue_status_reads_the_pair(coll, pair, monkeypatch):
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    status = ops.catalogue_status()
    assert status['catalogue']['bricklink_lists_loaded'] is False and status['collection']['activated_builds']


def test_migrate4_is_the_store4_migration(monkeypatch):
    from brickwork.store4 import cli as store4
    seen = []
    monkeypatch.setattr(store4, 'main', lambda argv: seen.append(argv) or 0)
    assert ops.migrate4(['--in', 'a.db', '--out', 'b.db']) == 0
    assert seen == [['migrate', '--in', 'a.db', '--out', 'b.db']]


def sets_net(request):
    """BrickLink's price guide and Brickset's getSets for the fixture set, whichever is asked."""
    if 'brickset' in request.full_url:
        return json.dumps({'status': 'success', 'matches': 1, 'sets': [{'setID': 5001, 'number': '1000', 'numberVariant': 1, 'name': 'Syn Castle Keep',
                                                                        'year': 1990, 'theme': 'Castle', 'pieces': 438, 'LEGOCom': {'DE': {'retailPrice': 79.99}}}]})
    return json.dumps({'meta': {'code': 200}, 'data': {'total_quantity': 2, 'qty_avg_price': '100', 'min_price': '90', 'max_price': '110'}})


def test_source_admin_commands(coll, world_free, pair, monkeypatch):
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    before = snapshot(pair.parent)
    status = ops.sources_status()
    assert status['bricklink']['used_today'] == 0 and status['brickset']['key'] == 'unset' and status['brickognize']['key'] == 'set'
    assert snapshot(pair.parent) == before
    keyed(monkeypatch, 'bricklink', 'brickset')
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    monkeypatch.setattr(base, 'transport', sets_net)
    result = ops.prices_refresh('1000-1')
    assert result['ok'] and result['state'] == 'done'
    assert ops.sources_status()['bricklink']['used_today'] == 2                       # new and used, one call each
    assert ops.brickset_refresh(['1000-1'])['state'] == 'done'
    assert ops.brickset_refresh([])['state'] == 'done'                                 # no number: every set held or wanted
    assert ops.settings_set('retail_country', 'US') == {'retail_country': 'US'}
    assert coll.db.execute("SELECT value FROM setting WHERE key='retail_country'").fetchone()[0] == 'US'
    assert coll.db.execute("SELECT via FROM event WHERE entity_kind='settings' ORDER BY id DESC").fetchone()[0] == 'cli'
    assert {j['kind'] for j in admin.jobs(coll.db)} == {'item'} and all(j['via'] == 'cli' for j in admin.jobs(coll.db))


@pytest.fixture
def world_free(coll):
    """The fixture set `1000-1` held once and a wish for another."""
    coll.add_copy('1000-1')
    coll.add_wish(coll.item('sets', '1000-2'))


def test_a_set_the_collection_does_not_know_is_named_not_guessed(coll, pair, monkeypatch):
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    with pytest.raises(ValueError, match='not a set Brick Work knows'):
        ops.prices_refresh('9999-1')
    assert coll.db.execute('SELECT count(*) FROM job').fetchone()[0] == 0


def test_import_priority_admin_service(coll, pair, monkeypatch):
    from brickwork.core.pipeline import STEPS
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    priority = {'pictures': {'part': ['bricklink', 'rebrickable_dump'], '*': ['bricklink']}}
    assert ops.settings_set('source_priority', json.dumps(priority)) == {'source_priority': priority}
    assert admin.settings(coll.db)['priority']['pictures'] == priority['pictures']
    order = list(reversed(STEPS))
    assert ops.settings_set('import_order:part', json.dumps(order)) == {'import_order:part': order}
    assert admin.settings(coll.db)['import_order'] == {'part': order}
    with pytest.raises(ValueError):
        ops.settings_set('import_order:part', '["identity"]')
    with pytest.raises(ValueError):
        ops.settings_set('import_order:planet', json.dumps(order))
    with pytest.raises(ValueError):
        ops.settings_set('source_priority', '[]')
    with pytest.raises(ValueError, match='unsupported setting'):
        ops.settings_set('secret', 'x')
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-private')
    assert ops.sources_status()['rebrickable']['key'] == 'set'
    assert ops.jobs_list() == []


def test_bad_price_settings_reads_and_save(coll, pair, monkeypatch):
    from brickwork.core.price_settings import DEFAULTS
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    coll.setting('incomplete_discount_pct', None)
    coll.setting('repair_use_loose_stock', 'invalid')
    shown = ops.settings_show()
    assert {k: shown[k] for k in DEFAULTS} == DEFAULTS and shown['retail_country'] == 'DE' and shown['display_currency'] == 'EUR'
    assert ops.settings_set('incomplete_discount_pct', '40')['incomplete_discount_pct'] == 40


def test_import_runs_the_items_job_here(coll, pair, monkeypatch):
    from brickwork.core import source_ops
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    monkeypatch.setattr(source_ops, 'register_handlers', lambda **options: None)          # the source steps end 'skipped': no source is called
    result = ops.import_item('S', '1000-1')
    assert result['state'] == 'done' and [s['name'] for s in result['steps']] == ['identity', 'inventory', 'matching', 'pictures', 'metadata', 'market_price']
    assert ops.jobs_list(failed=False)[0]['id'] == result['id'] and ops.jobs_list(failed=True) == []
    with pytest.raises(ValueError, match='not one item'):
        ops.import_item('S', 'nonesuch')
    with pytest.raises(Exception):
        ops.import_item('Z', '1000-1')
