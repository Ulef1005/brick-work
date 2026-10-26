"""Named wishlist receipts and portable exports. BrickLink identities stay canonical."""
import csv
import io
import json
from collections import defaultdict
from decimal import Decimal
from uuid import uuid4
from xml.etree import ElementTree as ET

from . import collection, errors
from .currency import configured_currency
from .sources.base import now
from .transaction import transaction

DEFAULT = 'default'


def listing(db, *, archived=False):
    return [dict(r) for r in db.execute('''SELECT l.*,count(w.id) AS count FROM wishlists l
        LEFT JOIN wishlist w ON w.list_id=l.id AND w.archived_at IS NULL
        WHERE (? OR l.archived_at IS NULL) GROUP BY l.id ORDER BY l.sort,l.name,l.id''', (archived,))]


def require(db, identifier=DEFAULT):
    row = db.execute('SELECT * FROM wishlists WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone()
    if not row:
        raise ValueError('Choose an active wishlist')
    return dict(row)


def save(db, identifier=None, data=None, *, action='save'):
    data = data or {}
    with transaction(db):
        before = collection.snapshot(db, 'wishlists', [identifier]) if identifier else []
        if identifier and not before:
            raise ValueError('Wishlist is unavailable')
        stamp = now().isoformat()
        wishes = []
        if action in ('archive', 'restore'):
            restoring = action == 'restore'
            if (before[0]['archived_at'] is None) == restoring:
                raise ValueError('Wishlist is already ' + ('active' if restoring else 'archived'))
            wishes = [dict(r) for r in db.execute('SELECT * FROM wishlist WHERE list_id=? AND archived_at IS ?',
                       (identifier, before[0]['archived_at'] if restoring else None))]
            if restoring:
                for r in wishes:
                    collection.wish_collision(db, 'wishlist', dict(r, archived_at=None))
            db.execute('UPDATE wishlists SET archived_at=? WHERE id=?', (None if restoring else stamp, identifier))
            db.execute('UPDATE wishlist SET archived_at=? WHERE id IN (SELECT value FROM json_each(?))',
                       (None if restoring else stamp, json.dumps([r['id'] for r in wishes])))
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
            if bl_id and db.execute('SELECT 1 FROM wishlists WHERE bricklink_id=? AND id!=?', (bl_id, identifier or '')).fetchone():
                raise errors.Conflict('BrickLink wanted list id is already linked')
            if before:
                db.execute('UPDATE wishlists SET name=?,note=?,sort=?,bricklink_id=? WHERE id=?', (name, note, sort, bl_id, identifier))
            else:
                identifier = uuid4().hex
                db.execute('INSERT INTO wishlists(id,name,note,sort,created_at,bricklink_id) VALUES(?,?,?,?,?,?)',
                           (identifier, name, note, sort, stamp, bl_id))
        changes = [('wishlists', before, collection.snapshot(db, 'wishlists', [identifier]))]
        if wishes:
            changes.append(('wishlist', wishes, collection.snapshot(db, 'wishlist', [r['id'] for r in wishes])))
        event = collection.receipt(db, changes, 'save')
        return identifier, event


def transfer(db, ids, target, *, copy=False):
    if not isinstance(ids, list) or not ids or len(ids) > 500 or len(set(ids)) != len(ids):
        raise ValueError('Choose up to 500 wishes once each')
    with transaction(db):
        require(db, target)
        before = collection.snapshot(db, 'wishlist', ids)
        if len(before) != len(ids) or any(r['archived_at'] for r in before):
            raise ValueError('Wish is unavailable')
        keys = [(r['item_type'], r['item_no'], r['color_id']) for r in before]
        if len(set(keys)) != len(keys):
            raise errors.Conflict('Selected wishes repeat an item and colour')
        current = {(r['item_type'], r['item_no'], r['color_id']): r['id'] for r in db.execute(
            'SELECT * FROM wishlist WHERE list_id=? AND archived_at IS NULL', (target,))}
        for r in before:
            existing = current.get((r['item_type'], r['item_no'], r['color_id']))
            if existing is not None and (copy or existing != r['id']):
                raise errors.Conflict('An item and colour already exists in the target list')
        stamp = now().isoformat()
        if copy:
            new_ids = []
            for r in before:
                values = {k: v for k, v in r.items() if k != 'id'}
                values.update(list_id=target, added_at=stamp, updated_at=stamp)
                new_ids.append(db.execute('INSERT INTO wishlist(' + ','.join(values) + ') VALUES(' + ','.join('?' for _ in values) + ')', tuple(values.values())).lastrowid)
            changes = [('wishlist', [], collection.snapshot(db, 'wishlist', new_ids))]
            flags = defaultdict(list)
            for flag in db.execute("SELECT * FROM item_flags WHERE entity_type='wishlist' AND CAST(entity_id AS INTEGER) IN (SELECT value FROM json_each(?)) ORDER BY flag_id", (json.dumps(ids),)):
                flags[int(flag['entity_id'])].append(flag['flag_id'])
            for source, destination in zip(before, new_ids):
                copied = [dict(entity_type='wishlist', entity_id=str(destination), flag_id=flag) for flag in flags[source['id']]]
                if copied:
                    db.executemany('INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES(:entity_type,:entity_id,:flag_id)', copied)
                    changes.append(('item_flags', [], copied))
            return collection.receipt(db, changes, 'save')
        db.execute('UPDATE wishlist SET list_id=?,updated_at=? WHERE id IN (SELECT value FROM json_each(?))', (target, stamp, json.dumps(ids)))
        return collection.receipt(db, [('wishlist', before, collection.snapshot(db, 'wishlist', ids))], 'save')


def export(db, identifier='all', *, format='bricklink', kind='parts'):
    if format not in ('bricklink', 'rebrickable') or kind not in ('sets', 'parts'):
        raise ValueError('Choose an export format and kind')
    if identifier != 'all':
        require(db, identifier)
    rows = [dict(r) for r in db.execute('''SELECT w.*,l.bricklink_id FROM wishlist w
        JOIN wishlists l ON l.id=w.list_id WHERE w.archived_at IS NULL AND l.archived_at IS NULL
        AND (?='all' OR w.list_id=?) ORDER BY l.sort,l.id,w.item_type,w.item_no,w.color_id,w.id''', (identifier, identifier))]
    from . import wish_progress
    wish_progress.annotate(db, rows)
    summary = dict(exported=0, omitted=[], notes=[])
    currency = configured_currency(db)
    if format == 'bricklink':
        root = ET.Element('INVENTORY')
        for r in rows:
            if r['item_type'] not in 'SPMIOGBC':
                summary['omitted'].append(dict(id=r['id'], item_no=r['item_no'], reason='Unresolved identity'))
                continue
            item = ET.SubElement(root, 'ITEM')
            fields = dict(ITEMTYPE=r['item_type'], ITEMID=r['item_no'])
            if r['color_id'] is not None: fields['COLOR'] = str(r['color_id'])
            fields['MINQTY'] = str(r['quantity'])
            if r['max_price'] is not None:
                if (r['max_price_currency'] or '').upper() == currency.upper() and Decimal(r['max_price']) > 0:
                    fields['MAXPRICE'] = r['max_price']
                else:
                    summary['notes'].append(dict(id=r['id'], item_no=r['item_no'], reason='MAXPRICE omitted: currency differs or limit is zero'))
            if r['condition'] in ('new', 'used'): fields['CONDITION'] = {'new': 'N', 'used': 'U'}[r['condition']]
            if r.get('qty_filled'):
                fields['QTYFILLED'] = str(min(r['qty_filled'], r['quantity']))
            fields.update(REMARKS=r['note'] or '', NOTIFY='N')
            if r['bricklink_id']: fields['WANTEDLISTID'] = r['bricklink_id']
            for key, value in fields.items(): ET.SubElement(item, key).text = value
            summary['exported'] += 1
        content = ET.tostring(root, encoding='unicode')
    else:
        mappings = defaultdict(set)
        for m in db.execute("SELECT * FROM id_match WHERE source='rebrickable' AND status IN ('matched','manual','inferred')"):
            key = ('color', m['color_id']) if m['kind'] == 'color' else (m['item_type'], m['item_no'])
            mappings[key].add(m['source_id'])
        stream = io.StringIO(newline='')
        from . import csv_safe
        writer = csv_safe.writer(stream)
        writer.writerow(['Set Number', 'Quantity'] if kind == 'sets' else ['Part', 'Color', 'Quantity'])
        for r in rows:
            if r['item_type'] != ('S' if kind == 'sets' else 'P'):
                summary['omitted'].append(dict(id=r['id'], item_no=r['item_no'], reason='Outside selected export kind'))
                continue
            numbers = mappings[r['item_type'], r['item_no']]
            colors = mappings['color', r['color_id']]
            if len(numbers) != 1 or kind == 'parts' and len(colors) != 1:
                summary['omitted'].append(dict(id=r['id'], item_no=r['item_no'], reason='Missing or ambiguous Rebrickable mapping'))
                continue
            writer.writerow([next(iter(numbers)), r['quantity']] if kind == 'sets' else [next(iter(numbers)), next(iter(colors)), r['quantity']])
            summary['exported'] += 1
        content = stream.getvalue()
    return dict(content=content, summary=summary, filename='wishlist.' + ('xml' if format == 'bricklink' else 'csv'),
                mimetype='application/xml' if format == 'bricklink' else 'text/csv')
