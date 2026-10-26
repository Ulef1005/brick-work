"""`python -m brickwork.store4 catalogue download|import|rebuild|reconcile|status` (design 6.1, 6.2, 6.6; issue #104, M.2e)
and `fetch bricklink|rebrickable <set-number>`, `jobs`, `jobs drain` (the job runner, issue #107, M.5d), and
`copy add|show|switch|undo|pending|settle|changes|preference|prefer-bricklink` (copies and their part lists, issue #108, M.6d).

Separate from the app's `brickwork catalogue` CLI, which runs the 3.3 code until M.8. `--data DIR` holds `brickwork.db`,
`catalogue.db`, `catalogue-src/rebrickable/<date>/` (the downloads), `mappings/` (the local layer, optional) and
`bricklink-lists/` (optional)."""
import argparse
from contextlib import closing, contextmanager
from datetime import date as Date, datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import urllib.request

from . import copies, jobs, pending
from .activate import activate
from .builder import build
from .bricklink_list import import_bricklink
from .connect import _uri, connect, has_catalogue
from .dump import HEADERS
from .errors import BuildBusy, Store4Error
from .mappings import MAPPINGS_DIR
from .migrate import MigrationError, NeedsDecision
from .migrate_run import Refused, run as run_migration
from .reconcile import reconcile
from .swap import build_lock

BASE_URL = 'https://cdn.rebrickable.com/media/downloads/{}.csv.gz'
USER_AGENT = {'User-Agent': 'brick-work-mappings'}
ONE_A_DAY = 'Rebrickable asks for at most one download a day.'
MANIFEST = 'manifest.json'
SHOWN = ('items', 'sets', 'parts', 'minifigs', 'colours', 'inventories', 'lines', 'links_upgraded', 'same_number', 'kinds_corrected')


class DownloadError(Store4Error):
    """A download that failed or a download directory that is not complete."""


def app_version():
    from ..version import __version__
    return __version__


def http_fetch(url):
    """Default fetch: (bytes, Last-Modified header or None). Tests inject their own."""
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read(), r.headers.get('Last-Modified')


class Paths:
    def __init__(self, data):
        self.data = Path(data)
        self.collection = self.data / 'brickwork.db'
        self.catalogue = self.data / 'catalogue.db'
        self.downloads = self.data / 'catalogue-src' / 'rebrickable'
        self.mappings = self.data / 'mappings'
        self.lists = self.data / 'bricklink-lists'

    def local_dir(self):
        return self.mappings if self.mappings.is_dir() and any(self.mappings.glob('*.csv')) else None

    def collection_if_any(self):
        return self.collection if self.collection.exists() else None


# ---------- downloads ----------

def check_download(directory, *, verify=False):
    """The manifest of a complete download, else DownloadError. Complete = a manifest naming all 12 files, each present
    with the recorded size (and, with `verify`, the recorded sha256)."""
    directory = Path(directory)
    manifest = directory / MANIFEST
    if not manifest.is_file():
        raise DownloadError(f'{directory} has no {MANIFEST}: the download is not complete (run `catalogue download`)')
    try:
        data = json.loads(manifest.read_text())
        files = {}
        for f in data['files']:
            if not (isinstance(f['name'], str) and type(f['bytes']) is int and isinstance(f['sha256'], str)):
                raise TypeError(f'a file entry has the wrong shape: {f}')
            files[f['name']] = f
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise DownloadError(f'{manifest} is malformed, so the download counts as incomplete: {exc!r}') from exc
    for name in HEADERS:
        entry, path = files.get(f'{name}.csv.gz'), directory / f'{name}.csv.gz'
        if entry is None:
            raise DownloadError(f'{manifest} does not list {name}.csv.gz')
        if not path.is_file() or path.stat().st_size != entry['bytes']:
            raise DownloadError(f'{path} is missing or differs in size from the manifest')
        if verify and hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise DownloadError(f'{path} differs from the manifest (sha256)')
    return data


def newest_download(paths):
    """(directory, manifest) of the newest complete download, or None."""
    if paths.downloads.is_dir():
        for d in sorted((p for p in paths.downloads.iterdir() if p.is_dir()), reverse=True):
            try:
                return d, check_download(d)
            except DownloadError:
                continue
    return None


def pick_source(paths, src):
    if src:
        src = Path(src)
        check_download(src, verify=True)
        return src
    found = newest_download(paths)
    if found is None:
        raise DownloadError(f'no complete download under {paths.downloads}; run `catalogue download` first')
    check_download(found[0], verify=True)
    return found[0]


def download(paths, *, day=None, force=False, fetch=http_fetch, say=print):
    day = day or Date.today().isoformat()
    directory = paths.downloads / day
    say(ONE_A_DAY)
    try:
        data = check_download(directory)
    except DownloadError:
        data = None
    if data and not force:
        say(f'Today\'s download is complete already ({directory}); nothing fetched. Run `catalogue import` to use it, or pass --force.')
        return dict(downloaded=False, directory=str(directory), files=len(data['files']))
    with download_lock(paths):
        return _download(paths, directory, day, fetch, say)


