"""Complete or part out (#55), one batched projection shared by every reader.

A place is a loose stock record or a live figure line in a set copy. Quantities
and component check state belong to that place; missing and damaged overlap is
capped at the required quantity. No stale or foreign quote becomes a zero.
"""
from collections import defaultdict
from decimal import Decimal as D

from . import collection, partout, planning, items, workbench
from .sources.base import now

RULE = (f'Complete it when complete value less the cost to complete beats the part-out value by {partout.MARGIN * 100:.0f}% and at least €{partout.MINIMUM_GAIN:.2f}. '
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
    fees = (D(str(config['repair_shipping'])) + D(str(config['repair_fees']))) * row['quantity'] if missing else D(0)
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
    row.update(minimum_gain=str(partout.MINIMUM_GAIN), margin_percent=int(partout.MARGIN * 100), complete=amount(complete), parts_value=amount(parts), to_complete=amount(total),
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
        AND (? IS NULL OR f.item_id=?) ORDER BY place''', (None, None, None, None))]
    places = {r['place']: r for r in rows}
    components = [dict(r) for r in db.execute('''SELECT 'stock:'||p.stock_id place,p.item_id,p.color_id,p.quantity,p.missing,p.damaged
        FROM stock_part p JOIN stock s ON s.id=p.stock_id WHERE p.retired_at IS NULL AND p.is_spare=0 AND p.quantity>0
        AND s.archived_at IS NULL AND (? IS NULL OR s.item_id=?)
        UNION ALL SELECT 'figure:'||p.copy_figure_id,p.item_id,p.color_id,p.quantity,p.missing,p.damaged
        FROM copy_part p JOIN copy_figure f ON f.id=p.copy_figure_id WHERE p.retired_at IS NULL AND p.is_spare=0 AND p.quantity>0
        AND (? IS NULL OR f.item_id=?)''', (None, None, None, None)) if r['place'] in places]
    grouped = defaultdict(list)
    for p in collection.decorate(db, components):
        grouped[p['place']].append(p)
    rows = [r for r in collection.decorate(db, rows) if not r['unresolved'] and grouped[r['place']]]
    config, stamp = planning.configuration(db), now()
    scope = {(r['item_id'], None) for r in rows} | {(p['item_id'], p['color_id']) for p in components}
    market = collection.prices(db, pairs=scope) if scope else {}
    quotes = {k: planning.quote([q for q in market.get(k, []) if q.get('slot') != 'boxed'], 'used', config, stamp) for k in scope}
    # Allocate available loose parts once, in the same deterministic place order on every reader.
    pool = defaultdict(int)
    if config['repair_use_loose_stock']:
        for stock in db.execute("SELECT * FROM stock WHERE kind='part' AND archived_at IS NULL"):
            pool[stock['item_id'], stock['color_id']] += workbench.available(db, stock)
        for held in db.execute("SELECT item_id,color_id,sum(qty) qty FROM allocation WHERE state='pending' AND kind='missing_part' GROUP BY item_id,color_id"):
            pool[held['item_id'], held['color_id']] = max(0, pool[held['item_id'], held['color_id']] - held['qty'])
    storages = dict(db.execute('SELECT id,name FROM storage WHERE archived_at IS NULL'))
    identities = items.labels(db, {(r['item_id'], None) for r in rows})
    labels = collection.copy_labels(db, [r['copy_id'] for r in rows if r['copy_id']])
    set_ids = {r['id']: r['item_id'] for r in db.execute('SELECT id,item_id FROM copy WHERE archived_at IS NULL')}
    names = items.labels(db, {(set_ids[r['copy_id']], None) for r in rows if r['copy_id']})
    rows.sort(key=lambda r: (r['copy_id'] is not None, r['place']))
    for r in rows:
        label = identities[r['item_id'], None]
        r['number_text'] = label.bricklink[1] if label.bricklink else label.number
        r['storage_name'] = storages.get(r['storage_id'])
        r['where'] = 'sets' if r['copy_id'] else 'loose'
        r['place_label'] = ('In ' + names[set_ids[r['copy_id']], None].text + ' ' + labels[r['copy_id']]) if r['copy_id'] else 'Loose'
        r['complete_quote'] = quotes.get((r['item_id'], None))
        r['parts'] = grouped[r['place']]
        for p in r['parts']:
            key = p['item_id'], p['color_id']
            p['quote'] = quotes.get(key)
            p['stock_used'] = min(pool[key], min(p['quantity'], p['missing'] + p['damaged']))
            pool[key] -= p['stock_used']
        project(r, config)
        r['unpriced_items'] = sorted({p['item_id'] for p in r['parts'] if not p['quote'] and not p['unresolved']} |
                                     ({r['item_id']} if not r['complete_quote'] else set()))
    return sorted([r for r in rows if item_id is None or r['item_id'] == item_id], key=lambda r: (r['needs_evidence'], r['where'] != 'loose', -D(r['gain'] or 0), r['number_text'], r['place']))


def read_body(db, item_id):
    """Stable API/MCP comparison body; money is decimal text in one currency."""
    fields = ('place', 'stock_id', 'copy_id', 'copy_figure_id', 'place_label', 'currency', 'quantity',
              'complete', 'parts_value', 'to_complete', 'shipping_fees', 'minimum_order_extra',
              'gain', 'lines', 'priced', 'enough', 'missing_count', 'needs_evidence', 'recommendation')
    quote = lambda q: {k: q[k] for k in ('price', 'currency', 'observed_at', 'guide')} if q else None
    return [dict({k:r[k] for k in fields}, complete_quote=quote(r['complete_quote']),
                 parts=[dict(item_id=p['item_id'], color_id=p['color_id'], quantity=p['quantity'],
                             missing=p['missing'], damaged=p['damaged'], need=p['need'], buy=p['buy'],
                             stock_used=p['stock_used'], quote=quote(p['quote'])) for p in r['parts']])
            for r in compare(db, item_id)]
