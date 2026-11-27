"""Run a sync run (#519) as a durable `job` in the shared queue rather than inside one web request."""
from datetime import datetime, timezone
import json
import logging
import os
import sqlite3

from ...store4 import jobs
from .. import errors, sync
from ..admin import audit
from ..sources.base import WaitingForBudget, now
from ..transaction import transaction
from . import run as sync_run

KIND = 'sync_run'
STAGES = ('pull', 'parts', 'send', 'lost_out')
VALID_VIA = ('app', 'cli', 'api', 'import', 'migration')
INTERRUPTED_MESSAGE = sync_run.INTERRUPTED_MESSAGE
LOG = logging.getLogger(__name__)

_STAGE_NOW = {
    'pull': 'Pulling sets and wishes',
    'parts': 'Pulling loose stock',
    'send': 'Sending changes',
    'lost_out': 'Sending Lost Parts',
}


def _via(via):
    return via if via in VALID_VIA else 'app'


def _stage_total(run, plans, form_data, name):
    if name == 'pull':
        if not plans['pull']:
            return 0
        wanted = [k for k, v in form_data['chosen'].items() if v in ('pull', 'take')]
        lost = form_data['lost'] or []
        lists = sum(1 for v in form_data['lists'].values() if v not in ('keep', 'skip'))
        return len(wanted) + len(lost) + lists
    if name == 'parts':
        return len(form_data['part']) if plans['parts'] else 0
    if name == 'send':
        return sum(1 for v in form_data['chosen'].values() if v in ('send', 'remove')) if plans['send'] else 0
    if name == 'lost_out':
        return len(form_data['lostsend']) if sync_run.lost_out(run) else 0
    return 0


def _has_work(form_data, name, total):
    """A stage with changes to make, or a pull that only marks the rows that already match (its total stays 0: nothing changes)."""
    return total > 0 or (name == 'pull' and bool(form_data.get('marks')))


def _interrupted(db, run, plans, form_data, name):
    """A stage a dead owner left `started`: failed (`done` when every send's result was already saved), never run again. For the send stage the rows get the result the send plan kept. The row in
    flight is the one the worker recorded before its call (`job_progress.in_flight`, cleared after the call; Brickset: one call per set number, so
    that set's rows together): its result is `unknown`, because Brick Work cannot tell whether the call arrived. Rows with no kept result are
    `failed`, they did not go. `run.retry_send` sends again the `failed` ones, and an `unknown` one only when the person asks for that row."""
    stage = {'status': 'failed', 'message': INTERRUPTED_MESSAGE}
    if name == 'lost_out':
        wanted = set(form_data.get('lostsend') or ())
        saved = [r for r in (run.get('lost_out') or {}).get('rows', ()) if r.get('key') in wanted and r.get('outcome') == 'sent']
        if wanted and len(saved) == len(wanted):      # the restart came after the last Lost Part was saved: nothing is left to check
            return dict(status='done', counts=dict(sent=len(saved), failed=0, waiting=0))
    if name == 'send' and plans.get('send'):
        plan = sync.load_plan(db, plans['send']['id'], 'send')
        kept = plan.get('results') or {}
        wanted = [k for k, v in form_data['chosen'].items() if v in ('send', 'remove')]
        flight = (run.get('job_progress') or {}).get('in_flight')
        in_flight = {flight} if flight in wanted else set()
        if in_flight and plan.get('source') == 'brickset':
            by_key = {r['key']: r for r in plan['rows']}
            in_flight = {k for k in wanted if by_key[k]['remote_no'] == by_key[flight]['remote_no']}
        in_flight = {k for k in in_flight if kept.get(k, {}).get('result') not in ('sent', 'unchanged')}     # the call was made and its result saved before the restart: that is known
        rows = [dict(key=k, **(dict(result='unknown', detail=INTERRUPTED_MESSAGE) if k in in_flight else kept[k] if k in kept else dict(result='failed', detail=INTERRUPTED_MESSAGE))) for k in wanted]
        counts = {}
        for row in rows:
            counts[row['result']] = counts.get(row['result'], 0) + 1
        stage.update(counts=counts, rows=len(rows), results=rows)
        if not counts.get('unknown') and not counts.get('failed') and all(r['result'] in ('sent', 'unchanged') for r in rows):
            stage = dict(stage, status='done')           # the restart came after the last result was saved: nothing is left to check
            stage.pop('message')
    return stage