@contextmanager
def download_lock(paths):
    """One download at a time per data dir; a second is refused (busy) before it touches anything."""
    paths.downloads.mkdir(parents=True, exist_ok=True)
    lock = open(paths.downloads / '.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise BuildBusy(f'another download is running on {paths.downloads} (busy); nothing was touched') from None
    try:
        yield
    finally:
        lock.close()


def _download(paths, directory, day, fetch, say):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / MANIFEST).unlink(missing_ok=True)       # the manifest goes first and returns last: a half download never looks complete
    entries = []
    for name in HEADERS:
        file = f'{name}.csv.gz'
        part = directory / (file + '.part')
        try:
            body, modified = fetch(BASE_URL.format(name))
        except Exception as exc:
            part.unlink(missing_ok=True)
            raise DownloadError(f'downloading {file} failed ({exc}); the download is not complete and has no manifest') from exc
        part.write_bytes(body)
        os.replace(part, directory / file)
        entries.append(dict(name=file, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), last_modified=modified))
        say(f'  {file}  {len(body):,} bytes')
    write_manifest(directory, entries, day)
    say(f'Downloaded {len(entries)} files to {directory}.')
    return dict(downloaded=True, directory=str(directory), files=len(entries))


def write_manifest(directory, entries, day):
    directory = Path(directory)
    manifest = dict(date=day, downloaded_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), files=entries)
    part = directory / (MANIFEST + '.part')
    part.write_text(json.dumps(manifest, indent=1))
    os.replace(part, directory / MANIFEST)


# ---------- build, activate, reconcile ----------

def activate_and_reconcile(paths):
    with closing(connect(paths.collection, paths.catalogue)) as db:
        activated = activate(db, via='cli')
        reconciled = reconcile(db, via='cli')
    return activated, reconciled


def do_import(paths, src=None, *, mappings_dir=MAPPINGS_DIR, now=None):
    source = pick_source(paths, src)
    built = build(source, paths.catalogue, collection=paths.collection_if_any(), app_version=app_version(), now=now,
                  mappings_dir=mappings_dir, local_dir=paths.local_dir())
    activated, reconciled = activate_and_reconcile(paths)
    return dict(source=str(source), build=built, activation=activated, reconcile=reconciled)


def do_import_bricklink(paths, directory, *, now=None):
    imported = import_bricklink(paths.catalogue, directory, collection=paths.collection_if_any(), app_version=app_version(), now=now)
    activated, reconciled = activate_and_reconcile(paths)
    return dict(bricklink=imported, activation=activated, reconcile=reconciled)


def do_rebuild(paths, src=None, *, mappings_dir=MAPPINGS_DIR, now=None):
    """Build from the newest download seeded only from the collection. An existing catalogue file is moved aside, never deleted."""
    source = pick_source(paths, src)
    aside = None
    with build_lock(paths.catalogue):                      # held from before the move until the new file is published
        if paths.catalogue.exists():
            aside = paths.catalogue.with_name(f"catalogue.db.damaged-{time.strftime('%Y%m%dT%H%M%S')}")
            os.replace(paths.catalogue, aside)
        try:
            built = build(source, paths.catalogue, collection=paths.collection_if_any(), app_version=app_version(), now=now,
                          mappings_dir=mappings_dir, local_dir=paths.local_dir(), locked=True)
        except BaseException:
            if aside and not paths.catalogue.exists():
                os.replace(aside, paths.catalogue)         # the build failed: the file is back where it was
            raise
    lists = newest_lists(paths)                            # the old file's lists are gone with it: reload them from disk (design 6.2)
    imported = import_bricklink(paths.catalogue, lists, collection=paths.collection_if_any(), app_version=app_version(), now=now) if lists else None
    activated, reconciled = activate_and_reconcile(paths)
    return dict(source=str(source), moved_aside=str(aside) if aside else None, build=built, bricklink=imported,
                bricklink_dir=str(lists) if lists else None, activation=activated, reconcile=reconciled)


def newest_lists(paths):
    """The newest subdirectory of data/bricklink-lists/ (by name), or None."""
    if paths.lists.is_dir():
        dirs = sorted(p for p in paths.lists.iterdir() if p.is_dir())
        if dirs:
            return dirs[-1]
    return None


def do_reconcile(paths):
    if not paths.catalogue.exists():
        raise DownloadError(f'{paths.catalogue} does not exist; run `catalogue import` or `catalogue rebuild`')
    activated, reconciled = activate_and_reconcile(paths)
    return dict(activation=activated, reconcile=reconciled)


# ---------- status ----------

def _ro(path):
    db = sqlite3.connect(_uri(path, 'ro'), uri=True)
    db.row_factory = sqlite3.Row
    return db


