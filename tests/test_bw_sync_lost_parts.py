"""Lost Parts from Rebrickable (#457): the adapter, the four rules, one or several copies, unmatched lines, the switch, a failed read, one Undo and
the setting. Invented data against the fake Rebrickable of test_bw_sync; no network.

Lines of the fixture sets (Rebrickable numbers): `1000-1` has 3001/4 x4, 3023/15 x2 and a spare 3023/4 x1; `1000-2` has 3001/4 x2 and 3023/15 x1.
`2070-1` has two copies (the `store` fixture), so a lost part of it needs a pick."""
from contextlib import closing
import json
from urllib.parse import parse_qs, urlparse

import pytest

from brickwork.core import admin, checker, errors, sync
from brickwork.core.connect import connect
from brickwork.core.sync import adapters, lost_parts
from tests.app4 import Coll
from tests.test_bw_sync import Rebrickable, TOKEN, pair, rebrickable_ready, store  # noqa: F401


def raw(set_no, part, colour, quantity, spare=False, number=1):
    """One result of the Lost Parts reply in the shape `parse_lost_part` assumes."""
    return dict(lost_part_id=number, lost_quantity=quantity,
                inv_part=dict(id=number, inv_part_id=number, part=dict(part_num=part, name='Invented'), color=dict(id=colour, name='Invented'),
                              set_num=set_no, quantity=9, is_spare=spare, element_id=None))


class Remote(Rebrickable):
    """The fake Rebrickable plus `/lost_parts/`: `lost` rows, paged `per_page` at a time, or `error` (an exception from the transport)."""

    def __init__(self, lost=(), per_page=1000):
        super().__init__()
        self.lost, self.per_page, self.error = list(lost), per_page, None

    def lost_calls(self):
        return [c for c in self.calls if c[1].endswith('/lost_parts/')]

    def __call__(self, request):
        url = urlparse(request.full_url)
        if not url.path.endswith('/lost_parts/'):
            return super().__call__(request)
        self.calls.append((request.get_method(), url.path, parse_qs(url.query)))
        if self.error:
            raise self.error
        page = int(parse_qs(url.query).get('page', ['1'])[0])
        chunk = self.lost[(page - 1) * self.per_page:page * self.per_page]
        return {'count': len(self.lost), 'next': 'more' if page * self.per_page < len(self.lost) else None, 'previous': None, 'results': chunk}


def copy_of(db, number, *, marks=()):
    """A copy of a fixture set with `marks` `[(part, colour, missing, spare)]` set on its lines; returns the copy id."""
    coll = Coll(db)
    copy_id = coll.add_copy(number)
    for part, colour, missing, *spare in marks:
        item, shade = coll.item('parts', part), coll.colour(colour)
        db.execute('UPDATE copy_part SET missing=?, checked=1 WHERE copy_id=? AND item_id=? AND color_id=? AND is_spare=? AND copy_figure_id IS NULL',
                   (missing, copy_id, item, shade, int(bool(spare and spare[0]))))
    db.commit()
    return copy_id


def marks(db, copy_id):
    """`{(part number, colour number, spare): missing}` of the copy's lines that are missing."""
    return {(r[0], r[1], bool(r[2])): r[3] for r in db.execute(
        '''SELECT i.born_key, c.born_key, p.is_spare, p.missing FROM copy_part p JOIN item i ON i.id=p.item_id JOIN color c ON c.id=p.color_id
           WHERE p.copy_id=? AND p.copy_figure_id IS NULL AND p.missing>0''', (copy_id,))}


def set_rule(db, value):
    admin.patch_settings(db, {'rebrickable_lost_parts_rule': value})


def planned(db, remote, rule=None):
    rebrickable_ready(db, remote)
    if rule:
        set_rule(db, rule)
    return sync.plan_pull(db, 'rebrickable', http=remote)


# --- the adapter ----------------------------------------------------------------------------

