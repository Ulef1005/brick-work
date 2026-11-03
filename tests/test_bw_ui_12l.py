"""UI-12l on the 4.0 store (M.8i part 1, issue #110): Catalogues & keys as a table, key cards, and every state the frame names.

The key refusal rules (what the sources answer when a key is wrong) are tested here at the source; the encrypted store is in
test_source_keys.py and the page's write-only forms and secrecy in test_bw_api_m5_web.py."""
from contextlib import closing
import json
import re
import sqlite3
from urllib.request import Request

from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
import pytest

from brickwork.core import secrets
from brickwork.core.sources import base
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)
from tests.test_bw_api_m5_web import BL_ENV, fake, keyed, stored, token  # noqa: F401  (keyed is a fixture)


def page(client, query=''):
    response = client.get('/manage/catalogues' + query)
    assert response.status_code == 200
    return response.get_data(as_text=True), BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def card(soup, source):
    return soup.find(attrs={'data-key-card': source})


def post(client, csrf_token, **data):
    return client.post('/manage/catalogues', data={'csrf_token': csrf_token, **data}, follow_redirects=True).get_data(as_text=True)


def test_sources_are_rows_with_names_toggles_and_short_dates(client, keyed, coll, world):
    coll.sql("""INSERT INTO source_record(source,kind,key,payload,digest,bytes,fetched_at,status) VALUES('rebrickable','color','0','{}','d',2,'2026-10-16T09:12:44.262Z','success')""")
    html, soup = page(client)
    rows = soup.select('form.bk-row')
    assert rows and all(r.find('input', {'name': 'csrf_token'}) and r.find('input', {'name': 'action', 'value': 'source'}) for r in rows)
    names = [r.select_one('.bk-name').get_text() for r in rows]
    assert names == ['BrickLink', 'Rebrickable', 'Brickset', 'Brickognize']             # the sources with a client; the catalogue has its own card
    toggle = rows[0].find('input', {'name': 'enabled'})
    assert toggle['type'] == 'checkbox' and toggle['role'] == 'switch' and toggle.has_attr('checked')
    assert 'Save source' not in html and 'Save<span class="sr"> ' in html
    assert '16 Oct · 09:12' in html
    assert not re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', html)
    assert {r.select_one('.bk-pill').get_text() for r in rows} <= {'Configured', 'Not set', 'No key needed', 'Rejected'}


def test_toggle_still_saves_through_the_row_form(client, keyed, pair, world):
    csrf_token = token(client)
    post(client, csrf_token, action='source', source='rebrickable')
    with closing(sqlite3.connect(pair)) as db:
        assert db.execute("SELECT enabled FROM source WHERE id='rebrickable'").fetchone()[0] == 0
        assert db.execute("SELECT old_value,new_value FROM event WHERE entity_kind='source' AND entity_id='rebrickable'").fetchone() == ('1', '0')
    post(client, csrf_token, action='source', source='rebrickable', enabled='yes')
    with closing(sqlite3.connect(pair)) as db:
        assert db.execute("SELECT enabled FROM source WHERE id='rebrickable'").fetchone()[0] == 1


def test_no_keys_and_the_catalogue_card(client, keyed, world):
    html, soup = page(client)
    assert 'No keys yet. Names, prices and pictures need at least a Rebrickable key.' in html
    assert 'Loaded' in soup.find(id='catalogues').get_text()
    assert soup.find(id='catalogues').select_one('.bk-primary') is None                  # nothing to load from here: the card names the commands
    for source in ('bricklink', 'rebrickable', 'brickset'):
        assert card(soup, source).select_one('.bk-pill').get_text() == 'Not set'
        assert card(soup, source).find('button', attrs={'data-key-submit': True})
    assert len(card(soup, 'bricklink').find_all('input', {'type': 'password'})) == 4
    assert [i['name'] for i in card(soup, 'rebrickable').find_all('input', {'type': 'password'})] == ['key:key']
    assert 'Key entry is disabled' not in html


def test_budget_used_up_banner_and_cell(client, keyed, coll, world):
    day = base.now().date().isoformat()
    coll.sql("INSERT INTO source_budget(source,day,used) VALUES('rebrickable',?,1000)", (day,))
    html, soup = page(client)
    assert 'Rebrickable budget used up for today. Updates wait until 00:00 UTC.' in html
    assert 'used up · resets 00:00 UTC' in html and '1000 / 1000' in html