def do_status(paths):
    out = dict(data=str(paths.data))
    if paths.catalogue.exists():
        with closing(_ro(paths.catalogue)) as db:
            meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
            builds = []
            for r in db.execute('SELECT id, kind, started_at, finished_at, mapping_version, counts_json FROM build ORDER BY id'):
                counts = json.loads(r['counts_json'] or '{}')
                builds.append(dict(id=r['id'], kind=r['kind'], started_at=r['started_at'], mapping_version=r['mapping_version'],
                                   counts={k: v for k, v in counts.items() if isinstance(v, (int, str))}))
            inv = db.execute('SELECT count(*), count(bl_digest) FROM inventory WHERE retired_at IS NULL').fetchone()
            out['catalogue'] = dict(path=str(paths.catalogue), bytes=paths.catalogue.stat().st_size, catalogue_id=meta.get('catalogue_id'),
                                    item_high_water=meta.get('item_high_water'), color_high_water=meta.get('color_high_water'),
                                    builds=builds, bricklink_lists_loaded=db.execute('SELECT count(*) FROM bricklink_item').fetchone()[0] > 0,
                                    bricklink_items=db.execute('SELECT count(*) FROM bricklink_item').fetchone()[0],
                                    bl_digest=dict(inventories=inv[0], with_digest=inv[1], null=inv[0] - inv[1]))
    else:
        out['catalogue'] = None
    if paths.collection.exists():
        with closing(_ro(paths.collection)) as db:
            meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
            activated = [dict(id=r['id'], kind=r['kind'], activated_at=r['activated_at'], reconciled_at=r['reconciled_at'])
                         for r in db.execute('SELECT id, kind, activated_at, reconciled_at FROM catalogue_build ORDER BY id')]
            last = db.execute('SELECT counts_json FROM catalogue_build WHERE reconciled_at IS NOT NULL ORDER BY id DESC LIMIT 1').fetchone()
            rec = json.loads(last['counts_json']).get('reconcile') if last else None
            out['collection'] = dict(path=str(paths.collection), catalogue_id=meta.get('catalogue_id'), activated_builds=activated,
                                     item_high_water=meta.get('catalogue_item_high_water'), color_high_water=meta.get('catalogue_color_high_water'),
                                     last_reconcile=summary(rec) if rec else None)
        out['collection']['part_lists'] = part_list_summary(paths)
    else:
        out['collection'] = None
    found = newest_download(paths)
    if found:
        d, manifest = found
        age = (datetime.now(timezone.utc) - datetime.fromtimestamp((d / MANIFEST).stat().st_mtime, timezone.utc)).days
        out['download'] = dict(directory=str(d), date=manifest.get('date', d.name), downloaded_at=manifest.get('downloaded_at'), age_days=age)
    else:
        out['download'] = None
    return out


def part_list_summary(paths):
    """How many copies carry a part list that changed (`copies.part_list_changes`), read-only; None without both files, or
    `{'error': text}` when the pair does not fit together (status must not fail for that)."""
    if not (paths.collection.exists() and paths.catalogue.exists()):
        return None
    try:
        with closing(connect(paths.collection, paths.catalogue, read_only=True)) as db:
            return copies.summarise_changes(copies.part_list_changes(db))
    except Store4Error as exc:
        return dict(error=str(exc))


def summary(rec):
    return dict(changes=rec.get('changes', {}), not_applied={k: len(v) for k, v in rec.get('not_applied', {}).items()},
                coverage=rec.get('coverage', {}), events=rec.get('events'))


# ---------- fetch and jobs ----------

def find_set(db, number):
    """The collection's or the catalogue's set with this Rebrickable number (a local Rebrickable-born set included), else None."""
    for schema in ('main', 'catalogue'):
        if schema == 'catalogue' and not has_catalogue(db):
            continue
        row = db.execute(f"SELECT id FROM {schema}.item WHERE kind='set' AND born_provider='rebrickable' AND born_namespace='sets' "
                         'AND born_key=?', (number,)).fetchone()
        if row:
            return row[0]
    return None


def open_pair(paths):
    for what, path in (('collection', paths.collection), ('catalogue', paths.catalogue)):
        if not path.exists():
            raise Store4Error(f'{path} does not exist; run `catalogue import` first (the {what} is needed to fetch a list)')
    return closing(connect(paths.collection, paths.catalogue))


def do_fetch(paths, source, number, *, http=None, clock=None):
    """Queue the fetch job for a set, run it now, and return the run's result (a `jobs.run` dict)."""
    with open_pair(paths) as db:
        item_id = find_set(db, number)
        if source == 'bricklink':
            if item_id is None:
                raise Store4Error(f'set {number} is in neither the collection nor the catalogue; fetch it from Rebrickable first')
            job = jobs.queue(db, 'bricklink_subsets', item_id=item_id, payload=number, via='cli', now=clock)
        else:
            local = item_id if item_id is not None and db.execute("SELECT 1 FROM main.item WHERE id=? AND origin='local'", (item_id,)).fetchone() else None
            job = jobs.queue(db, 'rebrickable_set', item_id=local, payload=number, via='cli', now=clock)
        return jobs.run(db, job, http=http, now=clock)


def do_jobs(paths):
    with open_pair(paths) as db:
        return dict(jobs=jobs.list_jobs(db))


def do_drain(paths, *, http=None, clock=None, limit=100):
    with open_pair(paths) as db:
        return dict(ran=jobs.drain(db, limit=limit, now=clock, http=http))


# ---------- copies ----------

def parse_choice(text):
    """`rebrickable` (the latest version), `rebrickable:N`, `bricklink` or `rebrickable-api` as a part list choice."""
    t = text.strip().lower().replace('-', '_')
    if t in ('bricklink', 'rebrickable_api'):
        return {'source': t}
    if t == 'rebrickable':
        return {'source': 'rebrickable', 'version': None}
    if t.startswith('rebrickable:') and t[12:].isdigit() and int(t[12:]) > 0:
        return {'source': 'rebrickable', 'version': int(t[12:])}
    raise Store4Error(f'{text!r} is not a part list choice: rebrickable, rebrickable:N, bricklink or rebrickable-api')


