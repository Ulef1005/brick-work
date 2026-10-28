"""The write transport of API v2 (M.11c, issue #113): what every write operation shares, on the 4.0 `event` log.

A write view is `@route(rule, method)` over `@write` over `function(db, body, **path)`: this module reads the request against the generated
write contract (`write_contract.json`, made from `openapi-v2.yaml` by `scripts/generate_api_writes.py`), checks the Idempotency-Key, runs the
function inside one transaction that also records the answer, and builds the envelope `{data, event_id, undo_url, idempotent_replay}`.

* **Nothing new is written here.** A function calls the core writer that owns the change (`collection.save`, `add.confirm`, `ledger.*`,
  `workbench.*`, `identity_admin.*`, `store4.copies.switch_part_list`, ...); each writes its own event, with the token's name as the actor
  (`transport.audited`). The function returns `Done(data)`; the event the envelope names is the last undoable event the call wrote (or the
  one it names), and `undo_url` is its Undo when a registered undoer takes it.
* **One operation.** Every event of a request shares an `api2:` operation key. Undoing the event a write names undoes the write whole: the
  undoable events of the same operation up to it, newest first (`undo_operation`), in the one transaction of the Undo.
* **Idempotency** (as v1, on the 4.0 log): the answer is stored as a `bw_api` event `op:<key>` in the transaction of the write, so a lost response
  can be asked for again for 30 days; the same key with another body, path or query is `409 idempotency_conflict`, and another token's key is another key.
* **Errors.** A `ValueError` is `422`, the contract's other failures are `core.errors`; a refusal of the 4.0 store (`Store4Error`) is mapped by
  `store4_problem`, so it never turns into a `500`."""
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import json
from pathlib import Path
import re
import uuid

from flask import current_app, g, jsonify, request

from ..api import transport
from ..core import admin, errors, undo as undoing
from ..core.transaction import transaction
from ..store4 import copies as copies_store, errors as store_errors, lookup, pending as pending_store
from . import database
from .items import for_write
from .read import clean, etag as etag_of
from ..core.secrets import fingerprint, secret_values

CONTRACT = json.loads(Path(__file__).with_name('write_contract.json').read_text())
SPEC = {o['endpoint']: o for o in CONTRACT['operations']}
SCHEMAS = CONTRACT['schemas']
KEY = re.compile(r'[A-Za-z0-9-]{1,80}')
UPLOAD_LIMITS = {'photos': 15, 'instruction': 20, 'identification': 8}   # megabytes, by the operation's name
CLAIM_SECONDS = 900                                                 # the claim of a network call that crashed expires after this
SHOWN_ONCE = {'post_tokens': ('data', 'secret')}                  # members of an answer that are never kept in the replay record: the replay shows them as null
KEYED = ('put_sources_by_source_key', 'put_sources_by_source_user', 'post_sources_by_source_user_connect')   # bodies that hold key material or a password
FINGERPRINT = 1                                                     # the version of the idempotency fingerprint; a change to what it hashes bumps it
PREFIX = 'api2:'                                                    # the operation key of every v2 write


# ---------- the request against the contract ----------

def kind_of(value):
    return ('null' if value is None else 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'number' if type(value) is float
            else 'object' if isinstance(value, dict) else 'array' if isinstance(value, list) else 'string' if isinstance(value, str) else '')


def invalid(path, message):
    raise errors.ValidationFailed((path + ': ' if path else '') + message)


