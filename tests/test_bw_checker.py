"""Check Set Parts on the 4.0 store (M.8d, issue #110): sessions on `part_check`, tokens by line id, receipts and Undo on `event`.

The fixture copy is a copy of `1000-1` (RICH in tests/app4.py): two required parts (3001 red x4, 3023 white x2), one spare part, and a
figure line (2 x fig-000004) with four own parts. Invented data, no network."""
import json
from pathlib import Path
import sqlite3
import uuid

from bs4 import BeautifulSoup
import pytest

from brickwork.core import checker, undo
from brickwork.store4 import copies
from tests.app4 import app4, client, coll, csrf, pair, read  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def copy(coll):
    return coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')


def mutate(db, copy_id, action, figure=None, **values):
    """One checker request as the script sends it (a fresh operation id each time)."""
    s = checker.session(db, copy_id, figure)
    return checker.write(db, copy_id, dict(action=action, operation=uuid.uuid4().hex, session=s['id'] if s else None, **values), figure)


def start(db, copy_id, **values):
    mutate(db, copy_id, 'start', **values)
    return checker.view(db, copy_id)


def answer_all(db, copy_id, state):
    for r in state['rows']:
        if r['kind'] != 'spare':
            mutate(db, copy_id, 'answer', token=r['token'], found=r['quantity'])


def test_the_sequence_is_parts_then_figures_and_the_spare_is_asked_last(coll, copy):
    db = coll.db
    state = start(db, copy)
    kinds = {r['token']: r['kind'] for r in state['rows']}
    assert [kinds[t] for t in state['session']['order']] == ['part', 'part', 'figure']
    assert sorted(kinds.values()) == ['figure', 'part', 'part', 'spare']
    assert state['session']['spares'] is None and all(t.startswith(('p:', 'f:')) for t in state['session']['order'])
    # the row of the session: order mode and spares answer are columns, the walk is the body
    row = db.execute('SELECT order_mode, spares, finished, copy_figure_id FROM part_check WHERE copy_id=?', (copy,)).fetchone()
    assert tuple(row) == ('inventory', None, 0, None)
    spare = next(r for r in state['rows'] if r['kind'] == 'spare')
    mutate(db, copy, 'spares', include=True)
    assert checker.session(db, copy)['order'][-1] == spare['token'] and checker.session(db, copy)['spares'] == 'yes'
    with pytest.raises(ValueError, match='already included'):
        mutate(db, copy, 'spares', include=True)


def test_an_answer_the_count_found_one_undo_and_a_retried_request(coll, copy):
    db = coll.db
    state = start(db, copy)
    part = next(r for r in state['rows'] if r['kind'] == 'part' and r['quantity'] == 4)
    before = checker.snapshot(db, copy, [part['token']])
    saved = mutate(db, copy, 'answer', token=part['token'], found=3)
    assert saved['session']['misses'] == [part['token']] and saved['progress']['missing'] == 1
    row = next(r for r in saved['rows'] if r['token'] == part['token'])
    assert (row['missing'], row['checked'], row['damaged']) == (1, 1, 0)
    payload = dict(action='found_one', token=part['token'], operation='retry-1', session=saved['session']['id'])
    checker.write(db, copy, payload)
    again = checker.write(db, copy, payload)                                    # the same operation id: the first answer, not a second
    assert next(r for r in again['rows'] if r['token'] == part['token'])['missing'] == 0
    assert again['session']['misses'] == [part['token']]                        # a recovered miss stays in the history
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='part_check' AND json_extract(new_value,'$.operation')='retry-1'").fetchone()[0] == 1
    mutate(db, copy, 'undo')
    assert db.execute('SELECT missing FROM copy_part WHERE id=?', (part['id'],)).fetchone()[0] == 1
    mutate(db, copy, 'undo')
    assert checker.snapshot(db, copy, [part['token']]) == before
    undone = db.execute("SELECT count(*) FROM event_undo u JOIN event e ON e.id=u.event_id WHERE e.entity_kind='part_check'").fetchone()[0]
    assert undone == 2


