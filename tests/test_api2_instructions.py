"""Instruction API and assistant tools use the same confirmed candidates."""
from contextlib import closing
from brickwork.core.connect import connect
from brickwork.core import instruction_sources as src, instructions as ins
from brickwork.core.pipeline import Pipeline
from tests.api2 import v2, call, write, validate, stored_token  # noqa: F401
from tests.app4 import app4, pair, coll  # noqa: F401
from tests.instruction_fakes import registry


def test_fetch_poll_download_retry(v2, coll, pair, monkeypatch, tmp_path):
    reg, fake = registry()
    monkeypatch.setattr(src, 'registry', reg)
    item = coll.item('sets', '1000-1')
    response = write(v2, '/instruction-files/fetch', body={'items': [{'id': item}], 'region': 'AT'})
    validate(response, 'post_instruction_files_fetch', '202')
    assert response.status_code == 202
    job = response.json['data']['jobs'][0]['id']
    assert not fake.calls
    with closing(connect(pair)) as db:
        Pipeline(db).run(job)
    response = call(v2, f'/jobs/{job}')
    validate(response, 'get_jobs_by_id')
    candidates = response.json['data']['instruction_search']['candidates']
    assert len(candidates) == 2 and not fake.calls
    response = write(v2, '/instruction-files/download', body={'candidate_ids': [candidates[0]['id']]})
    validate(response, 'post_instruction_files_download', '202')
    assert response.status_code == 202
    download = response.json['data']['id']
    fake.failure = OSError('invented offline')
    with closing(connect(pair)) as db:
        assert ins.Downloads(db, root=tmp_path).run(download)['state'] == 'failed'
    response = write(v2, f'/jobs/{download}/retry', body={})
    assert response.status_code == 202
    fake.failure = None
    with closing(connect(pair)) as db:
        assert ins.Downloads(db, root=tmp_path).run(download)['state'] == 'done'
    assert len(fake.calls) == 2


def test_invalid_ticks_and_write_scope(v2, pair):
    assert write(v2, '/instruction-files/download', body={'candidate_ids': []}).status_code == 422
    token = stored_token(pair, ['read'])
    assert call(v2, '/instruction-files/fetch', 'post', token=token, json={'items': [{'id': 1}]}).status_code == 403
