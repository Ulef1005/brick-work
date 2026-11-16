"""Source-independent instruction discovery and confirmed jobs; invented fixtures only."""
import json
from io import BytesIO
import pytest
from brickwork.core import instructions as ins, instruction_sources as src
from brickwork.core.pipeline import Pipeline
from brickwork.core.transaction import transaction
from tests.app4 import coll, pair  # noqa: F401
from tests.instruction_fakes import registry


def discover(coll, registry):
    with transaction(coll.db):
        job = ins.queue_find(coll.db, [coll.item('sets', '1000-1')], region='AT')[0]
    row = coll.db.execute('SELECT * FROM job WHERE id=?', (job,)).fetchone()
    ins.find(coll.db, row, registry=registry)
    return job, ins.candidates(coll.db, [job])[0]['candidates']


def download(coll, rows):
    with transaction(coll.db):
        return ins.queue_download(coll.db, [r['id'] for r in rows])


def test_empty_registry_and_pipeline(coll, monkeypatch):
    monkeypatch.setattr(src, 'registry', src.Registry())
    assert not src.registry.adapters
    with transaction(coll.db):
        job = ins.queue_find(coll.db, [coll.item('sets', '1000-1')])[0]
    assert Pipeline(coll.db).run(job)['state'] == 'done'
    group = ins.candidates(coll.db, [job])[0]
    assert group['error'] == ins.NO_SOURCE and group['sources_tried'] == [] and group['candidates'] == []


@pytest.mark.parametrize('source', ['rebrickable', 'peeron'])
def test_discovery_stores_candidates_without_fetching(coll, source):
    reg, fake = registry(source)
    job, rows = discover(coll, reg)
    assert [r['booklet'] for r in rows] == [1, 2]
    assert all(r['source'] == source and r['region'] == 'AT' for r in rows)
    assert fake.calls == []
    assert ins.candidates(coll.db, [job])[0]['sources_tried'] == [source]


def test_ticks_region_peeron_size_and_existing_files():
    files = [dict(id=1, source='peeron', region=None, language=None, size=100, file_id=None)]
    assert ins.tick_defaults(files, 'AT') == [1]
    files += [dict(id=2, source='rebrickable', region='AT', language='English', size=100, file_id=None)]
    assert ins.tick_defaults(files, 'AT') == [2]
    assert ins.tick_defaults(files, 'US') == []
    files[1]['size'] = src.LIMIT + 1
    assert ins.tick_defaults(files, 'AT') == []
    files[1].update(size=100, file_id=1)
    assert ins.tick_defaults(files, 'AT') == []


def test_confirmed_job_hash_dedup_rate_and_idempotent_run(coll, tmp_path):
    reg, fake = registry()
    _, rows = discover(coll, reg)
    job = download(coll, rows)
    delays = []
    runner = ins.Downloads(coll.db, registry=reg, root=tmp_path, sleep=delays.append, monotonic=lambda: 10)
    done = runner.run(job)
    assert done['state'] == 'done' and [s['state'] for s in done['steps']] == ['done', 'done']
    assert delays == [1.0]
    assert len(list((tmp_path / 'data/instructions').glob('*.pdf'))) == 1
    assert coll.db.execute('SELECT count(*) FROM instruction_file').fetchone()[0] == 2
    runner.run(job)
    assert len(fake.calls) == 2


@pytest.mark.parametrize('content', [b'not a PDF', b'%PDF-' + b'x' * src.LIMIT])
def test_download_checks_actual_size_and_pdf_and_retry(coll, tmp_path, content):
    reg, fake = registry()
    _, rows = discover(coll, reg)
    fake.content = BytesIO(content)
    job = download(coll, rows[:1])
    runner = ins.Downloads(coll.db, registry=reg, root=tmp_path)
    assert runner.run(job)['state'] == 'failed'
    assert coll.db.execute('SELECT count(*) FROM instruction_file').fetchone()[0] == 0
    fake.content = b'%PDF-1.4\nSam'
    runner.queue_retry(job)
    assert runner.run(job)['state'] == 'done'


def test_no_ticks_and_retry_after_pause_remaining_files(coll, tmp_path):
    with transaction(coll.db), pytest.raises(ValueError, match='Tick'):
        ins.queue_download(coll.db, [])
    reg, fake = registry()
    _, rows = discover(coll, reg)
    job = download(coll, rows)
    fake.failure = src.RetryAfter('120')
    runner = ins.Downloads(coll.db, registry=reg, root=tmp_path)
    result = runner.run(job)
    assert result['state'] == 'waiting_for_budget' and len(fake.calls) == 1
    assert all(s['retry_at'] == result['retry_at'] for s in result['steps'])


def test_partial_source_failure_keeps_other_candidates(coll):
    reg, fake = registry()
    class Broken:
        def find(self, *args):
            raise OSError('invented offline')
    reg.register('peeron', Broken())
    job, rows = discover(coll, reg)
    assert len(rows) == 2
    group = ins.candidates(coll.db, [job])[0]
    assert group['error'] == 'Peeron did not answer'


