"""Pictures and their source order on the 4.0 store (M.8f, issue #110; design 6.8): the three sources, the fall-through between them, the
Add review's `picture_known`, the bulk refresh and the media route. Invented data, fake transports, no network."""
import json

import pytest

from brickwork.core import items, pictures, pipeline
from brickwork.core.pipeline import Pipeline, StepDone, StepFailed
from brickwork.core.sources import base
from tests.app4 import app4, client, coll, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import Pictures, Router, add_picture_url, keyed, png, step_handlers, unkeyed

ASSET = 'https://cdn.rebrickable.com/media/parts/photos/{}.jpg'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    monkeypatch.setattr('brickwork.core.sources.images.transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))


def queue(coll, item, steps=('pictures',), **kw):
    coll.db.execute('BEGIN IMMEDIATE')
    job = Pipeline(coll.db).queue_steps(item, list(steps), via='app', **kw)
    coll.db.commit()
    return job


def run(coll, item, *, http=None, image_http=None, **kw):
    """One pictures job for the item with fake transports; returns (job status, the step)."""
    pl = Pipeline(coll.db, handlers=step_handlers(http=http, image_http=image_http))
    job = pl.run(queue(coll, item, **kw))
    return job, job['steps'][0]


def job_of(item):
    """The part of a job row `pictures.fetch` reads, for a call outside the pipeline."""
    return {'item_id': item, 'payload': None, 'id': None}


def stored(coll, item):
    return [tuple(r) for r in coll.db.execute('SELECT color_id, source, kind FROM picture WHERE item_id=? ORDER BY color_id, source', (item,))]


# ---------- the order ----------

def test_the_default_order_is_design_6_8s_and_the_setting_overrides_it_per_kind(coll):
    db = coll.db
    assert pictures.order(db, 'part') == ['rebrickable_dump', 'bricklink', 'rebrickable_api']
    assert [pictures.order(db, k) for k in ('set', 'minifigure', 'gear')] == [['bricklink', 'rebrickable_dump']] * 3
    coll.setting('source_priority', json.dumps({'pictures': {'part': ['bricklink:x', 'rebrickable_api', 'bricklink', 'gone'], '*': ['rebrickable_dump']}}))
    assert pictures.order(db, 'part') == ['bricklink', 'rebrickable_api']          # a suffix is dropped, a repeat and an unknown source are ignored
    assert pictures.order(db, 'set') == ['rebrickable_dump']
    coll.setting('source_priority', json.dumps({'metadata': {'set': ['brickset']}}))
    assert pictures.order(db, 'part') == pictures.DEFAULT_ORDER['part']              # a setting without pictures leaves the defaults
    coll.setting('source_priority', 'not json')
    assert pictures.order(db, 'set') == pictures.DEFAULT_ORDER['*']


def test_the_pictures_step_gets_the_order_of_the_kind_when_the_job_is_queued(coll, world):
    pl = Pipeline(coll.db)
    sources = lambda item: json.loads({s['name']: s for s in pl.status(queue(coll, item))['steps']}['pictures']['sources'])
    assert sources(world.brick) == ['rebrickable_dump', 'bricklink', 'rebrickable_api'] and sources(world.keep) == ['bricklink', 'rebrickable_dump']
    assert set(pictures.SOURCES) == {s for (step, s) in pictures.handlers() if step == 'pictures'}


def test_the_colours_of_a_part_are_those_it_is_held_in(coll, world):
    assert pictures.colours_of(coll.db, world.plate) == [world.red, 7]                  # copy lines in red and white... and the stock
    assert pictures.colours_of(coll.db, world.keep) == [None] and pictures.colours_of(coll.db, world.figure) == [None]
    assert pictures.colours_of(coll.db, coll.item('parts', 'dupupn0123')) == [None]                       # a part held in no colour: one colourless picture


# ---------- one source at a time ----------

def test_the_dump_serves_a_colour_it_has_a_url_for(coll, world, pair, tmp_path):
    add_picture_url(pair, world.plate, 7, ASSET.format('plate-white'))
    net = Pictures()
    with pytest.raises(StepFailed):                                         # the other colour has no url: the next source gets a go
        pictures.fetch(coll.db, job_of(world.plate), 'rebrickable_dump', image_http=net)
    assert net.asked == [ASSET.format('plate-white')]
    assert stored(coll, world.plate) == [(7, 'rebrickable_dump', 'photo')]
    row = coll.db.execute('SELECT local_path, url, width, height FROM picture').fetchone()
    assert row['local_path'].startswith('data/images/rebrickable_dump/part/') and (tmp_path / row['local_path']).is_file() and row['url'] == ASSET.format('plate-white')
    assert (row['width'], row['height']) == (8, 6)


def test_bricklink_names_its_image_by_the_resolved_key_and_colour(coll, world):
    net = Pictures()
    pictures.fetch(coll.db, job_of(world.keep), 'bricklink', image_http=net)
    pictures.fetch(coll.db, job_of(world.brick), 'bricklink', image_http=net)
    pictures.fetch(coll.db, job_of(world.figure), 'bricklink', image_http=net)
    assert net.asked == ['https://img.bricklink.com/ItemImage/SN/0/1000-1.png', 'https://img.bricklink.com/ItemImage/PN/5/3001.png',
                         'https://img.bricklink.com/ItemImage/MN/0/syn-fig-0004.png']
    assert stored(coll, world.brick) == [(world.red, 'bricklink', 'photo')] and stored(coll, world.keep) == [(None, 'bricklink', 'photo')]


def test_the_api_asks_for_the_colour_record_and_stores_a_render(coll, world, monkeypatch):
    keyed(monkeypatch, 'rebrickable')
    api = Router({'/parts/3001/colors/4/': {'part_img_url': 'https://cdn.rebrickable.com/media/parts/ldraw/4/3001.png'}})
    net = Pictures()
    pictures.fetch(coll.db, job_of(world.brick), 'rebrickable_api', http=api, image_http=net)
    assert api.urls == ['https://rebrickable.com/api/v3/lego/parts/3001/colors/4/'] and net.asked == ['https://cdn.rebrickable.com/media/parts/ldraw/4/3001.png']
    assert stored(coll, world.brick) == [(world.red, 'rebrickable_api', 'render')]
    assert coll.db.execute("SELECT used FROM source_budget WHERE source='rebrickable'").fetchone()[0] == 1      # the API call is budgeted, the download is not


def test_the_api_asks_sets_and_figures_for_their_own_record_and_a_part_without_colour_for_the_part(coll, world, monkeypatch):
    keyed(monkeypatch, 'rebrickable')
    api = Router({'/sets/1000-1/': {'set_img_url': 'https://cdn.rebrickable.com/media/sets/1000-1.jpg'},
                  '/minifigs/fig-000004/': {'set_img_url': 'https://cdn.rebrickable.com/media/sets/fig.jpg'}})
    pictures.fetch(coll.db, job_of(world.keep), 'rebrickable_api', http=api, image_http=Pictures())
    pictures.fetch(coll.db, job_of(world.figure), 'rebrickable_api', http=api, image_http=Pictures())
    assert api.urls == ['https://rebrickable.com/api/v3/lego/sets/1000-1/', 'https://rebrickable.com/api/v3/lego/minifigs/fig-000004/']
    assert stored(coll, world.keep) == [(None, 'rebrickable_api', 'photo')]


def test_what_a_source_cannot_name_is_a_finding_for_the_next_source(coll, world, monkeypatch):
    # no dump url for 3001 in red; a local BrickLink-born part has no Rebrickable number; no key for the API
    for item, source, message in ((world.brick, 'rebrickable_dump', 'no picture for this colour'), (world.mystery, 'bricklink', 'no number'),
                                  (world.local_part, 'rebrickable_api', 'no Rebrickable number')):
        job = job_of(item)
        with pytest.raises((StepFailed, StepDone)) as caught:
            pictures.fetch(coll.db, job, source, http=Router({}), image_http=Pictures())
        assert message in str(caught.value) or caught.value.code in ('not_found', 'unidentified')
    keyed(monkeypatch, 'rebrickable')
    coll.add_stock('part', coll.item('parts', '3001'), colour=2, quantity=1)
    coll.sql("UPDATE copy_part SET retired_at='a' WHERE item_id=?", (coll.item('parts', '3001'),))
    with pytest.raises(StepFailed) as colour:                                          # an unknown colour has no Rebrickable number either
        pictures.fetch(coll.db, job_of(coll.item('parts', '3001')), 'rebrickable_api', http=Router({}), image_http=Pictures())
    assert colour.value.code == 'not_found'


def test_an_item_with_no_number_ends_unidentified_and_calls_nothing(coll, world):
    net, router = Pictures(), Router({})
    job, step = run(coll, world.mystery, http=router, image_http=net)
    assert (step['state'], step['error_code']) == ('done', 'unidentified') and job['state'] == 'done'
    assert net.asked == [] and router.requests == [] and stored(coll, world.mystery) == []


# ---------- the order in a job ----------

def test_a_colour_without_a_dump_url_falls_through_to_bricklink(coll, world):
    net = Pictures()
    job, step = run(coll, world.brick, image_http=net)                         # 3001 in red: no picture_url, the BrickLink key resolves
    assert (job['state'], step['state'], step['source']) == ('done', 'done', 'bricklink')
    assert net.asked == ['https://img.bricklink.com/ItemImage/PN/5/3001.png'] and stored(coll, world.brick) == [(world.red, 'bricklink', 'photo')]


def test_colours_are_served_by_the_first_source_that_can_each_and_nothing_is_fetched_twice(coll, world, pair):
    add_picture_url(pair, world.plate, 7, ASSET.format('plate-white'))
    net = Pictures()
    job, step = run(coll, world.plate, image_http=net)                         # 3023 held in red and white: white from the dump, red from BrickLink
    assert (step['state'], step['source']) == ('done', 'bricklink')
    assert net.asked == [ASSET.format('plate-white'), 'https://img.bricklink.com/ItemImage/PN/5/3023.png']
    assert stored(coll, world.plate) == [(world.red, 'bricklink', 'photo'), (7, 'rebrickable_dump', 'photo')]
    again, _ = run(coll, world.plate, image_http=net)                          # served colours are left alone
    assert again['state'] == 'done' and len(net.asked) == 2


def test_the_order_decides_which_source_serves_first(coll, world):
    coll.setting('source_priority', json.dumps({'pictures': {'*': ['rebrickable_dump', 'bricklink']}}))
    net = Pictures()
    job, step = run(coll, world.keep, image_http=net)                           # the dump has no set pictures: BrickLink serves
    assert step['source'] == 'bricklink' and stored(coll, world.keep) == [(None, 'bricklink', 'photo')]


def test_when_nothing_served_the_step_fails_with_the_most_telling_error(coll, world):
    coll.sql("DELETE FROM item_link WHERE item_id=? AND provider='bricklink'", (world.brick,))
    job, step = run(coll, world.brick)                                         # no dump url, no BrickLink number, no Rebrickable key: the key is what to fix
    assert job['state'] == 'failed' and step['state'] == 'failed' and step['error_code'] == 'source_not_configured'
    assert 'key' in step['error'] and stored(coll, world.brick) == []


def test_a_failed_download_is_a_source_error_and_keeps_what_is_stored(coll, world):
    run(coll, world.keep, image_http=Pictures())
    before = stored(coll, world.keep)
    job, step = run(coll, world.keep, image_http=Pictures(default=OSError('https://img.bricklink.com/x?oauth_token=synthetic-secret')), refresh=True)
    assert (job['state'], step['state'], step['error_code']) == ('failed', 'failed', 'source_error') and 'synthetic' not in step['error']
    assert stored(coll, world.keep) == before                                  # the earlier picture and its row stay


def test_refresh_downloads_again_and_replaces_the_row(coll, world):
    first = Pictures(default=png('red'))
    run(coll, world.keep, image_http=first)
    path = coll.db.execute('SELECT local_path FROM picture').fetchone()[0]
    run(coll, world.keep, image_http=Pictures(default=png('blue')))               # not asked to refresh: left alone
    assert coll.db.execute('SELECT local_path FROM picture').fetchone()[0] == path
    run(coll, world.keep, image_http=Pictures(default=png('blue')), refresh=True)
    assert coll.db.execute('SELECT count(*), max(local_path) FROM picture').fetchone()[0] == 1 and coll.db.execute('SELECT local_path FROM picture').fetchone()[0] != path


def test_an_api_budget_wait_keeps_the_pictures_already_stored_and_resumes(coll, world, monkeypatch):
    keyed(monkeypatch, 'rebrickable')
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '1')
    coll.setting('source_priority', json.dumps({'pictures': {'part': ['rebrickable_api']}}))
    api = Router({'/parts/3023/colors/4/': {'part_img_url': 'https://cdn.rebrickable.com/media/a.png'},
                  '/parts/3023/colors/15/': {'part_img_url': 'https://cdn.rebrickable.com/media/b.png'}})
    net = Pictures()
    job, step = run(coll, world.plate, http=api, image_http=net)
    assert (job['state'], step['state'], step['error_code']) == ('waiting_for_budget', 'waiting_for_budget', 'budget') and step['retry_at'].endswith('Z')
    assert len(api.requests) == 1 and len(stored(coll, world.plate)) == 1
    coll.sql("UPDATE source_budget SET used=0")                                  # the next day: only the colour still missing is asked
    pl = Pipeline(coll.db, handlers=step_handlers(http=api, image_http=net))
    coll.sql("UPDATE job SET retry_at='2000-01-01T00:00:00.000Z'")
    coll.sql("UPDATE job_step SET retry_at='2000-01-01T00:00:00.000Z'")
    done = pl.run(job['id'])
    assert done['state'] == 'done' and len(api.requests) == 2 and len(stored(coll, world.plate)) == 2


