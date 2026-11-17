"""Short body-part names on a figure line of set detail (#34, design frame 12g)."""
from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection, figure_parts
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (fixtures)
from tests.test_bw_ui_3332 import FIGURE, SET, figure_part, figure_row

NAME = 'Minifig Part'


@pytest.mark.parametrize('category,expected', [
    ('Minifig Heads', 'Head'), ('Minifigure, Head', 'Head'),
    ('Minifig Upper Body', 'Torso'), ('Minifigure, Torso', 'Torso'),
    ('Minifig Lower Body', 'Legs'), ('Minifigure, Legs', 'Legs'),
    ('Minifigure, Hips', 'Hips'),
    ('Minifig Headwear', 'Headgear'), ('Minifigure, Headgear', 'Headgear'),
    ('Minifigure, Hair', 'Hair'),
    ('Minifig Accessories', 'Accessory'), ('Minifig Neckwear', 'Accessory'), ('Minifig Shields, Weapons, & Tools', 'Accessory'),
    ('Minifigs', 'Other'), ('minifig   HEADS ', 'Head'),
])
def test_every_short_name_from_its_category(category, expected):
    assert figure_parts.short_name(category, NAME) == expected
    assert expected in figure_parts.SHORT_NAMES


@pytest.mark.parametrize('category,name,expected', [
    ('Minifig Lower Body', 'Hips and Black Legs', 'Legs'), ('Minifig Lower Body', 'Minifig Hips Plain', 'Hips'),
    ('Minifig Headwear', 'Minifig Hair Short Swept', 'Hair'), ('Minifig Headwear', 'Minifig Hat Pirate', 'Headgear'),
    ('Minifig Upper Body', 'Torso Police Shirt', 'Torso'), ('Minifig Upper Body', 'Minifig Arm Left', 'Other'),
    ('Minifig Upper Body', 'Minifig Hand', 'Other'),
])
def test_the_part_name_settles_hips_hair_and_arms(category, name, expected):
    assert figure_parts.short_name(category, name) == expected


@pytest.mark.parametrize('category', [None, '', 'Bricks', '5'])
def test_a_part_in_no_figure_category_gets_the_first_words_of_its_name(category):
    assert figure_parts.short_name(category, 'Cape Cloth, Standard, Dark Red') == 'Cape Cloth, Standard'
    assert figure_parts.short_name(category, 'Flag 2 x 2') == 'Flag 2'
    assert figure_parts.short_name(category, 'Cape') == 'Cape'
    assert figure_parts.short_name(category, None) == 'Other'


def test_the_short_names_of_a_figure_are_distinct_and_keep_their_order():
    parts = [('Minifig Upper Body', 'Torso A'), ('Minifig Lower Body', 'Legs B'), ('Minifig Upper Body', 'Torso C')]
    assert figure_parts.short_names(parts) == ['Torso', 'Legs']
    assert figure_parts.short_names([]) == []


def test_the_figure_line_shows_short_names_and_keeps_the_full_names(coll, client):
    copy = coll.add_copy(SET)
    set_id = coll.item('sets', SET)
    full = figure_part(coll, copy, missing=1)
    coll.sql("UPDATE item SET category_name='Minifig Lower Body' WHERE id=?", (coll.item('parts', '970c03'),))
    detail = collection.detail(coll.db, set_id, copy_id=copy)
    entry = next(r for r in detail['consists'] if r['number'] == FIGURE)
    assert entry['missing_part_short'] == ['Legs'] and entry['missing_part_names'] == [full]
    soup = BeautifulSoup(client.get(f'/collection/item/{set_id}?copy={copy}&inventory=figures').data, 'html.parser')
    span = figure_row(soup).select_one('.bc-figure-parts')
    assert span.get_text() == 'Legs' and span['title'] == full


def test_the_markup_joins_several_short_names_with_a_mid_dot(app4):
    template = app4.jinja_env.from_string("{{ r.missing_part_short|join(' · ') }}")
    assert template.render(r=dict(missing_part_short=['Torso', 'Legs'])) == 'Torso · Legs'


def test_the_figure_parts_check_still_shows_full_names(coll, client):
    copy = coll.add_copy(SET)
    full = figure_part(coll, copy, missing=1)
    coll.sql("UPDATE item SET category_name='Minifig Lower Body' WHERE id=?", (coll.item('parts', '970c03'),))
    line = coll.db.execute('SELECT id FROM copy_figure WHERE copy_id=? AND item_id=?', (copy, coll.item('minifigs', FIGURE))).fetchone()[0]
    page = client.get(f'/workbench/check-parts/{copy}/figure/{line}')
    assert page.status_code == 200 and full in page.get_data(as_text=True)
