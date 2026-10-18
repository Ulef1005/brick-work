"""Collection sync with Rebrickable and Brickset (#10): owned sets and wanted sets, pull and send.

Pull imports what the site has and Brick Work lacks, row by row, in one undoable transaction; it never
deletes here. Send writes counts there after a review; removals only when ticked; Brick Work's Undo
cannot reverse a remote change. One copy here is one physical unit; the sites hold quantities.
Condition, completeness, box, instructions and storage never leave Brick Work.

State per source lives in `settings` under `sync:<source>:…` (link, baseline, last pull, last send);
plans are JSON files under data/sync/ and expire after 24 hours.
"""
import json
import shutil
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from uuid import uuid4

from .. import errors, keys
from ..admin import audit
from ..sources.base import KeyRejected, SourceError, WaitingForBudget, now
from ..transaction import transaction
from . import adapters

SOURCES = ('rebrickable', 'brickset')
LABELS = {'rebrickable': 'Rebrickable', 'brickset': 'Brickset'}
USER = {'rebrickable': 'rebrickable_user', 'brickset': 'brickset_user'}
PLAN_TTL = timedelta(hours=24)


def _source(source):
    if source not in SOURCES:
        raise errors.NotFound('Unknown sync source')
    return source


def _setting(db, key, default=None):
    row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _put(db, key, value):
    db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, json.dumps(value, sort_keys=True)))


def _root(db):
    return Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve().parent / 'data' / 'sync'


# Credentials -------------------------------------------------------------------------------

def connect(db, source, username, password, *, http=None):
    """Exchange username + password at the site for its token/hash and store only that, encrypted.

    The password is used for one request and dropped; it never reaches the database, an event,
    a log line, an error or a reply.
    """
    _source(source)
    if not isinstance(username, str) or not username.strip() or len(username) > 200:
        raise errors.ValidationFailed('Enter your username')
    if not isinstance(password, str) or not password or len(password) > 500:
        raise errors.ValidationFailed('Enter your password')
    token = adapters.adapter(db, source, http).connect(username.strip(), password)
    field = keys.fields(USER[source])[0]
    keys.save(db, USER[source], {field: token})
    return credential_state(db, source)


def paste(db, source, value):
    """Store a token/hash the user generated on the site (write-only)."""
    _source(source)
    keys.save(db, USER[source], {keys.fields(USER[source])[0]: value})
    return credential_state(db, source)


def remove(db, source):
    _source(source)
    keys.archive(db, USER[source])
    return credential_state(db, source)


def test(db, source, *, http=None):
    _source(source)
    adapters.adapter(db, source, http).check_user()
    return dict(source=source, ok=True, checked_at=now().isoformat())


def credential_state(db, source):
    return dict(source=source, user=keys.state(db, USER[source], keys.USER_ENV[USER[source]]),
                key=keys.state(db, source))


# Link and status ---------------------------------------------------------------------------

def link(db, source, options):
    """Which remote lists are used. Rebrickable: owned (list ids, empty = all but the wishlist list),
    wishlist (one list id or null), send_to (the owned list that receives sends). Both sources:
    wish_list (the Brick Work wishlist that pulls and sends wishes, default 'default')."""
    _source(source)
    if not isinstance(options, dict):
        raise errors.ValidationFailed('Send the link options as an object')
    allowed = {'owned', 'wishlist', 'send_to', 'wish_list'} if source == 'rebrickable' else {'wish_list'}
    if set(options) - allowed:
        raise errors.ValidationFailed('Unknown link option: ' + ', '.join(sorted(set(options) - allowed)))
    value = dict(_setting(db, f'sync:{source}:link', {}), **options)
    if source == 'rebrickable':
        owned = value.get('owned') or []
        if not isinstance(owned, list) or any(type(i) is not int or i <= 0 for i in owned):
            raise errors.ValidationFailed('Choose owned set lists by id')
        for key in ('wishlist', 'send_to'):
            if value.get(key) is not None and (type(value[key]) is not int or value[key] <= 0):
                raise errors.ValidationFailed('Choose a set list by id')
        if value.get('wishlist') and value['wishlist'] in owned:
            raise errors.ValidationFailed('The wishlist list cannot also be an owned list')
        if value.get('send_to') and owned and value['send_to'] not in owned:
            raise errors.ValidationFailed('Send to one of the owned lists')
    from .. import wishlists
    wishlists.require(db, value.get('wish_list') or 'default')
    with transaction(db):
        before = _setting(db, f'sync:{source}:link')
        _put(db, f'sync:{source}:link', value)
        audit(db, 'sync:' + source, 'link', before, value)
    return status(db, source)


