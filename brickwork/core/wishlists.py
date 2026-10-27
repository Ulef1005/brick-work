"""Named wishlists, their receipts and the portable exports on the 4.0 store (M.8g, issue #110; design 5 `wishlist` / `wish`, 5.1).

A wishlist is a `wishlist` row; a wish is a `wish` row with a uuid id, a kind word, an item id and, for a part, a colour id. A list holds
one live wish per item and colour (`wish_live_key`). Every change is one `collection` receipt event (`collection.receipt`), reversed by
`collection.undo`. The exports name an item for BrickLink through `core.items` (the preferred confirmed link, else a BrickLink-born number)
and for Rebrickable by its Rebrickable number: a row that cannot be named is **left out and listed** in the summary, never exported
under a made-up number and never a reason to stop the export."""
import io
import json
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from xml.etree import ElementTree as ET

from . import collection, errors, items
from .currency import configured_currency
from .transaction import transaction
from ..store4.connect import now as stamp_now

DEFAULT = 'default'


def listing(db, *, archived=False):
    return [dict(r) for r in db.execute('''SELECT l.*,count(w.id) AS count FROM wishlist l
        LEFT JOIN wish w ON w.wishlist_id=l.id AND w.archived_at IS NULL
        WHERE (? OR l.archived_at IS NULL) GROUP BY l.id ORDER BY l.sort,l.name,l.id''', (archived,))]


