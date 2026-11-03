"""Jobs (M.11d, issue #113): the import and refresh jobs of the pipeline and the two fetch kinds, and the operations that queue or run them.

A job is a row of `job` with its `job_step` rows (design 5.2). Queueing is part of the request's transaction; running happens outside it:
the embedded worker is woken after the commit (`writes.wake_worker`), and `POST /jobs/drain` runs one drain in the request, in a detached
write. Queued work answers `202` with `Location: /api/v2/jobs/{id}` when it made one job, else the list of jobs it made."""
import json

from ..core import admin, errors, pictures, pipeline, source_ops
from ..core.pipeline import Pipeline
from ..store4 import jobs as fetch_jobs
from . import route
from .items import for_write
from .prices import sql_page
from .read import arguments, bodies, flag, integer_id, reading, respond
from .writes import Done, write


# ---------- the Job body ----------

def job_bodies(db, rows):
    """`Job` bodies for job rows, in a fixed number of queries: the steps of all of them, the items they are about, who owns a running one."""
    ids = [r['id'] for r in rows]
    packed = json.dumps(ids)
    steps = {}
    for s in db.execute('SELECT * FROM main.job_step WHERE job_id IN (SELECT value FROM json_each(?)) ORDER BY job_id, position', (packed,)):
        steps.setdefault(s['job_id'], []).append({'name': s['name'], 'position': s['position'], 'state': s['state'], 'source': s['source'], 'error': s['error'],
                                                  'error_code': s['error_code'], 'retry_at': s['retry_at']})
    owners = {o['job_id']: o['pid'] for o in db.execute('SELECT job_id, pid FROM main.job_owner WHERE job_id IN (SELECT value FROM json_each(?))', (packed,))}
    path = db.execute('PRAGMA database_list').fetchone()['file']
    book = bodies(db, items=[r['item_id'] for r in rows if r['item_id'] is not None])
    return [{'id': r['id'], 'source': r['source'], 'kind': r['kind'], 'item': book.item(r['item_id']) if r['item_id'] is not None else None,
             'state': r['state'], 'attempts': r['attempts'], 'retry_at': r['retry_at'], 'error': r['error'], 'created_at': r['created_at'],
             'updated_at': r['updated_at'], 'steps': steps.get(r['id'], []),
             'interrupted': r['state'] == 'running' and not pipeline.owner_pid_alive(owners.get(r['id']), path=path, job=r['id'])} for r in rows]


def job_body(db, identifier):
    row = db.execute('SELECT * FROM main.job WHERE id=?', (identifier,)).fetchone()
    if row is None:
        raise errors.NotFound('No such job')
    return job_bodies(db, [row])[0]


def job_list(db, identifiers, skipped=()):
    rows = [db.execute('SELECT * FROM main.job WHERE id=?', (i,)).fetchone() for i in identifiers]
    return {'jobs': job_bodies(db, rows), 'skipped': list(skipped)}


def queued(db, identifier, status=202):
    """A single queued job as the answer: `202` with its `Location`."""
    return Done(job_body(db, identifier), status=status, headers={'Location': f'/api/v2/jobs/{identifier}'})


# ---------- reads ----------

@route('/jobs')
@reading
def get_jobs(db):
    args = arguments()
    direction = args.get('direction', 'desc')
    if direction not in ('asc', 'desc'):
        raise errors.UnknownFilter('direction is asc or desc')
    where, params = ' WHERE 1=1', []
    if args.get('state'):
        if args['state'] not in ('queued', 'running', 'waiting_for_budget', 'failed', 'done'):
            raise errors.UnknownFilter('state is queued, running, waiting_for_budget, failed or done')
        where, params = where + ' AND e.state=?', params + [args['state']]
    wanted = flag(args, 'failed')
    if wanted is not None:
        failed = "(e.state='failed' OR EXISTS(SELECT 1 FROM main.job_step s WHERE s.job_id=e.id AND s.state='failed'))"
        where += f' AND {failed}=' + ('1' if wanted else '0')
    signature = json.dumps(sorted((k, v) for k, v in args.items() if k not in ('cursor', 'limit')))
    rows, after, limit = sql_page(db, 'SELECT e.* FROM main.job e' + where, params, direction=direction, signature=signature,
                                  cursor=args.get('cursor'), limit=args.get('limit', 50), identity='e.id')
    return respond(job_bodies(db, rows), page={'next_cursor': after, 'limit': limit, 'total': None})


@route('/jobs/<id>')
@reading
def get_jobs_by_id(db, id):
    arguments()
    return respond(job_body(db, integer_id(id, 'job')))


# ---------- writes ----------

