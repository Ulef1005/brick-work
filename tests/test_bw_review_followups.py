"""Follow-ups from the review of #59-#64: what waits for M.11d.

M.11c (issue #113) ported to API v2 the check and upload-cap tests (tests/test_api2_write_collection.py, tests/test_api2_writes.py) and the session
key test (tests/test_session_key.py). What is left is the plan markers of sync and import, which are the sync and import pieces of M.11d."""
from contextlib import closing
import os

from brickwork.core import plans
from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app as api_app  # noqa: F401


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
