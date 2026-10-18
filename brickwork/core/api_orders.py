"""Order API adapter; all domain rules belong to orders and ledger."""
from . import api_reads as read, errors, orders, ledger


def mutate(db, identifier, action, data, values, *, prepared=None):
    if action == 'documents':
        text = data.get('text', '')
        if len(text.encode()) > 1024*1024:
            raise errors.PayloadTooLarge()
        result = orders.import_document(db, data['source'], text, choice=data.get('choice','new'),
            number=data.get('number'), label=data.get('label'), prepared=prepared)
        return result, 200
    read.one(db, 'SELECT id FROM orders WHERE id=?', (identifier,))
    if 'line_id' in values:
        read.one(db, 'SELECT id FROM order_lines WHERE id=? AND order_id=?', (values['line_id'],identifier))
    if 'doc_id' in values:
        read.one(db, 'SELECT id FROM order_documents WHERE id=? AND order_id=?', (values['doc_id'],identifier))
    if action in ('allocate','retry'):
        for choice in data['chosen']:
            if choice['target_type']=='copy' and not {'copy_id','target','target_id'} <= choice.keys():
                raise errors.ValidationFailed('Choose a copy gap')
    if action == '{line_id}':
        orders.match(db,identifier,values['line_id'],data['item_type'],data['item_no'],data.get('color_id'))
    elif action == 'hold': orders.hold(db,identifier,values['line_id'],data['held'])
    elif action == 'phase': orders.phase(db,identifier,values['doc_id'],data['action'],data.get('pairs'))
    elif action == 'received': orders.received(db,identifier,data['counts'])
    elif action == 'allocate': orders.allocate(db,identifier,data['chosen'])
    elif action == 'retry': orders.retry_allocations(db,identifier,data['chosen'])
    elif action == 'reconcile': orders.reconcile(db,identifier)
    else: raise errors.ValidationFailed('Unsupported order action')
    return dict(message='Saved'),200


def listing(db, identifier, resource):
    read.one(db, 'SELECT id FROM orders WHERE id=?', (identifier,))
    if resource == 'review': return orders.allocation_review(db, identifier)
    if resource == 'allocations': return orders.allocation_history(db, identifier)
    return ledger.history(db, order_id=identifier, limit=None)
