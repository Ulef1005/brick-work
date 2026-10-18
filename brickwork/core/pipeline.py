"""Durable, independent import steps over the v3 source layer.

Callers create canonical catalogue items here; collection writes remain separate.
A Pipeline owns its connection's transactions (do not wrap it in a transaction).
"""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3

from .connect import connect
from .importer.projection import PRIORITY
from .sources import base, images
from .sources.base import CatalogueNotLoaded, SourceDisabled, SourceError, WaitingForBudget, item, write
from .sources.bricklink import BrickLink
from .sources.bricklink_catalogue import BrickLinkCatalogue
from .sources.brickset import Brickset
from .sources.rebrickable import Rebrickable

STEPS = tuple(PRIORITY)
EVENT = 'import_progress'
TYPES = set('SPMGBCIO')
LABELS = {'identity': 'Fetching identity', 'inventory': 'Fetching parts',
          'matching': 'Matching ids', 'pictures': 'Downloading images',
          'metadata': 'Fetching set metadata', 'market_price': 'Fetching market price'}
NAMES = {'bricklink': 'BrickLink', 'bricklink:api': 'BrickLink',
         'bricklink:subsets': 'BrickLink', 'bricklink:local': 'BrickLink catalogue',
         'rebrickable': 'Rebrickable', 'brickset': 'Brickset', 'picture_refresh': 'Pictures'}


def yield_worker(db):
    """Never switch greenlets while this connection holds a transaction."""
    if db.in_transaction:
        return
    # wsgi.py patches before the app is imported; the CLI is never patched.
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


# Include pid so a fork cannot inherit ownership, and path to distinguish databases.
_CLAIMED_JOBS = set()


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
    if not isinstance(value, dict) or set(value) != set(STEPS):
        raise ValueError('source_priority must define all six steps')
    for step, types in value.items():
        if not isinstance(types, dict) or not types or any(t not in TYPES | {'*'} for t in types):
            raise ValueError('invalid priority item type')
        for sources in types.values():
            if (not isinstance(sources, list) or not sources
                    or any(not isinstance(s, str) or not re.fullmatch('[a-z][a-z0-9_:]*', s) for s in sources)
                    or len(sources) != len(set(sources))):
                raise ValueError('invalid source priority')
    return value


