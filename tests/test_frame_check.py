"""#492 part 2: the app-vs-frame check (scripts/frame_check.py): the band rule, the shell heights read from the frames, the `frames` world."""
import importlib.util
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('frame_check', ROOT / 'scripts' / 'frame_check.py')
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


def shot(path, height, marks=()):
    image = Image.new('RGB', (200, height), (255, 255, 255))
    for x, y in marks:
        image.putpixel((x, y), (0, 0, 0))
    image.save(path)
    return path


def test_identical_shots_are_ok(tmp_path):
    a, b = shot(tmp_path / 'a.png', 400), shot(tmp_path / 'b.png', 400)
    result = fc.compare(a, b, 1440, band=False)
    assert result['ratio'] == 0 and fc.verdict(result) == 'ok'


def test_band_rule_thresholds():
    assert fc.verdict({'ratio': 0.0009, 'dh': 0, 'tall': 1000}) == 'ok'
    assert fc.verdict({'ratio': 0.005, 'dh': 0, 'tall': 1000}) == 'NOTE'
    assert fc.verdict({'ratio': 0.021, 'dh': 0, 'tall': 1000}) == 'FAIL'
    assert fc.verdict({'ratio': 0.0, 'dh': 150, 'tall': 1000}) == 'FAIL'
    assert fc.verdict({'ratio': 0.0, 'dh': 40, 'tall': 1000}) == 'NOTE'


def test_a_height_difference_is_cropped_to_the_shorter_shot(tmp_path):
    a, b = shot(tmp_path / 'a.png', 400), shot(tmp_path / 'b.png', 600)
    result = fc.compare(a, b, 1440, band=False)
    assert result['ratio'] == 0 and result['dh'] == 100 and result['tall'] == 300


def test_a_crop_limit_leaves_the_rows_below_it_uncompared(tmp_path):
    """Design's rule for an excerpt frame (04-sets at 390): compare down to the drawn tile row, not the tile the frame cuts (#494)."""
    a = shot(tmp_path / 'a.png', 1000)
    b = shot(tmp_path / 'b.png', 1000, [(10, 300)])        # a mark at 150 CSS px (scale 2), far above the tab bar at the foot
    assert fc.compare(a, b, 390, band=False)['ratio'] > 0
    assert fc.compare(a, b, 390, band=False, limit=100)['ratio'] == 0   # the limit is 100 CSS px: the mark lies below it
    assert fc.compare(a, b, 390, band=False, limit=200)['ratio'] > 0
    assert fc.CROP_BELOW == {('04-sets', 390): 731, ('05-sets-without-storage', 390): 657, ('48-sets-pulled-copy', 390): 731} and {'04-sets', '05-sets-without-storage'} <= fc.BODY_BUILT
    assert fc.compare(a, b, 390, band=False, limit=-5)['ratio'] > 0     # a non-positive limit means no limit


def test_a_crop_limit_still_compares_the_phone_tab_bar_at_the_foot(tmp_path):
    """Review of the follow-up: the excerpt's cut must not hide a broken tab bar."""
    h = fc.band_rows(390)
    foot = next(px for where, px in h if where == 'foot')
    a = shot(tmp_path / 'a.png', 1688)                       # 844 CSS px at scale 2
    b = shot(tmp_path / 'b.png', 1688, [(10, 1688 - 3)])     # a mark in the tab bar
    assert fc.compare(a, b, 390, band=False, viewport=844, limit=700)['ratio'] > 0
    assert foot * 2 > 3


def test_the_foot_band_is_measured_from_each_shots_own_bottom(tmp_path):
    a = shot(tmp_path / 'a.png', 1000, [(10, 995)])        # a mark in the tab bar of the shorter shot
    b = shot(tmp_path / 'b.png', 1400, [(10, 1395)])       # the same mark in the foot of the taller one
    assert fc.compare(a, b, 390, band=True)['ratio'] == 0
    c = shot(tmp_path / 'c.png', 1400)
    assert fc.compare(a, c, 390, band=True)['ratio'] > 0


def test_the_shell_heights_come_from_the_frames():
    from b_prime_css import shell_heights
    h = shell_heights()
    assert set(h) == {'top', 'sub', 'ptop', 'tabbar', 'psub'} and all(v > 0 for v in h.values())


def test_the_count_line_names_the_approved_screens():
    assert fc.count_line().startswith('design gate: ') and ' approved screens built' in fc.count_line()
