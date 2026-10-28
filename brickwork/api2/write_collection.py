"""Writes on what is owned and wanted (M.11c, issue #113): copies, loose stock, wishes, wishlists, the Workbench's Take, Give and Found, and the
marks of a copy's lines.

Every function is a call of the core writer that owns the change; this module reads the request (items by number or id, colours in the
provider's space), checks that the row can take it (`404`, the ETag, `409 archived`) and builds the contract's body from the row afterwards.
Creating goes through the Add flow (`core/add.py`: resolve, validate, confirm), so an API copy is the copy the web makes: its part list is the
design's preselection, its import is queued, one receipt undoes it."""
import uuid

from ..core import add, checker, collection, errors, planning, wishlists, workbench
from ..core.media import media_root
from . import route
from .copies import FIGURES, LINES, check_state, completeness_body, copy_row, figure_body, part_body
from .items import for_write
from .read import bodies, integer_id
from .shapes import copy_bodies, stock_bodies, wish_bodies, wish_rows
from .writes import Done, identified, item_of, live_row, match, one_of, write


# ---------- guards and bodies ----------

def guard(db, table, entity, identifier, what):
    """The row a PATCH, DELETE or similar names: `404`, then the request's If-Match (`412`), then `409 archived`."""
    row = db.execute(f'SELECT * FROM main.{table} WHERE id=?', (str(identifier),)).fetchone() if len(str(identifier)) <= 64 else None
    if row is None:
        raise errors.NotFound(f'No such {what}')
    match(db, entity, str(identifier))
    if row['archived_at']:
        raise errors.Archived(f'This {what} is archived')
    return row


def archived_row(db, table, identifier, what):
    """The archived row a restore names: `404` if there is none, `409` if it is not archived."""
    row = db.execute(f'SELECT * FROM main.{table} WHERE id=?', (str(identifier),)).fetchone() if len(str(identifier)) <= 64 else None
    if row is None:
        raise errors.NotFound(f'No such {what}')
    if not row['archived_at']:
        raise errors.Conflict(f'This {what} is not archived')
    return row


def copy_response(db, identifier):
    return copy_bodies(db, [collection.instance(db, 'copy', identifier)], single=True)[0]


def stock_response(db, identifier, merged=()):
    body = stock_bodies(db, [collection.instance(db, 'stock', identifier)])[0]
    body['merged_ids'] = list(merged)
    return body


def wish_response(db, identifier):
    return wish_bodies(db, wish_rows(db, 'WHERE w.id=?', (identifier,)))[0]


def receipt(event, message=None):
    """`Receipt`: the event that did it and a word for it."""
    return {'event_id': event, **({'message': message} if message else {})}


def column_edits(body, renames=None):
    """The columns a PATCH body sets: its members, a few under the stored column's name (`purchase_location_id` is `place_id`)."""
    renames = renames or {'purchase_location_id': 'place_id'}
    return {renames.get(k, k): v for k, v in body.items()}


# ---------- adding ----------

def add_rows(db, item_id, color_id, where, *, quantity=1, condition=None, note=None, list_id=None, max_price=None, completeness=None, decision=None,
             storage_id=None, lot_id=None):
    """Add one reviewed row through the Add flow and return its receipt. `decision` is the API's: `skip` on something already owned or wished is
    `409` (nothing is written), `another` adds anyway; none adds only what is new. The failures of the review are `422`, a duplicate `409`."""
    row = {'item_id': item_id, 'color_id': color_id, 'quantity': quantity, 'condition': condition or ('any' if where == 'wishlist' else 'used'),
           'note': note, 'max_price': max_price}
    proposal = add.resolve(db, [row], where, list_id=list_id or 'default')
    if proposal['unresolved']:
        raise errors.ValidationFailed(proposal['unresolved'][0]['reason'])
    shown = proposal['items'][0]
    if decision == 'skip':
        if shown['owned'] or shown['wished']:
            raise errors.Conflict('Already owned or wished · skipped, nothing was added')
        decision = 'another'
    edit = {k: v for k, v in {'quantity': quantity, 'completeness': completeness, 'decision': decision or '', 'storage_id': storage_id, 'lot_id': lot_id,
                              'note': note, 'list_id': list_id}.items() if v is not None}
    try:
        rows = add.validate_edits(db, proposal['items'], [edit])
    except errors.BrickWorkError:
        raise
    except ValueError as error:
        if str(error).startswith(('Already owned', 'Already on')):
            raise errors.Conflict(str(error)) from None
        raise
    made = add.confirm(db, rows, batch=uuid.uuid4().hex)
    if not made:
        raise errors.ValidationFailed('Nothing was added')
    return made[0]


