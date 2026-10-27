"""What a catalogue build is seeded from (design 3.1): the catalogue file it replaces and the collection file."""
from contextlib import closing
from pathlib import Path
import sqlite3

from .connect import CATALOGUE_VERSION, SCHEMA_VERSION, _uri, check_ids_never_reused
from .errors import CatalogueError, CatalogueMismatch, SchemaMismatch

LOCAL_BASE = 1_000_000_000
FIXED_COLORS = {'9999': 1, '-1': 2}


def _rows(db, sql, *args):
    return [dict(r) for r in db.execute(sql, args)]


class OldCatalogue:
    """The file being replaced, opened read-only. Keeps the connection for the lines of carried inventories."""

    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(_uri(self.path, 'ro'), uri=True)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute('BEGIN')                      # one read snapshot for every read, the lines of carried inventories included
            try:
                self.meta = dict(self.db.execute('SELECT key, value FROM meta').fetchall())
            except sqlite3.DatabaseError as exc:
                raise CatalogueError(f'{self.path} cannot be read as a catalogue: {exc}') from exc
            if self.meta.get('schema_version') != CATALOGUE_VERSION:
                raise CatalogueError(f'{self.path} is not a Brick Work catalogue ({CATALOGUE_VERSION})')
            self.builds = _rows(self.db, 'SELECT * FROM build ORDER BY id')
            self.colors = {r['born_key']: r for r in _rows(self.db, 'SELECT * FROM color')}
            self.items = {(r['born_namespace'], r['born_key']): r for r in _rows(self.db, 'SELECT * FROM item')}
            self.themes = {r['id']: r for r in _rows(self.db, 'SELECT * FROM theme')}
            self.categories = {r['id']: r for r in _rows(self.db, 'SELECT * FROM part_category')}
            self.inventories = {(r['item_id'], r['version']): r for r in _rows(self.db, 'SELECT * FROM inventory')}
        except BaseException:
            self.db.close()
            raise

    def lines(self, inventory_id):
        """(part lines, figure lines, set lines) of one old inventory as lists of tuples."""
        return tuple([tuple(r) for r in self.db.execute(sql, (inventory_id,))] for sql in (
            'SELECT item_id, color_id, is_spare, quantity FROM inventory_part WHERE inventory_id=?',
            'SELECT item_id, quantity FROM inventory_figure WHERE inventory_id=?',
            'SELECT item_id, quantity FROM inventory_set WHERE inventory_id=?'))

    def close(self):
        self.db.close()


