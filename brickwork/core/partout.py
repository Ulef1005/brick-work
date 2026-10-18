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

from . import collection, planning
from .sources.base import now

COVERAGE = 0.9  # share of lines that need a price before a part-out total is shown


def values(db, copy_ids):
    copy_ids = sorted(set(copy_ids))
    if not copy_ids:
        return {}
    packed = json.dumps(copy_ids)
    lines = defaultdict(list)
    for r in db.execute('''SELECT copy_id,item_type,item_no,color_id,sum(coalesce(quantity,0)-coalesce(missing,0)) present
            FROM copy_parts WHERE copy_id IN (SELECT value FROM json_each(?)) AND coalesce(spare,0)=0 AND parent_minifig IS NULL
            GROUP BY 1,2,3,4''', (packed,)):
        if r['present'] > 0:
            lines[r['copy_id']].append((r['item_type'], r['item_no'], r['color_id'], r['present']))
    for r in db.execute('''SELECT copy_id,item_type,minifig_no,sum(coalesce(quantity,0)-coalesce(missing,0)) present
            FROM copy_minifigs WHERE copy_id IN (SELECT value FROM json_each(?)) GROUP BY 1,2,3''', (packed,)):
        if r['present'] > 0:
            lines[r['copy_id']].append((r['item_type'], r['minifig_no'], None, r['present']))
    scope = {(t, n, c) for rows in lines.values() for t, n, c, _ in rows}
    market = collection.prices(db, scope=scope) if scope else {}
    config, stamp = planning.configuration(db), now()
    quotes = {key: planning.quote(market.get(key, []), 'U', config, stamp) for key in scope}
    result = {}
    for copy_id in copy_ids:
        total, priced, missing = Decimal(0), 0, []
        for t, n, c, present in lines.get(copy_id, []):
            q = quotes.get((t, n, c))
            if q is None:
                missing.append(dict(item_type=t, item_no=n, color_id=c))
                continue
            total += Decimal(str(q['price'])) * present
            priced += 1
        count = len(lines.get(copy_id, []))
        enough = bool(count) and priced >= COVERAGE * count
        items = sorted({(m['item_type'], m['item_no']) for m in missing})
        result[copy_id] = dict(value=str(total.quantize(Decimal('0.01'))) if enough else None, currency=config['bricklink_currency'],
                               lines=count, priced=priced, enough=enough, unpriced=missing[:50], unpriced_count=len(missing),
                               unpriced_items=[list(key) for key in items[:200]])
    return result


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
