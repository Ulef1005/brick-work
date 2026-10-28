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


def _settings_db(read_only=False):
    from ..core.connect import connect
    return closing(connect(brickwork_path(), read_only=read_only, require_catalogue=False))


def settings_show():
    """Every preference with the value in force: the price preferences, retail country, display currency, source order, import order, freshness."""
    with _settings_db(True) as db:
        from ..core import admin
        return admin.settings(db)


def settings_set(key, value):
    """`brickwork settings set <key> <value>`: a price preference, the retail country, the source priority or one import order."""
    from ..core import admin
    from ..core.pipeline import validate_priority, STEPS, TYPES
    from ..core.sources.base import audit_origin
    with _settings_db() as db, audit_origin('cli'):
        if key == 'source_priority':
            parsed = json.loads(value)
            validate_priority(parsed)
            current = admin.settings(db)
            admin.save_settings(db, current['retail_country'], parsed, [])
            return {key: parsed}
        if key.startswith('import_order:'):
            kind = key.removeprefix('import_order:')
            parsed = json.loads(value)
            if kind not in TYPES or not isinstance(parsed, list) or any(not isinstance(s, str) for s in parsed) \
                    or len(parsed) != len(STEPS) or set(parsed) != set(STEPS):
                raise ValueError('import order must contain all six steps once')
            admin.patch_settings(db, {'import_order': {kind: parsed}})
            return {key: parsed}
        if key not in ('retail_country', 'bricklink_region', 'bricklink_currency', 'incomplete_discount_pct'):
            raise ValueError('unsupported setting')
        if key == 'retail_country':
            if value not in admin.COUNTRIES:
                raise ValueError('unsupported retail country')
            admin.save_settings(db, value, admin.settings(db)['priority'], [])
            return {key: value}
        from ..core.price_settings import save
        return save(db, {key: int(value) if key == 'incomplete_discount_pct' else value})


def brickwork_path():
    from ..core.pipeline import database_path
    return database_path()


def store4_paths():
    """store4's `Paths` for the collection this app opens: the catalogue, the downloads and the BrickLink lists sit beside it."""
    from ..core.connect import catalogue_path
    from ..store4.cli import Paths
    path = brickwork_path()
    paths = Paths(path.parent)
    paths.collection, paths.catalogue = path, catalogue_path(path)
    return paths


def catalogue_status():
    """The catalogue and its activation as `python -m brickwork.store4 catalogue status` reports them."""
    from ..store4.cli import do_status
    return do_status(store4_paths())


def catalogue_import_bricklink(directory):
    """Build a catalogue with the BrickLink item lists of DIRECTORY, activate and reconcile (store4's `catalogue import bricklink`)."""
    from ..store4.cli import do_import_bricklink
    return do_import_bricklink(store4_paths(), directory)


def migrate4(argv):
    """`brickwork migrate4 ...`: store4's migration of a 3.3 collection into a new 4.0 file (the arguments are `store4 migrate`'s)."""
    from ..store4 import cli as store4
    return store4.main(['migrate', *argv])


def _sets(db, numbers):
    """The set items for typed numbers; with none, every identified set held or wanted."""
    from ..core import items
    if numbers:
        found = []
        for number in numbers:
            matches = [m for m in items.find(db, 'set', number) if m['matched_by'] == 'born']
            if len(matches) != 1:
                raise ValueError(f'{number} is not a set Brick Work knows')
            found.append(matches[0]['item_id'])
        return list(dict.fromkeys(found))
    return [r[0] for r in db.execute("""SELECT DISTINCT i.id FROM main.item i WHERE i.kind='set' AND i.born_key IS NOT NULL AND i.merged_into IS NULL AND (
        EXISTS(SELECT 1 FROM main.copy c WHERE c.item_id=i.id AND c.archived_at IS NULL)
        OR EXISTS(SELECT 1 FROM main.wish w WHERE w.item_id=i.id AND w.archived_at IS NULL)) ORDER BY i.id""")]


