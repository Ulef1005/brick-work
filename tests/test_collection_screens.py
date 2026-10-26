"""The collection's read side on a 4.0 collection (M.8b, issue #110): the list screens, the shared item-page modules, jump search, purchase
places, the list payload and its cost, and the CSS and browser-geometry contracts. First half of the ports of `test_bw_collection.py`
(the writes of that file stay with M.8c to M.8e). Invented data only, no network."""
from itertools import count
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection
from tests.app4 import STAMP, app4, client, coll, pair, read, world  # noqa: F401  (the fixtures)

ROOT = Path(__file__).resolve().parents[1]


def soup_of(response):
    return BeautifulSoup(response.data, 'html.parser')


def records(response):
    """The rows of a list screen as dicts by field name, from its embedded `data-bc-records`."""
    data = json.loads(soup_of(response).select_one('[data-bc-records]').string)
    return [dict(zip(data['fields'], [r.get(str(i)) for i in range(len(data['fields']))])) for r in data['rows']]


_ids = count(2_000_000_000)


def bulk(db, kind, number, *, colour=None, prefix='bulk', born='bricklink'):
    """`number` local BrickLink-born items of a kind, each held once (a set as a copy without lines, any other kind as a stock line),
    in two executemany calls and one commit. The fast way to a big collection. Returns the item ids. `born='rebrickable'` gives them
    Rebrickable numbers, as most items have (BrickLink-born ones carry a `source` mark in every list record)."""
    letter = {'set': 'S', 'part': 'P', 'minifigure': 'M', 'instructions': 'I', 'box': 'O', 'gear': 'G', 'book': 'B', 'catalog': 'C'}[kind]
    first = [next(_ids) for _ in range(number)]
    db.executemany("""INSERT INTO item(id,origin,kind,kind_source,name,born_provider,born_namespace,born_key,created_at,updated_at)
                      VALUES(?,'local',?,?,?,?,?,?,?,?)""",
                   [(i, kind, 'namespace' if born == 'rebrickable' else 'bricklink', f'Collection item {n}', born,
                     {'set': 'sets', 'part': 'parts', 'minifigure': 'minifigs'}.get(kind, letter) if born == 'rebrickable' else letter,
                     f'{prefix}-{n}', STAMP, STAMP) for n, i in enumerate(first)])
    if kind == 'set':
        db.executemany("INSERT INTO copy(id,item_id,inventory_source,inventory_digest,created_at,updated_at) VALUES(?,?,'none','none',?,?)",
                       [(f'{prefix}-copy-{i}', i, STAMP, STAMP) for i in first])
    else:
        source = ('none', 'none') if kind == 'minifigure' else (None, None)
        db.executemany("INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,inventory_source,inventory_digest,created_at,updated_at) VALUES(?,?,?,?,1,'used',?,?,?,?)",
                       [(f'{prefix}-stock-{i}', kind, i, colour if kind == 'part' else None, *source, STAMP, STAMP) for i in first])
    db.commit()
    return first


def traced(db, call):
    """`(number of statements, result, statements)` of a call."""
    queries = []
    db.set_trace_callback(queries.append)
    try:
        result = call()
    finally:
        db.set_trace_callback(None)
    return len(queries), result, queries


@pytest.mark.parametrize('path', ['/', '/collection/sets', '/collection/M', '/collection/P', '/collection/I', '/collection/O', '/collection/G',
                                  '/collection/B', '/collection/C', '/collection/wishes'])
def test_lists_in_shell(world, client, path):
    r = client.get(path)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers['Cache-Control'] == 'no-store'
    soup = soup_of(r)
    assert soup.select_one('[data-web-ui="toni"]')
    assert soup.select_one('[data-bc-search]') and soup.select_one('[data-bc-sort]')
    assert soup.select_one('a[href="/collection/sets"]')
    assert b'https://example.test/part' not in r.data


def test_the_unidentified_kind_has_no_screen_of_its_own(world, client):
    """3.3's `?` placeholder type is gone: an unidentified item sits on its own kind's screen, marked Unidentified."""
    assert client.get('/collection/%3F').status_code == 404
    rows = records(client.get('/collection/G'))
    assert [(r['name'], r['unresolved']) for r in rows] == [('Mystery thing', True)]


