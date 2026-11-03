"""Orders (M.11d, issue #113): a BrickLink purchase, its documents and lines, what was received and where it went.

The domain is `core/orders.py` (design 5: `purchase_order`, `order_document`, `order_line`, `line_receipt`, `allocation`); this module reads
the request, finds the order (`404`), calls the core writer and builds the contract's bodies. A line names its item and colour as the item
and colour bodies of section 2.1 (a line the importer could not place has none and carries the provider's own words under `raw`). Every
write is one `orders:<id>` event whose Undo restores the order rows; importing a document by BrickLink order number reaches the network
first, outside the transaction, and the import itself runs in the one that stores the answer. The CSV and the wanted-list XML are
downloads."""
import json
import re

from flask import Response

from ..core import errors, order_exports, orders, undo
from . import route
from .read import arguments, bodies, integer_id, page, reading, record, respond
from .write_collection import receipt
from .writes import Done, color_of, item_of, write


# ---------- bodies ----------

def order_body(r):
    return {'id': r['id'], 'bricklink_order_id': r['bricklink_order_id'], 'store': r['store'], 'seller': r['seller'], 'date_ordered': r['date_ordered'],
            'status': r['status'], 'cost': r['cost'], 'currency': r['currency'], 'phase': r['phase'], 'lines': r['lots'], 'pieces': r['pieces'],
            'received': r['received'], 'allocated': r['allocated'], 'held': r['held']}


def document_body(r):
    return {'id': r['id'], 'order_id': r['order_id'], 'source': r['source'], 'label': r['label'], 'phase': r['phase'], 'created_at': r['created_at'],
            'updated_at': r['updated_at']}


def line_bodies(db, rows):
    """`OrderLine` bodies for a set of order lines (rows of `orders.lines`): the items and colours (and the candidates of an unplaced line)
    in a fixed number of queries."""
    suggestions = {}
    for r in rows:
        try:
            suggestions[r['id']] = json.loads(r['suggestions_json']) if r.get('suggestions_json') else []
        except ValueError:
            suggestions[r['id']] = []
    book = bodies(db, items=[r['item_id'] for r in rows if r['item_id'] is not None] + [s['item_id'] for each in suggestions.values() for s in each],
                  colors=[r['color_id'] for r in rows])
    return [{'id': r['id'], 'order_id': r['order_id'], 'document_id': r['document_id'], 'document_phase': r['phase'], 'line_no': r['line_no'], 'state': r['state'],
             'item': book.item(r['item_id']) if r['item_id'] is not None else None, 'color': book.color(r['color_id']), 'unplaced': r['item_id'] is None,
             'condition': r['condition'], 'qty': r['qty'], 'unit_price': r['unit_price'], 'line_total': r['line_total'], 'remark': r['remark'],
             'raw': {'item_type': r['raw_item_type'], 'item_no': r['raw_item_no'], 'color_id': r['raw_color_id'], 'color_name': r['raw_color_name'],
                     'name': r['raw_name'], 'text': r['raw_text']},
             'received': r['received'], 'allocated': r['allocated'], 'paired_line_id': r['paired_line_id'],
             'suggestions': [{'item': book.item(s['item_id']), 'label': s['label']} for s in suggestions[r['id']]]} for r in rows]


def allocation_bodies(db, order_id):
    rows = orders.allocation_rows(db, order_id, orders.lines(db, order_id))
    book = bodies(db, items=[r['item_id'] for r in rows], colors=[r['color_id'] for r in rows])
    return [{'id': r['id'], 'confirm_id': r['confirm_id'], 'order_id': r['order_id'], 'line_id': r['line_id'], 'qty': r['qty'], 'state': r['state'],
             'target_type': r['target_kind'], 'kind': r['kind'], 'copy_id': r['copy_id'], 'copy_part_id': r['copy_part_id'], 'copy_figure_id': r['copy_figure_id'],
             'stock_id': r['stock_id'], 'item': book.item(r['item_id']), 'color': book.color(r['color_id']), 'intent_before': r['intent_before'],
             'intent_after': r['intent_after'], 'created_at': r['created_at'], 'applied_at': r['applied_at'], 'undone_at': r['undone_at'],
             'target_label': r['target_label'], 'undo_event_id': r['undo_event']} for r in rows]