# ---------- picture_known (the Add review's warning) ----------

def test_picture_known_is_true_when_stored_or_some_source_of_the_order_can_serve(coll, world, monkeypatch, pair):
    db = coll.db
    assert pictures.picture_known(db, world.keep) and pictures.picture_known(db, world.brick, world.red)          # BrickLink names both
    assert not pictures.picture_known(db, world.mystery)                                                          # no number, nothing can serve
    coll.sql("DELETE FROM item_link WHERE item_id=? AND provider='bricklink'", (world.brick,))
    assert not pictures.picture_known(db, world.brick, world.red)                                                  # no dump url, no BrickLink key, no Rebrickable key
    keyed(monkeypatch, 'rebrickable')
    assert pictures.picture_known(db, world.brick, world.red)                                                      # the API can ask
    unkeyed(monkeypatch)
    add_picture_url(pair, world.brick, world.red, ASSET.format('brick-red'))
    assert pictures.picture_known(db, world.brick, world.red) and not pictures.picture_known(db, world.brick, 7)
    coll.sql("INSERT INTO picture(item_id, color_id, source, kind, local_path, fetched_at) VALUES(?, NULL, 'bricklink', 'photo', 'data/images/x.png', 'a')", (world.mystery,))
    assert pictures.picture_known(db, world.mystery)                                                               # a colourless picture serves every colour
    coll.setting('source_priority', json.dumps({'pictures': {'part': ['bricklink']}}))
    assert not pictures.picture_known(db, world.brick, world.red)                                                  # only the sources of the order count


