"""API v2 writes on prices and settings (M.11c, issue #113): manual observations (one and a batch) and the whitelisted settings. Ported from
test_bw_api_m4 (the price cases), test_bw_currency_39_api (the settings half; the exchange rates are M.11d) and test_bw_wish_progress_35_api onto the
4.0 fixtures. Every answer is validated against `openapi-v2.yaml`. Invented data."""
from contextlib import closing
import json

import pytest

from brickwork.core.connect import connect
from tests.api2 import call, events, row, rows, stored_token, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import table_digest

RED = 5                                                      # the BrickLink number of the fixture's red


def digest(pair):
    with closing(connect(pair)) as db:
        return table_digest(db, skip=('event', 'event_undo', 'item_merge', 'stock_transfer'))


def price(v2, world, amount='1.25', **fields):
    body = {'color': world.red, 'condition': 'used', 'guide': 'manual', 'slot': 'estimate', 'price': amount, 'currency': 'EUR'}
    body.update(fields)
    return write(v2, f'/items/{world.brick}/prices', body=body)


# ---------- one observation ----------

def test_a_manual_price_is_recorded_for_an_item_and_colour_and_read_back(v2, world, pair):
    response = price(v2, world, observed_at='2026-10-01T10:00:00+00:00')
    validate(response, 'post_items_by_id_prices', '201')
    observation = response.json['data']
    assert (observation['price'], observation['currency'], observation['guide'], observation['source'], observation['slot'], observation['color']['id']) == (
        '1.25', 'EUR', 'manual', 'manual', 'estimate', world.red)
    assert observation['item']['id'] == world.brick and observation['observed_at'] == '2026-10-01T10:00:00+00:00'
    current = call(v2, f'/items/{world.brick}/prices').json['data']['current']
    assert any(c['observation']['id'] == observation['id'] for c in current)
    assert (events(pair, 'id=?', (response.json['event_id'],))[0]['entity_kind']) == 'manual_prices'


def test_undoing_a_price_makes_the_latest_remaining_one_current_by_the_full_key(v2, world, pair):
    first, second = price(v2, world, '1.25'), price(v2, world, '2.50')
    third = price(v2, world, '3.75', currency='USD')
    assert first.status_code == second.status_code == third.status_code == 201
    assert write(v2, f"/events/{second.json['event_id']}/undo").status_code == 200
    current = rows(pair, "SELECT currency, observation_id FROM main.price_current WHERE guide='manual'")
    assert {r['currency']: r['observation_id'] for r in current} == {'EUR': first.json['data']['id'], 'USD': third.json['data']['id']}
    assert write(v2, f"/events/{first.json['event_id']}/undo").status_code == 200
    assert [r['currency'] for r in rows(pair, "SELECT currency FROM main.price_current WHERE guide='manual'")] == ['USD']
    assert len(rows(pair, "SELECT id FROM main.price_observation WHERE source='manual'")) == 3                                  # voided, never deleted
    assert call(v2, f'/items/{world.brick}/prices/history?limit=200').json['data'] and all(
        o['id'] != first.json['data']['id'] for o in call(v2, f'/items/{world.brick}/prices/history').json['data'])


def test_a_price_is_checked_before_it_is_kept(v2, world, pair):
    before = digest(pair)
    for fields in ({'price': '-1.00'}, {'price': 'abc'}, {'price': '1,5'}, {'currency': 'euro'}, {'condition': 'broken'}, {'guide': 'sold'}, {'color': None},
                   {'color': 99999}, {'observed_at': 'yesterday'}, {'observed_at': '2026-10-01T10:00:00'}):
        assert price(v2, world, **fields).status_code == 422, fields
    assert write(v2, f'/items/{world.keep}/prices', body={'color': world.red, 'condition': 'used', 'guide': 'manual', 'price': '1.00', 'currency': 'EUR'}).status_code == 422  # a set has no colour
    assert write(v2, '/items/987654321/prices', body={'condition': 'used', 'guide': 'manual', 'price': '1.00', 'currency': 'EUR'}).status_code == 404
    assert write(v2, f'/items/{world.brick}/prices', body={'condition': 'used', 'guide': 'manual', 'price': '1.00', 'currency': 'EUR'}, key=False).status_code == 428
    assert digest(pair) == before


