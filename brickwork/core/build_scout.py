"""Build Scout (#9): which catalogue sets can be built, or nearly built, from the loose stock. Read-only except `build_set` and `wish_set`.

It sits on the set-scoring engine (`core/set_scoring.py`, ADR 0026) but answers a different question. The engine ranks by rarity-weighted
evidence; Build Scout ranks by how much of a set the stock covers, and its numbers are the buildability ones (ADR 0027):

* **Parts** are a set's own part lines (sub-sets expanded, spares left out). A minifigure's components are not part lines of the set: the
  figure is one whole line, counted apart. So `parts_available = sum over the set's part lines of min(have, need)`, `percent = parts_available /
  parts_total`, `missing = parts_total - parts_available` (pieces) and `missing_lines` (lines not covered in full).
* **Figures** are the set's whole minifigures, `figures_available = sum of min(have, need)` over its figure lines. A loose whole figure counts;
  loose parts of a figure never do.
* **Swaps** (another colour, an alternate mould) are the engine's, listed apart and never in a number.
* **Cost** is the missing lines (parts and figures) priced from `price_current` where a price is known, in the one currency most of them are
  priced in, with the number of missing lines left unpriced. It is worked out for the page shown, never for the whole catalogue.

The stock is one eligibility rule (`stock_rows`) shared by the ranking and by Build it, so the pieces on the screen are the pieces that move:
live loose parts and minifigures, with `workbench.available` (damaged rows give nothing unless asked for, a figure with defective parts none, a
row's missing and damaged counts are taken off). A source selection is the union of the stock kept in no lot or storage (`loose`), the chosen
lots and the chosen storages with the storages inside them; none chosen means all loose stock.

Two indexes are built from the engine's loader with the engine's `build_index`, once per catalogue build and process: the parts one (the sets'
own parts only) and the figures one (whole figures only), so sub-sets are expanded by the same code as everywhere."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json
import threading
import uuid

from ..store4 import found_copy
from ..store4.audit import OPERATION_KEY
from . import add, collection, errors, gaps, set_scoring, workbench
from . import undo as undoing
from .admin import origin
from .transaction import transaction

DEFAULT_MIN_PERCENT = 60
MAX_LIMIT = 100
MAX_LINES = 500                 # missing lines a set's detail lists
WISH_NOTE = 'Buildable from stock'
MISSING_LINES_SHOWN = 12


# ---------- the stock ----------

def stock_rows(db, *, lots=(), storages=(), loose=False, damaged=False):
    """The live loose rows the chosen sources hold, each `dict(id, item_id, color_id, kind, have, lot_id, storage_id)`, `have` being what can be given
    (`workbench.available`). With no source chosen: all loose stock. A row in a chosen lot and a chosen storage is one row."""
    lots, storages = list(dict.fromkeys(lots)), list(dict.fromkeys(storages))
    where, params = '', []
    if lots or storages or loose:
        parts = []
        if loose:
            parts.append('(s.lot_id IS NULL AND s.storage_id IS NULL)')
        if lots:
            parts.append('s.lot_id IN (SELECT value FROM json_each(?))')
            params.append(json.dumps(lots))
        if storages:
            parts.append('''s.storage_id IN (WITH RECURSIVE t(id) AS (SELECT value FROM json_each(?) UNION
                              SELECT c.id FROM main.storage c JOIN t ON c.parent_id=t.id WHERE c.archived_at IS NULL) SELECT id FROM t)''')
            params.append(json.dumps(storages))
        where = ' AND (' + ' OR '.join(parts) + ')'
    rows = [dict(r) for r in db.execute(f"""SELECT s.* FROM main.stock s WHERE s.archived_at IS NULL AND s.quantity>0 AND s.kind IN ('part','minifigure') {where}
                                            ORDER BY s.id""", params)]
    defective = workbench.defective_figures(db)
    found = []
    for row in rows:
        have = workbench.available(db, dict(row, condition='used') if damaged and row['condition'] == 'damaged' else row, defective=defective)
        if have:
            found.append(dict(id=row['id'], item_id=row['item_id'], color_id=None if row['kind'] == 'minifigure' else row['color_id'], kind=row['kind'],
                              have=have, lot_id=row['lot_id'], storage_id=row['storage_id']))
    return found


def pile_of(rows):
    """`{line key: quantity}` of the rows (a figure is a line with colour 0, as in the engine)."""
    lines = defaultdict(int)
    for row in rows:
        lines[set_scoring.key_of(row['item_id'], row['color_id'])] += row['have']
    return dict(lines)


def sources_text(db, lots=(), storages=(), loose=False):
    """The words of a selection: 'Loose stock · 2 lots · 3 storages'."""
    if not (lots or storages or loose):
        return 'All loose stock'
    parts = ['Loose stock'] if loose else []
    if lots:
        parts.append(f'{len(lots)} lot{"" if len(lots) == 1 else "s"}')
    if storages:
        parts.append(f'{len(storages)} storage{"" if len(storages) == 1 else "s"}')
    return ' · '.join(parts)


# ---------- the indexes ----------

class Scout:
    """What one catalogue build gives: the parts index, the figures index and the sets' year and theme."""

    def __init__(self, db):
        rows = set_scoring.load_rows(db)
        self.key = rows.key
        sets = list(rows.sets)
        self.parts = set_scoring.build_index(set_scoring.Rows(sets, (), rows.subsets, (), rows.relations, rows.key))
        self.figures = set_scoring.build_index(set_scoring.Rows([(s, []) for s, _ in sets], rows.figures, rows.subsets, (), (), rows.key))
        self.nested = {parent for parent, _, _ in rows.subsets}
        cur = db.cursor()
        cur.row_factory = None
        self.meta = {r[0]: (r[1], r[2]) for r in cur.execute("SELECT id, year, theme_id FROM catalogue.item WHERE kind='set'")}
        self.themes = {r[0]: (r[1], r[2]) for r in cur.execute('SELECT id, name, parent_id FROM catalogue.theme')}
        self.children = defaultdict(list)
        for theme, (_, parent) in self.themes.items():
            self.children[parent].append(theme)

    def theme_ids(self, wanted):
        """The theme ids a theme filter means (an id, or a name in any case) with every sub-theme, or `ValueError`."""
        text = str(wanted).strip()
        start = [int(text)] if text.isdigit() and int(text) in self.themes else [t for t, (n, _) in self.themes.items() if n.casefold() == text.casefold()]
        if not start:
            raise ValueError(f'No such theme: {text}')
        found, todo = set(), list(start)
        while todo:
            theme = todo.pop()
            if theme not in found:
                found.add(theme)
                todo += self.children.get(theme, ())
        return found

    def theme_name(self, theme_id):
        return (self.themes.get(theme_id) or (None,))[0]


