"""Rebrickable part lists into loose stock (#471): pull only (Ulf, commission N round 0, 2026-11-19: "All five as drawn").

The person chooses which of their Rebrickable part lists are synced (none by default, the link's `part_lists`). Each list lands in one lot
of its own by default, made at the first pull and named after the list (the link remembers it in `part_list_lots`); a preview row can pick
another live lot. A plan compares each list with the loose parts in its lot, by part and colour: **New there** (Rebrickable has more) is
ticked with the difference; **Different** (more here) and **Only here** (none there) are listed and never pulled. Numbers that name no part
or no colour here are listed with the reason. One apply is one transaction with one receipt: the stock it adds (Added via Rebrickable,
#551), the tag *imported from Rebrickable*, the lots it made and Last synced from per list; one Undo takes it all back. Sending loose parts
to Rebrickable is out of scope (decided: pull only).

ASSUMED SHAPE (Rebrickable's API documentation, not checked live: the test instance has no user token): `GET /users/{token}/partlists/`
returns `{id, name, num_parts}` rows; `GET /users/{token}/partlists/{id}/parts/` returns `{quantity, part: {part_num}, color: {id}}` rows,
paged as the set lists are. If the reply differs, fix `adapters.parse_part_list_row`."""
import json
from uuid import uuid4

from ...store4 import origins
from ...store4.connect import now as store_now
from .. import errors, stock
from .. import undo as undoing
from ..admin import audit, origin
from ..transaction import transaction

FIELD = 'parts_receipt'


def _sync():
    from .. import sync                                   # the package imports this module
    return sync


def chosen(db):
    """The part list ids the person chose to sync (none by default)."""
    return list(_sync()._setting(db, 'rebrickable', 'link', {}).get('part_lists') or [])


def _lots(db):
    return dict(_sync()._setting(db, 'rebrickable', 'link', {}).get('part_list_lots') or {})


def _live_lot(db, lot_id):
    return lot_id and db.execute('SELECT 1 FROM main.lot WHERE id=? AND archived_at IS NULL', (lot_id,)).fetchone() is not None


def _part_item(db, number):
    """The catalogue part a Rebrickable part number names, or None."""
    from .. import add
    try:
        return add._pick(db, 'part', number)
    except ValueError:
        return None


def _colour(db, key):
    from .. import add
    try:
        return add._rebrickable_colour(db, key)
    except ValueError:
        return None


def _numbers(db, item, colour):
    """(Rebrickable part number, Rebrickable colour id) of a row only here, for the preview's words."""
    found = [None, None]
    for store in ('main', 'catalogue') if db.execute("SELECT 1 FROM pragma_database_list WHERE name='catalogue'").fetchone() else ('main',):
        part = db.execute(f'SELECT born_key FROM {store}.item WHERE id=?', (item,)).fetchone()
        shade = db.execute(f"SELECT born_key FROM {store}.color WHERE id=? AND born_provider='rebrickable'", (colour,)).fetchone()
        found = [found[0] or (part and part[0]), found[1] or (shade and int(shade[0]))]
    return found


