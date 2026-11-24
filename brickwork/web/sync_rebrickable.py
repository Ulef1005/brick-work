"""The Rebrickable sync page and its six steps (#519): connect, choose what, pick sets, preview, run, result.

The views only read and write through `core.sync` and `core.sync.run`; the plans, the applies and the choices are theirs. The run record is a plan
file (24 hours), so the pick, preview, run and result pages take its id in the path."""
import json
import re
import sqlite3

from flask import abort, flash, redirect, request, url_for
from flask_login import login_required

from .views import web_page, bw_add_csrf, bw_collection_editable
from .sync_views import _db, _event_id, _log, _message, _page, _receipt_source, _unavailable, lost_result

SOURCE = 'rebrickable'
STEPS = ('Connect', 'Choose what', 'Pick sets', 'Preview', 'Run', 'Result')
KEY_FIELD = 'key:key'


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


def _runs(db):
    """The last runs for the page at rest, newest first, from the sync log; Undo only on the newest pull that was not undone."""
    rows = _log(db, limit=5, source=SOURCE)
    undo = next((r['id'] for r in rows if r['direction'] == 'Pulled' and r['state'] == 'Done' and r.get('event')), None)
    return [dict(r, undoable=r['id'] == undo, retry=r['direction'] == 'Sent' and r['state'] != 'Done' and not r.get('lost'), title=('Undo' if r['direction'] == 'Undone' else 'Run')) for r in rows]


def site_page():
    """Frame 18: the account, the last runs and what syncs, from what is stored (no call to Rebrickable)."""
    from ..core import sync
    from ..core.sync import run as sync_run
    from .setup_state import key_missing
    with _db() as db:
        status = sync.status(db, SOURCE)
        connected = bool(status['credentials']['user']['configured'])
        key_gap = key_missing(SOURCE)
        budget = sync_run.budget(db)
        what = sync_run.what_syncs(db)
        runs = _runs(db)
        pulled = request.args.get('pulled', '')
        if _receipt_source(db, pulled) != SOURCE:
            pulled = ''
        result = lost_result(db, pulled)
        from ..core.sync import lost_parts
    last = status.get('last_pull') or status.get('last_send')
    stamps = [t for t in ((status.get('last_pull') or {}).get('at'), (status.get('last_send') or {}).get('at')) if t]
    from .sync_views import _last_sync
    return _page('web/toni/web/bw_sync_rb.html', screen='site', title='Rebrickable', subtitle='Last run ' + _last_sync(status) if last else 'Not run yet',
                 connected=connected, key_gap=key_gap, key=status['credentials']['key'], budget=budget, what=what, runs=runs,
                 waiting=status.get('waiting') or 0, pulled=pulled, lost_result=result, rule_labels=lost_parts.RULE_LABELS, stamps=stamps,
                 key_day=_day((budget or {}).get('last_success')), source=SOURCE)


@web_page.get('/workbench/sync/rebrickable/connect')
@login_required
@_unavailable
def bw_sync_rb_connect():
    from ..core import sync
    from .setup_state import key_missing
    with _db() as db:
        status = sync.status(db, SOURCE)
    return _page('web/toni/web/bw_sync_rb.html', screen='connect', title='Rebrickable', subtitle='Connect your account, choose what to sync, then run the sync.',
                 connected=bool(status['credentials']['user']['configured']), key_gap=key_missing(SOURCE), key=status['credentials']['key'], source=SOURCE,
                 **_steps(1))


@web_page.post('/workbench/sync/rebrickable/key')
@login_required
def bw_sync_rb_key():
    """Save, test or remove the Rebrickable API key from step 1: the same operations as Catalogues & keys, which stays their one implementation."""
    from ..core import errors
    from ..core.sources.base import KeyRejected, SourceError, redact
    from . import admin_ops
    _guard()
    action = request.form.get('action')
    try:
        if action == 'save':
            outcome = admin_ops.tools_write('key_test_save', source=SOURCE, values={'key': request.form.get(KEY_FIELD, '')})
            flash('Saved · The key works' if outcome['tested'] else 'Saved · Not tested: ' + outcome['reason'], 'success')
        elif action == 'test':
            admin_ops.tools_write('key_test', source=SOURCE)
            flash('Rebrickable accepted the API key.', 'success')
        elif action == 'remove':
            admin_ops.tools_write('key_remove', source=SOURCE)
            flash('Removed the stored API key.', 'success')
        else:
            abort(400)
    except KeyRejected as exc:
        flash('Rebrickable rejected the key · ' + redact(exc), 'warning')
    except (errors.BrickWorkError, SourceError) as exc:
        flash(redact(exc), 'warning')
    return redirect(url_for('web.bw_sync_rb_connect'))


