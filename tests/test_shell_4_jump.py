"""Global jump safety and bounds, rail current-state on a 4.0 collection (ported from test_jump_and_rail, M.8b).

The rail test covers the screens ported so far; the paths of screens answering 503 and the tools page stay in `test_jump_and_rail.py`."""
import re

import pytest

from brickwork.web.ui import ROOT, navigation
from tests.app4 import app4, client, coll, pair, read, world


def test_jump_injection_literal_wildcards_empty_and_bound(coll, client):
    malicious = '<img src=x onerror=alert(1)>'
    wanted = coll.add_wish(coll.local('set', malicious, born_key='new-set'))
    response = client.get('/collection/jump?q=new-set')
    assert response.mimetype == 'application/json'
    assert response.json['results'][0]['name'] == malicious
    assert response.json['results'][0]['url'].endswith(wanted)
    source = (ROOT / 'static/web/toni/jump.js').read_text()
    assert 'innerHTML' not in source and 'textContent' in source
    for query in ('', '   ', '%', "'OR1=1--"):
        assert client.get('/collection/jump', query_string={'q': query}).json['results'] == []
    assert len(client.get('/collection/jump', query_string={'q': 'x' * 200}).json['query']) == 100


def test_jump_limit_and_case_folding(coll, client):
    red = coll.colour('4')
    for n in range(25):
        coll.add_stock('part', coll.local('part', f'Älterer Plate {n}'), colour=red, quantity=1, condition='used')
    data = client.get('/collection/jump?q=plate').json
    assert data['limit'] == 20 and len(data['results']) == 20 and data['truncated']
    assert client.get('/collection/jump?q=%C3%A4lterer').json['results']
    assert client.get('/collection/jump?q=PLATE').json['results'] == data['results']


@pytest.mark.parametrize('path,current', [
    ('/collection/sets', 'Sets'), ('/collection/M', 'Minifigures'), ('/collection/P', 'Parts'),
    ('/collection/I', 'Instructions'), ('/collection/O', 'Boxes'), ('/collection/G', 'Gear'),
    ('/collection/wishes', 'Wishlist'), ('/collection/purchase-places', 'Storage')])
def test_rail_destinations_and_current_state(app4, client, world, path, current):
    with app4.test_request_context(path):
        from flask import session
        session['_user_id'] = 'admin'
        session['_fresh'] = True
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session[SESSION_PASSWORD] = password_mark(app4.config['AUTHENTICATION_PASSWORD'])
        app4.preprocess_request()
        groups = navigation()
        assert [name for name, _ in groups] == ['Collection', 'Workbench', 'Planning', 'Manage']
        links = [link for _, links in groups for link in links]
        titles = [link['title'] for link in links]
        for expected in ('Sets', 'Minifigures', 'Parts', 'Instructions', 'Boxes', 'Gear', 'Part to Inventory', 'Check Set Parts',
                         'Part Picker', 'Matcher', 'Orders', 'Storage', 'Wishlist', 'Prices', 'Complete sets', 'Add', 'Tools & Admin'):
            assert expected in titles
        assert [link['title'] for link in links if link['active']] == [current]
    response = client.get(path, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(r'aria-current="page">.*?' + re.escape(current).replace('&', '&amp;') + r'</span>.*?</a>', html, re.S)


def test_item_page_keeps_its_kind_current(client, world):
    response = client.get(f'/collection/item/{world.keep}', follow_redirects=True)
    assert response.status_code == 200
    assert re.search(r'aria-current="page">.*?Sets</span>.*?</a>', response.get_data(as_text=True), re.S)
