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
from ..sources.base import KeyRejected, RemoteBudgetExceeded, SourceError, WaitingForBudget, now, transport, USER_AGENT
from ..sources.brickset import Brickset, BASE as BRICKSET
from ..sources.rebrickable import Rebrickable
from .brickowl_run import BrickOwlUser

REBRICKABLE_USERS = 'https://rebrickable.com/api/v3/users'
NUMBER = re.compile(r'[A-Za-z0-9][A-Za-z0-9.-]{0,63}')
# Local ceilings for calls the sites do not count against the key.
LOGIN_PER_DAY = 10


class ConnectRefused(errors.ValidationFailed):
    """The site refused the username or password. The message never names either."""


def _day_counter(db, source, field, limit):
    """Count one uncharged call per UTC day; refuse past `limit` until midnight.

    The count is the day's `sync` events of that kind for the source (design 5.2 has no table for it, and `setting` holds preferences only):
    each attempt writes one, which carries no credential."""
    from ..admin import audit
    from ..transaction import transaction
    day = now().date().isoformat()
    with transaction(db):
        used = db.execute("SELECT count(*) FROM main.event WHERE entity_kind='sync' AND entity_id=? AND field=? AND at>=?", (source, field, day)).fetchone()[0]
        if used >= limit:
            midnight = now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            raise WaitingForBudget(None, midnight.isoformat())
        audit(db, 'sync:' + source, field, None, None)


def _number(value):
    value = str(value)
    if not NUMBER.fullmatch(value):
        raise SourceError('unexpected set number in the reply')
    return value


def _optional_id(value):
    if value is None:
        return None
    if type(value) is str and value.isdecimal():
        value = int(value)
    return value if type(value) is int and value >= 1 else None


def parse_lost_part(row):
    """One row of `GET /users/{token}/lost_parts/` as `dict(set_no, part_no, color_id, quantity, is_spare, lost_part_id, inv_part_id)`, or None when it cannot be read.

    ASSUMED SHAPE (Rebrickable's documentation; the OpenAPI file does not describe the items and the test instance has no user token, so it
    was not checked live): `{lost_part_id, lost_quantity, inv_part: {id, inv_part_id, part: {part_num, ...}, color: {id, ...}, set_num,
    quantity, is_spare, element_id}}`. The set number is read from `inv_part.set_num`, else `set_num` or
    `set.set_num` on the row itself. If Rebrickable's reply differs, fix this one function; a row it returns None for is
    counted by the caller and reported as "could not be read", and a run with such a row clears nothing."""
    try:
        inv = row['inv_part']
        quantity = row['lost_quantity']
        part_no = str(inv['part']['part_num'])
        color_id = inv['color']['id']
        spare = inv.get('is_spare', False)
        found = inv.get('set_num') or row.get('set_num') or (row.get('set') or {}).get('set_num')
        if found is None:
            return None
        if type(quantity) is str and quantity.isdecimal():
            quantity = int(quantity)
        if type(color_id) is str and color_id.lstrip('-').isdecimal():
            color_id = int(color_id)
        if type(quantity) is not int or quantity < 1 or type(color_id) is not int or not isinstance(spare, bool):
            return None
        return dict(set_no=_number(found), part_no=_number(part_no), color_id=color_id, quantity=quantity, is_spare=spare,
                    lost_part_id=_optional_id(row.get('lost_part_id')),
                    inv_part_id=_optional_id(inv.get('inv_part_id')))
    except (KeyError, TypeError, AttributeError, SourceError):
        return None


def parse_part_list_row(row):
    """One row of `GET /users/{token}/partlists/{id}/parts/` as `dict(part_no, color_id, quantity)`, or None when it cannot be read (#471).

    ASSUMED SHAPE (Rebrickable's documentation, not checked live): `{quantity, part: {part_num, ...}, color: {id, ...}, element_id}`."""
    try:
        quantity, colour, part_no = row['quantity'], row['color']['id'], row['part']['part_num']
        if type(part_no) is int:
            part_no = str(part_no)
        if type(quantity) is str and quantity.isdecimal():
            quantity = int(quantity)
        if type(colour) is str and re.fullmatch(r'-?\d+', colour):
            colour = int(colour)
        if type(quantity) is not int or quantity < 1 or type(colour) is not int or not isinstance(part_no, str) or not part_no:
            return None
        return dict(part_no=_number(part_no), color_id=colour, quantity=quantity)
    except (KeyError, TypeError, AttributeError, ValueError, SourceError):
        return None


