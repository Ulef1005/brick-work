"""Orders on the 4.0 store (M.8h, issue #110): documents, placing by item id, receipts, explicit allocation, Undo. Invented data, no network.

Rewritten from the 3.3 file of the same name. Gone with 3.3: the storage and ledger half (M.8e has its own tests), the API receipt and history
tests (M.11), the allocation-target upgrade (4.0 starts with the columns), the SQL-trace budget of the 3.3 audit. Kept: every order flow."""
import json
import sqlite3

import pytest

from brickwork.core import errors, orders
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)


@pytest.fixture
def token(client):
    return csrf(client)

XML = ('<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID><COLOR>5</COLOR><QTY>3</QTY><CONDITION>U</CONDITION><PRICE>0.12</PRICE></ITEM></INVENTORY>')


def saved(db, text=XML):
    result = orders.import_document(db, 'xml', text)
    oid, did = result['order_id'], result['document_id']
    orders.phase(db, oid, did, 'review')
    orders.phase(db, oid, did, 'save')
    return oid, did, orders.detail(db, oid)['saved'][0]['id']


def line_of(letter, number, *, colour=None, qty=3, condition='U', price='0.12'):
    return (f'<ITEM><ITEMTYPE>{letter}</ITEMTYPE><ITEMID>{number}</ITEMID>' + (f'<COLOR>{colour}</COLOR>' if colour is not None else '') +
            f'<QTY>{qty}</QTY><CONDITION>{condition}</CONDITION><PRICE>{price}</PRICE></ITEM>')


def inventory(*lines):
    return '<INVENTORY>' + ''.join(lines) + '</INVENTORY>'


def tables(db):
    """Every order table and the rows an allocation touches, for byte-for-byte comparisons after Undo."""
    return {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')]
            for t in ('purchase_order', 'order_document', 'order_line', 'line_receipt', 'line_receipt_log', 'allocation', 'copy', 'copy_part', 'copy_figure',
                      'copy_flag', 'stock', 'stock_part')}


def gap_of(db, oid, lid, copy_id, target='part'):
    return next(g for g in orders.destinations(db, orders.detail(db, oid)['saved'])[lid] if g['copy_id'] == copy_id and g['target'] == target)


# ---------- placing lines by item id ----------

def test_a_line_is_placed_by_its_bricklink_key_through_the_pooled_inverse(world, coll):
    result = orders.import_document(coll.db, 'xml', inventory(line_of('P', '3001', colour=5), line_of('S', '1000-1', qty=1), line_of('M', 'syn-fig-0004', qty=2),
                                                              line_of('I', '1000-1', qty=1)))
    assert (result['placed'], result['unplaced']) == (4, 0)
    rows = orders.lines(coll.db, result['order_id'])
    assert [(r['item_id'], r['color_id'], r['state'], r['condition']) for r in rows] == [
        (world.brick, world.red, 'matched', 'used'), (world.keep, None, 'matched', 'used'), (world.figure, None, 'matched', 'used'),
        (world.local_booklet, None, 'matched', 'used')]
    assert rows[0]['raw_item_type'] == 'P' and rows[0]['raw_item_no'] == '3001' and rows[0]['raw_color_id'] == 5 and '3001' in rows[0]['raw_text']


def test_an_unknown_number_colour_or_type_stays_raw_for_hand_matching(world, coll):
    before = coll.db.execute('SELECT count(*) FROM item').fetchone()[0]
    result = orders.import_document(coll.db, 'xml', inventory(line_of('P', 'nowhere', colour=5), line_of('P', '3001', colour=9999), line_of('P', '3001'),
                                                              line_of('G', 'gear-x', qty=1)))
    assert (result['placed'], result['unplaced']) == (0, 4)
    rows = orders.lines(coll.db, result['order_id'])
    assert [r['state'] for r in rows] == ['by_hand'] * 4 and all(r['item_id'] is None for r in rows)
    assert [r['raw_item_no'] for r in rows] == ['nowhere', '3001', '3001', 'gear-x'] and rows[1]['raw_color_id'] == 9999
    assert coll.db.execute('SELECT count(*) FROM item').fetchone()[0] == before                      # nothing is invented for an unknown key


