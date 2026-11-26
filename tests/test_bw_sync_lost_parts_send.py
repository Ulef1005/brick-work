"""Sending Lost Parts to Rebrickable (#469 part B): pure planner and remote apply.

Invented data against the `store` fixture and a fake client; no network."""

import json
import pytest

from brickwork.core.sync import adapters, lost_parts_send
from brickwork.store4 import fetched, rebrickable_api
from tests.app4 import Coll
from tests.test_bw_sync import pair, store  # noqa: F401
from tests.test_bw_sync_lost_parts import copy_of


def remote_row(set_no, part_no, color_id, quantity, *, is_spare=False, ids=(101,), inv_part_id=501):
    return dict(set_no=set_no, part_no=str(part_no), color_id=int(color_id), is_spare=bool(is_spare),
                quantity=int(quantity), ids=list(ids), inv_part_id=inv_part_id)


def remote_read(rows=(), *, unreadable=0, inv_parts=None):
    return dict(rows=list(rows), unreadable=unreadable, inv_parts=dict(inv_parts or {}))


def translate(db, numbers):
    out = {}
    for number in numbers:
        row = db.execute("SELECT id FROM main.item WHERE kind='set' AND born_key=?", (number,)).fetchone()
        out[number] = row[0] if row else None
    return out


class FakeClient:
    """Small in-memory client recording `lost_part_add` and `lost_part_remove` calls without network."""

    def __init__(self, *, budget_after=None, budget_error=None, reject=False, next_id=1000, add_reply=None):
        self.calls = []
        self.budget_after = budget_after
        self.budget_error = budget_error
        self.reject = reject
        self.next_id = next_id
        self.add_reply = add_reply

    def _step(self, call):
        if self.reject:
            raise adapters.KeyRejected('Key rejected')
        if self.budget_after is not None and len(self.calls) >= self.budget_after:
            raise self.budget_error or adapters.RemoteBudgetExceeded()
        self.calls.append(call)

    def lost_part_add(self, inv_part_id, quantity):
        self._step(('add', inv_part_id, quantity))
        if self.add_reply is not None:
            return self.add_reply(inv_part_id, quantity) if callable(self.add_reply) else self.add_reply
        lost_id = self.next_id
        self.next_id += 1
        return {'lost_part_id': lost_id, 'lost_quantity': quantity}

    def lost_part_remove(self, lost_part_id):
        self._step(('remove', lost_part_id))
        return True


def test_add_change_and_remove_unticked(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 3), ('3023', '4', 1, True)])
    remote = remote_read(
        [remote_row('1000-1', '3001', 4, 1, ids=[11, 12], inv_part_id=701),
         remote_row('1000-1', '3023', 15, 2, ids=[13], inv_part_id=702)],
        inv_parts={('1000-1', '3023', 4, True): 703},
    )
    planned = lost_parts_send.plan(store, remote, translate, rule='per_set', on=True)
    by_key = {(r['part_no'], r['color_id'], r['is_spare']): r for r in planned['rows']}
    assert set(by_key) == {('3001', 4, False), ('3023', 4, True), ('3023', 15, False)}

    added = by_key[('3023', 4, True)]
    assert added['state'] == 'add' and added['before'] == 0 and added['after'] == 1
    assert added['tickable'] and added['ticked'] is True and added['inv_part_id'] == 703

    changed = by_key[('3001', 4, False)]
    assert changed['state'] == 'change' and changed['before'] == 1 and changed['after'] == 3
    assert changed['tickable'] and changed['ticked'] is False and changed['ids'] == [11, 12]

    removed = by_key[('3023', 15, False)]
    assert removed['state'] == 'remove' and removed['before'] == 2 and removed['after'] == 0
    assert removed['tickable'] and removed['ticked'] is False and removed['ids'] == [13]


def test_equal_rows_are_omitted_and_rules_mirror_pull(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 1)])
    copy_of(store, '1000-2')
    remote = remote_read([
        remote_row('1000-1', '3001', 4, 2, ids=[21], inv_part_id=801),
        remote_row('1000-2', '3001', 4, 1, ids=[22], inv_part_id=802),
    ])
    add_only = lost_parts_send.plan(store, remote, translate, rule='add_only', on=True)
    assert add_only['rows'] == []

    per_part = lost_parts_send.plan(store, remote, translate, rule='per_part', on=True)
    assert [(r['set_no'], r['state'], r['before'], r['after']) for r in per_part['rows']] == [('1000-1', 'change', 2, 1)]

    everything = lost_parts_send.plan(store, remote, translate, rule='everything', on=True)
    assert [(r['set_no'], r['state']) for r in everything['rows']] == [('1000-1', 'change'), ('1000-2', 'remove')]


def test_several_copies_sum_and_list_each_copy(store):
    first = copy_of(store, '1000-1', marks=[('3001', '4', 1)])
    second = copy_of(store, '1000-1', marks=[('3001', '4', 2)])
    planned = lost_parts_send.plan(
        store,
        remote_read(inv_parts={('1000-1', '3001', 4, False): 901}),
        translate,
        rule='per_part',
        on=True,
    )
    (row,) = planned['rows']
    assert row['state'] == 'add' and row['after'] == 3
    assert {c['id']: c['missing'] for c in row['copies']} == {first: 1, second: 2}
    assert len(row['copies']) == 2
    assert all('missing' in c['label'] for c in row['copies'])


