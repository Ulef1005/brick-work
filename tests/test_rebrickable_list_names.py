"""#531: each synced set keeps the names of the Rebrickable set lists it is in, as the detail of its source (#551, ADR 0039). A set in two lists
carries both; a list renamed or removed at Rebrickable shows one preview line with the number of sets it touches, and Rename it / Drop the name
change every set that carries it, picked or not; nothing else on a copy changes; Undo restores the names. Invented data against the fake
Rebrickable of test_bw_sync."""
import json

import pytest

from brickwork.core import errors, stock, sync
from brickwork.core.transaction import transaction
from brickwork.store4 import merge, origins
from tests.test_bw_sync import GEAR, Rebrickable, key, live_copies, rebrickable_ready, store  # noqa: F401
from tests.test_bw_sync import pair  # noqa: F401


class Named(Rebrickable):
    """The fake Rebrickable with list names that can change, and lists that can go."""

    def __init__(self, names=None):
        super().__init__()
        self.names = dict(names or {1: 'Main collection', 2: 'Bought 2026', 9: 'Wanted'})

    def __call__(self, request):
        if request.full_url.rstrip('/').endswith('/setlists') or '/setlists/?' in request.full_url:
            return {'count': len(self.lists), 'next': None, 'results': [
                {'id': i, 'name': self.names[i], 'num_sets': len(v)} for i, v in self.lists.items()]}
        return super().__call__(request)


def names_of(db, number):
    return sorted(r[0] for r in db.execute('''SELECT f.list_name FROM synced_from f JOIN copy c ON c.id=f.copy_id JOIN item i ON i.id=c.item_id
                                               WHERE i.born_key=? AND c.archived_at IS NULL''', (number,)))


def pulled(db, remote, **kwargs):
    plan = sync.plan_pull(db, 'rebrickable', http=remote)
    return plan, sync.apply_pull(db, plan['id'], **kwargs)


def test_each_set_keeps_the_names_of_the_lists_it_is_in(store):
    remote = rebrickable_ready(store, Named())
    remote.lists[2]['1000-1'] = 1                                         # 1000-1 sits in two lists
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    row = next(r for r in plan['rows'] if r['number'] == '1000-1')
    assert row['lists'] == ['Main collection', 'Bought 2026'] and plan['lists']['keep'] is True and plan['lists']['preview'] == []
    sync.apply_pull(store, plan['id'])
    copies = live_copies(store, '1000-1')
    assert len(copies) == 3 and names_of(store, '1000-1') == sorted(['Main collection', 'Bought 2026'] * 3)
    assert set(names_of(store, '2070-1')) == {'Bought 2026'}                # by hand, and matched to its list
    wish = store.execute("SELECT f.list_key, f.list_name FROM synced_from f WHERE f.wish_id IS NOT NULL").fetchall()
    assert [tuple(w) for w in wish] == [('9', 'Wanted')]


def test_with_the_switch_off_no_name_is_kept(store):
    remote = rebrickable_ready(store, Named())
    plan = sync.plan_pull(store, 'rebrickable', http=remote, keep_list_names=False)
    assert plan['lists']['keep'] is False and not sync.keep_list_names_on(store, 'rebrickable')
    sync.apply_pull(store, plan['id'])
    assert {tuple(r) for r in store.execute('SELECT list_key, list_name FROM synced_from')} == {('', None)}


