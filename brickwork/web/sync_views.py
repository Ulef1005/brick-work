"""12n Collection sync pages (#10): sources, link, pull preview, send review. Services live in core.sync."""
from contextlib import closing
import json
import sqlite3

from flask import abort, flash, get_flashed_messages, redirect, render_template, request, url_for
from flask_login import login_required

from .views import web_page, bw_add_csrf, bw_add_token, bw_collection_editable

SOURCES = ('rebrickable', 'brickset')


def _db():
    from ..core.connect import connect
    from .admin_ops import brickwork_path
    return closing(connect(brickwork_path()))


def _unavailable(view):
    """Before setup there is no database: the usual notice, not a 500 (#68)."""
    from functools import wraps
    from flask import render_template

    @wraps(view)
    def wrapped(*args, **kwargs):
        import sqlite3
        from ..core.connect import NoCatalogue
        try:
            return view(*args, **kwargs)
        except (sqlite3.OperationalError, NoCatalogue):
            return render_template('web/toni/error.html', error='Brick Work database is not available. Check BW_DB_PATH and try again.', status=503), 503
    return wrapped


def _source(source):
    if source not in SOURCES:
        abort(404)
    return source


def _budget(db, source):
    from ..core.sync import adapters
    try:
        status = adapters.ADAPTERS[source](db).status()
        return dict(used=status['used_today'], budget=status['budget'])
    except Exception:
        return None


def _log(db, limit=20):
    """Sync log rows from the receipts, their undos and the send records, newest first."""
    rows = []
    for r in db.execute("""SELECT e.id, e.entity_id, e.field, e.new_value, e.at, EXISTS(SELECT 1 FROM event_undo u WHERE u.event_id=e.id) AS undone
            FROM event e WHERE e.entity_kind='sync' AND e.field IN ('receipt', 'undo', 'send') ORDER BY e.id DESC LIMIT ?""", (limit,)):
        value = json.loads(r['new_value']) if r['new_value'] else None
        if r['field'] == 'receipt':
            c = value.get('counts', {})
            what = ' · '.join(p for p in (
                f"{c.get('copies', 0)} {'copy' if c.get('copies') == 1 else 'copies'} added" if c.get('copies') else '',
                f"{c.get('stock', 0)} loose added" if c.get('stock') else '',
                f"{c.get('wishes_added', 0)} {'wish' if c.get('wishes_added') == 1 else 'wishes'} added" if c.get('wishes_added') else '',
                f"{c.get('wishes_changed', 0)} wish quantities raised" if c.get('wishes_changed') else '') if p) or 'Nothing new'
            rows.append(dict(at=r['at'], source=value['source'], direction='Pulled', what=what, state='Undone' if r['undone'] else 'Done', event=r['id']))
        elif r['field'] == 'undo':
            rows.append(dict(at=r['at'], source='', direction='Undone', what='Pull ' + str(value['undoes']) + ' undone', state='Done', event=None))
        else:
            counts = (value or {}).get('counts', {})
            sent = counts.get('sent', 0) + counts.get('unchanged', 0)
            problems = {k: v for k, v in counts.items() if k not in ('sent', 'unchanged')}
            what = f"{sent} {'change' if sent == 1 else 'changes'} sent" + ''.join(f" · {v} {k.replace('_', ' ')}" for k, v in problems.items())
            state = 'Done' if not problems else 'Waiting for you'
            rows.append(dict(at=r['at'], source=r['entity_id'], direction='Sent', what=what, state=state, event=None))
    return rows


def stamp(value):
    """'2026-10-14T21:10:…' -> '14 Oct · 21:10' (UTC as stored)."""
    from datetime import datetime
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return 'Not recorded'
    return moment.strftime('%d %b · %H:%M')


def _page(template, **context):
    from flask import current_app
    context.setdefault('stamp', stamp)
    response = current_app.make_response(render_template(template, csrf_token=bw_add_token(), can_edit=bw_collection_editable(),
                                                         messages=get_flashed_messages(with_categories=True), **context))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/manage/sync')
@login_required
@_unavailable
def bw_sync():
    from ..core import sync
    from .setup_state import key_missing
    with _db() as db:
        cards = []
        for source in SOURCES:
            status = sync.status(db, source)
            cards.append(dict(status, key_gap=key_missing(source), user=status['credentials']['user']['configured']))
        log = _log(db)
    return _page('web/toni/web/bw_sync.html', screen='sources', title='Collection sync', cards=cards, log=log)


@web_page.get('/manage/sync/<source>/link')
@login_required
@_unavailable
def bw_sync_link(source):
    from ..core import sync, wishlists
    from .setup_state import key_missing
    _source(source)
    lists, list_error = [], None
    with _db() as db:
        status = sync.status(db, source)
        user = status['credentials']['user']['configured']
        if user and source == 'rebrickable' and not key_missing(source):
            try:
                lists = sync.lists(db, source)
            except Exception as exc:  # shown on the page; the key or token may be refused
                list_error = _message(exc, source)
        wish_lists = wishlists.listing(db)
    return _page('web/toni/web/bw_sync.html', screen='link', title='Link ' + sync.LABELS[source], source=source,
                 label=sync.LABELS[source], status=status, user=user, key_gap=key_missing(source), lists=lists,
                 list_error=list_error, wish_lists=wish_lists)


