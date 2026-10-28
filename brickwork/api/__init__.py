"""Brick Work API v1: retired. Every path answers 410 Gone and names v2, except `GET /health` (release tracking and the container health check
read it). The 4.0 line cannot represent local or unidentified items in v1's terms (M.8a, issue #110, decision 1); v2 is the API (`brickwork/api2`,
`docs/brickwork/api-v2.md`). What v1 and v2 share is `transport.py` (read-only, the database per request, authentication, the problem+json handler)."""
from flask import Blueprint, jsonify, request
from werkzeug.exceptions import NotFound

from ..core import errors, meta
from . import transport
from .transport import db_path, problem, read_only  # noqa: F401 — kept importable from here (the web layer asks `read_only`)

api = Blueprint('brickwork_api', __name__, url_prefix='/api/v1')
HEALTH = 'brickwork_api.get_health'


def database():
    return transport.database(HEALTH)


@api.before_request
def retired():
    if request.endpoint != HEALTH:
        raise errors.ApiRetired(errors.API_V1_RETIRED)


api.after_request(transport.private_response)
api.teardown_request(transport.close_database)
api.register_error_handler(Exception, problem)


def register(app):
    from ..limits import install as install_body_limits
    install_body_limits(app)
    app.register_blueprint(api)
    # Routing 404/405 happen before Flask knows the blueprint.
    previous_404 = app.error_handler_spec.get(None, {}).get(404, {}).get(NotFound)

    def routing_error(error):
        if request.path == '/api/v1' or request.path.startswith('/api/v1/'):
            # Every v1 path is gone, whether or not a route is registered for it (health excepted).
            return problem(error if request.path == '/api/v1/health' else errors.ApiRetired(errors.API_V1_RETIRED))
        if error.code == 404 and previous_404:
            return previous_404(error)
        return error
    app.register_error_handler(404, routing_error)
    app.register_error_handler(405, routing_error)


@api.get('/health')
def get_health():
    return jsonify(data=meta.health(database()))
