"""BrickLink Store API on the 4.0 store (M.8f, issue #110; design 3.2, 3.8, user journey 2): the price guide, keyed by item id.

A price is asked for an item (and colour) through the one resolution function (`items.bricklink_key`: the BrickLink type, number and
colour number of the item's confirmed link). An item without one is `Unidentified`: the step ends `done` with the code `unidentified`
(design 3.8, Q21) and nothing is called. The observation keeps the key it priced as `provider_key` (`P:3023/1`, `S:6081-1`), and a
reply that proves an `inferred` link right upgrades it to `matched/bricklink_api`.

The part lists (`/subsets`) are `store4.jobs`' (`bricklink_subsets`); BrickLink's colour table comes with the catalogue builds; this client
keeps the price guide, the key check and the order endpoints (`list_orders`, `order_items`)."""
import html
import hashlib
import json
import os
import re
from decimal import Decimal

from ...store4.audit import Events
from ...store4.bricklink_sign import BASE, q, signed_request  # noqa: F401 (re-exported: signing lives in store4 since M.8a)
from ...store4.fetched import add_item_link
from .. import items
from ..pipeline import StepDone, StepFailed, StepNeedsKey, StepWait
from ..transaction import transaction
from .base import Source, SourceError, KeyRejected, NotFoundAtSource, InvalidReply, WaitingForBudget, observation, stamp, now
from . import base

TYPE_NAMES = dict(S='SET', P='PART', M='MINIFIG', G='GEAR', B='BOOK', C='CATALOG', I='INSTRUCTION', O='ORIGINAL_BOX')
TYPE_IDS = {value: key for key, value in TYPE_NAMES.items()}
NUMBER = re.compile('[A-Za-z0-9-]{1,32}')
SLOTS = {'new': 'bricklink_new', 'used': 'bricklink_used'}
CONDITION_LETTER = {'new': 'N', 'used': 'U'}
NO_COLOUR = 1                                   # "[No Color/Any Color]": a part held in it is asked without a colour filter
INVENTORY_ITEM_TYPES = frozenset((*TYPE_NAMES.values(), 'UNSORTED_LOT'))
CREATE_REQUIRED_FIELDS = frozenset({'item', 'color_id', 'quantity', 'unit_price', 'new_or_used'})
UPDATE_LOT_FIELDS = frozenset({'color_id', 'quantity', 'unit_price', 'new_or_used', 'completeness',
                               'description', 'remarks', 'bulk', 'is_retain', 'is_stock_room', 'stock_room_id'})
CREATE_LOT_FIELDS = CREATE_REQUIRED_FIELDS | UPDATE_LOT_FIELDS


def validate_digits(value, label):
    if not isinstance(value, (int, str)) or isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
        raise ValueError(f'invalid {label}')


def validate_int(value, label, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label} must be an integer >= {minimum}')


def validate_bool(value, label):
    if type(value) is not bool:
        raise ValueError(f'{label} must be boolean')


def validate_text(value, label, *, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f'invalid {label}')


def validate_unit_price(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,4})?', value) or Decimal(value) <= 0:
        raise ValueError('unit_price must be a positive decimal string with at most 4 decimals')


def validate_item_spec(item):
    if not isinstance(item, dict) or set(item) != {'no', 'type'}:
        raise ValueError('item must be a dict with no and type')
    validate_text(item['no'], 'item.no', required=True)
    if not isinstance(item['type'], str) or item['type'] not in INVENTORY_ITEM_TYPES:
        raise ValueError('invalid item.type')


def validate_lot_fields(data, *, allowed, required=()):
    if not isinstance(data, dict):
        raise ValueError('lot payload must be a dict')
    if set(data) - allowed:
        raise ValueError('unexpected lot field')
    if set(required) - set(data):
        raise ValueError('missing required lot field')