def lists(db, source, *, http=None):
    return adapters.adapter(db, _source(source), http).lists()


def status(db, source):
    _source(source)
    last_send = _setting(db, f'sync:{source}:last_send')
    waiting = [r for r in (last_send or {}).get('rows', []) if r['result'] in ('failed', 'paused', 'key_rejected')]
    return dict(source=source, label=LABELS[source], credentials=credential_state(db, source),
                link=_setting(db, f'sync:{source}:link', {}), last_pull=_setting(db, f'sync:{source}:last_pull'),
                last_send=None if last_send is None else {k: v for k, v in last_send.items() if k != 'rows'},
                waiting=len(waiting))


# Translation ---------------------------------------------------------------------------------

def _catalogue_sets(db, numbers):
    """Which of these set numbers exist as BrickLink sets (catalogue file, else this store's items)."""
    numbers = sorted(set(numbers))
    if not numbers:
        return set()
    from ..add import catalogue_path
    path = catalogue_path(db)
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as cat:
            return {r[0] for r in cat.execute(
                "SELECT item_no FROM items WHERE item_type='S' AND item_no IN (SELECT value FROM json_each(?))",
                (json.dumps(numbers),))}
    return {r[0] for r in db.execute(
        "SELECT item_no FROM items WHERE item_type='S' AND item_no IN (SELECT value FROM json_each(?))", (json.dumps(numbers),))}


def _match_kind(source):
    return 'set' if source == 'rebrickable' else 'set_number'


def translate(db, source, remote_numbers):
    """Remote set number -> BrickLink set number. A stored decision wins; otherwise the same number when
    the BrickLink catalogue has it (the sites share LEGO's set numbering). Anything else is unmatched."""
    decided = {}
    for r in db.execute("SELECT source_id,item_no,status FROM id_match WHERE source=? AND kind=? AND item_type='S' "
                        "AND source_id IN (SELECT value FROM json_each(?))",
                        (source, _match_kind(source), json.dumps(sorted(set(remote_numbers))))):
        if r['status'] in ('matched', 'manual', 'inferred') and r['item_no']:
            decided.setdefault(r['source_id'], set()).add(r['item_no'])
    known = _catalogue_sets(db, [n for n in remote_numbers if n not in decided])
    out = {}
    for number in remote_numbers:
        if number in decided:
            out[number] = next(iter(decided[number])) if len(decided[number]) == 1 else None
        else:
            out[number] = number if number in known else None
    return out


def reverse(db, source, item_numbers):
    """BrickLink set number -> remote set number, by the same rules in the other direction."""
    decided = {}
    for r in db.execute("SELECT source_id,item_no,status FROM id_match WHERE source=? AND kind=? AND item_type='S' "
                        "AND item_no IN (SELECT value FROM json_each(?))",
                        (source, _match_kind(source), json.dumps(sorted(set(item_numbers))))):
        if r['status'] in ('matched', 'manual', 'inferred'):
            decided.setdefault(r['item_no'], set()).add(r['source_id'])
    return {n: (next(iter(decided[n])) if len(decided.get(n, ())) == 1 else None) if n in decided else n
            for n in item_numbers}


