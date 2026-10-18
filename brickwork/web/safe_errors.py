"""Error text for responses (#76).

Messages the app writes for people (ValueError and its subclasses, BrickWorkError, SourceError) pass
through. Anything else (sqlite3, OS, KeyError, TypeError, parser errors) can name tables, columns, SQL or
paths: it is logged server side and replaced by the handler's fallback.
"""
import logging
import sqlite3

log = logging.getLogger('brickwork.web')
FALLBACK = 'Something went wrong · try again'


def public(exc, fallback=FALLBACK):
    """The text a response may show for `exc`."""
    from ..core.sources.base import SourceError
    if isinstance(exc, (sqlite3.Error, OSError)) or not isinstance(exc, (ValueError, SourceError)):
        log.warning('%s hidden from the response: %s', type(exc).__name__, exc)
        return fallback
    return str(exc)
