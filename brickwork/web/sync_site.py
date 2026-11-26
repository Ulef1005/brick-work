"""The Rebrickable and Brickset sync pages and their six steps (#519, #520): connect, choose what, pick sets, preview, run, result.

The views only read and write through `core.sync` and `core.sync.run`; the plans, the applies and the choices are theirs. The run record is a plan
file (24 hours), so the pick, preview, run and result pages take its id in the path. One view body serves both sites: each step is registered
under `/workbench/sync/<site>/...` and the endpoints `web.bw_sync_rb_<step>` and `web.bw_sync_bs_<step>`, and the site is the view's `source`."""
import json
import re
import sqlite3

from flask import abort, flash, redirect, request, url_for
from flask_login import login_required

from .safe_errors import public
from .views import web_page, bw_add_csrf, bw_collection_editable
from .sync_views import _db, _event_id, _log, _message, _page, _receipt_source, _unavailable, lost_result

SOURCE = 'rebrickable'
PREFIX = {'rebrickable': 'rb', 'brickset': 'bs'}
LABEL = {'rebrickable': 'Rebrickable', 'brickset': 'Brickset'}
TEMPLATE = 'web/toni/web/bw_sync_rb.html'
STEPS = ('Connect', 'Choose what', 'Pick sets', 'Preview', 'Run', 'Result')
KEY_FIELD = 'key:key'
# A local write failure: the database (sqlite3.Error) or a file (OSError), but never what the source layer reports (SourceError, BrickWorkError).
LOCAL = (sqlite3.Error, OSError)
UNSAVED = ('Brick Work could not write down this run: the data folder may be full or read-only. What Rebrickable already took stays there; '
           'check the sync log and Rebrickable before you start a new run.')
STEPS_LIST = []


def _to(source, step, **values):
    """The URL of one step of a site's page."""
    return url_for(f'web.bw_sync_{PREFIX[source]}_{step}', **values)


def _unsaved(source):
    return UNSAVED.replace('Rebrickable', LABEL[source])


def _route(method, path, unavailable):
    """Register a step for both sites: login first, the not-available notice for a page that reads (before setup there is no database)."""
    def register(view):
        STEPS_LIST.append((method, path, unavailable, view))
        return view
    return register


def _render(source, **context):
    return _page(TEMPLATE, source=source, label=LABEL[source], pre=PREFIX[source], **context)


def _guard():
    """The checks every write of the sync pages makes: same origin, the form's token, and a collection that can change."""
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') != request.host_url.rstrip('/') or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)
    bw_add_csrf(request.form)
    if not bw_collection_editable():
        abort(403, 'Changes are switched off on this instance')


def _steps(current):
    return dict(steps=STEPS, step=current)


def _day(value):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).strftime('%d %b').lstrip('0')
    except ValueError:
        return None


def _key_checked_day(key, last_success):
    """The day the key last worked (#686): the newest successful call of the source, shown only when it is not older than the key's save time,
    so a replaced key does not inherit the old key's day. None when there is no call yet."""
    from datetime import datetime, timezone

    def moment(value):
        try:
            when = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return None
        return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    seen, saved_at = moment(last_success), (key or {}).get('saved_at')
    saved = moment(saved_at) if saved_at else None
    if seen is None or (saved_at and (saved is None or seen < saved)):        # a save time that cannot be read hides the day, never shows an old key's
        return None
    return _day(last_success)


