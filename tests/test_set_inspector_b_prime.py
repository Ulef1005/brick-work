"""The Set Inspector of the B′ frames (R3-02, #495): the frame's check in the `frames` world, the top block, the answer card, the history of the last answers and
the editable missing count, and a phone that never scrolls sideways."""
import json
from pathlib import Path
import subprocess
import urllib.request

from bs4 import BeautifulSoup
import pytest

from brickwork.core import checker
from brickwork.core.admin import database
from brickwork.demo import checks, frames
from scripts import screen_gate
from tests import rendered

ROOT = Path(__file__).resolve().parents[1]
COPY = frames.INSPECTOR['copy']


def built(tmp_path):
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store('frames', store)
    return store


def test_the_frame_copy_has_the_checks_of_frame_06(tmp_path):
    """131 part lines, 54 found, 4 missing (12 pieces), 73 to check; 142 of 375 pieces checked; the 59th line (Fence Lattice 1 × 4 × 1, 3633, Dark Bluish Gray, need 2) is next."""
    with database(built(tmp_path), read_only=True) as db:
        state = checker.view(db, COPY)
    session, rows = state['session'], {r['token']: r for r in state['rows']}
    required = [rows[t] for t in session['order']]
    assert len(required) == 131 and all(r['kind'] == 'part' for r in required)
    answered = [r for r in required if session['answers'].get(r['token']) == 'answered']
    assert len(answered) == 58 and sum(1 for r in answered if r['missing']) == 4 and sum(r['missing'] for r in answered) == 12
    assert sum(r['quantity'] for r in answered) == 142 and sum(r['quantity'] for r in required) == 375
    current = rows[session['order'][session['cursor']]]
    assert (session['cursor'], current['name'], current['color_name'], current['item_no'], current['quantity'], current['rgb']) == (58, 'Fence Lattice 1 × 4 × 1', 'Dark Bluish Gray', '3633', 2, '#6C6E68')
    assert state['saved_at'] == '2026-10-12T14:20:00.000Z' and state['copy']['copy_no'] == 2 and state['copy']['copy_count'] == 2 and state['copy']['place'] == 'Flohmarkt Mauerpark'
    last = [rows[t]['item_no'] for t in reversed(session['order'][:58])][:4]
    assert last == ['3005', '3004', '3010', '3008']                                      # the frame's "Checked so far": three found lines and the missing Brick 1 × 8


def test_the_frame_copys_bar_on_the_sets_page_is_unchanged(tmp_path):
    from brickwork.core import collection
    with database(built(tmp_path), read_only=True) as db:
        rows = {r['item_no']: r for r in collection.listing(db, 'S')}
    assert rows['7213-1']['bars'] == [[365, 10, 375, 0, 0], [130, 12, 375, 0, 0]]


def test_set_count_changes_a_listed_line_without_moving_the_cursor(tmp_path):
    """The stepper of a missing card (O10b): one more or one fewer missing on a line already answered; the walk stays on the line it was on."""
    with database(built(tmp_path)) as db:
        before = checker.view(db, COPY)
        s = before['session']
        token = next(t for t in reversed(s['order'][:58]) if {r['token']: r for r in before['rows']}[t]['item_no'] == '3008')
        gap = {r['token']: r for r in before['rows']}[token]
        assert gap['missing'] == 1 and gap['quantity'] == 2
        after = checks.call(db, COPY, action='set_count', session=s['id'], token=token, found=0)   # one more missing
        assert {r['token']: r for r in after['rows']}[token]['missing'] == 2 and after['session']['cursor'] == 58
        again = checks.call(db, COPY, action='set_count', session=s['id'], token=token, found=2)   # none missing: it leaves the list
        assert {r['token']: r for r in again['rows']}[token]['missing'] == 0 and token not in again['session']['misses'] and again['session']['cursor'] == 58
        checks.call(db, COPY, action='undo', session=s['id'])
        assert checker.view(db, COPY)['rows'] and {r['token']: r for r in checker.view(db, COPY)['rows']}[token]['missing'] == 2


