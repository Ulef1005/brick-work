"""Shared navigation contracts for Lot Sorter and ordering (#412)."""
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'Workbench': ['Part Spotter', 'Set Inspector', 'Lot Sorter', 'Part Runner',
                  'Matchmaker', 'Build Scout', 'Orders', 'Storage'],
    'Planning': ['Wishlist', 'Prices', 'Complete sets', 'Order missing parts'],
}


@pytest.mark.parametrize('path,current,group', [
    ('/workbench/lot-sorter', 'Lot Sorter', 'Workbench'),
    ('/planning/order-missing-parts', 'Order missing parts', 'Planning'),
    ('/planning/order-missing-parts?step=review', 'Order missing parts', 'Planning'),
])
def test_all_shells(client, world, path, current, group):
    response = client.get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, 'html.parser')
    for name, titles in GROUPS.items():
        for selector in [f'[data-rail-group="{name}"]', f'[data-group-panel="{name}"]',
                         f'[data-nav-sheet="{name}"]']:
            panel = soup.select_one(selector)
            assert [n.text for n in panel.select('.nav-title')] == titles
            assert [a.select_one('.nav-title').text for a in panel.select('a[aria-current="page"]')] == ([current] if name == group else [])
    assert soup.select_one('.mobile-bottom [aria-current="true"]')['data-nav-group'] == group
    if current == 'Lot Sorter':
        assert soup.h1.text == 'Lot Sorter'
        assert soup.select_one('[data-bc-default-group="lot"]')
    else:
        assert soup.select_one('a[title="Order missing parts"] svg')


def test_complete_sets_links_to_order_missing_parts(client, world):
    soup = BeautifulSoup(client.get('/planning/complete-sets').text, 'html.parser')
    assert soup.select_one('main a[href="/planning/order-missing-parts"]')


def test_approved_icon_registered(client, world):
    paths = [ROOT / folder / 'lot-sorter.svg' for folder in
             ['design/components/icons', 'static/web/toni/icons', 'static/brickwork/icons-ui']]
    assert len({p.read_bytes() for p in paths}) == 1
    svg = ET.fromstring(paths[0].read_text())
    assert svg.attrib == dict(viewBox='0 0 24 24', fill='none', stroke='currentColor',
                             **{'stroke-width': '1.6', 'stroke-linecap': 'round', 'stroke-linejoin': 'round'})
    assert [n.attrib for n in svg] == [dict(x='3', y='12', width='18', height='8', rx='2'),
                                     dict(d='M9 12v8M15 12v8'), dict(d='M12 9.5V3M9.2 5.8L12 3l2.8 2.8')]
    for folder in ['design/components/icons', 'static/brickwork/icons-ui']:
        sprite = ET.fromstring((ROOT / folder / 'sprite.svg').read_text())
        assert sprite.find("{http://www.w3.org/2000/svg}symbol[@id='bw-lot-sorter']") is not None
    soup = BeautifulSoup(client.get('/workbench/lot-sorter').text, 'html.parser')
    assert soup.select_one('a[title="Lot Sorter"] svg path')['d'] == 'M9 12v8M15 12v8'


def test_selection_uses_ink_on_soft_and_keeps_phone_touch_targets():
    css = (ROOT / 'static/web/toni/shell.css').read_text()
    rule = css.split('/* #412:')[1]
    assert '[href="/workbench/lot-sorter"]' in rule
    assert '[href="/planning/order-missing-parts"]' in rule
    assert 'background:var(--tw-accent-soft);color:var(--tw-text)' in rule
    assert 'min-height:44px' in css
    import re
    assert not re.search(r'(?<![-\w])order\s*:', css)
