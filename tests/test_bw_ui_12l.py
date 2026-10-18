"""UI-12l: Catalogues & keys as a table, key cards, and every state the frame names."""
from contextlib import closing
import json
import re
import sqlite3

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import secrets
from brickwork.core.connect import connect
from brickwork.core.sources import base
from brickwork.web import admin_ops
from tests.test_bw_admin import bw
from tests.test_bw_api_m5_web import BL_ENV, fake, stored, token
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps


@pytest.fixture
def keyed(app, bw, monkeypatch):
    monkeypatch.delenv('BW_BRICKSET_API_KEY', raising=False)
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY', raising=False)
    for name in BL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    secrets.forget()
    return app


def page(client, query=''):
    response = client.get('/manage/catalogues' + query)
    assert response.status_code == 200
    return response.get_data(as_text=True), BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def card(soup, source):
    return soup.find(attrs={'data-key-card': source})


def post(client, csrf, **data):
    return client.post('/manage/catalogues', data={'csrf_token': csrf, **data}, follow_redirects=True).get_data(as_text=True)


def test_sources_are_rows_with_names_toggles_and_short_dates(keyed, bw):
    with closing(connect(bw)) as db, db:
        db.execute("INSERT OR IGNORE INTO sources VALUES('bricklink_catalogue','bricklink_catalogue','file',1,NULL)")
        db.execute("INSERT INTO jobs(kind,source,state,created_at,updated_at) VALUES('import','rebrickable','done','2026-10-16T09:00:00+00:00','2026-10-16T09:12:44.262655+00:00')")
    html, soup = page(logged_in(keyed))
    rows = soup.select('form.bk-row')
    assert rows and all(r.find('input', {'name': 'csrf_token'}) and r.find('input', {'name': 'action', 'value': 'source'}) for r in rows)
    names = [r.select_one('.bk-name').get_text() for r in rows]
    assert 'BrickLink catalogue' in names and 'bricklink_catalogue' not in names
    toggle = rows[0].find('input', {'name': 'enabled'})
    assert toggle['type'] == 'checkbox' and toggle['role'] == 'switch' and toggle.has_attr('checked')
    assert 'Save source' not in html and 'Save<span class="sr"> ' in html
    assert '16 Oct · 09:12' in html
    assert not re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', html)
    assert {r.select_one('.bk-pill').get_text() for r in rows} <= {'Configured', 'Not set', 'No key needed', 'Rejected'}


def test_toggle_still_saves_through_the_row_form(keyed, bw):
    client = logged_in(keyed)
    csrf = token(client)
    post(client, csrf, action='source', source='rebrickable')
    with closing(sqlite3.connect(bw)) as db:
        assert db.execute("SELECT enabled FROM sources WHERE source='rebrickable'").fetchone()[0] == 0
    post(client, csrf, action='source', source='rebrickable', enabled='yes')
    with closing(sqlite3.connect(bw)) as db:
        assert db.execute("SELECT enabled FROM sources WHERE source='rebrickable'").fetchone()[0] == 1


def test_no_keys_and_catalogue_not_loaded(keyed, bw):
    html, soup = page(logged_in(keyed))
    assert 'No keys yet. Names, prices and pictures need at least a Rebrickable key.' in html
    assert 'Not loaded' in soup.find(id='catalogues').get_text()
    assert soup.find(id='catalogues').select_one('.bk-primary').get_text() == 'Load catalogue'
    for source in ('bricklink', 'rebrickable', 'brickset'):
        assert card(soup, source).select_one('.bk-pill').get_text() == 'Not set'
        assert card(soup, source).find('button', attrs={'data-key-submit': True})
    assert len(card(soup, 'bricklink').find_all('input', {'type': 'password'})) == 4
    assert [i['name'] for i in card(soup, 'rebrickable').find_all('input', {'type': 'password'})] == ['key:key']
    assert 'Key entry is disabled' not in html


def test_budget_used_up_banner_and_cell(keyed, bw):
    day = base.now().date().isoformat()
    with closing(connect(bw)) as db, db:
        db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", ('source:used:rebrickable:' + day, '1000'))
    html, soup = page(logged_in(keyed))
    assert 'Rebrickable budget used up for today. Updates wait until 00:00 UTC.' in html
    assert 'used up · resets 00:00 UTC' in html and '1000 / 1000' in html


