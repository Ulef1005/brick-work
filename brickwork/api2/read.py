"""What every v2 read shares (M.11b, issue #113): the query vocabulary, item and colour bodies with a per-request cache, the listing
(filters, sort, cursor) over the 4.0 projections of `core/`, the ETag of copies, stock and wishes, and the answer envelope.

A read is a projection the web screens already use (`core/collection.py`, `workbench.py`, `planning.py`, ...) turned into the bodies of
`openapi-v2.yaml`: nothing here reads the v1 tables. Every body that names an item carries the item body (design 7), every colour the
colour body; a list is filtered and sorted in Python over the rows its projection returns (the collection is thousands of rows, not
millions) and paged with `core/listing.py`'s cursor, as v1 did. Strings leave through `respond`, which redacts the secret list once."""
from functools import wraps
import hashlib
import json
import re

from flask import g, jsonify, request

from ..core import errors
from ..core.listing import FILTERS, filter_rows, paginate
from ..core.secrets import secret_values
from ..core.sources.base import redact
from ..store4 import lookup
from . import database, serializers
from .items import DEFAULT_PROVIDER, snapshot

BOOLEAN = {'true', 'false'}
ARCHIVED = {'true': 'include', 'include': 'include', 'only': 'only'}


# ---------- the query ----------

def arguments(*extra):
    """The request's query as a dict, checked against the contract: a name the operation does not declare (and `extra`) is
    `400 unknown_filter`, a name given twice is `400 bad_request` unless the contract declares it an array."""
    from . import operations
    declared = operations()[request.endpoint.split('.', 1)[1]]['query']
    unknown = set(request.args) - set(declared) - set(extra)
    if unknown:
        raise errors.UnknownFilter('Unknown filter: ' + ', '.join(sorted(unknown)))
    for name in request.args:
        if not declared.get(name) and len(request.args.getlist(name)) != 1:
            raise errors.BadRequest('Repeat a query parameter only where documented')
    return request.args.to_dict()


def flag(args, name):
    """A `true`/`false` query value as a bool, or None when absent; anything else is `400 unknown_filter` (v1's rule)."""
    value = args.get(name)
    if value in (None, ''):
        return None
    if value not in BOOLEAN:
        raise errors.UnknownFilter(f'{name} is true or false')
    return value == 'true'


def reading(function):
    """A GET view over the request's database inside one read snapshot (the first read pins it), so an answer that reads several rows
    never mixes the states on either side of a merge that commits meanwhile. The view takes the connection as its first argument."""
    @wraps(function)
    def view(**kwargs):
        db = database()
        with snapshot(db):
            return function(db, **kwargs)
    return view


# ---------- bodies ----------

class Bodies:
    """Item and colour bodies for one request, each built once. Redaction happens at `respond`, not here.

    `load` brings many in a fixed number of queries; a list loads the ids of the rows it is about to describe, so the cost of a page
    does not grow with its rows. `item` and `color` on an id nobody loaded fall back to a read of that one."""

    def __init__(self, db):
        self.db = db
        self._items, self._colors = {}, {}
        self.secrets = secret_values()

    def load(self, items=(), colors=()):
        missing = {i for i in items if i is not None and i not in self._items}
        if missing:
            found = serializers.items(self.db, missing, self.secrets)
            self._items.update({i: found.get(i) for i in missing})
        missing = {c for c in colors if c is not None and c not in self._colors}
        if missing:
            found = serializers.colors(self.db, missing, self.secrets)
            self._colors.update({c: found.get(c) for c in missing})
        return self

    def item(self, item_id):
        if item_id not in self._items:
            self.load(items=[item_id])
        return self._items[item_id]

    def color(self, color_id):
        if color_id is None:
            return None
        if color_id not in self._colors:
            self.load(colors=[color_id])
        return self._colors[color_id]


def bodies(db, items=(), colors=()):
    """The request's `Bodies` (one per request, so a single answer never builds a body twice), with these ids loaded."""
    cache = g.get('api_bodies')
    if cache is None or cache.db is not db:
        cache = g.api_bodies = Bodies(db)
    return cache.load(items, colors)


