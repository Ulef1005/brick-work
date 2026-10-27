"""4.6r: every migrated screen uses words for visible numeric differences (ported from test_web_unsigned_text, M.8b).

Ported here: the formatter and guard tests, the two node harnesses, the collection screens that read only the 4.0 collection (lists, item
pages, wish pages, lots, purchase places), the jump search and the dimension names on the item page. Stay in `test_web_unsigned_text.py`:
the Add, orders, workbench and planning screens (M.8c, M.8e, M.8g, M.8h); `test_ported_screens_text.py` walks them."""
import re
import shutil
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from brickwork.web.formatting import difference, money, nowrap_tail, ratio
from tests.app4 import RICH, app4, client, coll, make_pair, read, world

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


def test_every_migrated_screen(client, world, read):
    """The collection's read-side screens: lists, wishes, places, every item page, lots and wishes by id."""
    routes = ['/', '/collection/sets', '/collection/wishes', '/collection/purchase-places']
    routes += ['/collection/' + k for k in ('S', 'M', 'P', 'I', 'O', 'G', 'B', 'C')]
    with read() as db:
        for (identifier,) in db.execute('SELECT id FROM main.item ORDER BY id'):
            routes.append(f'/collection/item/{identifier}')
        for (colour,) in db.execute('SELECT DISTINCT color_id FROM stock WHERE kind="part"'):
            routes.append(f'/collection/item/{world.brick}?colour={colour}')
        routes += ['/collection/lots/' + r[0] for r in db.execute('SELECT id FROM lot')]
        routes += ['/collection/wishes/' + r[0] for r in db.execute('SELECT id FROM wish')]
        routes.append(f'/collection/item/{world.keep}?copy={world.copy_a}')
    routes.append('/collection/item/S/1000-1')                      # the old number URL redirects
    for route in routes:
        response = client.get(route, follow_redirects=True)
        assert response.status_code == 200, (route, response.text[-1000:])
        assert_unsigned(response.text, route)


def test_jump_missing_labels_are_words(client, world):
    response = client.get('/collection/jump?q=1000-1')
    assert response.status_code == 200
    copies = [copy for row in response.json['results'] for copy in row.get('copies', [])]
    assert copies
    for copy in copies:
        assert re.fullmatch(r'\d+ missing · \d+ damaged', copy['missing_label'])


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


@pytest.fixture
def pair(tmp_path):
    """The rich fixture catalogue with three invented parts (`syn`) named by dimensions, all in the set 1000-1."""
    names = {'syn9991': 'Brick 1 x 2', 'syn9992': 'Brick 2 x 4', 'syn9993': 'Brick 1 x 1 x 3'}
    return make_pair(tmp_path, rich=True, extra_dump={'parts': [[number, name, 11, 'Plastic'] for number, name in names.items()],
                                                      'inventory_parts': RICH['inventory_parts'] + [[9001, number, 4, 1, 'False', ''] for number in names]})


@pytest.mark.parametrize('name,expected', [
    ('Brick 1 x 2', 'Brick 1\u00a0x\u00a02'),
    ('Brick 2 x 4', 'Brick 2\u00a0x\u00a04'),
    ('Brick 1 x 1 x 3', 'Brick 1\u00a0x\u00a01\u00a0x\u00a03'),
])
def test_dimension_names(coll, client, name, expected):
    coll.add_copy('1000-1')
    soup = BeautifulSoup(client.get(f'/collection/item/{coll.item("sets", "1000-1")}').text, 'html.parser')
    assert expected in [node.get_text() for node in soup.select('strong')]
    assert nowrap_tail(name) == expected
    # The record macro retains the exact, searchable plain-space name.
    import json
    records = [json.loads(node['data-record']) for node in soup.select('[data-record]')]
    assert any(record['name'] == name for record in records)


def test_collection_runtime():
    if not shutil.which('node'):
        pytest.skip('Node is unavailable')
    subprocess.run(['node', str(Path(__file__).with_name('toni_bw_collection_runtime.cjs'))], check=True)