def test_purchase_places_in_shell(world, client):
    r = client.get('/collection/purchase-places')
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    soup = soup_of(r)
    assert soup.select_one('[data-web-ui="toni"]') and soup.select_one('a[href="/collection/sets"]')
    assert any(l['href'].split('?')[0].endswith('bw-storage.css') for l in soup.select('link[rel=stylesheet]'))
    assert any(x['src'].split('?')[0].endswith('bw-ledger.js') for x in soup.select('script[src]'))
    assert soup.select_one('[data-search]') and soup.select_one('[data-sort]') and soup.select_one('[data-filters]') and soup.select_one('[data-rows] [data-row]')
    assert b'https://example.test/part' not in r.data


@pytest.mark.parametrize('kind', ['S', 'M', 'P', 'G', 'I', 'O', 'B', 'C'])
def test_shared_detail_modules(world, coll, client, kind):
    """Every kind's item page is built of the same modules (the Matching module is the Matcher's, M.8e)."""
    if kind in 'OBC':
        word = {'O': 'box', 'B': 'book', 'C': 'catalog'}[kind]
        item = coll.local(word, 'Fixture item', born_key='fixture-item')
        coll.add_stock(word, item, quantity=1)
        query = ''
    else:
        item, query = {'S': (world.keep, ''), 'M': (world.figure, f'?stock={world.stock_figure}'), 'P': (world.brick, f'?colour={world.red}'),
                       'G': (world.mystery, ''), 'I': (world.local_booklet, '')}[kind]
    r = client.get(f'/collection/item/{item}{query}')
    assert r.status_code == 200, r.get_data(as_text=True)
    soup = soup_of(r)
    assert [x['data-module'] for x in soup.select('[data-module]')] == (
        ['status', 'consists', 'used-in', 'prices', 'wanted', 'info'] if kind == 'M' else ['info', 'prices'] if kind == 'P' else
        ['info', 'prices', 'consists'])
    layout = soup.select_one('.bc-detail-layout')
    assert [child.name for child in layout.find_all(recursive=False)] == (['div', 'aside'] if kind == 'M' else ['aside', 'div'])
    assert layout.select_one('aside [data-module=info]')
    assert not layout.select('.bc-own-photos,.bc-detail-instances')
    panel = soup.select_one('dialog#bc-edit')
    if panel:
        sections = [h.get_text() for h in panel.select('.bc-edit-section > h3')]
        assert any(x.startswith('Instances') for x in sections) and 'Own photos' in sections
    message = soup.select_one('[data-bc-message]')
    assert message['role'] == 'status' and not message.has_attr('hidden')


def test_an_unidentified_item_has_the_shared_modules_and_says_so(world, client):
    """3.3's `?` placeholder page: the same item page, marked Unidentified and linked to the unresolved items."""
    soup = soup_of(client.get(f'/collection/item/{world.mystery}?stock={world.stock_mystery}'))
    assert [x['data-module'] for x in soup.select('[data-module]')] == ['info', 'prices', 'consists']
    assert 'Unidentified' in soup.get_text() and 'Unresolved' in soup.get_text()
    assert soup.select_one('.bc-detail-hero h1').get_text().endswith('(unidentified)')


def test_lot_page_and_archived_storage_filter_and_purchase_place_totals(coll, client):
    """The read half of 3.3's lot / storage / places test (its saves stay with M.8d)."""
    coll.storage('Old place', id='archived', archived_at='2026-01-01')
    lot = coll.lot('Pile A', note='Private lot note')
    coll.add_stock('part', coll.item('parts', '3001'), colour=coll.colour('4'), quantity=3, lot=lot)
    shop = coll.place('Shop')
    coll.add_copy('1000-1', place=shop, price='12.345', currency='')
    coll.add_copy('1000-1', place=shop, price='10', currency='EUR')
    r = client.get(f'/collection/lots/{lot}')
    assert r.status_code == 200 and b'Private lot note' in r.data
    soup = soup_of(client.get('/collection/P'))
    assert soup.select('[data-bc-filter="storage"] option') and not soup.select('[data-bc-filter="storage"] option[value="archived"]')
    places = collection.purchase_places(coll.db)
    assert [(p['name'], p['count']) for p in places] == [('Shop', 2)]
    assert places[0]['totals'] == {'Currency not recorded': collection.Decimal('12.345'), 'EUR': collection.Decimal('10')}


