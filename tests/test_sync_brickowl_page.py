"""#522 slice 2: the Brick Owl page at rest and its first three steps (connect, choose what, pick sets) on the run of core.sync.run that the other
sync pages share. The API key is the whole credential, and one Brick Owl wishlist is linked. What the back end here cannot do has no control.
Invented data against the fake Brick Owl of test_sync_brickowl_run; no network."""
from contextlib import closing
import re

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import sync
from brickwork.core.connect import connect
from brickwork.core.sources import base
from brickwork.core.sync import adapters
from brickwork.core.sync import run as sync_run
from tests.app4 import Coll, app4, client, pair  # noqa: F401
from tests.sources4 import keyed, unkeyed
from tests.test_bw_sync import EXTRA
from tests.test_sync_brickowl_run import BrickOwl
from tests.web_fixtures import ROOT  # noqa: F401

BASE = '/workbench/sync/brickowl'
CHOICES = {'owned_dir': 'both', 'wishlist_dir': 'both', 'wish_list': 'default', 'wishlist_id': '8101'}


@pytest.fixture
def pair(tmp_path):  # noqa: F811
    from tests.app4 import make_pair
    return make_pair(tmp_path, rich=True, extra_dump=EXTRA)


@pytest.fixture
def remote(pair, monkeypatch):
    unkeyed(monkeypatch)
    keyed(monkeypatch, 'brickowl')
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    fake = BrickOwl()
    monkeypatch.setattr(base, 'transport', fake)          # the key test builds a plain client
    monkeypatch.setattr(adapters, 'transport', fake)
    with closing(connect(pair)) as db:
        Coll(db).add_copy('2070-1')
    return fake


def soup(response):
    assert response.status_code == 200, response.status_code
    return BeautifulSoup(response.data, 'html.parser')


def token(client):
    client.get('/workbench/sync')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def db_of(pair):
    return closing(connect(pair))


def link_of(pair):
    with db_of(pair) as db:
        return sync.status(db, 'brickowl')['link']


def choose(client, csrf, drop=(), **changes):
    data = {'csrf_token': csrf, **CHOICES, **changes}
    return client.post(BASE + '/choose', data={k: v for k, v in data.items() if k not in drop})


def start(client, csrf, **changes):
    response = choose(client, csrf, **changes)
    assert response.status_code == 302 and '/run/' in response.location, response.location
    return re.search(r'/run/([0-9a-f]{32})/pick', response.location)[1]


def text(node):
    return ' '.join(node.get_text(' ', strip=True).split())


# --- the hub and the old routes -------------------------------------------------------------------------------------------

def test_the_hub_card_follows_the_api_key(client, remote, pair, monkeypatch):
    card = soup(client.get('/workbench/sync')).select_one('[data-sync-site=brickowl]')
    assert text(card.select_one('.sh-tag')) == 'Connected'
    assert card.select_one('a.bk-btn').get_text(strip=True) == 'Open' and card.select_one('a.bk-btn')['href'].endswith(BASE)
    assert 'Never' in card.select_one('.sh-meta').get_text() and 'orders' not in card.get_text()
    monkeypatch.delenv('BW_BRICKOWL_API_KEY')
    card = soup(client.get('/workbench/sync')).select_one('[data-sync-site=brickowl]')
    assert text(card.select_one('.sh-tag')) == 'Not connected' and 'none' in card.select_one('.sh-meta').get_text()
    assert card.select_one('a.bk-btn').get_text(strip=True) == 'Connect' and card.select_one('a.bk-btn')['href'].endswith(BASE + '/connect')
    assert remote.calls == []


def test_the_sync_log_names_brick_owl_in_two_words(client, remote, pair):
    with db_of(pair) as db:
        db.execute("INSERT INTO event(at, via, entity_kind, entity_id, field, new_value) VALUES "
                   "('2026-11-20T10:00:00Z', 'app', 'sync', 'brickowl', 'send', '{\"counts\": {\"sent\": 1}}')")
        db.commit()
    cells = [text(c) for c in soup(client.get('/workbench/sync')).select_one('.sy-log-row').select('span')]
    assert 'Brick Owl' in cells and 'Brickowl' not in cells


@pytest.mark.parametrize('action', ['connect', 'paste', 'remove', 'test'])
def test_the_user_credential_routes_do_not_exist_for_brick_owl(client, remote, pair, action):
    csrf = token(client)
    response = client.post(f'/manage/sync/brickowl/{action}', data={'csrf_token': csrf, 'value': 'synthetic-value-1', 'username': 'u', 'password': 'p'})
    assert response.status_code == 404
    assert remote.calls == []


