"""Tests for the Brick Owl pull-side sync adapter (#522)."""
import pytest

from brickwork.core.sources import base
from brickwork.core.sync.brickowl_run import BrickOwlUser
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


def test_adapter_identity_and_pull_only(brickowl_source):
    adapter = BrickOwlUser(brickowl_source.db, http=Net({}))
    assert BrickOwlUser.source == 'brickowl'
    assert adapter.source == 'brickowl'
    assert not hasattr(BrickOwlUser, 'send')
    assert not hasattr(BrickOwlUser, 'set_ids')


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