def test_entry_disabled_without_the_secret(client, keyed, world, monkeypatch):
    monkeypatch.delenv('BW_SECRET_KEY')
    html, soup = page(client)
    assert 'Key entry is disabled' in card(soup, 'rebrickable').get_text()
    assert not card(soup, 'rebrickable').find('input', {'type': 'password'})


def test_loaded_catalogue_pill_and_counts(client, keyed, coll, world):
    coll.sql("UPDATE catalogue_build SET reconciled_at='2026-10-23T13:00:00.000Z'")
    html, soup = page(client)
    box = soup.find(id='catalogues')
    assert 'Loaded · 23 Oct' in box.get_text() and '4 kinds · 18 items · 11 colours' in ' '.join(box.get_text().split())
    assert box.select_one('.bk-primary') is None and 'Last reconciled 23 Oct' in box.get_text()
    assert 'Parts 13' in ' '.join(box.get_text(' ').split())


def test_the_bricklink_item_lists_are_counted_when_loaded(client, keyed, pair, world):
    """The lists are part of the catalogue file (`catalogue import bricklink`); the card says how many items they hold."""
    assert 'BrickLink item lists not loaded' in ' '.join(page(client)[1].find(id='catalogues').get_text(' ').split())
    with closing(sqlite3.connect(pair.parent / 'catalogue.db')) as catalogue:
        build = catalogue.execute('SELECT min(id) FROM build').fetchone()[0]
        catalogue.executemany("INSERT INTO bricklink_item(item_type,item_no,name,name_key,build_id) VALUES('S',?,?,?,?)",
                              [(f'{n}-1', f'Set {n}', f'set {n}', build) for n in range(1, 4)])
        catalogue.commit()
    assert 'BrickLink item lists 3 items' in ' '.join(page(client)[1].find(id='catalogues').get_text(' ').split())


def test_freshness_and_pictures_cards(client, keyed, coll, world):
    from brickwork.core import admin
    admin.seed_freshness(coll.db)
    html, soup = page(client)
    fresh = soup.find(id='freshness-summary')
    assert 'BrickLink prices' in fresh.get_text() and '30 days' in fresh.get_text() and 'BrickLink pictures' in fresh.get_text()
    assert fresh.find('a', href=re.compile('/manage/settings#freshness'))
    pics = soup.find(id='picture-order')
    assert 'Rebrickable catalogue · BrickLink · Rebrickable API' in pics.get_text() and 'BrickLink · Rebrickable catalogue' in pics.get_text()
    assert 'Sets and wishlist' in pics.get_text() and 'Parts per colour' in pics.get_text()
    assert pics.find('a', href=re.compile('#picture-priority'))


def test_test_and_save_keeps_a_working_key_and_never_echoes_it(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    value = fake()
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0, 'name': 'Black'}))
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': value})
    assert 'Saved · The key works' in html and value not in html
    assert len(stored(pair)) == 1
    soup = BeautifulSoup(html, 'html.parser')
    assert card(soup, 'rebrickable').select_one('.bk-pill').get_text() == 'Configured'
    buttons = [b.get_text() for b in card(soup, 'rebrickable').select('.bk-btn')]
    assert buttons == ['Test key', 'Replace', 'Remove']
    assert 'Configured · saved' in card(soup, 'rebrickable').get_text()


def test_rejected_key_is_not_kept_and_the_card_says_so(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    value = fake()
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'detail': 'Invalid token ' + request.headers['Authorization']}))
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': value})
    assert value not in html
    soup = BeautifulSoup(html, 'html.parser')
    box = card(soup, 'rebrickable')
    assert box.select_one('.bk-pill').get_text() == 'Rejected' and box.select_one('.bk-error-box')
    assert 'Rebrickable key rejected.' in html
    assert box.find('input', {'type': 'password'}) and not stored(pair) or stored(pair)[0][2] is not None
    # The outcome is shown once.
    assert 'Rebrickable key rejected.' not in page(client)[0]


def test_replace_that_is_rejected_restores_the_earlier_key(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    first = fake()
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': first})
    before = stored(pair)
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'detail': 'Invalid token.'}))
    post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert stored(pair) == before