def _here(db, wish_list):
    owned = {r[0]: r[1] for r in db.execute(
        "SELECT set_no,count(*) FROM copies WHERE item_type='S' AND archived_at IS NULL GROUP BY set_no")}
    wanted = {r[0]: r[1] for r in db.execute(
        "SELECT item_no,sum(quantity) FROM wishlist WHERE item_type='S' AND archived_at IS NULL AND list_id=? GROUP BY item_no",
        (wish_list,))}
    return dict(owned=owned, wanted=wanted)


def _names(db, numbers):
    from ..add import catalogue_path
    numbers = sorted(set(numbers))
    names = {r[0]: r[1] for r in db.execute(
        "SELECT item_no,name FROM items WHERE item_type='S' AND item_no IN (SELECT value FROM json_each(?))", (json.dumps(numbers),))}
    path = catalogue_path(db)
    missing = [n for n in numbers if not names.get(n)]
    if missing and path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as cat:
            names.update({r[0]: r[1] for r in cat.execute(
                "SELECT item_no,name FROM items WHERE item_type='S' AND item_no IN (SELECT value FROM json_each(?))",
                (json.dumps(missing),))})
    return names


# Plans -------------------------------------------------------------------------------------

def _save_plan(db, plan):
    root = _root(db)
    root.mkdir(parents=True, exist_ok=True)
    cutoff = now() - PLAN_TTL
    for old in root.glob('*.json'):
        try:
            if datetime.fromisoformat(json.loads(old.read_text())['created_at']) < cutoff:
                old.unlink()
        except (OSError, ValueError, KeyError):
            old.unlink(missing_ok=True)
    (root / (plan['id'] + '.json')).write_text(json.dumps(plan))
    return plan


def load_plan(db, plan_id, direction=None):
    if not isinstance(plan_id, str) or len(plan_id) != 32 or not plan_id.isalnum():
        raise errors.ValidationFailed('Unknown sync plan')
    try:
        plan = json.loads((_root(db) / (plan_id + '.json')).read_text())
    except (OSError, ValueError):
        raise errors.ValidationFailed('This sync plan has expired · make a new one') from None
    if datetime.fromisoformat(plan['created_at']) < now() - PLAN_TTL:
        raise errors.ValidationFailed('This sync plan has expired · make a new one')
    if direction and plan['direction'] != direction:
        raise errors.ValidationFailed('This is a ' + plan['direction'] + ' plan')
    return plan


def _store_plan(db, plan):
    (_root(db) / (plan['id'] + '.json')).write_text(json.dumps(plan))


def _fetch(db, source, http):
    client = adapters.adapter(db, source, http)
    link_value = _setting(db, f'sync:{source}:link', {})
    remote = client.fetch(link_value)
    return client, link_value, remote


def _compare(db, source, link_value, remote):
    """Rows per set and kind with remote, here and baseline counts; unmatched remote numbers kept apart."""
    wish_list = link_value.get('wish_list') or 'default'
    here = _here(db, wish_list)
    baseline = _setting(db, f'sync:{source}:baseline', {})
    mapping = translate(db, source, list(set(remote['owned']) | set(remote['wanted'])))
    names = _names(db, [n for n in mapping.values() if n] + list(here['owned']) + list(here['wanted']))
    rows, unmatched = [], []
    for kind in ('owned', 'wanted'):
        there = {}
        for number, quantity in remote[kind].items():
            target = mapping.get(number)
            if target is None:
                unmatched.append(dict(key=f'{kind}:?{number}', kind=kind, remote_no=number, remote=quantity,
                                      state='unmatched', reason='No unique BrickLink set for this number'))
                continue
            entry = there.setdefault(target, [0, number])
            entry[0] += quantity
        base_remote = baseline.get('remote', {}).get(kind, {})
        base_here = baseline.get('here', {}).get(kind, {})
        for item in sorted(set(there) | set(here[kind])):
            r, remote_no = there.get(item, [0, None])
            h = here[kind].get(item, 0)
            rows.append(dict(key=f'{kind}:{item}', kind=kind, item_no=item, name=names.get(item), remote_no=remote_no,
                             remote=r, here=h, baseline_remote=base_remote.get(item), baseline_here=base_here.get(item)))
    return rows, unmatched, mapping


