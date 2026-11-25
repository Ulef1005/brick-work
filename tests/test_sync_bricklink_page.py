"""#521 slice A: the BrickLink sync page at rest and its steps (connect, choose what, pick lots, preview, run, result, undo).
Invented data against the fake BrickLink client of test_sync_bricklink_run; no network."""
from contextlib import closing
import json
import re
import sqlite3

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import orders, price_settings, sync, undo as undoing
from brickwork.core.connect import connect
from brickwork.core.sources import base
from brickwork.core.sources.base import SourceError
from brickwork.core.sync import bricklink_run
from brickwork.web import admin_ops
from tests.app4 import app4, client, pair  # noqa: F401
from tests.test_sync_bricklink_run import FakeBrickLink, _header, _items
from tests.web_fixtures import ROOT  # noqa: F401

BASE = '/workbench/sync/bricklink'
BL_ENV = (
    'BW_BRICKLINK_CONSUMER_KEY',
    'BW_BRICKLINK_CONSUMER_SECRET',
    'BW_BRICKLINK_TOKEN_VALUE',
    'BW_BRICKLINK_TOKEN_SECRET',
)
CHOICES = {'orders_dir': 'into', 'since_on': '', 'since': '', 'status': 'received_paid', 'region': 'eu'}


@pytest.fixture
def remote(pair, monkeypatch):
    monkeypatch.setattr(base, 'transport', lambda r: (_ for _ in ()).throw(AssertionError('network')))
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_PRICE_SETTINGS_LOCK', '0')
    for name in BL_ENV:
        monkeypatch.delenv(name, raising=False)
    fake = FakeBrickLink(
        headers=[
            _header(1001, status='RECEIVED', date_ordered='2026-11-17T10:00:00.000Z', unique_count=14, total='38.20', currency='EUR'),
            _header(1002, status='PAID', date_ordered='2026-11-05T09:00:00.000Z', unique_count=2, total='9.50', currency='EUR'),
        ],
        items_by_order={'1001': _items(qty=3), '1002': _items(qty=5)},
    )
    monkeypatch.setattr(bricklink_run, 'BrickLink', lambda db: fake)
    monkeypatch.setattr(orders, 'BrickLink', lambda db: fake, raising=False)
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


def set_keys(monkeypatch):
    for name in BL_ENV:
        monkeypatch.setenv(name, 'synthetic-' + name.lower())


def start_run(client, csrf):
    response = client.post(BASE + '/start', data={'csrf_token': csrf})
    assert response.status_code == 302 and '/run/' in response.location, response.location
    return re.search(r'/run/([0-9a-f]{32})/pick', response.location)[1]


def import_existing(pair, remote, order_id):
    with db_of(pair) as db:
        prepared = orders.api_data(db, str(order_id), client=remote, headers=remote.headers)
        orders.import_document(db, 'api', number=str(order_id), prepared=prepared)


def test_site_page_at_rest_without_and_with_keys(client, remote, monkeypatch):
    page = soup(client.get(BASE))
    assert page.select_one('h1').get_text(strip=True) == 'BrickLink'
    assert page.select_one('.sr-headrow p').get_text(strip=True) == 'Not run yet'
    connect_link = page.select_one('a.bk-primary')
    assert connect_link.get_text(strip=True) == 'Connect' and connect_link['href'].endswith(BASE + '/connect')
    assert not page.select('.sr-headrow form')

    set_keys(monkeypatch)
    page = soup(client.get(BASE))
    assert page.select_one('[data-rb-account] .sr-tag').get_text(strip=True) == 'Connected'
    kv = [t.get_text(' ', strip=True) for t in page.select('[data-rb-account] .sr-kv dt, [data-rb-account] .sr-kv dd')]
    assert kv == ['Key', 'Set in the environment', "Today's budget", '7 of 4400 calls']
    table = [[c.get_text(' ', strip=True) for c in tr.select('td')] for tr in page.select('[data-rb-what] tbody tr')]
    assert [row[0] for row in table] == ['Orders', 'Price guide', 'Wanted lists']
    assert [row[1] for row in table] == ['Into Brick Work', 'Into Brick Work', 'By file']
    change = page.select_one('[data-rb-what] a.bk-btn')
    assert change.get_text(strip=True) == 'Change what syncs' and change['href'].endswith(BASE + '/choose')
    assert page.select_one('form[action$="/workbench/sync/bricklink/start"] button')


