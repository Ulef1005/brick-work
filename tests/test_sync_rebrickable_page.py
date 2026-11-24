"""#519: the Rebrickable page at rest and its steps (connect, choose what, pick sets, preview, result), the run orchestration in core.sync.run
and the Lost Parts rule's move out of Settings. Invented data against fakes of Rebrickable; no network."""
from contextlib import closing
import json
import os
import re

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import admin, errors, sync
from brickwork.core.connect import connect
from brickwork.core.sources import base
from brickwork.core.sync import adapters, lost_parts_send
from brickwork.core.sync import run as sync_run
from tests.app4 import Coll, app4, client, pair  # noqa: F401
from tests.test_bw_sync import EXTRA, TOKEN
from tests.test_bw_sync_lost_parts import Remote, copy_of, marks, raw, two_copies_line
from tests.test_rebrickable_part_lists import WithParts
from tests.web_fixtures import ROOT  # noqa: F401


class Full(Remote):
    """The fake Rebrickable with Lost Parts and the part lists of test_rebrickable_part_lists, and POST/DELETE answered for Lost Parts."""

    def __init__(self, lost=()):
        super().__init__(lost)
        self.part_lists = WithParts().part_lists
        self.lost_writes = []
        self.fail_writes = False
        self.fail_sets = False
        self.names = {}

    def __call__(self, request):
        path = request.full_url.split('/api/v3/users/', 1)[-1].split('?')[0]
        parts = path.strip('/').split('/')[1:]
        if parts and parts[0] == 'lost_parts' and request.get_method() in ('POST', 'DELETE'):
            if self.fail_writes:
                raise OSError('offline')
            self.lost_writes.append((request.get_method(), path, (request.data or b'').decode()))
            return {'lost_part_id': 900 + len(self.lost_writes)} if request.get_method() == 'POST' else ''
        if parts == ['setlists'] and self.names:
            return {'count': 3, 'next': None, 'results': [{'id': i, 'name': self.names.get(i, f'List {i}'), 'num_sets': len(v)} for i, v in self.lists.items()]}
        if self.fail_sets and parts and parts[0] == 'setlists' and request.get_method() in ('POST', 'PUT', 'DELETE'):
            raise OSError('offline')
        if parts and parts[0] == 'partlists':
            return WithParts.__call__(self, request)
        return super().__call__(request)


@pytest.fixture
def pair(tmp_path):  # noqa: F811
    from tests.app4 import make_pair
    return make_pair(tmp_path, rich=True, extra_dump=EXTRA)


@pytest.fixture
def remote(pair, monkeypatch):
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters.RebrickableUser, 'minimum_spacing', 0)
    monkeypatch.setattr(base, 'transport', lambda r: (_ for _ in ()).throw(AssertionError('network')))
    fake = Full()
    monkeypatch.setattr(adapters, 'transport', fake)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    monkeypatch.delenv('BW_BRICKSET_API_KEY', raising=False)
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
    assert client.post('/manage/sync/rebrickable/paste', data={'csrf_token': csrf, 'value': TOKEN}).status_code == 302
    assert 'Saved' in client.get('/workbench/sync/rebrickable').get_data(as_text=True)      # shows (and so clears) the flash of the save
    return csrf


CHOICES = {'list_name:set:1': 'Main collection', 'list_name:set:2': 'Bought 2026', 'list_name:set:9': 'Wishlist', 'list_name:part:31': 'Bulk bin', 'owned_dir': 'both', 'wishlist_dir': 'both', 'parts_dir': 'off', 'lost_dir': 'off', 'owned': ['1', '2'], 'wishlist': '9', 'send_to': '1',
           'wish_list': 'default', 'lost_rule': 'per_part', 'send_rule': 'add_only'}


def choose(client, csrf, **changes):
    return client.post('/workbench/sync/rebrickable/choose', data={'csrf_token': csrf, **{**CHOICES, **changes}})


def start(client, csrf, **changes):
    """Step 2 saved and Rebrickable read: the run id."""
    response = choose(client, csrf, **changes)
    assert response.status_code == 302 and '/run/' in response.location, response.location
    return re.search(r'/run/([0-9a-f]{32})/pick', response.location)[1]


def run_form(page):
    return page.select_one('form.sr-preview')


def run_data(page, **extra):
    """What a browser posts from the preview: the fields as they stand, ticked boxes, chosen radios and selected options."""
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


# --- page 18 ----------------------------------------------------------------------------------------------------------

def test_the_page_before_a_connection_offers_connect_and_makes_no_call(client, remote):
    page = soup(client.get('/workbench/sync/rebrickable'))
    assert page.select_one('h1').get_text(strip=True) == 'Rebrickable'
    assert page.select_one('.sr-kicker').get_text(strip=True) == 'Workbench · Sync'
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Not connected'
    assert not page.select_one('button.bk-primary') and page.select_one('.sr-headrow a.bk-primary')['href'].endswith('/workbench/sync/rebrickable/connect')
    assert 'Nothing has run yet.' in page.select_one('[data-rb-runs]').get_text()
    assert remote.calls == []


def test_the_page_at_rest_shows_account_runs_and_what_syncs_from_what_is_stored(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, parts_dir='into', part_list=['31'], lost_dir='both')
    remote.calls.clear()
    page = soup(client.get('/workbench/sync/rebrickable'))
    assert remote.calls == []                                            # the page at rest reads nothing from Rebrickable
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Connected'
    kv = [t.get_text(' ', strip=True) for t in page.select('[data-rb-account] .sr-kv dt, [data-rb-account] .sr-kv dd')]
    assert kv[:4] == ['API key', 'Set in the environment', 'Speed', 'About 1 request a second'] and 'Budget today' in kv
    assert [b.get_text(strip=True) for b in page.select('[data-rb-account] .sr-actions .bk-btn')] == ['Test', 'Change', 'Remove']
    table = [[c.get_text(' ', strip=True) for c in tr.select('td')] for tr in page.select('[data-rb-what] tbody tr')]
    assert table[0] == ['Owned sets', 'Both ways', '2 set lists: Main collection, Bought 2026']       # the names step 2 showed
    assert table[1] == ['Wishlist', 'Both ways', 'Rebrickable Wishlist ↔ wishlist Wishlist'] and table[2] == ['Loose stock', 'Into Brick Work', '1 part list: Bulk bin']
    assert table[3] == ['Lost Parts', 'Both ways', 'Rule: Rebrickable wins per part in, Add only out']
    assert page.select_one('form[action$="/workbench/sync/rebrickable/start"] button').get_text(strip=True) == 'Start a sync'
    assert page.select_one('[data-rb-what] a.bk-btn')['href'].endswith('/workbench/sync/rebrickable/choose')


def test_the_account_buttons_of_the_page_come_back_to_the_page(client, remote, pair):
    csrf = connected(client, pair)
    response = client.post('/manage/sync/rebrickable/test', data={'csrf_token': csrf, 'next': 'site'})
    assert response.status_code == 302 and response.location.endswith('/workbench/sync/rebrickable')
    assert 'accepted the user token' in soup(client.get(response.location)).select_one('.bk-banner').get_text()
    response = client.post('/manage/sync/rebrickable/remove', data={'csrf_token': csrf, 'next': 'site'})
    assert response.location.endswith('/workbench/sync/rebrickable')
    assert soup(client.get('/workbench/sync/rebrickable')).select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Not connected'
    assert client.post('/manage/sync/rebrickable/test', data={'csrf_token': csrf, 'next': 'connect'}).location.endswith('/workbench/sync/rebrickable/connect')


def test_a_pull_of_the_old_flow_still_lands_on_the_page_with_its_undo(client, remote, pair):
    csrf = connected(client, pair)
    start(client, csrf)
    response = client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf})
    plan = soup(client.get(response.location))
    applied = client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan.select_one('input[name=plan_id]')['value'],
                                                                   'tick': [i['value'] for i in plan.select('input[name=tick]')]})
    page = soup(client.get(applied.location))
    undo = page.select_one('form.sy-undo')
    assert undo['action'].endswith('/workbench/sync/rebrickable/undo') and undo.button.get_text(strip=True) == 'Undo this run'
    runs = page.select('[data-rb-runs] .sr-run')
    assert runs[0].select_one('b').get_text().startswith('Run · ') and 'added' in runs[0].get_text()
    assert [b.get_text(strip=True) for b in runs[0].select('button')] == ['Undo this run']
    response = client.post('/workbench/sync/rebrickable/undo', data={'csrf_token': csrf, 'event': undo.select_one('input[name=event]')['value']})
    assert response.location.endswith('/workbench/sync/rebrickable')
    page = soup(client.get(response.location))
    assert 'Run undone.' in page.select_one('.bk-banner').get_text()
    assert [t.get_text(strip=True) for t in page.select('[data-rb-runs] .sr-tag')][:2] == ['Done', 'Undone']
    with db_of(pair) as db:
        assert db.execute("SELECT count(*) FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-1' AND c.archived_at IS NULL").fetchone()[0] == 0


# --- step 1 -----------------------------------------------------------------------------------------------------------

def test_connect_step_shows_the_key_and_the_account_and_never_the_secrets(client, remote, pair):
    page = soup(client.get('/workbench/sync/rebrickable/connect'))
    assert [li.get_text(' ', strip=True) for li in page.select('.sr-steps li')] == ['1 Connect', '2 Choose what', '3 Pick sets', '4 Preview', '5 Run', '6 Result']
    assert page.select_one('.sr-steps li[aria-current=step]').get_text(strip=True) == '1 Connect'
    assert page.select_one('.sr-stepline').get_text() == 'Step 1 of 6 · Connect · next: Choose what'
    key, account = page.select_one('[data-rb-key]'), page.select_one('[data-rb-account]')
    assert key.h2.get_text(' ', strip=True) == '1 · API key Set' and 'The key reads Rebrickable’s catalogue' in key.get_text()
    assert account.h2.get_text(' ', strip=True) == '2 · Your Rebrickable account Not connected'
    assert account.select_one('input[type=password][name=password]') and account.find('summary').get_text() == 'Paste a user token instead'
    assert page.select_one('.sr-foot span[aria-disabled=true]').get_text() == 'Next: choose what'
    assert page.select_one('.sr-foot a.sr-link').get_text() == 'Cancel'
    csrf = token(client)
    response = client.post('/manage/sync/rebrickable/connect', data={'csrf_token': csrf, 'username': 'u', 'password': 'synthetic-password-never-stored', 'next': 'connect'})
    assert response.location.endswith('/workbench/sync/rebrickable/connect')
    page = soup(client.get(response.location))
    assert 'synthetic-password-never-stored' not in page.decode() and TOKEN not in page.decode()
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Connected'
    assert page.select_one('.sr-foot a.bk-btn')['href'].endswith('/workbench/sync/rebrickable/choose')


