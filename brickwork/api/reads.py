"""Read transport: authorize, parse, call a core projection, then serialize."""
import json
from flask import Response, jsonify, request, send_file

from . import api, database
from .serializers import public
from ..core import add, admin, api_reads as read, api_orders, checker, collection, errors, orders, planning, workbench
from ..core.listing import FILTERS, filter_rows, paginate


SHAPES = {'get_catalogue_items': ['CatalogueItem'],
 'get_catalogue_items_by_type_by_no': 'CatalogueItem',
 'get_catalogue_status': 'CatalogueStatus',
 'get_colors': ['Color'],
 'get_colors_by_color_id': 'Color',
 'get_items': ['Item'],
 'get_items_by_type_by_no': 'ItemDetail',
 'get_items_by_type_by_no_inventory': ['InventoryLine'],
 'get_items_by_type_by_no_used_in': ['UsedIn'],
 'get_items_by_type_by_no_colors': ['Color'],
 'get_items_by_type_by_no_images': ['Image'],
 'get_copies': ['Copy'],
 'get_copies_by_id': 'Copy',
 'get_copies_by_id_completeness': 'Completeness',
 'get_copies_by_id_check': 'CheckState',
 'get_copies_by_id_gaps': ['Gap'],
 'get_copies_by_id_matches': ['Match'],
 'get_copies_by_id_parts': ['CopyPart'],
 'get_copies_by_id_figures': ['CopyFigure'],
 'get_stock': ['Stock'],
 'get_stock_by_id': 'Stock',
 'get_stock_by_id_parts': ['LooseFigurePart'],
 'get_minifigures': ['MinifigureRow'],
 'get_minifigures_by_no': 'ItemDetail',
 'get_unresolved': ['Unresolved'],
 'get_id_matches': ['IdMatch'],
 'get_gaps': ['Gap'],
 'get_matches': ['Match'],
 'get_instruction_files': ['InstructionFile'],
 'get_instruction_files_by_id': 'InstructionFile',
 'get_prices': ['PriceCurrent'],
 'get_items_by_type_by_no_prices': 'ItemPrices',
 'get_items_by_type_by_no_prices_history': ['PriceObservation'],
 'get_prices_stale': ['StaleItem'],
 'get_wishlists': ['Wishlist'],
 'get_wishes': ['Wish'],
 'get_wishes_by_id': 'Wish',
 'get_storages': ['Storage'],
 'get_storages_by_id': 'StorageDetail',
 'get_lots': ['Lot'],
 'get_lots_by_id': 'LotDetail',
 'get_places': ['Place'],
 'get_flags': ['Flag'],
 'get_planning_ranking': ['RankingRow'],
 'get_orders_by_id_allocation_review': ['OrderReview'],
 'get_orders_by_id_allocations': ['Allocation'],
 'get_orders_by_id_history': ['OrderHistory'],
 'get_orders': ['Order'],
 'get_orders_by_id': 'OrderDetail',
 'get_events': ['Event'],
 'get_events_by_id': 'Event',
 'get_jobs': ['Job'],
 'get_jobs_by_id': 'Job',
 'get_sources': ['Source'],
 'get_settings': 'Settings',
 'get_statistics': 'Statistics',
 'get_database_check': 'DatabaseCheck',
 'get_identifications': ['Identification'],
 'get_identifications_id': 'Identification'}


def response_shape():
    return SHAPES[request.endpoint.split(".")[-1]]


COMMON = {'list', 'q', 'sort', 'direction', 'cursor', 'limit'} | FILTERS


def query(extra=()):
    if set(request.args) - COMMON - set(extra):
        raise errors.UnknownFilter()
    if any(len(request.args.getlist(k)) != 1 for k in request.args):
        raise errors.BadRequest('Repeat a query parameter only where documented')
    return request.args.to_dict()


def single(value, etag=False):
    args = query()
    if 'color_id' in args and isinstance(value, dict) and 'current' in value:
        value = {k: [r for r in v if str(r.get('color_id')) == args['color_id']] for k, v in value.items()}
    response = jsonify(data=public(value, response_shape()))
    if etag:
        response.set_etag(etag if isinstance(etag, str) else read.etag(value))
    return response


