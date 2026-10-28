"""The write transport of API v2 (M.11c, issue #113): the generated contract file, the Idempotency-Key, If-Match, the request checks, scopes and
read-only, atomicity, the embedded worker, and the replay record. Ported from test_bw_api_m3 (idempotency, receipts, atomicity, manifest, worker) and
the write-error cases of test_bw_api_m4 and test_bw_review_followups onto the 4.0 fixtures. Invented data."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json

import pytest

from brickwork import api2
from brickwork.api2 import writes
from brickwork.core import admin
from brickwork.core.connect import connect
from scripts import generate_api_writes
from tests.api2 import OPERATION_BY_ID, call, events, row, rows, stored_token, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import table_digest


def digest(pair):
    with closing(connect(pair)) as db:
        return table_digest(db, skip=('event', 'event_undo', 'item_merge', 'stock_transfer', 'api_token'))


# ---------- the generated contract file ----------

def test_the_write_contract_file_is_the_one_the_generator_makes():
    assert (generate_api_writes.ROOT / 'brickwork/api2/write_contract.json').read_text() == generate_api_writes.generated_v2()


def test_every_write_operation_of_the_pieces_done_has_a_view_and_a_spec():
    spec = api2.operations()
    done = {i for i, o in spec.items() if o['piece'] in api2.DONE and o['method'] != 'GET'}
    assert set(writes.SPEC) == {i for i in done if spec[i]['piece'] in generate_api_writes.V2_PIECES}
    from tests.api2 import PREFIX
    for operation in writes.SPEC.values():
        assert operation['method'] == spec[operation['endpoint']]['method'] and operation['path'] == spec[operation['endpoint']]['path']
    assert len(writes.SPEC) == 64


def test_the_operations_that_need_an_idempotency_key_are_the_documented_ones():
    required = {i for i, o in writes.SPEC.items() if o['required']}
    assert required == {
        'post_wishlists', 'patch_wishlists_by_id', 'delete_wishlists_by_id', 'post_wishlists_by_id_restore', 'post_wishlists_by_id_transfer',
        'post_copies', 'post_stock', 'post_wishes', 'post_found', 'post_stock_booklets', 'post_lots',
        'post_copies_by_id_take', 'post_stock_by_id_give', 'post_wishes_by_id_to_owned', 'post_storages_by_id_contents', 'post_copies_by_id_parts_bulk',
        'post_prices_observations', 'post_items_by_id_prices', 'post_events_by_id_undo',
        'put_items_by_id_links', 'post_items_by_id_merge', 'post_items_by_id_unmerge', 'post_copies_by_id_inventory'}


def test_a_missing_key_is_428_where_the_contract_requires_it_and_nothing_is_written(v2, world, pair):
    before, count = digest(pair), len(events(pair))
    calls = [('/copies', 'post', {'item': {'id': world.keep}, 'decision': 'another'}), ('/stock', 'post', {'item': {'id': world.brick}, 'color': world.red, 'quantity': 1}),
             ('/wishes', 'post', {'item': {'id': world.keep}, 'decision': 'another'}), ('/lots', 'post', {'name': 'x', 'stock_ids': [world.stock_plate]}),
             (f'/copies/{world.copy_a}/take', 'post', {'item': {'id': world.brick}, 'color': world.red, 'quantity': 1}),
             ('/wishlists', 'post', {'name': 'x'}), (f'/items/{world.brick}/prices', 'post', {'condition': 'used', 'guide': 'manual', 'price': '1', 'currency': 'EUR', 'color': world.red}),
             ('/events/1/undo', 'post', None), (f'/items/{world.brick}/links', 'put', {'provider': 'bricklink', 'type': 'P', 'no': 'x'})]
    for path, method, body in calls:
        refused = write(v2, path, method, body, key=False)
        assert refused.status_code == 428 and refused.json['code'] == 'idempotency_key_required', path
    assert digest(pair) == before and len(events(pair)) == count


# ---------- the Idempotency-Key ----------

def test_a_replay_answers_the_first_answer_and_writes_nothing(v2, world, pair):
    first = write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'one'}, key='replay-1')
    count = len(events(pair))
    again = write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'one'}, key='replay-1')
    assert again.status_code == 200 and again.json == dict(first.json, idempotent_replay=True)
    assert len(events(pair)) == count


def test_another_body_or_path_under_the_same_key_is_409_and_another_token_has_its_own_keys(v2, world, pair):
    write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'one'}, key='conflict-1')
    body = write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'two'}, key='conflict-1')
    assert body.status_code == 409 and body.json['code'] == 'idempotency_conflict'
    path = write(v2, f'/copies/{world.copy_b}', 'patch', {'note': 'one'}, key='conflict-1')
    assert path.status_code == 409
    assert row(pair, 'SELECT note FROM main.copy WHERE id=?', (world.copy_a,))['note'] == 'one'
    other = stored_token(pair, ['read', 'write'], 'other')
    mine = write(v2, f'/copies/{world.copy_b}', 'patch', {'note': 'mine'}, key='shared-key')
    theirs = write(v2, f'/copies/{world.copy_b}', 'patch', {'note': 'theirs'}, key='shared-key', token=other)
    assert mine.status_code == theirs.status_code == 200 and theirs.json['idempotent_replay'] is False
    assert write(v2, f'/copies/{world.copy_b}', 'patch', {'note': 'theirs'}, key='shared-key', token=other).json['idempotent_replay'] is True


def test_a_key_is_honoured_for_thirty_days(v2, coll, world, pair):
    write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'one'}, key='old-1')
    record = row(pair, "SELECT id FROM main.event WHERE entity_kind='bw_api' AND field='op:old-1'")
    assert record
    old = (datetime.now(timezone.utc) - timedelta(days=31)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    with closing(connect(pair)) as db, db:
        db.execute('DROP TRIGGER event_no_update')
        db.execute('UPDATE main.event SET at=? WHERE id=?', (old, record['id']))
    fresh = write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'two'}, key='old-1')
    assert fresh.status_code == 200 and fresh.json['idempotent_replay'] is False and row(pair, 'SELECT note FROM main.copy WHERE id=?', (world.copy_a,))['note'] == 'two'


def test_a_key_is_one_to_eighty_letters_digits_and_hyphens(v2, world, pair):
    for key in ('a' * 81, 'has space', 'under_score', 'ü'):
        refused = write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'x'}, key=key)
        assert refused.status_code == 400 and refused.json['code'] == 'bad_request', key
    assert write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'x'}, key='a' * 80).status_code == 200
    assert write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'y'}, key=False).status_code == 200                      # optional here


def test_the_replay_record_is_hidden_from_the_event_list_and_carries_no_body(v2, world, pair):
    write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'hidden'}, key='hidden-1')
    listed = call(v2, '/events?limit=200').json['data']
    record = next(e for e in listed if e['entity'].startswith('bw_api'))
    assert record['old_value'] is None and record['new_value'] is None and record['undoable'] is False
    assert (record['via'], record['actor']) == ('api', 'bootstrap')


# ---------- the request ----------

def test_a_body_is_json_an_object_and_exactly_what_the_contract_names(v2, world, pair):
    before = digest(pair)
    path = f'/copies/{world.copy_a}'
    assert write(v2, path, 'patch', data='note=x', content_type='application/x-www-form-urlencoded').status_code == 415
    assert write(v2, path, 'patch', data='{"note": ', content_type='application/json').status_code == 400
    assert write(v2, path, 'patch', data='["note"]', content_type='application/json').status_code == 400
    assert write(v2, path, 'patch', {'note': 'x', 'colour': 'red'}).status_code == 422
    assert write(v2, path, 'patch', {'note': 5}).status_code == 422
    assert write(v2, path, 'patch', {'condition': 'broken'}).status_code == 422
    assert write(v2, path, 'patch', {'purchase_price': '1,5'}).status_code == 422
    assert write(v2, path + '?x=1', 'patch', {'note': 'x'}).status_code == 400
    assert write(v2, path, 'delete', data='{"x": 1}', content_type='application/json').status_code == 400                 # a body where none is accepted
    assert write(v2, '/copies', body={'quantity': 1}).status_code == 422                                                   # an item is required
    assert write(v2, '/copies', body={'item': {'id': world.keep, 'kind': 'set', 'key': '1000-1'}}).status_code == 422       # by id or by number, not both
    assert write(v2, '/copies', body={'item': {'kind': 'set'}}).status_code == 422
    assert write(v2, '/copies', body={'item': {'kind': 'planet', 'key': '1'}}).status_code == 422
    assert write(v2, '/copies', body={'item': {'provider': 'lego', 'kind': 'set', 'key': '1'}}).status_code == 422
    assert write(v2, '/copies', body={'item': {'id': 'one'}}).status_code == 422
    assert write(v2, '/copies', body={'item': {'id': world.keep}, 'quantity': True}).status_code == 422
    assert digest(pair) == before


def test_an_unknown_path_or_method_is_a_problem_not_a_page(v2, world):
    assert call(v2, '/copies/x/nowhere', 'post').status_code == 404
    wrong = call(v2, f'/copies/{world.copy_a}/take')
    assert wrong.status_code == 405 and wrong.json['code'] == 'method_not_allowed' and 'POST' in wrong.headers['Allow']


# ---------- scopes and read-only ----------

def test_a_read_token_cannot_write_and_a_write_token_cannot_change_settings(v2, world, pair):
    reader, writer = stored_token(pair, ['read'], 'reader'), stored_token(pair, ['read', 'write'], 'writer')
    before = digest(pair)
    for path, method, body in ((f'/copies/{world.copy_a}', 'patch', {'note': 'x'}), ('/wishlists', 'post', {'name': 'x'}), ('/events/1/undo', 'post', None)):
        refused = write(v2, path, method, body, token=reader)
        assert refused.status_code == 403 and refused.json['code'] == 'forbidden', path
    assert write(v2, '/settings', 'patch', {'retail_country': 'US'}, token=writer).status_code == 403
    assert digest(pair) == before
    assert call(v2, f'/copies/{world.copy_a}', token=reader).status_code == 200


def test_a_read_only_instance_refuses_every_write_whatever_the_scope(v2, world, pair, monkeypatch):
    monkeypatch.setenv('BW_READ_ONLY', '1')
    before, count = digest(pair), len(events(pair))
    for path, method, body in ((f'/copies/{world.copy_a}', 'patch', {'note': 'x'}), ('/settings', 'patch', {'retail_country': 'US'}), ('/lots', 'post', {'name': 'x', 'stock_ids': ['x']})):
        refused = write(v2, path, method, body)
        assert refused.status_code == 403 and refused.json['code'] == 'read_only_instance', path
    assert digest(pair) == before and len(events(pair)) == count
    assert call(v2, '/wishlists/all/export.xml').status_code == 200


# ---------- atomicity ----------

FAILURES = [
    ('/copies/{copy_a}', 'patch', {'note': 'x'}), ('/copies/{copy_b}', 'delete', None), ('/stock/{stock_brick}', 'patch', {'note': 'x'}),
    ('/wishes/{wish_part}', 'delete', None), ('/storages/{shelf}/contents', 'post', {'selections': [{'entity': 'copy', 'id': '{copy_b}'}]}),
    ('/lots', 'post', {'name': 'x', 'stock_ids': ['{stock_plate}']}), ('/places/{shop}', 'patch', {'name': 'x'}), ('/flags', 'post', {'name': 'x', 'kind': 'tag'}),
    ('/copies', 'post', {'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another', 'quantity': 2}),
    ('/stock', 'post', {'item': {'kind': 'part', 'key': '3001'}, 'color': 5, 'quantity': 2}), ('/wishlists', 'post', {'name': 'x'}),
    ('/copies/{copy_a}/take', 'post', {'item': {'kind': 'part', 'key': '3001'}, 'color': 5, 'quantity': 1}),
    ('/items/{brick}/prices', 'post', {'color': '{red}', 'condition': 'used', 'guide': 'manual', 'price': '1.00', 'currency': 'EUR'}),
    ('/settings', 'patch', {'retail_country': 'US'}), ('/items/{brick}/links', 'put', {'provider': 'bricklink', 'type': 'P', 'no': 'zz', 'preferred': True}),
]


def fill(value, world):
    if value == '{red}':
        return world.red
    if isinstance(value, str):
        return value.format(**world.__dict__) if '{' in value else value
    if isinstance(value, list):
        return [fill(v, world) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, world) for k, v in value.items()}
    return value


@pytest.mark.parametrize('path,method,body', FAILURES)
def test_a_failure_while_recording_the_answer_rolls_the_write_back(v2, world, pair, monkeypatch, path, method, body):
    real = admin.audit

    def failing(db, entity, field, *args, **kwargs):
        if entity.startswith('bw_api'):
            raise RuntimeError('Injected failure')
        return real(db, entity, field, *args, **kwargs)
    monkeypatch.setattr(admin, 'audit', failing)
    before, count = digest(pair), len(events(pair))
    response = write(v2, fill(path, world), method, fill(body, world))
    assert response.status_code == 500, response.get_data(as_text=True)
    assert digest(pair) == before and len(events(pair)) == count


@pytest.mark.parametrize('path,method,body', FAILURES)
def test_a_failure_after_the_write_leaves_nothing_and_no_replay_record(v2, world, pair, monkeypatch, path, method, body):
    before, count = digest(pair), len(events(pair))
    with monkeypatch.context() as patched:
        patched.setattr(writes, 'envelope', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('Injected failure')))
        response = write(v2, fill(path, world), method, fill(body, world), key='fail-1')
    assert response.status_code == 500, response.get_data(as_text=True)
    assert digest(pair) == before and len(events(pair)) == count
    assert write(v2, fill(path, world), method, fill(body, world), key='fail-1').json['idempotent_replay'] is False       # the key was not spent


# ---------- the embedded worker ----------

def test_a_write_that_queues_a_catalogue_import_wakes_the_worker(v2, world, monkeypatch):
    from brickwork.core import drainer
    started = []
    monkeypatch.setattr(drainer, 'start', lambda app, path, fallback=None: started.append(path) or True)
    plain = write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'x'})
    assert plain.status_code == 200 and started == []                                               # nothing is due after an edit
    made = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another'})
    assert made.status_code == 201 and len(started) == 1
    again = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another'}, key=made.request.headers['Idempotency-Key'])
    assert again.json['idempotent_replay'] is True and len(started) == 1                              # a replay starts nothing


def test_a_worker_that_cannot_start_does_not_turn_a_committed_write_into_an_error(v2, world, pair, monkeypatch, caplog):
    from brickwork.core import drainer

    def broken(*args, **kwargs):
        raise OSError('no threads')
    monkeypatch.setattr(drainer, 'start', broken)
    made = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another'})
    assert made.status_code == 201
    assert row(pair, 'SELECT count(*) AS n FROM main.copy')['n'] == 4
    assert any('import worker did not start' in r.getMessage() for r in caplog.records)


# ---------- store refusals ----------

def test_a_refusal_of_the_store_is_a_problem_with_its_own_words(v2, world, monkeypatch):
    from brickwork.store4 import copies as copies_store
    from brickwork.store4.errors import CatalogueError, Store4Error
    for error, status, code in ((copies_store.NothingToSwitch('same list'), 409, 'conflict'), (CatalogueError('no catalogue'), 424, 'catalogue_not_loaded'),
                                (Store4Error('refused'), 422, 'validation_failed')):
        monkeypatch.setattr(copies_store, 'switch_part_list_in', lambda *a, error=error, **k: (_ for _ in ()).throw(error))
        refused = write(v2, f'/copies/{world.copy_c}/inventory', body={'source': 'rebrickable'})
        assert (refused.status_code, refused.json['code']) == (status, code)
        assert refused.mimetype == 'application/problem+json'


# ---------- If-Match, scopes, missing and archived rows over every kind of edit ----------

def edit_cases(world, pair):
    from tests.test_api2_write_collection import edits
    return [(op, method, path, body) for op, method, path, body in edits(world, pair)]


def test_a_stale_if_match_is_412_on_every_write_that_takes_one(v2, world, pair):
    matching = {o['endpoint'] for o in writes.SPEC.values() if o['if_match']}
    assert matching == {'patch_copies_by_id', 'delete_copies_by_id', 'patch_stock_by_id', 'delete_stock_by_id', 'patch_wishes_by_id', 'delete_wishes_by_id',
                        'post_copies_by_id_inventory'}
    version = call(v2, f'/copies/{world.copy_c}').json['data']['inventory']['version']
    other = 1 if version == 2 else 2
    stale = {'If-Match': '"stale"'}
    before, count = digest(pair), len(events(pair))
    for operation, method, path, body in [
            ('patch_copies_by_id', 'patch', f'/copies/{world.copy_a}', {'note': 'x'}), ('delete_copies_by_id', 'delete', f'/copies/{world.copy_a}', None),
            ('patch_stock_by_id', 'patch', f'/stock/{world.stock_brick}', {'note': 'x'}), ('delete_stock_by_id', 'delete', f'/stock/{world.stock_brick}', None),
            ('patch_wishes_by_id', 'patch', f'/wishes/{world.wish_part}', {'note': 'x'}), ('delete_wishes_by_id', 'delete', f'/wishes/{world.wish_part}', None),
            ('post_copies_by_id_inventory', 'post', f'/copies/{world.copy_c}/inventory', {'source': 'rebrickable', 'version': other})]:
        refused = write(v2, path, method, body, headers=stale)
        assert refused.status_code == 412 and refused.json['code'] == 'precondition_failed', operation
    assert digest(pair) == before and len(events(pair)) == count


def test_every_edit_refuses_a_read_token_and_a_read_only_instance_and_names_nothing_that_is_missing(v2, world, pair, monkeypatch):
    reader = stored_token(pair, ['read'], 'reader')
    cases = edit_cases(world, pair)
    before = digest(pair)
    for operation, method, path, body in cases:
        assert write(v2, path, method, body, token=reader).status_code == 403, operation
    monkeypatch.setenv('BW_READ_ONLY', '1')
    for operation, method, path, body in cases:
        assert write(v2, path, method, body).status_code == 403, operation
    monkeypatch.delenv('BW_READ_ONLY')
    assert digest(pair) == before
    for operation, method, path, body in cases:
        segment = path.split('/')[2]                                                                      # the row the edit names: /copies/<id>/...
        missing = path.replace(segment, 'absent', 1)
        assert write(v2, missing, method, body).status_code == 404, (operation, missing)
    assert digest(pair) == before


def test_restoring_rolls_back_with_the_answer(v2, world, pair, monkeypatch):
    write(v2, f'/copies/{world.copy_b}', 'delete')
    real = admin.audit

    def failing(db, entity, field, *args, **kwargs):
        if entity.startswith('bw_api'):
            raise RuntimeError('Injected failure')
        return real(db, entity, field, *args, **kwargs)
    with monkeypatch.context() as patched:
        patched.setattr(admin, 'audit', failing)
        assert write(v2, f'/copies/{world.copy_b}/restore').status_code == 500
    assert row(pair, 'SELECT archived_at FROM main.copy WHERE id=?', (world.copy_b,))['archived_at']


# ---------- uploads ----------

@pytest.mark.parametrize('path,megabytes', [('/api/v2/copies/c1/photos', 15), ('/api/v2/stock/s1/photos', 15), ('/api/v2/instruction-files', 20)])
def test_an_upload_is_capped_just_above_its_own_limit(app4, path, megabytes):
    from brickwork import limits
    with app4.test_request_context(path, method='POST', content_type='multipart/form-data; boundary=x'):
        assert limits.body_limit() == megabytes * limits.MB + limits.FRAMING
    with app4.test_request_context(path, method='POST', content_type='application/json'):
        assert limits.body_limit() == limits.JSON_LIMIT
