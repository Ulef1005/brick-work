"""Identity admin on the 4.0 store (M.8i part 2, issue #110; design 3.2, 3.5, 3.6, 3.8): what needs a decision, and the decisions.

The Unresolved screen lists items, each with why it is there:

- `merge`: a local item that may be an item the catalogue knows: it carries `to_check` Rebrickable links (the migration's candidates), or it
  is BrickLink-born and a confirmed BrickLink link on another item names the same number (the rule-4 tie, 8.3). Resolved by `merge_item`.
- `link`: an item with a `to_check` link that is not such a candidate (a composition match of a figure, a same-number guess). `confirm_link`
  makes it the user's (`manual`), `reject_link` removes it.
- `status`: an `item_provider_status` of `to_check` (no candidate, migration, kind differs). A kind difference is resolved by
  `move_item_kind`; the others by `settle_status` (the user looked: it stays unmatched) or by a link or merge.
- `unidentified`: an item with no number from any provider that something references. Resolved by `add_link` (a typed BrickLink number) or a merge.

An item that nothing references and that has no candidate is not listed (a catalogue item with a `to_check` guess nobody owns, an undone
Add's leftover). Every decision is one transaction and one event with a receipt, and has an Undo (`core/undo`)."""
import json

from ..store4 import merge as moves
from ..store4.connect import has_catalogue, now
from ..store4.errors import MergeRefused
from ..store4.rowlog import RowLog
from . import collection, errors, items
from . import undo as undoing
from .admin import OPERATION_KEY, origin
from .transaction import transaction

CONFIRMED = ('manual', 'matched', 'inferred')
REFERENCED = ' OR '.join(f'EXISTS(SELECT 1 FROM main.{table} WHERE item_id=i.id)'
                         for table in ('copy', 'copy_figure', 'copy_part', 'stock', 'stock_part', 'wish'))
REASONS = ('merge', 'link', 'status', 'unidentified')


def _stores(db):
    return ('main', 'catalogue') if has_catalogue(db) else ('main',)


def _candidates(db, item):
    """Items a local item may be: `[dict(item_id, how)]`, one per item, same kind, never a merged item.

    `how` is `to_check` (a Rebrickable candidate link of the migration) or `same_number` (a confirmed BrickLink link on the item names this
    item's BrickLink number). A catalogue item not yet in the collection counts (it is projected when the merge needs it)."""
    found = {}
    for link in db.execute("SELECT provider_key, provider_kind FROM main.item_link WHERE item_id=? AND status='to_check' AND provider='rebrickable' ORDER BY id", (item['id'],)):
        for store in _stores(db):
            row = db.execute(f'SELECT id FROM {store}.item WHERE born_provider=\'rebrickable\' AND born_namespace=? AND born_key=? AND kind=?',
                             (link['provider_kind'], link['provider_key'], item['kind'])).fetchone()
            if row:
                found.setdefault(row['id'], 'to_check')
                break
    if item['born_provider'] == 'bricklink' and item['born_key'] is not None:
        for store in _stores(db):
            for row in db.execute(f'''SELECT DISTINCT k.item_id FROM {store}.item_link k WHERE k.provider='bricklink' AND k.provider_kind=? AND k.provider_key=?
                                      AND k.status IN ({",".join("?" * len(CONFIRMED))}) AND k.item_id!=? ORDER BY k.item_id''',
                                  (item['born_namespace'], item['born_key'], *CONFIRMED, item['id'])):
                found.setdefault(row['item_id'], 'same_number')
    result = []
    for item_id, how in sorted(found.items()):
        other = db.execute('SELECT kind, merged_into FROM main.item WHERE id=?', (item_id,)).fetchone()
        if other is None and has_catalogue(db):
            other = db.execute('SELECT kind, NULL AS merged_into FROM catalogue.item WHERE id=?', (item_id,)).fetchone()
        if other is not None and other['merged_into'] is None and other['kind'] == item['kind']:
            result.append(dict(item_id=item_id, how=how))
    return result


