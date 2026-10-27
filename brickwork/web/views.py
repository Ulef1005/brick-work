"""Brick Work v3 browser routes, backed solely by the core store."""
import re
import sqlite3
import time
from xml.etree import ElementTree as ET
from werkzeug.exceptions import HTTPException

from .safe_errors import public
from flask import Blueprint, abort, current_app, g, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import login_required

web_page = Blueprint('web', __name__)


@web_page.before_request
def bw_read_only_guard():
    """A read-only instance refuses every browser write, as the API does (one rule for all routes)."""
    from ..api import read_only
    # Reads that use POST stay available: a BrickLink XML export of selected copies, and a database
    # check (on a read-only instance it runs read-only and stores nothing).
    if request.endpoint == 'web.bw_planning_write' and (request.view_args or {}).get('action') == 'export':
        return
    if request.endpoint == 'web.bw_admin_write' and (request.view_args or {}).get('page') == 'database':
        return
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and read_only():
        abort(403, 'Changes are switched off on this instance')


@web_page.record_once
def install_ui(state):
    from .ui import install
    install(state.app)


def web_manifest():
    """Root-scoped install metadata; explicit theme follows the persisted picker."""
    import json
    from .ui import ROOT
    data = json.loads((ROOT / 'static/brickwork/manifest.webmanifest').read_text())
    if request.args.get('theme') == 'dark':
        data.update(theme_color='#1A1816', background_color='#1A1816')
    response = jsonify(data)
    response.mimetype = 'application/manifest+json'
    response.headers['Cache-Control'] = 'no-cache'
    return response


def shell_worker():
    """Version the precache by its contents, once per application start."""
    import hashlib
    import json
    import re
    from flask import Response
    from .ui import ROOT
    source = current_app.extensions.get('web_shell_worker')
    if source is None:
        source = (ROOT / 'static/web/toni/sw.js').read_text()
        assets = json.loads(re.search(r'const ASSETS = (\[.*?\]);', source, re.S)[1])
        digest = hashlib.sha256()
        for path in sorted(assets):
            data = (ROOT / path.lstrip('/')).read_bytes()
            digest.update(path.encode('utf-8') + b'\0')
            digest.update(len(data).to_bytes(8, 'big'))
            digest.update(data)
        source = source.replace('__ASSET_VERSION__', digest.hexdigest()[:16])
        current_app.extensions['web_shell_worker'] = source
    response = Response(source, mimetype='text/javascript')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@web_page.get('/manage/tools')
def bw_tools():
    return bw_admin('hub')


@web_page.get('/manage/<page>')
@login_required
def bw_admin(page):
    from . import admin_ops
    titles = {'hub': 'Tools & Admin', 'catalogues': 'Catalogues & keys', 'jobs': 'Jobs',
              'refresh': 'Bulk refresh prices', 'unresolved': 'Unresolved figures',
              'statistics': 'Statistics', 'values': 'Values', 'database': 'Database',
              'settings': 'Settings', 'appearance': 'Appearance', 'about': 'About', 'history': 'Identify history',
              'instructions': 'Instruction files'}
    if page not in titles:
        abort(404)
    if page == 'unresolved':                       # identity admin: M.8i part 2
        from . import ported
        return ported.holding('Unresolved figures', piece='M.8i part 2')
    group = request.args.get('group', 'owners')
    error, data = None, None
    try:
        if page not in ('appearance', 'about'):
            data = admin_ops.tools_read(page, group)
            from ..core.admin import display
            data = display(data)
            if page == 'settings':
                from ..core import currency
                from ..core.admin import database
                with database(admin_ops.brickwork_path(), read_only=True, require_catalogue=False) as rdb:
                    data['currency'] = dict(display=currency.display_currency(rdb), rates=currency.listing(rdb))
                    data['saved'] = settings_undo_offer(rdb, request.args.get('saved', ''))
            if page == 'catalogues':
                from ..core import keys as key_store, secrets as key_secrets
                data['view'] = admin_ops.catalogues_view(data, key_store.field_map(), key_secrets.entry_available(),
                                                         session.pop('bw_key_result', None), request.args.get('replace'))
                # #27: where the database and the media (pictures, PDFs) live, read-only.
                import os
                from ..core.media import root_for
                db_file = admin_ops.brickwork_path().resolve()
                data['view']['paths'] = dict(database=str(db_file), media=str(root_for(db_file) / 'data'),
                                             media_custom=bool(os.environ.get('BW_MEDIA_PATH', '').strip()))
    except (ValueError, sqlite3.Error, OSError):
        error = 'Brick Work database is not available. Check BW_DB_PATH and try again.'
    from ..core.pipeline import STEPS, TYPES
    from ..core.items import KIND_TYPE
    from ..core.admin import SOURCE_STEPS
    from ..core import keys, secrets
    response = current_app.make_response(render_template('web/toni/web/bw_admin.html',
        page=page, title=titles[page], data=data, error=error, group=group,
        steps=SOURCE_STEPS, item_types=sorted(TYPES), type_letters=sorted(KIND_TYPE.values()), csrf_token=bw_add_token(), can_edit=bw_collection_editable(),
        key_fields=keys.field_map(), key_entry=secrets.entry_available()))
    response.headers['Cache-Control'] = 'no-store'
    return response


def settings_undo_offer(db, text):
    """`?saved=<event id>` on the Settings page: the id when that event is a settings save that can still be undone, else None."""
    from . import token_rows
    from ..core import undo as undoing
    identifier = token_rows.event_id(text)
    if identifier is None:
        return None
    found = db.execute(f"SELECT 1 FROM main.event e WHERE e.id=? AND e.entity_kind='settings' AND e.field='save' AND NOT {undoing.undone_sql('e')}",
                       (identifier,)).fetchone()
    return identifier if found else None


