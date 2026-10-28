"""Where things are and where they came from (M.11b, issue #113): storages, lots, purchase places and flags.

Storages are the ledger's (`core/ledger.py`, with the virtual "Not stored"), a lot groups loose stock bought together, a place is where
something was bought, a flag is an owner, status or tag a copy, stock line or wish carries. Archived rows are hidden from the lists unless
the list takes `archived`."""
from decimal import Decimal

from ..core import collection, errors, ledger
from . import route
from .read import arguments, bodies, page, reading, record, respond
from .shapes import stock_bodies

UNSTORED = 'unstored'                                   # the id of the virtual location "Not stored" (v1's); `null` is only the filter spelling


def storage_body(r):
    return {'id': UNSTORED if r['id'] is None else r['id'], 'name': r['name'], 'copies': r['copies'], 'entries': r['entries'], 'pieces': r['pieces'],
            'lots': r['lots'], 'figures': r['figures'], 'part_lots': r['part_lots'], 'type': r['type'], 'parent_id': r['parent_id'],
            'parent_name': r['parent_name'], 'note': r['note'], 'archived_at': r.get('archived_at')}


def storage_response(db, key):
    """`Storage` of a live storage or an archived one (an archived storage holds nothing: its counts are zero), else `404`."""
    live = next((r for r in ledger.storages(db) if r['id'] == key), None)
    if live is not None:
        return storage_body(live)
    archived = db.execute('SELECT * FROM main.storage WHERE id=? AND archived_at IS NOT NULL', (key,)).fetchone() if key else None
    if archived is None:
        raise errors.NotFound('No such storage')
    parent = db.execute('SELECT name FROM main.storage WHERE id=?', (archived['parent_id'],)).fetchone() if archived['parent_id'] else None
    return storage_body(dict(archived, copies=0, entries=0, pieces=0, lots=0, figures=0, part_lots=0, parent_name=parent[0] if parent else None))


@route('/storages')
@reading
def get_storages(db):
    args = arguments()
    records = [record(UNSTORED if r['id'] is None else r['id'], r['name'] if r['id'] is not None else '￿', name=r['name'], _body=storage_body(r))
               for r in ledger.storages(db)]
    return page(records, args)


@route('/storages/<id>')
@reading
def get_storages_by_id(db, id):
    arguments()
    key = None if id == UNSTORED else id
    if key is not None and len(key) > 64:
        raise errors.NotFound('No such storage')
    live = next((r for r in ledger.storages(db) if r['id'] == key), None)
    if live is not None:
        found = ledger.storage_detail(db, key, [live])
        location, rows = storage_body(found['location']), found['rows']
    else:
        location = storage_response(db, key)
        rows = collection.decorate(db, [dict(r, entity=t, kind=t) for t, r in ledger.storage_contents(db, key)])
    book = bodies(db, items=[r['item_id'] for r in rows], colors=[r['color_id'] for r in rows])
    return respond({'location': location,
                    'rows': [{'entity': r['entity'], 'id': r['id'], 'item': book.item(r['item_id']), 'name': r['name'], 'color': book.color(r['color_id']),
                              'kind': r['kind'], 'quantity': r['quantity'], 'condition': r['condition'], 'completeness': r.get('completeness'),
                              'lot_id': r.get('lot')} for r in rows if r.get('item_id') is not None]})


# ---------- lots ----------

def lot_body(r):
    return {'id': r['id'], 'name': r['name'], 'note': r['note'], 'created_at': r['created_at'], 'storage_id': r['storage_id'],
            'purchase_location_id': r['place_id'], 'purchase_date': r['purchase_date'], 'purchase_price': r['purchase_price'],
            'purchase_currency': r['purchase_currency'], 'archived_at': r['archived_at'], 'entries': r['entries'], 'quantity': r['quantity']}


LOTS = '''SELECT l.*, coalesce(s.entries, 0) AS entries, coalesce(s.quantity, 0) AS quantity FROM main.lot l
    LEFT JOIN (SELECT lot_id, count(*) AS entries, sum(quantity) AS quantity FROM main.stock WHERE archived_at IS NULL GROUP BY lot_id) s ON s.lot_id=l.id'''


@route('/lots')
@reading
def get_lots(db):
    args = arguments()
    records = [record(r['id'], r['name'], name=r['name'], storage=r['storage_id'] or 'null', archived_at=r['archived_at'], _body=lot_body(r))
               for r in db.execute(LOTS + ' ORDER BY l.name, l.id')]
    return page(records, args)


@route('/lots/<id>')
@reading
def get_lots_by_id(db, id):
    arguments()
    row = db.execute(LOTS + ' WHERE l.id=?', (id,)).fetchone() if len(id) <= 64 else None
    if row is None:
        raise errors.NotFound('No such lot')
    rows = [collection.instance(db, 'stock', r[0]) for r in db.execute(
        'SELECT id FROM main.stock WHERE lot_id=? AND archived_at IS NULL ORDER BY item_id, color_id, created_at, id', (id,))]
    return respond({'lot': lot_body(row), 'rows': stock_bodies(db, rows)})


# ---------- places and flags ----------

def total_text(totals):
    return {currency: format(amount, 'f') if isinstance(amount, Decimal) else str(amount) for currency, amount in totals.items()}


@route('/places')
@reading
def get_places(db):
    args = arguments()
    records = [record(r['id'], r['name'], name=r['name'], _body={'archived_at': r['archived_at'], 'id': r['id'], 'name': r['name'], 'kind': r['kind'],
                                                                  'count': r['count'], 'totals': total_text(r['totals']), 'orders': r['orders'],
                                                                  'last_used': r['last_used']}) for r in collection.purchase_places(db)]
    return page(records, args)


@route('/flags')
@reading
def get_flags(db):
    args = arguments()
    counts = {}
    for table, column in (('copy_flag', 'flag_id'), ('stock_flag', 'flag_id'), ('wish_flag', 'flag_id')):
        for flag_id, n in db.execute(f'SELECT {column}, count(*) FROM main.{table} GROUP BY {column}'):
            counts[flag_id] = counts.get(flag_id, 0) + n
    records = [record(r['id'], r['name'], name=r['name'], kind=r['kind'],
                      _body={'archived_at': r['archived_at'], 'id': r['id'], 'name': r['name'], 'kind': r['kind'], 'shown_on_grid': bool(r['shown_on_grid']),
                             'count': counts.get(r['id'], 0)})
               for r in db.execute('SELECT * FROM main.flag WHERE archived_at IS NULL ORDER BY kind, name COLLATE NOCASE, id')]
    return page(records, args)