# ---------- the bulk refresh ----------

def test_state_counts_what_is_held_and_which_sources_pictured_it(coll, world):
    run(coll, world.keep, image_http=Pictures())
    run(coll, world.brick, image_http=Pictures())
    state = {r['kind']: r for r in pictures.state(coll.db)['summary']}
    assert state['set']['total'] == 3 and state['set']['with_picture'] == 1 and state['set']['missing'] == 2
    assert state['part']['with_picture'] == 1 and state['part']['sources']['bricklink'] == 1 and state['part']['sources']['rebrickable_dump'] == 0
    assert state['gear']['unidentified'] == 1 and state['gear']['total'] == 1 and pictures.state(coll.db)['unidentified'] == 1
    total = sum(r['total'] for r in state.values())
    assert total == coll.db.execute(pictures.HELD + 'SELECT count(*) FROM held').fetchone()[0]


def test_queue_makes_one_job_per_item_and_skips_what_is_pictured_busy_or_unidentified(coll, world):
    run(coll, world.keep, image_http=Pictures())
    selection = pictures.selection(coll.db, 'missing', ['set', 'part', 'minifigure', 'gear'])
    assert world.keep not in selection['item_ids'] and world.mystery not in selection['item_ids'] and selection['unidentified'] == 1
    assert {world.brick, world.plate, world.figure, world.duplo} <= set(selection['item_ids'])
    jobs, count = pictures.queue(coll.db, 'missing', ['part'])
    assert count == len(jobs) == len(pictures.selection(coll.db, 'missing', ['part'])['item_ids'])
    pl = Pipeline(coll.db)
    one = pl.status(jobs[0])
    assert [s['name'] for s in one['steps']] == ['pictures'] and json.loads(one['payload']) == {'steps': ['pictures']}
    again, same = pictures.queue(coll.db, 'missing', ['part'])
    assert again == [] and same == count                                          # the open jobs are not doubled
    everything, _ = pictures.queue(coll.db, 'all', ['set'])
    assert json.loads(pl.status(everything[0])['payload'])['refresh'] is True and world.keep in {pl.status(j)['item_id'] for j in everything}


