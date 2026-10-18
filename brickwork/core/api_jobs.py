"""Job operations for the API. Queueing is transactional; running happens outside it."""
import json
from . import admin, api_reads as read, errors, pictures
from .pipeline import STEPS, Pipeline
from .importer.projection import PRIORITY


def existing(db, identifier):
    row = db.execute("SELECT id FROM jobs WHERE id=? AND source='import'", (identifier,)).fetchone()
    if row is None:
        raise errors.NotFound()
    return read.job(db, identifier)


def retry(db, identifier, step=None):
    """Queue failed steps again (all, or one); the caller starts the worker afterwards."""
    if step is not None and step not in STEPS:
        raise errors.ValidationFailed('Unknown step')
    job = existing(db, identifier)
    if step is not None and step not in {s['name'] for s in job['steps']}:
        raise errors.ValidationFailed('Unknown step')
    if job['state'] == 'running' and not job['interrupted']:
        raise errors.Conflict('Job is running')
    if not any(s['state'] == 'failed' and (step is None or s['name'] == step) for s in job['steps']):
        raise errors.Conflict('No failed step to retry')
    Pipeline(db).queue_retry(identifier, step)
    return read.job(db, identifier)


def resume(db, identifier):
    """Continue an interrupted or budget-waiting job; a job that failed needs retry."""
    job = existing(db, identifier)
    if job['state'] not in ('queued', 'running', 'waiting_for_budget'):
        raise errors.Conflict('Job is not resumable; use retry for a failed job')
    if job['state'] == 'running' and not job['interrupted']:
        raise errors.Conflict('Job is running')
    admin.audit(db, 'job:' + str(identifier), 'resume')
    return job


def booklets(db):
    queued, skipped = admin.queue_missing_booklets(db)
    admin.audit(db, 'jobs', 'queued_booklets', new=dict(jobs=queued, skipped=skipped))
    return dict(jobs=[read.job(db, j) for j in queued], skipped=skipped)


def queue_pictures(db, data):
    """Queue a picture refresh job; a repeated identical request returns the active job."""
    if not isinstance(data, dict) or set(data) - {'source', 'scope', 'types', 'expected_count'} or not {'source', 'scope'} <= set(data):
        raise errors.ValidationFailed('Supply source and scope, with optional types and expected_count')
    types = data.get('types') or []
    if not isinstance(types, list) or not all(isinstance(t, str) for t in types):
        raise errors.ValidationFailed('types must be a list of item types')
    count = data.get('expected_count')
    if count is not None and (type(count) is not int or count < 0):
        raise errors.ValidationFailed('expected_count must be zero or more')
    job, selected = pictures.queue(db, data['source'], data['scope'], types, count, via='api')
    admin.audit(db, 'job:' + str(job), 'requested', new=dict(identities=selected))
    return read.job(db, job)


def drain(db, limit=100):
    """Run due jobs in this request (the same drain the worker loop performs)."""
    ran = Pipeline(db).drain(limit)
    return dict(jobs=[read.job(db, r['id']) for r in ran], skipped=[])


def queue_item(db, item_type, item_no, data, *, refresh=False):
    """Resolve catalogue identity, then queue through the shared pipeline."""
    from . import add
    from .sources.base import item
    allowed = set() if refresh else {'steps', 'sources'}
    if set(data) - allowed:
        raise errors.ValidationFailed('Unknown field')
    identity = add.lookup(db, item_type, item_no)
    if not identity:
        if not add.catalogue_path(db).is_file():
            raise errors.CatalogueNotLoaded()
        raise errors.NotFound()
    if refresh:
        live = admin.live_import_job(db, item_type, item_no)
        if live is not None:
            admin.audit(db, 'job:' + str(live), 'requested', new=dict(reused=True))
            return read.job(db, live)
        steps, sources = ['market_price'], None
    else:
        settings = dict(db.execute('SELECT key,value FROM settings'))
        steps = data.get('steps', json.loads(settings.get('import_order:' + item_type, json.dumps(STEPS))))
        sources = data.get('sources')
        if not isinstance(steps, list) or not steps or any(s not in STEPS for s in steps):
            raise errors.ValidationFailed('Unknown import step')
        supported = {s for types in PRIORITY.values() for order in types.values() for s in order}
        if sources is not None and (not isinstance(sources, list) or not sources or any(not isinstance(s, str) or s not in supported for s in sources)):
            raise errors.ValidationFailed('Unknown source')
    item(db, item_type, item_no, identity['name'])
    job = Pipeline(db).queue_steps(item_type, item_no, steps, via='api', sources=sources)
    return read.job(db, job)
