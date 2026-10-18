"""#68: small web defects."""
from contextlib import closing
import os
import re

import pytest

from brickwork.core import drainer
from brickwork.core.connect import connect
from tests.web_fixtures import app, apps, logged_in  # noqa: F401


@pytest.mark.parametrize('query', ['kind=x', '_anchor=x', '_method=POST', '_external=1', '_scheme=http'])
def test_print_list_ignores_url_for_keywords(app, query):  # noqa: F811
    with closing(connect(os.environ['BW_DB_PATH'])):
        pass
    response = logged_in(app).get('/lists/wishlist/print?' + query, headers={'X-Forwarded-Host': 'evil.example'})
    assert response.status_code == 200
    assert 'evil.example' not in response.get_data(as_text=True)


@pytest.mark.parametrize('path', ['/collection/purchase-places', '/manage/sync', '/manage/sync/rebrickable/link'])
def test_pages_before_setup_show_the_notice(app, path, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'not-set-up' / 'brickwork.db'))
    response = logged_in(app).get(path)
    assert response.status_code == 503
    assert 'database is not available' in response.get_data(as_text=True)


def test_a_resent_token_form_creates_nothing(app):  # noqa: F811
    with closing(connect(os.environ['BW_DB_PATH'])):
        pass
    client = logged_in(app)
    page = client.get('/manage/tokens?create=1').get_data(as_text=True)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    form_id = re.search(r'name="form_id" value="([^"]+)"', page).group(1)
    form = {'csrf_token': csrf, 'action': 'create', 'name': 'resent', 'scopes': ['read'], 'form_id': form_id}
    assert client.post('/manage/tokens', data=form).status_code == 200
    again = client.post('/manage/tokens', data=form)
    assert again.status_code == 409 and 'shown only once' in again.get_data(as_text=True)
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute("SELECT count(*) FROM api_tokens WHERE name='resent'").fetchone()[0] == 1


def test_read_only_export_writes_no_event(app, monkeypatch):  # noqa: F811
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        before = db.execute('SELECT count(*) FROM events').fetchone()[0]
    monkeypatch.setenv('BW_READ_ONLY', '1')
    response = logged_in(app).get('/manage/database/export')
    assert response.status_code == 200
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == before


def test_drainer_rechecks_before_it_stops(tmp_path, monkeypatch):
    from flask import Flask
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '1')
    app = Flask('drain')
    rounds, pending = [], [True, False]
    monkeypatch.setattr(drainer, 'loop', lambda path, sleep: rounds.append(1))
    monkeypatch.setattr(drainer, 'poll_delay', lambda db: 0 if pending.pop(0) else None)
    monkeypatch.setattr(drainer, 'connect', lambda path: __import__('sqlite3').connect(':memory:'))
    started = []
    assert drainer.start(app, tmp_path / 'x.db', fallback=lambda run: started.append(run))
    assert drainer.start(app, tmp_path / 'x.db', fallback=lambda run: started.append(run))  # already active
    assert len(started) == 1
    started[0]()
    assert len(rounds) == 2  # a job found at the final check runs another round
    assert not app.extensions['bw_import_worker_active']
