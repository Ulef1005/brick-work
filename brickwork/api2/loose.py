"""Loose stock, figures by identity, and the Workbench's gaps and matches (M.11b, issue #113).

Loose stock is the `stock` table (design 5): parts in a colour, whole minifigures with their own part list, booklets, boxes, gear, books
and catalogues. A figure row of `/minifigures` is an identity: what is owned loose, what is in sets, and what is missing of it.
Gaps and matches are `core/workbench.py`'s, over every copy and loose figure."""
from ..core import collection, errors, workbench
from ..store4 import lookup
from . import route
from .copies import gap_bodies, gap_records, match_bodies, match_records
from .read import (also, arguments, bodies, etag as etag_of, identity_filter, narrow, page, reading, record, respond, used_prices)
from .shapes import stock_bodies


def stock_row(db, stock_id):
    row = collection.instance(db, 'stock', stock_id) if len(stock_id) <= 64 else None
    if row is None:
        raise errors.NotFound('No such stock line')
    return row


@route('/stock')
@reading
def get_stock(db):
    args = arguments()
    kind = args.get('kind') or None
    if kind is not None and kind not in lookup.KINDS:
        raise errors.ValidationFailed('kind is one of ' + ', '.join(lookup.KINDS))
    items, color = identity_filter(db, args)
    rows = collection.instances(db, kind, include_archived=args.get('archived', '') in ('true', 'include', 'only'), stock_only=True)
    records = [record(r['id'], r['number'] or '', also=r['also'] or '', name=r['name'] or '', colour=r['color_name'] or '', kind=r['kind'],
                      condition=r['condition'] or '', storage=r['storage_id'] or 'null', place=r['place_id'] or 'null', lot=r['lot_id'] or 'null',
                      flags=[f['name'] for f in r['flags']], flag_ids=[f['id'] for f in r['flags']], theme=r['theme'] or '', category=r['category'] or '',
                      year=r['year'], missing=r['missing'], damaged=r['damaged'], quantity=r['quantity'], archived_at=r['archived_at'],
                      item_id=r['item_id'], color_id=r['color_id'], _row=r) for r in rows]
    records = narrow(records, items, color)
    if args.get('sort') == 'used_price':
        used_prices(db, records)
    return page(records, args, build=lambda chosen: stock_bodies(db, [r['_row'] for r in chosen]))


@route('/stock/<id>')
@reading
def get_stock_by_id(db, id):
    arguments()
    row = stock_row(db, id)
    return respond(stock_bodies(db, [row])[0], etag=etag_of(db, 'stock', id))


@route('/stock/<id>/parts')
@reading
def get_stock_by_id_parts(db, id):
    args = arguments()
    stock_row(db, id)
    lines = db.execute('SELECT * FROM main.stock_part WHERE stock_id=? AND retired_at IS NULL ORDER BY id', (id,)).fetchall()
    book = bodies(db, items=[r['item_id'] for r in lines], colors=[r['color_id'] for r in lines])
    records = []
    for r in lines:
        body = book.item(r['item_id'])
        records.append(record(r['id'], (body['rebrickable'] or {}).get('key') or '', also=also(body), name=body['name'], index=r['id'],
                              _body={'stock_id': id, 'item': body, 'color': book.color(r['color_id']), 'spare': r['is_spare'], 'quantity': r['quantity'],
                                     'missing': r['missing'], 'damaged': r['damaged'], 'checked': bool(r['checked'])}))
    return page(records, args, default_sort='index')


# ---------- figures by identity ----------

def figure_bodies(db, rows):
    book = bodies(db, items=[r['item_id'] for r in rows])
    return [{'item': book.item(r['item_id']), 'name': r['name'], 'theme': r['theme'] or None, 'year': r['year'], 'quantity': r['quantity'] or 0,
             'in_sets': r.get('in_sets') or 0, 'missing': r['missing'] or 0, 'damaged': r['damaged'] or 0, 'image_id': r['image']} for r in rows]


@route('/minifigures')
@reading
def get_minifigures(db):
    args = arguments()
    items, color = identity_filter(db, args)
    rows = collection.listing(db, 'M')
    records = [record(r['item_id'], r['number'] or '', also=r['also'] or '', name=r['name'] or '', colour='', type='M', theme=r['theme'] or '', category=r['category'] or '',
                      year=r['year'], quantity=r['quantity'] or 0, missing=r['missing'] or 0, damaged=r['damaged'] or 0, in_sets=r.get('in_sets') or 0,
                      item_id=r['item_id'], color_id=None, _row=r) for r in rows]
    records = narrow(records, items, color)
    if args.get('sort') == 'used_price':
        used_prices(db, records)
    return page(records, args, build=lambda chosen: figure_bodies(db, [r['_row'] for r in chosen]))


# ---------- gaps and matches ----------

@route('/gaps')
@reading
def get_gaps(db):
    args = arguments()
    items, color = identity_filter(db, args)
    return page(narrow(gap_records(workbench.gaps(db)), items, color), args, build=lambda chosen: gap_bodies(db, [r['_row'] for r in chosen]))


@route('/matches')
@reading
def get_matches(db):
    args = arguments()
    items, color = identity_filter(db, args)
    return page(narrow(match_records(workbench.matches(db)), items, color), args, build=lambda chosen: match_bodies(db, [r['_row'] for r in chosen]))
