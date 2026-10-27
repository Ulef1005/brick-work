"""UI-12j on the 4.0 store (M.8f): first run without keys, and the item page's price action naming the key it needs.

The bulk refresh and Catalogues & keys screens are M.8i's (test_bw_ui_12j_later.py)."""
import json

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import secrets
from tests.app4 import app4, client, coll, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import BRICKLINK_KEYS, unkeyed


def fake():
    import secrets as token_source
    return token_source.token_hex(14)


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr('brickwork.web.setup_state.catalogue_loaded', lambda: False)        # the fixture pair has its catalogue; first run is without one
    secrets.forget()


def soup(client, route):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def steps(page):
    return {li['data-step']: li for li in page.select('[data-first-run] .fr-step')}


def test_first_run_shows_three_steps_and_only_the_first_is_active(client):
    page = soup(client, '/collection/sets')
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


def test_first_run_unlocks_step_two_once_a_key_is_stored(client, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    found = steps(soup(client, '/collection/sets'))
    assert [found[k]['data-state'] for k in '123'] == ['done', 'current', 'waiting']
    assert found['2'].find('a')['href'] == '/manage/catalogues#catalogues'
    assert found['3'].find('button').has_attr('disabled')


def test_a_key_in_the_encrypted_store_counts_like_one_in_the_environment(client, coll):
    from brickwork.core import keys
    keys.save(coll.db, 'rebrickable', {'key': fake()})
    found = steps(soup(client, '/collection/sets'))
    assert [found[k]['data-state'] for k in '123'] == ['done', 'current', 'waiting']


def test_first_run_unlocks_add_once_catalogue_is_loaded(client, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    monkeypatch.setattr('brickwork.web.setup_state.catalogue_loaded', lambda: True)
    found = steps(soup(client, '/collection/sets'))
    assert [found[k]['data-state'] for k in '123'] == ['done', 'done', 'current']
    assert found['3'].find('a')['href'] == '/manage/add'


def test_first_run_never_shows_a_key_value(client, monkeypatch):
    secret = fake()
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', secret)
    assert secret not in client.get('/collection/sets').get_data(as_text=True)


def test_collection_with_sets_has_no_first_run(world, client):
    page = soup(client, '/collection/sets')
    assert not page.select('[data-first-run]')
    assert not page.select_one('[data-bc-list]').has_attr('hidden')


def test_update_price_names_the_missing_key(world, client):
    page = soup(client, f'/collection/item/{world.keep}')
    card = page.select_one('[data-module=prices]')
    button = card.find('button', string='Update price')
    assert button.has_attr('disabled') and not card.find('a', string='Update price')
    note = card.select_one('[data-needs-key=bricklink]')
    assert 'Needs a BrickLink key' in note.get_text()
    assert note.find('a')['href'] == '/manage/catalogues'


def test_update_price_refreshes_this_item_once_the_key_is_set(world, client, monkeypatch):
    # The bulk page lists stale prices only, so an item never priced showed 0 to refresh there:
    # the button queues a market price refresh for this item instead.
    for name in BRICKLINK_KEYS:
        monkeypatch.setenv(name, fake())
    card = soup(client, f'/collection/item/{world.keep}').select_one('[data-module=prices]')
    button = card.find('button', string='Update price')
    assert json.loads(button['data-bc-fetch-prices']) == [world.keep]
    assert button['data-refresh-url'] == '/planning/action/refresh' and not button.has_attr('disabled')
    assert card.select_one('[data-bc-fetch-status][role=status]')
    assert not card.select('[data-needs-key]')


def test_the_update_price_button_queues_a_job_for_the_item_it_names(world, client, coll, monkeypatch):
    for name in BRICKLINK_KEYS:
        monkeypatch.setenv(name, fake())
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', lambda: None)
    from tests.app4 import csrf
    response = client.post('/planning/action/refresh', json=dict(csrf_token=csrf(client), items=[world.keep]))
    job = response.get_json()['jobs'][0]
    assert coll.db.execute('SELECT item_id, state FROM job WHERE id=?', (job,)).fetchone()[:] == (world.keep, 'queued')
    assert [r[0] for r in coll.db.execute('SELECT name FROM job_step WHERE job_id=?', (job,))] == ['market_price']
