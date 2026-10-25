"""BrickLink pending and preferences (design 4.3 decision F as amended; issue #108, M.6c): Add with nothing fetched, the job's
hook, automatic switch of an unmarked copy, the offer for a marked one, accept, cancel, a failed job, the preferences.
Invented data; the job runner's `http` is a fake, no test touches the network."""
import json

import pytest

from brickwork.store4 import copies, jobs, pending
from brickwork.store4.errors import Store4Error
from tests.test_store4_bricklink_subsets import entry, reply
from tests.test_store4_copies import FIG_A, NEWER_SET, SET, add, db, fetch, key, no_key, q   # noqa: F401  (fixtures)
from tests.test_store4_switch import events, live, live_figures, line_id, rows

BL = {'source': 'bricklink'}


def ok(*entries):
    """A BrickLink subsets reply that the transport serves: 3023 red x6 (the set's line (11, 3)), 3626 black x2, no figures."""
    entries = entries or (entry('3023', 5, 6), entry('3626', 11, 2))
    return lambda url, headers: (200, reply(*entries))


def add_pending(db, **kw):
    return add(db, BL, **kw)


def copy_row(db, cid):
    return q(db, 'SELECT inventory_source, inventory_version, fetched_inventory_id, inventory_pending, pending_job_id FROM copy WHERE id=?', cid)[0]


def mark(db, cid, item=11, colour=3, spare=0, **cols):
    with db:
        db.execute(f'UPDATE copy_part SET {", ".join(c + "=?" for c in cols)} WHERE id=?', (*cols.values(), line_id(db, cid, item, colour, spare)))


def run(db, job, http):
    return jobs.run(db, job, http=http)


def job_of(db, cid):
    return q(db, 'SELECT pending_job_id FROM copy WHERE id=?', cid)[0][0]


# ---------- Add with BrickLink and nothing fetched ----------

def test_add_with_nothing_fetched_gives_rebrickables_list_and_a_pending_job(db, key):
    r = add_pending(db)
    cid = r['copy']['id']
    job = job_of(db, cid)
    assert copy_row(db, cid) == ('rebrickable', 2, None, 'bricklink', job)               # the latest version at once
    assert [l for l in live(db, cid) if l[0] == 0] == [(0, 11, 3, 0, 5), (0, 11, 4, 1, 1), (0, 12, 4, 0, 2)]
    s = jobs.status(db, job)
    assert (s['kind'], s['state'], s['item_id'], s['number']) == ('bricklink_subsets', 'queued', SET, '6081-1')
    assert r['pending'] == {'source': 'bricklink', 'job_id': job, 'job_reused': False}
    assert r['copy']['inventory_pending'] == 'bricklink' and r['copy']['pending_job_id'] == job
    receipt = json.loads(q(db, "SELECT new_value FROM event WHERE entity_kind='copy' AND field='add'")[0][0])
    assert receipt['pending']['job_id'] == job
    assert events(db, cid) == [('add',)] and q(db, "SELECT count(*) FROM event WHERE entity_kind='job'") == [(1,)]


def test_a_pinned_version_is_the_base_while_pending(db, key):
    copies.set_part_list_preference(db, SET, {'source': 'rebrickable', 'version': 1}, via='cli')
    cid = add_pending(db)['copy']['id']
    assert copy_row(db, cid)[:2] == ('rebrickable', 1) and copy_row(db, cid)[3] == 'bricklink'


def test_a_second_copy_reuses_the_open_job(db, key):
    first, second = add_pending(db), add_pending(db)
    assert job_of(db, first['copy']['id']) == job_of(db, second['copy']['id'])
    assert (first['pending']['job_reused'], second['pending']['job_reused']) == (False, True)
    assert q(db, 'SELECT count(*) FROM job') == [(1,)]


