"""The tests that wait for their module's port to the 4.0 store (M.8a, issue #110).

From M.8a the app opens only a 4.0 collection. A test file that still builds the 3.3 store (or imports a module no piece has ported yet)
cannot run; it is listed here with the piece that ports it (the #110 scope comment: M.8b to M.8j, and M.11 for the v1 API, whose
routes answer 410 until v2). `conftest.py` skips these files (`collect_ignore`); `scripts/check.sh` prints how many are left.

The list can only shrink: a piece removes its files here in the commit that rewrites them on 4.0 fixtures and turns them green
(`tests/test_quarantine.py` freezes the baseline). Nothing is deleted from this list by being forgotten: a file that exists and is not
listed runs.
"""

QUARANTINE = {
    # M.8d: Check Set Parts on part_check, collection writes, flags, photos
    'tests/test_web_unsigned_text.py': 'M.8g',
    # M.8f ported its files (sources, pictures, prices on provider_key, keys). Left here, re-labelled to the piece they belong to: the Catalogues & keys
    # screen tests (M.8i); split off by M.8f from files it ported: the 3.3 BrickLink XML loader, the CLI/export redaction, the Tools & Admin speed and
    # first-run tests, the Statistics retail test (M.8i), the Wishlist retail test (M.8g), the API speed tests (M.11).
    'tests/test_bw_api_m5_web.py': 'M.8i',
    'tests/test_bw_ui_12l.py': 'M.8i',
    # M.8g: planning, partout, wishlists, money
    'tests/test_bw_currency_39.py': 'M.8g',
    'tests/test_bw_partout_38.py': 'M.8g',
    'tests/test_bw_planning.py': 'M.8g',
    'tests/test_bw_wish_currency.py': 'M.8g',
    'tests/test_bw_wish_progress_35.py': 'M.8g',
    'tests/test_bw_retail_26_wishlist.py': 'M.8g',
    'tests/test_bw_wishlists.py': 'M.8g',
    # M.8h: orders, identify
    'tests/test_bw_orders_design.py': 'M.8h',
    'tests/test_bw_orders_export_44.py': 'M.8h',
    'tests/test_bw_orders_storage.py': 'M.8h',
    'tests/test_bw_ownership_45.py': 'M.8h',
    # M.8i: identity admin, merge/unmerge, settings, CLI, maintenance
    'tests/test_admin_ops.py': 'M.8i',
    'tests/test_bricklink_catalogue_xml.py': 'M.8i',
    'tests/test_bw_perf_admin.py': 'M.8i',
    'tests/test_bw_retail_26_statistics.py': 'M.8i',
    'tests/test_bw_ui_12j_later.py': 'M.8i',
    'tests/test_secret_redaction_cli_export.py': 'M.8i',
    'tests/test_bw_admin.py': 'M.8i',
    'tests/test_bw_collection_colours.py': 'M.8i',
    'tests/test_bw_lists_43_api.py': 'M.11',
    'tests/test_bw_lists_43_later.py': 'M.8g',
    'tests/test_shell_45s_later.py': 'M.8g',
    'tests/test_bw_admin_csrf.py': 'M.8i',
    'tests/test_bw_small_68.py': 'M.8i',
    'tests/test_bw_ui_12m.py': 'M.8i',
    'tests/test_bw_ui_5049.py': 'M.8i',
    'tests/test_ui_47b.py': 'M.8i',
    'tests/test_jump_and_rail.py': 'M.8i',
    'tests/test_safe_errors.py': 'M.8i',
    'tests/test_shell_46p.py': 'M.8i',
    'tests/test_ui_p6.py': 'M.8i',
    # M.8j: sync, BrickTracker rewrite, demo, the two guards
    'tests/importer/test_bricktracker_import.py': 'M.8j',
    'tests/importer/test_importer.py': 'M.8j',
    'tests/test_bw_import_ui.py': 'M.8j',
    'tests/test_bw_migrate_paths_61.py': 'M.8j',
    'tests/test_bw_sync.py': 'M.8j',
    'tests/test_bw_sync_ui.py': 'M.8j',
    'tests/test_demo.py': 'M.8j',
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
    'tests/test_runtime_contract.py': 'M.11',
}