@pytest.mark.parametrize('kind', list(collection.TYPES))
def test_list_query_count_is_constant(coll, kind):
    """The cost of a list screen does not grow with the collection: `listing` and `options` read in a fixed number of statements."""
    word, red = collection.TYPE_KIND[kind], coll.colour('4')
    bulk(coll.db, word, 100, colour=red, prefix='small')
    small, rows, _ = traced(coll.db, lambda: collection.listing(coll.db, kind))
    small_options, _, _ = traced(coll.db, lambda: collection.options(coll.db))
    assert len(rows) == 100
    bulk(coll.db, word, 200, colour=red, prefix='large')
    large, rows, _ = traced(coll.db, lambda: collection.listing(coll.db, kind))
    large_options, _, _ = traced(coll.db, lambda: collection.options(coll.db))
    assert len(rows) == 300
    assert large == small and large < 25
    assert large_options == small_options and large_options < 10


def test_jump_has_only_item_id_links(world, client):
    r = client.get('/collection/jump?q=1000-1')
    assert r.status_code == 200, r.json
    found = r.json['results'][0]
    assert found['kind'] == 'set' and found['number'] == '1000-1'
    copies = found['copies']
    assert {c['url'] for c in copies} == {f'/collection/item/{world.keep}?copy={c}' for c in (world.copy_a, world.copy_b)}
    assert all(c['check_url'] == f'/workbench/check-parts/{c["id"]}' for c in copies)
    r = client.get('/collection/jump?q=3001')
    assert r.status_code == 200, r.json
    assert r.json['results'][0]['url'] == f'/collection/item/{world.brick}?colour={world.red}'
    assert r.headers['Cache-Control'] == 'no-store'
    assert b'data-url="/collection/jump"' in client.get('/').data


def test_jump_takes_either_number_and_a_local_item_by_its_own(world, client):
    """The born number, a BrickLink number beside it (`970c00` for `970c03`) and a local BrickLink-born item's own number all find the item."""
    by_either = [{r['number'] for r in client.get('/collection/jump?q=' + q).json['results']} for q in ('x999', 'only')]
    assert by_either == [{'x999 (BrickLink)'}, {'x999 (BrickLink)'}]
    for query in ('970c03', '970c00'):
        assert [r['number'] for r in client.get('/collection/jump?q=' + query).json['results']] == ['970c03 · BrickLink 970c00']
    wish = client.get('/collection/jump?q=1000-2').json['results']
    assert [r['kind'] for r in wish] == ['wanted']
    assert wish[0]['url'] == f'/collection/wishes/{world.wish_set}'


def test_metadata_priority_prices_ranges_and_consolidation(coll):
    brick, red = coll.item('parts', '3001'), coll.colour('4')
    coll.prop(brick, 'material', 'ABS', source='bricklink')
    coll.prop(brick, 'material', 'Other', source='rebrickable')
    coll.setting('source_priority', json.dumps({'metadata': {'part': ['bricklink', 'rebrickable']}}))
    coll.sql("INSERT INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',30)")
    coll.price(brick, '3', colour=red, condition='used', minimum='1', maximum='5', sold=8, observed='2022-01-01T00:00:00.000Z')
    coll.add_stock('part', brick, colour=red, quantity=3, condition='used')
    coll.add_stock('part', brick, colour=red, quantity=2, condition=None)
    d = collection.detail(coll.db, brick, colour=red)
    assert d['properties']['material']['value'] == 'ABS'
    assert d['properties']['material']['alternatives'][0]['value'] == 'Other'
    assert d['prices'][0]['range'] == 50 and d['prices'][0]['stale']
    assert sum(r['quantity'] for r in d['consolidated']) == 5
    assert sum(len(r['lines']) for r in d['consolidated']) == 2


def test_jump_queries_are_bounded(coll):
    """The Matcher's half of 3.3's bound test stays with M.8e; the jump search reads in a fixed number of statements however much is held."""
    red = coll.colour('4')
    bulk(coll.db, 'part', 20, colour=red, prefix='part')
    small, _, _ = traced(coll.db, lambda: collection.search(coll.db, 'part'))
    bulk(coll.db, 'part', 300, colour=red, prefix='part-more')
    large, found, _ = traced(coll.db, lambda: collection.search(coll.db, 'part'))
    assert found['truncated'] and len(found['results']) == 20
    assert large == small and small < 25


