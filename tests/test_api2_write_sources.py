"""API v2 sources, the encrypted key store and the catalogue import (M.11d, issue #113). Ported from test_bw_api_m5 (keys, sources, budgets) and
test_bw_security (the scope of Undo) onto the 4.0 store. Mocked transports only; every answer is validated against `openapi-v2.yaml`."""
from contextlib import closing
import json
import os

from cryptography.fernet import Fernet
import pytest

from brickwork.core import keys, secrets
from brickwork.core.connect import connect
from brickwork.api2 import writes
from brickwork.core.sources import base
from tests.api2 import BL_ENV, bl, call, events, fake, row, rows, secret, stored_token, v2, validate, wire, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def put(v2, source, body, key=None, **kwargs):
    return write(v2, f'/sources/{source}/key', 'put', body, key=key or False, **kwargs)


def source(v2, name):
    return next(r for r in call(v2, '/sources').json['data'] if r['source'] == name)


def credentials(pair, name, names):
    with closing(connect(pair)) as db:
        return keys.credentials(db, name, names)


# ---------- the list ----------

def test_every_client_is_listed_with_its_key_state_and_nothing_secret(v2, world, secret, wire):
    listed = call(v2, '/sources')
    validate(listed, 'get_sources')
    assert {r['source'] for r in listed.json['data']} >= {'bricklink', 'rebrickable', 'brickset', 'brickognize'}
    value = fake()
    put(v2, 'rebrickable', {'key': value})
    shown = source(v2, 'rebrickable')
    assert shown['key'] == {'configured': True, 'origin': 'stored', 'saved_at': shown['key']['saved_at']} and value not in call(v2, '/sources').text


def test_the_list_pages_and_a_read_token_may_read_it(v2, world, pair):
    reader = stored_token(pair, ['read'], 'reader')
    first = call(v2, '/sources?limit=2', token=reader)
    validate(first, 'get_sources')
    assert len(first.json['data']) == 2 and first.json['page']['next_cursor']
    rest = call(v2, '/sources?limit=2&cursor=' + first.json['page']['next_cursor'], token=reader)
    assert rest.status_code == 200 and not {r['source'] for r in first.json['data']} & {r['source'] for r in rest.json['data']}
    assert call(v2, '/sources?direction=desc').json['data'][0]['source'] == 'rebrickable'
    assert call(v2, '/sources?q=x').status_code == 400


# ---------- the key store ----------

def test_a_key_is_encrypted_audited_and_write_only(v2, world, secret, wire, pair):
    value = fake()
    before = len(events(pair))
    response = put(v2, 'rebrickable', {'key': value})
    assert response.status_code == 200, response.text
    validate(response, 'put_sources_by_source_key')
    assert response.json['data']['key'] == {'configured': True, 'origin': 'stored', 'saved_at': response.json['data']['key']['saved_at']}
    assert value not in response.text
    stored = row(pair, 'SELECT * FROM source_key')
    assert value not in stored['ciphertext'] and secrets.decrypt(stored['ciphertext']).count(value) == 1
    new = events(pair, 'id>?', (before,))
    assert len(new) == 1 and (new[0]['via'], new[0]['actor']) == ('api', 'bootstrap')
    assert all(value not in json.dumps(r) and stored['ciphertext'] not in json.dumps(r) for r in events(pair))
    assert call(v2, f"/events/{response.json['event_id']}").json['data']['undoable'] is True
    assert source(v2, 'rebrickable')['key']['origin'] == 'stored'
    for name in os.listdir(os.path.dirname(pair)):
        path = os.path.join(os.path.dirname(pair), name)
        if os.path.isfile(path):
            assert value.encode() not in open(path, 'rb').read(), name


def test_bricklink_takes_four_values_and_every_input_is_checked(v2, world, secret, wire, pair):
    body = {'consumer_key': fake(), 'consumer_secret': fake(), 'token_value': fake(), 'token_secret': fake()}
    assert put(v2, 'bricklink', {'key': fake()}).status_code == 422
    assert put(v2, 'bricklink', {k: body[k] for k in list(body)[:3]}).status_code == 422
    assert put(v2, 'bricklink', body).status_code == 200
    assert credentials(pair, 'bricklink', BL_ENV) == tuple(body.values())
    for bad in ({'key': 'short'}, {'key': 'has space in it 123'}, {'key': 12345678}, {'key': fake(), 'extra': 'x'}, {}):
        response = put(v2, 'rebrickable', bad)
        assert response.status_code == 422 and response.json['code'] == 'validation_failed'
        for v in bad.values():
            assert str(v) not in response.text or len(str(v)) < 8
    assert put(v2, 'brickognize', {'key': fake()}).status_code == 422
    assert put(v2, 'nonesuch', {'key': fake()}).status_code == 404


