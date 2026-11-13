"""Set Inspector, Largest first: physical size from the catalogue name, then count, then colour."""
import pytest

from brickwork.core.checker import sorter
from brickwork.core.part_size import volume


@pytest.mark.parametrize('name,category,expected', [
    ('Brick 2 x 4', 'Brick', 8), ('Brick 1 x 2 x 3', 'Brick', 6), ('Plate 2 x 4', 'Plate', 8 / 3),
    ('Baseplate 32 x 32', 'Baseplate', 1024 / 3), ('Tile 1 x 1', 'Tile', 1 / 3), ('Slope 45 2 x 1', 'Slope', 2),
    ('Plate 1 1/2 x 2', 'Plate', 1.0), ('Technic Axle 6', 'Technic, Axle', 1.5),
    ('Minifigure, Utensil Sword', 'Minifigure, Utensil', 0.2), ('Wheel 30.4mm D. x 20mm', 'Wheel', 1.5),
])
def test_volume(name, category, expected):
    assert volume(name, category) == pytest.approx(expected)


def test_largest_first_is_by_size_then_count_then_colour():
    rows = [
        dict(token='a', name='Plate 1 x 1', category='Plate', quantity=20, color_name='Red', item_no='3024'),
        dict(token='b', name='Brick 2 x 4', category='Brick', quantity=1, color_name='Red', item_no='3001'),
        dict(token='c', name='Baseplate 16 x 16', category='Baseplate', quantity=1, color_name='Green', item_no='6098'),
        dict(token='d', name='Plate 2 x 4', category='Plate', quantity=4, color_name='Blue', item_no='3020'),
        dict(token='e', name='Brick 1 x 2', category='Brick', quantity=2, color_name='Yellow', item_no='3004'),
        dict(token='f', name='Brick 1 x 2', category='Brick', quantity=2, color_name='Black', item_no='3004'),
        dict(token='g', name='Slope 45 2 x 1', category='Slope', quantity=6, color_name='Red', item_no='3040'),
        dict(token='h', name='Technic Pin', category='Technic, Pin', quantity=10, color_name='Black', item_no='2780'),
    ]
    position = {r['token']: i for i, r in enumerate(rows)}
    ordered = [r['token'] for r in sorted(rows, key=sorter('largest', position))]
    # Baseplate, 2x4 brick, 2x4 plate; the 1x2-sized pieces by count (slope 6, then both bricks by colour);
    # then the 1x1 plate and the pin, however many there are.
    assert ordered == ['c', 'b', 'd', 'g', 'f', 'e', 'a', 'h']


def test_category_groups_use_catalogue_order_and_the_complete_largest_tie_breaker():
    rows = [dict(token=str(i), kind='part', name=name, category=category,
                 quantity=count, color_name=colour, item_no=number)
            for i, (name, category, count, colour, number) in enumerate([
                ('Tile 8 x 8', 'Tiles', 9, 'Red', '1'),
                ('Brick 1 x 1', 'Bricks', 2, 'Red', '2'),
                ('Plate 1 x 1', 'Plates', 1, 'Red', '3'),
                ('Brick 2 x 4', 'Bricks Special', 1, 'Red', '4'),
                ('Brick 1 x 1', 'Bricks', 3, 'Red', '2'),
                ('Brick 1 x 1', 'Bricks', 3, 'Black', '2'),
                ('Brick 1 x 1', 'Bricks', 3, 'Black', '1'),
                ('Brick 1 x 1', 'Bricks', 3, 'Black', '1'),
                ('Brick 9 x 9', None, 1, 'Red', '9'),
                ('Brick 8 x 8', 'Unmapped category', 1, 'Red', '8'),
                ('Slope 2 x 2', 'Bricks Sloped', 1, 'Red', '5'),
            ])]
    position = {r['token']: i for i, r in enumerate(rows)}
    assert [r['token'] for r in sorted(rows, key=sorter('group', position))] == [
        '3', '6', '7', '5', '4', '1', '10', '2', '0', '8', '9']
    assert sorted(rows, key=sorter('unrecognised', position)) == rows
    figures = [dict(r, kind='figure') for r in rows]
    assert sorted(figures, key=sorter('group', position)) == figures


def test_group_sort_keeps_figures_together_before_every_part_group():
    from brickwork.core.part_groups import GROUPS

    rows = []
    expected = ['figure-first', 'figure-second']
    for index, categories in enumerate(GROUPS.values()):
        for size in (1, 4):
            rows.append(dict(token=f'{index}-{size}', kind='part', name=f'Brick 1 x {size}',
                             category=categories[0], quantity=1))
        expected.extend([f'{index}-4', f'{index}-1'])
    rows.insert(1, dict(token='figure-first', kind='figure'))
    rows.insert(8, dict(token='figure-second', kind='figure'))
    position = {r['token']: i for i, r in enumerate(rows)}
    assert [r['token'] for r in sorted(rows, key=sorter('group', position))] == expected
