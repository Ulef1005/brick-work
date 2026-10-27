"""Brickset API v3 on the 4.0 store (M.8f, issue #110; user journey 2): set metadata and country retail prices, never market values.

What Brickset says about a set is `item_property(source='brickset')` and, for the retail country, one `price_observation(guide='retail')`.
A set Brickset does not know gets `item_provider_status(brickset, unmatched, no_match)` (design 3.2): looked, nothing found.

The Brickset number of an item is, in order: a confirmed `brickset` link (`item_link`), the Rebrickable number of a Rebrickable-born set
(`6081-1` is Brickset's form too), else the BrickLink number of a BrickLink-born set (`6081` is read as `6081-1`)."""
import json
import re
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request

from ...store4.connect import now as store_now
from .. import items
from ..pipeline import StepDone, StepFailed, StepWait
from . import base
from .base import Source, SourceError, KeyRejected, InvalidReply, NotFoundAtSource, WaitingForBudget, observation, property_value

BASE = 'https://brickset.com/api/v3.asmx'
CURRENCIES = {'DE': 'EUR', 'US': 'USD', 'UK': 'GBP', 'CA': 'CAD'}
PROPERTY_KEYS = ('setID', 'theme', 'subtheme', 'year', 'pieces', 'minifigs', 'name', 'category', 'availability')
NUMBER = re.compile('[A-Za-z0-9-]{1,32}')
BATCH = 500


