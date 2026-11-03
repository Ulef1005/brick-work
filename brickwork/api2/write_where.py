"""Writes on where things are and where they came from (M.11c, issue #113): storages, lots, purchase places, flags, and the PDFs of sets.

As the other write modules: each function is a call of the core writer that owns the change (`core/ledger.py`, `collection.new_lot`,
`admin.value_write`, `admin.attach_instruction`), the guards are the request's (`404`, `409 archived`), the body is read back from the row."""
import json

from ..core import admin, collection, errors, ledger
from ..core.media import media_root
from . import route
from .instructions import file_body, one as instruction_row
from .places import LOTS, lot_body, storage_response, total_text
from .read import bodies, integer_id
from .write_collection import archived_row, column_edits, receipt
from .writes import Done, flag_argument, item_of, live_row, write

FLAG_GROUPS = {'owner': 'owners', 'status': 'statuses', 'tag': 'tags'}


def created_id(db, event):
    """The id of the row a collection receipt created: the first row of the receipt's first table."""
    return json.loads(db.execute('SELECT new_value FROM main.event WHERE id=?', (event,)).fetchone()['new_value'])[0]['rows'][0]['id']


def deleted(identifier):
    return {'id': identifier, 'archived': True}


# ---------- storages ----------

def storage_fields(body):
    """The optional members of a storage write, under the keyword the ledger takes (a member left out stays as it is)."""
    return {k: body[k] for k in ('type', 'parent_id', 'note') if k in body}


@route('/storages', 'POST')
@write
def post_storages(db, body):
    identifier, event = ledger.storage_save(db, None, body['name'], **storage_fields(body))
    return Done(storage_response(db, identifier), event, status=201)


@route('/storages/<id>', 'PATCH')
@write
def patch_storages_by_id(db, body, id):
    live_row(db, 'storage', id, 'storage')
    identifier, event = ledger.storage_save(db, id, body['name'], **storage_fields(body))
    return Done(storage_response(db, identifier), event)


@route('/storages/<id>', 'DELETE')
@write
def delete_storages_by_id(db, body, id):
    live_row(db, 'storage', id, 'storage')
    move = flag_argument('move_to_unstored') or False
    if db.execute('SELECT 1 FROM main.storage WHERE parent_id=? AND archived_at IS NULL', (id,)).fetchone():
        raise errors.Conflict('Storages sit inside this one · move or archive them first')
    if ledger.storage_contents(db, id) and not move:
        raise errors.Conflict('The storage is not empty · move the items first, or archive it with move_to_unstored=true')
    event = ledger.storage_archive(db, id, move_to_unstored=move)
    return Done(storage_response(db, id), event)


@route('/storages/<id>/restore', 'POST')
@write
def post_storages_by_id_restore(db, body, id):
    archived_row(db, 'storage', id, 'storage')
    collection.restore(db, 'storage', id)
    return Done(storage_response(db, id))


@route('/storages/<id>/contents', 'POST')
@write
def post_storages_by_id_contents(db, body, id):
    if id != 'unstored':
        live_row(db, 'storage', id, 'storage')
    event = ledger.move(db, None if id == 'unstored' else id, body['selections'])
    return Done(receipt(event, 'Saved'), event)


# ---------- lots ----------

def lot_response(db, identifier):
    return lot_body(db.execute(LOTS + ' WHERE l.id=?', (identifier,)).fetchone())


@route('/lots', 'POST')
@write
def post_lots(db, body):
    event = collection.new_lot(db, body['stock_ids'], body)
    return Done(lot_response(db, created_id(db, event)), event, status=201)


@route('/lots/<id>', 'PATCH')
@write
def patch_lots_by_id(db, body, id):
    live_row(db, 'lot', id, 'lot')
    event = collection.save(db, 'lot', [id], column_edits(body))
    return Done(lot_response(db, id), event)


@route('/lots/<id>', 'DELETE')
@write
def delete_lots_by_id(db, body, id):
    live_row(db, 'lot', id, 'lot')
    event = collection.save(db, 'lot', [id], {}, archive=True)
    return Done(lot_response(db, id), event)


@route('/lots/<id>/restore', 'POST')
@write
def post_lots_by_id_restore(db, body, id):
    archived_row(db, 'lot', id, 'lot')
    collection.restore(db, 'lot', id)
    return Done(lot_response(db, id))


# ---------- purchase places ----------

def place_response(db, identifier):
    found = next((r for r in collection.purchase_places(db) if r['id'] == identifier), None)
    if found is None:                                                        # an archived place is in no list: it has no uses to count
        found = dict(db.execute('SELECT * FROM main.place WHERE id=?', (identifier,)).fetchone(), count=0, totals={}, orders=0, last_used=None)
    return {'archived_at': found['archived_at'], 'id': found['id'], 'name': found['name'], 'kind': found['kind'], 'count': found['count'],
            'totals': total_text(found['totals']), 'orders': found['orders'], 'last_used': found['last_used']}


