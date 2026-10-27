"""Fetch from Rebrickable, the follow-up (M.8f, issue #110; design 6.5, the M.8c note): when the `rebrickable_set` job an Add row queued is
done, the copies (or the wish) that row asked for are made, with their own undoable event; a failed fetch leaves the receipt with nothing to
create and the Add page says so. Invented replies served by a fake transport; no network."""
import json

import pytest

from brickwork.core import add, drainer
from brickwork.store4 import jobs, rebrickable_api
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)
from tests.test_bw_add import confirm, counts, csrf, review, undo  # noqa: F401 (csrf is a fixture)

SET = '99999-9'


def line(num, colour=4, quantity=2):
    return {'id': 1, 'inv_part_id': 1, 'part': {'part_num': num, 'name': f'name {num}', 'part_cat_id': 1},
            'color': {'id': colour, 'name': 'Red', 'rgb': 'C91A09', 'is_trans': False}, 'set_num': SET, 'quantity': quantity,
            'is_spare': False, 'element_id': None, 'num_sets': 1}


class Rebrickable:
    """A fake Rebrickable: the set's record, two part lines of the catalogue, no figures. `status` makes the set record fail."""

    def __init__(self, status=200):
        self.status, self.urls = status, []

    def __call__(self, url, headers):
        self.urls.append(url)
        path = url.split('/api/v3/lego')[1].split('?')[0]
        if path == f'/sets/{SET}/':
            return (200, {'set_num': SET, 'name': 'Fetched Set', 'year': 2026, 'theme_id': 1, 'num_parts': 6}) if self.status == 200 else (self.status, {'detail': 'Not found.'})
        rows = {f'/sets/{SET}/parts/': [line('3001'), line('3023', colour=15, quantity=4)], f'/sets/{SET}/minifigs/': []}[path]
        return 200, {'count': len(rows), 'next': None, 'previous': None, 'results': rows}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(rebrickable_api.KEY_ENV, 'test-key')
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', lambda: None)


def fetch_row(client, csrf, **edits):
    proposal = review(client, csrf, SET).json
    return confirm(client, csrf, proposal, decision='fetch', **edits).json


def copies_of(read, item=None):
    with read() as db:
        return [tuple(r) for r in db.execute("""SELECT c.condition, c.completeness, c.inventory_source, c.note FROM copy c JOIN item i ON i.id=c.item_id
                                               WHERE i.born_key=? AND c.archived_at IS NULL ORDER BY c.created_at""", (SET,))]


def test_a_finished_fetch_makes_the_copies_the_row_asked_for(world, client, csrf, read, pair, monkeypatch):
    net = Rebrickable()
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', net)
    receipt = fetch_row(client, csrf, quantity=2, condition='used', completeness='incomplete', note='From the fetch')['receipts'][0]
    assert receipt['fetch_job'] and receipt['copies'] == [] and copies_of(read) == []
    with read() as db:
        ask = json.loads(db.execute('SELECT new_value FROM event WHERE id=?', (receipt['event_id'],)).fetchone()[0])['ask']
        assert (ask['quantity'], ask['condition'], ask['completeness'], ask['note'], ask['where']) == (2, 'used', 'incomplete', 'From the fetch', 'owned')
        assert add.fetch_outcome(db, receipt['fetch_job'])['state'] == 'waiting' and drainer.pending(db)
    drainer.drain_once(pair)
    assert len(net.urls) == 3                                                       # the set, its parts, its figures: 3 calls, no figure needed more
    assert copies_of(read) == [('used', 'incomplete', 'rebrickable_api', 'From the fetch')] * 2
    with read() as db:
        item = db.execute('SELECT item_id FROM job WHERE id=?', (receipt['fetch_job'],)).fetchone()[0]
        assert db.execute("SELECT origin, kind, born_provider FROM item WHERE id=?", (item,)).fetchone()[:] == ('local', 'set', 'rebrickable')
        fetched = db.execute("SELECT id, new_value FROM event WHERE entity_kind='add' AND field='fetched'").fetchall()
        assert len(fetched) == 1
        made = json.loads(fetched[0]['new_value'])
        assert (made['receipt'], made['fetch_job'], made['item_id'], len(made['copies'])) == (receipt['event_id'], receipt['fetch_job'], item, 2)
        assert db.execute('SELECT count(*) FROM copy_part WHERE copy_id=?', (made['copies'][0],)).fetchone()[0] == 2           # the fetched list's two lines
        assert db.execute("SELECT state FROM job WHERE id=?", (made['job_id'],)).fetchone()[0] == 'queued'                   # the set gets its own import job
        assert add.fetch_outcome(db, receipt['fetch_job']) == dict(state='added', copies=2, message='Fetched · 2 copies added')
        assert not drainer.pending(db) or db.execute("SELECT 1 FROM job WHERE id=? AND state='queued'", (made['job_id'],)).fetchone()
    drainer.drain_once(pair)                                                        # a second pass makes nothing twice and runs the set's job
    assert len(copies_of(read)) == 2
    with read() as db:
        assert db.execute("SELECT count(*) FROM event WHERE entity_kind='add' AND field='fetched'").fetchone()[0] == 1
        assert db.execute('SELECT state FROM job WHERE id=?', (made['job_id'],)).fetchone()[0] == 'done'