def test_replace_remove_and_undo_restore_the_exact_key(v2, world, secret, wire, pair):
    first, second = fake(), fake()
    names = ('BW_REBRICKABLE_API_KEY',)
    put(v2, 'rebrickable', {'key': first})
    second_event = put(v2, 'rebrickable', {'key': second}).json
    assert credentials(pair, 'rebrickable', names) == (second,)
    assert write(v2, f"/events/{second_event['event_id']}/undo").status_code == 200
    assert credentials(pair, 'rebrickable', names) == (first,)
    removed = write(v2, '/sources/rebrickable/key', 'delete')
    validate(removed, 'delete_sources_by_source_key')
    assert removed.json['data']['key']['configured'] is False and write(v2, '/sources/rebrickable/key', 'delete').status_code == 404
    with pytest.raises(base.SourceNotConfigured):
        credentials(pair, 'rebrickable', names)
    assert write(v2, f"/events/{removed.json['event_id']}/undo").status_code == 200
    assert credentials(pair, 'rebrickable', names) == (first,)
    first_event = row(pair, "SELECT id FROM event WHERE entity_kind='source_key' AND field='save' ORDER BY id LIMIT 1")['id']
    assert write(v2, f'/events/{first_event}/undo').status_code == 200                 # creation Undo archives
    assert source(v2, 'rebrickable')['key']['configured'] is False
    assert write(v2, f'/events/{first_event}/undo').json['data']['already_undone'] is True


def test_a_later_save_blocks_the_undo_of_an_earlier_one(v2, world, secret, wire):
    first = put(v2, 'brickset', {'key': fake()}).json
    put(v2, 'brickset', {'key': fake()})
    blocked = write(v2, f"/events/{first['event_id']}/undo")
    assert blocked.status_code == 409 and blocked.json['code'] == 'undo_blocked' and source(v2, 'brickset')['key']['configured'] is True


def test_the_environment_key_wins_over_the_stored_one(v2, world, secret, wire, monkeypatch):
    env_value, stored_value = fake(), fake()
    put(v2, 'rebrickable', {'key': stored_value})
    wire.replies['rebrickable.com'] = json.dumps({'id': 0, 'name': 'Black'})
    assert write(v2, '/sources/rebrickable/key/test').status_code == 200
    assert wire.requests[-1].headers['Authorization'] == 'key ' + stored_value
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', env_value)
    assert source(v2, 'rebrickable')['key']['origin'] == 'env'
    assert write(v2, '/sources/rebrickable/key/test').status_code == 200
    assert wire.requests[-1].headers['Authorization'] == 'key ' + env_value
    assert stored_value not in str(source(v2, 'rebrickable')) and env_value not in str(source(v2, 'rebrickable'))


def test_without_the_secret_key_entry_is_disabled_but_environment_keys_work(v2, world, wire, monkeypatch, pair):
    response = put(v2, 'rebrickable', {'key': fake()})
    assert response.status_code == 424 and response.json['code'] == 'source_not_configured'
    assert 'BW_SECRET_KEY' in response.json['detail'] and row(pair, 'SELECT count(*) AS n FROM source_key')['n'] == 0
    assert call(v2, '/sources').status_code == 200
    monkeypatch.setenv('BW_BRICKSET_API_KEY', fake())
    wire.replies['brickset.com'] = json.dumps({'status': 'success'})
    assert write(v2, '/sources/brickset/key/test').status_code == 200


def test_a_wrong_secret_key_fails_closed_without_detail(v2, world, secret, wire, monkeypatch):
    value = fake()
    put(v2, 'rebrickable', {'key': value})
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    response = write(v2, '/sources/rebrickable/key/test')
    assert response.status_code == 424 and response.json['code'] == 'source_not_configured'
    assert value not in response.text and 'Traceback' not in response.text and not wire.requests