def pipeline_job(db, identifier):
    row = db.execute('SELECT id FROM main.job WHERE id=? AND kind=?', (integer_id(identifier, 'job'), pipeline.KIND)).fetchone()
    if row is None:
        raise errors.NotFound('No such job')
    return row['id']


@route('/jobs/<id>/retry', 'POST')
@write
def post_jobs_by_id_retry(db, body, id):
    """Queue the failed steps again (all, or one); the worker is woken after the commit."""
    identifier, step = pipeline_job(db, id), body.get('step')
    if step is not None and step not in pipeline.STEPS:
        raise errors.ValidationFailed('Unknown step')
    job = job_body(db, identifier)
    if step is not None and step not in {s['name'] for s in job['steps']}:
        raise errors.ValidationFailed('Unknown step')
    if job['state'] == 'running' and not job['interrupted']:
        raise errors.Conflict('Job is running')
    if not any(s['state'] == 'failed' and (step is None or s['name'] == step) for s in job['steps']):
        raise errors.Conflict('No failed step to retry')
    Pipeline(db).queue_retry(identifier, step)
    admin.audit(db, 'job:' + str(identifier), 'retry', new={'step': step})
    return queued(db, identifier)


@route('/jobs/<id>/resume', 'POST')
@write
def post_jobs_by_id_resume(db, body, id):
    """Continue an interrupted or budget-waiting job; a job that failed needs retry."""
    identifier = pipeline_job(db, id)
    job = job_body(db, identifier)
    if job['state'] not in ('queued', 'running', 'waiting_for_budget'):
        raise errors.Conflict('Job is not resumable; use retry for a failed job')
    if job['state'] == 'running' and not job['interrupted']:
        raise errors.Conflict('Job is running')
    admin.audit(db, 'job:' + str(identifier), 'resume')
    return queued(db, identifier)


@route('/jobs/drain', 'POST')
@write(detached=True)
def post_jobs_drain(db, body):
    """Run the jobs that are due in this request (the pass the worker makes)."""
    from ..core.transaction import transaction
    source_ops.register_handlers()
    ran = fetch_jobs.drain(db) + Pipeline(db).drain(100)
    identifiers = [r['id'] for r in ran if 'id' in r]
    with transaction(db):
        admin.audit(db, 'jobs', 'drained', new={'jobs': identifiers})
    return Done(job_list(db, identifiers))


@route('/jobs/instruction-identities', 'POST')
@write
def post_jobs_instruction_identities(db, body):
    queued_ids, skipped = admin.queue_missing_booklets(db)
    admin.audit(db, 'jobs', 'queued_booklets', new={'jobs': queued_ids, 'skipped': skipped})
    return Done(job_list(db, queued_ids, skipped), status=202)


@route('/jobs/pictures', 'POST')
@write
def post_jobs_pictures(db, body):
    """Queue a picture refresh job for each held item of the chosen kinds that has none running."""
    via, actor = admin.origin()
    try:
        ids, selected = pictures.queue(db, body['scope'], body.get('kinds') or list(pictures.KIND_LABELS), body.get('expected_count'), via=via, actor=actor)
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None
    admin.audit(db, 'jobs', 'pictures_requested', new={'jobs': ids, 'selected': selected})
    return Done(job_list(db, ids), status=202)


@route('/items/<id>/import', 'POST')
@write
def post_items_by_id_import(db, body, id):
    """Queue the import steps for an item (the six of its kind's order unless `steps` names some)."""
    item_id = for_write(db, id)
    via, actor = admin.origin()
    steps = body.get('steps')
    if steps is not None and (not steps or any(s not in pipeline.STEPS for s in steps) or len(set(steps)) != len(steps)):
        raise errors.ValidationFailed('Unknown import step')
    return queued(db, Pipeline(db).queue_steps(item_id, steps, via=via, actor=actor))


@route('/items/<id>/prices/refresh', 'POST')
@write
def post_items_by_id_prices_refresh(db, body, id):
    """Queue a market price refresh for one item; an unfinished job of the item answers instead of a second one."""
    item_id = for_write(db, id)
    via, actor = admin.origin()
    live = admin.live_import_job(db, item_id)
    if live is not None:
        admin.audit(db, 'job:' + str(live), 'requested', new={'reused': True})
        return queued(db, live)
    return queued(db, Pipeline(db).queue_steps(item_id, ['market_price'], via=via, actor=actor))


@route('/prices/refresh', 'POST')
@write
def post_prices_refresh(db, body):
    """Queue a market price refresh for every held or wanted item whose price is stale."""
    ids = admin.queue_refresh(db, admin.stale_prices(db))
    admin.audit(db, 'jobs', 'prices_requested', new={'jobs': ids})
    return Done(job_list(db, ids))
