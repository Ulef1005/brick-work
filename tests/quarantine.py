"""The tests that wait for their module's port to the 4.0 store (M.8a, issue #110).

From M.8a the app opens only a 4.0 collection. A test file that still builds the 3.3 store (or imports a module no piece has ported yet)
cannot run; it is listed here with the piece that ports it (the #110 scope comment: M.8b to M.8j, and M.11 for the v1 API, whose
routes answer 410 until v2). `conftest.py` skips these files (`collect_ignore`); `scripts/check.sh` prints how many are left.

The list can only shrink: a piece removes its files here in the commit that rewrites them on 4.0 fixtures and turns them green
(`tests/test_quarantine.py` freezes the baseline). Nothing is deleted from this list by being forgotten: a file that exists and is not
listed runs.
"""

QUARANTINE = {
    # M.11a (issue #113) ported to API v2 the transport tests of test_app_factory.py, test_bw_body_limits_62.py, test_bw_throttle.py and
    # test_runtime_contract.py; what was left of them is the MCP: M.11e.
    'tests/test_bw_throttle_mcp.py': 'M.11',
    'tests/test_runtime_contract_mcp.py': 'M.11',
    # M.11b and M.11c ported the reads and the writes of the v1 tests (tests/test_api2_read*.py, tests/test_api2_write*.py).
    # M.11d (issue #113) ported the rest, or deleted what had no 4.0 premise:
    #   test_bw_api_47, test_bw_api_jobs_followup, test_bw_api_m5, test_bw_api_m6, test_bw_orders_export_44_api, test_bw_orders_storage_api, test_bw_sync_api,
    #   test_bw_currency_39_api, test_bw_review_followups, test_bw_security -> tests/test_api2_write_{system,sources,jobs,orders,sync}.py,
    #   tests/test_api2_reads_admin.py, tests/test_secrets.py, tests/test_web_security.py (the import-source and plan-marker cases of the 3.3 text are gone
    #   with the 3.3 store; the colour sync with the 3.3 colour table; the receipt-kind registry of the bundle with the bundle: Undo is the event registry's);
    #   test_bw_api_m0, test_bw_api_m1, test_bw_api_m2 -> tests/test_api2_{contract,transport,reads,write_system}.py, tests/test_secrets.py (what was
    #   left of m0 tested the 3.3 upgrade, the 3.3 value lists and the v1 contract text; m2 was the generic GET sweep over the v1 contract).
    # What waits for M.11e is the MCP (m7, the wishlist tools of wishlists_api), the v1 contract harness it generates tools from (m1_contract) and the
    # parity test. They take `app`, `call` and the contract from tests/api2.py when they are ported; their old imports (test_bw_api_m1, m2, m3) are gone.
    'tests/test_bw_api_m1_contract.py': 'M.11',
    'tests/test_bw_api_m7.py': 'M.11',
    'tests/test_bw_api_parity.py': 'M.11',
    'tests/test_bw_wishlists_api.py': 'M.11',
}
