"""Global jump safety and bounds, rail current-state and tools coverage on the core store."""
import re

import pytest

from brickwork.core import admin
from brickwork.web.ui import ROOT, navigation
from tests.test_bw_collection import bw
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, apps, logged_in


def test_jump_injection_literal_wildcards_empty_and_bound(app, bw):
    malicious = '<img src=x onerror=alert(1)>'
    with admin.database(bw) as db, db:
        db.execute("UPDATE items SET name=? WHERE item_type='S' AND item_no='new-set'", (malicious,))
    client = logged_in(app)
    response = client.get('/collection/jump?q=new-set')
    assert response.mimetype == 'application/json'
    assert response.json['results'][0]['name'] == malicious
    source = (ROOT / 'static/web/toni/jump.js').read_text()
    assert 'innerHTML' not in source and 'textContent' in source
    for query in ('', '   ', '%', "'OR1=1--"):
        assert client.get('/collection/jump', query_string={'q': query}).json['results'] == []
    assert len(client.get('/collection/jump', query_string={'q': 'x' * 200}).json['query']) == 100


def test_jump_limit_and_case_folding(app, bw):
    with admin.database(bw) as db, db:
        db.execute("UPDATE items SET name='Älterer Plate' WHERE item_type='P' AND item_no='bl-part'")
        db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P','bl-part',11,1,'U')",
                       [(f'jump-{n}',) for n in range(25)])
    client = logged_in(app)
    data = client.get('/collection/jump?q=plate').json
    assert data['limit'] == 20 and len(data['results']) <= 20
    assert client.get('/collection/jump?q=%C3%A4lterer').json['results']
    assert client.get('/collection/jump?q=PLATE').json['results'] == data['results']


@pytest.mark.parametrize('path,current', [
    ('/collection/sets', 'Sets'), ('/collection/item/S/new-set', 'Sets'),
    ('/collection/M', 'Minifigures'), ('/collection/P', 'Parts'),
    ('/collection/I', 'Instructions'), ('/collection/O', 'Boxes'),
    ('/planning/complete-sets', 'Complete sets'), ('/workbench/orders', 'Orders'),
    ('/workbench/storage', 'Storage'), ('/collection/wishes', 'Wishlist'),
    ('/planning/prices', 'Prices'), ('/planning/wishlist', 'Wishlist'),
    ('/manage/add', 'Add'), ('/manage/tools', 'Tools & Admin'),
    ('/workbench/check-parts', 'Check Set Parts'), ('/workbench/matcher', 'Matcher'),
    ('/workbench/part-picker', 'Part Picker'), ('/workbench/part-to-inventory', 'Part to Inventory')])
def test_rail_destinations_and_current_state(app, bw, path, current):
    with app.test_request_context(path):
        from flask import session
        session['_user_id'] = 'admin'
        session['_fresh'] = True
        from brickwork.web.auth import SESSION_PASSWORD, password_mark
        session[SESSION_PASSWORD] = password_mark(app.config['AUTHENTICATION_PASSWORD'])
        app.preprocess_request()
        groups = navigation()
        assert [name for name, _ in groups] == ['Collection', 'Workbench', 'Planning', 'Manage']
        links = [link for _, links in groups for link in links]
        titles = [link['title'] for link in links]
        for expected in ('Sets', 'Minifigures', 'Parts', 'Instructions', 'Boxes', 'Part to Inventory', 'Check Set Parts',
                         'Part Picker', 'Matcher', 'Orders', 'Storage', 'Wishlist', 'Prices', 'Complete sets', 'Add', 'Tools & Admin'):
            assert expected in titles
        assert [link['title'] for link in links if link['active']] == [current]
    response = logged_in(app).get(path, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(r'aria-current="page">.*?' + re.escape(current).replace('&', '&amp;') + r'</span>.*?</a>', html, re.S)


def test_tools_page_links_are_live(app, bw):
    from bs4 import BeautifulSoup
    client = logged_in(app)
    html = client.get('/manage/tools').get_data(as_text=True)
    assert 'id="global-jump"' in html and 'class="mobile-bottom"' in html
    assert 'bootstrap' not in html.lower()
    hrefs = {a['href'] for a in BeautifulSoup(html, 'html.parser').select('main a[href^="/"]')}
    assert hrefs
    for href in hrefs:
        assert client.get(href).status_code in (200, 302), href
