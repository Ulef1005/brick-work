"""Error routing and install metadata through the real application factory."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from brickwork.core.connect import connect
from tests.web_fixtures import app, apps, logged_in

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api_app(app, monkeypatch):
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    from brickwork.web.admin_ops import setup
    with app.app_context():
        setup()
    return app


def bearer():
    return {'Authorization': 'Bearer synthetic-bootstrap'}


def test_unknown_api_path_is_problem_json(api_app):
    for method in ('get', 'post'):
        response = getattr(api_app.test_client(), method)('/api/v1/does-not-exist', headers=bearer())
        assert response.mimetype == 'application/problem+json', method
        assert response.json['code'] in ('not_found', 'method_not_allowed')
    assert api_app.test_client().get('/api/v1/does-not-exist', headers=bearer()).json['code'] == 'not_found'


def test_abort_404_inside_an_api_view_is_problem_json(api_app):
    response = api_app.test_client().delete('/api/v1/tokens/bootstrap', headers=bearer())
    assert response.status_code == 404
    assert response.mimetype == 'application/problem+json'
    assert response.json['code'] == 'not_found'

