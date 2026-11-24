"""#520: the Brickset page at rest and its steps (connect, choose what, pick sets, preview, result) on the run of core.sync.run that the Rebrickable page
shares. Owned and wanted sets with counts only: what Brickset's back end here cannot do has no control. Invented data against the fake Brickset
of test_bw_sync; no network."""
from contextlib import closing
import json
import re
import sqlite3

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import sync
from brickwork.core.connect import connect
from brickwork.core.sources import base
from brickwork.core.sync import adapters
from brickwork.core.sync import run as sync_run
from tests.app4 import Coll, app4, client, pair  # noqa: F401
from tests.test_bw_sync import EXTRA, HASH, Brickset
from tests.web_fixtures import ROOT  # noqa: F401

BASE = '/workbench/sync/brickset'
CHOICES = {'owned_dir': 'both', 'wishlist_dir': 'both', 'wish_list': 'default'}


@pytest.fixture
def pair(tmp_path):  # noqa: F811
    from tests.app4 import make_pair
    return make_pair(tmp_path, rich=True, extra_dump=EXTRA)


@pytest.fixture
def remote(pair, monkeypatch):
    monkeypatch.setattr(base, 'transport', lambda r: (_ for _ in ()).throw(AssertionError('network')))
    fake = Brickset()
    monkeypatch.setattr(adapters, 'transport', fake)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'synthetic-brickset-key')
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY', raising=False)
    monkeypatch.delenv('BW_BRICKSET_USER_HASH', raising=False)
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


def connected(client, pair):
    csrf = token(client)
    assert client.post('/manage/sync/brickset/paste', data={'csrf_token': csrf, 'value': HASH}).status_code == 302
    assert 'Saved' in client.get(BASE).get_data(as_text=True)      # shows (and so clears) the flash of the save
    return csrf


def choose(client, csrf, **changes):
    return client.post(BASE + '/choose', data={'csrf_token': csrf, **{**CHOICES, **changes}})


def start(client, csrf, **changes):
    response = choose(client, csrf, **changes)
    assert response.status_code == 302 and '/run/' in response.location, response.location
    return re.search(r'/run/([0-9a-f]{32})/pick', response.location)[1]


def run_data(page, **extra):
    """What a browser posts from the preview: the fields as they stand, ticked boxes and chosen radios."""
    data = {}
    for i in page.select('form.sr-preview input[name], form.sr-preview select[name]'):
        if i.name == 'select':
            chosen = i.select_one('option[selected]') or i.select_one('option')
            if chosen is not None and chosen.get('value', '') != '':
                data.setdefault(i['name'], chosen['value'])
        elif i.get('type') in ('checkbox', 'radio'):
            if i.has_attr('checked'):
                data.setdefault(i['name'], []).append(i['value'])
        elif i.get('type') != 'submit':
            data[i['name']] = i.get('value', '')
    data.update(extra)
    return data


def preview_of(client, run_id):
    return soup(client.get(f'{BASE}/run/{run_id}/preview'))


def rows_of(page):
    return {r.get('data-name', '').split(' ')[0]: r for r in page.select('[data-sy-row]')}


def apply_run(client, csrf, run_id, page=None, **extra):
    page = page or preview_of(client, run_id)
    return client.post(f'{BASE}/run/{run_id}/run', data={'csrf_token': csrf, **run_data(page, **extra)})


def copies(pair, number):
    with db_of(pair) as db:
        return db.execute("SELECT count(*) FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=? AND c.archived_at IS NULL", (number,)).fetchone()[0]


def wishes(pair, number):
    with db_of(pair) as db:
        return db.execute("SELECT coalesce(sum(w.quantity), 0) FROM wish w JOIN item i ON i.id=w.item_id WHERE i.born_key=? AND w.archived_at IS NULL", (number,)).fetchone()[0]


# --- frame 25 -----------------------------------------------------------------------------------------------------------

def test_the_page_before_a_connection_offers_connect_and_makes_no_call(client, remote):
    page = soup(client.get(BASE))
    assert page.select_one('h1').get_text(strip=True) == 'Brickset'
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Not connected'
    assert page.select_one('a.bk-primary').get_text(strip=True) == 'Connect' and page.select_one('a.bk-primary')['href'].endswith(BASE + '/connect')
    assert 'Nothing has run yet.' in page.get_text()
    assert remote.calls == []


