"""API v2 jobs (M.11d, issue #113): listing and reading, retry, resume, drain, and the queueing operations. Ported from test_bw_api_m5 (jobs),
test_bw_api_jobs_followup and the price refresh of test_bw_api_47 onto the 4.0 `job` tables. Mocked transports only."""
from contextlib import closing
from datetime import datetime, timezone
import json

import pytest

from brickwork.core import pipeline
from brickwork.core.connect import connect
from brickwork.core.pipeline import Pipeline
from tests.api2 import BL_ENV, bl, call, events, fake, row, rows, secret, stored_token, v2, validate, wire, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def queue(pair, item, steps=('identity',), via='api'):
    with closing(connect(pair)) as db:
        db.execute('BEGIN IMMEDIATE')
        job = Pipeline(db).queue_steps(item, list(steps), via=via, actor='bootstrap' if via == 'api' else None)
        db.commit()
    return job


def sql(pair, statement, params=()):
    with closing(connect(pair)) as db, db:
        db.execute(statement, params)


# ---------- reads ----------

def test_jobs_are_listed_newest_first_with_steps_and_filters(v2, world, pair):
    first, second = queue(pair, world.brick), queue(pair, world.plate, ('identity', 'matching'))
    sql(pair, "UPDATE job_step SET state='failed', error='boom', error_code='source_error' WHERE job_id=? AND name='identity'", (first,))
    sql(pair, "UPDATE job SET state='failed', error='boom', error_code='source_error' WHERE id=?", (first,))
    listed = call(v2, '/jobs')
    validate(listed, 'get_jobs')
    assert [j['id'] for j in listed.json['data']] == [second, first]
    assert [s['name'] for s in listed.json['data'][0]['steps']] == ['identity', 'matching'] and listed.json['data'][0]['item']['id'] == world.plate
    assert [j['id'] for j in call(v2, '/jobs?failed=true').json['data']] == [first]
    assert [j['id'] for j in call(v2, '/jobs?failed=false').json['data']] == [second]
    assert [j['id'] for j in call(v2, '/jobs?state=queued').json['data']] == [second]
    assert [j['id'] for j in call(v2, '/jobs?direction=asc').json['data']] == [first, second]
    assert call(v2, '/jobs?state=weird').status_code == 400 and call(v2, '/jobs?failed=maybe').status_code == 400
    page = call(v2, '/jobs?limit=1')
    assert len(page.json['data']) == 1 and call(v2, '/jobs?limit=1&cursor=' + page.json['page']['next_cursor']).json['data'][0]['id'] == first
    one = call(v2, f'/jobs/{first}')
    validate(one, 'get_jobs_by_id')
    assert one.json['data']['steps'][0]['error_code'] == 'source_error' and one.json['data']['interrupted'] is False
    assert call(v2, '/jobs/999').status_code == 404 and call(v2, '/jobs/x').status_code == 404
    assert call(v2, '/jobs', token=stored_token(pair, ['read'])).status_code == 200


# ---------- drain, retry, resume ----------

def test_drain_runs_the_due_jobs_in_the_request_and_replays(v2, world, secret, wire, pair, monkeypatch):
    job = queue(pair, world.brick)
    before = len(events(pair))
    response = write(v2, '/jobs/drain', key='drain-one')
    validate(response, 'post_jobs_drain')
    assert response.json['data']['jobs'][0]['id'] == job and response.json['data']['jobs'][0]['state'] == 'done'
    assert len([e for e in events(pair, 'id>?', (before,)) if e['entity_kind'] == 'bw_api']) == 1
    assert write(v2, '/jobs/drain', key='drain-one').json['idempotent_replay'] is True
    assert write(v2, '/jobs/drain', body={'x': 1}).status_code == 400
    assert write(v2, '/jobs/drain', token=stored_token(pair, ['read'], 'r')).status_code == 403


