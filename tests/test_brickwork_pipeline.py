"""Synthetic transport fixtures; these tests cannot access a provider."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from flask import Flask
import pytest

from brickwork.core.connect import connect
from brickwork.core.pipeline import Pipeline, STEPS
from brickwork.core.importer.projection import PRIORITY
from brickwork.core.sources import base, images
from brickwork.core.sources.bricklink import BrickLink
from brickwork.core.sources.rebrickable import Rebrickable


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(base, 'transport', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(images, 'transport', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    for key in (*BrickLink.credentials, *Rebrickable.credentials, 'BW_BRICKSET_API_KEY'):
        monkeypatch.setenv(key, 'synthetic-' + key)


@pytest.fixture
def db(tmp_path):
    with closing(connect(tmp_path / 'brickwork.db')) as db:
        yield db


def png():
    return (Path(__file__).parent / 'fixtures/brickwork/import-image.png').read_bytes()


def bl(data):
    return {'meta': {'code': 200}, 'data': data}


def transport(request):
    from brickwork.version import __version__
    assert request.get_header('User-agent') == f'BrickWork/{__version__} (+self-hosted)'
    url = request.full_url
    if 'api.bricklink.com' in url:
        if '/subsets' in url:
            return bl([{'entries': [dict(item={'type': 'PART', 'no': 'synthetic-p'}, quantity=2, color_id=4),
                                     dict(item={'type': 'MINIFIG', 'no': 'synthetic-m'}, quantity=1)]}])
        if '/price' in url:
            return bl(dict(total_quantity=2, qty_avg_price='1.2345', min_price='1', max_price='2'))
        kind = url.split('/items/')[1].split('/')[0]
        return bl(dict(type=kind, no=url.split('/')[-1], name='Synthetic item', category_id=1, year_released=2001))
    if 'brickset.com' in url:
        return {'status': 'success', 'matches': 1, 'sets': [dict(number='123', numberVariant=1, setID=42,
            theme='Synthetic theme', LEGOCom={'DE': {'retailPrice': '12.34'}})]}
    if 'rebrickable.com' in url:
        row = dict(part_num='rb-synthetic', external_ids={'BrickLink': ['synthetic-p']},
                   part_img_url='https://cdn.rebrickable.com/synthetic.png')
        if '/parts/?' in url:
            return dict(results=[row], count=1, next=None)
        if '/colors/?' in url:
            return dict(results=[dict(id=99, external_ids={'BrickLink': {'ext_ids': [4]}})], next=None)
        if '/colors/99/' in url:
            return dict(part_img_url='https://cdn.rebrickable.com/synthetic-red.png')
        return row
    raise AssertionError(url)


def pipeline(db, **kwargs):
    return Pipeline(db, http=transport, image_http=lambda _: png(), emit=lambda *args: None, **kwargs)


def test_all_steps_real_transport_and_local_images(db, tmp_path):
    events = []
    p = Pipeline(db, http=transport, image_http=lambda _: png(), emit=lambda event, payload: events.append((event, payload)))
    result = p.import_item('S', '123-1', via='cli')
    assert result['state'] == 'done'
    assert [s['name'] for s in result['steps']] == list(STEPS)
    assert all(s['state'] == 'done' for s in result['steps'])
    assert db.execute('SELECT name,year FROM items WHERE item_no=?', ('123-1',)).fetchone()['year'] == 2001
    assert [r[0] for r in db.execute('SELECT child_item_type FROM inventory_lines ORDER BY child_item_type')] == ['M', 'P']
    image = db.execute('SELECT * FROM item_images').fetchone()
    assert image['local_path'].startswith('data/images/bricklink/S/')
    assert (tmp_path / image['local_path']).read_bytes() == png()
    assert (image['width'], image['height']) == (3, 2)
    assert db.execute("SELECT count(*) FROM source_records").fetchone()[0] == 5
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert all(e == 'import_progress' for e, data in events)
    assert [data['count'] for e, data in events if data['state'] == 'progress'] == [1, 2]
    assert events[-1][1]['message'] == 'Import complete'
    assert db.execute("SELECT count(*) FROM events WHERE via!='import'").fetchone()[0] == 0
    assert p.import_item('S', '123-1', via='app')['id'] == result['id']


def test_setting_order_and_source_priority_snapshot(db):
    p = pipeline(db)
    priority = json.loads(json.dumps(PRIORITY))
    priority['identity']['*'] = ['custom', 'bricklink:api']
    order = list(reversed(STEPS))
    with db:
        db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(priority), 'source_priority'))
        db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(order), 'import_order:S'))
    seen = []
    p.handlers = {(step, source): lambda p, job, step: seen.append(step)
                  for step in STEPS for source in ('custom', 'bricklink', 'bricklink:subsets', 'rebrickable', 'brickset')}
    result = p.import_item('S', '123-1', via='app')
    assert seen == order
    assert result['steps'][-1]['sources'] == '["custom", "bricklink:api"]'
    assert result['state'] == 'done'


def test_independent_failure_commits_and_retry(db, tmp_path):
    p = pipeline(db)
    failed = [True]
    def inventory(p, job, step):
        # Identity must already be visible to a second connection.
        with closing(connect(tmp_path / 'brickwork.db')) as other:
            assert other.execute("SELECT name FROM items WHERE item_no='123-1'").fetchone()[0] == 'Synthetic item'
        if failed[0]:
            raise base.SourceError('BrickLink subsets failed')
        p.perform(job, step, 'bricklink:subsets')
    p.handlers = {('inventory', 'bricklink:subsets'): inventory}
    result = p.import_item('S', '123-1', via='order')
    assert result['state'] == 'failed'
    assert [s['name'] for s in result['steps'] if s['state'] == 'failed'] == ['inventory']
    assert db.execute('SELECT count(*) FROM item_images').fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM price_observations').fetchone()[0] == 3
    failed[0] = False
    result = p.retry(result['id'], 'inventory')
    assert result['state'] == 'done'
    assert db.execute('SELECT count(*) FROM price_observations').fetchone()[0] == 3
    assert db.execute('SELECT count(*) FROM item_images').fetchone()[0] == 1


def test_budget_resume_worker_no_repeat_calls(db, monkeypatch):
    clock = [datetime(2026, 10, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '2')
    http = Mock(side_effect=transport)
    p = Pipeline(db, http=http, image_http=lambda _: png(), emit=lambda *args: None)
    first = p.import_item('S', '123-1', via='cli')
    assert first['state'] == 'waiting_for_budget'
    market = next(s for s in first['steps'] if s['name'] == 'market_price')
    assert market['state'] == 'waiting_for_budget'
    child = db.execute("SELECT request_job FROM import_calls WHERE step='market_price'").fetchone()[0]
    assert child
    assert p.drain() == []
    clock[0] += timedelta(days=1)
    # Recreate pipeline/connection-side state: persisted checkpoints survive restarts.
    p = Pipeline(db, http=http, image_http=lambda _: png(), emit=lambda *args: None)
    assert p.drain()[0]['state'] == 'done'
    assert db.execute('SELECT state FROM jobs WHERE id=?', (child,)).fetchone()[0] == 'done'
    assert sum('/subsets' in c.args[0].full_url for c in http.call_args_list) == 1
    assert db.execute('SELECT count(*) FROM price_observations').fetchone()[0] == 3


def test_part_render_and_color_ids_are_translated(db, tmp_path):
    with db:
        db.execute("INSERT INTO items(item_type,item_no) VALUES('P','synthetic-p')")
        db.execute('INSERT INTO colors(color_id) VALUES(4)')
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id) VALUES('stock','P','synthetic-p',4)")
    result = pipeline(db).import_item('P', 'synthetic-p', via='part-to-inventory')
    assert result['state'] == 'done'
    assert {tuple(r) for r in db.execute('SELECT item_type,item_no FROM items')} == {('P', 'synthetic-p')}
    assert [(r['source_id'], r['color_id']) for r in db.execute("SELECT * FROM id_match WHERE kind='color'")] == [('99', 4)]
    image = db.execute('SELECT * FROM item_images').fetchone()
    assert (image['source'], image['kind'], image['color_id']) == ('rebrickable', 'render', 4)
    assert (tmp_path / image['local_path']).is_file()


@pytest.mark.parametrize('kind', ['M', 'P', 'G', 'B', 'C', 'I', 'O'])
def test_all_item_types(db, kind):
    result = pipeline(db).import_item(kind, 'synthetic-p' if kind == 'P' else 'synthetic-' + kind, via='app')
    assert result['state'] == 'done'
    assert all(s['state'] == 'done' for s in result['steps'])


def test_image_fallback_and_safe_errors(db, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'private-key')
    p = pipeline(db)
    def fail(p, job, step):
        raise base.SourceError('private-key render unavailable')
    p.handlers = {('pictures', 'rebrickable'): fail}
    result = p.import_item('P', 'synthetic-p', via='app')
    assert result['state'] == 'done'
    assert next(s for s in result['steps'] if s['name'] == 'pictures')['source'] == 'bricklink'
    assert 'private-key' not in str([tuple(r) for r in db.execute('SELECT * FROM events')])


def test_default_emit_is_a_no_op(db):
    assert Pipeline(db).emit('import_progress', {'job_id': 1}) is None


def test_invalid_priority_does_not_create_item(db):
    p = pipeline(db)
    with db:
        db.execute("UPDATE settings SET value='[]' WHERE key='source_priority'")
    with pytest.raises(ValueError):
        p.import_item('S', '123-1', via='cli')
    assert db.execute('SELECT count(*) FROM items').fetchone()[0] == 0


def test_image_redirect_hosts_and_bytes(db, tmp_path):
    with db:
        base.item(db, 'P', 'synthetic-p')
    http = Mock(return_value=png())
    for url in ('http://img.bricklink.com/x', 'https://evil.invalid/x', 'https://key@img.bricklink.com/x'):
        with pytest.raises(base.SourceError):
            images.download(db, tmp_path, 'bricklink', 'P', 'synthetic-p', url, http=http)
    http.assert_not_called()
    with pytest.raises(base.SourceError):
        images.download(db, tmp_path, 'bricklink', 'P', 'synthetic-p', 'https://img.bricklink.com/x', http=lambda _: b'invalid')
    assert db.execute('SELECT count(*) FROM item_images').fetchone()[0] == 0


def test_crashed_owner_resumes_and_live_owner_is_excluded(db, monkeypatch):
    p = pipeline(db)
    result = p.import_item('S', '123-1', via='cli')
    with db:
        db.execute("UPDATE jobs SET state='running' WHERE id=?", (result['id'],))
        db.execute('INSERT INTO import_owners VALUES(?,?)', (result['id'], 99999998))
    monkeypatch.setattr('brickwork.core.pipeline.os.kill', lambda *args: None)
    assert p.drain() == []
    assert p.import_item('S', '123-1', via='cli')['state'] == 'running'
    def dead(pid, signal):
        raise ProcessLookupError()
    monkeypatch.setattr('brickwork.core.pipeline.os.kill', dead)
    assert p.drain()[0]['state'] == 'done'
    assert db.execute('SELECT count(*) FROM import_owners').fetchone()[0] == 0


def test_wait_then_failure_can_be_retried(db, monkeypatch):
    clock = [datetime(2026, 10, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '2')
    p = pipeline(db)
    result = p.import_item('S', '123-1', via='cli')
    clock[0] += timedelta(days=1)
    p.clients['bricklink'].http = lambda _: bl({})
    result = p.drain()[0]
    assert result['state'] == 'failed'
    clock[0] += timedelta(days=1)
    p.clients['bricklink'].http = transport
    assert p.retry(result['id'], 'market_price')['state'] == 'done'


def test_catalogue_identity_year_offline(db, tmp_path):
    catalogue = tmp_path / 'bricklink-catalog.db'
    with sqlite3.connect(catalogue) as index:
        index.execute('CREATE TABLE items(item_type,item_no,name,category,year)')
        index.execute("INSERT INTO items VALUES('G','synthetic-G','Synthetic gear','9',1997)")
    p = pipeline(db, catalogue=catalogue)
    result = p.import_item('G', 'synthetic-G', via='app')
    assert result['steps'][0]['source'] == 'bricklink:local'
    assert tuple(db.execute("SELECT name,category,year FROM items WHERE item_no='synthetic-G'").fetchone()) == ('Synthetic gear', '9', 1997)


def test_disconnected_observer_does_not_fail_import(db):
    p = pipeline(db)
    p.emit = Mock(side_effect=OSError('observer disconnected'))
    assert p.import_item('S', '123-1', via='app')['state'] == 'done'


def test_migrated_part_colour_and_resolution_evidence(db):
    p = pipeline(db)
    with db:
        base.item(db, 'P', 'synthetic-p')
        db.execute('INSERT INTO colors(color_id) VALUES(4)')
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,color_id,status,evidence_json) VALUES('rebrickable','part','rb-p','P','synthetic-p',4,'manual','[]')")
    assert p.match_id('part', 'synthetic-p') == 'rb-p'
    with db:
        base.item(db, 'P', 'resolution-p')
        db.execute("INSERT INTO source_records VALUES('rebrickable','part_resolutions','resolution-p',?,NULL,'legacy')", (
            json.dumps({'records': [{'record': {'bricklink': 'resolution-p', 'parts': '[{"part_num":"rb-resolution"}]'}}]}),))
    assert p.resolution('resolution-p') == 'rb-resolution'
    assert db.execute("SELECT status FROM id_match WHERE source_id='rb-resolution'").fetchone()[0] == 'inferred'


def test_failed_listing_includes_mixed_budget_waits(db, monkeypatch):
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    p = pipeline(db)
    p.handlers = {('metadata', 'brickset'): lambda *args: (_ for _ in ()).throw(base.SourceError('Brickset failed'))}
    result = p.import_item('S', '123-1', via='app')
    assert result['state'] == 'waiting_for_budget'
    assert p.list_jobs(failed=True)[0]['id'] == result['id']


@pytest.mark.parametrize('kind,number,rb', [('S', '123-1', '123-1'), ('M', 'canonical-m', 'fig-rb')])
def test_other_image_fallbacks_keep_types(db, kind, number, rb):
    p = pipeline(db)
    if kind == 'M':
        with db:
            base.item(db, kind, number)
            db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','minifigure',?,'M',?,'manual','[]')", (rb, number))
    def http(request):
        if request.full_url.startswith('https://rebrickable.com/'):
            return {'set_num': rb, 'set_img_url': 'https://cdn.rebrickable.com/synthetic.png'}
        return transport(request)
    p.clients['rebrickable'].http = http
    def image_http(request):
        if 'bricklink.com' in request.full_url:
            raise OSError('synthetic failure')
        return png()
    p.image_http = image_http
    result = p.import_item(kind, number, via='app')
    assert result['state'] == 'done'
    assert tuple(db.execute('SELECT item_type,item_no,source,kind FROM item_images').fetchone()) == (kind, number, 'rebrickable', 'photo')


def test_runtime_foreign_keys_are_indexed(db):
    pipeline(db)
    for table in ('import_steps', 'import_calls', 'import_owners'):
        groups = {}
        for row in db.execute(f'PRAGMA foreign_key_list({table})'):
            groups.setdefault(row['id'], []).append(row['from'])
        indexes = [tuple(row['name'] for row in db.execute(f'PRAGMA index_info({i["name"]})'))
                   for i in db.execute(f'PRAGMA index_list({table})')]
        for columns in groups.values():
            assert any(index[:len(columns)] == tuple(columns) for index in indexes)


def test_app_uses_configured_new_store(tmp_path, monkeypatch):
    from brickwork.core.pipeline import import_item
    monkeypatch.delenv('BW_DB_PATH', raising=False)
    app = Flask(__name__)
    app.config['BRICKWORK_DB_PATH'] = str(tmp_path / 'new.db')
    app.config['LEGACY_DB_PATH'] = str(tmp_path / 'legacy.db')
    with app.app_context():
        result = import_item('S', '123-1', via='app', http=transport, image_http=lambda _: png())
    assert result['state'] == 'done'
    assert (tmp_path / 'new.db').exists()
    assert not (tmp_path / 'legacy.db').exists()


def test_image_download_user_agent_and_file_before_row(db, tmp_path):
    from brickwork.version import __version__
    db.execute("INSERT INTO items(item_type,item_no) VALUES('S','6080-1')")
    http = Mock(return_value=png())
    path = images.download(db, tmp_path, 'bricklink', 'S', '6080-1',
                           'https://img.bricklink.com/ItemImage/SN/0/6080-1.png', http=http)
    assert http.call_args.args[0].get_header('User-agent') == f'BrickWork/{__version__} (+self-hosted)'
    assert (tmp_path / path).is_file()
    assert db.execute('SELECT local_path FROM item_images').fetchone()[0] == path


def assert_safe_yields(monkeypatch, db):
    """Replace gevent's scheduler, leaving the transaction guard under test intact."""
    import gevent
    import gevent.monkey
    turns = []
    def sleep(seconds):
        assert not db.in_transaction
        turns.append(seconds)
    monkeypatch.setattr(gevent.monkey, 'is_module_patched', lambda name: True)
    monkeypatch.setattr(gevent, 'sleep', sleep)
    return turns


