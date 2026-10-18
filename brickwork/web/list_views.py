"""#43 Printable lists and CSV: missing parts, Part Picker results and the wishlist."""
from contextlib import closing
from datetime import date
import sqlite3

from flask import abort, current_app, render_template, request, url_for
from flask_login import login_required

from .views import web_page

KINDS = {'missing': 'Missing parts', 'picker': 'Part Picker', 'wishlist': 'Wishlist'}


def _rows(kind):
    from ..core import list_exports
    from ..core.admin import database
    from .admin_ops import brickwork_path
    with database(brickwork_path(), read_only=True) as db:
        if kind == 'missing':
            copies = request.args.getlist('copy')
            if not copies:
                raise ValueError('Choose the sets whose missing parts to list')
            return list_exports.missing(db, copies), copies
        if kind == 'picker':
            copies = request.args.getlist('copy')
            if not copies:
                raise ValueError('Choose the sets to pick parts for')
            return list_exports.picker(db, copies, request.args.getlist('rank') or None), copies
        return list_exports.wishlist(db, request.args.get('list', 'all')), []


def _images(rows):
    """Item pictures for the printed rows, one query."""
    from ..core.admin import database
    from .admin_ops import brickwork_path
    import json
    keys = sorted({(r['item_type'], r['item_no'], r.get('color_id')) for r in rows})
    if not keys:
        return {}
    with database(brickwork_path(), read_only=True) as db:
        found = {}
        for r in db.execute('''SELECT item_type,item_no,color_id,min(id) AS id FROM item_images
                WHERE (item_type||char(31)||item_no) IN (SELECT value FROM json_each(?)) GROUP BY 1,2,3''',
                (json.dumps(sorted({t + '\x1f' + n for t, n, _ in keys})),)):
            found.setdefault((r['item_type'], r['item_no'], r['color_id']), r['id'])
            found.setdefault((r['item_type'], r['item_no'], None), r['id'])
    return found


@web_page.get('/lists/<kind>/print')
@login_required
def bw_list_print(kind):
    if kind not in KINDS:
        abort(404)
    error, rows, copies = None, [], []
    try:
        rows, copies = _rows(kind)
    except (ValueError, sqlite3.Error) as exc:
        error = str(exc)
    pictures = request.args.get('pictures', '1') != '0'
    images = _images(rows) if pictures and rows else {}
    from .ui import passthrough_args
    args = passthrough_args('kind')
    args['pictures'] = ['0' if pictures else '1']
    toggle_url = url_for('web.bw_list_print', kind=kind, **args)
    back_url = (url_for('web.bw_planning', screen='complete-sets') if kind == 'missing'
                else url_for('web.bw_picker', copy=copies, pick='1') if kind == 'picker'
                else url_for('web.bw_planning', screen='wishlist', list=request.args.get('list', 'all')))
    response = current_app.make_response(render_template('web/toni/web/bw_print_list.html', kind=kind, title=KINDS[kind],
        rows=rows, copies=copies, error=error, pictures=pictures, images=images, today=date.today().isoformat(),
        total=sum(r['quantity'] or 0 for r in rows), toggle_url=toggle_url, back_url=back_url, csv_url=url_for('web.bw_list_csv', kind=kind, **passthrough_args('kind'))))
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/lists/<kind>.csv')
@login_required
def bw_list_csv(kind):
    from ..core import list_exports
    if kind not in KINDS:
        abort(404)
    try:
        rows, _ = _rows(kind)
    except (ValueError, sqlite3.Error) as exc:
        return current_app.response_class(str(exc), status=400, mimetype='text/plain')
    response = current_app.response_class(list_exports.to_csv(kind, rows), mimetype='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename=brickwork-{kind}-{date.today().isoformat()}.csv'
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/workbench/orders/export.csv')
@login_required
def bw_orders_export():
    """#44: order lines or a per-order summary as CSV, for a date range and a store."""
    from ..core import order_exports
    from ..core.admin import database
    from .admin_ops import brickwork_path
    kind = request.args.get('kind', 'lines')
    try:
        with database(brickwork_path(), read_only=True) as db:
            data = order_exports.rows(db, kind, request.args.get('from') or None, request.args.get('to') or None,
                                      request.args.get('store') or None)
    except (ValueError, sqlite3.Error) as exc:
        return current_app.response_class(str(exc), status=400, mimetype='text/plain')
    response = current_app.response_class(order_exports.to_csv(kind, data), mimetype='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename=brickwork-orders-{kind}-{date.today().isoformat()}.csv'
    response.headers['Cache-Control'] = 'no-store'
    return response


@web_page.get('/workbench/what-is-this')
@login_required
def bw_what_is_this():
    """#45: identify a part or minifigure by photo and see what you already have of it."""
    from .views import bw_add_token, bw_collection_editable
    from .setup_state import key_missing
    response = current_app.make_response(render_template('web/toni/web/bw_what_is_this.html', csrf_token=bw_add_token(),
        can_edit=bw_collection_editable(), detect_url=url_for('web.bw_inventory_detect')))
    response.headers['Cache-Control'] = 'no-store'
    return response