class RebrickableUser(Rebrickable):
    """User endpoints under /api/v3/users/ (set lists and their sets)."""
    TEMPLATES = re.compile(r'/(?:setlists/|setlists/[0-9]+/sets/|setlists/[0-9]+/sets/[A-Za-z0-9.-]+/|sets/|lost_parts/|lost_parts/[0-9]+/|partlists/|partlists/[0-9]+/parts/)')

    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        self.token = None
        send = self.http
        # DELETE answers 204 with an empty body; the recorded transport expects JSON.
        def wrapped(request):
            reply = send(request)
            return '{}' if reply in ('', b'', None) else reply
        self.http = wrapped

    def user_token(self):
        if self.token is None:
            self.token = keys.credentials(self.db, 'rebrickable_user', keys.USER_ENV['rebrickable_user'],
                                          label='Rebrickable user token')[0]
        return self.token

    def user_call(self, path, params=None, *, method='GET', data=None):
        if not self.TEMPLATES.fullmatch(path) or (method != 'DELETE' and re.fullmatch(r'/lost_parts/[0-9]+/', path)):
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
                            json.dumps(dict(params, **({'form': {k: v for k, v in data.items()}} if data else {})), sort_keys=True),
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

    def lost_parts(self):
        """The user's Lost Parts: `dict(rows, unreadable)`. `rows` are `parse_lost_part` results, one per set, part, colour and spare flag (a
        repeated one is summed); `unreadable` counts the rows it could not read. Read with `pages`, so every call is budgeted and recorded."""
        merged, unreadable = {}, 0
        for raw in self.pages('/lost_parts/'):
            row = parse_lost_part(raw) if isinstance(raw, dict) else None
            if row is None:
                unreadable += 1
                continue
            key = (row['set_no'], row['part_no'], row['color_id'], row['is_spare'])
            if key in merged:
                merged[key]['quantity'] += row['quantity']
                if row['lost_part_id'] is not None:
                    merged[key]['ids'].append(row['lost_part_id'])
                else:
                    merged[key]['ids_complete'] = False
                if merged[key]['inv_part_id'] is None and row['inv_part_id'] is not None:
                    merged[key]['inv_part_id'] = row['inv_part_id']
            else:
                has_id = row['lost_part_id'] is not None
                row['ids'] = [row['lost_part_id']] if has_id else []
                row['ids_complete'] = has_id
                merged[key] = row
        return dict(rows=list(merged.values()), unreadable=unreadable)

    def lost_part_add(self, inv_part_id, quantity):
        """Add one Lost Parts row on Rebrickable.

        ASSUMED SHAPE (Rebrickable's documentation; not checked live because the test instance has no user token):
        `POST /users/{token}/lost_parts/` with form fields `inv_part_id` and `lost_quantity`.
        After a 2xx the write is done, so only an error body fails; `lost_part_id` in the reply is optional."""
        reply = self.user_call('/lost_parts/', method='POST',
                               data={'inv_part_id': int(inv_part_id), 'lost_quantity': int(quantity)})
        if isinstance(reply, dict) and (
            'detail' in reply
            or 'non_field_errors' in reply
            or any(k in reply and not (type(reply[k]) is int and reply[k] >= 1) for k in ('inv_part_id', 'lost_quantity'))
        ):
            raise SourceError('Rebrickable refused the Lost Part')
        return reply

    def lost_part_remove(self, lost_part_id):
        """Remove one Lost Parts row on Rebrickable.

        ASSUMED SHAPE (Rebrickable's documentation; not checked live because the test instance has no user token):
        `DELETE /users/{token}/lost_parts/{id}/`. An empty reply is treated as success because 204 has no body, so it cannot be told from
        an empty-bodied error; live behaviour of POST and DELETE must be tried with a real user token before sending is offered."""
        reply = self.user_call(f'/lost_parts/{int(lost_part_id)}/', method='DELETE')
        if reply is not True:
            raise SourceError('Rebrickable refused the Lost Part removal')
        return True

    # The adapter surface used by the sync service.
    def connect(self, username, password):
        """Exchange username and password for a user token. Nothing is recorded."""
        self.ready()
        _day_counter(self.db, 'rebrickable', 'login', LOGIN_PER_DAY)
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

    def part_lists(self):
        """The user's part lists (#471): `[{id, name, parts}]`."""
        return [dict(id=int(r['id']), name=r.get('name') or '', parts=r.get('num_parts')) for r in self.pages('/partlists/')]

    def part_list_parts(self, list_id):
        """The rows of one part list, each `parse_part_list_row` (None for a row that cannot be read)."""
        return [parse_part_list_row(r) if isinstance(r, dict) else None for r in self.pages(f'/partlists/{int(list_id)}/parts/')]

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
        names = {str(r['id']): r['name'] for r in lists if r['id'] in owned_ids or r['id'] == wish}   # #531: each linked list's name as read now
        all_list_ids = [str(r['id']) for r in lists]
        return dict(owned=owned, wanted=wanted, per_list=per_list, owned_lists=owned_ids, names=names, all_list_ids=all_list_ids)

    def send(self, row, link, state):
        """Set the count of one set on the target list: POST (new), PUT (count) or DELETE (0)."""
        list_id = link.get('wishlist') if row['kind'] == 'wanted' else link.get('send_to') or state.get('send_to')
        if not list_id:
            raise errors.ValidationFailed('Link a Rebrickable wishlist to send wishes to' if row['kind'] == 'wanted' else
                                          'Choose the Rebrickable set list to send to')
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


