"""Loose stock on the 4.0 store (M.8c, issue #110; design 2.4 invariant 9, 3.5, 4.5): add, merge and undo of an add.

The merge key of a live stock row is `(item, colour, condition, lot, storage)` with NULL equal to NULL, the unique index
`stock_merge_key` (a loose minifigure never merges: it carries its own part list). Callers own the transaction and the write lock;
`add_loose` raises when none is open. Editing and merging on edit (`plan_edit`, `apply_edit`) are the collection-writes piece (M.8d); the ledger is `core/ledger.py` (M.8e)."""
import json
import uuid

from ..store4 import copies, identity
from ..store4.connect import now
from .admin import OPERATION_KEY, audit, origin

MERGE_FIELDS = ('item_id', 'color_id', 'condition', 'lot_id', 'storage_id')
CONDITIONS = ('new', 'used', 'damaged')


def merge_key(row):
    return tuple(row[field] for field in MERGE_FIELDS)


def _figure_list(db, item_id, quantity):
    """The parts of a loose figure: the figure's own Rebrickable list (design 4.5), each line times the quantity. Projects the parts
    and colours the list names. Returns the list columns of the stock row and the `stock_part` lines `(item, colour, spare, quantity)`."""
    target = copies._figure_target(db, item_id, quantity)           # catalogue latest, else a fetched list, else 'none'
    for part in sorted({k[0] for k in target.parts}):
        identity.project(db, part)
    for colour in sorted({k[1] for k in target.parts}):
        identity.project_color(db, colour)
    columns = dict(inventory_source=target.source, inventory_version=target.version, fetched_inventory_id=target.fetched_inventory_id,
                   inventory_digest=target.digest)
    return columns, [(part, colour, spare, line * quantity) for (part, colour, spare), line in sorted(target.parts.items())]


def add_loose(db, *, item_id, color_id=None, quantity, condition, lot_id=None, storage_id=None, note=None, via=None, actor=None):
    """Add `quantity` of an item to loose stock: onto the live row with the same merge key, else a new row. A part needs a colour
    and any other kind has none. Returns the change `{id, created, quantity, before, after}` (rows as dicts), which is what
    `undo_added` needs and what the Add receipt keeps."""
    if not db.in_transaction:
        raise ValueError('Loose stock must be added in a transaction')
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError('Choose a positive whole quantity')
    if condition is not None and condition not in CONDITIONS:
        raise ValueError('Choose new, used or damaged')
    identity.project(db, item_id)
    kind = db.execute('SELECT kind FROM main.item WHERE id=?', (item_id,)).fetchone()['kind']
    if kind == 'set':
        raise ValueError('A set is a copy, not loose stock')
    if kind == 'part':
        if color_id is None:
            raise ValueError('Choose a colour for each part')
        identity.project_color(db, color_id)
    else:
        color_id = None
    before = None
    if kind != 'minifigure':
        row = db.execute('''SELECT * FROM main.stock WHERE archived_at IS NULL AND kind!='minifigure' AND item_id=? AND color_key=coalesce(?, 0)
                            AND condition_key=coalesce(?, '') AND lot_key=coalesce(?, '') AND storage_key=coalesce(?, '')''',
                         (item_id, color_id, condition, lot_id, storage_id)).fetchone()
        before = dict(row) if row else None
    stamp = now()
    stock_id = before['id'] if before else uuid.uuid4().hex
    if before:
        db.execute('UPDATE main.stock SET quantity=?, updated_at=? WHERE id=?', (before['quantity'] + quantity, stamp, stock_id))
    else:
        columns = dict(id=stock_id, kind=kind, item_id=item_id, color_id=color_id, quantity=quantity, condition=condition,
                       storage_id=storage_id, lot_id=lot_id, note=note, created_at=stamp, updated_at=stamp)
        lines = []
        if kind == 'minifigure':
            lists, lines = _figure_list(db, item_id, quantity)
            columns.update(lists)
        db.execute(f'INSERT INTO main.stock({", ".join(columns)}) VALUES({", ".join("?" * len(columns))})', tuple(columns.values()))
        db.executemany('INSERT INTO main.stock_part(stock_id, item_id, color_id, is_spare, quantity) VALUES(?, ?, ?, ?, ?)',
                       [(stock_id, *line) for line in lines])
    after = dict(db.execute('SELECT * FROM main.stock WHERE id=?', (stock_id,)).fetchone())
    audit(db, 'stock:' + stock_id, 'increased' if before else 'created', before, after, via=via, actor=actor)
    return dict(id=stock_id, created=before is None, quantity=quantity, before=before, after=after)


