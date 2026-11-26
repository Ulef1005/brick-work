"""#551, frames 78 and 79: the Added via chip row of the loose-stock lists and the wishlist, the chip on each row and the filter behind them."""
import json
import subprocess
import os
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

from brickwork.core import collection, list_records
from brickwork.core.admin import database
from scripts import screen_gate
from tests import rendered

ROOT = Path(__file__).resolve().parents[1]


def listing(tmp_path, letter='P', **options):
    tmp_path.mkdir(exist_ok=True)
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store('frames-source', store)
    with database(store, read_only=True) as db:
        return collection.listing(db, letter, **options)


def second_origin(table, where='1'):
    """The demo worlds add everything by hand, and a Source row of one chip is hidden: give one `table` row of the running world a second origin."""
    with database(Path(os.environ['BW_DB_PATH'])) as db:
        trigger = f'{table}_added_via_fixed'
        sql = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (trigger,)).fetchone()[0]
        db.execute(f'DROP TRIGGER {trigger}')
        db.execute(f"UPDATE {table} SET added_via='rebrickable' WHERE id=(SELECT id FROM {table} WHERE archived_at IS NULL AND {where} ORDER BY id LIMIT 1)")
        db.execute(sql)
        db.commit()


def page(base, path):
    return BeautifulSoup(urllib.request.urlopen(base + path).read(), 'html.parser')


def test_a_grouped_row_names_each_origin_once_in_a_fixed_order():
    row = {}
    collection._row_sources(row, [None, 'hand', 'rebrickable', 'hand'])
    assert row['via'] == ['hand', 'rebrickable', 'before']
    assert row['source_chips'] == ['By hand', 'Added via Rebrickable sync', 'Before this release']


def test_a_row_with_nothing_owned_has_no_chip_and_counts_nowhere():
    row = {}
    collection._row_sources(row, [])
    assert row['via'] == [] and row['source_chips'] == []
    assert collection.source_chips([row, dict(via=['hand']), dict(via=['before'])])[0] == [('hand', 'By hand', 1), ('before', 'Before this release', 1)]


def test_an_emptied_stock_row_names_no_origin(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    store = tmp_path / 'brickwork.db'
    screen_gate.build_store('frames-source', store)
    with database(store) as db:
        row = next(r for r in collection.listing(db, 'P') if len(r['ids']) == 1 and r['quantity'])
        db.execute('UPDATE stock SET quantity=0 WHERE id=?', (row['ids'][0],))
        after = next((r for r in collection.listing(db, 'P') if r['ids'] == row['ids']), None)
        assert after is None or (not after.get('via') and not after.get('source_chips'))
        db.rollback()


def test_every_list_row_carries_the_origins_of_its_owned_instances(tmp_path):
    for letter, options in (('P', {}), ('M', {}), ('S', dict(wishes=True))):
        for row in listing(tmp_path / (letter + str(len(options))), letter, **options):
            owned = [row.get('added_via')] if options else [i.get('added_via') for i in row['instances'] if i.get('quantity') != 0]
            if not owned:                                                    # a part that is only inside sets
                assert not row.get('via') and not row.get('source_chips')
                continue
            assert row['via'] == sorted({v or 'before' for v in owned}, key=collection._source_order)
            assert len(row['source_chips']) == len(row['via'])


def test_the_chip_counts_are_list_rows_and_the_server_filter_matches_them(tmp_path):
    rows = listing(tmp_path)
    collection._row_sources(rows[0], ['rebrickable'])                                          # a second origin: one chip alone is not shown
    chips, lists = collection.source_chips(rows)
    assert lists == [] and len(chips) > 1
    for value, _label, count in chips:
        assert len(json.loads(str(list_records.payload(rows, filters={'via': value})))['rows']) == count


def test_the_pages_write_the_chip_row_once_there_are_two_origins_and_the_lot_sorter_never():
    with screen_gate.world('frames') as base:
        for path, table, where in (('/planning/wishlist', 'wish', '1'), ('/collection/P', 'stock', "kind='part'")):
            assert page(base, path).select_one('[data-bc-source]') is None, path                 # one origin: no row
            second_origin(table, where)
            row = page(base, path).select_one('[data-bc-source]')
            assert row.select_one('.bc-fchips-label').get_text() == 'Added via', path
            if path == '/planning/wishlist':
                assert row.select_one('input[data-bp-filter]')['data-bp-filter'] == 'via'
                offered = ['via:' + b['data-value'] for b in row.select('button')]
            else:
                assert row.select_one('input[data-bc-filter]')['data-bc-filter'] == 'via'
                offered = [b['data-bc-src'] for b in row.select('button')]
            assert len(offered) == 2 and 'via:rebrickable' in offered, (path, offered)
        assert page(base, '/workbench/lot-sorter').select_one('[data-bc-source]') is None


def render(tmp_path, path, script, table='wish', where='1'):
    chrome = rendered.chrome()
    with screen_gate.world('frames') as base:
        second_origin(table, where)
        jobs = {'jobs': [{'url': base + path, 'out': str(tmp_path / 'a.png'), 'width': 1440, 'theme': 'light', 'wait': 'main', 'script': script}]}
        (tmp_path / 'jobs.json').write_text(json.dumps(jobs))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome, str(tmp_path / 'jobs.json')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@rendered.group
def test_a_wishlist_chip_filters_the_rows_and_each_row_says_where_it_came_from(tmp_path):
    render(tmp_path, '/planning/wishlist',
           "const rows=()=>[...document.querySelectorAll('[data-bp-row]')].filter(n=>!n.hidden).length,wait=()=>new Promise(r=>setTimeout(r,300));"
           "return (async()=>{const n=rows(),b=document.querySelector('[data-bp-pick=\"via\"][data-value=\"rebrickable\"]');"
           "if(!n||!b)throw new Error('no wishes or no chip');"
           "if(document.querySelectorAll('[data-bp-row] .bc-source-chip').length!==n)throw new Error('chips on rows');"
           "b.click();await wait();if(rows()!==Number(b.querySelector('.mono').textContent))throw new Error('filtered: '+rows());"
           "b.click();await wait();if(rows()!==n)throw new Error('cleared: '+rows()+' of '+n);})();")


@rendered.group
def test_under_in_sets_the_row_is_gone_and_filters_nothing(tmp_path):
    render(tmp_path, '/collection/P',
           "const row=()=>document.querySelector('[data-bc-source]'),wait=()=>new Promise(r=>setTimeout(r,400));"
           "return (async()=>{document.querySelector('[data-bc-src=\"via:rebrickable\"]').click();await wait();"
           "const s=document.querySelector('[data-bc-filter=\"stock\"]');s.value='sets';s.dispatchEvent(new Event('change',{bubbles:true}));await wait();"
           "if(!row().hidden||row().querySelector('input').value)throw new Error('still filtering under In sets');"
           "if(row().getClientRects().length)throw new Error('still drawn');"
           "if(!document.querySelector('.bc-card'))throw new Error('nothing listed under In sets');})();", table='stock', where="kind='part'")