def test_the_copy_and_its_job_commit_or_roll_back_together(db, key, monkeypatch):
    monkeypatch.setattr(copies.Events, 'write', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    with pytest.raises(RuntimeError):
        add_pending(db)
    assert q(db, 'SELECT (SELECT count(*) FROM copy), (SELECT count(*) FROM job), (SELECT count(*) FROM job_step)') == [(0, 0, 0)]
    assert not db.in_transaction


def test_a_set_without_a_rebrickable_list_is_refused_clearly_and_writes_nothing(db, key):
    with pytest.raises(copies.NoPartList, match='no Rebrickable list'):
        add(db, BL, item=NEWER_SET)
    assert q(db, 'SELECT (SELECT count(*) FROM copy), (SELECT count(*) FROM job), (SELECT count(*) FROM event)') == [(0, 0, 0)]


def test_a_fetched_list_means_no_pending_at_all(db, key):
    fetch(db, SET, 'bricklink', [(11, 3, 0, 7)])
    cid = add_pending(db)['copy']['id']
    assert copy_row(db, cid)[0] == 'bricklink' and copy_row(db, cid)[3:] == (None, None) and q(db, 'SELECT count(*) FROM job') == [(0,)]


def test_pending_copies_are_usable_and_the_offer_says_waiting(db, key):
    cid = add_pending(db)['copy']['id']
    offer = pending.pending_offer(db, cid)
    assert offer['state'] == 'waiting' and offer['job']['state'] == 'queued'
    assert pending.pending_offer(db, add(db)['copy']['id']) is None                      # a plain copy has no offer


# ---------- settling after the job ----------

def test_an_unmarked_copy_switches_by_itself_when_the_job_succeeds(db, key):
    cid = add_pending(db)['copy']['id']
    job = job_of(db, cid)
    r = run(db, job, ok())
    assert r['state'] == 'done' and [(s['copy_id'], s['outcome']) for s in r['settled']] == [(cid, 'switched')]
    fid = q(db, "SELECT id FROM fetched_inventory WHERE source='bricklink'")[0][0]
    assert copy_row(db, cid) == ('bricklink', None, fid, None, None)
    assert q(db, 'SELECT inventory_digest FROM copy') == q(db, 'SELECT digest FROM fetched_inventory WHERE id=?', fid)
    assert live(db, cid) == [(0, 11, 3, 0, 6), (0, 16, 4, 0, 2)]
    assert live_figures(db, cid) == []
    assert events(db, cid) == [('add',), ('part_list_switch',)]
    receipt = json.loads(q(db, "SELECT new_value FROM event WHERE field='part_list_switch'")[0][0])
    assert receipt['trigger'] == {'automatic': True, 'job_id': job}
    assert pending.pending_offer(db, cid) is None


def test_both_copies_on_the_one_job_settle_together_and_a_marked_one_is_offered(db, key):
    a, b = add_pending(db)['copy']['id'], add_pending(db)['copy']['id']
    mark(db, b, 11, 3, 0, checked=1)
    r = run(db, job_of(db, a), ok())
    assert sorted((s['outcome']) for s in r['settled']) == ['offered', 'switched']
    assert copy_row(db, a)[0] == 'bricklink' and copy_row(db, b)[0] == 'rebrickable' and copy_row(db, b)[3] == 'bricklink'


@pytest.mark.parametrize('column, where', [('checked', (11, 3, 0)), ('missing', (12, 4, 0)), ('damaged', (11, 4, 1))])
def test_a_marked_copy_is_never_switched_without_the_user_and_is_offered(db, key, column, where):
    cid = add_pending(db)['copy']['id']
    mark(db, cid, *where, **{column: 1})
    before = rows(db, cid)['parts']
    r = run(db, job_of(db, cid), ok())
    assert [s['outcome'] for s in r['settled']] == ['offered']
    assert rows(db, cid)['parts'] == before and copy_row(db, cid)[0] == 'rebrickable'
    offer = pending.pending_offer(db, cid)
    assert offer['state'] == 'ready' and offer['marked'] is True and offer['job']['state'] == 'done'
    nco = offer['preview']['not_carried_over']
    expected = [] if column == 'checked' else [(where[0], where[1], where[2])]            # the checked line stays in BrickLink's list
    assert [(l['item_id'], l['color_id'], l['is_spare']) for l in nco['retired']] == expected
    assert events(db, cid) == [('add',)]


def test_a_marked_figure_also_keeps_the_copy_from_switching(db, key):
    cid = add_pending(db)['copy']['id']
    with db:
        db.execute('UPDATE copy_figure SET missing=1 WHERE copy_id=? AND item_id=?', (cid, FIG_A))
    run(db, job_of(db, cid), ok())
    assert copy_row(db, cid)[3] == 'bricklink'
    retired = pending.pending_offer(db, cid)['preview']['not_carried_over']['retired']
    assert [(r['kind'], r['figure_item']) for r in retired] == [('figure', FIG_A)]


def test_the_offer_lists_what_would_not_carry_over(db, key):
    cid = add_pending(db)['copy']['id']
    mark(db, cid, 12, 4, 0, missing=2)                                                  # 970c03 is not in BrickLink's reply
    run(db, job_of(db, cid), ok())
    retired = pending.pending_offer(db, cid)['preview']['not_carried_over']['retired']
    assert [(r['kind'], r['item_id'], r['color_id'], r['missing']) for r in retired] == [('part', 12, 4, [2, 2])]


def test_a_retired_mark_does_not_hold_back_the_switch(db, key):
    cid = add_pending(db)['copy']['id']
    mark(db, cid, 11, 3, 0, checked=1)
    with db:
        db.execute('UPDATE copy_part SET retired_at=? WHERE id=?', ('2026-10-25T00:00:00Z', line_id(db, cid, 11, 3, 0)))
    r = run(db, job_of(db, cid), ok())
    assert [s['outcome'] for s in r['settled']] == ['switched']


def test_settle_can_be_called_directly_and_twice(db, key):
    cid = add_pending(db)['copy']['id']
    job = job_of(db, cid)
    assert pending.settle_pending(db, job, via='cli') == []                              # queued: nothing to do
    jobs.run(db, job, http=ok())                                                         # settles through the hook
    assert pending.settle_pending(db, via='cli') == [] and copy_row(db, cid)[0] == 'bricklink'


def test_a_job_waiting_for_budget_leaves_the_copy_pending_and_usable(db, key):
    cid = add_pending(db)['copy']['id']
    r = run(db, job_of(db, cid), lambda url, headers: (429, {}))
    assert r['state'] == 'waiting_for_budget' and 'settled' not in r
    assert copy_row(db, cid)[0] == 'rebrickable' and copy_row(db, cid)[3] == 'bricklink'
    assert pending.pending_offer(db, cid)['state'] == 'waiting'
    mark(db, cid, 11, 3, 0, checked=1)                                                   # still usable
    assert q(db, 'SELECT checked FROM copy_part WHERE copy_id=? AND item_id=11 AND color_id=3', cid) == [(1,)]


def test_a_transient_failure_that_will_be_retried_leaves_the_copy_pending(db, key):
    cid = add_pending(db)['copy']['id']
    r = run(db, job_of(db, cid), lambda url, headers: (500, {}))
    assert r['state'] == 'failed' and r['retry_at'] and 'settled' not in r
    assert copy_row(db, cid)[3] == 'bricklink' and pending.pending_offer(db, cid)['state'] == 'waiting'


@pytest.mark.parametrize('http, code', [(lambda u, h: (404, {}), 'not_found'),
                                        (lambda u, h: (200, {'meta': {'code': 200}, 'data': 'x'}), 'invalid_reply')])
def test_a_job_that_failed_for_good_releases_the_copy_on_its_rebrickable_list(db, key, http, code):
    cid = add_pending(db)['copy']['id']
    job = job_of(db, cid)
    r = run(db, job, http)
    assert r['state'] == 'failed' and r['error_code'] == code and r['retry_at'] is None
    assert [(s['outcome'], s['error_code']) for s in r['settled']] == [('released', code)]
    assert copy_row(db, cid) == ('rebrickable', 2, None, None, None)
    assert events(db, cid) == [('add',), ('pending_failed',)]
    new = json.loads(q(db, "SELECT new_value FROM event WHERE field='pending_failed'")[0][0])
    assert (new['job_id'], new['error_code'], new['inventory_source']) == (job, code, 'rebrickable')
    assert pending.pending_offer(db, cid) is None


def test_no_bricklink_number_fails_the_job_as_unidentified_and_releases(db, key):
    cid = add_pending(db)['copy']['id']
    with db:
        db.execute("DELETE FROM item_link WHERE item_id=? AND provider='bricklink'", (SET,))
    r = run(db, job_of(db, cid), ok())
    assert r['error_code'] == 'unidentified' and [s['outcome'] for s in r['settled']] == ['released']


def test_a_failed_job_is_released_when_it_fails_before_it_even_runs(db, key, monkeypatch):
    cid = add_pending(db)['copy']['id']
    for k in ('CONSUMER_KEY',):
        monkeypatch.delenv('BW_BRICKLINK_' + k)
    r = run(db, job_of(db, cid), ok())
    assert r['ran'] is False and r['error_code'] == 'source_not_configured' and [s['outcome'] for s in r['settled']] == ['released']


def test_drain_settles_too(db, key):
    cid = add_pending(db)['copy']['id']
    (r,) = jobs.drain(db, http=ok())
    assert copy_row(db, cid)[0] == 'bricklink' and r['settled'][0]['outcome'] == 'switched'


# ---------- accept and cancel ----------

def test_accept_is_the_switch_and_carries_the_marks_it_can(db, key):
    cid = add_pending(db)['copy']['id']
    mark(db, cid, 11, 3, 0, checked=1, missing=2)
    mark(db, cid, 12, 4, 0, missing=1)
    run(db, job_of(db, cid), ok())
    job = job_of(db, cid)
    r = pending.accept_pending(db, cid, via='app', actor='u')
    assert r['trigger'] == {'accepted': True, 'job_id': job}
    assert copy_row(db, cid)[0] == 'bricklink' and copy_row(db, cid)[3:] == (None, None)
    assert q(db, 'SELECT quantity, missing, checked FROM copy_part WHERE copy_id=? AND item_id=11 AND color_id=3 AND retired_at IS NULL', cid) == [(6, 2, 1)]
    assert [x['item_id'] for x in r['not_carried_over']['retired']] == [12]
    copies.undo_switch(db, r['event_id'], via='app')                                     # the exact undo still works, pending is back
    assert copy_row(db, cid)[3] == 'bricklink' and copy_row(db, cid)[4] == job


def test_accept_before_the_list_is_there_or_without_pending_is_refused(db, key):
    cid = add_pending(db)['copy']['id']
    with pytest.raises(pending.NotReady):
        pending.accept_pending(db, cid, via='app')
    with pytest.raises(pending.NotPending):
        pending.accept_pending(db, add(db)['copy']['id'], via='app')
    assert copy_row(db, cid)[3] == 'bricklink'


def test_cancel_clears_pending_with_one_event_and_leaves_the_lines_alone(db, key):
    cid = add_pending(db)['copy']['id']
    mark(db, cid, 11, 3, 0, checked=1)
    snapshot = rows(db, cid)['parts']
    run(db, job_of(db, cid), ok())
    job = job_of(db, cid)
    new = pending.cancel_pending(db, cid, via='app', actor='u')
    assert new['job_id'] == job and copy_row(db, cid) == ('rebrickable', 2, None, None, None)
    assert rows(db, cid)['parts'] == snapshot
    assert events(db, cid) == [('add',), ('pending_cancel',)]
    assert q(db, "SELECT via, actor FROM event WHERE field='pending_cancel'") == [('app', 'u')]
    assert pending.pending_offer(db, cid) is None
    with pytest.raises(pending.NotPending):
        pending.cancel_pending(db, cid, via='app')


def test_cancel_while_waiting_leaves_the_job_for_the_other_copies(db, key):
    a, b = add_pending(db)['copy']['id'], add_pending(db)['copy']['id']
    job = job_of(db, a)
    pending.cancel_pending(db, a, via='app')
    assert jobs.status(db, job)['state'] == 'queued' and copy_row(db, b)[3] == 'bricklink'
    r = run(db, job, ok())
    assert [s['copy_id'] for s in r['settled']] == [b] and copy_row(db, a)[0] == 'rebrickable'


# ---------- preferences ----------

def test_a_set_preference_round_trips_through_the_picker(db, key):
    assert copies.set_part_list_preference(db, SET, BL, via='app', actor='u') == {'source': 'bricklink', 'version': None}
    assert copies.part_list_choices(db, SET)['preselected'] == BL
    copies.set_part_list_preference(db, SET, {'source': 'rebrickable', 'version': 1}, via='app')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 1}
    copies.set_part_list_preference(db, SET, {'source': 'rebrickable'}, via='app')               # "always the latest"
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 2}
    copies.set_part_list_preference(db, SET, None, via='app')
    assert q(db, 'SELECT count(*) FROM set_preference') == [(0,)] and copies.part_list_preference(db, SET) is None
    ev = q(db, "SELECT entity_kind, entity_id, field, old_value, new_value, via FROM event WHERE entity_kind='set_preference' ORDER BY id")
    assert [(e[0], e[1], e[2], e[5]) for e in ev] == [('set_preference', str(SET), 'preference', 'app')] * 4
    assert json.loads(ev[1][3]) == {'source': 'bricklink', 'version': None} and json.loads(ev[1][4]) == {'source': 'rebrickable', 'version': 1}
    assert ev[3][4] is None


