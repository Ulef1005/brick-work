"""Import from BrickTracker (#11 UI): upload an app.db, preview, import into this collection, Undo (rewritten on the 4.0 store in M.8j).

The older path that built a new database from server paths with a proof report (`brickwork migrate`) is gone, decision 4 of #110:
a 3.3 collection moves to 4.0 with `brickwork migrate4`.
"""
from contextlib import closing
import sqlite3
import uuid

from flask import abort, current_app, flash, get_flashed_messages, redirect, render_template, request, url_for
from .safe_errors import public
from flask_login import login_required

from .views import web_page, bw_add_csrf, bw_add_token, bw_collection_editable

LIMIT_MB = 200


def _db():
    from ..core.connect import connect
    from .admin_ops import brickwork_path
    return closing(connect(brickwork_path()))


def _render(**context):
    response = current_app.make_response(render_template('web/toni/web/bw_import.html', csrf_token=bw_add_token(),
        can_edit=bw_collection_editable(), messages=get_flashed_messages(with_categories=True), **context))
    response.headers['Cache-Control'] = 'no-store'
    return response


def _guard():
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') != request.host_url.rstrip('/') or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)
    bw_add_csrf(request.form)
    if not bw_collection_editable():
        abort(403, 'Changes are switched off on this instance')


@web_page.get('/manage/import-legacy')
@login_required
def bw_import_legacy():
    return _render(screen='upload', limit=LIMIT_MB, result=None, error=None)


@web_page.post('/manage/import-legacy/upload')
@login_required
def bw_import_upload():
    """Stream the upload to data/imports/uploads, plan from it, delete it either way."""
    from ..core.importer import bricktracker
    from ..core.sources.base import redact
    _guard()
    file = request.files.get('file')
    if file is None or not file.filename:
        flash('Choose the app.db file from your BrickTracker data folder.', 'warning')
        return redirect(url_for('web.bw_import_legacy'))
    with _db() as db:
        folder = bricktracker.plans_root(db) / 'uploads'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / uuid.uuid4().hex
        try:
            size = 0
            with target.open('wb') as out:
                while chunk := file.stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > LIMIT_MB * 1024 * 1024:
                        raise ValueError(f'The file is larger than {LIMIT_MB} MB · use brickwork import-bricktracker on the server')
                    out.write(chunk)
            plan = bricktracker.plan(db, target, name=file.filename)
        except (ValueError, OSError, sqlite3.Error) as exc:
            flash(redact(exc), 'warning')
            return redirect(url_for('web.bw_import_legacy'))
        finally:
            for leftover in (target, *(target.with_name(target.name + suffix) for suffix in ('-wal', '-shm', '-journal'))):
                leftover.unlink(missing_ok=True)       # a WAL-mode upload leaves its sidecars when read
    return redirect(url_for('web.bw_import_plan', plan_id=plan['id']))


@web_page.get('/manage/import-legacy/plan/<plan_id>')
@login_required
def bw_import_plan(plan_id):
    from ..core.importer import bricktracker
    with _db() as db:
        try:
            _, plan = bricktracker.load_plan(db, plan_id)
        except ValueError as exc:
            flash(str(exc), 'warning')
            return redirect(url_for('web.bw_import_legacy'))
    return _render(screen='plan', plan=plan, event=request.args.get('event'))


@web_page.post('/manage/import-legacy/plan/<plan_id>/apply')
@login_required
def bw_import_apply(plan_id):
    from ..core.importer import bricktracker
    from ..core.sources.base import audit_origin
    _guard()
    ticked = set(request.form.getlist('tick'))
    with _db() as db:
        try:
            _, plan = bricktracker.load_plan(db, plan_id)
            decisions = {r['key']: 'add' if r['key'] in ticked else 'skip' for r in plan['rows'] if not r['locked']}
            with audit_origin('app'):
                result = bricktracker.apply(db, plan_id, decisions)
        except (ValueError, sqlite3.Error) as exc:
            flash(public(exc, 'The import could not run · nothing was changed'), 'warning')
            return redirect(url_for('web.bw_import_plan', plan_id=plan_id))
    c = result['counts']
    if result.get('already_applied'):
        flash('This plan was already imported; nothing was added again.', 'info')
        return redirect(url_for('web.bw_import_legacy', event=result['event_id']))
    # Loose items are counted as the preview counts them, by line; the pieces follow in brackets (#145). An older receipt has no line count.
    lines, pieces = c.get('stock_lines'), c.get('stock', 0)
    loose = (f'{lines} loose items ({pieces} pieces)' if lines != pieces else f'{lines} loose items') if lines else (f'{pieces} loose pieces' if pieces else '')
    parts = [f'{c.get("copies", 0)} sets' if c.get('copies') else '', loose, f'{c.get("lots", 0)} lots' if c.get('lots') else '',
             f'{c.get("wishes", 0)} wishes' if c.get('wishes') else '']
    flash('Imported · ' + ' · '.join(p for p in parts if p) if any(c.values()) else 'Nothing was imported.', 'success')
    return redirect(url_for('web.bw_import_legacy', event=result['event_id']))


@web_page.post('/manage/import-legacy/undo')
@login_required
def bw_import_undo():
    from ..core.importer import bricktracker
    _guard()
    event = request.form.get('event', '')
    if not event.isdigit():
        abort(400)
    with _db() as db:
        try:
            bricktracker.undo(db, int(event))
            flash('Import undone.', 'success')
        except (ValueError, sqlite3.Error) as exc:
            flash(public(exc, 'The import could not run · nothing was changed'), 'warning')
    return redirect(url_for('web.bw_import_legacy'))
