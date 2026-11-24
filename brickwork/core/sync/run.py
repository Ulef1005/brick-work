"""One Rebrickable or Brickset run (#519, #520): the choices of step 2, the plans a run reads, the merged preview and the stages it applies.

A run is not new sync logic. It reads the plans that already exist (`sync.plan_pull` with its Lost Parts and list-name sections,
`sync.plan_send`, `part_lists.plan`, `lost_parts_send.plan`), merges their rows into one row per set with the choices that row has, and
applies the chosen rows through the same applies, one stage after the other: the pull (sets, wishes, Lost Parts in, list names), the part
lists, the sends, the Lost Parts out. The run record is a plan file (`direction='run'`, 24 hours like every plan); it keeps the ids of the
plans it read, the sets picked, and what each stage did, because `lost_parts_send.apply` keeps no progress of its own.

A run takes its site from its own record (`run['source']`); every other function takes `source`, Rebrickable when left out. Brickset has
owned and wanted sets with counts only: no lists, part lists or Lost Parts, so those stages never run for it.

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

SOURCE = 'rebrickable'
SOURCES = ('rebrickable', 'brickset')
DIRECTIONS_KEY = 'rebrickable_sync_directions'
DIRECTIONS_KEYS = {'rebrickable': DIRECTIONS_KEY, 'brickset': 'brickset_sync_directions'}
SEGMENTS = {'owned': ('into', 'both', 'to', 'off'), 'wishlist': ('into', 'both', 'to', 'off'), 'parts': ('into', 'off'), 'lost': ('into', 'both', 'to', 'off')}
SEGMENT_LABELS = {'into': 'Into Brick Work', 'both': 'Both ways', 'to': 'To Rebrickable', 'off': 'Off'}
SEGMENT_LABELS_BY = {'rebrickable': SEGMENT_LABELS, 'brickset': dict(SEGMENT_LABELS, to='To Brickset')}
MODE_LABELS = (('all', 'All linked'), ('list', 'By list'), ('theme', 'By theme'), ('year', 'By year'), ('one', 'One by one'))
MODES = tuple(m for m, _ in MODE_LABELS)
MODE_LABELS_BY = {'rebrickable': MODE_LABELS, 'brickset': tuple(m for m in MODE_LABELS if m[0] != 'list')}      # Brickset has no lists to pick by
KINDS_BY = {'rebrickable': tuple(SEGMENTS), 'brickset': ('owned', 'wishlist')}       # the kinds of data each site has a direction for
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
    if source == 'brickset':       # owned and wanted sets only: loose stock and Lost Parts are Rebrickable's
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
    if source == 'brickset':
        return _save_brickset_choices(db, form)
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


def _save_brickset_choices(db, form):
    """Step 2 of the Brickset page: `owned_dir`, `wishlist_dir` and `wish_list` (the Brick Work wishlist that takes the wanted sets). One transaction."""
    for kind in KINDS_BY['brickset']:
        if form.get(kind + '_dir') not in SEGMENTS[kind]:
            raise errors.ValidationFailed('Choose a direction for ' + kind)
    with transaction(db):
        before = dict(directions=_setting_row(db, DIRECTIONS_KEYS['brickset']))
        sync.link(db, 'brickset', dict(wish_list=form.get('wish_list') or 'default'))
        saved = json.dumps({k: form[k + '_dir'] for k in KINDS_BY['brickset']}, sort_keys=True)
        _put_setting(db, DIRECTIONS_KEYS['brickset'], saved)
        audit(db, 'sync:brickset', 'choices', before, dict(directions=saved))
    return directions(db, 'brickset')


def _saved_names(db):
    try:
        return json.loads(_setting_row(db, DIRECTIONS_KEY) or '{}').get('names') or {}
    except ValueError:
        return {}


def lost_labels(db):
    """The two Lost Parts rules as the page names them: `(pull rule label, send rule label)`."""
    return lost_parts.RULE_LABELS[lost_parts.rule(db)], dict((v, l) for v, l, _ in lost_parts_send.RULES)[lost_parts_send.send_rule(db)]


def _brickset_what_syncs(db):
    link = link_value(db, 'brickset')
    d = directions(db, 'brickset')
    labels = SEGMENT_LABELS_BY['brickset']
    wish_lists = {w['id']: w['name'] for w in wishlists.listing(db)}
    rows = []
    if d['owned'] != 'off':
        rows.append(dict(what='Owned sets', direction=labels[d['owned']], linked='Quantity owned'))
    if d['wishlist'] != 'off':
        rows.append(dict(what='Wanted sets', direction=labels[d['wishlist']],
                         linked='Wanted, as a flag, ↔ wishlist ' + wish_lists.get(link.get('wish_list') or 'default', 'Wanted')))
    return rows


def what_syncs(db, source=SOURCE):
    """The rows of the What syncs table of the page at rest, from what is stored: no call to the site."""
    if source == 'brickset':
        return _brickset_what_syncs(db)
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
    sets_out = d['owned'] in ('to', 'both') or d['wishlist'] in ('to', 'both')
    lost_in_on = d['lost'] in ('into', 'both')
    pull = (sync.plan_pull(db, source, http=http, lost_parts_switch=lost_in_on) if source == 'rebrickable' else sync.plan_pull(db, source, http=http)) if (sets_in or lost_in_on) else None
    send = sync.plan_send(db, source, http=http) if sets_out else None
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


def _presence_only(source, r):
    """Brickset holds a wanted set as a flag, so a wish of 2 here against 1 there is not a difference; Rebrickable keeps quantities."""
    return source == 'brickset' and r['kind'] == 'wanted' and bool(r['here']) == bool(r['remote'])


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
            if d['owned' if r['kind'] == 'owned' else 'wishlist'] in ways and not _presence_only(source, r):    # a kind that is Off in this direction is not a set this run touches
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
        if run.get('applied') or run.get('applying'):
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
                                                kept=(r.get('baseline_remote') or 0) == r['remote'] and (r.get('baseline_here') or 0) == r['here'] and r['remote'] != r['here']))
    for r in (plans['pull'] or {}).get('rows', ()):
        if picked is not None and r['item_id'] not in picked:
            continue
        if d['owned' if r['kind'] == 'owned' else 'wishlist'] not in ('into', 'both') or _presence_only(source, r):
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
        if d['owned' if r['kind'] == 'owned' else 'wishlist'] not in ('to', 'both') or _presence_only(source, r):
            continue
        row = row_of(r)
        if r['state'] == 'conflict':
            row['state'] = 'conflict'
            if r['tickable']:
                row['options'].append(dict(id='send', label=f"Send {r['send']} to {site}", note=f"{site} becomes {r['send']}"))
        elif r['state'] in ('remove', 'change') and r['tickable'] and any(o['id'] == 'pull' for o in row['options']):
            # Rebrickable has more than here: a lower count there is offered only when this set was lowered here since the last run
            if (r.get('baseline_here') or 0) > r['here'] and r.get('baseline_remote') is not None:
                row['state'] = 'gone'
                row['options'].append(dict(id='remove' if r['state'] == 'remove' else 'send',
                                           label=f'Remove from {site}' if r['state'] == 'remove' else f"Quantity {r['remote']} to {r['send']}",
                                           note='Takes the set off the list there' if r['state'] == 'remove' else None))
        elif r['state'] == 'remove' and r['tickable']:        # only sending: a set taken off the list here is offered for the list there, unticked
            row['state'] = 'remove'
            row['options'].append(dict(id='remove', label=f'Remove from {site}', note=None))
        elif r['state'] in ('add', 'change') and r['tickable'] and r['action']:
            row['state'] = 'send_add' if r['state'] == 'add' else 'change'
            row['options'].append(dict(id='send', label=(f"Add {r['send']} there" if r['state'] == 'add' else f"Quantity {r['remote']} to {r['send']}"), note=None))
            row['default'] = row['default'] or 'send'
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
    section = run.get('lost_out')
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
        return label + ' rejected the key or user token. Nothing more was changed there.'
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


def apply(db, run_id, form, *, http=None, via=None, actor=None):
    """Apply the chosen rows, stage by stage. `form` is a MultiDict of the preview's fields: `choice:<row key>` (pull, take, send, remove, keep),
    `lost` and `copy:<set no>` (Lost Parts in), `list:<key>` (list names), `part` and `lot:<key>` (loose stock), `lostsend` (Lost Parts out).
    A stage that fails says so in the run, and the next one still runs. The run is claimed first (a lock, then `applying` written before the
    first call to Rebrickable), so a second request for it, at once or later, changes nothing and gets the run as it is. Returns the run, saved."""
    with _Claim(db, run_id):
        run, plans = load(db, run_id)
        if run.get('applied') or run.get('applying'):
            return run
        shown = rows(db, run, plans)
        allowed = {r['key']: {o['id'] for o in r['options']} for r in shown}
        chosen = {k: form.get('choice:' + k) or 'keep' for k, ids in allowed.items() if ids}
        if any(v != 'keep' and v not in allowed[k] for k, v in chosen.items()):
            raise errors.ValidationFailed('Choose one of the offered changes for each row')
        run['applying'] = now().isoformat()
        sync._store_plan(db, run)
        _stages(db, run, plans, form, chosen, http, via, actor)
        run['applied'] = dict(at=now().isoformat(), events=run['applied_events'])
        run.pop('applying', None)
        sync._store_plan(db, run)
        return run


def _stages(db, run, plans, form, chosen, http, via, actor):
    stages, events = run['stages'], []
    source = run.get('source', SOURCE)
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
                effective = {k: lists.get(k, line['action']) for k, line in lines.items()}
                stages['pull'] = dict(status='done', event=result['event_id'], counts=result['counts'], rows=len(wanted),
                                      lists_changed=sum(1 for k, v in effective.items() if v in ('rename', 'drop') and lines[k]['sets']))   # distinct lists, as the preview names them
                events.append(result['event_id'])
            except FAILURES as exc:
                stages['pull'] = dict(status='failed', message=_message(exc, source))
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
                stages['send'] = dict(status='failed', message=_message(exc, source))
        else:
            stages['send'] = dict(status='none')
        sync._store_plan(db, run)
    section = lost_out(run)
    if section:
        wanted = [k for k in form.getlist('lostsend') if k in {r['key'] for r in section['rows'] if r.get('tickable')}]
        stages['lost_out'] = _apply_lost_out(db, run, wanted, http) if wanted else dict(status='none')
        sync._store_plan(db, run)
    with transaction(db):
        audit(db, 'sync:' + source, 'run', None, dict(run=run['id'], events=events), via=via, actor=actor)
    run['applied_events'] = events


class _Recorder:
    """The client of a Lost Parts send, writing each call to Rebrickable into the run as soon as it has gone through. `lost_parts_send.apply`
    keeps no progress of its own and has no hook per row, so the run learns of a sent row from the call, not from the apply's reply."""

    def __init__(self, client, db, run):
        self.client, self.db, self.run = client, db, run

    def _note(self, entry):
        self.run.setdefault('lost_calls', []).append(entry)
        try:
            sync._store_plan(self.db, self.run)
        except Exception as exc:       # the call went through: a local write failure must not stop the send or lose its result
            LOG.warning('Lost Parts progress could not be written to the run: %s', type(exc).__name__)
            self.run['progress_unsaved'] = True

    def lost_part_add(self, inv_part_id, quantity):
        reply = self.client.lost_part_add(inv_part_id, quantity)
        self._note(['add', inv_part_id, quantity])
        return reply

    def lost_part_remove(self, lost_part_id):
        reply = self.client.lost_part_remove(lost_part_id)
        self._note(['remove', lost_part_id])
        return reply

    def __getattr__(self, name):
        return getattr(self.client, name)