def test_the_adapter_pages_parses_and_sums(store):
    rebrickable_ready(store)
    rows = [raw('1000-1', '3001', 4, 1, number=1), raw('1000-1', '3001', 4, 2, number=2), raw('1000-1', '3023', 15, 1, number=3),
            raw('1000-2', '3001', 4, 1, True, number=4)]
    remote = Remote(rows, per_page=2)
    found = adapters.RebrickableUser(store, http=remote).lost_parts()
    assert len(remote.lost_calls()) == 2 and remote.lost_calls()[0][1] == f'/api/v3/users/{TOKEN}/lost_parts/'
    assert found['unreadable'] == 0
    assert {(r['set_no'], r['part_no'], r['color_id'], r['is_spare']): r['quantity'] for r in found['rows']} == {
        ('1000-1', '3001', 4, False): 3, ('1000-1', '3023', 15, False): 1, ('1000-2', '3001', 4, True): 1}
    assert TOKEN not in json.dumps([tuple(r) for r in store.execute('SELECT kind, key FROM source_record')])


@pytest.mark.parametrize('broken', [
    {'lost_quantity': 1}, {'lost_part_id': 1, 'lost_quantity': 0, 'inv_part': {}}, 'text',
    raw('1000-1', '3001', 4, 0), raw('1000-1', '3001', 4, -2), raw('1000-1', '3001', 4, 'many'),
    dict(raw('1000-1', '3001', 4, 1), inv_part=dict(raw('1000-1', '3001', 4, 1)['inv_part'], set_num=None)),
    dict(raw('1000-1', '3001', 4, 1), inv_part=dict(raw('1000-1', '3001', 4, 1)['inv_part'], part={})),
    dict(raw('1000-1', '3001', 4, 1), inv_part=dict(raw('1000-1', '3001', 4, 1)['inv_part'], is_spare='no')),
    raw('bad number!', '3001', 4, 1)])
def test_a_row_that_cannot_be_read_is_counted(store, broken):
    rebrickable_ready(store)
    found = adapters.RebrickableUser(store, http=Remote([raw('1000-1', '3023', 15, 1), broken])).lost_parts()
    assert found['unreadable'] == 1 and len(found['rows']) == 1


def test_the_template_accepts_only_the_lost_parts_path(store):
    rebrickable_ready(store)
    client = adapters.RebrickableUser(store, http=Remote())
    client.user_call('/lost_parts/', {'page': 1})
    with pytest.raises(ValueError):
        client.user_call('/lost_parts/1/', {})


# --- the four rules ---------------------------------------------------------------------------

def scenario(store):
    """A copy of 1000-1 with A=3001/4 missing 3, B=3023/15 missing 2; a copy of 1000-2 with 3001/4 missing 1. Rebrickable lists A x1 and the spare C x1 of 1000-1."""
    one = copy_of(store, '1000-1', marks=[('3001', '4', 3), ('3023', '15', 2)])
    two = copy_of(store, '1000-2', marks=[('3001', '4', 1)])
    remote = Remote([raw('1000-1', '3001', 4, 1, number=1), raw('1000-1', '3023', 4, 1, True, number=2)])
    return one, two, remote


EXPECTED = {
    'add_only': ({('3001', '4', False): 3, ('3023', '15', False): 2, ('3023', '4', True): 1}, {('3001', '4', False): 1}),
    'per_part': ({('3001', '4', False): 1, ('3023', '15', False): 2, ('3023', '4', True): 1}, {('3001', '4', False): 1}),
    'per_set': ({('3001', '4', False): 1, ('3023', '4', True): 1}, {('3001', '4', False): 1}),
    'everything': ({('3001', '4', False): 1, ('3023', '4', True): 1}, {}),
}
CLEARED = {'add_only': 0, 'per_part': 0, 'per_set': 1, 'everything': 2}


@pytest.mark.parametrize('rule', lost_parts.RULE_VALUES)
def test_each_rule_on_one_copy(store, rule):
    one, two, remote = scenario(store)
    plan = planned(store, remote, rule if rule != 'per_part' else None)       # per_part is the default: nothing stored
    lost = plan['lost']
    assert lost['status'] == 'read' and lost['rule'] == rule and lost['clearing']
    assert lost['summary']['cleared'] == CLEARED[rule]                            # the plan says how many marks it will clear
    assert {e['set_no'] for e in lost['sets']} == ({'1000-1', '1000-2'} if rule == 'everything' else {'1000-1'})
    assert marks(store, one) == {('3001', '4', False): 3, ('3023', '15', False): 2}      # a plan writes nothing
    result = sync.apply_pull(store, plan['id'], [])
    assert (marks(store, one), marks(store, two)) == EXPECTED[rule]
    assert result['counts']['lost_cleared'] == CLEARED[rule]
    assert result['counts']['lost_sets'] == len(lost['sets'])


