"""API v2 item addressing (M.11a, issue #113, decisions 2 to 5): by id, by each number path, lookup, both providers, colour-scoped links,
ambiguous, unknown, unidentified and merged ids. Invented data on the 4.0 fixtures."""
from contextlib import closing

from flask import Flask
import pytest

from brickwork.api import transport
from brickwork.api2 import items
from brickwork.core import errors
from brickwork.core.connect import connect
from brickwork.store4 import merge
from tests.api2 import PREFIX, call, v2  # noqa: F401
from tests.api2 import app4, coll, pair  # noqa: F401


def data(response):
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json['data']


# --- by id
def test_a_catalogue_item_by_id_has_the_design_7_body(v2, coll):
    set_id = coll.item('sets', '2070-1')
    body = data(call(v2, f'/items/{set_id}'))
    assert body == {'id': set_id, 'kind': 'set', 'name': 'Ring Me Rabbit', 'unidentified': False,
                    'bricklink': [{'type': 'S', 'no': '2070-1', 'color_id': None, 'color_scoped': False, 'brickwork_color_id': None, 'preferred': True}], 'rebrickable': {'key': '2070-1'}}
    # reading an item does not project it, and projecting it changes nothing the client sees
    assert coll.db.execute('SELECT 1 FROM main.item WHERE id=?', (set_id,)).fetchone() is None
    coll.project(set_id)
    assert data(call(v2, f'/items/{set_id}')) == body


def test_a_figure_lists_its_bricklink_number_and_a_part_none_preferred(v2, coll):
    figure = data(call(v2, f"/items/{coll.item('minifigs', 'fig-000004')}"))
    assert figure['kind'] == 'minifigure' and figure['bricklink'] == [{'type': 'M', 'no': 'syn-fig-0004', 'color_id': None, 'color_scoped': False, 'brickwork_color_id': None, 'preferred': True}]
    assert data(call(v2, f"/items/{coll.item('parts', '3001')}"))['bricklink'] == [{'type': 'P', 'no': '3001', 'color_id': None, 'color_scoped': False, 'brickwork_color_id': None, 'preferred': False}]


def test_the_leg_rule_shows_as_colour_scoped_links_with_bricklink_colour_ids(v2, coll):
    legs = data(call(v2, f"/items/{coll.item('parts', '970c03')}"))
    assert {(l['no'], l['color_id']) for l in legs['bricklink']} == {('970c00', 11), ('970c11', None)}      # black is BrickLink 11


def test_an_unidentified_item_says_so(v2, coll):
    mystery = coll.local('gear', 'Mystery thing')
    body = data(call(v2, f'/items/{mystery}'))
    assert body == {'id': mystery, 'kind': 'gear', 'name': 'Mystery thing', 'unidentified': True, 'bricklink': [], 'rebrickable': None}
    assert mystery >= 1_000_000_000


def test_a_bricklink_only_item_lists_its_born_number(v2, coll):
    local = coll.local('part', 'Only on BrickLink', born_key='x999')
    body = data(call(v2, f'/items/{local}'))
    assert body['unidentified'] is True and body['rebrickable'] is None
    assert body['bricklink'] == [{'type': 'P', 'no': 'x999', 'color_id': None, 'color_scoped': False, 'brickwork_color_id': None, 'preferred': True}]


def test_an_unknown_id_is_404(v2):
    for bad in ('999999999', '12345'):
        response = call(v2, '/items/' + bad)
        assert response.status_code == 404 and response.json['code'] == 'not_found' and response.mimetype == 'application/problem+json'


# --- by number
def test_a_set_number_is_the_same_at_both_providers(v2, coll):
    set_id = coll.item('sets', '2070-1')
    for provider in ('', '?provider=bricklink', '?provider=rebrickable'):
        assert data(call(v2, '/sets/by-number/2070-1' + provider))['id'] == set_id
    assert data(call(v2, '/lookup?kind=set&key=2070-1'))['id'] == set_id
    # the number path and the id path answer the same body
    assert data(call(v2, '/sets/by-number/2070-1')) == data(call(v2, f'/items/{set_id}'))


