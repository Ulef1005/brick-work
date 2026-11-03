"""4.9a: UI review run 6, set and part detail, on a 4.0 collection (M.8b, issue #110).

The Matching module and its sorting (c6/c7, c9/c10, the per-match query count) wait for M.8e, which ports the Matcher."""
from pathlib import Path
import re

from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'static/web/toni/bw-collection.css').read_text()
REGION = CSS.split('/* ===== 4.9a')[1].split('/* ===== end 4.9a')[0]


def page(client, route, **query):
    response = client.get(route, query_string=query)
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    return BeautifulSoup(response.data, 'html.parser')


def pills(soup):
    return [p.get_text() for p in soup.select('.bc-hero-status .bc-quantity-pill')]


def local_part(coll, quantity=3, condition='used'):
    """A BrickLink-born part held in red (the "loose part" of the old fixture), one stock line."""
    item = coll.local('part', 'BrickLink-only part', born_key='x999')
    red = coll.colour('4')
    return item, red, coll.add_stock('part', item, colour=red, quantity=quantity, condition=condition)


def loose_figure(coll, quantity=2):
    figure = coll.item('minifigs', 'fig-000004')
    return figure, coll.add_stock('minifigure', figure, quantity=quantity, condition='used')


def test_c1_set_hero_image_is_never_cropped():
    assert 'object-fit:cover' not in CSS.split('#bw-collection[data-type=S] .bc-hero-picture {')[1].split('\n')[0] + REGION
    assert '#bw-collection[data-type=S] .bc-hero-picture img { object-fit:contain' in REGION
    assert not re.search(r'bc-hero-picture[^{]*\{[^}]*object-fit:\s*cover', CSS)


def test_c2_c3_part_and_figure_phone_hero_follow_the_kit():
    assert '@media(max-width:767px)' in REGION
    assert 'grid-template-columns:96px minmax(0,1fr);align-items:end;gap:16px' in REGION
    assert '.bc-hero-picture { width:96px; }' in REGION
    assert 'font:600 24px/30px var(--tw-font);letter-spacing:-.3px' in REGION


def test_c4_c8_loose_part_and_figure_identity_pills(coll, client):
    part, red, _ = local_part(coll)
    figure, _ = loose_figure(coll)
    soup = page(client, f'/collection/item/{part}', colour=red)
    assert pills(soup) == ['Used', '×3']
    assert 'loose' not in soup.select_one('.bc-hero-status').get_text()
    assert pills(page(client, f'/collection/item/{figure}')) == []
    # Mixed conditions across instances: no single condition is claimed.
    coll.add_stock('part', part, colour=red, quantity=1, condition='new')
    assert pills(page(client, f'/collection/item/{part}', colour=red)) == ['×4']


def test_c5_loose_part_info_has_no_empty_tags_fact(coll, client):
    part, red, stock = local_part(coll)
    soup = page(client, f'/collection/item/{part}', colour=red)
    assert [n.get_text() for n in soup.select('[data-module=info] dt')] == ['Condition', 'Damaged', 'Quantity', 'Storage']
    # A recorded tag is content and stays visible.
    coll.tag('stock', stock, coll.flag('Display', 'tag', shown_on_grid=0))
    soup = page(client, f'/collection/item/{part}', colour=red)
    facts = {f.dt.get_text(): f.dd.get_text() for f in soup.select('[data-module=info] .bc-fact')}
    assert facts['Tags'] == 'Display'
    # Sets keep the Tags fact either way.
    copy = coll.add_copy('1000-1')
    soup = page(client, f'/collection/item/{coll.item("sets", "1000-1")}', copy=copy)
    assert 'Tags' in [n.get_text() for n in soup.select('[data-module=info] dt')]


def test_set_detail_has_no_matching_module(coll, client):
    """Decision 16 (A), the one assertion of c6/c7 that does not need the Matcher: Take on the missing-part cards covers it."""
    copy = coll.add_copy('1000-1')
    assert not page(client, f'/collection/item/{coll.item("sets", "1000-1")}', copy=copy).select('[data-module=matching]')