def test_a_key_that_names_two_items_is_never_guessed(world, coll):
    coll.link(world.plate, '3001', kind='P')                                       # the plate now claims 3001 too
    result = orders.import_document(coll.db, 'xml', inventory(line_of('P', '3001', colour=5)))
    assert (result['placed'], result['unplaced']) == (0, 1)
    row = orders.lines(coll.db, result['order_id'])[0]
    assert row['item_id'] is None and row['state'] == 'by_hand'
    assert sorted(s['item_id'] for s in json.loads(row['suggestions_json'])) == sorted([world.brick, world.plate])
    # the person picks one of the candidates; the line is placed and carries the colour
    orders.match(coll.db, result['order_id'], row['id'], item_id=world.brick, color_id=world.red)
    row = orders.lines(coll.db, result['order_id'])[0]
    assert (row['item_id'], row['color_id'], row['state'], row['confirmed_via'], row['suggestions_json']) == (world.brick, world.red, 'confirmed', 'search', None)


def test_matching_by_a_typed_number_needs_one_item(world, coll):
    result = orders.import_document(coll.db, 'xml', inventory(line_of('P', 'nowhere', colour=5)))
    row = orders.lines(coll.db, result['order_id'])[0]
    with pytest.raises(ValueError, match='catalogue'):
        orders.match(coll.db, result['order_id'], row['id'], item_type='P', item_no='nowhere', color_id=world.red)
    with pytest.raises(ValueError, match='colour'):
        orders.match(coll.db, result['order_id'], row['id'], item_type='P', item_no='3001')
    orders.match(coll.db, result['order_id'], row['id'], item_type='P', item_no='3001', color_id=world.red)
    row = orders.lines(coll.db, result['order_id'])[0]
    assert (row['item_id'], row['confirmed_via']) == (world.brick, 'number')


def test_matching_pairing_reopen_and_hold(world, coll):
    db = coll.db
    oid, did, lid = saved(db)
    result = orders.import_document(db, 'xml', XML.replace('3001', 'nowhere'), choice=oid)
    other = result['document_id']
    row = next(r for r in orders.lines(db, oid) if r['document_id'] == other)
    assert row['item_id'] is None and 'nowhere' in row['raw_text']
    with pytest.raises(ValueError, match='Match each'):
        orders.phase(db, oid, other, 'review')
    event = orders.match(db, oid, row['id'], item_id=world.brick, color_id=world.red)
    assert orders.detail(db, oid)['lines'][-1]['state'] == 'confirmed'
    orders.undo(db, event)
    assert next(r for r in orders.lines(db, oid) if r['id'] == row['id'])['item_id'] is None
    orders.match(db, oid, row['id'], item_id=world.brick, color_id=world.red)
    orders.phase(db, oid, other, 'review')
    orders.phase(db, oid, other, 'reopen')
    orders.phase(db, oid, other, 'review')
    orders.phase(db, oid, other, 'save', {str(row['id']): lid})
    assert orders.detail(db, oid)['ordered'] == 3                                   # paired: counted once
    orders.received(db, oid, {lid: 3})
    hold = orders.hold(db, oid, lid, True)
    with pytest.raises(ValueError, match='Match the line'):
        orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=1)])
    with pytest.raises(ValueError, match='Finish reviews'):
        orders.reconcile(db, oid)
    orders.undo(db, hold)
    orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=3)])
    assert len(orders.detail(db, oid)['allocations']) == 1


def test_pairs_must_share_item_colour_and_condition(world, coll):
    db = coll.db
    oid, did, lid = saved(db)
    second = orders.import_document(db, 'xml', XML.replace('<CONDITION>U', '<CONDITION>N'), choice=oid)
    new = next(r['id'] for r in orders.lines(db, oid) if r['document_id'] == second['document_id'])
    orders.phase(db, oid, second['document_id'], 'review')
    with pytest.raises(ValueError, match='Pairs must share'):
        orders.phase(db, oid, second['document_id'], 'save', {str(new): lid})


