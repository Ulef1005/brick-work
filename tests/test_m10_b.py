"""M.10 batch B (issue #112): identity on the item page (provider links, preferred link, merge and unmerge, the unidentified item) and the rebuilt
Unresolved items list. One test per screen state of design/approval/112-m10-b. Invented data only."""
import re

from bs4 import BeautifulSoup
import pytest

from brickwork.core import errors, identity_admin
from tests.app4 import STAMP, app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)


def page(client, url):
    response = client.get(url, follow_redirects=True)
    assert response.status_code == 200, (url, response.status_code)
    return BeautifulSoup(response.data, 'html.parser')


def post(client, item, **data):
    return client.post(f'/collection/item/{item}/identity', data={'csrf_token': csrf(client), **data})


def links_text(soup):
    return soup.select_one('[data-identity-module=links]').get_text(' ', strip=True)


def test_m10b1_links_card_shows_the_leg_rule_by_colour(coll, client):
    leg, black = coll.item('parts', '970c03'), coll.colour('0')
    coll.add_stock('part', leg, colour=black, quantity=4)
    text = links_text(page(client, f'/collection/item/{leg}?colour={black}'))
    assert 'BrickLink' in text and '970c00' in text and '970c11' in text and 'Rebrickable' in text and '970c03' in text
    assert 'Black only' in text.replace('Black only', 'Black only') and 'All other colours' in text and 'Used for Black' in text and 'matched' in text
    swatch = page(client, f'/collection/item/{leg}?colour={black}').select_one('[data-identity-module=links] .bc-colour')
    assert swatch.get_text(strip=True) == 'Black' and 'background:#' in swatch['style']


def test_m10b1_every_status_pill_and_the_rows_without_a_key(coll, client, world):
    red = world.red
    coll.link(world.brick, '3001a', kind='P', status='inferred')
    coll.link(world.brick, '3001b', kind='P', colour=red, status='manual', preferred=1)
    coll.link(world.brick, '3001-old', kind='parts', provider='rebrickable', status='to_check')
    soup = page(client, f'/collection/item/{world.brick}?colour={red}')
    text = links_text(soup)
    assert 'LEGO' not in text
    for word in ('matched', 'inferred', 'manual', 'to check', 'Preferred', 'Used for Red', 'catalogue number'):
        assert word in text, word


def test_m10b1_a_provider_row_without_a_key(coll, client, world):
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'rebrickable','unmatched','no_match',NULL,?)", (world.local_part, STAMP))
    text = links_text(page(client, f'/collection/item/{world.local_part}?colour={world.red}'))
    assert 'No Rebrickable number' in text and 'No match found' in text and 'own number' in text and 'LEGO' not in text


def test_m10b2_choosing_the_preferred_link_for_all_colours_or_one(coll, client, world):
    sheet = coll.item('parts', '003402')
    coll.add_stock('part', sheet, colour=world.white, quantity=3)
    soup = page(client, f'/collection/item/{sheet}?colour={world.white}')
    dialog = soup.select_one('#bi-prefer-bricklink')
    assert dialog and [r['value'] for r in dialog.select('input[name=link]')] and dialog.select_one('button[name=colour]')
    assert 'Prefer for all colours' in dialog.get_text() and 'only' in dialog.get_text()
    ids = {r['provider_key']: r['id'] for r in coll.db.execute("SELECT id, provider_key FROM main.item_link WHERE item_id=? AND provider='bricklink'", (sheet,))}
    response = post(client, sheet, action='prefer', link=str(ids['311.1stk01']), colour=str(world.white))
    assert response.status_code == 302 and 'done=' in response.headers['Location']
    row = coll.db.execute("SELECT status, origin, preferred FROM main.item_link WHERE item_id=? AND color_id=?", (sheet, world.white)).fetchone()
    assert tuple(row) == ('manual', 'user', 1)
    soup = page(client, response.headers['Location'])
    assert 'Preferred link saved' in soup.get_text() and soup.select_one('.bi-notice input[value=undo]')
    event = int(re.search(r'done=(\d+)', response.headers['Location']).group(1))
    assert post(client, sheet, action='undo', event=str(event)).status_code == 302
    assert coll.db.execute("SELECT count(*) FROM main.item_link WHERE item_id=? AND color_id=?", (sheet, world.white)).fetchone()[0] == 0
    post(client, sheet, action='prefer', link=str(ids['312.3stk01']))
    assert coll.db.execute("SELECT preferred FROM main.item_link WHERE id=?", (ids['312.3stk01'],)).fetchone()[0] == 1


