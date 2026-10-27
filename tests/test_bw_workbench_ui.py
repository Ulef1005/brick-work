"""The Workbench screens on the 4.0 store (M.8e, issue #110): Part Picker, Matcher, the save routes and their Undo, the recent saves.

Adapted from the page tests of the 3.3 test_bw_workbench.py (routes, selection and rank, copy grouping, booklets form, CSRF, found
destinations, picker markup). The "Needs a check" list of the Matcher is gone: a link still to check no longer blocks a match.
"""
import json
from pathlib import Path
import subprocess
import shutil

from bs4 import BeautifulSoup
import pytest

from brickwork.core import workbench as w
from tests.app4 import app4, client, coll, csrf, pair, post, read, world  # noqa: F401 (fixtures)


def soup(client, url):
    response = client.get(url)
    assert response.status_code == 200, (url, response.text[-500:])
    return BeautifulSoup(response.text, 'html.parser')


def save(client, token, action, **data):
    return client.post('/workbench/save/' + action, json=dict(csrf_token=token, **data))


def derived_copy(coll, checked=True):
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')
    for name in ('Instructions present', 'Box present') + (('Set is checked',) if checked else ()):
        coll.tag('copy', copy, coll.flag(name, 'status'))
    return copy


def test_routes_shell_selection_rank_and_matcher(world, client):
    for route in ['/workbench/part-picker', f'/workbench/part-picker?copy={world.copy_a}', '/workbench/matcher', '/workbench/match']:
        response = client.get(route)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'data-web-ui="toni"' in html and ('Recent saves' in html) == (not route.startswith('/workbench/part-picker?copy=')), route
        assert 'href="/workbench/part-picker"' in html and 'href="/workbench/match"' in html and 'href="/workbench/part-to-inventory"' in html
        assert 'aria-current="page"' in html and '<svg class="icon"' in html
        assert response.headers['Cache-Control'] == 'no-store'
    assert 'Start picking' in client.get(f'/workbench/part-picker?copy={world.copy_a}').text
    assert 'Add instruction booklets' in client.get('/workbench/match').text


def test_matcher_groups_copies_with_their_coverage_and_kinds(world, coll, client):
    for route in ['/workbench/matcher', '/workbench/match']:
        page = soup(client, route)
        assert not page.select_one('.breadcrumb')
        assert '2 copies can be advanced, 0 can become complete' in page.h1.text, 'a copy whose completeness the person set stays as it is'
        disclosure = page.find('summary', string='How matching works').parent
        assert not disclosure.has_attr('open') and 'not reservations' in disclosure.text
        group = page.select_one(f'[data-copy-id="{world.copy_a}"]')
        assert 'Set 1' in group.text
        assert group.select_one('[role="img"]')['aria-label'] == 'Covers 2 of 3 missing'
        assert {'Parts', 'Instruction'} == {n.text for n in group.select('.bw-kind')}
        assert group.select_one('[data-action="transfer"]') and 'Give' in group.text and 'Take' in group.text
        link = group.select_one('.bw-identity a')['href']
        assert link == f'/collection/item/{world.keep}?copy={world.copy_a}'
        assert not group.select_one('.bw-badge') and 'Completes checked copy' in group.select_one('.bw-match-action').text, 'the line says it, the copy does not'
    coll.sql("UPDATE copy SET completeness_source='derived' WHERE id=?", (world.copy_a,))
    page = soup(client, '/workbench/matcher')
    assert '2 copies can be advanced, 1 can become complete' in page.h1.text, 'the booklet and the box are not required parts'
    assert page.select_one(f'[data-copy-id="{world.copy_a}"] .bw-badge').text == 'Completes checked copy'


def test_a_loose_figure_group_links_its_stock_row_and_is_not_a_copy_to_advance(world, coll, client):
    coll.sql('UPDATE stock_part SET missing=1 WHERE id=1')
    part = coll.db.execute('SELECT item_id,color_id FROM stock_part WHERE id=1').fetchone()
    coll.add_stock('part', part['item_id'], colour=part['color_id'], quantity=1)
    page = soup(client, '/workbench/matcher')
    group = page.select_one(f'[data-copy-id="{world.stock_figure}"]')
    assert group and 'Loose minifigure' in group.text
    assert group.select_one('.bw-identity a')['href'] == f'/collection/item/{coll.item("minifigs", "fig-000004")}?stock={world.stock_figure}'
    assert '2 copies can be advanced' in page.h1.text, 'the loose figure is not counted'


