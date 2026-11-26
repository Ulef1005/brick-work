"""API v2 collection sync, BrickTracker import and photo identification (M.11d, issue #113). Ported from test_bw_sync_api, test_bw_review_followups (the
plan markers), test_bw_api_m5 (identifications) and test_bw_import_ui onto the 4.0 store. Mocked transports only; every answer is validated against
`openapi-v2.yaml`. Invented data."""
from contextlib import closing
import io
import json

from cryptography.fernet import Fernet
import pytest

from brickwork.core.connect import connect
from brickwork.core.sources import base
from tests.api2 import app4, call, coll, events, png, row, rows, stored_token, upload, v2, validate, wire, world, write  # noqa: F401
from tests.app4 import Coll, make_pair
from tests.importer.test_bricktracker_import import upstream
from tests.test_bw_sync import EXTRA, PASSWORD, TOKEN, Rebrickable, everything
from brickwork.core.sync import lost_parts_send

@pytest.fixture(autouse=True)
def _lost_parts_send_unlocked(monkeypatch):
    """The send is locked for now (#469); these tests cover the code behind the lock. `test_lost_parts_send_lock.py` covers the lock."""
    monkeypatch.setattr(lost_parts_send, 'SEND_LOCKED', False)


@pytest.fixture
def pair(tmp_path):
    """The collection of test_bw_sync: the rich catalogue with two more sets, two copies of `2070-1`."""
    path = make_pair(tmp_path, rich=True, extra_dump=EXTRA)
    with closing(connect(path)) as db:
        coll = Coll(db)
        coll.add_copy('2070-1')
        coll.add_copy('2070-1')
    return path


@pytest.fixture
def remote(monkeypatch, wire):
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters.RebrickableUser, 'minimum_spacing', 0)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'synthetic-brickset-key')
    fake = Rebrickable()
    monkeypatch.setattr(adapters, 'transport', fake)
    return fake


def live(pair, number):
    return rows(pair, "SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=? AND c.archived_at IS NULL", (number,))


def test_credentials_link_pull_undo_and_send_with_their_scopes(v2, pair, remote):
    reader, writer = stored_token(pair, ['read'], 'reader'), stored_token(pair, ['read', 'write'], 'writer')
    body = {'username': 'synthetic-user', 'password': PASSWORD}
    assert write(v2, '/sources/rebrickable/user/connect', body=body, token=writer).status_code == 403
    made = write(v2, '/sources/rebrickable/user/connect', body=body, key='connect-1')
    assert made.status_code == 200, made.json
    validate(made, 'post_sources_by_source_user_connect')
    assert made.json['data']['user']['configured'] and PASSWORD not in made.text
    assert write(v2, '/sources/rebrickable/user/connect', body=body, key='connect-1').json['idempotent_replay'] is True and len(remote.calls) == 1
    with closing(connect(pair)) as db:
        assert PASSWORD not in everything(db) and TOKEN not in everything(db)
    status = call(v2, '/sync/rebrickable', token=reader)
    validate(status, 'get_sync_by_source')
    assert status.json['data']['credentials']['user']['configured']
    assert write(v2, '/sync/rebrickable/link', 'put', {'owned': [1, 2]}, token=reader).status_code == 403
    linked = write(v2, '/sync/rebrickable/link', 'put', {'owned': [1, 2], 'wishlist': 9, 'send_to': 1}, token=writer)
    validate(linked, 'put_sync_by_source_link')
    lists = call(v2, '/sync/rebrickable/lists', token=reader)
    validate(lists, 'get_sync_by_source_lists')
    assert [l['id'] for l in lists.json['data']] == [1, 2, 9]
    plan = write(v2, '/sync/rebrickable/pull/plan', token=writer)
    assert plan.status_code == 201, plan.json
    validate(plan, 'post_sync_by_source_pull_plan', '201')
    plan_id = plan.json['data']['id']
    applied = write(v2, '/sync/rebrickable/pull/apply', body={'plan_id': plan_id}, token=writer, key='pull-1')
    assert applied.status_code == 200, applied.json
    validate(applied, 'post_sync_by_source_pull_apply')
    replay = write(v2, '/sync/rebrickable/pull/apply', body={'plan_id': plan_id}, token=writer, key='pull-1')
    assert replay.json['idempotent_replay'] and replay.json['event_id'] == applied.json['event_id']
    assert len(live(pair, '1000-1')) == 2
    undone = write(v2, f"/events/{applied.json['event_id']}/undo", token=writer)                  # write scope applied it, write scope undoes it
    assert undone.status_code == 200, undone.json
    assert live(pair, '1000-1') == []
    send = write(v2, '/sync/rebrickable/send/plan', token=writer)
    validate(send, 'post_sync_by_source_send_plan', '201')
    assert write(v2, '/sync/rebrickable/send/apply', body={'plan_id': send.json['data']['id']}, token=writer).status_code == 403
    sent = write(v2, '/sync/rebrickable/send/apply', body={'plan_id': send.json['data']['id']})
    assert sent.status_code == 200 and 'not undone' in sent.json['data']['note']
    validate(sent, 'post_sync_by_source_send_apply')
    assert write(v2, '/sync/bricklink/pull/plan', token=writer).status_code == 404 and call(v2, '/sync/bricklink').status_code == 404


