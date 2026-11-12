"""The pull list page of a lot (#202), rendered by the real app on the invented sets of `tests/stickers_world.py`.

Set 9401-1 has the tile in red x4, one sticker sheet and the part `bar` x2 (7 pieces). The lot holds the tile in red x2 and the rare part x1 (which is no part of the set). So the
list starts at 2 of 7 found, 5 would be recorded as missing and 1 piece stays in the lot. Server-rendered: the counters are form posts, the confirm is the same page."""
from bs4 import BeautifulSoup

from tests.app4 import app4, client, csrf  # noqa: F401 (fixtures)
from tests.stickers_world import World, coll, db, pair, world  # noqa: F401 (fixtures)


def base(world, number='9401-1'):
    return f"/collection/lots/{world.lot}/pull/{world.set(number)}"


def page(client, world, query='', tail='', number='9401-1', status=200):
    response = client.get(base(world, number) + tail + query)
    assert response.status_code == status, response.text[:300]
    return BeautifulSoup(response.text, 'html.parser')


def lines(soup):
    return {l.select_one('.bp-nm').text: l for l in soup.select('.bp-line')}


def numbers(soup, root='.bp-card'):
    return [r.select('span')[1].text for r in soup.select(f'{root} .bp-mv')]


def line_of(soup, name):
    return lines(soup)[name]


def count(line):
    return line.select_one('.bp-cnt .v').text


def test_the_page_shows_the_set_its_progress_the_lines_by_category_and_the_card(client, world):
    soup = page(client, world, '?show=all')
    assert soup.select_one('.bp-title').get_text(' ', strip=True).startswith('Stk Set 9401') and '9401-1' in soup.select_one('.bp-title').text
    assert soup.select_one('.bp .lab').text == 'Pull list' and soup.select_one('.crumb a')['href'] == f'/collection/lots/{world.lot}#set-detection'
    assert soup.select_one('.bp-prog').get_text(' ', strip=True) == '2 of 7 pieces found 5 to find'
    assert soup.select_one('.bp-strip i.f')['style'] == 'flex:2' and soup.select('.bp-strip i')[1]['style'] == 'flex:5'
    by_name = lines(soup)
    assert count(by_name['Stk tile']) == '2 of 4' and count(by_name['Stk bar']) == '0 of 2' and count(by_name['Stk sheet-a']) == '0 of 1'
    assert 'Red' in by_name['Stk tile'].select_one('.bw-colour').text and 'already in the lot' in by_name['Stk tile'].text
    groups = [g.text.split(' · ')[0] for g in soup.select('.bp-grp')]
    assert 'Stickers' in groups and groups == sorted(groups) and len(groups) >= 2            # by category, in name order
    assert numbers(soup) == ['2', '5', '1'] and soup.select_one('.bp-card .button.bw-primary').text == 'Make it a copy'
    assert soup.select_one('.bp-card h2').text == 'Make it a copy' and 'Creates your copy of 9401-1 from the 2 pieces found' in soup.select_one('.bp-lead').text
    assert soup.select_one('.bp-bar .bp-bar-count').get_text(' ', strip=True) == '2 found 5 to find'
    assert 'Missing parts show up in Matcher, Complete sets and the missing-parts XML.' in soup.select_one('.bp-note').text
    assert not soup.select('#bp-confirm')


def test_show_search_and_sort_are_the_pages_query(client, world):
    assert set(lines(page(client, world))) == {'Stk tile', 'Stk bar', 'Stk sheet-a'}                 # To find is the default: nothing is complete yet
    assert not lines(page(client, world, '?show=found')) and 'Nothing is found yet' in page(client, world, '?show=found').select_one('.bp-empty').text
    soup = page(client, world, '?show=all&q=bar')
    assert set(lines(soup)) == {'Stk bar'} and soup.select_one('input[name=q]')['value'] == 'bar'
    soup = page(client, world, '?show=all&sort=number')
    assert [g.text.split(' · ')[0] for g in soup.select('.bp-grp')] == ['All parts'] and soup.select_one('select[name=sort] option[selected]').text == 'Number'
    soup = page(client, world, '?q=nothing-like-it')
    assert 'No line matches' in soup.select_one('.bp-empty').text


