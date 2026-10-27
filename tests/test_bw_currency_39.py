"""#39 currency conversion for display and totals; stored amounts never change, on the 4.0 store (M.8g, issue #110). Invented data.

The API routes (M.11) and the Settings page (M.8i) are in test_bw_currency_39_api.py and test_bw_currency_39_settings.py, which wait for them."""
from decimal import Decimal

import pytest

from brickwork.core import currency, errors, planning
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)

ECB = '''<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time="2026-10-16"><Cube currency="USD" rate="1.1700"/><Cube currency="GBP" rate="0.8600"/><Cube currency="JPY" rate="nope"/></Cube></Cube></gesmes:Envelope>'''


def test_convert_rules():
    table = {'EUR': dict(per_eur=Decimal(1), as_of=None), 'USD': dict(per_eur=Decimal('1.17'), as_of='2026-10-16'),
             'GBP': dict(per_eur=Decimal('0.86'), as_of='2026-10-15')}
    assert currency.convert('117', 'USD', 'EUR', table)['amount'] == Decimal('100.00')
    usd_gbp = currency.convert('10', 'USD', 'GBP', table)
    assert usd_gbp['amount'] == Decimal('7.35') and usd_gbp['as_of'] == '2026-10-15' and usd_gbp['converted']
    assert currency.convert('5', 'EUR', 'EUR', table)['converted'] is False
    assert currency.convert('5', 'CHF', 'EUR', table) is None and currency.convert('x', 'USD', 'EUR', table) is None


def test_rates_ecb_manual_and_display(coll):
    db = coll.db
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
    assert currency.rates(db)['USD']['source'] == 'ecb' and currency.rates(db)['EUR']['per_eur'] == 1


def test_rates_and_display_are_audited_events(coll):
    db = coll.db
    currency.set_rate(db, 'chf', '0.95')
    currency.set_display(db, 'chf')
    currency.fetch_ecb(db, http=lambda request: ECB)
    events = [tuple(r) for r in db.execute("SELECT entity_kind, entity_id, field, via FROM event WHERE entity_kind IN ('exchange_rate','setting') ORDER BY id")]
    assert events == [('exchange_rate', 'CHF', 'save', 'app'), ('setting', 'display_currency', 'save', 'app'), ('exchange_rate', None, 'ecb', 'app')]
    assert coll.db.execute("SELECT value FROM setting WHERE key='display_currency'").fetchone()[0] == 'CHF'


def test_the_display_currency_defaults_to_the_bricklink_one(coll):
    assert currency.display_currency(coll.db) == 'EUR'
    coll.setting('bricklink_currency', 'GBP')
    assert currency.display_currency(coll.db) == 'GBP'
    coll.setting('display_currency', 'USD')
    assert currency.display_currency(coll.db) == 'USD'


def test_under_max_across_currencies(coll, read):
    gate = coll.item('sets', '1000-2')
    wish = coll.add_wish(gate, condition='used', max_price='5.00', currency='USD')
    coll.price(gate, '4.00', region='eu', currency='EUR')
    with read() as db:
        row = next(r for r in planning.wishes(db) if r['id'] == wish)
    assert row['max_state'] == 'differs'  # no rate yet: never compared
    currency.set_rate(coll.db, 'USD', '1.17')
    with read() as db:
        row = next(r for r in planning.wishes(db) if r['id'] == wish)
    assert row['max_state'] == 'under' and row['max_conversion']['currency'] == 'USD'
    assert Decimal(row['max_conversion']['amount']) == (Decimal(row['display_price']['price']) * Decimal('1.17')).quantize(Decimal('0.01'), 'ROUND_HALF_UP')
    assert tuple(coll.db.execute('SELECT max_price,max_price_currency FROM wish WHERE id=?', (wish,)).fetchone()) == ('5.00', 'USD')
