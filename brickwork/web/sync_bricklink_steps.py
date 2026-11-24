"""Pick, preview, apply, result and undo steps for the BrickLink sync page, plus URL registration (#521, slice A)."""
import re
import sqlite3

from flask import abort, flash, redirect, request, url_for
from flask_login import login_required

from .safe_errors import public
from .sync_bricklink import (
    LABEL, ROUTES, UNSAVED,
    _error_text, _is_bricklink_event, _load, _order_url, _pick_lede, _render, _route, _run_audit, _steps,
)
from .sync_site import LOCAL, _guard
from .sync_views import _db, _event_id, _unavailable
from .views import web_page


def _result_summary(pulled, failed):
    """One-sentence result summary covering pulled orders and any failed imports."""
    if pulled and failed:
        return f"{pulled} {'order' if pulled == 1 else 'orders'} pulled into Orders, {failed} failed."
    if pulled:
        return f"{pulled} {'order' if pulled == 1 else 'orders'} pulled into Orders."
    if failed:
        return f"{failed} {'order' if failed == 1 else 'orders'} could not be imported."
    return 'No orders were pulled in this run.'


@_route('get', '/run/<run_id>/pick', True)
def step_pick(run_id):
    """Frame 30: list candidate BrickLink orders so the user can tick which ones to pull."""
    from ..core.sync import bricklink_run
    with _db() as db:
        run = _load(db, run_id)
        if run is None:
            return redirect(url_for('web.bw_sync_bl_site'))
        all_rows = bricklink_run.rows(db, dict(run, picked=None))
    saved = None if run.get('picked') is None else set(run['picked'])
    items = [
        dict(row, checked=(row['id'] in saved if saved is not None else row['state'] == 'new'))
        for row in all_rows
    ]
    picked_count = sum(1 for item in items if item['checked'])
    return _render(
        screen='pick', title=LABEL, subtitle='Pick which orders this run pulls into Orders.',
        run=run, run_id=run['id'], items=items, pick_lede=_pick_lede(run.get('choices') or {}),
        picked_count=picked_count, **_steps(3),
    )


@_route('post', '/run/<run_id>/pick', False)
def step_pick_save(run_id):
    """Save the ticked order ids on this run and continue to Preview."""
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import bricklink_run
    _guard()
    ids = [value for value in request.form.getlist('item') if re.fullmatch('[0-9]{1,12}', value)]
    try:
        with _db() as db, audit_origin('app'):
            bricklink_run.save_pick(db, run_id, ids)
    except bricklink_run.FAILURES as exc:
        if isinstance(exc, errors.ValidationFailed) and 'not a BrickLink run' in str(exc):
            abort(404)
        flash(_error_text(exc), 'warning')
        return redirect(url_for('web.bw_sync_bl_pick', run_id=run_id))
    return redirect(url_for('web.bw_sync_bl_preview', run_id=run_id))


@_route('get', '/run/<run_id>/preview', True)
def step_preview(run_id):
    """Frame 31: show which picked orders will be pulled into Orders before anything changes."""
    from ..core.sync import bricklink_run
    with _db() as db:
        run = _load(db, run_id)
        if run is None:
            return redirect(url_for('web.bw_sync_bl_site'))
        if run.get('applied'):
            return redirect(url_for('web.bw_sync_bl_result', run_id=run['id']))
        rows = bricklink_run.rows(db, run)
    new_count = sum(1 for row in rows if row['state'] == 'new')
    return _render(
        screen='preview', title=LABEL, subtitle='Review what this run will pull into Orders. Nothing has changed yet.',
        run=run, rows=rows, new_count=new_count, **_steps(4),
    )


@_route('post', '/run/<run_id>/run', False)
def step_apply(run_id):
    """Pull the ticked new orders into Orders under audit and open the Result screen."""
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import bricklink_run
    _guard()
    try:
        with _db() as db, audit_origin('app'):
            bricklink_run.apply(db, run_id, request.form)
    except LOCAL as exc:
        flash(public(exc, UNSAVED), 'warning')
        return redirect(url_for('web.bw_sync_bl_site'))
    except bricklink_run.FAILURES as exc:
        if isinstance(exc, errors.ValidationFailed) and 'not a BrickLink run' in str(exc):
            abort(404)
        flash(_error_text(exc), 'warning')
        return redirect(url_for('web.bw_sync_bl_preview', run_id=run_id))
    return redirect(url_for('web.bw_sync_bl_result', run_id=run_id))


@_route('get', '/run/<run_id>/result', True)
def step_result(run_id):
    """Frame 33: report each attempted order from the run and offer one Undo when still undoable."""
    with _db() as db:
        run = _load(db, run_id)
        if run is None:
            return redirect(url_for('web.bw_sync_bl_site'))
        if not run.get('applied'):
            return redirect(url_for('web.bw_sync_bl_preview', run_id=run['id']))
        _, events, _ = _run_audit(db, run['id'])
        undone = bool(events) and all(
            db.execute('SELECT 1 FROM event_undo WHERE event_id=?', (e,)).fetchone()
            for e in events
        )
    stages = run.get('stages') or {}
    results = []
    for candidate in run.get('candidates') or ():
        stage = stages.get(candidate['id'])
        if not stage:
            continue
        done = stage.get('status') == 'done'
        order_id = stage.get('order_id') if done else None
        results.append(dict(
            label=candidate['label'],
            status=stage.get('status') or 'failed',
            placed=stage.get('placed') or 0,
            unplaced=stage.get('unplaced') or 0,
            message=stage.get('message'),
            order_url=_order_url(order_id) if order_id is not None else None,
        ))
    pulled_count = sum(1 for row in results if row['status'] == 'done')
    failed_count = sum(1 for row in results if row['status'] != 'done')
    undo_event = events[0] if (pulled_count and events and not undone) else None
    return _render(
        screen='result', title=LABEL, subtitle='Review what this run changed in Orders.',
        run=run, results=results, pulled_count=pulled_count, failed_count=failed_count,
        summary=_result_summary(pulled_count, failed_count), undo_event=undo_event, undone=undone, **_steps(6),
    )


@_route('post', '/undo', False)
def step_undo():
    """Undo a BrickLink run through `core.sync.run.undo_run`."""
    from ..core import errors
    from ..core.sources.base import audit_origin
    from ..core.sync import run as sync_run
    _guard()
    event = _event_id(request.form.get('event'))
    if event is None:
        abort(400)
    try:
        with _db() as db, audit_origin('app'):
            if not _is_bricklink_event(db, event):
                abort(404)
            sync_run.undo_run(db, event)
        flash('Run undone.', 'success')
    except sqlite3.Error as exc:
        flash(public(exc, UNSAVED), 'warning')
    except (errors.BrickWorkError, ValueError) as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('web.bw_sync_bl_site'))


def _register():
    """Register every BrickLink route on `web_page` with login outermost and the unavailable guard inside."""
    for method, path, unavailable, view in ROUTES:
        name = 'bw_sync_bl_' + view.__name__.removeprefix('step_')
        bound = _unavailable(view) if unavailable else view
        bound.__name__ = name
        bound = login_required(bound)
        bound.__name__ = name
        web_page.add_url_rule(
            '/workbench/sync/bricklink' + path,
            endpoint=name,
            view_func=bound,
            methods=[method.upper()],
        )


_register()
