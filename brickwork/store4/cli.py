"""`python -m brickwork.store4 catalogue download|import|rebuild|reconcile|status` (design 6.1, 6.2, 6.6; issue #104, M.2e).

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

from .activate import activate
from .builder import build
from .bricklink_list import import_bricklink
from .connect import _uri, connect
from .dump import HEADERS
from .errors import BuildBusy, Store4Error
from .mappings import MAPPINGS_DIR
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


def summary(rec):
    return dict(changes=rec.get('changes', {}), not_applied={k: len(v) for k, v in rec.get('not_applied', {}).items()},
                coverage=rec.get('coverage', {}), events=rec.get('events'))


# ---------- output ----------

def show_summary(s, say):
    """`s` is a summary() result."""
    say('  changes: ' + (', '.join(f'{k} {v}' for k, v in sorted(s['changes'].items())) or 'none'))
    say('  not applied: ' + (', '.join(f'{k} {v}' for k, v in sorted(s['not_applied'].items())) or 'none'))
    for kind, c in s['coverage'].items():
        say(f"  coverage {kind}: " + ', '.join(f'{k} {v}' for k, v in c.items()))


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
    for parser in (bl, *cat.choices.values()):
        parser.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='print the result as JSON')
        parser.add_argument('--data', default=argparse.SUPPRESS, help='as before the command')
    return root


def main(argv=None, *, fetch=http_fetch, mappings_dir=MAPPINGS_DIR, now=None, out=None):
    args = build_parser().parse_args(argv)
    out = out or sys.stdout
    paths = Paths(args.data)
    say = (lambda *a: None) if args.json else (lambda *a: print(*a, file=out, flush=True))
    command = args.command
    try:
        if command == 'download':
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
    except (Store4Error, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps(dict(error=str(exc))) if args.json else f'error: {exc}', file=out if args.json else sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True, default=str), file=out)
    else:
        show(result, command, say)
    return 0
