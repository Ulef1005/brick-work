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


def test_a_stage_that_was_started_is_never_run_again_after_a_takeover(three_sends, monkeypatch):
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, form_for(db, run_id))
        run = sync_run.load(db, run_id)[0]
        run['stages']['send'] = {'status': 'started'}
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='running' WHERE id=?", (job_id,))
        db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 999999999, ?)', (job_id, '2026-01-01T00:00:00.000Z'))
        db.commit()
        monkeypatch.setattr(adapters.RebrickableUser, 'send', lambda *a, **k: pytest.fail('a send ran again'))
        run_job.drain(db)
        run = sync_run.load(db, run_id)[0]
    assert run['stages']['send'] == {'status': 'failed', 'message': run_job.INTERRUPTED_MESSAGE}
    assert run['applied']


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


def test_the_plan_does_not_expire_while_the_job_works(three_sends):
    pair, run_id, keys = three_sends
    with db_of(pair) as db:
        before = sync_run.load(db, run_id)[0]['created_at']
        run_job.queue(db, run_id, form_for(db, run_id))
        run_job.drain(db)
        assert sync_run.load(db, run_id)[0]['created_at'] >= before