def test_the_old_link_page_goes_to_step_1_of_each_site(client, remote):
    assert client.get('/manage/sync/brickowl/link').location.endswith(BASE + '/connect')
    assert client.get('/manage/sync/brickset/link').location.endswith('/workbench/sync/brickset/connect')
    assert client.get('/manage/sync/rebrickable/link').location.endswith('/workbench/sync/rebrickable/connect')


def test_a_refused_key_on_the_old_send_page_is_called_a_key(client, remote, pair):
    from brickwork.web.sync_views import _message
    assert _message(base.KeyRejected('x'), 'brickowl') == 'Brick Owl rejected the key. Nothing was changed there.'
    assert _message(base.KeyRejected('x'), 'brickset') == 'Brickset rejected the key or user token. Nothing was changed there.'


def test_the_send_retry_of_the_page_opens_the_review_of_a_send(client, remote, pair):
    csrf = token(client)
    sync_link = client.post('/manage/sync/brickowl/send', data={'csrf_token': csrf, 'next': 'site'})
    assert sync_link.status_code == 302 and '/manage/sync/brickowl/plan/' in sync_link.location
    page = soup(client.get(sync_link.location))
    assert 'Send to Brick Owl' in page.get_text() and 'user token' not in page.get_text()


def test_the_navigation_marks_sync_on_the_brick_owl_steps(app4, client, remote):
    from brickwork.web import ui
    with app4.test_request_context(BASE + '/connect'):
        link = next(l for l in dict(ui.navigation())['Workbench'] if l['title'] == 'Sync')
        assert link['active'] is True


# --- the page at rest (frame 31) ------------------------------------------------------------------------------------------

def test_the_page_without_a_key_offers_connect_and_makes_no_call(client, remote, monkeypatch):
    monkeypatch.delenv('BW_BRICKOWL_API_KEY')
    page = soup(client.get(BASE))
    assert page.select_one('h1').get_text(strip=True) == 'Brick Owl' and 'Not synced yet' in page.get_text()
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Not connected'
    assert page.select_one('a.bk-primary').get_text(strip=True) == 'Connect' and page.select_one('a.bk-primary')['href'].endswith(BASE + '/connect')
    assert [text(b) for b in page.select('[data-rb-account] .sr-actions .bk-btn')] == ['Connect']
    assert remote.calls == []


def test_the_page_at_rest_shows_the_key_the_one_budget_and_what_syncs_without_a_call(client, remote, pair):
    csrf = token(client)
    assert choose(client, csrf, start='0', owned_dir='into', wishlist_dir='to').location.endswith(BASE)
    remote.calls.clear()
    page = soup(client.get(BASE))
    assert remote.calls == []                                            # the page at rest reads nothing from Brick Owl
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Connected'
    kv = [text(t) for t in page.select('[data-rb-account] .sr-kv dt, [data-rb-account] .sr-kv dd')]
    assert kv == ['API key', 'Set in the environment', 'Speed', 'At most 5 requests a second']       # no account name: none is stored
    assert [text(b) for b in page.select('[data-rb-account] .sr-actions .bk-btn')] == ['Test', 'Change']     # an environment key cannot be removed here
    budget = page.select_one('[data-rb-budget]')
    assert budget.select_one('h2').get_text(strip=True) == 'Today’s budget'
    assert [text(r) for r in budget.select('.sr-budget')] == ['All calls 0 of 2,000']      # one shared budget: no number per kind
    assert 'per-endpoint' not in page.get_text()
    assert page.select_one('[data-rb-runs]') is None                      # frame 31: no Last runs before the first run
    table = [[text(c) for c in tr.select('td')] for tr in page.select('[data-rb-what] tbody tr')]
    assert table == [['Owned sets', 'Into Brick Work', 'Quantity owned'], ['Wanted sets', 'To Brick Owl', 'Quantity wanted ↔ wishlist Wishlist']]
    assert page.select_one(f'form[action$="{BASE}/start"] button').get_text(strip=True) == 'Start a sync'
    assert page.select_one('[data-rb-what] a.bk-btn')['href'].endswith(BASE + '/choose')
    for word in ('user token', 'user hash', 'Rebrickable', 'Brickset'):
        assert word not in text(page.select_one('.bw-sync-rb-page') or page.select_one('#content'))


