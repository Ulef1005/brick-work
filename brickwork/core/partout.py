"""Part-out value (#38): what a copy's present parts and figures are worth one by one.

Sum over the copy's required parts (spares excluded, ADR 0011; figure components counted through
their figure) of the used quote per part and colour, plus each present minifigure as a whole (usual
BrickLink practice), using the same usable-quote rule as Complete sets (fresh, in the BrickLink
currency and region). Coverage says how many lines had a price; unpriced lines are listed so a
price refresh can be queued. Batched: three queries for any number of copies.

A total is given only when at least COVERAGE of the lines have a price: summing the few priced lines of a
set whose other parts have none yet showed a meaninglessly small value (four of 54 lines gave 0.18).
"""
from collections import defaultdict
from decimal import Decimal
import json

from . import collection, items, planning
from .sources.base import now

COVERAGE = 0.9  # share of lines that need a price before a part-out total is shown


def values(db, copy_ids):
    """`{copy id: dict(value, currency, lines, priced, enough, unpriced, unpriced_count, unpriced_items)}` for live copies.

    Lines are the copy's live set lines (a retired line is no line, spares and a figure's own parts excluded) and its live figure lines,
    each as (item id, colour id): the quantity present is the quantity less the missing. `unpriced` names up to 50 lines
    (`dict(item_id, color_id)`); `unpriced_items` is the item ids (up to 200) a price refresh could fetch, an unidentified item left out."""
    copy_ids = sorted(set(copy_ids))
    if not copy_ids:
        return {}
    packed = json.dumps(copy_ids)
    lines = defaultdict(list)
    for r in db.execute('''SELECT copy_id,item_id,color_id,sum(quantity-missing) present FROM copy_part
            WHERE copy_id IN (SELECT value FROM json_each(?)) AND is_spare=0 AND copy_figure_id IS NULL AND retired_at IS NULL
            GROUP BY 1,2,3''', (packed,)):
        if r['present'] > 0:
            lines[r['copy_id']].append((r['item_id'], r['color_id'], r['present']))
    for r in db.execute('''SELECT copy_id,item_id,sum(quantity-missing) present FROM copy_figure
            WHERE copy_id IN (SELECT value FROM json_each(?)) AND retired_at IS NULL GROUP BY 1,2''', (packed,)):
        if r['present'] > 0:
            lines[r['copy_id']].append((r['item_id'], None, r['present']))
    scope = {(i, c) for rows in lines.values() for i, c, _ in rows}
    market = collection.prices(db, pairs=scope) if scope else {}
    config, stamp = planning.configuration(db), now()
    quotes = {key: planning.quote(market.get(key, []), 'used', config, stamp) for key in scope}
    result = {}
    for copy_id in copy_ids:
        total, priced, missing = Decimal(0), 0, []
        for item_id, colour, present in lines.get(copy_id, []):
            q = quotes.get((item_id, colour))
            if q is None:
                missing.append(dict(item_id=item_id, color_id=colour))
                continue
            total += Decimal(str(q['price'])) * present
            priced += 1
        count = len(lines.get(copy_id, []))
        enough = bool(count) and priced >= COVERAGE * count
        wanted = sorted({m['item_id'] for m in missing})
        result[copy_id] = dict(value=str(total.quantize(Decimal('0.01'))) if enough else None, currency=config['bricklink_currency'],
                               lines=count, priced=priced, enough=enough, unpriced=missing[:50], unpriced_count=len(missing),
                               unpriced_items=_refreshable(db, wanted)[:200])
    return result


def _refreshable(db, item_ids):
    """The item ids of `item_ids` a price refresh can name for BrickLink: an unidentified item has no number to fetch by."""
    if not item_ids:
        return []
    labels = items.labels(db, {(i, None) for i in item_ids})
    return [i for i in item_ids if (i, None) in labels and not labels[i, None].unidentified]


def compare(copy, partout, config=None):
    """Complete, as-is and parted-out side by side for one copy record carrying complete_quote/current_value."""
    from decimal import Decimal as D
    if not partout or not partout.get('lines'):
        return None
    out = dict(partout=partout.get('value'), currency=partout['currency'], lines=partout['lines'], priced=partout['priced'],
               unpriced_items=partout.get('unpriced_items', []), hint=None)
    if out['partout'] is None:
        # Not enough prices for a total: the card says so and offers to fetch the missing ones.
        out['complete'] = out['as_is'] = None
        return out
    complete = (copy.get('complete_quote') or {}).get('price')
    out['complete'] = str(D(str(complete)).quantize(D('0.01'))) if complete is not None else None
    as_is = copy.get('current_value')
    out['as_is'] = str(D(str(as_is)).quantize(D('0.01'))) if as_is is not None else None
    if out['as_is'] is not None:
        gain = D(out['partout']) - D(out['as_is'])
        # A hint only when parting out is clearly worth more: 10 % and at least 5 in the currency.
        out['hint'] = str(gain.quantize(D('0.01'))) if gain >= max(D(5), D(out['as_is']) / 10) else None
    return out