def test_key_replay_uses_a_keyed_fingerprint_not_a_plain_hash(v2, world, secret, wire, pair):
    body = {'key': fake()}
    first = put(v2, 'rebrickable', body, key='key-replay')
    again = put(v2, 'rebrickable', body, key='key-replay')
    assert again.json['idempotent_replay'] is True and row(pair, 'SELECT count(*) AS n FROM source_key')['n'] == 1
    assert put(v2, 'rebrickable', {'key': fake()}, key='key-replay').status_code == 409
    saved = events(pair, "entity_kind='bw_api' AND field='op:key-replay'")[0]['new_value']
    assert body['key'] not in saved and first.json['event_id'] == again.json['event_id']
    from brickwork.api2 import writes
    assert json.loads(saved)['digest'] != __import__('hashlib').sha256(json.dumps({'source': 'rebrickable'}).encode()).hexdigest()
    assert writes.KEYED


def test_the_scopes_of_keys_sources_and_undo(v2, world, secret, wire, pair):
    for scopes in (['read'], ['read', 'write']):
        token = stored_token(pair, scopes, 'synthetic-' + '-'.join(scopes))
        assert put(v2, 'rebrickable', {'key': fake()}, token=token).status_code == 403
        assert write(v2, '/sources/rebrickable/key', 'delete', token=token).status_code == 403
        assert write(v2, '/sources/rebrickable/key/test', token=token).status_code == 403
        assert write(v2, '/sources/rebrickable', 'patch', {'enabled': False}, token=token).status_code == 403
        assert write(v2, '/catalogue/import', token=token).status_code == 403
    assert row(pair, 'SELECT count(*) AS n FROM source_key')['n'] == 0
    writer = stored_token(pair, ['read', 'write'], 'writer')
    saved = put(v2, 'rebrickable', {'key': fake()})
    removed = write(v2, '/sources/rebrickable/key', 'delete')
    toggled = write(v2, '/sources/brickset', 'patch', {'enabled': False})
    for event in (saved.json['event_id'], removed.json['event_id'], toggled.json['event_id']):
        assert write(v2, f'/events/{event}/undo', token=writer).status_code == 403            # undoing needs the scope the change needed


def test_a_read_only_instance_refuses_key_writes(v2, world, secret, wire, monkeypatch):
    monkeypatch.setenv('BW_READ_ONLY', '1')
    assert put(v2, 'rebrickable', {'key': fake()}).status_code == 403
    assert v2.put('/api/v2/sources/rebrickable/key', json={'key': fake()}).status_code == 401


def test_a_key_test_is_one_budgeted_call_without_key_material(v2, world, secret, wire):
    value = fake()
    put(v2, 'rebrickable', {'key': value})
    wire.replies['rebrickable.com'] = json.dumps({'id': 0, 'name': 'Black'})
    response = write(v2, '/sources/rebrickable/key/test')
    validate(response, 'post_sources_by_source_key_test')
    assert response.json['data']['ok'] is True and value not in response.text and len(wire.requests) == 1
    assert source(v2, 'rebrickable')['used_today'] == 1
    wire.replies['rebrickable.com'] = lambda request: json.dumps({'detail': 'Invalid token ' + value})
    failed = write(v2, '/sources/rebrickable/key/test')
    assert failed.status_code == 502 and value not in failed.text and failed.json['code'] == 'source_error'
    assert write(v2, '/sources/brickognize/key/test').status_code == 422


def test_an_exhausted_budget_is_429_with_retry_after(v2, world, secret, wire, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '1')
    wire.replies['rebrickable.com'] = json.dumps({'id': 0, 'name': 'Black'})
    assert write(v2, '/sources/rebrickable/key/test').status_code == 200
    response = write(v2, '/sources/rebrickable/key/test')
    assert response.status_code == 429 and response.json['code'] == 'budget_exhausted'
    assert int(response.headers['Retry-After']) == response.json['retry_after'] >= 1 and len(wire.requests) == 1


