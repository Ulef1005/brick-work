"""M5 transport: jobs, sources, the encrypted key store and identification upload.

Handlers parse and authorise, call one core service function and serialise. Queued
work answers 202 with the job; source calls that need the network run outside any
transaction (`detached`) and surface an exhausted budget as 429 with Retry-After.
"""
import hashlib
import os
import threading
import uuid

from flask import current_app, g, jsonify, request

from . import api, database, db_path
from .serializers import public
from ..core import api_jobs, api_writes as service, errors, identify, keys, secrets, source_ops
from ..core.api_reads import root
from ..core.audit_bundle import capture
from ..core import drainer
from ..core.sources.brickognize import Brickognize, photo_bytes

IDENTIFICATION_LIMIT = 8 * 1024 * 1024


def spawn(target):
    """Seam for the embedded drainer's thread; tests replace it."""
    threading.Thread(target=target, name='brickwork-drainer', daemon=True).start()


def start_worker():
    return drainer.start(current_app._get_current_object(), db_path(), lambda target: spawn(target))


def no_input():
    if request.args:
        raise errors.UnknownFilter()
    if request.get_data():
        raise errors.BadRequest('This action accepts no body')
    return {}


def json_input(*, optional=False):
    if request.args:
        raise errors.UnknownFilter()
    if optional and not request.get_data():
        return {}
    if request.mimetype != 'application/json':
        raise errors.UnsupportedMediaType()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise errors.BadRequest('Expected a JSON object')
    return data


def run(runner, body, action, shape, *, required=False, **options):
    return runner(database(), method=request.method, path=request.path, body=body,
                  key=request.headers.get('Idempotency-Key'), required=required,
                  token_name=g.api_identity['name'], action=action,
                  serialize=lambda value: public(value, shape), **options)


def answer(outcome, *, job=False):
    result, status = outcome
    response = jsonify(result)
    response.status_code = status
    if job and status == 202 and isinstance(result['data'], dict) and 'id' in result['data']:
        response.headers['Location'] = f"/api/v1/jobs/{result['data']['id']}"
    if status == 202 and not result['idempotent_replay']:
        start_worker()
    return response


# Jobs

@api.post('/jobs/<int:id>/retry')
def post_jobs_by_id_retry(id):
    data = json_input(optional=True)
    if set(data) - {'step'}:
        raise errors.ValidationFailed('Unknown field')
    return answer(run(service.execute, dict(data, job=id), lambda: (api_jobs.retry(database(), id, data.get('step')), 202), 'Job'), job=True)


@api.post('/jobs/<int:id>/resume')
def post_jobs_by_id_resume(id):
    no_input()
    return answer(run(service.execute, {'job': id}, lambda: (api_jobs.resume(database(), id), 202), 'Job'), job=True)


@api.post('/jobs/drain')
def post_jobs_drain():
    no_input()
    return answer(run(service.detached, {}, lambda: (api_jobs.drain(database()), 200), 'JobList'))


@api.post('/jobs/instruction-identities')
def post_jobs_instruction_identities():
    no_input()
    return answer(run(service.execute, {}, lambda: (api_jobs.booklets(database()), 202), 'JobList'))


@api.post('/jobs/pictures')
def post_jobs_pictures():
    data = json_input()
    return answer(run(service.execute, data, lambda: (api_jobs.queue_pictures(database(), data), 202), 'Job'), job=True)


# Sources

@api.patch('/sources/<source>')
def patch_sources_by_source(source):
    data = json_input()
    if set(data) != {'enabled'}:
        raise errors.ValidationFailed('Supply enabled')
    source_ops.known(source)

    def action():
        source_ops.toggle(database(), source, data['enabled'])
        return source_ops.view(database(), source), 200
    return answer(run(service.execute, dict(data, source=source), action, 'Source'))


@api.post('/catalogue/import')
def post_catalogue_import():
    no_input()
    return answer(run(service.detached, {}, lambda: (source_ops.catalogue_import(database()), 200), 'CatalogueStatus'))


@api.post('/colors/sync')
def post_colors_sync():
    no_input()
    return answer(run(service.detached, {}, lambda: (source_ops.sync_colours(database()), 200), 'ColorSyncResult'))


@api.put('/sources/<source>/key')
def put_sources_source_key(source):
    keys.known(source)
    data = json_input()
    keys.clean(source, data)
    # The body holds key material: replay compares a keyed fingerprint, never a plain hash.
    body = dict(source=source, fingerprint=secrets.fingerprint(data))

    def action():
        source_ops.ensure(database(), source)
        keys.save(database(), source, data)
        return source_ops.view(database(), source), 200
    return answer(run(service.execute, body, action, 'Source'))


@api.delete('/sources/<source>/key')
def delete_sources_source_key(source):
    keys.known(source)
    no_input()

    def action():
        source_ops.ensure(database(), source)
        keys.archive(database(), source)
        return source_ops.view(database(), source), 200
    return answer(run(service.execute, {'source': source}, action, 'Source'))