_SCOUTS = {}
_LOCK = threading.Lock()


def scout_for(db):
    """The `Scout` of the attached catalogue build (built once per build and process; the engine's key says when it is a new build)."""
    key = set_scoring.build_key(db)
    with _LOCK:
        held = _SCOUTS.get(key[0])
        if held is not None and held.key == key:
            return held
        _SCOUTS[key[0]] = held = Scout(db)
        return held


# ---------- the ranking ----------

def covered_by(index, lines):
    """`{position: pieces covered}` and `{position: lines covered in full}` of a pile against an index: the engine's min(have, need)."""
    covered, complete = defaultdict(int), defaultdict(int)
    for key, have in lines.items():
        found = index.posting.get(key)
        if found is None:
            continue
        for position, need in zip(*found):
            if have >= need:
                covered[position] += need
                complete[position] += 1
            else:
                covered[position] += have
    return covered, complete


def _whole(value, name, low=0):
    if value is None or value == '':
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} is a whole number') from None
    if value < low:
        raise ValueError(f'{name} is {low} or more')
    return value


def ranked(scout, pile, *, min_percent=DEFAULT_MIN_PERCENT, max_missing=None, theme=None, year_from=None, year_to=None, size_from=None, size_to=None):
    """Every set that shares a part line with the pile and passes the filters, best first: `[(position, covered, complete lines)]` and the count of sets
    that share a line. Sorted by percent available, then fewest missing pieces, then set id."""
    index = scout.parts
    min_percent = 0 if min_percent is None else min_percent
    if not 0 <= min_percent <= 100:
        raise ValueError('minimum is 0 to 100')
    themes = scout.theme_ids(theme) if theme not in (None, '') else None
    covered, complete = covered_by(index, pile)
    total, item, found = index.set_quantity, index.set_item, []
    for position, pieces in covered.items():
        size = total[position]
        if pieces * 100 < min_percent * size:
            continue
        if max_missing is not None and size - pieces > max_missing:
            continue
        if size_from is not None and size < size_from or size_to is not None and size > size_to:
            continue
        year, theme_id = scout.meta.get(item[position], (None, None))
        if (year_from is not None or year_to is not None) and (year is None or (year_from is not None and year < year_from) or (year_to is not None and year > year_to)):
            continue
        if themes is not None and theme_id not in themes:
            continue
        found.append((-pieces / size, size - pieces, item[position], position, pieces, complete[position]))
    found.sort(key=lambda r: r[:3])
    return [r[3:] for r in found], len(covered)