def created(ids):
    return Done({'ids': ids}, status=201)


@route('/copies', 'POST')
@write
def post_copies(db, body):
    item_id = item_of(db, body['item'])
    if (add.lookup(db, item_id) or {}).get('kind') != 'set':
        raise errors.ValidationFailed('A copy is a copy of a set · other items are loose stock')
    made = add_rows(db, item_id, None, 'owned', quantity=body.get('quantity', 1), condition=body.get('condition'), completeness=body.get('completeness'),
                    decision=body.get('decision'))
    ids = made['copies']
    edits = column_edits({k: v for k, v in body.items() if k in ('storage_id', 'purchase_location_id', 'purchase_date', 'purchase_price', 'purchase_currency')})
    if edits:
        collection.save(db, 'copy', ids, edits)
    return created(ids)


@route('/stock', 'POST')
@write
def post_stock(db, body):
    item_id, color_id = identified(db, body['item'], body.get('color'))
    if (add.lookup(db, item_id) or {}).get('kind') == 'set':
        raise errors.ValidationFailed('A set is owned as a copy · add it with POST /copies')
    made = add_rows(db, item_id, color_id, 'loose', quantity=body['quantity'], condition=body.get('condition'), note=body.get('note'),
                    storage_id=body.get('storage_id'), lot_id=body.get('lot_id'), decision='another')
    return created([made['stock']['id']])


@route('/wishes', 'POST')
@write
def post_wishes(db, body):
    item_id, color_id = identified(db, body['item'], body.get('color'))
    made = add_rows(db, item_id, color_id, 'wishlist', quantity=body.get('quantity', 1), condition=body.get('condition'), note=body.get('note'),
                    list_id=body.get('list_id'), max_price=body.get('max_price'), decision=body.get('decision'))
    wish_id = made['wish']['id']
    if body.get('max_price_currency') is not None:
        collection.save(db, 'wish', [wish_id], {'max_price_currency': body['max_price_currency']})            # a currency without a price is the core's refusal
    return created([wish_id])


# ---------- copies ----------

@route('/copies/<id>', 'PATCH')
@write
def patch_copies_by_id(db, body, id):
    guard(db, 'copy', 'copy', id, 'copy')
    collection.save(db, 'copy', [id], column_edits(body))
    return Done(copy_response(db, id))


@route('/copies/<id>', 'DELETE')
@write
def delete_copies_by_id(db, body, id):
    guard(db, 'copy', 'copy', id, 'copy')
    collection.save(db, 'copy', [id], {}, archive=True)
    return Done(copy_response(db, id))


@route('/copies/<id>/restore', 'POST')
@write
def post_copies_by_id_restore(db, body, id):
    archived_row(db, 'copy', id, 'copy')
    collection.restore(db, 'copy', id)
    return Done(copy_response(db, id))


@route('/copies/<id>/flags', 'PUT')
@write
def put_copies_by_id_flags(db, body, id):
    live_row(db, 'copy', id, 'copy')
    collection.save(db, 'copy', [id], {'flags': body['flags']})
    return Done(copy_response(db, id))


@route('/copies/<id>/pin', 'PUT')
@write
def put_copies_by_id_pin(db, body, id):
    live_row(db, 'copy', id, 'copy')
    event = planning.save(db, 'pin', {'id': id, 'pinned': body['pinned']})
    return Done(copy_response(db, id), event)


@route('/copies/<id>/checked', 'PUT')
@write
def put_copies_by_id_checked(db, body, id):
    live_row(db, 'copy', id, 'copy')
    event = checker.set_checked(db, id, body['checked'])
    return Done(completeness_body(db, copy_row(db, id)), event)