def plan(db, *, http=None):
    """The preview of a part-list pull. Writes nothing to the collection."""
    sync = _sync()
    wanted = chosen(db)
    if not wanted:
        raise errors.ValidationFailed('Choose the Rebrickable part lists to sync first')
    client = sync.adapters.adapter(db, 'rebrickable', http)
    lists = {r['id']: r for r in client.part_lists()}
    gone = [i for i in wanted if i not in lists]
    if gone:
        raise errors.ValidationFailed('A chosen Rebrickable part list no longer exists · choose again')
    lots = _lots(db)
    rows, unmatched, out_lists = [], [], []
    for list_id in wanted:
        lot = lots.get(str(list_id)) if _live_lot(db, lots.get(str(list_id))) else None
        there = {}
        for raw in client.part_list_parts(list_id):
            if raw is None:
                unmatched.append(dict(list_id=list_id, part_no=None, color_no=None, quantity=None, reason='Rebrickable sent a row that could not be read'))
                continue
            item, colour = _part_item(db, raw['part_no']), _colour(db, raw['color_id'])
            if item is None or colour is None:
                unmatched.append(dict(list_id=list_id, part_no=raw['part_no'], color_no=raw['color_id'], quantity=raw['quantity'],
                                      reason='No part with this number here' if item is None else 'No colour with this Rebrickable id here'))
                continue
            entry = there.setdefault((item, colour), [0, raw['part_no'], raw['color_id']])
            entry[0] += raw['quantity']
        here = {}
        if lot:
            for r in db.execute("SELECT item_id, color_id, sum(quantity) FROM main.stock WHERE kind='part' AND archived_at IS NULL AND lot_id=? GROUP BY item_id, color_id", (lot,)):
                here[(r[0], r[1])] = r[2]
        for (item, colour) in sorted(set(there) | set(here)):
            r, part_no, color_no = there.get((item, colour)) or [0, *_numbers(db, item, colour)]
            h = here.get((item, colour), 0)
            if r == h:
                continue
            state = 'add' if r > h else 'only_here' if r == 0 else 'differs'
            count = r - h if state == 'add' else 0
            rows.append(dict(key=f'{list_id}:{item}:{colour}', list_id=list_id, item_id=item, color_id=colour, part_no=part_no, color_no=color_no,
                             remote=r, here=h, state=state, count=count, tickable=count > 0, action='add' if count else None))
        out_lists.append(dict(id=list_id, name=lists[list_id]['name'], lot_id=lot, new_lot=lot is None))
    value = dict(id=uuid4().hex, created_at=sync.now().isoformat(), direction='parts', source='rebrickable', lists=out_lists, rows=rows,
                 unmatched=unmatched, summary=dict(add=sum(1 for r in rows if r['state'] == 'add'), differs=sum(1 for r in rows if r['state'] == 'differs'),
                                                   only_here=sum(1 for r in rows if r['state'] == 'only_here'), unmatched=len(unmatched)))
    return sync._save_plan(db, value)