# ---------- the documents ----------

def test_email_api_and_xml_keep_the_provider_s_words_and_refuse_duplicates(world, coll, monkeypatch):
    db = coll.db
    brick_name = db.execute('SELECT name FROM item WHERE id=?', (world.brick,)).fetchone()[0]
    text = (f'* Batch #1 (submitted Oct 12, 2026)\n[Used] Red {brick_name} (x3) ... EUR 0.12 each = EUR 0.36\n'
            '[New] Mystery lot (x2) ... EUR 1.00 each = EUR 2.00')
    result = orders.import_document(db, 'email', text)
    first, second = orders.lines(db, result['order_id'])
    assert (first['item_id'], first['color_id'], first['batch'], first['submitted'], first['line_total']) == (world.brick, world.red, 1, 'Oct 12, 2026', '0.36')
    assert (first['raw_color_name'], first['raw_color_id'], first['raw_name']) == ('Red', 5, brick_name)
    assert second['item_id'] is None and second['condition'] == 'new' and second['raw_name'] == 'Mystery lot'
    assert orders.get(db, result['order_id'])['date_ordered'] == '2026-10-12'
    assert orders.import_document(db, 'email', text)['duplicate']
    monkeypatch.setattr(orders.BrickLink, 'list_orders', lambda self: [dict(order_id=123, store_name='Test store', cost=dict(grand_total='4.00', currency_code='EUR'))])
    monkeypatch.setattr(orders.BrickLink, 'order_items', lambda self, n: [[dict(item=dict(type='PART', no='3001', name='Synthetic part'), color_id=5, new_or_used='N', quantity=2, unit_price='2.00')]])
    api = orders.import_document(db, 'api', number=123)
    order = orders.get(db, api['order_id'])
    assert (order['cost'], order['currency'], order['store']) == ('4.00', 'EUR', 'Test store')
    assert orders.lines(db, api['order_id'])[0]['item_id'] == world.brick
    assert orders.import_document(db, 'api', number=123)['duplicate']
    with pytest.raises(ValueError):
        orders.import_document(db, 'xml', '<!DOCTYPE INVENTORY>' + XML)
    with pytest.raises(ValueError):
        orders.import_document(db, 'xml', XML.replace('0.12', 'nan'))
    with pytest.raises(ValueError, match='New or Used'):
        orders.import_document(db, 'xml', XML.replace('<CONDITION>U', '<CONDITION>X'))


def test_an_email_item_name_that_matches_several_items_waits_for_the_person(world, coll):
    db = coll.db
    name = db.execute('SELECT name FROM item WHERE id=?', (world.brick,)).fetchone()[0]
    coll.sql('UPDATE item SET name=? WHERE id=?', (name, world.plate))
    result = orders.import_document(db, 'email', f'[Used] Red {name} (x1) ... EUR 1.00 each = EUR 1.00')
    row = orders.lines(db, result['order_id'])[0]
    assert row['item_id'] is None and sorted(s['item_id'] for s in json.loads(row['suggestions_json'])) == sorted([world.brick, world.plate])


def test_a_second_document_links_to_an_order_and_undo_leaves_the_provenance(world, coll):
    db = coll.db
    oid, did, lid = saved(db)
    assert orders.import_document(db, 'xml', XML, choice=oid)['duplicate']
    text = '[Used] Mystery lot (x3) ... EUR 0.12 each = EUR 0.36'
    other = orders.import_document(db, 'email', text, choice=oid)
    assert not other['duplicate'] and orders.get(db, oid)['currency'] == 'EUR'            # the e-mail has no total, and its currency stands (M.12)
    record = db.execute("SELECT payload FROM source_record WHERE kind='order_document:email'").fetchone()[0]
    assert json.loads(record)['text'] == text
    document = db.execute('SELECT * FROM order_document WHERE id=?', (other['document_id'],)).fetchone()
    assert document['raw_record_id'] and document['phase'] == 'draft'
    orders.undo(db, other['event_id'])
    assert db.execute("SELECT payload FROM source_record WHERE kind='order_document:email'").fetchone()[0] == record
    assert db.execute('SELECT phase FROM order_document WHERE id=?', (other['document_id'],)).fetchone()[0] == 'undone'


