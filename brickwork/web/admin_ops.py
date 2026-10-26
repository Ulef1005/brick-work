"""Standalone admin services shared by CLI and browser; core store only."""
import os
import logging
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from flask import current_app

from ..core.secrets import secret_values


SETUP_REQUIRED = "Database not set up. Run 'brickwork setup'."


def _media_root():
    from ..core.media import root_for
    return root_for(brickwork_path())


def settings_show():
    from ..core.connect import connect
    from ..core.price_settings import read
    with closing(connect(brickwork_path(), read_only=True)) as db:
        return read(db)


def settings_set(key, value):
    if key == 'source_priority' or key.startswith('import_order:'):
        from ..core.connect import connect
        from ..core.pipeline import validate_priority, STEPS, TYPES
        from ..core.sources.base import write
        import json
        parsed = json.loads(value)
        if key == 'source_priority':
            validate_priority(parsed)
        elif (key.removeprefix('import_order:') not in TYPES or not isinstance(parsed, list)
              or any(not isinstance(s, str) for s in parsed) or len(parsed) != len(STEPS) or set(parsed) != set(STEPS)):
            raise ValueError('import order must contain all six steps once')
        with closing(connect(brickwork_path())) as db, db:
            write(db, 'INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(parsed)))
        return {key: parsed}
    if key not in ('retail_country', 'bricklink_region', 'bricklink_currency', 'incomplete_discount_pct'):
        raise ValueError('unsupported setting')
    if key == 'retail_country':
        from ..core.connect import connect
        from ..core.sources.base import write
        from ..core.sources.brickset import CURRENCIES
        if value not in CURRENCIES:
            raise ValueError('unsupported retail country')
        with closing(connect(brickwork_path())) as db, db:
            write(db, 'INSERT OR REPLACE INTO settings VALUES(?,?)', (key, value))
        return {key: value}
    value = int(value) if key == 'incomplete_discount_pct' else value
    from ..core.connect import connect
    from ..core.price_settings import save
    with closing(connect(brickwork_path())) as db:
        return save(db, {key: value})


def migrate(app, decisions, catalogue, out, report, extras=None, replace=False, catalogue_src=None):
    """Offline migration service; deliberately needs no Flask or live DB setup."""
    from ..core.importer import import_collection as run
    result = run(app, extras, decisions, catalogue, out, report, replace=replace, catalogue_src=catalogue_src)
    return {'ok': result['ok'], 'proof': str(Path(report) / 'proof.md'),
            'runtime_seconds': result['runtime_seconds'], 'output_bytes': result['output_bytes'],
            'tables': {table: {key: row[key] for key in ('expected', 'actual', 'checksum_ok')}
                       for table, row in result['tables'].items()},
            'review_counts': result['review_counts'], 'unnamed_items': result['unnamed_items']}


# New source commands operate only on brickwork.db and the rebuildable BL index.
def brickwork_path():
    from ..core.pipeline import database_path
    return database_path()


def catalogue_status():
    from ..core.sources.bricklink_catalogue import info
    return {'bricklink': info(brickwork_path().with_name('bricklink-catalog.db'))}


def catalogue_import_bricklink(directory):
    from ..core.connect import connect
    from ..core.sources.bricklink_catalogue import load
    with closing(connect(brickwork_path())) as db:
        return load(directory, brickwork_path().with_name('bricklink-catalog.db'), db)


def prices_refresh(set_num):
    from ..core.connect import connect
    from ..core.sources.bricklink import BrickLink
    from ..core.sources.base import WaitingForBudget
    with closing(connect(brickwork_path())) as db:
        try:
            result = BrickLink(db).price_slots('S', set_num)
            return {'set_num': set_num, 'ok': True, 'slots': result}
        except WaitingForBudget as error:
            return {'set_num': set_num, 'state': 'waiting_for_budget', 'job_id': error.job_id}


def brickset_refresh(sets):
    from ..core.connect import connect
    from ..core.sources.brickset import Brickset
    from ..core.sources.base import WaitingForBudget
    with closing(connect(brickwork_path())) as db:
        try:
            return {'sets': Brickset(db).refresh(sets), 'state': 'done'}
        except WaitingForBudget as error:
            return {'state': 'waiting_for_budget', 'job_id': error.job_id}


CATALOGUE_NAMES = {'bricklink_catalogue': 'BrickLink catalogue', 'import': 'Import pipeline'}
KEY_LABELS = {'key': 'API key', 'token_value': 'Token'}
PICTURE_ROWS = (('Sets and wishlist', 'S'), ('Minifigures', 'M'), ('Parts per colour', 'P'))


def _field_label(name):
    return KEY_LABELS.get(name) or name.replace('_', ' ').capitalize()


def catalogues_view(data, key_fields, key_entry, result=None, replace=None):
    """Everything the Catalogues & keys page shows, prepared once; no key value is ever read.

    `result` is the one-shot outcome of the last key action ({source, state, message|event}).
    """
    from ..core.pipeline import NAMES
    from .formatting import short_stamp
    result = result or {}
    refused = result.get('source') if result.get('state') == 'rejected' else None
    # A refused replacement leaves the saved key as it was: only the card reports it.
    rejected = None if result.get('replacement') else refused
    restore_note = ' · The earlier key could not be restored; use Test key to check the stored key.' if result.get('restore_failed') else ''
    sources, banners = [], []
    for row in data['sources']:
        source = row['source']
        name = row['name'] if row.get('name') and row['name'] != source else CATALOGUE_NAMES.get(source, source.replace('_', ' ').capitalize())
        keyed = source in key_fields
        configured = bool((row.get('key_state') or {}).get('configured'))
        if source == rejected:
            pill = ('danger', 'Rejected')
            banners.append(('danger', name + ' key rejected.' + (' Prices are not updating.' if source == 'bricklink' else '')))
        elif not keyed:
            pill = ('neutral', 'No key needed')
        else:
            pill = ('success', 'Configured') if configured else ('neutral', 'Not set')
        used, budget = row.get('used_today') or 0, row.get('budget')
        exhausted = budget is not None and budget > 0 and used >= budget
        if exhausted and row.get('enabled'):
            banners.append(('warning', name + ' budget used up for today. ' + ('Price updates' if source == 'bricklink' else 'Updates') + ' wait until 00:00 UTC.'))
        error = row.get('last_error')
        sources.append(dict(source=source, name=name, pill=pill, enabled=bool(row.get('enabled')), exhausted=exhausted,
            budget=f"{used} / {budget if budget is not None else 'No cap'}", used=used,
            success=short_stamp(row.get('last_success'), True) if row.get('last_success') else None,
            error=(str(error['error']) + ' · ' + short_stamp(error['updated_at'])) if error else None))
    keys = []
    for source, fields in key_fields.items():
        row = next((r for r in data['sources'] if r['source'] == source), {})
        state = row.get('key_state') or {}
        name = next((s['name'] for s in sources if s['source'] == source), source.capitalize())
        card = dict(source=source, name=name, fields=[(f, _field_label(f)) for f in fields], message=None,
                    saved=short_stamp(state.get('saved_at')) if state.get('saved_at') else None)
        if result.get('source') == source and result.get('state') == 'removed':
            card.update(mode='removed', pill=('neutral', 'Removed'), event=result.get('event'))
        elif state.get('configured') and state.get('origin') == 'env':
            card.update(mode='env', pill=('danger', 'Rejected') if source == rejected else ('success', 'Configured'),
                        message=result.get('message') if source == refused else None)
        elif state.get('configured') and not (replace == source and key_entry):
            card.update(mode='stored', pill=('danger', 'Rejected') if source == rejected else ('success', 'Configured'),
                        can_replace=bool(key_entry),
                        message=(('New key rejected: ' + result.get('message') + ' · the saved key is unchanged')
                                 if result.get('replacement') else result.get('message') + restore_note) if source == refused else None)
        elif not key_entry:
            card.update(mode='disabled', pill=('neutral', 'Not set'))
        elif source == refused:
            card.update(mode='entry', pill=('danger', 'Rejected'), message=result.get('message'))
        else:
            card.update(mode='entry', pill=('success', 'Configured') if state.get('configured') else ('neutral', 'Not set'),
                        replacing=bool(state.get('configured')))
        keys.append(card)
    if not any(c['mode'] in ('env', 'stored') for c in keys):
        banners.append(('warning', 'No keys yet. Names, prices and pictures need at least a Rebrickable key.'))
    catalogue = data['catalogue']
    loaded = bool(catalogue.get('available'))
    counts = catalogue.get('counts') or {}
    labels = (('S', 'Sets'), ('M', 'Minifigures'), ('P', 'Parts'), ('I', 'Instructions'), ('O', 'Boxes'), ('G', 'Gear'), ('B', 'Books'), ('C', 'Catalogues'))
    colours = data['colours']
    freshness = []
    for rule in data['freshness']:
        days = rule['max_age_days']
        freshness.append(dict(label=CATALOGUE_NAMES.get(rule['source']) or NAMES.get(rule['source']) or rule['source'].capitalize(), kind=rule['kind'],
                              days=None if days is None else f"{days} {'day' if days == 1 else 'days'}"))
    order = (data.get('priority') or {}).get('pictures', {})
    pictures = [(label, [NAMES.get(s, s) for s in order.get(kind, order.get('*', []))]) for label, kind in PICTURE_ROWS]
    return dict(sources=sources, key_cards=keys, banners=banners, pictures=pictures, freshness=freshness,
                catalogue=dict(loaded=loaded, stamp=short_stamp(catalogue.get('loaded_at')) if loaded else None,
                               types=sum(1 for v in counts.values() if v), names=f"{sum(counts.values()):,}" if loaded else '0',
                               colours=colours['total'], gap=colours['total'] - colours['with_rgb'], with_rgb=colours['with_rgb'],
                               rows=[(label, f"{counts.get(t, 0):,}" if loaded else '0') for t, label in labels]))


def key_test_save(db, source, values):
    """Save a key, prove it with one budgeted call, and take it back only if the source refuses it.

    Returns {tested, reason}. Only an authoritative refusal (KeyRejected) restores the earlier state,
    using the receipt of this very save, and is re-raised with `replacement` saying whether a stored
    key existed before. Any other failure (network, server, budget, disabled source) keeps the key.
    """
    from ..core import keys
    from ..core.sources.base import KeyRejected, SourceDisabled, SourceError, WaitingForBudget, redact
    replacement = keys.state(db, source)['origin'] == 'stored'
    receipt = []
    keys.save(db, source, values, receipt)
    try:
        keys.check(db, source)
    except SourceDisabled:
        return dict(tested=False, reason='the source is disabled')
    except WaitingForBudget:
        return dict(tested=False, reason='its daily budget is used up')
    except KeyRejected as exc:
        exc.replacement = replacement
        exc.restore_failed = False
        try:
            if not receipt or receipt[0] is None:
                raise ValueError('no receipt for this save')
            row = db.execute('SELECT id,entity,field,new_value FROM events WHERE id=?', (receipt[0],)).fetchone()
            keys.undo(db, row['id'], dict(row))
        except Exception as failure:
            # The refusal still stands; say that the earlier key could not be put back.
            exc.restore_failed = True
            logging.getLogger(__name__).error('key rollback failed for %s (%s)', source, type(failure).__name__)
        raise
    except SourceError as exc:
        return dict(tested=False, reason=redact(exc))
    return dict(tested=True, reason=None)


def sources_status():
    from ..core.sources.bricklink import BrickLink
    from ..core.sources.brickset import Brickset
    from ..core.sources.rebrickable import Rebrickable
    from ..core.sources.bricklink_catalogue import BrickLinkCatalogue
    from ..core.sources.base import budget_used
    path = brickwork_path()
    if not path.exists():
        # Status must not create a database merely to report unset/unused keys.
        result = {}
        for client in (BrickLink, Brickset, BrickLinkCatalogue, Rebrickable):
            instance = client(None)
            result[client.source] = dict(key='set' if instance.configured() else 'unset',
                key_state=instance.status_key(), budget=instance.daily_budget, used_today=0, last_success=None)
        return result
    from ..core.admin import database
    with database(path, read_only=True) as db:
        result = {cls.source: cls(db).status() for cls in (BrickLink, Brickset, BrickLinkCatalogue, Rebrickable)}
        for row in db.execute('SELECT source FROM sources'):
            source = row['source']
            if source in result:
                continue
            budget = db.execute('SELECT value FROM settings WHERE key=?', ('source:budget:' + source,)).fetchone()
            day = datetime.now(timezone.utc).date().isoformat()
            used = budget_used(db, source, day)
            last = db.execute("SELECT max(updated_at) FROM jobs WHERE source=? AND state='done'", (source,)).fetchone()[0]
            result[source] = dict(key='unset', budget=int(budget[0]) if budget else None,
                                  used_today=used, last_success=last)
        return result


def import_item(item_type, item_no, progress=None):
    from ..core.pipeline import import_item as run
    return run(item_type, item_no, via='cli', path=brickwork_path(), **({'emit': progress} if progress else {}))


def import_bricktracker(source=None, plan_only=False, plan_id=None, decisions=None):
    """Plan a BrickTracker import, apply it unless --plan-only, or apply a stored plan."""
    from ..core.connect import connect
    from ..core.importer import bricktracker
    from ..core.sources.base import audit_origin
    choices = json.loads(Path(decisions).read_text()) if decisions else None
    with closing(connect(brickwork_path())) as db, audit_origin('cli'):
        if plan_id is None:
            plan = bricktracker.plan(db, source)
            if plan_only:
                return {key: plan[key] for key in ('id', 'schema', 'fresh', 'summary', 'unresolved')}
            plan_id = plan['id']
        return bricktracker.apply(db, plan_id, choices)


def sync_command(source, action, plan_id=None, tick=None, owned=None, wishlist=None, send_to=None, wish_list=None,
                 username=None, prompt=None):
    """`brickwork sync <source> <action>`: status, lists, link, pull, send, connect, paste, remove, test.

    connect asks for the password and paste for the token/hash without echo; neither is ever an argument.
    """
    import getpass
    from ..core.connect import connect
    from ..core import sync
    from ..core.sources.base import audit_origin
    prompt = prompt or getpass.getpass
    with closing(connect(brickwork_path())) as db, audit_origin('cli'):
        if action == 'status':
            return sync.status(db, source)
        if action == 'lists':
            return sync.lists(db, source)
        if action == 'link':
            options = {k: v for k, v in dict(owned=owned, wishlist=wishlist, send_to=send_to, wish_list=wish_list).items()
                       if v is not None}
            return sync.link(db, source, options)
        if action == 'connect':
            if not username:
                raise ValueError('Give --username; the password is asked for')
            return sync.connect(db, source, username, prompt('Password: '))
        if action == 'paste':
            return sync.paste(db, source, prompt('Token or hash: '))
        if action == 'remove':
            return sync.remove(db, source)
        if action == 'test':
            return sync.test(db, source)
        if action == 'pull':
            if plan_id:
                return sync.apply_pull(db, plan_id, tick)
            return sync.plan_pull(db, source)
        if plan_id:
            return sync.apply_send(db, plan_id, tick)
        return sync.plan_send(db, source)


def jobs_list(failed=False):
    from ..core.connect import connect
    from ..core.pipeline import Pipeline
    with closing(connect(brickwork_path())) as db:
        return Pipeline(db).list_jobs(failed)


def jobs_retry(job, step=None, progress=None):
    from ..core.pipeline import retry
    return retry(job, step, path=brickwork_path(), **({'emit': progress} if progress else {}))


# 4.1b: the web adapter and CLI share the new-store services.
def tools_read(page, group=None):
    from ..core import admin
    with admin.database(brickwork_path(), read_only=True) as db:
        if page == 'values':
            return admin.value_rows(db, group)
        if page == 'settings':
            from ..core.pictures import state
            return {**admin.settings(db), 'pictures': state(db)}
        if page == 'statistics':
            return admin.statistics(db)
        if page == 'database':
            from .formatting import short_stamp
            last = admin.last_check(db)
            if last:
                last['stamp'] = short_stamp(last.get('checked_at'), True)
            return {'last': last}
        if page == 'unresolved':
            return admin.unresolved(db)
        if page == 'refresh':
            return admin.stale_prices(db)
        if page == 'jobs':
            import json
            jobs = admin.jobs(db)
            from ..core.pipeline import owner_pid_alive
            has_owners = db.execute("SELECT 1 FROM sqlite_master WHERE name='import_owners'").fetchone()
            owners = dict(db.execute('SELECT job_id,pid FROM import_owners')) if has_owners else {}
            live = {job: owner_pid_alive(pid, path=brickwork_path(), job=job) for job, pid in owners.items()}
            return [{**job, 'interrupted': (job['state'] == 'running' or job['state'] == 'waiting_for_budget' and job['id'] in owners)
                     and not live.get(job['id'], False),
                     'picture_receipt': json.loads(job['payload'] or '{}') if job['kind'] == 'picture_refresh' else None} for job in jobs]
        if page == 'history':
            return admin.history(db)
        if page == 'instructions':
            # Count canonical booklet identities only. A set-level PDF does not
            # establish how many booklets that set has or which ones it covers.
            files = [dict(r) for r in db.execute('SELECT f.*,i.name FROM instruction_files f JOIN items i ON i.item_type=f.item_type AND i.item_no=f.set_no WHERE f.archived_at IS NULL ORDER BY set_no,id')]
            images = {}
            for number, identifier in db.execute("SELECT item_no,id FROM item_images WHERE item_type='I' AND copy_id IS NULL AND stock_id IS NULL ORDER BY fetched_at,id"):
                images[number] = identifier
            by_booklet = {}
            for row in files:
                if row['item_type'] == 'I':
                    by_booklet.setdefault(row['set_no'], []).append(row)
            # Every recorded booklet identity is listed, with or without a PDF.
            booklets = [dict(number=r['item_no'], name=r['name'], image=images.get(r['item_no']), files=by_booklet.get(r['item_no'], []))
                        for r in db.execute("SELECT item_no,name FROM items WHERE item_type='I' ORDER BY item_no")]
            coverage = dict(total=len(booklets), covered=sum(1 for b in booklets if b['files']))
            return dict(files=[r for r in files if r['item_type'] != 'I'], booklets=booklets, coverage=coverage)
        if page == 'catalogues':
            status = sources_status()
            sources = []
            for row in db.execute('SELECT * FROM sources ORDER BY name'):
                last = db.execute("SELECT error,updated_at FROM jobs WHERE source=? AND error IS NOT NULL ORDER BY updated_at DESC LIMIT 1", (row['source'],)).fetchone()
                sources.append({**dict(row), **status.get(row['source'], {}),
                                'last_error': dict(last) if last else None})
            from ..core import source_ops
            for name in source_ops.clients():
                if name not in {r['source'] for r in sources}:
                    sources.append(dict(source=name, name=name, kind='api', enabled=1, last_error=None, **status.get(name, {})))
            settings = admin.settings(db)
            return dict(sources=sources, catalogue=catalogue_status()['bricklink'],
                        colours=dict(db.execute('SELECT count(*) AS total,count(rgb) AS with_rgb FROM colors').fetchone()),
                        freshness=settings['freshness'], priority=settings['priority'])
        return dict(stale=len({(r['item_type'], r['item_no']) for r in admin.stale_prices(db)}),
                    unresolved=admin.count_unresolved(db), jobs=admin.count_jobs(db),
                    instructions=db.execute('SELECT count(*) FROM instruction_files WHERE archived_at IS NULL').fetchone()[0])


def tools_write(operation, **args):
    from ..core.sources.base import audit_origin
    with audit_origin('app'):
        return _tools_write(operation, **args)


def _tools_write(operation, **args):
    from ..core import admin
    with admin.database(brickwork_path()) as db:
        if operation == 'instruction_rename':
            return admin.instruction_rename(db, **args)
        if operation == 'instruction_upload':
            return admin.instruction_upload(db, _media_root(), **args)
        if operation == 'instruction_fetch':
            return admin.queue_missing_booklets(db)
        if operation == 'value':
            return admin.value_write(db, **args)
        if operation == 'resolve':
            return admin.resolve(db, **args)
        if operation == 'pictures':
            from ..core.pictures import queue
            return queue(db, **args)
        if operation == 'settings':
            return admin.save_settings(db, **args)
        if operation == 'database_check':
            return admin.run_check(db)
        if operation == 'refresh':
            return admin.queue_refresh(db, admin.stale_prices(db))
        if operation == 'images':
            match = next((r for r in admin.unresolved(db) if (r['source'], r['kind'], r['source_id']) ==
                          (args['source'], args['kind'], args['source_id'])), None)
            if not match:
                raise ValueError('Match is no longer unresolved')
            # Canonical candidates get only the existing pictures step, never a full import.
            from ..core.pipeline import Pipeline
            p = Pipeline(db)
            with db:
                db.execute('BEGIN IMMEDIATE')
                queued = []
                if match['reference_url'] and not match['image']:
                    queued.append(p.queue_steps(match['item_type'], match['item_no'], ('pictures',),
                        sources=['rebrickable'], reference_image=match['reference_url']))
                for choice in match['candidates']:
                    db.execute('INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES(?,?,?)',
                               (choice['item_type'], choice['item_no'], choice['name']))
                    queued.append(p.queue_steps(choice['item_type'], choice['item_no'], ('pictures',), sources=['bricklink']))
                admin.audit(db, 'match:' + match['source_id'], 'candidate_images', new=queued)
            return queued
        if operation == 'source':
            with db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT enabled FROM sources WHERE source=?', (args['source'],)).fetchone()
                if not row:
                    raise ValueError('Unknown source')
                db.execute('UPDATE sources SET enabled=? WHERE source=?', (int(args['enabled']), args['source']))
                admin.audit(db, 'source:' + args['source'], 'enabled', row[0], int(args['enabled']))
            return
        if operation == 'retry_queue':
            from ..core.pipeline import Pipeline
            return Pipeline(db).queue_retry(args['job'], args.get('step'))
        if operation in ('key_save', 'key_remove', 'key_test', 'key_undo', 'key_test_save'):
            from ..core import errors, keys, source_ops
            source_ops.ensure(db, keys.known(args['source']))
            if operation in ('key_save', 'key_test_save') and keys.state(db, args['source'])['origin'] == 'env':
                # The environment key wins, so a stored one would never be used or tested.
                raise errors.ValidationFailed('This key comes from the environment. Change it there; a stored key would be ignored')
            if operation == 'key_save':
                return keys.save(db, args['source'], args['values'])
            if operation == 'key_remove':
                receipt = []
                state = keys.archive(db, args['source'], receipt)
                return dict(state, event=receipt[0] if receipt else None)
            if operation == 'key_undo':
                row = db.execute('SELECT id,entity,field,new_value FROM events WHERE id=?', (args['event'],)).fetchone()
                if row is None or row['entity'] != 'source_key:' + args['source'] or row['field'] != 'archive':
                    raise ValueError('Unknown key change')
                return keys.undo(db, row['id'], dict(row))
            if operation == 'key_test_save':
                return key_test_save(db, args['source'], args['values'])
            return keys.check(db, args['source'])
        if operation == 'colours':
            from ..core.sources.bricklink import BrickLink
            return BrickLink(db).sync_colors()
        if operation == 'catalogue':
            from ..core.sources.bricklink_catalogue import source_directory
            return catalogue_import_bricklink(source_directory(brickwork_path()))
        raise ValueError('Unknown admin action')


def tools_export():
    """Consistent new-store snapshot with an app event; no filesystem side effects."""
    import sqlite3
    from ..core import admin
    from flask import has_app_context
    from ..api import read_only
    # A read-only instance writes nothing, not even this event (#68); the CLI has no app context.
    locked = read_only() if has_app_context() else os.environ.get('BW_READ_ONLY', '').lower() in ('1', 'true', 'yes', 'on')
    with admin.database(brickwork_path(), read_only=locked) as db:
        if not locked:
            with db:
                admin.audit(db, 'database', 'export')
        with closing(sqlite3.connect(':memory:')) as snapshot:
            db.backup(snapshot)
            from ..core import keys
            keys.strip(snapshot)  # stored source keys never leave the app, not even encrypted
            snapshot.execute('PRAGMA journal_mode=DELETE')
            result = bytearray(snapshot.serialize())
            # A serialized WAL header cannot be opened without its sidecar.
            result[18:20] = bytes((1, 1))
            if any(value.encode() in result for value in secret_values()):
                raise ValueError('Export contains credential material')
            return bytes(result)


def brickwork_check():
    from ..core import admin
    with admin.database(brickwork_path(), read_only=True) as db:
        return {'brickwork': admin.check(db)}


def jobs_worker():
    from ..core.pipeline import worker
    return worker(path=brickwork_path())


def setup():
    """Create a fresh 4.0 collection (an existing 4.0 file is left as it is; a 3.3 file is refused) and say where the catalogue goes."""
    from ..core.connect import GET_CATALOGUE, catalogue_path, connect
    path = brickwork_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path, require_catalogue=False)):
        pass
    catalogue = catalogue_path(path)
    result = {'setup': 'ok', 'database': str(path), 'catalogue': str(catalogue) if catalogue.is_file() else 'missing'}
    if not catalogue.is_file():
        result['next'] = f'Get the catalogue, which belongs beside the collection as {catalogue}: {GET_CATALOGUE}'
    return result
