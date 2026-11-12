"""The public demo's world: the invented collection only, as a layer over `dataset`, used by the exported demo (`export.export`) and the site's pictures.

The screen gate's approved baselines are rendered from the plain `dataset` world and must not move, so nothing here touches it: `dataset.build(path)`
without a layer is byte-for-byte what it was. With `layer()` the world is replaced by an invented collection that makes every screen of the app look
lived in: sets over several themes and years (with part lists, minifigures and check state), incomplete copies, loose parts and figures in storage,
gear, books and catalogs, several wishlists with maximum prices, price records and a few orders.

Everything is invented and deterministic (a fixed seed; the ids come from a seeded generator, never from the clock or the system's randomness):
the sets, figures, gear, books and catalogs have generic names under numbers in a range no catalogue uses (99xxx-1, fig-99xxxx), and the shops,
sellers and order numbers are made up. Nothing of the design test data's real-named catalogue is shown: its sets, figures and wishes are left out
whole, and of its inventories only generic parts and colours are used (see LICENCED and `generic` below for the rule). Pictures are the original
illustrations of design/demo-art/ (scripts/demo_art.py), stored as ordinary pictures with the source "Demo illustration".
"""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import random
import re
import struct
import sqlite3
import uuid

from ..core import items, orders, stock
from ..core.transaction import transaction
from . import clock, dataset

ART = Path(__file__).resolve().parents[2] / 'design' / 'demo-art'
SOURCE = 'demo_illustration'
SEED = 20261012
NAMESPACE = uuid.UUID('6f1c7a52-0a54-4d5d-9b52-2f6b1c0d5e11')


def uid(*parts):
    return str(uuid.uuid5(NAMESPACE, '/'.join(str(p) for p in parts)))


# (number, name, year, theme path, theme id, rows, figures)
SETS = [
    ('99101-1', 'Harbour Lighthouse', 2009, 'Town / Harbour', 5101, 96, 2),
    ('99102-1', 'Fishing Cutter', 2012, 'Town / Harbour', 5101, 54, 1),
    ('99103-1', 'Coastal Rescue Base', 2015, 'City / Coast Guard', 5102, 124, 3),
    ('99104-1', 'Volcano Survey Camp', 2018, 'City / Volcano', 5103, 138, 3),
    ('99105-1', 'Highway Diner', 2016, 'City / Roads', 5104, 88, 2),
    ('99106-1', 'Fire Brigade Tower', 2014, 'City / Fire', 5105, 112, 3),
    ('99107-1', 'Lunar Rover Garage', 2007, 'Space / Lunar', 5106, 72, 2),
    ('99108-1', 'Starlight Cruiser', 2021, 'Space / Cruisers', 5107, 146, 2),
    ('99109-1', 'Asteroid Miner', 1998, 'Space / Miners', 5108, 41, 1),
    ('99110-1', 'Dragon Keep Gatehouse', 2003, 'Castle / Dragon Keep', 5109, 130, 3),
    ('99111-1', 'Royal Stable', 1991, 'Castle / Royal Court', 5110, 76, 2),
    ('99112-1', 'Mountain Outpost', 2019, 'Castle / Frontier', 5111, 118, 3),
    ('99113-1', 'Crawler Crane', 2017, 'Mechanical / Construction', 5112, 140, 0),
    ('99114-1', 'Rally Buggy', 2020, 'Mechanical / Vehicles', 5113, 66, 1),
    ('99115-1', 'Wind Turbine', 2022, 'Makers / Eco', 5114, 82, 0),
    ('99116-1', 'Seaside Cottage', 2011, 'Makers / Houses', 5115, 104, 2),
    ('99117-1', 'Night Express', 2013, 'Trains / Night Express', 5116, 150, 2),
    ('99118-1', 'Pirate Cove', 1996, 'Pirates / Cove', 5117, 92, 3),
    ('99119-1', 'Jungle Expedition', 2008, 'Adventure / Jungle', 5118, 78, 3),
    ('99120-1', 'Desert Caravan', 2010, 'Adventure / Desert', 5119, 64, 2),
    ('99121-1', 'Market Square', 1989, 'Town / Market', 5120, 58, 2),
    ('99122-1', 'Old Mill', 2023, 'Makers / Houses', 5115, 120, 2),
]

# Wished sets (no part list: nobody owns them): number, name, year, theme path, theme id, parts
WISH_SETS = [
    ('99201-1', 'Grand Observatory', 2023, 'Makers / Landmarks', 5201, 2310),
    ('99202-1', 'Steam Depot', 2022, 'Trains / Steam Depot', 5202, 1468),
    ('99203-1', 'Frontier Fortress', 2020, 'Castle / Frontier', 5111, 1850),
    ('99204-1', 'Ocean Explorer', 2019, 'Town / Harbour', 5101, 942),
    ('99205-1', 'Skyline Tower', 2021, 'City / Roads', 5104, 1190),
    ('99206-1', 'Moon Base Alpha', 2022, 'Space / Lunar', 5106, 1604),
    ('99207-1', 'Pirate Galleon', 2018, 'Pirates / Cove', 5117, 2294),
    ('99208-1', 'Racing Garage', 2023, 'Mechanical / Vehicles', 5113, 760),
]

# Gear, books and catalogs are catalogue entries with no parts: number, name, year, theme path, theme id
GEAR = [('99501-1', 'Brick Separator Set', 2015), ('99502-1', 'Sorting Tray, Six Wells', 2018), ('99503-1', 'Display Stand, Wall', 2020),
        ('99504-1', 'Baseplate Carry Case', 2017), ('99505-1', 'Desk Lamp, Brick Shaped', 2021)]
