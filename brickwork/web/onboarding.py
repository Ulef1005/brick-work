"""#83: the guided first run as one resumable flow.

The steps' done state is read from the install itself (a catalogue build is active, a key is stored, the collection holds something), so the
flow cannot claim a step that did not happen. Only what the user chose is stored: the steps skipped for now. They sit in `onboarding.json`
beside the collection, which works before the collection file exists and travels with the data folder.
"""
import json
import os
import sqlite3

STEPS = ('catalogue', 'keys', 'collection')
FILE = 'onboarding.json'


def _path():
    from .admin_ops import brickwork_path
    return brickwork_path().parent / FILE


def skipped():
    """The steps the user skipped for now, in flow order; an unreadable file counts as none skipped."""
    try:
        data = json.loads(_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    chosen = data.get('skipped') if isinstance(data, dict) else None
    return [step for step in STEPS if isinstance(chosen, list) and step in chosen]


def mark(step, skip):
    """Skip a step for now, or take it back into the flow. Written atomically: a crash leaves the old file or the new one."""
    if step not in STEPS:
        raise ValueError(step)
    chosen = set(skipped())
    chosen.add(step) if skip else chosen.discard(step)
    path = _path()
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(dict(skipped=[s for s in STEPS if s in chosen])), encoding='utf-8')
    os.replace(temporary, path)


def collection_started():
    """The collection holds a copy or loose stock: step 3 is done however it got there (Add, an import, a sync)."""
    from .setup_state import _database
    try:
        with _database() as db:
            return bool(db.execute('SELECT EXISTS(SELECT 1 FROM main.copy) OR EXISTS(SELECT 1 FROM main.stock)').fetchone()[0])
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
