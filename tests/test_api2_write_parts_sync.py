"""API v2 Rebrickable part-list pull (#471): plan, apply, idempotent replay, scopes, validation and Undo. Invented data."""
from contextlib import closing
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest

from brickwork.core import stock, sync
from brickwork.core.connect import connect
from brickwork.core.sync import part_lists
from brickwork.core.transaction import transaction
from brickwork.store4.connect import now as store_now
from tests.api2 import app4, rows, stored_token, v2, validate, wire, write  # noqa: F401
from tests.app4 import Coll, make_pair
from tests.test_bw_sync import EXTRA, TOKEN, Rebrickable


@pytest.fixture
def pair(tmp_path):
    """The collection of test_bw_sync: the rich catalogue with two more sets, two copies of `2070-1`."""
    path = make_pair(tmp_path, rich=True, extra_dump=EXTRA)
    with closing(connect(path)) as db:
        coll = Coll(db)
        coll.add_copy('2070-1')
        coll.add_copy('2070-1')
    return path


@pytest.fixture
def remote(monkeypatch, wire):
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters.RebrickableUser, 'minimum_spacing', 0)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'synthetic-brickset-key')
    fake = Rebrickable()
    lists = [
        {'id': 11, 'name': 'Spare bricks', 'num_parts': 5},
        {'id': 12, 'name': 'Sorted bricks', 'num_parts': 2},
    ]
    parts = {
        11: [{'part_no': '3001', 'color_id': 4, 'quantity': 5}],
        12: [{'part_no': '3001', 'color_id': 4, 'quantity': 2}],
    }
    monkeypatch.setattr(adapters, 'transport', fake)
    monkeypatch.setattr(adapters.RebrickableUser, 'part_lists', lambda self: list(lists))
    monkeypatch.setattr(adapters.RebrickableUser, 'part_list_parts', lambda self, list_id: list(parts.get(list_id, [])))
    return fake


def loose_stock(pair):
    return rows(pair, "SELECT id, quantity, lot_id, added_via FROM stock WHERE kind='part' AND archived_at IS NULL ORDER BY id")


def seed_lot(pair, name, part_no, color_id, quantity):
    lot_id, stamp = uuid4().hex, store_now()
    with closing(connect(pair)) as db, transaction(db):
        db.execute('INSERT INTO main.lot(id, name, note, created_at, updated_at) VALUES(?, ?, ?, ?, ?)',
                   (lot_id, name, '', stamp, stamp))
        item, colour = part_lists._part_item(db, part_no), part_lists._colour(db, color_id)
        assert item is not None and colour is not None
        stock.add_loose(db, item_id=item, color_id=colour, quantity=quantity, condition=None, lot_id=lot_id,
                        via='cli', actor=None)
    return lot_id


def set_link(pair, **fields):
    with closing(connect(pair)) as db, transaction(db):
        current = sync._setting(db, 'rebrickable', 'link', {})
        sync._put(db, 'rebrickable', 'link', dict(current, **fields))


def test_part_lists_plan_apply_replay_undo_and_scopes(v2, pair, remote):
    reader, writer = stored_token(pair, ['read'], 'reader'), stored_token(pair, ['read', 'write'], 'writer')
    assert write(v2, '/sources/rebrickable/user', 'put', {'value': TOKEN}).status_code == 200
    assert write(v2, '/sync/rebrickable/parts/plan', token=reader).status_code == 403
    no_lists = write(v2, '/sync/rebrickable/parts/plan', token=writer)
    assert no_lists.status_code == 422 and 'Choose the Rebrickable part lists to sync first' in no_lists.text
    existing_lot = seed_lot(pair, 'Sorted bricks', '3001', 4, 5)
    set_link(pair, part_lists=[11, 12], part_list_lots={'12': existing_lot})
    before = loose_stock(pair)
    plan = write(v2, '/sync/rebrickable/parts/plan', token=writer)
    assert plan.status_code == 201, plan.json
    validate(plan, 'post_sync_rebrickable_parts_plan', '201')
    assert loose_stock(pair) == before
    by_state = {r['state']: r for r in plan.json['data']['rows']}
    assert set(by_state) == {'add', 'differs'}
    add_row, diff_row = by_state['add'], by_state['differs']
    assert add_row['tickable'] is True and add_row['count'] == 5 and add_row['action'] == 'add'
    assert diff_row['tickable'] is False and diff_row['count'] == 0 and diff_row['action'] is None
    plan_id = plan.json['data']['id']
    assert write(v2, '/sync/rebrickable/parts/apply', body={'plan_id': plan_id}, token=reader).status_code == 403
    bad_lot = write(v2, '/sync/rebrickable/parts/apply', body={'plan_id': plan_id, 'lots': {add_row['key']: 'no-such-lot'}}, token=writer)
    assert bad_lot.status_code == 422 and loose_stock(pair) == before
    applied = write(v2, '/sync/rebrickable/parts/apply', body={'plan_id': plan_id}, token=writer, key='parts-1')
    assert applied.status_code == 200, applied.json
    validate(applied, 'post_sync_rebrickable_parts_apply')
    assert applied.json['event_id'] and applied.json['undo_url'].endswith(f"/events/{applied.json['event_id']}/undo")
    after = loose_stock(pair)
    added = [r for r in after if r['lot_id'] != existing_lot]
    assert len(added) == 1 and added[0]['quantity'] == 5 and added[0]['added_via'] == 'rebrickable'
    replay = write(v2, '/sync/rebrickable/parts/apply', body={'plan_id': plan_id}, token=writer, key='parts-1')
    assert replay.status_code == 200 and replay.json['idempotent_replay'] is True
    assert replay.json['event_id'] == applied.json['event_id'] and loose_stock(pair) == after
    undone = write(v2, f"/events/{applied.json['event_id']}/undo", token=writer)
    assert undone.status_code == 200, undone.json
    assert loose_stock(pair) == before


def test_part_lists_apply_rejects_unknown_and_pull_plans(v2, pair, remote):
    writer = stored_token(pair, ['read', 'write'], 'writer')
    assert write(v2, '/sources/rebrickable/user', 'put', {'value': TOKEN}).status_code == 200
    assert write(v2, '/sync/rebrickable/parts/apply', body={'plan_id': 'nope'}, token=writer).status_code == 422
    pull = write(v2, '/sync/rebrickable/pull/plan', token=writer)
    assert pull.status_code == 201, pull.json
    wrong = write(v2, '/sync/rebrickable/parts/apply', body={'plan_id': pull.json['data']['id']}, token=writer)
    assert wrong.status_code == 422 and 'This is a pull plan' in wrong.text


def test_part_lists_are_chosen_through_the_link_write(v2, pair, remote):
    writer = stored_token(pair, ['read', 'write'], 'writer')
    put = write(v2, '/sync/rebrickable/link', 'put', {'part_lists': [11]}, token=writer)
    assert put.status_code == 200, put.text
    with closing(connect(pair)) as db:
        assert sync._setting(db, 'rebrickable', 'link', {}).get('part_lists') == [11]
    assert write(v2, '/sync/rebrickable/link', 'put', {'part_lists': [11, 11]}, token=writer).status_code == 422
    set_link(pair, part_lists=False)
    assert write(v2, '/sync/rebrickable/link', 'put', {'lost_parts': True}, token=writer).status_code == 200