def test_connect_page_shows_four_write_only_inputs_and_ip_binding_note(client, remote):
    page = soup(client.get(BASE + '/connect'))
    inputs = page.select('[data-rb-key] form input[type=password]')
    assert [i['name'] for i in inputs] == [
        'key:consumer_key', 'key:consumer_secret', 'key:token_value', 'key:token_secret',
    ]
    assert all(not i.has_attr('value') for i in inputs)
    assert 'binds the token to one IP address' in page.select_one('[data-rb-key] .sr-lede').get_text()


def test_key_post_delegates_to_admin_ops_and_enforces_action_and_csrf(client, remote, monkeypatch):
    calls = []

    def fake_write(op, **kw):
        calls.append((op, kw))
        return dict(tested=True, reason=None)

    monkeypatch.setattr(admin_ops, 'tools_write', fake_write)
    csrf = token(client)
    creds = {
        'key:consumer_key': 'ck-12345678',
        'key:consumer_secret': 'cs-12345678',
        'key:token_value': 'tv-12345678',
        'key:token_secret': 'ts-12345678',
    }
    response = client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'save', **creds})
    assert response.status_code == 302 and response.location.endswith(BASE + '/connect')
    assert calls[-1] == ('key_test_save', dict(source='bricklink', values=dict(
        consumer_key='ck-12345678', consumer_secret='cs-12345678',
        token_value='tv-12345678', token_secret='ts-12345678',
    )))
    assert 'Saved · The key works' in soup(client.get(response.location)).select_one('.bk-banner').get_text()

    assert client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'test'}).status_code == 302
    assert calls[-1] == ('key_test', dict(source='bricklink'))
    assert client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'remove'}).status_code == 302
    assert calls[-1] == ('key_remove', dict(source='bricklink'))

    assert client.post(BASE + '/key', data={'csrf_token': csrf, 'action': 'bogus'}).status_code == 400
    assert client.post(BASE + '/key', data={'action': 'test'}).status_code == 400      # no token, as every sync write
    assert client.post(
        BASE + '/key',
        data={'csrf_token': csrf, 'action': 'test'},
        headers={'Origin': 'https://foreign.example'},
    ).status_code == 403


def test_choose_page_defaults_validation_save_and_start(client, remote, pair, monkeypatch):
    no_key = client.get(BASE + '/choose')
    assert no_key.status_code == 302 and no_key.location.endswith(BASE + '/connect')

    set_keys(monkeypatch)
    with db_of(pair) as db:
        initial_region = price_settings.read(db)['bricklink_region']
    page = soup(client.get(BASE + '/choose'))
    assert page.select_one('input[name=orders_dir][checked]')['value'] == 'into'
    selected_status = page.select_one('select[name=status] option[selected]')
    assert selected_status['value'] == 'received_paid' and selected_status.get_text(strip=True) == 'Received and paid'
    assert not page.select_one('input[name=since_on]').has_attr('checked')
    assert [o['value'] for o in page.select('select[name=region] option')] == list(price_settings.REGIONS)
    assert page.select_one('select[name=region] option[selected]')['value'] == initial_region

    csrf = token(client)
    bad = client.post(BASE + '/choose', data={'csrf_token': csrf, **CHOICES, 'since_on': '1', 'since': '2026-02-30'})
    assert bad.status_code == 302 and bad.location.endswith(BASE + '/choose')
    assert 'Choose a valid start date' in soup(client.get(bad.location)).select_one('.bk-banner').get_text()

    new_region = next(r for r in price_settings.REGIONS if r != initial_region)
    saved = client.post(BASE + '/choose', data={
        'csrf_token': csrf, 'orders_dir': 'into', 'since_on': '1', 'since': '2026-10-01',
        'status': 'all', 'region': new_region, 'start': '0',
    })
    assert saved.status_code == 302 and saved.location.endswith(BASE)
    with db_of(pair) as db:
        assert price_settings.read(db)['bricklink_region'] == new_region
        assert bricklink_run.choices(db) == dict(orders='into', since_on=True, since='2026-10-01', status='all')

    started = client.post(BASE + '/choose', data={
        'csrf_token': csrf, 'orders_dir': 'into', 'since_on': '', 'since': '',
        'status': 'received_paid', 'region': new_region,
    })
    assert started.status_code == 302 and re.search(r'/run/[0-9a-f]{32}/pick$', started.location)
    assert remote.list_calls == 1


