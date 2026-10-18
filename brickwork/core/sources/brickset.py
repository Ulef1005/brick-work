"""Brickset API v3 metadata and country retail prices, never market values."""
import json
import os
import re
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request

from .base import Source, SourceError, KeyRejected, item, observation, property_value, write, now

BASE = 'https://brickset.com/api/v3.asmx'
CURRENCIES = {'DE': 'EUR', 'US': 'USD', 'UK': 'GBP', 'CA': 'CAD'}


class Brickset(Source):
    label = 'Brickset'
    source = 'brickset'
    daily_budget = 100
    minimum_spacing = 0
    freshness = {'getSets': 30, 'checkKey': 1, 'getKeyUsageStats': 1}
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
                    from .base import RemoteBudgetExceeded
                    raise RemoteBudgetExceeded()
                if re.search(r'invalid.*key|key.*invalid', str(reply.get('message', '')), re.IGNORECASE):
                    raise KeyRejected('Brickset API unsuccessful')
                raise SourceError('Brickset API unsuccessful')
            return normalize(reply) if normalize else reply
        request = Request(BASE + '/' + method, data=urlencode(body).encode(),
                          headers={'Content-Type': 'application/x-www-form-urlencoded'})
        return self.request(method, params or {}, request, consume,
                            charged=method == 'getSets', job_id=job_id)

    def check_key(self):
        return self.call('checkKey')

    def key_usage_stats(self):
        return self.call('getKeyUsageStats')

    def refresh(self, numbers, *, job_id=None):
        from ..pipeline import cooperative
        numbers = list(dict.fromkeys(numbers))
        if not numbers:
            numbers = [row[0] for row in self.db.execute("SELECT item_no FROM items WHERE item_type='S' ORDER BY item_no")]
        if any(not isinstance(n, str) or not re.fullmatch('[A-Za-z0-9-]{1,32}', n) for n in numbers):
            raise ValueError('invalid set number')
        if job_id is not None and len(numbers) > 500:
            raise ValueError('resume one batch at a time')
        setting = self.db.execute("SELECT value FROM settings WHERE key='retail_country'").fetchone()
        country = setting[0] if setting else 'DE'
        if country not in CURRENCIES:
            raise ValueError('unsupported retail country')
        results = []
        for offset in cooperative(self.db, range(0, len(numbers), 500)):
            batch = numbers[offset:offset + 500]
            mapping = {}
            for canonical in cooperative(self.db, batch):
                match = self.db.execute('''SELECT source_id FROM id_match WHERE source='brickset'
                    AND kind='set_number' AND item_type='S' AND item_no=?
                    AND status IN ('matched','inferred','manual')''', (canonical,)).fetchall()
                if len(match) > 1:
                    raise ValueError('ambiguous Brickset mapping')
                source_no = match[0][0] if match else (canonical + '-1' if canonical.isdigit() else canonical)
                if source_no in mapping:
                    raise ValueError('ambiguous Brickset mapping')
                mapping[source_no] = canonical
            def consume(reply):
                rows = reply['sets']
                if not isinstance(rows, list) or reply.get('matches', len(rows)) > 500:
                    raise ValueError('unexpected Brickset batch')
                mapped = []
                for row in cooperative(self.db, rows):
                    source_no = f"{row['number']}-{row['numberVariant']}"
                    canonical = mapping.get(source_no)
                    if canonical is None:
                        write(self.db, '''INSERT OR REPLACE INTO id_match(source,kind,source_id,status,evidence_json)
                            VALUES('brickset','set_number',?,'unmatched',?)''', (source_no, json.dumps(row)))
                        continue
                    item(self.db, 'S', canonical)
                    write(self.db, '''INSERT OR REPLACE INTO id_match(source,kind,source_id,item_type,item_no,
                        method,status,evidence_json,decided_at) VALUES('brickset','set_number',?,'S',?,?,'matched',?,?)''',
                          (source_no, canonical, 'set_number', json.dumps({'setID': row['setID']}), now().isoformat()))
                    for key in ('setID', 'theme', 'subtheme', 'year', 'pieces', 'minifigs', 'name', 'category', 'availability'):
                        property_value(self.db, self.source, 'S', canonical, key, row.get(key))
                    retail = row.get('LEGOCom', {}).get(country, {})
                    for key in ('dateFirstAvailable', 'dateLastAvailable'):
                        property_value(self.db, self.source, 'S', canonical, key, retail.get(key))
                    if retail.get('retailPrice') is not None:
                        price = Decimal(str(retail['retailPrice']))
                        if not price.is_finite() or price < 0:
                            raise ValueError('invalid retail price')
                        observation(self.db, self.source, 'S', canonical, guide='retail',
                                    price=format(price, 'f'), currency=CURRENCIES[country], region=country, slot='retail')
                    mapped.append(canonical)
                return mapped
            results.extend(self.call('getSets', {'setNumber': ','.join(mapping), 'pageSize': 500}, normalize=consume, job_id=job_id))
        return results