@web_page.post('/manage/<page>')
@login_required
def bw_admin_write(page):
    from ..core import errors
    from ..core.sources.base import SourceError
    from flask import flash
    from . import admin_ops
    from ..core.admin import SOURCE_STEPS
    from ..core.pipeline import STEPS, TYPES
    action = request.form.get('action', '')
    failure_label = {
        'catalogues': {'source': 'Source toggle', 'key_save': 'Source key', 'key_test_save': 'Source key', 'key_remove': 'Source key',
                       'key_undo': 'Source key', 'key_test': 'Source key test'}.get(action, 'Catalogues & keys'),
        'settings': 'Picture refresh' if action == 'pictures' else 'Settings',
        'unresolved': 'Figure resolution',
        'refresh': 'Price refresh',
        'jobs': 'Job resume' if action == 'resume' else 'Job retry',
        'values': 'Value ' + {'add': 'add', 'rename': 'rename', 'delete': 'delete'}.get(action, 'save'),
        'instructions': 'Instruction rename' if action == 'rename' else 'Instruction fetch' if action == 'fetch_missing' else 'Instruction upload',
    }.get(page, 'Admin action')
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
        abort(403)
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)
    bw_add_csrf(request.form)
    saved = None
    try:
        if page == 'unresolved':                   # identity admin: M.8i part 2
            from . import ported
            return ported.holding('Unresolved figures', piece='M.8i part 2')
        if page == 'instructions':
            if request.form['action'] == 'fetch_missing':
                if not bw_collection_editable():
                    abort(403, 'Changes are switched off on this instance')
                queued, skipped = admin_ops.tools_write('instruction_fetch')
                bw_start_worker()
                note = f'Queued {len(queued)} identity refreshes'
                if skipped:
                    note += f', {len(skipped)} skipped (no number: {", ".join(skipped[:5])}{" ..." if len(skipped) > 5 else ""})'
                flash(note + ' · This refreshes identities only; no PDFs are downloaded. Upload a PDF to attach one', 'info')
                return redirect(url_for('web.bw_admin', page='instructions'))
            if request.form['action'] == 'rename':
                admin_ops.tools_write('instruction_rename', identifier=int(request.form['id']), label=request.form['label'])
            else:
                upload = request.files['file']
                admin_ops.tools_write('instruction_upload', kind=request.form['item_type'], number=request.form['item_no'],
                    label=request.form['label'], content=upload.stream.read(20 * 1024 * 1024 + 1))
        elif page == 'values':
            admin_ops.tools_write('value', group=request.form['group'], action=request.form['action'],
                identifier=request.form.get('id'), name=request.form.get('name'), confirmed=request.form.get('confirm') == 'yes')
        elif page == 'database':
            if not bw_collection_editable():
                # Read-only instance: check on a read-only connection and report; nothing is stored or audited.
                from ..core import admin as core_admin
                from ..core.admin import database
                with database(admin_ops.brickwork_path(), read_only=True, require_catalogue=False) as db:
                    result = core_admin.check(db)
                findings = len(result['foreign_key_check'])
                ok = core_admin.check_ok(result)
                flash(('Database check: no problems found' if ok else
                       f"Database check: integrity {', '.join(result['integrity_check'][:3])} · {findings} foreign-key findings")
                      + ' · not stored, this instance is read-only', 'success' if ok else 'error')
                return redirect(url_for('web.bw_admin', page='database'))
            admin_ops.tools_write('database_check')
            flash('Database check finished', 'success')
            return redirect(url_for('web.bw_admin', page='database'))
        elif page == 'settings' and request.form.get('action') == 'pictures':
            if not bw_collection_editable():
                abort(403, 'Changes are switched off on this instance')
            try:
                jobs, count = admin_ops.tools_write('pictures', scope=request.form['scope'], kinds=request.form.getlist('types'),
                    expected_count=request.form.get('expected_count') or None)
            except ValueError as exc:                   # written for people: "N items now match, not M"
                flash('Picture refresh · ' + str(exc), 'error')
                return redirect(url_for('web.bw_admin', page='settings') + '#pictures')
            bw_start_worker()
            flash(f'{len(jobs)} picture jobs queued for {count} items · No Undo for picture refresh; existing files are kept', 'success')
            return redirect(url_for('web.bw_admin', page='jobs'))
        elif page == 'settings' and request.form.get('action') in ('display_currency', 'rate', 'ecb'):
            # #39: display currency and exchange rates; stored amounts never change.
            if not bw_collection_editable():
                abort(403, 'Changes are switched off on this instance')
            from ..core import currency
            from ..core.admin import database
            with database(admin_ops.brickwork_path(), require_catalogue=False) as db:
                if request.form['action'] == 'display_currency':
                    flash('Display currency ' + currency.set_display(db, request.form.get('display_currency')), 'success')
                elif request.form['action'] == 'rate':
                    currency.set_rate(db, request.form.get('currency'), request.form.get('per_eur') or None)
                    flash('Rate saved' if request.form.get('per_eur') else 'Rate removed', 'success')
                else:
                    result = currency.fetch_ecb(db)
                    flash(f"ECB rates of {result['as_of']} · {result['updated']} currencies"
                          + (f" · {result['kept_manual']} entered by hand kept" if result['kept_manual'] else ''), 'success')
            return redirect(url_for('web.bw_admin', page='settings') + '#currencies')
        elif page == 'settings' and request.form.get('action') == 'undo':
            if not bw_collection_editable():
                abort(403, 'Changes are switched off on this instance')
            try:
                admin_ops.tools_write('settings_undo', event=int(request.form['event']))
            except errors.BrickWorkError as exc:
                flash('Settings · ' + str(exc), 'error')
            else:
                flash('Settings restored', 'success')
            return redirect(url_for('web.bw_admin', page='settings'))
        elif page == 'settings':
            priority = {}
            for step in SOURCE_STEPS:
                priority[step] = {}
                for kind in ['*', *sorted(TYPES)]:
                    value = request.form.get('priority:' + step + ':' + kind, '').strip()
                    if value:
                        priority[step][kind] = [s.strip() for s in value.split(',')]
            freshness = [(request.form['source:' + n], request.form['kind:' + n], request.form['days:' + n])
                         for n in request.form.getlist('freshness')]
            saved = admin_ops.tools_write('settings', country=request.form['retail_country'], priority=priority, freshness=freshness)
        elif page == 'refresh':
            admin_ops.tools_write('refresh')
            bw_start_worker()
        elif page == 'jobs':
            if not bw_collection_editable():
                abort(403, 'Changes are switched off on this instance')
            job = int(request.form['job'])
            step = request.form.get('step') or None
            if step is not None and step not in STEPS and step != 'fetch':
                raise ValueError('Unknown step')
            # Queue Retry for the same worker used by refresh, without blocking the request.
            if request.form.get('action') == 'resume':
                import json
                from ..core.admin import database
                from ..store4 import jobs as fetch_jobs
                with database(admin_ops.brickwork_path(), read_only=True, require_catalogue=False) as db:
                    saved_job = db.execute("SELECT state FROM job WHERE id=? AND (source='import' OR kind IN (SELECT value FROM json_each(?)))",
                                           (job, json.dumps(sorted(fetch_jobs.KINDS)))).fetchone()
                    if saved_job is None or saved_job['state'] not in ('running', 'waiting_for_budget'):
                        raise ValueError('Job is not interrupted')
            else:
                admin_ops.tools_write('retry_queue', job=job, step=step)
            bw_start_worker()
        elif page == 'catalogues' and request.form['action'] in ('key_save', 'key_test_save', 'key_remove', 'key_test', 'key_undo'):
            if not bw_collection_editable():
                abort(403, 'Changes are switched off on this instance')
            from ..core import keys
            from ..core.sources.base import redact, KeyRejected
            source = request.form.get('source', '')
            try:
                if request.form['action'] == 'key_test_save':
                    # Write-only values, never echoed back: saved, tested once, and restored only if the source refuses the key.
                    values = {f: request.form.get('key:' + f, '') for f in keys.fields(keys.known(source))}
                    outcome = admin_ops.tools_write('key_test_save', source=source, values=values)
                    flash('Saved · The key works' if outcome['tested'] else 'Saved · Not tested: ' + outcome['reason'], 'success')
                    return redirect(url_for('web.bw_admin', page='catalogues'))
                if request.form['action'] == 'key_undo':
                    admin_ops.tools_write('key_undo', source=source, event=int(request.form['event']))
                elif request.form['action'] == 'key_save':
                    # The submitted values are write-only: they are never echoed, flashed or logged.
                    values = {f: request.form.get('key:' + f, '') for f in keys.fields(keys.known(source))}
                    admin_ops.tools_write('key_save', source=source, values=values)
                elif request.form['action'] == 'key_remove':
                    removed = admin_ops.tools_write('key_remove', source=source)
                    session['bw_key_result'] = dict(source=source, state='removed', event=removed.get('event'))
                else:
                    admin_ops.tools_write('key_test', source=source)
                    flash('Source key test · The key works', 'success')
                    return redirect(url_for('web.bw_admin', page='catalogues'))
            except KeyRejected as exc:
                session['bw_key_result'] = dict(source=source, state='rejected', message=redact(exc),
                                                replacement=bool(getattr(exc, 'replacement', False)) and not getattr(exc, 'restore_failed', False),
                                                restore_failed=bool(getattr(exc, 'restore_failed', False)))
                return redirect(url_for('web.bw_admin', page='catalogues'))
            except errors.BrickWorkError as exc:
                flash(failure_label + ' · ' + redact(exc), 'error')
                return redirect(url_for('web.bw_admin', page='catalogues'))
        elif page == 'catalogues':
            if request.form['action'] == 'source':
                admin_ops.tools_write('source', source=request.form['source'], enabled=request.form.get('enabled') == 'yes')
            else:
                abort(400)
        else:
            abort(404)
    except SourceError as exc:
        flash(failure_label + ' · ' + str(exc), 'error')
    except (ValueError, KeyError, TypeError, sqlite3.Error, OSError):
        flash('Nothing was saved. Check the values and try again.', 'error')
    else:
        flash('Saved', 'success')
    target = 'jobs' if page in ('refresh', 'jobs') else page
    extra = {'group': request.form.get('group', 'owners')} if page == 'values' else {'saved': saved} if page == 'settings' and saved else {}
    return redirect(url_for('web.bw_admin', page=target, **extra))


def bw_tokens_render(*, created=None, revoked_event=None, form_error=None, form_name='', form_scopes=('read', 'write'),
                     show_create=False, confirm=None, status=200):
    """The API tokens page. The one-time secret exists only in this response, never in a redirect, flash or log."""
    import uuid
    from . import admin_ops, token_rows
    from ..core import tokens
    from ..core.admin import database
    from ..core.sources.base import now
    error, stored, environment, revoked_name, revoked_undo = None, [], [], None, False
    try:
        with database(admin_ops.brickwork_path(), read_only=True, require_catalogue=False) as db:
            stored, environment = token_rows.rows(tokens.listing(db), now())
            if revoked_event is not None:
                revoked_name, revoked_undo = token_rows.revoked_event(db, revoked_event) or (None, False)
    except (ValueError, sqlite3.Error, OSError):
        error = 'Brick Work database is not available. Check BW_DB_PATH and try again.'
    editable = bw_collection_editable()
    confirm_row = next((r for r in stored if r['id'] == confirm), None) if editable else None
    response = current_app.make_response(render_template('web/toni/web/bw_tokens.html',
        error=error, stored=stored, environment=environment, can_edit=editable, csrf_token=bw_add_token(), created=created,
        revoked_name=revoked_name, revoked_undo=revoked_undo, revoked_event=revoked_event, form_error=form_error, form_name=form_name,
        form_scopes=form_scopes, scope_help=token_rows.SCOPE_HELP, show_create=show_create and editable, confirm_row=confirm_row,
        form_id=uuid.uuid4().hex))
    response.status_code = status
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/manage/tokens')
@login_required
def bw_tokens():
    from . import token_rows
    return bw_tokens_render(revoked_event=token_rows.event_id(request.args.get('revoked', '')),
                            show_create=request.args.get('create') == '1', confirm=request.args.get('revoke'))


