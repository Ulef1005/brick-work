"""The app's identity facade over the 4.0 store (M.8a, issue #110; design 3, 6.3).

Every screen and writer that used to say `(item_type, item_no)` says an item id and asks this module for the rest:

- `label(db, item_id, color_id=None)`: what to show for an item (decision 3 of the #110 scope: the Rebrickable born number first, the
  preferred BrickLink number beside it where it differs; a local BrickLink-born item shows its BrickLink number, marked BrickLink).
- `find(db, kind, number)`: items for a number a person typed or pasted: born key, then the catalogue's search index, then BrickLink links.
- `ensure(db, item_id)`: the item (and its links and colours) in the collection, projected from the catalogue when it is not yet.
- `bricklink_key(db, item_id, color_id)`: the BrickLink type, number and colour number, or `Unidentified`.
- the kind vocabulary and the BrickLink type letter <-> kind mapping, which belong to the borders (imports, exports, BrickLink calls) only.

An item is read from the collection when it is projected there, else from the catalogue. Nothing here writes except `ensure`, which writes
inside the caller's transaction (see `store4.identity.project`)."""
from dataclasses import asdict, dataclass
import json
import sqlite3

from ..store4 import identity
from ..store4.connect import has_catalogue
from ..store4.mint import TYPE_KIND
from . import errors

KINDS = ('set', 'part', 'minifigure', 'instructions', 'box', 'gear', 'book', 'catalog')
KIND_TYPE = {kind: letter for letter, kind in TYPE_KIND.items()}                 # BrickLink type letter <-> kind, borders only
CONFIRMED = identity.CONFIRMED
_IN = ','.join('?' * len(CONFIRMED))
BRICKLINK, REBRICKABLE = 'bricklink', 'rebrickable'


class Unidentified(errors.Unidentified):
    """The item has no BrickLink number: a BrickLink call, list or export cannot name it."""


def kind_of_type(letter):
    """The kind of a BrickLink item type letter (S, P, M, G, B, C, I, O)."""
    try:
        return TYPE_KIND[letter]
    except KeyError:
        raise errors.ValidationFailed(f'{letter!r} is not a BrickLink item type') from None


def type_of_kind(kind):
    """The BrickLink item type letter of a kind."""
    try:
        return KIND_TYPE[kind]
    except KeyError:
        raise errors.ValidationFailed(f'{kind!r} is not a kind (one of {", ".join(KINDS)})') from None


def _stores(db):
    return ('main', 'catalogue') if has_catalogue(db) else ('main',)


def _row(db, item_id):
    """The item as the collection holds it, else as the catalogue does; None if neither knows it."""
    for store in _stores(db):
        row = db.execute(f'SELECT id, kind, name, born_provider, born_namespace, born_key FROM {store}.item WHERE id=?', (item_id,)).fetchone()
        if row is not None:
            return row, store
    return None, None


def _colour_key(db, color_id):
    """The BrickLink colour number of a colour (best confirmed link; the collection's links win over the catalogue's), or None."""
    if color_id is None:
        return None
    for store in _stores(db):
        if store == 'catalogue' and db.execute('SELECT 1 FROM main.color WHERE id=?', (color_id,)).fetchone():
            return None                                     # a projected colour is the collection's: no links there means none
        rows = [dict(r) for r in db.execute(f'''SELECT provider_key, status FROM {store}.color_link
                                              WHERE color_id=? AND provider='bricklink' AND status IN ({_IN})''', (color_id, *CONFIRMED))]
        best = identity.best_color_link(rows)
        if best:
            return best['provider_key']
    return None


def _resolve(db, row, store, color_id):
    """(type, key, colour key) or None. Projected items go through `identity.resolve` itself; a catalogue-only item ranks its
    catalogue links with the same functions; a local BrickLink-born item with no link is its own BrickLink key."""
    item_id = row['id']
    if store == 'main' and (color_id is None or db.execute('SELECT 1 FROM main.color WHERE id=?', (color_id,)).fetchone()):
        found = identity.resolve(db, item_id, color_id)
    else:
        links = [dict(r) for r in db.execute(f'''SELECT provider_kind, provider_key, color_id, preferred, status FROM {store}.item_link
                                               WHERE item_id=? AND provider='bricklink' AND status IN ({_IN})''', (item_id, *CONFIRMED))]
        best = identity.best_item_link(links, color_id)
        found = (best['provider_kind'], best['provider_key'], _colour_key(db, color_id)) if best else None
    if found is None and row['born_provider'] == BRICKLINK and row['born_key'] is not None:
        found = (row['born_namespace'], row['born_key'], _colour_key(db, color_id))
    return found