def need_set(db, number):
    item_id = find_set(db, number)
    if item_id is None:
        raise Store4Error(f'set {number} is in neither the collection nor the catalogue')
    return item_id


def find_copy(db, ref):
    """A copy id, or a prefix of one that names exactly one copy."""
    rows = [r[0] for r in db.execute('SELECT id FROM main.copy WHERE id=? OR substr(id, 1, length(?))=? LIMIT 2', (ref, ref, ref))]
    if ref in rows:
        return ref
    if not rows:
        raise Store4Error(f'no copy {ref}')
    if len(rows) > 1:
        raise Store4Error(f'{ref} names more than one copy; give more of the id')
    return rows[0]


def copy_facts(db, copy_id):
    """The `copy show` result: source, version, digest, pending state and the line counts."""
    c = db.execute('SELECT c.*, i.born_key AS number, i.name AS set_name FROM main.copy c JOIN main.item i ON i.id=c.item_id '
                   'WHERE c.id=?', (copy_id,)).fetchone()

    def count(table, live):
        return db.execute(f'SELECT count(*) FROM main.{table} WHERE copy_id=? AND retired_at IS {"" if live else "NOT "}NULL',
                          (copy_id,)).fetchone()[0]

    offer = pending.pending_offer(db, copy_id)
    if offer and offer.get('preview'):                              # the full preview is long; the counts are what the CLI shows
        p = offer['preview']
        offer = {**offer, 'preview': dict(counts=p['counts'], not_carried_over={k: len(v) for k, v in p['not_carried_over'].items()})}
    return dict(id=c['id'], set=c['number'], name=c['set_name'], source=c['inventory_source'], version=c['inventory_version'],
                fetched_inventory_id=c['fetched_inventory_id'], digest=c['inventory_digest'], materialised_at=c['materialised_at'],
                condition=c['condition'], completeness=c['completeness'], archived_at=c['archived_at'],
                pending=offer, marked=copies.has_marks(db, copy_id),
                lines=dict(live=count('copy_part', True), retired=count('copy_part', False)),
                figures=dict(live=count('copy_figure', True), retired=count('copy_figure', False)),
                figure_lists={r[0]: r[1] for r in db.execute(
                    'SELECT inventory_source, count(*) FROM main.copy_figure WHERE copy_id=? AND retired_at IS NULL GROUP BY 1', (copy_id,))},
                changes=copies.part_list_changes(db, copy_id))


def receipt_counts(receipt):
    return dict(counts=receipt['counts'], not_carried_over={k: len(v) for k, v in receipt['not_carried_over'].items()},
                event_id=receipt['event_id'])


def add_choice(args):
    if args.rebrickable is not None:
        return {'source': 'rebrickable', 'version': args.rebrickable or None}
    return {'source': 'bricklink'} if args.bricklink else {'source': 'rebrickable_api'} if args.rebrickable_api else None


def do_copy(paths, args):
    """Run one `copy` command; the result carries `what` (the command) for the printer."""
    with open_pair(paths) as db:
        c = args.command
        if c == 'add':
            item_id = need_set(db, args.number)
            choice = add_choice(args) or copies.part_list_choices(db, item_id)['preselected']
            if choice is None:
                raise copies.NoPartList(f'set {args.number} has no part list to build a copy from')
            r = copies.create_copy(db, item_id, choice, via='cli')
            copy = r['copy']
            return dict(what='add', id=copy['id'], set=args.number, source=copy['inventory_source'], version=copy['inventory_version'],
                        digest=copy['inventory_digest'], figures=len(r['figures']), lines=len(r['parts']['rows']), pending=r.get('pending'))
        if c == 'show':
            return dict(what='show', **copy_facts(db, find_copy(db, args.copy)))
        if c == 'switch':
            copy_id, choice = find_copy(db, args.copy), parse_choice(args.choice)
            if args.preview:
                p = copies.preview_switch(db, copy_id, choice)
                return dict(what='switch', preview=True, id=copy_id, same_list=p['same_list'], counts=p['counts'],
                            not_carried_over={k: len(v) for k, v in p['not_carried_over'].items()})
            return dict(what='switch', preview=False, id=copy_id, **receipt_counts(copies.switch_part_list(db, copy_id, choice, via='cli')))
        if c == 'undo':
            r = copies.undo_switch(db, args.event, via='cli')
            return dict(what='undo', event_id=r['event_id'], undoes=r['undoes'], counts=r['counts'])
        if c == 'pending':
            words = args.args
            if len(words) > 2 or (len(words) == 2 and words[0] not in ('accept', 'cancel')):
                raise Store4Error('usage: copy pending [accept|cancel] <copy-id>')
            if not words:
                ids = [r[0] for r in db.execute('SELECT id FROM main.copy WHERE inventory_pending IS NOT NULL ORDER BY created_at, id')]
                offers = [(i, pending.pending_offer(db, i)) for i in ids]          # None: settled or cancelled meanwhile
                return dict(what='pending-list', copies=[dict(id=i, state=o['state']) for i, o in offers if o is not None])
            copy_id = find_copy(db, words[-1])
            if words[0] == 'accept':
                return dict(what='pending-accept', id=copy_id, **receipt_counts(pending.accept_pending(db, copy_id, via='cli')))
            if words[0] == 'cancel':
                return dict(what='pending-cancel', id=copy_id, **pending.cancel_pending(db, copy_id, via='cli'))
            return dict(what='pending-show', id=copy_id, pending=copy_facts(db, copy_id)['pending'])
        if c == 'settle':
            return dict(what='settle', settled=pending.settle_pending(db, via='cli'))
        if c == 'changes':
            found = copies.part_list_changes(db, find_copy(db, args.copy) if args.copy else None)
            return dict(what='changes', summary=copies.summarise_changes(found), changes=found)
        if c == 'preference':
            item_id = need_set(db, args.number)
            choice = None if args.choice == 'clear' else parse_choice(args.choice)
            return dict(what='preference', set=args.number, preference=copies.set_part_list_preference(db, item_id, choice, via='cli'))
        return dict(what='prefer-bricklink', on=copies.set_prefer_bricklink(db, args.state == 'on', via='cli'))


