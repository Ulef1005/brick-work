"""The reads under API v2 item addressing (M.11a, issue #113): item and colour bodies, merged ids and provider-number lookup."""
import pytest

from brickwork.store4 import lookup, merge
from tests.app4 import coll, pair  # noqa: F401


def test_item_body_of_a_catalogue_item_and_of_the_same_item_projected(coll):
    item = coll.item('parts', '970c03')
    body = lookup.item_body(coll.db, item)
    assert {(l['no'], l['color_id']) for l in body['bricklink']} == {('970c00', 11), ('970c11', None)}      # the leg rule: scoped to black (BrickLink 11)
    assert body['rebrickable'] == {'key': '970c03'} and body['unidentified'] is False and body['kind'] == 'part'
    coll.project(item)
    assert lookup.item_body(coll.db, item) == body
    assert lookup.item_body(coll.db, 123456789) is None


def test_unidentified_means_local_and_not_born_at_rebrickable(coll):
    assert lookup.item_body(coll.db, coll.local('gear', 'No number'))['unidentified'] is True
    assert lookup.item_body(coll.db, coll.local('part', 'BrickLink only', born_key='q1'))['unidentified'] is True
    assert lookup.item_body(coll.db, coll.item('parts', '3001'))['unidentified'] is False
    coll.project(coll.item('parts', '3001'))
    assert lookup.item_body(coll.db, coll.item('parts', '3001'))['unidentified'] is False    # projected is still a catalogue item


def test_a_preferred_link_comes_first_and_only_confirmed_links_are_listed(coll):
    brick = coll.item('parts', '3001')
    coll.link(brick, 'z-pick', kind='P', status='manual', preferred=1)
    coll.link(brick, 'candidate', kind='P', status='to_check')
    listed = lookup.item_body(coll.db, brick)['bricklink']
    assert [l['no'] for l in listed][0] == 'z-pick' and listed[0]['preferred'] is True
    assert 'candidate' not in [l['no'] for l in listed]


def test_color_body_for_catalogue_fixed_and_local_colours(coll):
    assert lookup.color_body(coll.db, coll.colour('4')) == {'id': coll.colour('4'), 'name': 'Red', 'rgb': 'C91A09', 'bricklink_id': 5, 'rebrickable_id': 4}
    assert lookup.color_body(coll.db, 1)['rebrickable_id'] == 9999 and lookup.color_body(coll.db, 1)['bricklink_id'] == 0
    assert lookup.color_body(coll.db, 2)['bricklink_id'] is None
    assert lookup.color_body(coll.db, 987654321) is None
    from brickwork.store4 import fetched
    local = fetched.create_local_color(coll.db, bricklink_key=9999991, name='Synthetic Teal')
    coll.db.commit()
    body = lookup.color_body(coll.db, local)
    assert body['bricklink_id'] == 9999991 and body['rebrickable_id'] is None and body['name'] == 'Synthetic Teal' and local >= 1_000_000_000


def test_live_id_follows_merges_and_reports_unknown(coll):
    loser = coll.local('part', 'Only on BrickLink', born_key='x999')
    survivor = coll.item('parts', '3001')
    coll.project(survivor)
    assert lookup.live_id(coll.db, loser) == (loser, False)
    merge.merge(coll.db, loser, survivor, via='cli')
    coll.db.commit()
    assert lookup.live_id(coll.db, loser) == (survivor, True)
    assert lookup.live_id(coll.db, survivor) == (survivor, False)
    assert lookup.live_id(coll.db, 424242) is None


def test_find_items_by_provider_kind_and_key(coll):
    set_id, brick = coll.item('sets', '2070-1'), coll.item('parts', '3001')
    assert lookup.find_items(coll.db, 'bricklink', 'set', '2070-1') == [set_id]
    assert lookup.find_items(coll.db, 'rebrickable', 'set', '2070-1') == [set_id]
    assert lookup.find_items(coll.db, 'bricklink', 'part', '3001') == [brick]
    assert lookup.find_items(coll.db, 'bricklink', 'part', '2070-1') == []              # the kind decides which BrickLink type is meant
    assert lookup.find_items(coll.db, 'bricklink', 'gear', '3001') == []


def test_find_items_validates_its_arguments(coll):
    with pytest.raises(ValueError):
        lookup.find_items(coll.db, 'bricklink', 'widget', '1')
    with pytest.raises(ValueError):
        lookup.find_items(coll.db, 'lego', 'part', '1')
    with pytest.raises(ValueError):
        lookup.find_items(coll.db, 'rebrickable', 'gear', '1')


def test_brickwork_color_reads_each_provider_space(coll):
    white = coll.colour('15')
    assert lookup.brickwork_color(coll.db, 'bricklink', 1) == white
    assert lookup.brickwork_color(coll.db, 'rebrickable', '15') == white
    assert lookup.brickwork_color(coll.db, 'brickwork', white) == white
    for provider, color in (('bricklink', 9999), ('rebrickable', 99999), ('brickwork', 99999999), ('bricklink', 'x'), ('lego', 1)):
        with pytest.raises(ValueError):
            lookup.brickwork_color(coll.db, provider, color)


def test_the_bodies_of_many_equal_the_body_of_each(coll):
    """M.11b: a page of a list builds its bodies in a fixed number of queries; the answer is the one a single read gives."""
    legs, mystery = coll.item('parts', '970c03'), coll.local('gear', 'No number')
    local = coll.local('part', 'BrickLink only', born_key='q9')
    coll.link(coll.item('parts', '3001'), 'x-3001', kind='P', colour=coll.colour('15'))
    wanted = [coll.item('sets', '1000-1'), coll.item('parts', '3001'), legs, mystery, local, 987654321]
    many = lookup.item_bodies(coll.db, wanted)
    assert set(many) == set(wanted) - {987654321}
    assert all(many[i] == lookup.item_body(coll.db, i) for i in many)
    colours = [coll.colour(k) for k in ('4', '15', '0')] + [1, 2, 987654321, None]
    bodies = lookup.color_bodies(coll.db, colours)
    assert set(bodies) == {c for c in colours if c not in (987654321, None)}
    assert all(bodies[i] == lookup.color_body(coll.db, i) for i in bodies)
    assert lookup.bricklink_colors(coll.db, colours) == {i: bodies[i]['bricklink_id'] for i in bodies} | {987654321: None}
    assert lookup.item_bodies(coll.db, []) == {} and lookup.color_bodies(coll.db, []) == {}


def test_a_page_of_bodies_costs_the_same_however_many_items(coll):
    sets, parts = coll.item('sets', '1000-1'), [coll.item('parts', k) for k in ('3001', '3023', '970c03', '970c22')]
    colours = [coll.colour(k) for k in ('4', '15', '0', '6')]
    queries = []
    coll.db.set_trace_callback(queries.append)
    lookup.item_bodies(coll.db, parts[:1])
    one = len(queries)
    queries.clear()
    lookup.item_bodies(coll.db, [sets, *parts])
    assert len(queries) == one
    queries.clear()
    lookup.color_bodies(coll.db, colours[:1])
    one = len(queries)
    queries.clear()
    lookup.color_bodies(coll.db, colours)
    assert len(queries) == one