def test_retail_countries_have_regions():
    from brickwork.core.admin import COUNTRIES
    assert set(COUNTRIES) <= ins.REGIONS.keys()
    assert ins.REGIONS['UK'] == ins.REGIONS['GB']


def test_booklet_find_resolves_set(coll):
    booklet = coll.local('instructions', 'Booklet', born_key='1000-1')
    coll.project(coll.item('sets', '1000-1'))
    with transaction(coll.db):
        job = ins.queue_find(coll.db, [booklet])[0]
    assert ins.candidates(coll.db, [job])[0]['item_id'] == coll.item('sets', '1000-1')


def test_removed_candidate_fails_step(coll, tmp_path):
    reg, _ = registry()
    _, rows = discover(coll, reg)
    job = download(coll, rows[:1])
    coll.db.execute('DELETE FROM instruction_candidate WHERE id=?', (rows[0]['id'],))
    coll.db.commit()
    result = ins.Downloads(coll.db, registry=reg, root=tmp_path).run(job)
    assert result['state'] == 'failed'
    assert result['steps'][0]['error'] == 'Candidate was removed'


@pytest.mark.parametrize('new_kind', ['instructions', 'box'])
def test_kind_move_refuses_discovery_rows(coll, new_kind):
    from brickwork.store4 import merge
    from brickwork.store4.errors import MergeRefused
    reg, _ = registry()
    job, _ = discover(coll, reg)
    coll.db.execute("UPDATE job SET state='done' WHERE id=?", (job,))
    coll.db.commit()
    with pytest.raises(MergeRefused, match='instruction'):
        merge.move_kind(coll.db, coll.item('sets', '1000-1'), new_kind)


@pytest.mark.parametrize('change', ["kind='box'", 'merged_into=?'])
def test_raw_item_change_refuses_discovery_rows(coll, change):
    import sqlite3
    reg, _ = registry()
    discover(coll, reg)
    target = coll.local('set', 'Surviving set')
    item = coll.item('sets', '1000-1')
    # Retire the catalogue item and detach the historical job to isolate discovery references.
    coll.db.execute("UPDATE item SET catalogue_retired_at='2026-01-01' WHERE id=?", (item,))
    coll.db.execute('UPDATE job SET item_id=NULL WHERE item_id=?', (item,))
    coll.db.execute('DELETE FROM item_link WHERE item_id=?', (item,))
    coll.db.commit()
    params = (target, item) if '?' in change else (item,)
    with pytest.raises(sqlite3.IntegrityError):
        coll.db.execute(f'UPDATE item SET {change} WHERE id=?', params)


def test_merge_refuses_active_download(coll):
    from brickwork.store4 import merge
    from brickwork.store4.errors import MergeRefused
    reg, _ = registry()
    job, candidates = discover(coll, reg)
    coll.db.execute("UPDATE job SET state='done' WHERE id=?", (job,))
    coll.db.commit()
    download(coll, candidates[:1])
    other = coll.local('set', 'Other set')
    with pytest.raises(MergeRefused, match='instruction_download'):
        merge.merge(coll.db, other, coll.item('sets', '1000-1'))


@pytest.mark.parametrize('candidate_region', ['GB', 'UK', 'Europe'])
def test_uk_and_gb_region_defaults_are_equivalent(candidate_region):
    candidate = dict(id=1, source='rebrickable', region=candidate_region, language='English', size=100, file_id=None)
    assert ins.tick_defaults([candidate], 'UK') == ins.tick_defaults([candidate], 'GB') == [1]


def test_region_is_validated_at_queue_time(coll):
    for bad in ('XX', 'de', ['AT']):
        with pytest.raises(ValueError, match='region'), transaction(coll.db):
            ins.queue_find(coll.db, [coll.item('sets', '1000-1')], region=bad)
    assert coll.db.execute('SELECT count(*) FROM instruction_search').fetchone()[0] == 0