def figures_of(scout, pile):
    """`{set item id: (figures covered, figures needed)}` for the sets that have figures."""
    index = scout.figures
    covered, _ = covered_by(index, {k: v for k, v in pile.items() if k & ((1 << 32) - 1) == 0})
    return {index.set_item[p]: (covered.get(p, 0), index.set_quantity[p]) for p in range(index.total)}, covered


def _filters(args):
    return dict(min_percent=_whole(args.get('min_percent', DEFAULT_MIN_PERCENT), 'min_percent'), max_missing=_whole(args.get('max_missing'), 'max_missing'),
                theme=args.get('theme') or None, year_from=_whole(args.get('year_from'), 'year_from'), year_to=_whole(args.get('year_to'), 'year_to'),
                size_from=_whole(args.get('size_from'), 'size_from'), size_to=_whole(args.get('size_to'), 'size_to'))


def scout(db, *, lots=(), storages=(), loose=False, damaged=False, limit=20, offset=0, detail=0, **filters):
    """The Build Scout answer: `dict(catalogue, source, input, total, limit, offset, results)`; `results` are the page's sets, each
    `dict(rank, set_item_id, year, theme, parts_available, parts_total, percent, missing_parts, missing_lines, figures_available, figures_required, cost, ...)`.
    With `detail` above 0 each set lists that many of its biggest missing lines (`gaps`), its missing figures (`figure_gaps`), its cost and its swaps. Read-only; `ValueError` for a refused argument."""
    if not 1 <= limit <= MAX_LIMIT or offset < 0 or not 0 <= detail <= MAX_LINES:
        raise ValueError(f'limit is 1 to {MAX_LIMIT}, offset from 0, detail 0 to {MAX_LINES}')
    options = _filters(filters)
    unknown = set(filters) - set(options)
    if unknown:
        raise ValueError('Unknown filter ' + ', '.join(sorted(unknown)))
    chosen = scout_for(db)
    rows = stock_rows(db, lots=lots, storages=storages, loose=loose, damaged=damaged)
    pile = pile_of(rows)
    ordered, sharing = ranked(chosen, pile, **options)
    figures, _ = figures_of(chosen, pile)
    page = ordered[offset:offset + limit]
    shown = _present(db, chosen, pile, page, offset, figures, detail)
    return dict(catalogue=dict(chosen.parts.describe(), nested=len(chosen.nested)),
                source=dict(lots=list(lots), storages=list(storages), loose=bool(loose), damaged=bool(damaged), text=sources_text(db, lots, storages, loose)),
                input=dict(lines=len(pile), pieces=sum(v for k, v in pile.items() if k & ((1 << 32) - 1)), figures=sum(v for k, v in pile.items() if not k & ((1 << 32) - 1))),
                filters=options, sharing=sharing, total=len(ordered), limit=limit, offset=offset, results=shown)


