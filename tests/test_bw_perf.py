"""Speed fixes: each keeps its output and is checked against the unoptimised result (4.0 store, M.8f).

Split out by M.8f: the Tools & Admin ones (hub counts, unresolved list, database check) are test_bw_perf_admin.py (M.8i) and the API ones
test_bw_perf_api.py (M.11). Removed with its premise: the 3.3 `copy_parts` cover index upgrade (the upgrade code went with M.8a; 4.0 creates
its indexes with the schema)."""
import json
from pathlib import Path
import re

from brickwork.core import admin, pictures, secrets
from brickwork.core.pipeline import Pipeline
from brickwork.core.sources import base
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def test_secret_values_read_once_per_display(monkeypatch):
    monkeypatch.setenv('BW_FIXTURE_KEY', 'swordfish-123456')
    calls = []
    real = secrets.secret_values
    monkeypatch.setattr(secrets, 'secret_values', lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setattr(base, 'secret_values', secrets.secret_values)
    value = {'rows': [{'a': 'x swordfish-123456 LEGO', 'b': ['swordfish-123456', 7]} for _ in range(50)], 'c': 'plain'}
    shown = admin.display(value)
    assert len(calls) == 1
    assert shown['rows'][0]['a'] == 'x [set] ' and shown['rows'][0]['b'] == ['[set]', 7] and shown['c'] == 'plain'
    assert base.redact('a swordfish-123456', []) == 'a swordfish-123456' and base.redact('a swordfish-123456') == 'a [set]'


def test_the_job_count_equals_the_job_list(coll, world, read):
    coll.db.execute('BEGIN IMMEDIATE')
    Pipeline(coll.db).queue_steps(world.keep, ['pictures'], via='app')
    Pipeline(coll.db).queue_steps(world.brick, via='app')
    coll.db.commit()
    with read() as db:
        listed = admin.jobs(db)
        assert admin.count_jobs(db) == len(listed) == 2
        assert [len(j['steps']) for j in listed] == [6, 1] and listed[0]['id'] > listed[1]['id']      # newest first, each with its steps


def test_pictures_state_matches_the_original_query(coll, world, read):
    """`pictures.state` counts in Python what one SQL over the held rows counts."""
    original = pictures.HELD + '''
        SELECT i.kind, count(*) total, sum(EXISTS(SELECT 1 FROM picture im WHERE im.item_id=h.item_id AND (im.color_id IS h.color_id OR im.color_id IS NULL))) present
        FROM held h JOIN item i ON i.id=h.item_id WHERE i.merged_into IS NULL GROUP BY i.kind'''
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/1.png','a')", (world.keep,))
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,?,'rebrickable_api','render','data/images/2.png','a')", (world.brick, world.red))
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,?,'rebrickable_api','render','data/images/3.png','a')", (world.plate, 7))
    with read() as db:
        expected = {r[0]: (r[1], r[2]) for r in db.execute(original)}
        state = pictures.state(db)
        got = {row['kind']: (row['total'], row['with_picture']) for row in state['summary'] if row['total']}
        assert got == expected and expected['set'] == (3, 1) and expected['part'][1] == 2
        assert {row['kind']: row['sources'] for row in state['summary']}['set']['bricklink'] == 1


def test_versioned_static_is_immutable_and_unversioned_is_not(client):
    html = client.get('/collection/sets').get_data(as_text=True)
    versioned = re.search(r'(/static/[^"\']+\?v=\d+)', html)[1]
    response = client.get(versioned)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'public, max-age=31536000, immutable'
    assert 'cookie' not in response.headers.get('Vary', '').lower() and 'Set-Cookie' not in response.headers
    assert 'X-Bw-Static-Immutable' not in response.headers
    plain = client.get(versioned.split('?')[0])
    assert 'immutable' not in plain.headers.get('Cache-Control', '')


def test_service_worker_precache_drops_splash_and_lockup_pngs():
    source = Path('static/web/toni/sw.js').read_text()
    assets = json.loads(re.search(r'const ASSETS = (\[.*?\]);', source, re.S)[1])
    assert not [a for a in assets if '/splash/' in a or re.search(r'lockup-.*\.png$', a)]
    manifest = Path('static/brickwork/manifest.webmanifest').read_text()
    assert '/static/brickwork/icons/icon-1024.png' in manifest and '/static/brickwork/icons/icon-1024.png' in assets
    assert all(Path(a.lstrip('/')).is_file() for a in assets)
