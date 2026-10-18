"""Import from BrickTracker (#11 UI): upload an app.db, preview, import into this collection, Undo.

The older path that builds a new database from server paths with a proof report stays available
under "Build a new database instead" (`brickwork migrate` does the same from the CLI).
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import uuid

from flask import abort, current_app, flash, get_flashed_messages, redirect, render_template, request, url_for
from flask_login import login_required

from .views import web_page, bw_add_csrf, bw_add_token, bw_collection_editable

LIMIT_MB = 200
MIGRATE_FIELDS = ('app', 'extras', 'decisions', 'catalogue', 'out', 'report', 'catalogue_src')


def data_paths(form):
    """The migrate form's paths, each inside the database folder, or ValueError (#61).

    A relative path is taken from that folder; an absolute one must already be inside it. Nothing
    outside it is read or written from the browser; the CLI (`brickwork migrate`) takes any path.
    """
    from .admin_ops import brickwork_path
    base = brickwork_path().parent.resolve()
    paths = {}
    for key in MIGRATE_FIELDS:
        value = (form.get(key) or '').strip()
        if not value:
            paths[key] = None
            continue
        path = Path(value)
        path = (path if path.is_absolute() else base / path).resolve()
        if not path.is_relative_to(base):
            raise ValueError('Give paths inside the data folder, for example imports/app.db; '
                             'use brickwork migrate for files elsewhere.')
        paths[key] = str(path)
    return paths


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
            target.unlink(missing_ok=True)
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
            flash(str(exc), 'warning')
            return redirect(url_for('web.bw_import_plan', plan_id=plan_id))
    c = result['counts']
    if result.get('already_applied'):
        flash('This plan was already imported; nothing was added again.', 'info')
        return redirect(url_for('web.bw_import_legacy', event=result['event_id']))
    flash('Imported · ' + ' · '.join(f'{n} {label}' for label, n in (
        ('sets', c.get('copies', 0)), ('loose items', c.get('stock', 0)), ('lots', c.get('lots', 0)), ('wishes', c.get('wishes', 0))) if n)
        if any(c.values()) else 'Nothing was imported.', 'success')
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
            flash(str(exc), 'warning')
    return redirect(url_for('web.bw_import_legacy'))


@web_page.post('/manage/import-legacy/migrate')
@login_required
def bw_import_migrate():
    """The older path: build a new database from server paths, with a proof report."""
    from .admin_ops import migrate
    from ..core.sources.base import redact
    _guard()
    result = error = None
    try:
        result = migrate(**data_paths(request.form))
    except (ValueError, OSError, sqlite3.Error) as exc:
        error = redact(exc)
    except TypeError:
        error = 'Fill in every required file path.'
    return _render(screen='upload', limit=LIMIT_MB, result=result, error=error)