def test_a_part_number_is_bricklinks_by_default(v2, coll):
    brick = coll.item('parts', '3001')
    assert data(call(v2, '/parts/by-number/3001'))['id'] == brick
    assert data(call(v2, '/parts/by-number/3001?provider=rebrickable'))['id'] == brick
    assert data(call(v2, '/lookup?provider=bricklink&kind=part&key=3001'))['id'] == brick
    assert data(call(v2, '/lookup?provider=rebrickable&kind=part&key=3001'))['id'] == brick


def test_the_two_providers_number_a_figure_differently(v2, coll):
    figure = coll.item('minifigs', 'fig-000004')
    assert data(call(v2, '/minifigures/by-number/syn-fig-0004'))['id'] == figure
    assert call(v2, '/minifigures/by-number/fig-000004').status_code == 404            # a Rebrickable number is not a BrickLink one
    assert data(call(v2, '/minifigures/by-number/fig-000004?provider=rebrickable'))['id'] == figure
    assert data(call(v2, '/lookup?provider=rebrickable&kind=minifigure&key=fig-000004'))['id'] == figure


def test_a_bricklink_only_number_finds_the_local_item(v2, coll):
    local = coll.local('part', 'Only on BrickLink', born_key='x999')
    found = data(call(v2, '/parts/by-number/x999'))
    assert found['id'] == local and found['unidentified'] is True
    assert call(v2, '/parts/by-number/x999?provider=rebrickable').status_code == 404


def test_an_unknown_number_is_404(v2):
    for path in ('/sets/by-number/9999-9', '/parts/by-number/nope', '/lookup?kind=part&key=nope', '/lookup?provider=rebrickable&kind=part&key=nope'):
        response = call(v2, path)
        assert response.status_code == 404 and response.json['code'] == 'not_found', path


def test_colour_scoped_links_decide_by_the_colour(v2, coll):
    plate, white = coll.item('parts', '3023'), coll.colour('15')
    coll.link(plate, '3023-scoped', kind='P', colour=white)                              # holds for white only
    coll.link(plate, '3023-open', kind='P')                                              # holds for every colour
    # BrickLink colour 1 is white, 11 is black
    assert data(call(v2, '/parts/by-number/3023-scoped'))['id'] == plate                  # no colour: a link of any scope
    scoped = data(call(v2, '/parts/by-number/3023-scoped?color=1'))
    assert scoped['id'] == plate and scoped['color'] == {'id': white, 'name': 'White', 'rgb': 'FFFFFF', 'bricklink_id': 1, 'rebrickable_id': 15}
    assert call(v2, '/parts/by-number/3023-scoped?color=11').status_code == 404           # scoped to white, asked in black
    assert data(call(v2, '/parts/by-number/3023-open?color=11'))['id'] == plate           # unscoped holds for black
    assert 'color' not in data(call(v2, '/parts/by-number/3023-open'))
    # the Rebrickable colour space: 15 is white there
    assert data(call(v2, '/lookup?provider=rebrickable&kind=part&key=3023&color=15'))['color']['id'] == white


def test_the_leg_rule_resolves_per_colour(v2, coll):
    black_legs, red_legs = coll.item('parts', '970c03'), coll.item('parts', '970c22')
    # BrickLink 970c00 is legs in one colour: Rebrickable has a part per hip colour behind it (black 970c03, red 970c22)
    ambiguous = call(v2, '/parts/by-number/970c00')
    assert ambiguous.status_code == 409 and [c['id'] for c in ambiguous.json['candidates']] == sorted([black_legs, red_legs])
    assert data(call(v2, '/parts/by-number/970c00?color=11'))['id'] == black_legs            # BrickLink 11 is black
    assert data(call(v2, '/parts/by-number/970c00?color=5'))['id'] == red_legs               # BrickLink 5 is red
    assert data(call(v2, '/parts/by-number/970c00?color=5'))['color']['rebrickable_id'] == 4
    # 970c11 is the unscoped row of the black ones: it holds for every colour but black, where the scoped row overrides it
    assert data(call(v2, '/parts/by-number/970c11?color=5'))['id'] == black_legs
    assert call(v2, '/parts/by-number/970c11?color=11').status_code == 404