@route('/copies/<id>/check', 'POST')
@write
def post_copies_by_id_check(db, body, id):
    from flask import request
    live_row(db, 'copy', id, 'copy')
    operation = request.headers.get('Idempotency-Key') or uuid.uuid4().hex
    checker.write(db, id, dict(body, operation=operation))
    # The checker answers a repeated operation from its own receipt and writes nothing then: the event is that receipt.
    found = db.execute("SELECT id FROM main.event WHERE entity_kind='part_check' AND entity_id=? AND field IN ('save','undo') "
                       "AND json_extract(new_value,'$.operation')=? ORDER BY id LIMIT 1", (id, operation)).fetchone()
    return Done(check_state(db, id), found['id'] if found else None)


@route('/copies/<id>/take', 'POST')
@write
def post_copies_by_id_take(db, body, id):
    live_row(db, 'copy', id, 'copy')
    item_id, color_id = identified(db, body['item'], body.get('color'))
    if color_id is not None and (add.lookup(db, item_id) or {}).get('kind') == 'minifigure':
        raise errors.ValidationFailed('A minifigure has no colour · leave color out')
    event = workbench.take_for_gap(db, id, item_id, color_id, body['quantity'])
    return Done(receipt(event, f'Took {body["quantity"]}'), event)


# ---------- the lines of a copy ----------

def line_of(db, copy_id, part_id):
    row = db.execute(LINES + ' AND p.id=?', (copy_id, integer_id(part_id, 'part'))).fetchone()
    if row is None:
        raise errors.NotFound('No such line in this copy')
    return row


@route('/copies/<id>/parts/<part_id>', 'PATCH')
@write
def patch_copies_by_id_parts_by_part_id(db, body, id, part_id):
    live_row(db, 'copy', id, 'copy')
    line = line_of(db, id, part_id)
    event = checker.mark(db, id, [(f'p:{line["id"]}', body)])
    row = db.execute(LINES + ' AND p.id=?', (id, line['id'])).fetchone()
    book = bodies(db, items=[row['item_id'], row['figure_item']], colors=[row['color_id']])
    return Done(part_body(book, id, row), event)


@route('/copies/<id>/parts/bulk', 'POST')
@write
def post_copies_by_id_parts_bulk(db, body, id):
    live_row(db, 'copy', id, 'copy')
    mode = body.get('mode', 'set')
    edits, skipped, seen = [], [], set()
    for n, entry in enumerate(body['items']):
        field = f'items[{n}]'
        try:
            item_id, color_id = identified(db, entry['item'], entry['color'])
        except (errors.Unidentified, errors.Ambiguous) as error:
            skipped.append({'field': field, 'code': error.code, 'message': str(error)})
            continue
        line = db.execute('SELECT id, missing FROM main.copy_part WHERE copy_id=? AND item_id=? AND color_id=? AND copy_figure_id IS NULL AND is_spare=0 '
                          'AND retired_at IS NULL', (id, item_id, color_id)).fetchone()
        if line is None:
            skipped.append({'field': field, 'code': 'not_found', 'message': 'The copy has no such part line'})
            continue
        if line['id'] in seen:
            raise errors.ValidationFailed(f'{field}: this line is named twice')
        seen.add(line['id'])
        edits.append((f'p:{line["id"]}', {'missing': entry['missing'] + (line['missing'] if mode == 'add' else 0)}))
    preview = body.get('dry_run') is True
    event = checker.mark(db, id, edits) if edits else None
    return Done({'applied': len(edits), 'skipped': skipped, 'dry_run': preview, 'event_id': None if preview else event}, event)


@route('/copies/<id>/figures/<item_id>', 'PATCH')
@write
def patch_copies_by_id_figures_by_item_id(db, body, id, item_id):
    live_row(db, 'copy', id, 'copy')
    item = for_write(db, item_id)
    line = db.execute('SELECT id FROM main.copy_figure WHERE copy_id=? AND item_id=? AND retired_at IS NULL', (id, item)).fetchone()
    if line is None:
        raise errors.NotFound('The copy has no such figure')
    event = checker.mark(db, id, [(f'f:{line["id"]}', body)])
    row = db.execute(FIGURES + ' AND f.id=?', (id, id, line['id'])).fetchone()
    return Done(figure_body(bodies(db, items=[item]).item(item), row), event)