def test_a_lowered_daily_budget_is_the_number_shown(client, remote, monkeypatch):
    monkeypatch.setenv('BW_BRICKOWL_DAILY_BUDGET', '50')
    assert text(soup(client.get(BASE)).select_one('[data-rb-budget] .sr-budget')) == 'All calls 0 of 50'


def test_last_runs_show_once_there_is_a_run(client, remote, pair):
    with db_of(pair) as db:
        db.execute("INSERT INTO event(at, via, entity_kind, entity_id, field, new_value) VALUES "
                   "('2026-11-20T10:00:00Z', 'app', 'sync', 'brickowl', 'send', '{\"counts\": {\"failed\": 1}}')")
        db.commit()
    page = soup(client.get(BASE))
    assert '0 changes sent' in page.select_one('[data-rb-runs]').get_text()
    runs = page.select_one('[data-rb-runs]')
    assert 'Rebrickable' not in runs.get_text() and 'Brickset' not in runs.get_text() and runs.select_one('[data-busy-label="Checking Brick Owl"]')


def test_test_and_remove_on_the_page_act_on_the_api_key_and_come_back(client, remote, pair, monkeypatch):
    monkeypatch.delenv('BW_BRICKOWL_API_KEY')
    csrf = token(client)
    client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'save', 'key:key': 'synthetic-stored-key-1'})
    page = soup(client.get(BASE))
    assert [text(b) for b in page.select('[data-rb-account] .sr-actions .bk-btn')] == ['Test', 'Change', 'Remove']
    for form in page.select('[data-rb-account] .sr-actions form'):
        assert form['action'].endswith(BASE + '/key') and form.select_one('input[name=next]')['value'] == 'site'
    remote.calls.clear()
    response = client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'test', 'next': 'site'})
    assert response.location.endswith(BASE) and remote.paths() == ['user/details']
    assert 'Brick Owl accepted the API key' in soup(client.get(BASE)).select_one('.bk-banner').get_text()
    response = client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'remove', 'next': 'site'})
    assert response.location.endswith(BASE)
    assert soup(client.get(BASE)).select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Not connected'


# --- step 1 -----------------------------------------------------------------------------------------------------------------

def test_connect_is_the_api_key_alone_and_never_shows_it(client, remote, pair, monkeypatch):
    monkeypatch.delenv('BW_BRICKOWL_API_KEY')
    page = soup(client.get(BASE + '/connect'))
    assert [text(li) for li in page.select('.sr-steps li')] == ['1 Connect', '2 Choose what', '3 Pick sets', '4 Preview', '5 Run', '6 Result']
    assert [c.has_attr('data-rb-key') for c in page.select('.sr-card')] == [True]
    assert page.select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Not set'
    assert page.select_one('[data-rb-key] form input[name="key:key"][type=password]')
    assert not page.select('input[name=username], input[name=password], input[name=value]')
    words = text(page.select_one('[data-rb-key]'))
    assert 'Collection' in words and 'Wishlist' in words and 'user token' not in words and 'user hash' not in words
    assert page.select_one('.sr-foot a.bk-btn') is None and page.select_one('.sr-foot [aria-disabled=true]')
    csrf = token(client)
    saved = client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'save', 'key:key': 'synthetic-stored-key-1'})
    assert saved.location.endswith(BASE + '/connect')
    page = soup(client.get(saved.location))
    assert 'Saved · The key works' in page.select_one('.bk-banner').get_text() and 'synthetic-stored-key-1' not in page.decode()
    assert page.select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Set' and page.select_one('.sr-masked')['readonly'] is not None
    assert page.select_one('.sr-foot a.bk-btn')['href'].endswith(BASE + '/choose')
    client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'remove'})
    assert soup(client.get(BASE + '/connect')).select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Not set'


# --- step 2 (frame 32) ------------------------------------------------------------------------------------------------------

def test_choose_needs_a_key_and_makes_no_call_without_one(client, remote, monkeypatch):
    monkeypatch.delenv('BW_BRICKOWL_API_KEY')
    response = client.get(BASE + '/choose')
    assert response.status_code == 302 and response.location.endswith(BASE + '/connect')
    assert remote.calls == []