def test_an_undo_is_retried_without_undoing_a_second_step(coll, copy):
    db = coll.db
    state = start(db, copy)
    first, second = state['session']['order'][:2]
    mutate(db, copy, 'answer', token=first, found=1)
    mutate(db, copy, 'answer', token=second, found=1)
    payload = dict(action='undo', operation='undo-retry', session=checker.session(db, copy)['id'])
    checker.write(db, copy, payload)
    checker.write(db, copy, payload)
    assert checker.session(db, copy)['answers'] == {first: 'answered'}


@pytest.mark.parametrize('source', ['derived', 'manual'])
def test_finish_needs_every_answer_and_leaves_spares_and_manual_completeness(coll, copy, source):
    db = coll.db
    coll.sql('UPDATE copy SET completeness_source=?, completeness=? WHERE id=?', (source, 'sealed' if source == 'manual' else 'incomplete', copy))
    state = start(db, copy)
    with pytest.raises(ValueError, match='Answer the skipped'):
        mutate(db, copy, 'finish', checked=True)
    answer_all(db, copy, state)
    mutate(db, copy, 'spares', include=True)
    spare = next(r for r in state['rows'] if r['kind'] == 'spare')
    mutate(db, copy, 'answer', token=spare['token'], found=0)                      # a missing spare never counts
    done = mutate(db, copy, 'finish', checked=True)
    assert done['copy']['set_checked'] is True
    assert done['copy']['completeness'] == ('complete' if source == 'derived' else 'sealed')
    mutate(db, copy, 'undo')
    assert not checker.session(db, copy)['finished'] and not checker.checked(db, copy)
    figure = next(r for r in state['rows'] if r['kind'] == 'figure')
    mutate(db, copy, 'answer', token=figure['token'], found=0)                      # both figures missing: the set is incomplete
    done = mutate(db, copy, 'finish', checked=True)
    assert done['copy']['completeness'] == ('incomplete' if source == 'derived' else 'sealed')


def test_skip_back_next_select_and_a_failed_receipt_rolls_everything_back(coll, copy):
    db = coll.db
    state = start(db, copy)
    token = state['session']['order'][0]
    assert mutate(db, copy, 'skip', token=token)['session']['answers'][token] == 'skipped'
    assert mutate(db, copy, 'back')['session']['cursor'] == 0
    assert mutate(db, copy, 'next')['session']['cursor'] == 1
    assert mutate(db, copy, 'select', token=token)['session']['cursor'] == 0
    old = checker.snapshot(db, copy, [token])
    db.execute("CREATE TRIGGER reject_checker_event BEFORE INSERT ON event WHEN new.entity_kind='part_check' BEGIN SELECT RAISE(ABORT,'no'); END")
    with pytest.raises(sqlite3.IntegrityError):
        mutate(db, copy, 'answer', token=token, found=0)
    assert checker.snapshot(db, copy, [token]) == old
    db.execute('DROP TRIGGER reject_checker_event')


def test_bounds_undo_conflict_and_an_archived_copy(coll, copy):
    db = coll.db
    state = start(db, copy)
    part = state['rows'][0]
    for found in (-1, part['quantity'] + 1, True, 'two'):
        with pytest.raises(ValueError, match='within the required quantity'):
            mutate(db, copy, 'answer', token=part['token'], found=found)
    with pytest.raises(ValueError, match='Choose a part from this copy'):
        mutate(db, copy, 'answer', token='p:9999', found=0)
    mutate(db, copy, 'answer', token=part['token'], found=0)
    coll.sql('UPDATE copy_part SET missing=0 WHERE id=?', (part['id'],))
    with pytest.raises(ValueError, match='elsewhere'):
        mutate(db, copy, 'undo')                                                    # the answer changed since: Undo refuses
    assert db.execute('SELECT count(*) FROM event_undo').fetchone()[0] == 0
    coll.sql("UPDATE copy SET archived_at='2026-10-13T00:00:00.000Z'")
    with pytest.raises(ValueError, match='no longer'):
        checker.view(db, copy)
    assert checker.choices(db) == []


