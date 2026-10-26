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

