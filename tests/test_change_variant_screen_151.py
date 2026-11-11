"""The Change variant screen (issue #151): the page that copies the merge page for two live catalogue items, its entry button in the Identity module,
the preview of what moves, the confirm with its one event and Undo. Invented data only, no network."""
import re

from bs4 import BeautifulSoup
import pytest

from brickwork.store4 import variant as store_variant
from tests.app4 import RICH, STAMP, app4, client, coll, csrf, make_pair, table_digest, world  # noqa: F401  (the fixtures)

NUMBER = 'syn-fig-0004'                                          # BrickLink's number of fig-000004 (matched, preferred)


@pytest.fixture
def pair(tmp_path):
    """The rich fixture catalogue plus a reissue of the figure, `fig-000005`."""
    extra = {'minifigs': [['fig-000005', 'Syn Reissue Figure', 1, '']], 'inventories': [*RICH['inventories'], [99001, 1, 'fig-000005']],
             'inventory_parts': [*RICH['inventory_parts'], [99001, '3023', 15, 1, 'False', '']]}
    return make_pair(tmp_path, rich=True, extra_dump=extra)


@pytest.fixture
def other(coll, world):
    """The reissue `fig-000005`, in the collection, with BrickLink's number as a link to check (the guess of a migration)."""
    new = coll.project(coll.item('minifigs', 'fig-000005'))
    coll.link(new, NUMBER, kind='M', status='to_check')
    return new


def page(client, url, status=200):
    response = client.get(url, follow_redirects=True)
    assert response.status_code == status, (url, response.status_code)
    return BeautifulSoup(response.data, 'html.parser')


def post(client, item, **data):
    return client.post(f'/collection/item/{item}/identity', data={'csrf_token': csrf(client), **data})


def url(item, **query):
    return f'/collection/item/{item}/change-variant' + ('?' + '&'.join(f'{k}={v}' for k, v in query.items()) if query else '')


def moves(soup):
    cells = [r.find_all('span', recursive=False) for r in soup.select('.bi-preview .bi-move')]
    return {c[0].get_text(' ', strip=True): c[1].get_text(' ', strip=True) for c in cells}


def test_the_button_is_beside_the_identity_module_of_a_live_figure_and_part_and_nowhere_else(coll, client, world):
    link = lambda item, **q: page(client, f'/collection/item/{item}', **q).select_one(f'[data-identity-module=links] a[href$="/change-variant"]')
    assert link(world.figure) and link(world.figure).get_text(strip=True) == 'Change variant…'
    assert link(world.brick) and link(world.figure)['href'] == url(world.figure)
    assert not page(client, f'/collection/item/{world.figure}').select_one('[data-identity-module=links] a[href$="/merge"]')   # Merge keeps its own conditions
    assert not page(client, f'/collection/item/{world.keep}').select('a[href$="/change-variant"]')                           # not a set
    assert not link(world.local_part)                                                                                        # an item of yours is merged, not changed
    assert page(client, f'/collection/item/{world.local_part}').select_one('a[href$="/merge"]')


def test_no_button_and_no_page_on_a_read_only_instance(coll, client, world, app4):
    app4.config['BW_READ_ONLY'] = True
    assert not page(client, f'/collection/item/{world.figure}').select('a[href$="/change-variant"]')
    response = client.get(url(world.figure))
    assert response.status_code == 403 and b'Changes are switched off on this instance' in response.data
    before = table_digest(coll.db)
    assert post(client, world.figure, action='change_variant', target='1').status_code == 403
    assert table_digest(coll.db) == before


def test_the_page_suggests_the_variant_with_the_same_number_of_the_same_kind(coll, client, world, other):
    soup = page(client, url(world.figure))
    assert soup.select_one('h1').get_text(strip=True) == 'Change variant'
    assert 'Syn Reissue Figure' in soup.select_one('.bi-card').get_text() or 'fig-000004' in soup.get_text()
    results = soup.select('.bi-result')
    assert [r['href'] for r in results] == [url(world.figure, target=other)]
    assert 'same BrickLink number' in results[0].get_text() and '1 suggested' in soup.select_one('[role=status]').get_text()
    assert not soup.select('.bi-preview')                                                    # nothing chosen yet, nothing to preview


