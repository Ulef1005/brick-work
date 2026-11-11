"""Change a variant: re-point what is owned from one catalogue item to another of the same kind (issue #151).

A figure (or part) can exist in the catalogue twice, as the old and the reissued variant, and a collection may own the wrong one. Unlike a
merge, neither item goes away: `change_variant_in(a, b)` moves the owned rows from `a` to `b` and makes BrickLink's number for the thing `b`'s,
in one transaction, under one `RowLog` receipt and one event (`item` / `change_variant`), which `undo_change_variant_in` puts back exactly.

What moves, keeping each row's id and history (the id of a copy, a stock row or a wish never changes):

- `stock` rows (loose figures and parts) with their own photos, `wish` rows, `copy_figure` lines (the line of a figure in a copy: its part lines hang on the line,
  not on the item, so a copy keeps its whole part list), and the `copy_part` and `stock_part` lines whose own item is `a` (when the kind is `part`).
- A line that was attached to a catalogue part list of `a` (`inventory_source='rebrickable'`) is attached to the same version of `b` when `b`'s
  catalogue has that version with the same digest, and else becomes `migrated`: the lines stay as they are and the page offers "choose a part
  list" (data model 8.6). It never names a list `b` does not have.
- What stays on `a`: its fetched part lists, prices, properties, pictures, set preference, order lines and allocations. A is left a plain
  catalogue item: never deleted, never merged.

The BrickLink number (`item_link`, provider `bricklink`). The number is the one `a` prefers for every colour; when `a` has none, the one
BrickLink link `b` holds to check; when neither, only the rows move. For each colour scope the number is held in (A's confirmed links of it and
B's links of it), `b` gets the link as `manual` (a `to_check` one is confirmed, a missing one is added, an `inferred` or `matched` one is upgraded) and
**preferred** (B's other preferred link of that scope loses the mark first, since there is one per item, provider and colour), and `a`'s link of the
same number and scope becomes `to_check` and not preferred. The schema's preferred model is per item, so it never collides between the two items;
what must not stay is a number that two items both confirm (the lookup would answer 409 ambiguous), and `to_check` is the state that does not
resolve, keeps the catalogue's seeded row in place (a reconcile does not insert it again) and shows `a` in Unresolved items for a person to decide
later. Nothing is deleted.

Refused (`MergeRefused`, as `merge_in`): an item that is not in the collection (a catalogue item is projected), the same item twice, a merged
item on either side, items of different kinds, a set (a copy's part list is the set's own: out of scope), a job in flight for either, a
copy, loose figure or part list holding a line for both items, a row that holds a fetched part list of `a`, a live stock row or wish that would meet a live one of `b` on its
key (`stock_merge_key`, `wish_live_key`; they are not summed), each naming the row."""
import json
import sqlite3
import uuid

from . import merge as moves
from .connect import now
from .errors import MergeRefused, NotInCatalogue
from .rowlog import RowLog

FIELD = 'change_variant'
LINES = ('copy_figure', 'copy_part', 'stock_part')               # the line tables of `_refuse_double_lines` this move touches


def _item(db, item_id):
    item = moves._item(db, item_id)
    if item is None:
        from . import identity
        try:
            identity.project(db, item_id)
        except NotInCatalogue:
            raise MergeRefused(f'item {item_id} is in neither the collection nor the catalogue') from None
        item = moves._item(db, item_id)
    return item


def _plan_stock(db, log, a, b):
    """The rows of `a` that move; refuses what would meet a live row of `b` on its key."""
    rows = log.select('stock', 'item_id=? ORDER BY created_at, id', (a,))
    for row in rows:
        if row['fetched_inventory_id'] is not None:
            raise MergeRefused(f'stock {row["id"]} holds a fetched part list of item {a} · switch its part list first, then change the variant')
        if row['archived_at'] is None and row['kind'] != 'minifigure':
            twin = db.execute('''SELECT id FROM main.stock WHERE item_id=? AND archived_at IS NULL AND kind!='minifigure' AND color_key=coalesce(?, 0)
                                 AND condition_key=coalesce(?, '') AND lot_key=coalesce(?, '') AND storage_key=coalesce(?, '')''',
                              (b, row['color_id'], row['condition'], row['lot_id'], row['storage_id'])).fetchone()
            if twin is not None:
                raise MergeRefused(f'stock {row["id"]} would meet stock {twin["id"]} of item {b} (same colour, condition, lot and storage) · '
                                   'the rows are not added up silently: change one of them first')
    return rows


