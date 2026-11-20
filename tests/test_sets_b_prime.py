"""The Sets page of the B′ frames (R3-01, #494): the bar of each copy, the storage index, the page's markup, and a phone that never scrolls sideways."""
import json
from pathlib import Path
import subprocess
import urllib.request

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection
from brickwork.core.admin import database
from scripts import screen_gate
from tests import rendered

ROOT = Path(__file__).resolve().parents[1]


def built(tmp_path, name):
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store(name, store)
    return store


def test_each_copy_has_its_bar_and_the_bars_add_up_to_the_heading(tmp_path):
    with database(built(tmp_path, 'frames'), read_only=True) as db:
        rows = {r['item_no']: r for r in collection.listing(db, 'S')}
    assert rows['7213-1']['bars'] == [[365, 10, 375, 0], [130, 12, 375, 0]]      # two copies, two bars; the second still has pieces to check
    assert rows['7938-1']['bars'] == [[643, 14, 657, 0]]
    assert rows['31120-1']['bars'] == [[1426, 0, 1426, 0]]                        # "Set is checked" and nothing missing: complete
    assert rows['8043-1']['bars'] == [[0, 0, 1123, 0]]                            # never checked
    assert rows['10254-1']['statuses'] == ['sealed']
    assert sum(b[1] for r in rows.values() for b in r['bars'] if b) == sum(r['missing_parts'] for r in rows.values()) == 69


def test_a_copy_without_a_part_list_has_no_bar(tmp_path):
    with database(built(tmp_path, 'frames')) as db:
        copy = db.execute('SELECT id FROM copy ORDER BY id LIMIT 1').fetchone()[0]
        assert copy in collection._copy_bars(db, [copy])
        db.execute('UPDATE copy_part SET retired_at=? WHERE copy_id=?', ('2026-10-12T00:00:00.000Z', copy))
        assert collection._copy_bars(db, [copy]) == {}                               # no live line: no entry, the page says "No part list"


def test_the_storage_index_lists_the_storages_with_copies_in_the_frames_order(tmp_path):
    with database(built(tmp_path, 'frames'), read_only=True) as db:
        index = collection.storage_index(collection.listing(db, 'S'), collection.options(db)['storages'])
    assert [(s['code'], s['name'], s['copies'], s['sets']) for s in index] == [
        ('S-0002', 'Shelf A2 – Town', 4, 3), ('S-0001', 'Shelf A1 – Castle', 2, 2), ('S-0005', 'Technic crate', 1, 1), ('S-0004', 'Display case', 1, 1)]


def test_no_storage_set_gives_an_empty_index(tmp_path):
    with database(built(tmp_path, 'frames-no-storage'), read_only=True) as db:
        assert collection.storage_index(collection.listing(db, 'S'), collection.options(db)['storages']) == []


def fetch(base, path):
    with urllib.request.urlopen(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


@rendered.group
def test_the_page_has_drawers_ledger_tabs_and_the_index_only_where_storage_is_set():
    with screen_gate.world('frames') as base:
        page = fetch(base, '/collection/sets')
        assert page.select_one('#bw-collection[data-bp-sets]') and page.select_one('.bp-sets.b-prime')
        assert [b.get_text(strip=True) for b in page.select('.bp-head-actions .seg button')] == ['Drawers', 'Ledger']
        assert [b['data-bc-view'] for b in page.select('.bp-head-actions .seg button')] == ['grid', 'list']
        assert [b.get_text(' ', strip=True) for b in page.select('.stabs button')] == ['All 7', 'Incomplete 3', 'Not checked 2', 'Complete 1', 'Sealed 1']
        assert [b.get_text(' ', strip=True) for b in page.select('.bp-index .idx')][:2] == ['All Every storage 8', 'S-0002 Shelf A2 – Town 4']
        assert page.select_one('h1').get_text() == '3 of 7 sets incomplete'
        assert '8 copies · 69 parts missing in view' in page.select_one('.bp-sub').get_text()
        assert page.select_one('[data-bc-filters]') and page.select_one('[data-bc-sort-open]') and page.select_one('[data-bc-search]')
        assert page.select_one('[data-bc-default-group]')['data-bc-default-group'] == 'storage'
    with screen_gate.world('frames-no-storage') as base:
        page = fetch(base, '/collection/sets')
        assert page.select_one('.bp-sets[data-bp-stored="false"]') and not page.select('.bp-index') and not page.select('[data-bp-storage-row]')


@rendered.group
def test_the_other_kinds_keep_their_page():
    with screen_gate.world('frames') as base:
        for kind in 'MPI':
            page = fetch(base, f'/collection/{kind}')
            assert not page.select('[data-bp-sets], .bp-sets'), kind
            assert page.select_one('header.bc-heading') and page.select('.bc-toolbar'), kind


@rendered.group
@pytest.mark.parametrize('width', [320, 375])
def test_the_page_never_scrolls_sideways_below_390(tmp_path, width):
    """Each element handles its own width (Ulf, 2026-11-20): a long free-text name and a long storage name are put in, the page must still fit."""
    chrome = rendered.chrome()
    script = ("document.querySelectorAll('.nm').forEach(n=>n.textContent='A very long free text set name without any break '+'x'.repeat(60));"
              "document.querySelectorAll('.bp-tape-name').forEach(n=>n.textContent='A storage called '+'y'.repeat(70));"
              "if(document.documentElement.scrollWidth>innerWidth)throw new Error('sideways: '+document.documentElement.scrollWidth+' > '+innerWidth);")
    with screen_gate.world('frames') as base:
        jobs = {'jobs': [{'url': base + '/collection/sets', 'out': str(tmp_path / f'{theme}.png'), 'width': width, 'theme': theme, 'wait': 'main', 'script': script}
                         for theme in ('light', 'dark')]}
        (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
