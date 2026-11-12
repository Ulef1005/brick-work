"""The screen gate's `extras` world (#268): the showcase world plus the few things the gate's other worlds do not hold.

The gate's approved baselines are rendered from the plain `dataset` world and must not move, so none of this goes into it, and the showcase
world (the exported demo and the site's pictures) is left as it is too. Only the gate builds this layer (`scripts/screen_gate.py` `world('extras')`),
for the screens that need what is added here:

* an instruction booklet and a box (kinds the demo dataset does not hold), with a price record that is stale, one with a single sale and a
  box that has no price at all (the module states of screen 16);
* a wish whose maximum price is in dollars, while its price is in euros: the verdict is "Not comparable" (screen 46).

Everything is invented and deterministic (its own fixed seed, the demo clock). The numbers sit in a range no catalogue uses (998xx-1)."""
from contextlib import closing
import random
import sqlite3

from ..core import items, stock
from ..core.transaction import transaction
from . import clock, dataset, showcase

SEED = showcase.SEED + 268
BOOKLET = ('99801-1', 'Instructions, Harbour Lighthouse', 2009)
BOX = ('99802-1', 'Box, Harbour Lighthouse', 2009)
BOX_BARE = ('99803-1', 'Box, Fishing Cutter', 2012)
DOLLAR_WISH = ('99209-1', 'Lakeside Pier', 2021, 'Town / Harbour', 5101, 1320)     # wished in dollars (the showcase wishes are all in euros)
KINDS = {BOOKLET[0]: 'instructions', BOX[0]: 'box', BOX_BARE[0]: 'box'}


class Layer(showcase.Layer):
    """The showcase layer with the extra catalogue rows and, after it, the extra collection rows."""

    def __init__(self, data, pictures=True):
        super().__init__(data, pictures)
        for number, name, year in (BOOKLET, BOX, BOX_BARE):
            self.catalogue.append(dict(set=number, name=name, year=year, theme_id=501, theme_path='Gear', parts=0))
        number, name, year, path, theme, pieces = DOLLAR_WISH
        self.catalogue.append(dict(set=number, name=name, year=year, theme_id=theme, theme_path=path, parts=pieces))

    def after_catalogue(self, catalogue):
        super().after_catalogue(catalogue)
        with closing(sqlite3.connect(catalogue)) as db:
            db.executemany("UPDATE item SET kind=?, kind_source='bricklink' WHERE born_namespace='sets' AND born_key=?", [(k, n) for n, k in KINDS.items()])
            db.commit()

    def fill(self, db, ids):
        super().fill(db, ids)
        patched = clock.freeze_clock()
        try:
            with showcase.seeded_uuids(random.Random(SEED)):
                self.extras(db)
        finally:
            clock.thaw_clock(patched)

    def extras(self, db):
        with transaction(db):
            for number, condition in ((BOOKLET[0], 'used'), (BOX[0], 'used'), (BOX_BARE[0], 'used')):
                stock.add_loose(db, item_id=dataset.item_by(db, 'sets', number), quantity=1, condition=condition, storage_id='storage-box-5', via='cli')
            booklet, box = dataset.item_by(db, 'sets', BOOKLET[0]), dataset.item_by(db, 'sets', BOX[0])
            dataset.price(db, booklet, None, 'U', 16.32, 14, '2026-08-12T06:00:00.000Z', low=9.0, high=28.0)      # 61 days before the demo's now: stale
            dataset.price(db, box, None, 'N', 35.95, 1, '2026-10-08T06:00:00.000Z')                                # one sale: thin data
            number, *_ = DOLLAR_WISH
            wish = items.ensure(db, dataset.item_by(db, 'sets', number))
            db.execute('''INSERT INTO wish(id, wishlist_id, kind, item_id, color_id, quantity, condition, max_price, max_price_currency, added_at, updated_at)
                          VALUES('wish-usd-pier', 'wl-birthday', 'set', ?, NULL, 1, 'new', '550.00', 'USD', ?, ?)''', (wish, dataset.STAMP, dataset.STAMP))
            dataset.price(db, wish, None, 'N', 612.0, 9, '2026-10-12T06:00:00.000Z', low=540.0, high=690.0)


def layer(data=dataset.DATA, pictures=True):
    return Layer(showcase.Path(data), pictures)