def test_choose_reads_the_wishlists_once_and_shows_only_what_the_back_end_can_do(client, remote, pair):
    csrf = token(client)
    page = soup(client.get(BASE + '/choose'))
    assert remote.paths() == ['wishlist/lists']
    assert [h.get_text(strip=True) for h in page.select('.sr-card h2')] == ['Owned sets', 'Wanted sets']
    assert [s.get_text(strip=True) for s in page.select('[data-rb-owned] .sr-seg span')] == ['Into Brick Work', 'Both ways', 'To Brick Owl', 'Off']
    assert [text(o) for o in page.select('select[name=wishlist_id] option')] == ['No wishlist', 'Winter shelf · 1 lot']
    assert page.select_one('select[name=wish_list]')
    assert not page.select('form.sr-choose input[type=checkbox]')              # no loose stock, no second wishlist
    words = text(page.select_one('form.sr-choose'))
    for claim in ('loose stock', 'cannot place', 'Orders', 'Unverified', 'price'):
        assert claim.lower() not in words.lower(), claim
    assert page.select_one('form.sr-choose')['action'].endswith(BASE + '/choose')
    assert page.select_one('.sr-foot a.sr-link')['href'].endswith(BASE + '/connect')
    assert 'Next: pick sets' in text(page.select_one('.sr-foot'))
    assert choose(client, csrf, start='0', owned_dir='to').location.endswith(BASE)
    assert link_of(pair) == {'wishlist_id': '8101', 'wish_list': 'default'}
    page = soup(client.get(BASE + '/choose'))
    assert page.select_one('select[name=wishlist_id] option[selected]')['value'] == '8101'
    assert page.select_one('input[name=owned_dir][checked]')['value'] == 'to'


def test_choosing_no_wishlist_unlinks_it(client, remote, pair):
    csrf = token(client)
    choose(client, csrf, start='0')
    choose(client, csrf, start='0', wishlist_id='')
    assert link_of(pair)['wishlist_id'] is None
    assert 'No Brick Owl wishlist linked' in soup(client.get(BASE)).select_one('[data-rb-what]').get_text()


@pytest.mark.parametrize('reply, reason', [
    (OSError('synthetic'), 'Brick Owl could not be reached'),
    ({'error': {'status': 'Invalid API key'}}, 'Brick Owl rejected the key.'),
    ({'error': {'status': 'Quota exceeded'}}, 'daily budget'),
])
def test_a_wishlist_read_that_fails_says_why_and_a_save_keeps_the_link(client, remote, pair, reply, reason):
    csrf = token(client)
    choose(client, csrf, start='0')
    remote.fail['wishlist/lists'] = [reply]
    page = soup(client.get(BASE + '/choose'))
    assert reason in page.select_one('.bk-banner[role=alert]').get_text()
    assert page.select_one('select[name=wishlist_id], input[name=wishlist_id]') is None
    assert 'stays linked' in page.select_one('[data-rb-wishlist]').get_text()
    assert choose(client, csrf, drop=('wishlist_id',), start='0', wishlist_dir='into').location.endswith(BASE)    # what that form posts
    assert link_of(pair)['wishlist_id'] == '8101'
    with db_of(pair) as db:
        assert sync_run.directions(db, 'brickowl')['wishlist'] == 'into'


def test_a_linked_wishlist_that_is_not_in_the_list_read_is_not_unlinked_by_a_save(client, remote, pair):
    with db_of(pair) as db:
        sync.link(db, 'brickowl', {'wishlist_id': '7777'})
    page = soup(client.get(BASE + '/choose'))
    chosen = page.select_one('select[name=wishlist_id] option[selected]')
    assert chosen['value'] == '7777' and 'not in the list' in chosen.get_text()


def test_a_bad_wishlist_id_saves_nothing(client, remote, pair):
    csrf = token(client)
    response = choose(client, csrf, wishlist_id='not an id')
    assert response.location.endswith(BASE + '/choose')
    assert link_of(pair) == {}


# --- step 3 (frame 71) ------------------------------------------------------------------------------------------------------

