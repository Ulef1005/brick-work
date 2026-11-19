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


def test_fetch_rejects_an_unknown_region(v2, coll):
    item = coll.item('sets', '1000-1')
    response = write(v2, '/instruction-files/fetch', body={'items': [{'id': item}], 'region': 'XX'})
    assert response.status_code == 422 and 'region' in str(response.json).lower()


def test_instruction_links_for_a_set(v2, coll):
    item = coll.item('sets', '1000-1')
    response = call(v2, f'/items/{item}/instruction-links')
    validate(response, 'get_items_by_id_instruction_links')
    data = response.json['data']
    assert data['set_no'] == '1000-1' and data['region'] == 'DE'
    assert [(link['source'], link['url']) for link in data['links']] == [
        ('lego', 'https://www.lego.com/de-de/service/building-instructions/1000?age-gate=grown_up'), ('rebrickable', 'https://rebrickable.com/sets/1000-1/')]
    response = call(v2, f'/items/{item}/instruction-links?region=AT')
    assert response.json['data']['region'] == 'AT' and '/en-gb/' in response.json['data']['links'][0]['url']


def test_instruction_links_refuse_what_they_cannot_link(v2, coll):
    item = coll.item('sets', '1000-1')
    assert call(v2, f'/items/{item}/instruction-links?region=XX').status_code == 422
    assert call(v2, '/items/999999/instruction-links').status_code == 404
    part = coll.item('parts', '3001')
    assert call(v2, f'/items/{part}/instruction-links').status_code == 422
    assert call(v2, f'/items/{item}/instruction-links?bogus=1').status_code == 400


def test_instruction_links_follow_the_retail_country(v2, coll, pair):
    item = coll.item('sets', '1000-1')
    with closing(connect(pair)) as db:
        db.execute("INSERT OR REPLACE INTO main.setting(key,value) VALUES('retail_country','US')")
        db.commit()
    assert call(v2, f'/items/{item}/instruction-links').json['data']['region'] == 'US'
    with closing(connect(pair)) as db:
        db.execute("UPDATE main.setting SET value='NL' WHERE key='retail_country'")
        db.commit()
    assert call(v2, f'/items/{item}/instruction-links').json['data']['region'] == 'DE'
