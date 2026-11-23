"""The Part Runner of the B′ frames (R3-03, #496): the frame's run in the `frames` world, the top block, the card with its stepper, the next parts in storage order, the scopes
(dialogs stay outside), the other states of the page as shipped, and a phone that never scrolls sideways."""
import json
from pathlib import Path
import subprocess
import urllib.request

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection, workbench
from brickwork.core.admin import database
from brickwork.demo import frames
from scripts import screen_gate
from tests import rendered

ROOT = Path(__file__).resolve().parents[1]
PATH = frames.runner_path()
COPIES = [part.split('=')[1] for part in PATH.split('&') if part.startswith('copy=')]


def built(tmp_path):
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store('frames', store)
    return store


def run_rows(store, ranking=('storage', 'colour')):
    with database(store, read_only=True) as db:
        gaps = workbench.gaps(db)
        rows = workbench.picker(db, COPIES, list(ranking), all_gaps=gaps)
        places = workbench.picker_places(db, rows)
    return rows, places


def test_the_frames_world_has_the_run_of_frame_07(tmp_path):
    """4 sets, 52 parts (one per part and colour); the 7th is Fence Lattice 1 × 4 × 1 (3633, Dark Bluish Gray), 3 for 10210-1 copy 1, and the next three are the frame's."""
    rows, places = run_rows(built(tmp_path))
    assert len(rows) == 52 and len({(r['item_id'], r['color_id']) for r in rows}) == 52
    seventh = rows[6]
    assert (seventh['name'], seventh['color_name'], seventh['item_no'], seventh['total'], seventh['rgb']) == ('Fence Lattice 1 × 4 × 1', 'Dark Bluish Gray', '3633', 3, '6C6E68')
    assert [(g['copy']['set_no'], g['copy']['label'], g['need']) for g in seventh['needs']] == [('10210-1', 'Set 1', 3)]
    following = rows[7:10]
    assert [(r['name'], r['color_name'], r['item_no'], r['total']) for r in following] == [
        ('Brick 1 × 4', 'Dark Bluish Gray', '3010', 2), ('Brick 1 × 6', 'Light Bluish Gray', '3009', 1), ('Slope 45° 2 × 2', 'White', '87619', 4)]
    drawers = [places[(r['item_id'], r['color_id'])][0] for r in following]
    assert [(p['code'], p['root'], p['leaf']) for p in drawers] == [
        ('S-0002', 'Shelf A2 – Town', 'Drawer 3'), ('S-0002', 'Shelf A2 – Town', 'Drawer 3'), ('S-0001', 'Shelf A1 – Castle', 'Drawer 4')]
    assert all(not places.get((r['item_id'], r['color_id'])) for r in rows[10:]), 'only the first ten parts have a drawer'
    assert sorted({g['copy']['set_no'] for r in rows for g in r['needs']}) == ['10210-1', '7213-1', '7938-1']


def test_the_runs_missing_pieces_keep_the_bars_of_the_sets_frame_and_of_frame_06(tmp_path):
    store = built(tmp_path)
    with database(store, read_only=True) as db:
        bars = {r['item_no']: r['bars'] for r in collection.listing(db, 'S')}
    assert bars['7213-1'] == [[365, 10, 375, 0, 0, None], [130, 12, 375, 0, 0, None]]
    assert [b[:2] for b in bars['7938-1']] == [[643, 14]] and [b[:2] for b in bars['10210-1']] == [[1590, 33]]
    rows, _ = run_rows(store)
    assert sum(g['need'] for r in rows for g in r['needs']) == 69 and sum(1 for r in rows for g in r['needs'] if g['copy']['id'] == frames.INSPECTOR['copy']) == 4


