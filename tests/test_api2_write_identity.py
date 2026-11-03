"""API v2 writes on identity and history (M.11c, issue #113): an item's BrickLink links, merge and unmerge, the switch of a copy's part list (with
BrickLink's list pending and cancelled), and Undo of a whole write. New for v2 (v1 had no identity); the cases follow test_store4_merge,
test_store4_switch and test_store4_pending through the API. Every answer is validated against `openapi-v2.yaml`. Invented data, no network."""
from contextlib import closing

import pytest

from brickwork.core.connect import connect
from brickwork.store4 import fetched, identity
from tests.api2 import call, events, row, rows, stored_token, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import table_digest

KEYS = ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET')
RED = 5


def digest(pair):
    with closing(connect(pair)) as db:
        return table_digest(db, skip=('event', 'event_undo', 'item_merge', 'stock_transfer'))


def live_lines(pair, copy_id):
    """The copy's live lines: what a part list switch changes and an Undo of it puts back (the retired rows it leaves are not lines)."""
    return rows(pair, 'SELECT p.item_id, p.color_id, p.is_spare, p.quantity, p.missing, f.item_id AS figure FROM main.copy_part p LEFT JOIN main.copy_figure f ON f.id=p.copy_figure_id '
                      'WHERE p.copy_id=? AND p.retired_at IS NULL ORDER BY 1, 2, 3, 6', (copy_id,))


@pytest.fixture
def key(monkeypatch):
    for name in KEYS:
        monkeypatch.setenv('BW_BRICKLINK_' + name, 'x')


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    for name in KEYS:
        monkeypatch.delenv('BW_BRICKLINK_' + name, raising=False)


# ---------- links ----------

def link(v2, item, body=None, **kwargs):
    return write(v2, f'/items/{item}/links', 'put', body or {'provider': 'bricklink', 'type': 'P', 'no': '3001z'}, **kwargs)


def test_a_manual_link_is_added_and_the_number_then_finds_the_item(v2, world, pair):
    made = link(v2, world.brick)
    validate(made, 'put_items_by_id_links')
    assert made.json['data'] == {'provider': 'bricklink', 'type': 'P', 'no': '3001z', 'color_id': None, 'color_scoped': False, 'brickwork_color_id': None,
                                 'status': 'manual', 'method': 'user', 'origin': 'user', 'preferred': False, 'decided_at': made.json['data']['decided_at']}
    assert call(v2, '/parts/by-number/3001z').json['data']['id'] == world.brick
    event = events(pair, 'id=?', (made.json['event_id'],))[0]
    assert (event['entity_kind'], event['field'], event['via'], event['actor']) == ('item_link', 'add', 'api', 'bootstrap')
    assert write(v2, f"/events/{made.json['event_id']}/undo").status_code == 200
    assert call(v2, '/parts/by-number/3001z').status_code == 404


def test_putting_the_same_link_again_changes_nothing_and_writes_no_event(v2, world, pair):
    first = link(v2, world.brick)
    count = len(events(pair))
    again = link(v2, world.brick)
    validate(again, 'put_items_by_id_links')
    assert again.json['data'] == first.json['data'] and again.json['event_id'] is None and 'undo_url' not in again.json
    assert [e for e in events(pair, 'id>?', (count,)) if e['entity_kind'] != 'bw_api'] == []
    existing = link(v2, world.brick, {'provider': 'bricklink', 'type': 'P', 'no': '3001'})                      # the catalogue's own link counts as there
    assert existing.status_code == 200 and existing.json['data']['status'] in ('matched', 'inferred', 'manual') and existing.json['event_id'] is None


def test_a_link_is_made_preferred_for_its_scope_and_one_undo_takes_back_both_steps(v2, world, pair):
    before = digest(pair)
    made = link(v2, world.brick, {'provider': 'bricklink', 'type': 'P', 'no': '3001z', 'preferred': True})
    validate(made, 'put_items_by_id_links')
    assert made.json['data']['preferred'] is True
    links = call(v2, f'/items/{world.brick}/links').json['data']
    assert [l['no'] for l in links if l['preferred']] == ['3001z']                                              # the old preferred link lost the mark
    assert call(v2, f'/items/{world.brick}').json['data']['bricklink'][0]['no'] == '3001z'
    assert write(v2, f"/events/{made.json['event_id']}/undo").status_code == 200
    assert digest(pair) == before
    assert call(v2, '/parts/by-number/3001z').status_code == 404


