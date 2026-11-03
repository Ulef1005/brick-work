"""Source calls on the 4.0 store (M.8f, issue #110; design 3.2, 5.2, 6.8): writes on item ids, budgets on `source_budget`.

A source is a client of one provider (`bricklink`, `rebrickable`, `brickset`, `brickognize`). Everything a call needs is in the collection
file: the day's counter, the pause a provider asked for (`blocked_until`) and the time of the last call (`last_attempt_at`) are the row of
`source_budget` for (source, day); the raw reply is a `source_record` under the pipeline job that asked; what a reply says about an item is
written on item ids (`property_value`, `observation`). `store4.jobs` keeps the same rows for the Rebrickable set fetch and the BrickLink
part list, so one daily budget covers both runners.

A call is `Source.request`: refuse when the source is disabled or has no key, count the call against the budget (or raise
`WaitingForBudget` with the time it may run again), make the HTTP request **outside** any write transaction, keep the reply, normalise it
in one savepoint. A reply that the source refuses because of the key is `KeyRejected`; every other failure is a `SourceError` whose text
holds no key material.
"""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPRedirectHandler

from ...store4.audit import value_text  # noqa: F401 (re-exported for the sources that write events)
from ...store4.connect import now as store_now  # noqa: F401
from ...version import __version__
from ..secrets import secret_values
from ..errors import SourceError as DomainSourceError
from ..transaction import transaction

USER_AGENT = f'BrickWork/{__version__} (+self-hosted)'
LOCKS = {}
AUDIT_ORIGIN = ContextVar('brickwork_audit_origin', default='import')
AUDIT_ACTOR = ContextVar('brickwork_audit_actor', default=None)
AUDIT_EXPLICIT = ContextVar('brickwork_audit_explicit', default=False)
CONDITIONS = {'N': 'new', 'U': 'used', 'new': 'new', 'used': 'used', None: None}      # BrickLink letters and words; stored as words (design 5.1)


@contextmanager
def audit_origin(via, actor=None):
    """Keep app-initiated source writes audited as app, including workers."""
    if via not in ('app', 'cli', 'api', 'import', 'migration'):
        raise ValueError('invalid audit origin')
    token = AUDIT_ORIGIN.set(via)
    actor_token = AUDIT_ACTOR.set(actor if via == 'api' else None)
    explicit_token = AUDIT_EXPLICIT.set(True)
    try:
        yield
    finally:
        AUDIT_ORIGIN.reset(token)
        AUDIT_ACTOR.reset(actor_token)
        AUDIT_EXPLICIT.reset(explicit_token)


def now():
    return datetime.now(timezone.utc)


def stamp(moment=None):
    """A UTC instant as the text the 4.0 columns hold (`2026-10-27T08:30:00.123Z`)."""
    moment = moment or now()
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def parse(text):
    """The instant a stored stamp names (the 4.0 `Z` form or an offset form), always timezone-aware."""
    moment = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def redact(value, secrets=None):
    """Mask secret values; callers redacting many strings pass one secret_values() snapshot."""
    text = str(value)
    for secret in (secret_values() if secrets is None else secrets):
        text = text.replace(secret, '[set]')
    return text


class ColourCodeError(ValueError):
    """A fixed, public validation message; never includes source payloads."""

    def __init__(self):
        super().__init__('Invalid BrickLink colour code')


class SourceError(DomainSourceError):
    """A safe, public source failure."""


class KeyRejected(SourceError):
    """The source itself refused the key (an authentication error), not a network or server fault."""


class SourceNotConfigured(SourceError):
    """The source has no usable key; the detail never contains key material."""
    code = 'source_not_configured'


class SourceDisabled(SourceError):
    code = 'source_disabled'


class CatalogueNotLoaded(SourceError):
    code = 'catalogue_not_loaded'


class NotFoundAtSource(SourceError):
    """The provider has no such item (HTTP 404, or an empty answer to a lookup)."""
    code = 'not_found'


class InvalidReply(SourceError):
    """The provider answered, but the answer cannot be used; another try gives the same."""
    code = 'invalid_reply'


