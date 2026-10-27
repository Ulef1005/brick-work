"""Which browser screens run on the 4.0 store (M.8a, issue #110).

From M.8a the app opens only a 4.0 collection. Screens are ported piece by piece (M.8b to M.8j); until a screen is ported it
answers 503 with a plain page instead of a database error. A piece lists its endpoints in `PORTED` when its tests are green on 4.0
fixtures; the quarantine list (`tests/quarantine.py`) shrinks in the same commit."""
from flask import render_template, request

# Endpoints that need no ported module: the install files and the login page.
PORTED = {'web.web_manifest', 'web.shell_worker'}
# M.8b: the collection's read side. The jump search is a read.
PORTED |= {'index.index', 'web.bw_sets', 'web.bw_collection', 'web.bw_collection_item', 'web.bw_collection_item_by_number',
           'web.bw_collection_wishes', 'web.bw_collection_wish', 'web.bw_collection_lot', 'web.bw_collection_places', 'web.bw_collection_jump'}
# M.8c: Add (search, review, confirm, undo) and the progress of the jobs it queues.
PORTED |= {'web.bw_add', 'web.bw_add_search', 'web.bw_add_review', 'web.bw_add_confirm', 'web.bw_add_undo', 'web.bw_add_job', 'web.bw_add_retry'}
# M.10 B: merge, unmerge and the preferred link, from the item page.
PORTED |= {'web.bw_item_merge', 'web.bw_item_identity'}
# M.8d: Check Set Parts (chooser, copy, figure line; each with its write), the collection's writes (save, archive, Undo, photo, caption, lot,
# wish) and the media handlers for own photos, pictures and instruction PDFs.
PORTED |= {'web.bw_check_parts', 'web.bw_check_copy', 'web.bw_check_figure', 'web.bw_check_write', 'web.bw_check_figure_write',
           'web.bw_collection_write', 'web.bw_image', 'web.bw_instruction_download'}
# M.8e: the Workbench (Part Picker, Matcher, Found it, booklets, Take and Give, Undo), Storage with its history, Part to Inventory (the page, its
# save and Undo; the photo recognition behind it is Identify, M.8h) and the printable lists and their CSV.
PORTED |= {'web.bw_picker', 'web.bw_matcher', 'web.bw_workbench_save', 'web.bw_storages', 'web.bw_storage_action',
           'web.bw_inventory', 'web.bw_inventory_save', 'web.bw_inventory_undo', 'web.bw_list_print', 'web.bw_list_csv'}
# M.8f: the Prices screen (shell, records, details, the price refresh behind its Update buttons and the item page's).
PORTED |= {'web.bw_planning', 'web.bw_prices_records', 'web.bw_prices_details', 'web.bw_planning_write'}
# M.8g: the Wishlist and Complete sets screens (they share `web.bw_planning`) with their writes (pin, repair settings, export, Undo) and the
# wishlist management and exports.
PORTED |= {'web.bw_wishlists_write', 'web.bw_wishlists_export'}
# M.8h: Orders (import, review, count, allocate, reconcile, the short list, the CSV export) and Identify (the photo recognition of Part to Inventory
# and What is this?; Add's photo mode runs through Add's own endpoints).
PORTED |= {'web.bw_orders', 'web.bw_order', 'web.bw_orders_action', 'web.bw_order_short', 'web.bw_orders_export', 'web.bw_inventory_detect',
           'web.bw_what_is_this'}
# M.8i: Tools & Admin (the hub, Catalogues & keys, Jobs, Bulk refresh, Statistics, Values, Database, Settings, Appearance, About, Identify
# history, Instruction files, Unresolved items), API tokens and the database export.
PORTED |= {'web.bw_tools', 'web.bw_admin', 'web.bw_admin_write', 'web.bw_tokens', 'web.bw_tokens_write', 'web.bw_export'}
# M.8j: Collection sync (sources, link, pull and send plans, their writes) and Import from BrickTracker (upload, plan, apply, Undo).
PORTED |= {'web.bw_sync', 'web.bw_sync_link', 'web.bw_sync_plan', 'web.bw_sync_write', 'web.bw_import_legacy', 'web.bw_import_upload',
           'web.bw_import_plan', 'web.bw_import_apply', 'web.bw_import_undo'}
# M.10 A: the copy page's Part list (the Switch sheet's body; its writes are `web.bw_collection_write`).
PORTED |= {'web.bw_copy_part_list', 'web.bw_add_picture_known'}
PIECE = 'M.11'


def holding(what=None, piece=None):
    response = render_template('web/toni/web/ported_hold.html', piece=piece or PIECE, what=what or request.path)
    return response, 503


def install(app):
    @app.before_request
    def hold_unported_screens():
        endpoint = request.endpoint
        if endpoint is None or endpoint in PORTED:
            return None
        if not (endpoint.startswith('web.') or endpoint == 'index.index'):
            return None
        from .auth import LoginManager
        if not LoginManager.is_authenticated():
            return None                                   # the screen's own login redirect comes first
        return holding()