def test_a_link_for_one_colour_is_scoped_in_the_bricklink_colour_space(v2, world, pair):
    made = link(v2, world.brick, {'provider': 'bricklink', 'type': 'P', 'no': '3001r', 'color_id': RED, 'preferred': True})
    validate(made, 'put_items_by_id_links')
    assert (made.json['data']['color_id'], made.json['data']['color_scoped'], made.json['data']['brickwork_color_id'], made.json['data']['preferred']) == (RED, True, world.red, True)
    assert call(v2, f'/parts/by-number/3001r?color={RED}').json['data']['id'] == world.brick
    assert call(v2, '/parts/by-number/3001r').json['data']['id'] == world.brick                                   # without a colour a link of any scope matches
    assert call(v2, '/parts/by-number/3001r?color=1').status_code == 404
    assert link(v2, world.brick, {'provider': 'bricklink', 'type': 'P', 'no': '3001r', 'color_id': 99999}).status_code == 422


def test_a_link_to_check_is_confirmed_by_putting_it(v2, coll, world, pair):
    coll.link(world.brick, '3001c', kind='P', status='to_check')
    confirmed = link(v2, world.brick, {'provider': 'bricklink', 'type': 'P', 'no': '3001c'})
    validate(confirmed, 'put_items_by_id_links')
    assert confirmed.json['data']['status'] == 'manual'
    assert events(pair, 'id=?', (confirmed.json['event_id'],))[0]['field'] == 'confirm'


def test_a_link_is_refused_when_it_would_be_a_merge_or_does_not_fit(v2, coll, world):
    taken = link(v2, world.plate, {'provider': 'bricklink', 'type': 'P', 'no': '3001'})                        # 3001 is the brick's
    assert taken.status_code == 409 and taken.json['code'] == 'conflict' and 'merge' in taken.json['detail']
    assert link(v2, world.brick, {'provider': 'bricklink', 'type': 'S', 'no': '3001z'}).status_code == 422       # a part's BrickLink type is P
    assert link(v2, world.brick, {'provider': 'bricklink', 'type': 'P', 'no': 'has space'}).status_code == 422
    assert link(v2, world.brick, {'provider': 'rebrickable', 'type': 'P', 'no': '3001z'}).status_code == 422
    assert link(v2, world.brick, {'type': 'P', 'no': '3001z', 'preferred': 'yes'}).status_code == 422
    assert link(v2, 987654321).status_code == 404
    assert link(v2, 'nope').status_code == 404
    assert link(v2, world.brick, key=False).status_code == 428
    loser = coll.local('part', 'Doubled', born_key='x7')
    assert write(v2, f'/items/{loser}/merge', body={'survivor': {'id': world.brick}}).status_code == 200
    merged = link(v2, loser)
    assert merged.status_code == 409 and merged.json['code'] == 'merged' and merged.json['survivor'] == world.brick


# ---------- merge and unmerge ----------

def test_a_local_item_is_merged_into_a_survivor_and_its_id_then_redirects(v2, coll, world, pair):
    loser = coll.local('part', 'Doubled part', born_key='x1')
    coll.add_stock('part', loser, colour=world.red, quantity=2, condition='new')
    before = digest(pair)
    merged = write(v2, f'/items/{loser}/merge', body={'survivor': {'id': world.brick}})
    validate(merged, 'post_items_by_id_merge')
    data = merged.json['data']
    assert (data['survivor']['id'], data['merged']['id'], data['receipt']['event_id']) == (world.brick, loser, merged.json['event_id'])
    assert data['receipt']['counts'] and merged.json['undo_url'] == f"/api/v2/events/{merged.json['event_id']}/undo"
    redirected = call(v2, f'/items/{loser}')
    assert redirected.status_code == 307 and redirected.headers['Location'] == f'/api/v2/items/{world.brick}'
    again = write(v2, f'/items/{loser}/merge', body={'survivor': {'id': world.brick}})
    assert again.status_code == 409 and again.json['code'] == 'merged'
    assert write(v2, f"/events/{merged.json['event_id']}/undo").status_code == 200
    assert digest(pair) == before and call(v2, f'/items/{loser}').status_code == 200


