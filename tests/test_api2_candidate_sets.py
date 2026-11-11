"""API v2: `GET /lots/{id}/candidate-sets` (#200, Lot Detective) on the invented sets of `test_candidate_sets`, and the setting that goes with it."""
import sqlite3
from contextlib import closing

import pytest

from tests.api2 import call, stored_token, v2, validate, write, events  # noqa: F401
from tests.app4 import app4  # noqa: F401
from tests.test_candidate_sets import RED, coll, db, lot, pair  # noqa: F401 — the fixtures of the service tests

PATH = '/lots/{}/candidate-sets'


def data(response):
    validate(response, 'get_lots_by_id_candidate_sets')
    return response.json['data']


def test_a_lot_of_two_sets_ranks_both_first(v2, lot):
    body = data(call(v2, PATH.format(lot.id)))
    names = [r['item']['name'] for r in body['results']]
    assert names[:3] == ['Det Set A', 'Det Set B', 'Det Decoy'] and body['lot'] == lot.id and body['common_max'] == 300
    first = body['results'][0]
    assert (first['rank'], first['score']) == (1, 100) and first['reasons'][0] == '4 of 5 distinctive parts found'
    printed = next(p for p in first['distinctive_found_parts'] if p['printed'])
    assert printed['item']['id'] == lot.part('a5pr0001') and printed['only_in_set'] and printed['color']['id'] and printed['quantity'] == 1
    assert 'picture' in printed and 'picture' in first
    missing = first['distinctive_missing_parts']
    assert [p['item']['id'] for p in missing] == [lot.part('a4')] and missing[0]['quantity'] == 0
    assert body['total'] >= 3 and body['input']['ignored_common_lines'] == 0


def test_a_local_picture_is_named(v2, coll, lot):
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,width,height,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/x.png',4,3,'2026-10-26T12:00:00.000Z')",
             (lot.part('a2'),))
    first = data(call(v2, PATH.format(lot.id)))['results'][0]
    picture = next(p for p in first['distinctive_found_parts'] if p['item']['id'] == lot.part('a2'))['picture']
    assert picture['id'] and picture['content_url'] == f"/api/v2/images/{picture['id']}/content"


def test_filters_and_paging(v2, lot):
    names = lambda q: [r['item']['name'] for r in data(call(v2, PATH.format(lot.id) + q))['results']]           # noqa: E731
    assert names('?theme=Pirates') == ['Det Set A', 'Det Decoy']
    assert names('?theme=602') == ['Det Set B']
    assert names('?year_from=2001&year_to=2005') == ['Det Set A', 'Det Set B']
    assert names('?parts_min=100&parts_max=200') == ['Det Set A']
    assert names('?min_score=100') == ['Det Set A']
    paged = data(call(v2, PATH.format(lot.id) + '?limit=1&offset=1'))
    assert [r['rank'] for r in paged['results']] == [2] and paged['limit'] == 1 and paged['offset'] == 1 and paged['total'] >= 3


def test_ignore_common_is_on_by_default_and_the_setting_changes_it(v2, lot, pair):
    body = data(call(v2, PATH.format(lot.id) + '?limit=100'))
    assert body['total'] == 35 and body['input']['ignored_common_lines'] == 0
    assert write(v2, '/settings', 'patch', {'candidate_sets_common_max': 25}).json['data']['candidate_sets_common_max'] == 25
    cut = data(call(v2, PATH.format(lot.id) + '?limit=100'))
    assert cut['total'] == 3 and cut['common_max'] == 25 and cut['input']['ignored_common_lines'] == 1
    everyone = data(call(v2, PATH.format(lot.id) + '?limit=100&ignore_common=false'))
    assert everyone['total'] == 35 and everyone['common_max'] is None
    assert call(v2, '/settings').json['data']['candidate_sets_common_max'] == 25
    assert any((e['entity_kind'], e['field']) == ('settings', 'candidate_sets') for e in events(pair))


@pytest.mark.parametrize('body', [{'candidate_sets_common_max': 24}, {'candidate_sets_common_max': 'many'}, {'candidate_sets_common_max': True}])
def test_a_bad_setting_is_refused(v2, body):
    assert write(v2, '/settings', 'patch', body).status_code == 422


@pytest.mark.parametrize('query, status, code', [
    ('?theme=Nothing', 422, 'validation_failed'), ('?min_score=101', 422, 'validation_failed'), ('?min_score=x', 422, 'validation_failed'),
    ('?year_from=x', 422, 'validation_failed'), ('?year_from=2005&year_to=2001', 422, 'validation_failed'),
    ('?parts_min=9&parts_max=1', 422, 'validation_failed'), ('?limit=0', 422, 'validation_failed'), ('?limit=101', 422, 'validation_failed'),
    ('?offset=-1', 422, 'validation_failed'), ('?ignore_common=maybe', 400, 'unknown_filter'), ('?bogus=1', 400, 'unknown_filter'),
    ('?theme=a&theme=b', 400, 'bad_request')])
def test_refusals(v2, lot, query, status, code):
    answer = call(v2, PATH.format(lot.id) + query)
    assert answer.status_code == status and answer.json['code'] == code


def test_an_unknown_lot_is_not_found(v2, lot):
    for unknown in ('nope', 'x' * 100):
        answer = call(v2, PATH.format(unknown))
        assert answer.status_code == 404 and answer.json['code'] == 'not_found'


def test_a_read_token_may_call_it_it_writes_nothing_and_no_token_may_not(v2, lot, pair):
    token = stored_token(pair, ['read'])
    before = len(events(pair))
    assert call(v2, PATH.format(lot.id), token=token).status_code == 200
    assert len(events(pair)) == before and call(v2, PATH.format(lot.id), token=None).status_code == 401


def test_an_oversized_theme_number_is_unknown_not_a_server_error(v2, lot):
    response = call(v2, PATH.format(lot.id) + '?theme=9223372036854775808')
    assert response.status_code == 422


def test_a_catalogue_part_picture_comes_from_the_colour_picture_list(v2, lot, tmp_path):
    part = lot.part('a2')
    colour = next(p for p in data(call(v2, PATH.format(lot.id)))['results'][0]['distinctive_found_parts'] if p['item']['id'] == part)['color']['id']
    with closing(sqlite3.connect(tmp_path / 'catalogue.db')) as other:        # the catalogue is attached read-only: write it from another connection
        other.execute("INSERT INTO picture_url(item_id,color_id,url) VALUES(?,?,'https://img.invalid/a2.png')", (part, colour))
        other.commit()
    first = data(call(v2, PATH.format(lot.id)))['results'][0]
    picture = next(p for p in first['distinctive_found_parts'] if p['item']['id'] == part)['picture']
    assert picture['image_url'] == 'https://img.invalid/a2.png'
