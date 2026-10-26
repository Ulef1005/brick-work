"""What you already own of an identified part or figure (#45), across colours.

Photo identification gives the shape, not the colour, so the summary lists every colour you hold,
the most held first, with where it is stored, plus the copies whose inventory needs that part
(missing or damaged). Batched: a handful of queries for any number of candidates. Keyed by item id (4.0).
"""
from collections import defaultdict
import json


def summary(db, item_ids):
    """`{item id: dict(total, colours, needed_by, needed_count)}` for the identified parts and figures `item_ids` (4.0: items are ids).

    Loose stock counts parts and figures held on their own (live, quantity above zero); `needed_by` lists the live copies whose live,
    non-spare lines of that item are missing or damaged (a retired line is no line, design 4.4)."""
    ids = sorted({i for i in item_ids if i})
    if not ids:
        return {}
    packed = json.dumps(ids)
    colours = {r[0]: dict(name=r[1], rgb=r[2]) for r in db.execute('SELECT id,name,rgb FROM main.color')}
    held = defaultdict(lambda: defaultdict(lambda: dict(quantity=0, storages=set())))
    for r in db.execute('''SELECT s.item_id,s.color_id,s.quantity,coalesce(t.name,l.name) AS place
            FROM stock s LEFT JOIN storage t ON t.id=s.storage_id AND t.archived_at IS NULL
            LEFT JOIN lot l ON l.id=s.lot_id AND l.archived_at IS NULL
            WHERE s.archived_at IS NULL AND s.quantity>0 AND s.item_id IN (SELECT value FROM json_each(?))''', (packed,)):
        entry = held[r['item_id']][r['color_id']]
        entry['quantity'] += r['quantity']
        if r['place']:
            entry['storages'].add(r['place'])
    needs = defaultdict(list)
    for r in db.execute('''SELECT p.item_id,p.color_id,p.copy_id,c.item_id AS set_id,sum(p.missing+p.damaged) AS gap
            FROM copy_part p JOIN copy c ON c.id=p.copy_id AND c.archived_at IS NULL
            WHERE p.retired_at IS NULL AND p.is_spare=0 AND p.item_id IN (SELECT value FROM json_each(?))
            GROUP BY 1,2,3 HAVING gap>0 ORDER BY c.item_id,c.created_at,c.id''', (packed,)):
        needs[r['item_id']].append(dict(copy_id=r['copy_id'], set_id=r['set_id'], color_id=r['color_id'], gap=r['gap']))
    for r in db.execute('''SELECT f.item_id,f.copy_id,c.item_id AS set_id,sum(f.missing) AS gap
            FROM copy_figure f JOIN copy c ON c.id=f.copy_id AND c.archived_at IS NULL
            WHERE f.retired_at IS NULL AND f.item_id IN (SELECT value FROM json_each(?)) GROUP BY 1,2 HAVING gap>0''', (packed,)):
        needs[r['item_id']].append(dict(copy_id=r['copy_id'], set_id=r['set_id'], color_id=None, gap=r['gap']))
    from . import items
    numbers = {k[0]: l for k, l in items.labels(db, [(r['set_id'], None) for rows in needs.values() for r in rows]).items()}
    out = {}
    for item_id in ids:
        rows = [dict(color_id=c, name=(colours.get(c) or {}).get('name'), rgb=(colours.get(c) or {}).get('rgb'),
                     quantity=v['quantity'], storages=sorted(v['storages']))
                for c, v in held.get(item_id, {}).items()]
        rows.sort(key=lambda r: (-r['quantity'], r['name'] or ''))
        wanted = [dict(r, set_no=(numbers[r['set_id']].number or numbers[r['set_id']].name) if r['set_id'] in numbers else '') for r in needs.get(item_id, [])]
        out[item_id] = dict(total=sum(r['quantity'] for r in rows), colours=rows, needed_by=wanted[:20], needed_count=len(wanted))
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
