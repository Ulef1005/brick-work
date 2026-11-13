"""The real-sets demo world: seven real sets with their real part lists and pictures, a collection of invented copies around them (#332).

A layer over `dataset`, like `showcase`, and separate from it: the screen gate's worlds and the showcase's fingerprints do not move, because nothing
here touches them. The world is the seven sets and nothing else that is a set: their numbers, names, years, themes, part lists, minifigures and
part lists of the figures are Rebrickable's (`not-mit/rebrickable/sets.json`, cut by `scripts/extract_rebrickable.py`), and five more real sets are
wished with name, year and part count only. Copies, check state, storage, shops, prices, loose stock, wishes and orders are invented, with a fixed
seed (nothing here reads the clock or the system's randomness).

Pictures are the ones in `not-mit/rebrickable/images/` (`manifest.json` maps a catalogue key such as `sets/31120-1` or `parts/3001/4` to a file).
Every item that has none shows the app's own missing-picture tile. The folder is not MIT: see `not-mit/NOTICE.md`. A build without the folder, or
without its manifest, has no pictures and is otherwise the same.
"""
import itertools
import json
import random
import shutil
import struct
from pathlib import Path

from ..core import items, stock
from ..core.transaction import transaction
from . import clock, dataset, showcase
from .showcase import line, mark, seeded_uuids, uid

FOLDER = Path(__file__).resolve().parents[2] / 'not-mit' / 'rebrickable'
SOURCE = 'rebrickable_images'
SEED = 20261113

# number: (what the owner did with the copy, storage, purchase place, purchase date, owner, tags)
COPIES = {
    '31120-1': ('complete', 'Display case', 'Corner Toy Shop', '2023-05-14', 'Alex', ['Castle', 'Display']),
    '7938-1': ('gaps', 'Shelf B', 'Village Flea Market', '2022-11-26', 'Sam', ['Retired']),
    '8043-1': ('progress', 'Mechanics crate', 'Example Parts Depot', '2024-02-03', 'Alex', []),
    '10210-1': ('gaps', 'Display case', 'High Street Toys', '2021-12-18', 'Shared', ['Display', 'Retired']),
    '7213-1': ('gaps', 'Shelf B', 'Sample Bricks Store', '2023-08-09', 'Sam', ['Retired']),
    '10254-1': ('sealed', 'Box 5', 'Gift', '2024-12-24', 'Shared', ['Gift']),
    '21028-1': ('unchecked', 'Study shelf', 'Demo Brick Outlet', '2025-03-30', 'Alex', ['Display']),
}
SECOND_COPY = {'7213-1': ('built', 'Study shelf')}
STATUS = {'complete': ['built'], 'gaps': ['built', 'needs-check'], 'progress': ['in-pieces', 'needs-check'], 'unchecked': ['in-pieces'], 'sealed': ['sealed']}
CHECKED_SETS = ('7938-1', '10210-1', '7213-1')        # the copies the loose stock can finish: a finished check is behind them
FINISHING = {'7938-1': 1.0, '10210-1': 1.0, '7213-1': 0.5}
STICKER_SETS = ('7938-1', '8043-1', '7213-1')          # the sets that hold a sticker sheet (a part of the category Stickers)
LOT = uid('lot', 'flea-market-bag')
LOT_NAME = 'Flea market bag'
LOT_COUNTS = (16, 9, 5)                                # unique part lines taken from the best, the second and the third candidate set
LOT_SHARED = 3
PULL_TICKS = 6
# Wished sets: list, set number, condition, maximum price
WISHES = [('wl-birthday', '6382-1', 'any', 79.0), ('wl-birthday', '6985-1', 'new', 249.0), ('wl-castle', '6085-1', 'used', 95.0),
          ('wl-castle', '6270-1', 'any', 120.0), ('default', '6542-1', 'used', 140.0)]

# The running checks the exported demo and the pictures show: copy id: (share of the steps answered, keep the missing counts)
CHECKS = {
    uid('copy', '21028-1', 'a'): (0.0, True),   # started, first part
    uid('copy', '8043-1', 'a'): (0.4, True),    # about 40 % answered, resume
    uid('copy', '7938-1', 'a'): (1.0, True),    # answered to the end, with gaps
    uid('copy', '31120-1', 'a'): (1.0, False),  # answered to the end, nothing missing
}


def snapshot(folder=FOLDER):
    return json.loads((Path(folder) / 'sets.json').read_text(encoding='utf-8'))


