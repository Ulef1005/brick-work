"""#41 size-aware part search in Add (M.8c, issue #110): the catalogue's `size_key` answers "2x1", "1*2" and "x3" in any order or
spelling, the other words match names, and a part number that looks like a size stays a part number. Invented parts on top of the
fixture catalogue; the shared Python/JavaScript table is tested in `test_collection_lists_size_search.py`."""
from contextlib import closing

from brickwork.core import add
from brickwork.core.connect import connect
from tests.app4 import make_pair


def test_catalogue_search_filters_by_size_key_and_keeps_part_numbers(tmp_path):
    parts = [['3021', 'Plate 2 x 3', 14, 'Plastic'], ['3004', 'Brick 1 x 2', 11, 'Plastic'], ['x1435', 'Gear Wheel Special', 11, 'Plastic'],
             ['3022', 'Plate 2 x 2', 14, 'Plastic']]
    pair = make_pair(tmp_path, rich=True, extra_dump={'parts': parts})
    with closing(connect(pair)) as db:
        found = lambda q: sorted(r['number'] for r in add.search(db, 'part', q)['items'])
        assert found('2x1') == ['3004', '3023'] and found('1*2') == ['3004', '3023'] and found('1 x 2') == ['3004', '3023']
        assert found('plate 2 x 1') == ['3023']                                   # the other words still match names
        assert found('x3') == ['3021'] and found('3x') == ['3021']                # a partial size: any part with that dimension
        assert found('x1435') == ['x1435']                                        # not a size: a part number
        assert db.execute("SELECT size_key FROM catalogue.item WHERE born_key='3021'").fetchone()[0] == '2x3'
        assert add.search(db, 'part', '2x1')['count'] == 2
