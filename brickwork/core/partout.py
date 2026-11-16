"""Part-out value (#38): what a copy's present parts and figures are worth one by one.

Sum over the copy's required parts (spares excluded, ADR 0011; figure components counted through
their figure) of the used quote per part and colour, plus each present minifigure as a whole (usual
BrickLink practice), in one currency and the configured region. Prefer the configured currency when coverage is sufficient.
Old cached quotes remain visible with their age mark. Coverage says how many lines had a price; unpriced lines are listed so a
price refresh can be queued. Batched: three queries for any number of copies.

A total is given only when at least COVERAGE of the lines have a price: summing the few priced lines of a
set whose other parts have none yet showed a meaninglessly small value (four of 54 lines gave 0.18).
"""
from collections import defaultdict
from decimal import Decimal
import json

from . import collection, items, planning
from .sources.base import now

MARGIN = Decimal('0.10')
MINIMUM_GAIN = Decimal('5.00')


def advantage(value, alternative):
    """Whether a value beats its alternative by the shared meaningful margin."""
    return value - alternative >= max(MINIMUM_GAIN, abs(alternative) * MARGIN)


COVERAGE = 0.9  # share of lines that need a price before a part-out total is shown


def values(db, copy_ids):
    """`{copy id: dict(value, currency, lines, priced, enough, oldest_observed, stale, unpriced, unpriced_count, unpriced_items)}` for live copies.

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
    currencies = [config['bricklink_currency']] + sorted({q['currency'] for rows in market.values() for q in rows
                                                        if q.get('currency') and q['currency'] != config['bricklink_currency']})
    quotes = {currency: {key: planning.quote(market.get(key, []), 'used', dict(config, bricklink_currency=currency), stamp,
                                             allow_old=True) for key in scope} for currency in currencies}
    result, unpriced = {}, {}
    for copy_id in copy_ids:
        rows = lines.get(copy_id, [])
        choices = [_summarize(rows, quotes[currency], currency) for currency in currencies]
        chosen = next((choice for choice in choices if choice['enough']), choices[0])
        result[copy_id] = chosen
        selected = quotes[chosen['currency']]
        # Cached stale lines still count and remain eligible for refresh.
        unpriced[copy_id] = sorted(chosen.pop('_unpriced_items') |
                                   {i for i, c, _ in rows if selected.get((i, c)) and selected[i, c].get('stale')})
    refreshable = set(_refreshable(db, sorted({i for ids in unpriced.values() for i in ids})))      # one read for every copy, not one per copy
    for copy_id, wanted in unpriced.items():
        result[copy_id]['unpriced_items'] = [i for i in wanted if i in refreshable][:200]
    return result


def _summarize(rows, quotes, currency):
    """One currency per total; the coverage rule is shared by every presentation."""
    total, used, missing = Decimal(0), [], []
    for item_id, colour, present in rows:
        q = quotes.get((item_id, colour))
        if q is None:
            missing.append(dict(item_id=item_id, color_id=colour))
        else:
            total += Decimal(str(q['price'])) * present
            used.append(q)
    count, priced = len(rows), len(used)
    enough = bool(count) and priced >= COVERAGE * count
    return dict(value=str(total.quantize(Decimal('0.01'))) if enough else None, currency=currency,
                oldest_observed=min((q['observed_at'] for q in used if q.get('observed_at')), default=None),
                stale=any(q.get('stale') for q in used), lines=count, priced=priced, enough=enough,
                unpriced=missing[:50], unpriced_count=len(missing), _unpriced_items={m['item_id'] for m in missing})


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
               unpriced_items=partout.get('unpriced_items', []), hint=None,
               oldest_observed=partout.get('oldest_observed'), stale=partout.get('stale', False), no_comparison=False)
    if out['partout'] is None:
        # Not enough prices for a total: the card says so and offers to fetch the missing ones.
        out['complete'] = out['as_is'] = None
        return out
    complete_quote = copy.get('complete_quote') or {}
    if copy.get('comparison_currency', complete_quote.get('currency', out['currency'])) != out['currency']:
        out.update(complete=None, as_is=None, no_comparison=True,
                   comparison_currency=copy.get('comparison_currency', complete_quote.get('currency')))
        return out
    complete = complete_quote.get('price')
    out['complete'] = str(D(str(complete)).quantize(D('0.01'))) if complete is not None else None
    as_is = copy.get('current_value')
    out['as_is'] = str(D(str(as_is)).quantize(D('0.01'))) if as_is is not None else None
    if out['as_is'] is not None:
        gain = D(out['partout']) - D(out['as_is'])
        # A hint only when parting out is clearly worth more: 10 % and at least 5 in the currency.
        out['hint'] = str(gain.quantize(D('0.01'))) if advantage(D(out['partout']), D(out['as_is'])) else None
    return out
