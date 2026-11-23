"""Sending Lost Parts to Rebrickable (#469 part B): pure planner and remote apply.

Invented data against the `store` fixture and a fake client; no network."""
import pytest

from brickwork.core.sync import adapters, lost_parts_send
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

    def __init__(self, *, budget_after=None, budget_error=None, reject=False):
        self.calls = []
        self.budget_after = budget_after
        self.budget_error = budget_error
        self.reject = reject

    def _step(self, call):
        if self.reject:
            raise adapters.KeyRejected('Key rejected')
        if self.budget_after is not None and len(self.calls) >= self.budget_after:
            raise self.budget_error or adapters.RemoteBudgetExceeded()
        self.calls.append(call)

    def lost_part_add(self, inv_part_id, quantity):
        self._step(('add', inv_part_id, quantity))

    def lost_part_remove(self, lost_part_id):
        self._step(('remove', lost_part_id))


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
    assert changed['tickable'] and changed['ticked'] is True and changed['ids'] == [11, 12]

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
    assert planned['status'] == 'off' and planned['rows'] == []


def test_apply_sends_only_ticked_and_fails_missing_inv_part_id(store):
    copy_of(store, '1000-1', marks=[('3001', '4', 3), ('3023', '4', 1, True)])
    remote = remote_read([
        remote_row('1000-1', '3001', 4, 1, ids=[41, 42], inv_part_id=501),
        remote_row('1000-1', '3023', 15, 2, ids=[43], inv_part_id=502),
    ])
    planned = lost_parts_send.plan(store, remote, translate, rule='per_set', on=True)
    events_before = store.execute('SELECT count(*) FROM event').fetchone()[0]

    client = FakeClient()
    # Default ticked (None) sends the ticked add/change rows and leaves the unticked remove row alone.
    report = lost_parts_send.apply(store, client, planned, None, via='test', actor='tester')
    assert client.calls == [('remove', 41), ('remove', 42), ('add', 501, 3)]
    assert [r['part_no'] for r in report['sent']] == ['3001']
    assert report['failed'] == []  # spare add without inv_part_id is not tickable
    assert 'Undo cannot reverse' in report['note']
    assert store.execute('SELECT count(*) FROM event').fetchone()[0] == events_before

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
        def __init__(self, ids, *, fail_add=None):
            self.present = set(ids)
            self.fail_add = fail_add
            self.calls = []

        def lost_part_remove(self, lost_id):
            if lost_id not in self.present:
                raise adapters.SourceError('404 Not Found')
            self.present.remove(lost_id)
            self.calls.append(('remove', lost_id))

        def lost_part_add(self, inv_part_id, quantity):
            if self.fail_add is not None:
                raise self.fail_add
            self.calls.append(('add', inv_part_id, quantity))

    budget_client = StatefulClient([41, 42], fail_add=adapters.RemoteBudgetExceeded())
    first = lost_parts_send.apply(store, budget_client, planned, None, via='test', actor='tester')
    assert first['sent'] == [] and first['failed'] == [] and len(first['remaining']) == 1
    assert first['remaining'][0]['removed'] is True
    budget_client.fail_add = None
    retry = lost_parts_send.apply(store, budget_client, dict(rows=first['remaining']), None, via='test', actor='tester')
    assert len(retry['sent']) == 1 and retry['failed'] == [] and retry['remaining'] == []
    assert budget_client.calls == [('remove', 41), ('remove', 42), ('add', 501, 3)]

    err_client = StatefulClient([41, 42], fail_add=adapters.SourceError('Rebrickable refused the Lost Part'))
    failed = lost_parts_send.apply(store, err_client, planned, None, via='test', actor='tester')
    assert failed['sent'] == [] and len(failed['failed']) == 1 and failed['failed'][0]['removed'] is True
    err_client.fail_add = None
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
    way to exceed one line; a remote that holds that sum plans no change."""
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
