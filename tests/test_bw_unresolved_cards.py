"""Unresolved items with the pictures in front (issue #459): guesses as picture cards, This one and None of these as one decision with one Undo,
the cache of guess pictures (no network: the client is injected), colour chips on part rows and the read-only page. Invented data only."""
import json
import os

from bs4 import BeautifulSoup
import pytest

from brickwork.core import guess_pictures, identity_admin, undo
from brickwork.core.media import root_for
from brickwork.core.sources import images
from tests.app4 import app4, client, coll, csrf, pair, table_digest, world  # noqa: F401  (the fixtures)
from tests.sources4 import png


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(images, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(guess_pictures, 'MIN_GAP', 0)


def post(client, **data):
    return client.post('/manage/unresolved', data={'csrf_token': csrf(client), **data})


def guesses(coll, world, keys=('nex025', 'nex064')):
    for key in keys:
        coll.link(world.figure, key, kind='M', status='to_check')
    return [r[0] for r in coll.db.execute("SELECT id FROM main.item_link WHERE status='to_check' AND item_id=? ORDER BY id", (world.figure,))]


def alive(db, item):
    return [tuple(r) for r in db.execute("SELECT provider_key, status FROM main.item_link WHERE item_id=? AND status IN ('to_check','manual') ORDER BY provider_key", (item,))]


def page(client):
    return BeautifulSoup(client.get('/manage/unresolved').data, 'html.parser')


def test_this_one_confirms_that_guess_and_rejects_the_others_in_one_undoable_step(coll, client, world):
    first, second = guesses(coll, world)
    before = table_digest(coll.db)
    response = post(client, action='choose', link=str(second))
    assert response.status_code == 302 and 'done=' in response.headers['Location']
    assert alive(coll.db, world.figure) == [('nex064', 'manual')]
    events = coll.db.execute("SELECT id, entity_kind, field FROM main.event WHERE field IN ('choose','confirm','reject') ORDER BY id").fetchall()
    assert [(e['entity_kind'], e['field']) for e in events] == [('item_link', 'choose')]
    receipt = json.loads(coll.db.execute('SELECT new_value FROM main.event WHERE id=?', (events[0]['id'],)).fetchone()[0])
    assert receipt['rejected'] == [first] and receipt['item'] == world.figure
    event = int(response.headers['Location'].split('done=')[1])
    assert 'Undo' in page_with_done(client, event)
    assert post(client, action='undo', event=str(event)).status_code == 302
    assert table_digest(coll.db) == before
    assert alive(coll.db, world.figure) == [('nex025', 'to_check'), ('nex064', 'to_check')]


def page_with_done(client, event):
    return client.get(f'/manage/unresolved?done={event}').get_data(as_text=True)


def test_this_one_leaves_a_guess_of_another_colour_alone(coll, world):
    coll.link(world.brick, '3001', kind='P', colour=world.red, status='to_check')
    coll.link(world.brick, '3001', kind='P', colour=world.white, status='to_check')
    ids = [r[0] for r in coll.db.execute("SELECT id FROM main.item_link WHERE item_id=? AND status='to_check' ORDER BY id", (world.brick,))]
    result = identity_admin.choose_link(coll.db, ids[0])
    assert result['rejected'] == 0
    assert [r[0] for r in coll.db.execute("SELECT status FROM main.item_link WHERE item_id=? AND status IN ('manual','to_check') ORDER BY id", (world.brick,))] == ['manual', 'to_check']


def test_none_of_these_rejects_every_guess_in_one_step_with_one_undo(coll, client, world):
    guesses(coll, world, ('nex025', 'nex064', 'nex099'))
    before = table_digest(coll.db)
    response = post(client, action='reject_all', item=str(world.figure))
    assert response.status_code == 302
    assert alive(coll.db, world.figure) == []
    assert coll.db.execute("SELECT count(*) FROM main.event WHERE field='reject_all'").fetchone()[0] == 1
    event = int(response.headers['Location'].split('done=')[1])
    assert undo.undo_event(coll.db, event)['already_undone'] is False
    assert table_digest(coll.db) == before


def test_the_single_confirm_and_reject_actions_still_work(coll, client, world):
    first, second = guesses(coll, world)
    assert post(client, action='confirm', link=str(first)).status_code == 302
    assert post(client, action='reject', link=str(second)).status_code == 302
    assert alive(coll.db, world.figure) == [('nex025', 'manual')]


def test_none_of_these_with_nothing_to_reject_saves_nothing(coll, client, world):
    before = table_digest(coll.db)
    assert post(client, action='reject_all', item=str(world.figure)).status_code == 302
    assert table_digest(coll.db) == before


def test_a_rebrickable_guess_on_a_local_item_cannot_be_chosen(coll, world):
    local = coll.local('part', 'Brick, local', born_key='x1')
    coll.link(local, 'abc', kind='parts', provider='rebrickable', status='to_check')
    coll.add_stock('part', local, colour=world.red, quantity=1, condition='used')
    link = coll.db.execute("SELECT id FROM main.item_link WHERE item_id=?", (local,)).fetchone()[0]
    with pytest.raises(Exception):
        identity_admin.choose_link(coll.db, link)


def test_the_guess_card_shows_the_number_the_name_the_reason_and_the_buttons(coll, client, world):
    guesses(coll, world)
    soup = page(client)
    assert soup.select_one('main h1').get_text() == '2 items to decide'
    row = soup.select_one(f'#item-{world.figure}')
    assert 'Which BrickLink figure is it?' in row.get_text()
    cards = row.select('.bu-grid form.bu-guess')
    assert [c.select_one('.mono').get_text() for c in cards] == ['nex025', 'nex064']
    for card in cards:
        assert card.select_one('button[value=choose]').get_text() == 'This one'
        assert card.select_one('.bi-tag').get_text().startswith('Found by')
        assert card.select_one('.bu-tile .bi-noimg').get_text() == 'No image'
        assert card.select_one('.bu-tile')['data-letter'] == 'M'                    # not cached yet: the page asks for it, it does not fetch it
    assert [b.get_text() for b in row.select('.bu-neither > form button, .bu-neither summary')] == ['None of these', 'Type a number']
    assert row.select_one('.bu-pills').get_text().strip() == '2 guesses'


def test_a_cached_picture_is_the_tile_and_a_failed_one_stays_a_no_image_tile(coll, client, world, pair):
    guesses(coll, world)
    root = root_for(pair)
    assert guess_pictures.fetch(root, 'M', 'nex025', 0, http=lambda request: png())[0] == 'ready'
    assert guess_pictures.fetch(root, 'M', 'nex064', 0, http=lambda request: (_ for _ in ()).throw(OSError('down')))[0] == 'none'
    cards = page(client).select(f'#item-{world.figure} .bu-grid form.bu-guess')
    assert cards[0].select_one('.bu-tile img')['src'] == '/manage/guess-pictures/M/nex025/0'
    assert cards[1].select_one('.bu-tile .bi-noimg') is not None and not cards[1].select_one('.bu-tile').has_attr('data-bu-pic')
    served = client.get('/manage/guess-pictures/M/nex025/0')
    assert served.status_code == 200 and served.mimetype == 'image/png'
    assert client.get('/manage/guess-pictures/M/nex064/0').status_code == 404            # a "no picture" marker is no file
    assert client.get('/manage/guess-pictures/M/other/0').status_code == 404             # never fetched here
    assert client.get('/manage/guess-pictures/M/..%2Fx/0').status_code == 404


def test_the_cache_asks_the_allowed_host_once_and_remembers_a_failure(pair):
    root, asked = root_for(pair), []

    def http(request):
        asked.append(request.full_url)
        return png()
    assert guess_pictures.fetch(root, 'P', '3001', 5, http=http)[0] == 'ready'
    assert guess_pictures.fetch(root, 'P', '3001', 5, http=http)[0] == 'ready'
    assert asked == ['https://img.bricklink.com/ItemImage/PN/5/3001.png']
    broken = []
    assert guess_pictures.fetch(root, 'P', '3023', 0, http=lambda r: broken.append(1) or b'not an image')[0] == 'none'
    assert guess_pictures.fetch(root, 'P', '3023', 0, http=lambda r: broken.append(1) or png())[0] == 'none'
    assert broken == [1]
    later = os.path.getmtime(guess_pictures._stem(root, 'P', '3023', 0).with_name('3023~0.none')) + guess_pictures.RETRY_AFTER + 1
    assert guess_pictures.fetch(root, 'P', '3023', 0, http=lambda r: png(), now=later)[0] == 'ready'
    with pytest.raises(ValueError):
        guess_pictures.fetch(root, 'P', '../x', 0, http=http)


def test_the_fetch_endpoint_needs_the_token_and_fills_the_cache_without_the_network(coll, client, world, monkeypatch):
    calls = []
    monkeypatch.setattr(images, 'transport', lambda request: calls.append(request.full_url) or png())
    guesses(coll, world)
    token = csrf(client)
    assert client.post('/manage/guess-pictures', json=dict(letter='M', number='sw0001', colour=0, csrf_token=token)).status_code == 400   # not an open guess
    assert client.post('/manage/guess-pictures', json=dict(letter='M', number='nex025', colour=0)).status_code == 400
    assert client.post('/manage/guess-pictures', json=dict(letter='M', number='nex025', colour=0, csrf_token='wrong')).status_code == 400
    assert client.post('/manage/guess-pictures', json=dict(letter='M', number='../x', colour=0, csrf_token=token)).status_code == 400
    assert client.post('/manage/guess-pictures', json=dict(letter='M', number='nex025', colour='0', csrf_token=token)).status_code == 400
    assert calls == []
    answer = client.post('/manage/guess-pictures', json=dict(letter='M', number='nex025', colour=0, csrf_token=token))
    assert answer.get_json() == dict(state='ready', url='/manage/guess-pictures/M/nex025/0')
    assert calls == ['https://img.bricklink.com/ItemImage/MN/0/nex025.png']
    assert client.get('/manage/guess-pictures/M/nex025/0').status_code == 200


def test_a_part_row_names_the_colours_the_collection_holds_it_in_and_a_scoped_guess_names_its_colour(coll, client, world):
    local = coll.local('part', 'Brick, tied', born_key='3001')
    coll.link(local, '3001', kind='P', status='matched')
    coll.link(local, '3001', kind='parts', provider='rebrickable', status='to_check')
    coll.add_stock('part', local, colour=world.red, quantity=2, condition='used')
    coll.add_stock('part', local, colour=world.white, quantity=1, condition='new')
    coll.link(world.plate, '3023a', kind='P', colour=world.white, status='to_check')
    soup = page(client)
    chips = soup.select(f'#item-{local} .bu-colours .bc-colour')
    assert [c.get_text() for c in chips] == ['Red', 'White']
    assert all('background:#' in c['style'] for c in chips)
    card = soup.select_one(f'#item-{world.plate} .bu-grid .bu-guess')
    assert card.select_one('.bc-colour').get_text() == 'White' and 'background:#' in card.select_one('.bc-colour')['style']
    assert card.select_one('.bu-tile').has_attr('data-colour')


def test_the_colours_come_from_one_query_for_all_rows(coll, world):
    for n in range(4):
        local = coll.local('part', f'Brick {n}')
        coll.add_stock('part', local, colour=world.red, quantity=1, condition='used')
    seen = []
    coll.db.set_trace_callback(lambda sql: seen.append(sql))
    identity_admin.unresolved(coll.db)
    coll.db.set_trace_callback(None)
    assert sum('FROM main.copy_part WHERE retired_at IS NULL AND color_id IS NOT NULL' in s for s in seen) == 1


def test_a_read_only_page_has_the_pictures_and_no_buttons(coll, client, world, monkeypatch):
    guesses(coll, world)
    local = coll.local('part', 'Brick, tied', born_key='3001')
    coll.link(local, '3001', kind='P', status='matched')
    coll.link(local, '3001', kind='parts', provider='rebrickable', status='to_check')
    monkeypatch.setattr('brickwork.api.read_only', lambda: True)
    soup = page(client)
    assert soup.select(f'#item-{world.figure} .bu-guess .bu-tile')
    assert soup.select('main article button') == []
    assert 'Type a number' not in soup.get_text() and 'None of these' not in soup.get_text()