def _record_cut_off(db, job, run, plans, name):
    """The sync-log record of a send or Lost Parts stage that was cut off: an unfinished one reads Interrupted in Last runs, with a way back to
    its page."""
    stage = run['stages'][name]
    if name == 'send' and stage.get('counts'):
        record = dict(plan=plans['send']['id'], counts=stage['counts'])
    elif name == 'lost_out':      # counted from the rows known to have gone out
        gone_out = sum(1 for r in (run.get('lost_out') or {}).get('rows', ()) if r.get('outcome') == 'sent')
        record = dict(plan=run['id'], kind='lost_parts', counts=dict(sent=gone_out))
    else:
        return
    if stage.get('status') != 'done':
        record.update(interrupted=True, run=run['id'], pulls=sync_run.pull_events(run))
    with transaction(db):
        audit(db, 'sync:' + run.get('source', sync_run.SOURCE), 'send', None, record, via=job['via'], actor=job['actor'])


def _has_plan(run, plans, name):
    return bool(sync_run.lost_out(run)) if name == 'lost_out' else bool(plans.get(name))


def queue(db, run_id, form, *, via='app', actor=None):
    """Queue a durable `sync_run` job for `run_id` and return its job id. A run that already has a job returns that job's id and a run
    applied or being applied in a request returns None; neither queues anything."""
    with sync_run._Claim(db, run_id):
        run, plans = sync_run.load(db, run_id)
        if run.get('job') or run.get('applied') or run.get('applying'):
            return run.get('job')
        chosen = sync_run.validate_choices(db, run, plans, form)
        form_data = sync_run._extract_form(run, plans, form, chosen)
        form_data['marks'] = sync_run.marked_rows(db, run, plans, sync_run.pull_wanted(form_data)) > 0     # #531: a pull with no change to make can still have rows to mark
        steps = [(name, _stage_total(run, plans, form_data, name)) for name in STAGES]
        active_steps = [(name, total) for name, total in steps if _has_work(form_data, name, total)]
        t = now()
        stamp = jobs._stamp(t)
        source = run.get('source', sync_run.SOURCE)
        via = _via(via)
        with transaction(db):
            job_id = db.execute(
                '''INSERT INTO job(source, kind, item_id, state, payload, via, actor, created_at, updated_at)
                   VALUES(?, ?, NULL, 'queued', ?, ?, ?, ?, ?)''',
                (source, KIND, json.dumps({'run': run_id}), via, actor, stamp, stamp),
            ).lastrowid
            for pos, (name, total) in enumerate(active_steps):
                db.execute(
                    '''INSERT INTO job_step(job_id, name, position, sources, source, state, count, total, updated_at)
                       VALUES(?, ?, ?, ?, ?, 'queued', 0, ?, ?)''',
                    (job_id, name, pos, json.dumps([source]), source, total, stamp),
                )
        run['job_form'] = form_data
        run['job'] = job_id
        run['applying'] = t.isoformat()
        run['queued'] = t.isoformat()
        sync._store_plan(db, run)
        return job_id


def _job_for_run(db, run_id):
    try:
        run = sync.load_plan(db, run_id, 'run')
    except errors.ValidationFailed:
        row = db.execute("SELECT id FROM job WHERE kind=? AND json_extract(payload, '$.run')=? ORDER BY id DESC LIMIT 1", (KIND, run_id)).fetchone()
        return row['id'] if row else None
    return run.get('job')