def test_the_api_key_is_saved_tested_and_removed_from_step_1(client, remote, pair, monkeypatch):
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    page = soup(client.get('/workbench/sync/rebrickable/connect'))
    assert page.select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Not set'
    form = page.select_one('[data-rb-key] form')
    assert form.select_one('input[name="key:key"][type=password]') and form.button.get_text(strip=True) == 'Save and test'
    csrf = token(client)
    saved = client.post('/workbench/sync/rebrickable/key', data={'csrf_token': csrf, 'action': 'save', 'key:key': 'synthetic-stored-key-1'})
    assert saved.location.endswith('/workbench/sync/rebrickable/connect')
    page = soup(client.get(saved.location))
    assert 'Saved' in page.select_one('.bk-banner').get_text() and 'synthetic-stored-key-1' not in page.decode()
    assert page.select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Set' and page.select_one('[data-rb-key] .sr-masked')['readonly'] is not None
    assert [b.get_text(strip=True) for b in page.select('[data-rb-key] button')] == ['Test', 'Remove']
    client.post('/workbench/sync/rebrickable/key', data={'csrf_token': csrf, 'action': 'remove'})
    assert soup(client.get('/workbench/sync/rebrickable/connect')).select_one('[data-rb-key] .sr-tag').get_text(strip=True) == 'Not set'
    assert client.post('/workbench/sync/rebrickable/key', data={'csrf_token': csrf, 'action': 'nonsense'}).status_code == 400
    assert client.post('/workbench/sync/rebrickable/key', data={'action': 'test'}).status_code in (400, 403)


# --- step 2 -----------------------------------------------------------------------------------------------------------

def test_choose_step_needs_a_connection(client, remote):
    response = client.get('/workbench/sync/rebrickable/choose')
    assert response.status_code == 302 and response.location.endswith('/workbench/sync/rebrickable/connect')


def test_choose_step_shows_the_choices_in_the_frames_order_and_saves_them(client, remote, pair):
    csrf = connected(client, pair)
    page = soup(client.get('/workbench/sync/rebrickable/choose'))
    assert [h.get_text(strip=True) for h in page.select('.sr-card h2')] == ['Owned sets', 'Wishlist', 'Loose stock', 'Lost Parts', 'When both sides differ']
    assert [s.get_text(strip=True) for s in page.select('[data-rb-owned] .sr-seg span')] == ['Into Brick Work', 'Both ways', 'To Rebrickable', 'Off']
    assert [s.get_text(strip=True) for s in page.select('[data-rb-parts] .sr-seg span')] == ['Into Brick Work', 'Off']
    assert [i['value'] for i in page.select('input[name=owned]')] == ['1', '2', '9'] and not page.select('input[name=owned][checked]')
    assert [i['value'] for i in page.select('input[name=part_list]')] == ['31', '32'] and not page.select('input[name=part_list][checked]')
    assert page.select_one('[data-rb-lost] input[name=lost_dir][checked]')['value'] == 'into'      # the switch that was on before
    assert [i['value'] for i in page.select('input[name=lost_rule]')] == ['add_only', 'per_part', 'per_set', 'everything']
    assert page.select_one('input[name=lost_rule][checked]')['value'] == 'per_part'
    assert [o['value'] for o in page.select('select[name=send_rule] option')] == ['add_only', 'per_part', 'per_set', 'everything']
    assert 'Ask me each time' in page.select('.sr-card')[-1].get_text()
    assert page.select_one('.sr-foot a.sr-link')['href'].endswith('/workbench/sync/rebrickable/connect')
    assert [b.get_text(strip=True) for b in page.select('.sr-foot button')] == ['Save', 'Next: pick sets']
    response = choose(client, csrf, start='0', owned=['1'], wishlist='9', send_to='1', parts_dir='into', part_list=['31'], lost_dir='both',
                      lost_rule='everything', send_rule='per_set', owned_dir='into', wishlist_dir='to')
    assert response.location.endswith('/workbench/sync/rebrickable')
    with db_of(pair) as db:
        link = sync.status(db, 'rebrickable')['link']
        assert (link['owned'], link['wishlist'], link['send_to'], link['part_lists'], link['lost_parts']) == ([1], 9, 1, [31], True)
        assert sync_run.directions(db) == dict(owned='into', wishlist='to', parts='into', lost='both')
        assert admin.settings(db)['rebrickable_lost_parts_rule'] == 'everything'
        assert lost_parts_send.enabled(db) and lost_parts_send.send_rule(db) == 'per_set'
    again = soup(client.get('/workbench/sync/rebrickable/choose'))
    assert again.select_one('[data-rb-owned] input[name=owned_dir][checked]')['value'] == 'into'
    assert [i['value'] for i in again.select('input[name=part_list][checked]')] == ['31']
    assert again.select_one('input[name=lost_rule][checked]')['value'] == 'everything'
    assert again.select_one('select[name=send_rule] option[selected]')['value'] == 'per_set'


def test_lost_parts_out_is_off_by_default_and_a_bad_choice_saves_nothing(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        assert not lost_parts_send.enabled(db) and sync_run.directions(db)['lost'] == 'into'
    response = choose(client, csrf, start='0', owned_dir='sideways')
    assert response.location.endswith('/workbench/sync/rebrickable/choose')
    assert 'Choose a direction' in soup(client.get(response.location)).select_one('.bk-banner').get_text()
    response = choose(client, csrf, start='0', send_rule='everyone')
    assert 'Choose add_only' in soup(client.get(response.location)).select_one('.bk-banner').get_text()
    response = choose(client, csrf, start='0', wishlist='1', owned=['1'])           # the wishlist list cannot also be an owned list
    assert response.location.endswith('/workbench/sync/rebrickable/choose')
    with db_of(pair) as db:
        assert sync.status(db, 'rebrickable')['link'] == {}
        assert db.execute("SELECT count(*) FROM setting WHERE key LIKE 'rebrickable_%'").fetchone()[0] == 0
    assert client.post('/workbench/sync/rebrickable/choose', data=CHOICES).status_code in (400, 403)      # no token


def test_a_failed_read_of_the_lists_still_shows_the_step(client, remote, pair):
    connected(client, pair)
    remote.error = None
    from brickwork.core.sync import adapters
    original = adapters.transport
    adapters.transport = lambda r: (_ for _ in ()).throw(OSError('offline'))
    try:
        page = soup(client.get('/workbench/sync/rebrickable/choose'))
    finally:
        adapters.transport = original
    assert 'could not be reached' in page.select_one('.bk-banner').get_text() and page.select_one('input[name=owned_dir]')


# --- steps 3 to 6 -----------------------------------------------------------------------------------------------------

# --- steps 3 to 6 -----------------------------------------------------------------------------------------------------

def preview_of(client, run_id):
    return soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/preview'))


def rows_of(page):
    return {r.get('data-name', '').split(' ')[0]: r for r in page.select('[data-sy-row]')}


def apply_run(client, csrf, run_id, page=None, **extra):
    page = page or preview_of(client, run_id)
    return client.post(f'/workbench/sync/rebrickable/run/{run_id}/run', data={'csrf_token': csrf, **run_data(page, **extra)})


def copies(pair, number):
    with db_of(pair) as db:
        return db.execute("SELECT count(*) FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=? AND c.archived_at IS NULL", (number,)).fetchone()[0]


def test_pick_step_lists_the_sets_a_run_could_touch_in_the_five_modes(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        Coll(db).add_copy('1000-4')
    run_id = start(client, csrf)
    url = f'/workbench/sync/rebrickable/run/{run_id}/pick'
    page = soup(client.get(url))
    assert page.select_one('.sr-steps li[aria-current=step]').get_text(strip=True) == '3 Pick sets'
    assert [a.get_text(strip=True) for a in page.select('.sr-seg a')] == ['All linked', 'By list', 'By theme', 'By year', 'One by one']
    assert page.select_one('.sr-seg a[aria-current]').get_text(strip=True) == 'All linked' and not page.select('.sr-chip')
    assert [(i['value'], i.has_attr('checked')) for i in page.select('input[name=item]')] == [(v, True) for v in ('1', '2', '3', '4', '5')]
    assert page.select_one('[data-sr-count]').get_text(' ', strip=True) == '5 of 5 sets picked'
    first = page.select_one('.sr-pickrow')
    assert first.select_one('b').get_text() == 'Syn Castle Keep' and first.select_one('.sr-pickid span').get_text() == '1000-1 · Castle · 1990'
    by_list = soup(client.get(url + '?by=list'))
    assert [(c['data-sr-chip'], c.select_one('.mono').get_text()) for c in by_list.select('.sr-chip')] == [('List 1', '2'), ('List 2', '1'), ('List 9', '1')]
    assert 'Rebrickable: List 1' in by_list.select_one('.sr-pickrow').get_text()
    assert by_list.select_one('input[name=keep_list_names][type=checkbox]').has_attr('checked') and by_list.find('h2', string='Keep the list names')
    assert [(c['data-sr-chip'], c.select_one('.mono').get_text()) for c in soup(client.get(url + '?by=theme')).select('.sr-chip')] == [('Castle', '4'), ('Gear', '1')]
    assert [c['data-sr-chip'] for c in soup(client.get(url + '?by=year')).select('.sr-chip')] == ['2026', '1993', '1992', '1991', '1990']
    one = soup(client.get(url + '?by=one'))
    assert not one.select('input[name=item][checked]') and not one.select('.sr-chip')
    assert client.get(url + '?by=sideways').status_code == 404
    assert client.get('/workbench/sync/rebrickable/run/' + 'f' * 32 + '/pick').location.endswith('/workbench/sync/rebrickable')


def test_picking_sets_narrows_the_preview_and_the_run(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        Coll(db).add_copy('1000-4')
    run_id = start(client, csrf)
    response = client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1', '4']})
    assert response.location.endswith(f'/run/{run_id}/preview')
    page = preview_of(client, run_id)
    assert sorted(rows_of(page)) == ['1000-1', '1000-4', 'rb-only-9'] and page.select_one('.sr-promise')      # a number that names no set stays listed, as not matched
    assert page.select_one('.sr-steps li[aria-current=step]').get_text(strip=True) == '4 Preview'
    assert [b.get_text(strip=True) for b in page.select('.sr-foot button')] == ['Run']
    assert page.select_one('[data-sy-total]')['data-sy-of'] == '2'                  # the script says "2 of 2 chosen" and "Run 2 changes"
    assert client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['99']}).location.endswith('/pick')     # not one of the sets
    assert apply_run(client, csrf, run_id, page).location.endswith(f'/run/{run_id}/result')
    assert copies(pair, '1000-1') == 2 and copies(pair, '1000-2') == 0 and copies(pair, '1000-3') == 0
    assert remote.lists[1]['1000-4'] == 1
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    assert [h.get_text(' ', strip=True) for h in page.select('.sr-card h2')] == ['Here in Brick Work 2 changed', 'On Rebrickable 1 sent']
    assert '2 sets added' in page.select_one('[data-rb-here]').get_text()
    assert page.select_one('[data-rb-here] button').get_text(strip=True) == 'Undo this run'
    assert 'cannot be undone here' in page.select_one('[data-rb-there] .sr-info').get_text()
    assert [a.get_text(strip=True) for a in page.select('.sr-foot a')] == ['Open sync log', 'Done']
    with db_of(pair) as db:
        assert sync_run.picked_ids(sync_run.load(db, run_id)[0]) == {1, 4}
    assert client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['99']}).location.endswith('/pick')      # an applied run is not picked again
    assert client.get(f'/workbench/sync/rebrickable/run/{run_id}/pick').location.endswith('/result')