class CollectionSeed:
    """What the collection file contributes: ids of catalogue-origin rows, local Rebrickable-born items, bound meta."""

    def __init__(self, path):
        self.path = Path(path)
        with closing(sqlite3.connect(_uri(self.path, 'ro'), uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')                              # one read transaction: an activation cannot commit between the reads
            try:
                self.meta = dict(db.execute('SELECT key, value FROM meta').fetchall())
            except sqlite3.DatabaseError as exc:
                raise SchemaMismatch(f'{self.path} is not a Brick Work {SCHEMA_VERSION} collection: {exc}') from exc
            if self.meta.get('schema_version') != SCHEMA_VERSION:
                raise SchemaMismatch(f'{self.path} is not a Brick Work {SCHEMA_VERSION} collection '
                                     f"(schema_version={self.meta.get('schema_version')!r})")
            check_ids_never_reused(db, self.path)
            self.items = _rows(db, "SELECT * FROM item WHERE born_provider='rebrickable'")
            self.colors = _rows(db, "SELECT * FROM color WHERE born_provider='rebrickable'")
            self.builds = _rows(db, 'SELECT * FROM catalogue_build ORDER BY id')


class _Ids:
    """A key <-> id registry that refuses a key with two ids and an id with two keys."""

    def __init__(self, what):
        self.what = what
        self.by_key, self.by_id = {}, {}

    def add(self, key, id_, source):
        if key in self.by_key and self.by_key[key][0] != id_:
            other, where = self.by_key[key]
            raise CatalogueMismatch(f'{self.what} {key} is id {other} in the {where} but id {id_} in the {source}; '
                                    'the seeds come from different id spaces')
        if id_ in self.by_id and self.by_id[id_][0] != key:
            other, where = self.by_id[id_]
            raise CatalogueMismatch(f'{self.what} id {id_} is {other} in the {where} but {key} in the {source}; '
                                    'the seeds come from different id spaces')
        self.by_key.setdefault(key, (id_, source))
        self.by_id.setdefault(id_, (key, source))

    def id_of(self, key):
        found = self.by_key.get(key)
        return found[0] if found else None


class Seeds:
    """The merged seeds: item and colour ids by born key, adoptable local items, high-water marks, catalogue_id."""

    def __init__(self, old, collection):
        self.old, self.collection = old, collection
        self.items, self.colors = _Ids('item'), _Ids('colour')
        for key, id_ in FIXED_COLORS.items():
            self.colors.add(key, id_, 'fixed colour ids')
        self.adoptable = {}                       # (namespace, born_key) -> local id, from collection items origin=local
        self.merged_local = {}                    # local items merged into another: never adopted, reported if the dump has the key
        self.merged_catalogue = {}                # catalogue items merged in the collection: key -> (merged id, merged_into)
        self.shadowed = {}                        # local items whose key the catalogue already numbers otherwise: for reconcile
        self.replacement = {}                     # merged keys that came back: key -> the fresh id an earlier build gave them
        self.item_hw = self.color_hw = 0
        self.catalogue_id = None
        self.merged_ids = set()                   # every collection id merged away, local or catalogue: never a live catalogue id
        if collection:
            for row in collection.items:
                if row.get('merged_into') is not None:
                    self.merged_ids.add(row['id'])
                if row['origin'] == 'catalogue' and row.get('merged_into') is not None:
                    self.merged_catalogue[(row['born_namespace'], row['born_key'])] = (row['id'], row['merged_into'])
        if old:
            self._take_old(old)
        if collection:
            self._take_collection(collection)
        bound = {s for s in ((old.meta.get('catalogue_id') if old else None),
                             (collection.meta.get('catalogue_id') if collection else None)) if s}
        if len(bound) > 1:
            raise CatalogueMismatch(f"the catalogue {old.path} (catalogue_id {old.meta['catalogue_id']}) is another catalogue than the one "
                                    f"the collection is bound to ({collection.meta['catalogue_id']})")
        self.catalogue_id = next(iter(bound), None)
        for ids, attr in ((self.items, 'item_hw'), (self.colors, 'color_hw')):
            seeded = max([i for i in ids.by_id if i < LOCAL_BASE] or [0])
            setattr(self, attr, max(getattr(self, attr), seeded))
        self.color_hw = max(self.color_hw, 2)

    @staticmethod
    def _hw(meta, key):
        return int(meta.get(key) or 0)

    def _check_hw(self, id_, hw, what, source, name):
        if id_ < LOCAL_BASE and id_ > hw:
            raise CatalogueMismatch(f'{what} id {id_} in the {source} exceeds its {name} {hw}; the file is damaged or from another id space')

    def _take_old(self, old):
        hw_item, hw_color = self._hw(old.meta, 'item_high_water'), self._hw(old.meta, 'color_high_water')
        for key, row in old.items.items():
            self._check_hw(row['id'], hw_item, f'item {key}', 'old catalogue', 'item_high_water')
            merged = self.merged_catalogue.get(key)
            if row['id'] in self.merged_ids:
                continue                              # the collection says this id is merged away (an adopted local item too): the old seed yields
            if merged:
                self.replacement[key] = row['id']     # the fresh id an earlier build gave the returned key: it stays
            self.items.add(key, row['id'], 'old catalogue')
        for key, row in old.colors.items():
            if row['id'] not in FIXED_COLORS.values():
                self._check_hw(row['id'], hw_color, f'colour {key}', 'old catalogue', 'color_high_water')
            self.colors.add(key, row['id'], 'old catalogue')
        self.item_hw, self.color_hw = hw_item, hw_color

    def _take_collection(self, coll):
        hw_item, hw_color = self._hw(coll.meta, 'catalogue_item_high_water'), self._hw(coll.meta, 'catalogue_color_high_water')
        for row in coll.items:
            key = (row['born_namespace'], row['born_key'])
            if row['origin'] == 'catalogue':
                self._check_hw(row['id'], hw_item, f'item {key}', 'collection', 'catalogue_item_high_water')
                if key not in self.replacement:       # a merged id whose key already has its replacement is no seed
                    self.items.add(key, row['id'], 'collection')
        for row in coll.colors:
            if row['origin'] == 'catalogue':
                if row['id'] not in FIXED_COLORS.values():
                    self._check_hw(row['id'], hw_color, f"colour {row['born_key']}", 'collection', 'catalogue_color_high_water')
                self.colors.add(row['born_key'], row['id'], 'collection')
        self.item_hw, self.color_hw = max(self.item_hw, hw_item), max(self.color_hw, hw_color)
        # Local Rebrickable-born items are adopted when the dump has their key, unless a catalogue id already names the key.
        # Then the local item cannot be projected beside it (one born key, two ids): it is reported for reconcile to merge.
        for row in coll.items:
            key = (row['born_namespace'], row['born_key'])
            if row['origin'] != 'local':
                continue
            if row.get('merged_into') is not None:
                self.merged_local[key] = row['id']
            elif key not in self.items.by_key:
                self.adoptable[key] = row['id']
            elif self.items.id_of(key) != row['id']:
                self.shadowed[key] = row['id']
        for key, id_ in self.adoptable.items():
            if id_ in self.items.by_id and self.items.by_id[id_][0] != key:
                raise CatalogueMismatch(f'local item {key} has id {id_}, which the {self.items.by_id[id_][1]} gives to {self.items.by_id[id_][0]}')