def test_full_import_and_bricklink_consume_never_yield_in_transaction(db, monkeypatch):
    app = Flask(__name__)
    turns = assert_safe_yields(monkeypatch, db)
    with app.app_context():
        p = pipeline(db)
        assert p.import_item('S', '123-1', via='app')['state'] == 'done'
        assert p.import_item('P', 'synthetic-p', via='app')['state'] == 'done'
        # The standalone consumer writes many lines inside Source._request.
        before = len(turns)
        p.clients['bricklink'].subsets('S', '123-1')
        assert len(turns) == before
    assert turns


def test_current_pid_without_process_claim_is_resumed(db):
    import os
    p = pipeline(db)
    with db:
        base.item(db, 'S', '123-1')
        job = p.queue_steps('S', '123-1', ['identity'], via='cli', sources=['bricklink:api'])
        db.execute("UPDATE jobs SET state='running' WHERE id=?", (job,))
        db.execute('INSERT INTO import_owners VALUES(?,?)', (job, os.getpid()))
    assert not p.owner_alive(job)
    result = p.drain()[0]
    assert result['state'] == 'done' and result['attempts'] == 1
    assert db.execute('SELECT count(*) FROM import_owners').fetchone()[0] == 0


def test_cooperation_defers_until_commit_even_on_exception(db, monkeypatch):
    from brickwork.core.pipeline import cooperative, yield_worker
    app = Flask(__name__)
    turns = assert_safe_yields(monkeypatch, db)
    with app.app_context():
        with pytest.raises(ValueError), db:
            db.execute('BEGIN IMMEDIATE')
            yield_worker(db)
            for _ in cooperative(db, range(2)):
                raise ValueError('rollback')
        assert not turns
        yield_worker(db)
    assert turns == [0]


