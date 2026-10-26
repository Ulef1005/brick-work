"""Atomic order and storage receipts on the v3 store."""
from .transaction import transaction
import json
import re
from uuid import uuid4

from .admin import audit
from . import workbench as w


ENTITY = 'bw_ledger'


def finish(db, changes, action, **context):
    merged = {}
    for change in changes:
        key = change['table'], json.dumps(change['key'], sort_keys=True)
        if key in merged:
            merged[key]['new'] = change['new']
            if 'quantity' in change:
                merged[key]['quantity'] = merged[key].get('quantity', 0) + change['quantity']
        else:
            merged[key] = dict(change)
    audit(db, ENTITY, 'receipt', None, dict(action=action, changes=list(merged.values()), **context))
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def insert(db, changes, table, values):
    cursor = db.execute('INSERT INTO '+table+'('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')', tuple(values.values()))
    key = {'line_id': values['line_id']} if table == 'line_receipts' else {'id': values.get('id', cursor.lastrowid)}
    new = w.snapshot(db, table, key)
    changes.append(dict(table=table, key=key, old=[], new=new))
    audit(db, ENTITY+':'+table, 'change', None, new)
    return key.get('id', key.get('line_id'))


def history(db, *, actions=None, limit=200, **context):
    """Filter receipt context in SQLite before decoding the bounded web history."""
    from .undo import undone_sql, undoable_sql
    predicates, parameters = [], []
    for key, value in context.items():
        if not re.fullmatch(r'[a-z_]+', key):
            raise ValueError('Invalid history context')
        predicates.append("json_extract(receipt, ?) IS ?")
        parameters.extend(('$.'+key, value))
    if actions:
        predicates.append("json_extract(receipt, '$.action') IN ("+','.join('?' for _ in actions)+')')
        parameters.extend(actions)
    where = ' AND '.join(predicates) or '1'
    sql = f"""WITH receipts AS (
        SELECT e.*, e.new_value AS receipt, 1 AS receipt_count
        FROM events e WHERE e.entity='bw_ledger' AND e.field='receipt' AND json_valid(e.new_value)
        UNION ALL
        SELECT e.*, json_extract(r.value,'$.new_value') AS receipt,
            json_array_length(e.new_value,'$.receipts') AS receipt_count
        FROM events e, json_each(CASE WHEN json_valid(e.new_value) THEN e.new_value END,'$.receipts') r
        WHERE e.entity='bw_api' AND (e.field='receipt' OR e.field LIKE 'op:%')
          AND json_extract(r.value,'$.entity')='bw_ledger'
          AND json_extract(r.value,'$.field')='receipt'
    ) SELECT e.*, {undone_sql()} AS undone, {undoable_sql()} AS undo_available
      FROM receipts e WHERE json_valid(receipt) AND {where} ORDER BY e.id DESC"""
    if limit is not None:
        sql += ' LIMIT ?'
        parameters.append(limit)
    return [dict(event, receipt=json.loads(event['receipt']), undone=bool(event['undone']),
                 undo_available=bool(event['undo_available']) and not event['undone'])
            for event in db.execute(sql, parameters)]


def undo_history(db, event_id):
    """Web history uses the API dispatcher, including bundled receipts and guards."""
    from . import undo as undo_module
    with transaction(db):
        result = undo_module.undo_event(db, event_id)
        if result['already_undone']:
            raise ValueError('This save has already been undone')


