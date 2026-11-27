"""#685 slice 1: a sync run as a durable `sync_run` job: queue, the drainer, per-call progress, stop, budget wait and takeover."""
from contextlib import closing
import json
import os

import pytest
from werkzeug.datastructures import MultiDict

from brickwork.core import drainer, errors, sync
from brickwork.core.connect import connect
from brickwork.core.sources.base import WaitingForBudget
from brickwork.core.sync import adapters
from brickwork.core.sync import run as sync_run
from brickwork.core.sync import run_job
from brickwork.store4 import jobs
from tests.app4 import Coll, app4, client  # noqa: F401
from tests.test_sync_rebrickable_page import connected, db_of, pair, remote, start  # noqa: F401
from brickwork.core.sync import lost_parts_send

@pytest.fixture(autouse=True)
def _lost_parts_send_unlocked(monkeypatch):
    """The send is locked for now (#469); these tests cover the code behind the lock. `test_lost_parts_send_lock.py` covers the lock."""
    monkeypatch.setattr(lost_parts_send, 'SEND_LOCKED', False)


def sends(db, run_id):
    """The keys of the rows this run could send, from the preview."""
    run, plans = sync_run.load(db, run_id)
    return [r['key'] for r in sync_run.rows(db, run, plans) if any(o['id'] == 'send' for o in r['options'])]


def form_for(db, run_id, *, send=True):
    """What the preview posts by default, with every sendable row set to send (or left on keep)."""
    run, plans = sync_run.load(db, run_id)
    fields = []
    for row in sync_run.rows(db, run, plans):
        ids = [o['id'] for o in row['options']]
        if send and 'send' in ids:
            fields.append(('choice:' + row['key'], 'send'))
        elif row['default']:
            fields.append(('choice:' + row['key'], row['default']))
    return MultiDict(fields)


@pytest.fixture
def three_sends(client, remote, pair):  # noqa: F811
    """A connected run whose preview has several rows that can be sent: a set only here and two that differ."""
    csrf = connected(client, pair)
    with db_of(pair) as db:
        for number in ('1000-4', '2070-1', '2070-1', '1000-2', '1000-2'):
            Coll(db).add_copy(number)
    run_id = start(client, csrf)
    with db_of(pair) as db:
        keys = sends(db, run_id)
    assert len(keys) >= 3, keys
    return pair, run_id, keys


def test_queue_makes_one_job_with_a_step_per_stage(three_sends, remote):
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        with pytest.raises(errors.ValidationFailed, match='Choose one of the offered changes'):
            run_job.queue(db, run_id, MultiDict([('choice:' + keys[0], 'bogus')]))
        form = form_for(db, run_id)
        job_id = run_job.queue(db, run_id, form, via='unexpected', actor='tester')
        job = db.execute('SELECT * FROM job WHERE id=?', (job_id,)).fetchone()
        assert (job['kind'], job['via'], job['actor'], job['state']) == ('sync_run', 'app', 'tester', 'queued')
        steps = {s['name']: s for s in db.execute('SELECT * FROM job_step WHERE job_id=?', (job_id,))}
        assert steps['send']['total'] == len(keys) and steps['send']['count'] == 0
        assert run_job.queue(db, run_id, form) == job_id
        assert db.execute("SELECT count(*) FROM job WHERE kind='sync_run'").fetchone()[0] == 1


def test_the_job_applies_what_run_apply_applies(client, remote, pair):  # noqa: F811
    csrf = connected(client, pair)
    with db_of(pair) as db:
        Coll(db).add_copy('1000-4')
    run_id = start(client, csrf)
    with db_of(pair) as db:
        form = form_for(db, run_id, send=False)
        job_id = run_job.queue(db, run_id, form)
        assert run_job.drain(db)
        run = sync_run.load(db, run_id)[0]
        assert run['applied'] and 'applying' not in run
        assert db.execute('SELECT state FROM job WHERE id=?', (job_id,)).fetchone()[0] == 'done'
        assert db.execute('SELECT count(*) FROM job_owner').fetchone()[0] == 0
        assert len(db.execute("SELECT 1 FROM event WHERE entity_kind='sync' AND field='run'").fetchall()) == 1
        assert run['stages']['pull']['status'] in ('done', 'none')
        events = run['applied']['events']
        assert run_job.progress(db, run_id)['state'] == 'done'
        if events:
            sync_run.undo_run(db, events[0])