def test_the_page_at_rest_shows_account_budget_runs_and_what_syncs_without_a_call(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0', owned_dir='into', wishlist_dir='to')
    remote.calls.clear()
    page = soup(client.get(BASE))
    assert remote.calls == []                                            # the page at rest reads nothing from Brickset
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Connected'
    kv = [t.get_text(' ', strip=True) for t in page.select('[data-rb-account] .sr-kv dt, [data-rb-account] .sr-kv dd')]
    assert kv == ['API key', 'Set in the environment', 'Today’s budget', '0 of 100 calls']      # the account name is not stored; no request speed is claimed
    assert [b.get_text(strip=True) for b in page.select('[data-rb-account] .sr-actions .bk-btn')] == ['Test', 'Change', 'Remove']
    table = [[c.get_text(' ', strip=True) for c in tr.select('td')] for tr in page.select('[data-rb-what] tbody tr')]
    assert table == [['Owned sets', 'Into Brick Work', 'Quantity owned'], ['Wanted sets', 'To Brickset', 'Wanted, as a flag, ↔ wishlist Wishlist']]
    assert page.select_one('form[action$="/workbench/sync/brickset/start"] button').get_text(strip=True) == 'Start a sync'
    assert page.select_one('[data-rb-what] a.bk-btn')['href'].endswith(BASE + '/choose')
    assert 'Purchase date and price never leave Brick Work' in page.get_text()


def test_the_account_buttons_of_the_page_come_back_to_it(client, remote, pair):
    csrf = connected(client, pair)
    response = client.post('/manage/sync/brickset/test', data={'csrf_token': csrf, 'next': 'site'})
    assert response.status_code == 302 and response.location.endswith(BASE)
    assert 'accepted the user token' in soup(client.get(response.location)).select_one('.bk-banner').get_text()
    response = client.post('/manage/sync/brickset/remove', data={'csrf_token': csrf, 'next': 'site'})
    assert response.location.endswith(BASE)
    assert soup(client.get(BASE)).select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Not connected'
    assert client.post('/manage/sync/brickset/test', data={'csrf_token': csrf, 'next': 'connect'}).location.endswith(BASE + '/connect')
    assert client.get('/manage/sync/brickset/link').location.endswith(BASE + '/connect')       # the old Link page is step 1 now


def test_the_hub_opens_the_page_of_a_connected_site_and_the_connect_step_of_the_other(client, remote, pair):
    hub = soup(client.get('/workbench/sync'))
    assert hub.select_one('[data-sync-site=brickset] a.bk-btn')['href'].endswith(BASE + '/connect')
    connected(client, pair)
    hub = soup(client.get('/workbench/sync'))
    assert hub.select_one('[data-sync-site=brickset] a.bk-btn')['href'].endswith(BASE)


# --- step 1 -------------------------------------------------------------------------------------------------------------

def test_connect_step_shows_the_key_and_the_account_and_never_the_secrets(client, remote, pair):
    page = soup(client.get(BASE + '/connect'))
    assert [li.get_text(' ', strip=True) for li in page.select('.sr-steps li')] == ['1 Connect', '2 Choose what', '3 Pick sets', '4 Preview', '5 Run', '6 Result']
    assert page.select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Set' and page.select_one('[data-rb-key] .sr-masked')['readonly'] is not None
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Not connected'
    assert page.select_one('form input[name=username]') and page.select_one('form input[type=password][name=password]')
    cards = ' '.join(c.get_text(' ', strip=True) for c in page.select('.sr-card'))
    assert 'Paste a user hash instead' in cards and 'user token' not in cards and 'Rebrickable' not in cards
    csrf = token(client)
    assert client.post('/manage/sync/brickset/connect', data={'csrf_token': csrf, 'username': 'synthetic-user', 'password': 'wrong', 'next': 'connect'}).status_code == 302
    assert 'did not accept' in soup(client.get(BASE + '/connect')).select_one('.bk-banner').get_text()
    from tests.test_bw_sync import PASSWORD
    assert client.post('/manage/sync/brickset/connect', data={'csrf_token': csrf, 'username': 'synthetic-user', 'password': PASSWORD, 'next': 'connect'}).location.endswith('/connect')
    page = soup(client.get(BASE + '/connect'))
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Connected'
    assert HASH not in page.decode() and PASSWORD not in page.decode()
    assert page.select_one('.sr-foot a.bk-btn')['href'].endswith(BASE + '/choose')


def test_the_api_key_is_saved_and_removed_from_step_1(client, remote, pair, monkeypatch):
    monkeypatch.delenv('BW_BRICKSET_API_KEY')
    page = soup(client.get(BASE + '/connect'))
    assert page.select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Not set'
    assert page.select_one('[data-rb-key] form input[name="key:key"][type=password]')
    csrf = token(client)
    saved = client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'save', 'key:key': 'synthetic-stored-key-1'})
    assert saved.location.endswith(BASE + '/connect')
    page = soup(client.get(saved.location))
    assert 'Saved' in page.select_one('.bk-banner').get_text() and 'synthetic-stored-key-1' not in page.decode()
    assert page.select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Set'
    client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'remove'})
    assert soup(client.get(BASE + '/connect')).select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Not set'
    assert client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'nonsense'}).status_code == 400