def test_count_bounds_are_the_tables_own(coll, copy):
    """Invariant 10: each count on its own, 0 to the quantity (the table refuses anything else)."""
    db = coll.db
    part = db.execute('SELECT id,quantity FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0', (copy,)).fetchone()
    for column in ('missing', 'damaged'):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f'UPDATE copy_part SET {column}=? WHERE id=?', (part['quantity'] + 1, part['id']))
    db.execute('UPDATE copy_part SET missing=?, damaged=? WHERE id=?', (part['quantity'], part['quantity'], part['id']))   # not summed: each on its own
    db.rollback()


def test_a_stale_session_cannot_undo_a_new_check(coll, copy):
    db = coll.db
    start(db, copy)
    old = checker.session(db, copy)['id']
    mutate(db, copy, 'finish', checked=False)
    current = start(db, copy)['session']['id']
    assert current != old
    with pytest.raises(ValueError, match='check changed'):
        checker.write(db, copy, dict(action='undo', session=old, operation='stale-undo'))
    assert checker.session(db, copy)['id'] == current
    with pytest.raises(ValueError, match='check changed'):
        checker.write(db, copy, dict(action='restart', session='stale', operation='stale-restart'))


@pytest.mark.parametrize('initial', [False, True])
@pytest.mark.parametrize('finish_checked', [False, True])
def test_finish_flag_receipt_and_undo(coll, copy, initial, finish_checked):
    db = coll.db
    state = start(db, copy)
    flag = checker.checked_flag(db)
    assert flag and db.execute('SELECT system FROM flag WHERE id=?', (flag,)).fetchone()[0] == 1
    if initial:
        coll.tag('copy', copy, flag)
    answer_all(db, copy, state)
    before = checker.snapshot(db, copy)
    done = mutate(db, copy, 'finish', checked=finish_checked)
    assert done['copy']['set_checked'] is finish_checked
    event = db.execute('SELECT old_value, new_value FROM event WHERE id=?', (checker.session(db, copy)['undo'][-1],)).fetchone()
    assert (json.loads(event[0])['checked_flag'] is True) is initial and (json.loads(event[1])['checked_flag'] is True) is finish_checked
    mutate(db, copy, 'undo')
    assert checker.snapshot(db, copy) == before and checker.checked(db, copy) is initial
    assert db.execute("SELECT count(*) FROM flag WHERE kind='status' AND name='Set is checked'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='flag' AND entity_id=?", (flag,)).fetchone()[0] == 1       # created once, audited once


def test_the_flag_is_made_on_the_first_write_not_on_a_read(coll, copy):
    db = coll.db
    checker.view(db, copy)
    assert checker.checked_flag(db) is None and db.execute('SELECT count(*) FROM flag').fetchone()[0] == 0
    db.execute("CREATE TRIGGER reject_creation BEFORE INSERT ON event WHEN new.entity_kind='part_check' BEGIN SELECT RAISE(ABORT,'no'); END")
    with pytest.raises(sqlite3.IntegrityError):
        mutate(db, copy, 'start')
    assert checker.checked_flag(db) is None and checker.session(db, copy) is None        # the flag rolled back with the receipt


def test_a_figure_is_checked_by_its_line_and_counts_on_the_figure_not_the_set(coll, copy):
    db = coll.db
    figure = db.execute('SELECT id FROM copy_figure WHERE copy_id=?', (copy,)).fetchone()[0]
    view = checker.figure_view(db, copy, figure)
    assert view['figure']['id'] == figure and len(view['rows']) == 4 and {r['kind'] for r in view['rows']} == {'part'}
    mutate(db, copy, 'start', figure=figure, order='largest')
    state = checker.figure_view(db, copy, figure)
    assert state['session']['sort'] == 'largest' and len(state['session']['order']) == 4
    head = state['rows'][0]
    before = db.execute('SELECT completeness, updated_at FROM copy WHERE id=?', (copy,)).fetchone()
    mutate(db, copy, 'answer', figure=figure, token=head['token'], found=0)
    assert db.execute('SELECT missing FROM copy_part WHERE id=?', (head['id'],)).fetchone()[0] == head['quantity']
    assert tuple(db.execute('SELECT completeness, updated_at FROM copy WHERE id=?', (copy,)).fetchone()) == tuple(before)    # the set is unchanged
    assert not checker.checked(db, copy) and checker.session(db, copy) is None                                           # the set has its own session
    done = mutate(db, copy, 'finish', figure=figure)
    assert done['session']['finished']
    assert db.execute("SELECT entity_id FROM event WHERE entity_kind='part_check' ORDER BY id DESC LIMIT 1").fetchone()[0] == f'{copy}:fig:{figure}'
    with pytest.raises(ValueError, match='not in this copy'):
        checker.figure_view(db, copy, 999)
    mutate(db, copy, 'undo', figure=figure)
    assert not checker.session(db, copy, figure)['finished']