def _changed_both(row):
    if row['baseline_remote'] is None and row['baseline_here'] is None:
        return False
    return (row['remote'] != (row['baseline_remote'] or 0) and row['here'] != (row['baseline_here'] or 0)
            and row['remote'] != row['here'])


def plan_pull(db, source, *, http=None):
    """What the site has that Brick Work lacks. Writes nothing to the collection."""
    _source(source)
    _, link_value, remote = _fetch(db, source, http)
    rows, unmatched, _ = _compare(db, source, link_value, remote)
    out = []
    for row in rows:
        r, h = row['remote'], row['here']
        if r == h:
            continue
        if _changed_both(row):
            state, action, count = 'conflict', None, max(0, r - h)
        elif r > h:
            state, action, count = 'add', 'add', r - h
        elif r == 0:
            state, action, count = 'only_here', None, 0
        else:
            state, action, count = 'differs', None, 0
        out.append(dict(row, state=state, action=action, count=count, tickable=count > 0))
    plan = dict(id=uuid4().hex, created_at=now().isoformat(), direction='pull', source=source, link=link_value,
                remote=dict(owned=remote['owned'], wanted=remote['wanted']), rows=out, unmatched=unmatched,
                summary=_summary(out, unmatched, rows))
    return _save_plan(db, plan)


def _summary(rows, unmatched, compared):
    counts = {}
    for row in rows:
        counts.setdefault(row['kind'], {}).setdefault(row['state'], 0)
        counts[row['kind']][row['state']] += 1
    for kind in ('owned', 'wanted'):
        counts.setdefault(kind, {})['same'] = sum(1 for r in compared if r['kind'] == kind and r['remote'] == r['here'])
        counts[kind]['unmatched'] = sum(1 for r in unmatched if r['kind'] == kind)
    return counts


def _ticked(plan, ticked):
    """Effective rows: defaults when `ticked` is None; else exactly the ticked tickable rows."""
    keys_ = {r['key'] for r in plan['rows']}
    if ticked is None:
        return [r for r in plan['rows'] if r['action']]
    if not isinstance(ticked, list) or any(not isinstance(k, str) for k in ticked):
        raise errors.ValidationFailed('Send ticked rows as a list of keys')
    unknown = set(ticked) - keys_
    if unknown:
        raise errors.ValidationFailed('Unknown sync rows: ' + ', '.join(sorted(unknown)[:5]))
    rows = [r for r in plan['rows'] if r['key'] in set(ticked)]
    if any(not r['tickable'] for r in rows):
        raise errors.ValidationFailed('Only rows with something to do can be ticked')
    return rows


def _flag(db, source, receipt):
    name = 'imported from ' + LABELS[source]
    row = db.execute("SELECT id FROM flags WHERE kind='tag' AND lower(name)=lower(?)", (name,)).fetchone()
    if row:
        return row[0]
    identifier = uuid4().hex
    db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,'tag',0)", (identifier, name))
    receipt['flag_created'] = identifier
    return identifier


