"""Loose stock on the 4.0 store (M.8c, issue #110; design 2.4 invariant 9): the merge key, the audited add, the guarded undo of an add.

The rest of the old file waits for its callers: the part-inventory, order-allocation and ledger paths that share `add_loose` are M.8e and
M.8h; the edit-merge (`merge_edited`) is M.8d with the collection writes. Invented data, no network."""
from contextlib import closing
import json
import sqlite3

import pytest

from brickwork.core import stock
from brickwork.core.connect import connect
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


@pytest.fixture
def db(pair):
    with closing(connect(pair)) as db:
        yield db


def values(coll, **extra):
    return dict(item_id=coll.item('parts', '3001'), color_id=coll.colour('4'), quantity=2, condition='used', **extra)


def add(db, **kw):
    """One add in its own transaction, as the app does it; returns the change."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        return stock.add_loose(db, **kw)


@pytest.mark.parametrize('field', ['color_id', 'condition', 'lot_id', 'storage_id'])
def test_merge_key_and_audited_undo(coll, field):
    db = coll.db
    lot, store = coll.lot('Lot'), coll.storage('Store')
    other_value = {'color_id': coll.colour('15'), 'condition': 'new', 'lot_id': lot, 'storage_id': store}[field]
    first = add(db, **values(coll))
    assert first['created'] and first['before'] is None
    same = add(db, **values(coll))
    assert (same['id'], same['created']) == (first['id'], False) and same['quantity'] == 2
    assert same['before'] == first['after'] and same['after']['quantity'] == 4
    different = add(db, **{**values(coll), field: other_value})
    assert different['created'] and different['id'] != first['id']
    with db:
        db.execute('BEGIN IMMEDIATE')
        stock.undo_added(db, different)
        stock.undo_added(db, same)
        assert dict(db.execute('SELECT * FROM stock WHERE id=?', (first['id'],)).fetchone()) == first['after']
        assert db.execute('SELECT archived_at FROM stock WHERE id=?', (different['id'],)).fetchone()[0]
        stock.undo_added(db, first)
        assert db.execute('SELECT archived_at FROM stock WHERE id=?', (first['id'],)).fetchone()[0]
    replacement = add(db, **values(coll))                                        # an archived row does not take part in the key
    assert replacement['created'] and replacement['id'] != first['id']
    event = db.execute("SELECT * FROM event WHERE entity_kind='stock' AND entity_id=? AND field IN ('created', 'increased') ORDER BY id", (first['id'],)).fetchall()
    assert [(e['field'], json.loads(e['new_value'])['quantity']) for e in event] == [('created', 2), ('increased', 4)]
    assert json.loads(event[1]['old_value']) == first['after']


def test_a_stock_row_needs_a_colour_only_when_it_is_a_part_and_never_a_set(coll):
    db = coll.db
    with pytest.raises(ValueError, match='colour'):
        add(db, item_id=coll.item('parts', '3001'), color_id=None, quantity=1, condition='used')
    gear = add(db, item_id=coll.local('gear', 'Thing'), color_id=coll.colour('4'), quantity=1, condition=None)
    assert gear['after']['color_id'] is None and gear['after']['kind'] == 'gear' and gear['after']['condition'] is None
    assert not db.in_transaction
    for bad in (dict(quantity=0), dict(quantity=True), dict(condition='mint')):
        with pytest.raises(ValueError):
            add(db, **{**values(coll), **bad})
    with pytest.raises(ValueError, match='copy'):
        add(db, item_id=coll.item('sets', '1000-1'), quantity=1, condition='new')
    with pytest.raises(ValueError, match='transaction'):
        stock.add_loose(db, **values(coll))


def test_minifigures_stay_separate_and_carry_their_parts(coll):
    db = coll.db
    figure = coll.item('minifigs', 'fig-000004')
    first = add(db, item_id=figure, quantity=1, condition='used')
    second = add(db, item_id=figure, quantity=2, condition='used')
    assert first['id'] != second['id'] and second['created']
    lines = lambda sid: db.execute('SELECT sum(quantity) FROM stock_part WHERE stock_id=?', (sid,)).fetchone()[0]
    assert lines(first['id']) > 0 and lines(second['id']) == 2 * lines(first['id'])
    assert (first['after']['inventory_source'], second['after']['inventory_source']) == ('rebrickable', 'rebrickable')


def test_a_figure_with_no_rebrickable_list_gets_none(coll):
    db = coll.db
    figure = coll.local('minifigure', 'BrickLink-only figure', born_key='bl-only-fig')
    row = add(db, item_id=figure, quantity=1, condition='used')['after']
    assert (row['inventory_source'], row['inventory_digest']) == ('none', None)
    assert db.execute('SELECT count(*) FROM stock_part WHERE stock_id=?', (row['id'],)).fetchone()[0] == 0


def test_six_additions_have_bounded_query_cost_and_exact_reverse(coll):
    db = coll.db
    first = add(db, **values(coll))                                              # the first add also projects the item and the colour
    with db:
        db.execute('BEGIN IMMEDIATE')
        queries = []
        db.set_trace_callback(queries.append)
        changes = [stock.add_loose(db, **values(coll)) for _ in range(6)]
        db.set_trace_callback(None)
        assert {c['id'] for c in changes} == {first['id']} and len(queries) % 6 == 0 and len(queries) // 6 <= 12
        for change in reversed(changes):
            stock.undo_added(db, change)
        assert db.execute('SELECT quantity FROM stock WHERE id=?', (first['id'],)).fetchone()[0] == 2


def test_undo_explains_changed_stock(world, client, coll):
    db = coll.db
    client.get('/manage/add')
    with client.session_transaction() as session:
        csrf = session['bw_add_csrf']
    proposal = client.post('/manage/add/review', json=dict(csrf_token=csrf, type='part', where='loose', mode='paste', text='3023')).json
    items = proposal['items']
    items[0].update(color_id=world.white, condition='new', decision='another')
    confirmed = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=items))
    stock_id = confirmed.json['receipts'][0]['stock']
    with db:
        db.execute('UPDATE stock SET quantity=20 WHERE id=?', (stock_id,))
    response = client.post('/manage/add/undo', json=dict(csrf_token=csrf, batch=confirmed.json['batch']))
    assert response.status_code == 400 and 'Stock changed' in response.json['error']
    assert db.execute('SELECT quantity FROM stock WHERE id=?', (stock_id,)).fetchone()[0] == 20


def test_audit_failure_rolls_back_the_increase(coll):
    db = coll.db
    first = add(db, **values(coll))
    with db:
        db.execute("CREATE TRIGGER reject_increase BEFORE INSERT ON event WHEN NEW.field='increased' BEGIN SELECT RAISE(ABORT,'audit rejected'); END")
    before = dict(db.execute('SELECT * FROM stock WHERE id=?', (first['id'],)).fetchone())
    with pytest.raises(sqlite3.IntegrityError, match='audit rejected'), db:
        db.execute('BEGIN IMMEDIATE')
        stock.add_loose(db, **values(coll))
    assert dict(db.execute('SELECT * FROM stock WHERE id=?', (first['id'],)).fetchone()) == before
