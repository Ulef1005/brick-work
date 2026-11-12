"""Stickers on the parts of a lot (#201): the sets a sticker may belong to, "This one" and "Not a sticker" (`core/stickers.py`, ADR 0028)."""
from ..core import errors, stickers
from . import route
from .ranking import pictures_of, whole
from .read import arguments, bodies, reading, respond
from .writes import Done, write


def choice_body(state):
    """`StickerState` as the answer shows it."""
    confirmed = state['confirmed']
    return {'flagged': state['flagged'],
            'confirmed': None if confirmed is None else {k: confirmed[k] for k in ('set_item_id', 'sheet_item_id', 'set_number', 'set_name')}}


def guarded(lot, stock):
    if len(lot) > 64 or len(stock) > 64:
        raise errors.NotFound('No such part in this lot')


@route('/lots/<id>/stock/<stock_id>/stickers')
@reading
def get_lots_by_id_stock_by_stock_id_stickers(db, id, stock_id):
    """The sets a sticker on a part line may belong to. Read-only."""
    args = arguments()
    guarded(id, stock_id)
    limit, offset = whole(args, 'limit', 20, 1, 100), whole(args, 'offset', 0, 0, 10 ** 9)
    found = stickers.candidates(db, id, stock_id, limit=limit, offset=offset)
    line, results = found['stock'], found['results']
    book = bodies(db, items={line['item_id']} | {r['set_item_id'] for r in results} | {r['sheet_item_id'] for r in results},
                  colors={line['color_id']})
    shots = pictures_of(db, {(r['sheet_item_id'], None) for r in results})
    return respond(dict(lot=id, stock_id=stock_id, item=book.item(line['item_id']), color=book.color(line['color_id']), quantity=line['quantity'],
                        sticker=choice_body(stickers.states(db, [stock_id])[stock_id]), total=found['total'], limit=limit, offset=offset,
                        results=[dict(set=book.item(r['set_item_id']), sheet=book.item(r['sheet_item_id']), year=r['year'],
                                      picture=shots.get((r['sheet_item_id'], None))) for r in results]))


def written(db, stock_id, done):
    return dict(changed=done['changed'], sticker=choice_body(stickers.states(db, [stock_id])[stock_id]))


@route('/lots/<id>/stock/<stock_id>/sticker', 'POST')
@write
def post_lots_by_id_stock_by_stock_id_sticker(db, body, id, stock_id):
    guarded(id, stock_id)
    done = stickers.confirm(db, id, stock_id, body['set_item_id'], body['sheet_item_id'])
    return Done(written(db, stock_id, done), done['event_id'])


@route('/lots/<id>/stock/<stock_id>/sticker', 'DELETE')
@write
def delete_lots_by_id_stock_by_stock_id_sticker(db, body, id, stock_id):
    guarded(id, stock_id)
    done = stickers.clear(db, id, stock_id)
    return Done(written(db, stock_id, done), done['event_id'])