def _runs(db, source):
    """The last runs for the page at rest, newest first, from the sync log; Undo only on the newest pull that was not undone. An interrupted run
    stays listed, with the rows of its pull, while that pull is not undone and is among the site's newest 200 log rows."""
    found = _log(db, limit=200, source=source)
    live = {r['event'] for r in found if r['direction'] == 'Pulled' and r['state'] == 'Done'}
    kept = {e for r in found if r['state'] == 'Interrupted' for e in r.get('pulls', ()) if e in live}
    rows = [r for i, r in enumerate(found) if i < 5 or r.get('event') in kept or (r['state'] == 'Interrupted' and kept.intersection(r.get('pulls', ())))]
    undo = next((r['id'] for r in found if r['direction'] == 'Pulled' and r['state'] == 'Done' and r.get('event')), None)
    return [dict(r, undoable=r['id'] == undo, retry=r['direction'] == 'Sent' and r['state'] not in ('Done', 'Interrupted') and not r.get('lost'), title=('Undo' if r['direction'] == 'Undone' else 'Run')) for r in rows]


def site_page(source):
    """Frames 18 and 25: the account, the last runs and what syncs, from what is stored (no call to the site)."""
    from ..core import sync
    from ..core.sync import run as sync_run
    from .setup_state import key_missing
    with _db() as db:
        status = sync.status(db, source)
        connected = bool(status['credentials']['user']['configured'])
        key_gap = key_missing(source)
        budget = sync_run.budget(db, source)
        what = sync_run.what_syncs(db, source)
        runs = _runs(db, source)
        pulled = request.args.get('pulled', '')
        if _receipt_source(db, pulled) != source:
            pulled = ''
        result = lost_result(db, pulled)
        from ..core.sync import lost_parts
    last = status.get('last_pull') or status.get('last_send')
    stamps = [t for t in ((status.get('last_pull') or {}).get('at'), (status.get('last_send') or {}).get('at')) if t]
    from .sync_views import _last_sync
    return _render(source, screen='site', title=LABEL[source], subtitle='Last run ' + _last_sync(status) if last else 'Not run yet',
                 connected=connected, account=status.get('account'), key_gap=key_gap, key=status['credentials']['key'], budget=budget, what=what, runs=runs,
                 waiting=status.get('waiting') or 0, pulled=pulled, lost_result=result, rule_labels=lost_parts.RULE_LABELS, stamps=stamps,
                 key_day=_key_checked_day(status['credentials']['key'], (budget or {}).get('last_success')))


@_route('get', '/connect', True)
def step_connect(source):
    from ..core import sync
    from .setup_state import key_missing
    with _db() as db:
        status = sync.status(db, source)
    return _render(source, screen='connect', title=LABEL[source], subtitle='Connect your account, choose what to sync, then run the sync.',
                 connected=bool(status['credentials']['user']['configured']), account=status.get('account'), key_gap=key_missing(source), key=status['credentials']['key'],
                 **_steps(1))


@_route('post', '/key', False)
def step_key(source):
    """Save, test or remove the site's API key from step 1: the same operations as Catalogues & keys, which stays their one implementation."""
    from ..core import errors
    from ..core.sources.base import KeyRejected, SourceError, redact
    from . import admin_ops
    _guard()
    action = request.form.get('action')
    try:
        if action == 'save':
            outcome = admin_ops.tools_write('key_test_save', source=source, values={'key': request.form.get(KEY_FIELD, '')})
            flash('Saved · The key works' if outcome['tested'] else 'Saved · Not tested: ' + outcome['reason'], 'success')
        elif action == 'test':
            admin_ops.tools_write('key_test', source=source)
            flash(LABEL[source] + ' accepted the API key.', 'success')
        elif action == 'remove':
            admin_ops.tools_write('key_remove', source=source)
            flash('Removed the stored API key.', 'success')
        else:
            abort(400)
    except KeyRejected as exc:
        flash(LABEL[source] + ' rejected the key · ' + redact(exc), 'warning')
    except (errors.BrickWorkError, SourceError) as exc:
        flash(redact(exc), 'warning')
    return redirect(_to(source, 'connect'))


