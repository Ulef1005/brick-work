"""Brick Work API v2 transport (M.11a, issue #113): v1's conventions with the 4.0 identity.

The contract is `docs/brickwork/api-v2.md` and `openapi-v2.yaml`. Authentication, scopes, the throttle, read-only, the audit origin,
envelopes and problem+json errors are v1's, shared through `api/transport.py`. The scope of every operation is read from the contract's
`security`, so the contract is the one place that says who may call what. An operation whose piece has not landed (`DONE` below)
answers `501 not_implemented` naming the piece; the contract check (`scripts/check_api_contract.py`) lists them."""
from functools import lru_cache

from flask import Blueprint, g, jsonify, request, send_file

from ..api import transport
from ..core import contract, errors, meta

NAME = 'brickwork_api2'
PREFIX = '/api/v2'
HEALTH = NAME + '.get_health'
OPEN = (HEALTH, NAME + '.get_openapi_yaml')
DONE = ('M.11a',)                                         # the pieces whose operations are implemented; a piece adds itself here

# (rule, method, view) collected by `route`, built into a blueprint by `blueprint()`. A view is named by its operationId.
ROUTES = []


def route(rule, method='GET'):
    def mark(view):
        ROUTES.append((rule, method, view))
        return view
    return mark


def database():
    return transport.database(HEALTH)


@lru_cache(maxsize=4)
def _operations(path, stamp):
    import yaml
    with open(path) as handle:
        spec = yaml.safe_load(handle)
    result = {}
    for template, methods in spec['paths'].items():
        for method, operation in methods.items():
            if isinstance(operation, dict) and 'operationId' in operation:
                security = operation.get('security', spec.get('security', []))
                scope = security[0]['bearerAuth'][0] if security else None
                result[operation['operationId']] = dict(method=method.upper(), path=template, scope=scope, piece=operation.get('x-piece'))
    return result


def operations():
    """`{operationId: {method, path, scope, piece}}` of the v2 contract (cached per file version)."""
    path = contract.contract_v2_path()
    return _operations(path, path.stat().st_mtime_ns)


def scope_of(endpoint, method):
    return operations()[endpoint.split('.', 1)[1]]['scope'] or 'read'


def authorize():
    transport.authorize(health=HEALTH, open_endpoints=OPEN, scope_of=scope_of)
    if request.endpoint not in OPEN:
        transport.audited()


def not_implemented(piece):
    def view(**_):
        response = jsonify(type='urn:brickwork:error:not_implemented', title='Not implemented', status=501, code='not_implemented',
                           error='not_implemented', piece=piece, detail=f'This operation arrives with {piece}', instance=request.path)
        response.status_code = 501
        response.content_type = 'application/problem+json'
        return response
    view.piece = piece                                    # the contract check tells a placeholder from an implemented view by this
    return view


def pending(spec):
    """The contract's operations that are not implemented: `[(operationId, method, path, piece)]`."""
    return [(i, o['method'], o['path'], o['piece']) for i, o in spec.items() if o['piece'] not in DONE]


def flask_rule(template):
    """`/items/{id}/links` -> `/items/<id>/links`. Every parameter is a string; a view that wants a number checks it itself."""
    return template.replace('{', '<').replace('}', '>')


def blueprint():
    api = Blueprint(NAME, __name__, url_prefix=PREFIX)
    api.before_request(authorize)
    api.after_request(transport.private_response)
    api.teardown_request(transport.close_database)
    api.register_error_handler(Exception, transport.problem)
    taken = set()
    for rule, method, view in ROUTES:
        api.add_url_rule(rule, view.__name__, view, methods=[method])
        taken.add(view.__name__)
    try:
        spec = operations()
    except errors.BrickWorkError:                         # the contract is missing: /openapi.yaml says so, nothing else is routed
        return api
    for operation_id, o in spec.items():
        if o['piece'] not in DONE and operation_id not in taken:
            api.add_url_rule(flask_rule(o['path']), operation_id, not_implemented(o['piece']), methods=[o['method']])
    return api


def _previous(app, code):
    handlers = app.error_handler_spec.get(None, {}).get(code, {})
    return next(iter(handlers.values()), None)


def register(app):
    from ..limits import install as install_body_limits
    install_body_limits(app)
    from . import items  # noqa: F401 — the routes of M.11a
    app.register_blueprint(blueprint())
    previous = {404: _previous(app, 404), 405: _previous(app, 405)}

    def routing_error(error):
        # Routing 404/405 happen before Flask knows the blueprint.
        if request.path == PREFIX or request.path.startswith(PREFIX + '/'):
            return transport.problem(error)
        handler = previous.get(error.code)
        return handler(error) if handler else error
    app.register_error_handler(404, routing_error)
    app.register_error_handler(405, routing_error)


@route('/health')
def get_health():
    return jsonify(data=meta.health(database(), meta.API_V2))


@route('/version')
def get_version():
    from ..api.serializers import public
    return jsonify(data=public(meta.version(database(), transport.read_only(), meta.API_V2), 'Version'))


@route('/me')
def get_me():
    return jsonify(data={k: g.api_identity[k] for k in ('name', 'scopes', 'expires_at')})


@route('/openapi.yaml')
def get_openapi_yaml():
    return send_file(contract.contract_v2_path(), mimetype='application/yaml')
