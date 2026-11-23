"""An empty kind's page keeps its place in the navigation (#171): the Collection group is active, at every width."""
from bs4 import BeautifulSoup
import pytest

from tests.app4 import app4, client, coll, pair, world


def shell(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


@pytest.mark.parametrize('path,title', [('/collection/B', 'Books'), ('/collection/C', 'Catalogs')])
def test_an_empty_kind_page_marks_its_entry_and_the_collection_group(world, client, path, title):
    page = shell(client, path)                         # the world holds gear but no books or catalogues
    for row in ('nav.sub', 'nav.psub'):                                                       # desktop sub row and phone strip
        entries = [a for a in page.select(f'{row} a') if a.select_one('.nav-title').text == title]
        assert len(entries) == 1 and entries[0].get('aria-current') == 'page' and 'on' in entries[0]['class']
    assert page.select_one('a[data-nav-group="Collection"]')['aria-current'] == 'true'        # phone tab bar
    assert not page.select_one('a[data-nav-group="Manage"]').has_attr('aria-current')
    assert [t.text for t in page.select('nav.tabs a.tab[aria-current="true"]')] == ['Collection']


def test_an_empty_kind_stays_hidden_on_other_pages(world, client):
    page = shell(client, '/collection/S')
    for row in ('nav.sub', 'nav.psub'):
        titles = [a.select_one('.nav-title').text for a in page.select(f'{row} a')]
        assert 'Books' not in titles and 'Catalogs' not in titles
        assert 'Gear' in titles                                                               # held, so shown
