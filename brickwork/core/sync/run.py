"""One Rebrickable run (#519): the choices of step 2, the plans a run reads, the merged preview and the stages it applies.

A run is not new sync logic. It reads the plans that already exist (`sync.plan_pull` with its Lost Parts and list-name sections,
`sync.plan_send`, `part_lists.plan`, `lost_parts_send.plan`), merges their rows into one row per set with the choices that row has, and
applies the chosen rows through the same applies, one stage after the other: the pull (sets, wishes, Lost Parts in, list names), the part
lists, the sends, the Lost Parts out. The run record is a plan file (`direction='run'`, 24 hours like every plan); it keeps the ids of the
plans it read, the sets picked, and what each stage did, because `lost_parts_send.apply` keeps no progress of its own.

Choices are kept without a schema change: the link (`sync.link`), the setting the Lost Parts pull rule already uses, the two settings of the
Lost Parts send (`lost_parts_send.KEY`, `RULE_KEY`) and `DIRECTIONS_KEY` here.
"""
import json
import sqlite3
from uuid import uuid4

from .. import errors, wishlists
from ..admin import audit
from ..sources.base import KeyRejected, SourceError, WaitingForBudget, now
from ..transaction import transaction
from .. import sync
from . import adapters, lost_parts, lost_parts_send, part_lists

SOURCE = 'rebrickable'
DIRECTIONS_KEY = 'rebrickable_sync_directions'
SEGMENTS = {'owned': ('into', 'both', 'to', 'off'), 'wishlist': ('into', 'both', 'to', 'off'), 'parts': ('into', 'off'), 'lost': ('into', 'both', 'to', 'off')}
SEGMENT_LABELS = {'into': 'Into Brick Work', 'both': 'Both ways', 'to': 'To Rebrickable', 'off': 'Off'}
MODE_LABELS = (('all', 'All linked'), ('list', 'By list'), ('theme', 'By theme'), ('year', 'By year'), ('one', 'One by one'))
MODES = tuple(m for m, _ in MODE_LABELS)
LIST_WORDS = {'rename': 'Rename it', 'keep': 'Keep', 'drop': 'Drop the name', 'skip': 'Skip'}
FAILURES = (errors.BrickWorkError, ValueError, SourceError, sqlite3.Error)


def _setting_row(db, key):
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (key,)).fetchone()
    return row[0] if row else None


def _put_setting(db, key, value):
    if value is None:
        db.execute('DELETE FROM main.setting WHERE key=?', (key,))
    else:
        db.execute('INSERT OR REPLACE INTO main.setting(key, value) VALUES(?, ?)', (key, value))


# Choices of step 2 ----------------------------------------------------------------------------------------------------

def link_value(db):
    return sync._setting(db, SOURCE, 'link', {})


def directions(db):
    """The direction of each kind of data: owned sets, the wishlist, loose stock, Lost Parts. Lost Parts come from the two switches that
    already exist (the pull's `lost_parts`, the send's setting); the others are remembered here, defaulting to what a plain sync did before
    (sets and wishes both ways) and to Into Brick Work for loose stock once a part list is chosen."""
    try:
        saved = json.loads(_setting_row(db, DIRECTIONS_KEY) or '{}')
    except ValueError:
        saved = {}
    link = link_value(db)
    out = {}
    for kind, default in (('owned', 'both'), ('wishlist', 'both'), ('parts', 'into' if link.get('part_lists') else 'off')):
        out[kind] = saved.get(kind) if saved.get(kind) in SEGMENTS[kind] else default
    into, out_ = sync.lost_parts_on(db, SOURCE), lost_parts_send.enabled(db)
    out['lost'] = 'both' if into and out_ else 'into' if into else 'to' if out_ else 'off'
    return out


