"""The transport both API lines share: read-only, the database per request, bearer authentication with scopes and the throttle,
the audit origin, the problem+json error handler and the 404/405 routing errors (v1 since 4.11, v2 since M.11a, issue #113).

A line (a blueprint) passes in what differs: its health endpoint, the endpoints that need no token, and the scope of every other
endpoint. Nothing here knows a path."""
from contextlib import ExitStack
import os
from pathlib import Path
import sqlite3

from flask import current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException

from ..core import errors, tokens
from ..core.connect import connect
from ..core.sources.base import WaitingForBudget, audit_origin, redact


def read_only():
    return current_app.config.get('BW_READ_ONLY', False) or os.environ.get('BW_READ_ONLY', '').lower() in ('1', 'true', 'yes', 'on')


def db_path():
    return Path(os.environ.get('BW_DB_PATH') or current_app.config.get('BRICKWORK_DB_PATH') or 'data/brickwork.db')


def database(health):
    """The request's connection to the collection (opened once). Health reads the collection alone, read-only: it answers on a first
    run before the catalogue is there and never writes."""
    if 'api_db' not in g:
        path = db_path()
        if not path.is_file():
            raise errors.NotSetUp("Run 'brickwork setup' first")
        g.api_db = connect(path, read_only=request.endpoint == health, require_catalogue=request.endpoint != health)
    return g.api_db


def authorize(*, health, open_endpoints, scope_of):
    """Open the request's audit stack and authenticate it. `open_endpoints` need no token; `scope_of(endpoint, method)` gives the scope
    every other endpoint needs. Order as in v1: throttle, token, read-only, scope."""
    g.api_stack = ExitStack()
    if request.endpoint in open_endpoints:
        if request.method != 'GET' and read_only():
            raise errors.ReadOnlyInstance()
        return
    header = request.headers.get('Authorization', '')
    supplied = header[7:] if header.startswith('Bearer ') else ''
    from ..core.throttle import API
    client = request.remote_addr
    wait = API.wait(client)
    if wait:
        raise errors.TooManyAttempts('Too many failed token checks · try again in ' + str(wait) + ' s', retry_after=wait)
    try:
        g.api_identity = tokens.authenticate(database(health), supplied, os.environ.get('BW_API_TOKEN', ''))
    except errors.Unauthorized:
        API.fail(client)
        raise
    API.succeed(client)
    if request.method != 'GET' and read_only():
        raise errors.ReadOnlyInstance()
    if not tokens.permits(g.api_identity, scope_of(request.endpoint, request.method)):
        raise errors.Forbidden()


def audited():
    """Enter the audit origin of an authenticated request (events carry via=api and the token name)."""
    g.api_stack.enter_context(audit_origin('api', actor=g.api_identity['name']))


def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def close_database(error):
    stack = g.pop('api_stack', None)
    if stack: stack.close()
    db = g.pop('api_db', None)
    if db is not None: db.close()


def problem(error):
    extra, headers = {}, {}
    if isinstance(error, errors.BrickWorkError):
        code, status, detail = error.code, error.status, redact(error)
        if isinstance(error, WaitingForBudget):
            extra.update(retry_after=error.retry_after(), job_id=error.job_id)
            headers['Retry-After'] = str(extra['retry_after'])
        if error.context.get('source'):
            extra['source'] = error.context['source']
        if error.code == 'too_many_attempts':
            extra['retry_after'] = error.context['retry_after']
            headers['Retry-After'] = str(error.context['retry_after'])
        # v2 (M.11a): the candidates of an ambiguous number, the survivor of a merged id and where a moved id went.
        for member in ('candidates', 'survivor'):
            if error.context.get(member) is not None:
                extra[member] = error.context[member]
        if error.code == 'moved':
            headers['Location'] = error.context['location']
    elif isinstance(error, sqlite3.Error):
        code, status, detail = 'db_unavailable', 503, 'Database unavailable'
    elif isinstance(error, HTTPException):
        status = error.code
        code = {400: 'bad_request', 401: 'unauthorized', 403: 'forbidden',
                404: 'not_found', 405: 'method_not_allowed', 409: 'conflict',
                413: 'payload_too_large', 415: 'unsupported_media_type'}.get(
                    status, 'bad_request' if 400 <= status < 500 else 'internal_error')
        detail = code.replace('_', ' ').capitalize()
    elif isinstance(error, ValueError):
        code, status, detail = 'validation_failed', 422, redact(error)
    else:
        code, status, detail = 'internal_error', 500, 'Internal error'
    response = jsonify(type='urn:brickwork:error:' + code, title=code.replace('_', ' ').capitalize(), status=status, code=code, detail=detail, instance=request.path, **extra)
    response.status_code = status
    response.headers.extend(headers)
    response.content_type = 'application/problem+json'
    if status == 401: response.headers['WWW-Authenticate'] = 'Bearer'
    if status == 405 and isinstance(error, HTTPException):
        allow = error.get_response().headers.get('Allow')
        if allow is not None: response.headers['Allow'] = allow
    return response
