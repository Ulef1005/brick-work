"""UI-12m: API tokens page. Shown-once secret, revoke with confirm and Undo, CSRF, read-only."""
import json
import re
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, tokens
from tests.test_bw_admin import migrated_bw, reset_shell_metadata_after_test  # noqa: F401
from tests.importer.test_importer import legacy  # noqa: F401
from tests.web_fixtures import app, apps, logged_in  # noqa: F401


def csrf(client):
    client.get('/manage/tokens')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def stored(db_path):
    with sqlite3.connect(db_path) as db:
        return list(db.iterdump())


def make(db_path, name, scopes):
    with admin.database(db_path) as db:
        return tokens.create(db, name, scopes)


def test_hub_links_to_tokens(app, migrated_bw):
    html = logged_in(app).get('/manage/tools').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    link = soup.select_one('a.bw-hub-row[href="/manage/tokens"]')
    assert link and 'API tokens' in link.get_text()


def test_requires_login(app, migrated_bw):
    client = app.test_client()
    assert client.get('/manage/tokens').status_code in (302, 401)
    assert client.post('/manage/tokens', data={'action': 'revoke', 'id': 'x'}).status_code in (302, 400, 401)


def test_empty_state(app, migrated_bw, monkeypatch):
    monkeypatch.delenv('BW_API_TOKEN', raising=False)
    soup = BeautifulSoup(logged_in(app).get('/manage/tokens').get_data(as_text=True), 'html.parser')
    assert soup.select_one('h1').get_text() == 'API tokens'
    empty = soup.select_one('.bw-tk-empty')
    assert 'No tokens yet.' in empty.get_text()
    assert 'Create one for each script or agent, with only the scopes it needs.' in empty.get_text()
    assert empty.select_one('[data-token-create-open]')
    assert not soup.select('.bw-tk-table')


def test_list_marks_environment_token_and_hides_secrets(app, migrated_bw, monkeypatch):
    monkeypatch.setenv('BW_API_TOKEN', 'env-secret-value')
    result, _ = make(migrated_bw, 'Toni house agent', ['read', 'write'])
    make(migrated_bw, 'Spreadsheet export', ['read'])
    response = logged_in(app).get('/manage/tokens')
    html = response.get_data(as_text=True)
    assert response.headers['Cache-Control'] == 'no-store'
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.select_one('.bw-tk-table')
    names = [s.get_text() for s in table.select('.bw-tk-name strong')]
    assert names == ['Spreadsheet export', 'Toni house agent', 'Install environment']  # tokens.listing order
    assert [c.get_text() for c in table.select('.bw-tk-chips')[1].select('.bw-tk-chip')] == ['read', 'write']
    assert 'From the install environment · cannot be revoked here' in table.get_text()
    assert len(table.select('.bw-tk-env')) == 1 and table.select_one('.bw-tk-env').get_text() == 'Environment'
    assert len(table.select('a[data-token-revoke]')) == 2  # the environment token has no Revoke
    assert result['secret'] not in html and 'env-secret-value' not in html
    assert soup.select_one('[data-token-shown]') is None


def test_create_shows_secret_once_with_copy(app, migrated_bw):
    client = logged_in(app)
    response = client.post('/manage/tokens', data={'csrf_token': csrf(client), 'action': 'create',
                                                   'name': 'Toni house agent', 'scopes': ['read', 'write']})
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
    shown = soup.select_one('[data-token-shown]')
    secret = shown.select_one('[data-token-value]').get_text().strip()
    assert len(secret) >= 40
    assert 'Your new token' in shown.get_text() and 'Copy it now. It cannot be shown again.' in shown.get_text()
    assert shown.select_one('[data-token-copy]').get_text() == 'Copy'
    assert [c.get_text() for c in shown.select('.bw-tk-chip')] == ['read', 'write']
    assert 'Toni house agent' in shown.get_text()
    # The secret authenticates, is stored only as a hash, and never appears again.
    with admin.database(migrated_bw) as db:
        assert tokens.authenticate(db, secret)['name'] == 'Toni house agent'
    assert secret not in '\n'.join(stored(migrated_bw))
    for path in ('/manage/tokens', '/manage/tokens?create=1', '/manage/tools'):
        assert secret not in client.get(path).get_data(as_text=True)


def test_create_does_not_log_secret(app, migrated_bw, caplog):
    client = logged_in(app)
    with caplog.at_level('DEBUG'):
        html = client.post('/manage/tokens', data={'csrf_token': csrf(client), 'action': 'create',
                                                   'name': 'Quiet', 'scopes': ['read']}).get_data(as_text=True)
    secret = re.search(r'data-token-value>([^<]+)<', html)[1]
    assert secret not in caplog.text


