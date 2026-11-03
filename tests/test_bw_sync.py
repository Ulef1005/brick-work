"""Collection sync (#10) on a 4.0 collection against mocked Rebrickable and Brickset transports (M.8j, issue #110). All data invented; no network.

The sets are the fixture catalogue's: `1000-1`, `1000-2`, `2070-1` and the two this file adds (`1000-3`, `1000-4`); `10018247-1` is a gear item, which
a pull places as loose stock, not as a copy (design 3.5). The API test (v1, 410 on this line) moved to test_bw_sync_api.py (M.11)."""
from contextlib import closing
import json
import logging
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
import pytest

from brickwork.core import errors, sync
from brickwork.core.connect import connect
from brickwork.core.sources import base
from tests.app4 import RICH, Coll, make_pair, table_digest

PASSWORD = 'synthetic-password-never-stored'
TOKEN = 'rbusertoken0123456789abcdef'
HASH = 'bsuserhash0123456789'
SETS = ['1000-1', '1000-2', '2070-1', '1000-3', '1000-4']
GEAR = '10018247-1'

# Two more Castle sets with a part list each, on top of RICH (invented, marked syn).
EXTRA = {
    'sets': RICH['sets'] + [['1000-3', 'Syn Castle Tower', 1992, 600, 2, ''], ['1000-4', 'Syn Castle Wall', 1993, 600, 2, '']],
    'inventories': RICH['inventories'] + [[9003, 1, '1000-3'], [9004, 1, '1000-4']],
    'inventory_parts': RICH['inventory_parts'] + [[9003, '3001', 4, 2, 'False', ''], [9004, '3023', 15, 2, 'False', '']],
}


class Rebrickable:
    """A small stateful Rebrickable: set lists 1 (owned), 2 (owned), 9 (wishlist)."""

    def __init__(self):
        self.lists = {1: {'1000-1': 2, '1000-2': 1, 'rb-only-9': 1}, 2: {'2070-1': 1, GEAR: 1}, 9: {'1000-3': 1}}
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
        self.owned = {'1000-1': (1001, 1), '1000-4': (1005, 3)}
        self.wanted = {'1000-2': 1002}
        self.ids = {'1000-1': 1001, '1000-2': 1002, '2070-1': 1003, '1000-3': 1004, '1000-4': 1005}
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
def pair(tmp_path):
    return make_pair(tmp_path, rich=True, extra_dump=EXTRA)


@pytest.fixture
def store(pair, tmp_path, monkeypatch):
    """A 4.0 collection with two copies of `2070-1` (`here-1`, `here-2` in the old text), keys in the environment, no network."""
    from brickwork.core.sync import adapters
    monkeypatch.setattr(adapters.RebrickableUser, 'minimum_spacing', 0)
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-rebrickable-key')
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'synthetic-brickset-key')
    for name in ('BW_REBRICKABLE_USER_TOKEN', 'BW_BRICKSET_USER_HASH'):
        monkeypatch.delenv(name, raising=False)
    with closing(connect(pair)) as db:
        coll = Coll(db)
        coll.add_copy('2070-1')
        coll.add_copy('2070-1')
    db = connect(pair)
    yield db
    db.close()


def everything(db):
    rows = []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        rows += [json.dumps(list(r), default=repr) for r in db.execute(f'SELECT * FROM "{table}"')]
    return '\n'.join(rows)


def live_copies(db, number):
    return db.execute("SELECT c.* FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=? AND c.archived_at IS NULL", (number,)).fetchall()


def key(db, number):
    """The `owned:<id>` row key of a set number."""
    return db.execute('SELECT id FROM main.item WHERE born_key=? UNION SELECT id FROM catalogue.item WHERE born_key=?', (number, number)).fetchone()[0]