def test_pick_lists_the_sets_of_the_run_with_their_counts(client, remote, pair):
    run_id = start(client, token(client))
    remote.calls.clear()
    page = soup(client.get(f'{BASE}/run/{run_id}/pick'))
    assert remote.calls == []
    assert [text(li) for li in page.select('.sr-steps li')][2] == '3 Pick sets'
    rows = {text(r.select_one('b')).split(' ')[0]: [text(s) for s in r.select('.sr-pickid > span')] for r in page.select('[data-sr-row]')}
    assert rows['1000-1'] == ['Set · 2 at Brick Owl · not here yet']
    assert rows['2070-1'] == ['Set · not at Brick Owl · 1 here']
    assert rows['1000-3'] == ['Wanted · 1 at Brick Owl · not here yet']
    assert all(' · ' in text(r.select_one('b')) for r in page.select('[data-sr-row]'))
    assert all(r.select_one('input[name=item][checked]') for r in page.select('[data-sr-row]'))
    assert [text(a) for a in page.select('nav.sr-seg a')] == ['All linked', 'By theme', 'By year', 'One by one']
    assert 'linked to Wishlist here' in text(page.select_one('[data-rb-wishlist]'))
    budget = text(page.select_one('[data-rb-budget]'))
    assert re.search(r'Used today \d+ of 2,000 calls', budget) and 'about' not in budget
    count = len(page.select('[data-sr-row]'))
    assert text(page.select_one('.sr-foot [data-sr-count]')) == f'{count} of {count} sets picked'
    words = text(page.select_one('form.sr-pick'))
    for claim in ('Unverified', 'Orders', 'minifig', 'since the last run'):
        assert claim not in words, claim
    assert not page.select('input[type=checkbox]:not([name=item])')           # no wishlist is picked here
    assert page.select_one('.sr-foot a.sr-link')['href'].endswith(BASE + '/choose')
    one = soup(client.get(f'{BASE}/run/{run_id}/pick?by=one'))
    assert not one.select('input[name=item][checked]')
    assert client.get(f'{BASE}/run/{run_id}/pick?by=list').status_code == 404


def test_pick_says_when_no_wishlist_is_linked_or_wishes_are_off(client, remote, pair):
    csrf = token(client)
    run_id = start(client, csrf, wishlist_id='')
    assert 'No Brick Owl wishlist is linked' in soup(client.get(f'{BASE}/run/{run_id}/pick')).select_one('[data-rb-wishlist]').get_text()
    run_id = start(client, csrf, wishlist_dir='off')
    page = soup(client.get(f'{BASE}/run/{run_id}/pick'))
    assert 'Off in this run' in page.select_one('[data-rb-wishlist]').get_text() and 'Wanted ·' not in page.select_one('.sr-rows').get_text()


def test_next_preview_saves_the_pick_and_the_preview_opens(client, remote, pair):
    csrf = token(client)
    run_id = start(client, csrf)
    page = soup(client.get(f'{BASE}/run/{run_id}/pick'))
    ids = [i['value'] for i in page.select('input[name=item]')]
    response = client.post(f'{BASE}/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ids[:1]})
    assert response.location.endswith(f'{BASE}/run/{run_id}/preview')
    preview = soup(client.get(response.location))
    assert preview.select('[data-sy-row]')
    with db_of(pair) as db:
        assert sync_run.load(db, run_id)[0]['picked'] == [int(ids[0]) if ids[0].isdigit() else ids[0]]


def test_start_a_sync_goes_to_pick_and_a_failed_read_stays_on_the_page(client, remote, pair):
    csrf = token(client)
    choose(client, csrf, start='0')
    client.get(BASE)                                    # shows (and so clears) the flash of the save
    response = client.post(BASE + '/start', data={'csrf_token': csrf})
    assert re.search(r'/run/[0-9a-f]{32}/pick$', response.location)
    remote.fail['collection/lots'] = [{'error': {'status': 'Invalid API key'}}]
    response = client.post(BASE + '/start', data={'csrf_token': csrf})
    assert response.location.endswith(BASE)
    assert 'Brick Owl rejected the key.' in soup(client.get(response.location)).select_one('.bk-banner').get_text()


def test_a_run_of_another_site_does_not_open_here(client, remote, pair):
    run_id = start(client, token(client))
    assert client.get(f'/workbench/sync/brickset/run/{run_id}/pick').status_code == 404
    assert client.get(f'{BASE}/run/{run_id}/pick').status_code == 200


def test_a_read_only_instance_shows_no_buttons_and_refuses_every_write(app4, client, remote, pair):
    csrf = token(client)
    app4.config['BW_READ_ONLY'] = True
    assert soup(client.get(BASE)).select_one('[data-rb-account] .sr-actions form') is None
    assert not soup(client.get(BASE + '/connect')).select('[data-rb-key] form')
    for path in ('/key', '/choose', '/start'):
        assert client.post(BASE + path, data={'csrf_token': csrf, 'action': 'test'}).status_code in (403, 405)
