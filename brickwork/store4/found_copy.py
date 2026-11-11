"""Make a copy from found parts: one new copy of a set, built from loose stock rows, in one transaction under one event (issue #9, Build it).

`make_copy_in(db, set_item_id, takes, ...)` is the shared piece: Build Scout's *Build it* uses it, and so can any later action that turns parts
already held (a lot's found parts, say) into a copy. The caller decides which stock rows give how much (`takes`, a list of `(stock id, amount)`);
this function writes:

* the copy of the set from the catalogue's latest Rebrickable list (the list the Scout ranked with), its figure lines and its part lines
  (`copies.build_target`, the same target `create_copy_in` writes), every line starting as missing;
* the taken parts and whole figures into the lines that name them, lowering `missing` (a figure line's missing figures, and the missing parts
  of those figures, as `workbench.reduce_gap` does);
* the stock rows' quantities down by what was taken (a row that reaches 0 stays, as a Take leaves it);
* one `stock_transfer` row per take and line, kept as provenance as the Workbench keeps them;
* ONE event `copy` / `make_from_stock` whose receipt is a `RowLog` of every row the call changed or inserted.

Undo (`undo_make_copy_in`) puts the stock rows back and archives the copy, as the Add flow's Undo does (a copy is archived, never deleted); it
is refused when any row it changed differs now, or the copy has since been given flags, a check, photos or other transfers.

The copy gets condition `used`, completeness `complete` when nothing is missing and else `incomplete` (set by hand: the derived rule needs a
Set is checked flag), and `note`. Refused (`MergeRefused`): a take that names no live stock row or more than the row holds, a take that matches no
line of the copy or more than the line needs, a set with no catalogue part list."""
import json
import uuid

from . import copies, merge as moves
from .connect import now
from .errors import MergeRefused, Store4Error
from .rowlog import RowLog

FIELD = 'make_from_stock'


class NothingToBuild(Store4Error):
    """The set has no part list to build a copy from."""


def _target(db, set_item_id):
    """The copy's lines for the list the Scout used (the catalogue's latest Rebrickable one, whatever the set's preference says)."""
    try:
        return copies.build_target(db, set_item_id, {'source': 'rebrickable'})
    except copies.NoPartList as error:
        raise NothingToBuild(str(error)) from None


