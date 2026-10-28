"""API v2 writes on what is owned and wanted (M.11c, issue #113): copies, loose stock, wishes, wishlists, Take, Give, Found and the marks of a copy's
lines. Ported from test_bw_api_m3, test_bw_api_m4, test_bw_api_take_figure, test_bw_wishlists_api, test_bw_check_api_63 and test_bw_review_followups
onto the 4.0 fixtures and the v2 contract: every answer is validated against `openapi-v2.yaml`. Invented data."""
from contextlib import closing

import pytest

from brickwork.core.connect import connect
from tests.api2 import call, events, row, rows, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import table_digest

RED, WHITE = 5, 1                                           # BrickLink colour numbers of the fixture's red and white


def digest(pair):
    """The collection's tables but the log and the provenance rows an Undo keeps (`stock_transfer`: Take and Give leave theirs)."""
    with closing(connect(pair)) as db:
        return table_digest(db, skip=('event', 'event_undo', 'item_merge', 'stock_transfer'))


def part_of(pair, copy_id, rebrickable_part, rebrickable_colour):
    """The id of the live set line of a copy for a Rebrickable part and colour."""
    return row(pair, '''SELECT p.id FROM main.copy_part p JOIN main.item i ON i.id=p.item_id JOIN main.color c ON c.id=p.color_id
                        WHERE p.copy_id=? AND i.born_key=? AND c.born_key=? AND p.copy_figure_id IS NULL AND p.retired_at IS NULL AND p.is_spare=0''',
               (copy_id, rebrickable_part, rebrickable_colour))['id']


def undo(v2, response, key='undo-' + 'x'):
    return write(v2, f"/events/{response.json['event_id']}/undo")


# ---------- every edit is one event, a replay answers the same, Undo takes it all back ----------

def edits(w, pair):
    """(operationId, method, path, body, status) for an edit of each kind; the world's ids fill the paths."""
    brick = part_of(pair, w.copy_a, '3001', '4')
    figure_line = row(pair, 'SELECT id FROM main.copy_figure WHERE copy_id=?', (w.copy_a,))['id']
    return [
        ('patch_copies_by_id', 'patch', f'/copies/{w.copy_a}', {'note': 'A new note', 'condition': 'new'}),
        ('delete_copies_by_id', 'delete', f'/copies/{w.copy_b}', None),
        ('put_copies_by_id_flags', 'put', f'/copies/{w.copy_a}/flags', {'flags': []}),
        ('put_copies_by_id_pin', 'put', f'/copies/{w.copy_a}/pin', {'pinned': True}),
        ('put_copies_by_id_checked', 'put', f'/copies/{w.copy_c}/checked', {'checked': True}),
        ('patch_copies_by_id_parts_by_part_id', 'patch', f'/copies/{w.copy_a}/parts/{brick}', {'missing': 0, 'damaged': 1}),
        ('patch_copies_by_id_figures_by_item_id', 'patch', f'/copies/{w.copy_a}/figures/{row(pair, "SELECT item_id FROM main.copy_figure WHERE id=?", (figure_line,))["item_id"]}', {'missing': 1}),
        ('patch_stock_by_id', 'patch', f'/stock/{w.stock_brick}', {'note': 'A new note', 'purchase_price': '1.25', 'purchase_currency': 'EUR'}),
        ('delete_stock_by_id', 'delete', f'/stock/{w.stock_brick}', None),
        ('put_stock_by_id_flags', 'put', f'/stock/{w.stock_plate}/flags', {'flags': [w.tag]}),
        ('patch_wishes_by_id', 'patch', f'/wishes/{w.wish_part}', {'max_price': '0.75', 'max_price_currency': 'EUR', 'quantity': 3}),
        ('delete_wishes_by_id', 'delete', f'/wishes/{w.wish_set}', None),
        ('put_wishes_by_id_flags', 'put', f'/wishes/{w.wish_part}/flags', {'flags': [w.tag]}),
        ('post_copies_by_id_take', 'post', f'/copies/{w.copy_a}/take', {'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 1}),
        ('post_stock_by_id_give', 'post', f'/stock/{w.stock_brick}/give', {'copy_id': w.copy_a, 'target': 'part', 'target_id': brick, 'quantity': 1}),
    ]


def test_every_edit_is_one_event_replays_and_is_undone_exactly(v2, world, pair):
    for operation, method, path, body in edits(world, pair):
        before, count = digest(pair), len(events(pair))
        response = write(v2, path, method, body, key='edit-' + operation.replace('_', '-')[:60])
        validate(response, operation)
        made = [e for e in events(pair, 'id>?', (count,)) if e['entity_kind'] != 'bw_api']
        assert made and all((e['via'], e['actor']) == ('api', 'bootstrap') for e in made), operation
        newest = events(pair, 'id=?', (response.json['event_id'],))[0]
        assert call(v2, f"/events/{newest['id']}").json['data']['undoable'], operation
        replay = write(v2, path, method, body, key='edit-' + operation.replace('_', '-')[:60])
        assert replay.status_code == response.status_code and replay.json['idempotent_replay'] is True and replay.json['data'] == response.json['data']
        assert len(events(pair)) == count + len(made) + 1, f'{operation}: a replay writes nothing'
        undone = write(v2, f"/events/{response.json['event_id']}/undo")
        validate(undone, 'post_events_by_id_undo')
        assert undone.json['data']['already_undone'] is False
        saved = call(v2, f"/events/{response.json['event_id']}").json['data']
        assert saved['undone'] is True and saved['undoable'] is False, operation
        assert digest(pair) == before, operation
        again = write(v2, f"/events/{response.json['event_id']}/undo")
        assert again.json['data']['already_undone'] is True and again.json['data']['event_id'] == undone.json['data']['event_id']


# ---------- creating ----------

def test_a_copy_is_created_by_number_with_its_fields_and_undone_whole(v2, world, pair):
    before = digest(pair)
    response = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '1000-2'}, 'quantity': 2, 'decision': 'another', 'condition': 'new', 'completeness': 'sealed',
                                          'storage_id': world.shelf, 'purchase_location_id': world.shop, 'purchase_price': '9.90', 'purchase_currency': 'EUR',
                                          'purchase_date': '2026-10-01'})
    validate(response, 'post_copies', '201')
    ids = response.json['data']['ids']
    assert len(ids) == 2 and response.json['undo_url'] == f"/api/v2/events/{response.json['event_id']}/undo"
    for each in ids:
        copy = call(v2, f'/copies/{each}').json['data']
        assert (copy['item']['id'], copy['condition'], copy['completeness'], copy['storage_id'], copy['purchase_location_id'], copy['purchase_price'],
                copy['purchase_currency'], copy['purchase_date']) == (world.gate, 'new', 'sealed', world.shelf, world.shop, '9.90', 'EUR', '2026-10-01')
        assert copy['inventory']['source'] == 'rebrickable'
    assert write(v2, f"/events/{response.json['event_id']}/undo").status_code == 200
    assert all(call(v2, f'/copies/{each}').json['data']['archived_at'] for each in ids)
    assert before != digest(pair)                                       # an undone creation is archived, never deleted


