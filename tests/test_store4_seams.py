"""The seams the app needs on the 4.0 store (M.8 preparation, issue #110): job kinds the runner owns, injectable credentials, and
the `_in` variants that run inside a caller's open write transaction. Invented data, no network."""
from contextlib import closing
import json

import pytest

from brickwork.store4 import bricklink_api, copies, jobs, keys, pending, rebrickable_api
from brickwork.store4.errors import Store4Error
from tests.test_store4_copies import KEYS as BL_KEYS, SET, add, db, key, no_key, q   # noqa: F401  (fixtures)
from tests.test_store4_pending import add_pending, mark, ok
from tests.test_store4_switch import events

BL = {'source': 'bricklink'}
V1, V2 = {'source': 'rebrickable', 'version': 1}, {'source': 'rebrickable', 'version': 2}


@pytest.fixture(autouse=True)
def no_provider():
    previous = keys.set_key_provider(None)
    yield
    keys.set_key_provider(previous)


def foreign(db, state='queued', kind='import_parse', via='import'):
    with db:
        return db.execute("""INSERT INTO job(source, kind, state, payload, via, created_at, updated_at)
                             VALUES('import', ?, ?, '{}', ?, '2026-10-25T00:00:00.000Z', '2026-10-25T00:00:00.000Z')""",
                          (kind, state, via)).lastrowid


def snapshot(db):
    return q(db, 'SELECT * FROM job ORDER BY id'), q(db, 'SELECT * FROM job_owner'), q(db, 'SELECT * FROM source_budget'), q(db, 'SELECT * FROM event')


# ---------- job kinds ----------

def test_drain_leaves_a_foreign_job_untouched(db, key):
    pipeline, failed_retry = foreign(db), foreign(db, 'failed')
    with db:
        db.execute("UPDATE job SET retry_at='2000-01-01T00:00:00.000Z' WHERE id=?", (failed_retry,))
    before = snapshot(db)
    assert jobs.drain(db) == []
    assert snapshot(db) == before
    assert jobs.status(db, pipeline)['state'] == 'queued'


def test_drain_still_runs_its_own_kind_beside_a_foreign_one(db, key):
    pipeline = foreign(db)
    own = jobs.queue(db, 'bricklink_subsets', item_id=SET, payload='6081-1', via='cli')
    ran = jobs.drain(db, http=ok())
    assert [r['id'] for r in ran] == [own] and ran[0]['state'] == 'done'
    assert jobs.status(db, pipeline)['state'] == 'queued'


def test_run_refuses_a_foreign_kind_clearly(db, key):
    pipeline = foreign(db)
    before = snapshot(db)
    with pytest.raises(jobs.ForeignKind, match="'import_parse'.*bricklink_subsets"):
        jobs.run(db, pipeline)
    assert snapshot(db) == before and not db.in_transaction


def test_settle_leftovers_ignores_a_foreign_job(db, key):
    cid = add_pending(db)['copy']['id']
    own = q(db, 'SELECT pending_job_id FROM copy WHERE id=?', cid)[0][0]
    with db:
        db.execute("UPDATE job SET kind='import_parse' WHERE id=?", (own,))          # the copy's job is now another runner's, and finished
        db.execute("UPDATE job SET state='failed', retry_at=NULL WHERE id=?", (own,))
    before = snapshot(db)
    jobs._settle_leftovers(db)
    assert snapshot(db) == before and q(db, 'SELECT inventory_pending FROM copy WHERE id=?', cid) == [('bricklink',)]


def test_settle_leftovers_still_settles_its_own(db, key):
    cid = add_pending(db)['copy']['id']
    own = q(db, 'SELECT pending_job_id FROM copy WHERE id=?', cid)[0][0]
    with db:
        db.execute("UPDATE job SET state='failed', retry_at=NULL, error_code='not_found' WHERE id=?", (own,))
    jobs._settle_leftovers(db)
    assert q(db, 'SELECT inventory_pending FROM copy WHERE id=?', cid) == [(None,)]


# ---------- credentials ----------