BOOKS = [('99601-1', 'The Brick Builder Handbook', 2016), ('99602-1', 'Castles of the Lowlands', 2012), ('99603-1', 'Gears and Mechanisms Explained', 2019),
         ('99604-1', 'Trains and Tracks, a Field Guide', 2014)]
CATALOGS = [('99701-1', 'Annual Product Catalog 1989', 1989), ('99702-1', 'Annual Product Catalog 1996', 1996), ('99703-1', 'Collector Price Guide 2004', 2004)]

FIGURE_NAMES = ['Harbour Master', 'Lighthouse Keeper', 'Deckhand', 'Coast Guard Pilot', 'Rescue Diver', 'Volcanologist', 'Camp Cook', 'Diner Waitress',
                'Short-Order Cook', 'Fire Chief', 'Firefighter', 'Tower Dispatcher', 'Rover Driver', 'Mechanic', 'Cruiser Captain', 'Navigator',
                'Asteroid Miner', 'Dragon Knight', 'Gate Guard', 'Court Jester', 'Stable Hand', 'Scout Archer', 'Outpost Captain', 'Mountain Guide',
                'Crane Operator', 'Rally Driver', 'Cottage Gardener', 'Station Master', 'Night Conductor', 'Pirate Captain', 'Cabin Boy', 'Parrot Keeper',
                'Jungle Explorer', 'Botanist', 'Caravan Trader', 'Desert Guide', 'Market Baker', 'Fishmonger', 'Miller', 'Farmhand', 'Wind Technician',
                'Baker Apprentice', 'Stargazer', 'Lab Assistant', 'Harbour Pilot', 'Net Mender', 'Signal Keeper', 'Cargo Handler', 'Bandit Lookout', 'Squire']

STORAGE = [('Shelf B', 'Shelf'), ('Cabinet A', 'Cabinet'), ('Drawer 3', 'Drawer'), ('Drawer 8', 'Drawer'), ('Drawer 12', 'Drawer'), ('Bag 07', 'Bag'),
           ('Box 5', 'Box'), ('Mechanics bin', 'Bin'), ('Wheels and tyres tray', 'Bin'), ('Study shelf', 'Shelf')]
# Clearly generic names: none is a real shop, store or market.
PLACES = [('Sample Bricks Store', 'BrickLink store'), ('Example Parts Depot', 'BrickLink store'), ('Corner Toy Shop', 'Shop'), ('Village Flea Market', 'Market'),
          ('Demo Brick Outlet', 'BrickLink store'), ('High Street Toys', 'Shop')]
HOMES = {  # a set's place on the shelves, by theme root
    'Town': 'Shelf A2 – Town', 'City': 'Shelf A2 – Town', 'Castle': 'Shelf A1 – Castle', 'Space': 'Display case', 'Mechanical': 'Mechanics crate',
    'Makers': 'Display case', 'Trains': 'Shelf A2 – Town', 'Pirates': 'Shelf A1 – Castle', 'Adventure': 'Kellerregal Ü2'}
OWNERS = ['Alex', 'Sam', 'Shared']
TAGS = {'Castle': ['Castle'], 'Space': ['Display'], 'Makers': ['Display']}
# state per set number: what the owner did with the copy (the second field says whether it has a part list of its own)
STATE = {
    '99101-1': 'complete', '99102-1': 'gaps', '99103-1': 'gaps', '99104-1': 'sealed', '99105-1': 'complete', '99106-1': 'progress', '99107-1': 'gaps',
    '99108-1': 'sealed', '99109-1': 'complete', '99110-1': 'gaps', '99111-1': 'gaps', '99112-1': 'progress', '99113-1': 'unchecked', '99114-1': 'gaps',
    '99115-1': 'complete', '99116-1': 'complete', '99117-1': 'gaps', '99118-1': 'gaps', '99119-1': 'progress', '99120-1': 'unchecked', '99121-1': 'complete',
    '99122-1': 'sealed'}
SECOND_COPIES = {'99102-1': ('built', 'Shelf B'), '99115-1': ('displayed', 'Display case'), '99121-1': ('built', 'Study shelf')}


# The flea-market lot (#200, #201, #202; the tutorial "Which set is this bag from?"): a bag of loose parts bought as one lot. Its part lines come from three
# invented sets by what only that set holds (so set detection ranks them apart), plus one line flagged Sticker that two sets hold together with a sticker sheet.
LOT = uid('lot', 'flea-market-bag')
LOT_NAME = 'Flea market bag'
LOT_SETS = (('99109-1', 16), ('99114-1', 9), ('99111-1', 5))       # the sets the lot's lines come from, and how many unique lines of each
LOT_SHARED = 3                                                    # lines two or three sets hold: they make the list look like a real bag
STICKER_SETS = ('99109-1', '99106-1')                              # the two sets that hold the sticker's part together with a sticker sheet
STICKER_PART = ('2431', 71)                                        # that part (a tile) and its colour: only these two sets hold it
STICKER_SHEETS = (('stk-99001', 'Sticker Sheet, Mining Signs'), ('stk-99002', 'Sticker Sheet, Fire Station Signs'))
# Found in the bulk, not yet filed (the pull list of the lot's best set): how many of the set's lines the person has ticked
PULL_TICKS = 6

