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
            # #31: enough invented bins for a second label sheet. No change to the older worlds.
            for n in range(1, 23):
                db.execute('INSERT OR IGNORE INTO storage(id,name,type,created_at) VALUES(?,?,?,?)',
                           (f'label-bin-{n:02d}', f'Box {n:02d}', 'Box', clock.FIXED_NOW.isoformat(timespec='milliseconds').replace('+00:00', 'Z')))
            db.execute("INSERT OR REPLACE INTO setting(key,value) VALUES('labels_address','https://bricks.example')")

            for number in KINDS:
                stock.add_loose(db, item_id=dataset.item_by(db, 'sets', number), quantity=1, condition='used', storage_id='storage-box-5', via='cli')
            item = dataset.item_by(db, 'sets', LISTING_BOX[0])
            base.observation(db, 'bricklink', item, guide='stock', price='128.35', currency='EUR', condition='U', slot='bricklink_used', region='eu',
                             qty=1, sold=0, observed_at='2026-10-10T06:00:00.000Z')
            for number, letter in PINNED:
                db.execute('UPDATE copy SET pinned=1 WHERE id=?', (showcase.uid('copy', number, letter),))
        with transaction(db):
            from .figure_comparisons import seed
            seed(db)
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


class OrderLayer(Layer):
    """The edge layer with Pick a Brick element ids in the catalogue (#54): two parts in three have one, the third has none, so the order list shows
    lines that can go to either source and lines that can only go to BrickLink. The collection rows are the edge world's, unchanged."""

    def after_catalogue(self, catalogue):
        super().after_catalogue(catalogue)
        with closing(sqlite3.connect(catalogue)) as db:
            pairs = db.execute('SELECT DISTINCT item_id, color_id FROM inventory_part ORDER BY item_id, color_id').fetchall()
            db.executemany('INSERT OR IGNORE INTO element(element_id, item_id, color_id) VALUES(?,?,?)',
                           [(str(300000 + 7 * n), item, color) for n, (item, color) in enumerate(pairs) if n % 3 != 2])
            db.commit()


def order_layer(data=dataset.DATA, pictures=True):
    return OrderLayer(showcase.Path(data), pictures)


# #25 slice 2: sets with instruction booklets in each preview state, one set per screen state (design/screens/states.json, section i25).
BOOKLET_SETS = {'99101-1': ('ready', 'ready', 'ready'),             # booklet-thumbnails-ready
                '99102-1': ('pending', 'pending'),                  # ...-pending: the preview worker has not run
                '99103-1': ('ready', 'failed'),                     # ...-failed: the second PDF cannot be rendered
                '99104-1': ('ready',),                              # ...-single: one booklet keeps today's row
                '99105-1': ('ready', 'ready', 'archived')}          # ...-archived: one booklet archived, shown under Show archived


def invented_pdf(label: str, shade: int) -> bytes:
    """A one page PDF of invented bricks and a title; the label makes every file differ (a file is stored under the hash of its bytes)."""
    colours = ((0.79, 0.10, 0.04), (0.95, 0.80, 0.20), (0.10, 0.30, 0.70), (0.20, 0.55, 0.30))
    stream = '0.96 0.95 0.92 rg 0 0 300 400 re f\n'
    for n, (x, y, w) in enumerate(((40, 250, 100), (150, 250, 100), (40, 200, 160), (40, 150, 70))):
        r, g, b = colours[(n + shade) % len(colours)]
        stream += f'{r} {g} {b} rg {x} {y} {w} 40 re f\n'
    stream += f'0.10 0.09 0.09 rg BT /F1 20 Tf 40 340 Td ({label}) Tj ET\n'
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
               f'<< /Length {len(stream)} >>\nstream\n{stream}endstream', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = '%PDF-1.4\n', []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{n} 0 obj\n{body}\nendobj\n'
    table = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n' + ''.join(f'{o:010d} 00000 n \n' for o in offsets)
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n'
    return out.encode('latin-1')


class InstructionLayer(Layer):
    """The edge layer with instruction booklets in every preview state (#25 slice 2), on showcase sets that carry none. The previews are rendered here by the
    app's own job (the ready ones), a corrupt PDF ends as failed, and the pending ones are attached last so no job has run for them when the page is served."""

    def edge(self, db):
        super().edge(db)
        from ..core import admin, instruction_thumbnails
        from ..core.media import media_root
        root = media_root(db)
        pending = []
        for number, kinds in BOOKLET_SETS.items():
            item = dataset.item_by(db, 'sets', number)
            for n, kind in enumerate(kinds, 1):
                label = f'Booklet {n} of {len(kinds)}'
                if kind == 'pending':
                    pending.append((item, label, invented_pdf(f'{number} · {label}', n)))
                    continue
                content = b'%PDF corrupt, not a document' if kind == 'failed' else invented_pdf(f'{number} · {label}', n)
                identifier = admin.attach_instruction(db, root, item, label, content)
                if kind == 'archived':
                    instruction_thumbnails.Thumbnails(db).drain()
                    admin.instruction_archive(db, identifier)
        instruction_thumbnails.Thumbnails(db).drain()
        for item, label, content in pending:
            admin.attach_instruction(db, root, item, label, content)


def instruction_layer(data=dataset.DATA, pictures=True):
    return InstructionLayer(showcase.Path(data), pictures)
