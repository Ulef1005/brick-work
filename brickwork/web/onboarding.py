"""#83: the guided first run as one resumable flow.

The steps' done state is read from the install itself (a catalogue build is active, a key is stored, the collection holds something), so the
flow cannot claim a step that did not happen. Only what the user chose is stored: the steps skipped for now. They sit in `onboarding.json`
beside the collection, which works before the collection file exists and travels with the data folder.
"""
import json
import os
import sqlite3

STEPS = ('catalogue', 'keys', 'collection', 'guide')
FILE = 'onboarding.json'


def _path():
    from .admin_ops import brickwork_path
    return brickwork_path().parent / FILE


def _load():
    try:
        data = json.loads(_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data):
    """Written atomically: a crash leaves the old file or the new one."""
    path = _path()
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data), encoding='utf-8')
    os.replace(temporary, path)


def skipped():
    """The steps the user skipped for now, in flow order; an unreadable file counts as none skipped."""
    chosen = _load().get('skipped')
    return [step for step in STEPS if isinstance(chosen, list) and step in chosen]


def guide_read():
    """#87: the guide was read to its end (its "Got it")."""
    return _load().get('read') == ['guide']


def mark(step, skip):
    """Skip a step for now, or take it back into the flow."""
    if step not in STEPS:
        raise ValueError(step)
    data, chosen = _load(), set(skipped())
    chosen.add(step) if skip else chosen.discard(step)
    _save(dict(data, skipped=[s for s in STEPS if s in chosen]))


def mark_read():
    _save(dict(_load(), read=['guide']))


def collection_started():
    """The collection holds a copy or loose stock: step 3 is done however it got there (Add, an import, a sync)."""
    from .setup_state import _database
    try:
        with _database() as db:
            return bool(db.execute('SELECT EXISTS(SELECT 1 FROM main.copy WHERE archived_at IS NULL) OR EXISTS(SELECT 1 FROM main.stock WHERE archived_at IS NULL)').fetchone()[0])
    except (sqlite3.Error, OSError, ValueError):
        return False


def states(done, can_edit, chosen):
    """Each step's state: done, current (the first open one, where the flow resumes), open, skipped, or waiting (it needs the catalogue,
    or changes are switched off). Keys never wait: the catalogue downloads without one (design 6.1)."""
    result, current = {}, None
    for step in STEPS:
        if done[step]:
            state = 'done'
        elif step == 'collection' and not (done['catalogue'] and can_edit):
            state = 'waiting'
        elif step in chosen:
            state = 'skipped'
        elif current is None:
            state, current = 'current', step
        else:
            state = 'open'
        result[step] = state
    return result


# #84: what each key gives and where it is made, for the keys step. The links are the sites' own key pages.
KEY_HELP = {
    'rebrickable': dict(gives='Part lists for sets newer than the catalogue, and pictures.', where='Get a Rebrickable key',
                        url='https://rebrickable.com/api/'),
    'bricklink': dict(gives='Prices, and placed orders from your BrickLink account. Four values: consumer key and secret, token and its secret.',
                      where='Get a BrickLink key', url='https://www.bricklink.com/v2/api/register_consumer.page'),
    'brickset': dict(gives='Set data such as retail prices, and set pictures.', where='Get a Brickset key',
                     url='https://brickset.com/tools/webservices/requestkey'),
}


def collection_summary():
    """#86: what the collection holds after step 3, and what is left to finish. An import leaves condition and completeness unset and tags
    each copy `imported from <site>`; the tags come with their copy counts so the summary can link the Collection filtered by each."""
    from .setup_state import _database
    try:
        with _database() as db:
            copies, unfinished = db.execute('SELECT count(*), count(*) FILTER (WHERE condition IS NULL) FROM main.copy WHERE archived_at IS NULL'
                                            ).fetchone()
            stock = db.execute('SELECT count(*) FROM main.stock WHERE archived_at IS NULL').fetchone()[0]
            wishes = db.execute('SELECT count(*) FROM main.wish WHERE archived_at IS NULL').fetchone()[0]
            imported = db.execute("SELECT f.name, count(DISTINCT c.id) FROM main.flag f JOIN main.copy_flag cf ON cf.flag_id=f.id "
                                  "JOIN main.copy c ON c.id=cf.copy_id AND c.archived_at IS NULL "
                                  "WHERE f.kind='tag' AND f.archived_at IS NULL AND lower(f.name) LIKE 'imported from %' "
                                  'GROUP BY f.id ORDER BY f.name').fetchall()
    except (sqlite3.Error, OSError, ValueError):
        return None
    return dict(copies=copies, unfinished=unfinished, stock=stock, wishes=wishes, imported=[(name, count) for name, count in imported])


# The pages a step-3 choice opens: while the flow sent the user there, they offer the way back to it.
RETURN_ENDPOINTS = {'web.bw_sync', 'web.bw_sync_link', 'web.bw_sync_plan', 'web.bw_import_legacy', 'web.bw_import_plan', 'web.bw_add'}