def tie(coll, world):
    local = coll.local('part', 'Brick, tied', born_key='3001')
    coll.link(local, '3001', kind='P', status='matched')
    coll.add_stock('part', local, colour=world.red, quantity=2, condition='used')
    coll.add_wish(local, colour=world.red, quantity=2)
    return local


def test_m10b3_merge_pick_preview_and_confirm_with_undo(coll, client, world):
    local = tie(coll, world)
    assert 'Merge into…' in links_text(page(client, f'/collection/item/{local}?colour={world.red}'))
    soup = page(client, f'/collection/item/{local}/merge')
    assert soup.select_one('input[name=q]') and 'Brick 2 x 4' in soup.select_one('.bi-results').get_text() and 'same BrickLink number' in soup.get_text()
    soup = page(client, f'/collection/item/{local}/merge?target={world.brick}')
    moves = soup.select_one('.bi-moves').get_text(' ', strip=True)
    assert 'wishes' in moves.lower() and 'loose stock' in moves.lower()
    assert soup.select_one('form input[name=action][value=merge]') and 'Merge into Brick 2 x 4' in soup.get_text()
    assert coll.db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()[0] is None      # the preview changed nothing
    response = post(client, local, action='merge', target=str(world.brick))
    assert response.status_code == 302
    soup = page(client, response.headers['Location'])
    assert 'Merged Brick, tied into this item' in soup.select_one('.bi-notice').get_text() and soup.select_one('.bi-notice input[value=undo]')
    event = int(re.search(r'done=(\d+)', response.headers['Location']).group(1))
    post(client, world.brick, action='undo', event=str(event))
    assert coll.db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()[0] is None


def test_m10b3_the_preview_says_busy_when_the_database_is_locked(coll, client, world, pair, monkeypatch):
    import sqlite3
    from contextlib import closing
    local = tie(coll, world)
    monkeypatch.setattr(identity_admin, 'PREVIEW_WAIT_MS', 50)
    with closing(sqlite3.connect(pair, isolation_level=None)) as other:
        other.execute('BEGIN IMMEDIATE')                                   # a sync holding the write lock
        soup = page(client, f'/collection/item/{local}/merge?target={world.brick}')
        other.execute('ROLLBACK')
    text = soup.select_one('.bi-preview').get_text(' ', strip=True)
    assert 'Busy, try again' in text and 'sync or a job' in text and not soup.select_one('input[name=action][value=merge]')
    assert soup.select_one('.bi-preview a.bi-btn')['href'].endswith(f'target={world.brick}')
    assert 'What moves' in page(client, f'/collection/item/{local}/merge?target={world.brick}').get_text()      # and it works again once the lock is gone


def test_m10b3_the_merge_page_is_closed_on_a_read_only_instance(coll, client, world, app4):
    local = tie(coll, world)
    app4.config['BW_READ_ONLY'] = True
    response = client.get(f'/collection/item/{local}/merge')
    assert response.status_code == 403 and b'Changes are switched off on this instance' in response.data