def _run_steps(numbers, steps):
    """Queue `steps` for each set and run the jobs here, in this process (the source handlers are registered for it)."""
    from ..core import source_ops
    from ..core.connect import connect
    from ..core.pipeline import Pipeline
    from ..core.sources.base import audit_origin
    from ..core.transaction import transaction
    source_ops.register_handlers()
    with closing(connect(brickwork_path())) as db, audit_origin('cli'):
        ids = _sets(db, numbers)
        with transaction(db):
            jobs = [Pipeline(db).queue_steps(i, steps, via='cli') for i in ids]
        return [Pipeline(db).run(job) for job in jobs]


def prices_refresh(set_num):
    """Fetch BrickLink prices for one set now (`market_price` step); the job is on the Jobs page."""
    job, = _run_steps([set_num], ('market_price',))
    return {'set_num': set_num, 'ok': job['state'] == 'done', 'state': job['state'], 'job': job['id']}


def brickset_refresh(sets):
    """Fetch Brickset's properties and retail price (`metadata` step) for the given sets, or for every set held or wanted."""
    jobs = _run_steps(sets, ('metadata',))
    state = 'done' if all(j['state'] == 'done' for j in jobs) else next(j['state'] for j in jobs if j['state'] != 'done')
    return {'sets': sets or [str(j['item_id']) for j in jobs], 'state': state, 'jobs': [j['id'] for j in jobs]}


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
                return {key: plan[key] for key in ('id', 'schema', 'fresh', 'summary', 'unplaced')}
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


def sources_status():
    from ..core import source_ops
    if not brickwork_path().exists():
        # Status must not create a database merely to report unset/unused keys.
        result = {}
        for source, client in source_ops.clients().items():
            instance = client(None)
            result[source] = dict(key='set' if instance.configured() else 'unset', key_state=instance.status_key(),
                                  budget=instance.daily_budget, used_today=0, last_success=None)
        return result
    from ..core.admin import database
    with database(brickwork_path(), read_only=True, require_catalogue=False) as db:
        return {source: source_ops.view(db, source) for source in source_ops.clients()}


def import_item(item_type, item_no, progress=None):
    """Queue the normal import of an item (a BrickLink type letter and a number) and run it here."""
    from ..core import items, source_ops
    from ..core.connect import connect
    from ..core.pipeline import Pipeline
    from ..core.sources.base import audit_origin
    from ..core.transaction import transaction
    source_ops.register_handlers()
    with closing(connect(brickwork_path())) as db, audit_origin('cli'):
        found = items.find(db, items.kind_of_type(item_type), item_no)
        born = [f for f in found if f['matched_by'] == 'born']
        if len(born) != 1 and len(found) != 1:
            raise ValueError(f'{item_no} is not one item Brick Work knows' if not found else f'{item_no} names several items · give the Rebrickable number')
        with transaction(db):
            job = Pipeline(db).queue_steps((born or found)[0]['item_id'], via='cli')
        return Pipeline(db).run(job)


def jobs_list(failed=False):
    from ..core.connect import connect
    from ..core.pipeline import Pipeline
    with closing(connect(brickwork_path())) as db:
        return Pipeline(db).list_jobs(failed)


def jobs_retry(job, step=None, progress=None):
    from ..core import source_ops
    from ..core.pipeline import retry
    source_ops.register_handlers()
    return retry(job, step, path=brickwork_path())