def validate(value, schema, path='', loose=False):
    """Fail with `422` unless `value` is what the schema says. Understands what the write contract uses: `$ref`, `allOf`, `oneOf`, `if`/`then`, `const`, `propertyNames`,
    `type` (a list too), `enum`, `pattern`, `minimum`, `minItems`/`maxItems`/`minProperties`, `items`, `properties` with `required` (an object that
    lists properties is closed: an unknown member is refused), and `additionalProperties` as a schema."""
    if '$ref' in schema:
        return validate(value, SCHEMAS[schema['$ref'].rsplit('/', 1)[-1]], path, loose)
    for part in schema.get('allOf', ()):
        validate(value, part, path, loose)
    if 'oneOf' in schema:
        passed = 0
        for part in schema['oneOf']:
            try:
                validate(value, part, path)
                passed += 1
            except errors.ValidationFailed:
                pass
        if passed != 1:
            invalid(path, 'name the item by id, or by kind and key (not both)')
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    kind = kind_of(value)
    if types and not (kind in types or kind == 'integer' and 'number' in types):
        invalid(path, 'expected ' + ' or '.join(types))
    if 'enum' in schema and value not in schema['enum']:
        invalid(path, 'expected one of ' + ', '.join(str(e) for e in schema['enum']))
    if 'const' in schema and value != schema['const']:
        invalid(path, f"expected {schema['const']}")
    if 'if' in schema:                                              # a condition on the value: what `then` asks holds only where `if` does
        try:
            validate(value, schema['if'], path, loose=True)         # a condition looks at the members it names and leaves the others alone
            holds = True
        except errors.ValidationFailed:
            holds = False
        if holds and 'then' in schema:
            validate(value, schema['then'], path)
    if kind in ('integer', 'number') and value < schema.get('minimum', value):
        invalid(path, f"must be at least {schema['minimum']}")
    if kind == 'string' and 'pattern' in schema and not re.search(schema['pattern'], value):
        invalid(path, 'has an invalid format')
    if kind == 'array':
        if len(value) < schema.get('minItems', 0):
            invalid(path, f"needs at least {schema['minItems']} items")
        if len(value) > schema.get('maxItems', len(value)):
            invalid(path, f"takes at most {schema['maxItems']} items")
        for n, item in enumerate(value):
            validate(item, schema.get('items', {}), f'{path}[{n}]')
    if kind == 'object':
        if len(value) < schema.get('minProperties', 0):
            invalid(path, 'supply at least one field')
        pattern = schema.get('propertyNames', {}).get('pattern')
        if pattern is not None and any(not re.search(pattern, name) for name in value):
            invalid(path, 'has a member with an invalid name')
        fields = schema.get('properties')
        if fields is not None:
            unknown = sorted(set(value) - set(fields))
            if unknown and not loose:
                invalid(path, 'unknown field ' + ', '.join(unknown))
            for name, member in value.items():
                if name in fields:
                    validate(member, fields[name], f'{path}.{name}' if path else name)
        missing = [r for r in schema.get('required', ()) if r not in value]
        if missing:
            invalid(path, 'missing ' + ', '.join(missing))
        if fields is None and isinstance(schema.get('additionalProperties'), dict):
            for name, member in value.items():
                validate(member, schema['additionalProperties'], f'{path}.{name}' if path else name)
    return value


def read_body(spec):
    """`(body, content)`: the checked JSON object (or the form fields of an upload) and the uploaded bytes, else `(None, None)`."""
    if spec['multipart']:
        if request.mimetype != 'multipart/form-data':
            raise errors.UnsupportedMediaType()
        if spec['endpoint'] == 'post_imports_bricktracker':
            return upload_database(spec)
        kind = 'identification' if 'identifications' in spec['endpoint'] else 'photos' if 'photos' in spec['endpoint'] else 'instruction'
        limit = UPLOAD_LIMITS[kind] * 1024 * 1024
        file = request.files.get('file')
        if file is None:
            raise errors.ValidationFailed('Choose a PDF' if kind == 'instruction' else 'Choose a photo')
        if kind != 'instruction' and not (file.mimetype or '').startswith('image/'):
            raise errors.UnsupportedMediaType()
        content = file.read(limit + 1)
        if len(content) > limit:
            raise errors.PayloadTooLarge()
        form = request.form.to_dict()
        if 'item' in form:                                          # a form field cannot nest: the item key is JSON text in it
            try:
                form['item'] = json.loads(form['item'])
            except ValueError:
                raise errors.ValidationFailed('item is a JSON object, such as {"id": 15011}') from None
        validate(dict(form, file='upload'), spec['schema'])
        return form, content
    if spec['schema']:
        if not request.get_data() and not spec['schema'].get('required') and not spec['schema'].get('minProperties'):
            return {}, None                                         # a body whose members are all optional may be left out
        if request.mimetype != 'application/json':
            raise errors.UnsupportedMediaType()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise errors.BadRequest('Expected a JSON object')
        if spec['endpoint'] == 'patch_settings' and set(body) - set(SCHEMAS['SettingsPatch']['properties']):
            raise errors.UnsupportedSetting('Unsupported setting: ' + ', '.join(sorted(set(body) - set(SCHEMAS['SettingsPatch']['properties']))))
        return validate(body, spec['schema']), None
    if request.get_data():
        raise errors.BadRequest('This action accepts no body')
    return {}, None


