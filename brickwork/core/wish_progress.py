"""Wishlist progress (#35): how much of each wished line you already have.

Derived, not booked: parts count loose stock of the same part and colour in a usable condition (parts
inside set copies are needed there and never count); sets count live copies; minifigures and other
items count loose stock. A manual value per line (qty_filled_manual, also set from BrickLink's
QTYFILLED on import) overrides the derived one. Three queries for any number of lines.
"""
from collections import defaultdict
import json

CONDITIONS = {'new': ('N',), 'used': ('U',), 'any': ('N', 'U'), None: ('N', 'U')}


def annotate(db, rows):
    keys = sorted({(r['item_type'], r['item_no']) for r in rows})
    if not keys:
        return rows
    packed = json.dumps([t + '\x1f' + n for t, n in keys])
    stock = defaultdict(int)
    for r in db.execute('''SELECT item_type,item_no,color_id,condition,sum(quantity) FROM loose_stock
            WHERE archived_at IS NULL AND (item_type||char(31)||item_no) IN (SELECT value FROM json_each(?))
            GROUP BY 1,2,3,4''', (packed,)):
        stock[r[0], r[1], r[2], r[3]] += r[4] or 0
    copies = {(r[0], r[1]): r[2] for r in db.execute('''SELECT item_type,set_no,count(*) FROM copies WHERE archived_at IS NULL
            AND (item_type||char(31)||set_no) IN (SELECT value FROM json_each(?)) GROUP BY 1,2''', (packed,))}
    manual = {}
    ids = [r['id'] for r in rows if r.get('id') is not None]
    if ids:
        manual = {r[0]: r[1] for r in db.execute('SELECT id,qty_filled_manual FROM wishlist WHERE id IN (SELECT value FROM json_each(?))',
                                                (json.dumps(ids),))}
    for r in rows:
        if r['item_type'] == 'S':
            derived = copies.get(('S', r['item_no']), 0)
        else:
            derived = sum(stock.get((r['item_type'], r['item_no'], r.get('color_id'), c), 0)
                          for c in CONDITIONS.get(r.get('condition'), ('N', 'U')))
        override = manual.get(r.get('id'))
        r['qty_filled_manual'] = override
        r['qty_filled'] = override if override is not None else derived
        r['qty_filled_source'] = 'manual' if override is not None else 'derived'
        r['filled'] = r['qty_filled'] >= (r.get('quantity') or 1)
    return rows