# The running checks the exported demo and the pictures show (brickwork/demo/checks.py): copy id: (share of the steps answered, keep the missing counts)
CHECKS = {
    uid('copy', '99120-1', 'a'): (0.0, True),    # started, first part
    uid('copy', '99106-1', 'a'): (0.4, True),    # about 40 % answered, resume
    uid('copy', '99103-1', 'a'): (1.0, True),    # answered to the end, with gaps
    uid('copy', '99101-1', 'a'): (1.0, False),   # answered to the end, nothing missing
}


# The public demo shows only the invented collection. What it may take from the design test data is its generic parts: a catalogue item is
# kept out when its name carries a licensed franchise, a character or a model (the words below), and a part is also kept out when it is a
# printed design (a name with "Print", or a part number with a print code, "pr" and digits), since printed artwork is where licences hide.
# A figure's part keeps its prints (a face is a print) and is tested against the words only. Every fixture set, figure, wish and order of the
# design test data is left out whole: the demo's catalogue, copies, wishes and figures are the invented ones in this file.
LICENCED_WORDS = (r'\bSW\b', 'star wars', 'millennium', 'falcon', 'droid', 'wookiee', 'chewbacca', 'c-3po', 'k-3po', 'han solo', r'\bleia\b', r'\brey\b', r'\bfinn\b',
                  'jedi', 'sith', 'vader', 'clone', 'gwen stacy', 'lavender brown', 'harry potter', 'hogwarts', 'marvel', 'avengers', 'spider', 'batman', r'\bdc\b',
                  'disney', 'mickey', 'ninjago', 'jurassic', 'minecraft', 'mario', 'indiana', 'lord of the rings', 'hobbit', 'ferrari', 'lamborghini', 'porsche',
                  'mclaren', 'bugatti', 'titanic', 'colosseum', 'eiffel', 'lego', 'duplo')
LICENCED = re.compile('|'.join(LICENCED_WORDS), re.I)
PRINTED = re.compile(r'\bprint\b|pr\d{3,}$|pat\d+$', re.I)


def generic(row, figure=False):
    """Whether a design-test-data part line may appear in the demo (the rule above)."""
    if LICENCED.search(row['name']) or LICENCED.search(row['part']):
        return False
    return figure or not (PRINTED.search(row['name']) or PRINTED.search(row['part']))


def parts_pool(data):
    """Part lines of the design test data's inventories that pass `generic`: the parts and colours the invented part lists are drawn from."""
    pool, figure_parts = {}, {}
    for path in sorted((data / 'inventories').glob('*-copy-a.json')):
        inventory = json.loads(path.read_text(encoding='utf-8'))
        for row in inventory['parts']:
            if not row.get('figure') and not row.get('spare') and generic(row):
                pool.setdefault((row['part'], row['color']['id']), row)
        for rows in inventory.get('minifigure_parts', {}).values():
            for row in rows:
                if not row.get('spare') and generic(row, figure=True):
                    figure_parts.setdefault(row['category'], {}).setdefault((row['part'], row['color']['id']), row)
    return [pool[k] for k in sorted(pool)], {c: [v[k] for k in sorted(v)] for c, v in sorted(figure_parts.items())}


def line(row, quantity, **marks):
    return {'figure': None, 'part': row['part'], 'name': row['name'], 'category': row['category'], 'color': row['color'], 'quantity': quantity,
            'spare': False, 'element': row.get('element'), 'print': row.get('print', False), 'checked': 0, 'missing': 0, 'damaged': 0, **marks}


def figure_rows(rng, figure_parts, number):
    """The part lines of one invented figure: head, torso, legs and sometimes a hat or an accessory."""
    rows = []
    for category in ('Minifig Heads', 'Minifig Upper Body', 'Minifig Lower Body', 'Minifig Headwear'):
        choices = figure_parts.get(category) or figure_parts.get('FIG ' + category) or []
        if choices and (category != 'Minifig Headwear' or rng.random() < 0.6):
            rows.append(dict(line(rng.choice(choices), 1), figure=number))
    return rows


