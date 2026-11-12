"""The screen gate's `edge` worlds (#268, decision 595): invented data for the approved states that were untested for want of data or a seam.

The gate's approved baselines are rendered from the `demo`, `showcase` and `extras` worlds and must not move, so none of this goes into them: the edge
worlds are built from the `extras` layer plus what is added here, and only states that name an `edge` world see any of it
(tests/test_gate_edge_world.py proves the three older worlds' data is unchanged). Added here:

* three sets in the catalogue that nobody owns or wishes for, which the Add page's import progress state adds (screen 20);
* a copy whose part list holds spare lines, with a set check that finished its required parts and said yes to the spare pass (screen 39);
* two incomplete copies that are pinned in Complete sets (screen 44);
* a box with a listings record and no sale, and an instruction booklet with no price record (the "listings only", "loading" and "error" module states of screen 16).

The `edge-value` world (#57) is these plus `ValueLayer`: five existing copies changed so the Value module and Paid vs value show their states (no row is added, so every
count stays); only states that name `edge-value` see it, and the `edge` worlds' approved baselines are rendered from the layer above.

The worlds themselves are named in scripts/screen_gate.py: `edge` (this layer), `edge-read-only` (the same data on an instance switched to
read-only, screen 19) and `edge-empty` (no copy at all, screen 36). Everything is invented and deterministic (its own seed and the demo clock); the
numbers sit in a range no catalogue uses (998xx-1 and up)."""
import random
import sqlite3
from contextlib import closing

import uuid

from ..core import checker, stock
from ..core.sources import base
from ..core.transaction import transaction
from . import clock, dataset, gate_extras, showcase

SEED = gate_extras.SEED + 1
IMPORT_SETS = (('99851-1', "Lighthouse Keeper's Cabin", 2024, 'Town / Harbour', 5101, 212),
               ('99852-1', 'Sample Set', 2023, 'City / Coast Guard', 5102, 148),
               ('99853-1', 'Storm Watch Station', 2024, 'City / Coast Guard', 5102, 176))
SPARE_SET = ('99861-1', 'Signal Tower', 2024, 'Town / Harbour', 5101)
SPARE_COPY = showcase.uid('copy', SPARE_SET[0], 'a')
LISTING_BOX = ('99871-1', 'Box, Pier Cottage', 2013)
BARE_BOOKLET = ('99872-1', 'Instructions, Pier Cottage', 2013)   # no price record at all, and a kind whose Prices module offers Update price (a box's is a link)
KINDS = {LISTING_BOX[0]: 'box', BARE_BOOKLET[0]: 'instructions'}
PINNED = (('99102-1', 'a'), ('99107-1', 'a'))      # incomplete copies of the showcase that the loose stock can finish: they rank in Complete sets
# The photo recognition of Part to Inventory, staged (screen 31): what Brickognize would answer for a photo of a tile with a groove. The gate's world is offline;
# `transport` replaces the network call of the source layer in the edge worlds, so the app's own detect route, mapping and review run on this answer.
RECOGNISED = (('2431', 0.93), ('3710', 0.71), ('3022', 0.42))
KEYS = {'BW_BRICKLINK_CONSUMER_KEY': 'gate-key-consumer', 'BW_BRICKLINK_CONSUMER_SECRET': 'gate-key-consumer-secret',
        'BW_BRICKLINK_TOKEN_VALUE': 'gate-key-token', 'BW_BRICKLINK_TOKEN_SECRET': 'gate-key-token-secret'}   # BrickLink looks configured, so Update price is offered (screen 16); invented, never sent anywhere


def transport(request):
    """The edge worlds' stand-in for the network: only the recognition is answered, with RECOGNISED; any other request is refused, so nothing reaches a server."""
    if not request.full_url.startswith('https://api.brickognize.com/predict/'):
        raise OSError('the gate world is offline')
    return {'items': [{'type': 'part', 'id': number, 'score': score} for number, score in RECOGNISED]}