@web_page.get('/manage/sync/<source>/plan/<plan_id>')
@login_required
def bw_sync_plan(source, plan_id):
    from ..core import sync
    _source(source)
    with _db() as db:
        try:
            plan = sync.load_plan(db, plan_id)
        except Exception as exc:
            flash(_message(exc, source), 'warning')
            return redirect(url_for('web.bw_sync'))
        if plan['source'] != source:
            abort(404)
        budget = _budget(db, source)
        status = sync.status(db, source)
    return _page('web/toni/web/bw_sync.html', screen=plan['direction'], title=('Pull from ' if plan['direction'] == 'pull' else 'Send to ') + sync.LABELS[source],
                 source=source, label=sync.LABELS[source], plan=plan, budget=budget, status=status,
                 results=plan.get('results', {}), receipt=request.args.get('event'))


def _message(exc, source):
    from ..core.sources.base import KeyRejected, SourceNotConfigured, WaitingForBudget
    from ..core.sync import LABELS
    if isinstance(exc, KeyRejected):
        return LABELS[source] + ' rejected the key or user token. Nothing was changed there.'
    if isinstance(exc, WaitingForBudget):
        return LABELS[source] + ' is paused: the daily budget is used up. Try again after ' + (exc.retry_at or 'midnight UTC')[:16].replace('T', ' ') + '.'
    if isinstance(exc, SourceNotConfigured):
        return str(exc) + '.'
    from .safe_errors import public
    return public(exc, LABELS[source] + ' could not be reached · nothing was changed. Try again.')


@web_page.post('/manage/sync/<source>/<action>')
@login_required
def bw_sync_write(source, action):
    from ..core import sync
    from ..core.sources.base import audit_origin
    _source(source)
    origin = request.headers.get('Origin')
    if origin and origin.rstrip('/') != request.host_url.rstrip('/') or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        abort(403)
    bw_add_csrf(request.form)
    if not bw_collection_editable():
        abort(403, 'Changes are switched off on this instance')
    form = request.form
    back = url_for('web.bw_sync_link', source=source)
    try:
        with _db() as db, audit_origin('app'):
            if action == 'connect':
                sync.connect(db, source, form.get('username', ''), form.get('password', ''))
                flash('Connected to ' + sync.LABELS[source] + ' · only the token is kept.', 'success')
            elif action == 'paste':
                sync.paste(db, source, form.get('value', '').strip())
                flash('Saved · the value is not shown again.', 'success')
            elif action == 'remove':
                sync.remove(db, source)
                flash('Removed the stored user token.', 'success')
            elif action == 'test':
                sync.test(db, source)
                flash(sync.LABELS[source] + ' accepted the user token.', 'success')
            elif action in ('link', 'pull'):
                if action == 'link':
                    options = {'wish_list': form.get('wish_list') or 'default'}
                    if source == 'rebrickable':
                        options['owned'] = [int(v) for v in form.getlist('owned') if v.isdigit()]
                        options['wishlist'] = int(form['wishlist']) if form.get('wishlist', '').isdigit() else None
                        send_to = form.get('send_to', '')
                        options['send_to'] = int(send_to) if send_to.isdigit() else (options['owned'][0] if len(options['owned']) == 1 else None)
                    sync.link(db, source, options)
                plan = sync.plan_pull(db, source)
                return redirect(url_for('web.bw_sync_plan', source=source, plan_id=plan['id']))
            elif action == 'send':
                plan = sync.plan_send(db, source)
                return redirect(url_for('web.bw_sync_plan', source=source, plan_id=plan['id']))
            elif action == 'apply':
                plan_id = form.get('plan_id', '')
                result = sync.apply_pull(db, plan_id, form.getlist('tick'))
                c = result['counts']
                if result.get('already_applied'):
                    flash('This plan was already pulled; nothing was added again.', 'info')
                    return redirect(url_for('web.bw_sync', pulled=result['event_id']))
                flash(f"Pulled · {c['copies']} {'copy' if c['copies'] == 1 else 'copies'}"
                      + (f", {c['stock']} loose" if c.get('stock') else '') + f" and {c['wishes_added'] + c['wishes_changed']} "
                      f"{'wish' if c['wishes_added'] + c['wishes_changed'] == 1 else 'wishes'} added here.", 'success')
                return redirect(url_for('web.bw_sync', pulled=result['event_id']))
            elif action == 'send_apply':
                plan_id = form.get('plan_id', '')
                sync.apply_send(db, plan_id, form.getlist('tick'))
                return redirect(url_for('web.bw_sync_plan', source=source, plan_id=plan_id))
            elif action == 'undo':
                event = form.get('event', '')
                if not event.isdigit():
                    abort(400)
                sync.undo(db, int(event))
                flash('Pull undone.', 'success')
                return redirect(url_for('web.bw_sync'))
            else:
                abort(404)
    except (ValueError, sqlite3.Error) as exc:
        flash(_message(exc, source), 'warning')
        if action in ('apply', 'send_apply') and form.get('plan_id'):
            return redirect(url_for('web.bw_sync_plan', source=source, plan_id=form['plan_id']))
        if action == 'undo':
            return redirect(url_for('web.bw_sync'))
    return redirect(back)
