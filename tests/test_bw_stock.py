"""Loose receipts share stock identities, while retaining independent provenance."""
from contextlib import closing
import base64
import json
import sqlite3

import pytest

from brickwork.core import add, ledger, orders, part_inventory, stock
from brickwork.core.connect import connect
from tests.test_bw_add import app, bw, legacy, apps, client_token
from tests.test_bw_orders_storage import saved
from tests.test_bw_part_inventory import photo


@pytest.fixture(autouse=True)
def archived_fixture_stock(bw):
    with closing(connect(bw)) as db, db:
        db.execute("UPDATE loose_stock SET archived_at='fixture' WHERE archived_at IS NULL")


def values(**extra):
    return dict(item_type='P', item_no='bl-part', color_id=11, quantity=2,
                condition='U', **extra)


@pytest.mark.parametrize('field,value', [('color_id', None), ('condition', 'N'),
                                      ('lot_id', 'lot'), ('storage_id', 'store')])
def test_merge_key_and_audited_undo(bw, field, value):
    with closing(connect(bw)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("INSERT INTO lots(id,name) VALUES('lot','Lot')")
        changes = []
        identifier, created = stock.add_loose(db, changes, **values())
        assert created
        before = dict(db.execute('SELECT * FROM loose_stock WHERE id=?', (identifier,)).fetchone())
        same, created = stock.add_loose(db, changes, **values())
        assert (same, created) == (identifier, False)
        assert changes[-1]['quantity'] == 2
        assert changes[-1]['old'] == [before]
        assert changes[-1]['new'][0]['quantity'] == 4
        different = values()
        different[field] = value
        other, created = stock.add_loose(db, changes, **different)
        assert created and other != identifier
        stock.undo_loose(db, changes[1:])
        assert dict(db.execute('SELECT * FROM loose_stock WHERE id=?', (identifier,)).fetchone()) == before
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?', (other,)).fetchone()[0]
        stock.undo_loose(db, changes[:1])
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?', (identifier,)).fetchone()[0]
        replacement, created = stock.add_loose(db, [], **values())
        assert created and replacement != identifier
        event = db.execute("SELECT * FROM events WHERE entity=? AND field='increased'", ('stock:' + identifier,)).fetchone()
        assert json.loads(event['old_value']) == before
        assert json.loads(event['new_value'])['quantity'] == 4


def piece(identifier, kind='P'):
    number = 'bl-figure' if kind == 'M' else 'bl-part'
    return dict(id=identifier, candidates=[dict(item_type=kind, item_no=number, score=.9)],
                chosen=dict(item_type=kind, item_no=number, color_id=11, quantity=2),
                photo=base64.b64encode(photo()).decode())


def add_row(kind='P'):
    return dict(item_type=kind, item_no='bl-figure' if kind == 'M' else 'bl-part',
                color_id=11, quantity=2, condition='U', name='Fixture',
                where='loose', decision='another')


def test_all_three_paths_share_helper_and_guarded_undo(bw, monkeypatch):
    calls = []
    original = stock.add_loose
    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        return result
    monkeypatch.setattr(stock, 'add_loose', tracked)
    with closing(connect(bw)) as db:
        first = add.confirm(db, [add_row()], batch='first')[0]
        second = add.confirm(db, [add_row()], batch='second')[0]
        identifier = first['stock'][0]
        assert second['stock'] == [identifier]
        assert [first['stock_changes'][0]['created'], second['stock_changes'][0]['created']] == [True, False]
        event = part_inventory.save(db, [piece('photo-id')], batch='photo', keep_photos=True)
        receipt = json.loads(db.execute('SELECT new_value FROM events WHERE id=?', (event,)).fetchone()[0])
        assert receipt['stock'] == [identifier]
        assert receipt['identifications'] == [dict(id='photo-id', stock_id=identifier)]
        assert db.execute("SELECT stock_id FROM item_images WHERE kind='own' ORDER BY id DESC").fetchone()[0] == identifier
        oid, _, lid = saved(db)
        orders.received(db, oid, {lid:3})
        allocation = orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=1),
                                               dict(line_id=lid, target_type='stock', quantity=2)])
        assert calls == [(identifier, True)] + [(identifier, False)] * 4
        assert db.execute('SELECT quantity FROM loose_stock WHERE id=?', (identifier,)).fetchone()[0] == 9
        assert {r[0] for r in db.execute('SELECT target_stock_id FROM allocations WHERE order_id=?', (oid,))} == {identifier}
        allocation_receipt = json.loads(db.execute('SELECT new_value FROM events WHERE id=?', (allocation,)).fetchone()[0])
        change = next(c for c in allocation_receipt['changes'] if c['table'] == 'loose_stock')
        assert change['quantity'] == 3 and change['created'] is False
        for undo in [lambda: add.undo(db, 'second'), lambda: part_inventory.undo(db, event)]:
            with pytest.raises(ValueError, match='Stock changed'):
                undo()
        with db:
            db.execute('UPDATE loose_stock SET note=? WHERE id=?', ('Later edit', identifier))
        with pytest.raises(ValueError, match='changed after saving'):
            ledger.undo(db, allocation)
        with db:
            db.execute('UPDATE loose_stock SET note=NULL WHERE id=?', (identifier,))
        ledger.undo(db, allocation)
        part_inventory.undo(db, event)
        add.undo(db, 'second')
        assert db.execute('SELECT quantity FROM loose_stock WHERE id=?', (identifier,)).fetchone()[0] == 2
        add.undo(db, 'first')
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?', (identifier,)).fetchone()[0]