def test_an_unticked_row_changes_nothing_and_a_second_post_does_not_run_again(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    data = run_data(page)
    data.pop('choice:owned:1')
    first = client.post(f'/workbench/sync/rebrickable/run/{run_id}/run', data={'csrf_token': csrf, **data})
    assert first.location.endswith('/result') and copies(pair, '1000-1') == 0 and copies(pair, '1000-2') == 1
    assert client.post(f'/workbench/sync/rebrickable/run/{run_id}/run', data={'csrf_token': csrf, **run_data(page)}).location.endswith('/result')
    assert copies(pair, '1000-1') == 0                              # the run was already applied: nothing more happened
    assert preview_of_redirect(client, run_id).endswith('/result')


def preview_of_redirect(client, run_id):
    return client.get(f'/workbench/sync/rebrickable/run/{run_id}/preview').location


def test_an_offered_choice_is_checked_and_an_expired_run_goes_back_to_the_page(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    response = client.post(f'/workbench/sync/rebrickable/run/{run_id}/run', data={'csrf_token': csrf, 'choice:owned:1': 'remove'})
    assert response.location.endswith('/preview') and 'Choose one of the offered changes' in soup(client.get(response.location)).select_one('.bk-banner').get_text()
    assert copies(pair, '1000-1') == 0
    gone = client.post('/workbench/sync/rebrickable/run/' + 'e' * 32 + '/run', data={'csrf_token': csrf})
    assert gone.location.endswith('/preview') or gone.status_code == 302
    assert client.get('/workbench/sync/rebrickable/run/' + 'e' * 32 + '/result').location.endswith('/workbench/sync/rebrickable')
    assert client.get(f'/workbench/sync/rebrickable/run/{run_id}/result').location.endswith('/preview')
    assert client.post(f'/workbench/sync/rebrickable/run/{run_id}/run', data={'choice:owned:1': 'pull'}).status_code in (400, 403)


def test_a_set_changed_in_both_places_is_a_choice_of_three(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id)                                     # 1000-1 twice and 1000-2 once come in; the baseline is now 2 and 1
    remote.lists[1]['1000-1'] = 5                                       # Rebrickable raised it, and here one copy went
    with db_of(pair) as db:
        copy_id = db.execute("SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-1' AND c.archived_at IS NULL LIMIT 1").fetchone()[0]
        db.execute("UPDATE copy SET archived_at='2026-11-20T10:00:00.000Z' WHERE id=?", (copy_id,))
        db.commit()
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    card = page.select_one('[data-rb-conflicts]')
    assert card.h2.get_text(' ', strip=True) == 'Changed in both places 1' and 'since the last run' in card.get_text()
    assert [(l.b.get_text(), l.select_one('.mono').get_text()) for l in card.select('.sr-choice label')] == [
        ('Keep 1 here', 'Nothing sent'), ('Take 5 from Rebrickable', 'Brick Work becomes 5'), ('Send 1 to Rebrickable', 'Rebrickable becomes 1')]
    assert [i['value'] for i in card.select('input[type=radio]')] == ['keep', 'take', 'send'] and card.select_one('input[checked]')['value'] == 'keep'
    assert 'Checks, storage and notes stay here either way; only quantities are compared.' in card.get_text()
    assert apply_run(client, csrf, run_id, page).status_code == 302
    assert copies(pair, '1000-1') == 1 and remote.lists[1]['1000-1'] == 5          # Keep: neither side changed
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    apply_run(client, csrf, run_id, page, **{'choice:owned:1': 'send'})
    assert remote.lists[1]['1000-1'] == 1
    remote.lists[1]['1000-1'] = 6
    with db_of(pair) as db:
        Coll(db).add_copy('1000-1')
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id, **{'choice:owned:1': 'take'})
    assert copies(pair, '1000-1') == 6


def test_a_set_gone_here_is_kept_unless_chosen(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id)
    with db_of(pair) as db:
        db.execute("UPDATE copy SET archived_at='2026-11-20T10:00:00.000Z' WHERE item_id=(SELECT id FROM item WHERE born_key='1000-2')")
        db.commit()
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    row = rows_of(page)['1000-2']
    assert [(i['value'], i.has_attr('checked')) for i in row.select('input[type=radio]')] == [('keep', True), ('pull', False), ('remove', False)]
    assert [l.b.get_text() for l in row.select('label')] == ['Keep 0 here', 'Add back here', 'Remove from Rebrickable']
    apply_run(client, csrf, run_id, page)
    assert copies(pair, '1000-2') == 0 and remote.lists[1]['1000-2'] == 1          # nothing is added back or removed unless chosen
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id, **{'choice:owned:2': 'remove'})
    assert '1000-2' not in remote.lists[1]


def test_lost_parts_come_in_on_the_picked_sets_and_a_copy_is_chosen_where_there_are_several(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        one = copy_of(db, '1000-1')
        copy_of(db, '2070-1')
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1), raw('2070-1', '3001', 4, 1, number=2)]
    remote.lists[1]['1000-1'] = 1
    run_id = start(client, csrf, lost_dir='into')
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1']})
    page = preview_of(client, run_id)
    card = page.select_one('[data-rb-lost-in]')
    assert card.h2.get_text(' ', strip=True) == 'Lost Parts 1' and '1 added' in card.select_one('.sy-lost-summary').get_text()
    assert card.select_one('input[name=lost]')['value'] == '1000-1' and 'Mark 1 part' in card.get_text()
    assert not card.select('select[data-sy-pick]')                       # the second set is not picked: its copies are not asked about
    apply_run(client, csrf, run_id, page)
    with db_of(pair) as db:
        assert marks(db, one) == {('3001', '4', False): 1}
    run_id = start(client, csrf, lost_dir='into')
    page = preview_of(client, run_id)
    pick = page.select_one('[data-rb-lost-in] select[data-sy-pick]')
    assert pick['name'] == 'copy:2070-1' and page.select_one('[data-rb-lost-in] .sy-lost-row .sy-state').get_text(' ', strip=True).startswith('Choose a copy')
    assert 'Run' in [b.get_text(strip=True) for b in page.select('.sr-foot button')]


def test_lost_parts_go_out_with_the_rule_and_a_row_over_one_copys_line_is_not_sent(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
        copy_of(db, '1000-2', marks=[('3001', '4', 2)])
        copy_of(db, '1000-2', marks=[('3001', '4', 2)])
    remote.lists[1] = {'1000-1': 1, '1000-2': 2}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1), raw('1000-2', '3023', 15, 1, number=2)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='add_only')
    page = preview_of(client, run_id)
    card = page.select_one('[data-rb-lost-out]')
    assert card.h2.get_text(' ', strip=True) == 'Lost Parts to Rebrickable 2'        # 1000-1 is sent, 1000-2 is listed as not sent
    assert len(card.select('input[name=lostsend]')) == 1
    assert 'Rule: Add only' in card.get_text()
    tick = card.select_one('input[name=lostsend]')
    assert tick['value'] == lost_parts_send.row_key('1000-1', '3001', 4, False) and '1 there to 3' in card.get_text()
    assert not tick.has_attr('checked')                              # a larger count is offered, not ticked: only an added part is ticked
    assert page.select_one('[data-rb-before]')
    apply_run(client, csrf, run_id, page, lostsend=[tick['value']])
    assert [(m, d) for m, p, d in remote.lost_writes] == [('POST', 'inv_part_id=1&lost_quantity=2')]
    result = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    assert result.select_one('[data-rb-there] .sr-tag').get_text(strip=True) == '1 sent'
    with db_of(pair) as db:
        send = db.execute("SELECT new_value FROM event WHERE entity_kind='sync' AND field='send' ORDER BY id DESC").fetchone()[0]
        assert json.loads(send)['counts'] == {'sent': 1}