def _scan(db):
    """`{item id: dict(item, reasons, candidates, links, statuses)}` for every item that needs a decision, without names or pictures."""
    table = {}

    def entry(row):
        return table.setdefault(row['id'], dict(item=row, reasons=[], candidates=[], links=[], statuses=[]))

    local = db.execute('''SELECT i.* FROM main.item i WHERE i.origin='local' AND i.merged_into IS NULL ORDER BY i.id''').fetchall()
    for item in local:
        candidates = _candidates(db, item)
        if candidates:
            entry(item)['candidates'] = candidates
            entry(item)['reasons'].append('merge')
    # to_check links: on a local item the Rebrickable ones are its merge candidates (listed under `candidates`); every other one asks to be
    # confirmed or rejected
    merging = {i for i, e in table.items() if e['candidates']}
    for link in db.execute(f'''SELECT l.*, i.origin AS item_origin FROM main.item_link l JOIN main.item i ON i.id=l.item_id
                               WHERE l.status='to_check' AND i.merged_into IS NULL AND (i.origin='local' OR {REFERENCED}) ORDER BY l.id'''):
        if link['item_origin'] == 'local' and link['provider'] == 'rebrickable' and link['item_id'] in merging:
            continue
        e = entry(db.execute('SELECT * FROM main.item WHERE id=?', (link['item_id'],)).fetchone())
        e['links'].append(dict(link))
        if 'link' not in e['reasons']:
            e['reasons'].append('link')
    for status in db.execute(f'''SELECT s.*, i.origin AS item_origin FROM main.item_provider_status s JOIN main.item i ON i.id=s.item_id
                                 WHERE s.status='to_check' AND i.merged_into IS NULL AND (i.origin='local' OR {REFERENCED}) ORDER BY s.item_id, s.reason'''):
        e = entry(db.execute('SELECT * FROM main.item WHERE id=?', (status['item_id'],)).fetchone())
        e['statuses'].append(dict(status))
        if 'status' not in e['reasons']:
            e['reasons'].append('status')
    for item in db.execute(f'''SELECT i.* FROM main.item i WHERE i.origin='local' AND i.born_key IS NULL AND i.merged_into IS NULL AND NOT {items.identified_sql('i')} AND ({REFERENCED}) ORDER BY i.id'''):
        e = entry(item)
        e['reasons'].append('unidentified')
    return table


def count_unresolved(db):
    """How many items `unresolved` lists."""
    return len(_scan(db))


def reason_counts(db):
    """`{reason: items}` over the list (an item with two reasons counts under both)."""
    counts = dict.fromkeys(REASONS, 0)
    for e in _scan(db).values():
        for reason in e['reasons']:
            counts[reason] += 1
    return counts


def _evidence(status):
    try:
        value = json.loads(status['evidence_json'] or '{}')
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def unresolved(db):
    """The list the Unresolved screen shows: one dict per item, ordered by kind and name.

    `item_id`, `kind`, `name`, `number_text`, `image`, `local`, `reasons`, `candidates` (with name, number and picture), `links` (the `to_check`
    links to confirm or reject), `statuses` and `references` (collection rows that name the item)."""
    scan = _scan(db)
    if not scan:
        return []
    wanted = list(scan) + [c['item_id'] for e in scan.values() for c in e['candidates']]
    decorated = {r['item_id']: r for r in collection.decorate(db, [dict(item_id=i) for i in dict.fromkeys(wanted)])}
    references = {}
    for table in ('copy', 'copy_figure', 'copy_part', 'stock', 'stock_part', 'wish'):
        for r in db.execute(f'SELECT item_id, count(*) AS n FROM main.{table} WHERE item_id IN (SELECT value FROM json_each(?)) GROUP BY item_id',
                            (json.dumps(sorted(scan)),)):
            references[r['item_id']] = references.get(r['item_id'], 0) + r['n']
    result = []
    for item_id, e in scan.items():
        row = decorated[item_id]
        candidates = []
        for c in e['candidates']:
            other = decorated.get(c['item_id'], {})
            candidates.append(dict(c, name=other.get('name'), number_text=other.get('number_text'), item_no=other.get('number_text') or '', image=other.get('image'),
                                   lines=db.execute('SELECT count(*) FROM main.copy_part WHERE item_id=? AND retired_at IS NULL', (c['item_id'],)).fetchone()[0]))
        statuses = [dict(s, to=_evidence(s).get('to')) for s in e['statuses']]
        result.append(dict(item_id=item_id, kind=e['item']['kind'], name=row.get('name'), number_text=row.get('number_text'), item_no=row.get('number_text') or '',
                           image=row.get('image'), local=e['item']['origin'] == 'local', reasons=e['reasons'], candidates=candidates, links=e['links'], statuses=statuses,
                           references=references.get(item_id, 0)))
    result.sort(key=lambda r: (r['kind'], (r['name'] or '').lower(), r['item_id']))
    return result


