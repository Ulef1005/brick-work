"""UI-12j on the Tools & Admin screens (bulk refresh and Catalogues & keys name the key they need): split out of test_bw_ui_12j.py by M.8f, waiting for M.8i.

3.3 form."""
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import secrets
from tests.test_bw_admin import bw
from tests.web_fixtures import app, apps, logged_in

BL_ENV = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in ('BW_BRICKSET_API_KEY', 'BW_REBRICKABLE_API_KEY', *BL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    secrets.forget()


def soup(client, route):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def test_bulk_refresh_and_load_colours_name_the_key(app, bw):
    client = logged_in(app)
    refresh = soup(client, '/manage/refresh')
    assert 'Needs a BrickLink key' in refresh.select_one('[data-needs-key=bricklink]').get_text()
    assert refresh.find('button', string=lambda t: t and t.startswith('Refresh all')).has_attr('disabled')
    catalogues = soup(client, '/manage/catalogues')
    assert catalogues.find('button', string='Load colours').has_attr('disabled')
    assert catalogues.select_one('[data-needs-key=bricklink]').find('a')['href'] == '/manage/catalogues'
    assert catalogues.find('button', string='Load catalogue') and not catalogues.find('button', string='Load catalogue').has_attr('disabled')
