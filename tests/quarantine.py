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
    # test_runtime_contract.py; M.11b and M.11c the reads and the writes of the v1 tests (tests/test_api2_read*.py, tests/test_api2_write*.py);
    # M.11d the rest of them, or deleted what had no 4.0 premise (see the commit of M.11d).
    # M.11e (issue #113) emptied the list: the MCP on API v2 and the v2 parity test. The six files that were left:
    #   test_bw_api_m7 -> tests/test_api2_mcp.py (the generated surface, the gate, every tool's round trip, the resources, the transports, the CLI flags;
    #     new: tools take numbers and a provider, never an item id); the cases on the v1 id spellings (`item_type`/`item_no`, `type`/`no` path
    #     parameters, `color_id`) are gone with those spellings;
    #   test_bw_throttle_mcp -> the same file (the in-process client carries the caller address);
    #   test_bw_wishlists_api -> the same file (the wishlist tools and their exports);
    #   test_bw_api_parity -> tests/test_api2_parity.py (every v2 operation routed and implemented, every tool one operation, the tool list is the
    #     contract's);
    #   test_bw_api_m1_contract -> tests/test_api2_parity.py (the strict loader and the closed schemas); its generated per-status cases ran the
    #     v1 M1 table (tokens, events) against v1 routes: deleted, v2 answers are validated against the contract in every test since M.11b;
    #   test_runtime_contract_mcp -> ported in place (the missing contract is now the v2 file).
}
