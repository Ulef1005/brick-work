"""M5: jobs, sources, the encrypted key store and uploads. Mocked transports only."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets as token_source
import socket
from unittest.mock import Mock

from cryptography.fernet import Fernet
from PIL import Image
import pytest

from brickwork.api import operations
from brickwork.core import keys, secrets
from brickwork.core.connect import connect
from brickwork.core.sources import base, images
from tests.test_bw_api_m1 import app, create as token_create
from tests.test_bw_api_m1_contract import CONTRACT, validate
from tests.test_bw_api_m2 import OPS, concrete, populated
from tests.test_bw_api_m3 import dbrows

BL_ENV = ('BW_BRICKLINK_CONSUMER_KEY', 'BW_BRICKLINK_CONSUMER_SECRET', 'BW_BRICKLINK_TOKEN_VALUE', 'BW_BRICKLINK_TOKEN_SECRET')


def call(app, path, method='get', token='synthetic-bootstrap', headers=None, **kwargs):
    return getattr(app.test_client(), method)('/api/v1' + path, headers={'Authorization': 'Bearer ' + token, **(headers or {})}, **kwargs)


def fake(length=24):
    return token_source.token_hex(length // 2)


def bl(data):
    return json.dumps({'meta': {'code': 200}, 'data': data})


class Wire:
    """Records every outbound request and answers from `replies` by URL fragment."""

    def __init__(self):
        self.requests, self.replies = [], {}

    def __call__(self, request):
        self.requests.append(request)
        for fragment, reply in self.replies.items():
            if fragment in request.full_url:
                return reply(request) if callable(reply) else reply
        raise AssertionError('Unexpected outbound call ' + request.full_url.split('?')[0])


@pytest.fixture
def wire(monkeypatch):
    wire = Wire()
    monkeypatch.setattr(base, 'transport', wire)
    monkeypatch.setattr(images, 'transport', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    monkeypatch.setattr(operations, 'spawn', lambda target: wire.spawned.append(target))
    wire.spawned = []
    for name in (*BL_ENV, 'BW_REBRICKABLE_API_KEY', 'BW_BRICKSET_API_KEY', 'BW_SECRET_KEY',
                 'BW_EMBEDDED_WORKER', 'BW_BRICKOGNIZE_DAILY_BUDGET', 'BW_BRICKLINK_DAILY_BUDGET'):
        monkeypatch.delenv(name, raising=False)
    secrets.forget()
    return wire


@pytest.fixture
def secret(monkeypatch, wire):
    value = Fernet.generate_key().decode()
    monkeypatch.setenv('BW_SECRET_KEY', value)
    return value


def put(app, source, body, key=None, **kwargs):
    headers = {'Idempotency-Key': key} if key else {}
    return call(app, f'/sources/{source}/key', 'put', json=body, headers=headers, **kwargs)


def source(app, name):
    return next(r for r in call(app, '/sources').json['data'] if r['source'] == name)


def png(size=(64, 48), mode='RGB'):
    out = io.BytesIO()
    Image.new(mode, size, (200, 30, 30)).save(out, 'PNG')
    return out.getvalue()


def upload(app, path, content, name='x.png', mimetype='image/png', key=None, token='synthetic-bootstrap', extra=None):
    headers = {'Authorization': 'Bearer ' + token}
    if key: headers['Idempotency-Key'] = key
    return app.test_client().post('/api/v1' + path, headers=headers, content_type='multipart/form-data',
                                  data={'file': (io.BytesIO(content), name, mimetype), **(extra or {})})


def events(since=0):
    return [r for r in dbrows('events') if r['id'] > since]


def last_event():
    return dbrows('events')[-1]['id']


# --- key store -------------------------------------------------------------------------------

def test_put_key_is_encrypted_audited_and_write_only(populated, secret, wire):
    value = fake()
    before = last_event()
    response = put(populated, 'rebrickable', {'key': value})
    assert response.status_code == 200, response.text
    validate(response.json, CONTRACT['paths']['/sources/{source}/key']['put']['responses']['200']['content']['application/json']['schema'])
    assert response.json['data']['key'] == dict(configured=True, origin='stored', saved_at=response.json['data']['key']['saved_at'])
    assert value not in response.text
    row = dbrows('source_keys')[0]
    assert value not in row['ciphertext'] and secrets.decrypt(row['ciphertext']).count(value) == 1
    new = events(before)
    assert len(new) == 1 and (new[0]['via'], new[0]['actor']) == ('api', 'bootstrap')
    assert all(value not in json.dumps(r) and row['ciphertext'] not in json.dumps(r) for r in dbrows('events'))
    for name in os.listdir(Path(os.environ['BW_DB_PATH']).parent):
        path = Path(os.environ['BW_DB_PATH']).parent / name
        if path.is_file(): assert value.encode() not in path.read_bytes()
    assert call(populated, f'/events/{response.json["event_id"]}').json['data']['undoable'] is True
    assert source(populated, 'rebrickable')['key']['origin'] == 'stored'


def test_bricklink_takes_four_values_and_validates(populated, secret, wire):
    body = {'consumer_key': fake(), 'consumer_secret': fake(), 'token_value': fake(), 'token_secret': fake()}
    assert put(populated, 'bricklink', {'key': fake()}).status_code == 422
    assert put(populated, 'bricklink', {k: body[k] for k in list(body)[:3]}).status_code == 422
    assert put(populated, 'bricklink', body).status_code == 200
    assert keys.credentials(connect(os.environ['BW_DB_PATH']), 'bricklink', BL_ENV) == tuple(body.values())
    for bad in ({'key': 'short'}, {'key': 'has space in it 123'}, {'key': 12345678}, {'key': fake(), 'extra': 'x'}, {}):
        response = put(populated, 'rebrickable', bad)
        assert response.status_code == 422 and response.json['code'] == 'validation_failed'
        for v in bad.values(): assert str(v) not in response.text or v == 'short'
    assert put(populated, 'brickognize', {'key': fake()}).status_code == 422
    assert put(populated, 'nonesuch', {'key': fake()}).status_code == 404


def test_replace_remove_and_undo_restore_exact_key(populated, secret, wire):
    first, second = fake(), fake()
    db = lambda: closing(connect(os.environ['BW_DB_PATH']))
    names = ('BW_REBRICKABLE_API_KEY',)
    put(populated, 'rebrickable', {'key': first})
    second_event = put(populated, 'rebrickable', {'key': second}).json
    with db() as c: assert keys.credentials(c, 'rebrickable', names) == (second,)
    undone = call(populated, f'/events/{second_event["event_id"]}/undo', 'post', headers={'Idempotency-Key': 'undo-replace'})
    assert undone.status_code == 200, undone.text
    with db() as c: assert keys.credentials(c, 'rebrickable', names) == (first,)
    removed = call(populated, '/sources/rebrickable/key', 'delete', headers={'Idempotency-Key': 'remove-one'})
    assert removed.status_code == 200 and removed.json['data']['key']['configured'] is False
    assert call(populated, '/sources/rebrickable/key', 'delete').status_code == 404
    with db() as c, pytest.raises(base.SourceNotConfigured): keys.credentials(c, 'rebrickable', names)
    assert call(populated, f'/events/{removed.json["event_id"]}/undo', 'post', headers={'Idempotency-Key': 'undo-remove'}).status_code == 200
    with db() as c: assert keys.credentials(c, 'rebrickable', names) == (first,)
    # The first save's Undo is allowed again once the key is back in the state that save produced,
    # and then archives it (creation Undo archives); it is not undone twice.
    first_event = next(r['id'] for r in dbrows('events') if r['entity'] == 'bw_api' and 'source_key' in r['new_value'] and r['field'].startswith('op:') is False)
    assert call(populated, f'/events/{first_event}/undo', 'post', headers={'Idempotency-Key': 'undo-first'}).status_code == 200
    assert source(populated, 'rebrickable')['key']['configured'] is False
    assert call(populated, f'/events/{first_event}/undo', 'post', headers={'Idempotency-Key': 'undo-first-2'}).json['data']['already_undone'] is True


def test_creation_undo_archives_and_later_save_blocks_it(populated, secret, wire):
    first = put(populated, 'brickset', {'key': fake()}).json
    put(populated, 'brickset', {'key': fake()})
    blocked = call(populated, f'/events/{first["event_id"]}/undo', 'post', headers={'Idempotency-Key': 'undo-first'})
    assert blocked.status_code == 409 and blocked.json['code'] == 'undo_blocked'
    assert source(populated, 'brickset')['key']['configured'] is True


def test_environment_key_wins_over_stored(populated, secret, wire, monkeypatch):
    env_value, stored_value = fake(), fake()
    put(populated, 'rebrickable', {'key': stored_value})
    wire.replies['rebrickable.com'] = json.dumps({'id': 0, 'name': 'Black'})
    assert call(populated, '/sources/rebrickable/key/test', 'post').status_code == 200
    assert wire.requests[-1].headers['Authorization'] == 'key ' + stored_value
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', env_value)
    assert source(populated, 'rebrickable')['key']['origin'] == 'env'
    assert call(populated, '/sources/rebrickable/key/test', 'post').status_code == 200
    assert wire.requests[-1].headers['Authorization'] == 'key ' + env_value
    assert stored_value not in str(source(populated, 'rebrickable')) and env_value not in str(source(populated, 'rebrickable'))


def test_missing_secret_disables_entry_but_not_environment_keys(populated, wire, monkeypatch):
    response = put(populated, 'rebrickable', {'key': fake()})
    assert response.status_code == 424 and response.json['code'] == 'source_not_configured'
    assert 'BW_SECRET_KEY' in response.json['detail'] and not dbrows('source_keys')
    assert call(populated, '/sources').status_code == 200
    value = fake()
    monkeypatch.setenv('BW_BRICKSET_API_KEY', value)
    wire.replies['brickset.com'] = json.dumps({'status': 'success'})
    assert call(populated, '/sources/brickset/key/test', 'post').status_code == 200


def test_wrong_secret_fails_closed_without_detail(populated, secret, wire, monkeypatch):
    value = fake()
    put(populated, 'rebrickable', {'key': value})
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    response = call(populated, '/sources/rebrickable/key/test', 'post')
    assert response.status_code == 424 and response.json['code'] == 'source_not_configured'
    assert value not in response.text and 'Traceback' not in response.text
    assert not wire.requests


def test_key_idempotency_uses_keyed_fingerprint(populated, secret, wire):
    body = {'key': fake()}
    first = put(populated, 'rebrickable', body, key='key-replay')
    again = put(populated, 'rebrickable', body, key='key-replay')
    assert again.json['idempotent_replay'] is True and len(dbrows('source_keys')) == 1
    assert put(populated, 'rebrickable', {'key': fake()}, key='key-replay').status_code == 409
    saved = [r for r in dbrows('events') if r['field'] == 'op:key-replay'][0]['new_value']
    assert hashlib_sha(json.dumps({'source': 'rebrickable', 'fingerprint': ''})) not in saved
    assert body['key'] not in saved
    assert first.json['event_id'] == again.json['event_id']


def hashlib_sha(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def test_key_scopes_and_read_only(populated, secret, wire, monkeypatch):
    for scopes in (['read'], ['read', 'write']):
        token = token_create(populated, 'synthetic-' + '-'.join(scopes), scopes).json['data']['secret']
        assert put(populated, 'rebrickable', {'key': fake()}, token=token).status_code == 403
        assert call(populated, '/sources/rebrickable/key', 'delete', token=token).status_code == 403
        assert call(populated, '/sources/rebrickable/key/test', 'post', token=token).status_code == 403
        assert call(populated, '/sources/rebrickable', 'patch', token=token, json={'enabled': False}).status_code == 403
        assert call(populated, '/colors/sync', 'post', token=token).status_code == 403
        assert call(populated, '/catalogue/import', 'post', token=token).status_code == 403
    assert not dbrows('source_keys')
    monkeypatch.setenv('BW_READ_ONLY', '1')
    assert put(populated, 'rebrickable', {'key': fake()}).status_code == 403
    assert populated.test_client().put('/api/v1/sources/rebrickable/key', json={'key': fake()}).status_code == 401


def test_key_test_reports_no_key_material_and_is_budgeted(populated, secret, wire, monkeypatch):
    value = fake()
    put(populated, 'rebrickable', {'key': value})
    wire.replies['rebrickable.com'] = json.dumps({'id': 0, 'name': 'Black'})
    response = call(populated, '/sources/rebrickable/key/test', 'post')
    validate(response.json, CONTRACT['paths']['/sources/{source}/key/test']['post']['responses']['200']['content']['application/json']['schema'])
    assert response.json['data']['ok'] is True and response.json['undo_url'] is None and value not in response.text
    assert len(wire.requests) == 1
    assert source(populated, 'rebrickable')['used_today'] == 1
    # A failing key surfaces a redacted source error.
    wire.replies['rebrickable.com'] = lambda request: json.dumps({'detail': 'Invalid token ' + value})
    failed = call(populated, '/sources/rebrickable/key/test', 'post')
    assert failed.status_code == 502 and value not in failed.text and failed.json['code'] == 'source_error'
    assert call(populated, '/sources/brickognize/key/test', 'post').status_code == 422


# --- typed errors, budgets ------------------------------------------------------------------

def test_colour_sync_typed_errors_and_success(populated, secret, wire, monkeypatch):
    response = call(populated, '/colors/sync', 'post')
    assert response.status_code == 424 and response.json['code'] == 'source_not_configured' and response.json['source'] == 'bricklink'
    for name in BL_ENV: monkeypatch.setenv(name, fake())
    assert call(populated, '/sources/bricklink', 'patch', json={'enabled': False}).status_code == 200
    response = call(populated, '/colors/sync', 'post')
    assert response.status_code == 424 and response.json['code'] == 'source_disabled' and not wire.requests
    assert call(populated, '/sources/bricklink', 'patch', json={'enabled': True}).status_code == 200
    wire.replies['api.bricklink.com'] = bl([{'color_id': 3, 'color_name': 'Synthetic blue', 'color_type': 'Solid', 'color_code': '0000FF'}])
    before = last_event()
    response = call(populated, '/colors/sync', 'post', headers={'Idempotency-Key': 'sync-one'})
    assert response.status_code == 200, response.text
    validate(response.json, CONTRACT['paths']['/colors/sync']['post']['responses']['200']['content']['application/json']['schema'])
    assert response.json['data'] == dict(colors=1, added=1) and response.json['undo_url'] is None
    assert any(r['field'] == 'op:sync-one' for r in events(before))
    replay = call(populated, '/colors/sync', 'post', headers={'Idempotency-Key': 'sync-one'})
    assert replay.json['idempotent_replay'] is True and len(wire.requests) == 1


def test_budget_exhaustion_is_429_with_retry_after_and_job(populated, secret, wire, monkeypatch):
    for name in BL_ENV: monkeypatch.setenv(name, fake())
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    wire.replies['api.bricklink.com'] = bl([])
    assert call(populated, '/colors/sync', 'post').status_code == 200
    response = call(populated, '/colors/sync', 'post')
    assert response.status_code == 429 and response.json['code'] == 'budget_exhausted'
    assert int(response.headers['Retry-After']) == response.json['retry_after'] >= 1
    assert response.json['job_id'] and len(wire.requests) == 1
    validate(response.json, CONTRACT['components']['schemas']['Problem'])
    job = dbrows('jobs')[-1]
    assert (job['state'], job['id']) == ('waiting_for_budget', response.json['job_id']) and job['retry_at']
    assert call(populated, '/jobs/' + str(job['id'])).json['data']['state'] == 'waiting_for_budget'


def test_remote_throttle_is_429_source_throttled(populated, secret, wire, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    wire.replies['rebrickable.com'] = json.dumps({'detail': 'Request was throttled. Expected available in 37 seconds.'})
    response = call(populated, '/sources/rebrickable/key/test', 'post')
    assert response.status_code == 429 and response.json['code'] == 'source_throttled'
    assert 30 <= int(response.headers['Retry-After']) <= 37 and response.json['job_id']


def test_catalogue_import_and_not_loaded(populated, secret, wire, monkeypatch):
    base_dir = Path(os.environ['BW_DB_PATH']).parent
    response = call(populated, '/catalogue/import', 'post')
    assert response.status_code == 422 and 'XML' in response.json['detail'] and str(base_dir) not in response.text
    source_dir = base_dir / 'bricklink-catalog-src'
    source_dir.mkdir()
    for kind, name in zip('SMPIOGBC', ('Set', 'Minifig', 'Part', 'Instruction', 'Box', 'Gear', 'Book', 'Catalog')):
        (source_dir / (name + '.xml')).write_text(f'<CATALOG><ITEM><ITEMTYPE>{kind}</ITEMTYPE><ITEMID>{kind}1</ITEMID><ITEMNAME>Synthetic {name}</ITEMNAME></ITEM></CATALOG>')
    os.remove(base_dir / 'bricklink-catalog.db')
    response = call(populated, '/catalogue/import', 'post')
    assert response.status_code == 200, response.text
    validate(response.json, CONTRACT['paths']['/catalogue/import']['post']['responses']['200']['content']['application/json']['schema'])
    assert response.json['data']['loaded'] is True and response.json['data']['items']['S'] == 1
    assert call(populated, '/catalogue/status').json['data']['loaded'] is True


# --- jobs -----------------------------------------------------------------------------------

def queue_identity(populated, steps=('identity',), sources=None):
    from brickwork.core.pipeline import Pipeline
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        job = Pipeline(db).queue_steps('P', '3001', steps, sources=sources or ['bricklink'])
        db.commit()
    return job


ITEM = {'no': '3001', 'type': 'PART', 'name': 'Synthetic brick', 'category_id': 5, 'year_released': 2020}


def test_drain_runs_due_jobs_and_records_one_event(populated, secret, wire, monkeypatch):
    for name in BL_ENV: monkeypatch.setenv(name, fake())
    wire.replies['api.bricklink.com'] = bl(ITEM)
    job = queue_identity(populated)
    before = last_event()
    response = call(populated, '/jobs/drain', 'post', headers={'Idempotency-Key': 'drain-one'})
    assert response.status_code == 200, response.text
    validate(response.json, CONTRACT['paths']['/jobs/drain']['post']['responses']['200']['content']['application/json']['schema'])
    assert response.json['data']['jobs'][0]['id'] == job and response.json['data']['jobs'][0]['state'] == 'done'
    assert response.json['undo_url'] is None
    mine = [r for r in events(before) if r['entity'] == 'bw_api']
    assert len(mine) == 1 and mine[0]['actor'] == 'bootstrap'
    assert call(populated, '/jobs/drain', 'post', headers={'Idempotency-Key': 'drain-one'}).json['idempotent_replay'] is True
    assert call(populated, '/jobs/drain', 'post', json={'x': 1}).status_code == 400


def test_step_failures_are_typed_for_missing_key_disabled_source_and_catalogue(populated, secret, wire, monkeypatch):
    job = queue_identity(populated, ('identity', 'matching'), None)
    local = queue_identity(populated, ('identity',), ['bricklink:local'])
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE import_steps SET sources='[\"bricklink\"]' WHERE name='identity' AND job_id=?", (job,))
        db.execute("UPDATE import_steps SET sources='[\"rebrickable\"]' WHERE name='matching'")
        db.execute("INSERT OR IGNORE INTO sources(source,name,kind,enabled) VALUES('rebrickable','Rebrickable','api',0)")
        db.execute("UPDATE sources SET enabled=0 WHERE source='rebrickable'")
    os.remove(Path(os.environ['BW_DB_PATH']).with_name('bricklink-catalog.db'))
    assert call(populated, '/jobs/drain', 'post').status_code == 200
    steps = {s['name']: s for s in call(populated, f'/jobs/{job}').json['data']['steps']}
    assert steps['identity']['error_code'] == 'source_not_configured' and 'not configured' in steps['identity']['error']
    assert steps['matching']['error_code'] == 'source_disabled'
    assert call(populated, f'/jobs/{local}').json['data']['steps'][0]['error_code'] == 'catalogue_not_loaded'
    assert not wire.requests


def test_retry_resume_and_embedded_drainer(populated, secret, wire, monkeypatch):
    job = queue_identity(populated)
    assert call(populated, '/jobs/drain', 'post').status_code == 200   # fails: no key
    assert call(populated, f'/jobs/{job}').json['data']['steps'][0]['state'] == 'failed'
    for name in BL_ENV: monkeypatch.setenv(name, fake())
    wire.replies['api.bricklink.com'] = bl(ITEM)
    before = last_event()
    response = call(populated, f'/jobs/{job}/retry', 'post', json={'step': 'identity'}, headers={'Idempotency-Key': 'retry-one'})
    assert response.status_code == 202, response.text
    validate(response.json, CONTRACT['paths']['/jobs/{id}/retry']['post']['responses']['202']['content']['application/json']['schema'])
    assert response.headers['Location'] == f'/api/v1/jobs/{job}' and response.json['data']['state'] == 'queued'
    assert response.json['data']['steps'][0]['state'] == 'queued' and response.json['undo_url'] is None
    assert len([r for r in events(before) if r['entity'] == 'bw_api']) == 1
    assert len(wire.spawned) == 1                      # the embedded drainer starts by default
    replay = call(populated, f'/jobs/{job}/retry', 'post', json={'step': 'identity'}, headers={'Idempotency-Key': 'retry-one'})
    assert replay.json['idempotent_replay'] is True and len(wire.spawned) == 1
    wire.spawned.pop()(); populated.extensions['bw_import_worker_active'] = False
    done = call(populated, f'/jobs/{job}').json['data']
    assert done['state'] == 'done' and done['interrupted'] is False
    assert call(populated, f'/jobs/{job}/retry', 'post').status_code == 409          # nothing failed
    assert call(populated, f'/jobs/{job}/resume', 'post').status_code == 409         # done is not resumable
    assert call(populated, '/jobs/9999/retry', 'post').status_code == 404
    assert call(populated, f'/jobs/{job}/retry', 'post', json={'step': 'nonsense'}).status_code == 422


def test_embedded_drainer_can_be_disabled_and_runs_once(populated, secret, wire, monkeypatch):
    job = queue_identity(populated)
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE jobs SET state='running' WHERE id=?", (job,))
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    response = call(populated, f'/jobs/{job}/resume', 'post')
    assert response.status_code == 202 and response.json['data']['interrupted'] is True and not wire.spawned
    monkeypatch.delenv('BW_EMBEDDED_WORKER')
    assert call(populated, f'/jobs/{job}/resume', 'post', headers={'Idempotency-Key': 'again'}).status_code == 202
    assert call(populated, f'/jobs/{job}/resume', 'post', headers={'Idempotency-Key': 'again-2'}).status_code == 202
    assert len(wire.spawned) == 1                                                   # one drainer per app


def test_queued_job_waits_for_budget_then_resumes(populated, secret, wire, monkeypatch):
    for name in BL_ENV: monkeypatch.setenv(name, fake())
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    wire.replies['api.bricklink.com'] = bl(ITEM)
    first, second = queue_identity(populated), queue_identity(populated)
    ran = call(populated, '/jobs/drain', 'post').json['data']['jobs']
    states = {r['id']: r['state'] for r in ran}
    assert states[first] == 'done' and states[second] == 'waiting_for_budget'
    waiting = call(populated, f'/jobs/{second}').json['data']
    assert waiting['retry_at'] and datetime.fromisoformat(waiting['retry_at']) > datetime.now(timezone.utc)
    assert waiting['steps'][0]['state'] == 'waiting_for_budget'
    assert len(wire.requests) == 1
    resumed = call(populated, f'/jobs/{second}/resume', 'post')
    assert resumed.status_code == 202 and resumed.json['data']['state'] == 'waiting_for_budget'


def test_instruction_identities_and_pictures_queue(populated, secret, wire):
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I','BK-1','Synthetic booklet')")
    response = call(populated, '/jobs/instruction-identities', 'post')
    assert response.status_code == 202, response.text
    validate(response.json, CONTRACT['paths']['/jobs/instruction-identities']['post']['responses']['202']['content']['application/json']['schema'])
    assert len(response.json['data']['jobs']) == 1 and response.json['data']['jobs'][0]['item_no'] == 'BK-1'
    assert len(wire.spawned) == 1
    body = {'source': 'priority', 'scope': 'all', 'types': ['P', 'S']}
    queued = call(populated, '/jobs/pictures', 'post', json=body, headers={'Idempotency-Key': 'pics-1'})
    assert queued.status_code == 202, queued.text
    validate(queued.json, CONTRACT['paths']['/jobs/pictures']['post']['responses']['202']['content']['application/json']['schema'])
    assert queued.json['data']['kind'] == 'picture_refresh' and queued.headers['Location'].endswith(str(queued.json['data']['id']))
    again = call(populated, '/jobs/pictures', 'post', json=body, headers={'Idempotency-Key': 'pics-2'})
    assert again.status_code == 202 and again.json['data']['id'] == queued.json['data']['id']      # active job is reused
    payload = json.loads([r for r in dbrows('jobs') if r['id'] == queued.json['data']['id']][0]['payload'])
    assert (payload['via'], payload['actor']) == ('api', 'bootstrap')
    for bad in ({'source': 'priority'}, {'source': 'x', 'scope': 'all', 'types': ['P']}, {'source': 'priority', 'scope': 'all', 'types': []}, {'source': 'priority', 'scope': 'all', 'extra': 1}):
        assert call(populated, '/jobs/pictures', 'post', json=bad).status_code == 422


def test_source_toggle_audit_and_undo(populated, secret, wire):
    before = last_event()
    response = call(populated, '/sources/rebrickable', 'patch', json={'enabled': False})
    assert response.status_code == 200, response.text
    validate(response.json, CONTRACT['paths']['/sources/{source}']['patch']['responses']['200']['content']['application/json']['schema'])
    assert response.json['data']['enabled'] is False and len(events(before)) == 1
    assert source(populated, 'rebrickable')['enabled'] is False
    undone = call(populated, f'/events/{response.json["event_id"]}/undo', 'post', headers={'Idempotency-Key': 'toggle-undo'})
    assert undone.status_code == 200 and source(populated, 'rebrickable')['enabled'] is True
    assert call(populated, '/sources/nonesuch', 'patch', json={'enabled': True}).status_code == 404
    assert call(populated, '/sources/rebrickable', 'patch', json={'enabled': 'no'}).status_code == 422
    assert call(populated, '/sources/rebrickable', 'patch', json={}).status_code == 422


def test_fresh_install_lists_every_client_so_keys_can_be_entered(app, wire):
    names = {r['source'] for r in call(app, '/sources').json['data']}
    assert {'bricklink', 'rebrickable', 'brickset', 'brickognize'} <= names


def test_sources_list_query_count_does_not_grow_with_keys(populated, secret, wire):
    def count():
        statements = []
        with closing(connect(os.environ['BW_DB_PATH'])) as db:
            db.set_trace_callback(statements.append)
            from brickwork.core import api_reads
            api_reads.sources(db)
        return len(statements)
    empty = count()
    put(populated, 'rebrickable', {'key': fake()}); put(populated, 'brickset', {'key': fake()})
    put(populated, 'bricklink', {k: fake() for k in ('consumer_key', 'consumer_secret', 'token_value', 'token_secret')})
    assert count() == empty


# --- uploads --------------------------------------------------------------------------------

def test_photo_upload_for_copy_and_stock_with_undo(populated, wire):
    for path, table, template in (('/copies/c1/photos', 'item_images', '/copies/{id}/photos'), ('/stock/t1/photos', 'item_images', '/stock/{id}/photos')):
        before, files = len(dbrows(table)), len(list((Path(os.environ['BW_DB_PATH']).parent / 'data/images/own').glob('*')) if (Path(os.environ['BW_DB_PATH']).parent / 'data/images/own').exists() else [])
        response = upload(populated, path, png(), key='photo-' + path.split('/')[1], extra={'caption': 'Synthetic caption'})
        assert response.status_code == 200, response.text
        validate(response.json, CONTRACT['paths'][template]['post']['responses']['200']['content']['application/json']['schema'])
        assert len(dbrows(table)) == before + 1 and dbrows(table)[-1]['caption'] == 'Synthetic caption'
        assert response.json['undo_url'] and call(populated, f'/events/{response.json["event_id"]}').json['data']['undoable']
        assert upload(populated, path, png(), key='photo-' + path.split('/')[1], extra={'caption': 'Synthetic caption'}).json['idempotent_replay']
        undone = call(populated, f'/events/{response.json["event_id"]}/undo', 'post', headers={'Idempotency-Key': 'undo-' + path.split('/')[1]})
        assert undone.status_code == 200


def test_photo_limits_types_scopes_and_atomicity(populated, wire, monkeypatch):
    own = Path(os.environ['BW_DB_PATH']).parent / 'data/images/own'
    over = b'\x89PNG' + b'0' * (15 * 1024 * 1024)
    assert upload(populated, '/copies/c1/photos', over).status_code == 413
    assert upload(populated, '/copies/c1/photos', b'%PDF-1.4', mimetype='application/pdf').status_code == 415
    assert upload(populated, '/copies/c1/photos', b'not an image', mimetype='image/png').status_code == 422
    assert upload(populated, '/copies/c1/photos', b'').status_code == 422
    assert upload(populated, '/copies/absent/photos', png()).status_code == 404
    assert call(populated, '/copies/c1/photos', 'post', json={'x': 1}).status_code == 415
    reader = token_create(populated, 'synthetic-reader', ['read']).json['data']['secret']
    assert upload(populated, '/copies/c1/photos', png(), token=reader).status_code == 403
    assert not own.exists() or not list(own.glob('*.jpg'))
    # A failure after the file is written leaves no orphan.
    from brickwork.core import admin
    real = admin.audit
    def fail(db, entity, field, *a, **k):
        if entity == 'bw_api': raise RuntimeError('Synthetic failure')
        return real(db, entity, field, *a, **k)
    monkeypatch.setattr(admin, 'audit', fail)
    assert upload(populated, '/copies/c1/photos', png()).status_code == 500
    assert not own.exists() or not list(own.glob('*.jpg'))


BRICKOGNIZE = json.dumps({'items': [{'type': 'part', 'id': '3001', 'score': 0.93}, {'type': 'set', 'id': '100-1', 'score': 0.4}]})


def test_identification_upload_get_thumb_archive_and_undo(populated, wire):
    wire.replies['api.brickognize.com'] = BRICKOGNIZE
    before = last_event()
    response = upload(populated, '/identifications', png((900, 700)), key='ident-one')
    assert response.status_code == 201, response.text
    validate(response.json, CONTRACT['paths']['/identifications']['post']['responses']['201']['content']['application/json']['schema'])
    record = response.json['data']
    assert record['has_thumb'] and [c['item_no'] for c in record['candidates']] == ['3001', '100-1']
    assert record['candidates'][0]['name'] == 'Synthetic brick' and record['candidates'][0]['score'] == 0.93
    assert len(wire.requests) == 1 and wire.requests[0].full_url.startswith('https://api.brickognize.com/predict/')
    assert len([r for r in events(before) if r['entity'] == 'bw_api']) == 1
    detail = call(populated, '/identifications/' + record['id'])
    assert detail.status_code == 200 and detail.json['data']['id'] == record['id']
    thumb = call(populated, f'/identifications/{record["id"]}/thumb')
    assert thumb.status_code == 200 and thumb.mimetype == 'image/jpeg'
    with Image.open(io.BytesIO(thumb.data)) as image: assert max(image.size) <= 256 and not image.getexif()
    assert record['id'] in [r['id'] for r in call(populated, '/identifications').json['data']]
    assert upload(populated, '/identifications', png((900, 700)), key='ident-one').json['idempotent_replay'] and len(wire.requests) == 1
    deleted = call(populated, f'/identifications/{record["id"]}', 'delete', headers={'Idempotency-Key': 'ident-del'})
    assert deleted.status_code == 200 and deleted.json['data']['archived_at']
    validate(deleted.json, CONTRACT['paths']['/identifications/{id}']['delete']['responses']['200']['content']['application/json']['schema'])
    assert record['id'] not in [r['id'] for r in call(populated, '/identifications').json['data']]
    assert call(populated, f'/identifications/{record["id"]}/thumb').status_code == 404
    assert call(populated, f'/identifications/{record["id"]}', 'delete').status_code == 409
    assert call(populated, f'/events/{deleted.json["event_id"]}/undo', 'post', headers={'Idempotency-Key': 'ident-undo'}).status_code == 200
    assert record['id'] in [r['id'] for r in call(populated, '/identifications').json['data']]
    created = response.json['event_id']
    assert call(populated, f'/events/{created}/undo', 'post', headers={'Idempotency-Key': 'ident-undo-2'}).status_code == 200
    assert record['id'] not in [r['id'] for r in call(populated, '/identifications').json['data']]
    assert call(populated, '/identifications/absent', 'delete').status_code == 404


def test_identification_limits_types_budget_and_failures(populated, wire, monkeypatch):
    wire.replies['api.brickognize.com'] = BRICKOGNIZE
    assert upload(populated, '/identifications', b'\x89PNG' + b'0' * (8 * 1024 * 1024)).status_code == 413
    assert upload(populated, '/identifications', b'%PDF', mimetype='application/pdf').status_code == 415
    assert upload(populated, '/identifications', b'garbage', mimetype='image/png').status_code == 422
    assert upload(populated, '/identifications', png(), extra={'caption': 'x'}).status_code == 422
    assert populated.test_client().post('/api/v1/identifications', headers={'Authorization': 'Bearer synthetic-bootstrap'}, json={}).status_code == 415
    assert not wire.requests and len(dbrows('identifications')) == 1
    monkeypatch.setenv('BW_BRICKOGNIZE_DAILY_BUDGET', '1')
    assert upload(populated, '/identifications', png()).status_code == 201
    exhausted = upload(populated, '/identifications', png((50, 50)))
    assert exhausted.status_code == 429 and exhausted.headers['Retry-After'] and exhausted.json['job_id']
    assert len(wire.requests) == 1 and len(dbrows('identifications')) == 2
    call(populated, '/sources/brickognize', 'patch', json={'enabled': False})
    assert upload(populated, '/identifications', png()).json['code'] == 'source_disabled'
    wire.replies['api.brickognize.com'] = json.dumps({'unexpected': True})
    call(populated, '/sources/brickognize', 'patch', json={'enabled': True})
    monkeypatch.setenv('BW_BRICKOGNIZE_DAILY_BUDGET', '10')
    assert upload(populated, '/identifications', png()).status_code == 502


# --- no key, ciphertext or fragment anywhere --------------------------------------------------

def needles(db_path):
    values = []
    for name in (*BL_ENV, 'BW_REBRICKABLE_API_KEY', 'BW_BRICKSET_API_KEY', 'BW_SECRET_KEY'):
        values.append(os.environ.get(name, ''))
    with closing(connect(db_path)) as db:
        for r in db.execute('SELECT ciphertext FROM source_keys UNION SELECT ciphertext FROM source_key_previous'):
            values.append(r[0])
    return values


def fragments(values):
    return {v[:8] for v in values if len(v) >= 16} | {v[-8:] for v in values if len(v) >= 16} | {v for v in values if v}


def test_no_secret_anywhere_in_the_api(populated, secret, wire, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    db_path = os.environ['BW_DB_PATH']
    stored_old, stored_new = fake(32), fake(32)
    plain = [stored_old, stored_new]
    for name in (*BL_ENV, 'BW_BRICKSET_API_KEY'):
        monkeypatch.setenv(name, fake(32))
    wire.replies['rebrickable.com'] = lambda request: json.dumps({'id': 0, 'detail': 'Invalid token ' + request.headers['Authorization']})
    wire.replies['brickset.com'] = lambda request: json.dumps({'status': 'error', 'message': 'bad ' + request.data.decode()})
    wire.replies['api.bricklink.com'] = lambda request: bl([]) if 'colors' in request.full_url else 'not json ' + request.headers['Authorization']
    wire.replies['api.brickognize.com'] = BRICKOGNIZE
    collected = []

    def keep(response):
        collected.append((response.status_code, response.headers, response.get_data(as_text=True) if not response.mimetype.startswith(('image/', 'application/vnd')) else ''))
        return response
    put(populated, 'rebrickable', {'key': stored_old}); keep(put(populated, 'rebrickable', {'key': stored_new}, key='k1'))
    keep(put(populated, 'rebrickable', {'key': stored_new}, key='k1'))
    keep(put(populated, 'rebrickable', {'key': 'short'}))
    keep(call(populated, '/sources/rebrickable/key/test', 'post'))        # rebrickable error echoing the header
    keep(call(populated, '/sources/brickset/key/test', 'post'))           # brickset error echoing the form body
    keep(call(populated, '/colors/sync', 'post'))
    keep(call(populated, '/jobs/drain', 'post'))
    keep(upload(populated, '/identifications', png()))
    keep(call(populated, '/sources/rebrickable/key', 'delete'))
    for path, operation in OPS:
        keep(call(populated, concrete(path)))
    for path in ('/sources', '/events?limit=200', '/jobs', '/database/check', '/settings', '/identifications', '/tokens', '/me', '/version', '/health'):
        keep(call(populated, path))
    keep(call(populated, '/database/export'))
    for response in [r for r in collected]:
        pass
    # Failure paths: wrong secret, missing secret.
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    keep(call(populated, '/sources/rebrickable/key/test', 'post'))
    monkeypatch.delenv('BW_SECRET_KEY')
    keep(put(populated, 'rebrickable', {'key': stored_new}))
    monkeypatch.setenv('BW_SECRET_KEY', secret)
    for status, headers, body in collected:
        text = body + '\n' + '\n'.join(f'{k}: {v}' for k, v in headers.items())
        for needle in fragments(needles(db_path) + plain) | {secret}:
            assert needle not in text, (needle[:3], text[:200])
    log = caplog.text
    for needle in fragments(needles(db_path) + plain):
        assert needle not in log
    for row in dbrows('events'):
        blob = json.dumps(row)
        for needle in fragments(needles(db_path) + plain):
            assert needle not in blob
    for row in dbrows('source_records') + dbrows('jobs'):
        blob = json.dumps(row, default=str)
        for needle in fragments(needles(db_path) + plain):
            assert needle not in blob
    folder = Path(db_path).parent
    for path in folder.rglob('*'):
        if path.is_file():
            data = path.read_bytes()
            for needle in [n for n in plain + needles(db_path)[:7] if n]:
                assert needle.encode() not in data, path.name
    assert any(status == 429 or status >= 400 for status, _, _ in collected)
    # The echoed provider replies were redacted before they were stored.
    assert any('[set]' in r['payload'] for r in dbrows('source_records'))


# --- review fixes -----------------------------------------------------------------------------

def test_export_snapshot_keeps_every_trigger_and_events_stay_append_only(populated, secret, wire):
    import sqlite3
    put(populated, 'rebrickable', {'key': fake()})
    export = call(populated, '/database/export')
    assert export.status_code == 200
    def triggers(connection):
        return {r[0]: r[1] for r in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")}
    with closing(connect(os.environ['BW_DB_PATH'])) as live, closing(sqlite3.connect(':memory:')) as copy:
        copy.deserialize(export.data)
        assert triggers(copy) == triggers(live) and 'events_no_update' in triggers(copy)
        with pytest.raises(sqlite3.DatabaseError, match='append-only'):
            copy.execute("UPDATE events SET old_value=NULL")
        with pytest.raises(sqlite3.DatabaseError, match='append-only'):
            copy.execute("DELETE FROM events")


def test_concurrent_duplicate_key_runs_the_action_once_and_failure_releases_it(populated, secret, wire, monkeypatch):
    import threading
    for name in BL_ENV: monkeypatch.setenv(name, fake())
    started, release = threading.Event(), threading.Event()
    def slow(request):
        started.set()
        assert release.wait(10)
        return bl([])
    wire.replies['api.bricklink.com'] = slow
    results = {}
    def first(): results['first'] = call(populated, '/colors/sync', 'post', headers={'Idempotency-Key': 'race-1'})
    thread = threading.Thread(target=first); thread.start()
    assert started.wait(10)
    second = call(populated, '/colors/sync', 'post', headers={'Idempotency-Key': 'race-1'})
    assert second.status_code == 409 and second.json['code'] == 'idempotency_conflict'
    release.set(); thread.join(10)
    assert results['first'].status_code == 200 and len(wire.requests) == 1
    assert call(populated, '/colors/sync', 'post', headers={'Idempotency-Key': 'race-1'}).json['idempotent_replay'] is True
    assert not [r for r in dbrows('settings') if r['key'].startswith('api:claim:')]
    # A failing action releases its claim, so the retry runs.
    wire.replies['api.bricklink.com'] = lambda request: 'not json'
    assert call(populated, '/colors/sync', 'post', headers={'Idempotency-Key': 'race-2'}).status_code == 502
    assert not [r for r in dbrows('settings') if r['key'].startswith('api:claim:')]
    wire.replies['api.bricklink.com'] = bl([])
    assert call(populated, '/colors/sync', 'post', headers={'Idempotency-Key': 'race-2'}).status_code == 200


def test_redaction_registry_is_thread_safe():
    import threading
    stop, failures = threading.Event(), []
    def churn():
        n = 0
        while not stop.is_set():
            n += 1
            secrets.remember(*[f'value-{n}-{i}-xxxxxxxx' for i in range(20)])
            if n % 50 == 0: secrets.forget()
    def read():
        try:
            for _ in range(3000): base.redact('text value-1-1-xxxxxxxx')
        except RuntimeError as error:
            failures.append(error)
    writers = [threading.Thread(target=churn) for _ in range(3)]
    readers = [threading.Thread(target=read) for _ in range(3)]
    for t in writers + readers: t.start()
    for t in readers: t.join(30)
    stop.set()
    for t in writers: t.join(10)
    secrets.forget()
    assert not failures


def test_archived_identification_is_hidden_from_the_single_read(populated, wire):
    wire.replies['api.brickognize.com'] = BRICKOGNIZE
    record = upload(populated, '/identifications', png()).json['data']
    assert call(populated, '/identifications/' + record['id'], 'delete').status_code == 200
    assert call(populated, '/identifications/' + record['id']).status_code == 404
    shown = call(populated, '/identifications/' + record['id'] + '?archived=true')
    assert shown.status_code == 200 and shown.json['data']['archived_at']
    assert call(populated, '/identifications/' + record['id'] + '?archived=maybe').status_code == 400


def test_catalogue_directory_has_one_resolver(populated, tmp_path):
    from brickwork.core.sources.bricklink_catalogue import source_directory
    from brickwork.web import admin_ops
    path = Path(os.environ['BW_DB_PATH'])
    assert source_directory(path) == path.resolve().parent / 'bricklink-catalog-src'
    seen = []
    real = admin_ops.catalogue_import_bricklink
    admin_ops.catalogue_import_bricklink = lambda directory: seen.append(directory)
    try:
        with populated.app_context():
            admin_ops._tools_write('catalogue')
    finally:
        admin_ops.catalogue_import_bricklink = real
    assert seen == [source_directory(path)]
