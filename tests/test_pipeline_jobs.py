"""The import pipeline on `job` / `job_step` (M.8c, issue #110): queueing, the three local steps, the skipped source steps, handlers,
claims, and the drainer that runs it beside `store4.jobs`. Invented data, no network."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os

import pytest

from brickwork.core import drainer, pipeline
from brickwork.core.connect import connect
from brickwork.core.pipeline import Pipeline, StepDone, StepFailed, StepWait
from brickwork.store4 import bricklink_api, jobs
from tests.app4 import coll, pair  # noqa: F401 (fixtures)


def queue(coll, item, steps=None, **kw):
    db = coll.db
    db.execute('BEGIN IMMEDIATE')
    job = Pipeline(db).queue_steps(item, steps, via=kw.pop('via', 'app'), **kw)
    db.commit()
    return job


def steps(pl, job):
    return {s['name']: s for s in pl.status(job)['steps']}


def test_queue_makes_one_job_with_the_six_steps_in_the_settings_order(coll):
    db, pl = coll.db, Pipeline(coll.db)
    item = coll.item('sets', '1000-1')
    job = queue(coll, item)
    status = pl.status(job)
    assert (status['source'], status['kind'], status['item_id'], status['state'], status['via']) == ('import', 'item', item, 'queued', 'app')
    assert [s['name'] for s in status['steps']] == list(pipeline.STEPS)
    assert json.loads(steps(pl, job)['identity']['sources']) == ['catalogue']
    assert json.loads(steps(pl, job)['metadata']['sources']) == ['brickset'] and json.loads(steps(pl, job)['market_price']['sources']) == ['bricklink']
    assert json.loads(steps(pl, job)['pictures']['sources']) == ['bricklink', 'rebrickable_api']
    event = db.execute("SELECT * FROM event WHERE entity_kind='job' AND entity_id=?", (str(job),)).fetchone()
    assert (event['field'], json.loads(event['new_value'])['steps']) == ('queued', list(pipeline.STEPS))
    # The migrated settings decide: the order of the kind, the picture sources.
    reverse = list(reversed(pipeline.STEPS))
    coll.setting('import_order:part', json.dumps(reverse))
    coll.setting('source_priority', json.dumps({'pictures': {'part': ['rebrickable_dump']}}))
    part = queue(coll, coll.item('parts', '3001'))
    assert [s['name'] for s in pl.status(part)['steps']] == reverse
    assert json.loads(steps(pl, part)['pictures']['sources']) == ['rebrickable_dump']
    assert json.loads(steps(pl, part)['metadata']['sources']) == []                                  # no list for a part: nothing to try
    assert [s['name'] for s in pl.status(queue(coll, item, ['market_price', 'pictures']))['steps']] == ['market_price', 'pictures']


def test_queue_refuses_bad_input_and_needs_the_callers_transaction(coll):
    db, pl = coll.db, Pipeline(coll.db)
    item = coll.item('sets', '1000-1')
    with pytest.raises(ValueError, match='transaction'):
        pl.queue_steps(item, via='app')
    db.execute('BEGIN IMMEDIATE')
    for bad in (dict(steps=['nope']), dict(steps=[]), dict(steps=['pictures', 'pictures']), dict(via='sync')):
        with pytest.raises(ValueError):
            pl.queue_steps(item, **{'steps': None, 'via': 'app', **bad})
    db.rollback()
    coll.setting('import_order:set', json.dumps(['identity']))
    db.execute('BEGIN IMMEDIATE')
    with pytest.raises(ValueError, match='import order'):
        pl.queue_steps(item, via='app')
    db.rollback()
    assert db.execute('SELECT count(*) FROM job').fetchone()[0] == 0


def test_a_catalogue_set_finishes_locally_and_skips_the_source_steps(coll):
    pl = Pipeline(coll.db)
    job = queue(coll, coll.item('sets', '1000-1'))
    done = pl.run(job)
    assert done['state'] == 'done' and done['attempts'] == 1 and done['error'] is None
    got = steps(pl, job)
    for name in ('identity', 'inventory', 'matching'):
        assert (got[name]['state'], got[name]['error_code'], got[name]['error'], got[name]['source']) == ('done', None, None, 'catalogue'), name
    for name in ('pictures', 'metadata', 'market_price'):
        assert (got[name]['state'], got[name]['error'], got[name]['source'], got[name]['count'], got[name]['total']) == ('done', pipeline.SKIPPED, None, 0, 0), name
    assert coll.db.execute('SELECT count(*) FROM job_owner').fetchone()[0] == 0
    assert pl.run(job)['attempts'] == 1                                                              # a done job is not run again


def test_an_unidentified_item_ends_its_steps_done_with_the_code_and_the_job_finishes(coll):
    pl = Pipeline(coll.db)
    mystery = coll.local('gear', 'Mystery thing')
    job = queue(coll, mystery)
    assert pl.run(job)['state'] == 'done'
    got = steps(pl, job)
    assert (got['identity']['state'], got['identity']['error_code']) == ('done', 'unidentified')
    assert (got['inventory']['state'], got['inventory']['error_code']) == ('done', None)             # a gear item has no part list to look for
    assert (got['matching']['state'], got['matching']['error_code']) == ('done', 'unidentified')
    assert coll.db.execute('SELECT count(*) FROM item_provider_status WHERE item_id=?', (mystery,)).fetchone()[0] == 0     # nothing to say about a number it lacks
    unidentified_set = queue(coll, coll.local('set', 'Mystery set'))
    pl.run(unidentified_set)
    assert steps(pl, unidentified_set)['inventory']['error_code'] == 'unidentified'
    assert pl.status(unidentified_set)['state'] == 'done'


def test_an_identified_item_without_a_bricklink_number_is_recorded_unmatched(coll):
    pl = Pipeline(coll.db)
    part = coll.item('parts', '3901')
    coll.project(part)
    coll.sql("DELETE FROM item_link WHERE item_id=?", (part,))
    job = queue(coll, part)
    pl.run(job)
    assert (steps(pl, job)['matching']['state'], steps(pl, job)['matching']['error_code']) == ('done', 'unidentified')
    row = coll.db.execute('SELECT * FROM item_provider_status WHERE item_id=?', (part,)).fetchone()
    assert (row['provider'], row['status'], row['reason'], json.loads(row['evidence_json'])) == ('bricklink', 'unmatched', 'no_match', {'rebrickable': '3901'})
    pl.retry(job)                                                                                  # a second pass updates the one row
    queue_again = queue(coll, part)
    pl.run(queue_again)
    assert coll.db.execute('SELECT count(*) FROM item_provider_status WHERE item_id=?', (part,)).fetchone()[0] == 1
    assert not coll.db.in_transaction


def test_an_identified_set_with_no_part_list_is_not_found_but_done(coll):
    pl = Pipeline(coll.db)
    bl_only = coll.local('set', 'BrickLink-only set', born_key='99-9')
    job = queue(coll, bl_only)
    pl.run(job)
    got = steps(pl, job)
    assert (got['identity']['error_code'], got['inventory']['error_code'], got['matching']['error_code']) == (None, 'not_found', None)   # it is its own BrickLink number
    assert pl.status(job)['state'] == 'done'


def test_a_handler_runs_for_its_step_and_source_and_a_failure_can_be_retried(coll):
    pl = Pipeline(coll.db, handlers={('market_price', 'bricklink'): lambda db, job, step: calls.append(job['id'])})
    calls = []
    job = queue(coll, coll.item('sets', '1000-1'))
    assert pl.run(job)['state'] == 'done' and calls == [job]
    got = steps(pl, job)
    assert (got['market_price']['state'], got['market_price']['source'], got['market_price']['error']) == ('done', 'bricklink', None)
    assert got['pictures']['error'] == pipeline.SKIPPED
    # A handler that fails: the other steps are not held back, the job fails, a retry runs only the failed step.
    outcome = [StepFailed('source_error', 'BrickLink is down')]
    def flaky(db, job, step):
        if outcome:
            raise outcome.pop()
    pl = Pipeline(coll.db, handlers={('market_price', 'bricklink'): flaky})
    job = queue(coll, coll.item('sets', '1000-1'))
    failed = pl.run(job)
    assert (failed['state'], failed['error'], failed['error_code']) == ('failed', 'BrickLink is down', 'source_error')
    assert steps(pl, job)['identity']['state'] == 'done' and steps(pl, job)['market_price']['state'] == 'failed'
    assert pl.run(job)['state'] == 'failed'                                                          # no retry unless asked: failed is final
    with pytest.raises(ValueError, match='unknown import step'):
        pl.queue_retry(job, 'nope')
    assert pl.retry(job, 'market_price')['state'] == 'done'
    assert steps(pl, job)['market_price']['state'] == 'done'


def test_a_provider_failure_is_not_erased_by_a_fallback_without_a_handler(coll):
    # Codex on M.8c: the first source fails, the next has no handler (yet): the step stays failed and Retry offers it
    job = queue(coll, coll.item('sets', '1000-1'))
    sources = json.loads(coll.db.execute("SELECT sources FROM job_step WHERE job_id=? AND name='pictures'", (job,)).fetchone()[0])
    assert len(sources) >= 2
    def down(db, job, step):
        raise StepFailed('source_error', 'down')
    failed = Pipeline(coll.db, handlers={('pictures', sources[0]): down}).run(job)
    got = steps(Pipeline(coll.db), job)['pictures']
    assert (failed['state'], got['state'], got['error']) == ('failed', 'failed', 'down')


def test_a_handler_may_end_its_step_done_with_a_finding(coll):
    pl = Pipeline(coll.db, handlers={('market_price', 'bricklink'): lambda db, job, step: (_ for _ in ()).throw(StepDone('unidentified', 'No BrickLink id'))})
    job = queue(coll, coll.item('sets', '1000-1'))
    assert pl.run(job)['state'] == 'done'
    got = steps(pl, job)['market_price']
    assert (got['state'], got['error_code'], got['error'], got['source']) == ('done', 'unidentified', 'No BrickLink id', 'bricklink')


def test_a_wait_marks_the_job_waiting_until_the_retry_time(coll):
    until = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    pl = Pipeline(coll.db, handlers={('market_price', 'bricklink'): lambda db, job, step: (_ for _ in ()).throw(StepWait(until, 'BrickLink budget'))})
    job = queue(coll, coll.item('sets', '1000-1'))
    waiting = pl.run(job)
    assert (waiting['state'], waiting['retry_at']) == ('waiting_for_budget', until)
    assert (steps(pl, job)['market_price']['state'], steps(pl, job)['market_price']['error_code']) == ('waiting_for_budget', 'budget')
    assert pl.drain() == [] and pl.status(job)['attempts'] == 1                                      # not due yet
    with closing(connect(coll.db.execute('PRAGMA database_list').fetchone()[2])) as other:
        assert drainer.poll_delay(other) > 1 and drainer.poll_delay(other) <= 60
    coll.sql("UPDATE job SET retry_at='2000-01-01T00:00:00.000Z' WHERE id=?", (job,))
    coll.sql("UPDATE job_step SET retry_at='2000-01-01T00:00:00.000Z' WHERE job_id=?", (job,))
    pl.handlers = {('market_price', 'bricklink'): lambda db, job, step: None}
    assert [j['state'] for j in pl.drain()] == ['done']


def test_a_live_owner_is_excluded_and_a_dead_or_unclaimed_one_is_taken_over(coll):
    pl = Pipeline(coll.db)
    job = queue(coll, coll.item('sets', '1000-1'))
    coll.sql('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, 1, ?)', (job, '2026-10-26T12:00:00.000Z'))      # pid 1 is always alive
    assert pl.run(job)['state'] == 'queued' and pl.drain() == []
    coll.sql('DELETE FROM job_owner')
    coll.sql('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, ?, ?)', (job, os.getpid(), '2026-10-26T12:00:00.000Z'))   # this process, no claim: crashed
    assert pl.run(job)['state'] == 'done'
    assert coll.db.execute('SELECT count(*) FROM job_owner').fetchone()[0] == 0


def test_an_interrupt_leaves_the_job_queued_and_unclaimed(coll):
    def interrupt(db, job, step):
        raise KeyboardInterrupt
    pl = Pipeline(coll.db, handlers={('pictures', 'bricklink'): interrupt})
    job = queue(coll, coll.item('sets', '1000-1'))
    with pytest.raises(KeyboardInterrupt):
        pl.run(job)
    assert pl.status(job)['state'] == 'queued' and coll.db.execute('SELECT count(*) FROM job_owner').fetchone()[0] == 0
    assert not pipeline._CLAIMED_JOBS


@pytest.mark.parametrize('kind', ['minifigure', 'part', 'gear', 'book', 'catalog', 'instructions', 'box'])
def test_every_kind_finishes(coll, kind):
    pl = Pipeline(coll.db)
    item = coll.item('minifigs', 'fig-000004') if kind == 'minifigure' else coll.item('parts', '3001') if kind == 'part' else coll.local(kind, 'Local ' + kind, born_key='k-1')
    job = queue(coll, item)
    assert pl.run(job)['state'] == 'done'
    assert {s['state'] for s in pl.status(job)['steps']} == {'done'}


def test_the_two_runners_ignore_each_others_jobs_and_the_drainer_runs_both(coll, pair, monkeypatch):
    db, pl = coll.db, Pipeline(coll.db)
    pipeline_job = queue(coll, coll.item('sets', '1000-1'))
    db.execute('BEGIN IMMEDIATE')
    fetch, _ = jobs.queue_in(db, 'bricklink_subsets', item_id=coll.item('sets', '1000-2'), payload='1000-2', via='app')
    db.commit()
    assert pl.drain() and pl.status(pipeline_job)['state'] == 'done'
    assert jobs.status(db, fetch)['state'] == 'queued'                                                # the pipeline did not touch the fetch job
    queue(coll, coll.item('sets', '1000-2'))
    for name in bricklink_api.KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    assert jobs.drain(db) == []                                                                       # no key: the fetch job fails, it does not run
    assert (jobs.status(db, fetch)['state'], jobs.status(db, fetch)['error_code']) == ('failed', 'source_not_configured')
    assert db.execute("SELECT state FROM job WHERE kind='item' ORDER BY id DESC").fetchone()[0] == 'queued'
    with closing(connect(pair)) as other:
        assert drainer.pending(other) and drainer.poll_delay(other) == 1
    drainer.drain_once(pair)
    with closing(connect(pair)) as other:
        assert {r['state'] for r in other.execute("SELECT state FROM job WHERE kind='item'")} == {'done'}
        assert drainer.poll_delay(other) is None and not drainer.pending(other)


def test_queue_new_items_queues_once_per_item(coll):
    db = coll.db
    db.execute('BEGIN IMMEDIATE')
    first = pipeline.queue_new_items(db, [coll.item('sets', '1000-1'), coll.item('sets', '1000-1')])
    second = pipeline.queue_new_items(db, [coll.item('sets', '1000-1'), coll.item('sets', '1000-2')])
    db.commit()
    assert len(first) == 1 and len(second) == 1


def test_foreign_keys_hold_after_a_run(coll):
    queue_ = queue(coll, coll.item('sets', '1000-1'))
    Pipeline(coll.db).run(queue_)
    assert coll.db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_drainer_rechecks_before_it_stops(tmp_path, monkeypatch):
    from flask import Flask
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '1')
    app = Flask('drain')
    rounds, pending = [], [True, False]
    monkeypatch.setattr(drainer, 'loop', lambda path, sleep: rounds.append(1))
    monkeypatch.setattr(drainer, 'poll_delay', lambda db: 0 if pending.pop(0) else None)
    monkeypatch.setattr(drainer, 'connect', lambda path: __import__('sqlite3').connect(':memory:'))
    started = []
    assert drainer.start(app, tmp_path / 'x.db', fallback=lambda run: started.append(run))
    assert drainer.start(app, tmp_path / 'x.db', fallback=lambda run: started.append(run))  # already active
    assert len(started) == 1
    started[0]()
    assert len(rounds) == 2  # a job found at the final check runs another round
    assert not app.extensions['bw_import_worker_active']
