"""API v2: the pull list of a set for a lot, the found counts and Make it a copy (#202), on the shared world.

Set `1000-1` (3001 red x4, 3023 white x2, two `fig-000004`, a spare). The lot `Bag` holds 3001 red x3 used (in Shelf A); 3023 white x2 and a figure are loose, in no lot,
and 3001 red x2 new is loose too."""
from contextlib import closing

import pytest

from brickwork.core.connect import connect
from tests.api2 import call, events, row, rows, stored_token, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import table_digest

RED, WHITE = 5, 1                                           # BrickLink colour numbers of the fixture's red and white


def path(world, lot=None, tail='', set_id=None):
    return f'/lots/{lot or world.bag}/pull-list/{set_id or world.keep}{tail}'


def listed(v2, world, query='', **kwargs):
    response = call(v2, path(world, **kwargs) + query)
    validate(response, 'get_lots_by_id_pull_list_by_set_id')
    return response.json['data']


def found(v2, world, item, colour, count, **kwargs):
    return write(v2, path(world, tail='/found'), body={'item': {'kind': 'part', 'key': item}, 'color': colour, 'found': count}, **kwargs)


def digest(pair):
    with closing(connect(pair)) as db:
        return table_digest(db, skip=('event', 'event_undo', 'api_token'))


def test_the_list_has_every_line_with_need_held_and_found_in_category_order(v2, world):
    body = listed(v2, world)
    assert body['lot'] == {'id': world.bag, 'name': 'Bag'} and body['set']['id'] == world.keep and body['nested'] is False and body['refusal'] is None
    assert [(r['item']['rebrickable']['key'], r['kind'], r['category'], r['need'], r['held'], r['found'], r['to_find']) for r in body['lines']] == [
        ('3001', 'part', 'Bricks', 4, 3, 3, 1), ('3023', 'part', 'Plates', 2, 0, 0, 2), ('fig-000004', 'figure', 'Minifigures', 2, 0, 0, 2)]
    assert body['lines'][0]['color']['id'] == world.red and body['lines'][2]['color'] is None
    assert body['totals'] == dict(need=8, held=3, found=3, to_find=5, lines=3, lines_to_find=3, figures_need=2, figures_found=0, lot_pieces=3,
                                  moves=dict(moves=3, missing=5, stays=0))
    assert (body['show'], body['total'], body['limit'], body['offset']) == ('all', 3, 100, 0)


def test_show_and_paging_keep_the_totals_of_the_whole_list(v2, world):
    found(v2, world, '3001', RED, 4)
    assert [r['item']['rebrickable']['key'] for r in listed(v2, world, '?show=find')['lines']] == ['3023', 'fig-000004']
    done = listed(v2, world, '?show=found')
    assert [r['item']['rebrickable']['key'] for r in done['lines']] == ['3001'] and done['totals']['found'] == 4 and done['total'] == 1
    paged = listed(v2, world, '?limit=1&offset=1')
    assert [r['item']['rebrickable']['key'] for r in paged['lines']] == ['3023'] and paged['total'] == 3 and paged['totals']['lines'] == 3


@pytest.mark.parametrize('query, status', [('?show=maybe', 422), ('?limit=0', 422), ('?limit=501', 422), ('?offset=-1', 422), ('?bogus=1', 400)])
def test_read_refusals(v2, world, query, status):
    assert call(v2, path(world) + query).status_code == status


def test_unknown_things_are_404(v2, world):
    assert call(v2, path(world, lot='absent')).status_code == 404
    assert call(v2, path(world, lot='x' * 70)).status_code == 404
    assert call(v2, path(world, set_id=987654321)).status_code == 404
    assert call(v2, path(world, set_id=world.brick)).status_code == 404                    # a part is no set
    assert call(v2, path(world, set_id='x')).status_code == 404


def test_a_read_token_may_read_it_and_nothing_is_written(v2, pair, world):
    token = stored_token(pair, ['read'])
    before = digest(pair)
    assert call(v2, path(world), token=token).status_code == 200 and call(v2, path(world), token=None).status_code == 401
    assert digest(pair) == before


# ---------- the found counts ----------

def test_a_found_count_is_kept_idempotent_and_not_an_event(v2, world, pair):
    before = len(events(pair, "entity_kind!='bw_api'"))                                     # the idempotency records are not collection events
    done = found(v2, world, '3023', WHITE, 2, key='found-1')
    validate(done, 'post_lots_by_id_pull_list_by_set_id_found')
    assert done.json['event_id'] is None and done.json['undo_url'] is None
    assert (done.json['data']['line']['found'], done.json['data']['totals']['found']) == (2, 5)
    again = found(v2, world, '3023', WHITE, 2, key='found-1')
    assert again.json == dict(done.json, idempotent_replay=True)
    other = found(v2, world, '3023', WHITE, 2)                                          # a second save of the same count changes nothing
    assert other.json['data'] == done.json['data']
    assert len(events(pair, "entity_kind!='bw_api'")) == before and listed(v2, world)['totals']['found'] == 5
    assert found(v2, world, '3023', WHITE, 0).json['data']['line']['found'] == 0 and listed(v2, world)['totals']['found'] == 3