def test_bricklink_translated_part_matches_rebrickable_number(store):
    copy_id = copy_of(store, '1000-1')
    coll = Coll(store)
    local_part = coll.local('part', 'BrickLink brick', born_key='3001bl')
    store.execute(
        'INSERT INTO main.item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,decided_at) '
        "VALUES(?,NULL,'rebrickable','part','3001','matched','external_ids','shipped',0,'2026-10-26T12:00:00Z')",
        (local_part,),
    )
    store.execute(
        'UPDATE copy_part SET item_id=?, missing=2, checked=1 WHERE copy_id=? AND item_id=? AND is_spare=0 AND color_id=?',
        (local_part, copy_id, coll.item('parts', '3001'), coll.colour('4')),
    )
    store.commit()

    planned = lost_parts_send.plan(
        store,
        remote_read(inv_parts={('1000-1', '3001', 4, False): 910}),
        translate,
        rule='per_part',
        on=True,
    )
    (row,) = planned['rows']
    assert (row['set_no'], row['part_no'], row['color_id'], row['after']) == ('1000-1', '3001', 4, 2)


def test_untranslatable_line_is_listed_and_never_sent(store):
    copy_id = copy_of(store, '1000-1')
    coll = Coll(store)
    unlinked = coll.local('part', 'Unlinked local part', born_key='unlinked-1')
    store.execute(
        'UPDATE copy_part SET item_id=?, missing=2, checked=1 WHERE copy_id=? AND item_id=? AND is_spare=0 AND color_id=?',
        (unlinked, copy_id, coll.item('parts', '3001'), coll.colour('4')),
    )
    store.commit()

    planned = lost_parts_send.plan(store, remote_read(), translate, rule='everything', on=True)
    assert planned['rows'] == []
    (unmatched,) = planned['unmatched']
    assert unmatched['set_no'] == '1000-1' and unmatched['missing'] == 2 and 'No Rebrickable number' in unmatched['reason']
    assert set(unmatched) == {
        'set_no', 'reason', 'parts', 'pieces', 'copy_id', 'copy_label', 'item_id', 'color_id', 'is_spare', 'missing',
    }
    assert unmatched['parts'] == 1 and unmatched['pieces'] == 2 and unmatched['copy_id'] == copy_id
    assert unmatched['item_id'] == unlinked and unmatched['is_spare'] is False
    assert planned['summary']['unmatched'] == 1
    client = FakeClient()
    report = lost_parts_send.apply(store, client, planned, None, via='test', actor='tester')
    assert client.calls == [] and report['sent'] == []


def test_unreadable_or_failed_read_plans_no_removals(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 1)])
    remote = remote_read(
        [remote_row('1000-1', '3023', 15, 2, ids=[31], inv_part_id=601)],
        unreadable=1,
        inv_parts={('1000-1', '3001', 4, False): 602},
    )
    planned = lost_parts_send.plan(store, remote, translate, rule='everything', on=True)
    assert planned['status'] == 'unavailable' and not planned['clearing'] and 'could not be read' in planned['message']
    assert planned['rows'] == [] and planned['unreadable'] == 1

    failed = lost_parts_send.plan(store, ' paused ', translate, rule='everything', on=True)
    assert failed['status'] == 'unavailable' and not failed['clearing'] and 'were not read' in failed['message']
    assert failed['rows'] == []


def test_switch_off_returns_off_and_setting_default_is_off(store):
    assert lost_parts_send.enabled(store) is False
    store.execute("INSERT INTO setting(key, value) VALUES(?, '1')", (lost_parts_send.KEY,))
    store.commit()
    assert lost_parts_send.enabled(store) is True

    copy_of(store, '1000-1', marks=[('3001', '4', 2)])
    planned = lost_parts_send.plan(store, remote_read(), translate, rule='everything', on=False)
    assert planned['status'] == 'off' and planned['clearing'] is False and planned['rows'] == []


def test_apply_sends_only_ticked_and_fails_missing_inv_part_id(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 3), ('3023', '4', 1, True)])
    remote = remote_read([
        remote_row('1000-1', '3001', 4, 1, ids=[41, 42], inv_part_id=501),
        remote_row('1000-1', '3023', 15, 2, ids=[43], inv_part_id=502),
    ])
    planned = lost_parts_send.plan(store, remote, translate, rule='per_set', on=True)
    events_before = store.execute('SELECT count(*) FROM event').fetchone()[0]

    client = FakeClient()
    # Default ticked (None) sends only ticked add rows; change and remove are unticked and spare add lacks inv_part_id.
    report = lost_parts_send.apply(store, client, planned, None, via='test', actor='tester')
    assert client.calls == [] and report['sent'] == []
    assert report['failed'] == []  # spare add without inv_part_id is not tickable
    assert 'Undo cannot reverse' in report['note']
    assert store.execute('SELECT count(*) FROM event').fetchone()[0] == events_before

    # Explicitly ticking the change row removes the old entry, then adds the new count.
    change_key = next(r['key'] for r in planned['rows'] if r['state'] == 'change')
    client_change = FakeClient()
    report_change = lost_parts_send.apply(store, client_change, planned, [change_key], via='test', actor='tester')
    assert client_change.calls == [('remove', 41), ('remove', 42), ('add', 501, 3)]
    assert [r['part_no'] for r in report_change['sent']] == ['3001']
    assert report_change['failed'] == []

    # Explicitly ticking the remove row sends its removal only.
    remove_key = next(r['key'] for r in planned['rows'] if r['state'] == 'remove')
    client2 = FakeClient()
    report2 = lost_parts_send.apply(store, client2, planned, [remove_key], via='test', actor='tester')
    assert client2.calls == [('remove', 43)] and len(report2['sent']) == 1 and not report2['failed']