def undo(db, event_id, *, receipt=None):
    with transaction(db):
        event = receipt if receipt is not None else db.execute("SELECT * FROM events WHERE id=? AND entity=? AND field='receipt'", (event_id, ENTITY)).fetchone()
        if not event:
            raise ValueError('Save is unavailable')
        # The dispatcher checks repeat Undo once per operation. Bundled ledger
        # receipts share that operation id and must each be reversed.
        if receipt is None and db.execute("SELECT 1 FROM events WHERE entity=? AND field='undo' AND new_value=?", (ENTITY, json.dumps(int(event_id)))).fetchone():
            return
        receipt = json.loads(event['new_value'])
        for guard in receipt.get('guards',[]):
            if w.snapshot(db,guard['table'],guard['key'])!=guard['value']:
                raise ValueError('The copy status changed after saving · review it before undoing')
        changes = receipt['changes']
        for c in changes:
            if w.snapshot(db, c['table'], c['key']) != c['new']:
                raise ValueError('This item changed after saving · undo the later save first')
        restored_locations = {c['key']['id'] for c in changes if c['table'] == 'storages'
                              and c['old'] and c['old'][0].get('archived_at') is None}
        # A moved lot that has since gained live parts in its destination would be split by Undo.
        receipt_stock = {c['key']['id'] for c in changes if c['table'] == 'loose_stock'}
        for c in changes:
            if c['table'] == 'lots' and c['old'] and c['new'] and c['old'][0].get('storage_id') != c['new'][0].get('storage_id'):
                gained = [r[0] for r in db.execute('SELECT id FROM loose_stock WHERE archived_at IS NULL AND lot_id=? AND storage_id IS ?', (c['key']['id'], c['new'][0].get('storage_id')))
                          if r[0] not in receipt_stock]
                if gained:
                    raise ValueError('This lot has gained parts in its new storage · move them out before undoing the move')
        for c in changes:
            if c['table'] == 'storages' and not c['old'] and (storage_contents(db, c['key']['id']) or db.execute(
                    'SELECT 1 FROM storages WHERE parent_id=? AND archived_at IS NULL', (c['key']['id'],)).fetchone()):
                raise ValueError('Move the items before undoing location creation')
            if c['table'] in ('copies', 'loose_stock', 'lots') and c['old']:
                destination = c['old'][0].get('storage_id')
                if destination and destination not in restored_locations:
                    require_storage(db, destination)
        # Receipt quantities cannot be restored below live allocations, even when
        # the allocation itself did not edit the receipt row.
        for c in changes:
            if c['table'] == 'line_receipts':
                live = db.execute("SELECT coalesce(sum(qty),0) FROM allocations WHERE line_id=? AND state IN ('applied','pending','conflict','undoing')", (c['key']['line_id'],)).fetchone()[0]
                if live > (c['old'][0]['received'] if c['old'] else 0):
                    raise ValueError('Undo the allocations before the received count')
        documents={c['key']['id'] for c in changes if c['table']=='order_documents' and (not c['old'] or c['old'][0]['phase']!='saved')}
        if documents:
            placeholders=','.join('?' for _ in documents)
            if db.execute("SELECT 1 FROM allocations a JOIN order_lines l ON l.id=a.line_id WHERE l.document_id IN ("+placeholders+") AND a.state IN ('applied','pending','conflict','undoing')",tuple(documents)).fetchone():
                raise ValueError('Undo allocations before undoing the document')
            if db.execute("SELECT 1 FROM line_receipts r JOIN order_lines l ON l.id=r.line_id WHERE l.document_id IN ("+placeholders+") AND r.received>0",tuple(documents)).fetchone():
                raise ValueError('Undo received counts before undoing the document')
            if db.execute("SELECT 1 FROM order_lines p JOIN order_lines l ON l.id=p.paired_line_id JOIN order_documents d ON d.id=p.document_id WHERE l.document_id IN ("+placeholders+") AND d.phase='saved' AND p.document_id NOT IN ("+placeholders+")",(*documents,*documents)).fetchone():
                raise ValueError('Undo the paired document first')
        for c in reversed(changes):
            table, key = c['table'], c['key']
            clause = ' AND '.join(k+' IS ?' for k in key)
            if c['old']:
                old = c['old'][0]
                db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in old)+' WHERE '+clause, (*old.values(), *key.values())) if c['new'] else db.execute('INSERT INTO '+table+'('+','.join(old)+') VALUES('+','.join('?' for _ in old)+')',tuple(old.values()))
            elif table == 'storages':
                db.execute('UPDATE storages SET archived_at=? WHERE '+clause,(w.stamp(),*key.values()))
            elif table == 'loose_stock':
                db.execute('UPDATE loose_stock SET archived_at=?,updated_at=? WHERE '+clause,(w.stamp(),w.stamp(),*key.values()))
            elif table == 'allocations':
                db.execute("UPDATE allocations SET state='undone',undone_at=? WHERE "+clause,(w.stamp(),*key.values()))
            elif table == 'item_flags':
                db.execute('DELETE FROM item_flags WHERE '+clause,tuple(key.values()))
            elif table == 'line_receipts':
                db.execute('UPDATE line_receipts SET received=0,updated_at=? WHERE '+clause,(w.stamp(),*key.values()))
            elif table == 'order_documents':
                db.execute("UPDATE order_documents SET phase='undone',updated_at=? WHERE "+clause,(w.stamp(),*key.values()))
            # Imported lines, catalogue identities, orders and receipt logs remain
            # as provenance; undo deactivates their document, never erases it.
            audit(db, ENTITY+':'+table, 'undo', c['new'], w.snapshot(db,table,key))
        audit(db, ENTITY, 'undo', receipt, int(event_id))