def test_create_validation_keeps_input_and_writes_nothing(app, migrated_bw):
    client = logged_in(app)
    token = csrf(client)
    before = stored(migrated_bw)
    for data, message in (({'name': 'bootstrap', 'scopes': ['read']}, 'bootstrap is reserved'),
                          ({'name': 'No scope'}, 'Choose read, write or admin scopes'),
                          ({'name': 'Bad', 'scopes': ['root']}, 'Choose read, write or admin scopes')):
        response = client.post('/manage/tokens', data={'csrf_token': token, 'action': 'create', **data})
        assert response.status_code == 422
        soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
        assert message in soup.select_one('.bw-tk-error').get_text()
        assert soup.select_one('[data-token-create]').has_attr('open')
        assert soup.select_one('[data-token-create] input[name=name]')['value'] == data['name']
        assert soup.select_one('[data-token-shown]') is None
    assert stored(migrated_bw) == before


def test_duplicate_name_is_refused(app, migrated_bw):
    make(migrated_bw, 'Same', ['read'])
    client = logged_in(app)
    response = client.post('/manage/tokens', data={'csrf_token': csrf(client), 'action': 'create', 'name': 'Same', 'scopes': ['read']})
    assert response.status_code == 409
    assert 'Token name already exists' in response.get_data(as_text=True)


def test_create_dialog_lists_three_scopes(app, migrated_bw):
    soup = BeautifulSoup(logged_in(app).get('/manage/tokens?create=1').get_data(as_text=True), 'html.parser')
    dialog = soup.select_one('[data-token-create]')
    assert dialog.has_attr('open')
    assert [i['value'] for i in dialog.select('input[name=scopes]')] == ['read', 'write', 'admin']
    assert [i.has_attr('checked') for i in dialog.select('input[name=scopes]')] == [True, True, False]
    assert dialog.select_one('input[name=csrf_token]')['value']


def test_revoke_confirm_state_then_revoke_and_undo(app, migrated_bw):
    result, _ = make(migrated_bw, 'Spreadsheet export', ['read'])
    ident = result['token']['id']
    client = logged_in(app)
    token = csrf(client)
    soup = BeautifulSoup(client.get('/manage/tokens?revoke=' + ident).get_data(as_text=True), 'html.parser')
    confirm = soup.select_one('[data-token-confirm]')
    assert confirm.has_attr('open')
    assert confirm.select_one('h2').get_text() == 'Revoke Spreadsheet export?'
    assert 'Scripts using it stop working at once. You can undo for a short while.' in confirm.get_text()
    assert confirm.select_one('input[name=id]')['value'] == ident
    # A GET never revokes.
    with admin.database(migrated_bw) as db:
        assert tokens.authenticate(db, result['secret'])['name'] == 'Spreadsheet export'
    response = client.post('/manage/tokens', data={'csrf_token': token, 'action': 'revoke', 'id': ident})
    assert response.status_code == 302 and '/manage/tokens?revoked=' in response.headers['Location']
    page = client.get(response.headers['Location'])
    soup = BeautifulSoup(page.get_data(as_text=True), 'html.parser')
    assert 'Spreadsheet export revoked. Calls with it now fail.' in soup.select_one('.bw-tk-banner').get_text()
    assert not soup.select('.bw-tk-table')  # the revoked token is gone from the list
    with admin.database(migrated_bw) as db:
        with pytest.raises(Exception):
            tokens.authenticate(db, result['secret'])
        event = db.execute("SELECT id FROM events WHERE entity='bw_token' AND field='revoke'").fetchone()[0]
    undo = soup.select_one('.bw-tk-banner form')
    assert undo.select_one('input[name=event]')['value'] == str(event)
    back = client.post('/manage/tokens', data={'csrf_token': token, 'action': 'undo', 'event': str(event)})
    assert back.status_code == 302
    with admin.database(migrated_bw) as db:
        assert tokens.authenticate(db, result['secret'])['name'] == 'Spreadsheet export'
        assert db.execute("SELECT count(*) FROM events WHERE entity='bw_token' AND field LIKE 'undo:%'").fetchone()[0] == 1
    page = client.get('/manage/tokens').get_data(as_text=True)
    assert 'Spreadsheet export' in page and 'bw-tk-banner' not in page


def test_revoke_banner_is_only_for_revoke_events(app, migrated_bw):
    make(migrated_bw, 'A', ['read'])
    with admin.database(migrated_bw, read_only=True) as db:
        create_event = db.execute("SELECT id FROM events WHERE entity='bw_token'").fetchone()[0]
    client = logged_in(app)
    assert 'bw-tk-banner' not in client.get(f'/manage/tokens?revoked={create_event}').get_data(as_text=True)
    assert 'bw-tk-banner' not in client.get('/manage/tokens?revoked=junk').get_data(as_text=True)