def show_choice(choice):
    if not choice:
        return 'none (choose a part list)'
    return choice['source'] + (f":{choice['version']}" if choice.get('version') else '')


def change_line(e, with_copy):
    what = f"figure {e['figure_item_id']}" if e['figure_id'] is not None else 'set list'
    return ((e['copy_id'][:8] + ' ' if with_copy else '') + f"{e['kind']}: {what} on {e['source']}"
            + (f" version {e['version']}" if e['version'] else '') + f", {(e['current_digest'] or '-')[:12]} -> {(e['catalogue_digest'] or '-')[:12]}"
            + f"; switch to {show_choice(e['choice'])}")


def show_offer(p, say):
    if not p:
        return
    line = f"  BrickLink list {p['state']} (job {p['job']['id']}, {p['job']['state']})"
    if p['state'] == 'ready':
        nco = p['preview']['not_carried_over']
        line += f", switch now? not carried over: retired {nco['retired']}, capped {nco['capped']}" + (', copy is marked' if p['marked'] else '')
    say(line)


def show_copy(r, say):
    what = r['what']
    if what == 'add':
        say(f"copy {r['id']}: set {r['set']} from {r['source']}" + (f" version {r['version']}" if r['version'] else '')
            + f", {r['figures']} figure line(s), {r['lines']} part line(s), digest {(r['digest'] or '-')[:12]}")
        if r['pending']:
            say(f"  BrickLink list pending: job {r['pending']['job_id']}" + (' (reused)' if r['pending']['job_reused'] else '') + ' (run `jobs drain`)')
    elif what == 'show':
        say(f"copy {r['id']}: set {r['set']} {r['name']}")
        say(f"  part list: {r['source']}" + (f" version {r['version']}" if r['version'] else '')
            + (f", fetched list {r['fetched_inventory_id']}" if r['fetched_inventory_id'] else '')
            + f", digest {(r['digest'] or '-')[:12]}, materialised {r['materialised_at']}")
        say(f"  lines: {r['lines']['live']} live, {r['lines']['retired']} retired; figures: {r['figures']['live']} live, "
            f"{r['figures']['retired']} retired" + ('; ' + ', '.join(f'{k} {v}' for k, v in sorted(r['figure_lists'].items())) if r['figure_lists'] else ''))
        say(f"  completeness {r['completeness'] or '-'}, condition {r['condition'] or '-'}, {'marked' if r['marked'] else 'no marks'}"
            + (f", archived {r['archived_at']}" if r['archived_at'] else ''))
        show_offer(r['pending'], say)
        for e in r['changes']:
            say('  ' + change_line(e, False))
    elif what == 'switch':
        say(('would switch' if r['preview'] else 'switched') + f" copy {r['id']}" + ('' if r['preview'] else f", event {r['event_id']}")
            + (' (already carries this list)' if r.get('same_list') else ''))
        say('  ' + (', '.join(f'{k} {v}' for k, v in r['counts'].items() if v) or 'no row changes'))
        say('  not carried over: ' + (', '.join(f'{k} {v}' for k, v in r['not_carried_over'].items() if v) or 'none'))
    elif what == 'undo':
        say(f"undid event {r['undoes']} (undo event {r['event_id']})")
    elif what == 'pending-list':
        for x in r['copies']:
            say(f"{x['id']}: {x['state']}")
        if not r['copies']:
            say('no copy is waiting for a BrickLink list')
    elif what == 'pending-show':
        if r['pending']:
            show_offer(r['pending'], say)
        else:
            say(f"copy {r['id']} is not waiting for a BrickLink list")
    elif what == 'pending-accept':
        say(f"accepted: copy {r['id']} switched to BrickLink's list, event {r['event_id']}")
        say('  not carried over: ' + (', '.join(f'{k} {v}' for k, v in r['not_carried_over'].items() if v) or 'none'))
    elif what == 'pending-cancel':
        say(f"cancelled the pending BrickLink list of copy {r['id']}; it stays on {r['inventory_source']} version {r['inventory_version']}")
    elif what == 'settle':
        for x in r['settled']:
            say(f"copy {x['copy_id']}: {x['outcome']}" + (f" ({x['error']})" if x.get('error') else ''))
        if not r['settled']:
            say('nothing to settle')
    elif what == 'changes':
        s = r['summary']
        say(f"{s['copies']} copies with a changed part list ({s['entries']} entries)")
        for e in r['changes']:
            say('  ' + change_line(e, True))
    elif what == 'preference':
        say(f"preference for {r['set']}: " + (show_choice(r['preference']) if r['preference'] else 'cleared'))
    else:
        say('prefer BrickLink: ' + ('on' if r['on'] else 'off'))