def test_a_known_price_and_its_currency_fill_an_order_once(world, coll, monkeypatch):
    db = coll.db
    oid, did, lid = saved(db)
    header = '<ORDER><ORDERID>555</ORDERID><STORENAME>Synthetic store</STORENAME><COST>12.50</COST><CURRENCY>EUR</CURRENCY>'
    document = '<ORDERS>' + header + '<ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3023</ITEMID><COLOR>1</COLOR><QTY>1</QTY><CONDITION>N</CONDITION></ITEM></ORDER></ORDERS>'
    linked = orders.import_document(db, 'xml', document, choice=oid)
    order = orders.get(db, oid)
    assert (order['bricklink_order_id'], order['store'], order['cost'], order['currency']) == ('555', 'Synthetic store', '12.50', 'EUR')
    orders.undo(db, linked['event_id'])
    order = orders.get(db, oid)
    assert (order['bricklink_order_id'], order['store'], order['cost'], order['currency']) == (None, None, None, None)


def test_document_undo_dependency_order_and_preserved_provenance(world, coll):
    db = coll.db
    result = orders.import_document(db, 'xml', XML)
    oid, did = result['order_id'], result['document_id']
    review = orders.phase(db, oid, did, 'review')
    save = orders.phase(db, oid, did, 'save')
    lid = orders.detail(db, oid)['saved'][0]['id']
    received = orders.received(db, oid, {lid: 2})
    with pytest.raises(errors.UndoBlocked, match='received'):
        orders.undo(db, save)
    for event in (received, save, review, result['event_id']):
        orders.undo(db, event)
    detail = orders.detail(db, oid)
    assert detail['documents'][0]['phase'] == 'undone' and detail['lines'][0]['raw_text'] and not detail['saved']
    assert orders.import_document(db, 'xml', XML)['duplicate']                      # the document stays: it is never imported twice


# ---------- counting and allocating ----------

def test_copy_and_stock_allocation_derived_completeness_and_undo(world, coll):
    db = coll.db
    coll.mark(world.copy_a, '3001', '4', missing=3)
    before = tables(db)
    oid, did, lid = saved(db)
    received = orders.received(db, oid, {lid: 3})
    gap = gap_of(db, oid, lid, world.copy_a)
    assert gap['need'] == 3 and gap['copy']['label']
    allocated = orders.allocate(db, oid, [dict(line_id=lid, target_type='copy', copy_id=gap['copy_id'], target=gap['target'], target_id=gap['target_id'], quantity=2),
                                          dict(line_id=lid, target_type='stock', quantity=1, storage_id=world.shelf, lot_id=world.bag)])
    assert db.execute('SELECT missing FROM copy_part WHERE id=?', (gap['target_id'],)).fetchone()[0] == 1
    rows = [dict(r) for r in db.execute('SELECT * FROM allocation WHERE order_id=? ORDER BY id', (oid,))]
    assert [(r['target_kind'], r['kind'], r['qty'], r['state'], r['item_id'], r['color_id']) for r in rows] == [
        ('copy', 'missing_part', 2, 'applied', world.brick, world.red), ('stock', 'loose_part', 1, 'applied', world.brick, world.red)]
    assert (rows[0]['copy_id'], rows[0]['copy_part_id'], rows[0]['intent_before'], rows[0]['intent_after']) == (world.copy_a, gap['target_id'], 3, 1)
    stock = db.execute('SELECT * FROM stock WHERE id=?', (rows[1]['stock_id'],)).fetchone()
    assert (stock['quantity'], stock['storage_id'], stock['lot_id'], stock['condition']) == (4, world.shelf, world.bag, 'used')       # onto the row with that key
    with pytest.raises(errors.UndoBlocked, match='allocations'):
        orders.undo(db, received)                                                       # allocations first
    with pytest.raises(ValueError, match='Received quantity'):
        orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=1)])
    orders.undo(db, allocated)
    assert {r[0] for r in db.execute('SELECT state FROM allocation WHERE order_id=?', (oid,))} == {'undone'}
    orders.undo(db, received)
    after = tables(db)
    for table in ('copy', 'copy_part', 'copy_figure', 'copy_flag', 'stock', 'stock_part'):
        assert after[table] == before[table], table                                      # the collection is as before
    assert orders.detail(db, oid)['received'] == 0
    assert db.execute('PRAGMA foreign_key_check').fetchall() == [] and db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_reconcile_closes_the_order_and_undo_reopens_it(world, coll):
    db = coll.db
    oid, did, lid = saved(db)
    orders.received(db, oid, {lid: 3})
    allocated = orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=3)])
    reconciled = orders.reconcile(db, oid)
    assert orders.get(db, oid)['status'] == 'Reconciled' and orders.listing(db)[0]['phase'] == 'Reconciled'
    orders.undo(db, reconciled)
    assert orders.get(db, oid)['status'] is None
    orders.undo(db, allocated)


