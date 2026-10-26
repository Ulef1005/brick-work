"""v1.3 figure detail states and shared item-detail regressions."""
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


def test_wanted_add_uses_existing_review_confirm_and_undo(app, bw, monkeypatch):
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', lambda: None)
    with sqlite3.connect(bw.with_name('bricklink-catalog.db')) as cat:
        cat.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT)')
        cat.execute("INSERT INTO items VALUES('M','bl-figure','Synthetic figure')")
    client = logged_in(app)
    csrf = token(client)
    soup = page(client)
    link = soup.select_one('[data-module=wanted] a')
    target = page(client, link['href'])
    assert target.select_one('input[name=type][checked]')['value'] == 'M'
    assert target.select_one('input[name=where][checked]')['value'] == 'wishlist'
    assert target.select_one('input[name=mode][checked]')['value'] == 'paste'
    assert target.select_one('[data-paste]').get_text() == 'bl-figure'
    review = client.post('/manage/add/review', json=dict(csrf_token=csrf,type='M',where='wishlist',mode='paste',text='bl-figure'))
    assert review.status_code == 200, review.json
    proposal = review.get_json()
    assert len(proposal['items']) == 1
    proposal['items'][0]['decision'] = 'another'
    confirmed = client.post('/manage/add/confirm', json=dict(csrf_token=csrf,token=proposal['token'],items=proposal['items']))
    assert confirmed.status_code == 200, confirmed.json
    soup = page(client)
    wish_link = soup.select_one('[data-module=wanted] a')
    assert 'On the wishlist' in wish_link.get_text()
    with admin.database(bw) as db, db:
        db.execute("UPDATE wishlist SET max_price='11408.95',max_price_currency='EUR' WHERE item_type='M' AND item_no='bl-figure'")
    assert '€11,408.95' in page(client).select_one('[data-module=wanted]').get_text()
    # A later edit of the wish blocks the Undo of the add; it never restores over the edit.
    blocked = client.post('/manage/add/undo', json=dict(csrf_token=csrf,batch=confirmed.json['batch']))
    assert blocked.status_code == 400 and 'undo the later save first' in blocked.get_json()['error']
    assert '€11,408.95' in page(client).select_one('[data-module=wanted]').get_text()
    with admin.database(bw) as db, db:
        db.execute("UPDATE wishlist SET max_price=NULL,max_price_currency=NULL WHERE item_type='M' AND item_no='bl-figure'")
    assert client.post('/manage/add/undo', json=dict(csrf_token=csrf,batch=confirmed.json['batch'])).status_code == 200
    assert 'Not on the wishlist' in page(client).select_one('[data-module=wanted]').get_text()


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


@pytest.mark.parametrize('query', ['type=X', 'type=X&where=X', 'type=&where='])
def test_add_invalid_initial_radios_fall_back(app, bw, query):
    soup = page(logged_in(app), '/manage/add?' + query)
    assert [r['value'] for r in soup.select('input[name=type][checked]')] == ['S']
    assert [r['value'] for r in soup.select('input[name=where][checked]')] == ['owned']