# ---------- photos ----------

@route('/copies/<id>/photos', 'POST')
@write
def post_copies_by_id_photos(db, body, id, content):
    live_row(db, 'copy', id, 'copy')
    event = collection.photo(db, media_root(db), 'copy', id, content, body.get('caption', ''))
    return Done(copy_response(db, id), event)


@route('/stock/<id>/photos', 'POST')
@write
def post_stock_by_id_photos(db, body, id, content):
    live_row(db, 'stock', id, 'stock line')
    event = collection.photo(db, media_root(db), 'stock', id, content, body.get('caption', ''))
    return Done(stock_response(db, id), event)


# ---------- loose stock ----------

@route('/stock/<id>', 'PATCH')
@write
def patch_stock_by_id(db, body, id):
    guard(db, 'stock', 'stock', id, 'stock line')
    event = collection.save(db, 'stock', [id], column_edits(body))
    return Done(stock_response(db, id, [r['id'] for r in collection.merge_result(db, event)]), event)


@route('/stock/<id>', 'DELETE')
@write
def delete_stock_by_id(db, body, id):
    guard(db, 'stock', 'stock', id, 'stock line')
    collection.save(db, 'stock', [id], {}, archive=True)
    return Done(stock_response(db, id))


@route('/stock/<id>/restore', 'POST')
@write
def post_stock_by_id_restore(db, body, id):
    archived_row(db, 'stock', id, 'stock line')
    collection.restore(db, 'stock', id)
    return Done(stock_response(db, id))


@route('/stock/<id>/flags', 'PUT')
@write
def put_stock_by_id_flags(db, body, id):
    live_row(db, 'stock', id, 'stock line')
    collection.save(db, 'stock', [id], {'flags': body['flags']})
    return Done(stock_response(db, id))


@route('/stock/<id>/parts', 'PATCH')
@write
def patch_stock_by_id_parts(db, body, id):
    live_row(db, 'stock', id, 'stock line')
    edits = []
    for n, entry in enumerate(body['parts']):
        item_id, color_id = identified(db, entry['item'], entry['color'])
        fields = {k: entry[k] for k in ('missing', 'damaged', 'checked') if k in entry}
        if not fields:
            raise errors.ValidationFailed(f'parts[{n}]: choose a count to change')
        edits.append((item_id, color_id, entry['spare'] or 0, fields))
    event = checker.mark_stock_parts(db, id, edits)
    rows = db.execute('SELECT * FROM main.stock_part WHERE stock_id=? AND retired_at IS NULL ORDER BY id', (id,)).fetchall()
    book = bodies(db, items=[r['item_id'] for r in rows], colors=[r['color_id'] for r in rows])
    return Done({'parts': [{'stock_id': id, 'item': book.item(r['item_id']), 'color': book.color(r['color_id']), 'spare': r['is_spare'], 'quantity': r['quantity'],
                            'missing': r['missing'], 'damaged': r['damaged'], 'checked': bool(r['checked'])} for r in rows]}, event)


@route('/stock/<id>/give', 'POST')
@write
def post_stock_by_id_give(db, body, id):
    live_row(db, 'stock', id, 'stock line')
    event = workbench.transfer(db, id, body['copy_id'], body['target'], body['target_id'], body['quantity'])
    return Done(receipt(event, 'Saved'), event)


@route('/stock/booklets', 'POST')
@write
def post_stock_booklets(db, body):
    event = workbench.booklets(db, body['text'], body.get('quantity', 1))
    return Done(receipt(event, 'Saved'), event)


@route('/found', 'POST')
@write
def post_found(db, body):
    item_id, color_id = identified(db, body['item'], body['color'])
    event = workbench.found(db, item_id, color_id, body['destination'], body.get('assignments') or {}, body['quantity'])
    return Done(receipt(event, 'Saved'), event)


# ---------- wishes ----------