def test_connect_stores_only_the_token(store, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    remote = Rebrickable()
    state = sync.connect(store, 'rebrickable', 'synthetic-user', PASSWORD, http=remote)
    assert state['user']['configured'] and state['user']['origin'] == 'stored'
    assert PASSWORD not in everything(store) and TOKEN not in everything(store)
    assert PASSWORD not in json.dumps(state) and PASSWORD not in caplog.text
    leaked = [p.name for p in tmp_path.rglob("*") if p.is_file() and p.suffix in ('.db', '.json') and PASSWORD.encode() in p.read_bytes()]
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


def test_the_link_lives_on_sync_state(store):
    rebrickable_ready(store)
    row = store.execute("SELECT link_json, baseline_json, last_pull_json, last_send_json FROM sync_state WHERE source='rebrickable'").fetchone()
    assert json.loads(row[0]) == {'owned': [1, 2], 'send_to': 1, 'wishlist': 9}
    assert row[1:] == (None, None, None)
    assert not store.execute("SELECT 1 FROM sync_state WHERE source='brickset'").fetchone()


def test_pull_plan_rows(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    rows = {r['key']: r for r in plan['rows']}
    by_number = {r['number']: r for r in plan['rows'] if r['kind'] == 'owned'}
    assert by_number['1000-1']['state'] == 'add' and by_number['1000-1']['count'] == 2
    assert by_number['2070-1']['state'] == 'differs' and by_number['2070-1']['here'] == 2
    assert by_number[GEAR]['state'] == 'add' and by_number[GEAR]['count'] == 1
    assert {r['number']: r['state'] for r in plan['rows'] if r['kind'] == 'wanted'} == {'1000-3': 'add'}
    assert [u['remote_no'] for u in plan['unmatched']] == ['rb-only-9']
    assert all(k.split(':')[1].isdigit() for k in rows), 'rows are keyed by item id'
    assert TOKEN not in everything(store)
    assert not live_copies(store, '1000-1')


def test_apply_pull_one_event_flag_and_exact_undo(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    digest = table_digest(store)
    before = store.execute('SELECT max(id) FROM event').fetchone()[0]
    result = sync.apply_pull(store, plan['id'])
    receipts = store.execute("SELECT entity_kind, field FROM event WHERE id>? AND entity_kind='sync'", (before,)).fetchall()
    assert [tuple(r) for r in receipts] == [('sync', 'receipt')]
    copies = live_copies(store, '1000-1')
    assert len(copies) == 2 and all(c['condition'] is None and c['completeness'] is None for c in copies)
    assert copies[0]['inventory_source'] == 'rebrickable'                        # design 4.3's preselection, as Add
    names = {r[0] for r in store.execute('SELECT f.name FROM copy_flag c JOIN flag f ON f.id=c.flag_id WHERE c.copy_id=?', (copies[0]['id'],))}
    assert names == {'imported from Rebrickable'}
    gear = store.execute("SELECT s.* FROM stock s JOIN item i ON i.id=s.item_id WHERE i.born_key=?", (GEAR,)).fetchone()
    assert gear['kind'] == 'gear' and gear['quantity'] == 1 and gear['archived_at'] is None
    assert store.execute("SELECT w.quantity FROM wish w JOIN item i ON i.id=w.item_id WHERE i.born_key='1000-3' AND w.archived_at IS NULL").fetchone()[0] == 1
    assert result['counts'] == dict(copies=3, stock=1, wishes_added=1, wishes_changed=0)      # 2 + 1 (1000-2), the gear, one wish
    assert sync.apply_pull(store, plan['id'])['already_applied']
    assert store.execute("SELECT count(*) FROM job WHERE item_id IN (SELECT id FROM item WHERE born_key='1000-1')").fetchone()[0] == 1
    baseline = json.loads(store.execute("SELECT baseline_json FROM sync_state WHERE source='rebrickable'").fetchone()[0])
    assert baseline['remote']['owned'][str(key(store, '1000-1'))] == 2
    assert store.execute("SELECT kind, event_id IS NOT NULL, json_extract(counts_json, '$.copies') FROM plan WHERE id=?", (plan['id'],)).fetchone()[:] == ('sync_pull', 1, 3)
    undone = sync.undo(store, result['event_id'])
    assert not undone['already_undone']
    assert not live_copies(store, '1000-1') and not live_copies(store, '1000-2')
    assert not store.execute("SELECT 1 FROM wish WHERE archived_at IS NULL").fetchone()
    assert not store.execute("SELECT 1 FROM flag WHERE name LIKE 'imported from%'").fetchone()
    assert store.execute("SELECT quantity FROM stock WHERE id=?", (gear['id'],)).fetchone()[0] == 1 and store.execute(
        "SELECT archived_at IS NOT NULL FROM stock WHERE id=?", (gear['id'],)).fetchone()[0] == 1
    assert sync.undo(store, result['event_id'])['already_undone']
    assert store.execute("SELECT baseline_json FROM sync_state WHERE source='rebrickable'").fetchone()[0] is None
    changed = {t: v for t, v in table_digest(store).items() if digest.get(t) != v}
    assert set(changed) <= {'copy', 'copy_part', 'copy_figure', 'stock', 'stock_part', 'wish', 'job', 'job_step', 'item', 'item_property',
                            'item_link', 'color', 'color_link', 'sync_state', 'plan', 'item_provider_status', 'flag'}, changed


def test_undo_guarded_and_ticks(store):
    remote = rebrickable_ready(store)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    with pytest.raises(errors.ValidationFailed):
        sync.apply_pull(store, plan['id'], [f"owned:{key(store, '2070-1')}"])           # nothing to pull: not tickable
    result = sync.apply_pull(store, plan['id'], [f"owned:{key(store, '1000-1')}"])
    assert result['counts']['copies'] == 2 and result['counts']['wishes_added'] == 0
    store.execute("UPDATE copy SET note='later' WHERE item_id=?", (key(store, '1000-1'),))
    store.commit()
    with pytest.raises(errors.UndoBlocked, match='changed since'):
        sync.undo(store, result['event_id'])
    assert len(live_copies(store, '1000-1')) == 2


def test_changed_in_both_places_is_a_conflict(store):
    remote = rebrickable_ready(store)
    sync.apply_pull(store, sync.plan_pull(store, 'rebrickable', http=remote)['id'])
    remote.lists[1]['1000-1'] = 4      # changed there
    store.execute("UPDATE copy SET archived_at='2026-01-01' WHERE id=(SELECT id FROM copy WHERE item_id=? LIMIT 1)", (key(store, '1000-1'),))
    store.commit()                      # changed here
    rows = {r['number']: r for r in sync.plan_pull(store, 'rebrickable', http=remote)['rows'] if r['kind'] == 'owned'}
    conflict = rows['1000-1']
    assert conflict['state'] == 'conflict' and conflict['action'] is None and conflict['remote'] == 4 and conflict['here'] == 1


def test_the_first_sync_has_no_baseline_and_so_no_conflict(store):
    """Design 8: the migration carries the link only; with no baseline `_changed_both` has nothing to compare against."""
    remote = rebrickable_ready(store)
    remote.lists[1]['1000-1'] = 4
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    assert not [r for r in plan['rows'] if r['state'] == 'conflict']
    assert all(r['baseline_remote'] is None and r['baseline_here'] is None for r in plan['rows'])


def test_send_plan_untick_removal_and_results(store):
    remote = rebrickable_ready(store)
    sync.apply_pull(store, sync.plan_pull(store, 'rebrickable', http=remote)['id'], [])             # a baseline, nothing pulled
    plan = sync.plan_send(store, 'rebrickable', http=remote)
    rows = {r['number']: r for r in plan['rows'] if r['kind'] == 'owned'}
    assert rows['2070-1']['send'] == 2 and rows['2070-1']['action'] == 'send'
    assert rows['1000-1']['state'] == 'remove' and rows['1000-1']['action'] is None
    assert 'cannot reverse' in plan['note']
    result = sync.apply_send(store, plan['id'], http=remote)
    # Default ticks only: list 2 keeps its one, list 1 (send_to) gets the second; no removal sent.
    assert {r['key']: r['result'] for r in result['rows']} == {f"owned:{key(store, '2070-1')}": 'sent'}
    assert remote.lists[1]['2070-1'] == 1 and remote.lists[2]['2070-1'] == 1 and remote.lists[1]['1000-1'] == 2
    assert 'not undone' in result['note']
    # Sending to list 2 cannot lower list 1's count: that row fails with a reason, the next one still runs.
    sync.link(store, 'rebrickable', {'send_to': 2})
    store.execute("UPDATE copy SET archived_at='2026-01-01' WHERE id=(SELECT id FROM copy WHERE item_id=? LIMIT 1)", (key(store, '2070-1'),))
    store.commit()
    plan = sync.plan_send(store, 'rebrickable', http=remote)
    ticked = [f"owned:{key(store, '2070-1')}", f"owned:{key(store, '1000-1')}"]
    result = sync.apply_send(store, plan['id'], ticked, http=remote)
    outcome = {r['key']: r['result'] for r in result['rows']}
    assert outcome == {ticked[0]: 'sent', ticked[1]: 'failed'}
    assert sync.status(store, 'rebrickable')['waiting'] == 1
    baseline = json.loads(store.execute("SELECT baseline_json FROM sync_state WHERE source='rebrickable'").fetchone()[0])
    assert baseline['remote']['owned'][str(key(store, '2070-1'))] == 1


def test_send_removal_only_when_ticked_and_budget_pause(store, monkeypatch):
    remote = rebrickable_ready(store)
    sync.link(store, 'rebrickable', {'owned': [1], 'send_to': 1})
    plan = sync.plan_send(store, 'rebrickable', http=remote)
    ticked = [f"owned:{key(store, '1000-1')}", f"owned:{key(store, '1000-2')}"]
    result = sync.apply_send(store, plan['id'], ticked, http=remote)
    assert all(r['result'] == 'sent' for r in result['rows']) and '1000-1' not in remote.lists[1]
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '1')
    with pytest.raises(base.WaitingForBudget):
        sync.plan_send(store, 'rebrickable', http=remote)       # the budget is spent by the fetch itself on the next run


def test_brickset_pull_and_send(store):
    bs = Brickset()
    sync.paste(store, 'brickset', HASH)
    plan = sync.plan_pull(store, 'brickset', http=bs)
    rows = {r['number']: r for r in plan['rows']}
    assert rows['1000-4']['count'] == 3 and rows['1000-2']['state'] == 'add' and rows['1000-2']['kind'] == 'wanted'
    sync.apply_pull(store, plan['id'])
    send = sync.plan_send(store, 'brickset', http=bs)
    rows = {r['number']: r for r in send['rows'] if r['kind'] == 'owned'}
    assert rows['2070-1']['send'] == 2 and rows['2070-1']['action'] == 'send'
    sync.apply_send(store, send['id'], http=bs)
    assert bs.owned['2070-1'] == (1003, 2)
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
    Coll(store).add_copy('1000-4')
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


def test_unidentified_items_are_not_sent_and_are_listed(store):
    """Design 3.8: an item with no number cannot be named to a site; the send plan lists it as not on the site and ticks nothing."""
    remote = rebrickable_ready(store)
    sync.link(store, 'rebrickable', {'owned': [1], 'send_to': 1})
    coll = Coll(store)
    mystery = coll.local('gear', 'Mystery thing')
    coll.add_stock('gear', mystery, quantity=2, condition='new')
    plan = sync.plan_send(store, 'rebrickable', http=remote)
    row = next(r for r in plan['rows'] if r['item_id'] == mystery)
    assert row['state'] == 'unmatched' and row['action'] is None and not row['tickable'] and 'no number yet' in row['reason']
    with pytest.raises(errors.ValidationFailed):
        sync.apply_send(store, plan['id'], [row['key']], http=remote)
    # A BrickLink-born local set is sent by its BrickLink number, and a Rebrickable-born one by its own.
    local = coll.local('set', 'Only on BrickLink', born_key='9999-1')
    store.execute("INSERT INTO copy(id, item_id, inventory_source, created_at, updated_at) VALUES('local-copy', ?, 'none', '2026-10-26T12:00:00.000Z', '2026-10-26T12:00:00.000Z')", (local,))
    store.commit()
    row = next(r for r in sync.plan_send(store, 'rebrickable', http=remote)['rows'] if r['item_id'] == local)
    assert row['remote_no'] == '9999-1' and row['action'] == 'send'


def test_numbers_are_translated_by_born_key_then_by_a_confirmed_bricklink_link(store):
    coll = Coll(store)
    local = coll.local('set', 'Local set', born_key='lego-77')
    coll.link(local, '77-1', kind='S')
    numbers = ['1000-1', GEAR, '77-1', 'nothing-1', 'fig-000004', '3001']
    found = sync.translate(store, numbers)
    assert found['1000-1'] == coll.item('sets', '1000-1') and found[GEAR] == coll.item('sets', GEAR)
    assert found['77-1'] == local
    assert found['nothing-1'] is None and found['fig-000004'] is None and found['3001'] is None      # a part or figure is not a set
    assert sync.reverse(store, [local, coll.item('sets', '1000-1')]) == {local: '77-1', coll.item('sets', '1000-1'): '1000-1'}


def test_a_number_two_items_share_prefers_the_rebrickable_one_and_a_merged_item_follows_its_survivor(store):
    from brickwork.store4 import merge
    coll = Coll(store)
    survivor = coll.item('sets', '1000-1')
    twin = coll.local('set', 'Local twin', born_key='1000-1')
    assert sync.translate(store, ['1000-1'])['1000-1'] == survivor                      # the number is Rebrickable's: its item wins a local twin
    other = coll.local('set', 'Other local', born_key='5555-1')
    again = coll.local('gear', 'Another local', born_key='5555-1')      # another BrickLink type, the same number
    assert sync.translate(store, ['5555-1'])['5555-1'] is None                          # two local items, no born one: not guessed
    store.execute('BEGIN IMMEDIATE')
    merge.merge_in(store, twin, survivor, via='cli')
    store.commit()
    assert sync.translate(store, ['1000-1'])['1000-1'] == survivor and other != again


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
    assert cli.main(['sync', 'rebrickable', 'pull', '--apply', plan['id'], '--tick', f"owned:{key(store, '1000-1')}", '--json']) == 0
    assert json.loads(capsys.readouterr().out)['counts']['copies'] == 2
    assert store.execute("SELECT via FROM event WHERE entity_kind='sync' AND field='receipt'").fetchone()[0] == 'cli'
    assert cli.main(['sync', 'rebrickable', 'connect', '--json']) == 1
    assert '--username' in capsys.readouterr().err


def test_a_second_submit_after_a_lost_file_write_applies_nothing(store):
    """#64: the plan file not yet marked (a second tab, or a crash before the file write); the `plan` table decides."""
    plan = sync.plan_pull(store, 'rebrickable', http=rebrickable_ready(store))
    first = sync.apply_pull(store, plan['id'])
    stale = sync.load_plan(store, plan['id'], 'pull')
    stale.pop('applied')
    sync._store_plan(store, stale)
    copies = store.execute('SELECT count(*) FROM copy').fetchone()[0]
    again = sync.apply_pull(store, plan['id'])
    assert again['already_applied'] and again['event_id'] == first['event_id']
    assert store.execute('SELECT count(*) FROM copy').fetchone()[0] == copies


def test_a_rolled_back_apply_can_be_applied_again(store):
    """#64: inside an outer write that fails, the marker rolls back with the rows."""
    from brickwork.core.transaction import transaction
    plan = sync.plan_pull(store, 'rebrickable', http=rebrickable_ready(store))
    with pytest.raises(RuntimeError):
        with transaction(store):
            sync.apply_pull(store, plan['id'])
            raise RuntimeError('outer write failed')
    assert not live_copies(store, '1000-1')
    assert not store.execute('SELECT 1 FROM plan').fetchone()
    result = sync.apply_pull(store, plan['id'])
    assert not result['already_applied'] and result['counts']['copies'] == 3


def test_undo_keeps_a_tag_the_pile_already_had(store):
    """P2 (review): a pull that merges onto an existing pile must not remove a flag link it did not make."""
    coll = Coll(store)
    gear = coll.item('sets', GEAR)
    pile = coll.add_stock('gear', gear, quantity=1, condition=None)
    flag = coll.flag('imported from Rebrickable', 'tag')
    coll.tag('stock', pile, flag)
    remote = rebrickable_ready(store)
    remote.lists[2][GEAR] = 2
    result = sync.apply_pull(store, sync.plan_pull(store, 'rebrickable', http=remote)['id'])
    assert store.execute('SELECT quantity FROM stock WHERE id=?', (pile,)).fetchone()[0] == 2
    sync.undo(store, result['event_id'])
    assert store.execute('SELECT quantity FROM stock WHERE id=?', (pile,)).fetchone()[0] == 1
    assert store.execute('SELECT 1 FROM stock_flag WHERE stock_id=? AND flag_id=?', (pile, flag)).fetchone()