def test_m10b2_set_preferred_every_branch(coll, world):
    sheet = coll.item('parts', '003402')
    coll.add_stock('part', sheet, colour=world.white, quantity=1)
    db = coll.db
    ids = {r['provider_key']: r['id'] for r in db.execute("SELECT id, provider_key FROM main.item_link WHERE item_id=? AND provider='bricklink'", (sheet,))}
    # all colours: the chosen unscoped link is preferred, nothing else
    result = identity_admin.set_preferred(db, ids['311.1stk01'])
    assert [r['provider_key'] for r in db.execute('SELECT provider_key FROM main.item_link WHERE item_id=? AND preferred=1', (sheet,))] == ['311.1stk01']
    # choosing another moves the mark
    identity_admin.set_preferred(db, ids['312.3stk01'])
    assert [r['provider_key'] for r in db.execute('SELECT provider_key FROM main.item_link WHERE item_id=? AND preferred=1', (sheet,))] == ['312.3stk01']
    from tests.app4 import table_digest
    before = table_digest(db)
    # one colour: a scoped manual row of the user's own, the unscoped choice stays
    event = identity_admin.set_preferred(db, ids['310.3stk01'], world.white)['event_id']
    scoped = db.execute('SELECT status, method, origin, preferred, provider_key FROM main.item_link WHERE item_id=? AND color_id=?', (sheet, world.white)).fetchall()
    assert [tuple(r) for r in scoped] == [('manual', 'user', 'user', 1, '310.3stk01')]
    assert db.execute('SELECT preferred FROM main.item_link WHERE id=?', (ids['312.3stk01'],)).fetchone()[0] == 1
    from brickwork.core import undo
    undo.undo_event(db, event)                                                            # Undo restores exactly
    assert table_digest(db) == before
    assert db.execute('SELECT count(*) FROM main.item_link WHERE item_id=? AND color_id IS NOT NULL', (sheet,)).fetchone()[0] == 0
    assert [r['provider_key'] for r in db.execute('SELECT provider_key FROM main.item_link WHERE item_id=? AND preferred=1', (sheet,))] == ['312.3stk01']
    with pytest.raises(errors.ValidationFailed):                                           # a one-colour link cannot be preferred for all colours
        identity_admin.set_preferred(db, _scoped(coll, world))
    with pytest.raises(errors.NotFound):                                                   # a link that does not exist
        identity_admin.set_preferred(db, 999999)
    coll.link(world.brick, '3001q', kind='P', status='to_check')
    with pytest.raises(errors.Conflict):                                                   # an unconfirmed link must be confirmed first
        identity_admin.set_preferred(db, db.execute("SELECT id FROM main.item_link WHERE provider_key='3001q'").fetchone()[0])


def _scoped(coll, world):
    coll.link(world.brick, '3001s', kind='P', colour=world.red, status='matched')
    return coll.db.execute("SELECT id FROM main.item_link WHERE provider_key='3001s'").fetchone()[0]


def test_m10b2_a_link_that_does_not_belong_to_the_item_is_refused(coll, client, world):
    sheet = coll.item('parts', '003402')
    coll.add_stock('part', sheet, colour=world.white, quantity=1)
    other = coll.db.execute("SELECT id FROM main.item_link WHERE item_id=? AND provider='bricklink' LIMIT 1", (world.brick,)).fetchone()
    response = post(client, sheet, action='prefer', link=str(other['id']))
    assert response.status_code == 302 and 'done=' not in response.headers['Location']
    assert coll.db.execute('SELECT preferred FROM main.item_link WHERE id=?', (other['id'],)).fetchone()[0] == 0


def test_m10b3_the_refusals_in_plain_words(coll, client, world):
    soup = page(client, f'/collection/item/{world.brick}/merge')                       # a live catalogue item cannot be merged away
    assert 'part of the catalogue' in soup.select_one('.bi-refusal').get_text()
    assert 'Merge into…' not in links_text(page(client, f'/collection/item/{world.brick}?colour={world.red}'))
    double = coll.local('part', 'Second entry', born_key='dup')
    line = coll.db.execute('SELECT * FROM main.copy_part WHERE copy_id=? AND item_id=? AND retired_at IS NULL LIMIT 1', (world.copy_a, world.brick)).fetchone()
    generated = {r['name'] for r in coll.db.execute('PRAGMA main.table_xinfo(copy_part)') if r['hidden'] in (2, 3)}
    values = {c: line[c] for c in line.keys() if c != 'id' and c not in generated} | {'item_id': double}
    coll.sql(f'INSERT INTO main.copy_part({",".join(values)}) VALUES({",".join("?" * len(values))})', tuple(values.values()))
    soup = page(client, f'/collection/item/{double}/merge?target={world.brick}')
    refusal = soup.select_one('.bi-refusal').get_text(' ', strip=True)
    assert 'not allowed' in refusal and 'One of your copies holds a part line for both items' in refusal and 'by hand' in refusal
    assert not soup.select_one('input[name=action][value=merge]')