def save_choices(db, form):
    """Save step 2 in one transaction. `form` holds the checked values: `owned_dir`, `wishlist_dir`, `parts_dir`, `lost_dir`, `owned`
    (list ids), `wishlist`, `send_to`, `wish_list`, `part_lists`, `lost_rule`, `send_rule`, `keep_list_names`. A value that does not fit
    raises ValidationFailed and nothing is saved."""
    for kind in SEGMENTS:
        if form.get(kind + '_dir') not in SEGMENTS[kind]:
            raise errors.ValidationFailed('Choose a direction for ' + kind)
    try:
        lost_parts.valid_rule(form['lost_rule'])
        lost_parts_send.valid_rule(form['send_rule'])
    except ValueError as exc:
        raise errors.ValidationFailed(str(exc)) from None
    lost = form['lost_dir']
    with transaction(db):
        before = dict(directions=_setting_row(db, DIRECTIONS_KEY), send_rule=_setting_row(db, lost_parts_send.RULE_KEY), send=_setting_row(db, lost_parts_send.KEY))
        sync.link(db, SOURCE, dict(wish_list=form['wish_list'], owned=form['owned'], wishlist=form['wishlist'], send_to=form['send_to'],
                                   part_lists=form['part_lists'], lost_parts=lost in ('into', 'both'), keep_list_names=bool(form['keep_list_names'])))
        if form['lost_rule'] != lost_parts.rule(db):
            from ..admin import patch_settings
            patch_settings(db, {'rebrickable_lost_parts_rule': form['lost_rule']})
        names = {k: v for k, v in (form.get('names') or {}).items() if isinstance(k, str) and isinstance(v, str)}
        saved = json.dumps(dict({k: form[k + '_dir'] for k in ('owned', 'wishlist', 'parts')}, names=names), sort_keys=True)
        _put_setting(db, DIRECTIONS_KEY, saved)
        _put_setting(db, lost_parts_send.RULE_KEY, form['send_rule'])
        _put_setting(db, lost_parts_send.KEY, 'on' if lost in ('to', 'both') else 'off')
        audit(db, 'sync:' + SOURCE, 'choices', before, dict(directions=saved, send_rule=form['send_rule'], lost=lost))
    return directions(db)


def lost_labels(db):
    """The two Lost Parts rules as the page names them: `(pull rule label, send rule label)`."""
    return lost_parts.RULE_LABELS[lost_parts.rule(db)], dict((v, l) for v, l, _ in lost_parts_send.RULES)[lost_parts_send.send_rule(db)]


def what_syncs(db):
    """The rows of the What syncs table of the page at rest, from what is stored: no call to Rebrickable."""
    from ...store4 import origins
    link = link_value(db)
    d = directions(db)
    names = {k: v for k, (v, _) in origins.lists_of(db, SOURCE).items()}
    try:
        saved = json.loads(_setting_row(db, DIRECTIONS_KEY) or '{}').get('names') or {}
    except ValueError:
        saved = {}
    names = dict(names, **saved)        # the names step 2 last showed, until a pull records new ones
    owned = link.get('owned') or []
    wish_lists = {w['id']: w['name'] for w in wishlists.listing(db)}
    into, sent = lost_labels(db)
    rows = []
    if d['owned'] != 'off':
        rows.append(dict(what='Owned sets', direction=SEGMENT_LABELS[d['owned']],
                         linked=(f"{len(owned)} set {'list' if len(owned) == 1 else 'lists'}: " + ', '.join(names.get('set:' + str(i)) or names.get(str(i), f'List {i}') for i in owned)) if owned
                         else 'Every set list except the wishlist list'))
    if d['wishlist'] != 'off':
        rows.append(dict(what='Wishlist', direction=SEGMENT_LABELS[d['wishlist']],
                         linked=('Rebrickable ' + (names.get('set:' + str(link['wishlist'])) or names.get(str(link['wishlist']), 'wishlist list')) + ' ↔ wishlist ' + wish_lists.get(link.get('wish_list') or 'default', 'Wanted'))
                         if link.get('wishlist') else 'No wishlist list linked'))
    parts = link.get('part_lists') or []
    if d['parts'] != 'off' and parts:
        rows.append(dict(what='Loose stock', direction=SEGMENT_LABELS['into'],
                         linked=f"{len(parts)} part {'list' if len(parts) == 1 else 'lists'}: " + ', '.join(names.get(f'part:{i}', f'List {i}') for i in parts)))
    if d['lost'] != 'off':
        rule = into if d['lost'] == 'into' else sent if d['lost'] == 'to' else f'{into} in, {sent} out'
        rows.append(dict(what='Lost Parts', direction=SEGMENT_LABELS[d['lost']], linked='Rule: ' + rule))
    return rows


