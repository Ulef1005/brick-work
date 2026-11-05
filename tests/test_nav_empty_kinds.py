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
    entries = page.select(f'a[title="{title}"]')
    assert entries and all(a.get('aria-current') == 'page' for a in entries)                  # sidebar and the group strip
    assert page.select_one('a[data-nav-group="Collection"]')['aria-current'] == 'true'        # phone bottom bar
    assert page.select_one('a[data-nav-group="Manage"]')['aria-current'] == 'false'
    assert not page.select_one('[data-group-panel="Collection"]').has_attr('hidden')
    assert page.select_one('[data-group-panel="Manage"]').has_attr('hidden')


def test_an_empty_kind_stays_hidden_on_other_pages(world, client):
    page = shell(client, '/collection/S')
    assert not page.select('a[title="Books"]') and not page.select('a[title="Catalogs"]')
    assert page.select('a[title="Gear"]')                                                     # held, so shown
