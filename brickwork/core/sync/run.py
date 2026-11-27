"""One Rebrickable, Brickset or Brick Owl run (#519, #520, #522): the choices of step 2, the plans a run reads, the merged preview and the stages it applies.

A run is not new sync logic. It reads the plans that already exist (`sync.plan_pull` with its Lost Parts and list-name sections,
`sync.plan_send`, `part_lists.plan`, `lost_parts_send.plan`), merges their rows into one row per set with the choices that row has, and
applies the chosen rows through the same applies, one stage after the other: the pull (sets, wishes, Lost Parts in, list names), the part
lists, the sends, the Lost Parts out. The run record is a plan file (`direction='run'`, 24 hours like every plan); it keeps the ids of the
plans it read, the sets picked, and what each stage did, because `lost_parts_send.apply` keeps no progress of its own.

A run takes its site from its own record (`run['source']`); every other function takes `source`, Rebrickable when left out. Brickset has
owned and wanted sets with counts only: no lists, part lists or Lost Parts, so those stages never run for it. The same holds for Brick Owl,
which links one of its wishlists too (`wishlist_id`) and gets one send per row, not per set number.

Choices are kept without a schema change: the link (`sync.link`), the setting the Lost Parts pull rule already uses, the two settings of the
Lost Parts send (`lost_parts_send.KEY`, `RULE_KEY`) and `DIRECTIONS_KEY` here.
"""
import fcntl
import json
import logging
import sqlite3
from uuid import uuid4

from .. import errors, wishlists
from ..admin import audit
from ..sources.base import KeyRejected, SourceError, WaitingForBudget, now
from ..transaction import transaction
from .. import sync
from . import adapters, lost_parts, lost_parts_send, part_lists

INTERRUPTED_MESSAGE = 'Interrupted: check what was sent and run again.'     # the message of a stage a restart cut off (`run_job`, `retry_send`)
SOURCE = 'rebrickable'
SOURCES = ('rebrickable', 'brickset', 'brickowl')
DIRECTIONS_KEY = 'rebrickable_sync_directions'
DIRECTIONS_KEYS = {'rebrickable': DIRECTIONS_KEY, 'brickset': 'brickset_sync_directions', 'brickowl': 'brickowl_sync_directions'}
SEGMENTS = {'owned': ('into', 'both', 'to', 'off'), 'wishlist': ('into', 'both', 'to', 'off'), 'parts': ('into', 'off'), 'lost': ('into', 'both', 'to', 'off')}
SEGMENT_LABELS = {'into': 'Into Brick Work', 'both': 'Both ways', 'to': 'To Rebrickable', 'off': 'Off'}
SEGMENT_LABELS_BY = {'rebrickable': SEGMENT_LABELS, 'brickset': dict(SEGMENT_LABELS, to='To Brickset'), 'brickowl': dict(SEGMENT_LABELS, to='To Brick Owl')}
MODE_LABELS = (('all', 'All linked'), ('list', 'By list'), ('theme', 'By theme'), ('year', 'By year'), ('one', 'One by one'))
MODES = tuple(m for m, _ in MODE_LABELS)
_NO_LISTS = tuple(m for m in MODE_LABELS if m[0] != 'list')      # Brickset and Brick Owl have no set lists to pick by
MODE_LABELS_BY = {'rebrickable': MODE_LABELS, 'brickset': _NO_LISTS, 'brickowl': _NO_LISTS}
def segments():
    """`SEGMENTS` as offered now: without a way out for Lost Parts while their send is locked."""
    return dict(SEGMENTS, lost=('into', 'off')) if lost_parts_send.SEND_LOCKED else SEGMENTS


KINDS_BY = {'rebrickable': tuple(SEGMENTS), 'brickset': ('owned', 'wishlist'), 'brickowl': ('owned', 'wishlist')}       # the kinds of data each site has a direction for
LIST_WORDS = {'rename': 'Rename it', 'keep': 'Keep', 'drop': 'Drop the name', 'skip': 'Skip'}
LOG = logging.getLogger(__name__)
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

def link_value(db, source=SOURCE):
    return sync._setting(db, source, 'link', {})


def directions(db, source=SOURCE):
    """The direction of each kind of data: owned sets, the wishlist, loose stock, Lost Parts. Lost Parts come from the two switches that
    already exist (the pull's `lost_parts`, the send's setting); the others are remembered here, defaulting to what a plain sync did before
    (sets and wishes both ways) and to Into Brick Work for loose stock once a part list is chosen."""
    try:
        saved = json.loads(_setting_row(db, DIRECTIONS_KEYS[source]) or '{}')
    except ValueError:
        saved = {}
    if source != SOURCE:           # owned and wanted sets only: loose stock and Lost Parts are Rebrickable's
        return dict({kind: saved.get(kind) if saved.get(kind) in SEGMENTS[kind] else 'both' for kind in KINDS_BY[source]}, parts='off', lost='off')
    link = link_value(db)
    out = {}
    for kind, default in (('owned', 'both'), ('wishlist', 'both'), ('parts', 'into' if link.get('part_lists') else 'off')):
        out[kind] = saved.get(kind) if saved.get(kind) in SEGMENTS[kind] else default
    into, out_ = sync.lost_parts_on(db, SOURCE), lost_parts_send.enabled(db)
    out['lost'] = 'both' if into and out_ else 'into' if into else 'to' if out_ else 'off'
    return out


