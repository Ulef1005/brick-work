"""The Lost Parts switch, rule remark, plan section, copy chooser and result on the Collection sync pages (#457). Invented data; no network."""
from contextlib import closing
import re

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import admin
from brickwork.core.connect import connect
from brickwork.core.sources import base
from tests.app4 import Coll, app4, client, pair  # noqa: F401
from tests.test_bw_sync import EXTRA, TOKEN
from tests.test_bw_sync_lost_parts import Remote, copy_of, marks, raw, two_copies_line
from tests.test_bw_sync_ui import soup, token
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
    fake = Remote()
    monkeypatch.setattr(adapters, 'transport', fake)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    monkeypatch.delenv('BW_BRICKSET_API_KEY', raising=False)
    with closing(connect(pair)) as db:
        Coll(db).add_copy('2070-1')
        Coll(db).add_copy('2070-1')
    return fake


def linked(client):
    csrf = token(client)
    client.post('/manage/sync/rebrickable/paste', data={'csrf_token': csrf, 'value': TOKEN})
    client.post('/manage/sync/rebrickable/link', data={'csrf_token': csrf, 'owned': ['1', '2'], 'wishlist': '9', 'send_to': '1'})
    return csrf


def pull_form(page):
    return page.select_one('[data-sync-source=rebrickable] form.sy-pull')


def test_the_switch_is_on_by_default_beside_pull_with_the_rule_in_words(client, remote, pair):
    linked(client)
    page = soup(client.get('/manage/sync'))
    form = pull_form(page)
    box = form.select_one('input[type=checkbox][name=lost_parts]')
    assert box['value'] == '1' and box.has_attr('checked') and box['role'] == 'switch'
    assert form.select_one('input[type=hidden][name=lost_parts]')['value'] == '0'
    assert form.select_one('.sy-lost-switch').get_text(strip=True) == 'Bring in Lost Parts'
    assert form.select_one('button.bk-primary').get_text(strip=True) == 'Pull'
    note = page.select_one('#sy-lost-note')
    assert box['aria-describedby'] == 'sy-lost-note'
    assert 'Rule: Rebrickable wins per part.' in note.get_text(' ', strip=True).replace(' .', '.')
    assert note.a['href'].endswith('/manage/tools/settings#sync') or note.a['href'].endswith('#sync')
    assert page.select_one('[data-sync-source=brickset] input[name=lost_parts]') is None
    with closing(connect(pair)) as db:
        admin.patch_settings(db, {'rebrickable_lost_parts_rule': 'everything'})
    assert 'Rebrickable wins everywhere' in soup(client.get('/manage/sync')).select_one('#sy-lost-note').get_text()


def test_switching_off_is_remembered_and_makes_no_call(client, remote):
    csrf = linked(client)
    made = len(remote.lost_calls())                                        # "Link and preview pull" read the list once, the switch being on
    response = client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf, 'lost_parts': ['0']})
    assert response.status_code == 302 and len(remote.lost_calls()) == made
    plan = soup(client.get(response.location))
    assert 'Lost Parts are switched off for this pull.' in plan.get_text()
    assert not pull_form(soup(client.get('/manage/sync'))).select_one('input[type=checkbox]').has_attr('checked')
    client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf})                      # no field: the remembered value
    assert len(remote.lost_calls()) == made
    client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf, 'lost_parts': ['0', '1']})
    assert len(remote.lost_calls()) == made + 1
    assert pull_form(soup(client.get('/manage/sync'))).select_one('input[type=checkbox]').has_attr('checked')