@pytest.mark.parametrize('data', [{'action': 'create', 'name': 'x', 'scopes': ['read']}, {'action': 'revoke', 'id': 'x'}, {'action': 'undo', 'event': '1'}])
@pytest.mark.parametrize('token', [None, 'wrong'])
def test_csrf_rejects_every_post_without_writes(app, migrated_bw, data, token):
    client = logged_in(app)
    client.get('/manage/tokens')
    before = stored(migrated_bw)
    form = dict(data)
    if token:
        form['csrf_token'] = token
    response = client.post('/manage/tokens', data=form)
    assert response.status_code == 400 and b'Invalid CSRF token' in response.data
    assert stored(migrated_bw) == before


def test_every_post_form_has_one_token_field(app, migrated_bw):
    result, _ = make(migrated_bw, 'A', ['read'])
    client = logged_in(app)
    token = csrf(client)
    client.post('/manage/tokens', data={'csrf_token': token, 'action': 'revoke', 'id': result['token']['id']})
    soup = BeautifulSoup(client.get('/manage/tokens?revoked=1&create=1&revoke=none').get_data(as_text=True), 'html.parser')
    forms = soup.select('main form[method=post]')
    assert len(forms) >= 2
    for form in forms:
        assert len(form.select('input[name=csrf_token]')) == 1


def test_read_only_instance_refuses_writes_and_hides_actions(app, migrated_bw):
    result, _ = make(migrated_bw, 'A', ['read'])
    client = logged_in(app)
    token = csrf(client)
    app.config['BW_READ_ONLY'] = True
    try:
        before = stored(migrated_bw)
        for data in ({'action': 'create', 'name': 'B', 'scopes': ['read']}, {'action': 'revoke', 'id': result['token']['id']}, {'action': 'undo', 'event': '1'}):
            assert client.post('/manage/tokens', data={'csrf_token': token, **data}).status_code == 403
        assert stored(migrated_bw) == before
        soup = BeautifulSoup(client.get('/manage/tokens').get_data(as_text=True), 'html.parser')
        assert not soup.select('[data-token-create-open], [data-token-revoke], [data-token-create]')
        assert 'Changes are switched off' in soup.get_text()
    finally:
        app.config['BW_READ_ONLY'] = False


def test_cross_site_post_is_refused(app, migrated_bw):
    client = logged_in(app)
    token = csrf(client)
    response = client.post('/manage/tokens', data={'csrf_token': token, 'action': 'create', 'name': 'x', 'scopes': ['read']},
                           headers={'Origin': 'https://evil.example'})
    assert response.status_code == 403


def test_unknown_action_and_missing_db(app, migrated_bw):
    client = logged_in(app)
    assert client.post('/manage/tokens', data={'csrf_token': csrf(client), 'action': 'nope'}).status_code == 400


def test_query_count_is_flat(app, migrated_bw):
    for i in range(12):
        make(migrated_bw, f'T{i}', ['read'])
    counts = []
    import brickwork.core.admin as core_admin
    original = core_admin.database
    statements = []
    from contextlib import contextmanager

    @contextmanager
    def traced(path, **kw):
        with original(path, **kw) as db:
            db.set_trace_callback(lambda sql: statements.append(sql))
            yield db
    import brickwork.web.admin_ops as ops
    core_admin.database = traced
    try:
        logged_in(app).get('/manage/tokens')
    finally:
        core_admin.database = original
    selects = [s for s in statements if 'api_tokens' in s]
    assert len(selects) == 1


def test_revoked_param_is_validated(app, migrated_bw):
    client = logged_in(app)
    for value in ('%C2%B2', '9' * 5000, 'x', '-1', ''):
        response = client.get('/manage/tokens?revoked=' + value)
        assert response.status_code == 200 and 'bw-tk-banner' not in response.get_data(as_text=True)


def test_dates_use_stored_value_without_conversion(app, migrated_bw):
    make(migrated_bw, 'Dated', ['read'])
    with admin.database(migrated_bw) as db, db:
        db.execute("UPDATE api_tokens SET created_at='2026-10-02T23:30:00+00:00', last_used_at='2026-10-14T22:10:00+00:00'")
    soup = BeautifulSoup(logged_in(app).get('/manage/tokens').get_data(as_text=True), 'html.parser')
    dates = [d.get_text() for d in soup.select('.bw-tk-table .bw-tk-date')]
    assert dates == ['2 Oct 2026', '14 Oct, 22:10']