def test_a_lost_parts_row_over_one_copys_line_shows_its_reason_and_cannot_be_posted(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 2}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='add_only')
    page = preview_of(client, run_id)
    card = page.select_one('[data-rb-lost-out]')
    assert not card.select('input[name=lostsend]')
    row = card.select_one('.sr-prow')
    assert 'Not sent' in row.get_text() and "The copies together miss 6, but one copy's line holds 4" in row.get_text()
    key = lost_parts_send.row_key('1000-1', '3001', 4, False)
    apply_run(client, csrf, run_id, page, lostsend=[key])
    assert remote.lost_writes == []                                 # a posted key of a row that is not sent is dropped on the server too
    with db_of(pair) as db:
        row = sync_run.load(db, run_id)[0]['lost_out']['rows'][0]
        assert row['tickable'] is False and 'one copy' in row['reason']


def test_a_lost_parts_send_that_fails_is_listed_and_a_budget_or_key_stop_keeps_the_rest(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3), ('3023', '15', 1)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off')
    remote.fail_writes = True
    apply_run(client, csrf, run_id, lostsend=[lost_parts_send.row_key('1000-1', '3001', 4, False)])
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    assert page.select_one('[data-rb-there] .sr-tag').get_text(strip=True) == '1 failed'
    with db_of(pair) as db:
        stage = sync_run.load(db, run_id)[0]['stages']['lost_out']
        assert stage['status'] == 'partial' and stage['counts']['failed'] >= 1


def test_loose_stock_comes_in_by_part_list_and_one_undo_takes_the_run_and_its_parts_back(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf, parts_dir='into', part_list=['31'])
    page = preview_of(client, run_id)
    card = page.select_one('[data-rb-parts]')
    assert card.h2.get_text(' ', strip=True) == 'Loose stock 2'
    assert [i['value'] for i in card.select('input[name=part]')] == ['31:' + k.split(':', 1)[1] for k in [i['value'] for i in card.select('input[name=part]')]]
    assert [o.get_text() for o in card.select('select[name=lot_all] option')] == ['One lot per part list']
    assert 'Add 5 here' in card.get_text() and 'from Bin A' in card.get_text()
    apply_run(client, csrf, run_id, page)
    with db_of(pair) as db:
        assert db.execute("SELECT count(*) FROM stock s JOIN lot l ON l.id=s.lot_id WHERE l.name='Bin A' AND s.archived_at IS NULL").fetchone()[0] == 2
        events = json.loads(db.execute("SELECT new_value FROM event WHERE entity_kind='sync' AND field='run'").fetchone()[0])['events']
        assert len(events) == 2
    result = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    assert '7 loose pieces added from part lists' in result.select_one('[data-rb-here]').get_text()
    site = soup(client.get('/workbench/sync/rebrickable'))
    assert [r.select_one('b').get_text()[:3] for r in site.select('[data-rb-runs] .sr-run')] == ['Run', 'Run']
    undo = [f for f in site.select('[data-rb-runs] form') if f['action'].endswith('/undo')]
    assert len(undo) == 1                                           # the newest run only
    response = client.post('/workbench/sync/rebrickable/undo', data={'csrf_token': csrf, 'event': undo[0].select_one('input[name=event]')['value']})
    assert response.location.endswith('/workbench/sync/rebrickable')
    with db_of(pair) as db:
        assert copies(pair, '1000-1') == 0
        assert db.execute("SELECT count(*) FROM stock WHERE archived_at IS NULL AND kind='part'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM event_undo").fetchone()[0] >= 2
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    assert page.select_one('[data-rb-here]').get_text().endswith('This run was undone.') and not page.select_one('[data-rb-here] button')