def test_entry_disabled_without_the_secret(keyed, bw, monkeypatch):
    monkeypatch.delenv('BW_SECRET_KEY')
    html, soup = page(logged_in(keyed))
    assert 'Key entry is disabled' in card(soup, 'rebrickable').get_text()
    assert not card(soup, 'rebrickable').find('input', {'type': 'password'})


def test_loaded_catalogue_pill_and_counts(keyed, bw, monkeypatch):
    monkeypatch.setattr(admin_ops, 'catalogue_status', lambda: {'bricklink': dict(
        available=True, loaded_at='2026-10-16T05:57:29+00:00', counts={'S': 21893, 'P': 76519})})
    html, soup = page(logged_in(keyed))
    box = soup.find(id='catalogues')
    assert 'Loaded · 16 Oct' in box.get_text() and '2 types · 98,412 names' in box.get_text()
    assert box.select_one('.bk-primary') is None and 'Load colours' in box.get_text()
    assert '21,893' in box.get_text()


def test_freshness_and_pictures_cards(keyed, bw):
    html, soup = page(logged_in(keyed))
    fresh = soup.find(id='freshness-summary')
    assert 'BrickLink prices' in fresh.get_text() and '7 days' in fresh.get_text()
    assert fresh.find('a', href=re.compile('/manage/settings#freshness'))
    pics = soup.find(id='picture-order')
    assert 'Rebrickable · BrickLink' in pics.get_text() and 'Sets and wishlist' in pics.get_text() and 'Parts per colour' in pics.get_text()
    assert pics.find('a', href=re.compile('#picture-priority'))


def test_test_and_save_keeps_a_working_key_and_never_echoes_it(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    value = fake()
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0, 'name': 'Black'}))
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': value})
    assert 'Saved · The key works' in html and value not in html
    assert len(stored(bw)) == 1
    soup = BeautifulSoup(html, 'html.parser')
    assert card(soup, 'rebrickable').select_one('.bk-pill').get_text() == 'Configured'
    buttons = [b.get_text() for b in card(soup, 'rebrickable').select('.bk-btn')]
    assert buttons == ['Test key', 'Replace', 'Remove']
    assert 'Configured · saved' in card(soup, 'rebrickable').get_text()


def test_rejected_key_is_not_kept_and_the_card_says_so(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    value = fake()
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'detail': 'Invalid token ' + request.headers['Authorization']}))
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': value})
    assert value not in html
    soup = BeautifulSoup(html, 'html.parser')
    box = card(soup, 'rebrickable')
    assert box.select_one('.bk-pill').get_text() == 'Rejected' and box.select_one('.bk-error-box')
    assert 'Rebrickable key rejected.' in html
    assert box.find('input', {'type': 'password'}) and not stored(bw) or stored(bw)[0][2] is not None
    # The outcome is shown once.
    assert 'Rebrickable key rejected.' not in page(client)[0]


def test_replace_that_is_rejected_restores_the_earlier_key(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    first = fake()
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': first})
    before = stored(bw)
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'detail': 'Invalid token.'}))
    post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert stored(bw) == before


