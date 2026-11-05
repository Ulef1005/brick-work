"""#180: the list subtitle and the filter panel's Show button use the singular noun for a count of 1."""
import re

import pytest
from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401  (fixtures)


def page(client, route):
    response = client.get(route)
    assert response.status_code == 200, route
    return BeautifulSoup(response.data, 'html.parser')


def texts(client, kind):
    soup = page(client, '/collection/' + kind)
    return soup.select_one('header p.secondary').get_text(' ', strip=True), soup.select_one('[data-bc-apply]').get_text(strip=True)


@pytest.mark.parametrize('kind,add,one,many', [('B', 'book', 'book', 'books'), ('C', 'catalog', 'catalog', 'catalogs')])
def test_book_and_catalog_lists_use_the_singular_for_one(client, coll, world, kind, add, one, many):  # noqa: F811
    coll.add_stock(add, coll.local(add, 'Syn 1', born_key='k-1'), quantity=1, condition='used')
    assert texts(client, kind) == ('1 ' + one, 'Show 1 ' + one)
    coll.add_stock(add, coll.local(add, 'Syn 2', born_key='k-2'), quantity=1, condition='used')
    assert texts(client, kind) == ('2 ' + many, 'Show 2 ' + many)


def test_the_sets_subtitle_says_copy_for_one_copy_and_copies_otherwise(client, world):  # noqa: F811
    subtitle, show = texts(client, 'S')
    match = re.match(r'(\d+) (copy|copies)\b', subtitle)
    assert match and match.group(2) == ('copy' if match.group(1) == '1' else 'copies')
    count = re.match(r'Show (\d+) (set|sets)$', show)
    assert count and count.group(2) == ('set' if count.group(1) == '1' else 'sets')
