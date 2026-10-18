"""Source writes, durable UTC reservations and credential-safe transport errors.

No source-specific schema: jobs hold work, settings hold UTC counters and pacing, and
source_records retain each reply under its job id rather than overwriting it.
"""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPRedirectHandler

from ...version import __version__
from ..secrets import secret_values
from ..errors import SourceError as DomainSourceError

USER_AGENT = f'BrickWork/{__version__} (+self-hosted)'
LOCKS = {}
AUDIT_ORIGIN = ContextVar('brickwork_audit_origin', default='import')
AUDIT_ACTOR = ContextVar('brickwork_audit_actor', default=None)
AUDIT_EXPLICIT = ContextVar('brickwork_audit_explicit', default=False)


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


class WaitingForBudget(SourceError):
    code = 'budget_exhausted'
    def __init__(self, job_id, retry_at=None, throttled=False):
        self.job_id = job_id
        self.retry_at = retry_at
        if throttled:
            self.code = 'source_throttled'
        super().__init__('waiting for budget')

    def retry_after(self):
        """Whole seconds until the budget allows another call, at least one."""
        try:
            wait = (datetime.fromisoformat(self.retry_at) - now()).total_seconds()
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
        reply = Reply(error.read().decode('utf-8'))
        reply.status = error.code
        return reply


def write(db, sql, params=()):
    """Execute a mutation and append its audit event in the caller's transaction."""
    cursor = db.execute(sql, params)
    table = re.search(r'(?:INTO|UPDATE|FROM)\s+(\w+)', sql, re.IGNORECASE).group(1)
    audit = redact(json.dumps(params, default=str))
    if len(audit) > 4096:
        audit = json.dumps({'sha256': hashlib.sha256(audit.encode()).hexdigest(),
                            'length': len(audit)})
    from ..admin import audit as record
    record(db, 'source:' + table, sql.split()[0].lower(), new=json.loads(audit), via=AUDIT_ORIGIN.get(), actor=AUDIT_ACTOR.get())
    return cursor


def item(db, kind, number, name=None):
    write(db, '''INSERT INTO items(item_type,item_no,name,updated_at) VALUES(?,?,?,?)
        ON CONFLICT(item_type,item_no) DO UPDATE SET name=coalesce(excluded.name,items.name),
        updated_at=excluded.updated_at''', (kind, number, name, now().isoformat()))


def property_value(db, source, kind, number, key, value):
    if value is not None:
        write(db, '''INSERT INTO item_properties VALUES(?,?,?,?,?,NULL,?)
            ON CONFLICT(item_type,item_no,key,source) DO UPDATE SET
            value=excluded.value,fetched_at=excluded.fetched_at''',
              (kind, number, key, source, str(value), now().isoformat()))


