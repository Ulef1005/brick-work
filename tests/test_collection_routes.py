"""The collection's browser routes on the 4.0 store (M.8b, issue #110): the item page by id and the redirects to it, the colour chooser,
the lists, the jump search, the shell's counts, first run, and which screens still answer 503. Invented data, no network."""
import json

from bs4 import BeautifulSoup
import pytest

from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def soup(response):
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def records(page):
    data = json.loads(soup(page).select_one('[data-bc-records]').string)
    return [dict(zip(data['fields'], [r.get(str(i)) for i in range(len(data['fields']))])) for r in data['rows']]


def test_every_collection_list_renders_and_carries_the_item_url_base(world, client):
    for kind in 'SMPIOGBC':
        page = client.get(f'/collection/{kind}')
        assert page.status_code == 200, kind
        root = soup(page).select_one('#bw-collection')
        assert root['data-type'] == kind and root['data-item-base'] == '/collection/item/0' and root['data-wish-base'] == '/collection/wishes/0'
    assert client.get('/collection/s').status_code == 200                       # the letter is not case sensitive
    for bad in ('/collection/X', '/collection/?', '/collection/sets/1'):
        assert client.get(bad).status_code == 404, bad
    assert client.get('/collection/wishes').status_code == 200 and client.get('/collection/purchase-places').status_code == 200


def test_a_list_row_links_by_item_id_and_names_the_unidentified(world, client):
    sets = records(client.get('/collection/sets'))
    assert [(r['item_id'], r['number'], r['quantity']) for r in sets] == [(world.keep, '1000-1', 2), (world.duplo, '2070-1', 1)]
    gear = records(client.get('/collection/G'))
    assert [(r['item_id'], r['number'], r['name'], r['unresolved']) for r in gear] == [(world.mystery, None, 'Mystery thing', True)]
    parts = records(client.get('/collection/P'))
    local = next(r for r in parts if r['item_id'] == world.local_part)
    assert (local['number'], local['source'], local['also']) == ('x999', 'bricklink', None)


def test_the_item_page_by_id_shows_the_copy_asked_for(world, client):
    page = client.get(f'/collection/item/{world.keep}?copy={world.copy_b}')
    html = soup(page)
    assert page.status_code == 200 and html.select_one('h1').get_text(strip=True).replace('\xa0', ' ') == 'Syn Castle Keep'
    assert 'Sealed' in html.get_text() and html.select_one('a.bc-copy-chip[aria-current=page]').get_text(strip=True) == 'Set 2'
    chips = [a['href'] for a in html.select('a.bc-copy-chip')]
    assert chips == [f'/collection/item/{world.keep}?copy={world.copy_a}', f'/collection/item/{world.keep}?copy={world.copy_b}']
    assert page.headers['Cache-Control'] == 'no-store'
    assert client.get(f'/collection/item/{world.keep}?copy=nope').status_code == 404
    assert client.get('/collection/item/999999').status_code == 404
    assert client.get('/collection/item/0x1').status_code == 404


def test_a_part_with_one_colour_goes_straight_to_it_and_with_several_asks(world, coll, client):
    one = client.get(f'/collection/item/{world.brick}?copy=ignored')
    assert one.status_code == 302 and one.headers['Location'].endswith(f'/collection/item/{world.brick}?copy=ignored&colour={world.red}')
    coll.add_stock('part', world.brick, colour=world.white, quantity=1)
    chooser = client.get(f'/collection/item/{world.brick}')
    assert chooser.status_code == 200
    links = [a['href'] for a in soup(chooser).select('.bc-colour-chooser a')]
    assert sorted(links) == sorted(f'/collection/item/{world.brick}?colour={c}' for c in (world.red, world.white))
    assert client.get(f'/collection/item/{world.brick}?colour={world.white}').status_code == 200
    assert client.get(f'/collection/item/{world.brick}?colour=abc').status_code == 404


def test_an_item_that_is_not_a_part_or_is_held_in_no_colour_opens_at_once(world, coll, client):
    assert client.get(f'/collection/item/{world.local_booklet}').status_code == 200
    coll.sql('UPDATE wish SET archived_at=? WHERE id=?', ('2026-10-26T00:00:00.000Z', world.wish_part))
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-10-26T00:00:00.000Z', world.stock_plate))
    coll.sql('UPDATE copy SET archived_at=? WHERE item_id=?', ('2026-10-26T00:00:00.000Z', world.keep))
    page = client.get(f'/collection/item/{world.plate}')                 # held in no colour any more: no choice to make
    assert page.status_code == 200 and not soup(page).select('.bc-colour-chooser')


def test_the_no_colour_bookmark_of_3_3_means_colour_1(world, coll, client):
    coll.add_stock('part', world.brick, colour=1, quantity=2)
    page = client.get(f'/collection/item/{world.brick}?colour=none')
    assert page.status_code == 200 and '[No Color/Any Color]' in soup(page).get_text()
    assert [a['href'] for a in soup(client.get(f'/collection/item/{world.brick}')).select('.bc-colour-chooser a')] != []


