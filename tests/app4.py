"""Shared helpers for tests of the app on a 4.0 collection (M.8b, issue #110); later pieces reuse them.

`make_pair` is the fixture pair: the offline fixture catalogue of `store4_mint_fixtures` beside a fresh, activated collection.
`Coll` writes into it through the store4 writers where they exist (`add_copy` is `store4.copies.create_copy`) and with plain SQL where
the writer belongs to a later piece (stock, wishes, prices, places): one helper per row, each committing, so a request made right
after sees it. `app4` is the real app on the pair and `client` a logged-in browser. Invented data only, no network.

    def test_x(coll, client):
        set_id = coll.item('sets', '2070-1')
        coll.add_copy('2070-1', condition='used', completeness='incomplete')
        coll.add_stock('part', coll.item('parts', '3001'), colour=coll.colour('4'), quantity=3)
        assert client.get('/collection/parts').status_code == 200
"""
from contextlib import closing
import shutil
import uuid

from flask import Flask
import pytest

from brickwork.app import setup_app
from brickwork.core.connect import connect
from brickwork.store4 import copies, fetched, identity
from brickwork.store4.activate import activate
from tests.store4_mint_fixtures import build_catalogue, colour_id, item_id
from tests.web_fixtures import ROOT, logged_in

STAMP = '2026-10-26T12:00:00.000Z'
BROWSER_PASSWORD = 'synthetic-password'


# Rows of the Rebrickable dump the fixture catalogue lacks: a Castle set `1000-1` (theme Castle, two figures, a spare) with 3001 in red,
# 3023 in white and the figure `fig-000004`; `1000-2` is a second set of the same parts. Marked `syn`: invented, not real dump rows.
RICH = {
    'themes': [[600, 'Castle', '']],
    'sets': [['1000-1', 'Syn Castle Keep', 1990, 600, 7, ''], ['1000-2', 'Syn Castle Gate', 1991, 600, 3, '']],
    'inventories': [[9001, 1, '1000-1'], [9002, 1, '1000-2']],
    'inventory_parts': [[9001, '3001', 4, 4, 'False', ''], [9001, '3023', 15, 2, 'False', ''], [9001, '3023', 4, 1, 'True', ''],
                        [9002, '3001', 4, 2, 'False', ''], [9002, '3023', 15, 1, 'False', '']],
    'inventory_minifigs': [[9001, 'fig-000004', 2]],
}


def make_pair(tmp_path, *, rich=False, **catalogue):
    """`tmp_path/brickwork.db` and `tmp_path/catalogue.db`, activated. Keyword arguments go to `build_catalogue` (`extra_dump`, ...);
    `rich=True` adds `RICH` to the dump."""
    (tmp_path / 'cat').mkdir()
    if rich:
        catalogue['extra_dump'] = {**RICH, **(catalogue.get('extra_dump') or {})}
    shutil.copy(build_catalogue(tmp_path / 'cat', **catalogue), tmp_path / 'catalogue.db')
    path = tmp_path / 'brickwork.db'
    with closing(connect(path)) as db:
        activate(db)
    return path


