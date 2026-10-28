"""UI-12j: which keys and catalogues are missing, for the first-run path and for key-gated actions.

Reads only key status (configured or not), never a key value.
"""
from datetime import date
import sqlite3

from flask import g

from ..core import keys


def _database():
    from ..core.admin import database
    from .admin_ops import brickwork_path
    return database(brickwork_path(), read_only=True, require_catalogue=False)


def key_states():
    """Per keyed source: True when a key is configured. Cached for the request; unreadable store counts as not set."""
    cached = g.get('bw_key_states')
    if cached is None:
        try:
            with _database() as db:
                cached = {source: bool(keys.state(db, source)['configured']) for source in keys.ENV}
        except (sqlite3.Error, OSError, ValueError):
            cached = {source: False for source in keys.ENV}
        g.bw_key_states = cached
    return cached


def key_missing(source):
    """The display name of the key an action needs when it is not configured, else None."""
    if source in keys.ENV and not key_states().get(source):
        return keys.LABELS.get(source, source.capitalize())
    return None


def catalogue_file():
    from ..core.connect import catalogue_path
    from .admin_ops import brickwork_path
    try:
        return catalogue_path(brickwork_path()).is_file()
    except (sqlite3.Error, OSError, ValueError):
        return False


def catalogue_loaded():
    """The catalogue is beside the collection and a build of it is active in the collection (design 6.1 step 3)."""
    if not catalogue_file():
        return False
    try:
        with _database() as db:
            return db.execute('SELECT 1 FROM main.catalogue_build LIMIT 1').fetchone() is not None
    except (sqlite3.Error, OSError, ValueError):
        return False


def first_run(can_edit):
    """The steps of 12j with their state: done, current or waiting. Keys are optional (design 6.1): the catalogue downloads without one, so
    step 2 never waits on step 1. `file` is a catalogue that is there but not active yet; `today` offers today's download on disk; `job` is the
    catalogue job to show (running, failed or interrupted)."""
    from . import admin_ops, catalogue_jobs
    from ..store4 import cli
    keyed = any(key_states().values())
    loaded = catalogue_loaded()
    paths = admin_ops.store4_paths()
    found = cli.newest_download(paths)
    job = catalogue_jobs.read(paths)
    states = ['done' if keyed else 'optional', 'done' if loaded else 'current']
    states.append('current' if loaded and can_edit else 'waiting')
    # 4 (#11): bring a BrickTracker collection over; needs only the catalogue for BrickLink names.
    states.append('current' if loaded and can_edit else 'waiting')
    return dict(steps=states, keyed=keyed, loaded=loaded, file=not loaded and catalogue_file(), can_edit=can_edit,
                today=bool(found and found[0].name == date.today().isoformat()),
                job=job if job and job['state'] in ('running', 'failed', 'interrupted') and not loaded else None)