def _lists(db):
    """The set lists and the part lists of the account, each with the reason it could not be read (None when it could): `(sets, sets_error, parts, parts_error)`."""
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


@web_page.get('/workbench/sync/rebrickable/choose')
@login_required
@_unavailable
def bw_sync_rb_choose():
    from ..core import sync, wishlists
    from ..core.sync import lost_parts, lost_parts_send
    from ..core.sync import run as sync_run
    with _db() as db:
        status = sync.status(db, SOURCE)
        if not status['credentials']['user']['configured']:
            flash('Connect your Rebrickable account first.', 'warning')
            return redirect(url_for('web.bw_sync_rb_connect'))
        lists, sets_error, part_lists, parts_error = _lists(db)
        return _page('web/toni/web/bw_sync_rb.html', screen='choose', title='Rebrickable', subtitle='Choose what to sync, and in which direction. You can change it later.',
                     source=SOURCE, link=status['link'], directions=sync_run.directions(db), segments=sync_run.SEGMENTS, segment_labels=sync_run.SEGMENT_LABELS,
                     lists=lists, part_lists=part_lists, set_error=sets_error, parts_error=parts_error, wish_lists=wishlists.listing(db), keep_names=sync.keep_list_names_on(db, SOURCE),
                     lost_rules=lost_parts.RULES, lost_rule=lost_parts.rule(db), send_rules=lost_parts_send.RULES, send_rule=lost_parts_send.send_rule(db),
                     **_steps(2))


def _ids(values):
    """Ids from form values: ASCII digits only, so '²' or a 30-digit number is left out, never a 500."""
    return [int(v) for v in values if re.fullmatch(r'[0-9]{1,18}', v)]


@web_page.post('/workbench/sync/rebrickable/choose')
@login_required
def bw_sync_rb_choose_save():
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    form = request.form
    one = lambda name: _event_id(form.get(name))   # noqa: E731  (the same ASCII-digit rule)
    names = {k.removeprefix('list_name:'): v[:80] for k, v in form.items() if k.startswith('list_name:')}
    owned = _ids(form.getlist('owned'))
    values = dict(owned_dir=form.get('owned_dir'), wishlist_dir=form.get('wishlist_dir'), parts_dir=form.get('parts_dir'), lost_dir=form.get('lost_dir'),
                  owned=owned, wishlist=one('wishlist'), send_to=one('send_to') or (owned[0] if len(owned) == 1 else None),
                  wish_list=form.get('wish_list') or 'default', part_lists=_ids(form.getlist('part_list')), lost_rule=form.get('lost_rule', ''),
                  send_rule=form.get('send_rule', ''), keep_list_names=form.get('keep_list_names') != '0', names=names,
                  keep_set_links=form.get('set_lists_read') == '0', keep_part_links=form.get('part_lists_read') == '0')
    try:
        with _db() as db, audit_origin('app'):
            sync_run.save_choices(db, values)
            if form.get('start') == '0':
                flash('Saved.', 'success')
                return redirect(url_for('web.bw_sync_site', source=SOURCE))
            plan = sync_run.start(db)
    except (errors.BrickWorkError, ValueError, sqlite3.Error, *sync_run.FAILURES) as exc:
        flash(_message(exc, SOURCE), 'warning')
        return redirect(url_for('web.bw_sync_rb_choose'))
    return redirect(url_for('web.bw_sync_rb_pick', run_id=plan['id']))


@web_page.post('/workbench/sync/rebrickable/start')
@login_required
def bw_sync_rb_start():
    """Start a sync with the choices already saved (the page at rest): read Rebrickable and go to the pick step."""
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    try:
        with _db() as db, audit_origin('app'):
            plan = sync_run.start(db)
    except sync_run.FAILURES as exc:
        flash(_message(exc, SOURCE), 'warning')
        return redirect(url_for('web.bw_sync_site', source=SOURCE))
    return redirect(url_for('web.bw_sync_rb_pick', run_id=plan['id']))