def test_an_old_number_url_redirects_to_the_item_through_find(world, client):
    moved = client.get('/collection/item/S/1000-1')
    assert moved.status_code == 301 and moved.headers['Location'] == f'/collection/item/{world.keep}'
    assert client.get('/collection/item/set/1000-1').headers['Location'] == f'/collection/item/{world.keep}'
    with_copy = client.get(f'/collection/item/S/1000-1?copy={world.copy_a}')
    assert with_copy.headers['Location'] == f'/collection/item/{world.keep}?copy={world.copy_a}'
    assert client.get('/collection/item/M/syn-fig-0004').headers['Location'] == f'/collection/item/{world.figure}'      # the BrickLink number finds it too
    assert client.get('/collection/item/P/x999').headers['Location'] == f'/collection/item/{world.local_part}'
    for gone in ('/collection/item/S/nope', '/collection/item/X/1000-1', '/collection/item/P/1000-1'):
        assert client.get(gone).status_code == 404, gone
    assert client.get('/collection/item/S/1000-1', follow_redirects=True).status_code == 200
    # an `item_id` in the query is the destination's own route parameter: dropped, not a TypeError (Codex on M.8b)
    moved = client.get('/collection/item/S/1000-1?item_id=123&stock=x')
    assert moved.status_code == 301 and moved.headers['Location'] == f'/collection/item/{world.keep}?stock=x'


def test_an_old_part_url_translates_the_bricklink_colour_number(world, client):
    """In 3.3 a part's colour in the URL was the BrickLink colour number: 5 is red in BrickLink, which is Brick Work's colour 'Red'."""
    moved = client.get('/collection/item/P/3001?colour=5')
    assert moved.status_code == 301 and moved.headers['Location'] == f'/collection/item/{world.brick}?colour={world.red}'
    unknown = client.get('/collection/item/P/3001?colour=987654')
    assert unknown.status_code == 301 and unknown.headers['Location'] == f'/collection/item/{world.brick}'


def test_a_merged_item_answers_with_the_item_it_was_merged_into(world, coll, client):
    away = coll.local('part', 'Merged away', born_key='dup-3001')
    coll.sql('UPDATE item SET merged_into=? WHERE id=?', (world.brick, away))
    coll.sql('INSERT INTO item_redirect(old_id,new_id) VALUES(?,?)', (away, world.brick))
    moved = client.get(f'/collection/item/{away}?stock=x&colour=4')
    assert moved.status_code == 301 and moved.headers['Location'] == f'/collection/item/{world.brick}?stock=x&colour=4'


def test_the_wish_page_by_uuid(world, client):
    page = client.get(f'/collection/wishes/{world.wish_part}')
    assert page.status_code == 200 and 'Your max price' in page.get_data(as_text=True)
    assert client.get('/collection/wishes/nope').status_code == 404
    assert client.get(f'/collection/wishes/{world.wish_part}').headers['Cache-Control'] == 'no-store'


def test_the_lot_and_purchase_place_pages(world, client):
    assert 'Bag' in client.get(f'/collection/lots/{world.bag}').get_data(as_text=True)
    assert client.get('/collection/lots/nope').status_code == 404
    places = client.get('/collection/purchase-places').get_data(as_text=True)
    assert 'Shop' in places and '12.50' in places


def test_jump_results_name_both_numbers_and_link_by_id(world, client):
    sets = client.get('/collection/jump?q=1000-1').json['results']
    keep = next(r for r in sets if r['kind'] == 'set')
    assert keep['number'] == '1000-1' and [c['url'] for c in keep['copies']] == [f'/collection/item/{world.keep}?copy={world.copy_a}', f'/collection/item/{world.keep}?copy={world.copy_b}']
    assert keep['copies'][0]['condition'] == 'used' and keep['copies'][0]['completeness'] == 'incomplete' and keep['url'] is None
    part = client.get('/collection/jump?q=x999').json['results'][0]
    assert part['number'] == 'x999 (BrickLink)' and part['url'] == f'/collection/item/{world.local_part}?colour={world.red}'
    wanted = client.get('/collection/jump?q=gate').json['results'][0]
    assert wanted['kind'] == 'wanted' and wanted['url'] == f'/collection/wishes/{world.wish_set}'
    assert client.get('/collection/jump').json == {'query': '', 'results': [], 'limit': 20, 'truncated': False}
    figure = client.get('/collection/jump?q=syn-fig').json['results'][0]
    assert figure['number'].startswith('fig-000004 · BrickLink syn-fig-0004') and figure['kind'] == 'minifigure'


def test_the_shell_counts_what_is_owned_in_the_4_0_tables(world, app4):
    from brickwork.web import ui
    with app4.test_request_context('/'):
        assert ui.navigation_counts() == {'Sets': 2, 'Minifigures': 1, 'Parts': 12, 'Instructions': 1, 'Gear': 1, 'Wishlist': 2}


def test_the_unported_screens_still_say_so_and_the_ported_ones_do_not(world, client):
    for held in ('/workbench/orders', '/planning/wishlist', '/manage/tools'):
        assert client.get(held).status_code == 503, held
    for served in ('/', '/collection/sets', f'/collection/item/{world.keep}', '/collection/jump?q=a', '/workbench/matcher', '/workbench/storage'):
        assert client.get(served).status_code != 503, served


def test_a_collection_with_no_catalogue_file_gets_the_first_run_page_on_sets(pair, client):
    pair.with_name('catalogue.db').unlink()
    page = client.get('/collection/sets')
    assert page.status_code == 200 and 'data-first-run' in page.get_data(as_text=True)
    assert client.get('/collection/wishes').status_code == 200                       # says what is missing in its own words, in the shell