def _lists(db):
    """Rebrickable: the set lists and the part lists of the account, each with the reason it could not be read (None when it could): `(sets, sets_error, parts, parts_error)`."""
    from ..core import sync
    from ..core.sync import adapters
    from ..core.sources.base import SourceError
    sets, parts, sets_error, parts_error = [], [], None, None
    try:
        sets = sync.lists(db, SOURCE)
    except (SourceError, ValueError, sqlite3.Error) as exc:
        sets_error = _message(exc, SOURCE)
    try:
        parts = adapters.adapter(db, SOURCE).part_lists()
    except (SourceError, ValueError, sqlite3.Error) as exc:
        parts_error = _message(exc, SOURCE)
    return sets, sets_error, parts, parts_error


@_route('get', '/choose', True)
def step_choose(source):
    from ..core import sync, wishlists
    from ..core.sync import lost_parts, lost_parts_send
    from ..core.sync import run as sync_run
    with _db() as db:
        status = sync.status(db, source)
        if not status['credentials']['user']['configured']:
            flash('Connect your ' + LABEL[source] + ' account first.', 'warning')
            return redirect(_to(source, 'connect'))
        if source == 'brickset':       # owned and wanted sets with counts: two directions and the wishlist here that takes the wanted sets
            return _render(source, screen='choose', title=LABEL[source], subtitle='Choose what to sync, and in which direction. You can change it later.',
                           link=status['link'], directions=sync_run.directions(db, source), segments=sync_run.SEGMENTS, segment_labels=sync_run.SEGMENT_LABELS_BY[source],
                           wish_lists=wishlists.listing(db), **_steps(2))
        lists, sets_error, part_lists, parts_error = _lists(db)
        return _render(source, screen='choose', title=LABEL[source], subtitle='Choose what to sync, and in which direction. You can change it later.',
                     link=status['link'], directions=sync_run.directions(db), segments=sync_run.SEGMENTS, segment_labels=sync_run.SEGMENT_LABELS,
                     lists=lists, part_lists=part_lists, set_error=sets_error, parts_error=parts_error, wish_lists=wishlists.listing(db), keep_names=sync.keep_list_names_on(db, SOURCE),
                     lost_rules=lost_parts.RULES, lost_rule=lost_parts.rule(db), send_rules=lost_parts_send.RULES, send_rule=lost_parts_send.send_rule(db),
                     **_steps(2))


def _ids(values):
    """Ids from form values: ASCII digits only, so '²' or a 30-digit number is left out, never a 500."""
    return [int(v) for v in values if re.fullmatch(r'[0-9]{1,18}', v)]


@_route('post', '/choose', False)
def step_choose_save(source):
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    form = request.form
    if source == 'brickset':
        values = dict(owned_dir=form.get('owned_dir'), wishlist_dir=form.get('wishlist_dir'), wish_list=form.get('wish_list') or 'default')
    else:
        values = _rebrickable_values(form)
    try:
        with _db() as db, audit_origin('app'):
            sync_run.save_choices(db, values, source)
            if form.get('start') == '0':
                flash('Saved.', 'success')
                return redirect(url_for('web.bw_sync_site', source=source))
            plan = sync_run.start(db, source=source)
    except (errors.BrickWorkError, ValueError, sqlite3.Error, *sync_run.FAILURES) as exc:
        flash(_message(exc, source), 'warning')
        return redirect(_to(source, 'choose'))
    return redirect(_to(source, 'pick', run_id=plan['id']))


def _rebrickable_values(form):
    """The checked values of step 2 of the Rebrickable page."""
    one = lambda name: _event_id(form.get(name))   # noqa: E731  (the same ASCII-digit rule)
    names = {k.removeprefix('list_name:'): v[:80] for k, v in form.items() if k.startswith('list_name:')}
    owned = _ids(form.getlist('owned'))
    values = dict(owned_dir=form.get('owned_dir'), wishlist_dir=form.get('wishlist_dir'), parts_dir=form.get('parts_dir'), lost_dir=form.get('lost_dir'),
                  owned=owned, wishlist=one('wishlist'), send_to=one('send_to') or (owned[0] if len(owned) == 1 else None),
                  wish_list=form.get('wish_list') or 'default', part_lists=_ids(form.getlist('part_list')), lost_rule=form.get('lost_rule', ''),
                  send_rule=form.get('send_rule', ''), keep_list_names=form.get('keep_list_names') != '0', names=names,
                  keep_set_links=form.get('set_lists_read') == '0', keep_part_links=form.get('part_lists_read') == '0')
    return values