def _load(db, run_id):
    from ..core import errors
    from ..core.sync import run as sync_run
    try:
        return sync_run.load(db, run_id)
    except errors.BrickWorkError as exc:
        flash(str(exc), 'warning')
        return None, None


def _gone():
    return redirect(url_for('web.bw_sync_site', source=SOURCE))


@web_page.get('/workbench/sync/rebrickable/run/<run_id>/pick')
@login_required
@_unavailable
def bw_sync_rb_pick(run_id):
    from ..core.sync import run as sync_run
    mode = request.args.get('by', 'all')
    if mode not in sync_run.MODES:
        abort(404)
    with _db() as db:
        run, plans = _load(db, run_id)
        if run is None:
            return _gone()
    if run.get('applied') or run.get('applying'):
        return redirect(url_for('web.bw_sync_rb_result', run_id=run_id))
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
    return _page('web/toni/web/bw_sync_rb.html', screen='pick', title='Rebrickable', subtitle=(
        'Pick the sets this run covers. A set you do not pick keeps its copies, counts and fields; only its list names follow their lists.' if mode == 'list' and lists.get('keep')
        else 'Pick the sets this run covers. Sets you do not pick stay as they are on both sides.'), source=SOURCE, run=run, mode=mode, modes=sync_run.MODE_LABELS,
        candidates=candidates, picked=picked, chips=chips, group=mode, keep_names=bool(lists.get('keep')), list_names=sorted((lists.get('names') or {}).values()),
        loose=_loose_names(run, plans), lost_on=run['directions']['lost'] != 'off', **_steps(3))


def _loose_names(run, plans):
    return [entry['name'] for entry in (plans['parts'] or {}).get('lists', ())]


@web_page.post('/workbench/sync/rebrickable/run/<run_id>/pick')
@login_required
def bw_sync_rb_pick_save(run_id):
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    ids = _ids(request.form.getlist('item'))
    keep = None if 'keep_present' not in request.form else request.form.getlist('keep_list_names')[-1:] == ['1']   # the hidden 0 comes first: the last value wins
    try:
        with _db() as db, audit_origin('app'):
            sync_run.save_pick(db, run_id, ids, keep)
    except (errors.BrickWorkError, *sync_run.FAILURES) as exc:
        flash(_message(exc, SOURCE), 'warning')
        return redirect(url_for('web.bw_sync_rb_pick', run_id=run_id))
    return redirect(url_for('web.bw_sync_rb_preview', run_id=run_id))


def _lots(db):
    return [dict(r) for r in db.execute('SELECT id, name FROM main.lot WHERE archived_at IS NULL ORDER BY name, id')]


@web_page.get('/workbench/sync/rebrickable/run/<run_id>/preview')
@login_required
@_unavailable
def bw_sync_rb_preview(run_id):
    from ..core import sync
    from ..core.sync import lost_parts, lost_parts_send
    from ..core.sync import run as sync_run
    with _db() as db:
        run, plans = _load(db, run_id)
        if run is None:
            return _gone()
        if run.get('applied'):
            return redirect(url_for('web.bw_sync_rb_result', run_id=run_id))
        if run.get('applying'):
            flash('This run is already running, or was interrupted. Check the sync log, then start a new one.', 'warning')
            return redirect(url_for('web.bw_sync_site', source=SOURCE))
        rows = sync_run.rows(db, run, plans)
        budget = sync_run.budget(db)
        lots = _lots(db)
        status = sync.status(db, SOURCE)
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
    send_requests = sum(1 for r in rows for o in r['options'] if o['id'] in ('send', 'remove') and o['id'] == r['default']) + sum(1 for r in lost_send_rows if r.get('ticked'))
    last = ((status.get('last_pull') or {}).get('at') or (status.get('last_send') or {}).get('at'))
    return _page('web/toni/web/bw_sync_rb.html', screen='preview', title='Rebrickable', source=SOURCE, run=run, rows=main, conflicts=conflicts, counts=counts,
                 lost_in=lost_in, lost_out=lost_out, parts=parts, parts_unmatched=(plans['parts'] or {}).get('unmatched', ()), parts_lists=(plans['parts'] or {}).get('lists', ()), lots=lots, lines=changed_lines,
                 list_words=sync_run.LIST_WORDS, budget=budget, choosable=choosable, requests=send_requests, rule_labels=lost_parts.RULE_LABELS,
                 send_rule_labels={v: l for v, l, _ in lost_parts_send.RULES}, last_run=last, compared=len(run['candidates']),
                 checked=(plans['pull'] or plans['send'] or plans['parts'] or {}).get('created_at'), picked_count=len(run['picked'] if run['picked'] is not None else run['candidates']),
                 **_steps(4))


