"""One BrickLink orders run (#521): choices, candidate orders, preview rows and pulling chosen orders into Orders.

A BrickLink run keeps the same run-record shape as `core.sync.run` so the sync pages and `run.undo_run` handle it, without adding
`'bricklink'` to the set-sync `SOURCES` or `ADAPTERS`. Orders come in through `orders.api_data` and `orders.import_document`; the price
guide region stays in `price_settings`.
"""
from datetime import date
import json
import sqlite3
from uuid import uuid4

from .. import errors, orders, price_settings
from .. import sync
from ..admin import audit
from ..sources.base import KeyRejected, SourceError, WaitingForBudget, now
from ..sources.bricklink import BrickLink
from ..transaction import transaction
from . import run as sync_run

SOURCE = 'bricklink'
CHOICES_KEY = 'bricklink_sync_choices'
STATUSES = (('received_paid', 'Received and paid', {'RECEIVED', 'PAID'}), ('all', 'All orders', None))
ORDERS_DIRS = ('into', 'off')
FAILURES = (errors.BrickWorkError, ValueError, SourceError, KeyRejected, WaitingForBudget, sqlite3.Error)
REMOTE_FAILURES = tuple(e for e in FAILURES if e is not sqlite3.Error)
_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
_STATUS_SETS = {key: allowed for key, _, allowed in STATUSES}


def _setting_row(db, key):
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (key,)).fetchone()
    return row[0] if row else None


def _put_setting(db, key, value):
    if value is None:
        db.execute('DELETE FROM main.setting WHERE key=?', (key,))
    else:
        db.execute('INSERT OR REPLACE INTO main.setting(key, value) VALUES(?, ?)', (key, value))


