"""API v2 orders (M.11d, issue #113): documents, lines, receipts, allocation, reconcile, the downloads and Undo. Ported from test_bw_api_m6,
test_bw_orders_storage_api and test_bw_orders_export_44_api onto the 4.0 order tables; the order rules themselves are tests/test_bw_orders_storage.py.
Every answer is validated against `openapi-v2.yaml`. Invented data, no network."""
import csv
import io

import pytest

from brickwork.core import orders
from tests.api2 import call, events, row, rows, stored_token, v2, validate, wire, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import client  # noqa: F401

RED = 5                                                       # the BrickLink colour number of the world's red
XML = ('<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID><COLOR>5</COLOR><QTY>3</QTY><CONDITION>U</CONDITION><PRICE>0.12</PRICE></ITEM>'
       '<ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>nowhere</ITEMID><COLOR>5</COLOR><QTY>1</QTY><CONDITION>N</CONDITION><PRICE>1.00</PRICE></ITEM></INVENTORY>')
ONE = '<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID><COLOR>5</COLOR><QTY>3</QTY><CONDITION>U</CONDITION><PRICE>0.12</PRICE></ITEM></INVENTORY>'


def send(v2, path, body=None, method='post', key=None, **kwargs):
    response = write(v2, path, method, body, key=key or True, **kwargs)
    assert response.status_code == 200, (path, response.text)
    return response


def imported(v2, text=ONE, **extra):
    return send(v2, '/orders/documents', dict(source='xml', text=text, **extra), key=True)


def saved(v2, text=ONE):
    made = imported(v2, text)
    order, document = made.json['data']['order_id'], made.json['data']['document_id']
    for action in ('review', 'save'):
        send(v2, f'/orders/{order}/documents/{document}/phase', {'action': action})
    line = call(v2, f'/orders/{order}').json['data']['lines'][0]['id']
    return order, document, line


# ---------- documents and lines ----------

def test_a_document_is_imported_as_a_draft_replays_and_a_duplicate_writes_nothing(v2, world, pair):
    before = len([e for e in events(pair) if e['entity_kind'] != 'bw_api'])
    made = send(v2, '/orders/documents', dict(source='xml', text=XML), key='doc-1')
    validate(made, 'post_orders_documents')
    data = made.json['data']
    assert (data['duplicate'], data['placed'], data['unplaced']) == (False, 1, 1) and data['event_id'] == made.json['event_id'] and made.json['undo_url']
    assert len([e for e in events(pair) if e['entity_kind'] != 'bw_api']) == before + 1
    assert send(v2, '/orders/documents', dict(source='xml', text=XML), key='doc-1').json['idempotent_replay'] is True
    duplicate = send(v2, '/orders/documents', dict(source='xml', text=XML), key='doc-2')
    assert duplicate.json['data']['duplicate'] is True and duplicate.json['event_id'] is None
    assert len([e for e in events(pair) if e['entity_kind'] != 'bw_api']) == before + 1
    assert write(v2, '/orders/documents', body=dict(source='xml', text=XML), key=False).status_code == 428
    assert all(e['via'] == 'api' and e['actor'] == 'bootstrap' for e in events(pair, "entity_kind='orders'"))


def test_an_import_that_fails_in_its_last_step_leaves_nothing(v2, world, pair, monkeypatch):
    from brickwork.core import admin
    tables = lambda: {t: rows(pair, f'SELECT * FROM {t}') for t in ('purchase_order', 'order_document', 'order_line', 'event')}
    before = tables()
    real = admin.audit

    def fail(db, entity, *args, **kwargs):
        if entity.startswith('bw_api'):
            raise RuntimeError('Synthetic audit failure')
        return real(db, entity, *args, **kwargs)
    monkeypatch.setattr(admin, 'audit', fail)
    assert write(v2, '/orders/documents', body=dict(source='xml', text=ONE), key='doc-fail').status_code == 500
    assert tables() == before
    monkeypatch.setattr(admin, 'audit', real)
    assert write(v2, '/orders/documents', body=dict(source='xml', text=ONE), key='doc-fail').status_code == 200            # the claim was released


