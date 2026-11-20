"""The Matchmaker of the B′ frames (frame 09, #498): the three copies of the `frames-matcher` world, the drawn page, untouched picker chooser, and phone widths without horizontal scroll."""
import json
from pathlib import Path
import re
import subprocess
import urllib.request

from bs4 import BeautifulSoup
import pytest

from brickwork.core import workbench
from brickwork.core.admin import database
from scripts import screen_gate
from tests import rendered

ROOT = Path(__file__).resolve().parents[1]
PATH = '/workbench/matcher'


def built(tmp_path):
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store('frames-matcher', store)
    return store


def fetch(base, path):
    with urllib.request.urlopen(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


def test_the_matcher_world_has_the_three_copies_of_frame_09(tmp_path):
    """Three copies can be advanced in order; the first copy of 7213-1 has no match."""
    store = built(tmp_path)
    with database(store, read_only=True) as db:
        all_gaps = workbench.gaps(db)
        rows = workbench.matches(db, all_gaps=all_gaps)
        groups = workbench.group_matches(db, rows, all_gaps)
    summary = [
        (g['copy']['set_no'], g['copy']['label'], g['covered'], g['missing'], g['completes'])
        for g in groups
    ]
    assert summary == [
        ('7213-1', 'Set 2', 7, 12, False),
        ('10210-1', 'Set 1', 11, 33, False),
        ('7938-1', 'Set 1', 2, 14, False),
    ]
    assert not any(g['copy']['set_no'] == '7213-1' and g['copy']['label'] == 'Set 1' for g in groups)


@rendered.group
def test_the_page_is_drawn_to_the_frame():
    with screen_gate.world('frames-matcher') as base:
        page = fetch(base, PATH)
    root = page.select_one('#bw-workbench[data-mode=matcher]')
    assert root is not None
    assert any(el.get_text(' ', strip=True) == 'Workbench · Matchmaker' for el in root.find_all(True))
    assert root.select_one('h1').get_text(' ', strip=True) == '3 copies can be advanced, 0 can become complete'
    assert any(
        'Completable first, then coverage' in el.get_text(' ', strip=True)
        and '3 copies' in el.get_text(' ', strip=True)
        and not el.select('.bw-copy-group')
        and not el.select('h1')
        for el in root.find_all(True)
    )
    groups = root.select('article.bw-copy-group')
    assert len(groups) == 3
    for group in groups:
        for attr in ('data-row', 'data-copy-id', 'data-name', 'data-number', 'data-need', 'data-filter-value'):
            assert group.has_attr(attr)
    expected = [
        ('covers 7 of 12 missing', 'Copy 2', '58.3%'),
        ('covers 11 of 33 missing', 'Copy 1', '33.3%'),
        ('covers 2 of 14 missing', 'Copy 1', '14.3%'),
    ]
    for group, (covers_text, copy_text, width_pct) in zip(groups, expected):
        text = ' '.join(group.get_text(' ', strip=True).split())
        assert covers_text in text and copy_text in text
        assert any(
            re.search(rf'width\s*:\s*{re.escape(width_pct)}', el.get('style', ''))
            for el in group.select('[style]')
        )
    tiles = [group.select_one('.bp-match-pic') for group in groups]   # the copy's own tile; the part tiles inside the match details keep their own text
    assert all(tile is not None and tile.get_text(' ', strip=True) == 'Set picture' for tile in tiles)
    assert root.select_one('input[type="search"], input[data-search]') is not None
    assert root.select_one('button[data-filters]') is not None
    assert any(b.get_text(' ', strip=True) == 'Sort' for b in root.select('button'))
    assert root.select_one('form[data-action="booklets"]') is not None
    assert 'Add instruction booklets' in root.get_text(' ', strip=True)
    assert any(
        d.select_one('summary') and 'How matching works' in d.select_one('summary').get_text(' ', strip=True)
        for d in root.select('details')
    )
    assert root.select_one('[data-list="history"]') is not None
    assert 'Recent saves' in root.get_text(' ', strip=True)


@rendered.group
def test_the_other_workbench_states_are_not_changed():
    """The Part Runner chooser keeps its own page with no Matchmaker header or group classes."""
    with screen_gate.world('frames-matcher') as base:
        chooser = fetch(base, '/workbench/part-picker')
    assert not chooser.select('.bp-match-head') and not chooser.select('.bp-match-group')
    assert chooser.select_one('[data-choose] h1').get_text() == 'Pick for which sets?'


@rendered.group
@pytest.mark.parametrize('width', [320, 375])
def test_the_page_never_scrolls_sideways_below_390(tmp_path, width):
    chrome = rendered.chrome()
    script = "if(document.documentElement.scrollWidth!==innerWidth)throw new Error('sideways: '+document.documentElement.scrollWidth+' vs '+innerWidth);"
    with screen_gate.world('frames-matcher') as base:
        jobs = {'jobs': [{'url': base + PATH, 'out': str(tmp_path / f'{theme}.png'), 'width': width, 'theme': theme, 'wait': 'main', 'script': script} for theme in ('light', 'dark')]}
        (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