def test_the_plan_shows_the_clearing_the_chooser_and_the_result(client, remote, pair):
    csrf = linked(client)
    with closing(connect(pair)) as db:
        one = copy_of(db, '1000-1', marks=[('3023', '15', 2)])
        copies, row = two_copies_line(db)
        admin.patch_settings(db, {'rebrickable_lost_parts_rule': 'per_set'})
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1), row, raw('1000-4', '3001', 4, 1, number=3)]
    plan = soup(client.get(client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf}).location))
    section = plan.select_one('.sy-lost')
    assert 'Rule: Rebrickable wins per set' in section.get_text()
    assert 'This will clear 1 missing mark (2 pieces)' in section.select_one('.bk-banner').get_text()
    assert 'Lost Parts' in [t.get_text(' ', strip=True) for t in plan.select('[data-sy-tab]')][-1] or any(
        t['data-sy-tab'] == 'lost' for t in plan.select('[data-sy-tab]'))
    rows = {r.select_one('.sy-id .mono').get_text(strip=True): r for r in section.select('[data-sy-row]')}
    assert rows['1000-1'].select_one('input[name=lost][data-sy-tick]').has_attr('checked')
    choose = [s for s in section.select('select[data-sy-pick]')]
    assert len(choose) == 1 and choose[0]['name'] == 'copy:2070-1' and choose[0].option['value'] == ''
    assert [o['value'] for o in choose[0].select('option')][1:] == copies
    assert 'No copy of this set' in section.get_text()
    plan_id = plan.select_one('input[name=plan_id]')['value']
    assert plan.select_one('input[name=lost_listed]')
    response = client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'tick': [], 'lost_listed': '1',
                                                                    'lost': ['1000-1'], 'copy:2070-1': copies[1]})
    assert response.status_code == 302 and 'pulled=' in response.location
    page = soup(client.get(response.location))
    result = page.select_one('.sy-lost-result')
    assert '2 parts marked on 2 sets' in result.get_text() and '1 mark cleared' in result.get_text()
    assert 'Rule: Rebrickable wins per set' in result.get_text() and 'not matched' in result.get_text() and '1000-4' in result.get_text()
    assert 'Lost Parts: 2 parts marked on 2 sets, 1 cleared' in page.select_one('.sy-log').get_text()
    with closing(connect(pair, read_only=True)) as db:
        assert marks(db, one) == {('3001', '4', False): 1} and marks(db, copies[1]) and not marks(db, copies[0])
    client.post('/manage/sync/rebrickable/undo', data={'csrf_token': csrf, 'event': re.search(r'pulled=(\d+)', response.location)[1]})
    with closing(connect(pair, read_only=True)) as db:
        assert marks(db, one) == {('3023', '15', False): 2} and not marks(db, copies[1])


def test_a_set_without_a_pick_is_left_out_and_listed(client, remote, pair):
    csrf = linked(client)
    with closing(connect(pair)) as db:
        copies, row = two_copies_line(db)
    remote.lost = [row]
    plan_id = soup(client.get(client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf}).location)).select_one('input[name=plan_id]')['value']
    response = client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'tick': [], 'lost_listed': '1', 'copy:2070-1': ''})
    result = soup(client.get(response.location)).select_one('.sy-lost-result')
    assert 'Choose a copy' in result.get_text() and 'pick the copy' in result.get_text()


def test_a_failed_read_says_so_and_the_pull_still_works(client, remote):
    csrf = linked(client)
    remote.error = RuntimeError('boom')
    plan = soup(client.get(client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf}).location))
    assert 'Lost Parts were not read' in plan.select_one('.sy-lost .bk-banner').get_text()
    assert plan.select('input[name=tick]')
    plan_id = plan.select_one('input[name=plan_id]')['value']
    response = client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan_id, 'lost_listed': '1', 'tick': []})
    assert 'Lost Parts were not read' in soup(client.get(response.location)).select_one('.sy-lost-result').get_text()


def test_the_new_fields_need_csrf(client, remote):
    linked(client)
    assert client.post('/manage/sync/rebrickable/pull', data={'lost_parts': '1'}).status_code == 400
    assert client.post('/manage/sync/rebrickable/apply', data={'plan_id': 'x' * 32, 'lost_listed': '1', 'lost': ['1000-1']}).status_code == 400
