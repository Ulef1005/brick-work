"""v1.3 figure detail states and shared item-detail regressions, on the 4.0 store (M.8b).

Items are ids; a part is always held in a colour (colour 1 is "no colour"); the item page answers 302 to the one colour of a part and shows
a chooser for several. Not here: the wanted-add through review/confirm/undo (Add, M.8c), the unresolved wanted receipt/undo (M.8d), the Add
radio fallback (M.8c), the Check figure parts page itself (M.8d) and the Matching headline of loose figures (M.8e)."""
from urllib.parse import urlsplit, parse_qs

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection
from brickwork.store4 import fetched
from tests.app4 import STAMP, world, coll, pair, read, app4, client  # noqa: F401  (fixtures)

NO_COLOUR = 1


def page(client, route, status=200):
    response = client.get(route)
    assert response.status_code == status, (route, response.status_code)
    return BeautifulSoup(response.data, 'html.parser')


def item_url(item, **query):
    return f'/collection/item/{item}' + ('?' + '&'.join(f'{k}={v}' for k, v in query.items()) if query else '')


def query_of(location):
    return parse_qs(urlsplit(location).query)


def used_row(soup, copy_id):
    """The 'Used in sets' row of one copy."""
    for row in soup.select('[data-module=used-in] [data-bc-row]'):
        if row.select_one(f'a[href*="copy={copy_id}"]'):
            return row
    raise AssertionError(f'no used-in row for copy {copy_id}')


def components(coll, copy_id, figure):
    """The component lines (ids) of the figure `figure` in a copy."""
    return [r[0] for r in coll.sql('''SELECT p.id FROM copy_part p JOIN copy_figure f ON f.id=p.copy_figure_id WHERE p.copy_id=? AND f.item_id=? AND p.retired_at IS NULL''',
                                   (copy_id, figure)).fetchall()]


@pytest.fixture
def figure_world(coll, world):
    """The world with Set 1 (copy A) older than Set 2 (copy B), the figure in a theme and a year, and a picture."""
    coll.sql('UPDATE copy SET created_at=? WHERE id=?', ('2026-01-01T00:00:00.000Z', world.copy_a))
    coll.sql('UPDATE copy SET created_at=? WHERE id=?', ('2026-01-02T00:00:00.000Z', world.copy_b))
    coll.sql('UPDATE main.item SET year=2011 WHERE id=?', (world.figure,))
    coll.prop(world.figure, 'theme', 'City · Police')
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,NULL,'rebrickable','render','data/images/fig.png',?)", (world.figure, STAMP))
    return world


@pytest.mark.parametrize('state', ['loose-and-sets', 'parts-missing', 'only-loose', 'only-sets', 'unidentified', 'no-picture'])
def test_six_figure_states(coll, figure_world, client, state):
    w = figure_world
    item = w.figure
    if state == 'parts-missing':
        coll.sql('UPDATE copy_part SET missing=1 WHERE id=?', (components(coll, w.copy_a, w.figure)[0],))
    elif state == 'only-loose':
        coll.sql('UPDATE copy_figure SET retired_at=? WHERE item_id=?', (STAMP, w.figure))
    elif state == 'only-sets':
        coll.sql('UPDATE stock SET archived_at=? WHERE id=?', (STAMP, w.stock_figure))
    elif state == 'unidentified':
        item = coll.local('minifigure', 'Mystery figure')
        coll.sql("INSERT INTO copy_figure(copy_id,item_id,inventory_source,inventory_digest,quantity,missing,updated_at) VALUES(?,?,'none','none',1,0,?)", (w.copy_a, item, STAMP))
    elif state == 'no-picture':
        coll.sql('DELETE FROM picture WHERE item_id=?', (w.figure,))
    soup = page(client, item_url(item))
    # The Matching module belongs to the workbench (M.8e): it is not on the page until then.
    assert [m['data-module'] for m in soup.select('[data-module]')] == ['status', 'consists', 'used-in', 'prices', 'wanted', 'info']
    assert not soup.select('.bc-hero-status .bc-quantity-pill')
    assert 'Grouped by place' not in soup.get_text()
    assert 'rebrickable-translated' not in soup.select_one('[data-module=consists]').get_text()
    assert not soup.select('[data-module=consists] .bc-toolbar, [data-module=used-in] .bc-toolbar')
    used = soup.select_one('[data-module=used-in]')
    if state == 'only-loose':
        assert 'Not in any set copy.' in used.get_text()
    else:
        row = used_row(soup, w.copy_a)
        assert row.select_one('.bc-used-identity>.mono').get_text() == '1000-1 · Set 1'
        check = row.select_one('a.bc-check-figure')
        assert check['href'] == f'/workbench/check-parts/{w.copy_a}/figure/M/{item}'
    if state == 'parts-missing':
        assert used_row(soup, w.copy_a).select_one('[data-figure-state=parts-missing]').get_text() == '1 part missing'
        assert used_row(soup, w.copy_b).select_one('[data-figure-state=present]').get_text() == 'Present'
        assert 'Set 1 · 1000-1 · missing' in soup.select_one('.bc-component-state').get_text()
    if state == 'unidentified':
        assert soup.h1.get_text().replace('\xa0', ' ') == 'Mystery figure (unidentified)'
        assert 'Parts unknown until the figure is identified.' in soup.get_text()
        assert soup.select_one('.bc-figure-context').get_text() == 'Theme and year not known'
        assert 'Not identified' in soup.select_one('[data-module=info]').get_text()
        assert soup.select_one('[data-module=info] a')['href'] == '/manage/unresolved'
    else:
        assert 'Identified' in soup.select_one('[data-module=info]').get_text()
        assert soup.select_one('.bc-figure-context').get_text() == 'City · Police · 2011'
        if state != 'no-picture':
            assert soup.select_one('.bc-hero-picture img')['src'].startswith('/manage/images/')
    if state == 'no-picture':
        assert 'No image' in soup.select_one('.bc-hero-picture').get_text()
        assert not soup.select_one('.bc-hero-picture img')
    if state not in ('only-sets', 'unidentified'):
        assert soup.select_one('[data-bc-photo-file]')


