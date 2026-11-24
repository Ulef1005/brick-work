"""Invented PDFs and bounded jobs, without a browser or network."""
from pathlib import Path
import subprocess

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from tests.app4 import app4, client, coll, csrf, pair, world  # noqa: F401
from brickwork.core import admin, instruction_thumbnails as thumbs
from brickwork.core.media import media_root
from brickwork.core.transaction import transaction


def pdf():
    import pypdfium2 as pdfium
    from io import BytesIO
    with pdfium.PdfDocument.new() as doc:
        doc.new_page(300, 400).close()
        stream = BytesIO()
        doc.save(stream)
        return stream.getvalue()


def attach(coll, item, content=None, label='Booklet 1 of 2'):
    with transaction(coll.db):
        return admin.attach_instruction(coll.db, media_root(coll.db), item, label, pdf() if content is None else content)


def test_render_invented_pdf(tmp_path):
    source, target = tmp_path / 'invented.pdf', tmp_path / 'preview.png'
    source.write_bytes(pdf())
    thumbs.render(source, target)
    with Image.open(target) as image:
        assert image.size == (240, 320)


def test_job_and_restore(coll, world):
    identifier = attach(coll, world.keep)
    root = media_root(coll.db)
    assert coll.db.execute('SELECT thumbnail_state FROM instruction_file WHERE id=?', (identifier,)).fetchone()[0] == 'pending'
    assert not list((root / 'data/instructions').glob('*.thumb.png'))
    result = thumbs.Thumbnails(coll.db).drain()
    assert result[0]['state'] == 'done'
    row = coll.db.execute('SELECT * FROM instruction_file WHERE id=?', (identifier,)).fetchone()
    assert row['thumbnail_state'] == 'ready'
    target = root / row['thumbnail_path']
    assert target.is_file()
    thumbs.queue_missing(coll.db)
    assert coll.db.execute('SELECT count(*) FROM job WHERE kind=?', (thumbs.KIND,)).fetchone()[0] == 1
    target.unlink()
    thumbs.queue_missing(coll.db)
    thumbs.queue_missing(coll.db)
    assert coll.db.execute('SELECT count(*) FROM job WHERE kind=?', (thumbs.KIND,)).fetchone()[0] == 2
    thumbs.Thumbnails(coll.db).drain()
    assert target.is_file()


@pytest.mark.parametrize('failure', ['corrupt', 'timeout', 'native', 'oversize'])
def test_failure_keeps_pdf(coll, world, monkeypatch, failure):
    identifier = attach(coll, world.keep, b'%PDF corrupt' if failure == 'corrupt' else None)
    if failure == 'oversize':
        monkeypatch.setattr(thumbs, 'MAX_BYTES', 1)
        monkeypatch.setattr(thumbs.subprocess, 'run', lambda *a, **kw: pytest.fail('Parser must not start'))
    elif failure in ('timeout', 'native'):
        def fail(*args, **kwargs):
            assert kwargs['timeout'] == 10
            assert isinstance(args[0], list) and 'shell' not in kwargs
            raise subprocess.TimeoutExpired(args[0], 10) if failure == 'timeout' else subprocess.CalledProcessError(-11, args[0])
        monkeypatch.setattr(thumbs.subprocess, 'run', fail)
    assert thumbs.Thumbnails(coll.db).drain()[0]['state'] == 'failed'
    row = coll.db.execute('SELECT * FROM instruction_file WHERE id=?', (identifier,)).fetchone()
    assert row['thumbnail_state'] == 'failed' and row['thumbnail_path'] is None
    assert (media_root(coll.db) / row['path']).is_file()
    assert not list((media_root(coll.db) / 'data/instructions').glob('*.tmp'))
    thumbs.queue_missing(coll.db)
    assert coll.db.execute('SELECT count(*) FROM job WHERE kind=?', (thumbs.KIND,)).fetchone()[0] == 1