def test_a_number_that_names_several_items_is_409_ambiguous_with_candidates(v2, coll):
    one, two = coll.item('parts', '3001'), coll.item('parts', '3023')
    coll.link(one, 'twin', kind='P')
    coll.link(two, 'twin', kind='P')
    response = call(v2, '/parts/by-number/twin')
    assert response.status_code == 409 and response.json['code'] == 'ambiguous'
    assert response.mimetype == 'application/problem+json'
    assert [c['id'] for c in response.json['candidates']] == sorted([one, two])
    assert all({'id', 'kind', 'name', 'unidentified', 'bricklink', 'rebrickable'} <= set(c) for c in response.json['candidates'])
    assert call(v2, '/lookup?kind=part&key=twin').status_code == 409
    # addressing one of them by id settles it
    assert data(call(v2, f'/items/{one}'))['id'] == one


def test_a_manual_link_decides_alone_when_a_colour_is_given(v2, coll):
    one, two = coll.item('parts', '3001'), coll.item('parts', '3023')
    coll.link(one, 'both', kind='P', status='matched')
    coll.link(two, 'both', kind='P', status='manual')
    assert data(call(v2, '/parts/by-number/both?color=5'))['id'] == two                  # candidate_items: the manual link decides alone


def test_a_to_check_link_does_not_address_an_item(v2, coll):
    coll.link(coll.item('parts', '3001'), 'maybe', kind='P', status='to_check')
    assert call(v2, '/parts/by-number/maybe').status_code == 404


def test_bad_addressing_arguments_are_422_or_400(v2):
    for path in ('/lookup', '/lookup?kind=part', '/lookup?key=3001', '/lookup?kind=widget&key=1', '/lookup?provider=lego&kind=part&key=1',
                 '/lookup?provider=rebrickable&kind=gear&key=1', '/lookup?kind=part&key=3001&color=zebra', '/lookup?kind=part&key=3001&color=999999',
                 '/parts/by-number/3001?provider=brickwork', '/lookup?provider=brickwork&kind=part&key=1'):
        response = call(v2, path)
        assert response.status_code == 422 and response.json['code'] == 'validation_failed', path
    for path in ('/lookup?kind=part&key=3001&nope=1', '/parts/by-number/3001?type=P'):
        assert call(v2, path).status_code == 400 and call(v2, path).json['code'] == 'unknown_filter', path


# --- merged ids (decision 5, amended: 307 on GET, 409 merged on writes)
@pytest.fixture
def merged(coll):
    loser = coll.local('part', 'Only on BrickLink', born_key='x999')
    survivor = coll.item('parts', '3001')
    coll.project(survivor)
    merge.merge(coll.db, loser, survivor, via='cli')
    coll.db.commit()
    return loser, survivor


def test_a_merged_id_is_a_307_to_the_survivor_that_is_never_cached(v2, merged):
    loser, survivor = merged
    response = call(v2, f'/items/{loser}')
    assert response.status_code == 307
    assert response.headers['Location'] == f'{PREFIX}/items/{survivor}'
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.mimetype == 'application/problem+json'
    assert response.json['code'] == 'moved' and response.json['survivor'] == survivor
    followed = v2.get(response.headers['Location'], headers={'Authorization': 'Bearer synthetic-bootstrap'})
    assert followed.status_code == 200 and followed.json['data']['id'] == survivor


def test_the_redirect_keeps_the_rest_of_the_path_and_the_query(v2, merged):
    loser, survivor = merged
    response = call(v2, f'/items/{loser}?x=1&y=2')
    assert response.status_code == 307 and response.headers['Location'] == f'{PREFIX}/items/{survivor}?x=1&y=2'


def test_a_number_that_was_merged_away_finds_the_survivor(v2, merged):
    loser, survivor = merged
    found = data(call(v2, '/parts/by-number/x999'))
    assert found['id'] == survivor


def test_unmerge_makes_the_id_answer_for_itself_again(v2, coll, merged):
    loser, survivor = merged
    assert call(v2, f'/items/{loser}').status_code == 307
    merge_id = coll.db.execute('SELECT id FROM item_merge WHERE merged_id=?', (loser,)).fetchone()[0]
    merge.unmerge(coll.db, merge_id, via='cli')
    coll.db.commit()
    again = call(v2, f'/items/{loser}')
    assert again.status_code == 200 and again.json['data']['id'] == loser