def test_the_job_view_says_what_became_of_the_row(world, client, csrf, pair, monkeypatch):
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    receipt = fetch_row(client, csrf, quantity=1)['receipts'][0]
    last = lambda: client.get(f'/manage/add/jobs/{receipt["fetch_job"]}').json['events'][-1]
    assert last()['message'] == 'Import queued'
    drainer.drain_once(pair)
    assert (last()['state'], last()['message']) == ('done', 'Fetched · 1 copy added')


def test_undo_of_the_batch_takes_the_fetched_copies_back_and_nothing_comes_again(world, client, csrf, read, pair, monkeypatch):
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    batch = fetch_row(client, csrf, quantity=2)['batch']
    drainer.drain_once(pair)
    assert len(copies_of(read)) == 2
    assert undo(client, csrf, batch).status_code == 200
    assert copies_of(read) == []
    drainer.drain_once(pair)
    assert copies_of(read) == []
    with read() as db:
        events = [tuple(r) for r in db.execute("SELECT field, id IN (SELECT event_id FROM event_undo) FROM event WHERE entity_kind='add' ORDER BY id")]
    assert events == [('receipt', 1), ('fetched', 1), ('undo', 0), ('undo', 0)]            # the later rows first: each undone once, by its own undo event


def test_a_batch_undone_before_the_fetch_finished_makes_nothing(world, client, csrf, read, pair, monkeypatch):
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    batch = fetch_row(client, csrf, quantity=2)['batch']
    assert undo(client, csrf, batch).status_code == 200
    drainer.drain_once(pair)
    assert copies_of(read) == []
    with read() as db:
        assert db.execute("SELECT count(*) FROM event WHERE entity_kind='add' AND field IN ('fetched', 'fetch_failed')").fetchone()[0] == 0


def test_a_failed_fetch_leaves_the_receipt_with_nothing_to_create_and_a_retry_settles_it(world, client, csrf, read, pair, monkeypatch):
    net = Rebrickable(status=404)
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', net)
    receipt = fetch_row(client, csrf, quantity=1)['receipts'][0]
    drainer.drain_once(pair)
    assert copies_of(read) == []
    with read() as db:
        job = db.execute('SELECT state, error_code FROM job WHERE id=?', (receipt['fetch_job'],)).fetchone()
        assert tuple(job) == ('failed', 'not_found')
        assert add.fetch_outcome(db, receipt['fetch_job']) == dict(state='failed', copies=0, message='Fetch failed · nothing was added')
        assert not add.has_unsettled_fetches(db)
    final = client.get(f'/manage/add/jobs/{receipt["fetch_job"]}').json['events'][-1]
    assert (final['state'], final['message']) == ('failed', 'Fetch failed · nothing was added')
    net.status = 200                                                                 # the set exists after all: Retry queues the same job again
    assert client.post(f'/manage/add/jobs/{receipt["fetch_job"]}/retry', json=dict(csrf_token=csrf)).json == {'message': 'Queued'}
    drainer.drain_once(pair)
    assert len(copies_of(read)) == 1
    with read() as db:
        assert add.fetch_outcome(db, receipt['fetch_job'])['message'] == 'Fetched · 1 copy added'


def test_a_wishlist_row_gets_its_wish_and_undo_archives_it(world, client, csrf, read, pair, monkeypatch):
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    proposal = review(client, csrf, SET, where='wishlist').json
    batch = confirm(client, csrf, proposal, decision='fetch', quantity=3, condition='new').json
    drainer.drain_once(pair)
    with read() as db:
        wish = db.execute("SELECT w.quantity, w.condition, w.wishlist_id, w.archived_at FROM wish w JOIN item i ON i.id=w.item_id WHERE i.born_key=?", (SET,)).fetchone()
        assert tuple(wish) == (3, 'new', 'default', None) and db.execute("SELECT count(*) FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=?", (SET,)).fetchone()[0] == 0
        assert add.fetch_outcome(db, batch['receipts'][0]['fetch_job'])['message'] == 'Fetched · added to the wishlist'
    assert undo(client, csrf, batch['batch']).status_code == 200
    with read() as db:
        assert db.execute("SELECT archived_at IS NOT NULL FROM wish w JOIN item i ON i.id=w.item_id WHERE i.born_key=?", (SET,)).fetchone()[0] == 1


