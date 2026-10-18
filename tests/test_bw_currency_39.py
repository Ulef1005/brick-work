"""#39 currency conversion for display and totals; stored amounts never change. Invented data."""
from contextlib import closing
from decimal import Decimal
import os

from bs4 import BeautifulSoup
import pytest

from brickwork.core import currency, errors, planning
from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import apps, logged_in  # noqa: F401

H = {'Authorization': 'Bearer synthetic-bootstrap'}
ECB = '''<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time="2026-10-16"><Cube currency="USD" rate="1.1700"/><Cube currency="GBP" rate="0.8600"/><Cube currency="JPY" rate="nope"/></Cube></Cube></gesmes:Envelope>'''


def store():
    return closing(connect(os.environ['BW_DB_PATH']))


def test_convert_rules():
    table = {'EUR': dict(per_eur=Decimal(1), as_of=None), 'USD': dict(per_eur=Decimal('1.17'), as_of='2026-10-16'),
             'GBP': dict(per_eur=Decimal('0.86'), as_of='2026-10-15')}
    assert currency.convert('117', 'USD', 'EUR', table)['amount'] == Decimal('100.00')
    usd_gbp = currency.convert('10', 'USD', 'GBP', table)
    assert usd_gbp['amount'] == Decimal('7.35') and usd_gbp['as_of'] == '2026-10-15' and usd_gbp['converted']
    assert currency.convert('5', 'EUR', 'EUR', table)['converted'] is False
    assert currency.convert('5', 'CHF', 'EUR', table) is None and currency.convert('x', 'USD', 'EUR', table) is None


def test_rates_ecb_manual_and_display(populated):
    with store() as db:
        assert currency.listing(db) == []
        currency.set_rate(db, 'gbp', '0.85')
        result = currency.fetch_ecb(db, http=lambda request: ECB)
        assert result == dict(as_of='2026-10-16', updated=1, kept_manual=1)
        rates = {r['currency']: r for r in currency.listing(db)}
        assert rates['USD']['source'] == 'ecb' and rates['GBP'] == dict(currency='GBP', per_eur='0.85', as_of=rates['GBP']['as_of'], source='manual')
        with pytest.raises(errors.ValidationFailed):
            currency.set_rate(db, 'EUR', '1')
        with pytest.raises(errors.ValidationFailed):
            currency.set_rate(db, 'USD', '-1')
        with pytest.raises(errors.SourceError):
            currency.fetch_ecb(db, http=lambda request: '<x/>')
        currency.set_rate(db, 'GBP', None)
        assert 'GBP' not in {r['currency'] for r in currency.listing(db)}
        assert currency.set_display(db, 'usd') == 'USD' and currency.display_currency(db) == 'USD'


def test_under_max_across_currencies(populated):
    with store() as db:
        with db:
            db.execute("UPDATE wishlist SET max_price='5.00',max_price_currency='USD' WHERE id=1")
        wish = next(r for r in planning.wishes(db) if r['id'] == 1)
        assert wish['max_state'] == 'differs'  # no rate yet: never compared
        currency.set_rate(db, 'USD', '1.17')
        wish = next(r for r in planning.wishes(db) if r['id'] == 1)
        assert wish['max_state'] == 'under' and wish['max_conversion']['currency'] == 'USD'
        assert Decimal(wish['max_conversion']['amount']) == (Decimal(wish['display_price']['price']) * Decimal('1.17')).quantize(Decimal('0.01'), 'ROUND_HALF_UP')
        stored = db.execute('SELECT max_price,max_price_currency FROM wishlist WHERE id=1').fetchone()
        assert tuple(stored) == ('5.00', 'USD')


def test_api_rates_and_settings(populated):
    c = populated.test_client()
    put = c.put('/api/v1/exchange-rates/usd', json={'per_eur': '1.17'}, headers=dict(H, **{'Idempotency-Key': 'fx-1'}))
    assert put.status_code == 200, put.json
    listed = c.get('/api/v1/exchange-rates', headers=H).json
    assert listed['data'][0]['currency'] == 'USD' and listed['display_currency']
    patched = c.patch('/api/v1/settings', json={'display_currency': 'USD'}, headers=dict(H, **{'Idempotency-Key': 'fx-2'}))
    assert patched.status_code == 200 and patched.json['data']['display_currency'] == 'USD'
    assert c.put('/api/v1/exchange-rates/EUR', json={'per_eur': '1'}, headers=dict(H, **{'Idempotency-Key': 'fx-3'})).status_code == 422



def test_settings_page_and_converted_saving(bw, apps, monkeypatch):
    from datetime import datetime, timezone
    from brickwork.core import retail
    from brickwork.core.sources.base import observation, property_value
    monkeypatch.setattr(retail, 'now', lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
    with closing(connect(bw)) as db:
        with db:
            observation(db, 'brickset', 'S', 'new-set', guide='retail', price='100.00', currency='EUR', region='DE', slot='retail')
            property_value(db, 'brickset', 'S', 'new-set', 'dateLastAvailable', '2027-12-31T00:00:00Z')
            db.execute("UPDATE copies SET purchase_price='93.60',purchase_currency='USD' WHERE id='copy'")
    client = logged_in(apps('toni'))
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    section = page.select_one('#currencies')
    assert section.select_one('input[name=display_currency]') and 'No rates yet' in section.get_text()
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    response = client.post('/manage/settings', data={'csrf_token': token, 'action': 'rate', 'currency': 'usd', 'per_eur': '1.17'})
    assert response.status_code == 302 and response.location.endswith('#currencies')
    page = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    assert page.select_one('#currencies .bw-rate-code').get_text() == 'USD'
    card = BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data, 'html.parser').select_one('.bc-retail-saving')
    assert 'Paid US$93.60 ≈ €80.00 · 20 % under retail' in ' '.join(card.get_text(' ').split()) or '≈ €80.00' in card.get_text()
    assert 'Converted at' in card['title']
