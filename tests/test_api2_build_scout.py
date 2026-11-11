"""API v2 Build Scout (#9): `GET /planning/build-scout` and `POST /items/{id}/build`, on the rich fixture catalogue and the shared world.

Set `1000-1` (3001 red x4, 3023 white x2, two `fig-000004`, a spare) and `1000-2` (3001 red x2, 3023 white x1). The world's loose stock: 3001 red x3 used (lot Bag, in
Shelf A) and x2 new, 3023 white x2 new, one figure, and a BrickLink-born part that no set holds."""
import pytest

from tests.api2 import call, events, row, rows, stored_token, v2, validate, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import table_digest
from contextlib import closing
from brickwork.core.connect import connect

PATH = '/planning/build-scout'


def data(response):
    validate(response, 'get_planning_build_scout')
    return response.json['data']


def keep_row(body, world):
    return next(r for r in body['results'] if r['item']['id'] == world.keep)


def test_every_set_the_stock_makes_is_ranked_with_its_numbers(v2, world):
    body = data(call(v2, PATH))
    assert body['source'] == {'lots': [], 'storages': [], 'loose': False, 'damaged': False, 'text': 'All loose stock'}
    assert body['input'] == {'lines': 4, 'pieces': 12, 'figures': 1} and body['filters']['min_percent'] == 60
    keep, gate = keep_row(body, world), next(r for r in body['results'] if r['item']['id'] == world.gate)
    assert (keep['parts_available'], keep['parts_total'], keep['percent'], keep['missing_parts'], keep['missing_lines']) == (6, 6, 100.0, 0, 0)
    assert (keep['figures_available'], keep['figures_required'], keep['missing_figures'], keep['nested']) == (1, 2, 1, False)
    assert (gate['parts_available'], gate['parts_total'], gate['percent']) == (3, 3, 100.0)
    assert [r['rank'] for r in body['results']] == [1, 2] and body['total'] == 2 and body['catalogue']['sets'] >= 3
    assert 'gaps' not in keep and keep['theme'] == 'Castle' and keep['year'] == 1990


def test_detail_adds_gaps_figures_cost_and_swaps(v2, coll, world):
    coll.add_stock('part', world.plate, colour=world.red, quantity=2, condition='used')               # 3023 red: a swap for the white ones
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-11-01T00:00:00Z', world.stock_plate))   # no white 3023 left
    body = data(call(v2, PATH + '?min_percent=0&detail=5'))
    keep = keep_row(body, world)
    assert (keep['parts_available'], keep['missing_parts'], keep['missing_lines']) == (4, 2, 1)
    assert [(g['item']['id'], g['color']['id'], g['need'], g['have'], g['missing']) for g in keep['gaps']] == [(world.plate, world.white, 2, 0, 2)]
    assert [(g['item']['id'], g['color'], g['missing']) for g in keep['figure_gaps']] == [(world.figure, None, 1)]
    assert keep['cost'] == {'amount': '2.00', 'currency': 'EUR', 'priced_lines': 1, 'unpriced_lines': 1}       # the figure is priced at 2.00, 3023 white is not
    swap = keep['swaps']['items'][0]
    assert swap['kind'] == 'colour' and swap['quantity'] == 2 and swap['have']['color']['id'] == world.red and swap['wanted']['color']['id'] == world.white


def test_the_sources_and_the_filters(v2, coll, world):
    lot = data(call(v2, PATH + f'?lot={world.bag}&min_percent=0'))
    assert lot['source']['lots'] == [world.bag] and lot['source']['text'] == '1 lot' and lot['input']['pieces'] == 3
    assert keep_row(lot, world)['parts_available'] == 3 and [r['item']['id'] for r in data(call(v2, PATH + f'?lot={world.bag}'))['results']] == [world.gate]      # 3 of 6 is 50 %, 2 of 3 is 67 %
    shelf = data(call(v2, PATH + f'?storage={world.shelf}&min_percent=0'))
    assert shelf['source']['storages'] == [world.shelf] and shelf['input']['pieces'] == 3
    assert data(call(v2, PATH + '?loose=true&min_percent=0'))['input']['pieces'] == 9                  # the stock kept in no lot or storage
    assert [r['item']['id'] for r in data(call(v2, PATH + '?theme=castle&year_from=1991'))['results']] == [world.gate]
    assert [r['item']['id'] for r in data(call(v2, PATH + '?size_from=4'))['results']] == [world.keep]
    assert data(call(v2, PATH + '?max_missing=0&limit=1'))['limit'] == 1
    coll.add_stock('part', world.brick, colour=world.red, quantity=4, condition='damaged')
    assert data(call(v2, PATH + '?damaged=true'))['input']['pieces'] == 16
    assert data(call(v2, PATH))['input']['pieces'] == 12


def test_paging(v2, world):
    first = data(call(v2, PATH + '?limit=1'))
    second = data(call(v2, PATH + '?limit=1&offset=1'))
    assert (first['results'][0]['rank'], second['results'][0]['rank']) == (1, 2) and first['results'][0]['item']['id'] != second['results'][0]['item']['id']
    assert data(call(v2, PATH + '?offset=5'))['results'] == []