# 4.1b: the web adapter and CLI share the new-store services.
KEY_LABELS = {'key': 'API key', 'token_value': 'Token'}
PICTURE_ROWS = (('Sets and wishlist', 'set'), ('Minifigures', 'minifigure'), ('Parts per colour', 'part'))
PICTURE_NAMES = {'rebrickable_dump': 'Rebrickable catalogue', 'bricklink': 'BrickLink', 'rebrickable_api': 'Rebrickable API'}
CATALOGUE_KINDS = (('set', 'Sets'), ('minifigure', 'Minifigures'), ('part', 'Parts'), ('instructions', 'Instructions'), ('box', 'Boxes'),
                   ('gear', 'Gear'), ('book', 'Books'), ('catalog', 'Catalogues'))


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
        name = row['name'] if row.get('name') and row['name'] != source else source.replace('_', ' ').capitalize()
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
    counts = catalogue.get('counts') or {}
    loaded = bool(catalogue.get('available'))
    freshness = []
    for rule in data['freshness']:
        days = rule['max_age_days']
        freshness.append(dict(label=NAMES.get(rule['source']) or rule['source'].capitalize(), kind=rule['kind'],
                              days=None if days is None else f"{days} {'day' if days == 1 else 'days'}"))
    order = (data.get('priority') or {}).get('pictures', {})
    pictures = [(label, [PICTURE_NAMES.get(s.split(':')[0], s) for s in order.get(kind, order.get('*', []))]) for label, kind in PICTURE_ROWS]
    if loaded and not catalogue['activated']:
        banners.append(('warning', 'The catalogue is not activated yet. Run the command below once; nothing can be added until then.'))
    return dict(sources=sources, key_cards=keys, banners=banners, pictures=pictures, freshness=freshness,
                catalogue=dict(loaded=loaded, activated=catalogue['activated'], reconciled=catalogue['reconciled'],
                               stamp=short_stamp(catalogue.get('last_built'), True) if catalogue.get('last_built') else None,
                               reconciled_stamp=short_stamp(catalogue['last_reconciled'], True) if catalogue.get('last_reconciled') else None,
                               types=sum(1 for v in counts.values() if v), names=f"{sum(counts.values()):,}" if loaded else '0',
                               colours=catalogue['colours']['total'], gap=catalogue['colours']['total'] - catalogue['colours']['with_rgb'],
                               with_rgb=catalogue['colours']['with_rgb'], bricklink_items=f"{catalogue['bricklink_items']:,}",
                               bricklink_loaded=bool(catalogue['bricklink_items']), commands=catalogue['commands'], path=catalogue['path'],
                               rows=[(label, f"{counts.get(kind, 0):,}" if loaded else '0') for kind, label in CATALOGUE_KINDS]))


def tools_read(page, group=None):
    from ..core import admin
    with admin.database(brickwork_path(), read_only=True, require_catalogue=False) as db:
        if page == 'values':
            return admin.value_rows(db, group)
        if page == 'settings':
            from ..core import pictures
            return {**admin.settings(db), 'pictures': {**pictures.state(db), 'matrix': pictures.matrix(db)}, 'bricklink_list': bricklink_list_switch(db)}
        if page == 'statistics':
            return admin.statistics(db)
        if page == 'database':
            from .formatting import short_stamp
            last = admin.last_check(db)
            if last:
                last['stamp'] = short_stamp(last.get('checked_at'), True)
            return {'last': last}
        if page == 'refresh':
            return admin.stale_prices(db)
        if page == 'jobs':
            from ..core.pipeline import owner_pid_alive
            owners = dict(db.execute('SELECT job_id,pid FROM job_owner'))
            live = {job: owner_pid_alive(pid, path=brickwork_path(), job=job) for job, pid in owners.items()}
            jobs = admin.jobs(db)
            return dict(total=admin.count_jobs(db), jobs=[
                {**job, 'interrupted': (job['state'] == 'running' or job['state'] == 'waiting_for_budget' and job['id'] in owners)
                 and not live.get(job['id'], False)} for job in jobs])
        if page == 'unresolved':
            return dict(items=admin.unresolved(db))
        if page == 'history':
            return admin.history(db)
        if page == 'instructions':
            return admin.instruction_overview(db)
        if page == 'catalogues':
            from ..core import source_ops
            sources = []
            for source in source_ops.clients():
                last = db.execute("SELECT error,updated_at FROM job WHERE source=? AND error IS NOT NULL ORDER BY updated_at DESC LIMIT 1", (source,)).fetchone()
                sources.append({**source_ops.view(db, source), 'last_error': dict(last) if last else None})
            settings = admin.settings(db)
            return dict(sources=sources, catalogue=catalogue_card(db), freshness=settings['freshness'], priority=settings['priority'])
        return dict(stale=len({r['item_id'] for r in admin.stale_prices(db)}), jobs=admin.count_jobs(db), unresolved=admin.count_unresolved(db),
                    instructions=db.execute('SELECT count(*) FROM instruction_file WHERE archived_at IS NULL').fetchone()[0])