def test_a_remote_throttle_is_429_source_throttled(v2, world, secret, wire, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    wire.replies['rebrickable.com'] = json.dumps({'detail': 'Request was throttled. Expected available in 37 seconds.'})
    response = write(v2, '/sources/rebrickable/key/test')
    assert response.status_code == 429 and response.json['code'] == 'source_throttled' and 30 <= int(response.headers['Retry-After']) <= 37


# ---------- the switch ----------

def test_a_source_is_switched_off_and_on_and_undo_puts_it_back(v2, world, wire, pair):
    before = len(events(pair))
    response = write(v2, '/sources/rebrickable', 'patch', {'enabled': False})
    validate(response, 'patch_sources_by_source')
    assert response.json['data']['enabled'] is False and len([e for e in events(pair, 'id>?', (before,)) if e['entity_kind'] != 'bw_api']) == 1 and source(v2, 'rebrickable')['enabled'] is False
    assert write(v2, f"/events/{response.json['event_id']}/undo").status_code == 200 and source(v2, 'rebrickable')['enabled'] is True
    assert write(v2, '/sources/nonesuch', 'patch', {'enabled': True}).status_code == 404
    assert write(v2, '/sources/rebrickable', 'patch', {'enabled': 'no'}).status_code == 422
    assert write(v2, '/sources/rebrickable', 'patch', {}).status_code == 422


# ---------- the catalogue ----------

def test_the_catalogue_import_without_lists_is_a_refusal_that_names_no_folder(v2, world, wire, pair):
    response = write(v2, '/catalogue/import')
    assert response.status_code == 422 and 'lists' in response.json['detail'] and str(os.path.dirname(pair)) not in response.text


def test_the_catalogue_import_loads_the_newest_folder_of_lists_and_answers_the_status(v2, world, wire, pair):
    from brickwork.store4.cli import Paths
    from tests.test_store4_bricklink import write_xml
    write_xml(Paths(pair.parent).lists / '2026-10-26')
    response = write(v2, '/catalogue/import', key='cat-1')
    assert response.status_code == 200, response.json
    validate(response, 'post_catalogue_import')
    data = response.json['data']
    assert data['loaded'] is True and data['items'] > 0 and data['builds'] and set(data['coverage']) == {'matched', 'inferred', 'manual', 'to_check'}
    assert data['last_reconcile'] is not None
    replay = write(v2, '/catalogue/import', key='cat-1')
    assert replay.json['idempotent_replay'] is True
    named = response.json['event_id']
    assert named is not None and replay.json['event_id'] == named                                  # activation's event carries this request's key
    row = events(pair, 'id=?', (named,))[0]
    assert row['operation_key'].startswith(writes.PREFIX)                                           # an event of this request, not a stray key
    state = __import__('json').loads((pair.parent / 'catalogue-job.json').read_text())
    assert state['kind'] == 'lists' and state['state'] == 'done'


def test_colors_sync_is_not_an_operation(v2):
    assert write(v2, '/colors/sync').status_code == 405              # the path is /colors (a read); the sync is gone with the 3.3 colour table


# ---------- a duplicate key while the call is out ----------

def test_a_duplicate_key_while_the_call_is_out_is_refused_and_a_failed_call_releases_its_key(v2, world, secret, wire, pair, monkeypatch):
    import threading
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', fake())
    started, release = threading.Event(), threading.Event()

    def slow(request):
        started.set()
        assert release.wait(10)
        return json.dumps({'id': 0, 'name': 'Black'})
    wire.replies['rebrickable.com'] = slow
    results = {}
    thread = threading.Thread(target=lambda: results.update(first=write(v2, '/sources/rebrickable/key/test', key='race-1')))
    thread.start()
    assert started.wait(10)
    second = write(v2, '/sources/rebrickable/key/test', key='race-1')
    assert second.status_code == 409 and second.json['code'] == 'idempotency_conflict'
    release.set()
    thread.join(10)
    assert results['first'].status_code == 200 and len(wire.requests) == 1
    assert write(v2, '/sources/rebrickable/key/test', key='race-1').json['idempotent_replay'] is True
    claims = lambda: rows(pair, "SELECT key FROM setting WHERE key LIKE 'api:claim:%'")
    assert claims() == []
    wire.replies['rebrickable.com'] = lambda request: 'not json'
    assert write(v2, '/sources/rebrickable/key/test', key='race-2').status_code == 502
    assert claims() == []
    wire.replies['rebrickable.com'] = json.dumps({'id': 0, 'name': 'Black'})
    assert write(v2, '/sources/rebrickable/key/test', key='race-2').status_code == 200
