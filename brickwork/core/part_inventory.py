"""Part to Inventory on the 4.0 store (M.8e, issue #110): photo proposals and atomic inventory batches.

A batch is one `part_inventory:<batch>` receipt event holding the stock changes `stock.add_loose` made (rows before and after), the lot
it created, the photos it kept and the identification records it wrote; Undo (`core/undo.py`) takes the stock back, archives the lot,
the photos and the records, and writes `event_undo`. It is refused when the stock changed since (undo the later save first).
The recognition call itself (Brickognize, `/workbench/part-to-inventory/detect`) is Identify's (M.8h, `core/identify.py`): `candidates` here
is its mapping of predictions to items.
"""
import base64
import io
import json
import uuid
from pathlib import Path

from . import add, collection, identify, stock
from . import undo as undoing
from .admin import audit
from .media import media_root
from .transaction import on_rollback, transaction
from ..store4.connect import now as stamp_now

CONDITIONS = {'U': 'used', 'N': 'new', 'used': 'used', 'new': 'new'}


def options(db):
    return dict(colours=add.colors(db),
                lots=[dict(r, created_date=(r['created_at'] or '')[:10]) for r in db.execute(
                    '''SELECT l.*,coalesce(sum(s.quantity),0) AS quantity FROM main.lot l LEFT JOIN main.stock s ON s.lot_id=l.id AND s.archived_at IS NULL
                       WHERE l.archived_at IS NULL GROUP BY l.id ORDER BY l.name,l.id''')],
                storages=[dict(r) for r in db.execute('SELECT * FROM main.storage WHERE archived_at IS NULL ORDER BY name,id')])


def candidates(db, predictions):
    """`(choices, unresolved)` for recognition predictions of parts and minifigures: `core/identify.py` maps each number to an item (never
    guessing between several) and adds what you already hold of it."""
    return identify.candidates(db, predictions)


def keep_photo(db, root, item_id, color_id, content, *, stock_id=None, copy_id=None):
    """An own photo of the piece or set: the file under data/images/own, the row in `photo` (on the stock row or the copy). Returns the photo id.
    Add's photo mode keeps its photo the same way."""
    from PIL import Image
    photo_id = collection._photo_id()
    relative = 'data/images/own/' + photo_id + '.jpg'
    target = Path(root).resolve() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
        image.convert('RGB').save(target, 'JPEG', quality=90)
    on_rollback(db, lambda: target.unlink(missing_ok=True))
    db.execute('''INSERT INTO main.photo(id,item_id,color_id,copy_id,stock_id,local_path,width,height,caption,taken_at,created_at)
                  VALUES(?,?,?,?,?,?,?,?,NULL,NULL,?)''', (photo_id, item_id, color_id, copy_id, stock_id, relative, width, height, stamp_now()))
    return photo_id