def test_a_retired_line_leaves_the_check_and_a_returning_line_keeps_its_answer(coll, copy):
    """Design 4.4: an in-place switch retires a line and re-activates the same row; a check keeps its answers by line id."""
    db = coll.db
    state = start(db, copy)
    first = state['session']['order'][0]
    mutate(db, copy, 'answer', token=first, found=1)
    coll.sql('UPDATE copy_part SET retired_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', int(first[2:])))
    view = checker.view(db, copy)
    assert first not in view['session']['order'] and first not in view['session']['answers'] and view['session']['cursor'] == 0
    assert all(r['token'] != first for r in view['rows'])
    coll.sql('UPDATE copy_part SET retired_at=NULL WHERE id=?', (int(first[2:]),))
    view = checker.view(db, copy)
    assert first in view['session']['order'] and view['session']['answers'][first] == 'answered'


def test_a_switched_copy_keeps_its_session_and_walks_the_new_lines(coll):
    """The real in-place switch (design 4.4): lines keep their ids, so a check in progress keeps its answers; a retired line leaves the walk and
    a line the new list added joins it, so the check can still be finished."""
    db = coll.db
    copy = coll.add_copy('2070-1', version=1)
    state = start(db, copy)
    first, second, third = state['session']['order']
    for token in (first, second):
        mutate(db, copy, 'answer', token=token, found=0)
    copies.switch_part_list(db, copy, {'source': 'rebrickable', 'version': 2}, via='cli')
    db.commit()
    live = {f"p:{r[0]}" for r in db.execute('SELECT id FROM copy_part WHERE copy_id=? AND retired_at IS NULL', (copy,))}
    assert third not in live and {first, second} <= live and len(live) == 4                    # one line retired, two new
    view = checker.view(db, copy)
    assert view['session']['answers'] == {first: 'answered', second: 'answered'}
    assert view['session']['order'][:2] == [first, second] and set(view['session']['order']) == live
    new = [t for t in view['session']['order'] if t not in (first, second)]
    for token in new:
        mutate(db, copy, 'answer', token=token, found=1)
    assert mutate(db, copy, 'finish', checked=False)['session']['finished']
    figure_free = [r for r in checker.rows(db, copy, decorate=False) if r['kind'] != 'spare']
    assert len(figure_free) == 4


def test_a_copy_without_spares_has_no_spare_step(coll):
    db = coll.db
    copy = coll.add_copy('2070-1')
    state = start(db, copy)
    assert 'spare' not in {r['kind'] for r in state['rows']}
    with pytest.raises(ValueError, match='no spare parts'):
        mutate(db, copy, 'spares', include=False)


def test_normalise_drops_spare_answers_and_misses_until_yes():
    s = dict(order=['p:1', 'p:2'], cursor=2, answers={'p:1': 'answered', 'p:2': 'answered'}, misses=['p:2', 'p:1'], spares=None)
    kinds = {'p:1': 'part', 'p:2': 'spare', 'p:9': 'part'}
    assert checker.normalise(dict(s), kinds) == dict(order=['p:1', 'p:9'], cursor=1, answers={'p:1': 'answered'}, misses=['p:1'], spares=None)     # p:9 is new
    kept = checker.normalise(dict(s, spares='yes'), kinds)
    assert kept['order'] == ['p:1', 'p:2', 'p:9'] and kept['misses'] == ['p:2', 'p:1']