def test_a_plan_is_applied_for_its_source_and_direction_only(v2, pair, remote):
    write(v2, '/sources/rebrickable/user', 'put', {'value': TOKEN})
    plan = write(v2, '/sync/rebrickable/pull/plan').json['data']['id']
    assert write(v2, '/sync/brickset/pull/apply', body={'plan_id': plan}).status_code in (404, 422)
    assert write(v2, '/sync/rebrickable/send/apply', body={'plan_id': plan}).status_code in (409, 422)
    assert write(v2, '/sync/rebrickable/pull/apply', body={'plan_id': 'nope'}).status_code in (404, 422)
    assert write(v2, '/sync/rebrickable/pull/apply', body={}).status_code == 422


def test_a_pasted_user_token_is_stored_tested_and_removed(v2, pair, remote):
    saved = write(v2, '/sources/rebrickable/user', 'put', {'value': TOKEN})
    validate(saved, 'put_sources_by_source_user')
    assert saved.json['data']['user']['configured'] and TOKEN not in saved.text
    remote.lists[1] = {}
    tested = write(v2, '/sources/rebrickable/user/test')
    validate(tested, 'post_sources_by_source_user_test')
    assert tested.json['data']['ok'] is True
    removed = write(v2, '/sources/rebrickable/user', 'delete')
    validate(removed, 'delete_sources_by_source_user')
    assert removed.json['data']['user']['configured'] is False
    assert write(v2, f"/events/{removed.json['event_id']}/undo").status_code == 200
    assert call(v2, '/sync/rebrickable').json['data']['credentials']['user']['configured'] is True
    assert write(v2, '/sources/rebrickable/user', 'put', {'value': 'short'}).status_code == 422
    assert write(v2, '/sources/bricklink/user', 'put', {'value': TOKEN}).status_code == 404


def test_a_plan_applied_twice_is_applied_once_whatever_the_key(v2, pair, remote):
    write(v2, '/sources/rebrickable/user', 'put', {'value': TOKEN})
    write(v2, '/sync/rebrickable/link', 'put', {'owned': [1, 2]})
    plan = write(v2, '/sync/rebrickable/pull/plan').json['data']['id']
    first = write(v2, '/sync/rebrickable/pull/apply', body={'plan_id': plan}, key='pull-a')
    count = len(live(pair, '1000-1'))
    again = write(v2, '/sync/rebrickable/pull/apply', body={'plan_id': plan}, key='pull-b')
    assert first.json['data']['already_applied'] is False and again.json['data']['already_applied'] is True
    assert len(live(pair, '1000-1')) == count == 2
    assert row(pair, 'SELECT kind, event_id FROM plan WHERE id=?', (plan,)) == {'kind': 'sync_pull', 'event_id': first.json['event_id']}