@api.post('/sources/<source>/key/test')
def post_sources_source_key_test(source):
    keys.known(source)
    no_input()

    def action():
        source_ops.ensure(database(), source)
        return keys.check(database(), source), 200
    return answer(run(service.detached, {'source': source}, action, 'KeyTest'))


# Identification upload

def upload(limit):
    """One image file from a multipart request: type, size and (later) decodability limits."""
    if request.args:
        raise errors.UnknownFilter()
    if request.mimetype != 'multipart/form-data':
        raise errors.UnsupportedMediaType()
    if set(request.form):
        raise errors.ValidationFailed('Unknown field')
    file = request.files.get('file')
    if file is None or set(request.files) != {'file'}:
        raise errors.ValidationFailed('Choose a photo')
    if not (file.mimetype or '').startswith('image/'):
        raise errors.UnsupportedMediaType()
    raw = file.read(limit + 1)
    if len(raw) > limit:
        raise errors.PayloadTooLarge()
    return raw


@api.post('/identifications')
def post_identifications():
    raw = upload(IDENTIFICATION_LIMIT)

    def action():
        photo = photo_bytes(raw)
        candidates = Brickognize(database()).predict(photo)
        with capture() as captured:
            record = identify.store(database(), root(database()), photo, candidates)
        # #45: what you already hold of each candidate (in the reply only, not stored with the result).
        from ..core import ownership
        owned = ownership.summary(database(), [(c['item_type'], c['item_no']) for c in record['candidates']])
        record = dict(record, candidates=[dict(c, owned=dict(owned[(c['item_type'], c['item_no'])],
                                                             text=ownership.text(owned[(c['item_type'], c['item_no'])])))
                                          if (c['item_type'], c['item_no']) in owned else c for c in record['candidates']])
        return record, 201, [r for r in captured if service.is_receipt(r)]
    return answer(run(service.detached, dict(file_sha256=hashlib.sha256(raw).hexdigest()), action, 'Identification'))


@api.delete('/identifications/<id>')
def delete_identifications_id(id):
    no_input()

    def action():
        identify.archive(database(), id)
        from ..core import api_reads
        return api_reads.record(database(), 'identifications', id, archived=True), 200
    return answer(run(service.execute, {'id': id}, action, 'Identification'))


@api.post('/items/<type>/<no>/import')
def post_items_by_type_by_no_import(type, no):
    data = json_input()
    return answer(run(service.execute, dict(data, item_type=type, item_no=no),
        lambda: (api_jobs.queue_item(database(), type, no, data), 202), 'Job'), job=True)


@api.post('/items/<type>/<no>/prices/refresh')
def post_items_by_type_by_no_prices_refresh(type, no):
    data = json_input()
    return answer(run(service.execute, dict(data, item_type=type, item_no=no),
        lambda: (api_jobs.queue_item(database(), type, no, data, refresh=True), 202), 'Job'), job=True)


# BrickTracker import (issue #11): upload a database, get a plan, apply chosen rows; Undo through /events.

IMPORT_LIMIT = int(os.environ.get('BW_IMPORT_MAX_MB', '200')) * 1024 * 1024


def upload_database(limit):
    """One SQLite file from a multipart request, streamed to a private temp file under data/imports/."""
    from ..core.importer import bricktracker
    if request.args:
        raise errors.UnknownFilter()
    if request.mimetype != 'multipart/form-data':
        raise errors.UnsupportedMediaType()
    if set(request.form):
        raise errors.ValidationFailed('Unknown field')
    file = request.files.get('file')
    if file is None or set(request.files) != {'file'}:
        raise errors.ValidationFailed('Choose a BrickTracker database file (app.db)')
    folder = bricktracker.plans_root(database()) / 'uploads'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / uuid.uuid4().hex
    digest, size = hashlib.sha256(), 0
    try:
        with target.open('wb') as out:
            while chunk := file.stream.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise errors.PayloadTooLarge()
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target, digest.hexdigest(), file.filename or 'app.db'


@api.post('/imports/bricktracker')
def post_imports_bricktracker():
    from ..core.importer import bricktracker
    path, sha256, name = upload_database(IMPORT_LIMIT)

    def action():
        try:
            return bricktracker.plan(database(), path, name=name), 201
        except ValueError as exc:
            raise errors.ValidationFailed(str(exc)) from None
        finally:
            path.unlink(missing_ok=True)
    try:
        return answer(run(service.detached, dict(file_sha256=sha256), action, 'ImportPlan'))
    finally:
        path.unlink(missing_ok=True)


