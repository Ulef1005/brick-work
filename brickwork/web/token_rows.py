"""Presentation rows for the API tokens page. Only token metadata is ever read here."""
from datetime import datetime, timedelta, timezone
import json
import os
import re

from .formatting import short_date

UNDO_WINDOW = timedelta(minutes=10)

SCOPE_HELP = (
    ('read', 'See the collection, lists and prices'),
    ('write', 'Add and change items, run checks'),
    ('admin', 'Keys, tokens, jobs and maintenance'),
)


def day(value):
    return short_date(value) if value else '—'


def day_time(value):
    return short_date(value, with_time=True) if value else '—'


def _expired(value, now):
    try:
        return datetime.fromisoformat(value) <= now
    except (TypeError, ValueError):
        return False


def row(token, now):
    expired = bool(token['expires_at']) and _expired(token['expires_at'], now)
    return dict(id=token['id'], name=token['name'], scopes=token['scopes'], created=day(token['created_at']),
                last_used=day_time(token['last_used_at']), environment=False,
                note='Expired' if expired else 'Expires ' + day(token['expires_at']) if token['expires_at'] else '')


def rows(listing, now):
    """Active stored tokens, then the install-environment token (never revocable here)."""
    stored = [row(t, now) for t in listing if not t['revoked_at']]
    environment = []
    if os.environ.get('BW_API_TOKEN'):
        environment.append(dict(id=None, name='Install environment', scopes=['read', 'write', 'admin'], created='—',
                                last_used='—', environment=True, note='From the install environment · cannot be revoked here'))
    return stored, environment


def event_id(text):
    """A bounded decimal event id from request input, or None."""
    return int(text) if isinstance(text, str) and re.fullmatch(r'[0-9]{1,18}', text) else None


def _object(text):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def recent(event, now=None):
    """True while the event is inside the Undo window (the page promises Undo for a short while only)."""
    try:
        at = datetime.fromisoformat(str(event['at']).replace('Z', '+00:00'))
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - at <= UNDO_WINDOW


def undoable(event):
    """The payload shape tokens.undo reads: a new object with the token id, and for a revoke an old object."""
    new = _object(event['new_value'])
    if new is None or not isinstance(new.get('id'), str) or 'revoked_at' not in new:
        return False
    return event['field'] != 'revoke' or _object(event['old_value']) is not None and 'revoked_at' in _object(event['old_value'])


def revoked_event(db, identifier):
    """(name, undoable) for a revoke event; a neutral name when the payload has none; None for other events."""
    found = db.execute("SELECT field,old_value,new_value,at FROM events WHERE id=? AND entity='bw_token' AND field='revoke'", (identifier,)).fetchone()
    if not found:
        return None
    payload = _object(found['new_value'])
    name = payload.get('name') if payload else None
    return (name if isinstance(name, str) and name else 'Token'), undoable(found) and recent(found)
