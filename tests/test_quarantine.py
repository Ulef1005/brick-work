"""The quarantine can only shrink and nothing live leans on it (M.8a, issue #110; tests/quarantine.py)."""
import ast
from pathlib import Path

from tests.quarantine import QUARANTINE

ROOT = Path(__file__).resolve().parents[1]
PIECES = {'M.8b', 'M.8c', 'M.8d', 'M.8e', 'M.8f', 'M.8g', 'M.8h', 'M.8i', 'M.8j', 'M.11'}

# Frozen at M.8a. A piece removes its files from tests/quarantine.py; it never adds one here or there.
BASELINE = frozenset((
    'tests/importer/test_bricktracker_import.py',
    'tests/importer/test_importer.py',
    'tests/test_admin_ops.py',
    'tests/test_app_factory.py',
    'tests/test_brickwork_pipeline.py',
    'tests/test_brickwork_rebrickable.py',
    'tests/test_brickwork_schema.py',
    'tests/test_brickwork_sources.py',
    'tests/test_bw_48a.py',
    'tests/test_bw_48c.py',
    'tests/test_bw_49a.py',
    'tests/test_bw_49b.py',
    'tests/test_bw_add.py',
    'tests/test_bw_admin.py',
    'tests/test_bw_admin_csrf.py',
    'tests/test_bw_api_47.py',
    'tests/test_bw_api_jobs_followup.py',
    'tests/test_bw_api_m0.py',
    'tests/test_bw_api_m1.py',
    'tests/test_bw_api_m1_contract.py',
    'tests/test_bw_api_m2.py',
    'tests/test_bw_api_m3.py',
    'tests/test_bw_api_m4.py',
    'tests/test_bw_api_m5.py',
    'tests/test_bw_api_m5_web.py',
    'tests/test_bw_api_m6.py',
    'tests/test_bw_api_m7.py',
    'tests/test_bw_api_parity.py',
    'tests/test_bw_api_take_figure.py',
    'tests/test_bw_body_limits_62.py',
    'tests/test_bw_check_api_63.py',
    'tests/test_bw_checker.py',
    'tests/test_bw_collection.py',
    'tests/test_bw_collection_47d.py',
    'tests/test_bw_collection_48d.py',
    'tests/test_bw_core_fixes.py',
    'tests/test_bw_currency_39.py',
    'tests/test_bw_first_run_60.py',
    'tests/test_bw_import_ui.py',
    'tests/test_bw_list_cost.py',
    'tests/test_bw_lists_43.py',
    'tests/test_bw_listspeed.py',
    'tests/test_bw_media_27.py',
    'tests/test_bw_migrate_paths_61.py',
    'tests/test_bw_orders_design.py',
    'tests/test_bw_orders_export_44.py',
    'tests/test_bw_orders_storage.py',
    'tests/test_bw_ownership_45.py',
    'tests/test_bw_part_inventory.py',
    'tests/test_bw_partout_38.py',
    'tests/test_bw_perf.py',
    'tests/test_bw_pictures.py',
    'tests/test_bw_planning.py',
    'tests/test_bw_prices.py',
    'tests/test_bw_retail_26.py',
    'tests/test_bw_review_followups.py',
    'tests/test_bw_security.py',
    'tests/test_bw_size_search_41.py',
    'tests/test_bw_small_68.py',
    'tests/test_bw_stock.py',
    'tests/test_bw_storage_46.py',
    'tests/test_bw_storage_archive.py',
    'tests/test_bw_storage_ui.py',
    'tests/test_bw_sync.py',
    'tests/test_bw_sync_ui.py',
    'tests/test_bw_throttle.py',
    'tests/test_bw_thumbnails.py',
    'tests/test_bw_ui_12f.py',
    'tests/test_bw_ui_12j.py',
    'tests/test_bw_ui_12l.py',
    'tests/test_bw_ui_12m.py',
    'tests/test_bw_ui_1d.py',
    'tests/test_bw_ui_3332.py',
    'tests/test_bw_ui_5049.py',
    'tests/test_bw_ui_lists.py',
    'tests/test_bw_wish_currency.py',
    'tests/test_bw_wish_progress_35.py',
    'tests/test_bw_wishlists.py',
    'tests/test_bw_wishlists_api.py',
    'tests/test_bw_workbench.py',
    'tests/test_demo.py',
    'tests/test_import_polling.py',
    'tests/test_jump_and_rail.py',
    'tests/test_runtime_contract.py',
    'tests/test_safe_errors.py',
    'tests/test_secret_redaction.py',
    'tests/test_shell_41a.py',
    'tests/test_shell_45s.py',
    'tests/test_shell_46p.py',
    'tests/test_shell_49f.py',
    'tests/test_toni_shell.py',
    'tests/test_ui_47b.py',
    'tests/test_ui_p6.py',
    'tests/test_web_unsigned_text.py',
    # M.8d split these out of files it ported (tests that belong to a later piece moved, none was added): out of test_bw_collection.py
    # the Matching / Take and Give tests (M.8e) and the colours action (M.8i), out of test_bw_core_fixes.py the part inventory (M.8e) and API (M.11) tests.
    'tests/test_bw_collection_colours.py',
    'tests/test_bw_collection_matching.py',
    'tests/test_bw_core_fixes_api.py',
    'tests/test_bw_core_fixes_part_inventory.py',
    # M.8e split these out of files it ported (tests that belong to a later piece moved, none was added): out of test_bw_lists_43.py the API
    # exports (M.11) and the planning-screen entry points (M.8g), out of test_shell_45s.py the planning, prices and Tools and Admin paths (M.8g).
    'tests/test_bw_lists_43_api.py',
    'tests/test_bw_lists_43_later.py',
    'tests/test_shell_45s_later.py',
    # M.8f split these out of files it ported (tests that belong to a later piece moved, none was added): out of test_brickwork_sources.py the 3.3
    # BrickLink XML loader (M.8i), out of test_bw_retail_26.py the Wishlist line (M.8g) and the Statistics page (M.8i), out of test_bw_perf.py the
    # Tools & Admin tests (M.8i) and the API ones (M.11), out of test_bw_ui_12j.py the bulk-refresh and Catalogues & keys test (M.8i), out of
    # test_secret_redaction.py the CLI error and the export (M.8i).
    'tests/test_bricklink_catalogue_xml.py',
    'tests/test_bw_perf_admin.py',
    'tests/test_bw_perf_api.py',
    'tests/test_bw_retail_26_statistics.py',
    'tests/test_bw_retail_26_wishlist.py',
    'tests/test_bw_ui_12j_later.py',
    'tests/test_secret_redaction_cli_export.py',
    # M.8g split these out of files it ported (tests that belong to a later piece moved, none was added): out of test_bw_currency_39.py the API
    # (M.11) and Settings page (M.8i) tests, out of test_bw_partout_38.py and test_bw_wish_progress_35.py the API ones (M.11), out of
    # test_shell_45s.py the Tools and Admin path (M.8i).
    'tests/test_bw_currency_39_api.py',
    'tests/test_bw_currency_39_settings.py',
    'tests/test_bw_partout_38_api.py',
    'tests/test_bw_wish_progress_35_api.py',
    'tests/test_shell_45s_tools.py',
    # M.8h split these out of files it ported (tests that belong to a later piece moved, none was added): out of test_bw_orders_storage.py and
    # test_bw_orders_export_44.py the API receipts, history and export tests (M.11).
    'tests/test_bw_orders_export_44_api.py',
    'tests/test_bw_orders_storage_api.py',
))