def test_a_big_copy_saves_and_chooses_in_a_fixed_number_of_queries(coll, copy, monkeypatch):
    db = coll.db
    red = coll.colour('4')
    for n in range(150):
        item = coll.local('part', f'Bulk part {n}', born_key=f'bulk{n}')
        coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,is_spare,quantity) VALUES(?,?,?,0,1)', (copy, item, red))
    total = db.execute('SELECT count(*) FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND is_spare=0', (copy,)).fetchone()[0]
    assert total == 152
    import brickwork.core.collection as collection
    calls, original = [], collection.decorate
    monkeypatch.setattr(collection, 'decorate', lambda *args, **kw: calls.append(len(args[1])) or original(*args, **kw))
    started = checker.write(db, copy, dict(action='start', operation='large-start'))
    assert started['partial'] and sum(started['progress'].values()) == total + 1 and started['rows'] == []
    assert checker.write(db, copy, dict(action='start', operation='large-start'))['partial']       # a retry
    token = checker.session(db, copy)['order'][0]
    payload = dict(action='answer', token=token, found=0, operation='large-save', session=started['session']['id'])
    for _ in range(2):
        result = checker.write(db, copy, payload)
        assert len(result['rows']) == 1 and 'image' not in result['rows'][0]
    assert max(calls, default=0) <= 1                                                   # only the answered row is ever decorated
    statements = []
    db.set_trace_callback(statements.append)
    checker.choices(db)
    db.set_trace_callback(None)
    assert len(statements) < 20


def test_the_chooser_counts_progress_by_line_and_sorts_in_progress_first(coll, copy):
    db = coll.db
    other = coll.add_copy('1000-1')
    state = start(db, copy)
    required = [r for r in state['rows'] if r['kind'] != 'spare']
    mutate(db, copy, 'answer', token=required[0]['token'], found=required[0]['quantity'])
    mutate(db, copy, 'skip', token=required[1]['token'])
    choices = checker.choices(db)
    assert [c['copy']['id'] for c in choices] == [copy, other]
    active = choices[0]
    assert (active['completed'], active['total'], active['entries'], active['parts']) == (1, 3, 4, 2)
    assert active['copy']['label'] == 'Set 1' and choices[1]['copy']['label'] == 'Set 2' and active['copy']['set_no'] == '1000-1'
    coll.sql("UPDATE copy_figure SET retired_at='2026-10-27T00:00:00.000Z' WHERE copy_id=?", (copy,))      # a retired line is no line
    assert [(c['completed'], c['total']) for c in checker.choices(db) if c['copy']['id'] == copy] == [(1, 2)]


def test_undo_is_registered_for_a_check_event_and_a_second_undo_does_nothing(coll, copy):
    db = coll.db
    state = start(db, copy)
    mutate(db, copy, 'answer', token=state['session']['order'][0], found=0)
    event = checker.session(db, copy)['undo'][-1]
    assert ('part_check', 'save') in undo.REGISTRY
    assert undo.undo_event(db, event)['already_undone'] is False
    assert undo.undo_event(db, event)['already_undone'] is True


# ---------- the screens ----------

def page(client, route):
    response = client.get(route)
    assert response.status_code == 200, response.text[-400:]
    return BeautifulSoup(response.text, 'html.parser')


def json_state(soup):
    return json.loads(soup.select_one('script[data-check-state]').text)


