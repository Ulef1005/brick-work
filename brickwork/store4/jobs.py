"""A small durable job runner for the two fetch kinds (design 4.3 decision F, 5.2, 6.5; issue #107, M.5d).

Jobs live in the collection's `job` / `job_step` / `job_owner` / `source_budget` tables and survive a restart. Two kinds:

- `bricklink_subsets` (source `bricklink`, item = the set, payload = the requested number): one signed call, then
  `bricklink_subsets.load_subsets`.
- `rebrickable_set` (source `rebrickable`, item = a local set already fetched once, else none; payload = the set number):
  `rebrickable_api.fetch_set_replies` (3 + n calls), then `load_rebrickable_set`.

A run claims the job through `job_owner`, makes every call **outside** any write transaction (each call is counted in its own
short transaction, so `source_budget` and the step's `count` follow the network), then loads the result and marks the job done
in **one** write transaction: a job is `done` exactly when its list is stored, and a cut-off or failed fetch writes nothing.

Policy (decisions the design leaves open, all in the tests):

- Budget: the day is the UTC day. A job starts only when today's remaining calls cover its minimum (1 for BrickLink, 3 for a
  Rebrickable set); each further call is checked again. Out of budget -> `waiting_for_budget`, `error_code='budget'`, `retry_at`
  = the next UTC midnight; a Rebrickable fetch cut off after n calls keeps them counted and starts over at the next run.
  HTTP 429 -> `waiting_for_budget` too, `retry_at` = the time the reply names (else 60 s), also recorded as the source's
  `blocked_until`, so no other job of the source calls before it.
- Errors end `failed` with the design's codes: no key or a refused key (401/403, a BrickLink IP mismatch) -> `source_not_configured`;
  404 -> `not_found`; an invalid reply or a list the store refuses -> `invalid_reply`; no BrickLink key for the set ->
  `unidentified`; network, 5xx and other HTTP failures -> `source_error`, retried: `failed` with a `retry_at`, which `drain`
  picks up, at most MAX_ATTEMPTS runs, 1, 5, 15 and 60 minutes apart; the last failure keeps `failed` with no `retry_at`.
  Only a transient failure has a `retry_at`; every other `failed` job is final (a new `queue` makes a new job).
- A dead owner's claim is taken over (the pid is gone, or it is this pid in a process that does not hold the job)."""
from datetime import datetime, timedelta, timezone
import json
import os
import re

from . import bricklink_api, bricklink_subsets, identity, keys, rebrickable_api
from .audit import Events, transaction
from .errors import Store4Error
from .fetched import InventoryError
from .rebrickable_api import FetchError, InvalidReply, KeyRefused, NotFound, SetInCatalogue, Throttled, UrllibHttp

KINDS = {'bricklink_subsets': 'bricklink', 'rebrickable_set': 'rebrickable'}
STEP = 'fetch'
MINIMUM_CALLS = {'bricklink_subsets': 1, 'rebrickable_set': 3}         # a Rebrickable set is 3 + n; n is known only after the minifigs call
BUDGET = {'bricklink': ('BW_BRICKLINK_DAILY_BUDGET', 4400), 'rebrickable': ('BW_REBRICKABLE_DAILY_BUDGET', 1000)}   # as 3.3
MAX_ATTEMPTS = 5
RETRY_MINUTES = (1, 5, 15, 60)                                          # after attempt 1, 2, 3, 4
NUMBER = re.compile('[A-Za-z0-9-]{1,64}')
OWN_KINDS = '(' + ', '.join(f"'{k}'" for k in KINDS) + ')'              # SQL list of the kinds this module runs; any other job is not its own
ACTIVE = "(state IN ('queued','running','waiting_for_budget') OR (state='failed' AND retry_at IS NOT NULL))"

_CLAIMED = set()                                                        # (pid, collection path, job) this process is working on
_DEFAULT_HTTP = {}                                                      # one transport per source: its spacing lasts across jobs


