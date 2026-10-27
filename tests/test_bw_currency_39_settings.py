"""#39 the Settings page's currencies and the converted saving, on the 4.0 store (M.8i part 1, issue #110). Invented data.

Split out of test_bw_currency_39.py in M.8g; the core (rates, ECB, display) is tested there, the converted saving on the item page in
test_bw_retail_26.py. This is the screen."""
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import pytest

from brickwork.core import currency, retail
from brickwork.core.sources.base import observation, property_value
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)

ECB = '''<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time="2026-10-16"><Cube currency="USD" rate="1.1700"/><Cube currency="GBP" rate="0.8600"/></Cube></Cube></gesmes:Envelope>'''


def test_settings_page_and_converted_saving(client, coll, monkeypatch):
    monkeypatch.setattr(retail, 'now', lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
    keep = coll.item('sets', '1000-1')
    coll.project(keep)
    observation(coll.db, 'brickset', keep, guide='retail', price='100.00', currency='EUR', region='DE', slot='retail')
    property_value(coll.db, 'brickset', keep, 'dateLastAvailable', '2027-12-31T00:00:00Z')
    coll.db.commit()
    copy = coll.add_copy('1000-1', condition='used', price='93.60', currency='USD')
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    section = page.select_one('#currencies')
    assert section.select_one('input[name=display_currency]') and 'No rates yet' in section.get_text()
    token = csrf(client)
    response = client.post('/manage/settings', data={'csrf_token': token, 'action': 'rate', 'currency': 'usd', 'per_eur': '1.17'})
    assert response.status_code == 302 and response.location.endswith('#currencies')
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    assert page.select_one('#currencies .bw-rate-code').get_text() == 'USD'
    card = BeautifulSoup(client.get(f'/collection/item/{keep}?copy={copy}').data, 'html.parser').select_one('.bc-retail-saving')
    assert 'Paid $93.60 ≈ €80.00 · 20 % under retail' in ' '.join(card.get_text(' ').split())
    assert 'Converted at' in card['title']


def test_display_currency_rates_and_ecb_through_the_screen(client, coll, monkeypatch):
    token = csrf(client)
    post = lambda **data: client.post('/manage/settings', data={'csrf_token': token, **data}, follow_redirects=True).get_data(as_text=True)
    assert 'Display currency USD' in post(action='display_currency', display_currency='usd')
    assert currency.display_currency(coll.db) == 'USD'
    assert 'Rate saved' in post(action='rate', currency='GBP', per_eur='0.85')
    assert 'Rate removed' in post(action='rate', currency='GBP', per_eur='')
    monkeypatch.setattr('brickwork.core.sources.base.transport', lambda request: ECB)
    assert 'ECB rates of 2026-10-16 · 2 currencies' in post(action='ecb')
    assert {r['currency'] for r in currency.listing(coll.db)} == {'GBP', 'USD'}
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    assert {r.get_text() for r in page.select('#currencies .bw-rate-code')} == {'GBP', 'USD'}
    assert page.select_one('input[name=display_currency]')['value'] == 'USD'


def test_the_currency_forms_are_closed_on_a_read_only_instance(app4, client, coll):
    token = csrf(client)
    app4.config['BW_READ_ONLY'] = True
    try:
        for data in (dict(action='display_currency', display_currency='USD'), dict(action='rate', currency='USD', per_eur='1.1'), dict(action='ecb')):
            assert client.post('/manage/settings', data={'csrf_token': token, **data}).status_code == 403
        page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
        assert not page.select('#currencies form')
    finally:
        app4.config['BW_READ_ONLY'] = False
    assert currency.listing(coll.db) == []
