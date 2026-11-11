"""The Build Scout screen (#9): the list with its filters and the selected set's panel, the set's own page, the rail entry, and the writes behind the buttons
(Build it, Add to wishlist, Undo, the missing-parts XML). Flask test client on the rich fixture catalogue; no browser."""
from bs4 import BeautifulSoup
import pytest

from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)

PATH = '/workbench/build-scout'


def soup(client, path=PATH):
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def names(page):
    return [r.select_one('.bs-name').get_text(' ', strip=True).replace('\xa0', ' ') for r in page.select('a.bs-row')]


def test_the_list_ranks_the_sets_and_selects_the_first(client, world):
    page = soup(client)
    assert page.select_one('h1').get_text() == 'Build Scout'
    assert names(page) == ['1000-1 Syn Castle Keep', '1000-2 Syn Castle Gate']
    first = page.select_one('a.bs-row')
    assert first['aria-current'] == 'true' and 'is-selected' in first['class'] and first['href'] == f'/workbench/build-scout/{world.keep}'
    assert first['data-select'] == f'{PATH}?set={world.keep}'
    assert '100%' in first.select_one('.bs-share-text').get_text() and '6 of 6 parts' in first.get_text()
    assert '1 of 2 figures missing' in first.select_one('.bs-missing').get_text()
    cap = page.select_one('.cap2').get_text()
    assert cap.startswith('2 of 3 sets · 12 loose pieces counted') and 'swaps listed in the set, never in the %' in cap
    panel = page.select_one('[data-bs-panel]')
    assert panel['data-set'] == str(world.keep) and 'bs-aside' in panel['class']
    assert 'Figures: 1 of 2 in stock' in panel.get_text() and panel.select_one('[data-bs-build]') and panel.select_one('[data-bs-wish]')
    assert panel.select_one('a[href*="missing.xml"]')['href'].startswith(f'{PATH}/{world.keep}/missing.xml')


def test_the_set_asked_for_is_the_one_selected(client, world):
    page = soup(client, f'{PATH}?set={world.gate}')
    assert page.select_one('[data-bs-panel]')['data-set'] == str(world.gate)
    assert [a.has_attr('aria-current') for a in page.select('a.bs-row')] == [False, True]


def test_the_filters_and_sources_come_back_in_the_form_and_the_links(client, world):
    page = soup(client, f'{PATH}?min_percent=0&theme=Castle&year_from=1991&lot={world.bag}&damaged=1')
    assert names(page) == ['1000-2 Syn Castle Gate']
    form = page.select_one('form.bs-filters')
    assert form['method'] == 'get'
    assert form.select_one('input[name=min_percent]')['value'] == '0' and form.select_one('input[name=theme]')['value'] == 'Castle'
    assert form.select_one('input[name=year_from]')['value'] == '1991'
    assert form.select_one(f'input[name=lot][value="{world.bag}"]').has_attr('checked') and form.select_one('input[name=damaged]').has_attr('checked')
    assert not form.select_one('input[name=loose]').has_attr('checked')
    assert form.select_one('summary').get_text(' ', strip=True) == 'Parts from 1 lot'
    link = page.select_one('a.bs-row')['href']
    assert link.startswith(f'/workbench/build-scout/{world.gate}?') and f'lot={world.bag}' in link and 'theme=Castle' in link
    assert page.select_one('[data-bs-panel] a[href*="missing.xml"]') is None or f'lot={world.bag}' in page.select_one('[data-bs-panel] a[href*="missing.xml"]')['href']


def test_a_refused_filter_is_named_and_the_defaults_are_used(client, world):
    page = soup(client, f'{PATH}?min_percent=lots&max_missing=-2')
    assert 'min_percent is a whole number' in page.select_one('.notice').get_text()
    assert page.select_one('input[name=min_percent]')['value'] == '60' and len(names(page)) == 2
    assert 'No such theme' in soup(client, f'{PATH}?theme=Nothing').select_one('.notice').get_text()


def test_nothing_reaching_the_minimum_and_no_stock_say_so(client, coll, world):
    assert 'No set reaches 101%' not in soup(client, f'{PATH}?min_percent=100').get_text()
    page = soup(client, f'{PATH}?min_percent=100&max_missing=0&year_from=2100')
    assert 'No set reaches 100% of its parts' in page.select_one('.bs-empty').get_text() and page.select_one('[data-bs-panel]') is None
    coll.sql('UPDATE stock SET archived_at=? WHERE kind IN (?, ?)', ('2026-11-01T00:00:00Z', 'part', 'minifigure'))
    assert 'No loose parts to count yet' in soup(client).select_one('.bs-empty').get_text()


def test_the_set_page_shows_the_panel_alone_with_a_way_back(client, world):
    page = soup(client, f'{PATH}/{world.keep}?min_percent=0')
    assert page.select_one('.crumb a').get_text() == '‹ Build Scout' and page.select_one('.crumb a')['href'].startswith(PATH) and not page.select('a.bs-row')
    panel = page.select_one('[data-bs-panel]')
    assert 'bs-aside' not in panel['class'] and panel.select_one('h1').get_text(' ', strip=True) == '1000-1 Syn Castle Keep'
    assert page.select_one('#bw-build-scout')['data-build-url'] == f'{PATH}/{world.keep}/build'
    assert client.get(f'{PATH}/{world.brick}').status_code == 404                           # a part has no part list to compare
    assert client.get(f'{PATH}/987654').status_code == 404