def fetch(base, path):
    with urllib.request.urlopen(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


@rendered.group
def test_the_page_names_the_feature_the_run_and_the_next_parts_and_keeps_the_dialogs_outside_the_scope():
    with screen_gate.world('frames') as base:
        page = fetch(base, PATH)
    root = page.select_one('#bw-workbench[data-bp-run]')
    top = root.select_one('.bp-run.b-prime[data-run-top]')
    assert top.select_one('.head .lbl').get_text() == 'Workbench · Part Runner' and top.select_one('.run-eyebrow').get_text() == 'Workbench · Part Runner · 4 sets'
    assert top.select_one('h1').get_text() == 'Collecting for 4 sets' and top.select_one('.head p').get_text() == 'Storage order: parts come in the order of your drawers.'
    assert top.select_one('[data-run-label]').get_text() == 'Part 7 / 52'
    segments = [i['class'][0] for i in top.select('.run-strip i')]
    assert len(segments) == 52 and segments[:6] == ['f'] * 6 and segments[6] == 'c' and set(segments[7:]) == {'u'}
    assert [a.get_text(strip=True) for a in top.select('.run-link')] == ['Print list', 'Stop']
    stop = top.select_one('.bw-stop svg path')
    assert stop['d'] == 'M6 6l12 12M18 6L6 18' and not top.select('mask'), 'the thin X, not the logo X'
    shown = [c for c in root.select('[data-pick] [data-row]') if not c.has_attr('hidden')]
    assert len(shown) == 1
    card = shown[0]
    assert card.select_one('.bp-run-card.b-prime .run-n').get_text() == '3' and card.select_one('.run-nm').get_text(strip=True).replace('\xa0', ' ') == 'Fence Lattice 1 × 4 × 1'
    assert 'background:#6C6E68' in card.select_one('.run-cnt .v')['style'] and card.select_one('.run-for').get_text(strip=True) == 'for 10210-1 · copy 1 · 3 missing'
    act = card.select_one('.bp-run-act.b-prime')
    assert [b.get_text(strip=True) for b in act.select('button')] == ['−', 'Found ×3', '+', 'Missing']
    tape = card.select_one('.bp-run-next.b-prime [data-next-tape]')
    assert tape.get_text(' ', strip=True) == 'S-0002 Shelf A2 – Town 3 parts next'
    assert [r.select_one('.run-nx-name').get_text().replace('\xa0', ' ') for r in card.select('.bp-run-next [data-next] > [data-nx-row]')] == ['Brick 1 × 4', 'Brick 1 × 6', 'Slope 45° 2 × 2']
    assert [r.select_one('.run-nx-n').get_text() for r in card.select('.bp-run-next [data-next] > [data-nx-row]')] == ['2×', '1×', '4×']
    assert card.select_one('[data-nx-row] .run-nx-sub').get_text(' ', strip=True) == 'Dark Bluish Gray · 3010 · S-0002 · drawer 3'
    # the destination dialog and the message are outside every .b-prime scope, whose reset would strip their padding
    assert all(not d.find_parent(class_='b-prime') for d in root.select('dialog')) and not root.select_one('[data-message]').find_parent(class_='b-prime')
    assert not root.select_one('.bw-keys').find_parent(class_='b-prime')
    # the templates the JS builds a filtered next list from sit beside [data-next], never in it
    assert card.select_one('.bp-run-next > template[data-nx-item]') and not card.select('[data-next] template')


@rendered.group
def test_the_part_parameter_puts_the_run_on_its_part_and_stays_inside_the_run():
    with screen_gate.world('frames') as base:
        first = fetch(base, PATH.replace('&part=7', ''))
        past = fetch(base, PATH.replace('part=7', 'part=999'))
    assert first.select_one('[data-run-label]').get_text() == 'Part 1 / 52' and first.select_one('#bw-workbench')['data-start'] == '0'
    assert past.select_one('[data-run-label]').get_text() == 'Part 52 / 52' and past.select_one('#bw-workbench')['data-start'] == '51'


@rendered.group
def test_the_other_states_of_the_page_keep_their_pages():
    """The chooser, the ranking step and the Matchmaker are not the run: no B′ top block, as shipped."""
    with screen_gate.world('frames') as base:
        chooser = fetch(base, '/workbench/part-picker')
        ranking = fetch(base, f'/workbench/part-picker?copy={COPIES[0]}')
        matcher = fetch(base, '/workbench/match')
    for page in (chooser, ranking, matcher):
        assert not page.select('[data-bp-run]') and not page.select('.bp-run')
    assert chooser.select_one('[data-choose] h1').get_text() == 'Pick for which sets?'
    assert ranking.select_one('[data-rank] h1').get_text() == 'In what order do you pick?' and not ranking.select_one('[data-rank]').has_attr('hidden')
    assert matcher.select_one('#bw-workbench[data-mode=matcher]')


@rendered.group
@pytest.mark.parametrize('width', [320, 375])
def test_the_page_never_scrolls_sideways_below_390(tmp_path, width):
    """Each element handles its own width: a long part name, a long colour and a long set line are put in, and the page must still fit."""
    chrome = rendered.chrome()
    script = ("document.querySelectorAll('.run-nm').forEach(n=>n.textContent='A part name '+'y'.repeat(80));"
              "document.querySelectorAll('.run-colour').forEach(n=>n.textContent='A colour '+'z'.repeat(60));"
              "document.querySelectorAll('.run-for').forEach(n=>n.textContent='for '+'10210-1 · copy 1 · 3 missing · '.repeat(6));"
              "if(document.documentElement.scrollWidth>innerWidth)throw new Error('sideways: '+document.documentElement.scrollWidth+' > '+innerWidth);")
    with screen_gate.world('frames') as base:
        jobs = {'jobs': [{'url': base + PATH, 'out': str(tmp_path / f'{theme}.png'), 'width': width, 'theme': theme, 'wait': 'main', 'script': script} for theme in ('light', 'dark')]}
        (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@rendered.group
def test_the_run_strip_scrolls_inside_itself_at_320_and_fits_at_375(tmp_path):
    """52 parts do not fit a 320 px phone at 5 px each: the strip scrolls inside itself, never the page; at 375 px they fit."""
    chrome = rendered.chrome()
    narrow = ("const s=document.querySelector('.run-strip');if(!s)throw new Error('no strip');"
              "if(s.scrollWidth<=s.clientWidth)throw new Error('the strip should be wider than its box: '+s.scrollWidth+' vs '+s.clientWidth);"
              "if(!/auto|scroll/.test(getComputedStyle(s).overflowX))throw new Error('the strip does not scroll inside itself');"
              "if(document.documentElement.scrollWidth>innerWidth)throw new Error('the page scrolls sideways');")
    fits = ("const s=document.querySelector('.run-strip');if(s.scrollWidth>s.clientWidth)throw new Error('the strip should fit at 375: '+s.scrollWidth+' vs '+s.clientWidth);")
    with screen_gate.world('frames') as base:
        for width, script in ((320, narrow), (375, fits)):
            jobs = {'jobs': [{'url': base + PATH, 'out': str(tmp_path / f'{width}.png'), 'width': width, 'theme': 'light', 'wait': 'main', 'script': script}]}
            (tmp_path / f'jobs{width}.json').write_text(json.dumps(jobs))
            result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / f'jobs{width}.json')], capture_output=True, text=True)
            assert result.returncode == 0, str(width) + result.stdout + result.stderr