# ---------- output ----------

def show_job(r, say):
    step = r['step'] or {}
    ran = '' if r.get('ran', True) else ' (not run now)'
    say(f"job {r['id']} {r['kind']} {r['number']}: {r['state']}{ran}, attempt {r['attempts']}, {step.get('count', 0)} call(s)")
    if r['state'] == 'done' and r.get('result'):
        x = r['result']
        if r['kind'] == 'bricklink_subsets':
            say(f"  list {x['seq']}: {x['required_lines']} required ({x['required_total']} pieces), {x['spare_lines']} spare lines "
                f"({x['spare_total']}), {x['figure_lines']} figure lines")
            say(f"  local items created: {_counts(x['local_items_created'])}; ambiguous settled by the set {x['ambiguous_by_context']}, made local {x['ambiguous_made_local']}")
            say('  digest matches catalogue version ' + str(x['matches_version']) if x['bl_digest_matches'] else '  digest matches no catalogue version')
        else:
            say(f"  list {x['seq']}: {x['part_lines']} part lines ({x['part_total']} pieces), {x['spare_lines']} spare lines ({x['spare_total']}), "
                f"{x['figure_lines']} figure lines, {len(x['figure_lists'])} figure list(s) fetched")
            say(f"  local items created: {_counts(x['local_items_created'])}")
            say('  digest matches catalogue version ' + str(x['matches_version']) if x['matches_version'] else '  digest matches no catalogue version')
    elif r['state'] != 'done':
        say(f"  {r['error_code'] or '-'}: {r['error'] or ''}" + (f"; next try {r['retry_at']}" if r['retry_at'] else ''))


def _counts(counts):
    return ', '.join(f'{k} {v}' for k, v in counts.items() if v) or 'none'


# ---------- output (catalogue) ----------

def show_summary(s, say):
    """`s` is a summary() result."""
    say('  changes: ' + (', '.join(f'{k} {v}' for k, v in sorted(s['changes'].items())) or 'none'))
    say('  not applied: ' + (', '.join(f'{k} {v}' for k, v in sorted(s['not_applied'].items())) or 'none'))
    for kind, c in s['coverage'].items():
        say(f"  coverage {kind}: " + ', '.join(f'{k} {v}' for k, v in c.items()))


def show_part_lists(x, say):
    if x is None:
        return
    if 'error' in x:
        say(f"  copies with a changed part list: not checked ({x['error']})")
    else:
        kinds = ', '.join(f'{k} {v}' for k, v in sorted(x['by_kind'].items()))
        say(f"  {x['copies']} copies with a changed part list" + (f" ({kinds}; {x['gone']} copies whose list is gone)" if x['copies'] else ''))


def show(result, command, say):
    if command == 'status':
        cat, coll, dl = result['catalogue'], result['collection'], result['download']
        say(f"data: {result['data']}")
        if cat:
            say(f"catalogue: {cat['bytes']:,} bytes, id {cat['catalogue_id']}, high-water item {cat['item_high_water']} colour {cat['color_high_water']}")
            for b in cat['builds']:
                c = {k: v for k, v in b['counts'].items() if k in SHOWN}
                say(f"  build {b['id']} {b['kind']} {b['started_at']} mapping {b['mapping_version'] or '-'}"
                    + (' ' + ', '.join(f'{k} {v}' for k, v in c.items()) if c else ''))
            say(f"  BrickLink lists: {'loaded, ' + str(cat['bricklink_items']) + ' items' if cat['bricklink_lists_loaded'] else 'not loaded'}")
            d = cat['bl_digest']
            say(f"  bl_digest: {d['with_digest']} of {d['inventories']} inventories ({d['null']} without)")
        else:
            say('catalogue: none')
        if coll:
            say(f"collection: id binding {coll['catalogue_id']}, high-water item {coll['item_high_water']} colour {coll['color_high_water']}")
            for b in coll['activated_builds']:
                say(f"  build {b['id']} {b['kind']} activated {b['activated_at']}, reconciled {b['reconciled_at'] or 'no'}")
            if coll['last_reconcile']:
                say('  last reconcile:')
                show_summary(coll['last_reconcile'], lambda t: say('  ' + t))
            show_part_lists(coll.get('part_lists'), say)
        else:
            say('collection: none')
        say(f"newest download: {dl['directory']} ({dl['age_days']} days old)" if dl else 'newest download: none')
        return
    if command == 'download':
        return
    if 'build' in result:
        b = result['build']
        say(f"built {b.get('target')} in {b.get('seconds')} s, {b.get('bytes', 0):,} bytes")
        if result.get('moved_aside'):
            say(f"the old catalogue file was kept as {result['moved_aside']}")
    if 'bricklink_dir' in result and result['bricklink'] is None:
        say('BrickLink lists are not loaded: data/bricklink-lists/ has no directory (run `catalogue import bricklink --from DIR`)')
    if result.get('bricklink'):
        b = result['bricklink']
        say(f"BrickLink lists imported in {b.get('seconds')} s, {b.get('bytes', 0):,} bytes")
    a = result['activation']
    say(f"activated builds {a['builds'] or 'none new'}, {a['colours']} colours, {a['colour_links']} colour links")
    say('reconcile:')
    show_summary(summary(result['reconcile']), say)
    show_part_lists(result.get('part_lists'), say)