def test_detail_links_are_canonical_and_no_nested_links(world, coll, client):
    """Every item of the world has a page by its id (a part by its held colour), without a link inside a link."""
    items = [dict(r) for r in coll.db.execute('SELECT id,kind FROM main.item')]
    assert len(items) > 10
    shown = 0
    for item in items:
        r = client.get(f'/collection/item/{item["id"]}', query_string={'colour': world.red} if item['kind'] == 'part' else {})
        if r.status_code == 200:
            shown += 1
            assert not soup_of(r).select('a a'), item
    assert shown >= 8


def test_parts_listing_shape_and_query_count(world, coll):
    """Parts listing on 4.0 (replaces 3.3's byte-for-byte gate baseline, a 3.3 snapshot): a row is an item in a colour with its owned
    instances grouped, its counts in sets and its used-sold quote, in a fixed number of statements."""
    n, rows, queries = traced(coll.db, lambda: collection.listing(coll.db, 'P'))
    by_number = {(r['number'], r['color_name']): r for r in rows}
    assert len(rows) == len(by_number) and ('3001', 'Red') in by_number and ('x999', 'Red') in by_number
    brick = by_number['3001', 'Red']
    assert (brick['item_id'], brick['color_id'], brick['kind'], brick['item_type']) == (world.brick, world.red, 'part', 'P')
    assert (brick['quantity'], brick['in_sets'], brick['missing'], sorted(brick['conditions']), len(brick['instances'])) == (5, 8, 1, ['new', 'used'], 2)
    assert brick['price']['price'] == '0.40' and brick['price']['condition'] == 'used' and brick['price']['guide'] == 'sold'
    assert by_number['3023', 'White']['quantity'] == 2 and by_number['3023', 'White']['price'] is None
    held_only_in_sets = [r for r in rows if not r['quantity']]
    assert held_only_in_sets and all(r['in_sets'] and r['instances'] == [] for r in held_only_in_sets)
    assert by_number['x999', 'Red']['number_text'] == 'x999 (BrickLink)' and by_number['x999', 'Red']['number_source'] == 'bricklink'
    assert n < 25, n                   # 3.3 pinned 14; the catalogue probes and the identity load are statements of their own now
    # Unrelated catalogue rows must not reach Python: one read of properties and one of pictures, each for the listed items only.
    property_reads = [q for q in queries if 'FROM item_property' in q]
    assert len(property_reads) == 1 and 'item_id IN' in property_reads[0]
    image_reads = [q for q in queries if 'FROM picture' in q]
    assert len(image_reads) == 1 and 'json_each' in image_reads[0]


def test_parts_listing_preserves_unfiltered_instance_order(coll, monkeypatch):
    red = coll.colour('4')
    coll.add_stock('part', coll.item('parts', '3001'), colour=red)
    for number in ['z-part', 'a-part', 'part-10', 'part-2']:
        coll.add_stock('part', coll.local('part', number, born_key=number), colour=red)
    actual = collection.listing(coll.db, 'P')
    original = collection.instances
    with monkeypatch.context() as patch:
        patch.setattr(collection, 'instances', lambda db, kind=None, **kw: [r for r in original(db) if kind is None or r['kind'] == kind])
        expected = collection.listing(coll.db, 'P')
    assert actual == expected
    assert [r['number'] for r in actual][:5] == ['3001', 'z-part', 'a-part', 'part-10', 'part-2']


def test_collection_response_budget(coll, client):
    """A large collection (7,441 parts, 195 sets, 600 figures): route bytes and SQL cost (also a local benchmark)."""
    import time
    from statistics import median
    red = coll.colour('4')
    bulk(coll.db, 'part', 5, colour=red, prefix='few')
    few, _, _ = traced(coll.db, lambda: (collection.listing(coll.db, 'P'), collection.options(coll.db)))
    for kind, number in [('part', 7441), ('set', 195), ('minifigure', 600)]:
        bulk(coll.db, kind, number, colour=red, prefix='bench', born='rebrickable')
    for kind in ['P', 'S', 'M']:
        times = []
        for _ in range(5):
            start = time.perf_counter()
            response = client.get('/collection/' + kind)
            times.append(time.perf_counter() - start)
        print(f'Collection {kind}: {median(times):.6f}s, {len(response.data)} bytes')
        assert response.status_code == 200
        if kind == 'P':
            part_bytes = len(response.data)
    assert part_bytes < 1_500_000
    n, _, _ = traced(coll.db, lambda: (collection.listing(coll.db, 'P'), collection.options(coll.db)))
    assert n == few and n < 30


