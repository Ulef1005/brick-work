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
import re
import sqlite3

from ..store4 import merge as moves
from ..store4.connect import has_catalogue, now
from ..store4.errors import MergeRefused
from ..store4.rowlog import RowLog
from . import add, collection, errors, items
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

    `item_id`, `kind`, `name`, `number_text`, `image`, `local`, `reasons`, `facets` (what the screen filters by: the reasons, with `status` replaced by
    the status reasons `no_candidate`, `kind_differs`, `migration`), `candidates` (with name, number, picture and `uses`: what the user's copies
    hold of that candidate), `links` (the `to_check` links to confirm or reject), `statuses`, `references` (collection rows that name the item)
    and `uses`."""
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
                                   lines=db.execute('SELECT count(*) FROM main.copy_part WHERE item_id=? AND retired_at IS NULL', (c['item_id'],)).fetchone()[0],
                                   uses=uses(db, c['item_id'])))
        statuses = [dict(s, to=_evidence(s).get('to')) for s in e['statuses']]
        result.append(dict(item_id=item_id, kind=e['item']['kind'], name=row.get('name'), number_text=row.get('number_text'), item_no=row.get('number_text') or '',
                           image=row.get('image'), local=e['item']['origin'] == 'local', reasons=e['reasons'], candidates=candidates, links=e['links'], statuses=statuses,
                           references=references.get(item_id, 0), uses=uses(db, item_id),
                           facets=list(dict.fromkeys([r for r in e['reasons'] if r != 'status'] + [x['reason'] for x in statuses]))))
    result.sort(key=lambda r: (r['kind'], (r['name'] or '').lower(), r['item_id']))
    return result


def uses(db, item_id):
    """What the user's rows hold of an item: `dict(copies, lines, stock, wishes)` (copies that hold it, live part lines, loose stock rows, live wishes).

    On a merge row's candidates this says which candidate the user's copies already use (the M.10 note: the migrated part lists name it)."""
    one = lambda sql: db.execute(sql, (item_id,)).fetchone()[0]
    return dict(copies=one('SELECT count(DISTINCT copy_id) FROM main.copy_part WHERE item_id=? AND retired_at IS NULL')
                + one('SELECT count(*) FROM main.copy WHERE item_id=?'),
                lines=one('SELECT count(*) FROM main.copy_part WHERE item_id=? AND retired_at IS NULL')
                + one('SELECT count(*) FROM main.copy_figure WHERE item_id=? AND retired_at IS NULL'),
                stock=one('SELECT count(*) FROM main.stock WHERE item_id=? AND archived_at IS NULL'),
                wishes=one('SELECT count(*) FROM main.wish WHERE item_id=? AND archived_at IS NULL'))


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


def set_preferred(db, link_id, color_id=None, item_id=None):
    """Make a link the preferred one of its item and provider: for every colour (`color_id` None; the link must hold for every colour), or for
    one colour (design 3.2: a new colour-scoped `manual` row, or the item's scoped row of that key made preferred). The previous preferred link
    of that scope loses the mark. `item_id`, when given, must be the link's item (the item page names its own). One logged change, Undo puts
    every row back."""
    def action(db, *, via, actor, operation_key):
        log = RowLog(db)
        rows = log.select('item_link', 'id=?', (link_id,))
        if not rows:
            raise errors.NotFound(f'No link {link_id}')
        link = rows[0]
        if item_id is not None and link['item_id'] != item_id:
            raise errors.NotFound(f'Link {link_id} does not belong to item {item_id}')
        if link['status'] == 'to_check':
            raise errors.Conflict('Confirm this link before choosing it')
        scope = color_id if color_id is not None else link['color_id']
        if color_id is None and link['color_id'] is not None:
            raise errors.ValidationFailed('This link holds for one colour only · choose it for that colour')
        item = db.execute('SELECT id FROM main.item WHERE id=? AND merged_into IS NULL', (link['item_id'],)).fetchone()
        if item is None:
            raise errors.NotFound(f'No item {link["item_id"]}')
        if scope is not None and not db.execute('SELECT 1 FROM main.color WHERE id=?', (scope,)).fetchone():
            raise errors.ValidationFailed('Unknown colour')
        same = [r for r in log.select('item_link', 'item_id=? AND provider=? AND coalesce(color_id,0)=?', (link['item_id'], link['provider'], scope or 0))]
        target = next((r for r in same if r['provider_kind'] == link['provider_kind'] and r['provider_key'] == link['provider_key']), None)
        for other in same:
            if other['preferred'] and (target is None or other['id'] != target['id']):
                log.update('item_link', other, preferred=0)
        if target is not None:
            sets = {} if target['preferred'] else dict(preferred=1, decided_at=now(), decided_by='user')
            if scope is not None and (target['status'] != 'manual' or target['origin'] != 'user'):
                sets.update(status='manual', method='user', origin='user', decided_at=now(), decided_by='user')       # the choice is the user's, as an insert's is
            if sets:
                log.update('item_link', target, **sets)
        else:
            log.insert('item_link', item_id=link['item_id'], color_id=scope, provider=link['provider'], provider_kind=link['provider_kind'],
                       provider_key=link['provider_key'], status='manual', method='user', origin='user', preferred=1, evidence_digest=None,
                       evidence_json=None, catalogue_build_id=None, decided_at=now(), decided_by='user')
        return dict(event_id=_logged(db, 'item_link', link['item_id'], 'prefer', None, dict(item=link['item_id'], key=link['provider_key'], colour=scope),
                                     log, via=via, actor=actor, operation_key=operation_key), item_id=link['item_id'])
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
for _entity, _field in (('item_link', 'confirm'), ('item_link', 'reject'), ('item_link', 'add'), ('item_link', 'prefer'), ('item_provider_status', 'settle')):
    undoing.register(_entity, _field, _undo_logged)


# ---------- reads for the item page (design 3.2, 3.6, 3.8; M.10 batch B) ----------

PROVIDERS = (('bricklink', 'BrickLink'), ('rebrickable', 'Rebrickable'))      # LEGO numbers matter for colours only; item links of that provider stay in the data, not on the page
STATUS_WORDS = {'matched': 'matched', 'inferred': 'inferred', 'manual': 'manual', 'to_check': 'to check', 'born': 'catalogue number', 'own': 'own number'}
REASON_WORDS = {'no_match': 'No match found', 'no_candidate': 'To check · no candidate', 'kind_differs': 'To check · the kind differs',
                'migration': 'To check · from the migration'}
REASON_NOTES = {'no_match': 'Looked, and the provider has nothing under this number.',
                'no_candidate': 'Nothing could be placed for it yet. Add a link, or merge it into a catalogue item.',
                'kind_differs': 'The catalogue and the provider disagree on what kind of item this is.',
                'migration': 'Carried over from Brick Work 3 without a match. Add a link, or merge it into a catalogue item.'}
TABLE_WORDS = {'copy': 'copies', 'copy_figure': 'figure lines', 'copy_part': 'part lines', 'stock': 'loose stock rows', 'stock_part': 'figure part lines',
               'wish': 'wishes', 'price_observation': 'prices', 'price_current': 'current prices', 'price_watch': 'price watches', 'item_link': 'links',
               'item_provider_status': 'provider notes', 'item_property': 'properties', 'picture': 'pictures', 'photo': 'photos',
               'instruction_file': 'instruction files', 'order_line': 'order lines', 'allocation': 'allocations', 'job': 'jobs',
               'fetched_inventory_part': 'fetched part list lines', 'fetched_inventory_figure': 'fetched figure lines', 'fetched_inventory': 'fetched part lists',
               'set_preference': 'part list choices', 'identification_action': 'identification notes', 'stock_transfer': 'stock transfers'}
CONFIRMED_STATUS = ('manual', 'matched', 'inferred')
PREVIEW_WAIT_MS = 1500


def _store_of(db, item_id):
    return 'main' if db.execute('SELECT 1 FROM main.item WHERE id=?', (item_id,)).fetchone() else 'catalogue'


def _colours(db, ids):
    """`{colour id: dict(name, rgb, ink)}` from the collection's colours, else the catalogue's."""
    from . import add
    found = {}
    for store in _stores(db):
        left = [i for i in ids if i is not None and i not in found]
        for r in db.execute(f'SELECT id, name, rgb FROM {store}.color WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(left),)):
            found.setdefault(r['id'], dict(name=r['name'], rgb=r['rgb'], ink=add.colour_ink(r['rgb'])))
    return found


def merge_blocker(db, item_id):
    """Why an item cannot be merged away, in plain words, or None (design 3.6: a local item, or one the catalogue has retired)."""
    row = db.execute('SELECT origin, catalogue_retired_at, merged_into FROM main.item WHERE id=?', (item_id,)).fetchone()
    if row is None:
        return 'This item is in the catalogue and not in your collection yet, so it stays as it is.'
    if row['merged_into'] is not None:
        return 'This item is merged into another one already.'
    if row['origin'] == 'catalogue' and row['catalogue_retired_at'] is None:
        return 'This item is part of the catalogue, so it stays. Only items you added yourself, or ones the catalogue has retired, can be merged into another.'
    return None


def links(db, item_id, colour=None):
    """The Links card of an item page: per provider the keys with status, colour scope, preferred and which one answers for `colour`, plus the
    provider status rows that have no key. `editable` is False for an item that is only in the catalogue (nothing to write to yet)."""
    from ..store4 import identity as ident
    store = _store_of(db, item_id)
    item = db.execute(f'SELECT * FROM {store}.item WHERE id=?', (item_id,)).fetchone()
    if item is None:
        raise errors.NotFound(f'No item {item_id}')
    origin_of = item['origin'] if 'origin' in item.keys() else 'catalogue'
    rows = [dict(r) for r in db.execute(f'SELECT * FROM {store}.item_link WHERE item_id=? ORDER BY color_id IS NOT NULL, provider_key', (item_id,))]
    statuses = [dict(r) for r in db.execute('SELECT * FROM main.item_provider_status WHERE item_id=? ORDER BY provider, reason', (item_id,))] if store == 'main' else []   # the catalogue file has no such table
    colours = _colours(db, {r['color_id'] for r in rows} | {colour})
    result = []
    for provider, label in PROVIDERS:
        mine = [r for r in rows if r['provider'] == provider]
        confirmed = [r for r in mine if r['status'] in CONFIRMED_STATUS]
        used = ident.best_item_link(confirmed, colour) if confirmed else None
        entries = []
        if item['born_provider'] == provider and item['born_key'] is not None and not any(r['provider_key'] == item['born_key'] for r in mine):
            entries.append(dict(id=None, key=item['born_key'], kind=item['born_namespace'], status='born' if origin_of == 'catalogue' else 'own', preferred=False,
                                color_id=None, scope=None, in_use=used is None))
        for r in mine:
            scope = dict(id=r['color_id'], **colours[r['color_id']]) if r['color_id'] is not None and r['color_id'] in colours else None
            entries.append(dict(id=r['id'], key=r['provider_key'], kind=r['provider_kind'], status=r['status'], method=r['method'], origin=r['origin'],
                                preferred=bool(r['preferred']), color_id=r['color_id'], scope=scope, in_use=used is not None and used['provider_key'] == r['provider_key']
                                and used['color_id'] == r['color_id'] and used['provider_kind'] == r['provider_kind']))
        for entry in entries:
            entry['status_word'] = STATUS_WORDS[entry['status']]
        unscoped = [e for e in entries if e['color_id'] is None and e['status'] in CONFIRMED_STATUS]
        result.append(dict(provider=provider, label=label, links=entries, choose=len(unscoped) > 1,
                           statuses=[dict(s, word=REASON_WORDS[s['reason']], note=REASON_NOTES[s['reason']], to=_evidence(s).get('to'))
                                     for s in statuses if s['provider'] == provider]))
    shown = result
    return dict(item_id=item_id, kind=item['kind'], editable=store == 'main', colour=colour, colour_name=(colours.get(colour) or {}).get('name'),
                providers=shown, to_check=sum(1 for r in rows if r['status'] == 'to_check') + sum(1 for s in statuses if s['status'] == 'to_check'),
                local=origin_of == 'local', unidentified=not _identified(db, item_id, store, item), merge_blocker=merge_blocker(db, item_id))


def _identified(db, item_id, store, item):
    if item['born_key'] is not None:
        return True
    return bool(db.execute(f"SELECT 1 FROM {store}.item_link WHERE item_id=? AND provider='bricklink' AND status IN ('manual','matched','inferred')", (item_id,)).fetchone())


def explain_refusal(db, text, loser=None, survivor=None):
    """A `MergeRefused` message in plain words for the merge screen (the refusals of design 3.6)."""
    def row_of(item_id):
        for store in _stores(db):
            row = db.execute(f'SELECT name, born_key, kind FROM {store}.item WHERE id=?', (item_id,)).fetchone()
            if row:
                return row
        return None

    def name(item_id):
        row = row_of(item_id)
        return (row['name'] or row['born_key'] or f'item {item_id}') if row else f'item {item_id}'
    if 'live catalogue item' in text:
        return f'{name(loser)} is part of the catalogue, so it cannot be merged into another item. Only items you added yourself, or ones the catalogue has retired, can be.'
    if 'merged itself' in text:
        return f'{name(survivor)} was merged into another item already. Pick the item it was merged into.'
    if 'merged already' in text:
        return f'{name(loser)} is merged into another item already.'
    if 'into itself' in text:
        return 'An item cannot be merged into itself. Pick another item.'
    if ' is a ' in text and 'merges only into one of its own kind' in text:
        a, b = row_of(loser), row_of(survivor)
        return f'{name(loser)} is a {a["kind"]} and {name(survivor)} is a {b["kind"]}. An item merges only into one of its own kind; change the kind first.'
    if 'still in flight' in text or 'in flight' in text:
        return 'A job for one of these items is still running. Let it finish, or cancel it in Jobs, then merge.'
    if ' holds ' in text and 'for both items' in text:
        sentence = re.sub(r'^copy \S+ holds', 'One of your copies holds', text.split(' · ')[0])
        sentence = re.sub(r'^loose figure \S+ holds', 'One of your loose figures holds', sentence)
        sentence = re.sub(r'^fetched (part|figure) list \S+ holds', r'A fetched \1 list holds', sentence)
        return sentence + '. Correct that line by hand first, then merge again.'
    if 'dangling' in text:
        return 'The merge would leave a row pointing at nothing, so nothing was changed.'
    return text[0].upper() + text[1:]


def merge_preview(db, loser, survivor):
    """What `merge_in` would do, without doing it: runs the merge in a transaction and rolls it back (a write connection is needed).

    `dict(ok, refusal, rows, dropped, counts)`: `rows` = `[(table words, rows changed)]` biggest first; `dropped` = rows the survivor already
    has (kept as they are, the loser's go); `refusal` = plain-words reason, or None."""
    via, actor = origin()
    out = dict(ok=False, refusal=None, busy=False, rows=[], dropped=0, counts={})
    wait = db.execute('PRAGMA busy_timeout').fetchone()[0]
    db.execute(f'PRAGMA busy_timeout={PREVIEW_WAIT_MS}')            # a screen must not hang behind a sync or a job that holds the write lock
    try:
        db.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError as exc:
        if 'locked' not in str(exc) and 'busy' not in str(exc):
            raise
        out['busy'] = True
        out['refusal'] = 'Brick Work is busy with something else, such as a sync or a job. Try again in a moment.'
        return out
    finally:
        db.execute(f'PRAGMA busy_timeout={wait}')
    try:
        try:
            counts = moves.merge_in(db, int(loser), int(survivor), via=via, actor=actor, operation_key=None)['counts']
        except MergeRefused as exc:
            out['refusal'] = explain_refusal(db, str(exc), int(loser), int(survivor))
        else:
            rows = [(TABLE_WORDS.get(t, t.replace('_', ' ')), c.get('moved', 0) + c.get('inserted', 0)) for t, c in counts.items() if t != 'item']
            out.update(ok=True, counts=counts, rows=sorted([r for r in rows if r[1]], key=lambda r: (-r[1], r[0])),
                       dropped=sum(c.get('deleted', 0) for c in counts.values()))
    finally:
        db.execute('ROLLBACK')
    return out


def unmerge_blocker(db, merge_id):
    """Why a merge cannot be taken back, in plain words, or None: the checks of `unmerge_in`, read-only."""
    merge = db.execute('SELECT * FROM main.item_merge WHERE id=?', (merge_id,)).fetchone()
    if merge is None or merge['undone_at'] is not None:
        return 'This merge was undone already.'
    loser, survivor = merge['merged_id'], merge['survivor_id']
    row = db.execute('SELECT merged_into FROM main.item WHERE id=?', (loser,)).fetchone()
    redirect = db.execute('SELECT new_id FROM main.item_redirect WHERE old_id=?', (loser,)).fetchone()
    if row is None or row['merged_into'] != survivor or redirect is None or redirect['new_id'] != survivor:
        return 'The item is not merged into this one any more.'
    try:
        moves._refuse_active_jobs(db, loser, survivor)
    except MergeRefused:
        return 'A job for one of these items is still running. Let it finish, or cancel it in Jobs, then unmerge.'
    receipt = json.loads(merge['receipt_json'])
    log = RowLog(db, receipt['changes'] if isinstance(receipt, dict) else receipt)
    changed = log.verify()
    if changed is not None:
        return (f'The {TABLE_WORDS.get(changed["t"], changed["t"].replace("_", " "))} it moved changed after the merge, so they cannot be put back safely. '
                'Undo the later change first, then unmerge.')
    known = receipt.get('dependents', {}) if isinstance(receipt, dict) else {}
    for table, keys in moves._dependents(db, log).items():
        if set(keys) - set(known.get(table, ())):
            return (f'New {TABLE_WORDS.get(table, table.replace("_", " "))} were added to rows the merge moved, so they cannot be put back safely. '
                    'Undo the later change first, then unmerge.')
    return None


def merged_into(db, item_id):
    """The merges still standing into an item: `[dict(merge_id, merged_id, name, number_text, at, via, blocker, counts)]`, newest first."""
    result = []
    for m in db.execute('SELECT * FROM main.item_merge WHERE survivor_id=? AND undone_at IS NULL ORDER BY id DESC', (item_id,)):
        shown = collection.decorate(db, [dict(item_id=m['merged_id'])])[0]
        counts = {}
        try:
            receipt = json.loads(m['receipt_json'])
            for change in receipt['changes']:
                counts[change['t']] = counts.get(change['t'], 0) + 1
        except (ValueError, KeyError, TypeError):
            pass
        rows = sorted(((TABLE_WORDS.get(t, t), n) for t, n in counts.items() if t != 'item'), key=lambda r: (-r[1], r[0]))
        result.append(dict(merge_id=m['id'], merged_id=m['merged_id'], name=shown.get('name'), number_text=shown.get('number_text'), image=shown.get('image'),
                           at=m['at'], via=m['via'], blocker=unmerge_blocker(db, m['id']), rows=rows[:4]))
    return result


def survivors(db, loser, text, limit=12):
    """Items the user may merge `loser` into: those a typed number finds, or (with no text) the candidates the Unresolved list names.
    `[dict(item_id, name, number_text, image, kind, how)]`, same kind as the loser, never the loser."""
    row = db.execute('SELECT * FROM main.item WHERE id=?', (loser,)).fetchone()
    if row is None:
        raise errors.NotFound(f'No item {loser}')
    text = (text or '').strip()
    if text:
        found = [dict(item_id=f['item_id'], how=f['matched_by']) for f in items.find(db, row['kind'], text, limit=limit + 1)]      # exact numbers first
        try:                                                        # then the Add search: names and sizes (without an active catalogue it cannot run)
            found += [dict(item_id=h['item_id'], how='search') for h in add.search(db, row['kind'], text)['items']]
        except errors.CatalogueNotLoaded:
            pass
        tokens = re.findall(r'[^\W_]+', text.lower())              # local items by name or number, which the size search leaves out
        if tokens:
            clause = ' AND '.join("(lower(name) LIKE ? ESCAPE '\\' OR lower(coalesce(born_key, '')) LIKE ? ESCAPE '\\')" for _ in tokens)
            args = [x for t in tokens for x in ('%' + add._escape(t) + '%',) * 2]
            found += [dict(item_id=r[0], how='search') for r in db.execute(
                f"SELECT id FROM main.item WHERE origin='local' AND kind=? AND merged_into IS NULL AND {clause} ORDER BY name, id LIMIT 20", (row['kind'], *args))]
        seen = {loser}
        found = [f for f in found if not (f['item_id'] in seen or seen.add(f['item_id']))][:limit]
    else:
        found = [dict(item_id=c['item_id'], how=c['how']) for c in _candidates(db, row)]
    decorated = {r['item_id']: r for r in collection.decorate(db, [dict(item_id=f['item_id']) for f in found])}
    return [dict(f, name=decorated[f['item_id']].get('name'), number_text=decorated[f['item_id']].get('number_text'), image=decorated[f['item_id']].get('image'),
                 kind=decorated[f['item_id']].get('kind'), year=decorated[f['item_id']].get('year')) for f in found]
