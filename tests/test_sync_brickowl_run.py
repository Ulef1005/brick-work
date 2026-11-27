"""#522 slice 1: Brick Owl as a source of the sync core, its runs and the API: owned and wanted sets on the adapter. Invented data against a small
stateful fake of Brick Owl; no network."""
from contextlib import closing
import json
from urllib.parse import parse_qs, urlparse

import pytest

from brickwork.core import errors, sync
from brickwork.core.connect import connect
from brickwork.core.sources import base
from brickwork.core.sync import adapters
from brickwork.core.sync import run as sync_run
from tests.api2 import app4, call, coll, v2, validate, wire, world, write  # noqa: F401
from tests.app4 import Coll, make_pair
from tests.sources4 import keyed, unkeyed
from tests.test_bw_sync import EXTRA

LINK = {'wishlist_id': '8101'}


class BrickOwl:
    """Collection lots and one wishlist (8101). `owned` and `wanted` are lists of [lot id, set number, quantity]. `fail` maps a path to the
    replies to give instead, one per call."""

    def __init__(self):
        self.lots = {'owned': [['1', '1000-1', 2]], 'wanted': [['201', '1000-3', 1]]}
        self.calls, self.fail, self.next_id = [], {}, 500
        self.boids = {n: '9' + n.replace('-', '') for n in ('1000-1', '1000-2', '1000-3', '1000-4', '2070-1')}

    def _number(self, boid):
        return next(n for n, b in self.boids.items() if b == boid)

    def __call__(self, request):
        url = urlparse(request.full_url)
        path = url.path.removeprefix('/v1/')
        form = {k: v[0] for k, v in parse_qs(request.data.decode() if request.data else url.query).items()}
        self.calls.append((path, form))
        if self.fail.get(path):
            reply = self.fail[path].pop(0)
            if reply is not None:
                if isinstance(reply, BaseException):
                    raise reply
                return reply
        if path == 'user/details':
            return {'username': 'synthetic'}
        if path == 'wishlist/lists':
            return [{'wishlist_id': '8101', 'name': 'Winter shelf', 'lot_count': str(len(self.lots['wanted']))}]
        if path in ('collection/lots', 'wishlist/lots'):
            kind = 'owned' if path == 'collection/lots' else 'wanted'
            return [dict(lot_id=i, boid=self.boids[n], type='Set', qty=str(q), con='used', full_con=None, price=None, note=None,
                         ids=[{'id': n.removesuffix('-1') if n.endswith('-1') else n, 'type': 'set_number'}]) for i, n, q in self.lots[kind]]
        if path == 'catalog/id_lookup':
            return {'boids': [self.boids[form['id']]] if form['id'] in self.boids else []}
        kind = 'owned' if path.startswith('collection/') else 'wanted'
        action = path.split('/')[1]
        if action == 'create_lot':
            self.next_id += 1
            self.lots[kind].append([str(self.next_id), self._number(form['boid']), 1])
            return {'status': 'Success', 'lot_id': str(self.next_id)}
        lot = next((r for r in self.lots[kind] if r[0] == form['lot_id']), None)
        if lot is None:
            return {'error': {'status': 'Unknown lot'}}
        if action == 'delete_lot':
            self.lots[kind].remove(lot)
        else:
            lot[2] = int(form.get('quantity') or form.get('minimum_quantity'))
        return {'status': 'Success'}

    def held(self, kind, number):
        return sum(q for _, n, q in self.lots[kind] if n == number)

    def paths(self):
        return [p for p, _ in self.calls]


@pytest.fixture
def pair(tmp_path):  # noqa: F811
    return make_pair(tmp_path, rich=True, extra_dump=EXTRA)


