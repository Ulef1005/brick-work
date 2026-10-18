"""Pure helpers kept by the standalone checker and formatting."""
import pytest

from brickwork.web.formatting import plural
from brickwork.web.part_size import ordered, progress, size_score


def test_size_proxy():
    assert size_score('Baseplate 32 x 32') > size_score('Panel 2 x 5 x 6 Wall') > size_score('Brick 1 x 2 x 5') > size_score('Plate 2 x 4') > size_score('Tile 1 x 1')
    assert size_score('Technic Brick 1 x 2 [1 Pin Hole]') == 6
    assert 48 < size_score('Wheel 24 x 43 Technic') < 120
    assert size_score('Wheel Arch, Mudguard 2 x 4') == 8
    assert size_score('Technic Axle 32') > size_score('Technic Pin')
    assert size_score('Unknown') == 4
    assert size_score('Plate 1 1/2 × 2') == 2
    assert size_score('Brick 2 x 2 or 3 x 3') == 12  # ambiguous: representative brick
    assert size_score('Plate 2 X 4') == size_score('Plate 2 × 4')


def test_spares_missing_first_and_stable_order():
    rows = [dict(key=str(i), sequence=i, score=score, spare=spare, missing=missing, checked=checked, colour=colour)
            for i, (score, spare, missing, checked, colour) in enumerate(
                [(10, False, 0, True, 'White'), (2, False, 1, False, 'Black'), (100, True, 1, False, 'Black')])]
    assert [r['key'] for r in ordered(rows, 'missing')] == ['1', '0', '2']
    assert [r['key'] for r in ordered(rows)] == ['0', '1', '2']
    assert progress(rows) == dict(total=2, checked=1, missing=1, checked_missing=0)


@pytest.mark.parametrize('count,expected', [(0, '0 copies'), (1, '1 copy'), (2, '2 copies')])
def test_plurals(count, expected):
    assert plural(count, 'copy', 'copies') == expected
    assert plural(count, 'part') == f'{count} {"part" if count == 1 else "parts"}'