def fetch(base, path):
    with urllib.request.urlopen(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


@rendered.group
def test_the_page_names_the_feature_the_copy_and_keeps_the_dialogs_outside_the_scope():
    with screen_gate.world('frames') as base:
        page = fetch(base, f'/workbench/check-parts/{COPY}?run=1')
    top = page.select_one('#bw-checker[data-bp-checker] .bp-chk.b-prime[data-chk-top]')
    assert top and top.select_one('.lbl').get_text() == 'Workbench · Set Inspector'
    assert top.select_one('.chk-line').get_text() == '7213-1 · Copy 2 of 2 · bought used, Flohmarkt Mauerpark'
    assert top.select_one('h1').get_text() == 'Off-Road Fire Truck & Fireboat' and top.select_one('[data-chk-tag]').get_text() == 'Check in progress'
    assert top.select_one('.chk-saved').get_text() == 'Saved 14:20 · resume any time'
    assert top.select_one('.cells[data-progress]') is not None
    # the message, Undo and Retry (and so any dialog) are outside the .b-prime scope, whose reset would strip their padding
    feedback = page.select_one('[data-save-feedback]')
    assert feedback and not feedback.find_parent(class_='b-prime')
    assert [b.get_text() for b in feedback.select('button')] == ['Undo', 'Retry']
    assert page.select_one('[data-stage]') and not page.select_one('[data-stage]').find_parent(class_='b-prime')


@rendered.group
def test_a_figure_check_and_the_chooser_keep_their_page():
    with screen_gate.world('frames') as base:
        chooser = fetch(base, '/workbench/check-parts')
    assert not chooser.select('[data-bp-checker]') and chooser.select_one('#bw-check-choices')


@rendered.group
@pytest.mark.parametrize('width', [320, 375])
def test_the_page_never_scrolls_sideways_below_390(tmp_path, width):
    """Each element handles its own width (Ulf, 2026-11-20): a long free-text set name and a long copy place are put in, and the page must still fit."""
    chrome = rendered.chrome()
    script = ("document.querySelectorAll('.chk-title').forEach(n=>n.textContent='A very long free text set name without any break '+'x'.repeat(60));"
              "document.querySelectorAll('.chk-nm').forEach(n=>n.textContent='A part name '+'y'.repeat(80));"
              "if(document.documentElement.scrollWidth>innerWidth)throw new Error('sideways: '+document.documentElement.scrollWidth+' > '+innerWidth);")
    with screen_gate.world('frames') as base:
        jobs = {'jobs': [{'url': base + f'/workbench/check-parts/{COPY}?run=1', 'out': str(tmp_path / f'{theme}.png'), 'width': width, 'theme': theme, 'wait': 'main', 'script': script}
                         for theme in ('light', 'dark')]}
        (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@rendered.group
def test_the_section_strip_scrolls_inside_itself_at_375():
    """The sub row (the shell's section tabs) is wider than a phone and scrolls inside itself, never the page."""
    chrome = rendered.chrome()
    script = ("const row=document.querySelector('.psub');if(!row)throw new Error('no phone sub row');"
              "if(row.scrollWidth<=row.clientWidth)throw new Error('the strip should be wider than the phone: '+row.scrollWidth+' vs '+row.clientWidth);"
              "if(!/auto|scroll/.test(getComputedStyle(row).overflowX))throw new Error('the strip does not scroll inside itself');")
    import tempfile
    with tempfile.TemporaryDirectory() as scratch, screen_gate.world('frames') as base:
        jobs = {'jobs': [{'url': base + f'/workbench/check-parts/{COPY}?run=1', 'out': str(Path(scratch) / 'x.png'), 'width': 375, 'theme': 'light', 'wait': 'main', 'script': script}]}
        (Path(scratch) / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(Path(scratch) / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@rendered.group
def test_a_copy_never_checked_has_the_x_device_and_a_figure_check_keeps_its_progress(tmp_path):
    from brickwork.demo.showcase import uid
    store = built(tmp_path)
    with database(store, read_only=True) as db:
        figure = db.execute('SELECT copy_id, id FROM copy_figure WHERE retired_at IS NULL ORDER BY copy_id, id LIMIT 1').fetchone()
    with screen_gate.world('frames') as base:
        never = fetch(base, f'/workbench/check-parts/{uid("copy", "7213-1", "a")}')
        fig = fetch(base, f'/workbench/check-parts/{figure[0]}/figure/{figure[1]}')
    chip = never.select_one('[data-chk-tag]')
    assert 'xchip' in chip['class'] and chip.get_text(strip=True) == 'Not checked' and chip.select_one('svg path')   # the X of the Sets bar, not a dashed tag
    assert fig.select_one('#bw-checker [data-chk-big]') and fig.select_one('#bw-checker [data-legend]') and fig.select_one('#bw-checker .cells[data-progress]')
    assert not fig.select_one('[data-save-feedback]').find_parent(class_='b-prime')