class WaitingForBudget(SourceError):
    code = 'budget_exhausted'

    def __init__(self, job_id=None, retry_at=None, throttled=False):
        self.job_id = job_id
        self.retry_at = retry_at
        if throttled:
            self.code = 'source_throttled'
        super().__init__('waiting for budget')

    def retry_after(self):
        """Whole seconds until the budget allows another call, at least one."""
        try:
            wait = (parse(self.retry_at) - now()).total_seconds()
        except (TypeError, ValueError):
            return 60
        return max(1, int(wait) + (wait % 1 > 0))


class RemoteBudgetExceeded(SourceError):
    code = 'source_throttled'

    def __init__(self, retry_seconds=None):
        self.retry_seconds = retry_seconds
        super().__init__('waiting for budget')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Reply(str):
    """Reply text that remembers the HTTP status of an error answer."""
    status = None


def transport(request):
    """Transport seam for tests; return raw text, including HTTP error replies (with their status)."""
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            return response.read().decode('utf-8')
    except HTTPError as error:
        reply = Reply(error.read().decode('utf-8', 'replace'))
        reply.status = error.code
        return reply


def write(db, sql, params=()):
    """Execute a mutation and append its audit event in the caller's transaction (the table is the event's entity)."""
    cursor = db.execute(sql, params)
    table = re.search(r'(?:INTO|UPDATE|FROM)\s+(\w+)', sql, re.IGNORECASE).group(1)
    audit = redact(json.dumps(params, default=str))
    if len(audit) > 4096:
        audit = json.dumps({'sha256': hashlib.sha256(audit.encode()).hexdigest(), 'length': len(audit)})
    from ..admin import audit as record
    record(db, 'source:' + table, sql.split()[0].lower(), new=json.loads(audit), via=AUDIT_ORIGIN.get(), actor=AUDIT_ACTOR.get())
    return cursor


# ---------- what a source writes about an item ----------

def item(db, item_id):
    """The item in the collection (projected from the catalogue when it is not there yet); returns its id.

    Writes inside the caller's transaction. A source never creates an item: an id neither file knows is `NotFound`."""
    from .. import items
    return items.ensure(db, item_id)


def property_value(db, source, item_id, key, value, unit=None):
    """Keep what `source` says about `item_id` under `key` (one row per item, key and source; the newest reply wins)."""
    if value is None:
        return
    db.execute('''INSERT INTO item_property(item_id, key, source, value, unit, fetched_at) VALUES(?, ?, ?, ?, ?, ?)
                  ON CONFLICT(item_id, key, source) DO UPDATE SET value=excluded.value, unit=excluded.unit, fetched_at=excluded.fetched_at''',
               (item_id, key, source, str(value), unit, store_now()))


