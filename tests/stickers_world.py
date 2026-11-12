"""Invented sets for the sticker tests (#201): one catalogue, built once per test through `make_pair`.

Parts (all `stk`, invented): `tile` (the part a sticker goes on), `r1` (a rare part), `sheet-a` to `sheet-d` (category `Stickers`, found by name: the category id is 58 here
only as in the shipped catalogue), `bar`. Sets: `9401-1` holds the tile in red and sheet A (it has a sheet picture); `9402-1` the tile in red and sheet B;
`9403-1` the tile in red and the rare part, no sheet; `9404-1` the tile in WHITE and sheet C; `9405-1` the tile in red and sheet D as a spare line only;
`9406-1` has two inventory versions, the tile and sheet A only in the old one; `9407-1` holds the tile in red and no sheet; `9408-1` holds the tile in red
and two sheets, A and B (one row, the sheet with the lower number first); `9451-1` to `9453-1` hold the tile in red and sheet B (they fill the chooser's second page). Thirty noise sets hold only the tile in red, so the
tile is held by more than 25 sets (common when the setting is 25)."""
from contextlib import closing

import pytest

from brickwork.core.connect import connect
from tests.app4 import Coll, make_pair

PARTS = ['tile', 'r1', 'bar', 'sheet-a', 'sheet-b', 'sheet-c', 'sheet-d']
NOISE = [f'94{n}-1' for n in range(10, 40)]
SETS = {'9401-1': 2001, '9402-1': 2003, '9403-1': 1999, '9404-1': 2005, '9405-1': 2007, '9406-1': 1990, '9407-1': 2010, '9408-1': 2012, '9451-1': 2011, '9452-1': 2013, '9453-1': 2014}
DUMP = {
    'part_categories': [['58', 'Stickers']],
    'themes': [[700, 'Stickerland', '']],
    'parts': [[f'stk-{p}', f'Stk {p}', 58 if p.startswith('sheet') else 14, 'Plastic'] for p in PARTS],
    'sets': [[n, f'Stk Set {n[:4]}', y, 700, 40, ''] for n, y in SETS.items()] + [[n, f'Stk Noise {n[:4]}', 2010, 700, 5, ''] for n in NOISE],
    'inventories': ([[9501, 1, '9401-1'], [9502, 1, '9402-1'], [9503, 1, '9403-1'], [9504, 1, '9404-1'], [9505, 1, '9405-1'], [9506, 1, '9406-1'],
                    [9507, 2, '9406-1'], [9508, 1, '9407-1'], [9509, 1, '9408-1'], [9510, 1, '9451-1'], [9511, 1, '9452-1'], [9512, 1, '9453-1']] + [[9520 + i, 1, n] for i, n in enumerate(NOISE)]),
    'inventory_parts': (
        [[9501, 'stk-tile', 4, 4, 'False', ''], [9501, 'stk-sheet-a', 0, 1, 'False', 'https://img.invalid/sheet-a.jpg'], [9501, 'stk-bar', 0, 2, 'False', '']]
        + [[9502, 'stk-tile', 4, 4, 'False', ''], [9502, 'stk-sheet-b', 0, 1, 'False', '']]
        + [[9503, 'stk-tile', 4, 4, 'False', ''], [9503, 'stk-r1', 4, 1, 'False', '']]
        + [[9504, 'stk-tile', 15, 4, 'False', ''], [9504, 'stk-sheet-c', 0, 1, 'False', '']]
        + [[9505, 'stk-tile', 4, 4, 'False', ''], [9505, 'stk-sheet-d', 0, 1, 'True', '']]
        + [[9506, 'stk-tile', 4, 4, 'False', ''], [9506, 'stk-sheet-a', 0, 1, 'False', ''], [9507, 'stk-bar', 0, 1, 'False', '']]
        + [[9508, 'stk-tile', 4, 4, 'False', '']]
        + [[9509, 'stk-tile', 4, 4, 'False', ''], [9509, 'stk-sheet-b', 0, 1, 'False', ''], [9509, 'stk-sheet-a', 0, 1, 'False', '']]
        + [[9510 + n, 'stk-tile', 4, 4, 'False', ''] for n in range(3)] + [[9510 + n, 'stk-sheet-b', 0, 1, 'False', ''] for n in range(3)]
        + [[9520 + i, 'stk-tile', 4, 4, 'False', ''] for i in range(len(NOISE))]),
}
RED = '4'


@pytest.fixture
def pair(tmp_path):
    return make_pair(tmp_path, extra_dump=DUMP)


@pytest.fixture
def db(pair):
    with closing(connect(pair)) as db:
        yield db


@pytest.fixture
def coll(db):
    return Coll(db)


class World:
    """A lot with the tile in red (the flagged line, when `flag`) and the rare part, plus the helpers the tests ask for."""

    def __init__(self, coll, *, flag=False, rare=True):
        self.coll = coll
        self.lot = coll.lot('Sticker lot')
        self.tile = coll.item('parts', 'stk-tile')
        self.red = coll.colour(RED)
        self.line = coll.add_stock('part', self.tile, colour=self.red, quantity=2, condition='used', lot=self.lot)
        self.rare = coll.add_stock('part', coll.item('parts', 'stk-r1'), colour=self.red, quantity=1, condition='used', lot=self.lot) if rare else None
        if flag:
            self.flag()

    def flag(self):
        coll = self.coll
        coll.tag('stock', self.line, coll.flag('Sticker'))

    def set(self, number):
        return self.coll.item('sets', number)

    def sheet(self, key):
        return self.coll.item('parts', 'stk-' + key)


@pytest.fixture
def world(coll):
    return World(coll)
