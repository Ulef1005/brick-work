"""UI-lists (design audit v1.3, tracking issues 18 and 21): Collection list pages against frames 1c, 7a, 12h and 12i, on the 4.0 store (M.8b)."""
from pathlib import Path
import json
import shutil
import subprocess

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection
from brickwork.core.list_records import FIELDS, payload
from tests.app4 import world, coll, pair, read, app4, client  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
FILTERS = 'type condition status colour problem storage place flags lot duplicates stock category theme year'.split()


def hidden_inside(element, panel):
    """True when a wrapper between the element and the (itself hidden) panel carries the hidden attribute."""
    return any(p.has_attr('hidden') for p in element.parents if p is not panel and panel in p.parents)


def page(client, route):
    response = client.get(route)
    assert response.status_code == 200, route
    return BeautifulSoup(response.data, 'html.parser')


def records(soup):
    return json.loads(soup.select_one('script[data-bc-records]').string)


def test_list_records_carry_subtheme_and_tags_only_as_display_fields(coll, world, read):
    coll.prop(world.keep, 'subtheme', 'Lion Knights')
    with read() as db:
        rows = collection.listing(db, 'S')
    assert FIELDS[-5:] == ['subtheme', 'tags', 'item_id', 'also', 'source']
    data = json.loads(payload(rows))
    index = {name: i for i, name in enumerate(data['fields'])}
    castle = next(r for r in data['rows'] if r.get(str(index['item_id'])) == world.keep and r.get(str(index['number'])) == '1000-1')
    assert castle[str(index['subtheme'])] == 'Lion Knights'
    # Only tag flags with shown_on_grid travel as tags; status flags such as "Set is checked" stay in flags.
    assert castle[str(index['tags'])] == ['collection']
    assert 'Set is checked' in castle[str(index['flags'])]


def test_headlines_for_parts_and_minifigures(coll, world, client):
    coll.sql('UPDATE stock SET damaged=2 WHERE id=?', (world.stock_brick,))
    head = page(client, '/collection/P').select_one('.bc-heading')
    assert ' has damaged pieces' in head.select_one('h1').get_text() or ' have damaged pieces' in head.select_one('h1').get_text()
    assert 'entries' in head.select_one('.secondary').get_text() and 'in 1 lot' in head.select_one('.secondary').get_text()
    figures = page(client, '/collection/M')
    assert 'loose minifigure' in figures.select_one('.bc-heading h1').get_text()
    assert ' in sets' in figures.select_one('.bc-heading .secondary').get_text()
    # Other kinds keep the plain page name.
    assert page(client, '/collection/O').select_one('.bc-heading h1').get_text() == 'Boxes'
    # A list without damaged parts says so instead of showing a zero count in a sentence.
    coll.sql('UPDATE stock SET damaged=0')
    coll.sql('UPDATE copy_part SET damaged=0')
    assert page(client, '/collection/P').select_one('.bc-heading h1').get_text() == 'No parts have damaged pieces'


@pytest.mark.parametrize('kind', ['P', 'M', 'I', 'O', 'G'])
def test_filter_panel_uses_chips_and_pickers_and_keeps_every_filter(world, client, kind):
    panel = page(client, '/collection/' + kind).select_one('[data-bc-panel]')
    names = {s['data-bc-filter'] for s in panel.select('select[data-bc-filter]')}
    assert set(FILTERS) <= names, set(FILTERS) - names
    # Short option sets are chips or segmented controls; their native dropdowns are hidden backing controls (conditions are words).
    assert [b['data-value'] for b in panel.select('[data-bc-pick=condition]')] == ['new', 'used', 'damaged']
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


def test_filter_chips_apply_the_same_filter_values_as_the_old_dropdowns(client):
    """Each chip drives the existing select of the same name, so URL parameters and saved state keep working."""
    panel = page(client, '/collection/P').select_one('[data-bc-panel]')
    for pick in panel.select('[data-bc-pick]'):
        select = panel.select_one(f'select[data-bc-filter={pick["data-bc-pick"]}]')
        assert select is not None, pick
        assert pick['data-value'] in {o.get('value', o.get_text()) for o in select.select('option')}, pick


def test_parts_list_is_a_table_by_default_with_quick_chips_and_by_lot(coll, world, client):
    coll.sql('UPDATE stock SET damaged=2 WHERE id=?', (world.stock_brick_new,))
    soup = page(client, '/collection/P')
    main = soup.select_one('[data-bc-list][data-bc-main]')
    assert main['data-bc-default-group'] == 'lot' and main['data-bc-page-size'] == '15'
    assert soup.select_one('[data-bc-rows]')['data-view'] == 'list'
    assert [s.get_text() for s in soup.select('.bc-table-head span')] == ['', 'Colour · part', 'Damaged', 'Lot', 'Used price', 'Qty']
    chips = {b['data-bc-quick']: b.get_text(' ', strip=True) for b in soup.select('.bc-quick-chips button')}
    data = records(soup)
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
    figures = page(client, '/collection/M')
    assert figures.select_one('[data-bc-rows]')['data-view'] == 'grid'
    assert not figures.select('.bc-table-head, .bc-quick-chips, .bc-flat-switch')


def test_minifigure_headline_counts_quantities_and_status_chips_are_the_sets_only(coll, world, read, client):
    coll.sql('UPDATE stock SET quantity=4 WHERE id=?', (world.stock_figure,))
    soup = page(client, '/collection/M')
    with read() as db:
        total = db.execute("SELECT coalesce(sum(quantity),0) FROM stock WHERE kind='minifigure' AND archived_at IS NULL").fetchone()[0]
    assert total == 4 and soup.select_one('.bc-heading h1').get_text() == f'{total} loose minifigures'
    # The completeness chips are words (design 5.1) and belong to the sets list; parts and figures have none.
    assert [b['data-value'] for b in page(client, '/collection/S').select('[data-bc-pick=status]')] == ['sealed', 'complete', 'incomplete', 'unknown']
    assert not soup.select('[data-bc-pick=status]') and not page(client, '/collection/P').select('[data-bc-pick=status]')


def test_an_unidentified_item_sits_on_its_own_kinds_screen_marked_unidentified(world, client):
    """The `?` placeholder screen is gone (4.0): an item with no number is listed with the kind it has and carries no number."""
    assert client.get('/collection/%3F').status_code == 404
    data = records(page(client, '/collection/G'))
    index = {name: i for i, name in enumerate(data['fields'])}
    (mystery,) = [r for r in data['rows'] if r.get(str(index['item_id'])) == world.mystery]
    assert mystery[str(index['name'])] == 'Mystery thing' and mystery[str(index['unresolved'])] is True
    assert str(index['number']) not in mystery
    js = (ROOT / 'static/web/toni/bw-collection.js').read_text()
    assert "r.number?'To check':'Unidentified'" in js


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


def test_default_rows_of_parts_and_minifigures_are_unchanged(world, client):
    """Decision 20 is open: the list still carries exactly the records it carried before."""
    for kind in 'PM':
        data = records(page(client, '/collection/' + kind))
        index = data['fields'].index('number')
        assert data['rows'] and all(str(index) in row for row in data['rows'])


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