def test_minifigures_stay_separate_in_all_paths(bw):
    with closing(connect(bw)) as db:
        first = add.confirm(db, [add_row('M'), add_row('M')], batch='figures')
        assert first[0]['stock'] != first[1]['stock']
        event = part_inventory.save(db, [piece('figure-1', 'M'), piece('figure-2', 'M')],
                                    batch='figures', keep_photos=False)
        receipt = json.loads(db.execute('SELECT new_value FROM events WHERE id=?', (event,)).fetchone()[0])
        assert len(set(receipt['stock'])) == 2
        oid, _, lid = saved(db, text='<INVENTORY><ITEM><ITEMTYPE>M</ITEMTYPE><ITEMID>bl-figure</ITEMID><COLOR>11</COLOR><QTY>3</QTY><CONDITION>U</CONDITION></ITEM></INVENTORY>')
        orders.received(db, oid, {lid:3})
        allocation = orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=1),
                                               dict(line_id=lid, target_type='stock', quantity=2)])
        assert db.execute('SELECT count(DISTINCT target_stock_id) FROM allocations WHERE order_id=?', (oid,)).fetchone()[0] == 2
        ledger.undo(db, allocation)
        part_inventory.undo(db, event)
        add.undo(db, 'figures')


def test_six_additions_have_bounded_query_cost_and_exact_reverse(bw):
    with closing(connect(bw)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        queries, changes = [], []
        db.set_trace_callback(queries.append)
        results = [stock.add_loose(db, changes, **values()) for _ in range(6)]
        db.set_trace_callback(None)
        assert len({r[0] for r in results}) == 1
        # Lookup, write, snapshot, audit and its append-only trigger per add.
        assert len(queries) == 30
        stock.undo_loose(db, changes)
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?', (results[0][0],)).fetchone()[0]


def test_add_undo_route_explains_changed_stock(app, bw):
    client, csrf, _ = client_token(app)
    with closing(connect(bw)) as db:
        add.confirm(db, [add_row()], batch='original')
        receipt = add.confirm(db, [add_row()], batch='increase')[0]
        with db:
            db.execute('UPDATE loose_stock SET quantity=20 WHERE id=?', (receipt['stock'][0],))
    response = client.post('/manage/add/undo', json=dict(csrf_token=csrf, batch='increase'))
    assert response.status_code == 400
    assert 'Stock changed' in response.json['error']
    with closing(connect(bw)) as db:
        assert db.execute('SELECT quantity FROM loose_stock WHERE id=?', (receipt['stock'][0],)).fetchone()[0] == 20


def test_audit_failure_rolls_back_increase(bw):
    with closing(connect(bw)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            identifier, _ = stock.add_loose(db, [], **values())
            db.execute("CREATE TRIGGER reject_increase BEFORE INSERT ON events WHEN NEW.field='increased' BEGIN SELECT RAISE(ABORT,'audit rejected'); END")
        before = dict(db.execute('SELECT * FROM loose_stock WHERE id=?', (identifier,)).fetchone())
        with pytest.raises(sqlite3.IntegrityError, match='audit rejected'), db:
            db.execute('BEGIN IMMEDIATE')
            stock.add_loose(db, [], **values())
        assert dict(db.execute('SELECT * FROM loose_stock WHERE id=?', (identifier,)).fetchone()) == before


def test_ledger_quantity_can_first_appear_on_later_change(bw):
    with closing(connect(bw)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        changes = []
        identifier, _ = stock.add_loose(db, changes, **values())
        first = dict(changes[0]); first.pop('quantity')
        stock.add_loose(db, changes, **values())
        event = ledger.finish(db, [first, changes[1]], 'test')
        receipt = json.loads(db.execute('SELECT new_value FROM events WHERE id=?', (event,)).fetchone()[0])
        assert len(receipt['changes']) == 1
        assert receipt['changes'][0]['quantity'] == 2
        assert receipt['changes'][0]['old'] == first['old']
        assert receipt['changes'][0]['new'] == changes[1]['new']
    with closing(connect(bw)) as db:
        ledger.undo(db, event)
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?', (identifier,)).fetchone()[0]
