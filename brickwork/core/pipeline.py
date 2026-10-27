"""The import pipeline on the 4.0 store (M.8c, issue #110; design 5.2, 6.5, 3.8): one `pipeline` job per Add, six steps.

A job is a row of `job` (source `import`, kind `item`, `item_id` the item) with one `job_step` per step name; the order and the
step names come from the setting `import_order:<kind>` (the migration carries it, kind words), default `STEPS`. The job survives a
restart and is run by `core.drainer` beside `store4.jobs` (which runs only its own two fetch kinds and ignores this one).

What a step does until the source handlers return (M.8f):

- `identity`, `inventory`, `matching` finish locally from the catalogue and the collection; no network. A step that finds nothing to
  work with ends `done` with the code `unidentified` (the item has no number from any provider, or no BrickLink number for
  `matching`) or `not_found` (an identified set or figure with no part list); a finding is not a failure, so the job finishes.
- `pictures`, `metadata` and `market_price` need a source handler. Handlers are registered with `register(step, source, handler)`
  (M.8f does that). A step with no handler for any of its sources ends `done` with `error` = `SKIPPED`, count 0 and no source, so
  the job finishes and a screen can say the step was skipped; it is not `failed` and `queue_retry` leaves it alone. A handler
  registered later runs for new jobs; steps already skipped stay skipped (a pictures refresh is queued explicitly).

A handler is `handler(db, job, step)`; it returns normally (step done), raises `StepDone(code, message)` (done with a finding, such as
`unidentified` for an item with no number the source knows), `StepWait(retry_at, why)` (waiting for budget) or `StepFailed(code, message)`
(failed). The job is `done` when no step failed or waits, `waiting_for_budget` with the earliest
`retry_at` while one waits, else `failed`; `queue_retry` puts failed steps back.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import re

from ..store4.audit import Events
from ..store4.connect import has_catalogue, now
from . import items
from .connect import connect
from .transaction import transaction

STEPS = ('identity', 'inventory', 'matching', 'pictures', 'metadata', 'market_price')
TYPES = set(items.KINDS)                        # the keys of `import_order:<kind>` and of the per-kind source lists
KIND, SOURCE = 'item', 'import'                  # design 5.2 and the user journey: `job(source=import, kind=item, item_id)` + six `job_step`
LOCAL = ('identity', 'inventory', 'matching')
SKIPPED = 'skipped: no source handler is registered for this step'
DEFAULT_PRIORITY = {                            # design 6.8 for the pictures; `core.pictures.DEFAULT_ORDER` is the same table
    'pictures': {'part': ['rebrickable_dump', 'bricklink', 'rebrickable_api'], '*': ['bricklink', 'rebrickable_dump']},
    'metadata': {'set': ['brickset']}, 'market_price': {'*': ['bricklink']},
}
LABELS = {'identity': 'Checking identity', 'inventory': 'Checking the part list', 'matching': 'Matching ids',
          'pictures': 'Downloading images', 'metadata': 'Fetching set metadata', 'market_price': 'Fetching market price'}
NAMES = {'bricklink': 'BrickLink', 'rebrickable': 'Rebrickable', 'rebrickable_dump': 'Rebrickable', 'rebrickable_api': 'Rebrickable',
         'brickset': 'Brickset', 'catalogue': 'Catalogue', 'picture_refresh': 'Pictures'}
LEGACY_PICTURE_SOURCES = {'rebrickable': ('rebrickable_dump', 'rebrickable_api')}
HANDLERS = {}                                   # (step, source) -> handler(db, job, step); filled by `core.source_ops.register_handlers`
_CLAIMED_JOBS = set()                           # (pid, path, job) this process is running


class StepWait(Exception):
    """Raised by a handler: the step waits for a budget or a rate pause until `retry_at` (an ISO stamp)."""

    def __init__(self, retry_at, why='waiting for budget'):
        super().__init__(why)
        self.retry_at, self.why = retry_at, why


class StepDone(Exception):
    """Raised by a handler that found nothing to work with: the step ends done with the finding (`unidentified`, `not_found`)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class StepFailed(Exception):
    """Raised by a handler: the step failed with one of the job_step error codes."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def register(step, source, handler):
    """Run `handler(db, job, step)` for `step` when `source` is the one being tried (M.8f)."""
    if step not in STEPS:
        raise ValueError(f'{step!r} is not a pipeline step')
    HANDLERS[step, source] = handler


def yield_worker(db):
    """Never switch greenlets while this connection holds a transaction."""
    if db.in_transaction:
        return
    import sys
    monkey = sys.modules.get('gevent.monkey')
    if monkey and monkey.is_module_patched('time'):
        sys.modules['gevent'].sleep(0)


def cooperative(db, rows):
    """Cooperate after each unit unless a transaction is still open."""
    for row in rows:
        try:
            yield row
        finally:
            yield_worker(db)


def owner_pid_alive(pid, *, path=None, job=None):
    """A same-pid row is live only when this process holds its job claim."""
    if pid is None:
        return False
    if pid == os.getpid():
        return (pid, str(Path(path).resolve()), job) in _CLAIMED_JOBS if path is not None else False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def validate_priority(value):
    """A `source_priority` value: some of the six steps, each `{kind or '*': [source ids]}`."""
    if not isinstance(value, dict) or not set(value) <= set(STEPS):
        raise ValueError('source_priority names only the pipeline steps')
    for step, kinds in value.items():
        if not isinstance(kinds, dict) or not kinds or any(k not in TYPES | {'*'} for k in kinds):
            raise ValueError('invalid item kind')
        for sources in kinds.values():
            if (not isinstance(sources, list) or not sources
                    or any(not isinstance(s, str) or not re.fullmatch('[a-z][a-z0-9_:]*', s) for s in sources)
                    or len(sources) != len(set(sources))):
                raise ValueError('invalid source priority')
    return value


def _setting(db, key):
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (key,)).fetchone()
    return row[0] if row else None


def order_for(db, kind):
    """The steps to run for an item of `kind`: `import_order:<kind>`, else every step in `STEPS` order."""
    raw = _setting(db, 'import_order:' + kind)
    order = json.loads(raw) if raw else list(STEPS)
    if not isinstance(order, list) or len(order) != len(STEPS) or set(order) != set(STEPS):
        raise ValueError('Check the import order in Tools & Admin')
    return order


def sources_for(db, step, kind):
    """The source ids a step tries, in order: the local steps use the catalogue; the others the kind's list of `source_priority`
    (the setting when it names the step, else `DEFAULT_PRIORITY`)."""
    if step in LOCAL:
        return ['catalogue']
    stored = _setting(db, 'source_priority')
    table = json.loads(stored).get(step) if stored else None
    table = table or DEFAULT_PRIORITY.get(step) or {}
    wanted = list(table.get(kind, table.get('*', [])))
    if step == 'pictures':                                          # 3.3's `rebrickable` in a file written before the migration translated it
        wanted = [s.split(':')[0] for s in wanted]                  # a suffix means nothing for a picture source (`core.pictures.order` drops it too)
        wanted = list(dict.fromkeys(n for s in wanted for n in LEGACY_PICTURE_SOURCES.get(s, (s,))))
    return wanted


class Pipeline:
    def __init__(self, db, *, handlers=None):
        self.db = db
        self.path = Path(db.execute('PRAGMA database_list').fetchone()['file'])
        self.handlers = handlers or {}            # per instance, tried before the module registry

    # ---- queue ----

    def queue_steps(self, item_id, steps=None, *, via, actor=None, refresh=False):
        """Queue a job for the item and return its id. Writes inside the caller's open write transaction (Add's). `refresh` asks the
        steps to fetch again what they already have (a picture refresh of every held item)."""
        if not self.db.in_transaction:
            raise ValueError('queue_steps needs the caller\'s open write transaction')
        if via not in ('app', 'cli', 'api', 'import'):
            raise ValueError('invalid import origin')
        items.ensure(self.db, item_id)
        kind = self.db.execute('SELECT kind FROM main.item WHERE id=?', (item_id,)).fetchone()['kind']
        steps = list(steps) if steps is not None else order_for(self.db, kind)
        if not steps or any(s not in STEPS for s in steps) or len(set(steps)) != len(steps):
            raise ValueError('invalid refresh steps')
        stamp, actor = now(), actor if via == 'api' else None
        job = self.db.execute('''INSERT INTO main.job(source, kind, item_id, state, payload, via, actor, created_at, updated_at)
                                 VALUES(?, ?, ?, 'queued', ?, ?, ?, ?, ?)''',
                              (SOURCE, KIND, item_id, json.dumps({'steps': steps, **({'refresh': True} if refresh else {})}), via, actor, stamp, stamp)).lastrowid
        for position, step in enumerate(steps):
            self.db.execute('INSERT INTO main.job_step(job_id, name, position, sources, total, updated_at) VALUES(?, ?, ?, ?, 1, ?)',
                            (job, step, position, json.dumps(sources_for(self.db, step, kind)), stamp))
        Events(self.db, via, actor).write('job', job, 'queued', new={'kind': KIND, 'item_id': item_id, 'steps': steps})
        return job

    def status(self, job):
        row = self.db.execute('SELECT * FROM main.job WHERE id=? AND kind=?', (job, KIND)).fetchone()
        if not row:
            raise ValueError('unknown import job')
        return {**dict(row), 'steps': [dict(s) for s in self.db.execute('SELECT * FROM main.job_step WHERE job_id=? ORDER BY position', (job,))]}

    def list_jobs(self, failed=False):
        return [self.status(r[0]) for r in self.db.execute(
            "SELECT id FROM main.job WHERE kind=? AND (?=0 OR state='failed' OR EXISTS "
            "(SELECT 1 FROM main.job_step WHERE job_id=job.id AND state='failed')) ORDER BY id DESC", (KIND, int(failed)))]

    def queue_retry(self, job, step=None):
        """Put the failed steps (or the named failed step) back to queued, and the job with them."""
        with transaction(self.db):
            snapshot = self.status(job)
            if self.owner_alive(job):
                raise ValueError('import job is running')
            if step is not None and step not in {s['name'] for s in snapshot['steps']}:
                raise ValueError('unknown import step')
            stamp = now()
            for saved in snapshot['steps']:
                if saved['state'] != 'failed' or step is not None and saved['name'] != step:
                    continue
                self.db.execute('''UPDATE main.job_step SET state='queued', source_index=0, error=NULL, error_code=NULL, retry_at=NULL,
                                   updated_at=? WHERE job_id=? AND name=?''', (stamp, job, saved['name']))
            self.db.execute("UPDATE main.job SET state='queued', error=NULL, error_code=NULL, retry_at=NULL, updated_at=? WHERE id=?", (stamp, job))
        return job

    def retry(self, job, step=None):
        self.queue_retry(job, step)
        return self.run(job)

    # ---- run ----

    def owner_alive(self, job):
        owner = self.db.execute('SELECT pid FROM main.job_owner WHERE job_id=?', (job,)).fetchone()
        return owner_pid_alive(owner[0] if owner else None, path=self.path, job=job)

    def _claim(self, job):
        """Take the job if it may run now: its snapshot, or None (not runnable, finished, or another process has it)."""
        with transaction(self.db):
            snapshot = self.status(job)
            due = snapshot['state'] in ('waiting_for_budget', 'failed') and snapshot['retry_at'] and snapshot['retry_at'] <= now()
            if not (snapshot['state'] in ('queued', 'running') or due) or self.owner_alive(job):
                return None
            stamp = now()
            self.db.execute('INSERT OR REPLACE INTO main.job_owner(job_id, pid, claimed_at) VALUES(?, ?, ?)', (job, os.getpid(), stamp))
            self.db.execute("UPDATE main.job SET state='running', attempts=attempts+1, retry_at=NULL, updated_at=? WHERE id=?", (stamp, job))
            _CLAIMED_JOBS.add((os.getpid(), str(self.path.resolve()), job))
            return self.status(job)

    def _put(self, job, step, state, *, source=None, error=None, code=None, retry_at=None, count=0, total=1):
        with transaction(self.db):
            self.db.execute('''UPDATE main.job_step SET state=?, source=?, error=?, error_code=?, retry_at=?, count=?, total=?, updated_at=?
                               WHERE job_id=? AND name=?''', (state, source, error, code, retry_at, count, total, now(), job, step))

    def run(self, job):
        snapshot = self._claim(job)
        if snapshot is None:
            return self.status(job)
        try:
            for saved in cooperative(self.db, snapshot['steps']):
                if saved['state'] in ('done', 'failed'):
                    continue
                if saved['state'] == 'waiting_for_budget' and saved['retry_at'] and saved['retry_at'] > now():
                    continue
                self._step(snapshot, saved)
            steps = self.status(job)['steps']
            waits = [s['retry_at'] for s in steps if s['state'] == 'waiting_for_budget' and s['retry_at']]
            failures = [s for s in steps if s['state'] == 'failed']
            state = 'waiting_for_budget' if waits else 'failed' if failures else 'done'
            with transaction(self.db):
                self.db.execute('UPDATE main.job SET state=?, error=?, error_code=?, retry_at=?, updated_at=? WHERE id=?',
                                (state, failures[0]['error'] if failures else None, failures[0]['error_code'] if failures else None,
                                 min(waits) if waits else None, now(), job))
        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            with transaction(self.db):                       # an interrupted job waits for the next pass
                self.db.execute("UPDATE main.job SET state='queued', updated_at=? WHERE id=? AND state='running'", (now(), job))
            raise
        finally:
            if self.db.in_transaction:
                self.db.rollback()
            with transaction(self.db):
                self.db.execute('DELETE FROM main.job_owner WHERE job_id=?', (job,))
            _CLAIMED_JOBS.discard((os.getpid(), str(self.path.resolve()), job))
        return self.status(job)

    def _step(self, job, saved):
        name, sources = saved['name'], json.loads(saved['sources'])
        self._put(job['id'], name, 'running', source=sources[saved['source_index']] if saved['source_index'] < len(sources) else None)
        if name in LOCAL:
            with transaction(self.db):                                   # the step's own writes and its state commit together
                code, message = LOCAL_STEPS[name](self.db, job['item_id'])
                self._put(job['id'], name, 'done', source='catalogue', error=message, code=code, count=1, total=1)
            return
        failed = None                                                   # (failure, source): the most telling provider failure so far
        for index in range(saved['source_index'], len(sources)):
            source = sources[index]
            handler = self.handlers.get((name, source)) or HANDLERS.get((name, source))
            if handler is None:
                continue
            with transaction(self.db):
                self.db.execute('UPDATE main.job_step SET source_index=? WHERE job_id=? AND name=?', (index, job['id'], name))
            try:
                handler(self.db, job, saved)
            except StepDone as finding:
                self._put(job['id'], name, 'done', source=source, error=finding.message, code=finding.code, count=1, total=1)
                return
            except StepWait as wait:
                self._put(job['id'], name, 'waiting_for_budget', source=source, error=wait.why, code='budget', retry_at=wait.retry_at)
                return
            except StepFailed as failure:
                if failed is None or failure.code != 'not_found':       # a source that only cannot name the item never hides a real error
                    failed = (failure, source)
                continue
            self._put(job['id'], name, 'done', source=source, count=1, total=1)
            return
        if failed is not None:                                          # a fallback without a handler does not erase the failure
            failure, source = failed
            self._put(job['id'], name, 'failed', source=source, error=failure.message, code=failure.code)
            return
        self._put(job['id'], name, 'done', error=SKIPPED if sources else 'skipped: no source is set for this step and kind', count=0, total=0)

    def drain(self, limit=100):
        """Run the pipeline jobs that may run now: queued ones, claims that died, and waiting or failed ones whose retry is due."""
        ids = [r[0] for r in self.db.execute('''SELECT id FROM main.job WHERE kind=? AND (state IN ('queued','running')
            OR (state IN ('waiting_for_budget','failed') AND retry_at IS NOT NULL AND retry_at<=?)) ORDER BY id LIMIT ?''',
                                             (KIND, now(), limit))]
        return [self.run(job) for job in cooperative(self.db, ids) if not self.owner_alive(job)]


# ---- the local steps: each returns (error code, message) for a finished step, (None, None) when all is well ----

def _item(db, item_id):
    row = db.execute('SELECT id, kind, born_provider, born_key FROM main.item WHERE id=?', (item_id,)).fetchone()
    if row is None:
        raise ValueError(f'item {item_id} is not in the collection')
    return row


def _identity(db, item_id):
    if _item(db, item_id)['born_key'] is None:
        return 'unidentified', 'The item has no number from any provider'
    return None, None


def _inventory(db, item_id):
    row = _item(db, item_id)
    if row['kind'] not in ('set', 'minifigure'):
        return None, None
    if row['born_key'] is None:
        return 'unidentified', 'The item has no number from any provider, so no part list is known'
    lists = ['SELECT 1 FROM main.fetched_inventory WHERE item_id=:i']
    if has_catalogue(db):
        lists.append('SELECT 1 FROM catalogue.inventory WHERE item_id=:i AND retired_at IS NULL')
    if db.execute(' UNION ALL '.join(lists) + ' LIMIT 1', {'i': item_id}).fetchone():
        return None, None
    return 'not_found', 'No part list is known for this item'


def _matching(db, item_id):
    """The item has a confirmed BrickLink number, or the collection records that none is known (`item_provider_status`, design 3.8) and
    the step ends `unidentified`: prices, exports and order matching skip the item."""
    row = _item(db, item_id)
    try:
        items.bricklink_key(db, item_id)
    except items.Unidentified:
        if row['born_key'] is not None:
            evidence = json.dumps({row['born_provider']: row['born_key']}, sort_keys=True)
            db.execute("""INSERT INTO main.item_provider_status(item_id, provider, status, reason, evidence_json, checked_at)
                          VALUES(?, 'bricklink', 'unmatched', 'no_match', ?, ?)
                          ON CONFLICT(item_id, provider, reason) DO UPDATE SET evidence_json=excluded.evidence_json, checked_at=excluded.checked_at""",
                       (item_id, evidence, now()))
        return 'unidentified', 'The item has no BrickLink number, so prices and exports skip it'
    return None, None


LOCAL_STEPS = {'identity': _identity, 'inventory': _inventory, 'matching': _matching}


# ---- module-level seams the app and the drainer use ----

def database_path(path=None):
    if path is not None:
        return Path(path)
    if os.environ.get('BW_DB_PATH'):
        return Path(os.environ['BW_DB_PATH'])
    from flask import current_app, has_app_context
    if has_app_context():
        configured = current_app.config.get('BRICKWORK_DB_PATH')
        if configured:
            return Path(configured)
    return Path('data/brickwork.db')


def drain(db, limit=100):
    """Run the pipeline jobs that may run now; the results of the jobs this call ran."""
    return Pipeline(db).drain(limit)


def retry(job, step=None, *, path=None, **options):
    with closing(connect(database_path(path))) as db:
        return Pipeline(db, **options).retry(job, step)


def status(job, *, path=None):
    with closing(connect(database_path(path))) as db:
        return Pipeline(db).status(job)


def queue_new_items(db, item_ids):
    """Queue the normal import for items that are new to this store and have no job yet (Add's rule, for imports and sync)."""
    pipeline, queued = Pipeline(db), []
    for item_id in sorted(set(item_ids)):
        if db.execute('SELECT 1 FROM main.job WHERE item_id=? AND kind=? LIMIT 1', (item_id, KIND)).fetchone():
            continue
        queued.append(pipeline.queue_steps(item_id, via='app'))
    return queued