def test_building_the_frames_world_twice_gives_the_run_stock_the_same_ids_and_stamps(tmp_path):
    """The run's loose stock is saved after the layer's own fill thawed the clock and the uuids; it is stamped and numbered the same in every build."""
    def stock_rows(folder):
        store = folder / 'brickwork.db'
        folder.mkdir()
        screen_gate.build_store('frames', store)
        with database(store, read_only=True) as db:
            rows, places = run_rows(store)
            wanted = {(r['item_id'], r['color_id']) for r in rows[:10]}
            return sorted((r['id'], r['created_at'], r['updated_at'], r['item_id'], r['color_id'], r['storage_id'], r['quantity']) for r in db.execute(
                "SELECT * FROM stock WHERE kind='part' AND archived_at IS NULL") if (r['item_id'], r['color_id']) in wanted)
    first, second = stock_rows(tmp_path / 'a'), stock_rows(tmp_path / 'b')
    assert len(first) == 10 and first == second
    assert all(row[1].startswith('2026-10-12') for row in first), 'stamped with the demo clock, not the day of the build'


@rendered.group
@pytest.mark.parametrize('width,visible', [(1440, True), (390, False)])
def test_the_destination_dialog_has_a_visible_close_from_768_px_and_closes_only_on_the_backdrop(tmp_path, width, visible):
    """The visible card's dialog (not the first card's). A press at a point of the backdrop closes it; a press in its own padding, and a drag that starts inside, do not.
    The points are hit-tested with elementFromPoint (the backdrop answers as the dialog) and the events carry their coordinates; the capture has no mouse of its own."""
    chrome = rendered.chrome()
    script = ("document.head.insertAdjacentHTML('beforeend','<style>dialog,dialog[open]{animation:none!important;transition:none!important;opacity:1!important;transform:none!important;scale:none!important}</style>');"
              "const open=document.querySelector('[data-row]:not([hidden]) [data-run-found]');if(!open)throw new Error('no Found button on the visible card');"
              "const fire=(el,type,x,y)=>el.dispatchEvent(new MouseEvent(type,{bubbles:true,clientX:x,clientY:y}));"
              "const press=(from,to)=>{const a=document.elementFromPoint(...from),b=document.elementFromPoint(...to);if(a!==d||b!==d)throw new Error('the points should hit the dialog or its backdrop');fire(a,'mousedown',...from);fire(b,'mouseup',...to);fire(b,'click',...to);};"
              "open.click();await new Promise(r=>setTimeout(r,300));const d=document.querySelector('dialog[open]');if(!d||!d.closest('[data-row]:not([hidden])'))throw new Error('the visible card\\'s dialog did not open');"
              "const x=d.querySelector('[data-selector-close]'),cs=getComputedStyle(x),shown=cs.clipPath==='none'&&cs.position==='static'&&parseFloat(cs.height)>=40;"
              f"if(shown!=={str(visible).lower()})throw new Error('close control visible: '+shown+' at {width}');"
              "const r=d.getBoundingClientRect();if(r.width<100)throw new Error('the dialog has no box: '+r.width);"
              "const inside=[r.left+4,r.top+4],outsidePoint=[2,2];"
              "press(inside,inside);if(!d.open)throw new Error('a press in the dialog\\'s padding must not close it');"
              "press(inside,outsidePoint);if(!d.open)throw new Error('a drag that starts inside must not close it');"
              "press(outsidePoint,outsidePoint);if(d.open)throw new Error('a press on the backdrop should close the dialog');")
    with screen_gate.world('frames') as base:
        jobs = {'jobs': [{'url': base + PATH, 'out': str(tmp_path / 'x.png'), 'width': width, 'theme': 'light', 'wait': 'main', 'script': script}]}
        (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