def test_budget_stop_reports_remaining_and_key_rejected_propagates(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 2), ('3023', '15', 1), ('3023', '4', 1, True)])
    remote = remote_read(inv_parts={
        ('1000-1', '3001', 4, False): 301,
        ('1000-1', '3023', 15, False): 302,
        ('1000-1', '3023', 4, True): 303,
    })
    planned = lost_parts_send.plan(store, remote, translate, rule='per_part', on=True)
    ticked = [r['key'] for r in planned['rows']]
    assert len(ticked) == 3

    client = FakeClient(budget_after=1)
    report = lost_parts_send.apply(store, client, planned, ticked, via='test', actor='tester')
    assert len(client.calls) == 1
    assert len(report['sent']) == 1 and len(report['remaining']) == 2 and report['failed'] == []

    waiting = FakeClient(budget_after=1, budget_error=adapters.WaitingForBudget(None, '2026-11-23T14:00:00Z'))
    waiting_report = lost_parts_send.apply(store, waiting, planned, ticked, via='test', actor='tester')
    assert len(waiting.calls) == 1
    assert len(waiting_report['sent']) == 1 and len(waiting_report['remaining']) == 2 and waiting_report['failed'] == []

    rejecting = FakeClient(reject=True)
    with pytest.raises(adapters.KeyRejected):
        lost_parts_send.apply(store, rejecting, planned, ticked, via='test', actor='tester')


def test_unavailable_plan_sends_nothing_on_apply(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 2)])
    for bad_remote in ('throttled', remote_read(unreadable=2, inv_parts={('1000-1', '3001', 4, False): 602})):
        planned = lost_parts_send.plan(store, bad_remote, translate, rule='everything', on=True)
        assert planned['status'] == 'unavailable' and planned['rows'] == [] and planned['message']
        client = FakeClient()
        report = lost_parts_send.apply(store, client, planned, None, via='test', actor='tester')
        assert client.calls == [] and report['sent'] == [] and report['failed'] == []


def test_incomplete_ids_rows_are_untickable_and_never_sent(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 3)])
    remote = remote_read([
        dict(remote_row('1000-1', '3001', 4, 1, ids=[11], inv_part_id=701), ids_complete=False),
        dict(remote_row('1000-1', '3023', 15, 2, ids=[13], inv_part_id=702), ids_complete=False),
    ])
    planned = lost_parts_send.plan(store, remote, translate, rule='per_set', on=True)
    assert {r['state'] for r in planned['rows']} == {'change', 'remove'}
    assert all(not r['tickable'] and not r['ticked'] and r['reason'] for r in planned['rows'])
    client = FakeClient()
    report = lost_parts_send.apply(store, client, planned, [r['key'] for r in planned['rows']], via='test', actor='tester')
    assert client.calls == [] and report['sent'] == [] and len(report['failed']) == 2


def test_change_row_keeps_removed_progress_on_budget_and_error_retries(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 3)])
    remote = remote_read([remote_row('1000-1', '3001', 4, 1, ids=[41, 42], inv_part_id=501)])
    planned = lost_parts_send.plan(store, remote, translate, rule='per_part', on=True)

    class StatefulClient:
        def __init__(self, ids, *, fail_remove=None):
            self.present = set(ids)
            self.fail_remove = fail_remove
            self.calls = []

        def lost_part_remove(self, lost_id):
            if self.fail_remove is not None:
                raise self.fail_remove
            if lost_id not in self.present:
                raise adapters.SourceError('404 Not Found')
            self.present.remove(lost_id)
            self.calls.append(('remove', lost_id))

        def lost_part_add(self, inv_part_id, quantity):
            self.calls.append(('add', inv_part_id, quantity))
            return {'lost_part_id': 999, 'lost_quantity': quantity}

    change_keys = [r['key'] for r in planned['rows']]
    budget_client = StatefulClient([41, 42], fail_remove=adapters.RemoteBudgetExceeded())
    first = lost_parts_send.apply(store, budget_client, planned, change_keys, via='test', actor='tester')
    assert first['sent'] == [] and first['failed'] == [] and len(first['remaining']) == 1
    assert first['remaining'][0]['added'] is False and first['remaining'][0]['removed'] is False
    budget_client.fail_remove = None
    retry = lost_parts_send.apply(store, budget_client, dict(rows=first['remaining']), None, via='test', actor='tester')
    assert len(retry['sent']) == 1 and retry['failed'] == [] and retry['remaining'] == []
    assert budget_client.calls == [('remove', 41), ('remove', 42), ('add', 501, 3)]

    err_client = StatefulClient([41, 42], fail_remove=adapters.SourceError('Rebrickable refused the Lost Part removal'))
    failed = lost_parts_send.apply(store, err_client, planned, change_keys, via='test', actor='tester')
    assert failed['sent'] == [] and len(failed['failed']) == 1 and failed['failed'][0]['added'] is False
    err_client.fail_remove = None
    retry_err = lost_parts_send.apply(store, err_client, dict(rows=failed['failed']), None, via='test', actor='tester')
    assert len(retry_err['sent']) == 1 and retry_err['failed'] == []
    assert err_client.calls == [('remove', 41), ('remove', 42), ('add', 501, 3)]