# ---------- entry ----------

def build_parser():
    root = argparse.ArgumentParser(prog='python -m brickwork.store4', description=__doc__)
    root.add_argument('--data', default='data', help='directory of brickwork.db, catalogue.db, catalogue-src/ (default: data)')
    root.add_argument('--json', action='store_true', help='print the result as JSON')
    commands = root.add_subparsers(dest='group', required=True)
    cat = commands.add_parser('catalogue').add_subparsers(dest='command', required=True)
    dl = cat.add_parser('download', help='fetch the 12 Rebrickable dump files into today\'s directory')
    dl.add_argument('--date', help='directory name, YYYY-MM-DD (default: today)')
    dl.add_argument('--force', action='store_true', help='download again although today\'s directory is complete')
    imp = cat.add_parser('import', help='build from a download, seeded from the catalogue and the collection; activate; reconcile')
    imp.add_argument('--src', help='a download directory with a manifest (default: the newest complete one)')
    sources = imp.add_subparsers(dest='source')
    bl = sources.add_parser('bricklink', help='import the BrickLink item lists, then activate and reconcile')
    bl.add_argument('--from', dest='directory', required=True, help='directory of the BrickLink catalogue XML files')
    reb = cat.add_parser('rebuild', help='build a lost catalogue from the newest download, seeded only from the collection')
    reb.add_argument('--src')
    cat.add_parser('reconcile', help='activate if needed, then reconcile')
    cat.add_parser('status')
    fetch = commands.add_parser('fetch', help='queue a fetch job for a set and run it now').add_subparsers(dest='command', required=True)
    fetchers = [fetch.add_parser('bricklink', help='BrickLink subsets list for a set the catalogue or collection holds (1 call)'),
                fetch.add_parser('rebrickable', help='Rebrickable list for a set newer than the catalogue (3 + n calls)')]
    for parser in fetchers:
        parser.add_argument('number', help='the set number, e.g. 6081-1')
    jobs_cmd = commands.add_parser('jobs', help='list the jobs')
    jobs_cmd.set_defaults(group='jobs')
    jobs_sub = jobs_cmd.add_subparsers(dest='command')
    drain = jobs_sub.add_parser('drain', help='run the jobs that may run now')
    drain.add_argument('--limit', type=int, default=100)
    copy = commands.add_parser('copy', help='add, show and switch copies and their part lists').add_subparsers(dest='command', required=True)
    add = copy.add_parser('add', help="add a copy of a set (default part list: the picker's preselection)")
    add.add_argument('number', help='the set number, e.g. 6081-1')
    pick = add.add_mutually_exclusive_group()
    pick.add_argument('--rebrickable', nargs='?', type=int, const=0, metavar='VERSION', help="Rebrickable's list (the latest without VERSION)")
    pick.add_argument('--bricklink', action='store_true', help="BrickLink's list (fetched later when none is stored; needs a key)")
    pick.add_argument('--rebrickable-api', action='store_true', help='the fetched Rebrickable list')
    show_c = copy.add_parser('show', help="a copy's part list, pending state, counts and changes")
    show_c.add_argument('copy', help='the copy id or a unique start of it')
    switch = copy.add_parser('switch', help='switch a copy to another part list in place')
    switch.add_argument('copy')
    switch.add_argument('choice', help='rebrickable, rebrickable:N, bricklink or rebrickable-api')
    switch.add_argument('--preview', action='store_true', help='show what would change, write nothing')
    undo = copy.add_parser('undo', help='undo a part list switch by its event id')
    undo.add_argument('event', type=int)
    pend = copy.add_parser('pending', help="copies waiting for BrickLink's list; `pending accept|cancel <copy>`, `pending <copy>`")
    pend.add_argument('args', nargs='*', metavar='[accept|cancel] COPY')
    copy.add_parser('settle', help='settle the copies waiting on finished jobs')
    changes = copy.add_parser('changes', help='copies and figure lines whose part list changed (read-only)')
    changes.add_argument('copy', nargs='?')
    pref = copy.add_parser('preference', help='the part list new copies of a set use')
    pref.add_argument('number')
    pref.add_argument('choice', help='rebrickable, rebrickable:N, bricklink or clear')
    pb = copy.add_parser('prefer-bricklink', help="the global switch: prefer BrickLink's list when a key exists")
    pb.add_argument('state', choices=('on', 'off'))
    mig = commands.add_parser('migrate', help='migrate a 3.3 collection file into a new 4.0 file: write, prove, report, publish only on PASS')
    mig.add_argument('--in', dest='src', required=True, help='the 3.3 collection file (read-only; the 3.3 app must be stopped, or this a copy)')
    mig.add_argument('--catalogue', required=True, help='the catalogue.db the mint resolves against')
    mig.add_argument('--mappings', required=True, help='the mappings directory the catalogue was built with (every file is hashed)')
    mig.add_argument('--out', required=True, help='the 4.0 file to create (must not exist)')
    mig.add_argument('--report', required=True, help='the report folder (new or empty)')
    mig.add_argument('--pin', help='proof.json or summary.md of an earlier run: refuse unless the catalogue and the mapping files are identical')
    mig.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='print the result as JSON')
    for parser in (bl, *cat.choices.values(), *fetchers, jobs_cmd, drain, *copy.choices.values()):
        parser.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='print the result as JSON')
        parser.add_argument('--data', default=argparse.SUPPRESS, help='as before the command')
    return root


