"""The paths that add items without Add's own job queue the `pictures` step (#183): the helper and the order allocation, Part Spotter and
Workbench Found call sites. Sync and the file import from another app are covered in their own test files. Invented data, no network."""
import pytest

from brickwork.core import orders, part_inventory, pictures, pipeline, workbench as w
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)
from tests.test_bw_orders_storage import saved
from tests.test_bw_add import csrf  # noqa: F401 (the Add page's own token fixture)


def live_picture_jobs(db, item_id):
    return db.execute("SELECT j.id, j.payload FROM main.job j JOIN main.job_step s ON s.job_id=j.id WHERE j.kind=? AND j.item_id=? AND s.name='pictures'",
                      (pipeline.KIND, item_id)).fetchall()


def give_picture(coll, item_id, colour=None):
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,?,'bricklink','photo','data/images/x.png','a')", (item_id, colour))


def test_the_helper_queues_only_identified_items_that_miss_a_picture_and_have_no_live_job(world, coll):
    db = coll.db
    give_picture(coll, world.plate)  # a colour-less picture covers every colour
    jobs = pictures.queue_missing(db, [world.brick, world.plate, world.mystery, world.brick])
    assert len(jobs) == 1 and len(live_picture_jobs(db, world.brick)) == 1
    assert not live_picture_jobs(db, world.plate), 'it has its picture'
    assert not live_picture_jobs(db, world.mystery), 'unidentified: no source can name it'
    assert pictures.queue_missing(db, [world.brick]) == [] and len(live_picture_jobs(db, world.brick)) == 1, 'not twice while one is waiting'
    assert pictures.queue_missing(db, []) == []


def test_one_call_is_one_batch_and_a_job_is_only_the_pictures_step(world, coll):
    db = coll.db
    jobs = pictures.queue_missing(db, [world.brick, world.figure])
    batches = {pipeline.Pipeline(db).status(j)['payload'] for j in jobs}
    assert len(jobs) == 2 and len({__import__('json').loads(p)['batch'] for p in batches}) == 1
    assert [s['name'] for s in pipeline.Pipeline(db).status(jobs[0])['steps']] == ['pictures']


def test_a_colour_held_without_a_picture_counts_even_when_another_colour_has_one(world, coll):
    give_picture(coll, world.brick, world.white)
    assert len(pictures.queue_missing(coll.db, [world.brick])) == 1


def allocate(db, world, coll, picture=False):
    oid, did, lid = saved(db)
    orders.received(db, oid, {lid: 3})
    if picture:
        give_picture(coll, world.brick, world.red)
    return oid, lid


def test_an_order_line_placed_into_loose_stock_queues_the_picture(world, coll):
    db = coll.db
    oid, lid = allocate(db, world, coll)
    assert not live_picture_jobs(db, world.brick)
    orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=2)])
    assert len(live_picture_jobs(db, world.brick)) == 1
    orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=1)])
    assert len(live_picture_jobs(db, world.brick)) == 1, 'not twice while one is waiting'


def test_an_order_line_whose_item_has_its_picture_queues_nothing(world, coll):
    db = coll.db
    oid, lid = allocate(db, world, coll, picture=True)
    orders.allocate(db, oid, [dict(line_id=lid, target_type='stock', quantity=3)])
    assert not live_picture_jobs(db, world.brick)


def test_an_order_line_filling_a_copy_gap_queues_nothing(world, coll):
    db = coll.db
    oid, lid = allocate(db, world, coll)
    gap = next(g for g in orders.destinations(db, orders.detail(db, oid)['saved'])[lid] if g['copy_id'] == world.copy_a and g['target'] == 'part')
    orders.allocate(db, oid, [dict(line_id=lid, target_type='copy', copy_id=gap['copy_id'], target='part', target_id=gap['target_id'], quantity=1)])
    assert not live_picture_jobs(db, world.brick)


def piece(world, batch):
    return dict(id='piece-' + batch, candidates=[dict(item_id=world.brick, score=.9)], chosen=dict(item_id=world.brick, color_id=world.red, quantity=2))


def test_part_to_inventory_queues_the_picture(world, coll):
    db = coll.db
    part_inventory.save(db, [piece(world, 'a')], batch='a', keep_photos=False)
    assert len(live_picture_jobs(db, world.brick)) == 1
    part_inventory.save(db, [piece(world, 'b')], batch='b', keep_photos=False)
    assert len(live_picture_jobs(db, world.brick)) == 1, 'not twice while one is waiting'


def test_part_to_inventory_queues_nothing_for_a_part_with_its_picture(world, coll):
    give_picture(coll, world.brick, world.red)
    part_inventory.save(coll.db, [piece(world, 'a')], batch='a', keep_photos=False)
    assert not live_picture_jobs(coll.db, world.brick)