def save_choices(db, form, source=SOURCE):
    """Save step 2 in one transaction. `form` holds the checked values: `owned_dir`, `wishlist_dir`, `parts_dir`, `lost_dir`, `owned`
    (list ids), `wishlist`, `send_to`, `wish_list`, `part_lists`, `lost_rule`, `send_rule`, `keep_list_names`. A value that does not fit
    raises ValidationFailed and nothing is saved."""
    if source != SOURCE:
        return _save_sets_choices(db, form, source)
    if lost_parts_send.SEND_LOCKED and form.get('lost_dir') in ('to', 'both'):
        raise errors.ValidationFailed(lost_parts_send.LOCKED_MESSAGE)
    for kind in SEGMENTS:
        if form.get(kind + '_dir') not in segments()[kind]:
            raise errors.ValidationFailed('Choose a direction for ' + kind)
    try:
        lost_parts.valid_rule(form['lost_rule'])
        lost_parts_send.valid_rule(form['send_rule'])
    except ValueError as exc:
        raise errors.ValidationFailed(str(exc)) from None
    lost = form['lost_dir']
    with transaction(db):
        before = dict(directions=_setting_row(db, DIRECTIONS_KEY))
        stored = link_value(db)
        stored_names = _saved_names(db)
        names = dict(form.get('names') or {})
        if form.get('keep_set_links'):       # the set lists could not be read, so the form carried none: those links and their names stay
            form.update(owned=stored.get('owned') or [], wishlist=stored.get('wishlist'), send_to=stored.get('send_to'))
            names = {**{k: v for k, v in names.items() if not k.startswith('set:')}, **{k: v for k, v in stored_names.items() if k.startswith('set:')}}
        if form.get('keep_part_links'):      # the same for the part lists
            form.update(part_lists=stored.get('part_lists') or [])
            names = {**{k: v for k, v in names.items() if not k.startswith('part:')}, **{k: v for k, v in stored_names.items() if k.startswith('part:')}}
        form['names'] = names
        sync.link(db, SOURCE, dict(wish_list=form['wish_list'], owned=form['owned'], wishlist=form['wishlist'], send_to=form['send_to'],
                                   part_lists=form['part_lists'], lost_parts=lost in ('into', 'both'), keep_list_names=bool(form['keep_list_names'])))
        from ..admin import patch_settings
        patch_settings(db, {'rebrickable_lost_parts_rule': form['lost_rule'], 'rebrickable_lost_parts_send': lost in ('to', 'both'),
                            'rebrickable_lost_parts_send_rule': form['send_rule']})
        names = {k: v for k, v in (form.get('names') or {}).items() if isinstance(k, str) and isinstance(v, str)}
        saved = json.dumps(dict({k: form[k + '_dir'] for k in ('owned', 'wishlist', 'parts')}, names=names), sort_keys=True)
        _put_setting(db, DIRECTIONS_KEY, saved)
        audit(db, 'sync:' + SOURCE, 'choices', before, dict(directions=saved, send_rule=form['send_rule'], lost=lost))
    return directions(db)


def _save_sets_choices(db, form, source):
    """Step 2 of a site with owned and wanted sets only: `owned_dir`, `wishlist_dir`, `wish_list` (the Brick Work wishlist that takes the wanted
    sets) and, for Brick Owl, `wishlist_id` (its wishlist there; left as it is when the form does not carry it). One transaction."""
    for kind in KINDS_BY[source]:
        if form.get(kind + '_dir') not in SEGMENTS[kind]:
            raise errors.ValidationFailed('Choose a direction for ' + kind)
    with transaction(db):
        before = dict(directions=_setting_row(db, DIRECTIONS_KEYS[source]))
        options = dict(wish_list=form.get('wish_list') or 'default')
        if source == 'brickowl' and 'wishlist_id' in form:
            options['wishlist_id'] = form['wishlist_id'] or None
        sync.link(db, source, options)
        saved = json.dumps({k: form[k + '_dir'] for k in KINDS_BY[source]}, sort_keys=True)
        _put_setting(db, DIRECTIONS_KEYS[source], saved)
        audit(db, 'sync:' + source, 'choices', before, dict(directions=saved))
    return directions(db, source)


def _saved_names(db):
    try:
        return json.loads(_setting_row(db, DIRECTIONS_KEY) or '{}').get('names') or {}
    except ValueError:
        return {}


def lost_labels(db):
    """The two Lost Parts rules as the page names them: `(pull rule label, send rule label)`."""
    return lost_parts.RULE_LABELS[lost_parts.rule(db)], dict((v, l) for v, l, _ in lost_parts_send.RULES)[lost_parts_send.send_rule(db)]


def _sets_what_syncs(db, source):
    link = link_value(db, source)
    d = directions(db, source)
    labels = SEGMENT_LABELS_BY[source]
    wish_lists = {w['id']: w['name'] for w in wishlists.listing(db)}
    rows = []
    if d['owned'] != 'off':
        rows.append(dict(what='Owned sets', direction=labels[d['owned']], linked='Quantity owned'))
    if d['wishlist'] != 'off':
        linked = 'Quantity wanted ↔ wishlist ' + wish_lists.get(link.get('wish_list') or 'default', 'Wanted')
        if source == 'brickowl' and not link.get('wishlist_id'):      # nothing is read or sent without one
            linked = 'No Brick Owl wishlist linked'
        rows.append(dict(what='Wanted sets', direction=labels[d['wishlist']], linked=linked))
    return rows


def what_syncs(db, source=SOURCE):
    """The rows of the What syncs table of the page at rest, from what is stored: no call to the site."""
    if source != SOURCE:
        return _sets_what_syncs(db, source)
    from ...store4 import origins
    link = link_value(db)
    d = directions(db)
    recorded = {k: v for k, (v, _) in origins.lists_of(db, SOURCE).items()}       # names a pull recorded come first, then those step 2 showed
    saved = _saved_names(db)
    set_name = lambda i: recorded.get(str(i)) or saved.get('set:' + str(i)) or f'List {i}'     # noqa: E731
    part_name = lambda i: recorded.get('part:' + str(i)) or saved.get('part:' + str(i)) or f'List {i}'     # noqa: E731
    owned = link.get('owned') or []
    wish_lists = {w['id']: w['name'] for w in wishlists.listing(db)}
    into, sent = lost_labels(db)
    rows = []
    if d['owned'] != 'off':
        rows.append(dict(what='Owned sets', direction=SEGMENT_LABELS[d['owned']],
                         linked=(f"{len(owned)} set {'list' if len(owned) == 1 else 'lists'}: " + ', '.join(set_name(i) for i in owned)) if owned
                         else 'Every set list except the wishlist list'))
    if d['wishlist'] != 'off':
        rows.append(dict(what='Wishlist', direction=SEGMENT_LABELS[d['wishlist']],
                         linked=('Rebrickable ' + set_name(link['wishlist']) + ' ↔ wishlist ' + wish_lists.get(link.get('wish_list') or 'default', 'Wanted'))
                         if link.get('wishlist') else 'No wishlist list linked'))
    parts = link.get('part_lists') or []
    if d['parts'] != 'off' and parts:
        rows.append(dict(what='Loose stock', direction=SEGMENT_LABELS['into'],
                         linked=f"{len(parts)} part {'list' if len(parts) == 1 else 'lists'}: " + ', '.join(part_name(i) for i in parts)))
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