def test_a_counter_is_a_form_post_that_keeps_the_progress_and_returns_to_the_line(client, world):
    token = csrf(client)
    soup = page(client, world, '?show=all')
    plus = line_of(soup, 'Stk bar').select('.bp-step')[1]
    data = {i['name']: i['value'] for i in plus.select('input')}
    assert data['found'] == '1' and data['item_id'] == str(world.coll.item('parts', 'stk-bar')) and plus.select_one('button')['aria-label'].startswith('One more')
    posted = client.post(base(world) + '/found', data=dict(data, csrf_token=token))
    assert posted.status_code == 302 and posted.headers['Location'].endswith('?show=all#l-' + f"{data['item_id']}-{data['color_id'] or 0}")
    soup = page(client, world, '?show=all')
    assert count(line_of(soup, 'Stk bar')) == '1 of 2' and soup.select_one('.bp-prog').get_text(' ', strip=True) == '3 of 7 pieces found 4 to find' and numbers(soup) == ['3', '4', '1']
    minus = line_of(soup, 'Stk tile').select('.bp-step')[0]
    assert minus.select_one('button').has_attr('disabled'), 'the two pieces the lot holds cannot be un-found'
    tick = line_of(soup, 'Stk bar').select_one('.bp-cbform')
    tick_data = {i['name']: i['value'] for i in tick.select('input')}
    assert tick_data['found'] == '2'
    client.post(base(world) + '/found', data=dict(tick_data, csrf_token=token))
    soup = page(client, world, '?show=all')
    full = line_of(soup, 'Stk bar')
    assert count(full) == '2 of 2' and 'bp-full' in full['class'] and full.select_one('.bp-cb.on') and 'full' in full.select_one('.bp-cnt')['class']
    assert numbers(soup) == ['4', '3', '1']                                                  
    # a later visit shows the same, and a count that is not a number is refused
    assert count(line_of(page(client, world, '?show=all'), 'Stk bar')) == '2 of 2'
    assert client.post(base(world) + '/found', data=dict(data, csrf_token=token, found='x')).status_code == 400
    assert client.post(base(world) + '/found', data=dict(data, csrf_token=token, found='9')).status_code == 400
    assert client.post(base(world) + '/found', data=dict(data, csrf_token='wrong')).status_code in (400, 403)


def test_the_confirm_is_the_same_page_with_the_three_numbers_and_writes_nothing(client, world, db):
    before = db.execute('SELECT count(*) FROM main.event').fetchone()[0]
    soup = page(client, world, tail='/make-copy')
    dialog = soup.select_one('#bp-confirm')
    assert dialog['role'] == 'dialog' and dialog.select_one('h2').text == 'Make 9401-1 a copy?'
    assert numbers(soup, '#bp-confirm') == ['2', '5', '1']
    assert [r.select('span')[0].text for r in dialog.select('.bp-mv')] == ['Found pieces move out of the lot', 'Recorded as missing on the copy', 'Stay in the lot']
    assert 'Incomplete' in dialog.select_one('.bp-status').text and 'Not checked' in dialog.select_one('.bp-status').text
    assert dialog.select_one('form button').text == 'Make copy of 9401-1' and dialog.select_one('.bp-cancel')['href'].endswith(f'/pull/{world.set("9401-1")}')
    assert db.execute('SELECT count(*) FROM main.event').fetchone()[0] == before