def request_stop(db, run_id):
    """Ask the worker to stop after the call in flight by setting `stop` on `job.payload`."""
    sync_run._checked(run_id)
    job_id = _job_for_run(db, run_id)
    if job_id is None:
        return False
    stamp = jobs._stamp(now())
    with transaction(db):
        db.execute("UPDATE job SET payload=json_set(coalesce(payload, '{}'), '$.stop', 1), updated_at=? WHERE id=?", (stamp, job_id))
        db.execute("UPDATE job SET retry_at=? WHERE id=? AND state='waiting_for_budget'", (stamp, job_id))     # a waiting job is claimed at once, to stop
    return True


def _stop_requested(db, job_id):
    row = db.execute('SELECT payload FROM job WHERE id=?', (job_id,)).fetchone()
    if not row or not row['payload']:
        return False
    return bool(json.loads(row['payload']).get('stop'))


def _refresh_plans(db, run, t=None):
    stamp = (t or now()).isoformat()
    run['created_at'] = stamp
    sync._store_plan(db, run)
    for name in ('pull', 'send', 'parts'):
        plan_id = run.get(name)
        if not plan_id:
            continue
        try:
            plan = sync.load_plan(db, plan_id)
            plan['created_at'] = stamp
            sync._store_plan(db, plan)
        except errors.ValidationFailed:
            pass


def _retry_stamp(retry_at, t):
    if not retry_at:
        return jobs._stamp(jobs._midnight(t))
    if isinstance(retry_at, datetime):
        dt = retry_at if retry_at.tzinfo else retry_at.replace(tzinfo=timezone.utc)
        return jobs._stamp(dt)
    dt = datetime.fromisoformat(str(retry_at).replace('Z', '+00:00'))
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return jobs._stamp(dt)


def _call_label(name, run, plans, key):
    if name == 'send':
        for row in (plans.get('send') or {}).get('rows', ()):
            if row['key'] == key:
                return f"Sending {row.get('number') or row.get('name') or key}"
    if name == 'lost_out':
        for row in (run.get('lost_out') or {}).get('rows', ()):
            if row['key'] == key:
                return f"Sending Lost Part {row.get('set_no')} {row.get('part_no')}"
    return _STAGE_NOW.get(name)


def _claim(db, job_id, t):
    stamp = jobs._stamp(t)
    with transaction(db):
        job = db.execute('SELECT * FROM job WHERE id=?', (job_id,)).fetchone()
        if job is None or job['kind'] != KIND:
            return None
        due = job['retry_at'] is not None and job['retry_at'] <= stamp
        if not (job['state'] in ('queued', 'running') or (job['state'] == 'waiting_for_budget' and due)):
            return None
        owner = db.execute('SELECT pid, boot_id, start_ticks FROM job_owner WHERE job_id=?', (job_id,)).fetchone()
        if owner and jobs._alive(db, owner[0], job_id, owner[1], owner[2]):
            return None
        db.execute('INSERT OR REPLACE INTO job_owner(job_id, pid, claimed_at, boot_id, start_ticks) VALUES(?, ?, ?, ?, ?)',
                   (job_id, os.getpid(), stamp, *jobs.owner_identity()))
        db.execute("UPDATE job SET state='running', attempts=attempts+1, retry_at=NULL, error=NULL, error_code=NULL, updated_at=? WHERE id=?",
                   (stamp, job_id))
        jobs._CLAIMED.add((os.getpid(), jobs._path(db), job_id))
        return dict(db.execute('SELECT * FROM job WHERE id=?', (job_id,)).fetchone())


def _set_step(db, job_id, name, state, *, count=None, error=None, error_code=None, retry_at=None):
    stamp = jobs._stamp(now())
    if count is None:
        db.execute('UPDATE job_step SET state=?, error=?, error_code=?, retry_at=?, updated_at=? WHERE job_id=? AND name=?',
                   (state, error, error_code, retry_at, stamp, job_id, name))
    else:
        db.execute('UPDATE job_step SET state=?, count=?, error=?, error_code=?, retry_at=?, updated_at=? WHERE job_id=? AND name=?',
                   (state, count, error, error_code, retry_at, stamp, job_id, name))