# Planning -------------------------------------------------------------------------------------------------------------

def _facts(db, item_ids):
    """`{item id: (theme, year)}` from the collection's row, else the catalogue's."""
    out = {}
    packed = json.dumps(sorted(set(item_ids)))
    for r in db.execute('SELECT id, theme_name, year FROM main.item WHERE id IN (SELECT value FROM json_each(?))', (packed,)):
        out[r['id']] = (r['theme_name'], r['year'])
    if sync.has_catalogue(db):
        for r in db.execute('SELECT i.id, t.name AS theme, i.year FROM catalogue.item i LEFT JOIN catalogue.theme t ON t.id=i.theme_id '
                            'WHERE i.id IN (SELECT value FROM json_each(?))', (packed,)):
            out.setdefault(r['id'], (r['theme'], r['year']))
    return out


def _over_one_copy(db, rows):
    """A Lost Parts row sums the missing marks of every copy of the set, but the pull side rejects a count above one copy's line. Such a row is
    marked not sent, with the reason (the planner's own check sums the copies' lines too, so it cannot see this)."""
    for row in rows:
        if row['state'] not in ('add', 'change') or not row.get('tickable') or len(row.get('copies') or ()) < 2:
            continue
        item = sync.translate(db, [row['set_no']]).get(row['set_no'])
        held = lost_parts._copies(db, [item]).get(item, []) if item else []
        key = (row['part_no'], str(row['color_id']), bool(row['is_spare']))
        lines = [max((l['quantity'] for l in lost_parts._lines(db, c['id'])[1].get(key, [])), default=0) for c in held]
        biggest = max(lines, default=0)
        if biggest and row['after'] > biggest:
            row.update(tickable=False, ticked=False,
                       reason=f"The copies together miss {row['after']}, but one copy's line holds {biggest}. Rebrickable takes one copy's count")


def _lost_send(db, client):
    if not lost_parts_send.enabled(db):
        return None
    try:
        read = client.lost_parts()
    except SourceError as failure:
        read = sync._why(failure)
    planned = lost_parts_send.plan(db, read, sync.translate, rule=lost_parts_send.send_rule(db), on=True)
    _over_one_copy(db, planned['rows'])
    mapping = sync.translate(db, {r['set_no'] for r in planned['rows']})
    names = sync._names(db, [i for i in mapping.values() if i])
    for row in planned['rows']:
        row['item_id'] = mapping.get(row['set_no'])
        number, row['name'] = names.get(row['item_id']) or (None, None)
        row['number'] = number or row['set_no']
    return planned


def start(db, *, http=None):
    """Read what the saved choices cover and save the run. Writes nothing to the collection. Raises what a read of Rebrickable raises."""
    d = directions(db)
    link = link_value(db)
    sets_in = d['owned'] in ('into', 'both') or d['wishlist'] in ('into', 'both')
    sets_out = d['owned'] in ('to', 'both') or d['wishlist'] in ('to', 'both')
    lost_in_on = d['lost'] in ('into', 'both')
    pull = sync.plan_pull(db, SOURCE, http=http, lost_parts_switch=lost_in_on) if (sets_in or lost_in_on) else None
    send = sync.plan_send(db, SOURCE, http=http) if sets_out else None
    parts = part_lists.plan(db, http=http) if d['parts'] == 'into' and link.get('part_lists') else None
    lost_send = _lost_send(db, adapters.adapter(db, SOURCE, http)) if d['lost'] in ('to', 'both') else None
    run = dict(id=uuid4().hex, created_at=now().isoformat(), direction='run', source=SOURCE, directions=d,
               pull=pull and pull['id'], send=send and send['id'], parts=parts and parts['id'], lost_out=lost_send, picked=None, stages={})
    run['candidates'] = candidates(db, pull, send, lost_send)
    return sync._save_plan(db, run)