def test_make_it_a_copy_moves_the_found_pieces_shows_the_copy_and_undo_takes_it_back(client, world, db):
    token = csrf(client)
    made = client.post(base(world) + '/make-copy', data=dict(csrf_token=token))
    assert made.status_code == 302
    soup = BeautifulSoup(client.get(made.headers['Location']).text, 'html.parser')
    banner = soup.select_one('.bp-done')
    assert banner.text.startswith('Copy made · 2 pieces moved out of the lot') and 'recorded as missing' in banner.text
    copy = db.execute('SELECT id FROM main.copy WHERE item_id=? AND archived_at IS NULL', (world.set('9401-1'),)).fetchone()['id']
    assert banner.select_one('a')['href'].endswith(f"copy={copy}") and banner.select_one('form button').text == 'Undo'
    assert db.execute('SELECT quantity FROM main.stock WHERE id=?', (world.line,)).fetchone()[0] == 0
    assert db.execute('SELECT quantity FROM main.stock WHERE id=?', (world.rare,)).fetchone()[0] == 1                  # the rest of the lot stays
    assert numbers(soup) == ['0', '7', '1'] and 'Nothing' not in banner.text
    event = banner.select_one('input[name=event_id]')['value']
    undone = client.post(base(world) + '/undo', data=dict(csrf_token=token, event_id=event))
    assert undone.status_code == 302 and undone.headers['Location'].endswith('?undone=1')
    soup = BeautifulSoup(client.get(undone.headers['Location']).text, 'html.parser')
    assert soup.select_one('.bp-done').text.startswith('Undone') and numbers(soup) == ['2', '5', '1']
    assert db.execute('SELECT archived_at FROM main.copy WHERE id=?', (copy,)).fetchone()[0] is not None
    assert client.post(base(world) + '/undo', data=dict(csrf_token=token, event_id=event)).status_code == 302      # already undone: nothing more to do
    assert client.post(base(world, '9402-1') + '/undo', data=dict(csrf_token=token, event_id=event)).status_code == 404   # an event of another set
    assert client.post(base(world) + '/undo', data=dict(csrf_token=token, event_id='nonsense')).status_code == 400


def test_a_refusal_shows_on_the_page_and_writes_nothing(client, world, coll, db):
    other = coll.lot('Empty lot')
    url = f"/collection/lots/{other}/pull/{world.set('9401-1')}"
    soup = BeautifulSoup(client.get(url).text, 'html.parser')
    assert soup.select_one('.bp-card .button')['aria-disabled'] == 'true' and 'Nothing found yet' in soup.select_one('.bp-why').text
    assert not BeautifulSoup(client.get(url + '/make-copy').text, 'html.parser').select('#bp-confirm')
    refused = client.post(url + '/make-copy', data=dict(csrf_token=csrf(client)))
    assert refused.status_code == 422 and 'Nothing found yet' in BeautifulSoup(refused.text, 'html.parser').select_one('.bp-error').text
    assert not db.execute("SELECT 1 FROM main.event WHERE field='make_from_stock'").fetchone()


def test_unknown_lots_and_sets_are_404(client, world):
    assert client.get(f"/collection/lots/nothing/pull/{world.set('9401-1')}").status_code == 404
    assert client.get(f'/collection/lots/{world.lot}/pull/987654321').status_code == 404
    assert client.get(f"/collection/lots/{world.lot}/pull/{world.sheet('sheet-a')}").status_code == 404            # a part is no set


def test_a_read_only_instance_shows_the_list_without_writes(client, world, app4):
    app4.config['BW_READ_ONLY'] = True
    soup = page(client, world, '?show=all')
    assert not soup.select('.bp-line form') and not soup.select('.bp-step') and soup.select_one('.bp-card .button')['aria-disabled'] == 'true'
    assert 'switched off' in soup.select_one('.bp-why').text and not page(client, world, tail='/make-copy').select('#bp-confirm')
    token = csrf(client)
    for tail in ('/found', '/make-copy', '/undo'):
        assert client.post(base(world) + tail, data=dict(csrf_token=token, item_id='1', found='1', event_id='1')).status_code == 403
    app4.config['BW_READ_ONLY'] = False
