"""Review fixes of M.11c (issue #113): Undo needs the scope of the write it undoes, a token's idempotency key is its own for the checker too, a
no-op check start answers 200, the fingerprint of a write holds its query, and a handled refusal logs no traceback. Invented data, no network."""
import logging

import pytest

from tests.api2 import call, events, row, rows, stored_token, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


# ---------- 1. Undo needs the scope of what it undoes ----------

def test_a_write_token_cannot_undo_an_admin_change(v2, world, pair):
    writer = stored_token(pair, ['read', 'write'], 'writer')
    changed = write(v2, '/settings', 'patch', {'retail_country': 'US'})
    assert changed.status_code == 200 and changed.json['undo_url']
    refused = write(v2, f"/events/{changed.json['event_id']}/undo", token=writer)
    assert refused.status_code == 403 and refused.json['code'] == 'forbidden'
    assert call(v2, '/settings').json['data']['retail_country'] == 'US'
    assert write(v2, f"/events/{changed.json['event_id']}/undo").status_code == 200                     # an admin may
    assert call(v2, '/settings').json['data']['retail_country'] == 'DE'


def test_every_event_an_admin_operation_writes_is_undone_only_by_admin():
    from brickwork.core import undo
    admin_only = {('settings', 'save'), ('import', 'receipt'), ('source', 'enabled'), ('source_key', 'save'),
                  ('source_key', 'archive'), ('bw_token', 'create'), ('bw_token', 'revoke')}
    assert {pair for pair, u in undo.REGISTRY.items() if u.admin} >= admin_only


# ---------- 2. another token's key is another key for the checker ----------

def test_two_tokens_with_one_key_each_get_their_own_check_receipt(v2, world, pair):
    other = stored_token(pair, ['read', 'write'], 'other')
    path = f'/copies/{world.copy_c}/check'
    first = write(v2, path, body={'action': 'start'}, key='shared-1')
    session = first.json['data']['session']['id']
    a = write(v2, path, body={'action': 'next', 'session': session}, key='shared-2')
    b = write(v2, path, body={'action': 'next', 'session': session}, key='shared-2', token=other)
    assert a.status_code == b.status_code == 200
    assert b.json['idempotent_replay'] is False and b.json['event_id'] != a.json['event_id']
    assert rows(pair, "SELECT actor FROM main.event WHERE id=?", (b.json['event_id'],)) == [{'actor': 'other'}]


# ---------- 3. a no-op write answers 200 ----------

def test_starting_a_check_that_is_running_is_a_no_op_with_no_event(v2, world, pair):
    path = f'/copies/{world.copy_c}/check'
    first = write(v2, path, body={'action': 'start'})
    count = len(events(pair))
    again = write(v2, path, body={'action': 'start'})
    assert again.status_code == 200, again.json
    validate(again, 'post_copies_by_id_check')
    assert again.json['event_id'] is None and 'undo_url' not in again.json
    assert again.json['data']['session']['id'] == first.json['data']['session']['id']
    assert [e for e in events(pair, 'id>?', (count,)) if e['entity_kind'] != 'bw_api'] == []


def test_the_other_writes_that_change_nothing_still_answer_200(v2, world):
    for method, path, body in (('patch', f'/copies/{world.copy_a}', {'note': 'Flea market'}), ('put', f'/copies/{world.copy_a}/pin', {'pinned': False}),
                               ('put', f'/copies/{world.copy_a}/flags', {'flags': [world.tag, world.checked]}),
                               ('put', f'/copies/{world.copy_c}/checked', {'checked': False}), ('patch', f'/stock/{world.stock_brick}', {'condition': 'used'}),
                               ('patch', f'/wishes/{world.wish_part}', {'quantity': 2}), ('patch', f'/storages/{world.shelf}', {'name': 'Shelf A'}),
                               ('patch', '/settings', {'retail_country': 'DE'})):
        for _ in range(2):
            assert write(v2, path, method, body).status_code == 200, (method, path)


# ---------- 4. the query is part of the request ----------