def test_the_search_finds_by_number_or_name_and_only_the_same_kind(coll, client, world, other):
    names = lambda q: [a.select_one('strong').get_text() for a in page(client, url(world.figure, q=q)).select('.bi-result')]
    assert names('Reissue') == ['Syn Reissue Figure'] and names('fig-000005') == ['Syn Reissue Figure']
    assert 'Brick 2 x 4' not in names('Brick') and names('Brick') == []                     # a part is no variant of a figure
    assert 'No live minifigure has that number or name' in page(client, url(world.figure, q='zzzz')).get_text()
    assert names('fig-000004') == []                                                         # never the item itself


def test_a_catalogue_item_not_yet_in_the_collection_is_offered_too(coll, client, world):
    soup = page(client, url(world.figure, q='fig-000005'))                                   # still only in the catalogue: projected when the change needs it
    assert [a.select_one('strong').get_text() for a in soup.select('.bi-result')] == ['Syn Reissue Figure']


def test_choosing_one_shows_what_moves_without_changing_anything(coll, client, world, other):
    coll.add_wish(world.figure, quantity=2)
    before = table_digest(coll.db)
    soup = page(client, url(world.figure, target=other))
    assert table_digest(coll.db) == before and coll.db.execute('SELECT count(*) FROM main.event WHERE field=?', ('change_variant',)).fetchone()[0] == 0
    assert soup.select_one('.bi-result[aria-current=true] .bi-pill').get_text(strip=True) == 'Chosen'
    assert soup.select_one('#bi-preview-title').get_text() == 'Change this to'
    rows = moves(soup)
    assert rows['Loose figures'] == '1' and rows['Figure lines in copies'] == '2' and rows['Wishes'] == '1'
    assert rows[f'BrickLink number {NUMBER}'] == 'follows to fig-000005'
    text = soup.select_one('.bi-preview').get_text(' ', strip=True)
    assert 'stays in the catalogue' in text and 'Links to check' in text
    form = soup.select_one('.bi-preview form.bi-confirm')
    assert form['action'] == f'/collection/item/{world.figure}/identity' and form.select_one('input[name=action]')['value'] == 'change_variant'
    assert form.select_one('input[name=target]')['value'] == str(other) and form.select_one('button').get_text() == 'Change variant'


def test_a_loose_stock_rows_photos_are_counted_with_it(coll, client, world, other):
    coll.sql("INSERT INTO photo(id, item_id, stock_id, local_path, created_at) VALUES('ph-1', ?, ?, 'data/images/own/ph-1.jpg', ?)", (world.figure, world.stock_figure, STAMP))
    assert '1 photo goes with the loose rows' in page(client, url(world.figure, target=other)).select_one('.bi-preview').get_text(' ', strip=True)


def test_a_part_shows_its_own_lines_and_the_number_that_follows(coll, client, world):
    soup = page(client, url(world.plate, target=world.brick))
    rows = moves(soup)
    assert rows['Loose parts'] == '1' and rows['Part lines in copies'] == '4' and rows['Part lines in figures'] == '0' and rows['Wishes'] == '1'
    assert 'Figure lines in copies' not in rows and soup.select_one('.bi-preview input[name=action][value=change_variant]')


@pytest.mark.parametrize('case', ['kind', 'job', 'wish', 'set'])
def test_a_refusal_is_the_pages_red_message_and_offers_no_confirm(coll, client, world, other, case):
    item, target = world.figure, other
    if case == 'kind':
        target, words = world.brick, 'not the same kind'
    elif case == 'job':
        coll.sql("INSERT INTO job(source,kind,item_id,state,via,created_at,updated_at) VALUES('bricklink','item',?,'queued','app',?,?)", (other, STAMP, STAMP))
        words = 'still running'
    elif case == 'wish':
        coll.add_wish(world.figure, quantity=1)
        coll.add_wish(other, quantity=1)
        words = 'would meet a wish'
    else:
        item, target, words = world.keep, world.gate, 'Only a figure or a part'
    soup = page(client, url(item, target=target))
    red = soup.select_one('.bi-refusal')
    assert red and words in red.get_text() and not soup.select_one('input[name=action][value=change_variant]')


def test_two_variants_of_loose_stock_that_would_meet_are_refused_by_name(coll, client, world):
    coll.add_stock('part', world.brick, colour=world.white, quantity=3, condition='new')
    soup = page(client, url(world.plate, target=world.brick))
    assert 'would meet a loose stock row you already have' in soup.select_one('.bi-refusal').get_text() and not soup.select_one('input[name=action][value=change_variant]')