def test_picker_selection_primary_and_single_part_layout(world, coll, client):
    page = soup(client, '/workbench/part-picker')
    assert not page.select_one('.breadcrumb')
    assert page.select_one('[data-all]').text == 'All incomplete sets' and page.select_one('[data-none]').text == 'Choose sets'
    assert page.select_one('[data-row] .bw-picture') and page.select_one('[data-continue].bw-primary')
    assert [r['value'] for r in page.select('[data-row] input[name=copy]')] == [world.copy_a]
    coll.mark(world.copy_a, '3023', '15', missing=1)
    cards = soup(client, f'/workbench/part-picker?copy={world.copy_a}&pick=1').select('[data-pick] [data-row]')
    assert len(cards) == 2 and sum(not c.has_attr('hidden') for c in cards) == 1
    assert cards[0].select_one('[data-part-position]').text == 'Part 1 of 2'
    for card in cards:
        assert [n['class'][0] for n in card.find_all('div', recursive=False)] == ['bw-picker-media', 'bw-picker-details']
        identity = card.select_one('.bw-identity')
        assert identity.select_one('.bw-colour').find_next_sibling('span')['class'] == ['mono']
        assert not identity.select_one('strong'), 'the part name appears once'
        selector = card.select_one('[data-selector]')
        assert not selector.select('.bw-picture, .bw-identity') and selector.select_one('[data-quantity]').has_attr('hidden')
        assert [n['value'] for n in selector.select('[name=destination]')] == ['set', 'loose', 'list']
        assert selector.select_one('.bw-confirm.bw-primary').text == 'Confirm'
        form = card.select_one('form[data-action=found]')
        assert set(json.loads(form['data-identity'])) == {'item_id', 'color_id'}
    assert 'grid-template-columns:minmax(0,420px) minmax(0,1fr)' in Path('static/web/toni/bw-workbench.css').read_text()


def test_picker_ranking_controls_and_disabled_keys(world, coll, client):
    coll.sql("UPDATE item SET category_name='Plates' WHERE id=?", (world.brick,))
    response = client.get(f'/workbench/part-picker?copy={world.copy_a}&ranked=1&rank=storage&rank=colour&pick=1')
    page = BeautifulSoup(response.text, 'html.parser')
    assert response.status_code == 200 and page.select_one('[data-pick]').has_attr('hidden') is False
    controls = page.select('[data-rank-key] input')
    assert len(controls) == 5
    assert [n['value'] for n in controls if n.has_attr('checked')] == ['storage', 'colour']
    assert page.select_one('[value=size]').has_attr('disabled')
    handle = page.select_one('[data-rank-key="size"] [data-drag]')
    assert handle['tabindex'] == '-1' and handle['aria-disabled'] == 'true' and len(page.select('[data-drag][tabindex="0"]')) == 4
    default = soup(client, f'/workbench/part-picker?copy={world.copy_a}')
    assert [n['data-rank-key'] for n in default.select('[data-rank-key]')] == list(w.PICKER_KEYS)
    assert [n['value'] for n in default.select('[data-rank-key] input[checked]')] == ['category', 'colour', 'set', 'storage']


def test_picker_destination_rows_say_how_many_are_missing(world, coll, client):
    page = soup(client, f'/workbench/part-picker?copy={world.copy_a}&pick=1')
    labels = page.select('.bw-assignments label > span.mono')
    assert labels and all(label.get_text().endswith(' missing') for label in labels)
    jump = client.get('/collection/jump?q=1000-1')
    assert jump.status_code == 200
    copies = [copy for row in jump.json['results'] for copy in row.get('copies', [])]
    assert copies


