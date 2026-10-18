"""Photo proposals and atomic inventory batches on the migrated store."""
import base64
import json
import uuid

from .transaction import transaction
from . import add, stock
from .admin import audit
from .sources.base import now
from .sources.brickognize import keep


def options(db):
    return dict(colours=add.colors(db),
                lots=[dict(r) for r in db.execute('SELECT l.*,coalesce(sum(s.quantity),0) AS quantity FROM lots l LEFT JOIN loose_stock s ON s.lot_id=l.id AND s.archived_at IS NULL WHERE l.archived_at IS NULL GROUP BY l.id ORDER BY l.name,l.id')],
                storages=[dict(r) for r in db.execute('SELECT * FROM storages WHERE archived_at IS NULL ORDER BY name,id')])


def candidates(db, predictions):
    result, unresolved = [], []
    for prediction in predictions[:9]:
        if prediction['item_type'] not in ('P', 'M'):
            continue
        identity = add.lookup(db, prediction['item_type'], prediction['item_no'])
        if not identity:
            unresolved.append(dict(**prediction, reason='Unknown catalogue identity'))
            continue
        row = add.decorate(db, dict(**identity, score=prediction['score']))
        if row['to_check']:
            unresolved.append(dict(**prediction, reason='To check'))
        else:
            result.append(row)
    # #45: what you already hold of each candidate, across colours, and which copies need it.
    from . import ownership
    owned = ownership.summary(db, [(r['item_type'], r['item_no']) for r in result])
    for row in result:
        info = owned.get((row['item_type'], row['item_no']))
        row['owned_summary'] = dict(info, text=ownership.text(info)) if info else dict(total=0, colours=[], needed_by=[], needed_count=0, text=ownership.text(None))
    return result, unresolved