def mark(rows, rng, state):
    """Check marks on the part lines for the state of a copy; returns (lines checked, pieces missing, pieces damaged)."""
    checked = missing = damaged = 0
    count = len(rows)
    for index, row in enumerate(rows):
        if state in ('complete', 'gaps'):
            row['checked'] = row['quantity']
        elif state == 'progress':
            row['checked'] = row['quantity'] if index < count * 0.45 else 0
        if state == 'gaps' and rng.random() < 0.09:
            row['missing'] = min(row['quantity'], rng.choice([1, 1, 2, 3]))
            row['checked'] = row['quantity'] - row['missing']
        if state in ('gaps', 'complete') and rng.random() < 0.025:
            row['damaged'] = 1
        checked += row['checked'] > 0 and state != 'unchecked' and row['checked'] == row['quantity'] - row['missing']
        missing += row['missing']
        damaged += row['damaged']
    if state == 'gaps' and not missing:
        row = rows[len(rows) // 2]
        row['missing'], row['checked'] = 1, row['quantity'] - 1
        missing = 1
    return checked, missing, damaged


def build_copy(rng, pool, figure_parts, number, name, year, path, theme, rows_n, figures_n, figure_names):
    """The part list (with check state) and the figures of one invented set."""
    state = STATE[number]
    chosen = rng.sample(pool, rows_n)
    lines = [line(row, rng.choice([1, 1, 1, 1, 2, 2, 3, 4, 6, 8])) for row in chosen]
    pieces = sum(r['quantity'] for r in lines)
    figures, figure_lines = [], {}
    for _ in range(figures_n):
        figure_no = 'fig-99%04d' % (len(figure_names) + 1)
        figure_names.append(figure_no)
        rows = figure_rows(rng, figure_parts, figure_no)
        fname = FIGURE_NAMES[(len(figure_names) - 1) % len(FIGURE_NAMES)]
        figures.append({'figure': figure_no, 'name': fname, 'quantity': 1, 'parts': len(rows)})
        figure_lines[figure_no] = rows
    kept = state in ('complete', 'gaps', 'progress')
    checked, missing, damaged = mark(lines, rng, state)
    for rows in figure_lines.values():
        mark(rows, rng, 'complete' if state in ('complete', 'gaps') else state)
    summary = {'rows': len(lines), 'pieces': pieces, 'rows_checked': checked if kept else 0, 'pieces_missing': missing, 'pieces_damaged': damaged,
               'minifigures': figures_n}
    if state == 'complete':
        summary['rows_checked'] = len(lines)
    inventory = {'copy_id': uid('copy', number, 'a'), 'set': number, 'name': name, 'parts': lines, 'minifigures': figures, 'minifigure_parts': figure_lines}
    return inventory, pieces, summary


class Layer:
    """What the richer world adds to the base: catalogue rows, copies (in the shape of the design test data's sets.json), part lists, and a fill step."""

    def __init__(self, data, pictures=True):
        self.pictures = pictures
        self.figure_rows = {}
        rng = random.Random(SEED)
        pool, figure_parts = parts_pool(data)
        self.pool, self.rng = pool, rng
        self.sets, self.catalogue, self.inventories, self.figures = [], [], {}, []
        for number, name, year, path, theme, rows_n, figures_n in SETS:
            inventory, pieces, summary = build_copy(rng, pool, figure_parts, number, name, year, path, theme, rows_n, figures_n, self.figures)
            self.inventories[number] = inventory
            self.catalogue.append(dict(set=number, name=name, year=year, theme_id=theme, theme_path=path, parts=pieces))
            self.sets.append(self.copy(number, name, year, path, theme, pieces, summary, inventory['copy_id'], 0))
            if number in SECOND_COPIES:
                self.sets.append(self.copy(number, name, year, path, theme, pieces, {}, uid('copy', number, 'b'), 1))
        self.add_sticker_sheets()
        used = {}
        for inventory in self.inventories.values():
            for row in inventory['parts']:
                used.setdefault((row['part'], row['color']['id']), row)
        self.stockpool = [used[k] for k in sorted(used)]   # the catalogue holds only the parts some invented set uses: loose stock, wishes and orders draw from those
        for number, name, year, path, theme, pieces in WISH_SETS:
            self.catalogue.append(dict(set=number, name=name, year=year, theme_id=theme, theme_path=path, parts=pieces))
        for number, name, year in GEAR:
            self.catalogue.append(dict(set=number, name=name, year=year, theme_id=501, theme_path='Gear', parts=0))
        for number, name, year in BOOKS:
            self.catalogue.append(dict(set=number, name=name, year=year, theme_id=497, theme_path='Books', parts=0))
        for number, name, year in CATALOGS:
            self.catalogue.append(dict(set=number, name=name, year=year, theme_id=5990, theme_path='Books / Catalogs', parts=0))

    def sticker_line(self):
        """The part line (of the first sticker set's inventory) that is the lot's Sticker line: STICKER_PART, held by exactly the two STICKER_SETS."""
        holders = [n for n, inventory in self.inventories.items() if any((r['part'], r['color']['id']) == STICKER_PART for r in inventory['parts'])]
        if sorted(holders) != sorted(STICKER_SETS):
            raise ValueError('The sticker part must be held by exactly the two sticker sets')
        return next(r for r in self.inventories[STICKER_SETS[0]]['parts'] if (r['part'], r['color']['id']) == STICKER_PART)

    def add_sticker_sheets(self):
        """A sticker sheet (a part of the category `Stickers`, found by that name) in each of the STICKER_SETS' part lists: the catalogue does not say which
        part a sticker goes on, so the lot page offers the sets that hold the flagged part and a sheet. Added after the random draw: nothing else moves."""
        base = self.sticker_line()
        for number, (part, name) in zip(STICKER_SETS, STICKER_SHEETS):
            inventory = self.inventories[number]
            counted = STATE[number] in ('complete', 'gaps')
            inventory['parts'] = [r for r in inventory['parts'] if r['category'] != 'Stickers']      # the drawn-from pool's own sticker sheets carry a real set's name
            sheet = line(dict(part=part, name=name, category='Stickers', color=base['color']), 1, checked=1 if counted else 0)
            inventory['parts'].append(sheet)

    def copy(self, number, name, year, path, theme, pieces, summary, copy_id, nth):
        root = path.split(' / ')[0]
        sealed = STATE[number] == 'sealed' and not nth
        status = ['sealed'] if sealed else (list(SECOND_COPIES[number][0:1]) if nth else
                 {'complete': ['built'], 'gaps': ['built', 'needs-check'], 'progress': ['in-pieces', 'needs-check'], 'unchecked': ['in-pieces']}[STATE[number]])
        index = [s[0] for s in SETS].index(number)
        price = round((pieces * (0.085 + (index % 5) * 0.012)) / 0.5) * 0.5 + 0.99
        return {'id': copy_id, 'set': number, 'name': name, 'year': year, 'theme_id': theme, 'theme_path': path, 'parts': pieces, 'status': status,
                'owners': [OWNERS[(index + nth) % 3]], 'tags': TAGS.get(root, []) + (['Retired'] if year < 2010 else []) + (['Gift'] if index % 7 == 3 else []),
                'storage': SECOND_COPIES[number][1] if nth else ('Box 5' if sealed else HOMES[root]),
                'purchase_location': [p[0] for p in PLACES][(index * 3 + nth) % len(PLACES)] if index % 4 else 'Gift',
                'purchase_date': '%04d-%02d-%02d' % (2022 + (index + nth) % 4 if year > 2005 else 2020 + index % 3, 1 + (index * 5 + nth) % 12, 1 + (index * 7) % 27),
                'purchase_price': None if index % 7 == 3 and not nth else round(price * (0.55 if nth else 1), 2), 'summary': summary}

    # ---------- the catalogue ----------

    def after_catalogue(self, catalogue):
        """The three catalog entries are kept in a book theme in the dump; BrickLink's kind correction (kind_source 'bricklink') makes them catalogs."""
        with closing(sqlite3.connect(catalogue)) as db:
            db.executemany("UPDATE item SET kind='catalog', kind_source='bricklink' WHERE born_namespace='sets' AND born_key=?", [(n,) for n, _, _ in CATALOGS])
            db.commit()

    # ---------- the collection ----------

    def fill(self, db, ids):
        patched = clock.freeze_clock()   # saves made here are stamped with the demo's own "now", not the day it is built
        try:
            with seeded_uuids(self.rng):
                self.storage_and_places(db)
                self.loose_parts(db)
                self.loose_figures(db, ids)
                self.other_kinds(db)
                self.finishing_stock(db)
                self.finished_checks(db)
                self.prices(db)
                self.damaged_prices(db)
                self.missing_figures(db)
                self.wishlists(db)
                self.orders(db)
                self.flea_market(db)
                if self.pictures:
                    self.illustrate(db)
        finally:
            clock.thaw_clock(patched)

    def illustrate(self, db):
        """Own illustrations (design/demo-art/, drawn by scripts/demo_art.py: original artwork, nothing from BrickLink, Rebrickable, Brickset or LEGO)
        stored the way the app stores any picture: a file under data/images/ in the media folder and a `picture` row, source "Demo illustration"."""
        from contextlib import closing as _closing
        import shutil
        from ..core.media import media_root
        manifest = json.loads((ART / 'manifest.json').read_text(encoding='utf-8'))
        folder = media_root(db) / 'data' / 'images'
        folder.mkdir(parents=True, exist_ok=True)
        with transaction(db):
            db.execute("INSERT OR IGNORE INTO source(id, name, kind, enabled) VALUES(?, 'Demo illustration', 'file', 1)", (SOURCE,))
            for row in picture_targets(db):
                file = manifest.get(picture_key(row))
                if file is None:
                    continue
                shutil.copyfile(ART / file, folder / file)
                kind = 'render' if row['kind'] in ('set', 'minifigure', 'gear', 'book', 'catalog') else 'photo'
                width, height = struct.unpack('>II', (ART / file).read_bytes()[16:24])
                db.execute('INSERT OR IGNORE INTO picture(item_id, color_id, source, kind, local_path, url, width, height, fetched_at) VALUES(?, ?, ?, ?, ?, NULL, ?, ?, ?)',
                           (row['item_id'], row['color_id'], SOURCE, kind, 'data/images/' + file, width, height, dataset.STAMP))

    def storage_and_places(self, db):
        with transaction(db):
            for name, kind in STORAGE:
                dataset.put(db, 'storage', 'storage-' + dataset.slug(name), name, type=kind)
                db.execute('UPDATE storage SET type=? WHERE id=? AND type IS NULL', (kind, 'storage-' + dataset.slug(name)))
            for name, kind in PLACES:
                dataset.put(db, 'place', 'place-' + dataset.slug(name), name, kind=kind)
                db.execute('UPDATE place SET kind=? WHERE id=? AND kind IS NULL', (kind, 'place-' + dataset.slug(name)))
            # The shelves nest: boxes and drawers sit in a cabinet or on a shelf.
            for child, parent in (('Bag 07', 'Box 5'), ('Drawer 3', 'Cabinet A'), ('Drawer 8', 'Cabinet A'), ('Drawer 12', 'Cabinet A'),
                                  ('Box 5', 'Shelf B'), ('Mechanics bin', 'Mechanics crate'), ('Wheels and tyres tray', 'Mechanics crate')):
                if parent:
                    db.execute('UPDATE storage SET parent_id=? WHERE id=?', ('storage-' + dataset.slug(parent), 'storage-' + dataset.slug(child)))

    def loose_parts(self, db):
        drawers = ['Drawer 3', 'Drawer 8', 'Drawer 12', 'Bag 07', 'Parts drawer unit', 'Mechanics bin', 'Wheels and tyres tray']
        with transaction(db):
            for row in self.rng.sample(self.stockpool, 90):
                drawer = drawers[(sum(map(ord, row['part'])) + row['color']['id']) % len(drawers)]
                if row['category'].startswith('Technic'):
                    drawer = 'Mechanics bin'
                elif row['category'].startswith('Wheels'):
                    drawer = 'Wheels and tyres tray'
                stock.add_loose(db, item_id=dataset.item_by(db, 'parts', row['part']), color_id=dataset.colour_by(db, row['color']['id']),
                                quantity=self.rng.choice([2, 3, 4, 6, 8, 10, 12, 16, 24, 40]), condition=self.rng.choice(['used', 'used', 'new']),
                                storage_id='storage-' + dataset.slug(drawer), via='cli')

    def loose_figures(self, db, ids):
        places = ['Box 5', 'Drawer 3', 'Display case', 'Box 3']
        with transaction(db):
            for index, figure in enumerate(self.figures[:34:2]):
                stock.add_loose(db, item_id=dataset.item_by(db, 'minifigs', figure), quantity=1 + index % 3, condition='used',
                                storage_id='storage-' + dataset.slug(places[index % len(places)]), via='cli')

    def finishing_stock(self, db):
        """Loose parts that finish three of the incomplete copies (the Matchmaker offers them as complete-able) and half-finish a third."""
        wanted = {'99102-1': 1.0, '99114-1': 1.0, '99105-1': 1.0, '99107-1': 0.5}
        with transaction(db):
            for number, share in wanted.items():
                rows = [r for r in self.inventories[number]['parts'] if r['missing'] or r['damaged']]
                for row in rows[:max(1, round(len(rows) * share))]:
                    stock.add_loose(db, item_id=dataset.item_by(db, 'parts', row['part']), color_id=dataset.colour_by(db, row['color']['id']),
                                    quantity=row['missing'] + row['damaged'], condition='used', storage_id='storage-drawer-8', via='cli')

    def finished_checks(self, db):
        """The three copies the loose stock can finish have a finished check behind them (the status 'Set is checked', completeness worked out by the
        app), as Set Inspector leaves a copy; the Matchmaker counts only such copies as ones that can become complete."""
        with transaction(db):
            flag = dataset.put(db, 'flag', 'status-set-is-checked', 'Set is checked', kind='status', shown_on_grid=0)
            for number in ('99102-1', '99114-1', '99105-1'):
                copy = next(c for c in self.sets if c['set'] == number and c['summary'])
                db.execute('INSERT OR IGNORE INTO copy_flag(copy_id, flag_id) VALUES(?, ?)', (copy['id'], flag))
                db.execute("UPDATE copy SET completeness='incomplete', completeness_source='derived' WHERE id=?", (copy['id'],))

    def other_kinds(self, db):
        homes = {'gear': ['Study shelf', 'Cabinet A', 'Study shelf', 'Display case', 'Study shelf'], 'book': ['Study shelf'] * 4, 'catalog': ['Kellerregal Ü2'] * 3}
        with transaction(db):
            for kind, rows in (('gear', GEAR), ('book', BOOKS), ('catalog', CATALOGS)):
                for index, (number, _, _) in enumerate(rows):
                    stock.add_loose(db, item_id=dataset.item_by(db, 'sets', number), quantity=1 + (index == 0 and kind == 'gear') * 2,
                                    condition='used' if kind != 'gear' else 'new', storage_id='storage-' + dataset.slug(homes[kind][index]), via='cli')

    def prices(self, db):
        """A new and a used value for every owned invented set, and a history for a few, so Prices, Wishlist and the item pages have numbers."""
        with transaction(db):
            for index, number in enumerate(c['set'] for c in self.catalogue if c['parts'] and c['set'] in self.inventories):
                copy = next(c for c in self.sets if c['set'] == number)
                item = dataset.item_by(db, 'sets', number)
                base = copy['parts'] * (0.11 + (index % 6) * 0.012)
                dataset.price(db, item, None, 'N', round(base * 1.25, 2), 14 + index % 9, '2026-10-12T06:00:00.000Z', low=round(base * 1.05, 2), high=round(base * 1.5, 2))
                dataset.price(db, item, None, 'U', round(base * 0.82, 2), 22 + index % 17, '2026-10-12T06:00:00.000Z', low=round(base * 0.6, 2), high=round(base * 1.1, 2))
                for month in range(6):
                    dataset.price(db, item, None, 'U', round(base * (0.8 + 0.01 * ((month * 3 + index) % 7)), 2), None,
                                  '2026-%02d-14T06:00:00.000Z' % (4 + month), current=False)

    def damaged_prices(self, db):
        """A used price for each damaged part that is not also missing (the base world prices the missing ones), so a repair can be costed."""
        with transaction(db):
            for number, inventory in self.inventories.items():
                for row in inventory['parts']:
                    if row['damaged'] and not row['missing']:
                        dataset.price(db, dataset.item_by(db, 'parts', row['part']), dataset.colour_by(db, row['color']['id']), 'U',
                                      round(0.05 + 0.02 * (len(row['part']) % 5), 2), 25, dataset.STAMP)

    def missing_figures(self, db):
        """A figure missing from three of the incomplete copies."""
        with transaction(db):
            for number in ('99103-1', '99110-1', '99117-1'):
                copy = next(c for c in self.sets if c['set'] == number)
                figure = self.inventories[number]['minifigures'][-1]['figure']
                db.execute('UPDATE copy_figure SET missing=1 WHERE copy_id=? AND item_id=? AND retired_at IS NULL', (copy['id'], dataset.item_by(db, 'minifigs', figure)))

    def wishlists(self, db):
        lists = [('wl-birthday', 'Birthday ideas', 1), ('wl-castle', 'Castle theme', 2), ('wl-parts', 'Parts to buy', 3)]
        with transaction(db):
            for key, name, order in lists:
                db.execute("INSERT OR IGNORE INTO wishlist(id,name,sort,created_at) VALUES(?,?,?,?)", (key, name, order, dataset.STAMP))
            plan = [('wl-birthday', '99201-1', 'new', 199.99, 2310), ('wl-birthday', '99206-1', 'new', 129.0, 1604), ('wl-birthday', '99208-1', 'any', 64.5, 760),
                    ('wl-castle', '99203-1', 'new', 149.99, 1850), ('wl-castle', '99207-1', 'used', 140.0, 2294), ('wl-castle', '99204-1', 'new', 74.0, 942),
                    ('default', '99202-1', 'new', 109.99, 1468), ('default', '99205-1', 'used', 59.0, 1190)]
            for index, (key, number, condition, maximum, pieces) in enumerate(plan):
                item = items.ensure(db, dataset.item_by(db, 'sets', number))
                db.execute('''INSERT INTO wish(id, wishlist_id, kind, item_id, color_id, quantity, condition, max_price, max_price_currency, added_at, updated_at)
                              VALUES(?, ?, 'set', ?, NULL, 1, ?, ?, 'EUR', ?, ?)''', ('wish-' + dataset.slug(number), key, item, condition, f'{maximum:.2f}', dataset.STAMP, dataset.STAMP))
                base = pieces * (0.085 + (index % 4) * 0.01)
                dataset.price(db, item, None, 'N', round(base, 2), 11 + index, '2026-10-12T06:00:00.000Z', low=round(base * 0.88, 2), high=round(base * 1.2, 2))
                dataset.price(db, item, None, 'U', round(base * 0.74, 2), 19 + index * 2, '2026-10-12T06:00:00.000Z', low=round(base * 0.55, 2), high=round(base * 0.95, 2))
                for month in range(10):
                    dataset.price(db, item, None, 'N', round(base * (1.12 - 0.012 * month), 2), None, '2026-%02d-%02dT06:00:00.000Z' % (1 + month, 14), current=False)
            wanted = [('wl-parts', rng_part, qty, price) for rng_part, qty, price in zip(self.rng.sample(self.stockpool, 9), [40, 24, 16, 60, 12, 30, 8, 20, 50],
                                                                                       [0.06, 0.12, 0.2, 0.05, 0.3, 0.1, 0.45, 0.15, 0.04])]
            for index, (key, row, quantity, maximum) in enumerate(wanted):
                part, colour = dataset.item_by(db, 'parts', row['part']), dataset.colour_by(db, row['color']['id'])
                items.ensure(db, part)
                db.execute('''INSERT OR IGNORE INTO wish(id, wishlist_id, kind, item_id, color_id, quantity, condition, max_price, max_price_currency, added_at, updated_at)
                              VALUES(?, ?, 'part', ?, ?, ?, 'new', ?, 'EUR', ?, ?)''', ('wish-part-%d' % index, key, part, colour, quantity, f'{maximum:.2f}', dataset.STAMP, dataset.STAMP))
                dataset.price(db, part, colour, 'N', round(maximum * 0.8, 2), 120 + index * 7, dataset.STAMP)
            for index, figure in enumerate(self.figures[34:38]):
                item = items.ensure(db, dataset.item_by(db, 'minifigs', figure))
                db.execute('''INSERT OR IGNORE INTO wish(id, wishlist_id, kind, item_id, color_id, quantity, condition, max_price, max_price_currency, added_at, updated_at)
                              VALUES(?, 'wl-castle', 'minifigure', ?, NULL, 1, 'any', ?, 'EUR', ?, ?)''', ('wish-figure-%d' % index, item, f'{6 + index * 2.5:.2f}', dataset.STAMP, dataset.STAMP))

    def flea_market(self, db):
        """The Flea market bag: a lot of loose parts the Set detection (#200) ranks against the sets, the Sticker line of the chooser (#201) and the progress of a
        pull list (#202). The lines are the parts that only one of LOT_SETS holds, in full quantity, a few parts several sets hold, and the sticker part; for the
        best set, a few more lines are ticked as found in the bulk."""
        from ..core import pull_list, stickers
        holders = {}
        for number, inventory in self.inventories.items():
            for row in inventory['parts']:
                holders.setdefault((row['part'], row['color']['id']), set()).add(number)
        base = self.sticker_line()
        chosen = []
        for number, count in LOT_SETS:
            own = [r for r in self.inventories[number]['parts'] if holders[(r['part'], r['color']['id'])] == {number} and not r['category'].startswith('Sticker')]
            chosen += own[:count]
        shared = [r for r in self.inventories[LOT_SETS[0][0]]['parts'] if len(holders[(r['part'], r['color']['id'])]) in (2, 3) and r is not base]
        chosen += shared[:LOT_SHARED]
        with transaction(db):
            db.execute('INSERT INTO lot(id, name, note, place_id, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)',
                       (LOT, LOT_NAME, 'One bag, no list', None, dataset.STAMP, dataset.STAMP))
            for row in chosen + [base]:
                made = stock.add_loose(db, item_id=dataset.item_by(db, 'parts', row['part']), color_id=dataset.colour_by(db, row['color']['id']),
                                       quantity=row['quantity'], condition='used', lot_id=LOT, via='cli')
                if row is base:
                    flag, _ = stickers.ensure_flag(db)
                    db.execute('INSERT OR IGNORE INTO stock_flag(stock_id, flag_id) VALUES(?, ?)', (made['id'], flag))
        best = dataset.item_by(db, 'sets', LOT_SETS[0][0])
        ticked = [r for r in self.inventories[LOT_SETS[0][0]]['parts'] if r not in chosen and r is not base and not r['category'].startswith('Sticker')]
        for row in ticked[:PULL_TICKS]:
            pull_list.set_found(db, LOT, best, dataset.item_by(db, 'parts', row['part']), dataset.colour_by(db, row['color']['id']), row['quantity'])

    def orders(self, db):
        """Three orders through the app's own XML import: one received whole, one partly arrived, one still a draft (nothing is allocated)."""
        made = [('Sample Bricks Store', '9900101', '2026-09-28', 'Received', 7, 'all'), ('Example Parts Depot', '9900102', '2026-10-05', 'Shipped', 5, 'part'),
                ('Demo Brick Outlet', '9900103', '2026-10-10', 'Pending', 4, None)]
        order_rng = random.Random(SEED + 1)
        # Only parts the order import can place by BrickLink's numbers (a few parts have no link in the shipped mappings).
        placeable = [r for r in self.stockpool if orders._place(db, 'P', r['part'], bricklink_colour(db, r['color']['id']))[0] is not None]
        for number, (store, bricklink, ordered, status, count, arrived) in enumerate(made):
            rows = order_rng.sample(placeable, count)
            lines = [(row, 6 + index * 5, 'N' if (index + number) % 3 else 'U', 0.04 + 0.03 * ((index * 5 + number) % 6)) for index, row in enumerate(rows)]
            cost = sum(qty * price for _, qty, _, price in lines) + 3.9
            xml = ('<INVENTORY><ORDERDATE>%s</ORDERDATE><STATUS>%s</STATUS><CURRENCY>EUR</CURRENCY><COST>%.2f</COST>' % (ordered, status, cost) + ''.join(
                '<ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>%s</ITEMID><COLOR>%d</COLOR><QTY>%d</QTY><CONDITION>%s</CONDITION><PRICE>%.2f</PRICE></ITEM>'
                % (row['part'], bricklink_colour(db, row['color']['id']), qty, condition, price) for row, qty, condition, price in lines) + '</INVENTORY>')
            result = orders.import_document(db, 'xml', xml, number=bricklink, label=store)
            with transaction(db):
                db.execute('UPDATE purchase_order SET store=?, seller=? WHERE id=?', (store, store, result['order_id']))
            if arrived is None:
                continue
            orders.phase(db, result['order_id'], result['document_id'], 'review')
            orders.phase(db, result['order_id'], result['document_id'], 'save')
            saved = orders.detail(db, result['order_id'])['saved']
            orders.received(db, result['order_id'], {r['id']: r['qty'] for r in (saved if arrived == 'all' else saved[:3])})
            if arrived == 'all':   # put into the drawers, then closed
                orders.allocate(db, result['order_id'], [dict(line_id=r['id'], quantity=r['qty'], target_type='stock', storage_id='storage-drawer-3') for r in saved])
                orders.reconcile(db, result['order_id'])


def bricklink_colour(db, colour):
    """BrickLink's number for a Rebrickable colour number (the catalogue's colour links)."""
    row = db.execute("SELECT l.provider_key FROM catalogue.color c JOIN catalogue.color_link l ON l.color_id = c.id AND l.provider = 'bricklink' WHERE c.born_key = ?", (str(colour),)).fetchone()
    return int(row[0]) if row else int(colour)


@contextmanager
def seeded_uuids(rng):
    """Every uuid4 made inside comes from `rng`, so the ids of loose stock and wishes are the same in every build."""
    real = uuid.uuid4
    uuid.uuid4 = lambda: uuid.UUID(int=rng.getrandbits(128), version=4)
    try:
        yield
    finally:
        uuid.uuid4 = real


def layer(data=dataset.DATA, pictures=True):
    return Layer(Path(data), pictures)


TARGETS = '''
    WITH want(item_id, color_id) AS (
      SELECT item_id, NULL FROM copy WHERE archived_at IS NULL UNION SELECT item_id, color_id FROM stock WHERE archived_at IS NULL
      UNION SELECT item_id, color_id FROM wish WHERE archived_at IS NULL UNION SELECT item_id, color_id FROM order_line WHERE item_id IS NOT NULL
      UNION SELECT item_id, color_id FROM copy_part WHERE retired_at IS NULL
      UNION SELECT item_id, NULL FROM copy_figure WHERE retired_at IS NULL)
    SELECT w.item_id, w.color_id, i.kind, i.born_namespace, i.born_key, i.name, c.born_key AS colour_key, c.rgb AS colour_rgb
    FROM want w JOIN item i ON i.id = w.item_id LEFT JOIN color c ON c.id = w.color_id
    WHERE i.origin = 'catalogue' ORDER BY i.born_namespace, i.born_key, c.born_key'''


def picture_targets(db):
    """Every item (and colour) the built world shows that wants a picture: owned, wished, held loose or ordered, and every part of a copy and every figure."""
    return [dict(r) for r in db.execute(TARGETS)]


def picture_key(row):
    return '/'.join(str(p) for p in (row['born_namespace'], row['born_key'], row['colour_key']) if p is not None)


def missing_pictures():
    """The pictures the world needs that design/demo-art/manifest.json does not list (scripts/demo_art.py draws them)."""
    from ..core.connect import connect
    import tempfile
    manifest = json.loads((ART / 'manifest.json').read_text(encoding='utf-8')) if (ART / 'manifest.json').is_file() else {}
    with tempfile.TemporaryDirectory() as scratch:
        store = Path(scratch) / 'brickwork.db'
        dataset.build(store, layer=layer(pictures=False))
        with closing(connect(store, read_only=True)) as db:
            return sorted({picture_key(r) for r in picture_targets(db)} - manifest.keys())