@pytest.mark.parametrize('payload', [None, 'null', '[1]', '"x"', '{"id":"1"}', '{not json'])
def test_revoke_banner_survives_bad_event_payload(app, migrated_bw, payload):
    # Events are append-only, so a malformed payload is inserted as a new row.
    with admin.database(migrated_bw) as db, db:
        event = db.execute("INSERT INTO events(entity,field,old_value,new_value,at,via,actor) VALUES('bw_token','revoke',NULL,?,'2026-10-16T00:00:00+00:00','app',NULL)", (payload,)).lastrowid
    response = logged_in(app).get(f'/manage/tokens?revoked={event}')
    html = response.get_data(as_text=True)
    assert response.status_code == 200 and 'not available' not in html
    assert 'Token revoked. Calls with it now fail.' in html
    assert 'name="action" value="undo"' not in html  # no Undo for an unreadable event


def test_missing_database_shows_error_page(app, migrated_bw):
    client = logged_in(app)
    token = csrf(client)
    migrated_bw.unlink()
    response = client.get('/manage/tokens')
    assert response.status_code == 200 and 'database is not available' in response.get_data(as_text=True)
    assert client.post('/manage/tokens', data={'csrf_token': token, 'action': 'revoke', 'id': 'x'}).status_code in (302, 400, 500)


@pytest.mark.parametrize('payload', [None, 'null', '[1]', '{"id":"1"}', '{not json'])
def test_forged_undo_of_unreadable_event_is_400(app, migrated_bw, payload):
    with admin.database(migrated_bw) as db, db:
        event = db.execute("INSERT INTO events(entity,field,old_value,new_value,at,via,actor) VALUES('bw_token','revoke',NULL,?,'2026-10-16T00:00:00+00:00','app',NULL)", (payload,)).lastrowid
    client = logged_in(app)
    response = client.post('/manage/tokens', data={'csrf_token': csrf(client), 'action': 'undo', 'event': str(event)})
    assert response.status_code == 400


@pytest.mark.parametrize('value', ['9' * 19, '9' * 5000, '\u00b2', '-1', 'x', ''])
def test_undo_event_id_is_bounded(app, migrated_bw, value):
    client = logged_in(app)
    response = client.post('/manage/tokens', data={'csrf_token': csrf(client), 'action': 'undo', 'event': value})
    assert response.status_code == 400


def test_readable_revoke_still_shows_undo(app, migrated_bw):
    result, _ = make(migrated_bw, 'A', ['read'])
    with admin.database(migrated_bw) as db:
        _, event = tokens.revoke(db, result['token']['id'])
    html = logged_in(app).get(f'/manage/tokens?revoked={event}').get_data(as_text=True)
    assert 'name="action" value="undo"' in html


def test_undo_window_closes_after_ten_minutes(app, migrated_bw, monkeypatch):
    from datetime import timedelta
    from brickwork.web import token_rows
    result, _ = make(migrated_bw, 'Old leak', ['read'])
    with admin.database(migrated_bw) as db:
        _, event = tokens.revoke(db, result['token']['id'])
    assert token_rows.UNDO_WINDOW == timedelta(minutes=10)
    monkeypatch.setattr(token_rows, 'UNDO_WINDOW', timedelta(seconds=-1))
    client = logged_in(app)
    html = client.get(f'/manage/tokens?revoked={event}').get_data(as_text=True)
    assert 'Old leak revoked.' in html and 'name="action" value="undo"' not in html
    response = client.post('/manage/tokens', data={'csrf_token': csrf(client), 'action': 'undo', 'event': str(event)})
    assert response.status_code == 400
    with admin.database(migrated_bw) as db:
        with pytest.raises(Exception):
            tokens.authenticate(db, result['secret'])


def test_second_undo_reports_already_undone(app, migrated_bw):
    result, _ = make(migrated_bw, 'Twice', ['read'])
    with admin.database(migrated_bw) as db:
        _, event = tokens.revoke(db, result['token']['id'])
    client = logged_in(app)
    token = csrf(client)
    client.post('/manage/tokens', data={'csrf_token': token, 'action': 'undo', 'event': str(event)})
    client.post('/manage/tokens', data={'csrf_token': token, 'action': 'undo', 'event': str(event)})
    page = client.get('/manage/tokens').get_data(as_text=True)
    assert 'Token change already undone' in page


def test_broken_expiry_value_does_not_hide_the_list(app, migrated_bw):
    result, _ = make(migrated_bw, 'Odd expiry', ['read'])
    with admin.database(migrated_bw) as db, db:
        db.execute("UPDATE api_tokens SET expires_at='not a date' WHERE id=?", (result['token']['id'],))
    html = logged_in(app).get('/manage/tokens').get_data(as_text=True)
    assert 'Odd expiry' in html and 'database is not available' not in html
