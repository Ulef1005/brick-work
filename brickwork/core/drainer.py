"""The embedded job drainer loop, shared by the web app and the API."""
from contextlib import closing
import os
import threading
import time

from datetime import datetime, timezone

from ..store4 import jobs, reconcile_job
from . import add, pipeline, source_ops
from .admin import begin_operation, end_operation
from .connect import connect
from .sources.base import audit_origin

# Two runners share the `job` table and each ignores the other's kinds: `store4.jobs` runs the two fetch kinds, `core.pipeline` the
# app's own `item` jobs (M.8c). Both are looked at here: one poll, one stop.
PENDING_SQL = (f"SELECT state, retry_at FROM job WHERE (kind IN {jobs.OWN_KINDS} OR kind IN ('{pipeline.KIND}', '{reconcile_job.KIND}')) "
               f"AND {jobs.ACTIVE}")


def poll_delay(db):
    """None when nothing is queued, running, waiting or due for a retry; else seconds to the next look (at most 60)."""
    rows = db.execute(PENDING_SQL).fetchall()
    if not rows:
        return None   # not jobs.has_leftovers: a copy offered the switch stays pending on a done job until the user answers
    if any(r['state'] in ('queued', 'running') for r in rows):
        return 1
    now = datetime.now(timezone.utc)
    waits = []
    for r in rows:
        if r['retry_at']:
            due = datetime.strptime(r['retry_at'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
            waits.append(max(0, (due - now).total_seconds()))
    return min(60, min(waits)) if waits else 60


def pending(db):
    """Is there work for the drainer at start-up: an active job, or copies still pending on a finished one (`jobs.has_leftovers`;
    the process stopped before settling them). One drain settles what can be settled, then `poll_delay` lets the worker stop."""
    return db.execute(PENDING_SQL + ' LIMIT 1').fetchone() is not None or jobs.has_leftovers(db) or add.has_unsettled_fetches(db)


def queue_startup_work(path):
    """At start (the embedded drainer's and `brickwork worker`'s): a catalogue swapped in but not reconciled yet becomes one reconcile job
    (design 6.2), run by the drain like any other. Returns the job id, or None when nothing is due."""
    with closing(connect(path, require_catalogue=False)) as db:          # no catalogue file: nothing to reconcile, and the first-run page must still load
        return reconcile_job.queue_if_due(db, via='app')


def drain_once(path):
    """One pass of both runners. The fetch jobs go first: a BrickLink or Rebrickable list a pipeline job looks for may have landed.
    Then the copies a finished Fetch from Rebrickable asked for are made (`add.settle_fetches`); their pipeline job runs on the next pass."""
    with closing(connect(path)) as db:
        ran = jobs.drain(db) + pipeline.drain(db)
        reconcile_job.drain(db)
        add.settle_fetches(db)
        return ran


def loop(path, sleep, *, stop=None):
    """Drain due jobs, then sleep until the next deadline; return when nothing is pending."""
    with audit_origin('app'):
        begin_operation()
        try:
            while stop is None or not stop.is_set():
                drain_once(path)
                with closing(connect(path)) as db:
                    delay = poll_delay(db)
                if delay is None:
                    return
                sleep(delay)
        finally:
            end_operation()


def spawn(target):
    """Seam for the embedded drainer's thread; tests replace it."""
    threading.Thread(target=target, name='brickwork-drainer', daemon=True).start()


def sleep(seconds):
    """Looked up at call time, so gevent's patching applies and tests can replace it."""
    time.sleep(seconds)


def enabled():
    """BW_EMBEDDED_WORKER=0 leaves draining to `brickwork worker` on headless installs."""
    return os.environ.get('BW_EMBEDDED_WORKER', '1').lower() not in ('0', 'false', 'no', 'off')


LOCK = threading.Lock()


def start(app, path, fallback=None):
    """One drainer per app; a daemon thread is the standalone default.

    The active flag is set and cleared under a lock (#68), and the drainer checks for due work once more
    before it clears the flag, so a job queued while it was stopping is not left waiting.
    """
    if not enabled():
        return False
    source_ops.register_handlers()                  # the pipeline runs the source steps only where a worker runs (a test's pipeline skips them)
    with LOCK:
        if app.extensions.get('bw_import_worker_active'):
            return True
        app.extensions['bw_import_worker_active'] = True
    launch = fallback or spawn

    def pending_work():
        with closing(connect(path)) as db:
            return poll_delay(db) is not None

    def run():
        try:
            with app.app_context():
                while True:
                    loop(path, sleep)
                    with LOCK:
                        if not pending_work():
                            app.extensions['bw_import_worker_active'] = False
                            return
        except BaseException:
            with LOCK:
                app.extensions['bw_import_worker_active'] = False
            raise
    try:
        launch(run)
    except Exception:
        with LOCK:
            app.extensions['bw_import_worker_active'] = False
        raise
    return True


def worker(*, path, stop=None, poll_seconds=None):
    """`brickwork worker`: drain the queue in this process until nothing is pending (the headless counterpart of the embedded drainer)."""
    source_ops.register_handlers()
    queue_startup_work(path)
    loop(path, sleep, stop=stop)
