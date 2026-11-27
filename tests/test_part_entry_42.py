"""#42: what Part Spotter's review step can infer. The colours the catalogue knows a part in (one is preselected), where the same part, colour
and condition already sits as loose stock (the "add here" group, other conditions apart), a piece saved "into" one of those rows merging there,
and the JSON lookup the page's script will call. Invented data on the fixture world of `tests/app4.py`."""
import json

import pytest

from brickwork.core import part_inventory as inventory
from tests.app4 import app4, client, coll, elements, pair, read, world  # noqa: F401 (fixtures)


def piece(world, n, **chosen):
    return dict(id=f'piece-{n}', candidates=[dict(item_id=world.brick, score=.9)], chosen=dict(item_id=world.brick, color_id=world.red, quantity=1, **chosen))


def test_known_colours_come_from_the_catalogue_and_what_is_held(world, coll):
    db = coll.db
    plate = inventory.known_colours(db, world.plate)                              # 3023: white and red in the set inventory, white held
    assert {c['color_id'] for c in plate['colours']} == {world.white, world.red} and plate['single'] is None and plate['known']
    brick = inventory.known_colours(db, world.brick)                              # 3001: only red anywhere
    assert [c['color_id'] for c in brick['colours']] == [world.red] and brick['single'] == world.red


def test_an_element_id_adds_its_colour(world, coll, pair):
    elements(pair, coll, ('3001', '15', '300101'))
    assert {c['color_id'] for c in inventory.known_colours(coll.db, world.brick)['colours']} == {world.red, world.white}


def test_a_part_with_no_known_colour_says_so(world, coll):
    assert inventory.known_colours(coll.db, world.local_part)['colours'][0]['color_id'] == world.red   # held in red
    assert inventory.known_colours(coll.db, world.mystery) == dict(colours=[], single=None, known=False)


def test_existing_rows_list_the_same_condition_most_first_and_count_the_others(world, coll):
    found = inventory.existing_rows(coll.db, world.brick, world.red, 'U')
    assert [r['stock_id'] for r in found['rows']] == [world.stock_brick] and found['total'] == 3
    assert found['rows'][0]['storage'] == 'Shelf A' and found['rows'][0]['lot'] == 'Bag'
    assert found['other_conditions'] == {'new': 2}
    assert inventory.existing_rows(coll.db, world.plate, world.red, 'used') == dict(rows=[], total=0, other_conditions={})
    with pytest.raises(ValueError):
        inventory.existing_rows(coll.db, world.brick, world.red, 'mint')


def test_a_piece_saved_into_an_owned_row_merges_there_and_undo_takes_it_back(world, coll):
    db = coll.db
    event = inventory.save(db, [piece(world, 1, into=world.stock_brick)], batch='into', condition='used', keep_photos=False)
    assert db.execute('SELECT quantity FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[0] == 4
    receipt = json.loads(db.execute('SELECT new_value FROM event WHERE id=?', (event,)).fetchone()[0])
    assert [c['id'] for c in receipt['stock']] == [world.stock_brick]
    inventory.undo(db, event)
    assert db.execute('SELECT quantity FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[0] == 3


def test_into_a_row_of_another_condition_or_part_is_refused(world, coll):
    db = coll.db
    for into in (world.stock_brick_new, world.stock_plate, 'nope'):
        with pytest.raises(ValueError, match='That stock changed'):
            inventory.save(db, [piece(world, 2, into=into)], batch='bad-' + into, condition='used', keep_photos=False)


def test_the_lookup_answers_the_colours_and_with_a_colour_the_rows(world, client):
    body = client.get(f'/workbench/part-to-inventory/lookup?item_id={world.brick}').get_json()
    assert body['colours']['single'] == world.red and 'existing' not in body
    body = client.get(f'/workbench/part-to-inventory/lookup?item_id={world.brick}&colour={world.red}&condition=N').get_json()
    assert [r['stock_id'] for r in body['existing']['rows']] == [world.stock_brick_new] and body['existing']['other_conditions'] == {'used': 3}
    assert client.get('/workbench/part-to-inventory/lookup?item_id=x').status_code == 400
