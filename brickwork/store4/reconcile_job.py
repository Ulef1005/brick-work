"""The start-up reconcile (design 6.2, M.10c): a catalogue swapped in but not reconciled yet (`catalogue_build.reconciled_at` NULL), found when
the app or its worker starts, becomes one `reconcile` job in the collection's `job` table; the drainer runs it, never a request.

`queue_if_due` is idempotent: while a reconcile job is queued or running, its id is returned instead of a second job. `drain` claims a queued
job (or one whose process died), activates any build the collection has not recorded yet, runs `reconcile`, and settles the job `done` or
`failed` with the reason. Nothing here touches the schema: the job is an ordinary row (source `mapping`, kind `reconcile`, no steps)."""
import os

from .activate import activate
from .audit import Events, transaction
from .connect import has_catalogue
from .jobs import ACTIVE, _alive, _now, _stamp
from .reconcile import reconcile

KIND, SOURCE = 'reconcile', 'mapping'


def reconcile_due(db):
    """Is a build activated in this collection still waiting for its reconcile, or a catalogue build not yet activated?"""
    if not has_catalogue(db):
        return False
    if db.execute('SELECT 1 FROM main.catalogue_build WHERE reconciled_at IS NULL LIMIT 1').fetchone():
        return True
    return db.execute('SELECT 1 FROM catalogue.build WHERE id NOT IN (SELECT id FROM main.catalogue_build) LIMIT 1').fetchone() is not None


def active_job(db):
    """The queued or running reconcile job's id, else None."""
    row = db.execute(f"SELECT id FROM main.job WHERE kind=? AND {ACTIVE} ORDER BY id LIMIT 1", (KIND,)).fetchone()
    return row[0] if row else None


def queue_if_due(db, *, via='app', actor=None, now=None):
    """Queue a reconcile job when one is due and none is open; returns its id (the open one's when it exists), or None when nothing is due."""
    if not reconcile_due(db):
        return None
    with transaction(db, 'queueing the reconcile'):
        found = active_job(db)
        if found:
            return found
        stamp = _stamp(_now(now))
        job = db.execute('''INSERT INTO main.job(source, kind, state, payload, via, actor, created_at, updated_at)
                            VALUES(?, ?, 'queued', NULL, ?, ?, ?, ?)''', (SOURCE, KIND, via, actor, stamp, stamp)).lastrowid
        Events(db, via, actor).write('job', job, 'created', new={'kind': KIND})
        return job


def _claim(db, job_id, stamp):
    """Take a queued job, or a running one whose owner is gone; False when another process has it."""
    with transaction(db, 'claiming the reconcile'):
        job = db.execute('SELECT state FROM main.job WHERE id=?', (job_id,)).fetchone()
        owner = db.execute('SELECT pid FROM main.job_owner WHERE job_id=?', (job_id,)).fetchone()
        if job is None or job['state'] not in ('queued', 'running') or (owner and _alive(db, owner[0], job_id)):
            return False
        db.execute('INSERT OR REPLACE INTO main.job_owner(job_id, pid, claimed_at) VALUES(?, ?, ?)', (job_id, os.getpid(), stamp))
        db.execute("UPDATE main.job SET state='running', attempts=attempts+1, error=NULL, updated_at=? WHERE id=?", (stamp, job_id))
        return True


def drain(db, *, now=None):
    """Run the queued reconcile jobs; returns `[{id, state, error}]` of the ones this call ran."""
    ran = []
    for (job_id,) in db.execute(f"SELECT id FROM main.job WHERE kind=? AND state IN ('queued','running') ORDER BY id", (KIND,)).fetchall():
        stamp = _stamp(_now(now))
        if not _claim(db, job_id, stamp):
            continue
        state, error = 'done', None
        try:
            activate(db, via='app')
            reconcile(db, via='app')
        except Exception as exc:                          # the reason is shown on the job; the old state is untouched (reconcile is one transaction)
            state, error = 'failed', str(exc)[:300]
        with transaction(db, 'settling the reconcile'):
            db.execute('UPDATE main.job SET state=?, error=?, updated_at=? WHERE id=?', (state, error, _stamp(_now(now)), job_id))
            db.execute('DELETE FROM main.job_owner WHERE job_id=?', (job_id,))
        ran.append(dict(id=job_id, state=state, error=error))
    return ran
