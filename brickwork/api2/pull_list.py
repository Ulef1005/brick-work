"""Pull a detected set out of a lot (#202): the pull list of a set for one lot, the found counts and Make it a copy (`core/pull_list.py`, ADR 0029)."""
from ..core import errors, pull_list
from . import route
from .items import for_write, live
from .ranking import pictures_of, whole
from .read import arguments, bodies, reading, respond
from .writes import Done, identified, write


def guarded(lot):
    if len(lot) > 64:
        raise errors.NotFound('No such lot')


def refused(error):
    """`NotFound` stays 404; any other refusal of the service is the caller's input: 422."""
    return error if isinstance(error, errors.BrickWorkError) else errors.ValidationFailed(str(error))


def line_body(book, shots, line):
    return dict(item=book.item(line['item_id']), color=book.color(line['color_id']), kind=line['kind'], category=line['category'], need=line['need'],
                held=line['held'], found=line['found'], to_find=line['need'] - line['found'], picture=shots.get((line['item_id'], line['color_id'])))


def sorted_lines(lines, book):
    def number(line):
        item = book.item(line['item_id'])
        return ((item.get('rebrickable') or {}).get('key') or item['name'], line['color_id'] or 0)
    return sorted(lines, key=lambda line: (line['category'] == pull_list.FIGURES, line['category'] or '', *number(line)))


def totals_body(info):
    return dict(info['totals'], lot_pieces=info['lot_pieces'], **{'moves': pull_list.moves(info)})


def head(db, info, book):
    return dict(lot=dict(id=info['lot']['id'], name=info['lot']['name']), set=book.item(info['set']['id']), totals=totals_body(info), nested=info['nested'],
                refusal=info['refusal'])


@route('/lots/<id>/pull-list/<set_id>')
@reading
def get_lots_by_id_pull_list_by_set_id(db, id, set_id):
    """The pull list of a set for a lot: every line of the set with what it needs, what the lot holds and what is found so far. Read-only."""
    args = arguments()
    show = args.get('show', 'all')
    if show not in pull_list.SHOWS:
        raise errors.ValidationFailed('show is find, found or all')
    limit, offset = whole(args, 'limit', 100, 1, 500), whole(args, 'offset', 0, 0, 10 ** 9)
    guarded(id)
    chosen = live(db, set_id)
    try:
        info = pull_list.state(db, id, chosen)
    except (ValueError, errors.NotFound) as error:
        raise refused(error) from None
    lines = [ln for ln in info['lines'] if show == 'all' or (show == 'find') == (ln['found'] < ln['need'])]
    book = bodies(db, items={ln['item_id'] for ln in lines} | {chosen}, colors={ln['color_id'] for ln in lines})
    lines = sorted_lines(lines, book)
    page = lines[offset:offset + limit]
    shots = pictures_of(db, {(ln['item_id'], ln['color_id']) for ln in page})
    return respond(dict(head(db, info, book), show=show, total=len(lines), limit=limit, offset=offset, lines=[line_body(book, shots, ln) for ln in page]))


@route('/lots/<id>/pull-list/<set_id>/found', 'POST')
@write
def post_lots_by_id_pull_list_by_set_id_found(db, body, id, set_id):
    """Save the found count of one line (idempotent, not an event)."""
    guarded(id)
    chosen = for_write(db, set_id)
    item, color = identified(db, body['item'], body.get('color'))
    try:
        line = pull_list.set_found(db, id, chosen, item, color, body['found'])
    except (ValueError, errors.NotFound) as error:
        raise refused(error) from None
    info = pull_list.state(db, id, chosen)
    book = bodies(db, items=[item, chosen], colors=[color])
    return Done(dict(line=line_body(book, {}, line), totals=totals_body(info)), None)


@route('/lots/<id>/pull-list/<set_id>/make-copy', 'POST')
@write
def post_lots_by_id_pull_list_by_set_id_make_copy(db, body, id, set_id):
    """Make it a copy: the found pieces move out of the lot into a new copy of the set, one undoable event (`copy` / `make_from_stock`)."""
    guarded(id)
    chosen = for_write(db, set_id)
    try:
        made = pull_list.make_copy(db, id, chosen)
    except (ValueError, errors.NotFound) as error:
        raise refused(error) from None
    return Done(dict(copy_id=made['copy_id'], set=bodies(db, items=[chosen]).item(chosen), pieces=made['pieces'], figures=made['figures'],
                     missing_parts=made['missing_parts'], missing_figures=made['missing_figures'], completeness=made['completeness'], stays=made['stays']),
                made['event_id'])