def _flag_number(value):
    """A Brickset flag number (1 to 8) from whatever a reply holds, else None: never an exception, however odd the value."""
    text = str(value).strip()
    return int(text) if text.isdecimal() and len(text) <= 2 and 1 <= int(text) <= 8 else None


def _whole(value, low, high):
    """A whole number from low to high out of whatever a reply holds, else None (0 for \"none\" is below `low`, so it reads as None): never an exception."""
    text = str(value).strip()
    return int(text) if text.isdecimal() and len(text) <= 4 and low <= int(text) <= high else None


class BricksetUser(Brickset):
    """Brickset collection methods: login, checkUserHash, getSets (owned/wanted), setCollection."""
    USER_METHODS = ('login', 'checkUserHash', 'getSets', 'setCollection', 'getUserFlagLabels')

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
        return self.request('user:' + method, json.dumps(payload, sort_keys=True), request, consume, charged=charged)

    def connect(self, username, password):
        self.ready()
        _day_counter(self.db, 'brickset', 'login', LOGIN_PER_DAY)
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
        self.user_call('checkUserHash', {}, payload={}, charged=True)
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
        """The owned and wanted sets with their counts, and `fields`: what else Brickset keeps per set (notes, the flags that are on), read from
        the same two calls, so it costs nothing extra."""
        owned, wanted, ids, fields = {}, {}, {}, {}

        def note(number, collection, wanted=False):
            # `flags` is a list of {flagNo, value} (documented, and an empty list on the live account checked 24.11.); anything else reads as no flags
            listed = collection.get('flags')
            on = [_flag_number(f.get('flagNo')) for f in (listed if isinstance(listed, list) else ())
                  if isinstance(f, dict) and str(f.get('value')).lower() in ('true', '1') and _flag_number(f.get('flagNo'))]
            # `rating` (0 = none) and `wantedPriority` (1 = Brickset's default) are ints in `collection`, checked live 24.11.; Brickset keeps a
            # wantedPriority on every set, so it counts only for a set that is wanted
            entry = fields.setdefault(number, dict(notes=str(collection.get('notes') or ''), flags=sorted(on),
                                                   rating=_whole(collection.get('rating'), 1, 5), priority=None))
            if wanted:
                entry['priority'] = _whole(collection.get('wantedPriority'), 1, 999)
        for row in self._sets({'owned': 1}):
            number = _number(f"{row['number']}-{row['numberVariant']}")
            collection = row.get('collection') or {}
            owned[number] = int(collection.get('qtyOwned') or 1)
            ids[number] = int(row['setID'])
            note(number, collection)
        for row in self._sets({'wanted': 1}):
            number = _number(f"{row['number']}-{row['numberVariant']}")
            collection = row.get('collection') or {}
            wanted[number] = int(collection.get('qtyWanted') or 1)
            ids[number] = int(row['setID'])
            note(number, collection, wanted=True)
        return dict(owned=owned, wanted=wanted, ids=ids, names={}, fields=fields)

    def flag_labels(self):
        """The names the person gave the eight flags at Brickset, `{flag number: label}`; a flag without a name is missing. One charged call."""
        reply = self.user_call('getUserFlagLabels', {}, payload={}, charged=True)
        listed = reply.get('flags')
        return {_flag_number(f.get('flagNo')): str(f['label']).strip() for f in (listed if isinstance(listed, list) else ())
                if isinstance(f, dict) and f.get('label') and str(f['label']).strip() and _flag_number(f.get('flagNo'))}

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

    def send_set(self, rows, link, state):
        """Write all rows of one set (owned and wanted) in a single setCollection call."""
        set_id = state['ids'].get(rows[0]['remote_no'])
        if set_id is None:
            raise errors.ValidationFailed('Brickset does not know this set number')
        params = {}
        for row in rows:
            n = row['send']
            if row['kind'] == 'wanted':
                params.update({'qtyWanted': n} if n > 0 else {'want': 0})
            else:
                params.update({'own': 1, 'qtyOwned': n} if n > 0 else {'own': 0})
        self.user_call('setCollection', {'SetID': set_id, 'params': json.dumps(params)},
                       payload=dict(SetID=set_id, **params), charged=True)
        return 'sent'

    def send(self, row, link, state):
        return self.send_set([row], link, state)


ADAPTERS = {'rebrickable': RebrickableUser, 'brickset': BricksetUser, 'brickowl': BrickOwlUser}


def adapter(db, source, http=None):
    if source not in ADAPTERS:
        raise errors.NotFound('Unknown sync source')
    return ADAPTERS[source](db, http=http or transport)
