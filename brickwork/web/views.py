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
                with database(admin_ops.brickwork_path(), read_only=True) as rdb:
                    data['currency'] = dict(display=currency.display_currency(rdb), rates=currency.listing(rdb))
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
    from ..core import keys, secrets
    response = current_app.make_response(render_template('web/toni/web/bw_admin.html',
        page=page, title=titles[page], data=data, error=error, group=group,
        steps=STEPS, item_types=sorted(TYPES), csrf_token=bw_add_token(), can_edit=bw_collection_editable(),
        key_fields=keys.field_map(), key_entry=secrets.entry_available()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/manage/<page>')
@login_required
def bw_admin_write(page):
    from ..core.sources.base import ColourCodeError, SourceError
    from flask import flash
    from . import admin_ops
    from ..core.pipeline import STEPS, TYPES
    import json
    action = request.form.get('action', '')
    failure_label = {
        'catalogues': {'load': 'Catalogue load', 'colours': 'Colour load', 'source': 'Source toggle',
                       'key_save': 'Source key', 'key_test_save': 'Source key', 'key_remove': 'Source key',
                       'key_undo': 'Source key', 'key_test': 'Source key test'}.get(action, 'Catalogues & keys'),
        'settings': 'Picture refresh' if action == 'pictures' else 'Settings',
        'unresolved': 'Picture load' if action == 'images' else 'Figure resolution',
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
    try:
        if page == 'instructions':
            if request.form['action'] == 'fetch_missing':
                if not bw_collection_editable():
                    abort(403, 'Changes are switched off on this instance')
                queued, skipped = admin_ops.tools_write('instruction_fetch')
                bw_start_worker()
                note = f'Queued {len(queued)} identity refreshes'
                if skipped:
                    note += f', {len(skipped)} skipped (invalid number: {", ".join(skipped[:5])}{" ..." if len(skipped) > 5 else ""})'
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
                with database(admin_ops.brickwork_path(), read_only=True) as db:
                    result = core_admin.check(db)
                findings = len(result['foreign_key_check'])
                ok = result['integrity_check'] == ['ok'] and not findings
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
            job, count = admin_ops.tools_write('pictures', source=request.form['source'],
                scope=request.form['scope'], types=request.form.getlist('types'),
                expected_count=request.form.get('expected_count') or None)
            bw_start_worker()
            flash(f'{count} picture identities queued · No Undo for picture refresh; existing files are kept', 'success')
            return redirect(url_for('web.bw_admin', page='jobs') + '#job-' + str(job))
        elif page == 'settings' and request.form.get('action') in ('display_currency', 'rate', 'ecb'):
            # #39: display currency and exchange rates; stored amounts never change.
            if not bw_collection_editable():
                abort(403, 'Changes are switched off on this instance')
            from ..core import currency
            from ..core.admin import database
            with database(admin_ops.brickwork_path()) as db:
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
        elif page == 'settings':
            priority = {}
            for step in STEPS:
                priority[step] = {}
                for kind in ['*', *sorted(TYPES)]:
                    value = request.form.get('priority:' + step + ':' + kind, '').strip()
                    if value:
                        priority[step][kind] = [s.strip() for s in value.split(',')]
            freshness = [(request.form['source:' + n], request.form['kind:' + n], request.form['days:' + n])
                         for n in request.form.getlist('freshness')]
            admin_ops.tools_write('settings', country=request.form['retail_country'], priority=priority, freshness=freshness)
        elif page == 'unresolved':
            identity = {k: request.form[k] for k in ('source', 'kind', 'source_id')}
            if request.form['action'] == 'images':
                admin_ops.tools_write('images', **identity)
                bw_start_worker()
            else:
                choice = json.loads(request.form['candidate']) if request.form['action'] == 'pick' else None
                admin_ops.tools_write('resolve', **identity, selected=tuple(choice) if choice else None)
        elif page == 'refresh':
            admin_ops.tools_write('refresh')
            bw_start_worker()
        elif page == 'jobs':
            if not bw_collection_editable():
                abort(403, 'Changes are switched off on this instance')
            job = int(request.form['job'])
            step = request.form.get('step') or None
            if step is not None and step not in STEPS:
                raise ValueError('Unknown step')
            # Queue Retry for the same worker used by refresh, without blocking the request.
            if request.form.get('action') == 'resume':
                from ..core.admin import database
                with database(admin_ops.brickwork_path(), read_only=True) as db:
                    saved = db.execute("SELECT state FROM jobs WHERE id=? AND source='import'", (job,)).fetchone()
                    if saved is None or saved['state'] not in ('running', 'waiting_for_budget'):
                        raise ValueError('Job is not interrupted')
            else:
                admin_ops.tools_write('retry_queue', job=job, step=step)
            bw_start_worker()
        elif page == 'catalogues' and request.form['action'] in ('key_save', 'key_test_save', 'key_remove', 'key_test', 'key_undo'):
            if not bw_collection_editable():
                abort(403, 'Changes are switched off on this instance')
            from ..core import errors, keys
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
            if request.form['action'] == 'load':
                admin_ops.tools_write('catalogue')
                admin_ops.tools_write('colours')
            elif request.form['action'] == 'colours':
                admin_ops.tools_write('colours')
            else:
                admin_ops.tools_write('source', source=request.form['source'], enabled=request.form.get('enabled') == 'yes')
        else:
            abort(404)
    except ColourCodeError as exc:
        flash(str(exc), 'error')
    except SourceError as exc:
        flash(failure_label + ' · ' + str(exc), 'error')
    except (ValueError, KeyError, TypeError, sqlite3.Error, OSError):
        flash('Nothing was saved. Check the values and try again.', 'error')
    else:
        flash('Saved', 'success')
    target = 'jobs' if page in ('refresh', 'jobs') else page
    return redirect(url_for('web.bw_admin', page=target, **({'group': request.form.get('group', 'owners')} if page == 'values' else {})))


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
        with database(admin_ops.brickwork_path(), read_only=True) as db:
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
    import uuid
    from . import admin_ops, token_rows
    from ..core import errors, tokens
    from ..core.admin import database
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
        with database(admin_ops.brickwork_path()) as db, audit_origin('app'):
            if action == 'create':
                scopes = request.form.getlist('scopes')
                # Reloading the page that showed a secret resends this form: answer, do not create again (#68).
                form_id = request.form.get('form_id', '')
                if not re.fullmatch(r'[0-9a-f]{32}', form_id or ''):
                    form_id = ''
                if form_id:
                    db.execute("DELETE FROM settings WHERE key LIKE 'token_form:%' AND value<?", (str(time.time() - 86400),))
                    if db.execute('SELECT 1 FROM settings WHERE key=?', ('token_form:' + form_id,)).fetchone():
                        return bw_tokens_render(form_error='This form was already sent: the token exists, and its secret is shown only once.',
                                                status=409)
                try:
                    created, _ = tokens.create(db, request.form.get('name', ''), scopes)
                except errors.BrickWorkError as exc:
                    return bw_tokens_render(form_error=str(exc), form_name=request.form.get('name', ''), form_scopes=scopes,
                                            show_create=True, status=getattr(exc, 'status', 400))
                if form_id:
                    with db:
                        db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', ('token_form:' + form_id, str(time.time())))
                return bw_tokens_render(created=created)
            if action == 'revoke':
                _, event = tokens.revoke(db, request.form.get('id', ''))
                return redirect(url_for('web.bw_tokens', revoked=event))
            identifier = token_rows.event_id(request.form.get('event', ''))
            if identifier is None:
                abort(400, 'Invalid event')
            found = db.execute("SELECT field,old_value,new_value,at FROM events WHERE id=? AND entity='bw_token' AND field IN ('create','revoke')", (identifier,)).fetchone()
            if found and not token_rows.undoable(found):
                abort(400, 'This token change cannot be undone')
            if found and not token_rows.recent(found):
                abort(400, 'Undo is no longer available for this token change')
            response, _, _ = tokens.undo(db, identifier, 'ui-' + uuid.uuid4().hex)
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
    """Resume durable imports when the standalone app starts."""
    from .admin_ops import brickwork_path
    from ..core.admin import database
    with app.app_context():
        path = brickwork_path()
        if not path.is_file():
            return
        with database(path, read_only=True) as db:
            pending = db.execute("""SELECT 1 FROM jobs WHERE source='import'
                AND state IN ('queued','running','waiting_for_budget') LIMIT 1""").fetchone()
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
@login_required
def bw_image(image_id):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from flask import send_file
    path = brickwork_path()
    with database(path, read_only=True) as db:
        row = db.execute('SELECT local_path FROM item_images WHERE id=?', (image_id,)).fetchone()
    if not row:
        abort(404)
    from ..core.media import root_for
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
        target, mimetype = thumbnails.lookup(root, image_id, int(width), target)
    response = send_file(target, mimetype=mimetype, max_age=86400)
    response.cache_control.public = None
    response.cache_control.private = True
    return response


@web_page.get('/manage/instructions/<int:identifier>/download')
@login_required
def bw_instruction_download(identifier):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from flask import send_file
    path = brickwork_path()
    with database(path, read_only=True) as db:
        row = db.execute('SELECT path FROM instruction_files WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone()
    if not row:
        abort(404)
    from ..core.media import root_for
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


@web_page.get('/manage/add')
@login_required
def bw_add():
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import add
    error, colours, wishlists = None, [], []
    try:
        with database(brickwork_path(), read_only=True) as db:
            colours = add.colors(db)
            from ..core.wishlists import listing
            wishlists = listing(db)
    except (ValueError, sqlite3.Error, OSError):
        error = 'Brick Work database is not available. Check BW_DB_PATH and try again.'
    response = current_app.make_response(render_template('web/toni/web/bw_add.html',
        types=add.TYPES, colours=colours, wishlists=wishlists, error=error, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/manage/add/search')
@login_required
def bw_add_search():
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.add import search
    try:
        with database(brickwork_path(), read_only=True) as db:
            result = search(db, request.args.get('type', 'S'), request.args.get('q', '')[:100], request.args.get('sort', 'number'))
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
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import add
    from ..core.sources.base import audit_origin, SourceError
    from ..core.sources.brickognize import Brickognize, photo_bytes
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    bw_add_csrf(data)
    kind, where, mode = data.get('type', 'S'), data.get('where', 'owned'), data.get('mode', 'paste')
    if kind not in add.TYPES:
        abort(400, 'Choose an item type')
    try:
        with database(brickwork_path()) as db, audit_origin('app'):
            photo = None
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
            elif mode == 'photo':
                upload = request.files.get('file')
                if not upload:
                    raise ValueError('Choose a photo')
                photo = photo_bytes(upload.read(8 * 1024 * 1024 + 1))
                candidates = Brickognize(db).predict(photo)
                rows = [{**candidate, 'quantity': 1} for candidate in candidates]
                if not rows:
                    raise ValueError('Nothing identified · try another photo')
            elif mode == 'search':
                rows = data.get('items', [])
                if not isinstance(rows, list):
                    raise ValueError('Choose items from the search')
            else:
                raise ValueError('Choose how to add')
            proposal = add.resolve(db, rows, where, list_id=data.get('list_id') or 'default', map_wanted_ids=data.get('map_wanted_ids', 'true') not in (False, 'false'))
            if photo:
                scores = {(r['item_type'], r['item_no']): r['score'] for r in rows}
                for row in proposal['items']:
                    row['score'] = scores[row['item_type'], row['item_no']]
            token = bw_add_signer().dumps(dict(**proposal, batch=uuid.uuid4().hex,
                owner=bw_add_token(), photo=base64.b64encode(photo).decode() if photo else None, mode=mode))
        return jsonify(**proposal, token=token, candidates=mode == 'photo')
    except (ValueError, SourceError, sqlite3.Error, OSError, UnicodeError, json.JSONDecodeError, ET.ParseError) as error:
        return jsonify(error=public(error, 'Could not read this input')), 400


@web_page.post('/manage/add/confirm')
@login_required
def bw_add_confirm():
    import base64
    from itsdangerous import BadSignature
    from .admin_ops import brickwork_path
    from ..core.admin import database
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
        if proposal['mode'] == 'photo':
            selected = data.get('candidate')
            if type(selected) is not int or not 0 <= selected < len(original):
                raise ValueError('Choose a photo candidate first')
            original = [original[selected]]
        with database(brickwork_path()) as db, audit_origin('app'):
            rows = add.validate_edits(db, original, data.get('items'), batch=proposal['batch'])
            receipts = add.confirm(db, rows, batch=proposal['batch'],
                photo=base64.b64decode(proposal['photo']) if proposal['photo'] else None,
                keep_photo=data.get('keep_photo') is True)
        if receipts:
            bw_start_worker()
        return jsonify(receipts=receipts, batch=proposal['batch'])
    except (BadSignature, ValueError, sqlite3.Error, OSError, TypeError, KeyError) as error:
        saved = []
        if proposal and proposal.get('owner') == bw_add_token():
            try:
                with database(brickwork_path(), read_only=True) as db:
                    saved = add.receipts(db, proposal['batch'])
            except (ValueError, sqlite3.Error, OSError):
                pass
        if saved:
            bw_start_worker()
        message = (f'{len(saved)} items added · try again to finish this review' if saved else
                   public(error, 'Could not add · check the review and try again'))
        return jsonify(error=message, receipts=saved), 400


@web_page.post('/manage/add/undo')
@login_required
def bw_add_undo():
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.add import undo
    data = request.get_json(silent=True) or {}
    bw_add_csrf(data)
    if not isinstance(data.get('batch'), str):
        abort(400)
    try:
        with database(brickwork_path()) as db:
            undo(db, data['batch'])
    except ValueError as exc:
        return jsonify(error=public(exc, 'Could not undo · try again')), 400
    return jsonify(message='Undone')


@web_page.get('/manage/add/jobs/<int:job>')
@login_required
def bw_add_job(job):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    with database(brickwork_path(), read_only=True) as db:
        snapshot = db.execute("SELECT state FROM jobs WHERE id=? AND source='import'", (job,)).fetchone()
        if snapshot is None:
            abort(404)
        steps = db.execute('SELECT * FROM import_steps WHERE job_id=? ORDER BY position', (job,)).fetchall()
    # Only the safe step contract is returned; raw payloads and source keys stay server-side.
    done = sum(s['state'] == 'done' for s in steps)
    # The progress widget speaks started/progress/waiting/failed/done.
    shown = {'waiting_for_budget': 'waiting', 'running': 'progress', 'queued': 'started'}
    events = [dict(job_id=job, step=s['name'], state=shown.get(s['state'], s['state']),
        completed_steps=done, total_steps=len(steps), count=s['count'], total=s['total'],
        job_state=snapshot['state'], retry=s['state'] == 'failed',
        message=s['error'] if s['state'] == 'failed' else 'Waiting for budget' if s['state'] == 'waiting_for_budget' else 'Importing · ' + s['name']) for s in steps]
    events.append(dict(job_id=job, step=None, state=snapshot['state'], completed_steps=done,
        total_steps=len(steps), message='Import complete' if snapshot['state'] == 'done' else 'Import needs attention' if snapshot['state'] == 'failed' else 'Waiting for budget' if snapshot['state'] == 'waiting_for_budget' else 'Import queued'))
    response = jsonify(events=events)
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/manage/add/jobs/<int:job>/retry')
@login_required
def bw_add_retry(job):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.pipeline import Pipeline
    from ..core.sources.base import audit_origin
    data = request.get_json(silent=True) or {}
    bw_add_csrf(data)
    try:
        with database(brickwork_path()) as db, audit_origin('app'):
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
    path = brickwork_path()
    error, copies = None, []
    try:
        with database(path, read_only=True) as db:
            copies = checker.choices(db, _media(path))
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
    path = brickwork_path()
    try:
        with database(path, read_only=True) as db:
            state = checker.view(db, copy_id, _media(path))
    except ValueError as error:
        abort(404, str(error))
    response = current_app.make_response(render_template('web/toni/web/bw_checker.html', state=state, error=None, csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/workbench/check-parts/<copy_id>/figure/<minifig_type>/<minifig_no>')
@login_required
def bw_check_figure(copy_id, minifig_type, minifig_no):
    """Check figure parts: one whole figure's own parts inside a copy (4.8a)."""
    from .admin_ops import brickwork_path
    from ..core import checker
    from ..core.admin import database
    path = brickwork_path()
    try:
        with database(path, read_only=True) as db:
            state = checker.figure_view(db, copy_id, _media(path), minifig_type, minifig_no)
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
    import json
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import workbench
    rows, copies, history, selected, error = [], [], [], request.args.getlist('copy'), None
    unresolved_rows = []
    match_groups = []
    ranking = request.args.getlist('rank') if request.args.get('ranked') else list(workbench.PICKER_DEFAULT)
    rank_keys = []
    try:
        with database(brickwork_path(), read_only=True) as db:
            all_gaps = workbench.gaps(db)
            unresolved_rows = [r for r in all_gaps if r['unresolved']]
            missing = [r for r in all_gaps if r['target'] == 'part']
            by_copy = {}
            for row in missing:
                copy = by_copy.setdefault(row['copy_id'],dict(row['copy'],missing=0))
                copy['missing'] += row['need']
            copies = workbench.decorate_many(db, [dict(c, item_no=c['set_no']) for c in by_copy.values()])
            rows = workbench.picker(db,selected,ranking,all_gaps=all_gaps) if mode == 'picker' else workbench.matches(db, all_gaps=all_gaps)
            if mode == 'picker':
                rank_keys = workbench.picker_keys(rows)
            if mode == 'matcher':
                match_groups = workbench.group_matches(db, rows, all_gaps)
            history = [dict(r) for r in db.execute("SELECT id,at,new_value FROM events WHERE entity='bw_workbench' AND field='receipt' AND id NOT IN (SELECT CAST(new_value AS INTEGER) FROM events WHERE entity='bw_workbench' AND field='undo') ORDER BY id DESC LIMIT 50")]
            for row in history:
                row['receipt'] = json.loads(row['new_value'])
    except (ValueError,sqlite3.Error,OSError):
        error = 'Brick Work database is not available. Check BW_DB_PATH and try again.'
    response = current_app.make_response(render_template('web/toni/web/bw_workbench.html',mode=mode,
        rows=rows,ranking=ranking,rank_keys=rank_keys,picking=request.args.get('pick') == '1',match_groups=match_groups,copies=copies,selected=selected,history=history,unresolved_rows=unresolved_rows,error=error,csrf_token=bw_add_token()))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.post('/workbench/check-parts/<copy_id>')
@login_required
def bw_check_write(copy_id):
    return bw_check_save(copy_id)


@web_page.post('/workbench/check-parts/<copy_id>/figure/<minifig_type>/<minifig_no>')
@login_required
def bw_check_figure_write(copy_id, minifig_type, minifig_no):
    return bw_check_save(copy_id, (minifig_type, minifig_no))


def bw_check_save(copy_id, figure=None):
    import uuid
    from .admin_ops import brickwork_path
    from ..core import checker
    from ..core.admin import database
    origin = request.headers.get('Origin')
    if (origin and origin.rstrip('/') != request.host_url.rstrip('/')) or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)
    path = brickwork_path()
    payload = request.get_json(silent=True) if request.is_json else dict(request.form)
    if not isinstance(payload, dict):
        return jsonify(error='Choose a checker action'), 400
    bw_add_csrf(payload)
    payload.pop('csrf_token', None)
    if not request.is_json:
        payload['operation'] = uuid.uuid4().hex
        if payload.get('action') not in ('start', 'restart'):
            abort(400)
    try:
        with database(path) as db:
            state = checker.write(db, copy_id, payload, _media(path), figure)
    except (ValueError, sqlite3.Error, OSError) as error:
        message = public(error, 'The answer could not be saved. Retry.')
        if not request.is_json:
            flash(message, 'bw-checker')
            return redirect(url_for('web.bw_check_figure', copy_id=copy_id, minifig_type=figure[0], minifig_no=figure[1]) if figure else url_for('web.bw_check_copy', copy_id=copy_id))
        return jsonify(error=message), 409
    if not request.is_json:
        return redirect(url_for('web.bw_check_figure', copy_id=copy_id, minifig_type=figure[0], minifig_no=figure[1]) if figure else url_for('web.bw_check_copy', copy_id=copy_id, run=1))
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
                event = workbench.found(db,data['item_type'],data['item_no'],data['color_id'],data['destination'],data.get('assignments',{}),data['quantity'])
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
            data['lots'] = [dict(r) for r in db.execute('SELECT id,name FROM lots WHERE archived_at IS NULL ORDER BY name')]
            # Resolve history targets in one batch; no query for each allocation.
            targets = {row['id']: dict(row) for row in db.execute('''
                SELECT a.id,c.set_no,s.name AS storage,l.name AS lot
                FROM allocations a LEFT JOIN copies c ON c.id=coalesce(a.target_copy_id,a.copy_id)
                LEFT JOIN loose_stock stock ON stock.id=a.target_stock_id
                LEFT JOIN storages s ON s.id=stock.storage_id
                LEFT JOIN lots l ON l.id=stock.lot_id WHERE a.order_id=?
            ''', (order_id,))}
            identities = {row['id']: row for row in data['lines']}
            for allocation in data['allocations']:
                allocation['identity'] = identities.get(allocation['line_id'])
                target = targets.get(allocation['id']) or {}
                copy_ref = allocation.get('target_copy_id') or allocation.get('copy_id')
                if allocation['target_type'] == 'copy' or (allocation['target_type'] is None and copy_ref):
                    name = target.get('set_no') or copy_ref
                    allocation['target_label'] = 'Copy ' + str(name) if name else 'Target not recorded'
                elif allocation['target_type'] == 'stock':
                    allocation['target_label'] = (('Lot ' + target['lot'] if target.get('lot') else 'Loose stock') +
                        (' · ' + target['storage'] if target.get('storage') else ''))
                else:
                    allocation['target_label'] = 'Target not recorded'
            allocation_events = {}
            for event in data['history']:
                if event['undo_available'] and not event['undone']:
                    for change in event['receipt'].get('changes', []):
                        if change['table'] == 'allocations':
                            allocation_events[change['key']['id']] = event['id']
            for allocation in data['allocations']:
                allocation['undo_event'] = allocation_events.get(allocation['id'])
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
    from ..core.part_inventory import candidates
    from ..core.sources.brickognize import Brickognize, photo_bytes
    from ..core.sources.base import audit_origin
    bw_add_csrf(request.form)
    try:
        upload = request.files.get('file')
        if not upload:
            raise ValueError('Choose a photo')
        photo = photo_bytes(upload.read(8 * 1024 * 1024 + 1))
        with database(brickwork_path()) as db, audit_origin('app'):
            choices, unresolved = candidates(db, Brickognize(db).predict(photo, request.form.get('endpoint', 'parts')))
        if not choices:
            return jsonify(error='Nothing identified · try another photo', unresolved=unresolved), 400
        proposal = dict(id=uuid.uuid4().hex, owner=bw_add_token(), candidates=choices, photo=base64.b64encode(photo).decode())
        return jsonify(candidates=choices, unresolved=unresolved, token=bw_add_signer().dumps(proposal))
    except (ValueError, sqlite3.Error, OSError) as exc:
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
                row = db.execute("SELECT l.id, l.name, l.created_date FROM events e JOIN lots l ON l.id = json_extract(e.new_value, '$.lot') WHERE e.id = ?", (event,)).fetchone()
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
    from ..core import orders, ledger
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
                event = orders.match(db, int(data['order_id']), int(data['line_id']), data['item_type'], data['item_no'], data.get('color_id'))
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
                ledger.undo_history(db, int(data['event_id']))
                return jsonify(message='Undone')
            else:
                abort(404)
        return jsonify(message='Saved', event_id=event)
    except (ValueError, KeyError, TypeError, sqlite3.Error, SourceError, UnicodeError) as exc:
        return jsonify(message=public(exc, 'Nothing was saved · review the values and try again')), 400


@web_page.get('/workbench/orders/<int:order_id>/short.xml')
@login_required
def bw_order_short(order_id):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core.orders import short_xml
    with database(brickwork_path(), read_only=True) as db:
        try:
            text = short_xml(db, order_id)
        except ValueError:
            abort(404)
    response = current_app.response_class(text, mimetype='application/xml')
    response.headers['Content-Disposition'] = 'attachment; filename="order-short.xml"'
    response.headers['Cache-Control'] = 'no-store'
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
    from . import setup_state
    kind = kind.upper()
    if kind not in collection.TYPES:
        abort(404)
    error = None
    rows, choices = [], dict(storages=[], places=[], lots=[], flags=[], colours=[])
    try:
        with database(brickwork_path(), read_only=True) as db:
            rows = collection.listing(db, kind)
            choices = collection.options(db)
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


@web_page.get('/collection/item/<kind>/<path:number>')
@login_required
def bw_collection_item(kind, number):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    kind = kind.upper()
    try:
        colour_arg = request.args.get('colour')
        colour = int(colour_arg) if colour_arg and colour_arg != 'none' else None
        with database(brickwork_path(), read_only=True) as db:
            colour_choices = collection.part_colours(db, number) if kind=='P' and not colour_arg else []
            if len(colour_choices)==1:
                from .ui import passthrough_args
                args = passthrough_args('kind', 'number')
                args['colour'] = colour_choices[0]['color_id'] if colour_choices[0]['color_id'] is not None else 'none'
                return redirect(url_for('web.bw_collection_item', kind=kind, number=number, **args))
            detail = collection.detail(db, kind, number, colour=colour,
                copy_id=request.args.get('copy'), stock_id=request.args.get('stock'))
            detail['colour_choices'] = colour_choices if len(colour_choices)>1 else []
            choices = collection.options(db)
    except ValueError as exc:
        abort(404, str(exc))
    return bw_collection_detail_response(detail, choices, collection.TYPES.get(kind, 'Collection'))


def bw_collection_detail_response(detail, choices, title):
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


@web_page.get('/collection/wishes/<int:identifier>')
@login_required
def bw_collection_wish(identifier):
    from .admin_ops import brickwork_path
    from ..core.admin import database
    from ..core import collection
    with database(brickwork_path(), read_only=True) as db:
        wish=db.execute('SELECT * FROM wishlist WHERE id=? AND archived_at IS NULL',(identifier,)).fetchone()
        if not wish: abort(404)
        detail=collection.detail(db,wish['item_type'],wish['item_no'],colour=wish['color_id'],wish_id=identifier)
        choices=collection.options(db, include_wishlists=True)
    return bw_collection_detail_response(detail,choices,'Wishlist')


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
                            result['url'] = url_for('web.bw_collection_item',kind=r['item_type'],number=r['item_no'],colour=r['color_id'],stock=r['id'])
            elif action=='wish':
                event=collection.want_placeholder(db,data.get('item_no'))
                message='Added to wishlist'
            elif action=='undo':
                event=int(data['event_id'])
                row=db.execute('SELECT entity FROM events WHERE id=?',(event,)).fetchone()
                if row and row[0]=='bw_workbench': workbench.undo(db,event)
                else: collection.undo(db,event)
                message='Undone'
            elif action=='transfer':
                event=workbench.transfer(db,data['source_id'],data['copy_id'],data['target'],data['target_id'],data['quantity'])
                message='Saved'
            elif action=='take':
                event=workbench.take_for_gap(db,data['copy_id'],data['item_type'],data['item_no'],data['color_id'],data['quantity'])
                message='Took '+str(int(data['quantity']))
            elif action=='photo':
                upload=request.files.get('photo')
                event=collection.photo(db,_media(brickwork_path()),data['entity'],data['identifier'],upload.read(15*1024*1024+1) if upload else b'',data.get('caption',''))
                message='Photo added'
            elif action=='lot':
                event=collection.new_lot(db,data['ids'],data)
                message='Lot created'
            elif action=='caption':
                event=collection.caption(db,int(data['identifier']),data.get('caption',''))
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
                item_type=kind,type_label=collection.TYPES[kind],number=r['item_no'],name=r['name'],
                quantity=r.get('quantity'),color=r.get('color_id'),color_name=r['color_name'],
                image=url_for('web.bw_image',image_id=r['image'],w=320) if r['image'] else None)
            params=dict(kind=kind,number=r['item_no'])
            if r.get('color_id') is not None: params['colour']=r['color_id']
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
                available_types=[r[0] for r in db.execute('SELECT DISTINCT item_type FROM price_current')]
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
    kind,number=request.args.get('kind'),request.args.get('number')
    if kind not in collection.TYPES or not number: abort(400)
    try: colour=int(request.args['colour']) if request.args.get('colour') not in (None,'') else None
    except ValueError: abort(400)
    if colour is not None and not 0<=colour<2**31: abort(400)
    try:
        with database(brickwork_path(),read_only=True) as db:
            result=planning.price_details(db,kind,number,colour)
    except (ValueError,sqlite3.Error,OSError) as exc: return jsonify(message=public(exc, 'Brick Work database is not available · try again')),503
    if result is None: abort(404)
    response=jsonify(result);response.headers['Cache-Control']='no-store';return response


@web_page.post('/planning/action/<action>')
@login_required
def bw_planning_write(action):
    import json
    from ..core import planning
    from ..core.admin import database
    from ..core.pipeline import Pipeline
    from .admin_ops import brickwork_path
    if action!='export' and not bw_collection_editable(): abort(403,'Changes are switched off on this instance')
    data=request.get_json(silent=True)
    if not isinstance(data,dict): abort(400)
    bw_add_csrf(data)
    try:
        with database(brickwork_path()) as db:
            if action=='export':
                response=current_app.response_class(planning.export(db,data.get('ids')),mimetype='application/xml')
                response.headers['Content-Disposition']='attachment; filename="missing-parts.xml"'
                response.headers['Cache-Control']='no-store'
                return response
            if action=='refresh':
                identities=data.get('items')
                if not isinstance(identities,list) or not identities or len(identities)>2000: raise ValueError('Choose priced items')
                keys=[];seen=set()
                for key in identities:
                    if not isinstance(key,list) or len(key)!=2 or not all(isinstance(v,str) for v in key): raise ValueError('Choose item identities')
                    if tuple(key) not in seen:
                        seen.add(tuple(key));keys.append(key)
                valid={(r[0],r[1]) for r in db.execute('SELECT item_type,item_no FROM items WHERE (item_type,item_no) IN (SELECT json_extract(value,\'$[0]\'),json_extract(value,\'$[1]\') FROM json_each(?))',(json.dumps(keys),))}
                if set(map(tuple,keys))!=valid or any(k[0]=='?' for k in keys): raise ValueError('Resolve items before refreshing')
                pipeline=Pipeline(db)
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    jobs=[pipeline.queue_steps(*key,['market_price'],via='app') for key in keys]
                bw_start_worker()
                return jsonify(message='Price refresh queued · budgets checked by the worker',jobs=jobs)
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
    except (ValueError,sqlite3.Error) as exc:
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
