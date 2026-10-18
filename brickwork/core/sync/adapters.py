"""Remote collection adapters for Rebrickable and Brickset (#10): owned sets and wanted sets only.

Every call goes through the source's budgeted, recorded transport, except the one-time connect,
which must not store anything it sends or receives. Job payloads and errors never carry the user
token, the userHash or a password: paths are recorded as templates.
"""
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote
from urllib.request import Request

from .. import errors, keys, secrets
from ..sources.base import KeyRejected, SourceError, WaitingForBudget, now, transport, USER_AGENT
from ..sources.brickset import Brickset, BASE as BRICKSET
from ..sources.rebrickable import Rebrickable

REBRICKABLE_USERS = 'https://rebrickable.com/api/v3/users'
NUMBER = re.compile(r'[A-Za-z0-9][A-Za-z0-9.-]{0,63}')
# Local ceilings for calls the sites do not count against the key.
LOGIN_PER_DAY = 10
BRICKSET_WRITES_PER_DAY = 500


class ConnectRefused(errors.ValidationFailed):
    """The site refused the username or password. The message never names either."""


def _day_counter(db, key, limit):
    """Count one uncharged call per UTC day; refuse past `limit` until midnight."""
    day = now().date().isoformat()
    setting = f'{key}:{day}'
    with db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM settings WHERE key=?', (setting,)).fetchone()
        used = int(row[0]) if row else 0
        if used >= limit:
            midnight = now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            raise WaitingForBudget(None, midnight.isoformat())
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (setting, str(used + 1)))


def _number(value):
    value = str(value)
    if not NUMBER.fullmatch(value):
        raise SourceError('unexpected set number in the reply')
    return value


