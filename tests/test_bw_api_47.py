"""#47: the four contract operations that had no route. Invented data."""
from contextlib import closing
import os

from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app, create  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

ADMIN = {'Authorization': 'Bearer synthetic-bootstrap'}


def post(app, path, json=None, key=None, method='post', headers=ADMIN):
    h = dict(headers, **({'Idempotency-Key': key} if key else {}))
    return getattr(app.test_client(), method)('/api/v1' + path, json=json, headers=h)


def test_check_start_answer_and_key_required(populated):
    assert post(populated, '/copies/c1/check', {'action': 'start'}).status_code == 428
    made = post(populated, '/copies/c1/check', {'action': 'start'}, 'check-start-1')
    assert made.status_code == 200, made.json
    assert 'rows' in made.json['data'] and 'session' in made.json['data']
    replay = post(populated, '/copies/c1/check', {'action': 'start'}, 'check-start-1')
    assert replay.json['idempotent_replay']
    assert post(populated, '/copies/c1/check', {'action': 'explode'}, 'check-bad').status_code == 422
    assert post(populated, '/copies/nope/check', {'action': 'start'}, 'check-missing').status_code == 404


def test_resolve_leave_and_wrong_candidate(populated):
    body = {'source': 'rebrickable', 'kind': 'part', 'source_id': 'synthetic', 'selected': None}
    made = post(populated, '/unresolved/resolve', body, 'resolve-1')
    assert made.status_code == 200 and made.json['data']['source_id'] == 'synthetic'
    wrong = post(populated, '/unresolved/resolve', dict(body, selected=['P', 'not-a-candidate']), 'resolve-2')
    assert wrong.status_code == 409
    assert post(populated, '/unresolved/resolve', dict(body, selected='P 3001'), 'resolve-3').status_code == 422


def test_prices_refresh_queues_jobs(populated, monkeypatch):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    made = post(populated, '/prices/refresh', key='refresh-1')
    assert made.status_code == 200, made.json
    assert isinstance(made.json['data']['jobs'], list) and made.json['data']['skipped'] == []


def test_patch_settings_scope_one_event_and_validation(populated):
    writer = create(populated, 'writer', ['write']).json['data']['secret']
    assert post(populated, '/settings', {'retail_country': 'US'}, 's0', 'patch', {'Authorization': 'Bearer ' + writer}).status_code == 403
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        before = db.execute('SELECT max(id) FROM events').fetchone()[0]
    made = post(populated, '/settings', {'retail_country': 'US', 'incomplete_discount_pct': 25,
                                         'repair': {'shipping': '4.00'}, 'freshness': []}, 's1', 'patch')
    assert made.status_code == 200, made.json
    data = made.json['data']
    assert data['retail_country'] == 'US' and data['incomplete_discount_pct'] == 25.0 and data['repair']['shipping'] == '4.00'
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute('SELECT count(*) FROM events WHERE id>?', (before,)).fetchone()[0] == 1
    assert post(populated, '/settings', {'nope': 1}, 's2', 'patch').status_code == 422
    assert post(populated, '/settings', {'import_order': {'S': ['identity']}}, 's3', 'patch').status_code == 422
    assert post(populated, '/settings', {'retail_country': 'FR'}, 's4', 'patch').status_code == 422
    assert populated.test_client().get('/api/v1/settings', headers=ADMIN).json['data']['retail_country'] == 'US'
