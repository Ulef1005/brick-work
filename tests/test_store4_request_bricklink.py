"""A copy that already exists moves to BrickLink's list (design 4.3 decision F, existing copy; issue #112, M.10 A): at once when a BrickLink
list is fetched, else it waits on the queued `bricklink_subsets` job and the job's success runs the automatic switch. Invented data."""
import pytest

from brickwork.store4 import copies, jobs, pending
from brickwork.store4.errors import Store4Error
from tests.test_store4_copies import SET, add, db, fetch, key, no_key, q   # noqa: F401  (fixtures)
from tests.test_store4_pending import copy_row, job_of, ok, run
from tests.test_store4_switch import events


def request(db, cid):
    return pending.request_bricklink(db, cid, via='cli', actor='t')


def test_with_a_fetched_list_the_copy_switches_at_once(db, key):
    fid = fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
    cid = add(db)['copy']['id']
    r = request(db, cid)
    assert r['switched'] is True and r['receipt']['event_id']
    assert copy_row(db, cid) == ('bricklink', None, fid, None, None)
    assert events(db, cid) == [('add',), ('part_list_switch',)]


def test_without_one_the_copy_waits_on_a_queued_job_and_keeps_its_list(db, key):
    cid = add(db)['copy']['id']
    before = copy_row(db, cid)
    r = request(db, cid)
    job = job_of(db, cid)
    assert r == {'switched': False, 'pending': {'source': 'bricklink', 'job_id': job, 'job_reused': False}}
    assert copy_row(db, cid)[:3] == before[:3] and copy_row(db, cid)[3:] == ('bricklink', job)
    assert q(db, 'SELECT kind, state, item_id FROM job WHERE id=?', job) == [('bricklink_subsets', 'queued', SET)]
    assert pending.pending_offer(db, cid)['state'] == 'waiting'
    assert events(db, cid) == [('add',), ('pending_request',)]


def test_the_jobs_success_runs_the_automatic_switch(db, key):
    cid = add(db)['copy']['id']
    request(db, cid)
    r = run(db, job_of(db, cid), ok())
    assert [(s['copy_id'], s['outcome']) for s in r['settled']] == [(cid, 'switched')]
    assert copy_row(db, cid)[0] == 'bricklink' and copy_row(db, cid)[3:] == (None, None)


def test_a_second_copy_reuses_the_open_job(db, key):
    a, b = add(db)['copy']['id'], add(db)['copy']['id']
    request(db, a)
    assert request(db, b)['pending']['job_reused'] is True and job_of(db, a) == job_of(db, b)


def test_the_request_is_refused_without_a_key_when_waiting_or_already_on_it(db, key, monkeypatch):
    cid = add(db)['copy']['id']
    request(db, cid)
    with pytest.raises(Store4Error, match='already waiting'):
        request(db, cid)
    fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
    done = add(db)['copy']['id']
    request(db, done)
    with pytest.raises(copies.NothingToSwitch):
        request(db, done)
    for name in ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET'):
        monkeypatch.delenv('BW_BRICKLINK_' + name)
    with pytest.raises(Store4Error, match='needs a BrickLink key|without a BrickLink key'):
        request(db, add(db)['copy']['id'])