def apply_pull(db, plan_id, ticked=None):
    """Create one copy per missing unit (flagged, condition and completeness unset) and the missing
    wishes, in one transaction with one receipt. Never deletes or lowers anything here."""
    from .. import plans
    plan = load_plan(db, plan_id, 'pull')
    # The database marker decides; the plan file can say applied for a write that rolled back.
    done = plans.applied(db, 'sync', plan_id, file_says_applied=bool(plan.get('applied')))
    if done:
        return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
    rows = _ticked(plan, ticked)
    source, stamp = plan['source'], now().isoformat()
    wish_list = plan['link'].get('wish_list') or 'default'
    receipt = dict(plan=plan_id, source=source, items=[], wishes_added=[], wishes_changed=[], flag_created=None,
                   baseline_before=None, guards={})
    from .. import wishlists
    with transaction(db):
        # Checked again under the write lock: a second submit waits here and finds the first one's marker.
        done = plans.applied(db, 'sync', plan_id, file_says_applied=bool(plan.get('applied')))
        if done:
            return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
        wishlists.require(db, wish_list)
        flag = _flag(db, source, receipt) if any(r['kind'] == 'owned' for r in rows) else None
        names = _names(db, [r['item_no'] for r in rows])
        known = {r[0] for r in db.execute("SELECT item_no FROM items WHERE item_type='S' AND item_no IN (SELECT value FROM json_each(?))",
                                         (json.dumps([r['item_no'] for r in rows]),))}
        wishes = {r['item_no']: dict(r) for r in db.execute(
            "SELECT * FROM wishlist WHERE item_type='S' AND archived_at IS NULL AND list_id=? "
            "AND item_no IN (SELECT value FROM json_each(?))", (wish_list, json.dumps([r['item_no'] for r in rows])))}
        for row in rows:
            number = row['item_no']
            if number not in known:
                db.execute('INSERT INTO items(item_type,item_no,name,updated_at) VALUES(?,?,?,?)', ('S', number, names.get(number), stamp))
                known.add(number)
            if row['kind'] == 'owned':
                created = [uuid4().hex for _ in range(row['count'])]
                db.executemany("INSERT INTO copies(id,item_type,set_no,condition,completeness,completeness_source,updated_at) "
                               "VALUES(?,'S',?,NULL,NULL,'derived',?)", [(c, number, stamp) for c in created])
                db.executemany("INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES('copy',?,?)", [(c, flag) for c in created])
                receipt['items'].append(dict(item_type='S', item_no=number, copies=created))
            elif number in wishes:
                old = wishes[number]
                db.execute('UPDATE wishlist SET quantity=?,updated_at=? WHERE id=?', (old['quantity'] + row['count'], stamp, old['id']))
                receipt['wishes_changed'].append(old)
            else:
                identifier = db.execute("INSERT INTO wishlist(item_type,item_no,quantity,condition,added_at,updated_at,list_id) "
                                        "VALUES('S',?,?,'any',?,?,?)", (number, row['count'], stamp, stamp, wish_list)).lastrowid
                receipt['wishes_added'].append(identifier)
        copies = [c for item in receipt['items'] for c in item['copies']]
        wish_ids = receipt['wishes_added'] + [w['id'] for w in receipt['wishes_changed']]
        for table, ids in (('copies', copies), ('wishlist', wish_ids)):
            if ids:
                receipt['guards'][table] = [dict(r) for r in db.execute(
                    f'SELECT * FROM {table} WHERE id IN (SELECT value FROM json_each(?)) ORDER BY id', (json.dumps(ids),))]
        from ..pipeline import queue_new_items
        receipt['jobs'] = queue_new_items(db, {('S', item['item_no']) for item in receipt['items']})
        receipt['baseline_before'] = _setting(db, f'sync:{source}:baseline')
        _put(db, f'sync:{source}:baseline', _baseline(db, plan, wish_list))
        counts = dict(copies=len(copies), wishes_added=len(receipt['wishes_added']), wishes_changed=len(receipt['wishes_changed']))
        receipt['counts'] = counts
        _put(db, f'sync:{source}:last_pull', dict(at=stamp, plan=plan_id, counts=counts))
        from ..audit_bundle import CAPTURE
        bundled = CAPTURE.get() is not None
        audit(db, 'bw_sync', 'receipt', None, receipt)
        event = None if bundled else db.execute('SELECT last_insert_rowid()').fetchone()[0]
        plans.mark(db, 'sync', plan_id, dict(event_id=event, counts=counts, at=stamp))
    plan['applied'] = dict(event_id=event, counts=counts, at=stamp)
    _store_plan(db, plan)
    return dict(event_id=event, already_applied=False, counts=counts)


def _baseline(db, plan, wish_list):
    """Remote counts as last seen and here counts now, per BrickLink set number."""
    mapping = translate(db, plan['source'], list(set(plan['remote']['owned']) | set(plan['remote']['wanted'])))
    remote = {}
    for kind in ('owned', 'wanted'):
        remote[kind] = {}
        for number, quantity in plan['remote'][kind].items():
            if mapping.get(number):
                remote[kind][mapping[number]] = remote[kind].get(mapping[number], 0) + quantity
    return dict(at=now().isoformat(), remote=remote, here=_here(db, wish_list))


