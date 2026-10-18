"""UI-lists (design audit v1.3, tracking issues 18 and 21): Collection list pages against frames 1c, 7a, 12h and 12i."""
from pathlib import Path
import json
import shutil
import subprocess

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin
from brickwork.core.list_records import FIELDS, payload
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps

ROOT = Path(__file__).resolve().parent.parent
FILTERS = 'type condition status colour problem storage place flags lot duplicates stock category theme year'.split()


def seed(db):
    db.execute("INSERT OR IGNORE INTO colors(color_id,name,rgb) VALUES(11,'Black','05131D')")
    db.execute("INSERT OR IGNORE INTO flags(id,name,kind,shown_on_grid) VALUES('t-display','Display','tag',1)")
    db.execute("INSERT OR IGNORE INTO flags(id,name,kind,shown_on_grid) VALUES('t-box','Box present','status',0)")
    db.execute("INSERT OR IGNORE INTO lots(id,name) VALUES('lot-1','Lot 1')")
    db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name,year) VALUES('S','6080-1',?,1984)", ("King's Castle",))
    db.execute("INSERT OR IGNORE INTO item_properties(item_type,item_no,key,source,value) VALUES('S','6080-1','theme','rebrickable','Castle')")
    db.execute("INSERT OR IGNORE INTO item_properties(item_type,item_no,key,source,value) VALUES('S','6080-1','subtheme','rebrickable','Lion Knights')")
    db.execute("INSERT INTO copies(id,item_type,set_no,condition,completeness,completeness_source) VALUES('c-6080','S','6080-1','U','C','manual')")
    db.execute("INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES('copy','c-6080','t-display')")
    db.execute("INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES('copy','c-6080','t-box')")
    for i in range(3):
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P',?,?)", (f'p{i}', f'Plate {i}'))
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,lot_id,damaged) VALUES(?,'P',?,11,5,'U',?,?)",
                   (f'ls-{i}', f'p{i}', 'lot-1' if i == 0 else None, 2 if i == 1 else 0))
    db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('M','fig-a','Figure A')")
    db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition) VALUES('lm-a','M','fig-a',1,'U')")


def hidden_inside(element, panel):
    """True when a wrapper between the element and the (itself hidden) panel carries the hidden attribute."""
    return any(p.has_attr('hidden') for p in element.parents if p is not panel and panel in p.parents)


def page(app, route):
    return BeautifulSoup(logged_in(app).get(route).data, 'html.parser')


def test_list_records_carry_subtheme_and_tags_only_as_display_fields(app, bw):
    from brickwork.core import collection
    with admin.database(bw) as db, db:
        seed(db)
        rows = collection.listing(db, 'S')
    assert FIELDS[-2:] == ['subtheme', 'tags']
    data = json.loads(payload(rows))
    index = {name: i for i, name in enumerate(data['fields'])}
    castle = next(r for r in data['rows'] if r.get(str(index['number'])) == '6080-1')
    assert castle[str(index['subtheme'])] == 'Lion Knights'
    # Only tag flags travel as tags; status flags such as "Box present" stay in flags.
    assert castle[str(index['tags'])] == ['Display']
    assert 'Box present' in castle[str(index['flags'])]


def test_headlines_for_parts_and_minifigures(app, bw):
    with admin.database(bw) as db, db:
        seed(db)
    parts = page(app, '/collection/P')
    head = parts.select_one('.bc-heading')
    assert head.select_one('h1').get_text() == '1 part has damaged pieces' or ' have damaged pieces' in head.select_one('h1').get_text()
    assert 'entries' in head.select_one('.secondary').get_text() and 'in 1 lot' in head.select_one('.secondary').get_text()
    figures = page(app, '/collection/M')
    assert 'loose minifigure' in figures.select_one('.bc-heading h1').get_text()
    assert ' in sets' in figures.select_one('.bc-heading .secondary').get_text()
    # Other kinds keep the plain page name.
    assert page(app, '/collection/O').select_one('.bc-heading h1').get_text() == 'Boxes'
    # A list without damaged parts says so instead of showing a zero count in a sentence.
    with admin.database(bw) as db, db:
        db.execute('UPDATE loose_stock SET damaged=0')
        db.execute('UPDATE copy_parts SET damaged=0')
    assert page(app, '/collection/P').select_one('.bc-heading h1').get_text() == 'No parts have damaged pieces'