def observation(db, source, item_id, *, guide, price, currency, color_id=None, condition=None, slot=None, region=None, qty=None,
                sold=None, minimum=None, maximum=None, provider_key=None, observed_at=None, job_id=None, error=None):
    """Record one price observation and make it the current one of its key (item, colour, condition, guide, slot, region, currency).

    `condition` is `new`/`used` (BrickLink's `N`/`U` are accepted); `provider_key` is the provider's own key that was priced
    (BrickLink: `P:3023/1`, type, number and colour number). The observation stays when a newer one replaces it as current."""
    try:
        condition = CONDITIONS[condition]
    except KeyError:
        raise ValueError(f'{condition!r} is not a price condition') from None
    cursor = db.execute('''INSERT INTO price_observation(item_id, color_id, condition, guide, slot, region, currency, price, qty, sold, min, max,
                           source, provider_key, observed_at, error, job_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (item_id, color_id, condition, guide, slot, region, currency, price, qty, sold, minimum, maximum, source,
                         provider_key, observed_at or store_now(), error, job_id))
    observation_id = cursor.lastrowid
    db.execute('''DELETE FROM price_current WHERE item_id=? AND color_key=coalesce(?, 0) AND condition_key=coalesce(?, '') AND guide=?
                  AND slot_key=coalesce(?, '') AND region_key=coalesce(?, '') AND currency_key=coalesce(?, '')''',
               (item_id, color_id, condition, guide, slot, region, currency))
    db.execute('''INSERT INTO price_current(item_id, color_id, condition, guide, slot, region, currency, observation_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?)''',
               (item_id, color_id, condition, guide, slot, region, currency, observation_id))
    return observation_id


# ---------- the day's budget ----------

def day_of(moment=None):
    return (moment or now()).astimezone(timezone.utc).date().isoformat()


def budget_used(db, source, day):
    """The calls counted against `source` on a UTC day."""
    row = db.execute('SELECT used FROM source_budget WHERE source=? AND day=?', (source, day)).fetchone()
    return row[0] if row else 0


def next_midnight(moment=None):
    moment = (moment or now()).astimezone(timezone.utc)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


class Source:
    source = ''
    daily_budget = 0
    minimum_spacing = 0
    credentials = ()

    def __init__(self, db, *, http=None, sleep=None, clock=None):
        self.db = db
        self.http = http or transport
        self.sleep = sleep or (lambda seconds: time.sleep(seconds))       # looked up at call time, so a test's patch applies
        self.clock = clock or (lambda: now())

    label = property(lambda self: self.source.capitalize())

    def configured(self):
        """True when the environment or an encrypted stored key can serve this source."""
        from .. import keys
        return keys.configured(self.db, self.source, self.credentials)

    def credential_values(self):
        """Key values in the order of `credentials`: environment first, then the store."""
        from .. import keys
        return keys.credentials(self.db, self.source, self.credentials, label=self.label)

    def enabled(self):
        if self.db is None:
            return True
        row = self.db.execute('SELECT enabled FROM source WHERE id=?', (self.source,)).fetchone()
        return row is None or bool(row[0])

    def ready(self):
        """Typed refusal before any request is built, reserved or charged."""
        if not self.enabled():
            raise SourceDisabled(self.label + ' is disabled', source=self.source)
        if not self.configured():
            raise SourceNotConfigured(self.label + ' key is not configured', source=self.source)

    # ---- budget ----

    def reserve(self, *, charged=True):
        """Count one call, or raise `WaitingForBudget` when the day's budget is used or the source asked for a pause.

        The write lock covers the budget, the pause, the spacing and the count together, so two processes never spend the same call or
        send together. When the spacing has not passed, the lock is let go, the wait is slept, and the check starts again."""
        while True:
            moment = self.clock()
            day, text = day_of(moment), stamp(moment)
            delay = 0
            with transaction(self.db):
                used = budget_used(self.db, self.source, day)
                until = self.db.execute('SELECT max(blocked_until) FROM source_budget WHERE source=?', (self.source,)).fetchone()[0]
                rate_wait = bool(until) and until > text
                daily_wait = charged and used >= self.daily_budget
                if daily_wait or rate_wait:
                    deadlines = ([stamp(next_midnight(moment))] if daily_wait else []) + ([until] if rate_wait else [])
                    raise WaitingForBudget(None, max(deadlines), throttled=rate_wait and not daily_wait)
                last = self.db.execute('SELECT max(last_attempt_at) FROM source_budget WHERE source=?', (self.source,)).fetchone()[0] if self.minimum_spacing else None
                if last:
                    delay = self.minimum_spacing - (moment - parse(last)).total_seconds()
                if delay <= 0:
                    self.db.execute('INSERT OR IGNORE INTO source_budget(source, day) VALUES(?, ?)', (self.source, day))
                    self.db.execute('UPDATE source_budget SET used=used+?, last_attempt_at=? WHERE source=? AND day=?',
                                    (int(charged), text, self.source, day))
                    return
            self.sleep(delay)

    def block(self, retry_seconds=None):
        """The source said no more for now: for `retry_seconds`, else until the next UTC midnight. Returns the retry stamp."""
        moment = self.clock()
        until = stamp(moment + timedelta(seconds=retry_seconds)) if retry_seconds is not None else stamp(next_midnight(moment))
        self.db.execute('INSERT OR IGNORE INTO source_budget(source, day) VALUES(?, ?)', (self.source, day_of(moment)))
        # max(): a shorter pause from an overlapping call never cuts a longer one short
        self.db.execute('UPDATE source_budget SET blocked=1, blocked_until=max(coalesce(blocked_until, ?), ?) WHERE source=? AND day=?',
                        (until, until, self.source, day_of(moment)))
        return until

    # ---- calls ----

    def request(self, kind, key, request, normalize, *, charged=True, job_id=None):
        """One budgeted call; returns what `normalize(parsed reply)` returns (it writes in one savepoint, with the reply kept)."""
        if not request.has_header('User-agent'):
            request.add_header('User-Agent', USER_AGENT)
        with LOCKS.setdefault(self.source, threading.RLock()):
            return self._request(kind, key, request, normalize, charged=charged, job_id=job_id)

    def _request(self, kind, key, request, normalize, *, charged, job_id):
        self.ready()
        self.reserve(charged=charged)
        try:
            raw = self.http(request)
        except Exception:
            raise SourceError(self.source + ' could not be reached') from None
        text = redact(raw if isinstance(raw, str) else json.dumps(raw))
        status = getattr(raw, 'status', None)
        error = result = None
        with transaction(self.db):
            record = self.db.execute('''INSERT INTO source_record(source, kind, key, payload, digest, bytes, job_id, fetched_at, status)
                                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'received')
                                        ON CONFLICT(source, kind, key, digest) DO UPDATE SET job_id=excluded.job_id,
                                        fetched_at=excluded.fetched_at, status='received' RETURNING id''',
                                     (self.source, kind, str(key), text, hashlib.sha256(text.encode()).hexdigest(), len(text.encode()), job_id,
                                      store_now())).fetchone()[0]
            self.db.execute('SAVEPOINT normalized')
            try:
                value = json.loads(text)
                # A 401 or 403 carrying the source's own JSON error is the source refusing the key.
                # An HTML or empty answer (proxy, WAF) says nothing about the key and stays a plain failure.
                if status in (401, 403) and self.credentials and isinstance(value, dict) and self.key_refused(value):
                    raise KeyRejected(self.label + ' API unsuccessful')
                result = normalize(value)
            except RemoteBudgetExceeded as exhausted:
                self.db.execute('ROLLBACK TO normalized')
                until = self.block(exhausted.retry_seconds)
                error = WaitingForBudget(None, until, throttled=exhausted.retry_seconds is not None)
            except (ColourCodeError, NotFoundAtSource, InvalidReply) as failure:
                self.db.execute('ROLLBACK TO normalized')
                error = failure
            except SourceError as failure:
                self.db.execute('ROLLBACK TO normalized')
                error = (KeyRejected if isinstance(failure, KeyRejected) else SourceError)(redact(failure))
            except Exception:
                self.db.execute('ROLLBACK TO normalized')
                error = InvalidReply(self.source + ' returned an invalid or unsuccessful reply')
            finally:
                self.db.execute('RELEASE normalized')
            self.db.execute('UPDATE source_record SET status=? WHERE id=?', ('failed' if error else 'success', record))
        if error:
            raise error
        return result

    def key_refused(self, reply):
        """True when an error reply (already parsed) means the key itself was refused."""
        return True

    def status_key(self):
        from .. import keys
        return keys.state(self.db, self.source, self.credentials)

    def status(self):
        used = budget_used(self.db, self.source, day_of())
        success = self.db.execute("SELECT max(fetched_at) FROM source_record WHERE source=? AND status='success'", (self.source,)).fetchone()[0]
        state = self.status_key()
        return dict(key='set' if state['configured'] else 'unset', key_state=state, budget=self.daily_budget,
                    used_today=used, last_success=success)


def record_change(db, entity, old, new):
    """Retain before/after snapshots for source-owned display data."""
    from ..admin import audit
    audit(db, entity, 'source_record', old, new, via=AUDIT_ORIGIN.get(), actor=AUDIT_ACTOR.get())
