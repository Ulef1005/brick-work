"""Shared admin services (CLI and browser): core store only, no network."""
from pathlib import Path
import hashlib
import json
import sqlite3
from unittest.mock import Mock

import pytest
import requests

from brickwork.web import admin_ops as ops
from tests.web_fixtures import app, apps  # noqa: F401


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, 'request', Mock(side_effect=AssertionError('network forbidden')))


def snapshot(directory):
    return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in Path(directory).rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm'))}


READ_COMMANDS = [['check'], ['catalogue', 'status'], ['sources', 'status'], ['settings', 'show']]


@pytest.mark.parametrize('command', READ_COMMANDS)
def test_read_commands_require_setup(app, tmp_path, monkeypatch, capsys, command):
    from brickwork.web import cli
    monkeypatch.setattr(cli, 'application_context', lambda operation: app.app_context())
    before = snapshot(tmp_path)
    code = cli.main(command)
    error = capsys.readouterr().err
    if command in (['catalogue', 'status'], ['sources', 'status']):
        assert code == 0  # reads the rebuildable index or the environment only
    else:
        assert code == 1 and error.startswith('Web error: ')
    assert snapshot(tmp_path) == before
    assert not (tmp_path / 'brickwork.db').exists()


@pytest.mark.parametrize('command', READ_COMMANDS)
def test_cli_reads_wal_database_without_writes(app, tmp_path, monkeypatch, command):
    from contextlib import closing
    from brickwork.web import cli
    from brickwork.core.connect import connect
    assert ops.setup()['setup'] == 'ok'
    with closing(connect(ops.brickwork_path())) as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before = snapshot(tmp_path)
    statements = []
    original = sqlite3.connect

    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, 'connect', traced)
    monkeypatch.setattr(cli, 'application_context', lambda operation: app.app_context())
    assert cli.main(['--json', *command]) == 0
    assert snapshot(tmp_path) == before
    assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP'))
                   for s in statements)


def test_source_admin_commands(app, tmp_path, monkeypatch):
    from brickwork.core.sources import base
    from brickwork.core.connect import connect
    before = snapshot(tmp_path)
    status = ops.sources_status()
    assert status['bricklink']['used_today'] == 0
    assert status['brickset']['key'] in ('set', 'unset')
    assert ops.catalogue_status()['bricklink']['available'] is False
    assert snapshot(tmp_path) == before
    loaded = ops.catalogue_import_bricklink('tests/fixtures/brickwork')
    assert len(loaded['counts']) == 8
    assert ops.catalogue_status()['bricklink']['available'] is True
    for key in ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET'):
        monkeypatch.setenv('BW_BRICKLINK_' + key, 'test-secret-' + key)
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    monkeypatch.setattr(base, 'transport', lambda _: {'meta': {'code': 200}, 'data':
        {'total_quantity': 2, 'qty_avg_price': '100', 'min_price': '90', 'max_price': '110'}})
    assert ops.prices_refresh('123-1')['ok']
    assert ops.sources_status()['bricklink']['used_today'] == 2
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'test-secret-brickset')
    monkeypatch.setattr(base, 'transport', lambda _: json.loads(
        Path('tests/fixtures/brickwork/brickset.json').read_text()))
    assert ops.brickset_refresh(['123-1']) == {'sets': ['123-1'], 'state': 'done'}
    assert ops.settings_set('retail_country', 'US') == {'retail_country': 'US'}
    with connect(ops.brickwork_path()) as db:
        assert db.execute("SELECT value FROM settings WHERE key='retail_country'").fetchone()[0] == 'US'


def test_import_priority_admin_service(app, tmp_path, monkeypatch):
    from brickwork.core.pipeline import STEPS
    from brickwork.core.importer.projection import PRIORITY
    assert ops.settings_set('source_priority', json.dumps(PRIORITY)) == {'source_priority': PRIORITY}
    order = list(reversed(STEPS))
    assert ops.settings_set('import_order:P', json.dumps(order)) == {'import_order:P': order}
    with pytest.raises(ValueError):
        ops.settings_set('import_order:P', '["identity"]')
    with pytest.raises(ValueError):
        ops.settings_set('source_priority', '[]')
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-private')
    assert ops.sources_status()['rebrickable']['key'] == 'set'
    assert ops.jobs_list() == []


def test_bad_price_settings_reads_and_save(app):
    from contextlib import closing
    from brickwork.core.connect import connect
    from brickwork.core.price_settings import DEFAULTS
    with closing(connect(ops.brickwork_path())) as db, db:
        db.execute("INSERT INTO settings VALUES('incomplete_discount_pct',NULL)")
        db.execute("INSERT INTO settings VALUES('repair_use_loose_stock','invalid')")
    assert ops.settings_show() == DEFAULTS
    assert ops.settings_set('incomplete_discount_pct', '40')['incomplete_discount_pct'] == 40
