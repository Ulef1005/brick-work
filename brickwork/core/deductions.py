"""What a copy's missing parts and figures take off its asking price or worth (#53), priced line by line.

A copy is **checked** when it has the status flag `Set is checked` or is sealed (a sealed set has nothing to check). For a checked copy the
missing lines are priced one by one; for any other copy nothing is known about what is missing, and the flat incomplete-set discount of the
settings stays the fallback (`valuation`).

A line is a set part (item and colour, spares and a figure's own parts excluded, a retired line none) with `missing` above 0, or a figure with
`missing` above 0. Its price is the used quote Complete sets prices a repair with (`planning.quote`: fresh, in the BrickLink currency and region);
no such quote makes the line **needs evidence**: it stays in the list and is left out of the sum. A damaged line is not deducted.

The Sell card (`selling`) and the Value card's Worth now (`valuation`) both read this module, so the two cards cannot disagree about a checked copy.
Batched: the flags, the lines and the quotes are three reads for any number of copies.
"""
from decimal import Decimal, ROUND_HALF_UP
import json

from . import collection, planning
from . import currency as fx

CHECKED = 'Set is checked'
CENT = Decimal('0.01')


def _cents(amount):
    return amount.quantize(CENT, ROUND_HALF_UP)


def checked(db, copies):
    """The ids of the checked copies among `copies` (rows carrying `id` and `completeness`): flagged `Set is checked`, or sealed."""
    ids = [c['id'] for c in copies]
    if not ids:
        return set()
    flagged = {r[0] for r in db.execute("""SELECT x.copy_id FROM copy_flag x JOIN flag f ON f.id=x.flag_id
        WHERE f.name=? AND f.kind='status' AND f.archived_at IS NULL AND x.copy_id IN (SELECT value FROM json_each(?))""", (CHECKED, json.dumps(ids)))}
    return flagged | {c['id'] for c in copies if c.get('completeness') == 'sealed'}


def lines(db, copy_ids, stamp):
    """`{copy id: {'parts': [line], 'figures': [line]}}`, each line `dict(group, item_id, color_id, missing, unit, total, currency)`: `unit` and
    `total` (the unit price times `missing`) are Decimals in `currency`, or None when the line needs evidence. Parts first, in item order."""
    ids = sorted(set(copy_ids))
    found = {i: dict(parts=[], figures=[]) for i in ids}
    if not ids:
        return found
    packed = json.dumps(ids)
    for r in db.execute('''SELECT copy_id,item_id,color_id,sum(missing) missing FROM copy_part
            WHERE copy_id IN (SELECT value FROM json_each(?)) AND is_spare=0 AND copy_figure_id IS NULL AND retired_at IS NULL
            GROUP BY 1,2,3 HAVING sum(missing)>0 ORDER BY 1,2,3''', (packed,)):
        found[r['copy_id']]['parts'].append(dict(group='part', item_id=r['item_id'], color_id=r['color_id'], missing=r['missing']))
    for r in db.execute('''SELECT copy_id,item_id,sum(missing) missing FROM copy_figure
            WHERE copy_id IN (SELECT value FROM json_each(?)) AND retired_at IS NULL GROUP BY 1,2 HAVING sum(missing)>0 ORDER BY 1,2''', (packed,)):
        found[r['copy_id']]['figures'].append(dict(group='figure', item_id=r['item_id'], color_id=None, missing=r['missing']))
    scope = {(l['item_id'], l['color_id']) for c in found.values() for l in c['parts'] + c['figures']}
    market = collection.prices(db, pairs=scope) if scope else {}
    config = planning.configuration(db)
    quotes = {key: planning.quote(market.get(key, []), 'used', config, stamp) for key in scope}
    for c in found.values():
        for line in c['parts'] + c['figures']:
            q = quotes.get((line['item_id'], line['color_id']))
            unit = Decimal(str(q['price'])) if q else None
            line.update(unit=unit, total=unit * line['missing'] if q else None, currency=q['currency'] if q else None)
    return found


def shown(copy_lines, display, table):
    """The copy's lines with `shown` added to each priced one: its total as the display currency, in whole cents. Returns the same dict, or
    None when a line is in a currency with no rate (never two currencies in one figure)."""
    for line in copy_lines['parts'] + copy_lines['figures']:
        line['shown'] = None
        if line['total'] is None:
            continue
        converted = fx.convert(line['total'], line['currency'], display, table)
        if converted is None:
            return None
        line['shown'] = _cents(converted['amount'])
    return copy_lines


def totals(copy_lines):
    """The sums of a copy's `shown` lines, in the display currency: `parts` and `figures` (what they take off), `pieces` (missing parts counted
    singly), `figure_count`, `lines` (part and figure lines), `priced`, and `unpriced` (the lines that need evidence, parts first)."""
    parts, figures = copy_lines['parts'], copy_lines['figures']
    every = parts + figures
    return dict(parts=sum((l['shown'] for l in parts if l['shown'] is not None), Decimal(0)),
                figures=sum((l['shown'] for l in figures if l['shown'] is not None), Decimal(0)),
                pieces=sum(l['missing'] for l in parts), figure_count=sum(l['missing'] for l in figures), lines=len(every),
                priced=sum(l['shown'] is not None for l in every), unpriced=[l for l in every if l['shown'] is None])


def net(average, sums):
    """The asking price before the floor: the average (display cents) less the two deductions, never under 0.00."""
    return max(average - sums['parts'] - sums['figures'], Decimal(0))
