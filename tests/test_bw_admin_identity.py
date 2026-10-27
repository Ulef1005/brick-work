"""Identity admin of Tools & Admin on the 4.0 store (M.8i part 2, issue #110; design 3.2, 3.5, 3.6, 3.8): the Unresolved items list, merging a
local item into a catalogue item, confirming or rejecting a guess, linking a number, the kind move, and Undo of each. Invented data only."""
import json
import re

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, errors, identity_admin, undo
from brickwork.web import admin_ops
from tests.app4 import STAMP, app4, client, coll, csrf, pair, read, table_digest, world  # noqa: F401  (the fixtures)


def post(client, **data):
    return client.post('/manage/unresolved', data={'csrf_token': csrf(client), **data})


def tie(coll, world):
    """A local BrickLink-born part whose number is the BrickLink number of the catalogue brick: the rule-4 tie (design 8.3), plus its migration guess."""
    local = coll.local('part', 'Brick, tied', born_key='3001')
    coll.link(local, '3001', kind='P', status='matched')
    coll.link(local, '3001', kind='parts', provider='rebrickable', status='to_check')
    coll.add_stock('part', local, colour=world.red, quantity=2, condition='used')
    return local


def rows(db):
    return {r['item_id']: r for r in identity_admin.unresolved(db)}


def test_the_list_holds_what_needs_a_decision_and_nothing_else(coll, world):
    db = coll.db
    found = rows(db)
    assert set(found) == {world.mystery} and found[world.mystery]['reasons'] == ['unidentified']      # the local part and booklet are fine as they are
    local = tie(coll, world)
    found = rows(db)
    assert found[local]['reasons'] == ['merge'] and [c['item_id'] for c in found[local]['candidates']] == [world.brick]
    assert found[local]['candidates'][0]['how'] == 'to_check' and found[local]['links'] == []
    assert identity_admin.count_unresolved(db) == len(found) == admin.count_unresolved(db) == 2
    assert identity_admin.reason_counts(db) == {'merge': 1, 'link': 0, 'status': 0, 'unidentified': 1}


def test_a_rule_4_tie_without_a_migration_guess_still_names_the_catalogue_item(coll, world):
    local = coll.local('part', 'Brick, tied', born_key='3001')
    coll.add_stock('part', local, colour=world.red, quantity=1, condition='new')
    entry = rows(coll.db)[local]
    assert [(c['item_id'], c['how']) for c in entry['candidates']] == [(world.brick, 'same_number')]


def test_a_to_check_link_and_a_status_are_listed_for_a_referenced_catalogue_item_only(coll, world):
    db = coll.db
    coll.link(world.brick, '3001x', kind='P', status='to_check')
    coll.link(world.figure, 'syn-fig-guess', kind='M', status='to_check')
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','no_candidate',NULL,?)", (world.plate, STAMP))
    spare = coll.item('parts', '970c22')
    coll.link(spare, 'zzz', kind='P', status='to_check')                                              # a catalogue item nothing references
    found = rows(db)
    assert spare not in found
    assert found[world.brick]['reasons'] == ['link'] and found[world.plate]['reasons'] == ['status'] and found[world.figure]['reasons'] == ['link']
    assert found[world.brick]['links'][0]['provider_key'] == '3001x'


def test_merging_a_candidate_through_the_screen_and_undoing_it(coll, client, world):
    db = coll.db
    local = tie(coll, world)
    before = table_digest(db)
    response = post(client, action='merge', item=str(local), target=str(world.brick))
    assert response.status_code == 302 and 'done=' in response.headers['Location']
    assert db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()[0] == world.brick
    assert local not in rows(db)
    event = int(re.search(r'done=(\d+)', response.headers['Location']).group(1))
    page = BeautifulSoup(client.get(response.headers['Location']).data, 'html.parser')
    assert page.select_one('input[name=action][value=undo]') and page.select_one('input[name=event]')['value'] == str(event)
    assert post(client, action='undo', event=str(event)).status_code == 302
    assert table_digest(db) == before and local in rows(db)
    assert db.execute('SELECT 1 FROM main.event_undo WHERE event_id=?', (event,)).fetchone()
    assert client.get(f'/manage/unresolved?done={event}').data.count(b'value="undo"') == 0              # nothing left to undo


def test_a_typed_number_picks_the_target_and_says_when_it_is_none(coll, client, world):
    db = coll.db
    local = tie(coll, world)
    page = post(client, action='merge', item=str(local), number='no-such-part')
    assert page.status_code == 302 and db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()[0] is None
    assert 'No part has the number' in client.get('/manage/unresolved').get_data(as_text=True)
    post(client, action='merge', item=str(local), number='3001')
    assert db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()[0] == world.brick


