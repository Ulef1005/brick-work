"""#48, split out of test_bw_throttle.py by M.11a (issue #113): the MCP in-process client carries the caller address. Waits for M.11e."""
from brickwork.core import throttle  # noqa: F401
from tests.test_bw_api_m1 import app as api_app  # noqa: F401


def test_mcp_in_process_client_carries_the_caller_address(api_app, monkeypatch):  # noqa: F811
    from brickwork.core.mcp.client import InProcessClient
    monkeypatch.setenv('BW_LOGIN_MAX_FAILURES', '2')
    for _ in range(2):
        InProcessClient(api_app, 'wrong', remote_addr='10.9.2.1').request('GET', '/me')
    assert InProcessClient(api_app, 'synthetic-bootstrap', remote_addr='10.9.2.1').request('GET', '/me')[0] == 429
    assert InProcessClient(api_app, 'synthetic-bootstrap', remote_addr='10.9.2.2').request('GET', '/me')[0] == 200