def test_a_set_is_named_by_id_or_by_either_providers_number(v2, world):
    by_id = write(v2, '/copies', body={'item': {'id': world.duplo}})
    by_rebrickable = write(v2, '/copies', body={'item': {'provider': 'rebrickable', 'kind': 'set', 'key': '2070-1'}, 'decision': 'another'})
    by_bricklink = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '2070-1'}, 'decision': 'another'})
    assert by_id.status_code == 409 and by_id.json['code'] == 'conflict'               # owned already: say so, or choose another
    for response in (by_rebrickable, by_bricklink):
        validate(response, 'post_copies', '201')
        assert call(v2, f"/copies/{response.json['data']['ids'][0]}").json['data']['item']['id'] == world.duplo


def test_a_number_that_names_no_item_is_unidentified_and_one_that_names_several_is_ambiguous(v2, coll, world):
    unknown = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '99999-1'}})
    assert unknown.status_code == 422 and unknown.json['code'] == 'unidentified'
    assert write(v2, '/copies', body={'item': {'id': 987654321}}).json['code'] == 'unidentified'
    first, second = coll.local('set', 'Twin one', born_key='7777-1'), coll.local('set', 'Twin two', born_key='7778-1')
    for each in (first, second):
        coll.link(each, '7777-9', kind='S')
    ambiguous = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '7777-9'}})
    assert ambiguous.status_code == 409 and ambiguous.json['code'] == 'ambiguous'
    assert sorted(c['id'] for c in ambiguous.json['candidates']) == sorted([first, second])
    assert write(v2, '/copies', body={'item': {'id': first}, 'decision': 'another'}).status_code == 201     # an id settles it


def test_a_merged_id_in_a_body_is_409_merged_with_the_survivor(v2, coll, world):
    loser = coll.local('set', 'Doubled', born_key='7001-1')
    assert write(v2, f'/items/{loser}/merge', body={'survivor': {'id': world.keep}}).status_code == 200
    refused = write(v2, '/copies', body={'item': {'id': loser}})
    assert refused.status_code == 409 and refused.json['code'] == 'merged' and refused.json['survivor'] == world.keep


def test_something_other_than_a_set_is_not_a_copy_and_a_set_is_not_stock(v2, world):
    assert write(v2, '/copies', body={'item': {'id': world.brick}}).status_code == 422
    assert write(v2, '/stock', body={'item': {'id': world.keep}, 'quantity': 1}).status_code == 422


def test_a_decision_skip_adds_nothing_when_the_set_is_owned_and_adds_when_it_is_new(v2, coll, world):
    skipped = write(v2, '/copies', body={'item': {'id': world.keep}, 'decision': 'skip'})
    assert skipped.status_code == 409 and len(call(v2, '/copies').json['data']) == 3
    added = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '2070-1'}, 'decision': 'skip'})
    assert added.status_code == 409                                                  # owned (copy C)
    fresh = write(v2, '/wishes', body={'item': {'id': coll.local('gear', 'Unowned gear', born_key='g-1')}, 'decision': 'skip'})
    validate(fresh, 'post_wishes', '201')                                            # neither owned nor wished: skip adds it