def test_every_entry_exists_and_names_a_piece():
    for name, piece in QUARANTINE.items():
        assert (ROOT / name).is_file(), f'{name} is listed but does not exist (delete the entry when the file is deleted)'
        assert piece in PIECES, f'{name}: {piece} is not a piece of the #110 plan'


def test_the_list_is_a_subset_of_the_frozen_baseline():
    grown = sorted(set(QUARANTINE) - BASELINE)
    assert not grown, f'the quarantine can only shrink; new entries: {grown}'


def imported_modules(path):
    """The `tests.*` modules a file imports, as repo-relative paths (absolute and relative imports)."""
    tree = ast.parse(path.read_text())
    package = ['tests'] + list(path.relative_to(ROOT / 'tests').parent.parts)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                base = '.'.join(package[:len(package) - node.level + 1] + ([base] if base else []))
            names = [base] + [f'{base}.{alias.name}' for alias in node.names]
        else:
            continue
        for name in names:
            if name.split('.')[0] == 'tests':
                found.add('/'.join(name.split('.')) + '.py')
    return found


def test_no_live_test_imports_a_quarantined_module():
    offenders = []
    for path in sorted((ROOT / 'tests').rglob('*.py')):
        name = path.relative_to(ROOT).as_posix()
        if name in QUARANTINE:
            continue
        for imported in imported_modules(path) & set(QUARANTINE):
            offenders.append(f'{name} imports {imported}')
    assert not offenders, offenders


def test_the_scan_sees_an_import():
    assert 'tests/quarantine.py' in imported_modules(ROOT / 'tests' / 'conftest.py')