def validate_common_lot_fields(data, *, item_type=None):
    if 'color_id' in data:
        validate_int(data['color_id'], 'color_id', minimum=0)
    if 'new_or_used' in data and (not isinstance(data['new_or_used'], str) or data['new_or_used'] not in ('N', 'U')):
        raise ValueError('new_or_used must be N or U')
    if 'completeness' in data:
        if item_type is not None and item_type != 'SET':
            raise ValueError('completeness is only valid for SET items')
        if not isinstance(data['completeness'], str) or data['completeness'] not in ('C', 'B', 'S'):
            raise ValueError('completeness must be C, B or S')
    if 'unit_price' in data:
        validate_unit_price(data['unit_price'])
    if 'bulk' in data:
        validate_int(data['bulk'], 'bulk', minimum=1)
    if 'is_retain' in data:
        validate_bool(data['is_retain'], 'is_retain')
    if 'is_stock_room' in data:
        validate_bool(data['is_stock_room'], 'is_stock_room')
    if 'stock_room_id' in data:
        if data.get('is_stock_room') is not True:
            raise ValueError('stock_room_id requires is_stock_room to be true')
        if not isinstance(data['stock_room_id'], str) or data['stock_room_id'] not in ('A', 'B', 'C'):
            raise ValueError('stock_room_id must be A, B or C')
    for key in ('description', 'remarks'):
        if key in data:
            validate_text(data[key], key)


def validate_create_lot(lot):
    validate_lot_fields(lot, allowed=CREATE_LOT_FIELDS, required=CREATE_REQUIRED_FIELDS)
    validate_item_spec(lot['item'])
    validate_int(lot['quantity'], 'quantity', minimum=1)
    validate_common_lot_fields(lot, item_type=lot['item']['type'])


def validate_update_lot(changes):
    validate_lot_fields(changes, allowed=UPDATE_LOT_FIELDS)
    if not changes:
        raise ValueError('changes must not be empty')
    if 'quantity' in changes:
        value = changes['quantity']
        if not isinstance(value, str) or not re.fullmatch(r'[+-][0-9]+', value):
            raise ValueError('quantity must be a change with a + or - sign')
    validate_common_lot_fields(changes)


def split_tokens(value, label):
    if isinstance(value, str):
        tokens = value.split(',')
    elif isinstance(value, (list, tuple)):
        tokens = list(value)
    else:
        raise ValueError(f'invalid {label}')
    if not tokens or any(not isinstance(token, str) or not token for token in tokens):
        raise ValueError(f'invalid {label}')
    return tokens


def validate_inventory_query(item_type, status, color_id, category_id):
    params = {}
    if item_type is not None:
        tokens = split_tokens(item_type, 'item_type')
        if any(token not in INVENTORY_ITEM_TYPES for token in tokens):
            raise ValueError('invalid item_type')
        params['item_type'] = ','.join(tokens)
    if status is not None:
        tokens = split_tokens(status, 'status')
        if any(not re.fullmatch(r'-?[YSBCNR]', token) for token in tokens):
            raise ValueError('invalid status')
        params['status'] = ','.join(tokens)
    if color_id is not None:
        validate_int(color_id, 'color_id', minimum=0)
        params['color_id'] = color_id
    if category_id is not None:
        validate_digits(category_id, 'category_id')
        params['category_id'] = int(category_id)
    return params


def provider_key(letter, number, colour_key=None):
    """The BrickLink key an observation priced, in the form the migration wrote: `P:3023/1`, `S:6081-1`, `M:air003`."""
    return f'{letter}:{number}' + (f'/{colour_key}' if letter == 'P' and colour_key is not None else '')