def test_missing_figure_disables_checker(coll, figure_world, client):
    coll.mark_figure(figure_world.copy_a, 'fig-000004', missing=1)
    soup = page(client, item_url(figure_world.figure))
    row = used_row(soup, figure_world.copy_a)
    assert row.select_one('[data-figure-state=missing]').get_text() == 'Missing'
    assert row.select_one('button.bc-check-figure[disabled]')
    assert not row.select_one('a.bc-check-figure')
    assert used_row(soup, figure_world.copy_b).select_one('a.bc-check-figure')


def test_part_colour_redirect_chooser_and_jump(coll, world, client):
    part, red, white = world.local_part, world.red, world.white
    response = client.get(item_url(part, stock=world.stock_local))
    assert response.status_code == 302
    assert query_of(response.location) == {'stock': [world.stock_local], 'colour': [str(red)]}
    assert 'Unknown colour' not in page(client, response.location).select_one('.bc-detail-hero').get_text()
    coll.add_wish(part, colour=white, quantity=1)
    soup = page(client, item_url(part))
    assert len(soup.select('.bc-colour-chooser a')) == 2
    assert 'Unknown colour' not in soup.select_one('.bc-detail-hero').get_text()
    assert not soup.select('[data-module=prices]')
    result = client.get('/collection/jump?q=x999')
    assert result.status_code == 200
    parts = [r for r in result.json['results'] if r['kind'] == 'part']
    assert parts and all('colour=' in r['url'] for r in parts)


def test_shared_rows_and_short_toolbar_threshold(coll, figure_world, client):
    w = figure_world
    soup = page(client, item_url(w.brick, colour=w.red))
    used = soup.select_one('.bc-used-sets')
    assert used.select_one('.bc-used-identity>.mono').get_text() == '1000-1 · Set 1'
    assert 'needs ' in used.get_text() and ' · have ' in used.get_text()
    assert not used.select('sup, .bc-toolbar')
    assert soup.select_one('[data-bc-photo-file]')
    for _ in range(14):
        coll.add_copy('1000-1')
    used = page(client, item_url(w.figure)).select_one('[data-module=used-in]')
    assert used.select_one('.bc-toolbar') and used['data-bc-page-size'] == '15'
    assert len(used.select('[data-bc-row]')) == 16


def test_figure_detail_queries_do_not_grow_per_component_or_copy(coll, figure_world, read):
    w = figure_world

    def measured():
        queries = []
        with read() as db:
            db.set_trace_callback(queries.append)
            try:
                collection.detail(db, w.figure)
            finally:
                db.set_trace_callback(None)
        return len(queries)
    before = measured()
    for _ in range(20):
        coll.add_copy('1000-1')
    line = coll.sql('SELECT id FROM copy_figure WHERE copy_id=? AND item_id=?', (w.copy_a, w.figure)).fetchone()[0]
    for n in range(100):
        part = fetched.create_local_item(coll.db, kind='part', born_provider='bricklink', born_namespace='P', born_key=f'component-{n}', name=f'Component {n}')
        coll.db.execute('INSERT INTO copy_part(copy_id,copy_figure_id,item_id,color_id,quantity,missing) VALUES(?,?,?,?,1,1)', (w.copy_a, line, part, w.red))
    coll.db.commit()
    assert measured() == before


@pytest.mark.parametrize('query', ['number=x', 'kind=S', 'number=x&kind=S', 'item_id=999999', 'item_id=x&_external=1', '_anchor=a&_scheme=ftp'])
def test_colour_redirect_drops_arguments_that_are_the_route(world, client, query):
    response = client.get(item_url(world.local_part, stock=world.stock_local) + '&' + query)
    assert response.status_code == 302
    assert urlsplit(response.location).path == item_url(world.local_part) and not urlsplit(response.location).netloc
    args = query_of(response.location)
    assert args['stock'] == [world.stock_local] and args['colour'] == [str(world.red)]
    assert not {'item_id', '_external', '_anchor', '_scheme'} & set(args)
    page(client, response.location)