def start(db, *, http=None, source=SOURCE):
    """Read what the saved choices cover and save the run. Writes nothing to the collection. Raises what a read of the site raises."""
    d = directions(db, source)
    link = link_value(db, source)
    sets_in = d['owned'] in ('into', 'both') or d['wishlist'] in ('into', 'both')
    send_kinds = tuple(k for k, key in (('owned', 'owned'), ('wanted', 'wishlist')) if d[key] in ('to', 'both'))
    lost_in_on = d['lost'] in ('into', 'both')
    want_pull = sets_in or lost_in_on
    want_send = bool(send_kinds)
    fetched = sync._fetch(db, source, http) if want_pull and want_send else None
    pull = (sync.plan_pull(db, source, http=http, lost_parts_switch=lost_in_on, fetched=fetched) if source == 'rebrickable'
            else sync.plan_pull(db, source, http=http, fetched=fetched)) if want_pull else None
    send = sync.plan_send(db, source, http=http, kinds=send_kinds, fetched=fetched) if want_send else None
    parts = part_lists.plan(db, http=http) if d['parts'] == 'into' and link.get('part_lists') else None
    lost_send = _lost_send(db, adapters.adapter(db, SOURCE, http)) if d['lost'] in ('to', 'both') else None
    run = dict(id=uuid4().hex, created_at=now().isoformat(), direction='run', source=source, directions=d,
               pull=pull and pull['id'], send=send and send['id'], parts=parts and parts['id'], lost_out=lost_send, picked=None, stages={})
    run['candidates'] = candidates(db, d, pull, send, lost_send, source)
    return sync._save_plan(db, run)


def load(db, run_id):
    """`(run, plans)`: the run record and the plans it read (`pull`, `send`, `parts`; None where the run read none)."""
    run = sync.load_plan(db, run_id, 'run')
    return run, {name: (sync.load_plan(db, run[name]) if run.get(name) else None) for name in ('pull', 'send', 'parts')}


def candidates(db, d, pull, send, lost_send, source=SOURCE):
    """One entry per set a run could touch (a row that differs, a Lost Parts set), for the pick step: item id, number, name, theme, year, lists."""
    found = {}

    def add(item_id, number, name, lists=()):
        if item_id is None:
            return
        entry = found.setdefault(item_id, dict(item_id=item_id, number=number, name=name, lists=[]))
        entry['lists'] = sorted(set(entry['lists']) | set(lists))
    for plan, ways in ((pull, ('into', 'both')), (send, ('to', 'both'))):
        for r in (plan or {}).get('rows', ()):
            if d['owned' if r['kind'] == 'owned' else 'wishlist'] in ways:    # a kind that is Off in this direction is not a set this run touches
                add(r['item_id'], r['number'], r['name'], r.get('lists') or ())
    if d['lost'] in ('into', 'both'):
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


def save_pick(db, run_id, ids, keep_names=None, *, http=None):
    """Save the sets picked, under the run's lock and on the run as it is then: a run that is applying or applied is not changed. `keep_names`
    (True or False), when it differs from the plan's, reads the pull again with the other list-name switch (#531), because the plan decides
    which list names the preview offers. Returns the run."""
    with _Claim(db, run_id):
        run = sync.load_plan(db, run_id, 'run')
        if run.get('applied') or run.get('applying') or run.get('job'):
            raise errors.ValidationFailed('This run has already run')
        ids = set(ids)
        if ids - {c['item_id'] for c in run['candidates']}:
            raise errors.ValidationFailed('Pick sets from the list')
        pull = sync.load_plan(db, run['pull']) if run.get('pull') else None
        if keep_names is not None and pull and run.get('source', SOURCE) == SOURCE and bool((pull.get('lists') or {}).get('keep')) != bool(keep_names):
            pull = sync.plan_pull(db, SOURCE, http=http, lost_parts_switch=run['directions']['lost'] in ('into', 'both'), keep_list_names=bool(keep_names))
            run['pull'] = pull['id']
            run['candidates'] = candidates(db, run['directions'], pull, sync.load_plan(db, run['send']) if run.get('send') else None, run.get('lost_out'), SOURCE)
        run['picked'] = sorted(ids & {c['item_id'] for c in run['candidates']})
        sync._store_plan(db, run)
        return run


_TAGS = {'add': ('New there', 'info'), 'send_add': ('Only here', 'dash'), 'change': ('Quantity differs', 'warning'), 'remove': ('Removes there', 'danger'),
         'differs': ('Different', 'warning'), 'only_here': ('Only here', 'unknown'), 'conflict': ('Changed in both places', 'warning'),
         'unmatched': ('Not matched', 'unknown'), 'info': ('Same', 'unknown'), 'gone': ('Gone here', 'dash')}


def _lot_note(row):
    return 'Deletes a lot there' if row.get('deletes_lot') else None


def _gone_note(row):
    if row['state'] != 'remove':
        return _lot_note(row)
    return 'Takes the set off the list there' + (' · deletes a lot there' if row.get('deletes_lot') else '')