def test_m10b4_a_merged_item_and_the_refusal_to_unmerge(coll, client, world):
    clean, changed = tie(coll, world), coll.local('part', 'Brick, old entry', born_key='3001-old')
    coll.add_stock('part', changed, colour=world.white, quantity=3, condition='new')
    identity_admin.merge_item(coll.db, clean, world.brick)             # in either order: a freed row id is no longer reused (#124)
    identity_admin.merge_item(coll.db, changed, world.brick)
    coll.sql('UPDATE main.stock SET quantity=quantity+1 WHERE item_id=? AND color_id=? AND condition=?', (world.brick, world.white, 'new'))
    redirect = client.get(f'/collection/item/{clean}')
    assert redirect.status_code == 301
    soup = page(client, redirect.headers['Location'] + f'?colour={world.red}')
    assert 'was merged into this item' in soup.select_one('.bi-notice-info').get_text()                    # the old address says where the visitor came from
    cards = soup.select('#bi-merged .bi-merged')
    assert len(cards) == 2
    by_name = {c.select_one('strong').get_text(): c for c in cards}
    assert not by_name['Brick, tied'].select_one('button[disabled]') and not by_name['Brick, tied'].select_one('.bi-refusal')
    blocked = by_name['Brick, old entry']
    assert blocked.select_one('button[disabled]') and 'Unmerge is not possible' in blocked.select_one('.bi-refusal').get_text() and 'Undo the later change first' in blocked.get_text()
    merge_id = int(by_name['Brick, tied'].select_one('input[name=merge]')['value'])
    assert post(client, world.brick, action='unmerge', merge=str(merge_id)).status_code == 302
    assert coll.db.execute('SELECT merged_into FROM main.item WHERE id=?', (clean,)).fetchone()[0] is None


def test_m10b5_unresolved_list_pattern_and_what_the_copies_use(coll, client, world):
    local = coll.local('part', 'Plate, tied', born_key='3023')
    coll.link(local, '3023', kind='P', status='matched')
    coll.link(local, 'dupupn0123', kind='parts', provider='rebrickable', status='to_check')
    coll.add_stock('part', local, colour=world.white, quantity=1)
    soup = page(client, '/manage/unresolved')
    assert soup.select_one('[data-bu-search]') and soup.select_one('[data-bu-open=filters]') and soup.select_one('[data-bu-open=sort]') and soup.select_one('[data-bu-count]')
    assert {i['value'] for i in soup.select('[data-bu-filter]')} >= {'', 'merge', 'unidentified'}
    row = soup.select_one(f'#item-{local}')
    assert 'merge' in row['data-facets'] and len(row.select('.bu-cand')) == 2
    text = [c.get_text(' ', strip=True) for c in row.select('.bu-cand')]
    assert any('Your copies use this one' in t and 'Same BrickLink number' in t for t in text) and any('Not used in your copies' in t and 'Migration guess' in t for t in text)
    assert row.select_one('button[value=merge]') and row.select_one('input[name=number]')
    link_row = soup.select_one(f'#item-{world.mystery}')
    assert link_row.select_one('button[value=link]') and 'unidentified' in link_row['data-facets']


def test_m10b5_unresolved_confirm_and_reject_rows(coll, client, world):
    coll.link(world.figure, 'syn-fig-guess', kind='M', status='to_check')
    soup = page(client, '/manage/unresolved')
    row = soup.select_one(f'#item-{world.figure}')
    assert row.select_one('button[value=confirm]') and row.select_one('button[value=reject]') and 'to check' in row.get_text()


def test_m10b6_the_unidentified_item_explains_and_offers_two_ways(coll, client, world):
    soup = page(client, f'/collection/item/{world.mystery}')
    assert not soup.select('[data-module=matching] [data-bc-search]')                       # no empty search over 0 results
    card = soup.select_one('[data-identity-module=unidentified]').get_text(' ', strip=True)
    assert 'Not identified yet' in card and 'Price updates skip it' in card and 'BrickLink export' in card
    assert soup.select_one('[data-identity-module=unidentified] input[name=number]') and soup.select_one('[data-identity-module=unidentified] a[href$="/merge"]')
    assert post(client, world.mystery, action='link', number='3001').status_code == 302
    assert page(client, f'/collection/item/{world.mystery}').select_one('[data-identity-module=unidentified]') is None
