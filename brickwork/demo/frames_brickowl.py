"""The world `frames-brickowl` (#522): the collection of the Sets frames with a Brick Owl API key and an invented Brick Owl account, for the frames
31, 32 and 71 of design/screens-b. Brick Owl is answered here and never called: three wishlists with the frame's names and numbers of lots, and a
collection that holds what this one holds, except one lot of 7213-1 (two copies here) and one 6542-1, which is only on the wishlist here (the
frame's own second set is not in this catalogue). The run of frame 71 is staged through `core.sync.run.start` and kept under a fixed id, so the page has a fixed path."""
from contextlib import contextmanager
import os
from urllib.parse import parse_qs, urlparse

from . import clock

RUN_ID = '5220' * 8
KEY = {'BW_BRICKOWL_API_KEY': 'invented-brickowl-key'}
WISHLISTS = (('8101', 'Wanted', 8), ('8102', 'Christmas', 3), ('8103', 'Old ideas', 5))
COLLECTION = {'7213-1': 1, '6542-1': 1, '7938-1': 1, '10254-1': 1, '10210-1': 1, '31120-1': 1, '8043-1': 1, '21028-1': 1}


def transport(request):
    url = urlparse(request.full_url)
    path = url.path.removeprefix('/v1/')
    if path == 'wishlist/lists':
        return [dict(wishlist_id=i, name=name, lot_count=str(lots)) for i, name, lots in WISHLISTS]
    if path == 'collection/lots':
        return [dict(lot_id=str(n), boid=f'9{n}', type='Set', qty=str(quantity), ids=[dict(id=number, type='set_number')])
                for n, (number, quantity) in enumerate(COLLECTION.items(), 1)]
    if path == 'wishlist/lots':
        return []
    if path == 'catalog/id_lookup':
        return {'boids': ['9' + parse_qs(url.query)['id'][0].replace('-', '')]}
    if path == 'user/details':
        return {'username': 'invented'}
    raise ValueError('the invented Brick Owl has no ' + path)


@contextmanager
def seams():
    """The invented key and Brick Owl, put back afterwards. The adapter keeps no spacing between its calls here: under the gate's frozen clock no
    time passes, so a spaced call would wait for ever."""
    from ..core.sources import base
    from ..core.sync import adapters
    saved_keys = {k: os.environ.get(k) for k in KEY}
    saved = base.transport, adapters.transport
    spacing = vars(adapters.BrickOwlUser).get('minimum_spacing')
    os.environ.update(KEY)
    base.transport = adapters.transport = transport
    adapters.BrickOwlUser.minimum_spacing = 0
    try:
        yield
    finally:
        base.transport, adapters.transport = saved
        if spacing is None:
            del adapters.BrickOwlUser.minimum_spacing
        else:
            adapters.BrickOwlUser.minimum_spacing = spacing
        for key, value in saved_keys.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def stage(store):
    """Link the first wishlist and stage the run of the pick step, at the demo's own now."""
    from ..core import sync
    from ..core.admin import database
    from ..core.sync import run as sync_run
    patched = clock.freeze_clock()
    try:
        with seams(), database(store) as db:
            sync.link(db, 'brickowl', {'wishlist_id': WISHLISTS[0][0], 'wish_list': 'default'})
            run = sync_run.start(db, source='brickowl')
            sync._store_plan(db, dict(run, id=RUN_ID))
    finally:
        clock.thaw_clock(patched)
