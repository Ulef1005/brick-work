"""Security hardening of the browser side on a 4.0 collection (ported from test_bw_security by M.11d, issue #113): one read-only rule for the
browser, CSRF on check-parts, request errors. The API half of that file (admin-scoped Undo) is tests/test_api2_write_sources.py."""
import pytest

from tests.app4 import app4, client, coll, pair, world  # noqa: F401
from tests.web_fixtures import logged_in


@pytest.mark.parametrize('path,data', [
    ('/manage/values', {'action': 'add'}),
    ('/workbench/storage/action/save', {'name': 'Probe'}),
    ('/workbench/check-parts/copy', {'action': 'start'}),
])
def test_read_only_refuses_every_browser_write(app4, world, path, data):
    app4.config['BW_READ_ONLY'] = True
    client = logged_in(app4)
    assert client.post(path, data=data).status_code == 403
    assert client.get('/workbench/check-parts').status_code == 200


def test_check_parts_post_needs_csrf(client, world):
    assert client.post('/workbench/check-parts/copy', json={'action': 'start', 'operation': 'x'}).status_code == 400
    assert client.post('/workbench/check-parts/copy', data={'action': 'start'}).status_code == 400


def test_non_ascii_password_is_refused_not_500(app4):
    response = app4.test_client().post('/login', data={'password': 'pässwort'})
    assert response.status_code == 302 and 'wrong_password' in response.headers['Location']


def test_json_body_that_is_not_an_object_is_400(client, world):
    for path in ('/workbench/check-parts/copy', '/manage/add/review'):
        assert client.post(path, json=[1]).status_code == 400


def test_session_cookie_is_same_site_lax(app4):
    assert app4.config['SESSION_COOKIE_SAMESITE'] == 'Lax'


def test_oversized_photo_is_refused_before_decoding(world, pair, monkeypatch):
    from contextlib import closing
    from io import BytesIO
    from PIL import Image
    from brickwork.core import collection
    from brickwork.core.connect import connect
    out = BytesIO()
    Image.new('L', (6000, 6000)).save(out, 'PNG')                       # 36 MP, compresses to a few KB
    loaded = []
    monkeypatch.setattr(Image.Image, 'load', lambda self: loaded.append(1))
    with closing(connect(pair)) as db, pytest.raises(ValueError, match='smaller photo'):
        collection.photo(db, pair.parent, 'copy', world.copy_a, out.getvalue(), None)
    assert not loaded