@pytest.mark.parametrize('query, status, code', [
    ('?limit=0', 422, 'validation_failed'), ('?limit=101', 422, 'validation_failed'), ('?offset=-1', 422, 'validation_failed'), ('?detail=51', 422, 'validation_failed'),
    ('?min_percent=101', 422, 'validation_failed'), ('?min_percent=x', 422, 'validation_failed'), ('?theme=nothing', 422, 'validation_failed'),
    ('?max_missing=-1', 422, 'validation_failed'), ('?lot=none', 404, 'not_found'), ('?storage=none', 404, 'not_found'), ('?bogus=1', 400, 'unknown_filter'),
    ('?loose=maybe', 400, 'unknown_filter'), ('?min_percent=1&min_percent=2', 400, 'bad_request')])
def test_refusals(v2, world, query, status, code):
    answer = call(v2, PATH + query)
    assert answer.status_code == status and answer.json['code'] == code


def test_a_read_token_may_read_and_it_writes_nothing(v2, pair, world):
    token = stored_token(pair, ['read'])
    before = len(events(pair))
    assert call(v2, PATH, token=token).status_code == 200
    assert call(v2, PATH, token=None).status_code == 401
    assert len(events(pair)) == before


# ---------- Build it ----------

def digest(pair):
    with closing(connect(pair)) as db:
        return table_digest(db, skip=('event', 'event_undo', 'item_merge', 'stock_transfer', 'copy', 'copy_part', 'copy_figure', 'api_token'))


def build(v2, item, body=None, **kwargs):
    return write(v2, f'/items/{item}/build', body=body, **kwargs)


def test_build_it_makes_a_copy_moves_the_stock_and_undo_puts_it_back(v2, world, pair):
    before, copies_before = digest(pair), rows(pair, 'SELECT id FROM main.copy')
    done = build(v2, world.keep, {})
    validate(done, 'post_items_by_id_build')
    body = done.json['data']
    assert (body['pieces'], body['figures'], body['missing_parts'], body['missing_figures'], body['completeness']) == (6, 1, 0, 1, 'incomplete')
    assert body['item']['id'] == world.keep and done.json['undo_url'] == f"/api/v2/events/{done.json['event_id']}/undo"
    copy = row(pair, 'SELECT * FROM main.copy WHERE id=?', (body['copy_id'],))
    assert (copy['item_id'], copy['archived_at'], copy['completeness']) == (world.keep, None, 'incomplete') and len(rows(pair, 'SELECT id FROM main.copy')) == len(copies_before) + 1
    assert row(pair, 'SELECT quantity FROM main.stock WHERE id=?', (world.stock_brick,))['quantity'] == 0
    assert row(pair, 'SELECT quantity FROM main.stock WHERE id=?', (world.stock_brick_new,))['quantity'] == 1
    assert row(pair, 'SELECT quantity FROM main.stock WHERE id=?', (world.stock_figure,))['quantity'] == 0
    event = events(pair, 'id=?', (done.json['event_id'],))[0]
    assert (event['entity_kind'], event['field'], event['via'], event['actor']) == ('copy', 'make_from_stock', 'api', 'bootstrap')
    now = data(call(v2, PATH + '?min_percent=0'))
    assert all(r['item']['id'] != world.keep or r['parts_available'] < 6 for r in now['results'])        # the parts are in the copy now
    undone = write(v2, f"/events/{done.json['event_id']}/undo")
    assert undone.status_code == 200 and digest(pair) == before
    assert row(pair, 'SELECT archived_at FROM main.copy WHERE id=?', (body['copy_id'],))['archived_at'] is not None
    assert keep_row(data(call(v2, PATH)), world)['parts_available'] == 6


def test_build_it_with_sources_and_a_replay(v2, world, pair):
    done = build(v2, world.keep, {'lots': [world.bag]}, key='same-key')
    assert done.status_code == 200 and (done.json['data']['pieces'], done.json['data']['missing_parts']) == (3, 3)
    again = build(v2, world.keep, {'lots': [world.bag]}, key='same-key')
    assert again.status_code == 200 and again.json['idempotent_replay'] is True and again.json['data']['copy_id'] == done.json['data']['copy_id']
    assert len(rows(pair, "SELECT id FROM main.event WHERE field='make_from_stock'")) == 1


def test_build_it_refusals(v2, world, pair):
    token = stored_token(pair, ['read'])
    before = digest(pair)
    assert build(v2, world.brick, {}).status_code == 422                                  # a part, not a set
    assert build(v2, world.keep, {'lots': ['none']}).status_code == 404
    assert build(v2, 987654321, {}).status_code == 404
    assert build(v2, world.keep, {'extra': 1}).status_code == 422
    assert build(v2, world.keep, {}, key=False).status_code == 428
    assert build(v2, world.duplo, {}).status_code == 422                                  # no stock holds anything the set needs
    assert build(v2, world.keep, {}, token=token).status_code == 403
    assert digest(pair) == before and not rows(pair, "SELECT id FROM main.event WHERE field='make_from_stock'")


def test_a_read_only_instance_refuses_build_it(v2, world, app4):
    app4.config['BW_READ_ONLY'] = True
    refused = build(v2, world.keep, {})
    assert refused.status_code == 403 and refused.json['code'] == 'read_only_instance'