def test_start_post_when_orders_off_flashes_and_returns_to_choose(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    csrf = token(client)
    client.post(BASE + '/choose', data={'csrf_token': csrf, **CHOICES, 'orders_dir': 'off', 'start': '0'})
    soup(client.get(BASE))
    response = client.post(BASE + '/start', data={'csrf_token': csrf})
    assert response.status_code == 302 and response.location.endswith(BASE + '/choose')
    assert 'Orders are switched off' in soup(client.get(response.location)).select_one('.bk-banner').get_text()
    assert remote.list_calls == 0


def test_pick_page_lists_orders_marks_imported_and_validates_post(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    import_existing(pair, remote, '1001')
    csrf = token(client)
    run_id = start_run(client, csrf)

    page = soup(client.get(f'{BASE}/run/{run_id}/pick'))
    rows = {r.select_one('input[name=item]')['value']: r for r in page.select('.sr-pickrow')}
    assert list(rows) == ['1001', '1002']
    assert 'Order 1001' in rows['1001'].get_text() and 'Received 17 Nov · 14 lots · 38.20 EUR' in rows['1001'].get_text()
    assert rows['1001'].select_one('.sr-tag').get_text(strip=True) == 'Imported'
    assert not rows['1001'].select_one('input[name=item]').has_attr('checked')
    assert 'Order 1002' in rows['1002'].get_text() and 'Paid 5 Nov · 2 lots · 9.50 EUR' in rows['1002'].get_text()
    assert rows['1002'].select_one('input[name=item]').has_attr('checked')
    assert not rows['1002'].select_one('.sr-tag')
    assert page.select_one('[data-sr-count]').get_text(' ', strip=True) == '1 of 2 orders picked'

    bad = client.post(f'{BASE}/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['9999']})
    assert bad.status_code == 302 and bad.location.endswith(f'/run/{run_id}/pick')
    assert 'Pick orders from the list' in soup(client.get(bad.location)).select_one('.bk-banner').get_text()

    good = client.post(f'{BASE}/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1002', 'bogus', '12x']})
    assert good.status_code == 302 and good.location.endswith(f'/run/{run_id}/preview')
    with db_of(pair) as db:
        assert bricklink_run.load(db, run_id)['picked'] == ['1002']


def test_preview_page_shows_new_and_imported_rows_and_redirects_once_applied(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    import_existing(pair, remote, '1001')
    csrf = token(client)
    run_id = start_run(client, csrf)
    assert client.post(f'{BASE}/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1001', '1002']}).status_code == 302

    page = soup(client.get(f'{BASE}/run/{run_id}/preview'))
    rows = {r.select_one('b').get_text(strip=True): r for r in page.select('[data-sy-row]')}
    assert list(rows) == ['Order 1001', 'Order 1002']
    assert not rows['Order 1001'].select_one('input[type=checkbox]')
    assert rows['Order 1001'].select_one('.sr-tag').get_text(strip=True) == 'Imported'
    box = rows['Order 1002'].select_one('input[type=checkbox][name="order:1002"]')
    assert box is not None and box['value'] == 'pull' and box.has_attr('checked')
    assert rows['Order 1002'].select_one('.sr-tag').get_text(strip=True) == 'New at BrickLink'
    assert 'One Undo for the whole run.' in page.get_text()

    assert client.post(f'{BASE}/run/{run_id}/run', data={'csrf_token': csrf, 'order:1002': 'pull'}).status_code == 302
    again = client.get(f'{BASE}/run/{run_id}/preview')
    assert again.status_code == 302 and again.location.endswith(f'/run/{run_id}/result')