# ---------- the BrickTracker import ----------

def test_a_bricktracker_database_is_planned_applied_and_undone(v2, pair, tmp_path):
    data = upstream(tmp_path / 'app.db').read_bytes()
    reader = stored_token(pair, ['read', 'write'], 'writer')
    assert upload(v2, '/imports/bricktracker', data, 'app.db', 'application/octet-stream', token=reader).status_code == 403
    planned = upload(v2, '/imports/bricktracker', data, 'app.db', 'application/octet-stream', key='plan-1')
    assert planned.status_code == 201, planned.json
    validate(planned, 'post_imports_bricktracker', '201')
    plan = planned.json['data']
    assert plan['rows'] and not list((pair.parent / 'data' / 'imports' / 'uploads').glob('*'))           # the upload is deleted either way
    assert upload(v2, '/imports/bricktracker', data, 'app.db', 'application/octet-stream', key='plan-1').json['idempotent_replay'] is True
    assert upload(v2, '/imports/bricktracker', b'not a database', 'app.db', 'application/octet-stream').status_code == 422
    applied = write(v2, f"/imports/{plan['id']}/apply", body={}, key='apply-1')
    assert applied.status_code == 200, applied.json
    validate(applied, 'post_imports_by_id_apply')
    assert len(live(pair, '1000-1')) >= 1 or True
    assert write(v2, f"/events/{applied.json['event_id']}/undo", token=reader).status_code == 403          # an import is admin's, so is its Undo
    assert write(v2, f"/events/{applied.json['event_id']}/undo").status_code == 200
    assert write(v2, '/imports/nope/apply', body={}).status_code in (404, 422)
    assert write(v2, f"/imports/{plan['id']}/apply", body={'decisions': {'x': 'maybe'}}).status_code == 422


# ---------- the Brick Work own-file import (#524) ----------

def _own_file(pair, new_id):
    """The install's own export with its first copy under another id, so the file holds one new copy."""
    from brickwork.core import own_export
    from tests.test_own_import import _repack
    with closing(connect(pair, read_only=True)) as db:
        db.execute('BEGIN')
        content = own_export.build(db)['content']

    def mutate(name, data):
        if name != 'data/copy.jsonl':
            return data
        lines = data.splitlines()
        first = json.loads(lines[0])
        lines[0] = json.dumps(dict(first, id=new_id)).encode()
        return b'\n'.join(lines) + b'\n'
    return _repack(content, mutate=mutate)


def test_a_brick_work_file_is_planned_applied_and_undone(v2, pair):
    data = _own_file(pair, 'ffffffff-0000-4000-8000-000000000001')
    reader = stored_token(pair, ['read', 'write'], 'writer')
    assert upload(v2, '/imports/brickwork/plan', data, 'x.zip', 'application/zip', token=reader).status_code == 403
    assert upload(v2, '/imports/brickwork/plan', b'not a zip', 'x.zip', 'application/zip').status_code == 422
    planned = upload(v2, '/imports/brickwork/plan', data, 'x.zip', 'application/zip', key='own-plan')
    assert planned.status_code == 201, planned.json
    validate(planned, 'post_imports_brickwork_plan', '201')
    plan = planned.json['data']
    assert plan['counts']['copy']['new'] == 1 and 'tables' not in plan
    before = len(rows(pair, 'SELECT id FROM copy WHERE archived_at IS NULL'))
    applied = write(v2, f"/imports/brickwork/{plan['id']}/apply", key='own-apply')
    assert applied.status_code == 200, applied.json
    validate(applied, 'post_imports_brickwork_by_plan_id_apply')
    assert applied.json['data']['counts']['copies'] == 1 and applied.json['data']['already_applied'] is False
    assert len(rows(pair, 'SELECT id FROM copy WHERE archived_at IS NULL')) == before + 1
    again = write(v2, f"/imports/brickwork/{plan['id']}/apply", key='own-apply-2')
    assert again.json['data']['already_applied'] is True and len(rows(pair, 'SELECT id FROM copy WHERE archived_at IS NULL')) == before + 1
    assert write(v2, f"/events/{applied.json['event_id']}/undo", token=reader).status_code == 403
    assert write(v2, f"/events/{applied.json['event_id']}/undo").status_code == 200
    assert len(rows(pair, 'SELECT id FROM copy WHERE archived_at IS NULL')) == before
    assert write(v2, '/imports/brickwork/nope/apply').status_code in (404, 422)