def visuals(db, rows):
    """Decorate a list using a constant number of queries."""
    from .add import decorate_many
    return decorate_many(db, rows)


def storages(db):
    """Per-storage counts. ``part_lots`` is lots plus loose parts that are not inside a lot kept in the same storage.

    Figures are minifigures and figure placeholders; ``other`` is instructions, boxes, gear, books and catalogues.
    """
    return [dict(r) for r in db.execute('''WITH c AS (SELECT storage_id,count(*) AS copies FROM copies WHERE archived_at IS NULL GROUP BY storage_id),
      s AS (SELECT t.storage_id,count(*) AS entries,coalesce(sum(t.quantity),0) AS pieces,
        coalesce(sum(t.item_type IN ('M','?')),0) AS figures,
        coalesce(sum(t.item_type='P' AND x.id IS NULL),0) AS loose_parts,
        coalesce(sum(t.item_type IN ('I','O','G','B','C')),0) AS other
        FROM loose_stock t LEFT JOIN lots x ON x.id=t.lot_id AND x.archived_at IS NULL AND x.storage_id IS t.storage_id
        WHERE t.archived_at IS NULL GROUP BY t.storage_id),
      l AS (SELECT storage_id,count(*) AS lots FROM lots WHERE archived_at IS NULL GROUP BY storage_id)
      SELECT p.id,p.name,p.type,p.parent_id,p.note,(SELECT name FROM storages q WHERE q.id=p.parent_id) AS parent_name,coalesce(c.copies,0) AS copies,coalesce(s.entries,0) AS entries,coalesce(s.pieces,0) AS pieces,coalesce(l.lots,0) AS lots,
      coalesce(s.figures,0) AS figures,coalesce(s.loose_parts,0)+coalesce(l.lots,0) AS part_lots,coalesce(s.other,0) AS other
      FROM (SELECT id,name,type,parent_id,note FROM storages WHERE archived_at IS NULL UNION ALL SELECT NULL,'Not stored',NULL,NULL,NULL) p
      LEFT JOIN c ON c.storage_id IS p.id LEFT JOIN s ON s.storage_id IS p.id LEFT JOIN l ON l.storage_id IS p.id ORDER BY p.id IS NULL,p.name''')]


def storage_detail(db, identifier, rows=None):
    """``rows`` are already-loaded ``storages(db)``, so a page does not run that query twice."""
    location = next((r for r in (storages(db) if rows is None else rows) if r['id'] == identifier), None)
    if location is None:
        raise ValueError('Location is unavailable')
    rows = [dict(r) for r in db.execute('''SELECT 'copy' AS entity,c.id,c.item_type,c.set_no AS item_no,NULL AS color_id,
      i.name,1 AS quantity,c.completeness FROM copies c JOIN items i ON i.item_type=c.item_type AND i.item_no=c.set_no
      WHERE c.archived_at IS NULL AND c.storage_id IS ? UNION ALL
      SELECT 'stock',s.id,s.item_type,s.item_no,s.color_id,i.name,s.quantity,NULL FROM loose_stock s
      JOIN items i ON i.item_type=s.item_type AND i.item_no=s.item_no WHERE s.archived_at IS NULL AND s.storage_id IS ?''',(identifier,identifier))]
    return dict(location=location, rows=visuals(db,rows))