def destination_body(book, gap):
    return {'copy_id': gap['copy_id'], 'target': gap['target'], 'target_id': gap['target_id'], 'need': gap['need'], 'item': book.item(gap['item_id']),
            'color': book.color(gap['color_id']), 'label': (gap.get('copy') or {}).get('label')}


def review_bodies(db, order_id):
    saved = [r for r in orders.lines(db, order_id) if r['phase'] == 'saved' and r['paired_line_id'] is None]
    where = orders.destinations(db, saved)
    book = bodies(db, items=[g['item_id'] for each in where.values() for g in each], colors=[g['color_id'] for each in where.values() for g in each])
    shown = {b['id']: b for b in line_bodies(db, saved)}
    return [{'id': r['id'], 'line': shown[r['id']], 'available': r['received'] - r['allocated'], 'destinations': [destination_body(book, g) for g in where[r['id']]]}
            for r in saved]


def order_row(db, identifier):
    """The listing row of an order (its counts and phase), `404` if there is none."""
    order_id = integer_id(identifier, 'order')
    found = next((r for r in orders.listing(db) if r['id'] == order_id), None)
    if found is None:
        raise errors.NotFound('No such order')
    return found


def history_bodies(db, order_id):
    rows = db.execute(f"""SELECT e.id, e.at, e.via, e.actor, e.field, {undo.undone_sql()} AS undone, {undo.undoable_sql()} AS undoable FROM main.event e
                          WHERE e.entity_kind=? AND e.entity_id=? ORDER BY e.id DESC""", (orders.ENTITY, str(order_id))).fetchall()
    return [{'id': r['id'], 'receipt': {'action': r['field']}, 'undone': bool(r['undone']), 'undo_available': bool(r['undoable']) and not r['undone'],
             'at': r['at'], 'via': r['via'], 'actor': r['actor']} for r in rows]


# ---------- reads ----------

@route('/orders')
@reading
def get_orders(db):
    args = arguments()
    direction = args.get('direction', 'asc')
    if direction not in ('asc', 'desc'):
        raise errors.UnknownFilter('direction is asc or desc')
    records = [record(r['id'], r['bricklink_order_id'] or '', bricklink_order_id=r['bricklink_order_id'] or '', status=r['status'] or '', _body=order_body(r))
               for r in orders.listing(db)]
    return page(records, {k: v for k, v in args.items() if k in ('cursor', 'limit', 'direction', 'bricklink_order_id', 'status')}, default_sort='number')


@route('/orders/<id>')
@reading
def get_orders_by_id(db, id):
    arguments()
    found = order_row(db, id)
    documents = [document_body(d) for d in db.execute('SELECT * FROM main.order_document WHERE order_id=? ORDER BY id', (found['id'],))]
    return respond({'order': order_body(found), 'documents': documents, 'lines': line_bodies(db, orders.lines(db, found['id']))})


@route('/orders/<id>/allocation-review')
@reading
def get_orders_by_id_allocation_review(db, id):
    args = arguments()
    found = order_row(db, id)
    records = [record(r['id'], str(r['id']).zfill(12), _body=r) for r in review_bodies(db, found['id'])]
    return page(records, args, default_sort='number')


@route('/orders/<id>/allocations')
@reading
def get_orders_by_id_allocations(db, id):
    args = arguments()
    found = order_row(db, id)
    records = [record(r['id'], str(r['id']).zfill(12), _body=r) for r in allocation_bodies(db, found['id'])]
    return page(records, args, default_sort='number', default_direction='desc')


@route('/orders/<id>/history')
@reading
def get_orders_by_id_history(db, id):
    args = arguments()
    found = order_row(db, id)
    records = [record(r['id'], str(r['id']).zfill(12), _body=r) for r in history_bodies(db, found['id'])]
    return page(records, args, default_sort='number', default_direction='desc')


@route('/orders/<id>/short.xml')
@reading
def get_orders_by_id_short_xml(db, id):
    arguments()
    found = order_row(db, id)
    result = orders.short_export(db, found['id'])
    return Response(result['xml'], mimetype='application/xml', headers={'X-Skipped-Lines': str(len(result['skipped']))})