def _present(db, chosen, pile, page, offset, figures, detail):
    index = chosen.parts
    prices = _prices(db, chosen, [p for p, _, _ in page], pile) if detail else None
    out = []
    for n, (position, pieces, complete) in enumerate(page):
        item = index.set_item[position]
        size = index.set_quantity[position]
        have_f, need_f = figures.get(item, (0, 0))
        year, theme_id = chosen.meta.get(item, (None, None))
        row = dict(rank=offset + n + 1, set_item_id=item, year=year, theme=chosen.theme_name(theme_id), theme_id=theme_id,
                   parts_available=pieces, parts_total=size, percent=round(100 * pieces / size, 1), missing_parts=size - pieces,
                   missing_lines=index.set_lines[position] - complete, figures_available=have_f, figures_required=need_f, missing_figures=need_f - have_f,
                   nested=item in chosen.nested)
        if detail:
            row.update(set_detail_in(db, chosen, position, pile, lines_shown=detail, prices=prices))
        out.append(row)
    return out


# ---------- one set ----------

def missing_lines(chosen, position, pile):
    """The set's part lines the pile does not cover in full: `[(key, need, have, missing)]`, the biggest gap first."""
    index = chosen.parts
    lines = []
    for key, need in zip(index.set_keys[position], index.set_needs[position]):
        have = min(pile.get(key, 0), need)
        if have < need:
            lines.append((key, need, have, need - have))
    lines.sort(key=lambda r: (-r[3], r[0]))
    return lines


def figure_lines(chosen, item, pile):
    """The set's whole-figure lines as `[(key, need, have, missing)]` (all of them, covered or not)."""
    index = chosen.figures
    position = index.position.get(item)
    if position is None:
        return []
    return [(k, need, min(pile.get(k, 0), need), need - min(pile.get(k, 0), need)) for k, need in zip(index.set_keys[position], index.set_needs[position])]


def _prices(db, chosen, positions, pile):
    """`price_map` over the missing lines (parts and figures) of the page's sets: one lookup for the page (see the module doc)."""
    pairs = set()
    for position in positions:
        for key, _, _, _ in missing_lines(chosen, position, pile):
            pairs.add(set_scoring.unkey(key))
        for key, _, _, _ in figure_lines_missing(chosen, chosen.parts.set_item[position], pile):
            pairs.add(set_scoring.unkey(key))
    return price_map(db, pairs)


def price_map(db, pairs):
    """`dict(prices={(item, colour or 0): Decimal}, currency)` from `price_current` for the (item id, colour id or None) pairs: the used price before
    the new one, a sold average before a stock listing, the newest observation last; a price in another currency than most are is left out."""
    pairs = list(pairs)
    if not pairs:
        return dict(prices={}, currency=None)
    wanted = json.dumps([[i, c or 0] for i, c in pairs])
    best = {}
    for row in db.execute("""SELECT p.item_id, coalesce(p.color_id,0) AS color_id, p.condition, p.guide, o.price, o.currency, o.id
        FROM price_current p JOIN price_observation o ON o.id=p.observation_id
        WHERE o.voided_at IS NULL AND coalesce(o.error,'')='' AND o.price IS NOT NULL AND coalesce(o.slot,'')!='boxed' AND p.guide IN ('sold','stock')
        AND EXISTS(SELECT 1 FROM json_each(?) j WHERE json_extract(j.value,'$[0]')=p.item_id AND json_extract(j.value,'$[1]')=coalesce(p.color_id,0))""", (wanted,)):
        try:
            value = Decimal(row['price'])
        except (InvalidOperation, TypeError):
            continue
        rank = (row['condition'] != 'used', row['guide'] != 'sold', -row['id'])
        key = (row['item_id'], row['color_id'])
        if key not in best or rank < best[key][0]:
            best[key] = (rank, value, row['currency'] or '')
    if not best:
        return dict(prices={}, currency=None)
    counts = defaultdict(int)
    for _, _, currency in best.values():
        counts[currency] += 1
    currency = max(counts, key=lambda c: (counts[c], c))
    return dict(prices={k: v for k, (_, v, c) in best.items() if c == currency}, currency=currency or None)


