"""Helpers for the tests of API v2 (M.11a, issue #113) on the 4.0 fixtures of `tests/app4.py`."""
from contextlib import closing

import pytest

from brickwork.core import tokens
from brickwork.core.connect import connect
from tests.app4 import app4, coll, pair, world  # noqa: F401 — fixtures re-exported for the test files

BOOTSTRAP = 'synthetic-bootstrap'
PREFIX = '/api/v2'


@pytest.fixture
def v2(app4, monkeypatch):
    """A test client of the real app with `BW_API_TOKEN` set."""
    monkeypatch.setenv('BW_API_TOKEN', BOOTSTRAP)
    return app4.test_client()


def call(client, path, method='get', token=BOOTSTRAP, **kwargs):
    headers = dict(kwargs.pop('headers', {}))
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    return getattr(client, method)(PREFIX + path, headers=headers, **kwargs)


def stored_token(pair, scopes, name='synthetic-client'):
    """The secret of a stored token with those scopes."""
    with closing(connect(pair)) as db:
        return tokens.create(db, name, scopes)[0]['secret']


# ---- the answer against the contract (M.11b)
from copy import deepcopy
from pathlib import Path

from scripts.check_api_contract import load_yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = load_yaml((ROOT / 'docs/brickwork/openapi-v2.yaml').read_text())
OPERATION_BY_ID = {op['operationId']: op for methods in CONTRACT['paths'].values() for op in methods.values() if isinstance(op, dict)}


def _closed(node):
    """The contract's schemas with every object that lists properties closed: an answer may carry nothing the contract does not name.
    A free member (`{}` or an object without properties) stays free."""
    if isinstance(node, dict):
        if 'properties' in node and 'additionalProperties' not in node:
            node['additionalProperties'] = False
        for child in node.values():
            _closed(child)
    elif isinstance(node, list):
        for child in node:
            _closed(child)
    return node


CLOSED = _closed(deepcopy(CONTRACT))


def validate(response, operation_id, status='200'):
    """Fail unless the answer is what the contract says for this operation and status (media type, and the JSON against its schema)."""
    import jsonschema
    declared = CLOSED['paths']
    operation = next(op for methods in declared.values() for op in methods.values() if isinstance(op, dict) and op['operationId'] == operation_id)
    definition = operation['responses'][status]
    if '$ref' in definition:
        definition = CLOSED['components']['responses'][definition['$ref'].rsplit('/', 1)[1]]
    media = response.content_type.split(';')[0]
    assert response.status_code == int(status), response.get_data(as_text=True)[:500]
    assert media in definition['content'] or any(m.endswith('/*') and media.startswith(m[:-1]) for m in definition['content']), (media, list(definition['content']))
    if media.endswith('json'):
        schema = definition['content'][media]['schema']
        validator = jsonschema.Draft202012Validator({**schema, 'components': CLOSED['components']}, format_checker=jsonschema.FormatChecker())
        issues = list(validator.iter_errors(response.json))
        assert not issues, '\n'.join(f"{list(e.absolute_path)}: {e.message}" for e in issues[:8])
    return response


def add_files(coll, pair, world):
    """A cached picture (number 1) of the keep set and a PDF record (number 1) for it, with bytes under the media folder (beside the database)."""
    from tests.app4 import STAMP
    for name, content in (('data/images/synthetic.png', b'\x89PNG\r\n\x1a\n'), ('data/instructions/synthetic.pdf', b'%PDF-1.4\n%%EOF')):
        target = Path(pair).parent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,width,height,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/synthetic.png',4,3,?)",
             (world.keep, STAMP))
    coll.sql("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,'data/instructions/synthetic.pdf','Synthetic booklet',?)", (world.keep, STAMP))


# ---- writes (M.11c)
import uuid


def write(client, path, method='post', body=None, key=True, token=BOOTSTRAP, headers=None, **kwargs):
    """A write: JSON `body` (omitted: none) under an Idempotency-Key of its own (`key=False`: none; a text: that one)."""
    headers = dict(headers or {})
    if key:
        headers['Idempotency-Key'] = key if isinstance(key, str) else 'k-' + uuid.uuid4().hex
    if body is not None and 'data' not in kwargs:
        kwargs['json'] = body
    return call(client, path, method, token=token, headers=headers, **kwargs)


def events(pair, where='1=1', params=()):
    """The event rows of the collection (oldest first), for a test that checks what a write left."""
    with closing(connect(pair, read_only=True)) as db:
        return [dict(r) for r in db.execute(f'SELECT * FROM main.event WHERE {where} ORDER BY id', params)]


def row(pair, sql, params=()):
    with closing(connect(pair, read_only=True)) as db:
        found = db.execute(sql, params).fetchone()
        return None if found is None else dict(found)


def rows(pair, sql, params=()):
    with closing(connect(pair, read_only=True)) as db:
        return [dict(r) for r in db.execute(sql, params)]


# ---- sources, network and keys (M.11d)
import io
import json
import secrets as token_source
from unittest.mock import Mock

from cryptography.fernet import Fernet

BL_ENV = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')


def fake(length=24):
    """A key-shaped value nobody uses."""
    return token_source.token_hex(length // 2)


def bl(data):
    return json.dumps({'meta': {'code': 200}, 'data': data})


class Wire:
    """Records every outbound request and answers from `replies` by URL fragment (a reply is a body, or a function of the request)."""

    def __init__(self):
        self.requests, self.replies = [], {}

    def __call__(self, request):
        self.requests.append(request)
        for fragment, reply in self.replies.items():
            if fragment in request.full_url:
                return reply(request) if callable(reply) else reply
        raise AssertionError('Unexpected outbound call ' + request.full_url.split('?')[0])


@pytest.fixture
def wire(monkeypatch):
    """No network: the source clients' transport is this recorder, the image downloads are forbidden, sleeps are skipped and no key is set."""
    from brickwork.core import secrets
    from brickwork.core.sources import base, images
    wire = Wire()
    monkeypatch.setattr(base, 'transport', wire)
    monkeypatch.setattr(images, 'transport', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    for name in (*BL_ENV, 'BW_REBRICKABLE_API_KEY', 'BW_BRICKSET_API_KEY', 'BW_SECRET_KEY', 'BW_BRICKOGNIZE_DAILY_BUDGET', 'BW_BRICKLINK_DAILY_BUDGET',
                 'BW_REBRICKABLE_USER_TOKEN', 'BW_BRICKSET_USER_HASH'):
        monkeypatch.delenv(name, raising=False)
    secrets.forget()
    return wire


@pytest.fixture
def secret(monkeypatch, wire):
    """`BW_SECRET_KEY` set: key entry is enabled."""
    value = Fernet.generate_key().decode()
    monkeypatch.setenv('BW_SECRET_KEY', value)
    return value


def png(size=(64, 48), mode='RGB'):
    from PIL import Image
    out = io.BytesIO()
    Image.new(mode, size, (200, 30, 30)).save(out, 'PNG')
    return out.getvalue()


def upload(client, path, content, name='x.png', mimetype='image/png', key=None, token=BOOTSTRAP, extra=None, method='post'):
    """A multipart write: `content` as the `file` part (under an Idempotency-Key when `key` says)."""
    headers = {'Authorization': 'Bearer ' + token}
    if key:
        headers['Idempotency-Key'] = key
    return getattr(client, method)(PREFIX + path, headers=headers, content_type='multipart/form-data',
                                   data={'file': (io.BytesIO(content), name, mimetype), **(extra or {})})