def rows(db, run, plans):
    """The preview rows: one per set and kind, with the choices each has. An option is `dict(id, label, note)`: `pull` adds the difference here,
    `take` takes Rebrickable's count (a pull only raises a count here), `send` sends the count here, `remove` takes the set off the list
    there (unticked), `keep` leaves both sides (the first of a row with a choice). `default` is the option chosen at first, if any."""
    d, picked = run['directions'], picked_ids(run)
    source = run.get('source', SOURCE)
    site = sync.LABELS[source]
    merged = {}

    def row_of(r):
        return merged.setdefault(r['key'], dict(key=r['key'], item_id=r['item_id'], kind=r['kind'], number=r['number'], name=r['name'], remote=r['remote'],
                                                here=r['here'], remote_no=r['remote_no'], options=[], default=None, state='info', reason=None,
                                                kept=bool(r.get('kept')) or ((r.get('baseline_remote') or 0) == r['remote'] and (r.get('baseline_here') or 0) == r['here'] and r['remote'] != r['here'])))
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
                row['options'].append(dict(id='take', label=f"Take {r['remote']} from {site}", note=f"Brick Work becomes {r['remote']}"))
        else:
            row['state'] = r['state']
    for r in (plans['send'] or {}).get('rows', ()):
        if picked is not None and r['item_id'] not in picked:
            continue
        if d['owned' if r['kind'] == 'owned' else 'wishlist'] not in ('to', 'both'):
            continue
        row = row_of(r)
        row['send_no'] = r.get('remote_no')          # the number a send goes to: Brickset gets one call per set number, whatever kind the row is
        if r['state'] == 'conflict':
            row['state'] = 'conflict'
            if r['tickable']:
                note = f"{site} becomes {r['send']}" + (' · deletes a lot there' if r.get('deletes_lot') else '')
                row['options'].append(dict(id='send', label=f"Send {r['send']} to {site}", note=note))
        elif r['state'] in ('remove', 'change') and r['tickable'] and any(o['id'] == 'pull' for o in row['options']):
            # Rebrickable has more than here: a lower count there is offered only when this set was lowered here since the last run
            if (r.get('baseline_here') or 0) > r['here'] and r.get('baseline_remote') is not None:
                row['state'] = 'gone'
                row['options'].append(dict(id='remove' if r['state'] == 'remove' else 'send',
                                           label=f'Remove from {site}' if r['state'] == 'remove' else f"Quantity {r['remote']} to {r['send']}",
                                           note=_gone_note(r)))
        elif r['state'] == 'remove' and r['tickable']:        # only sending: a set taken off the list here is offered for the list there, unticked
            row['state'] = 'remove'
            row['options'].append(dict(id='remove', label=f'Remove from {site}', note=_lot_note(r)))
        elif r['state'] in ('add', 'change') and r['tickable'] and r['action']:
            row['state'] = 'send_add' if r['state'] == 'add' else 'change'
            row['options'].append(dict(id='send', label=(f"Add {r['send']} there" if r['state'] == 'add' else f"Quantity {r['remote']} to {r['send']}"), note=None))
            row['default'] = row['default'] or 'send'
        elif r['state'] == 'change' and r.get('deletes_lot') and r['tickable']:      # Brick Owl: offered, never chosen for the person
            row['state'] = 'change'
            row['options'].append(dict(id='send', label=f"Quantity {r['remote']} to {r['send']}", note=_lot_note(r)))
        elif r.get('reason'):
            row['reason'] = r['reason']        # why the send side has nothing for this row; the row is not unmatched when it can still be pulled
    out = []
    for row in merged.values():
        if row['reason'] and not row['options'] and row['state'] == 'info':
            row['state'] = 'unmatched'
        if row['kept']:
            row['default'] = None
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
    """The Lost Parts section of the pull, narrowed to the sets picked, with its summary worked out again for them (None when Lost Parts do not
    come in). A set that only exists through a copy this pull would make is not offered when owned sets do not come in."""
    section = (plans['pull'] or {}).get('lost') or {}
    picked = picked_ids(run)
    d = run['directions']
    if d['lost'] not in ('into', 'both') or not section:
        return None
    coming = d['owned'] in ('into', 'both')
    sets, unmatched_sets = [], list(section.get('unmatched_sets', ()))
    for e in section.get('sets', ()):
        if picked is not None and e['item_id'] not in picked:
            continue
        if e['state'] == 'new' and not coming:
            unmatched_sets.append(dict(set_no=e['set_no'], parts=e['parts'], pieces=e['pieces'], reason='The set is not pulled in this run, so it has no copy to mark'))
            continue
        sets.append(e)
    summary = dict(section['summary'], sets=len(sets), added=0, replaced=0, cleared=0, cleared_pieces=0, pick=0,
                   unmatched=sum(u['parts'] for u in unmatched_sets))
    for e in sets:
        if e['state'] == 'pick':
            summary['pick'] += 1
        for name in ('added', 'replaced', 'cleared', 'cleared_pieces', 'unmatched'):
            summary[name] += (e.get('preview') or {}).get(name, 0)
    return dict(section, sets=sets, unmatched_sets=unmatched_sets, summary=summary)


def lost_out(run):
    """The Lost Parts send plan, narrowed to the sets picked (None when Lost Parts do not go out)."""
    section = None if lost_parts_send.SEND_LOCKED else run.get('lost_out')      # a run planned before the lock keeps its plan and sends nothing of it
    picked = picked_ids(run)
    if not section:
        return None
    return dict(section, rows=[r for r in section['rows'] if picked is None or r.get('item_id') in picked])


def part_rows(plans):
    return (plans['parts'] or {}).get('rows', [])


def budget(db, source=SOURCE):
    try:
        status = adapters.ADAPTERS[source](db).status()
        return dict(used=status['used_today'], budget=status['budget'], last_success=status['last_success'], key=status['key_state'])
    except Exception:
        return None


# Applying -------------------------------------------------------------------------------------------------------------

def _message(exc, source=SOURCE):
    label = sync.LABELS[source]
    if isinstance(exc, KeyRejected):
        return label + ' rejected the ' + sync.credential_words(source) + '. Nothing more was changed there.'
    if isinstance(exc, WaitingForBudget):
        return label + ' is paused: the daily budget is used up. Try again after ' + (exc.retry_at or 'midnight UTC')[:16].replace('T', ' ') + '.'
    if isinstance(exc, SourceError):
        return label + ' could not be reached. Nothing more was changed there.'
    return str(exc) or 'This step could not be done.'


def _checked(run_id):
    """A run id as `sync.load_plan` reads it (32 letters and digits), before any file is made for it."""
    if not isinstance(run_id, str) or len(run_id) != 32 or not run_id.isalnum() or not run_id.isascii():
        raise errors.ValidationFailed('Unknown sync plan')
    return run_id


class _Claim:
    """An exclusive lock on one run, across processes: a file next to its plan file. A second request for the same run waits here, then re-reads
    the run and finds the first one's marker. The lock files go with their plan files (`sync._save_plan`)."""

    def __init__(self, db, run_id):
        root = sync._root(db)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / (_checked(run_id) + '.lock')

    def __enter__(self):
        self.file = open(self.path, 'a')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX)
        except BaseException:
            self.file.close()
            raise
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.file, fcntl.LOCK_UN)
        finally:
            self.file.close()


def _getlist(form, key):
    if hasattr(form, 'getlist'):
        return form.getlist(key)
    value = form.get(key)
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def validate_choices(db, run, plans, form):
    """Validate the preview row choices as `apply` and `run_job.queue` require."""
    shown = rows(db, run, plans)
    allowed = {r['key']: {o['id'] for o in r['options']} for r in shown}
    chosen = {k: form.get('choice:' + k) or 'keep' for k, ids in allowed.items() if ids}
    if any(v != 'keep' and v not in allowed[k] for k, v in chosen.items()):
        raise errors.ValidationFailed('Choose one of the offered changes for each row')
    return chosen


