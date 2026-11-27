"""#546: the jump search takes an element id (the number printed on a bag or a booklet) and lands on the part in that colour: owned rows of that
colour only, or the catalogue part, labelled "not in your collection", when nothing of it is owned or wanted. The catalogue search of API v2 takes the
same id. Invented element ids on the fixture world of `tests/app4.py`."""
from brickwork.core import collection, items
from tests.app4 import app4, client, coll, elements, pair, read, world  # noqa: F401 (fixtures)
from tests.api2 import call, v2, validate  # noqa: F401


def found(db, q):
    return [(r['item_id'], r.get('color_id'), r.get('entity'), r.get('element')) for r in collection.search(db, q)['results']]


def with_elements(pair, coll):
    elements(pair, coll, ('3001', '4', '4211383'), ('3001', '4', '300121'), ('3023', '4', '302321'), ('3023', '15', '302301'))


def test_an_owned_element_finds_that_colour_only_with_every_element_id(world, coll, pair, read):
    with_elements(pair, coll)
    with read() as db:
        assert items.element(db, '300121') == (world.brick, world.red) and items.element(db, '30012') is None and items.element(db, 'abc12') is None
        hits = collection.search(db, '300121')['results']
        assert {(r['item_id'], r['color_id']) for r in hits} == {(world.brick, world.red)}                  # no other colour of 3001
        assert hits[0]['element'] == '300121' and hits[0]['element_ids'] == ['300121', '4211383'] and hits[0]['entity'] != 'catalogue'
        assert {i['id'] for i in hits[0]['instances']} == {world.stock_brick, world.stock_brick_new}


def test_an_element_of_a_part_not_owned_shows_the_catalogue_part(world, coll, pair, read):
    with_elements(pair, coll)
    with read() as db:
        assert found(db, '302321') == [(world.plate, world.red, 'catalogue', '302321')]      # 3023 red is only a spare in a set: not owned
        assert {e for _, _, e, _ in found(db, '302301')} == {'stock', 'wish'}                   # 3023 white: loose and wanted
        assert found(db, '9999999') == []


def test_the_jump_dialog_labels_the_element_and_a_part_not_in_the_collection(world, coll, pair, client):
    with_elements(pair, coll)
    rows = client.get('/collection/jump?q=302321').get_json()['results']
    (part,) = [r for r in rows if r['kind'] == 'part']
    assert part['type_label'] == 'Parts · element 302321 · not in your collection' and part['element_ids'] == ['302321']
    assert client.get(part['url']).status_code == 200
    (owned,) = [r for r in client.get('/collection/jump?q=4211383').get_json()['results'] if r['kind'] == 'part']
    assert owned['type_label'] == 'Parts · element 4211383'


def test_the_api_catalogue_search_takes_an_element_id(world, coll, pair, v2):
    with_elements(pair, coll)
    answer = call(v2, '/catalogue/items?q=302321')
    validate(answer, 'get_catalogue_items')
    first = answer.json['data'][0]
    assert first['item']['id'] == world.plate and first['element']['id'] == '302321' and first['element']['element_ids'] == ['302321']
    assert first['element']['color']['id'] == world.red
    assert all('element' not in r for r in call(v2, '/catalogue/items?q=3023').json['data'])
