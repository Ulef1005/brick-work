"""List cost regressions on the 4.0 store (M.8f, issue #110).

The 3.3 test of the BrickLink name refresh (`names.refresh` over the `bricklink-catalog.db` sidecar) is removed: its premise is gone, since in 4.0
the catalogue holds the names and reconcile writes BrickLink's as `item_property(source='bricklink')` (design 6.6). `core/names.py` itself stays
until M.8j deletes the 3.3 importer that still imports it."""
from contextlib import closing

from brickwork.core import collection
from brickwork.core.connect import connect
from tests.app4 import app4, client, coll, pair, world  # noqa: F401 (fixtures)


def test_deleted_picture_stays_selected_and_image_route_returns_404(coll, world, client, pair):
    with closing(connect(pair)) as db, db:
        identifier = db.execute("INSERT INTO picture(item_id, color_id, source, kind, local_path, fetched_at) "
                                "VALUES(?, ?, 'rebrickable_api', 'render', 'data/images/deleted.png', '2099-01-01')", (world.brick, world.red)).lastrowid
    row = collection.decorate(coll.db, [dict(item_id=world.brick, color_id=world.red)])[0]
    assert row['image'] == identifier                                       # the newest row wins even though its file is gone
    assert client.get('/collection/P').status_code == 200
    assert client.get(f'/manage/images/{identifier}').status_code == 404


def test_the_picture_that_serves_a_colour_is_chosen_by_the_order_then_the_newest(coll, world):
    older = coll.sql("INSERT INTO picture(item_id, color_id, source, kind, local_path, fetched_at) VALUES(?, ?, 'bricklink', 'photo', 'data/images/a.png', '2026-01-01')",
                     (world.brick, world.red)).lastrowid
    dump = coll.sql("INSERT INTO picture(item_id, color_id, source, kind, local_path, fetched_at) VALUES(?, ?, 'rebrickable_dump', 'photo', 'data/images/b.png', '2025-01-01')",
                    (world.brick, world.red)).lastrowid
    colourless = coll.sql("INSERT INTO picture(item_id, color_id, source, kind, local_path, fetched_at) VALUES(?, NULL, 'rebrickable_api', 'render', 'data/images/c.png', '2026-06-01')",
                          (world.brick,)).lastrowid
    pick = lambda: collection.decorate(coll.db, [dict(item_id=world.brick, color_id=world.red)])[0]['image']
    assert pick() == dump                                                   # parts: the dump first, then BrickLink, then the API (design 6.8)
    coll.setting('source_priority', '{"pictures": {"part": ["rebrickable_api", "bricklink"]}}')
    assert pick() == colourless                                             # a picture with no colour serves every colour
    coll.setting('source_priority', '{"pictures": {"part": ["bricklink"]}}')
    assert pick() == older