def test_one_multiple_states_and_archive(client, coll, world):
    first = attach(coll, world.keep)
    url = f'/collection/item/{world.keep}'
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    assert not page.select('.bc-booklet-card, .bc-booklet-tile') and 'Open PDF · Booklet 1 of 2' in page.text   # one booklet keeps today's row
    second = attach(coll, world.keep, label='Booklet 2 of 2')
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    assert len(page.select('.bc-booklet-card')) == 2
    assert len(page.select('.bc-booklet-tile progress')) == 2
    thumbs.Thumbnails(coll.db).drain()
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    image = page.select_one('.bc-booklet-tile img')
    assert client.get(image['src']).mimetype == 'image/png'
    assert client.get(f'/manage/instructions/{first}/download').mimetype == 'application/pdf'
    with transaction(coll.db):
        coll.db.execute("UPDATE instruction_file SET thumbnail_state='failed' WHERE id=?", (second,))
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    assert page.select_one('.bc-booklet-tile.bc-no-image').text == 'No image'
    token = csrf(client)
    response = client.post('/collection/save/instruction-rename', json=dict(csrf_token=token, identifier=second, label='Second booklet'))
    assert response.status_code == 200
    response = client.post('/collection/save/instruction-archive', json=dict(csrf_token=token, identifier=second))
    assert response.status_code == 200
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    assert not page.select('.bc-booklet-card') and 'Show archived · 1' in page.text and 'Open PDF · Booklet 1 of 2' in page.text
    assert client.get(f'/manage/instructions/{second}/download?thumbnail=1').status_code == 404


def test_restore_archived_booklet(client, coll, world, monkeypatch):
    first = attach(coll, world.keep, label='Booklet 1 of 2')
    second = attach(coll, world.keep, label='Booklet 2 of 2')
    url = f'/collection/item/{world.keep}'
    token = csrf(client)
    assert client.post('/collection/save/instruction-archive', json=dict(csrf_token=token, identifier=second)).status_code == 200
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    form = page.select_one('.kit-disclosure form[data-bc-action="instruction-restore"]')
    assert form.select_one('[name=identifier]')['value'] == str(second)
    assert form.select_one('button')['aria-label'] == 'Restore Booklet 2 of 2' and form.select_one('[data-bc-form-message][role=status]') is not None
    response = client.post('/collection/save/instruction-restore', json=dict(csrf_token=token, identifier=second))
    assert response.status_code == 200 and response.json['message'] == 'Restored'
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    assert len(page.select('.bc-booklet-card')) == 2 and 'Show archived' not in page.text
    # Undo takes the restore back
    assert client.post('/collection/save/undo', json=dict(csrf_token=token, event_id=response.json['event_id'])).status_code == 200
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    assert 'Show archived · 1' in page.text
    # a live booklet cannot be restored
    assert client.post('/collection/save/instruction-restore', json=dict(csrf_token=token, identifier=first)).status_code == 400
    monkeypatch.setenv('BW_READ_ONLY', '1')
    page = BeautifulSoup(client.get(url).data, 'html.parser')
    assert 'Show archived · 1' in page.text and not page.select('form[data-bc-action="instruction-restore"]')
    assert client.post('/collection/save/instruction-restore', json=dict(csrf_token=token, identifier=second)).status_code == 403


def test_merge_carries_file_preview(coll, world):
    from brickwork.store4 import merge
    loser = coll.local('set', 'Local booklet set')
    identifier = attach(coll, loser)
    thumbs.Thumbnails(coll.db).drain()
    before = dict(coll.db.execute('SELECT * FROM instruction_file WHERE id=?', (identifier,)).fetchone())
    other = coll.local('set', 'Surviving set')
    merge.merge(coll.db, loser, other)
    after = dict(coll.db.execute('SELECT * FROM instruction_file WHERE id=?', (identifier,)).fetchone())
    assert after == {**before, 'item_id': other}


def test_upgrade_45_is_idempotent_and_matches_fresh(tmp_path):
    import sqlite3
    from contextlib import closing
    from brickwork.store4.connect import HERE, connect, upgrade
    path = tmp_path / 'old.db'
    with closing(sqlite3.connect(path)) as db:
        db.executescript((HERE / 'brickwork.sql').read_text().split('-- Instruction thumbnails, schema 4.6')[0])
        db.execute("INSERT INTO meta(key,value) VALUES('schema_version','4.5')")
        db.commit()
    assert upgrade(path) == upgrade(path) == '4.8'
    with closing(connect(path, tmp_path / 'catalogue.db')) as old, closing(connect(tmp_path / 'new.db', tmp_path / 'catalogue.db')) as new:
        assert list(old.execute('PRAGMA table_info(instruction_file)')) == list(new.execute('PRAGMA table_info(instruction_file)'))
        assert dict(old.execute('SELECT key,value FROM meta'))['upgraded_to_4.6']