@web_page.post('/manage/tokens')
@login_required
def bw_tokens_write():
    from . import admin_ops, token_rows
    from ..core import errors, tokens
    from ..core.admin import database, operation
    from ..core.sources.base import audit_origin
    from flask import flash
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
        abort(403)
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)
    bw_add_csrf(request.form)
    if not bw_collection_editable():
        abort(403, 'Changes are switched off on this instance')
    action = request.form.get('action', '')
    if action not in ('create', 'revoke', 'undo'):
        abort(400)
    try:
        with database(admin_ops.brickwork_path(), require_catalogue=False) as db, audit_origin('app'):
            if action == 'create':
                scopes = request.form.getlist('scopes')
                # Reloading the page that showed a secret resends this form: answer, do not create again (#68). The form id is the
                # operation key of the request that created the token, so "already sent" is read from that token's event.
                form_id = request.form.get('form_id', '')
                if not re.fullmatch(r'[0-9a-f]{32}', form_id or ''):
                    form_id = ''
                if form_id:
                    if db.execute("SELECT 1 FROM main.event WHERE entity_kind='bw_token' AND field='create' AND operation_key=?", (form_id,)).fetchone():
                        return bw_tokens_render(form_error='This form was already sent: the token exists, and its secret is shown only once.',
                                                status=409)
                try:
                    with operation(form_id or None):
                        created, _ = tokens.create(db, request.form.get('name', ''), scopes)
                except errors.BrickWorkError as exc:
                    return bw_tokens_render(form_error=str(exc), form_name=request.form.get('name', ''), form_scopes=scopes,
                                            show_create=True, status=getattr(exc, 'status', 400))
                return bw_tokens_render(created=created)
            if action == 'revoke':
                _, event = tokens.revoke(db, request.form.get('id', ''))
                return redirect(url_for('web.bw_tokens', revoked=event))
            identifier = token_rows.event_id(request.form.get('event', ''))
            if identifier is None:
                abort(400, 'Invalid event')
            found = db.execute("SELECT field,old_value,new_value,at FROM main.event WHERE id=? AND entity_kind='bw_token' AND field IN ('create','revoke')", (identifier,)).fetchone()
            if found and not token_rows.undoable(found):
                abort(400, 'This token change cannot be undone')
            if found and not token_rows.recent(found):
                abort(400, 'Undo is no longer available for this token change')
            response, _, _ = tokens.undo(db, identifier)
            flash('Token restored' if found and found['field'] == 'revoke' and not response.get('already_undone') else response.get('message', 'Done'), 'success')
            return redirect(url_for('web.bw_tokens'))
    except (errors.BrickWorkError, ValueError) as exc:
        flash(str(exc) or 'Nothing was saved. Try again.', 'error')
    except sqlite3.Error:
        flash('Nothing was saved. Try again.', 'error')
    return redirect(url_for('web.bw_tokens'))


def bw_start_worker():
    """One background drainer per app; database claims exclude other processes."""
    from . import admin_ops
    from ..core import drainer
    app = current_app._get_current_object()
    if not drainer.enabled():
        from flask import flash, has_request_context
        if has_request_context():
            flash('Queued. Run the import worker to continue.', 'info')
        return False
    return drainer.start(app, admin_ops.brickwork_path())


def bw_resume_imports(app):
    """Resume durable fetch jobs when the standalone app starts (a refused file, such as a 3.3 one, stops the start with its message)."""
    from .admin_ops import brickwork_path
    from ..core.admin import database
    with app.app_context():
        path = brickwork_path()
        if not path.is_file():
            return
        from ..core import drainer
        with database(path, read_only=True, require_catalogue=False) as db:
            pending = drainer.pending(db)
        if pending:
            bw_start_worker()


@web_page.get('/manage/database/export')
@login_required
def bw_export():
    from .admin_ops import tools_export
    from flask import Response
    try:
        content = tools_export()
    except (ValueError, sqlite3.Error, OSError):
        from flask import flash
        flash('Export could not be completed. Check the database and try again.', 'error')
        return redirect(url_for('web.bw_admin', page='database'))
    return Response(content, mimetype='application/vnd.sqlite3',
                    headers={'Content-Disposition': 'attachment; filename=brickwork.db', 'Cache-Control': 'no-store'})


@web_page.get('/manage/images/<int:image_id>')
@web_page.get('/manage/images/<image_id>')
@login_required
def bw_image(image_id):
    """A picture of an item (`picture`, a cache: a number) or an own photo (`photo`: a hex text that is never all digits), by file.

    Pictures are fetched by the pipeline's `pictures` step (`core.pictures`): a number with no row answers 404, like a row whose file is gone."""
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.media import root_for
    from flask import send_file
    path = brickwork_path()
    image_id = str(image_id)
    own = not image_id.isdigit()
    if own and not re.fullmatch(r'[0-9a-f]{32}', image_id):
        abort(404)
    with database(path, read_only=True) as db:
        row = (db.execute('SELECT local_path FROM photo WHERE id=? AND archived_at IS NULL', (image_id,)) if own
               else db.execute('SELECT local_path FROM picture WHERE id=?', (int(image_id),))).fetchone()
    if not row:
        abort(404)
    root = root_for(path)
    target = (root / row[0]).resolve()
    if not target.is_relative_to(root / 'data/images') or not target.is_file():
        abort(404)
    width = request.args.get('w')
    mimetype = None
    if width is not None:
        from ..core import thumbnails
        if width not in {str(w) for w in thumbnails.WIDTHS}:
            abort(400)
        if own:                                                         # the original of an own photo is what is shown, at any width
            width = None
    if width is not None:
        target, mimetype = thumbnails.lookup(root, int(image_id), int(width), target)
    response = send_file(target, mimetype=mimetype, max_age=86400)
    response.cache_control.public = None
    response.cache_control.private = True
    return response


@web_page.get('/manage/instructions/<int:identifier>/download')
@login_required
def bw_instruction_download(identifier):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.media import root_for
    from flask import send_file
    path = brickwork_path()
    with database(path, read_only=True) as db:
        row = db.execute('SELECT path FROM instruction_file WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone()
    if not row:
        abort(404)
    root = root_for(path)
    target = (root / row[0]).resolve()
    if not target.is_relative_to(root / 'data/instructions') or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name='instructions.pdf')


# Brick Work Add: browser writes use the shared core.
def bw_add_signer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.secret_key, salt='brickwork-add-review')


def _media(path):
    from ..core.media import root_for
    return root_for(path)


def _ledger():
    from ..core import ledger
    return ledger


def bw_add_token():
    from flask import session
    import secrets
    session.setdefault('bw_add_csrf', secrets.token_hex(32))
    return session['bw_add_csrf']


def bw_add_csrf(data):
    import hmac
    if not hasattr(data, 'get'):
        abort(400, 'Send a JSON object')
    token = data.get('csrf_token', '')
    if not isinstance(token, str) or not hmac.compare_digest(token, bw_add_token()):
        abort(400, 'Invalid CSRF token')


def _add_database(read_only=False):
    """The collection for the Add screens. Opened without insisting on a catalogue, so a missing or inactive one is answered with the fix
    (`add.require_catalogue`) instead of a failed request."""
    from .admin_ops import brickwork_path
    from ..core.admin import database
    return database(brickwork_path(), read_only=read_only, require_catalogue=False)