class Upload:
    """A BrickTracker database streamed to a private file, not held in memory: its path, the SHA-256 of its bytes and the name it came with.
    `discard` removes the file (the request is done with it, whatever happened)."""

    def __init__(self, path, sha256, name):
        self.path, self.sha256, self.name = path, sha256, name

    def discard(self):
        for suffix in ('', '-wal', '-shm', '-journal'):                 # the plan opens the file: SQLite may leave its sidecars
            self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)


def upload_database(spec):
    """One SQLite file from a multipart request, streamed to a private file under the import plans' folder, up to `BW_IMPORT_MAX_MB`."""
    import os
    from ..core.importer import bricktracker
    limit = int(os.environ.get('BW_IMPORT_MAX_MB', '200')) * 1024 * 1024
    file = request.files.get('file')
    if file is None or set(request.files) != {'file'}:
        raise errors.ValidationFailed('Choose a BrickTracker database file (app.db)')
    form = request.form.to_dict()
    validate(dict(form, file='upload'), spec['schema'])
    folder = bricktracker.plans_root(database()) / 'uploads'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / uuid.uuid4().hex
    digest, size = hashlib.sha256(), 0
    try:
        with target.open('wb') as out:
            while chunk := file.stream.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise errors.PayloadTooLarge()
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return form, Upload(target, digest.hexdigest(), file.filename or 'app.db')


# ---------- items in a request ----------

def item_of(db, key, *, what='item'):
    """The id of the live item an `ItemKey` names: by `id` (a merged one is `409 merged`), or by provider number (decision 3: `bricklink` unless
    named). None, or no such id, is `422 unidentified`; several is `409 ambiguous` with the candidates; a Rebrickable number a kind has none
    for is `422`."""
    if 'id' in key:
        try:
            return for_write(db, key['id'])
        except errors.NotFound:
            raise errors.Unidentified(f'No {what} with id {key["id"]}') from None
    provider = key.get('provider', 'bricklink')
    try:
        found = lookup.find_items(db, provider, key['kind'], key['key'], None)
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None
    return one_of(db, found, f'{provider} {key["kind"]} {key["key"]}')


def one_of(db, found, name):
    from .serializers import item as item_body
    if not found:
        raise errors.Unidentified(f'{name} names no item')
    if len(found) > 1:
        raise errors.Ambiguous(f'{name} names {len(found)} items; address one by id', candidates=[item_body(db, i) for i in found])
    return found[0]


def color_of(db, key, color):
    """The Brick Work colour id of a request's `color`: in the provider space of the item key (a Brick Work id when the item is named by id)."""
    if color is None:
        return None
    provider = 'brickwork' if 'id' in key else key.get('provider', 'bricklink')
    try:
        return lookup.brickwork_color(db, provider, color)
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None


def identified(db, key, color):
    """`(item id, colour id)` of an `ItemKey` and its colour. With a colour in the BrickLink space the number is read in that colour
    (design 3.2: a link scoped to the colour wins)."""
    if 'id' in key:
        return item_of(db, key), color_of(db, key, color)
    colour = color_of(db, key, color)
    provider = key.get('provider', 'bricklink')
    try:
        found = lookup.find_items(db, provider, key['kind'], key['key'], colour)
    except ValueError as error:
        raise errors.ValidationFailed(str(error)) from None
    return one_of(db, found, f'{provider} {key["kind"]} {key["key"]}'), colour


# ---------- preconditions ----------

def match(db, entity, identifier):
    """`412` unless the request's If-Match (when it has one) is the ETag of the row now (`*` is any)."""
    if 'If-Match' not in request.headers:
        return
    expected = request.if_match
    current = etag_of(db, entity, identifier)
    if not (expected.star_tag or (current is not None and expected.contains(current))):
        raise errors.PreconditionFailed()