def _valid_date(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == value else None


def choices(db):
    """The saved step-2 choices for BrickLink orders; any stored value that does not fit falls back to its default."""
    try:
        saved = json.loads(_setting_row(db, CHOICES_KEY) or '{}')
    except (ValueError, TypeError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    orders_dir = saved.get('orders') if saved.get('orders') in ORDERS_DIRS else 'into'
    status = saved.get('status') if saved.get('status') in _STATUS_SETS else 'received_paid'
    since = _valid_date(saved.get('since'))
    since_on = saved.get('since_on') is True and since is not None
    return dict(orders=orders_dir, since_on=since_on, since=since, status=status)


def save_choices(db, form):
    """Validate and save the BrickLink step-2 choices and price region in one audited transaction."""
    orders_dir = form.get('orders_dir')
    if orders_dir not in ORDERS_DIRS:
        raise errors.ValidationFailed('Choose a direction for orders')
    status = form.get('status')
    if status not in _STATUS_SETS:
        raise errors.ValidationFailed('Choose which orders to include')
    raw_since_on = form.get('since_on')
    if raw_since_on not in (None, '', '0', '1', False, True):
        raise errors.ValidationFailed('Choose whether to filter by date')
    since_on = raw_since_on in ('1', True)
    raw_since = form.get('since')
    if raw_since is not None and not isinstance(raw_since, str):
        raise errors.ValidationFailed('Choose a valid start date')
    raw_since = (raw_since or '').strip()
    if since_on:
        since = _valid_date(raw_since)
        if since is None:
            raise errors.ValidationFailed('Choose a valid start date')
    elif raw_since:
        since = _valid_date(raw_since)
        if since is None:
            raise errors.ValidationFailed('Choose a valid start date')
    else:
        since = None
    region = None
    if 'region' in form:
        region = form.get('region')
        if region not in price_settings.REGIONS:
            raise errors.ValidationFailed('Choose a BrickLink region')
        if price_settings.region_locked():
            if region != price_settings.read(db)['bricklink_region']:
                raise errors.ValidationFailed('The price region is locked on this install')
            region = None
    with transaction(db):
        before = dict(choices=_setting_row(db, CHOICES_KEY), region=price_settings.read(db)['bricklink_region'])
        if region is not None:
            price_settings.save(db, {'bricklink_region': region})
        saved = json.dumps(dict(orders=orders_dir, since_on=since_on, since=since, status=status), sort_keys=True)
        _put_setting(db, CHOICES_KEY, saved)
        audit(db, 'sync:' + SOURCE, 'choices', before, dict(choices=saved, region=region or before['region']))
    return choices(db)


def what_syncs(db):
    """The rows of the What syncs table of the BrickLink page at rest: no call to BrickLink."""
    saved = choices(db)
    rows_out = []
    if saved['orders'] != 'off':
        rows_out.append(dict(what='Orders', direction='Into Brick Work', linked='Pulled into Orders'))
    rows_out.append(dict(what='Price guide', direction='Into Brick Work', linked='Used for prices and Complete sets'))
    rows_out.append(dict(what='Wanted lists', direction='By file', linked='The page builds the XML; BrickLink has no wanted-list API'))
    return rows_out


def budget(db, client=None):
    try:
        status = (BrickLink(db) if client is None else client).status()
        return dict(used=status['used_today'], budget=status['budget'], last_success=status['last_success'], key=status['key_state'])
    except Exception:
        return None


def _imported_ids(db):
    return {str(r[0]) for r in db.execute('SELECT bricklink_order_id FROM main.purchase_order WHERE bricklink_order_id IS NOT NULL')}


def start(db, *, client=None):
    """Fetch matching BrickLink order headers and store the run. Writes nothing to the collection."""
    saved = choices(db)
    if saved['orders'] == 'off':
        raise errors.ValidationFailed('Orders are switched off')
    client = BrickLink(db) if client is None else client
    allowed = _STATUS_SETS[saved['status']]
    kept = []
    for header in client.list_orders() or ():
        order_id = header.get('order_id')
        if order_id is None or str(order_id) == '':
            continue
        status = str(header.get('status') or '')
        if allowed is not None and status.upper() not in allowed:
            continue
        day = str(header.get('date_ordered') or '')[:10]
        if saved['since_on'] and saved['since'] and day < saved['since']:
            continue
        kept.append(header)
    kept.sort(key=lambda h: (str(h.get('date_ordered') or ''), str(h['order_id'])), reverse=True)
    imported = _imported_ids(db)
    candidates = []
    for header in kept:
        oid = str(header['order_id'])
        cost = header.get('cost') if isinstance(header.get('cost'), dict) else {}
        candidates.append(dict(id=oid, label='Order ' + oid, date=str(header.get('date_ordered') or '')[:10],
                               status=header.get('status') or '', lots=header.get('unique_count') or 0,
                               total=cost.get('grand_total'), currency=cost.get('currency_code') or None,
                               imported=oid in imported))
    run = dict(id=uuid4().hex, created_at=now().isoformat(), direction='run', source=SOURCE,
               choices=saved, candidates=candidates, headers=kept, picked=None, stages={})
    return sync._save_plan(db, run)


def load(db, run_id):
    run = sync.load_plan(db, run_id, 'run')
    if run.get('source') != SOURCE:
        raise errors.ValidationFailed('This run is not a BrickLink run')
    return run


def save_pick(db, run_id, ids):
    run = load(db, run_id)
    if run.get('applied'):
        raise errors.ValidationFailed('This run has already run')
    ids = set(ids)
    if ids - {c['id'] for c in run['candidates']}:
        raise errors.ValidationFailed('Pick orders from the list')
    run['picked'] = sorted(ids)
    sync._store_plan(db, run)
    return run


def _short_date(day):
    valid = _valid_date(day)
    if valid is None:
        return day or ''
    parsed = date.fromisoformat(valid)
    return f'{parsed.day} {_MONTHS[parsed.month - 1]}'


def _detail(candidate):
    status = candidate.get('status') or ''
    status_text = status.replace('_', ' ').capitalize() if status else ''
    date_text = _short_date(candidate.get('date') or '')
    head = ' '.join(part for part in (status_text, date_text) if part)
    parts = [head] if head else []
    lots = candidate.get('lots') or 0
    if lots:
        parts.append(f"{lots} {'lot' if lots == 1 else 'lots'}")
    total = candidate.get('total')
    if total not in (None, ''):
        currency = candidate.get('currency')
        parts.append(f'{total} {currency}' if currency else str(total))
    return ' · '.join(parts)


def rows(db, run):
    """Preview rows for the picked candidates (or all candidates before a pick): `new` orders offer Pull in, imported ones are `same`."""
    picked = None if run.get('picked') is None else set(run['picked'])
    imported = _imported_ids(db)
    out = []
    for c in run['candidates']:
        if picked is not None and c['id'] not in picked:
            continue
        state = 'same' if (c.get('imported') or c['id'] in imported) else 'new'
        out.append(dict(key='order:' + c['id'], id=c['id'], label=c['label'], detail=_detail(c), state=state,
                        options=[dict(id='pull', label='Pull in', note=None)] if state == 'new' else [],
                        default='pull' if state == 'new' else None))
    return out


def _message(exc):
    if isinstance(exc, KeyRejected):
        return 'BrickLink rejected the key or token.'
    if isinstance(exc, WaitingForBudget):
        return 'BrickLink is paused: the daily budget is used up. Try again after ' + (exc.retry_at or 'midnight UTC')[:16].replace('T', ' ') + '.'
    if isinstance(exc, SourceError):
        return str(exc) or 'BrickLink could not be reached.'
    return str(exc) or 'This order could not be imported.'


def apply(db, run_id, form, *, client=None, via=None, actor=None):
    """Pull each ticked new order into Orders using the headers cached at `start`, recording one stage per order and one run audit row."""
    with sync_run._Claim(db, run_id):
        run = load(db, run_id)
        if run.get('applied'):
            return run
        wanted = [r['id'] for r in rows(db, run) if r['state'] == 'new' and form.get(r['key']) == 'pull']
        if wanted and client is None:
            client = BrickLink(db)
        headers = run.get('headers')
        events = []
        for order_no in wanted:
            try:
                prepared = orders.api_data(db, order_no, client=client, headers=headers)
                result = orders.import_document(db, 'api', number=order_no, prepared=prepared)
            except REMOTE_FAILURES as exc:
                run['stages'][order_no] = dict(status='failed', message=_message(exc))
            else:
                run['stages'][order_no] = dict(status='done', order_id=result['order_id'], placed=result['placed'],
                                               unplaced=result['unplaced'], event=result['event_id'])
                if not result['duplicate'] and result['event_id'] is not None:
                    events.append(result['event_id'])
            sync._store_plan(db, run)
        with transaction(db):
            audit(db, 'sync:' + SOURCE, 'run', None, dict(run=run['id'], events=events), via=via, actor=actor)
        run['applied'] = True
        sync._store_plan(db, run)
        return run
