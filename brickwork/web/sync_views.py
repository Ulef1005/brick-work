"""12n Collection sync pages (#10): sources, link, pull preview, send review. Services live in core.sync."""
from contextlib import closing
import json
import re
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


def _log(db, limit=20, source=None):
    """Sync log rows from the receipts, their undos and the send records, newest first.
    With a source, only that site's rows (an undo counts for the site of the pull it undid), read until `limit` of them are found."""
    rows = []
    seen_sends = set()
    for r in db.execute("""SELECT e.id, e.entity_id, e.field, e.new_value, e.at, EXISTS(SELECT 1 FROM event_undo u WHERE u.event_id=e.id) AS undone
            FROM event e WHERE e.entity_kind='sync' AND e.field IN ('receipt', 'undo', 'send', 'parts_receipt') ORDER BY e.id DESC"""):
        if len(rows) >= limit:              # read until `limit` rows are found: a long run records every call, and those collapse into one row
            break
        value = json.loads(r['new_value']) if r['new_value'] else None
        site = _row_source(db, r, value)
        if source is not None and site != source:
            continue
        if r['field'] == 'parts_receipt':
            c = value.get('counts', {})
            rows.append(dict(id=r['id'], at=r['at'], source='rebrickable', direction='Pulled', event=r['id'], state='Undone' if r['undone'] else 'Done',
                             what=f"{c.get('pieces', 0)} loose {'piece' if c.get('pieces') == 1 else 'pieces'} added from {c.get('rows', 0)} part list {'row' if c.get('rows') == 1 else 'rows'}"))
        elif r['field'] == 'receipt':
            c = value.get('counts', {})
            what = ' · '.join(p for p in (
                f"{c.get('copies', 0)} {'copy' if c.get('copies') == 1 else 'copies'} added" if c.get('copies') else '',
                f"{c.get('stock', 0)} loose added" if c.get('stock') else '',
                f"{c.get('wishes_added', 0)} {'wish' if c.get('wishes_added') == 1 else 'wishes'} added" if c.get('wishes_added') else '',
                f"{c.get('wishes_changed', 0)} wish quantities raised" if c.get('wishes_changed') else '',
                _lost_words(c)) if p) or 'Nothing new'
            rows.append(dict(id=r['id'], at=r['at'], source=value['source'], direction='Pulled', what=what, state='Undone' if r['undone'] else 'Done', event=r['id']))
        elif r['field'] == 'undo':
            rows.append(dict(id=r['id'], at=r['at'], source=site, direction='Undone', what='Pull ' + str(value['undoes']) + ' undone', state='Done', event=None))
        else:
            if (value or {}).get('plan') is not None and (value or {}).get('plan') in seen_sends:      # a long run sends one call at a time and records each: the newest record of a send plan stands for it
                continue
            seen_sends.add((value or {}).get('plan'))
            counts = (value or {}).get('counts', {})
            sent = counts.get('sent', 0) + counts.get('unchanged', 0)
            problems = {k: v for k, v in counts.items() if k not in ('sent', 'unchanged')}
            what = ('Lost Parts: ' if (value or {}).get('kind') == 'lost_parts' else '') + f"{sent} {'change' if sent == 1 else 'changes'} sent" + ''.join(f" · {v} {k.replace('_', ' ')}" for k, v in problems.items())
            interrupted = bool((value or {}).get('interrupted'))
            state = 'Interrupted' if interrupted else 'Done' if not problems else 'Waiting for you'
            rows.append(dict(id=r['id'], at=r['at'], source=r['entity_id'], direction='Sent', what=what, state=state, event=None, lost=(value or {}).get('kind') == 'lost_parts',
                             run=(value or {}).get('run')))
    return rows[:limit]


def _event_id(value):
    """An event id from a query or form value: ASCII digits that fit SQLite's integer, else None (never a 500 on '²' or a 30-digit id)."""
    text = str(value or '')
    return int(text) if re.fullmatch(r'[0-9]{1,18}', text) else None