@_route('post', '/start', False)
def step_start(source):
    """Start a sync with the choices already saved (the page at rest): read the site and go to the pick step."""
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    try:
        with _db() as db, audit_origin('app'):
            plan = sync_run.start(db, source=source)
    except sync_run.FAILURES as exc:
        flash(_message(exc, source), 'warning')
        return redirect(url_for('web.bw_sync_site', source=source))
    return redirect(_to(source, 'pick', run_id=plan['id']))


def _load(db, run_id, source):
    """`(run, plans)`; `(None, None)` for a run that is gone, expired or belongs to the other site (a run id of one site opens nothing on the other)."""
    from ..core import errors
    from ..core.sync import run as sync_run
    try:
        run, plans = sync_run.load(db, run_id)
    except errors.BrickWorkError as exc:
        flash(str(exc), 'warning')
        return None, None
    if run.get('source', SOURCE) != source:
        abort(404)
    return run, plans


def _gone(source):
    return redirect(url_for('web.bw_sync_site', source=source))


@_route('get', '/run/<run_id>/pick', True)
def step_pick(source, run_id):
    from ..core.sync import run as sync_run
    mode = request.args.get('by', 'all')
    if mode not in [m for m, _ in sync_run.MODE_LABELS_BY[source]]:
        abort(404)
    with _db() as db:
        run, plans = _load(db, run_id, source)
        if run is None:
            return _gone(source)
    if run.get('applied') or run.get('applying'):
        return redirect(_to(source, 'result', run_id=run_id))
    picked = sync_run.picked_ids(run)
    candidates = run['candidates']
    keys = {'list': lambda c: c['lists'], 'theme': lambda c: [c['theme']] if c['theme'] else [], 'year': lambda c: [str(c['year'])] if c['year'] else []}
    chips = {}
    if mode in keys:
        for c in candidates:
            for k in keys[mode](c):
                chips[k] = chips.get(k, 0) + 1
    chips = sorted(chips.items(), key=lambda kv: (kv[0] if mode != 'year' else -int(kv[0]) if kv[0].isdigit() else 0, kv[0]))
    lists = (plans['pull'] or {}).get('lists') or {}
    return _render(source, screen='pick', title=LABEL[source], subtitle=(
        'Pick the sets this run covers. A set you do not pick keeps its copies, counts and fields; only its list names follow their lists.' if mode == 'list' and lists.get('keep')
        else 'Pick the sets this run covers. Sets you do not pick stay as they are on both sides.'), run=run, mode=mode, modes=sync_run.MODE_LABELS_BY[source],
        candidates=candidates, picked=picked, chips=chips, group=mode, keep_names=bool(lists.get('keep')), list_names=sorted((lists.get('names') or {}).values()),
        loose=_loose_names(run, plans), lost_on=run['directions']['lost'] != 'off', **_steps(3))


def _loose_names(run, plans):
    return [entry['name'] for entry in (plans['parts'] or {}).get('lists', ())]


@_route('post', '/run/<run_id>/pick', False)
def step_pick_save(source, run_id):
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    ids = _ids(request.form.getlist('item'))
    keep = None if 'keep_present' not in request.form else request.form.getlist('keep_list_names')[-1:] == ['1']   # the hidden 0 comes first: the last value wins
    try:
        with _db() as db, audit_origin('app'):
            _same_site(db, run_id, source)
            sync_run.save_pick(db, run_id, ids, keep)
    except (errors.BrickWorkError, *sync_run.FAILURES) as exc:
        flash(_message(exc, source), 'warning')
        return redirect(_to(source, 'pick', run_id=run_id))
    return redirect(_to(source, 'preview', run_id=run_id))


