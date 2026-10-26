"""Which browser screens run on the 4.0 store (M.8a, issue #110).

From M.8a the app opens only a 4.0 collection. Screens are ported piece by piece (M.8b to M.8j); until a screen is ported it
answers 503 with a plain page instead of a database error. A piece lists its endpoints in `PORTED` when its tests are green on 4.0
fixtures; the quarantine list (`tests/quarantine.py`) shrinks in the same commit.

`HELD` names endpoints with a temporary stand-in: the collection list shows the first-run page on an empty collection and the
holding page otherwise (the real list is M.8b)."""
from flask import render_template, request

# Endpoints that need no ported module: the install files and the login page.
PORTED = {'web.web_manifest', 'web.shell_worker'}
PIECE = 'M.8b to M.8j'


def holding(what=None):
    response = render_template('web/toni/web/ported_hold.html', piece=PIECE, what=what or request.path)
    return response, 503


def collection_stand_in():
    """The collection list until M.8b: first-run guidance when the collection holds no copy, else the holding page."""
    from contextlib import closing
    import sqlite3
    from flask import current_app, make_response
    from ..core.admin import database
    from . import setup_state, ui
    from .admin_ops import brickwork_path
    from .views import bw_add_token, bw_collection_editable
    kind = (request.view_args or {}).get('kind', 'S').upper()
    try:
        with database(brickwork_path(), read_only=True, require_catalogue=False) as db:
            copies = db.execute('SELECT count(*) FROM copy').fetchone()[0]
    except (sqlite3.Error, OSError, ValueError):
        copies = 0
    if copies or kind != 'S':
        return holding()
    response = make_response(render_template('web/toni/web/bw_collection.html',
        title='Sets', kind='S', rows=[], records=ui.bw_collection_records([]),
        choices=dict(storages=[], places=[], lots=[], flags=[], colours=[]), error=None,
        csrf_token=bw_add_token(), can_edit=bw_collection_editable(), detail=None,
        first_run=setup_state.first_run(bw_collection_editable())))
    response.headers['Cache-Control'] = 'no-store'
    return response


HELD = {'web.bw_sets': collection_stand_in, 'web.bw_collection': collection_stand_in, 'index.index': collection_stand_in}


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
        stand_in = HELD.get(endpoint)
        return stand_in() if stand_in else holding()