def test_setting_what_is_set_writes_no_event(db, key):
    copies.set_part_list_preference(db, SET, BL, via='app')
    copies.set_part_list_preference(db, SET, BL, via='app')
    copies.set_part_list_preference(db, NEWER_SET, None, via='app')
    assert q(db, "SELECT count(*) FROM event WHERE entity_kind='set_preference'") == [(1,)]


@pytest.mark.parametrize('choice', [{'source': 'rebrickable', 'version': 9}, {'source': 'bricklink', 'version': 1}, {'source': 'nope'},
                                    {'source': 'rebrickable', 'version': '1'}, {'source': 'rebrickable', 'version': True}])
def test_a_preference_the_schema_or_catalogue_refuses_changes_nothing(db, choice):
    with pytest.raises(copies.BadPreference):
        copies.set_part_list_preference(db, SET, choice, via='app')
    assert q(db, 'SELECT (SELECT count(*) FROM set_preference), (SELECT count(*) FROM event)') == [(0, 0)]


def test_a_preference_needs_a_set(db):
    with pytest.raises(copies.BadPreference, match='not a set'):
        copies.set_part_list_preference(db, 11, BL, via='app')


def test_the_global_switch_round_trips_through_the_picker_and_needs_a_key(db, key):
    assert copies.set_prefer_bricklink(db, True, via='app', actor='u') is True
    assert q(db, "SELECT value FROM setting WHERE key='prefer_bricklink_inventory'") == [('true',)]
    assert copies.part_list_choices(db, SET)['preselected'] == BL
    assert copies.set_prefer_bricklink(db, True, via='app') is True                       # unchanged: no second event
    copies.set_prefer_bricklink(db, False, via='app')
    assert q(db, "SELECT count(*) FROM setting WHERE key='prefer_bricklink_inventory'") == [(0,)]
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 2}
    assert q(db, "SELECT field, old_value, new_value FROM event WHERE entity_kind='setting' ORDER BY id") == [
        ('value', None, 'true'), ('value', 'true', None)]