def test_found_into_loose_stock_queues_the_picture_and_the_other_destinations_do_not(world, coll):
    db = coll.db
    w.found(db, world.brick, world.red, 'list', {}, 1)
    assert not live_picture_jobs(db, world.brick)
    w.found(db, world.brick, world.red, 'loose', {}, 1)
    assert len(live_picture_jobs(db, world.brick)) == 1
    w.found(db, world.brick, world.red, 'loose', {}, 1)
    assert len(live_picture_jobs(db, world.brick)) == 1, 'not twice while one is waiting'


def test_found_into_loose_stock_queues_nothing_for_a_part_with_its_picture(world, coll):
    give_picture(coll, world.brick, world.red)
    w.found(coll.db, world.brick, world.red, 'loose', {}, 1)
    assert not live_picture_jobs(coll.db, world.brick)


def test_a_running_picture_step_does_not_block_a_follow_up(world, coll):
    """A running step read its colours when it began, so a colour added meanwhile needs its own job (Codex review)."""
    db = coll.db
    first = pictures.queue_missing(db, [world.brick])
    coll.sql("UPDATE job_step SET state='running' WHERE job_id=? AND name='pictures'", (first[0],))
    coll.sql("UPDATE job SET state='running' WHERE id=?", (first[0],))
    assert len(pictures.queue_missing(db, [world.brick])) == 1 and len(live_picture_jobs(db, world.brick)) == 2


def test_queueing_never_fails_the_write_it_follows(world, coll, monkeypatch, caplog):
    """The write has committed; a queueing failure is logged and returns no jobs (Codex review)."""
    def locked(*a, **k):
        raise __import__('sqlite3').OperationalError('database is locked')
    monkeypatch.setattr(pictures, '_queue_missing', locked)
    with caplog.at_level('WARNING'):
        assert pictures.queue_missing(coll.db, [world.brick]) == []
    assert 'Could not queue pictures' in caplog.text


def copy_lines(db, copy_id):
    return {r[0] for r in db.execute('SELECT item_id FROM copy_part WHERE copy_id=? AND retired_at IS NULL UNION SELECT item_id FROM copy_figure WHERE copy_id=? AND retired_at IS NULL',
                                     (copy_id, copy_id))}


def test_queue_for_copies_queues_the_parts_and_figures_still_without_a_picture(world, coll):
    # #217: a set's parts had no picture after Add until Refresh pictures ran.
    db = coll.db
    lines = copy_lines(db, world.copy_a)
    assert lines
    pictured = sorted(lines)[0]
    give_picture(coll, pictured)
    jobs = pictures.queue_for_copies(db, [world.copy_a, world.copy_a])
    queued = {pipeline.Pipeline(db).status(j)['item_id'] for j in jobs}
    assert pictured not in queued and queued <= lines and queued
    assert pictures.queue_for_copies(db, [world.copy_a]) == [], 'not twice while they wait'
    assert pictures.queue_for_copies(db, []) == []


def test_adding_a_set_queues_its_parts_pictures(world, client, csrf, read):
    from tests.test_bw_add import review
    proposal = review(client, csrf, '1000-1').json
    items = proposal['items']
    items[0].update(decision='another')
    result = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=items))
    assert result.status_code == 200
    copy_id = result.json['receipts'][0]['copies'][0]
    with read() as db:
        lines = copy_lines(db, copy_id)
        waiting = {r[0] for r in db.execute("SELECT DISTINCT j.item_id FROM main.job j JOIN main.job_step s ON s.job_id=j.id WHERE j.kind=? AND s.name='pictures' AND s.state='queued'",
                                            (pipeline.KIND,))}
    assert lines and lines & waiting, 'the new copy\'s parts wait for their pictures'


def test_the_add_review_asks_for_a_picture_with_its_token(world, client, csrf, monkeypatch):
    # #217: POST /manage/add/picture fetches and stores a reviewed item's picture (pictures.preview); the Add token is required.
    asked = []
    monkeypatch.setattr(pictures, 'preview', lambda db, item_id, **kw: asked.append(item_id) or 77)
    assert client.post('/manage/add/picture', json=dict(item_id=world.keep)).status_code == 400          # no token
    reply = client.post('/manage/add/picture', json=dict(csrf_token=csrf, item_id=world.keep))
    assert reply.status_code == 200 and reply.json == {'image': 77} and asked == [world.keep]
    assert client.post('/manage/add/picture', json=dict(csrf_token=csrf, item_id='x')).status_code == 400
    script = (__import__('pathlib').Path(__file__).parents[1] / 'static/web/toni/bw-add.js').read_text()
    assert "api('/picture', {item_id: row.item_id})" in script and 'dataset.pictureFor' in script