def _apply_lost_out(db, run, wanted, http):
    planned = run['lost_out']
    message = None
    try:
        reply = lost_parts_send.apply(db, _Recorder(adapters.adapter(db, SOURCE, http), db, run), planned, wanted)
    except KeyRejected as exc:
        reply = dict(getattr(exc, 'partial', dict(sent=[], failed=[], remaining=[])))
        message = _message(exc)
        reply['failed'] = list(reply['failed']) + [dict(r, reason=message) for r in reply['remaining']]     # refused, not paused: what was not tried failed
        reply['remaining'] = []
    except (SourceError, ValueError) as exc:
        return dict(status='failed', message=_message(exc))
    for part in ('sent', 'failed', 'remaining'):
        for row in reply[part]:
            for i, old in enumerate(planned['rows']):
                if old['key'] == row['key']:
                    planned['rows'][i] = dict(row, outcome='sent' if part == 'sent' else 'failed' if part == 'failed' else 'waiting')
    counts = dict(sent=len(reply['sent']), failed=len(reply['failed']), waiting=len(reply['remaining']))
    if counts['waiting'] and not message:
        message = 'Rebrickable is paused: the daily budget is used up. ' + ('1 Lost Part waits.' if counts['waiting'] == 1 else f"{counts['waiting']} Lost Parts wait.")
    try:
        sync._store_plan(db, run)      # what Rebrickable took is written down before anything else can fail
    except OSError as exc:
        LOG.warning('Lost Parts progress could not be written to the run: %s', type(exc).__name__)
        run['progress_unsaved'] = True
    with transaction(db):
        audit(db, 'sync:' + SOURCE, 'send', None, dict(plan=run['id'], kind='lost_parts', counts={k: v for k, v in dict(sent=counts['sent'], failed=counts['failed'], paused=counts['waiting']).items() if v}))
    return dict(status='done' if not (counts['failed'] or counts['waiting']) else 'partial', counts=counts, message=message, unsaved=bool(run.get('progress_unsaved')),
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
    """Send again the rows of the run's send stage that did not go through (failed, paused or refused). The send plan keeps what was sent. Under
    the run's lock, so two requests do not send the same row twice: the second finds nothing left to retry."""
    with _Claim(db, run_id):
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
