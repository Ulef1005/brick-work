"""What you already own of an identified part or figure (#45), across colours.

Photo identification gives the shape, not the colour, so the summary lists every colour you hold,
the most held first, with where it is stored, plus the copies whose inventory needs that part
(missing or damaged). Batched: three queries for any number of candidates.
"""
from collections import defaultdict
import json


def summary(db, keys):
    keys = sorted({(t, n) for t, n in keys if t and n})
    if not keys:
        return {}
    packed = json.dumps([t + '\x1f' + n for t, n in keys])
    colours = {r[0]: dict(name=r[1], rgb=r[2]) for r in db.execute('SELECT color_id,name,rgb FROM colors')}
    held = defaultdict(lambda: defaultdict(lambda: dict(quantity=0, storages=set())))
    for r in db.execute('''SELECT s.item_type,s.item_no,s.color_id,s.quantity,coalesce(t.name,l.name) AS place
            FROM loose_stock s LEFT JOIN storages t ON t.id=s.storage_id AND t.archived_at IS NULL
            LEFT JOIN lots l ON l.id=s.lot_id AND l.archived_at IS NULL
            WHERE s.archived_at IS NULL AND s.quantity>0 AND (s.item_type||char(31)||s.item_no) IN (SELECT value FROM json_each(?))''', (packed,)):
        entry = held[r['item_type'], r['item_no']][r['color_id']]
        entry['quantity'] += r['quantity']
        if r['place']:
            entry['storages'].add(r['place'])
    needs = defaultdict(list)
    for r in db.execute('''SELECT p.item_type,p.item_no,p.color_id,p.copy_id,c.set_no,
            sum(coalesce(p.missing,0)+coalesce(p.damaged,0)) AS gap
            FROM copy_parts p JOIN copies c ON c.id=p.copy_id AND c.archived_at IS NULL
            WHERE coalesce(p.spare,0)=0 AND (p.item_type||char(31)||p.item_no) IN (SELECT value FROM json_each(?))
            GROUP BY 1,2,3,4 HAVING gap>0 ORDER BY c.set_no''', (packed,)):
        needs[r['item_type'], r['item_no']].append(dict(copy_id=r['copy_id'], set_no=r['set_no'], color_id=r['color_id'], gap=r['gap']))
    for r in db.execute('''SELECT m.item_type,m.minifig_no,m.copy_id,c.set_no,sum(coalesce(m.missing,0)) AS gap
            FROM copy_minifigs m JOIN copies c ON c.id=m.copy_id AND c.archived_at IS NULL
            WHERE (m.item_type||char(31)||m.minifig_no) IN (SELECT value FROM json_each(?)) GROUP BY 1,2,3 HAVING gap>0''', (packed,)):
        needs[r['item_type'], r['minifig_no']].append(dict(copy_id=r['copy_id'], set_no=r['set_no'], color_id=None, gap=r['gap']))
    out = {}
    for key in keys:
        rows = [dict(color_id=c, name=(colours.get(c) or {}).get('name'), rgb=(colours.get(c) or {}).get('rgb'),
                     quantity=v['quantity'], storages=sorted(v['storages']))
                for c, v in held.get(key, {}).items()]
        rows.sort(key=lambda r: (-r['quantity'], r['name'] or ''))
        out[key] = dict(total=sum(r['quantity'] for r in rows), colours=rows, needed_by=needs.get(key, [])[:20],
                        needed_count=len(needs.get(key, [])))
    return out


def text(info):
    """'You have 14 in 3 colours: Black 8 (Bin A3), Red 4 (Bin C1)' or 'Not in your collection'."""
    if not info or not info['total']:
        return 'Not in your collection'
    shown = []
    for c in info['colours'][:4]:
        where = ' (' + ', '.join(c['storages'][:2]) + ')' if c['storages'] else ''
        shown.append(f"{c['name'] or 'No colour'} {c['quantity']}{where}")
    more = len(info['colours']) - len(shown)
    colours = len(info['colours'])
    head = f"You have {info['total']}" + (f" in {colours} colours" if colours > 1 else '')
    return head + ': ' + ', '.join(shown) + (f', {more} more' if more > 0 else '')
