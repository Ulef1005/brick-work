"""BrickLink Store API on the 4.0 store (M.8f, issue #110; design 3.2, 3.8, user journey 2): the price guide, keyed by item id.

A price is asked for an item (and colour) through the one resolution function (`items.bricklink_key`: the BrickLink type, number and
colour number of the item's confirmed link). An item without one is `Unidentified`: the step ends `done` with the code `unidentified`
(design 3.8, Q21) and nothing is called. The observation keeps the key it priced as `provider_key` (`P:3023/1`, `S:6081-1`), and a
reply that proves an `inferred` link right upgrades it to `matched/bricklink_api`.

The part lists (`/subsets`) are `store4.jobs`' (`bricklink_subsets`); BrickLink's colour table comes with the catalogue builds; this client
keeps the price guide, the key check and the order endpoints (`list_orders`, `order_items`)."""
import json
import os
import re
from decimal import Decimal

from ...store4.audit import Events
from ...store4.bricklink_sign import BASE, q, signed_request  # noqa: F401 (re-exported: signing lives in store4 since M.8a)
from ...store4.fetched import add_item_link
from .. import items
from ..pipeline import StepDone, StepFailed, StepWait
from ..transaction import transaction
from .base import Source, SourceError, KeyRejected, NotFoundAtSource, InvalidReply, WaitingForBudget, observation, stamp, now
from . import base

TYPE_NAMES = dict(S='SET', P='PART', M='MINIFIG', G='GEAR', B='BOOK', C='CATALOG', I='INSTRUCTION', O='ORIGINAL_BOX')
TYPE_IDS = {value: key for key, value in TYPE_NAMES.items()}
NUMBER = re.compile('[A-Za-z0-9-]{1,32}')
SLOTS = {'new': 'bricklink_new', 'used': 'bricklink_used'}
CONDITION_LETTER = {'new': 'N', 'used': 'U'}
NO_COLOUR = 1                                   # "[No Color/Any Color]": a part held in it is asked without a colour filter


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

    def call(self, path, params=None, *, normalize=None, job_id=None):
        types = '|'.join(TYPE_IDS)
        if not re.fullmatch(r'(?:/items/(' + types + r')/[A-Za-z0-9-]{1,32}(/price)?|/colors/[0-9]+|/orders|/orders/[0-9]+/items)', path):
            raise ValueError('unsupported BrickLink endpoint')
        self.ready()

        def consume(reply):
            meta = reply['meta']
            if meta['code'] != 200:
                if meta['code'] == 404:
                    raise NotFoundAtSource('BrickLink has no such item')
                if meta['code'] == 401 and 'TOKEN_IP_MISMATCHED' in str(meta):
                    raise SourceError('BrickLink token IP mismatch (public IP changed?)')
                if self.key_refused(reply):
                    raise KeyRejected('BrickLink API unsuccessful')
                raise SourceError('BrickLink API unsuccessful')
            data = reply['data']
            return normalize(data) if normalize else data
        return self.request(path, json.dumps(params or {}, sort_keys=True), signed_request(path, params or {}, self.credential_values()),
                            consume, job_id=job_id)

    def check_key(self):
        """Cheapest authenticated read; proves the four values without changing data."""
        return self.call('/colors/1', normalize=lambda row: True)

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
                raise StepFailed('source_not_configured', str(error)) from None
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