def observation(db, source, kind, number, *, guide, price, currency, color=None,
                condition=None, slot=None, region=None, qty=None, sold=None, minimum=None, maximum=None, observed_at=None):
    if color is not None:
        write(db, 'INSERT OR IGNORE INTO colors(color_id) VALUES(?)', (color,))
    key = (kind, number, color, condition, guide, slot, region, currency)
    cursor = write(db, '''INSERT INTO price_observations(item_type,item_no,color_id,condition,
        guide,slot,region,currency,price,qty,sold,min,max,source,observed_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (*key, price, qty, sold, minimum, maximum, source, observed_at or now().isoformat()))
    write(db, '''DELETE FROM price_current WHERE item_type=? AND item_no=? AND color_id IS ?
        AND condition IS ? AND guide=? AND slot IS ? AND region IS ? AND currency IS ?''', key)
    write(db, 'INSERT INTO price_current VALUES(?,?,?,?,?,?,?,?,?)', (*key, cursor.lastrowid))


def budget_used(db, source, day):
    stored = db.execute('SELECT value FROM settings WHERE key=?',
                        ('source:used:' + source + ':' + day,)).fetchone()
    if stored:
        value = int(stored[0])
        if value < 0:
            raise SourceError('invalid source budget state')
        return value
    return db.execute('SELECT coalesce(sum(budget_used),0) FROM jobs WHERE source=? AND budget_day=?',
                      (source, day)).fetchone()[0]


class Source:
    source = ''
    daily_budget = 0
    minimum_spacing = 0
    freshness = {}
    credentials = ()
    source_kind = 'api'

    def __init__(self, db, *, http=None):
        self.db = db
        self.http = http or transport

    label = property(lambda self: self.source.capitalize())

    def configured(self):
        """True when the environment or an encrypted stored key can serve this source."""
        from .. import keys
        return keys.configured(self.db, self.source, self.credentials)

    def credential_values(self):
        """Key values in the order of `credentials`: environment first, then the store."""
        from .. import keys
        return keys.credentials(self.db, self.source, self.credentials, label=self.label)

    def ready(self):
        """Typed refusal before any request is built, reserved or charged."""
        if not self.enabled():
            raise SourceDisabled(self.label + ' is disabled', source=self.source)
        if not self.configured():
            raise SourceNotConfigured(self.label + ' key is not configured', source=self.source)

    def enabled(self):
        if self.db is None:
            return True
        row = self.db.execute('SELECT enabled FROM sources WHERE source=?', (self.source,)).fetchone()
        return row is None or bool(row[0])

    def register(self):
        write(self.db, 'INSERT OR IGNORE INTO sources(source,name,kind) VALUES(?,?,?)',
              (self.source, self.source, self.source_kind))
        write(self.db, 'INSERT OR REPLACE INTO settings VALUES(?,?)',
              ('source:budget:' + self.source, str(self.daily_budget)))
        for kind, days in self.freshness.items():
            write(self.db, 'INSERT OR IGNORE INTO source_freshness VALUES(?,?,?)',
                  (self.source, kind, days))

    def reserve(self, kind, payload, *, charged=True, job_id=None):
        # The database lock serializes reservations and pacing across processes.
        waiting = False
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.register()
            pacing_key = 'source:last_attempt:' + self.source
            last = self.db.execute('SELECT value FROM settings WHERE key=?', (pacing_key,)).fetchone()
            if last:
                delay = self.minimum_spacing - (now() - datetime.fromisoformat(last[0])).total_seconds()
                if delay > 0:
                    time.sleep(delay)
            timestamp = now()
            day = timestamp.date().isoformat()
            used = budget_used(self.db, self.source, day)
            blocked = self.db.execute('SELECT value FROM settings WHERE key=?',
                                      ('source:blocked_day:' + self.source,)).fetchone()
            until = self.db.execute('SELECT value FROM settings WHERE key=?',
                                    ('source:blocked_until:' + self.source,)).fetchone()
            rate_wait = until is not None and datetime.fromisoformat(until[0]) > timestamp
            daily_wait = charged and (used >= self.daily_budget or blocked and blocked[0] == day)
            waiting = bool(daily_wait or rate_wait)
            throttled = bool(rate_wait and not daily_wait)
            midnight = (timestamp.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
            deadlines = ([midnight] if daily_wait else []) + ([until[0]] if rate_wait else [])
            retry_at = max(deadlines) if deadlines else None
            if job_id is None:
                job_id = write(self.db, '''INSERT INTO jobs(source,kind,state,payload,created_at,updated_at)
                    VALUES(?,?,?,?,?,?)''', (self.source, kind, 'queued', json.dumps(payload),
                                           timestamp.isoformat(), timestamp.isoformat())).lastrowid
            else:
                job = self.db.execute('SELECT source,state,kind,payload FROM jobs WHERE id=?', (job_id,)).fetchone()
                if (not job or job['source'] != self.source or job['state'] != 'waiting_for_budget'
                        or job['kind'] != kind or job['payload'] != json.dumps(payload)):
                    raise SourceError('job cannot be resumed')
            write(self.db, '''UPDATE jobs SET state=?,attempts=attempts+?,budget_day=?,budget_used=?,
                retry_at=?,error=NULL,updated_at=? WHERE id=?''',
                ('waiting_for_budget' if waiting else 'running', 0 if waiting else 1, day,
                 0 if waiting else int(charged),
                 retry_at, timestamp.isoformat(), job_id))
            if not waiting:
                if charged:
                    write(self.db, 'INSERT OR REPLACE INTO settings VALUES(?,?)',
                          ('source:used:' + self.source + ':' + day, str(used + 1)))
                write(self.db, 'INSERT OR REPLACE INTO settings VALUES(?,?)', (pacing_key, timestamp.isoformat()))
        if waiting:
            raise WaitingForBudget(job_id, retry_at, throttled)
        return job_id

    def request(self, kind, payload, request, normalize, *, charged=True, job_id=None):
        # Keep the Web API's in-process serialization, with durable pacing
        # additionally covering other processes and restarts.
        if not request.has_header('User-agent'):
            request.add_header('User-Agent', USER_AGENT)
        with LOCKS.setdefault(self.source, threading.RLock()):
            return self._request(kind, payload, request, normalize, charged=charged, job_id=job_id)

    def _request(self, kind, payload, request, normalize, *, charged=True, job_id=None):
        self.ready()
        job_id = self.reserve(kind, payload, charged=charged, job_id=job_id)
        attempt = self.db.execute('SELECT attempts FROM jobs WHERE id=?', (job_id,)).fetchone()[0]
        record_id = f'{job_id}:{attempt}'
        raw = None
        error = None
        result = None
        retry_time = None
        try:
            raw = self.http(request)
        except Exception:
            error = SourceError(self.source + ' could not be reached')
        with self.db:
            if error is None:
                raw_text = raw if isinstance(raw, str) else json.dumps(raw)
                write(self.db, 'INSERT INTO source_records VALUES(?,?,?,?,?,?)',
                      (self.source, kind, record_id, redact(raw_text), now().isoformat(), 'received'))
                self.db.execute('SAVEPOINT normalized')
                try:
                    value = json.loads(redact(raw_text))
                    # A 401 or 403 carrying the source's own JSON error is the source refusing the key.
                    # An HTML or empty answer (proxy, WAF) says nothing about the key and stays a plain failure.
                    if (getattr(raw, 'status', None) in (401, 403) and self.credentials
                            and isinstance(value, dict) and self.key_refused(value)):
                        raise KeyRejected(self.label + ' API unsuccessful')
                    result = normalize(value)
                except RemoteBudgetExceeded as exhausted:
                    self.db.execute('ROLLBACK TO normalized')
                    error = WaitingForBudget(job_id, throttled=exhausted.retry_seconds is not None)
                    if exhausted.retry_seconds is not None:
                        retry_time = (now() + timedelta(seconds=exhausted.retry_seconds)).isoformat()
                        write(self.db, 'INSERT OR REPLACE INTO settings VALUES(?,?)',
                              ('source:blocked_until:' + self.source, retry_time))
                    else:
                        write(self.db, 'INSERT OR REPLACE INTO settings VALUES(?,?)',
                              ('source:blocked_day:' + self.source, now().date().isoformat()))
                except ColourCodeError as failure:
                    self.db.execute('ROLLBACK TO normalized')
                    error = failure
                except SourceError as failure:
                    self.db.execute('ROLLBACK TO normalized')
                    error = (KeyRejected if isinstance(failure, KeyRejected) else SourceError)(redact(failure))
                except Exception:
                    self.db.execute('ROLLBACK TO normalized')
                    error = SourceError(self.source + ' returned an invalid or unsuccessful reply')
                finally:
                    self.db.execute('RELEASE normalized')
                write(self.db, 'UPDATE source_records SET status=? WHERE source=? AND kind=? AND source_id=?',
                      ('failed' if error else 'success', self.source, kind, record_id))
            retry = retry_time or (now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
            if isinstance(error, WaitingForBudget):
                error.retry_at = retry
            write(self.db, 'UPDATE jobs SET state=?,error=?,updated_at=?,retry_at=? WHERE id=?',
                  ('waiting_for_budget' if isinstance(error, WaitingForBudget) else 'failed' if error else 'done',
                   str(error) if error else None, now().isoformat(),
                   retry if isinstance(error, WaitingForBudget) else None, job_id))
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
        day = now().date().isoformat()
        used = budget_used(self.db, self.source, day)
        success = self.db.execute("SELECT max(updated_at) FROM jobs WHERE source=? AND state='done'", (self.source,)).fetchone()[0]
        state = self.status_key()
        return dict(key='set' if state['configured'] else 'unset', key_state=state, budget=self.daily_budget,
                    used_today=used, last_success=success)


def record_change(db, entity, old, new):
    """Retain before/after snapshots for source-owned display data."""
    db.execute('INSERT INTO events(entity,field,old_value,new_value,at,via,actor) VALUES(?,?,?,?,?,?,?)',
               (entity, 'source_record', json.dumps(old, default=str), json.dumps(new, default=str),
                now().isoformat(), AUDIT_ORIGIN.get(), AUDIT_ACTOR.get()))