def test_the_environment_is_the_default(monkeypatch):
    for name in bricklink_api.KEY_ENVS:
        monkeypatch.setenv(name, 'v-' + name[-6:])
    monkeypatch.setenv(rebrickable_api.KEY_ENV, 'rb-key')
    assert bricklink_api.key_configured() and bricklink_api.credentials() == tuple('v-' + n[-6:] for n in bricklink_api.KEY_ENVS)
    assert rebrickable_api._headers()['Authorization'] == 'key rb-key'
    monkeypatch.delenv(rebrickable_api.KEY_ENV)
    with pytest.raises(rebrickable_api.FetchError):
        rebrickable_api._headers()
    monkeypatch.delenv(bricklink_api.KEY_ENVS[0])
    assert not bricklink_api.key_configured()
    with pytest.raises(Store4Error, match=bricklink_api.KEY_ENVS[0]):
        bricklink_api.credentials()


def test_a_provider_wins_and_the_environment_is_not_read(monkeypatch):
    for name in (*bricklink_api.KEY_ENVS, rebrickable_api.KEY_ENV):
        monkeypatch.setenv(name, 'from-env')
    asked = []
    store = {name: 'from-store' for name in (*bricklink_api.KEY_ENVS, rebrickable_api.KEY_ENV)}
    keys.set_key_provider(lambda name: asked.append(name) or store.get(name))
    assert bricklink_api.credentials() == ('from-store',) * 4
    assert rebrickable_api._headers()['Authorization'] == 'key from-store'
    assert set(asked) == {*bricklink_api.KEY_ENVS, rebrickable_api.KEY_ENV}


def test_a_provider_returning_none_means_not_configured(db, monkeypatch):
    for name in (*bricklink_api.KEY_ENVS, rebrickable_api.KEY_ENV):
        monkeypatch.setenv(name, 'from-env')                                          # the environment must not rescue it
    keys.set_key_provider(lambda name: None)
    assert not bricklink_api.key_configured() and not jobs._configured('rebrickable')
    with pytest.raises(Store4Error, match='not configured'):
        bricklink_api.credentials()
    with pytest.raises(rebrickable_api.FetchError):
        rebrickable_api._headers()
    job = jobs.queue(db, 'bricklink_subsets', item_id=SET, payload='6081-1', via='cli')
    out = jobs.run(db, job, http=lambda url, headers: pytest.fail('no call without a key'))
    assert (out['state'], out['error_code'], out['ran']) == ('failed', 'source_not_configured', False)


def test_a_provider_with_a_partial_key_set_is_not_configured():
    keys.set_key_provider({'BW_BRICKLINK_CONSUMER_KEY': 'a', 'BW_BRICKLINK_CONSUMER_SECRET': 'b'}.get)
    assert not bricklink_api.key_configured()


def test_a_provider_key_runs_a_job_and_is_masked_in_errors(db, monkeypatch):
    for name in (*bricklink_api.KEY_ENVS, rebrickable_api.KEY_ENV):
        monkeypatch.delenv(name, raising=False)
    keys.set_key_provider(lambda name: 'secret-' + name if name in bricklink_api.KEY_ENVS else None)
    assert jobs._safe('boom secret-' + bricklink_api.KEY_ENVS[2] + ' here') == 'boom [set] here'
    job = jobs.queue(db, 'bricklink_subsets', item_id=SET, payload='6081-1', via='cli')
    out = jobs.run(db, job, http=ok())
    assert out['state'] == 'done'


def test_the_provider_must_be_callable():
    with pytest.raises(TypeError):
        keys.set_key_provider('not callable')


# ---------- _in variants ----------

def outer(db):
    db.execute('BEGIN IMMEDIATE')


@pytest.mark.parametrize('call', [
    lambda db: copies.create_copy_in(db, SET, V2, via='cli'),
    lambda db: copies.switch_part_list_in(db, 'x', V1, via='cli'),
    lambda db: copies.undo_switch_in(db, 1, via='cli'),
    lambda db: copies.set_part_list_preference_in(db, SET, V1, via='cli'),
    lambda db: copies.set_prefer_bricklink_in(db, True, via='cli'),
    lambda db: pending.accept_pending_in(db, 'x', via='cli'),
    lambda db: pending.cancel_pending_in(db, 'x', via='cli'),
])
def test_each_in_variant_refuses_without_an_open_transaction(db, call):
    with pytest.raises(Store4Error, match='open write transaction'):
        call(db)
    assert not db.in_transaction