def test_apply_imports_orders_shows_result_and_is_idempotent(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    csrf = token(client)
    run_id = start_run(client, csrf)
    form = {'csrf_token': csrf, 'order:1001': 'pull', 'order:1002': 'pull'}
    response = client.post(f'{BASE}/run/{run_id}/run', data=form)
    assert response.status_code == 302 and response.location.endswith(f'/run/{run_id}/result')

    with db_of(pair) as db:
        po_map = dict(db.execute('SELECT bricklink_order_id, id FROM main.purchase_order').fetchall())
        audit_row = db.execute(
            "SELECT new_value FROM main.event WHERE entity_kind='sync' AND entity_id='bricklink' AND field='run' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        events = json.loads(audit_row['new_value'])['events']
        event_count = db.execute('SELECT count(*) FROM main.event').fetchone()[0]
    assert set(po_map) == {'1001', '1002'} and len(events) == 2

    page = soup(client.get(response.location))
    rows = {r.select_one('b').get_text(strip=True): r for r in page.select('.sr-prow')}
    assert list(rows) == ['Order 1001', 'Order 1002']
    for oid in ('1001', '1002'):
        row = rows['Order ' + oid]
        assert 'Pulled into Orders (' in row.get_text()
        link = row.select_one('a.sr-link')
        assert link.get_text(strip=True) == 'Open order' and str(po_map[oid]) in link['href']
    undo_form = page.select_one('form[action$="/workbench/sync/bricklink/undo"]')
    assert undo_form and undo_form.select_one('input[name=event]')['value'] == str(events[0])

    item_calls = list(remote.item_calls)
    second = client.post(f'{BASE}/run/{run_id}/run', data=form)
    assert second.status_code == 302 and second.location.endswith(f'/run/{run_id}/result')
    assert remote.item_calls == item_calls
    with db_of(pair) as db:
        assert db.execute('SELECT count(*) FROM main.purchase_order').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM main.event').fetchone()[0] == event_count


def test_apply_reports_a_failing_order_and_still_imports_the_other(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    remote.fail['1001'] = SourceError('BrickLink unavailable')
    csrf = token(client)
    run_id = start_run(client, csrf)
    response = client.post(f'{BASE}/run/{run_id}/run', data={'csrf_token': csrf, 'order:1001': 'pull', 'order:1002': 'pull'})
    assert response.status_code == 302 and response.location.endswith(f'/run/{run_id}/result')

    with db_of(pair) as db:
        assert [r[0] for r in db.execute('SELECT bricklink_order_id FROM main.purchase_order')] == ['1002']
    page = soup(client.get(response.location))
    rows = {r.select_one('b').get_text(strip=True): r for r in page.select('.sr-prow')}
    assert 'BrickLink unavailable' in rows['Order 1001'].get_text()
    assert rows['Order 1001'].select_one('.sr-tag').get_text(strip=True) == 'Failed'
    assert 'Pulled into Orders (' in rows['Order 1002'].get_text()
    assert rows['Order 1002'].select_one('a.sr-link').get_text(strip=True) == 'Open order'


def test_undo_reverts_orders_updates_site_and_result_and_checks_event_and_csrf(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    csrf = token(client)
    run_id = start_run(client, csrf)
    client.post(f'{BASE}/run/{run_id}/run', data={'csrf_token': csrf, 'order:1001': 'pull', 'order:1002': 'pull'})

    result = soup(client.get(f'{BASE}/run/{run_id}/result'))
    event = result.select_one('form[action$="/undo"] input[name=event]')['value']

    assert client.post(BASE + '/undo', data={'event': event}).status_code == 400
    assert client.post(BASE + '/undo', data={'csrf_token': csrf, 'event': '999999'}).status_code == 404

    response = client.post(BASE + '/undo', data={'csrf_token': csrf, 'event': event})
    assert response.status_code == 302 and response.location.endswith(BASE)
    site = soup(client.get(response.location))
    assert 'Run undone.' in site.select_one('.bk-banner').get_text()
    assert site.select_one('[data-rb-runs] .sr-run') and not site.select_one('[data-rb-runs] form[action$="/undo"]')

    with db_of(pair) as db:
        phases = [r[0] for r in db.execute('SELECT phase FROM main.order_document ORDER BY id')]
    assert phases == ['undone', 'undone']

    after_result = soup(client.get(f'{BASE}/run/{run_id}/result'))
    assert 'This run was undone.' in after_result.get_text()
    assert not after_result.select_one('form[action$="/undo"]')
    assert client.get('/workbench/sync').status_code == 200


def test_cross_site_run_ids_return_404_in_both_directions(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    csrf = token(client)
    with db_of(pair) as db:
        other = sync._save_plan(db, dict(
            id='b' * 32, created_at=base.now().isoformat(), direction='run',   # a fixed date would pass PLAN_TTL and the plan be removed
            source='brickset', candidates=[], picked=None, stages={},
        ))
    other_id = other['id']
    for path in ('pick', 'preview', 'result'):
        assert client.get(f'{BASE}/run/{other_id}/{path}').status_code == 404, path
    for path in ('pick', 'run'):
        assert client.post(f'{BASE}/run/{other_id}/{path}', data={'csrf_token': csrf}).status_code == 404, path

    bl_id = start_run(client, csrf)
    for path in ('pick', 'preview', 'result'):
        assert client.get(f'/workbench/sync/brickset/run/{bl_id}/{path}').status_code == 404, path
    for path in ('pick', 'run'):
        assert client.post(f'/workbench/sync/brickset/run/{bl_id}/{path}', data={'csrf_token': csrf}).status_code == 404, path


def test_hub_card_shows_connected_open_and_last_run(client, remote, monkeypatch):
    hub = soup(client.get('/workbench/sync'))
    card = hub.select_one('[data-sync-site=bricklink]')
    assert card.select_one('a.bk-btn')['href'].endswith(BASE + '/connect')

    set_keys(monkeypatch)
    hub = soup(client.get('/workbench/sync'))
    card = hub.select_one('[data-sync-site=bricklink]')
    assert 'Connected' in card.get_text()
    btn = card.select_one('a.bk-btn')
    assert btn.get_text(strip=True) == 'Open' and btn['href'].endswith(BASE)

    csrf = token(client)
    run_id = start_run(client, csrf)
    client.post(f'{BASE}/run/{run_id}/run', data={'csrf_token': csrf, 'order:1001': 'pull'})
    card = soup(client.get('/workbench/sync')).select_one('[data-sync-site=bricklink]')
    assert 'Never' not in card.select_one('.sh-meta').get_text()


def test_undo_older_run_leaves_newer_run_undoable(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    remote.items_by_order['1002'] = [
        dict(_items(qty=5)[0], item=dict(no='3002-other', type='PART', name='Other brick'), new_or_used='N'),
    ]
    csrf = token(client)
    run_b = start_run(client, csrf)
    assert client.post(f'{BASE}/run/{run_b}/run', data={'csrf_token': csrf, 'order:1001': 'pull'}).status_code == 302
    run_a = start_run(client, csrf)
    assert client.post(f'{BASE}/run/{run_a}/run', data={'csrf_token': csrf, 'order:1002': 'pull'}).status_code == 302

    site_before = soup(client.get(BASE))
    assert len(site_before.select('[data-rb-runs] form[action$="/undo"]')) == 2

    event_b = soup(client.get(f'{BASE}/run/{run_b}/result')).select_one('form[action$="/undo"] input[name=event]')['value']
    response = client.post(BASE + '/undo', data={'csrf_token': csrf, 'event': event_b})
    assert response.status_code == 302 and response.location.endswith(BASE)
    assert client.get('/workbench/sync').status_code == 200

    site_after = soup(client.get(BASE))
    undo_inputs = site_after.select('[data-rb-runs] form[action$="/undo"] input[name=event]')
    assert len(undo_inputs) == 1 and undo_inputs[0]['value'] != event_b

    result_a = soup(client.get(f'{BASE}/run/{run_a}/result'))
    assert 'This run was undone.' not in result_a.get_text()
    assert result_a.select_one('form[action$="/undo"]')

    result_b = soup(client.get(f'{BASE}/run/{run_b}/result'))
    assert 'This run was undone.' in result_b.get_text()
    assert not result_b.select_one('form[action$="/undo"]')


def test_choose_page_locked_region_and_unlock(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    monkeypatch.delenv('BW_PRICE_SETTINGS_LOCK', raising=False)
    assert price_settings.region_locked() is True
    with db_of(pair) as db:
        initial_region = price_settings.read(db)['bricklink_region']
    other_region = next(r for r in price_settings.REGIONS if r != initial_region)

    page = soup(client.get(BASE + '/choose'))
    assert page.select_one('select[name=region]').has_attr('disabled')
    assert 'The region is locked by this installation. Whoever runs Brick Work can change it with BW_PRICE_SETTINGS_LOCK.' in page.select_one('[data-bl-price]').get_text()

    csrf = token(client)
    saved = client.post(BASE + '/choose', data={
        'csrf_token': csrf, 'orders_dir': 'into', 'since_on': '1', 'since': '2026-10-01',
        'status': 'all', 'start': '0',
    })
    assert saved.status_code == 302 and saved.location.endswith(BASE)
    with db_of(pair) as db:
        assert bricklink_run.choices(db) == dict(orders='into', since_on=True, since='2026-10-01', status='all')
        assert price_settings.read(db)['bricklink_region'] == initial_region

    crafted = client.post(BASE + '/choose', data={
        'csrf_token': csrf, 'orders_dir': 'off', 'since_on': '', 'since': '',
        'status': 'received_paid', 'region': other_region, 'start': '0',
    })
    assert crafted.status_code == 302 and crafted.location.endswith(BASE + '/choose')
    banners = ' '.join(b.get_text() for b in soup(client.get(crafted.location)).select('.bk-banner'))      # the earlier 'Saved.' is still queued
    assert 'The price region is locked on this install' in banners
    with db_of(pair) as db:
        assert bricklink_run.choices(db) == dict(orders='into', since_on=True, since='2026-10-01', status='all')
        assert price_settings.read(db)['bricklink_region'] == initial_region

    monkeypatch.setenv('BW_PRICE_SETTINGS_LOCK', '0')
    assert price_settings.region_locked() is False
    unlocked_page = soup(client.get(BASE + '/choose'))
    assert not unlocked_page.select_one('select[name=region]').has_attr('disabled')
    assert 'The region is locked by this installation.' not in unlocked_page.select_one('[data-bl-price]').get_text()
    unlocked = client.post(BASE + '/choose', data={
        'csrf_token': csrf, 'orders_dir': 'into', 'since_on': '1', 'since': '2026-10-01',
        'status': 'all', 'region': other_region, 'start': '0',
    })
    assert unlocked.status_code == 302 and unlocked.location.endswith(BASE)
    with db_of(pair) as db:
        assert price_settings.read(db)['bricklink_region'] == other_region


def test_apply_sqlite_error_flashes_unsaved_and_redirects_to_site(client, remote, pair, monkeypatch):
    from brickwork.web import sync_bricklink      # imported here: the module needs the web app loaded first (the `client` fixture does that)
    set_keys(monkeypatch)
    csrf = token(client)
    run_id = start_run(client, csrf)

    def broken_import(*args, **kwargs):
        raise sqlite3.OperationalError('disk I/O error')

    monkeypatch.setattr(orders, 'import_document', broken_import)
    response = client.post(f'{BASE}/run/{run_id}/run', data={'csrf_token': csrf, 'order:1001': 'pull'})
    assert response.status_code == 302 and response.location.endswith(BASE)
    site = soup(client.get(response.location))
    assert sync_bricklink.UNSAVED in site.select_one('.bk-banner').get_text()
    assert sync_bricklink._error_text(sqlite3.OperationalError('disk I/O error')) == sync_bricklink.UNSAVED
    with db_of(pair) as db:
        stored = bricklink_run.load(db, run_id)
        assert '1001' not in stored['stages']


def test_partial_undo_keeps_run_undoable_until_every_event_is_undone(client, remote, pair, monkeypatch):
    set_keys(monkeypatch)
    remote.items_by_order['1002'] = [
        dict(_items(qty=5)[0], item=dict(no='3002-other', type='PART', name='Other brick'), new_or_used='N'),
    ]
    csrf = token(client)
    run_id = start_run(client, csrf)
    response = client.post(f'{BASE}/run/{run_id}/run', data={'csrf_token': csrf, 'order:1001': 'pull', 'order:1002': 'pull'})
    assert response.status_code == 302 and response.location.endswith(f'/run/{run_id}/result')

    with db_of(pair) as db:
        audit_row = db.execute(
            "SELECT new_value FROM main.event WHERE entity_kind='sync' AND entity_id='bricklink' AND field='run' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        events = json.loads(audit_row['new_value'])['events']
        assert len(events) == 2
        undoing.undo_event(db, events[0])

    site_partial = soup(client.get(BASE))
    undo_input = site_partial.select_one('[data-rb-runs] form[action$="/undo"] input[name=event]')
    assert undo_input is not None and undo_input['value'] == str(events[0])

    result_partial = soup(client.get(f'{BASE}/run/{run_id}/result'))
    assert 'This run was undone.' not in result_partial.get_text()
    result_undo = result_partial.select_one('form[action$="/undo"] input[name=event]')
    assert result_undo is not None and result_undo['value'] == str(events[0])

    with db_of(pair) as db:
        undoing.undo_event(db, events[1])

    site_done = soup(client.get(BASE))
    assert site_done.select_one('[data-rb-runs] .sr-run') and not site_done.select_one('[data-rb-runs] form[action$="/undo"]')

    result_done = soup(client.get(f'{BASE}/run/{run_id}/result'))
    assert 'This run was undone.' in result_done.get_text()
    assert not result_done.select_one('form[action$="/undo"]')


def test_start_and_save_pick_oserror_flash_unsaved(client, remote, pair, monkeypatch):
    from brickwork.web import sync_bricklink
    set_keys(monkeypatch)
    csrf = token(client)
    run_id = start_run(client, csrf)

    def fail_plan(*args, **kwargs):
        raise OSError('read-only data folder')

    monkeypatch.setattr(sync, '_save_plan', fail_plan)
    start_resp = client.post(BASE + '/start', data={'csrf_token': csrf})
    assert start_resp.status_code == 302 and start_resp.location.endswith(BASE + '/choose')
    assert sync_bricklink.UNSAVED in soup(client.get(start_resp.location)).select_one('.bk-banner').get_text()

    monkeypatch.setattr(sync, '_store_plan', fail_plan)
    pick_resp = client.post(f'{BASE}/run/{run_id}/pick', data={'csrf_token': csrf, 'item': ['1001']})
    assert pick_resp.status_code == 302 and pick_resp.location.endswith(f'/run/{run_id}/pick')
    assert sync_bricklink.UNSAVED in soup(client.get(pick_resp.location)).select_one('.bk-banner').get_text()
