"""Collection sync with Rebrickable and Brickset (#10) on the 4.0 store (M.8j, issue #110; design 3.5, 5.2): owned sets and wanted sets,
pull and send.

Pull imports what the site has and Brick Work lacks, row by row, in one undoable transaction; it never deletes here. Send writes counts
there after a review; removals only when ticked; Brick Work's Undo cannot reverse a remote change. One copy here is one physical unit;
the sites hold quantities. Condition, completeness, box, instructions and storage never leave Brick Work.

Every row speaks an item id. A remote set number is a Rebrickable number (Brickset's `number-variant` is the same numbering): it is
translated to an item by its born key, else by one confirmed BrickLink link, and an item is placed by its current kind (design 3.5): a
set becomes a copy (design 4.3's preselection, as Add), every other kind becomes stock of that kind. Sending names an item by its born
key or through `items.bricklink_key`; an item with no number at all is left out and listed as not on the site.

State per source lives in `sync_state` (link, baseline, last pull, last send; the migration carries only the link, so the first sync
after the cutover shows a full comparison and `_changed_both` has nothing to compare against). Plans are JSON files under data/sync/ and
expire after 24 hours; whether a plan was applied is the `plan` table's (`core/plans.py`)."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ...store4 import pending
from ...store4.connect import has_catalogue, now as store_now
from .. import errors, items, keys, stock
from .. import undo as undoing
from ..admin import audit
from ..sources.base import KeyRejected, SourceError, WaitingForBudget, now
from ..transaction import transaction
from . import adapters

SOURCES = ('rebrickable', 'brickset')
LABELS = {'rebrickable': 'Rebrickable', 'brickset': 'Brickset'}
USER = {'rebrickable': 'rebrickable_user', 'brickset': 'brickset_user'}
PLAN_TTL = timedelta(hours=24)
COLUMNS = {'link': 'link_json', 'baseline': 'baseline_json', 'last_pull': 'last_pull_json', 'last_send': 'last_send_json'}
SETLIKE = tuple(kind for kind in items.KINDS if kind not in ('part', 'minifigure'))   # what a site's set list can hold
_KINDS_SQL = ','.join(repr(k) for k in SETLIKE)


def _source(source):
    if source not in SOURCES:
        raise errors.NotFound('Unknown sync source')
    return source


def _setting(db, source, name, default=None):
    row = db.execute(f'SELECT {COLUMNS[name]} FROM main.sync_state WHERE source=?', (source,)).fetchone()
    return json.loads(row[0]) if row and row[0] is not None else default


def _put(db, source, name, value):
    column = COLUMNS[name]
    text = None if value is None else json.dumps(value, sort_keys=True)
    db.execute(f'INSERT INTO main.sync_state(source, {column}, updated_at) VALUES(?, ?, ?) '
               f'ON CONFLICT(source) DO UPDATE SET {column}=excluded.{column}, updated_at=excluded.updated_at', (source, text, store_now()))


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
    value = dict(_setting(db, source, 'link', {}), **options)
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
        before = _setting(db, source, 'link')
        _put(db, source, 'link', value)
        audit(db, 'sync:' + source, 'link', before, value)
    return status(db, source)


def lists(db, source, *, http=None):
    return adapters.adapter(db, _source(source), http).lists()


def status(db, source):
    _source(source)
    last_send = _setting(db, source, 'last_send')
    waiting = [r for r in (last_send or {}).get('rows', []) if r['result'] in ('failed', 'paused', 'key_rejected')]
    return dict(source=source, label=LABELS[source], credentials=credential_state(db, source),
                link=_setting(db, source, 'link', {}), last_pull=_setting(db, source, 'last_pull'),
                last_send=None if last_send is None else {k: v for k, v in last_send.items() if k != 'rows'},
                waiting=len(waiting))


# Translation ---------------------------------------------------------------------------------

def _stores(db):
    return ('main', 'catalogue') if has_catalogue(db) else ('main',)


def translate(db, remote_numbers):
    """Remote set number -> the item id it names, or None. A number is a Rebrickable number (Brickset's `number-variant` is the same
    numbering): the item whose born key it is (a local BrickLink-born item counts by its BrickLink number), else the one item a confirmed
    BrickLink link names; a number that names several items, or none, or only a part or figure, is None (the plan lists it as not matched)."""
    numbers = sorted(set(remote_numbers))
    if not numbers:
        return {}
    born = {n: {} for n in numbers}                              # number -> {item id: born provider}
    packed = json.dumps(numbers)
    for store in _stores(db):
        live = '' if store == 'main' else ' AND retired_at IS NULL AND id NOT IN (SELECT id FROM main.item)'
        for row in db.execute(f'SELECT id, born_key, born_provider FROM {store}.item WHERE born_key IN (SELECT value FROM json_each(?)) AND kind IN ({_KINDS_SQL}){live}', (packed,)):
            born[row['born_key']][items._merged_target(db, row['id'])] = row['born_provider']
    out = {}
    for number, found in born.items():
        rebrickable = [i for i, provider in found.items() if provider == 'rebrickable']
        out[number] = (rebrickable or list(found))[0] if len(rebrickable or found) == 1 else None      # the number is a Rebrickable one: its item wins a local twin
    rest = [n for n in numbers if not born[n]]
    linked = {n: set() for n in rest}
    for store in _stores(db):
        live = '' if store == 'main' else ' AND i.retired_at IS NULL AND l.item_id NOT IN (SELECT id FROM main.item)'
        for row in db.execute(f"""SELECT l.item_id, l.provider_key FROM {store}.item_link l JOIN {store}.item i ON i.id=l.item_id
                                  WHERE l.provider='bricklink' AND l.provider_key IN (SELECT value FROM json_each(?)) AND l.status IN ({items._IN})
                                  AND i.kind IN ({_KINDS_SQL}){live}""", (json.dumps(rest), *items.CONFIRMED)):
            linked[row['provider_key']].add(items._merged_target(db, row['item_id']))
    out.update({n: next(iter(ids)) if len(ids) == 1 else None for n, ids in linked.items()})
    return out


def reverse(db, item_ids):
    """Item id -> the set number a site knows it by: the Rebrickable number of a Rebrickable-born item, else the BrickLink number
    (`items.bricklink_key`; a local BrickLink-born item is its own). An item with no number at all is None: it is left out and listed."""
    out = {}
    for item_id in sorted(set(item_ids)):
        label = items.label(db, item_id)
        if label.source == 'rebrickable':
            out[item_id] = label.number
            continue
        try:
            out[item_id] = items.bricklink_key(db, item_id)[1]
        except items.Unidentified:
            out[item_id] = None
    return out


def _here(db, wish_list):
    """What this collection holds per item id: copies of sets plus loose stock of the other kinds; wishes of the linked list."""
    owned = {r[0]: r[1] for r in db.execute('SELECT item_id, count(*) FROM main.copy WHERE archived_at IS NULL GROUP BY item_id')}
    for item_id, quantity in db.execute(f'SELECT item_id, sum(quantity) FROM main.stock WHERE archived_at IS NULL AND kind IN ({_KINDS_SQL}) GROUP BY item_id'):
        owned[item_id] = owned.get(item_id, 0) + quantity
    wanted = {r[0]: r[1] for r in db.execute(
        f'SELECT item_id, sum(quantity) FROM main.wish WHERE archived_at IS NULL AND wishlist_id=? AND kind IN ({_KINDS_SQL}) GROUP BY item_id', (wish_list,))}
    return dict(owned={k: v for k, v in owned.items() if v}, wanted=wanted)


def _names(db, item_ids):
    """`{item id: (born number or None, name)}` from the collection's row, else the catalogue's."""
    out, packed = {}, json.dumps(sorted(set(item_ids)))
    for store in _stores(db):
        for r in db.execute(f'SELECT id, born_key, name FROM {store}.item WHERE id IN (SELECT value FROM json_each(?))', (packed,)):
            out.setdefault(r['id'], (r['born_key'], r['name']))
    return out


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
    link_value = _setting(db, source, 'link', {})
    remote = client.fetch(link_value)
    return client, link_value, remote


def _compare(db, source, link_value, remote):
    """Rows per item and kind with remote, here and baseline counts; unmatched remote numbers kept apart."""
    wish_list = link_value.get('wish_list') or 'default'
    here = _here(db, wish_list)
    baseline = _setting(db, source, 'baseline', {})
    mapping = translate(db, set(remote['owned']) | set(remote['wanted']))
    names = _names(db, [i for i in mapping.values() if i] + list(here['owned']) + list(here['wanted']))
    rows, unmatched = [], []
    for kind in ('owned', 'wanted'):
        there = {}
        for number, quantity in remote[kind].items():
            target = mapping.get(number)
            if target is None:
                unmatched.append(dict(key=f'{kind}:?{number}', kind=kind, remote_no=number, remote=quantity,
                                      state='unmatched', reason='No unique set in Brick Work for this number'))
                continue
            entry = there.setdefault(target, [0, number])
            entry[0] += quantity
        base_remote = baseline.get('remote', {}).get(kind, {})
        base_here = baseline.get('here', {}).get(kind, {})
        for item_id in sorted(set(there) | set(here[kind])):
            r, remote_no = there.get(item_id, [0, None])
            number, name = names.get(item_id, (None, None))
            rows.append(dict(key=f'{kind}:{item_id}', kind=kind, item_id=item_id, number=number or name, name=name, remote_no=remote_no,
                             remote=r, here=here[kind].get(item_id, 0),
                             baseline_remote=base_remote.get(str(item_id)), baseline_here=base_here.get(str(item_id))))
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
    row = db.execute("SELECT id FROM main.flag WHERE kind='tag' AND lower(name)=lower(?) AND archived_at IS NULL", (name,)).fetchone()
    if row:
        return row[0]
    identifier = uuid4().hex
    db.execute("INSERT INTO main.flag(id, name, kind, shown_on_grid, created_at) VALUES(?, ?, 'tag', 0, ?)", (identifier, name, store_now()))
    receipt['flag_created'] = identifier
    return identifier


def _placed_wish(db, wish_list, item_id, kind, count, via, actor):
    """Raise the live wish of the item in the list by `count` (keeping its condition), or make one. Returns the receipt entry."""
    from .. import add
    old = db.execute('SELECT condition FROM main.wish WHERE wishlist_id=? AND item_id=? AND color_key=0 AND archived_at IS NULL', (wish_list, item_id)).fetchone()
    scratch = {}
    add._add_wish(db, dict(list_id=wish_list, item_id=item_id, kind=kind, color_id=None, quantity=count, decision='another',
                           condition=old['condition'] if old else 'any'), scratch, via, actor)
    return scratch['wish']


def apply_pull(db, plan_id, ticked=None, *, via=None, actor=None):
    """Place one copy per missing unit of a set (design 4.3's preselection; flagged, condition and completeness unset), loose stock of the
    other kinds, and the missing wishes, in one transaction with one receipt. Never deletes or lowers anything here."""
    from .. import add, plans
    from ..admin import origin
    from ..pipeline import queue_new_items
    plan = load_plan(db, plan_id, 'pull')
    done = plans.applied(db, 'sync', plan_id)           # the database decides; the plan file can say applied for a write that rolled back
    if done:
        return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
    rows = _ticked(plan, ticked)
    if via is None:
        via, actor = origin()
    source, stamp = plan['source'], store_now()
    wish_list = plan['link'].get('wish_list') or 'default'
    receipt = dict(plan=plan_id, source=source, copies=[], stock=[], wishes=[], pending=[], flag=None, flag_created=None, baseline_before=None,
                   stock_flags=[], guards={}, jobs=[])
    from .. import wishlists
    with transaction(db):
        done = plans.applied(db, 'sync', plan_id)       # checked again under the write lock: a second submit waits here and finds the first one's marker
        if done:
            return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
        wishlists.require(db, wish_list)
        flag = receipt['flag'] = _flag(db, source, receipt) if any(r['kind'] == 'owned' for r in rows) else None
        touched = set()
        for row in rows:
            item_id = row['item_id']
            items.ensure(db, item_id)
            kind = db.execute('SELECT kind FROM main.item WHERE id=?', (item_id,)).fetchone()[0]
            touched.add(item_id)
            if row['kind'] == 'wanted':
                receipt['wishes'].append(_placed_wish(db, wish_list, item_id, kind, row['count'], via, actor))
            elif kind == 'set':
                for _ in range(row['count']):
                    copy_id, waiting = add._add_copy(db, dict(item_id=item_id, condition=None, completeness=None, note=None), via, actor)
                    receipt['copies'].append(copy_id)
                    receipt['guards'][copy_id] = dict(db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone())
                    db.execute('INSERT INTO main.copy_flag(copy_id, flag_id) VALUES(?, ?)', (copy_id, flag))
                    if waiting:
                        receipt['pending'].append(dict(waiting, copy_id=copy_id))
            else:
                change = stock.add_loose(db, item_id=item_id, quantity=row['count'], condition=None, via=via, actor=actor)
                receipt['stock'].append(change)
                if not db.execute('SELECT 1 FROM main.stock_flag WHERE stock_id=? AND flag_id=?', (change['id'], flag)).fetchone():
                    db.execute('INSERT INTO main.stock_flag(stock_id, flag_id) VALUES(?, ?)', (change['id'], flag))
                    receipt['stock_flags'].append([change['id'], flag])
        receipt['jobs'] = queue_new_items(db, touched)
        receipt['baseline_before'] = _setting(db, source, 'baseline')
        _put(db, source, 'baseline', _baseline(db, plan, wish_list))
        counts = dict(copies=len(receipt['copies']), stock=sum(c['quantity'] for c in receipt['stock']),
                      wishes_added=sum(1 for w in receipt['wishes'] if w['created']),
                      wishes_changed=sum(1 for w in receipt['wishes'] if not w['created']))
        receipt['counts'] = counts
        _put(db, source, 'last_pull', dict(at=stamp, plan=plan_id, counts=counts))
        audit(db, 'sync:' + plan_id, 'receipt', None, receipt, via=via, actor=actor)
        event = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        plans.mark(db, 'sync', plan_id, dict(event_id=event, counts=counts, at=stamp), source=source, created_at=plan['created_at'])
    plan['applied'] = dict(event_id=event, counts=counts, at=stamp)
    _store_plan(db, plan)
    return dict(event_id=event, already_applied=False, counts=counts)


def _baseline(db, plan, wish_list):
    """Remote counts as last seen and here counts now, per item id (as text: JSON keys)."""
    mapping = translate(db, set(plan['remote']['owned']) | set(plan['remote']['wanted']))
    remote = {}
    for kind in ('owned', 'wanted'):
        remote[kind] = {}
        for number, quantity in plan['remote'][kind].items():
            if mapping.get(number):
                key = str(mapping[number])
                remote[kind][key] = remote[kind].get(key, 0) + quantity
    here = _here(db, wish_list)
    return dict(at=now().isoformat(), remote=remote, here={k: {str(i): n for i, n in v.items()} for k, v in here.items()})


def _undo_pull(db, event, via, actor):
    """Reverse one pull exactly: the wishes, the stock, the copies it made (each still untouched), its flag and the baseline. Refused whole when
    anything it wrote was changed since."""
    from .. import add
    r = json.loads(event['new_value'])
    stamp = store_now()
    changed = 'Something from this sync has changed since · undo the later change first'
    for entry in r['wishes']:
        row = db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()
        if row is None or dict(row) != entry['after']:
            raise ValueError(changed)
    for entry in reversed(r['wishes']):
        row = db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()
        if entry['created']:
            db.execute('UPDATE main.wish SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, entry['id']))
        else:
            b = entry['before']
            db.execute('UPDATE main.wish SET quantity=?, updated_at=? WHERE id=?', (b['quantity'], b['updated_at'], entry['id']))
        audit(db, 'wish:' + entry['id'], 'undo_sync', dict(row), dict(db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()), via=via, actor=actor)
    flag = r.get('flag')
    for change in reversed(r['stock']):
        stock.undo_added(db, change, via=via, actor=actor)
        if [change['id'], flag] in r.get('stock_flags', [[change['id'], flag]] if change['created'] else []):   # only a link this pull made
            db.execute('DELETE FROM main.stock_flag WHERE stock_id=? AND flag_id=?', (change['id'], flag))
    for copy_id in reversed(r['copies']):
        row = db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()
        if row is not None and row['archived_at'] is not None:
            continue
        db.execute('DELETE FROM main.copy_flag WHERE copy_id=? AND flag_id=?', (copy_id, flag))
        if not add._copy_untouched(db, copy_id, r['guards'][copy_id]):
            raise ValueError(changed)
        if row['inventory_pending']:
            pending.cancel_pending_in(db, copy_id, via=via, actor=actor)
        db.execute('UPDATE main.copy SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, copy_id))
        audit(db, 'copy:' + copy_id, 'archived_at', None, stamp, via=via, actor=actor)
    if r.get('flag_created') and not any(db.execute(f'SELECT 1 FROM main.{t} WHERE flag_id=? LIMIT 1', (flag,)).fetchone() for t in ('copy_flag', 'stock_flag', 'wish_flag')):
        db.execute('DELETE FROM main.flag WHERE id=?', (r['flag_created'],))
    _put(db, r['source'], 'baseline', r['baseline_before'])
    audit(db, 'sync:' + r['plan'], 'undo', None, {'undoes': event['id']}, via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('sync', 'receipt', _undo_pull, admin=True)


def undo(db, event_id):
    """Reverse one pull exactly (`core.undo`); refused when anything it wrote was changed since."""
    return undoing.undo_event(db, event_id)


def plan_send(db, source, *, http=None):
    """The remote calls a send would make: one row per set whose count differs. Removals unticked."""
    _source(source)
    client, link_value, remote = _fetch(db, source, http)
    rows, unmatched, mapping = _compare(db, source, link_value, remote)
    targets = reverse(db, [r['item_id'] for r in rows if r['remote_no'] is None])
    out = []
    for row in rows:
        r, h = row['remote'], row['here']
        if r == h:
            continue
        remote_no = row['remote_no'] or targets.get(row['item_id'])
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
                        reason='No set number on ' + LABELS[source] + ' (the item has no number yet)' if unmatched_here else None))
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
        baseline = _setting(db, source, 'baseline', {'remote': {'owned': {}, 'wanted': {}}, 'here': {'owned': {}, 'wanted': {}}})
        for row in sent:
            baseline.setdefault('remote', {}).setdefault(row['kind'], {})[str(row['item_id'])] = row['send']
            baseline.setdefault('here', {}).setdefault(row['kind'], {})[str(row['item_id'])] = row['here']
        _put(db, source, 'baseline', baseline)
        _put(db, source, 'last_send', report)
        # A record, not an undoable receipt: remote changes cannot be taken back from here.
        audit(db, 'sync:' + source, 'send', None, dict(plan=plan_id, counts=summary))
    return dict(plan=plan_id, counts=summary, rows=[dict(key=k, **v) for k, v in results.items()],
                note='Remote changes are not undone by Brick Work\'s Undo.')