@pytest.mark.parametrize('kind', ['P', 'M', 'I', 'O', 'G'])
def test_filter_panel_uses_chips_and_pickers_and_keeps_every_filter(app, bw, kind):
    with admin.database(bw) as db, db:
        seed(db)
    panel = page(app, '/collection/' + kind).select_one('[data-bc-panel]')
    names = {s['data-bc-filter'] for s in panel.select('select[data-bc-filter]')}
    assert set(FILTERS) <= names, set(FILTERS) - names
    # Short option sets are chips or segmented controls; their native dropdowns are hidden backing controls.
    assert [b['data-value'] for b in panel.select('[data-bc-pick=condition]')] == ['N', 'U', 'D']
    assert [b['data-value'] for b in panel.select('[data-bc-pick=problem]')] == ['damaged', 'missing']
    assert [b['data-value'] for b in panel.select('[data-bc-pick=stock]')] == ['loose', 'sets']
    for name in ('condition', 'problem', 'stock', 'status', 'type'):
        select = panel.select_one(f'select[data-bc-filter={name}]')
        assert hidden_inside(select, panel), name
    # Long option sets keep a picker row.
    rows = {r.select_one('select')['data-bc-filter'] for r in panel.select('.bc-theme-row')}
    assert {'theme', 'storage', 'year'} <= rows and (('colour' in rows) == (kind == 'P'))
    # 12i: Group by and Select mode sit in the View section, outside Other filters.
    view = panel.select_one('.bc-view-group')
    assert not view.find_parent('details')
    assert [b.get_text() for b in view.select('[data-bc-group-pick]')] == ['None', 'Theme', 'Storage', 'Year', 'Place', 'Lot']
    assert view.select_one('[data-bc-select][role=switch]') and view.select_one('select[data-bc-group]')
    assert not panel.select_one('details.bc-other-filters').select('[data-bc-select],[data-bc-group]')
    other = {s['data-bc-filter'] for s in panel.select_one('details.bc-other-filters').select('select[data-bc-filter]') if not hidden_inside(s, panel)}
    assert {'place', 'flags', 'lot', 'category'} <= other


def test_filter_chips_apply_the_same_filter_values_as_the_old_dropdowns(app, bw):
    """Each chip drives the existing select of the same name, so URL parameters and saved state keep working."""
    panel = page(app, '/collection/P').select_one('[data-bc-panel]')
    for pick in panel.select('[data-bc-pick]'):
        select = panel.select_one(f'select[data-bc-filter={pick["data-bc-pick"]}]')
        assert select is not None, pick
        assert pick['data-value'] in {o.get('value', o.get_text()) for o in select.select('option')}, pick


def test_parts_list_is_a_table_by_default_with_quick_chips_and_by_lot(app, bw):
    with admin.database(bw) as db, db:
        seed(db)
    soup = page(app, '/collection/P')
    main = soup.select_one('[data-bc-list][data-bc-main]')
    assert main['data-bc-default-group'] == 'lot' and main['data-bc-page-size'] == '15'
    assert soup.select_one('[data-bc-rows]')['data-view'] == 'list'
    assert [s.get_text() for s in soup.select('.bc-table-head span')] == ['', 'Colour · part', 'Damaged', 'Lot', 'Used price', 'Qty']
    chips = {b['data-bc-quick']: b.get_text(' ', strip=True) for b in soup.select('.bc-quick-chips button')}
    data = json.loads(soup.select_one('script[data-bc-records]').string)
    index = {name: i for i, name in enumerate(data['fields'])}
    total = len(data['rows'])
    damaged = sum(1 for r in data['rows'] if r.get(str(index['damaged'])))
    lots = [r.get(str(index['lot']), ['null']) for r in data['rows']]
    lotted = sum(1 for x in lots if any(v != 'null' for v in x))
    unlotted = sum(1 for x in lots if 'null' in x)
    assert damaged >= 1 and lotted >= 1
    assert chips == {'': f'All {total}', 'problem:damaged': f'Damaged {damaged}', 'lot:any': f'In lots {lotted}', 'lot:null': f'No lot {unlotted}'}
    toggle = [b.get_text() for b in soup.select('.bc-flat-switch [data-bc-group-pick]')]
    assert toggle == ['Flat', 'By lot']
    # The grid stays as an option; other lists keep the grid by default and have no table.
    assert [b['data-bc-view'] for b in soup.select('.bc-view-switch button')] == ['grid', 'list']
    figures = page(app, '/collection/M')
    assert figures.select_one('[data-bc-rows]')['data-view'] == 'grid'
    assert not figures.select('.bc-table-head, .bc-quick-chips, .bc-flat-switch')