def _drop_unsent_lost_parts(db, job_id, run):
    """A job queued before the send was locked still has Lost Parts out: nothing of it is sent, so its stage waits for nothing and its
    step is closed. A stage that already has an outcome keeps it."""
    if not run.get('lost_out') or sync_run.lost_out(run) is not None:
        return
    stage = run['stages'].get('lost_out') or {}
    if stage.get('status') in ('done', 'failed', 'partial', 'stopped', 'none'):
        return
    # a stage that had begun keeps its counts, failures and message (what was sent, what may be gone); it is stopped, not erased
    run['stages']['lost_out'] = dict(stage, status='stopped') if stage else dict(status='none')
    _refresh_plans(db, run)
    with transaction(db):
        db.execute("UPDATE job_step SET state='done', count=total, error=NULL, error_code=NULL, retry_at=NULL, updated_at=? WHERE job_id=? AND name='lost_out'",
                   (jobs._stamp(now()), job_id))


def _finish_stopped(db, job, run, plans, form_data, start_idx):
    _drop_unsent_lost_parts(db, job['id'], run)
    for name in STAGES[start_idx:]:
        existing = run['stages'].get(name)
        if existing and existing.get('status') in ('done', 'none', 'failed', 'stopped'):
            continue
        if not _has_plan(run, plans, name):
            continue
        if _stage_total(run, plans, form_data, name) == 0:
            run['stages'][name] = dict(status='none')
        else:
            run['stages'][name] = dict(existing or {}, status='stopped')       # a waiting stage keeps its rows for retry_send
            with transaction(db):
                _set_step(db, job['id'], name, 'done', error='Stopped at your request')
    _settle_done(db, job, run, error='Stopped at your request')


def _settle_done(db, job, run, *, error=None):
    events = sync_run.pull_events(run)
    t = now()
    stamp = jobs._stamp(t)
    source = run.get('source', sync_run.SOURCE)
    if error is None and any(st.get('status') in ('failed', 'partial') or (st.get('counts') or {}).get('key_rejected') for st in run['stages'].values()):
        error = 'Some changes were not made; see the result'
    run['applied'] = dict(at=t.isoformat(), events=events)       # the run first: a crash between the two leaves a done run, which a takeover settles
    run.pop('applying', None)
    if 'job_progress' in run:
        run['job_progress']['now'] = None
    _refresh_plans(db, run, t)
    with transaction(db):
        audit(db, 'sync:' + source, 'run', None, dict(run=run['id'], events=events), via=job['via'], actor=job['actor'])
        db.execute("UPDATE job SET state='done', error=?, error_code=NULL, retry_at=NULL, updated_at=? WHERE id=?",
                   (error, stamp, job['id']))
        db.execute('DELETE FROM job_owner WHERE job_id=?', (job['id'],))


def _settle_budget(db, job, run, stage_name, stage_msg, retry_at):
    t = now()
    stamp = jobs._stamp(t)
    retry_stamp = _retry_stamp(retry_at, t)
    if 'job_progress' in run:
        run['job_progress']['now'] = None
    _refresh_plans(db, run, t)
    with transaction(db):
        _set_step(db, job['id'], stage_name, 'waiting_for_budget', error=stage_msg, error_code='budget', retry_at=retry_stamp)
        db.execute("UPDATE job SET state='waiting_for_budget', error_code='budget', error=?, retry_at=?, updated_at=? WHERE id=?",
                   (stage_msg, retry_stamp, stamp, job['id']))
        db.execute('DELETE FROM job_owner WHERE job_id=?', (job['id'],))