def test_job_retries_and_read_only_actions(client, coll, world, monkeypatch):
    identifier = attach(coll, world.keep, b'%PDF corrupt')
    job = thumbs.Thumbnails(coll.db).drain()[0]['id']
    token = csrf(client)
    response = client.post('/collection/save/instruction-archive', json=dict(csrf_token=token, identifier=identifier))
    assert response.status_code == 200
    monkeypatch.setenv('BW_READ_ONLY', '1')
    page = BeautifulSoup(client.get(f'/collection/item/{world.keep}').data, 'html.parser')
    assert not page.select('form[data-bc-action^="instruction-"]')
    assert client.post('/collection/save/instruction-rename', json=dict(csrf_token=token, identifier=identifier, label='Changed')).status_code == 403
    monkeypatch.delenv('BW_READ_ONLY')
    runner = thumbs.runner_for(coll.db, thumbs.KIND)
    runner.queue_retry(job)
    assert runner.status(job)['state'] == 'queued'
    assert runner.drain()[0]['state'] == 'failed'  # an archived file is rendered too (so Undo never meets a stuck pending state); this one is corrupt
    assert coll.db.execute('SELECT thumbnail_state FROM instruction_file WHERE id=?', (identifier,)).fetchone()[0] == 'failed'


def test_preview_poll_runtime():
    from tests import rendered
    result = subprocess.run([rendered.need_node(), 'tests/toni_bw_thumbnails_runtime.cjs'], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_render_does_not_invalidate_rename_undo(coll, world):
    from brickwork.core import collection
    identifier = attach(coll, world.keep)
    event = admin.instruction_rename(coll.db, identifier, 'Changed title', undoable=True)
    thumbs.Thumbnails(coll.db).drain()
    collection.undo(coll.db, event)
    row = coll.db.execute('SELECT * FROM instruction_file WHERE id=?', (identifier,)).fetchone()
    assert row['label'] == 'Booklet 1 of 2' and row['thumbnail_state'] == 'ready'


def test_archive_before_the_job_runs_then_undo_leaves_no_stuck_preview(coll, world):
    from brickwork.core import collection
    identifier = attach(coll, world.keep)
    event = admin.instruction_archive(coll.db, identifier)
    assert thumbs.Thumbnails(coll.db).drain()[0]['state'] == 'done'
    collection.undo(coll.db, event)
    row = coll.db.execute('SELECT * FROM instruction_file WHERE id=?', (identifier,)).fetchone()
    assert row['archived_at'] is None and row['thumbnail_state'] == 'ready' and row['thumbnail_path']


def test_render_child_is_limited_and_has_a_minimal_environment(coll, world, monkeypatch):
    seen = {}
    def run(command, **kwargs):
        seen.update(kwargs)
        Path(command[-1]).write_bytes(b'png')
    monkeypatch.setattr(subprocess, 'run', run)
    identifier = attach(coll, world.keep)
    job = coll.db.execute("SELECT id FROM job WHERE kind=? ORDER BY id DESC", (thumbs.KIND,)).fetchone()[0]
    assert thumbs.Thumbnails(coll.db).run(job)['state'] == 'done'
    assert seen['env'] == thumbs.CHILD_ENV and 'HOME' not in seen['env']


def test_limit_child_sets_limits_and_tolerates_a_refusing_platform(monkeypatch):
    import resource
    calls = []
    monkeypatch.setattr(resource, 'setrlimit', lambda name, value: calls.append((name, value)))
    thumbs.limit_child()
    assert calls == [(resource.RLIMIT_AS, (thumbs.MEMORY_LIMIT,) * 2), (resource.RLIMIT_CPU, (thumbs.CPU_LIMIT,) * 2)]
    def refuse(name, value):
        raise ValueError('not supported')
    monkeypatch.setattr(resource, 'setrlimit', refuse)
    thumbs.limit_child()


def test_render_child_works_under_its_limits(tmp_path):
    source, target = tmp_path / 'a.pdf', tmp_path / 'a.png'
    source.write_bytes(pdf())
    subprocess.run([__import__('sys').executable, '-m', thumbs.__name__, str(source), str(target)], check=True, env=thumbs.CHILD_ENV, timeout=60)
    with Image.open(target) as image:
        assert image.size == (240, 320)