def test_a_put_in_lot_is_used_for_every_loose_row(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        db.execute("INSERT INTO lot(id, name, created_at, updated_at) VALUES('lot-x', 'Sorted tub', '2026-11-01T00:00:00.000Z', '2026-11-01T00:00:00.000Z')")
        db.commit()
    run_id = start(client, csrf, parts_dir='into', part_list=['31'])
    page = preview_of(client, run_id)
    assert [o.get_text() for o in page.select('select[name=lot_all] option')] == ['One lot per part list', 'Lot · Sorted tub']
    apply_run(client, csrf, run_id, page, lot_all='lot-x')
    with db_of(pair) as db:
        assert db.execute("SELECT count(*) FROM stock WHERE lot_id='lot-x' AND archived_at IS NULL").fetchone()[0] == 2


def test_list_names_are_offered_first_and_a_renamed_list_follows_its_choice(client, remote, pair):
    csrf = connected(client, pair)
    apply_run(client, csrf, start(client, csrf))
    remote.names = {1: 'Home collection'}
    page = preview_of(client, start(client, csrf))
    card = page.select_one('[data-rb-lists]')
    assert card.h2.get_text() == 'Rebrickable lists' and card.select_one('b').get_text() == 'List 1'
    line = card.select_one('.sr-listline')
    assert 'Renamed at Rebrickable to “Home collection”; the source detail of 2 sets changes' in line.get_text()
    assert [o['value'] for o in line.select('option')] == ['rename', 'keep'] and line.select_one('option[selected]')['value'] == 'rename'
    run_id = page.select_one('form.sr-preview')['action'].split('/run/')[1].split('/')[0]
    apply_run(client, csrf, run_id, page, **{'list:1': 'keep'})
    with db_of(pair) as db:
        from brickwork.store4 import origins
        assert origins.lists_of(db, 'rebrickable')['1'][0] == 'List 1'


def test_turning_the_list_names_off_on_the_pick_step_reads_the_pull_again(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    with db_of(pair) as db:
        before = sync_run.load(db, run_id)[0]['pull']
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1'], 'keep_present': '1', 'keep_list_names': ['0']})
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        assert run['pull'] != before and sync.load_plan(db, run['pull'])['lists']['keep'] is False
        assert run['picked'] == [1]


def test_a_failed_send_is_listed_with_a_retry_and_the_page_keeps_the_waiting_rows(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        Coll(db).add_copy('1000-4')
    run_id = start(client, csrf, owned_dir='to', wishlist_dir='off')
    remote.fail_sets = True
    apply_run(client, csrf, run_id)
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    there = page.select_one('[data-rb-there]')
    assert there.select_one('.sr-tag.sr-hatch').get_text(strip=True) == '1 failed'
    assert there.select_one('.sr-prow b').get_text() == 'Syn Castle Wall' and there.select_one('button').get_text(strip=True) == 'Retry'
    assert page.select_one('.sr-steps li[aria-current=step]').get_text(strip=True) == '6 Result'
    site = soup(client.get('/workbench/sync/rebrickable'))
    run = site.select_one('[data-rb-runs] .sr-run')
    assert 'Waiting for you' in run.select_one('.sr-tag').get_text() and [b.get_text(strip=True) for b in run.select('button')] == ['Retry']
    assert '1 row to Rebrickable still waiting.' in site.select_one('[data-rb-runs]').get_text()
    remote.fail_sets = False
    retry = client.post('/manage/sync/rebrickable/send', data={'csrf_token': csrf})
    assert '/manage/sync/rebrickable/plan/' in retry.location


def test_a_read_only_instance_shows_no_buttons_and_refuses_every_write(app4, client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    app4.config['BW_READ_ONLY'] = True
    try:
        site = soup(client.get('/workbench/sync/rebrickable'))
        assert not site.select('.sr-headrow form') and not site.select('[data-rb-account] form')
        page = preview_of(client, run_id)
        assert not page.select('.sr-foot button')
        for url, data in ((f'/workbench/sync/rebrickable/run/{run_id}/run', {}), (f'/workbench/sync/rebrickable/run/{run_id}/pick', {'item': ['1']}),
                          ('/workbench/sync/rebrickable/choose', CHOICES), ('/workbench/sync/rebrickable/start', {}), ('/workbench/sync/rebrickable/undo', {'event': '1'}),
                          ('/workbench/sync/rebrickable/key', {'action': 'test'})):
            assert client.post(url, data={'csrf_token': csrf, **data}).status_code == 403, url
    finally:
        app4.config['BW_READ_ONLY'] = False


def test_start_a_sync_uses_the_saved_choices(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0', owned_dir='into', wishlist_dir='off')
    response = client.post('/workbench/sync/rebrickable/start', data={'csrf_token': csrf})
    assert response.status_code == 302 and '/pick' in response.location
    page = preview_of(client, re.search(r'/run/([0-9a-f]{32})/', response.location)[1])
    assert sorted(rows_of(page)) == ['1000-1', '1000-2', '10018247-1', 'rb-only-9']          # the wishlist is off: 1000-3 is not in it
    assert client.post('/workbench/sync/rebrickable/start', data={}).status_code in (400, 403)


def test_start_reports_a_failed_read_and_stays_on_the_page(client, remote, pair, monkeypatch):
    csrf = connected(client, pair)
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters, 'transport', lambda r: (_ for _ in ()).throw(OSError('offline')))
    response = client.post('/workbench/sync/rebrickable/start', data={'csrf_token': csrf})
    assert response.location.endswith('/workbench/sync/rebrickable')
    assert 'could not be reached' in soup(client.get(response.location)).select_one('.bk-banner').get_text()


def test_a_lower_count_there_is_offered_only_for_a_set_lowered_here_or_when_only_sending(client, remote, pair):
    csrf = connected(client, pair)
    apply_run(client, csrf, start(client, csrf))                      # 1000-1 comes in twice
    with db_of(pair) as db:
        db.execute("UPDATE copy SET archived_at='2026-11-20T10:00:00.000Z' WHERE id=(SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-1' AND c.archived_at IS NULL LIMIT 1)")
        db.commit()
    page = preview_of(client, start(client, csrf))
    row = rows_of(page)['1000-1']
    assert [l.b.get_text() for l in row.select('label')] == ['Keep 1 here', 'Add back here', 'Quantity 2 to 1']
    assert [i['value'] for i in row.select('input[type=radio]')] == ['keep', 'pull', 'send'] and row.select_one('input[checked]')['value'] == 'keep'
    page = preview_of(client, start(client, csrf, owned_dir='to', wishlist_dir='off'))      # only sending: the plain send row, as the old Review and send had it
    row = rows_of(page)['1000-1']
    box = row.select_one('input[name="choice:owned:1"]')
    assert box['type'] == 'checkbox' and box['value'] == 'send' and box.has_attr('checked') and 'Quantity 2 to 1' in row.get_text()


def test_keeping_the_list_names_on_the_pick_step_does_not_read_the_pull_again(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    with db_of(pair) as db:
        before = sync_run.load(db, run_id)[0]['pull']
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1'], 'keep_present': '1', 'keep_list_names': ['0', '1']})
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        assert run['pull'] == before and sync.load_plan(db, before)['lists']['keep'] is True and run['picked'] == [1]
        assert sync.status(db, 'rebrickable')['link']['keep_list_names'] is True


def test_a_copy_pick_alone_marks_the_lost_parts_of_that_set(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '2070-1')
        copies, row = two_copies_line(db)
    remote.lost = [row]
    run_id = start(client, csrf, lost_dir='into', owned_dir='off', wishlist_dir='off')
    page = preview_of(client, run_id)
    assert page.select_one('[data-rb-lost-in] select[data-sy-pick]')['name'] == 'copy:2070-1' and not page.select('[data-rb-lost-in] input[name=lost]')
    apply_run(client, csrf, run_id, page, **{'copy:2070-1': copies[1]})         # nothing else ticked: the chosen copy is the tick
    with db_of(pair) as db:
        assert marks(db, copies[1]) and not marks(db, copies[0])


def test_retry_sends_again_only_the_rows_that_did_not_go_through(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        Coll(db).add_copy('1000-4')
    run_id = start(client, csrf, owned_dir='to', wishlist_dir='off')
    remote.fail_sets = True
    apply_run(client, csrf, run_id)
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    form = page.select_one('[data-rb-there] form')
    assert form['action'].endswith(f'/run/{run_id}/retry') and '1000-4' not in remote.lists[1]
    remote.fail_sets = False
    response = client.post(form['action'], data={'csrf_token': csrf})
    assert response.location.endswith(f'/run/{run_id}/result') and remote.lists[1]['1000-4'] == 1
    page = soup(client.get(response.location))
    assert page.select_one('[data-rb-there] .sr-tag').get_text(strip=True) == '1 sent' and not page.select('[data-rb-there] form')
    assert client.post(form['action'], data={'csrf_token': csrf}).location.endswith('/result')          # nothing left to retry: said, not sent again
    assert client.post(form['action'], data={}).status_code in (400, 403)


def test_a_lost_parts_send_is_a_row_of_the_log_without_a_retry_that_would_open_the_set_send(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off')
    remote.fail_writes = True
    apply_run(client, csrf, run_id, lostsend=[lost_parts_send.row_key('1000-1', '3001', 4, False)])
    site = soup(client.get('/workbench/sync/rebrickable'))
    run = site.select_one('[data-rb-runs] .sr-run')
    assert run.select_one('span').get_text().startswith('Lost Parts: ') and not run.select('button')
    with db_of(pair) as db:
        assert sync_run.load(db, run_id)[0]['lost_out']['rows'][0].get('outcome') == 'failed'


# --- review round 1 ---------------------------------------------------------------------------------------------------

def test_undo_takes_only_a_rebrickable_pull_and_reads_ids_as_ascii_digits(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id)
    with db_of(pair) as db:
        other = db.execute("INSERT INTO event(at, via, entity_kind, entity_id, field, new_value) VALUES ('2026-11-20T10:00:00Z', 'app', 'sync', '1', 'receipt', ?)",
                           (json.dumps({'source': 'brickset', 'counts': {}}),)).lastrowid
        ordinary = db.execute("INSERT INTO event(at, via, entity_kind, entity_id, field, new_value) VALUES ('2026-11-20T10:00:00Z', 'app', 'wish', 'x', 'quantity', '2')").lastrowid
        db.commit()
    for event in (other, ordinary, 999999):
        assert client.post('/workbench/sync/rebrickable/undo', data={'csrf_token': csrf, 'event': str(event)}).status_code == 404
    for bad in ('²', '', '1' * 30, 'x'):
        assert client.post('/workbench/sync/rebrickable/undo', data={'csrf_token': csrf, 'event': bad}).status_code == 400
    assert copies(pair, '1000-1') == 2                              # nothing was undone
    response = choose(client, csrf, start='0', owned=['1', '²', '2'], wishlist='²')       # ignored, never a 500
    assert response.status_code == 302
    with db_of(pair) as db:
        link = sync.status(db, 'rebrickable')['link']
        assert link['owned'] == [1, 2] and link.get('wishlist') is None


def test_a_run_is_claimed_and_a_second_post_changes_nothing(client, remote, pair):
    from werkzeug.datastructures import MultiDict
    csrf = connected(client, pair)
    with db_of(pair) as db:
        Coll(db).add_copy('1000-4')
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    assert apply_run(client, csrf, run_id, page).location.endswith('/result')
    sent = list(remote.calls)
    assert apply_run(client, csrf, run_id, page).location.endswith('/result')                # the second post: the run as it is
    assert remote.calls == sent and copies(pair, '1000-1') == 2
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        assert run['applied'] and 'applying' not in run
        assert sync_run.apply(db, run_id, MultiDict())['applied'] == run['applied']
        assert len(db.execute("SELECT 1 FROM event WHERE entity_kind='sync' AND field='run'").fetchall()) == 1
        assert (sync._root(db) / (run_id + '.lock')).exists()


def test_a_run_that_is_applying_or_was_interrupted_is_not_applied_again(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        run['applying'] = '2026-11-24T08:00:00+00:00'
        sync._store_plan(db, run)
    calls = len(remote.calls)
    response = apply_run(client, csrf, run_id, page)
    assert response.location.endswith('/workbench/sync/rebrickable')
    assert 'already running, or was interrupted' in soup(client.get(response.location)).select_one('.bk-banner').get_text()
    assert copies(pair, '1000-1') == 0 and len(remote.calls) == calls
    for url in ('/preview', '/result'):
        assert client.get(f'/workbench/sync/rebrickable/run/{run_id}' + url).location.endswith('/workbench/sync/rebrickable')
    assert client.get(f'/workbench/sync/rebrickable/run/{run_id}/pick').location.endswith('/result')
    assert client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1']}).location.endswith('/pick')


def test_a_lost_parts_send_writes_each_call_into_the_run(client, remote, pair, monkeypatch):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3), ('3023', '15', 1)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off')
    seen = []
    real = adapters.RebrickableUser.lost_part_add

    def watch(self, inv, quantity):
        reply = real(self, inv, quantity)
        with db_of(pair) as db:
            seen.append(len(sync_run.load(db, run_id)[0].get('lost_calls', ())))      # before this call is noted
        return reply
    monkeypatch.setattr(adapters.RebrickableUser, 'lost_part_add', watch)
    apply_run(client, csrf, run_id, lostsend=[lost_parts_send.row_key('1000-1', '3001', 4, False)])
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        assert seen == [0] and run['lost_calls'] == [['add', 1, 2]]


def test_saving_step_2_after_a_failed_read_of_the_lists_keeps_the_links(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0', parts_dir='into', part_list=['31'])
    with db_of(pair) as db:
        link = sync.status(db, 'rebrickable')['link']
        assert link['owned'] == [1, 2] and link['part_lists'] == [31]
        names = sync_run._saved_names(db)
    kept_transport = adapters.transport
    adapters.transport = lambda r: (_ for _ in ()).throw(OSError('offline'))
    try:
        page = soup(client.get('/workbench/sync/rebrickable/choose'))
    finally:
        adapters.transport = kept_transport
    assert page.select_one('input[name=set_lists_read]')['value'] == '0'
    data = {'csrf_token': csrf, 'set_lists_read': '0', 'part_lists_read': '0', 'owned_dir': 'into', 'wishlist_dir': 'off', 'parts_dir': 'into', 'lost_dir': 'off', 'wish_list': 'default',
            'lost_rule': 'everything', 'send_rule': 'per_set', 'start': '0'}               # the form carried no list, no name
    assert client.post('/workbench/sync/rebrickable/choose', data=data).location.endswith('/workbench/sync/rebrickable')
    with db_of(pair) as db:
        kept = sync.status(db, 'rebrickable')['link']
        assert (kept['owned'], kept['wishlist'], kept['send_to'], kept['part_lists']) == ([1, 2], 9, 1, [31])
        assert sync_run.directions(db) == dict(owned='into', wishlist='off', parts='into', lost='off')
        assert sync_run._saved_names(db) == names and admin.settings(db)['rebrickable_lost_parts_rule'] == 'everything'
    data.update(set_lists_read='1', part_lists_read='1')                                 # a form that did read them and ticked none clears them
    client.post('/workbench/sync/rebrickable/choose', data=data)
    with db_of(pair) as db:
        assert sync.status(db, 'rebrickable')['link']['owned'] == []


def test_the_lost_parts_send_switch_and_rule_are_saved_through_the_settings(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0', lost_dir='to', send_rule='per_part')
    with db_of(pair) as db:
        shown = admin.settings(db)
        assert shown['rebrickable_lost_parts_send'] is True and shown['rebrickable_lost_parts_send_rule'] == 'per_part'
        assert db.execute("SELECT count(*) FROM event WHERE entity_kind='settings' AND field='save'").fetchone()[0] >= 1       # the settings' own, undoable save
    choose(client, csrf, start='0', lost_dir='into')
    with db_of(pair) as db:
        assert admin.settings(db)['rebrickable_lost_parts_send'] is False


def test_a_kind_that_is_off_is_not_a_candidate_and_a_send_reason_does_not_hide_a_pullable_row(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf, wishlist_dir='off', send_to='')           # two owned lists and none to send to
    with db_of(pair) as db:
        assert 3 not in {c['item_id'] for c in sync_run.load(db, run_id)[0]['candidates']}        # 1000-3 is only on the wishlist
    page = preview_of(client, run_id)
    row = rows_of(page)['1000-1']
    assert row.select_one('input[name="choice:owned:1"]')['value'] == 'pull' and row['data-state'] == 'into'
    assert 'Not sent: Link one owned Rebrickable list to send to' in row.get_text()
    assert rows_of(page).get('1000-3') is None


def test_partial_picks_count_only_their_own_lost_parts(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        one = copy_of(db, '1000-1')
        two = copy_of(db, '1000-2')
    remote.lists[1] = {'1000-1': 1, '1000-2': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1), raw('1000-2', '3001', 4, 1, number=2)]
    run_id = start(client, csrf, lost_dir='into', owned_dir='into', wishlist_dir='off')
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1']})
    page = preview_of(client, run_id)
    card = page.select_one('[data-rb-lost-in]')
    assert [i['value'] for i in card.select('input[name=lost]')] == ['1000-1']
    assert card.h2.get_text(' ', strip=True) == 'Lost Parts 1' and card.select_one('.sy-lost-summary').get_text().startswith('1 added')
    apply_run(client, csrf, run_id, page)
    with db_of(pair) as db:
        assert marks(db, one) and not marks(db, two)


def test_lost_parts_of_a_set_that_is_not_pulled_are_not_offered_ticked(client, remote, pair):
    csrf = connected(client, pair)
    remote.lost = [raw('1000-2', '3001', 4, 1, number=1)]                  # 1000-2 is on Rebrickable once and has no copy here
    page = preview_of(client, start(client, csrf, lost_dir='into', owned_dir='off', wishlist_dir='off'))
    card = page.select_one('[data-rb-lost-in]')
    assert not card.select('input[name=lost]') and 'not pulled in this run' in card.get_text()
    page = preview_of(client, start(client, csrf, lost_dir='into', owned_dir='into', wishlist_dir='off'))
    assert page.select_one('[data-rb-lost-in] input[name=lost]')['value'] == '1000-2'       # it comes in with its copy, as before


def test_the_result_counts_cleared_marks_and_renames_and_lists_skipped_lost_parts(client, remote, pair):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_id = copy_of(db, '1000-1', marks=[('3023', '15', 2)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='into', owned_dir='into', wishlist_dir='off', lost_rule='per_set')
    page = preview_of(client, run_id)
    with db_of(pair) as db:                                              # the copy changes between the preview and the run
        db.execute("UPDATE copy_part SET missing=1 WHERE copy_id=? AND missing>0", (copy_id,))
        db.commit()
    apply_run(client, csrf, run_id, page)
    text = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result')).select_one('[data-rb-here]').get_text(' ', strip=True)
    assert 'left out' in text                                           # skipped Lost Parts are listed, with their reason
    run_id = start(client, csrf, lost_dir='into', owned_dir='into', wishlist_dir='off', lost_rule='per_set')
    apply_run(client, csrf, run_id)
    text = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result')).select_one('[data-rb-here]').get_text(' ', strip=True)
    assert '1 mark cleared' in text
    remote.names = {1: 'Home collection'}
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id)
    assert 'list name' in soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result')).select_one('[data-rb-here]').get_text()


def test_a_budget_pause_shows_as_waiting_not_failed(client, remote, pair, monkeypatch):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off')

    def pause(self, inv, quantity):
        raise base.WaitingForBudget(None, '2026-11-25T00:00:00+00:00')
    monkeypatch.setattr(adapters.RebrickableUser, 'lost_part_add', pause)
    apply_run(client, csrf, run_id, lostsend=[lost_parts_send.row_key('1000-1', '3001', 4, False)])
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    there = page.select_one('[data-rb-there]')
    assert [t.get_text(strip=True) for t in there.select('.sr-tag')] == ['1 waiting'] and 'the daily budget is used up' in there.get_text()
    assert 'failed' not in page.select_one('.sr-head p').get_text() and '1 waiting' in page.select_one('.sr-head p').get_text()
    with db_of(pair) as db:
        assert sync_run.load(db, run_id)[0]['stages']['lost_out']['counts'] == dict(sent=0, failed=0, waiting=1)


def test_the_preview_shows_part_rows_that_could_not_be_matched_and_a_renamed_list_counts_as_chosen(client, remote, pair):
    csrf = connected(client, pair)
    page = preview_of(client, start(client, csrf, parts_dir='into', part_list=['31'], owned_dir='off', wishlist_dir='off'))
    assert 'No part with this number here' in page.select_one('[data-rb-parts]').get_text()
    apply_run(client, csrf, start(client, csrf))                                  # records the list names
    remote.names = {1: 'Home collection'}
    page = preview_of(client, start(client, csrf, owned_dir='off', wishlist_dir='off', lost_dir='into'))
    select = page.select_one('[data-rb-lists] select[data-sy-listpick]')
    assert select['name'] == 'list:1' and page.select_one('[data-sy-total]')['data-sy-of'] == '1'      # the rename is one of the choices to make


def test_the_page_prefers_the_names_a_pull_recorded(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0')
    page = soup(client.get('/workbench/sync/rebrickable'))
    assert page.select_one('[data-rb-what] td:nth-child(3)').get_text() == '2 set lists: Main collection, Bought 2026'      # what step 2 showed
    apply_run(client, csrf, start(client, csrf))
    page = soup(client.get('/workbench/sync/rebrickable'))
    assert page.select_one('[data-rb-what] td:nth-child(3)').get_text() == '2 set lists: List 1, List 2'                  # what the pull recorded


def test_a_conflict_that_was_kept_comes_back_as_the_same_card(client, remote, pair):
    csrf = connected(client, pair)
    apply_run(client, csrf, start(client, csrf))                          # baseline: 1000-1 twice
    remote.lists[1]['1000-1'] = 5                                         # Rebrickable raised it, one copy went here: changed in both places
    with db_of(pair) as db:
        db.execute("UPDATE copy SET archived_at='2026-11-20T10:00:00.000Z' WHERE id=(SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-1' AND c.archived_at IS NULL LIMIT 1)")
        db.commit()
    remote.lists[2]['1000-4'] = 1                                         # something else comes in, so the pull is applied and resets the baseline
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    assert page.select_one('[data-rb-conflicts] input[checked]')['value'] == 'keep'
    apply_run(client, csrf, run_id, page)
    assert copies(pair, '1000-4') == 1 and copies(pair, '1000-1') == 1
    page = preview_of(client, start(client, csrf))
    card = page.select_one('[data-rb-conflicts]')                         # #686: the Keep is remembered, the pull's baseline reset does not end it
    assert card.h2.get_text(' ', strip=True) == 'Changed in both places 1'
    assert [i['value'] for i in card.select('input[type=radio]')] == ['keep', 'take', 'send'] and card.select_one('input[checked]')['value'] == 'keep'
    assert run_data(page)['choice:owned:1'] == ['keep']                   # Apply all keeps it: nothing is overwritten


# --- review round 3 ---------------------------------------------------------------------------------------------------

def test_the_needs_key_line_keeps_its_text_and_points_a_rebrickable_key_to_step_1(app4):
    with app4.test_request_context('/'):
        template = app4.jinja_env.from_string("{% from 'web/toni/web/bw_first_run.html' import needs_key %}{{ needs_key(source, 'Name') }}")
        bricklink = BeautifulSoup(template.render(source='bricklink'), 'html.parser').a
        rebrickable = BeautifulSoup(template.render(source='rebrickable'), 'html.parser').a
    assert bricklink.get_text(strip=True) == 'Catalogues & keys' and '&amp;' not in bricklink.get_text() and bricklink['href'].endswith('/manage/catalogues')
    assert rebrickable.get_text(strip=True) == 'Add it on the Rebrickable page' and rebrickable['href'].endswith('/workbench/sync/rebrickable/connect')


def test_a_bad_run_id_makes_no_lock_file_and_no_500(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    with db_of(pair) as db:
        root = sync._root(db)
    before = sorted(p.name for p in root.iterdir())
    for bad in ('x', 'a' * 31, 'a' * 33, '%C2%B2' * 16, '..' + 'b' * 30):
        for path in ('run', 'pick', 'retry'):
            response = client.post(f'/workbench/sync/rebrickable/run/{bad}/{path}', data={'csrf_token': csrf, 'item': ['1']})
            assert response.status_code in (302, 404), (bad, path, response.status_code)
        assert client.get(f'/workbench/sync/rebrickable/run/{bad}/preview').status_code in (302, 404)
    assert sorted(p.name for p in root.iterdir()) == before
    with db_of(pair) as db:
        for call in (lambda: sync_run.apply(db, 'x', None), lambda: sync_run.save_pick(db, 'x', []), lambda: sync_run.retry_send(db, 'x')):
            with pytest.raises(errors.ValidationFailed, match='Unknown sync plan'):
                call()
    assert run_id in ''.join(before)


def test_a_pick_cannot_overwrite_a_run_that_is_applying_or_applied(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    with db_of(pair) as db:
        sync_run.save_pick(db, run_id, [1])
        run = sync_run.load(db, run_id)[0]
        run['applying'] = '2026-11-24T08:00:00+00:00'
        sync._store_plan(db, run)
        with pytest.raises(errors.ValidationFailed, match='already run'):
            sync_run.save_pick(db, run_id, [1, 2])
        assert sync_run.load(db, run_id)[0]['picked'] == [1]
    response = client.post(f'/workbench/sync/rebrickable/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1', '2']})
    assert response.status_code == 302 and soup(client.get(response.location, follow_redirects=True)).select_one('.bk-banner')
    with db_of(pair) as db:
        assert sync_run.load(db, run_id)[0]['picked'] == [1]


def test_a_plan_file_is_written_whole_and_old_lock_files_are_pruned(client, remote, pair):
    csrf = connected(client, pair)
    run_id = start(client, csrf)
    with db_of(pair) as db:
        root = sync._root(db)
        before = (root / (run_id + '.json')).read_text()
        with pytest.raises(TypeError):
            sync._store_plan(db, {'id': run_id, 'broken': object()})            # json.dumps fails: the old file stays, no temporary file is left
        assert (root / (run_id + '.json')).read_text() == before and not list(root.glob('*.tmp'))
        stray = root / ('c' * 32 + '.tmp')
        stray.write_text('half')
        os.utime(stray, (0, 0))
        orphan = root / ('d' * 32 + '.lock')
        orphan.write_text('')
        kept = root / (run_id + '.lock')
        kept.write_text('')
        sync._save_plan(db, dict(id='e' * 32, created_at=base.now().isoformat(), direction='pull', source='rebrickable'))
        assert not orphan.exists() and not stray.exists() and kept.exists() and (root / (run_id + '.json')).exists()


def test_a_kept_difference_with_a_missing_baseline_side_comes_back_as_the_card(client, remote, pair):
    csrf = connected(client, pair)
    apply_run(client, csrf, start(client, csrf))                         # baseline: 1000-1 twice, 1000-2 once
    with db_of(pair) as db:                                              # 1000-2 goes from here (baseline here 1, now none)...
        db.execute("UPDATE copy SET archived_at='2026-11-20T10:00:00.000Z' WHERE item_id=(SELECT id FROM item WHERE born_key='1000-2')")
        db.commit()
    remote.lists[1]['1000-2'] = 4                                        # ...while Rebrickable raised it: changed in both places, here is 0
    remote.lists[2]['1000-4'] = 1
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    assert page.select_one('[data-rb-conflicts] input[checked]')['value'] == 'keep'
    apply_run(client, csrf, run_id, page)                                # something else comes in, the baseline is reset, 1000-2 kept at 0 here
    page = preview_of(client, start(client, csrf))
    row = rows_of(page)['1000-2']
    assert row['data-state'] == 'conflict' and row.select_one('input[name="choice:owned:2"][checked]')['value'] == 'keep'       # #686: still the card, Keep selected
    assert run_data(page)['choice:owned:2'] == ['keep']
    # a set only on Rebrickable that was left unticked (no baseline here for it) comes back unticked as well
    remote.lists[2]['1000-3'] = 1
    remote.lists[2]['1000-4'] = 2                                         # another set has more there: the pull has something to apply, 1000-3 is left out
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    assert rows_of(page)['1000-3'].select_one('input[type=checkbox]').has_attr('checked')              # new: ticked
    data = run_data(page)
    data.pop('choice:owned:3')
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/run', data={'csrf_token': csrf, **data})
    assert copies(pair, '1000-4') == 2
    page = preview_of(client, start(client, csrf))
    row = rows_of(page)['1000-3']
    assert not row.select_one('input[type=checkbox]').has_attr('checked') and 'not taken at the last run' in row.get_text()


def test_a_refused_key_makes_what_was_not_tried_failed_not_waiting(client, remote, pair, monkeypatch):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3), ('3023', '15', 2)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1), raw('1000-1', '3023', 15, 1, number=2)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off')

    def refuse(self, inv, quantity):
        raise base.KeyRejected('Rebrickable refused the user token')
    monkeypatch.setattr(adapters.RebrickableUser, 'lost_part_add', refuse)
    keys = [lost_parts_send.row_key('1000-1', '3001', 4, False), lost_parts_send.row_key('1000-1', '3023', 15, False)]
    apply_run(client, csrf, run_id, lostsend=keys)
    with db_of(pair) as db:
        stage = sync_run.load(db, run_id)[0]['stages']['lost_out']
    assert stage['counts'] == dict(sent=0, failed=2, waiting=0) and 'rejected the key' in stage['message']
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    assert [t.get_text(strip=True) for t in page.select('[data-rb-there] .sr-tag')] == ['2 failed'] and 'waiting' not in page.select_one('.sr-head p').get_text()


def test_the_loose_stock_card_shows_for_unmatched_rows_alone_and_the_into_tab_counts_what_it_shows(client, remote, pair):
    csrf = connected(client, pair)
    remote.part_lists[33] = ('Odd bin', [('99999', 4, 1)])
    page = preview_of(client, start(client, csrf, parts_dir='into', part_list=['33'], owned_dir='off', wishlist_dir='off'))
    card = page.select_one('[data-rb-parts]')
    assert card and 'No part with this number here' in card.get_text() and not card.select('input[name=part]')
    with db_of(pair) as db:
        copy_of(db, '1000-1')
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    remote.lists[1] = {'1000-1': 1}
    page = preview_of(client, start(client, csrf, parts_dir='into', part_list=['31'], lost_dir='into', owned_dir='into', wishlist_dir='off'))
    tabs = {b['data-sy-tab']: b.select_one('.mono').get_text() for b in page.select('.sr-tabs button')}
    rows = [r for r in page.select('[data-sy-row]') if r['data-state'] == 'into' or 'into' in r.get('data-also', '').split()]
    assert tabs['into'] == str(len(rows)) and int(tabs['into']) >= 3        # the set rows, the Lost Parts coming in and the two loose rows


def test_a_local_write_failure_after_a_sent_part_keeps_the_result_and_says_so(client, remote, pair, monkeypatch):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='per_part')
    real, state = sync._store_plan, {'failed': False}

    def flaky(db, plan):
        if plan.get('lost_calls') and not state['failed']:
            state['failed'] = True
            raise OSError('/secret/path/disk full')
        return real(db, plan)
    monkeypatch.setattr(sync, '_store_plan', flaky)
    apply_run(client, csrf, run_id, lostsend=[lost_parts_send.row_key('1000-1', '3001', 4, False)])
    assert state['failed'] and [w[0] for w in remote.lost_writes] == ['POST', 'DELETE']       # the replaced row was still removed after the failed write
    with db_of(pair) as db:
        stage = sync_run.load(db, run_id)[0]['stages']['lost_out']
    assert stage['counts'] == dict(sent=1, failed=0, waiting=0) and stage['unsaved'] is True
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result'))
    assert 'could not write down how far the Lost Parts send got' in page.select_one('[data-rb-there]').get_text()
    assert '/secret/path' not in page.decode()


def test_a_data_folder_that_stays_unwritable_after_the_send_is_a_message_not_a_500(client, remote, pair, monkeypatch):
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='per_part')
    real = sync._store_plan

    def full(db, plan):
        if plan.get('lost_calls'):
            raise OSError('/secret/path/disk full')
        return real(db, plan)
    monkeypatch.setattr(sync, '_store_plan', full)
    page = preview_of(client, run_id)
    response = client.post(f'/workbench/sync/rebrickable/run/{run_id}/run',
                           data={'csrf_token': csrf, **run_data(page), 'lostsend': lost_parts_send.row_key('1000-1', '3001', 4, False)})
    assert response.status_code == 302 and response.location.endswith('/workbench/sync/rebrickable')
    assert [w[0] for w in remote.lost_writes] == ['POST', 'DELETE']
    landing = client.get('/workbench/sync/rebrickable').get_data(as_text=True)
    assert 'could not write down this run' in landing and '/secret/path' not in landing


def test_a_database_that_cannot_be_written_during_a_run_is_not_reported_as_rebrickable_unreachable(client, remote, pair, monkeypatch, caplog):
    import sqlite3
    csrf = connected(client, pair)
    run_id = start(client, csrf)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError('database or disk is full: /secret/db')
    for name in ('apply', 'retry_send'):
        monkeypatch.setattr(sync_run, name, locked)
        response = client.post(f'/workbench/sync/rebrickable/run/{run_id}/{"run" if name == "apply" else "retry"}', data={'csrf_token': csrf})
        assert response.status_code == 302 and response.location.endswith('/workbench/sync/rebrickable')
        landing = client.get('/workbench/sync/rebrickable').get_data(as_text=True)
        assert 'could not write down this run' in landing and 'could not be reached' not in landing and '/secret/db' not in landing
    assert 'OperationalError hidden from the response' in caplog.text


def test_step_2_keeps_the_side_whose_lists_could_not_be_read(client, remote, pair):
    csrf = connected(client, pair)
    choose(client, csrf, start='0', parts_dir='into', part_list=['31'])
    page_ok = soup(client.get('/workbench/sync/rebrickable/choose'))
    assert [page_ok.select_one(f'input[name={n}]')['value'] for n in ('set_lists_read', 'part_lists_read')] == ['1', '1']
    kept = adapters.transport

    def parts_down(request):
        if '/partlists/' in request.full_url:
            raise OSError('offline')
        return kept(request)
    adapters.transport = parts_down
    try:
        page = soup(client.get('/workbench/sync/rebrickable/choose'))
    finally:
        adapters.transport = kept
    assert [page.select_one(f'input[name={n}]')['value'] for n in ('set_lists_read', 'part_lists_read')] == ['1', '0']
    data = {'csrf_token': csrf, 'set_lists_read': '1', 'part_lists_read': '0', 'owned_dir': 'both', 'wishlist_dir': 'both', 'parts_dir': 'into', 'lost_dir': 'off',
            'wish_list': 'default', 'lost_rule': 'per_part', 'send_rule': 'add_only', 'owned': ['1'], 'wishlist': '9', 'send_to': '1', 'list_name:set:1': 'Main collection',
            'start': '0'}
    client.post('/workbench/sync/rebrickable/choose', data=data)
    with db_of(pair) as db:
        link = sync.status(db, 'rebrickable')['link']
        assert link['owned'] == [1] and link['part_lists'] == [31]               # the set lists were read: saved as ticked; the part lists were not: kept
        assert sync_run._saved_names(db).get('part:31') == 'Bulk bin'
    data.update(set_lists_read='0', part_lists_read='1')
    data.pop('owned')
    client.post('/workbench/sync/rebrickable/choose', data=data)
    with db_of(pair) as db:
        link = sync.status(db, 'rebrickable')['link']
        assert link['owned'] == [1] and link['part_lists'] == []                 # now the part lists were read (none ticked), the set lists were not


def test_the_result_counts_each_renamed_list_once(client, remote, pair):
    csrf = connected(client, pair)
    apply_run(client, csrf, start(client, csrf))                      # list 1 holds two sets: two rows carry its name
    remote.names = {1: 'Home collection', 2: 'Garage'}
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id)
    text = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result')).select_one('[data-rb-here]').get_text(' ', strip=True)
    assert '2 list names changed' in text and 'list names changed' in text




# --- #686: a Keep is remembered across runs -------------------------------------------------------------------------------

def make_a_conflict(client, remote, pair, *, also_pull=True):
    """A conflict on 1000-1 (Rebrickable 5, one copy gone here): the card is offered; `also_pull` brings something else in so the pull applies."""
    csrf = connected(client, pair)
    apply_run(client, csrf, start(client, csrf))
    remote.lists[1]['1000-1'] = 5
    with db_of(pair) as db:
        db.execute("UPDATE copy SET archived_at='2026-11-20T10:00:00.000Z' WHERE id=(SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-1' AND c.archived_at IS NULL LIMIT 1)")
        db.commit()
    if also_pull:
        remote.lists[2]['1000-4'] = 1
    return csrf


def test_a_keep_is_remembered_when_the_run_pulls_nothing(client, remote, pair):
    csrf = make_a_conflict(client, remote, pair, also_pull=False)
    run_id = start(client, csrf)
    page = preview_of(client, run_id)
    assert page.select_one('[data-rb-conflicts] input[checked]')['value'] == 'keep'
    apply_run(client, csrf, run_id, page)                                 # nothing is pulled: only the baseline's kept map changes
    with db_of(pair) as db:
        kept = sync._setting(db, 'rebrickable', 'baseline', {}).get('kept')
    assert kept == {'owned': {str(db_item(pair, '1000-1')): [5, 1]}}
    card = preview_of(client, start(client, csrf)).select_one('[data-rb-conflicts]')
    assert card.h2.get_text(' ', strip=True) == 'Changed in both places 1'


def db_item(pair, number):
    with db_of(pair) as db:
        return db.execute("SELECT id FROM item WHERE born_key=?", (number,)).fetchone()[0]


def test_a_keep_is_forgotten_when_either_side_changes(client, remote, pair):
    csrf = make_a_conflict(client, remote, pair)
    apply_run(client, csrf, start(client, csrf))                          # the pull applies, the baseline resets, the Keep stays
    assert preview_of(client, start(client, csrf)).select_one('[data-rb-conflicts]')
    remote.lists[1]['1000-1'] = 6                                         # Rebrickable moves again: the pair no longer matches
    page = preview_of(client, start(client, csrf))
    assert not page.select('[data-rb-conflicts]')


def test_the_api_does_not_add_a_kept_set_with_no_ticks(client, remote, pair):
    """The default pull apply of the API takes every row with an action; a kept conflict has none, so it is not added."""
    csrf = make_a_conflict(client, remote, pair)
    apply_run(client, csrf, start(client, csrf))
    before = copies(pair, '1000-1')
    with db_of(pair) as db:
        plan = sync.plan_pull(db, 'rebrickable')
        row = next(r for r in plan['rows'] if r['key'] == f"owned:{db_item(pair, '1000-1')}")
        assert row['state'] == 'conflict' and row['action'] is None and row['kept']
        sync.apply_pull(db, plan['id'])
    assert copies(pair, '1000-1') == before


def test_the_kept_map_is_plain_json_and_an_undo_of_the_pull_restores_the_counts_and_keeps_the_keep(client, remote, pair):
    """The baseline JSON carries `kept`: it round-trips as JSON (the database file is the export), and the pull's Undo puts the baseline back."""
    csrf = make_a_conflict(client, remote, pair)
    with db_of(pair) as db:
        before = sync._setting(db, 'rebrickable', 'baseline', {})
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id)
    with db_of(pair) as db:
        baseline = sync._setting(db, 'rebrickable', 'baseline', {})
        assert baseline['kept'] and json.loads(json.dumps(baseline)) == baseline
        sync_run.undo_run(db, sync_run.load(db, run_id)[0]['applied']['events'][0])
        restored = sync._setting(db, 'rebrickable', 'baseline', {})
        assert {k: v for k, v in restored.items() if k != 'kept'} == before          # the counts are back as they were
        assert restored['kept'] == baseline['kept']                                   # the Keep was written before the pull: the Undo does not forget it


def test_taking_or_sending_a_kept_conflict_ends_its_keep_and_a_send_only_run_leaves_the_other_kind(client, remote, pair):
    csrf = make_a_conflict(client, remote, pair)
    apply_run(client, csrf, start(client, csrf))                          # the Keep stands after the pull
    item = str(db_item(pair, '1000-1'))
    with db_of(pair) as db:
        assert sync._setting(db, 'rebrickable', 'baseline', {})['kept']['owned'][item] == [5, 1]
    run_id = start(client, csrf)
    apply_run(client, csrf, run_id, **{'choice:owned:' + item: 'take'})   # resolved by Take: here becomes 5
    with db_of(pair) as db:
        assert 'kept' not in sync._setting(db, 'rebrickable', 'baseline', {}) or item not in sync._setting(db, 'rebrickable', 'baseline', {})['kept'].get('owned', {})
    # a Keep of the other kind is left alone by a run that only sends owned sets
    with db_of(pair) as db:
        baseline = sync._setting(db, 'rebrickable', 'baseline', {})
        sync._put(db, 'rebrickable', 'baseline', dict(baseline, kept={'wanted': {'999': [4, 1]}}))
        db.commit()
    start(client, csrf, owned_dir='to', wishlist_dir='off', lost_dir='off')
    run_id = start(client, csrf, owned_dir='to', wishlist_dir='off', lost_dir='off')
    apply_run(client, csrf, run_id)
    with db_of(pair) as db:
        assert sync._setting(db, 'rebrickable', 'baseline', {})['kept']['wanted'] == {'999': [4, 1]}


def test_a_job_run_remembers_the_keep_even_when_its_pull_has_nothing_to_do(client, remote, pair):
    from werkzeug.datastructures import MultiDict
    from brickwork.core.sync import run_job
    csrf = make_a_conflict(client, remote, pair, also_pull=False)
    run_id = start(client, csrf)
    item = str(db_item(pair, '1000-1'))
    with db_of(pair) as db:
        run_job.queue(db, run_id, MultiDict([('choice:owned:' + item, 'keep')]))
        run_job.drain(db)
        assert sync._setting(db, 'rebrickable', 'baseline', {}).get('kept') == {'owned': {item: [5, 1]}}


def test_a_keep_ends_when_the_counts_meet_and_does_not_come_back_later(client, remote, pair):
    csrf = make_a_conflict(client, remote, pair)
    apply_run(client, csrf, start(client, csrf))                          # the Keep stands
    item = str(db_item(pair, '1000-1'))
    remote.lists[1]['1000-1'] = 1                                         # the counts meet (here 1)
    remote.lists[2]['1000-4'] = 2                                         # and a pull has something to write, so the baseline is rebuilt
    apply_run(client, csrf, start(client, csrf))
    with db_of(pair) as db:
        assert 'kept' not in sync._setting(db, 'rebrickable', 'baseline', {})
    remote.lists[1]['1000-1'] = 5                                         # one side moves alone: a plain add, not a resurrected conflict
    page = preview_of(client, start(client, csrf))
    assert not page.select('[data-rb-conflicts]') and rows_of(page)['1000-1']


def test_sending_a_kept_conflict_ends_its_keep_without_an_empty_map(client, remote, pair):
    csrf = make_a_conflict(client, remote, pair)
    apply_run(client, csrf, start(client, csrf))
    item = str(db_item(pair, '1000-1'))
    apply_run(client, csrf, start(client, csrf), **{'choice:owned:' + item: 'send'})
    with db_of(pair) as db:
        assert 'kept' not in sync._setting(db, 'rebrickable', 'baseline', {})


def test_a_run_that_picks_other_sets_leaves_a_keep_alone(client, remote, pair):
    csrf = make_a_conflict(client, remote, pair)
    apply_run(client, csrf, start(client, csrf))                          # the Keep on 1000-1 stands
    item = str(db_item(pair, '1000-1'))
    remote.lists[2]['1000-3'] = 1                                         # another set the run could touch
    run_id = start(client, csrf)
    with db_of(pair) as db:
        candidates = {c['item_id'] for c in sync_run.load(db, run_id)[0]['candidates']}
        other = next(i for i in candidates if i != int(item))
        sync_run.save_pick(db, run_id, {other})                           # a run that covers another set only
    apply_run(client, csrf, run_id)
    with db_of(pair) as db:
        assert sync._setting(db, 'rebrickable', 'baseline', {})['kept']['owned'][item] == [5, 1]


def test_a_keep_only_job_stopped_before_it_starts_writes_nothing(client, remote, pair):
    from werkzeug.datastructures import MultiDict
    from brickwork.core.sync import run_job
    csrf = make_a_conflict(client, remote, pair, also_pull=False)
    run_id = start(client, csrf)
    item = str(db_item(pair, '1000-1'))
    with db_of(pair) as db:
        run_job.queue(db, run_id, MultiDict([('choice:owned:' + item, 'keep')]))
        run_job.request_stop(db, run_id)
        run_job.drain(db)
        assert 'kept' not in sync._setting(db, 'rebrickable', 'baseline', {})
        assert tuple(db.execute("SELECT state, error FROM job WHERE kind='sync_run'").fetchone()) == ('done', 'Stopped at your request')


def test_kept_rows_covers_only_what_the_run_covers():
    """#686: the Keep map after a run: rows it covers are rewritten, the kinds and sets it skips stay as they were."""
    def row(kind, item, remote, here, *, kept=False):
        return dict(key=f'{kind}:{item}', kind=kind, item_id=item, state='conflict', remote=remote, here=here, kept=kept)
    existing = {'owned': {'1': [6, 2], '3': [9, 1]}, 'wanted': {'7': [4, 0]}}
    rows = [row('owned', 1, 5, 1, kept=True), row('owned', 2, 3, 1), row('wanted', 7, 4, 0, kept=True)]
    # the run skips set 1 and does not cover wanted: an old preview's row for either cannot overwrite what is stored
    out = sync.kept_rows(rows, ['owned:2'], existing=existing, covered=('owned',), skipped={1})
    assert out == {'owned': {'1': [6, 2], '2': [3, 1]}, 'wanted': {'7': [4, 0]}}                 # 3 is covered and no longer a conflict: dropped
    # a covered set whose counts met is not in the rows at all: its entry ends
    assert sync.kept_rows([], [], existing={'owned': {'1': [5, 1]}}, covered=('owned', 'wanted'), skipped=set()) == {}
    # resolved by this run: the entry ends
    assert sync.kept_rows(rows[:1], [], resolved=['owned:1'], existing={'owned': {'1': [5, 1]}}) == {}