def save(db, pieces, *, batch, condition='used', lot_id=None, new_lot=None, keep_photos=True):
    """Add up to 6 identified pieces to loose stock in one receipt. A batch id saved twice returns the first receipt (a retry)."""
    if not isinstance(pieces, list) or not 1 <= len(pieces) <= 6:
        raise ValueError('Review between 1 and 6 pieces')
    condition = CONDITIONS.get(condition)
    if condition is None:
        raise ValueError('Choose used or new')
    if new_lot is not None and (not isinstance(new_lot, dict) or not isinstance(new_lot.get('name'), str) or not isinstance(new_lot.get('note', ''), str)):
        raise ValueError('Name the new lot')
    with transaction(db):
        # An undone receipt (web undo event, or an API undo naming it) counts as absent: the same pieces can be saved again.
        old = db.execute(f"SELECT e.id FROM main.event e WHERE e.entity_kind='part_inventory' AND e.entity_id=? AND e.field='receipt' AND NOT {undoing.undone_sql('e')} "
                         'ORDER BY e.id DESC LIMIT 1', (batch,)).fetchone()
        if old:
            return old[0]
        validated = []
        for piece in pieces:
            chosen = piece['chosen']
            try:
                item_id = int(chosen['item_id'])
            except (KeyError, TypeError, ValueError):
                raise ValueError('Review this catalogue identity again') from None
            choice = next((r for r in piece['candidates'] if r.get('item_id') == item_id), None)
            identity = add.lookup(db, item_id)
            if not choice or not identity or identity['kind'] not in ('part', 'minifigure') or choice.get('unresolved'):
                raise ValueError('Review this catalogue identity again')
            colour = chosen.get('color_id')
            if identity['kind'] == 'part' and not add._colour_known(db, colour):
                raise ValueError('Choose a colour')
            validated.append((piece, identity, colour if identity['kind'] == 'part' else None, add.quantity(chosen.get('quantity', 1))))
        stamp = stamp_now()
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
            db.execute('INSERT INTO main.lot(id,name,note,storage_id,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                       (lot_id, new_lot['name'].strip(), str(new_lot.get('note', '')) or None, new_lot.get('storage_id') or None, stamp, stamp))
            audit(db, 'lot:' + lot_id, 'created', None, dict(db.execute('SELECT * FROM main.lot WHERE id=?', (lot_id,)).fetchone()))
        elif lot_id and not db.execute('SELECT 1 FROM main.lot WHERE id=? AND archived_at IS NULL', (lot_id,)).fetchone():
            raise ValueError('Choose an available lot')
        root = media_root(db)
        stock_changes, records, photos = [], [], []
        for piece, identity, colour, amount in validated:
            identifier = piece['id']
            prior = db.execute('SELECT archived_at FROM main.identification WHERE id=?', (identifier,)).fetchone()
            if prior and prior['archived_at'] is None:
                raise ValueError('This piece was already added')
            change = stock.add_loose(db, item_id=identity['item_id'], color_id=colour, quantity=amount, condition=condition, lot_id=lot_id)
            stock_changes.append(change)
            if prior:                                   # archived by an earlier Undo: bring it back instead of colliding on the key
                db.execute('UPDATE main.identification SET archived_at=NULL,created_at=?,has_thumb=?,candidates=? WHERE id=?',
                           (stamp, int(keep_photos), json.dumps(piece['candidates']), identifier))
            else:
                db.execute('INSERT INTO main.identification(id,created_at,has_thumb,candidates) VALUES(?,?,?,?)', (identifier, stamp, int(keep_photos), json.dumps(piece['candidates'])))
            audit(db, 'identification:' + identifier, 'created', None, dict(db.execute('SELECT * FROM main.identification WHERE id=?', (identifier,)).fetchone()))
            db.execute("INSERT INTO main.identification_action(identification_id,kind,at,item_id,color_id,quantity,stock_id) VALUES(?,'inventory',?,?,?,?,?)",
                       (identifier, stamp, identity['item_id'], colour, amount, change['id']))
            records.append(identifier)
            if keep_photos and piece.get('photo'):
                photos.append(keep_photo(db, root, identity['item_id'], colour, base64.b64decode(piece['photo']), stock_id=change['id']))
        receipt = dict(batch=batch, stock=stock_changes, lot=created_lot, identifications=records, photos=photos)
        audit(db, 'part_inventory:' + batch, 'receipt', None, receipt)
        return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def _undo_batch(db, event, via, actor):
    """Take a batch back: the stock it added, its lot, photos and identification records. Refused when the stock or the lot changed."""
    receipt = json.loads(event['new_value'])
    for change in reversed(receipt['stock']):
        stock.undo_added(db, change, via=via, actor=actor)
    stamp = stamp_now()
    if receipt['lot']:
        if db.execute('SELECT 1 FROM main.stock WHERE lot_id=? AND archived_at IS NULL', (receipt['lot'],)).fetchone():
            raise ValueError('This lot now contains other stock')
        db.execute('UPDATE main.lot SET archived_at=?,updated_at=? WHERE id=?', (stamp, stamp, receipt['lot']))
    for photo_id in receipt['photos']:
        db.execute('UPDATE main.photo SET archived_at=? WHERE id=? AND archived_at IS NULL', (stamp, photo_id))
    for identifier in receipt['identifications']:
        db.execute('UPDATE main.identification SET archived_at=? WHERE id=? AND archived_at IS NULL', (stamp, identifier))
    audit(db, 'part_inventory:' + receipt['batch'], 'undo', None, dict(undoes=event['id']), via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('part_inventory', 'receipt', _undo_batch)


def undo(db, event_id):
    """Undo a batch receipt by its event id; a second Undo does nothing."""
    row = db.execute('SELECT entity_kind FROM main.event WHERE id=?', (int(event_id),)).fetchone()
    if row is None or row['entity_kind'] != 'part_inventory':
        raise ValueError('Choose a batch receipt')
    return undoing.undo_event(db, int(event_id), via='app')
