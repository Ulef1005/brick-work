"""4.6r: every migrated screen uses words for visible numeric differences."""
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin
from brickwork.web.formatting import difference, money, nowrap_tail, ratio
from tests.test_bw_add import app, apps, bw, legacy, logged_in
from tests.test_bw_admin import reset_shell_metadata_after_test
from tests.test_bw_orders_storage import saved
from tests.test_bw_workbench import gaps
from tests.test_bw_planning import evidence

SIGN = re.compile(r'(?:^|[\s(\[·])[-−–—]\d')


def assert_unsigned(html, route):
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.select_one('[data-web-ui="toni"]'), route
    for node in soup.find_all(string=True):
        if node.parent.name in ('script', 'style'):
            continue
        assert not SIGN.search(str(node)), (route, str(node))
        assert not re.search(r'\d[–—−]\d', str(node)), (route, str(node))
    for node in soup.find_all(True):
        attributes = ['aria-label', 'title', 'alt', 'placeholder']
        if node.name == 'button' or (node.name == 'input' and node.get('type') in ('button', 'submit')):
            attributes.append('value')
        for attr in attributes:
            text = node.get(attr, '')
            assert not SIGN.search(text), (route, attr, text)
            assert not re.search(r'\d[–—−]\d', text), (route, attr, text)
    return soup


# Derived from git diff --name-only for this follow-up. Shared fragments list
# the routes that include them; dynamic order/item routes are appended below.
TEMPLATE_ROUTES = {
    'web/bw_planning.html': ['/planning/prices', '/planning/wishlist', '/planning/complete-sets'],
    'brickwork/collection_modules.html': ['/collection/item/S/new-set', '/collection/item/P/bl-part'],
    'web/bw_collection_detail.html': ['/collection/item/S/new-set'],
    'web/bw_workbench.html': ['/workbench/part-picker', '/workbench/part-picker?copy=copy&pick=1', '/workbench/matcher', '/workbench/match'],
    'web/bw_checker.html': ['/workbench/check-parts', '/workbench/check-parts/copy'],
    'web/bw_ledger_macros.html': ['/workbench/orders', '/workbench/storage/store'],
    'web/bw_orders.html': ['/workbench/orders'],  # detail order appended below
}


def test_every_migrated_screen(app, gaps):
    path, _ = gaps
    with admin.database(path) as db:
        evidence(db)
        with db:
            db.execute("INSERT INTO copies(id,set_no,condition,current_value,current_value_currency) VALUES('value-override','new-set','U','102','EUR')")
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged) SELECT 'value-override',item_type,item_no,color_id,quantity,missing,damaged FROM copy_parts WHERE copy_id='copy'")
    client = logged_in(app)
    routes = ['/collection/sets', '/collection/wishes',
              '/collection/purchase-places']
    routes += [route for routes in TEMPLATE_ROUTES.values() for route in routes]
    routes += ['/collection/' + quote(k, safe='') for k in ('S','M','P','I','O','G','B','C','?')]
    routes += ['/planning/' + s for s in ('prices','wishlist','complete-sets')]
    routes += ['/workbench/' + s for s in (
        'part-picker', 'part-picker?copy=copy', 'part-picker?copy=copy&pick=1',
        'matcher', 'match', 'check-parts', 'check-parts/copy', 'part-to-inventory',
        'orders', 'storage', 'storage/store', 'storage/unstored')]
    routes += ['/manage/' + s for s in (
        'tools','catalogues','jobs','refresh','unresolved','statistics','values',
        'database','settings','appearance','history','instructions','add')]
    with admin.database(path) as db:
        order, _, _ = saved(db)
        routes.append('/workbench/orders/' + str(order))
        for row in db.execute('SELECT item_type,item_no FROM items'):
            routes.append('/collection/item/' + quote(row['item_type'], safe='') + '/' + quote(row['item_no'], safe='') )
        routes += ['/collection/lots/' + quote(r[0], safe='') for r in db.execute('SELECT id FROM lots')]
        routes += ['/collection/wishes/' + str(r[0]) for r in db.execute('SELECT id FROM wishlist')]
    for route in routes:
        response = client.get(route, follow_redirects=True)
        assert response.status_code == 200, (route, response.text[-1000:])
        assert_unsigned(response.text, route)


def test_picker_destination_rows_and_jump(app, gaps):
    client = logged_in(app)
    soup = assert_unsigned(client.get('/workbench/part-picker?copy=copy&pick=1').text, 'picker')
    labels = soup.select('.bw-assignments label > span.mono')
    assert labels
    assert all(re.search(r'\d+ missing$', label.get_text()) for label in labels)
    response = client.get('/collection/jump?q=new-set')
    assert response.status_code == 200
    copies = [copy for row in response.json['results'] for copy in row.get('copies', [])]
    assert copies
    for copy in copies:
        assert re.fullmatch(r'\d+ missing · \d+ damaged', copy['missing_label'])