def test_a_merge_the_rules_refuse_says_why_and_changes_nothing(coll, client, world):
    db = coll.db
    local = tie(coll, world)
    before = table_digest(db)
    post(client, action='merge', item=str(local), target=str(world.keep))                              # a set: another kind
    assert 'its own kind' in client.get('/manage/unresolved').get_data(as_text=True)
    post(client, action='merge', item=str(world.brick), target=str(local))                             # a live catalogue item as the loser
    assert 'live catalogue item' in client.get('/manage/unresolved').get_data(as_text=True)
    assert table_digest(db) == before


def test_confirm_reject_settle_and_link_each_have_an_undo(coll, world):
    db = coll.db
    coll.link(world.brick, '3001x', kind='P', status='to_check')
    coll.link(world.plate, '3023x', kind='P', status='to_check')
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','no_candidate',NULL,?)", (world.figure, STAMP))
    link_a = db.execute("SELECT id FROM main.item_link WHERE provider_key='3001x'").fetchone()[0]
    link_b = db.execute("SELECT id FROM main.item_link WHERE provider_key='3023x'").fetchone()[0]
    before = table_digest(db)
    steps = [identity_admin.confirm_link(db, link_a), identity_admin.reject_link(db, link_b), identity_admin.settle_status(db, world.figure, 'bricklink', 'no_candidate'),
             identity_admin.add_link(db, world.mystery, ' 4711 ')]
    assert tuple(db.execute('SELECT status, origin, method FROM main.item_link WHERE id=?', (link_a,)).fetchone()) == ('manual', 'user', 'user')
    assert db.execute("SELECT 1 FROM main.item_link WHERE provider_key='3023x'").fetchone() is None
    assert db.execute("SELECT status FROM main.item_provider_status WHERE item_id=?", (world.figure,)).fetchone()[0] == 'unmatched'
    assert tuple(db.execute("SELECT provider_kind, provider_key, status FROM main.item_link WHERE item_id=?", (world.mystery,)).fetchone()) == ('G', '4711', 'manual')
    assert world.brick not in rows(db) and world.plate not in rows(db) and world.figure not in rows(db)      # every decision settled what it asked about
    for step in reversed(steps):
        assert undo.undo_event(db, step['event_id'])['already_undone'] is False
    assert table_digest(db) == before
    assert undo.undo_event(db, steps[0]['event_id'])['already_undone'] is True


def test_the_decisions_refuse_what_is_not_theirs_to_make(coll, world):
    db = coll.db
    local = tie(coll, world)
    guess = db.execute("SELECT id FROM main.item_link WHERE item_id=? AND provider='rebrickable'", (local,)).fetchone()[0]
    with pytest.raises(errors.ValidationFailed, match='merge it into that item'):
        identity_admin.confirm_link(db, guess)
    settled = db.execute("SELECT id FROM main.item_link WHERE item_id=? AND provider='bricklink'", (local,)).fetchone()[0]
    with pytest.raises(errors.Conflict, match='no longer to check'):
        identity_admin.reject_link(db, settled)
    with pytest.raises(errors.Conflict, match='belongs to item'):
        identity_admin.add_link(db, world.local_part, '3001')
    with pytest.raises(errors.ValidationFailed, match='without spaces'):
        identity_admin.add_link(db, world.mystery, 'two words')
    identity_admin.add_link(db, world.mystery, 'g1')
    with pytest.raises(errors.Conflict, match='already'):
        identity_admin.add_link(db, world.mystery, 'g1')


def test_a_decision_undo_is_refused_after_a_later_change(coll, world):
    db = coll.db
    coll.link(world.brick, '3001x', kind='P', status='to_check')
    link = db.execute("SELECT id FROM main.item_link WHERE provider_key='3001x'").fetchone()[0]
    step = identity_admin.confirm_link(db, link)
    coll.sql("UPDATE item_link SET preferred=1 WHERE id=?", (link,))
    with pytest.raises(errors.UndoBlocked, match='changed since'):
        undo.undo_event(db, step['event_id'])


def test_the_kind_move_is_offered_from_the_list_and_undone_from_the_screen(coll, client, world):
    db = coll.db
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','kind_differs',?,?)",
             (world.mystery, json.dumps({'from': 'gear', 'to': 'book'}), STAMP))
    entry = rows(db)[world.mystery]
    assert entry['reasons'] == ['status', 'unidentified'] or entry['reasons'] == ['unidentified', 'status']
    assert entry['statuses'][0]['to'] == 'book'
    page = BeautifulSoup(client.get('/manage/unresolved').data, 'html.parser')
    assert page.select_one('button[name=action][value=move_kind]').get_text() == 'Move to book'
    before = table_digest(db)
    response = post(client, action='move_kind', item=str(world.mystery), kind='book')
    assert db.execute('SELECT kind FROM main.item WHERE id=?', (world.mystery,)).fetchone()[0] == 'book'
    event = int(re.search(r'done=(\d+)', response.headers['Location']).group(1))
    post(client, action='undo', event=str(event))
    assert table_digest(db) == before


