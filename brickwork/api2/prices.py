"""Prices (M.11b, issue #113): the current price per item, colour, condition and guide, one item's prices and history, and the stale list.

A price is a `price_observation` row; `price_current` names the observation that is current for each (item, colour, condition, guide,
slot, region, currency). A voided observation is never shown (design 5). The freshness rule is the source's `prices` rule in
`source_freshness` (`collection.decorate_prices` applies it)."""
import base64
import json

from ..core import admin, collection, errors
from ..core.collection_prices import dated
from ..core.sources.base import now
from . import route
from .items import DEFAULT_PROVIDER, live
from .read import arguments, bodies, color_id_for, identity_filter, key_text, narrow, page, reading, record, respond

CURRENT = '''SELECT p.item_id, p.color_id, p.condition, p.guide, p.slot, p.region, p.currency, p.observation_id, i.kind, i.name, i.born_key,
    o.source, o.price, o.min, o.max, o.qty, o.sold, o.observed_at, o.error, o.provider_key, f.max_age_days
    FROM price_current p JOIN price_observation o ON o.id=p.observation_id JOIN item i ON i.id=p.item_id
    LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices' WHERE o.voided_at IS NULL'''


def observation(book, r, identifier=None):
    """A `PriceObservation` body of an observation row (or of a current-price row, whose observation id is `observation_id`)."""
    return {'id': identifier if identifier is not None else r['id'], 'item': book.item(r['item_id']), 'color': book.color(r['color_id']),
            'condition': r['condition'], 'guide': r['guide'], 'slot': r['slot'], 'region': r['region'], 'currency': r['currency'], 'price': r['price'],
            'qty': r['qty'], 'sold': r['sold'], 'min': r['min'], 'max': r['max'], 'source': r['source'], 'observed_at': r['observed_at'], 'error': r['error']}


def current_body(book, r):
    stamp = dated(r['observed_at'])
    return {'observation': observation(book, r, r['observation_id']), 'age_days': (now() - stamp).days if stamp else None, 'stale': bool(r['stale'])}


def current_rows(db, item_id=None, color_id=None):
    """The current-price rows, decorated (`stale`); for one item (and colour) or all."""
    where, params = '', []
    if item_id is not None:
        where, params = ' AND p.item_id=?', [item_id]
        if color_id is not None:
            where, params = where + ' AND p.color_id=?', params + [color_id]
    rows = db.execute(CURRENT + where + ' ORDER BY p.item_id, p.color_id, p.condition, p.guide, p.currency, p.slot, p.region', params).fetchall()
    return collection.decorate_prices(rows)


def key(r):
    return key_text(r['item_id'], r['color_id'], r['condition'], r['guide'], r['slot'], r['region'], r['currency'])


@route('/prices')
@reading
def get_prices(db):
    args = arguments()
    items, color = identity_filter(db, args)
    records = [record(key(r), r['born_key'] or '', name=r['name'], kind=r['kind'], condition=r['condition'] or '', guide=r['guide'], source=r['source'],
                      item_id=r['item_id'], color_id=r['color_id'], _row=r) for r in current_rows(db)]

    def build(chosen):
        rows = [r['_row'] for r in chosen]
        book = bodies(db, items=[r['item_id'] for r in rows], colors=[r['color_id'] for r in rows])
        return [current_body(book, r) for r in rows]
    return page(narrow(records, items, color), args, build=build)


def colour_argument(db, args):
    """The Brick Work colour a `color` argument names (in `provider`'s space, bricklink by default), or None."""
    if args.get('color') in (None, ''):
        return None
    return color_id_for(db, args.get('provider', DEFAULT_PROVIDER), args['color'])


@route('/items/<id>/prices')
@reading
def get_items_by_id_prices(db, id):
    args = arguments()
    item_id = live(db, id)
    color = colour_argument(db, args)
    where, params = 'item_id=? AND voided_at IS NULL', [item_id]
    if color is not None:
        where, params = where + ' AND color_id=?', params + [color]
    records = db.execute(f'SELECT * FROM price_observation WHERE {where} ORDER BY observed_at DESC, id DESC LIMIT 200', params).fetchall()
    current = current_rows(db, item_id, color)
    book = bodies(db, items=[item_id], colors=[r['color_id'] for r in (*records, *current)])
    return respond({'current': [current_body(book, r) for r in current], 'records': [observation(book, r) for r in records]})


