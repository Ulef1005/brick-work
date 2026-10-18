"""Applied markers for import and sync plans, kept in the database (#64).

A plan file on disk said whether it was applied, written after the commit: two submits, or a crash
between the commit and the file write, applied the plan again. The marker is now a settings row,
checked and written inside the apply transaction, so it commits or rolls back with the rows it stands
for. The plan file still records the result, but no longer decides whether a plan applies.
"""
from datetime import timedelta
import json

from .sources.base import now

RECEIPTS = {'sync': 'bw_sync', 'import': 'bw_import'}
KEEP = timedelta(days=3)  # plan files live 24 hours; a marker outlives its plan, then goes


def _key(kind, plan_id):
    return f'plan_applied:{kind}:{plan_id}'


def applied(db, kind, plan_id, *, file_says_applied=False):
    """The stored result of an applied plan ({event_id, counts, at}), or None.

    Only when the plan file says applied but there is no marker (a plan applied by an older release, or
    a write that rolled back) is the plan's receipt looked up, alone or bundled in an API event; a
    receipt means applied, none means the write never committed.
    """
    row = db.execute('SELECT value FROM settings WHERE key=?', (_key(kind, plan_id),)).fetchone()
    if row:
        return json.loads(row[0])
    if not file_says_applied:
        return None
    needle = json.dumps(plan_id)
    for event in db.execute("SELECT id,entity,new_value FROM events WHERE ((entity=? AND field='receipt') OR entity='bw_api') "
                            "AND json_valid(new_value) AND (instr(new_value,?) OR instr(new_value,?)) ORDER BY id",
                            (RECEIPTS[kind], '"plan": ' + needle, '"plan":' + needle)):
        value = json.loads(event['new_value']) or {}
        receipts = [value] if event['entity'] != 'bw_api' else [_json(r.get('new_value')) for r in value.get('receipts', [])
                                                               if isinstance(r, dict) and r.get('entity') == RECEIPTS[kind]]
        for receipt in receipts:
            if isinstance(receipt, dict) and receipt.get('plan') == plan_id:
                return dict(event_id=event['id'], counts=receipt.get('counts', {}))
    return None


def _json(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def mark(db, kind, plan_id, result):
    """Record the plan as applied; a second mark for the same plan fails, so it cannot apply twice."""
    db.execute("DELETE FROM settings WHERE key LIKE 'plan_applied:%' AND json_extract(value,'$.at')<?",
               ((now() - KEEP).isoformat(),))
    db.execute('INSERT INTO settings(key,value) VALUES(?,?)', (_key(kind, plan_id), json.dumps(result, sort_keys=True)))