def _extract_form(run, plans, form, chosen):
    """Freeze the preview MultiDict into the plain dict a durable run job also uses."""
    listed = lost_in(run, plans)
    lost = [s for s in _getlist(form, 'lost') if s in {e['set_no'] for e in listed['sets']}] if listed else None
    picks = {k.removeprefix('copy:'): v for k, v in form.items() if k.startswith('copy:') and v}
    if listed:
        picks = {k: v for k, v in picks.items() if k in {e['set_no'] for e in listed['sets']}}
        lost = sorted(set(lost or ()) | set(picks))        # choosing a copy for a set is ticking it
    else:
        picks = {}
    lines = {line['key']: line for line in ((plans['pull'] or {}).get('lists') or {}).get('preview', ())}
    lists = {k.removeprefix('list:'): v for k, v in form.items() if k.startswith('list:') and k.removeprefix('list:') in lines}
    part = [k for k in _getlist(form, 'part') if k in {r['key'] for r in part_rows(plans)}]
    lots = {k.removeprefix('lot:'): v for k, v in form.items() if k.startswith('lot:') and v and k.removeprefix('lot:') in part}
    section = lost_out(run)
    lostsend = [k for k in _getlist(form, 'lostsend') if k in {r['key'] for r in section['rows'] if r.get('tickable')}] if section else []
    return dict(chosen=chosen, lost=lost, copies=picks, lists=lists, part=part, lots=lots, lostsend=lostsend)


def apply(db, run_id, form, *, http=None, via=None, actor=None):
    """Apply the chosen rows, stage by stage. `form` is a MultiDict of the preview's fields: `choice:<row key>` (pull, take, send, remove, keep),
    `lost` and `copy:<set no>` (Lost Parts in), `list:<key>` (list names), `part` and `lot:<key>` (loose stock), `lostsend` (Lost Parts out).
    A stage that fails says so in the run, and the next one still runs. The run is claimed first (a lock, then `applying` written before the
    first call to Rebrickable), so a second request for it, at once or later, changes nothing and gets the run as it is. Returns the run, saved."""
    with _Claim(db, run_id):
        run, plans = load(db, run_id)
        if run.get('applied') or run.get('applying') or (run.get('job') and not run.get('applied')):
            return run
        chosen = validate_choices(db, run, plans, form)
        run['applying'] = now().isoformat()
        sync._store_plan(db, run)
        _stages(db, run, plans, form, chosen, http, via, actor)
        run['applied'] = dict(at=now().isoformat(), events=run['applied_events'])
        run.pop('applying', None)
        sync._store_plan(db, run)
        return run


def pull_wanted(form_data):
    """The preview rows the person chose to take into Brick Work."""
    return [k for k, v in form_data['chosen'].items() if v in ('pull', 'take')]


def kinds_in(ways):
    """The kinds of row ('owned', 'wanted') whose direction in `ways` (see `directions`) brings them into Brick Work (#531)."""
    return tuple(kind for kind, key in (('owned', 'owned'), ('wanted', 'wishlist')) if ways.get(key) in ('into', 'both'))


def marked_rows(db, run, plans):
    """How many rows here a run that takes nothing in would mark Last synced from (#531): the rows that already match, of the kinds that come
    in."""
    kinds = kinds_in(run.get('directions') or {})
    return sync.pull_marked_rows(db, plans['pull'], kinds) if plans['pull'] and kinds else 0


def stage_pull(db, run, plans, form_data, *, via=None, actor=None, raise_budget=False):
    """Run the pull stage (sets, wishes, Lost Parts in, list names) and store its outcome on `run`."""
    pull = plans['pull']
    if not pull:
        return None
    stages, source = run['stages'], run.get('source', SOURCE)
    wanted = pull_wanted(form_data)
    lost, picks, lists = form_data['lost'], form_data['copies'], form_data['lists']
    lines = {line['key']: line for line in (pull.get('lists') or {}).get('preview', ())}
    kept = [k for k, v in form_data['chosen'].items() if v == 'keep']       # the conflicts the person chose to Keep: remembered (#686)
    kept_covered, kept_skipped = keep_scope(run)
    changes = bool(wanted or lost or picks or any(v not in ('keep', 'skip') for v in lists.values()))
    only_marked = 0 if changes else marked_rows(db, run, plans)      # nothing to take in: what the pull will record is all it does
    if changes or only_marked:
        try:
            result = sync.apply_pull(db, pull['id'], wanted, lost=lost, picks=picks or None, lists=lists or None, kept=kept, kept_covered=kept_covered, kept_skipped=kept_skipped, incoming=kinds_in(run.get('directions') or {}), mark_only=not changes, via=via, actor=actor)
            effective = {k: lists.get(k, line['action']) for k, line in lines.items()}
            stages['pull'] = dict(status='done', event=result['event_id'], counts=result['counts'], rows=len(wanted),
                                  lists_changed=sum(1 for k, v in effective.items() if v in ('rename', 'drop') and lines[k]['sets']) if changes else 0, marked=only_marked)
        except WaitingForBudget as exc:
            stages['pull'] = dict(status='waiting' if raise_budget else 'failed', message=_message(exc, source))
            if raise_budget:
                sync._store_plan(db, run)
                raise
        except FAILURES as exc:
            stages['pull'] = dict(status='failed', message=_message(exc, source))
    else:
        stages['pull'] = dict(status='none')
    sync._store_plan(db, run)
    return stages['pull']


def stage_parts(db, run, plans, form_data, *, via=None, actor=None, raise_budget=False):
    """Run the part-list stage and store its outcome on `run`."""
    if not plans['parts']:
        return None
    stages = run['stages']
    wanted, lots = form_data['part'], form_data['lots']
    if wanted:
        try:
            result = part_lists.apply(db, plans['parts']['id'], wanted, lots=lots or None, via=via, actor=actor)
            stages['parts'] = dict(status='done', event=result['event_id'], counts=result['counts'], rows=len(wanted))
        except WaitingForBudget as exc:
            stages['parts'] = dict(status='waiting' if raise_budget else 'failed', message=_message(exc))
            if raise_budget:
                sync._store_plan(db, run)
                raise
        except FAILURES as exc:
            stages['parts'] = dict(status='failed', message=_message(exc))
    else:
        stages['parts'] = dict(status='none')
    sync._store_plan(db, run)
    return stages['parts']


