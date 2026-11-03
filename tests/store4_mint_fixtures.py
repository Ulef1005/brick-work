"""The fixture catalogue of design 8.11, built at test time from the CSVs under tests/regression/fixtures/catalogue/ with the
real builder (never a committed .db), and a small 3.3 store to mint against.

The CSVs are real rows of the Rebrickable dump and the shipped mapping, plus one synthetic composition row. Tests add rows of their
own through `extra_dump`, `extra_parts` and `extra_local` where the real rows lack a case; those names carry `syn`."""
import csv
import gzip
from pathlib import Path
import shutil
import sqlite3

from brickwork.store4.builder import build
from brickwork.store4.connect import connect
from brickwork.store4.dump import HEADERS

FIXTURES = Path(__file__).resolve().parent / 'regression' / 'fixtures' / 'catalogue'
SCHEMA_33 = Path(__file__).resolve().parent / 'legacy33' / 'schema-3.3.sql'
STAMP = '2026-10-23T12:00:00.000Z'


def _append(path, rows):
    with open(path, 'a', newline='') as f:
        for row in rows:
            csv.writer(f, lineterminator='\n').writerow(row)


def build_catalogue(tmp_path, *, extra_dump=None, extra_parts=(), extra_local=(), local_parts=(), composition=True):
    """Build `tmp_path/catalogue.db` from the fixture CSVs and return its path.

    `extra_dump`: {table: [rows]} appended to the dump files. `extra_parts`: rows of parts.csv (the shipped layer). `extra_local`: rows
    of the local minifigs.csv. `local_parts`: rows of a local parts.csv (it replaces the shipped rows of the parts it names).
    `composition=False` builds without the local layer (the "without composition file" case)."""
    dump = tmp_path / 'dump'
    dump.mkdir()
    for name in HEADERS:
        plain = tmp_path / 'plain' / f'{name}.csv'
        plain.parent.mkdir(exist_ok=True)
        # the figures file is stored as rebrickable-minifigs.csv: the repo guard (test_no_minifig_mapping_ships) refuses any tracked minifigs.csv
        shutil.copy(FIXTURES / 'dump' / ('rebrickable-minifigs.csv' if name == 'minifigs' else f'{name}.csv'), plain)
        _append(plain, (extra_dump or {}).get(name, ()))
        with open(plain, 'rb') as src, gzip.open(dump / f'{name}.csv.gz', 'wb') as out:
            out.write(src.read())
    maps = tmp_path / 'mappings'
    shutil.copytree(FIXTURES / 'mappings', maps)
    _append(maps / 'parts.csv', extra_parts)
    local = None
    if composition or local_parts:
        local = tmp_path / 'local'
        local.mkdir()
        if composition:
            shutil.copy(FIXTURES / 'local' / 'figure-composition.csv', local / 'minifigs.csv')   # stored under another name: see above
            _append(local / 'minifigs.csv', extra_local)
        if local_parts:
            head = '# mapping_version: 2099.1.1.1\n# dump_date: 2026-10-23\n# source: SYNTHETIC\n'
            (local / 'parts.csv').write_text(head + 'rb_part_num,rb_color_id,provider,provider_kind,provider_key,status,method,preferred\n')
            _append(local / 'parts.csv', local_parts)
    target = tmp_path / 'catalogue.db'
    build(dump, target, app_version='4.0.test', now=STAMP, mappings_dir=maps, local_dir=local)
    return target


def open_collection(tmp_path, catalogue):
    """A fresh 4.0 collection with the catalogue attached read-only."""
    return connect(tmp_path / 'brickwork-4.db', catalogue)


def item_id(db, namespace, born_key):
    return db.execute("SELECT id FROM catalogue.item WHERE born_namespace=? AND born_key=?", (namespace, born_key)).fetchone()[0]


def colour_id(db, born_key):
    return db.execute("SELECT id FROM catalogue.color WHERE born_key=?", (born_key,)).fetchone()[0]


class Store33:
    """A 3.3 store in memory (the 3.3 schema without the foreign keys that would force every row's parents)."""

    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript(SCHEMA_33.read_text())
        self.db.execute('PRAGMA foreign_keys=OFF')
        self._n = 0
        for color_id, name, kind, rgb in ((1, 'White', 'Solid', 'FFFFFF'), (5, 'Red', 'Solid', 'C91A09'), (11, 'Black', 'Solid', '05131D'),
                                          (72, 'Maersk Blue', 'Solid', '3592C3'), (77, 'Pearl Dark Gray', 'Pearl', '575857'),
                                          (0, '(Not Applicable)', 'Solid', None), (3, 'Yellow', 'Solid', 'F2CD37'),
                                          (500, 'Invented Trans Colour', 'Transparent', 'AABBCC'), (501, 'Invented Solid', 'Solid', None)):
            self.db.execute('INSERT INTO colors VALUES(?, ?, ?, ?)', (color_id, name, kind, rgb))

    def item(self, item_type, item_no, name=None, year=None):
        self.db.execute('INSERT OR IGNORE INTO items(item_type, item_no, name, year) VALUES(?, ?, ?, ?)', (item_type, item_no, name, year))

    def copy(self, set_no, item_type='S'):
        self._n += 1
        copy_id = f'copy-{self._n}'
        self.item(item_type, set_no)
        self.db.execute('INSERT INTO copies(id, item_type, set_no) VALUES(?, ?, ?)', (copy_id, item_type, set_no))
        return copy_id

    def part(self, copy_id, item_type, item_no, color_id, parent=None, quantity=1):
        self.item(item_type, item_no)
        if parent:
            self.item(*parent)
        self.db.execute('INSERT INTO copy_parts(copy_id, parent_minifig_type, parent_minifig, item_type, item_no, color_id, spare, quantity) '
                        'VALUES(?, ?, ?, ?, ?, ?, 0, ?)', (copy_id, *(parent or (None, None)), item_type, item_no, color_id, quantity))

    def figure(self, copy_id, item_type, item_no):
        self.item(item_type, item_no)
        self.db.execute('INSERT INTO copy_minifigs(copy_id, item_type, minifig_no, quantity) VALUES(?, ?, ?, 1)', (copy_id, item_type, item_no))

    def stock(self, item_type, item_no, color_id=None):
        self._n += 1
        self.item(item_type, item_no)
        self.db.execute('INSERT INTO loose_stock(id, item_type, item_no, color_id, quantity) VALUES(?, ?, ?, ?, 1)',
                        (f'stock-{self._n}', item_type, item_no, color_id))
        return f'stock-{self._n}'

    def stock_part(self, stock_id, item_type, item_no, color_id):
        self.item(item_type, item_no)
        self.db.execute('INSERT INTO loose_minifig_parts(stock_id, item_type, item_no, color_id, spare, quantity) VALUES(?, ?, ?, ?, 0, 1)',
                        (stock_id, item_type, item_no, color_id))

    def wish(self, item_type, item_no, color_id=None):
        self.item(item_type, item_no)
        self.db.execute('INSERT INTO wishlist(item_type, item_no, color_id, quantity) VALUES(?, ?, ?, 1)', (item_type, item_no, color_id))
