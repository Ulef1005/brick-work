"""4.6r on the 4.0 store (M.8c, issue #110): every ported screen uses words for visible numeric differences.

`ROUTES` lists the screens a piece has ported; each piece adds its own (M.8f added the Prices screen and the text its records and details carry;
M.8g the Wishlist and Complete sets screens, with a repair of every kind: ranked, free, outside break-even and needing evidence). Item, lot, wish and Check Set Parts pages are walked from the data (M.8d: the chooser, every copy's
check screen, running and not, and every figure line's; M.8e: the Part Picker and Matcher with each copy selected, the Storage screen of every
storage, the printable lists and the Part to Inventory page; M.8h: the Orders hub, What is this? and an order's four views, see below)."""
import re

from bs4 import BeautifulSoup

from brickwork.core import checker
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)
from tests.test_bw_planning import evidence

SIGN = re.compile(r'(?:^|[\s(\[·])[-−–—]\d')
KINDS = ('sets', 'wishes', 'purchase-places', 'M', 'P', 'I', 'O', 'G', 'B', 'C')
ROUTES = ['/collection/' + kind for kind in KINDS] + ['/manage/add', '/manage/add?type=part&where=wishlist&number=3001', '/workbench/check-parts'] + [
    '/workbench/part-picker', '/workbench/matcher', '/workbench/match', '/workbench/storage', '/workbench/storage/unstored', '/workbench/part-to-inventory',
    '/lists/wishlist/print', '/lists/wishlist.csv', '/planning/prices', '/planning/prices?kind=P', '/planning/wishlist', '/planning/complete-sets',
    '/workbench/orders', '/workbench/what-is-this']


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


def test_the_prices_records_and_details_use_words_for_numeric_differences(world, coll, client, read):
    """The Prices screen is drawn by script from two JSON answers: their display text is held to the same rule as a page."""
    coll.price(world.gate, '12.30', condition='new', guide='stock', minimum='10', maximum='15', sold=3)
    coll.price(world.keep, '25.00', condition='new', minimum='20', maximum='30', sold=5, source='bricklink', slot='bricklink_new', key='S:1000-1')
    texts = []
    data = client.get('/planning/prices/records').get_json()
    for row in data['rows']:
        texts += [str(v) for v in row if isinstance(v, str)]
    with read() as db:
        identities = [(r['item_id'], r['color_id']) for r in db.execute('SELECT DISTINCT item_id, color_id FROM price_current')]
    assert len(identities) > 3
    for item_id, colour in identities:
        details = client.get('/planning/prices/details', query_string=dict(item_id=item_id, **({} if colour is None else {'colour': colour}))).get_json()
        assert details is not None
        texts += [str(details['context'] or ''), str(details['selected'] or ''), *details['conditions']]
        for group in details['groups']:
            texts.append(group['label'])
            for quote in group['quotes']:
                texts += [quote['label'], quote['head'], quote['meta'], quote.get('aria', ''), quote.get('min', ''), quote.get('max', '')]
    assert any('€' in t for t in texts)
    for text in texts:
        assert not SIGN.search(text), text
        assert not re.search(r'\d[–—−]\d', text), text


def test_planning_negative_ratio_and_gain_phrases(coll, client):
    e = evidence(coll)
    coll.sql("UPDATE copy SET current_value='102',current_value_currency='EUR' WHERE id=?", (e.copy,))
    soup = assert_unsigned(client.get('/planning/complete-sets').text, 'negative ratio')
    row = soup.select_one('[data-bp-row]')
    assert '0.15 lost per 1 spent' in row.get_text()
    assert 'net gain €15.50 below' in row.select_one('summary').get_text()
    details = row.select_one('.bp-repair-details').get_text()
    assert 'repair €13.50 · net gain €15.50 below' in details


def test_every_kind_of_repair_row_uses_words(coll, client, read):
    """Ranked, outside break-even (worth less repaired) and needing evidence (a part with no price), and a free repair (no shipping, no fees, loose
    stock covers it): each row's text."""
    from brickwork.core import planning
    e = evidence(coll)
    coll.setting('repair_use_loose_stock', '1')
    outside = coll.add_copy('1000-1', condition='used', current_value='120', current_value_currency='EUR')       # worth more as is than complete
    coll.mark(outside, '3001', '4', missing=1)
    coll.add_stock('part', e.brick, colour=e.red, quantity=4, condition='used')
    unpriced = coll.add_copy('1000-1', condition='used')
    coll.mark(unpriced, '3023', '15', missing=1)                                                                  # no price for a white 3023
    with read() as db:
        groups = {r['group'] for r in planning.ranking(db)['rows']}
    assert {'outside', 'needs_evidence'} <= groups
    soup = assert_unsigned(client.get('/planning/complete-sets').text, 'every kind of repair row')
    assert len(soup.select('[data-bp-row]')) == 3
    for key, value in dict(repair_shipping='0', repair_fees='0', repair_min_order='0').items():
        coll.setting(key, value)
    with read() as db:
        assert 'free_repairs' in {r['group'] for r in planning.ranking(db)['rows']}
    assert_unsigned(client.get('/planning/complete-sets').text, 'free repair')


def test_prices_name_tail(world, coll, client):
    # Names are rendered by bw-prices.js from the records; the runtime harness asserts the non-breaking tail on its row markup.
    coll.price(world.gate, '12.30', condition='new', guide='stock', minimum='10', maximum='15', sold=3)
    data = client.get('/planning/prices/records').get_json()
    assert any(len(r[data['fields'].index('name')].split()) > 1 for r in data['rows'])


def test_the_orders_screens_use_words_for_numeric_differences(world, coll, client):
    """An order in every state its page shows: a draft with an unplaced line, a saved line counted short, an allocation (M.8h)."""
    from brickwork.core import orders
    from tests.test_bw_orders_storage import inventory, line_of, saved
    coll.mark(world.copy_a, '3001', '4', missing=2)
    draft = orders.import_document(coll.db, 'xml', inventory(line_of('P', 'nowhere', colour=5), line_of('P', '3001', colour=5)))
    oid, _, lid = saved(coll.db, inventory(line_of('P', '3001', colour=5, qty=4)))
    orders.received(coll.db, oid, {lid: 3})
    gap = next(g for g in orders.destinations(coll.db, orders.detail(coll.db, oid)['saved'])[lid] if g['copy_id'] == world.copy_a)
    orders.allocate(coll.db, oid, [dict(line_id=lid, target_type='copy', copy_id=gap['copy_id'], target='part', target_id=gap['target_id'], quantity=2)])
    routes = [f'/workbench/orders/{o}?view={view}' for o in (oid, draft['order_id']) for view in ('detail', 'count', 'allocation', 'history')]
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, route
        assert_unsigned(response.text, route)
