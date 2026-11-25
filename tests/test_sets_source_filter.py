"""#551, frame 45: the Source chip rows of the Sets page (Added via, Last synced from), counted in sets, and the filter behind them."""
import json
import subprocess
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

from brickwork.core import collection, list_records
from brickwork.core.admin import database
from brickwork.core.listing import filter_rows
from scripts import screen_gate
from tests import rendered

ROOT = Path(__file__).resolve().parents[1]


def sets(tmp_path):
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store('frames-source', store)           # seven sets; copy 1 of 7213-1 was pulled from Rebrickable's "Main collection"
    with database(store, read_only=True) as db:
        return collection.listing(db, 'S')


def test_the_chips_count_sets_not_copies_and_name_the_list(tmp_path):
    via, lists = collection.source_chips(sets(tmp_path))
    assert via == [('hand', 'By hand', 7), ('rebrickable', 'Rebrickable sync', 1)]      # 7213-1 has a hand copy and a pulled copy: it counts under both
    assert lists == [('rebrickable|main', 'Rebrickable · Main collection', 1)]


def test_a_row_without_a_recorded_origin_reads_before_this_release():
    row = dict(via=['before'], list=[], list_labels={})
    assert collection.source_chips([row])[0] == [('before', 'Before this release', 1)]


def test_the_server_side_filter_matches_the_two_new_fields(tmp_path):
    rows = sets(tmp_path)
    payload = json.loads(str(list_records.payload(rows, filters={'via': 'rebrickable'})))
    assert len(payload['rows']) == 1
    assert len(json.loads(str(list_records.payload(rows, filters={'list': 'rebrickable|main'})))['rows']) == 1
    assert len(json.loads(str(list_records.payload(rows, filters={'list': 'rebrickable|nope'})))['rows']) == 0
    assert len(json.loads(str(list_records.payload(rows, filters={'via': 'hand', 'list': 'rebrickable|main'})))['rows']) == 1


def test_the_page_writes_one_button_per_chip_with_its_count():
    with screen_gate.world('frames-source') as base:
        page = BeautifulSoup(urllib.request.urlopen(base + '/collection/sets').read(), 'html.parser')
    rows = page.select('.bp-fchips')
    assert [r.select_one('.bp-fchips-label').get_text() for r in rows] == ['Added via', 'Last synced from']
    assert [b.get_text(' ', strip=True) for b in rows[0].select('button')] == ['By hand 7', 'Rebrickable sync 1']
    assert [b['data-bc-src'] for b in rows[1].select('button')] == ['list:rebrickable|main']
    assert [r.select_one('input[data-bc-filter]')['data-bc-filter'] for r in rows] == ['via', 'list']


@rendered.group
def test_a_chip_filters_the_tiles_and_a_second_press_clears_it(tmp_path):
    chrome = rendered.chrome()
    script = ("const tiles=()=>document.querySelectorAll('.stile').length,wait=()=>new Promise(r=>setTimeout(r,300));"
              "return (async()=>{const n=tiles(),b=document.querySelector('[data-bc-src=\"via:rebrickable\"]');"
              "b.click();await wait();if(tiles()!==1||b.getAttribute('aria-pressed')!=='true')throw new Error('pressed: '+tiles());"
              "document.querySelector('[data-bc-src=\"list:rebrickable|main\"]').click();await wait();if(tiles()!==1)throw new Error('combined: '+tiles());"
              "b.click();await wait();document.querySelector('[data-bc-src=\"list:rebrickable|main\"]').click();await wait();"
              "if(tiles()!==n)throw new Error('cleared: '+tiles()+' of '+n);})();")
    with screen_gate.world('frames-source') as base:
        jobs = {'jobs': [{'url': base + '/collection/sets', 'out': str(tmp_path / 'a.png'), 'width': 1440, 'theme': 'light', 'wait': 'main', 'script': script}]}
        (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@rendered.group
def test_a_filter_no_chip_offers_is_dropped_not_kept_invisible(tmp_path):
    chrome = rendered.chrome()
    script = ("if(document.querySelectorAll('.stile').length!==7)throw new Error('tiles: '+document.querySelectorAll('.stile').length);")
    with screen_gate.world('frames-source') as base:
        jobs = {'jobs': [{'url': base + '/collection/sets?via=gone&list=rebrickable%7Cold', 'out': str(tmp_path / 'a.png'), 'width': 1440, 'theme': 'light', 'wait': 'main', 'script': script}]}
        (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_list_recorded_without_its_name_takes_the_name_another_row_has():
    rows = [dict(via=['hand'], list=['rebrickable|42'], list_labels={'rebrickable|42': 'Rebrickable'}),
            dict(via=['hand'], list=['rebrickable|42'], list_labels={'rebrickable|42': 'Rebrickable · Main collection'})]
    assert collection.source_chips(rows)[1] == [('rebrickable|42', 'Rebrickable · Main collection', 2)]


def test_the_script_combines_the_two_rows_and_a_pressed_chip_clears_its_row():
    js = (ROOT / 'static/web/toni/bw-collection.js').read_text()
    assert "data-bc-src" in js and "control.value=on?'':v" in js


def test_the_source_rows_sit_above_the_storage_row():
    html = (ROOT / 'templates/web/toni/web/bw_sets.html').read_text()
    assert html.index('data-bp-source>') < html.index('data-bp-storage-row>')       # frame 45, 390 wide