@pytest.mark.parametrize('seconds,expected', [(20,20), (7200,60), (0,1)])
def test_poll_delay_uses_earliest_budget_deadline(db, monkeypatch, seconds, expected):
    from brickwork.core.pipeline import poll_delay
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    monkeypatch.setattr(base, 'now', lambda: now)
    p = pipeline(db)
    assert poll_delay(db) is None
    for offset in (7201, seconds):
        with db:
            base.item(db, 'S', str(offset))
            job = p.queue_steps('S', str(offset), ['identity'], via='cli', sources=['bricklink:api'])
            db.execute("UPDATE jobs SET state='waiting_for_budget',retry_at=? WHERE id=?",
                       ((now + timedelta(seconds=offset)).isoformat(), job))
    assert poll_delay(db) == expected
    with db:
        base.item(db, 'S', 'runnable')
        p.queue_steps('S', 'runnable', ['identity'], via='cli', sources=['bricklink:api'])
    assert poll_delay(db) == 1


@pytest.mark.parametrize('kind,number,expected', [('P','ref-part','render'), ('S','ref-set','photo'), ('M','ref-figure','photo')])
def test_reference_download_matches_refresh_kind(db, kind, number, expected):
    with db:
        db.execute('INSERT INTO items(item_type,item_no) VALUES(?,?)', (kind, number))
    p = Pipeline(db, image_http=lambda _: png(), emit=lambda *args: None)
    job = p.queue_steps(kind, number, ['pictures'], sources=['rebrickable'],
                        reference_image='https://cdn.rebrickable.com/reference.png')
    db.commit()
    assert p.run(job)['state'] == 'done'
    assert db.execute('SELECT kind FROM item_images').fetchone()[0] == expected
