"""Global jump safety and bounds, rail current-state and tools coverage on the core store."""
import re

import pytest

from brickwork.core import admin
from brickwork.web.ui import ROOT, navigation
from tests.test_bw_collection import bw
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, apps, logged_in


@pytest.mark.parametrize('path,current', [
    ('/planning/complete-sets', 'Complete sets'), ('/workbench/orders', 'Orders'),
    ('/workbench/storage', 'Storage'),
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