def test_loose_stock_is_created_in_the_providers_colour_and_identical_lines_merge(v2, world):
    made = write(v2, '/stock', body={'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 4, 'condition': 'used', 'storage_id': world.shelf,
                                     'lot_id': world.bag, 'note': 'More'})
    validate(made, 'post_stock', '201')
    assert made.json['data']['ids'] == [world.stock_brick]                          # the same item, colour, condition, lot and storage: one line
    line = call(v2, f'/stock/{world.stock_brick}').json['data']
    assert line['quantity'] == 7 and line['color']['bricklink_id'] == RED
    by_rebrickable = write(v2, '/stock', body={'item': {'provider': 'rebrickable', 'kind': 'part', 'key': '3001'}, 'color': 4, 'quantity': 1, 'condition': 'new'})
    assert by_rebrickable.json['data']['ids'] == [world.stock_brick_new]
    by_id = write(v2, '/stock', body={'item': {'id': world.plate}, 'color': world.red, 'quantity': 1, 'condition': 'damaged'})
    assert by_id.status_code == 201 and call(v2, f"/stock/{by_id.json['data']['ids'][0]}").json['data']['color']['id'] == world.red
    assert write(v2, '/stock', body={'item': {'kind': 'part', 'key': '3001'}, 'color': 9999, 'quantity': 1}).status_code == 422
    assert write(v2, '/stock', body={'item': {'kind': 'part', 'key': '3001'}, 'quantity': 1}).status_code == 422          # a part needs its colour
    assert write(v2, '/stock', body={'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 0}).status_code == 422


def test_a_wish_is_created_in_a_list_and_adds_to_the_live_row_on_another(v2, world):
    target = write(v2, '/wishlists', body={'name': 'New'}).json['data']['id']
    created = write(v2, '/wishes', body={'item': {'kind': 'set', 'key': '1000-1'}, 'list_id': target, 'condition': 'any', 'decision': 'another', 'note': 'Soon',
                                         'max_price': '50.00', 'max_price_currency': 'USD'})
    validate(created, 'post_wishes', '201')
    wish = call(v2, f"/wishes/{created.json['data']['ids'][0]}").json['data']
    assert (wish['list_id'], wish['condition'], wish['max_price'], wish['max_price_currency'], wish['note']) == (target, 'any', '50.00', 'USD', 'Soon')
    again = write(v2, '/wishes', body={'item': {'kind': 'set', 'key': '1000-1'}, 'list_id': target, 'quantity': 2, 'decision': 'another'})
    assert again.json['data']['ids'] == [wish['id']] and call(v2, f"/wishes/{wish['id']}").json['data']['quantity'] == 3
    assert write(v2, '/wishes', body={'item': {'kind': 'set', 'key': '1000-1'}, 'list_id': target}).status_code == 409
    assert write(v2, '/wishes', body={'item': {'kind': 'set', 'key': '1000-1'}, 'list_id': 'nowhere'}).status_code == 422
    coloured = write(v2, '/wishes', body={'item': {'kind': 'part', 'key': '3001'}, 'color': WHITE, 'quantity': 5, 'condition': 'new'})
    assert call(v2, f"/wishes/{coloured.json['data']['ids'][0]}").json['data']['color']['bricklink_id'] == WHITE


def test_a_wish_becomes_copies_or_stock_and_leaves_the_rest_wished(v2, world):
    coll_before = len(call(v2, '/copies').json['data'])
    whole = write(v2, f'/wishes/{world.wish_set}/to-owned', body={'condition': 'new', 'completeness': 'sealed'})
    validate(whole, 'post_wishes_by_id_to_owned')
    assert len(call(v2, '/copies').json['data']) == coll_before + 1
    assert call(v2, f'/wishes/{world.wish_set}').json['data']['archived_at']
    part = write(v2, f'/wishes/{world.wish_part}/to-owned', body={'quantity': 1})
    validate(part, 'post_wishes_by_id_to_owned')
    assert call(v2, f'/wishes/{world.wish_part}').json['data']['quantity'] == 1
    line = call(v2, f"/stock/{part.json['data']['ids'][0]}").json['data']
    assert (line['item']['id'], line['color']['id'], line['condition']) == (world.plate, world.white, 'new')
    assert write(v2, f'/wishes/{world.wish_part}/to-owned', body={'quantity': 5}).status_code == 409
    undone = write(v2, f"/events/{whole.json['event_id']}/undo")                    # one Undo takes the copy away and puts the wish back
    assert undone.status_code == 200 and call(v2, f'/wishes/{world.wish_set}').json['data']['archived_at'] is None
    assert len(call(v2, '/copies').json['data']) == coll_before


# ---------- editing ----------

def test_a_copy_edit_checks_the_etag_the_row_and_the_values(v2, world, pair):
    path = f'/copies/{world.copy_a}'
    tag = call(v2, path).headers['ETag']
    count = len(events(pair))
    assert write(v2, path, 'patch', {'note': 'x'}, headers={'If-Match': '"stale"'}).status_code == 412
    assert len(events(pair)) == count
    saved = write(v2, path, 'patch', {'note': 'Nine', 'purchase_price': '3.50'}, headers={'If-Match': tag})
    validate(saved, 'patch_copies_by_id')
    assert saved.json['data']['note'] == 'Nine' and saved.json['data']['purchase_price'] == '3.50' and saved.json['data']['purchase_currency']
    assert write(v2, path, 'delete', headers={'If-Match': tag}).status_code == 412          # the tag moved with the save
    assert write(v2, path, 'patch', {'note': 'y'}, headers={'If-Match': '*'}).status_code == 200
    assert write(v2, path, 'patch', {'storage_id': 'nowhere'}).status_code == 422
    assert write(v2, path, 'patch', {'condition': 'broken'}).status_code == 422
    assert write(v2, path, 'patch', {'purchase_price': '-1'}).status_code == 422
    assert write(v2, path, 'patch', {}).status_code == 422
    assert write(v2, '/copies/nope', 'patch', {'note': 'x'}).status_code == 404
    assert write(v2, path, 'patch', {'purchase_location_id': world.shop, 'completeness': 'complete'}).json['data']['completeness_source'] == 'manual'


def test_a_copy_is_archived_restored_and_an_archived_one_refuses_writes(v2, world):
    path = f'/copies/{world.copy_b}'
    archived = write(v2, path, 'delete')
    validate(archived, 'delete_copies_by_id')
    assert archived.json['data']['archived_at']
    for method, tail, body in (('patch', '', {'note': 'x'}), ('put', '/pin', {'pinned': True}), ('put', '/flags', {'flags': []}), ('delete', '', None)):
        refused = write(v2, path + tail, method, body)
        assert refused.status_code == 409 and refused.json['code'] == 'archived', tail
    restored = write(v2, path + '/restore')
    validate(restored, 'post_copies_by_id_restore')
    assert restored.json['data']['archived_at'] is None
    assert write(v2, path + '/restore').status_code == 409                                  # not archived any more
    assert write(v2, '/copies/nope/restore').status_code == 404
    assert write(v2, f"/events/{restored.json['event_id']}/undo").status_code == 200
    assert call(v2, path).json['data']['archived_at']


def test_flags_are_replaced_pinning_and_the_checked_flag_follow(v2, world):
    flagged = write(v2, f'/copies/{world.copy_b}/flags', 'put', {'flags': [world.tag]})
    validate(flagged, 'put_copies_by_id_flags')
    assert flagged.json['data']['flags'] == [world.tag]
    assert write(v2, f'/copies/{world.copy_b}/flags', 'put', {'flags': ['nope']}).status_code == 422
    pinned = write(v2, f'/copies/{world.copy_b}/pin', 'put', {'pinned': True})
    validate(pinned, 'put_copies_by_id_pin')
    assert pinned.json['data']['pinned'] is True
    checked = write(v2, f'/copies/{world.copy_c}/checked', 'put', {'checked': True})
    validate(checked, 'put_copies_by_id_checked')
    assert checked.json['data']['checked'] is True and world.checked in call(v2, f'/copies/{world.copy_c}').json['data']['flags']
    cleared = write(v2, f'/copies/{world.copy_c}/checked', 'put', {'checked': False})
    assert cleared.json['data']['checked'] is False and world.checked not in call(v2, f'/copies/{world.copy_c}').json['data']['flags']
    assert write(v2, f'/copies/{world.copy_c}/checked', 'put', {'checked': 'yes'}).status_code == 422


def test_clearing_checked_on_a_copy_that_never_had_it_still_leaves_one_undoable_event(v2, world, pair):
    flags = rows(pair, 'SELECT * FROM main.copy_flag ORDER BY copy_id, flag_id')
    cleared = write(v2, f'/copies/{world.copy_b}/checked', 'put', {'checked': False})
    validate(cleared, 'put_copies_by_id_checked')
    assert rows(pair, 'SELECT * FROM main.copy_flag ORDER BY copy_id, flag_id') == flags
    assert write(v2, f"/events/{cleared.json['event_id']}/undo").status_code == 200
    assert write(v2, f'/copies/{world.copy_b}/checked', 'put', {'checked': True}).status_code == 200


def test_a_stock_edit_may_merge_into_a_line_and_lists_the_lines_it_merged_into(v2, world, pair):
    line = world.stock_brick_new                                                           # 3001 red, new, no lot, not stored
    response = write(v2, f'/stock/{line}', 'patch', {'condition': 'used', 'storage_id': world.shelf, 'lot_id': world.bag})
    validate(response, 'patch_stock_by_id')
    assert response.json['data']['merged_ids'] == [world.stock_brick] and response.json['data']['archived_at']
    assert call(v2, f'/stock/{world.stock_brick}').json['data']['quantity'] == 5
    assert len([e for e in events(pair, "entity_kind='collection' AND field='save'")]) == 1       # one event for the edit and the merge
    assert write(v2, f"/events/{response.json['event_id']}/undo").status_code == 200
    assert call(v2, f'/stock/{world.stock_brick}').json['data']['quantity'] == 3 and call(v2, f'/stock/{line}').json['data']['archived_at'] is None


def test_stock_and_wishes_check_their_tags_and_states(v2, world):
    for path, restore in ((f'/stock/{world.stock_plate}', 'post_stock_by_id_restore'), (f'/wishes/{world.wish_part}', 'post_wishes_by_id_restore')):
        tag = call(v2, path).headers['ETag']
        assert write(v2, path, 'patch', {'note': 'x'}, headers={'If-Match': '"stale"'}).status_code == 412
        assert write(v2, path, 'patch', {'note': 'x'}, headers={'If-Match': tag}).status_code == 200
        assert write(v2, path, 'delete', headers={'If-Match': tag}).status_code == 412
        archived = write(v2, path, 'delete')
        assert archived.status_code == 200 and archived.json['data']['archived_at']
        assert write(v2, path, 'patch', {'note': 'x'}).json['code'] == 'archived'
        restored = write(v2, path + '/restore')
        validate(restored, restore)
        assert restored.json['data']['archived_at'] is None
        assert write(v2, path + '/restore').status_code == 409


def test_a_wish_edit_moves_colour_list_and_progress(v2, world):
    other = write(v2, '/wishlists', body={'name': 'Other'}).json['data']['id']
    moved = write(v2, f'/wishes/{world.wish_part}', 'patch', {'list_id': other, 'qty_filled_manual': 1, 'quantity': 2, 'color': world.red})
    validate(moved, 'patch_wishes_by_id')
    assert (moved.json['data']['list_id'], moved.json['data']['qty_filled'], moved.json['data']['qty_filled_source'], moved.json['data']['color']['id']) == (
        other, 1, 'manual', world.red)
    assert write(v2, f'/wishes/{world.wish_part}', 'patch', {'list_id': 'nowhere'}).status_code == 422
    assert write(v2, f'/wishes/{world.wish_set}', 'patch', {'color': world.red}).status_code == 422                 # a set has no colour
    assert write(v2, f'/wishes/{world.wish_part}', 'patch', {'qty_filled_manual': None, 'max_price': None}).json['data']['qty_filled_source'] == 'derived'


# ---------- wishlists ----------

def test_a_wishlist_is_created_renamed_moved_copied_archived_and_restored(v2, world):
    created = write(v2, '/wishlists', body={'name': 'Holiday', 'note': 'Winter'})
    validate(created, 'post_wishlists', '201')
    target = created.json['data']['id']
    assert write(v2, '/wishlists', body={'name': 'Holiday', 'note': 'Winter'}, key=created.request.headers['Idempotency-Key']).json['idempotent_replay'] is True
    renamed = write(v2, f'/wishlists/{target}', 'patch', {'name': 'Gifts'})
    validate(renamed, 'patch_wishlists_by_id')
    assert renamed.json['data']['name'] == 'Gifts' and renamed.json['data']['note'] == 'Winter'
    moved = write(v2, f'/wishlists/{target}/transfer', body={'ids': [world.wish_part]})
    validate(moved, 'post_wishlists_by_id_transfer')
    assert moved.json['data']['event_id'] == moved.json['event_id']
    assert call(v2, f'/wishes?list={target}').json['data'][0]['id'] == world.wish_part
    assert write(v2, f"/events/{moved.json['event_id']}/undo").status_code == 200
    assert call(v2, f'/wishes?list={target}').json['data'] == []
    copied = write(v2, f'/wishlists/{target}/transfer', body={'ids': [world.wish_part], 'copy': True})
    assert copied.status_code == 200 and len(call(v2, '/wishes').json['data']) == 3
    archived = write(v2, f'/wishlists/{target}', 'delete')
    validate(archived, 'delete_wishlists_by_id')
    assert archived.json['data']['archived_at'] and len(call(v2, '/wishlists').json['data']) == 1
    assert write(v2, f'/wishlists/{target}', 'patch', {'name': 'x'}).json['code'] == 'archived'
    restored = write(v2, f'/wishlists/{target}/restore')
    validate(restored, 'post_wishlists_by_id_restore')
    assert restored.json['data']['archived_at'] is None and restored.json['data']['count'] == 1
    assert write(v2, f'/wishlists/{target}/restore').status_code == 409
    assert write(v2, '/wishlists/nope/transfer', body={'ids': [world.wish_part]}).status_code == 404
    assert write(v2, f'/wishlists/{target}/transfer', body={'ids': ['nope']}).status_code == 422
    assert write(v2, f'/wishlists/{target}/transfer', body={'ids': [1]}).status_code == 422                       # wish ids are texts


# ---------- Take, Give, Found ----------

def test_take_moves_loose_stock_into_a_missing_part_and_one_undo_reverses_it(v2, world, pair):
    before = digest(pair)
    response = write(v2, f'/copies/{world.copy_a}/take', body={'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 1})
    validate(response, 'post_copies_by_id_take')
    assert response.json['data']['event_id'] == response.json['event_id']
    assert call(v2, f'/copies/{world.copy_a}').json['data']['missing'] == 0
    assert write(v2, f'/copies/{world.copy_a}/take', body={'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 1}).status_code == 422   # nothing missing now
    assert write(v2, f"/events/{response.json['event_id']}/undo").status_code == 200
    assert digest(pair) == before


def test_take_checks_what_it_takes(v2, world):
    take = lambda body: write(v2, f'/copies/{world.copy_a}/take', body=body)
    assert take({'item': {'kind': 'part', 'key': '3001'}, 'quantity': 1}).status_code == 422                          # a part needs its colour
    assert take({'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 9}).status_code == 422             # only 1 is missing
    assert take({'item': {'kind': 'part', 'key': '3023'}, 'color': WHITE, 'quantity': 1}).status_code == 422            # not missing from this copy
    assert take({'item': {'kind': 'part', 'key': '99999'}, 'color': RED, 'quantity': 1}).json['code'] == 'unidentified'
    assert write(v2, '/copies/nope/take', body={'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 1}).status_code == 404
    refused = take({'item': {'id': world.figure}, 'color': world.red, 'quantity': 1})
    assert refused.status_code == 422 and 'colour' in refused.json['detail']


def test_take_a_whole_minifigure_and_undo(v2, coll, world, pair):
    coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    before = digest(pair)
    taken = write(v2, f'/copies/{world.copy_a}/take', body={'item': {'id': world.figure}, 'quantity': 1})
    validate(taken, 'post_copies_by_id_take')
    assert row(pair, 'SELECT missing FROM main.copy_figure WHERE copy_id=?', (world.copy_a,))['missing'] == 0
    assert row(pair, 'SELECT quantity FROM main.stock WHERE id=?', (world.stock_figure,))['quantity'] == 0
    assert write(v2, f"/events/{taken.json['event_id']}/undo").status_code == 200
    assert digest(pair) == before


def test_give_checks_the_gap_and_the_stock(v2, world, pair):
    brick = part_of(pair, world.copy_a, '3001', '4')
    body = {'copy_id': world.copy_a, 'target': 'part', 'target_id': brick, 'quantity': 1}
    given = write(v2, f'/stock/{world.stock_brick}/give', body=body)
    validate(given, 'post_stock_by_id_give')
    assert call(v2, f'/copies/{world.copy_a}').json['data']['missing'] == 0
    stale = write(v2, f'/stock/{world.stock_brick}/give', body=body)
    assert stale.status_code == 409 and stale.json['code'] == 'stale_match'
    assert write(v2, '/stock/nope/give', body=body).status_code == 404
    assert write(v2, f'/stock/{world.stock_brick}/give', body=dict(body, target='nowhere')).status_code == 422


def test_found_lowers_gaps_or_adds_loose_stock(v2, world, pair):
    brick = part_of(pair, world.copy_a, '3001', '4')
    found = write(v2, '/found', body={'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'destination': 'set', 'quantity': 1, 'assignments': {str(brick): 1}})
    validate(found, 'post_found')
    assert call(v2, f'/copies/{world.copy_a}').json['data']['missing'] == 0
    loose = write(v2, '/found', body={'item': {'kind': 'part', 'key': '3023'}, 'color': WHITE, 'destination': 'loose', 'quantity': 2})
    validate(loose, 'post_found')
    assert call(v2, f'/stock/{world.stock_plate}').json['data']['quantity'] == 2 or any(s['quantity'] == 2 for s in call(v2, '/stock').json['data'])
    assert write(v2, '/found', body={'item': {'kind': 'part', 'key': '3023'}, 'color': WHITE, 'destination': 'list', 'quantity': 1}).status_code == 200
    assert write(v2, '/found', body={'item': {'kind': 'part', 'key': '3023'}, 'color': WHITE, 'destination': 'set', 'quantity': 1, 'assignments': {'999': 1}}).status_code == 409
    assert write(v2, '/found', body={'item': {'kind': 'part', 'key': '3023'}, 'color': None, 'destination': 'loose', 'quantity': 1}).status_code == 422


def test_booklets_are_added_from_lines_of_set_number_and_quantity(v2, world, pair):
    bad = write(v2, '/stock/booklets', body={'text': 'not a number!'})
    assert bad.status_code == 422
    unknown = write(v2, '/stock/booklets', body={'text': '55555-1'})
    assert unknown.status_code == 422 and 'unknown booklet' in unknown.json['detail']
    held = write(v2, '/stock/booklets', body={'text': '1000-1, 2', 'quantity': 1})
    validate(held, 'post_stock_booklets')
    assert row(pair, "SELECT quantity FROM main.stock WHERE item_id=? AND kind='instructions'", (world.local_booklet,))['quantity'] == 3


# ---------- the marks of a copy's lines ----------

def test_a_part_line_is_marked_missing_damaged_and_checked(v2, world, pair):
    brick = part_of(pair, world.copy_a, '3001', '4')
    plate = part_of(pair, world.copy_a, '3023', '15')
    marked = write(v2, f'/copies/{world.copy_a}/parts/{plate}', 'patch', {'missing': 1, 'damaged': 1, 'checked': True})
    validate(marked, 'patch_copies_by_id_parts_by_part_id')
    assert (marked.json['data']['missing'], marked.json['data']['damaged'], marked.json['data']['checked'], marked.json['data']['copy_id']) == (1, 1, True, world.copy_a)
    assert call(v2, f'/copies/{world.copy_a}').json['data']['missing'] == 2
    for body in ({'missing': -1}, {'missing': 5}, {'missing': True}, {}, {'checked': 'yes'}, {'missing': 1, 'extra': 1}):
        assert write(v2, f'/copies/{world.copy_a}/parts/{brick}', 'patch', body).status_code == 422, body
    assert write(v2, f'/copies/{world.copy_a}/parts/999999', 'patch', {'missing': 1}).status_code == 404
    assert write(v2, f'/copies/{world.copy_a}/parts/nope', 'patch', {'missing': 1}).status_code == 404
    assert write(v2, f'/copies/{world.copy_b}/parts/{brick}', 'patch', {'missing': 1}).status_code == 404            # the line is another copy's


def test_a_mark_is_undone_only_in_the_order_it_was_made(v2, world, pair):
    brick = part_of(pair, world.copy_a, '3001', '4')
    first = write(v2, f'/copies/{world.copy_a}/parts/{brick}', 'patch', {'missing': 0})
    second = write(v2, f'/copies/{world.copy_a}/parts/{brick}', 'patch', {'missing': 1})
    blocked = write(v2, f"/events/{first.json['event_id']}/undo")
    assert blocked.status_code == 409 and blocked.json['code'] == 'undo_blocked'
    assert write(v2, f"/events/{second.json['event_id']}/undo").status_code == 200
    assert write(v2, f"/events/{first.json['event_id']}/undo").status_code == 200
    assert row(pair, 'SELECT missing FROM main.copy_part WHERE id=?', (brick,))['missing'] == 1


def test_bulk_marks_set_or_add_by_item_and_colour_and_a_dry_run_changes_nothing(v2, world, pair):
    brick = part_of(pair, world.copy_a, '3001', '4')
    before, count = digest(pair), len(events(pair))
    body = {'items': [{'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'missing': 1}, {'item': {'kind': 'part', 'key': 'nothing'}, 'color': RED, 'missing': 1},
                      {'item': {'kind': 'part', 'key': '3023'}, 'color': RED, 'missing': 1}], 'mode': 'add', 'dry_run': True}
    preview = write(v2, f'/copies/{world.copy_a}/parts/bulk', body=body)
    validate(preview, 'post_copies_by_id_parts_bulk')
    assert preview.json['data']['applied'] == 1 and sorted(s['code'] for s in preview.json['data']['skipped']) == ['not_found', 'unidentified']
    assert preview.json['event_id'] is None and preview.json['undo_url'] is None and preview.json['data']['dry_run'] is True
    assert digest(pair) == before and len(events(pair)) == count                                      # a preview leaves nothing at all
    applied = write(v2, f'/copies/{world.copy_a}/parts/bulk', body=dict(body, dry_run=False))
    validate(applied, 'post_copies_by_id_parts_bulk')
    assert row(pair, 'SELECT missing FROM main.copy_part WHERE id=?', (brick,))['missing'] == 2 and applied.json['data']['event_id'] == applied.json['event_id']
    assert write(v2, f'/copies/{world.copy_a}/parts/bulk', body=dict(body, dry_run=False, mode='set')).status_code == 200
    assert row(pair, 'SELECT missing FROM main.copy_part WHERE id=?', (brick,))['missing'] == 1
    assert write(v2, f'/copies/{world.copy_a}/parts/bulk', body=dict(body, dry_run=False)).status_code == 200      # add 1 to 1
    over = write(v2, f'/copies/{world.copy_a}/parts/bulk', body={'items': [{'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'missing': 9}], 'mode': 'add'})
    assert over.status_code == 422
    assert write(v2, f'/copies/{world.copy_a}/parts/bulk', body={'items': []}).status_code == 422
    assert write(v2, f'/copies/{world.copy_a}/parts/bulk', body=body, key=False).status_code == 428


def test_a_whole_figure_is_marked_and_its_components_stay_on_the_figure(v2, coll, world, pair):
    figure = row(pair, 'SELECT item_id FROM main.copy_figure WHERE copy_id=?', (world.copy_a,))['item_id']
    marked = write(v2, f'/copies/{world.copy_a}/figures/{figure}', 'patch', {'missing': 1})
    validate(marked, 'patch_copies_by_id_figures_by_item_id')
    assert marked.json['data']['missing'] == 1 and marked.json['data']['item']['id'] == figure
    assert write(v2, f'/copies/{world.copy_a}/figures/{figure}', 'patch', {'missing': 9}).status_code == 422
    assert write(v2, f'/copies/{world.copy_a}/figures/{world.brick}', 'patch', {'missing': 0}).status_code == 404
    assert write(v2, f'/copies/{world.copy_a}/figures/nope', 'patch', {'missing': 0}).status_code == 404
    component = row(pair, 'SELECT p.id FROM main.copy_part p JOIN main.copy_figure f ON f.id=p.copy_figure_id WHERE p.copy_id=? LIMIT 1', (world.copy_a,))
    assert component is not None
    comp = write(v2, f'/copies/{world.copy_a}/parts/{component["id"]}', 'patch', {'missing': 1})
    assert comp.status_code == 200 and comp.json['data']['parent_minifig']['id'] == figure
    assert call(v2, f'/copies/{world.copy_a}/completeness').json['data']['missing_figures'] == 1


def test_the_loose_parts_of_a_minifigure_are_marked_by_item_and_colour(v2, world, pair):
    line = row(pair, 'SELECT * FROM main.stock_part WHERE stock_id=? AND is_spare=0 LIMIT 1', (world.stock_figure,))
    item = {'id': line['item_id']}
    marked = write(v2, f'/stock/{world.stock_figure}/parts', 'patch', {'parts': [{'item': item, 'color': line['color_id'] and row(pair, 'SELECT id FROM main.color WHERE id=?', (line['color_id'],))['id'],
                                                                           'spare': 0, 'missing': 1, 'checked': True}]})
    validate(marked, 'patch_stock_by_id_parts')
    assert [p for p in marked.json['data']['parts'] if p['missing'] == 1 and p['checked']]
    assert write(v2, f"/events/{marked.json['event_id']}/undo").status_code == 200
    assert row(pair, 'SELECT missing, checked FROM main.stock_part WHERE id=?', (line['id'],)) == {'missing': 0, 'checked': 0}
    for body in ({'parts': [{'item': item, 'color': line['color_id'], 'spare': 0, 'missing': line['quantity'] + 1}]},
                 {'parts': [{'item': item, 'color': line['color_id'], 'spare': 0}]},
                 {'parts': [{'item': {'id': world.plate}, 'color': 1, 'spare': 0, 'missing': 0}]}):
        assert write(v2, f'/stock/{world.stock_figure}/parts', 'patch', body).status_code in (404, 422)
    assert write(v2, f'/stock/{world.stock_brick}/parts', 'patch', {'parts': [{'item': item, 'color': 1, 'spare': 0, 'missing': 0}]}).status_code == 422


def test_the_part_check_answers_through_the_checker_with_its_receipt_and_undo(v2, world, pair):
    started = write(v2, f'/copies/{world.copy_c}/check', body={'action': 'start'}, key='chk-1')
    validate(started, 'post_copies_by_id_check')
    session = started.json['data']['session']['id']
    stepped = write(v2, f'/copies/{world.copy_c}/check', body={'action': 'next', 'session': session}, key='chk-2')
    validate(stepped, 'post_copies_by_id_check')
    newest = events(pair, 'id=?', (stepped.json['event_id'],))[0]
    assert newest['entity_kind'] == 'part_check' and stepped.json['undo_url'] == f"/api/v2/events/{newest['id']}/undo"
    assert (newest['via'], newest['actor']) == ('api', 'bootstrap')
    assert write(v2, f"/events/{stepped.json['event_id']}/undo").status_code == 200
    again = write(v2, f'/copies/{world.copy_c}/check', body={'action': 'start'}, key='chk-1')
    assert again.json['idempotent_replay'] is True and again.json['event_id'] == started.json['event_id']
    other = stored(v2, pair)
    same = write(v2, f'/copies/{world.copy_c}/check', body={'action': 'start'}, key='chk-1', token=other)           # another token, the same key: its own request
    assert same.status_code == 200 and same.json['idempotent_replay'] is False and same.json['event_id'] is None         # the check is running: nothing to start
    assert write(v2, f'/copies/{world.copy_c}/check', body={'action': 'dance'}).status_code == 422
    assert write(v2, f'/copies/{world.copy_c}/check', body={'action': 'next', 'session': 'stale'}).status_code == 422


def stored(v2, pair):
    from tests.api2 import stored_token
    return stored_token(pair, ['read', 'write'], 'other')


# ---------- what a creation leaves, and what undoing it does ----------

def test_a_created_copy_has_its_lines_and_its_import_is_queued_by_the_api(v2, world, pair):
    made = write(v2, '/copies', body={'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another'})
    copy = made.json['data']['ids'][0]
    assert len(call(v2, f'/copies/{copy}/parts').json['data']) == 2                                   # the set's lines came with the copy, as for the web
    queued = rows(pair, 'SELECT via, actor, state FROM main.job ORDER BY id DESC')
    assert queued and (queued[0]['via'], queued[0]['actor']) == ('api', 'bootstrap')                   # the import runs for the token that asked


def test_loose_stock_of_another_place_is_a_new_line_and_leaves_the_old_one_alone(v2, world):
    other = write(v2, '/stock', body={'item': {'kind': 'part', 'key': '3001'}, 'color': RED, 'quantity': 2, 'condition': 'used'})
    assert other.status_code == 201 and other.json['data']['ids'] != [world.stock_brick]
    assert call(v2, f'/stock/{world.stock_brick}').json['data']['quantity'] == 3                       # not stored, not in a lot: another line
    assert call(v2, f"/stock/{other.json['data']['ids'][0]}").json['data']['quantity'] == 2


@pytest.mark.parametrize('path,body', [
    ('/copies', {'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another'}),
    ('/stock', {'item': {'kind': 'part', 'key': '3023'}, 'color': WHITE, 'quantity': 4, 'condition': 'used'}),
    ('/wishes', {'item': {'kind': 'set', 'key': '1000-1'}, 'condition': 'any', 'decision': 'another'}),
])
def test_every_creation_is_undone_by_archiving_never_by_deleting(v2, world, pair, path, body):
    made = write(v2, path, body=body)
    assert made.status_code == 201, made.get_data(as_text=True)
    created = made.json['data']['ids']
    table = {'/copies': 'copy', '/stock': 'stock', '/wishes': 'wish'}[path]
    undone = write(v2, f"/events/{made.json['event_id']}/undo")
    assert undone.status_code == 200
    kept = rows(pair, f'SELECT * FROM main.{table} WHERE id IN ({",".join("?" * len(created))})', tuple(created))
    assert len(kept) == len(created)                                                                     # still there
    assert all(r['archived_at'] for r in kept)


def test_the_checker_steps_work_on_a_store_that_already_has_the_flag(v2, world):
    assert world.checked                                                                                # the fixture's "Set is checked" status flag
    started = write(v2, f'/copies/{world.copy_a}/check', body={'action': 'start'}, key='c-1')
    assert started.status_code == 200
    session = started.json['data']['session']['id']
    for n, action in enumerate(('next', 'back', 'next'), 2):
        step = write(v2, f'/copies/{world.copy_a}/check', body={'action': action, 'session': session}, key=f'c-{n}')
        validate(step, 'post_copies_by_id_check')


def test_taking_a_figure_again_when_nothing_is_left_is_refused_in_words(v2, coll, world, pair):
    coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    coll.mark_figure(world.copy_b, 'fig-000004', missing=1)
    assert write(v2, f'/copies/{world.copy_a}/take', body={'item': {'id': world.figure}, 'color': None, 'quantity': 1}).status_code == 200
    again = write(v2, f'/copies/{world.copy_b}/take', body={'item': {'id': world.figure}, 'quantity': 1})
    assert again.status_code == 422 and again.json['detail'] == 'Nothing is left in loose stock'
    part = write(v2, f'/copies/{world.copy_a}/take', body={'item': {'id': world.brick}, 'quantity': 1})
    assert part.status_code == 422 and 'colour' in part.json['detail']


# ---------- a figure's components count on the figure, not on the set ----------

def test_figure_components_stay_on_the_figure_and_the_checker_agrees(v2, coll, world, pair):
    coll.sql('UPDATE copy_part SET missing=0, damaged=0 WHERE copy_id=?', (world.copy_a,))
    coll.sql('UPDATE copy_figure SET missing=0 WHERE copy_id=?', (world.copy_a,))
    coll.sql("UPDATE copy SET completeness_source='derived' WHERE id=?", (world.copy_a,))
    component = row(pair, 'SELECT p.id, p.quantity FROM main.copy_part p WHERE p.copy_id=? AND p.copy_figure_id IS NOT NULL AND p.is_spare=0 LIMIT 1', (world.copy_a,))
    assert write(v2, f'/copies/{world.copy_a}/checked', 'put', {'checked': True}).json['data']['derived'] == 'complete'
    marked = write(v2, f'/copies/{world.copy_a}/parts/{component["id"]}', 'patch', {'missing': 1, 'checked': True})
    assert marked.status_code == 200
    assert call(v2, f'/copies/{world.copy_a}/completeness').json['data']['derived'] == 'complete'                     # the set's own lines are all there
    figures = call(v2, f'/copies/{world.copy_a}/figures').json['data']
    assert [f['parts_missing'] for f in figures if f['parts_missing']] == [1]
    assert write(v2, f'/copies/{world.copy_a}/parts/{component["id"]}', 'patch', {'missing': 0}).status_code == 200
    whole = row(pair, 'SELECT item_id FROM main.copy_figure WHERE copy_id=? LIMIT 1', (world.copy_a,))['item_id']
    assert write(v2, f'/copies/{world.copy_a}/figures/{whole}', 'patch', {'missing': 1}).status_code == 200
    assert call(v2, f'/copies/{world.copy_a}/completeness').json['data']['derived'] == 'incomplete'                   # a whole missing figure does count


def test_a_create_that_fails_on_a_later_field_adds_nothing(v2, world, pair):
    before, count = digest(pair), len(events(pair))
    for body in ({'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another', 'storage_id': 'nowhere'},
                 {'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another', 'purchase_currency': 'EUR'},        # a currency without a price
                 {'item': {'kind': 'set', 'key': '1000-2'}, 'decision': 'another', 'purchase_price': '-3'}):
        assert write(v2, '/copies', body=body).status_code == 422, body
    wish = write(v2, '/wishes', body={'item': {'kind': 'set', 'key': '1000-1'}, 'max_price_currency': 'USD', 'decision': 'another'})
    assert wish.status_code == 422 and 'price' in wish.json['detail']
    assert digest(pair) == before and len(events(pair)) == count