def test_unmerge_by_the_merged_id_restores_every_row_and_names_the_merge(v2, coll, world, pair):
    loser = coll.local('part', 'Doubled part', born_key='x1')
    coll.add_stock('part', loser, colour=world.red, quantity=2, condition='new')
    before = digest(pair)
    merged = write(v2, f'/items/{loser}/merge', body={'survivor': {'id': world.brick}})
    other = write(v2, f'/items/{loser}/unmerge', body={'merge_id': merged.json['data']['merge_id'] + 1})
    assert other.status_code == 409
    unmerged = write(v2, f'/items/{loser}/unmerge', body={})
    validate(unmerged, 'post_items_by_id_unmerge')
    assert (unmerged.json['data']['merge_id'], unmerged.json['data']['survivor']['id'], unmerged.json['data']['merged']['id']) == (merged.json['data']['merge_id'], world.brick, loser)
    assert digest(pair) == before and call(v2, f'/items/{loser}').status_code == 200
    assert 'undo_url' not in unmerged.json                                                                      # an unmerge is not itself undone: merge again
    assert write(v2, f'/items/{loser}/unmerge', body={}).status_code == 409                                    # not merged any more
    assert write(v2, '/items/987654321/unmerge', body={}).status_code == 404
    remerge = write(v2, f'/items/{loser}/merge', body={'survivor': {'kind': 'part', 'key': '3001'}})
    assert remerge.status_code == 200 and remerge.json['data']['survivor']['id'] == world.brick                # the survivor by its BrickLink number


def test_unmerge_is_refused_when_a_moved_row_changed_since(v2, coll, world):
    loser = coll.local('part', 'Doubled part', born_key='x1')
    coll.add_stock('part', loser, colour=world.red, quantity=2, condition='new')
    assert write(v2, f'/items/{loser}/merge', body={'survivor': {'id': world.brick}}).status_code == 200
    assert write(v2, f'/stock/{world.stock_brick_new}', 'patch', {'note': 'changed after the merge'}).status_code == 200      # the line the loser's stock merged into
    refused = write(v2, f'/items/{loser}/unmerge', body={})
    assert refused.status_code == 409 and refused.json['code'] == 'conflict'


def test_a_merge_the_rules_refuse_is_409_and_one_that_names_nothing_is_422(v2, coll, world):
    local = coll.local('part', 'Local part', born_key='x2')
    gear = coll.local('gear', 'Local gear', born_key='x3')
    cases = [(world.brick, {'id': local}, 409),                                   # a live catalogue item cannot be merged away
             (local, {'id': local}, 409),                                         # not into itself
             (local, {'id': gear}, 409),                                          # not into another kind
             (local, {'id': 987654321}, 422), (local, {'kind': 'part', 'key': 'nothing'}, 422)]
    for loser, survivor, status in cases:
        refused = write(v2, f'/items/{loser}/merge', body={'survivor': survivor})
        assert refused.status_code == status, (loser, survivor, refused.get_data(as_text=True))
    assert write(v2, '/items/987654321/merge', body={'survivor': {'id': world.brick}}).status_code == 404
    assert write(v2, f'/items/{local}/merge', body={'survivor': {'id': world.brick, 'kind': 'part', 'key': '3001'}}).status_code == 422
    assert write(v2, f'/items/{local}/merge', body={}).status_code == 422
    assert write(v2, f'/items/{local}/merge', body={'survivor': {'id': world.brick}}, key=False).status_code == 428


def test_a_survivor_named_by_an_ambiguous_number_is_409_with_the_candidates(v2, coll, world):
    first, second = coll.local('part', 'Twin one', born_key='y1'), coll.local('part', 'Twin two', born_key='y2')
    for each in (first, second):
        coll.link(each, 'twin', kind='P')
    loser = coll.local('part', 'Doubled', born_key='x4')
    refused = write(v2, f'/items/{loser}/merge', body={'survivor': {'kind': 'part', 'key': 'twin'}})
    assert refused.status_code == 409 and refused.json['code'] == 'ambiguous'
    assert sorted(c['id'] for c in refused.json['candidates']) == sorted([first, second])


# ---------- the part list of a copy ----------

def versions(v2, copy_id):
    inventory = call(v2, f'/copies/{copy_id}').json['data']['inventory']
    return inventory['version'], inventory['of']


