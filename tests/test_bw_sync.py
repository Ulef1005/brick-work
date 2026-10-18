"""Collection sync (#10) against mocked Rebrickable and Brickset transports. All data invented; no network."""
from contextlib import closing
import json
import logging
import sqlite3
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
import pytest

from brickwork.core import errors, sync
from brickwork.core.connect import connect
from brickwork.core.sources import base

PASSWORD = 'synthetic-password-never-stored'
TOKEN = 'rbusertoken0123456789abcdef'
HASH = 'bsuserhash0123456789'
SETS = ['10001-1', '10002-1', '10003-1', '10004-1', '10005-1']


class Rebrickable:
    """A small stateful Rebrickable: set lists 1 (owned), 2 (owned), 9 (wishlist)."""

    def __init__(self):
        self.lists = {1: {'10001-1': 2, '10002-1': 1, 'rb-only-9': 1}, 2: {'10003-1': 1}, 9: {'10004-1': 1}}
        self.calls = []
        self.token_reply = {'user_token': TOKEN}

    def __call__(self, request):
        url = urlparse(request.full_url)
        method = request.get_method()
        body = parse_qs(request.data.decode()) if request.data else {}
        self.calls.append((method, url.path, body))
        path = url.path.removeprefix('/api/v3/users/')
        if path == '_token/':
            return self.token_reply
        token, rest = path.split('/', 1)
        if token != TOKEN:
            reply = base.Reply(json.dumps({'detail': 'Invalid token.'}))
            reply.status = 401
            return reply
        parts = rest.strip('/').split('/')
        if parts == ['setlists']:
            return {'count': 3, 'next': None, 'results': [
                {'id': i, 'name': f'List {i}', 'num_sets': len(v)} for i, v in self.lists.items()]}
        list_id = int(parts[1])
        if len(parts) == 3 and method == 'GET':
            return {'count': len(self.lists[list_id]), 'next': None, 'results': [
                {'list_id': list_id, 'quantity': q, 'include_spares': True, 'set': {'set_num': n, 'name': 'Invented'}}
                for n, q in self.lists[list_id].items()]}
        if len(parts) == 3 and method == 'POST':
            self.lists[list_id][body['set_num'][0]] = int(body['quantity'][0])
            return {'quantity': int(body['quantity'][0])}
        number = parts[3]
        if method == 'PUT':
            self.lists[list_id][number] = int(body['quantity'][0])
            return {'quantity': int(body['quantity'][0])}
        if method == 'DELETE':
            del self.lists[list_id][number]
            return ''
        raise AssertionError((method, url.path))


class Brickset:
    def __init__(self):
        self.owned = {'10001-1': (1001, 1), '10005-1': (1005, 3)}
        self.wanted = {'10002-1': 1002}
        self.ids = {'10001-1': 1001, '10002-1': 1002, '10003-1': 1003, '10004-1': 1004, '10005-1': 1005}
        self.calls = []

    def __call__(self, request):
        method = request.full_url.rsplit('/', 1)[1]
        body = {k: v[0] for k, v in parse_qs(request.data.decode()).items()}
        self.calls.append((method, body))
        if method == 'login':
            if body['password'] != PASSWORD:
                return {'status': 'error', 'message': 'Invalid username and/or password'}
            return {'status': 'success', 'hash': HASH}
        if body.get('userHash') != HASH:
            return {'status': 'error', 'message': 'Invalid user hash'}
        if method == 'checkUserHash':
            return {'status': 'success'}
        if method == 'getSets':
            params = json.loads(body['params'])

            def row(number, set_id, qty=None):
                n, v = number.rsplit('-', 1)
                return {'setID': set_id, 'number': n, 'numberVariant': int(v), 'collection': {'qtyOwned': qty or 0}}
            if params.get('owned'):
                rows = [row(n, i, q) for n, (i, q) in self.owned.items()]
            elif params.get('wanted'):
                rows = [row(n, i) for n, i in self.wanted.items()]
            else:
                rows = [row(n, self.ids[n]) for n in params['setNumber'].split(',') if n in self.ids]
            return {'status': 'success', 'matches': len(rows), 'sets': rows}
        if method == 'setCollection':
            params = json.loads(body['params'])
            number = next(n for n, i in self.ids.items() if i == int(body['SetID']))
            if 'own' in params:
                if params['own']:
                    self.owned[number] = (int(body['SetID']), params['qtyOwned'])
                else:
                    self.owned.pop(number, None)
            if 'want' in params:
                if params['want']:
                    self.wanted[number] = int(body['SetID'])
                else:
                    self.wanted.pop(number, None)
            return {'status': 'success'}
        raise AssertionError(method)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters.RebrickableUser, 'minimum_spacing', 0)
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'synthetic-brickset-key')
    for name in ('BW_REBRICKABLE_USER_TOKEN', 'BW_BRICKSET_USER_HASH'):
        monkeypatch.delenv(name, raising=False)
    with closing(sqlite3.connect(tmp_path / 'bricklink-catalog.db')) as cat, cat:
        cat.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT,normalized_name TEXT,category TEXT)')
        cat.executemany("INSERT INTO items VALUES('S',?,?,NULL,NULL)", [(n, 'Invented ' + n) for n in SETS])
    path = tmp_path / 'brickwork.db'
    with closing(connect(path)) as db:
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','10003-1','Invented 10003-1')")
        db.execute("INSERT INTO copies(id,item_type,set_no) VALUES('here-1','S','10003-1'),('here-2','S','10003-1')")
        db.commit()
    db = connect(path)
    yield db
    db.close()