def _same_site(db, run_id, source):
    """A run id of the other site opens nothing here (404). An id that is not a run, or has expired, is left to the write that follows, which says so."""
    from ..core import errors, sync
    try:
        run = sync.load_plan(db, run_id, 'run')
    except errors.BrickWorkError:
        return
    if run.get('source', SOURCE) != source:
        abort(404)


def _lots(db):
    return [dict(r) for r in db.execute('SELECT id, name FROM main.lot WHERE archived_at IS NULL ORDER BY name, id')]


@_route('get', '/run/<run_id>/preview', True)
def step_preview(source, run_id):
    from ..core import sync
    from ..core.sync import lost_parts, lost_parts_send
    from ..core.sync import run as sync_run
    with _db() as db:
        run, plans = _load(db, run_id, source)
        if run is None:
            return _gone(source)
        if run.get('applied'):
            return redirect(_to(source, 'result', run_id=run_id))
        if run.get('job'):
            return redirect(_to(source, 'progress', run_id=run_id))
        if run.get('applying'):
            flash('This run is already running, or was interrupted. Check the sync log, then start a new one.', 'warning')
            return redirect(url_for('web.bw_sync_site', source=source))
        rows = sync_run.rows(db, run, plans)
        budget = sync_run.budget(db, source)
        lots = _lots(db)
        status = sync.status(db, source)
    lost_in = sync_run.lost_in(run, plans)
    lost_out = sync_run.lost_out(run)
    parts = sync_run.part_rows(plans)
    lines = ((plans['pull'] or {}).get('lists') or {}).get('preview', ())
    changed_lines = [line for line in lines]
    conflicts = [r for r in rows if r['state'] == 'conflict']
    main = [r for r in rows if r['state'] != 'conflict']
    lost_rows = (len((lost_in or {}).get('sets', ())) + len((lost_in or {}).get('unmatched_sets', ()))) if lost_in and lost_in.get('status') == 'read' else 0
    lost_send_rows = [r for r in (lost_out or {}).get('rows', ())]
    counts = dict(all=len(rows) + lost_rows + len(lost_send_rows) + len(parts), into=sum(1 for r in rows if r['group'] == 'into') + lost_rows + len(parts), to=sum(1 for r in rows if r['group'] == 'to') + len(lost_send_rows),
                  both=len(conflicts), lost=lost_rows + len(lost_send_rows), parts=len(parts))
    choosable = sum(1 for r in rows if r['options']) + sum(1 for e in (lost_in or {}).get('sets', ()) if e['state'] == 'pick' or e['preview']['added'] or e['preview']['replaced'] or e['preview']['cleared']) \
        + sum(1 for r in lost_send_rows if r.get('tickable')) + len(parts) + sum(1 for line in changed_lines if set(line['choices']) - {'keep', 'skip'})
    sending = [r for r in rows for o in r['options'] if o['id'] in ('send', 'remove') and o['id'] == r['default']]
    sets_sent = len({r.get('send_no') or r['item_id'] for r in sending}) if source == 'brickset' else len(sending)      # Brickset gets one call per set, whatever changes in it
    send_requests = sets_sent + sum(1 for r in lost_send_rows if r.get('ticked'))
    last = ((status.get('last_pull') or {}).get('at') or (status.get('last_send') or {}).get('at'))
    return _render(source, screen='preview', title=LABEL[source], run=run, rows=main, conflicts=conflicts, counts=counts,
                 lost_in=lost_in, lost_out=lost_out, parts=parts, parts_unmatched=(plans['parts'] or {}).get('unmatched', ()), parts_lists=(plans['parts'] or {}).get('lists', ()), lots=lots, lines=changed_lines,
                 list_words=sync_run.LIST_WORDS, budget=budget, choosable=choosable, requests=send_requests, rule_labels=lost_parts.RULE_LABELS,
                 send_rule_labels={v: l for v, l, _ in lost_parts_send.RULES}, last_run=last, compared=len(run['candidates']),
                 checked=(plans['pull'] or plans['send'] or plans['parts'] or {}).get('created_at'), picked_count=len(run['picked'] if run['picked'] is not None else run['candidates']),
                 **_steps(4))