class Coll:
    """Writers over one open connection to a 4.0 collection (catalogue attached). Every method commits."""

    def __init__(self, db):
        self.db = db
        self.ticks = 0

    def tick(self):
        """A creation stamp later than the one before (a millisecond apart): copies and stock sort by creation, ties by a random id."""
        self.ticks += 1
        return f'2026-10-26T12:{self.ticks // 60000 % 60:02d}:{self.ticks // 1000 % 60:02d}.{self.ticks % 1000:03d}Z'

    # --- ids
    def item(self, namespace, key):
        """The id of a catalogue item by Rebrickable namespace (`sets`, `parts`, `minifigs`) and number."""
        return item_id(self.db, namespace, key)

    def colour(self, born_key):
        """The Brick Work colour id of a Rebrickable colour number."""
        return colour_id(self.db, born_key)

    def project(self, item):
        identity.project(self.db, item)
        self.db.commit()
        return item

    # --- items
    def local(self, kind, name, *, born_key=None, namespace=None, provider='bricklink', year=None):
        """A local item (id from 1,000,000,000): BrickLink-born with `born_key`, or unidentified without one."""
        namespace = namespace or {'set': 'S', 'part': 'P', 'minifigure': 'M', 'instructions': 'I', 'box': 'O', 'gear': 'G', 'book': 'B', 'catalog': 'C'}[kind]
        new = fetched.create_local_item(self.db, kind=kind, born_provider=provider if born_key else None, born_namespace=namespace if born_key else None,
                                        born_key=born_key, name=name, kind_source='bricklink' if born_key else 'manual', year=year)
        self.db.commit()
        return new

    def link(self, item, key, *, kind='P', colour=None, provider='bricklink', status='matched', preferred=0):
        """A confirmed (or `to_check`) provider link on a projected item."""
        self.project(item) if self.db.execute('SELECT 1 FROM main.item WHERE id=?', (item,)).fetchone() is None else None
        self.db.execute('''INSERT INTO main.item_link(item_id,color_id,provider,provider_kind,provider_key,status,method,origin,preferred,decided_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)''', (item, colour, provider, kind, key, status, 'external_ids' if status != 'manual' else 'user',
                                                          'shipped' if status != 'manual' else 'user', preferred, STAMP))
        self.db.commit()

    # --- places
    def _named(self, table, name, **fields):
        identifier = fields.pop('id', None) or uuid.uuid4().hex
        columns = ['id', 'name', 'created_at', *fields]
        self.db.execute(f'INSERT INTO {table}({",".join(columns)}) VALUES({",".join("?" * len(columns))})', (identifier, name, STAMP, *fields.values()))
        self.db.commit()
        return identifier

    def storage(self, name, **fields):
        return self._named('storage', name, **fields)

    def place(self, name, **fields):
        return self._named('place', name, **fields)

    def lot(self, name, **fields):
        identifier = fields.pop('id', None) or uuid.uuid4().hex
        self.db.execute('INSERT INTO lot(id,name,created_at,updated_at,storage_id,place_id,note) VALUES(?,?,?,?,?,?,?)',
                        (identifier, name, STAMP, STAMP, fields.get('storage_id'), fields.get('place_id'), fields.get('note')))
        self.db.commit()
        return identifier

    def flag(self, name, kind='tag', *, shown_on_grid=1):
        """A flag, or the one of that name when it exists (the status flags are seeded by the migration, not by setup)."""
        found = self.db.execute('SELECT id FROM flag WHERE name=? AND kind=?', (name, kind)).fetchone()
        if found:
            return found[0]
        return self._named('flag', name, kind=kind, shown_on_grid=shown_on_grid)

    def tag(self, entity, row_id, flag):
        table, column = {'copy': ('copy_flag', 'copy_id'), 'stock': ('stock_flag', 'stock_id'), 'wish': ('wish_flag', 'wish_id')}[entity]
        self.db.execute(f'INSERT INTO {table}({column},flag_id) VALUES(?,?)', (row_id, flag))
        self.db.commit()

    # --- what is owned
    def add_copy(self, set_key='2070-1', *, choice=None, storage=None, place=None, price=None, currency=None, date=None, note=None, pinned=0,
                 version=None, **fields):
        """A copy of a catalogue set through `store4.copies.create_copy` (its lines come from the catalogue's latest list), then the
        columns the writer does not take (`storage`, `place`, `price` with `currency`, `date`, `current_value`...) by SQL. Returns the copy id."""
        set_item = self.item('sets', set_key)
        choice = choice or {'source': 'rebrickable', 'version': version}
        receipt = copies.create_copy(self.db, set_item, choice, via='cli', condition=fields.pop('condition', None),
                                     completeness=fields.pop('completeness', None), note=note)
        cid = receipt['copy']['id']
        columns = {'storage_id': storage, 'place_id': place, 'purchase_price': price, 'purchase_currency': currency if price is not None else None,
                   'purchase_date': date, 'pinned': pinned, **fields}
        columns = {k: v for k, v in columns.items() if v is not None and not (k == 'pinned' and v == 0)}
        columns.setdefault('created_at', self.tick())
        if columns:
            self.db.execute('UPDATE copy SET ' + ','.join(f'{k}=?' for k in columns) + ' WHERE id=?', (*columns.values(), cid))
        self.db.commit()
        return cid

    def mark(self, copy_id, part_key, colour_key, *, missing=0, damaged=0, checked=None, figure=None):
        """Set the state of one live line of a copy: the part by Rebrickable number and colour, in the set or in a figure."""
        item, colour = self.item('parts', part_key), self.colour(colour_key)
        scope = 'AND copy_figure_id IS NULL' if figure is None else 'AND copy_figure_id=(SELECT id FROM copy_figure WHERE copy_id=? AND item_id=?)'
        args = (copy_id, item, colour) + (() if figure is None else (copy_id, self.item('minifigs', figure)))
        changes = {'missing': missing, 'damaged': damaged}
        if checked is not None:
            changes['checked'] = checked
        done = self.db.execute('UPDATE copy_part SET ' + ','.join(f'{k}=?' for k in changes) + f' WHERE copy_id=? AND item_id=? AND color_id=? AND retired_at IS NULL {scope}',
                               (*changes.values(), *args)).rowcount
        self.db.commit()
        assert done == 1, f'{part_key}/{colour_key} is not one live line of the copy'

    def mark_figure(self, copy_id, figure_key, *, missing):
        self.db.execute('UPDATE copy_figure SET missing=? WHERE copy_id=? AND item_id=? AND retired_at IS NULL', (missing, copy_id, self.item('minifigs', figure_key)))
        self.db.commit()

    def retire_line(self, copy_id, part_key, colour_key):
        """Retire a line as an in-place switch does (design 4.4): the row stays, `retired_at` says it is no line."""
        self.db.execute('UPDATE copy_part SET retired_at=? WHERE copy_id=? AND item_id=? AND color_id=?', (STAMP, copy_id, self.item('parts', part_key), self.colour(colour_key)))
        self.db.commit()

    def add_stock(self, kind, item, *, colour=None, quantity=1, condition='used', storage=None, lot=None, place=None, price=None, currency=None,
                  note=None, missing=None, damaged=None, checked=None, source=None):
        """Loose stock of an item (a catalogue id is projected first). A loose figure takes its part list from the catalogue's latest
        (`source='rebrickable'`) unless `source` says `none`. Returns the stock id."""
        self.db.execute('SELECT 1')
        identity.project(self.db, item) if self.db.execute('SELECT 1 FROM main.item WHERE id=?', (item,)).fetchone() is None else None
        sid = uuid.uuid4().hex
        extra = {}
        if kind == 'minifigure':
            version = self.db.execute('SELECT version, digest FROM catalogue.inventory WHERE item_id=? AND is_latest=1', (item,)).fetchone()
            if source == 'none' or version is None:
                extra = dict(inventory_source='none', inventory_digest='none')
            else:
                extra = dict(inventory_source='rebrickable', inventory_version=version['version'], inventory_digest=version['digest'])
        columns = dict(id=sid, kind=kind, item_id=item, color_id=colour if kind == 'part' else None, quantity=quantity, condition=condition,
                       storage_id=storage, lot_id=lot, place_id=place, purchase_price=price, purchase_currency=currency if price is not None else None,
                       note=note, missing=missing, damaged=damaged, checked=checked, created_at=self.tick(), updated_at=STAMP, **extra)
        self.db.execute(f'INSERT INTO stock({",".join(columns)}) VALUES({",".join("?" * len(columns))})', tuple(columns.values()))
        if extra.get('inventory_source') == 'rebrickable':
            for part in self.db.execute('SELECT item_id,color_id,is_spare,quantity FROM catalogue.inventory_part WHERE inventory_id=(SELECT id FROM catalogue.inventory WHERE item_id=? AND is_latest=1)', (item,)).fetchall():
                identity.project(self.db, part['item_id'])
                self.db.execute('INSERT INTO stock_part(stock_id,item_id,color_id,is_spare,quantity) VALUES(?,?,?,?,?)', (sid, part['item_id'], part['color_id'], part['is_spare'], part['quantity']))
        self.db.commit()
        return sid

    def add_wish(self, item, *, kind=None, colour=None, quantity=1, condition=None, max_price=None, currency=None, wishlist='default', filled=None, note=None):
        """A wish for an item (projected first). `kind` defaults to the item's. Returns the wish id."""
        identity.project(self.db, item) if self.db.execute('SELECT 1 FROM main.item WHERE id=?', (item,)).fetchone() is None else None
        kind = kind or self.db.execute('SELECT kind FROM main.item WHERE id=?', (item,)).fetchone()[0]
        wid = uuid.uuid4().hex
        self.db.execute('''INSERT INTO wish(id,wishlist_id,kind,item_id,color_id,quantity,condition,max_price,max_price_currency,qty_filled_manual,note,added_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (wid, wishlist, kind, item, colour if kind == 'part' else None, quantity, condition, max_price,
                                                                 currency if max_price is not None else None, filled, note, STAMP, STAMP))
        self.db.commit()
        return wid

    def price(self, item, price, *, colour=None, condition='used', guide='sold', slot=None, region=None, currency='EUR', source='bricklink', observed=STAMP,
              minimum=None, maximum=None, sold=None, qty=None, error=None, key=None):
        """One observation and its `price_current` row (what a price refresh leaves). Returns the observation id."""
        identity.project(self.db, item) if self.db.execute('SELECT 1 FROM main.item WHERE id=?', (item,)).fetchone() is None else None
        observation = self.db.execute('''INSERT INTO price_observation(item_id,color_id,condition,guide,slot,region,currency,price,qty,sold,min,max,source,provider_key,observed_at,error)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (item, colour, condition, guide, slot, region, currency, price, qty, sold, minimum, maximum, source, key, observed, error)).lastrowid
        self.db.execute('''INSERT OR REPLACE INTO price_current(item_id,color_id,condition,guide,slot,region,currency,observation_id) VALUES(?,?,?,?,?,?,?,?)''',
                        (item, colour, condition, guide, slot, region, currency, observation))
        self.db.commit()
        return observation

    def prop(self, item, key, value, *, source='brickset', unit=None):
        identity.project(self.db, item) if self.db.execute('SELECT 1 FROM main.item WHERE id=?', (item,)).fetchone() is None else None
        self.db.execute('INSERT INTO item_property(item_id,key,source,value,unit,fetched_at) VALUES(?,?,?,?,?,?)', (item, key, source, value, unit, STAMP))
        self.db.commit()

    def setting(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO setting(key,value) VALUES(?,?)', (key, value))
        self.db.commit()

    def sql(self, statement, params=()):
        """Anything else a test needs to arrange, committed."""
        cursor = self.db.execute(statement, params)
        self.db.commit()
        return cursor


class World:
    """What `build_world` made: ids by name (`w.copy_a`, `w.set_keep`, ...). Attribute access only."""

    def __init__(self, **ids):
        self.__dict__.update(ids)


def build_world(coll):
    """A small collection with a bit of everything the screens show, on the rich fixture catalogue (`RICH`).

    Sets: `1000-1` "Syn Castle Keep" (two figures, 3001 red x4, 3023 white x2, a spare) and `1000-2`, `2070-1` (Duplo, two versions).
    Copies: A = 1000-1 used, incomplete, one red 3001 missing, on Shelf A, bought at Shop for 12.50 EUR; B = 1000-1 new, sealed; C = 2070-1 used, complete.
    Stock: 3001 red x3 used (lot Bag, Shelf A) and x2 new, 3023 white x2 new, fig-000004 x1 used (with its parts), a local BrickLink-born part,
    a local BrickLink-born booklet, an unidentified gear item. Wishes: set 1000-2, 3023 white x2 with a maximum price. Used-sold prices for the
    set, 3001 red and the figure. Flags: tag "collection", statuses "Set is checked", "Box present", "Instructions present"."""
    shelf, shop = coll.storage('Shelf A', type='Shelf'), coll.place('Shop', kind='Shop')
    bag = coll.lot('Bag', storage_id=shelf)
    tag = coll.flag('collection', 'tag')
    checked, box, booklet_flag = (coll.flag(n, 'status') for n in ('Set is checked', 'Box present', 'Instructions present'))
    keep, gate, duplo = (coll.item('sets', n) for n in ('1000-1', '1000-2', '2070-1'))
    brick, plate, figure = coll.item('parts', '3001'), coll.item('parts', '3023'), coll.item('minifigs', 'fig-000004')
    red, white = coll.colour('4'), coll.colour('15')
    copy_a = coll.add_copy('1000-1', condition='used', completeness='incomplete', storage=shelf, place=shop, price='12.50', currency='EUR', date='2024-05-01', note='Flea market')
    copy_b = coll.add_copy('1000-1', condition='new', completeness='sealed')
    copy_c = coll.add_copy('2070-1', condition='used', completeness='complete')
    coll.mark(copy_a, '3001', '4', missing=1)
    coll.tag('copy', copy_a, tag)
    coll.tag('copy', copy_a, checked)
    local_part = coll.local('part', 'Only on BrickLink', born_key='x999')
    local_booklet = coll.local('instructions', 'Syn Castle Keep booklet', born_key='1000-1')
    mystery = coll.local('gear', 'Mystery thing')
    stock_brick = coll.add_stock('part', brick, colour=red, quantity=3, condition='used', storage=shelf, lot=bag)
    stock_brick_new = coll.add_stock('part', brick, colour=red, quantity=2, condition='new')
    stock_plate = coll.add_stock('part', plate, colour=white, quantity=2, condition='new')
    stock_figure = coll.add_stock('minifigure', figure, quantity=1, condition='used')
    stock_local = coll.add_stock('part', local_part, colour=red, quantity=5, condition='used')
    stock_booklet = coll.add_stock('instructions', local_booklet, quantity=1, condition='used')
    stock_mystery = coll.add_stock('gear', mystery, quantity=2, condition='new')
    wish_set = coll.add_wish(gate, quantity=1, condition='any')
    wish_part = coll.add_wish(plate, colour=white, quantity=2, condition='new', max_price='0.50', currency='EUR')
    coll.price(keep, '30.00', condition='used', minimum='25.00', maximum='35.00', sold=4)
    coll.price(brick, '0.40', colour=red, condition='used', minimum='0.20', maximum='0.60', sold=9)
    coll.price(figure, '2.00', condition='used', sold=3)
    return World(shelf=shelf, shop=shop, bag=bag, tag=tag, checked=checked, box=box, booklet_flag=booklet_flag, keep=keep, gate=gate, duplo=duplo,
                 brick=brick, plate=plate, figure=figure, red=red, white=white, copy_a=copy_a, copy_b=copy_b, copy_c=copy_c, local_part=local_part,
                 local_booklet=local_booklet, mystery=mystery, stock_brick=stock_brick, stock_brick_new=stock_brick_new, stock_plate=stock_plate,
                 stock_figure=stock_figure, stock_local=stock_local, stock_booklet=stock_booklet, stock_mystery=stock_mystery, wish_set=wish_set,
                 wish_part=wish_part)


@pytest.fixture
def world(coll):
    """`build_world` on the `coll` fixture's collection."""
    return build_world(coll)


@pytest.fixture
def pair(tmp_path):
    """The path of an activated 4.0 collection with the rich fixture catalogue (`RICH`) beside it."""
    return make_pair(tmp_path, rich=True)


@pytest.fixture
def coll(pair):
    with closing(connect(pair)) as db:
        yield Coll(db)


@pytest.fixture
def read(pair):
    """A read-only connection per call: `with read() as db:`; sees what the writers committed."""
    return lambda: closing(connect(pair, read_only=True))


@pytest.fixture
def app4(pair, monkeypatch):
    """The real app on the pair (no embedded worker, password login)."""
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', BROWSER_PASSWORD)
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    app = Flask('app4-tests', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config.update(TESTING=True, SECRET_KEY='synthetic-session')
    return app


@pytest.fixture
def client(app4):
    return logged_in(app4)
