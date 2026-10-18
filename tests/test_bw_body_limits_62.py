"""#62: request bodies over the cap are refused before they are read."""
import io

from flask import Flask

from brickwork import limits
from tests.test_bw_api_m1 import app as api_app, call  # noqa: F401
from tests.web_fixtures import app, apps, logged_in  # noqa: F401

AUTH = {'Authorization': 'Bearer synthetic-bootstrap'}


class Exploding(io.BytesIO):
    """A body that fails the test if anything reads it."""
    def read(self, *args):
        raise AssertionError('the body was read')
    readline = read


def declared(client, path, content_type, length, **headers):
    # The test client recomputes Content-Length from the stream; the WSGI environ carries the declared one.
    return client.post(path, headers={'Content-Type': content_type, **headers},
                       environ_overrides={'CONTENT_LENGTH': str(length)}, input_stream=Exploding())


def test_json_over_the_cap_is_refused_unread(api_app):  # noqa: F811
    response = declared(api_app.test_client(), '/api/v1/stock', 'application/json', limits.JSON_LIMIT + 1,
                        **AUTH, **{'Idempotency-Key': 'k1'})
    assert response.status_code == 413
    assert response.json['code'] == 'payload_too_large'


def test_identification_upload_over_its_cap_is_refused(api_app):  # noqa: F811
    response = declared(api_app.test_client(), '/api/v1/identifications', 'multipart/form-data; boundary=x',
                        limits.IDENTIFICATION_LIMIT + 1, **AUTH)
    assert response.status_code == 413


def test_any_upload_over_the_global_cap_is_refused(api_app):  # noqa: F811
    response = declared(api_app.test_client(), '/api/v1/copies/c1/photos', 'multipart/form-data; boundary=x',
                        limits.upload_limit() + 1, **AUTH)
    assert response.status_code == 413


def test_a_large_upload_under_the_cap_is_not_refused_by_size(api_app):  # noqa: F811
    response = api_app.test_client().post('/api/v1/identifications', headers=AUTH,
        data={'file': (io.BytesIO(b'x' * (2 * limits.MB)), 'p.txt', 'text/plain')})
    assert response.status_code != 413


def test_web_form_over_the_cap_is_refused(app):  # noqa: F811
    response = declared(logged_in(app), '/collection/save/edit', 'application/x-www-form-urlencoded', limits.JSON_LIMIT + 1)
    assert response.status_code == 413


def test_normal_bodies_still_pass(api_app):  # noqa: F811
    assert call(api_app, '/me').status_code == 200
    created = api_app.test_client().post('/api/v1/tokens', json={'name': 'limits', 'scopes': ['read']}, headers=AUTH)
    assert created.status_code == 201


def test_limits_follow_the_import_setting(monkeypatch):
    monkeypatch.setenv('BW_IMPORT_MAX_MB', '50')
    assert limits.upload_limit() == 51 * limits.MB
    app = Flask('limits')
    limits.install(app)
    limits.install(app)
    assert app.config['MAX_CONTENT_LENGTH'] == 51 * limits.MB
    assert len(app.before_request_funcs[None]) == 1