def _plan_wishes(db, log, a, b):
    rows = log.select('wish', 'item_id=? ORDER BY added_at, id', (a,))
    for row in rows:
        if row['archived_at'] is None:
            twin = db.execute('SELECT id FROM main.wish WHERE item_id=? AND archived_at IS NULL AND wishlist_id=? AND color_key=coalesce(?, 0)',
                              (b, row['wishlist_id'], row['color_id'])).fetchone()
            if twin is not None:
                raise MergeRefused(f'wish {row["id"]} would meet wish {twin["id"]} of item {b} on the same wish list and colour · '
                                   'the rows are not added up silently: archive or change one of them first')
    return rows


def _attach(db, row, b):
    """The inventory columns of a moved line: attached to `b`'s own version of the catalogue list when it has the same one, else `migrated`."""
    if row['inventory_source'] != 'rebrickable':
        return {}
    same = db.execute('SELECT 1 FROM catalogue.inventory WHERE item_id=? AND version=? AND digest IS ?', (b, row['inventory_version'], row['inventory_digest'])).fetchone()
    return {} if same else dict(inventory_source='migrated', inventory_version=None)


def _move_rows(db, log, a, b):
    for row in _plan_stock(db, log, a, b):
        log.update('stock', row, item_id=b, **_attach(db, row, b))
        for photo in log.select('photo', 'stock_id=? AND item_id=?', (row['id'], a)):
            log.update('photo', photo, item_id=b)              # the detail page finds a stock row's photos by item and stock
    for row in _plan_wishes(db, log, a, b):
        log.update('wish', row, item_id=b)
    for row in log.select('copy_figure', 'item_id=?', (a,)):
        if row['fetched_inventory_id'] is not None:
            raise MergeRefused(f'copy {row["copy_id"]} holds a fetched part list of item {a} for its figure line · '
                               'switch its part list first, then change the variant')
        log.update('copy_figure', row, item_id=b, **_attach(db, row, b))
    for table in ('copy_part', 'stock_part'):
        for row in log.select(table, 'item_id=?', (a,)):
            log.update(table, row, item_id=b)


def _same_scope(row, scope):
    return (row['color_id'] or 0) == (scope or 0)


def _links(log, a, b):
    """BrickLink's number moves to `b`; returns the number or None (see the module doc)."""
    mine = log.select('item_link', "item_id=? AND provider='bricklink' ORDER BY id", (a,))
    theirs = log.select('item_link', "item_id=? AND provider='bricklink' ORDER BY id", (b,))
    number = next((r['provider_key'] for r in mine if r['preferred'] and r['color_id'] is None and r['status'] != 'to_check'), None)
    if number is None:
        waiting = {r['provider_key'] for r in theirs if r['status'] == 'to_check' and r['color_id'] is None}
        number = waiting.pop() if len(waiting) == 1 else None
    if number is None:
        return None
    held = [r for r in mine if r['provider_key'] == number and r['status'] != 'to_check']
    letter = next(r['provider_kind'] for r in held + [r for r in theirs if r['provider_key'] == number])
    scopes = list(dict.fromkeys([r['color_id'] for r in held] + [r['color_id'] for r in theirs if r['provider_key'] == number]))
    for scope in scopes:
        now_ = now()
        row = next((r for r in log.select('item_link', "item_id=? AND provider='bricklink' AND provider_key=?", (b, number)) if _same_scope(r, scope)), None)
        for other in log.select('item_link', "item_id=? AND provider='bricklink' AND preferred=1", (b,)):
            if _same_scope(other, scope) and (row is None or other['id'] != row['id']):
                log.update('item_link', other, preferred=0)
        if row is None:
            log.insert('item_link', item_id=b, color_id=scope, provider='bricklink', provider_kind=letter, provider_key=number, status='manual', method='user',
                       origin='user', preferred=1, evidence_digest=None, evidence_json=json.dumps({'changed_variant_from': a}), catalogue_build_id=None,
                       decided_at=now_, decided_by='user')
        else:
            sets = {} if row['status'] == 'manual' and row['origin'] == 'user' and row['preferred'] else dict(
                status='manual', method='user', origin='user', preferred=1, decided_at=now_, decided_by='user')
            if sets:
                log.update('item_link', row, **sets)
        for old in log.select('item_link', "item_id=? AND provider='bricklink' AND provider_key=? AND status!='to_check'", (a, number)):
            if _same_scope(old, scope):
                log.update('item_link', old, status='to_check', preferred=0)
    return number