def receipt_of(db, event_id):
    row = db.execute("SELECT new_value FROM events WHERE id=? AND entity='bw_sync' AND field='receipt'", (event_id,)).fetchone()
    if not row:
        raise errors.NotFound('No sync receipt')
    return json.loads(row[0])


def undo(db, event_id, receipt=None):
    """Reverse one pull exactly; refused when anything it wrote was changed since."""
    receipt = receipt if receipt is not None else receipt_of(db, event_id)
    with transaction(db):
        if db.execute("SELECT 1 FROM events WHERE entity='bw_sync' AND field='undo' AND old_value=?", (json.dumps(event_id),)).fetchone():
            return dict(undone_event_id=event_id, already_undone=True)
        for table, saved in receipt['guards'].items():
            current = [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE id IN (SELECT value FROM json_each(?)) ORDER BY id',
                                                    (json.dumps([r['id'] for r in saved]),))]
            if current != saved:
                raise ValueError('Something from this sync has changed since · undo the later change first')
        stamp = now().isoformat()
        copies = [c for item in receipt['items'] for c in item['copies']]
        db.execute('UPDATE copies SET archived_at=?,updated_at=? WHERE id IN (SELECT value FROM json_each(?))', (stamp, stamp, json.dumps(copies)))
        db.execute("DELETE FROM item_flags WHERE entity_type='copy' AND entity_id IN (SELECT value FROM json_each(?))", (json.dumps(copies),))
        db.execute('UPDATE wishlist SET archived_at=?,updated_at=? WHERE id IN (SELECT value FROM json_each(?))',
                   (stamp, stamp, json.dumps(receipt['wishes_added'])))
        for old in receipt['wishes_changed']:
            db.execute('UPDATE wishlist SET quantity=?,updated_at=? WHERE id=?', (old['quantity'], old['updated_at'], old['id']))
        if receipt['flag_created'] and not db.execute('SELECT 1 FROM item_flags WHERE flag_id=?', (receipt['flag_created'],)).fetchone():
            db.execute('DELETE FROM flags WHERE id=?', (receipt['flag_created'],))
        if receipt['baseline_before'] is None:
            db.execute('DELETE FROM settings WHERE key=?', (f"sync:{receipt['source']}:baseline",))
        else:
            _put(db, f"sync:{receipt['source']}:baseline", receipt['baseline_before'])
        audit(db, 'bw_sync', 'undo', event_id, None)
    return dict(undone_event_id=event_id, already_undone=False)


