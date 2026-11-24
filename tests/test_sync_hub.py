"""#518: Workbench Sync hub, site pages, legacy redirects, and navigation. Invented data; no network."""
from contextlib import closing

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core.connect import connect
from brickwork.core.sources import base
from brickwork.web import ui
from tests.app4 import Coll, app4, client, pair  # noqa: F401
from tests.test_bw_sync import EXTRA, TOKEN, Rebrickable
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
    return fake


def soup(response):
    assert response.status_code == 200, response.status_code
    return BeautifulSoup(response.data, 'html.parser')


def csrf_token(client):
    client.get('/workbench/sync')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def test_hub_renders_four_site_cards_in_order_and_sections(client, remote):
    page = soup(client.get('/workbench/sync'))
    cards = page.select('[data-sync-site]')
    assert [c['data-sync-site'] for c in cards] == ['rebrickable', 'brickset', 'bricklink', 'brickowl']
    assert [c.select_one('.sh-name').get_text(strip=True) for c in cards] == ['Rebrickable', 'Brickset', 'BrickLink', 'Brick Owl']
    for key in ('bricklink', 'brickowl'):
        card = page.select_one(f'[data-sync-site={key}]')
        assert card.select_one('.sh-tag.sh-tag-dash').get_text(strip=True) == 'Not connected'
        assert 'none' in card.select_one('.sh-meta').get_text()
        assert 'Never' in card.select_one('.sh-meta').get_text()
        btn = card.select_one('a.bk-btn')
        assert btn.get_text(strip=True) == 'Connect'
        assert btn['href'].endswith('/workbench/sync/bricklink/connect' if key == 'bricklink' else '/manage/catalogues')   # BrickLink has its page (#521), Brick Owl not yet
    imp =page.select_one('[data-sync-import]')
    assert imp.select_one('.sh-name').get_text(strip=True) == 'Import & export'
    assert imp.select_one('a.bk-btn').get_text(strip=True) == 'Open'
    assert imp.select_one('a.bk-btn')['href'].endswith('/manage/import-legacy')
    assert 'Never' in imp.select_one('.sh-import-meta').get_text()
    assert page.select_one('#sy-log-title').get_text(strip=True) == 'Sync log'
    assert 'How sync works' in page.select_one('.sy-how').get_text()
    assert page.select_one('link[href*="bw-sync-hub.css"]')


def test_rebrickable_shows_connect_before_token_and_open_after(client, remote, pair):
    before = soup(client.get('/workbench/sync')).select_one('[data-sync-site=rebrickable]')
    assert before.select_one('.sh-tag.sh-tag-dash').get_text(strip=True) == 'Not connected'
    assert before.select_one('a.bk-btn').get_text(strip=True) == 'Connect'
    assert before.select_one('a.bk-btn')['href'].endswith('/workbench/sync/rebrickable/connect')

    csrf = csrf_token(client)
    response = client.post('/manage/sync/rebrickable/paste', data={'csrf_token': csrf, 'value': TOKEN})
    assert response.status_code == 302

    after = soup(client.get('/workbench/sync')).select_one('[data-sync-site=rebrickable]')
    tag = after.select_one('.sh-tag')
    assert tag.get_text(strip=True) == 'Connected' and 'sh-tag-dash' not in tag.get('class', [])
    assert after.select_one('a.bk-btn').get_text(strip=True) == 'Open'
    assert after.select_one('a.bk-btn')['href'].endswith('/workbench/sync/rebrickable')
    assert 'Linked' in after.select_one('.sh-meta').get_text()                    # a pasted token has no account name
    with closing(connect(pair)) as db:                                              # #686: the name, once it is known, takes the place of "Linked"
        db.execute("INSERT OR REPLACE INTO setting(key, value) VALUES('rebrickable_account_name', 'synthetic_user')")
        db.commit()
    named = soup(client.get('/workbench/sync')).select_one('[data-sync-site=rebrickable]')
    assert 'synthetic_user' in named.select_one('.sh-meta').get_text() and 'Linked' not in named.select_one('.sh-meta').get_text()


def test_legacy_manage_sync_redirects(client, remote):
    hub_resp = client.get('/manage/sync')
    assert hub_resp.status_code == 302 and hub_resp.location.endswith('/workbench/sync')
    pulled_resp = client.get('/manage/sync?pulled=5')
    assert pulled_resp.status_code == 302 and pulled_resp.location.endswith('/workbench/sync/rebrickable?pulled=5')


def test_site_page_restricts_source_has_back_link_and_404s_unknown(client, remote):
    rb = soup(client.get('/workbench/sync/rebrickable'))
    assert [c.name for c in rb.select('[data-rb-account], [data-rb-runs], [data-rb-what]')] == ['section'] * 3
    assert rb.select_one('h1').get_text(strip=True) == 'Rebrickable'
    back = rb.select_one('a.bw-back')
    assert back['href'].endswith('/workbench/sync') and back.get_text(strip=True) == 'Sync'
    assert client.get('/workbench/sync/bricklink').status_code == 200      # its own page since #521
    assert client.get('/workbench/sync/brickowl').status_code == 404
    assert client.get('/workbench/sync/unknown').status_code == 404