def test_c11_c12_progress_css_follows_dom_order():
    template = (ROOT / 'templates/web/toni/brickwork/collection_modules.html').read_text()
    assert 'class="bc-progress-block"' in template
    assert '.bc-progress-block { display:flex;flex-direction:column;gap:6px; }' in REGION
    assert '.bc-progress-stats { justify-content:space-between;flex-wrap:nowrap; }' in REGION
    assert '.bc-progress-stats:has(+ .bc-coverage) { margin-bottom:8px; }' in REGION
    assert 'display:contents' not in REGION and 'order:' not in REGION


def test_c11_c12_progress_dom_keeps_one_block(coll, client):
    copy = coll.add_copy('1000-1')
    coll.mark(copy, '3001', '4', missing=1, checked=1)
    soup = page(client, f'/collection/item/{coll.item("sets", "1000-1")}', copy=copy)
    block = soup.select_one('[aria-label="Copy progress"] .bc-progress-block')
    assert block
    # Kit order: the bar, then the present count on the left and the missing count on the right. The coverage bar and its two captions
    # ("can be taken", "to order") need the loose stock the Matcher counts: they are pinned with M.8e.
    assert [c.get('class')[-1] for c in block.find_all(recursive=False)][:2] == ['bc-progress', 'bc-progress-stats']
    first = block.select_one('.bc-progress-stats')
    assert first.find_all(recursive=False)[0]['class'] == ['bc-progress-present'] and first.find_all(recursive=False)[1].get_text().endswith(' missing')
    assert first.find_all(recursive=False)[0].get_text() == '5 of 6 parts present'
    assert first.find_all(recursive=False)[1].get_text() == '1 missing'


def test_c13_edit_keeps_estimate_folded(coll, client):
    copy = coll.add_copy('1000-1')
    soup = page(client, f'/collection/item/{coll.item("sets", "1000-1")}', copy=copy)
    form = soup.select_one('#bc-edit form')
    estimate = form.select_one('input[name=current_value]')
    assert estimate.find_parent('details', class_='bc-estimate-details')
    assert not estimate.find_parent('details').has_attr('open')
    assert form.select_one('input[name=current_value_currency]').find_parent('details') is estimate.find_parent('details')
    legends = [l.get_text() for l in form.select('legend')]
    assert legends.index('Completeness') < legends.index('Flags')
    assert form.select_one('details.bc-estimate-details > summary').get_text() == 'Set estimate'


def test_c14_c15_figure_rows_in_css_and_dom(coll, client):
    copy = coll.add_copy('1000-1')
    soup = page(client, f'/collection/item/{coll.item("sets", "1000-1")}', copy=copy)
    rows = soup.select('.bc-figure-row')
    assert rows and all(r.select_one('.bc-figure-status') for r in rows)
    assert not [r for r in soup.select('.bc-inventory-row') if r.select_one('.bc-figure-status') and 'bc-figure-row' not in r['class']]
    assert '.bc-figure-status { flex:none;white-space:nowrap;height:24px;min-height:24px;padding:0 10px; }' in REGION
    assert 'a.bc-figure-status { min-height:24px;' in REGION
    # v1.3 uses a flexible identity and a separate checker action at all widths.
    assert all(r.select_one('.bc-figure-identity > a') for r in rows)
    assert not soup.select('a.bc-figure-status')
    assert all(r.select_one('.bc-check-figure') for r in rows)
    assert 'min-width:200px' not in REGION


def test_followup_unrecorded_condition_blocks_the_condition_pill(coll, client):
    part, red, _ = local_part(coll)
    coll.add_stock('part', part, colour=red, quantity=1, condition=None)
    assert pills(page(client, f'/collection/item/{part}', colour=red)) == ['×4']