# exit codes of `migrate` (argparse keeps 2 for a usage error, 1 is any other failure)
EXIT_PASS, EXIT_FAILED_PROOF, EXIT_REFUSED, EXIT_NEEDS_DECISION = 0, 10, 11, 12


def attach_line(counts, kind, label):
    c = counts.get(kind, {'attached': 0, 'total': 0})
    return f'{label} {c["attached"]}/{c["total"]}' + (f' ({100 * c["attached"] / c["total"]:.1f}%)' if c['total'] else '')


def do_migrate(args, out):
    """Exit codes: 0 PASS and published; 10 the proof FAILED (report written, no output); 11 refused before writing (pin, existing output,
    report folder in use, a 3.3 file with a WAL); 12 3.3 rows need a decision (listed); 1 any other failure."""
    try:
        res = run_migration(args.src, args.catalogue, args.mappings, args.out, args.report, pin=args.pin)
    except NeedsDecision as exc:
        print(f'needs a decision: {exc}', file=sys.stderr)
        for row in exc.rows[:20]:
            print(f'  {row.get("why")}', file=sys.stderr)
        return EXIT_NEEDS_DECISION
    except (Refused, FileExistsError) as exc:
        print(f'refused: {exc}', file=sys.stderr)
        return EXIT_REFUSED
    except (Store4Error, OSError, ValueError, sqlite3.Error) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    counts = res.migration.attach_counts()
    parts = {n: p['result'] for n, p in res.proof['parts'].items()}
    if getattr(args, 'json', False):
        print(json.dumps(dict(result=res.result, published=res.published, out=str(res.out), report=str(res.report), digest=res.digest, proof=parts,
                              attach=counts, rows=res.migration.counts(), seconds=round(res.seconds, 1)), indent=1, sort_keys=True), file=out)
    else:
        rows = res.migration.counts()
        print(f'proof {res.result}: ' + ', '.join(f'{n} {v}' for n, v in parts.items()), file=out)
        print('rows: ' + ', '.join(f'{k} {rows[k]}' for k in ('copy', 'copy_figure', 'copy_part', 'stock', 'stock_part', 'wish', 'price_observation') if k in rows), file=out)
        print('attached: ' + ', '.join(attach_line(counts, k, label) for k, label in (('copy', 'copies'), ('figure', 'figure lines'), ('loose_figure', 'loose figures'))), file=out)
        print(f'report: {res.report} (digest {res.digest[:16]})', file=out)
        print(f'{res.out} published' if res.published else 'NOT published', file=out)
    return EXIT_PASS if res.result == 'PASS' else EXIT_FAILED_PROOF


def main(argv=None, *, fetch=http_fetch, mappings_dir=MAPPINGS_DIR, now=None, out=None, http=None, clock=None):
    args = build_parser().parse_args(argv)
    out = out or sys.stdout
    if args.group == 'migrate':
        return do_migrate(args, out)
    paths = Paths(args.data)
    say = (lambda *a: None) if args.json else (lambda *a: print(*a, file=out, flush=True))
    command = args.command
    try:
        if args.group == 'copy':
            result = do_copy(paths, args)
        elif args.group == 'fetch':
            result = do_fetch(paths, command, args.number, http=http, clock=clock)
        elif args.group == 'jobs':
            result = do_drain(paths, http=http, clock=clock, limit=args.limit) if command == 'drain' else do_jobs(paths)
        elif command == 'download':
            result = download(paths, day=args.date, force=args.force, fetch=fetch, say=lambda *a: print(*a, file=sys.stderr if args.json else out, flush=True))
        elif command == 'import' and args.source == 'bricklink':
            result = do_import_bricklink(paths, args.directory, now=now)
        elif command == 'import':
            result = do_import(paths, args.src, mappings_dir=mappings_dir, now=now)
        elif command == 'rebuild':
            result = do_rebuild(paths, args.src, mappings_dir=mappings_dir, now=now)
        elif command == 'reconcile':
            result = do_reconcile(paths)
        else:
            result = do_status(paths)
        if args.group == 'catalogue' and command in ('import', 'rebuild', 'reconcile'):
            result['part_lists'] = part_list_summary(paths)
    except (Store4Error, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps(dict(error=str(exc))) if args.json else f'error: {exc}', file=out if args.json else sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True, default=str), file=out)
    elif args.group == 'copy':
        show_copy(result, say)
    elif args.group == 'fetch':
        show_job(result, say)
    elif args.group == 'jobs':
        for r in result.get('jobs') or result.get('ran') or []:
            show_job(r, say)
        if not (result.get('jobs') or result.get('ran')):
            say('no jobs' if 'jobs' in result else 'no job was due')
    else:
        show(result, command, say)
    return 1 if args.group == 'fetch' and result['state'] != 'done' else 0