class Layer(gate_extras.Layer):
    """The extras layer with the catalogue rows and, after it, the collection rows of the edge worlds."""

    def __init__(self, data, pictures=True):
        super().__init__(data, pictures)
        rng = random.Random(SEED)
        for number, name, year, path, theme, pieces in IMPORT_SETS:
            self.catalogue.append(dict(set=number, name=name, year=year, theme_id=theme, theme_path=path, parts=pieces))
        for number, name, year in (LISTING_BOX, BARE_BOOKLET):
            self.catalogue.append(dict(set=number, name=name, year=year, theme_id=501, theme_path='Gear', parts=0))
        self.add_spare_copy(rng)

    def add_spare_copy(self, rng):
        """A copy of an invented set whose part list has spare lines: fourteen required lines and three spare ones (what a kit's extra pieces are)."""
        number, name, year, path, theme = SPARE_SET
        chosen = rng.sample(self.pool, 17)
        lines = [showcase.line(row, rng.choice([1, 1, 2, 3, 4])) for row in chosen[:14]] + [showcase.line(row, rng.choice([1, 2]), spare=True) for row in chosen[14:]]
        pieces = sum(r['quantity'] for r in lines if not r['spare'])
        self.inventories[number] = {'copy_id': SPARE_COPY, 'set': number, 'name': name, 'parts': lines, 'minifigures': [], 'minifigure_parts': {}}
        self.catalogue.append(dict(set=number, name=name, year=year, theme_id=theme, theme_path=path, parts=pieces))
        self.sets.append({'id': SPARE_COPY, 'set': number, 'name': name, 'year': year, 'theme_id': theme, 'theme_path': path, 'parts': pieces,
                          'status': ['in-pieces'], 'owners': ['Alex'], 'tags': [], 'storage': 'Shelf B', 'purchase_location': 'Corner Toy Shop',
                          'purchase_date': '2025-03-08', 'purchase_price': 49.99, 'summary': {}})

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
                self.edge(db)
        finally:
            clock.thaw_clock(patched)

    def edge(self, db):
        with transaction(db):
            for number in KINDS:
                stock.add_loose(db, item_id=dataset.item_by(db, 'sets', number), quantity=1, condition='used', storage_id='storage-box-5', via='cli')
            item = dataset.item_by(db, 'sets', LISTING_BOX[0])
            base.observation(db, 'bricklink', item, guide='stock', price='128.35', currency='EUR', condition='U', slot='bricklink_used', region='eu',
                             qty=1, sold=0, observed_at='2026-10-10T06:00:00.000Z')
            for number, letter in PINNED:
                db.execute('UPDATE copy SET pinned=1 WHERE id=?', (showcase.uid('copy', number, letter),))
        self.spare_check(db)

    def spare_check(self, db):
        """A set check made with the checker's own writes: every required line answered, the spare question answered yes, no spare line answered yet."""
        def call(**payload):
            return checker.write(db, SPARE_COPY, dict(operation=str(uuid.uuid4()), **payload))
        call(action='start', order='inventory')
        state = checker.view(db, SPARE_COPY)
        rows = {r['token']: r for r in state['rows']}
        for token in [t for t in state['session']['order'] if rows[t]['kind'] != 'spare']:
            call(action='answer', session=state['session']['id'], token=token, found=rows[token]['quantity'] or 0)
        call(action='spares', session=state['session']['id'], include=True)


class NoCopies(showcase.Layer):
    """The showcase catalogue and nothing owned: no copy, no stock, no wish (the checker's "no copies" state, screen 36)."""

    def __init__(self, data, pictures=False):
        super().__init__(data, False)
        self.sets, self.inventories = [], {}

    def fill(self, db, ids):
        pass


def layer(data=dataset.DATA, pictures=True):
    return Layer(showcase.Path(data), pictures)


def empty_layer(data=dataset.DATA, pictures=False):
    return NoCopies(showcase.Path(data), pictures)


# The copies and sets `ValueLayer` changes (numbers of the showcase): a copy with your own value, a set with no sale at all, a set whose quote is old, a copy paid in dollars.
OVERRIDE_SET, NO_QUOTE_SET, STALE_SET, DOLLAR_SET = '99101-1', '99112-1', '99103-1', '99105-1'
STALE_AT = '2026-06-01T00:00:00.000Z'    # older than the source's freshness rule at the demo clock (2026-10-12)


class ValueLayer(Layer):
    """The edge layer with the value data of #57: an override, a set with no sale, an old quote and a copy paid in dollars, on copies the showcase already owns."""

    def edge(self, db):
        super().edge(db)
        with transaction(db):
            def first_copy(number):
                return db.execute('SELECT id FROM copy WHERE item_id=? ORDER BY created_at, id LIMIT 1', (dataset.item_by(db, 'sets', number),)).fetchone()[0]
            db.execute("UPDATE copy SET current_value='62.00', current_value_currency='EUR' WHERE id=?", (first_copy(OVERRIDE_SET),))
            quiet = dataset.item_by(db, 'sets', NO_QUOTE_SET)
            db.execute('DELETE FROM price_current WHERE item_id=?', (quiet,))
            db.execute('DELETE FROM price_observation WHERE item_id=?', (quiet,))
            db.execute('UPDATE price_observation SET observed_at=? WHERE item_id=?', (STALE_AT, dataset.item_by(db, 'sets', STALE_SET)))
            db.execute("UPDATE copy SET purchase_price='50.00', purchase_currency='USD' WHERE id=?", (first_copy(DOLLAR_SET),))
            db.execute("INSERT OR REPLACE INTO source_freshness(source, kind, max_age_days) VALUES('bricklink', 'prices', 30)")
            db.execute("INSERT OR REPLACE INTO exchange_rate(currency, per_eur, as_of, source) VALUES('USD', '1.08', '2026-10-09', 'manual')")


def value_layer(data=dataset.DATA, pictures=True):
    return ValueLayer(showcase.Path(data), pictures)