def test_a_derived_copy_follows_its_gaps_and_a_manual_one_does_not(world, coll):
    db = coll.db
    coll.mark(world.copy_a, '3001', '4', missing=1)
    oid, did, lid = saved(db, XML.replace('<QTY>3', '<QTY>1'))
    orders.received(db, oid, {lid: 1})
    gap = gap_of(db, oid, lid, world.copy_a)
    coll.sql("UPDATE copy SET completeness='incomplete',completeness_source='derived' WHERE id=?", (world.copy_a,))
    event = orders.allocate(db, oid, [dict(line_id=lid, target_type='copy', copy_id=gap['copy_id'], target='part', target_id=gap['target_id'], quantity=1)])
    assert db.execute('SELECT missing,damaged FROM copy_part WHERE id=?', (gap['target_id'],)).fetchone()[:] == (0, 0)
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (world.copy_a,)).fetchone()[0] != 'incomplete'
    orders.undo(db, event)
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (world.copy_a,)).fetchone()[0] == 'incomplete'
    coll.sql("UPDATE copy SET completeness='complete',completeness_source='manual' WHERE id=?", (world.copy_a,))
    orders.allocate(db, oid, [dict(line_id=lid, target_type='copy', copy_id=gap['copy_id'], target='part', target_id=gap['target_id'], quantity=1)])
    assert db.execute('SELECT completeness FROM copy WHERE id=?', (world.copy_a,)).fetchone()[0] == 'complete'


def test_the_copy_status_guard_refuses_undo_after_a_status_change(world, coll):
    db = coll.db
    coll.mark(world.copy_a, '3001', '4', missing=1)
    oid, did, lid = saved(db, XML.replace('<QTY>3', '<QTY>1'))
    orders.received(db, oid, {lid: 1})
    gap = gap_of(db, oid, lid, world.copy_a)
    event = orders.allocate(db, oid, [dict(line_id=lid, target_type='copy', copy_id=gap['copy_id'], target='part', target_id=gap['target_id'], quantity=1)])
    coll.sql('DELETE FROM copy_flag WHERE copy_id=? AND flag_id=?', (world.copy_a, world.checked))
    with pytest.raises(errors.UndoBlocked, match='copy status'):
        orders.undo(db, event)
    coll.sql('INSERT INTO copy_flag(copy_id,flag_id) VALUES(?,?)', (world.copy_a, world.checked))
    orders.undo(db, event)


