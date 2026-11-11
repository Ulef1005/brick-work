"""Planning and exports (M.11b, issue #113): the Complete-sets ranking and the printable and portable lists built from gaps and wishes.

The ranking is `core/planning.py`'s (live copies with a gap, by what a repair gains per unit spent); the exports are `core/gaps.py`,
`core/list_exports.py` and `core/planning.py`'s `export`, which name every line for BrickLink where they can and list the rest."""
from decimal import Decimal
import json

from flask import Response, request

from ..core import candidate_sets, collection, errors, list_exports, planning, set_scoring
from . import route
from .read import (arguments, bodies, flag, page, reading, record, respond)


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


# ---------- sets versus a pile of parts (#199) ----------

SELECTORS = ('lot', 'storage', 'loose', 'stock')


def whole(args, name, default, low, high):
    try:
        value = int(args.get(name, default))
    except ValueError:
        raise errors.ValidationFailed(f'{name} is a whole number') from None
    if not low <= value <= high:
        raise errors.ValidationFailed(f'{name} is {low} to {high}')
    return value


@route('/planning/set-scores')
@reading
def get_planning_set_scores(db):
    """The catalogue's sets ranked by how much of a pile of loose parts each explains (`core/set_scoring.py`, ADR 0026). Read-only."""
    args = arguments()
    stock = request.args.getlist('stock')
    chosen = [name for name in SELECTORS if (stock if name == 'stock' else args.get(name) not in (None, '', 'false'))]
    if len(chosen) != 1 or (args.get('loose') not in (None, '', 'true', 'false')):
        raise errors.ValidationFailed('Give exactly one of lot, storage, loose=true or stock')
    limit, offset, detail = whole(args, 'limit', 20, 1, 100), whole(args, 'offset', 0, 0, 10 ** 9), whole(args, 'detail', 10, 0, 50)
    try:
        if chosen[0] == 'lot':
            parts, flags = set_scoring.from_lot(db, args['lot'])
        elif chosen[0] == 'storage':
            parts, flags = set_scoring.from_storage(db, args['storage'])
        elif chosen[0] == 'stock':
            if len(stock) > 5000 or len(set(stock)) != len(stock):
                raise errors.ValidationFailed('Choose 1 to 5000 different stock lines')
            parts, flags = set_scoring.from_stock(db, stock)
        else:
            parts, flags = set_scoring.from_loose(db)
    except errors.BrickWorkError:
        raise
    except ValueError as error:
        raise (errors.NotFound(str(error)) if str(error).startswith('No such') else errors.ValidationFailed(str(error))) from None
    result = set_scoring.score(db, parts, flags, limit=limit, offset=offset, detail=detail)
    lines = [*result['input']['unmatched']]
    for r in result['results']:
        lines += r['matched'] + [s[k] for s in r['swaps']['items'] for k in ('have', 'wanted')]
    book = bodies(db, items={r['set_item_id'] for r in result['results']} | {i['item_id'] for i in lines}, colors={i['color_id'] for i in lines})

    def line(body):
        return {**{k: v for k, v in body.items() if k not in ('item_id', 'color_id')}, 'item': book.item(body['item_id']), 'color': book.color(body['color_id'])}

    sets = [{**{k: v for k, v in r.items() if k not in ('set_item_id', 'matched', 'swaps')}, 'item': book.item(r['set_item_id']),
             'matched': [line(m) for m in r['matched']],
             'swaps': {**r['swaps'], 'items': [{**s, 'have': line(s['have']), 'wanted': line(s['wanted'])} for s in r['swaps']['items']]}}
            for r in result['results']]
    given = result['input']
    return respond(dict(catalogue=result['catalogue'], source=dict(kind=chosen[0], id=None if chosen[0] in ('loose', 'stock') else args[chosen[0]]),
                        input=dict(given, unmatched=[line(u) for u in given['unmatched']]),
                        total=result['total'], limit=limit, offset=offset, results=sets))


# ---------- which sets came in this lot (#200) ----------

def number(args, name, low, high):
    if name not in args or args[name] == '':
        return None
    try:
        value = float(args[name])
    except ValueError:
        raise errors.ValidationFailed(f'{name} is a number') from None
    if not low <= value <= high:
        raise errors.ValidationFailed(f'{name} is {low} to {high}')
    return value