def test_add_without_inv_part_id_is_untickable_with_reason(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 2)])
    planned = lost_parts_send.plan(store, remote_read(), translate, rule='per_part', on=True)
    (row,) = planned['rows']
    assert row['state'] == 'add' and row['tickable'] is False and row['ticked'] is False
    assert row['reason'] == 'Rebrickable inventory part id unknown'
    client = FakeClient()
    report = lost_parts_send.apply(store, client, planned, None, via='test', actor='tester')
    assert client.calls == [] and report['sent'] == [] and report['failed'] == []


def test_marks_of_two_copies_add_up_and_a_matching_remote_plans_nothing(store):
    """A copy's `missing` is capped at the line quantity by the schema (CHECK missing<=quantity), so the sum of several copies is the only
    way to exceed one line; a remote that holds that sum plans no change, while a planned sum above the set line quantity is untickable."""
    first = copy_of(store, '1000-1', marks=[('3001', '4', 3)])
    second = copy_of(store, '1000-1', marks=[('3001', '4', 2)])
    same = lost_parts_send.plan(
        store,
        remote_read([remote_row('1000-1', '3001', 4, 5, ids=[81], inv_part_id=801)]),
        translate,
        rule='per_part',
        on=True,
    )
    assert same['rows'] == []
    planned = lost_parts_send.plan(
        store,
        remote_read(inv_parts={('1000-1', '3001', 4, False): 801}),
        translate,
        rule='per_part',
        on=True,
    )
    (row,) = planned['rows']
    assert row['after'] == 5 and {c['id']: c['missing'] for c in row['copies']} == {first: 3, second: 2}
    assert row['tickable'] is True and row['ticked'] is True and not row.get('reason')
    client = FakeClient()
    assert [r['after'] for r in lost_parts_send.apply(store, client, planned, None, via='test', actor='tester')['sent']] == [5]
    assert client.calls == [('add', 801, 5)]


def test_set_parts_cache_reads_a_list_of_pages_and_the_newest_fetch(store):
    page = {'results': [{'part': {'part_num': '3001'}, 'color': {'id': 4}, 'is_spare': False, 'inv_part_id': 555}]}
    store.execute("INSERT INTO main.source_record(source, kind, key, payload, digest, bytes, fetched_at, status) "
                  "VALUES('rebrickable', 'set_parts', '9999-1', ?, 'd1', 1, '2026-01-01T00:00:00.000Z', 'ok')", (json.dumps([page, {'results': []}]),))
    store.execute("INSERT INTO main.source_record(source, kind, key, payload, digest, bytes, fetched_at, status) "
                  "VALUES('rebrickable', 'set_parts', '9999-1', ?, 'd2', 1, '2025-01-01T00:00:00.000Z', 'ok')", (json.dumps({'results': []}),))
    store.commit()
    assert lost_parts_send._set_parts_map(store, '9999-1') == {('3001', 4, False): 555}


def test_no_removal_planned_when_live_copy_has_no_part_list(store):
    none_copy = copy_of(store, '1000-2')
    empty_copy = copy_of(store, '1000-1')
    store.execute("UPDATE copy SET inventory_source='none', inventory_version=NULL WHERE id=?", (none_copy,))
    store.execute("UPDATE copy_part SET retired_at='2026-01-01' WHERE copy_id=?", (empty_copy,))
    store.commit()
    remote = remote_read([
        remote_row('1000-2', '3001', 4, 1, ids=[91], inv_part_id=901),
        remote_row('1000-1', '3001', 4, 1, ids=[92], inv_part_id=902),
    ])
    for rule in ('everything', 'per_set'):
        planned = lost_parts_send.plan(store, remote, translate, rule=rule, on=True)
        assert planned['rows'] == []
        assert {(u['set_no'], u['reason']) for u in planned['unmatched']} == {
            ('1000-1', 'The set has no part list yet'),
            ('1000-2', 'The set has no part list yet'),
        }
        for u in planned['unmatched']:
            assert set(u) == {
                'set_no', 'reason', 'parts', 'pieces', 'copy_id', 'copy_label', 'item_id', 'color_id', 'is_spare', 'missing',
            }
            assert u['parts'] == 1 and u['pieces'] == 1
            assert u['copy_id'] is None and u['copy_label'] is None and u['item_id'] is None and u['missing'] is None