@route('/orders/export.csv')
@reading
def get_orders_export_csv(db):
    args = arguments()
    kind = args.get('kind', 'lines')
    try:
        data = order_exports.rows(db, kind, args.get('from') or None, args.get('to') or None, args.get('store') or None)
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None
    return Response(order_exports.to_csv(kind, data), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=brickwork-orders-{kind}.csv'})


# ---------- writes ----------

def order_line(db, order_id, line_id):
    row = db.execute('SELECT id FROM main.order_line WHERE id=? AND order_id=?', (integer_id(line_id, 'line'), order_id)).fetchone()
    if row is None:
        raise errors.NotFound('No such line in this order')
    return row['id']


def order_document(db, order_id, document_id):
    row = db.execute('SELECT id FROM main.order_document WHERE id=? AND order_id=?', (integer_id(document_id, 'document'), order_id)).fetchone()
    if row is None:
        raise errors.NotFound('No such document in this order')
    return row['id']


@route('/orders/documents', 'POST')
@write(detached=True)
def post_orders_documents(db, body):
    """Import a document as a draft. By BrickLink order number the order is fetched first, outside any transaction; the import itself runs in
    the transaction that stores the answer, so it is whole or not at all. The same document again answers `duplicate`, writes nothing."""
    text = body.get('text', '')
    if len(text.encode()) > 1024 * 1024:
        raise errors.PayloadTooLarge()
    prepared = orders.api_data(db, body.get('number')) if body['source'] == 'api' and re.fullmatch('[0-9]{1,12}', str(body.get('number') or '')) else None

    def run():
        result = orders.import_document(db, body['source'], text, choice=body.get('choice', 'new'), number=body.get('number'), label=body.get('label'), prepared=prepared)
        return Done({k: result[k] for k in ('order_id', 'document_id', 'duplicate', 'placed', 'unplaced')} | {'event_id': result['event_id']}, result['event_id'])
    return run


@route('/orders/<id>/lines/<line_id>', 'PATCH')
@write
def patch_orders_by_id_lines_by_line_id(db, body, id, line_id):
    found = order_row(db, id)
    line = order_line(db, found['id'], line_id)
    item = item_of(db, body['item'])
    event = orders.match(db, found['id'], line, item_id=item, color_id=color_of(db, body['item'], body.get('color')))
    return Done(receipt(event, 'Saved'), event)


@route('/orders/<id>/lines/<line_id>/hold', 'PUT')
@write
def put_orders_by_id_lines_by_line_id_hold(db, body, id, line_id):
    found = order_row(db, id)
    event = orders.hold(db, found['id'], order_line(db, found['id'], line_id), body['held'])
    return Done(receipt(event, 'Saved'), event)


@route('/orders/<id>/documents/<doc_id>/phase', 'POST')
@write
def post_orders_by_id_documents_by_doc_id_phase(db, body, id, doc_id):
    found = order_row(db, id)
    event = orders.phase(db, found['id'], order_document(db, found['id'], doc_id), body['action'], body.get('pairs'))
    return Done(receipt(event, 'Saved'), event)


@route('/orders/<id>/received', 'POST')
@write
def post_orders_by_id_received(db, body, id):
    found = order_row(db, id)
    event = orders.received(db, found['id'], body['counts'])
    return Done(receipt(event, 'Saved'), event)


@route('/orders/<id>/allocate', 'POST')
@write
def post_orders_by_id_allocate(db, body, id):
    found = order_row(db, id)
    event = orders.allocate(db, found['id'], body['chosen'])
    return Done(receipt(event, 'Saved'), event)


@route('/orders/<id>/allocations/retry', 'POST')
@write
def post_orders_by_id_allocations_retry(db, body, id):
    found = order_row(db, id)
    event = orders.retry_allocations(db, found['id'], body['chosen'])
    return Done(receipt(event, 'Saved'), event)


@route('/orders/<id>/reconcile', 'POST')
@write
def post_orders_by_id_reconcile(db, body, id):
    found = order_row(db, id)
    event = orders.reconcile(db, found['id'])
    return Done(receipt(event, 'Saved'), event)
