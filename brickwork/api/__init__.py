"""Brick Work v1 transport. The legacy web API remains independently mounted."""
from contextlib import ExitStack
import os
from pathlib import Path
import sqlite3

from flask import Blueprint, current_app, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException, NotFound

from ..core import errors, meta, tokens
from ..core.connect import connect
from ..core.contract import contract_path
from ..core.listing import filter_rows, paginate
from ..core.sources.base import WaitingForBudget, audit_origin, redact

api = Blueprint('brickwork_api', __name__, url_prefix='/api/v1')


def read_only():
    return current_app.config.get('BW_READ_ONLY', False) or os.environ.get('BW_READ_ONLY', '').lower() in ('1', 'true', 'yes', 'on')


def db_path():
    return Path(os.environ.get('BW_DB_PATH') or current_app.config.get('BRICKWORK_DB_PATH') or 'data/brickwork.db')


def database():
    if 'api_db' not in g:
        path = db_path()
        if not path.is_file():
            raise errors.NotSetUp("Run 'brickwork setup' first")
        # Health reads the collection alone, read-only: it answers on a first run before the catalogue is there and never writes.
        g.api_db = connect(path, read_only=request.endpoint == HEALTH, require_catalogue=request.endpoint != HEALTH)
    return g.api_db


HEALTH = 'brickwork_api.get_health'


@api.before_request
def retired():
    """API v1 answers 410 Gone on the 4.0 line (M.8a, decision 1): v1 cannot represent local or unidentified items; v2 comes with M.11.
    The one exception is GET /health, which release tracking and the container health check read. The route table stays, so the
    contract checks keep describing what v2 inherits."""
    if request.endpoint != HEALTH:
        raise errors.ApiRetired(errors.API_V1_RETIRED)


@api.before_request
def authorize():
    g.api_stack = ExitStack()
    if request.endpoint in ('brickwork_api.get_health', 'brickwork_api.get_openapi_yaml'):
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
        g.api_identity = tokens.authenticate(database(), supplied, os.environ.get('BW_API_TOKEN', ''))
    except errors.Unauthorized:
        API.fail(client)
        raise
    API.succeed(client)
    if request.method != 'GET' and read_only():
        raise errors.ReadOnlyInstance()
    scope = 'admin' if request.endpoint in ('brickwork_api.get_tokens', 'brickwork_api.post_tokens', 'brickwork_api.delete_tokens_by_id', 'brickwork_api.get_database_check', 'brickwork_api.get_database_export', 'brickwork_api.patch_sources_by_source', 'brickwork_api.post_catalogue_import', 'brickwork_api.post_colors_sync', 'brickwork_api.put_sources_source_key', 'brickwork_api.delete_sources_source_key', 'brickwork_api.post_sources_source_key_test', 'brickwork_api.post_imports_bricktracker', 'brickwork_api.post_imports_by_id_apply', 'brickwork_api.post_sync_by_source_send_apply', 'brickwork_api.post_sources_source_user_connect', 'brickwork_api.put_sources_source_user', 'brickwork_api.delete_sources_source_user', 'brickwork_api.post_sources_source_user_test', 'brickwork_api.patch_settings', 'brickwork_api.put_exchange_rates_by_code', 'brickwork_api.post_exchange_rates_ecb') else ('read' if request.method == 'GET' else 'write')
    if not tokens.permits(g.api_identity, scope):
        raise errors.Forbidden()
    if request.method != 'GET' and 'If-Match' in request.headers:
        from .writes import SPEC
        if not any(op['if_match'] and request.endpoint == 'brickwork_api.' + op['endpoint'] for op in SPEC['operations']):
            raise errors.BadRequest('If-Match is not supported on this operation')
    g.api_stack.enter_context(audit_origin('api', actor=g.api_identity['name']))


@api.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@api.teardown_request
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


api.register_error_handler(Exception, problem)


def register(app):
    from ..limits import install as install_body_limits
    install_body_limits(app)
    app.register_blueprint(api)
    # Routing 404/405 happen before Flask knows the blueprint.
    previous_404 = app.error_handler_spec.get(None, {}).get(404, {}).get(NotFound)
    def routing_error(error):
        if request.path == '/api/v1' or request.path.startswith('/api/v1/'):
            # Every v1 path is gone, whether or not a route is still registered for it (health excepted).
            return problem(error if request.path == '/api/v1/health' else errors.ApiRetired(errors.API_V1_RETIRED))
        if error.code == 404 and previous_404:
            return previous_404(error)
        return error
    app.register_error_handler(404, routing_error)
    app.register_error_handler(405, routing_error)


@api.get('/health')
def get_health():
    return jsonify(data=meta.health(database()))


@api.get('/version')
def get_version():
    from .serializers import public
    return jsonify(data=public(meta.version(database(), read_only()), 'Version'))


@api.get('/me')
def get_me():
    return jsonify(data={k: g.api_identity[k] for k in ('name', 'scopes', 'expires_at')})


@api.get('/openapi.yaml')
def get_openapi_yaml():
    return send_file(contract_path(), mimetype='application/yaml')


@api.get('/tokens')
def get_tokens():
    if set(request.args) - {'cursor', 'limit', 'direction'}:
        raise errors.UnknownFilter()
    direction = request.args.get('direction', 'asc')
    rows = filter_rows(tokens.listing(database()), sort='name', direction=direction)
    return jsonify(paginate(rows, cursor=request.args.get('cursor'), limit=request.args.get('limit', 50), sort='name', direction=direction, signature='/tokens'))


def written(data, event, status=200):
    return jsonify(data=data, event_id=event, undo_url=f'/api/v1/events/{event}/undo', idempotent_replay=False), status


@api.post('/tokens')
def post_tokens():
    data = request.get_json(silent=True)
    if not isinstance(data, dict): raise errors.BadRequest('Expected a JSON object')
    if set(data) - {'name', 'scopes', 'expires_at'}: raise errors.ValidationFailed('Unknown token field')
    result, event = tokens.create(database(), data.get('name'), data.get('scopes'), data.get('expires_at'))
    return written(result, event, 201)


@api.delete('/tokens/<id>')
def delete_tokens_by_id(id):
    return written(*tokens.revoke(database(), id))


@api.post('/events/<int:id>/undo')
def post_events_by_id_undo(id):
    if request.get_data():
        raise errors.BadRequest('Undo accepts no request body')
    from ..core import api_writes as service, undo
    from .serializers import public
    def action():
        return undo.undo_event(database(), id, via='api', actor=g.api_identity['name'], identity=g.api_identity), 200
    result,status = service.execute(database(),method=request.method,path=request.path,body={},
        key=request.headers.get('Idempotency-Key'),required=True,token_name=g.api_identity['name'],
        action=action,serialize=lambda value: public(value,'UndoResult'))
    result['undo_url'] = None
    return jsonify(result),status



from . import reads  # noqa: E402,F401 — install the read-only route manifest

from . import writes  # noqa: E402,F401

from . import operations  # noqa: E402,F401 — M5 jobs, sources, key store, identification

from . import sync  # noqa: E402,F401 — collection sync with Rebrickable and Brickset