def optional_whole(args, name, low=0, high=10 ** 9):
    return None if args.get(name) in (None, '') else whole(args, name, 0, low, high)


def pictures_of(db, pairs):
    """`{(item id, colour id or None): {id, content_url, image_url}}` for the lines: the newest local picture (the colour's, else the item's own) and
    the catalogue's picture address (`image_url`, absent when the catalogue has none); a line without either is left out."""
    items = sorted({i for i, _ in pairs})
    local = {}
    for r in db.execute('SELECT id,item_id,color_id FROM main.picture WHERE item_id IN (SELECT value FROM json_each(?)) ORDER BY fetched_at, id', (json.dumps(items),)):
        local[(r['item_id'], r['color_id'])] = r['id']
    remote = {r[0]: r[1] for r in db.execute('SELECT id,img_url FROM catalogue.item WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(items),)) if r[1]}
    shipped = {}                                   # parts carry no item picture in the catalogue: theirs sit in `picture_url`, per colour
    for r in db.execute('SELECT item_id,color_id,url FROM catalogue.picture_url WHERE item_id IN (SELECT value FROM json_each(?)) ORDER BY color_id', (json.dumps(items),)):
        shipped[(r[0], r[1])] = r[2]
        shipped.setdefault((r[0], None), r[2])                  # the item's first colour stands in for a line in a colour with no picture
    found = {}
    for item, colour in pairs:
        picture = local.get((item, colour)) or local.get((item, None))
        address = shipped.get((item, colour)) or shipped.get((item, None)) or remote.get(item)
        body = {'id': picture, 'content_url': f'/api/v2/images/{picture}/content' if picture else None, 'image_url': address}
        if picture or body['image_url']:
            found[(item, colour)] = body
    return found


@route('/lots/<id>/candidate-sets')
@reading
def get_lots_by_id_candidate_sets(db, id):
    """The sets a lot may have come from (Lot Detective, `core/candidate_sets.py`): ranked, with reasons and distinctive parts. Read-only."""
    args = arguments()
    ignore_common = flag(args, 'ignore_common')
    ignore_common = True if ignore_common is None else ignore_common
    limit, offset = whole(args, 'limit', 20, 1, 100), whole(args, 'offset', 0, 0, 10 ** 9)
    min_score = number(args, 'min_score', 0, 100) or 0
    year_from, year_to, parts_min, parts_max = (optional_whole(args, n) for n in ('year_from', 'year_to', 'parts_min', 'parts_max'))
    for low, high, names in ((year_from, year_to, 'year_from and year_to'), (parts_min, parts_max, 'parts_min and parts_max')):
        if low is not None and high is not None and low > high:
            raise errors.ValidationFailed(f'{names} are a range: the first is above the second')
    if len(id) > 64:
        raise errors.NotFound('No such lot')
    try:
        result = candidate_sets.candidates(db, id, min_score=min_score, theme=args.get('theme'), year_from=year_from, year_to=year_to,
                                           parts_min=parts_min, parts_max=parts_max, ignore_common=ignore_common, limit=limit, offset=offset)
    except ValueError as error:
        raise (errors.NotFound(str(error)) if str(error) == 'No such lot' else errors.ValidationFailed(str(error))) from None
    parts = [p for r in result['results'] for p in r['distinctive_found_parts'] + r['distinctive_missing_parts']]
    set_ids = {r['set_item_id'] for r in result['results']}
    book = bodies(db, items=set_ids | {p['item_id'] for p in parts}, colors={p['color_id'] for p in parts})
    shots = pictures_of(db, {(p['item_id'], p['color_id']) for p in parts} | {(i, None) for i in set_ids})

    def part(body):
        return {**{k: v for k, v in body.items() if k not in ('item_id', 'color_id')}, 'item': book.item(body['item_id']),
                'color': book.color(body['color_id']), 'picture': shots.get((body['item_id'], body['color_id']))}

    sets = [{**{k: v for k, v in r.items() if k not in ('set_item_id', 'distinctive_found_parts', 'distinctive_missing_parts')},
             'item': book.item(r['set_item_id']), 'picture': shots.get((r['set_item_id'], None)),
             'distinctive_found_parts': [part(p) for p in r['distinctive_found_parts']],
             'distinctive_missing_parts': [part(p) for p in r['distinctive_missing_parts']]} for r in result['results']]
    return respond(dict(result, lot=id, results=sets))
