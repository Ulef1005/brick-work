"""Printable and CSV lists (#43) on the 4.0 store (M.8e, issue #110): missing parts, Part Picker results and the wishlist.

The same rows feed the CSV download and the printed page; colour names always travel with the colour id so a black-and-white printout
still says which colour. Every row names its item as the screens do (`core/items.py`: the Rebrickable number first, the preferred
BrickLink number beside it where it differs; an unidentified item by its name) and carries its picture (`image`).
"""
from collections import defaultdict
import io

from . import collection, gaps, workbench
from . import csv_safe

MISSING = ('Item type', 'Item number', 'Name', 'Colour', 'Colour id', 'Condition', 'Quantity', 'Note')
PICKER = ('Rank', 'Item type', 'Item number', 'Name', 'Colour', 'Colour id', 'Quantity', 'Sets', 'Storage')
WISHLIST = ('List', 'Item type', 'Item number', 'Name', 'Colour', 'Colour id', 'Quantity', 'Condition', 'Max price', 'Currency', 'Note')


def _shown(db, rows):
    """The rows with the screen's words for their item and colour (`collection.decorate`), keeping their own keys."""
    return collection.decorate(db, rows)


def missing(db, copy_ids):
    """Missing items of the chosen copies, combined per item, colour and condition, as the XML export does, except that items with no
    BrickLink number stay on the list (marked) instead of being left out: a printout is still useful while they wait to be matched."""
    lines = defaultdict(int)
    for gap in gaps.copy_gaps(db, copy_ids):
        lines[gap['item_id'], gap['color_id'], gap['condition'] or 'used'] += gap['quantity']
    shown = _shown(db, [dict(item_id=i, color_id=c, condition=cond, quantity=q) for (i, c, cond), q in lines.items()])
    for r in shown:
        r['colour'] = r['color_name']
    return sorted(shown, key=lambda r: ((r['number_text'] or r['name'] or '').lower(), r['color_id'] or 0, r['condition']))


def picker(db, copy_ids, ranking=None):
    rows = workbench.picker(db, copy_ids, ranking or list(workbench.PICKER_DEFAULT))
    return [dict(rank=i, item_id=r['item_id'], item_type=r['item_type'], item_no=r['item_no'], number_text=r['number_text'], name=r['name'], colour=r['color_name'],
                 color_id=r['color_id'], quantity=r['total'], image=r['image'], unresolved=r['unresolved'],
                 sets=' · '.join(sorted({n['copy']['set_no'] for n in r['needs']})), storage=r.get('rank_storage') or '')
            for i, r in enumerate(rows, 1)]


def wishlist(db, list_id='all'):
    if list_id != 'all' and not db.execute('SELECT 1 FROM main.wishlist WHERE id=? AND archived_at IS NULL', (list_id,)).fetchone():
        raise ValueError('Choose an existing wishlist')
    rows = [dict(r) for r in db.execute('''SELECT w.*,l.name AS list_name,l.sort AS list_sort FROM main.wish w JOIN main.wishlist l ON l.id=w.wishlist_id
        WHERE w.archived_at IS NULL AND l.archived_at IS NULL AND (?='all' OR w.wishlist_id=?)''', (list_id, list_id))]
    shown = _shown(db, rows)
    for r in shown:
        r['colour'] = r['color_name']
    return sorted(shown, key=lambda r: (r['list_sort'], r['list_name'], r['item_type'], (r['number_text'] or r['name'] or '').lower(), r['color_id'] or 0, r['id']))


def to_csv(kind, rows):
    stream = io.StringIO(newline='')
    out = csv_safe.writer(stream)
    if kind == 'missing':
        out.writerow(MISSING)
        out.writerows([r['item_type'], r['item_no'], r['name'] or '', r['colour'] or '', '' if r['color_id'] is None else r['color_id'],
                       (r['condition'] or '').capitalize(), r['quantity'], 'Not matched yet' if r['unresolved'] else ''] for r in rows)
    elif kind == 'picker':
        out.writerow(PICKER)
        out.writerows([r['rank'], r['item_type'], r['item_no'], r['name'] or '', r['colour'] or '',
                       '' if r['color_id'] is None else r['color_id'], r['quantity'], r['sets'], r['storage']] for r in rows)
    else:
        out.writerow(WISHLIST)
        out.writerows([r['list_name'], r['item_type'], r['item_no'], r['name'] or '', r['colour'] or '',
                       '' if r['color_id'] is None else r['color_id'], r['quantity'], (r['condition'] or '').capitalize(),
                       r['max_price'] or '', r['max_price_currency'] or '', r['note'] or ''] for r in rows)
    return stream.getvalue()
