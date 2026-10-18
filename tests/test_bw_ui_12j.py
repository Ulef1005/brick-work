"""UI-12j: first run without keys, and actions that name the key they need."""
from contextlib import closing

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import secrets
from brickwork.core.connect import connect
from tests.test_bw_admin import bw
from tests.test_bw_api_m5_web import BL_ENV, fake
from tests.web_fixtures import app, apps, logged_in


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in ('BW_BRICKSET_API_KEY', 'BW_REBRICKABLE_API_KEY', *BL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    secrets.forget()


@pytest.fixture
def empty(app, tmp_path, monkeypatch):
    path = tmp_path / 'brickwork.db'
    monkeypatch.setenv('BW_DB_PATH', str(path))
    connect(path).close()
    return app


def soup(client, route):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def steps(page):
    return {li['data-step']: li for li in page.select('[data-first-run] .fr-step')}


def test_first_run_shows_three_steps_and_only_the_first_is_active(empty):
    page = soup(logged_in(empty), '/collection/sets')
    assert page.h1.get_text(strip=True) == 'Sets'
    assert '0 sets' in page.select_one('.bc-heading .secondary').get_text()
    assert page.select_one('[data-first-run] h2').get_text() == 'Nothing here yet.'
    found = steps(page)
    assert [found[k]['data-state'] for k in '123'] == ['current', 'waiting', 'waiting']
    first = found['1'].find('a')
    assert first.get_text(strip=True) == 'Catalogues & keys' and first['href'] == '/manage/catalogues'
    for k in '23':
        button = found[k].find('button')
        assert button.has_attr('disabled') and not found[k].find('a')
    assert 'without keys' in page.select_one('.fr-note').get_text()
    assert page.select_one('[data-bc-list]').has_attr('hidden')


def test_first_run_unlocks_step_two_once_a_key_is_stored(empty, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    found = steps(soup(logged_in(empty), '/collection/sets'))
    assert [found[k]['data-state'] for k in '123'] == ['done', 'current', 'waiting']
    assert found['2'].find('a')['href'] == '/manage/catalogues#catalogues'
    assert found['3'].find('button').has_attr('disabled')


def test_first_run_unlocks_add_once_catalogue_is_loaded(empty, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    monkeypatch.setattr('brickwork.web.setup_state.catalogue_loaded', lambda: True)
    found = steps(soup(logged_in(empty), '/collection/sets'))
    assert [found[k]['data-state'] for k in '123'] == ['done', 'done', 'current']
    assert found['3'].find('a')['href'] == '/manage/add'


def test_first_run_never_shows_a_key_value(empty, monkeypatch):
    secret = fake()
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', secret)
    assert secret not in logged_in(empty).get('/collection/sets').get_data(as_text=True)


def test_collection_with_sets_has_no_first_run(app, bw):
    page = soup(logged_in(app), '/collection/sets')
    assert not page.select('[data-first-run]')
    assert not page.select_one('[data-bc-list]').has_attr('hidden')


def test_update_price_names_the_missing_key(app, bw):
    page = soup(logged_in(app), '/collection/item/S/1')
    card = page.select_one('[data-module=prices]')
    button = card.find('button', string='Update price')
    assert button.has_attr('disabled') and not card.find('a', string='Update price')
    note = card.select_one('[data-needs-key=bricklink]')
    assert 'Needs a BrickLink key' in note.get_text()
    assert note.find('a')['href'] == '/manage/catalogues'


def test_update_price_refreshes_this_item_once_the_key_is_set(app, bw, monkeypatch):
    # The bulk page lists stale prices only, so an item never priced showed 0 to refresh there:
    # the button queues a market price refresh for this item instead.
    import json
    for name in BL_ENV:
        monkeypatch.setenv(name, fake())
    card = soup(logged_in(app), '/collection/item/S/1').select_one('[data-module=prices]')
    button = card.find('button', string='Update price')
    assert json.loads(button['data-bc-fetch-prices']) == [['S', '1']]
    assert button['data-refresh-url'] == '/planning/action/refresh' and not button.has_attr('disabled')
    assert card.select_one('[data-bc-fetch-status][role=status]')
    assert not card.select('[data-needs-key]')


def test_bulk_refresh_and_load_colours_name_the_key(app, bw):
    client = logged_in(app)
    refresh = soup(client, '/manage/refresh')
    assert 'Needs a BrickLink key' in refresh.select_one('[data-needs-key=bricklink]').get_text()
    assert refresh.find('button', string=lambda t: t and t.startswith('Refresh all')).has_attr('disabled')
    catalogues = soup(client, '/manage/catalogues')
    assert catalogues.find('button', string='Load colours').has_attr('disabled')
    assert catalogues.select_one('[data-needs-key=bricklink]').find('a')['href'] == '/manage/catalogues'
    assert catalogues.find('button', string='Load catalogue') and not catalogues.find('button', string='Load catalogue').has_attr('disabled')