def page(values, default_sort='number', default_direction='asc', metadata=None):
    args = query()
    filters = {k: v for k, v in args.items() if k in FILTERS}
    if filters.get('archived') == 'true': filters['archived'] = 'include'
    sort, direction = args.get('sort', default_sort), args.get('direction', default_direction)
    pairs = []
    for index, raw in enumerate(values):
        adapted = read.listing_record(raw)
        adapted['_api_colour_id'] = str(raw.get('color_id')) if raw.get('color_id') is not None else 'null'
        adapted['id'] = read.cursor_id(raw)
        adapted['index'] = raw.get('id') if isinstance(raw.get('id'), int) else index
        adapted['_raw'] = raw
        pairs.append(adapted)
    filtered = filter_rows(pairs, args.get('q', ''), filters, sort, direction)
    result = paginate(filtered, cursor=args.get('cursor'), limit=args.get('limit', 50), sort=sort, direction=direction,
                      signature=json.dumps([request.path, {k: v for k, v in args.items() if k not in ('cursor', 'limit')}], sort_keys=True))
    result['data'] = [public(r['_raw'], response_shape()[0]) for r in result['data']]
    if args.get('q') or args.get('archived'):
        result['page']['total'] = None
    if metadata:
        result.update(read.serialize(metadata))
        if 'settings' in metadata:
            result['settings'] = public(metadata['settings'], 'Settings')
    return jsonify(result)


def install():
    """Explicit route manifest, mirrored by the OpenAPI operation table."""
    lists = {
        '/catalogue/items': lambda db: read.catalogue(db),
        '/colors': add.colors,
        '/items': read.items,
        '/copies': lambda db: read.entities(db, 'copy'),
        '/stock': lambda db: read.entities(db, 'stock'),
        '/wishes': lambda db: [r for r in read.entities(db, 'wish') if not request.args.get('list') or r['list_id']==request.args['list']],
        '/minifigures': lambda db: collection.listing(db, 'M'),
        '/unresolved': admin.unresolved,
        '/id-matches': lambda db: read.resource_rows(db, 'id-matches'),
        '/gaps': workbench.gaps,
        '/matches': workbench.matches,
        '/instruction-files': lambda db: read.resource_rows(db, 'instruction-files'),
        '/prices': read.current_prices,
        '/prices/stale': read.stale_prices,
        '/storages': read.storages,
        '/lots': read.lots,
        '/places': read.places,
        '/flags': lambda db: read.resource_rows(db, 'flags'),
        '/orders': orders.listing,
        '/events': read.events,
        '/jobs': read.jobs,
        '/sources': read.sources,
        '/identifications': lambda db: read.resource_rows(db, 'identifications'),
    }
    for path, backing in lists.items():
        def handler(backing=backing, path=path):
            if path in ('/events', '/jobs', '/prices'):
                from ..core import api_pages
                result = api_pages.page(database(), path[1:], query())
                result['data'] = [public(r, response_shape()[0]) for r in result['data']]
                return jsonify(result)
            return page(backing(database()), metadata={'coverage': read.instruction_coverage(database())} if path == '/instruction-files' else None)
        endpoint = 'get_' + path.strip('/').replace('/', '_').replace('-', '_')
        api.add_url_rule(path, endpoint, handler, methods=['GET'])


install()


@api.get('/catalogue/items/<type>/<no>')
def get_catalogue_items_by_type_by_no(type, no):
    if not add.catalogue_path(database()).is_file():
        raise errors.CatalogueNotLoaded()
    value = add.lookup(database(), type, no)
    if value is None: raise errors.NotFound()
    return single(value)


@api.get('/catalogue/status')
def get_catalogue_status():
    return single(read.catalogue_status(database()))


@api.get('/colors/<int:color_id>')
def get_colors_by_color_id(color_id):
    return single(read.record(database(), 'colors', color_id))


@api.get('/items/<type>/<no>')
def get_items_by_type_by_no(type, no):
    return single(read.item(database(), type, no))


@api.get('/minifigures/<no>')
def get_minifigures_by_no(no):
    return single(read.item(database(), 'M', no))


@api.get('/items/<type>/<no>/inventory')
def get_items_by_type_by_no_inventory(type, no):
    return page(read.inventory(database(), type, no))


@api.get('/items/<type>/<no>/used-in')
def get_items_by_type_by_no_used_in(type, no):
    return page(read.used_in(database(), type, no))


@api.get('/items/<type>/<no>/colors')
def get_items_by_type_by_no_colors(type, no):
    return page(read.item_colors(database(), type, no))


@api.get('/items/<type>/<no>/images')
def get_items_by_type_by_no_images(type, no):
    return page(read.images(database(), type, no))


@api.get('/copies/<id>')
def get_copies_by_id(id):
    from ..core import partout
    value = read.entity(database(), 'copy', id)
    # #38: the part-out value of this copy (value, coverage and the unpriced lines); not part of the ETag.
    po = partout.values(database(), [value['id']]).get(value['id'])
    if po:
        po = {k: v for k, v in po.items() if k not in ('enough', 'unpriced_items')}
    value = dict(value, partout=po)
    return single(value, etag=read.entity_etag(database(), 'copy', id))