def test_the_rail_has_build_scout_beside_matchmaker(client, world):
    page = soup(client)
    rail = [a.get('title') for a in page.select('aside.rail nav a')]
    assert rail.index('Build Scout') == rail.index('Matchmaker') + 1
    assert page.select_one('aside.rail a[aria-current="page"], aside.rail a.active') is not None


def test_the_jump_search_finds_build_scout(client, world):
    found = client.get('/collection/jump?q=scout')
    assert found.status_code == 200 and 'Build Scout' in found.get_data(as_text=True)


def test_a_read_only_instance_has_no_build_it_and_no_wishlist_button(client, world, monkeypatch):
    monkeypatch.setattr('brickwork.api.read_only', lambda: True)
    panel = soup(client).select_one('[data-bs-panel]')
    assert panel.select_one('[data-bs-build]') is None and panel.select_one('[data-bs-wish]') is None
    assert panel.select_one('a[href*="missing.xml"]') is not None                           # the export is a read


def test_build_it_is_off_when_the_chosen_stock_holds_nothing_the_set_needs(client, coll, world):
    empty = coll.lot('Empty bag')
    panel = soup(client, f'{PATH}/{world.keep}?min_percent=0&lot={empty}').select_one('[data-bs-panel]')
    assert panel.select_one('[data-bs-build]').has_attr('disabled') and 'holds nothing this set needs' in panel.get_text()
    assert panel.select_one('[data-bs-wish]') is not None


# ---------- the writes behind the buttons ----------

def send(client, path, token, **data):
    return client.post(path, json=dict(csrf_token=token, **data))


def test_build_it_moves_the_parts_and_undo_puts_them_back(client, coll, world):
    token = csrf(client)
    done = send(client, f'{PATH}/{world.keep}/build', token, lots=[], storages=[], loose=False, damaged=False)
    assert done.status_code == 200, done.get_data(as_text=True)
    body = done.get_json()
    assert body['message'].startswith('Made a copy · 6 pieces and 1 figure moved out of loose stock') and body['event_id']
    assert body['url'].startswith(f'/collection/item/set/') or f'/{world.keep}' in body['url']
    assert coll.db.execute('SELECT quantity FROM stock WHERE id=?', (world.stock_figure,)).fetchone()[0] == 0
    assert 'Syn Castle Keep' not in ' '.join(names(soup(client)))                         # the parts are in the copy now
    undone = send(client, f'{PATH}/undo', token, event_id=body['event_id'])
    assert undone.status_code == 200 and undone.get_json()['message'] == 'Undone'
    assert coll.db.execute('SELECT quantity FROM stock WHERE id=?', (world.stock_figure,)).fetchone()[0] == 1
    assert 'Syn Castle Keep' in ' '.join(names(soup(client)))
    again = send(client, f'{PATH}/undo', token, event_id=body['event_id'])
    assert again.status_code == 200                                                         # a second Undo does nothing


def test_build_it_uses_the_sources_the_page_sent(client, coll, world):
    token = csrf(client)
    body = send(client, f'{PATH}/{world.keep}/build', token, lots=[world.bag], storages=[], loose=False).get_json()
    assert body['message'].startswith('Made a copy · 3 pieces moved out of loose stock · 3 still missing')


def test_the_writes_refuse_what_they_must(client, coll, world, monkeypatch):
    token = csrf(client)
    assert client.post(f'{PATH}/{world.keep}/build', json={'csrf_token': 'wrong'}).status_code == 400
    assert send(client, f'{PATH}/{world.keep}/nothing', token).status_code == 404
    refused = send(client, f'{PATH}/{world.brick}/build', token)
    assert refused.status_code == 400 and refused.get_json()['message']
    assert send(client, f'{PATH}/{world.keep}/build', token, lots=[1]).status_code == 400
    assert coll.db.execute("SELECT count(*) FROM event WHERE field='make_from_stock'").fetchone()[0] == 0
    monkeypatch.setattr('brickwork.api.read_only', lambda: True)
    assert send(client, f'{PATH}/{world.keep}/build', token).status_code == 403
    assert send(client, f'{PATH}/{world.keep}/wishlist', token).status_code == 403


def test_add_to_wishlist_marks_the_wish_and_a_second_press_adds_nothing(client, coll, world):
    token = csrf(client)
    first = send(client, f'{PATH}/{world.keep}/wishlist', token).get_json()
    assert first['message'] == 'Added to the wishlist' and first['event_id'] and first['already'] is False
    wish = coll.db.execute('SELECT * FROM wish WHERE item_id=? AND archived_at IS NULL', (world.keep,)).fetchone()
    assert (wish['kind'], wish['note'], wish['wishlist_id']) == ('set', 'Buildable from stock', 'default')
    second = send(client, f'{PATH}/{world.keep}/wishlist', token).get_json()
    assert second['message'] == 'Already on the wishlist' and second['already'] is True
    assert send(client, f'{PATH}/undo', token, event_id=first['event_id']).status_code == 200
    assert coll.db.execute('SELECT count(*) FROM wish WHERE item_id=? AND archived_at IS NULL', (world.keep,)).fetchone()[0] == 0


def test_the_missing_parts_xml_is_the_copies_exporter_output(client, coll, world):
    assert client.get(f'{PATH}/{world.gate}/missing.xml').status_code == 404                # nothing is missing of it
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-11-01T00:00:00Z', world.stock_plate))
    response = client.get(f'{PATH}/{world.keep}/missing.xml')
    assert response.status_code == 200 and response.mimetype == 'application/xml'
    assert 'attachment' in response.headers['Content-Disposition'] and b'<INVENTORY>' in response.data
    assert b'3023' in response.data and b'<MINQTY>2</MINQTY>' in response.data
