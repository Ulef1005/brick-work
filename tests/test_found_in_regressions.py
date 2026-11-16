"""Found in review regressions against real catalogue, writes, REST and MCP."""
import pytest
from bs4 import BeautifulSoup

from brickwork.core import stock, supersets
from brickwork.core.transaction import transaction
from tests.app4 import RICH, make_pair, csrf, post, client  # noqa: F401
from tests.api2 import app4, coll, world, v2, call, validate  # noqa: F401
from tests.test_api2_mcp import adapter, run_tool, payload  # noqa: F401


@pytest.fixture
def pair(tmp_path):
    extra = {**RICH, 'minifigs': [['fig-999990', 'Syn double legs', 2, '']],
             'inventories': RICH['inventories'] + [[999990, 1, 'fig-999990']],
             'inventory_parts': RICH['inventory_parts'] + [[999990, '970c03', 0, 2, 'False', '']]}
    return make_pair(tmp_path, extra_dump=extra)


@pytest.mark.parametrize('namespace,number', [('sets', '1000-1'), ('minifigs', 'fig-000004')])
def test_wish_projects_catalogue_holder(client, coll, namespace, number):
    item = coll.item(namespace, number)
    part, color = coll.item('parts', '970c03'), coll.colour('0')
    assert coll.db.execute('SELECT 1 FROM main.item WHERE id=?', (item,)).fetchone() is None
    url = f'/collection/item/{part}/supersets?color={color}'
    before = BeautifulSoup(client.get(url).data, 'html.parser')
    assert before.select_one(f'[data-found-wish="{item}"]')
    response = post(client, csrf(client), 'wish', item_id=item)
    assert response.status_code == 200, response.json
    assert coll.db.execute('SELECT 1 FROM main.item WHERE id=?', (item,)).fetchone()
    after = BeautifulSoup(client.get(url).data, 'html.parser')
    row = next(r for r in after.select('article') if r.select_one(f'a[href="/collection/item/{item}"]'))
    assert 'On wishlist' in row.text
    assert not row.select('[data-found-wish]')


def test_three_figures_with_two_parts_module_and_api(v2, coll):
    figure = coll.item('minifigs', 'fig-999990')
    part, color = coll.item('parts', '970c03'), coll.colour('0')
    with transaction(coll.db):
        made = stock.add_loose(coll.db, item_id=figure, quantity=3, condition='used')
    assert coll.db.execute('SELECT quantity FROM stock_part WHERE stock_id=?', (made['id'],)).fetchone()[0] == 6
    row = next(r for r in supersets.found_in(coll.db, part, color)['results'] if r.get('stock_id') == made['id'])
    assert row['quantity'] == 6
    response = validate(call(v2, f'/items/{part}/supersets?color={color}'), 'get_items_by_id_supersets')
    assert next(r for r in response.json['data'] if r['stock_id'] == made['id'])['quantity'] == 6


def test_mcp_rebrickable_black_zero(adapter):
    result = run_tool(adapter, 'get_part_supersets', dict(provider='rebrickable', kind='part', no='970c03', color=0))
    assert not result.isError, payload(result)
    assert payload(result)


def test_catalogue_only_colour_module_and_api(v2, coll):
    part, color = coll.item('parts', '970c03'), coll.colour('0')
    # Activation eagerly projects colours; reproduce a colour absent from the projection.
    coll.sql('DELETE FROM main.color_link WHERE color_id=?', (color,))
    coll.sql('DELETE FROM main.color WHERE id=?', (color,))
    assert coll.db.execute('SELECT 1 FROM main.color WHERE id=?', (color,)).fetchone() is None
    assert supersets.found_in(coll.db, part, color)['total'] > 0
    response = validate(call(v2, f'/items/{part}/supersets?color={color}'), 'get_items_by_id_supersets')
    assert response.json['color']['id'] == color
    assert coll.db.execute('SELECT 1 FROM main.color WHERE id=?', (color,)).fetchone() is None


def test_owned_set_picture_has_no_part_colour(client, coll, world):
    coll.sql("INSERT INTO picture(item_id,source,kind,local_path,fetched_at) VALUES(?,'bricklink','photo','data/images/set.png','2026-10-26T12:00:00.000Z')", (world.keep,))
    part, color = coll.item('parts', '970c03'), coll.colour('0')
    response = client.get(f'/collection/item/{part}/supersets?color={color}')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    row = next(r for r in soup.select('article') if r.select_one(f'a[href*="copy={world.copy_a}"]'))
    image = row.select_one('img')
    assert image and image['alt'] == 'Syn Castle Keep'
    assert row.select_one('[data-caption]')['data-caption'] == 'Syn Castle Keep'