def test_an_email_and_a_pulled_order_are_documents_too(v2, world, monkeypatch):
    calls = []

    def pull(db, number):
        calls.append(number)
        return orders.parse_xml(ONE)
    monkeypatch.setattr(orders, 'api_data', pull)
    data = dict(source='api', number='123456')
    made = send(v2, '/orders/documents', data, key='pull-1')
    assert send(v2, '/orders/documents', data, key='pull-1').json['idempotent_replay'] is True and calls == ['123456']
    assert call(v2, f"/orders/{made.json['data']['order_id']}").json['data']['documents'][0]['source'] == 'api'
    assert write(v2, '/orders/documents', body=dict(source='api', number='x'), key='pull-2').status_code == 422
    assert write(v2, '/orders/documents', body=dict(source='xml', text='   '), key='pull-3').status_code == 422
    assert write(v2, '/orders/documents', body=dict(source='fax', text='x'), key='pull-4').status_code == 422


def test_an_order_is_listed_and_read_with_its_documents_and_lines(v2, world, pair):
    order = imported(v2, XML).json['data']['order_id']
    listed = call(v2, '/orders')
    validate(listed, 'get_orders')
    assert [(o['id'], o['lines'], o['pieces'], o['received'], o['phase']) for o in listed.json['data']] == [(order, 0, 0, 0, 'Draft')]
    one = call(v2, f'/orders/{order}')
    validate(one, 'get_orders_by_id')
    data = one.json['data']
    assert data['order']['id'] == order and [d['phase'] for d in data['documents']] == ['draft']
    placed, unplaced = data['lines'][0], data['lines'][1]
    assert placed['item']['id'] == world.brick and placed['color']['id'] == world.red and (placed['qty'], placed['condition']) == (3, 'used')
    assert unplaced['item'] is None and unplaced['unplaced'] is True and unplaced['raw']['item_no'] == 'nowhere'
    assert call(v2, '/orders?status=Nope').json['data'] == [] and call(v2, '/orders?bricklink_order_id=').status_code == 200
    assert call(v2, '/orders?colour=x').status_code == 400
    assert call(v2, '/orders/999').status_code == 404 and call(v2, '/orders/x').status_code == 404
    assert call(v2, f'/orders/{order}', token=stored_token(pair, ['read'])).status_code == 200


def test_a_draft_line_is_matched_by_number_and_colour_and_undone(v2, world, pair):
    made = imported(v2, XML)
    order = made.json['data']['order_id']
    lines = call(v2, f'/orders/{order}').json['data']['lines']
    stray = lines[1]['id']
    matched = send(v2, f'/orders/{order}/lines/{stray}', {'item': {'provider': 'rebrickable', 'kind': 'part', 'key': '3023'}, 'color': 15}, method='patch')
    validate(matched, 'patch_orders_by_id_lines_by_line_id')
    after = call(v2, f'/orders/{order}').json['data']['lines'][1]
    assert after['item']['id'] == world.plate and after['color']['id'] == world.white and after['unplaced'] is False
    assert write(v2, f"/events/{matched.json['event_id']}/undo").status_code == 200
    assert call(v2, f'/orders/{order}').json['data']['lines'][1]['item'] is None
    assert write(v2, f'/orders/{order}/lines/{stray}', 'patch', {'item': {'provider': 'rebrickable', 'kind': 'part', 'key': '3023'}}).status_code == 422          # a part needs its colour
    assert write(v2, f'/orders/{order}/lines/{stray}', 'patch', {'item': {'provider': 'rebrickable', 'kind': 'part', 'key': 'zzz'}, 'color': 15}).status_code == 422
    assert write(v2, f'/orders/{order}/lines/999', 'patch', {'item': {'id': world.plate}, 'color': world.white}).status_code == 404


