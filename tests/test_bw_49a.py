"""4.9a: UI review run 6, set and part detail."""
import re
import sqlite3
from pathlib import Path

from bs4 import BeautifulSoup

from brickwork.core import admin, collection
from tests.test_bw_checker import bw, legacy, mutate  # noqa: F401
from tests.test_bw_collection import reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps  # noqa: F401

CSS = Path('static/web/toni/bw-collection.css').read_text()
REGION = CSS.split('/* ===== 4.9a')[1].split('/* ===== end 4.9a')[0]


def page(app, route, **query):
    response = logged_in(app).get(route, query_string=query)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_c1_set_hero_image_is_never_cropped():
    assert 'object-fit:cover' not in CSS.split('#bw-collection[data-type=S] .bc-hero-picture {')[1].split('\n')[0] + REGION
    assert '#bw-collection[data-type=S] .bc-hero-picture img { object-fit:contain' in REGION
    assert not re.search(r'bc-hero-picture[^{]*\{[^}]*object-fit:\s*cover', CSS)


def test_c2_c3_part_and_figure_phone_hero_follow_the_kit():
    assert '@media(max-width:767px)' in REGION
    assert 'grid-template-columns:96px minmax(0,1fr);align-items:end;gap:16px' in REGION
    assert '.bc-hero-picture { width:96px; }' in REGION
    assert 'font:600 24px/30px var(--tw-font);letter-spacing:-.3px' in REGION


def test_c4_c8_loose_part_and_figure_identity_pills(app, bw):
    for route, kwargs, quantity in [('/collection/item/P/bl-part', {'colour': 11}, '×3'), ('/collection/item/M/bl-figure', {}, '×2')]:
        soup = page(app, route, **kwargs)
        pills = [p.get_text() for p in soup.select('.bc-hero-status .bc-quantity-pill')]
        assert pills == (['Used', quantity] if '/P/' in route else []), (route, pills)
        if '/P/' in route:
            assert 'loose' not in soup.select_one('.bc-hero-status').get_text()
    # Mixed conditions across instances: no single condition is claimed.
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('loose-part-new','P','bl-part',11,1,'N')")
    soup = page(app, '/collection/item/P/bl-part', colour=11)
    assert [p.get_text() for p in soup.select('.bc-hero-status .bc-quantity-pill')] == ['×4']


def test_c5_loose_part_info_has_no_empty_tags_fact(app, bw):
    soup = page(app, '/collection/item/P/bl-part', colour=11)
    assert [n.get_text() for n in soup.select('[data-module=info] dt')] == ['Condition', 'Damaged', 'Quantity', 'Storage']
    # A recorded tag is content and stays visible.
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('tag-x','Display','tag',0)")
        db.execute("INSERT INTO item_flags VALUES('stock','loose-part','tag-x')")
    soup = page(app, '/collection/item/P/bl-part', colour=11)
    facts = {f.dt.get_text(): f.dd.get_text() for f in soup.select('[data-module=info] .bc-fact')}
    assert facts['Tags'] == 'Display'
    # Sets keep the Tags fact either way.
    soup = page(app, '/collection/item/S/new-set', copy='copy')
    assert 'Tags' in [n.get_text() for n in soup.select('[data-module=info] dt')]


def test_c6_c7_part_matching_has_no_toolbar_and_states_its_order(app, bw):
    with admin.database(bw) as db, db:
        db.execute("UPDATE copy_parts SET missing=1,damaged=0 WHERE item_type='P' AND item_no='bl-part' AND parent_minifig IS NULL")
    soup = page(app, '/collection/item/P/bl-part', colour=11)
    matching = soup.select_one('[data-module=matching]')
    assert not matching.select('.bc-toolbar, [data-bc-search], [data-bc-sort]')
    assert matching.select_one('.bc-matching-headline').get_text()
    assert matching.select_one('.bc-matching-sub').get_text() == 'Sorted by fewest parts left'
    assert matching.select_one('.bc-matching-headline').find_next_sibling() == matching.select_one('.bc-matching-sub')
    # Decision 16 (A): set detail has no Matching module; Take on the missing-part cards covers it.
    assert not page(app, '/collection/item/S/new-set', copy='copy').select('[data-module=matching]')


def test_c7_matches_are_sorted_by_completion_then_fewest_parts_left(app, bw):
    with admin.database(bw) as db, db:
        db.execute("UPDATE copy_minifigs SET missing=0")
        db.execute("UPDATE copy_parts SET missing=0")
        original = dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
        for copy in ('a-many', 'z-one'):
            db.execute('INSERT INTO copies(' + ','.join(original) + ') VALUES(' + ','.join('?' for _ in original) + ')', tuple(dict(original, id=copy).values()))
        template = [dict(r) for r in db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_type='P' AND item_no='bl-part' AND parent_minifig IS NULL")]
        assert template
        # Copy a-many lacks two distinct parts, z-one lacks one; alphabetical order would put a-many first.
        for copy, extra in (('z-one', 0), ('a-many', 1)):
            for line in template:
                row = dict(line, id=None, copy_id=copy, missing=1, quantity=1)
                db.execute('INSERT INTO copy_parts(' + ','.join(row) + ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values()))
            for n in range(extra):
                db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P',?,?)", (f'other-{n}', f'Other {n}'))
                row = dict(template[0], id=None, copy_id=copy, item_no=f'other-{n}', missing=1, quantity=1)
                db.execute('INSERT INTO copy_parts(' + ','.join(row) + ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values()))
        detail = collection.detail(db, 'P', 'bl-part', colour=11)
    order = [m['copy_id'] for m in detail['matches']]
    assert order.index('z-one') < order.index('a-many')


