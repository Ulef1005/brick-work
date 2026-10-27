"""The 3.3 BrickLink catalogue XML loader (`sources/bricklink_catalogue.py`): split out of test_brickwork_sources.py by M.8f, waiting for M.8i.

In 4.0 the BrickLink item lists are loaded by `catalogue import bricklink` (store4.bricklink_list) and the names come with reconcile; this loader and its
`bricklink-catalog.db` sidecar go with the Tools & Admin catalogue screen. The tests stay as written until M.8i removes or rewrites them."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs
from urllib.request import Request
from unittest.mock import Mock

import pytest

from brickwork.core.connect import connect
from brickwork.core.sources import base, bricklink_catalogue as catalogue
from brickwork.core.sources.bricklink import BrickLink, signed_request
from brickwork.core.sources.brickset import Brickset

FIXTURES = Path(__file__).parent / 'fixtures/brickwork'


@pytest.fixture
def db(tmp_path):
    with closing(connect(tmp_path / 'brickwork.db')) as connection:
        yield connection


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(base, 'transport', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    for key in (*BrickLink.credentials, *Brickset.credentials):
        monkeypatch.setenv(key, 'secret-' + key)


def reply(data):
    return {'meta': {'code': 200}, 'data': data}


def test_catalogue_all_types_and_previous(db, tmp_path):
    target = tmp_path / 'bricklink-catalog.db'
    result = catalogue.load(FIXTURES, target, db)
    assert result['counts'] == dict.fromkeys('SPMGBCIO', 1)
    with sqlite3.connect(target) as index:
        assert index.execute("SELECT name FROM items WHERE item_type='B'").fetchone()[0] == 'Test (B)'
    previous = target.read_bytes()
    catalogue.load(FIXTURES, target, db)
    assert target.with_name('bricklink-catalog.prev.db').read_bytes() == previous
    bad = tmp_path / 'bad'
    bad.mkdir()
    (bad / 'Sets.xml').write_text('<CATALOG><ITEM><ITEMTYPE>S</ITEMTYPE><ITEMID>1</ITEMID><ITEMNAME>X</ITEMNAME></ITEM></CATALOG>')
    current = target.read_bytes()
    with pytest.raises(ValueError):
        catalogue.load(bad, target, db)
    assert target.read_bytes() == current
    assert db.execute('SELECT count(*) FROM source_records').fetchone()[0] == 16
    assert db.execute("SELECT count(*) FROM events WHERE via!='import'").fetchone()[0] == 0


def test_atomic_replace_failure(db, tmp_path, monkeypatch):
    target = tmp_path / 'bricklink-catalog.db'
    catalogue.load(FIXTURES, target, db)
    catalogue.load(FIXTURES, target, db)
    current, previous = target.read_bytes(), target.with_name('bricklink-catalog.prev.db').read_bytes()
    replace = catalogue.os.replace
    def fail(source, dest):
        if Path(dest) == target:
            raise OSError('install failed')
        return replace(source, dest)
    monkeypatch.setattr(catalogue.os, 'replace', fail)
    with pytest.raises(OSError):
        catalogue.load(FIXTURES, target, db)
    assert target.read_bytes() == current
    assert target.with_name('bricklink-catalog.prev.db').read_bytes() == previous


def test_catalogue_loader_updates_held_names_with_provenance(db,tmp_path):
    with db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P','123-1','Fallback')")
    catalogue.load(FIXTURES,tmp_path/'bricklink-catalog.db',db)
    assert db.execute("SELECT name FROM items WHERE item_type='P'").fetchone()[0]=='Test (P)'
    assert tuple(db.execute("SELECT value,source FROM item_properties WHERE key='name'").fetchone())==('Test (P)','bricklink')
