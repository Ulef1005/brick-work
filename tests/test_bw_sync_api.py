"""Collection sync through API v1 (#10). Split off test_bw_sync.py by M.8j: API v1 answers 410 on the 4.0 line and comes back as v2 in M.11 (the 3.3 text,
using the fakes and the `store` fixture of test_bw_sync, whose store is a 4.0 collection now; M.11 rewrites it)."""
from tests.test_bw_sync import *  # noqa: F401,F403
from tests.test_bw_sync import Rebrickable, PASSWORD, TOKEN, everything  # noqa: F401


def test_api_scopes_connect_pull_and_undo(store, monkeypatch):
    from flask import Flask
    from brickwork.api import register
    from brickwork.core.sync import adapters
    path = store.execute('PRAGMA database_list').fetchone()[2]
    remote = Rebrickable()
    monkeypatch.setattr(adapters, 'transport', remote)
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    monkeypatch.setenv('BW_DB_PATH', path)
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.delenv('BW_READ_ONLY', raising=False)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    register(app)
    client = app.test_client()
    admin = {'Authorization': 'Bearer synthetic-bootstrap'}

    def token(scope):
        return {'Authorization': 'Bearer ' + client.post('/api/v1/tokens', headers=admin,
                json={'name': scope + '-client', 'scopes': [scope]}).json['data']['secret']}
    reader, writer = token('read'), token('write')
    body = {'username': 'synthetic-user', 'password': PASSWORD}
    assert client.post('/api/v1/sources/rebrickable/user/connect', headers=writer, json=body).status_code == 403
    made = client.post('/api/v1/sources/rebrickable/user/connect', headers=dict(admin, **{'Idempotency-Key': 'connect-1'}), json=body)
    assert made.status_code == 200, made.json
    assert made.json['data']['user']['configured'] and PASSWORD not in made.get_data(as_text=True)
    assert PASSWORD not in everything(store) and TOKEN not in everything(store)
    assert client.get('/api/v1/sync/rebrickable', headers=reader).json['data']['credentials']['user']['configured']
    assert client.put('/api/v1/sync/rebrickable/link', headers=reader, json={'owned': [1, 2]}).status_code == 403
    assert client.put('/api/v1/sync/rebrickable/link', headers=writer, json={'owned': [1, 2], 'wishlist': 9, 'send_to': 1}).status_code == 200
    plan = client.post('/api/v1/sync/rebrickable/pull/plan', headers=writer)
    assert plan.status_code == 201, plan.json
    plan_id = plan.json['data']['id']
    applied = client.post('/api/v1/sync/rebrickable/pull/apply', headers=dict(writer, **{'Idempotency-Key': 'pull-1'}),
                          json={'plan_id': plan_id})
    assert applied.status_code == 200, applied.json
    replay = client.post('/api/v1/sync/rebrickable/pull/apply', headers=dict(writer, **{'Idempotency-Key': 'pull-1'}),
                         json={'plan_id': plan_id})
    assert replay.json['idempotent_replay'] and replay.json['event_id'] == applied.json['event_id']
    assert store.execute("SELECT count(*) FROM copies WHERE set_no='10001-1' AND archived_at IS NULL").fetchone()[0] == 2
    undone = client.post(f"/api/v1/events/{applied.json['event_id']}/undo", headers=dict(writer, **{'Idempotency-Key': 'undo-1'}))
    assert undone.status_code == 200, undone.json
    assert not store.execute("SELECT 1 FROM copies WHERE set_no='10001-1' AND archived_at IS NULL").fetchone()
    send = client.post('/api/v1/sync/rebrickable/send/plan', headers=writer).json['data']
    assert client.post('/api/v1/sync/rebrickable/send/apply', headers=writer, json={'plan_id': send['id']}).status_code == 403
    sent = client.post('/api/v1/sync/rebrickable/send/apply', headers=admin, json={'plan_id': send['id']})
    assert sent.status_code == 200 and 'not undone' in sent.json['data']['note']
    assert client.post('/api/v1/sync/bricklink/pull/plan', headers=writer).status_code == 404