def test_a_confirmation_with_a_stale_count_is_refused_and_nothing_is_queued(coll, world):
    n = len(pictures.selection(coll.db, 'missing', ['part'])['item_ids'])
    with pytest.raises(ValueError, match='now match'):
        pictures.queue(coll.db, 'missing', ['part'], expected_count=n + 1)
    assert coll.db.execute('SELECT count(*) FROM job').fetchone()[0] == 0
    assert pictures.queue(coll.db, 'missing', ['part'], expected_count=n)[1] == n
    for bad in (('nowhere', ['part']), ('missing', []), ('missing', ['spaceship'])):
        with pytest.raises(ValueError, match='scope and item kinds'):
            pictures.selection(coll.db, *bad)


def test_register_hands_the_pipeline_the_three_picture_handlers(coll):
    saved = dict(pipeline.HANDLERS)
    pictures.register()
    assert {s for (step, s) in pipeline.HANDLERS if step == 'pictures'} == set(pictures.SOURCES)
    pipeline.HANDLERS.clear()
    pipeline.HANDLERS.update(saved)


# ---------- the media route ----------

def test_the_image_route_serves_a_stored_picture_and_404s_the_rest(coll, world, client, app4):
    run(coll, world.keep, image_http=Pictures())
    image = coll.db.execute('SELECT id, local_path FROM picture').fetchone()
    response = client.get(f'/manage/images/{image["id"]}')
    assert response.status_code == 200 and response.data == png()
    assert client.get(f'/manage/images/{image["id"]}?w=320').status_code == 200
    assert client.get('/manage/images/9999').status_code == 404
    page = client.get(f'/collection/item/{world.keep}')
    assert page.status_code == 200 and f'/manage/images/{image["id"]}' in page.get_data(as_text=True)