@web_page.get('/manage/add')
@login_required
def bw_add():
    from ..core import add
    from ..core.errors import CatalogueNotLoaded
    error, colours, lists = None, [], []
    try:
        with _add_database(read_only=True) as db:
            colours, lists = add.colors(db), add.wishlists(db)
            try:
                add.require_catalogue(db)
            except CatalogueNotLoaded as exc:
                error = str(exc)
    except (ValueError, sqlite3.Error, OSError):
        error = 'Brick Work database is not available. Check BW_DB_PATH and try again.'
    from ..core import items
    asked = request.args.get('type', '')
    asked = items.TYPE_KIND.get(asked, asked) if len(asked) == 1 else asked          # old links carry the BrickLink letter
    response = current_app.make_response(render_template('web/toni/web/bw_add.html', initial_kind=asked if asked in add.KIND_NAMES else 'set',
        kinds=add.KIND_NAMES, colours=colours, wishlists=lists, error=error, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/manage/add/search')
@login_required
def bw_add_search():
    from ..core.add import search
    try:
        with _add_database(read_only=True) as db:
            result = search(db, request.args.get('type', 'set'), request.args.get('q', '')[:100], request.args.get('sort', 'number'))
    except (ValueError, sqlite3.Error, OSError) as error:
        return jsonify(error=public(error, 'Catalogue is not available')), 400
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/manage/add/review')
@login_required
def bw_add_review():
    import base64
    import json
    import uuid
    from ..core import add, identify
    from ..core.sources.brickognize import photo_bytes
    from ..core.sources.base import audit_origin, SourceError
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    bw_add_csrf(data)
    kind, where, mode = data.get('type', 'set'), data.get('where', 'owned'), data.get('mode', 'paste')
    if kind not in add.KIND_NAMES:
        abort(400, 'Choose an item type')
    photo = None
    try:
        with _add_database() as db, audit_origin('app'):
            if mode == 'paste':
                rows = add.paste(data.get('text', '')[:100000], kind)
            elif mode == 'file':
                upload = request.files.get('file')
                if not upload:
                    raise ValueError('Choose a file')
                raw = upload.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError('Choose a file smaller than 2 MB')
                rows = add.file_rows(raw, upload.filename or '', kind)
            elif mode == 'search':
                rows = data.get('items', [])
                if not isinstance(rows, list):
                    raise ValueError('Choose items from the search')
            elif mode == 'photo':
                upload = request.files.get('file')
                if not upload:
                    raise ValueError('Choose a photo')
                photo = photo_bytes(upload.read(8 * 1024 * 1024 + 1))
                choices, missed = identify.recognise(db, photo, kind if kind in ('part', 'minifigure') else None, kinds=('part', 'minifigure', 'set'))
                if not choices:
                    raise ValueError('Nothing identified · try another photo')
                rows = [dict(item_id=c['item_id'], quantity=1, score=c['score']) for c in choices]
            else:
                raise ValueError('Choose how to add')
            proposal = add.resolve(db, rows, where, list_id=data.get('list_id') or 'default',
                                   map_wanted_ids=data.get('map_wanted_ids', 'true') not in (False, 'false'))
            if photo:
                scores = {r['item_id']: r['score'] for r in rows}
                for row in proposal['items']:
                    row['score'] = scores.get(row['item_id'])
                proposal['unresolved'] += [dict(number=m['item_no'], reason=m['reason']) for m in missed]
            token = bw_add_signer().dumps(dict(**proposal, batch=uuid.uuid4().hex, owner=bw_add_token(), mode=mode,
                                               photo=base64.b64encode(photo).decode() if photo else None))
        return jsonify(**proposal, token=token, candidates=mode == 'photo')
    except (ValueError, SourceError, sqlite3.Error, OSError, UnicodeError, json.JSONDecodeError, ET.ParseError) as error:
        return jsonify(error=public(error, 'Could not read this input')), 400


def _add_receipt_view(receipt):
    """What the page needs of a receipt: no row snapshots."""
    keys = ('batch', 'index', 'item_id', 'kind', 'where', 'quantity', 'name', 'label', 'copies', 'job_id', 'fetch_job', 'pending', 'event_id')
    view = {k: receipt.get(k) for k in keys}
    view['stock'] = (receipt.get('stock') or {}).get('id')
    view['wish'] = (receipt.get('wish') or {}).get('id')
    return view


@web_page.post('/manage/add/confirm')
@login_required
def bw_add_confirm():
    import base64
    from itsdangerous import BadSignature
    from ..core import add
    from ..core.sources.base import audit_origin
    data = request.get_json(silent=True) or {}
    bw_add_csrf(data)
    proposal = None
    try:
        proposal = bw_add_signer().loads(data.get('token', ''), max_age=3600)
        if proposal['owner'] != bw_add_token():
            raise ValueError('Review this input again')
        original = proposal['items']
        if proposal.get('mode') == 'photo':                # a photo offers candidates; the person chooses one first
            selected = data.get('candidate')
            if type(selected) is not int or not 0 <= selected < len(original):
                raise ValueError('Choose a photo candidate first')
            original = [original[selected]]
        with _add_database() as db, audit_origin('app'):
            rows = add.validate_edits(db, original, data.get('items'), batch=proposal['batch'])
            receipts = add.confirm(db, rows, batch=proposal['batch'], photo=base64.b64decode(proposal['photo']) if proposal.get('photo') else None,
                                   keep_photo=data.get('keep_photo') is True)
        if receipts:
            bw_start_worker()
        return jsonify(receipts=[_add_receipt_view(r) for r in receipts], batch=proposal['batch'])
    except (BadSignature, ValueError, sqlite3.Error, OSError, TypeError, KeyError) as error:
        saved = []
        if proposal and proposal.get('owner') == bw_add_token():
            try:
                with _add_database(read_only=True) as db:
                    saved = add.receipts(db, proposal['batch'])
            except (ValueError, sqlite3.Error, OSError):
                pass
        if saved:
            bw_start_worker()
        message = (f'{len(saved)} items added · try again to finish this review' if saved else
                   public(error, 'Could not add · check the review and try again'))
        return jsonify(error=message, receipts=[_add_receipt_view(r) for r in saved]), 400


@web_page.post('/manage/add/undo')
@login_required
def bw_add_undo():
    from ..core.add import undo
    data = request.get_json(silent=True) or {}
    bw_add_csrf(data)
    if not isinstance(data.get('batch'), str):
        abort(400)
    try:
        with _add_database() as db:
            undo(db, data['batch'])
    except ValueError as exc:
        return jsonify(error=public(exc, 'Could not undo · try again')), 400
    return jsonify(message='Undone')


@web_page.get('/manage/add/jobs/<int:job>')
@login_required
def bw_add_job(job):
    with _add_database(read_only=True) as db:
        snapshot = db.execute('SELECT state FROM job WHERE id=?', (job,)).fetchone()
        if snapshot is None:
            abort(404)
        steps = db.execute('SELECT * FROM job_step WHERE job_id=? ORDER BY position', (job,)).fetchall()
        from ..core import add
        fetch = add.fetch_outcome(db, job)           # a Fetch from Rebrickable job says what became of the Add row that asked for it
    # Only the safe step contract is returned; raw payloads and source keys stay server-side.
    done = sum(s['state'] == 'done' for s in steps)
    # The progress widget speaks started/progress/waiting/failed/done.
    shown = {'waiting_for_budget': 'waiting', 'running': 'progress', 'queued': 'started'}
    events = [dict(job_id=job, step=s['name'], state=shown.get(s['state'], s['state']),
        completed_steps=done, total_steps=len(steps), count=s['count'], total=s['total'],
        job_state=snapshot['state'], retry=s['state'] == 'failed',
        message=s['error'] if s['state'] == 'failed' or (s['state'] == 'done' and s['error']) else 'Waiting for budget' if s['state'] == 'waiting_for_budget' else 'Importing · ' + s['name']) for s in steps]
    events.append(dict(job_id=job, step=None, state=snapshot['state'], completed_steps=done,
        total_steps=len(steps), message=fetch['message'] if fetch and fetch['state'] != 'waiting' else 'Import complete' if snapshot['state'] == 'done' else 'Import needs attention' if snapshot['state'] == 'failed' else 'Waiting for budget' if snapshot['state'] == 'waiting_for_budget' else 'Import queued'))
    response = jsonify(events=events)
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/manage/add/jobs/<int:job>/retry')
@login_required
def bw_add_retry(job):
    from ..core.pipeline import Pipeline
    from ..core.sources.base import audit_origin
    data = request.get_json(silent=True) or {}
    bw_add_csrf(data)
    try:
        from ..store4 import jobs as fetch_jobs
        with _add_database() as db, audit_origin('app'):
            row = db.execute('SELECT kind FROM main.job WHERE id=?', (job,)).fetchone()
            if row is not None and row['kind'] in fetch_jobs.KINDS:      # a fetch job of store4's runner (Fetch from Rebrickable)
                fetch_jobs.requeue(db, job)
            else:
                Pipeline(db).queue_retry(job, data.get('step'))
        bw_start_worker()
        return jsonify(message='Queued')
    except ValueError:
        return jsonify(error='Could not retry this import'), 400


@web_page.get('/workbench/check-parts')
@login_required
def bw_check_parts():
    from .admin_ops import brickwork_path
    from ..core import checker
    from ..core.admin import database
    error, copies = None, []
    try:
        with database(brickwork_path(), read_only=True) as db:
            copies = checker.choices(db)
    except (ValueError, sqlite3.Error, OSError):
        error = 'Brick Work database is not available. Check BW_DB_PATH and try again.'
    response = current_app.make_response(render_template('web/toni/web/bw_checker.html', copies=copies, state=None, error=error, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/workbench/check-parts/<copy_id>')
@login_required
def bw_check_copy(copy_id):
    from .admin_ops import brickwork_path
    from ..core import checker
    from ..core.admin import database
    try:
        with database(brickwork_path(), read_only=True) as db:
            state = checker.view(db, copy_id)
    except ValueError as error:
        abort(404, str(error))
    response = current_app.make_response(render_template('web/toni/web/bw_checker.html', state=state, error=None, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/workbench/check-parts/<copy_id>/figure/<int:copy_figure_id>')
@login_required
def bw_check_figure(copy_id, copy_figure_id):
    """Check figure parts: one whole figure line's own parts inside a copy (4.8a)."""
    from .admin_ops import brickwork_path
    from ..core import checker
    from ..core.admin import database
    try:
        with database(brickwork_path(), read_only=True) as db:
            state = checker.figure_view(db, copy_id, copy_figure_id)
    except ValueError as error:
        abort(404, str(error))
    response = current_app.make_response(render_template('web/toni/web/bw_checker.html', state=state, error=None, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/workbench/part-picker')
@login_required
def bw_picker():
    return bw_workbench_page('picker')


@web_page.get('/workbench/matcher')
@web_page.get('/workbench/match')
@login_required
def bw_matcher():
    return bw_workbench_page('matcher')


def bw_workbench_page(mode):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import workbench
    rows, copies, history, selected, error = [], [], [], request.args.getlist('copy'), None
    match_groups = []
    ranking = request.args.getlist('rank') if request.args.get('ranked') else list(workbench.PICKER_DEFAULT)
    rank_keys = []
    try:
        with database(brickwork_path(), read_only=True) as db:
            all_gaps = workbench.gaps(db)
            by_copy = {}
            for row in (r for r in all_gaps if r['target'] == 'part'):
                copy = by_copy.setdefault(row['copy_id'], dict(row['copy'], missing=0))
                copy['missing'] += row['need']
            copies = list(by_copy.values())
            rows = workbench.picker(db, selected, ranking, all_gaps=all_gaps) if mode == 'picker' else workbench.matches(db, all_gaps=all_gaps)
            if mode == 'picker':
                rank_keys = workbench.picker_keys(rows)
            if mode == 'matcher':
                match_groups = workbench.group_matches(db, rows, all_gaps)
            history = workbench.history(db)
    except (ValueError, sqlite3.Error, OSError):
        error = 'Brick Work database is not available. Check BW_DB_PATH and try again.'
    response = current_app.make_response(render_template('web/toni/web/bw_workbench.html', mode=mode,
        rows=rows, ranking=ranking, rank_keys=rank_keys, picking=request.args.get('pick') == '1', match_groups=match_groups, copies=copies,
        selected=selected, history=history, error=error, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/workbench/check-parts/<copy_id>')
@login_required
def bw_check_write(copy_id):
    return bw_check_save(copy_id)


@web_page.post('/workbench/check-parts/<copy_id>/figure/<int:copy_figure_id>')
@login_required
def bw_check_figure_write(copy_id, copy_figure_id):
    return bw_check_save(copy_id, copy_figure_id)


def bw_check_save(copy_id, figure=None):
    import uuid
    from .admin_ops import brickwork_path
    from ..core import checker
    from ..core.admin import database
    origin = request.headers.get('Origin')
    if (origin and origin.rstrip('/') != request.host_url.rstrip('/')) or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)
    payload = request.get_json(silent=True) if request.is_json else dict(request.form)
    if not isinstance(payload, dict):
        return jsonify(error='Choose a checker action'), 400
    bw_add_csrf(payload)
    payload.pop('csrf_token', None)
    if not request.is_json:
        payload['operation'] = uuid.uuid4().hex
        if payload.get('action') not in ('start', 'restart'):
            abort(400)
    back = url_for('web.bw_check_figure', copy_id=copy_id, copy_figure_id=figure) if figure else url_for('web.bw_check_copy', copy_id=copy_id)
    try:
        with database(brickwork_path()) as db:
            state = checker.write(db, copy_id, payload, figure)
    except (ValueError, sqlite3.Error, OSError) as error:
        message = public(error, 'The answer could not be saved. Retry.')
        if not request.is_json:
            flash(message, 'bw-checker')
            return redirect(back)
        return jsonify(error=message), 409
    if not request.is_json:
        return redirect(back if figure else url_for('web.bw_check_copy', copy_id=copy_id, run=1))
    response = jsonify(state=state)
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/workbench/save/<action>')
@login_required
def bw_workbench_save(action):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import workbench
    data = request.get_json(silent=True) or {}
    bw_add_csrf(data)
    try:
        with database(brickwork_path()) as db:
            if action == 'transfer':
                event = workbench.transfer(db,data['source_id'],data['copy_id'],data['target'],data['target_id'],data['quantity'])
            elif action == 'found':
                event = workbench.found(db,int(data['item_id']),data['color_id'],data['destination'],data.get('assignments',{}),data['quantity'])
            elif action == 'booklets':
                event = workbench.booklets(db,data['text'],data['quantity'])
            elif action == 'undo':
                workbench.undo(db,int(data['event_id']))
                return jsonify(message='Undone')
            else:
                abort(404)
        return jsonify(message='Saved',event_id=event)
    except ValueError as error:
        if action == 'booklets':
            return jsonify(message=public(error, 'Nothing was saved · review the values and try again')),400
        return jsonify(message='Nothing was saved · stock or missing count may have changed. Review and try again.'),400
    except (KeyError,TypeError,sqlite3.Error):
        return jsonify(message='Nothing was saved · stock or missing count may have changed. Review and try again.'),400


@web_page.get('/workbench/part-to-inventory')
@login_required
def bw_inventory():
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.part_inventory import options
    error, data = None, dict(colours=[], lots=[], storages=[])
    try:
        with database(brickwork_path(), read_only=True) as db:
            data = options(db)
    except (ValueError, sqlite3.Error) as exc:
        error = public(exc, 'Brick Work database is not available. Check BW_DB_PATH and try again.')
    response = current_app.make_response(render_template('web/toni/web/bw_inventory.html', **data, error=error, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


def bw_ledger_payload():
    origin=request.headers.get('Origin')
    if (origin and origin.rstrip('/') != request.host_url.rstrip('/')) or request.headers.get('Sec-Fetch-Site')=='cross-site':
        abort(403)
    data=request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(data,dict):
        abort(400,'Choose valid form values')
    bw_add_csrf(data)
    return data


@web_page.get('/workbench/orders')
@login_required
def bw_orders():
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import orders
    error = None
    rows = []
    try:
        with database(brickwork_path(), read_only=True) as db:
            rows = orders.listing(db)
    except (ValueError, sqlite3.Error) as exc:
        error = public(exc, 'Brick Work database is not available. Check BW_DB_PATH and try again.')
    response = current_app.make_response(render_template('web/toni/web/bw_orders.html', rows=rows, detail=None, error=error, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/workbench/orders/<int:order_id>')
@login_required
def bw_order(order_id):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import orders, ledger, add
    try:
        with database(brickwork_path(), read_only=True) as db:
            data = orders.detail(db, order_id)
            rows = orders.listing(db)
            data['destinations'] = orders.destinations(db, data['saved'])
            data['colours'] = add.colors(db)
            data['storages'] = ledger.storages(db)
            data['lots'] = [dict(r) for r in db.execute('SELECT id,name FROM lot WHERE archived_at IS NULL ORDER BY name')]
    except (ValueError, sqlite3.Error):
        abort(404)
    order_view = request.args.get('view', 'detail')
    if order_view not in ('detail', 'count', 'allocation', 'history'):
        order_view = 'detail'
    response = current_app.make_response(render_template(
        'web/toni/web/bw_orders.html', rows=rows, detail=data,
        order_phase=next(r['phase'] for r in rows if r['id'] == order_id),
        order_view=order_view, error=None, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/workbench/part-to-inventory/detect')
@login_required
def bw_inventory_detect():
    import base64
    import uuid
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import identify
    from ..core.sources.brickognize import photo_bytes
    from ..core.sources.base import audit_origin, SourceError
    bw_add_csrf(request.form)
    try:
        upload = request.files.get('file')
        if not upload:
            raise ValueError('Choose a photo')
        photo = photo_bytes(upload.read(8 * 1024 * 1024 + 1))
        endpoint = request.form.get('endpoint', 'parts')
        if endpoint not in ('parts', 'figs'):
            raise ValueError('Choose parts or figures')
        with database(brickwork_path()) as db, audit_origin('app'):
            choices, unresolved = identify.recognise(db, photo, {'parts': 'part', 'figs': 'minifigure'}[endpoint])
        if not choices:
            return jsonify(error='Nothing identified · try another photo', unresolved=unresolved), 400
        proposal = dict(id=uuid.uuid4().hex, owner=bw_add_token(), candidates=choices, photo=base64.b64encode(photo).decode())
        return jsonify(candidates=choices, unresolved=unresolved, token=bw_add_signer().dumps(proposal))
    except (ValueError, SourceError, sqlite3.Error, OSError) as exc:
        return jsonify(error=public(exc, 'Could not recognise this photo')), 400


@web_page.post('/workbench/part-to-inventory/save')
@login_required
def bw_inventory_save():
    import hashlib
    from itsdangerous import BadSignature, SignatureExpired
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import part_inventory
    data = request.get_json(silent=True) or {}
    bw_add_csrf(data)
    try:
        if not isinstance(data.get('pieces'), list) or not 1 <= len(data['pieces']) <= 6:
            raise ValueError('Review between 1 and 6 pieces')
        pieces = []
        for piece in data['pieces']:
            proposal = bw_add_signer().loads(piece['token'], max_age=3600)
            if proposal['owner'] != bw_add_token():
                raise ValueError('Review these photos again')
            pieces.append(dict(**proposal, chosen=piece['chosen']))
        if data.get('destination') == 'lot' and not (data.get('lot_id') or data.get('new_lot')):
            raise ValueError('Choose a lot or create one')
        ids = sorted(p['id'] for p in pieces)
        if len(set(ids)) != len(ids):
            raise ValueError('A piece can only be added once')
        batch = hashlib.sha256('|'.join(ids).encode()).hexdigest()
        with database(brickwork_path()) as db:
            event = part_inventory.save(db, pieces, batch=batch, condition=data.get('condition', 'U'), lot_id=data.get('lot_id'), new_lot=data.get('new_lot'), keep_photos=data.get('keep_photos', True) is True)
            created = None
            if data.get('new_lot'):
                row = db.execute("SELECT l.id, l.name, substr(l.created_at,1,10) AS created_date FROM main.event e JOIN main.lot l ON l.id = json_extract(e.new_value, '$.lot') WHERE e.id = ?", (event,)).fetchone()
                created = dict(row) if row else None
        return jsonify(event=event, message='Receipts saved. Batch added.', lot=created)
    except SignatureExpired:
        return jsonify(error='This batch expired after an hour · identify the pieces again'), 400
    except (BadSignature, ValueError, KeyError, TypeError, sqlite3.Error, OSError):
        return jsonify(error='Could not add this batch · review the pieces and destination'), 400


@web_page.post('/workbench/part-to-inventory/undo')
@login_required
def bw_inventory_undo():
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.part_inventory import undo
    data = request.get_json(silent=True) or {}
    bw_add_csrf(data)
    try:
        with database(brickwork_path()) as db:
            undo(db, int(data.get('event', 0)))
        return jsonify(message='Undone')
    except (ValueError, TypeError, sqlite3.Error) as exc:
        return jsonify(error=public(exc, 'Nothing was saved · review the values and try again')), 400
@web_page.post('/workbench/orders/action/<action>')
@login_required
def bw_orders_action(action):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import orders
    from ..core.sources.base import audit_origin, SourceError
    data = bw_ledger_payload()
    try:
        with database(brickwork_path()) as db, audit_origin('app'):
            if action == 'placed':
                from ..core.sources.bricklink import BrickLink
                imported = {str(row['bricklink_order_id']) for row in orders.listing(db)}
                placed = BrickLink(db).list_orders()
                return jsonify(orders=[dict(number=str(row['order_id']), store=row.get('store_name') or row.get('seller_name') or 'Store not recorded', date=row.get('date_ordered') or '', imported=str(row['order_id']) in imported) for row in placed])
            elif action == 'import':
                text = data.get('text', '')
                upload = request.files.get('file')
                if upload:
                    text = upload.read(1024 * 1024 + 1).decode('utf-8-sig')
                result = orders.import_document(db, data['source'], text, choice=data.get('choice', 'new'), number=data.get('number'), label=upload.filename if upload else None)
                return jsonify(**result, message='Already imported · open the existing order' if result['duplicate'] else 'Draft saved · review the lines', url=url_for('web.bw_order', order_id=result['order_id']))
            elif action == 'match':
                event = orders.match(db, int(data['order_id']), int(data['line_id']), item_id=int(data['item_id']) if data.get('item_id') not in (None, '') else None,
                                     color_id=data.get('color_id'), item_type=data.get('item_type'), item_no=data.get('item_no'))
            elif action in ('review', 'reopen', 'save'):
                event = orders.phase(db, int(data['order_id']), int(data['document_id']), action, data.get('pairs'))
            elif action == 'received':
                event = orders.received(db, int(data['order_id']), data['counts'])
            elif action == 'allocate':
                event = orders.allocate(db, int(data['order_id']), data['chosen'])
            elif action == 'hold':
                event = orders.hold(db, int(data['order_id']), int(data['line_id']), data['held'])
            elif action == 'reconcile':
                event = orders.reconcile(db, int(data['order_id']))
            elif action == 'undo':
                orders.undo_history(db, int(data['event_id']))
                return jsonify(message='Undone')
            else:
                abort(404)
        return jsonify(message='Saved', event_id=event)
    except (ValueError, KeyError, TypeError, sqlite3.Error, SourceError, UnicodeError) as exc:
        return jsonify(message=public(exc, 'Nothing was saved · review the values and try again')), 400


@web_page.get('/workbench/orders/<int:order_id>/short.xml')
@login_required
def bw_order_short(order_id):
    import json
    from urllib.parse import quote
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.orders import short_export
    with database(brickwork_path(), read_only=True) as db:
        try:
            result = short_export(db, order_id)
        except ValueError:
            abort(404)
    response = current_app.response_class(result['xml'], mimetype='application/xml')
    response.headers['Content-Disposition'] = 'attachment; filename="order-short.xml"'
    response.headers['Cache-Control'] = 'no-store'
    if result['skipped']:                                  # a line BrickLink cannot name is left out and said so (M.8g's header)
        response.headers['X-Bw-Skipped'] = quote(json.dumps(result['skipped'], separators=(',', ':')))
    return response


@web_page.get('/workbench/storage')
@web_page.get('/workbench/storage/<identifier>')
@login_required
def bw_storages(identifier=None):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import ledger
    error, rows, detail, history = None, [], None, []
    explicit = bool(identifier)
    try:
        with database(brickwork_path(), read_only=True) as db:
            rows = ledger.storages(db)
            places = [r for r in rows if r['id']]
            # 12c: the first storage is selected until another is chosen; with none, the empty state.
            if identifier:
                detail = ledger.storage_view(db, None if identifier == 'unstored' else identifier, rows)
            elif places:
                detail = ledger.storage_view(db, places[0]['id'], rows)
            history = ledger.history(db, actions=('storage', 'move', 'archive'))
    except (ValueError, sqlite3.Error) as exc:
        error = public(exc, 'Brick Work database is not available. Check BW_DB_PATH and try again.')
    response = current_app.make_response(render_template('web/toni/web/bw_storage.html', rows=rows, detail=detail, explicit=explicit, history=history, error=error, csrf_token=bw_add_token(),
        storage_types=_ledger().STORAGE_TYPES))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/workbench/storage/action/<action>')
@login_required
def bw_storage_action(action):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import ledger
    data = bw_ledger_payload()
    try:
        with database(brickwork_path()) as db:
            if action == 'save':
                extra = {k: data[k] for k in ('type', 'parent_id', 'note') if k in data}
                identifier, event = ledger.storage_save(db, data.get('id'), data['name'], **extra)
                return jsonify(message='Saved', event_id=event, url=url_for('web.bw_storages', identifier=identifier))
            elif action == 'place_kind':
                event = ledger.place_kind(db, data['id'], data.get('kind'))
            elif action == 'move':
                event = ledger.move(db, data.get('storage_id') or None, data['selections'])
            elif action == 'archive':
                event = ledger.storage_archive(db, data['id'], move_to_unstored=data.get('move_to_unstored') in (True, 'yes'))
                return jsonify(message='Location archived', event_id=event, url=url_for('web.bw_storages'))
            elif action == 'undo':
                ledger.undo_history(db, int(data['event_id']))
                return jsonify(message='Undone')
            else:
                abort(404)
        return jsonify(message='Saved', event_id=event)
    except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        return jsonify(message=public(exc, 'Nothing was saved · review the values and try again')), 400


@web_page.get('/collection/sets')
@login_required
def bw_sets():
    return bw_collection('S')


@web_page.get('/collection/<kind>')
@login_required
def bw_collection(kind):
    from . import ui
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    from ..core.connect import NoCatalogue
    from . import setup_state
    kind = kind.upper()
    if kind not in collection.TYPES:
        abort(404)
    error = None
    rows, choices = [], dict(storages=[], places=[], lots=[], flags=[], colours=[])
    try:
        if brickwork_path().is_file():                                 # no file yet: the first-run page, as with no catalogue
            with database(brickwork_path(), read_only=True) as db:
                rows = collection.listing(db, kind)
                choices = collection.options(db)
    except NoCatalogue:
        pass                                                           # first run: the page says how to get a catalogue
    except (sqlite3.Error, OSError, ValueError) as exc:
        error = public(exc, 'Brick Work database is not available. Check BW_DB_PATH and try again.')
    response = current_app.make_response(render_template('web/toni/web/bw_collection.html',
        title=collection.TYPES[kind], kind=kind, rows=rows, records=ui.bw_collection_records(rows), choices=choices, error=error,
        csrf_token=bw_add_token(), can_edit=bw_collection_editable(), detail=None,
        first_run=setup_state.first_run(bw_collection_editable()) if kind == 'S' and not rows and not error else None))
    response.headers['Cache-Control'] = 'no-store'
    return response


def bw_collection_editable():
    from ..api import read_only
    from .auth import LoginManager
    return not read_only() and LoginManager.is_authenticated()


@web_page.get('/collection/item/<int:item_id>')
@login_required
def bw_collection_item(item_id):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    from ..store4.connect import has_catalogue
    try:
        colour_arg = request.args.get('colour')
        with database(brickwork_path(), read_only=True) as db:
            moved = db.execute('SELECT new_id FROM item_redirect WHERE old_id=?', (item_id,)).fetchone()
            if moved:                                                      # a merged item answers with the item it was merged into (design 3.6)
                from .ui import passthrough_args
                return redirect(url_for('web.bw_collection_item', item_id=moved[0], **passthrough_args('item_id')), 301)
            try:
                colour = (collection.NO_COLOUR if colour_arg == 'none' else int(colour_arg)) if colour_arg else None   # 3.3's "no colour" is colour 1
            except ValueError:
                abort(404, 'Colour is unavailable')
            row = db.execute('SELECT kind FROM item WHERE id=?', (item_id,)).fetchone() or (
                db.execute('SELECT kind FROM catalogue.item WHERE id=?', (item_id,)).fetchone() if has_catalogue(db) else None)
            if row is None:
                abort(404, 'Item is unavailable')
            letter = collection.type_of(row['kind'])
            g.bw_nav_type = letter
            colour_choices = collection.part_colours(db, item_id) if row['kind'] == 'part' and colour is None else []
            if len(colour_choices) == 1:
                from .ui import passthrough_args
                args = passthrough_args('item_id')
                args['colour'] = colour_choices[0]['color_id']
                return redirect(url_for('web.bw_collection_item', item_id=item_id, **args))
            detail = collection.detail(db, item_id, colour=colour, copy_id=request.args.get('copy'), stock_id=request.args.get('stock'))
            detail['colour_choices'] = colour_choices if len(colour_choices) > 1 else []
            choices = collection.options(db)
    except ValueError as exc:
        abort(404, str(exc))
    return bw_collection_detail_response(detail, choices, collection.TYPES.get(letter, 'Collection'))


@web_page.get('/collection/item/<kind>/<path:number>')
@login_required
def bw_collection_item_by_number(kind, number):
    """Number URLs of earlier versions (and a pasted number): the item the number names, through `core.items.find`. The colour of
    a part is a BrickLink colour number there, and means the colour that number stands for."""
    from .admin_ops import brickwork_path
    from .ui import passthrough_args
    from ..core.admin import database
    from ..core import items
    from ..store4 import identity
    kind_word = items.kind_of_type(kind.upper()) if len(kind) == 1 and kind.upper() in items.KIND_TYPE.values() else kind if kind in items.KINDS else None
    if kind_word is None:
        abort(404, 'Item is unavailable')
    args = passthrough_args('kind', 'number', 'item_id')            # item_id is the destination's own parameter
    with database(brickwork_path(), read_only=True) as db:
        found = items.find(db, kind_word, number, limit=1)
        if not found:
            abort(404, 'Item is unavailable')
        item_id = found[0]['item_id']
        if kind_word == 'part' and 'colour' in args:
            old = args.pop('colour')[0]
            try:
                resolved = identity.resolve_inverse(db, items.type_of_kind(kind_word), number, None if old == 'none' else str(old))
            except Exception:                                              # an ambiguous or unknown colour: the part, and its colour chooser
                resolved = None
            if resolved:
                item_id, args['colour'] = resolved[0], resolved[1]
    return redirect(url_for('web.bw_collection_item', item_id=item_id, **args), 301)


def bw_collection_detail_response(detail, choices, title):
    for photo in detail.get('photos', ()):                                 # an own photo is served by the image route, by its text id
        photo['url'] = url_for('web.bw_image', image_id=photo['id'])
    response = current_app.make_response(render_template('web/toni/web/bw_collection_detail.html',
        title=title, detail=detail, choices=choices, csrf_token=bw_add_token(), can_edit=bw_collection_editable()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/collection/wishes')
@login_required
def bw_collection_wishes():
    from . import ui
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    error = None
    rows, choices = [], dict(storages=[], places=[], lots=[], flags=[], colours=[])
    try:
        with database(brickwork_path(), read_only=True) as db:
            rows, choices = collection.listing(db, 'S', wishes=True), collection.options(db)
    except (sqlite3.Error, OSError, ValueError) as exc:
        error = public(exc, 'Brick Work database is not available. Check BW_DB_PATH and try again.')
    response = current_app.make_response(render_template('web/toni/web/bw_collection.html',
        title='Wishlist', kind='wish', rows=rows, records=ui.bw_collection_records(rows), choices=choices, error=error, csrf_token=bw_add_token(),
        can_edit=bw_collection_editable(), detail=None))
    response.headers['Cache-Control']='no-store'
    return response


@web_page.get('/collection/wishes/<identifier>')
@login_required
def bw_collection_wish(identifier):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    with database(brickwork_path(), read_only=True) as db:
        wish = db.execute('SELECT * FROM wish WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone()
        if not wish: abort(404)
        try:
            detail = collection.detail(db, wish['item_id'], colour=wish['color_id'], wish_id=identifier)
        except ValueError as exc: abort(404, str(exc))
        choices = collection.options(db, include_wishlists=True)
    return bw_collection_detail_response(detail, choices, 'Wishlist')


@web_page.get('/collection/lots/<identifier>')
@login_required
def bw_collection_lot(identifier):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    try:
        with database(brickwork_path(),read_only=True) as db:
            detail,choices=collection.lot_detail(db,identifier),collection.options(db)
    except ValueError as exc: abort(404,str(exc))
    response=current_app.make_response(render_template('web/toni/web/bw_collection_extra.html',
        title='Part lot',detail=detail,rows=detail['rows'],choices=choices,can_edit=bw_collection_editable(),csrf_token=bw_add_token()))
    response.headers['Cache-Control']='no-store'
    return response


@web_page.get('/collection/purchase-places')
@login_required
def bw_collection_places():
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    try:
        with database(brickwork_path(),read_only=True) as db:
            rows=collection.purchase_places(db)
    except (ValueError, sqlite3.Error, OSError):
        return render_template('web/toni/error.html', error='Brick Work database is not available. Check BW_DB_PATH and try again.', status=503), 503
    response=current_app.make_response(render_template('web/toni/web/bw_purchase_locations.html',
        rows=rows,csrf_token=bw_add_token(),can_edit=bw_collection_editable(),
        place_kinds=_ledger().PLACE_KINDS))
    response.headers['Cache-Control']='no-store'
    return response


@web_page.post('/collection/save/<action>')
@login_required
def bw_collection_write(action):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection, workbench
    if not bw_collection_editable(): abort(403,'Changes are switched off on this instance')
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(data,dict): abort(400,'Choose a change')
    bw_add_csrf(data)
    result = {}
    try:
        with database(brickwork_path()) as db:
            if action in ('save','archive'):
                event=collection.save(db,data.get('entity'),data.get('ids'),data.get('values',{}),archive=action=='archive')
                message='Set deleted' if action=='archive' and data.get('entity')=='copy' else ('Archived' if action=='archive' else 'Saved')
                if action=='save' and data.get('entity')=='stock':
                    merged = collection.merge_result(db,event)
                    if merged:
                        message='Merged into existing stock'
                        result['merged_ids'] = [r['id'] for r in merged]
                        if len(merged)==1:
                            r=merged[0]
                            result['url'] = url_for('web.bw_collection_item',item_id=r['item_id'],stock=r['id'],**({'colour':r['color_id']} if r['color_id'] is not None else {}))
            elif action=='wish':
                event=collection.want(db,int(data['item_id']),data.get('color_id'))
                message='Added to wishlist'
            elif action=='transfer':
                event=workbench.transfer(db,data['source_id'],data['copy_id'],data['target'],data['target_id'],data['quantity'])
                message='Saved'
            elif action=='take':
                event=workbench.take_for_gap(db,data['copy_id'],int(data['item_id']),data.get('color_id'),data['quantity'])
                message='Took '+str(int(data['quantity']))
            elif action=='undo':
                event=int(data['event_id'])
                collection.undo(db,event)
                message='Undone'
            elif action=='photo':
                upload=request.files.get('photo')
                event=collection.photo(db,_media(brickwork_path()),data['entity'],data['identifier'],upload.read(15*1024*1024+1) if upload else b'',data.get('caption',''))
                message='Photo added'
            elif action=='lot':
                event=collection.new_lot(db,data['ids'],data)
                message='Lot created'
            elif action=='caption':
                event=collection.caption(db,str(data['identifier']),data.get('caption',''))
                message='Caption saved'
            else: abort(404)
    except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc:
        return jsonify(message=public(exc, 'Nothing was saved · review the values and try again')),400
    return jsonify(event_id=event,message=message,**result)


@web_page.get('/collection/jump')
@login_required
def bw_collection_jump():
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    try:
        with database(brickwork_path(),read_only=True) as db:
            result=collection.search(db,request.args.get('q',''))
        rows=[]
        for r in result['results']:
            kind=r['item_type']
            row=dict(kind='wanted' if r.get('entity')=='wish' else {'S':'set','M':'minifigure','P':'part'}.get(kind,'item'),
                item_type=kind,type_label=collection.TYPES[kind],number=r['number_text'] or r['name'],name=r['name'],
                quantity=r.get('quantity'),color=r.get('color_id'),color_name=r['color_name'],
                image=url_for('web.bw_image',image_id=r['image'],w=320) if r['image'] else None)
            params=dict(item_id=r['item_id'])
            if r.get('color_id') is not None and kind=='P': params['colour']=r['color_id']
            if row['kind']=='wanted': row['url']=url_for('web.bw_collection_wish',identifier=r['id'])
            elif row['kind']=='set':
                row['copies']=[dict(id=c['id'],condition=c['condition'],completeness=c['completeness'],
                    missing_label=f"{c['missing']} missing · {c['damaged']} damaged",url=url_for('web.bw_collection_item',**params,copy=c['id']),
                    check_url=url_for('web.bw_check_copy',copy_id=c['id'])) for c in r['instances'] if c['entity']=='copy']
                if not row['copies']: continue
                row['url']=row['copies'][0]['url'] if len(row['copies'])==1 else None
            else: row['url']=url_for('web.bw_collection_item',**params)
            rows.append(row)
        result['results']=rows
    except (sqlite3.Error,OSError,ValueError) as exc:
        return jsonify(message=public(exc, 'Brick Work database is not available · try again')),503
    response=jsonify(result);response.headers['Cache-Control']='no-store';return response


@web_page.get('/planning/<screen>')
@login_required
def bw_planning(screen):
    from ..core import planning, collection
    from ..core.admin import database
    from .admin_ops import brickwork_path
    if screen not in ('wishlist','prices','complete-sets'): abort(404)
    error=None;rows=[];settings={};available_types=[];lists=[]
    list_id=request.args.get('list','all')
    kind=request.args.get('kind') or None
    if kind and kind not in collection.TYPES: abort(400)
    try:
        with database(brickwork_path(),read_only=True) as db:
            if screen=='wishlist':
                from ..core import wishlists
                lists=wishlists.listing(db, archived=True)
                if any(l['id']==list_id and l['archived_at'] for l in lists): list_id='all'
                if list_id != 'all': wishlists.require(db, list_id)
                rows=[r for r in planning.wishes(db) if list_id=='all' or r['list_id']==list_id]
            elif screen=='prices':
                # Rows are not rendered here: the page loads compact records and each row's observations on demand.
                available_types=[collection.type_of(r[0]) for r in db.execute('SELECT DISTINCT i.kind FROM price_current p JOIN item i ON i.id=p.item_id')]
            else:
                data=planning.ranking(db);rows=data['rows'];settings=data['settings']
    except (ValueError,sqlite3.Error,OSError) as exc: error=public(exc, 'Brick Work database is not available. Check BW_DB_PATH and try again.')
    response=current_app.make_response(render_template('web/toni/web/bw_prices.html' if screen=='prices' else 'web/toni/web/bw_planning.html',
        screen=screen,title={'wishlist':'Wishlist','prices':'Prices','complete-sets':'Complete sets'}[screen],
        rows=rows,settings=settings,error=error,kind=kind,types=collection.TYPES,available_types=available_types, wishlists=lists, list_id=list_id,
        can_edit=bw_collection_editable(),csrf_token=bw_add_token()))
    response.headers['Cache-Control']='no-store'
    return response


@web_page.get('/planning/prices/records')
@login_required
def bw_prices_records():
    """Compact Prices rows for the client list: positional fields, display text only."""
    import json
    from ..core import planning
    from ..core.admin import database
    from .admin_ops import brickwork_path
    try:
        with database(brickwork_path(),read_only=True) as db:
            result=planning.price_records(planning.priced_items(db))
    except (ValueError,sqlite3.Error,OSError) as exc: return jsonify(message=public(exc, 'Brick Work database is not available · try again')),503
    response=current_app.response_class(json.dumps(result,separators=(',',':'),ensure_ascii=False),mimetype='application/json')
    response.headers['Cache-Control']='no-store'
    return response


@web_page.get('/planning/prices/details')
@login_required
def bw_prices_details():
    """The observation list of one identity, loaded when its Details disclosure opens."""
    from ..core import planning, collection
    from ..core.admin import database
    from .admin_ops import brickwork_path
    try:
        item_id=int(request.args['item_id'])
        colour=int(request.args['colour']) if request.args.get('colour') not in (None,'') else None
    except (KeyError,ValueError): abort(400)
    if item_id<1 or colour is not None and not 0<colour<2**31: abort(400)
    try:
        with database(brickwork_path(),read_only=True) as db:
            result=planning.price_details(db,item_id,colour)
    except (ValueError,sqlite3.Error,OSError) as exc: return jsonify(message=public(exc, 'Brick Work database is not available · try again')),503
    if result is None: abort(404)
    response=jsonify(result);response.headers['Cache-Control']='no-store';return response


@web_page.post('/planning/action/<action>')
@login_required
def bw_planning_write(action):
    """The planning writes: `refresh` queues one `market_price` job per item id (unless one is unfinished already), `pin` and `settings`
    save one event each, `undo` reverses any receipt by its event id, `export` is the BrickLink XML of the chosen copies' repair lines (a
    read: it stays available on a read-only instance). Lines with no BrickLink number are skipped and listed (`summary: true` answers
    JSON with the list, else the file)."""
    import json
    from urllib.parse import quote
    from ..core import items as core_items, planning
    from ..core.admin import database, live_import_job
    from ..core.pipeline import Pipeline
    from ..core.transaction import transaction
    from .admin_ops import brickwork_path
    if action not in ('refresh', 'export', 'pin', 'settings', 'undo'): abort(404)
    if action!='export' and not bw_collection_editable(): abort(403,'Changes are switched off on this instance')
    data=request.get_json(silent=True)
    if not isinstance(data,dict): abort(400)
    bw_add_csrf(data)
    try:
        if action=='refresh':
            identities=data.get('items')
            if not isinstance(identities,list) or not identities or len(identities)>2000: raise ValueError('Choose priced items')
            ids=[]
            for identifier in identities:
                if type(identifier) is not int or identifier<1: raise ValueError('Choose item identities')
                if identifier not in ids: ids.append(identifier)
            with database(brickwork_path()) as db:
                try:
                    if any(core_items.label(db,i).unidentified for i in ids): raise ValueError('Resolve items before refreshing')
                except core_items.errors.NotFound: raise ValueError('Choose item identities') from None
                pipeline=Pipeline(db)
                with transaction(db):
                    jobs=[pipeline.queue_steps(i,['market_price'],via='app') for i in ids if live_import_job(db,i) is None]
            bw_start_worker()
            return jsonify(message='Price refresh queued · budgets checked by the worker',jobs=jobs)
        if action=='export':
            with database(brickwork_path(),read_only=True) as db:
                result=planning.export(db,data.get('ids'))
            skipped=[dict(item_no=(r['name'] or ''),color=r['color_name'],quantity=r['quantity'],reason=r['why']) for r in result['skipped']]
            if data.get('summary') is True:
                return jsonify(content=result['xml'].decode('utf-8'),filename='missing-parts.xml',mimetype='application/xml',
                               summary=dict(exported=len(result['lines']),skipped=skipped))
            response=current_app.response_class(result['xml'],mimetype='application/xml')
            response.headers['Content-Disposition']='attachment; filename="missing-parts.xml"'
            response.headers['Cache-Control']='no-store'
            response.headers['X-Bw-Skipped']=quote(json.dumps(skipped,separators=(',',':')))
            return response
        with database(brickwork_path()) as db:
            if action=='undo': planning.undo(db,int(data['event_id']));event=None
            else: event=planning.save(db,action,data)
    except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as exc: return jsonify(message=public(exc, 'Nothing was saved · review the values and try again')),400
    return jsonify(message='Undone' if action=='undo' else 'Saved',event_id=event)


@web_page.post('/planning/wishlists/<action>')
@login_required
def bw_wishlists_write(action):
    from ..core import wishlists, collection
    from ..core.admin import database
    from ..core.sources.base import audit_origin
    from .admin_ops import brickwork_path
    data=request.get_json(silent=True) or {}
    bw_add_csrf(data)
    if not bw_collection_editable(): abort(403, 'Changes are switched off on this instance')
    try:
        with database(brickwork_path()) as db, audit_origin('app'):
            if action=='undo':
                collection.undo(db, int(data['event_id'])); event=None
            elif action=='transfer':
                event=wishlists.transfer(db, data.get('ids'), data.get('list_id'), copy=data.get('copy',False))
            elif action in ('save','archive','restore'):
                _,event=wishlists.save(db, data.get('id') or None, data.get('values',{}), action=action)
            else: abort(404)
        return jsonify(message='Copied' if data.get('copy') else 'Saved', event_id=event)
    except (ValueError,KeyError,TypeError,sqlite3.Error) as exc:
        return jsonify(message=public(exc, 'Nothing was saved · review the values and try again')),400


@web_page.get('/planning/wishlists/<identifier>/export.<format>')
@login_required
def bw_wishlists_export(identifier,format):
    from ..core import wishlists
    from ..core.admin import database
    from .admin_ops import brickwork_path
    if format not in ('xml','csv'): abort(404)
    try:
        with database(brickwork_path(),read_only=True) as db:
            result=wishlists.export(db,identifier,format='bricklink' if format=='xml' else 'rebrickable',kind=request.args.get('kind','parts'))
        if request.args.get('summary')=='true': return jsonify(result)
        response=current_app.response_class(result['content'],mimetype=result['mimetype'])
        response.headers['Content-Disposition']='attachment; filename='+result['filename']
        return response
    except (ValueError,sqlite3.Error) as exc:
        return jsonify(message=public(exc, 'Nothing was saved · review the values and try again')),400

from . import sync_views  # noqa: E402,F401 — 12n Collection sync pages

from . import import_views  # noqa: E402,F401 — Import from BrickTracker (#11)

from . import list_views  # noqa: E402,F401 — printable lists and CSV (#43)