def clean(value, secrets):
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {k: clean(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v, secrets) for v in value]
    return value


def respond(data=None, status=200, etag=None, **members):
    """`{"data": ...}` (and `page` and the like in `members`), every string redacted once, with the ETag when given."""
    cache = g.get('api_bodies')
    response = jsonify(clean(dict(data=data, **members), cache.secrets if cache is not None else secret_values()))
    response.status_code = status
    if etag:
        response.set_etag(etag)
    return response


# ---------- identity filters ----------

def item_ids_for(db, provider, number, kind=None, color_id=None):
    """The live item ids a provider number stands for (any kind unless `kind` says), for the `number` filter of a list."""
    if provider not in lookup.PROVIDERS:
        raise errors.ValidationFailed('number is given with provider bricklink or rebrickable (a Brick Work id is not a number)')
    if kind is not None and kind not in lookup.KINDS:
        raise errors.ValidationFailed('kind is one of ' + ', '.join(lookup.KINDS))
    kinds = [kind] if kind else [k for k in lookup.KINDS if provider == 'bricklink' or k in lookup.REBRICKABLE_NAMESPACE]
    if kind in ('instructions', 'box') and 'set' not in kinds:
        kinds = kinds + ['set']                      # a booklet's or box's number is its set's, and the Workbench's gaps name the set
    found = set()
    for each in kinds:
        try:
            found.update(lookup.find_items(db, provider, each, number, color_id))
        except ValueError:
            if kind:
                raise errors.ValidationFailed(f'Rebrickable has no numbers for kind {kind}') from None
    return found


def color_id_for(db, provider, color):
    """The Brick Work colour id of a `color` filter given in the provider's space (decision 4), or `422`."""
    if provider not in lookup.COLOR_PROVIDERS:
        raise errors.ValidationFailed('provider is bricklink, rebrickable or brickwork')
    try:
        return lookup.brickwork_color(db, provider, color)
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None


def identity_filter(db, args):
    """`(item ids or None, colour id or None)` from the `number`, `provider` and `color` filters. A filter that names nothing that exists
    is an empty set (the list is empty), not an error; a malformed colour is `422`."""
    provider = args.get('provider', DEFAULT_PROVIDER)
    color = None
    if args.get('color') not in (None, ''):
        color = color_id_for(db, provider, args['color'])         # first: a number is read in the colour (scoped links win, design 3.2)
    items = None
    if args.get('number') not in (None, ''):
        items = item_ids_for(db, provider, args['number'], args.get('kind'), color)
    if color is None and args.get('provider') not in (None, '') and provider not in lookup.COLOR_PROVIDERS:
        raise errors.ValidationFailed('provider is bricklink, rebrickable or brickwork')
    return items, color


def narrow(records, items, color):
    """The records of the items (`None`: all) and the colour (`None`: all) an `identity_filter` names. A record carries `item_id` and
    `color_id`; a filter on a colour keeps only the rows held in that colour."""
    return [r for r in records if (items is None or r['item_id'] in items) and (color is None or r.get('color_id') == color)]


def used_prices(db, records):
    """Give each record the `price` the `used_price` sort reads: the used, sold quote the screens show, as `[currency, amount]`."""
    from ..core import collection, collection_prices
    pairs = {(r['item_id'], r.get('color_id')) for r in records}
    market = collection.prices(db, pairs=pairs, used_sold=True) if pairs else {}
    priority = collection_prices.priority(db)
    for r in records:
        quotes = market.get((r['item_id'], r.get('color_id')), [])
        best = collection_prices.choose([q for q in quotes if q['guide'] == 'sold' and q.get('slot') != 'boxed'], r.get('kind'), priority, 'used')
        r['price'] = [best.get('currency') or 'Currency not recorded', best['price']] if best else None
    return records


# ---------- the listing ----------

