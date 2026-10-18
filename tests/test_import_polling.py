"""Live import progress by HTTP polling: real endpoint output drives the shipped widget."""
from contextlib import closing
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from brickwork.core.connect import connect
from brickwork.core.pipeline import Pipeline
from tests.test_bw_collection import bw
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, apps, logged_in

ROOT = Path(__file__).resolve().parents[1]


def make_job(db, steps):
    """Queue a job and force each of its steps into a state; return the job id."""
    job = Pipeline(db).queue_steps('S', 'new-set', ('inventory', 'pictures', 'market_price'), sources=['bricklink'])
    names = [r[0] for r in db.execute('SELECT name FROM import_steps WHERE job_id=? ORDER BY position', (job,))]
    for name, (state, count, total, error) in zip(names, steps):
        db.execute('UPDATE import_steps SET state=?,count=?,total=?,error=? WHERE job_id=? AND name=?',
                   (state, count, total, error, job, name))
    return job


def poll(client, job):
    response = client.get(f'/manage/add/jobs/{job}')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    return response.json


@pytest.fixture
def scenarios(app, bw):
    client = logged_in(app)
    with closing(connect(bw)) as db, db:
        running = make_job(db, [('done', 5, 5, None), ('running', 38, 112, None), ('queued', 0, 0, None)])
        db.execute("UPDATE jobs SET state='running' WHERE id=?", (running,))
        finished = make_job(db, [('done', 5, 5, None)] * 3)
        db.execute("UPDATE jobs SET state='done' WHERE id=?", (finished,))
        failed = make_job(db, [('done', 5, 5, None), ('failed', 0, 0, 'Fixture failure'), ('queued', 0, 0, None)])
        db.execute("UPDATE jobs SET state='failed' WHERE id=?", (failed,))
        waiting = make_job(db, [('done', 5, 5, None), ('waiting_for_budget', 10, 100, None), ('queued', 0, 0, None)])
        db.execute("UPDATE jobs SET state='waiting_for_budget' WHERE id=?", (waiting,))
    return client, dict(running=running, finished=finished, failed=failed, waiting=waiting), bw


def run_widget(tmp_path, data):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable')
    path = tmp_path / 'events.json'
    path.write_text(json.dumps(data))
    result = subprocess.run([node, str(ROOT / 'tests/import_polling_e2e.cjs'), str(path)],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_polled_events_never_expose_payloads_or_keys(scenarios):
    client, jobs, _ = scenarios
    for job in jobs.values():
        text = json.dumps(poll(client, job))
        assert 'payload' not in text and 'key' not in text.lower().replace('keeps', '')


def test_widget_follows_running_finished_failed_and_waiting_jobs(scenarios, tmp_path):
    client, jobs, _ = scenarios
    data = {name: dict(job=job, polls=[poll(client, job)], click=name == 'failed') for name, job in jobs.items()}
    out = run_widget(tmp_path, data)
    # Running: two of three steps' worth of finished work plus 38 of 112 on the active step.
    assert 33 < out['running']['width'] < 56 and out['running']['retryHidden'] is True
    assert out['finished']['width'] == 100 and out['finished']['message'] == 'Import complete'
    assert out['finished']['retryHidden'] is True
    assert out['failed']['retryHidden'] is False and out['failed']['retried'] == [[jobs['failed'], 'pictures']]
    assert 'attention' in out['failed']['message']
    assert out['waiting']['retryHidden'] is True and 'budget' in out['waiting']['message'].lower()


def test_failed_job_retried_then_finishes_in_later_polls(scenarios, tmp_path):
    client, jobs, bw = scenarios
    job = jobs['failed']
    first = poll(client, job)
    with client.session_transaction() as session:
        csrf = session.get('bw_add_csrf')
    if csrf is None:
        client.get('/manage/add')
        with client.session_transaction() as session:
            csrf = session['bw_add_csrf']
    assert client.post(f'/manage/add/jobs/{job}/retry', json={'csrf_token': csrf, 'step': 'pictures'}).status_code == 200
    queued = poll(client, job)
    with closing(connect(bw)) as db, db:
        db.execute("UPDATE import_steps SET state='done',error=NULL,count=3,total=3 WHERE job_id=?", (job,))
        db.execute("UPDATE jobs SET state='done' WHERE id=?", (job,))
    done = poll(client, job)
    out = run_widget(tmp_path, {
        'retry-visible': dict(job=job, polls=[first]),
        'queued-clears-failure': dict(job=job, polls=[first, queued]),
        'finished': dict(job=job, polls=[first, queued, done])})
    assert out['retry-visible']['retryHidden'] is False
    assert out['queued-clears-failure']['retryHidden'] is True
    assert out['finished']['retryHidden'] is True and out['finished']['width'] == 100
    assert out['finished']['message'] == 'Import complete'


def test_unknown_job_is_404_and_login_is_required(scenarios, app):
    client, jobs, _ = scenarios
    assert client.get('/manage/add/jobs/99999').status_code == 404
    anonymous = app.test_client().get(f"/manage/add/jobs/{jobs['running']}")
    assert anonymous.status_code == 302 and '/login' in anonymous.location