def test_transfer_route_history_atomicity_and_undo(world, coll, client):
    db = coll.db
    token = csrf(client)
    line = db.execute('SELECT id FROM copy_part WHERE copy_id=? AND item_id=?', (world.copy_a, world.brick)).fetchone()[0]
    data = dict(source_id=world.stock_brick, copy_id=world.copy_a, target='part', target_id=line, quantity=1)
    assert client.post('/workbench/save/transfer', json=data).status_code == 400, 'no CSRF token'
    response = save(client, token, 'transfer', **data)
    assert response.status_code == 200 and response.json['message'] == 'Saved'
    assert db.execute('SELECT missing FROM copy_part WHERE id=?', (line,)).fetchone()[0] == 0
    assert db.execute('SELECT via FROM event WHERE id=?', (response.json['event_id'],)).fetchone()[0] == 'app'
    assert save(client, token, 'transfer', **data).status_code == 400
    page = soup(client, '/workbench/matcher')
    saves = page.select('[data-list=history] article')
    assert len(saves) == 1 and 'transfer' in saves[0].get_text() and '3001' in saves[0].get_text()
    assert saves[0].select_one('[data-undo-event]')['data-undo-event'] == str(response.json['event_id'])
    undone = save(client, token, 'undo', event_id=response.json['event_id'])
    assert undone.json['message'] == 'Undone'
    assert db.execute('SELECT missing FROM copy_part WHERE id=?', (line,)).fetchone()[0] == 1
    assert save(client, token, 'undo', event_id=response.json['event_id']).status_code == 200      # a second Undo does nothing
    assert not soup(client, '/workbench/matcher').select('[data-list=history] article')
    assert save(client, token, 'undo', event_id=1).status_code == 400, 'not a workbench save'
    assert save(client, token, 'nonsense').status_code == 404
    # A refused save leaves no trace.
    db.execute("CREATE TRIGGER reject_workbench BEFORE INSERT ON event WHEN NEW.entity_kind='workbench' BEGIN SELECT RAISE(ABORT,'fixture'); END")
    db.commit()
    assert save(client, token, 'transfer', **data).status_code == 400
    assert db.execute('SELECT missing FROM copy_part WHERE id=?', (line,)).fetchone()[0] == 1 and db.execute('SELECT quantity FROM stock WHERE id=?', (world.stock_brick,)).fetchone()[0] == 3


def test_found_destinations_and_booklets_route(world, coll, client):
    db = coll.db
    token = csrf(client)
    line = db.execute('SELECT id FROM copy_part WHERE copy_id=? AND item_id=?', (world.copy_a, world.brick)).fetchone()[0]
    for destination, assignments in (('set', {str(line): 1}), ('loose', {}), ('list', {})):
        response = save(client, token, 'found', item_id=world.brick, color_id=world.red, destination=destination, assignments=assignments, quantity=1)
        assert response.status_code == 200, (destination, response.json)
        assert save(client, token, 'undo', event_id=response.json['event_id']).json['message'] == 'Undone'
    assert db.execute('SELECT missing FROM copy_part WHERE id=?', (line,)).fetchone()[0] == 1
    assert save(client, token, 'found', item_id=world.brick, color_id=world.red, destination='set', assignments={str(line): 2}, quantity=2).status_code == 400
    assert client.post('/workbench/save/booklets', json={'text': '6081', 'quantity': 1}).status_code == 400
    bad = save(client, token, 'booklets', text='6081\n\nunknown\n123456-1', quantity=1)
    assert bad.status_code == 400 and 'Line 1: 6081' in bad.json['message']


def test_the_login_guard_covers_the_workbench(app4):
    anonymous = app4.test_client()
    for route in ('/workbench/matcher', '/workbench/part-picker', '/workbench/storage'):
        assert anonymous.get(route).status_code in (302, 401, 403)
    assert anonymous.post('/workbench/save/transfer', json={}).status_code in (302, 401, 403)


def test_workbench_browser_runtime():
    if not shutil.which('node'):
        pytest.skip('node is not installed')
    subprocess.run(['node', str(Path(__file__).with_name('toni_bw_workbench_runtime.cjs'))], check=True, capture_output=True, text=True)
