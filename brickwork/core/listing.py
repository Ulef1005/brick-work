"""Shared collection filtering and stable keyset pagination, without database reads."""
import base64
from functools import cmp_to_key
from decimal import Decimal
import hashlib
import json
import re

from .errors import BadRequest, UnknownFilter

FILTERS = set('type condition status storage place flag flags tag has stock lot problem duplicates theme category year colour inventory item_no archived under_max since color_id source guide currency kind state entity field copy_id source_id item_type completes has_file owned spare parent bricklink_order_id via undoable failed'.split())
SORTS = set('number name year quantity missing damaged used_price colour index ranking'.split())


def natural(value):
    return [(1, int(v)) if v.isdigit() else (0, v.casefold()) for v in re.split(r'(\d+)', str(value or ''))]


def compare(a, b, key):
    def value(r):
        if key == 'ranking':
            rank = r.get('ranking', [0, 0, '0', '0', 0, '', ''])
            return (rank[0], rank[1], Decimal(rank[2]), Decimal(rank[3]), rank[4], rank[5], rank[6])
        if key == 'used_price':
            p = r.get('price')
            return (p[0], float(p[1])) if p else ('', 0)
        if key == 'missing':
            return float(r.get('missing') or 0) + float(r.get('damaged') or 0)
        if key in ('quantity', 'year', 'damaged', 'index'):
            return float(r.get(key) or 0)
        return natural(r.get(key))
    x, y = value(a), value(b)
    return (x > y) - (x < y)


def comparator(sort, direction, group=''):
    def order(a, b):
        grouped = compare(a, b, group) if group else 0
        absent = (not a.get('price')) - (not b.get('price')) if sort == 'used_price' else 0
        return grouped or absent or compare(a, b, sort) * (-1 if direction == 'desc' or sort == 'missing' else 1) or compare(a, b, 'number') or compare(a, b, 'id')
    return order


def filter_rows(rows, query='', filters=None, sort='number', direction='asc', group=''):
    filters = filters or {}
    if set(filters) - FILTERS or sort not in SORTS or direction not in ('asc', 'desc') or group and group not in SORTS:
        raise UnknownFilter('Unknown filter, sort or direction')
    choices = {'inventory': {'parts', 'figures', 'instructions'}, 'problem': {'missing', 'damaged'},
               'duplicates': {'true', 'false'}, 'archived': {'include', 'only'},
               'under_max': {'true', 'false'},
               **{k: {'true', 'false'} for k in ('completes', 'has_file', 'owned', 'spare', 'undoable', 'failed')}}
    if any(filters.get(key) not in (None, '') and str(filters[key]) not in values for key, values in choices.items()):
        raise UnknownFilter('Unknown filter value')
    from .size_search import parse, matches as size_matches
    full, partial, rest = parse(query)
    def matches(r):
        # #41: a size in the query matches by size key; the remaining words match the text as before.
        if full or partial:
            if not size_matches(r.get('name') or '', full, partial):
                return False
            text = ' '.join(str(r.get(k) or '') for k in ('name', 'number', 'colour', 'category', 'theme', 'year')).casefold()
            if any(word.casefold() not in text for word in rest.split()):
                return False
        elif query.strip().casefold() not in ' '.join(str(r.get(k) or '') for k in ('name', 'number', 'colour', 'category', 'theme', 'year')).casefold():
            return False
        for key, v in filters.items():
            if v is None or v == '':
                continue
            value = str(v)
            if key == 'inventory':
                types = ('M', '?') if value == 'figures' else ('M', '?', 'I', 'O') if value == 'parts' else ('I', 'O')
                if (r.get('type') in types) != (value != 'parts'): return False
            elif key == 'problem':
                if float(r.get(value) or 0) <= 0: return False
            elif key == 'duplicates':
                if str(bool(r.get(key))).lower() != value: return False
            elif key == 'archived':
                if value == 'only' and not r.get('archived_at'): return False
                if value not in ('only', 'include'): raise UnknownFilter('Unknown archive filter')
            elif key == 'since':
                if str(r.get('updated_at') or r.get('created_at') or r.get('at') or r.get('added_at') or '') < value: return False
            elif key == 'under_max':
                if 'max_state' in r:
                    if r['max_state'] != ('under' if value == 'true' else 'over'): return False
                    continue
                if not r.get('price') or r.get('max_price') is None: return False
                if (float(r['price'][1]) <= float(r['max_price'])) != (value == 'true'): return False
            elif key in ('completes', 'has_file', 'owned', 'spare', 'undoable', 'failed'):
                if str(bool(r.get(key))).lower() != value: return False
            elif key == 'lot' and value == 'any':
                lots = r.get('lot', [])
                if not any(str(x) != 'null' for x in (lots if isinstance(lots, list) else [lots])): return False
            elif key == 'colour' and '_api_colour_id' in r:
                if r['_api_colour_id'] != value: return False
            elif key == 'entity':
                if not str(r.get('entity') or '').startswith(value): return False
            else:
                target = 'flags' if key in ('tag', 'has') else 'flag_ids' if key == 'flag' else 'number' if key == 'item_no' else 'type' if key == 'item_type' else key
                actual = r.get(target, '')
                actual = actual if isinstance(actual, list) else [actual]
                value = {'new': 'N', 'used': 'U', 'damaged': 'D'}.get(value, value) if key == 'condition' else value
                value = {'sealed': 'S', 'complete': 'C', 'incomplete': 'I', 'unknown': ''}.get(value, value) if key == 'status' else value
                if value not in [str(x) for x in actual]: return False
        return filters.get('archived') in ('include', 'only') or not r.get('archived_at')
    return sorted(filter(matches, rows), key=cmp_to_key(comparator(sort, direction, group)))


def paginate(rows, *, cursor=None, limit=50, sort='number', direction='asc', signature=''):
    try:
        if isinstance(limit, bool): raise ValueError()
        limit = int(limit)
        if not 1 <= limit <= 200: raise ValueError()
    except (TypeError, ValueError):
        raise BadRequest('Limit must be between 1 and 200') from None
    stamp = hashlib.sha256(json.dumps([sort, direction, signature]).encode()).hexdigest()
    total = len(rows)
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
            if decoded['signature'] != stamp or not isinstance(decoded['after'], dict): raise ValueError()
            order = comparator(sort, direction)
            rows = [r for r in rows if order(r, decoded['after']) > 0]
        except (ValueError, TypeError, KeyError):
            raise BadRequest('Invalid cursor') from None
    selected = rows[:limit]
    after = None
    if len(rows) > limit:
        anchor = {k: selected[-1].get(k) for k in ('id', 'number', sort, 'price', 'damaged')}
        after = base64.urlsafe_b64encode(json.dumps({'signature': stamp, 'after': anchor}).encode()).decode().rstrip('=')
    return {'data': selected, 'page': {'next_cursor': after, 'limit': limit, 'total': total}}