def test_the_same_key_with_another_query_is_a_conflict_not_a_replay(v2, world, pair):
    path = f'/storages/{world.shelf}'
    first = write(v2, path + '?move_to_unstored=true', 'delete', key='q-1')
    assert first.status_code == 200
    other = write(v2, path + '?move_to_unstored=false', 'delete', key='q-1')
    assert other.status_code == 409 and other.json['code'] == 'idempotency_conflict'
    same = write(v2, path + '?move_to_unstored=true', 'delete', key='q-1')
    assert same.status_code == 200 and same.json['idempotent_replay'] is True


# ---------- 5. a handled refusal logs no traceback ----------

def test_a_refusal_of_the_store_logs_a_line_not_a_traceback(v2, world, caplog):
    path = f'/copies/{world.copy_c}/inventory'
    inventory = call(v2, f'/copies/{world.copy_c}').json['data']['inventory']
    body = {'source': 'rebrickable', 'version': inventory['version']}
    with caplog.at_level(logging.DEBUG):
        refused = write(v2, path, body=body)
    assert refused.status_code == 409
    assert [r for r in caplog.records if r.exc_info or r.exc_text] == []
    assert [r for r in caplog.records if r.levelno > logging.INFO] == []
    assert any('NothingToSwitch' in r.getMessage() or 'already' in r.getMessage().lower() for r in caplog.records)


def test_an_unexpected_exception_keeps_its_traceback_in_the_log(v2, world, caplog, monkeypatch):
    from brickwork.core import checker

    def boom(*args, **kwargs):
        raise RuntimeError('synthetic bug')
    monkeypatch.setattr(checker, 'write', boom)
    with caplog.at_level(logging.INFO):
        failed = write(v2, f'/copies/{world.copy_c}/check', body={'action': 'start'})
    assert failed.status_code == 500
    assert [r for r in caplog.records if r.exc_info and 'synthetic bug' in str(r.exc_info[1])]


# ---------- follow-ups: preferred false, fingerprint version ----------

def test_preferred_false_leaves_the_preference_alone_and_never_clears_it(v2, world):
    path = f'/items/{world.brick}/links'
    made = write(v2, path, 'put', {'provider': 'bricklink', 'type': 'P', 'no': '3001z', 'preferred': True})
    assert made.json['data']['preferred'] is True
    again = write(v2, path, 'put', {'provider': 'bricklink', 'type': 'P', 'no': '3001z', 'preferred': False})
    assert again.status_code == 200 and again.json['data']['preferred'] is True and again.json['event_id'] is None
    other = write(v2, path, 'put', {'provider': 'bricklink', 'type': 'P', 'no': '3001y', 'preferred': False})
    assert other.json['data']['preferred'] is False
    assert [l['no'] for l in call(v2, path).json['data'] if l['preferred']] == ['3001z']
    swapped = write(v2, path, 'put', {'provider': 'bricklink', 'type': 'P', 'no': '3001y', 'preferred': True})
    assert [l['no'] for l in call(v2, path).json['data'] if l['preferred']] == ['3001y'] and swapped.status_code == 200


def test_a_receipt_keeps_the_version_of_its_fingerprint_and_replays_under_it(v2, world, pair, monkeypatch):
    import json
    from brickwork.api2 import writes
    first = write(v2, '/wishlists', body={'name': 'Versioned'}, key='fp-1')
    receipt = events(pair, "entity_kind='bw_api' AND field='op:fp-1'")[0]
    assert json.loads(receipt['new_value'])['v'] == writes.FINGERPRINT == 1
    # a later version hashes differently; the receipt of version 1 still replays and still conflicts on another body
    monkeypatch.setattr(writes, 'DIGESTS', {**writes.DIGESTS, 2: lambda body, content: 'v2-' + writes.digest_v1(body, content)})
    monkeypatch.setattr(writes, 'FINGERPRINT', 2)
    again = write(v2, '/wishlists', body={'name': 'Versioned'}, key='fp-1')
    assert again.status_code == first.status_code and again.json['idempotent_replay'] is True
    assert write(v2, '/wishlists', body={'name': 'Other'}, key='fp-1').status_code == 409