def test_list_records_are_script_safe_and_display_only(world, coll, client):
    name = '</script><img src=x onerror="alert(1)"> & a name'
    coll.sql('UPDATE item SET name=? WHERE id=?', (name, world.local_part))
    response = client.get('/collection/P')
    soup = soup_of(response)
    data = json.loads(soup.select_one('[data-bc-records]').string)
    assert not soup.select('[data-bc-row]')
    assert not soup.select('img[onerror]')
    assert any(r['name'] == name for r in records(response))
    assert 'note' not in data['fields'] and 'instances' not in data['fields']


def test_list_payload_preserves_colour_zero():
    from brickwork.core.list_records import payload
    data = json.loads(str(payload([{'item_type': 'P', 'item_no': 'zero', 'color_id': 0}])))
    assert data['rows'][0][str(data['fields'].index('color_id'))] == 0


@pytest.mark.parametrize('missing,damaged,label', [(0, 0, ''), (3, 0, '3 missing'), (0, 1, '1 damaged'), (3, 1, '3 missing · 1 damaged')])
def test_defect_formatter_and_browser_payload(missing, damaged, label):
    from brickwork.core.list_records import payload
    assert collection.defects(missing, damaged) == label
    data = json.loads(payload([dict(item_type='P', item_no='3022', missing=missing, damaged=damaged)]))
    assert data['rows'][0].get(str(data['fields'].index('defects')), '') == label


@pytest.mark.parametrize('name', ['', 'Named part'])
def test_identity_macro_and_detail_heading(world, coll, client, app4, name):
    """The number appears once in the heading block: beside a name, or as the heading when the item has none."""
    coll.sql('UPDATE item SET name=?,category_name=NULL,year=1968 WHERE id=?', (name, world.local_part))
    coll.sql("UPDATE color SET rgb='FFFFFF' WHERE id=?", (world.red,))
    soup = soup_of(client.get(f'/collection/item/{world.local_part}?colour={world.red}'))
    hero = soup.select_one('.bc-detail-hero')
    for picture in hero.select('.bc-hero-picture'):         # the placeholder of a missing picture names the item too
        picture.decompose()
    assert hero.get_text(' ', strip=True).split().count('x999') == 1
    assert hero.h1.get_text() == (name or 'x999 (BrickLink)').replace(' ', ' ')
    assert '· 1968' not in hero.get_text()
    assert 'background:#FFFFFF' in str(hero.select_one('.bc-colour'))
    assert 'color:#1A1816' in str(hero.select_one('.bc-colour'))
    assert not hero.select_one('.bc-colour-tile')
    assert '−0 missing' not in soup.get_text()
    with app4.test_request_context():
        macro = app4.jinja_env.get_template('web/toni/brickwork/collection_modules.html').module.identity
        row = dict(item_type='S', item_no='312-3', number_text='312-3', name=name or None, year=1968, category=None, theme=None)
        identity = BeautifulSoup(str(macro(row)), 'html.parser')
        assert identity.get_text(' ', strip=True).split().count('312-3') == 1
        assert identity.select_one('strong') is not None if name else identity.select_one('strong') is None
        assert identity.select_one('.secondary').get_text() == '1968'


def test_missing_static_falls_back(app4):
    from brickwork.web.ui import bw_static
    with app4.test_request_context():
        assert bw_static('web/toni/missing-45u.css').endswith('/static/web/toni/missing-45u.css')


