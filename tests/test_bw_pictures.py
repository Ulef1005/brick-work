"""Picture refresh through real v3 migration evidence, without live services."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from PIL import Image
import pytest

from brickwork.core import add, drainer, pictures
from brickwork.core.connect import connect
from brickwork.core.importer.migrate import migrate
from brickwork.core.pipeline import Pipeline
from brickwork.core.sources import base, images
from tests.importer.test_importer import legacy, insert
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps


def png(color='blue'):
    stream = BytesIO()
    Image.new('RGB', (4, 3), color).save(stream, 'PNG')
    return stream.getvalue()


@pytest.fixture
def migrated(legacy, monkeypatch):
    # Two parts can share an image_id. Give this fixture explicit, distinct cache names.
    with sqlite3.connect(legacy['app_db']) as db:
        db.execute("UPDATE rebrickable_parts SET image_id=part")
    (legacy['app_db'].parent / 'data/images/set.png').unlink()
    migrate(**legacy)
    monkeypatch.setenv('BW_DB_PATH', str(legacy['out_db']))
    root = legacy['out_db'].parent
    for filename in ('sets/old-set.jpg', 'parts/rb-part.jpg', 'minifigures/rb-figure.jpg',
                     'bl-images/I/new-set.png', 'sets/unmatched.jpg'):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png())
    (root / 'minifigures/rb-review.jpg').write_bytes(png())
    (root / 'parts/rb-duplicate.jpg').write_bytes(b'corrupt')
    return legacy['out_db']


def test_local_copy_receipt_and_collection_projection(migrated):
    root = migrated.parent
    before = {p: (p.read_bytes(), p.stat().st_mtime) for folder in ('sets','parts','minifigures','bl-images') for p in (root/folder).rglob('*') if p.is_file()}
    with closing(connect(migrated)) as db:
        job, count = pictures.queue(db, 'existing', 'missing', pictures.TYPE_LABELS)
        pipeline = Pipeline(db, emit=lambda *args: None, image_http=Mock(side_effect=AssertionError('network')))
        result = pipeline.run(job)
        assert result['state'] == 'done'
        assert result['steps'][0]['count'] == result['steps'][0]['total'] == count
        receipt = json.loads(result['payload'])
        assert receipt['stored'] >= 4
        reasons = ' '.join(r['reason'] for r in receipt['issues'])
        assert 'No unambiguous identity' in reasons
        assert 'verified' in reasons and 'Unresolved identity' in reasons
        rows = add.decorate_many(db, [dict(item_type=k, item_no=n, color_id=c) for k,n,c in
            [('S','new-set',None), ('P','bl-part',11), ('M','bl-figure',None), ('I','new-set',None)]])
        assert all(r['image'] for r in rows)
        for row in db.execute('SELECT * FROM item_images WHERE source IN (\'rebrickable\',\'bricklink\')'):
            assert (root / row['local_path']).is_file()
            assert row['width'] == 4 and row['height'] == 3
        picture = db.execute("SELECT fetched_at FROM item_images WHERE item_type='S'").fetchone()[0]
        assert abs(datetime.fromisoformat(picture).timestamp() - before[root/'sets/old-set.jpg'][1]) < 0.000001
        assert db.execute("SELECT count(*) FROM events WHERE field='stored' AND via='app'").fetchone()[0] >= 4
    assert all(p.read_bytes() == data and p.stat().st_mtime == mtime for p,(data,mtime) in before.items())


def test_existing_rebrickable_kinds_and_set_refresh_replaces_row(migrated):
    with closing(connect(migrated)) as db:
        job, _ = pictures.queue(db, 'existing', 'missing', ['S', 'P', 'M'])
        download = Mock(return_value=png('red'))
        pipeline = Pipeline(db, emit=lambda *args: None, image_http=download)
        assert pipeline.run(job)['state'] == 'done'
        download.assert_not_called()
        rows = {(r['item_type'], r['item_no']): r for r in db.execute(
            "SELECT * FROM item_images WHERE source='rebrickable'")}
        assert rows['S', 'new-set']['kind'] == 'photo'
        assert rows['P', 'bl-part']['kind'] == 'render'
        assert rows['M', 'bl-figure']['kind'] == 'photo'
        old_set = dict(rows['S', 'new-set'])

        job, _ = pictures.queue(db, 'rebrickable', 'all', ['S'])
        pipeline.clients['rebrickable'].call = lambda *args, **kwargs: {
            'set_img_url': 'https://cdn.rebrickable.com/set.png'}
        assert pipeline.run(job)['state'] == 'done'
        download.assert_called_once()
        refreshed = db.execute(
            "SELECT * FROM item_images WHERE item_type='S' AND item_no='new-set' AND source='rebrickable'").fetchall()
        assert len(refreshed) == 1
        assert refreshed[0]['kind'] == 'photo'
        assert refreshed[0]['local_path'] != old_set['local_path']
        assert (migrated.parent / refreshed[0]['local_path']).read_bytes() == png('red')
        event = db.execute(
            "SELECT * FROM events WHERE entity='picture:S:new-set' AND field='stored' ORDER BY id DESC LIMIT 1").fetchone()
        assert event['via'] == 'app'
        assert json.loads(event['old_value']) == [old_set]


@pytest.mark.parametrize('source', ['priority','bricklink','rebrickable','existing'])
@pytest.mark.parametrize('scope', ['missing','all'])
def test_queue_counts_scopes_and_dedup(migrated, source, scope):
    with closing(connect(migrated)) as db:
        Pipeline(db)
        with base.audit_origin('app'):
            images.store(db, migrated.parent, 'bricklink','S','new-set',png())
        expected = pictures.selection(db, source, scope, ['S','P','M'])
        job, count = pictures.queue(db, source, scope, ['S','P','M','S'])
        assert count == len(expected)
        assert ('new-set' in [r['item_no'] for r in expected]) == (scope == 'all')
        assert pictures.queue(db, source, scope, ['M','S','P']) == (job,count)
        saved = json.loads(db.execute('SELECT payload FROM jobs WHERE id=?', (job,)).fetchone()[0])
        keys = [(r['item_type'],r['item_no'],r['color_id']) for r in saved['identities']]
        assert len(keys) == len(set(keys))
        assert saved['source'] == source
        assert db.execute("SELECT via FROM events WHERE entity=? AND field='queued'", ('job:'+str(job),)).fetchone()[0] == 'app'


def test_summary_and_queue_query_cost(migrated):
    with closing(connect(migrated)) as db:
        with db:
            db.executemany("INSERT INTO items(item_type,item_no) VALUES('S',?)", [(str(n),) for n in range(300)])
            db.executemany("INSERT INTO wishlist(item_type,item_no) VALUES('S',?)", [(str(n),) for n in range(300)])
        pipeline = Pipeline(db)
        queries = []
        db.set_trace_callback(queries.append)
        summary = pictures.state(db)
        assert len(queries) <= 5
        assert sum(r['total'] for r in summary['summary']) >= 300
        queries.clear()
        pictures.queue(db, 'bricklink', 'all', ['S'])
        assert len(queries) < 100
        db.set_trace_callback(None)


def test_refresh_budget_resumes_and_no_repeat_download(migrated, monkeypatch):
    clock = [datetime(2026,10,13,tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    monkeypatch.setenv('BW_BRICKLINK_MIN_SPACING', '0')
    with closing(connect(migrated)) as db:
        with db:
            db.execute("INSERT INTO items VALUES('S','two',NULL,NULL,NULL,NULL)")
            db.execute("INSERT INTO wishlist(item_type,item_no) VALUES('S','two')")
        job, count = pictures.queue(db, 'bricklink', 'all', ['S'])
        download = Mock(return_value=png())
        pipeline = Pipeline(db, emit=lambda *args: None, image_http=download)
        assert pipeline.run(job)['state'] == 'waiting_for_budget'
        assert download.call_count == 1
        clock[0] += timedelta(days=1)
        result = pipeline.run(job)
        assert result['state'] == 'done' and download.call_count == 2
        assert result['steps'][0]['count'] == count
        assert all(r[0] == 'app' for r in db.execute("SELECT via FROM events WHERE field='stored'"))


def test_failure_keeps_picture_and_priority(migrated):
    with closing(connect(migrated)) as db:
        with base.audit_origin('app'):
            old = images.store(db,migrated.parent,'bricklink','S','new-set',png())
        job, _ = pictures.queue(db,'bricklink','all',['S'])
        result = Pipeline(db,emit=lambda *args: None,image_http=Mock(side_effect=OSError())).run(job)
        assert json.loads(result['payload'])['issues']
        assert (migrated.parent/old).is_file()
        assert db.execute("SELECT local_path FROM item_images WHERE item_type='S'").fetchone()[0] == old


def test_settings_dialog_routes_csrf_gate_and_jobs(app, migrated, monkeypatch):
    client = logged_in(app)
    html = client.get('/manage/settings').get_data(as_text=True)
    assert 'Refresh pictures' in html and 'Existing Brick Work files' in html
    assert 'picture-priority' in html and 'data-picture-dialog' in html
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    data = dict(action='pictures',source='existing',scope='missing',types=['S','P','M','I'],csrf_token=token)
    assert client.post('/manage/settings',data={**data,'csrf_token':'wrong'}).status_code == 400
    app.config['BW_READ_ONLY'] = True
    try:
        assert client.post('/manage/settings',data=data).status_code == 403
    finally:
        app.config.pop('BW_READ_ONLY')
    monkeypatch.setattr('brickwork.web.views.bw_start_worker',lambda: None)
    response = client.post('/manage/settings',data=data)
    assert response.status_code == 302 and '/jobs#job-' in response.location
    with closing(connect(migrated)) as db:
        job = db.execute("SELECT id FROM jobs WHERE kind='picture_refresh'").fetchone()[0]
        Pipeline(db,emit=lambda *args: None).run(job)
    html = client.get('/manage/jobs').get_data(as_text=True)
    assert 'No Undo for picture refresh' in html and 'findings' in html


@pytest.mark.parametrize('source', ['bricklink','rebrickable','priority'])
def test_remote_sources_and_priority_fallback(migrated, source, monkeypatch):
    monkeypatch.setenv('BW_BRICKLINK_MIN_SPACING','0')
    with closing(connect(migrated)) as db:
        job, _ = pictures.queue(db,source,'missing',['S'])
        def download(request):
            if source == 'priority' and 'bricklink' in request.full_url:
                raise OSError('Unavailable')
            return png('red')
        pipeline = Pipeline(db,emit=lambda *args: None,image_http=download)
        pipeline.clients['rebrickable'].call = lambda *args,**kwargs: {'set_img_url':'https://cdn.rebrickable.com/set.png'}
        result = pipeline.run(job)
        assert result['state'] == 'done'
        row = db.execute("SELECT source FROM item_images WHERE item_type='S'").fetchone()
        assert row[0] == ('bricklink' if source == 'bricklink' else 'rebrickable')
        receipt = json.loads(result['payload'])
        assert receipt['stored'] == 1


def test_event_failure_preserves_previous_row(migrated):
    with closing(connect(migrated)) as db:
        old = images.store(db,migrated.parent,'bricklink','S','new-set',png())
        db.execute("CREATE TRIGGER reject_picture BEFORE INSERT ON events WHEN NEW.field='stored' BEGIN SELECT RAISE(ABORT,'rejected'); END")
        with pytest.raises(sqlite3.IntegrityError):
            images.store(db,migrated.parent,'bricklink','S','new-set',png('red'))
        assert db.execute("SELECT local_path FROM item_images WHERE item_type='S'").fetchone()[0] == old
        assert (migrated.parent/old).is_file()


def test_replace_keeps_other_source_and_display_priority(migrated, monkeypatch):
    monkeypatch.setenv('BW_BRICKLINK_MIN_SPACING','0')
    with closing(connect(migrated)) as db:
        pipeline = Pipeline(db,emit=lambda *args: None,image_http=lambda _: png('red'))
        priority = db.execute("SELECT value FROM settings WHERE key='source_priority'").fetchone()[0]
        with base.audit_origin('app'):
            old = images.store(db,migrated.parent,'bricklink','S','new-set',png())
            rb = images.store(db,migrated.parent,'rebrickable','S','new-set',png('green'))
        job, _ = pictures.queue(db,'bricklink','all',['S'])
        pipeline.run(job)
        assert (migrated.parent/old).is_file() and (migrated.parent/rb).is_file()
        assert db.execute("SELECT local_path FROM item_images WHERE item_type='S' AND source='bricklink'").fetchone()[0] != old
        assert db.execute("SELECT local_path FROM item_images WHERE item_type='S' AND source='rebrickable'").fetchone()[0] == rb
        assert db.execute("SELECT value FROM settings WHERE key='source_priority'").fetchone()[0] == priority
        decorated = add.decorate_many(db,[dict(item_type='S',item_no='new-set',color_id=None)])[0]
        assert db.execute('SELECT source FROM item_images WHERE id=?',(decorated['image'],)).fetchone()[0] == 'bricklink'


def test_unknown_part_colour_is_reported_without_guessing(migrated):
    with closing(connect(migrated)) as db:
        with db:
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity) VALUES('unknown-colour','P','bl-part',1)")
        job, _ = pictures.queue(db,'bricklink','missing',['P'])
        downloaded = []
        pipeline = Pipeline(db,emit=lambda *args: None,image_http=lambda request: downloaded.append(request.full_url) or png())
        result = pipeline.run(job)
        findings = json.loads(result['payload'])['issues']
        assert any(r['name'] == 'bl-part' and r['reason'].startswith('Unknown colour') for r in findings)
        assert all('/PN/0/bl-part' not in url for url in downloaded)


def test_count_matrix_matches_exact_selection_for_every_type_and_scope(migrated):
    with closing(connect(migrated)) as db:
        # Give every migrated cache row a physical file, then add overlapping
        # sources and a colourless fallback through the real storage helper.
        for row in db.execute('SELECT local_path FROM item_images'):
            path = migrated.parent / row[0]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png())
        images.store(db, migrated.parent, 'bricklink', 'S', 'new-set', png())
        images.store(db, migrated.parent, 'rebrickable', 'S', 'new-set', png())
        images.store(db, migrated.parent, 'bricklink', 'P', 'bl-part', png())
        with db:
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity) VALUES('unknown-colour','P','bl-part',1)")
        snapshot = pictures.state(db)
        assert 'rows' not in snapshot
        for kind in pictures.TYPE_LABELS:
            for scope in ('missing', 'all'):
                rows = pictures.selection(db, 'existing', scope, [kind])
                cells = [snapshot['matrix'][k][scope] for k in (kind, '?')]
                assert sum(c['count'] for c in cells) == len(rows)
                assert sum(c['unresolved'] for c in cells) == sum(r['unresolved'] for r in rows)
                assert sum(c['unknown_colour'] for c in cells) == sum(
                    r['item_type'] == 'P' and r['color_id'] is None and not r['unresolved'] for r in rows)
        rows = pictures.selection(db, 'existing', 'missing', pictures.TYPE_LABELS)
        assert sum(v['missing']['count'] for v in snapshot['matrix'].values()) == len(rows)
        assert pictures.queue(db, 'existing', 'missing', pictures.TYPE_LABELS)[1] == len(rows)


def test_settings_size_queries_and_no_picture_file_checks(app, migrated, monkeypatch):
    import importlib
    connections = importlib.import_module('brickwork.core.connect')
    with closing(connect(migrated)) as db, db:
        db.executemany("INSERT INTO items(item_type,item_no,name) VALUES('S',?,?)",
                       [(f'cost-{n}', 'Held identity ' + 'x' * 200) for n in range(600)])
        db.executemany("INSERT INTO wishlist(item_type,item_no) VALUES('S',?)",
                       [(f'cost-{n}',) for n in range(600)])
    client = logged_in(app)
    queries = []
    original = connections.connect
    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(queries.append)
        return db
    monkeypatch.setattr('brickwork.core.admin.connect', traced)
    # Fail specifically on picture-file checks; Flask may inspect template files.
    original_is_file = Path.is_file
    original_stat = Path.stat
    def guarded(method):
        def call(path, *args, **kwargs):
            assert 'data/images' not in path.as_posix(), 'Settings checked a picture file'
            return method(path, *args, **kwargs)
        return call
    monkeypatch.setattr(Path, 'is_file', guarded(original_is_file))
    monkeypatch.setattr(Path, 'stat', guarded(original_stat))
    response = client.get('/manage/settings')
    assert response.status_code == 200
    assert len(response.data) < 100_000
    assert b'data-picture-identities' not in response.data
    assert b'data-picture-counts' in response.data
    assert b'cost-599' not in response.data
    assert queries, "Settings SQL was not traced"
    assert len(queries) <= 30


def test_receipt_reports_actual_count_and_changed_estimate(app, migrated, monkeypatch):
    client = logged_in(app)
    client.get('/manage/settings')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', lambda: None)
    response = client.post('/manage/settings', data=dict(
        action='pictures', source='existing', scope='missing', types=['S'],
        csrf_token=token, expected_count='999'))
    assert response.status_code == 302
    with closing(connect(migrated)) as db:
        job = db.execute("SELECT * FROM jobs WHERE kind='picture_refresh'").fetchone()
        receipt = json.loads(job['payload'])
        count = len(receipt['identities'])
        assert count != 999 and receipt['expected_count'] == 999
        # Changing an estimate must not queue duplicate work.
        assert pictures.queue(db, 'existing', 'missing', ['S'], expected_count=998) == (job['id'], count)
        assert db.execute("SELECT count(*) FROM jobs WHERE kind='picture_refresh'").fetchone()[0] == 1
    html = client.get('/manage/jobs').get_data(as_text=True)
    assert f'{count} picture identities queued' in html
    assert 'Dialog estimate 999' in html and 'changed before confirmation' in html


def test_large_picture_job_yields_and_measures_stretches(migrated, monkeypatch):
    import time
    import inspect
    from brickwork.core import pipeline as module
    with closing(connect(migrated)) as db:
        with db:
            for index in range(320):
                number = f'fixture-{index}'
                db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S',?,?)", (number, number))
                db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity) VALUES(?,'S',?,1)", (number, number))
                path = migrated.parent / 'bl-images/S' / (number + '.png')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png())
        job, count = pictures.queue(db, 'existing', 'all', ['S'])
        intervals = []
        identities_yielded = []
        previous = time.perf_counter()
        def checkpoint(connection):
            nonlocal previous
            assert not connection.in_transaction
            now = time.perf_counter()
            intervals.append(now - previous)
            caller = inspect.currentframe().f_back
            if isinstance(caller.f_locals.get('rows'), enumerate):
                identities_yielded.append(1)
            previous = now
        monkeypatch.setattr(module, 'yield_worker', checkpoint)
        queries = []
        db.set_trace_callback(queries.append)
        pipeline = Pipeline(db, emit=lambda *args: None)
        # Measure the whole worker path, including initialization and cache scan.
        assert pipeline.run(job)['state'] == 'done'
        intervals.append(time.perf_counter() - previous)
        db.set_trace_callback(None)
        # Checkpoints and image events cost a bounded number of queries per
        # identity; no per-identity scan of all identities or steps is needed.
        assert len(queries) < count * 40 + 200
        assert len(identities_yielded) == count
        assert db.execute("SELECT count(*) FROM import_calls WHERE job_id=? AND operation LIKE 'picture_identity:%'", (job,)).fetchone()[0] == count
        print(f'320-identity fixture: {len(intervals)} yield boundaries; longest stretch {max(intervals)*1000:.2f} ms')
        # Finished identities also yield during checkpoint replay.
        saved = pipeline.status(job)
        before = len(identities_yielded)
        pictures.run(pipeline, saved)
        assert len(identities_yielded) - before == count


def test_orphan_restart_claim_and_concurrent_workers(migrated, monkeypatch):
    import threading
    from brickwork.core.pipeline import worker
    job_started = threading.Event()
    release = threading.Event()
    processed = []
    with closing(connect(migrated)) as db:
        job, count = pictures.queue(db, 'existing', 'all', ['S'])
        pipeline = Pipeline(db, emit=lambda *args: None)
        original = pictures.run
        # Simulate interruption after one durable identity checkpoint.
        saved = pipeline.status(job)
        payload = json.loads(saved['payload'])
        one = {**saved, 'payload': json.dumps({**payload, 'identities': payload['identities'][:1]})}
        original(pipeline, one)
        with db:
            db.execute("UPDATE jobs SET state='running',payload=? WHERE id=?", (saved['payload'], job))
            db.execute('UPDATE import_steps SET total=? WHERE job_id=?', (count, job))
            db.execute('INSERT INTO import_owners VALUES(?,?)', (job, 99999999))
    def handler(pipeline, snapshot, step):
        processed.append(snapshot['id'])
        job_started.set()
        assert release.wait(5)
        return original(pipeline, snapshot)
    results = []
    def first():
        results.extend(worker(path=migrated, emit=lambda *args: None,
                              handlers={('pictures', 'picture_refresh'): handler}))
    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert job_started.wait(5)
        assert worker(path=migrated, emit=lambda *args: None) == []
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert processed == [job] and results[0]['state'] == 'done'
    with closing(connect(migrated)) as db:
        assert Pipeline(db).status(job)['attempts'] == 1
        assert db.execute('SELECT count(*) FROM import_owners').fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM import_calls WHERE job_id=? AND operation LIKE 'picture_identity:%'", (job,)).fetchone()[0] == count
    assert worker(path=migrated) == []


def test_startup_resume_once_and_interrupted_page(app, migrated, monkeypatch):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '1')
    from brickwork.web.views import bw_resume_imports
    from brickwork.core.pipeline import worker
    with closing(connect(migrated)) as db:
        job, _ = pictures.queue(db, 'existing', 'all', ['S'])
        with db:
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (job,))
            db.execute('INSERT INTO import_owners VALUES(?,?)', (job, 99999999))
    client = logged_in(app)
    assert 'Interrupted · Resume' in client.get('/manage/jobs').get_data(as_text=True)
    tasks = []
    monkeypatch.setattr(drainer, 'spawn', tasks.append)
    bw_resume_imports(app)
    bw_resume_imports(app)
    assert len(tasks) == 1
    tasks[0]()
    assert app.extensions['bw_import_worker_active'] is False
    assert worker(path=migrated) == []
    with closing(connect(migrated)) as db:
        assert Pipeline(db).status(job)['state'] == 'done'
        assert db.execute("SELECT count(*) FROM events WHERE entity=? AND via='app'", ('source:jobs',)).fetchone()[0] > 0


def test_cli_worker_does_not_import_gevent(migrated, monkeypatch):
    import builtins
    from brickwork.core.pipeline import worker
    original = builtins.__import__
    def without_gevent(name, *args, **kwargs):
        if name.startswith('gevent'):
            raise AssertionError('CLI must not require gevent')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_gevent)
    with closing(connect(migrated)) as db:
        job, _ = pictures.queue(db, 'existing', 'all', ['S'])
    assert worker(path=migrated)[0]['state'] == 'done'


def test_jobs_list_query_count(migrated):
    from brickwork.core import admin
    with closing(connect(migrated)) as db:
        pipeline = Pipeline(db)
        with db:
            for _ in range(320):
                pipeline.queue_steps('S', 'new-set', ('pictures',), sources=['picture_refresh'])
        queries = []
        db.set_trace_callback(queries.append)
        assert len(admin.jobs(db)) == 320
        assert len(queries) == 3
        db.set_trace_callback(None)


def test_real_gevent_hub_runs_between_picture_units(migrated):
    import subprocess
    import sys
    with closing(connect(migrated)) as db:
        pictures.queue(db, 'existing', 'all', ['S'])
    script = '''
import gevent.monkey
gevent.monkey.patch_all()
import gevent
import sys
from brickwork.core.pipeline import worker
turns = []
def observer():
    while True:
        turns.append(1)
        gevent.sleep(0)
watch = gevent.spawn(observer)
result = worker(path=sys.argv[1])
watch.kill()
assert result[0]['state'] == 'done'
assert len(turns) >= result[0]['steps'][0]['total']
'''
    result = subprocess.run([sys.executable, '-c', script, str(migrated)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_each_pipeline_step_yields(migrated, monkeypatch):
    from brickwork.core import pipeline as module
    db = connect(migrated)
    turns = []
    monkeypatch.setattr(module, 'yield_worker', lambda connection: turns.append(1))
    runner = Pipeline(db, emit=lambda *args: None,
                      handlers={(step, 'fixture'): lambda *args: None for step in module.STEPS})
    with db:
        job = runner.queue_steps('S', 'new-set', module.STEPS, sources=['fixture'])
    assert runner.run(job)['state'] == 'done'
    assert len(turns) >= len(module.STEPS)
    db.close()


def test_interrupted_budget_resume_preserves_deadline(app, migrated, monkeypatch):
    from brickwork.core.pipeline import worker
    clock = [datetime(2026, 10, 13, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    deadline = (clock[0] + timedelta(seconds=60)).isoformat()
    with closing(connect(migrated)) as db:
        job, _ = pictures.queue(db, 'existing', 'all', ['S'])
        with db:
            db.execute("UPDATE jobs SET state='waiting_for_budget',retry_at=? WHERE id=?", (deadline, job))
            db.execute("UPDATE import_steps SET state='waiting_for_budget',retry_at=? WHERE job_id=?", (deadline, job))
            db.execute('INSERT INTO import_owners VALUES(?,?)', (job, 99999999))
    client = logged_in(app)
    assert 'Interrupted · Resume' in client.get('/manage/jobs').get_data(as_text=True)
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    started = Mock()
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', started)
    assert client.post('/manage/jobs', data=dict(action='resume', job=job, csrf_token='wrong')).status_code == 400
    with closing(connect(migrated)) as db:
        events_before = db.execute('SELECT count(*) FROM events').fetchone()[0]
    assert client.post('/manage/jobs', data=dict(action='resume', job=job, csrf_token=token)).status_code == 302
    started.assert_called_once()
    with closing(connect(migrated)) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == events_before
    assert worker(path=migrated) == []
    with closing(connect(migrated)) as db:
        assert Pipeline(db).status(job)['retry_at'] == deadline
    clock[0] += timedelta(seconds=61)
    assert worker(path=migrated)[0]['state'] == 'done'
    assert worker(path=migrated) == []


def test_app_resumes_recovery_after_setup(apps, monkeypatch):
    from brickwork.core import drainer
    from brickwork.web import views
    scheduled = []
    monkeypatch.setattr(drainer, 'enabled', lambda: True)
    monkeypatch.setattr(views, 'bw_resume_imports', scheduled.append)
    application = apps('toni')
    assert scheduled == [application]


@pytest.mark.parametrize('budget_seconds,expected_sleep', [(1,1), (20,20), (7200,60)])
def test_startup_drainer_resumes_orphan_after_budget_deadline(app, migrated, monkeypatch, budget_seconds, expected_sleep):
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '1')
    from brickwork.web.views import bw_resume_imports
    clock = [datetime(2026, 10, 13, tzinfo=timezone.utc)]
    monkeypatch.setattr(base, 'now', lambda: clock[0])
    deadline = (clock[0] + timedelta(seconds=budget_seconds)).isoformat()
    with closing(connect(migrated)) as db:
        job, _ = pictures.queue(db, 'existing', 'all', ['S'])
        with db:
            db.execute("UPDATE jobs SET state='waiting_for_budget',retry_at=? WHERE id=?", (deadline, job))
            db.execute("UPDATE import_steps SET state='waiting_for_budget',retry_at=? WHERE job_id=?", (deadline, job))
            db.execute('INSERT INTO import_owners VALUES(?,?)', (job, 99999999))
    tasks = []
    monkeypatch.setattr(drainer, 'spawn', tasks.append)
    waits = []
    def sleep(seconds):
        if seconds:
            waits.append(seconds)
            # Advance to the deadline after checking the first poll interval.
            clock[0] += timedelta(seconds=budget_seconds)
    monkeypatch.setattr(drainer, 'sleep', sleep)
    bw_resume_imports(app)
    bw_resume_imports(app)
    assert len(tasks) == 1
    tasks[0]()
    assert waits == [expected_sleep]
    assert app.extensions['bw_import_worker_active'] is False
    with closing(connect(migrated)) as db:
        saved = Pipeline(db).status(job)
        assert saved['state'] == 'done' and saved['attempts'] == 1
        assert db.execute('SELECT count(*) FROM import_owners').fetchone()[0] == 0


def test_picture_refresh_scheduler_never_yields_with_transaction(migrated, app, monkeypatch):
    from tests.test_brickwork_pipeline import assert_safe_yields
    with closing(connect(migrated)) as db, app.app_context():
        turns = assert_safe_yields(monkeypatch, db)
        job, _ = pictures.queue(db, 'existing', 'all', ['S', 'P', 'M'])
        assert Pipeline(db, emit=lambda *args: None).run(job)['state'] == 'done'
        assert turns


@pytest.mark.parametrize('action,step', [('resume', None), ('retry', None), ('retry', 'pictures')])
def test_jobs_actions_require_editable_and_csrf(app, migrated, monkeypatch, action, step):
    with closing(connect(migrated)) as db:
        job, _ = pictures.queue(db, 'existing', 'all', ['S'])
        with db:
            db.execute("UPDATE jobs SET state=? WHERE id=?", ('running' if action == 'resume' else 'failed', job))
            db.execute("UPDATE import_steps SET state='failed' WHERE job_id=?", (job,))
    client = logged_in(app)
    client.get('/manage/jobs')
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    started = Mock()
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', started)
    data = dict(action=action, job=job)
    if step:
        data['step'] = step
    assert client.post('/manage/jobs', data=data).status_code == 400
    assert client.post('/manage/jobs', data={**data, 'csrf_token': 'wrong'}).status_code == 400
    monkeypatch.setitem(app.config, 'BW_READ_ONLY', True)
    assert client.post('/manage/jobs', data={**data, 'csrf_token': token}).status_code == 403
    started.assert_not_called()
    with closing(connect(migrated)) as db:
        assert db.execute('SELECT state FROM import_steps WHERE job_id=?', (job,)).fetchone()[0] == 'failed'
    monkeypatch.setitem(app.config, 'BW_READ_ONLY', False)
    assert client.post('/manage/jobs', data={**data, 'csrf_token': token}).status_code == 302
    started.assert_called_once()
    if action == 'retry':
        with closing(connect(migrated)) as db:
            assert db.execute('SELECT state FROM import_steps WHERE job_id=?', (job,)).fetchone()[0] == 'queued'


def test_bulk_failed_progress_keeps_counts_and_reason(migrated):
    with closing(connect(migrated)) as db:
        job, total = pictures.queue(db, 'existing', 'all', ['S'])
        db.commit()
        messages = []
        pipeline = Pipeline(db, emit=lambda event, payload: messages.append(payload))
        with db:
            db.execute("UPDATE import_steps SET count=1 WHERE job_id=?", (job,))
        pipeline.progress(job, 'pictures', 'failed', source='picture_refresh', error='Disk is full')
        payload = messages[-1]
        assert payload['message'] == f'Downloading images · 1 of {total} · failed · Disk is full'
        assert payload['state'] == 'failed' and payload['retry']