@api.post('/imports/<id>/apply')
def post_imports_by_id_apply(id):
    from ..core.importer import bricktracker
    data = json_input(optional=True)
    if set(data) - {'decisions'} or not isinstance(data.get('decisions', {}), dict):
        raise errors.ValidationFailed('Send {"decisions": {row key: "add" or "skip"}}')

    def action():
        try:
            return bricktracker.apply(database(), id, data.get('decisions', {})), 200
        except ValueError as exc:
            raise errors.ValidationFailed(str(exc)) from None
    response = answer(run(service.execute, dict(data, plan_id=id), action, 'ImportApplied'))
    start_worker()  # catalogue imports queued for new sets and figures
    return response


# #47: four operations the contract listed without a route.

@api.post('/copies/<id>/check')
def post_copies_by_id_check(id):
    """One Check Set Parts action; the Idempotency-Key is the checker's operation id (required)."""
    from ..core import checker
    from ..core.api_reads import root
    data = json_input()
    key = request.headers.get('Idempotency-Key')
    allowed = {'action', 'token', 'session', 'found', 'include', 'checked', 'order'}
    if set(data) - allowed or data.get('action') not in ('start', 'answer', 'found_one', 'skip', 'select', 'back',
                                                          'next', 'spares', 'finish', 'undo'):
        raise errors.ValidationFailed('Send a check action: start, answer, found_one, skip, select, back, next, spares, finish or undo')

    def action():
        db = database()
        if not db.execute('SELECT 1 FROM copies WHERE id=? AND archived_at IS NULL', (id,)).fetchone():
            raise errors.NotFound('Copy not found')
        try:
            return checker.write(db, id, dict(data, operation=key), root(db)), 200
        except ValueError as exc:
            if isinstance(exc, errors.BrickWorkError):
                raise
            raise errors.ValidationFailed(str(exc)) from None
    return answer(run(service.execute, dict(data, copy_id=id), action, 'CheckState', required=True, self_audited=True))


@api.post('/unresolved/resolve')
def post_unresolved_resolve():
    """Choose a recorded candidate (or none, which leaves it to check) for one unresolved identity."""
    from ..core import admin
    data = json_input()
    if set(data) - {'source', 'kind', 'source_id', 'selected'} or not all(isinstance(data.get(k), str) for k in ('source', 'kind', 'source_id')):
        raise errors.ValidationFailed('Send source, kind, source_id and selected ([item type, item number] or null)')
    selected = data.get('selected')
    if selected is not None:
        if not (isinstance(selected, list) and len(selected) == 2 and all(isinstance(v, str) for v in selected)):
            raise errors.ValidationFailed('selected is [item type, item number] or null')
        selected = tuple(selected)

    def action():
        db = database()
        try:
            admin.resolve(db, data['source'], data['kind'], data['source_id'], selected)
        except ValueError as exc:
            if isinstance(exc, errors.BrickWorkError):
                raise
            raise errors.Conflict(str(exc)) from None
        row = db.execute('SELECT source,kind,source_id,item_type,item_no FROM id_match WHERE source=? AND kind=? AND source_id=?',
                         (data['source'], data['kind'], data['source_id'])).fetchone()
        return dict(row), 200
    return answer(run(service.execute, data, action, 'Unresolved'))


@api.post('/prices/refresh')
def post_prices_refresh():
    """Queue a market-price refresh for every stale item (the Bulk refresh prices button)."""
    from ..core import admin
    from ..core import api_reads
    no_input()

    def action():
        db = database()
        ids = admin.queue_refresh(db, admin.stale_prices(db))
        jobs = [api_reads.job(db, i) for i in ids]
        return dict(jobs=jobs, skipped=[]), 200
    response = answer(run(service.execute, {}, action, 'JobList'))
    start_worker()
    return response


@api.patch('/settings')
def patch_settings():
    from ..core import admin
    data = json_input()
    return answer(run(service.execute, data, lambda: (admin.patch_settings(database(), data), 200), 'Settings'))


# #39 exchange rates: per 1 EUR, entered by hand or loaded from the ECB reference feed.

@api.get('/exchange-rates')
def get_exchange_rates():
    from ..core import currency
    no_input()
    from flask import jsonify as _json
    return _json(data=public(currency.listing(database()), ['ExchangeRate']), display_currency=currency.display_currency(database()))


@api.put('/exchange-rates/<code>')
def put_exchange_rates_by_code(code):
    from ..core import currency
    data = json_input()
    if set(data) != {'per_eur'}:
        raise errors.ValidationFailed('Send {"per_eur": rate or null}')

    def action():
        currency.set_rate(database(), code, data['per_eur'])
        return currency.listing(database()), 200
    return answer(run(service.execute, dict(data, currency=code), action, ['ExchangeRate']))


@api.post('/exchange-rates/ecb')
def post_exchange_rates_ecb():
    from ..core import currency
    no_input()
    return answer(run(service.detached, {}, lambda: (currency.fetch_ecb(database()), 200), 'EcbResult'))
