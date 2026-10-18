"""Import defaults and shared refresh deduplication regressions."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

import pytest

from brickwork.core import admin
from brickwork.core.connect import connect
from brickwork.core.importer.projection import PRIORITY
from tests.test_bw_api_m1 import app, call
from tests.test_bw_api_m2 import populated
from tests.test_bw_api_m3 import write, dbrows
from tests.test_bw_api_m1_contract import CONTRACT, validate


@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('step,item_type,sources', [
    (step, kind, sources)
    for step, types in PRIORITY.items() for kind, sources in types.items()
])
def test_import_accepts_every_step_default(populated, monkeypatch, step, item_type, sources, explicit):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    kind, number = ('P', '3001') if item_type == 'P' else ('S', '100-1')
    # Import requires a catalogue entry even when the item is already stored.
    with sqlite3.connect(Path(os.environ['BW_DB_PATH']).with_name('bricklink-catalog.db')) as db:
        db.execute("INSERT OR IGNORE INTO items VALUES('P','3001','Synthetic brick','Synthetic',2025,'synthetic brick')")
    defaults = call(populated, '/settings').json['data']['source_priority'][step][item_type]
    assert defaults == sources
    body = {'steps': [step]}
    if explicit:
        body['sources'] = defaults
    validate(body, CONTRACT['components']['schemas']['ImportRequest'])
    response = write(populated, f'/items/{kind}/{number}/import', body=body)
    assert response.status_code == 202, response.text
    saved = [s for s in dbrows('import_steps') if s['job_id'] == response.json['data']['id']]
    assert len(saved) == 1 and saved[0]['name'] == step
    assert json.loads(saved[0]['sources']) == sources


def test_import_source_enum_matches_pipeline():
    expected = {s for types in PRIORITY.values() for sources in types.values() for s in sources}
    assert set(CONTRACT['components']['schemas']['ImportRequest']['properties']['sources']['items']['enum']) == expected


@pytest.mark.parametrize('sources', [[], ['unknown'], [{}], 'bricklink'])
def test_invalid_import_sources(populated, monkeypatch, sources):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    before = dbrows('jobs')
    response = write(populated, '/items/S/100-1/import', body={'sources': sources})
    assert response.status_code == 422
    assert dbrows('jobs') == before


@pytest.mark.parametrize('state', ['queued', 'running', 'waiting_for_budget'])
def test_refresh_reuses_live_job_and_bulk_skips(populated, monkeypatch, state):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    path = '/items/S/100-1/prices/refresh'
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE jobs SET state='done'")
    first = write(populated, path, body={}, key='first-refresh')
    assert first.status_code == 202, first.text
    identifier = first.json['data']['id']
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute('UPDATE jobs SET state=? WHERE id=?', (state, identifier))
    before = dbrows('jobs')
    again = write(populated, path, body={}, key='second-refresh')
    assert again.status_code == 202, again.text
    assert again.json['data']['id'] == identifier
    assert again.json['data']['state'] == state
    assert again.headers['Location'] == first.headers['Location']
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        assert admin.queue_refresh(db, [{'item_type': 'S', 'item_no': '100-1'}]) == []
    assert dbrows('jobs') == before


@pytest.mark.parametrize('state', ['done', 'failed'])
def test_refresh_replaces_finished_job(populated, monkeypatch, state):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute('UPDATE jobs SET state=?', (state,))
    before = len(dbrows('jobs'))
    response = write(populated, '/items/S/100-1/prices/refresh', body={})
    assert response.status_code == 202, response.text
    assert len(dbrows('jobs')) == before + 1
    steps = [s['name'] for s in dbrows('import_steps') if s['job_id'] == response.json['data']['id']]
    assert steps == ['market_price']