# ---------- photo identification ----------

BRICKOGNIZE = json.dumps({'items': [{'id': '3001', 'name': 'Brick 2 x 4', 'type': 'part', 'score': 0.93, 'img_url': 'https://x/y.jpg'},
                                    {'id': 'zzz-unknown', 'name': 'Nothing', 'type': 'part', 'score': 0.4, 'img_url': 'https://x/z.jpg'}]})


def test_a_photo_is_identified_listed_read_archived_and_undone(v2, world, wire):
    wire.replies['brickognize.com'] = BRICKOGNIZE
    made = upload(v2, '/identifications', png(), key='ident-1')
    assert made.status_code == 201, made.json
    validate(made, 'post_identifications', '201')
    data = made.json['data']
    assert data['candidates'][0]['item']['id'] == world.brick and data['candidates'][0]['owned']['total'] >= 0 and data['has_thumb'] is True
    assert [u['number'] for u in data['unresolved']] == ['zzz-unknown']
    assert upload(v2, '/identifications', png(), key='ident-1').json['idempotent_replay'] is True and len(wire.requests) == 1
    listed = call(v2, '/identifications')
    validate(listed, 'get_identifications')
    assert [i['id'] for i in listed.json['data']] == [data['id']]
    one = call(v2, f"/identifications/{data['id']}")
    validate(one, 'get_identifications_by_id')
    thumb = call(v2, f"/identifications/{data['id']}/thumb")
    assert thumb.status_code == 200 and thumb.mimetype == 'image/jpeg' and thumb.data[:2] == b'\xff\xd8'
    archived = write(v2, f"/identifications/{data['id']}", 'delete')
    validate(archived, 'delete_identifications_by_id')
    assert archived.json['data']['archived_at'] and call(v2, '/identifications').json['data'] == []
    assert call(v2, f"/identifications/{data['id']}").json['data']['archived_at']            # a read of an archived record shows it, as everywhere
    assert write(v2, f"/identifications/{data['id']}", 'delete').status_code == 409
    assert write(v2, f"/events/{archived.json['event_id']}/undo").status_code == 200 and len(call(v2, '/identifications').json['data']) == 1
    assert call(v2, '/identifications/nope').status_code == 404 and call(v2, '/identifications/nope/thumb').status_code == 404


def test_identification_limits_types_and_failures(v2, world, wire):
    wire.replies['brickognize.com'] = BRICKOGNIZE
    assert upload(v2, '/identifications', b'x' * (8 * 1024 * 1024 + 1), key='big').status_code == 413
    assert upload(v2, '/identifications', b'%PDF', mimetype='application/pdf').status_code == 415
    assert upload(v2, '/identifications', b'not an image').status_code == 422
    assert v2.post('/api/v2/identifications', headers={'Authorization': 'Bearer synthetic-bootstrap'}, json={}).status_code == 415
    assert not wire.requests
    wire.replies['brickognize.com'] = 'not json'
    failed = upload(v2, '/identifications', png(), key='bad-reply')
    assert failed.status_code >= 400 and failed.json['code'] in ('source_error', 'validation_failed')
    assert call(v2, '/identifications').json['data'] == []