def storage_view(db, identifier, rows=None):
    """The Storage page projection: ``storage_detail`` plus what 12c groups by.

    Adds the copy condition, the lot a part sits in (only a lot kept in this same storage) and the lots
    themselves, and splits the rows into sets, figures (M and ?), part lots (lots, then P rows) and other
    (I, O, G, B, C). A lot's size counts only the parts in its own storage, which is what a move carries.
    The API keeps reading ``storage_detail`` unchanged.
    """
    detail = storage_detail(db, identifier, rows)
    extra = {(e, i): (c, lot) for e, i, c, lot in db.execute('''SELECT 'copy',id,condition,NULL FROM copies WHERE archived_at IS NULL AND storage_id IS ? UNION ALL
        SELECT 'stock',s.id,s.condition,x.id FROM loose_stock s LEFT JOIN lots x ON x.id=s.lot_id AND x.archived_at IS NULL AND x.storage_id IS s.storage_id
        WHERE s.archived_at IS NULL AND s.storage_id IS ?''', (identifier, identifier))}
    lots = [dict(r, entity='lot', item_type='L', item_no=None) for r in db.execute('''SELECT l.id,l.name,coalesce(s.entries,0) AS entries,coalesce(s.quantity,0) AS quantity
        FROM lots l LEFT JOIN (SELECT t.lot_id,count(*) AS entries,sum(t.quantity) AS quantity FROM loose_stock t JOIN lots x ON x.id=t.lot_id
        WHERE t.archived_at IS NULL AND t.storage_id IS x.storage_id GROUP BY t.lot_id) s ON s.lot_id=l.id
        WHERE l.archived_at IS NULL AND l.storage_id IS ? ORDER BY l.name,l.id''', (identifier,))]
    for r in detail['rows']:
        r['condition'], r['lot'] = extra.get((r['entity'], r['id']), (None, None))
    rows = detail['rows']
    stock = [r for r in rows if r['entity'] == 'stock']
    detail['sets'] = [r for r in rows if r['entity'] == 'copy']
    detail['figures'] = [r for r in stock if r['item_type'] in ('M', '?')]
    detail['part_lots'] = lots + [r for r in stock if r['item_type'] == 'P']
    detail['other'] = [r for r in stock if r['item_type'] not in ('M', '?', 'P')]
    detail['total'] = len(detail['sets']) + len(detail['figures']) + len(detail['part_lots']) + len(detail['other'])
    return detail


STORAGE_TYPES = ('Box', 'Shelf', 'Drawer', 'Bin', 'Bag', 'Case', 'Cabinet', 'Room', 'Other')
PLACE_KINDS = ('BrickLink store', 'Online shop', 'Shop', 'Market', 'Fair', 'Private', 'Other')
KEEP = object()