def everything(db):
    rows = []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        rows += [json.dumps(list(r), default=repr) for r in db.execute(f'SELECT * FROM "{table}"')]
    return '\n'.join(rows)


def test_connect_stores_only_the_token(store, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    remote = Rebrickable()
    state = sync.connect(store, 'rebrickable', 'synthetic-user', PASSWORD, http=remote)
    assert state['user']['configured'] and state['user']['origin'] == 'stored'
    assert PASSWORD not in everything(store) and TOKEN not in everything(store)
    assert PASSWORD not in json.dumps(state) and PASSWORD not in caplog.text
    leaked = [p.name for p in tmp_path.rglob("*") if p.is_file() and PASSWORD.encode() in p.read_bytes()]
    assert not leaked, leaked
    remote.token_reply = {'non_field_errors': ['Unable to log in']}
    with pytest.raises(errors.ValidationFailed) as refused:
        sync.connect(store, 'rebrickable', 'synthetic-user', 'wrong-' + PASSWORD, http=remote)
    assert PASSWORD not in str(refused.value) and 'synthetic-user' not in str(refused.value)
    bs = Brickset()
    with pytest.raises(errors.ValidationFailed):
        sync.connect(store, 'brickset', 'synthetic-user', 'nope-' + PASSWORD, http=bs)
    sync.connect(store, 'brickset', 'synthetic-user', PASSWORD, http=bs)
    assert sync.test(store, 'brickset', http=bs)['ok'] and HASH not in everything(store)


def test_paste_remove_and_rejected_token(store):
    sync.paste(store, 'rebrickable', 'wrong-token-1234567')
    with pytest.raises(base.KeyRejected):
        sync.test(store, 'rebrickable', http=Rebrickable())
    assert not sync.remove(store, 'rebrickable')['user']['configured']
    with pytest.raises(base.SourceNotConfigured):
        sync.plan_pull(store, 'rebrickable', http=Rebrickable())


def rebrickable_ready(store, remote=None):
    sync.paste(store, 'rebrickable', TOKEN)
    sync.link(store, 'rebrickable', {'owned': [1, 2], 'wishlist': 9, 'send_to': 1})
    return remote or Rebrickable()


def test_pull_plan_rows(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    rows = {r['key']: r for r in plan['rows']}
    assert rows['owned:10001-1']['state'] == 'add' and rows['owned:10001-1']['count'] == 2
    assert rows['owned:10003-1']['state'] == 'differs' and rows['owned:10003-1']['here'] == 2
    assert rows['wanted:10004-1']['state'] == 'add'
    assert [u['remote_no'] for u in plan['unmatched']] == ['rb-only-9']
    assert TOKEN not in everything(store)
    with closing(sqlite3.connect(':memory:')):
        pass
    assert not store.execute("SELECT 1 FROM copies WHERE set_no='10001-1'").fetchone()


def test_apply_pull_one_event_flag_and_exact_undo(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    before = store.execute('SELECT max(id) FROM events').fetchone()[0]
    result = sync.apply_pull(store, plan['id'])
    assert [r[0] for r in store.execute('SELECT entity FROM events WHERE id>? AND entity NOT LIKE ?', (before, 'source:%'))] == ['bw_sync']
    copies = store.execute("SELECT * FROM copies WHERE set_no='10001-1'").fetchall()
    assert len(copies) == 2 and all(c['condition'] is None and c['completeness'] is None for c in copies)
    flag = store.execute("SELECT f.name FROM item_flags i JOIN flags f ON f.id=i.flag_id WHERE i.entity_id=?", (copies[0]['id'],)).fetchone()
    assert flag['name'] == 'imported from Rebrickable'
    assert store.execute("SELECT quantity FROM wishlist WHERE item_no='10004-1' AND archived_at IS NULL").fetchone()[0] == 1
    assert result['counts'] == dict(copies=3, wishes_added=1, wishes_changed=0)  # 2 + 1 (10002-1)
    assert sync.apply_pull(store, plan['id'])['already_applied']
    assert store.execute("SELECT count(*) FROM jobs WHERE item_type='S'").fetchone()[0] >= 0
    sync.undo(store, result['event_id'])
    assert not store.execute("SELECT 1 FROM copies WHERE set_no='10001-1' AND archived_at IS NULL").fetchone()
    assert not store.execute("SELECT 1 FROM wishlist WHERE archived_at IS NULL").fetchone()
    assert not store.execute("SELECT 1 FROM flags").fetchone()
    assert sync.undo(store, result['event_id'])['already_undone']


def test_undo_guarded_and_ticks(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    with pytest.raises(errors.ValidationFailed):
        sync.apply_pull(store, plan['id'], ['owned:10003-1'])  # nothing to pull: not tickable
    result = sync.apply_pull(store, plan['id'], ['owned:10001-1'])
    assert result['counts']['copies'] == 2 and result['counts']['wishes_added'] == 0
    store.execute("UPDATE copies SET note='later' WHERE set_no='10001-1'")
    store.commit()
    with pytest.raises(ValueError, match='changed since'):
        sync.undo(store, result['event_id'])


def test_changed_in_both_places_is_a_conflict(store):
    remote = rebrickable_ready(store)
    sync.apply_pull(store, sync.plan_pull(store, 'rebrickable', http=remote)['id'])
    remote.lists[1]['10001-1'] = 4      # changed there
    store.execute("UPDATE copies SET archived_at='2026-01-01' WHERE id=(SELECT id FROM copies WHERE set_no='10001-1' LIMIT 1)")
    store.commit()                      # changed here
    rows = {r['key']: r for r in sync.plan_pull(store, 'rebrickable', http=remote)['rows']}
    conflict = rows['owned:10001-1']
    assert conflict['state'] == 'conflict' and conflict['action'] is None and conflict['remote'] == 4 and conflict['here'] == 1


def test_send_plan_untick_removal_and_results(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_send(store, 'rebrickable', http=remote)
    rows = {r['key']: r for r in plan['rows']}
    assert rows['owned:10003-1']['send'] == 2 and rows['owned:10003-1']['action'] == 'send'
    assert rows['owned:10001-1']['state'] == 'remove' and rows['owned:10001-1']['action'] is None
    assert 'cannot reverse' in plan['note']
    result = sync.apply_send(store, plan['id'], http=remote)
    # Default ticks only: list 2 keeps its one, list 1 (send_to) gets the second; no removal sent.
    assert {r['key']: r['result'] for r in result['rows']} == {'owned:10003-1': 'sent'}
    assert remote.lists[1]['10003-1'] == 1 and remote.lists[2]['10003-1'] == 1 and remote.lists[1]['10001-1'] == 2
    assert 'not undone' in result['note']
    # Sending to list 2 cannot lower list 1's count: that row fails with a reason, the next one still runs.
    sync.link(store, 'rebrickable', {'send_to': 2})
    store.execute("UPDATE copies SET archived_at='2026-01-01' WHERE id='here-2'")
    store.commit()
    plan = sync.plan_send(store, 'rebrickable', http=remote)
    result = sync.apply_send(store, plan['id'], ['owned:10003-1', 'owned:10001-1'], http=remote)
    outcome = {r['key']: r['result'] for r in result['rows']}
    assert outcome == {'owned:10003-1': 'sent', 'owned:10001-1': 'failed'}
    assert sync.status(store, 'rebrickable')['waiting'] == 1


def test_send_removal_only_when_ticked_and_budget_pause(store, monkeypatch):
    remote = rebrickable_ready(store)
    sync.link(store, 'rebrickable', {'owned': [1], 'send_to': 1})
    plan = sync.plan_send(store, 'rebrickable', http=remote)
    result = sync.apply_send(store, plan['id'], ['owned:10001-1', 'owned:10002-1'], http=remote)
    assert all(r['result'] == 'sent' for r in result['rows']) and '10001-1' not in remote.lists[1]
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '1')
    plan_rows = sync.plan_send  # budget is spent by the fetch itself on the next run
    with pytest.raises(base.WaitingForBudget):
        plan_rows(store, 'rebrickable', http=remote)


def test_brickset_pull_and_send(store):
    bs = Brickset()
    sync.paste(store, 'brickset', HASH)
    plan = sync.plan_pull(store, 'brickset', http=bs)
    rows = {r['key']: r for r in plan['rows']}
    assert rows['owned:10005-1']['count'] == 3 and rows['wanted:10002-1']['state'] == 'add'
    sync.apply_pull(store, plan['id'])
    send = sync.plan_send(store, 'brickset', http=bs)
    rows = {r['key']: r for r in send['rows']}
    assert rows['owned:10003-1']['send'] == 2 and rows['owned:10003-1']['action'] == 'send'
    sync.apply_send(store, send['id'], http=bs)
    assert bs.owned['10003-1'] == (1003, 2)
    assert all(c[0] != 'setCollection' or json.loads(c[1]['params']).get('own') != 0 for c in bs.calls)


def test_link_validation(store):
    with pytest.raises(errors.ValidationFailed):
        sync.link(store, 'rebrickable', {'owned': [1], 'wishlist': 1})
    with pytest.raises(errors.ValidationFailed):
        sync.link(store, 'brickset', {'owned': [1]})
    with pytest.raises(errors.NotFound):
        sync.status(store, 'bricklink')


def test_send_pauses_on_budget_and_retries_only_unsent(store, monkeypatch):
    remote = rebrickable_ready(store)
    sync.link(store, 'rebrickable', {'owned': [1], 'send_to': 1})
    store.execute("INSERT INTO items(item_type,item_no) VALUES('S','10005-1')")
    store.execute("INSERT INTO copies(id,item_type,set_no) VALUES('here-5','S','10005-1')")
    store.commit()
    plan = sync.plan_send(store, 'rebrickable', http=remote)
    sendable = [r['key'] for r in plan['rows'] if r['action']]
    assert len(sendable) == 2
    used = base.budget_used(store, 'rebrickable', base.now().date().isoformat())
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', str(used + 1))
    first = {r['key']: r['result'] for r in sync.apply_send(store, plan['id'], http=remote)['rows']}
    assert sorted(first.values()) == ['paused', 'sent']
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '1000')
    calls = len(remote.calls)
    second = {r['key']: r['result'] for r in sync.apply_send(store, plan['id'], http=remote)['rows']}
    assert sorted(second.values()) == ['sent', 'sent'] and len(remote.calls) == calls + 1


def test_api_scopes_connect_pull_and_undo(store, monkeypatch):
    from flask import Flask
    from brickwork.api import register
    from brickwork.core.sync import adapters
    path = store.execute('PRAGMA database_list').fetchone()[2]
    remote = Rebrickable()
    monkeypatch.setattr(adapters, 'transport', remote)
    monkeypatch.setenv('BW_API_TOKEN', 'synthetic-bootstrap')
    monkeypatch.setenv('BW_DB_PATH', path)
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.delenv('BW_READ_ONLY', raising=False)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    register(app)
    client = app.test_client()
    admin = {'Authorization': 'Bearer synthetic-bootstrap'}

    def token(scope):
        return {'Authorization': 'Bearer ' + client.post('/api/v1/tokens', headers=admin,
                json={'name': scope + '-client', 'scopes': [scope]}).json['data']['secret']}
    reader, writer = token('read'), token('write')
    body = {'username': 'synthetic-user', 'password': PASSWORD}
    assert client.post('/api/v1/sources/rebrickable/user/connect', headers=writer, json=body).status_code == 403
    made = client.post('/api/v1/sources/rebrickable/user/connect', headers=dict(admin, **{'Idempotency-Key': 'connect-1'}), json=body)
    assert made.status_code == 200, made.json
    assert made.json['data']['user']['configured'] and PASSWORD not in made.get_data(as_text=True)
    assert PASSWORD not in everything(store) and TOKEN not in everything(store)
    assert client.get('/api/v1/sync/rebrickable', headers=reader).json['data']['credentials']['user']['configured']
    assert client.put('/api/v1/sync/rebrickable/link', headers=reader, json={'owned': [1, 2]}).status_code == 403
    assert client.put('/api/v1/sync/rebrickable/link', headers=writer, json={'owned': [1, 2], 'wishlist': 9, 'send_to': 1}).status_code == 200
    plan = client.post('/api/v1/sync/rebrickable/pull/plan', headers=writer)
    assert plan.status_code == 201, plan.json
    plan_id = plan.json['data']['id']
    applied = client.post('/api/v1/sync/rebrickable/pull/apply', headers=dict(writer, **{'Idempotency-Key': 'pull-1'}),
                          json={'plan_id': plan_id})
    assert applied.status_code == 200, applied.json
    replay = client.post('/api/v1/sync/rebrickable/pull/apply', headers=dict(writer, **{'Idempotency-Key': 'pull-1'}),
                         json={'plan_id': plan_id})
    assert replay.json['idempotent_replay'] and replay.json['event_id'] == applied.json['event_id']
    assert store.execute("SELECT count(*) FROM copies WHERE set_no='10001-1' AND archived_at IS NULL").fetchone()[0] == 2
    undone = client.post(f"/api/v1/events/{applied.json['event_id']}/undo", headers=dict(writer, **{'Idempotency-Key': 'undo-1'}))
    assert undone.status_code == 200, undone.json
    assert not store.execute("SELECT 1 FROM copies WHERE set_no='10001-1' AND archived_at IS NULL").fetchone()
    send = client.post('/api/v1/sync/rebrickable/send/plan', headers=writer).json['data']
    assert client.post('/api/v1/sync/rebrickable/send/apply', headers=writer, json={'plan_id': send['id']}).status_code == 403
    sent = client.post('/api/v1/sync/rebrickable/send/apply', headers=admin, json={'plan_id': send['id']})
    assert sent.status_code == 200 and 'not undone' in sent.json['data']['note']
    assert client.post('/api/v1/sync/bricklink/pull/plan', headers=writer).status_code == 404


def test_cli_status_pull_and_apply(store, monkeypatch, capsys):
    from brickwork.core.sync import adapters
    from brickwork.web import cli
    remote = rebrickable_ready(store)
    monkeypatch.setattr(adapters, 'transport', remote)
    monkeypatch.setenv('BW_DB_PATH', store.execute('PRAGMA database_list').fetchone()[2])
    assert cli.main(['sync', 'rebrickable', 'status', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['credentials']['user']['configured']
    assert cli.main(['sync', 'rebrickable', 'pull', '--json']) == 0
    plan = json.loads(capsys.readouterr().out)
    assert cli.main(['sync', 'rebrickable', 'pull', '--apply', plan['id'], '--tick', 'owned:10001-1', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['counts']['copies'] == 2
    assert store.execute("SELECT via FROM events WHERE entity='bw_sync'").fetchone()[0] == 'cli'
    assert cli.main(['sync', 'rebrickable', 'connect', '--json']) == 1
    assert '--username' in capsys.readouterr().err


def test_a_second_submit_after_a_lost_file_write_applies_nothing(store):
    """#64: the plan file not yet marked (a second tab, or a crash before the file write)."""
    plan = sync.plan_pull(store, 'rebrickable', http=rebrickable_ready(store))
    first = sync.apply_pull(store, plan['id'])
    stale = sync.load_plan(store, plan['id'], 'pull')
    stale.pop('applied')
    sync._store_plan(store, stale)
    copies = store.execute('SELECT count(*) FROM copies').fetchone()[0]
    again = sync.apply_pull(store, plan['id'])
    assert again['already_applied'] and again['event_id'] == first['event_id']
    assert store.execute('SELECT count(*) FROM copies').fetchone()[0] == copies


def test_a_rolled_back_apply_can_be_applied_again(store):
    """#64: inside an outer write that fails, the marker rolls back with the rows."""
    from brickwork.core.transaction import transaction
    plan = sync.plan_pull(store, 'rebrickable', http=rebrickable_ready(store))
    with pytest.raises(RuntimeError):
        with transaction(store):
            sync.apply_pull(store, plan['id'])
            raise RuntimeError('outer write failed')
    assert not store.execute("SELECT 1 FROM copies WHERE set_no='10001-1'").fetchone()
    result = sync.apply_pull(store, plan['id'])
    assert not result['already_applied'] and result['counts']['copies'] == 3