def test_the_global_switch_has_no_effect_without_a_key(db):
    copies.set_prefer_bricklink(db, True, via='app')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 2}


def test_the_sets_preference_beats_the_global_switch(db, key):
    copies.set_prefer_bricklink(db, True, via='app')
    copies.set_part_list_preference(db, SET, {'source': 'rebrickable', 'version': 1}, via='app')
    assert copies.part_list_choices(db, SET)['preselected'] == {'source': 'rebrickable', 'version': 1}


def test_the_automatic_switch_checks_for_marks_inside_its_own_transaction(db, key):
    cid = add(db)['copy']['id']
    fetch(db, SET, 'bricklink', [(11, 3, 0, 6)])
    with db:
        db.execute('UPDATE copy_part SET checked=1 WHERE id=?', (line_id(db, cid, 11, 3, 0),))   # marked after any outside look
    before = rows(db, cid)
    with pytest.raises(copies.CopyMarked):
        copies.switch_part_list(db, cid, {'source': 'bricklink'}, via='cli', actor='t', unless_marked=True)
    assert rows(db, cid) == before and events(db, cid) == [('add',)]


def test_a_switch_for_a_job_the_copy_no_longer_waits_on_is_refused_and_writes_nothing(db, key):
    cid = add_pending(db)['copy']['id']
    job = job_of(db, cid)
    pending.cancel_pending(db, cid, via='cli', actor='t')                 # committed by "another connection" before the switch
    fetch(db, SET, 'bricklink', [(11, 3, 0, 6)])
    before = rows(db, cid)
    with pytest.raises(copies.PendingChanged):
        copies.switch_part_list(db, cid, BL, via='cli', actor='t', unless_marked=True, while_pending_on=job)
    assert rows(db, cid) == before


def test_drain_settles_copies_left_pending_on_a_job_that_finished_before_they_were_settled(db, key, monkeypatch):
    cid = add_pending(db)['copy']['id']
    settled = jobs._settled
    monkeypatch.setattr(jobs, '_settled', lambda db, out: out)              # the process stops between the job's commit and settling
    run(db, job_of(db, cid), ok())
    assert copy_row(db, cid)[3] == 'bricklink'
    monkeypatch.setattr(jobs, '_settled', settled)                          # not undo(): that would drop the key fixture too
    jobs.drain(db, http=ok())
    assert copy_row(db, cid)[0] == 'bricklink' and copy_row(db, cid)[3] is None