def test_a_price_of_a_merged_item_is_409_merged(v2, coll, world):
    loser = coll.local('part', 'Doubled part', born_key='x1')
    assert write(v2, f'/items/{loser}/merge', body={'survivor': {'id': world.brick}}).status_code == 200
    refused = write(v2, f'/items/{loser}/prices', body={'color': world.red, 'condition': 'used', 'guide': 'manual', 'price': '1.00', 'currency': 'EUR'})
    assert refused.status_code == 409 and refused.json['code'] == 'merged' and refused.json['survivor'] == world.brick


# ---------- a batch ----------

def batch_item(**fields):
    item = {'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'condition': 'used', 'guide': 'manual', 'price': '1.00', 'currency': 'EUR'}
    item.update(fields)
    return item


def test_a_batch_is_one_receipt_in_one_transaction_and_one_undo_voids_it_all(v2, world, pair):
    response = write(v2, '/prices/observations', body={'items': [batch_item(), batch_item(price='2.00'), batch_item(item={'id': world.plate}, color=1)]})
    validate(response, 'post_prices_observations')
    assert response.json['data'] == {'applied': 3, 'skipped': [], 'dry_run': False, 'event_id': response.json['event_id']}
    assert len(rows(pair, "SELECT id FROM main.price_observation WHERE source='manual'")) == 3
    assert write(v2, f"/events/{response.json['event_id']}/undo").status_code == 200
    assert not rows(pair, "SELECT * FROM main.price_current WHERE guide='manual'")
    assert len(rows(pair, "SELECT id FROM main.price_observation WHERE source='manual' AND voided_at IS NOT NULL")) == 3


def test_a_batch_that_fails_halfway_writes_nothing(v2, world, pair):
    before, count = digest(pair), len(events(pair))
    failing = write(v2, '/prices/observations', body={'items': [batch_item(), batch_item(color=99999)]})
    assert failing.status_code == 422
    assert write(v2, '/prices/observations', body={'items': [batch_item(), batch_item(item={'kind': 'part', 'key': 'nothing'})]}).json['code'] == 'unidentified'
    assert write(v2, '/prices/observations', body={'items': [batch_item()] * 501}).status_code == 422
    assert write(v2, '/prices/observations', body={'items': []}).status_code == 422
    assert write(v2, '/prices/observations', body={'items': [batch_item()]}, key=False).status_code == 428
    assert digest(pair) == before and len(events(pair)) == count


# ---------- settings ----------

def seeded(coll):
    from brickwork.core import admin
    admin.seed_freshness(coll.db)
    coll.db.commit()


def test_the_settings_read_back_what_the_screens_show(v2, coll, world, pair):
    seeded(coll)
    response = call(v2, '/settings')
    validate(response, 'get_settings')
    settings = response.json['data']
    assert (settings['retail_country'], settings['display_currency'], settings['bricklink_region'], settings['bricklink_currency'], settings['incomplete_discount_pct']) == (
        'DE', 'EUR', 'eu', 'EUR', 30)
    assert settings['prefer_bricklink_inventory'] is False
    assert settings['repair'] == {'shipping': '3.00', 'fees': '0.50', 'min_order': '0', 'use_loose_stock': False}
    assert settings['source_priority']['pictures']['part'] == ['rebrickable_dump', 'bricklink', 'rebrickable_api']
    assert {'source': 'bricklink', 'kind': 'prices', 'max_age_days': 30} in settings['freshness']
    assert call(v2, '/settings', token=stored_token(pair, ['read'])).status_code == 200


def test_settings_change_by_whitelist_in_one_event_and_undo_puts_them_back(v2, world, pair):
    before = digest(pair)
    changed = write(v2, '/settings', 'patch', {'retail_country': 'US', 'incomplete_discount_pct': 25, 'display_currency': 'USD',
                                              'repair': {'shipping': '4.50', 'use_loose_stock': True}})
    validate(changed, 'patch_settings')
    data = changed.json['data']
    assert (data['retail_country'], data['incomplete_discount_pct'], data['display_currency'], data['repair']['shipping'], data['repair']['use_loose_stock']) == (
        'US', 25, 'USD', '4.50', True)
    assert call(v2, '/settings').json['data'] == data
    assert changed.json['event_id'] and changed.json['undo_url']
    assert write(v2, f"/events/{changed.json['event_id']}/undo").status_code == 200
    assert call(v2, '/settings').json['data']['retail_country'] == 'DE'


def test_the_picture_order_and_the_freshness_rules_are_settings(v2, coll, world):
    seeded(coll)
    order = {'pictures': {'part': ['bricklink', 'rebrickable_dump'], '*': ['bricklink']}}
    changed = write(v2, '/settings', 'patch', {'source_priority': order})
    validate(changed, 'patch_settings')
    assert changed.json['data']['source_priority']['pictures'] == order['pictures']
    assert changed.json['data']['source_priority']['metadata'] == {'set': ['brickset']}                          # a step left out keeps its order
    rules = changed.json['data']['freshness']
    edited = [dict(r, max_age_days=7) if (r['source'], r['kind']) == ('bricklink', 'prices') else r for r in rules]
    after = write(v2, '/settings', 'patch', {'freshness': edited}).json['data']['freshness']
    assert [r['max_age_days'] for r in after if (r['source'], r['kind']) == ('bricklink', 'prices')] == [7]
    for bad in ({'source_priority': {'pictures': {'part': []}}}, {'source_priority': {'nowhere': {'part': ['bricklink']}}},
                {'source_priority': {'pictures': {'part': ['nosuchsource']}}}, {'source_priority': {'pictures': {'sock': ['bricklink']}}}):
        assert write(v2, '/settings', 'patch', bad).status_code == 422, bad


def test_the_bricklink_part_list_preference_is_a_setting_with_its_own_event(v2, world, pair):
    on = write(v2, '/settings', 'patch', {'prefer_bricklink_inventory': True})
    validate(on, 'patch_settings')
    assert on.json['data']['prefer_bricklink_inventory'] is True
    assert row(pair, "SELECT value FROM main.setting WHERE key='prefer_bricklink_inventory'") == {'value': 'true'}
    event = events(pair, 'id=?', (on.json['event_id'],))[0]
    assert (event['entity_kind'], event['entity_id'], event['field'], event['via'], event['actor']) == ('setting', 'prefer_bricklink_inventory', 'value', 'api', 'bootstrap')
    off = write(v2, '/settings', 'patch', {'prefer_bricklink_inventory': False})
    assert off.json['data']['prefer_bricklink_inventory'] is False and row(pair, "SELECT value FROM main.setting WHERE key='prefer_bricklink_inventory'") is None
    assert write(v2, '/settings', 'patch', {'prefer_bricklink_inventory': 'yes'}).status_code == 422


def test_a_setting_that_is_already_so_changes_nothing_and_says_so(v2, world, pair):
    count = len(events(pair))
    same = write(v2, '/settings', 'patch', {'retail_country': 'DE'})
    validate(same, 'patch_settings')
    assert same.json['event_id'] is None and 'undo_url' not in same.json
    assert [e for e in events(pair, 'id>?', (count,)) if e['entity_kind'] != 'bw_api'] == []


def test_a_setting_outside_the_whitelist_or_out_of_range_is_refused(v2, world, pair):
    before = digest(pair)
    unsupported = write(v2, '/settings', 'patch', {'bricklink_key': 'secret'})
    assert unsupported.status_code == 422 and unsupported.json['code'] == 'unsupported_setting'
    for bad in ({}, {'retail_country': 'FR'}, {'incomplete_discount_pct': 120}, {'incomplete_discount_pct': 'ten'}, {'repair': {'shipping': '-1'}},
                {'repair': {'colour': 'red'}}, {'bricklink_currency': 'eur'}, {'display_currency': 'not a code'}, {'freshness': [{'source': 'nowhere', 'kind': 'prices', 'max_age_days': 1}]}):
        assert write(v2, '/settings', 'patch', bad).status_code == 422, bad
    assert digest(pair) == before


def test_changing_settings_needs_the_admin_scope(v2, pair):
    writer = stored_token(pair, ['read', 'write'], 'writer')
    assert write(v2, '/settings', 'patch', {'retail_country': 'US'}, token=writer).status_code == 403
    assert call(v2, '/settings', token=writer).status_code == 200