class Pipeline:
    def __init__(self, db, *, root=None, catalogue=None, http=None, image_http=None,
                 emit=None, handlers=None):
        self.db = db
        path = Path(db.execute('PRAGMA database_list').fetchone()['file'])
        self.path = path
        from .media import root_for
        self.root = Path(root) if root is not None else root_for(path)
        self.catalogue = Path(catalogue) if catalogue else path.with_name('bricklink-catalog.db')
        self.image_http = image_http
        self.emit = emit or (lambda event, payload: None)
        # An extension supplies (step, source) -> handler(pipeline, job, step).
        self.handlers = handlers or {}
        self.clients = {c.source: c(db, http=http) for c in (BrickLink, Rebrickable, Brickset)}
        from .transaction import transaction, schema
        with transaction(db):
            schema(db, Path(__file__).with_name('import.sql').read_text())
            if 'error_code' not in {r[1] for r in db.execute('PRAGMA table_info(import_steps)')}:
                # Additive: the stable code of a failed step (source_not_configured, source_disabled, ...).
                db.execute('ALTER TABLE import_steps ADD COLUMN error_code TEXT')
            write(db, "INSERT OR IGNORE INTO sources(source,name,kind) VALUES('import','Import pipeline','manual')")
            write(db, 'INSERT OR IGNORE INTO settings VALUES(?,?)', ('source_priority', json.dumps(PRIORITY)))
            for kind in sorted(TYPES):
                write(db, 'INSERT OR IGNORE INTO settings VALUES(?,?)', ('import_order:' + kind, json.dumps(STEPS)))

    def status(self, job):
        row = self.db.execute("SELECT * FROM jobs WHERE id=? AND source='import'", (job,)).fetchone()
        if not row:
            raise ValueError('unknown import job')
        return {**dict(row), 'steps': [dict(s) for s in self.db.execute(
            'SELECT * FROM import_steps WHERE job_id=? ORDER BY position', (job,))]}

    def queue_steps(self, item_type, item_no, steps, *, via='app', sources=None, reference_image=None):
        """Queue a selective refresh without resetting an existing import.

        The worker uses the same durable step handlers and budget checkpoints.
        This method participates in the caller's transaction.
        """
        if (item_type not in TYPES or not re.fullmatch('[A-Za-z0-9-]{1,32}', item_no)) and not (reference_image and steps == ('pictures',) and item_type == '?'):
            raise ValueError('invalid BrickLink item key')
        if not steps or any(s not in STEPS for s in steps) or via not in ('app', 'cli', 'api'):
            raise ValueError('invalid refresh steps')
        priority = validate_priority(json.loads(self.db.execute(
            "SELECT value FROM settings WHERE key='source_priority'").fetchone()[0]))
        from .sources.base import AUDIT_ACTOR
        stamp = base.now().isoformat()
        job = self.db.execute('''INSERT INTO jobs(source,kind,item_type,item_no,state,payload,created_at,updated_at)
            VALUES('import','refresh',?,?,'queued',?,?,?)''',
            (item_type, item_no, json.dumps({'via': via, **({'actor': AUDIT_ACTOR.get()} if via=='api' else {}), **({'reference_image': reference_image} if reference_image else {})}), stamp, stamp)).lastrowid
        for position, step in enumerate(steps):
            order = sources or priority[step].get(item_type, priority[step].get('*', []))
            self.db.execute('''INSERT INTO import_steps(job_id,name,position,sources,updated_at)
                VALUES(?,?,?,?,?)''', (job, step, position, json.dumps(order), stamp))
        from .admin import audit
        from .sources.base import AUDIT_ACTOR
        audit(self.db, 'job:' + str(job), 'queued', new=list(steps), via=via, actor=AUDIT_ACTOR.get())
        return job

    def list_jobs(self, failed=False):
        return [self.status(row[0]) for row in self.db.execute(
            "SELECT id FROM jobs WHERE source='import' AND (?=0 OR state='failed' OR EXISTS "
            "(SELECT 1 FROM import_steps WHERE job_id=jobs.id AND state='failed')) ORDER BY id DESC", (int(failed),))]

    def update_step(self, job, step, state, *, source=None, error=None, retry_at=None, count=0, total=1, error_code=None):
        with self.db:
            write(self.db, '''UPDATE import_steps SET state=?,source=?,error=?,retry_at=?,count=?,total=?,updated_at=?,error_code=?
                WHERE job_id=? AND name=?''', (state, source, error, retry_at, count, total, base.now().isoformat(), error_code, job, step))

    def progress(self, job, step, state, *, source=None, count=0, total=1, error=None):
        snapshot = self.status(job)
        steps = snapshot['steps']
        done = sum(s['state'] == 'done' for s in steps)
        label = NAMES.get(source, source or '')
        bulk = snapshot['kind'] == 'picture_refresh'
        if bulk:
            saved = steps[0]
            count, total = saved['count'], saved['total']
        if step is None:
            message = ('Import complete' if state == 'done' else
                       f'{label} · Waiting for budget' + (f' · {error}' if error else '') if state == 'waiting' and label else
                       'Waiting for budget' if state == 'waiting' else
                       f'{label} failed · {error}' if error else 'Import needs attention')
        elif state == 'failed':
            message = f'{label or "Import"} failed · {error}'
        elif state == 'waiting':
            message = f'{label} · Waiting for budget'
        else:
            message = f'{LABELS[step]} from {label}'
            if state == 'progress':
                message += f' · {count} of {total}'
        if bulk:
            message = f'Downloading images · {count} of {total}' + (' · waiting for budget' if state == 'waiting' else ' · complete' if state == 'done' else f' · failed · {error or "Import needs attention"}' if state == 'failed' else '')
        payload = dict(job_id=job, item_type=snapshot['item_type'], item_no=snapshot['item_no'],
                       step=step, source=source, state=state, count=count, total=total,
                       completed_steps=done, total_steps=len(steps), job_state=snapshot['state'],
                       message=base.redact(message), error=base.redact(error) if error else None,
                       retry=state == 'failed' and step is not None)
        try:
            self.emit(EVENT, payload)
        except Exception:
            # A disconnected observer must never change durable import results.
            pass

    def import_item(self, item_type, item_no, *, via):
        if item_type not in TYPES or not isinstance(item_no, str) or not re.fullmatch('[A-Za-z0-9-]{1,32}', item_no):
            raise ValueError('invalid BrickLink item key')
        if via not in ('app', 'cli', 'api', 'order', 'part-to-inventory'):
            raise ValueError('invalid import origin')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute("SELECT id FROM jobs WHERE source='import' AND item_type=? AND item_no=? ORDER BY id DESC LIMIT 1",
                                       (item_type, item_no)).fetchone()
            if existing:
                job = existing[0]
            else:
                settings = dict(self.db.execute('SELECT key,value FROM settings'))
                priority = validate_priority(json.loads(settings['source_priority']))
                order = json.loads(settings['import_order:' + item_type])
                if not isinstance(order, list) or any(not isinstance(s, str) for s in order) or len(order) != len(STEPS) or set(order) != set(STEPS):
                    raise ValueError('import order must contain all six steps once')
                item(self.db, item_type, item_no)
                job = write(self.db, '''INSERT INTO jobs(source,kind,item_type,item_no,state,payload,created_at,updated_at)
                    VALUES('import','item',?,?,'queued',?,?,?)''',
                    (item_type, item_no, json.dumps({'via': via}), base.now().isoformat(), base.now().isoformat())).lastrowid
                for position, step in enumerate(order):
                    sources = priority[step].get(item_type, priority[step].get('*', []))
                    write(self.db, '''INSERT INTO import_steps(job_id,name,position,sources,updated_at)
                        VALUES(?,?,?,?,?)''', (job, step, position, json.dumps(sources), base.now().isoformat()))
        return self.run(job)

    def call(self, job, step, operation, invoke):
        """Persist per-call checkpoints, including the exact waiting source job."""
        saved = self.db.execute('SELECT * FROM import_calls WHERE job_id=? AND step=? AND operation=?',
                                (job, step, operation)).fetchone()
        if saved and saved['result'] is not None:
            return json.loads(saved['result'])
        try:
            result = invoke(saved['request_job'] if saved else None)
        except WaitingForBudget as waiting:
            with self.db:
                write(self.db, '''INSERT INTO import_calls(job_id,step,operation,request_job) VALUES(?,?,?,?)
                    ON CONFLICT(job_id,step,operation) DO UPDATE SET request_job=excluded.request_job''',
                      (job, step, operation, waiting.job_id))
            raise
        except Exception:
            if saved and saved['request_job'] is not None:
                with self.db:
                    write(self.db, 'UPDATE import_calls SET request_job=NULL WHERE job_id=? AND step=? AND operation=?',
                          (job, step, operation))
            raise
        with self.db:
            write(self.db, '''INSERT INTO import_calls(job_id,step,operation,result) VALUES(?,?,?,?)
                ON CONFLICT(job_id,step,operation) DO UPDATE SET result=excluded.result,request_job=NULL''',
                  (job, step, operation, json.dumps(result)))
        return result

    def owner_alive(self, job):
        owner = self.db.execute('SELECT pid FROM import_owners WHERE job_id=?', (job,)).fetchone()
        return owner_pid_alive(owner[0] if owner else None, path=self.path, job=job)

    def run(self, job):
        options=json.loads(self.status(job)['payload'] or '{}')
        if options.get('via')=='api':
            with base.audit_origin('api',actor=options.get('actor')):
                return self._run(job)
        return self._run(job)

    def _run(self, job):
        # Atomic claim prevents two workers importing the same item concurrently.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            snapshot = self.status(job)
            state = snapshot['state']
            if state == 'done' or self.owner_alive(job):
                return self.status(job)
            write(self.db, 'INSERT OR REPLACE INTO import_owners(job_id,pid) VALUES(?,?)', (job, os.getpid()))
            write(self.db, "UPDATE jobs SET state='running',attempts=attempts+1,updated_at=? WHERE id=?",
                  (base.now().isoformat(), job))
        _CLAIMED_JOBS.add((os.getpid(), str(self.path.resolve()), job))
        for saved in cooperative(self.db, snapshot['steps']):
            step = saved['name']
            if saved['state'] in ('done', 'failed'):
                continue
            if saved['state'] == 'waiting_for_budget' and saved['retry_at'] and saved['retry_at'] > base.now().isoformat():
                continue
            sources = json.loads(saved['sources'])
            if not self.applicable(snapshot['item_type'], step):
                sources = []
            for index in cooperative(self.db, range(saved['source_index'], len(sources))):
                source = sources[index]
                with self.db:
                    write(self.db, 'UPDATE import_steps SET source_index=? WHERE job_id=? AND name=?', (index, job, step))
                self.update_step(job, step, 'running', source=source,
                                 count=saved['count'] if snapshot['kind'] == 'picture_refresh' else 0,
                                 total=saved['total'] if snapshot['kind'] == 'picture_refresh' else 1)
                self.progress(job, step, 'started', source=source)
                try:
                    handler = self.handlers.get((step, source))
                    if handler:
                        handler(self, snapshot, step)
                    else:
                        self.perform(snapshot, step, source)
                    if step == 'inventory' and snapshot['item_type'] == 'S':
                        from .add import materialize
                        materialize(self.db, snapshot['item_type'], snapshot['item_no'])
                except WaitingForBudget as waiting:
                    child = self.db.execute('SELECT retry_at FROM jobs WHERE id=?', (waiting.job_id,)).fetchone()
                    current = self.status(job)['steps'][saved['position']]
                    self.update_step(job, step, 'waiting_for_budget', source=source, retry_at=child[0], count=current['count'], total=current['total'])
                    self.progress(job, step, 'waiting', source=source)
                    break
                except Exception as error:
                    # Source errors are safe; arbitrary failures must not leak URLs/keys.
                    message = base.redact(error) if isinstance(error, SourceError) else 'Import step could not be completed'
                    self.update_step(job, step, 'failed', source=source, error=message,
                                     error_code=(getattr(error, 'code', None) or 'source_error') if isinstance(error, SourceError) else None)
                    self.progress(job, step, 'failed', source=source, error=message)
                    if index + 1 < len(sources):
                        continue
                    break
                else:
                    total = saved['total'] if snapshot['kind'] == 'picture_refresh' else 1
                    self.update_step(job, step, 'done', source=source, count=total, total=total)
                    self.progress(job, step, 'done', source=source, count=total, total=total)
                    break
            else:
                self.update_step(job, step, 'done', count=1)
                self.progress(job, step, 'done', count=1)
        steps = self.status(job)['steps']
        waits = [s['retry_at'] for s in steps if s['state'] == 'waiting_for_budget' and s['retry_at']]
        failures = [s for s in steps if s['state'] == 'failed']
        state = 'waiting_for_budget' if waits else 'failed' if failures else 'done'
        with self.db:
            write(self.db, 'UPDATE jobs SET state=?,error=?,retry_at=?,updated_at=? WHERE id=?',
                  (state, failures[0]['error'] if failures else None, min(waits) if waits else None, base.now().isoformat(), job))
            write(self.db, 'DELETE FROM import_owners WHERE job_id=?', (job,))
        _CLAIMED_JOBS.discard((os.getpid(), str(self.path.resolve()), job))
        blocked = next((s for s in steps if s['state'] == 'waiting_for_budget'), None)
        failed = failures[0] if failures else None
        error = failed['error'] if failed else None
        if waits and failed:
            error = f"{NAMES.get(failed['source'], failed['source'])} failed · {error}"
        self.progress(job, None, 'waiting' if waits else state,
                      source=blocked['source'] if blocked else failed['source'] if failed else None, error=error)
        return self.status(job)

    @staticmethod
    def applicable(kind, step):
        return not (step == 'inventory' and kind not in ('S', 'M') or step == 'metadata' and kind != 'S')

    def queue_retry(self, job, step=None):
        from .transaction import transaction
        with transaction(self.db):
            snapshot = self.status(job)
            if self.owner_alive(job):
                raise ValueError('import job is running')
            if step is not None and step not in {s['name'] for s in snapshot['steps']}:
                raise ValueError('unknown import step')
            for saved in snapshot['steps']:
                if saved['state'] != 'failed' or step is not None and saved['name'] != step:
                    continue
                write(self.db, '''UPDATE import_steps SET state='queued',source_index=0,error=NULL,error_code=NULL,retry_at=NULL,updated_at=?
                    WHERE job_id=? AND name=?''', (base.now().isoformat(), job, saved['name']))
            write(self.db, "UPDATE jobs SET state='queued',error=NULL,retry_at=NULL,updated_at=? WHERE id=?",
                  (base.now().isoformat(), job))
        return job

    def retry(self, job, step=None):
        self.queue_retry(job, step)
        return self.run(job)

    def drain(self, limit=100):
        jobs = [r[0] for r in self.db.execute("""SELECT id FROM jobs WHERE source='import'
            AND (state IN ('queued','running') OR state='waiting_for_budget' AND retry_at<=?) ORDER BY id LIMIT ?""",
            (base.now().isoformat(), limit))]
        results = [self.run(job) for job in cooperative(self.db, jobs) if not self.owner_alive(job)]
        if results:
            try:
                self.db.execute('PRAGMA optimize')  # cheap: re-analyses only tables whose size changed a lot
            except sqlite3.Error:
                pass
        return results

    def match_id(self, kind, number=None, color=None):
        # Migrated part matches may carry colour evidence as well as a part id.
        clause = 'color_id IS ?' if kind == 'color' else 'item_type=? AND item_no=?'
        values = (color,) if kind == 'color' else ({'part': 'P', 'minifigure': 'M', 'set': 'S'}[kind], number)
        rows = self.db.execute("SELECT DISTINCT source_id FROM id_match WHERE source='rebrickable' AND kind=? AND " +
                               clause + " AND status IN ('matched','manual','inferred')", (kind, *values)).fetchall()
        if len(rows) != 1:
            raise SourceError('Rebrickable id needs manual matching')
        return rows[0][0]

    def resolution(self, number):
        try:
            return self.match_id('part', number)
        except SourceError:
            pass
        raw = self.db.execute("SELECT payload FROM source_records WHERE source='rebrickable' AND kind='part_resolutions' AND source_id=?",
                              (number,)).fetchone()
        if raw is None:
            raise SourceError('Part resolution needs manual matching')
        records = json.loads(raw[0])['records']
        candidates = set()
        for entry in records:
            record = entry['record']
            if record['bricklink'] != number:
                raise SourceError('Part resolution evidence mismatch')
            candidates.update(row['part_num'] for row in json.loads(record['parts']))
        if len(candidates) != 1:
            raise SourceError('Part resolution needs manual matching')
        source_id = next(iter(candidates))
        old = self.db.execute("SELECT item_type,item_no,status FROM id_match WHERE source='rebrickable' AND kind='part' AND source_id=?",
                              (source_id,)).fetchone()
        if old and (old['status'] in ('manual', 'matched', 'inferred') or old['item_type'] == '?'):
            raise SourceError('Part resolution needs manual matching')
        with self.db:
            write(self.db, "INSERT INTO id_match(source,kind,source_id,item_type,item_no,method,status,evidence_json,decided_at) "
                  "VALUES('rebrickable','part',?,'P',?,'part_resolutions','inferred',?,?) "
                  "ON CONFLICT(source,kind,source_id) DO UPDATE SET item_type='P',item_no=excluded.item_no,"
                  "method=excluded.method,status=excluded.status,evidence_json=excluded.evidence_json,decided_at=excluded.decided_at",
                  (source_id, number, base.redact(raw[0]), base.now().isoformat()))
        return source_id

    def colors(self, kind, number):
        if kind != 'P':
            return [None]
        return [r[0] for r in self.db.execute('''SELECT color_id FROM inventory_lines
            WHERE child_item_type='P' AND child_item_no=? AND color_id IS NOT NULL
            UNION SELECT color_id FROM loose_stock WHERE item_type='P' AND item_no=? AND color_id IS NOT NULL
            UNION SELECT color_id FROM copy_parts WHERE item_type='P' AND item_no=? AND color_id IS NOT NULL
            UNION SELECT color_id FROM wishlist WHERE item_type='P' AND item_no=? AND archived_at IS NULL AND color_id IS NOT NULL''',
            (number, number, number, number))] or [None]

    def perform(self, job, step, source):
        if step == 'pictures' and source == 'picture_refresh':
            from .pictures import run
            with base.audit_origin(json.loads(job['payload']).get('via', 'app'), actor=json.loads(job['payload']).get('actor')):
                return run(self, job)
        provider = source.split(':')[0]
        enabled = self.db.execute('SELECT enabled FROM sources WHERE source=?', (provider,)).fetchone()
        if enabled and not enabled[0]:
            raise SourceDisabled(NAMES.get(provider, provider) + ' is disabled', source=provider)
        jid, kind, number = job['id'], job['item_type'], job['item_no']
        options = json.loads(job['payload'] or '{}')
        def call(key, fn):
            return self.call(jid, step, options.get('picture_prefix', '') + source + ':' + key, fn)
        reference = options.get('reference_image')
        if step == 'pictures' and source == 'rebrickable' and reference:
            call('reference_download', lambda _: images.download(self.db, self.root, source, kind, number,
                 reference, http=self.image_http, image_kind=images.picture_kind(source, kind)))
            return
        if step == 'identity' and source == 'bricklink:local':
            if not self.catalogue.is_file():
                raise CatalogueNotLoaded('BrickLink catalogue unavailable')
            with closing(sqlite3.connect(self.catalogue.resolve().as_uri() + '?mode=ro', uri=True)) as catalogue:
                columns = {r[1] for r in catalogue.execute('PRAGMA table_info(items)')}
                row = catalogue.execute('SELECT name,category,' + ('year' if 'year' in columns else 'NULL') +
                                        ' FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone()
            if not row:
                raise SourceError('BrickLink catalogue item missing')
            with self.db:
                BrickLinkCatalogue(self.db).register()
                item(self.db, kind, number, row[0])
                base.property_value(self.db, 'bricklink', kind, number, 'name', row[0])
                write(self.db, 'UPDATE items SET category=?,year=coalesce(?,year) WHERE item_type=? AND item_no=?', (row[1], row[2], kind, number))
            return
        if step == 'identity' and source in ('bricklink', 'bricklink:api'):
            return call('item', lambda child: self.clients['bricklink'].item_info(kind, number, job_id=child))
        if step == 'inventory' and source in ('bricklink', 'bricklink:subsets'):
            rows = call('subsets', lambda child: self.clients['bricklink'].subsets(kind, number, job_id=child))
            for count in cooperative(self.db, range(1, len(rows) + 1)):
                self.progress(jid, step, 'progress', source=source, count=count, total=len(rows))
            return
        if step == 'matching':
            if kind != 'P':
                return  # BL inventory/identity does not require foreign identifiers.
            if source in ('part_resolutions', 'manual'):
                if source == 'part_resolutions':
                    self.resolution(number)
                self.match_id('part', number)
                return
            if source == 'rebrickable':
                try:
                    self.match_id('part', number)
                except SourceError:
                    call('part', lambda child: self.clients[source].find_part(number, job_id=child))
                for color in cooperative(self.db, self.colors(kind, number)):
                    if color is None:
                        continue
                    try:
                        self.match_id('color', color=color)
                    except SourceError:
                        page = 1
                        while True:
                            def consume(reply):
                                for row in cooperative(self.db, reply['results']):
                                    ids = row.get('external_ids', {}).get('BrickLink', {})
                                    ids = ids.get('ext_ids', []) if isinstance(ids, dict) else ids
                                    canonical = int(ids[0]) if len(ids) == 1 else None
                                    self.clients[source].match('color', row, canonical=canonical)
                                return bool(reply.get('next'))
                            more = call('colors:' + str(page), lambda child: self.clients[source].call(
                                '/colors/', {'page': page, 'page_size': 1000}, normalize=consume, job_id=child))
                            if not more:
                                break
                            page += 1
                            yield_worker(self.db)
                        self.match_id('color', color=color)
                return
        if step == 'pictures' and source in ('bricklink', 'rebrickable'):
            colors = [options['picture_color']] if 'picture_color' in options else self.colors(kind, number)
            for color in cooperative(self.db, colors):
                if source == 'bricklink':
                    url = f'https://img.bricklink.com/ItemImage/{kind}N/{color or 0}/{number}.png'
                else:
                    if kind == 'P':
                        rb = self.match_id('part', number)
                        if color is not None:
                            rb_color = int(self.match_id('color', color=color))
                            url = call('url:' + str(color), lambda child: self.clients[source].part_image(rb, rb_color, job_id=child))
                        else:
                            row = call('part_image', lambda child: self.clients[source].part(rb, canonical=number, job_id=child))
                            url = row.get('part_img_url')
                    elif kind in ('S', 'M'):
                        rb = number if kind == 'S' else self.match_id('minifigure', number)
                        row = call('image', lambda child: self.clients[source].minifigure(rb, canonical=number, job_id=child)
                                   if kind == 'M' else self.clients[source].call('/sets/' + rb + '/', job_id=child))
                        url = row.get('set_img_url')
                    else:
                        raise SourceError('Rebrickable has no image for this item type')
                if not url:
                    raise SourceError(source + ' image unavailable')
                def fetch(child):
                    reservation = self.clients[source].reserve('picture', {'type': kind, 'number': number, 'color': color}, job_id=child) if 'picture_prefix' in options else None
                    try:
                        result = images.download(self.db, self.root, source, kind, number, url,
                            color=color, image_kind=images.picture_kind(source, kind), http=self.image_http)
                    except SourceError:
                        if reservation is not None:
                            with self.db:
                                write(self.db, "UPDATE jobs SET state='failed',error='Image could not be downloaded',updated_at=? WHERE id=?", (base.now().isoformat(), reservation))
                        raise
                    if reservation is not None:
                        with self.db:
                            write(self.db, "UPDATE jobs SET state='done',updated_at=? WHERE id=?", (base.now().isoformat(), reservation))
                    return result
                call('download:' + str(color), fetch)
            return
        if step == 'metadata' and source == 'brickset':
            result = call('metadata', lambda child: self.clients[source].refresh([number], job_id=child))
            if number not in result:
                raise SourceError('Brickset set metadata missing')
            return
        if step == 'market_price' and source == 'bricklink':
            for color in cooperative(self.db, self.colors(kind, number)):
                for condition in cooperative(self.db, ('N', 'U')):
                    call(f'price:{color}:{condition}', lambda child: self.clients[source].price(kind, number, color, condition, job_id=child))
            return
        raise SourceError('Import source has no handler for this step')


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


def import_item(item_type, item_no, *, via, path=None, **options):
    with closing(connect(database_path(path))) as db:
        return Pipeline(db, **options).import_item(item_type, item_no, via=via)


def retry(job, step=None, *, path=None, **options):
    with closing(connect(database_path(path))) as db:
        return Pipeline(db, **options).retry(job, step)


def status(job, *, path=None):
    with closing(connect(database_path(path))) as db:
        return Pipeline(db).status(job)


def poll_delay(db):
    """Stop when empty; wait for the earliest budget deadline, at most 60s."""
    rows = db.execute("""SELECT state,retry_at FROM jobs WHERE source='import'
        AND state IN ('queued','running','waiting_for_budget')""").fetchall()
    if not rows:
        return None
    now = base.now()
    if any(row['state'] != 'waiting_for_budget' or
           row['retry_at'] and row['retry_at'] <= now.isoformat() for row in rows):
        return 1
    from datetime import datetime
    deadlines = [datetime.fromisoformat(row['retry_at']) for row in rows if row['retry_at']]
    return min(60, max(0, (min(deadlines) - now).total_seconds())) if deadlines else 60


def worker(*, path=None, limit=100, stop=None, poll_seconds=1, **options):
    """Drain once, or poll until a threading.Event is set for automatic resumes."""
    if limit < 1 or poll_seconds <= 0:
        raise ValueError('worker limit and poll interval must be positive')
    with closing(connect(database_path(path))) as db:
        pipeline = Pipeline(db, **options)
        if stop is None:
            return pipeline.drain(limit)
        while not stop.is_set():
            pipeline.drain(limit)
            stop.wait(poll_seconds)
        return []


def queue_new_items(db, items):
    """Queue the normal catalogue import for items that are new to this store, as Add does."""
    settings = dict(db.execute("SELECT key,value FROM settings WHERE key LIKE 'import_order:%'").fetchall())
    pipeline, jobs = Pipeline(db), []
    for kind, number in sorted(items):
        if kind not in ('S', 'M') or 'import_order:' + kind not in settings:
            continue
        if db.execute('SELECT 1 FROM jobs WHERE item_type=? AND item_no=? LIMIT 1', (kind, number)).fetchone():
            continue
        order = json.loads(settings['import_order:' + kind])
        if len(order) != len(STEPS) or set(order) != set(STEPS):
            continue
        from .sources.base import AUDIT_ORIGIN
        jobs.append(pipeline.queue_steps(kind, number, order, via=AUDIT_ORIGIN.get() if AUDIT_ORIGIN.get() in ('api', 'cli') else 'app'))
    return jobs