class ForeignKind(Store4Error):
    """The job is of a kind this module does not run (the app's pipeline jobs share the `job` table)."""


class BudgetWait(Store4Error):
    """Raised between two calls: the day's budget or the source's rate wait stops the fetch here."""

    def __init__(self, retry_at, why):
        super().__init__(why)
        self.retry_at, self.why = retry_at, why


# ---------- time ----------

def _now(now):
    t = now() if callable(now) else now
    t = t if t is not None else datetime.now(timezone.utc)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _stamp(t):
    return t.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def _day(t):
    return t.astimezone(timezone.utc).date().isoformat()


def _midnight(t):
    return t.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


# ---------- queue ----------

def _check_number(number):
    if not isinstance(number, str) or not NUMBER.fullmatch(number):
        raise Store4Error(f'{number!r} is not a set number')
    return number


def in_catalogue(db, number):
    """The catalogue (or the collection, as a catalogue item) holds this Rebrickable set: its own list is used, nothing is fetched."""
    return rebrickable_api._catalogue_item(db, 'sets', number) is not None or db.execute(
        "SELECT 1 FROM main.item WHERE origin='catalogue' AND born_provider='rebrickable' AND born_namespace='sets' AND born_key=?",
        (number,)).fetchone() is not None


def queue(db, kind, *, item_id=None, payload, via, actor=None, now=None):
    """Queue a fetch job and return its id; while one for the same item (else the same number) is queued, running, waiting or
    waiting for a retry, that job's id is returned instead."""
    with transaction(db, 'queueing a job'):
        return queue_in(db, kind, item_id=item_id, payload=payload, via=via, actor=actor, now=now)[0]


def queue_in(db, kind, *, item_id=None, payload, via, actor=None, now=None):
    """`queue` inside the caller's open write transaction (M.6c: a copy and its pending job commit or roll back together).
    Returns `(job id, created)`; `created` is False when an open job for the same item was returned instead."""
    if kind not in KINDS:
        raise Store4Error(f'unknown job kind {kind!r}')
    number = _check_number(payload)
    if not db.in_transaction:
        raise Store4Error('queue_in needs the caller\'s open write transaction; use queue()')
    t = _now(now)
    if kind == 'bricklink_subsets':
        if item_id is None:
            raise Store4Error('a BrickLink subsets job needs the set item')
        identity.project(db, item_id)                                   # a catalogue set joins the collection; the job names it
    elif item_id is None and in_catalogue(db, number):
        raise SetInCatalogue(f'the catalogue already has set {number}; use the catalogue\'s part list instead of fetching one')
    if item_id is not None:
        row = db.execute('SELECT kind FROM main.item WHERE id=?', (item_id,)).fetchone()
        if row is None or row['kind'] != 'set':
            raise Store4Error(f'item {item_id} is not a set in the collection')
    where, args = ('item_id=?', (item_id,)) if item_id is not None else ('item_id IS NULL AND payload=?', (json.dumps({'number': number}),))
    found = db.execute(f'SELECT id FROM job WHERE kind=? AND {ACTIVE} AND {where} ORDER BY id', (kind, *args)).fetchone()
    if found:
        return found[0], False
    source, stamp = KINDS[kind], _stamp(t)
    job = db.execute('''INSERT INTO job(source, kind, item_id, state, payload, via, actor, created_at, updated_at)
                        VALUES(?, ?, ?, 'queued', ?, ?, ?, ?, ?)''',
                     (source, kind, item_id, json.dumps({'number': number}), via, actor, stamp, stamp)).lastrowid
    db.execute('''INSERT INTO job_step(job_id, name, position, sources, source, total, updated_at) VALUES(?, ?, 0, ?, ?, ?, ?)''',
               (job, STEP, json.dumps([source]), source, MINIMUM_CALLS[kind], stamp))
    Events(db, via, actor).write('job', job, 'created', new={'kind': kind, 'item_id': item_id, 'number': number})
    return job, True