# --- step 2 -------------------------------------------------------------------------------------------------------------

def test_choose_step_needs_a_connection(client, remote):
    response = client.get(BASE + '/choose')
    assert response.status_code == 302 and response.location.endswith(BASE + '/connect')


def test_choose_step_shows_only_what_the_back_end_can_do_and_saves_it(client, remote, pair):
    csrf = connected(client, pair)
    page = soup(client.get(BASE + '/choose'))
    assert [h.get_text(strip=True) for h in page.select('.sr-card h2')] == ['Owned sets', 'Wanted sets', 'When both sides differ']
    assert [s.get_text(strip=True) for s in page.select('[data-rb-owned] .sr-seg span')] == ['Into Brick Work', 'Both ways', 'To Brickset', 'Off']
    assert page.select_one('input[name=owned_dir][checked]')['value'] == 'both' and page.select_one('input[name=wishlist_dir][checked]')['value'] == 'both'
    assert [o['value'] for o in page.select('select[name=wish_list] option')] == ['default']
    text = page.get_text(' ')
    for missing in ('Flag', 'Notes', 'Rating', 'priority', 'Minifigures', 'Lost Parts', 'Loose stock'):
        assert missing not in text, missing                       # a control for what the back end cannot do is not shown
    assert not page.select('input[type=checkbox]') and 'Ask me each time' in page.select('.sr-card')[-1].get_text()
    assert page.select_one('.sr-foot a.sr-link')['href'].endswith(BASE + '/connect')
    assert [b.get_text(strip=True) for b in page.select('.sr-foot button')] == ['Save', 'Next: pick sets']
    response = choose(client, csrf, start='0', owned_dir='into', wishlist_dir='off')
    assert response.location.endswith(BASE)
    with db_of(pair) as db:
        assert sync_run.directions(db, 'brickset') == dict(owned='into', wishlist='off', parts='off', lost='off')
        assert sync_run.directions(db, 'rebrickable')['owned'] == 'both'                       # Rebrickable's own are separate
    again = soup(client.get(BASE + '/choose'))
    assert again.select_one('input[name=owned_dir][checked]')['value'] == 'into' and again.select_one('input[name=wishlist_dir][checked]')['value'] == 'off'