def test_a_rename_at_rebrickable_is_one_line_and_renames_every_set_picked_or_not(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    before = {r['id']: dict(r) for r in store.execute('SELECT * FROM copy')}
    remote.names[1] = 'Home collection'
    remote.lists[1]['1000-4'] = 1                                         # something new to pick, which the person leaves out
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    lines = {l['key']: l for l in plan['lists']['preview']}
    assert lines['1'] == dict(key='1', old_name='Main collection', name='Home collection', state='renamed', sets=2, action='rename',
                              choices=['rename', 'keep'])
    assert lines['2']['state'] == 'unchanged' and lines['2']['action'] == 'skip'
    result = sync.apply_pull(store, plan['id'], [])                         # nothing ticked: only the names follow
    assert set(names_of(store, '1000-1')) == {'Home collection'} and not live_copies(store, '1000-4')
    after = {r['id']: dict(r) for r in store.execute('SELECT * FROM copy')}
    assert after == before                                                 # copies, counts and fields stay
    sync.undo(store, result['event_id'])
    assert set(names_of(store, '1000-1')) == {'Main collection'}


def test_keep_the_old_name_over_a_rename(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    remote.names[1] = 'Home collection'
    pulled(store, remote, lists={'1': 'keep'})
    assert set(names_of(store, '1000-1')) == {'Main collection'}


def test_a_removed_list_drops_its_name_and_the_sets_stay_and_undo_puts_it_back(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    sync.link(store, 'rebrickable', {'owned': [1]})
    del remote.lists[2], remote.names[2]
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    line = next(l for l in plan['lists']['preview'] if l['key'] == '2')
    assert (line['state'], line['action'], line['sets'], line['name']) == ('removed', 'drop', 2, None)   # 2070-1 and the gear item
    result = sync.apply_pull(store, plan['id'], [])
    assert names_of(store, '2070-1') == [] and len(live_copies(store, '2070-1')) == 2
    sync.undo(store, result['event_id'])
    assert set(names_of(store, '2070-1')) == {'Bought 2026'}


def test_a_choice_is_checked_against_its_line(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    remote.names[1] = 'Home collection'
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    for bad in ({'1': 'drop'}, {'77': 'skip'}, ['1']):
        with pytest.raises(errors.ValidationFailed):
            sync.apply_pull(store, plan['id'], lists=bad)
    with pytest.raises(errors.ValidationFailed):
        sync.link(store, 'rebrickable', {'keep_list_names': 'yes'})


def test_the_api_takes_the_list_choices(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    remote.names[1] = 'Home collection'
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    from brickwork.api2 import sync as api
    import inspect
    assert 'list_choices' in inspect.getsource(api.post_sync_by_source_pull_apply)
    receipt_id = sync.apply_pull(store, plan['id'], [], lists={'1': 'rename'})['event_id']
    receipt = json.loads(store.execute('SELECT new_value FROM event WHERE id=?', (receipt_id,)).fetchone()[0])
    assert len(receipt['lists']['renamed']) == 3 and receipt['lists']['dropped'] == []


def test_undo_of_a_dropped_list_skips_a_row_removed_by_a_kind_move(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    sync.link(store, 'rebrickable', {'owned': [1]})
    del remote.lists[2], remote.names[2]
    _, dropped = pulled(store, remote, ticked=[])
    gear = key(store, GEAR)
    with transaction(store):
        store.execute("UPDATE main.job SET state='done'")   # the pulls queue catalogue jobs; a kind move waits for them
        merge.move_kind_in(store, gear, 'set', via='app')
    sync.undo(store, dropped['event_id'])
    assert set(names_of(store, '2070-1')) == {'Bought 2026'}


def test_an_unlinked_list_is_not_treated_as_removed(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    sync.link(store, 'rebrickable', {'owned': [1]})
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    line = next(l for l in plan['lists']['preview'] if l['key'] == '2')
    assert (line['state'], line['action']) == ('unlinked', 'keep')
    sync.apply_pull(store, plan['id'])
    assert set(names_of(store, '2070-1')) == {'Bought 2026'}


def test_switching_off_keep_list_names_leaves_recorded_names_unchanged(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    before = [tuple(r) for r in store.execute(
        "SELECT copy_id, stock_id, wish_id, list_key, list_name FROM synced_from WHERE list_key!='' ORDER BY id")]
    remote.names[1] = 'Home collection'
    sync.link(store, 'rebrickable', {'owned': [1]})
    del remote.lists[2], remote.names[2]
    plan = sync.plan_pull(store, 'rebrickable', http=remote, keep_list_names=False)
    assert plan['lists']['keep'] is False and plan['lists']['preview'] == []
    assert plan['rows'] and all(r['lists'] == [] for r in plan['rows'])
    assert plan['link'].get('keep_list_names') is False
    sync.apply_pull(store, plan['id'])
    after = [tuple(r) for r in store.execute(
        "SELECT copy_id, stock_id, wish_id, list_key, list_name FROM synced_from WHERE list_key!='' ORDER BY id")]
    assert after == before


def test_zero_quantity_stock_and_remote_entries_get_no_synced_from_line(store):
    remote = rebrickable_ready(store, Named())
    with transaction(store):
        zero = stock.add_loose(store, item_id=key(store, GEAR), quantity=1, condition='new')
        store.execute('UPDATE stock SET quantity=0 WHERE id=?', (zero['id'],))
    remote.lists[2]['2070-1'] = 0
    plan, _ = pulled(store, remote)
    row = next(r for r in plan['rows'] if r['number'] == '2070-1')
    assert row['lists'] == []
    assert not store.execute('SELECT 1 FROM synced_from WHERE stock_id=?', (zero['id'],)).fetchone()
    assert names_of(store, '2070-1') == []


def test_archived_rows_do_not_keep_a_list_alive_and_mixed_names_are_renamed(store):
    remote = rebrickable_ready(store, Named())
    pulled(store, remote)
    store.execute("UPDATE copy SET archived_at='2026-11-23T00:00:00.000Z' WHERE item_id=?", (key(store, '2070-1'),))
    store.execute("UPDATE stock SET archived_at='2026-11-23T00:00:00.000Z'")
    store.execute("UPDATE synced_from SET list_name='Old name' WHERE list_key='1' AND copy_id=(SELECT id FROM copy WHERE item_id=? AND archived_at IS NULL)",
                  (key(store, '1000-2'),))
    store.commit()
    sync.link(store, 'rebrickable', {'owned': [1]})
    del remote.lists[2], remote.names[2]
    assert '2' not in origins.lists_of(store, 'rebrickable')
    assert origins.lists_of(store, 'rebrickable')['1'] == ('Main collection', 2)
    assert origins.mixed_lists(store, 'rebrickable') == {'1'}
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    lines = {l['key']: l for l in plan['lists']['preview']}
    assert '2' not in lines and lines['1']['state'] == 'renamed' and lines['1']['action'] == 'rename'
    sync.apply_pull(store, plan['id'], [])
    assert set(names_of(store, '1000-1')) == {'Main collection'} and set(names_of(store, '1000-2')) == {'Main collection'}
    assert origins.mixed_lists(store, 'rebrickable') == set()


def test_plan_row_lists_follow_row_kind(store):
    remote = rebrickable_ready(store, Named())
    remote.lists[9]['1000-1'] = 1
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    by_kind = {r['kind']: r for r in plan['rows'] if r['number'] == '1000-1'}
    assert by_kind['owned']['lists'] == ['Main collection']
    assert by_kind['wanted']['lists'] == ['Wanted']