def test_no_colour_chooser_opens_instance(coll, world, client):
    """A part held in no colour is held in colour 1; the chooser offers it and its page lists that stock, not the red one."""
    unknown = coll.add_stock('part', world.brick, colour=NO_COLOUR, quantity=2)
    soup = page(client, item_url(world.brick))
    links = [a for a in soup.select('.bc-colour-chooser a') if query_of(a['href']).get('colour') == [str(NO_COLOUR)]]
    assert len(links) == 1 and len(soup.select('.bc-colour-chooser a')) == 2
    selected = page(client, links[0]['href'])
    assert not selected.select('.bc-colour-chooser')
    assert unknown in selected.get_text() or selected.select(f'[data-bc-rows] a[href*="stock={unknown}"]')
    assert not selected.select(f'[data-bc-rows] a[href*="stock={world.stock_brick}"]')
    for link in selected.select('[data-bc-rows] a[href*="stock="]'):
        assert query_of(link['href'])['colour'] == [str(NO_COLOUR)]
        assert not page(client, link['href']).select('.bc-colour-chooser')


@pytest.mark.parametrize('source', ['stock', 'copy'])
def test_zero_quantity_colour_is_not_a_choice(coll, world, client, source):
    if source == 'stock':
        coll.add_stock('part', world.brick, colour=world.white, quantity=0)
    else:
        coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity) VALUES(?,?,?,0)', (world.copy_a, world.brick, world.white))
    response = client.get(item_url(world.brick))
    assert response.status_code == 302
    assert query_of(response.location) == {'colour': [str(world.red)]}


def test_manual_figure_line_does_not_duplicate_used_copy(coll, figure_world, read, client):
    """The 3.3 shape (a figure stored as a part line of the copy) is gone: a figure is a `copy_figure` line. Each copy that holds it is one row
    of "Used in sets", whatever its quantity, while the figure count adds the quantities."""
    w = figure_world
    with read() as db:
        detail = collection.detail(db, w.figure)
    copies = {u['copy_id'] for u in detail['used_in']}
    assert len(detail['used_in']) == len(copies) == 2 and detail['set_count'] == 4
    assert len(page(client, item_url(w.figure)).select('[data-module=used-in] [data-bc-row]')) == 2


@pytest.mark.parametrize('many', [False, True])
def test_headline_counts_each_loose_figure(coll, figure_world, read, client, many):
    """The Matching headline ("completes 2 figures") belongs to the workbench (M.8e); what stays here is that every loose figure is counted."""
    w = figure_world
    second = coll.add_stock('minifigure', w.figure, quantity=1, condition='new')
    if many:
        coll.sql('UPDATE stock SET quantity=3 WHERE id=?', (second,))
    with read() as db:
        for selected in (w.stock_figure, second):
            detail = collection.detail(db, w.figure, stock_id=selected)
            assert detail['loose_count'] == (4 if many else 2) and detail['loose_conditions'] == {'used': 1, 'new': 3 if many else 1}
    assert f'{4 if many else 2} loose' in page(client, item_url(w.figure)).select_one('[data-module=status]').get_text()


@pytest.mark.parametrize('kind', ['set', 'part', 'minifigure'])
@pytest.mark.parametrize('identified', [True, False])
def test_unresolved_price_message_matches_identification(coll, client, kind, identified):
    """An item with no number says it has no price until it is identified; one waiting on a link decision has simply no quotes."""
    item = coll.local(kind, 'Unresolved price', born_key='unresolved-price' if identified else None)
    if identified:
        coll.link(item, 'unresolved-price', kind={'set': 'S', 'part': 'P', 'minifigure': 'M'}[kind], status='to_check')
    query = {'colour': NO_COLOUR} if kind == 'part' else {}
    prices = page(client, item_url(item, **query)).select_one('[data-module=prices]').get_text()
    assert ('No price until the item is identified.' in prices) == (not identified)
    if identified:
        assert 'No sales and no listings recorded.' in prices


def test_only_zero_quantity_colour_does_not_redirect(coll, client):
    part = coll.local('part', 'Empty part', born_key='empty-part')
    coll.add_stock('part', part, colour=coll.colour('4'), quantity=0)
    assert client.get(item_url(part)).status_code == 200


def test_single_no_colour_redirect_uses_colour_one(coll, client):
    part = coll.local('part', 'Unknown part', born_key='unknown-part')
    coll.add_stock('part', part, colour=NO_COLOUR, quantity=1)
    response = client.get(item_url(part))
    assert response.status_code == 302
    assert query_of(response.location) == {'colour': [str(NO_COLOUR)]}
    assert not page(client, response.location).select('.bc-colour-chooser')
