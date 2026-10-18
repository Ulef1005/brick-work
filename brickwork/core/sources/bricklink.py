"""BrickLink Store API, using the Web API's OAuth signing and price rules."""
import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from decimal import Decimal
from urllib.parse import quote, urlencode
from urllib.request import Request

from .base import Source, SourceError, KeyRejected, ColourCodeError, item, observation, property_value, write, now, record_change

BASE = 'https://api.bricklink.com/api/store/v1'
TYPE_NAMES = dict(S='SET', P='PART', M='MINIFIG', G='GEAR', B='BOOK', C='CATALOG', I='INSTRUCTION', O='ORIGINAL_BOX')
TYPE_IDS = {value: key for key, value in TYPE_NAMES.items()}


def q(value):
    return quote(str(value), safe='~')


def signed_request(path, params, credentials, *, timestamp=None, nonce=None):
    url = BASE + path
    ck, cs, tv, ts = credentials
    oauth = dict(oauth_consumer_key=ck, oauth_token=tv, oauth_signature_method='HMAC-SHA1',
                 oauth_timestamp=str(int(time.time()) if timestamp is None else timestamp),
                 oauth_nonce=nonce or uuid.uuid4().hex, oauth_version='1.0')
    pairs = sorted({**params, **oauth}.items())
    base = '&'.join(['GET', q(url), q('&'.join(f'{q(k)}={q(v)}' for k, v in pairs))])
    key = q(cs) + '&' + q(ts)
    oauth['oauth_signature'] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    auth = 'OAuth ' + ','.join(f'{k}="{q(v)}"' for k, v in oauth.items())
    return Request(url + ('?' + urlencode(params) if params else ''), headers={'Authorization': auth})