@_route('post', '/run/<run_id>/run', False)
def step_apply(source, run_id):
    from werkzeug.datastructures import MultiDict
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    from ..core.sync import run_job
    _guard()
    form = MultiDict(request.form)
    if form.get('lot_all'):    # one lot for every loose row ticked, the section's "Put in"
        for key in form.getlist('part'):
            form['lot:' + key] = form['lot_all']
    try:
        with _db() as db, audit_origin('app'):
            _same_site(db, run_id, source)
            run_job.queue(db, run_id, form, via='app')
            run, _plans = sync_run.load(db, run_id)
    except LOCAL as exc:   # the database or the run file could not be written, possibly after Rebrickable took changes: say so, never a 500
        flash(public(exc, _unsaved(source)), 'warning')
        return redirect(url_for('web.bw_sync_site', source=source))
    except (errors.BrickWorkError, *sync_run.FAILURES) as exc:
        flash(_message(exc, source), 'warning')
        return redirect(_to(source, 'preview', run_id=run_id))
    if run.get('job'):                 # queued now, or by an earlier post: the page follows the job
        return redirect(_to(source, 'progress', run_id=run_id))
    if not run.get('applied'):         # claimed by another request that has not finished, or one that was interrupted
        flash('This run is already running, or was interrupted. Check the sync log, then start a new one.', 'warning')
        return redirect(url_for('web.bw_sync_site', source=source))
    return redirect(_to(source, 'result', run_id=run_id))


def _interrupted_stage(stages, name):
    from ..core.sync import run as sync_run
    stage = stages.get(name) or {}
    return stage.get('status') == 'failed' and stage.get('message') == sync_run.INTERRUPTED_MESSAGE


def _is_interrupted(stages):
    return _interrupted_stage(stages, 'send') or _interrupted_stage(stages, 'lost_out')


def _send_it_when(site, unknown):
    """When to tick Send it too, for the rows in flight as (chosen action, run row): how the person sees on the site that the call did not arrive.
    A removal did not arrive when the row is still there, an add when it is not there, a changed row stays there either way."""
    if len(unknown) != 1:
        return 'where the change did not arrive'
    action, row = unknown[0]
    if action == 'remove':
        return 'if it is still there'
    label = next((o['label'] for o in row.get('options', ()) if o['id'] == 'send'), '')
    if label.startswith('Add '):
        return 'if it is not there'
    if label.startswith('Quantity ') or label.removeprefix('Send ').split(' ', 1)[0].isdigit():
        return f'if {site} does not show the new count'
    return f'if {site} does not show the new value'


def _undo_listed(runs, run_id):
    """Whether Last runs lists this run as Interrupted and offers the Undo of its pull (a newer pull takes the Undo over)."""
    pulls = {e for r in runs if r.get('run') == run_id and r['state'] == 'Interrupted' for e in r.get('pulls', ())}
    return any(r['undoable'] and r.get('event') in pulls for r in runs)


def _unsent_rows(rows, send):
    """The rows an interrupted send left, from the stage's results: `unknown` is the one that was in flight (it may have gone out), `failed` did not
    go. Rows that went out are only counted."""
    items = []
    for r in send.get('results', ()):
        if r['result'] in ('sent', 'unchanged'):
            continue
        row = rows.get(r['key'], {})
        items.append(dict(key=r['key'], number=row.get('number'), name=row.get('name') or 'Name not recorded',
                          what=(row['options'][-1]['label'].lower() if row.get('options') else ''), state='not known' if r['result'] == 'unknown' else 'not sent'))
    return sorted(items, key=lambda i: i['state'] != 'not known')       # the rows that may have gone out come first: the list shows only the first few