def _run_one(db, job, http):
    job_id = job['id']
    run_id = json.loads(job['payload'])['run']
    with sync_run._Claim(db, run_id):        # `queue` stores the form under this lock, after it commits the job
        run, plans = sync_run.load(db, run_id)
    form_data = run.get('job_form')
    if form_data is None:
        raise ValueError('Run has no job_form')
    if run.get('applied'):                   # settled in the run, the process stopped before the job: close the job only
        with transaction(db):
            db.execute("UPDATE job SET state='done', updated_at=? WHERE id=?", (jobs._stamp(now()), job_id))
            db.execute('DELETE FROM job_owner WHERE job_id=?', (job_id,))
        return
    run['applying'] = now().isoformat()
    prog = run.setdefault('job_progress', {})
    prog.setdefault('started_at', now().isoformat())
    prog.setdefault('calls', [])
    prog['now'] = None
    _refresh_plans(db, run)

    if not run['stages']:        # the first pass only: a resume would write the Keep choices of an older preview over newer ones
        if _stop_requested(db, job_id):      # stopped before it started: nothing is done, not even the Keep choices
            _finish_stopped(db, job, run, plans, form_data, 0)
            return
        sync_run.remember_choices(db, run, plans, form_data)
    for idx, name in enumerate(STAGES):
        existing = run['stages'].get(name)
        if existing and existing.get('status') in ('done', 'none', 'failed', 'stopped'):
            continue
        if existing and existing.get('status') == 'started':
            run['stages'][name] = _interrupted(db, run, plans, form_data, name)
            _refresh_plans(db, run)
            finished = run['stages'][name].get('status') == 'done'
            _record_cut_off(db, job, run, plans, name)
            with transaction(db):
                if finished:
                    _set_step(db, job_id, name, 'done')
                    db.execute('UPDATE job_step SET count=total WHERE job_id=? AND name=?', (job_id, name))
                else:
                    _set_step(db, job_id, name, 'failed', error=INTERRUPTED_MESSAGE)
            continue
        if not _has_plan(run, plans, name):
            if name == 'lost_out':
                _drop_unsent_lost_parts(db, job_id, run)
            continue
        total = _stage_total(run, plans, form_data, name)
        if not _has_work(form_data, name, total):
            run['stages'][name] = dict(status='none')
            _refresh_plans(db, run)
            continue
        if _stop_requested(db, job_id):
            _finish_stopped(db, job, run, plans, form_data, idx)
            return

        run['stages'][name] = {'status': 'started'}
        prog['now'] = _STAGE_NOW.get(name)
        _refresh_plans(db, run)
        with transaction(db):
            _set_step(db, job_id, name, 'running')

        paused_holder = {'retry_at': None}
        done_holder = {'count': 0}

        def on_call(event, key, count, *, retry_at=None, _name=name, _holder=paused_holder, _done=done_holder):
            _done['count'] = count
            if event == 'before':
                prog['now'] = _call_label(_name, run, plans, key)
                prog['in_flight'] = key if _name == 'send' else None     # written down before the call: a restart then knows which send was cut off
                _refresh_plans(db, run)
            elif event == 'after':
                prog['in_flight'] = None
                ts = now().timestamp()
                prog['calls'] = [c for c in prog.get('calls', []) if c >= ts - 60.0] + [ts]
                _refresh_plans(db, run)
                with transaction(db):
                    db.execute('UPDATE job_step SET count=?, updated_at=? WHERE job_id=? AND name=?',
                               (count, jobs._stamp(now()), job_id, _name))
            elif event == 'paused':
                prog['in_flight'] = None
                _holder['retry_at'] = retry_at
                _refresh_plans(db, run)
                with transaction(db):
                    db.execute('UPDATE job_step SET count=?, updated_at=? WHERE job_id=? AND name=?',
                               (count, jobs._stamp(now()), job_id, _name))

        try:
            if name == 'pull':
                stage = sync_run.stage_pull(db, run, plans, form_data, via=job['via'], actor=job['actor'], raise_budget=True)
            elif name == 'parts':
                stage = sync_run.stage_parts(db, run, plans, form_data, via=job['via'], actor=job['actor'], raise_budget=True)
            elif name == 'send':
                stage = sync_run.stage_send(db, run, plans, form_data, http=http, per_key=True,
                                            should_stop=lambda: _stop_requested(db, job_id), on_call=on_call)
            else:
                stage = sync_run.stage_lost_out(db, run, form_data, http=http, per_key=True,
                                                should_stop=lambda: _stop_requested(db, job_id), on_call=on_call)
        except WaitingForBudget as exc:
            stage = run['stages'][name]
            _settle_budget(db, job, run, name, stage.get('message'), exc.retry_at)
            return

        _refresh_plans(db, run)
        status = (stage or {}).get('status')
        if status == 'waiting':
            _settle_budget(db, job, run, name, stage.get('message'), paused_holder['retry_at'])
            return
        if status == 'stopped':
            with transaction(db):
                _set_step(db, job_id, name, 'done', count=done_holder['count'], error='Stopped at your request')
            _finish_stopped(db, job, run, plans, form_data, idx + 1)
            return
        with transaction(db):
            if status == 'failed':
                _set_step(db, job_id, name, 'failed', count=done_holder['count'], error=stage.get('message'))
            else:
                _set_step(db, job_id, name, 'done', count=total)

    _settle_done(db, job, run)


