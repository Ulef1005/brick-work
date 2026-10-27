"""#68: small web defects on the 4.0 store (M.8i part 1: lists print, tokens and the export).

The drainer re-check moved to `test_pipeline_jobs.py` and the not-set-up notice for Add to `test_bw_add.py` (M.8c); the Collection sync pages' notice is
M.8j's (`test_bw_small_68_sync.py`)."""
from contextlib import closing
import re

import pytest

from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)


@pytest.mark.parametrize('query', ['kind=x', '_anchor=x', '_method=POST', '_external=1', '_scheme=http'])
def test_print_list_ignores_url_for_keywords(client, world, query):
    response = client.get('/lists/wishlist/print?' + query, headers={'X-Forwarded-Host': 'evil.example'})
    assert response.status_code == 200
    assert 'evil.example' not in response.get_data(as_text=True)


def test_a_resent_token_form_creates_nothing(client, coll, world):
    page = client.get('/manage/tokens?create=1').get_data(as_text=True)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    form_id = re.search(r'name="form_id" value="([^"]+)"', page).group(1)
    form = {'csrf_token': csrf_token, 'action': 'create', 'name': 'resent', 'scopes': ['read'], 'form_id': form_id}
    assert client.post('/manage/tokens', data=form).status_code == 200
    again = client.post('/manage/tokens', data=form)
    assert again.status_code == 409 and 'shown only once' in again.get_data(as_text=True)
    assert coll.db.execute("SELECT count(*) FROM api_token WHERE name='resent'").fetchone()[0] == 1
    # A form that failed (the name exists) is not "sent": the same id may be submitted again with another name.
    taken = dict(form, name='resent', form_id='0' * 32)
    assert client.post('/manage/tokens', data=taken).status_code == 409
    assert client.post('/manage/tokens', data=dict(taken, name='resent two')).status_code == 200


def test_read_only_export_writes_no_event(client, coll, world, monkeypatch):
    before = coll.db.execute('SELECT count(*) FROM event').fetchone()[0]
    monkeypatch.setenv('BW_READ_ONLY', '1')
    response = client.get('/manage/database/export')
    assert response.status_code == 200
    assert coll.db.execute('SELECT count(*) FROM event').fetchone()[0] == before
