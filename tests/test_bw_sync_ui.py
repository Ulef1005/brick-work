"""12n Collection sync pages (#10) against the mocked Rebrickable of test_bw_sync. Invented data; no network."""
from contextlib import closing
import os
import re
import sqlite3

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core.connect import connect
from brickwork.core.sources import base
from tests.test_bw_sync import Rebrickable, SETS, TOKEN, PASSWORD
from tests.web_fixtures import app, apps, logged_in  # noqa: F401


@pytest.fixture
def remote(app, tmp_path, monkeypatch):
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters.RebrickableUser, 'minimum_spacing', 0)
    monkeypatch.setattr(base, 'transport', lambda r: (_ for _ in ()).throw(AssertionError('network')))
    fake = Rebrickable()
    monkeypatch.setattr(adapters, 'transport', fake)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    monkeypatch.delenv('BW_BRICKSET_API_KEY', raising=False)
    path = tmp_path / 'brickwork.db'
    with closing(connect(path)) as db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','10003-1','Invented 10003-1')")
        db.execute("INSERT INTO copies(id,item_type,set_no) VALUES('here-1','S','10003-1'),('here-2','S','10003-1')")
        db.commit()
    with closing(sqlite3.connect(tmp_path / 'bricklink-catalog.db')) as cat, cat:
        cat.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT,normalized_name TEXT,category TEXT)')
        cat.executemany("INSERT INTO items VALUES('S',?,?,NULL,NULL)", [(n, 'Invented ' + n) for n in SETS])
    return fake


def soup(response):
    assert response.status_code == 200, response.status_code
    return BeautifulSoup(response.data, 'html.parser')


def token(client):
    client.get('/manage/sync')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def test_sources_page_cards_and_hub_row(app, remote):
    client = logged_in(app)
    page = soup(client.get('/manage/sync'))
    cards = {c['data-sync-source']: c for c in page.select('[data-sync-source]')}
    assert cards['rebrickable'].select_one('.bk-pill').get_text(strip=True) == 'Not linked'
    assert cards['rebrickable'].select_one('a.bk-primary').get_text(strip=True) == 'Link a collection'
    assert cards['brickset'].select_one('[data-needs-key=brickset]').strong.text == 'Needs a Brickset key'
    assert 'Nothing pulled or sent yet.' in page.get_text()
    assert soup(client.get('/manage/tools')).find('a', href='/manage/sync')


def test_connect_link_pull_apply_undo(app, remote):
    client = logged_in(app)
    csrf = token(client)
    link = soup(client.get('/manage/sync/rebrickable/link'))
    assert link.select_one('form[action$="/connect"] input[type=password][name=password]')
    response = client.post('/manage/sync/rebrickable/connect', data={'csrf_token': csrf, 'username': 'synthetic-user', 'password': PASSWORD})
    assert response.status_code == 302
    link = soup(client.get('/manage/sync/rebrickable/link'))
    assert 'Connected' in link.select_one('.sy-account .bk-pill').get_text()
    assert PASSWORD not in link.decode() and TOKEN not in link.decode()
    assert [i['value'] for i in link.select('input[name=owned]')] == ['1', '2', '9']
    response = client.post('/manage/sync/rebrickable/link', data={'csrf_token': csrf, 'owned': ['1', '2'], 'wishlist': '9', 'send_to': '1', 'wish_list': 'default'})
    assert response.status_code == 302 and '/manage/sync/rebrickable/plan/' in response.location
    plan = soup(client.get(response.location))
    ticks = {i['value']: i.has_attr('checked') for i in plan.select('input[name=tick]')}
    assert ticks['owned:10001-1'] and ticks['wanted:10004-1']
    assert [t.get_text(' ', strip=True) for t in plan.select('[data-sy-tab]')][:2] == ['All 4', 'New there 3']
    assert plan.select_one('[data-state=unmatched]')
    plan_id = plan.select_one('input[name=plan_id]')['value']
    response = client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'tick': ['owned:10001-1']})
    assert response.status_code == 302 and 'pulled=' in response.location
    sources = soup(client.get(response.location))
    assert 'Pulled · 2 copies' in sources.get_text()
    assert sources.select_one('.sy-log-row')
    event = re.search(r'pulled=(\d+)', response.location)[1]
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute("SELECT count(*) FROM copies WHERE set_no='10001-1' AND archived_at IS NULL").fetchone()[0] == 2
    client.post('/manage/sync/rebrickable/undo', data={'csrf_token': csrf, 'event': event})
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute("SELECT count(*) FROM copies WHERE set_no='10001-1' AND archived_at IS NULL").fetchone()[0] == 0


def test_send_review_untick_removal_and_result(app, remote):
    client = logged_in(app)
    csrf = token(client)
    client.post('/manage/sync/rebrickable/paste', data={'csrf_token': csrf, 'value': TOKEN})
    client.post('/manage/sync/rebrickable/link', data={'csrf_token': csrf, 'owned': ['1', '2'], 'wishlist': '9', 'send_to': '1'})
    response = client.post('/manage/sync/rebrickable/send', data={'csrf_token': csrf})
    review = soup(client.get(response.location))
    ticks = {i['value']: i.has_attr('checked') for i in review.select('input[name=tick]')}
    assert ticks['owned:10003-1'] and not ticks['owned:10001-1']
    assert 'Removals are unticked until you tick them.' in review.select_one('.sy-before').get_text()
    plan_id = review.select_one('input[name=plan_id]')['value']
    response = client.post('/manage/sync/rebrickable/send_apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'tick': ['owned:10003-1']})
    result = soup(client.get(response.location))
    assert 'Sent 1 change to Rebrickable' in result.select_one('.sy-result').get_text()
    assert remote.lists[1]['10003-1'] == 1


def test_rejected_token_message(app, remote):
    client = logged_in(app)
    csrf = token(client)
    client.post('/manage/sync/rebrickable/paste', data={'csrf_token': csrf, 'value': 'wrong-token-123'})
    response = client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf})
    page = soup(client.get(response.location))
    assert 'Rebrickable rejected the key or user token' in page.get_text()


def test_writes_need_csrf(app, remote):
    client = logged_in(app)
    assert client.post('/manage/sync/rebrickable/pull', data={}).status_code == 400
    assert client.get('/manage/sync/bricklink/link').status_code == 404