@dataclass(frozen=True)
class Label:
    item_id: int
    kind: str
    name: str
    number: str | None            # what to show first; None for an unidentified item
    source: str | None            # 'rebrickable' | 'bricklink' (a local BrickLink-born item: mark it) | None
    also: str | None              # the preferred BrickLink number, shown beside `number` only where it differs
    bricklink: tuple | None       # (BrickLink type, number, colour number) through identity.resolve, else None
    unidentified: bool            # no born key at all (the item has no number from any provider)
    color_id: int | None = None

    @property
    def text(self):
        """One line for a screen: `3001`, `3001 · BrickLink 3001a`, `BrickLink x1718c01 (BrickLink)`, or the name of an unidentified item."""
        if self.number is None:
            return self.name
        if self.source == BRICKLINK:
            return f'{self.number} (BrickLink)'
        return f'{self.number} · BrickLink {self.also}' if self.also else self.number

    def as_dict(self):
        return asdict(self) | {'text': self.text}


def _label(row, found, color_id):
    number, source = row['born_key'], row['born_provider']
    also = found[1] if found and source == REBRICKABLE and found[1] != number else None
    return Label(item_id=row['id'], kind=row['kind'], name=row['name'], number=number, source=source, also=also,
                 bricklink=found, unidentified=number is None, color_id=color_id)


def label(db, item_id, color_id=None):
    """What to show for an item (and colour). Raises NotFound for an id neither file knows."""
    row, store = _row(db, item_id)
    if row is None:
        raise errors.NotFound(f'No item {item_id}')
    return _label(row, _resolve(db, row, store, color_id), color_id)


def _colour_keys(db, color_ids):
    """`{colour id: BrickLink colour number or None}` for many colours: the same answers as `_colour_key`, in two queries."""
    wanted = sorted({c for c in color_ids if c is not None})
    keys = dict.fromkeys(wanted)
    if not wanted:
        return keys
    packed = json.dumps(wanted)
    projected = {r[0] for r in db.execute('SELECT id FROM main.color WHERE id IN (SELECT value FROM json_each(?))', (packed,))}
    found, stores = {}, _stores(db)
    for store in stores:
        for r in db.execute(f"""SELECT color_id, provider_key, status FROM {store}.color_link WHERE provider='bricklink' AND status IN ({_IN})
                                AND color_id IN (SELECT value FROM json_each(?))""", (*CONFIRMED, packed)):
            found.setdefault((store, r['color_id']), []).append(dict(r))
    for colour in wanted:
        for store in stores:
            if store == 'catalogue' and colour in projected:
                break                                           # a projected colour is the collection's: no links there means none
            best = identity.best_color_link(found.get((store, colour), []))
            if best:
                keys[colour] = best['provider_key']
                break
    return keys


