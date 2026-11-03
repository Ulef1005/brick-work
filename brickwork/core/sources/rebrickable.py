"""Rebrickable API v3 on the 4.0 store (M.8f, issue #110; design 3.2, 6.8): picture URLs and external-id evidence, keyed by item id.

The catalogue and the set part lists come from the dump and from `store4.rebrickable_api` (the `rebrickable_set` job); this client asks
for what neither has: the picture of a part in a colour (`/parts/{num}/colors/{id}/`) or of a set or figure, and a part's record, whose
`external_ids` say which BrickLink number it is. Evidence about a BrickLink number is written the way the collection records links:
exactly one BrickLink id gives a `matched/external_ids` link; none or several give `item_provider_status(bricklink, unmatched, no_match)`
and no link. A refresh never replaces a `manual` link and never downgrades a confirmed one."""
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request

from ...store4.audit import Events
from ...store4.connect import now as store_now
from ...store4.fetched import add_item_link
from .. import items
from . import base
from .base import Source, SourceError, KeyRejected, NotFoundAtSource, RemoteBudgetExceeded

BASE = 'https://rebrickable.com/api/v3/lego'
PATH = re.compile(r'/(?:parts|colors|minifigs|sets)/(?:[A-Za-z0-9._-]+/(?:colors/[0-9]+/)?)?')
CONFIRMED = ('manual', 'matched', 'inferred')


class Rebrickable(Source):
    label = 'Rebrickable'
    source = 'rebrickable'
    minimum_spacing = 1
    credentials = ('BW_REBRICKABLE_API_KEY',)

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        budget = os.environ.get('BW_REBRICKABLE_DAILY_BUDGET', '1000')
        if not re.fullmatch('[0-9]+', budget) or int(budget) <= 0:
            raise SourceError('BW_REBRICKABLE_DAILY_BUDGET must be a positive integer')
        self.daily_budget = int(budget)

    def call(self, path, params=None, *, normalize=None, job_id=None):
        if not PATH.fullmatch(path):
            raise ValueError('unsupported Rebrickable endpoint')
        self.ready()

        def consume(reply):
            if not isinstance(reply, dict):
                raise base.InvalidReply('Rebrickable returned an invalid reply')
            if 'detail' in reply:
                detail = str(reply['detail'])
                if 'throttled' in detail.lower():
                    match = re.search(r'available in ([0-9]+) seconds?', detail, re.IGNORECASE)
                    raise RemoteBudgetExceeded(retry_seconds=max(1, min(86400, int(match[1]))) if match else 60)
                if re.search(r'invalid token|authentication credentials', detail, re.IGNORECASE):
                    raise KeyRejected('Rebrickable API unsuccessful')
                if re.search(r'not found', detail, re.IGNORECASE):
                    raise NotFoundAtSource('Rebrickable has no such record')
                raise SourceError('Rebrickable API unsuccessful')
            return normalize(reply) if normalize else reply
        params = params or {}
        request = Request(BASE + path + ('?' + urlencode(params) if params else ''), headers={'Authorization': 'key ' + self.credential_values()[0]})
        return self.request(path, json.dumps(params, sort_keys=True), request, consume, job_id=job_id)

    def check_key(self):
        return self.call('/colors/0/', normalize=lambda row: True)

    def picture_url(self, path, key, *, item_id=None, job_id=None):
        """The picture URL in the record at `path` (`part_img_url` or `set_img_url`). A part's own record (`/parts/{num}/`) also tells which
        BrickLink number it is: with `item_id` that evidence is recorded (`record_match`)."""
        def consume(row):
            if item_id is not None and 'external_ids' in row:
                self.record_match(item_id, row)
            url = row.get(key)
            if not url or not isinstance(url, str):
                raise NotFoundAtSource('Rebrickable has no picture for this item')
            return url
        return self.call(path, normalize=consume, job_id=job_id)

    def part(self, item_id, *, job_id=None):
        """The record of a Rebrickable-born part; its BrickLink evidence is recorded. Returns the record."""
        label = items.label(self.db, item_id)
        if label.kind != 'part' or label.source != 'rebrickable':
            raise ValueError('only a Rebrickable-born part can be asked for its record')
        number = label.number

        def consume(record):
            if record.get('part_num') != number:
                raise base.InvalidReply('Rebrickable answered with another part')
            self.record_match(item_id, record)
            return record
        return self.call(f'/parts/{number}/', normalize=consume, job_id=job_id)

    def record_match(self, item_id, record):
        """Write what a part record says about the item's BrickLink number (call inside the request's savepoint)."""
        ids = record.get('external_ids', {}).get('BrickLink', [])
        if isinstance(ids, dict):
            ids = ids.get('ext_ids', [])
        ids = list(dict.fromkeys(str(value) for value in ids))
        items.ensure(self.db, item_id)
        if len(ids) == 1:
            add_item_link(self.db, item_id, provider='bricklink', provider_kind='P', provider_key=ids[0], status='matched', method='external_ids',
                          origin='api', evidence={'rebrickable': record.get('part_num'), 'bricklink': ids},
                          events=Events(self.db, base.AUDIT_ORIGIN.get(), base.AUDIT_ACTOR.get()))
            self.db.execute("DELETE FROM main.item_provider_status WHERE item_id=? AND provider='bricklink' AND reason='no_match'", (item_id,))
            return 'matched'
        placed = self.db.execute(f'''SELECT 1 FROM main.item_link WHERE item_id=? AND provider='bricklink' AND status IN ({','.join('?' * len(CONFIRMED))}) LIMIT 1''',
                                 (item_id, *CONFIRMED)).fetchone()
        if placed:
            return 'kept'                                              # a confirmed link is never downgraded by a refresh
        self.db.execute('''INSERT INTO main.item_provider_status(item_id, provider, status, reason, evidence_json, checked_at)
                           VALUES(?, 'bricklink', 'unmatched', 'no_match', ?, ?) ON CONFLICT(item_id, provider, reason)
                           DO UPDATE SET evidence_json=excluded.evidence_json, checked_at=excluded.checked_at''',
                        (item_id, json.dumps({'rebrickable': record.get('part_num'), 'bricklink': ids}, sort_keys=True), store_now()))
        return 'unmatched'
