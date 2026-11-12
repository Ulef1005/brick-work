"""API v2: the sticker candidates of a part line and "This one" / "Not a sticker" (#201), on the invented sets of `tests/stickers_world.py`."""
from tests.api2 import call, events, validate, v2, write  # noqa: F401
from tests.app4 import app4  # noqa: F401
from tests.stickers_world import World, coll, db, pair, world  # noqa: F401 — the fixtures

LIST = '/lots/{}/stock/{}/stickers'
ONE = '/lots/{}/stock/{}/sticker'


def listed(v2, world, query=''):
    response = call(v2, LIST.format(world.lot, world.line) + query)
    validate(response, 'get_lots_by_id_stock_by_stock_id_stickers')
    return response.json['data']


def confirm(v2, world, number='9401-1', sheet='sheet-a', **kwargs):
    return write(v2, ONE.format(world.lot, world.line), body={'set_item_id': world.set(number), 'sheet_item_id': world.sheet(sheet)}, **kwargs)


def test_the_candidates_are_the_sets_with_the_part_and_a_sheet_and_the_state_is_shown(v2, world):
    body = listed(v2, world)
    assert [r['set']['name'] for r in body['results']] == ['Stk Set 9401', 'Stk Set 9408', 'Stk Set 9402', 'Stk Set 9451', 'Stk Set 9452', 'Stk Set 9453'] and body['total'] == 6
    assert body['item']['id'] == world.tile and body['color']['id'] == world.red and body['quantity'] == 2 and body['sticker'] == {'flagged': False, 'confirmed': None}
    first = body['results'][0]
    assert first['sheet']['id'] == world.sheet('sheet-a') and first['year'] == 2001 and first['picture']['image_url'] == 'https://img.invalid/sheet-a.jpg'
    assert body['results'][2]['picture'] is None
    paged = listed(v2, world, '?limit=1&offset=2')
    assert [r['set']['name'] for r in paged['results']] == ['Stk Set 9402'] and paged['limit'] == 1 and paged['offset'] == 2


def test_a_line_that_is_not_a_live_part_of_the_lot_is_404_and_a_bad_page_is_422(v2, world, coll):
    other = coll.lot('Elsewhere')
    assert call(v2, LIST.format(other, world.line)).status_code == 404
    assert call(v2, LIST.format(world.lot, 'absent')).status_code == 404
    assert call(v2, LIST.format('x' * 70, world.line)).status_code == 404
    assert call(v2, LIST.format(world.lot, world.line) + '?limit=0').status_code == 422


def test_confirm_is_one_undoable_event_and_replays(v2, world, pair):
    world.flag()
    done = confirm(v2, world, key='sticker-1')
    validate(done, 'post_lots_by_id_stock_by_stock_id_sticker')
    body = done.json
    assert body['data']['changed'] is True and body['data']['sticker']['confirmed']['set_number'] == '9401-1' and body['undo_url'].endswith(f"/events/{body['event_id']}/undo")
    again = confirm(v2, world, key='sticker-1')
    assert again.json == dict(body, idempotent_replay=True)
    other_key = confirm(v2, world)                                                  # already chosen: nothing to write, the answer names the earlier event
    assert other_key.json['data']['changed'] is False and other_key.json['event_id'] == body['event_id']
    assert len(events(pair, "entity_kind='stock_sticker'")) == 1
    assert listed(v2, world)['sticker']['confirmed']['set_item_id'] == world.set('9401-1')
    undone = write(v2, f"/events/{body['event_id']}/undo")
    assert undone.status_code == 200
    assert listed(v2, world)['sticker'] == {'flagged': True, 'confirmed': None}


def test_confirm_refuses_a_part_without_the_flag_and_a_pair_that_is_no_candidate_and_a_bad_body(v2, world, pair):
    assert confirm(v2, world).status_code == 409
    world.flag()
    assert confirm(v2, world, number='9403-1').status_code == 422
    assert confirm(v2, world, sheet='sheet-b').status_code == 422
    assert write(v2, ONE.format(world.lot, world.line), body={'set_item_id': 'x'}).status_code == 422
    assert write(v2, ONE.format(world.lot, world.line), body={'set_item_id': 1, 'sheet_item_id': 2, 'extra': 1}).status_code == 422
    assert write(v2, ONE.format(world.lot, 'absent'), body={'set_item_id': 1, 'sheet_item_id': 2}).status_code == 404
    assert events(pair, "entity_kind='stock_sticker'") == []


def test_not_a_sticker_removes_the_flag_and_the_choice_and_undo_brings_them_back(v2, world, pair):
    world.flag()
    confirm(v2, world)
    done = write(v2, ONE.format(world.lot, world.line), 'delete')
    validate(done, 'delete_lots_by_id_stock_by_stock_id_sticker')
    assert done.json['data'] == {'changed': True, 'sticker': {'flagged': False, 'confirmed': None}}
    nothing = write(v2, ONE.format(world.lot, world.line), 'delete')
    assert nothing.json['data']['changed'] is False and nothing.json['event_id'] is None
    write(v2, f"/events/{done.json['event_id']}/undo")
    assert listed(v2, world)['sticker']['confirmed']['set_number'] == '9401-1'


def test_the_candidate_sets_of_the_lot_carry_the_sticker_reason_and_the_swaps(v2, world, coll):
    world.flag()
    confirm(v2, world, number='9402-1', sheet='sheet-b')
    response = call(v2, f'/lots/{world.lot}/candidate-sets?ignore_common=false&min_score=0&limit=100')
    validate(response, 'get_lots_by_id_candidate_sets')
    first = response.json['data']['results'][0]
    assert first['item']['name'] == 'Stk Set 9402' and first['reasons'][0] == 'sticker of set 9402-1 confirmed' and first['score'] == 100
    assert first['swaps'] == {'lines': 0, 'quantity': 0, 'items': []}


def test_a_part_in_another_colour_is_a_swap_and_never_counted(v2, coll):
    lot = coll.lot('Swap lot')
    coll.add_stock('part', coll.item('parts', 'stk-tile'), colour=coll.colour('4'), quantity=4, condition='used', lot=lot)      # an exact match, so the set is a candidate
    coll.add_stock('part', coll.item('parts', 'stk-bar'), colour=coll.colour('4'), quantity=2, condition='used', lot=lot)       # set 9401 holds the bar in the "no colour"
    base = call(v2, f'/lots/{lot}/candidate-sets?ignore_common=false&min_score=0&limit=100')
    first = next(r for r in base.json['data']['results'] if r['item']['name'] == 'Stk Set 9401')
    swap = first['swaps']
    assert swap['lines'] == 1 and swap['quantity'] == 2 and swap['items'][0]['kind'] == 'colour'
    assert swap['items'][0]['have']['color']['id'] != swap['items'][0]['wanted']['color']['id'] and swap['items'][0]['have']['item']['id'] == swap['items'][0]['wanted']['item']['id']
    validate(base, 'get_lots_by_id_candidate_sets')
    assert first['covered_lines'] == 1, 'the swap is not a covered line'