def test_a_document_is_reviewed_reopened_and_saved_and_a_line_is_held(v2, world, pair):
    order, document, line = saved(v2)
    phase = lambda action: write(v2, f'/orders/{order}/documents/{document}/phase', 'post', {'action': action})
    assert phase('review').status_code == 422                                   # it is saved
    held = send(v2, f'/orders/{order}/lines/{line}/hold', {'held': True}, method='put')
    validate(held, 'put_orders_by_id_lines_by_line_id_hold')
    assert call(v2, f'/orders/{order}').json['data']['lines'][0]['state'] == 'held'
    send(v2, f'/orders/{order}/lines/{line}/hold', {'held': False}, method='put')
    assert write(v2, f'/orders/{order}/lines/{line}/hold', 'put', {'held': 'yes'}).status_code == 422
    assert write(v2, f'/orders/{order}/documents/99/phase', 'post', {'action': 'review'}).status_code == 404
    assert write(v2, f'/orders/{order}/documents/{document}/phase', 'post', {'action': 'dance'}).status_code == 422


# ---------- receipts, allocation, reconcile ----------

def test_received_allocated_reconciled_and_every_step_undone(v2, world, pair):
    order, document, line = saved(v2)
    receipt = send(v2, f'/orders/{order}/received', {'counts': {str(line): 3}})
    validate(receipt, 'post_orders_by_id_received')
    assert call(v2, f'/orders/{order}').json['data']['lines'][0]['received'] == 3 and call(v2, f'/orders/{order}').json['data']['order']['phase'] == 'Counting'
    choice = {'line_id': line, 'target_type': 'stock', 'quantity': 3}
    allocated = send(v2, f'/orders/{order}/allocate', {'chosen': [choice]}, key='alloc-1')
    validate(allocated, 'post_orders_by_id_allocate')
    assert send(v2, f'/orders/{order}/allocate', {'chosen': [choice]}, key='alloc-1').json['idempotent_replay'] is True
    assert row(pair, 'SELECT count(*) AS n FROM allocation')['n'] == 1
    blocked = write(v2, f"/events/{receipt.json['event_id']}/undo")
    assert blocked.status_code == 409 and blocked.json['code'] == 'undo_blocked'
    assert 'MINQTY' not in call(v2, f'/orders/{order}/short.xml').text
    reconciled = send(v2, f'/orders/{order}/reconcile')
    validate(reconciled, 'post_orders_by_id_reconcile')
    assert call(v2, f'/orders/{order}').json['data']['order']['status'] == 'Reconciled'
    for event in (reconciled, allocated, receipt):
        assert write(v2, f"/events/{event.json['event_id']}/undo").status_code == 200
    assert row(pair, 'SELECT received FROM line_receipt')['received'] == 0 and row(pair, 'SELECT state FROM allocation')['state'] == 'undone'
    assert write(v2, f"/events/{allocated.json['event_id']}/undo").json['data']['already_undone'] is True


def test_the_short_list_names_what_is_missing_and_the_downloads_are_files(v2, world, pair):
    order, document, line = saved(v2)
    short = call(v2, f'/orders/{order}/short.xml')
    assert short.status_code == 200 and short.mimetype == 'application/xml' and '<MINQTY>3</MINQTY>' in short.text and '<ITEMID>3001</ITEMID>' in short.text
    summary = call(v2, '/orders/export.csv?kind=summary')
    assert summary.status_code == 200 and summary.mimetype == 'text/csv' and list(csv.reader(io.StringIO(summary.text)))[0][0] == 'Order'
    assert call(v2, '/orders/export.csv').status_code == 200
    assert call(v2, '/orders/export.csv?from=bad').status_code == 422 and call(v2, '/orders/export.csv?page=2').status_code == 400
    assert call(v2, '/orders/999/short.xml').status_code == 404


