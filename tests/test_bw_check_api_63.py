"""#63: Check Set Parts through the API on a store that already has the "Set is checked" flag."""
from contextlib import closing
import os

from brickwork.core.connect import connect
from tests.test_bw_api_m1 import app  # noqa: F401
from tests.test_bw_api_m2 import populated  # noqa: F401

ADMIN = {'Authorization': 'Bearer synthetic-bootstrap'}


def post(app, body, key):
    return app.test_client().post('/api/v1/copies/c1/check', json=body, headers=dict(ADMIN, **{'Idempotency-Key': key}))


def with_flag(app):
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('checked','Set is checked','status',0)")
    return app


def events():
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        return [dict(r) for r in db.execute('SELECT id,entity,via,actor FROM events ORDER BY id')]


def test_every_call_works_once_the_flag_exists(populated):  # noqa: F811
    app = with_flag(populated)
    started = post(app, {'action': 'start'}, 'chk-1')
    assert started.status_code == 200, started.json
    session = started.json['data']['session']['id']
    for n, action in enumerate(('next', 'back', 'next'), 2):
        step = post(app, {'action': action, 'session': session}, f'chk-{n}')
        assert step.status_code == 200, step.json


def test_events_record_the_api_and_the_operation_id(populated):  # noqa: F811
    app = with_flag(populated)
    started = post(app, {'action': 'start'}, 'chk-ev-1')
    rows = {r['id']: r for r in events()}
    operation = rows[max(rows)]  # the idempotency record; the response names the checker's own event (its Undo)
    assert operation['entity'] == 'bw_api' and operation['via'] == 'api' and operation['actor'] == 'bootstrap'
    checker_rows = [r for r in rows.values() if r['entity'].startswith('checker:')]
    assert checker_rows and all(r['via'] == 'api' and r['actor'] == 'bootstrap' for r in checker_rows)
    assert all(r['id'] < operation['id'] for r in checker_rows)


def test_replay_returns_the_first_answer(populated):  # noqa: F811
    app = with_flag(populated)
    first = post(app, {'action': 'start'}, 'chk-replay')
    again = post(app, {'action': 'start'}, 'chk-replay')
    assert again.json['idempotent_replay'] and again.json['event_id'] == first.json['event_id']
