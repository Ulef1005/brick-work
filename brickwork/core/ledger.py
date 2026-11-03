"""Storage on the 4.0 store (M.8e, issue #110): the counts, the page projection, and the writes with their history and Undo.

A write is one `ledger` receipt event (`storage`, `place`, `move`, `archive`): the tables it changed, before and after, as
`collection.receipt` writes them. Undo is the collection's generic undoer (refused unless every row still equals what the request left)
behind the three storage guards of 3.3 (`undo_guard`). The order receipts are `core/orders.py`'s (M.8h): they use the same tracker.
"""
import json
from uuid import uuid4

from . import collection, stock as stock_module, workbench
from . import undo as undoing
from .transaction import transaction

ENTITY = 'ledger'
STORAGE_TYPES = ('Box', 'Shelf', 'Drawer', 'Bin', 'Bag', 'Case', 'Cabinet', 'Room', 'Other')
PLACE_KINDS = ('BrickLink store', 'Online shop', 'Shop', 'Market', 'Fair', 'Private', 'Other')
KEEP = object()
OTHER_KINDS = ('instructions', 'box', 'gear', 'book', 'catalog')


def visuals(db, rows):
    """Decorate rows that carry an `item_id` (identity, colour, picture) using a constant number of queries."""
    return collection.decorate(db, rows)


# ---------- history and undo ----------

def history(db, *, actions=None, limit=200):
    """The newest ledger saves, filtered in SQLite: `[dict(id, at, receipt=dict(action), receipt_count, undone, undo_available)]`."""
    marks = ','.join('?' for _ in actions) if actions else None
    rows = db.execute(f"""SELECT e.id,e.at,e.field,{undoing.undone_sql()} AS undone,{undoing.undoable_sql()} AS undoable FROM main.event e
                          WHERE e.entity_kind=?{' AND e.field IN (' + marks + ')' if marks else ''} ORDER BY e.id DESC{' LIMIT ?' if limit is not None else ''}""",
                      (ENTITY, *(actions or ()), *((limit,) if limit is not None else ())))
    return [dict(id=r['id'], at=r['at'], receipt=dict(action=r['field']), receipt_count=1, undone=bool(r['undone']),
                 undo_available=bool(r['undoable']) and not r['undone']) for r in rows]


def undo_guard(db, event, via, actor):
    """The storage guards, then the generic undo: a created location with contents or sub-locations stays; a moved lot that gained parts
    in its new storage stays; an item put back into a location that is no longer live stays."""
    before, after = json.loads(event['old_value']), json.loads(event['new_value'])
    pairs = list(zip(before, after))
    restored = {r['id'] for old, new in pairs if old['table'] == 'storage' for r in old['rows'] if r['archived_at'] is None}
    receipt_stock = {r['id'] for old, new in pairs if new['table'] == 'stock' for r in new['rows']}
    for old, new in pairs:
        table = new['table']
        if table == 'storage' and not old['rows']:
            for r in new['rows']:
                if storage_contents(db, r['id']) or db.execute('SELECT 1 FROM main.storage WHERE parent_id=? AND archived_at IS NULL', (r['id'],)).fetchone():
                    raise ValueError('Move the items before undoing location creation')
        if table == 'lot':
            for was, now in zip(old['rows'], new['rows']):
                if was['storage_id'] != now['storage_id']:
                    gained = [r[0] for r in db.execute('SELECT id FROM main.stock WHERE archived_at IS NULL AND lot_id=? AND storage_id IS ?', (now['id'], now['storage_id']))
                              if r[0] not in receipt_stock]
                    if gained:
                        raise ValueError('This lot has gained parts in its new storage · move them out before undoing the move')
        if table in ('copy', 'stock', 'lot'):
            for storage_id in sorted({r['storage_id'] for r in old['rows'] if r['storage_id'] and r['storage_id'] not in restored}):
                require_storage(db, storage_id)
    return collection._undo_collection(db, event, via, actor)


for _field in ('storage', 'place', 'move', 'archive'):
    undoing.register(ENTITY, _field, undo_guard)


