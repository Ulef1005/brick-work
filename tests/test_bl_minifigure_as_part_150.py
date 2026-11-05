"""Issue #150: a BrickLink minifigure number (type M) that no catalogue minifigure holds but the catalogue holds, as the very same number, as
one BrickLink part (type P) resolves to that part, as a part line in no colour: the lookup, order lines, the BrickLink subsets list. A
catalogue minifigure still wins, several parts keep today's answer, another number is never tried. Invented data, no network."""
from contextlib import closing

import pytest

from brickwork.core import orders
from brickwork.core.connect import connect
from brickwork.store4 import bricklink_subsets as bs, identity, lookup
from tests.api2 import call, v2  # noqa: F401
from tests.app4 import app4, make_pair  # noqa: F401
from tests.store4_mint_fixtures import TECHNIC_DUMP, TECHNIC_FIGURES, TECHNIC_PARTS, item_id
from tests.test_bw_orders_storage import inventory, line_of


@pytest.fixture
def pair(tmp_path):
    return make_pair(tmp_path, rich=True, extra_dump=TECHNIC_DUMP, extra_parts=TECHNIC_PARTS, extra_local=TECHNIC_FIGURES)


@pytest.fixture
def db(pair):
    with closing(connect(pair)) as db:
        yield db


def part(db, key):
    return item_id(db, 'parts', key)


def test_the_lookup_of_a_figure_number_returns_the_part(db):
    assert lookup.find_items(db, 'bricklink', 'minifigure', 'syntech1') == [part(db, 'syn-tech-a')]
    assert lookup.find_items(db, 'bricklink', 'part', 'syntech1') == [part(db, 'syn-tech-a')]
    assert lookup.find_items(db, 'bricklink', 'minifigure', 'syntech1', 1) == [part(db, 'syn-tech-a')]                  # "no colour"
    assert lookup.find_items(db, 'bricklink', 'minifigure', 'syntech1', db.execute('SELECT id FROM main.color WHERE id>2').fetchone()[0]) == []   # another colour: a figure has none
    assert lookup.find_items(db, 'rebrickable', 'minifigure', 'syntech1') == []         # only BrickLink's own figure numbers


def test_the_api_lookup_returns_the_part_body(v2, pair):
    with closing(connect(pair)) as db:
        wanted = part(db, 'syn-tech-a')
    body = call(v2, '/lookup?provider=bricklink&kind=minifigure&key=syntech1').get_json()['data']
    assert (body['id'], body['kind']) == (wanted, 'part')


def test_the_resolver_gives_the_part_in_no_colour(db):
    assert identity.resolve_inverse(db, 'M', 'syntech1', None, exhaustive=True) == (part(db, 'syn-tech-a'), 1)
    assert identity.resolve_inverse(db, 'M', 'syntech1', None) is None               # the plain inverse (reconcile, mint) is unchanged


def test_a_catalogue_minifigure_still_wins(db):
    figure = item_id(db, 'minifigs', 'fig-000004')
    assert lookup.find_items(db, 'bricklink', 'minifigure', 'syntech3') == [figure]
    assert identity.resolve_inverse(db, 'M', 'syntech3', None, exhaustive=True) == (figure, 1)


def test_several_parts_keep_todays_answer(db):
    assert lookup.find_items(db, 'bricklink', 'minifigure', 'syntech2') == []
    assert identity.resolve_inverse(db, 'M', 'syntech2', None, exhaustive=True) is None


def test_another_number_is_never_tried(db):
    assert lookup.find_items(db, 'bricklink', 'minifigure', 'syntech9') == []
    assert identity.resolve_inverse(db, 'M', 'syn-tech-a', None, exhaustive=True) is None      # a Rebrickable number is not a BrickLink one


def test_a_local_figure_with_that_number_keeps_resolving_to_itself(db):
    from brickwork.store4 import fetched
    local = fetched.create_local_item(db, kind='minifigure', born_provider='bricklink', born_namespace='M', born_key='syntech1', name='x', kind_source='bricklink')
    fetched.add_item_link(db, local, provider='bricklink', provider_kind='M', provider_key='syntech1', status='matched', method='bricklink_list', origin='bricklink_list')
    db.commit()
    assert lookup.find_items(db, 'bricklink', 'minifigure', 'syntech1') == [local]
    assert identity.resolve_inverse(db, 'M', 'syntech1', None, exhaustive=True) == (local, 1)


