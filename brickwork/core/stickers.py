"""Stickers on loose parts (#201): the Sticker flag, the sets a sticker may belong to, and the confirmed choice (ADR 0027).

A person ticks "Has a sticker" when filing a part (`part_inventory.save`): the stock row gets the `tag` flag named Sticker. The catalogue has sticker sheets
(parts of the category named `Stickers`) but does not say which part a sticker goes on, so `candidates` is the fallback: the live catalogue sets whose latest
inventory holds the part in that colour **and** a sticker sheet. The person then confirms one (`confirm`, "This one"), keeps the flag as a hint (nothing to
store) or says it is no sticker (`clear`, which removes the flag).

**Storage.** A confirmation is an event, not a row: `stock_sticker:<stock id>`, field `confirm` (`new_value` holds the set, the sheet and the stock line) or
`clear` ("Not a sticker"). The line's current state is its newest event of those two that was not undone, so Undo of a later choice shows the earlier one
again. A confirmation counts only while the stock row holds the Sticker flag. The scoring engine reads it from the same events (`set_scoring._stock_rows`).
No table, so no schema step (ADR 0027)."""
import json
import uuid

from . import errors, set_scoring as engine, undo as undoing
from .admin import audit
from ..store4.connect import now as stamp_now

FLAG_NAME = 'Sticker'
KIND, CONFIRM, CLEAR = 'stock_sticker', 'confirm', 'clear'
MAX_LIMIT = 100


def flag_id(db):
    """The id of the live `tag` flag named Sticker (any case), or None."""
    row = db.execute("SELECT id FROM main.flag WHERE kind='tag' AND archived_at IS NULL AND lower(name)=lower(?) ORDER BY created_at,id LIMIT 1", (FLAG_NAME,)).fetchone()
    return row[0] if row else None


def ensure_flag(db):
    """`(flag id, created)`: the Sticker flag, made as a visible tag when the collection has none yet."""
    found = flag_id(db)
    if found:
        return found, False
    identifier = uuid.uuid4().hex
    db.execute("INSERT INTO main.flag(id,name,kind,shown_on_grid,system,created_at) VALUES(?,?,'tag',1,0,?)", (identifier, FLAG_NAME, stamp_now()))
    return identifier, True


def line(db, lot_id, stock_id):
    """The live loose part `stock_id` in lot `lot_id` as a dict (name, number, colour); `errors.NotFound` when the lot has no such part line."""
    row = db.execute('''SELECT s.id,s.item_id,s.color_id,s.quantity,s.kind,s.lot_id,i.name,i.born_key AS number,c.name AS color_name
                        FROM main.stock s JOIN main.item i ON i.id=s.item_id LEFT JOIN main.color c ON c.id=s.color_id
                        WHERE s.id=? AND s.archived_at IS NULL AND s.lot_id=? AND s.kind='part' ''', (stock_id, lot_id)).fetchone()
    if row is None:
        raise errors.NotFound('No such part in this lot')
    return dict(row)


def _latest_sql():
    return (f"SELECT e.id,e.field,e.new_value FROM main.event e WHERE e.entity_kind='{KIND}' AND e.entity_id=? AND e.field IN ('{CONFIRM}','{CLEAR}') "
            'AND NOT EXISTS(SELECT 1 FROM main.event_undo u WHERE u.event_id=e.id) ORDER BY e.id DESC LIMIT 1')


def decision(db, stock_id):
    """The confirmed sticker of a stock line as `dict(set_item_id, sheet_item_id, set_number, set_name, event_id)`, or None."""
    row = db.execute(_latest_sql(), (stock_id,)).fetchone()
    if row is None or row['field'] != CONFIRM:
        return None
    body = json.loads(row['new_value'])
    names = db.execute('SELECT born_key,name FROM catalogue.item WHERE id=?', (body['set_item_id'],)).fetchone()
    return dict(set_item_id=body['set_item_id'], sheet_item_id=body['sheet_item_id'], set_number=names[0] if names else None,
                set_name=names[1] if names else None, event_id=row['id'])