class BrickLink(Source):
    label = 'BrickLink'
    source = 'bricklink'
    minimum_spacing = 1
    credentials = tuple('BW_BRICKLINK_' + name for name in
                        ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET'))

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        value = os.environ.get('BW_BRICKLINK_DAILY_BUDGET', '4400')
        if not re.fullmatch(r'[0-9]+', value) or int(value) <= 0:
            raise SourceError('BW_BRICKLINK_DAILY_BUDGET must be a positive integer')
        self.daily_budget = int(value)

    def key_refused(self, reply):
        """A credential error: not an IP, signature-request, clock or nonce problem."""
        meta = reply.get('meta')
        return (isinstance(meta, dict) and meta.get('code') in (401, 403)
                and not re.search(r'IP_MISMATCH|BAD_OAUTH|TIMESTAMP|NONCE', str(meta), re.IGNORECASE))

    def call(self, path, params=None, *, method='GET', body=None, normalize=None, job_id=None):
        types = '|'.join(TYPE_IDS)
        allowed = {
            'GET': r'(?:/items/(' + types + r')/[A-Za-z0-9-]{1,32}(/price)?|/colors/[0-9]+|/orders|/orders/[0-9]+/items|/inventories(?:/[0-9]+)?)',
            'POST': r'/inventories',
            'PUT': r'/inventories/[0-9]+',
            'DELETE': r'/inventories/[0-9]+',
        }
        pattern = allowed.get(method)
        if not pattern or not re.fullmatch(pattern, path):
            raise ValueError('unsupported BrickLink endpoint')
        self.ready()

        def consume(reply):
            meta = reply['meta']
            if meta['code'] not in ((200, 201) if method == 'POST' else (200,)):
                if meta['code'] == 404:
                    raise NotFoundAtSource('BrickLink has no such item')
                if meta['code'] == 401 and 'TOKEN_IP_MISMATCHED' in str(meta):
                    raise SourceError('BrickLink token IP mismatch (public IP changed?)')
                if self.key_refused(reply):
                    raise KeyRejected('BrickLink API unsuccessful')
                raise SourceError('BrickLink API unsuccessful')
            data = None if method == 'DELETE' else reply['data']
            return normalize(data) if normalize else data
        query = params or {}
        key_parts = [method, path, json.dumps(query, sort_keys=True)]
        if body is not None:
            key_parts.append(hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest())
        request = signed_request(path, query, self.credential_values(), method=method, body=body)
        return self.request(path, ' '.join(key_parts), request, consume, job_id=job_id)

    def check_key(self):
        """Cheapest authenticated read; proves the four values without changing data."""
        return self.call('/colors/1', normalize=lambda row: True)

    def item_name(self, letter, number, *, job_id=None):
        """BrickLink's name for an item (`ORIGINAL_BOX` / `INSTRUCTION` of a set number, #382): one call, no price. `NotFoundAtSource` when
        BrickLink does not list it."""
        if letter not in TYPE_NAMES or not NUMBER.fullmatch(str(number)):
            raise ValueError('invalid item key')

        def consume(data):
            name = data.get('name') if isinstance(data, dict) else None
            if isinstance(data, dict) and str(data.get('no')).lower() != str(number).lower():
                raise InvalidReply('BrickLink answered for another item')
            if not isinstance(name, str) or not name.strip():
                raise InvalidReply('BrickLink item has no name')
            return html.unescape(name).strip()
        return self.call(f'/items/{TYPE_NAMES[letter]}/{number}', normalize=consume, job_id=job_id)

    def settings(self):
        values = dict(self.db.execute('SELECT key, value FROM setting'))
        region = values.get('bricklink_region', 'eu')
        currency = values.get('bricklink_currency', 'EUR')
        if not re.fullmatch('[a-z_]{2,32}', region) or not re.fullmatch('[A-Z]{3}', currency):
            raise SourceError('invalid BrickLink settings')
        return region, currency

    def price(self, item_id, color_id=None, condition='used', *, job_id=None):
        """The BrickLink price guide of an item (and colour) in one condition: the sold guide, then the stock guide when nothing sold.

        Writes one `price_observation` per call made (the stock one only when no sale was recorded). `items.Unidentified` when the
        item has no confirmed BrickLink number; nothing is called then."""
        condition = base.CONDITIONS.get(condition)
        if condition is None:
            raise ValueError('invalid price condition')
        letter, number, colour_key = items.bricklink_key(self.db, item_id, color_id)
        if letter not in TYPE_NAMES or not NUMBER.fullmatch(str(number)):
            raise ValueError('invalid price key')
        if letter == 'P' and color_id not in (None, NO_COLOUR) and colour_key is None:
            # without BrickLink's colour the guide is unfiltered: it would be booked as this colour's price
            raise items.Unidentified(f'Colour {color_id} of item {item_id} has no BrickLink colour number')
        region, currency = self.settings()
        key = provider_key(letter, number, colour_key)
        params = dict(guide_type='sold', new_or_used=CONDITION_LETTER[condition], currency_code=currency)
        if region != 'all':
            params['region'] = region
        if letter == 'P' and colour_key is not None:
            params['color_id'] = int(colour_key)

        def consume(guide):
            quantity = guide['total_quantity']
            if type(quantity) is not int or quantity < 0:
                raise ValueError('invalid quantity')
            price = minimum = maximum = None
            if quantity:
                numbers = [Decimal(str(guide[k])) for k in ('qty_avg_price', 'min_price', 'max_price')]
                if not all(n.is_finite() for n in numbers) or numbers[0] <= 0 or numbers[1] < 0 or numbers[2] <= 0:
                    raise ValueError('invalid price')
                price, minimum, maximum = [format(n, 'f') for n in numbers]
            items.ensure(self.db, item_id)
            guide_type = params['guide_type']
            observation(self.db, self.source, item_id, guide=guide_type, price=price, currency=currency, color_id=color_id, condition=condition,
                        slot=SLOTS[condition], region=region, qty=quantity, sold=quantity if guide_type == 'sold' else None,
                        minimum=minimum, maximum=maximum, provider_key=key, job_id=job_id)
            self.confirm_link(item_id, letter, number)
            self.checkpoint(job_id, f'price:{color_id or 0}:{key}:{condition}:{guide_type}', {'qty': quantity})        # in the call's own savepoint: landed means recorded
            return dict(price=price, qty=quantity, guide=guide_type, currency=currency, sold=quantity if guide_type == 'sold' else None,
                        min=minimum, max=maximum, region=region, provider_key=key, observed_at=stamp())

        path = f'/items/{TYPE_NAMES[letter]}/{number}/price'
        sold = self.checkpointed(job_id, f'price:{color_id or 0}:{key}:{condition}:sold')
        result = dict(qty=sold['qty'], guide='sold', provider_key=key, resumed=True) if sold else self.call(path, params, normalize=consume, job_id=job_id)
        if result['qty'] == 0:                                      # each guide call is its own checkpoint: a wait between them resumes at the stock guide
            params['guide_type'] = 'stock'
            stock = self.checkpointed(job_id, f'price:{color_id or 0}:{key}:{condition}:stock')
            result = dict(qty=stock['qty'], guide='stock', provider_key=key, resumed=True) if stock else self.call(path, params, normalize=consume, job_id=job_id)
        return result

    def _step_exists(self, job_id):
        return job_id is not None and self.db.execute("SELECT 1 FROM main.job_step WHERE job_id=? AND name='market_price'", (job_id,)).fetchone() is not None

    def checkpointed(self, job_id, operation):
        """The recorded result of a guide call this pipeline job already made, else None."""
        if not self._step_exists(job_id):
            return None
        row = self.db.execute("SELECT result FROM main.job_call WHERE job_id=? AND step='market_price' AND operation=?", (job_id, operation)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def checkpoint(self, job_id, operation, result):
        if self._step_exists(job_id):
            self.db.execute("INSERT OR REPLACE INTO main.job_call(job_id, step, operation, result) VALUES(?, 'market_price', ?, ?)",
                            (job_id, operation, json.dumps(result)))

    def confirm_link(self, item_id, letter, number):
        """An answer for this BrickLink key proves a rule-made (`inferred`) link right: it becomes `matched/bricklink_api` (user journey 2).
        `manual` and `matched` links are never touched (`fetched.add_item_link`)."""
        for row in self.db.execute('''SELECT color_id FROM main.item_link WHERE item_id=? AND provider='bricklink' AND provider_kind=?
                                      AND provider_key=? AND status='inferred' ''', (item_id, letter, number)).fetchall():
            add_item_link(self.db, item_id, provider='bricklink', provider_kind=letter, provider_key=number, status='matched',
                          method='bricklink_api', origin='api', color_id=row['color_id'],
                          events=Events(self.db, base.AUDIT_ORIGIN.get(), base.AUDIT_ACTOR.get()))

    def list_orders(self, filed=False):
        if type(filed) is not bool:
            raise ValueError('filed must be boolean')
        return self.call('/orders', {'direction': 'out', 'filed': str(filed).lower()})

    def order_items(self, order_id):
        if isinstance(order_id, bool) or not re.fullmatch('[0-9]+', str(order_id)):
            raise ValueError('invalid order id')
        return self.call(f'/orders/{order_id}/items')

    def store_lots(self, item_type=None, status=None, color_id=None, category_id=None):
        return self.call('/inventories', validate_inventory_query(item_type, status, color_id, category_id))

    def store_lot(self, inventory_id):
        validate_digits(inventory_id, 'inventory id')
        return self.call(f'/inventories/{inventory_id}')

    def create_store_lot(self, lot):
        validate_create_lot(lot)
        return self.call('/inventories', method='POST', body=lot)

    def update_store_lot(self, inventory_id, changes):
        validate_digits(inventory_id, 'inventory id')
        validate_update_lot(changes)
        return self.call(f'/inventories/{inventory_id}', method='PUT', body=changes)

    def delete_store_lot(self, inventory_id):
        validate_digits(inventory_id, 'inventory id')
        return self.call(f'/inventories/{inventory_id}', method='DELETE')


# ---------- the pipeline step ----------

def watch(db, item_id, color_id, condition):
    """Note that the item's price in this condition is kept fresh: `price_watch` (item, colour, condition) with the time of the last fetch.
    `origin` says why it is watched: `owned` when a copy or loose stock holds the item, else `wanted`."""
    stamp_now = base.store_now()
    owned = db.execute('''SELECT 1 FROM main.copy WHERE item_id=:i AND archived_at IS NULL
                          UNION ALL SELECT 1 FROM main.stock WHERE item_id=:i AND archived_at IS NULL LIMIT 1''', {'i': item_id}).fetchone()
    db.execute('''INSERT INTO price_watch(item_id, color_id, condition, origin, first_seen, last_fetch_at, last_attempt_at) VALUES(?, ?, ?, ?, ?, ?, ?)
                  ON CONFLICT(item_id, color_key, condition_key) DO UPDATE SET last_fetch_at=excluded.last_fetch_at,
                  last_attempt_at=excluded.last_attempt_at, last_error=NULL, last_error_at=NULL''',
               (item_id, color_id, condition, 'owned' if owned else 'wanted', stamp_now, stamp_now, stamp_now))



def market_price(db, job, step, *, http=None):
    """The `market_price` step: each colour the item is held in, new and used. Resumes after a budget wait without repeating a call that
    already landed (`job_call` keeps one row per finished key and condition). `StepDone('unidentified')` for an item with no BrickLink key."""
    item_id = job['item_id']
    client = BrickLink(db, http=http)
    done = {r['operation'] for r in db.execute('SELECT operation FROM main.job_call WHERE job_id=? AND step=?', (job['id'], step['name']))}
    unmapped = set()
    for color_id in items.colours_held(db, item_id):
        for condition in ('new', 'used'):
            try:
                letter, number, colour_key = items.bricklink_key(db, item_id, color_id)
            except items.Unidentified:
                raise StepDone('unidentified', 'The item has no BrickLink number, so no price can be asked for') from None
            if letter == 'P' and color_id not in (None, NO_COLOUR) and colour_key is None:
                unmapped.add(color_id)                              # never asked: an unfiltered guide is not this colour's price
                continue
            operation = f'price:{color_id or 0}:{provider_key(letter, number, colour_key)}:{condition}'     # the internal colour too: two colours can share a BrickLink one
            if operation in done:
                continue
            try:
                client.price(item_id, color_id, condition, job_id=job['id'])
            except WaitingForBudget as wait:
                raise StepWait(wait.retry_at, 'waiting for budget') from None
            except base.SourceNotConfigured as error:
                raise StepNeedsKey(str(error)) from None                # #139: no key yet is not a failure
            except base.SourceDisabled as error:
                raise StepFailed('source_not_configured', str(error)) from None
            except KeyRejected as error:
                raise StepFailed('source_not_configured', str(error)) from None
            except NotFoundAtSource as error:
                raise StepFailed('not_found', str(error)) from None
            except InvalidReply as error:
                raise StepFailed('invalid_reply', str(error)) from None
            except SourceError as error:
                raise StepFailed('source_error', str(error)) from None
            with transaction(db):
                db.execute('INSERT OR REPLACE INTO main.job_call(job_id, step, operation, result) VALUES(?, ?, ?, ?)',
                           (job['id'], step['name'], operation, json.dumps({'at': stamp()})))
                watch(db, item_id, color_id, condition)
            done.add(operation)
    if unmapped:                                                    # the other colours were priced; this finding is the step's end
        raise StepDone('unidentified', f'{len(unmapped)} colour(s) have no BrickLink colour number, so no price was asked for them')


def handlers(*, http=None):
    def run(db, job, step):
        with base.audit_origin(job['via'], job.get('actor')):
            market_price(db, job, step, http=http)
    return {('market_price', 'bricklink'): run}