@route('/places', 'POST')
@write
def post_places(db, body):
    event = admin.value_write(db, 'purchase-places', 'add', None, body['name'], confirmed=True)
    return Done(place_response(db, created_id(db, event)), event, status=201)


@route('/places/<id>', 'PATCH')
@write
def patch_places_by_id(db, body, id):
    live_row(db, 'place', id, 'purchase place')
    event = admin.value_write(db, 'purchase-places', 'rename', id, body['name'], confirmed=True)
    return Done(place_response(db, id), event)


@route('/places/<id>', 'DELETE')
@write
def delete_places_by_id(db, body, id):
    live_row(db, 'place', id, 'purchase place')
    event = admin.value_write(db, 'purchase-places', 'delete', id, confirmed=True)
    return Done(deleted(id), event)


@route('/places/<id>/restore', 'POST')
@write
def post_places_by_id_restore(db, body, id):
    archived_row(db, 'place', id, 'purchase place')
    collection.restore(db, 'place', id)
    return Done(place_response(db, id))


# ---------- flags ----------

def flag_response(db, identifier):
    row = db.execute('SELECT * FROM main.flag WHERE id=?', (identifier,)).fetchone()
    used = sum(db.execute(f'SELECT count(*) FROM main.{table} WHERE flag_id=?', (identifier,)).fetchone()[0] for table in ('copy_flag', 'stock_flag', 'wish_flag'))
    return {'archived_at': row['archived_at'], 'id': row['id'], 'name': row['name'], 'kind': row['kind'], 'shown_on_grid': bool(row['shown_on_grid']), 'count': used}


def own_flag(db, identifier):
    """A live flag a person may rename or archive (the system flags are the app's)."""
    row = live_row(db, 'flag', identifier, 'flag')
    if row['system']:
        raise errors.Conflict(admin.SYSTEM_VALUE)
    return row


@route('/flags', 'POST')
@write
def post_flags(db, body):
    event = admin.value_write(db, FLAG_GROUPS[body['kind']], 'add', None, body['name'], confirmed=True)
    return Done(flag_response(db, created_id(db, event)), event, status=201)


@route('/flags/<id>', 'PATCH')
@write
def patch_flags_by_id(db, body, id):
    row = own_flag(db, id)
    event = admin.value_write(db, FLAG_GROUPS[row['kind']], 'rename', id, body['name'], confirmed=True)
    return Done(flag_response(db, id), event)


@route('/flags/<id>', 'DELETE')
@write
def delete_flags_by_id(db, body, id):
    row = own_flag(db, id)
    event = admin.value_write(db, FLAG_GROUPS[row['kind']], 'delete', id, confirmed=True)
    return Done(deleted(id), event)


@route('/flags/<id>/restore', 'POST')
@write
def post_flags_by_id_restore(db, body, id):
    archived_row(db, 'flag', id, 'flag')
    collection.restore(db, 'flag', id)
    return Done(flag_response(db, id))


# ---------- the PDFs of sets ----------

def file_response(db, identifier):
    row = instruction_row(db, identifier)
    return file_body(bodies(db, items=[row['item_id']]), media_root(db), row)


def live_file(db, identifier):
    row = instruction_row(db, identifier)
    if row['archived_at']:
        raise errors.Archived('This instruction file is archived')
    return row


@route('/instruction-files', 'POST')
@write
def post_instruction_files(db, body, content):
    item_id = item_of(db, body['item'])
    target = admin.instruction_set_of(db, item_id)
    identifier = admin.attach_instruction(db, media_root(db), target, body['label'], content, undoable=True)
    return Done(file_response(db, identifier), status=201)


@route('/instruction-files/<id>', 'PATCH')
@write
def patch_instruction_files_by_id(db, body, id):
    live_file(db, id)
    event = admin.instruction_rename(db, integer_id(id, 'instruction file'), body['label'], undoable=True)
    return Done(file_response(db, id), event)


@route('/instruction-files/<id>', 'DELETE')
@write
def delete_instruction_files_by_id(db, body, id):
    live_file(db, id)
    event = admin.instruction_archive(db, integer_id(id, 'instruction file'))
    return Done(deleted(int(id)), event)


@route('/instruction-files/<id>/restore', 'POST')
@write
def post_instruction_files_by_id_restore(db, body, id):
    row = instruction_row(db, id)
    if not row['archived_at']:
        raise errors.Conflict('This instruction file is not archived')
    collection.restore(db, 'instruction_file', int(id))
    return Done(file_response(db, id))