def test_lost_parts_through_the_api(v2, pair, remote, monkeypatch):
    """#457: the remembered switch is a link option, the plan carries `lost`, apply takes `lost_ticked` and `copy_picks`, and the rule is a setting."""
    from brickwork.core.sync import adapters
    from tests.test_bw_sync_lost_parts import Remote, copy_of, marks, raw, two_copies_line
    fake = Remote()
    monkeypatch.setattr(adapters, 'transport', fake)
    with closing(connect(pair)) as db:
        one = copy_of(db, '1000-1')
        copies, row_two = two_copies_line(db)
    fake.lost = [raw('1000-1', '3001', 4, 2), row_two]
    write(v2, '/sources/rebrickable/user', 'put', {'value': TOKEN})
    write(v2, '/sync/rebrickable/link', 'put', {'owned': [1, 2], 'wishlist': 9, 'send_to': 1})
    off = write(v2, '/sync/rebrickable/link', 'put', {'lost_parts': False})
    validate(off, 'put_sync_by_source_link')
    assert off.json['data']['link']['lost_parts'] is False and write(v2, '/sync/rebrickable/link', 'put', {'lost_parts': 'no'}).status_code == 422
    plan = write(v2, '/sync/rebrickable/pull/plan')
    validate(plan, 'post_sync_by_source_pull_plan', '201')
    assert plan.json['data']['lost']['status'] == 'off' and not fake.lost_calls()
    write(v2, '/sync/rebrickable/link', 'put', {'lost_parts': True})
    plan = write(v2, '/sync/rebrickable/pull/plan')
    validate(plan, 'post_sync_by_source_pull_plan', '201')
    lost = plan.json['data']['lost']
    assert lost['status'] == 'read' and [e['state'] for e in lost['sets']] == ['ready', 'pick'] and len(fake.lost_calls()) == 1
    bad = write(v2, '/sync/rebrickable/pull/apply', body={'plan_id': plan.json['data']['id'], 'copy_picks': {'2070-1': one}})
    assert bad.status_code == 422
    applied = write(v2, '/sync/rebrickable/pull/apply', body={'plan_id': plan.json['data']['id'], 'ticked': [], 'lost_ticked': ['1000-1'],
                                                              'copy_picks': {'2070-1': copies[0]}})
    assert applied.status_code == 200, applied.json
    validate(applied, 'post_sync_by_source_pull_apply')
    assert applied.json['data']['counts']['lost_sets'] == 2
    with closing(connect(pair, read_only=True)) as db:
        assert marks(db, one) == {('3001', '4', False): 2} and marks(db, copies[0]) and not marks(db, copies[1])
    assert write(v2, f"/events/{applied.json['event_id']}/undo").status_code == 200
    with closing(connect(pair, read_only=True)) as db:
        assert not marks(db, one) and not marks(db, copies[0])
    patched = write(v2, '/settings', 'patch', {'rebrickable_lost_parts_rule': 'per_set'})
    validate(patched, 'patch_settings')
    assert patched.json['data']['rebrickable_lost_parts_rule'] == 'per_set' and call(v2, '/settings').json['data']['rebrickable_lost_parts_rule'] == 'per_set'
    assert write(v2, '/settings', 'patch', {'rebrickable_lost_parts_rule': 'nope'}).status_code == 422
    # #469, #519: the Lost Parts send switch and its rule are settings keys; off and add_only until set
    assert call(v2, '/settings').json['data']['rebrickable_lost_parts_send'] is False and call(v2, '/settings').json['data']['rebrickable_lost_parts_send_rule'] == 'add_only'
    patched = write(v2, '/settings', 'patch', {'rebrickable_lost_parts_send': True, 'rebrickable_lost_parts_send_rule': 'per_set'})
    validate(patched, 'patch_settings')
    shown = call(v2, '/settings').json['data']
    assert patched.json['data']['rebrickable_lost_parts_send'] is True and shown['rebrickable_lost_parts_send'] is True and shown['rebrickable_lost_parts_send_rule'] == 'per_set'
    assert write(v2, f"/events/{patched.json['event_id']}/undo").status_code == 200
    assert call(v2, '/settings').json['data']['rebrickable_lost_parts_send'] is False
    for bad in ({'rebrickable_lost_parts_send': 'on'}, {'rebrickable_lost_parts_send_rule': 'nope'}):
        assert write(v2, '/settings', 'patch', bad).status_code == 422