@api.get('/stock/<id>')
def get_stock_by_id(id):
    return single(read.entity(database(), 'stock', id), etag=read.entity_etag(database(), 'stock', id))


@api.get('/wishes/<int:id>')
def get_wishes_by_id(id):
    return single(read.entity(database(), 'wish', id), etag=read.entity_etag(database(), 'wish', id))


@api.get('/copies/<id>/parts')
def get_copies_by_id_parts(id):
    return page(read.child_rows(database(), 'parts', id))


@api.get('/copies/<id>/figures')
def get_copies_by_id_figures(id):
    return page(read.child_rows(database(), 'figures', id))


@api.get('/stock/<id>/parts')
def get_stock_by_id_parts(id):
    return page(read.child_rows(database(), 'stock-parts', id))


@api.get('/copies/<id>/completeness')
def get_copies_by_id_completeness(id):
    return single(read.completeness_read(database(), id))


@api.get('/copies/<id>/check')
def get_copies_by_id_check(id):
    read.entity(database(), 'copy', id)
    return single(checker.view(database(), id, read.root(database())))


@api.get('/copies/<id>/gaps')
def get_copies_by_id_gaps(id):
    read.entity(database(), 'copy', id)
    return page([r for r in workbench.gaps(database()) if r['copy_id'] == id])


@api.get('/copies/<id>/matches')
def get_copies_by_id_matches(id):
    read.entity(database(), 'copy', id)
    return page([r for r in workbench.matches(database()) if r['copy_id'] == id])


@api.get('/items/<type>/<no>/prices')
def get_items_by_type_by_no_prices(type, no):
    observations = read.price_history(database(), type, no)
    return single(dict(current=read.current_prices(database(), type, no), observations=observations))


@api.get('/items/<type>/<no>/prices/history')
def get_items_by_type_by_no_prices_history(type, no):
    from ..core import api_pages
    read.one(database(), 'SELECT 1 FROM items WHERE item_type=? AND item_no=?', (type,no))
    result=api_pages.page(database(),'price-history',dict(query(),item_type=type,item_no=no))
    result['data']=[public(r,'PriceObservation') for r in result['data']]
    return jsonify(result)


@api.get('/instruction-files/<int:id>')
def get_instruction_files_by_id(id):
    return single(read.record(database(), 'instruction-files', id))


@api.get('/storages/<id>')
def get_storages_by_id(id):
    return single(read.storage(database(), id))


@api.get('/lots/<id>')
def get_lots_by_id(id):
    read.record(database(), 'lots', id)
    return single(collection.lot_detail(database(), id, include_archived=True))


@api.get('/orders/<int:id>')
def get_orders_by_id(id):
    read.record(database(), 'orders', id)
    return single(orders.detail(database(), id))


@api.get('/orders/<int:id>/short.xml')
def get_orders_by_id_short_xml(id):
    query()
    read.record(database(), 'orders', id)
    return Response(orders.short_xml(database(), id), mimetype='application/xml')


@api.get('/events/<int:id>')
def get_events_by_id(id):
    value = next((r for r in read.events(database(), id) if r['id'] == id), None)
    if value is None: raise errors.NotFound()
    return single(value)


@api.get('/jobs/<int:id>')
def get_jobs_by_id(id):
    return single(read.job(database(), id))


@api.get('/settings')
def get_settings():
    return single(admin.settings(database()))


@api.get('/statistics')
def get_statistics():
    return single(admin.statistics(database()))


@api.get('/planning/ranking')
def get_planning_ranking():
    result = planning.ranking(database())
    return page(result['rows'], default_sort='ranking', metadata={'settings': result['settings']})


def export_missing(xml):
    allowed = COMMON | {'ids', 'copy_id'}
    if set(request.args) - allowed: raise errors.UnknownFilter()
    ids = request.args.getlist('copy_id') or (request.args.get('ids', '').split(',') if request.args.get('ids') else [])
    result = read.missing(database(), ids, xml)
    if xml:
        return Response(result, mimetype='application/xml')
    return jsonify(data=read.serialize(result))


@api.get('/export/missing.xml')
def get_export_missing_xml():
    return export_missing(True)


@api.get('/export/missing.json')
def get_export_missing_json():
    return export_missing(False)


@api.get('/images/<int:id>/content')
def get_images_by_id_content(id):
    query()
    return send_file(read.content(database(), 'images', id))


