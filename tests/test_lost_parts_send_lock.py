"""The Lost Parts send is locked (#469, the owner's decision): no route sends, a stored direction has no effect, pulling in still works."""
import pytest
from werkzeug.datastructures import MultiDict

from brickwork.core import admin, errors, sync
from brickwork.core.sync import lost_parts_send, run as sync_run, run_job
from tests.app4 import app4, client  # noqa: F401
from tests.test_bw_sync_lost_parts import copy_of, raw
from tests.test_sync_rebrickable_page import apply_run, choose, connected, db_of, pair, remote, soup, start  # noqa: F401

KEY = lost_parts_send.row_key('1000-1', '3001', 4, False)


def owing(pair, remote):  # noqa: F811
    with db_of(pair) as db:
        copy_of(db, '1000-1', marks=[('3001', '4', 3)])
    remote.lists[1] = {'1000-1': 1}
    remote.lost = [raw('1000-1', '3001', 4, 1, number=1)]


def stored_on(db):
    """The setting as a version before the lock could leave it."""
    db.execute("INSERT OR REPLACE INTO setting(key,value) VALUES(?, 'on')", (lost_parts_send.KEY,))
    db.commit()


def test_the_send_is_locked():
    assert lost_parts_send.SEND_LOCKED is True


def test_the_page_offers_no_way_out_and_refuses_a_stale_form(client, remote, pair):  # noqa: F811
    csrf = connected(client, pair)
    choose(client, csrf)
    page = soup(client.get('/workbench/sync/rebrickable/choose'))
    assert [i['value'] for i in page.select('[data-rb-lost] input[name=lost_dir]')] == ['into', 'off']
    assert not page.select('[data-rb-lost] select[name=send_rule]') and 'sends the parts you find' not in page.get_text()
    for direction in ('to', 'both'):
        answer = soup(client.get(choose(client, csrf, lost_dir=direction).location))
        assert lost_parts_send.LOCKED_MESSAGE in answer.get_text()
    with db_of(pair) as db:
        assert not lost_parts_send.enabled(db) and sync_run.directions(db)['lost'] in ('into', 'off')


def test_a_direction_stored_as_to_rebrickable_has_no_effect(client, remote, pair):  # noqa: F811
    csrf = connected(client, pair)
    owing(pair, remote)
    with db_of(pair) as db:
        stored_on(db)
        assert not lost_parts_send.enabled(db) and sync_run.directions(db)['lost'] in ('into', 'off')
    run_id = start(client, csrf, lost_dir='off', owned_dir='off', wishlist_dir='off')
    with db_of(pair) as db:
        stored_on(db)
        assert sync_run.load(db, run_id)[0].get('lost_out') is None
    page = soup(client.get(f'/workbench/sync/rebrickable/run/{run_id}/preview'))
    assert not page.select('[data-rb-lost-out]')
    apply_run(client, csrf, run_id, lostsend=[KEY])
    with db_of(pair) as db:
        run_job.drain(db)
    assert remote.lost_writes == []


@pytest.mark.parametrize('how', ['from the page', 'in one call', 'as a queued job'])
def test_a_run_planned_before_the_lock_sends_no_lost_parts(client, remote, pair, monkeypatch, how):  # noqa: F811
    monkeypatch.setattr(lost_parts_send, 'SEND_LOCKED', False)
    csrf = connected(client, pair)
    owing(pair, remote)
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='per_part')
    with db_of(pair) as db:
        assert [r['key'] for r in sync_run.load(db, run_id)[0]['lost_out']['rows'] if r['tickable']] == [KEY]
        if how == 'as a queued job':
            run_job.queue(db, run_id, MultiDict([('lostsend', KEY)]))       # queued by the old version, drained by this one
    monkeypatch.setattr(lost_parts_send, 'SEND_LOCKED', True)
    if how == 'from the page':
        apply_run(client, csrf, run_id, lostsend=[KEY])
    with db_of(pair) as db:
        if how == 'in one call':
            sync_run.apply(db, run_id, MultiDict([('lostsend', KEY)]))
        run_job.drain(db)
        open_steps = db.execute("SELECT s.name, s.state FROM job_step s JOIN job j ON j.id=s.job_id WHERE j.kind='sync_run' AND j.state='done' AND s.state<>'done'").fetchall()
        assert not open_steps, [tuple(r) for r in open_steps]
    assert remote.lost_writes == []


@pytest.mark.parametrize('stop', [False, True])
def test_a_job_paused_on_lost_parts_before_the_lock_ends_without_waiting_ones(client, remote, pair, monkeypatch, stop):  # noqa: F811
    monkeypatch.setattr(lost_parts_send, 'SEND_LOCKED', False)
    csrf = connected(client, pair)
    owing(pair, remote)
    run_id = start(client, csrf, lost_dir='to', owned_dir='off', wishlist_dir='off', send_rule='per_part')
    with db_of(pair) as db:
        job_id = run_job.queue(db, run_id, MultiDict([('lostsend', KEY)]))
        run = sync_run.load(db, run_id)[0]
        run['stages'] = {'lost_out': dict(status='waiting', counts=dict(sent=0, failed=0, waiting=1), message='1 Lost Part waits.')}
        sync._store_plan(db, run)
        db.execute("UPDATE job SET state='waiting_for_budget', retry_at='2026-01-01T00:00:00.000Z' WHERE id=?", (job_id,))
        db.execute("UPDATE job_step SET state='waiting_for_budget' WHERE job_id=?", (job_id,))
        db.commit()
        monkeypatch.setattr(lost_parts_send, 'SEND_LOCKED', True)
        if stop:
            run_job.request_stop(db, run_id)
        run_job.drain(db)
        assert sync_run.load(db, run_id)[0]['stages']['lost_out'] == dict(status='none')
        assert tuple(db.execute('SELECT state, count = total FROM job_step WHERE job_id=?', (job_id,)).fetchone()) == ('done', 1)
    assert remote.lost_writes == []


def test_the_settings_routes_refuse_to_switch_it_on(client, remote, pair):  # noqa: F811
    with db_of(pair) as db:
        with pytest.raises(errors.ValidationFailed, match='not available'):      # the API's PATCH /settings, the CLI and MCP go through here
            admin.patch_settings(db, {'rebrickable_lost_parts_send': True})
        admin.patch_settings(db, {'rebrickable_lost_parts_send': False})
        assert not lost_parts_send.enabled(db)


def test_the_command_line_cannot_switch_it_on(pair, monkeypatch):  # noqa: F811
    from brickwork.web import admin_ops
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    with pytest.raises(ValueError, match='unsupported setting'):
        admin_ops.settings_set(lost_parts_send.KEY, 'true')
    with db_of(pair) as db:
        assert not lost_parts_send.enabled(db)