@_route('get', '/run/<run_id>/progress', True)
def step_progress(source, run_id):
    """Step 5 while a run is a job (#685): the pull as one step, the sends one call at a time, Stop after this one, and the interrupted view."""
    from ..core.sync import run as sync_run
    from ..core.sync import run_job
    with _db() as db:
        run, plans = _load(db, run_id, source)
        if run is None:
            return _gone(source)
        if not run.get('job'):
            return redirect(_to(source, 'result' if run.get('applied') else 'preview', run_id=run_id))
        info = run_job.progress(db, run_id)
        interrupted = run.get('applied') and _is_interrupted(run['stages'])
        if run.get('applied') and not interrupted:
            return redirect(_to(source, 'result', run_id=run_id))
        rows = {r['key']: r for r in sync_run.rows(db, run, plans)} if interrupted else {}
        undo_listed = bool(interrupted) and _undo_listed(_runs(db, source), run_id)
        events = sync_run.pull_events(run)
        pull_undone = bool(interrupted and events and all(db.execute('SELECT 1 FROM event_undo WHERE event_id=?', (e,)).fetchone() for e in events))      # one of two undone: not "the pull"
    stages = {s['name']: s for s in info['stages']}
    send = run['stages'].get('send') or {}
    sent_rows = [r for r in send.get('results', ()) if r['result'] in ('sent', 'unchanged')]
    unsent = _unsent_rows(rows, send) if interrupted else []
    chosen = (run.get('job_form') or {}).get('chosen', {})
    send_it_when = _send_it_when(LABEL[source], [(chosen.get(u['key']), rows.get(u['key'], {})) for u in unsent if u['state'] == 'not known'])
    return _render(source, screen='progress', title=LABEL[source], run=run, info=info, unsaved=_unsaved(source), pstages=stages, interrupted=bool(interrupted), unsent=unsent,
                 sent_count=len(sent_rows), send_total=send.get('rows', 0), unknown_count=sum(1 for u in unsent if u['state'] == 'not known'),
                 unsent_count=sum(1 for u in unsent if u['state'] == 'not sent'), lost_interrupted=_interrupted_stage(run['stages'], 'lost_out'),
                 undo_in_last_runs=undo_listed, pull_undone=pull_undone, send_it_when=send_it_when,
 **_steps(5))


@_route('post', '/run/<run_id>/stop', False)
def step_stop(source, run_id):
    from ..core import errors
    from ..core.sync import run_job
    _guard()
    try:
        with _db() as db:
            _same_site(db, run_id, source)
            run_job.request_stop(db, run_id)
    except LOCAL as exc:
        flash(public(exc, _unsaved(source)), 'warning')
    except errors.BrickWorkError as exc:
        flash(_message(exc, source), 'warning')
    return redirect(_to(source, 'progress', run_id=run_id))


