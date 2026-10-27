"""4.6r on the 4.0 store (M.8c, issue #110): every ported screen uses words for visible numeric differences.

`ROUTES` lists the screens a piece has ported; each piece adds its own (the planning and prices screens are still in
`test_web_unsigned_text.py`, quarantined). Item, lot, wish and Check Set Parts pages are walked from the data (M.8d: the chooser, every copy's
check screen, running and not, and every figure line's; M.8e: the Part Picker and Matcher with each copy selected, the Storage screen of every
storage, the printable lists and the Part to Inventory page)."""
import re

from bs4 import BeautifulSoup

from brickwork.core import checker
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)

SIGN = re.compile(r'(?:^|[\s(\[·])[-−–—]\d')
KINDS = ('sets', 'wishes', 'purchase-places', 'M', 'P', 'I', 'O', 'G', 'B', 'C')
ROUTES = ['/collection/' + kind for kind in KINDS] + ['/manage/add', '/manage/add?type=part&where=wishlist&number=3001', '/workbench/check-parts'] + [
    '/workbench/part-picker', '/workbench/matcher', '/workbench/match', '/workbench/storage', '/workbench/storage/unstored', '/workbench/part-to-inventory',
    '/lists/wishlist/print', '/lists/wishlist.csv']


def assert_unsigned(html, route, shell=True):
    soup = BeautifulSoup(html, 'html.parser')
    assert not shell or soup.select_one('[data-web-ui="toni"]'), route
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


def test_every_ported_screen(world, coll, client, read):
    routes = list(ROUTES)
    checker.write(coll.db, world.copy_a, dict(action='start', operation='text-start'))       # one check in progress: its start card and its running screen
    with read() as db:
        routes += [f'/collection/item/{r[0]}' for r in db.execute('SELECT id FROM item ORDER BY id')]
        routes += [f'/collection/lots/{r[0]}' for r in db.execute('SELECT id FROM lot')]
        routes += [f'/collection/wishes/{r[0]}' for r in db.execute('SELECT id FROM wish')]
        routes += [f'/workbench/check-parts/{r[0]}' for r in db.execute('SELECT id FROM copy WHERE archived_at IS NULL')]
        routes += [f'/workbench/check-parts/{r[0]}?run=1' for r in db.execute('SELECT id FROM copy WHERE archived_at IS NULL')]
        routes += [f'/workbench/check-parts/{r[0]}/figure/{r[1]}' for r in db.execute('SELECT copy_id,id FROM copy_figure WHERE retired_at IS NULL')]
        routes += [f'/workbench/part-picker?copy={r[0]}' for r in db.execute('SELECT id FROM copy WHERE archived_at IS NULL')]
        routes += [f'/workbench/part-picker?copy={r[0]}&pick=1' for r in db.execute('SELECT id FROM copy WHERE archived_at IS NULL')]
        routes += [f'/workbench/storage/{r[0]}' for r in db.execute('SELECT id FROM storage')]
        routes += [f'/lists/missing/print?copy={r[0]}' for r in db.execute('SELECT id FROM copy WHERE archived_at IS NULL')]
        routes += [f'/lists/picker/print?copy={r[0]}' for r in db.execute('SELECT id FROM copy WHERE archived_at IS NULL')]
    assert len(routes) > 20
    for route in routes:
        response = client.get(route, follow_redirects=True)
        assert response.status_code == 200, (route, response.text[-500:])
        if route.endswith('.csv'):
            continue
        assert_unsigned(response.text, route, shell=not route.startswith('/lists/'))        # a printable list is a page of its own, without the shell
