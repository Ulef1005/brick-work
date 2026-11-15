"""Part groups on the order list, the print list and the pull list (#315, part 3). The set page and the checker are in `test_part_groups.py`."""
from bs4 import BeautifulSoup
import pytest

from brickwork.core import part_groups
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)
from tests.test_bw_order_missing_225 import SETTINGS, URL


def categorise(coll, **by_part):
    """Give the main.item of each part (Rebrickable number) the category name."""
    for number, name in by_part.items():
        item = coll.project(coll.item('parts', number))
        coll.db.execute('UPDATE main.item SET category_name=? WHERE id=?', (name, item))
    coll.db.commit()


def order_scene(coll):
    """Two copies: used 3001 (2 missing) and 3023 (1), 3004 (3) plus a missing figure; the categories make three groups and a part with none."""
    for key, value in SETTINGS.items():
        coll.setting(key, value)
    copy = coll.add_copy('1000-1', condition='used')
    coll.mark(copy, '3001', '4', missing=2)
    coll.mark(copy, '3023', '15', missing=1)
    coll.mark_figure(copy, 'fig-000004', missing=1)
    return copy


def soup_of(client, url=URL, **query):
    response = client.get(url, query_string=query)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def names(soup):
    return [s['data-bw-section'] for s in soup.select('[data-bw-section]')]


# ---------- the shared helpers ----------

def test_sections_are_ordered_outside_rows_stay_out_and_none_is_flat():
    rows = [dict(group='Tiles', quantity=2), dict(group='Bricks', quantity=3), dict(group=None, quantity=9), dict(group='Other', quantity=1), dict(group='Bricks', quantity=4)]
    outside, found = part_groups.sections(rows, 'grouped')
    assert [r['quantity'] for r in outside] == [9]
    assert [(g['name'], g['lines'], g['pieces']) for g in found] == [('Bricks', 2, 7), ('Tiles', 1, 2), ('Other', 1, 1)]
    flat, none = part_groups.sections(rows, 'none')
    assert flat == rows and none == []


def test_mode_reads_the_setting_and_ignores_a_bad_value(coll):
    assert part_groups.mode(coll.db) == 'grouped'
    for value in ('bricklink', 'none'):
        coll.setting('part_list_grouping', value)
        assert part_groups.mode(coll.db) == value
    coll.setting('part_list_grouping', 'bogus')
    assert part_groups.mode(coll.db) == 'grouped'


def test_annotate_gives_the_group_of_the_category_and_leaves_non_parts_out(coll):
    categorise(coll, **{'3001': 'Bricks', '3023': 'Made up'})
    rows = [dict(item_id=coll.project(coll.item('parts', '3001'))), dict(item_id=coll.project(coll.item('parts', '3023'))), dict(item_id=coll.project(coll.item('minifigs', 'fig-000004')), figure=True)]
    part_groups.annotate(coll.db, rows, 'grouped', is_part=lambda r: not r.get('figure'))
    assert [r['group'] for r in rows] == ['Bricks', 'Other', None]
    part_groups.annotate(coll.db, rows, 'bricklink', is_part=lambda r: not r.get('figure'))
    assert [r['group'] for r in rows] == ['Bricks', 'Made up', None]
    part_groups.annotate(coll.db, rows, 'none')
    assert [r['group'] for r in rows] == [None, None, None]


# ---------- order missing parts ----------

def test_order_lines_sit_under_part_groups_all_open(coll, client):
    order_scene(coll)
    categorise(coll, **{'3001': 'Bricks', '3023': 'Plates'})
    soup = soup_of(client)
    assert names(soup) == ['Bricks', 'Plates']
    assert all(s.has_attr('open') for s in soup.select('[data-bw-section]'))
    [bricks, plates] = soup.select('[data-bw-section]')
    assert bricks.select_one('.bw-sec-head').get_text(' ', strip=True).endswith('1 line · 2 pieces')
    assert plates.select_one('.bw-sec-count').text == '1 line · 1 piece'
    assert len(soup.select('[data-bw-section] .oo-line')) == 2
    figure = soup.select('.oo-lines[data-oo-lines] > .oo-line')[0]
    assert 'fig-000004' in figure.get_text() and not figure.find_parent('details')      # a whole figure stays outside the groups, first
    assert soup.select_one('[data-bw-sections-actions]').has_attr('hidden')
    assert [a.text for a in soup.select('[data-bw-sections-actions] a')] == ['Expand all', 'Collapse all']
    assert soup.select_one('[data-bw-sections]')['data-bw-sections-key'] == 'all'
    assert soup.select_one('.oo-tab.on, .oo-tab[aria-current=page]')                     # the tabs, totals and chips are the page as before
    assert len(soup.select('.oo-sc')) == 6


def test_order_other_appears_only_when_a_part_has_no_category(coll, client):
    order_scene(coll)
    categorise(coll, **{'3001': 'Bricks', '3023': 'Plates'})
    assert 'Other' not in names(soup_of(client))
    categorise(coll, **{'3023': 'Made up'})
    assert names(soup_of(client)) == ['Bricks', 'Other']
    coll.setting('part_list_grouping', 'bricklink')
    assert names(soup_of(client)) == ['Bricks', 'Made up']


