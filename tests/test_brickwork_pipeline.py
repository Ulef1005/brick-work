"""The source steps of the import pipeline on the 4.0 store (M.8f, issue #110): `pictures`, `metadata` and `market_price` through their
handlers, with fake transports. Claims, restarts and the local steps are `test_pipeline_jobs.py`'s (M.8c). No network."""
from datetime import datetime, timezone
import json

import pytest

from brickwork.core import drainer, pipeline, source_ops
from brickwork.core.pipeline import Pipeline
from brickwork.core.sources import base
from tests.app4 import coll, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import Pictures, Router, keyed, price_reply, step_handlers, unkeyed

BRICKSET = {'status': 'success', 'matches': 1, 'sets': [{
    'setID': 5001, 'number': '1000', 'numberVariant': 1, 'name': 'Syn Castle Keep', 'year': 1990, 'theme': 'Castle', 'pieces': 438,
    'LEGOCom': {'DE': {'retailPrice': 79.99, 'dateFirstAvailable': '1990-01-01T00:00:00Z', 'dateLastAvailable': '1993-12-31T00:00:00Z'}}}]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    unkeyed(monkeypatch)
    monkeypatch.setattr(base, 'transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))
    monkeypatch.setattr(base.time, 'sleep', lambda _: None)
    monkeypatch.setattr('brickwork.core.sources.images.transport', lambda request: (_ for _ in ()).throw(AssertionError('network forbidden')))


def queue(coll, item, steps=None, **kw):
    coll.db.execute('BEGIN IMMEDIATE')
    job = Pipeline(coll.db).queue_steps(item, steps, via=kw.pop('via', 'app'), **kw)
    coll.db.commit()
    return job


def steps(pl, job):
    return {s['name']: s for s in pl.status(job)['steps']}


def routes(**extra):
    return Router({'/items/SET/1000-1/price': price_reply(), '/items/PART/': price_reply(average='0.4'), 'getSets': BRICKSET, **extra})


def test_every_step_of_a_set_through_its_handlers(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink', 'brickset')
    net, pics = routes(), Pictures()
    pl = Pipeline(coll.db, handlers=step_handlers(http=net, image_http=pics))
    job = queue(coll, world.keep)
    done = pl.run(job)
    got = steps(pl, job)
    assert done['state'] == 'done' and all(s['state'] == 'done' for s in got.values())
    assert [got[n]['source'] for n in ('identity', 'inventory', 'matching', 'pictures', 'metadata', 'market_price')] == \
        ['catalogue', 'catalogue', 'catalogue', 'bricklink', 'brickset', 'bricklink']
    assert pics.asked == ['https://img.bricklink.com/ItemImage/SN/0/1000-1.png']
    assert [r['key'] for r in coll.db.execute("SELECT key FROM source_record WHERE source='bricklink' ORDER BY id")] == ['{"currency_code": "EUR", "guide_type": "sold", "new_or_used": "N", "region": "eu"}',
                                                                                                                            '{"currency_code": "EUR", "guide_type": "sold", "new_or_used": "U", "region": "eu"}']
    assert {r['job_id'] for r in coll.db.execute('SELECT job_id FROM source_record')} == {job}
    prices = [tuple(r) for r in coll.db.execute("SELECT condition, guide, provider_key, job_id FROM price_observation WHERE source='bricklink' AND job_id=? ORDER BY id", (job,))]
    assert prices == [('new', 'sold', 'S:1000-1', job), ('used', 'sold', 'S:1000-1', job)]
    assert coll.db.execute("SELECT value FROM item_property WHERE item_id=? AND key='pieces' AND source='brickset'", (world.keep,)).fetchone()[0] == '438'
    assert coll.db.execute("SELECT price FROM price_observation WHERE guide='retail'").fetchone()[0] == '79.99'
    assert [(r['condition'], r['origin']) for r in coll.db.execute('SELECT condition, origin FROM price_watch WHERE item_id=? ORDER BY condition', (world.keep,))] == [('new', 'owned'), ('used', 'owned')]
    assert coll.db.execute('SELECT count(*) FROM job_call WHERE job_id=? AND step=\'market_price\'', (job,)).fetchone()[0] == 4      # two guide calls and the two finished conditions


def test_a_part_is_priced_in_every_colour_it_is_held_in(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    net = routes()
    pl = Pipeline(coll.db, handlers=step_handlers(http=net, image_http=Pictures()))
    job = queue(coll, world.plate, ['market_price'])
    assert pl.run(job)['state'] == 'done'
    asked = sorted(u.split('/api/store/v1')[1].split('&oauth')[0].split('?')[1].split('&color_id=')[1].split('&')[0] for u in net.urls if 'color_id' in u)
    assert asked == ['1', '1', '5', '5']                                                    # BrickLink's colours for red (5) and white (1), new and used
    keys = {r[0] for r in coll.db.execute("SELECT provider_key FROM price_observation WHERE item_id=?", (world.plate,)) if r[0]}
    assert keys == {'P:3023/5', 'P:3023/1'}


def test_an_item_with_no_brickLink_number_ends_unidentified_and_calls_nothing(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink', 'brickset')
    net = routes()
    pl = Pipeline(coll.db, handlers=step_handlers(http=net, image_http=Pictures()))
    job = queue(coll, world.mystery, ['market_price', 'pictures'])
    done = pl.run(job)
    got = steps(pl, job)
    assert done['state'] == 'done' and all((s['state'], s['error_code']) == ('done', 'unidentified') for s in got.values())
    nameless = queue(coll, coll.local('set', 'A set nobody can name'), ['metadata'])           # Brickset cannot be asked for a set with no number
    pl.run(nameless)
    assert (steps(pl, nameless)['metadata']['state'], steps(pl, nameless)['metadata']['error_code']) == ('done', 'unidentified')
    assert net.requests == [] and coll.db.execute('SELECT count(*) FROM price_observation WHERE item_id=?', (world.mystery,)).fetchone()[0] == 0


def test_a_local_brickLink_born_part_is_priced_by_its_own_number(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    net = routes()
    pl = Pipeline(coll.db, handlers=step_handlers(http=net, image_http=Pictures()))
    assert pl.run(queue(coll, world.local_part, ['market_price']))['state'] == 'done'
    assert any('/items/PART/x999/price' in u for u in net.urls)


def test_a_set_brickset_does_not_know_is_a_finding_not_a_failure(coll, world, monkeypatch):
    keyed(monkeypatch, 'brickset')
    pl = Pipeline(coll.db, handlers=step_handlers(http=Router({'getSets': {'status': 'success', 'matches': 0, 'sets': []}})))
    job = queue(coll, world.keep, ['metadata'])
    done = pl.run(job)
    metadata = steps(pl, job)['metadata']
    assert (done['state'], metadata['state'], metadata['error_code']) == ('done', 'done', 'not_found')
    assert [tuple(r) for r in coll.db.execute('SELECT provider, status, reason FROM item_provider_status WHERE item_id=?', (world.keep,))] == [('brickset', 'unmatched', 'no_match')]


def test_metadata_has_no_source_for_a_part_and_the_step_says_so(coll, world):
    pl = Pipeline(coll.db, handlers=step_handlers())
    job = queue(coll, world.brick, ['metadata'])
    pl.run(job)
    metadata = steps(pl, job)['metadata']
    assert (metadata['state'], metadata['source'], metadata['count']) == ('done', None, 0) and 'no source is set' in metadata['error']


def test_missing_keys_fail_the_steps_that_need_them_and_retry_runs_only_those(coll, world, monkeypatch):
    net, pics = routes(), Pictures()
    pl = Pipeline(coll.db, handlers=step_handlers(http=net, image_http=pics))
    job = queue(coll, world.keep, ['pictures', 'metadata', 'market_price'])
    failed = pl.run(job)
    got = steps(pl, job)
    assert failed['state'] == 'failed' and failed['error_code'] == 'source_not_configured'
    assert (got['pictures']['state'], got['metadata']['state'], got['market_price']['state']) == ('done', 'failed', 'failed')     # pictures need no key
    assert got['metadata']['error_code'] == got['market_price']['error_code'] == 'source_not_configured' and 'key' in got['metadata']['error']
    assert net.requests == [] and len(pics.asked) == 1
    keyed(monkeypatch, 'bricklink', 'brickset')
    done = pl.retry(job)
    got = steps(pl, job)
    assert done['state'] == 'done' and all(s['state'] == 'done' for s in got.values())
    assert len(pics.asked) == 1                                                       # the finished step was not run again
    assert coll.db.execute('SELECT attempts FROM job WHERE id=?', (job,)).fetchone()[0] == 2


def test_a_failed_step_does_not_stop_the_others_and_names_its_reason(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    pics = Pictures(default=OSError('connection reset'))
    pl = Pipeline(coll.db, handlers=step_handlers(http=routes(), image_http=pics))
    job = queue(coll, world.keep, ['pictures', 'market_price'])
    done = pl.run(job)
    got = steps(pl, job)
    assert done['state'] == 'failed' and (got['pictures']['state'], got['pictures']['error_code']) == ('failed', 'source_error')
    assert got['pictures']['source'] == 'bricklink' and got['pictures']['error'] == 'bricklink image could not be downloaded'
    assert got['market_price']['state'] == 'done' and coll.db.execute('SELECT count(*) FROM price_observation WHERE job_id=?', (job,)).fetchone()[0] == 2


def test_a_budget_wait_resumes_without_repeating_a_price_that_landed(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    net = routes()
    pl = Pipeline(coll.db, handlers=step_handlers(http=net, image_http=Pictures()))
    job = queue(coll, world.keep, ['market_price'])
    waiting = pl.run(job)
    step = steps(pl, job)['market_price']
    assert (waiting['state'], step['state'], step['error_code']) == ('waiting_for_budget', 'waiting_for_budget', 'budget')
    assert waiting['retry_at'] == step['retry_at'] and waiting['retry_at'].endswith('T00:00:00.000Z') and len(net.requests) == 1
    assert pl.drain() == []                                                           # nothing is due yet
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '5')
    coll.sql("UPDATE job SET retry_at='2000-01-01T00:00:00.000Z'")
    coll.sql("UPDATE job_step SET retry_at='2000-01-01T00:00:00.000Z'")
    coll.sql("UPDATE source_budget SET used=0, blocked_until=NULL, blocked=0")
    done = pl.drain()
    assert [d['state'] for d in done] == ['done'] and len(net.requests) == 2         # only the condition that had not landed was asked
    assert [r[0] for r in coll.db.execute("SELECT condition FROM price_observation WHERE job_id=? ORDER BY id", (job,))] == ['new', 'used']


def test_a_throttle_waits_with_the_time_the_source_named(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    net = Router({'/price': (429, {'meta': {'code': 429, 'message': 'RATE'}})})
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    job = queue(coll, world.keep, ['market_price'])
    result = pl.run(job)
    assert result['state'] == 'failed' and steps(pl, job)['market_price']['error_code'] == 'source_error'      # BrickLink's own throttle code is an ordinary error


def test_the_drainer_runs_the_registered_handlers_in_the_background(coll, world, pair, monkeypatch):
    keyed(monkeypatch, 'bricklink', 'brickset')
    source_ops.register_handlers(http=routes(), image_http=Pictures())
    job = queue(coll, world.keep)
    assert drainer.pending(coll.db)
    drainer.drain_once(pair)
    assert coll.db.execute('SELECT state FROM job WHERE id=?', (job,)).fetchone()[0] == 'done'
    assert coll.db.execute('SELECT count(*) FROM picture WHERE item_id=?', (world.keep,)).fetchone()[0] == 1
    assert not drainer.pending(coll.db)


def test_without_a_worker_the_source_steps_are_skipped_and_say_so(coll, world):
    pl = Pipeline(coll.db)
    job = queue(coll, world.keep, ['pictures', 'market_price'])
    assert pl.run(job)['state'] == 'done'
    assert all(s['state'] == 'done' and s['error'] == pipeline.SKIPPED and s['source'] is None for s in steps(pl, job).values())


def test_the_audit_origin_of_the_job_is_kept_on_what_a_step_writes(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    pl = Pipeline(coll.db, handlers=step_handlers(http=routes(), image_http=Pictures()))
    job = queue(coll, world.keep, ['pictures'], via='cli')
    pl.run(job)
    assert coll.db.execute("SELECT via FROM event WHERE entity_kind='picture'").fetchone()[0] == 'cli'


def test_a_colour_without_a_brickLink_colour_number_is_never_priced_unfiltered(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    coll.project(world.plate)
    from brickwork.store4 import identity
    identity.project_color(coll.db, world.red)
    coll.sql("DELETE FROM color_link WHERE color_id=? AND provider='bricklink'", (world.red,))
    from brickwork.core import items
    from brickwork.core.sources.bricklink import BrickLink
    net = routes()
    with pytest.raises(items.Unidentified, match='no BrickLink colour number'):
        BrickLink(coll.db, http=net).price(world.plate, world.red, 'used')
    assert net.requests == []
    pl = Pipeline(coll.db, handlers=step_handlers(http=net, image_http=Pictures()))
    job = queue(coll, world.plate, ['market_price'])
    pl.run(job)
    step = steps(pl, job)['market_price']
    assert (step['state'], step['error_code']) == ('done', 'unidentified') and 'colour' in step['error']
    assert all('color_id=5' not in u for u in net.urls) and len(net.requests) == 2                  # white (BrickLink 1) was priced, new and used
    assert {r[0] for r in coll.db.execute('SELECT color_id FROM price_observation WHERE job_id=?', (job,))} == {7}


def test_each_guide_call_is_its_own_checkpoint_so_a_one_call_budget_still_finishes(coll, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    monkeypatch.setenv('BW_BRICKLINK_DAILY_BUDGET', '1')
    net = Router({'guide_type=sold': price_reply(quantity=0), 'guide_type=stock': price_reply(quantity=5, average='9', low='8', high='10')})
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    job = queue(coll, world.keep, ['market_price'])
    for day in range(6):                                               # new and used, sold then stock: four calls, one a day
        pl.run(job)
        if pl.status(job)['state'] == 'done':
            break
        coll.sql("UPDATE job SET retry_at='2000-01-01T00:00:00.000Z'")
        coll.sql("UPDATE job_step SET retry_at='2000-01-01T00:00:00.000Z'")
        coll.sql('UPDATE source_budget SET used=0, blocked_until=NULL, blocked=0')
    assert pl.status(job)['state'] == 'done' and day == 3
    assert ['sold' if 'guide_type=sold' in u else 'stock' for u in net.urls] == ['sold', 'stock', 'sold', 'stock']
    assert [tuple(r) for r in coll.db.execute('SELECT condition, guide FROM price_observation WHERE job_id=? ORDER BY id', (job,))] == [
        ('new', 'sold'), ('new', 'stock'), ('used', 'sold'), ('used', 'stock')]


def test_two_colours_that_share_a_brickLink_colour_are_both_priced(coll, world, monkeypatch):
    """Maersk Blue and Pastel Blue are both BrickLink 72: the checkpoint is by the internal colour as well."""
    keyed(monkeypatch, 'bricklink')
    from brickwork.store4 import identity
    for colour in (world.red, 7):
        identity.project_color(coll.db, colour)
    coll.sql("UPDATE color_link SET provider_key='72', inverse_preferred=0 WHERE provider='bricklink' AND color_id IN (?, 7)", (world.red,))
    net = routes()
    pl = Pipeline(coll.db, handlers=step_handlers(http=net))
    job = queue(coll, world.plate, ['market_price'])
    assert pl.run(job)['state'] == 'done' and len(net.requests) == 4
    assert sorted({(r['color_id'], r['provider_key']) for r in coll.db.execute('SELECT color_id, provider_key FROM price_observation WHERE job_id=?', (job,))}) == [
        (world.red, 'P:3023/72'), (7, 'P:3023/72')]
    assert coll.db.execute('SELECT count(*) FROM price_watch WHERE item_id=?', (world.plate,)).fetchone()[0] == 4
