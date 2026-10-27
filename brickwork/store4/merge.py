"""Merge, unmerge and the kind move of an item (M.8i part 2, issue #110; design 3.5, 3.6, 3.8).

`merge_in(loser, survivor)` moves every reference to the loser onto the survivor in one transaction, sets `merged_into`, writes the
redirect, the `item_merge` row with its receipt and one event. The receipt is a `RowLog`: every row changed, deleted or inserted, as it
was and as it became, so `unmerge_in` can refuse when any of them differs now and otherwise put them all back exactly.

What a merge decides where two rows meet (the rules of 3.6; each is also in `docs/how-to/merge-items.md`):

- **summed**: loose stock meeting on its merge key (`stock_merge_key`) adds quantity, missing and damaged to the survivor's row and archives
  the loser's, as a stock edit does; a live wish meeting on `wish_live_key` adds quantity and is archived the same way.
- **the survivor's row stays, the loser's goes**: `item_link` of the same provider key and colour (a `manual` link of the loser upgrades
  the survivor's), `item_provider_status` of the same provider and reason, `item_property`, `picture`, `set_preference`, `price_current`,
  `price_watch`. A cached or derived row is not worth a conflict; the receipt holds the deleted row.
- **the merge is the decision**: the loser's `to_check` links and statuses are dropped (they asked for exactly this decision).
- **numbers**: the loser's fetched part lists are renumbered after the survivor's and are not `latest` where the survivor has one.
- **the loser's own number is kept**: a BrickLink- or Rebrickable-born loser leaves an `inferred` link of its born key on the survivor
  when the survivor holds none, so the number still finds the item.
- **refused**: a copy, a loose figure or a fetched list that holds lines for both items (`copy_figure`, `copy_part`, `stock_part`,
  `fetched_inventory_part`, `fetched_inventory_figure`): the lines carry counts, checks and references that no rule can add up
  silently. The message names the copy; fix it by hand first.

The kind move (3.5) changes an item's kind when the schema's guards refuse a plain UPDATE because rows reference the old kind. The
rows of the old kind are replaced by rows of the new one (`copy` <-> `stock`, `stock` and `wish` with the same id and the new kind),
under one receipt, and `move_kind_in` refuses whatever it would lose."""
import json
import uuid

from .audit import value_text
from .connect import now
from .errors import MergeRefused, NotInCatalogue, Store4Error
from .rowlog import RowLog

MOVES = (('copy', 'item_id'), ('copy_figure', 'item_id'), ('copy_part', 'item_id'), ('stock_part', 'item_id'),
         ('fetched_inventory_part', 'item_id'), ('fetched_inventory_figure', 'item_id'), ('allocation', 'item_id'),
         ('identification_action', 'item_id'), ('instruction_file', 'item_id'), ('job', 'item_id'), ('order_line', 'item_id'),
         ('order_line', 'sticker_set_item_id'), ('photo', 'item_id'), ('price_observation', 'item_id'), ('stock_transfer', 'item_id'))
SHADOWED = (('item_property', ('key', 'source')), ('picture', ('color_id', 'source', 'kind')), ('set_preference', ()),
            ('price_current', ('color_id', 'condition', 'guide', 'slot', 'region', 'currency')), ('price_watch', ('color_id', 'condition')))


def _need_transaction(db, what):
    if not db.in_transaction:
        raise Store4Error(f'{what} needs the caller\'s open write transaction; use the version that opens its own')