def load(db, run_id):
    """`(run, plans)`: the run record and the plans it read (`pull`, `send`, `parts`; None where the run read none)."""
    run = sync.load_plan(db, run_id, 'run')
    return run, {name: (sync.load_plan(db, run[name]) if run.get(name) else None) for name in ('pull', 'send', 'parts')}


def candidates(db, pull, send, lost_send):
    """One entry per set a run could touch (a row that differs, a Lost Parts set), for the pick step: item id, number, name, theme, year, lists."""
    found = {}

    def add(item_id, number, name, lists=()):
        if item_id is None:
            return
        entry = found.setdefault(item_id, dict(item_id=item_id, number=number, name=name, lists=[]))
        entry['lists'] = sorted(set(entry['lists']) | set(lists))
    for plan in (pull, send):
        for r in (plan or {}).get('rows', ()):
            add(r['item_id'], r['number'], r['name'], r.get('lists') or ())
    for e in ((pull or {}).get('lost') or {}).get('sets', ()):
        add(e['item_id'], e.get('number'), e.get('name'))
    for r in (lost_send or {}).get('rows', ()):
        add(r.get('item_id'), r.get('number'), r.get('name'))
    facts = _facts(db, list(found))
    for item_id, entry in found.items():
        entry['theme'], entry['year'] = facts.get(item_id, (None, None))
    return sorted(found.values(), key=lambda e: (str(e['number']), e['item_id']))


def picked_ids(run):
    """The item ids the run covers: None until the pick step is saved, then the picked ones."""
    return None if run.get('picked') is None else set(run['picked'])


def save_pick(db, run, ids, keep_names=None, *, http=None):
    """Save the sets picked. `keep_names` (True or False), when it differs from the plan's, reads the pull again with the other list-name
    switch (#531), because the plan decides which list names the preview offers."""
    ids = set(ids)
    if ids - {c['item_id'] for c in run['candidates']}:
        raise errors.ValidationFailed('Pick sets from the list')
    pull = sync.load_plan(db, run['pull']) if run.get('pull') else None
    if keep_names is not None and pull and bool((pull.get('lists') or {}).get('keep')) != bool(keep_names):
        pull = sync.plan_pull(db, SOURCE, http=http, lost_parts_switch=run['directions']['lost'] in ('into', 'both'), keep_list_names=bool(keep_names))
        run['pull'] = pull['id']
        run['candidates'] = candidates(db, pull, sync.load_plan(db, run['send']) if run.get('send') else None, run.get('lost_out'))
    run['picked'] = sorted(ids & {c['item_id'] for c in run['candidates']})
    sync._store_plan(db, run)
    return run


_TAGS = {'add': ('New there', 'info'), 'send_add': ('Only here', 'dash'), 'change': ('Quantity differs', 'warning'), 'remove': ('Removes there', 'danger'),
         'differs': ('Different', 'warning'), 'only_here': ('Only here', 'unknown'), 'conflict': ('Changed in both places', 'warning'),
         'unmatched': ('Not matched', 'unknown'), 'info': ('Same', 'unknown'), 'gone': ('Gone here', 'dash')}