def find_target(db, loser, text):
    """The one item a typed number means for `loser` (same kind, not itself); a ValidationFailed says when it is none or several."""
    row = db.execute('SELECT kind FROM main.item WHERE id=?', (loser,)).fetchone()
    if row is None:
        raise errors.NotFound(f'No item {loser}')
    found = [f for f in items.find(db, row['kind'], text) if f['item_id'] != loser]
    if not found:
        raise errors.ValidationFailed(f'No {row["kind"]} has the number {text!r}')
    if len(found) > 1:
        raise errors.ValidationFailed(f'{text!r} names several items ({", ".join(str(f["item_id"]) for f in found[:5])}) · pick one of the candidates')
    return found[0]['item_id']


# ---------- decisions ----------

def _run(db, function, *args, **kwargs):
    via, actor = origin()
    try:
        with transaction(db):
            return function(db, *args, via=via, actor=actor, operation_key=OPERATION_KEY.get(), **kwargs)
    except MergeRefused as exc:
        raise errors.Conflict(str(exc)) from None


def merge_item(db, loser, survivor):
    """Merge the local item `loser` into `survivor` (one transaction, one event, one receipt). Returns `{merge_id, event_id, counts}`."""
    return _run(db, moves.merge_in, int(loser), int(survivor))


def unmerge_item(db, merge_id):
    return _run(db, moves.unmerge_in, int(merge_id))


def move_item_kind(db, item_id, kind):
    """Change an item's kind with its rows (design 3.5). Returns `{event_id, from, to, counts}`."""
    return _run(db, moves.move_kind_in, int(item_id), kind)


def _logged(db, entity, ident, field, old, new, log, *, via, actor, operation_key):
    """Write the event of a logged change; its `new_value` is the receipt (`{changes: [...], ...}`)."""
    return moves._event(db, via, actor, operation_key, entity, ident, field, old, dict(new, changes=log.changes))


def confirm_link(db, link_id):
    """A `to_check` link becomes the user's (`manual`). A Rebrickable candidate of a local item is not confirmed: that is a merge."""
    def action(db, *, via, actor, operation_key):
        log = RowLog(db)
        rows = log.select('item_link', 'id=?', (link_id,))
        if not rows or rows[0]['status'] != 'to_check':
            raise errors.Conflict('This link is no longer to check')
        link = rows[0]
        item = db.execute('SELECT origin FROM main.item WHERE id=?', (link['item_id'],)).fetchone()
        if link['provider'] == 'rebrickable' and item['origin'] == 'local':
            raise errors.ValidationFailed('This says the local item is a catalogue item · merge it into that item instead')
        log.update('item_link', link, status='manual', method='user', origin='user', decided_at=now(), decided_by='user')
        return dict(event_id=_logged(db, 'item_link', link_id, 'confirm', 'to_check', dict(item=link['item_id']), log, via=via, actor=actor,
                                     operation_key=operation_key), item_id=link['item_id'])
    return _in(db, action)


def reject_link(db, link_id):
    """Remove a `to_check` link (Undo puts it back)."""
    def action(db, *, via, actor, operation_key):
        log = RowLog(db)
        rows = log.select('item_link', 'id=?', (link_id,))
        if not rows or rows[0]['status'] != 'to_check':
            raise errors.Conflict('This link is no longer to check')
        log.delete('item_link', rows[0])
        return dict(event_id=_logged(db, 'item_link', link_id, 'reject', 'to_check', dict(item=rows[0]['item_id']), log, via=via, actor=actor,
                                     operation_key=operation_key), item_id=rows[0]['item_id'])
    return _in(db, action)