def test_review_collection_controls_and_source_disclosure(world, coll, client):
    soup = soup_of(client.get('/'))
    assert soup.select_one('.bc-status-strip')
    assert [b['data-bc-status'] for b in soup.select('[data-bc-status]')] == ['', 'sealed', 'complete', 'incomplete', 'unknown']
    assert len(soup.select('.bc-toolbar [data-bc-search]')) == 1
    assert soup.select_one('[data-bc-panel] [data-bc-group]')
    assert soup.select_one('[data-bc-sort-panel] [data-bc-direction]')
    assert soup.select_one('[data-bc-view=grid]')['aria-label'] == 'Grid'
    coll.prop(world.keep, 'source_modified_at', 'Recorded timestamp', source='rebrickable')
    coll.prop(world.keep, 'name', 'Alternative name', source='rebrickable')
    coll.tag('copy', world.copy_a, world.box)
    coll.tag('copy', world.copy_a, world.booklet_flag)
    soup = soup_of(client.get(f'/collection/item/{world.keep}?copy={world.copy_a}'))
    info = soup.select_one('[data-module=info]')
    assert not info.select_one('.bc-source-details')
    disclosure = soup.select_one('#bc-edit .bc-source-details')
    assert disclosure and not disclosure.has_attr('open')
    assert 'Recorded timestamp' in disclosure.get_text()
    assert 'Alternative name' in disclosure.get_text()
    visible = info.find('dl', recursive=False)
    facts = {f.dt.get_text(): f.dd.get_text() for f in visible.select('.bc-fact')}
    assert facts['Parts check'] == 'Checked' and facts['Box'] == facts['Instructions'] == 'Yes'
    assert [b.get_text() for b in soup.select('[data-bc-tab]')][1:] == ['Minifigures', 'Instructions & Box']
    assert soup.select_one('[data-bc-tab=parts] .bc-tab-count')
    assert soup.select_one('[data-module=consists] [aria-label="Copy progress"]')
    soup = soup_of(client.get(f'/collection/item/{world.brick}?colour={world.red}'))
    assert not soup.select('[data-module=consists]')
    # 3.3 put the Matching module after the prices; it is the Matcher's now (M.8e)
    assert [m['data-module'] for m in soup.select('[data-module]')] == ['info', 'prices']


@pytest.mark.parametrize('viewer', ['read_only', 'anonymous'])
def test_run4_readonly_source_details(world, coll, app4, viewer):
    coll.prop(world.keep, 'source_modified_at', 'Recorded timestamp', source='rebrickable')
    coll.prop(world.keep, 'name', 'Alternative name', source='rebrickable')
    expected = collection.detail(coll.db, world.keep, copy_id=world.copy_a)['properties']
    if viewer == 'read_only':
        from tests.web_fixtures import logged_in
        app4.config['BW_READ_ONLY'] = True
        client = logged_in(app4)
    else:
        # Collection pages need a session (see test_auth_guard); an anonymous viewer is sent to the login page.
        anonymous = app4.test_client().get(f'/collection/item/{world.keep}?copy={world.copy_a}')
        assert anonymous.status_code == 302 and '/login' in anonymous.location
        return
    response = client.get(f'/collection/item/{world.keep}?copy={world.copy_a}')
    assert response.status_code == 200
    soup = soup_of(response)
    action = soup.select_one('[data-module=info] [data-bw-open=bc-edit]')
    assert action.get_text(strip=True) == 'Details' and action.select_one('svg')
    dialog = soup.select_one('#bc-edit')
    disclosure = dialog.select_one('.bc-source-details')
    assert not disclosure.has_attr('open')
    assert 'Recorded timestamp' in disclosure.get_text()
    assert 'Alternative name' in disclosure.get_text()
    for prop in expected.values():
        for recorded in [prop, *prop.get('alternatives', [])]:
            assert str(recorded['value']) in disclosure.get_text()
            assert recorded['source'] in disclosure.get_text()
            if recorded['fetched_at']:
                assert recorded['fetched_at'] in disclosure.get_text()
    assert not dialog.select('form, input, select, textarea, [data-bw-open=bc-delete]')
    assert [b.get_text(strip=True) for b in dialog.select('button')] == ['Close', 'Copy details']      # the second only chooses among the set's two copies
    assert not soup.select_one('#bc-delete')


