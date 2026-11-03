"""Wishlist progress (#35): how much of each wished line you already have.

Derived, not booked: parts count loose stock of the same part and colour in a usable condition (new or used; parts
inside set copies are needed there and never count); sets count live copies; minifigures and other
items count loose stock. A manual value per line (qty_filled_manual, also set from BrickLink's
QTYFILLED on import) overrides the derived one. Three queries for any number of lines.
"""
from collections import defaultdict
import json

CONDITIONS = {'new': ('new',), 'used': ('used',), 'any': ('new', 'used'), None: ('new', 'used')}


def annotate(db, rows):
    """Add `qty_filled_manual`, `qty_filled`, `qty_filled_source` and `filled` to wish rows (4.0: `item_id`, `color_id`, words)."""
    ids = sorted({r['item_id'] for r in rows})
    if not ids:
        return rows
    packed = json.dumps(ids)
    stock = defaultdict(int)
    for r in db.execute('''SELECT item_id,color_id,condition,sum(quantity) FROM stock
            WHERE archived_at IS NULL AND item_id IN (SELECT value FROM json_each(?)) GROUP BY 1,2,3''', (packed,)):
        stock[r[0], r[1], r[2]] += r[3] or 0
    copies = {r[0]: r[1] for r in db.execute('''SELECT item_id,count(*) FROM copy WHERE archived_at IS NULL
            AND item_id IN (SELECT value FROM json_each(?)) GROUP BY 1''', (packed,))}
    manual = {}
    wish_ids = [r['id'] for r in rows if r.get('id') is not None]
    if wish_ids:
        manual = {r[0]: r[1] for r in db.execute('SELECT id,qty_filled_manual FROM wish WHERE id IN (SELECT value FROM json_each(?))',
                                                (json.dumps(wish_ids),))}
    for r in rows:
        if r.get('kind') == 'set' or r.get('item_type') == 'S':
            derived = copies.get(r['item_id'], 0)
        else:
            derived = sum(stock.get((r['item_id'], r.get('color_id'), c), 0) for c in CONDITIONS.get(r.get('condition'), ('new', 'used')))
        override = manual.get(r.get('id'))
        r['qty_filled_manual'] = override
        r['qty_filled'] = override if override is not None else derived
        r['qty_filled_source'] = 'manual' if override is not None else 'derived'
        r['filled'] = r['qty_filled'] >= (r.get('quantity') or 1)
    return rows