def test_a_failed_step_is_retried_and_the_job_is_resumed(v2, world, secret, wire, pair):
    job = queue(pair, world.brick, ('identity',))
    sql(pair, "UPDATE job SET state='failed', error='boom', error_code='source_error' WHERE id=?", (job,))
    sql(pair, "UPDATE job_step SET state='failed', error='boom', error_code='source_error' WHERE job_id=?", (job,))
    retried = write(v2, f'/jobs/{job}/retry', body={'step': 'identity'}, key='retry-one')
    assert retried.status_code == 202, retried.text
    validate(retried, 'post_jobs_by_id_retry', '202')
    assert retried.headers['Location'] == f'/api/v2/jobs/{job}' and retried.json['data']['state'] == 'queued' and retried.json['data']['steps'][0]['state'] == 'queued'
    assert write(v2, f'/jobs/{job}/retry', body={'step': 'identity'}, key='retry-one').json['idempotent_replay'] is True
    assert write(v2, f'/jobs/{job}/retry').status_code == 409                       # nothing failed any more
    assert write(v2, f'/jobs/{job}/retry', body={'step': 'nonsense'}).status_code == 422
    assert write(v2, '/jobs/9999/retry').status_code == 404
    resumed = write(v2, f'/jobs/{job}/resume')
    assert resumed.status_code == 202 and resumed.headers['Location'] == f'/api/v2/jobs/{job}'
    validate(resumed, 'post_jobs_by_id_resume', '202')
    sql(pair, "UPDATE job SET state='done' WHERE id=?", (job,))
    assert write(v2, f'/jobs/{job}/resume').status_code == 409                      # done is not resumable
    assert write(v2, f'/jobs/{job}/retry').status_code == 409


def test_a_job_whose_worker_died_is_interrupted_and_resumable(v2, world, pair):
    job = queue(pair, world.brick)
    sql(pair, "UPDATE job SET state='running' WHERE id=?", (job,))
    assert call(v2, f'/jobs/{job}').json['data']['interrupted'] is True
    assert write(v2, f'/jobs/{job}/resume').status_code == 202
    assert write(v2, f'/jobs/{job}/retry').status_code == 409                       # interrupted, nothing failed


