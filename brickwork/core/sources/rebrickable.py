"""API v3 lookups and external-id evidence; canonical keys stay BrickLink."""
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request

from .base import Source, SourceError, KeyRejected, RemoteBudgetExceeded, now, write
from .images import download

BASE = 'https://rebrickable.com/api/v3/lego'


class Rebrickable(Source):
    label = 'Rebrickable'
    source = 'rebrickable'
    minimum_spacing = 1
    credentials = ('BW_REBRICKABLE_API_KEY',)
    freshness = {'part': 30, 'color': 90, 'minifigure': 30, 'image': 30}

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        budget = os.environ.get('BW_REBRICKABLE_DAILY_BUDGET', '1000')
        if not re.fullmatch('[0-9]+', budget) or int(budget) <= 0:
            raise SourceError('BW_REBRICKABLE_DAILY_BUDGET must be a positive integer')
        self.daily_budget = int(budget)

    def call(self, path, params=None, *, normalize=None, job_id=None):
        if not re.fullmatch(r'/(?:parts|colors|minifigs|sets)/(?:[A-Za-z0-9-]+/(?:colors/[0-9]+/)?)?', path):
            raise ValueError('unsupported Rebrickable endpoint')
        self.ready()
        def consume(reply):
            if not isinstance(reply, dict):
                raise SourceError('Rebrickable returned an invalid reply')
            if 'detail' in reply:
                if 'throttled' in str(reply['detail']).lower():
                    match = re.search(r'available in ([0-9]+) seconds?', str(reply['detail']), re.IGNORECASE)
                    delay = max(1, min(86400, int(match[1]))) if match else 60
                    raise RemoteBudgetExceeded(retry_seconds=delay)
                if re.search(r'invalid token|authentication credentials', str(reply['detail']), re.IGNORECASE):
                    raise KeyRejected('Rebrickable API unsuccessful')
                raise SourceError('Rebrickable API unsuccessful')
            return normalize(reply) if normalize else reply
        params = params or {}
        request = Request(BASE + path + ('?' + urlencode(params) if params else ''),
                          headers={'Authorization': 'key ' + self.credential_values()[0]})
        return self.request(path, params, request, consume, job_id=job_id)

    def check_key(self):
        return self.call('/colors/0/', normalize=lambda row: True)

    def match(self, kind, row, *, canonical=None):
        identifiers = row.get('external_ids', {}).get('BrickLink', [])
        if isinstance(identifiers, dict):
            identifiers = identifiers.get('ext_ids', [])
        identifiers = list(dict.fromkeys(str(value) for value in identifiers))
        source_id = str(row['id'] if kind == 'color' else row['part_num'] if kind == 'part' else row['set_num'])
        item_type = {'part': 'P', 'minifigure': 'M', 'set': 'S'}.get(kind)
        valid = canonical is not None and str(canonical) in identifiers and len(identifiers) == 1
        if valid:
            if kind == 'color':
                write(self.db, 'INSERT OR IGNORE INTO colors(color_id) VALUES(?)', (int(canonical),))
            elif not self.db.execute('SELECT 1 FROM items WHERE item_type=? AND item_no=?', (item_type, canonical)).fetchone():
                valid = False
        # A source refresh never replaces a user's decision.
        existing = self.db.execute('SELECT status,item_type,item_no,color_id FROM id_match WHERE source=? AND kind=? AND source_id=?',
                                   (self.source, kind, source_id)).fetchone()
        if existing and existing['status'] in ('manual', 'matched', 'inferred'):
            return dict(existing)
        write(self.db, '''INSERT INTO id_match(source,kind,source_id,item_type,item_no,color_id,method,status,evidence_json,decided_at)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,kind,source_id) DO UPDATE SET
            item_type=excluded.item_type,item_no=excluded.item_no,color_id=excluded.color_id,
            method=excluded.method,status=excluded.status,evidence_json=excluded.evidence_json,decided_at=excluded.decided_at''',
              (self.source, kind, source_id, item_type if valid else None,
               str(canonical) if valid and item_type else None, int(canonical) if valid and kind == 'color' else None,
               'external_ids', 'matched' if valid else 'unmatched', json.dumps(row), now().isoformat()))
        return dict(source_id=source_id, status='matched' if valid else 'unmatched')

    @staticmethod
    def identifier(number):
        if not isinstance(number, str) or not re.fullmatch('[A-Za-z0-9-]{1,64}', number):
            raise ValueError('invalid Rebrickable identifier')
        return number

    def part(self, number, *, canonical=None, job_id=None):
        self.identifier(number)
        def consume(row):
            if row['part_num'] != number:
                raise ValueError('part mismatch')
            self.match('part', row, canonical=canonical)
            return row
        return self.call(f'/parts/{number}/', normalize=consume, job_id=job_id)

    def color(self, color_id, *, canonical=None, job_id=None):
        if type(color_id) is not int or color_id < 0:
            raise ValueError('invalid Rebrickable colour')
        def consume(row):
            if row['id'] != color_id:
                raise ValueError('color mismatch')
            self.match('color', row, canonical=canonical)
            return row
        return self.call(f'/colors/{color_id}/', normalize=consume, job_id=job_id)

    def minifigure(self, number, *, canonical=None, job_id=None):
        self.identifier(number)
        def consume(row):
            if row['set_num'] != number:
                raise ValueError('minifigure mismatch')
            self.match('minifigure', row, canonical=canonical)
            return row
        return self.call(f'/minifigs/{number}/', normalize=consume, job_id=job_id)

    def find_part(self, canonical, *, job_id=None):
        self.identifier(canonical)
        def consume(reply):
            from ..pipeline import cooperative
            rows = reply['results']
            if reply.get('next') or reply.get('count', len(rows)) != len(rows):
                raise SourceError('ambiguous Rebrickable part results')
            for row in cooperative(self.db, rows):
                self.match('part', row, canonical=canonical if len(rows) == 1 else None)
            return rows
        rows = self.call('/parts/', {'bricklink_id': canonical, 'inc_part_details': 1}, normalize=consume, job_id=job_id)
        matches = [row for row in rows if str(canonical) in row.get('external_ids', {}).get('BrickLink', [])]
        if len(matches) != 1 or len(rows) != 1:
            raise SourceError('Rebrickable part needs manual matching')
        return matches[0]

    def part_image(self, number, color_id, *, job_id=None):
        self.identifier(number)
        if type(color_id) is not int or color_id < 0:
            raise ValueError('invalid Rebrickable colour')
        def consume(row):
            url = row.get('part_img_url')
            if not url:
                raise SourceError('Rebrickable has no part render')
            return url
        return self.call(f'/parts/{number}/colors/{color_id}/', normalize=consume, job_id=job_id)

    def download_part_image(self, number, color_id, canonical, canonical_color, root, *, http=None):
        url = self.part_image(number, color_id)
        return download(self.db, root, self.source, 'P', canonical, url,
                        color=canonical_color, image_kind='render', http=http)