def live_row(db, table, identifier, what, *, archived=False):
    """The row of `table` (a uuid text id), `404` if there is none and `409 archived` if it is archived (unless `archived` allows it)."""
    row = db.execute(f'SELECT * FROM main.{table} WHERE id=?', (str(identifier),)).fetchone() if len(str(identifier)) <= 64 else None
    if row is None:
        raise errors.NotFound(f'No such {what}')
    if row['archived_at'] and not archived:
        raise errors.Archived(f'This {what} is archived')
    return row


# ---------- the answer ----------

class Done:
    """What a write function returns: the `data` of the answer; `event` when the call knows which event is its receipt (else the newest undoable
    one it wrote); `status` when it is not the contract's first success status; `headers` to add."""

    def __init__(self, data, event=None, status=None, headers=None):
        self.data, self.event, self.status, self.headers = data, event, status, headers or {}


def now_text(delta=timedelta()):
    return (datetime.now(timezone.utc) + delta).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def digest_v1(body, content):
    if request.endpoint.split('.', 1)[-1] in KEYED:                  # key material: a keyed fingerprint, never a plain hash of it
        body = {'fingerprint': fingerprint(body)}
    file = None if content is None else content.sha256 if isinstance(content, Upload) else hashlib.sha256(content).hexdigest()
    packed = json.dumps(dict(v=1, method=request.method, path=request.path, query=sorted(request.args.items(multi=True)), body=body, file=file),
                        sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(packed.encode()).hexdigest()


DIGESTS = {1: digest_v1}                                           # every version ever stored in a receipt: an old receipt keeps replaying under its own


def digest_of(body, content, version=FINGERPRINT):
    return DIGESTS[version](body, content)


def receipt_of(spec, result):
    """The answer as the replay record keeps it: without what is shown once (a token's secret)."""
    hidden = SHOWN_ONCE.get(spec['endpoint'])
    if hidden is None:
        return result
    kept = {**result, hidden[0]: {**result[hidden[0]], hidden[1]: None}}
    return kept


def replay_of(db, key, body, content, actor):
    """The stored answer to this key within 30 days (by this token), or None; another request under the key is `409`. The request is
    fingerprinted by the version its receipt was stored under (`v`, 1 when the receipt has none)."""
    since = now_text(timedelta(days=-30))
    for row in db.execute("SELECT actor, at, new_value FROM main.event WHERE entity_kind='bw_api' AND entity_id=? AND field=? ORDER BY id DESC", (key, 'op:' + key)):
        if row['actor'] == actor and row['at'] >= since:
            saved = json.loads(row['new_value'])
            if saved['digest'] != digest_of(body, content, saved.get('v', 1)):
                raise errors.IdempotencyConflict()
            return saved
    return None


def undoable_events(db, after):
    """The events written after `after` that a registered undoer takes and that nobody undid, oldest first: `[(id, operation_key)]`."""
    return [(r['id'], r['operation_key']) for r in db.execute(
        f"SELECT e.id, e.operation_key, {undoing.undoable_sql('e')} AS undoable, {undoing.undone_sql('e')} AS undone FROM main.event e "
        f"WHERE e.id>? AND e.entity_kind!='bw_api' ORDER BY e.id", (after,)) if r['undoable'] and not r['undone']]


def newest_event(db, after):
    row = db.execute("SELECT max(id) FROM main.event WHERE id>? AND entity_kind!='bw_api'", (after,)).fetchone()
    return row[0]


def envelope(db, spec, done, before, preview=False):
    status = done.status or spec['statuses'][0]
    if preview:
        event = undo = None
    else:
        undoable = [i for i, _ in undoable_events(db, before)]
        if done.event is not None:
            event = done.event
            ok = db.execute(f"SELECT {undoing.undoable_sql('e')} AS undoable FROM main.event e WHERE e.id=?", (event,)).fetchone()
            undo = event if ok and ok['undoable'] and not undoing.is_undone(db, event) else None
        elif undoable:
            event = undo = undoable[-1]
        else:
            event, undo = newest_event(db, before), None
    if event is None and not spec['event_nullable']:
        raise RuntimeError('Mutation did not emit an event')
    result = {'data': done.data, 'event_id': event, 'idempotent_replay': False}
    if undo is not None:
        result['undo_url'] = f'/api/v2/events/{undo}/undo'
    elif spec['undo_nullable']:
        result['undo_url'] = None
    return clean(result, secret_values()), status


def execute(db, spec, function, values, body, content):
    """Run one write: replay, or the function and its answer, in one transaction."""
    key = request.headers.get('Idempotency-Key')
    if not key and spec['required']:
        raise errors.IdempotencyKeyRequired()
    if key is not None and not KEY.fullmatch(key):
        raise errors.BadRequest('Invalid Idempotency-Key')
    actor = g.api_identity['name']
    digest = digest_of(body, content)
    preview = body.get('dry_run') is True
    with transaction(db):
        if key:
            saved = replay_of(db, key, body, content, actor)
            if saved:
                return dict(saved['response'], idempotent_replay=True), saved['status'], saved.get('headers', {}), True
        before = db.execute('SELECT coalesce(max(id), 0) FROM main.event').fetchone()[0]
        if preview:
            db.execute('SAVEPOINT api_preview')
        with admin.operation(PREFIX + uuid.uuid4().hex):
            extra = {'content': content} if spec['multipart'] else {}
            done = function(db, body, **extra, **values)
            if not isinstance(done, Done):
                done = Done(done)
            result, status = envelope(db, spec, done, before, preview)
            if preview:
                db.execute('ROLLBACK TO api_preview')
                db.execute('RELEASE api_preview')
                return result, status, done.headers, False
            if key:
                admin.audit(db, 'bw_api:' + key, 'op:' + key, new=dict(v=FINGERPRINT, digest=digest, status=status, response=receipt_of(spec, result), headers=done.headers,
                                                                       method=request.method, path=request.path))
    return result, status, done.headers, False


def execute_detached(db, spec, function, values, body, content):
    """Run a write whose work reaches the network (or is long) outside any transaction: the function opens its own short transactions
    through the core writers, then the answer is stored in one more. A claim row keeps a concurrent duplicate of the same key from
    running the call twice; a failed call releases it, so the key can be sent again and no receipt is stored."""
    key = request.headers.get('Idempotency-Key')
    if not key and spec['required']:
        raise errors.IdempotencyKeyRequired()
    if key is not None and not KEY.fullmatch(key):
        raise errors.BadRequest('Invalid Idempotency-Key')
    actor = g.api_identity['name']
    claim = None
    with transaction(db):
        if key:
            saved = replay_of(db, key, body, content, actor)
            if saved:
                return dict(saved['response'], idempotent_replay=True), saved['status'], saved.get('headers', {}), True
            claim = f'api:claim:{actor}:{key}'
            held = db.execute('SELECT value FROM main.setting WHERE key=?', (claim,)).fetchone()
            if held and (datetime.now(timezone.utc) - datetime.strptime(held[0], '%Y-%m-%dT%H:%M:%S.000Z').replace(tzinfo=timezone.utc)).total_seconds() < CLAIM_SECONDS:
                raise errors.IdempotencyConflict('This Idempotency-Key is still being processed')
            db.execute('INSERT OR REPLACE INTO main.setting(key,value) VALUES(?,?)', (claim, now_text()))
    try:
        before = db.execute('SELECT coalesce(max(id), 0) FROM main.event').fetchone()[0]
        with admin.operation(PREFIX + uuid.uuid4().hex):
            extra = {'content': content} if spec['multipart'] else {}
            outcome = function(db, body, **extra, **values)
            with transaction(db):
                # A function may return a callable: the network work is done, and the change itself runs here, in the one transaction that
                # also stores the answer (an order import is whole or not at all).
                done = outcome() if callable(outcome) else outcome
                if not isinstance(done, Done):
                    done = Done(done)
                result, status = envelope(db, spec, done, before)
                if key:
                    admin.audit(db, 'bw_api:' + key, 'op:' + key, new=dict(v=FINGERPRINT, digest=digest_of(body, content), status=status, response=receipt_of(spec, result),
                                                                           headers=done.headers, method=request.method, path=request.path))
                if claim:
                    db.execute('DELETE FROM main.setting WHERE key=?', (claim,))
    except BaseException:
        if claim:
            with transaction(db):
                db.execute('DELETE FROM main.setting WHERE key=?', (claim,))
        raise
    return result, status, done.headers, False


def wake_worker():
    """A write may have queued a catalogue import (adding a copy, stock or a wish, a copy switched to BrickLink's list): start the embedded
    drainer when a job is due, as the web views do after their writes. The write has committed by then, so a failure here is logged and never
    replaces its response."""
    from ..core import drainer
    try:
        if drainer.poll_delay(database()) is not None:
            drainer.start(current_app._get_current_object(), transport.db_path())
    except Exception:
        current_app.logger.exception('the import worker did not start after an API write; queued jobs wait for the next start')


def write(function=None, *, detached=False):
    """A write view: the request is read and checked against the generated contract, the function runs once (or its stored answer replays).
    `@write(detached=True)` is for a call that reaches the network or runs long: it runs outside any transaction (`execute_detached`)."""
    if function is None:
        return lambda f: write(f, detached=detached)
    spec = SPEC[function.__name__]

    @wraps(function)
    def view(**values):
        db = database()
        arguments(spec)
        body, content = read_body(spec)
        try:
            result, status, headers, replayed = (execute_detached if detached else execute)(db, spec, function, values, body, content)
        finally:
            if isinstance(content, Upload):
                content.discard()
        if not replayed:
            wake_worker()
        response = jsonify(result)
        response.status_code = status
        for name, value in headers.items():
            response.headers[name] = value
        return response
    return view


def arguments(spec):
    """The query of a write: only what the contract declares for it, once."""
    unknown = set(request.args) - set(spec['query'])
    if unknown or any(len(request.args.getlist(name)) != 1 for name in request.args):
        raise errors.UnknownFilter('Unknown filter: ' + ', '.join(sorted(unknown)) if unknown else 'Repeat a query parameter only where documented')
    return request.args


def flag_argument(name):
    """A `true`/`false` query value as a bool (None when absent); anything else is `400 unknown_filter`."""
    value = request.args.get(name)
    if value is None:
        return None
    if value not in ('true', 'false'):
        raise errors.UnknownFilter(f'{name} is true or false')
    return value == 'true'


# ---------- Undo of a whole write ----------

def undo_operation(db, event_id, *, via, actor, identity):
    """Undo an event and, when it belongs to a v2 write, the undoable events that write made before it (newest first), so that the event a
    write names undoes the write whole. Returns `(undone_event_id, undo_event_id or None, already_undone)`."""
    event = db.execute('SELECT * FROM main.event WHERE id=?', (event_id,)).fetchone()
    if event is None:
        raise errors.NotFound('No such event')
    if undoing.is_undone(db, event_id):
        return event_id, db.execute('SELECT undo_event_id FROM main.event_undo WHERE event_id=?', (event_id,)).fetchone()[0], True
    group = [event_id]
    if (event['operation_key'] or '').startswith(PREFIX):
        group += [r['id'] for r in db.execute(
            f"SELECT e.id FROM main.event e WHERE e.operation_key=? AND e.id<? AND e.entity_kind!='bw_api' AND {undoing.undoable_sql('e')} "
            f"AND NOT {undoing.undone_sql('e')} ORDER BY e.id DESC", (event['operation_key'], event_id))]
    last = None
    for each in group:
        last = undoing.undo_event(db, each, via=via, actor=actor, identity=identity)['undo_event_id']
    return event_id, last, False


# ---------- refusals of the 4.0 store ----------

CONFLICTS = (copies_store.CopyMarked, copies_store.PendingChanged, copies_store.NothingToSwitch, copies_store.SwitchUndoRefused,
             pending_store.NotPending, pending_store.NotReady, copies_store.BrickLinkPending, store_errors.MergeRefused)


def store4_problem(error):
    """A refusal of the 4.0 store as the problem it is: a state that does not allow the change is `409`, a missing catalogue `424`, the rest
    `422`; the words are the refusal's own, with paths cut."""
    text = store_errors.public_text(error, what='an API write', refusal=True)
    if isinstance(error, CONFLICTS):
        mapped = errors.Conflict(text)
    elif isinstance(error, store_errors.CatalogueError):
        mapped = errors.CatalogueNotLoaded(text)
    elif isinstance(error, store_errors.AmbiguousIdentity):
        mapped = errors.Ambiguous(text)
    else:
        mapped = errors.ValidationFailed(text)
    return transport.problem(mapped)