class RebrickableUser(Rebrickable):
    """User endpoints under /api/v3/users/ (set lists and their sets)."""
    TEMPLATES = re.compile(r'/(?:setlists/|setlists/[0-9]+/sets/|setlists/[0-9]+/sets/[A-Za-z0-9.-]+/|sets/)')

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        self.token = None
        send = self.http
        # DELETE answers 204 with an empty body; the recorded transport expects JSON.
        self.http = lambda request: send(request) or '{}'

    def user_token(self):
        if self.token is None:
            self.token = keys.credentials(self.db, 'rebrickable_user', keys.USER_ENV['rebrickable_user'],
                                          label='Rebrickable user token')[0]
        return self.token

    def user_call(self, path, params=None, *, method='GET', data=None):
        if not self.TEMPLATES.fullmatch(path):
            raise ValueError('unsupported Rebrickable user endpoint')
        self.ready()
        token = self.user_token()
        params = params or {}
        url = f'{REBRICKABLE_USERS}/{quote(token, safe="")}{path}' + ('?' + urlencode(params) if params else '')
        body = urlencode(data).encode() if data is not None else None
        request = Request(url, data=body, method=method, headers={'Authorization': 'key ' + self.credential_values()[0],
                                                                  'Accept': 'application/json'})
        if body is not None:
            request.add_header('Content-Type', 'application/x-www-form-urlencoded')

        def consume(reply):
            if method == 'DELETE' and reply == {}:
                return True
            if isinstance(reply, dict) and 'detail' in reply and len(reply) == 1:
                detail = str(reply['detail'])
                if 'throttled' in detail.lower():
                    from ..sources.base import RemoteBudgetExceeded
                    match = re.search(r'available in ([0-9]+) seconds?', detail, re.IGNORECASE)
                    raise RemoteBudgetExceeded(retry_seconds=max(1, min(86400, int(match[1]))) if match else 60)
                if re.search(r'invalid token|authentication credentials|invalid user token', detail, re.IGNORECASE):
                    raise KeyRejected('Rebrickable refused the user token or key')
                raise SourceError('Rebrickable API unsuccessful')
            return reply
        # The recorded job payload names the path template only, never the token.
        return self.request('user:' + method.lower() + ':' + re.sub(r'[0-9]+', 'N', path),
                            dict(params, **({'form': {k: v for k, v in data.items()}} if data else {})),
                            request, consume)

    def pages(self, path):
        rows, page = [], 1
        while True:
            reply = self.user_call(path, {'page': page, 'page_size': 1000})
            if not isinstance(reply, dict) or not isinstance(reply.get('results'), list):
                raise SourceError('Rebrickable returned an invalid reply')
            rows.extend(reply['results'])
            if not reply.get('next'):
                return rows
            page += 1
            if page > 200:
                raise SourceError('Rebrickable list is too long')

    # The adapter surface used by the sync service.
    def connect(self, username, password):
        """Exchange username and password for a user token. Nothing is recorded."""
        self.ready()
        _day_counter(self.db, 'sync:rebrickable:logins', LOGIN_PER_DAY)
        request = Request(REBRICKABLE_USERS + '/_token/', method='POST',
                          data=urlencode({'username': username, 'password': password}).encode(),
                          headers={'Authorization': 'key ' + self.credential_values()[0], 'User-Agent': USER_AGENT,
                                   'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        try:
            raw = self.http(request)
            reply = raw if isinstance(raw, dict) else json.loads(raw)
        except Exception:
            raise SourceError('Rebrickable could not be reached') from None
        token = reply.get('user_token') if isinstance(reply, dict) else None
        if isinstance(token, str) and token:
            secrets.remember(token)
            return token
        status = getattr(raw, 'status', None)
        detail = str(reply.get('detail', '')) if isinstance(reply, dict) else ''
        if status in (401, 403) and re.search(r'invalid (?:api )?key|invalid token|api key', detail, re.IGNORECASE):
            raise KeyRejected('Rebrickable refused the API key')
        raise ConnectRefused('Rebrickable did not accept that username and password')

    def check_user(self):
        self.user_call('/setlists/', {'page': 1, 'page_size': 1})
        return True

    def lists(self):
        return [dict(id=int(r['id']), name=r.get('name') or '', sets=r.get('num_sets'))
                for r in self.pages('/setlists/')]

    def fetch(self, link):
        """Remote counts: owned = the linked owned lists (all but the wishlist list when unset)."""
        lists = self.lists()
        wish = link.get('wishlist')
        owned_ids = link.get('owned') or [r['id'] for r in lists if r['id'] != wish]
        known = {r['id'] for r in lists}
        missing = [i for i in owned_ids + ([wish] if wish else []) if i not in known]
        if missing:
            raise errors.ValidationFailed('A linked Rebrickable set list no longer exists · link again')
        owned, wanted, per_list = {}, {}, {}
        for list_id in owned_ids + ([wish] if wish else []):
            for row in self.pages(f'/setlists/{list_id}/sets/'):
                number = _number(row['set']['set_num'])
                quantity = int(row.get('quantity') or 0)
                target = wanted if list_id == wish else owned
                target[number] = target.get(number, 0) + quantity
                per_list.setdefault(str(list_id), {})[number] = quantity
        return dict(owned=owned, wanted=wanted, per_list=per_list, owned_lists=owned_ids, names={})

    def send(self, row, link, state):
        """Set the count of one set on the target list: POST (new), PUT (count) or DELETE (0)."""
        list_id = link.get('wishlist') if row['kind'] == 'wanted' else link.get('send_to') or state.get('send_to')
        if not list_id:
            raise errors.ValidationFailed('Choose the Rebrickable set list to send to')
        current = state['per_list'].get(str(list_id), {}).get(row['remote_no'], 0)
        others = (row['remote'] or 0) - current
        target = row['send'] - others
        if target < 0:
            raise errors.ValidationFailed('Other linked lists hold more · change them on Rebrickable')
        number = row['remote_no']
        if target == current:
            return 'unchanged'
        if target == 0:
            self.user_call(f'/setlists/{list_id}/sets/{number}/', method='DELETE')
        elif current == 0:
            self.user_call(f'/setlists/{list_id}/sets/', method='POST',
                           data={'set_num': number, 'quantity': target, 'include_spares': 'true'})
        else:
            self.user_call(f'/setlists/{list_id}/sets/{number}/', method='PUT',
                           data={'quantity': target, 'include_spares': 'true'})
        state['per_list'].setdefault(str(list_id), {})[number] = target
        return 'sent'


class BricksetUser(Brickset):
    """Brickset collection methods: login, checkUserHash, getSets (owned/wanted), setCollection."""
    USER_METHODS = ('login', 'checkUserHash', 'getSets', 'setCollection')

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        self.hash = None

    def user_hash(self):
        if self.hash is None:
            self.hash = keys.credentials(self.db, 'brickset_user', keys.USER_ENV['brickset_user'],
                                         label='Brickset user hash')[0]
        return self.hash

    def user_call(self, method, body_extra, *, payload, charged):
        if method not in self.USER_METHODS:
            raise ValueError('unsupported Brickset endpoint')
        self.ready()
        body = dict(apiKey=self.credential_values()[0], userHash=self.user_hash(), **body_extra)

        def consume(reply):
            if reply.get('status') != 'success':
                message = str(reply.get('message', ''))
                if message == 'API limit exceeded':
                    from ..sources.base import RemoteBudgetExceeded
                    raise RemoteBudgetExceeded()
                if re.search(r'invalid.*(?:key|hash)|(?:key|hash).*invalid|user hash', message, re.IGNORECASE):
                    raise KeyRejected('Brickset refused the key or user hash')
                raise SourceError('Brickset API unsuccessful')
            return reply
        request = Request(BRICKSET + '/' + method, data=urlencode(body).encode(),
                          headers={'Content-Type': 'application/x-www-form-urlencoded'})
        return self.request('user:' + method, payload, request, consume, charged=charged)

    def connect(self, username, password):
        self.ready()
        _day_counter(self.db, 'sync:brickset:logins', LOGIN_PER_DAY)
        request = Request(BRICKSET + '/login', data=urlencode(dict(
            apiKey=self.credential_values()[0], username=username, password=password)).encode(),
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': USER_AGENT})
        try:
            raw = self.http(request)
            reply = raw if isinstance(raw, dict) else json.loads(raw)
        except Exception:
            raise SourceError('Brickset could not be reached') from None
        if isinstance(reply, dict) and reply.get('status') == 'success' and isinstance(reply.get('hash'), str) and reply['hash']:
            secrets.remember(reply['hash'])
            return reply['hash']
        message = str(reply.get('message', '')) if isinstance(reply, dict) else ''
        if re.search(r'invalid api key|api key', message, re.IGNORECASE):
            raise KeyRejected('Brickset refused the API key')
        raise ConnectRefused('Brickset did not accept that username and password')

    def check_user(self):
        self.user_call('checkUserHash', {}, payload={}, charged=False)
        return True

    def lists(self):
        return []

    def _sets(self, filters):
        rows, page = [], 1
        while True:
            params = dict(filters, pageSize=500, pageNumber=page)
            reply = self.user_call('getSets', {'params': json.dumps(params)}, payload=params, charged=True)
            batch = reply.get('sets') or []
            rows.extend(batch)
            if len(rows) >= int(reply.get('matches') or 0) or not batch:
                return rows
            page += 1
            if page > 100:
                raise SourceError('Brickset collection is too long')

    def fetch(self, link):
        owned, wanted, ids = {}, {}, {}
        for row in self._sets({'owned': 1}):
            number = _number(f"{row['number']}-{row['numberVariant']}")
            owned[number] = int((row.get('collection') or {}).get('qtyOwned') or 1)
            ids[number] = int(row['setID'])
        for row in self._sets({'wanted': 1}):
            number = _number(f"{row['number']}-{row['numberVariant']}")
            wanted[number] = 1
            ids[number] = int(row['setID'])
        return dict(owned=owned, wanted=wanted, ids=ids, names={})

    def set_ids(self, numbers):
        """Brickset setIDs for set numbers, one charged getSets per 500 numbers."""
        found = {}
        numbers = sorted(set(numbers))
        for offset in range(0, len(numbers), 500):
            batch = numbers[offset:offset + 500]
            params = dict(setNumber=','.join(batch), pageSize=500)
            reply = self.user_call('getSets', {'params': json.dumps(params)}, payload=params, charged=True)
            for row in reply.get('sets') or []:
                found[_number(f"{row['number']}-{row['numberVariant']}")] = int(row['setID'])
        return found

    def send(self, row, link, state):
        set_id = state['ids'].get(row['remote_no'])
        if set_id is None:
            raise errors.ValidationFailed('Brickset does not know this set number')
        _day_counter(self.db, 'sync:brickset:writes', BRICKSET_WRITES_PER_DAY)
        if row['kind'] == 'wanted':
            params = {'want': 1 if row['send'] else 0}
        else:
            params = {'own': 1, 'qtyOwned': row['send']} if row['send'] else {'own': 0}
        self.user_call('setCollection', {'SetID': set_id, 'params': json.dumps(params)},
                       payload=dict(SetID=set_id, **params), charged=False)
        return 'sent'


ADAPTERS = {'rebrickable': RebrickableUser, 'brickset': BricksetUser}


def adapter(db, source, http=None):
    if source not in ADAPTERS:
        raise errors.NotFound('Unknown sync source')
    return ADAPTERS[source](db, http=http or transport)