def adapt(args):
    """The query as `filter_rows` takes it: only its filter names, with the v2 spellings translated (`archived=true` is `include`,
    `spare=0|1` is `false|true`)."""
    filters = {k: v for k, v in args.items() if k in FILTERS and v != ''}
    if 'archived' in filters:
        if filters['archived'] not in ARCHIVED:
            raise errors.UnknownFilter('archived is true, include or only')
        filters['archived'] = ARCHIVED[filters['archived']]
    if 'spare' in filters:
        if filters['spare'] not in ('0', '1', 'true', 'false'):
            raise errors.UnknownFilter('spare is 0 or 1')
        filters['spare'] = 'true' if filters['spare'] in ('1', 'true') else 'false'
    return filters


def page(records, args, *, default_sort='number', default_direction='asc', build=None, applied=(), **members):
    """Filter, sort and page `records` (dicts with the listing keys of `core/listing.py` and, under `_body`, the public body).

    `id` is the row's stable unique key (the cursor and the tie-break). `build`, when given, turns the chosen page of records into
    bodies in one go (a bulk read for the rows of one page); otherwise each record's `_body` is the body. `applied` names query filters the caller already applied; `members` join the envelope.
    Returns the response with `{"data": [...], "page": {next_cursor, limit, total}}`."""
    filters = adapt({k: v for k, v in args.items() if k not in applied})
    sort, direction = args.get('sort', default_sort), args.get('direction', default_direction)
    ordered = filter_rows(records, args.get('q', ''), filters, sort, direction)
    signature = json.dumps([request.path, {k: v for k, v in args.items() if k not in ('cursor', 'limit')}], sort_keys=True)
    result = paginate(ordered, cursor=args.get('cursor'), limit=args.get('limit', 50), sort=sort, direction=direction, signature=signature)
    data = build(result['data']) if build else [r['_body'] for r in result['data']]
    return respond(data, page=result['page'], **members)


def also(body):
    """The other numbers an item answers to (its BrickLink numbers), as one searchable text."""
    return ' '.join(dict.fromkeys(link['no'] for link in body['bricklink'])) if body else ''


def record(row_id, number='', **fields):
    """A listing record: the keys `filter_rows` reads (`id` unique and stable, `number` the sort key) and whatever the list filters on."""
    found = dict(id=str(row_id), number=number or '', index=row_id if isinstance(row_id, int) else 0)
    found.update(fields)
    return found


def key_text(*parts):
    """A stable unique key for a row that has no id of its own (gaps, matches, prices)."""
    return json.dumps(parts, separators=(',', ':'), default=str)


# ---------- ETag ----------

TABLES = {'copy': ('copy', 'copy_flag', 'copy_id'), 'stock': ('stock', 'stock_flag', 'stock_id'), 'wish': ('wish', 'wish_flag', 'wish_id')}


def etags(db, entity, ids):
    """`{id: etag}` for rows of a copy, stock or wish table: a hash of the stored row and its flag ids, so any change that matters moves
    it. Two queries for any number of ids; the hash is v1's recipe (sha256 of the sorted JSON of `{snapshot, flags}`)."""
    table, link, column = TABLES[entity]
    packed = json.dumps(sorted(set(ids)))
    rows = {r['id']: dict(r) for r in db.execute(f'SELECT * FROM main.{table} WHERE id IN (SELECT value FROM json_each(?))', (packed,))}
    flags = {}
    for r in db.execute(f'SELECT {column} AS owner, flag_id FROM main.{link} WHERE {column} IN (SELECT value FROM json_each(?)) ORDER BY flag_id', (packed,)):
        flags.setdefault(r['owner'], []).append(r['flag_id'])
    return {i: hashlib.sha256(json.dumps(dict(snapshot=row, flags=flags.get(i, [])), sort_keys=True, default=str).encode()).hexdigest()
            for i, row in rows.items()}


def etag(db, entity, identifier):
    return etags(db, entity, [identifier]).get(identifier)


# ---------- small shapes ----------

NUMBER = re.compile(r'[0-9]+')


def integer_id(text, what='record'):
    """An integer path segment, or 404: an id that is not one names nothing."""
    if not NUMBER.fullmatch(str(text)) or len(str(text)) > 18:
        raise errors.NotFound(f'No such {what}')
    return int(text)