def undo(db, event_id):
    """Undo a ledger save by its event id; a second Undo of the same save does nothing."""
    row = db.execute('SELECT entity_kind FROM main.event WHERE id=?', (int(event_id),)).fetchone()
    if row is None or row['entity_kind'] != ENTITY:
        raise ValueError('Save is unavailable')
    return undoing.undo_event(db, int(event_id), via='app')


def undo_history(db, event_id):
    """Undo a ledger save from its history list; a save already undone says so."""
    with transaction(db):
        row = db.execute('SELECT entity_kind FROM main.event WHERE id=?', (int(event_id),)).fetchone()
        if row is None or row['entity_kind'] != ENTITY:
            raise ValueError('Save is unavailable')
        if undoing.undo_event(db, int(event_id), via='app')['already_undone']:
            raise ValueError('This save has already been undone')


# ---------- reads ----------

def storages(db):
    """Per-storage counts. ``part_lots`` is lots plus loose parts that are not inside a lot kept in the same storage.

    Figures are minifigures; ``other`` is instructions, boxes, gear, books and catalogues. The last row is the virtual "Not stored"."""
    return [dict(r) for r in db.execute('''WITH c AS (SELECT storage_id,count(*) AS copies FROM main.copy WHERE archived_at IS NULL GROUP BY storage_id),
      s AS (SELECT t.storage_id,count(*) AS entries,coalesce(sum(t.quantity),0) AS pieces,
        coalesce(sum(t.kind='minifigure'),0) AS figures,
        coalesce(sum(t.kind='part' AND x.id IS NULL),0) AS loose_parts,
        coalesce(sum(t.kind IN ('instructions','box','gear','book','catalog')),0) AS other
        FROM main.stock t LEFT JOIN main.lot x ON x.id=t.lot_id AND x.archived_at IS NULL AND x.storage_id IS t.storage_id
        WHERE t.archived_at IS NULL GROUP BY t.storage_id),
      l AS (SELECT storage_id,count(*) AS lots FROM main.lot WHERE archived_at IS NULL GROUP BY storage_id)
      SELECT p.id,p.name,p.type,p.parent_id,p.note,(SELECT name FROM main.storage q WHERE q.id=p.parent_id) AS parent_name,coalesce(c.copies,0) AS copies,
      coalesce(s.entries,0) AS entries,coalesce(s.pieces,0) AS pieces,coalesce(l.lots,0) AS lots,
      coalesce(s.figures,0) AS figures,coalesce(s.loose_parts,0)+coalesce(l.lots,0) AS part_lots,coalesce(s.other,0) AS other
      FROM (SELECT id,name,type,parent_id,note FROM main.storage WHERE archived_at IS NULL UNION ALL SELECT NULL,'Not stored',NULL,NULL,NULL) p
      LEFT JOIN c ON c.storage_id IS p.id LEFT JOIN s ON s.storage_id IS p.id LEFT JOIN l ON l.storage_id IS p.id ORDER BY p.id IS NULL,p.name,p.id''')]


def storage_detail(db, identifier, rows=None):
    """``rows`` are already-loaded ``storages(db)``, so a page does not run that query twice."""
    location = next((r for r in (storages(db) if rows is None else rows) if r['id'] == identifier), None)
    if location is None:
        raise ValueError('Location is unavailable')
    found = [dict(r) for r in db.execute('''SELECT 'copy' AS entity,c.id,c.item_id,NULL AS color_id,1 AS quantity,c.completeness,c.condition,NULL AS lot,'set' AS kind
      FROM main.copy c WHERE c.archived_at IS NULL AND c.storage_id IS ? ORDER BY c.item_id,c.created_at,c.id''', (identifier,))]
    found += [dict(r) for r in db.execute('''SELECT 'stock' AS entity,s.id,s.item_id,s.color_id,s.quantity,NULL AS completeness,s.condition,x.id AS lot,s.kind
      FROM main.stock s LEFT JOIN main.lot x ON x.id=s.lot_id AND x.archived_at IS NULL AND x.storage_id IS s.storage_id
      WHERE s.archived_at IS NULL AND s.storage_id IS ? ORDER BY s.item_id,s.color_id,s.created_at,s.id''', (identifier,))]
    return dict(location=location, rows=visuals(db, found))