@api.get('/instruction-files/<int:id>/content')
def get_instruction_files_by_id_content(id):
    query()
    return send_file(read.content(database(), 'instructions', id), mimetype='application/pdf', as_attachment=True, download_name='instructions.pdf')


@api.get('/identifications/<id>')
def get_identifications_id(id):
    archived = request.args.get('archived')
    if archived not in (None, 'true', 'false'):
        raise errors.UnknownFilter()
    return single(read.record(database(), 'identifications', id, archived=archived == 'true'))


@api.get('/identifications/<id>/thumb')
def get_identifications_id_thumb(id):
    query()
    return send_file(read.content(database(), 'identifications', id), mimetype='image/jpeg')


@api.get('/database/check')
def get_database_check():
    return single(admin.check(database()))


@api.get('/database/export')
def get_database_export():
    query()
    return Response(read.database_export(database()), mimetype='application/vnd.sqlite3',
                    headers={'Content-Disposition': 'attachment; filename=brickwork.db'})


@api.get('/orders/<int:id>/allocation-review')
def get_orders_by_id_allocation_review(id):
    query()
    return page(api_orders.listing(database(),id,'review'), default_sort='number')


@api.get('/orders/<int:id>/allocations')
def get_orders_by_id_allocations(id):
    query()
    return page(api_orders.listing(database(),id,'allocations'), default_sort='number')


@api.get('/orders/<int:id>/history')
def get_orders_by_id_history(id):
    query()
    return page(api_orders.listing(database(),id,'history'), default_sort='number')


@api.get('/wishlists')
def get_wishlists():
    from ..core import wishlists
    return page(wishlists.listing(database(), archived=request.args.get('archived') == 'true'), default_sort='name')


def export_wishlist(id, format):
    from ..core import wishlists
    if format not in ('xml', 'csv'): raise errors.NotFound()
    if set(request.args) - {'kind', 'summary'}: raise errors.UnknownFilter()
    result = wishlists.export(database(), id, format='bricklink' if format=='xml' else 'rebrickable', kind=request.args.get('kind', 'parts'))
    if request.args.get('summary') == 'true': return jsonify(data=result)
    return Response(result['content'], mimetype=result['mimetype'], headers={
        'Content-Disposition': 'attachment; filename='+result['filename'],
        'X-Wishlist-Exported': str(result['summary']['exported']),
        'X-Wishlist-Omitted': str(len(result['summary']['omitted'])),
        'X-Wishlist-Notes': str(len(result['summary']['notes']))})


@api.get('/wishlists/<id>/export.xml')
def export_wishlist_xml(id):
    return export_wishlist(id, 'xml')


@api.get('/wishlists/<id>/export.csv')
def export_wishlist_csv(id):
    return export_wishlist(id, 'csv')


# #43: the printable lists as CSV (the same rows as the web's /lists/<kind>.csv).

def list_csv(kind):
    from ..core import list_exports
    allowed = {'missing': {'copy_id', 'ids'}, 'picker': {'copy_id', 'rank'}, 'wishlist': {'list'}}[kind]
    if set(request.args) - allowed:
        raise errors.UnknownFilter()
    db = database()
    if kind == 'wishlist':
        try:
            rows = list_exports.wishlist(db, request.args.get('list', 'all'))
        except ValueError as exc:
            raise errors.NotFound(str(exc)) from None
    else:
        ids = request.args.getlist('copy_id') or (request.args.get('ids', '').split(',') if request.args.get('ids') else [])
        if not ids:
            raise errors.ValidationFailed('Choose copies with copy_id')
        rows = list_exports.missing(db, ids) if kind == 'missing' else list_exports.picker(db, ids, request.args.getlist('rank') or None)
    return Response(list_exports.to_csv(kind, rows), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=brickwork-{kind}.csv'})


@api.get('/export/missing.csv')
def get_export_missing_csv():
    return list_csv('missing')


@api.get('/export/picker.csv')
def get_export_picker_csv():
    return list_csv('picker')


@api.get('/export/wishlist.csv')
def get_export_wishlist_csv():
    return list_csv('wishlist')


@api.get('/orders/export.csv')
def get_orders_export_csv():
    """#44: saved order lines or per-order summaries as CSV."""
    from ..core import order_exports
    if set(request.args) - {'from', 'to', 'store', 'kind'}:
        raise errors.UnknownFilter()
    kind = request.args.get('kind', 'lines')
    try:
        data = order_exports.rows(database(), kind, request.args.get('from'), request.args.get('to'), request.args.get('store'))
    except ValueError as exc:
        raise errors.ValidationFailed(str(exc)) from None
    return Response(order_exports.to_csv(kind, data), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=brickwork-orders-{kind}.csv'})