def test_a_stock_allocation_refuses_undo_once_the_stock_changed(world, coll):
    db = coll.db
    oid, did, lid = saved(db)
    orders.received(db, oid, {lid: 3})
    event = orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=2)])
    stock = db.execute('SELECT stock_id FROM allocation WHERE order_id=?', (oid,)).fetchone()[0]
    coll.sql('UPDATE stock SET quantity=quantity-1 WHERE id=?', (stock,))
    with pytest.raises(errors.UndoBlocked, match='changed'):
        orders.undo(db, event)


def test_physical_booklets_boxes_and_whole_figures_fill_their_gaps(world, coll):
    db = coll.db
    coll.sql('DELETE FROM copy_flag WHERE copy_id=? AND flag_id IN (?,?)', (world.copy_a, world.box, world.booklet_flag))
    coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    coll.local('box', 'Syn Castle Keep box', born_key='1000-1')
    for letter, target, flag in [('I', 'instructions', world.booklet_flag), ('O', 'box', world.box)]:
        oid, did, lid = saved(db, inventory(line_of(letter, '1000-1', qty=1)))
        orders.received(db, oid, {lid: 1})
        assert world.copy_a in [g['copy_id'] for g in orders.destinations(db, orders.detail(db, oid)['saved'])[lid]]
        event = orders.allocate(db, oid, [dict(line_id=lid, target_type='copy', copy_id=world.copy_a, target=target, target_id=world.copy_a, quantity=1)])
        assert db.execute('SELECT 1 FROM copy_flag WHERE copy_id=? AND flag_id=?', (world.copy_a, flag)).fetchone()
        assert db.execute('SELECT kind FROM allocation WHERE id=(SELECT max(id) FROM allocation)').fetchone()[0] == target
        orders.undo(db, event)
        assert not db.execute('SELECT 1 FROM copy_flag WHERE copy_id=? AND flag_id=?', (world.copy_a, flag)).fetchone()
    oid, did, lid = saved(db, inventory(line_of('M', 'syn-fig-0004', qty=1)))
    orders.received(db, oid, {lid: 1})
    gap = gap_of(db, oid, lid, world.copy_a, 'figure')
    event = orders.allocate(db, oid, [dict(line_id=lid, target_type='copy', copy_id=gap['copy_id'], target='figure', target_id=gap['target_id'], quantity=1)])
    assert db.execute('SELECT missing FROM copy_figure WHERE id=?', (gap['target_id'],)).fetchone()[0] == 0
    assert db.execute('SELECT kind,copy_figure_id FROM allocation WHERE id=(SELECT max(id) FROM allocation)').fetchone()[:] == ('missing_figure', gap['target_id'])
    orders.undo(db, event)
    assert db.execute('SELECT missing FROM copy_figure WHERE id=?', (gap['target_id'],)).fetchone()[0] == 1


def test_a_set_line_cannot_go_to_loose_stock(world, coll):
    db = coll.db
    oid, did, lid = saved(db, inventory(line_of('S', '1000-1', qty=1)))
    orders.received(db, oid, {lid: 1})
    with pytest.raises(ValueError, match='copy'):
        orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=1)])
    assert db.execute('SELECT count(*) FROM allocation').fetchone()[0] == 0


def test_counts_stay_between_allocated_and_ordered(world, coll):
    db = coll.db
    oid, did, lid = saved(db)
    for bad in (4, -1, 'x'):
        with pytest.raises(ValueError):
            orders.received(db, oid, {lid: bad})
    orders.received(db, oid, {lid: 3})
    orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=2)])
    with pytest.raises(ValueError, match='between allocated and ordered'):
        orders.received(db, oid, {lid: 1})
    assert [tuple(r) for r in db.execute('SELECT old,new FROM line_receipt_log ORDER BY id')] == [(0, 3)]