def rows(db, run, plans):
    """The preview rows: one per set and kind, with the choices each has. An option is `dict(id, label, note)`: `pull` adds the difference here,
    `take` takes Rebrickable's count (a pull only raises a count here), `send` sends the count here, `remove` takes the set off the list
    there (unticked), `keep` leaves both sides (the first of a row with a choice). `default` is the option chosen at first, if any."""
    d, picked = run['directions'], picked_ids(run)
    merged = {}

    def row_of(r):
        return merged.setdefault(r['key'], dict(key=r['key'], item_id=r['item_id'], kind=r['kind'], number=r['number'], name=r['name'], remote=r['remote'],
                                                here=r['here'], remote_no=r['remote_no'], options=[], default=None, state='info', reason=None))
    for r in (plans['pull'] or {}).get('rows', ()):
        if picked is not None and r['item_id'] not in picked:
            continue
        if d['owned' if r['kind'] == 'owned' else 'wishlist'] not in ('into', 'both'):
            continue
        row = row_of(r)
        if r['state'] == 'add' and r['tickable']:
            row['state'] = 'add'
            row['options'].append(dict(id='pull', label=f"Add {r['count']} here" if r['kind'] == 'owned' else 'Add to wishlist here', note=None))
            row['default'] = 'pull'
        elif r['state'] == 'conflict':
            row['state'] = 'conflict'
            if r['tickable']:
                row['options'].append(dict(id='take', label=f"Take {r['remote']} from Rebrickable", note=f"Brick Work becomes {r['remote']}"))
        else:
            row['state'] = r['state']
    for r in (plans['send'] or {}).get('rows', ()):
        if picked is not None and r['item_id'] not in picked:
            continue
        if d['owned' if r['kind'] == 'owned' else 'wishlist'] not in ('to', 'both'):
            continue
        row = row_of(r)
        if r['state'] == 'conflict':
            row['state'] = 'conflict'
            if r['tickable']:
                row['options'].append(dict(id='send', label=f"Send {r['send']} to Rebrickable", note=f"Rebrickable becomes {r['send']}"))
        elif r['state'] in ('remove', 'change') and r['tickable'] and any(o['id'] == 'pull' for o in row['options']):
            # Rebrickable has more than here: a lower count there is offered only when this set was lowered here since the last run
            if (r.get('baseline_here') or 0) > r['here'] and r.get('baseline_remote') is not None:
                row['state'] = 'gone'
                row['options'].append(dict(id='remove' if r['state'] == 'remove' else 'send',
                                           label='Remove from Rebrickable' if r['state'] == 'remove' else f"Quantity {r['remote']} to {r['send']}",
                                           note='Takes the set off the list there' if r['state'] == 'remove' else None))
        elif r['state'] == 'remove' and r['tickable']:        # only sending: a set taken off the list here is offered for the list there, unticked
            row['state'] = 'remove'
            row['options'].append(dict(id='remove', label='Remove from Rebrickable', note=None))
        elif r['state'] in ('add', 'change') and r['tickable'] and r['action']:
            row['state'] = 'send_add' if r['state'] == 'add' else 'change'
            row['options'].append(dict(id='send', label=(f"Add {r['send']} there" if r['state'] == 'add' else f"Quantity {r['remote']} to {r['send']}"), note=None))
            row['default'] = row['default'] or 'send'
        elif r.get('reason'):
            row['state'], row['reason'] = 'unmatched', r['reason']
    out = []
    for row in merged.values():
        if row['state'] == 'gone':     # gone here: nothing is sent or added unless chosen
            row['options'] = [dict(o, label=('Add back here' if o['id'] == 'pull' else o['label'])) for o in row['options']]
            row['default'] = None
        if row['state'] == 'conflict' or len(row['options']) > 1 or row['state'] == 'gone':
            row['options'].insert(0, dict(id='keep', label=f"Keep {row['here']} here", note='Nothing sent'))
        row['tag'], row['tone'] = _TAGS[row['state']]
        row['group'] = ('both' if row['state'] == 'conflict' else 'into' if any(o['id'] in ('pull', 'take') for o in row['options'])
                        else 'to' if row['options'] else 'info')
        out.append(row)
    for u in (plans['pull'] or {}).get('unmatched', ()):
        if d['owned' if u['kind'] == 'owned' else 'wishlist'] in ('into', 'both'):
            out.append(dict(key=u['key'], item_id=None, kind=u['kind'], number=u['remote_no'], name='Not matched', remote=u['remote'], here=0, options=[],
                            default=None, state='unmatched', reason=u['reason'], tag='Not matched', tone='unknown', group='info', remote_no=u['remote_no']))
    return sorted(out, key=lambda r: (r['state'] != 'conflict', str(r['number'])))


def lost_in(run, plans):
    """The Lost Parts section of the pull, narrowed to the sets picked (None when Lost Parts do not come in)."""
    section = (plans['pull'] or {}).get('lost') or {}
    picked = picked_ids(run)
    if run['directions']['lost'] not in ('into', 'both') or not section:
        return None
    return dict(section, sets=[e for e in section.get('sets', ()) if picked is None or e['item_id'] in picked])


