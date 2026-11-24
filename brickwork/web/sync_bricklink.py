"""The BrickLink sync page and its six steps (#521, slice A): connect, choose what, pick lots, preview, run, result.

Slice A covers orders into Orders and the price guide region. All run state lives in `core.sync.bricklink_run`,
key writes go through `admin_ops`, and undo uses `core.sync.run.undo_run` with its own BrickLink audit row."""
import json
import re
import sqlite3

from flask import abort, current_app, flash, redirect, request, url_for
from flask_login import login_required

from .safe_errors import public
from .sync_site import LOCAL, _day, _guard
from .sync_views import _db, _event_id, _page, _unavailable, stamp
from .views import web_page

SOURCE = 'bricklink'
LABEL = 'BrickLink'
TEMPLATE = 'web/toni/web/bw_sync_bl.html'
STEPS = ('Connect', 'Choose what', 'Pick lots', 'Preview', 'Run', 'Result')
UNSAVED = ('Brick Work could not write down this run: the data folder may be full or read-only. '
           'Check Orders and the sync log before you start a new run.')
_KEY_LABELS = {
    'consumer_key': 'Consumer key',
    'consumer_secret': 'Consumer secret',
    'token_value': 'Token value',
    'token_secret': 'Token secret',
}
_REGION_LABELS = {
    'all': 'All regions', 'eu': 'European Union', 'europe': 'Europe', 'north_america': 'North America', 'south_america': 'South America',
    'asia': 'Asia', 'oceania': 'Oceania', 'africa': 'Africa', 'middle_east': 'Middle East',
}
ROUTES = []


def _route(method, path, unavailable):
    """Register one BrickLink step: login outermost, the not-available notice inside for GET pages."""
    def register(view):
        ROUTES.append((method, path, unavailable, view))
        return view
    return register


def _render(**context):
    return _page(TEMPLATE, source=SOURCE, label=LABEL, **context)


def _steps(current):
    return dict(steps=STEPS, step=current)


def _keys():
    from ..core import keys
    return keys


def _key_fields():
    """Ordered `(field, label)` pairs for BrickLink's four OAuth credentials."""
    return [(field, _KEY_LABELS[field]) for field in _keys().fields(SOURCE)]


def _region_options():
    """`(value, label)` options for the price region, in the order of `price_settings.REGIONS`."""
    from ..core import price_settings
    return [(region, _REGION_LABELS[region]) for region in price_settings.REGIONS]


def _error_text(exc):
    from ..core import errors
    from ..core.sources.base import KeyRejected, SourceError, WaitingForBudget
    from ..core.sync import bricklink_run
    if isinstance(exc, (KeyRejected, WaitingForBudget, SourceError)):
        return bricklink_run._message(exc)
    if isinstance(exc, errors.BrickWorkError):
        return str(exc)
    return public(exc, 'BrickLink could not be reached · nothing was changed. Try again.')


def _same_site(db, run_id):
    """A run id of another site opens nothing here (404)."""
    from ..core import errors, sync
    try:
        run = sync.load_plan(db, run_id, 'run')
    except errors.BrickWorkError:
        return
    if run.get('source') != SOURCE:
        abort(404)


def _load(db, run_id):
    """Load one BrickLink run; 404 for another site's run, else flash and None when missing or expired."""
    from ..core import errors
    from ..core.sync import bricklink_run
    _same_site(db, run_id)
    try:
        run = bricklink_run.load(db, run_id)
    except errors.ValidationFailed as exc:
        if 'not a BrickLink run' in str(exc):
            abort(404)
        flash(str(exc), 'warning')
        return None
    except errors.BrickWorkError as exc:
        flash(str(exc), 'warning')
        return None
    if run.get('source') != SOURCE:
        abort(404)
    return run


def _runs(db, limit=5):
    """Newest BrickLink runs from `main.event`; Undo only on the newest when no later BrickLink undo row exists."""
    rows = []
    for index, r in enumerate(db.execute(
        "SELECT id, at, new_value FROM main.event WHERE entity_kind='sync' AND entity_id=? AND field='run' ORDER BY id DESC LIMIT ?",
        (SOURCE, limit),
    )):
        try:
            data = json.loads(r['new_value']) if r['new_value'] else {}
        except ValueError:
            data = {}
        events = data.get('events') if isinstance(data, dict) else []
        events = events if isinstance(events, list) else []
        n = len(events)
        event = events[0] if events else None
        undoable = False
        if index == 0 and event is not None:
            later_undo = db.execute(
                "SELECT 1 FROM main.event WHERE entity_kind='sync' AND entity_id=? AND field='undo' AND id > ? LIMIT 1",
                (SOURCE, r['id']),
            ).fetchone()
            undoable = later_undo is None
        rows.append(dict(id=r['id'], at=r['at'], what=f"{n} {'order' if n == 1 else 'orders'} pulled",
                         event=event, undoable=undoable))
    return rows


def _run_audit(db, run_id):
    """Return `(audit_id, events, at)` for one BrickLink run row, or `(None, [], None)`."""
    for row in db.execute(
        "SELECT id, new_value, at FROM main.event WHERE entity_kind='sync' AND entity_id=? AND field='run' ORDER BY id DESC",
        (SOURCE,),
    ):
        try:
            data = json.loads(row['new_value']) if row['new_value'] else {}
        except ValueError:
            continue
        if isinstance(data, dict) and data.get('run') == run_id:
            events = data.get('events') or []
            return row['id'], events if isinstance(events, list) else [], row['at']
    return None, [], None