def storage_save(db, identifier, name, *, type=KEEP, parent_id=KEEP, note=KEEP):
    """Create or change a storage. #46: type (STORAGE_TYPES or empty), parent_id (another live storage,
    never itself or one inside it) and note; fields left at KEEP stay as they are."""
    name = str(name).strip()
    if not name or len(name) > 160:
        raise ValueError('Use a location name between 1 and 160 characters')
    fields = dict(name=name)
    if type is not KEEP:
        type = (type or '').strip() or None
        if type is not None and type not in STORAGE_TYPES:
            raise ValueError('Choose a storage type: ' + ', '.join(STORAGE_TYPES))
        fields['type'] = type
    if note is not KEEP:
        note = (note or '').strip() or None
        if note is not None and len(note) > 500:
            raise ValueError('Keep the note under 500 characters')
        fields['note'] = note
    with transaction(db):
        if parent_id is not KEEP:
            parent_id = parent_id or None
            if parent_id is not None:
                require_storage(db, parent_id)
                # Walk up from the new parent: reaching this storage would make a loop.
                seen, current = set(), parent_id
                while current is not None and current not in seen:
                    if current == identifier:
                        raise ValueError('A storage cannot sit inside itself or a storage inside it')
                    seen.add(current)
                    row = db.execute('SELECT parent_id FROM storages WHERE id=?', (current,)).fetchone()
                    current = row[0] if row else None
            fields['parent_id'] = parent_id
        changes = []
        if identifier:
            require_storage(db, identifier)
            w.record(db,changes,'storages',{'id':identifier},lambda:db.execute(
                'UPDATE storages SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),identifier)))
        else:
            identifier = uuid4().hex
            insert(db,changes,'storages',dict(id=identifier,**fields))
        return identifier, finish(db,changes,'storage',storage_id=identifier)


def place_kind(db, identifier, kind):
    """#46: what kind of place a purchase location is; one receipt, Undo in History."""
    kind = (kind or '').strip() or None
    if kind is not None and kind not in PLACE_KINDS:
        raise ValueError('Choose a kind: ' + ', '.join(PLACE_KINDS))
    with transaction(db):
        if not db.execute('SELECT 1 FROM purchase_locations WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone():
            raise ValueError('Purchase location is unavailable')
        changes = []
        w.record(db,changes,'purchase_locations',{'id':identifier},lambda:db.execute('UPDATE purchase_locations SET kind=? WHERE id=?',(kind,identifier)))
        return finish(db,changes,'place')


def move(db, identifier, selections):
    if not selections or len(selections)>1000:
        raise ValueError('Choose up to 1000 items to move')
    with transaction(db):
        if identifier is not None:
            require_storage(db, identifier)
        changes = []
        # Read the carried parts before any write moves their lot; they count against the same limit.
        lots = sorted({s['id'] for s in selections if s['entity']=='lot'})
        done = {s['id'] for s in selections if s['entity']=='stock'}
        carried = [r[0] for r in db.execute('SELECT s.id FROM loose_stock s JOIN lots l ON l.id=s.lot_id WHERE s.archived_at IS NULL AND s.storage_id IS l.storage_id AND l.id IN ('+','.join('?' for _ in lots)+') ORDER BY s.id',lots)] if lots else []
        carried = [k for k in carried if k not in done]
        if len(selections)+len(carried)>1000:
            if carried:
                raise ValueError(('This lot holds ' if len(lots)==1 else 'These lots hold ')+str(len(carried))+' parts · move it in parts or archive the storage')
            raise ValueError('Choose up to 1000 items to move')
        # Batch-load selected records; unknown or archived ids reject the whole move.
        for entity, table in [('copy','copies'),('stock','loose_stock'),('lot','lots')]:
            ids = sorted({s['id'] for s in selections if s['entity']==entity})
            if not ids:
                continue
            rows = {r['id']:r for r in db.execute('SELECT * FROM '+table+' WHERE archived_at IS NULL AND id IN ('+','.join('?' for _ in ids)+')',ids)}
            if len(rows)!=len(ids):
                raise ValueError('An item changed · review this location again')
            for key in ids:
                w.record(db,changes,table,{'id':key},lambda k=key,t=table:db.execute('UPDATE '+t+' SET storage_id=?'+(',updated_at=?' if t!='lots' else '')+' WHERE id=?',(identifier,*((w.stamp(),) if t!='lots' else ()),k)))
        if any(s['entity'] not in ('copy','stock','lot') for s in selections):
            raise ValueError('Choose copies, loose stock or lots')
        # A lot carries its parts: stock that sits in the lot's own storage follows it in the same receipt, so one Undo restores both.
        for key in carried:
            w.record(db,changes,'loose_stock',{'id':key},lambda k=key:db.execute('UPDATE loose_stock SET storage_id=?,updated_at=? WHERE id=?',(identifier,w.stamp(),k)))
        return finish(db,changes,'move',storage_id=identifier)


def require_storage(db, identifier):
    if not db.execute('SELECT 1 FROM storages WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone():
        raise ValueError('Location is unavailable')


def storage_contents(db, identifier):
    """Load live references in three queries, including a lot's own location."""
    return [(table, dict(row)) for table in ('copies', 'loose_stock', 'lots')
            for row in db.execute('SELECT * FROM '+table+' WHERE storage_id=? AND archived_at IS NULL', (identifier,))]


def storage_archive(db, identifier, *, move_to_unstored=False):
    """Archive a location and optionally move its live contents in one receipt."""
    with transaction(db):
        require_storage(db, identifier)
        if db.execute('SELECT 1 FROM storages WHERE parent_id=? AND archived_at IS NULL', (identifier,)).fetchone():
            raise ValueError('Storages sit inside this one · move or archive them first')
        contents = storage_contents(db, identifier)
        if contents and not move_to_unstored:
            raise ValueError('Move the items first or choose Move everything to Not stored')
        changes = []
        for table, row in contents:
            w.record(db, changes, table, {'id': row['id']},
                     lambda t=table, r=row: db.execute('UPDATE '+t+' SET storage_id=NULL'+
                         (',updated_at=?' if t != 'lots' else '')+' WHERE id=?',
                         (w.stamp(), r['id']) if t != 'lots' else (r['id'],)))
        w.record(db, changes, 'storages', {'id': identifier},
                 lambda: db.execute('UPDATE storages SET archived_at=? WHERE id=?', (w.stamp(), identifier)))
        return finish(db, changes, 'archive', storage_id=identifier)