def save(db, pieces, *, batch, condition='U', lot_id=None, new_lot=None, keep_photos=True):
    if not isinstance(pieces, list) or not 1 <= len(pieces) <= 6:
        raise ValueError('Review between 1 and 6 pieces')
    if condition not in ('U', 'N'):
        raise ValueError('Choose used or new')
    if new_lot is not None and (not isinstance(new_lot, dict) or not isinstance(new_lot.get('name'), str) or not isinstance(new_lot.get('note', ''), str)):
        raise ValueError('Name the new lot')
    with db:
        db.execute('BEGIN IMMEDIATE')
        from .api_reads import undone_sql
        # An undone receipt (web undo event, or an API undo naming it) counts as absent.
        old = db.execute("SELECT e.id FROM events e WHERE e.entity=? AND e.field='receipt' AND NOT " + undone_sql('e') +
                         " ORDER BY e.id DESC LIMIT 1", ('part_inventory:' + batch,)).fetchone()
        if old:  # an undone receipt counts as absent: the same pieces can be saved again
            return old[0]
        colours = {r[0]: r[1] for r in db.execute('SELECT color_id,name FROM colors')}
        blocked = {(r[0], r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check'")}
        existing = {(r[0], r[1]) for r in db.execute('SELECT item_type,item_no FROM items')}
        validated = []
        for piece in pieces:
            chosen = piece['chosen']
            choice = next((r for r in piece['candidates'] if (r['item_type'], r['item_no']) == (chosen['item_type'], chosen['item_no'])), None)
            identity = add.lookup(db, chosen['item_type'], chosen['item_no'])
            if not choice or not identity or chosen['item_type'] not in ('P', 'M') or (chosen['item_type'], chosen['item_no']) in blocked:
                raise ValueError('Review this catalogue identity again')
            colour = chosen.get('color_id')
            if colour not in colours:
                raise ValueError('Choose a colour')
            validated.append((piece, identity, colour, add.quantity(chosen.get('quantity', 1))))
        created_lot = None
        if new_lot:
            if lot_id or not str(new_lot.get('name', '')).strip():
                raise ValueError('Name the new lot')
            if len(new_lot['name']) > 200 or len(str(new_lot.get('note', ''))) > 2000:
                raise ValueError('Use a name up to 200 characters and a note up to 2000')
            if new_lot.get('storage_id'):
                from .ledger import require_storage
                require_storage(db, new_lot['storage_id'])
            lot_id = created_lot = uuid.uuid4().hex
            db.execute('INSERT INTO lots(id,name,note,storage_id,created_date) VALUES(?,?,?,?,?)',
                       (lot_id, new_lot['name'].strip(), str(new_lot.get('note', '')), new_lot.get('storage_id') or None, now().date().isoformat()))
            audit(db, 'lot:' + lot_id, 'created', None, dict(db.execute('SELECT * FROM lots WHERE id=?', (lot_id,)).fetchone()))
        elif lot_id and not db.execute('SELECT 1 FROM lots WHERE id=? AND archived_at IS NULL', (lot_id,)).fetchone():
            raise ValueError('Choose an available lot')
        stock_ids, stock_changes, identifications = [], [], []
        for piece, identity, colour, quantity in validated:
            kind, number = identity['item_type'], identity['item_no']
            stamp = now().isoformat()
            if (kind, number) not in existing:
                db.execute('INSERT INTO items(item_type,item_no,name,updated_at) VALUES(?,?,?,?)', (kind, number, identity['name'], stamp))
                audit(db, 'item:' + kind + ':' + number, 'created', None, dict(db.execute('SELECT * FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone()))
                existing.add((kind, number))
            identifier = piece['id']
            prior = db.execute('SELECT archived_at FROM identifications WHERE id=?', (identifier,)).fetchone()
            if prior and prior['archived_at'] is None:
                raise ValueError('This piece was already added')
            stock_id, _ = stock.add_loose(db, stock_changes, item_type=kind, item_no=number,
                color_id=colour, quantity=quantity, condition=condition, lot_id=lot_id)
            stock_ids.append(stock_id)
            # The schema has no identification-to-stock column; retain this link
            # in the batch receipt without sharing the two identities.
            identifications.append(dict(id=identifier, stock_id=stock_id))
            if prior:  # archived by an earlier Undo: bring it back instead of colliding on the key
                db.execute('UPDATE identifications SET archived_at=NULL,created_at=?,has_thumb=?,candidates=? WHERE id=?', (stamp, int(keep_photos), json.dumps(piece['candidates']), identifier))
                audit(db, 'identification:' + identifier, 'restored', None, dict(db.execute('SELECT * FROM identifications WHERE id=?', (identifier,)).fetchone()))
            else:
                db.execute('INSERT INTO identifications(id,created_at,has_thumb,candidates) VALUES(?,?,?,?)', (identifier, stamp, int(keep_photos), json.dumps(piece['candidates'])))
                audit(db, 'identification:' + identifier, 'created', None, dict(db.execute('SELECT * FROM identifications WHERE id=?', (identifier,)).fetchone()))
            action = db.execute("INSERT INTO identification_actions(identification_id,kind,at,item_type,part_num,color_id,color_name,quantity) VALUES(?,'inventory',?,?,?,?,?,?)", (identifier, stamp, kind, number, colour, colours[colour], quantity)).lastrowid
            audit(db, 'identification_action:' + str(action), 'created', None, dict(db.execute('SELECT * FROM identification_actions WHERE id=?', (action,)).fetchone()))
            if keep_photos:
                keep(db, kind, number, base64.b64decode(piece['photo']), stock_id=stock_id)
        audit(db, 'part_inventory:' + batch, 'receipt', None, dict(stock=stock_ids, stock_changes=stock_changes, identifications=identifications, lot=created_lot))
        return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def undo(db, event, *, receipt=None):
    with transaction(db):
        row = receipt if receipt is not None else db.execute("SELECT * FROM events WHERE id=? AND entity LIKE 'part_inventory:%' AND field='receipt'", (event,)).fetchone()
        if not row:
            raise ValueError('Choose a batch receipt')
        # One predicate with save: a newer web undo event, or an API undo naming this receipt.
        from .api_reads import undone_sql
        if db.execute('SELECT ' + undone_sql('e') + ' FROM events e WHERE e.id=?', (row['id'],)).fetchone()[0]:
            return
        receipt = json.loads(row['new_value'])
        if 'stock_changes' in receipt:
            stock.undo_loose(db, receipt['stock_changes'])
        for table, ids in [('loose_stock', [] if 'stock_changes' in receipt else receipt['stock']), ('lots', [receipt['lot']] if receipt['lot'] else [])]:
            for identifier in ids:
                old = dict(db.execute('SELECT * FROM ' + table + ' WHERE id=?', (identifier,)).fetchone())
                if table == 'lots' and db.execute('SELECT 1 FROM loose_stock WHERE lot_id=? AND archived_at IS NULL', (identifier,)).fetchone():
                    raise ValueError('This lot now contains other stock')
                if table == 'loose_stock':
                    original = json.loads(db.execute("SELECT new_value FROM events WHERE entity=? AND field='created'", ('stock:' + identifier,)).fetchone()[0])
                    if old != original:
                        raise ValueError('Stock changed since this batch · review it first')
                db.execute('UPDATE ' + table + ' SET archived_at=? WHERE id=?', (now().isoformat(), identifier))
                audit(db, table + ':' + identifier, 'archived_at', old, dict(db.execute('SELECT * FROM ' + table + ' WHERE id=?', (identifier,)).fetchone()))
        for item in receipt.get('identifications', []):
            old = db.execute('SELECT * FROM identifications WHERE id=? AND archived_at IS NULL', (item['id'],)).fetchone()
            if old:
                db.execute('UPDATE identifications SET archived_at=? WHERE id=?', (now().isoformat(), item['id']))
                audit(db, 'identification:' + item['id'], 'archived_at', dict(old), dict(db.execute('SELECT * FROM identifications WHERE id=?', (item['id'],)).fetchone()))
        audit(db, row['entity'], 'undo', receipt, None)
