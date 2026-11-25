"""Tests for the Brick Owl sync adapter (#522)."""
from urllib.parse import parse_qs
import pytest

from brickwork.core import errors
from brickwork.core.sources import base
from brickwork.core.sync.brickowl_run import BrickOwlUser, lot_changes
from tests.app4 import app4, coll, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import Net, keyed, unkeyed


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)


@pytest.fixture
def brickowl_source(coll):
    return coll


def _lot(lot_id, boid, item_type, qty, con, ids):
    return {
        'lot_id': lot_id,
        'boid': boid,
        'type': item_type,
        'qty': qty,
        'con': con,
        'full_con': None,
        'price': None,
        'note': None,
        'ids': ids,
    }


def test_adapter_identity(brickowl_source):
    adapter = BrickOwlUser(brickowl_source.db, http=Net({}))
    assert BrickOwlUser.source == 'brickowl'
    assert adapter.source == 'brickowl'
    assert hasattr(BrickOwlUser, 'send')
    assert hasattr(BrickOwlUser, 'send_set')
    assert hasattr(BrickOwlUser, 'set_ids')


def test_check_user_returns_true(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net({'username': 'syn'})
    assert BrickOwlUser(brickowl_source.db, http=net).check_user() is True
    assert 'user/details' in net.urls[0]


def test_lists_shape(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net([
        {
            'wishlist_id': '8101',
            'name': 'Winter shelf',
            'description': '',
            'public': False,
            'url': 'https://example.invalid/w/8101',
            'item_count': '12',
            'lot_count': '5',
            'created': '2026-01-01',
            'updated': '2026-01-02',
        },
        {
            'wishlist_id': '8102',
            'name': 'Spare builds',
            'description': 'notes',
            'public': True,
            'url': 'https://example.invalid/w/8102',
            'item_count': None,
            'lot_count': '0',
            'created': '2026-01-03',
            'updated': '2026-01-04',
        },
    ])
    assert BrickOwlUser(brickowl_source.db, http=net).lists() == [
        {'id': '8101', 'name': 'Winter shelf', 'lots': 5},
        {'id': '8102', 'name': 'Spare builds', 'lots': 0},
    ]


def test_fetch_collection_sums_normalizes_and_skips(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    lots = [
        _lot('1', '90001', 'Set', '1', 'new', [
            {'id': '91001', 'type': 'item_no'},
            {'id': '70010-1', 'type': 'set_number'},
            {'id': '70010-1', 'type': 'set_number'},
        ]),
        _lot('2', '90001', 'Set', '2', 'used', [{'id': ' 70010 ', 'type': 'set_number'}]),
        _lot('3', '90002', 'Set', '1', 'new', [{'id': '70020', 'type': 'set_number'}]),
        _lot('4', '90003', 'Set', '1', 'new', [{'id': '91003', 'type': 'item_no'}]),
        _lot('5', '90004', 'Set', '0', 'new', [{'id': '70040-1', 'type': 'set_number'}]),
        _lot('6', '90005', 'Set', '1.5', 'new', [{'id': '70050-1', 'type': 'set_number'}]),
    ]
    net = Net(lots)
    result = BrickOwlUser(brickowl_source.db, http=net).fetch({})
    assert result == {
        'owned': {'70010-1': 3, '70020-1': 1},
        'wanted': {},
        'ids': {'70010-1': '90001', '70020-1': '90002'},
        'names': {},
        'unreadable': 3,                                  # a lot with no set number, a quantity of 0 and one of 1.5
        'lots': {
            'owned': {'70010-1': [{'lot_id': '1', 'qty': 1}, {'lot_id': '2', 'qty': 2}], '70020-1': [{'lot_id': '3', 'qty': 1}]},
            'wanted': {},
        },
    }
    assert len(net.requests) == 1 and 'collection/lots' in net.urls[0]


def test_fetch_linked_wishlist_ignores_non_sets(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    collection = [
        _lot('1', '90001', 'Set', '1', 'new', [{'id': '70010-1', 'type': 'set_number'}]),
    ]
    wishlist = [
        _lot('10', '90010', 'Set', '2', 'new', [{'id': '70030', 'type': 'set_number'}]),
        _lot('11', '3001-21', 'Part', '4', 'new', [{'id': '3001', 'type': 'item_no'}]),
        _lot('12', '80001', 'Minifigure', '1', 'new', [{'id': 'fig-1', 'type': 'item_no'}]),
    ]
    net = Net(collection, wishlist)
    result = BrickOwlUser(brickowl_source.db, http=net).fetch({'wishlist_id': '8101'})
    assert result == {
        'owned': {'70010-1': 1},
        'wanted': {'70030-1': 2},
        'ids': {'70010-1': '90001', '70030-1': '90010'},
        'names': {},
        'unreadable': 0,
        'lots': {
            'owned': {'70010-1': [{'lot_id': '1', 'qty': 1}]},
            'wanted': {'70030-1': [{'lot_id': '10', 'qty': 2}]},
        },
    }
    assert 'wishlist/lots' in net.urls[1] and 'wishlist_id=8101' in net.urls[1]


def test_unexpected_reply_raises_source_error(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    with pytest.raises(base.SourceError, match='unexpected collection'):
        BrickOwlUser(brickowl_source.db, http=Net({'unexpected': []})).fetch({})
    with pytest.raises(base.SourceError, match='unexpected collection'):
        BrickOwlUser(brickowl_source.db, http=Net([], {'unexpected': []})).fetch({'wishlist_id': '8101'})
    with pytest.raises(base.SourceError, match='unexpected collection'):
        BrickOwlUser(brickowl_source.db, http=Net({'unexpected': []})).lists()


def test_lot_changes_cases():
    lots = [{'lot_id': '1', 'qty': 2}, {'lot_id': '2', 'qty': 3}]
    assert lot_changes(lots, 0) == [('delete', '1'), ('delete', '2')]
    assert lot_changes([], 0) == []
    assert lot_changes([], 1) == [('create', None, 1)]
    assert lot_changes([], 3) == [('create', None, 3)]
    assert lot_changes(lots, 5) == []
    assert lot_changes(lots, 7) == [('update', '1', 4)]
    assert lot_changes(lots, 1) == [('delete', '2'), ('update', '1', 1)]
    assert lot_changes(lots, 2) == [('delete', '2')]
    assert lot_changes(lots, 4) == [('update', '2', 2)]


def test_set_ids_looks_up_sets_and_skips_unknown(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net({'boids': ['849212']}, {'boids': []}, {'boids': ['1', '2']})
    result = BrickOwlUser(brickowl_source.db, http=net).set_ids(['75192-1', '99999-1', '75192-1', '88888-1'])
    assert result == {'75192-1': '849212'}                                    # no boid and two boids are both left out
    assert len(net.requests) == 3
    assert 'id=75192-1' in net.urls[0] and 'type=Set' in net.urls[0] and 'id_type=set_number' in net.urls[0]
    assert 'id=88888-1' in net.urls[1] and 'id=99999-1' in net.urls[2]


def test_send_set_owned_create_update_delete(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net({'status': 'Success', 'lot_id': '101'}, {'status': 'Success'})
    adapter = BrickOwlUser(brickowl_source.db, http=net)
    state = {'ids': {'75192-1': '849212'}, 'lots': {'owned': {}, 'wanted': {}}}
    assert adapter.send_set([{'kind': 'owned', 'send': 3, 'remote_no': '75192-1'}], {}, state) == 'sent'
    assert [req.full_url for req in net.requests] == [
        'https://api.brickowl.com/v1/collection/create_lot',
        'https://api.brickowl.com/v1/collection/update',
    ]
    assert parse_qs(net.requests[0].data.decode())['boid'] == ['849212']
    assert parse_qs(net.requests[1].data.decode())['lot_id'] == ['101']
    assert parse_qs(net.requests[1].data.decode())['quantity'] == ['3']

    net = Net({'status': 'Success'})
    adapter = BrickOwlUser(brickowl_source.db, http=net)
    state = {'ids': {'75192-1': '849212'}, 'lots': {'owned': {'75192-1': [{'lot_id': '1', 'qty': 1}]}, 'wanted': {}}}
    assert adapter.send({'kind': 'owned', 'send': 4, 'remote_no': '75192-1'}, {}, state) == 'sent'
    assert net.urls == ['https://api.brickowl.com/v1/collection/update']
    assert parse_qs(net.requests[0].data.decode())['quantity'] == ['4']

    net = Net({'status': 'Success'})
    adapter = BrickOwlUser(brickowl_source.db, http=net)
    state = {
        'ids': {'75192-1': '849212'},
        'lots': {'owned': {'75192-1': [{'lot_id': '1', 'qty': 1}, {'lot_id': '2', 'qty': 2}]}, 'wanted': {}},
    }
    assert adapter.send_set([{'kind': 'owned', 'send': 0, 'remote_no': '75192-1'}], {}, state) == 'sent'
    assert net.urls == [
        'https://api.brickowl.com/v1/collection/delete_lot',
        'https://api.brickowl.com/v1/collection/delete_lot',
    ]
    assert [parse_qs(req.data.decode())['lot_id'][0] for req in net.requests] == ['1', '2']


def test_send_set_wanted_requires_wishlist_and_fetches_once(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    adapter = BrickOwlUser(brickowl_source.db, http=Net({}))
    with pytest.raises(errors.ValidationFailed, match='Link a Brick Owl wishlist'):
        adapter.send_set([{'kind': 'wanted', 'send': 1, 'remote_no': '75192-1'}], {}, {'ids': {}, 'lots': {'owned': {}, 'wanted': {}}})

    collection = [_lot('1', '849212', 'Set', '1', 'new', [{'id': '75192-1', 'type': 'set_number'}])]
    wishlist = []
    net = Net(collection, wishlist, {'status': 'Success'}, {'status': 'Success', 'lot_id': '201'}, {'status': 'Success'})   # reads, owned update, wish create, wish update
    adapter = BrickOwlUser(brickowl_source.db, http=net)
    link = {'wishlist_id': '8101'}
    state = {'ids': {'75192-1': '849212'}}
    assert adapter.send_set([
        {'kind': 'owned', 'send': 2, 'remote_no': '75192-1'},
        {'kind': 'wanted', 'send': 2, 'remote_no': '75192-1'},
    ], link, state) == 'sent'
    assert adapter.send({'kind': 'owned', 'send': 2, 'remote_no': '75192-1'}, link, {'ids': {'75192-1': '849212'}}) == 'sent'
    assert sum('collection/lots' in url for url in net.urls) == 1
    assert 'wishlist/create_lot' in net.urls[3]
    assert 'wishlist/update' in net.urls[4]
    assert parse_qs(net.requests[4].data.decode())['wishlist_id'] == ['8101']
    assert parse_qs(net.requests[4].data.decode())['minimum_quantity'] == ['2']


def test_send_set_unknown_set_number_raises(brickowl_source, monkeypatch):
    keyed(monkeypatch, 'brickowl')
    net = Net({'boids': []})
    adapter = BrickOwlUser(brickowl_source.db, http=net)
    state = {'ids': {}, 'lots': {'owned': {}, 'wanted': {}}}
    with pytest.raises(errors.ValidationFailed, match='Brick Owl does not know this set number'):
        adapter.send_set([{'kind': 'owned', 'send': 1, 'remote_no': '99999-1'}], {}, state)