def test_a_count_smaller_on_rebrickable_replaces_only_where_the_rule_says(store):
    one = copy_of(store, '1000-1', marks=[('3001', '4', 4)])
    plan = planned(store, Remote([raw('1000-1', '3001', 4, 1)]), 'add_only')
    assert plan['lost']['sets'] == []                                     # the larger count is kept: nothing to write
    sync.apply_pull(store, plan['id'], [])
    assert marks(store, one) == {('3001', '4', False): 4}
    plan = planned(store, Remote([raw('1000-1', '3001', 4, 1)]), 'per_part')
    assert plan['lost']['sets'][0]['preview']['replaced'] == 1
    sync.apply_pull(store, plan['id'], [])
    assert marks(store, one) == {('3001', '4', False): 1}


def test_the_derived_completeness_follows_the_marks(store):
    one = copy_of(store, '1000-1')
    sync.apply_pull(store, planned(store, Remote([raw('1000-1', '3001', 4, 1)]))['id'], [])
    assert store.execute('SELECT completeness FROM copy WHERE id=?', (one,)).fetchone()[0] in ('incomplete', None)
    assert store.execute("SELECT count(*) FROM event WHERE entity_kind='part_check' AND entity_id=?", (checker.entity_id(one),)).fetchone()[0] == 1


# --- one copy or several ----------------------------------------------------------------------

def two_copies_line(store):
    copies = [r[0] for r in store.execute("SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='2070-1' AND c.archived_at IS NULL ORDER BY c.created_at, c.id")]
    line = store.execute('''SELECT i.born_key, c.born_key, p.quantity FROM copy_part p JOIN item i ON i.id=p.item_id JOIN color c ON c.id=p.color_id
                            WHERE p.copy_id=? AND p.copy_figure_id IS NULL AND p.is_spare=0 AND p.retired_at IS NULL ORDER BY p.id LIMIT 1''', (copies[0],)).fetchone()
    return copies, raw('2070-1', line[0], int(line[1]), 1)


def test_several_copies_need_a_pick(store):
    first, second = (None, None)
    copies, row = two_copies_line(store)
    remote = Remote([row])
    plan = planned(store, remote)
    entry = plan['lost']['sets'][0]
    assert entry['state'] == 'pick' and entry['copy_id'] is None and [c['id'] for c in entry['copies']] == copies
    assert entry['lost'][0]['part_no'] == row['inv_part']['part']['part_num'] and plan['lost']['summary']['pick'] == 1
    left = sync.apply_pull(store, plan['id'], [])
    receipt = json.loads(store.execute("SELECT new_value FROM event WHERE id=?", (left['event_id'],)).fetchone()[0])['lost']
    assert receipt['left_out'] == [dict(set_no='2070-1', parts=1, reason='Choose a copy')] and not receipt['events']
    assert not any(marks(store, c) for c in copies)
    picked = sync.apply_pull(store, planned(store, remote)['id'], [], picks={'2070-1': copies[1]})
    assert marks(store, copies[1]) and not marks(store, copies[0])
    assert picked['counts']['lost_sets'] == 1


def test_a_pick_must_be_a_copy_of_that_set(store):
    copies, row = two_copies_line(store)
    other = copy_of(store, '1000-2')
    plan = planned(store, Remote([row]))
    with pytest.raises(errors.ValidationFailed, match='not a copy'):
        sync.apply_pull(store, plan['id'], [], picks={'2070-1': other})
    with pytest.raises(errors.ValidationFailed, match='Unknown Lost Parts sets'):
        sync.apply_pull(store, plan['id'], [], picks={'1000-1': copies[0]})
    assert not marks(store, other)


def test_untick_a_set_leaves_it_alone(store):
    one = copy_of(store, '1000-1')
    plan = planned(store, Remote([raw('1000-1', '3001', 4, 2)]))
    sync.apply_pull(store, plan['id'], [], lost=[])
    assert not marks(store, one)