def test_order_tab_groups_only_its_own_lines_and_keeps_its_key(coll, client):
    order_scene(coll)
    categorise(coll, **{'3001': 'Bricks', '3023': 'Plates'})
    soup = soup_of(client, tab='bl', sel='1', step='review', copy=[coll.db.execute('SELECT id FROM copy').fetchone()[0]])
    assert soup.select_one('[data-bw-sections]')['data-bw-sections-key'] == 'bl'
    assert names(soup) == ['Bricks', 'Plates']
    assert names(soup_of(client, tab='pab')) == []


def test_order_with_no_grouping_is_the_flat_list(coll, client):
    order_scene(coll)
    categorise(coll, **{'3001': 'Bricks', '3023': 'Plates'})
    coll.setting('part_list_grouping', 'none')
    soup = soup_of(client)
    assert not soup.select('[data-bw-section], [data-bw-sections], [data-bw-sections-actions]')
    assert len(soup.select('ul[data-oo-lines] > .oo-line')) == 3


def test_order_files_are_not_grouped(coll, client):
    copy = order_scene(coll)
    categorise(coll, **{'3001': 'Bricks'})
    xml = client.get(URL + '/missing-parts.xml', query_string=dict(copy=[copy])).get_data(as_text=True)
    assert 'Bricks' not in xml and '<ITEM>' in xml


# ---------- print list ----------

PRINT = '/lists/{}/print'


def print_scene(coll, world):
    coll.mark(world.copy_a, '3001', '4', missing=2)
    coll.mark(world.copy_a, '3023', '15', missing=1)
    categorise(coll, **{'3001': 'Bricks', '3023': 'Plates'})
    return world.copy_a


def sections_of(soup):
    return [(t['data-pr-section'], t.select_one('.pr-sec-count').text, len(t.select('tr:not(.pr-sec-row)'))) for t in soup.select('tbody[data-pr-section]')]


def test_print_list_has_a_heading_per_group_in_one_table(world, coll, client):
    copy = print_scene(coll, world)
    soup = soup_of(client, PRINT.format('missing'), copy=copy)
    assert sections_of(soup) == [('Bricks', '1 line · 2 pieces', 1), ('Plates', '1 line · 1 piece', 1)]
    assert len(soup.select('table')) == 1 and len(soup.select('thead')) == 1 and not soup.select('details, .bw-sec-chevron, summary')
    head = soup.select_one('.pr-sec-row th')
    assert head['colspan'] == str(len(soup.select('thead th'))) and head['scope'] == 'colgroup'
    assert [th.text for th in soup.select('thead th') if th.text] == ['Item', 'Colour', 'Condition', 'Qty']       # the table header and its columns stay


def test_print_other_only_when_needed_and_bricklink_names(world, coll, client):
    copy = print_scene(coll, world)
    assert 'Other' not in [s[0] for s in sections_of(soup_of(client, PRINT.format('missing'), copy=copy))]
    categorise(coll, **{'3023': 'Made up'})
    assert [s[0] for s in sections_of(soup_of(client, PRINT.format('missing'), copy=copy))] == ['Bricks', 'Other']
    coll.setting('part_list_grouping', 'bricklink')
    assert [s[0] for s in sections_of(soup_of(client, PRINT.format('missing'), copy=copy))] == ['Bricks', 'Made up']


def test_print_with_no_grouping_is_the_plain_table_and_the_csv_never_groups(world, coll, client):
    copy = print_scene(coll, world)
    flat = client.get(f'/lists/missing.csv?copy={copy}').get_data(as_text=True)
    coll.setting('part_list_grouping', 'none')
    soup = soup_of(client, PRINT.format('missing'), copy=copy)
    assert not soup.select('tbody[data-pr-section], .pr-sec-row') and len(soup.select('tbody')) == 1
    assert 'Bricks' not in flat and 'Plates' not in flat
    assert client.get(f'/lists/missing.csv?copy={copy}').get_data(as_text=True) == flat
    coll.setting('part_list_grouping', 'grouped')
    assert client.get(f'/lists/missing.csv?copy={copy}').get_data(as_text=True) == flat


@pytest.mark.parametrize('kind,extra', [('picker', {}), ('wishlist', {})])
def test_print_groups_the_part_rows_of_the_picker_and_the_wishlist(world, coll, client, kind, extra):
    copy = print_scene(coll, world)
    soup = soup_of(client, PRINT.format(kind), copy=copy)
    found = dict((name, rows) for name, _, rows in sections_of(soup))
    assert found and set(found) <= {'Bricks', 'Plates'}
    if kind == 'wishlist':
        assert [r.get_text() for r in soup.select('tbody:not([data-pr-section]) .pr-no')]           # the wished set stays outside the sections, first
    else:
        assert soup.select('tbody[data-pr-section=Bricks] .pr-num')                                  # the rank column stays
