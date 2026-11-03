"""The source layer on the 4.0 store (M.8f, issue #110): budgets on `source_budget`, kept replies, BrickLink prices on `provider_key`,
Brickset metadata and retail, the picture cache. Invented data and fake transports only; no network."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from brickwork.core import items
from brickwork.core.sources import base, images
from brickwork.core.sources.bricklink import BrickLink, provider_key, signed_request
from brickwork.core.sources.brickset import Brickset
from brickwork.core.sources.rebrickable import Rebrickable
from tests.app4 import coll, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import Net, Pictures, keyed, png, price_reply, unkeyed


class Clock:
    """A settable UTC clock and a sleep that moves it."""

    def __init__(self, at='2026-10-27T10:00:00+00:00'):
        self.at = datetime.fromisoformat(at)
        self.slept = []

    def __call__(self):
        return self.at

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.at += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)


def used(db, source='bricklink'):
    return [tuple(r) for r in db.execute('SELECT day, used, blocked, blocked_until FROM source_budget WHERE source=? ORDER BY day', (source,))]


def test_oauth_reference():
    # Reference case from the Web API snapshot.
    request = signed_request('/items/SET/6081-1/price', {'guide_type': 'sold', 'new_or_used': 'N'}, ['ck', 'cs', 'tv', 'ts'], timestamp=123, nonce='abc')
    import base64
    import hashlib
    import hmac
    from urllib.parse import quote, unquote
    header = request.get_header('Authorization')
    fields = dict(pair.strip().split('=', 1) for pair in header[6:].split(','))
    signature = unquote(fields.pop('oauth_signature').strip('"'))
    oauth = {k: unquote(v.strip('"')) for k, v in fields.items()}
    params = {'guide_type': 'sold', 'new_or_used': 'N', **oauth}
    q = lambda v: quote(str(v), safe='~')
    normalized = '&'.join(f'{q(k)}={q(v)}' for k, v in sorted(params.items()))
    value = '&'.join(['GET', q('https://api.bricklink.com/api/store/v1/items/SET/6081-1/price'), q(normalized)])
    assert signature == base64.b64encode(hmac.new(b'cs&ts', value.encode(), hashlib.sha1).digest()).decode()


# ---------- budgets, pauses and the kept reply ----------

def test_a_call_is_counted_on_source_budget_and_paced(coll, monkeypatch, clock):
    keyed(monkeypatch, 'bricklink')
    net = Net(price_reply())
    client = BrickLink(coll.db, http=net, sleep=clock.sleep, clock=clock)
    keep = coll.item('sets', '1000-1')
    client.price(keep, None, 'used')                                              # one sold call with a sale
    assert used(coll.db) == [('2026-10-27', 1, 0, None)] and clock.slept == []
    client.price(keep, None, 'new')
    assert used(coll.db)[0][1] == 2 and clock.slept == [1]                        # BrickLink asks one second between calls
    assert coll.db.execute("SELECT last_attempt_at FROM source_budget WHERE source='bricklink'").fetchone()[0].endswith('Z')


def test_the_daily_budget_is_shared_with_the_job_runner_and_waits_for_midnight(coll, monkeypatch, clock):
    keyed(monkeypatch, 'bricklink')
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '3')
    coll.sql("INSERT INTO source_budget(source, day, used) VALUES('bricklink', '2026-10-27', 3)")     # what store4.jobs counted today
    net = Net(price_reply())
    item = coll.item('sets', '1000-1')
    with pytest.raises(base.WaitingForBudget) as wait:
        BrickLink(coll.db, http=net, sleep=clock.sleep, clock=clock).price(item, None, 'used')
    assert wait.value.retry_at == '2026-10-28T00:00:00.000Z' and net.requests == [] and wait.value.code == 'budget_exhausted'
    assert used(coll.db) == [('2026-10-27', 3, 0, None)]
    clock.at = datetime(2026, 10, 28, 0, 0, 1, tzinfo=timezone.utc)                                    # the next UTC day starts fresh
    BrickLink(coll.db, http=net, sleep=clock.sleep, clock=clock).price(item, None, 'used')
    assert used(coll.db)[-1] == ('2026-10-28', 1, 0, None)


@pytest.mark.parametrize('value', ['0', '-1', 'x', '1.5', ''])
def test_an_invalid_budget_setting_is_refused(coll, monkeypatch, value):
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', value)
    with pytest.raises(base.SourceError, match='BW_BRICKLINK_DAILY_BUDGET'):
        BrickLink(coll.db)
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', value)
    with pytest.raises(base.SourceError, match='BW_REBRICKABLE_DAILY_BUDGET'):
        Rebrickable(coll.db)


def test_a_throttle_reply_pauses_the_source_until_the_time_it_names(coll, monkeypatch, clock):
    keyed(monkeypatch, 'rebrickable')
    net = Net({'detail': 'Request was throttled. Expected available in 25 seconds.'}, {'part_img_url': 'https://cdn.rebrickable.com/x.jpg'})
    client = Rebrickable(coll.db, http=net, sleep=clock.sleep, clock=clock)
    with pytest.raises(base.WaitingForBudget) as wait:
        client.picture_url('/parts/3001/', 'part_img_url')
    assert wait.value.code == 'source_throttled' and wait.value.retry_at == '2026-10-27T10:00:25.000Z'
    assert used(coll.db, 'rebrickable')[0][2:] == (1, '2026-10-27T10:00:25.000Z')
    clock.at += timedelta(seconds=10)                                                                # still paused: no second call
    with pytest.raises(base.WaitingForBudget) as again:
        Rebrickable(coll.db, http=net, sleep=clock.sleep, clock=clock).picture_url('/parts/3001/', 'part_img_url')
    assert again.value.retry_at == '2026-10-27T10:00:25.000Z' and len(net.requests) == 1
    clock.at += timedelta(seconds=20)                                                                # another client of the source honours it too
    assert Rebrickable(coll.db, http=net, sleep=clock.sleep, clock=clock).picture_url('/parts/3001/', 'part_img_url') == 'https://cdn.rebrickable.com/x.jpg'
    assert len(net.requests) == 2


def test_a_reply_is_kept_under_the_job_with_keys_redacted(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    secret = 'synthetic-bw_bricklink_consumer_key'
    reply = price_reply()
    reply['data']['echo'] = secret
    net = Net(reply)
    item = coll.item('sets', '1000-1')
    coll.project(item)
    job = coll.sql("INSERT INTO job(source, kind, item_id, state, via, created_at, updated_at) VALUES('import', 'item', ?, 'running', 'app', 'a', 'a')", (item,)).lastrowid
    BrickLink(coll.db, http=net).price(item, None, 'used', job_id=job)
    records = coll.db.execute('SELECT source, kind, key, status, job_id, payload FROM source_record').fetchall()
    assert [(r['source'], r['kind'], r['status'], r['job_id']) for r in records] == [('bricklink', '/items/SET/1000-1/price', 'success', job)]
    assert secret not in records[0]['payload'] and '[set]' in records[0]['payload']
    assert coll.db.execute('SELECT job_id FROM price_observation').fetchone()[0] == job
    # the same reply twice is one record (the key includes the digest)
    BrickLink(coll.db, http=Net(reply)).price(item, None, 'used', job_id=job)
    assert coll.db.execute('SELECT count(*) FROM source_record').fetchone()[0] == 1


def test_no_key_and_a_disabled_source_refuse_before_any_call_or_charge(coll, monkeypatch):
    net = Net(price_reply())
    item = coll.item('sets', '1000-1')
    with pytest.raises(base.SourceNotConfigured):
        BrickLink(coll.db, http=net).price(item, None, 'used')
    keyed(monkeypatch, 'bricklink')
    coll.sql("UPDATE source SET enabled=0 WHERE id='bricklink'")
    with pytest.raises(base.SourceDisabled):
        BrickLink(coll.db, http=net).price(item, None, 'used')
    assert net.requests == [] and used(coll.db) == []


@pytest.mark.parametrize('status, body, refused', [
    (401, {'meta': {'code': 401, 'message': 'INVALID_TOKEN'}}, True), (403, {'meta': {'code': 403, 'message': 'BAD_OAUTH_REQUEST'}}, False),
    (401, {'meta': {'code': 401, 'message': 'TOKEN_IP_MISMATCHED'}}, False), (403, '<html>blocked</html>', False)])
def test_only_an_authentication_error_in_the_sources_own_words_refuses_the_key(coll, monkeypatch, status, body, refused):
    keyed(monkeypatch, 'bricklink')
    with pytest.raises(base.SourceError) as caught:
        BrickLink(coll.db, http=Net((status, body))).price(coll.item('sets', '1000-1'), None, 'used')
    assert isinstance(caught.value, base.KeyRejected) is refused


def test_a_transport_failure_has_a_fixed_text_and_is_charged_once(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    with pytest.raises(base.SourceError) as caught:
        BrickLink(coll.db, http=Net(OSError('connection to https://api.bricklink.com/?oauth_token=synthetic-secret refused'))).price(coll.item('sets', '1000-1'), None, 'used')
    assert str(caught.value) == 'bricklink could not be reached' and used(coll.db)[0][1] == 1


def test_endpoint_allowlist(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    for path in ('/items/SET/6081-1/subsets', '/inventories', '/items/SET/../price', '/colors'):
        with pytest.raises(ValueError, match='unsupported BrickLink endpoint'):
            BrickLink(coll.db, http=Net({})).call(path)
    with pytest.raises(ValueError, match='unsupported Brickset endpoint'):
        Brickset(coll.db, http=Net({})).call('deleteSet')


def test_source_preserves_an_explicit_user_agent(coll, monkeypatch):
    keyed(monkeypatch, 'brickset')
    from urllib.request import Request
    net = Net({'status': 'success', 'matches': 0, 'sets': []})
    client = Brickset(coll.db, http=net)
    request = Request('https://brickset.com/api/v3.asmx/checkKey', headers={'User-Agent': 'x'})
    client.request('checkKey', '{}', request, lambda reply: reply, charged=False)
    assert net.requests[0].get_header('User-agent') == 'x'
    client.check_key()
    assert net.requests[1].get_header('User-agent').startswith('BrickWork/')


# ---------- BrickLink prices ----------

def test_a_price_is_recorded_for_the_resolved_key_with_its_provider_key(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    brick, red = coll.item('parts', '3001'), coll.colour('4')
    net = Net(price_reply(quantity=4, average='0.456789', low='0.2', high='0.9'))
    result = BrickLink(coll.db, http=net).price(brick, red, 'used')
    assert result['provider_key'] == 'P:3001/5' and result['guide'] == 'sold' and result['price'] == '0.456789'
    request = net.requests[0]
    assert request.full_url.startswith('https://api.bricklink.com/api/store/v1/items/PART/3001/price?')
    assert 'color_id=5' in request.full_url and 'new_or_used=U' in request.full_url and 'region=eu' in request.full_url and 'currency_code=EUR' in request.full_url
    row = coll.db.execute('SELECT * FROM price_observation').fetchone()
    assert (row['item_id'], row['color_id'], row['condition'], row['guide'], row['slot'], row['region'], row['currency'], row['price'], row['qty'], row['sold'],
            row['min'], row['max'], row['source'], row['provider_key']) == (brick, red, 'used', 'sold', 'bricklink_used', 'eu', 'EUR', '0.456789', 4, 4,
                                                                          '0.2', '0.9', 'bricklink', 'P:3001/5')
    assert row['observed_at'].endswith('Z') and row['error'] is None and row['voided_at'] is None
    current = coll.db.execute('SELECT * FROM price_current').fetchone()
    assert (current['item_id'], current['color_id'], current['condition'], current['guide'], current['observation_id']) == (brick, red, 'used', 'sold', row['id'])
    assert coll.db.execute('SELECT count(*) FROM price_watch').fetchone()[0] == 0      # watching is the pipeline step's note, not a single call's


def test_a_sold_guide_without_sales_falls_back_to_the_stock_guide_and_each_call_is_one_observation(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    keep = coll.item('sets', '1000-1')
    net = Net(price_reply(quantity=0), price_reply(quantity=7, average='30', low='20', high='40'))
    result = BrickLink(coll.db, http=net).price(keep, None, 'new')
    assert result['guide'] == 'stock' and result['qty'] == 7 and len(net.requests) == 2 and 'guide_type=stock' in net.requests[1].full_url
    rows = [tuple(r) for r in coll.db.execute('SELECT guide, price, qty, sold, condition, provider_key FROM price_observation ORDER BY id')]
    assert rows == [('sold', None, 0, 0, 'new', 'S:1000-1'), ('stock', '30', 7, None, 'new', 'S:1000-1')]
    assert {r[0] for r in coll.db.execute('SELECT guide FROM price_current')} == {'sold', 'stock'}
    assert used(coll.db)[0][1] == 2


def test_a_newer_observation_replaces_the_current_one_and_the_old_one_stays(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    keep = coll.item('sets', '1000-1')
    BrickLink(coll.db, http=Net(price_reply(average='10'))).price(keep, None, 'used')
    BrickLink(coll.db, http=Net(price_reply(average='11'))).price(keep, None, 'used')
    assert coll.db.execute('SELECT count(*) FROM price_observation').fetchone()[0] == 2
    assert coll.db.execute('SELECT o.price FROM price_current c JOIN price_observation o ON o.id=c.observation_id').fetchall()[0][0] == '11'


def test_the_regional_currency_and_worldwide_settings_decide_the_parameters(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    keep = coll.item('sets', '1000-1')
    coll.setting('bricklink_region', 'all')
    coll.setting('bricklink_currency', 'USD')
    net = Net(price_reply())
    BrickLink(coll.db, http=net).price(keep, None, 'used')
    assert 'region' not in net.requests[0].full_url and 'currency_code=USD' in net.requests[0].full_url
    row = coll.db.execute('SELECT region, currency FROM price_observation').fetchone()
    assert (row['region'], row['currency']) == ('all', 'USD')
    coll.setting('bricklink_currency', 'euro')
    with pytest.raises(base.SourceError, match='invalid BrickLink settings'):
        BrickLink(coll.db, http=net).price(keep, None, 'used')


def test_an_item_without_a_brickLink_number_is_unidentified_and_nothing_is_called(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    net = Net(price_reply())
    with pytest.raises(items.Unidentified):
        BrickLink(coll.db, http=net).price(world.mystery, None, 'used')
    assert net.requests == [] and used(coll.db) == []


def test_a_local_brickLink_born_item_is_priced_by_its_own_number(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    net = Net(price_reply())
    BrickLink(coll.db, http=net).price(world.local_part, world.red, 'new')
    assert '/items/PART/x999/price' in net.requests[0].full_url and 'color_id=5' in net.requests[0].full_url
    assert coll.db.execute('SELECT provider_key FROM price_observation WHERE item_id=?', (world.local_part,)).fetchone()[0] == 'P:x999/5'


def test_an_inferred_link_becomes_matched_from_the_reply_and_a_manual_one_is_left(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    keep = coll.item('sets', '1000-1')
    coll.project(keep)
    status = lambda: [tuple(r) for r in coll.db.execute("SELECT provider_key, status, method, origin FROM item_link WHERE item_id=? AND provider='bricklink'", (keep,))]
    assert status() == [('1000-1', 'inferred', 'set_number', 'rule')]
    BrickLink(coll.db, http=Net(price_reply())).price(keep, None, 'used')
    assert status() == [('1000-1', 'matched', 'bricklink_api', 'api')]
    assert coll.db.execute("SELECT count(*) FROM event WHERE entity_kind='item_link' AND field='status'").fetchone()[0] == 1
    manual = coll.item('sets', '1000-2')
    coll.project(manual)
    coll.sql("UPDATE item_link SET status='manual', origin='user', method='user' WHERE item_id=? AND provider='bricklink'", (manual,))
    BrickLink(coll.db, http=Net(price_reply())).price(manual, None, 'used')
    assert coll.db.execute("SELECT status FROM item_link WHERE item_id=? AND provider_key='1000-2'", (manual,)).fetchall()[0][0] == 'manual'


@pytest.mark.parametrize('guide', [{'total_quantity': 'x'}, {'total_quantity': 2, 'qty_avg_price': 'NaN', 'min_price': '1', 'max_price': '2'},
                                  {'total_quantity': 2, 'qty_avg_price': '0', 'min_price': '1', 'max_price': '2'},
                                  {'total_quantity': 2, 'qty_avg_price': '1', 'min_price': '-1', 'max_price': '2'}, {'total_quantity': 1}])
def test_an_invalid_price_writes_nothing_but_keeps_the_reply(coll, monkeypatch, guide):
    keyed(monkeypatch, 'bricklink')
    with pytest.raises(base.InvalidReply):
        BrickLink(coll.db, http=Net({'meta': {'code': 200}, 'data': guide})).price(coll.item('sets', '1000-1'), None, 'used')
    assert coll.db.execute('SELECT count(*) FROM price_observation').fetchone()[0] == 0
    assert coll.db.execute('SELECT count(*) FROM price_current').fetchone()[0] == 0
    assert [r[0] for r in coll.db.execute('SELECT status FROM source_record')] == ['failed']


def test_an_unknown_item_at_brickLink_is_not_found_and_an_ip_mismatch_says_so_safely(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    keep = coll.item('sets', '1000-1')
    with pytest.raises(base.NotFoundAtSource):
        BrickLink(coll.db, http=Net({'meta': {'code': 404, 'message': 'RESOURCE_NOT_FOUND'}})).price(keep, None, 'used')
    with pytest.raises(base.SourceError) as caught:
        BrickLink(coll.db, http=Net((401, {'meta': {'code': 401, 'message': 'TOKEN_IP_MISMATCHED'}}))).price(keep, None, 'used')
    assert 'IP mismatch' in str(caught.value) and not isinstance(caught.value, base.KeyRejected)
    assert coll.db.execute('SELECT payload FROM source_record ORDER BY id DESC').fetchone()[0].count('TOKEN_IP_MISMATCHED') == 1


def test_price_key_forms():
    assert provider_key('P', '3023', '1') == 'P:3023/1' and provider_key('P', '3023') == 'P:3023'
    assert provider_key('S', '6081-1', None) == 'S:6081-1' and provider_key('M', 'air003', '5') == 'M:air003'     # a colour belongs to parts only


def test_the_order_endpoints_stay_with_the_client(coll, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    net = Net({'meta': {'code': 200}, 'data': [{'order_id': 7}]})
    client = BrickLink(coll.db, http=net)
    assert client.list_orders() == [{'order_id': 7}] and client.order_items(7) == [{'order_id': 7}]
    assert 'direction=out' in net.urls[0] and 'filed=false' in net.urls[0] and net.urls[1].endswith('/orders/7/items')
    with pytest.raises(ValueError):
        client.order_items('7/../x')
    with pytest.raises(ValueError):
        client.list_orders('yes')


# ---------- the base writers ----------

def test_observation_and_property_writers_are_item_keyed_upserts(coll):
    keep = coll.item('sets', '1000-1')
    coll.project(keep)
    first = base.observation(coll.db, 'brickset', keep, guide='retail', price='80', currency='EUR', region='DE', slot='retail')
    second = base.observation(coll.db, 'brickset', keep, guide='retail', price='85', currency='EUR', region='DE', slot='retail')
    assert second > first and coll.db.execute('SELECT observation_id FROM price_current').fetchall()[0][0] == second
    with pytest.raises(ValueError, match='price condition'):
        base.observation(coll.db, 'manual', keep, guide='manual', price='1', currency='EUR', condition='mint')
    base.property_value(coll.db, 'brickset', keep, 'pieces', 438)
    base.property_value(coll.db, 'brickset', keep, 'pieces', 440)
    base.property_value(coll.db, 'brickset', keep, 'theme', None)
    assert [tuple(r) for r in coll.db.execute('SELECT key, value, source FROM item_property')] == [('pieces', '440', 'brickset')]
    assert base.item(coll.db, coll.item('parts', '3001')) == coll.item('parts', '3001')


# ---------- Brickset ----------

def brickset_row(number='1000', variant=1, **extra):
    return {'setID': 5001, 'number': number, 'numberVariant': variant, 'name': 'Syn Castle Keep', 'year': 1990, 'theme': 'Castle', 'subtheme': 'Lion',
            'pieces': 438, 'minifigs': 2, 'category': 'Normal', 'availability': 'Retail',
            'LEGOCom': {'DE': {'retailPrice': 79.99, 'dateFirstAvailable': '1990-01-01T00:00:00Z', 'dateLastAvailable': '1993-12-31T00:00:00Z'},
                        'US': {'retailPrice': 89.99}}, **extra}


def test_brickset_writes_properties_and_the_retail_price_of_the_country(coll, monkeypatch):
    keyed(monkeypatch, 'brickset')
    keep = coll.item('sets', '1000-1')
    net = Net({'status': 'success', 'matches': 1, 'sets': [brickset_row()]})
    assert Brickset(coll.db, http=net).refresh([keep]) == [keep]
    props = {r['key']: r['value'] for r in coll.db.execute("SELECT key, value FROM item_property WHERE item_id=? AND source='brickset'", (keep,))}
    assert props['pieces'] == '438' and props['theme'] == 'Castle' and props['dateLastAvailable'] == '1993-12-31T00:00:00Z' and props['setID'] == '5001'
    row = coll.db.execute("SELECT * FROM price_observation WHERE guide='retail'").fetchone()
    assert (row['item_id'], row['price'], row['currency'], row['region'], row['slot'], row['source'], row['condition']) == (keep, '79.99', 'EUR', 'DE', 'retail', 'brickset', None)
    body = net.requests[0].data.decode()
    assert 'setNumber' in body and '1000-1' in body and 'apiKey=synthetic-bw_brickset_api_key' in body
    assert used(coll.db, 'brickset')[0][1] == 1                                   # getSets is charged; checkKey is not
    Brickset(coll.db, http=Net({'status': 'success', 'matches': 0, 'sets': []})).check_key()
    assert used(coll.db, 'brickset')[0][1] == 1


def test_the_retail_country_setting_picks_the_prices_currency(coll, monkeypatch):
    keyed(monkeypatch, 'brickset')
    coll.setting('retail_country', 'US')
    keep = coll.item('sets', '1000-1')
    Brickset(coll.db, http=Net({'status': 'success', 'matches': 1, 'sets': [brickset_row()]})).refresh([keep])
    row = coll.db.execute("SELECT price, currency, region FROM price_observation WHERE guide='retail'").fetchone()
    assert tuple(row) == ('89.99', 'USD', 'US')
    coll.setting('retail_country', 'FR')
    with pytest.raises(ValueError, match='retail country'):
        Brickset(coll.db, http=Net({})).refresh([keep])


def test_a_set_brickset_does_not_know_gets_unmatched_no_match_and_a_known_one_clears_it(coll, monkeypatch):
    keyed(monkeypatch, 'brickset')
    keep, gate = coll.item('sets', '1000-1'), coll.item('sets', '1000-2')
    net = Net({'status': 'success', 'matches': 1, 'sets': [brickset_row('1000', 1)]})
    assert Brickset(coll.db, http=net).refresh([keep, gate]) == [keep]
    status = lambda item: [tuple(r) for r in coll.db.execute('SELECT provider, status, reason FROM item_provider_status WHERE item_id=?', (item,))]
    assert status(gate) == [('brickset', 'unmatched', 'no_match')] and status(keep) == []
    assert json.loads(coll.db.execute('SELECT evidence_json FROM item_provider_status WHERE item_id=?', (gate,)).fetchone()[0]) == {'brickset': '1000-2'}
    Brickset(coll.db, http=Net({'status': 'success', 'matches': 1, 'sets': [brickset_row('1000', 2)]})).refresh([gate])
    assert status(gate) == []


def test_brickset_numbers_come_from_a_link_the_rebrickable_number_or_the_brickLink_number(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    client = Brickset(coll.db)
    assert client.number_of(world.keep) == '1000-1'                              # Rebrickable-born: Brickset's form too
    local_set = coll.local('set', 'Only on BrickLink', born_key='7777')
    assert client.number_of(local_set) == '7777-1'                                # a BrickLink number without a variant means variant 1
    coll.link(world.keep, '1000-9', kind='set', provider='brickset', status='manual')
    assert client.number_of(world.keep) == '1000-9'                               # a confirmed Brickset link wins
    assert client.number_of(world.mystery) is None
    with pytest.raises(ValueError, match='no Brickset number'):
        client.refresh([world.mystery])


def test_an_api_limit_pauses_brickset_until_midnight(coll, monkeypatch, clock):
    keyed(monkeypatch, 'brickset')
    keep = coll.item('sets', '1000-1')
    net = Net({'status': 'error', 'message': 'API limit exceeded'})
    with pytest.raises(base.WaitingForBudget) as wait:
        Brickset(coll.db, http=net, clock=clock, sleep=clock.sleep).refresh([keep])
    assert wait.value.retry_at == '2026-10-28T00:00:00.000Z' and wait.value.code == 'budget_exhausted'
    assert used(coll.db, 'brickset')[0][2:] == (1, '2026-10-28T00:00:00.000Z')
    with pytest.raises(base.WaitingForBudget):                                    # no second call while it is paused
        Brickset(coll.db, http=net, clock=clock, sleep=clock.sleep).refresh([keep])
    assert len(net.requests) == 1


def test_a_brickset_key_error_is_a_key_rejection(coll, monkeypatch):
    keyed(monkeypatch, 'brickset')
    with pytest.raises(base.KeyRejected):
        Brickset(coll.db, http=Net({'status': 'error', 'message': 'Invalid API key'})).check_key()
    with pytest.raises(base.SourceError) as caught:
        Brickset(coll.db, http=Net({'status': 'error', 'message': 'Server on fire'})).check_key()
    assert not isinstance(caught.value, base.KeyRejected)


def test_brickset_without_a_retail_price_records_the_properties_only(coll, monkeypatch):
    keyed(monkeypatch, 'brickset')
    keep = coll.item('sets', '1000-1')
    row = brickset_row()
    row['LEGOCom'] = {'DE': {}}
    Brickset(coll.db, http=Net({'status': 'success', 'matches': 1, 'sets': [row]})).refresh([keep])
    assert coll.db.execute('SELECT count(*) FROM price_observation').fetchone()[0] == 0
    assert coll.db.execute('SELECT count(*) FROM item_property WHERE item_id=?', (keep,)).fetchone()[0] >= 8


# ---------- the picture cache ----------

def test_a_picture_is_verified_stored_by_digest_and_its_row_replaced(coll, tmp_path):
    brick, red = coll.item('parts', '3001'), coll.colour('4')
    coll.project(brick)
    first = images.store(coll.db, tmp_path, 'bricklink', brick, 'part', png('red'), color_id=red, url='https://img.bricklink.com/a.png')
    assert first.startswith('data/images/bricklink/part/') and first.endswith('.png') and (tmp_path / first).read_bytes() == png('red')
    rows = coll.db.execute('SELECT * FROM picture').fetchall()
    assert [(r['item_id'], r['color_id'], r['source'], r['kind'], r['width'], r['height']) for r in rows] == [(brick, red, 'bricklink', 'photo', 8, 6)]
    second = images.store(coll.db, tmp_path, 'bricklink', brick, 'part', png('blue'), color_id=red)
    assert second != first and coll.db.execute('SELECT count(*) FROM picture').fetchone()[0] == 1
    other = images.store(coll.db, tmp_path, 'rebrickable_dump', brick, 'part', png('green'), color_id=red)           # another source keeps its own row
    assert coll.db.execute('SELECT count(*) FROM picture').fetchone()[0] == 2 and other.startswith('data/images/rebrickable_dump/')
    events = [json.loads(r[0]) for r in coll.db.execute("SELECT new_value FROM event WHERE entity_kind='picture' AND field='stored' ORDER BY id")]
    assert [e['source'] for e in events] == ['bricklink', 'bricklink', 'rebrickable_dump']


def test_only_rebrickables_api_part_pictures_are_renders():
    assert images.picture_kind('rebrickable_api', 'part') == 'render'
    assert [images.picture_kind(s, k) for s, k in (('rebrickable_dump', 'part'), ('bricklink', 'part'), ('rebrickable_api', 'set'))] == ['photo'] * 3


@pytest.mark.parametrize('data', [b'', b'not an image', b'GIF89a'])
def test_bytes_that_are_no_image_are_refused_and_leave_nothing(coll, tmp_path, data):
    brick = coll.item('parts', '3001')
    coll.project(brick)
    with pytest.raises(base.SourceError, match='could not be verified'):
        images.store(coll.db, tmp_path, 'bricklink', brick, 'part', data)
    assert coll.db.execute('SELECT count(*) FROM picture').fetchone()[0] == 0 and not (tmp_path / 'data').exists()


def test_a_download_keeps_to_https_hosts_of_the_source(coll, tmp_path):
    brick = coll.item('parts', '3001')
    coll.project(brick)
    fake = Pictures()
    for source, url in (('bricklink', 'http://img.bricklink.com/a.png'), ('bricklink', 'https://evil.example/a.png'),
                        ('bricklink', 'https://user:pw@img.bricklink.com/a.png'), ('bricklink', 'https://img.bricklink.com:8443/a.png'),
                        ('rebrickable_dump', 'https://img.bricklink.com/a.png'), ('own', 'https://img.bricklink.com/a.png')):
        with pytest.raises(base.SourceError, match='unsupported image URL'):
            images.download(coll.db, tmp_path, source, brick, 'part', url, http=fake)
    assert fake.asked == []
    stored = images.download(coll.db, tmp_path, 'rebrickable_api', brick, 'part', '//cdn.rebrickable.com/media/x.png', color_id=coll.colour('4'), http=fake)
    assert fake.asked == ['https://cdn.rebrickable.com/media/x.png'] and stored.startswith('data/images/rebrickable_api/part/')
    assert coll.db.execute('SELECT kind FROM picture').fetchone()[0] == 'render'
    with pytest.raises(base.SourceError, match='could not be downloaded'):
        images.download(coll.db, tmp_path, 'bricklink', brick, 'part', 'https://img.bricklink.com/b.png', http=Pictures(default=OSError('https://x?token=synthetic')))


def test_an_oversized_picture_is_refused(coll, tmp_path, monkeypatch):
    brick = coll.item('parts', '3001')
    coll.project(brick)
    monkeypatch.setattr(images, 'MAX_BYTES', 10)
    with pytest.raises(base.SourceError, match='could not be verified'):
        images.store(coll.db, tmp_path, 'bricklink', brick, 'part', png())


def test_the_picture_sources_are_rows_of_source(coll):
    assert {r[0] for r in coll.db.execute("SELECT id FROM source WHERE id IN ('rebrickable_dump', 'bricklink', 'rebrickable_api')")} == {'rebrickable_dump', 'bricklink', 'rebrickable_api'}


def test_the_spacing_is_checked_under_the_write_lock_by_every_process(coll, monkeypatch, clock):
    """Two clients (two processes) that both saw 'long ago' before either reserved still go one second apart."""
    keyed(monkeypatch, 'bricklink')
    keep = coll.item('sets', '1000-1')
    net = Net(price_reply())
    from contextlib import closing
    from brickwork.core.connect import connect
    seen = []
    with closing(connect(coll.db.execute('PRAGMA database_list').fetchone()[2])) as other:
        first = BrickLink(coll.db, http=net, sleep=clock.sleep, clock=clock)
        second = BrickLink(other, http=net, sleep=lambda s: (seen.append(s), clock.sleep(s))[0], clock=clock)
        first.reserve()
        second.reserve()                                       # reads the first one's attempt under its own lock: waits the second out
    assert seen == [1.0] and used(coll.db)[0][1] == 2