def test_allocation_is_atomic_and_a_retry_runs_against_the_current_counts(v2, world, pair):
    order, document, line = saved(v2)
    send(v2, f'/orders/{order}/received', {'counts': {str(line): 2}})
    choices = [{'line_id': line, 'target_type': 'stock', 'quantity': 1}, {'line_id': line, 'target_type': 'stock', 'quantity': 2}]
    refused = write(v2, f'/orders/{order}/allocate', body={'chosen': choices}, key='atomic-1')
    assert refused.status_code == 422 and row(pair, 'SELECT count(*) AS n FROM allocation')['n'] == 0
    stock = row(pair, 'SELECT count(*) AS n FROM stock')['n']
    retried = send(v2, f'/orders/{order}/allocations/retry', {'chosen': choices[:1]}, key='atomic-2')
    validate(retried, 'post_orders_by_id_allocations_retry')
    assert row(pair, 'SELECT count(*) AS n FROM allocation')['n'] == 1 and row(pair, 'SELECT count(*) AS n FROM stock')['n'] in (stock, stock + 1)
    for path in ('allocate', 'allocations/retry'):
        assert write(v2, f'/orders/{order}/{path}', body={'chosen': choices[:1]}, key=False).status_code == 428
        assert write(v2, f'/orders/{order}/{path}', body={'chosen': [{'line_id': line, 'target_type': 'copy', 'quantity': 1}]}).status_code == 422


def test_the_review_the_allocations_and_the_history_page(v2, world, pair):
    order, document, line = saved(v2)
    send(v2, f'/orders/{order}/received', {'counts': {str(line): 3}})
    allocated = send(v2, f'/orders/{order}/allocate', {'chosen': [{'line_id': line, 'target_type': 'stock', 'quantity': 2}]})
    review = call(v2, f'/orders/{order}/allocation-review')
    validate(review, 'get_orders_by_id_allocation_review')
    assert review.json['data'][0]['available'] == 1 and review.json['data'][0]['line']['item']['id'] == world.brick
    assert any(d['copy_id'] == world.copy_a and d['target'] == 'part' for d in review.json['data'][0]['destinations'])
    listed = call(v2, f'/orders/{order}/allocations')
    validate(listed, 'get_orders_by_id_allocations')
    assert listed.json['data'][0]['qty'] == 2 and listed.json['data'][0]['target_type'] == 'stock' and listed.json['data'][0]['undo_event_id'] == allocated.json['event_id']
    history = call(v2, f'/orders/{order}/history')
    validate(history, 'get_orders_by_id_history')
    assert any(h['id'] == allocated.json['event_id'] and h['receipt'] == {'action': 'allocate'} and h['undo_available'] and h['via'] == 'api' for h in history.json['data'])
    assert [h['receipt']['action'] for h in history.json['data']][-1] == 'import'
    paged = call(v2, f'/orders/{order}/history?limit=2')
    assert len(paged.json['data']) == 2 and call(v2, f'/orders/{order}/history?limit=2&cursor=' + paged.json['page']['next_cursor']).status_code == 200
    for suffix in ('allocation-review', 'allocations', 'history'):
        assert call(v2, f'/orders/999/{suffix}').status_code == 404


def test_a_read_token_reads_orders_and_cannot_write_them(v2, world, pair):
    order, document, line = saved(v2)
    reader = stored_token(pair, ['read'], 'reader')
    assert write(v2, f'/orders/{order}/reconcile', token=reader).status_code == 403
    assert write(v2, '/orders/documents', body=dict(source='xml', text=ONE), token=reader).status_code == 403
    assert call(v2, f'/orders/{order}/history', token=reader).status_code == 200 and call(v2, '/orders/export.csv', token=reader).status_code == 200


# ---------- the cost of a page does not grow with the order ----------

