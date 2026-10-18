"""49b · UI review run 6, Collection lists (finding ids c18..c30 in docs/brickwork/design-diff-49b.md)."""
from pathlib import Path
from bs4 import BeautifulSoup

from brickwork.core import admin
from tests.test_bw_collection import bw, legacy, reset_shell_metadata_after_test
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps


def sets_page(app):
    return BeautifulSoup(logged_in(app).get('/collection/sets').data, 'html.parser')


def test_c18_c19_c20_sets_sort_matches_kit(app, bw):
    sort = sets_page(app).select_one('[data-bc-sort-panel]')
    labels = [b.get_text(strip=True).rstrip('✓') for b in sort.select('[data-bc-sort-pick]')]
    assert labels == ['Number', 'Name', 'Year', 'Missing parts', 'Used price']
    assert [o['value'] for o in sort.select('[data-bc-sort] option')] == ['number', 'name', 'year', 'missing', 'used_price']
    assert 'Missing first' not in str(sort)


def test_c20_other_kinds_keep_colour_and_quantity_with_new_label(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/collection/P').data, 'html.parser')
    options = {o['value']: o.get_text() for o in soup.select('[data-bc-sort] option')}
    assert options['missing'] == 'Missing parts' and 'colour' in options and 'quantity' in options


def test_c22_c23_c24_c25_c26_filters_sheet(app, bw):
    panel = sets_page(app).select_one('[data-bc-panel]')
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
    css = Path('static/web/toni/bw-collection.css').read_text()
    region = css[css.index('===== 49b'):]
    assert '.bc-filter-apply { position:static; }' in region


def test_c27_status_distribution_says_not_checked(app, bw):
    soup = sets_page(app)
    strip = soup.select_one('.bc-status-strip')
    assert any(s['title'].startswith('Not checked · ') for s in strip.select('.bc-segment'))
    assert 'Unknown' not in strip.get_text() + str([s['title'] for s in strip.select('.bc-segment')])
    chips = [b.get_text(' ', strip=True) for b in soup.select('.bc-status-chips button')]
    assert any(c.startswith('Not checked ') for c in chips) and not any(c.startswith('Unknown') for c in chips)


def test_c28_instructions_headline_states_pdf_coverage(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/collection/I').data, 'html.parser')
    heading = soup.select_one('.bc-heading h1').get_text(strip=True)
    import re
    match = re.fullmatch(r'(\d+) of (\d+) booklets? (has|have) a PDF', heading)
    assert match, heading
    assert int(match.group(1)) <= int(match.group(2))
    noun = 'booklet' if match.group(2) == '1' else 'booklets'
    assert soup.select_one('.bc-heading p').get_text(strip=True) == match.group(2) + ' ' + noun


def test_c29_c30_phone_rows_css_and_default():
    css = Path('static/web/toni/bw-collection.css').read_text()
    region = css[css.index('===== 49b'):]
    assert '#bw-collection[data-type=I] .bc-cards[data-view=list] .bc-card>.bc-picture' in region
    assert 'width:56px;height:56px;aspect-ratio:1' in region and 'min-height:84px' in region
    js = Path('static/web/toni/bw-collection.js').read_text()
    assert "['I','P'].includes(type)" in js and "max-width: 767px" in js


def test_followup_status_select_says_not_checked(app, bw):
    select = sets_page(app).select_one('[data-bc-panel] select[data-bc-filter=status]')
    assert select.select_one('option[value=unknown]').get_text() == 'Not checked'


def test_followup_phone_rows_scoped_to_phone():
    css = Path('static/web/toni/bw-collection.css').read_text()
    region = css[css.index('Instructions and Parts on a phone'):css.index('/* ===== end 49b')]
    assert region.index('@media(max-width:767px)') < region.index('min-height:84px')
    assert region.rstrip().endswith('}') and region.count('@media') == 1