def test_change_removes_then_adds_and_add_only_never_sends_a_change(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 3)])
    remote_up = remote_read([remote_row('1000-1', '3001', 4, 1, ids=[61], inv_part_id=501)])
    add_only_plan = lost_parts_send.plan(store, remote_up, translate, rule='add_only', on=True)
    (row,) = add_only_plan['rows']
    assert row['state'] == 'change' and row['tickable'] is False and row['ticked'] is False
    assert row['reason'] == lost_parts_send.ADD_ONLY_CHANGE
    client = FakeClient()
    report = lost_parts_send.apply(store, client, add_only_plan, [row['key']], via='test', actor='tester')
    assert client.calls == [] and report['sent'] == [] and report['failed'][0]['reason'] == lost_parts_send.ADD_ONLY_CHANGE

    remote_down = remote_read([remote_row('1000-1', '3001', 4, 5, ids=[61, 62], inv_part_id=501)])
    down_plan = lost_parts_send.plan(store, remote_down, translate, rule='per_part', on=True)
    client_down = FakeClient()
    report_down = lost_parts_send.apply(store, client_down, down_plan, [r['key'] for r in down_plan['rows']], via='test', actor='tester')
    assert client_down.calls == [('remove', 61), ('remove', 62), ('add', 501, 3)]
    assert len(report_down['sent']) == 1 and report_down['sent'][0]['added'] is True


def test_downward_change_blocked_like_remove_with_unmatched_reason(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 1)])
    no_list = copy_of(store, '1000-1')
    store.execute("UPDATE copy SET inventory_source='none', inventory_version=NULL WHERE id=?", (no_list,))
    store.commit()

    copy_unlinked = copy_of(store, '1000-2', marks=[('3001', '4', 1)])
    coll = Coll(store)
    unlinked = coll.local('part', 'Unlinked local part', born_key='unlinked-downward')
    store.execute(
        'UPDATE copy_part SET item_id=?, missing=1, checked=1 WHERE copy_id=? AND item_id=? AND is_spare=0 AND color_id=?',
        (unlinked, copy_unlinked, coll.item('parts', '3023'), coll.colour('15')),
    )
    store.commit()

    remote = remote_read([
        remote_row('1000-1', '3001', 4, 3, ids=[71], inv_part_id=701),
        remote_row('1000-2', '3001', 4, 2, ids=[72], inv_part_id=702),
    ])
    planned = lost_parts_send.plan(store, remote, translate, rule='per_part', on=True)
    assert planned['rows'] == []
    by_set = {u['set_no']: u['reason'] for u in planned['unmatched']}
    assert by_set['1000-1'] == 'The set has no part list yet'
    assert 'No Rebrickable number' in by_set['1000-2']


def test_send_rule_setting_is_separate_from_pull_and_defaults_to_add_only(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 1)])
    remote = remote_read([remote_row('1000-1', '3001', 4, 3, ids=[81], inv_part_id=801)])
    assert lost_parts_send.send_rule(store) == 'add_only'

    store.execute("INSERT OR REPLACE INTO setting(key, value) VALUES('rebrickable_lost_parts_rule', 'everything')")
    store.commit()
    assert lost_parts_send.send_rule(store) == 'add_only'
    default_plan = lost_parts_send.plan(store, remote, translate, rule=None, on=True)
    assert default_plan['rule'] == 'add_only' and default_plan['rows'] == []

    store.execute("INSERT OR REPLACE INTO setting(key, value) VALUES(?, 'per_part')", (lost_parts_send.RULE_KEY,))
    store.commit()
    assert lost_parts_send.send_rule(store) == 'per_part'
    send_plan = lost_parts_send.plan(store, remote, translate, rule=None, on=True)
    assert send_plan['rule'] == 'per_part' and len(send_plan['rows']) == 1

    store.execute("INSERT OR REPLACE INTO setting(key, value) VALUES(?, 'unknown')", (lost_parts_send.RULE_KEY,))
    store.commit()
    assert lost_parts_send.send_rule(store) == 'add_only'
    with pytest.raises(ValueError):
        lost_parts_send.plan(store, remote, translate, rule='unknown', on=True)


def test_budget_stop_keeps_ticked_on_remaining_and_fails_unsendable_rows(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 2), ('3023', '4', 1, True)])
    remote = remote_read(
        [remote_row('1000-1', '3023', 15, 2, ids=[91], inv_part_id=902)],
        inv_parts={('1000-1', '3001', 4, False): 901},
    )
    planned = lost_parts_send.plan(store, remote, translate, rule='per_set', on=True)
    all_keys = [r['key'] for r in planned['rows']]
    assert len(all_keys) == 3

    stopped = lost_parts_send.apply(store, FakeClient(budget_after=0), planned, all_keys, via='test', actor='tester')
    assert stopped['sent'] == []
    assert [r['part_no'] for r in stopped['failed']] == ['3023'] and stopped['failed'][0]['is_spare'] is True
    assert len(stopped['remaining']) == 2
    assert all(r['ticked'] is True for r in stopped['remaining'])

    retry_client = FakeClient()
    retried = lost_parts_send.apply(store, retry_client, dict(rows=stopped['remaining']), None, via='test', actor='tester')
    assert len(retried['sent']) == 2 and retried['failed'] == [] and retried['remaining'] == []
    assert retry_client.calls == [('add', 901, 2), ('remove', 91)]


