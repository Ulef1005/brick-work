"""Printable and CSV lists (#43): missing parts, Part Picker results and the wishlist.

The same rows feed the CSV download and the printed page; colour names always travel with the colour
id so a black-and-white printout still says which colour.
"""
import csv

from . import csv_safe
import io
import json

from . import planning, workbench

MISSING = ('Item type', 'Item number', 'Name', 'Colour', 'Colour id', 'Condition', 'Quantity', 'Note')
PICKER = ('Rank', 'Item type', 'Item number', 'Name', 'Colour', 'Colour id', 'Quantity', 'Sets', 'Storage')
WISHLIST = ('List', 'Item type', 'Item number', 'Name', 'Colour', 'Colour id', 'Quantity', 'Condition', 'Max price', 'Currency', 'Note')


def _names(db, keys):
    keys = sorted({(t, n) for t, n in keys if t and n})
    if not keys:
        return {}
    return {(r[0], r[1]): r[2] for r in db.execute(
        "SELECT item_type,item_no,name FROM items WHERE (item_type||char(31)||item_no) IN (SELECT value FROM json_each(?))",
        (json.dumps([t + '\x1f' + n for t, n in keys]),))}


def _colours(db):
    return {r[0]: r[1] for r in db.execute('SELECT color_id,name FROM colors')}


def missing(db, copy_ids):
    """Missing items of the chosen copies, combined per item, colour and condition, as the XML export does,
    except that unresolved figures and parts without a colour stay on the list (marked) instead of
    blocking it: a printout is still useful while they wait to be matched."""
    from collections import defaultdict
    if not isinstance(copy_ids, list) or not copy_ids or len(copy_ids) > 2000 or len(set(copy_ids)) != len(copy_ids):
        raise ValueError('Choose copies to list')
    chosen = [r for r in planning.ranking(db)['rows'] if r['id'] in copy_ids]
    if len(chosen) != len(copy_ids):
        raise ValueError('Copy is unavailable')
    lines, unresolved = defaultdict(int), set()
    for c in chosen:
        for r in c['items']:
            if not r['missing']:
                continue
            key = (r['item_type'], r['item_no'], r['color_id'], c['condition'] or 'U')
            lines[key] += r['missing']
            if r['unresolved'] or r['item_type'] == '?' or (r['item_type'] == 'P' and r['color_id'] is None):
                unresolved.add(key)
    names, colours = _names(db, [k[:2] for k in lines]), _colours(db)
    return [dict(item_type=t, item_no=n, color_id=col, condition=cond, quantity=q, name=names.get((t, n)),
                 colour=colours.get(col), unresolved=(t, n, col, cond) in unresolved)
            for (t, n, col, cond), q in sorted(lines.items(), key=lambda pair: str(pair[0]))]


def picker(db, copy_ids, ranking=None):
    rows = workbench.picker(db, copy_ids, ranking or list(workbench.PICKER_DEFAULT))
    names, colours = _names(db, [(r['item_type'], r['item_no']) for r in rows]), _colours(db)
    return [dict(rank=i, item_type=r['item_type'], item_no=r['item_no'], name=r.get('name') or names.get((r['item_type'], r['item_no'])),
                 colour=colours.get(r['color_id']), color_id=r['color_id'], quantity=r['total'],
                 sets=' · '.join(sorted({n['copy']['set_no'] for n in r['needs']})), storage=r.get('rank_storage') or '')
            for i, r in enumerate(rows, 1)]


def wishlist(db, list_id='all'):
    from . import wishlists
    if list_id != 'all':
        wishlists.require(db, list_id)
    rows = [dict(r) for r in db.execute('''SELECT w.*,l.name AS list_name FROM wishlist w JOIN wishlists l ON l.id=w.list_id
        WHERE w.archived_at IS NULL AND l.archived_at IS NULL AND (?='all' OR w.list_id=?)
        ORDER BY l.sort,l.name,w.item_type,w.item_no,w.color_id''', (list_id, list_id))]
    names, colours = _names(db, [(r['item_type'], r['item_no']) for r in rows]), _colours(db)
    return [dict(r, name=names.get((r['item_type'], r['item_no'])), colour=colours.get(r['color_id'])) for r in rows]


def to_csv(kind, rows):
    stream = io.StringIO(newline='')
    out = csv_safe.writer(stream)
    if kind == 'missing':
        out.writerow(MISSING)
        out.writerows([r['item_type'], r['item_no'], r['name'] or '', r['colour'] or '', '' if r['color_id'] is None else r['color_id'],
                       {'N': 'New', 'U': 'Used'}.get(r['condition'], r['condition'] or ''), r['quantity'],
                       'Not matched yet' if r['unresolved'] else ''] for r in rows)
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