def test_the_short_list_names_what_is_still_missing(world, coll):
    db = coll.db
    oid, did, lid = saved(db, inventory(line_of('P', '3001', colour=5, qty=3), line_of('M', 'syn-fig-0004', qty=2, condition='N')))
    both = [r['id'] for r in orders.detail(db, oid)['saved']]
    orders.received(db, oid, {both[0]: 2, both[1]: 2})
    result = orders.short_export(db, oid)
    assert 'MINQTY>1<' in result['xml'] and '3001' in result['xml'] and 'syn-fig-0004' not in result['xml'] and result['skipped'] == []
    coll.sql("DELETE FROM item_link WHERE item_id=? AND provider='bricklink'", (world.brick,))
    result = orders.short_export(db, oid)
    assert '3001' not in result['xml'] and result['skipped'][0]['why'] == 'no BrickLink number'


# ---------- atomicity and the web transport ----------

def test_a_failed_save_changes_nothing(world, coll):
    db = coll.db
    oid, did, lid = saved(db)
    orders.received(db, oid, {lid: 3})
    before = tables(db)
    db.execute("CREATE TEMP TRIGGER reject_allocation BEFORE INSERT ON main.allocation BEGIN SELECT RAISE(ABORT, 'no'); END")
    with pytest.raises(sqlite3.IntegrityError):
        orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=2)])
    assert tables(db) == before
    db.execute('DROP TRIGGER reject_allocation')
    db.execute("CREATE TEMP TRIGGER reject_event BEFORE INSERT ON main.event WHEN NEW.entity_kind='orders' BEGIN SELECT RAISE(ABORT, 'no'); END")
    with pytest.raises(sqlite3.IntegrityError):
        orders.received(db, oid, {lid: 2})
    with pytest.raises(sqlite3.IntegrityError):
        orders.import_document(db, 'xml', XML.replace('<QTY>3', '<QTY>2'))
    assert tables(db) == before


def test_300_lines_import_and_allocate_in_linear_statements(world, coll):
    db = coll.db
    statements = []
    db.set_trace_callback(statements.append)
    result = orders.import_document(db, 'xml', inventory(*[line_of('P', '3001', colour=5, qty=n) for n in range(1, 301)]))
    db.set_trace_callback(None)
    assert (result['placed'], result['unplaced']) == (300, 0) and len(statements) < 6000, len(statements)
    oid, did = result['order_id'], result['document_id']
    orders.phase(db, oid, did, 'review')
    orders.phase(db, oid, did, 'save', {})
    rows = orders.detail(db, oid)['saved']
    orders.received(db, oid, {r['id']: r['qty'] for r in rows})
    statements.clear()
    db.set_trace_callback(statements.append)
    orders.allocate(db, oid, [dict(line_id=r['id'], target_type='stock', quantity=r['qty']) for r in rows])
    db.set_trace_callback(None)
    assert len(statements) < 6000, len(statements)
    assert db.execute('SELECT sum(qty) FROM allocation').fetchone()[0] == sum(r['qty'] for r in rows)


def test_the_web_flow_import_review_count_hold_and_undo(world, client, token, coll, read):
    def post(action, **data):
        return client.post('/workbench/orders/action/' + action, json=dict(csrf_token=token, **data))
    response = client.get('/workbench/orders')
    assert response.status_code == 200 and 'data-web-ui="toni"' in response.text and response.headers['Cache-Control'] == 'no-store'
    assert client.post('/workbench/orders/action/import', json=dict(source='xml', text=XML)).status_code == 400            # no CSRF token
    imported = post('import', source='xml', text=XML)
    assert imported.status_code == 200, imported.json
    oid, did = imported.json['order_id'], imported.json['document_id']
    assert 'Resume review' in client.get(imported.json['url']).text
    assert post('import', source='xml', text=XML).json['duplicate']
    for action in ('review', 'save'):
        assert post(action, order_id=oid, document_id=did).status_code == 200
    with read() as db:
        lid = orders.detail(db, oid)['saved'][0]['id']
    assert post('received', order_id=oid, counts={str(lid): 2}).status_code == 200
    assert '1 short' in client.get(f'/workbench/orders/{oid}').text
    short = client.get(f'/workbench/orders/{oid}/short.xml')
    assert 'MINQTY>1' in short.get_data(as_text=True) and short.mimetype == 'application/xml'
    for held in (True, False):
        response = post('hold', order_id=oid, line_id=lid, held=held)
        assert response.status_code == 200
        assert post('undo', event_id=response.json['event_id']).status_code == 200
        again = post('undo', event_id=response.json['event_id'])
        assert again.status_code == 400 and 'already been undone' in again.json['message']
    assert client.get('/workbench/orders/9999').status_code == 404
    assert post('nonsense').status_code == 404


