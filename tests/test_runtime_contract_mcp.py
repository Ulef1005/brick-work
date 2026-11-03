"""Missing packaged contracts produce actionable CLI failures: the MCP part of test_runtime_contract.py, split out by M.11a (issue #113) and ported
by M.11e, which regenerated the MCP from openapi-v2.yaml: the file that is missing is now the v2 one."""
from pathlib import Path
import subprocess
import sys

import pytest


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
contract.CONTRACT_V2 = Path(sys.argv[1])
sys.exit(main(['mcp', *sys.argv[2:]]))
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'missing.yaml'), *flags],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 1
    assert result.stdout == ''
    assert 'MCP error: OpenAPI contract is missing: docs/brickwork/openapi-v2.yaml.' in result.stderr
    assert 'Rebuild the image' in result.stderr
    assert 'Traceback' not in result.stderr
