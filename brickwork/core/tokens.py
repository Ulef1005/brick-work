"""Scoped bearer credentials. Secrets are generated once; audit contains metadata only."""
from .transaction import transaction
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid

from . import errors
from .admin import audit
from .sources.base import now

SCOPES = ('read', 'write', 'admin')
PUBLIC = 'id name scopes created_at expires_at last_used_at revoked_at'.split()


def public(row):
    result = {key: row[key] for key in PUBLIC}
    result['scopes'] = json.loads(result['scopes'])
    return result


def listing(db):
    return [public(row) for row in db.execute('SELECT * FROM api_tokens ORDER BY name,id')]


def create(db, name, scopes, expires_at=None):
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or name.strip() == 'bootstrap':
        raise errors.ValidationFailed('Enter a token name of 1 to 80 characters; bootstrap is reserved')
    if not isinstance(scopes, list) or not scopes or any(s not in SCOPES for s in scopes):
        raise errors.ValidationFailed('Choose read, write or admin scopes')
    if expires_at is not None:
        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry.tzinfo is None or expiry <= now():
                raise ValueError()
            expires_at = expiry.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            raise errors.ValidationFailed('Expiry must be a future timestamp with timezone') from None
    identifier, secret = str(uuid.uuid4()), secrets.token_urlsafe(32)
    try:
        with transaction(db):
            db.execute('INSERT INTO api_tokens VALUES(?,?,?,?,?,?,NULL,NULL)', (
                identifier, name.strip(), hashlib.sha256(secret.encode()).hexdigest(),
                json.dumps(sorted(set(scopes), key=SCOPES.index)), now().isoformat(), expires_at))
            token = public(db.execute('SELECT * FROM api_tokens WHERE id=?', (identifier,)).fetchone())
            audit(db, 'bw_token', 'create', new=token)
            event = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    except sqlite3.IntegrityError:
        raise errors.Conflict('Token name already exists') from None
    return {'token': token, 'secret': secret}, event


def revoke(db, identifier):
    with transaction(db):
        row = db.execute('SELECT * FROM api_tokens WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise errors.NotFound('Token not found')
        if row['revoked_at']:
            raise errors.Conflict('Token is already revoked')
        db.execute('UPDATE api_tokens SET revoked_at=? WHERE id=?', (now().isoformat(), identifier))
        token = public(db.execute('SELECT * FROM api_tokens WHERE id=?', (identifier,)).fetchone())
        audit(db, 'bw_token', 'revoke', old=public(row), new=token)
        event = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    return token, event


def authenticate(db, supplied, bootstrap=''):
    # Hash both sides to fixed-length values before the constant-time comparison.
    digest = hashlib.sha256(supplied.encode()).hexdigest()
    env_match = hmac.compare_digest(digest, hashlib.sha256(bootstrap.encode()).hexdigest())
    if bootstrap and supplied and env_match:
        return {'name': 'bootstrap', 'scopes': ['admin'], 'expires_at': None}
    row = db.execute('SELECT * FROM api_tokens WHERE hash=?', (digest,)).fetchone()
    valid_hash = hmac.compare_digest(digest, row['hash'] if row else '0' * 64)
    if not bootstrap and not db.execute('SELECT 1 FROM api_tokens LIMIT 1').fetchone():
        raise errors.ApiDisabled()
    if not supplied or not row or not valid_hash or row['revoked_at']:
        raise errors.Unauthorized()
    current = now()
    if row['expires_at'] and datetime.fromisoformat(row['expires_at']) <= current:
        raise errors.Unauthorized()
    if not row['last_used_at'] or datetime.fromisoformat(row['last_used_at']) <= current - timedelta(minutes=1):
        with db:
            db.execute('UPDATE api_tokens SET last_used_at=? WHERE id=? AND (last_used_at IS NULL OR last_used_at<=?)',
                       (current.isoformat(), row['id'], (current - timedelta(minutes=1)).isoformat()))
    return public(row)


def permits(identity, scope):
    return max(SCOPES.index(s) for s in identity['scopes']) >= SCOPES.index(scope)


def undo(db, event_id, operation):
    """Undo credential changes without putting credential hashes in audit receipts."""
    import re
    from .sources.base import AUDIT_ACTOR
    if not operation:
        raise errors.IdempotencyKeyRequired()
    if not re.fullmatch(r'[A-Za-z0-9-]{1,80}', operation):
        raise errors.BadRequest('Invalid Idempotency-Key')
    with transaction(db):
        actor = AUDIT_ACTOR.get()
        replay = db.execute("SELECT * FROM events WHERE entity='bw_token' AND field=? AND actor IS ? AND at>=? ORDER BY id DESC LIMIT 1",
                            ('undo:' + operation, actor, (now() - timedelta(days=30)).isoformat())).fetchone()
        if replay:
            receipt = json.loads(replay['new_value'])
            if receipt['event_id'] != event_id:
                raise errors.IdempotencyConflict()
            return receipt['response'], replay['id'], True
        event = db.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        if not event:
            raise errors.NotFound('Event not found')
        if event['entity'] != 'bw_token' or event['field'] not in ('create', 'revoke'):
            raise errors.NotUndoable()
        new = json.loads(event['new_value'])
        already_undone = False
        for later in db.execute("SELECT new_value FROM events WHERE entity='bw_token' AND id>?", (event_id,)):
            change = json.loads(later['new_value'])
            if change.get('event_id') == event_id:
                already_undone = True
                break
        if already_undone:
            response = {'undone_event_id': event_id, 'message': 'Token change already undone', 'already_undone': True}
            audit(db, 'bw_token', 'undo:' + operation, new={'event_id': event_id, 'id': new['id'], 'response': response})
            return response, db.execute('SELECT last_insert_rowid()').fetchone()[0], False
        row = db.execute('SELECT * FROM api_tokens WHERE id=?', (new['id'],)).fetchone()
        if not row or row['revoked_at'] != new['revoked_at']:
            raise errors.UndoBlocked('Token changed since this event')
        revoked = now().isoformat() if event['field'] == 'create' else json.loads(event['old_value'])['revoked_at']
        db.execute('UPDATE api_tokens SET revoked_at=? WHERE id=?', (revoked, new['id']))
        response = {'undone_event_id': event_id, 'message': 'Token change undone', 'already_undone': False}
        audit(db, 'bw_token', 'undo:' + operation, new={'event_id': event_id, 'id': new['id'], 'response': response})
        identifier = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        return response, identifier, False