def test_a_3_3_name_in_the_order_means_the_dump_then_the_api_and_a_missing_source_row_is_made(coll, world, tmp_path):
    coll.setting('source_priority', json.dumps({'pictures': {'part': ['rebrickable', 'bricklink'], '*': ['bricklink', 'rebrickable']}}))
    assert pictures.order(coll.db, 'part') == ['rebrickable_dump', 'rebrickable_api', 'bricklink']
    assert pictures.order(coll.db, 'set') == ['bricklink', 'rebrickable_dump', 'rebrickable_api']
    job = Pipeline(coll.db).status(queue(coll, world.brick))
    assert json.loads({s['name']: s for s in job['steps']}['pictures']['sources']) == ['rebrickable_dump', 'rebrickable_api', 'bricklink']      # the queued job agrees
    coll.sql("DELETE FROM source WHERE id='rebrickable_api'")                         # a 4.0 file made before the seed had it
    from brickwork.core.sources import images
    images.store(coll.db, tmp_path, 'rebrickable_api', world.brick, 'part', png(), color_id=world.red)
    assert [tuple(r) for r in coll.db.execute("SELECT id, name, kind FROM source WHERE id='rebrickable_api'")] == [('rebrickable_api', 'Rebrickable API', 'api')]


def test_a_refresh_waiting_for_budget_resumes_with_the_colours_not_yet_refreshed(coll, world, monkeypatch):
    keyed(monkeypatch, 'rebrickable')
    monkeypatch.setenv('BW_REBRICKABLE_DAILY_BUDGET', '1')
    coll.setting('source_priority', json.dumps({'pictures': {'part': ['rebrickable_api']}}))
    api = Router({'/parts/3023/colors/4/': {'part_img_url': 'https://cdn.rebrickable.com/media/a.png'},
                  '/parts/3023/colors/15/': {'part_img_url': 'https://cdn.rebrickable.com/media/b.png'}})
    net = Pictures()
    for colour in (world.red, 7):                                                  # both colours already have a picture: only a refresh asks again
        coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,?,'rebrickable_api','render','data/images/old.png','a')", (world.plate, colour))
    job, step = run(coll, world.plate, http=api, image_http=net, refresh=True)
    assert step['state'] == 'waiting_for_budget' and len(api.requests) == 1
    coll.sql('UPDATE source_budget SET used=0, blocked_until=NULL')
    coll.sql("UPDATE job SET retry_at='2000-01-01T00:00:00.000Z'")
    coll.sql("UPDATE job_step SET retry_at='2000-01-01T00:00:00.000Z'")
    done = Pipeline(coll.db, handlers=step_handlers(http=api, image_http=net)).run(job['id'])
    assert done['state'] == 'done' and len(api.requests) == 2                      # the second colour, not the first again
    assert len({u for u in api.urls}) == 2 and len(net.asked) == 2


def test_a_suffix_on_a_picture_source_means_nothing_in_the_order_and_in_the_queued_job(coll, world):
    coll.setting('source_priority', json.dumps({'pictures': {'set': ['bricklink:x', 'rebrickable_dump:y']}}))
    assert pictures.order(coll.db, 'set') == ['bricklink', 'rebrickable_dump']
    job = Pipeline(coll.db).status(queue(coll, world.keep))
    assert json.loads({s['name']: s for s in job['steps']}['pictures']['sources']) == ['bricklink', 'rebrickable_dump']