def _fail_unexpected(db, job_id, *, write_failed=False):
    """An unexpected error in the worker. The job ends failed (done, when the run was already settled). A run that had begun shows its stages as
    they stand, with the run's audit entry, so the result page, undo and `retry_send` work; a run that never began is released to be queued again."""
    if db.in_transaction:
        db.rollback()
    stamp = jobs._stamp(now())
    job = run = plans = None
    try:
        job = db.execute('SELECT * FROM job WHERE id=?', (job_id,)).fetchone()
        run, plans = sync_run.load(db, json.loads(job['payload'])['run'])
    except Exception as exc:
        LOG.warning('sync_run job %s: its run could not be read: %s', job_id, type(exc).__name__)
    settled = bool(run and run.get('applied'))
    began = bool(run and any(st.get('status') != 'none' for st in run['stages'].values()))        # a `none` record is written before any work
    msg = 'The result was recorded, but the last step of the job failed' if settled else jobs._safe('Sync run failed unexpectedly')
    with transaction(db):
        db.execute("UPDATE job SET state=?, error_code=?, error=?, retry_at=NULL, updated_at=? WHERE id=?",
                   ('done' if settled else 'failed', None if settled else 'source_error', msg, stamp, job_id))
        finished = [n for n, st in (run['stages'] if run else {}).items() if st.get('status') in ('done', 'none')]      # saved before the error: not failed
        for name in finished:
            db.execute("UPDATE job_step SET state='done', count=total, updated_at=? WHERE job_id=? AND name=? AND state IN ('running', 'queued')",
                       (stamp, job_id, name))
        db.execute("UPDATE job_step SET state='failed', error_code='source_error', error=?, updated_at=? WHERE job_id=? AND state IN ('running', 'queued')",
                   (msg, stamp, job_id))
        db.execute('DELETE FROM job_owner WHERE job_id=?', (job_id,))
    if run is None:
        return
    try:
        run.pop('applying', None)
        cut_off = []
        if 'job_progress' in run:
            run['job_progress']['now'] = None
        if not began and not settled:      # nothing ran: the run can be queued again
            for key in ('job', 'job_form', 'job_progress'):
                run.pop(key, None)
        elif not settled:
            if write_failed:      # the data folder or database refused a write: what is stored may lack what went out, and the run page warns of that
                run['write_failed'] = True
            for name, stage in run['stages'].items():
                if stage.get('status') == 'started':
                    run['stages'][name] = dict(_interrupted(db, run, plans, run['job_form'], name), cause='error')      # no restart: the run page says so
                    cut_off.append(name)
            events = [st['event'] for st in run['stages'].values() if st.get('event') is not None]
            run['applied'] = dict(at=now().isoformat(), events=events)
        sync._store_plan(db, run)             # the run first: a failing audit below must not leave it stuck as running
        for name in cut_off:
            _record_cut_off(db, job, run, plans, name)
            if run['stages'][name]['status'] == 'done':      # every result was saved before the error
                with transaction(db):
                    db.execute("UPDATE job_step SET state='done', count=total, error=NULL, error_code=NULL WHERE job_id=? AND name=?", (job_id, name))
        if began and not settled:
            with transaction(db):
                audit(db, 'sync:' + run.get('source', sync_run.SOURCE), 'run', None, dict(run=run['id'], events=run['applied']['events']), via=job['via'], actor=job['actor'])
    except Exception as exc:
        LOG.warning('sync_run job %s: the failed run could not be stored: %s', job_id, type(exc).__name__)


