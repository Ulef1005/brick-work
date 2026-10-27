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
# M.8d: Check Set Parts (chooser, copy, figure line; each with its write), the collection's writes (save, archive, Undo, photo, caption, lot,
# wish) and the media handlers for own photos, pictures and instruction PDFs.
PORTED |= {'web.bw_check_parts', 'web.bw_check_copy', 'web.bw_check_figure', 'web.bw_check_write', 'web.bw_check_figure_write',
           'web.bw_collection_write', 'web.bw_image', 'web.bw_instruction_download'}
PIECE = 'M.8e to M.8j'


def holding(what=None):
    response = render_template('web/toni/web/ported_hold.html', piece=PIECE, what=what or request.path)
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