# ---------- reading ----------

def _row(db, job_id):
    row = db.execute('SELECT * FROM job WHERE id=?', (job_id,)).fetchone()
    if row is None:
        raise Store4Error(f'no job {job_id}')
    return row


def status(db, job_id):
    """The job and its step as plain dicts (`number` unpacked from the payload)."""
    job = dict(_row(db, job_id))
    job['number'] = (json.loads(job['payload'] or '{}') or {}).get('number')       # a foreign job's payload has its own shape
    step = db.execute('SELECT * FROM job_step WHERE job_id=? AND name=?', (job_id, STEP)).fetchone()
    job['step'] = dict(step) if step else None
    return job


def list_jobs(db, *, states=None):
    rows = db.execute('SELECT id FROM job ORDER BY id').fetchall()
    jobs = [status(db, r[0]) for r in rows]
    return [j for j in jobs if states is None or j['state'] in states]


# ---------- budget ----------

def daily_budget(source):
    name, default = BUDGET[source]
    value = os.environ.get(name, str(default))
    if not re.fullmatch('[0-9]+', value) or int(value) <= 0:
        raise Store4Error(f'{name} must be a positive integer')
    return int(value)


def _used(db, source, day):
    row = db.execute('SELECT used FROM source_budget WHERE source=? AND day=?', (source, day)).fetchone()
    return row[0] if row else 0


def _wait_until(db, source, t, need):
    """None when `need` more calls may start now, else (retry_at, why): the next midnight when the day is used up, the source's
    `blocked_until` while a rate wait lasts, the later of the two when both apply."""
    limit, used, stamp = daily_budget(source), _used(db, source, _day(t)), _stamp(t)
    deadlines, why = [], []
    if used + need > limit:
        deadlines.append(_stamp(_midnight(t)))
        why.append(f'{source} budget: {used} of {limit} calls used today, {need} needed')
    blocked = db.execute('SELECT max(blocked_until) FROM source_budget WHERE source=?', (source,)).fetchone()[0]
    if blocked and blocked > stamp:
        deadlines.append(blocked)
        why.append(f'{source} asked for a pause until {blocked}')
    return (max(deadlines), '; '.join(why)) if deadlines else None


class _Calls:
    """The `http` the fetchers get: every call is checked against the budget and counted before it goes out, in its own short
    transaction, so the network never runs inside a write transaction."""

    def __init__(self, db, job, http, now):
        self.db, self.job, self.http, self.now = db, job, http, now
        self.made = 0

    def __call__(self, url, headers):
        source, t = self.job['source'], _now(self.now)
        stamp, day = _stamp(t), _day(t)
        with transaction(self.db, 'counting a call'):
            wait = _wait_until(self.db, source, t, 1)
            if wait:
                raise BudgetWait(*wait)
            self.db.execute('INSERT OR IGNORE INTO source_budget(source, day) VALUES(?, ?)', (source, day))
            self.db.execute('UPDATE source_budget SET used=used+1, last_attempt_at=? WHERE source=? AND day=?', (stamp, source, day))
            self.db.execute('UPDATE job_step SET count=count+1, total=max(total, count+1), updated_at=? WHERE job_id=? AND name=?',
                            (stamp, self.job['id'], STEP))
            self.db.execute('UPDATE job SET budget_day=?, budget_used=budget_used+1, updated_at=? WHERE id=?', (day, stamp, self.job['id']))
        self.made += 1
        return self.http(url, headers)


# ---------- claim and settle ----------

def _path(db):
    return next(r[2] for r in db.execute('PRAGMA database_list') if r[1] == 'main')