def stage_send(db, run, plans, form_data, *, http=None, per_key=False, should_stop=None, on_call=None):
    """Run the send stage either as one call (`run.apply`) or one call per wanted key (`run_job`)."""
    if not plans['send']:
        return None
    stages, source = run['stages'], run.get('source', SOURCE)
    wanted = [k for k, v in form_data['chosen'].items() if v in ('send', 'remove')]
    if not wanted:
        stages['send'] = dict(status='none')
        sync._store_plan(db, run)
        return stages['send']
    if not per_key:
        try:
            result = sync.apply_send(db, plans['send']['id'], wanted, http=http)
            stages['send'] = dict(status='done', counts=result['counts'], rows=len(wanted), results=result['rows'])
        except FAILURES as exc:
            stages['send'] = dict(status='failed', message=_message(exc, source))
        sync._store_plan(db, run)
        return stages['send']

    plan_id = plans['send']['id']
    send_plan = sync.load_plan(db, plan_id, 'send')
    existing = send_plan.get('results') or {}
    went = ('sent', 'unchanged')
    if source == 'brickset':      # one call per set number, as `apply_send` makes it: a set's owned and wanted rows go together
        by_key = {r['key']: r for r in send_plan['rows']}
        grouped = {}
        for key in wanted:
            grouped.setdefault(by_key[key]['remote_no'], []).append(key)
        units = list(grouped.values())
    else:
        units = [[key] for key in wanted]
    done_count = sum(1 for k in wanted if existing.get(k, {}).get('result') in went)
    stopped, paused_retry_at, paused_exc, stopped_keys, failure = False, None, None, {}, None
    for idx, unit in enumerate(units):
        key = unit[0]
        later = [k for u in units[idx + 1:] for k in u]
        if all(existing.get(k, {}).get('result') in went for k in unit):
            continue
        if should_stop and should_stop():
            stopped = True
            for rem in [k for u in units[idx:] for k in u]:
                if existing.get(rem, {}).get('result') not in went:
                    stopped_keys[rem] = dict(result='stopped', detail='Stopped at your request')
            break
        if on_call:
            on_call('before', key, done_count)
        try:
            reply = sync.apply_send(db, plan_id, unit, http=http)
        except WaitingForBudget as exc:
            paused_exc = exc
            paused_retry_at = exc.retry_at
            send_plan = sync.load_plan(db, plan_id, 'send')
            res_map = send_plan.setdefault('results', {})
            for k in unit:
                res_map[k] = dict(result='paused', detail=_message(exc, source), retry_at=exc.retry_at)
            for rem in later:
                if res_map.get(rem, {}).get('result') not in went:
                    res_map[rem] = dict(result='paused', detail=None)
            sync._store_plan(db, send_plan)
            if on_call:
                on_call('paused', key, done_count, retry_at=paused_retry_at)
            break
        except FAILURES as exc:
            failure = _message(exc, source)
            break
        row_res = next((r for r in reply['rows'] if r['key'] in unit and r['result'] in ('paused', 'key_rejected')), None)
        if row_res:
            stop_kind = row_res['result']
            send_plan = sync.load_plan(db, plan_id, 'send')
            res_map = send_plan.setdefault('results', {})
            for rem in later:
                if res_map.get(rem, {}).get('result') not in went:
                    res_map[rem] = dict(result=stop_kind, detail=None)
            sync._store_plan(db, send_plan)
            if stop_kind == 'paused':
                paused_retry_at = row_res.get('retry_at')
                if on_call:
                    on_call('paused', key, done_count, retry_at=paused_retry_at)
            else:
                done_count = len(wanted)
                if on_call:
                    on_call('after', key, done_count)
            break
        done_count += len(unit)
        if on_call:
            on_call('after', key, done_count)

    res_map = sync.load_plan(db, plan_id, 'send').get('results') or {}
    agg_rows = []
    for key in wanted:
        if key in stopped_keys:
            agg_rows.append(dict(key=key, **stopped_keys[key]))
        elif key in res_map:
            agg_rows.append(dict(key=key, **res_map[key]))
        elif failure:
            agg_rows.append(dict(key=key, result='failed', detail=failure))
    counts = {}
    for row in agg_rows:
        counts[row['result']] = counts.get(row['result'], 0) + 1
    if failure:
        stages['send'] = dict(status='failed', message=failure, counts=counts, rows=len(wanted), results=agg_rows)
    elif counts.get('paused'):
        exc = paused_exc or WaitingForBudget(None, paused_retry_at)
        stages['send'] = dict(status='waiting', counts=counts, rows=len(wanted), results=agg_rows, message=_message(exc, source))
    elif stopped:
        stages['send'] = dict(status='stopped', counts=counts, rows=len(wanted), results=agg_rows)
    else:
        stages['send'] = dict(status='done', counts=counts, rows=len(wanted), results=agg_rows)
    sync._store_plan(db, run)
    return stages['send']


