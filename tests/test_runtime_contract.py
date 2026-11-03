"""A missing packaged contract produces an actionable API failure (M.11a, issue #113: API v2). The MCP CLI part is test_runtime_contract_mcp.py."""
from flask import Flask

from brickwork import api2
from brickwork.core import contract as contract_file


def test_a_missing_contract_is_an_actionable_500(tmp_path, monkeypatch):
    monkeypatch.setattr(contract_file, 'CONTRACT_V2', tmp_path / 'missing.yaml')
    app = Flask(__name__)
    app.config['TESTING'] = True
    api2.register(app)
    response = app.test_client().get(api2.PREFIX + '/openapi.yaml')
    assert response.status_code == 500
    assert response.content_type == 'application/problem+json'
    assert response.json['code'] == 'internal_error'
    assert 'OpenAPI contract is missing: docs/brickwork/openapi-v2.yaml' in response.json['detail']
    assert 'Rebuild the image' in response.json['detail']
    assert 'Traceback' not in response.text