@pytest.mark.parametrize('suffix', ['', '/allocation-review', '/allocations', '/history'])
def test_an_order_page_runs_the_same_number_of_queries_with_more_lines(v2, world, coll, pair, monkeypatch, suffix):
    from tests.test_api2_reads import Counting
    order, document, line = saved(v2)
    send(v2, f'/orders/{order}/received', {'counts': {str(line): 3}})
    send(v2, f'/orders/{order}/allocate', {'chosen': [{'line_id': line, 'target_type': 'stock', 'quantity': 1}]})
    counting = Counting(monkeypatch)
    assert call(v2, f'/orders/{order}{suffix}').status_code == 200
    small = len(counting.queries)
    for number in range(2, 302):
        coll.sql("INSERT INTO order_line(order_id,document_id,line_no,item_id,color_id,condition,state,qty,updated_at) VALUES(?,?,?,?,?, 'used','matched',1,'2026-10-26T12:00:00.000Z')",
                 (order, document, number, world.brick, world.red))
    counting.queries.clear()
    response = call(v2, f'/orders/{order}{suffix}?limit=200' if suffix else f'/orders/{order}')
    assert response.status_code == 200
    assert len(counting.queries) <= small + 2, (suffix, small, len(counting.queries))
    if suffix:
        assert len(response.json['data']) <= 200


def test_a_pulled_order_goes_through_the_bricklink_client_once_with_its_budget_and_never_shows_the_credentials(v2, world, pair, wire, monkeypatch):
    import json
    import os
    from tests.api2 import BL_ENV, bl, fake
    for name in BL_ENV:
        monkeypatch.setenv(name, fake())
    calls = []

    def reply(request):
        calls.append(request.full_url)
        data = ([[{'item': {'type': 'PART', 'no': '3001', 'name': 'Synthetic brick'}, 'color_id': RED, 'new_or_used': 'U', 'quantity': 3, 'unit_price': '0.12'}]]
                if request.full_url.endswith('/items') else [{'order_id': 123456, 'store_name': 'Synthetic store', 'cost': {'grand_total': '0.36', 'currency_code': 'EUR'}}])
        return bl(data)
    wire.replies['api.bricklink.com'] = reply
    made = send(v2, '/orders/documents', dict(source='api', number='123456'), key='pull-bl')
    assert len(calls) == 2
    assert send(v2, '/orders/documents', dict(source='api', number='123456'), key='pull-bl').json['idempotent_replay'] is True and len(calls) == 2
    assert all(os.environ[name] not in json.dumps(made.json) for name in BL_ENV)
    order = call(v2, f"/orders/{made.json['data']['order_id']}").json['data']
    assert order['order']['store'] == 'Synthetic store' and order['lines'][0]['item']['id'] == world.brick and order['documents'][0]['source'] == 'api'
    assert write(v2, f"/events/{made.json['event_id']}/undo").status_code == 200
    assert call(v2, f"/orders/{made.json['data']['order_id']}").json['data']['documents'][0]['phase'] == 'undone'


def test_a_receipt_the_api_made_is_undone_through_the_web_and_a_second_undo_changes_nothing(v2, client, world, pair):
    from tests.app4 import csrf
    from brickwork.core import ledger
    from contextlib import closing
    from brickwork.core.connect import connect
    order, document, line = saved(v2)
    with closing(connect(pair)) as db:
        destination, _ = ledger.storage_save(db, None, 'Destination')
    token = csrf(client)
    moved = send(v2, f'/storages/{destination}/contents', {'selections': [{'entity': 'copy', 'id': world.copy_b}]})
    received = send(v2, f'/orders/{order}/received', {'counts': {str(line): 2}})
    for route, page, event, check in (('storage', '/workbench/storage', moved.json['event_id'],
                                       lambda: row(pair, 'SELECT storage_id FROM copy WHERE id=?', (world.copy_b,))['storage_id'] is None),
                                      ('orders', f'/workbench/orders/{order}', received.json['event_id'],
                                       lambda: row(pair, 'SELECT received FROM line_receipt WHERE line_id=?', (line,))['received'] == 0)):
        assert f'data-undo-event="{event}"' in client.get(page).text
        url = f'/workbench/{route}/action/undo'
        assert client.post(url, json=dict(csrf_token=token, event_id=event)).status_code == 200
        assert check()
        count = len(events(pair))
        again = client.post(url, json=dict(csrf_token=token, event_id=event))
        assert again.status_code == 400 and 'already been undone' in again.json['message']
        assert len(events(pair)) == count
