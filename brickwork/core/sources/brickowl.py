"""Brick Owl API v1 client (#522)."""
from datetime import datetime, timezone
import math
import os
import re
from urllib.parse import urlencode
from urllib.request import Request

from . import base
from .base import KeyRejected, Source, SourceError

BASE = 'https://api.brickowl.com/v1'
_ENDPOINTS = {
    'GET': re.compile(
        r'(?:user/details|collection/lots|wishlist/(?:lists|lots)|order/(?:list|view|items)|catalog/id_lookup)'
    ),
    'POST': re.compile(
        r'(?:collection/(?:create_lot|update|delete_lot)|wishlist/(?:create_lot|update|delete_lot))'
    ),
}
_ID_TYPES = ('item_no', 'design_id', 'bl_item_no', 'set_number')
_TEXT_PATTERN = re.compile(r'[A-Za-z0-9_-]{1,64}')
_INT_PATTERN = re.compile(r'[0-9]+')


def _validate_id(value, pattern, message):
    if value is None or isinstance(value, bool) or not pattern.fullmatch(str(value)):
        raise ValueError(message)
    return str(value)


def _validate_positive_int(value, message):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(message)
    return value


def _error_text(reply):
    if not isinstance(reply, dict) or not reply.get('error'):
        return ''
    error = reply['error']
    if isinstance(error, dict):
        return ' '.join(str(v) for v in error.values() if isinstance(v, (str, int)) and not isinstance(v, bool))
    return str(error)


def _succeeded(reply):
    if not isinstance(reply, dict) or reply.get('status') != 'Success':
        raise SourceError('Brick Owl did not confirm the change')
    return reply


def _created_lot(reply):
    _succeeded(reply)
    lot_id = reply.get('lot_id') if isinstance(reply, dict) else None
    if lot_id is None or isinstance(lot_id, bool) or not isinstance(lot_id, (str, int)) or not str(lot_id).strip():
        raise SourceError('Brick Owl did not return a lot')
    return str(lot_id).strip()


def _unix_timestamp(since):
    if isinstance(since, bool):
        raise ValueError('invalid since timestamp')
    if isinstance(since, (int, float)):
        if not math.isfinite(since) or since < 0:
            raise ValueError('invalid since timestamp')
        return int(since)
    if isinstance(since, datetime):
        moment = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        return int(moment.timestamp())
    if isinstance(since, str):
        if _INT_PATTERN.fullmatch(since):
            return int(since)
        try:
            return int(base.parse(since).timestamp())
        except ValueError:
            pass
    raise ValueError('invalid since timestamp')