def test_a_set_with_one_copy_and_one_archived_is_a_single_copy(store):
    gone = copy_of(store, '1000-1')
    store.execute("UPDATE copy SET archived_at='2026-01-01' WHERE id=?", (gone,))
    store.commit()
    live = copy_of(store, '1000-1')
    plan = planned(store, Remote([raw('1000-1', '3001', 4, 2)]))
    assert plan['lost']['sets'][0]['state'] == 'ready' and plan['lost']['sets'][0]['copy_id'] == live


# --- no matching line --------------------------------------------------------------------------

def test_unmatched_lines_are_listed_with_the_reason(store):
    one = copy_of(store, '1000-1', marks=[('3023', '15', 1)])
    remote = Remote([raw('1000-1', '3001', 4, 1, number=1),               # matches
                     raw('1000-1', '9999', 4, 1, number=2),               # no such part on the copy
                     raw('1000-1', '3001', 15, 1, number=3),              # colour not on the copy
                     raw('1000-1', '3023', 4, 1, number=4),               # the line is a spare, the row says it is not
                     raw('1000-1', '3001', 4, 9, True, number=5),         # spare row for a part that has no spare line
                     raw('1000-1', '3023', 15, 5, number=6),              # more than the line holds
                     raw('1000-4', '3001', 4, 1, number=7),               # a set with no copy
                     raw('77777-1', '3001', 4, 1, number=8)])             # a set Brick Work does not know
    plan = planned(store, remote, 'everything')
    entry = plan['lost']['sets'][0]['preview']
    reasons = sorted(u['reason'] for u in entry['unmatched_list'])
    assert len(reasons) == 5 and sum('No line' in r for r in reasons) == 4
    assert any("holds 2" in r for r in reasons)
    assert entry['not_cleared'] and not entry['cleared'], 'a set with an unmatched part is not cleared'
    assert {u['set_no']: u['reason'] for u in plan['lost']['unmatched_sets']}['1000-4'].startswith('No copy of this set')
    assert 'No unique set' in {u['set_no']: u['reason'] for u in plan['lost']['unmatched_sets']}['77777-1']
    sync.apply_pull(store, plan['id'], [])
    assert marks(store, one) == {('3001', '4', False): 1, ('3023', '15', False): 1}
    receipt = json.loads(store.execute("SELECT new_value FROM event WHERE entity_kind='sync' ORDER BY id DESC").fetchone()[0])['lost']
    assert len(receipt['unmatched']) == 5 and len(receipt['unmatched_sets']) == 2


def test_a_spare_row_matches_the_spare_line(store):
    one = copy_of(store, '1000-1')
    sync.apply_pull(store, planned(store, Remote([raw('1000-1', '3023', 4, 1, True)]))['id'], [])
    assert marks(store, one) == {('3023', '4', True): 1}


def test_a_copy_on_a_bricklink_list_matches_through_the_link(store):
    """A line whose item is a local BrickLink-born part with a confirmed Rebrickable link still matches the Rebrickable number."""
    one = copy_of(store, '1000-1')
    coll = Coll(store)
    local = coll.local('part', 'Local brick', born_key='3001bl')
    store.execute('INSERT INTO main.item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,decided_at) '
                  "VALUES(?,NULL,'rebrickable','part','3001','matched','external_ids','shipped',0,'2026-10-26T12:00:00Z')", (local,))
    store.execute('UPDATE copy_part SET item_id=? WHERE copy_id=? AND item_id=? AND is_spare=0 AND color_id=?',
                  (local, one, coll.item('parts', '3001'), coll.colour('4')))
    store.commit()
    sync.apply_pull(store, planned(store, Remote([raw('1000-1', '3001', 4, 2)]))['id'], [])
    assert store.execute('SELECT missing FROM copy_part WHERE copy_id=? AND item_id=?', (one, local)).fetchone()[0] == 2


# --- the switch, a failed read and the guards ---------------------------------------------------

