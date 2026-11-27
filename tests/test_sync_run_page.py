"""#685 slice 2: the run page while a run is a job: queued and applying (frame 94), sending with Stop (95), interrupted with Send again (96)."""
import json
import re

from bs4 import BeautifulSoup
import pytest

from brickwork.core import sync
from brickwork.core.sync import run as sync_run
from brickwork.core.sync import run_job
from werkzeug.datastructures import MultiDict

from tests.app4 import app4, client  # noqa: F401
from tests.test_sync_rebrickable_page import apply_run, connected, db_of, pair, remote, soup, start  # noqa: F401
from tests.test_sync_run_job import form_for, three_sends  # noqa: F401
from brickwork.core.sync import lost_parts_send

@pytest.fixture(autouse=True)
def _lost_parts_send_unlocked(monkeypatch):
    """The send is locked for now (#469); these tests cover the code behind the lock. `test_lost_parts_send_lock.py` covers the lock."""
    monkeypatch.setattr(lost_parts_send, 'SEND_LOCKED', False)


def page_of(client, run_id):
    return client.get(f'/workbench/sync/rebrickable/run/{run_id}/progress')


def text(node):
    return re.sub(r'\s+', ' ', node.get_text(' ', strip=True))


def test_applying_a_run_queues_a_job_and_the_run_page_says_so(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        data = dict(form_for(db, run_id).items(multi=True))
    posted = client.post(f'/workbench/sync/rebrickable/run/{run_id}/run', data={'csrf_token': _csrf(client), **data})
    assert posted.location.endswith('/progress')                        # queued, nothing run yet: the page follows the job
    page = soup(client.get(posted.location))
    live = page.select_one('[data-sr-live]')
    assert live.has_attr('data-sr-poll')
    assert 'Waiting to start' in text(live)
    assert 'Stop after this one' in text(live)
    assert page.select_one('.sr-now').get_text(' ', strip=True).startswith('5 Run')


def _csrf(client):
    client.get('/collection/sets')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def test_the_pull_shows_as_one_step_without_a_count_and_the_sends_wait_for_it(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id))
    page = soup(page_of(client, run_id))
    pull = page.select_one('[data-rb-pull]')
    assert pull and 'Into Brick Work' in text(pull) and 'Waiting to start' in text(pull)
    with db_of(pair) as db:
        db.execute("UPDATE job SET state='running'")
        db.commit()
    assert 'no count for this part' in text(soup(page_of(client, run_id)).select_one('[data-rb-pull]'))
    assert 'Stop after this one' in text(page.select_one('[data-sr-live]'))