def _receipt_source(db, event_id):
    """The site of one pull receipt ('' when the id names no receipt)."""
    event_id = _event_id(event_id)
    if event_id is None:
        return ''
    row = db.execute("SELECT new_value FROM event WHERE id=? AND entity_kind='sync' AND field IN ('receipt', 'parts_receipt')", (event_id,)).fetchone()
    return ((json.loads(row['new_value']) if row and row['new_value'] else {}) or {}).get('source', '') or ('rebrickable' if row else '')


def _row_source(db, r, value):
    """The site a log event belongs to: a receipt names it, a send keeps it as its entity id, an undo takes it from the pull it undid."""
    if r['field'] == 'receipt':
        return (value or {}).get('source', '')
    if r['field'] == 'parts_receipt':
        return 'rebrickable'
    if r['field'] == 'undo':
        return _receipt_source(db, (value or {}).get('undoes'))
    return r['entity_id']


def _lost_words(c):
    """The Lost Parts part of a log line: parts marked on how many sets."""
    marked = c.get('lost_added', 0) + c.get('lost_replaced', 0)
    if not c.get('lost_sets'):
        return ''
    words = f"Lost Parts: {marked} {'part' if marked == 1 else 'parts'} marked on {c['lost_sets']} {'set' if c['lost_sets'] == 1 else 'sets'}"
    return words + (f", {c['lost_cleared']} cleared" if c.get('lost_cleared') else '')


def lost_result(db, event_id):
    """The Lost Parts step of one pull as its receipt kept it (None: that pull had none), for the result card."""
    event_id = _event_id(event_id)
    if event_id is None:
        return None
    row = db.execute("SELECT new_value FROM event WHERE id=? AND entity_kind='sync' AND field='receipt'", (event_id,)).fetchone()
    return (json.loads(row['new_value']) if row and row['new_value'] else {}).get('lost')


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


_SITE_DESCRIPTIONS = {
    'rebrickable': 'Set lists, wishlist, part lists and Lost Parts; minifigures as a check',
    'brickset': 'Owned and wanted sets with their counts',
    'bricklink': 'Orders into Orders, the price guide; store inventory and wanted lists by file follow',
    'brickowl': 'Collection lots, wishlists, inventory, orders; a daily budget per kind',
}


def _last_sync(status):
    """Newest pull or send time formatted with stamp, or 'Never'. Compared as instants: a pull is stamped '…Z', a send '…+00:00'."""
    from datetime import datetime

    from datetime import timezone

    def instant(value):   # as a UTC instant (a stamp without an offset counts as UTC, as stored)
        try:
            moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return datetime.min
        return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo else moment
    times = [t for t in ((status.get('last_pull') or {}).get('at'), (status.get('last_send') or {}).get('at')) if t]
    return stamp(max(times, key=instant)) if times else 'Never'


def _state_tag(status, connected):
    """Second tag for a connected site when status carries a waiting count."""
    if not connected or 'waiting' not in status or status['waiting'] is None:
        return None
    waiting = status['waiting']
    if waiting:
        return dict(text=f"{waiting} {'change' if waiting == 1 else 'changes'} waiting", dashed=True)
    if status.get('last_pull') or status.get('last_send'):
        return dict(text='In sync', dashed=False)
    return None


def _last_import(db):
    """Newest file-import receipt time formatted with stamp, or 'Never'."""
    row = db.execute("SELECT at FROM event WHERE field='receipt' AND entity_kind IN ('import', 'add') ORDER BY id DESC LIMIT 1").fetchone()
    return stamp(row['at']) if row and row['at'] else 'Never'


def _last_bricklink_sync(db):
    """Newest BrickLink run time formatted with stamp, or 'Never'."""
    row = db.execute("SELECT at FROM main.event WHERE entity_kind='sync' AND entity_id='bricklink' AND field='run' ORDER BY id DESC LIMIT 1").fetchone()
    return stamp(row['at']) if row and row['at'] else 'Never'