def test_the_switch_is_on_by_default_and_remembered(store):
    remote = Remote([raw('1000-1', '3001', 4, 1)])
    rebrickable_ready(store, remote)
    assert sync.lost_parts_on(store, 'rebrickable') and sync.plan_pull(store, 'rebrickable', http=remote)['lost']['status'] == 'read'
    calls = len(remote.lost_calls())
    plan = sync.plan_pull(store, 'rebrickable', http=remote, lost_parts_switch=False)
    assert plan['lost']['status'] == 'off' and plan['lost']['sets'] == [] and len(remote.lost_calls()) == calls
    assert plan['rows'], 'the set comparison is the same'
    assert not sync.lost_parts_on(store, 'rebrickable') and sync.status(store, 'rebrickable')['link']['lost_parts'] is False
    assert sync.plan_pull(store, 'rebrickable', http=remote)['lost']['status'] == 'off' and len(remote.lost_calls()) == calls
    assert sync.plan_pull(store, 'rebrickable', http=remote, lost_parts_switch=True)['lost']['status'] == 'read'
    assert len(remote.lost_calls()) == calls + 1
    with pytest.raises(errors.ValidationFailed):
        sync.link(store, 'rebrickable', {'lost_parts': 'yes'})


def test_a_failed_read_leaves_the_set_sync_whole(store):
    remote = rebrickable_ready(store, Remote([raw('1000-1', '3001', 4, 1)]))
    remote.error = RuntimeError('boom TOKEN ' + TOKEN)
    plan = sync.plan_pull(store, 'rebrickable', http=remote)
    assert plan['lost']['status'] == 'failed' and 'were not read' in plan['lost']['message'] and TOKEN not in json.dumps(plan)
    assert not plan['lost']['sets'] and {r['number'] for r in plan['rows']} >= {'1000-1', '1000-2'}
    result = sync.apply_pull(store, plan['id'])
    assert result['counts'] == dict(copies=3, stock=1, wishes_added=1, wishes_changed=0)
    receipt = json.loads(store.execute("SELECT new_value FROM event WHERE id=?", (result['event_id'],)).fetchone()[0])['lost']
    assert receipt['status'] == 'failed' and not receipt['events']


def test_a_throttled_read_is_said_plainly(store):
    remote = rebrickable_ready(store, Remote())
    remote.lost_reply = None

    def throttled(request, original=remote.__call__):
        if urlparse(request.full_url).path.endswith('/lost_parts/'):
            return {'detail': 'Request was throttled. Expected available in 30 seconds.'}
        return original(request)
    plan = sync.plan_pull(store, 'rebrickable', http=throttled)
    assert plan['lost']['status'] == 'failed' and 'paused' in plan['lost']['message'] and plan['rows']


def test_an_unreadable_row_turns_clearing_off(store):
    """The reply shape is assumed: when a row cannot be read, nothing is cleared, whatever the rule."""
    one = copy_of(store, '1000-1', marks=[('3023', '15', 2)])
    plan = planned(store, Remote([raw('1000-1', '3001', 4, 1), {'surprise': True}]), 'everything')
    lost = plan['lost']
    assert lost['unreadable'] == 1 and not lost['clearing'] and 'nothing is cleared' in lost['message'] and lost['summary']['cleared'] == 0
    sync.apply_pull(store, plan['id'], [])
    assert marks(store, one) == {('3023', '15', False): 2, ('3001', '4', False): 1}


def test_everything_with_an_empty_list_clears_the_synced_sets_only(store):
    synced = copy_of(store, '1000-1', marks=[('3001', '4', 2)])
    elsewhere = copy_of(store, '1000-3', marks=[('3001', '4', 1)])           # 1000-3 is only on the wishlist list: not an owned set
    plan = planned(store, Remote([]), 'everything')
    assert plan['lost']['summary']['cleared'] == 1
    sync.apply_pull(store, plan['id'], [])
    assert not marks(store, synced) and marks(store, elsewhere) == {('3001', '4', False): 1}


# --- one Undo ------------------------------------------------------------------------------------

def test_one_undo_restores_the_sets_and_every_mark(store):
    one, two, remote = scenario(store)
    plan = planned(store, remote, 'everything')
    result = sync.apply_pull(store, plan['id'])
    receipt = json.loads(store.execute('SELECT new_value FROM event WHERE id=?', (result['event_id'],)).fetchone()[0])
    assert len(receipt['lost']['events']) == 2 and result['counts']['copies'] == 1       # the pull also adds the second copy of 1000-1, which takes no mark
    assert (marks(store, one), marks(store, two)) == EXPECTED['everything']
    undone = sync.undo(store, result['event_id'])
    assert not undone['already_undone']
    assert marks(store, one) == {('3001', '4', False): 3, ('3023', '15', False): 2} and marks(store, two) == {('3001', '4', False): 1}
    assert store.execute('SELECT count(*) FROM event_undo').fetchone()[0] == 3        # the pull and its two copies' receipts
    assert sync.undo(store, result['event_id'])['already_undone']
    assert not live_marks_on_new_copies(store, one, two)