def test_collection_money_formatter_is_shared_and_lossless():
    from brickwork.web.ui import bw_age, bw_collection_records, bw_price_order
    from brickwork.web.formatting import money
    assert money('189.0', 'EUR', fixed=True) == '€189.00'
    assert money('12.5144', 'EUR', fixed=True) == '€12.51'
    assert money('0', 'USD', fixed=True) == '$0.00'
    assert bw_age('2026-10-08T23:00:00Z') == '8 Oct'
    assert bw_age(None) == 'Age not recorded'
    row = dict(item_type='S', item_no='312-3', price=dict(currency='EUR', price='12.5144', age='2026-10-08', stale=True))
    data = json.loads(bw_collection_records([row]))
    price = data['rows'][0][str(data['fields'].index('price'))]
    assert price == ['EUR', '12.5144', '2026-10-08', True, '€12.51', '8 Oct']
    assert [p['condition'] for p in bw_price_order([{'condition': None}, {'condition': 'new'}, {'condition': 'used'}])] == ['used', 'new', None]


@pytest.mark.parametrize('kind', ['S', 'M', 'P', 'I'])
def test_collection_payload_built_once_per_request(world, client, monkeypatch, kind):
    from brickwork.web import ui
    from brickwork.core import list_records
    from types import SimpleNamespace
    original = ui.bw_collection_records
    original_dumps = list_records.json.dumps
    serializations = []

    def dumps(*args, **kwargs):
        serializations.append(1)
        return original_dumps(*args, **kwargs)
    monkeypatch.setattr(list_records, 'json', SimpleNamespace(dumps=dumps))
    calls = []

    def counted(rows):
        calls.append(len(rows))
        return original(rows)
    monkeypatch.setattr(ui, 'bw_collection_records', counted)
    response = client.get('/collection/' + kind)
    assert response.status_code == 200
    assert len(calls) == 1
    assert len(serializations) == 1
    assert len(soup_of(response).select('[data-bc-records]')) == 1


def test_collection_intrinsic_width_and_detail_flow_css():
    css = (ROOT / 'static/web/toni/bw-collection.css').read_text()

    def rule(selector):
        return re.findall(re.escape(selector) + r'\s*\{([^}]+)\}', css)[-1]
    assert 'min-width:0' in rule('#bw-collection')
    assert 'min-width:0' in rule('#bw-collection [data-bc-list]')
    assert 'max-width:100%' in rule('#bw-collection .bc-status-chips')
    assert 'overflow-x:hidden' not in css
    assert 'display:flex;flex-direction:column' in rule('#bw-collection .bc-detail-aside>.bc-module')
    assert 'flex:none' in rule('#bw-collection .bc-detail-aside>.bc-module>*')
    assert 'flex:none' in rule('#bw-collection .bc-price>*')
    assert 'display:block' in rule('#bw-collection .bc-fact small')


def test_set_inventory_panel_contains_controls_and_empty_state(world, client):
    soup = soup_of(client.get(f'/collection/item/{world.keep}'))
    section = soup.select_one('[data-module=consists]')
    inventory = section.select_one('[data-bc-tab-inventory]')
    assert inventory.select_one('[data-bc-rows]')
    assert not inventory.select_one('.bc-toolbar')
    assert not inventory.select_one('[data-bc-count]')
    assert not inventory.select_one('[data-bc-tab-extras]')
    assert section.select_one('[data-bc-tab-extras]').has_attr('hidden')


def add_47f_inventory_parts(coll, copy_id):
    """Reported identities added to a copy's inventory for layout checks: a long-named tyre in black and an old brick in white."""
    for number, name, colour, quantity in [('7b', 'Tire Smooth Small Dually', coll.colour('0'), 8),
                                           ('3001old', 'Brick 2 x 4 without Cross Support', coll.colour('15'), 1)]:
        part = coll.local('part', name, born_key=number)
        coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,quantity) VALUES(?,?,?,?)', (copy_id, part, colour, quantity))


def add_49a_long_figure(coll, copy_id):
    """4.9a: a figure with a long name and one missing component, for the Minifigures tab geometry."""
    figure = coll.local('minifigure', 'Cavalry Soldier with Breastplate and Plumed Helmet', born_key='long-fig')
    line = coll.sql("INSERT INTO copy_figure(copy_id,item_id,inventory_source,inventory_digest,quantity,missing,updated_at) VALUES(?,?,'none','none',1,0,?)",
                    (copy_id, figure, STAMP)).lastrowid
    torso = coll.local('part', 'Torso', born_key='long-fig-torso')
    coll.sql('INSERT INTO copy_part(copy_id,copy_figure_id,item_id,color_id,quantity,missing) VALUES(?,?,?,?,1,1)', (copy_id, line, torso, coll.colour('15')))


