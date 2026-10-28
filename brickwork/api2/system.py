"""Tokens, exchange rates and the database (M.11d, issue #113): the admin surface that is not a source.

Tokens are `core/tokens.py`'s (a secret is shown once, in the answer of its creation; Undo of a creation revokes it). Exchange rates are
`core/currency.py`'s: a hand-entered rate is one audited write, the ECB feed is one keyless request made outside any transaction. The database
check is `admin.check`; the export is a snapshot of the collection without the stored source keys (not even encrypted) and refuses to leave
if a known secret would remain in it."""
from contextlib import closing
import sqlite3

from flask import Response

from ..core import admin, currency, errors, keys, tokens
from ..core.secrets import secret_values
from . import route
from .read import arguments, page, reading, record, respond
from .writes import Done, write


# ---------- tokens ----------

@route('/tokens')
@reading
def get_tokens(db):
    args = arguments()
    direction = args.get('direction', 'asc')
    if direction not in ('asc', 'desc'):
        raise errors.UnknownFilter('direction is asc or desc')
    records = [record(t['id'], t['name'], name=t['name'], _body=t) for t in tokens.listing(db)]
    return page(records, {k: v for k, v in args.items() if k in ('cursor', 'limit', 'direction')}, default_sort='name')


@route('/tokens', 'POST')
@write
def post_tokens(db, body):
    created, event = tokens.create(db, body.get('name'), body.get('scopes'), body.get('expires_at'))
    return Done(created, event, status=201)


@route('/tokens/<id>', 'DELETE')
@write
def delete_tokens_by_id(db, body, id):
    revoked, event = tokens.revoke(db, id)
    return Done(revoked, event)


# ---------- exchange rates ----------

@route('/exchange-rates')
@reading
def get_exchange_rates(db):
    arguments()
    return respond(currency.listing(db), display_currency=currency.display_currency(db))


@route('/exchange-rates/<code>', 'PUT')
@write
def put_exchange_rates_by_code(db, body, code):
    currency.set_rate(db, code, body['per_eur'])
    return Done(currency.listing(db))


@route('/exchange-rates/ecb', 'POST')
@write(detached=True)
def post_exchange_rates_ecb(db, body):
    return Done(currency.fetch_ecb(db))


# ---------- the database ----------

@route('/database/check')
@reading
def get_database_check(db):
    arguments()
    return respond(admin.check(db))


@route('/database/export')
@reading
def get_database_export(db):
    """A consistent snapshot of the collection, stripped of the stored keys; never a write."""
    arguments()
    with closing(sqlite3.connect(':memory:')) as snapshot:
        db.backup(snapshot)
        keys.strip(snapshot)
        snapshot.execute('PRAGMA journal_mode=DELETE')
        content = bytearray(snapshot.serialize())
    content[18:20] = bytes((1, 1))                          # a serialised WAL header cannot be opened without its sidecar
    if any(value.encode() in content for value in secret_values()):
        raise errors.Conflict('Export contains credential material')
    return Response(bytes(content), mimetype='application/vnd.sqlite3', headers={'Content-Disposition': 'attachment; filename=brickwork.db'})