def test_a_cross_site_write_is_refused(world, client, token):
    response = client.post('/workbench/orders/action/import', json=dict(csrf_token=token, source='xml', text=XML), headers={'Origin': 'https://other.test'})
    assert response.status_code == 403


def test_allocated_stock_follows_a_storage_archive(world, coll):
    """The order-allocation part of the 3.3 storage route test: stock an allocation made sits in a storage; archiving it moves the stock to
    Not stored in one receipt, and one Undo puts it back."""
    from brickwork.core import ledger
    db = coll.db
    oid, did, lid = saved(db)
    orders.received(db, oid, {lid: 3})
    box = ledger.storage_save(db, None, 'Order box')[0]
    orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=3, storage_id=box)])
    stock_id = db.execute('SELECT stock_id FROM allocation WHERE order_id=?', (oid,)).fetchone()[0]
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (stock_id,)).fetchone()[0] == box
    archived = ledger.storage_archive(db, box, move_to_unstored=True)
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (stock_id,)).fetchone()[0] is None
    ledger.undo(db, archived)
    assert db.execute('SELECT storage_id FROM stock WHERE id=?', (stock_id,)).fetchone()[0] == box


# ---------- review findings (Codex, M.8h) ----------

def test_a_match_cannot_be_undone_once_its_document_is_saved(world, coll):
    db = coll.db
    result = orders.import_document(db, 'xml', inventory(line_of('P', 'nowhere', colour=5)))
    oid, did = result['order_id'], result['document_id']
    line = orders.lines(db, oid)[0]['id']
    event = orders.match(db, oid, line, item_id=world.brick, color_id=world.red)
    orders.phase(db, oid, did, 'review')
    orders.phase(db, oid, did, 'save')
    orders.received(db, oid, {line: 3})
    orders.allocate(db, oid, [dict(line_id=line, target_type='stock', quantity=3)])
    with pytest.raises(errors.UndoBlocked):
        orders.undo(db, event)
    assert orders.lines(db, oid)[0]['item_id'] == world.brick


def test_a_match_undo_is_refused_for_a_saved_line_even_without_counts(world, coll):
    db = coll.db
    result = orders.import_document(db, 'xml', inventory(line_of('P', 'nowhere', colour=5)))
    oid, did = result['order_id'], result['document_id']
    event = orders.match(db, oid, orders.lines(db, oid)[0]['id'], item_id=world.brick, color_id=world.red)
    orders.phase(db, oid, did, 'review')
    with pytest.raises(errors.UndoBlocked, match='Reopen'):
        orders.undo(db, event)


def test_workbench_can_be_imported_first_in_a_fresh_interpreter():
    import subprocess
    import sys
    for first in ('brickwork.core.workbench', 'brickwork.core.orders', 'brickwork.core.undo', 'brickwork.core.add'):
        done = subprocess.run([sys.executable, '-B', '-c', f'import {first}'], capture_output=True, text=True)
        assert done.returncode == 0, (first, done.stderr[-400:])


def test_a_header_total_without_a_currency_stores_neither_and_imports_the_lines(world, coll):
    document = '<ORDER><ORDERID>556</ORDERID><COST>12.50</COST>' + line_of('P', '3001', colour=5) + '</ORDER>'
    result = orders.import_document(coll.db, 'xml', document)
    order = orders.get(coll.db, result['order_id'])
    assert (order['cost'], order['currency'], order['bricklink_order_id']) == (None, None, '556')
    assert result['placed'] == 1