def test_minifigure_headline_counts_quantities_and_placeholders_get_status_chips(app, bw):
    with admin.database(bw) as db, db:
        seed(db)
        db.execute("UPDATE loose_stock SET quantity=4 WHERE id='lm-a'")
    soup = page(app, '/collection/M')
    total = db_sum = None
    with admin.database(bw, read_only=True) as db:
        total = db.execute("SELECT coalesce(sum(quantity),0) FROM loose_stock WHERE item_type='M' AND archived_at IS NULL").fetchone()[0]
    assert soup.select_one('.bc-heading h1').get_text() == f'{total} loose minifigures'
    placeholders = page(app, '/collection/%3F').select_one('[data-bc-panel]')
    assert [b['data-value'] for b in placeholders.select('[data-bc-pick=status]')] == ['S', 'C', 'I', 'unknown']
    assert not page(app, '/collection/P').select('[data-bc-pick=status]')


def test_lot_filter_matches_between_the_api_filter_and_the_list_script():
    """One rule for lot: any, null and a specific id behave the same in listing.filter_rows and bw-collection.js."""
    from brickwork.core.listing import filter_rows
    node = shutil.which('node')
    if not node:
        pytest.skip('node not installed')
    rows = [{'number': 'a', 'lot': ['null']}, {'number': 'b', 'lot': ['lot-1']}, {'number': 'c', 'lot': ['null', 'lot-2']}, {'number': 'd'}]
    script = (
        "const fs=require('node:fs'),vm=require('node:vm');const window={};"
        "const ctx={window,document:{querySelector:()=>null}};"
        "vm.runInNewContext(fs.readFileSync('static/web/toni/formatting.js','utf8')+fs.readFileSync('static/web/toni/bw-collection.js','utf8'),ctx);"
        "const rows=JSON.parse(process.argv[1]);const out={};"
        "for(const v of ['any','null','lot-1','lot-2'])out[v]=window.BrickCollection.filterRows(rows.map(r=>({lot:['null'],...r})),'',{lot:v}).map(r=>r.number);"
        "console.log(JSON.stringify(out));")
    js = json.loads(subprocess.run([node, '-e', script, json.dumps(rows)], check=True, capture_output=True, text=True, cwd=ROOT).stdout)
    # The script's record decoder defaults an absent lot to ['null']; the API rows carry the same default.
    api = {v: sorted(r['number'] for r in filter_rows([dict({'lot': ['null']}, **r) for r in rows], filters={'lot': v})) for v in js}
    assert {k: sorted(v) for k, v in js.items()} == api
    assert api['any'] == ['b', 'c'] and api['null'] == ['a', 'c', 'd']


def test_default_rows_of_parts_and_minifigures_are_unchanged(app, bw):
    """Decision 20 is open: the list still carries exactly the records it carried before."""
    with admin.database(bw) as db, db:
        seed(db)
    for kind in 'PM':
        data = json.loads(page(app, '/collection/' + kind).select_one('script[data-bc-records]').string)
        index = data['fields'].index('number')
        assert all(str(index) in row for row in data['rows']) and data['rows']


def test_set_card_sources_and_markup_contract():
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    region = css[css.index('===== UI-lists'):]
    assert 'display:contents' not in region
    assert '.bc-card-foot:has(>.bc-foot-main)' in region and '.bc-tag ' in region
    assert 'min-height:0' in region[region.index('.bc-lot-link'):].split('}')[0], 'link height trap is reset for table links'
    js = (ROOT / 'static/web/toni/bw-collection.js').read_text()
    assert "'Not checked'" in js and "'Unknown'" not in js
    assert "'Load more'" not in (ROOT / 'templates/web/toni/web/bw_collection.html').read_text()


def test_lists_runtime_harness():
    node = shutil.which('node')
    if not node:
        pytest.skip('node not installed')
    done = subprocess.run([node, str(ROOT / 'tests/toni_bw_collection_lists_runtime.cjs')], check=True, capture_output=True, text=True, cwd=ROOT)
    assert 'lists runtime ok' in done.stdout