def add_link(db, item_id, number):
    """Link an item to a typed BrickLink number (`manual`). Refused when the item has that number already, or another item holds it: that is a merge."""
    number = (number or '').strip()
    if not number or len(number) > 40 or any(c.isspace() for c in number):
        raise errors.ValidationFailed('Type a BrickLink number without spaces')

    def action(db, *, via, actor, operation_key):
        item = db.execute('SELECT * FROM main.item WHERE id=? AND merged_into IS NULL', (item_id,)).fetchone()
        if item is None:
            raise errors.NotFound(f'No item {item_id}')
        letter = items.type_of_kind(item['kind'])
        if db.execute("SELECT 1 FROM main.item_link WHERE item_id=? AND provider='bricklink' AND provider_kind=? AND provider_key=? AND color_id IS NULL",
                      (item_id, letter, number)).fetchone():
            raise errors.Conflict(f'The item has the BrickLink number {number} already')
        others = [r['item_id'] for store in _stores(db) for r in db.execute(
            f"SELECT item_id FROM {store}.item_link WHERE provider='bricklink' AND provider_kind=? AND provider_key=? AND status IN ('manual','matched','inferred') AND item_id!=?",
            (letter, number, item_id))]
        if others:
            raise errors.Conflict(f'BrickLink {number} belongs to item {others[0]} already · merge into it instead')
        log = RowLog(db)
        log.insert('item_link', item_id=item_id, color_id=None, provider='bricklink', provider_kind=letter, provider_key=number, status='manual',
                   method='user', origin='user', preferred=0, evidence_digest=None, evidence_json=None, catalogue_build_id=None, decided_at=now(), decided_by='user')
        return dict(event_id=_logged(db, 'item_link', item_id, 'add', None, dict(item=item_id, number=number), log, via=via, actor=actor,
                                     operation_key=operation_key), item_id=item_id)
    return _in(db, action)


def settle_status(db, item_id, provider, reason):
    """The user looked and the item stays unmatched: a `to_check` status becomes `unmatched`."""
    def action(db, *, via, actor, operation_key):
        log = RowLog(db)
        rows = log.select('item_provider_status', 'item_id=? AND provider=? AND reason=?', (item_id, provider, reason))
        if not rows or rows[0]['status'] != 'to_check':
            raise errors.Conflict('This is no longer to check')
        log.update('item_provider_status', rows[0], status='unmatched', checked_at=now())
        return dict(event_id=_logged(db, 'item_provider_status', item_id, 'settle', 'to_check', dict(item=item_id, provider=provider, reason=reason),
                                     log, via=via, actor=actor, operation_key=operation_key), item_id=item_id)
    return _in(db, action)


def _in(db, action):
    via, actor = origin()
    with transaction(db):
        return action(db, via=via, actor=actor, operation_key=OPERATION_KEY.get())


# ---------- Undo ----------

def _undo_merge(db, event, via, actor):
    row = db.execute('SELECT id FROM main.item_merge WHERE event_id=?', (event['id'],)).fetchone()
    if row is None:
        raise errors.UndoBlocked('This merge has no record')
    return moves.unmerge_in(db, row['id'], via=via, actor=actor, operation_key=OPERATION_KEY.get())


def _undo_kind_move(db, event, via, actor):
    return moves.undo_kind_move_in(db, event['id'], via=via, actor=actor, operation_key=OPERATION_KEY.get())


def _undo_logged(db, event, via, actor):
    """Put a logged decision back: refused when any row it changed differs now."""
    receipt = json.loads(event['new_value'])
    log = RowLog(db, receipt['changes'])
    changed = log.verify()
    if changed is not None:
        raise errors.UndoBlocked(f'{changed["t"]} changed since this decision · undo the later change first')
    db.execute('PRAGMA defer_foreign_keys=ON')
    log.restore()
    undo = moves._event(db, via, actor, OPERATION_KEY.get(), event['entity_kind'], event['entity_id'], event['field'] + '_undo', None, dict(undoes=event['id']))
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo))
    return dict(event_id=undo)


undoing.register('item', 'merge', _undo_merge)
undoing.register('item', moves.KIND_FIELD, _undo_kind_move)
for _entity, _field in (('item_link', 'confirm'), ('item_link', 'reject'), ('item_link', 'add'), ('item_provider_status', 'settle')):
    undoing.register(_entity, _field, _undo_logged)
