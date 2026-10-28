"""A copy that already exists moves to BrickLink's list (design 4.3 decision F, existing copy; issue #112, M.10 A): at once when a BrickLink
list is fetched, else it waits on the queued `bricklink_subsets` job and the job's success runs the automatic switch. Invented data."""
import pytest

from brickwork.store4 import copies, jobs, pending
from brickwork.store4.errors import Store4Error
from tests.test_store4_copies import SET, add, db, fetch, key, no_key, q   # noqa: F401  (fixtures)
from tests.test_store4_pending import copy_row, job_of, ok, run
from tests.test_store4_switch import events


def request(db, cid):
    return pending.request_bricklink(db, cid, via='cli', actor='t')


def test_with_a_fetched_list_the_copy_switches_at_once(db, key):
    fid = fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
    cid = add(db)['copy']['id']
    r = request(db, cid)
    assert r['switched'] is True and r['receipt']['event_id']
    assert copy_row(db, cid) == ('bricklink', None, fid, None, None)
    assert events(db, cid) == [('add',), ('part_list_switch',)]


def test_without_one_the_copy_waits_on_a_queued_job_and_keeps_its_list(db, key):
    cid = add(db)['copy']['id']
    before = copy_row(db, cid)
    r = request(db, cid)
    job = job_of(db, cid)
    assert r == {'switched': False, 'pending': {'source': 'bricklink', 'job_id': job, 'job_reused': False}}
    assert copy_row(db, cid)[:3] == before[:3] and copy_row(db, cid)[3:] == ('bricklink', job)
    assert q(db, 'SELECT kind, state, item_id FROM job WHERE id=?', job) == [('bricklink_subsets', 'queued', SET)]
    assert pending.pending_offer(db, cid)['state'] == 'waiting'
    assert events(db, cid) == [('add',), ('pending_request',)]


def test_the_jobs_success_runs_the_automatic_switch(db, key):
    cid = add(db)['copy']['id']
    request(db, cid)
    r = run(db, job_of(db, cid), ok())
    assert [(s['copy_id'], s['outcome']) for s in r['settled']] == [(cid, 'switched')]
    assert copy_row(db, cid)[0] == 'bricklink' and copy_row(db, cid)[3:] == (None, None)


def test_a_second_copy_reuses_the_open_job(db, key):
    a, b = add(db)['copy']['id'], add(db)['copy']['id']
    request(db, a)
    assert request(db, b)['pending']['job_reused'] is True and job_of(db, a) == job_of(db, b)


def test_the_request_is_refused_without_a_key_when_waiting_or_already_on_it(db, key, monkeypatch):
    cid = add(db)['copy']['id']
    request(db, cid)
    with pytest.raises(Store4Error, match='already waiting'):
        request(db, cid)
    fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
    done = add(db)['copy']['id']
    request(db, done)
    with pytest.raises(copies.NothingToSwitch):
        request(db, done)
    for name in ('CONSUMER_KEY', 'CONSUMER_SECRET', 'TOKEN_VALUE', 'TOKEN_SECRET'):
        monkeypatch.delenv('BW_BRICKLINK_' + name)
    with pytest.raises(Store4Error, match='needs a BrickLink key|without a BrickLink key'):
        request(db, add(db)['copy']['id'])


def test_remembering_rides_the_switch_and_its_undo_and_is_refused_before_a_write(db, key):
    from brickwork.core import undo
    cid = add(db, {'source': 'rebrickable', 'version': 2})['copy']['id']
    receipt = copies.switch_part_list(db, cid, {'source': 'rebrickable', 'version': 1}, via='cli', remember=True)
    assert copies.part_list_preference(db, SET) == {'source': 'rebrickable', 'version': 1}
    assert receipt['preference'] == {'old': None, 'new': {'source': 'rebrickable', 'version': 1}}
    undo.undo_event(db, receipt['event_id'], via='cli')
    assert copies.part_list_preference(db, SET) is None and copy_row(db, cid)[1] == 2
    with pytest.raises(copies.BadPreference):
        copies.switch_part_list(db, cid, {'source': 'rebrickable_api'}, via='cli', remember=True)
    assert copy_row(db, cid)[1] == 2 and events(db, cid)[-1] == ('part_list_switch_undo',)