def test_prices_name_tail(app, bw):
    # Names are rendered by bw-prices.js from the records; the runtime harness asserts the non-breaking tail on its row markup.
    data = logged_in(app).get('/planning/prices/records').get_json()
    assert any(len(r[data['fields'].index('name')].split()) > 1 for r in data['rows'])


@pytest.mark.parametrize('value,expected', [(2,'2 surplus'),(-3,'3 missing'),(0,'0'),(None,'—'),('text','text')])
def test_count_difference(value, expected):
    assert difference(value) == expected


@pytest.mark.parametrize('value,expected', [(2,'€2 above'),(-3,'€3 below'),(0,'€0'),(None,'—'),('text','text')])
def test_money_difference(value, expected):
    assert money(value, signed=True) == expected


@pytest.mark.parametrize('value,expected', [('Technic, Liftarm Thick 1','Technic, Liftarm Thick\u00a01'),("Aaron Fox's Aero Striker", "Aaron Fox's Aero\u00a0Striker"),('Part','Part')])
def test_nowrap_tail(value, expected):
    assert nowrap_tail(value) == expected


@pytest.mark.parametrize('text,forbidden', [('-2',True),(' · −3',True),('(–5',True),('[—2',True),('312-3',False),('3001-old',False),('2026-10-14',False),('2026-10-14T12:00:00',False)])
def test_guard_preserves_identifiers(text, forbidden):
    assert bool(SIGN.search(text)) is forbidden


def test_inventory_text_runtime():
    if not shutil.which('node'):
        pytest.skip('Node is unavailable')
    subprocess.run(['node', str(Path(__file__).with_name('toni_bw_inventory_runtime.cjs'))], check=True)


@pytest.mark.parametrize('value,short,expected', [
    (-.15, False, '0.15 lost per 1 spent'), (.15, False, '0.15 gained per 1 spent'),
    (-.15, True, '0.15× lost'), (.15, True, '0.15× gained'),
    (0, False, '0.00 gained per 1 spent'), (None, False, '—'),
])
def test_ratio(value, short, expected):
    assert ratio(value, short) == expected


@pytest.mark.parametrize('attribute', ['aria-label', 'title', 'alt', 'placeholder', 'value'])
def test_guard_checks_visible_attributes(attribute):
    tag = 'button' if attribute == 'value' else 'span'
    with pytest.raises(AssertionError):
        assert_unsigned(f'<div data-web-ui="toni"><{tag} {attribute}="-2"></{tag}></div>', 'attribute')
    assert_unsigned(f'<div data-web-ui="toni"><{tag} {attribute}="312-3" data-count="-2"></{tag}></div>', 'identifier')


@pytest.mark.parametrize('name,expected', [
    ('Brick 1 x 2', 'Brick 1\u00a0x\u00a02'),
    ('Brick 2 x 4', 'Brick 2\u00a0x\u00a04'),
    ('Brick 1 x 1 x 3', 'Brick 1\u00a0x\u00a01\u00a0x\u00a03'),
])
def test_dimension_names(app, bw, name, expected):
    with admin.database(bw) as db, db:
        db.execute("UPDATE items SET name=? WHERE item_type='P' AND item_no='bl-part'", (name,))
    soup = BeautifulSoup(logged_in(app).get('/collection/item/S/new-set').text, 'html.parser')
    assert expected in [node.get_text() for node in soup.select('strong')]
    assert nowrap_tail(name) == expected
    # The record macro retains the exact, searchable plain-space name.
    import json
    records = [json.loads(node['data-record']) for node in soup.select('[data-record]')]
    assert any(record['name'] == name for record in records)


def test_planning_negative_ratio_and_gain_phrases(app, bw):
    with admin.database(bw) as db:
        evidence(db)
        with db:
            db.execute("UPDATE copies SET current_value='102',current_value_currency='EUR' WHERE id='copy'")
    soup = assert_unsigned(logged_in(app).get('/planning/complete-sets').text, 'negative ratio')
    row = soup.select_one('[data-bp-row]')
    assert '0.15 lost per 1 spent' in row.get_text()
    assert 'net gain €15.50 below' in row.select_one('summary').get_text()
    details = row.select_one('.bp-repair-details').get_text()
    assert 'repair €13.50 · net gain €15.50 below' in details


def test_collection_runtime():
    if not shutil.which('node'):
        pytest.skip('Node is unavailable')
    subprocess.run(['node', str(Path(__file__).with_name('toni_bw_collection_runtime.cjs'))], check=True)
