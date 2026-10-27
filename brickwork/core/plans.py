"""Applied markers for import and sync plans, kept in the collection's `plan` table (#64; 4.0 design 5, M.8j).

A plan's rows live in a JSON file for 24 hours; whether it was applied is the database's to say. The marker is a `plan` row inserted in the
apply transaction, so it commits or rolls back with the rows it stands for, and a second apply of the same plan finds it (the `id` is the
primary key, so a second mark fails too). The plan file still records the result for its page, but never decides whether a plan applies.
"""
import json

from ..store4.connect import now

KINDS = {'sync': 'sync_pull', 'import': 'import'}


def applied(db, kind, plan_id):
    """The stored result of an applied plan (`{event_id, counts, at}`), or None."""
    row = db.execute('SELECT applied_at, event_id, counts_json FROM main.plan WHERE id=? AND kind=? AND applied_at IS NOT NULL',
                     (plan_id, KINDS[kind])).fetchone()
    if row is None:
        return None
    return dict(event_id=row['event_id'], counts=json.loads(row['counts_json'] or '{}'), at=row['applied_at'])


def mark(db, kind, plan_id, result, *, source=None, created_at=None):
    """Record the plan as applied (`result`: `event_id`, `counts`, `at`); a second mark for the same plan fails."""
    db.execute('INSERT INTO main.plan(id, kind, source, created_at, applied_at, event_id, counts_json) VALUES(?, ?, ?, ?, ?, ?, ?)',
               (plan_id, KINDS[kind], source, created_at or result['at'], result['at'], result.get('event_id'),
                json.dumps(result.get('counts') or {}, sort_keys=True)))