def test_rows_that_cannot_be_made_are_recorded_once_and_not_tried_again(world, client, csrf, read, pair, monkeypatch):
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    receipt = fetch_row(client, csrf, quantity=1)['receipts'][0]
    monkeypatch.setattr(add, '_add_copy', lambda *a, **k: (_ for _ in ()).throw(ValueError('the list was refused')))
    drainer.drain_once(pair)
    with read() as db:
        failed = db.execute("SELECT new_value FROM event WHERE entity_kind='add' AND field='fetch_failed'").fetchall()
        assert len(failed) == 1 and json.loads(failed[0][0])['error'] == 'the list was refused'
        assert add.fetch_outcome(db, receipt['fetch_job'])['state'] == 'refused' and not add.has_unsettled_fetches(db)
        assert db.execute('SELECT count(*) FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=?', (SET,)).fetchone()[0] == 0
    drainer.drain_once(pair)
    with read() as db:
        assert db.execute("SELECT count(*) FROM event WHERE entity_kind='add' AND field='fetch_failed'").fetchone()[0] == 1


def test_a_finished_job_the_process_did_not_settle_is_settled_at_the_next_start(world, client, csrf, read, pair, monkeypatch):
    """The process stops between the job's commit and the settling: the drainer sees the leftover and settles it."""
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    fetch_row(client, csrf, quantity=1)
    from contextlib import closing
    from brickwork.core.connect import connect
    with closing(connect(pair)) as db:
        jobs.drain(db)                                                              # only the fetch runner ran
    with read() as db:
        assert copies_of(read) == [] and add.has_unsettled_fetches(db) and drainer.pending(db)
    drainer.drain_once(pair)
    assert len(copies_of(read)) == 1
    with read() as db:
        assert not add.has_unsettled_fetches(db)


def test_settling_twice_makes_the_copies_once(world, client, csrf, read, pair, monkeypatch):
    """A second worker that listed the receipt before the first settled it finds it settled under the write lock and does nothing."""
    from contextlib import closing
    from brickwork.core.connect import connect
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    fetch_row(client, csrf, quantity=2)
    with closing(connect(pair)) as db:
        jobs.drain(db)
    with closing(connect(pair)) as one, closing(connect(pair)) as two:
        assert len(one.execute(f'SELECT e.id {add.UNSETTLED}').fetchall()) == 1
        real = add.transaction

        def settle_elsewhere_first(database):
            monkeypatch.setattr(add, 'transaction', real)            # the other worker settles after `one` listed, before `one` locks
            assert add.settle_fetches(two) == 1
            return real(database)
        monkeypatch.setattr(add, 'transaction', settle_elsewhere_first)
        assert add.settle_fetches(one) == 0
    assert len(copies_of(read)) == 2


def test_an_undo_committed_after_the_list_was_read_is_honoured(world, client, csrf, read, pair, monkeypatch):
    from contextlib import closing
    from brickwork.core.connect import connect
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    batch = fetch_row(client, csrf, quantity=1)['batch']
    with closing(connect(pair)) as db:
        jobs.drain(db)
        real = add.transaction

        def undo_first(database):
            monkeypatch.setattr(add, 'transaction', real)
            assert undo(client, csrf, batch).status_code == 200
            return real(database)
        monkeypatch.setattr(add, 'transaction', undo_first)
        assert add.settle_fetches(db) == 0
    assert copies_of(read) == []


def test_a_receipt_written_before_follow_ups_is_recorded_once_and_does_not_stop_the_drain(world, client, csrf, read, pair, monkeypatch):
    from contextlib import closing
    from brickwork.core.connect import connect
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    receipt = fetch_row(client, csrf, quantity=1)['receipts'][0]
    with closing(connect(pair)) as db:
        value = json.loads(db.execute('SELECT new_value FROM event WHERE id=?', (receipt['event_id'],)).fetchone()[0])
        del value['ask']
        db.execute('DROP TRIGGER event_no_update')                                    # an old receipt, as the version before this one wrote it
        db.execute('UPDATE event SET new_value=? WHERE id=?', (json.dumps(value), receipt['event_id']))
        db.commit()
    drainer.drain_once(pair)                                                          # no KeyError, no abort
    drainer.drain_once(pair)
    assert copies_of(read) == []
    with read() as db:
        failed = db.execute("SELECT new_value FROM event WHERE entity_kind='add' AND field='fetch_failed'").fetchall()
        assert len(failed) == 1 and 'before fetch follow-ups' in json.loads(failed[0][0])['error']
        assert add.fetch_outcome(db, receipt['fetch_job'])['state'] == 'refused' and not add.has_unsettled_fetches(db)


def test_any_error_while_making_the_rows_is_recorded_not_raised(world, client, csrf, read, pair, monkeypatch):
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', Rebrickable())
    fetch_row(client, csrf, quantity=1)
    monkeypatch.setattr(add, '_add_copy', lambda *a, **k: {}['missing'])
    drainer.drain_once(pair)
    with read() as db:
        assert db.execute("SELECT count(*) FROM event WHERE entity_kind='add' AND field='fetch_failed'").fetchone()[0] == 1