def drain(db, http=None):
    """Run every runnable `sync_run` job (queued, dead-owner running, or due waiting_for_budget)."""
    stamp = jobs._stamp(now())
    ids = [r[0] for r in db.execute(
        '''SELECT id FROM job
           WHERE kind=?
             AND (state IN ('queued', 'running')
                  OR (state='waiting_for_budget' AND retry_at IS NOT NULL AND retry_at<=?))
           ORDER BY id''',
        (KIND, stamp),
    ).fetchall()]
    ran = []
    path = jobs._path(db)
    for job_id in ids:
        try:
            job = _claim(db, job_id, now())
        except sqlite3.OperationalError as exc:          # the collection is busy: this pass leaves the job, the next one takes it
            LOG.warning('sync_run job %s not claimed: %s', job_id, type(exc).__name__)
            continue
        if job is None:
            continue
        try:
            _run_one(db, job, http)
            ran.append(dict(db.execute('SELECT * FROM job WHERE id=?', (job_id,)).fetchone()))
        except Exception as exc:
            LOG.warning('sync_run job %s failed unexpectedly: %s', job_id, type(exc).__name__)
            _fail_unexpected(db, job_id, write_failed=isinstance(exc, (OSError, sqlite3.Error)))
        except BaseException:
            if db.in_transaction:
                db.rollback()
            with transaction(db):
                db.execute('DELETE FROM job_owner WHERE job_id=?', (job_id,))
            raise
        finally:
            jobs._CLAIMED.discard((os.getpid(), path, job_id))
    return ran


def progress(db, run_id):
    """Read-only progress snapshot of a `sync_run` job for the page and API."""
    run = sync.load_plan(db, run_id, 'run')
    job_id = run.get('job')
    job_row = db.execute('SELECT * FROM job WHERE id=?', (job_id,)).fetchone() if job_id is not None else None
    steps = db.execute('SELECT * FROM job_step WHERE job_id=? ORDER BY position', (job_id,)).fetchall() if job_id is not None else []
    payload = json.loads(job_row['payload'] or '{}') if job_row and job_row['payload'] else {}
    prog = run.get('job_progress') or {}
    run_stages = run.get('stages') or {}
    current_now = prog.get('now')
    stage_list = []
    for step in steps:
        name = step['name']
        st = (run_stages.get(name) or {}).get('status') or step['state']
        stage_list.append(dict(
            name=name,
            status=st,
            done=step['count'],
            total=step['total'],
            now=current_now if st == 'started' else None,
        ))
    done = sum(s['done'] for s in stage_list)
    total = sum(s['total'] for s in stage_list)
    current_ts = now().timestamp()
    recent_calls = [ts for ts in (prog.get('calls') or []) if ts >= current_ts - 30.0]
    rps = len(recent_calls) / 30.0 if len(recent_calls) >= 2 else None
    started_at = prog.get('started_at')
    seconds_left = None
    if started_at and done > 0:
        elapsed = current_ts - datetime.fromisoformat(started_at).timestamp()
        if elapsed > 0:
            seconds_left = max(0, total - done) / (done / elapsed)
    source = run.get('source', sync_run.SOURCE)
    state = job_row['state'] if job_row else ('done' if run.get('applied') else None)
    return {
        'job': job_id,
        'state': state,
        'done': done,
        'total': total,
        'stages': stage_list,
        'now': current_now,
        'started_at': started_at,
        'requests_per_second': rps,
        'seconds_left': seconds_left,
        'budget': sync_run.budget(db, source),
        'stop_requested': bool(payload.get('stop')),
        'retry_at': job_row['retry_at'] if job_row else None,
        'error': job_row['error'] if job_row else None,
        'result': run.get('applied'),
    }
