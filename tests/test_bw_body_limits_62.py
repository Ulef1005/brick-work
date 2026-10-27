"""#62: request bodies over the cap are refused before they are read.

M.11a (issue #113): the API tests run against /api/v2 on the 4.0 fixtures; a body under the cap reaches the operation (501 until its piece)."""
import io

from flask import Flask

from brickwork import limits
from tests.api2 import call, v2  # noqa: F401
from tests.app4 import app4, coll, pair  # noqa: F401
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


def test_json_over_the_cap_is_refused_unread(v2):  # noqa: F811
    response = declared(v2, '/api/v2/stock', 'application/json', limits.JSON_LIMIT + 1,
                        **AUTH, **{'Idempotency-Key': 'k1'})
    assert response.status_code == 413
    assert response.json['code'] == 'payload_too_large'


def test_identification_upload_over_its_cap_is_refused(v2):  # noqa: F811
    response = declared(v2, '/api/v2/identifications', 'multipart/form-data; boundary=x',
                        limits.IDENTIFICATION_LIMIT + 1, **AUTH)
    assert response.status_code == 413


def test_any_upload_over_the_global_cap_is_refused(v2):  # noqa: F811
    response = declared(v2, '/api/v2/copies/c1/photos', 'multipart/form-data; boundary=x',
                        limits.upload_limit() + 1, **AUTH)
    assert response.status_code == 413


def test_a_large_upload_under_the_cap_is_not_refused_by_size(v2):  # noqa: F811
    response = v2.post('/api/v2/identifications', headers=AUTH,
        data={'file': (io.BytesIO(b'x' * (2 * limits.MB)), 'p.txt', 'text/plain')})
    assert response.status_code != 413


def test_web_form_over_the_cap_is_refused(app):  # noqa: F811
    response = declared(logged_in(app), '/collection/save/edit', 'application/x-www-form-urlencoded', limits.JSON_LIMIT + 1)
    assert response.status_code == 413


def test_normal_bodies_still_pass(v2):  # noqa: F811
    assert call(v2, '/me').status_code == 200
    reached = v2.post('/api/v2/tokens', json={'name': 'limits', 'scopes': ['read']}, headers=AUTH)
    assert reached.status_code == 501                                                  # past the size check: the operation arrives with M.11d


def test_limits_follow_the_import_setting(monkeypatch):
    monkeypatch.setenv('BW_IMPORT_MAX_MB', '50')
    assert limits.upload_limit() == 51 * limits.MB
    app = Flask('limits')
    limits.install(app)
    limits.install(app)
    assert app.config['MAX_CONTENT_LENGTH'] == 51 * limits.MB
    assert len(app.before_request_funcs[None]) == 1