def lost_out(run):
    """The Lost Parts send plan, narrowed to the sets picked (None when Lost Parts do not go out)."""
    section = run.get('lost_out')
    picked = picked_ids(run)
    if not section:
        return None
    return dict(section, rows=[r for r in section['rows'] if picked is None or r.get('item_id') in picked])


def part_rows(plans):
    return (plans['parts'] or {}).get('rows', [])


def budget(db):
    try:
        status = adapters.ADAPTERS[SOURCE](db).status()
        return dict(used=status['used_today'], budget=status['budget'], last_success=status['last_success'], key=status['key_state'])
    except Exception:
        return None


# Applying -------------------------------------------------------------------------------------------------------------

def _message(exc):
    if isinstance(exc, KeyRejected):
        return 'Rebrickable rejected the key or user token. Nothing more was changed there.'
    if isinstance(exc, WaitingForBudget):
        return 'Rebrickable is paused: the daily budget is used up. Try again after ' + (exc.retry_at or 'midnight UTC')[:16].replace('T', ' ') + '.'
    if isinstance(exc, SourceError):
        return 'Rebrickable could not be reached. Nothing more was changed there.'
    return str(exc) or 'This step could not be done.'


def apply(db, run_id, form, *, http=None, via=None, actor=None):
    """Apply the chosen rows, stage by stage. `form` is a MultiDict of the preview's fields: `choice:<row key>` (pull, take, send, remove, keep),
    `lost` and `copy:<set no>` (Lost Parts in), `list:<key>` (list names), `part` and `lot:<key>` (loose stock), `lostsend` (Lost Parts out).
    A stage that fails says so in the run, and the next one still runs. Returns the run, saved; a run already applied is returned as it is."""
    run, plans = load(db, run_id)
    if run.get('applied'):
        return run
    shown = rows(db, run, plans)
    allowed = {r['key']: {o['id'] for o in r['options']} for r in shown}
    chosen = {k: form.get('choice:' + k) or 'keep' for k, ids in allowed.items() if ids}
    if any(v != 'keep' and v not in allowed[k] for k, v in chosen.items()):
        raise errors.ValidationFailed('Choose one of the offered changes for each row')
    stages, events = run['stages'], []
    pull = plans['pull']
    if pull:
        wanted = [k for k, v in chosen.items() if v in ('pull', 'take')]
        listed = lost_in(run, plans)
        lost = [s for s in form.getlist('lost') if s in {e['set_no'] for e in listed['sets']}] if listed else None
        picks = {k.removeprefix('copy:'): v for k, v in form.items() if k.startswith('copy:') and v}
        if listed:
            picks = {k: v for k, v in picks.items() if k in {e['set_no'] for e in listed['sets']}}
            lost = sorted(set(lost or ()) | set(picks))        # choosing a copy for a set is ticking it
        lines = {line['key']: line for line in (pull.get('lists') or {}).get('preview', ())}
        lists = {k.removeprefix('list:'): v for k, v in form.items() if k.startswith('list:') and k.removeprefix('list:') in lines}
        if wanted or lost or picks or any(v not in ('keep', 'skip') for v in lists.values()):
            try:
                result = sync.apply_pull(db, pull['id'], wanted, lost=lost, picks=picks or None, lists=lists or None, via=via, actor=actor)
                stages['pull'] = dict(status='done', event=result['event_id'], counts=result['counts'], rows=len(wanted))
                events.append(result['event_id'])
            except FAILURES as exc:
                stages['pull'] = dict(status='failed', message=_message(exc))
        else:
            stages['pull'] = dict(status='none')
        sync._store_plan(db, run)
    if plans['parts']:
        wanted = [k for k in form.getlist('part') if k in {r['key'] for r in part_rows(plans)}]
        lots = {k.removeprefix('lot:'): v for k, v in form.items() if k.startswith('lot:') and v and k.removeprefix('lot:') in wanted}
        if wanted:
            try:
                result = part_lists.apply(db, plans['parts']['id'], wanted, lots=lots or None, via=via, actor=actor)
                stages['parts'] = dict(status='done', event=result['event_id'], counts=result['counts'], rows=len(wanted))
                events.append(result['event_id'])
            except FAILURES as exc:
                stages['parts'] = dict(status='failed', message=_message(exc))
        else:
            stages['parts'] = dict(status='none')
        sync._store_plan(db, run)
    if plans['send']:
        wanted = [k for k, v in chosen.items() if v in ('send', 'remove')]
        if wanted:
            try:
                result = sync.apply_send(db, plans['send']['id'], wanted, http=http)
                stages['send'] = dict(status='done', counts=result['counts'], rows=len(wanted), results=result['rows'])
            except FAILURES as exc:
                stages['send'] = dict(status='failed', message=_message(exc))
        else:
            stages['send'] = dict(status='none')
        sync._store_plan(db, run)
    section = lost_out(run)
    if section:
        wanted = [k for k in form.getlist('lostsend') if k in {r['key'] for r in section['rows'] if r.get('tickable')}]
        stages['lost_out'] = _apply_lost_out(db, run, wanted, http) if wanted else dict(status='none')
        sync._store_plan(db, run)
    with transaction(db):
        audit(db, 'sync:' + SOURCE, 'run', None, dict(run=run['id'], events=events), via=via, actor=actor)
    run['applied'] = dict(at=now().isoformat(), events=events)
    sync._store_plan(db, run)
    return run


