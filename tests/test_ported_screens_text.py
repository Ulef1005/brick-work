"""4.6r on the 4.0 store (M.8c, issue #110): every ported screen uses words for visible numeric differences.

`ROUTES` lists the screens a piece has ported; each piece adds its own (the workbench, planning, prices and orders screens are still in
`test_web_unsigned_text.py`, quarantined). Item, lot and wish pages are walked from the data."""
import re

from bs4 import BeautifulSoup

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)

SIGN = re.compile(r'(?:^|[\s(\[·])[-−–—]\d')
KINDS = ('sets', 'wishes', 'purchase-places', 'M', 'P', 'I', 'O', 'G', 'B', 'C')
ROUTES = ['/collection/' + kind for kind in KINDS] + ['/manage/add', '/manage/add?type=part&where=wishlist&number=3001']


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


def test_every_ported_screen(world, client, read):
    routes = list(ROUTES)
    with read() as db:
        routes += [f'/collection/item/{r[0]}' for r in db.execute('SELECT id FROM item ORDER BY id')]
        routes += [f'/collection/lots/{r[0]}' for r in db.execute('SELECT id FROM lot')]
        routes += [f'/collection/wishes/{r[0]}' for r in db.execute('SELECT id FROM wish')]
    assert len(routes) > 20
    for route in routes:
        response = client.get(route, follow_redirects=True)
        assert response.status_code == 200, (route, response.text[-500:])
        assert_unsigned(response.text, route)