def pictures_manifest(folder=FOLDER):
    path = Path(folder) / 'images' / 'manifest.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


class Layer(showcase.Layer):
    """The seven sets as copies in the shape of the design test data's sets.json, their inventories with check state, and the fill step.

    It reuses the showcase layer's storage, loose-stock and order steps (which draw from `stockpool`) and replaces everything that names a set."""

    def __init__(self, folder=FOLDER, pictures=True):   # does not call the showcase's __init__: its sets are invented ones
        self.folder, self.pictures = Path(folder), pictures
        rng = self.rng = random.Random(SEED)
        data = snapshot(self.folder)
        self.sets, self.catalogue, self.inventories, self.figures = [], [], {}, []
        for index, entry in enumerate(data['sets']):
            number, state = entry['set'], COPIES[entry['set']][0]
            lines = [dict(r, checked=0, missing=0, damaged=0) for r in entry['parts_list']]
            figure_lines = {fig: [dict(r, checked=0, missing=0, damaged=0) for r in rows] for fig, rows in entry['minifigure_parts'].items()}
            counted = [r for r in lines if not r['spare']]
            checked, missing, damaged = mark(counted, rng, state)
            for rows in figure_lines.values():
                mark([r for r in rows if not r['spare']], rng, 'complete' if state in ('complete', 'gaps') else state)
            pieces = sum(r['quantity'] for r in counted)
            summary = {'rows': len(counted), 'pieces': pieces, 'rows_checked': len(counted) if state == 'complete' else (checked if state in ('gaps', 'progress') else 0),
                       'pieces_missing': missing, 'pieces_damaged': damaged, 'minifigures': len(entry['minifigures'])}
            copy_id = uid('copy', number, 'a')
            self.inventories[number] = {'copy_id': copy_id, 'set': number, 'name': entry['name'], 'parts': lines, 'minifigures': entry['minifigures'],
                                        'minifigure_parts': figure_lines}
            self.figures += [f['figure'] for f in entry['minifigures']]
            self.catalogue.append(dict(set=number, name=entry['name'], year=entry['year'], theme_id=entry['theme_id'], theme_path=entry['theme_path'], parts=entry['parts']))
            self.sets.append(self.copy(entry, index, pieces, summary, copy_id, 0))
            if number in SECOND_COPY:
                self.sets.append(self.copy(entry, index, pieces, {}, uid('copy', number, 'b'), 1))
        for entry in data['wished']:
            self.catalogue.append(dict(set=entry['set'], name=entry['name'], year=entry['year'], theme_id=entry['theme_id'], theme_path=entry['theme_path'], parts=entry['parts']))
        used = {}
        for inventory in self.inventories.values():
            for row in inventory['parts']:
                if not row['spare']:
                    used.setdefault((row['part'], row['color']['id']), row)
        self.stockpool = [used[k] for k in sorted(used)]
        self.wished = {e['set']: e for e in data['wished']}

    def copy(self, entry, index, pieces, summary, copy_id, nth):
        number = entry['set']
        state, storage, place, date, owner, tags = COPIES[number]
        price = round((pieces * (0.085 + (index % 5) * 0.012)) / 0.5) * 0.5 + 0.99
        sealed = state == 'sealed' and not nth
        return {'id': copy_id, 'set': number, 'name': entry['name'], 'year': entry['year'], 'theme_id': entry['theme_id'], 'theme_path': entry['theme_path'],
                'parts': pieces, 'status': list(SECOND_COPY[number][:1]) if nth else STATUS[state], 'owners': [owner], 'tags': [] if nth else tags,
                'storage': SECOND_COPY[number][1] if nth else storage, 'purchase_location': place, 'purchase_date': date,
                'purchase_price': None if place == 'Gift' and not nth else round(price * (0.55 if nth else 1), 2), 'summary': summary,
                'sealed': sealed}

    def after_catalogue(self, catalogue):
        """Nothing to correct: every catalogue entry is a set."""

    # ---------- the collection ----------

    def fill(self, db, ids):
        patched = clock.freeze_clock()   # saves made here are stamped with the demo's own "now", not the day it is built
        try:
            with seeded_uuids(self.rng):
                self.storage_and_places(db)
                self.loose_parts(db)
                self.loose_figures(db, ids)
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

    def loose_figures(self, db, ids):
        places = ['Box 5', 'Drawer 3', 'Display case', 'Box 3']
        with transaction(db):
            for index, figure in enumerate(self.figures[::2]):
                stock.add_loose(db, item_id=dataset.item_by(db, 'minifigs', figure), quantity=1 + index % 3, condition='used',
                                storage_id='storage-' + dataset.slug(places[index % len(places)]), via='cli')

    def finishing_stock(self, db):
        """Loose parts that finish two of the incomplete copies (the Matchmaker offers them as complete-able) and half-finish a third."""
        with transaction(db):
            for number, share in FINISHING.items():
                rows = [r for r in self.inventories[number]['parts'] if r['missing'] or r['damaged']]
                for row in rows[:max(1, round(len(rows) * share))]:
                    stock.add_loose(db, item_id=dataset.item_by(db, 'parts', row['part']), color_id=dataset.colour_by(db, row['color']['id']),
                                    quantity=row['missing'] + row['damaged'], condition='used', storage_id='storage-drawer-8', via='cli')

    def finished_checks(self, db):
        """The copies the loose stock can finish have a finished check behind them (the status 'Set is checked', completeness worked out by the app), as
        Set Inspector leaves a copy; the Matchmaker counts only such copies as ones that can become complete."""
        with transaction(db):
            flag = dataset.put(db, 'flag', 'status-set-is-checked', 'Set is checked', kind='status', shown_on_grid=0)
            for number in CHECKED_SETS:
                copy = next(c for c in self.sets if c['set'] == number and c['summary'])
                db.execute('INSERT OR IGNORE INTO copy_flag(copy_id, flag_id) VALUES(?, ?)', (copy['id'], flag))
                db.execute("UPDATE copy SET completeness='incomplete', completeness_source='derived' WHERE id=?", (copy['id'],))

    def missing_figures(self, db):
        """A figure missing from two of the incomplete copies."""
        with transaction(db):
            for number in ('7938-1', '10210-1'):
                copy = next(c for c in self.sets if c['set'] == number)
                figure = self.inventories[number]['minifigures'][-1]['figure']
                db.execute('UPDATE copy_figure SET missing=1 WHERE copy_id=? AND item_id=? AND retired_at IS NULL', (copy['id'], dataset.item_by(db, 'minifigs', figure)))

    def wishlists(self, db):
        lists = [('wl-birthday', 'Birthday ideas', 1), ('wl-castle', 'Castle and pirates', 2), ('wl-parts', 'Parts to buy', 3)]
        with transaction(db):
            for key, name, order in lists:
                db.execute("INSERT OR IGNORE INTO wishlist(id,name,sort,created_at) VALUES(?,?,?,?)", (key, name, order, dataset.STAMP))
            for index, (key, number, condition, maximum) in enumerate(WISHES):
                item = items.ensure(db, dataset.item_by(db, 'sets', number))
                db.execute('''INSERT INTO wish(id, wishlist_id, kind, item_id, color_id, quantity, condition, max_price, max_price_currency, added_at, updated_at)
                              VALUES(?, ?, 'set', ?, NULL, 1, ?, ?, 'EUR', ?, ?)''', ('wish-' + dataset.slug(number), key, item, condition, f'{maximum:.2f}', dataset.STAMP, dataset.STAMP))
                base = self.wished[number]['parts'] * (0.2 - 0.02 * (index % 4))
                dataset.price(db, item, None, 'N', round(base, 2), 11 + index, '2026-10-12T06:00:00.000Z', low=round(base * 0.88, 2), high=round(base * 1.2, 2))
                dataset.price(db, item, None, 'U', round(base * 0.74, 2), 19 + index * 2, '2026-10-12T06:00:00.000Z', low=round(base * 0.55, 2), high=round(base * 0.95, 2))
                for month in range(10):
                    dataset.price(db, item, None, 'N', round(base * (1.12 - 0.012 * month), 2), None, '2026-%02d-14T06:00:00.000Z' % (1 + month), current=False)
            wanted = zip(self.rng.sample(self.stockpool, 9), [40, 24, 16, 60, 12, 30, 8, 20, 50], [0.06, 0.12, 0.2, 0.05, 0.3, 0.1, 0.45, 0.15, 0.04])
            for index, (row, quantity, maximum) in enumerate(wanted):
                part, colour = dataset.item_by(db, 'parts', row['part']), dataset.colour_by(db, row['color']['id'])
                items.ensure(db, part)
                db.execute('''INSERT OR IGNORE INTO wish(id, wishlist_id, kind, item_id, color_id, quantity, condition, max_price, max_price_currency, added_at, updated_at)
                              VALUES(?, 'wl-parts', 'part', ?, ?, ?, 'new', ?, 'EUR', ?, ?)''', ('wish-part-%d' % index, part, colour, quantity, f'{maximum:.2f}', dataset.STAMP, dataset.STAMP))
                dataset.price(db, part, colour, 'N', round(maximum * 0.8, 2), 120 + index * 7, dataset.STAMP)

    def lot_plan(self):
        """(the Sticker line, the candidate sets best first): the Sticker line is a part line that exactly two of the STICKER_SETS hold, so the chooser
        offers those two; the lot's lines come from the best set, the second and a third set."""
        holders = {}
        for number, inventory in self.inventories.items():
            for row in inventory['parts']:
                if not row['spare']:
                    holders.setdefault((row['part'], row['color']['id']), set()).add(number)
        for pair in itertools.combinations(STICKER_SETS, 2):
            for number in pair:
                for row in self.inventories[number]['parts']:
                    if holders.get((row['part'], row['color']['id'])) == set(pair) and not row['spare'] and row['category'] != 'Stickers':
                        third = next(n for n in self.inventories if n not in pair and n != '31120-1')
                        return row, (pair[0], pair[1], third), holders
        raise ValueError('No part line is held by exactly two of the sets that hold a sticker sheet')

    def flea_market(self, db):
        """The Flea market bag: a lot of loose parts the Set detection ranks against the sets, the Sticker line of the chooser and the progress of a pull list.
        The lines are the parts that only one of the three candidate sets holds, in full quantity, a few parts several sets hold, and the sticker part."""
        from ..core import pull_list, stickers
        base, candidates, holders = self.lot_plan()
        chosen = []
        for number, count in zip(candidates, LOT_COUNTS):
            own = [r for r in self.inventories[number]['parts'] if not r['spare'] and holders[(r['part'], r['color']['id'])] == {number} and r['category'] != 'Stickers']
            chosen += own[:count]
        shared = [r for r in self.inventories[candidates[0]]['parts'] if not r['spare'] and len(holders[(r['part'], r['color']['id'])]) in (2, 3) and r is not base]
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
        best = dataset.item_by(db, 'sets', candidates[0])
        ticked = [r for r in self.inventories[candidates[0]]['parts'] if r not in chosen and r is not base and not r['spare'] and r['category'] != 'Stickers']
        for row in ticked[:PULL_TICKS]:
            pull_list.set_found(db, LOT, best, dataset.item_by(db, 'parts', row['part']), dataset.colour_by(db, row['color']['id']), row['quantity'])

    # ---------- the pictures ----------

    def illustrate(self, db):
        """The pictures of not-mit/rebrickable/images/, stored the way the app stores any picture: a file under data/images/ in the media folder and a
        `picture` row, source "Rebrickable". An item without one keeps the missing-picture tile."""
        from ..core.media import media_root
        manifest = pictures_manifest(self.folder)
        images = self.folder / 'images'
        folder = media_root(db) / 'data' / 'images'
        folder.mkdir(parents=True, exist_ok=True)
        with transaction(db):
            db.execute("INSERT OR IGNORE INTO source(id, name, kind, enabled) VALUES(?, 'Rebrickable', 'file', 1)", (SOURCE,))
            for row in showcase.picture_targets(db):
                file = manifest.get(showcase.picture_key(row))
                if file is None:
                    continue
                name = file.replace('/', '-')
                shutil.copyfile(images / file, folder / name)
                width, height = size_of(images / file)
                db.execute('INSERT OR IGNORE INTO picture(item_id, color_id, source, kind, local_path, url, width, height, fetched_at) VALUES(?, ?, ?, ?, ?, NULL, ?, ?, ?)',
                           (row['item_id'], row['color_id'], SOURCE, 'photo' if row['kind'] == 'part' else 'render', 'data/images/' + name, width, height, dataset.STAMP))


def size_of(path):
    """Width and height of a PNG or a JPEG, read from the header."""
    data = Path(path).read_bytes()
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return struct.unpack('>II', data[16:24])
    index = 2
    while index < len(data):   # JPEG: walk the segments to the first start-of-frame marker
        marker, length = data[index + 1], struct.unpack('>H', data[index + 2:index + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack('>HH', data[index + 5:index + 9])
            return width, height
        index += 2 + length
    raise ValueError('not a PNG or JPEG: %s' % path)


def layer(folder=FOLDER, pictures=True):
    return Layer(folder, pictures)
