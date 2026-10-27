"""The Workbench on the 4.0 store (M.8e, issue #110; design 5 `stock_transfer`, 4.4, 3.8): gaps, the Matcher, the Part Picker, Take and Give.

**Gaps.** What a copy lacks: a live set line's missing and damaged pieces, a live figure line's missing figures, a missing booklet or box
(a set copy without the status flag "Instructions present" / "Box present"), and a loose figure's missing parts. A retired line is no line,
a spare is not a gap, a figure's own parts are not set gaps (design 4.4, 4.5).

**Matching is by item id.** A gap names an item (and a colour for a part); loose stock matches when it is the same item in the same colour.
A booklet or box is the exception: a set's booklet is the item whose BrickLink number is the set's BrickLink number, so a gap and a stock
row meet on `('instructions', <that number>)`. Nothing is blocked because a link is still "to check" (the Rebrickable id is exact); the
mark stays on the row (`unresolved`) for the screen. Retired lines are never matched.

**Take and Give** move loose stock into a gap and lower the gap in one transaction under one `workbench` receipt event (tables before and
after, undone by `core/undo.py` through the collection's generic undoer). Each move also writes a `stock_transfer` row naming the rows
involved and that event; Undo keeps those rows (they are provenance, like the event itself).

A receipt's last entry may be `context` (what a history row says); it is not a table.
"""
from collections import Counter, defaultdict
import json

from . import add, collection, items
from . import stock as stock_module
from . import undo as undoing
from .errors import StaleMatch
from .transaction import transaction
from ..store4 import fetched
from ..store4.connect import has_catalogue, now as stamp_now

ENTITY = 'workbench'
GAP_KINDS = {'part': 'P', 'figure': 'M', 'stock-part': 'P', 'instructions': 'I', 'box': 'O'}
STATUS_FLAG = {'instructions': 'Instructions present', 'box': 'Box present'}
BOOKLET_KIND = {'instructions': 'instructions', 'box': 'box'}


def stamp():
    return stamp_now()


# ---------- flags and stock availability ----------

def flag(db, name):
    """The id of the live status flag called `name`, or None unless there is exactly one."""
    rows = db.execute("SELECT id FROM main.flag WHERE archived_at IS NULL AND kind='status' AND lower(name)=lower(?)", (name,)).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def asserted(db, copy_id, name):
    identifier = flag(db, name)
    return bool(identifier and db.execute('SELECT 1 FROM main.copy_flag WHERE copy_id=? AND flag_id=?', (copy_id, identifier)).fetchone())


def defective_figures(db):
    """Ids of the loose figures with a live part line marked missing or damaged: they are not offered."""
    return {r[0] for r in db.execute('SELECT DISTINCT stock_id FROM main.stock_part WHERE retired_at IS NULL AND (missing>0 OR damaged>0)')}


def available(db, row, *, defective=None):
    """How many of a loose stock row can be given: none when damaged, none for a figure whose own parts are defective."""
    if row['condition'] == 'damaged':
        return 0
    if row['kind'] == 'minifigure':
        bad = row['id'] in defective if defective is not None else db.execute(
            'SELECT 1 FROM main.stock_part WHERE stock_id=? AND retired_at IS NULL AND (missing>0 OR damaged>0)', (row['id'],)).fetchone()
        if bad:
            return 0
    return max(0, (row['quantity'] or 0) - (row['missing'] or 0) - (row['damaged'] or 0))


def part_gap(row, whole_missing=0):
    """Required replacements, with whole missing figures covering constituents."""
    return max(0, (row['missing'] or 0) + (row['damaged'] or 0) - whole_missing * (row['quantity'] or 0))


def identity(row):
    """What a gap or a stock row is matched by: `key` when the row carries one, else item and colour."""
    return row['key'] if 'key' in row else (row['item_id'], row['color_id'])


def _booklet_numbers(db, rows, id_column='item_id'):
    """`{item id: BrickLink number}` of booklet or box items, in one batch (None for an item with no BrickLink number)."""
    pairs = {(r[id_column], None) for r in rows}
    return {item: (label.bricklink[1] if label.bricklink else None) for (item, _), label in items.labels(db, pairs).items()}


def stock_key(row, numbers):
    """The matching key of a stock row (`numbers` is `_booklet_numbers` of the booklet and box rows)."""
    if row['kind'] in BOOKLET_KIND.values():
        return (row['kind'], numbers.get(row['item_id']))
    return (row['item_id'], row['color_id'])


# ---------- gaps ----------

def _scope(only):
    return (None, None) if only is None else (json.dumps(sorted(only[0])), json.dumps(sorted(only[1])))