def undo_added(db, change, *, via=None, actor=None):
    """Reverse one `add_loose` change: archive the row it created, or take its quantity back off the row it increased. Refused when
    the row differs from what the add left (any later change: edit, merge, take, a later add onto it)."""
    row = db.execute('SELECT * FROM main.stock WHERE id=?', (change['id'],)).fetchone()
    current = dict(row) if row else None
    if current != change['after']:
        raise ValueError('Stock changed since this save · undo the later save first')
    stamp = now()
    if change['created']:
        db.execute('UPDATE main.stock SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, change['id']))
    else:
        db.execute('UPDATE main.stock SET quantity=?, updated_at=? WHERE id=?',
                   (current['quantity'] - change['quantity'], change['before']['updated_at'], change['id']))
    audit(db, 'stock:' + change['id'], 'undo', current, dict(db.execute('SELECT * FROM main.stock WHERE id=?', (change['id'],)).fetchone()),
          via=via, actor=actor)


def plan_edit(db, rows, edits):
    """Where an edit of live stock rows lands: `[(row id, target id or None)]`, in the order the rows are given.

    A row whose merge key, once `edits` are applied, equals the key of another live row merges into it (invariant 9: one live row per
    key). The other row is a stock row outside the selection, or a selected row that kept or took that key earlier in the order. A
    loose minifigure never merges (it carries its own part list); a selected row whose key does not change targets itself. One query
    finds the outside rows however many rows are edited."""
    if not any(field in MERGE_FIELDS for field in edits):
        return [(row['id'], None) for row in rows]
    keys = {row['id']: merge_key(dict(row, **{k: v for k, v in edits.items() if k in MERGE_FIELDS})) for row in rows if row['kind'] != 'minifigure'}
    outside = {}
    if keys:
        wanted = json.dumps(sorted(set(keys.values()), key=repr))
        for found in db.execute(f'''WITH k(item_id, color_id, condition, lot_id, storage_id) AS
                                (SELECT json_extract(value,'$[0]'), json_extract(value,'$[1]'), json_extract(value,'$[2]'), json_extract(value,'$[3]'),
                                        json_extract(value,'$[4]') FROM json_each(?))
                              SELECT s.id, k.item_id, k.color_id, k.condition, k.lot_id, k.storage_id FROM main.stock s JOIN k
                              ON s.item_id=k.item_id AND s.color_key=coalesce(k.color_id,0) AND s.condition_key=coalesce(k.condition,'')
                             AND s.lot_key=coalesce(k.lot_id,'') AND s.storage_key=coalesce(k.storage_id,'')
                              WHERE s.archived_at IS NULL AND s.kind!='minifigure' AND s.id NOT IN (SELECT value FROM json_each(?)) ORDER BY s.id''',
                                (wanted, json.dumps(sorted(row['id'] for row in rows)))):
            outside.setdefault(tuple(found)[1:], found[0])
    claimed, plan = {}, []
    for row in rows:
        key = keys.get(row['id'])
        target = None if key is None else claimed.get(key) or outside.get(key)
        if key is not None and target is None:
            claimed[key] = row['id']
        plan.append((row['id'], target))
    return plan


def _columns(db):
    return [r['name'] for r in db.execute('PRAGMA main.table_xinfo(stock)') if r['hidden'] == 0]


def _rows(db, ids):
    names = ','.join(_columns(db))
    return {r['id']: dict(r) for r in db.execute(f'SELECT {names} FROM main.stock WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(sorted(ids)),))}


def _sum(a, b):
    return None if a is None and b is None else (a or 0) + (b or 0)


def apply_edit(db, rows, edits, plan, *, stamp=None, via=None, actor=None):
    """Write an edit as `plan_edit` planned it, inside the caller's transaction, in a fixed number of statements however many rows.

    A row that merges is archived with the edits applied (so its merge key names the row it went into) and its quantity, missing and
    damaged counts are added to the target (`checked` stays only when both were checked); every other row takes the edits. Each row a
    merge touches also gets its own `merge` event with the row before and after."""
    if not db.in_transaction:
        raise ValueError('Loose stock must be edited in a transaction')
    stamp = stamp or now()
    by_id = {r['id']: r for r in rows}
    merges = [(row, target) for row, target in plan if target is not None]
    values = dict(edits, updated_at=stamp)
    sets = ','.join(f'{k}=?' for k in values)
    if merges:
        outside = {t for _, t in merges if t not in by_id}
        current = dict(by_id, **(_rows(db, outside) if outside else {}))
        before, state = {}, {}
        for row_id, target in merges:
            source, destination = by_id[row_id], state.setdefault(target, dict(current[target]))
            before.setdefault(target, dict(current[target]))
            before[row_id] = source
            destination['quantity'] += source['quantity']
            destination['missing'] = _sum(destination['missing'], source['missing'])
            destination['damaged'] = _sum(destination['damaged'], source['damaged'])
            destination['checked'] = 1 if destination['checked'] and source['checked'] else destination['checked']
        sources = json.dumps(sorted(row_id for row_id, _ in merges))
        db.execute(f'UPDATE main.stock SET {sets}, archived_at=? WHERE id IN (SELECT value FROM json_each(?))', (*values.values(), stamp, sources))
        db.execute('''UPDATE main.stock SET quantity=j.quantity, missing=j.missing, damaged=j.damaged, checked=j.checked, updated_at=?
                      FROM (SELECT json_extract(value,'$.id') AS id, json_extract(value,'$.quantity') AS quantity, json_extract(value,'$.missing') AS missing,
                                   json_extract(value,'$.damaged') AS damaged, json_extract(value,'$.checked') AS checked FROM json_each(?)) j
                      WHERE stock.id=j.id''', (stamp, json.dumps(list(state.values()))))
    plain = [row_id for row_id, target in plan if target is None]
    if plain:
        db.execute(f'UPDATE main.stock SET {sets} WHERE id IN (SELECT value FROM json_each(?))', (*values.values(), json.dumps(sorted(plain))))
    if merges:
        after = _rows(db, before)
        via, actor = (via, actor) if via else origin()
        payload = [dict(id=i, old=before[i], new=after[i]) for i in sorted(before)]
        db.execute('''INSERT INTO main.event(at,via,actor,entity_kind,entity_id,field,old_value,new_value,operation_key)
                      SELECT ?,?,?,'stock',json_extract(value,'$.id'),'merge',json_extract(value,'$.old'),json_extract(value,'$.new'),? FROM json_each(?)''',
                   (stamp, via, actor, OPERATION_KEY.get(), json.dumps(payload, sort_keys=True)))
