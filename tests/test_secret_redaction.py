"""Environment credentials stay private regardless of their variable prefix (4.0 store, M.8f).

The CLI error text and the export are the maintenance piece's (test_secret_redaction_cli_export.py, M.8i)."""
import pytest

from brickwork.core.secrets import secret_values
from brickwork.core.sources import base
from tests.app4 import coll, pair  # noqa: F401 (fixtures)
from tests.sources4 import Net, keyed, price_reply


@pytest.fixture(params=['OLD_REBRICKABLE_API_KEY', 'OTHER_SECRET', 'CUSTOM_TOKEN',
                        'LEGACY_PASSWORD', 'OLD_API_KEY', 'BW_API_KEY'])
def credential(request, monkeypatch):
    value = 'synthetic-credential-for-redaction'
    monkeypatch.setenv(request.param, value)
    monkeypatch.setenv('OLD_DISPLAY_NAME', 'ordinary-display-name')
    monkeypatch.setenv('OLD_EMPTY_KEY', '')
    return value


@pytest.mark.parametrize('value, expected', [
    ('1', []),
    ('1234567', []),
    ('12345678', ['12345678']),
])
def test_secret_values_minimum_length(value, expected):
    assert secret_values({'SOME_KEY': value}) == expected


def test_source_audit_redacts_arbitrary_prefix(coll, credential):
    base.write(coll.db, 'INSERT INTO setting(key, value) VALUES(?, ?)', ('note', credential + ' ordinary-display-name'))
    audit = coll.db.execute("SELECT new_value FROM event WHERE entity_kind='source'").fetchone()[0]
    assert credential not in audit
    assert '[set] ordinary-display-name' in audit


def test_a_kept_reply_and_a_source_error_redact_arbitrary_prefix(coll, credential, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    reply = price_reply()
    reply['data']['note'] = credential + ' ordinary-display-name'
    from brickwork.core.sources.bricklink import BrickLink
    BrickLink(coll.db, http=Net(reply)).price(coll.item('sets', '1000-1'), None, 'used')
    kept = coll.db.execute('SELECT payload FROM source_record').fetchone()[0]
    assert credential not in kept and '[set] ordinary-display-name' in kept
    assert base.redact('x ' + credential) == 'x [set]'