def test_a_pending_request_can_remember_bricklink_in_the_same_transaction(db, key):
    cid = add(db)['copy']['id']
    pending.request_bricklink(db, cid, via='cli', remember=True)
    assert copies.part_list_preference(db, SET) == {'source': 'bricklink', 'version': None} and copy_row(db, cid)[3] == 'bricklink'


def test_a_copy_on_bricklink_takes_a_newer_fetched_list(db, key):
    first = fetch(db, SET, 'bricklink', [(11, 3, 0, 5)])
    cid = add(db)['copy']['id']
    request(db, cid)
    assert copy_row(db, cid)[2] == first
    second = fetch(db, SET, 'bricklink', [(11, 3, 0, 8)])
    assert request(db, cid)['switched'] is True and copy_row(db, cid)[2] == second
    with pytest.raises(copies.NothingToSwitch):
        request(db, cid)


# ---------- Codex review 2: Undo restores the stored preference as it was; a pending request keeps its old value ----------

def test_undo_restores_a_preference_the_catalogue_no_longer_has(db, key):
    from brickwork.core import undo
    cid = add(db, {'source': 'rebrickable', 'version': 2})['copy']['id']
    with db:
        db.execute("INSERT INTO set_preference(item_id, inventory_source, inventory_version, decided_at) VALUES(?, 'rebrickable', 99, '2026-10-25T00:00:00Z')", (SET,))
    receipt = copies.switch_part_list(db, cid, {'source': 'rebrickable', 'version': 1}, via='cli', remember=True)
    assert copies.part_list_preference(db, SET) == {'source': 'rebrickable', 'version': 1}
    undo.undo_event(db, receipt['event_id'], via='cli')                                    # version 99 left the catalogue; Undo must not mind
    assert copies.part_list_preference(db, SET) == {'source': 'rebrickable', 'version': 99} and copy_row(db, cid)[1] == 2


def test_a_pending_request_keeps_the_old_preference_for_the_switch_that_settles_it(db, key):
    from brickwork.core import undo
    copies.set_part_list_preference(db, SET, {'source': 'rebrickable', 'version': 1}, via='cli')
    cid = add(db)['copy']['id']
    pending.request_bricklink(db, cid, via='cli', remember=True)
    assert copies.part_list_preference(db, SET) == {'source': 'bricklink', 'version': None}
    r = run(db, job_of(db, cid), ok())
    event = [s for s in r['settled'] if s['copy_id'] == cid][0]['event_id']
    assert copy_row(db, cid)[0] == 'bricklink'
    undo.undo_event(db, event, via='cli')                                                  # one Undo takes the switch and the preference back
    assert copy_row(db, cid)[0] == 'rebrickable' and copies.part_list_preference(db, SET) == {'source': 'rebrickable', 'version': 1}


def test_accepting_a_ready_offer_carries_the_old_preference_too(db, key):
    from brickwork.core import undo
    cid = add(db)['copy']['id']
    with db:
        db.execute('UPDATE copy_part SET checked=1 WHERE copy_id=? AND retired_at IS NULL AND is_spare=0 AND copy_figure_id IS NULL', (cid,))
    pending.request_bricklink(db, cid, via='cli', remember=True)
    run(db, job_of(db, cid), ok())                                                         # marked: stays pending, offered
    receipt = pending.accept_pending(db, cid, via='cli')
    undo.undo_event(db, receipt['event_id'], via='cli')
    assert copies.part_list_preference(db, SET) is None


def test_cancelling_a_pending_request_puts_the_old_preference_back(db, key):
    copies.set_part_list_preference(db, SET, {'source': 'rebrickable', 'version': 1}, via='cli')
    cid = add(db)['copy']['id']
    pending.request_bricklink(db, cid, via='cli', remember=True)
    pending.cancel_pending(db, cid, via='cli')
    assert copies.part_list_preference(db, SET) == {'source': 'rebrickable', 'version': 1} and copy_row(db, cid)[3] is None
    other = add(db)['copy']['id']                                                          # a preference changed since is left alone
    pending.request_bricklink(db, other, via='cli', remember=True)
    copies.set_part_list_preference(db, SET, {'source': 'rebrickable', 'version': 2}, via='cli')
    pending.cancel_pending(db, other, via='cli')
    assert copies.part_list_preference(db, SET) == {'source': 'rebrickable', 'version': 2}