class BrickOwl(Source):
    """Brick Owl API v1 client."""

    label = 'Brick Owl'
    source = 'brickowl'
    daily_budget = 2000
    minimum_spacing = 0.2
    credentials = ('BW_BRICKOWL_API_KEY',)

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        value = os.environ.get('BW_BRICKOWL_DAILY_BUDGET', str(self.daily_budget))
        if not _INT_PATTERN.fullmatch(value) or int(value) <= 0:
            raise SourceError('BW_BRICKOWL_DAILY_BUDGET must be a positive integer')
        self.daily_budget = min(self.daily_budget, int(value))

    def key_refused(self, reply):
        """True only when an error reply reports access denied or invalid key."""
        text = _error_text(reply)
        return bool(text and re.search(r'access\s+denied|invalid.*key|key.*invalid', text, re.IGNORECASE))

    def call(self, path, params=None, *, method='GET', normalize=None, job_id=None):
        """Send one GET or POST request to an allow-listed Brick Owl endpoint."""
        allowed = _ENDPOINTS.get(method)
        if not allowed or not isinstance(path, str) or not allowed.fullmatch(path):
            raise ValueError('unsupported Brick Owl endpoint')
        self.ready()
        api_key = self.credential_values()[0]
        clean = {k: v for k, v in (params or {}).items() if v is not None and k != 'key'}
        record_key = f'{path}?{urlencode(sorted(clean.items()))}' if clean else path
        payload = urlencode({'key': api_key, **clean})
        if method == 'POST':
            request = Request(
                f'{BASE}/{path}',
                data=payload.encode(),
                method='POST',
                headers={'User-Agent': base.USER_AGENT, 'Content-Type': 'application/x-www-form-urlencoded'},
            )
        else:
            request = Request(f'{BASE}/{path}?{payload}', headers={'User-Agent': base.USER_AGENT})

        def consume(reply):
            text = _error_text(reply)
            if text:
                if re.search(r'quota\s+exceeded|rate\s+limit|too\s+many\s+requests', text, re.IGNORECASE):
                    raise base.RemoteBudgetExceeded()
                if re.search(r'access\s+denied|invalid\s+(?:api\s+)?key|(?:api\s+)?key\s+(?:is\s+)?invalid', text, re.IGNORECASE):
                    raise KeyRejected('Brick Owl API unsuccessful')
                raise SourceError('Brick Owl API unsuccessful')
            return normalize(reply) if normalize else reply

        return self.request(path, record_key, request, consume, charged=True, job_id=job_id)

    def check_key(self):
        """Verify the Brick Owl API key with a user/details call."""
        return self.call('user/details')

    def collection_lots(self):
        """Fetch the account collection lots."""
        return self.call('collection/lots')

    def wishlist_lists(self):
        """Fetch the account wishlists."""
        return self.call('wishlist/lists')

    def wishlist_lots(self, wishlist_id):
        """Fetch lots for one wishlist."""
        wid = _validate_id(wishlist_id, _TEXT_PATTERN, 'invalid wishlist id')
        return self.call('wishlist/lots', {'wishlist_id': wid})

    def orders(self, list_type='customer', *, limit=500, offset=0, since=None):
        """Fetch customer or store orders."""
        if list_type not in ('customer', 'store'):
            raise ValueError('invalid order list type')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            raise ValueError('invalid limit')
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError('invalid offset')
        params = {'list_type': list_type, 'limit': limit, 'offset': offset}
        if since is not None:
            params['update_time'] = _unix_timestamp(since)
        return self.call('order/list', params)

    def order(self, order_id):
        """Fetch one order by id."""
        oid = _validate_id(order_id, _INT_PATTERN, 'invalid order id')
        return self.call('order/view', {'order_id': oid})

    def order_items(self, order_id):
        """Fetch items for one order."""
        oid = _validate_id(order_id, _INT_PATTERN, 'invalid order id')
        return self.call('order/items', {'order_id': oid})

    def id_lookup(self, id_value, item_type, id_type=None):
        """Look up a Brick Owl catalog id."""
        if id_value is None or isinstance(id_value, bool) or not str(id_value).strip():
            raise ValueError('invalid id')
        if not isinstance(item_type, str) or not re.fullmatch(r'[A-Za-z_]{1,32}', item_type):
            raise ValueError('invalid item type')
        if id_type is not None and id_type not in _ID_TYPES:
            raise ValueError('invalid id type')
        params = {'id': str(id_value).strip(), 'type': item_type}
        if id_type is not None:
            params['id_type'] = id_type
        return self.call('catalog/id_lookup', params)

    def create_collection_lot(self, boid, color_id=None):
        """Create a collection lot and return its lot id."""
        params = {'boid': _validate_id(boid, _TEXT_PATTERN, 'invalid boid')}
        if color_id is not None:
            params['color_id'] = _validate_id(color_id, _INT_PATTERN, 'invalid color id')
        return self.call('collection/create_lot', params, method='POST', normalize=_created_lot)

    def update_collection_lot(self, lot_id, quantity=None, condition=None):
        """Update quantity or condition of one collection lot."""
        lid = _validate_id(lot_id, _TEXT_PATTERN, 'invalid lot id')
        if quantity is None and condition is None:
            raise ValueError('nothing to update')
        params = {'lot_id': lid}
        if quantity is not None:
            params['quantity'] = _validate_positive_int(quantity, 'invalid quantity')
        if condition is not None:
            params['condition'] = _validate_id(condition, _TEXT_PATTERN, 'invalid condition')
        return self.call('collection/update', params, method='POST', normalize=_succeeded)

    def delete_collection_lot(self, lot_id):
        """Delete one collection lot."""
        lid = _validate_id(lot_id, _TEXT_PATTERN, 'invalid lot id')
        return self.call('collection/delete_lot', {'lot_id': lid}, method='POST', normalize=_succeeded)

    def create_wishlist_lot(self, wishlist_id, boid):
        """Create a wishlist lot and return its lot id."""
        wid = _validate_id(wishlist_id, _TEXT_PATTERN, 'invalid wishlist id')
        bid = _validate_id(boid, _TEXT_PATTERN, 'invalid boid')
        return self.call('wishlist/create_lot', {'wishlist_id': wid, 'boid': bid}, method='POST', normalize=_created_lot)

    def update_wishlist_lot(self, wishlist_id, lot_id, minimum_quantity):
        """Update minimum quantity of one wishlist lot."""
        wid = _validate_id(wishlist_id, _TEXT_PATTERN, 'invalid wishlist id')
        lid = _validate_id(lot_id, _TEXT_PATTERN, 'invalid lot id')
        qty = _validate_positive_int(minimum_quantity, 'invalid quantity')
        return self.call('wishlist/update', {'wishlist_id': wid, 'lot_id': lid, 'minimum_quantity': qty}, method='POST', normalize=_succeeded)

    def delete_wishlist_lot(self, wishlist_id, lot_id):
        """Delete one wishlist lot."""
        wid = _validate_id(wishlist_id, _TEXT_PATTERN, 'invalid wishlist id')
        lid = _validate_id(lot_id, _TEXT_PATTERN, 'invalid lot id')
        return self.call('wishlist/delete_lot', {'wishlist_id': wid, 'lot_id': lid}, method='POST', normalize=_succeeded)