@web_page.post('/workbench/sync/rebrickable/run/<run_id>/run')
@login_required
def bw_sync_rb_apply(run_id):
    from werkzeug.datastructures import MultiDict
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    form = MultiDict(request.form)
    if form.get('lot_all'):    # one lot for every loose row ticked, the section's "Put in"
        for key in form.getlist('part'):
            form['lot:' + key] = form['lot_all']
    try:
        with _db() as db, audit_origin('app'):
            run = sync_run.apply(db, run_id, form)
    except (errors.BrickWorkError, *sync_run.FAILURES) as exc:
        flash(_message(exc, SOURCE), 'warning')
        return redirect(url_for('web.bw_sync_rb_preview', run_id=run_id))
    if not run.get('applied'):         # claimed by another request that has not finished, or one that was interrupted
        flash('This run is already running, or was interrupted. Check the sync log, then start a new one.', 'warning')
        return redirect(url_for('web.bw_sync_site', source=SOURCE))
    return redirect(url_for('web.bw_sync_rb_result', run_id=run_id))


@web_page.get('/workbench/sync/rebrickable/run/<run_id>/result')
@login_required
@_unavailable
def bw_sync_rb_result(run_id):
    from ..core.sync import lost_parts
    from ..core.sync import run as sync_run
    with _db() as db:
        run, plans = _load(db, run_id)
        if run is None:
            return _gone()
        if not run.get('applied'):
            if run.get('applying'):
                flash('This run is already running, or was interrupted. Check the sync log, then start a new one.', 'warning')
                return redirect(url_for('web.bw_sync_site', source=SOURCE))
            return redirect(url_for('web.bw_sync_rb_preview', run_id=run_id))
        budget = sync_run.budget(db)
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
    return _page('web/toni/web/bw_sync_rb.html', screen='result', title='Rebrickable', source=SOURCE, run=run, stages=stages, undone=undone, failed_rows=failed_rows,
                 here=here, sent_total=sent_total, failed_total=failed_total, waiting_total=waiting_total, list_changes=list_changes, lost_in=lost_in,
                 rule_labels=lost_parts.RULE_LABELS, budget=budget, finished=run['applied']['at'], **_steps(6))


@web_page.post('/workbench/sync/rebrickable/undo')
@login_required
def bw_sync_rb_undo():
    """Undo this run: the pull and the part-list pull of one run in one step. Only a Rebrickable pull can be undone here."""
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    event = _event_id(request.form.get('event'))
    if event is None:
        abort(400)
    try:
        with _db() as db, audit_origin('app'):
            if _receipt_source(db, event) != SOURCE:
                abort(404)
            sync_run.undo_run(db, event)
        flash('Run undone.', 'success')
    except (errors.BrickWorkError, ValueError, sqlite3.Error) as exc:
        flash(str(exc) if isinstance(exc, ValueError) else _message(exc, SOURCE), 'warning')
    return redirect(url_for('web.bw_sync_site', source=SOURCE))


@web_page.post('/workbench/sync/rebrickable/run/<run_id>/retry')
@login_required
def bw_sync_rb_retry(run_id):
    """Retry the sends of a run that did not go through (a failed row, a budget pause); only rows not sent are tried again."""
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    try:
        with _db() as db, audit_origin('app'):
            sync_run.retry_send(db, run_id)
    except (errors.BrickWorkError, *sync_run.FAILURES) as exc:
        flash(_message(exc, SOURCE), 'warning')
    return redirect(url_for('web.bw_sync_rb_result', run_id=run_id))