def states(db, stock_ids):
    """`{stock id: dict(flagged, confirmed)}` for the stock lines: `flagged` is whether the Sticker flag is on it, `confirmed` its `decision` (only
    while flagged)."""
    ids = list(stock_ids)
    if not ids:
        return {}
    flag = flag_id(db)
    held = set()
    if flag:
        held = {r[0] for r in db.execute('SELECT stock_id FROM main.stock_flag WHERE flag_id=? AND stock_id IN (SELECT value FROM json_each(?))',
                                         (flag, json.dumps(ids)))}
    return {i: dict(flagged=i in held, confirmed=decision(db, i) if i in held else None) for i in ids}


def _holders(db, stock):
    """Every candidate set of a part line, ordered (see `candidates`)."""
    rows = db.execute(
        '''WITH holders AS (
             SELECT DISTINCT i.item_id AS set_id, i.id AS inventory_id FROM catalogue.inventory i
             JOIN catalogue.item t ON t.id=i.item_id AND t.kind='set' AND t.retired_at IS NULL
             JOIN catalogue.inventory_part p ON p.inventory_id=i.id AND p.item_id=? AND p.color_id=? AND p.is_spare=0
             WHERE i.is_latest=1 AND i.retired_at IS NULL)
           SELECT h.set_id, s.born_key AS set_number, s.name AS set_name, s.year, sh.id AS sheet_item_id, sh.born_key AS sheet_number, sh.name AS sheet_name,
                  coalesce((SELECT u.url FROM catalogue.picture_url u WHERE u.item_id=sh.id ORDER BY u.color_id LIMIT 1), sh.img_url) AS sheet_picture
           FROM holders h JOIN catalogue.item s ON s.id=h.set_id
           JOIN catalogue.inventory_part q ON q.inventory_id=h.inventory_id AND q.is_spare=0
           JOIN catalogue.item sh ON sh.id=q.item_id AND sh.kind='part' AND sh.retired_at IS NULL
           JOIN catalogue.part_category c ON c.id=sh.category_id AND c.name=?
           ORDER BY h.set_id, sh.born_key, sh.id''', (stock['item_id'], stock['color_id'], engine.STICKER_CATEGORY)).fetchall()
    sets = {}
    for r in rows:
        sets.setdefault(r['set_id'], dict(r))                      # the first sheet by number
    ordered = sorted(sets.values(), key=lambda r: (r['sheet_picture'] is None, r['year'] is None, r['year'] or 0, r['set_number'] or '', r['set_id']))
    return [dict(set_item_id=r['set_id'], set_number=r['set_number'], set_name=r['set_name'], year=r['year'], sheet_item_id=r['sheet_item_id'],
                 sheet_number=r['sheet_number'], sheet_name=r['sheet_name'], sheet_picture=r['sheet_picture']) for r in ordered]


def candidates(db, lot_id, stock_id, *, limit=3, offset=0):
    """The sets a sticker on this part line may belong to: `dict(stock, total, limit, offset, results)`.

    Each result is a live catalogue set (not retired) whose latest, live inventory holds the part in the line's colour (spare lines left out, ADR 0011) and
    at least one sticker sheet (a part of the category `Stickers`, by name): `set_item_id`, `set_number`, `set_name`, `year`, `sheet_item_id`,
    `sheet_number`, `sheet_name` and `sheet_picture` (the catalogue's picture address, or None). A set with several sheets is one row, its sheet with the lowest
    number first. Sets with a sheet picture come first, then the earlier year, then the number."""
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise ValueError(f'limit is 1 to {MAX_LIMIT}, offset from 0')
    stock = line(db, lot_id, stock_id)
    every = _holders(db, stock)
    return dict(stock=stock, total=len(every), limit=limit, offset=offset, results=every[offset:offset + limit])


