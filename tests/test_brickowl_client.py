"""Tests for the Brick Owl API v1 client (#522)."""
from datetime import datetime, timezone
from urllib.parse import parse_qs

import pytest

from brickwork.core import keys
from brickwork.core.sources import base
from brickwork.core.sources.brickowl import BrickOwl
from tests.app4 import app4, coll, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import Net, keyed, unkeyed
from tests.test_brickwork_sources import Clock, used


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)


@pytest.fixture
def brickowl_source(coll):
    # The brickowl source row comes with the 4.9 step.
    return coll


def test_url_user_agent_and_record_key_exclude_secret(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net({'order_id': '92'})
    reply = BrickOwl(brickowl_source.db, http=net).order(92)
    assert reply == {'order_id': '92'}
    request = net.requests[0]
    assert request.get_method() == 'GET'
    assert request.full_url.startswith('https://api.brickowl.com/v1/order/view?')
    assert 'key=synthetic-bw_brickowl_api_key' in request.full_url and 'order_id=92' in request.full_url
    assert request.get_header('User-agent').startswith('BrickWork/')
    row = brickowl_source.db.execute('SELECT source, kind, key, status FROM source_record').fetchone()
    assert tuple(row) == ('brickowl', 'order/view', 'order/view?order_id=92', 'success')
    assert 'synthetic-bw_brickowl_api_key' not in row['key']


def test_record_key_sorts_parameters_and_redacts_secret_payload(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    secret = 'synthetic-bw_brickowl_api_key'
    net = Net({'echo': secret, 'items': []})
    BrickOwl(brickowl_source.db, http=net).call('catalog/id_lookup', {'type': 'Part', 'id': '3001'})
    row = brickowl_source.db.execute('SELECT key, payload FROM source_record').fetchone()
    assert row['key'] == 'catalog/id_lookup?id=3001&type=Part'
    assert secret not in row['key'] and secret not in row['payload'] and '[set]' in row['payload']


@pytest.mark.parametrize('path', ['order/create', 'inventory/update', 'user/details/../x', '/user/details', 'other', ''])
def test_disallowed_endpoint_raises_value_error(brickowl_source, monkeypatch, path):
    keyed(monkeypatch, 'brickowl')
    net = Net({})
    with pytest.raises(ValueError, match='unsupported Brick Owl endpoint'):
        BrickOwl(brickowl_source.db, http=net).call(path)
    assert net.requests == []


def test_403_access_denied_raises_key_rejected(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    with pytest.raises(base.KeyRejected):
        BrickOwl(brickowl_source.db, http=Net((403, {'error': 'Access Denied'}))).check_key()


@pytest.mark.parametrize('status, body, exc_type', [
    (200, {'error': 'Invalid API key'}, base.KeyRejected),
    (200, {'error': 'Access denied for this key'}, base.KeyRejected),
    (403, {'error': 'Temporary failure'}, base.SourceError),
    (403, '<html>blocked</html>', base.InvalidReply),
    (200, {'error': 'Something went wrong'}, base.SourceError),
    (400, {'error': {'status': 'Invalid condition'}}, base.SourceError),
    (403, {'error': {'status': 'Access Denied'}}, base.KeyRejected),
    (400, {'error': {'status': 'Rate limit exceeded'}}, base.WaitingForBudget),
])
def test_error_reply_classification(brickowl_source, monkeypatch, status, body, exc_type):
    keyed(monkeypatch, 'brickowl')
    with pytest.raises(exc_type) as caught:
        BrickOwl(brickowl_source.db, http=Net((status, body))).check_key()
    if exc_type is base.SourceError:
        assert not isinstance(caught.value, base.KeyRejected)
    assert 'synthetic-bw_brickowl_api_key' not in str(caught.value)


@pytest.mark.parametrize('message', ['Daily quota exceeded', 'Rate limit exceeded', 'Too many requests'])
def test_quota_error_waits_for_budget(brickowl_source, monkeypatch, clock, message):
    keyed(monkeypatch, 'brickowl')
    net = Net({'error': message}, {'username': 'syn'})
    client = BrickOwl(brickowl_source.db, http=net, sleep=clock.sleep, clock=clock)
    with pytest.raises(base.WaitingForBudget) as wait:
        client.check_key()
    assert wait.value.retry_at == '2026-10-28T00:00:00.000Z'
    assert used(brickowl_source.db, 'brickowl')[0][2:] == (1, '2026-10-28T00:00:00.000Z')
    with pytest.raises(base.WaitingForBudget):
        client.check_key()
    assert len(net.requests) == 1


def test_daily_budget_counts_calls_and_paces(brickowl_source, monkeypatch, clock):
    keyed(monkeypatch, 'brickowl')
    monkeypatch.setenv('BW_BRICKOWL_DAILY_BUDGET', '2')
    net = Net([{'lot_id': 1}], [{'list_id': 2}], [{'list_id': 3}])
    client = BrickOwl(brickowl_source.db, http=net, sleep=clock.sleep, clock=clock)
    assert client.daily_budget == 2
    assert client.collection_lots() == [{'lot_id': 1}]
    assert client.wishlist_lists() == [{'list_id': 2}]
    assert used(brickowl_source.db, 'brickowl') == [('2026-10-27', 2, 0, None)]
    assert clock.slept == [0.2]
    with pytest.raises(base.WaitingForBudget) as wait:
        client.wishlist_lists()
    assert wait.value.code == 'budget_exhausted' and len(net.requests) == 2
    clock.at = datetime(2026, 10, 28, 0, 0, 1, tzinfo=timezone.utc)
    assert client.wishlist_lists() == [{'list_id': 3}]
    assert used(brickowl_source.db, 'brickowl')[-1] == ('2026-10-28', 1, 0, None)


def test_daily_budget_env_may_lower_only(coll, monkeypatch):
    assert BrickOwl(coll.db).daily_budget == 2000
    monkeypatch.setenv('BW_BRICKOWL_DAILY_BUDGET', '5000')
    assert BrickOwl(coll.db).daily_budget == 2000


@pytest.mark.parametrize('value', ['0', '-1', 'x', '1.5', ''])
def test_invalid_daily_budget_env_is_refused(coll, monkeypatch, value):
    monkeypatch.setenv('BW_BRICKOWL_DAILY_BUDGET', value)
    with pytest.raises(base.SourceError, match='BW_BRICKOWL_DAILY_BUDGET'):
        BrickOwl(coll.db)


def test_method_endpoint_allow_list_and_post_for_writes(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    write_paths = ('collection/create_lot', 'collection/update', 'collection/delete_lot',
                   'wishlist/create_lot', 'wishlist/update', 'wishlist/delete_lot')
    read_paths = ('user/details', 'collection/lots', 'wishlist/lists', 'wishlist/lots',
                  'order/list', 'order/view', 'order/items', 'catalog/id_lookup')
    net = Net({'status': 'Success', 'lot_id': '77'})
    client = BrickOwl(brickowl_source.db, http=net)
    for path in write_paths:
        with pytest.raises(ValueError, match='unsupported Brick Owl endpoint'):
            client.call(path)
    for path in read_paths:
        with pytest.raises(ValueError, match='unsupported Brick Owl endpoint'):
            client.call(path, method='POST')
    with pytest.raises(ValueError, match='unsupported Brick Owl endpoint'):
        client.call('user/details', method='PUT')
    assert net.requests == []
    client.create_collection_lot('849212')
    client.update_collection_lot('77', quantity=2, condition='news')
    client.delete_collection_lot('77')
    client.create_wishlist_lot('8101', '849212')
    client.update_wishlist_lot('8101', '77', 3)
    client.delete_wishlist_lot('8101', '77')
    assert [req.get_method() for req in net.requests] == ['POST'] * 6


def test_thin_read_methods_and_validation(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net([{'lot_id': 1}], [{'order_id': '10'}], [{'item': '3001'}], {'boids': ['123']})
    client = BrickOwl(brickowl_source.db, http=net)
    assert client.wishlist_lots(42) == [{'lot_id': 1}]
    assert client.orders('store', limit=100, offset=50, since=1700000000) == [{'order_id': '10'}]
    assert client.order_items(92) == [{'item': '3001'}]
    assert client.id_lookup('3001', 'Part', id_type='design_id') == {'boids': ['123']}
    assert 'wishlist_id=42' in net.urls[0]
    assert 'list_type=store' in net.urls[1] and 'limit=100' in net.urls[1]
    assert 'offset=50' in net.urls[1] and 'update_time=1700000000' in net.urls[1]
    assert 'order_id=92' in net.urls[2]
    assert 'id=3001' in net.urls[3] and 'type=Part' in net.urls[3] and 'id_type=design_id' in net.urls[3]
    for bad in (lambda: client.wishlist_lots('bad/id'), lambda: client.orders('other'),
                lambda: client.orders(limit=5001), lambda: client.orders(offset=-1),
                lambda: client.orders(since='not-a-date'), lambda: client.order('92/x'),
                lambda: client.order_items(True), lambda: client.id_lookup('3001', 'Part', id_type='other')):
        with pytest.raises(ValueError):
            bad()


def test_keys_and_ready_checks(brickowl_source, monkeypatch):
    assert keys.ENV['brickowl'] == ('BW_BRICKOWL_API_KEY',)
    assert keys.LABELS['brickowl'] == 'Brick Owl'
    assert keys.fields('brickowl') == ('key',)
    with pytest.raises(base.SourceNotConfigured):
        BrickOwl(brickowl_source.db, http=Net({})).check_key()
    keyed(monkeypatch, 'brickowl')
    assert keys.check(brickowl_source.db, 'brickowl', http=Net({'username': 'syn'}))['ok'] is True
    brickowl_source.sql("UPDATE source SET enabled=0 WHERE id='brickowl'")
    with pytest.raises(base.SourceDisabled):
        BrickOwl(brickowl_source.db, http=Net({})).check_key()


@pytest.mark.parametrize('message, exc_type', [
    ('Limit exceeds maximum of 250', base.SourceError),
    ('API key limit reached', base.SourceError),
    ('Permission denied for this wishlist', base.SourceError),
    ('Daily quota exceeded for this key', base.WaitingForBudget),
    ('Invalid API key', base.KeyRejected),
])
def test_error_text_is_matched_by_phrase_not_by_a_word(brickowl_source, monkeypatch, message, exc_type):
    keyed(monkeypatch, 'brickowl')
    with pytest.raises(exc_type) as caught:
        BrickOwl(brickowl_source.db, http=Net({'error': message})).collection_lots()
    if exc_type is base.SourceError:
        assert type(caught.value) is base.SourceError


def test_post_puts_key_and_params_in_body_not_url(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net({'status': 'Success'})
    reply = BrickOwl(brickowl_source.db, http=net).update_collection_lot('12', quantity=3, condition='news')
    assert reply == {'status': 'Success'}
    request = net.requests[0]
    assert request.get_method() == 'POST'
    assert request.full_url == 'https://api.brickowl.com/v1/collection/update'
    assert request.get_header('Content-type') == 'application/x-www-form-urlencoded'
    assert parse_qs(request.data.decode()) == {
        'key': ['synthetic-bw_brickowl_api_key'],
        'lot_id': ['12'],
        'quantity': ['3'],
        'condition': ['news'],
    }
    row = brickowl_source.db.execute('SELECT kind, key, payload FROM source_record').fetchone()
    assert row['kind'] == 'collection/update'
    assert row['key'] == 'collection/update?condition=news&lot_id=12&quantity=3'
    assert 'synthetic-bw_brickowl_api_key' not in row['key'] and 'synthetic-bw_brickowl_api_key' not in row['payload']


def test_thin_write_methods_and_validation(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net({'status': 'Success', 'lot_id': 501}, {'status': 'Success', 'lot_id': '601'}, {'status': 'Success'})
    client = BrickOwl(brickowl_source.db, http=net)
    assert client.create_collection_lot('3001', color_id=21) == '501'
    assert parse_qs(net.requests[0].data.decode())['color_id'] == ['21']
    assert client.create_wishlist_lot('8101', '849212') == '601'
    with pytest.raises(base.SourceError, match='Brick Owl did not return a lot'):
        client.create_collection_lot('849212')
    for bad in (lambda: client.create_collection_lot('bad/id'), lambda: client.create_collection_lot('3001', color_id='x'),
                lambda: client.update_collection_lot('12'), lambda: client.update_collection_lot('12', quantity=0),
                lambda: client.update_wishlist_lot('8101', '12', 0), lambda: client.delete_collection_lot(True)):
        with pytest.raises(ValueError):
            bad()
