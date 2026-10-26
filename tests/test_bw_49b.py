"""49b · UI review run 6, Collection lists (finding ids c18..c30 in docs/brickwork/design-diff-49b.md)."""
from pathlib import Path
import re

from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / 'static/web/toni/bw-collection.css'


def list_page(client, route):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def sets_page(client):
    return list_page(client, '/collection/sets')


def test_c18_c19_c20_sets_sort_matches_kit(world, client):
    sort = sets_page(client).select_one('[data-bc-sort-panel]')
    labels = [b.get_text(strip=True).rstrip('✓') for b in sort.select('[data-bc-sort-pick]')]
    assert labels == ['Number', 'Name', 'Year', 'Missing parts', 'Used price']
    assert [o['value'] for o in sort.select('[data-bc-sort] option')] == ['number', 'name', 'year', 'missing', 'used_price']
    assert 'Missing first' not in str(sort)


def test_c20_other_kinds_keep_colour_and_quantity_with_new_label(world, client):
    soup = list_page(client, '/collection/P')
    options = {o['value']: o.get_text() for o in soup.select('[data-bc-sort] option')}
    assert options['missing'] == 'Missing parts' and 'colour' in options and 'quantity' in options


def test_c22_c23_c24_c25_c26_filters_sheet(world, client):
    panel = sets_page(client).select_one('[data-bc-panel]')
    theme = panel.select_one('.bc-theme-row')
    storage = panel.select_one('.bc-storage-row')
    year = panel.select_one('.bc-year-row')
    assert theme.find_next_sibling() == storage and storage.find_next_sibling() == year
    for row in (storage, year):
        assert not row.find_parent('details')
    assert storage.select_one('option')['value'] == '' and storage.select_one('option').get_text() == 'All locations'
    assert year.select_one('option').get_text() == 'any'
    assert len(panel.select('[data-bc-filter=storage]')) == 1 and len(panel.select('[data-bc-filter=year]')) == 1
    # 12i: Select and Group sit in the sheet's View section, no longer behind "Other filters".
    details = panel.select_one('details.bc-other-filters')
    assert not details.select_one('[data-bc-select]') and not details.select_one('[data-bc-group]')
    view = panel.select_one('.bc-view-group')
    assert not view.find_parent('details')
    assert view.select_one('[data-bc-select][role=switch]') and view.select_one('[data-bc-group]')
    assert [b.get_text() for b in view.select('[data-bc-group-pick]')] == ['None', 'Theme', 'Storage', 'Year', 'Place']
    assert view.find_next_sibling() == details
    # The Show action is the last element of the sheet: its own row, nothing underneath.
    assert panel.find_all(recursive=False)[-1].has_attr('data-bc-apply')


def test_c26_apply_is_not_sticky_on_phone():
    css = CSS.read_text()
    region = css[css.index('===== 49b'):]
    assert '.bc-filter-apply { position:static; }' in region


def test_c27_status_distribution_says_not_checked(coll, client):
    coll.add_copy('1000-1', condition='used')                      # completeness not recorded: a set nobody has checked
    coll.add_copy('1000-2', condition='new', completeness='sealed')
    soup = sets_page(client)
    strip = soup.select_one('.bc-status-strip')
    assert any(s['title'].startswith('Not checked · ') for s in strip.select('.bc-segment'))
    assert 'Unknown' not in strip.get_text() + str([s['title'] for s in strip.select('.bc-segment')])
    chips = [b.get_text(' ', strip=True) for b in soup.select('.bc-status-chips button')]
    assert any(c.startswith('Not checked ') for c in chips) and not any(c.startswith('Unknown') for c in chips)


def test_c28_instructions_headline_states_pdf_coverage(coll, client):
    for number in ('1000-1', '1000-2'):                            # a booklet shares the files of the set of the same number
        coll.add_stock('instructions', coll.local('instructions', f'Syn booklet {number}', born_key=number), quantity=1, condition='used')
    coll.sql("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,?,?,?)",
             (coll.project(coll.item('sets', '1000-1')), 'data/instructions/booklet.pdf', 'Booklet', '2026-10-26T12:00:00.000Z'))
    soup = list_page(client, '/collection/I')
    heading = soup.select_one('.bc-heading h1').get_text(strip=True)
    match = re.fullmatch(r'(\d+) of (\d+) booklets? (has|have) a PDF', heading)
    assert match, heading
    assert (int(match.group(1)), int(match.group(2))) == (1, 2) and match.group(3) == 'has'
    noun = 'booklet' if match.group(2) == '1' else 'booklets'
    assert soup.select_one('.bc-heading p').get_text(strip=True) == match.group(2) + ' ' + noun


def test_c29_c30_phone_rows_css_and_default():
    css = CSS.read_text()
    region = css[css.index('===== 49b'):]
    assert '#bw-collection[data-type=I] .bc-cards[data-view=list] .bc-card>.bc-picture' in region
    assert 'width:56px;height:56px;aspect-ratio:1' in region and 'min-height:84px' in region
    js = Path('static/web/toni/bw-collection.js').read_text()
    assert "['I','P'].includes(type)" in js and "max-width: 767px" in js


def test_followup_status_select_says_not_checked(world, client):
    select = sets_page(client).select_one('[data-bc-panel] select[data-bc-filter=status]')
    assert select.select_one('option[value=unknown]').get_text() == 'Not checked'


def test_followup_phone_rows_scoped_to_phone():
    css = CSS.read_text()
    region = css[css.index('Instructions and Parts on a phone'):css.index('/* ===== end 49b')]
    assert region.index('@media(max-width:767px)') < region.index('min-height:84px')
    assert region.rstrip().endswith('}') and region.count('@media') == 1