def catalogue_card(db):
    """What the Catalogues & keys page says of the catalogue: whether it is attached and activated, when it was built and reconciled, what
    it holds, the BrickLink item lists, and (when something is missing) the command that fixes it. Reads database rows and one directory
    listing; it opens no download file."""
    from ..core.connect import catalogue_path
    from ..store4.connect import has_catalogue
    path = brickwork_path()
    data = path.resolve().parent
    fix = f'python -m brickwork.store4 --data {data} '
    card = dict(available=has_catalogue(db), path=str(catalogue_path(path)), builds=[], counts={}, colours=dict(total=0, with_rgb=0),
                bricklink_items=0, activated=False, reconciled=False, last_built=None, last_reconciled=None, commands=[])
    builds = [dict(r) for r in db.execute('SELECT id,kind,activated_at,reconciled_at FROM main.catalogue_build ORDER BY id')]
    card.update(builds=builds, activated=bool(builds), reconciled=bool(builds) and all(b['reconciled_at'] for b in builds),
                last_reconciled=max((b['reconciled_at'] for b in builds if b['reconciled_at']), default=None))
    if not card['available']:
        card['commands'] = [('Get the catalogue', fix + 'catalogue download'), ('Build it', fix + 'catalogue import')]
        return card
    card['last_built'] = db.execute('SELECT max(finished_at) FROM catalogue.build').fetchone()[0]
    card['counts'] = dict(db.execute('SELECT kind,count(*) FROM catalogue.item WHERE retired_at IS NULL GROUP BY kind'))
    card['colours'] = dict(db.execute('SELECT count(*) AS total,count(rgb) AS with_rgb FROM catalogue.color WHERE retired_at IS NULL').fetchone())
    card['bricklink_items'] = db.execute('SELECT count(*) FROM catalogue.bricklink_item').fetchone()[0]
    # A newer build the collection has not recorded yet (an update stopped before activation) needs the same command.
    card['unactivated'] = [r[0] for r in db.execute('SELECT id FROM catalogue.build WHERE id NOT IN (SELECT id FROM main.catalogue_build) ORDER BY id')]
    card['activated'] = card['activated'] and not card['unactivated']
    if not card['activated']:
        card['commands'] = [('Activate the catalogue', fix + 'catalogue reconcile')]
    elif not card['reconciled']:
        card['commands'] = [('Reconcile the collection with the catalogue', fix + 'catalogue reconcile')]
    return card


def identity_write(db, *, action, item=None, target=None, number=None, link=None, kind=None, provider=None, reason=None, event=None, colour=None, merge=None):
    """One decision of the Unresolved screen (`core/identity_admin`); returns the result, which carries the event id for Undo."""
    from ..core import errors, identity_admin as identity, undo
    if action == 'undo':
        return undo.undo_event(db, int(event))
    if action == 'merge':
        item = int(item)
        survivor = int(target) if target else identity.find_target(db, item, number)
        return identity.merge_item(db, item, survivor)
    if action == 'confirm':
        return identity.confirm_link(db, int(link))
    if action == 'reject':
        return identity.reject_link(db, int(link))
    if action == 'link':
        return identity.add_link(db, int(item), number)
    if action == 'prefer':
        return identity.set_preferred(db, int(link), int(colour) if colour else None, int(item) if item else None)
    if action == 'unmerge':
        return identity.unmerge_item(db, int(merge))
    if action == 'settle':
        return identity.settle_status(db, int(item), provider, reason)
    if action == 'move_kind':
        return identity.move_item_kind(db, int(item), kind)
    raise errors.ValidationFailed('Unknown action')


def tools_write(operation, **args):
    from ..core.sources.base import audit_origin
    with audit_origin('app'):
        return _tools_write(operation, **args)


