"""Complete or part out (#55), one batched projection shared by every reader.

A place is a loose stock record or a live figure line in a set copy. Quantities
and component check state belong to that place; missing and damaged overlap is
capped at the required quantity. No stale or foreign quote becomes a zero.
"""
from collections import defaultdict
from decimal import Decimal as D

from . import collection, partout, planning, items
from .sources.base import now

RULE = ('Complete it when complete value less the cost to complete beats the part-out value by 10% and at least €5.00. '
        'Part out when the reverse holds. Otherwise no recommendation.')


def project(row, config):
    """Price one place whose component lines already carry fresh used quotes."""
    lines = row['parts']
    priced = sum(p['quote'] is not None for p in lines)
    enough = bool(lines) and priced >= partout.COVERAGE * len(lines)
    present, cost, missing = D(0), D(0), 0
    cost_known = True
    for p in lines:
        need = min(p['quantity'], p['missing'] + p['damaged'])
        p['need'] = need
        missing += need
        buy = max(0, need - p.get('stock_used', 0))
        p['buy'] = buy
        if p['quote']:
            unit = D(str(p['quote']['price']))
            present += unit * (p['quantity'] - need)
            cost += unit * buy
        elif buy:
            cost_known = False
    fees = D(str(config['repair_shipping'])) + D(str(config['repair_fees'])) if missing else D(0)
    minimum = max(D(0), D(str(config['repair_min_order'])) - cost) if missing else D(0)
    total = cost + fees + minimum if cost_known else None
    complete = D(str(row['complete_quote']['price'])) * row['quantity'] if row['complete_quote'] else None
    parts = present if enough else None
    gain = complete - total - parts if complete is not None and total is not None and parts is not None else None
    recommendation = None
    if gain is not None and missing:
        net = complete - total
        recommendation = ('Complete it' if partout.advantage(net, parts) else
                          'Part out' if partout.advantage(parts, net) else 'Keep as is')
    amount = lambda v: str(v.quantize(D('0.01'))) if v is not None else None
    row.update(complete=amount(complete), parts_value=amount(parts), to_complete=amount(total),
               shipping_fees=amount(fees), minimum_order_extra=amount(minimum), gain=amount(gain),
               currency=config['bricklink_currency'], lines=len(lines), priced=priced, enough=enough,
               missing_count=missing, recommendation=recommendation,
               needs_evidence=not enough or complete is None or total is None)
    return row


def compare(db, item_id=None):
    """All live places with component data, optionally scoped to one figure. Fixed query count."""
    rows = [dict(r) for r in db.execute('''SELECT 'stock:'||s.id place, s.id stock_id, NULL copy_id,
        NULL copy_figure_id,s.item_id,s.quantity,s.storage_id,i.name,i.year,i.theme_name theme
        FROM stock s JOIN item i ON i.id=s.item_id WHERE s.kind='minifigure'
        AND s.archived_at IS NULL AND s.quantity>0 AND (? IS NULL OR s.item_id=?)
        UNION ALL SELECT 'figure:'||f.id,NULL,c.id,f.id,f.item_id,f.quantity,c.storage_id,i.name,i.year,i.theme_name
        FROM copy_figure f JOIN copy c ON c.id=f.copy_id JOIN item i ON i.id=f.item_id
        WHERE c.archived_at IS NULL AND f.retired_at IS NULL AND f.quantity>f.missing
        AND (? IS NULL OR f.item_id=?) ORDER BY place''', (item_id, item_id, item_id, item_id))]
    places = {r['place']: r for r in rows}
    components = [dict(r) for r in db.execute('''SELECT 'stock:'||p.stock_id place,p.item_id,p.color_id,p.quantity,p.missing,p.damaged
        FROM stock_part p JOIN stock s ON s.id=p.stock_id WHERE p.retired_at IS NULL AND p.is_spare=0 AND p.quantity>0
        AND s.archived_at IS NULL AND (? IS NULL OR s.item_id=?)
        UNION ALL SELECT 'figure:'||p.copy_figure_id,p.item_id,p.color_id,p.quantity,p.missing,p.damaged
        FROM copy_part p JOIN copy_figure f ON f.id=p.copy_figure_id WHERE p.retired_at IS NULL AND p.is_spare=0 AND p.quantity>0
        AND (? IS NULL OR f.item_id=?)''', (item_id, item_id, item_id, item_id)) if r['place'] in places]
    grouped = defaultdict(list)
    for p in collection.decorate(db, components):
        grouped[p['place']].append(p)
    rows = [r for r in collection.decorate(db, rows) if not r['unresolved'] and grouped[r['place']]]
    config, stamp = planning.configuration(db), now()
    scope = {(r['item_id'], None) for r in rows} | {(p['item_id'], p['color_id']) for p in components}
    market = collection.prices(db, pairs=scope) if scope else {}
    quotes = {k: planning.quote(market.get(k, []), 'used', config, stamp) for k in scope}
    labels = collection.copy_labels(db, [r['copy_id'] for r in rows if r['copy_id']])
    set_ids = {r['id']: r['item_id'] for r in db.execute('SELECT id,item_id FROM copy WHERE archived_at IS NULL')}
    names = items.labels(db, {(set_ids[r['copy_id']], None) for r in rows if r['copy_id']})
    for r in rows:
        r['where'] = 'sets' if r['copy_id'] else 'loose'
        r['place_label'] = ('In ' + names[set_ids[r['copy_id']], None].text + ' ' + labels[r['copy_id']]) if r['copy_id'] else 'Loose'
        r['complete_quote'] = quotes.get((r['item_id'], None))
        r['parts'] = grouped[r['place']]
        for p in r['parts']:
            p['quote'] = quotes.get((p['item_id'], p['color_id']))
        project(r, config)
    return sorted(rows, key=lambda r: (r['needs_evidence'], r['where'] != 'loose', -D(r['gain'] or 0), r['number_text'], r['place']))