def stage_lost_out(db, run, form_data, *, http=None, per_key=False, should_stop=None, on_call=None):
    """Run the Lost Parts out stage either as one call (`run.apply`) or one call per wanted key (`run_job`)."""
    section = lost_out(run)
    if not section:
        return None
    stages = run['stages']
    wanted = form_data['lostsend']
    if not wanted:
        stages['lost_out'] = dict(status='none')
        sync._store_plan(db, run)
        return stages['lost_out']
    if not per_key:
        stages['lost_out'] = _apply_lost_out(db, run, wanted, http)
        sync._store_plan(db, run)
        return stages['lost_out']

    planned = run['lost_out']
    sent_keys = {r['key'] for r in planned['rows'] if r.get('outcome') == 'sent'}
    done_count = sum(1 for k in wanted if k in sent_keys)
    stopped, paused, paused_retry_at, key_rejected_msg, failed_msg, called = False, False, None, None, None, False
    for idx, key in enumerate(wanted):
        if key in sent_keys:
            continue
        if should_stop and should_stop():
            stopped = True
            break
        if on_call:
            on_call('before', key, done_count)
        called = True
        result, meta = _lost_out_calls(db, run, [key], http)
        if result['status'] == 'failed':
            if meta['retry_at'] is not None or meta['budget_error']:
                paused = True
                paused_retry_at = meta['retry_at']
                for row in planned['rows']:
                    if row['key'] in set(wanted[idx:]) and row.get('outcome') != 'sent':
                        row['outcome'] = 'waiting'
                if on_call:
                    on_call('paused', key, done_count, retry_at=paused_retry_at)
            else:
                failed_msg = result['message']
            break
        if meta['key_rejected']:
            key_rejected_msg = result['message']
            for row in planned['rows']:
                if row['key'] in set(wanted[idx + 1:]) and row.get('outcome') != 'sent':
                    row['outcome'] = 'failed'
                    row['reason'] = ' '.join(filter(None, (key_rejected_msg, row.get('gone'))))      # gone from an earlier pass
            done_count = len(wanted)
            if on_call:
                on_call('after', key, done_count)
            break
        if result['counts']['waiting']:
            paused = True
            paused_retry_at = meta['retry_at']
            for row in planned['rows']:
                if row['key'] in set(wanted[idx + 1:]) and row.get('outcome') != 'sent':
                    row['outcome'] = 'waiting'
            if on_call:
                on_call('paused', key, done_count, retry_at=paused_retry_at)
            break
        done_count += 1
        if on_call:
            on_call('after', key, done_count)

    if failed_msg and not called:
        stages['lost_out'] = dict(status='failed', message=failed_msg)
    elif failed_msg and not any(r.get('outcome') in ('sent', 'failed', 'waiting') for r in planned['rows'] if r['key'] in set(wanted)):
        stages['lost_out'] = dict(status='failed', message=failed_msg)
    else:
        by_key = {r['key']: r for r in planned['rows'] if r['key'] in set(wanted)}
        sent_rows = [by_key[k] for k in wanted if by_key.get(k, {}).get('outcome') == 'sent']
        failed_rows = [by_key[k] for k in wanted if by_key.get(k, {}).get('outcome') == 'failed']
        waiting_rows = [by_key[k] for k in wanted if by_key.get(k, {}).get('outcome') == 'waiting']
        counts = dict(sent=len(sent_rows), failed=len(failed_rows), waiting=len(waiting_rows))
        message = key_rejected_msg
        if counts['waiting'] and not message:
            message = _paused_message(counts['waiting'], [*failed_rows, *waiting_rows])
        if stopped and not message:
            message = 'Stopped at your request'
        if called or any(counts.values()):
            _audit_lost_out(db, run, counts)
        status = 'waiting' if paused else 'stopped' if stopped else 'done' if not counts['failed'] else 'partial'
        stages['lost_out'] = dict(status=status, counts=counts, message=message, unsaved=bool(run.get('progress_unsaved')),
                                      failed=[dict(key=r['key'], set_no=r['set_no'], part_no=r['part_no'], reason=r.get('reason')) for r in failed_rows])
    sync._store_plan(db, run)
    return stages['lost_out']


def keep_scope(run):
    """What the run's preview covers, for the Keep memory (#686): the kinds whose direction is not Off, and the sets it skips (the ones it could
    touch that were not picked)."""
    d, picked = run['directions'], picked_ids(run)
    skipped = set() if picked is None else {c['item_id'] for c in run['candidates']} - picked
    return tuple(kind for kind, direction in (('owned', 'owned'), ('wanted', 'wishlist')) if d[direction] != 'off'), skipped


def remember_choices(db, run, plans, form_data):
    """The conflicts the person chose to Keep are remembered (#686) before any stage runs, so a stage with nothing to do (or one that fails) cannot
    lose them. The pairs are the counts of the preview rows the person saw, for the kinds the run shows. Not fatal: a Keep that could not be
    written is only forgotten."""
    if not (plans['pull'] or plans['send']):
        return
    covered, skipped = keep_scope(run)
    try:
        sync.remember_kept(db, run.get('source', SOURCE), rows(db, run, plans), [k for k, v in form_data['chosen'].items() if v == 'keep'], covered, skipped)
    except FAILURES as exc:
        LOG.warning('The Keep choices of a run could not be written: %s', type(exc).__name__)


def _stages(db, run, plans, form, chosen, http, via, actor):
    form_data = _extract_form(run, plans, form, chosen)
    remember_choices(db, run, plans, form_data)
    stage_pull(db, run, plans, form_data, via=via, actor=actor)
    stage_parts(db, run, plans, form_data, via=via, actor=actor)
    stage_send(db, run, plans, form_data, http=http)
    stage_lost_out(db, run, form_data, http=http)
    events = [run['stages'][s]['event'] for s in ('pull', 'parts') if (run['stages'].get(s) or {}).get('event') is not None]
    source = run.get('source', SOURCE)
    with transaction(db):
        audit(db, 'sync:' + source, 'run', None, dict(run=run['id'], events=events), via=via, actor=actor)
    run['applied_events'] = events


class _Recorder:
    """The client of a Lost Parts send, writing each call to Rebrickable into the run as soon as it has gone through. `lost_parts_send.apply`
    keeps no progress of its own and has no hook per row, so the run learns of a sent row from the call, not from the apply's reply."""

    def __init__(self, client, db, run):
        self.client, self.db, self.run = client, db, run
        self.retry_at = None

    def _note(self, entry):
        self.run.setdefault('lost_calls', []).append(entry)
        try:
            sync._store_plan(self.db, self.run)
        except Exception as exc:       # the call went through: a local write failure must not stop the send or lose its result
            LOG.warning('Lost Parts progress could not be written to the run: %s', type(exc).__name__)
            self.run['progress_unsaved'] = True

    def lost_part_add(self, inv_part_id, quantity):
        try:
            reply = self.client.lost_part_add(inv_part_id, quantity)
        except WaitingForBudget as exc:
            self.retry_at = exc.retry_at
            raise
        self._note(['add', inv_part_id, quantity])
        return reply

    def lost_part_remove(self, lost_part_id):
        try:
            reply = self.client.lost_part_remove(lost_part_id)
        except WaitingForBudget as exc:
            self.retry_at = exc.retry_at
            raise
        self._note(['remove', lost_part_id])
        return reply

    def __getattr__(self, name):
        return getattr(self.client, name)


def _paused_message(waiting, rows):
    """The budget pause of a Lost Parts send. Every row of `rows` whose old entry is gone is named, waiting or already failed: a stopped
    run never sends the new count."""
    text = 'Rebrickable is paused: the daily budget is used up. ' + ('1 Lost Part waits.' if waiting == 1 else f'{waiting} Lost Parts wait.')
    return ' '.join([text, *(r['gone'] for r in rows if r.get('gone'))])


