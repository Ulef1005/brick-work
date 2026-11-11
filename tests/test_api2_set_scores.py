"""API v2: `GET /planning/set-scores` (#199), the scoring engine of `core/set_scoring.py` over loose stock, on the rich fixture catalogue."""
import pytest

from brickwork.core import set_scoring
from tests.api2 import call, stored_token, v2, validate  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401

PATH = '/planning/set-scores'


def data(response):
    validate(response, 'get_planning_set_scores')
    return response.json['data']


def test_a_lot_is_scored_against_the_catalogue(v2, coll, world):
    coll.tag('stock', world.stock_brick, coll.flag('sticker'))
    body = data(call(v2, PATH + f'?lot={world.bag}'))
    assert body['source'] == {'kind': 'lot', 'id': world.bag} and body['input']['lines'] == 1 and body['input']['quantity'] == 3
    ids = [r['item']['id'] for r in body['results']]
    assert set(ids) == {world.keep, world.gate} and body['total'] == 2
    keep = body['results'][ids.index(world.keep)]
    assert keep['covered_quantity'] == 3 and keep['covered_lines'] == 1 and keep['complete_lines'] == 0 and keep['set_quantity'] == 4 + 2 + 2 + 8
    gate = body['results'][ids.index(world.gate)]
    assert gate['complete_lines'] == 1                                  # 3001 red x2 is covered in full by 3
    assert [r['rank'] for r in body['results']] == [1, 2] and body['results'][0]['evidence'] >= body['results'][1]['evidence']
    line = gate['matched'][0]
    assert line['item']['id'] == world.brick and line['color']['id'] == world.red and (line['quantity'], line['need'], line['covered']) == (3, 2, 2)
    assert line['flags'] == ['sticker'] and gate['flags']['sticker']['lines'] == 1
    assert body['catalogue']['sets'] >= 3


def test_loose_stock_a_storage_and_a_selection_are_scored_too(v2, coll, world):
    loose = data(call(v2, PATH + '?loose=true'))
    assert loose['source'] == {'kind': 'loose', 'id': None} and loose['input']['quantity'] == 3 + 2 + 2 + 1 + 5
    assert loose['input']['unmatched_lines'] == 1 and loose['input']['unmatched'][0]['item']['id'] == world.local_part           # the BrickLink-born part
    shelf = data(call(v2, PATH + f'?storage={world.shelf}'))
    assert shelf['source']['kind'] == 'storage' and shelf['input']['quantity'] == 3
    picked = data(call(v2, PATH + f'?stock={world.stock_plate}&stock={world.stock_figure}'))
    assert picked['source'] == {'kind': 'stock', 'id': None} and picked['input']['lines'] == 2
    figure = next(r for r in picked['results'] if r['item']['id'] == world.keep)
    assert any(m['color'] is None and m['item']['id'] == world.figure for m in figure['matched'])               # the whole figure


def test_paging_and_detail(v2, coll, world):
    first = data(call(v2, PATH + '?loose=true&limit=1&detail=0'))
    assert len(first['results']) == 1 and first['limit'] == 1 and first['results'][0]['matched'] == [] and first['total'] >= 2
    second = data(call(v2, PATH + '?loose=true&limit=1&offset=1&detail=0'))
    assert second['results'][0]['rank'] == 2 and second['results'][0]['item']['id'] != first['results'][0]['item']['id']
    assert data(call(v2, PATH + f'?lot={world.bag}&offset=5'))['results'] == []


def test_a_swap_is_listed_apart(v2, coll, world):
    # the pile has 3023 in red; set 1000-1 holds 3023 in white: a colour swap, not a match
    coll.add_stock('part', world.plate, colour=world.red, quantity=2, condition='used', lot=world.bag)
    body = data(call(v2, PATH + f'?lot={world.bag}'))
    keep = next(r for r in body['results'] if r['item']['id'] == world.keep)
    swap = next(s for s in keep['swaps']['items'] if s['kind'] == 'colour')
    assert swap['have']['color']['id'] == world.red and swap['wanted']['color']['id'] == world.white and swap['quantity'] == 2
    assert keep['covered_lines'] == 1 and keep['swaps']['lines'] >= 1


@pytest.mark.parametrize('query, status, code', [
    ('', 422, 'validation_failed'), ('?lot=a&loose=true', 422, 'validation_failed'), ('?loose=maybe', 422, 'validation_failed'),
    ('?lot=none', 404, 'not_found'), ('?storage=none', 404, 'not_found'), ('?stock=nope', 422, 'validation_failed'),
    ('?loose=true&limit=0', 422, 'validation_failed'), ('?loose=true&limit=101', 422, 'validation_failed'), ('?loose=true&offset=-1', 422, 'validation_failed'),
    ('?loose=true&limit=x', 422, 'validation_failed'), ('?loose=true&detail=51', 422, 'validation_failed'), ('?loose=true&bogus=1', 400, 'unknown_filter'),
    ('?lot=a&lot=b', 400, 'bad_request')])
def test_refusals(v2, world, query, status, code):
    answer = call(v2, PATH + query)
    assert answer.status_code == status and answer.json['code'] == code


def test_a_duplicate_selection_is_refused(v2, world):
    answer = call(v2, PATH + f'?stock={world.stock_plate}&stock={world.stock_plate}')
    assert answer.status_code == 422


def test_a_read_token_may_call_it_and_no_token_may_not(v2, pair, world):
    assert call(v2, PATH + '?loose=true', token=stored_token(pair, ['read'])).status_code == 200
    assert call(v2, PATH + '?loose=true', token=None).status_code == 401


def test_it_writes_nothing(v2, world, pair):
    from tests.api2 import events
    before = len(events(pair))
    assert call(v2, PATH + '?loose=true').status_code == 200
    assert len(events(pair)) == before


def test_the_answer_is_cached_per_build_and_input(v2, world):
    call(v2, PATH + '?loose=true')
    assert set_scoring._RESULTS