def test_c9_c10_figure_matching_headline_and_order(app, bw):
    soup = page(app, '/collection/item/M/bl-figure')
    modules = [m['data-module'] for m in soup.select('[data-module]')]
    assert modules.index('consists') < modules.index('matching')
    matching = soup.select_one('[data-module=matching]')
    assert not matching.select('.bc-toolbar')
    headline = matching.select_one('.bc-matching-headline').get_text()
    assert headline.startswith('Fits 1 set, completes '), headline
    assert matching.select_one('.bc-matching-sub').get_text() == 'Sorted by fewest parts left'
    # No remaining match: the figure module shows one empty-state line.
    with admin.database(bw) as db, db:
        db.execute("UPDATE copy_minifigs SET missing=0")
    matching = page(app, '/collection/item/M/bl-figure').select_one('[data-module=matching]')
    assert not matching.select('.bc-matching-headline')
    assert 'Nothing to match yet' in matching.get_text()


def test_c11_c12_progress_css_follows_dom_order():
    template = Path('templates/web/toni/brickwork/collection_modules.html').read_text()
    assert 'class="bc-progress-block"' in template
    assert '.bc-progress-block { display:flex;flex-direction:column;gap:6px; }' in REGION
    assert '.bc-progress-stats { justify-content:space-between;flex-wrap:nowrap; }' in REGION
    assert '.bc-progress-stats:has(+ .bc-coverage) { margin-bottom:8px; }' in REGION
    assert 'display:contents' not in REGION and 'order:' not in REGION


def test_c11_c12_progress_dom_keeps_one_block(app, bw):
    with admin.database(bw) as db, db:
        db.execute("UPDATE copy_parts SET missing=1,checked=1 WHERE copy_id='copy' AND parent_minifig IS NULL AND item_type='P'")
    soup = page(app, '/collection/item/S/new-set', copy='copy')
    block = soup.select_one('[aria-label="Copy progress"] .bc-progress-block')
    assert block
    # Kit order: bar, present left and missing right, coverage bar, then its two captions.
    assert [c.get('class')[-1] for c in block.find_all(recursive=False)] == ['bc-progress', 'bc-progress-stats', 'bc-coverage', 'bc-progress-stats']
    first, last = block.select('.bc-progress-stats')
    assert first.find_all(recursive=False)[0]['class'] == ['bc-progress-present'] and first.find_all(recursive=False)[1].get_text().endswith(' missing')
    assert [s.get_text().split(' ', 1)[1] for s in last.select('span')] == ['can be taken', 'to order']
    assert [s.get_text().split(' ', 1)[1] for s in block.select('.bc-progress-stats span')] == ['missing', 'can be taken', 'to order']


def test_c13_edit_keeps_estimate_folded(app, bw):
    soup = page(app, '/collection/item/S/new-set', copy='copy')
    form = soup.select_one('#bc-edit form')
    names = [n.get('name') or n.get_text() for n in form.select('legend, input[name=current_value], p, details > summary, [data-bc-flags] legend')]
    estimate = form.select_one('input[name=current_value]')
    assert estimate.find_parent('details', class_='bc-estimate-details')
    assert not estimate.find_parent('details').has_attr('open')
    assert form.select_one('input[name=current_value_currency]').find_parent('details') is estimate.find_parent('details')
    legends = [l.get_text() for l in form.select('legend')]
    assert legends.index('Completeness') < legends.index('Flags')
    assert form.select_one('details.bc-estimate-details > summary').get_text() == 'Set estimate'


def test_c14_c15_figure_rows_in_css_and_dom(app, bw):
    soup = page(app, '/collection/item/S/new-set', copy='copy')
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



def test_matches_cost_no_query_per_match(app, bw):
    statements = []
    with admin.database(bw) as db:
        db.set_trace_callback(statements.append)
        collection.detail(db, 'P', 'bl-part', colour=11)
        few = len(statements)
        statements.clear()
        with db:
            original = dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
            line = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_no='bl-part' AND parent_minifig IS NULL").fetchone())
            for n in range(150):
                db.execute('INSERT INTO copies(' + ','.join(original) + ') VALUES(' + ','.join('?' for _ in original) + ')', tuple(dict(original, id=f'bulk{n}').values()))
                row = dict(line, id=None, copy_id=f'bulk{n}', missing=1, quantity=1)
                db.execute('INSERT INTO copy_parts(' + ','.join(row) + ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values()))
        statements.clear()
        collection.detail(db, 'P', 'bl-part', colour=11)
        many = len(statements)
    assert many <= few + 20, (few, many)


def test_followup_unrecorded_condition_blocks_the_condition_pill(app, bw):
    with admin.database(bw) as db, db:
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('loose-part-unknown','P','bl-part',11,1,NULL)")
    soup = page(app, '/collection/item/P/bl-part', colour=11)
    assert [p.get_text() for p in soup.select('.bc-hero-status .bc-quantity-pill')] == ['×4']