def _lost_out_calls(db, run, wanted, http):
    """Run Lost Parts out calls for `wanted` and update `run['lost_out']` without writing the stage audit."""
    planned = run['lost_out']
    message, key_rejected = None, False
    recorder = _Recorder(adapters.adapter(db, SOURCE, http), db, run)
    try:
        reply = lost_parts_send.apply(db, recorder, planned, wanted)
    except KeyRejected as exc:
        reply = dict(getattr(exc, 'partial', dict(sent=[], failed=[], remaining=[])))
        message = _message(exc)
        key_rejected = True
        reply['failed'] = list(reply['failed']) + [dict(r, reason=' '.join(filter(None, (message, r.get('gone'))))) for r in reply['remaining']]     # refused, not paused: what was not tried failed
        reply['remaining'] = []
    except WaitingForBudget as exc:
        return dict(status='failed', message=_message(exc)), dict(retry_at=exc.retry_at, key_rejected=False, budget_error=True)
    except (SourceError, ValueError) as exc:
        return dict(status='failed', message=_message(exc)), dict(retry_at=None, key_rejected=False, budget_error=False)
    for part in ('sent', 'failed', 'remaining'):
        for row in reply[part]:
            for i, old in enumerate(planned['rows']):
                if old['key'] == row['key']:
                    planned['rows'][i] = dict(row, outcome='sent' if part == 'sent' else 'failed' if part == 'failed' else 'waiting')
    counts = dict(sent=len(reply['sent']), failed=len(reply['failed']), waiting=len(reply['remaining']))
    if counts['waiting'] and not message:
        message = _paused_message(counts['waiting'], [*reply['failed'], *reply['remaining']])
    try:
        sync._store_plan(db, run)      # what Rebrickable took is written down before anything else can fail
    except OSError as exc:
        LOG.warning('Lost Parts progress could not be written to the run: %s', type(exc).__name__)
        run['progress_unsaved'] = True
    result = dict(status='done' if not (counts['failed'] or counts['waiting']) else 'partial', counts=counts, message=message, unsaved=bool(run.get('progress_unsaved')),
                  failed=[dict(key=r['key'], set_no=r['set_no'], part_no=r['part_no'], reason=r.get('reason')) for r in reply['failed']])
    return result, dict(retry_at=recorder.retry_at, key_rejected=key_rejected, budget_error=False)


def _audit_lost_out(db, run, counts):
    with transaction(db):
        audit(db, 'sync:' + SOURCE, 'send', None, dict(plan=run['id'], kind='lost_parts', counts={k: v for k, v in dict(sent=counts['sent'], failed=counts['failed'], paused=counts['waiting']).items() if v}))


def _apply_lost_out(db, run, wanted, http):
    result, _ = _lost_out_calls(db, run, wanted, http)
    if 'counts' in result:
        _audit_lost_out(db, run, result['counts'])
    return result


def pull_events(run):
    """The pull events of a run (the pull and the part-list pull), the ones its Undo takes back."""
    return [run['stages'][s]['event'] for s in ('pull', 'parts') if (run['stages'].get(s) or {}).get('event') is not None]


def undo_run(db, event_id):
    """Undo a pull and the part-list pull of the same run in one step (the run is found by either event). Raises UndoBlocked, and undoes
    nothing, when something it wrote changed since."""
    from .. import undo as undoing
    ids = [event_id]
    for row in db.execute("SELECT new_value FROM event WHERE entity_kind='sync' AND field='run' ORDER BY id DESC"):      # no limit: an older run must not be undone by half
        events = (json.loads(row['new_value']) or {}).get('events', []) if row['new_value'] else []
        if event_id in events:
            ids = list(events)
            break
    with transaction(db):
        for e in reversed(ids):
            undoing.undo_event(db, e)
    return ids


def _job_send_done(db, run):
    """Send again sent what the job could not: its send step is done, and the job keeps no error unless another stage still failed, in
    whole or in part."""
    job_id = run['job']
    left = any(st.get('status') in ('failed', 'partial') or (st.get('counts') or {}).get('key_rejected') for st in run['stages'].values())
    with transaction(db):
        db.execute("UPDATE job_step SET state='done', count=total, error=NULL, error_code=NULL, retry_at=NULL WHERE job_id=? AND name='send'", (job_id,))
        if not left:
            db.execute("UPDATE job SET error=NULL, error_code=NULL WHERE id=? AND state='done'", (job_id,))


def retry_send(db, run_id, *, http=None, also=()):
    """Send again the rows of the run's send stage that did not go through (failed, paused or refused). The send plan keeps what was sent. Under
    the run's lock, so two requests do not send the same row twice: the second finds nothing left to retry. A row whose result is `unknown` (a send a
    restart cut off: it may have gone out) is sent again only when its key is in `also`; by default it is left."""
    with _Claim(db, run_id):
        run, plans = load(db, run_id)
        send = plans['send']
        stage = (run.get('stages') or {}).get('send')
        if run.get('job') and not run.get('applied'):
            raise errors.ValidationFailed('This run is still running')
        if not send or not stage or not stage.get('results'):
            raise errors.ValidationFailed('This run sent nothing that can be retried')
        again = [r['key'] for r in stage['results'] if r['result'] not in ('sent', 'unchanged') and (r['result'] != 'unknown' or r['key'] in set(also))]
        if not again:
            if any(r['result'] == 'unknown' for r in stage['results']):
                raise errors.ValidationFailed('Only a row that may have gone out is left. Check it, then choose Send it too on that row')
            if run.get('job'):
                _job_send_done(db, run)      # an earlier Send again may have stored the run and then failed to write the job
            raise errors.ValidationFailed('Everything this run sent went through')
        result = sync.apply_send(db, send['id'], again, http=http)
        kept_unknown = [r for r in stage['results'] if r['result'] == 'unknown' and r['key'] not in again]    # a row left out stays as it was, whatever the send plan says of it
        left_keys = {r['key'] for r in kept_unknown}
        rows = [r for r in result['rows'] if r['key'] not in left_keys] + kept_unknown
        counts = {}
        for r in rows:
            counts[r['result']] = counts.get(r['result'], 0) + 1
        left = len(kept_unknown)
        if left:     # a row that may have gone out is still unchecked: the run stays interrupted, here and in the sync log
            run['stages']['send'] = dict(status='failed', message=INTERRUPTED_MESSAGE, counts=counts, rows=len(rows), results=rows,
                                         **({'cause': stage['cause']} if stage.get('cause') else {}))      # what cut it off stays on the card
            with transaction(db):
                audit(db, 'sync:' + run.get('source', SOURCE), 'send', None, dict(plan=send['id'], counts=counts, interrupted=True, run=run_id, pulls=pull_events(run)))
        else:
            run['stages']['send'] = dict(status='done', counts=counts, rows=len(rows), results=rows)
        sync._store_plan(db, run)      # the run first: if this fails, the job must not say more than the run does
        if run.get('job') and all(r['result'] in ('sent', 'unchanged') for r in run['stages']['send']['results']):
            _job_send_done(db, run)
        return run