def test_sending_shows_n_of_m_the_budget_and_a_stop_that_is_remembered(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute("UPDATE job_step SET state='done', count=total WHERE job_id=? AND name IN ('pull', 'parts')", (job_id,))
        db.execute("UPDATE job_step SET state='running', count=1 WHERE job_id=? AND name='send'", (job_id,))
        db.commit()
        total = db.execute("SELECT total FROM job_step WHERE job_id=? AND name='send'", (job_id,)).fetchone()[0]
    page = soup(page_of(client, run_id))
    send = page.select_one('[data-rb-send]')
    assert f'Sending 1 of {total}' in text(send) and 'budget today' in text(send) and send.select_one('[role=progressbar]')['aria-valuenow'] == '1'
    assert 'Pull applied' in text(page.select_one('[data-rb-pull]'))
    button = send.select_one('form[action$="/stop"] button')
    assert text(button) == 'Stop after this one' and not button.has_attr('disabled')
    csrf = _csrf(client)
    assert client.post(f'/workbench/sync/rebrickable/run/{run_id}/stop', data={'csrf_token': csrf}).location.endswith('/progress')
    stopped = soup(page_of(client, run_id)).select_one('[data-rb-send] form[action$="/stop"] button')
    assert text(stopped) == 'Stopping after this one' and stopped.has_attr('disabled')
    assert client.post(f'/workbench/sync/rebrickable/run/{run_id}/stop').status_code in (400, 403)      # a write needs the token


def test_a_run_that_is_done_leaves_the_run_page_for_the_result(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    response = apply_run(client, _csrf(client), run_id)
    assert response.status_code in (200, 302)
    with db_of(pair) as db:
        run_job.drain(db)
    assert page_of(client, run_id).location.endswith('/result')


def test_an_interrupted_send_shows_what_went_out_and_offers_send_again(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    _interrupt(pair, run_id)
    page = soup(page_of(client, run_id))
    send = page.select_one('[data-rb-send]')
    assert 'Interrupted' in text(send) and 'not known' in text(send) and 'never repeated by itself' in text(send)
    assert not page.select_one('[data-sr-live]').has_attr('data-sr-poll')
    assert text(send.select_one('form[action$="/retry"] button')) == 'Send again'
    assert len(send.select('.sr-prow')) == len(keys)
    assert [text(t) for t in send.select('.sr-prow .sr-tag')][0] == 'Not known'


def test_a_run_of_the_other_site_or_one_that_never_started_opens_nothing(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    assert page_of(client, run_id).location.endswith('/preview')                       # no job yet
    assert client.get(f'/workbench/sync/brickset/run/{run_id}/progress').status_code in (302, 404)


def _interrupt(pair, run_id, in_flight=None):
    """A run whose send stage a restart cut off: the stage was `started`, the job's owner is dead; the drainer settles it."""
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'send': {'status': 'started'}}
        run.setdefault('job_progress', {})['in_flight'] = in_flight or next(k for k, v in run['job_form']['chosen'].items() if v in ('send', 'remove'))     # the worker wrote it before its call
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        run_job.drain(db)
        return [r['key'] for r in sync_run.load(db, run_id)[0]['stages']['send']['results']], [r['result'] for r in sync_run.load(db, run_id)[0]['stages']['send']['results']]


def test_sends_go_in_the_order_the_interrupted_view_relies_on(three_sends, monkeypatch):  # noqa: F811
    from brickwork.core.sync import adapters
    pair, run_id, keys = three_sends
    seen, real = [], adapters.RebrickableUser.send

    def record(self, row, link, state):
        seen.append(row['key'])
        return real(self, row, link, state)
    monkeypatch.setattr(adapters.RebrickableUser, 'send', record)
    with db_of(pair) as db:
        form = form_for(db, run_id)
        wanted = [k.removeprefix('choice:') for k, v in form.items(multi=True) if v in ('send', 'remove')]
        run_job.queue(db, run_id, form)
        run_job.drain(db)
    assert seen == wanted and len(seen) == len(keys)        # the first row with no result after a restart is the one that was in flight


def test_the_row_in_flight_is_unknown_and_the_rows_after_it_did_not_go(three_sends):  # noqa: F811
    pair, run_id, keys = three_sends
    order, results = _interrupt(pair, run_id)
    assert results == ['unknown'] + ['failed'] * (len(keys) - 1) and set(order) == set(keys)


def test_send_again_leaves_the_unknown_row_unless_it_is_chosen(three_sends, client, monkeypatch):  # noqa: F811
    from brickwork.core.sync import adapters
    pair, run_id, keys = three_sends
    order, results = _interrupt(pair, run_id)
    sent, real = [], adapters.RebrickableUser.send

    def record(self, row, link, state):
        sent.append(row['key'])
        return real(self, row, link, state)
    monkeypatch.setattr(adapters.RebrickableUser, 'send', record)
    page = soup(page_of(client, run_id))
    box = page.select_one('input[name=also]')
    assert box and box['value'] == order[0] and not box.has_attr('checked') and text(box.parent) == 'Send it too'
    csrf = _csrf(client)
    url = f'/workbench/sync/rebrickable/run/{run_id}/retry'
    client.post(url, data={'csrf_token': csrf})
    assert sent == order[1:]                                       # only the rows that did not go
    with db_of(pair) as db:
        left = {r['key']: r['result'] for r in sync_run.load(db, run_id)[0]['stages']['send']['results']}
        assert left[order[0]] == 'unknown' and {v for k, v in left.items() if k != order[0]} == {'sent'}
    client.post(url, data={'csrf_token': csrf})                    # nothing but the unknown row is left: the page says to choose it
    assert sent == order[1:]
    client.post(url, data={'csrf_token': csrf, 'also': order[0]})
    assert sent == order[1:] + [order[0]]


def test_last_runs_shows_an_interrupted_run_with_undo_for_its_pull_and_a_way_back(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    _interrupt(pair, run_id)
    site = soup(client.get('/workbench/sync/rebrickable'))
    runs = [text(r) for r in site.select('[data-rb-runs] .sr-run')]
    assert any('Interrupted' in r for r in runs)
    assert site.select_one('[data-rb-runs] a[href$="/progress"]')['href'].endswith(f'/run/{run_id}/progress')
    assert sum(1 for r in runs if 'changes sent' in r or 'change sent' in r) <= 1      # one record for the send, not one per call


def test_send_again_without_the_unknown_row_keeps_the_run_interrupted_with_its_choice(three_sends, client, monkeypatch):  # noqa: F811
    pair, run_id, keys = three_sends
    order, results = _interrupt(pair, run_id)
    posted = client.post(f'/workbench/sync/rebrickable/run/{run_id}/retry', data={'csrf_token': _csrf(client)})
    assert posted.location.endswith('/progress')                    # not the result: the choice for the row is on the run page
    page = soup(client.get(posted.location))
    assert page.select_one('input[name=also]') and 'Interrupted' in text(page.select_one('[data-rb-send]'))
    site = soup(client.get('/workbench/sync/rebrickable'))
    assert any('Interrupted' in text(r) for r in site.select('[data-rb-runs] .sr-run'))      # the log still says so
    posted = client.post(f'/workbench/sync/rebrickable/run/{run_id}/retry', data={'csrf_token': _csrf(client), 'also': order[0]})
    assert posted.location.endswith('/result')                      # every row is settled now


def test_a_row_a_budget_pause_left_is_still_the_one_in_flight_after_a_restart(three_sends):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        form = form_for(db, run_id)
        wanted = [k.removeprefix('choice:') for k, v in form.items(multi=True) if v in ('send', 'remove')]
        plan_id = sync_run.load(db, run_id)[1]['send']['id']
        plan = sync.load_plan(db, plan_id, 'send')
        plan['results'] = {wanted[0]: dict(result='sent', detail=None), wanted[1]: dict(result='paused', detail=None), wanted[2]: dict(result='paused', detail=None)}
        sync._store_plan(db, plan)
    order, results = _interrupt(pair, run_id, in_flight=wanted[1])
    assert dict(zip(order, results)) == {wanted[0]: 'sent', wanted[1]: 'unknown', wanted[2]: 'paused'}
    with db_of(pair) as db:       # Send again without the choice sends the rest and leaves the row in flight, whatever the send plan kept of it
        sync_run.retry_send(db, run_id)
        left = {r['key']: r['result'] for r in sync_run.load(db, run_id)[0]['stages']['send']['results']}
        assert left[wanted[1]] == 'unknown' and sync_run.load(db, run_id)[0]['stages']['send']['status'] == 'failed'


def test_the_hub_log_shows_one_row_for_a_long_send_and_keeps_the_pull_in_its_limit(three_sends):  # noqa: F811
    from brickwork.web.sync_views import _log
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        rows = _log(db, limit=2)
        assert [r['direction'] for r in rows].count('Sent') == 1 and 'Pulled' in [r['direction'] for r in rows]


def test_the_preview_of_a_run_with_a_job_opens_its_run_page(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id))
    assert client.get(f'/workbench/sync/rebrickable/run/{run_id}/preview').location.endswith('/progress')


def test_with_no_send_in_flight_no_row_is_unknown(three_sends):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'send': {'status': 'started'}}
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        run_job.drain(db)
        assert {r['result'] for r in sync_run.load(db, run_id)[0]['stages']['send']['results']} == {'failed'}      # died between calls: nothing may have gone out


def test_a_call_is_written_down_before_it_is_made(three_sends, monkeypatch):  # noqa: F811
    from brickwork.core.sync import adapters
    pair, run_id, keys = three_sends
    seen, real = [], adapters.RebrickableUser.send

    def record(self, row, link, state):
        with db_of(pair) as other:
            seen.append((row['key'], sync_run.load(other, run_id)[0]['job_progress'].get('in_flight')))
        return real(self, row, link, state)
    monkeypatch.setattr(adapters.RebrickableUser, 'send', record)
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        assert seen and all(key == flight for key, flight in seen) and sync_run.load(db, run_id)[0]['job_progress']['in_flight'] is None


def test_a_send_whose_result_was_saved_before_the_restart_stays_sent(three_sends):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run = sync_run.load(db, run_id)[0]
        first = next(k for k, v in run['job_form']['chosen'].items() if v in ('send', 'remove'))
        plan_id = sync_run.load(db, run_id)[1]['send']['id']
        plan = sync.load_plan(db, plan_id, 'send')
        plan['results'] = {first: dict(result='sent', detail=None)}                  # saved by the send, the worker died before it cleared `in_flight`
        sync._store_plan(db, plan)
    order, results = _interrupt(pair, run_id, in_flight=first)
    assert dict(zip(order, results))[first] == 'sent' and 'unknown' not in results


def test_a_pull_that_succeeded_in_part_is_not_reported_as_applied_or_as_nothing_changed(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'pull': {'status': 'done'}, 'parts': {'status': 'failed', 'message': 'x'}}
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute("INSERT INTO job_step(job_id, name, position, sources, source, state, count, total, updated_at) VALUES(?, 'parts', 5, '[\"rebrickable\"]', 'rebrickable', 'failed', 0, 2, '2026-11-25T00:00:00.000Z')", (job_id,))
        db.commit()
    pull = soup(page_of(client, run_id)).select_one('[data-rb-pull]')
    assert 'applied in part' in text(pull) and 'Nothing here changed' not in text(pull) and 'Pull applied' not in text(pull)


def test_an_interrupt_between_two_sends_says_no_send_was_cut_off(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'send': {'status': 'started'}}
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        run_job.drain(db)
    send = soup(page_of(client, run_id)).select_one('[data-rb-send]')
    assert 'No send was cut off' in text(send) and 'Send again sends every row that is not sent' in text(send) and 'Not known' not in text(send) and not send.select('input[name=also]')


def test_a_run_whose_last_send_was_saved_before_the_restart_is_not_left_interrupted(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run = sync_run.load(db, run_id)[0]
        wanted = [k for k, v in run['job_form']['chosen'].items() if v in ('send', 'remove')]
        plan_id = sync_run.load(db, run_id)[1]['send']['id']
        plan = sync.load_plan(db, plan_id, 'send')
        plan['results'] = {k: dict(result='sent', detail=None) for k in wanted}
        sync._store_plan(db, plan)
    order, results = _interrupt(pair, run_id, in_flight=wanted[-1])
    assert set(results) == {'sent'}
    with db_of(pair) as db:
        assert sync_run.load(db, run_id)[0]['stages']['send']['status'] == 'done'
        step = db.execute("SELECT s.state, s.error, s.count, s.total FROM job_step s JOIN job j ON j.id=s.job_id WHERE s.name='send' ORDER BY j.id DESC").fetchone()
        assert (step['state'], step['error']) == ('done', None) and step['count'] == step['total']
        from brickwork.web.sync_views import _log
        assert [r['state'] for r in _log(db, source='rebrickable') if r['direction'] == 'Sent'] == ['Done']
    assert page_of(client, run_id).location.endswith('/result')


def test_last_runs_keeps_an_interrupted_run_and_its_pull_until_the_pull_is_undone(three_sends):  # noqa: F811
    from brickwork.core.admin import audit
    from brickwork.core.transaction import transaction
    from brickwork.web.sync_site import _runs
    pair, run_id, keys = three_sends
    _interrupt(pair, run_id)
    with db_of(pair) as db:
        pulls = sync_run.pull_events(sync_run.load(db, run_id)[0])
        assert pulls
        for n in range(6):          # six newer sends push both rows past the five newest
            with transaction(db):
                audit(db, 'sync:rebrickable', 'send', None, dict(plan=f'later-{n}', counts={'sent': 1}))
        listed = _runs(db, 'rebrickable')
        assert [r['state'] for r in listed].count('Interrupted') == 1 and len(listed) > 5
        assert [r['event'] for r in listed if r['undoable']] and all(r['event'] in pulls for r in listed if r['undoable'])
        with transaction(db):       # a newer live pull that falls out of the five newest keeps the Undo: it never moves back to the older, listed one
            audit(db, 'sync:rebrickable', 'receipt', None, dict(source='rebrickable', counts={}, plan='newer'))
            for n in range(6):
                audit(db, 'sync:rebrickable', 'send', None, dict(plan=f'after-{n}', counts={'sent': 1}))
        assert not [r for r in _runs(db, 'rebrickable') if r['undoable']]
        sync_run.undo_run(db, pulls[0])
        listed = _runs(db, 'rebrickable')
        assert len(listed) == 5 and not [r for r in listed if r['state'] == 'Interrupted']


@pytest.mark.parametrize('choice, words', [('send', 'Tick Send it too only if Rebrickable does not show the new count'), ('remove', 'Tick Send it too only if it is still there')])
def test_the_note_says_when_to_tick_send_it_too(three_sends, client, choice, words):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        first = next(k.removeprefix('choice:') for k, v in form_for(db, run_id).items(multi=True) if v in ('send', 'remove'))
    _interrupt(pair, run_id, in_flight=first)
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        run['job_form']['chosen'][first] = choice
        sync._store_plan(db, run)
    page = text(soup(page_of(client, run_id)).select_one('main'))
    assert words in page and 'They stay done. Undo for this pull is in Last runs, where this run is listed as Interrupted.' in page
    from brickwork.core.admin import audit
    from brickwork.core.transaction import transaction
    with db_of(pair) as db:
        with transaction(db):       # a newer pull takes the Undo over: the card no longer says where this one's is
            audit(db, 'sync:rebrickable', 'receipt', None, dict(source='rebrickable', counts={}, plan='newer'))
    page = text(soup(page_of(client, run_id)).select_one('main'))
    assert 'They stay done.' in page and 'Undo for this pull is in Last runs' not in page


@pytest.mark.parametrize('unknown, words', [
    ([('send', 'Add 2 there')], 'if it is not there'),
    ([('send', 'Quantity 1 to 2')], 'if Brickset does not show the new count'),
    ([('send', 'Send 3 to Brickset')], 'if Brickset does not show the new count'),
    ([('send', 'Send built in 2019 to Brickset')], 'if Brickset does not show the new value'),
    ([('remove', 'Remove from Brickset')], 'if it is still there'),
    ([('send', 'Add 2 there'), ('remove', 'Remove from Brickset')], 'where the change did not arrive'),
    ([('send', 'Add 2 there'), ('send', 'Add 1 there')], 'where the change did not arrive'),
])
def test_send_it_when_matches_what_the_row_would_show(client, unknown, words):  # noqa: F811     the app is built first: importing the web module alone changes the route order
    from brickwork.web.sync_site import _send_it_when
    assert _send_it_when('Brickset', [(a, dict(options=[dict(id=a, label=label)])) for a, label in unknown]) == words


def test_after_the_pull_is_undone_the_interrupted_run_says_so(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    _interrupt(pair, run_id)
    with db_of(pair) as db:
        events = sync_run.pull_events(sync_run.load(db, run_id)[0])
    before = text(soup(page_of(client, run_id)))
    if not events:
        pytest.skip('this run pulled nothing')
    assert 'They stay done' in before
    client.post('/workbench/sync/rebrickable/undo', data={'csrf_token': _csrf(client), 'event': events[0]})
    after = text(soup(page_of(client, run_id)))
    assert 'This pull was undone' in after and 'They stay done' not in after


def test_with_only_the_unknown_row_left_the_note_asks_for_send_again(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    _interrupt(pair, run_id)
    assert 'then send the rest again' in text(soup(page_of(client, run_id)))
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/retry', data={'csrf_token': _csrf(client)})
    note = text(soup(page_of(client, run_id)))
    assert 'then choose Send again' in note and 'send the rest again' not in note


def test_one_of_two_pulls_undone_does_not_say_the_pull_was_undone(three_sends, client, monkeypatch):  # noqa: F811
    pair, run_id, keys = three_sends
    _interrupt(pair, run_id)
    with db_of(pair) as db:
        first = sync_run.pull_events(sync_run.load(db, run_id)[0])[0]
    monkeypatch.setattr(sync_run, 'pull_events', lambda run: [first, first + 100000])      # a second pull that is still live
    client.post('/workbench/sync/rebrickable/undo', data={'csrf_token': _csrf(client), 'event': first})
    with db_of(pair) as db:
        assert db.execute('SELECT 1 FROM event_undo WHERE event_id=?', (first,)).fetchone()
    assert 'This pull was undone' not in text(soup(page_of(client, run_id)))


def test_undo_run_finds_a_run_behind_many_newer_ones(three_sends, monkeypatch):  # noqa: F811
    from brickwork.core import undo
    from brickwork.core.admin import audit
    from brickwork.core.transaction import transaction
    pair, run_id, keys = three_sends
    undone = []
    monkeypatch.setattr(undo, 'undo_event', lambda db, event: undone.append(event))
    with db_of(pair) as db:
        with transaction(db):
            audit(db, 'sync:rebrickable', 'run', None, dict(run=run_id, events=[900001, 900002]), via='app')
            for n in range(205):
                audit(db, 'sync:rebrickable', 'run', None, dict(run=f'later-{n}', events=[]), via='app')
        assert sync_run.undo_run(db, 900001) == [900001, 900002]      # not found would give [900001] alone
    assert undone == [900002, 900001]


def test_while_the_pull_is_applied_the_run_the_pull_and_the_sends_are_three_cards_and_stop_waits(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
    queued = soup(page_of(client, run_id))
    assert not queued.select_one('[data-rb-run] button').has_attr('disabled')      # a run that has not started can be stopped
    with db_of(pair) as db:
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.commit()
    page = soup(page_of(client, run_id))
    assert text(page.select_one('[data-rb-run] h2')).startswith('Running ') and page.select_one('[data-rb-run] button').has_attr('disabled')
    assert text(page.select_one('[data-rb-pull] h2')) == 'Into Brick Work' and 'Applying the pull' in text(page.select_one('[data-rb-pull]'))
    send = page.select_one('[data-rb-send]')
    assert text(send.h2) == 'To Rebrickable' and f'0 of {len(keys)} sent' in text(send) and send.select_one('[role=progressbar]')['aria-valuenow'] == '0'


def test_send_again_that_sends_everything_leaves_no_failed_step_in_jobs(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    order, _ = _interrupt(pair, run_id)
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/retry', data={'csrf_token': _csrf(client), 'also': order[0]})
    with db_of(pair) as db:
        job_id = sync_run.load(db, run_id)[0]['job']
        assert db.execute("SELECT state, error FROM job_step WHERE job_id=? AND name='send'", (job_id,)).fetchone()[:] == ('done', None)
        assert db.execute('SELECT error FROM job WHERE id=?', (job_id,)).fetchone()[0] is None


def test_the_result_with_one_of_two_pulls_undone_still_offers_undo(three_sends, client, monkeypatch):  # noqa: F811
    pair, run_id, keys = three_sends
    apply_run(client, _csrf(client), run_id)
    with db_of(pair) as db:
        run_job.drain(db)
        run = sync_run.load(db, run_id)[0]
        first = run['applied']['events'][0]
        run['applied']['events'] = [first, first + 100000]          # a second pull that is still there
        sync._store_plan(db, run)
    client.post('/workbench/sync/rebrickable/undo', data={'csrf_token': _csrf(client), 'event': first})
    page = text(soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result')))
    assert 'Undo this run' in page and 'This run was undone' not in page


def test_a_run_where_only_lost_parts_were_cut_off_shows_in_last_runs(client, remote, pair):  # noqa: F811
    from brickwork.core.sync import lost_parts_send
    from tests.test_bw_sync_lost_parts import copy_of, raw
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]      # a listed part carries its inventory id, so the row can be ticked
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='per_part')
    key = lost_parts_send.row_key('1000-1', '3001', 4, False)
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, MultiDict([('lostsend', key)]))
        assert [s[0] for s in db.execute('SELECT name FROM job_step WHERE job_id=?', (job_id,))] == ['lost_out']
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'lost_out': {'status': 'started'}}
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        run_job.drain(db)
    runs = [text(r) for r in soup(client.get('/workbench/sync/rebrickable')).select('[data-rb-runs] .sr-run')]
    assert any('Lost Parts: ' in r and 'Interrupted' in r for r in runs), runs


@pytest.mark.parametrize('saved', [True, False])
def test_a_cut_off_lost_parts_stage_keeps_a_record_whether_or_not_every_row_was_saved(client, remote, pair, saved):  # noqa: F811
    from brickwork.core.sync import lost_parts_send
    from tests.test_bw_sync_lost_parts import copy_of, raw
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='per_part')
    key = lost_parts_send.row_key('1000-1', '3001', 4, False)
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, MultiDict([('lostsend', key)]))
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'lost_out': {'status': 'started'}}
        if saved:
            run['lost_out']['rows'][0]['outcome'] = 'sent'
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        run_job.drain(db)
    row = text(soup(client.get('/workbench/sync/rebrickable')).select_one('[data-rb-runs] .sr-run'))
    assert 'Lost Parts: ' in row and ('Interrupted' in row) is not saved, row


def test_send_again_keeps_the_job_error_while_another_stage_is_partly_failed(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    order, _ = _interrupt(pair, run_id)
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        run['stages']['lost_out'] = dict(status='partial', counts=dict(sent=0, failed=1, waiting=0))
        sync._store_plan(db, run)
        db.execute("UPDATE job SET error='Some changes were not made; see the result' WHERE id=?", (run['job'],))
        db.commit()
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/retry', data={'csrf_token': _csrf(client), 'also': order[0]})
    with db_of(pair) as db:
        assert db.execute('SELECT error FROM job WHERE id=?', (sync_run.load(db, run_id)[0]['job'],)).fetchone()[0]


def test_lost_parts_saved_before_the_restart_are_not_called_interrupted():
    run = dict(lost_out=dict(rows=[dict(key='a', outcome='sent'), dict(key='b', outcome='sent')]))
    assert run_job._interrupted(None, run, {}, dict(lostsend=['a', 'b']), 'lost_out')['status'] == 'done'
    run['lost_out']['rows'][1].pop('outcome')
    assert run_job._interrupted(None, run, {}, dict(lostsend=['a', 'b']), 'lost_out')['status'] == 'failed'


def test_a_second_send_again_repairs_a_job_the_first_one_could_not_write(three_sends, client, monkeypatch):  # noqa: F811
    pair, run_id, keys = three_sends
    order, _ = _interrupt(pair, run_id)
    real = sync_run._job_send_done
    monkeypatch.setattr(sync_run, '_job_send_done', lambda db, run: None)       # the job write is lost
    url = f'/workbench/sync/rebrickable/run/{run_id}/retry'
    client.post(url, data={'csrf_token': _csrf(client), 'also': order[0]})
    monkeypatch.setattr(sync_run, '_job_send_done', real)
    client.post(url, data={'csrf_token': _csrf(client)})
    with db_of(pair) as db:
        job_id = sync_run.load(db, run_id)[0]['job']
        assert db.execute("SELECT state FROM job_step WHERE job_id=? AND name='send'", (job_id,)).fetchone()[0] == 'done'


def _crash_on_send(monkeypatch, number):
    from brickwork.core.sync import adapters
    real, calls = adapters.RebrickableUser.send, []

    def send(self, row, link, state):
        calls.append(row['key'])
        if len(calls) == number:
            raise RuntimeError('boom')
        return real(self, row, link, state)

    monkeypatch.setattr(adapters.RebrickableUser, 'send', send)


def test_an_unexpected_error_during_a_send_does_not_say_the_server_restarted(three_sends, client, monkeypatch):  # noqa: F811
    pair, run_id, keys = three_sends
    _crash_on_send(monkeypatch, 2)
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        steps = {r['name']: r['state'] for r in db.execute('SELECT name, state FROM job_step WHERE job_id=?', (job_id,))}
        assert steps.pop('send') == 'failed' and set(steps.values()) <= {'done'}, steps
    page = text(soup(page_of(client, run_id)))
    assert 'the run failed' in page and 'restart' not in page.lower() and 'could not write down' not in page, page
    runs = [text(r) for r in soup(client.get('/workbench/sync/rebrickable')).select('[data-rb-runs] .sr-run')]
    assert any('Interrupted' in r for r in runs), runs
    with db_of(pair) as db:
        unknown = [r['key'] for r in sync_run.load(db, run_id)[0]['stages']['send']['results'] if r['result'] == 'unknown']
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/retry', data={'csrf_token': _csrf(client)})      # the Not known row stays: still interrupted
    with db_of(pair) as db:
        stage = sync_run.load(db, run_id)[0]['stages']['send']
    assert unknown and stage['cause'] == 'error'
    assert 'the run failed' in text(soup(page_of(client, run_id)))


def test_an_error_after_the_last_saved_result_leaves_the_send_done_in_jobs(three_sends, client, monkeypatch):  # noqa: F811
    pair, run_id, keys = three_sends
    real = sync_run.stage_send

    def sends_then_fails(*args, **kwargs):
        real(*args, **kwargs)
        args[1]['stages']['send'] = {'status': 'started'}      # every result is in the send plan, the stage was not yet stored as done
        sync._store_plan(args[0], args[1])
        raise RuntimeError('boom')

    monkeypatch.setattr(sync_run, 'stage_send', sends_then_fails)
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        assert sync_run.load(db, run_id)[0]['stages']['send']['status'] == 'done'
        assert db.execute("SELECT state, error FROM job_step WHERE job_id=? AND name='send'", (job_id,)).fetchone()[:] == ('done', None)
    runs = [text(r) for r in soup(client.get('/workbench/sync/rebrickable')).select('[data-rb-runs] .sr-run')]
    assert not any('Interrupted' in r for r in runs), runs


def test_send_again_that_leaves_a_row_keeps_the_pulls_on_its_record(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    _interrupt(pair, run_id)
    client.post(f'/workbench/sync/rebrickable/run/{run_id}/retry', data={'csrf_token': _csrf(client)})
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        record = json.loads(db.execute("SELECT new_value FROM event WHERE entity_kind='sync' AND field='send' ORDER BY id DESC").fetchone()[0])
    assert record['interrupted'] and record['run'] == run_id and record['pulls'] == sync_run.pull_events(run)


def test_a_read_only_viewer_of_an_interrupted_run_gets_no_buttons(three_sends, app4, client):  # noqa: F811
    pair, run_id, keys = three_sends
    _interrupt(pair, run_id)
    app4.config['BW_READ_ONLY'] = True
    try:
        page = soup(page_of(client, run_id))
    finally:
        app4.config['BW_READ_ONLY'] = False
    assert not page.select('[data-rb-send] button') and not page.select('[data-rb-send] input[name=also]')


def test_a_cut_off_lost_parts_stage_is_named_on_the_card(client, remote, pair):  # noqa: F811
    from tests.test_bw_sync_lost_parts import copy_of, raw
    csrf = connected(client, pair)
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='per_part')
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, MultiDict([('lostsend', lost_parts_send.row_key('1000-1', '3001', 4, False))]))
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'lost_out': {'status': 'started'}}
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        run_job.drain(db)
    page = text(soup(page_of(client, run_id)))
    assert 'Lost Parts were being sent when the server restarted' in page and 'No send was cut off' not in page


