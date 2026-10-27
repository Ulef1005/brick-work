"""v1.3 figure detail states and shared item-detail regressions (M.8d: what is left writes through the collection save).

The wanted link into Add and the initial radios moved to `test_bw_add.py` (M.8c)."""
from urllib.parse import urlsplit, parse_qs, quote
from pathlib import Path
import os
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection
from tests.test_bw_collection import bw, token
from tests.web_fixtures import app, apps, logged_in
from tests.importer.test_importer import legacy
from tests.test_bw_admin import reset_shell_metadata_after_test


def page(client, route='/collection/item/M/bl-figure'):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_unresolved_wanted_receipt_undo_and_rollback(app, bw):
    client = logged_in(app)
    csrf = token(client)
    route = '/collection/item/%3F/rebrickable:rb-review'
    soup = page(client, route)
    assert soup.select_one('[data-module=wanted] form[data-bc-action=wish] button').get_text() == 'Add to wishlist'
    saved = client.post('/collection/save/wish', json=dict(csrf_token=csrf,item_no='rebrickable:rb-review'))
    assert saved.status_code == 200, saved.json
    assert 'On the wishlist' in page(client, route).select_one('[data-module=wanted]').get_text()
    duplicate = client.post('/collection/save/wish', json=dict(csrf_token=csrf,item_no='rebrickable:rb-review'))
    assert duplicate.status_code == 400
    event = saved.json['event_id']
    with admin.database(bw) as db:
        assert db.execute('SELECT entity FROM events WHERE id=?',(event,)).fetchone()[0] == 'bw_collection'
    undone = client.post('/collection/save/undo', json=dict(csrf_token=csrf,event_id=event))
    assert undone.status_code == 200
    assert 'Not on the wishlist' in page(client, route).select_one('[data-module=wanted]').get_text()
    with admin.database(bw) as db:
        db.execute("CREATE TRIGGER reject_wish BEFORE INSERT ON events WHEN new.entity='bw_collection' BEGIN SELECT RAISE(ABORT,'receipt failed'); END")
        with pytest.raises(sqlite3.IntegrityError):
            collection.want_placeholder(db, 'rebrickable:rb-review')
        assert db.execute("SELECT count(*) FROM wishlist WHERE item_type='?' AND archived_at IS NULL").fetchone()[0] == 0
