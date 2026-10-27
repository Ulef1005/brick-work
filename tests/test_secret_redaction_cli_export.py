"""Environment credentials stay private in the CLI error text and in the export: split out of test_secret_redaction.py by M.8f, waiting for M.8i.

3.3 form; the export and the CLI are the maintenance piece's (M.8i), which rewrites these on the 4.0 store."""
from contextlib import closing
import sqlite3

from flask import Flask
import pytest

from brickwork.core.connect import connect
from brickwork.web import admin_ops, cli


@pytest.fixture(params=['OLD_REBRICKABLE_API_KEY', 'OTHER_SECRET', 'CUSTOM_TOKEN',
                        'LEGACY_PASSWORD', 'OLD_API_KEY', 'BW_API_KEY'])
def credential(request, monkeypatch):
    value = 'synthetic-credential-for-redaction'
    monkeypatch.setenv(request.param, value)
    monkeypatch.setenv('OLD_DISPLAY_NAME', 'ordinary-display-name')
    monkeypatch.setenv('OLD_EMPTY_KEY', '')
    return value


def test_cli_error_redacts_arbitrary_prefix(credential):
    app = Flask(__name__)
    app.config['CUSTOM_PASSWORD'] = 'synthetic-config-password'
    with app.app_context():
        result = cli._safe_error(ValueError(
            credential + ' ordinary-display-name synthetic-config-password'))
    assert result == '[set] ordinary-display-name [set]'


def test_export_rejects_arbitrary_prefix(tmp_path, monkeypatch, credential):
    path = tmp_path / 'brickwork.db'
    monkeypatch.setenv('BW_DB_PATH', str(path))
    with closing(connect(path)) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','1',?)",
                   ('ordinary-display-name',))
    # Non-secret environment values and empty credentials do not block exports.
    exported = admin_ops.tools_export()
    with closing(sqlite3.connect(':memory:')) as snapshot:
        snapshot.deserialize(exported)
        assert snapshot.execute('SELECT name FROM items').fetchone()[0] == 'ordinary-display-name'
    with closing(connect(path)) as db, db:
        db.execute('UPDATE items SET name=?', (credential,))
    with pytest.raises(ValueError, match='Export contains credential material'):
        admin_ops.tools_export()