@route('/wishes/<id>', 'PATCH')
@write
def patch_wishes_by_id(db, body, id):
    guard(db, 'wish', 'wish', id, 'wish')
    edits = column_edits(body, {'list_id': 'wishlist_id', 'color': 'color_id'})
    collection.save(db, 'wish', [id], edits)
    return Done(wish_response(db, id))


@route('/wishes/<id>', 'DELETE')
@write
def delete_wishes_by_id(db, body, id):
    guard(db, 'wish', 'wish', id, 'wish')
    collection.save(db, 'wish', [id], {}, archive=True)
    return Done(wish_response(db, id))


@route('/wishes/<id>/restore', 'POST')
@write
def post_wishes_by_id_restore(db, body, id):
    archived_row(db, 'wish', id, 'wish')
    collection.restore(db, 'wish', id)
    return Done(wish_response(db, id))


@route('/wishes/<id>/flags', 'PUT')
@write
def put_wishes_by_id_flags(db, body, id):
    live_row(db, 'wish', id, 'wish')
    collection.save(db, 'wish', [id], {'flags': body['flags']})
    return Done(wish_response(db, id))


@route('/wishes/<id>/to-owned', 'POST')
@write
def post_wishes_by_id_to_owned(db, body, id):
    wish = live_row(db, 'wish', id, 'wish')
    quantity = body.get('quantity', wish['quantity'])
    if quantity > wish['quantity']:
        raise errors.Conflict('Wished quantity changed')
    kind = db.execute('SELECT kind FROM main.item WHERE id=?', (wish['item_id'],)).fetchone()['kind']
    condition = body.get('condition') or (wish['condition'] if wish['condition'] in ('new', 'used') else 'used')
    made = add_rows(db, wish['item_id'], wish['color_id'], 'owned' if kind == 'set' else 'loose', quantity=quantity, condition=condition,
                    completeness=body.get('completeness'), decision='another')
    ids = made['copies'] if kind == 'set' else [made['stock']['id']]
    if quantity == wish['quantity']:
        collection.save(db, 'wish', [id], {}, archive=True)
    else:
        collection.save(db, 'wish', [id], {'quantity': wish['quantity'] - quantity})
    return Done({'ids': ids})


# ---------- wishlists ----------

def wishlist_body(db, identifier):
    r = db.execute('''SELECT l.*, count(w.id) AS count FROM main.wishlist l LEFT JOIN main.wish w ON w.wishlist_id=l.id AND w.archived_at IS NULL
                      WHERE l.id=? GROUP BY l.id''', (identifier,)).fetchone()
    return {'id': r['id'], 'name': r['name'], 'note': r['note'], 'sort': r['sort'], 'archived_at': r['archived_at'], 'created_at': r['created_at'],
            'bricklink_id': r['bricklink_id'], 'count': r['count']}


@route('/wishlists', 'POST')
@write
def post_wishlists(db, body):
    identifier, event = wishlists.save(db, None, body)
    return Done(wishlist_body(db, identifier), event, status=201)


@route('/wishlists/<id>', 'PATCH')
@write
def patch_wishlists_by_id(db, body, id):
    live_row(db, 'wishlist', id, 'wishlist')
    _, event = wishlists.save(db, id, body)
    return Done(wishlist_body(db, id), event)


@route('/wishlists/<id>', 'DELETE')
@write
def delete_wishlists_by_id(db, body, id):
    live_row(db, 'wishlist', id, 'wishlist')
    _, event = wishlists.save(db, id, {}, action='archive')
    return Done(wishlist_body(db, id), event)


@route('/wishlists/<id>/restore', 'POST')
@write
def post_wishlists_by_id_restore(db, body, id):
    archived_row(db, 'wishlist', id, 'wishlist')
    _, event = wishlists.save(db, id, {}, action='restore')
    return Done(wishlist_body(db, id), event)


@route('/wishlists/<id>/transfer', 'POST')
@write
def post_wishlists_by_id_transfer(db, body, id):
    live_row(db, 'wishlist', id, 'wishlist')
    event = wishlists.transfer(db, body['ids'], id, copy=body.get('copy', False))
    return Done(receipt(event, 'Copied' if body.get('copy') else 'Moved'), event)