def test_the_screen_renders_every_kind_of_row_and_its_forms_carry_one_token(coll, client, world):
    tie(coll, world)
    coll.link(world.brick, '3001x', kind='P', status='to_check')
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','to_check','kind_differs',?,?)",
             (world.mystery, json.dumps({'from': 'gear', 'to': 'book'}), STAMP))
    response = client.get('/manage/unresolved')
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    assert soup.select_one('main h1').get_text() == 'Unresolved items'
    token = csrf(client)
    forms = soup.select('form[method=post]')
    assert len(forms) >= 6
    for form in forms:
        assert [f['value'] for f in form.select('input[name=csrf_token]')] == [token]
    text = soup.get_text(' ')
    assert 'Merge into this' in text and 'Confirm' in text and 'Reject' in text and 'Keep as unmatched' in text and 'Link BrickLink number' in text


def test_the_hub_row_counts_the_list(coll, client, world):
    tie(coll, world)
    soup = BeautifulSoup(client.get('/manage/tools').data, 'html.parser')
    row = next(a for a in soup.select('.bw-hub a.bw-hub-row') if a['href'] == '/manage/unresolved')
    assert row.select_one('.bw-hub-title').get_text() == 'Unresolved items'
    assert row.select_one('.bw-hub-signal').get_text() == f'{identity_admin.count_unresolved(coll.db)} to decide'


def test_a_merged_item_leaves_the_list_and_its_page_redirects(coll, client, world):
    db = coll.db
    local = tie(coll, world)
    identity_admin.merge_item(db, local, world.brick)
    assert local not in rows(db)
    response = client.get(f'/collection/item/{local}')
    assert response.status_code == 301 and response.headers['Location'].endswith(f'/collection/item/{world.brick}')


def test_the_candidates_carry_the_items_own_name_and_number(coll, world):
    local = tie(coll, world)
    candidate = rows(coll.db)[local]['candidates'][0]
    assert candidate['name'] == 'Brick 2 x 4' and candidate['number_text'].startswith('3001')


@pytest.mark.parametrize('action', ['merge', 'confirm', 'reject', 'settle', 'link', 'move_kind', 'undo'])
@pytest.mark.parametrize('token', [None, 'wrong'])
def test_unresolved_csrf_rejects_before_dispatch_without_writes(client, world, pair, monkeypatch, action, token):
    client.get('/manage/unresolved')

    def forbidden(*args, **kwargs):
        pytest.fail('Invalid CSRF reached an admin write')
    monkeypatch.setattr(admin_ops, 'tools_write', forbidden)
    data = {'action': action}
    if token is not None:
        data['csrf_token'] = token
    assert client.post('/manage/unresolved', data=data).status_code == 400


def test_an_unknown_action_and_a_missing_field_save_nothing(coll, client, world):
    db = coll.db
    before = table_digest(db)
    for data in ({'action': 'nonsense'}, {'action': 'merge'}, {'action': 'confirm', 'link': 'x'}, {'action': 'settle', 'item': str(world.mystery)}):
        assert post(client, **data).status_code == 302
    assert table_digest(db) == before
    assert 'Identity decision' in client.get('/manage/unresolved').get_data(as_text=True)


def test_a_read_only_instance_cannot_decide(coll, client, world, monkeypatch):
    local = tie(coll, world)
    csrf(client)
    monkeypatch.setattr('brickwork.api.read_only', lambda: True)
    assert client.post('/manage/unresolved', data={'csrf_token': csrf(client), 'action': 'merge', 'item': str(local), 'target': str(world.brick)}).status_code == 403
    assert coll.db.execute('SELECT merged_into FROM main.item WHERE id=?', (local,)).fetchone()[0] is None


def test_a_linked_number_gives_an_unidentified_item_an_identity_without_a_born_key(coll, world):
    """Finding 4 (design 3.8: resolving an unidentified item is adding a link; born keys are immutable): the list, the picture refresh and the
    bulk price refresh follow the confirmed link, and Undo puts the item back exactly."""
    from brickwork.core import items, pictures, pipeline
    db = coll.db
    assert world.mystery in rows(db) and rows(db)[world.mystery]['reasons'] == ['unidentified']
    assert not items.identified(db, world.mystery) and pictures.state(db)['unidentified'] == 1
    assert world.mystery not in {r['item_id'] for r in admin.stale_prices(db)}
    before = table_digest(db)
    step = identity_admin.add_link(db, world.mystery, '4711')
    assert db.execute('SELECT born_key FROM main.item WHERE id=?', (world.mystery,)).fetchone()[0] is None
    assert world.mystery not in rows(db) and items.identified(db, world.mystery)
    assert pictures.state(db)['unidentified'] == 0 and world.mystery in pictures.selection(db, 'all', ['gear'])['item_ids']
    assert world.mystery in {r['item_id'] for r in admin.stale_prices(db)}
    assert pipeline._identity(db, world.mystery) == (None, None)
    undo.undo_event(db, step['event_id'])
    assert table_digest(db) == before and world.mystery in rows(db)