def apply(db, plan_id, ticked=None, *, lots=None, via=None, actor=None):
    """Add the ticked rows' difference to loose stock in one transaction with one receipt (`sync:<plan>` / `parts_receipt`). `lots`
    ({row key: lot id}) puts a row into another live lot than its list's own. Never lowers or removes stock here."""
    from .. import plans
    sync = _sync()
    value = sync.load_plan(db, plan_id, 'parts')
    done = plans.applied(db, 'sync', plan_id)
    if done:
        return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
    rows = sync._ticked(value, ticked)
    lots = {} if lots is None else lots
    if not isinstance(lots, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in lots.items()):
        raise errors.ValidationFailed('Send the lots as an object of row key to lot id')
    if set(lots) - {r['key'] for r in value['rows']}:
        raise errors.ValidationFailed('Unknown part-list rows')
    if via is None:
        via, actor = origin()
    stamp = store_now()
    receipt = dict(plan=plan_id, stock=[], stock_flags=[], lots_made=[], link_before=None, flag=None, flag_created=None, synced=[])
    with transaction(db), origins.adding('rebrickable'):
        done = plans.applied(db, 'sync', plan_id)
        if done:
            return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
        for lot in set(lots.values()):
            if not _live_lot(db, lot):
                raise errors.ValidationFailed('Choose a lot that exists')
        link_value = sync._setting(db, 'rebrickable', 'link', {})
        receipt['link_before'] = link_value
        own = dict(link_value.get('part_list_lots') or {})
        flag = receipt['flag'] = sync._flag(db, 'rebrickable', receipt) if rows else None
        for entry in value['lists']:
            needed = any(r['list_id'] == entry['id'] and r['key'] not in lots for r in rows)
            if needed and not _live_lot(db, own.get(str(entry['id']))):
                lot_id = uuid4().hex
                db.execute('INSERT INTO main.lot(id, name, note, created_at, updated_at) VALUES(?, ?, ?, ?, ?)',
                           (lot_id, entry['name'] or f'Rebrickable part list {entry["id"]}', 'From Rebrickable', stamp, stamp))
                audit(db, 'lot:' + lot_id, 'created', None, dict(db.execute('SELECT * FROM main.lot WHERE id=?', (lot_id,)).fetchone()), via=via, actor=actor)
                receipt['lots_made'].append(lot_id)
                own[str(entry['id'])] = lot_id
        names = {e['id']: e['name'] for e in value['lists']}
        for row in rows:
            lot_id = lots.get(row['key']) or own[str(row['list_id'])]
            change = stock.add_loose(db, item_id=row['item_id'], color_id=row['color_id'], quantity=row['count'], condition=None, lot_id=lot_id,
                                     via=via, actor=actor)
            receipt['stock'].append(change)
            if not db.execute('SELECT 1 FROM main.stock_flag WHERE stock_id=? AND flag_id=?', (change['id'], flag)).fetchone():
                db.execute('INSERT INTO main.stock_flag(stock_id, flag_id) VALUES(?, ?)', (change['id'], flag))
                receipt['stock_flags'].append([change['id'], flag])
            receipt['synced'].append(origins.touch(db, 'stock', change['id'], 'rebrickable', at=stamp, list_key=f'part:{row["list_id"]}',
                                                   list_name=names[row['list_id']]))
        if own != (link_value.get('part_list_lots') or {}):
            sync._put(db, 'rebrickable', 'link', dict(link_value, part_list_lots=own))
        counts = dict(rows=len(rows), pieces=sum(r['count'] for r in rows), lots_made=len(receipt['lots_made']))
        receipt['counts'] = counts
        audit(db, 'sync:' + plan_id, FIELD, None, receipt, via=via, actor=actor)
        event = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        plans.mark(db, 'sync', plan_id, dict(event_id=event, counts=counts, at=stamp), source='rebrickable', created_at=value['created_at'])
    value['applied'] = dict(event_id=event, counts=counts, at=stamp)
    sync._store_plan(db, value)
    return dict(event_id=event, already_applied=False, counts=counts)


def _undo(db, event, via, actor):
    """Reverse one part-list pull exactly: the stock it added, its tag links, the lots it made (still empty) and Last synced from."""
    r = json.loads(event['new_value'])
    sync = _sync()
    for entry in reversed(r['synced']):
        origins.untouch(db, entry)
    for change in reversed(r['stock']):
        try:
            stock.undo_added(db, change, via=via, actor=actor)
        except ValueError:
            raise ValueError('Something from this sync has changed since · undo the later change first') from None
        if [change['id'], r['flag']] in r['stock_flags']:
            db.execute('DELETE FROM main.stock_flag WHERE stock_id=? AND flag_id=?', (change['id'], r['flag']))
    stamp = store_now()
    for lot_id in r['lots_made']:
        if not db.execute('SELECT 1 FROM main.stock WHERE lot_id=? AND archived_at IS NULL', (lot_id,)).fetchone():
            db.execute('UPDATE main.lot SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, lot_id))
            audit(db, 'lot:' + lot_id, 'archived_at', None, stamp, via=via, actor=actor)
    if r.get('flag_created') and not any(db.execute(f'SELECT 1 FROM main.{t} WHERE flag_id=? LIMIT 1', (r['flag'],)).fetchone()
                                         for t in ('copy_flag', 'stock_flag', 'wish_flag')):
        db.execute('DELETE FROM main.flag WHERE id=?', (r['flag_created'],))
    current = sync._setting(db, 'rebrickable', 'link', {})
    sync._put(db, 'rebrickable', 'link', dict(current, part_list_lots=(r['link_before'] or {}).get('part_list_lots') or {}))
    audit(db, 'sync:' + r['plan'], 'undo', None, {'undoes': event['id']}, via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('sync', FIELD, _undo)
