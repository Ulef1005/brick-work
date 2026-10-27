"""12n Collection sync pages (#10) on a 4.0 collection against the mocked Rebrickable of test_bw_sync (M.8j, issue #110). Invented data; no network."""
from contextlib import closing
import re

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core.connect import connect
from brickwork.core.sources import base
from tests.app4 import Coll, app4, client, pair, table_digest  # noqa: F401
from tests.test_bw_sync import EXTRA, GEAR, PASSWORD, TOKEN, Rebrickable
from tests.web_fixtures import ROOT  # noqa: F401


@pytest.fixture
def pair(tmp_path):  # noqa: F811
    from tests.app4 import make_pair
    return make_pair(tmp_path, rich=True, extra_dump=EXTRA)


@pytest.fixture
def remote(pair, monkeypatch):
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters.RebrickableUser, 'minimum_spacing', 0)
    monkeypatch.setattr(base, 'transport', lambda r: (_ for _ in ()).throw(AssertionError('network')))
    fake = Rebrickable()
    monkeypatch.setattr(adapters, 'transport', fake)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    monkeypatch.delenv('BW_BRICKSET_API_KEY', raising=False)
    with closing(connect(pair)) as db:
        Coll(db).add_copy('2070-1')
        Coll(db).add_copy('2070-1')
    return fake


def soup(response):
    assert response.status_code == 200, response.status_code
    return BeautifulSoup(response.data, 'html.parser')


def token(client):
    client.get('/manage/sync')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def count(pair, number, table='copy'):
    with closing(connect(pair, read_only=True)) as db:
        return db.execute(f'SELECT count(*) FROM {table} c JOIN item i ON i.id=c.item_id WHERE i.born_key=? AND c.archived_at IS NULL', (number,)).fetchone()[0]


def test_sources_page_cards_and_hub_row(client, remote):
    page = soup(client.get('/manage/sync'))
    cards = {c['data-sync-source']: c for c in page.select('[data-sync-source]')}
    assert cards['rebrickable'].select_one('.bk-pill').get_text(strip=True) == 'Not linked'
    assert cards['rebrickable'].select_one('a.bk-primary').get_text(strip=True) == 'Link a collection'
    assert cards['brickset'].select_one('[data-needs-key=brickset]').strong.text == 'Needs a Brickset key'
    assert 'Nothing pulled or sent yet.' in page.get_text()
    assert soup(client.get('/manage/tools')).find('a', href='/manage/sync')


def test_connect_link_pull_apply_undo(client, remote, pair):
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
    assert len(ticks) == 4 and all(ticks.values())
    assert [t.get_text(' ', strip=True) for t in plan.select('[data-sy-tab]')][:2] == ['All 5', 'New there 4']
    assert plan.select_one('[data-state=unmatched]')
    plan_id = plan.select_one('input[name=plan_id]')['value']
    with closing(connect(pair, read_only=True)) as db:
        first = db.execute('SELECT id FROM catalogue.item WHERE born_key=?', ('1000-1',)).fetchone()[0]
    response = client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'tick': [f'owned:{first}']})
    assert response.status_code == 302 and 'pulled=' in response.location
    sources = soup(client.get(response.location))
    assert 'Pulled · 2 copies' in sources.get_text()
    assert sources.select_one('.sy-log-row')
    event = re.search(r'pulled=(\d+)', response.location)[1]
    assert count(pair, '1000-1') == 2
    client.post('/manage/sync/rebrickable/undo', data={'csrf_token': csrf, 'event': event})
    assert count(pair, '1000-1') == 0
    assert 'Undone' in soup(client.get('/manage/sync')).select_one('.sy-log').get_text()


def test_pulled_gear_is_loose_stock_and_the_log_says_so(client, remote, pair):
    csrf = token(client)
    client.post('/manage/sync/rebrickable/paste', data={'csrf_token': csrf, 'value': TOKEN})
    response = client.post('/manage/sync/rebrickable/link', data={'csrf_token': csrf, 'owned': ['1', '2'], 'wishlist': '9', 'send_to': '1'})
    plan_id = soup(client.get(response.location)).select_one('input[name=plan_id]')['value']
    response = client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'tick': []})
    assert response.status_code == 302
    client.get(response.location)
    plan = soup(client.get(client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf}).location))
    gear = [i['value'] for i in plan.select('input[name=tick]')]
    assert gear
    plan_id = plan.select_one('input[name=plan_id]')['value']
    client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'tick': gear})
    assert count(pair, GEAR, 'stock') == 1
    assert '1 loose added' in soup(client.get('/manage/sync')).get_text()


def test_send_review_untick_removal_and_result(client, remote):
    csrf = token(client)
    client.post('/manage/sync/rebrickable/paste', data={'csrf_token': csrf, 'value': TOKEN})
    client.post('/manage/sync/rebrickable/link', data={'csrf_token': csrf, 'owned': ['1', '2'], 'wishlist': '9', 'send_to': '1'})
    response = client.post('/manage/sync/rebrickable/send', data={'csrf_token': csrf})
    review = soup(client.get(response.location))
    rows = {r.select_one('.sy-id .mono').get_text(strip=True): r for r in review.select('[data-sy-row]')}
    box = {number: row.select_one('input[name=tick]') for number, row in rows.items() if row.select_one('input[name=tick]')}
    assert box['2070-1'].has_attr('checked') and not box['1000-1'].has_attr('checked')
    assert 'Removals are unticked until you tick them.' in review.select_one('.sy-before').get_text()
    plan_id = review.select_one('input[name=plan_id]')['value']
    response = client.post('/manage/sync/rebrickable/send_apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'tick': [box['2070-1']['value']]})
    result = soup(client.get(response.location))
    assert 'Sent 1 change to Rebrickable' in result.select_one('.sy-result').get_text()
    assert remote.lists[1]['2070-1'] == 1


def test_rejected_token_message(client, remote):
    csrf = token(client)
    client.post('/manage/sync/rebrickable/paste', data={'csrf_token': csrf, 'value': 'wrong-token-123'})
    response = client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf})
    page = soup(client.get(response.location))
    assert 'Rebrickable rejected the key or user token' in page.get_text()


def test_writes_need_csrf(client, remote):
    assert client.post('/manage/sync/rebrickable/pull', data={}).status_code == 400
    assert client.get('/manage/sync/bricklink/link').status_code == 404


def test_the_pages_before_setup_show_the_notice(app4, tmp_path, monkeypatch):
    """#68: no database is not a 500 (moved here from test_bw_small_68_sync.py)."""
    from tests.web_fixtures import logged_in
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'not-set-up' / 'brickwork.db'))
    for path in ('/manage/sync', '/manage/sync/rebrickable/link'):
        response = logged_in(app4).get(path)
        assert response.status_code == 503
        assert 'database is not available' in response.get_data(as_text=True)