def test_the_chooser_and_the_copy_landing(coll, copy, client):
    token = csrf(client)
    soup = page(client, '/workbench/check-parts')
    root = soup.select_one('#bw-check-choices')
    assert root.h1.text == '0 checks in progress, 1 set not checked'
    row = root.select_one('[data-list-row]')
    assert row['href'] == f'/workbench/check-parts/{copy}' and row['data-number'] == '1000-1' and row['data-state'] == 'unchecked'
    assert row.select_one('.check-choice-meta>.mono').text == '2 parts'
    assert 'Start a check' in client.get(f'/workbench/check-parts/{copy}').text
    started = client.post(f'/workbench/check-parts/{copy}', data={'csrf_token': token, 'action': 'start', 'order': 'largest'})
    assert started.status_code == 302 and started.location.endswith(f'/{copy}?run=1')
    landing = page(client, f'/workbench/check-parts/{copy}')
    box = landing.select_one('#bw-checker')
    assert box['data-landing'] == 'true' and box.select_one('[data-start] [data-resume]')['href'].endswith('?run=1')
    assert box.select_one('[data-check-body]').has_attr('hidden') and 'Minifigures follow the required parts.' in box.text
    assert [i['value'] for i in box.select('input[name=order]')] == ['inventory', 'colour', 'largest']
    assert box.select_one('input[name=order][checked]')['value'] == 'largest'
    assert box.select_one('.check-saved').text.startswith('Saved ') and '0 of 3 entries done' in box.select_one('.check-saved').text
    assert box.find('a', string='Back to the set')['href'].endswith(f'?copy={copy}')
    assert box['data-endpoint'] == f'/workbench/check-parts/{copy}'
    progress = page(client, '/workbench/check-parts')
    assert progress.select_one('#bw-check-choices h1').text == '1 check in progress, 0 sets not checked'
    assert progress.select_one('[data-copy-section="progress"] [role=img]')['aria-label'] == '0 of 3 checked'
    running = page(client, f'/workbench/check-parts/{copy}?run=1')
    assert running.select_one('#bw-checker')['data-landing'] == 'false' and not running.select_one('[data-start]')
    assert running.select_one('[data-copy-status]').has_attr('hidden')
    assert json_state(running)['session']['sort'] == 'largest'
    assert json_state(running)['copy']['condition'] == 'used'


def test_the_script_posts_answers_and_gets_the_changed_rows_back(coll, copy, client):
    token = csrf(client)
    url = f'/workbench/check-parts/{copy}'
    client.post(url, data={'csrf_token': token, 'action': 'start'})
    state = json_state(page(client, url + '?run=1'))
    row = state['rows'][0]
    payload = dict(action='answer', operation='api-answer', session=state['session']['id'], token=row['token'], found=0)
    assert client.post(url, json={**payload, 'csrf_token': token}, headers={'Origin': 'https://other.invalid'}).status_code == 403
    assert client.post(url, json={**payload, 'csrf_token': 'wrong'}).status_code == 400
    assert coll.db.execute('SELECT count(*) FROM event WHERE entity_kind=?', ('part_check',)).fetchone()[0] == 1          # only the start so far
    done = client.post(url, json={**payload, 'csrf_token': token})
    assert done.status_code == 200 and done.headers['Cache-Control'] == 'no-store'
    assert done.json['state']['session']['misses'] == [row['token']] and [r['token'] for r in done.json['state']['rows']] == [row['token']]
    undone = client.post(url, json=dict(action='undo', operation='api-undo', session=state['session']['id'], csrf_token=token))
    assert undone.status_code == 200 and undone.json['state']['rows'][0]['missing'] == 0
    failed = client.post(url, json=dict(action='answer', operation='api-bad', session='stale', token=row['token'], found=0, csrf_token=token))
    assert failed.status_code == 409 and 'changed' in failed.json['error']
    assert client.get('/workbench/check-parts/absent').status_code == 404
    assert client.post(url, data={'csrf_token': token, 'action': 'answer'}).status_code == 400            # a plain form may only start or restart


def test_a_person_who_is_not_logged_in_is_sent_to_log_in(coll, copy, app4):
    anonymous = app4.test_client()
    assert anonymous.get('/workbench/check-parts').status_code == 302
    assert anonymous.post(f'/workbench/check-parts/{copy}', json={}).status_code == 302


def test_the_figure_screens_and_their_routes(coll, copy, client):
    token = csrf(client)
    figure = coll.db.execute('SELECT id FROM copy_figure WHERE copy_id=?', (copy,)).fetchone()[0]
    url = f'/workbench/check-parts/{copy}/figure/{figure}'
    html = client.get(url)
    assert html.status_code == 200 and 'Check figure parts' in html.text
    assert client.get(f'/workbench/check-parts/{copy}/figure/999').status_code == 404
    assert client.get(f'/workbench/check-parts/{copy}/figure/x').status_code == 404
    started = client.post(url, data={'csrf_token': token, 'action': 'start'})
    assert started.status_code == 302 and started.location.endswith(url)
    box = page(client, url).select_one('#bw-checker')
    assert box['data-endpoint'] == url and box['data-done-url'] == f'/collection/item/{coll.item("sets", "1000-1")}?copy={copy}&inventory=figures'
    set_page = page(client, f'/workbench/check-parts/{copy}')
    assert set_page.select_one('#bw-checker')['data-figure-url'] == f'/workbench/check-parts/{copy}/figure/0'
    assert [r['id'] for r in json_state(page(client, f'/workbench/check-parts/{copy}'))['rows'] if r['kind'] == 'figure'] == [figure]


