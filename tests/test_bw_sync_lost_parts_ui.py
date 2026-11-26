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
from brickwork.core.sync import lost_parts_send

@pytest.fixture(autouse=True)
def _lost_parts_send_unlocked(monkeypatch):
    """The send is locked for now (#469); these tests cover the code behind the lock. `test_lost_parts_send_lock.py` covers the lock."""
    monkeypatch.setattr(lost_parts_send, 'SEND_LOCKED', False)


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


def choose_page(client):
    return soup(client.get('/workbench/sync/rebrickable/choose'))


def test_the_lost_parts_direction_is_on_by_default_with_the_rule_on_the_choose_page(client, remote, pair):
    """#457, #519: the switch is the Into Brick Work end of the Lost Parts segment and the rule is its radio rows, both on step 2 of the Rebrickable page."""
    linked(client)
    page = choose_page(client)
    card = page.select_one('[data-rb-lost]')
    assert card.select_one('input[name=lost_dir][checked]')['value'] == 'into'
    assert [i['value'] for i in card.select('input[name=lost_dir]')] == ['into', 'both', 'to', 'off']
    assert [i['value'] for i in card.select('input[name=lost_rule]')] == ['add_only', 'per_part', 'per_set', 'everything']
    assert card.select_one('input[name=lost_rule][checked]')['value'] == 'per_part'
    assert 'Rebrickable wins per part' in card.get_text()
    assert page.select_one('[data-sync-source=brickset] input[name=lost_parts]') is None
    with closing(connect(pair)) as db:
        admin.patch_settings(db, {'rebrickable_lost_parts_rule': 'everything'})
    assert choose_page(client).select_one('input[name=lost_rule][checked]')['value'] == 'everything'


def test_switching_off_is_remembered_and_makes_no_call(client, remote):
    csrf = linked(client)
    made = len(remote.lost_calls())                                        # "Link and preview pull" read the list once, the switch being on
    response = client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf, 'lost_parts': ['0']})
    assert response.status_code == 302 and len(remote.lost_calls()) == made
    plan = soup(client.get(response.location))
    assert 'Lost Parts are switched off for this pull.' in plan.get_text()
    assert choose_page(client).select_one('input[name=lost_dir][checked]')['value'] == 'off'
    client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf})                      # no field: the remembered value
    assert len(remote.lost_calls()) == made
    client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf, 'lost_parts': ['0', '1']})
    assert len(remote.lost_calls()) == made + 1
    assert choose_page(client).select_one('input[name=lost_dir][checked]')['value'] == 'into'


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
    assert 'Lost Parts: 2 parts marked on 2 sets, 1 cleared' in page.select_one('[data-rb-runs]').get_text()
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


def test_a_set_the_pull_brings_in_is_marked_from_the_page(client, remote, pair):
    """#513: 1000-2 has no copy here and Rebrickable owns it once, so one pull adds the copy and marks its Lost Parts."""
    csrf = linked(client)
    remote.lost = [raw('1000-2', '3001', 4, 1)]
    plan = soup(client.get(client.post('/manage/sync/rebrickable/pull', data={'csrf_token': csrf}).location))
    section = plan.select_one('.sy-lost')
    rows = {r.select_one('.sy-id .mono').get_text(strip=True): r for r in section.select('[data-sy-row]')}
    assert rows['1000-2'].select_one('input[name=lost][data-sy-tick]').has_attr('checked')
    assert 'Mark 1 part' in rows['1000-2'].select_one('.sy-do').get_text(' ', strip=True)
    assert 'No copy of this set' not in section.get_text()
    ticks = [i['value'] for i in plan.select('input[name=tick][checked]')]
    response = client.post('/manage/sync/rebrickable/apply', data={'csrf_token': csrf, 'plan_id': plan.select_one('input[name=plan_id]')['value'],
                                                                    'tick': ticks, 'lost_listed': '1', 'lost': ['1000-2']})
    assert response.status_code == 302
    with closing(connect(pair)) as db:
        (copy,) = [r[0] for r in db.execute("SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='1000-2' AND c.archived_at IS NULL")]
        assert marks(db, copy) == {('3001', '4', False): 1}
