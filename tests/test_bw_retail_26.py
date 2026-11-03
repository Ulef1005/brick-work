"""#26 retail price, availability and savings from the Brickset data, on the 4.0 store (M.8f). Invented data.

The Wishlist line and the Statistics screen are the planning (M.8g) and maintenance (M.8i) pieces' (test_bw_retail_26_wishlist.py,
test_bw_retail_26_statistics.py)."""
from datetime import datetime, timezone

from bs4 import BeautifulSoup
import pytest

from brickwork.core import retail
from brickwork.core.sources.base import observation, property_value
from tests.app4 import app4, client, coll, pair, world  # noqa: F401 (fixtures)

TODAY = datetime(2026, 10, 17, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(retail, 'now', lambda: TODAY)
    from brickwork.core import collection
    monkeypatch.setattr(collection, 'now', lambda: TODAY)


def seed(coll, last='2026-12-31', price='79.99', currency='EUR', copy_price='59.99', copy_currency='EUR'):
    """Retail data for the fixture set `1000-1` and its first copy's price paid."""
    keep = coll.item('sets', '1000-1')
    coll.project(keep)
    observation(coll.db, 'brickset', keep, guide='retail', price=price, currency=currency, region='DE', slot='retail')
    property_value(coll.db, 'brickset', keep, 'dateFirstAvailable', '2024-01-01T00:00:00Z')
    property_value(coll.db, 'brickset', keep, 'dateLastAvailable', last + 'T00:00:00Z')
    property_value(coll.db, 'brickset', keep, 'theme', 'Castle')
    coll.db.commit()
    copy = coll.add_copy('1000-1', condition='used', price=copy_price, currency=copy_currency, date='2025-03-01')
    return keep, copy


def test_status_rules_and_saving(coll):
    keep, _ = seed(coll)
    info = retail.lookup(coll.db, [keep])[keep]
    assert (info['price'], info['currency'], info['country'], info['first'], info['status']) == ('79.99', 'EUR', 'DE', '2024-01-01', 'Retiring')
    property_value(coll.db, 'brickset', keep, 'dateLastAvailable', '2026-01-01T00:00:00Z')
    assert retail.lookup(coll.db, [keep])[keep]['status'] == 'Retired'
    property_value(coll.db, 'brickset', keep, 'dateLastAvailable', '2028-01-01T00:00:00Z')
    assert retail.lookup(coll.db, [keep])[keep]['status'] == 'Available'
    assert retail.saving('59.99', 'EUR', info) == dict(pct=25, under=True)
    assert retail.saving('89.99', 'EUR', info) == dict(pct=13, under=False)             # 12.5 % over
    assert retail.saving('59.99', 'USD', info) is None and retail.saving(None, 'EUR', info) is None
    assert retail.lookup(coll.db, []) == {} and retail.lookup(coll.db, [coll.item('sets', '2070-1')]) == {}


def test_the_retail_country_picks_the_price_and_a_voided_price_is_not_shown(coll):
    keep, _ = seed(coll)
    coll.setting('retail_country', 'US')
    assert retail.lookup(coll.db, [keep])[keep].get('price') is None                       # DE was observed, US was not
    coll.setting('retail_country', 'DE')
    coll.sql('UPDATE price_observation SET voided_at=? WHERE item_id=?', ('2026-10-01T00:00:00.000Z', keep))
    assert 'price' not in retail.lookup(coll.db, [keep])[keep]


def test_the_item_page_shows_retail_availability_and_the_saving_of_the_chosen_copy(coll, client):
    keep, copy = seed(coll)
    other = coll.add_copy('1000-1', condition='used', price='50', currency='USD')
    card = BeautifulSoup(client.get(f'/collection/item/{keep}?copy={copy}').data, 'html.parser').select_one('[data-bc-retail]')
    text = ' '.join(card.get_text(' ').split())
    assert 'Retail · DE' in text and '€79.99' in text and 'Available at LEGO 2024-01 to 2026-12' in text
    assert card.select_one('[data-retail-status=retiring]') and 'Paid €59.99 · 25 % under retail' in text
    elsewhere = BeautifulSoup(client.get(f'/collection/item/{keep}?copy={other}').data, 'html.parser').select_one('[data-bc-retail]')
    assert 'not comparable' in elsewhere.get_text()


def test_spent_against_retail_per_currency_year_and_theme(coll):
    keep, copy = seed(coll)
    coll.add_copy('1000-1', condition='used', price='50', currency='USD', date='2025-06-01')          # another currency, no rate: not comparable
    coll.add_copy('1000-1', condition='new')                                                          # no price paid: not counted at all
    stats = retail.spent_vs_retail(coll.db)
    assert stats['totals'][0]['pct'] == 25 and stats['totals'][0]['copies'] == 1 and stats['not_comparable'] == 1
    assert [r['label'] for r in stats['themes']] == ['Castle'] and stats['years'][0]['label'] == '2025' and stats['country'] == 'DE'
    assert stats['overall']['currency'] == 'EUR' and stats['overall']['pct'] == 25 and stats['converted'] == 0


def test_a_rate_makes_another_currency_comparable_and_says_so(coll):
    keep, copy = seed(coll)
    coll.sql("INSERT INTO exchange_rate(currency, per_eur, as_of, source) VALUES('USD', '1.25', '2026-10-16', 'manual')")
    coll.add_copy('1000-1', condition='used', price='110', currency='USD', date='2025-06-01')         # 110 USD = 88 EUR against 79.99 retail
    stats = retail.spent_vs_retail(coll.db)
    assert stats['converted'] == 1 and stats['not_comparable'] == 0 and stats['totals'][0]['copies'] == 2
    rates = {'EUR': dict(per_eur=1, as_of=None), 'USD': dict(per_eur=1.25, as_of='2026-10-16')}
    from decimal import Decimal
    table = {k: dict(v, per_eur=Decimal(str(v['per_eur']))) for k, v in rates.items()}
    saving = retail.saving('110', 'USD', retail.lookup(coll.db, [keep])[keep], table)
    assert saving['converted'] is True and saving['under'] is False and saving['as_of'] == '2026-10-16' and saving['amount'] == '88.00' and saving['pct'] == 10