def _is_bricklink_event(db, event_id):
    """True only when `event_id` belongs to a `sync:bricklink` run audit row."""
    for row in db.execute(
        "SELECT new_value FROM main.event WHERE entity_kind='sync' AND entity_id=? AND field='run' ORDER BY id DESC",
        (SOURCE,),
    ):
        try:
            data = json.loads(row['new_value']) if row['new_value'] else {}
        except ValueError:
            continue
        if isinstance(data, dict) and event_id in (data.get('events') or ()):
            return True
    return False


def _order_url(order_id):
    return url_for('web.bw_order', order_id=int(order_id))


def _pick_lede(choices):
    """Heading line for the Pick step, adapted to the saved date and status filters."""
    since_on = choices.get('since_on') and choices.get('since')
    all_status = choices.get('status') == 'all'
    if since_on and not all_status:
        lead = f"Orders since {choices['since']} with status Received or Paid."
    elif since_on:
        lead = f"Orders since {choices['since']}."
    elif not all_status:
        lead = 'Orders with status Received or Paid.'
    else:
        lead = 'All orders.'
    return lead + ' Tick the orders this run pulls into Orders.'


@_route('get', '', True)
def step_site():
    """Frame 27: BrickLink account, last runs and what syncs, from stored data (no call to BrickLink)."""
    from ..core.sync import bricklink_run
    with _db() as db:
        key = _keys().state(db, SOURCE)
        connected = bool(key.get('configured'))
        budget = bricklink_run.budget(db)
        choices = bricklink_run.choices(db)
        what = bricklink_run.what_syncs(db)
        runs = _runs(db, limit=5)
    subtitle = 'Last run ' + stamp(runs[0]['at']) if runs else 'Not run yet'
    return _render(screen='site', title=LABEL, subtitle=subtitle, connected=connected, key=key,
                   orders_on=choices['orders'] != 'off', budget=budget, what=what, runs=runs,
                   key_day=_day((budget or {}).get('last_success')))


@_route('get', '/connect', True)
def step_connect():
    """Frame 28: enter, test or remove the four write-only OAuth credentials."""
    with _db() as db:
        key = _keys().state(db, SOURCE)
    return _render(screen='connect', title=LABEL, subtitle='Connect your account, choose what to sync, then run the sync.',
                   connected=bool(key.get('configured')), key=key, key_fields=_key_fields(), **_steps(1))


@_route('post', '/key', False)
def step_key():
    """Save, test or remove BrickLink's OAuth credentials through `admin_ops`, keeping one implementation."""
    from ..core import errors
    from ..core.sources.base import KeyRejected, SourceError, redact
    from . import admin_ops
    _guard()
    action = request.form.get('action')
    back = url_for('web.bw_sync_bl_site') if request.form.get('next') == 'site' else url_for('web.bw_sync_bl_connect')
    try:
        if action == 'save':
            values = {field: request.form.get('key:' + field, '') for field, _ in _key_fields()}
            outcome = admin_ops.tools_write('key_test_save', source=SOURCE, values=values)
            flash('Saved · The key works' if outcome['tested'] else 'Saved · Not tested: ' + outcome['reason'], 'success')
        elif action == 'test':
            admin_ops.tools_write('key_test', source=SOURCE)
            flash('BrickLink accepted the key.', 'success')
        elif action == 'remove':
            admin_ops.tools_write('key_remove', source=SOURCE)
            flash('Removed the stored key.', 'success')
        else:
            abort(400)
    except KeyRejected as exc:
        flash('BrickLink rejected the key · ' + redact(exc), 'warning')
    except (errors.BrickWorkError, SourceError, ValueError, sqlite3.Error) as exc:
        flash(redact(exc), 'warning')
    return redirect(back)


@_route('get', '/choose', True)
def step_choose():
    """Frame 29: choose orders direction, filters and price guide region."""
    from ..core import price_settings
    from ..core.sync import bricklink_run
    with _db() as db:
        if not _keys().state(db, SOURCE).get('configured'):
            flash('Connect your BrickLink account first.', 'warning')
            return redirect(url_for('web.bw_sync_bl_connect'))
        choices = bricklink_run.choices(db)
        region = price_settings.read(db)['bricklink_region']
    return _render(screen='choose', title=LABEL, subtitle='Choose what to sync, and in which direction. You can change it later.',
                   choices=choices, statuses=bricklink_run.STATUSES, region=region, regions=_region_options(), **_steps(2))


@_route('post', '/choose', False)
def step_choose_save():
    """Save step-2 choices under audit; start a run and go to Pick unless only saving."""
    from ..core.sources.base import audit_origin
    from ..core.sync import bricklink_run
    _guard()
    try:
        with _db() as db, audit_origin('app'):
            bricklink_run.save_choices(db, request.form)
            if request.form.get('start') == '0':
                flash('Saved.', 'success')
                return redirect(url_for('web.bw_sync_bl_site'))
            run = bricklink_run.start(db)
    except bricklink_run.FAILURES as exc:
        flash(_error_text(exc), 'warning')
        return redirect(url_for('web.bw_sync_bl_choose'))
    return redirect(url_for('web.bw_sync_bl_pick', run_id=run['id']))


@_route('post', '/start', False)
def step_start():
    """Start a BrickLink run with the saved choices: read order headers and go to the pick step."""
    from ..core.sources.base import audit_origin
    from ..core.sync import bricklink_run
    _guard()
    try:
        with _db() as db, audit_origin('app'):
            run = bricklink_run.start(db)
    except bricklink_run.FAILURES as exc:
        flash(_error_text(exc), 'warning')
        return redirect(url_for('web.bw_sync_bl_choose'))
    return redirect(url_for('web.bw_sync_bl_pick', run_id=run['id']))
