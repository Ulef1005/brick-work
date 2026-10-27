"""Encrypted source-key store: one service for the API and the Catalogues & keys page.

Keys come from the environment first, then from `source_key` (Fernet, secret from
BW_SECRET_KEY, see secrets.py). Only `configured`, `origin` and `saved_at` ever leave
this module; values and ciphertext are never returned, logged, audited or put in an error.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3

from . import errors, secrets
from . import undo as undoing
from .transaction import transaction

# Environment variable names per keyed source, in the order the clients use them.
ENV = {
    'bricklink': ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET',
                  'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET'),
    'rebrickable': ('BW_REBRICKABLE_API_KEY',),
    'brickset': ('BW_BRICKSET_API_KEY',),
}
# Per-user collection credentials (#10): only the site's token or hash, never a password.
USER_ENV = {
    'rebrickable_user': ('BW_REBRICKABLE_USER_TOKEN',),
    'brickset_user': ('BW_BRICKSET_USER_HASH',),
}
KEYLESS = ('brickognize', 'bricklink_catalogue')
LABELS = {'bricklink': 'BrickLink', 'rebrickable': 'Rebrickable', 'brickset': 'Brickset',
          'rebrickable_user': 'Rebrickable user token', 'brickset_user': 'Brickset user hash'}


def _env(source):
    return ENV.get(source) or USER_ENV[source]
VALUE = re.compile(r'[\x21-\x7e]{8,256}')


def fields(source):
    """Public input names: `key` for single-key sources, else the env name without its prefix."""
    if source in USER_ENV:
        return ('token',) if source == 'rebrickable_user' else ('hash',)
    names = _env(source)
    if len(names) == 1:
        return ('key',)
    prefix = 'BW_' + source.upper() + '_'
    return tuple(n.removeprefix(prefix).lower() for n in names)


def field_map():
    """Input names per keyed source, for the Catalogues & keys form."""
    return {source: fields(source) for source in ENV}


def known(source):
    """A keyed source; raises the typed error a client should see otherwise."""
    if source in ENV:
        return source
    if source in KEYLESS:
        raise errors.ValidationFailed('This source needs no key')
    raise errors.NotFound('Unknown source')


def _stored(db, source, *, live=True):
    if db is None:
        return None
    try:
        return db.execute('SELECT source,ciphertext,saved_at,archived_at FROM source_key WHERE source=?'
                          + (' AND archived_at IS NULL' if live else ''), (source,)).fetchone()
    except sqlite3.OperationalError:
        return None  # A store that could not be upgraded has no key table yet.


def _env_complete(names):
    return bool(names) and all(os.environ.get(n) for n in names)


def stored_states(db):
    """Every live stored key's saved_at in one query, for lists."""
    try:
        return {r[0]: r[1] for r in db.execute('SELECT source,saved_at FROM source_key WHERE archived_at IS NULL')}
    except sqlite3.OperationalError:
        return {}


def state(db, source, names=None, saved=None):
    """Key status without decrypting anything: configured, origin (env|stored|null), saved_at."""
    names = ENV.get(source, ()) if names is None else names
    if not names and source in KEYLESS:
        return dict(configured=True, origin=None, saved_at=None)
    if saved is not None:
        stored = {'saved_at': saved[source]} if source in saved else None
    else:
        stored = _stored(db, source) if source in ENV or source in USER_ENV else None
    env = _env_complete(names)
    return dict(configured=env or stored is not None, origin='env' if env else 'stored' if stored else None,
                saved_at=stored['saved_at'] if stored else None)


def configured(db, source, names):
    if not names:
        return True
    return state(db, source, names)['configured']


def credentials(db, source, names, *, label=None):
    """Resolve key values for a client: complete environment first, then the decrypted store."""
    from .sources.base import SourceNotConfigured
    label = label or LABELS.get(source, source)
    if _env_complete(names):
        return tuple(os.environ[n] for n in names)
    stored = _stored(db, source)
    if stored is not None:
        try:
            bundle = json.loads(secrets.decrypt(stored['ciphertext']))
            values = tuple(bundle[n] for n in names)
        except (errors.BrickWorkError, KeyError, ValueError, TypeError):
            # Fixed text: a wrong BW_SECRET_KEY or damaged row must not say more.
            raise SourceNotConfigured(label + ' stored key cannot be used', source=source) from None
        secrets.remember(*values)
        return values
    raise SourceNotConfigured(label + ' key is not configured', source=source)


