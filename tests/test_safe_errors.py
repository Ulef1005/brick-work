"""#76: database and OS error text never reaches a response; messages written for people still do."""
import sqlite3

from brickwork.core import planning
from brickwork.web.safe_errors import public
from tests.test_bw_collection import bw  # noqa: F401  (fixture)
from tests.importer.test_importer import legacy  # noqa: F401  (fixture)
from tests.web_fixtures import app, apps, logged_in  # noqa: F401  (fixtures)


def test_public_keeps_user_messages_and_hides_the_rest(caplog):
    assert public(ValueError('Choose a list')) == 'Choose a list'
    caplog.set_level('WARNING', logger='brickwork.web')
    for exc in (sqlite3.OperationalError('no such column: secret_column'), OSError('/srv/data/brickwork.db: denied'),
                KeyError('csrf_token'), TypeError('unsupported operand')):
        assert public(exc, 'Fallback') == 'Fallback'
    assert 'secret_column' in caplog.text  # the detail stays in the server log


def test_a_forced_database_error_does_not_leak(app, bw, monkeypatch):
    client = logged_in(app)
    client.get('/planning/wishlist')
    with client.session_transaction() as session:
        token = session.get('bw_add_csrf')

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError('no such column: secret_column in table wishlist')
    monkeypatch.setattr(planning, 'save', broken)
    response = client.post('/planning/action/save', json={'csrf_token': token})
    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert 'secret_column' not in body and 'wishlist' not in body
    assert response.get_json()['message'] == 'Nothing was saved · review the values and try again'
