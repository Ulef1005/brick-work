"""The tests that wait for their module's port to the 4.0 store (M.8a, issue #110).

From M.8a the app opens only a 4.0 collection. A test file that still builds the 3.3 store (or imports a module no piece has ported yet)
cannot run; it is listed here with the piece that ports it (the #110 scope comment: M.8b to M.8j, and M.11 for the v1 API, whose
routes answer 410 until v2). `conftest.py` skips these files (`collect_ignore`); `scripts/check.sh` prints how many are left.

The list can only shrink: a piece removes its files here in the commit that rewrites them on 4.0 fixtures and turns them green
(`tests/test_quarantine.py` freezes the baseline). Nothing is deleted from this list by being forgotten: a file that exists and is not
listed runs.
"""

QUARANTINE = {
    # M.8h split these out of files it ported (tests that belong to a later piece moved, none was added): out of test_bw_orders_storage.py and
    # test_bw_orders_export_44.py the API receipts, history and export tests (M.11).
    'tests/test_bw_orders_export_44_api.py': 'M.11',
    'tests/test_bw_orders_storage_api.py': 'M.11',
    # M.8j split this out of a file it ported (the test that belongs to a later piece moved, none was added): out of test_bw_sync.py the API test (M.11).
    'tests/test_bw_sync_api.py': 'M.11',
    # M.11a (issue #113) ported to API v2 the transport tests of test_app_factory.py, test_bw_body_limits_62.py, test_bw_throttle.py and
    # test_runtime_contract.py (all four are live again) and the contract tests of test_bw_api_m0.py (now tests/test_api2_contract.py; what is
    # left of it is the 3.3 core: upgrade, secrets, price settings). Split out of them, none added: the MCP tests (M.11e).
    'tests/test_bw_throttle_mcp.py': 'M.11',
    'tests/test_runtime_contract_mcp.py': 'M.11',
    # M.11b (issue #113) ported to API v2 the reads of test_bw_api_m1, test_bw_api_m2 and test_bw_api_m3 (tests/test_api2_read*.py; the generic
    # contract tests over all GETs stay in test_bw_api_m2 for the operations of M.11d), all of test_bw_perf_api.py and test_bw_partout_38_api.py (both
    # deleted), the reads of test_bw_wish_progress_35_api.py and of test_bw_media_27.py. What is left of them is writes or M.11d operations.
    # test_bw_currency_39_api.py has no read of M.11b: its one test writes and reads exchange rates and settings (M.11c, M.11d).
    # M.11c (issue #113) ported to API v2 the writes of test_bw_api_m3 and test_bw_api_m4 (both deleted: every test in them was a write of M.11c),
    # test_bw_api_take_figure, test_bw_check_api_63, test_bw_core_fixes_api, test_bw_lists_43_api (its reads were M.11b's), test_bw_media_27 and
    # test_bw_wish_progress_35_api (all deleted), and the settings half of test_bw_currency_39_api, the writes and CLI of test_bw_wishlists_api and
    # the check and upload-cap tests of test_bw_review_followups. What is left of those three is exchange rates (M.11d), the MCP (M.11e) and the
    # plan markers of sync and import (M.11d). Split out, none added: the session key test of test_bw_review_followups (tests/test_session_key.py).
    # The M.11d files below that took `write` and `dbrows` from test_bw_api_m3 take `write` and `rows` of tests/api2.py when they are ported.
    # M.11: API v2 and clients: the v1 API, MCP and contract tests
    'tests/test_bw_api_47.py': 'M.11',
    'tests/test_bw_api_jobs_followup.py': 'M.11',
    'tests/test_bw_api_m0.py': 'M.11',
    'tests/test_bw_api_m1.py': 'M.11',
    'tests/test_bw_api_m1_contract.py': 'M.11',
    'tests/test_bw_api_m2.py': 'M.11',
    'tests/test_bw_api_m5.py': 'M.11',
    'tests/test_bw_api_m6.py': 'M.11',
    'tests/test_bw_api_m7.py': 'M.11',
    'tests/test_bw_api_parity.py': 'M.11',
    'tests/test_bw_review_followups.py': 'M.11',
    'tests/test_bw_security.py': 'M.11',
    'tests/test_bw_wishlists_api.py': 'M.11',
    'tests/test_bw_currency_39_api.py': 'M.11',
}