def plan_send(db, source, *, http=None):
    """The remote calls a send would make: one row per set whose count differs. Removals unticked."""
    _source(source)
    client, link_value, remote = _fetch(db, source, http)
    rows, unmatched, mapping = _compare(db, source, link_value, remote)
    targets = reverse(db, source, [r['item_no'] for r in rows if r['remote_no'] is None])
    out = []
    for row in rows:
        r, h = row['remote'], row['here']
        if r == h:
            continue
        remote_no = row['remote_no'] or targets.get(row['item_no'])
        if row['kind'] == 'wanted':
            send = 1 if h else 0
            if source == 'rebrickable':
                send = h
            if send == r or (source == 'brickset' and bool(h) == bool(r)):
                continue
        else:
            send = h
        state = 'conflict' if _changed_both(row) else 'remove' if h == 0 else 'add' if r == 0 else 'change'
        unmatched_here = remote_no is None
        out.append(dict(row, remote_no=remote_no, send=send, state='unmatched' if unmatched_here else state,
                        action='send' if state in ('add', 'change') and not unmatched_here else None,
                        tickable=not unmatched_here,
                        reason='No set number on ' + LABELS[source] if unmatched_here else None))
    extra = {}
    if source == 'brickset':
        known = dict(remote.get('ids', {}))
        missing = [r['remote_no'] for r in out if r['remote_no'] and r['remote_no'] not in known]
        if missing:
            known.update(client.set_ids(missing))
        for row in out:
            if row['remote_no'] and row['remote_no'] not in known and row['state'] != 'unmatched':
                row.update(state='unmatched', action=None, tickable=False, reason='Brickset does not know this set number')
        extra['ids'] = {k: v for k, v in known.items()}
    else:
        extra['per_list'] = remote['per_list']
        owned_lists = remote.get('owned_lists') or []
        extra['send_to'] = link_value.get('send_to') or (owned_lists[0] if len(owned_lists) == 1 else None)
        if extra['send_to'] is None:
            for row in out:
                if row['kind'] == 'owned' and row['action']:
                    row.update(action=None, tickable=False, reason='Link one owned Rebrickable list to send to')
    plan = dict(id=uuid4().hex, created_at=now().isoformat(), direction='send', source=source, link=link_value,
                remote=dict(owned=remote['owned'], wanted=remote['wanted']), state=extra, rows=out, unmatched=unmatched,
                summary=_summary(out, unmatched, rows),
                note='Sending changes ' + LABELS[source] + '. Brick Work\'s Undo cannot reverse a remote change.')
    return _save_plan(db, plan)


def apply_send(db, plan_id, ticked=None, *, http=None):
    """Perform the ticked remote calls in order. Each row records sent, unchanged, failed, paused
    (budget) or key_rejected. A budget stop pauses the rest; a rejected key or token stops the rest.
    Re-applying the same plan retries only rows that were not sent. Nothing is retried silently."""
    plan = load_plan(db, plan_id, 'send')
    source = plan['source']
    rows = _ticked(plan, ticked)
    results = plan.setdefault('results', {})
    client = adapters.adapter(db, source, http)
    stop = None
    for row in rows:
        if results.get(row['key'], {}).get('result') in ('sent', 'unchanged'):
            continue
        if stop:
            results[row['key']] = dict(result=stop, detail=None)
            continue
        try:
            results[row['key']] = dict(result=client.send(row, plan['link'], plan['state']), detail=None, at=now().isoformat())
        except WaitingForBudget as paused:
            stop = 'paused'
            results[row['key']] = dict(result='paused', detail='Waiting for the daily budget', retry_at=paused.retry_at)
        except KeyRejected:
            stop = 'key_rejected'
            results[row['key']] = dict(result='key_rejected', detail=LABELS[source] + ' refused the key or user token')
        except (SourceError, errors.BrickWorkError, ValueError) as failure:
            results[row['key']] = dict(result='failed', detail=str(failure))
        _store_plan(db, plan)
    sent = [r for r in rows if results.get(r['key'], {}).get('result') in ('sent', 'unchanged')]
    stamp = now().isoformat()
    summary = {}
    for value in results.values():
        summary[value['result']] = summary.get(value['result'], 0) + 1
    report = dict(at=stamp, plan=plan_id, counts=summary,
                  rows=[dict(key=k, result=v['result']) for k, v in results.items()])
    with transaction(db):
        baseline = _setting(db, f'sync:{source}:baseline', {'remote': {'owned': {}, 'wanted': {}}, 'here': {'owned': {}, 'wanted': {}}})
        for row in sent:
            baseline.setdefault('remote', {}).setdefault(row['kind'], {})[row['item_no']] = row['send']
            baseline.setdefault('here', {}).setdefault(row['kind'], {})[row['item_no']] = row['here']
        _put(db, f'sync:{source}:baseline', baseline)
        _put(db, f'sync:{source}:last_send', report)
        # A record, not an undoable receipt: remote changes cannot be taken back from here.
        audit(db, 'sync:' + source, 'send', None, dict(plan=plan_id, counts=summary))
    return dict(plan=plan_id, counts=summary, rows=[dict(key=k, **v) for k, v in results.items()],
                note='Remote changes are not undone by Brick Work\'s Undo.')
