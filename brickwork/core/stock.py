"""Loose stock on the 4.0 store (M.8c, issue #110; design 2.4 invariant 9, 3.5, 4.5): add, merge and undo of an add.

The merge key of a live stock row is `(item, colour, condition, lot, storage)` with NULL equal to NULL, the unique index
`stock_merge_key` (a loose minifigure never merges: it carries its own part list). Callers own the transaction and the write lock;
`add_loose` raises when none is open. Editing, merging on edit and the ledger are the collection-writes piece (M.8d, M.8e)."""
import uuid

from ..store4 import copies, identity
from ..store4.connect import now
from .admin import audit

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