@pytest.mark.parametrize('call', [
    lambda db: copies.create_copy(db, SET, V2, via='cli'),
    lambda db: copies.switch_part_list(db, 'x', V1, via='cli'),
    lambda db: copies.undo_switch(db, 1, via='cli'),
    lambda db: copies.set_part_list_preference(db, SET, V1, via='cli'),
    lambda db: copies.set_prefer_bricklink(db, True, via='cli'),
    lambda db: pending.accept_pending(db, 'x', via='cli'),
    lambda db: pending.cancel_pending(db, 'x', via='cli'),
])
def test_the_plain_functions_still_refuse_inside_an_open_transaction(db, call):
    outer(db)
    with pytest.raises(Store4Error, match='own transaction'):
        call(db)
    db.rollback()


def test_two_operations_commit_together(db):
    outer(db)
    a = copies.create_copy_in(db, SET, V2, via='cli')
    b = copies.create_copy_in(db, SET, V1, via='cli')
    copies.switch_part_list_in(db, a['copy']['id'], V1, via='cli')
    copies.set_part_list_preference_in(db, SET, V1, via='cli')
    copies.set_prefer_bricklink_in(db, True, via='cli')
    assert db.in_transaction
    db.commit()
    assert q(db, 'SELECT count(*) FROM copy') == [(2,)]
    assert events(db, a['copy']['id']) == [('add',), ('part_list_switch',)]
    assert copies.part_list_preference(db, SET) == {'source': 'rebrickable', 'version': 1}
    assert q(db, "SELECT value FROM setting WHERE key='prefer_bricklink_inventory'") == [('true',)]
    assert q(db, 'SELECT inventory_version FROM copy WHERE id=?', b['copy']['id']) == [(1,)]


def test_two_operations_roll_back_together(db):
    outer(db)
    a = copies.create_copy_in(db, SET, V2, via='cli')
    copies.switch_part_list_in(db, a['copy']['id'], V1, via='cli')
    copies.set_part_list_preference_in(db, SET, V1, via='cli')
    copies.set_prefer_bricklink_in(db, True, via='cli')
    db.rollback()
    assert q(db, 'SELECT (SELECT count(*) FROM copy), (SELECT count(*) FROM copy_part), (SELECT count(*) FROM event),'
                 ' (SELECT count(*) FROM set_preference), (SELECT count(*) FROM setting)') == [(0, 0, 0, 0, 0)]


def test_a_failure_in_the_second_operation_rolls_the_first_back_with_it(db):
    outer(db)
    copies.create_copy_in(db, SET, V2, via='cli')
    with pytest.raises(copies.BadPreference):
        copies.set_part_list_preference_in(db, SET, {'source': 'nope'}, via='cli')
    assert db.in_transaction                                  # the caller decides; nothing was committed by the failure
    db.rollback()
    assert q(db, 'SELECT count(*) FROM copy') == [(0,)]


def test_undo_in_undoes_a_switch_in_the_callers_transaction(db):
    cid = add(db)['copy']['id']
    outer(db)
    switched = copies.switch_part_list_in(db, cid, V1, via='cli')
    undone = copies.undo_switch_in(db, switched['event_id'], via='cli')
    db.commit()
    assert undone['undoes'] == switched['event_id']
    assert events(db, cid) == [('add',), ('part_list_switch',), ('part_list_switch_undo',)]


def test_pending_in_variants_cancel_and_accept_inside_an_outer_transaction(db, key):
    cancel = add_pending(db)['copy']['id']
    outer(db)
    pending.cancel_pending_in(db, cancel, via='cli')
    db.rollback()
    assert q(db, 'SELECT inventory_pending FROM copy WHERE id=?', cancel) == [('bricklink',)]    # rolled back with the caller
    outer(db)
    pending.cancel_pending_in(db, cancel, via='cli')
    db.commit()
    assert q(db, 'SELECT inventory_pending FROM copy WHERE id=?', cancel) == [(None,)]

    accept = add_pending(db)['copy']['id']
    mark(db, accept, checked=1)                                # a marked copy is offered, not switched by the job
    job = q(db, 'SELECT pending_job_id FROM copy WHERE id=?', accept)[0][0]
    assert jobs.run(db, job, http=ok())['settled'][0]['outcome'] == 'offered'
    outer(db)
    receipt = pending.accept_pending_in(db, accept, via='cli')
    assert receipt['trigger'] == {'accepted': True, 'job_id': job}
    db.rollback()
    assert q(db, 'SELECT inventory_source, inventory_pending FROM copy WHERE id=?', accept) == [('rebrickable', 'bricklink')]
    outer(db)
    pending.accept_pending_in(db, accept, via='cli')
    db.commit()
    assert q(db, 'SELECT inventory_source, inventory_pending FROM copy WHERE id=?', accept) == [('bricklink', None)]