def known_user(source):
    """A per-user credential slot (`rebrickable_user`, `brickset_user`)."""
    if source in USER_ENV:
        return source
    raise errors.NotFound('Unknown source')


def clean(source, payload):
    """Validate write-only input; messages never echo a submitted value."""
    if source not in USER_ENV:
        known(source)
    expected = fields(source)
    if not isinstance(payload, dict) or set(payload) != set(expected):
        raise errors.ValidationFailed('Supply ' + ', '.join(expected))
    values = {}
    for field in expected:
        value = payload[field]
        value = value.strip() if isinstance(value, str) else value
        if not isinstance(value, str) or not VALUE.fullmatch(value):
            raise errors.ValidationFailed('Enter a valid ' + field.replace('_', ' '))
        values[field] = value
    return values


def save(db, source, payload, receipt=None):
    """Encrypt and store a key bundle (replace allowed). Returns the public key state.

    `receipt`, when a list, gets the id of the audit event this call wrote.
    """
    values = clean(source, payload)
    bundle = dict(zip(_env(source), values.values()))
    ciphertext = secrets.encrypt(json.dumps(bundle, sort_keys=True))  # disabled without BW_SECRET_KEY
    secrets.remember(*bundle.values())
    stamp = _now()
    with transaction(db):
        old = _stored(db, source, live=False)
        if old is not None:
            db.execute('INSERT OR REPLACE INTO source_key_previous(source,ciphertext,saved_at,archived_at) VALUES(?,?,?,?)',
                       (source, old['ciphertext'], old['saved_at'], old['archived_at']))
            db.execute('UPDATE source_key SET ciphertext=?,saved_at=?,archived_at=NULL WHERE source=?',
                       (ciphertext, stamp, source))
        else:
            db.execute('DELETE FROM source_key_previous WHERE source=?', (source,))
            db.execute('INSERT INTO source_key(source,ciphertext,saved_at) VALUES(?,?,?)', (source, ciphertext, stamp))
        event = _audit(db, source, 'save', dict(source=source, saved_at=stamp, archived_at=None,
                       previous=None if old is None else dict(saved_at=old['saved_at'], archived_at=old['archived_at'])))
        if receipt is not None:
            receipt.append(event)
    return state(db, source)


def archive(db, source, receipt=None):
    """Archive the stored key (it stops being used); Undo restores it."""
    if source not in USER_ENV:
        known(source)
    stamp = _now()
    with transaction(db):
        row = _stored(db, source)
        if row is None:
            raise errors.NotFound('No stored key')
        db.execute('UPDATE source_key SET archived_at=? WHERE source=?', (stamp, source))
        event = _audit(db, source, 'archive', dict(source=source, saved_at=row['saved_at'], archived_at=stamp, previous=None))
        if receipt is not None:
            receipt.append(event)
    return state(db, source)