def _flagged(db, stock_id):
    flag = flag_id(db)
    return bool(flag and db.execute('SELECT 1 FROM main.stock_flag WHERE stock_id=? AND flag_id=?', (stock_id, flag)).fetchone())


def confirm(db, lot_id, stock_id, set_item_id, sheet_item_id):
    """Record "This one": the sticker on this part line is the sheet `sheet_item_id` of set `set_item_id`, one event (undoable). The pair must be one of
    the line's `candidates`; the line must hold the Sticker flag. Choosing what is already chosen writes nothing. Returns `dict(event_id, changed)`."""
    from .transaction import transaction
    with transaction(db):
        line(db, lot_id, stock_id)
        if not _flagged(db, stock_id):
            raise errors.Conflict('This part is not marked as having a sticker')
        results = _holders(db, line(db, lot_id, stock_id))
        if not any(r['set_item_id'] == set_item_id and r['sheet_item_id'] == sheet_item_id for r in results):
            raise ValueError('Choose one of the sets that hold this part and a sticker sheet')
        now = decision(db, stock_id)
        if now and (now['set_item_id'], now['sheet_item_id']) == (set_item_id, sheet_item_id):
            return dict(event_id=now['event_id'], changed=False)
        audit(db, f'{KIND}:{stock_id}', CONFIRM, now and dict(set_item_id=now['set_item_id'], sheet_item_id=now['sheet_item_id']),
              dict(set_item_id=set_item_id, sheet_item_id=sheet_item_id, stock_id=stock_id, lot_id=lot_id))
        return dict(event_id=db.execute('SELECT last_insert_rowid()').fetchone()[0], changed=True)


def clear(db, lot_id, stock_id):
    """Record "Not a sticker": the Sticker flag leaves the line and a confirmation, if there is one, stops counting; one event (undoable).
    A line without the flag writes nothing. Returns `dict(event_id, changed)`."""
    from .transaction import transaction
    with transaction(db):
        line(db, lot_id, stock_id)
        flag = flag_id(db)
        if not _flagged(db, stock_id):
            return dict(event_id=None, changed=False)
        now = decision(db, stock_id)
        db.execute('DELETE FROM main.stock_flag WHERE stock_id=? AND flag_id=?', (stock_id, flag))
        audit(db, f'{KIND}:{stock_id}', CLEAR, dict(flag_id=flag, **({'set_item_id': now['set_item_id'], 'sheet_item_id': now['sheet_item_id']} if now else {})),
              dict(stock_id=stock_id, lot_id=lot_id, flag_id=flag))
        return dict(event_id=db.execute('SELECT last_insert_rowid()').fetchone()[0], changed=True)


def _undo_confirm(db, event, via, actor):
    """Undo "This one": the event stops counting, so the line's earlier choice (or none) is its state again. Nothing else changed since."""
    return _undone(db, event, via, actor)


def _undo_clear(db, event, via, actor):
    """Undo "Not a sticker": the flag goes back on the line (refused when the line is gone); the earlier confirmation counts again."""
    body = json.loads(event['new_value'])
    row = db.execute('SELECT 1 FROM main.stock WHERE id=? AND archived_at IS NULL', (body['stock_id'],)).fetchone()
    if row is None:
        raise ValueError('This part line is gone')
    flag = db.execute('SELECT 1 FROM main.flag WHERE id=? AND archived_at IS NULL', (body['flag_id'],)).fetchone()
    if flag is None:
        raise ValueError('The Sticker flag was removed')
    db.execute('INSERT OR IGNORE INTO main.stock_flag(stock_id,flag_id) VALUES(?,?)', (body['stock_id'], body['flag_id']))
    return _undone(db, event, via, actor)


def _undone(db, event, via, actor):
    audit(db, f"{KIND}:{event['entity_id']}", 'undo', None, dict(undoes=event['id']), via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register(KIND, CONFIRM, _undo_confirm)
undoing.register(KIND, CLEAR, _undo_clear)