def test_key_rejected_attaches_partial_report_with_progress(store):
    rows = [
        dict(key='r1', state='add', inv_part_id=501, after=2, ids=[], tickable=True, ticked=True),
        dict(key='r2', state='change', inv_part_id=502, before=1, after=3, ids=[41, 42], ids_complete=True, tickable=True, ticked=True),
        dict(key='r3', state='remove', ids=[43], ids_complete=True, tickable=True, ticked=False),
    ]

    class RejectOnSecondRemove:
        def __init__(self):
            self.calls = []

        def lost_part_add(self, inv_part_id, quantity):
            self.calls.append(('add', inv_part_id, quantity))
            return {'lost_part_id': 999, 'lost_quantity': quantity}

        def lost_part_remove(self, lost_id):
            if lost_id == 42:
                raise adapters.KeyRejected('Refused')
            self.calls.append(('remove', lost_id))

    client = RejectOnSecondRemove()
    with pytest.raises(adapters.KeyRejected) as exc:
        lost_parts_send.apply(store, client, dict(rule='per_part', rows=rows), ['r1', 'r2', 'r3'], via='test', actor='tester')
    partial = exc.value.partial
    assert [r['key'] for r in partial['sent']] == ['r1']
    assert partial['failed'] == []
    assert [r['key'] for r in partial['remaining']] == ['r2', 'r3']
    assert partial['remaining'][0]['added'] is False and partial['remaining'][0]['removed_ids'] == [41]
    assert all(r['ticked'] is True for r in partial['remaining'])


def test_apply_validates_ticked_and_row_ids_and_quantities(store):
    client = FakeClient()
    for bad_ticked in (123, [['unhashable']], '1000-1:3001:4:0'):
        with pytest.raises(ValueError):
            lost_parts_send.apply(store, client, dict(rows=[]), bad_ticked, via='test', actor='tester')

    bad_rows = [
        dict(key='k1', state='add', inv_part_id=0, after=2, ids=[], tickable=True, ticked=True),
        dict(key='k2', state='add', inv_part_id=True, after=2, ids=[], tickable=True, ticked=True),
        dict(key='k3', state='add', inv_part_id=501, after=0, ids=[], tickable=True, ticked=True),
        dict(key='k4', state='change', inv_part_id=501, before=1, after=-2, ids=[11], ids_complete=True, tickable=True, ticked=True),
        dict(key='k5', state='remove', ids=[11, 0], ids_complete=True, tickable=True, ticked=True),
        dict(key='k6', state='remove', ids=['11'], ids_complete=True, tickable=True, ticked=True),
    ]
    report = lost_parts_send.apply(store, client, dict(rule='per_part', rows=bad_rows), None, via='test', actor='tester')
    assert client.calls == [] and report['sent'] == [] and report['remaining'] == []
    assert len(report['failed']) == len(bad_rows)
    assert all(r.get('reason') for r in report['failed'])


def test_default_ticked_sends_only_add_rows(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 3), ('3023', '4', 1, True)])
    remote = remote_read(
        [remote_row('1000-1', '3001', 4, 1, ids=[41], inv_part_id=501),
         remote_row('1000-1', '3023', 15, 2, ids=[42], inv_part_id=502)],
        inv_parts={('1000-1', '3023', 4, True): 503},
    )
    planned = lost_parts_send.plan(store, remote, translate, rule='per_set', on=True)
    assert {r['state']: r['ticked'] for r in planned['rows']} == {'add': True, 'change': False, 'remove': False}
    client = FakeClient()
    report = lost_parts_send.apply(store, client, planned, None, via='test', actor='tester')
    assert client.calls == [('add', 503, 1)]
    assert [r['state'] for r in report['sent']] == ['add'] and report['failed'] == []


class ListedClient:
    """Like Rebrickable (checked live, #469): an add for a part that is listed is refused. `refuse` says which adds fail otherwise."""

    def __init__(self, refuse=lambda quantity: None):
        self.calls, self.refuse, self.listed, self.next_id = [], refuse, {501: (41, 1)}, 900

    def lost_part_remove(self, lost_id):
        self.calls.append(('remove', lost_id))
        self.listed = {part: row for part, row in self.listed.items() if row[0] != lost_id}
        return True

    def lost_part_add(self, inv_part_id, quantity):
        self.calls.append(('add', inv_part_id, quantity))
        failure = self.refuse(quantity)
        if failure is not None:
            raise failure
        if inv_part_id in self.listed:
            raise adapters.SourceError('Rebrickable refused the Lost Part')
        self.next_id += 1
        self.listed[inv_part_id] = (self.next_id, quantity)
        return {'lost_part_id': self.next_id, 'lost_quantity': quantity}


def change_plan(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 3)])
    planned = lost_parts_send.plan(store, remote_read([remote_row('1000-1', '3001', 4, 1, ids=[41], inv_part_id=501)]), translate, rule='per_part', on=True)
    return planned, [r['key'] for r in planned['rows']]


