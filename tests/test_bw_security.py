"""Security hardening: admin-scoped Undo, one read-only rule for the browser, CSRF on check-parts, request errors."""
import pytest

from tests.test_bw_api_m1 import app, create as token_create  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401
from tests.test_bw_api_m5 import call, fake, put, secret, source, wire  # noqa: F401
from tests.test_bw_checker import bw  # noqa: F401
from tests.importer.test_importer import legacy  # noqa: F401
from tests.web_fixtures import apps, logged_in  # noqa: F401


def undo(app, event, token, key):
    return call(app, f'/events/{event}/undo', 'post', token=token, headers={'Idempotency-Key': key})


def test_write_token_cannot_undo_key_removal_or_source_toggle(populated, secret, wire):
    writer = token_create(populated, 'synthetic-writer', ['read', 'write']).json['data']['secret']
    put(populated, 'rebrickable', {'key': fake()})
    removed = call(populated, '/sources/rebrickable/key', 'delete', headers={'Idempotency-Key': 'remove'})
    assert removed.status_code == 200
    assert undo(populated, removed.json['event_id'], writer, 'w-undo-key').status_code == 403
    assert source(populated, 'rebrickable')['key']['configured'] is False
    toggled = call(populated, '/sources/bricklink', 'patch', json={'enabled': False}, headers={'Idempotency-Key': 'toggle'})
    assert toggled.status_code == 200, toggled.text
    assert undo(populated, toggled.json['event_id'], writer, 'w-undo-toggle').status_code == 403
    assert source(populated, 'bricklink')['enabled'] is False
    # The admin bootstrap token still can.
    assert undo(populated, removed.json['event_id'], 'synthetic-bootstrap', 'a-undo-key').status_code == 200
    assert source(populated, 'rebrickable')['key']['configured'] is True


@pytest.mark.parametrize('path,data', [
    ('/manage/values', {'action': 'add'}),
    ('/workbench/storage/action/save', {'name': 'Probe'}),
    ('/workbench/check-parts/copy', {'action': 'start'}),
])
def test_read_only_refuses_every_browser_write(bw, apps, path, data):
    app = apps('toni')
    app.config['BW_READ_ONLY'] = True
    client = logged_in(app)
    assert client.post(path, data=data).status_code == 403
    assert client.get('/workbench/check-parts').status_code == 200


def test_check_parts_post_needs_csrf(bw, apps):
    client = logged_in(apps('toni'))
    assert client.post('/workbench/check-parts/copy', json={'action': 'start', 'operation': 'x'}).status_code == 400
    assert client.post('/workbench/check-parts/copy', data={'action': 'start'}).status_code == 400


def test_non_ascii_password_is_refused_not_500(apps):
    app = apps('toni')
    response = app.test_client().post('/login', data={'password': 'pässwort'})
    assert response.status_code == 302 and 'wrong_password' in response.headers['Location']


def test_json_body_that_is_not_an_object_is_400(bw, apps):
    client = logged_in(apps('toni'))
    for path in ('/workbench/check-parts/copy', '/manage/add/review'):
        assert client.post(path, json=[1]).status_code == 400


def test_session_cookie_is_same_site_lax(apps):
    assert apps('toni').config['SESSION_COOKIE_SAMESITE'] == 'Lax'


def test_oversized_photo_is_refused_before_decoding(bw, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from brickwork.core import admin, collection
    out = BytesIO(); Image.new('L', (6000, 6000)).save(out, 'PNG')  # 36 MP, compresses to a few KB
    loaded = []
    monkeypatch.setattr(Image.Image, 'load', lambda self: loaded.append(1))
    with admin.database(bw) as db, pytest.raises(ValueError, match='smaller photo'):
        copy = db.execute('SELECT id FROM copies LIMIT 1').fetchone()[0]
        collection.photo(db, bw.parent, 'copy', copy, out.getvalue(), None)
    assert not loaded