def storage_view(db, identifier, rows=None):
    """The Storage page projection: ``storage_detail`` plus what the page groups by.

    Adds the lot a part sits in (only a lot kept in this same storage) and the lots themselves, and splits the rows into sets, figures,
    part lots (lots, then loose parts) and other. A lot's size counts only the parts in its own storage, which is what a move carries."""
    detail = storage_detail(db, identifier, rows)
    lots = [dict(r, entity='lot', item_type='L', item_no=None, kind='lot') for r in db.execute('''SELECT l.id,l.name,coalesce(s.entries,0) AS entries,coalesce(s.quantity,0) AS quantity
        FROM main.lot l LEFT JOIN (SELECT t.lot_id,count(*) AS entries,sum(t.quantity) AS quantity FROM main.stock t JOIN main.lot x ON x.id=t.lot_id
        WHERE t.archived_at IS NULL AND t.storage_id IS x.storage_id GROUP BY t.lot_id) s ON s.lot_id=l.id
        WHERE l.archived_at IS NULL AND l.storage_id IS ? ORDER BY l.name,l.id''', (identifier,))]
    rows = detail['rows']
    stock = [r for r in rows if r['entity'] == 'stock']
    detail['sets'] = [r for r in rows if r['entity'] == 'copy']
    detail['figures'] = [r for r in stock if r['kind'] == 'minifigure']
    detail['part_lots'] = lots + [r for r in stock if r['kind'] == 'part']
    detail['other'] = [r for r in stock if r['kind'] in OTHER_KINDS]
    detail['total'] = len(detail['sets']) + len(detail['figures']) + len(detail['part_lots']) + len(detail['other'])
    return detail


def storage_contents(db, identifier):
    """Live references to a storage in three queries, including a lot's own location: `[(table, row)]`, tables `copy`, `stock`, `lot`."""
    return [(table, dict(row)) for table in ('copy', 'stock', 'lot')
            for row in db.execute(f'SELECT * FROM main.{table} WHERE storage_id=? AND archived_at IS NULL', (identifier,))]