@pytest.fixture
def remote(pair, monkeypatch):
    unkeyed(monkeypatch)
    keyed(monkeypatch, 'brickowl')
    monkeypatch.setattr(base, 'transport', lambda r: (_ for _ in ()).throw(AssertionError('network')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    fake = BrickOwl()
    monkeypatch.setattr(adapters, 'transport', fake)
    return fake


@pytest.fixture
def db(pair, remote):
    with closing(connect(pair)) as connection:
        yield connection


def count(db, table, number):
    column = 'count(*)' if table == 'copy' else 'coalesce(sum(x.quantity), 0)'
    return db.execute(f'SELECT {column} FROM main.{table} x JOIN main.item i ON i.id=x.item_id WHERE i.born_key=? AND x.archived_at IS NULL', (number,)).fetchone()[0]


def have(db, number, copies):
    coll = Coll(db)
    for _ in range(copies):
        coll.add_copy(number)


def rows_by(plan):
    return {(r['kind'], r['remote_no']): r for r in plan['rows']}


def test_a_pull_outside_a_run_applies_reads_brick_owls_own_directions_and_undoes(db, remote):
    # the Rebrickable switches are Off: a pull that read them would write no Last synced from
    db.execute("INSERT INTO main.setting(key, value) VALUES('rebrickable_sync_directions', ?)", (json.dumps({'owned': 'off', 'wishlist': 'off'}),))
    db.commit()
    sync.link(db, 'brickowl', LINK)
    plan = sync.plan_pull(db, 'brickowl')
    result = sync.apply_pull(db, plan['id'])
    assert result['counts'] == dict(copies=2, stock=0, wishes_added=1, wishes_changed=0)
    assert count(db, 'copy', '1000-1') == 2 and count(db, 'wish', '1000-3') == 1
    assert db.execute("SELECT count(*) FROM main.flag WHERE name='imported from Brick Owl'").fetchone()[0] == 1
    assert {r[0] for r in db.execute("SELECT DISTINCT site FROM main.synced_from")} == {'brickowl'}
    sync.undo(db, result['event_id'])
    assert count(db, 'copy', '1000-1') == 0 and count(db, 'wish', '1000-3') == 0


def test_the_status_and_the_account_routes_of_a_key_only_site(db, remote):
    status = sync.status(db, 'brickowl')
    assert status['label'] == 'Brick Owl' and status['account'] is None
    assert status['credentials']['user'] is None and status['credentials']['key']
    for call in (lambda: sync.connect(db, 'brickowl', 'a', 'b'), lambda: sync.paste(db, 'brickowl', 'x' * 12),
                 lambda: sync.remove(db, 'brickowl'), lambda: sync.test(db, 'brickowl')):
        with pytest.raises(errors.NotFound, match='API key alone'):
            call()
    assert remote.calls == []
    assert sync.lists(db, 'brickowl') == [dict(id='8101', name='Winter shelf', lots=1)]


def test_the_link_takes_a_wishlist_id_and_nothing_of_rebrickable(db, remote):
    assert sync.link(db, 'brickowl', LINK)['link'] == LINK
    assert sync.link(db, 'brickowl', {'wishlist_id': None})['link'] == {'wishlist_id': None}
    for bad in ({'wishlist_id': 8101}, {'wishlist_id': 'a b'}, {'wishlist_id': ''}, {'owned': [1]}):
        with pytest.raises(errors.ValidationFailed):
            sync.link(db, 'brickowl', bad)


def test_without_a_wishlist_wishes_are_not_offered_to_send(db, remote):
    Coll(db).add_wish(Coll(db).item('sets', '1000-2'))
    plan = sync.plan_send(db, 'brickowl')
    row = rows_by(plan)[('wanted', '1000-2')]
    assert not row['tickable'] and row['reason'] == 'Link a Brick Owl wishlist to send wishes to'
    assert 'wishlist/lots' not in remote.paths()


def test_a_send_creates_a_lot_and_a_lower_count_that_deletes_a_lot_is_not_ticked(db, remote):
    remote.lots['owned'] = [['1', '1000-1', 1], ['2', '1000-1', 1], ['3', '1000-4', 3]]
    have(db, '2070-1', 2)
    have(db, '1000-1', 1)
    have(db, '1000-4', 2)
    sync.link(db, 'brickowl', LINK)
    plan = sync.plan_send(db, 'brickowl')
    rows = rows_by(plan)
    assert rows[('owned', '2070-1')]['action'] == 'send'
    assert rows[('owned', '1000-4')]['action'] == 'send'                  # 3 to 2 in one lot: a quantity change
    assert rows[('owned', '1000-1')]['action'] is None and rows[('owned', '1000-1')]['tickable']      # 2 to 1 in two lots: a lot goes
    result = sync.apply_send(db, plan['id'])
    assert {r['result'] for r in result['rows']} == {'sent'}
    assert remote.held('owned', '2070-1') == 2 and remote.held('owned', '1000-4') == 2 and remote.held('owned', '1000-1') == 2


def test_a_set_brick_owl_does_not_know_is_unmatched_in_the_plan(db, remote):
    del remote.boids['2070-1']
    remote.lots = {'owned': [], 'wanted': []}
    have(db, '2070-1', 1)
    row = rows_by(sync.plan_send(db, 'brickowl'))[('owned', '2070-1')]
    assert row['state'] == 'unmatched' and not row['tickable'] and row['reason'] == 'Brick Owl does not know this set number'


@pytest.mark.parametrize('failure', [{'error': {'status': 'Rate limit exceeded'}}, OSError('cut off')])
def test_a_retry_after_a_create_whose_quantity_call_failed_makes_no_second_lot(db, remote, failure):
    remote.lots = {'owned': [], 'wanted': []}
    have(db, '2070-1', 3)
    plan = sync.plan_send(db, 'brickowl')
    remote.fail['collection/update'] = [failure]
    first = sync.apply_send(db, plan['id'])
    assert first['rows'][0]['result'] in ('paused', 'failed')
    assert len(remote.lots['owned']) == 1
    db.execute("DELETE FROM main.source_budget") if first['rows'][0]['result'] == 'paused' else None
    db.commit()
    second = sync.apply_send(db, plan['id'])
    assert second['rows'][0]['result'] == 'sent'
    assert len(remote.lots['owned']) == 1 and remote.held('owned', '2070-1') == 3


def test_a_create_that_arrived_but_answered_nothing_is_read_again_before_the_retry(db, remote):
    remote.lots = {'owned': [], 'wanted': []}
    have(db, '2070-1', 1)
    plan = sync.plan_send(db, 'brickowl')
    remote.fail['collection/create_lot'] = [OSError('the reply was lost')]
    assert sync.apply_send(db, plan['id'])['rows'][0]['result'] == 'failed'
    remote.lots['owned'] = [['501', '2070-1', 1]]                       # it had arrived
    assert sync.apply_send(db, plan['id'])['rows'][0]['result'] in ('sent', 'unchanged')
    assert remote.held('owned', '2070-1') == 1 and remote.paths().count('collection/create_lot') == 1


def test_a_send_cut_off_by_a_restart_reads_the_lots_again(db, remote):
    remote.lots = {'owned': [], 'wanted': []}
    have(db, '2070-1', 1)
    plan = sync.plan_send(db, 'brickowl')

    class Died(BaseException):
        pass
    remote.fail['collection/create_lot'] = [Died()]                     # the process dies inside the call: nothing after it runs
    with pytest.raises(Died):
        sync.apply_send(db, plan['id'])
    remote.lots['owned'] = [['501', '2070-1', 1]]
    sync.apply_send(db, plan['id'])
    assert remote.held('owned', '2070-1') == 1


def test_a_run_has_its_own_directions_pulls_sends_and_undoes(db, remote):
    have(db, '2070-1', 1)
    form = dict(owned_dir='both', wishlist_dir='into', wish_list='default', wishlist_id='8101')
    assert sync_run.save_choices(db, form, 'brickowl') == dict(owned='both', wishlist='into', parts='off', lost='off')
    assert sync.status(db, 'brickowl')['link'] == dict(wishlist_id='8101', wish_list='default')
    assert sync_run.directions(db)['owned'] == 'both' and sync_run.directions(db, 'brickset')['wishlist'] == 'both'
    assert [r['what'] for r in sync_run.what_syncs(db, 'brickowl')] == ['Owned sets', 'Wanted sets']
    run = sync_run.start(db, source='brickowl')
    assert run['source'] == 'brickowl' and run['parts'] is None and run['lost_out'] is None
    run, plans = sync_run.load(db, run['id'])
    shown = {(r['kind'], r['number']): r for r in sync_run.rows(db, run, plans)}
    assert shown[('owned', '1000-1')]['default'] == 'pull' and shown[('owned', '2070-1')]['default'] == 'send'
    form = {'choice:' + r['key']: r['default'] for r in shown.values() if r['default']}
    done = sync_run.apply(db, run['id'], form)
    assert done['stages']['pull']['status'] == 'done' and done['stages']['send']['status'] == 'done'
    assert count(db, 'copy', '1000-1') == 2 and remote.held('owned', '2070-1') == 1
    sync_run.undo_run(db, done['stages']['pull']['event'])
    assert count(db, 'copy', '1000-1') == 0


def test_a_lower_count_that_deletes_a_lot_is_offered_unticked_in_a_run(db, remote):
    remote.lots = {'owned': [['1', '1000-1', 1], ['2', '1000-1', 1]], 'wanted': []}
    have(db, '1000-1', 1)
    sync_run.save_choices(db, dict(owned_dir='to', wishlist_dir='off', wish_list='default'), 'brickowl')
    run, plans = sync_run.load(db, sync_run.start(db, source='brickowl')['id'])
    row = sync_run.rows(db, run, plans)[0]
    assert [o['id'] for o in row['options']] == ['send'] and row['default'] is None
    assert row['options'][0]['note'] == 'Deletes a lot there'


def test_the_api_serves_brick_owl_with_a_string_wishlist_and_its_user_routes_do_not(v2, pair, remote):
    status = call(v2, '/sync/brickowl')
    assert status.status_code == 200, status.json
    validate(status, 'get_sync_by_source')
    linked = write(v2, '/sync/brickowl/link', 'put', LINK)
    assert linked.status_code == 200, linked.json
    validate(linked, 'put_sync_by_source_link')
    lists = call(v2, '/sync/brickowl/lists')
    validate(lists, 'get_sync_by_source_lists')
    assert [entry['id'] for entry in lists.json['data']] == ['8101']
    plan = write(v2, '/sync/brickowl/pull/plan')
    assert plan.status_code == 201, plan.json
    validate(plan, 'post_sync_by_source_pull_plan', '201')
    applied = write(v2, '/sync/brickowl/pull/apply', body={'plan_id': plan.json['data']['id']})
    assert applied.status_code == 200, applied.json
    validate(applied, 'post_sync_by_source_pull_apply')
    send = write(v2, '/sync/brickowl/send/plan')
    assert send.status_code == 201, send.json
    validate(send, 'post_sync_by_source_send_plan', '201')
    sent = write(v2, '/sync/brickowl/send/apply', body={'plan_id': send.json['data']['id']})
    assert sent.status_code == 200, sent.json
    validate(sent, 'post_sync_by_source_send_apply')
    refused = write(v2, '/sources/brickowl/user', 'put', {'value': 'x' * 12})
    assert refused.status_code == 404, refused.json


def test_lots_read_again_after_a_failure_are_kept_for_the_rows_that_follow(db, remote):
    remote.lots = {'owned': [], 'wanted': []}
    for number in ('1000-1', '1000-2', '2070-1'):
        have(db, number, 1)
    plan = sync.plan_send(db, 'brickowl')
    keys = [r['key'] for r in plan['rows']]
    remote.fail['collection/create_lot'] = [OSError('cut off')]
    assert sync.apply_send(db, plan['id'], keys[:1])['rows'][0]['result'] == 'failed'
    before = remote.paths().count('collection/lots')
    for key in keys:                      # as a job sends: one call, and one client, per row
        sync.apply_send(db, plan['id'], [key])
    assert remote.paths().count('collection/lots') == before + 1
    assert all(remote.held('owned', n) == 1 for n in ('1000-1', '1000-2', '2070-1'))


def test_a_conflict_whose_send_deletes_a_lot_says_so(db, remote):
    remote.lots = {'owned': [['1', '1000-1', 1], ['2', '1000-1', 1]], 'wanted': []}
    have(db, '1000-1', 2)
    sync.apply_pull(db, sync.plan_pull(db, 'brickowl')['id'])                # the baseline: 2 and 2
    remote.lots['owned'].append(['3', '1000-1', 1])                          # 3 there
    db.execute('UPDATE main.copy SET archived_at=updated_at WHERE id=(SELECT id FROM main.copy c WHERE archived_at IS NULL AND item_id=? LIMIT 1)',
               (Coll(db).item('sets', '1000-1'),))                            # 1 here
    db.commit()
    row = rows_by(sync.plan_send(db, 'brickowl'))[('owned', '1000-1')]
    assert row['state'] == 'conflict' and row['deletes_lot'] is True and row['action'] is None
    sync_run.save_choices(db, dict(owned_dir='both', wishlist_dir='off', wish_list='default'), 'brickowl')
    run, plans = sync_run.load(db, sync_run.start(db, source='brickowl')['id'])
    options = {o['id']: o for o in sync_run.rows(db, run, plans)[0]['options']}
    assert options['send']['note'] == 'Brick Owl becomes 1 · deletes a lot there'


def test_what_syncs_says_when_no_brick_owl_wishlist_is_linked(db, remote):
    linked = lambda: {r['what']: r['linked'] for r in sync_run.what_syncs(db, 'brickowl')}['Wanted sets']
    assert linked() == 'No Brick Owl wishlist linked'
    sync.link(db, 'brickowl', LINK)
    assert linked() == 'Quantity wanted ↔ wishlist Wishlist'


@pytest.mark.parametrize('lots', [[['1', '1000-1', 1], ['2', '1000-1', 1]], []])
def test_a_local_twin_is_never_sent_under_a_number_that_belongs_to_another_item(db, remote, lots):
    remote.lots = {'owned': [list(lot) for lot in lots], 'wanted': []}
    coll = Coll(db)
    twin = coll.local('gear', 'Syn local twin', born_key='1000-1')      # the number is the catalogue set's
    coll.add_stock('gear', twin)
    have(db, '1000-1', 3)
    plan = sync.plan_send(db, 'brickowl')
    row = next(r for r in plan['rows'] if r['item_id'] == twin)
    assert not row['tickable'] and row['action'] is None and 'deletes_lot' not in row
    assert row['reason'] == 'Another item here has this number at Brick Owl'
    sync.apply_send(db, plan['id'])
    assert remote.held('owned', '1000-1') == 3
    sync_run.save_choices(db, dict(owned_dir='to', wishlist_dir='off', wish_list='default'), 'brickowl')
    run, plans = sync_run.load(db, sync_run.start(db, source='brickowl')['id'])
    assert all(not shown['options'] for shown in sync_run.rows(db, run, plans) if shown['item_id'] == twin)