def sql_page(db, select, params, *, direction, signature, cursor, limit, identity='o.id'):
    """A page of an append-only history by its integer key, in SQL: `(rows, next_cursor)`. The cursor holds the last key."""
    try:
        limit = int(limit)
        if not 1 <= limit <= 200:
            raise ValueError
    except (TypeError, ValueError):
        raise errors.BadRequest('Limit must be between 1 and 200') from None
    clause = ''
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
            if decoded['s'] != signature or type(decoded['after']) is not int:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise errors.BadRequest('Invalid cursor') from None
        clause, params = f' AND {identity}{">" if direction == "asc" else "<"}?', [*params, decoded['after']]
    rows = db.execute(f'{select}{clause} ORDER BY {identity} {"ASC" if direction == "asc" else "DESC"} LIMIT ?', (*params, limit + 1)).fetchall()
    after = None
    if len(rows) > limit:
        rows = rows[:limit]
        after = base64.urlsafe_b64encode(json.dumps({'s': signature, 'after': rows[-1][identity.split('.')[-1]]}).encode()).decode().rstrip('=')
    return rows, after, limit


@route('/items/<id>/prices/history')
@reading
def get_items_by_id_prices_history(db, id):
    args = arguments()
    item_id = live(db, id)
    color = colour_argument(db, args)
    direction = args.get('direction', 'desc')
    if direction not in ('asc', 'desc'):
        raise errors.UnknownFilter('direction is asc or desc')
    where, params = 'o.item_id=? AND o.voided_at IS NULL', [item_id]
    if color is not None:
        where, params = where + ' AND o.color_id=?', params + [color]
    if args.get('condition'):
        where, params = where + ' AND o.condition IS ?', params + [None if args['condition'] == 'null' else args['condition']]
    signature = json.dumps([item_id, color, args.get('condition'), direction])
    rows, after, limit = sql_page(db, f'SELECT o.* FROM price_observation o WHERE {where}', params, direction=direction, signature=signature,
                                  cursor=args.get('cursor'), limit=args.get('limit', 50))
    book = bodies(db, items=[item_id], colors=[r['color_id'] for r in rows])
    return respond([observation(book, r) for r in rows], page={'next_cursor': after, 'limit': limit, 'total': None})


# ---------- stale prices ----------

@route('/prices/stale')
@reading
def get_prices_stale(db):
    args = arguments()
    stale = {(r['item_id'], r['color_id'], r['condition']): r for r in admin.stale_prices(db)}
    origins = db.execute('''SELECT DISTINCT item_id, NULL AS color_id, condition, 'copy' AS source_table FROM main.copy WHERE archived_at IS NULL
        UNION SELECT DISTINCT item_id, color_id, condition, 'stock' FROM main.stock WHERE archived_at IS NULL AND kind!='minifigure'
        UNION SELECT DISTINCT item_id, color_id, CASE condition WHEN 'any' THEN NULL ELSE condition END, 'wish' FROM main.wish WHERE archived_at IS NULL''').fetchall()
    records = []
    for r in origins:
        found = stale.get((r['item_id'], r['color_id'], r['condition']))
        if found is None:
            continue
        records.append(record(key_text(r['item_id'], r['color_id'], r['condition'], r['source_table']), found['item_no'], name=found['name'],
                              _row=dict(r, name=found['name'])))

    def build(chosen):
        rows = [r['_row'] for r in chosen]
        book = bodies(db, items=[r['item_id'] for r in rows], colors=[r['color_id'] for r in rows])
        return [{'item': book.item(r['item_id']), 'name': r['name'], 'color': book.color(r['color_id']), 'condition': r['condition'], 'source_table': r['source_table']}
                for r in rows]
    return page(records, args, build=build)