def test_replace_link_opens_entry_with_cancel(client, keyed, world, monkeypatch):
    csrf_token = token(client)
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    html, soup = page(client, '?replace=rebrickable')
    box = card(soup, 'rebrickable')
    assert box.find('input', {'type': 'password'}) and box.find('a', string='Cancel')


def test_remove_shows_the_removed_state_and_undo_restores(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    html = post(client, csrf_token, action='key_remove', source='rebrickable')
    soup = BeautifulSoup(html, 'html.parser')
    box = card(soup, 'rebrickable')
    assert 'Rebrickable key removed.' in box.get_text() and box.select_one('.bk-pill').get_text() == 'Removed'
    undo = box.find('form')
    assert undo.find('input', {'name': 'csrf_token'}) and undo.find('input', {'name': 'action'})['value'] == 'key_undo'
    html = post(client, csrf_token, action='key_undo', source='rebrickable', event=undo.find('input', {'name': 'event'})['value'])
    assert card(BeautifulSoup(html, 'html.parser'), 'rebrickable').select_one('.bk-pill').get_text() == 'Configured'
    assert stored(pair)[0][2] is None


def test_undo_refuses_another_sources_event(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    post(client, csrf_token, action='key_remove', source='rebrickable')
    event = sqlite3.connect(pair).execute("SELECT max(id) FROM event WHERE entity_kind='source_key' AND entity_id='rebrickable'").fetchone()[0]
    post(client, csrf_token, action='key_undo', source='brickset', event=event)
    assert stored(pair)[0][2] is not None


@pytest.mark.parametrize('csrf_value', [None, 'wrong'])
def test_test_and_save_requires_csrf(client, keyed, pair, world, csrf_value):
    client.get('/manage/catalogues')
    data = {'action': 'key_test_save', 'source': 'rebrickable', 'key:key': fake()}
    if csrf_value:
        data['csrf_token'] = csrf_value
    assert client.post('/manage/catalogues', data=data).status_code == 400 and not stored(pair)


def test_every_key_form_carries_csrf_and_no_value(client, keyed, world):
    html, soup = page(client)
    for form in soup.select('[data-key-card] form'):
        assert len(form.find_all('input', {'name': 'csrf_token'})) == 1 and form['method'] == 'post'
        assert all(not i.has_attr('value') for i in form.find_all('input', {'type': 'password'}))


def refuse(request):
    return json.dumps({'detail': 'Invalid token.'})


def broken(request):
    raise OSError('connection reset')


def save_ok(client, csrf_token, monkeypatch):
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps({'id': 0}))
    post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})


@pytest.mark.parametrize('transport', [broken, lambda request: '<html>502 Bad Gateway</html>', lambda request: json.dumps({'detail': 'Server error'})])
def test_non_authoritative_failures_keep_the_key_and_do_not_say_rejected(client, keyed, pair, world, monkeypatch, transport):
    csrf_token = token(client)
    monkeypatch.setattr(base, 'transport', transport)
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Saved · Not tested:' in html and 'Rejected' not in html and 'rejected' not in html
    assert len(stored(pair)) == 1 and stored(pair)[0][2] is None
    assert card(BeautifulSoup(html, 'html.parser'), 'rebrickable').select_one('.bk-pill').get_text() == 'Configured'