def require_storage(db, identifier):
    if not db.execute('SELECT 1 FROM main.storage WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone():
        raise ValueError('Location is unavailable')


# ---------- writes ----------

def storage_save(db, identifier, name, *, type=KEEP, parent_id=KEEP, note=KEEP):
    """Create or change a storage: type (STORAGE_TYPES or empty), parent_id (another live storage, never itself or one inside it) and
    note; fields left at KEEP stay as they are. Returns `(storage id, event id)`."""
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
                    row = db.execute('SELECT parent_id FROM main.storage WHERE id=?', (current,)).fetchone()
                    current = row[0] if row else None
            fields['parent_id'] = parent_id
        tracker = workbench.Tracker(db)
        if identifier:
            require_storage(db, identifier)
            tracker.touch('storage', identifier)
            db.execute('UPDATE main.storage SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', (*fields.values(), identifier))
        else:
            identifier = uuid4().hex
            tracker.created('storage', identifier)
            fields = dict(id=identifier, created_at=workbench.stamp(), **fields)
            db.execute('INSERT INTO main.storage(' + ','.join(fields) + ') VALUES(' + ','.join('?' for _ in fields) + ')', tuple(fields.values()))
        return identifier, tracker.write('storage', ENTITY)


def place_kind(db, identifier, kind):
    """What kind of place a purchase location is; one receipt, Undo in History."""
    kind = (kind or '').strip() or None
    if kind is not None and kind not in PLACE_KINDS:
        raise ValueError('Choose a kind: ' + ', '.join(PLACE_KINDS))
    with transaction(db):
        if not db.execute('SELECT 1 FROM main.place WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone():
            raise ValueError('Purchase location is unavailable')
        tracker = workbench.Tracker(db)
        tracker.touch('place', identifier)
        db.execute('UPDATE main.place SET kind=? WHERE id=?', (kind, identifier))
        return tracker.write('place', ENTITY)


def _put_stock_in(db, tracker, ids, storage_id):
    """Set the storage of live stock rows. A row that then meets another live row's merge key (item, colour, condition, lot, storage)
    merges into it as a stock edit does (`stock.plan_edit` / `apply_edit`: quantities, missing and damaged summed, `checked` only when both
    were); the receipt keeps both rows, so one Undo restores them exactly. A loose figure is not in the key and never merges."""
    if not ids:
        return
    rows = [dict(r) for r in db.execute('SELECT * FROM main.stock WHERE id IN (SELECT value FROM json_each(?)) ORDER BY id', (json.dumps(sorted(ids)),))]
    edits = {'storage_id': storage_id}
    plan = stock_module.plan_edit(db, rows, edits)
    tracker.touch('stock', *ids, *[target for _, target in plan if target is not None and target not in ids])
    stock_module.apply_edit(db, rows, edits, plan, stamp=workbench.stamp())


def move(db, identifier, selections):
    """Move copies, loose stock and lots to a storage (None: Not stored). A lot carries its parts that sit in the lot's own storage."""
    if not selections or len(selections) > 1000:
        raise ValueError('Choose up to 1000 items to move')
    with transaction(db):
        if identifier is not None:
            require_storage(db, identifier)
        if any(s.get('entity') not in ('copy', 'stock', 'lot') for s in selections):
            raise ValueError('Choose copies, loose stock or lots')
        # Read the carried parts before any write moves their lot; they count against the same limit.
        lots = sorted({s['id'] for s in selections if s['entity'] == 'lot'})
        done = {s['id'] for s in selections if s['entity'] == 'stock'}
        carried = [r[0] for r in db.execute('SELECT s.id FROM main.stock s JOIN main.lot l ON l.id=s.lot_id WHERE s.archived_at IS NULL AND s.storage_id IS l.storage_id '
                                            'AND l.id IN (SELECT value FROM json_each(?)) ORDER BY s.id', (json.dumps(lots),))] if lots else []
        carried = [k for k in carried if k not in done]
        if len(selections) + len(carried) > 1000:
            if carried:
                raise ValueError(('This lot holds ' if len(lots) == 1 else 'These lots hold ') + str(len(carried)) + ' parts · move it in parts or archive the storage')
            raise ValueError('Choose up to 1000 items to move')
        tracker = workbench.Tracker(db)
        stock_ids = sorted({s['id'] for s in selections if s['entity'] == 'stock'} | set(carried))
        for entity in ('copy', 'stock', 'lot'):
            ids = sorted({s['id'] for s in selections if s['entity'] == entity})
            if not ids:
                continue
            live = {r[0] for r in db.execute(f'SELECT id FROM main.{entity} WHERE archived_at IS NULL AND id IN (SELECT value FROM json_each(?))', (json.dumps(ids),))}
            if len(live) != len(ids):
                raise ValueError('An item changed · review this location again')
            if entity == 'stock':
                continue                                                      # moved below with the parts a lot carries
            tracker.touch(entity, *ids)
            db.execute(f'UPDATE main.{entity} SET storage_id=?,updated_at=? WHERE id IN (SELECT value FROM json_each(?))', (identifier, workbench.stamp(), json.dumps(ids)))
        # A lot carries its parts: stock that sits in the lot's own storage follows it in the same receipt, so one Undo restores both.
        _put_stock_in(db, tracker, stock_ids, identifier)
        return tracker.write('move', ENTITY)


def storage_archive(db, identifier, *, move_to_unstored=False):
    """Archive a location and optionally move its live contents to Not stored in one receipt."""
    with transaction(db):
        require_storage(db, identifier)
        if db.execute('SELECT 1 FROM main.storage WHERE parent_id=? AND archived_at IS NULL', (identifier,)).fetchone():
            raise ValueError('Storages sit inside this one · move or archive them first')
        contents = storage_contents(db, identifier)
        if contents and not move_to_unstored:
            raise ValueError('Move the items first or choose Move everything to Not stored')
        tracker = workbench.Tracker(db)
        _put_stock_in(db, tracker, [row['id'] for t, row in contents if t == 'stock'], None)
        for table in ('copy', 'lot'):
            ids = [row['id'] for t, row in contents if t == table]
            if ids:
                tracker.touch(table, *ids)
                db.execute(f'UPDATE main.{table} SET storage_id=NULL,updated_at=? WHERE id IN (SELECT value FROM json_each(?))', (workbench.stamp(), json.dumps(ids)))
        tracker.touch('storage', identifier)
        db.execute('UPDATE main.storage SET archived_at=? WHERE id=?', (workbench.stamp(), identifier))
        return tracker.write('archive', ENTITY)
