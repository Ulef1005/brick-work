"""Environment credentials stay private in the CLI error text and in the export, on the 4.0 store (M.8i part 1, issue #110).

Split out of test_secret_redaction.py by M.8f."""
from contextlib import closing
import sqlite3

from flask import Flask
import pytest

from brickwork.web import admin_ops, cli
from tests.app4 import coll, pair  # noqa: F401  (the fixtures)


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


def test_export_rejects_arbitrary_prefix(coll, pair, monkeypatch, credential):
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    item = coll.local('part', 'ordinary-display-name', born_key='x1')
    # Non-secret environment values and empty credentials do not block exports.
    exported = admin_ops.tools_export()
    with closing(sqlite3.connect(':memory:')) as snapshot:
        snapshot.deserialize(exported)
        assert snapshot.execute('SELECT name FROM item WHERE id=?', (item,)).fetchone()[0] == 'ordinary-display-name'
    coll.sql('UPDATE item SET name=? WHERE id=?', (credential, item))
    with pytest.raises(ValueError, match='Export contains credential material'):
        admin_ops.tools_export()