def test_an_order_line_naming_the_figure_becomes_a_part_line(pair):
    with closing(connect(pair)) as db:
        made = orders.import_document(db, 'xml', inventory(line_of('M', 'syntech1', qty=2), line_of('M', 'syntech2', qty=1)))
        got = {r['raw_item_no']: r for r in db.execute('SELECT * FROM order_line WHERE order_id=?', (made['order_id'],))}
        wanted = part(db, 'syn-tech-a')
        assert (got['syntech1']['item_id'], got['syntech1']['color_id'], got['syntech1']['state']) == (wanted, 1, 'matched')
        assert db.execute('SELECT kind FROM item WHERE id=?', (wanted,)).fetchone()[0] == 'part'
        assert got['syntech2']['item_id'] is None                                            # ambiguous: not placed on either part
        assert db.execute("SELECT count(*) FROM item WHERE born_provider='bricklink' AND born_namespace='M'").fetchone()[0] == 0


def test_a_subsets_figure_line_is_a_part_line(pair):
    entry = {'item': {'no': 'syntech1', 'name': 'Tech figure', 'type': 'MINIFIG', 'category_id': 1}, 'quantity': 2, 'extra_quantity': 0,
             'is_alternate': False, 'is_counterpart': False}
    with closing(connect(pair)) as db:
        keep = item_id(db, 'sets', '1000-1')
        result = bs.load_subsets(db, keep, '1000-1', {'meta': {'code': 200}, 'data': [{'match_no': 0, 'entries': [entry]}]})
        wanted = part(db, 'syn-tech-a')
        assert [tuple(r) for r in db.execute('SELECT item_id, color_id, is_spare, quantity FROM main.fetched_inventory_part WHERE fetched_inventory_id=?',
                                             (result.fetched_id,))] == [(wanted, 1, 0, 2)]
        assert db.execute('SELECT count(*) FROM main.fetched_inventory_figure WHERE fetched_inventory_id=?', (result.fetched_id,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM main.item WHERE born_provider='bricklink' AND born_namespace='M'").fetchone()[0] == 0


def test_an_email_line_naming_the_figure_without_a_colour_is_placed_on_the_part_in_no_colour(pair):
    import sqlite3
    with sqlite3.connect(pair.with_name('catalogue.db')) as cat:
        build = cat.execute('SELECT max(id) FROM build').fetchone()[0]
        cat.execute("INSERT INTO bricklink_item(item_type,item_no,name,name_key,build_id) VALUES('M','syntech1','Technic Figure Syn One','technic figure syn one',?)", (build,))
    text = '* Batch #1 (submitted Dec 1, 2025 04:55)\n[Used] Technic Figure Syn One (x1) ..... EUR 2.00 each = EUR 2.00\n'
    with closing(connect(pair)) as db:
        made = orders.import_document(db, 'email', text)
        assert (made['placed'], made['unplaced']) == (1, 0)
        line = db.execute('SELECT item_id, color_id, state FROM order_line WHERE order_id=?', (made['order_id'],)).fetchone()
        assert tuple(line) == (part(db, 'syn-tech-a'), 1, 'matched')
        orders.phase(db, made['order_id'], made['document_id'], 'review')


def test_an_email_line_naming_the_figure_in_a_colour_keeps_that_colour(pair):
    import sqlite3
    with sqlite3.connect(pair.with_name('catalogue.db')) as cat:
        build = cat.execute('SELECT max(id) FROM build').fetchone()[0]
        cat.execute("INSERT INTO bricklink_item(item_type,item_no,name,name_key,build_id) VALUES('M','syntech1','Technic Figure Syn One','technic figure syn one',?)", (build,))
    text = '* Batch #1 (submitted Dec 1, 2025 04:55)\n[Used] Red Technic Figure Syn One (x1) ..... EUR 2.00 each = EUR 2.00\n'
    with closing(connect(pair)) as db:
        made = orders.import_document(db, 'email', text)
        line = db.execute('SELECT item_id, color_id FROM order_line WHERE order_id=?', (made['order_id'],)).fetchone()
        assert line['item_id'] == part(db, 'syn-tech-a')
        assert line['color_id'] not in (None, 1)            # the colour the e-mail names is kept, not replaced by "no colour"


def test_an_api_write_naming_the_figure_lands_on_the_part_in_no_colour(v2, pair):
    from tests.api2 import write
    made = write(v2, '/stock', body={'item': {'provider': 'bricklink', 'kind': 'minifigure', 'key': 'syntech1'}, 'quantity': 2, 'condition': 'used'})
    assert made.status_code == 201
    with closing(connect(pair)) as db:
        stock = db.execute('SELECT s.item_id, s.color_id, s.quantity FROM main.stock s WHERE s.id=?', (made.json['data']['ids'][0],)).fetchone()
        assert tuple(stock) == (part(db, 'syn-tech-a'), 1, 2)
    assert write(v2, '/stock', body={'item': {'provider': 'bricklink', 'kind': 'part', 'key': 'syntech1'}, 'quantity': 1}).status_code == 422   # a real part still needs its colour
