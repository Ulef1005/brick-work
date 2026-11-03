"""Writes on identity and history (M.11c, issue #113): an item's BrickLink links, merge and unmerge, the switch of a copy's part list, and Undo.

Links and merges are `core/identity_admin.py`'s (one logged change each, Undo puts every row back); the part list of a copy is
`store4/copies.py`'s switch and `store4/pending.py`'s request for BrickLink's list (a copy waits on the fetch job and keeps its list
meanwhile, so that answer is `202`). Undo is `core/undo.py`'s dispatcher over the event a write named, applied to the whole write
(`writes.undo_operation`)."""
from flask import g

from ..core import admin, errors, identity_admin, items
from ..store4 import copies as copies_store, jobs, pending
from . import route
from .item_views import link_bodies
from .items import for_write, item_id as canonical_id
from .read import bodies, integer_id
from .write_collection import copy_response, guard
from .writes import Done, color_of, item_of, undo_operation, write


# ---------- links ----------

def link_row(db, item_id, number, kind, scope):
    return db.execute("SELECT * FROM main.item_link WHERE item_id=? AND provider='bricklink' AND provider_kind=? AND provider_key=? AND coalesce(color_id,0)=?",
                      (item_id, kind, number, scope or 0)).fetchone()


@route('/items/<id>/links', 'PUT')
@write
def put_items_by_id_links(db, body, id):
    """Make sure the item has this BrickLink link as a `manual` one (a link to check is confirmed), and when asked make it the preferred one of
    its colour scope. Nothing changes, and no event is written, when it is all there already."""
    item_id = for_write(db, id)
    items.ensure(db, item_id)
    kind = db.execute('SELECT kind FROM main.item WHERE id=?', (item_id,)).fetchone()['kind']
    if items.type_of_kind(kind) != body['type']:
        raise errors.ValidationFailed(f'A {kind} has the BrickLink type {items.type_of_kind(kind)}, not {body["type"]}')
    scope = color_of(db, {}, body.get('color_id'))
    row = link_row(db, item_id, body['no'], body['type'], scope)
    if row is None:
        identity_admin.add_link(db, item_id, body['no'], scope)
    elif row['status'] == 'to_check':
        identity_admin.confirm_link(db, row['id'])
    row = link_row(db, item_id, body['no'], body['type'], scope)
    if body.get('preferred') and not row['preferred']:
        identity_admin.set_preferred(db, row['id'], scope, item_id)
        row = link_row(db, item_id, body['no'], body['type'], scope)
    return Done(link_bodies(db, [row])[0])


# ---------- merge and unmerge ----------

def merge_body(db, merge_id, survivor, merged, receipt):
    book = bodies(db, items=[survivor, merged])
    return {'merge_id': merge_id, 'survivor': book.item(survivor), 'merged': book.item(merged), 'receipt': receipt}


@route('/items/<id>/merge', 'POST')
@write
def post_items_by_id_merge(db, body, id):
    loser = for_write(db, id)
    survivor = item_of(db, body['survivor'], what='survivor')
    done = identity_admin.merge_item(db, loser, survivor)
    return Done(merge_body(db, done['merge_id'], survivor, loser, {'event_id': done['event_id'], 'counts': done['counts']}), done['event_id'])


@route('/items/<id>/unmerge', 'POST')
@write
def post_items_by_id_unmerge(db, body, id):
    merged = canonical_id(id)
    if db.execute('SELECT 1 FROM main.item WHERE id=?', (merged,)).fetchone() is None:
        raise errors.NotFound('No such item')
    found = db.execute('SELECT * FROM main.item_merge WHERE merged_id=? AND undone_at IS NULL ORDER BY id DESC', (merged,)).fetchall()
    if 'merge_id' in body:
        found = [r for r in found if r['id'] == body['merge_id']]
    if not found:
        raise errors.Conflict('This item is not merged into another' if 'merge_id' not in body else 'That merge does not hold for this item')
    merge = found[0]
    done = identity_admin.unmerge_item(db, merge['id'])
    return Done(merge_body(db, merge['id'], merge['survivor_id'], merged, {'event_id': done['event_id']}), done['event_id'])


# ---------- the part list of a copy ----------

@route('/copies/<id>/inventory', 'POST')
@write
def post_copies_by_id_inventory(db, body, id):
    copy = guard(db, 'copy', 'copy', id, 'copy')
    via, actor = admin.origin()
    remember = body.get('remember', False)
    if body['source'] == 'rebrickable':
        receipt = copies_store.switch_part_list_in(db, id, {'source': 'rebrickable', 'version': body.get('version')}, via=via, actor=actor, remember=remember)
        return Done(copy_response(db, id), receipt['event_id'])
    if 'version' in body:
        raise errors.ValidationFailed("version is for Rebrickable's lists")
    if not jobs._configured('bricklink'):
        raise errors.SourceNotConfigured("BrickLink's list is not offered without a BrickLink key")
    if copy['inventory_pending'] is not None:
        raise errors.Conflict('This copy is already waiting for BrickLink\'s list')
    done = pending.request_bricklink_in(db, id, via=via, actor=actor, remember=remember)
    if done['switched']:
        return Done(copy_response(db, id), done['receipt']['event_id'])
    return Done(copy_response(db, id), status=202, headers={'Location': f"/api/v2/jobs/{done['pending']['job_id']}"})


@route('/copies/<id>/inventory/pending', 'DELETE')
@write
def delete_copies_by_id_inventory_pending(db, body, id):
    guard(db, 'copy', 'copy', id, 'copy')
    via, actor = admin.origin()
    pending.cancel_pending_in(db, id, via=via, actor=actor)
    return Done(copy_response(db, id))


# ---------- Undo ----------

@route('/events/<id>/undo', 'POST')
@write
def post_events_by_id_undo(db, body, id):
    via, actor = admin.origin()
    undone, last, already = undo_operation(db, integer_id(id, 'event'), via=via, actor=actor, identity=g.api_identity)
    return Done({'undone_event_id': undone, 'event_id': last, 'already_undone': already}, last)