def test_a_copy_switches_to_another_rebrickable_list_and_undo_switches_back(v2, world, pair):
    version, count = versions(v2, world.copy_c)
    assert count == 2
    other = 1 if version == 2 else 2
    before = live_lines(pair, world.copy_c)
    switched = write(v2, f'/copies/{world.copy_c}/inventory', body={'source': 'rebrickable', 'version': other})
    validate(switched, 'post_copies_by_id_inventory')
    assert switched.json['data']['inventory']['version'] == other
    event = events(pair, 'id=?', (switched.json['event_id'],))[0]
    assert (event['entity_kind'], event['field'], event['via'], event['actor']) == ('copy', 'part_list_switch', 'api', 'bootstrap')
    same = write(v2, f'/copies/{world.copy_c}/inventory', body={'source': 'rebrickable', 'version': other})
    assert same.status_code == 409 and same.json['code'] == 'conflict'
    assert write(v2, f"/events/{switched.json['event_id']}/undo").status_code == 200
    assert live_lines(pair, world.copy_c) == before and versions(v2, world.copy_c)[0] == version
    assert write(v2, f'/copies/{world.copy_c}/inventory', body={'source': 'rebrickable', 'version': 99}).status_code == 422


def test_a_switch_may_be_remembered_for_new_copies_of_the_set(v2, world, pair):
    version, _ = versions(v2, world.copy_c)
    other = 1 if version == 2 else 2
    before = live_lines(pair, world.copy_c)
    switched = write(v2, f'/copies/{world.copy_c}/inventory', body={'source': 'rebrickable', 'version': other, 'remember': True})
    validate(switched, 'post_copies_by_id_inventory')
    assert row(pair, 'SELECT inventory_source, inventory_version FROM main.set_preference WHERE item_id=?', (world.duplo,)) == {'inventory_source': 'rebrickable', 'inventory_version': other}
    assert write(v2, f"/events/{switched.json['event_id']}/undo").status_code == 200
    assert live_lines(pair, world.copy_c) == before
    assert row(pair, 'SELECT * FROM main.set_preference WHERE item_id=?', (world.duplo,)) is None                 # the preference goes back with the switch


def test_the_switch_checks_the_tag_the_copy_and_the_body(v2, world):
    path = f'/copies/{world.copy_c}/inventory'
    version, _ = versions(v2, world.copy_c)
    body = {'source': 'rebrickable', 'version': 1 if version == 2 else 2}
    assert write(v2, path, body=body, headers={'If-Match': '"stale"'}).status_code == 412
    assert write(v2, path, body={'source': 'nowhere'}).status_code == 422
    assert write(v2, path, body={'source': 'rebrickable', 'version': 'x'}).status_code == 422
    assert write(v2, path, body={'source': 'bricklink', 'version': 1}).status_code == 422
    assert write(v2, '/copies/nope/inventory', body=body).status_code == 404
    assert write(v2, path, body=body, key=False).status_code == 428
    tag = call(v2, f'/copies/{world.copy_c}').headers['ETag']
    assert write(v2, path, body=body, headers={'If-Match': tag}).status_code == 200
    write(v2, f'/copies/{world.copy_b}', 'delete')
    assert write(v2, f'/copies/{world.copy_b}/inventory', body=body).json['code'] == 'archived'


def test_bricklinks_list_needs_a_key(v2, world):
    refused = write(v2, f'/copies/{world.copy_c}/inventory', body={'source': 'bricklink'})
    assert refused.status_code == 424 and refused.json['code'] == 'source_not_configured'