class Brickset(Source):
    label = 'Brickset'
    source = 'brickset'
    daily_budget = 100
    minimum_spacing = 0
    credentials = ('BW_BRICKSET_API_KEY',)

    def call(self, method, params=None, *, normalize=None, job_id=None):
        if method not in ('getSets', 'checkKey', 'getKeyUsageStats'):
            raise ValueError('unsupported Brickset endpoint')
        self.ready()
        body = dict(apiKey=self.credential_values()[0])
        if params is not None:
            body.update(userHash='', params=json.dumps(params))

        def consume(reply):
            if reply['status'] != 'success':
                if reply.get('message') == 'API limit exceeded':
                    raise base.RemoteBudgetExceeded()
                if re.search(r'invalid.*key|key.*invalid', str(reply.get('message', '')), re.IGNORECASE):
                    raise KeyRejected('Brickset API unsuccessful')
                raise SourceError('Brickset API unsuccessful')
            return normalize(reply) if normalize else reply
        request = Request(BASE + '/' + method, data=urlencode(body).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
        return self.request(method, json.dumps(params or {}, sort_keys=True), request, consume, charged=method == 'getSets', job_id=job_id)

    def check_key(self):
        return self.call('checkKey')

    def key_usage_stats(self):
        return self.call('getKeyUsageStats')

    def country(self):
        row = self.db.execute("SELECT value FROM setting WHERE key='retail_country'").fetchone()
        country = row[0] if row and row[0] else 'DE'
        if country not in CURRENCIES:
            raise ValueError('unsupported retail country')
        return country

    def number_of(self, item_id):
        """Brickset's number for a set item, or None when the item has nothing to ask with."""
        link = self.db.execute('''SELECT provider_key FROM main.item_link WHERE item_id=? AND provider='brickset' AND status IN ('manual','matched','inferred')
                                  ORDER BY preferred DESC, CASE status WHEN 'manual' THEN 0 WHEN 'matched' THEN 1 ELSE 2 END, provider_key LIMIT 1''',
                                (item_id,)).fetchone()
        if link:
            return link[0]
        label = items.label(self.db, item_id)
        if label.number is None:
            return None
        if label.source == 'bricklink':
            return label.number + '-1' if label.number.isdigit() else label.number
        return label.number

    def refresh(self, item_ids, *, job_id=None):
        """Ask Brickset about sets (up to 500 per call). Returns the item ids Brickset knew; the others get `unmatched/no_match`."""
        item_ids = list(dict.fromkeys(item_ids))
        mapping = {}
        for item_id in item_ids:
            number = self.number_of(item_id)
            if number is None or not NUMBER.fullmatch(number):
                raise ValueError(f'item {item_id} has no Brickset number')
            if mapping.setdefault(number, item_id) != item_id:
                raise ValueError('ambiguous Brickset mapping')
        country, known = self.country(), []
        for offset in range(0, len(mapping), BATCH):
            batch = dict(list(mapping.items())[offset:offset + BATCH])

            def consume(reply, batch=batch):
                rows = reply['sets']
                if not isinstance(rows, list) or reply.get('matches', len(rows)) > BATCH:
                    raise ValueError('unexpected Brickset batch')
                seen = set()
                for row in rows:
                    item_id = batch.get(f"{row['number']}-{row['numberVariant']}")
                    if item_id is None:
                        continue
                    items.ensure(self.db, item_id)
                    for key in PROPERTY_KEYS:
                        property_value(self.db, self.source, item_id, key, row.get(key))
                    retail = (row.get('LEGOCom') or {}).get(country) or {}
                    for key in ('dateFirstAvailable', 'dateLastAvailable'):
                        property_value(self.db, self.source, item_id, key, retail.get(key))
                    if retail.get('retailPrice') is not None:
                        price = Decimal(str(retail['retailPrice']))
                        if not price.is_finite() or price < 0:
                            raise ValueError('invalid retail price')
                        observation(self.db, self.source, item_id, guide='retail', price=format(price, 'f'), currency=CURRENCIES[country],
                                    region=country, slot='retail', job_id=job_id)
                    self.db.execute('DELETE FROM main.item_provider_status WHERE item_id=? AND provider=? AND reason=?', (item_id, self.source, 'no_match'))
                    seen.add(item_id)
                for number, item_id in batch.items():
                    if item_id not in seen:
                        items.ensure(self.db, item_id)
                        self.db.execute('''INSERT INTO main.item_provider_status(item_id, provider, status, reason, evidence_json, checked_at)
                                           VALUES(?, ?, 'unmatched', 'no_match', ?, ?) ON CONFLICT(item_id, provider, reason)
                                           DO UPDATE SET evidence_json=excluded.evidence_json, checked_at=excluded.checked_at''',
                                        (item_id, self.source, json.dumps({'brickset': number}, sort_keys=True), store_now()))
                return sorted(seen)
            known += self.call('getSets', {'setNumber': ','.join(batch), 'pageSize': BATCH}, normalize=consume, job_id=job_id)
        return known


# ---------- the pipeline step ----------

def metadata(db, job, step, *, http=None):
    """The `metadata` step for one set: properties and retail price. `StepDone('unidentified')` for a set with no number to ask with,
    `StepDone('not_found')` when Brickset does not know it (a finding, not a failure: asking again gives the same)."""
    item_id = job['item_id']
    client = Brickset(db, http=http)
    if client.number_of(item_id) is None:
        raise StepDone('unidentified', 'The set has no number from any provider, so Brickset cannot be asked')
    try:
        known = client.refresh([item_id], job_id=job['id'])
    except WaitingForBudget as wait:
        raise StepWait(wait.retry_at, 'waiting for budget') from None
    except (base.SourceNotConfigured, base.SourceDisabled, KeyRejected) as error:
        raise StepFailed('source_not_configured', str(error)) from None
    except NotFoundAtSource as error:
        raise StepFailed('not_found', str(error)) from None
    except InvalidReply as error:
        raise StepFailed('invalid_reply', str(error)) from None
    except SourceError as error:
        raise StepFailed('source_error', str(error)) from None
    if item_id not in known:
        raise StepDone('not_found', 'Brickset does not know this set')


def handlers(*, http=None):
    def run(db, job, step):
        with base.audit_origin(job['via'], job.get('actor')):
            metadata(db, job, step, http=http)
    return {('metadata', 'brickset'): run}