def cost_of(missing, prices):
    """`dict(amount, currency, priced_lines, unpriced_lines)` for `[(key, quantity)]` missing lines against `price_map`'s answer; `amount` is None when
    no line is priced."""
    amount, priced, unpriced = Decimal(0), 0, 0
    for key, quantity in missing:
        item, colour = set_scoring.unkey(key)
        price = prices['prices'].get((item, colour or 0))
        if price is None:
            unpriced += 1
        else:
            amount += price * quantity
            priced += 1
    return dict(amount=str(amount.quantize(Decimal('0.01'))) if priced else None, currency=prices['currency'] if priced else None,
                priced_lines=priced, unpriced_lines=unpriced)


def set_detail_in(db, chosen, position, pile, *, lines_shown=MAX_LINES, prices=None):
    """What a set adds to a row: its biggest missing part lines, its missing figure lines, the cost to complete and its swaps."""
    index = chosen.parts
    item = index.set_item[position]
    missing = missing_lines(chosen, position, pile)
    figs = figure_lines_missing(chosen, item, pile)
    prices = prices if prices is not None else price_map(db, [set_scoring.unkey(k) for k, *_ in missing + figs])
    swaps = set_scoring._swaps(index, position, pile, dict(zip(index.set_keys[position], index.set_needs[position])), set_scoring.by_item_of(pile))
    return dict(gaps=[dict(item_id=set_scoring.unkey(k)[0], color_id=set_scoring.unkey(k)[1], need=need, have=have, missing=gap) for k, need, have, gap in missing[:lines_shown]],
                figure_gaps=[dict(item_id=set_scoring.unkey(k)[0], need=need, have=have, missing=gap) for k, need, have, gap in figs],
                cost=cost_of([(k, gap) for k, _, _, gap in missing + figs], prices), swaps=swaps)


def set_detail(db, set_item_id, *, lots=(), storages=(), loose=False, damaged=False):
    """One set's full Build Scout numbers for the chosen stock (whether or not it passes a filter), or `ValueError` for a set that is no candidate."""
    chosen = scout_for(db)
    rows = stock_rows(db, lots=lots, storages=storages, loose=loose, damaged=damaged)
    pile = pile_of(rows)
    position = chosen.parts.position.get(int(set_item_id))
    if position is None:
        raise ValueError('This set has no part list to compare')
    index = chosen.parts
    covered, complete = covered_by(index, pile)
    pieces = covered.get(position, 0)
    size = index.set_quantity[position]
    figures, _ = figures_of(chosen, pile)
    have_f, need_f = figures.get(int(set_item_id), (0, 0))
    year, theme_id = chosen.meta.get(int(set_item_id), (None, None))
    return dict(set_item_id=int(set_item_id), year=year, theme=chosen.theme_name(theme_id), parts_available=pieces, parts_total=size,
                percent=round(100 * pieces / size, 1), missing_parts=size - pieces, missing_lines=index.set_lines[position] - complete.get(position, 0),
                figures_available=have_f, figures_required=need_f, missing_figures=need_f - have_f, nested=int(set_item_id) in chosen.nested,
                input=dict(pieces=sum(v for k, v in pile.items() if k & ((1 << 32) - 1))),
                **set_detail_in(db, chosen, position, pile))


def missing_export(db, set_item_id, **sources):
    """The BrickLink wanted-list XML of a set's missing parts and figures for the chosen stock, by the exporter the copies use (`gaps.export_lines`):
    `dict(xml, lines, skipped)`."""
    chosen = scout_for(db)
    pile = pile_of(stock_rows(db, **sources))
    position = chosen.parts.position.get(int(set_item_id))
    if position is None:
        raise ValueError('This set has no part list to compare')
    total = defaultdict(int)
    for key, _, _, gap in missing_lines(chosen, position, pile) + figure_lines_missing(chosen, int(set_item_id), pile):
        item, colour = set_scoring.unkey(key)
        total[item, colour, 'N'] += gap
    if not total:
        raise ValueError('Nothing is missing of this set')
    return gaps.export_lines(db, total)


def figure_lines_missing(chosen, item, pile):
    return [r for r in figure_lines(chosen, item, pile) if r[3]]