@pytest.mark.parametrize('copies_matching', [1, 2])
def test_the_preview_of_a_matching_collection_offers_run_and_the_result_says_what_was_recorded(client, remote, pair, copies_matching):  # noqa: F811
    from tests.app4 import Coll
    from tests.test_sync_rebrickable_page import preview_of
    remote.lists = {1: {'2070-1': 1} if copies_matching == 1 else {'2070-1': 1, '1000-2': 1}, 2: {}, 9: {}}      # the counts match what is here
    with db_of(pair) as db:
        if copies_matching == 2:
            Coll(db).add_copy('1000-2')
    csrf = connected(client, pair)
    run_id = start(client, csrf, owned_dir='into', wishlist_dir='off')
    page = preview_of(client, run_id)
    line = text(page.select_one('[data-sr-matching]'))
    assert line == ('1 row here already matches Rebrickable. Run records where it came from.' if copies_matching == 1
                    else '2 rows here already match Rebrickable. Run records where they came from.'), line
    assert page.select_one('button[data-sy-submit]').has_attr('data-sy-marks')
    with db_of(pair) as db:
        sync_run.apply(db, run_id, MultiDict())
    result = text(soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/result')))
    assert f"Last synced from recorded on {'1 row' if copies_matching == 1 else '2 rows'}." in result and 'Nothing changed here' not in result, result


@pytest.mark.parametrize('path', ['/workbench/sync', '/workbench/sync/rebrickable', '/workbench/sync/rebrickable/choose', '/workbench/sync/bricklink', '/collection/sets'])
def test_a_message_shows_once_on_every_kind_of_page(client, remote, pair, path):  # noqa: F811
    connected(client, pair)
    client.get(path)
    with client.session_transaction() as session:
        session['_flashes'] = [('success', 'Run undone.')]
    page = client.get(path, follow_redirects=True).get_data(as_text=True)
    assert page.count('Run undone.') == 1, page.count('Run undone.')


def test_last_runs_says_what_a_record_only_run_did(client, remote, pair):  # noqa: F811
    from tests.app4 import Coll
    remote.lists = {1: {'2070-1': 1, '1000-2': 1}, 2: {'1000-2': 1}, 9: {}}      # one set in two lists: two lines on one row
    with db_of(pair) as db:
        Coll(db).add_copy('1000-2')
        Coll(db).add_copy('1000-2')
    csrf = connected(client, pair)
    run_id = start(client, csrf, owned_dir='into', wishlist_dir='off')
    with db_of(pair) as db:
        sync_run.apply(db, run_id, MultiDict())
        rows = db.execute('SELECT count(DISTINCT copy_id), count(*) FROM main.synced_from').fetchone()
    assert rows[1] > rows[0] > 0, tuple(rows)
    last = text(soup(client.get('/workbench/sync/rebrickable')).select_one('[data-rb-runs] .sr-run'))
    assert f"Last synced from recorded on {rows[0]} row{'' if rows[0] == 1 else 's'}" in last and 'Nothing new' not in last, last