def live_marks_on_new_copies(store, *known):
    """Marks on any live copy other than `known`: the copy the pull added is archived by the Undo and carries none."""
    return [c for (c,) in store.execute("SELECT id FROM copy WHERE archived_at IS NULL AND id IN (SELECT copy_id FROM copy_part WHERE missing>0)") if c not in known]


def test_undo_is_refused_whole_when_a_mark_changed_since(store):
    one, two, remote = scenario(store)
    result = sync.apply_pull(store, planned(store, remote, 'per_set')['id'], [])
    checker.mark(store, one, [(f"p:{store.execute('SELECT id FROM copy_part WHERE copy_id=? AND is_spare=1', (one,)).fetchone()[0]}", dict(missing=0))])
    with pytest.raises(errors.UndoBlocked, match='changed since'):
        sync.undo(store, result['event_id'])
    assert marks(store, one) == {('3001', '4', False): 1}, 'nothing was half undone'


def test_an_old_receipt_without_lost_parts_still_undoes(store):
    remote = rebrickable_ready(store, Remote())
    result = sync.apply_pull(store, sync.plan_pull(store, 'rebrickable', http=remote, lost_parts_switch=False)['id'])
    assert 'lost' not in json.loads(store.execute('SELECT new_value FROM event WHERE id=?', (result['event_id'],)).fetchone()[0])
    assert not sync.undo(store, result['event_id'])['already_undone']


# --- the setting ---------------------------------------------------------------------------------

def test_the_rule_setting_validates_saves_and_undoes(store):
    assert admin.settings(store)['rebrickable_lost_parts_rule'] == 'per_part'
    assert [v for v, _, _ in lost_parts.RULES] == ['add_only', 'per_part', 'per_set', 'everything']
    for bad in ('rebrickable', '', None, 3, ['per_set']):
        with pytest.raises(errors.ValidationFailed):
            admin.patch_settings(store, {'rebrickable_lost_parts_rule': bad})
    assert store.execute("SELECT 1 FROM setting WHERE key='rebrickable_lost_parts_rule'").fetchone() is None
    with pytest.raises(ValueError):
        admin.save_settings(store, 'DE', admin.settings(store)['priority'], [], rebrickable_lost_parts_rule='all')
    assert admin.save_settings(store, 'DE', admin.settings(store)['priority'], [], rebrickable_lost_parts_rule='per_part') is None      # the shown value is no change
    event = admin.save_settings(store, 'DE', admin.settings(store)['priority'], [], rebrickable_lost_parts_rule='everything')
    assert admin.settings(store)['rebrickable_lost_parts_rule'] == 'everything'
    assert admin.save_settings(store, 'DE', admin.settings(store)['priority'], []) is None                     # None leaves it
    assert admin.settings(store)['rebrickable_lost_parts_rule'] == 'everything'
    from brickwork.core import undo
    undo.undo_event(store, event)
    assert admin.settings(store)['rebrickable_lost_parts_rule'] == 'per_part'
    assert store.execute("SELECT 1 FROM setting WHERE key='rebrickable_lost_parts_rule'").fetchone() is None
    assert admin.patch_settings(store, {'rebrickable_lost_parts_rule': 'add_only'})['rebrickable_lost_parts_rule'] == 'add_only'


def test_an_unknown_stored_rule_reads_as_the_default(store):
    store.execute("INSERT INTO setting(key,value) VALUES('rebrickable_lost_parts_rule','weird')")
    store.commit()
    assert admin.settings(store)['rebrickable_lost_parts_rule'] == 'per_part'


