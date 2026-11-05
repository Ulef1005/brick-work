"""#194: the Brickset `metadata` step asks for the other queued jobs' sets in the same `getSets` call. Fake Brickset, no network."""
import json
from urllib.parse import parse_qs

import pytest

from brickwork.core import pipeline
from brickwork.core.pipeline import Pipeline
from brickwork.core.sources import base, brickset
from tests.app4 import coll, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import Net, keyed, step_handlers, unkeyed
from tests.test_brickwork_pipeline import queue, steps
from tests.test_brickwork_sources import brickset_row, used


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)


def reply(*numbers):
    rows = [brickset_row(*n.split('-')[:1], int(n.split('-')[1]), setID=i) for i, n in enumerate(numbers, 1)]
    return {'status': 'success', 'matches': len(rows), 'sets': rows}


def asked(net):
    return [parse_qs(r.data.decode())['params'][0] for r in net.requests]


def pipe(net):
    return lambda coll: Pipeline(coll.db, handlers=step_handlers(http=net))


def test_queued_metadata_steps_share_one_call(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    net = Net(reply('1000-1', '1000-2', '2070-1'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    jobs = [queue(coll, i, ['metadata']) for i in (world.keep, world.gate, world.duplo)]
    assert pl.run(jobs[0])['state'] == 'done'
    assert len(net.requests) == 1 and json.loads(asked(net)[0])['setNumber'] == '1000-1,1000-2,2070-1'
    assert used(coll.db, 'brickset')[0][1] == 1
    for job, item in zip(jobs, (world.keep, world.gate, world.duplo)):
        step = steps(pl, job)['metadata']
        assert (step['state'], step['source'], step['error_code']) == ('done', 'brickset', None)
        assert coll.db.execute("SELECT value FROM item_property WHERE item_id=? AND key='pieces' AND source='brickset'", (item,)).fetchone()[0] == '438'
        assert coll.db.execute("SELECT price FROM price_observation WHERE guide='retail' AND item_id=?", (item,)).fetchone()[0] == '79.99'
        assert coll.db.execute('SELECT count(*) FROM job_owner WHERE job_id=?', (job,)).fetchone()[0] == 0
    assert [Pipeline.status(pl, j)['state'] for j in jobs[1:]] == ['queued', 'queued']       # the drain finishes them: nothing left to ask
    pl.drain()
    assert [pl.status(j)['state'] for j in jobs] == ['done'] * 3 and len(net.requests) == 1


def test_a_set_missing_from_the_reply_is_not_found_in_its_own_job(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    net = Net(reply('1000-1', '2070-1'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    jobs = [queue(coll, i, ['metadata']) for i in (world.keep, world.gate, world.duplo)]
    pl.run(jobs[0])
    assert [(steps(pl, j)['metadata']['state'], steps(pl, j)['metadata']['error_code']) for j in jobs] == \
        [('done', None), ('done', 'not_found'), ('done', None)]
    assert [tuple(r) for r in coll.db.execute('SELECT item_id, reason FROM item_provider_status WHERE provider=?', ('brickset',))] == [(world.gate, 'no_match')]


def test_a_job_whose_next_step_is_another_is_left_alone(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    net = Net(reply('1000-1', '1000-2'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    first = queue(coll, world.keep, ['metadata'])
    other = queue(coll, world.gate, ['pictures', 'metadata'])
    pl.run(first)
    assert json.loads(asked(net)[0])['setNumber'] == '1000-1'
    got = pl.status(other)
    assert got['state'] == 'queued' and [s['state'] for s in got['steps']] == ['queued', 'queued']


def test_a_running_or_cancelled_job_is_not_taken(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    monkeypatch.setattr(pipeline, '_CLAIMED_JOBS', set())                                   # the claim below is never released
    net = Net(reply('1000-1'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    first = queue(coll, world.keep, ['metadata'])
    claimed = queue(coll, world.gate, ['metadata'])
    cancelled = queue(coll, world.duplo, ['metadata'], batch='bulk')
    other = Pipeline(coll.db)
    assert other._claim(claimed) is not None                                                # another worker has it
    assert pipeline.cancel_batch(coll.db, 'bulk') == 1
    pl.run(first)
    assert json.loads(asked(net)[0])['setNumber'] == '1000-1'
    assert pl.status(claimed)['steps'][0]['state'] == 'queued' and pl.status(cancelled)['steps'][0]['error'] == pipeline.CANCELLED
    assert coll.db.execute('SELECT count(*) FROM job_owner WHERE job_id=?', (claimed,)).fetchone()[0] == 1


def test_an_exhausted_budget_calls_nothing_and_the_jobs_keep_waiting(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    net = Net(reply('1000-1', '1000-2'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    jobs = [queue(coll, i, ['metadata']) for i in (world.keep, world.gate)]
    coll.db.execute('INSERT INTO source_budget(source, day, used) VALUES(?, ?, ?)', ('brickset', base.day_of(), brickset.Brickset.daily_budget))
    coll.db.commit()
    assert pl.run(jobs[0])['state'] == 'waiting_for_budget'
    assert net.requests == []
    before = pl.status(jobs[1])
    assert before['state'] == 'queued' and before['attempts'] == 0 and before['steps'][0]['state'] == 'queued'
    assert coll.db.execute('SELECT count(*) FROM job_owner').fetchone()[0] == 0
    coll.db.execute("UPDATE job SET state='waiting_for_budget', retry_at='2999-01-01T00:00:00.000Z' WHERE id=?", (jobs[1],))
    coll.db.commit()
    pl.run(jobs[0])
    after = pl.status(jobs[1])
    assert (after['state'], after['retry_at']) == ('waiting_for_budget', '2999-01-01T00:00:00.000Z') and net.requests == []


def test_a_waiting_job_joins_the_call_once_the_budget_allows_it(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    net = Net(reply('1000-1', '1000-2'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    jobs = [queue(coll, i, ['metadata']) for i in (world.keep, world.gate)]
    coll.db.execute("UPDATE job SET state='waiting_for_budget', retry_at='2999-01-01T00:00:00.000Z' WHERE id=?", (jobs[1],))
    coll.db.execute("UPDATE job_step SET state='waiting_for_budget', retry_at='2999-01-01T00:00:00.000Z' WHERE job_id=?", (jobs[1],))
    coll.db.commit()
    pl.run(jobs[0])
    assert json.loads(asked(net)[0])['setNumber'] == '1000-1,1000-2' and len(net.requests) == 1
    assert steps(pl, jobs[1])['metadata']['state'] == 'done'


def test_a_failed_call_leaves_every_job_as_before(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    net = Net({'status': 'error', 'message': 'boom'})
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    jobs = [queue(coll, i, ['metadata']) for i in (world.keep, world.gate)]
    assert pl.run(jobs[0])['state'] == 'failed'
    mate = pl.status(jobs[1])
    assert (mate['state'], mate['attempts'], mate['steps'][0]['state']) == ('queued', 0, 'queued')
    assert coll.db.execute('SELECT count(*) FROM job_owner').fetchone()[0] == 0


def test_the_call_takes_at_most_batch_sets_the_current_job_first(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    monkeypatch.setattr(brickset, 'BATCH', 2)
    net = Net(reply('1000-2', '2070-1'), reply('1000-1'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    jobs = [queue(coll, i, ['metadata']) for i in (world.gate, world.duplo, world.keep)]
    pl.run(jobs[0])
    assert json.loads(asked(net)[0])['setNumber'] == '1000-2,2070-1' and len(net.requests) == 1
    assert [steps(pl, j)['metadata']['state'] for j in jobs] == ['done', 'done', 'queued']


def owned(coll):
    return coll.db.execute("SELECT count(*) FROM job_owner").fetchone()[0], coll.db.execute("SELECT count(*) FROM job WHERE state='running'").fetchone()[0]


def test_a_claim_that_fails_part_way_releases_the_ones_already_taken(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    monkeypatch.setattr(pipeline, '_CLAIMED_JOBS', set())
    pl = Pipeline(coll.db, handlers=step_handlers(http=Net(reply('1000-1'))))
    jobs = [queue(coll, i, ['metadata']) for i in (world.keep, world.gate, world.duplo)]
    real, calls = pipeline.Pipeline.owner_alive, []

    def flaky(self, job):
        calls.append(job)
        if len(calls) == 2:
            raise RuntimeError('database is locked')
        return real(self, job)
    monkeypatch.setattr(pipeline.Pipeline, 'owner_alive', flaky)
    with pytest.raises(RuntimeError, match='locked'):
        pipeline.claim_batchmates(coll.db, 'metadata', 'brickset', exclude=jobs[0], limit=5)
    assert owned(coll) == (0, 0) and not pipeline._CLAIMED_JOBS
    assert [pl.status(j)['state'] for j in jobs[1:]] == ['queued', 'queued']


def test_a_failing_finish_releases_the_unfinished_mates_and_keeps_the_finished_ones_done(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    monkeypatch.setattr(pipeline, '_CLAIMED_JOBS', set())
    net = Net(reply('1000-1', '1000-2', '2070-1'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    jobs = [queue(coll, i, ['metadata']) for i in (world.keep, world.gate, world.duplo)]
    real, count = pipeline._unclaim, []

    def flaky(db, claim, step=None, **done):
        if step is not None:
            count.append(claim['job'])
            if len(count) == 2:
                raise RuntimeError('database is locked')
        return real(db, claim, step, **done)
    monkeypatch.setattr(pipeline, '_unclaim', flaky)
    with pytest.raises(RuntimeError, match='locked'):
        pl.run(jobs[0])
    assert owned(coll)[0] == 0 and not pipeline._CLAIMED_JOBS
    assert coll.db.execute("SELECT count(*) FROM job WHERE state='running' AND id!=?", (jobs[0],)).fetchone()[0] == 0
    assert [steps(pl, j)['metadata']['state'] for j in jobs[1:]] == ['done', 'queued']


def test_a_candidate_that_moved_on_before_its_claim_is_not_taken(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    monkeypatch.setattr(pipeline, '_CLAIMED_JOBS', set())
    jobs = [queue(coll, i, ['metadata']) for i in (world.keep, world.gate, world.duplo)]

    def accept(item):
        if item == world.gate:                                               # the gate's job finishes its step after the selection
            coll.db.execute("UPDATE job_step SET state='done' WHERE job_id=?", (jobs[1],))
            coll.db.commit()
        return True
    claims = pipeline.claim_batchmates(coll.db, 'metadata', 'brickset', exclude=jobs[0], limit=5, accept=accept)
    assert [c['job'] for c in claims] == [jobs[2]]
    pipeline.release_batchmates(coll.db, claims)
    assert owned(coll) == (0, 0)