def _tools_write(operation, **args):
    from ..core import admin
    with admin.database(brickwork_path(), require_catalogue=False) as db:
        if operation == 'instruction_rename':
            return admin.instruction_rename(db, **args)
        if operation == 'instruction_upload':
            return admin.instruction_upload(db, _media_root(), **args)
        if operation == 'instruction_fetch':
            return admin.queue_missing_booklets(db)
        if operation == 'value':
            return admin.value_write(db, **args)
        if operation == 'pictures':
            from ..core.pictures import queue
            return queue(db, **args)
        if operation == 'settings':
            return admin.save_settings(db, **args)
        if operation == 'settings_undo':
            from ..core import undo
            return undo.undo_event(db, args['event'])
        if operation == 'database_check':
            return admin.run_check(db)
        if operation == 'identity':
            return identity_write(db, **args)
        if operation == 'refresh':
            return admin.queue_refresh(db, admin.stale_prices(db))
        if operation == 'source':
            from ..core import source_ops
            return source_ops.toggle(db, args['source'], args['enabled'])
        if operation == 'retry_queue':
            from ..core.pipeline import Pipeline
            from ..store4 import jobs as fetch_jobs
            row = db.execute('SELECT kind FROM main.job WHERE id=?', (args['job'],)).fetchone()
            if row is not None and row['kind'] in fetch_jobs.KINDS:          # a fetch job runs on store4's runner, as Retry on Add does
                return fetch_jobs.requeue(db, args['job'])
            return Pipeline(db).queue_retry(args['job'], args.get('step'))
        if operation in ('key_save', 'key_remove', 'key_test', 'key_undo', 'key_test_save'):
            from ..core import errors, keys, source_ops
            if operation != 'key_undo':
                keys.known(args['source'])
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
                row = db.execute('SELECT id,entity_kind,entity_id,field FROM event WHERE id=?', (args['event'],)).fetchone()
                if row is None or (row['entity_kind'], row['entity_id'], row['field']) != ('source_key', args['source'], 'archive'):
                    raise ValueError('Unknown key change')
                return keys.undo(db, row['id'])
            if operation == 'key_test_save':
                return key_test_save(db, args['source'], args['values'])
            return keys.check(db, args['source'])
        raise ValueError('Unknown admin action')


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
            keys.undo(db, receipt[0])
        except Exception as failure:
            # The refusal still stands; say that the earlier key could not be put back.
            exc.restore_failed = True
            logging.getLogger(__name__).error('key rollback failed for %s (%s)', source, type(failure).__name__)
        raise
    except SourceError as exc:
        return dict(tested=False, reason=redact(exc))
    return dict(tested=True, reason=None)


def tools_export():
    """Consistent new-store snapshot with an app event; no filesystem side effects."""
    import sqlite3
    from ..core import admin
    from flask import has_app_context
    from ..api import read_only
    # A read-only instance writes nothing, not even this event (#68); the CLI has no app context.
    locked = read_only() if has_app_context() else os.environ.get('BW_READ_ONLY', '').lower() in ('1', 'true', 'yes', 'on')
    with admin.database(brickwork_path(), read_only=locked, require_catalogue=False) as db:
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
    with admin.database(brickwork_path(), read_only=True, require_catalogue=False) as db:
        return {'brickwork': admin.check(db)}


def jobs_worker():
    from ..core.drainer import worker
    return worker(path=brickwork_path())


def setup():
    """Create a fresh 4.0 collection (an existing 4.0 file is left as it is; a 3.3 file is refused) and say where the catalogue goes."""
    from ..core import admin
    from ..core.connect import GET_CATALOGUE, catalogue_path
    path = brickwork_path()
    admin.ensure_collection(path)                     # freshness rules, system flags, setup event; an existing collection keeps its own
    catalogue = catalogue_path(path)
    result = {'setup': 'ok', 'database': str(path), 'catalogue': str(catalogue) if catalogue.is_file() else 'missing'}
    if not catalogue.is_file():
        result['next'] = f'Open the app and press Download the catalogue on the first page, or from the command line: {GET_CATALOGUE}. It belongs beside the collection as {catalogue}.'
    return result


CATALOGUE_PAGES = {'catalogue': 'Catalogue', 'catalogue-lists': 'BrickLink item lists', 'catalogue-mappings': 'Mappings and coverage',
                   'migration': 'Migration report'}