def test_workbench_nav_lists_sync_and_marks_it_current(app4, client, remote):
    page = soup(client.get('/workbench/sync'))
    assert page.find('a', href='/workbench/sync')
    for path in ('/workbench/sync', '/workbench/sync/rebrickable', '/workbench/sync/rebrickable/connect', '/manage/sync/brickset/link'):
        with app4.test_request_context(path):
            groups = dict(ui.navigation())
            workbench = groups['Workbench']
            titles = [link['title'] for link in workbench]
            assert titles.index('Sync') == titles.index('Storage') + 1
            sync_link = next(link for link in workbench if link['title'] == 'Sync')
            assert sync_link['active'] is True and sync_link['url'].endswith('/workbench/sync')


def _event(db, field, entity_id, value, at='2026-11-20T10:00:00Z'):
    import json
    cur = db.execute("INSERT INTO event(at, via, entity_kind, entity_id, field, new_value) VALUES (?, 'app', 'sync', ?, ?, ?)",
                     (at, entity_id, field, json.dumps(value)))
    return cur.lastrowid


def test_site_log_keeps_its_own_rows_and_undos_past_other_sites_traffic(pair):
    from brickwork.web.sync_views import _log
    with closing(connect(pair)) as db:
        pull = _event(db, 'receipt', '1', {'source': 'rebrickable', 'counts': {'copies': 2}})
        _event(db, 'undo', str(pull), {'undoes': pull})
        for _ in range(30):   # more of Brickset's traffic than one page of the log
            _event(db, 'send', 'brickset', {'counts': {'sent': 1}})
        db.commit()
        rebrickable = _log(db, source='rebrickable')
        assert [(r['direction'], r['source']) for r in rebrickable] == [('Undone', 'rebrickable'), ('Pulled', 'rebrickable')]
        brickset = _log(db, source='brickset')
        assert len(brickset) == 20 and {r['source'] for r in brickset} == {'brickset'}
        assert _log(db)[-1]['source'] == 'brickset'   # the hub's log is the newest 20 of every site


def test_site_page_ignores_a_pull_of_another_site(client, remote, pair):
    with closing(connect(pair)) as db:
        pull = _event(db, 'receipt', '1', {'source': 'rebrickable', 'counts': {}})
        db.commit()
    assert soup(client.get(f'/workbench/sync/rebrickable?pulled={pull}')).select_one('form.sy-undo')
    assert soup(client.get(f'/workbench/sync/brickset?pulled={pull}')).select_one('form.sy-undo') is None
    assert soup(client.get('/workbench/sync/rebrickable?pulled=999999')).select_one('form.sy-undo') is None
    for odd in ('%C2%B2', '9' * 30, '-1', 'x'):   # a superscript digit, past SQLite's integer, signed, not a number: the page, not a 500
        assert soup(client.get(f'/workbench/sync/rebrickable?pulled={odd}')).select_one('form.sy-undo') is None
        assert client.get(f'/manage/sync?pulled={odd}').status_code == 302


def test_undo_refuses_a_pull_of_another_site(client, remote, pair):
    with closing(connect(pair)) as db:
        pull = _event(db, 'receipt', '1', {'source': 'rebrickable', 'counts': {}})
        db.commit()
    csrf = csrf_token(client)
    assert client.post('/manage/sync/brickset/undo', data={'csrf_token': csrf, 'event': str(pull)}).status_code == 404
    assert client.post('/manage/sync/rebrickable/undo', data={'csrf_token': csrf, 'event': '9' * 30}).status_code == 400
    with closing(connect(pair)) as db:
        assert db.execute('SELECT COUNT(*) FROM event_undo WHERE event_id=?', (pull,)).fetchone()[0] == 0


def test_the_key_day_is_the_last_good_call_and_a_replaced_key_does_not_inherit_it():
    """#686: "checked 18 Nov" on the Rebrickable page is the newest successful call, never older than the key's save time."""
    from brickwork.web.sync_site import _key_checked_day
    assert _key_checked_day({'saved_at': '2026-11-10T09:00:00.000Z'}, '2026-11-18T12:00:00+00:00') == '18 Nov'
    assert _key_checked_day({'saved_at': '2026-11-20T09:00:00+00:00'}, '2026-11-18T12:00:00.000Z') is None      # the key was replaced after the last call
    assert _key_checked_day({'saved_at': None}, '2026-11-18T12:00:00Z') == '18 Nov'                         # an environment key has no save time
    assert _key_checked_day({'saved_at': '2026-11-10T09:00:00Z'}, None) is None and _key_checked_day(None, 'x') is None