# ---------- the actions ----------

def wish_set(db, set_item_id):
    """Put the set on the default wishlist, marked `WISH_NOTE` in the wish's note (by the Add flow, so the receipt is its own and Undo is Add's).
    Returns `dict(event_id, wish_id, already)`; a set already wished is `already` and nothing is written."""
    via, actor = origin()
    row = {'item_id': int(set_item_id), 'color_id': None, 'quantity': 1, 'condition': 'any', 'note': WISH_NOTE, 'max_price': None}
    if (add.lookup(db, row['item_id']) or {}).get('kind') != 'set':
        raise ValueError('Only a set can be added to the wishlist from Build Scout')
    proposal = add.resolve(db, [row], 'wishlist', list_id='default')
    if proposal['unresolved']:
        raise ValueError(proposal['unresolved'][0]['reason'])
    if proposal['items'][0]['wished']:
        return dict(event_id=None, wish_id=None, already=True)
    rows = add.validate_edits(db, proposal['items'], [dict(quantity=1, decision='another', note=WISH_NOTE, list_id='default')])
    made = add.confirm(db, rows, batch=uuid.uuid4().hex, via=via, actor=actor)
    if not made:
        raise ValueError('Nothing was added')
    return dict(event_id=made[0].get('event_id'), wish_id=made[0]['wish']['id'], already=False)


def plan_takes(db, set_item_id, rows):
    """How a Build it takes from `rows` (`stock_rows`): `[(stock id, amount)]` so that every part line gets min(have, need) and every figure line
    min(have, need), the largest usable row first and then the lowest id (the Matchmaker's order), and the totals taken."""
    chosen = scout_for(db)
    position = chosen.parts.position.get(int(set_item_id))
    if position is None:
        raise ValueError('This set has no part list to build from')
    if int(set_item_id) in chosen.nested:
        raise ValueError('This set is made of other sets · Build it does not handle those yet')
    by_key = defaultdict(list)
    for row in rows:
        by_key[set_scoring.key_of(row['item_id'], row['color_id'])].append(dict(row))
    needs = list(zip(chosen.parts.set_keys[position], chosen.parts.set_needs[position]))
    fig = chosen.figures.position.get(int(set_item_id))
    if fig is not None:
        needs += list(zip(chosen.figures.set_keys[fig], chosen.figures.set_needs[fig]))
    takes, pieces, figures = [], 0, 0
    for key, need in needs:
        left = need
        for row in sorted(by_key.get(key, ()), key=lambda r: (-min(r['have'], need), r['id'])):
            step = min(left, row['have'])
            if step:
                takes.append((row['id'], step))
                row['have'] -= step
                left -= step
            if not left:
                break
        if key & ((1 << 32) - 1):
            pieces += need - left
        else:
            figures += need - left
    return takes, dict(pieces=pieces, figures=figures)


def build_set(db, set_item_id, *, lots=(), storages=(), loose=False, damaged=False, note='Built from loose stock'):
    """Build it: one copy of the set, the matching parts and whole figures moved out of the chosen stock into it, the rest recorded as missing on
    the copy, as one transaction and one undoable event (`found_copy.make_copy_in`). Returns `dict(event_id, copy_id, pieces, figures, missing_parts,
    missing_figures)`; a `ValueError` is a refusal that wrote nothing (a set with no part list or made of sets, nothing in stock for it)."""
    via, actor = origin()
    with transaction(db):
        rows = stock_rows(db, lots=lots, storages=storages, loose=loose, damaged=damaged)
        takes, totals = plan_takes(db, set_item_id, rows)
        if not takes:
            raise ValueError('The chosen stock holds nothing this set needs')
        made = found_copy.make_copy_in(db, int(set_item_id), takes, via=via, actor=actor, operation_key=OPERATION_KEY.get(), note=note)
    return made


def _undo_build(db, event, via, actor):
    return found_copy.undo_make_copy_in(db, event['id'], via=via, actor=actor, operation_key=OPERATION_KEY.get())


undoing.register('copy', found_copy.FIELD, _undo_build)