def test_a_job_waiting_for_its_budget_may_be_resumed(v2, world, pair):
    job = queue(pair, world.brick, ('identity',))
    sql(pair, "UPDATE job SET state='waiting_for_budget', retry_at='2999-01-01T00:00:00.000Z' WHERE id=?", (job,))
    waiting = call(v2, f'/jobs/{job}').json['data']
    assert waiting['state'] == 'waiting_for_budget' and datetime.fromisoformat(waiting['retry_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc)
    resumed = write(v2, f'/jobs/{job}/resume')
    assert resumed.status_code == 202 and resumed.json['data']['state'] == 'waiting_for_budget'


def test_only_the_pipeline_jobs_are_retried_or_resumed(v2, world, pair):
    sql(pair, "INSERT INTO job(source,kind,state,via,created_at,updated_at) VALUES('rebrickable','rebrickable_set','failed','app','2026-10-28T00:00:00.000Z','2026-10-28T00:00:00.000Z')")
    fetch = row(pair, "SELECT id FROM job WHERE kind='rebrickable_set'")['id']
    assert call(v2, f'/jobs/{fetch}').status_code == 200
    assert write(v2, f'/jobs/{fetch}/retry').status_code == 404 and write(v2, f'/jobs/{fetch}/resume').status_code == 404


# ---------- queueing ----------

def test_booklets_without_a_pdf_queue_their_identity_step(v2, world, coll, pair):
    booklet = coll.local('instructions', 'Synthetic booklet', born_key='BK-1')
    other = coll.local('instructions', 'Numberless booklet')
    response = write(v2, '/jobs/instruction-identities')
    assert response.status_code == 202, response.text
    validate(response, 'post_jobs_instruction_identities', '202')
    jobs = response.json['data']['jobs']
    assert sorted(j['item']['id'] for j in jobs) == sorted([booklet, world.local_booklet]) and [s['name'] for s in jobs[0]['steps']] == ['identity'] and response.json['data']['skipped'] == [str(other)]
    assert write(v2, '/jobs/instruction-identities').json['data']['jobs'] == []         # a live job is not queued twice


def test_a_picture_refresh_queues_one_job_per_held_item_and_not_twice(v2, world, pair):
    body = {'scope': 'all', 'kinds': ['part', 'set']}
    count = len(call(v2, '/jobs').json['data'])
    queued = write(v2, '/jobs/pictures', body=body, key='pics-1')
    assert queued.status_code == 202, queued.text
    validate(queued, 'post_jobs_pictures', '202')
    jobs = queued.json['data']['jobs']
    assert jobs and all(j['kind'] == 'item' and [s['name'] for s in j['steps']] == ['pictures'] and j['state'] == 'queued' for j in jobs)
    assert len(call(v2, '/jobs?limit=200').json['data']) == count + len(jobs)
    assert (row(pair, "SELECT via, actor FROM job WHERE id=?", (jobs[0]['id'],))) == {'via': 'api', 'actor': 'bootstrap'}
    again = write(v2, '/jobs/pictures', body=body, key='pics-2')
    assert again.status_code == 202 and again.json['data']['jobs'] == []                 # the live jobs are reused
    stale = write(v2, '/jobs/pictures', body={'scope': 'missing', 'kinds': ['part'], 'expected_count': 999})
    assert stale.status_code == 422
    for bad in ({}, {'scope': 'sometimes'}, {'scope': 'all', 'kinds': []}, {'scope': 'all', 'kinds': ['sock']}, {'scope': 'all', 'extra': 1}):
        assert write(v2, '/jobs/pictures', body=bad).status_code == 422, bad


def test_an_item_import_queues_its_steps_and_an_item_refresh_reuses_a_live_job(v2, world, pair):
    made = write(v2, f'/items/{world.brick}/import', body={'steps': ['identity', 'market_price']})
    assert made.status_code == 202, made.text
    validate(made, 'post_items_by_id_import', '202')
    assert [s['name'] for s in made.json['data']['steps']] == ['identity', 'market_price'] and made.headers['Location'] == f"/api/v2/jobs/{made.json['data']['id']}"
    default = write(v2, f'/items/{world.plate}/import', body={})
    assert [s['name'] for s in default.json['data']['steps']] == list(pipeline.STEPS)
    for bad in ({'steps': []}, {'steps': ['nonsense']}, {'steps': ['identity', 'identity']}, {'sources': ['bricklink']}):
        assert write(v2, f'/items/{world.brick}/import', body=bad).status_code == 422, bad
    assert write(v2, '/items/99999/import', body={}).status_code == 404
    refresh = write(v2, f'/items/{world.keep}/prices/refresh', body={}, key='first-refresh')
    assert refresh.status_code == 202
    validate(refresh, 'post_items_by_id_prices_refresh', '202')
    again = write(v2, f'/items/{world.keep}/prices/refresh', body={}, key='second-refresh')
    assert again.json['data']['id'] == refresh.json['data']['id'] and again.headers['Location'] == refresh.headers['Location']
    sql(pair, "UPDATE job SET state='done' WHERE id=?", (refresh.json['data']['id'],))
    third = write(v2, f'/items/{world.keep}/prices/refresh', body={})
    assert third.json['data']['id'] != refresh.json['data']['id'] and [s['name'] for s in third.json['data']['steps']] == ['market_price']
    assert write(v2, f'/items/{world.keep}/prices/refresh', body={'x': 1}).status_code == 422


def test_the_bulk_price_refresh_queues_the_stale_items_once(v2, world, pair):
    made = write(v2, '/prices/refresh', key='refresh-1')
    assert made.status_code == 200, made.text
    validate(made, 'post_prices_refresh')
    jobs = made.json['data']['jobs']
    assert made.json['data']['skipped'] == [] and all([s['name'] for s in j['steps']] == ['market_price'] for j in jobs)
    assert write(v2, '/prices/refresh').json['data']['jobs'] == [] if jobs else True
    assert write(v2, '/prices/refresh', token=stored_token(pair, ['read'], 'r')).status_code == 403