def _event(db, via, actor, operation_key, kind, ident, field, old=None, new=None):
    text = value_text
    return db.execute('''INSERT INTO main.event(at, via, actor, entity_kind, entity_id, field, old_value, new_value, operation_key)
                         VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (now(), via, actor, kind, None if ident is None else str(ident), field, text(old), text(new), operation_key)).lastrowid


def _item(db, item_id):
    return db.execute('SELECT * FROM main.item WHERE id=?', (item_id,)).fetchone()


def _sum(a, b):
    return None if a is None and b is None else (a or 0) + (b or 0)


def _foreign_keys(db, tables):
    for table in tables:
        found = db.execute(f'PRAGMA main.foreign_key_check("{table}")').fetchall()
        if found:
            raise MergeRefused(f'{table} would hold a dangling reference ({len(found)} rows); nothing was changed')


# ---------- merge ----------

def _refuse_active_jobs(db, *item_ids):
    """A job in flight (queued, running, waiting for budget, or failed and due a retry) for an item writes to the id it was queued with; the
    guards would reject it after a merge or a kind move, so the change waits for the job."""
    marks = ','.join('?' * len(item_ids))
    job = db.execute(f"""SELECT id, kind, state, item_id FROM main.job WHERE item_id IN ({marks}) AND (state IN ('queued','running','waiting_for_budget')
                         OR (state='failed' AND retry_at IS NOT NULL)) ORDER BY id LIMIT 1""", item_ids).fetchone()
    if job is not None:
        raise MergeRefused(f'job {job["id"]} ({job["kind"]}, {job["state"]}) is still in flight for item {job["item_id"]} · '
                           'let it finish, or cancel it, then try again')


def _dependents(db, log):
    """`{table: [row keys]}`: the rows that refer to a row the log moved (a copy, a stock row...) and name an item themselves, as they
    are now. Taken at merge time and again at unmerge time: a row in the second and not the first was created after the merge (a photo
    added to a moved copy), and putting the parent back would strand it. Found from the schema's foreign keys, not from a list."""
    tables = [r[0] for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    links = {}                                                   # parent table -> [(child table, [(child column, parent column)], [item columns])]
    for child in tables:
        groups, item_columns = {}, []
        for fk in db.execute(f'PRAGMA main.foreign_key_list("{child}")'):
            if fk['table'] == 'item':
                item_columns.append(fk['from'])
            groups.setdefault((fk['id'], fk['table']), []).append((fk['from'], fk['to'] or log.pk(fk['table'])[len(groups.get((fk['id'], fk['table']), []))]))
        if item_columns:
            for (_, parent), pairs in groups.items():
                if parent != 'item':
                    links.setdefault(parent, []).append((child, pairs, item_columns))
    found = {}
    for change in log.changes:
        if change['b'] is None or change['a'] is None:
            continue
        for child, pairs, item_columns in links.get(change['t'], ()):
            where = ' AND '.join(f'"{c}"=?' for c, _ in pairs) + ' AND (' + ' OR '.join(f'"{c}" IS NOT NULL' for c in item_columns) + ')'
            for row in log.select(child, where, [change['a'][p] for _, p in pairs]):
                key = log._key(dict(t=child, a=row, b=None))
                found.setdefault(child, set()).add(json.dumps(list(key[1:]) if len(key) > 1 else list(key), default=str))
    return {t: sorted(v) for t, v in found.items()}


def _refuse_double_lines(db, loser, survivor):
    """A parent that holds a line for both items cannot be merged by a rule: the counts and checks on the lines are the user's."""
    checks = (
        ('copy_figure', 'SELECT a.copy_id FROM main.copy_figure a JOIN main.copy_figure b ON b.copy_id=a.copy_id WHERE a.item_id=? AND b.item_id=?',
         'copy {} holds a figure line for both items'),
        ('copy_part', '''SELECT a.copy_id FROM main.copy_part a JOIN main.copy_part b ON b.copy_id=a.copy_id AND b.figure_key=a.figure_key
                         AND b.color_id=a.color_id AND b.is_spare=a.is_spare WHERE a.item_id=? AND b.item_id=?''',
         'copy {} holds a part line for both items in one colour'),
        ('stock_part', 'SELECT a.stock_id FROM main.stock_part a JOIN main.stock_part b ON b.stock_id=a.stock_id AND b.color_id=a.color_id AND b.is_spare=a.is_spare WHERE a.item_id=? AND b.item_id=?',
         'loose figure {} holds a part line for both items in one colour'),
        ('fetched_inventory_part', '''SELECT a.fetched_inventory_id FROM main.fetched_inventory_part a JOIN main.fetched_inventory_part b
                                      ON b.fetched_inventory_id=a.fetched_inventory_id AND b.color_id=a.color_id AND b.is_spare=a.is_spare
                                      WHERE a.item_id=? AND b.item_id=?''', 'fetched part list {} holds a line for both items in one colour'),
        ('fetched_inventory_figure', '''SELECT a.fetched_inventory_id FROM main.fetched_inventory_figure a JOIN main.fetched_inventory_figure b
                                         ON b.fetched_inventory_id=a.fetched_inventory_id WHERE a.item_id=? AND b.item_id=?''',
         'fetched figure list {} holds a line for both items'))
    for table, sql, message in checks:
        found = db.execute(sql, (loser, survivor)).fetchone()
        if found:
            raise MergeRefused(message.format(found[0]) + ' · correct that line by hand, then merge again')


def _merge_links(db, log, loser, survivor):
    """item_link: the merge is the decision for the loser's to_check links; a link the survivor already holds is not doubled."""
    mine = log.select('item_link', 'item_id=? ORDER BY id', (loser,))
    for link in mine:
        if link['status'] == 'to_check':
            log.delete('item_link', link)
    held = {(r['provider'], r['provider_kind'], r['provider_key'], r['color_id']): r for r in log.select('item_link', 'item_id=?', (survivor,))}
    preferred = {(r['provider'], r['color_id']) for r in held.values() if r['preferred']}
    for link in mine:
        if link['status'] == 'to_check':
            continue
        key = (link['provider'], link['provider_kind'], link['provider_key'], link['color_id'])
        twin = held.get(key)
        if twin is not None:
            if link['status'] == 'manual' and twin['status'] != 'manual':      # a user's decision outranks the survivor's machine one
                held[key] = log.update('item_link', twin, status='manual', method=link['method'], origin='user',
                                       decided_at=link['decided_at'], decided_by=link['decided_by'])
            log.delete('item_link', log.get('item_link', link))
            continue
        sets = dict(item_id=survivor)
        if link['preferred'] and (link['provider'], link['color_id']) in preferred:
            sets['preferred'] = 0
        elif link['preferred']:
            preferred.add((link['provider'], link['color_id']))
        held[key] = log.update('item_link', link, **sets)


def _keep_born_number(db, log, loser_row, survivor):
    """The loser's own number still finds the item: an `inferred` link on the survivor when it holds none of that number."""
    if loser_row['born_provider'] is None or loser_row['born_key'] is None:
        return
    found = db.execute('''SELECT 1 FROM main.item_link WHERE item_id=? AND provider=? AND provider_kind=? AND provider_key=?''',
                       (survivor, loser_row['born_provider'], loser_row['born_namespace'], loser_row['born_key'])).fetchone()
    if found or db.execute('SELECT 1 FROM main.item WHERE id=? AND born_provider=? AND born_namespace=? AND born_key=?',
                           (survivor, loser_row['born_provider'], loser_row['born_namespace'], loser_row['born_key'])).fetchone():
        return
    log.insert('item_link', item_id=survivor, color_id=None, provider=loser_row['born_provider'], provider_kind=loser_row['born_namespace'],
               provider_key=loser_row['born_key'], status='inferred', method='merge', origin='user', preferred=0, evidence_digest=None,
               evidence_json=json.dumps({'merged_item': loser_row['id']}), catalogue_build_id=None, decided_at=now(), decided_by='merge')


def _merge_statuses(db, log, loser, survivor):
    mine = log.select('item_provider_status', 'item_id=?', (loser,))
    held = {(r['provider'], r['reason']) for r in log.select('item_provider_status', 'item_id=?', (survivor,))}
    for row in mine:
        if row['status'] == 'to_check' or (row['provider'], row['reason']) in held:
            log.delete('item_provider_status', row)
        else:
            log.update('item_provider_status', row, item_id=survivor)


def _merge_shadowed(log, loser, survivor):
    for table, columns in SHADOWED:
        taken = {tuple(r[c] for c in columns) for r in log.select(table, 'item_id=?', (survivor,))}
        for row in log.select(table, 'item_id=?', (loser,)):
            if tuple(row[c] for c in columns) in taken:
                log.delete(table, row)
            else:
                taken.add(tuple(row[c] for c in columns))
                log.update(table, row, item_id=survivor)


def _merge_fetched(log, loser, survivor):
    """The loser's fetched part lists come over after the survivor's: numbered on, and never `latest` beside a survivor's latest."""
    sources = {}
    for row in log.select('fetched_inventory', 'item_id=?', (survivor,)):
        top = sources.setdefault(row['source'], dict(seq=0, latest=False))
        top['seq'], top['latest'] = max(top['seq'], row['seq']), top['latest'] or bool(row['is_latest'])
    for row in log.select('fetched_inventory', 'item_id=? ORDER BY source, seq', (loser,)):
        theirs = sources.get(row['source'])
        sets = dict(item_id=survivor)
        if theirs is not None:
            theirs['seq'] += 1
            sets['seq'] = theirs['seq']
            if theirs['latest']:
                sets['is_latest'] = 0
        log.update('fetched_inventory', row, **sets)


def _merge_stock(db, log, loser, survivor, stamp):
    for row in log.select('stock', 'item_id=? ORDER BY created_at, id', (loser,)):
        twin = None
        if row['archived_at'] is None and row['kind'] != 'minifigure':
            twin = db.execute('''SELECT id FROM main.stock WHERE item_id=? AND archived_at IS NULL AND kind!='minifigure' AND color_key=coalesce(?, 0)
                                 AND condition_key=coalesce(?, '') AND lot_key=coalesce(?, '') AND storage_key=coalesce(?, '')''',
                              (survivor, row['color_id'], row['condition'], row['lot_id'], row['storage_id'])).fetchone()
        if twin is None:
            log.update('stock', row, item_id=survivor)
            continue
        target = log.select('stock', 'id=?', (twin['id'],))[0]
        log.update('stock', target, quantity=target['quantity'] + row['quantity'], missing=_sum(target['missing'], row['missing']),
                   damaged=_sum(target['damaged'], row['damaged']), checked=1 if target['checked'] and row['checked'] else target['checked'],
                   updated_at=stamp)
        log.update('stock', row, item_id=survivor, archived_at=stamp, updated_at=stamp)


def _merge_wishes(db, log, loser, survivor, stamp):
    for row in log.select('wish', 'item_id=? ORDER BY added_at, id', (loser,)):
        twin = None
        if row['archived_at'] is None:
            twin = db.execute('SELECT id FROM main.wish WHERE item_id=? AND archived_at IS NULL AND wishlist_id=? AND color_key=coalesce(?, 0)',
                              (survivor, row['wishlist_id'], row['color_id'])).fetchone()
        if twin is None:
            log.update('wish', row, item_id=survivor)
            continue
        target = log.select('wish', 'id=?', (twin['id'],))[0]
        sets = dict(quantity=target['quantity'] + row['quantity'], updated_at=stamp)
        if target['qty_filled_manual'] is not None or row['qty_filled_manual'] is not None:
            sets['qty_filled_manual'] = _sum(target['qty_filled_manual'], row['qty_filled_manual'])
        if target['max_price'] is None and row['max_price'] is not None:
            sets.update(max_price=row['max_price'], max_price_currency=row['max_price_currency'])
        log.update('wish', target, **sets)
        log.update('wish', row, item_id=survivor, archived_at=stamp, updated_at=stamp)


def merge_in(db, loser, survivor, *, via, actor=None, operation_key=None):
    """Merge the item `loser` into `survivor`, inside the caller's open write transaction. Returns `{merge_id, event_id, counts}`.

    Refuses (`MergeRefused`) a loser that is a live catalogue item (design 3.6: no catalogue row may name a merged id), a survivor that is
    merged itself or of another kind, an item merged into itself, and the double lines named in the module doc."""
    _need_transaction(db, 'merge_in')
    if loser == survivor:
        raise MergeRefused('an item cannot be merged into itself')
    old = _item(db, loser)
    if old is None:
        raise MergeRefused(f'item {loser} is not in this collection')
    if old['merged_into'] is not None:
        raise MergeRefused(f'item {loser} is merged already (into {old["merged_into"]})')
    if old['origin'] == 'catalogue' and old['catalogue_retired_at'] is None:
        raise MergeRefused(f'item {loser} is a live catalogue item: only a local item, or one the catalogue has retired, can be merged away')
    keep = _item(db, survivor)
    if keep is None:
        from . import identity
        try:
            identity.project(db, survivor)
        except NotInCatalogue:
            raise MergeRefused(f'item {survivor} is in neither the collection nor the catalogue') from None
        keep = _item(db, survivor)
    if keep['merged_into'] is not None:
        raise MergeRefused(f'item {survivor} is merged itself (into {keep["merged_into"]}); merge into that one')
    if keep['kind'] != old['kind']:
        raise MergeRefused(f'item {loser} is a {old["kind"]} and item {survivor} a {keep["kind"]}: an item merges only into one of its own kind '
                           '(change the kind first)')
    _refuse_double_lines(db, loser, survivor)
    _refuse_active_jobs(db, loser, survivor)
    db.execute('PRAGMA defer_foreign_keys=ON')                  # composite keys (item, fetched list) pass through a state of one moved, one not
    stamp = now()
    log = RowLog(db)
    _merge_links(db, log, loser, survivor)
    _keep_born_number(db, log, old, survivor)
    _merge_statuses(db, log, loser, survivor)
    _merge_shadowed(log, loser, survivor)
    _merge_fetched(log, loser, survivor)
    _merge_stock(db, log, loser, survivor, stamp)
    _merge_wishes(db, log, loser, survivor, stamp)
    for table, column in MOVES:
        for row in log.select(table, f'"{column}"=?', (loser,)):
            log.update(table, row, **{column: survivor})
    _foreign_keys(db, log.tables())
    operation_key = operation_key or uuid.uuid4().hex
    counts = {}
    for change in log.changes:
        op = 'inserted' if change['b'] is None else 'deleted' if change['a'] is None else 'moved'
        counts.setdefault(change['t'], {}).setdefault(op, 0)
        counts[change['t']][op] += 1
    event = _event(db, via, actor, operation_key, 'item', survivor, 'merge', loser, dict(merged=loser, counts=counts))
    db.execute('UPDATE main.item SET merged_into=? WHERE id=?', (survivor, loser))          # item_merge_guard: after every reference moved
    db.execute('INSERT INTO main.item_redirect(old_id, new_id) VALUES(?, ?)', (loser, survivor))
    merge_id = db.execute('''INSERT INTO main.item_merge(survivor_id, merged_id, at, via, actor, event_id, receipt_json) VALUES(?, ?, ?, ?, ?, ?, ?)''',
                          (survivor, loser, stamp, via, actor, event, json.dumps(dict(changes=log.changes, dependents=_dependents(db, log)), sort_keys=True))).lastrowid
    return dict(merge_id=merge_id, event_id=event, counts=counts)


def unmerge_in(db, merge_id, *, via, actor=None, operation_key=None):
    """Undo a merge from its receipt, inside the caller's open write transaction. Returns `{event_id, merge_id}`.

    Refused (`MergeRefused`) when the merge was undone already, when the loser or its redirect is not as the merge left them, or when any
    row the merge changed differs from what it left (a later edit, move or merge of the survivor's rows): undo the later change first."""
    _need_transaction(db, 'unmerge_in')
    merge = db.execute('SELECT * FROM main.item_merge WHERE id=?', (merge_id,)).fetchone()
    if merge is None:
        raise MergeRefused(f'merge {merge_id} does not exist')
    if merge['undone_at'] is not None:
        raise MergeRefused(f'merge {merge_id} was undone already')
    loser, survivor = merge['merged_id'], merge['survivor_id']
    row = _item(db, loser)
    redirect = db.execute('SELECT new_id FROM main.item_redirect WHERE old_id=?', (loser,)).fetchone()
    if row is None or row['merged_into'] != survivor or redirect is None or redirect['new_id'] != survivor:
        raise MergeRefused(f'item {loser} is not merged into {survivor} any more')
    _refuse_active_jobs(db, loser, survivor)
    receipt = json.loads(merge['receipt_json'])
    log = RowLog(db, receipt['changes'] if isinstance(receipt, dict) else receipt)
    changed = log.verify()
    if changed is not None:
        raise MergeRefused(f'{changed["t"]} changed since the merge · undo the later change first')
    known = receipt.get('dependents', {}) if isinstance(receipt, dict) else {}
    for table, keys in _dependents(db, log).items():
        if set(keys) - set(known.get(table, ())):
            raise MergeRefused(f'{table} changed since the merge (a row added after it refers to a row the merge moved) · undo the later change first')
    db.execute('PRAGMA defer_foreign_keys=ON')
    db.execute('DELETE FROM main.item_redirect WHERE old_id=?', (loser,))
    db.execute('UPDATE main.item SET merged_into=NULL WHERE id=?', (loser,))
    log.restore()
    _foreign_keys(db, log.tables())
    stamp = now()
    event = _event(db, via, actor, operation_key or uuid.uuid4().hex, 'item', survivor, 'unmerge', loser, dict(undoes=merge['event_id'], merge=merge_id))
    db.execute('UPDATE main.item_merge SET undone_at=?, undo_event_id=? WHERE id=?', (stamp, event, merge_id))
    db.execute('INSERT OR IGNORE INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (merge['event_id'], event))
    return dict(event_id=event, merge_id=merge_id)


def _own_transaction(db, what, function, *args, **kwargs):
    if db.in_transaction:
        raise Store4Error(f'{what} runs in its own transaction; commit or roll back the open one first')
    db.execute('BEGIN IMMEDIATE')
    try:
        result = function(db, *args, **kwargs)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def merge(db, loser, survivor, *, via='cli', actor=None):
    """`merge_in` in its own transaction."""
    return _own_transaction(db, 'merge', merge_in, loser, survivor, via=via, actor=actor)


def unmerge(db, merge_id, *, via='cli', actor=None):
    """`unmerge_in` in its own transaction."""
    return _own_transaction(db, 'unmerge', unmerge_in, merge_id, via=via, actor=actor)


# ---------- kind move (design 3.5) ----------

MOVABLE = ('set', 'instructions', 'box', 'gear', 'book', 'catalog')
KIND_FIELD = 'kind_move'


def _children(db, table, column, value):
    return db.execute(f'SELECT 1 FROM main."{table}" WHERE "{column}"=? LIMIT 1', (value,)).fetchone() is not None


def _plan_copies_to_stock(db, log, item_id, new_kind):
    """Rows that replace the item's copies by loose stock; refuses whatever a copy holds that a stock row cannot."""
    copies = log.select('copy', 'item_id=? ORDER BY created_at, id', (item_id,))
    seen = {}
    for copy in copies:
        cid = copy['id']
        for table, column in (('copy_part', 'copy_id'), ('copy_figure', 'copy_id'), ('part_check', 'copy_id'), ('allocation', 'copy_id'),
                              ('stock_transfer', 'copy_id'), ('identification_action', 'copy_id')):
            if _children(db, table, column, cid):
                raise MergeRefused(f'copy {cid} has {table.replace("_", " ")} rows · a copy with lines cannot become loose stock')
        if copy['pending_job_id'] is not None or copy['inventory_pending'] is not None:
            raise MergeRefused(f'copy {cid} waits for a part list · cancel that first')
        if copy['archived_at'] is None:
            key = (copy['condition'], copy['storage_id'])
            if key in seen:
                raise MergeRefused(f'copies {seen[key]} and {cid} share condition and storage, so they would be one stock row · '
                                   'move one to another storage or archive it first')
            seen[key] = cid
    return copies


def _kind_move_stock(db, log, item_id, new_kind):
    """Direction copy -> stock."""
    copies = _plan_copies_to_stock(db, log, item_id, new_kind)
    plan = []
    for copy in copies:
        stock_id = str(uuid.uuid4())
        flags = log.select('copy_flag', 'copy_id=?', (copy['id'],))
        photos = log.select('photo', 'copy_id=?', (copy['id'],))
        plan.append((copy, stock_id, flags, photos))
        for flag in flags:
            log.delete('copy_flag', flag)
        for photo in photos:
            log.update('photo', photo, copy_id=None, stock_id=stock_id)
        log.delete('copy', copy)
    return plan


def _insert_stock(log, item_id, new_kind, plan):
    for copy, stock_id, flags, photos in plan:
        log.insert('stock', id=stock_id, kind=new_kind, item_id=item_id, color_id=None, quantity=1, condition=copy['condition'],
                   storage_id=copy['storage_id'], lot_id=None, place_id=copy['place_id'], purchase_date=copy['purchase_date'],
                   purchase_price=copy['purchase_price'], purchase_currency=copy['purchase_currency'], note=copy['note'],
                   missing=None, damaged=None, checked=None, inventory_source=None, inventory_version=None, fetched_inventory_id=None,
                   inventory_digest=None, created_at=copy['created_at'], updated_at=copy['updated_at'], archived_at=copy['archived_at'])
        for flag in flags:
            log.insert('stock_flag', stock_id=stock_id, flag_id=flag['flag_id'])


def _kind_move_copies(db, log, item_id):
    """Direction stock -> copies; refuses what a copy cannot hold."""
    plan = []
    for row in log.select('stock', 'item_id=? ORDER BY created_at, id', (item_id,)):
        sid = row['id']
        if row['condition'] == 'damaged':
            raise MergeRefused(f'stock {sid} is damaged, a state a copy does not have · change its condition first')
        if row['lot_id'] is not None:
            raise MergeRefused(f'stock {sid} sits in a lot, which a copy cannot · take it out of the lot first')
        if row['missing'] or row['damaged']:
            raise MergeRefused(f'stock {sid} carries missing or damaged counts, which a copy of this kind does not · clear them first')
        for table in ('stock_transfer', 'allocation', 'identification_action'):
            if _children(db, table, 'stock_id', sid):
                raise MergeRefused(f'stock {sid} has {table.replace("_", " ")} rows · it cannot become copies')
        photos = log.select('photo', 'stock_id=?', (sid,))
        flags = log.select('stock_flag', 'stock_id=?', (sid,))
        if row['quantity'] < 1:
            raise MergeRefused(f'stock {sid} holds none, so there is no copy to make from it · archived or not, set its quantity first')
        if row['quantity'] != 1 and (row['purchase_price'] is not None or photos or flags):
            raise MergeRefused(f'stock {sid} holds {row["quantity"]} pieces with a price, photo or flag, which would have to be split · '
                               'split the row first')
        plan.append((row, photos, flags))
        for flag in flags:
            log.delete('stock_flag', flag)
    return plan


def move_kind_in(db, item_id, new_kind, *, via, actor=None, operation_key=None):
    """Change an item's kind with the rows that reference the old one, inside the caller's open write transaction.

    Allowed between `set`, `instructions`, `box`, `gear`, `book` and `catalog` (parts and figures take their kind from their number,
    3.1). Refused (`MergeRefused`) for a merged item, for a set with part lines or a fetched list leaving `set`, and for anything a copy
    or a stock row could not carry, with the row named. The kind source becomes `bricklink` when the item's `kind_differs` status names
    that kind, else `manual`; that status is cleared. Returns `{event_id, from, to, counts}`; the receipt is the event's `new_value`."""
    _need_transaction(db, 'move_kind_in')
    item = _item(db, item_id)
    if item is None:
        raise MergeRefused(f'item {item_id} is not in this collection')
    old = item['kind']
    if item['merged_into'] is not None:
        raise MergeRefused(f'item {item_id} is merged')
    if new_kind == old:
        raise MergeRefused(f'item {item_id} is a {old} already')
    _refuse_active_jobs(db, item_id)
    if old not in MOVABLE or new_kind not in MOVABLE:
        raise MergeRefused(f'only {", ".join(MOVABLE)} change into one another; a {old} cannot become a {new_kind}')
    if old == 'set':
        for table in ('fetched_inventory', 'instruction_file', 'set_preference'):
            if _children(db, table, 'item_id', item_id):
                raise MergeRefused(f'the set has {table.replace("_", " ")} rows, which only a set can hold')
    db.execute('PRAGMA defer_foreign_keys=ON')
    log = RowLog(db)
    stock_rows = wish_rows = plan = None
    stamp = now()
    # 1. the rows of the old kind go (the guards refuse a kind change, and a row of the new kind, while they exist)
    if old == 'set':
        plan = _kind_move_stock(db, log, item_id, new_kind)
    elif new_kind == 'set':
        plan = _kind_move_copies(db, log, item_id)
        for row, photos, flags in plan:
            for photo in photos:
                log.update('photo', photo, stock_id=None)             # re-attached below, to the first copy
            log.delete('stock', row)
    else:
        stock_rows = log.select('stock', 'item_id=?', (item_id,))
        for row in stock_rows:
            log.delete('stock', row)
    wish_rows = log.select('wish', 'item_id=?', (item_id,))
    for row in wish_rows:
        log.delete('wish', row)
    # 2. the kind
    status = db.execute("SELECT evidence_json FROM main.item_provider_status WHERE item_id=? AND reason='kind_differs'", (item_id,)).fetchone()
    source = 'manual'
    if status is not None:
        try:
            source = 'bricklink' if json.loads(status['evidence_json'] or '{}').get('to') == new_kind else 'manual'
        except ValueError:
            pass
    log.update('item', log.select('item', 'id=?', (item_id,))[0], kind=new_kind, kind_source=source)
    for row in log.select('item_provider_status', "item_id=? AND reason='kind_differs'", (item_id,)):
        log.delete('item_provider_status', row)
    # 3. the rows of the new kind
    if old == 'set':
        _insert_stock(log, item_id, new_kind, plan)
    elif new_kind == 'set':
        for row, photos, flags in plan:
            for number in range(row['quantity']):
                copy_id = str(uuid.uuid4())
                log.insert('copy', id=copy_id, item_id=item_id, inventory_source='none', inventory_version=None, fetched_inventory_id=None,
                           inventory_digest=None, materialised_at=None, inventory_pending=None, pending_job_id=None, condition=row['condition'],
                           completeness=None, completeness_source=None, storage_id=row['storage_id'], place_id=row['place_id'],
                           purchase_date=row['purchase_date'], purchase_price=row['purchase_price'], purchase_currency=row['purchase_currency'],
                           note=row['note'], current_value=None, current_value_currency=None, pinned=0, created_at=row['created_at'],
                           updated_at=row['updated_at'], archived_at=row['archived_at'])
                for flag in flags:
                    log.insert('copy_flag', copy_id=copy_id, flag_id=flag['flag_id'])
                if number == 0:
                    for photo in log.select('photo', 'id IN (%s)' % ','.join('?' * len(photos)) if photos else '0', [p['id'] for p in photos]):
                        log.update('photo', photo, copy_id=copy_id)
    else:
        for row in stock_rows:
            log.insert('stock', **{**{c: row[c] for c in log.cols('stock')}, 'kind': new_kind})
    for row in wish_rows:
        log.insert('wish', **{**{c: row[c] for c in log.cols('wish')}, 'kind': new_kind})
    _foreign_keys(db, log.tables())
    counts = {}
    for change in log.changes:
        op = 'inserted' if change['b'] is None else 'deleted' if change['a'] is None else 'changed'
        counts.setdefault(change['t'], {}).setdefault(op, 0)
        counts[change['t']][op] += 1
    receipt = dict(item=item_id, **{'from': old, 'to': new_kind}, counts=counts, changes=log.changes)
    event = _event(db, via, actor, operation_key or uuid.uuid4().hex, 'item', item_id, KIND_FIELD, old, receipt)
    return {'event_id': event, 'from': old, 'to': new_kind, 'counts': counts}


def undo_kind_move_in(db, event_id, *, via, actor=None, operation_key=None):
    """Put a kind move back from its receipt (the event's `new_value`); refused when any row it changed differs now."""
    _need_transaction(db, 'undo_kind_move_in')
    event = db.execute('SELECT * FROM main.event WHERE id=?', (event_id,)).fetchone()
    if event is None or event['entity_kind'] != 'item' or event['field'] != KIND_FIELD:
        raise MergeRefused(f'event {event_id} is not a kind move')
    if db.execute('SELECT 1 FROM main.event_undo WHERE event_id=?', (event_id,)).fetchone():
        raise MergeRefused(f'event {event_id} was undone already')
    receipt = json.loads(event['new_value'])
    _refuse_active_jobs(db, receipt['item'])
    log = RowLog(db, receipt['changes'])
    changed = log.verify()
    if changed is not None:
        raise MergeRefused(f'{changed["t"]} changed since the kind move · undo the later change first')
    db.execute('PRAGMA defer_foreign_keys=ON')
    log.restore()
    _foreign_keys(db, log.tables())
    undo = _event(db, via, actor, operation_key or uuid.uuid4().hex, 'item', receipt['item'], KIND_FIELD + '_undo', receipt['to'],
                  dict(undoes=event_id, restored=receipt['from']))
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event_id, undo))
    return {'event_id': undo, 'undoes': event_id}


def move_kind(db, item_id, new_kind, *, via='cli', actor=None):
    return _own_transaction(db, 'move_kind', move_kind_in, item_id, new_kind, via=via, actor=actor)