@pytest.fixture
def collection_chromium_geometry(world, coll, client, tmp_path):
    """Measure shipped shell/page CSS, including native disclosure layout."""
    executable = os.environ.get('BW_COLLECTION_CHROME')
    if not executable:
        pytest.skip('Set BW_COLLECTION_CHROME for opt-in browser geometry verification')
    pages = tmp_path / 'geometry'
    pages.mkdir()
    coll.sql('UPDATE copy SET note=?,condition=? WHERE id=?', ('Long private note ' * 30, 'used', world.copy_a))
    add_47f_inventory_parts(coll, world.copy_a)
    add_49a_long_figure(coll, world.copy_a)
    coll.sql('UPDATE copy_part SET missing=1 WHERE copy_id=? AND item_id=? AND copy_figure_id IS NULL AND retired_at IS NULL', (world.copy_a, world.brick))
    # the world's two copies of the set make the copy chips; a wide, stale price range for the set
    coll.price(world.keep, '25', condition='new', minimum='1', maximum='50', sold=2, observed='2022-01-01T00:00:00.000Z')
    for kind in ['S', 'M', 'P', 'I', 'detail']:
        route = f'/collection/item/{world.keep}?copy={world.copy_a}' if kind == 'detail' else '/collection/' + kind
        response = client.get(route)
        assert response.status_code == 200
        soup = soup_of(response)
        for link in soup.select('link[rel=stylesheet]'):
            style = soup.new_tag('style')
            style.string = (ROOT / urlsplit(link['href']).path.lstrip('/')).read_text()
            link.replace_with(style)
        for script in soup.select('script'):
            if script.get('type') == 'application/json':
                continue
            if 'formatting.js' in script.get('src', ''):
                script.attrs.clear()
                script.string = (ROOT / 'static/web/toni/formatting.js').read_text()
                soup.body.append(script.extract())
            elif 'bw-collection.js' in script.get('src', ''):
                script.attrs.clear()
                script.string = (ROOT / 'static/web/toni/bw-collection.js').read_text()
                # Defer until the fixture DOM exists.
                soup.body.append(script.extract())
            else:
                script.decompose()
        (pages / (kind + '.html')).write_text(str(soup))
    result = subprocess.run(['node', 'tests/toni_bw_collection_geometry.cjs', str(Path(executable)), str(pages)], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[0])


def test_collection_chromium_geometry(collection_chromium_geometry):
    assert collection_chromium_geometry['identityMeasurements']


def test_49a_chromium_geometry_measured(collection_chromium_geometry):
    """c1 uncropped set image, c14 one-line 24 px figure pill, c15 identity width, c11 present-before-missing (c12, the coverage captions, waits for M.8e)."""
    measured = collection_chromium_geometry['review49a']
    assert {m['width'] for m in measured} == {360, 390, 768, 1024, 1440}
    for m in measured:
        assert m['hero']['objectFit'] != 'cover' and m['hero']['objectFit'] == 'contain', m
        assert m['pill']['height'] == 24 and m['pill']['lines'] == 1, m
        assert m['figure']['linkWidth'] >= 150 and m['figure']['wordSplit'] is False, m
        assert all(m['missingCard'].values()), m
        assert m['progress']['presentBeforeMissing'], m
        # The coverage bar and its captions ("can be taken", "to order") are the Matcher's: no bar until M.8e, so `captionsBelowCoverage` is False here.
        assert not m['progress']['captionsBelowCoverage'], m


def test_47f_chromium_geometry_identity_minimum(collection_chromium_geometry):
    """Present identities keep 150 px; missing cards keep the kit column budget."""
    measurements = collection_chromium_geometry['identityMeasurements']
    assert [measurement['width'] for measurement in measurements] == [360, 390, 768, 820]
    for measurement in measurements:
        assert measurement['rows']
        assert {row['missing'] for row in measurement['rows']} == {False, True}
        for row in measurement['rows']:
            # Frame 1d: 16 px padding each side, 96 px picture, 16 px gap;
            # allow 1 px for fractional layout rounding.
            minimum = row['cardWidth'] - 2 * 16 - 96 - 16 - 1 if row['missing'] else 150
            assert row['width'] >= minimum, (measurement['width'], row, minimum)