def test_a_copy_asks_for_bricklinks_list_waits_and_cancels(v2, key, world, pair):
    path = f'/copies/{world.copy_c}/inventory'
    asked = write(v2, path, body={'source': 'bricklink', 'remember': True})
    validate(asked, 'post_copies_by_id_inventory', '202')
    job = row(pair, "SELECT pending_job_id FROM main.copy WHERE id=?", (world.copy_c,))['pending_job_id']
    assert asked.headers['Location'] == f'/api/v2/jobs/{job}' and asked.json['data']['inventory']['pending'] == 'bricklink'
    assert row(pair, "SELECT state, kind FROM main.job WHERE id=?", (job,)) == {'state': 'queued', 'kind': 'bricklink_subsets'}
    assert write(v2, path, body={'source': 'bricklink'}).status_code == 409                                       # already waiting
    cancelled = write(v2, f'{path}/pending', 'delete')
    validate(cancelled, 'delete_copies_by_id_inventory_pending')
    assert cancelled.json['data']['inventory']['pending'] is None
    assert row(pair, 'SELECT * FROM main.set_preference WHERE item_id=?', (world.duplo,)) is None                 # cancelling puts the remembered choice back
    again = write(v2, f'{path}/pending', 'delete')
    assert again.status_code == 409 and again.json['code'] == 'conflict'
    assert write(v2, '/copies/nope/inventory/pending', 'delete').status_code == 404


def test_with_a_fetched_list_the_switch_to_bricklink_is_at_once(v2, key, coll, world, pair):
    lines = rows(pair, 'SELECT item_id, color_id, is_spare, quantity FROM main.copy_part WHERE copy_id=? AND retired_at IS NULL AND copy_figure_id IS NULL', (world.copy_c,))
    fetched.write_fetched(coll.db, world.duplo, 'bricklink', [(r['item_id'], r['color_id'], r['is_spare'], r['quantity'] + 1) for r in lines])
    coll.db.commit()
    switched = write(v2, f'/copies/{world.copy_c}/inventory', body={'source': 'bricklink'})
    validate(switched, 'post_copies_by_id_inventory')
    assert switched.json['data']['inventory']['source'] == 'bricklink' and switched.json['undo_url']
    assert write(v2, f"/events/{switched.json['event_id']}/undo").status_code == 200
    assert call(v2, f'/copies/{world.copy_c}').json['data']['inventory']['source'] == 'rebrickable'


# ---------- Undo ----------

def test_undo_of_a_write_that_made_several_events_undoes_them_all(v2, world):
    made = write(v2, f'/wishes/{world.wish_part}/to-owned', body={'quantity': 1})
    assert made.status_code == 200
    undone = write(v2, f"/events/{made.json['event_id']}/undo")
    validate(undone, 'post_events_by_id_undo')
    assert undone.json['data']['undone_event_id'] == made.json['event_id'] and undone.json['data']['already_undone'] is False
    assert call(v2, f'/wishes/{world.wish_part}').json['data']['quantity'] == 2
    assert call(v2, f"/stock/{made.json['data']['ids'][0]}").json['data']['quantity'] == 2            # the white plates were merged into the line of two


def test_undo_answers_for_the_unknown_the_unundoable_and_the_blocked(v2, world, pair):
    assert write(v2, '/events/999999/undo').status_code == 404
    assert write(v2, '/events/nope/undo').status_code == 404
    plain = events(pair, "entity_kind='copy' AND field='add'")[0]
    refused = write(v2, f"/events/{plain['id']}/undo")
    assert refused.status_code == 409 and refused.json['code'] == 'not_undoable'
    first = write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'one'})
    write(v2, f'/copies/{world.copy_a}', 'patch', {'note': 'two'})
    blocked = write(v2, f"/events/{first.json['event_id']}/undo")
    assert blocked.status_code == 409 and blocked.json['code'] == 'undo_blocked'
    assert write(v2, f"/events/{first.json['event_id']}/undo", key=False).status_code == 428


def test_undoing_a_token_needs_the_admin_scope_even_with_a_write_token(v2, pair):
    from brickwork.core import tokens
    with closing(connect(pair)) as db:                                                                              # the token routes are M.11d: core's writer
        _, event = tokens.create(db, 'later', ['read'])
    event = {'id': event}
    writer = stored_token(pair, ['read', 'write'], 'writer')
    assert write(v2, f"/events/{event['id']}/undo", token=writer).status_code == 403
    assert write(v2, f"/events/{event['id']}/undo").status_code == 200


def test_a_replay_of_a_queued_switch_answers_202_with_the_same_location(v2, key, world):
    path = f'/copies/{world.copy_c}/inventory'
    first = write(v2, path, body={'source': 'bricklink'}, key='queued-1')
    again = write(v2, path, body={'source': 'bricklink'}, key='queued-1')
    assert first.status_code == again.status_code == 202 and again.json['idempotent_replay'] is True
    assert again.headers['Location'] == first.headers['Location']