def _undo_key(db, event, via, actor):
    """Reverse one save or archive event (`undo.register('source_key', ...)`); a later change to the key blocks it."""
    source, field = event['entity_id'], event['field']
    value = json.loads(event['new_value'])
    if source not in ENV and source not in USER_ENV or value.get('source') != source:
        raise errors.NotUndoable()
    row = _stored(db, source, live=False)
    if row is None:
        raise ValueError('Item changed · undo the later save first')
    if field == 'archive':
        if row['archived_at'] != value['archived_at'] or row['saved_at'] != value['saved_at']:
            raise ValueError('Item changed · undo the later save first')
        db.execute('UPDATE source_key SET archived_at=NULL WHERE source=?', (source,))
    elif field == 'save':
        if row['archived_at'] is not None or row['saved_at'] != value['saved_at']:
            raise ValueError('Item changed · undo the later save first')
        previous = db.execute('SELECT * FROM source_key_previous WHERE source=?', (source,)).fetchone()
        if value['previous'] is None:
            db.execute('UPDATE source_key SET archived_at=? WHERE source=?', (_now(), source))
        elif previous is None or previous['saved_at'] != value['previous']['saved_at']:
            raise ValueError('The earlier key is no longer available')
        else:
            db.execute('UPDATE source_key SET ciphertext=?,saved_at=?,archived_at=? WHERE source=?',
                       (previous['ciphertext'], previous['saved_at'], previous['archived_at'], source))
            db.execute('DELETE FROM source_key_previous WHERE source=?', (source,))
    else:
        raise errors.NotUndoable()
    from .admin import audit
    audit(db, 'source_key:' + source, 'undo', new=event['id'], via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('source_key', 'save', _undo_key, admin=True)
undoing.register('source_key', 'archive', _undo_key, admin=True)


def undo(db, event_id, **options):
    """Reverse one save or archive receipt by its event id (`core.undo.undo_event`)."""
    return undoing.undo_event(db, event_id, **options)


def provider(path):
    """The credential provider for `store4.keys` (M.8a): the environment first, then the encrypted `source_key` table.

    `path` is the collection file, or a callable returning it (looked up at call time, so the app's configuration applies).
    A source's credentials come from the environment only when all of its variables are set (as `credentials` does), else from the
    stored bundle; a missing, archived, undecryptable or unreadable entry is simply "not configured" (None), never an error text."""
    where = {name: source for source, names in {**ENV, **USER_ENV}.items() for name in names}

    def get(name):
        source = where.get(name)
        if source is None:
            return os.environ.get(name) or None
        names = _env(source)
        if _env_complete(names):
            return os.environ[name]
        location = path() if callable(path) else path
        try:
            with closing(sqlite3.connect(Path(location).resolve().as_uri() + '?mode=ro', uri=True)) as db:
                db.row_factory = sqlite3.Row
                stored = _stored(db, source)
            if stored is None:
                return None
            value = json.loads(secrets.decrypt(stored['ciphertext'])).get(name)
        except (sqlite3.Error, OSError, ValueError, TypeError, errors.BrickWorkError):
            return None
        if value:
            secrets.remember(value)
        return value or None
    return get


def install(path):
    """Make `provider(path)` the credential source of the 4.0 fetchers. Idempotent; the app calls it once at start."""
    from ..store4 import keys as store4_keys
    store4_keys.set_key_provider(provider(path))


def check(db, source, **options):
    """One budgeted call that proves the key works. The result carries no key material."""
    known(source)
    from .sources.base import now
    if source == 'bricklink':
        from .sources.bricklink import BrickLink as client
    elif source == 'rebrickable':
        from .sources.rebrickable import Rebrickable as client
    else:
        from .sources.brickset import Brickset as client
    client(db, **options).check_key()
    return dict(source=source, ok=True, checked_at=now().isoformat())


def _now():
    from .sources.base import now
    return now().isoformat()


def _audit(db, source, field, receipt):
    from .admin import audit
    from .audit_bundle import CAPTURE
    audit(db, 'source_key:' + source, field, new=receipt)
    return db.execute('SELECT last_insert_rowid()').fetchone()[0] if CAPTURE.get() is None else None


def strip(snapshot):
    """Remove every stored key (live, archived, previous) from an in-memory export copy.

    secure_delete zeroes the freed pages and VACUUM rewrites the file, so no ciphertext
    survives in the serialised bytes.
    """
    snapshot.execute('PRAGMA secure_delete=ON')
    # Audit rows of key changes carry only metadata, but an older or foreign row must not leak either.
    # The trigger is dropped only while blanking, then recreated from the snapshot's own DDL.
    saved = snapshot.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='event_no_update'").fetchone()
    snapshot.execute('DROP TRIGGER IF EXISTS event_no_update')
    snapshot.execute("UPDATE event SET old_value=NULL,new_value=NULL WHERE entity_kind='source_key'")
    if saved:
        snapshot.execute(saved[0])
    for table in ('source_key', 'source_key_previous'):
        try:
            snapshot.execute('DELETE FROM ' + table)
        except sqlite3.OperationalError:
            pass
    snapshot.commit()
    snapshot.execute('VACUUM')
