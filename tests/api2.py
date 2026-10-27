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