@_route('get', '/run/<run_id>/result', True)
def step_result(source, run_id):
    from ..core.sync import lost_parts
    from ..core.sync import run as sync_run
    with _db() as db:
        run, plans = _load(db, run_id, source)
        if run is None:
            return _gone(source)
        if not run.get('applied'):
            if run.get('job'):
                return redirect(_to(source, 'progress', run_id=run_id))
            if run.get('applying'):
                flash('This run is already running, or was interrupted. Check the sync log, then start a new one.', 'warning')
                return redirect(url_for('web.bw_sync_site', source=source))
            return redirect(_to(source, 'preview', run_id=run_id))
        budget = sync_run.budget(db, source)
        rows = {r['key']: r for r in sync_run.rows(db, run, plans)}
        undone = False
        events = run['applied']['events']
        if events:
            undone = bool(db.execute('SELECT 1 FROM event_undo WHERE event_id=?', (events[0],)).fetchone())
        pull = (run['stages'].get('pull') or {})
        lost_in = lost_result(db, pull['event']) if pull.get('event') else None
        list_changes = pull.get('lists_changed', 0)                   # distinct lists renamed or dropped, as the preview names them
    stages = run['stages']
    send = stages.get('send') or {}
    failed_rows = [dict(rows.get(r['key'], {}), result=r) for r in send.get('results', ()) if r['result'] not in ('sent', 'unchanged')]
    counts = send.get('counts') or {}
    lost = stages.get('lost_out') or {}
    lost_counts = lost.get('counts') or {}
    sent_total = counts.get('sent', 0) + counts.get('unchanged', 0) + lost_counts.get('sent', 0)
    waiting_total = counts.get('paused', 0) + lost_counts.get('waiting', 0)               # a budget pause: the rest waits, it did not fail
    failed_total = sum(v for k, v in counts.items() if k not in ('sent', 'unchanged', 'paused')) + lost_counts.get('failed', 0)
    parts = stages.get('parts') or {}
    changed = pull.get('counts') or {}
    here = (changed.get('copies', 0) + changed.get('stock', 0) + changed.get('wishes_added', 0) + changed.get('wishes_changed', 0) + changed.get('lost_added', 0)
            + changed.get('lost_replaced', 0) + changed.get('lost_cleared', 0) + (parts.get('counts') or {}).get('rows', 0) + list_changes)
    return _render(source, screen='result', title=LABEL[source], run=run, stages=stages, undone=undone, failed_rows=failed_rows,
                 here=here, sent_total=sent_total, failed_total=failed_total, waiting_total=waiting_total, list_changes=list_changes, lost_in=lost_in,
                 rule_labels=lost_parts.RULE_LABELS, budget=budget, finished=run['applied']['at'], **_steps(6))


@_route('post', '/undo', False)
def step_undo(source):
    """Undo this run: the pull and the part-list pull of one run in one step. Only a pull of this site can be undone here."""
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    event = _event_id(request.form.get('event'))
    if event is None:
        abort(400)
    try:
        with _db() as db, audit_origin('app'):
            if _receipt_source(db, event) != source:
                abort(404)
            sync_run.undo_run(db, event)
        flash('Run undone.', 'success')
    except (errors.BrickWorkError, ValueError, sqlite3.Error) as exc:
        flash(str(exc) if isinstance(exc, ValueError) else _message(exc, source), 'warning')
    return redirect(url_for('web.bw_sync_site', source=source))


@_route('post', '/run/<run_id>/retry', False)
def step_retry(source, run_id):
    """Retry the sends of a run that did not go through (a failed row, a budget pause); only rows not sent are tried again."""
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    try:
        with _db() as db, audit_origin('app'):
            _same_site(db, run_id, source)
            sync_run.retry_send(db, run_id, also=request.form.getlist('also'))
    except LOCAL as exc:
        flash(public(exc, _unsaved(source)), 'warning')
        return redirect(url_for('web.bw_sync_site', source=source))
    except (errors.BrickWorkError, *sync_run.FAILURES) as exc:
        flash(_message(exc, source), 'warning')
    try:
        with _db() as db:
            stages = sync_run.load(db, run_id)[0].get('stages') or {}
    except (errors.BrickWorkError, *LOCAL):
        stages = {}
    return redirect(_to(source, 'progress' if _is_interrupted(stages) else 'result', run_id=run_id))


def _register():
    """Both sites get every step: the same view body under its own URL, endpoint and `source`."""
    for source in PREFIX:
        for method, path, unavailable, view in STEPS_LIST:
            def bound(view=view, source=source, **values):
                return view(source, **values)
            bound.__name__ = f'bw_sync_{PREFIX[source]}_{view.__name__.removeprefix("step_")}'
            if unavailable:
                bound = _unavailable(bound)
            bound = login_required(bound)
            web_page.add_url_rule(f'/workbench/sync/{source}{path}', endpoint=bound.__name__, view_func=bound, methods=[method.upper()])


_register()