def gaps(db, only=None):
    """Every gap, decorated for a screen; `only=(copy_ids, stock_ids)` keeps just those copies' and loose figures' gaps.

    A gap is `dict(target, target_id, copy_id, need, item_id, color_id, key, copy, ...)` plus the decoration of `collection.decorate`
    (`name`, `item_type`, `item_no`, `number_text`, `color_name`, `rgb`, `ink`, `image`, `unresolved`, ...). `target` is `part`
    (`target_id` = the copy_part id), `figure` (the copy_figure id), `instructions` / `box` (the copy id) or `stock-part` (the stock_part
    id of a loose figure, whose id is `copy_id`). Parts first, then figures, booklets and boxes, then loose figures' parts."""
    copy_scope, stock_scope = _scope(only)
    live_copy = 'SELECT c.id,c.item_id,c.completeness,c.completeness_source,c.condition,c.created_at FROM main.copy c WHERE c.archived_at IS NULL'
    copies = {r['id']: dict(r) for r in db.execute(live_copy + (' AND c.id IN (SELECT value FROM json_each(?))' if only is not None else '') + ' ORDER BY c.item_id,c.created_at,c.id', (copy_scope,) if only is not None else ())}
    for copy_id, label in collection.copy_labels(db, list(copies)).items():
        copies[copy_id]['label'] = label
    decorated = {r['item_id']: r for r in collection.decorate(db, [dict(item_id=i) for i in sorted({c['item_id'] for c in copies.values()})])}
    for c in copies.values():
        d = decorated[c['item_id']]
        c.update(set_no=d['item_no'], set_name=d['name'], name=d['name'], item_no=d['item_no'], item_type='S', number_text=d['number_text'], image=d['image'], unresolved=d['unresolved'])
    scope = ' AND p.copy_id IN (SELECT value FROM json_each(?))' if only is not None else ''
    args = (copy_scope,) if only is not None else ()
    result = []
    for r in db.execute('''SELECT p.* FROM main.copy_part p JOIN main.copy c ON c.id=p.copy_id AND c.archived_at IS NULL
                           WHERE p.retired_at IS NULL AND p.is_spare=0 AND p.copy_figure_id IS NULL AND (p.missing>0 OR p.damaged>0)''' + scope + ' ORDER BY p.id', args):
        need = part_gap(r)
        if need and r['copy_id'] in copies:
            result.append(dict(target='part', target_id=r['id'], copy_id=r['copy_id'], need=need, item_id=r['item_id'], color_id=r['color_id'],
                               quantity=r['quantity'], missing=r['missing'], damaged=r['damaged'], key=(r['item_id'], r['color_id']), copy=copies[r['copy_id']]))
    for r in db.execute('''SELECT f.* FROM main.copy_figure f JOIN main.copy c ON c.id=f.copy_id AND c.archived_at IS NULL
                           WHERE f.retired_at IS NULL AND f.missing>0''' + scope.replace('p.copy_id', 'f.copy_id') + ' ORDER BY f.id', args):
        if r['copy_id'] in copies:
            result.append(dict(target='figure', target_id=r['id'], copy_id=r['copy_id'], need=r['missing'], item_id=r['item_id'], color_id=None,
                               quantity=r['quantity'], missing=r['missing'], damaged=0, key=(r['item_id'], None), copy=copies[r['copy_id']]))
    asserted_flags = {(r[0], r[1]) for r in db.execute('SELECT copy_id,flag_id FROM main.copy_flag')}
    set_numbers = _booklet_numbers(db, [dict(item_id=c['item_id']) for c in copies.values()])
    status_ids = {target: flag(db, name) for target, name in STATUS_FLAG.items()}
    for c in copies.values():
        for target, name in STATUS_FLAG.items():
            found = status_ids[target]
            if found and (c['id'], found) not in asserted_flags:
                result.append(dict(target=target, target_id=c['id'], copy_id=c['id'], need=1, item_id=c['item_id'], color_id=None, quantity=1, missing=1, damaged=0,
                                   key=(target, set_numbers.get(c['item_id'])), copy=c, name=name.replace(' present', ' missing')))
    for r in db.execute('''SELECT p.*,s.item_id AS figure_item FROM main.stock_part p JOIN main.stock s ON s.id=p.stock_id
                           WHERE s.archived_at IS NULL AND s.quantity>0 AND s.kind='minifigure' AND p.retired_at IS NULL AND p.is_spare=0 AND p.missing>0'''
                          + (' AND s.id IN (SELECT value FROM json_each(?))' if only is not None else '') + ' ORDER BY s.created_at,s.id,p.id',
                          (stock_scope,) if only is not None else ()):
        result.append(dict(target='stock-part', target_id=r['id'], copy_id=r['stock_id'], need=r['missing'], item_id=r['item_id'], color_id=r['color_id'],
                           quantity=r['quantity'], missing=r['missing'], damaged=r['damaged'], key=(r['item_id'], r['color_id']), figure_item=r['figure_item']))
    figure_stock = {g['copy_id'] for g in result if g['target'] == 'stock-part'}
    loose = {}
    if figure_stock:
        figures = {r['id']: dict(r) for r in db.execute('SELECT id,item_id FROM main.stock WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(sorted(figure_stock)),))}
        fig_decorated = {r['item_id']: r for r in collection.decorate(db, [dict(item_id=i) for i in sorted({f['item_id'] for f in figures.values()})])}
        for stock_id, f in figures.items():
            d = fig_decorated[f['item_id']]
            loose[stock_id] = dict(id=stock_id, item_id=f['item_id'], set_no=d['item_no'], set_name=d['name'], name=d['name'], item_no=d['item_no'], label='Loose minifigure', item_type='M',
                                   number_text=d['number_text'], image=d['image'], unresolved=d['unresolved'], completeness=None, completeness_source=None)
    for g in result:
        if g['target'] == 'stock-part':
            g['copy'] = loose[g['copy_id']]
    custom = [g.pop('name', None) for g in result]
    decorated = collection.decorate(db, [dict(item_id=g['item_id'], color_id=g['color_id']) for g in result])
    for g, d, name in zip(result, decorated, custom):
        g.update({k: v for k, v in d.items() if k not in ('item_id', 'color_id')})
        if g['target'] in STATUS_FLAG:                       # a missing booklet or box: the set's number and picture, its own words
            g.update(name=name, item_type=GAP_KINDS[g['target']], kind=g['target'], color_name=None, rgb=None, ink=None)
        g['unresolved'] = bool(g['unresolved'] or g['copy'].get('unresolved'))
    return result


def relevant(db, item_id, colour, kind, *, copy_ids=(), stock_ids=()):
    """Copies and loose figures whose gaps can reach the matches of one item: those holding a gap on it, and the named ones.

    A superset is fine: `gaps(only=...)` returns every gap of these and the caller filters. A copy is relevant when it holds a gap on the
    item's identity or is named; its other gaps matter because `completes` counts all of a copy's gaps. A booklet or box can fill any set
    copy, so all copies are relevant to it."""
    copies, stock = set(copy_ids), set(stock_ids)
    if kind in BOOKLET_KIND.values():
        copies.update(r[0] for r in db.execute('SELECT id FROM main.copy WHERE archived_at IS NULL'))
        return copies, stock
    copies.update(r[0] for r in db.execute('''SELECT DISTINCT copy_id FROM main.copy_part WHERE item_id=? AND color_id IS ? AND is_spare=0 AND retired_at IS NULL
                                              AND copy_figure_id IS NULL AND (missing>0 OR damaged>0)''', (item_id, colour)))
    copies.update(r[0] for r in db.execute('SELECT DISTINCT copy_id FROM main.copy_figure WHERE item_id=? AND retired_at IS NULL AND missing>0', (item_id,)))
    stock.update(r[0] for r in db.execute('SELECT DISTINCT stock_id FROM main.stock_part WHERE item_id=? AND color_id IS ? AND is_spare=0 AND retired_at IS NULL AND missing>0', (item_id, colour)))
    return copies, stock


def completion_context(db, all_gaps):
    """Group required gaps once and load copy-level ranking facts once: `({copy: Counter(key)}, {copies with "Set is checked"})`."""
    counts = defaultdict(Counter)
    for gap in all_gaps:
        if gap['target'] in ('part', 'figure'):
            counts[gap['copy_id']][identity(gap)] += 1
    identifier = flag(db, 'Set is checked')
    checked = {r[0] for r in db.execute('SELECT copy_id FROM main.copy_flag WHERE flag_id=?', (identifier,))} if identifier else set()
    return counts, checked


# ---------- the Matcher ----------

def _usable_stock(db, wanted):
    """`{key: [(stock row, have)]}` for the live loose stock whose key some gap wants and of which some can be given."""
    rows = [dict(r) for r in db.execute("SELECT * FROM main.stock WHERE archived_at IS NULL AND quantity>0 AND kind IN ('part','minifigure','instructions','box') ORDER BY id")]
    numbers = _booklet_numbers(db, [r for r in rows if r['kind'] in BOOKLET_KIND.values()])
    defective = defective_figures(db)
    found = defaultdict(list)
    for row in rows:
        key = stock_key(row, numbers)
        if key not in wanted or key[1] is None and row['kind'] in BOOKLET_KIND.values():
            continue
        have = available(db, row, defective=defective)
        if have:
            found[key].append((row, have))
    return found


def matches(db, *, all_gaps=None):
    """Loose stock that could fill gaps: one row per (gap, stock row), completing matches first, then the larger amount."""
    all_gaps = gaps(db) if all_gaps is None else all_gaps
    counts, eligible = completion_context(db, all_gaps)
    totals = {copy_id: sum(keys.values()) for copy_id, keys in counts.items()}
    stock = _usable_stock(db, {identity(g) for g in all_gaps})
    result = []
    for gap in all_gaps:
        for source, have in stock.get(identity(gap), ()):
            completes = gap['target'] in ('part', 'figure') and totals[gap['copy_id']] == 1 and gap['copy_id'] in eligible and have >= gap['need']
            result.append(dict(gap, source_id=source['id'], have=have, suggested=min(have, gap['need']), completes=bool(completes),
                               source_note=source['note'], storage=source['storage_id']))
    return sorted(result, key=lambda r: (not r['completes'], -r['suggested'], r['copy']['set_no'], r['copy_id'], r['source_id']))


def group_matches(db, rows, all_gaps):
    """Candidate coverage per copy; stock is capped within each copy, not reserved."""
    grouped = {}
    for row in rows:
        group = grouped.setdefault(row['copy_id'], dict(copy=row['copy'], rows=[], covered=0, missing=0, completes=False, owned_copy=row['target'] != 'stock-part'))
        group['rows'].append(row)
    _, checked_copies = completion_context(db, all_gaps)
    gaps_by_copy = defaultdict(list)
    for gap in all_gaps:
        gaps_by_copy[gap['copy_id']].append(gap)
    for identifier, group in grouped.items():
        remaining = {r['source_id']: r['have'] for r in group['rows']}
        candidates = defaultdict(list)
        for row in group['rows']:
            candidates[(row['target'], str(row['target_id']))].append(row)
        required_missing = required_covered = 0
        for gap in gaps_by_copy[identifier]:
            need, covered = gap['need'], 0
            for row in candidates[(gap['target'], str(gap['target_id']))]:
                amount = min(need - covered, remaining[row['source_id']])
                covered += amount
                remaining[row['source_id']] -= amount
            group['missing'] += need
            group['covered'] += covered
            if gap['target'] in ('part', 'figure'):
                required_missing += need
                required_covered += covered
        c = group['copy']
        group['completes'] = bool(required_missing and required_missing == required_covered
                                  and identifier in checked_copies and c.get('completeness_source') == 'derived')
        group['kinds'] = list(dict.fromkeys(r['item_type'] for r in group['rows']))
    return sorted((g for g in grouped.values() if g['missing']),
                  key=lambda g: (not g['completes'], -(g['covered'] / g['missing'] if g['missing'] else 1), g['copy']['set_no'], g['copy']['id']))


# ---------- the Part Picker ----------

PICKER_KEYS = ('category', 'colour', 'size', 'set', 'storage')
PICKER_DEFAULT = PICKER_KEYS


def picker(db, selected, ranking=None, *, all_gaps=None):
    """The missing parts of the chosen copies, one row per part and colour, in the picking order."""
    all_gaps = gaps(db) if all_gaps is None else all_gaps
    selected = set(selected)
    counts, eligible = completion_context(db, all_gaps)
    totals = {copy_id: sum(keys.values()) for copy_id, keys in counts.items()}
    grouped = {}
    for r in (r for r in all_gaps if r['target'] == 'part' and r['copy_id'] in selected):
        g = grouped.setdefault(identity(r), dict(r, needs=[], total=0, completes=0))
        g['needs'].append(r)
        g['total'] += r['need']
    for g in grouped.values():
        for copy_id in {r['copy_id'] for r in g['needs']}:
            if totals[copy_id] == counts[copy_id][identity(g)] and copy_id in eligible:
                g['completes'] += 1
    categories = {r[0]: (r[1] or '').strip() for r in db.execute('SELECT id,category_name FROM main.item WHERE id IN (SELECT value FROM json_each(?))',
                                                                  (json.dumps(sorted({g['item_id'] for g in grouped.values()})),))}
    for g in grouped.values():
        g['category'] = categories.get(g['item_id']) or None
    storage_names = defaultdict(set)
    defective = defective_figures(db)
    for raw in db.execute('''SELECT s.*,t.name AS storage_name FROM main.stock s JOIN main.storage t ON t.id=s.storage_id
                             WHERE s.kind='part' AND s.archived_at IS NULL AND t.archived_at IS NULL AND t.name IS NOT NULL'''):
        source = dict(raw)
        if available(db, source, defective=defective):
            storage_names[(source['item_id'], source['color_id'])].add(source['storage_name'])
    for g in grouped.values():
        g['rank_set'] = min(r['copy']['set_no'] for r in g['needs'])
        g['rank_storage'] = ' · '.join(sorted(storage_names[identity(g)]))
    return order_picker(list(grouped.values()), ranking)


def picker_keys(rows):
    """Availability is based on the selected snapshot, never guessed dimensions."""
    reasons = dict(size='No part sizes are recorded',
                   category='' if any(r.get('category') for r in rows) else 'No category is recorded for these parts',
                   storage='' if any(r.get('rank_storage') for r in rows) else 'No usable loose parts have a recorded location')
    return [dict(key=k, label=k.capitalize(), reason=reasons.get(k, '')) for k in PICKER_KEYS]


def order_picker(rows, ranking=None):
    enabled = set(k['key'] for k in picker_keys(rows) if not k['reason'])
    ranking = list(dict.fromkeys(k for k in (PICKER_DEFAULT if ranking is None else ranking) if k in enabled))

    def key(row):
        values = dict(completes=-row['completes'], colour=row.get('color_name') or '', category=row.get('category') or '', set=row['rank_set'], storage=row['rank_storage'])
        return tuple((k != 'colour' and values[k] == '', values[k]) for k in ranking) + (-row['completes'], row['item_no'], row['color_id'] or 0, row['item_id'])
    return sorted(rows, key=key)


# ---------- the receipt of a request ----------

class Tracker:
    """Collects the rows a request changes, before and after, and writes the one receipt event (`collection.receipt`'s tables format).

    `touch` a row (or link set) before changing it; `created` the rows the request inserts; `write` then snapshots every touched row
    again, keeps those that really changed and writes the event. A modified row and a created row of one table are separate entries
    (the undoer archives created rows and puts modified rows back)."""

    def __init__(self, db):
        self.db = db
        self.before = {}               # table -> {id: row dict, or None for a row the request created}
        self.links = {}                # link table -> {owner id: rows before}
        self.extra = None

    def touch(self, table, *ids):
        seen = self.before.setdefault(table, {})
        new = [i for i in dict.fromkeys(ids) if i not in seen]
        if new:
            rows = {r['id']: r for r in collection.snapshot(self.db, table, new)}
            for identifier in new:
                seen[identifier] = rows.get(identifier if table not in collection.INTEGER_IDS else int(identifier))

    def touch_links(self, table, owner):
        self.links.setdefault(table, {}).setdefault(owner, collection.links(self.db, table, owner))

    def created(self, table, identifier):
        self.before.setdefault(table, {}).setdefault(identifier, None)

    def context(self, **values):
        self.extra = values

    def entries(self):
        entries = []
        for table, seen in self.before.items():
            now_rows = {r['id']: r for r in collection.snapshot(self.db, table, list(seen))}
            changed = [i for i, old in seen.items() if old is not None and now_rows.get(i) != old]
            if changed:
                after = collection.snapshot(self.db, table, changed)
                entries.append((table, [seen[r['id']] for r in after], after))
            made = [i for i, old in seen.items() if old is None and i in now_rows]
            if made:
                entries.append((table, [], collection.snapshot(self.db, table, made)))
        for table, owners in self.links.items():
            for owner, old in owners.items():
                new = collection.links(self.db, table, owner)
                if new != old:
                    entries.append((table, old, new))
        return entries

    def write(self, field, entity=ENTITY):
        entries = self.entries()
        if self.extra is not None:
            entries.append(('context', [self.extra], [self.extra]))
        return collection.receipt(self.db, entries, field, entity=entity)


def _recompute(db, tracker, copy_id):
    """A copy whose completeness is derived follows its gaps."""
    state = collection_derived(db, copy_id)
    if state is None:
        return
    row = db.execute('SELECT completeness FROM main.copy WHERE id=?', (copy_id,)).fetchone()
    if state != row['completeness']:
        tracker.touch('copy', copy_id)
        db.execute('UPDATE main.copy SET completeness=?,updated_at=? WHERE id=?', (state, stamp(), copy_id))


def collection_derived(db, copy_id):
    from .completeness import derived_state
    return derived_state(db, copy_id)


def reduce_gap(db, tracker, gap, amount, *, update_completeness=True):
    """Lower a gap by `amount` (a part's missing first, then its damaged; a figure's missing and its parts'; a flag set)."""
    target = gap['target']
    if target == 'part':
        tracker.touch('copy_part', gap['target_id'])
        db.execute('UPDATE main.copy_part SET missing=max(0,missing-?),damaged=max(0,damaged-max(0,?-missing)) WHERE id=?', (amount, amount, gap['target_id']))
    elif target == 'stock-part':
        tracker.touch('stock_part', gap['target_id'])
        db.execute('UPDATE main.stock_part SET missing=missing-? WHERE id=?', (amount, gap['target_id']))
    elif target == 'figure':
        tracker.touch('copy_figure', gap['target_id'])
        db.execute('UPDATE main.copy_figure SET missing=missing-? WHERE id=?', (amount, gap['target_id']))
        # Parts covered by the whole missing figure cease to be missing too.
        # A component row's quantity already counts every figure of the line, so one figure covers quantity / figures of it.
        figures = db.execute('SELECT quantity FROM main.copy_figure WHERE id=?', (gap['target_id'],)).fetchone()[0] or 1
        for part in db.execute('SELECT * FROM main.copy_part WHERE copy_figure_id=? AND retired_at IS NULL AND is_spare=0', (gap['target_id'],)).fetchall():
            delta = min(part['missing'] + part['damaged'], amount * part['quantity'] // figures)
            if delta:
                tracker.touch('copy_part', part['id'])
                db.execute('UPDATE main.copy_part SET missing=max(0,missing-?),damaged=max(0,damaged-max(0,?-missing)) WHERE id=?', (delta, delta, part['id']))
    else:
        tracker.touch_links('copy_flag', gap['copy_id'])
        db.execute('INSERT INTO main.copy_flag(copy_id,flag_id) VALUES(?,?)', (gap['copy_id'], flag(db, STATUS_FLAG[target])))
    if update_completeness and target != 'stock-part':
        _recompute(db, tracker, gap['copy_id'])


def requested_gap(db, source, copy_id, target, target_id):
    """Read only the requested copy (or loose figure) and line under the write lock; None when it is not a gap `source` can fill."""
    skey = stock_key(source, _booklet_numbers(db, [source]) if source['kind'] in BOOKLET_KIND.values() else {})
    if target == 'stock-part':
        figure = db.execute("SELECT * FROM main.stock WHERE id=? AND archived_at IS NULL AND quantity>0 AND kind='minifigure'", (copy_id,)).fetchone()
        try:
            part_id = int(target_id)
        except (TypeError, ValueError):
            return None
        row = db.execute('SELECT * FROM main.stock_part WHERE id=? AND stock_id=? AND retired_at IS NULL AND is_spare=0 AND missing>0', (part_id, copy_id)).fetchone() if figure else None
        if not row or (row['item_id'], row['color_id']) != skey:
            return None
        return dict(row, copy_id=copy_id, target=target, target_id=row['id'], need=row['missing'], key=skey)
    copy = db.execute('SELECT * FROM main.copy WHERE id=? AND archived_at IS NULL', (copy_id,)).fetchone()
    if not copy:
        return None
    if target == 'part':
        try:
            part_id = int(target_id)
        except (TypeError, ValueError):
            return None
        row = db.execute('''SELECT * FROM main.copy_part WHERE copy_id=? AND id=? AND is_spare=0 AND copy_figure_id IS NULL AND retired_at IS NULL
                            AND (missing>0 OR damaged>0)''', (copy_id, part_id)).fetchone()
        if not row or (row['item_id'], row['color_id']) != skey:
            return None
        return dict(row, copy_id=copy_id, target=target, target_id=row['id'], need=part_gap(row), key=skey)
    if target == 'figure':
        try:
            figure_id = int(target_id)
        except (TypeError, ValueError):
            return None
        row = db.execute('SELECT * FROM main.copy_figure WHERE id=? AND copy_id=? AND retired_at IS NULL AND missing>0', (figure_id, copy_id)).fetchone()
        if not row or (row['item_id'], None) != skey:
            return None
        return dict(row, color_id=None, copy_id=copy_id, target=target, target_id=row['id'], need=row['missing'], key=skey)
    if target in STATUS_FLAG:
        name = STATUS_FLAG[target]
        if str(target_id) != str(copy_id) or not flag(db, name) or asserted(db, copy_id, name):
            return None
        number = _booklet_numbers(db, [copy])[copy['item_id']]
        if number is None or skey != (target, number):
            return None
        return dict(item_id=copy['item_id'], color_id=None, copy_id=copy_id, target=target, target_id=copy_id, need=1, key=skey)
    return None


def move_stock(db, tracker, source, match, amount):
    """One source row into one gap: the stock arithmetic behind every transfer and take. Returns the `stock_transfer` row to write."""
    tracker.touch('stock', source['id'])
    snapshot = json.dumps(tracker.before['stock'][source['id']], sort_keys=True)
    db.execute('UPDATE main.stock SET quantity=quantity-?,updated_at=? WHERE id=?', (amount, stamp(), source['id']))
    reduce_gap(db, tracker, match, amount)
    target = match['target']
    return dict(kind=target, stock_id=source['id'], copy_id=None if target == 'stock-part' else match['copy_id'],
                copy_part_id=match['target_id'] if target == 'part' else None, copy_figure_id=match['target_id'] if target == 'figure' else None,
                stock_part_id=match['target_id'] if target == 'stock-part' else None, item_id=source['item_id'], color_id=source['color_id'],
                quantity=amount, source_snapshot=snapshot)


def _finish_transfer(db, tracker, transfers, field, **context):
    """Write the receipt, then the `stock_transfer` rows that name its event. Returns the event id."""
    tracker.context(**context)
    event = tracker.write(field)
    when = stamp()
    for t in transfers:
        db.execute('''INSERT INTO main.stock_transfer(at,kind,stock_id,copy_id,copy_part_id,copy_figure_id,stock_part_id,item_id,color_id,quantity,source_snapshot,event_id)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (when, t['kind'], t['stock_id'], t['copy_id'], t['copy_part_id'], t['copy_figure_id'], t['stock_part_id'],
                                                             t['item_id'], t['color_id'], t['quantity'], t['source_snapshot'], event))
    return event


def transfer(db, source_id, copy_id, target, target_id, amount):
    """Give (or Take) `amount` of one stock row into one gap. Raises `StaleMatch` when the stock or the gap changed."""
    amount = add.quantity(amount)
    with transaction(db):
        row = db.execute("SELECT * FROM main.stock WHERE id=? AND archived_at IS NULL AND quantity>0 AND kind IN ('part','minifigure','instructions','box')", (source_id,)).fetchone()
        source = dict(row) if row else None
        match = requested_gap(db, source, copy_id, target, target_id) if source else None
        if not match or amount > min(available(db, source), match['need']):
            raise StaleMatch('Stock or missing count changed · review matches again')
        tracker = Tracker(db)
        moved = move_stock(db, tracker, source, match, amount)
        return _finish_transfer(db, tracker, [moved], 'transfer', item_id=source['item_id'], color_id=source['color_id'], quantity=amount, target=target)


def take_for_gap(db, copy_id, item_id, color_id, quantity_wanted):
    """Take N of one missing part (or whole minifigure) from loose stock into a set copy, all or nothing.

    Sources follow the Matcher's order per gap (largest usable amount first, then stock id); one transaction and one receipt, so one
    Undo reverses every move."""
    amount = add.quantity(quantity_wanted)
    kind = (db.execute('SELECT kind FROM main.item WHERE id=?', (item_id,)).fetchone() or [None])[0]
    figure = kind == 'minifigure'
    if figure:
        color_id = None
    elif kind != 'part' or color_id is None:
        raise ValueError('Only parts with a colour and whole minifigures can be taken')
    with transaction(db):
        stock = [dict(r) for r in db.execute('SELECT * FROM main.stock WHERE item_id=? AND color_id IS ? AND archived_at IS NULL AND quantity>0 ORDER BY id', (item_id, color_id))]
        if not stock:
            raise ValueError('Nothing is left in loose stock')
        sample = stock[0]
        wanted = []
        if figure:
            rows = db.execute('SELECT id FROM main.copy_figure WHERE copy_id=? AND item_id=? AND retired_at IS NULL AND missing>0 ORDER BY id', (copy_id, item_id)).fetchall()
            target = 'figure'
        else:
            rows = db.execute('''SELECT id FROM main.copy_part WHERE copy_id=? AND item_id=? AND color_id=? AND is_spare=0 AND copy_figure_id IS NULL AND retired_at IS NULL
                                 AND (missing>0 OR damaged>0) ORDER BY id''', (copy_id, item_id, color_id)).fetchall()
            target = 'part'
        for row in rows:
            gap = requested_gap(db, sample, copy_id, target, row['id'])
            if gap:
                wanted.append(gap)
        missing = sum(g['need'] for g in wanted)
        if not missing:
            raise ValueError('Nothing is missing of this ' + ('minifigure' if figure else 'part'))
        if amount > missing:
            raise ValueError(f'Only {missing} are missing')
        defective = defective_figures(db) if figure else None
        have = {s['id']: available(db, s, defective=defective) for s in stock}
        usable = sum(have.values())
        if amount > usable:
            raise ValueError(f'Only {usable} are left in loose stock' if usable else 'Nothing is left in loose stock')
        by_id = {s['id']: s for s in stock if have[s['id']]}
        tracker, moved, left = Tracker(db), [], amount
        for gap in wanted:
            need = gap['need']
            while left and need and by_id:
                # Matcher order from the in-memory amounts: largest usable first, then lowest id.
                chosen = min(by_id, key=lambda i: (-min(have[i], need), i))
                source = by_id[chosen]
                step = min(left, need, have[chosen])
                moved.append(move_stock(db, tracker, source, gap, step))
                source['quantity'] -= step
                have[chosen] -= step
                if not have[chosen]:
                    del by_id[chosen]
                left -= step
                need -= step
        if left:
            raise StaleMatch('Stock or missing count changed · try again')
        return _finish_transfer(db, tracker, moved, 'transfer', item_id=item_id, color_id=color_id, quantity=amount, target=target)


def found(db, item_id, color_id, destination, assignments, amount):
    """The picker's "Found it": lower the chosen copies' gaps of a part, add it to loose stock, or only record the find."""
    amount = add.quantity(amount)
    if destination not in ('set', 'loose', 'list'):
        raise ValueError('Choose a resolved part and destination')
    with transaction(db):
        row = db.execute("SELECT kind FROM main.item WHERE id=?", (item_id,)).fetchone()
        if not row or row['kind'] != 'part' or color_id is None or not db.execute('SELECT 1 FROM main.color WHERE id=?', (color_id,)).fetchone():
            raise ValueError('Part or colour is unavailable')
        tracker = Tracker(db)
        if destination == 'set':
            current = {str(r['target_id']): r for r in gaps(db) if r['target'] == 'part' and (r['item_id'], r['color_id']) == (item_id, color_id)}
            if not isinstance(assignments, dict) or not assignments or sum(add.quantity(q) for q in assignments.values()) != amount:
                raise ValueError('Assign the found count to copies')
            for identifier, q in assignments.items():
                q = add.quantity(q)
                gap = current.get(str(identifier))
                if not gap or q > gap['need']:
                    raise StaleMatch('Missing count changed · review the part again')
                reduce_gap(db, tracker, gap, q)
        elif destination == 'loose':
            change = stock_module.add_loose(db, item_id=item_id, color_id=color_id, quantity=amount, condition='used')
            _note_added(tracker, change)
        tracker.context(item_id=item_id, color_id=color_id, quantity=amount, destination=destination)
        return tracker.write('found')


def _note_added(tracker, change):
    """Tell the tracker about a stock row `stock.add_loose` created or increased (its before state is the change's)."""
    seen = tracker.before.setdefault('stock', {})
    if change['id'] not in seen:
        names = collection.columns(tracker.db, 'stock')            # `add_loose` reads `SELECT *`, which carries the generated columns too
        seen[change['id']] = {k: v for k, v in change['before'].items() if k in names} if change['before'] else None


def booklet_item(db, number):
    """`(item id, error)` of the instruction booklet a number names: the full number (`4819-1`), or a bare set number with exactly one
    booklet (`4819`). A booklet is an item of kind `instructions`: one the collection already holds, else one the BrickLink item list
    (catalogue `bricklink_item`, type I, when loaded) names, which is created as a local BrickLink-born item. A set's own number does
    not name its booklet. The item id is `('new', number, name)` for a booklet to create."""
    number = number.strip()
    held = {r['born_key']: r['id'] for r in db.execute("SELECT id,born_key FROM main.item WHERE kind='instructions' AND born_key IS NOT NULL AND merged_into IS NULL "
                                                      'AND (born_key=? OR born_key GLOB ?)', (number, number + '-[0-9]*'))}
    if has_catalogue(db):
        held.update({r['born_key']: r['id'] for r in db.execute("SELECT id,born_key FROM catalogue.item WHERE kind='instructions' AND retired_at IS NULL "
                                                               'AND (born_key=? OR born_key GLOB ?)', (number, number + '-[0-9]*'))
                     if r['born_key'] not in held})
    listed = {}
    if has_catalogue(db):
        listed = {r['item_no']: r['name'] for r in db.execute("SELECT item_no,name FROM catalogue.bricklink_item WHERE item_type='I' AND (item_no=? OR item_no GLOB ?)",
                                                              (number, number + '-[0-9]*')) if r['item_no'] not in held}
    names = {k for k in (*held, *listed) if k == number or (k.startswith(number + '-') and k[len(number) + 1:].isdigit())}
    if '-' in number:
        names = names & {number}
    if len(names) != 1:
        return None, 'ambiguous; enter the full booklet number' if names else 'unknown booklet number'
    key = names.pop()
    return (held[key] if key in held else ('new', key, listed[key])), 'unknown booklet number'


def booklets(db, text, amount):
    """Add physical booklets to loose stock: one booklet number per line, an optional `,quantity`."""
    import re
    amount = add.quantity(amount)
    if amount > 99 or not isinstance(text, str) or len(text) > 20000:
        raise ValueError('Enter up to 200 booklet lines · quantity 1 to 99')
    lines = [(index, s.strip()) for index, s in enumerate(text.splitlines(), 1) if s.strip()]
    if not 1 <= len(lines) <= 200:
        raise ValueError('Enter 1 to 200 booklet lines')
    parsed, errors_ = [], []
    for index, line in lines:
        cells = [s.strip() for s in line.split(',')]
        if len(cells) > 2 or not re.fullmatch(r'[A-Za-z0-9]+(?:-[0-9]+)?', cells[0]):
            raise ValueError(f'Line {index}: use a set number, optionally comma and quantity')
        q = add.quantity(cells[1]) if len(cells) == 2 else amount
        if q > 99:
            raise ValueError(f'Line {index}: quantity must be 1 to 99')
        item, reason = booklet_item(db, cells[0])
        if item is None:
            errors_.append(f'Line {index}: {cells[0]} · {reason}')
        else:
            parsed.append((item, q))
    if errors_:
        raise ValueError('Nothing was saved · ' + '; '.join(errors_))
    with transaction(db):
        tracker = Tracker(db)
        for item, q in parsed:
            if isinstance(item, tuple):                                   # a booklet the BrickLink list names and no item holds yet
                _, key, name = item
                item = fetched.create_local_item(db, kind='instructions', born_provider='bricklink', born_namespace='I', born_key=key, name=name, kind_source='bricklink')
                fetched.add_item_link(db, item, provider='bricklink', provider_kind='I', provider_key=key, status='matched', method='bricklink_list', origin='bricklink_list')
            change = stock_module.add_loose(db, item_id=item, quantity=q, condition='used')
            _note_added(tracker, change)
        tracker.context(lines=len(parsed), quantity=sum(q for _, q in parsed))
        return tracker.write('booklets')


# ---------- undo and history ----------

def undo(db, event_id, *, receipt=None):
    """Undo a workbench receipt; a second Undo of the same receipt does nothing."""
    row = db.execute('SELECT entity_kind FROM main.event WHERE id=?', (int(event_id),)).fetchone()
    if row is None or row['entity_kind'] != ENTITY:
        raise ValueError('Save is unavailable')
    return collection.undo(db, event_id)


def _undo_receipt(db, event, via, actor):
    return collection._undo_collection(db, event, via, actor)


for _field in ('transfer', 'found', 'booklets'):
    undoing.register(ENTITY, _field, _undo_receipt)


def history(db, limit=50):
    """The newest workbench saves that are not undone: `[dict(id, at, action, label, quantity, undo_available)]`."""
    rows = []
    for e in db.execute(f'''SELECT e.id,e.at,e.field,e.new_value FROM main.event e WHERE e.entity_kind=? AND NOT {undoing.undone_sql('e')}
                            ORDER BY e.id DESC LIMIT ?''', (ENTITY, limit)):
        context = next((t['rows'][0] for t in json.loads(e['new_value']) if t['table'] == 'context' and t['rows']), {})
        rows.append(dict(id=e['id'], at=e['at'], action=e['field'], item_id=context.get('item_id'), color_id=context.get('color_id'),
                         quantity=context.get('quantity'), undo_available=True))
    labels = items.labels(db, {(r['item_id'], r['color_id']) for r in rows if r['item_id'] is not None})
    for r in rows:
        label = labels.get((r['item_id'], r['color_id']))
        r['label'] = label.text if label else ''
    return rows
