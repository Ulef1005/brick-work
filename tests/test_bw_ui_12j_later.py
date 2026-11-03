"""UI-12j on the Tools & Admin screens (bulk refresh names the key it needs; Catalogues & keys has nothing to load that needs one), on the 4.0 store
(M.8i part 1, issue #110)."""
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import secrets
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

BL_ENV = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in ('BW_BRICKSET_API_KEY', 'BW_REBRICKABLE_API_KEY', *BL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    secrets.forget()
    yield
    secrets.forget()


def soup(client, route):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def test_bulk_refresh_names_the_key(client, world):
    refresh = soup(client, '/manage/refresh')
    assert 'Needs a BrickLink key' in refresh.select_one('[data-needs-key=bricklink]').get_text()
    assert refresh.find('button', string=lambda t: t and t.startswith('Refresh all')).has_attr('disabled')
    assert refresh.select_one('[data-needs-key=bricklink]').find('a')['href'] == '/manage/catalogues'


def test_bulk_refresh_is_enabled_with_a_key(client, world, monkeypatch):
    for name in BL_ENV:
        monkeypatch.setenv(name, 'synthetic-value-123')
    refresh = soup(client, '/manage/refresh')
    assert not refresh.select('[data-needs-key]')
    assert not refresh.find('button', string=lambda t: t and t.startswith('Refresh all')).has_attr('disabled')


def test_catalogues_page_loads_nothing_from_bricklink(client, world):
    """The colours and names come with the catalogue builds, not from a call: no button there waits for a key."""
    catalogues = soup(client, '/manage/catalogues')
    assert not catalogues.find('button', string='Load colours') and not catalogues.select('[data-needs-key]')