def test_found_refusals_write_nothing(v2, world, pair):
    before = digest(pair)
    token = stored_token(pair, ['read'])
    assert found(v2, world, '3023', WHITE, 3).status_code == 422                        # above the need
    assert found(v2, world, '3023', WHITE, -1).status_code == 422
    assert found(v2, world, '3001', WHITE, 1).status_code == 422                        # a colour the set does not have: not on the list
    assert found(v2, world, '3004', RED, 1).status_code in (404, 422)                   # a part that is no line (or not in the catalogue)
    assert write(v2, path(world, tail='/found'), body={'item': {'kind': 'part', 'key': '3023'}, 'found': True}).status_code == 422
    assert write(v2, path(world, tail='/found'), body={'found': 1}).status_code == 422
    assert write(v2, path(world, tail='/found'), body={'item': {'kind': 'part', 'key': '3023'}, 'color': WHITE, 'found': 1, 'extra': 1}).status_code == 422
    assert write(v2, path(world, lot='absent', tail='/found'), body={'item': {'kind': 'part', 'key': '3023'}, 'color': WHITE, 'found': 1}).status_code == 404
    assert found(v2, world, '3023', WHITE, 1, token=token).status_code == 403
    assert digest(pair) == before


def test_a_read_only_instance_refuses_the_found_count_and_make_copy(v2, world, app4):
    app4.config['BW_READ_ONLY'] = True
    assert found(v2, world, '3023', WHITE, 1).json['code'] == 'read_only_instance'
    refused = write(v2, path(world, tail='/make-copy'))
    assert refused.status_code == 403 and refused.json['code'] == 'read_only_instance'


# ---------- Make it a copy ----------

def make(v2, world, **kwargs):
    return write(v2, path(world, tail='/make-copy'), **kwargs)


def test_make_it_a_copy_is_one_event_that_moves_the_found_counts_and_undo_restores(v2, world, pair):
    found(v2, world, '3001', RED, 4)
    found(v2, world, '3023', WHITE, 1)
    before = digest(pair)
    copies = len(rows(pair, 'SELECT id FROM main.copy'))
    stays_other = row(pair, 'SELECT quantity FROM main.stock WHERE id=?', (world.stock_brick_new,))['quantity']
    done = make(v2, world, key='copy-1')
    validate(done, 'post_lots_by_id_pull_list_by_set_id_make_copy')
    data = done.json['data']
    assert (data['pieces'], data['figures'], data['missing_parts'], data['missing_figures'], data['completeness'], data['stays']) == (5, 0, 1, 2, 'incomplete', 0)
    assert data['set']['id'] == world.keep and done.json['undo_url'] == f"/api/v2/events/{done.json['event_id']}/undo"
    event = events(pair, 'id=?', (done.json['event_id'],))[0]
    assert (event['entity_kind'], event['field'], event['via'], event['actor']) == ('copy', 'make_from_stock', 'api', 'bootstrap')
    assert len(rows(pair, "SELECT id FROM main.event WHERE field='make_from_stock'")) == 1 and len(rows(pair, 'SELECT id FROM main.copy')) == copies + 1
    assert row(pair, 'SELECT quantity FROM main.stock WHERE id=?', (world.stock_brick,))['quantity'] == 0
    assert row(pair, 'SELECT quantity FROM main.stock WHERE id=?', (world.stock_brick_new,))['quantity'] == stays_other                 # loose, not in the lot: untouched
    assert row(pair, 'SELECT quantity FROM main.stock WHERE id=?', (world.stock_plate,))['quantity'] == 2
    after = listed(v2, world)
    assert (after['totals']['found'], after['totals']['lot_pieces']) == (0, 0)                                                      # the lot has nothing of the set left
    again = make(v2, world, key='copy-1')
    assert again.json == dict(done.json, idempotent_replay=True) and len(rows(pair, 'SELECT id FROM main.copy')) == copies + 1
    undone = write(v2, f"/events/{done.json['event_id']}/undo")
    assert undone.status_code == 200
    assert row(pair, 'SELECT archived_at FROM main.copy WHERE id=?', (data['copy_id'],))['archived_at'] is not None
    state = listed(v2, world)
    assert state['totals']['found'] == 5 and state['totals']['held'] == 5                          # the 4 red and the 1 white are filed in the lot now
    assert digest(pair) != before                                                                  # the ticked pieces stay in the lot


def test_make_it_a_copy_refusals_write_nothing(v2, world, pair):
    token = stored_token(pair, ['read'])
    before = digest(pair)
    nothing = make(v2, world)                                                                      # nothing ticked and... the lot holds 3 of the set: allowed
    assert nothing.status_code == 200
    again = make(v2, world)                                                                        # now nothing is left in the lot
    assert again.status_code == 422 and 'Nothing found yet' in again.json['detail']
    assert make(v2, world, key=False).status_code == 428
    assert make(v2, world, token=token).status_code == 403
    assert write(v2, path(world, lot='absent', tail='/make-copy')).status_code == 404
    assert write(v2, path(world, set_id=world.brick, tail='/make-copy')).status_code == 404
    assert before != digest(pair)
    assert len(rows(pair, "SELECT id FROM main.event WHERE field='make_from_stock'")) == 1
