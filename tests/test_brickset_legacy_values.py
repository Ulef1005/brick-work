"""Brickset's new/used values are 3.3 history (#173): labelled legacy wherever they show; other sources' values are not."""
from brickwork.core import collection, collection_prices
from tests.app4 import app4, client, coll, pair, read  # noqa: F401  (fixtures)
from tests.test_collection_item_page import item_page, put_observations


def test_only_a_brickset_valuation_is_legacy():
    rows = [dict(source='brickset', guide='valuation'), dict(source='bricklink', guide='valuation'), dict(source='brickset', guide='retail'),
            dict(source='manual', guide='manual')]
    rows = [dict(r, condition='new', slot=None, observed_at='2026-10-09', max_age_days=None, price='1', min=None, max=None, sold=None) for r in rows]
    assert [r['legacy'] for r in collection.decorate_prices(rows)] == [True, False, False, False]


def test_the_item_page_labels_the_legacy_value_in_the_records_and_the_estimate(coll, client):
    keep = coll.item('sets', '1000-1')
    cid = coll.add_copy('1000-1')                                       # no estimate of its own
    put_observations(coll, keep, [dict(price='12', observed_at='2026-10-08'),
                                  dict(condition='new', guide='valuation', price='30', observed_at='2026-10-09', source='brickset')])
    card = item_page(client, keep, copy=cid).select_one('[data-module=prices]')
    legacy = [p for p in card.select('.bc-price-records .bc-price') if '30.00' in p.get_text()]
    assert legacy and collection_prices.LEGACY_LABEL in legacy[0].get_text()
    footer = card.select_one('.bc-price-footer').get_text(' ', strip=True)
    assert '30.00' in footer and 'legacy' in footer
    market = [p for p in card.select('.bc-price-records .bc-price') if '12.00' in p.get_text()]
    assert market and 'legacy' not in market[0].get_text()
