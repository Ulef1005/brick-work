"""Planning and exports (M.11b, issue #113): the Complete-sets ranking and the printable and portable lists built from gaps and wishes.

The ranking is `core/planning.py`'s (live copies with a gap, by what a repair gains per unit spent); the exports are `core/gaps.py`,
`core/list_exports.py` and `core/planning.py`'s `export`, which name every line for BrickLink where they can and list the rest."""
from decimal import Decimal

from flask import Response, request

from ..core import collection, errors, list_exports, planning
from . import route
from .read import (arguments, bodies, page, reading, record, respond)


def plain(value):
    """A value as JSON carries it: decimals as strings (never floats), tuples as lists."""
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def quote_body(quote):
    if not quote:
        return None
    return {k: plain(quote.get(k)) for k in ('price', 'currency', 'region', 'source', 'guide', 'condition', 'observed_at')}


def settings_body(config):
    return {'bricklink_region': config['bricklink_region'], 'bricklink_currency': config['bricklink_currency'],
            'incomplete_discount_pct': float(config['incomplete_discount_pct']),
            'repair': {'shipping': str(config['repair_shipping']), 'fees': str(config['repair_fees']), 'min_order': str(config['repair_min_order']),
                       'use_loose_stock': bool(config['repair_use_loose_stock'])}}


@route('/planning/ranking')
@reading
def get_planning_ranking(db):
    args = arguments()
    data = planning.ranking(db)
    book = bodies(db, items={*(r['item_id'] for r in data['rows']), *(i['item_id'] for r in data['rows'] for i in r['items'])},
                  colors={i['color_id'] for r in data['rows'] for i in r['items']})
    defects = collection._copy_defects(db, 'c.archived_at IS NULL', ())
    records = []
    for r in data['rows']:
        lines = [{'item': book.item(i['item_id']), 'name': i['name'], 'color': book.color(i['color_id']), 'missing': i['missing'],
                  'original_gap': i['original_gap'], 'stock_used': i['stock_used'], 'quote': quote_body(i.get('quote'))} for i in r['items']]
        missing, damaged = defects.get(r['id'], (0, 0, 0, 0))[:2]
        body = {'id': r['id'], 'group': r['group'], 'items': lines, 'rank': r.get('rank'), 'reasons': r['reasons'], 'missing_count': r['missing_count'],
                'missing_figures': r['missing_figures'], 'missing_parts': r['missing_parts'], 'original_gap': r['original_gap'], 'stock_used': r['stock_used'],
                'unresolved_items': r['unresolved_items'], 'display_ratio_width': r.get('display_ratio_width'), 'complete_quote': quote_body(r.get('complete_quote')),
                'listing': bool(r['listing']), 'item': book.item(r['item_id']), 'name': r['name'], 'condition': r['condition'], 'completeness': r['completeness'],
                'completeness_source': r['completeness_source'], 'storage_id': r['storage_id'], 'purchase_location_id': r['place_id'],
                'purchase_date': r['purchase_date'], 'purchase_price': r['purchase_price'], 'purchase_currency': r['purchase_currency'], 'note': r['note'],
                'current_value': plain(r.get('current_value')), 'current_value_currency': r['current_value_currency'], 'pinned': bool(r['pinned']),
                'missing': missing, 'damaged': damaged, 'updated_at': r['updated_at'], 'archived_at': r['archived_at'],
                'value_when_complete': plain(r.get('value_when_complete')), 'valuation_basis': r.get('valuation_basis'), 'breakdown': plain(r.get('breakdown', {})),
                'repair_cost': plain(r.get('repair_cost')), 'gross_gain': plain(r.get('gross_gain')), 'net_gain': plain(r.get('net_gain')),
                'ratio': plain(r.get('ratio')), 'ratio_width': r.get('ratio_width', 0.0), 'ratio_overflow': bool(r.get('ratio_overflow', False))}
        records.append(record(r['id'], r['set_num'] or '', name=r['name'] or '', colour='', status=r['completeness'] or '', theme=r.get('theme') or '',
                              category=r.get('category') or '', year=r.get('year'), missing=r['missing_count'], damaged=0, ranking=planning.ranking_cursor_key(r),
                              _body=body))
    return page(records, args, default_sort='ranking', settings=settings_body(data['settings']))


# ---------- exports ----------

def chosen_copies():
    """The copy ids an export names: repeated `copy_id`, else the comma-separated `ids`."""
    ids = request.args.getlist('copy_id') or (request.args.get('ids', '').split(',') if request.args.get('ids') else [])
    ids = [i.strip() for i in ids]
    if not ids or any(not i for i in ids):
        raise errors.ValidationFailed('Choose copies with copy_id')
    if len(ids) > 2000 or len(set(ids)) != len(ids):
        raise errors.ValidationFailed('Choose 1 to 2000 different copies')
    return ids


def attachment(content, mimetype, name):
    return Response(content, mimetype=mimetype, headers={'Content-Disposition': f'attachment; filename={name}'})


@route('/export/missing.csv')
@reading
def get_export_missing_csv(db):
    arguments()
    return attachment(list_exports.to_csv('missing', list_exports.missing(db, chosen_copies())), 'text/csv', 'brickwork-missing.csv')


@route('/export/picker.csv')
@reading
def get_export_picker_csv(db):
    arguments()
    ids = chosen_copies()
    return attachment(list_exports.to_csv('picker', list_exports.picker(db, ids, request.args.getlist('rank') or None)), 'text/csv', 'brickwork-picker.csv')


@route('/export/wishlist.csv')
@reading
def get_export_wishlist_csv(db):
    args = arguments()
    try:
        rows = list_exports.wishlist(db, args.get('list', 'all'))
    except ValueError as error:
        raise errors.NotFound(str(error)) from None
    return attachment(list_exports.to_csv('wishlist', rows), 'text/csv', 'brickwork-wishlist.csv')


def conditions(letter):
    return {'N': 'new', 'U': 'used'}.get(letter)


@route('/export/missing.json')
@reading
def get_export_missing_json(db):
    arguments()
    result = planning.export(db, chosen_copies())
    book = bodies(db, items=[r['item_id'] for r in (*result['lines'], *result['skipped'])], colors=[r['color_id'] for r in (*result['lines'], *result['skipped'])])

    def line(r, **more):
        return {'item': book.item(r['item_id']), 'color': book.color(r['color_id']), 'quantity': r['quantity'], 'condition': conditions(r['condition']), **more}
    wanted = [line(r, bricklink={'type': r['bricklink'][0], 'no': r['bricklink'][1], 'color_id': None if r['bricklink'][2] is None else int(r['bricklink'][2])})
              for r in result['lines']]
    return respond(wanted, skipped=[line(r, why=r['why']) for r in result['skipped']])


@route('/export/missing.xml')
@reading
def get_export_missing_xml(db):
    arguments()
    return attachment(planning.export(db, chosen_copies())['xml'], 'application/xml', 'brickwork-missing.xml')
