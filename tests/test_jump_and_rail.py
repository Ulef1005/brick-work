"""Global jump safety and bounds, rail current-state and tools coverage on the 4.0 store (M.8i part 1: the rail walks every screen; Add's own rail test is
in `test_bw_add.py`, M.8c)."""
import re

import pytest
from bs4 import BeautifulSoup

from brickwork.web.ui import navigation
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)


@pytest.mark.parametrize('path,current', [
    ('/planning/complete-sets', 'Complete sets'), ('/workbench/orders', 'Orders'),
    ('/workbench/storage', 'Storage'),
    ('/planning/prices', 'Prices'), ('/planning/wishlist', 'Wishlist'),
    ('/manage/tools', 'Tools & Admin'),
    ('/workbench/check-parts', 'Check Set Parts'), ('/workbench/matcher', 'Matcher'),
    ('/workbench/part-picker', 'Part Picker'), ('/workbench/part-to-inventory', 'Part to Inventory')])
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
        for expected in ('Sets', 'Minifigures', 'Parts', 'Instructions', 'Boxes', 'Part to Inventory', 'Check Set Parts',
                         'Part Picker', 'Matcher', 'Orders', 'Storage', 'Wishlist', 'Prices', 'Complete sets', 'Add', 'Tools & Admin'):
            assert expected in titles
        assert [link['title'] for link in links if link['active']] == [current]
    response = client.get(path, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(r'aria-current="page">.*?' + re.escape(current).replace('&', '&amp;') + r'</span>.*?</a>', html, re.S)


# The Collection sync and legacy import pages are M.8j's: they answer 503 until then.
LATER = ('/manage/sync', '/manage/import-legacy')


def test_tools_page_links_are_live(client, world):
    html = client.get('/manage/tools').get_data(as_text=True)
    assert 'id="global-jump"' in html and 'class="mobile-bottom"' in html
    assert 'bootstrap' not in html.lower()
    hrefs = {a['href'] for a in BeautifulSoup(html, 'html.parser').select('main a[href^="/"]')}
    assert hrefs
    for href in hrefs:
        if href.startswith(LATER):
            assert client.get(href).status_code == 503, href
        else:
            assert client.get(href).status_code in (200, 302), href