def test_the_rule_in_the_api_body_and_the_cli(store, tmp_path, monkeypatch):
    from brickwork.api2 import write_money
    assert write_money.settings_body(store)['rebrickable_lost_parts_rule'] == 'per_part'
    from brickwork.web import admin_ops
    from contextlib import contextmanager

    @contextmanager
    def same(read_only=False):
        yield store
    monkeypatch.setattr(admin_ops, '_settings_db', same)
    assert admin_ops.settings_set('rebrickable_lost_parts_rule', 'per_set') == {'rebrickable_lost_parts_rule': 'per_set'}
    assert admin.settings(store)['rebrickable_lost_parts_rule'] == 'per_set'
    with pytest.raises(errors.ValidationFailed):
        admin_ops.settings_set('rebrickable_lost_parts_rule', 'nope')


# Review fixes (2026-11-17) ---------------------------------------------------------------------

def test_fingerprint_is_the_edits_as_plain_data():
    assert lost_parts.fingerprint(dict(trail=[['p:9', 2, 0], ['p:3', 0, 2]])) == [['p:3', 0, 2], ['p:9', 2, 0]]


def test_a_mark_made_after_the_preview_is_not_cleared(store):
    """Review P1: the pull writes a copy only when the copy still gives the edits the preview showed."""
    one, two, remote = scenario(store)
    plan = planned(store, remote, 'per_set')
    line = store.execute('SELECT p.id FROM copy_part p JOIN item i ON i.id=p.item_id WHERE p.copy_id=? AND p.copy_figure_id IS NULL AND i.born_key=? AND p.is_spare=0',
                         (one, '3023')).fetchone()[0]
    checker.mark(store, one, [('p:%d' % line, dict(missing=1, checked=True))])           # 2 missing at the preview, 1 now
    before = marks(store, one)
    result = sync.apply_pull(store, plan['id'], [])
    assert marks(store, one) == before                                           # the new mark and the old ones stay
    receipt = json.loads(store.execute('SELECT new_value FROM event WHERE id=?', (result['event_id'],)).fetchone()[0])['lost']
    assert receipt['skipped'] == [dict(set_no='1000-1', reason='The missing parts of this copy changed since the preview. Preview the pull again')]
    assert not receipt['events']


def test_the_copy_chooser_says_what_each_copy_would_change(store):
    """Review P2: a set with several copies has a preview per copy, shown on the option, and a changed copy is skipped at apply."""
    copies, row = two_copies_line(store)
    plan = planned(store, Remote([row]))
    entry = plan['lost']['sets'][0]
    assert set(entry['previews']) == set(copies) and all(p['added'] == 1 and p['cleared'] == 0 for p in entry['previews'].values())
    assert [c['effect'] for c in entry['copies']] == ['adds 1', 'adds 1']
    line = store.execute('SELECT id FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL AND is_spare=0 ORDER BY id LIMIT 1', (copies[1],)).fetchone()[0]
    checker.mark(store, copies[1], [('p:%d' % line, dict(missing=1, checked=True))])      # the pick's own line changes after the preview
    result = sync.apply_pull(store, plan['id'], [], picks={'2070-1': copies[1]})
    receipt = json.loads(store.execute('SELECT new_value FROM event WHERE id=?', (result['event_id'],)).fetchone()[0])['lost']
    assert [s['set_no'] for s in receipt['skipped']] == ['2070-1'] and not receipt['events']


def test_two_remote_rows_for_one_line_are_one_count(store):
    """Review P2: rows that resolve to the same line (an item with several Rebrickable numbers) are summed, never two edits on one line."""
    one = copy_of(store, '1000-1')
    index = lost_parts._lines(store, one)[1]
    key, lines = next((k, v) for k, v in index.items() if not k[2] and len(v) == 1 and v[0]['quantity'] >= 3)
    alias = dict(index)
    alias[('alias-number', key[1], False)] = lines
    rows = [dict(part_no=key[0], color_id=int(key[1]), is_spare=False, quantity=2), dict(part_no='alias-number', color_id=int(key[1]), is_spare=False, quantity=1)]
    original = lost_parts._lines
    lost_parts._lines = lambda db, copy_id: (original(db, copy_id)[0], alias)
    try:
        result = lost_parts.changes(store, one, rows, 'add_only')
    finally:
        lost_parts._lines = original
    assert result['edits'] == [('p:%d' % lines[0]['id'], dict(missing=3, checked=True))] and len(result['added']) == 1