@web_page.get('/workbench/sync')
@login_required
@_unavailable
def bw_sync_hub():
    from flask import current_app
    from ..core import sync
    with _db() as db:
        sites = []
        for source in ('rebrickable', 'brickset'):
            status = sync.status(db, source)
            connected = bool(status['credentials']['user']['configured'])
            sites.append(dict(
                key=source, label=sync.LABELS[source], description=_SITE_DESCRIPTIONS[source],
                connected=connected, state_tag=_state_tag(status, connected),
                account=(status.get('account') or 'Linked') if connected else 'none', last_sync=_last_sync(status),      # #686: the account name when it is known
                action_label='Open' if connected else 'Connect',
                url=url_for('web.bw_sync_site', source=source) if connected else url_for('web.bw_sync_rb_connect' if source == 'rebrickable' else 'web.bw_sync_bs_connect'),
            ))
        from ..core import keys
        bl_connected = bool(keys.state(db, 'bricklink')['configured'])
        sites.append(dict(
            key='bricklink', label='BrickLink', description=_SITE_DESCRIPTIONS['bricklink'],
            connected=bl_connected, state_tag=None,
            account='Linked' if bl_connected else 'none', last_sync=_last_bricklink_sync(db),
            action_label='Open' if bl_connected else 'Connect',
            url=url_for('web.bw_sync_bl_site') if bl_connected else url_for('web.bw_sync_bl_connect'),
        ))
        keys_url = url_for('web.bw_admin', page='catalogues')
        sites.append(dict(
            key='brickowl', label='Brick Owl', description=_SITE_DESCRIPTIONS['brickowl'],
            connected=False, state_tag=None, account='none', last_sync='Never',
            action_label='Connect', url=keys_url,
        ))
        import_url = url_for('web.bw_import_legacy') if 'web.bw_import_legacy' in current_app.view_functions else url_for('web.bw_add', mode='file')
        import_export = dict(last_import=_last_import(db), last_export='Never', url=import_url)
        log = _log(db)
    return _page('web/toni/web/bw_sync_hub.html', title='Sync', sites=sites, import_export=import_export, log=log)


@web_page.get('/workbench/sync/<source>')
@login_required
@_unavailable
def bw_sync_site(source):
    from .sync_site import site_page
    _source(source)
    return site_page(source)   # both sites have the six-step pages of web/sync_site.py (#519, #520)


@web_page.get('/manage/sync')
@login_required
@_unavailable
def bw_sync():
    pulled = request.args.get('pulled')
    if pulled:
        source = 'rebrickable'
        with _db() as db:
            row = db.execute("SELECT new_value FROM event WHERE id=? AND entity_kind='sync' AND field='receipt'", (_event_id(pulled) or 0,)).fetchone()
        if row and row['new_value']:
            found = json.loads(row['new_value']).get('source')
            source = found if found in SOURCES else source
        return redirect(url_for('web.bw_sync_site', source=source, pulled=pulled))
    return redirect(url_for('web.bw_sync_hub'))


@web_page.get('/manage/sync/<source>/link')
@login_required
@_unavailable
def bw_sync_link(source):
    _source(source)
    return redirect(url_for('web.bw_sync_rb_connect' if source == 'rebrickable' else 'web.bw_sync_bs_connect'))   # the account and the choices are steps 1 and 2 of the site's page (#519, #520)