def test_saved_time_is_optional_on_the_start_card(coll, copy, client, monkeypatch):
    db = coll.db
    start(db, copy)
    state = checker.view(db, copy)
    for saved_at, expected in ((None, None), ('2020-10-16T14:20:00.000Z', '16 Oct, 14:20')):
        monkeypatch.setattr(checker, 'view', lambda *args, state=dict(state, saved_at=saved_at): state)
        text = page(client, f'/workbench/check-parts/{copy}').select_one('.check-saved').text
        assert (f'Saved {expected}' in text) if expected else ('Saved' not in text)


def test_there_is_a_message_when_no_copies_are_left(coll, copy, client):
    coll.sql("UPDATE copy SET archived_at='2026-10-16T00:00:00.000Z'")
    soup = page(client, '/workbench/check-parts')
    assert 'No copies to check yet.' in soup.select_one('main').text and not soup.select('[data-list-row]')


def test_the_checked_status_decides_the_chooser_section(coll, copy, client):
    db = coll.db
    state = start(db, copy)
    answer_all(db, copy, state)
    mutate(db, copy, 'finish', checked=True)
    soup = page(client, '/workbench/check-parts')
    row = soup.select_one('[data-list-row]')
    assert row['data-checked'] == 'true' and row['data-state'] == 'checked' and row.has_attr('hidden')
    assert soup.select_one('[data-filter] option[selected]')['value'] == 'unchecked'
    assert soup.select_one('[data-check-sort] option')['value'] == 'largest'
    assert soup.select_one('[data-check-all-fallback]') is not None


def test_checker_runtime():
    import shutil
    import subprocess
    subprocess.run([shutil.which('node'), str(Path(__file__).with_name('toni_bw_checker_runtime.cjs'))], check=True, capture_output=True, text=True)


# ---------- the style sheet's contracts (files only) ----------

def test_chooser_compact_styles():
    css = (ROOT / 'static/web/toni/bw-checker.css').read_text()
    assert '#bw-check-choices .check-copy .check-picture { width:56px;height:56px;' in css
    assert '#bw-check-choices .check-copy>div:nth-child(2) { min-width:0; }' in css
    assert 'border-top:.5px solid var(--tw-divider);border-radius:0;min-height:89px' in css
    assert '[data-status="complete"]' in css and '[data-status="incomplete"]' in css and '[data-status="sealed"]' in css
    shared = (ROOT / 'static/web/toni/bw-collection.css').read_text()
    assert ':is(#bw-collection,#bw-planning,#bw-check-choices) .bc-toolbar { display:grid;grid-template-columns:minmax(0,1fr) 44px 44px;' in shared


def test_chooser_phone_status_stacks_below_full_identity():
    import re
    css = (ROOT / 'static/web/toni/bw-checker.css').read_text()
    phone = css.split('@media(width < 480px) {', 1)[1].rsplit('}', 1)[0]
    assert '#bw-check-choices .check-copy { flex-wrap:wrap; }' in phone
    assert '#bw-check-choices .check-copy>div:nth-child(2) { flex:1 1 calc(100% - 68px);text-wrap:balance; }' in phone
    assert '#bw-check-choices .check-copy>.check-choice-meta { flex-basis:calc(100% - 68px);margin-left:68px;text-align:left;justify-items:start; }' in phone
    for rule in re.findall(r'[^{}]*>span\.mono\s*\{([^{}]*)\}', css):
        assert not re.search(r'white-space\s*:\s*nowrap|overflow\s*:\s*hidden|text-overflow\s*:\s*ellipsis', rule)
    assert not re.search(r'\border\s*:|display\s*:\s*contents', phone)