def test_progress_rises_per_send_call(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    seen = []
    real = adapters.RebrickableUser.send

    def watch(self, row, link, state):
        with closing(connect(pair)) as probe:
            seen.append(run_job.progress(probe, run_id))
        return real(self, row, link, state)

    monkeypatch.setattr(adapters.RebrickableUser, 'send', watch)
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id))
        first = run_job.progress(db, run_id)
        assert first['state'] == 'queued' and first['done'] == 0 and first['requests_per_second'] is None
        run_job.drain(db)
        last = run_job.progress(db, run_id)
    sent = [s for s in seen if s['stages'] and any(st['name'] == 'send' for st in st_list(s))]
    assert [next(st['done'] for st in st_list(s) if st['name'] == 'send') for s in sent] == list(range(len(keys)))
    assert all(s['now'] for s in sent) and last['state'] == 'done' and last['done'] == last['total']


def st_list(snapshot):
    return snapshot['stages']


def test_stop_after_this_one_leaves_the_rest_unsent(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    calls = []
    real = adapters.RebrickableUser.send

    def first_then_stop(self, row, link, state):
        calls.append(row['key'])
        if len(calls) == 1:
            with closing(connect(pair)) as other:
                assert run_job.request_stop(other, run_id)
        return real(self, row, link, state)

    monkeypatch.setattr(adapters.RebrickableUser, 'send', first_then_stop)
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        run = sync_run.load(db, run_id)[0]
        job = db.execute("SELECT state, error FROM job WHERE kind='sync_run'").fetchone()
    assert len(calls) == 1
    assert run['stages']['send']['status'] == 'stopped' and run['applied']
    assert tuple(job) == ('done', 'Stopped at your request')


def test_a_stage_that_was_started_is_never_run_again_after_a_takeover_but_can_be_retried(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    real, gate = adapters.RebrickableUser.send, {'open': False}

    def guarded(self, row, link, state):
        assert gate['open'], 'a send ran again'
        return real(self, row, link, state)

    monkeypatch.setattr(adapters.RebrickableUser, 'send', guarded)
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run = sync_run.load(db, run_id)[0]
        run['stages']['send'] = {'status': 'started'}
        run.setdefault('job_progress', {})['in_flight'] = next(k for k, v in run['job_form']['chosen'].items() if v in ('send', 'remove'))
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        run_job.drain(db)
        run = sync_run.load(db, run_id)[0]
        stage = run['stages']['send']
        assert stage['status'] == 'failed' and stage['message'] == run_job.INTERRUPTED_MESSAGE and run['applied']
        assert {r['key'] for r in stage['results']} == set(sends(db, run_id)) and sorted(r['result'] for r in stage['results']) == ['failed'] * (len(stage['results']) - 1) + ['unknown']
        gate['open'] = True
        unknown = [r['key'] for r in stage['results'] if r['result'] == 'unknown']
        assert sync_run.retry_send(db, run_id)['stages']['send']['status'] == 'failed'            # the row that was in flight is left unless asked for
        retried = sync_run.retry_send(db, run_id, also=unknown)
        assert retried['stages']['send']['status'] == 'done'


def test_the_synchronous_paths_leave_a_queued_run_alone(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    monkeypatch.setattr(adapters.RebrickableUser, 'send', lambda *a, **k: pytest.fail('a send ran'))
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        assert sync_run.apply(db, run_id, form_for(db, run_id))['job'] == job_id
        with pytest.raises(errors.ValidationFailed, match='already run'):
            sync_run.save_pick(db, run_id, [])
        with pytest.raises(errors.ValidationFailed, match='still running'):
            sync_run.retry_send(db, run_id)


def test_stop_reaches_a_job_waiting_for_the_budget(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    monkeypatch.setattr(adapters.RebrickableUser, 'send', lambda *a, **k: (_ for _ in ()).throw(WaitingForBudget('rebrickable', '2099-01-01T00:00:00+00:00')))
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        assert db.execute('SELECT state FROM job WHERE id=?', (job_id,)).fetchone()[0] == 'waiting_for_budget'
        assert run_job.request_stop(db, run_id)
        run_job.drain(db)
        job = db.execute('SELECT state, error FROM job WHERE id=?', (job_id,)).fetchone()
        assert tuple(job) == ('done', 'Stopped at your request') and sync_run.load(db, run_id)[0]['applied']


def test_a_budget_wait_ends_the_job_waiting_and_a_later_drain_resumes_unsent_rows(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    real = adapters.RebrickableUser.send
    sent, mode = [], {'wait': True}

    def limited(self, row, link, state):
        if mode['wait'] and len(sent) == 1:
            raise WaitingForBudget('rebrickable', '2099-01-01T00:00:00+00:00')
        sent.append(row['key'])
        return real(self, row, link, state)

    monkeypatch.setattr(adapters.RebrickableUser, 'send', limited)
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        job = db.execute('SELECT state, error_code, retry_at FROM job WHERE id=?', (job_id,)).fetchone()
        assert job['state'] == 'waiting_for_budget' and job['error_code'] == 'budget' and job['retry_at']
        assert db.execute('SELECT count(*) FROM job_owner').fetchone()[0] == 0
        assert run_job.drain(db) == []
        db.execute("UPDATE job SET retry_at='2000-01-01T00:00:00.000Z' WHERE id=?", (job_id,))
        db.commit()
        mode['wait'] = False
        run_job.drain(db)
        assert db.execute('SELECT state FROM job WHERE id=?', (job_id,)).fetchone()[0] == 'done'
    assert sorted(sent) == sorted(set(sent)) and len(sent) == len(keys)


def test_the_embedded_drainer_runs_a_queued_run_and_the_job_body_names_a_dead_owner(three_sends, client):  # noqa: F811
    pair, run_id, keys = three_sends
    from brickwork.api2 import jobs as api_jobs
    with client.application.app_context(), db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        body = api_jobs.job_body(db, job_id)
        assert body['kind'] == 'sync_run' and body['interrupted'] is True
    drainer.drain_once(str(pair))
    with client.application.app_context(), db_of(pair) as db:
        assert db.execute('SELECT state FROM job WHERE id=?', (job_id,)).fetchone()[0] == 'done'
        assert api_jobs.job_body(db, job_id)['interrupted'] is False


def test_the_plan_does_not_expire_while_the_job_works(three_sends, monkeypatch):
    from datetime import datetime, timedelta, timezone
    pair, run_id, keys = three_sends
    monkeypatch.setattr(sync, 'PLAN_TTL', timedelta(hours=1))
    old = (datetime.now(timezone.utc) - timedelta(minutes=50)).isoformat()
    with db_of(pair) as db:
        run = sync_run.load(db, run_id)[0]
        run['created_at'] = old
        sync._store_plan(db, run)
        run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        assert sync_run.load(db, run_id)[0]['created_at'] > old


def test_stop_on_a_waiting_job_keeps_the_rows_for_retry(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    real, state = adapters.RebrickableUser.send, {'sent': 0, 'mode': 'wait'}

    def send(self, row, link, st):
        if state['sent'] >= 1 and state['mode'] == 'wait':
            raise WaitingForBudget('rebrickable', '2099-01-01T00:00:00+00:00')
        state['sent'] += 1
        return real(self, row, link, st)

    monkeypatch.setattr(adapters.RebrickableUser, 'send', send)
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        assert run_job.request_stop(db, run_id)
        run_job.drain(db)
        stage = sync_run.load(db, run_id)[0]['stages']['send']
        assert stage['status'] == 'stopped' and len(stage['results']) == len(keys)
        state['mode'] = 'go'
        state['sent'] = 0
        assert sync_run.retry_send(db, run_id)['stages']['send']['status'] == 'done'


def test_an_unexpected_error_fails_the_job_and_the_run_still_shows_what_happened(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    real, state = adapters.RebrickableUser.send, {'n': 0, 'crash': True}

    def send(self, row, link, st):
        state['n'] += 1
        if state['n'] == 2 and state['crash']:
            raise RuntimeError('boom')
        return real(self, row, link, st)

    monkeypatch.setattr(adapters.RebrickableUser, 'send', send)
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        job = db.execute('SELECT state, error_code FROM job WHERE id=?', (job_id,)).fetchone()
        assert tuple(job) == ('failed', 'source_error')
        run = sync_run.load(db, run_id)[0]
        assert run['applied'] and 'applying' not in run and run['stages']['send']['status'] == 'failed'
        assert db.execute("SELECT count(*) FROM event WHERE entity_kind='sync' AND field='run'").fetchone()[0] == 1       # undo finds the run
        state['crash'] = False
        unknown = [r['key'] for r in run['stages']['send']['results'] if r['result'] == 'unknown']
        assert sync_run.retry_send(db, run_id, also=unknown)['stages']['send']['status'] == 'done'



def test_the_job_sends_lost_parts_out_one_call_with_one_audit_entry(client, remote, pair):  # noqa: F811
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
        assert [s['name'] for s in db.execute('SELECT name FROM job_step WHERE job_id=?', (job_id,))] == ['lost_out']
        run_job.drain(db)
        stage = sync_run.load(db, run_id)[0]['stages']['lost_out']
        assert stage['status'] == 'done' and stage['counts'] == dict(sent=1, failed=0, waiting=0)
        step = db.execute('SELECT count, total, state FROM job_step WHERE job_id=?', (job_id,)).fetchone()
        assert tuple(step) == (1, 1, 'done')
        assert len(db.execute("SELECT 1 FROM event WHERE entity_kind='sync' AND field='send'").fetchall()) == 1
    assert [(m, d) for m, p, d in remote.lost_writes] == [('DELETE', ''), ('POST', 'inv_part_id=1&lost_quantity=3')]


def test_a_run_that_never_began_is_released_when_the_job_fails_at_once(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    monkeypatch.setattr(run_job, '_run_one', lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        assert db.execute('SELECT state FROM job WHERE id=?', (job_id,)).fetchone()[0] == 'failed'
        assert {r[0] for r in db.execute('SELECT state FROM job_step WHERE job_id=?', (job_id,))} == {'failed'}
        run = sync_run.load(db, run_id)[0]
        assert not run.get('applied') and not run.get('job') and 'applying' not in run
        assert 'write_failed' not in run      # nothing ran: the next try of this run carries no warning over
        assert run_job.queue(db, run_id, form_for(db, run_id)) != job_id


def test_a_failing_send_unit_keeps_the_rows_the_plan_holds(three_sends, monkeypatch):
    import sqlite3
    pair, run_id, keys = three_sends
    real, state = adapters.RebrickableUser.send, {'n': 0}

    def send(self, row, link, st):
        state['n'] += 1
        if state['n'] == 2:
            raise sqlite3.OperationalError('database is locked')
        return real(self, row, link, st)

    monkeypatch.setattr(adapters.RebrickableUser, 'send', send)
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        stage = sync_run.load(db, run_id)[0]['stages']['send']
        assert stage['status'] == 'failed' and len(stage['results']) == len(keys)
        assert stage['counts'].get('failed') and sync_run.retry_send(db, run_id)['stages']['send']['status'] == 'done'


@pytest.mark.parametrize('by_job', [True, False])
def test_a_run_with_nothing_to_add_still_marks_the_rows_that_match(client, remote, pair, by_job):  # noqa: F811
    """#531: the first run after the upgrade, when the copies here already match the site."""
    csrf = connected(client, pair)
    first = start(client, csrf, wishlist_dir='off', owned_dir='into')
    with db_of(pair) as db:
        sync_run.apply(db, first, form_for(db, first, send=False))        # now the copies here match
        db.execute('DELETE FROM main.synced_from')
        db.commit()
    run_id = start(client, csrf, wishlist_dir='off', owned_dir='into')
    nothing = MultiDict()
    with db_of(pair) as db:
        copies = db.execute('SELECT count(*) FROM main.copy WHERE archived_at IS NULL').fetchone()[0]
        if by_job:
            job_id = run_job.queue(db, run_id, nothing)
            assert [tuple(r) for r in db.execute('SELECT name, total FROM job_step WHERE job_id=?', (job_id,))] == [('pull', 0)]
            run_job.drain(db)
            assert db.execute('SELECT state FROM job WHERE id=?', (job_id,)).fetchone()[0] == 'done'
        else:
            sync_run.apply(db, run_id, nothing)
        stage = sync_run.load(db, run_id)[0]['stages']['pull']
        assert stage['status'] == 'done' and not any(stage['counts'].values()), stage
        marked = db.execute('SELECT count(DISTINCT copy_id) FROM main.synced_from WHERE copy_id IS NOT NULL').fetchone()[0]
        assert marked > 0 and db.execute('SELECT count(*) FROM main.copy WHERE archived_at IS NULL').fetchone()[0] == copies
        sync_run.undo_run(db, stage['event'])
        assert db.execute('SELECT count(*) FROM main.synced_from').fetchone()[0] == 0


def _matching(client, remote, pair, **directions):
    """A run whose copies here already match the site and carry no Last synced from yet."""
    csrf = connected(client, pair)
    first = start(client, csrf, wishlist_dir='off', owned_dir='into')
    with db_of(pair) as db:
        sync_run.apply(db, first, form_for(db, first, send=False))
        db.execute('DELETE FROM main.synced_from')
        db.commit()
    return start(client, csrf, **{'wishlist_dir': 'off', 'owned_dir': 'into', **directions})


def test_stopping_a_queued_mark_only_run_leaves_no_step_waiting(client, remote, pair):  # noqa: F811
    run_id = _matching(client, remote, pair)
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, MultiDict())
        assert run_job.request_stop(db, run_id)
        run_job.drain(db)
        assert not db.execute("SELECT 1 FROM job_step WHERE job_id=? AND state='queued'", (job_id,)).fetchall()
        assert db.execute('SELECT count(*) FROM main.synced_from').fetchone()[0] == 0


def test_a_kind_that_does_not_come_in_is_not_marked(client, remote, pair):  # noqa: F811
    run_id = _matching(client, remote, pair, owned_dir='off', wishlist_dir='into')
    with db_of(pair) as db:
        run, plans = sync_run.load(db, run_id)
        assert sync_run.marked_rows(db, run, plans) == 0
        sync_run.apply(db, run_id, MultiDict())
        assert db.execute('SELECT count(*) FROM main.synced_from WHERE copy_id IS NOT NULL').fetchone()[0] == 0


def test_a_mark_only_pull_runs_no_lost_parts_step_and_renames_no_list(client, remote, pair, monkeypatch):  # noqa: F811
    from brickwork.core.sync import lost_parts
    run_id = _matching(client, remote, pair, lost_dir='into')
    monkeypatch.setattr(lost_parts, 'apply', lambda *a, **k: pytest.fail('the Lost Parts step ran'))
    monkeypatch.setattr(sync, '_apply_lists', lambda *a, **k: pytest.fail('list names were changed'))
    with db_of(pair) as db:
        plan = sync.load_plan(db, sync_run.load(db, run_id)[0]['pull'])
        plan['lists'] = dict(plan['lists'], preview=[dict(key='1', action='rename', sets=2, choices=['rename', 'keep'])])      # a list renamed there
        sync._store_plan(db, plan)
        sync_run.apply(db, run_id, MultiDict())
        stage = sync_run.load(db, run_id)[0]['stages']['pull']
        assert stage['status'] == 'done' and stage['lists_changed'] == 0, stage


def test_a_released_run_runs_every_stage_chosen_on_the_next_try(three_sends, monkeypatch):
    """A failure after a stage recorded `none` and before the next began releases the run; the record must not make the next try skip it."""
    pair, run_id, keys = three_sends
    real = run_job._run_one

    def records_none_then_fails(db, job, http):
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'pull': {'status': 'none'}}
        sync._store_plan(db, run)
        raise RuntimeError('boom')

    monkeypatch.setattr(run_job, '_run_one', records_none_then_fails)
    with db_of(pair) as db:
        run_job.queue(db, run_id, form_for(db, run_id, send=False))
        run_job.drain(db)
        released = sync_run.load(db, run_id)[0]
        assert not released.get('job') and released['stages'] == {}
        monkeypatch.setattr(run_job, '_run_one', real)
        job_id = run_job.queue(db, run_id, form_for(db, run_id, send=False))       # the second try, with rows chosen to come in
        run_job.drain(db)
        assert sync_run.load(db, run_id)[0]['stages']['pull']['status'] == 'done'
        assert not db.execute("SELECT 1 FROM job_step WHERE job_id=? AND state='queued'", (job_id,)).fetchall()


@pytest.mark.parametrize('owned,wished', [('into', 'off'), ('off', 'into'), ('to', 'into'), ('off', 'off')])
def test_a_pull_marks_only_the_kinds_that_come_in(client, remote, pair, owned, wished):  # noqa: F811
    from brickwork.core.sync import run as runs
    csrf = connected(client, pair)
    run_id = start(client, csrf, owned_dir='into', wishlist_dir='into')
    ways = dict(owned=owned, wishlist=wished)
    with db_of(pair) as db:
        plan_id = sync_run.load(db, run_id)[0]['pull']
        sync.apply_pull(db, plan_id, None, incoming=runs.kinds_in(ways))      # a pull that takes rows in
        copies = db.execute('SELECT count(*) FROM main.synced_from WHERE copy_id IS NOT NULL OR stock_id IS NOT NULL').fetchone()[0]
        wishes = db.execute('SELECT count(*) FROM main.synced_from WHERE wish_id IS NOT NULL').fetchone()[0]
    assert (copies > 0, wishes > 0) == (owned in ('into', 'both'), wished in ('into', 'both')), (copies, wishes)


def _matching_set_and_wish(pair, remote):
    """A copy and a wish here that already match the site, and one more wish there that a pull would add."""
    remote.lists = {1: {'1000-2': 1}, 2: {}, 9: {'1000-3': 1, '1000-4': 1}}
    with db_of(pair) as db:
        coll = Coll(db)
        coll.add_copy('1000-2')
        coll.add_wish(coll.item('sets', '1000-3'))


def _marked(db, copy_number='1000-2', wish_number='1000-3'):
    """Whether the matching copy and the matching wish carry Last synced from."""
    coll = Coll(db)
    copy = db.execute('SELECT 1 FROM main.synced_from s JOIN main.copy c ON c.id=s.copy_id WHERE c.item_id=?', (coll.item('sets', copy_number),)).fetchone()
    wish = db.execute('SELECT 1 FROM main.synced_from s JOIN main.wish w ON w.id=s.wish_id WHERE w.item_id=?', (coll.item('sets', wish_number),)).fetchone()
    return bool(copy), bool(wish)


@pytest.mark.parametrize('takes_a_wish', [False, True])
def test_a_pull_outside_a_run_follows_the_saved_directions_and_what_it_takes_in(client, remote, pair, takes_a_wish):  # noqa: F811
    _matching_set_and_wish(pair, remote)
    csrf = connected(client, pair)
    run_id = start(client, csrf, owned_dir='into', wishlist_dir='off')
    with db_of(pair) as db:
        plan = sync.load_plan(db, sync_run.load(db, run_id)[0]['pull'])
        wish_rows = [r['key'] for r in plan['rows'] if r['kind'] == 'wanted' and r['tickable']]
        assert wish_rows
        sync.apply_pull(db, plan['id'], wish_rows if takes_a_wish else [])
        assert _marked(db) == (True, takes_a_wish)


def test_a_run_marks_by_its_own_directions_not_by_those_saved_later(client, remote, pair):  # noqa: F811
    _matching_set_and_wish(pair, remote)
    csrf = connected(client, pair)
    run_id = start(client, csrf, owned_dir='into', wishlist_dir='off')
    start(client, csrf, owned_dir='into', wishlist_dir='into')      # the saved directions now take wishes in too
    with db_of(pair) as db:
        sync_run.apply(db, run_id, MultiDict())
        assert sync_run.load(db, run_id)[0]['stages']['pull']['status'] == 'done'
        assert _marked(db) == (True, False)