def test_a_bad_choice_saves_nothing_and_the_two_sites_keep_their_own_choices(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0', owned_dir='to')
    response = choose(client, csrf, start='0', owned_dir='sideways')
    assert response.location.endswith(BASE + '/choose')
    with db_of(pair) as db:
        assert sync_run.directions(db, 'brickset')['owned'] == 'to'
        assert sync_run.directions(db, 'rebrickable')['owned'] == 'both'
        row = db.execute("SELECT 1 FROM setting WHERE key='rebrickable_sync_directions'").fetchone()
        assert row is None


# --- the run --------------------------------------------------------------------------------------------------------------

def test_a_run_pulls_and_sends_with_a_choice_per_row_and_one_undo_takes_the_pull_back(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    page = soup(client.get(f'{BASE}/run/{run_id}/pick'))
    assert [a.get_text(strip=True) for a in page.select('.sr-seg a')] == ['All linked', 'By theme', 'By year', 'One by one']      # no lists on Brickset
    assert page.select_one('[data-sr-count]').get_text(' ', strip=True) == '4 of 4 sets picked'
    assert client.get(f'{BASE}/run/{run_id}/pick?by=list').status_code == 404
    assert soup(client.get(f'{BASE}/run/{run_id}/pick?by=theme')).select('.sr-chip')
    assert client.post(f'{BASE}/run/{run_id}/pick', data={'csrf_token': csrf, 'item': [i['value'] for i in page.select('input[name=item]')]}).location.endswith('/preview')
    page = preview_of(client, run_id)
    rows = rows_of(page)
    assert sorted(rows) == ['1000-1', '1000-2', '1000-4', '2070-1']
    assert 'Add 3 here' in rows['1000-4'].get_text() and 'Add to wishlist here' in rows['1000-2'].get_text() and 'Add 1 there' in rows['2070-1'].get_text()
    assert re.fullmatch(r'\d+ / 100', page.select_one('[data-rb-before] .mono').get_text()) and page.select_one('[data-sy-requests]').get_text() == '1'
    assert 'seconds' not in page.select_one('[data-rb-before]').get_text()                  # no request speed is claimed for Brickset
    assert [t.get_text(' ', strip=True) for t in page.select('.sr-tabs button')] == ['All 4', 'Into Brick Work 3', 'To Brickset 1', 'Changed in both places 0']
    assert apply_run(client, csrf, run_id, page).location.endswith(f'/run/{run_id}/result')
    assert copies(pair, '1000-1') == 1 and copies(pair, '1000-4') == 3 and wishes(pair, '1000-2') == 1
    assert remote.owned['2070-1'] == (1003, 1)
    page = soup(client.get(f'{BASE}/run/{run_id}/result'))
    assert [h.get_text(' ', strip=True) for h in page.select('.sr-card h2')] == ['Here in Brick Work 5 changed', 'On Brickset 1 sent']
    assert '4 sets added' in page.select_one('[data-rb-here]').get_text() and '1 wish added' in page.select_one('[data-rb-here]').get_text()
    assert 'cannot be undone here' in page.select_one('[data-rb-there] .sr-info').get_text() and 'Brickset' in page.select_one('[data-rb-there] .sr-info').get_text()
    site = soup(client.get(BASE))
    undo = site.select_one('[data-rb-runs] form[action$="/workbench/sync/brickset/undo"]')
    assert undo and site.select_one('[data-rb-runs] .sr-run b').get_text().startswith('Run · ')
    response = client.post(BASE + '/undo', data={'csrf_token': csrf, 'event': undo.select_one('input[name=event]')['value']})
    assert response.location.endswith(BASE)
    assert copies(pair, '1000-1') == 0 and copies(pair, '1000-4') == 0 and wishes(pair, '1000-2') == 0
    assert remote.owned['2070-1'] == (1003, 1)                                              # what was sent stays sent


def test_a_conflict_is_a_choice_and_keep_changes_nothing(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf, owned_dir='both', wishlist_dir='off')
    apply_run(client, csrf, run_id)                      # a first run: 1000-1 and 1000-4 come in, 2070-1 goes out
    with db_of(pair) as db:
        Coll(db).add_copy('1000-1')                      # here 2, there 1 since the last run
    remote.owned['1000-1'] = (1001, 4)                   # and there 4: changed in both places
    run_id = start(client, csrf, owned_dir='both', wishlist_dir='off')
    page = preview_of(client, run_id)
    conflict = page.select_one('[data-rb-conflicts]')
    assert conflict and '1000-1' in conflict.get_text() and 'here 2 · Brickset 4' in conflict.get_text()
    options = [i['value'] for i in conflict.select('input[type=radio]')]
    assert options == ['keep', 'take', 'send']
    assert conflict.select_one('input[value=keep]').has_attr('checked')
    apply_run(client, csrf, run_id, page)
    assert copies(pair, '1000-1') == 2 and remote.owned['1000-1'] == (1001, 4)
    run_id = start(client, csrf, owned_dir='both', wishlist_dir='off')
    apply_run(client, csrf, run_id, **{'choice:owned:' + str(_item(pair, '1000-1')): 'send'})
    assert remote.owned['1000-1'] == (1001, 2)


def _item(pair, number):
    with db_of(pair) as db:
        return sync.translate(db, [number])[number]


def test_a_wish_of_two_here_and_a_wanted_flag_there_is_not_a_difference(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_wish(coll.item('sets', '1000-2'), quantity=2)
    run_id = start(client, csrf, owned_dir='off')
    with db_of(pair) as db:
        run, plans = sync_run.load(db, run_id)
        assert [c['number'] for c in run['candidates']] == []
        assert sync_run.rows(db, run, plans) == []
    page = preview_of(client, run_id)
    assert not rows_of(page) and 'Nothing differs' in page.get_text()


def test_a_wish_removed_here_is_offered_for_the_flag_there_and_a_flag_goes_off_only_when_chosen(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf, owned_dir='off', wishlist_dir='to')
    page = preview_of(client, run_id)
    row = rows_of(page)['1000-2']
    assert 'Remove from Brickset' in row.get_text() and not row.select_one('input[type=checkbox][checked]')
    apply_run(client, csrf, run_id, page)
    assert '1000-2' in remote.wanted                       # an unticked removal is not sent
    run_id = start(client, csrf, owned_dir='off', wishlist_dir='to')
    apply_run(client, csrf, run_id, **{'choice:wanted:' + str(_item(pair, '1000-2')): 'remove'})
    assert '1000-2' not in remote.wanted


def test_a_failed_send_is_listed_on_the_result_with_a_retry_and_the_daily_budget_pauses_the_rest(client, remote, pair, monkeypatch):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        Coll(db).add_copy('1000-3')
    run_id = start(client, csrf, owned_dir='to', wishlist_dir='off')
    real = adapters.BricksetUser.send

    def pause(self, row, link, state):
        raise base.WaitingForBudget(None, '2026-11-25T00:00:00+00:00')
    monkeypatch.setattr(adapters.BricksetUser, 'send', pause)
    apply_run(client, csrf, run_id)
    page = soup(client.get(f'{BASE}/run/{run_id}/result'))
    assert '2 waiting' in page.select_one('.sr-head p').get_text() and 'failed' not in page.select_one('.sr-head p').get_text()
    assert page.select_one('form[action$="/retry"] button').get_text(strip=True) == 'Retry'
    assert 'the daily budget' in page.select_one('[data-rb-there]').get_text()
    site = soup(client.get(BASE))
    retry_form = site.select_one('[data-rb-runs] form[action$="/manage/sync/brickset/send"]')
    assert retry_form and retry_form.select_one('input[name=next]')['value'] == 'site'     # on a failed re-plan the user stays on the site page
    monkeypatch.setattr(adapters.BricksetUser, 'send', real)
    assert client.post(f'{BASE}/run/{run_id}/retry', data={'csrf_token': csrf}).location.endswith('/result')
    assert remote.owned['2070-1'] == (1003, 1) and remote.owned['1000-3'] == (1004, 1)


def test_a_run_of_the_other_site_opens_and_changes_nothing_here(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    for method, path in (('get', 'pick'), ('get', 'preview'), ('get', 'result')):
        assert getattr(client, method)(f'/workbench/sync/rebrickable/run/{run_id}/{path}').status_code == 404, path
    for path in ('pick', 'run', 'retry'):
        assert client.post(f'/workbench/sync/rebrickable/run/{run_id}/{path}', data={'csrf_token': csrf}).status_code == 404, path
    assert copies(pair, '1000-1') == 0
    assert client.get(f'{BASE}/run/{"f" * 32}/pick').location.endswith(BASE)
    assert client.post(f'{BASE}/run/{"f" * 32}/run', data={'csrf_token': csrf}).status_code in (302, 303)


def test_a_refused_hash_stops_the_start_with_a_message_and_stays_on_the_page(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0')
    client.post('/manage/sync/brickset/paste', data={'csrf_token': csrf, 'value': 'a-hash-brickset-refuses'})
    response = client.post(BASE + '/start', data={'csrf_token': csrf})
    assert response.status_code == 302 and response.location.endswith(BASE)
    assert 'Brickset rejected the key or user token' in ' '.join(b.get_text() for b in soup(client.get(response.location)).select('.bk-banner'))


def test_a_read_only_instance_shows_no_buttons_and_refuses_every_write(app4, client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    app4.config['BW_READ_ONLY'] = True
    try:
        site = soup(client.get(BASE))
        assert not site.select('.sr-headrow form') and not site.select('[data-rb-account] form')
        assert not preview_of(client, run_id).select('.sr-foot button')
        for url, data in ((f'{BASE}/run/{run_id}/run', {}), (f'{BASE}/run/{run_id}/pick', {'item': ['1']}), (BASE + '/choose', CHOICES), (BASE + '/start', {}),
                          (BASE + '/undo', {'event': '1'}), (BASE + '/key', {'action': 'test'})):
            assert client.post(url, data={'csrf_token': csrf, **data}).status_code == 403, url
    finally:
        app4.config['BW_READ_ONLY'] = False


def test_the_rebrickable_choices_and_the_brickset_ones_do_not_meet(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0', owned_dir='to')
    with db_of(pair) as db:
        assert json.loads(db.execute("SELECT value FROM setting WHERE key='brickset_sync_directions'").fetchone()[0]) == dict(owned='to', wishlist='both')
        assert sync.status(db, 'brickset')['link'] == {'wish_list': 'default'}


def test_a_run_of_the_other_site_is_a_404_and_a_failing_db_answers_302_not_500(client, remote, pair, monkeypatch):
    from werkzeug.exceptions import NotFound
    from brickwork.web import sync_site
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    with db_of(pair) as db, pytest.raises(NotFound):
        sync_site._same_site(db, run_id, 'rebrickable')

    def locked():
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(sync_site, '_db', locked)
    for path in ('pick', 'run', 'retry'):
        response = client.post(f'{BASE}/run/{run_id}/{path}', data={'csrf_token': csrf})
        assert response.status_code == 302, path


def test_brickset_start_with_owned_off_and_wanted_to_does_not_call_set_ids_for_owned_rows(client, remote, pair, monkeypatch):
    csrf = connected(client, pair)
    seen = []
    real_set_ids = adapters.BricksetUser.set_ids

    def counted(self, numbers):
        seen.append(list(numbers))
        return real_set_ids(self, numbers)

    monkeypatch.setattr(adapters.BricksetUser, 'set_ids', counted)
    start(client, csrf, owned_dir='off', wishlist_dir='to')
    assert seen == []
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_wish(coll.item('sets', '1000-3'), quantity=1)
    start(client, csrf, owned_dir='off', wishlist_dir='to')
    assert seen == [['1000-3']]


def test_a_wish_lowered_here_and_cleared_there_is_not_a_conflict_on_brickset(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_wish(coll.item('sets', '1000-2'), quantity=2)
    item_id = _item(pair, '1000-2')
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id)
    with db_of(pair) as db:
        db.execute('UPDATE wish SET quantity=1 WHERE item_id=? AND archived_at IS NULL', (item_id,))
        db.commit()
    if isinstance(remote.wanted, dict):
        remote.wanted.pop('1000-2', None)
    else:
        remote.wanted.discard('1000-2')
    run_id = start(client, csrf, owned_dir='off', wishlist_dir='both')
    with db_of(pair) as db:
        run, plans = sync_run.load(db, run_id)
        pull_row = next(r for r in plans['pull']['rows'] if r['key'] == f'wanted:{item_id}')
        send_row = next(r for r in plans['send']['rows'] if r['key'] == f'wanted:{item_id}')
        assert pull_row['baseline_here'] == 2 and pull_row['baseline_remote'] == 1
        assert pull_row['state'] != 'conflict' and send_row['state'] != 'conflict'
        merged = sync_run.rows(db, run, plans)
        assert len(merged) == 1 and merged[0]['state'] != 'conflict'
    assert not preview_of(client, run_id).select_one('[data-rb-conflicts]')
