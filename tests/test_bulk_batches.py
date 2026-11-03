"""#127: a bulk refresh is one batch. The drain runs interactive work (an Add's job, a single Update, an Add's part-list fetch) ahead of
it, the per-source budgets still hold for its items, Cancel stops what is left, and Jobs shows it as one row with progress and failures."""
import json

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, pipeline
from brickwork.core.pipeline import Pipeline, StepFailed, StepWait
from brickwork.core.transaction import transaction
from brickwork.store4 import jobs as fetch_jobs
from tests.app4 import app4, client, coll, csrf, pair, world  # noqa: F401 (fixtures)

STEP = 'market_price'


def bulk(coll, item_ids):
    """A bulk price refresh of the items: one batch."""
    return admin.queue_refresh(coll.db, [{'item_id': i} for i in item_ids])


def single(coll, item_id):
    """A single Update, as the item page queues it: no batch."""
    with transaction(coll.db):
        return Pipeline(coll.db).queue_steps(item_id, [STEP], via='app')


def runner(coll, calls, *, wait_for=(), fail_for=()):
    """A pipeline whose market price handler only records the order it was called in (no network)."""
    def handler(db, job, step):
        calls.append(job['item_id'])
        if job['item_id'] in wait_for:
            raise StepWait('2999-01-01T00:00:00.000Z', 'BrickLink budget used up for today')
        if job['item_id'] in fail_for:
            raise StepFailed('not_found', 'BrickLink says: no price guide')
    kinds = {r[0] for r in coll.db.execute('SELECT DISTINCT kind FROM item')}
    sources = {s for kind in kinds for s in pipeline.sources_for(coll.db, STEP, kind)}
    return Pipeline(coll.db, handlers={(STEP, s): handler for s in sources})


def batch_of(coll, job):
    return json.loads(coll.db.execute('SELECT payload FROM job WHERE id=?', (job,)).fetchone()[0]).get('batch')


def test_a_bulk_refresh_is_one_batch_and_a_single_update_is_none(world, coll):
    jobs = bulk(coll, [world.keep, world.gate, world.duplo, world.brick])
    assert len(jobs) == 4 and len({batch_of(coll, j) for j in jobs}) == 1 and batch_of(coll, jobs[0]).startswith('prices-')
    assert batch_of(coll, single(coll, world.plate)) is None


def test_interactive_work_queued_during_a_batch_runs_before_the_rest_of_it(world, coll):
    bulk(coll, [world.keep, world.gate, world.duplo, world.brick])
    calls = []
    runner(coll, calls).drain(limit=1)                                        # the batch has started
    assert calls == [world.keep]
    single(coll, world.plate)                                                 # an Update arrives mid-refresh
    runner(coll, calls).drain(limit=1)
    assert calls == [world.keep, world.plate]                                 # it goes next, not after the three left
    runner(coll, calls).drain()
    assert calls == [world.keep, world.plate, world.gate, world.duplo, world.brick]


def test_a_waiting_fetch_job_ends_the_pass_before_a_batch_job_but_not_before_an_interactive_one(world, coll):
    bulk(coll, [world.keep, world.gate])
    single(coll, world.plate)
    fetch_jobs.queue(coll.db, 'rebrickable_set', item_id=world.duplo, payload='2070-1', via='app')      # an Add's part list
    calls = []
    runner(coll, calls).drain()
    assert calls == [world.plate]                                             # the Update ran; the batch waits for the fetch
    coll.db.execute("UPDATE job SET state='done' WHERE kind='rebrickable_set'")
    coll.db.commit()
    runner(coll, calls).drain()
    assert calls == [world.plate, world.keep, world.gate]


def test_the_budget_still_holds_for_a_batchs_items_and_the_rest_goes_on(world, coll):
    jobs = bulk(coll, [world.keep, world.gate, world.duplo])
    calls = []
    runner(coll, calls, wait_for={world.gate}).drain()
    assert calls == [world.keep, world.gate, world.duplo]
    states = {j: coll.db.execute('SELECT state FROM job WHERE id=?', (j,)).fetchone()[0] for j in jobs}
    assert list(states.values()) == ['done', 'waiting_for_budget', 'done']
    runner(coll, calls, wait_for={world.gate}).drain()
    assert calls == [world.keep, world.gate, world.duplo]                     # not before its budget is back
    found = pipeline.batches(coll.db)[0]
    assert (found['total'], found['done'], found['waiting'], found['state']) == (3, 2, 1, 'waiting_for_budget')


def test_cancel_stops_what_is_left_and_nothing_of_it_runs_again(world, coll):
    jobs = bulk(coll, [world.keep, world.gate, world.duplo, world.brick])
    calls = []
    runner(coll, calls).drain(limit=1)
    batch = batch_of(coll, jobs[0])
    assert pipeline.cancel_batch(coll.db, batch) == 3
    runner(coll, calls).drain()
    assert calls == [world.keep]
    found = pipeline.batches(coll.db)[0]
    assert (found['done'], found['cancelled'], found['failed'], found['state']) == (1, 3, 0, 'cancelled')
    assert pipeline.cancel_batch(coll.db, batch) == 0
    assert coll.db.execute("SELECT count(*) FROM event WHERE entity_kind='job' AND field='cancelled'").fetchone()[0] == 1


def soup(client, route):
    response = client.get(route)
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def test_jobs_shows_a_batch_as_one_row_with_progress_failures_and_cancel(world, coll, client):
    jobs = bulk(coll, [world.keep, world.gate, world.duplo, world.brick])
    single(coll, world.plate)
    runner(coll, [], fail_for={world.gate}).drain(limit=3)                    # the single Update, then keep and gate of the batch
    page = soup(client, '/manage/jobs')
    rows = page.select('[data-bw-batches] [data-batch]')
    assert len(rows) == 1 and rows[0]['data-batch'] == batch_of(coll, jobs[0])
    assert rows[0].h2.get_text(' ', strip=True).startswith('Bulk refresh prices · 4 items')
    assert rows[0].select_one('[data-batch-counts]').get_text() == '1 of 4 done · 1 failed · 2 to go'
    assert rows[0].select_one('[role=progressbar]')['aria-valuenow'] == '2'
    failure = rows[0].select_one('[data-batch-failures] .bw-entry')
    assert 'no price guide' in failure.get_text()
    listed = {s['id'] for s in page.select('[data-bw-rows] [data-bw-row]')}
    assert not {f'job-{j}' for j in jobs} & listed                            # the batch's jobs are not rows of their own
    form = rows[0].select_one('[data-batch-cancel]').find_parent('form')
    response = client.post('/manage/jobs', data={i['name']: i['value'] for i in form.select('input')})
    assert response.status_code == 302
    row = soup(client, '/manage/jobs').select_one('[data-bw-batches] [data-batch]')
    assert '2 cancelled' in row.select_one('[data-batch-counts]').get_text() and not row.select('[data-batch-cancel]')


@pytest.mark.parametrize('batch', ['', 'prices', 'prices-XYZ', 'pictures-12345678; DROP'])
def test_cancel_refuses_a_batch_id_it_did_not_make(world, client, batch):
    response = client.post('/manage/jobs', data=dict(csrf_token=csrf(client), action='cancel_batch', batch=batch))
    assert response.status_code == 302 and 'Nothing was saved' in client.get('/manage/jobs').get_data(as_text=True)
