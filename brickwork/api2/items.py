"""Item addressing (M.11a, decisions 2 to 5 of issue #113): `/items/{id}`, the three by-number paths and `/lookup`.

All answer `200` with the same item body (design 7), so a client needs one round trip. A number that names several items is
`409 ambiguous` with the candidates, one that names none is `404`, a merged id is `307` to the survivor on GET and `409 merged` on a
write (`for_write`, used by the write pieces)."""
from flask import jsonify, request

from ..core import errors
from ..store4 import lookup
from . import database, route, serializers

DEFAULT_PROVIDER = 'bricklink'                            # decision 3: what every current client, order e-mail and the House API speak


def item_id(text):
    """The integer of a path segment; an id that is not one names no item."""
    if not str(text).isdigit() or int(text) < 1 or len(str(text)) > 18:
        raise errors.NotFound('No such item')
    return int(text)


def moved(old, live):
    """The `307` of a merged id: where the survivor is, with the rest of the path and the query kept."""
    location = request.full_path.rstrip('?').replace(f'/items/{old}', f'/items/{live}', 1)
    return errors.Moved(f'Item {old} was merged into item {live}', location=location, survivor=live)


def live(db, text):
    """The id of the live item a path names, or `Moved` / `NotFound`. For reads."""
    old = item_id(text)
    found = lookup.live_id(db, old)
    if found is None:
        raise errors.NotFound('No such item')
    if found[1]:
        raise moved(old, found[0])
    return old


def for_write(db, text):
    """The id of a live item a write names: a merged id is `409 merged` naming the survivor (decision 5), an unknown one `404`."""
    old = item_id(text)
    found = lookup.live_id(db, old)
    if found is None:
        raise errors.NotFound('No such item')
    if found[1]:
        raise errors.Merged(f'Item {old} was merged into item {found[0]}; write to the survivor', survivor=found[0])
    return old


def _arguments(allowed):
    unknown = set(request.args) - set(allowed)
    if unknown:
        raise errors.UnknownFilter('Unknown filter: ' + ', '.join(sorted(unknown)))
    return request.args


def resolve(db, provider, kind, key, color):
    """The item body for a provider number (and colour, in the provider's space), or 404, 409 ambiguous, 422."""
    if provider not in lookup.PROVIDERS:
        raise errors.ValidationFailed('provider is bricklink or rebrickable for an item number (a Brick Work colour id goes on /items/{id} paths)')
    if kind not in lookup.KINDS:
        raise errors.ValidationFailed('kind is one of ' + ', '.join(lookup.KINDS))
    if not key or len(key) > 64:
        raise errors.ValidationFailed('Enter an item number of 1 to 64 characters')
    color_id = None
    if color not in (None, ''):
        try:
            color_id = lookup.brickwork_color(db, provider, color)
        except ValueError as error:
            raise errors.ValidationFailed(str(error)) from None
    try:
        ids = lookup.find_items(db, provider, kind, key, color_id)
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None
    if not ids:
        raise errors.NotFound(f'No {kind} {key} at {provider}')
    if len(ids) > 1:
        raise errors.Ambiguous(f'{provider} {kind} {key} names {len(ids)} items; address one by id',
                               candidates=[serializers.item(db, i) for i in ids])
    body = serializers.item(db, ids[0])
    if color_id is not None:
        body['color'] = serializers.color(db, color_id)   # the resolved Brick Work colour: a client maps provider colours through it
    return jsonify(data=body)


def numbered(kind):
    args = _arguments(('provider', 'color'))
    return args.get('provider', DEFAULT_PROVIDER), kind


@route('/items/<id>')
def get_items_by_id(id):
    db = database()
    return jsonify(data=serializers.item(db, live(db, id)))


@route('/sets/by-number/<no>')
def get_sets_by_number_by_no(no):
    provider, kind = numbered('set')
    return resolve(database(), provider, kind, no, request.args.get('color'))


@route('/parts/by-number/<no>')
def get_parts_by_number_by_no(no):
    provider, kind = numbered('part')
    return resolve(database(), provider, kind, no, request.args.get('color'))


@route('/minifigures/by-number/<no>')
def get_minifigures_by_number_by_no(no):
    provider, kind = numbered('minifigure')
    return resolve(database(), provider, kind, no, request.args.get('color'))


@route('/lookup')
def get_lookup():
    args = _arguments(('provider', 'kind', 'key', 'color'))
    if not args.get('kind') or not args.get('key'):
        raise errors.ValidationFailed('kind and key are required')
    return resolve(database(), args.get('provider', DEFAULT_PROVIDER), args['kind'], args['key'], args.get('color'))