def change_variant_in(db, from_id, to_id, *, via, actor=None, operation_key=None):
    """Change the variant `from_id` to `to_id` for everything owned, inside the caller's open write transaction. Returns
    `{event_id, from, to, number, counts}`; the receipt is the event's `new_value` (see the module doc for what moves and what is refused)."""
    moves._need_transaction(db, 'change_variant_in')
    if from_id == to_id:
        raise MergeRefused('an item cannot become itself')
    old = moves._item(db, from_id)
    if old is None:
        raise MergeRefused(f'item {from_id} is not in this collection')
    if old['merged_into'] is not None:
        raise MergeRefused(f'item {from_id} is merged already (into {old["merged_into"]})')
    new = _item(db, to_id)
    if new['merged_into'] is not None:
        raise MergeRefused(f'item {to_id} is merged (into {new["merged_into"]}); change to that one')
    if new['kind'] != old['kind']:
        raise MergeRefused(f'item {from_id} is a {old["kind"]} and item {to_id} a {new["kind"]}: a variant changes only to one of its own kind')
    if old['kind'] == 'set':
        raise MergeRefused('a set cannot change variant here: a copy\'s part list is its set\'s own')
    moves._refuse_double_lines(db, from_id, to_id, LINES)
    moves._refuse_active_jobs(db, from_id, to_id)
    db.execute('PRAGMA defer_foreign_keys=ON')
    log = RowLog(db)
    _move_rows(db, log, from_id, to_id)
    number = _links(log, from_id, to_id)
    moves._foreign_keys(db, log.tables())
    counts = {}
    for change in log.changes:
        op = 'inserted' if change['b'] is None else 'deleted' if change['a'] is None else 'changed'
        counts.setdefault(change['t'], {}).setdefault(op, 0)
        counts[change['t']][op] += 1
    receipt = dict(item=to_id, **{'from': from_id, 'to': to_id}, number=number, counts=counts, changes=log.changes, dependents=moves._dependents(db, log))
    event = moves._event(db, via, actor, operation_key or uuid.uuid4().hex, 'item', to_id, FIELD, from_id, receipt)
    return {'event_id': event, 'from': from_id, 'to': to_id, 'number': number, 'counts': counts}


def undo_change_variant_in(db, event_id, *, via, actor=None, operation_key=None):
    """Put a change of variant back from its receipt (the event's `new_value`); refused when any row it changed differs now, or a row added since
    refers to a line it moved."""
    moves._need_transaction(db, 'undo_change_variant_in')
    event = db.execute('SELECT * FROM main.event WHERE id=?', (event_id,)).fetchone()
    if event is None or event['entity_kind'] != 'item' or event['field'] != FIELD:
        raise MergeRefused(f'event {event_id} is not a change of variant')
    if db.execute('SELECT 1 FROM main.event_undo WHERE event_id=?', (event_id,)).fetchone():
        raise MergeRefused(f'event {event_id} was undone already')
    receipt = json.loads(event['new_value'])
    moves._refuse_active_jobs(db, receipt['from'], receipt['to'])
    log = RowLog(db, receipt['changes'])
    changed = log.verify()
    if changed is not None:
        raise MergeRefused(f'{changed["t"]} changed since the change of variant · undo the later change first')
    known = receipt.get('dependents', {})
    for table, keys in moves._dependents(db, log).items():
        if set(keys) - set(known.get(table, ())):
            raise MergeRefused(f'{table} changed since the change of variant (a row added after it refers to a row it moved) · undo the later change first')
    db.execute('PRAGMA defer_foreign_keys=ON')
    try:
        log.restore()
    except sqlite3.IntegrityError as error:                     # a row added since now holds the original's key (stock or wish key)
        raise MergeRefused(f'a row added since the change of variant holds the place of one to restore ({error}) · '
                           'archive or change that row first, then undo') from None
    moves._foreign_keys(db, log.tables())
    undo = moves._event(db, via, actor, operation_key or uuid.uuid4().hex, 'item', receipt['to'], FIELD + '_undo', receipt['to'],
                        dict(undoes=event_id, restored=receipt['from']))
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event_id, undo))
    return {'event_id': undo, 'undoes': event_id}


def change_variant(db, from_id, to_id, *, via='cli', actor=None):
    """`change_variant_in` in its own transaction."""
    return moves._own_transaction(db, 'change_variant', change_variant_in, from_id, to_id, via=via, actor=actor)
