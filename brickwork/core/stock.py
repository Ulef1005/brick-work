"""Loose-stock receipts; callers own the transaction and write lock."""
from uuid import uuid4
from collections import defaultdict
import json

from .admin import audit, redact
from .sources.base import now


MERGE_FIELDS = ('item_type', 'item_no', 'color_id', 'condition', 'lot_id', 'storage_id')


def merge_key(row):
    return tuple(row[field] for field in MERGE_FIELDS)


def merge_edited(db, before, after):
    """Merge changed keys in bulk; return every original row for the receipt.

    Prefer an unedited destination, then the lowest id, as add_loose does.
    Archived source rows retain their metadata, flags and attachments.
    """
    originals = {r['id']: r for r in before}
    changed = [r['id'] for r in after if r['item_type'] != 'M' and
               merge_key(r) != merge_key(originals[r['id']])]
    if not changed:
        return before
    candidates = [dict(r) for r in db.execute(
        'WITH keys AS (SELECT DISTINCT ' + ','.join(MERGE_FIELDS) +
        ' FROM loose_stock WHERE id IN (SELECT value FROM json_each(?))) '
        'SELECT s.* FROM loose_stock s JOIN keys e ON ' +
        ' AND '.join('s.'+f+' IS e.'+f for f in MERGE_FIELDS) +
        " WHERE s.archived_at IS NULL AND s.item_type!='M' ORDER BY s.id",
        (json.dumps(changed),))]
    groups = defaultdict(list)
    for row in candidates:
        groups[merge_key(row)].append(row)
    updates = []
    stamp = now().isoformat()
    edited = set(originals)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        destination = min(rows, key=lambda r: (r['id'] in edited, r['id']))
        if any(r['quantity'] is None for r in rows):
            raise ValueError('Stock quantity is not recorded · cannot merge these rows')
        total = sum(r['quantity'] for r in rows)
        defects = {field: sum(r[field] or 0 for r in rows)
                   if any(r[field] is not None for r in rows) else None
                   for field in ('missing', 'damaged')}
        checked = 1 if all(r['checked'] for r in rows) else destination['checked']
        for row in rows:
            originals.setdefault(row['id'], row)
            updates.append(dict(row,
                                missing=defects['missing'] if row is destination else row['missing'],
                                damaged=defects['damaged'] if row is destination else row['damaged'],
                                checked=checked if row is destination else row['checked'],
                                quantity=total
                                if row is destination else row['quantity'],
                                archived_at=None if row is destination else stamp, updated_at=stamp))
    if updates:
        db.execute('''UPDATE loose_stock SET quantity=json_extract(j.value,'$.quantity'),
            missing=json_extract(j.value,'$.missing'),damaged=json_extract(j.value,'$.damaged'),
            checked=json_extract(j.value,'$.checked'),
            archived_at=json_extract(j.value,'$.archived_at'),updated_at=json_extract(j.value,'$.updated_at')
            FROM json_each(?) j WHERE loose_stock.id=json_extract(j.value,'$.id')''',
            (json.dumps(updates),))
        audit_rows(db, [(originals[r['id']], r) for r in updates], 'merge')
    return sorted(originals.values(), key=lambda r: r['id'])


def audit_rows(db, pairs, action):
    """One event per row, one SQL statement regardless of batch size."""
    from .audit_bundle import CAPTURE
    if CAPTURE.get() is not None:
        for old,new in pairs: audit(db,'stock:'+old['id'],action,old,new)
        return
    payload = [dict(entity='stock:'+old['id'], old=redact(json.dumps(old)),
                    new=redact(json.dumps(new))) for old, new in pairs]
    if payload:
        db.execute('''INSERT INTO events(entity,field,old_value,new_value,at,via)
            SELECT json_extract(value,'$.entity'),?,json_extract(value,'$.old'),
            json_extract(value,'$.new'),?,'app' FROM json_each(?)''',
            (action, now().isoformat(), json.dumps(payload)))


def add_loose(db, changes, *, item_type, item_no, color_id, quantity,
              condition, lot_id=None, storage_id=None, note=None):
    """Return (stock id, created), recording the exact quantity and snapshots."""
    if not db.in_transaction:
        raise ValueError('Loose stock must be added in a transaction')
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError('Choose a positive whole quantity')
    old = None
    if item_type != 'M':
        row = db.execute('SELECT * FROM loose_stock WHERE archived_at IS NULL '
                         'AND ' + ' AND '.join(f + ' IS ?' for f in MERGE_FIELDS) +
                         ' ORDER BY id LIMIT 1',
                         (item_type, item_no, color_id, condition, lot_id, storage_id)).fetchone()
        old = dict(row) if row else None
    stamp = now().isoformat()
    identifier = old['id'] if old else uuid4().hex
    if old:
        db.execute('UPDATE loose_stock SET quantity=?,updated_at=? WHERE id=?',
                   (old['quantity'] + quantity, stamp, identifier))
    else:
        db.execute('INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,'
                   'lot_id,storage_id,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier, item_type, item_no, color_id, quantity, condition,
                    lot_id, storage_id, note, stamp, stamp))
    new = dict(db.execute('SELECT * FROM loose_stock WHERE id=?', (identifier,)).fetchone())
    changes.append(dict(table='loose_stock', key={'id': identifier}, old=[old] if old else [],
                        new=[new], created=old is None, quantity=quantity))
    audit(db, 'stock:' + identifier, 'increased' if old else 'created', old, new)
    return identifier, old is None


def undo_loose(db, changes):
    """Reverse in receipt order, refusing any changed destination atomically."""
    for change in reversed(changes):
        identifier = change['key']['id']
        row = db.execute('SELECT * FROM loose_stock WHERE id=?', (identifier,)).fetchone()
        current = dict(row) if row else None
        if [current] != change['new']:
            raise ValueError('Stock changed since this save · undo the later save first')
        if change['old']:
            old = change['old'][0]
            db.execute('UPDATE loose_stock SET quantity=?,updated_at=? WHERE id=?',
                       (current['quantity'] - change['quantity'], old['updated_at'], identifier))
        else:
            stamp = now().isoformat()
            db.execute('UPDATE loose_stock SET archived_at=?,updated_at=? WHERE id=?',
                       (stamp, stamp, identifier))
        new = dict(db.execute('SELECT * FROM loose_stock WHERE id=?', (identifier,)).fetchone())
        audit(db, 'stock:' + identifier, 'undo', current, new)