def test_a_change_whose_new_count_fails_puts_the_old_one_back_and_a_retry_starts_over(store):
    planned, keys = change_plan(store)
    client = ListedClient(refuse=lambda quantity: adapters.SourceError('boom') if quantity == 3 else None)
    report = lost_parts_send.apply(store, client, planned, keys, via='test', actor='tester')
    assert client.calls == [('remove', 41), ('add', 501, 3), ('add', 501, 1)] and client.listed == {501: (901, 1)}
    (row,) = report['failed']
    assert row['reason'] == 'Rebrickable did not take the new count. The old count, 1, was put back.'
    assert row['ids'] == [901] and row['removed'] is False and row['added'] is False

    client.refuse = lambda quantity: None
    retry = lost_parts_send.apply(store, client, dict(rows=report['failed']), None, via='test', actor='tester')
    assert client.calls[3:] == [('remove', 901), ('add', 501, 3)] and client.listed == {501: (902, 3)}
    assert len(retry['sent']) == 1 and retry['failed'] == []


def test_a_change_that_loses_the_entry_names_the_part_and_the_old_count(store):
    planned, keys = change_plan(store)
    client = ListedClient(refuse=lambda quantity: adapters.SourceError('down'))
    report = lost_parts_send.apply(store, client, planned, keys, via='test', actor='tester')
    (row,) = report['failed']
    assert row['reason'] == "Part 3001 of set 1000-1 may be gone from Rebrickable's Lost Parts: it had 1. Brick Work could not put it back. Check it there."
    assert row['removed'] is True and row['added'] is False and client.listed == {} and row['gone'] == row['reason']

    client.refuse = lambda quantity: None
    retry = lost_parts_send.apply(store, client, dict(rows=report['failed']), None, via='test', actor='tester')
    assert client.calls[-1] == ('add', 501, 3) and client.calls.count(('remove', 41)) == 1 and len(retry['sent']) == 1


@pytest.mark.parametrize('pause_on', [3, 1])       # the budget runs out on the new count, or on putting the old one back
def test_a_budget_pause_after_the_removal_waits_and_then_adds_the_new_count(store, pause_on):
    planned, keys = change_plan(store)
    outcomes = {3: adapters.SourceError('boom'), pause_on: adapters.RemoteBudgetExceeded()}
    client = ListedClient(refuse=outcomes.get)
    report = lost_parts_send.apply(store, client, planned, keys, via='test', actor='tester')
    (row,) = report['remaining']
    assert report['failed'] == [] and row['removed'] is True and row['added'] is False and 'it had 1' in row['gone']
    client.refuse = lambda quantity: None
    retry = lost_parts_send.apply(store, client, dict(rows=report['remaining']), None, via='test', actor='tester')
    assert client.listed == {501: (901, 3)} and len(retry['sent']) == 1 and client.calls.count(('remove', 41)) == 1


@pytest.mark.parametrize('failure', [adapters.SourceError('down'), adapters.KeyRejected('Refused')])
def test_a_removal_that_stops_halfway_names_the_old_count(store, failure):
    class Halfway:
        def lost_part_remove(self, lost_id):
            if lost_id == 42:
                raise failure
            return True

    row = dict(key='r', set_no='1000-1', part_no='3001', state='change', rule='per_part', inv_part_id=501, before=3, after=5, ids=[41, 42], ids_complete=True, tickable=True)
    try:
        report = lost_parts_send.apply(store, Halfway(), dict(rule='per_part', rows=[row]), ['r'])
        assert 'it had 3' in report['failed'][0]['reason']
    except adapters.KeyRejected as exc:
        assert 'it had 3' in exc.partial['remaining'][0]['gone']


@pytest.mark.parametrize('stop', [adapters.RemoteBudgetExceeded(), adapters.KeyRejected('Refused')])
def test_a_retry_after_a_failed_put_back_that_stops_again_still_says_it_could_not(store, stop):
    planned, keys = change_plan(store)
    client = ListedClient(refuse=lambda quantity: adapters.SourceError('down'))
    first = lost_parts_send.apply(store, client, planned, keys, via='test', actor='tester')
    client.refuse = lambda quantity: stop
    try:
        (row,) = lost_parts_send.apply(store, client, dict(rows=first['failed']), None, via='test', actor='tester')['remaining']
    except adapters.KeyRejected as exc:
        (row,) = exc.partial['remaining']
    assert 'could not put it back' in row['gone']


def test_a_key_refused_after_the_removal_keeps_what_is_gone(store):
    planned, keys = change_plan(store)
    client = ListedClient(refuse=lambda quantity: adapters.KeyRejected('Refused'))
    with pytest.raises(adapters.KeyRejected) as exc:
        lost_parts_send.apply(store, client, planned, keys, via='test', actor='tester')
    (row,) = exc.value.partial['remaining']
    assert 'it had 1' in row['gone'] and row['removed'] is True