def _apply_lost_out(db, run, wanted, http):
    planned = run['lost_out']
    message = None
    try:
        reply = lost_parts_send.apply(db, adapters.adapter(db, SOURCE, http), planned, wanted)
    except KeyRejected as exc:
        reply = getattr(exc, 'partial', dict(sent=[], failed=[], remaining=[]))
        message = _message(exc)
    except (SourceError, ValueError) as exc:
        return dict(status='failed', message=_message(exc))
    for part in ('sent', 'failed', 'remaining'):
        for row in reply[part]:
            for i, old in enumerate(planned['rows']):
                if old['key'] == row['key']:
                    planned['rows'][i] = dict(row, outcome='sent' if part == 'sent' else 'failed' if part == 'failed' else 'waiting')
    counts = dict(sent=len(reply['sent']), failed=len(reply['failed']), waiting=len(reply['remaining']))
    sync._store_plan(db, run)      # what Rebrickable took is written down before anything else can fail: a second post must not send it again
    with transaction(db):
        audit(db, 'sync:' + SOURCE, 'send', None, dict(plan=run['id'], kind='lost_parts', counts={k: v for k, v in dict(sent=counts['sent'], failed=counts['failed'], paused=counts['waiting']).items() if v}))
    return dict(status='done' if not (counts['failed'] or counts['waiting']) else 'partial', counts=counts, message=message,
                failed=[dict(key=r['key'], set_no=r['set_no'], part_no=r['part_no'], reason=r.get('reason')) for r in reply['failed']])


def undo_run(db, event_id):
    """Undo a pull and the part-list pull of the same run in one step (the run is found by either event). Raises UndoBlocked, and undoes
    nothing, when something it wrote changed since."""
    from .. import undo as undoing
    ids = [event_id]
    for row in db.execute("SELECT new_value FROM event WHERE entity_kind='sync' AND field='run' ORDER BY id DESC LIMIT 200"):
        events = (json.loads(row['new_value']) or {}).get('events', []) if row['new_value'] else []
        if event_id in events:
            ids = list(events)
            break
    with transaction(db):
        for e in reversed(ids):
            undoing.undo_event(db, e)
    return ids


def retry_send(db, run_id, *, http=None):
    """Send again the rows of the run's send stage that did not go through (failed, paused or refused). The send plan keeps what was sent."""
    run, plans = load(db, run_id)
    send = plans['send']
    stage = (run.get('stages') or {}).get('send')
    if not send or not stage or not stage.get('results'):
        raise errors.ValidationFailed('This run sent nothing that can be retried')
    again = [r['key'] for r in stage['results'] if r['result'] not in ('sent', 'unchanged')]
    if not again:
        raise errors.ValidationFailed('Everything this run sent went through')
    result = sync.apply_send(db, send['id'], again, http=http)
    run['stages']['send'] = dict(status='done', counts=result['counts'], rows=len(result['rows']), results=result['rows'])
    sync._store_plan(db, run)
    return run