def test_replace_link_opens_entry_with_cancel(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    html, soup = page(client, '?replace=rebrickable')
    box = card(soup, 'rebrickable')
    assert box.find('input', {'type': 'password'}) and box.find('a', string='Cancel')


def test_remove_shows_the_removed_state_and_undo_restores(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    html = post(client, csrf, action='key_remove', source='rebrickable')
    soup = BeautifulSoup(html, 'html.parser')
    box = card(soup, 'rebrickable')
    assert 'Rebrickable key removed.' in box.get_text() and box.select_one('.bk-pill').get_text() == 'Removed'
    undo = box.find('form')
    assert undo.find('input', {'name': 'csrf_token'}) and undo.find('input', {'name': 'action'})['value'] == 'key_undo'
    html = post(client, csrf, action='key_undo', source='rebrickable', event=undo.find('input', {'name': 'event'})['value'])
    assert card(BeautifulSoup(html, 'html.parser'), 'rebrickable').select_one('.bk-pill').get_text() == 'Configured'
    assert stored(bw)[0][2] is None


def test_undo_refuses_another_sources_event(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    post(client, csrf, action='key_remove', source='rebrickable')
    event = sqlite3.connect(bw).execute("SELECT max(id) FROM events WHERE entity='source_key:rebrickable'").fetchone()[0]
    post(client, csrf, action='key_undo', source='brickset', event=event)
    assert stored(bw)[0][2] is not None


@pytest.mark.parametrize('csrf', [None, 'wrong'])
def test_test_and_save_requires_csrf(keyed, bw, csrf):
    client = logged_in(keyed)
    client.get('/manage/catalogues')
    data = {'action': 'key_test_save', 'source': 'rebrickable', 'key:key': fake()}
    if csrf:
        data['csrf_token'] = csrf
    assert client.post('/manage/catalogues', data=data).status_code == 400 and not stored(bw)


def test_every_key_form_carries_csrf_and_no_value(keyed, bw):
    html, soup = page(logged_in(keyed))
    for form in soup.select('[data-key-card] form'):
        assert len(form.find_all('input', {'name': 'csrf_token'})) == 1 and form['method'] == 'post'
        assert all(not i.has_attr('value') for i in form.find_all('input', {'type': 'password'}))


def refuse(request):
    return json.dumps({'detail': 'Invalid token.'})


def broken(request):
    raise OSError('connection reset')


def save_ok(client, csrf, monkeypatch):
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})


@pytest.mark.parametrize('transport', [broken, lambda request: '<html>502 Bad Gateway</html>', lambda request: json.dumps({'detail': 'Server error'})])
def test_non_authoritative_failures_keep_the_key_and_do_not_say_rejected(keyed, bw, monkeypatch, transport):
    client = logged_in(keyed)
    csrf = token(client)
    monkeypatch.setattr(base, 'transport', transport)
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Saved · Not tested:' in html and 'Rejected' not in html and 'rejected' not in html
    assert len(stored(bw)) == 1 and stored(bw)[0][2] is None
    assert card(BeautifulSoup(html, 'html.parser'), 'rebrickable').select_one('.bk-pill').get_text() == 'Configured'


def test_authoritative_refusal_rolls_back(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    monkeypatch.setattr(base, 'transport', refuse)
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Rebrickable key rejected.' in html
    rows = stored(bw)
    assert len(rows) == 1 and rows[0][2] is not None


def test_rejected_replacement_says_so_on_the_card_and_keeps_the_old_key(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    save_ok(client, csrf, monkeypatch)
    before = stored(bw)
    monkeypatch.setattr(base, 'transport', refuse)
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    soup = BeautifulSoup(html, 'html.parser')
    box = card(soup, 'rebrickable')
    assert stored(bw) == before
    assert 'New key rejected: Rebrickable API unsuccessful · the saved key is unchanged' in box.select_one('.bk-error-box').get_text()
    assert box.select_one('.bk-pill').get_text() == 'Configured' and [b.get_text() for b in box.select('.bk-btn')] == ['Test key', 'Replace', 'Remove']
    assert 'Rejected' not in html and 'key rejected.' not in html
    row = next(r for r in soup.select('form.bk-row') if r.select_one('.bk-name').get_text() == 'Rebrickable')
    assert row.select_one('.bk-pill').get_text() == 'Configured'


def test_failed_test_key_claims_rejection_only_for_an_authoritative_refusal(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    save_ok(client, csrf, monkeypatch)
    monkeypatch.setattr(base, 'transport', broken)
    html = post(client, csrf, action='key_test', source='rebrickable')
    assert 'Rejected' not in html and 'could not be reached' in html
    monkeypatch.setattr(base, 'transport', refuse)
    html = post(client, csrf, action='key_test', source='rebrickable')
    soup = BeautifulSoup(html, 'html.parser')
    assert card(soup, 'rebrickable').select_one('.bk-pill').get_text() == 'Rejected'
    assert card(soup, 'rebrickable').select_one('.bk-error-box')
    row = next(r for r in soup.select('form.bk-row') if r.select_one('.bk-name').get_text() == 'Rebrickable')
    assert row.select_one('.bk-pill').get_text() == 'Rejected' and 'Rebrickable key rejected.' in html
    assert len(stored(bw)) == 1 and stored(bw)[0][2] is None


def test_rollback_uses_the_receipt_of_its_own_save(keyed, bw, monkeypatch):
    from brickwork.core import keys
    client = logged_in(keyed)
    csrf = token(client)
    save_ok(client, csrf, monkeypatch)
    before = stored(bw)
    real = keys.check
    def interleaved(db, source, **options):
        # A later event for the same source must not be mistaken for this call's save.
        with db:
            db.execute("INSERT INTO events(entity,field,old_value,new_value,at,via) VALUES('source_key:rebrickable','save','null','{}','2026-10-16T10:00:00+00:00','app')")
        return real(db, source, **options)
    monkeypatch.setattr(keys, 'check', interleaved)
    monkeypatch.setattr(base, 'transport', refuse)
    post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert stored(bw) == before


def test_remove_undo_uses_the_removal_receipt(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    save_ok(client, csrf, monkeypatch)
    html = post(client, csrf, action='key_remove', source='rebrickable')
    event = int(card(BeautifulSoup(html, 'html.parser'), 'rebrickable').find('input', {'name': 'event'})['value'])
    with closing(sqlite3.connect(bw)) as db:
        assert event == db.execute("SELECT max(id) FROM events WHERE entity='source_key:rebrickable' AND field='archive'").fetchone()[0]
        with db:
            db.execute("INSERT INTO events(entity,field,old_value,new_value,at,via) VALUES('source_key:rebrickable','archive','null','{}','2026-10-16T10:00:00+00:00','app')")
    post(client, csrf, action='key_undo', source='rebrickable', event=event)
    assert stored(bw)[0][2] is None


@pytest.mark.parametrize('source,reply,refused', [
    ('bricklink', {'meta': {'code': 401, 'message': 'INVALID_TOKEN'}}, True),
    ('bricklink', {'meta': {'code': 403, 'message': 'PERMISSION'}}, True),
    ('bricklink', {'meta': {'code': 401, 'message': 'TOKEN_IP_MISMATCHED'}}, False),
    ('bricklink', {'meta': {'code': 500, 'message': 'ERR'}}, False),
    ('rebrickable', {'detail': 'Invalid token.'}, True),
    ('rebrickable', {'detail': 'Authentication credentials were not provided.'}, True),
    ('rebrickable', {'detail': 'Not found.'}, False),
    ('brickset', {'status': 'error', 'message': 'Invalid API key'}, True),
    ('brickset', {'status': 'error', 'message': 'Server busy'}, False),
])
def test_only_an_authentication_refusal_is_a_key_rejection(keyed, bw, monkeypatch, source, reply, refused):
    from brickwork.core import keys, source_ops
    values = {f: fake() for f in keys.fields(source)}
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps(reply))
    with closing(connect(bw)) as db:
        source_ops.ensure(db, source)
        keys.save(db, source, values)
        with pytest.raises(base.SourceError) as caught:
            keys.check(db, source)
        assert isinstance(caught.value, base.KeyRejected) is refused


def status_reply(code, body):
    reply = base.Reply(body)
    reply.status = code
    return reply


REFUSALS = {
    'bricklink': json.dumps({'meta': {'code': 401, 'message': 'INVALID_TOKEN', 'description': 'token invalid'}}),
    'rebrickable': json.dumps({'detail': 'Some other wording for a bad key.'}),
    'brickset': json.dumps({'status': 'error', 'message': 'API key not valid'}),
}


@pytest.mark.parametrize('source', ['bricklink', 'rebrickable', 'brickset'])
@pytest.mark.parametrize('code', [401, 403])
def test_http_401_and_403_with_the_sources_json_error_refuse_the_key(keyed, bw, monkeypatch, source, code):
    from brickwork.core import keys, source_ops
    body = REFUSALS[source].replace('401', str(code))
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(code, body))
    with closing(connect(bw)) as db:
        source_ops.ensure(db, source)
        keys.save(db, source, {f: fake() for f in keys.fields(source)})
        with pytest.raises(base.KeyRejected):
            keys.check(db, source)


@pytest.mark.parametrize('source', ['bricklink', 'rebrickable', 'brickset'])
@pytest.mark.parametrize('code', [401, 403])
@pytest.mark.parametrize('body', ['Forbidden', '<html>Attention Required! Cloudflare</html>', '', json.dumps(['x'])])
def test_non_json_401_and_403_do_not_refuse_the_key(keyed, bw, monkeypatch, source, code, body):
    from brickwork.core import keys, source_ops
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(code, body))
    with closing(connect(bw)) as db:
        source_ops.ensure(db, source)
        keys.save(db, source, {f: fake() for f in keys.fields(source)})
        with pytest.raises(base.SourceError) as caught:
            keys.check(db, source)
        assert not isinstance(caught.value, base.KeyRejected)


@pytest.mark.parametrize('message', ['TOKEN_IP_MISMATCHED', 'BAD_OAUTH_REQUEST', 'TIMESTAMP_OUT_OF_RANGE', 'NONCE_USED'])
def test_bricklink_401_for_a_non_key_reason_is_not_a_refusal(keyed, bw, monkeypatch, message):
    from brickwork.core import keys, source_ops
    body = json.dumps({'meta': {'code': 401, 'message': message}})
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(401, body))
    with closing(connect(bw)) as db:
        source_ops.ensure(db, 'bricklink')
        keys.save(db, 'bricklink', {f: fake() for f in keys.fields('bricklink')})
        with pytest.raises(base.SourceError) as caught:
            keys.check(db, 'bricklink')
        assert not isinstance(caught.value, base.KeyRejected)


def test_keyless_source_keeps_its_plain_error(keyed, bw):
    from brickwork.core.sources.brickognize import Brickognize
    with closing(connect(bw)) as db:
        client = Brickognize(db, http=lambda request: status_reply(401, json.dumps({'detail': 'nope'})))
        assert client.credentials == ()
        # A keyless source has no key to refuse: its 401 is handled exactly as before.
        result = client.request('probe', {}, __import__('urllib.request').request.Request('https://example.invalid/'), lambda value: value)
        assert result == {'detail': 'nope'}


def test_html_403_on_a_replacement_keeps_the_new_key_untested(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(403, '<html>Cloudflare</html>'))
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Saved · Not tested' in html and 'rejected' not in html.lower()
    assert len(stored(bw)) == 1 and stored(bw)[0][2] is None


@pytest.mark.parametrize('action', ['key_save', 'key_test_save'])
def test_saving_is_refused_while_an_environment_key_is_set(keyed, bw, monkeypatch, action):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    monkeypatch.setattr(base, 'transport', lambda request: pytest.fail('no call may be made'))
    client = logged_in(keyed)
    html = post(client, token(client), action=action, source='rebrickable', **{'key:key': fake()})
    assert 'This key comes from the environment' in html and 'Source key' in html and not stored(bw)


def test_failure_labels_name_the_key_actions(keyed, bw, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    client = logged_in(keyed)
    html = post(client, token(client), action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Source key ·' in html


@pytest.mark.parametrize('code,body', [(500, 'oops'), (502, '<html>bad gateway</html>'), (404, 'Not found'), (401, 'TOKEN_IP_MISMATCHED')])
def test_other_statuses_are_not_a_key_refusal(keyed, bw, monkeypatch, code, body):
    from brickwork.core import keys, source_ops
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(code, body))
    with closing(connect(bw)) as db:
        source_ops.ensure(db, 'bricklink')
        keys.save(db, 'bricklink', {f: fake() for f in keys.fields('bricklink')})
        with pytest.raises(base.SourceError) as caught:
            keys.check(db, 'bricklink')
        assert not isinstance(caught.value, base.KeyRejected)


def test_refused_replacement_by_status_restores_the_working_key(keyed, bw, monkeypatch):
    client = logged_in(keyed)
    csrf = token(client)
    save_ok(client, csrf, monkeypatch)
    before = stored(bw)
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(403, json.dumps({'detail': 'Invalid API key.'})))
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert stored(bw) == before and 'New key rejected' in html and 'Not tested' not in html


def test_failed_rollback_is_reported_not_hidden(keyed, bw, monkeypatch, caplog):
    from brickwork.core import keys
    client = logged_in(keyed)
    csrf = token(client)
    save_ok(client, csrf, monkeypatch)
    monkeypatch.setattr(base, 'transport', refuse)
    monkeypatch.setattr(keys, 'undo', lambda *a, **k: (_ for _ in ()).throw(ValueError('boom')))
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Nothing was saved' not in html
    assert 'The earlier key could not be restored' in html and 'Rebrickable key rejected.' in html
    assert 'key rollback failed for rebrickable (ValueError)' in caplog.text


def test_missing_receipt_means_no_rollback_id_and_no_undo_link(keyed, bw, monkeypatch):
    from brickwork.core import keys
    client = logged_in(keyed)
    csrf = token(client)
    monkeypatch.setattr(keys, '_audit', lambda *a, **k: None)
    save_ok(client, csrf, monkeypatch)
    html = post(client, csrf, action='key_remove', source='rebrickable')
    box = card(BeautifulSoup(html, 'html.parser'), 'rebrickable')
    assert 'key removed.' in box.get_text() and box.find('form') is None
    # A refusal with no receipt cannot be rolled back; it says so instead of failing.
    monkeypatch.setattr(base, 'transport', refuse)
    html = post(client, csrf, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'The earlier key could not be restored' in html and 'Nothing was saved' not in html