@web_page.get('/manage/sync/<source>/plan/<plan_id>')
@login_required
def bw_sync_plan(source, plan_id):
    from ..core import sync
    from ..core.sync import lost_parts
    _source(source)
    with _db() as db:
        try:
            plan = sync.load_plan(db, plan_id)
        except Exception as exc:
            flash(_message(exc, source), 'warning')
            return redirect(url_for('web.bw_sync_site', source=source))
        if plan['source'] != source:
            abort(404)
        budget = _budget(db, source)
        status = sync.status(db, source)
    return _page('web/toni/web/bw_sync.html', screen=plan['direction'], title=('Pull from ' if plan['direction'] == 'pull' else 'Send to ') + sync.LABELS[source],
                 source=source, label=sync.LABELS[source], plan=plan, budget=budget, status=status,
                 results=plan.get('results', {}), receipt=request.args.get('event'), rule_labels=lost_parts.RULE_LABELS)


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
    if form.get('next') in ('site', 'connect'):   # a site's page and its connect step keep their own account buttons (#519, #520)
        back = url_for('web.bw_sync_site' if form['next'] == 'site' else 'web.bw_sync_rb_connect' if source == 'rebrickable' else 'web.bw_sync_bs_connect',
                       **({} if form['next'] == 'connect' else {'source': source}))
    try:
        with _db() as db, audit_origin('app'):
            if action == 'connect':
                sync.connect(db, source, form.get('username', ''), form.get('password', ''))
                flash('Connected to ' + sync.LABELS[source] + ' · only the token and your username are kept.', 'success')
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
                # The switch posts a hidden 0 before its checkbox's 1: the last value wins, and a form without the field keeps the remembered one.
                switch = form.getlist('lost_parts')[-1:] if action == 'pull' else []
                plan = sync.plan_pull(db, source, lost_parts_switch=(switch[0] == '1') if switch else None)
                return redirect(url_for('web.bw_sync_plan', source=source, plan_id=plan['id']))
            elif action == 'send':
                plan = sync.plan_send(db, source)
                return redirect(url_for('web.bw_sync_plan', source=source, plan_id=plan['id']))
            elif action == 'apply':
                plan_id = form.get('plan_id', '')
                picks = {k.removeprefix('copy:'): v for k, v in form.items() if k.startswith('copy:') and v}
                result = sync.apply_pull(db, plan_id, form.getlist('tick'), lost=form.getlist('lost') if form.get('lost_listed') else None,
                                         picks=picks or None)
                c = result['counts']
                if result.get('already_applied'):
                    flash('This plan was already pulled; nothing was added again.', 'info')
                    return redirect(url_for('web.bw_sync_site', source=source, pulled=result['event_id']))
                flash(f"Pulled · {c['copies']} {'copy' if c['copies'] == 1 else 'copies'}"
                      + (f", {c['stock']} loose" if c.get('stock') else '') + f" and {c['wishes_added'] + c['wishes_changed']} "
                      f"{'wish' if c['wishes_added'] + c['wishes_changed'] == 1 else 'wishes'} added here." + (' ' + _lost_words(c) + '.' if c.get('lost_sets') else ''), 'success')
                return redirect(url_for('web.bw_sync_site', source=source, pulled=result['event_id']))
            elif action == 'send_apply':
                plan_id = form.get('plan_id', '')
                sync.apply_send(db, plan_id, form.getlist('tick'))
                return redirect(url_for('web.bw_sync_plan', source=source, plan_id=plan_id))
            elif action == 'undo':
                event = _event_id(form.get('event', ''))
                if event is None:
                    abort(400)
                if _receipt_source(db, event) != source:   # a pull of another site is undone from its own page
                    abort(404)
                sync.undo(db, event)
                flash('Pull undone.', 'success')
                return redirect(url_for('web.bw_sync_site', source=source))
            else:
                abort(404)
    except (ValueError, sqlite3.Error) as exc:
        flash(_message(exc, source), 'warning')
        if action in ('apply', 'send_apply') and form.get('plan_id'):
            return redirect(url_for('web.bw_sync_plan', source=source, plan_id=form['plan_id']))
        if action == 'undo':
            return redirect(url_for('web.bw_sync_site', source=source))
    return redirect(back)