def require(db, identifier=DEFAULT):
    row = db.execute('SELECT * FROM wishlist WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone()
    if not row:
        raise ValueError('Choose an active wishlist')
    return dict(row)


def save(db, identifier=None, data=None, *, action='save'):
    data = data or {}
    with transaction(db):
        before = collection.snapshot(db, 'wishlist', [identifier]) if identifier else []
        if identifier and not before:
            raise ValueError('Wishlist is unavailable')
        stamp = stamp_now()
        wishes = []
        if action in ('archive', 'restore'):
            restoring = action == 'restore'
            if (before[0]['archived_at'] is None) == restoring:
                raise ValueError('Wishlist is already ' + ('active' if restoring else 'archived'))
            if not restoring:
                # The stamp tells the wishes archived with the list from the ones archived on their own, so it must differ from theirs.
                taken = {r[0] for r in db.execute('SELECT DISTINCT archived_at FROM wish WHERE wishlist_id=? AND archived_at IS NOT NULL', (identifier,))}
                while stamp in taken:
                    time.sleep(0.001)
                    stamp = stamp_now()
            wishes = [dict(r) for r in db.execute('SELECT * FROM wish WHERE wishlist_id=? AND archived_at IS ?',
                       (identifier, before[0]['archived_at'] if restoring else None))]
            if restoring:
                for r in wishes:
                    collection.wish_collision(db, 'wish', dict(r, archived_at=None))
            db.execute('UPDATE wishlist SET archived_at=? WHERE id=?', (None if restoring else stamp, identifier))
            db.execute('UPDATE wish SET archived_at=?,updated_at=? WHERE id IN (SELECT value FROM json_each(?))',
                       (None if restoring else stamp, stamp, json.dumps([r['id'] for r in wishes])))
        else:
            if before and before[0]['archived_at']:
                raise ValueError('Restore the wishlist first')
            name = str(data.get('name', before[0]['name'] if before else '')).strip()
            if not name or len(name) > 120:
                raise ValueError('Enter a wishlist name up to 120 characters')
            note = data.get('note', before[0]['note'] if before else None)
            sort = data.get('sort', before[0]['sort'] if before else 0)
            if type(sort) is not int:
                raise ValueError('Choose a whole sort number')
            bl_id = data.get('bricklink_id', before[0]['bricklink_id'] if before else None)
            if bl_id is not None and (not isinstance(bl_id, str) or not bl_id.isdecimal()):
                raise ValueError('Enter a numeric BrickLink wanted list id')
            if bl_id and db.execute('SELECT 1 FROM wishlist WHERE bricklink_id=? AND id!=?', (bl_id, identifier or '')).fetchone():
                raise errors.Conflict('BrickLink wanted list id is already linked')
            if before:
                db.execute('UPDATE wishlist SET name=?,note=?,sort=?,bricklink_id=? WHERE id=?', (name, note, sort, bl_id, identifier))
            else:
                identifier = uuid4().hex
                db.execute('INSERT INTO wishlist(id,name,note,sort,created_at,bricklink_id) VALUES(?,?,?,?,?,?)',
                           (identifier, name, note, sort, stamp, bl_id))
        changes = [('wishlist', before, collection.snapshot(db, 'wishlist', [identifier]))]
        if wishes:
            changes.append(('wish', wishes, collection.snapshot(db, 'wish', [r['id'] for r in wishes])))
        event = collection.receipt(db, changes, 'save')
        return identifier, event


def transfer(db, ids, target, *, copy=False):
    if not isinstance(ids, list) or not ids or len(ids) > 500 or len(set(ids)) != len(ids) or not all(isinstance(i, str) for i in ids):
        raise ValueError('Choose up to 500 wishes once each')
    with transaction(db):
        require(db, target)
        before = collection.snapshot(db, 'wish', ids)
        if len(before) != len(ids) or any(r['archived_at'] for r in before):
            raise ValueError('Wish is unavailable')
        keys = [(r['item_id'], r['color_id']) for r in before]
        if len(set(keys)) != len(keys):
            raise errors.Conflict('Selected wishes repeat an item and colour')
        current = {(r['item_id'], r['color_id']): r['id'] for r in db.execute(
            'SELECT id,item_id,color_id FROM wish WHERE wishlist_id=? AND archived_at IS NULL', (target,))}
        for r in before:
            existing = current.get((r['item_id'], r['color_id']))
            if existing is not None and (copy or existing != r['id']):
                raise errors.Conflict('An item and colour already exists in the target list')
        stamp = stamp_now()
        if copy:
            new_ids = []
            for r in before:
                values = {k: v for k, v in r.items() if k != 'id'}
                values.update(id=uuid4().hex, wishlist_id=target, added_at=stamp, updated_at=stamp)
                db.execute('INSERT INTO wish(' + ','.join(values) + ') VALUES(' + ','.join('?' for _ in values) + ')', tuple(values.values()))
                new_ids.append(values['id'])
            changes = [('wish', [], collection.snapshot(db, 'wish', new_ids))]
            flags = defaultdict(list)
            for flag in db.execute('SELECT wish_id,flag_id FROM wish_flag WHERE wish_id IN (SELECT value FROM json_each(?)) ORDER BY wish_id,flag_id', (json.dumps(ids),)):
                flags[flag['wish_id']].append(flag['flag_id'])
            for source, destination in zip(before, new_ids):
                copied = [dict(wish_id=destination, flag_id=flag) for flag in flags[source['id']]]
                if copied:
                    db.executemany('INSERT INTO wish_flag(wish_id,flag_id) VALUES(:wish_id,:flag_id)', copied)
                    changes.append(('wish_flag', [], collection.links(db, 'wish_flag', destination)))
            return collection.receipt(db, changes, 'save')
        db.execute('UPDATE wish SET wishlist_id=?,updated_at=? WHERE id IN (SELECT value FROM json_each(?))', (target, stamp, json.dumps(ids)))
        return collection.receipt(db, [('wish', before, collection.snapshot(db, 'wish', ids))], 'save')


def _rebrickable_numbers(db, item_ids):
    """`{item id: {Rebrickable numbers}}`: the born key of a Rebrickable-born item, else the confirmed Rebrickable links of a local one."""
    packed = json.dumps(sorted(item_ids))
    found = {r['id']: {r['born_key']} for r in db.execute("""SELECT id,born_key FROM main.item WHERE born_provider='rebrickable' AND born_key IS NOT NULL
        AND id IN (SELECT value FROM json_each(?))""", (packed,))}
    linked = defaultdict(set)
    marks = ','.join('?' * len(items.CONFIRMED))
    for r in db.execute(f"""SELECT item_id,provider_key FROM main.item_link WHERE provider='rebrickable' AND status IN ({marks})
        AND item_id IN (SELECT value FROM json_each(?))""", (*items.CONFIRMED, packed)):
        linked[r['item_id']].add(r['provider_key'])
    return {**linked, **found}


def _rebrickable_colours(db, color_ids):
    """`{colour id: {Rebrickable colour numbers}}`: the born key of a Rebrickable-born colour, else its confirmed Rebrickable links."""
    packed = json.dumps(sorted(c for c in color_ids if c is not None))
    found = {r['id']: {r['born_key']} for r in db.execute("SELECT id,born_key FROM main.color WHERE born_provider='rebrickable' AND id IN (SELECT value FROM json_each(?))", (packed,))}
    linked = defaultdict(set)
    marks = ','.join('?' * len(items.CONFIRMED))
    for r in db.execute(f"""SELECT color_id,provider_key FROM main.color_link WHERE provider='rebrickable' AND status IN ({marks})
        AND color_id IN (SELECT value FROM json_each(?))""", (*items.CONFIRMED, packed)):
        linked[r['color_id']].add(r['provider_key'])
    return {**linked, **found}


def export(db, identifier='all', *, format='bricklink', kind='parts'):
    """`dict(content, summary, filename, mimetype)`: the live wishes of one list (or all active lists) as a BrickLink wanted list (XML) or a
    Rebrickable CSV of parts or sets. `summary` says how many rows were exported, which were left out and why, and which limits were dropped."""
    if format not in ('bricklink', 'rebrickable') or kind not in ('sets', 'parts'):
        raise ValueError('Choose an export format and kind')
    if identifier != 'all':
        require(db, identifier)
    rows = [dict(r) for r in db.execute('''SELECT w.*,l.bricklink_id AS list_bricklink_id,i.name,i.born_key FROM wish w
        JOIN wishlist l ON l.id=w.wishlist_id JOIN item i ON i.id=w.item_id WHERE w.archived_at IS NULL AND l.archived_at IS NULL
        AND (?='all' OR w.wishlist_id=?) ORDER BY l.sort,l.id,w.kind,i.born_key,i.id,w.color_id,w.id''', (identifier, identifier))]
    from . import wish_progress
    wish_progress.annotate(db, rows)
    summary = dict(exported=0, omitted=[], notes=[])
    currency = configured_currency(db)
    labels = items.labels(db, {(r['item_id'], r['color_id']) for r in rows})

    def named(r):
        label = labels.get((r['item_id'], r['color_id']))
        return (label.number if label and label.number else None) or r['name']
    if format == 'bricklink':
        root = ET.Element('INVENTORY')
        for r in rows:
            label = labels.get((r['item_id'], r['color_id']))
            key = label.bricklink if label else None
            if key is None:
                summary['omitted'].append(dict(id=r['id'], item_no=named(r), reason='No BrickLink number'))
                continue
            if r['kind'] == 'part' and key[2] is None:
                summary['omitted'].append(dict(id=r['id'], item_no=named(r), reason='No BrickLink colour'))
                continue
            item = ET.SubElement(root, 'ITEM')
            fields = dict(ITEMTYPE=key[0], ITEMID=key[1])
            if r['color_id'] is not None:
                fields['COLOR'] = str(key[2])
            fields['MINQTY'] = str(r['quantity'])
            if r['max_price'] is not None:
                try:
                    positive = Decimal(r['max_price']) > 0
                except InvalidOperation:
                    positive = False
                if (r['max_price_currency'] or '').upper() == currency.upper() and positive:
                    fields['MAXPRICE'] = r['max_price']
                else:
                    summary['notes'].append(dict(id=r['id'], item_no=named(r), reason='MAXPRICE omitted: currency differs or limit is zero'))
            if r['condition'] in ('new', 'used'):
                fields['CONDITION'] = {'new': 'N', 'used': 'U'}[r['condition']]
            if r.get('qty_filled'):
                fields['QTYFILLED'] = str(min(r['qty_filled'], r['quantity']))
            fields.update(REMARKS=r['note'] or '', NOTIFY='N')
            if r['list_bricklink_id']:
                fields['WANTEDLISTID'] = r['list_bricklink_id']
            for name, value in fields.items():
                ET.SubElement(item, name).text = value
            summary['exported'] += 1
        content = ET.tostring(root, encoding='unicode')
    else:
        wanted = 'set' if kind == 'sets' else 'part'
        numbers = _rebrickable_numbers(db, {r['item_id'] for r in rows if r['kind'] == wanted})
        colours = _rebrickable_colours(db, {r['color_id'] for r in rows if r['kind'] == wanted})
        stream = io.StringIO(newline='')
        from . import csv_safe
        writer = csv_safe.writer(stream)
        writer.writerow(['Set Number', 'Quantity'] if kind == 'sets' else ['Part', 'Color', 'Quantity'])
        for r in rows:
            if r['kind'] != wanted:
                summary['omitted'].append(dict(id=r['id'], item_no=named(r), reason='Outside selected export kind'))
                continue
            number, colour = numbers.get(r['item_id'], set()), colours.get(r['color_id'], set())
            if len(number) != 1 or kind == 'parts' and len(colour) != 1:
                summary['omitted'].append(dict(id=r['id'], item_no=named(r), reason='Missing or ambiguous Rebrickable mapping'))
                continue
            writer.writerow([next(iter(number)), r['quantity']] if kind == 'sets' else [next(iter(number)), next(iter(colour)), r['quantity']])
            summary['exported'] += 1
        content = stream.getvalue()
    return dict(content=content, summary=summary, filename='wishlist.' + ('xml' if format == 'bricklink' else 'csv'),
                mimetype='application/xml' if format == 'bricklink' else 'text/csv')