def _alive(db, pid, job_id):
    if pid == os.getpid():
        return (pid, _path(db), job_id) in _CLAIMED
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _safe(text):
    """An error text with every configured key value masked; messages are static, this is the belt for the braces."""
    text = str(text)
    for name in (*bricklink_api.KEY_ENVS, rebrickable_api.KEY_ENV):
        value = keys.get(name)
        if value:
            text = text.replace(value, '[set]')
    return text


def _put(db, job_id, state, t, *, code=None, error=None, retry_at=None, attempts=None):
    """Write job and step to one state (inside the caller's transaction) and drop the claim."""
    stamp = _stamp(t)
    db.execute('UPDATE job SET state=?, error_code=?, error=?, retry_at=?, attempts=coalesce(?, attempts), updated_at=? WHERE id=?',
               (state, code, error, retry_at, attempts, stamp, job_id))
    db.execute('UPDATE job_step SET state=?, error_code=?, error=?, retry_at=?, updated_at=? WHERE job_id=? AND name=?',
               (state, code, error, retry_at, stamp, job_id, STEP))
    db.execute('DELETE FROM job_owner WHERE job_id=?', (job_id,))


def _claim(db, job_id, now):
    """Take the job if it may run now; returns its row, or None (not runnable, owned, finished in this call, or waiting)."""
    t = _now(now)
    stamp = _stamp(t)
    with transaction(db, 'claiming a job'):
        job = _row(db, job_id)
        if job['kind'] not in KINDS:
            raise ForeignKind(f'job {job_id} is a {job["kind"]!r} job; store4.jobs runs only {", ".join(KINDS)}')
        due = job['retry_at'] is not None and job['retry_at'] <= stamp
        if not (job['state'] in ('queued', 'running') or job['state'] in ('waiting_for_budget', 'failed') and due):
            return None
        owner = db.execute('SELECT pid FROM job_owner WHERE job_id=?', (job_id,)).fetchone()
        if owner and _alive(db, owner[0], job_id):
            return None
        source, kind = job['source'], job['kind']
        if not _configured(source):
            _put(db, job_id, 'failed', t, code='source_not_configured', error=f'the {source} key is not configured', attempts=job['attempts'] + 1)
            return None
        if kind == 'bricklink_subsets' and _bricklink_number(db, job) is None:
            _put(db, job_id, 'failed', t, code='unidentified', attempts=job['attempts'] + 1,
                 error='the set has no BrickLink number, so its BrickLink list cannot be fetched')
            return None
        if kind == 'rebrickable_set' and in_catalogue(db, json.loads(job['payload'])['number']):
            _put(db, job_id, 'failed', t, code='invalid_reply', attempts=job['attempts'] + 1,
                 error='the catalogue has this set now; use its own part list')
            return None
        wait = _wait_until(db, source, t, MINIMUM_CALLS[kind])
        if wait:
            _put(db, job_id, 'waiting_for_budget', t, code='budget', error=wait[1], retry_at=wait[0])
            return None
        db.execute('INSERT OR REPLACE INTO job_owner(job_id, pid, claimed_at) VALUES(?, ?, ?)', (job_id, os.getpid(), stamp))
        db.execute('''UPDATE job SET state='running', attempts=attempts+1, budget_day=?, budget_used=0, retry_at=NULL, error=NULL,
                      error_code=NULL, updated_at=? WHERE id=?''', (_day(t), stamp, job_id))
        db.execute('''UPDATE job_step SET state='running', count=0, error=NULL, error_code=NULL, retry_at=NULL, updated_at=?
                      WHERE job_id=? AND name=?''', (stamp, job_id, STEP))
        _CLAIMED.add((os.getpid(), _path(db), job_id))
        return _row(db, job_id)


def _configured(source):
    return bricklink_api.key_configured() if source == 'bricklink' else bool(keys.get(rebrickable_api.KEY_ENV))


def _bricklink_number(db, job):
    """The set's BrickLink set number, from the collection's links (design 3.2); None when it has none."""
    link = identity.resolve(db, job['item_id'], None)
    return link[1] if link and link[0] == 'S' else None


