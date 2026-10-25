"""The job runner for the two fetch kinds: queue, per-day budget, waiting, retries, owners, error codes, drain (design 5.2, 6.5; issue #107, M.5d).
All replies are invented and no test touches the network: `http` is injected."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
import sqlite3
import subprocess

import pytest

from brickwork.store4 import jobs, rebrickable_api as ra
from brickwork.store4.connect import connect
from brickwork.store4.errors import Store4Error
from tests.store4_fixtures import pair
from tests.test_store4_bricklink_subsets import entry, reply
from tests.test_store4_rebrickable_api import Fake, figure, part

T0 = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
MIDNIGHT = '2026-10-26T00:00:00.000Z'
SET = 'NEW-1'
CATALOGUE_SET = 10                                              # 6081-1, with the BrickLink link ('S', '6081-1')
NO_LINK_SET = 21                                                # a catalogue set without any BrickLink key
KEYS = {'BW_BRICKLINK_CONSUMER_KEY': 'ck-secret-1', 'BW_BRICKLINK_CONSUMER_SECRET': 'cs-secret-2', 'BW_BRICKLINK_TOKEN_VALUE': 'tv-secret-3',
        'BW_BRICKLINK_TOKEN_SECRET': 'ts-secret-4', 'BW_REBRICKABLE_API_KEY': 'test-key'}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('BW_BRICKLINK_DAILY_BUDGET', raising=False)
    monkeypatch.delenv('BW_REBRICKABLE_DAILY_BUDGET', raising=False)
    jobs._DEFAULT_HTTP.clear()


@pytest.fixture
def world(tmp_path):
    col, cat = pair(tmp_path)
    with closing(sqlite3.connect(cat)) as c:
        c.execute("INSERT INTO item(id, kind, kind_source, name, name_key, size_key, year, num_parts, build_id, born_provider, born_namespace,"
                  " born_key, digest) VALUES(?, 'set', 'namespace', 'No BrickLink', 'no bricklink', '', 1993, 4, 1, 'rebrickable', 'sets', '7777-1', 'd')",
                  (NO_LINK_SET,))
        c.commit()
    return col, cat


@pytest.fixture
def db(world):
    with closing(connect(*world)) as conn:
        yield conn


class Net:
    """One injectable `http` for both sources: records every URL, answers BrickLink with `bl` and Rebrickable with `rb`."""

    def __init__(self, rb=None, bl=None):
        self.urls, self.rb, self.bl = [], rb, bl if bl is not None else (200, reply(entry('3023', 5, 10, 3), entry('3626', 11, 4)))

    def __call__(self, url, headers):
        self.urls.append(url)
        if 'bricklink.com' in url:
            assert headers['Authorization'].startswith('OAuth ')
            return self.bl(url) if callable(self.bl) else self.bl
        return self.rb(url, headers)


def rebrickable(figures=2, **kw):
    figs = [figure(f'fig-new{i}') for i in range(figures)]
    return Fake(set_parts=[part('3023', 4, 2), part('3626', 0, 1)], minifigs=figs,
                figure_parts={f'fig-new{i}': [part('3626', 0)] for i in range(figures)}, **kw)


def q(db, sql, *args):
    return [tuple(r) for r in db.execute(sql, args)]


def bricklink_job(db, now=T0, item=CATALOGUE_SET):
    return jobs.queue(db, 'bricklink_subsets', item_id=item, payload='6081-1', via='cli', now=now)


def rebrickable_job(db, number=SET, now=T0):
    return jobs.queue(db, 'rebrickable_set', payload=number, via='cli', now=now)


def used(db, source='bricklink'):
    return q(db, 'SELECT day, used FROM source_budget WHERE source=? ORDER BY day', source)


# ---------- queue ----------

def test_queue_makes_a_queued_job_with_one_step_and_an_event(db):
    job = bricklink_job(db)
    s = jobs.status(db, job)
    assert (s['source'], s['kind'], s['state'], s['item_id'], s['number'], s['via'], s['attempts']) == ('bricklink', 'bricklink_subsets', 'queued', 10, '6081-1', 'cli', 0)
    assert (s['step']['name'], s['step']['state'], s['step']['count'], s['step']['total']) == ('fetch', 'queued', 0, 1)
    assert q(db, "SELECT entity_kind, entity_id, field FROM event WHERE entity_kind='job'") == [('job', str(job), 'created')]
    assert jobs.status(db, rebrickable_job(db))['step']['total'] == 3


def test_a_second_queue_returns_the_open_job_until_it_is_done(db):
    first = bricklink_job(db)
    assert bricklink_job(db) == first
    assert rebrickable_job(db) == rebrickable_job(db)
    net = Net()
    assert jobs.run(db, first, http=net, now=T0)['state'] == 'done'
    again = bricklink_job(db)
    assert again != first and jobs.status(db, again)['state'] == 'queued'


def test_a_waiting_job_and_a_job_waiting_for_its_retry_still_count_as_open(db, monkeypatch):
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    jobs.run(db, bricklink_job(db), http=Net(), now=T0)
    waiting = bricklink_job(db)
    assert jobs.run(db, waiting, http=Net(), now=T0)['state'] == 'waiting_for_budget'
    assert bricklink_job(db) == waiting
    retry = rebrickable_job(db)
    jobs.run(db, retry, http=Net(rb=Fake(set_status=500)), now=T0)
    assert jobs.status(db, retry)['state'] == 'failed' and rebrickable_job(db) == retry


def test_a_final_failure_does_not_block_a_new_job(db):
    job = bricklink_job(db)
    jobs.run(db, job, http=Net(bl=(404, {'meta': {'code': 404}})), now=T0)
    assert jobs.status(db, job)['state'] == 'failed'
    assert bricklink_job(db) != job


def test_queue_refuses_what_cannot_be_fetched(db):
    with pytest.raises(Store4Error, match='unknown job kind'):
        jobs.queue(db, 'prices', payload='6081-1', via='cli')
    with pytest.raises(Store4Error, match='needs the set item'):
        jobs.queue(db, 'bricklink_subsets', payload='6081-1', via='cli')
    with pytest.raises(Store4Error, match='not a set number'):
        jobs.queue(db, 'rebrickable_set', payload='../x', via='cli')
    with pytest.raises(Store4Error, match='not a set in the collection'):
        jobs.queue(db, 'bricklink_subsets', item_id=11, payload='3023', via='cli')
    with pytest.raises(ra.SetInCatalogue):
        jobs.queue(db, 'rebrickable_set', payload='6081-1', via='cli')
    assert q(db, 'SELECT count(*) FROM job') == [(0,)]


def test_queueing_a_catalogue_set_projects_it_into_the_collection(db):
    assert q(db, 'SELECT count(*) FROM main.item WHERE id=10') == [(0,)]
    bricklink_job(db)
    assert q(db, 'SELECT count(*) FROM main.item WHERE id=10') == [(1,)]


# ---------- running, both kinds ----------

def test_a_bricklink_run_stores_the_list_under_the_job(db):
    job = bricklink_job(db)
    net = Net()
    r = jobs.run(db, job, http=net, now=T0)
    assert (r['ran'], r['state'], r['attempts'], r['error_code'], r['retry_at']) == (True, 'done', 1, None, None)
    assert r['result']['required_lines'] == 2 and r['result']['spare_lines'] == 1
    assert q(db, 'SELECT job_id, source, is_latest FROM main.fetched_inventory') == [(job, 'bricklink', 1)]
    assert q(db, "SELECT job_id FROM main.source_record WHERE source='bricklink'") == [(job,)]
    assert (r['step']['state'], r['step']['count'], r['step']['total']) == ('done', 1, 1)
    assert len(net.urls) == 1 and net.urls[0].startswith('https://api.bricklink.com/api/store/v1/items/SET/6081-1/subsets?') and 'break_minifigs=false' in net.urls[0]
    assert q(db, 'SELECT count(*) FROM job_owner') == [(0,)]


def test_a_rebrickable_run_stores_the_list_under_the_job(db):
    job = rebrickable_job(db)
    r = jobs.run(db, job, http=Net(rb=rebrickable()), now=T0)
    assert (r['state'], r['attempts']) == ('done', 1)
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory WHERE job_id=?', job) == [(3,)]            # the set and its two figures
    assert q(db, 'SELECT DISTINCT job_id FROM main.source_record') == [(job,)]
    assert (r['step']['count'], r['step']['total']) == (5, 5) and r['result']['calls'] == 5
    assert jobs.status(db, job)['budget_used'] == 5
    assert q(db, 'SELECT item_id >= 1000000000 FROM job WHERE id=?', job) == [(1,)]                           # the job names the set it made


def test_the_budget_is_counted_per_call_and_per_utc_day(db):
    jobs.run(db, rebrickable_job(db), http=Net(rb=rebrickable()), now=T0)
    assert used(db, 'rebrickable') == [('2026-10-25', 5)]
    jobs.run(db, bricklink_job(db), http=Net(), now=T0)
    jobs.run(db, bricklink_job(db), http=Net(), now=T0 + timedelta(hours=13))                             # 01:00 the next UTC day
    assert used(db) == [('2026-10-25', 1), ('2026-10-26', 1)]
    assert used(db, 'rebrickable') == [('2026-10-25', 5)]


def test_the_default_budgets_are_the_3_3_ones_and_come_from_the_environment(monkeypatch):
    assert (jobs.daily_budget('bricklink'), jobs.daily_budget('rebrickable')) == (4400, 1000)
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '10')
    assert jobs.daily_budget('bricklink') == 10
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '0')
    with pytest.raises(Store4Error, match='positive integer'):
        jobs.daily_budget('rebrickable')


# ---------- budget exhausted ----------

def test_an_exhausted_budget_waits_until_midnight_and_runs_after_it(db, monkeypatch):
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    jobs.run(db, bricklink_job(db), http=Net(), now=T0)
    job, net = bricklink_job(db), Net()
    r = jobs.run(db, job, http=net, now=T0)
    assert (r['state'], r['error_code'], r['retry_at'], r['attempts'], r['step']['state']) == ('waiting_for_budget', 'budget', MIDNIGHT, 0, 'waiting_for_budget')
    assert net.urls == [] and used(db) == [('2026-10-25', 1)]
    assert jobs.drain(db, now=T0 + timedelta(hours=11, minutes=59), http=net) == [] and net.urls == []       # 23:59, not yet
    ran = jobs.drain(db, now=T0 + timedelta(hours=12, seconds=1), http=net)
    assert [x['state'] for x in ran] == ['done'] and ran[0]['id'] == job
    assert used(db) == [('2026-10-25', 1), ('2026-10-26', 1)]


def test_a_rebrickable_set_needs_three_calls_left_to_start(db, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '5')
    assert jobs.run(db, rebrickable_job(db), http=Net(rb=rebrickable(figures=0)), now=T0)['state'] == 'done'            # 3 calls, 2 left
    net = Net(rb=rebrickable(figures=0))
    r = jobs.run(db, rebrickable_job(db, 'NEW-2'), http=net, now=T0)
    assert (r['state'], r['retry_at'], r['attempts'], r['step']['count']) == ('waiting_for_budget', MIDNIGHT, 0, 0)
    assert net.urls == [] and used(db, 'rebrickable') == [('2026-10-25', 3)]


def test_exactly_three_left_is_enough_for_a_set_without_figures(db, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '6')
    jobs.run(db, rebrickable_job(db), http=Net(rb=rebrickable(figures=0)), now=T0)
    assert jobs.run(db, rebrickable_job(db, 'NEW-2'), http=Net(rb=rebrickable(figures=0, set_num='NEW-2')), now=T0)['state'] == 'done'
    assert used(db, 'rebrickable') == [('2026-10-25', 6)]


def test_a_fetch_cut_off_mid_way_writes_nothing_and_starts_over_the_next_day(db, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '4')
    job, net = rebrickable_job(db), Net(rb=rebrickable(figures=2))
    r = jobs.run(db, job, http=net, now=T0)                                                              # needs 5, has 4
    assert (r['state'], r['error_code'], r['retry_at']) == ('waiting_for_budget', 'budget', MIDNIGHT)
    assert len(net.urls) == 4 and used(db, 'rebrickable') == [('2026-10-25', 4)]
    assert (r['step']['count'], r['attempts']) == (4, 1)
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)] and q(db, 'SELECT count(*) FROM main.source_record') == [(0,)]
    assert q(db, 'SELECT count(*) FROM main.item WHERE id>=1000000000') == [(0,)]
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '5')
    r = jobs.run(db, job, http=Net(rb=rebrickable(figures=2)), now=T0 + timedelta(hours=13))
    assert (r['state'], r['attempts'], r['step']['count']) == ('done', 2, 5)
    assert used(db, 'rebrickable') == [('2026-10-25', 4), ('2026-10-26', 5)]
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(3,)]


# ---------- rate wait (429) ----------

def test_a_429_is_a_rate_wait_with_the_time_the_reply_names(db):
    job = rebrickable_job(db)
    net = Net(rb=lambda url, headers: (429, {'detail': 'Request was throttled. Expected available in 25 seconds.'}))
    r = jobs.run(db, job, http=net, now=T0)
    assert (r['state'], r['error_code'], r['retry_at']) == ('waiting_for_budget', 'budget', '2026-10-25T12:00:25.000Z')
    assert used(db, 'rebrickable') == [('2026-10-25', 1)] and r['attempts'] == 1
    assert q(db, "SELECT blocked, blocked_until FROM source_budget WHERE source='rebrickable'") == [(1, '2026-10-25T12:00:25.000Z')]


def test_a_429_without_a_time_waits_sixty_seconds_and_blocks_the_whole_source(db):
    first = rebrickable_job(db)
    r = jobs.run(db, first, http=Net(rb=lambda url, headers: (429, {'detail': 'slow down'})), now=T0)
    assert r['retry_at'] == '2026-10-25T12:01:00.000Z'
    second, net = rebrickable_job(db, 'NEW-2'), Net(rb=rebrickable())
    r = jobs.run(db, second, http=net, now=T0 + timedelta(seconds=30))
    assert (r['state'], r['retry_at'], r['attempts']) == ('waiting_for_budget', '2026-10-25T12:01:00.000Z', 0) and net.urls == []
    other = jobs.run(db, bricklink_job(db), http=Net(), now=T0 + timedelta(seconds=30))                  # BrickLink is not blocked
    assert other['state'] == 'done'
    assert [x['id'] for x in jobs.drain(db, now=T0 + timedelta(seconds=61), http=Net(rb=lambda u, h: (404, {})))] == [first, second]


def test_a_bricklink_429_in_the_reply_meta_is_a_rate_wait_too(db):
    r = jobs.run(db, bricklink_job(db), http=Net(bl=(200, {'meta': {'code': 429, 'message': 'RATE_LIMIT'}})), now=T0)
    assert (r['state'], r['retry_at'], r['error_code']) == ('waiting_for_budget', '2026-10-25T12:01:00.000Z', 'budget')


# ---------- error codes ----------

def failed(r, code, text=''):
    assert (r['state'], r['error_code'], r['retry_at']) == ('failed', code, None), r
    assert text in r['error'] and r['step']['error_code'] == code
    return r


def test_a_missing_key_fails_before_any_call(db, monkeypatch):
    net = Net(rb=rebrickable())
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    failed(jobs.run(db, rebrickable_job(db), http=net, now=T0), 'source_not_configured', 'not configured')
    monkeypatch.delenv('BW_BRICKLINK_TOKEN_SECRET')
    failed(jobs.run(db, bricklink_job(db), http=net, now=T0), 'source_not_configured', 'not configured')
    assert net.urls == [] and used(db) == [] and used(db, 'rebrickable') == []


@pytest.mark.parametrize('status', [401, 403])
def test_a_refused_key_is_source_not_configured(db, status):
    failed(jobs.run(db, rebrickable_job(db), http=Net(rb=Fake(set_status=status)), now=T0), 'source_not_configured', 'refused the key')
    bl = (status, {'meta': {'code': status, 'message': 'TOKEN_INVALID'}})
    failed(jobs.run(db, bricklink_job(db), http=Net(bl=bl), now=T0), 'source_not_configured', 'refused the key')


def test_a_bricklink_ip_mismatch_has_its_own_message(db):
    bl = (401, {'meta': {'code': 401, 'message': 'TOKEN_IP_MISMATCHED', 'description': 'x'}})
    failed(jobs.run(db, bricklink_job(db), http=Net(bl=bl), now=T0), 'source_not_configured', 'IP mismatch')


def test_a_bricklink_signature_or_clock_problem_is_a_retried_source_error(db):
    bl = (401, {'meta': {'code': 401, 'message': 'BAD_OAUTH_REQUEST', 'description': 'timestamp'}})
    r = jobs.run(db, bricklink_job(db), http=Net(bl=bl), now=T0)
    assert (r['state'], r['error_code'], r['retry_at']) == ('failed', 'source_error', '2026-10-25T12:01:00.000Z')


def test_a_missing_set_is_not_found(db):
    failed(jobs.run(db, rebrickable_job(db), http=Net(rb=Fake(set_status=404)), now=T0), 'not_found')
    failed(jobs.run(db, bricklink_job(db), http=Net(bl=(404, {'meta': {'code': 404}})), now=T0), 'not_found', '6081-1')
    failed(jobs.run(db, bricklink_job(db), http=Net(bl=(200, {'meta': {'code': 404}})), now=T0), 'not_found')


def test_an_invalid_reply_is_invalid_reply_and_stores_nothing(db):
    failed(jobs.run(db, bricklink_job(db), http=Net(bl=(200, {'meta': {'code': 200}, 'data': 'x'})), now=T0), 'invalid_reply', 'invalid BrickLink')
    failed(jobs.run(db, bricklink_job(db), http=Net(bl=(200, reply())), now=T0), 'invalid_reply', 'empty')
    bad = Fake(set_parts=[part('3023')])
    bad.data[f'/sets/{SET}/parts/'] = [{'part': 'x', 'color': {}, 'quantity': 1, 'is_spare': False}]
    failed(jobs.run(db, rebrickable_job(db), http=Net(rb=bad), now=T0), 'invalid_reply', 'no part or colour')
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)]


def test_a_list_the_store_refuses_is_invalid_reply_not_a_retry(db):
    unknown_colour = Fake(set_parts=[part('3023', 8888)])
    failed(jobs.run(db, rebrickable_job(db), http=Net(rb=unknown_colour), now=T0), 'invalid_reply', 'download today')
    assert q(db, 'SELECT count(*) FROM main.item WHERE id>=1000000000') == [(0,)]


def test_a_set_that_joined_the_catalogue_while_queued_is_not_fetched(db, world):
    job = rebrickable_job(db)
    with closing(sqlite3.connect(world[1])) as c:
        c.execute("INSERT INTO item(id, kind, kind_source, name, name_key, size_key, year, num_parts, build_id, born_provider, born_namespace,"
                  " born_key, digest) VALUES(30, 'set', 'namespace', 'Now here', 'now here', '', 2026, 4, 1, 'rebrickable', 'sets', ?, 'd')", (SET,))
        c.commit()
    net = Net(rb=rebrickable())
    failed(jobs.run(db, job, http=net, now=T0), 'invalid_reply', 'catalogue has this set')
    assert net.urls == []


def test_a_set_without_a_bricklink_key_is_unidentified_and_costs_no_call(db):
    net = Net()
    job = jobs.queue(db, 'bricklink_subsets', item_id=NO_LINK_SET, payload='7777-1', via='cli', now=T0)
    failed(jobs.run(db, job, http=net, now=T0), 'unidentified', 'no BrickLink number')
    assert net.urls == [] and used(db) == []


# ---------- retries of transient failures ----------

def test_a_transient_failure_is_retried_with_growing_pauses_and_then_stops(db):
    job = bricklink_job(db)
    net = Net(bl=lambda url: (500, {}))
    t, pauses = T0, []
    for attempt in range(1, jobs.MAX_ATTEMPTS + 1):
        r = jobs.run(db, job, http=net, now=t)
        assert (r['state'], r['error_code'], r['attempts']) == ('failed', 'source_error', attempt)
        if attempt < jobs.MAX_ATTEMPTS:
            assert jobs.run(db, job, http=net, now=t)['ran'] is False                  # not before the retry time
            pauses.append(datetime.fromisoformat(r['retry_at'].replace('Z', '+00:00')) - t)
            t = datetime.fromisoformat(r['retry_at'].replace('Z', '+00:00'))
    assert pauses == [timedelta(minutes=m) for m in (1, 5, 15, 60)]
    assert r['retry_at'] is None and 'gave up after 5 attempts' in r['error']
    assert jobs.drain(db, now=t + timedelta(days=1), http=net) == [] and len(net.urls) == 5
    assert used(db) == [('2026-10-25', 5)]


def test_drain_retries_a_failed_job_when_its_time_has_come_and_it_can_succeed(db):
    job = bricklink_job(db)
    r = jobs.run(db, job, http=Net(bl=lambda url: (502, {})), now=T0)
    assert r['retry_at'] == '2026-10-25T12:01:00.000Z'
    assert jobs.drain(db, now=T0 + timedelta(seconds=59), http=Net()) == []
    (r,) = jobs.drain(db, now=T0 + timedelta(seconds=61), http=Net())
    assert (r['state'], r['attempts'], r['error'], r['error_code'], r['retry_at']) == ('done', 2, None, None, None)


def test_a_network_error_is_retried(db):
    def down(url, headers):
        raise ra.FetchError('Rebrickable call failed: URLError')
    r = jobs.run(db, rebrickable_job(db), http=down, now=T0)
    assert (r['state'], r['error_code'], r['retry_at']) == ('failed', 'source_error', '2026-10-25T12:01:00.000Z')
    assert r['error'] == 'Rebrickable call failed: URLError'


def test_no_key_value_reaches_a_job_row(db):
    jobs.run(db, bricklink_job(db), http=Net(bl=(500, {'meta': {'message': 'ck-secret-1'}})), now=T0)
    rows = db.execute('SELECT * FROM job').fetchall() + db.execute('SELECT * FROM job_step').fetchall()
    dump = ' '.join(str(tuple(r)) for r in rows)
    assert dump and not any(v in dump for v in KEYS.values())


# ---------- owners ----------

def dead_pid():
    p = subprocess.Popen(['true'])
    p.wait()
    return p.pid


def test_a_dead_owners_claim_is_taken_over(db):
    job = bricklink_job(db)
    db.execute("UPDATE job SET state='running', attempts=1 WHERE id=?", (job,))
    db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, ?, ?)', (job, dead_pid(), '2026-10-25T11:00:00.000Z'))
    db.commit()
    r = jobs.run(db, job, http=Net(), now=T0)
    assert (r['ran'], r['state'], r['attempts']) == (True, 'done', 2) and q(db, 'SELECT count(*) FROM job_owner') == [(0,)]


def test_a_live_owners_claim_is_left_alone(db):
    job = bricklink_job(db)
    db.execute("UPDATE job SET state='running', attempts=1 WHERE id=?", (job,))
    db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, ?, ?)', (job, os.getppid(), '2026-10-25T11:00:00.000Z'))
    db.commit()
    net = Net()
    r = jobs.run(db, job, http=net, now=T0)
    assert (r['ran'], r['state'], r['attempts']) == (False, 'running', 1) and net.urls == []
    assert jobs.drain(db, now=T0, http=net) == [] and q(db, 'SELECT pid FROM job_owner') == [(os.getppid(),)]


def test_this_pid_is_alive_only_while_this_process_holds_the_job(db):
    job = bricklink_job(db)
    db.execute("UPDATE job SET state='running' WHERE id=?", (job,))
    db.execute('INSERT INTO job_owner(job_id, pid, claimed_at) VALUES(?, ?, ?)', (job, os.getpid(), '2026-10-25T11:00:00.000Z'))
    db.commit()
    assert jobs.run(db, job, http=Net(), now=T0)['state'] == 'done'                  # a stale row of a restarted process with a reused pid


def test_an_interrupt_leaves_the_job_running_without_a_claim(db):
    job = bricklink_job(db)
    def interrupted(url, headers):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        jobs.run(db, job, http=interrupted, now=T0)
    assert jobs.status(db, job)['state'] == 'running' and q(db, 'SELECT count(*) FROM job_owner') == [(0,)]
    assert jobs.run(db, job, http=Net(), now=T0)['state'] == 'done'


def test_a_bug_marks_the_job_failed_and_is_raised(db, monkeypatch):
    job = bricklink_job(db)
    monkeypatch.setattr(jobs.bricklink_subsets, 'load_subsets', lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        jobs.run(db, job, http=Net(), now=T0)
    s = jobs.status(db, job)
    assert (s['state'], s['error_code'], s['retry_at']) == ('failed', 'source_error', None) and 'ZeroDivisionError' in s['error']
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)] and q(db, 'SELECT count(*) FROM job_owner') == [(0,)]


# ---------- drain ----------

def many(url, headers):
    path = url.split('/api/v3/lego')[1].split('?')[0]
    if path.count('/') == 3 and path.startswith('/sets/'):
        return 200, {'set_num': path.split('/')[2], 'name': 'Another', 'year': 2026, 'num_parts': 1}
    return 200, {'count': 1, 'next': None, 'previous': None, 'results': [part('3023', 4)] if 'parts' in path else []}


def test_drain_runs_the_oldest_first_and_stops_at_the_limit(db):
    ids = [rebrickable_job(db, f'NEW-{n}') for n in (1, 2, 3)]
    net = Net(rb=many)
    ran = jobs.drain(db, limit=2, now=T0, http=net)
    assert [r['id'] for r in ran] == ids[:2] and [r['state'] for r in ran] == ['done', 'done']
    assert [u.split('/sets/')[1].split('/')[0] for u in net.urls if u.endswith('/')] == ['NEW-1', 'NEW-2']
    assert jobs.status(db, ids[2])['state'] == 'queued'
    assert [r['id'] for r in jobs.drain(db, now=T0, http=net)] == [ids[2]]
    assert jobs.drain(db, now=T0, http=net) == []


def test_drain_skips_jobs_that_are_waiting_failed_for_good_or_done(db, monkeypatch):
    waiting, final = bricklink_job(db), rebrickable_job(db)
    jobs.run(db, final, http=Net(rb=Fake(set_status=404)), now=T0)
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    db.execute("INSERT INTO source_budget(source, day, used) VALUES('bricklink', '2026-10-25', 1)")
    db.commit()
    jobs.run(db, waiting, http=Net(), now=T0)
    assert jobs.status(db, waiting)['state'] == 'waiting_for_budget'
    assert jobs.drain(db, now=T0, http=Net()) == []
    assert [j['state'] for j in jobs.list_jobs(db)] == ['waiting_for_budget', 'failed']
    assert [j['id'] for j in jobs.list_jobs(db, states=('failed',))] == [final]


def test_what_m6_reads_the_job_state_and_the_fetched_list_by_job_id(db):
    job = bricklink_job(db)
    assert jobs.status(db, job)['state'] == 'queued'
    jobs.drain(db, now=T0, http=Net())
    assert jobs.status(db, job)['state'] == 'done'
    assert q(db, 'SELECT item_id, source, seq, is_latest FROM main.fetched_inventory WHERE job_id=?', job) == [(10, 'bricklink', 1, 1)]


def test_a_reply_without_results_is_invalid_and_not_retried(db):
    def broken(url, headers):
        return (200, {'count': 1}) if '/parts/' in url else rebrickable(figures=0)(url, headers)
    s = jobs.run(db, rebrickable_job(db), http=Net(rb=broken), now=T0)
    assert (s['state'], s['error_code'], s['retry_at']) == ('failed', 'invalid_reply', None)


def test_a_shorter_throttle_never_cuts_a_longer_pause(db):
    job = bricklink_job(db)
    def throttled(url):                                         # an overlapping call records a long pause while this one is out
        db.execute("INSERT INTO source_budget(source, day, blocked, blocked_until) VALUES('bricklink', '2026-10-25', 1, '2026-10-25T13:00:00.000Z')"
                   " ON CONFLICT(source, day) DO UPDATE SET blocked=1, blocked_until=excluded.blocked_until")
        db.commit()
        return 429, {'meta': {'code': 429}}                     # this one names no time: 60 s
    jobs.run(db, job, http=Net(bl=throttled), now=T0)
    assert q(db, "SELECT blocked_until FROM source_budget WHERE source='bricklink'") == [('2026-10-25T13:00:00.000Z',)]


def test_a_link_changed_during_the_call_is_asked_again(db):
    job = bricklink_job(db)
    def moved(url):
        db.execute("UPDATE main.item_link SET provider_key='6081-2' WHERE item_id=? AND provider_kind='S'", (CATALOGUE_SET,))
        db.commit()
        return 200, reply(entry('3023', 5, 1))
    s = jobs.run(db, job, http=Net(bl=moved), now=T0)
    assert (s['state'], s['error_code']) == ('failed', 'source_error') and s['retry_at'] is not None
    assert q(db, 'SELECT count(*) FROM main.fetched_inventory') == [(0,)]