def test_a_write_naming_a_merged_id_is_409_merged_naming_the_survivor(app4, coll, merged):
    loser, survivor = merged
    with app4.test_request_context(f'{PREFIX}/items/{loser}/links', method='PUT'):
        with closing(connect(coll.db.execute('PRAGMA database_list').fetchone()[2])) as db:
            with pytest.raises(errors.Merged) as raised:
                items.for_write(db, str(loser))
            assert items.for_write(db, str(survivor)) == survivor
        response = transport.problem(raised.value)
    assert response.status_code == 409 and response.json['code'] == 'merged' and response.json['survivor'] == survivor
    assert response.mimetype == 'application/problem+json'


# --- review round 1 (Codex findings, each written as a failing test first)
def test_a_born_number_does_not_outvote_a_manual_link_given_a_colour(v2, coll):
    born = coll.local('part', 'Born at x', born_key='bornx')
    other = coll.item('parts', '3001')
    coll.link(other, 'bornx', kind='P', colour=coll.colour('15'), status='manual')            # manual, scoped to white
    found = call(v2, '/parts/by-number/bornx?color=1')                                       # BrickLink 1 is white
    assert found.status_code == 200 and found.json['data']['id'] == other
    assert call(v2, '/parts/by-number/bornx').status_code == 409                              # without a colour both still match
    assert born != other


def test_a_born_number_does_not_apply_in_a_colour_its_item_has_a_scoped_link_for(v2, coll):
    born = coll.local('part', 'Born at y', born_key='borny')
    coll.link(born, 'borny-white', kind='P', colour=coll.colour('15'))                         # the leg rule: scoped row overrides the unscoped one
    assert call(v2, '/parts/by-number/borny?color=1').status_code == 404                       # white: the born number is overridden
    assert data(call(v2, '/parts/by-number/borny?color=11'))['id'] == born                     # black: it holds
    assert data(call(v2, '/parts/by-number/borny'))['id'] == born                              # no colour: it holds


def test_a_link_scoped_to_a_colour_without_a_bricklink_id_never_reads_as_unscoped(v2, coll):
    unknown = coll.colour('-1')                                                               # [Unknown]: no BrickLink colour
    plate = coll.item('parts', '3023')
    coll.link(plate, 'scoped-nobl', kind='P', colour=unknown)
    coll.link(plate, 'open', kind='P')
    links = {l['no']: l for l in data(call(v2, f'/items/{plate}'))['bricklink']}
    assert links['scoped-nobl']['color_id'] is None and links['scoped-nobl']['color_scoped'] is True
    assert links['scoped-nobl']['brickwork_color_id'] == unknown
    assert links['open']['color_scoped'] is False and links['open']['brickwork_color_id'] is None
    white = coll.colour('15')
    coll.link(plate, 'scoped-white', kind='P', colour=white)
    entry = {l['no']: l for l in data(call(v2, f'/items/{plate}'))['bricklink']}['scoped-white']
    assert (entry['color_id'], entry['color_scoped'], entry['brickwork_color_id']) == (1, True, white)


def test_resolution_and_body_are_one_snapshot(v2, coll, pair, monkeypatch):
    from brickwork.store4 import lookup
    loser = coll.local('part', 'Moving', born_key='mv1')
    coll.link(loser, 'mv-link', kind='P')
    survivor = coll.item('parts', '3001')
    coll.project(survivor)
    real = lookup.live_id

    def live_then_merge(db, item_id):
        result = real(db, item_id)
        with closing(connect(pair)) as other:                                                 # a merge commits between the two reads
            merge.merge(other, loser, survivor, via='cli')
            other.commit()
        return result
    monkeypatch.setattr(lookup, 'live_id', live_then_merge)
    body = data(call(v2, f'/items/{loser}'))
    assert body['id'] == loser and 'mv-link' in [l['no'] for l in body['bricklink']]          # the state live_id saw, links included


def test_ids_are_canonical_integers(v2, coll):
    local = coll.local('part', 'Big id', born_key='big1')
    assert call(v2, f'/items/{local}').status_code == 200
    for bad in (f'0{local}', f'00{local}', '007', '+7', ' 7'):
        assert call(v2, '/items/' + bad).status_code == 404, bad