def test_authoritative_refusal_rolls_back(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    monkeypatch.setattr(base, 'transport', refuse)
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Rebrickable key rejected.' in html
    rows = stored(pair)
    assert len(rows) == 1 and rows[0][2] is not None


def test_rejected_replacement_says_so_on_the_card_and_keeps_the_old_key(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    save_ok(client, csrf_token, monkeypatch)
    before = stored(pair)
    monkeypatch.setattr(base, 'transport', refuse)
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    soup = BeautifulSoup(html, 'html.parser')
    box = card(soup, 'rebrickable')
    assert stored(pair) == before
    assert 'New key rejected: Rebrickable API unsuccessful · the saved key is unchanged' in box.select_one('.bk-error-box').get_text()
    assert box.select_one('.bk-pill').get_text() == 'Configured' and [b.get_text() for b in box.select('.bk-btn')] == ['Test key', 'Replace', 'Remove']
    assert 'Rejected' not in html and 'key rejected.' not in html
    row = next(r for r in soup.select('form.bk-row') if r.select_one('.bk-name').get_text() == 'Rebrickable')
    assert row.select_one('.bk-pill').get_text() == 'Configured'


def test_failed_test_key_claims_rejection_only_for_an_authoritative_refusal(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    save_ok(client, csrf_token, monkeypatch)
    monkeypatch.setattr(base, 'transport', broken)
    html = post(client, csrf_token, action='key_test', source='rebrickable')
    assert 'Rejected' not in html and 'could not be reached' in html
    monkeypatch.setattr(base, 'transport', refuse)
    html = post(client, csrf_token, action='key_test', source='rebrickable')
    soup = BeautifulSoup(html, 'html.parser')
    assert card(soup, 'rebrickable').select_one('.bk-pill').get_text() == 'Rejected'
    assert card(soup, 'rebrickable').select_one('.bk-error-box')
    row = next(r for r in soup.select('form.bk-row') if r.select_one('.bk-name').get_text() == 'Rebrickable')
    assert row.select_one('.bk-pill').get_text() == 'Rejected' and 'Rebrickable key rejected.' in html
    assert len(stored(pair)) == 1 and stored(pair)[0][2] is None


def test_rollback_uses_the_receipt_of_its_own_save(client, keyed, pair, world, monkeypatch):
    from brickwork.core import keys
    csrf_token = token(client)
    save_ok(client, csrf_token, monkeypatch)
    before = stored(pair)
    real = keys.check

    def interleaved(db, source, **options):
        # A later event for the same source must not be mistaken for this call's save.
        with db:
            db.execute("INSERT INTO event(at,via,entity_kind,entity_id,field,old_value,new_value) VALUES('2026-10-16T10:00:00.000Z','app','source_key','rebrickable','save',NULL,'{}')")
        return real(db, source, **options)
    monkeypatch.setattr(keys, 'check', interleaved)
    monkeypatch.setattr(base, 'transport', refuse)
    post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert stored(pair) == before


def test_remove_undo_uses_the_removal_receipt(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    save_ok(client, csrf_token, monkeypatch)
    html = post(client, csrf_token, action='key_remove', source='rebrickable')
    event = int(card(BeautifulSoup(html, 'html.parser'), 'rebrickable').find('input', {'name': 'event'})['value'])
    with closing(sqlite3.connect(pair)) as db:
        assert event == db.execute("SELECT max(id) FROM event WHERE entity_kind='source_key' AND entity_id='rebrickable' AND field='archive'").fetchone()[0]
        with db:
            db.execute("INSERT INTO event(at,via,entity_kind,entity_id,field,old_value,new_value) VALUES('2026-10-16T10:00:00.000Z','app','source_key','rebrickable','archive',NULL,'{}')")
    post(client, csrf_token, action='key_undo', source='rebrickable', event=event)
    assert stored(pair)[0][2] is None


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
def test_only_an_authentication_refusal_is_a_key_rejection(coll, keyed, monkeypatch, source, reply, refused):
    from brickwork.core import keys
    values = {f: fake() for f in keys.fields(source)}
    monkeypatch.setattr(base, 'transport', lambda request: json.dumps(reply))
    keys.save(coll.db, source, values)
    with pytest.raises(base.SourceError) as caught:
        keys.check(coll.db, source)
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
def test_http_401_and_403_with_the_sources_json_error_refuse_the_key(coll, keyed, monkeypatch, source, code):
    from brickwork.core import keys
    body = REFUSALS[source].replace('401', str(code))
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(code, body))
    keys.save(coll.db, source, {f: fake() for f in keys.fields(source)})
    with pytest.raises(base.KeyRejected):
        keys.check(coll.db, source)


@pytest.mark.parametrize('source', ['bricklink', 'rebrickable', 'brickset'])
@pytest.mark.parametrize('code', [401, 403])
@pytest.mark.parametrize('body', ['Forbidden', '<html>Attention Required! Cloudflare</html>', '', json.dumps(['x'])])
def test_non_json_401_and_403_do_not_refuse_the_key(coll, keyed, monkeypatch, source, code, body):
    from brickwork.core import keys
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(code, body))
    keys.save(coll.db, source, {f: fake() for f in keys.fields(source)})
    with pytest.raises(base.SourceError) as caught:
        keys.check(coll.db, source)
    assert not isinstance(caught.value, base.KeyRejected)


@pytest.mark.parametrize('message', ['TOKEN_IP_MISMATCHED', 'BAD_OAUTH_REQUEST', 'TIMESTAMP_OUT_OF_RANGE', 'NONCE_USED'])
def test_bricklink_401_for_a_non_key_reason_is_not_a_refusal(coll, keyed, monkeypatch, message):
    from brickwork.core import keys
    body = json.dumps({'meta': {'code': 401, 'message': message}})
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(401, body))
    keys.save(coll.db, 'bricklink', {f: fake() for f in keys.fields('bricklink')})
    with pytest.raises(base.SourceError) as caught:
        keys.check(coll.db, 'bricklink')
    assert not isinstance(caught.value, base.KeyRejected)


def test_keyless_source_keeps_its_plain_error(coll, keyed):
    from brickwork.core.sources.brickognize import Brickognize
    client = Brickognize(coll.db, http=lambda request: status_reply(401, json.dumps({'detail': 'nope'})))
    assert client.credentials == ()
    # A keyless source has no key to refuse: its 401 is handled exactly as before.
    result = client.request('probe', 'k', Request('https://example.invalid/'), lambda value: value)
    assert result == {'detail': 'nope'}


def test_html_403_on_a_replacement_keeps_the_new_key_untested(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(403, '<html>Cloudflare</html>'))
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Saved · Not tested' in html and 'rejected' not in html.lower()
    assert len(stored(pair)) == 1 and stored(pair)[0][2] is None


@pytest.mark.parametrize('action', ['key_save', 'key_test_save'])
def test_saving_is_refused_while_an_environment_key_is_set(client, keyed, pair, world, monkeypatch, action):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    monkeypatch.setattr(base, 'transport', lambda request: pytest.fail('no call may be made'))
    html = post(client, token(client), action=action, source='rebrickable', **{'key:key': fake()})
    assert 'This key comes from the environment' in html and 'Source key' in html and not stored(pair)


def test_failure_labels_name_the_key_actions(client, keyed, world, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    html = post(client, token(client), action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Source key ·' in html


@pytest.mark.parametrize('code,body', [(500, 'oops'), (502, '<html>bad gateway</html>'), (404, 'Not found'), (401, 'TOKEN_IP_MISMATCHED')])
def test_other_statuses_are_not_a_key_refusal(coll, keyed, monkeypatch, code, body):
    from brickwork.core import keys
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(code, body))
    keys.save(coll.db, 'bricklink', {f: fake() for f in keys.fields('bricklink')})
    with pytest.raises(base.SourceError) as caught:
        keys.check(coll.db, 'bricklink')
    assert not isinstance(caught.value, base.KeyRejected)


def test_refused_replacement_by_status_restores_the_working_key(client, keyed, pair, world, monkeypatch):
    csrf_token = token(client)
    save_ok(client, csrf_token, monkeypatch)
    before = stored(pair)
    monkeypatch.setattr(base, 'transport', lambda request: status_reply(403, json.dumps({'detail': 'Invalid API key.'})))
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert stored(pair) == before and 'New key rejected' in html and 'Not tested' not in html


def test_failed_rollback_is_reported_not_hidden(client, keyed, world, monkeypatch, caplog):
    from brickwork.core import keys
    csrf_token = token(client)
    save_ok(client, csrf_token, monkeypatch)
    monkeypatch.setattr(base, 'transport', refuse)
    monkeypatch.setattr(keys, 'undo', lambda *a, **k: (_ for _ in ()).throw(ValueError('boom')))
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'Nothing was saved' not in html
    assert 'The earlier key could not be restored' in html and 'Rebrickable key rejected.' in html
    assert 'key rollback failed for rebrickable (ValueError)' in caplog.text


def test_missing_receipt_means_no_rollback_id_and_no_undo_link(client, keyed, world, monkeypatch):
    from brickwork.core import keys
    csrf_token = token(client)
    monkeypatch.setattr(keys, '_audit', lambda *a, **k: None)
    save_ok(client, csrf_token, monkeypatch)
    html = post(client, csrf_token, action='key_remove', source='rebrickable')
    box = card(BeautifulSoup(html, 'html.parser'), 'rebrickable')
    assert 'key removed.' in box.get_text() and box.find('form') is None
    # A refusal with no receipt cannot be rolled back; it says so instead of failing.
    monkeypatch.setattr(base, 'transport', refuse)
    html = post(client, csrf_token, action='key_test_save', source='rebrickable', **{'key:key': fake()})
    assert 'The earlier key could not be restored' in html and 'Nothing was saved' not in html