def _transport(source, http):
    if http is not None:
        return http
    return _DEFAULT_HTTP.setdefault(source, UrllibHttp())


# ---------- run ----------

def run(db, job_id, *, http=None, now=None):
    """Run one job if it may run now; returns `status()` plus `ran` (this call ran it) and `result` (the loader's summary, when the
    run stored a list). The job's state tells the outcome: `done`, `waiting_for_budget` (see `retry_at`), `failed`."""
    job = _claim(db, job_id, now)
    if job is None:
        return _settled(db, {**status(db, job_id), 'ran': False, 'result': None})
    source, number = job['source'], json.loads(job['payload'])['number']
    calls = _Calls(db, job, _transport(source, http), now)
    result = None
    try:
        try:
            if job['kind'] == 'bricklink_subsets':
                bl_number = _bricklink_number(db, job)                  # once: the reply is stored under the number it was asked for
                reply = bricklink_api.fetch_subsets(bl_number, http=calls)
            else:
                replies = rebrickable_api.fetch_set_replies(number, http=calls, headers=rebrickable_api._headers(),
                                                            catalogue_has_figure=rebrickable_api.catalogue_figure_check(db))
            events = Events(db, job['via'], job['actor'])
            with transaction(db, 'loading a fetched list'):
                if job['kind'] == 'bricklink_subsets':
                    if _bricklink_number(db, job) != bl_number:         # the set's link changed while the call was out: ask again
                        raise FetchError(f'the set\'s BrickLink number changed from {bl_number} during the fetch')
                    result = bricklink_subsets.load_subsets(db, job['item_id'], bl_number, reply, job_id=job_id, events=events)
                else:
                    result = rebrickable_api.load_rebrickable_set(db, number, replies, job_id=job_id, events=events)
                db.execute('UPDATE job_step SET count=?, total=?, updated_at=? WHERE job_id=? AND name=?',
                           (calls.made, max(calls.made, 1), _stamp(_now(now)), job_id, STEP))
                if job['kind'] == 'rebrickable_set':                    # the job now names the set it made, as a BrickLink job names its own
                    db.execute('UPDATE job SET item_id=? WHERE id=?', (result.set_item_id, job_id))
                _put(db, job_id, 'done', _now(now))
        except BudgetWait as wait:
            _settle(db, job_id, now, 'waiting_for_budget', 'budget', _safe(wait.why), wait.retry_at)
        except Throttled as throttled:
            t = _now(now)
            until = _stamp(t + timedelta(seconds=throttled.retry_seconds))
            with transaction(db, 'recording a throttle'):
                db.execute('INSERT OR IGNORE INTO source_budget(source, day) VALUES(?, ?)', (source, _day(t)))
                # max(): a shorter pause from an overlapping call never cuts a longer one short
                db.execute('UPDATE source_budget SET blocked=1, blocked_until=max(coalesce(blocked_until, ?), ?) WHERE source=? AND day=?',
                           (until, until, source, _day(t)))
                _put(db, job_id, 'waiting_for_budget', t, code='budget', retry_at=until,
                     error=f'{source} throttled the call; waiting {throttled.retry_seconds} s')
        except NotFound as exc:
            _settle(db, job_id, now, 'failed', 'not_found', _safe(exc))
        except KeyRefused as exc:
            _settle(db, job_id, now, 'failed', 'source_not_configured', _safe(exc))
        except InvalidReply as exc:                                     # a 200 the fetch cannot use: another try costs budget for nothing
            _settle(db, job_id, now, 'failed', 'invalid_reply', _safe(exc))
        except FetchError as exc:                                       # network, 5xx, other HTTP: worth another try
            _transient(db, job_id, now, _safe(exc))
        except (InventoryError, SetInCatalogue, Store4Error) as exc:    # a reply the store refuses: another try gives the same
            _settle(db, job_id, now, 'failed', 'invalid_reply', _safe(exc))
    except BaseException as exc:                                        # a bug or an interrupt: never leave a claim behind
        if db.in_transaction:
            db.rollback()
        if isinstance(exc, Exception) and _row(db, job_id)['state'] == 'running':
            _settle(db, job_id, now, 'failed', 'source_error', _safe(f'internal error: {exc.__class__.__name__}'))
        else:                                                           # an interrupt: the job stays `running`, a later run takes it over
            with transaction(db, 'releasing a claim'):
                db.execute('DELETE FROM job_owner WHERE job_id=?', (job_id,))
        raise
    finally:
        _CLAIMED.discard((os.getpid(), _path(db), job_id))
    return _settled(db, {**status(db, job_id), 'ran': True, 'result': result.as_dict() if result else None})


