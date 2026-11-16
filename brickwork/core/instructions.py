"""Instruction discovery and confirmed downloads on the existing job queue."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import re
import time
from urllib.parse import urlsplit

from . import instruction_sources as sources
from .pipeline import Pipeline
from .transaction import transaction
from ..store4.connect import now

NO_SOURCE = 'No instruction source is set up yet'
DOWNLOAD_KIND = 'instruction_download'
CAP = 50
DELAY = 1.0


def region_for(db):
    row = db.execute("SELECT value FROM main.setting WHERE key='retail_country'").fetchone()
    return row[0] if row and row[0] else 'DE'


def queue_find(db, item_ids, *, region=None, via='app', actor=None):
    ids = list(dict.fromkeys(item_ids))
    if not ids or len(ids) > CAP:
        raise ValueError('Choose between 1 and 50 sets')
    jobs = []
    for identifier in ids:
        from . import items, admin
        items.ensure(db, identifier)
        identifier = admin.instruction_set_of(db, identifier)
        row = db.execute('SELECT kind, merged_into FROM main.item WHERE id=?', (identifier,)).fetchone()
        if row['kind'] != 'set' or row['merged_into'] is not None:
            raise ValueError('Choose an existing set')
        job = Pipeline(db).queue_steps(identifier, ['instructions'], via=via, actor=actor)
        db.execute('INSERT INTO main.instruction_search(job_id,item_id,updated_at) VALUES(?,?,?)', (job, identifier, now()))
        payload = json.dumps({'steps': ['instructions'], 'region': region or region_for(db)})
        db.execute('UPDATE main.job SET payload=? WHERE id=?', (payload, job))
        jobs.append(job)
    return jobs


def find(db, job, *, registry=None):
    registry = registry if registry is not None else sources.registry
    region = json.loads(job['payload']).get('region') or region_for(db)
    item = db.execute('SELECT born_key FROM main.item WHERE id=?', (job['item_id'],)).fetchone()
    tried, failures = [], []
    for source, adapter in registry.adapters.items():
        tried.append(source)
        try:
            candidates = adapter.find(item['born_key'], region) if item['born_key'] else []
            with transaction(db):
                db.execute("INSERT OR IGNORE INTO main.source(id,name,kind) VALUES(?,?,'file')",
                           (source, sources.DISPLAY_NAMES[source]))
                for c in candidates:
                    if c.source != source or urlsplit(c.url).scheme != 'https':
                        raise ValueError('Invalid instruction candidate')
                    if not c.label or len(c.label) > 120:
                        raise ValueError('Invalid booklet label')
                    db.execute('''INSERT INTO main.instruction_candidate(item_id,search_job,source,title,booklet,booklets,language,region,size,url)
                        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id,source,url) DO UPDATE SET
                        search_job=excluded.search_job,title=excluded.title,booklet=excluded.booklet,booklets=excluded.booklets,
                        language=excluded.language,region=excluded.region,size=excluded.size''',
                        (job['item_id'], job['id'], source, c.label, c.booklet, c.booklets, c.language, c.region, c.size, c.url))
        except Exception:
            failures.append(getattr(adapter, 'unavailable', None) or sources.DISPLAY_NAMES[source] + ' did not answer')
    message = NO_SOURCE if not tried else ' · '.join(failures) or None
    with transaction(db):
        db.execute('UPDATE main.instruction_search SET sources_tried=?,error=?,updated_at=? WHERE job_id=?',
                   (json.dumps(tried), message, now(), job['id']))
    return message


def candidates(db, jobs):
    groups = []
    for job in jobs:
        row = db.execute('''SELECT s.*,i.name,i.born_key,j.state FROM main.instruction_search s
            JOIN main.item i ON i.id=s.item_id JOIN main.job j ON j.id=s.job_id WHERE s.job_id=?''', (job,)).fetchone()
        if row:
            files = [dict(c) for c in db.execute('SELECT * FROM main.instruction_candidate WHERE search_job=? ORDER BY booklet,id', (job,))]
            files.sort(key=lambda c: (c['source'], re.sub(r'\s*\(\d+/\d+\)\s*$', '', c['title']).casefold(), c['booklet'], c['id']))
            groups.append({**dict(row), 'sources_tried': json.loads(row['sources_tried']), 'candidates': files})
    return groups


REGIONS = {'AT': ('Europe', 'English'), 'DE': ('Europe', 'German'), 'GB': ('Europe', 'English'), 'UK': ('Europe', 'English'),
           'FR': ('Europe', 'French'), 'US': ('North America', 'English'), 'CA': ('North America', 'English'),
           'AU': ('Oceania', 'English')}
LANGUAGES = {'en': 'english', 'de': 'german', 'fr': 'french'}


def matches_region(candidate, region):
    if candidate['source'] == 'official':
        from .official_instructions import LOCALES
        return candidate['region'] == LOCALES.get(region, 'en-us')
    area, language = REGIONS.get(region, (region, None))
    region_match = not candidate['region'] or candidate['region'].casefold() in {region.casefold(), area.casefold(), 'any', 'worldwide', *({'uk', 'gb'} if region in ('UK', 'GB') else set())}
    spoken = (candidate['language'] or '').casefold()
    language_match = not language or not spoken or LANGUAGES.get(spoken, spoken) == language.casefold()
    return region_match and language_match


def download_limit(db, source):
    if source != 'official':
        return sources.LIMIT
    row = db.execute("SELECT value FROM main.setting WHERE key='official_download_limit_mb'").fetchone()
    return int(row[0] if row else 500) * 1024 * 1024


def tick_defaults(files, region, official_limit=500 * 1024 * 1024):
    selected, used = [], 0
    for c in files:
        limit = official_limit if c['source'] == 'official' else sources.LIMIT
        size = c['size']
        if (not c['file_id'] and size is not None and size <= limit and used + size <= official_limit
                and ((c['source'] == 'peeron' and len(files) == 1)
                     or (c['source'] != 'peeron' and matches_region(c, region)))):
            selected.append(c['id'])
            used += size
    return selected


def queue_download(db, candidate_ids, *, via='app', actor=None):
    ids = list(dict.fromkeys(candidate_ids))
    if not ids or len(ids) > CAP:
        raise ValueError('Tick between 1 and 50 files')
    rows = []
    for identifier in ids:
        row = db.execute('SELECT * FROM main.instruction_candidate WHERE id=?', (identifier,)).fetchone()
        if not row or row['file_id'] or row['size'] is not None and row['size'] > download_limit(db, row['source']):
            raise ValueError('Choose files within their source download limit')
        rows.append(row)
    stamp = now()
    job = db.execute('''INSERT INTO main.job(source,kind,state,payload,via,actor,created_at,updated_at)
        VALUES('import',?,'queued',?,?,?,?,?)''', (DOWNLOAD_KIND, json.dumps({'candidate_ids': ids}), via, actor, stamp, stamp)).lastrowid
    for position, row in enumerate(rows):
        db.execute('''INSERT INTO main.job_step(job_id,name,position,sources,updated_at)
            VALUES(?,?,?,?,?)''', (job, str(row['id']), position, json.dumps([row['source']]), stamp))
    from ..store4.audit import Events
    Events(db, via, actor).write('job', job, 'queued', new={'kind': DOWNLOAD_KIND, 'candidate_ids': ids})
    return job


class Downloads(Pipeline):
    kind = DOWNLOAD_KIND

    def __init__(self, db, *, registry=None, root=None, sleep=time.sleep, monotonic=time.monotonic):
        super().__init__(db)
        self.registry = registry if registry is not None else sources.registry
        from .media import media_root
        self.root = root if root is not None else media_root(db)
        self.sleep, self.monotonic, self.hosts = sleep, monotonic, {}
        self.requests = 0

    def run(self, job):
        self.requests = 0
        return super().run(job)

    def cancel(self, job):
        self.status(job)
        with transaction(self.db):
            self.db.execute("""UPDATE main.job_step SET state='failed',error='Cancelled',retry_at=NULL,updated_at=?
                WHERE job_id=? AND state IN ('queued','waiting_for_budget')""", (now(), job))
            if not self.owner_alive(job):
                self.db.execute("UPDATE main.job SET state='failed',error='Cancelled',retry_at=NULL,updated_at=? WHERE id=? AND state!='done'", (now(), job))

    def _step(self, job, saved):
        row = self.db.execute('SELECT * FROM main.instruction_candidate WHERE id=?', (int(saved['name']),)).fetchone()
        name = saved['name']
        if row is None:
            self._put(job['id'], name, 'failed', code='source_error', error='Candidate was removed')
            return
        self._put(job['id'], name, 'running', source=row['source'])
        try:
            if row['file_id']:
                self._put(job['id'], name, 'done', count=1)
                return
            if self.requests >= CAP:
                raise ValueError('Download limit reached · retry the remaining files')
            adapter = self.registry.adapters.get(row['source'])
            if adapter is None:
                raise ValueError(NO_SOURCE)
            host = urlsplit(row['url']).hostname
            # A second confirmed job must respect an earlier job's persisted host pause.
            pauses = self.db.execute('''SELECT s.retry_at,c.url FROM main.job_step s JOIN main.job j ON j.id=s.job_id
                JOIN main.instruction_candidate c ON c.id=CAST(s.name AS INTEGER)
                WHERE j.kind=? AND s.state='waiting_for_budget' AND s.retry_at>?''', (DOWNLOAD_KIND, now())).fetchall()
            pause = next((p['retry_at'] for p in pauses if urlsplit(p['url']).hostname == host), None)
            if pause:
                self._put(job['id'], name, 'waiting_for_budget', code='budget', retry_at=pause, error='Waiting for the source')
                return
            if host in self.hosts:
                self.sleep(max(0, DELAY - (self.monotonic() - self.hosts[host])))
            self.requests += 1
            self.hosts[host] = self.monotonic()
            limit = download_limit(self.db, row['source'])
            content = adapter.fetch(row['url'], limit)
            if not isinstance(content, bytes):
                try:
                    content_bytes = content.read(limit + 1)
                finally:
                    content.close()
                content = content_bytes
            from .admin import attach_instruction
            with transaction(self.db):
                file_id = attach_instruction(self.db, self.root, row['item_id'], row['title'], content, limit=limit)
                self.db.execute('UPDATE main.instruction_candidate SET file_id=? WHERE id=?', (file_id, row['id']))
                self._put(job['id'], name, 'done', source=row['source'], count=1)
        except sources.RetryAfter as wait:
            try:
                deadline = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(wait.value)))
            except (ValueError, TypeError):
                try:
                    deadline = parsedate_to_datetime(wait.value)
                    if deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError, AttributeError, OverflowError):
                    deadline = datetime.now(timezone.utc) + timedelta(seconds=60)
            deadline = max(deadline, datetime.now(timezone.utc) + timedelta(seconds=1))
            stamp = deadline.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            # Pause every remaining file: never issue another request after Retry-After in this run.
            for step in self.status(job['id'])['steps']:
                if step['state'] not in ('done', 'failed'):
                    self._put(job['id'], step['name'], 'waiting_for_budget', code='budget', error=str(wait), retry_at=stamp)
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else 'The source could not download this file'
            self._put(job['id'], name, 'failed', source=row['source'], code='source_error', error=message)