def labels(db, pairs):
    """`{(item_id, color_id): Label}` for many pairs at once (list screens): the same answers as `label`, in a handful of queries
    (items, links, colours). A pair whose item neither file knows is left out."""
    pairs = {(item_id, color_id) for item_id, color_id in pairs}
    if not pairs:
        return {}
    stores = _stores(db)
    wanted = {item_id for item_id, _ in pairs}
    rows = {}
    for store in stores:                                          # the collection's row wins over the catalogue's
        missing = sorted(wanted - rows.keys())
        if not missing:
            break
        for r in db.execute(f'SELECT id, kind, name, born_provider, born_namespace, born_key FROM {store}.item WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(missing),)):
            rows[r['id']] = (r, store)
    links = {}
    for store in stores:
        ids = sorted(i for i, (_, s) in rows.items() if s == store)
        if not ids:
            continue
        for r in db.execute(f"""SELECT item_id, provider_kind, provider_key, color_id, preferred, status FROM {store}.item_link
                                WHERE provider='bricklink' AND status IN ({_IN}) AND item_id IN (SELECT value FROM json_each(?))""", (*CONFIRMED, json.dumps(ids))):
            links.setdefault(r['item_id'], []).append(dict(r))
    found = {}
    for item_id, color_id in pairs:
        if item_id not in rows:
            continue
        row, _ = rows[item_id]
        best = identity.best_item_link(links.get(item_id, []), color_id)
        found[item_id, color_id] = (best['provider_kind'], best['provider_key']) if best else (
            (row['born_namespace'], row['born_key']) if row['born_provider'] == BRICKLINK and row['born_key'] is not None else None)
    colours = _colour_keys(db, [c for (i, c), f in found.items() if f is not None])
    return {(i, c): _label(rows[i][0], (*f, colours.get(c)) if f else None, c) for (i, c), f in found.items()}


def bricklink_key(db, item_id, color_id=None):
    """(BrickLink type, number, colour number) of an item in a colour, or `Unidentified` when no confirmed link names it."""
    row, store = _row(db, item_id)
    if row is None:
        raise errors.NotFound(f'No item {item_id}')
    found = _resolve(db, row, store, color_id)
    if found is None:
        raise Unidentified(f'Item {item_id} ({row["name"]}) has no BrickLink number')
    return found


def ensure(db, item_id):
    """The item in the collection: projected from the catalogue (with its links and colours) when it is not there yet.

    Writes inside the caller's transaction and does not commit; the caller's commit or rollback decides (`store4.identity.project`)."""
    return identity.project(db, item_id)


def find(db, kind, number, *, limit=20):
    """The items a typed number may mean, best first: `[dict(item_id, kind, name, number, matched_by)]`.

    Order: the born key (the Rebrickable number, or a local item's BrickLink number), then the catalogue's search index over the born
    and every linked number, then confirmed BrickLink links. `kind` is a kind (or None for all). A merged item is replaced by the item it
    was merged into. Search takes both numbers: `3001` and the BrickLink `3001a` find the same part when a link says so."""
    number = (number or '').strip()
    if not number:
        return []
    if kind is not None and kind not in KINDS:
        raise errors.ValidationFailed(f'{kind!r} is not a kind (one of {", ".join(KINDS)})')
    found = {}                                                  # item id -> how, in order of first discovery

    def add(ids, how):
        for item_id in ids:
            item_id = _merged_target(db, item_id)
            found.setdefault(item_id, how)

    kind_sql, kind_args = (' AND kind=?', (kind,)) if kind else ('', ())
    for store in _stores(db):
        live = '' if store == 'main' else ' AND retired_at IS NULL AND id NOT IN (SELECT id FROM main.item)'
        add([r[0] for r in db.execute(f'SELECT id FROM {store}.item WHERE born_key=? COLLATE NOCASE{kind_sql}{live} ORDER BY id', (number, *kind_args))], 'born')
    if has_catalogue(db):
        phrase = '"' + number.replace('"', '""') + '"'
        try:
            add([r[0] for r in db.execute(f'SELECT item_id FROM catalogue.item_fts WHERE keys MATCH ?{kind_sql} ORDER BY rank, item_id',
                                          (phrase, *kind_args))], 'search')
        except sqlite3.OperationalError:
            pass                                                # a number with no word in it (punctuation only) is not an FTS query
    for store in _stores(db):
        letter = (' AND provider_kind=?', (type_of_kind(kind),)) if kind else ('', ())
        live = '' if store == 'main' else ' AND item_id NOT IN (SELECT id FROM main.item)'
        add([r[0] for r in db.execute(f'''SELECT DISTINCT item_id FROM {store}.item_link
                                         WHERE provider='bricklink' AND provider_key=? COLLATE NOCASE AND status IN ({_IN}){letter[0]}{live}
                                         ORDER BY item_id''', (number, *CONFIRMED, *letter[1]))], 'bricklink')
    out = []
    for item_id, how in found.items():
        if len(out) >= limit:
            break
        row, _ = _row(db, item_id)
        if row is not None and (kind is None or row['kind'] == kind):
            out.append(dict(item_id=item_id, kind=row['kind'], name=row['name'], number=row['born_key'], matched_by=how))
    return out


def _merged_target(db, item_id):
    seen = set()
    while item_id not in seen:
        seen.add(item_id)
        row = db.execute('SELECT merged_into FROM main.item WHERE id=?', (item_id,)).fetchone()
        if row is None or row[0] is None:
            return item_id
        item_id = row[0]
    return item_id