def make_copy_in(db, set_item_id, takes, *, via, actor=None, operation_key=None, note=None):
    """Make the copy inside the caller's open write transaction. Returns `dict(event_id, copy_id, pieces, figures, missing_parts, missing_figures,
    completeness)`; the receipt is the event's `new_value`."""
    moves._need_transaction(db, 'make_copy_in')
    target = _target(db, set_item_id)
    copies._project(db, target)
    log = RowLog(db)
    taken = {}                                                    # stock id -> amount (a stock row named twice is summed)
    for stock_id, amount in takes:
        if int(amount) < 1:
            raise MergeRefused('a take is a whole number above 0')
        taken[stock_id] = taken.get(stock_id, 0) + int(amount)
    rows = {}
    for stock_id, amount in taken.items():
        found = log.select('stock', "id=? AND archived_at IS NULL AND kind IN ('part','minifigure')", (stock_id,))
        if not found or found[0]['quantity'] < amount:
            raise MergeRefused(f'stock {stock_id} is not live or holds less than {amount}')
        rows[stock_id] = found[0]
    # what is taken per line key: (item, colour or None) -> [(stock id, amount)]
    pool = {}
    for stock_id, amount in taken.items():
        row = rows[stock_id]
        pool.setdefault((row['item_id'], None if row['kind'] == 'minifigure' else row['color_id']), []).append([stock_id, amount])
    stamp = now()
    copy_id = str(uuid.uuid4())
    lines = target.lines()
    transfers = []                                                # (kind, stock id, line table, line id, item, colour, amount)

    def draw(key, wanted):
        """Up to `wanted` from the pool of `key`: `[(stock id, amount)]`."""
        got, rest = [], wanted
        for entry in pool.get(key, ()):
            step = min(rest, entry[1])
            if step:
                got.append((entry[0], step))
                entry[1] -= step
                rest -= step
            if not rest:
                break
        return got

    figure_rows, figure_taken = {}, {}
    for fig in target.figures:
        got = draw((fig.item_id, None), fig.quantity)
        figure_taken[fig.item_id] = got
    taken_figs = {item: sum(a for _, a in got) for item, got in figure_taken.items()}
    log_copy = log.insert('copy', id=copy_id, item_id=set_item_id, inventory_source=target.source, inventory_version=target.version,
                          fetched_inventory_id=target.fetched_inventory_id, inventory_digest=target.digest, materialised_at=stamp, inventory_pending=None,
                          pending_job_id=None, condition='used', completeness='incomplete', completeness_source='manual', note=note,
                          created_at=stamp, updated_at=stamp)
    missing_figures = 0
    for fig in target.figures:
        missing = fig.quantity - taken_figs[fig.item_id]
        missing_figures += missing
        row = log.insert('copy_figure', copy_id=copy_id, item_id=fig.item_id, inventory_source=fig.source, inventory_version=fig.version,
                         fetched_inventory_id=fig.fetched_inventory_id, inventory_digest=fig.digest, quantity=fig.quantity, missing=missing, updated_at=stamp)
        figure_rows[fig.item_id] = (row['id'], fig.quantity, missing)
        for stock_id, amount in figure_taken[fig.item_id]:
            transfers.append(('figure', stock_id, 'copy_figure', row['id'], fig.item_id, None, amount))
    missing_parts = 0
    for (figure, item, colour, spare), quantity in sorted(lines.items(), key=lambda kv: tuple(-1 if x is None else x for x in kv[0])):
        figure_id, missing = None, 0
        if figure is not None:
            figure_id, figure_quantity, figure_missing = figure_rows[figure]
            missing = min(quantity, figure_missing * quantity // figure_quantity) if figure_quantity else 0
        elif not spare:
            got = draw((item, colour), quantity)
            missing = quantity - sum(a for _, a in got)
            missing_parts += missing
        part = log.insert('copy_part', copy_id=copy_id, copy_figure_id=figure_id, item_id=item, color_id=colour, is_spare=spare, quantity=quantity, missing=missing)
        if figure is None and not spare:
            for stock_id, amount in got:
                transfers.append(('part', stock_id, 'copy_part', part['id'], item, colour, amount))
    left = [(key, entry) for key, entries in pool.items() for entry in entries if entry[1]]
    if left:
        key, entry = left[0]
        raise MergeRefused(f'stock {entry[0]} gives {entry[1]} more of item {key[0]} than the copy has lines for')
    complete = not missing_parts and not missing_figures
    if complete:
        log.update('copy', log_copy, completeness='complete')
    before = {}
    for stock_id, amount in taken.items():
        before[stock_id] = json.dumps(rows[stock_id], sort_keys=True)
        log.update('stock', rows[stock_id], quantity=rows[stock_id]['quantity'] - amount, updated_at=stamp)
    moves._foreign_keys(db, log.tables())
    pieces = sum(a for t in transfers if t[0] == 'part' for a in (t[6],))
    figures = sum(t[6] for t in transfers if t[0] == 'figure')
    receipt = dict(copy=copy_id, item=set_item_id, taken=[[s, a] for s, a in taken.items()], pieces=pieces, figures=figures, missing_parts=missing_parts,
                   missing_figures=missing_figures, changes=log.changes)
    event = moves._event(db, via, actor, operation_key or uuid.uuid4().hex, 'copy', copy_id, FIELD, None, receipt)
    for kind, stock_id, table, line_id, item, colour, amount in transfers:
        db.execute('''INSERT INTO main.stock_transfer(at, kind, stock_id, copy_id, copy_part_id, copy_figure_id, stock_part_id, item_id, color_id, quantity,
                      source_snapshot, event_id) VALUES(?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)''',
                   (stamp, kind, stock_id, copy_id, line_id if table == 'copy_part' else None, line_id if table == 'copy_figure' else None, item, colour,
                    amount, before[stock_id], event))
    return dict(event_id=event, copy_id=copy_id, pieces=pieces, figures=figures, missing_parts=missing_parts, missing_figures=missing_figures,
                completeness='complete' if complete else 'incomplete')


def undo_make_copy_in(db, event_id, *, via, actor=None, operation_key=None):
    """Put the stock back and archive the copy a `make_copy_in` made, inside the caller's open write transaction."""
    moves._need_transaction(db, 'undo_make_copy_in')
    event = db.execute('SELECT * FROM main.event WHERE id=?', (event_id,)).fetchone()
    if event is None or event['entity_kind'] != 'copy' or event['field'] != FIELD:
        raise MergeRefused(f'event {event_id} is not a copy made from stock')
    if db.execute('SELECT 1 FROM main.event_undo WHERE event_id=?', (event_id,)).fetchone():
        raise MergeRefused(f'event {event_id} was undone already')
    receipt = json.loads(event['new_value'])
    copy_id = receipt['copy']
    copy = db.execute('SELECT archived_at FROM main.copy WHERE id=?', (copy_id,)).fetchone()
    if copy is None or copy['archived_at'] is not None:
        raise MergeRefused('the copy was archived since · nothing to undo')
    log = RowLog(db, receipt['changes'])
    changed = log.verify()
    if changed is not None:
        raise MergeRefused(f'{changed["t"]} changed since Build it · undo the later change first')
    for table, sql in (('flags', 'SELECT 1 FROM main.copy_flag WHERE copy_id=?'), ('a check', 'SELECT 1 FROM main.part_check WHERE copy_id=?'),
                       ('photos', 'SELECT 1 FROM main.photo WHERE copy_id=? AND archived_at IS NULL'), ('an allocation', 'SELECT 1 FROM main.allocation WHERE copy_id=?'),
                       ('another transfer', 'SELECT 1 FROM main.stock_transfer WHERE copy_id=? AND event_id!=?')):
        if db.execute(sql, (copy_id, event_id) if table == 'another transfer' else (copy_id,)).fetchone():
            raise MergeRefused(f'the copy has {table} since Build it · undo the later change first')
    only_stock = RowLog(db, [c for c in receipt['changes'] if c['t'] == 'stock'])
    try:
        only_stock.restore()
    except Exception as error:                                   # a row added since holds the place of one to restore
        raise MergeRefused(f'the stock could not be put back ({error})') from None
    stamp = now()
    db.execute('UPDATE main.copy SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, copy_id))
    undo = moves._event(db, via, actor, operation_key or uuid.uuid4().hex, 'copy', copy_id, FIELD + '_undo', None, dict(undoes=event_id, archived=copy_id))
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event_id, undo))
    return {'event_id': undo, 'undoes': event_id}
