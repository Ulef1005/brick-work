"""Follow-ups from the review of #59-#64."""
from contextlib import closing
import io
import logging
import os

import pytest
from flask import Flask

from brickwork import limits
from brickwork.core import plans
from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app, app as api_app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

ADMIN = {'Authorization': 'Bearer synthetic-bootstrap'}


def check(app, body, key):
    return app.test_client().post('/api/v1/copies/c1/check', json=body, headers=dict(ADMIN, **{'Idempotency-Key': key}))


def test_check_returns_the_checker_event_with_an_undo_link(populated):  # noqa: F811
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('checked','Set is checked','status',0)")
    started = check(populated, {'action': 'start'}, 'rv-1')
    session = started.json['data']['session']['id']
    moved = check(populated, {'action': 'next', 'session': session}, 'rv-2')
    assert moved.status_code == 200
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        entity = db.execute('SELECT entity FROM events WHERE id=?', (moved.json['event_id'],)).fetchone()[0]
    assert entity.startswith('checker:')
    assert moved.json['undo_url'] == f"/api/v1/events/{moved.json['event_id']}/undo"
    undone = populated.test_client().post(moved.json['undo_url'], headers=dict(ADMIN, **{'Idempotency-Key': 'rv-undo'}))
    assert undone.status_code == 200, undone.json


def test_a_checker_operation_seen_by_another_token_is_not_a_500(populated):  # noqa: F811
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('checked','Set is checked','status',0)")
    first = check(populated, {'action': 'start'}, 'rv-shared')
    other = populated.test_client().post('/api/v1/tokens', json={'name': 'other', 'scopes': ['read', 'write']}, headers=ADMIN).json['data']['secret']
    again = populated.test_client().post('/api/v1/copies/c1/check', json={'action': 'start'},
                                         headers={'Authorization': 'Bearer ' + other, 'Idempotency-Key': 'rv-shared'})
    assert first.status_code == 200 and again.status_code == 200, again.json


@pytest.mark.parametrize('path,megabytes', [('/workbench/part-to-inventory/detect', 8), ('/manage/add/review', 8),
    ('/workbench/orders/action/document', 1), ('/collection/save/photo', 15), ('/manage/instructions', 20),
    ('/api/v1/copies/c1/photos', 15), ('/api/v1/instruction-files', 20), ('/manage/import-legacy/upload', None)])
def test_upload_caps_per_route(path, megabytes):
    app = Flask('caps')
    with app.test_request_context(path, method='POST', content_type='multipart/form-data; boundary=x'):
        expected = limits.upload_limit() if megabytes is None else megabytes * limits.MB + limits.FRAMING
        assert limits.body_limit() == expected


def test_session_key_second_starter_reads_the_first_and_mode_is_tightened(tmp_path, monkeypatch):
    from brickwork.web.auth import session_key
    monkeypatch.setenv('BW_DB_PATH', str(tmp_path / 'brickwork.db'))
    first = session_key()
    key = tmp_path / 'session.key'
    key.chmod(0o644)
    assert session_key() == first and key.stat().st_mode & 0o777 == 0o600
    key.write_bytes(b'\xff\xfe')
    repaired = session_key()  # a damaged key is replaced, and the new one is kept
    assert len(repaired) >= 32 and session_key() == repaired
    assert not [p for p in tmp_path.iterdir() if p.name.startswith('.session.key.')]


def test_a_plan_applied_before_markers_is_recognised(api_app):  # noqa: F811
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        from brickwork.core.admin import audit
        audit(db, 'bw_sync', 'receipt', None, dict(plan='a' * 32, counts=dict(copies=2)), via='app')
        found = plans.applied(db, 'sync', 'a' * 32, file_says_applied=True)
        assert found['counts'] == {'copies': 2} and found['event_id']
        assert plans.applied(db, 'sync', 'a' * 32) is None  # no search on the path of a new plan
        assert plans.applied(db, 'sync', 'b' * 32, file_says_applied=True) is None
        assert plans.applied(db, 'import', 'a' * 32, file_says_applied=True) is None


def test_old_markers_are_pruned(api_app):  # noqa: F811
    import json
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("INSERT INTO settings(key,value) VALUES('plan_applied:sync:old',?)", (json.dumps(dict(at='2000-01-01T00:00:00+00:00')),))
        plans.mark(db, 'sync', 'c' * 32, dict(event_id=1, counts={}, at='2026-10-17T00:00:00+00:00'))
        assert not db.execute("SELECT 1 FROM settings WHERE key='plan_applied:sync:old'").fetchone()