def test_retry_after_is_capped_at_one_hour(coll, tmp_path):
    from datetime import datetime, timedelta, timezone
    reg, fake = registry()
    _, rows = discover(coll, reg)
    job = download(coll, rows)
    fake.failure = src.RetryAfter('99999999')
    result = ins.Downloads(coll.db, registry=reg, root=tmp_path).run(job)
    retry = datetime.strptime(result['retry_at'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
    assert retry <= datetime.now(timezone.utc) + timedelta(hours=1, seconds=5)


def test_candidate_in_an_active_download_is_not_queued_twice(coll, tmp_path):
    reg, fake = registry()
    _, rows = discover(coll, reg)
    job = download(coll, rows[:1])
    with pytest.raises(ValueError, match='already queued'), transaction(coll.db):
        ins.queue_download(coll.db, [rows[0]['id']])
    with transaction(coll.db):
        ins.queue_download(coll.db, [rows[1]['id']])
    runner = ins.Downloads(coll.db, registry=reg, root=tmp_path)
    runner.cancel(job)
    with transaction(coll.db):
        ins.queue_download(coll.db, [rows[0]['id']])


def test_attach_rechecks_the_candidate_and_streams_the_file(coll, tmp_path):
    from tempfile import TemporaryFile
    from brickwork.core.admin import attach_instruction
    reg, fake = registry()
    _, rows = discover(coll, reg)
    job = download(coll, rows[:1])
    streams = []
    def fetch(url, limit):
        stream = TemporaryFile()
        stream.write(fake.content)
        stream.seek(0)
        streams.append(stream)
        # Another job finishes the same candidate while this file downloads.
        with transaction(coll.db):
            other = attach_instruction(coll.db, tmp_path, rows[0]['item_id'], 'Other job', fake.content)
            coll.db.execute('UPDATE instruction_candidate SET file_id=? WHERE id=?', (other, rows[0]['id']))
        return stream
    fake.fetch = fetch
    assert ins.Downloads(coll.db, registry=reg, root=tmp_path).run(job)['state'] == 'done'
    assert coll.db.execute('SELECT count(*) FROM instruction_file').fetchone()[0] == 1
    assert streams and all(s.closed for s in streams)


def test_a_streamed_download_is_copied_in_chunks(coll, tmp_path):
    from hashlib import sha256
    from tempfile import TemporaryFile
    from brickwork.core.admin import attach_instruction
    data = b'%PDF-1.4\n' + b'x' * 200000
    with TemporaryFile() as stream:
        stream.write(data)
        stream.seek(0)
        with transaction(coll.db):
            attach_instruction(coll.db, tmp_path, coll.item('sets', '1000-1'), 'Streamed', stream)
    assert (tmp_path / 'data/instructions' / (sha256(data).hexdigest() + '.pdf')).read_bytes() == data
    with TemporaryFile() as stream, pytest.raises(ValueError):
        stream.write(b'Alex')
        with transaction(coll.db):
            attach_instruction(coll.db, tmp_path, coll.item('sets', '1000-1'), 'Not a PDF', stream)


@pytest.mark.parametrize('value', ['1' + '0' * 12, '1' + '0' * 20])
def test_a_huge_retry_after_is_clamped_not_dropped(coll, tmp_path, value):
    from datetime import datetime, timedelta, timezone
    reg, fake = registry()
    _, rows = discover(coll, reg)
    job = download(coll, rows)
    fake.failure = src.RetryAfter(value)
    result = ins.Downloads(coll.db, registry=reg, root=tmp_path).run(job)
    assert result['state'] == 'waiting_for_budget'
    retry = datetime.strptime(result['retry_at'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
    assert retry <= datetime.now(timezone.utc) + timedelta(hours=1, seconds=5)
    assert retry >= datetime.now(timezone.utc) + timedelta(minutes=59)


def test_duplicate_download_check_uses_the_row_id(coll):
    reg, fake = registry()
    _, rows = discover(coll, reg)
    download(coll, rows[:1])
    with pytest.raises(ValueError, match='already queued'), transaction(coll.db):
        ins.queue_download(coll.db, [float(rows[0]['id'])])


def test_attach_does_not_hold_the_write_lock_while_the_file_is_copied(coll, tmp_path):
    import sqlite3
    reg, fake = registry()
    _, rows = discover(coll, reg)
    job = download(coll, rows[:1])
    path = coll.db.execute('PRAGMA database_list').fetchone()[2]
    seen = []

    class Slow(BytesIO):
        def read(self, size=-1):
            data = super().read(size)
            if not seen:
                seen.append(True)
                other = sqlite3.connect(path, timeout=0.2)
                try:
                    other.execute('BEGIN IMMEDIATE')  # raises 'database is locked' while the downloader holds the write lock
                    other.rollback()
                    seen.append('free')
                finally:
                    other.close()
            return data
    fake.fetch = lambda url, limit: Slow(fake.content)
    assert ins.Downloads(coll.db, registry=reg, root=tmp_path).run(job)['state'] == 'done'
    assert seen == [True, 'free']


def test_a_rolled_back_attach_keeps_a_file_another_row_references(coll, tmp_path):
    from brickwork.core.admin import attach_instruction
    item = coll.item('sets', '1000-1')
    data = b'%PDF-1.4\nshared'
    with transaction(coll.db):
        attach_instruction(coll.db, tmp_path, item, 'First', data)
    with pytest.raises(RuntimeError), transaction(coll.db):
        attach_instruction(coll.db, tmp_path, item, 'Second', data)
        raise RuntimeError('boom')
    assert len(list((tmp_path / 'data/instructions').glob('*.pdf'))) == 1
    assert coll.db.execute('SELECT count(*) FROM instruction_file').fetchone()[0] == 1