PICTURE_SOURCES = (('rebrickable_dump', 'Rebrickable catalogue', 'A picture address stored in your catalogue. Costs nothing and works offline once the catalogue is built.'),
                   ('bricklink', 'BrickLink', "BrickLink's public picture for the part number and colour. No key needed."),
                   ('rebrickable_api', 'Rebrickable API', 'Asks Rebrickable for the picture. Needs a Rebrickable key and uses its daily budget.'))


def bricklink_list_switch(db):
    """The "Prefer BrickLink's part list for new copies" switch (design 4.3): whether it is on and whether a BrickLink key is set. Read only."""
    from ..store4 import jobs
    row = db.execute("SELECT value FROM main.setting WHERE key='prefer_bricklink_inventory'").fetchone()
    return dict(on=bool(row and row[0] == 'true'), key=bool(jobs._configured('bricklink')))


def set_prefer_bricklink(enabled):
    """Flip the switch through the core writer (one event, undoable like any setting event)."""
    from contextlib import closing
    from ..core.connect import connect
    from ..store4 import copies
    with closing(connect(brickwork_path())) as db:
        return copies.set_prefer_bricklink(db, enabled, via='app')


def migration_report_dir():
    """The folder the migration report is read from: `BW_MIGRATION_REPORT` when set, else `migration-report/` beside the collection file."""
    import os
    from pathlib import Path
    custom = os.environ.get('BW_MIGRATION_REPORT', '').strip()
    return Path(custom) if custom else brickwork_path().resolve().parent / 'migration-report'


def catalogue_pages(page):
    """Everything the catalogue lifecycle pages show, prepared once (stamps formatted, nothing written)."""
    from . import catalogue_jobs
    from ..store4 import cli, status
    from .formatting import short_stamp
    paths = store4_paths()
    out = dict(page=page, kind_names=dict(CATALOGUE_KINDS))
    job = catalogue_jobs.read(paths)
    if page in ('catalogue', 'catalogue-lists'):
        wanted = 'lists' if page == 'catalogue-lists' else None
        out['job'] = job if job and (job['kind'] == 'lists') == (wanted == 'lists') else None
        out['result'] = catalogue_jobs.result_view(paths, out['job'])
        out['running'] = bool(job and job['state'] == 'running')
        out['running_label'] = job['label'] if out['running'] else None
        if job:
            for key in ('started_at', 'finished_at'):
                job[key + '_text'] = short_stamp(job.get(key), True)
    if page == 'catalogue':
        build = status.catalogue_build(paths)
        if build:
            build.update(built_text=short_stamp(build['built_at'], True), reconciled_text=short_stamp(build['reconciled_at'], True),
                         download_text=short_stamp(build['download_date']) if build['download_date'] else None,
                         megabytes=round(build['bytes'] / 1_000_000, 1))
        out.update(build=build, can_rebuild=cli.newest_download(paths) is not None)
    elif page == 'catalogue-lists':
        lists = status.bricklink_lists(paths)
        if lists['loaded']:
            lists['loaded']['at_text'] = short_stamp(lists['loaded']['at'], True)
        out['lists'] = lists
    elif page == 'catalogue-mappings':
        out.update(layers=status.mapping_layers(paths), coverage=status.coverage(paths))
    elif page == 'migration':
        from contextlib import closing
        from ..core.connect import connect
        from ..store4.migrate_report import read_report
        expected = None
        try:
            with closing(connect(brickwork_path(), read_only=True, require_catalogue=False)) as db:
                row = db.execute("SELECT value FROM main.meta WHERE key='migrated_from'").fetchone()
                expected = json.loads(row[0]).get('report_digest') if row else None
        except (ValueError, sqlite3.Error, OSError):
            pass
        out['report'] = read_report(migration_report_dir(), expected_digest=expected)
        if out['report']:
            out['report']['headline']['migrated_at_text'] = short_stamp(out['report']['headline']['migrated_at'], True)
        out['report_dir'] = str(migration_report_dir()) if os.environ.get('BW_MIGRATION_REPORT', '').strip() else f'{migration_report_dir().parent.name}/{migration_report_dir().name}/'
        out['migrated'] = expected is not None
    return out