def test_apply_catches_unexpected_client_exception_and_retry_never_reposts(store):
    rows = [
        dict(key='r1', state='change', rule='per_part', inv_part_id=501, before=1, after=3,
             ids=[41, 42], ids_complete=True, tickable=True, ticked=False),
        dict(key='r2', state='add', rule='per_part', inv_part_id=502, before=0, after=1,
             ids=[], ids_complete=True, tickable=True, ticked=True),
    ]

    class FlakyClient:
        def __init__(self):
            self.calls = []
            self.boom = True

        def lost_part_add(self, inv_part_id, quantity):
            self.calls.append(('add', inv_part_id, quantity))
            return {'lost_part_id': 999, 'lost_quantity': quantity}

        def lost_part_remove(self, lost_id):
            if self.boom and lost_id == 42:
                raise RuntimeError('network drop')
            self.calls.append(('remove', lost_id))
            return True

    client = FlakyClient()
    report = lost_parts_send.apply(store, client, dict(rule='per_part', rows=rows), ['r1', 'r2'], via='test', actor='tester')
    assert [r['key'] for r in report['sent']] == ['r2']
    assert len(report['failed']) == 1
    failed_row = report['failed'][0]
    assert failed_row['key'] == 'r1' and failed_row['added'] is False and failed_row['removed_ids'] == [41]
    assert failed_row['reason'].startswith('network drop ') and 'it had 1' in failed_row['reason']      # one of the two old rows is gone

    client.boom = False
    retry = lost_parts_send.apply(store, client, dict(rule='per_part', rows=report['failed']), None, via='test', actor='tester')
    assert [r['key'] for r in retry['sent']] == ['r1'] and retry['failed'] == []
    assert client.calls == [('remove', 41), ('add', 502, 1), ('remove', 42), ('add', 501, 3)]


def test_lookup_inv_part_id_uses_newest_record_caches_payload_and_skips_remove(store, monkeypatch):
    old_pages = [{'count': 1, 'next': None, 'previous': None, 'results': [
        {'id': 9001, 'inv_part_id': 111, 'part': {'part_num': '3001'}, 'color': {'id': 4}, 'is_spare': False},
    ]}]
    new_pages = [
        {'count': 3, 'next': 'https://rebrickable.com/api/v3/lego/sets/1000-1/parts/?page=2', 'previous': None, 'results': [
            {'id': 9002, 'inv_part_id': 222, 'part': {'part_num': '3001'}, 'color': {'id': 4}, 'is_spare': False},
        ]},
        {'count': 3, 'next': None, 'previous': None, 'results': [
            {'id': 9003, 'inv_part_id': 333, 'part': {'part_num': '3023'}, 'color': {'id': 4}, 'is_spare': True},
            {'id': 9004, 'part': {'part_num': '3023'}, 'color': {'id': 15}, 'is_spare': False},
        ]},
    ]
    fetched.store_source_record(store, source='rebrickable', kind='set_parts', key='1000-1', payload=rebrickable_api._joined(old_pages))
    fetched.store_source_record(store, source='rebrickable', kind='set_parts', key='1000-1', payload=rebrickable_api._joined(new_pages))
    store.commit()

    parses = []
    real_loads = lost_parts_send.json.loads
    monkeypatch.setattr(lost_parts_send.json, 'loads', lambda text: (parses.append(text), real_loads(text))[1])
    cache = {}
    assert lost_parts_send._lookup_inv_part_id(store, '1000-1', '3001', 4, False, {}, cache) == 222
    assert lost_parts_send._lookup_inv_part_id(store, '1000-1', '3023', 4, True, {}, cache) == 333
    assert lost_parts_send._lookup_inv_part_id(store, '1000-1', '3023', 15, False, {}, cache) is None
    assert len(parses) == 1

    copy_of(store, '1000-1', marks=[('3001', '4', 2), ('3023', '4', 1, True)])
    copy_of(store, '1000-2')
    remote = remote_read([remote_row('1000-2', '3001', 4, 1, ids=[88], inv_part_id=None)])
    seen_sets = []
    real_set_parts_map = lost_parts_send._set_parts_map
    monkeypatch.setattr(
        lost_parts_send,
        '_set_parts_map',
        lambda db, set_no: (seen_sets.append(set_no), real_set_parts_map(db, set_no))[1],
    )
    planned = lost_parts_send.plan(store, remote, translate, rule='everything', on=True)
    assert seen_sets == ['1000-1']
    by_part = {(r['set_no'], r['part_no'], r['is_spare']): r for r in planned['rows']}
    assert by_part[('1000-1', '3001', False)]['inv_part_id'] == 222
    assert by_part[('1000-1', '3023', True)]['inv_part_id'] == 333
    assert by_part[('1000-2', '3001', False)]['state'] == 'remove'


def test_colour_handling_sorts_mixed_and_negative_and_unmatches_non_integer(store, monkeypatch):
    assert sorted(['abc', '10', '-1', '4'], key=lost_parts_send._colour_sort_key) == ['-1', '4', '10', 'abc']
    copy_of(store, '1000-1', marks=[('3001', '4', 2)])

    monkeypatch.setattr(lost_parts_send.wishlists, '_rebrickable_colours', lambda db, ids: {cid: {'blue'} for cid in ids})
    bad_colour = lost_parts_send.plan(store, remote_read(), translate, rule='per_part', on=True)
    assert bad_colour['rows'] == [] and len(bad_colour['unmatched']) == 1
    assert 'not an integer' in bad_colour['unmatched'][0]['reason']

    monkeypatch.setattr(lost_parts_send.wishlists, '_rebrickable_colours', lambda db, ids: {cid: {'-1', 'blue'} for cid in ids})
    mixed = lost_parts_send.plan(store, remote_read(), translate, rule='per_part', on=True)
    assert mixed['rows'] == [] and len(mixed['unmatched']) == 1
    assert 'Several Rebrickable numbers' in mixed['unmatched'][0]['reason']