def test_the_confirm_moves_the_rows_writes_one_event_and_undo_puts_everything_back(coll, client, world, other):
    wish = coll.add_wish(world.figure, quantity=2)
    before = table_digest(coll.db)
    events = coll.db.execute('SELECT count(*) FROM main.event').fetchone()[0]
    response = post(client, world.figure, action='change_variant', target=str(other))
    assert response.status_code == 302 and response.headers['Location'].startswith(f'/collection/item/{other}?done=')
    assert coll.db.execute('SELECT count(*) FROM main.event').fetchone()[0] == events + 1
    event = coll.db.execute("SELECT * FROM main.event WHERE field='change_variant'").fetchone()
    assert (event['entity_kind'], event['entity_id'], event['old_value'], event['via']) == ('item', str(other), str(world.figure), 'app')
    assert coll.db.execute('SELECT item_id FROM main.stock WHERE id=?', (world.stock_figure,)).fetchone()[0] == other
    assert coll.db.execute('SELECT item_id FROM main.wish WHERE id=?', (wish,)).fetchone()[0] == other
    assert coll.db.execute('SELECT count(*) FROM main.copy_figure WHERE item_id=?', (world.figure,)).fetchone()[0] == 0
    soup = page(client, response.headers['Location'])
    notice = soup.select_one('.bi-notice')
    assert notice.get_text(' ', strip=True).startswith('Changed variant from') and 'to this item · ' in notice.get_text() and 'Saved' not in notice.get_text()
    assert notice.select_one('input[value=undo]')
    event_id = int(re.search(r'done=(\d+)', response.headers['Location']).group(1))
    assert post(client, other, action='undo', event=str(event_id)).status_code == 302
    assert table_digest(coll.db) == before


def test_a_confirm_the_rules_refuse_says_so_on_the_page_and_changes_nothing(coll, client, world, other):
    coll.sql("INSERT INTO job(source,kind,item_id,state,via,created_at,updated_at) VALUES('bricklink','item',?,'queued','app',?,?)", (other, STAMP, STAMP))
    before = table_digest(coll.db)
    response = post(client, world.figure, action='change_variant', target=str(other))
    assert response.status_code == 302 and response.headers['Location'].startswith(url(world.figure, target=other))
    soup = page(client, response.headers['Location'])
    assert 'Not saved' in soup.get_text() and soup.select_one('.bi-refusal')
    assert table_digest(coll.db) == before


def test_the_page_of_an_item_that_cannot_change_variant_says_why(coll, client, world):
    soup = page(client, url(world.local_part))
    assert 'cannot change variant' in soup.select_one('.bi-refusal').get_text() and not soup.select('.bi-search')
    assert page(client, url(world.keep)).select_one('.bi-refusal')


def test_the_page_of_an_item_that_is_not_there_is_404(client, world):
    assert client.get(url(999999999)).status_code == 404


def test_the_page_survives_a_catalogue_that_is_not_activated(coll, client, world, other, monkeypatch):
    from brickwork.store4.errors import CatalogueError

    def refuse(*args, **kwargs):
        raise CatalogueError('no catalogue')
    monkeypatch.setattr(store_variant, 'preview_change_variant', refuse)
    soup = page(client, url(world.figure, target=other))
    assert "catalogue isn't activated yet" in soup.select_one('.bi-refusal').get_text()


def test_a_preview_whose_catalogue_table_is_missing_is_the_catalogue_refusal_not_a_server_error(coll, client, world, other, monkeypatch):
    import sqlite3

    def gone(*args, **kwargs):
        raise sqlite3.OperationalError('no such table: catalogue.inventory')
    monkeypatch.setattr(store_variant, 'preview_change_variant', gone)
    soup = page(client, url(world.figure, target=other))
    assert "catalogue isn't activated yet" in soup.select_one('.bi-refusal').get_text()


def test_a_retired_catalogue_item_is_not_offered_as_a_variant(coll, client, world, tmp_path):
    import sqlite3
    from contextlib import closing
    assert [a.select_one('strong').get_text() for a in page(client, url(world.figure, q='fig-000005')).select('.bi-result')] == ['Syn Reissue Figure']
    with closing(sqlite3.connect(tmp_path / 'catalogue.db')) as other:                       # the catalogue retires it (the file is attached read-only here)
        other.execute("UPDATE item SET retired_at='2026-11-01T00:00:00.000Z' WHERE born_key='fig-000005'")
        other.commit()
    assert page(client, url(world.figure, q='fig-000005')).select('.bi-result') == []