class BrickLink(Source):
    label = 'BrickLink'
    source = 'bricklink'
    minimum_spacing = 1
    freshness = {'price': 7, 'subsets': 30, 'item': 30, 'colors': 90, 'orders': 1}
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
        if not re.fullmatch(r'(?:/items/(' + types + r')/[A-Za-z0-9-]{1,32}(/subsets|/price)?|/colors|/colors/[0-9]+|/orders|/orders/[0-9]+/items)', path):
            raise ValueError('unsupported BrickLink endpoint')
        self.ready()
        def consume(reply):
            if reply['meta']['code'] != 200:
                if reply['meta']['code'] == 401 and 'TOKEN_IP_MISMATCHED' in str(reply['meta']):
                    raise SourceError('BrickLink token IP mismatch (public IP changed?)')
                if self.key_refused(reply):
                    raise KeyRejected('BrickLink API unsuccessful')
                raise SourceError('BrickLink API unsuccessful')
            data = reply['data']
            return normalize(data) if normalize else data
        return self.request(path, params or {}, signed_request(path, params or {},
                            self.credential_values()), consume, job_id=job_id)

    def check_key(self):
        """Cheapest authenticated read; proves the four values without changing data."""
        return self.call('/colors/1', normalize=lambda row: True)

    def settings(self):
        values = dict(self.db.execute('SELECT key,value FROM settings'))
        region = values.get('bricklink_region', 'eu')
        currency = values.get('bricklink_currency', 'EUR')
        if not re.fullmatch('[a-z_]{2,32}', region) or not re.fullmatch('[A-Z]{3}', currency):
            raise SourceError('invalid BrickLink settings')
        return region, currency

    def price(self, item_type, identifier, color_id=None, condition='N', *, job_id=None):
        if (item_type not in TYPE_NAMES or condition not in ('N', 'U')
                or not isinstance(identifier, str) or not re.fullmatch('[A-Za-z0-9-]{1,32}', identifier)):
            raise ValueError('invalid price key')
        if color_id is not None and (type(color_id) is not int or color_id < 0):
            raise ValueError('invalid color')
        region, currency = self.settings()
        params = dict(guide_type='sold', new_or_used=condition, currency_code=currency)
        if region != 'all':
            params['region'] = region
        if item_type == 'P' and color_id is not None:
            params['color_id'] = color_id
        def consume(guide):
            quantity = guide['total_quantity']
            if type(quantity) is not int or quantity < 0:
                raise ValueError('invalid quantity')
            price = minimum = maximum = None
            if quantity:
                numbers = [Decimal(str(guide[key])) for key in ('qty_avg_price', 'min_price', 'max_price')]
                if not all(n.is_finite() for n in numbers) or numbers[0] <= 0 or numbers[1] < 0 or numbers[2] <= 0:
                    raise ValueError('invalid price')
                price, minimum, maximum = [format(n, 'f') for n in numbers]
            item(self.db, item_type, identifier)
            observation(self.db, self.source, item_type, identifier, guide=params['guide_type'],
                        price=price, currency=currency, color=color_id, condition=condition,
                        slot='bricklink_new' if condition == 'N' else 'bricklink_used', region=region,
                        qty=quantity, sold=quantity if params['guide_type'] == 'sold' else None,
                        minimum=minimum, maximum=maximum)
            guide_type = params['guide_type']
            return dict(price=price, qty=quantity, guide=guide_type, guide_type=guide_type, currency=currency,
                        source=('bricklink' if guide_type == 'sold' else 'bricklink_stock') if quantity else None,
                        sold=quantity if guide_type == 'sold' else None, min=minimum, max=maximum,
                        region=region, observed_at=now().isoformat())
        path = f'/items/{TYPE_NAMES[item_type]}/{identifier}/price'
        if job_id is not None:
            job = self.db.execute('SELECT kind,payload FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job or job['kind'] != path:
                raise ValueError('price job mismatch')
            saved_params = json.loads(job['payload'])
            params['guide_type'] = saved_params.get('guide_type')
            if params['guide_type'] not in ('sold', 'stock') or params != saved_params:
                raise ValueError('price job parameters mismatch')
        result = self.call(path, params, normalize=consume, job_id=job_id)
        if result['qty'] == 0:
            params['guide_type'] = 'stock'
            result = self.call(path, params, normalize=consume)
        return result

    def part_price(self, item_type, item_no, color_id, condition):
        if item_type not in ('P', 'M'):
            raise ValueError('invalid part price key')
        return self.price(item_type, item_no, color_id, condition)

    def price_slots(self, item_type, identifier, color_id=None):
        kind = TYPE_IDS.get(item_type, item_type)
        return {slot: self.price(kind, identifier, color_id, condition) for slot, condition in
                (('bricklink_new', 'N'), ('bricklink_used', 'U'))}

    def subsets(self, item_type, identifier, *, job_id=None):
        kind = TYPE_IDS.get(item_type, item_type)
        if kind not in ('S', 'M'):
            raise ValueError('invalid inventory parent')
        def consume(groups):
            from ..pipeline import cooperative
            summed = {}
            for group in cooperative(self.db, groups):
                for entry in cooperative(self.db, group['entries']):
                    if entry.get('is_counterpart') or entry.get('is_alternate'):
                        continue
                    child = TYPE_IDS.get(entry['item']['type'])
                    if child not in (('P', 'M') if kind == 'S' else ('P',)):
                        continue
                    number, quantity = entry['item']['no'], entry['quantity']
                    extra, color = entry.get('extra_quantity', 0), entry.get('color_id')
                    if not re.fullmatch('[A-Za-z0-9-]{1,40}', number) or type(quantity) is not int or quantity <= 0:
                        raise ValueError('invalid subset')
                    if type(extra) is not int or not 0 <= extra <= quantity:
                        raise ValueError('invalid extra quantity')
                    if child == 'P' and (type(color) is not int or color < 0):
                        raise ValueError('invalid subset color')
                    key = (child, number, color)
                    old = summed.get(key, (0, 0))
                    summed[key] = (old[0] + quantity, old[1] + extra)
            if not summed:
                raise ValueError('empty subsets')
            item(self.db, kind, identifier)
            write(self.db, 'DELETE FROM inventory_lines WHERE parent_item_type=? AND parent_item_no=? AND source=?',
                  (kind, identifier, self.source))
            result = []
            for (child, number, color), (quantity, extra) in cooperative(self.db, summed.items()):
                item(self.db, child, number)
                if color is not None:
                    write(self.db, 'INSERT OR IGNORE INTO colors(color_id) VALUES(?)', (color,))
                write(self.db, '''INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,
                    child_item_no,color_id,quantity,extra_quantity,source,fetched_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                      (kind, identifier, child, number, color, quantity, extra, self.source, now().isoformat()))
                result.append(dict(item_type=child, item_no=number, color_id=color, quantity=quantity, extra_quantity=extra))
            return result
        return self.call(f'/items/{TYPE_NAMES[kind]}/{identifier}/subsets', normalize=consume, job_id=job_id)

    def sync_colors(self):
        def consume(rows):
            from ..pipeline import cooperative
            codes = []
            for row in rows:
                code = row.get('color_code')
                if code is not None and (not isinstance(code, str) or not re.fullmatch('[0-9A-Fa-f]{6}', code)):
                    raise ColourCodeError()
                codes.append(code.upper() if code is not None else None)
            old_colors = {r['color_id']: dict(r) for r in self.db.execute('SELECT * FROM colors')}
            for row, code in cooperative(self.db, zip(rows, codes)):
                write(self.db, '''INSERT INTO colors(color_id,name,type,rgb) VALUES(?,?,?,?) ON CONFLICT(color_id)
                    DO UPDATE SET name=excluded.name,type=excluded.type,rgb=coalesce(excluded.rgb,colors.rgb)''',
                      (row['color_id'], row['color_name'], row['color_type'], code))
                record_change(self.db, 'color:' + str(row['color_id']), old_colors.get(row['color_id']),
                              dict(color_id=row['color_id'], name=row['color_name'], type=row['color_type'],
                                   rgb=code or (old_colors.get(row['color_id']) or {}).get('rgb')))
            return len(rows)
        return self.call('/colors', normalize=consume)

    def item_info(self, item_type, identifier, *, job_id=None):
        kind = TYPE_IDS.get(item_type, item_type)
        def consume(row):
            if row['no'] != identifier or TYPE_IDS[row['type']] != kind:
                raise ValueError('item mismatch')
            item(self.db, kind, identifier, row['name'])
            for key, value in row.items():
                property_value(self.db, self.source, kind, identifier, key, value)
            write(self.db, 'UPDATE items SET category=?,year=? WHERE item_type=? AND item_no=?',
                  (str(row['category_id']) if row.get('category_id') is not None else None,
                   row.get('year_released'), kind, identifier))
            return row
        return self.call(f'/items/{TYPE_NAMES[kind]}/{identifier}', normalize=consume, job_id=job_id)

    def list_orders(self, filed=False):
        if type(filed) is not bool:
            raise ValueError('filed must be boolean')
        return self.call('/orders', {'direction': 'out', 'filed': str(filed).lower()})

    def order_items(self, order_id):
        if isinstance(order_id, bool) or not re.fullmatch('[0-9]+', str(order_id)):
            raise ValueError('invalid order id')
        return self.call(f'/orders/{order_id}/items')
