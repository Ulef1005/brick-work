"""UI-12j: which keys and catalogues are missing, for the first-run path and for key-gated actions.

Reads only key status (configured or not), never a key value.
"""
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


def catalogue_loaded():
    from ..core.connect import catalogue_path
    from .admin_ops import brickwork_path
    try:
        return catalogue_path(brickwork_path()).is_file()
    except (sqlite3.Error, OSError, ValueError):
        return False


def first_run(can_edit):
    """The three steps of 12j with their state: done, current or waiting."""
    keyed = any(key_states().values())
    loaded = catalogue_loaded()
    states = ['done' if keyed else 'current']
    states.append('done' if loaded else 'current' if keyed else 'waiting')
    states.append('current' if keyed and loaded and can_edit else 'waiting')
    # 4 (#11): bring a BrickTracker collection over; needs only the catalogue for BrickLink names.
    states.append('current' if loaded and can_edit else 'waiting')
    return dict(steps=states, keyed=keyed, loaded=loaded)