def _settled(db, out):
    """Copies waiting for a finished BrickLink job are settled now (M.6c): switched when unmarked, offered when marked, released
    when the job failed for good. Adds `settled` (one entry per copy) to the run's result when there was any. The import is
    here because `pending` imports this module."""
    from . import pending
    settled = pending.settle_pending(db, out['id'], via=out['via'], actor=out['actor'])
    return {**out, 'settled': settled} if settled else out


LEFTOVERS = (f"FROM main.copy c JOIN main.job j ON j.id=c.pending_job_id WHERE c.inventory_pending='bricklink' "
             f"AND j.kind IN {OWN_KINDS} AND (j.state='done' OR (j.state='failed' AND j.retry_at IS NULL))")


def _settle_leftovers(db):
    """Copies still pending on a job that already finished (the process stopped between the job's commit and `_settled`) are
    settled before `drain` looks for new work, since a finished job is never run again."""
    from . import pending
    for row in db.execute(f'SELECT DISTINCT j.id, j.via, j.actor {LEFTOVERS} ORDER BY j.id').fetchall():
        pending.settle_pending(db, row['id'], via=row['via'], actor=row['actor'])


def has_leftovers(db):
    """Copies wait on a job that already finished: `drain` settles them first, so a start-up must run it even with no active job."""
    return db.execute(f'SELECT 1 {LEFTOVERS} LIMIT 1').fetchone() is not None


def _settle(db, job_id, now, state, code, error, retry_at=None):
    with transaction(db, 'settling a job'):
        _put(db, job_id, state, _now(now), code=code, error=error, retry_at=retry_at)


def _transient(db, job_id, now, error):
    t = _now(now)
    with transaction(db, 'settling a job'):
        attempts = _row(db, job_id)['attempts']
        if attempts >= MAX_ATTEMPTS:
            _put(db, job_id, 'failed', t, code='source_error', error=f'{error} (gave up after {attempts} attempts)')
        else:
            _put(db, job_id, 'failed', t, code='source_error', error=error, retry_at=_stamp(t + timedelta(minutes=RETRY_MINUTES[attempts - 1])))


def drain(db, *, limit=100, now=None, http=None):
    """Run the jobs that may run now, oldest first: queued ones, those whose claim died, waiting ones whose `retry_at` has passed and
    failed ones whose retry is due; at most `limit` are looked at. Returns the `run()` results of the jobs this call ran.
    Only the kinds in `KINDS` are looked at: other jobs in the table (the app's pipeline) are left untouched."""
    _settle_leftovers(db)
    stamp = _stamp(_now(now))
    ids = [r[0] for r in db.execute(f'''SELECT id FROM job WHERE kind IN {OWN_KINDS} AND (state IN ('queued','running')
                                       OR (state IN ('waiting_for_budget','failed') AND retry_at IS NOT NULL AND retry_at<=?))
                                       ORDER BY id LIMIT ?''', (stamp, limit))]
    results = [run(db, i, http=http, now=now) for i in ids]
    return [r for r in results if r['ran']]
