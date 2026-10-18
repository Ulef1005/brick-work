"""Missing packaged contracts produce actionable API and CLI failures."""
from pathlib import Path
import subprocess
import sys

from flask import Flask
import pytest

from brickwork.api import register
from brickwork.core import contract as contract_file


def test_missing_contract_api(tmp_path, monkeypatch):
    monkeypatch.setattr(contract_file, 'CONTRACT', tmp_path / 'missing.yaml')
    app = Flask(__name__)
    app.config['TESTING'] = True
    register(app)
    response = app.test_client().get('/api/v1/openapi.yaml')
    assert response.status_code == 500
    assert response.content_type == 'application/problem+json'
    assert response.json['code'] == 'internal_error'
    assert 'OpenAPI contract is missing: docs/brickwork/openapi-v1.yaml' in response.json['detail']
    assert 'Rebuild the image' in response.json['detail']
    assert 'Traceback' not in response.text


@pytest.mark.parametrize('flags', [
    ['--in-process'],
    [],  # stdio using the HTTP API client
    ['--transport', 'http'],
])
def test_missing_contract_mcp_cli(tmp_path, flags):
    # A fresh process exercises the real CLI exit code and stderr, with an empty
    # contract cache. No server or network is needed: startup must fail first.
    code = '''
import sys
from pathlib import Path
from brickwork.core import contract
from brickwork.web.cli import main
contract.CONTRACT = Path(sys.argv[1])
sys.exit(main(['mcp', *sys.argv[2:]]))
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'missing.yaml'), *flags],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 1
    assert result.stdout == ''
    assert 'MCP error: OpenAPI contract is missing: docs/brickwork/openapi-v1.yaml.' in result.stderr
    assert 'Rebuild the image' in result.stderr
    assert 'Traceback' not in result.stderr
