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
    'tests/test_bw_lists_43_api.py': 'M.11',
    # M.8j split this out of a file it ported (the test that belongs to a later piece moved, none was added): out of test_bw_sync.py the API test (M.11).
    'tests/test_bw_sync_api.py': 'M.11',
    # M.11: API v2 and clients: the v1 API, MCP and contract tests
    'tests/test_app_factory.py': 'M.11',
    'tests/test_bw_api_47.py': 'M.11',
    'tests/test_bw_api_jobs_followup.py': 'M.11',
    'tests/test_bw_api_m0.py': 'M.11',
    'tests/test_bw_api_m1.py': 'M.11',
    'tests/test_bw_api_m1_contract.py': 'M.11',
    'tests/test_bw_api_m2.py': 'M.11',
    'tests/test_bw_api_m3.py': 'M.11',
    'tests/test_bw_api_m4.py': 'M.11',
    'tests/test_bw_api_m5.py': 'M.11',
    'tests/test_bw_api_m6.py': 'M.11',
    'tests/test_bw_api_m7.py': 'M.11',
    'tests/test_bw_api_parity.py': 'M.11',
    'tests/test_bw_api_take_figure.py': 'M.11',
    'tests/test_bw_body_limits_62.py': 'M.11',
    'tests/test_bw_check_api_63.py': 'M.11',
    'tests/test_bw_core_fixes_api.py': 'M.11',
    'tests/test_bw_media_27.py': 'M.11',
    'tests/test_bw_perf_api.py': 'M.11',
    'tests/test_bw_review_followups.py': 'M.11',
    'tests/test_bw_security.py': 'M.11',
    'tests/test_bw_throttle.py': 'M.11',
    'tests/test_bw_wishlists_api.py': 'M.11',
    'tests/test_bw_currency_39_api.py': 'M.11',
    'tests/test_bw_partout_38_api.py': 'M.11',
    'tests/test_bw_wish_progress_35_api.py': 'M.11',
    'tests/test_runtime_contract.py': 'M.11',
}
