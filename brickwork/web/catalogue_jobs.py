"""The catalogue jobs of Tools & Admin (design 6.1, 6.2, 6.6; M.10c): Re-download, Rebuild, Reconcile and loading the BrickLink item lists.

One job at a time per data folder, run on a thread of the web process through the same core calls as `python -m brickwork.store4 catalogue ...`
(`cli.download`, `builder.build`, `cli.do_rebuild`, `cli.do_import_bricklink`, `cli.activate_and_reconcile`). The job's state is one small JSON
file beside the collection (`catalogue-job.json`), so any worker of the app can show it and a restart cannot leave a running job showing
forever: a state whose process is gone reads as interrupted. The builds hold their own file locks, so a second job from the command line
is refused by the core, not by this file."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import itertools
import threading

from ..store4 import cli, status
from ..store4.connect import connect
from ..store4.errors import Store4Error, public_text

FILE = 'catalogue-job.json'
KINDS = {'redownload': 'Re-download', 'rebuild': 'Rebuild', 'reconcile': 'Reconcile', 'lists': 'Load BrickLink item lists'}
STEPS = {'redownload': ('Downloading the Rebrickable files', 'Building the catalogue', 'Reconciling the collection'),
         'rebuild': ('Rebuilding the catalogue from the downloaded files', 'Reconciling the collection'),
         'reconcile': ('Reconciling the collection',),
         'lists': ('Building the catalogue with the lists', 'Reconciling the collection')}
_PARTS = itertools.count()
FETCH = None                                              # tests and frames put a fetch function here; None is the real download


class Busy(Store4Error):
    """A catalogue job is already running."""


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _path(paths):
    return Path(paths.data) / FILE


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read(paths):
    """The last job's state, or None. A job marked running whose process is gone is returned as `interrupted`."""
    try:
        state = json.loads(_path(paths).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get('kind') not in KINDS:
        return None
    if state.get('state') == 'running' and not _alive(int(state.get('pid') or 0)):
        state = dict(state, state='interrupted', error='Brick Work stopped while this was running. Nothing was half written: the old catalogue is still in place.')
    state['label'] = KINDS[state['kind']]
    state['steps'] = list(STEPS[state['kind']])
    return state


def _write(paths, state):
    target = _path(paths)
    part = target.with_name(f'{FILE}.{os.getpid()}.{threading.get_ident()}.{next(_PARTS)}.part')      # one name per writer: two never share a file
    part.write_text(json.dumps(state, sort_keys=True), encoding='utf-8')
    os.replace(part, target)


@contextmanager
def _admission(paths):
    """One admission at a time across processes: the check that no job runs and the write of the new state happen under `catalogue-job.lock`
    (flock, so it also holds between threads of one process). The app runs one gunicorn worker today; the lock keeps that true if it changes."""
    lock = open(Path(paths.data) / (FILE.removesuffix('.json') + '.lock'), 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        lock.close()                                          # closing releases the flock


def start(paths, kind, *, folder=None, background=True):
    """Start a job. Raises `Busy` while another one runs, `Store4Error` when its inputs are missing. With `background=False` it runs
    here and returns the final state (tests); otherwise it returns the first state at once."""
    if kind not in KINDS:
        raise Store4Error(f'unknown catalogue job {kind!r}')
    with _admission(paths):
        current = read(paths)
        if current and current['state'] == 'running':
            raise Busy(f"{current['label']} is running already; wait for it to finish")
        directory = None
        if kind == 'rebuild' and cli.newest_download(paths) is None:
            raise Store4Error('there is no complete Rebrickable download to rebuild from; run Re-download first')
        if kind == 'reconcile' and not paths.catalogue.exists():
            raise Store4Error('there is no catalogue file yet; run Re-download first')
        if kind == 'lists':
            names = [d.name for d in paths.lists.iterdir() if d.is_dir()] if paths.lists.is_dir() else []
            if not names:
                raise Store4Error(f'there is no folder of BrickLink lists under {paths.lists}')
            folder = folder or sorted(names)[-1]
            if folder not in names:                      # a folder name from the list only, never a typed path
                raise Store4Error('choose one of the folders listed')
            if not paths.catalogue.exists():
                raise Store4Error('build the catalogue first: the lists are added to it')
            directory = paths.lists / folder
        state = dict(kind=kind, state='running', pid=os.getpid(), started_at=_now(), finished_at=None, step=0, folder=folder, error=None, result=None)
        _write(paths, state)
    if not background:
        return _run(paths, state, directory)
    threading.Thread(target=_run, args=(paths, state, directory), daemon=True, name='catalogue-job').start()
    return read(paths)


def _step(paths, state, index):
    state['step'] = index
    _write(paths, state)


def _run(paths, state, directory):
    kind = state['kind']
    try:
        result = {}
        if kind == 'redownload':
            got = cli.download(paths, fetch=FETCH or cli.http_fetch, say=lambda *_: None)
            result['download'] = dict(downloaded=got['downloaded'], files=got['files'])
            _step(paths, state, 1)
            source = cli.pick_source(paths, None)
            built = cli.build(source, paths.catalogue, collection=paths.collection_if_any(), app_version=cli.app_version(),
                              mappings_dir=cli.MAPPINGS_DIR, local_dir=paths.local_dir())
            result['build'] = _build(built)
            _step(paths, state, 2)
            result['reconcile'] = _reconcile(paths)
        elif kind == 'rebuild':
            out = cli.do_rebuild(paths)
            result['build'] = _build(out['build'])
            result['moved_aside'] = Path(out['moved_aside']).name if out.get('moved_aside') else None
            result['reconcile'] = cli.summary(out['reconcile']) if out.get('reconcile') else None
            _step(paths, state, 1)
        elif kind == 'lists':
            out = cli.import_bricklink(paths.catalogue, directory, collection=paths.collection_if_any(), app_version=cli.app_version())
            result['lists'] = dict(counts={k: v for k, v in out['counts'].items() if isinstance(v, (int, str))}, files=[f['name'] for f in out['files']])
            _step(paths, state, 1)
            result['reconcile'] = _reconcile(paths)
        else:
            result['reconcile'] = _reconcile(paths)
        state.update(state='done', result=result)
    except Exception as exc:                              # shown on the page in words; the details stay in the log
        state.update(state='failed', error=_words(exc))
    state['finished_at'] = _now()
    _write(paths, state)
    return read(paths)


def _words(exc):
    return public_text(exc, what='the catalogue job')


def _build(built):
    counts = built.get('counts') or {}
    return {k: counts[k] for k in ('live_items', 'items', 'colours', 'new_items', 'new_colours', 'retired_items', 'retired_colours',
                                   'retired_inventories', 'adopted', 'sets', 'parts', 'minifigs') if k in counts}


def _reconcile(paths):
    activated, reconciled = cli.activate_and_reconcile(paths)
    return cli.summary(reconciled)


def result_view(paths, state):
    """What a finished job changed, for the page: the counts of the build, reconcile's changes and what it did not apply, and the copies whose
    part list changed (read now, from the files)."""
    if not state or state.get('state') != 'done':
        return None
    out = dict(state['result'] or {})
    if paths.collection.exists() and paths.catalogue.exists():
        with closing(connect(paths.collection, paths.catalogue, read_only=True)) as db:
            out['copies'], out['copies_total'] = status.changed_copies(db)
    return out
