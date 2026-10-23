"""The optional BrickLink item lists (design 3.3, 3.5, 6.2, 6.6, decisions 3 and 8): the XML files of BrickLink's catalogue
download become `bricklink_item` (and `bricklink_color`) in a new catalogue file seeded from the current one.

What a loaded list does to the links and kinds (`apply_list`), in this order:
 1. undoes what an earlier list did (a link it upgraded goes back to `inferred/set_number`, its `same_number` candidates go),
    so the result depends on the list now loaded and not on the loads before it;
 2. corrects guessed kinds (zero-part sets, from the theme or the default `set`): a zero-part set whose number matches exactly one BrickLink type (S as it is; G, B, C, I with
    the trailing `-1` stripped; O and P/M never count) other than the guess gets that kind with `kind_source='bricklink'`, and below, its candidate;
 3. upgrades `inferred/set_number` links to `matched/bricklink_list` where the BrickLink item of that type and number exists;
 4. proposes `same_number` candidates, `to_check` and never `matched` (decision 8).
Loading a list never creates an item. The same step runs again on a re-download (`carry_lists`, a builder layer)."""
from collections import Counter
from contextlib import closing
import hashlib
import html
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import time
from xml.etree import ElementTree as ET

from ..core.size_search import name_key as size_key_of
from .connect import _uri, now as clock
from .errors import BrickLinkListError, CatalogueError
from .layers import FTS_INSERT, bl_digests
from .swap import build_lock, check_new, new_path, publish, recheck_merged, remove_new

TYPES = frozenset('SPMGBCIO')                                 # the eight BrickLink item types of the 3.3 loader's check
TYPE_OF_KIND = {'set': 'S', 'gear': 'G', 'book': 'B', 'catalog': 'C', 'instructions': 'I', 'box': 'O', 'part': 'P', 'minifigure': 'M'}
KIND_OF_TYPE = {t: k for k, t in TYPE_OF_KIND.items() if t in 'SGBCIO'}
ITEM_COLS = ('item_type', 'item_no', 'name', 'name_key', 'category', 'year', 'weight', 'dim_x', 'dim_y', 'dim_z', 'alt_item_ids',
             'size_key', 'build_id')
COLOR_COLS = ('id', 'name', 'rgb', 'type', 'build_id')
LINK_COLS = ('item_id', 'color_id', 'provider', 'provider_kind', 'provider_key', 'status', 'method', 'origin', 'preferred',
             'evidence_digest', 'build_id')
SAMPLE = 200                                                  # kind corrections listed in counts_json (the count is complete)


def _evidence(*fields):
    return hashlib.sha256('\x1f'.join(str(f) for f in fields).encode()).hexdigest()


def _text(element, tag):
    value = element.findtext(tag)
    value = ' '.join(html.unescape(html.unescape(value)).split()) if value is not None else ''
    return value or None


def _parse(name, data):
    """('items' | 'colours', rows) of one XML file's bytes, checked as the 3.3 loader checks it."""
    rows, kind = [], None
    try:
        context = ET.iterparse(io.BytesIO(data), events=('start', 'end'))
        _, root = next(context)
        if root.tag != 'CATALOG':
            raise BrickLinkListError(f'{name}: expected a CATALOG root')
        for event, element in context:
            if event != 'end' or element.tag != 'ITEM':
                continue
            this = 'items' if element.find('ITEMTYPE') is not None else 'colours' if element.find('COLOR') is not None else None
            if this is None or kind not in (None, this):
                raise BrickLinkListError(f'{name}: an entry is neither an item nor a colour, or the file mixes both')
            kind = this
            rows.append(_item(name, element) if this == 'items' else _colour(name, element))
            root.clear()                                       # clearing ITEM alone would keep every child alive
    except ET.ParseError as exc:
        raise BrickLinkListError(f'{name} is not well-formed XML: {exc}') from exc
    if kind is None:
        raise BrickLinkListError(f'{name} holds no items and no colours')
    return kind, rows


def _item(name, element):
    item_type, number = _text(element, 'ITEMTYPE'), _text(element, 'ITEMID')
    title = _text(element, 'ITEMNAME')
    if item_type not in TYPES or not number or not title:
        raise BrickLinkListError(f'{name}: invalid catalogue item')
    year = _text(element, 'YEARRELEASED') or _text(element, 'YEAR')          # an empty element is no year
    if year is not None and (not year.isdigit() or len(year) != 4):
        raise BrickLinkListError(f'{name}: invalid catalogue year {year!r}')
    return dict(item_type=item_type, item_no=number, name=title, name_key=' '.join(title.casefold().split()), category=_text(element, 'CATEGORY'),
                year=int(year) if year else None, weight=_text(element, 'ITEMWEIGHT'), dim_x=_text(element, 'ITEMDIMX'),
                dim_y=_text(element, 'ITEMDIMY'), dim_z=_text(element, 'ITEMDIMZ'), alt_item_ids=_text(element, 'ALTITEMIDS'),
                size_key=size_key_of(title))


def _colour(name, element):
    number, title = _text(element, 'COLOR'), _text(element, 'COLORNAME')
    if not number or not number.isdigit() or not title:
        raise BrickLinkListError(f'{name}: invalid colour entry')
    return dict(id=int(number), name=title, rgb=_text(element, 'COLORRGB'), type=_text(element, 'COLORTYPE'))


class Lists:
    """The `*.xml` files of one directory, read once: the bytes hashed are the bytes parsed. A file is an item list or a colour list."""

    def __init__(self, directory):
        directory = Path(directory)
        paths = sorted(p for p in directory.glob('*.xml') if not p.name.startswith('.')) if directory.is_dir() else []
        if not paths:
            raise BrickLinkListError(f'{directory} holds no BrickLink catalogue XML files')
        self.items, self.colours, self.item_files, self.colour_files = [], [], [], []
        for path in paths:
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise BrickLinkListError(f'{path.name} cannot be read: {exc}') from exc
            kind, rows = _parse(path.name, data)
            entry = dict(name=path.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), rows=len(rows))
            target, files = (self.items, self.item_files) if kind == 'items' else (self.colours, self.colour_files)
            target.extend(rows)
            files.append(entry)
        if not self.items:
            raise BrickLinkListError(f'{directory} holds no BrickLink item lists (colour files alone are not loaded)')
        seen = Counter((r['item_type'], r['item_no']) for r in self.items)
        dup = [k for k, n in seen.items() if n > 1]
        if dup:
            raise BrickLinkListError(f'the lists name {dup[0][0]} {dup[0][1]} more than once ({len(dup)} duplicates)')
        if {r['item_type'] for r in self.items} != TYPES:
            raise BrickLinkListError('catalogue must contain all eight item types '
                                     f"(found {''.join(sorted({r['item_type'] for r in self.items})) or 'none'})")
        ids = Counter(r['id'] for r in self.colours)
        if any(n > 1 for n in ids.values()):
            raise BrickLinkListError('the colour list names a colour more than once')


def import_bricklink(target, bricklink_dir, *, collection=None, app_version, now=None):
    """Build a new catalogue from the current `target` plus the BrickLink lists in `bricklink_dir`, check it and swap it in
    (`.prev` kept), under the same lock and swap as `builder.build`. Returns the report. `collection` (read-only) is rechecked
    for merges before the swap."""
    target = Path(target)
    if not target.is_file():
        raise CatalogueError(f'{target} does not exist; build the catalogue from a Rebrickable dump first')
    with build_lock(target):
        started = time.monotonic()
        lists = Lists(bricklink_dir)                          # a bad list is refused before any file is touched
        new = new_path(target)
        remove_new(new)
        try:
            report = _build_from_current(target, new, lists, app_version, now)
            if collection:
                recheck_merged(new, collection)
            report['seconds'] = round(time.monotonic() - started, 1)
        except BaseException:
            remove_new(new)
            raise
        publish(new, target, keep_previous=True)
        report.update(target=str(target), previous=str(target.with_name(target.name + '.prev')), bytes=target.stat().st_size)
        return report


def _stamp(now):
    return now() if callable(now) else (now or clock())


def _build_from_current(target, new, lists, app_version, now):
    started_at = _stamp(now)
    with closing(sqlite3.connect(_uri(target, 'ro'), uri=True)) as src, closing(sqlite3.connect(new)) as dst:
        try:
            meta = dict(src.execute('SELECT key, value FROM meta').fetchall())
        except sqlite3.DatabaseError as exc:
            raise CatalogueError(f'{target} cannot be read as a catalogue: {exc}') from exc
        src.backup(dst)                                       # one consistent snapshot of the current file
    db = sqlite3.connect(new)
    db.row_factory = sqlite3.Row
    db.isolation_level = None
    try:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('PRAGMA synchronous=OFF')
        db.execute('BEGIN')
        build_id = db.execute('SELECT max(id) FROM build').fetchone()[0] + 1
        db.execute('DELETE FROM bricklink_item')
        list_build = build_id
        db.execute('INSERT INTO build(id, kind, seeded_from, started_at, app_version, files_json, counts_json) VALUES(?, ?, ?, ?, ?, ?, ?)',
                   (build_id, 'bricklink_list', 'catalogue', started_at, app_version, json.dumps(lists.item_files), '{}'))
        _insert(db, 'bricklink_item', ITEM_COLS, [dict(r, build_id=build_id) for r in lists.items])
        counts = dict(items=len(lists.items), by_type=dict(sorted(Counter(r['item_type'] for r in lists.items).items())))
        if lists.colours:
            colour_build = build_id + 1
            db.execute('DELETE FROM bricklink_color')
            db.execute('INSERT INTO build(id, kind, seeded_from, started_at, app_version, files_json, counts_json) VALUES(?, ?, ?, ?, ?, ?, ?)',
                       (colour_build, 'bricklink_colors', 'catalogue', started_at, app_version, json.dumps(lists.colour_files),
                        json.dumps(dict(colours=len(lists.colours)))))
            _insert(db, 'bricklink_color', COLOR_COLS, [dict(r, build_id=colour_build) for r in lists.colours])
            counts['colours'] = len(lists.colours)
        touched = set()
        counts.update(apply_list(db, list_build, touched))
        _refresh_fts(db, touched)
        counts['bl_digest'] = _recompute_digests(db)
        db.execute('UPDATE build SET counts_json=?, finished_at=? WHERE id=?', (json.dumps(counts, sort_keys=True), _stamp(now), build_id))
        db.execute('COMMIT')
        check_new(db)
    finally:
        db.close()
    return dict(build_id=build_id, catalogue_id=meta.get('catalogue_id'), counts=counts, files=lists.item_files + lists.colour_files)


def _recompute_digests(db):
    """inventory.bl_digest again through the builder's own function, since a corrected set loses its inferred S link and a bundle
    that holds it must not keep a digest that hashes it. A digest that was NULL stays NULL: the import adds no link that counts."""
    before = db.execute('SELECT count(bl_digest), count(*) FROM inventory').fetchone()
    ctx = SimpleNamespace(color_ids=dict(db.execute('SELECT born_key, id FROM color')), report={},
                          incomplete_inventories={r[0] for r in db.execute('SELECT id FROM inventory WHERE bl_digest IS NULL')})
    bl_digests(db, ctx)
    return dict(ctx.report['bl_digest'], with_digest_before=before[0], inventories=before[1])


def _insert(db, table, cols, rows):
    db.executemany(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join(':' + c for c in cols)})", rows)


def carry_lists(db, ctx):
    """Builder layer (re-download, design 6.2): copy the BrickLink list tables of the file being replaced, then apply the list
    to the fresh links, so a re-download loses nothing a loaded list established. Their `build` rows are carried with the history."""
    if ctx.old is None:
        return
    src = ctx.old.db
    for table, cols in (('bricklink_item', ITEM_COLS), ('bricklink_color', COLOR_COLS)):
        cursor = src.execute(f"SELECT {','.join(cols)} FROM {table}")
        while rows := cursor.fetchmany(20000):
            db.executemany(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [tuple(r) for r in rows])
    list_build = db.execute('SELECT max(build_id) FROM bricklink_item').fetchone()[0]
    if list_build is None:
        return
    ctx.report['bricklink_list'] = apply_list(db, list_build)


def apply_list(db, list_build, touched=None):
    """Apply the loaded `bricklink_item` rows to the items and links of the file (see the module doc). Returns counts; the ids of
    items whose FTS row changes are added to `touched` when given."""
    touched = set() if touched is None else touched
    report = {}
    # 1. undo an earlier list
    reverted = db.execute("SELECT id, provider_key FROM item_link WHERE method='bricklink_list' AND origin='bricklink_list' AND status='matched'").fetchall()
    for link_id, key in reverted:
        db.execute("UPDATE item_link SET status='inferred', method='set_number', origin='rule', evidence_digest=? WHERE id=?",
                   (_evidence('set_number', key), link_id))
    touched.update(r[0] for r in db.execute("DELETE FROM item_link WHERE method='same_number' RETURNING item_id"))
    # 2. kind corrections: zero-part sets whose kind is a guess, from the theme or (no theme row) the default `set`
    listed = {(r[0], r[1]) for r in db.execute('SELECT item_type, item_no FROM bricklink_item')}   # the type and number pairs, one pass
    corrected, ambiguous = [], 0
    for item_id, kind, key in db.execute("""SELECT id, kind, born_key FROM item WHERE born_namespace='sets' AND retired_at IS NULL AND num_parts=0
                                            AND (kind_source='theme' OR (kind_source='namespace' AND kind='set')) ORDER BY id""").fetchall():
        found = zero_part_matches(key, listed)
        if not found or {t for t, _ in found} == {TYPE_OF_KIND[kind]}:
            continue                                          # not listed, or BrickLink says what the guess says
        if len(found) > 1:
            ambiguous += 1                                    # the guess and another type, or several others: no answer is better than another
            continue
        new_kind = KIND_OF_TYPE[next(iter(found))[0]]
        db.execute("UPDATE item SET kind=?, kind_source='bricklink' WHERE id=?", (new_kind, item_id))
        # a set leaving `set` must not keep the set-number rule's inferred S link (the builder's rule skips it on a re-download)
        db.execute("DELETE FROM item_link WHERE item_id=? AND provider='bricklink' AND status='inferred' AND method='set_number'", (item_id,))
        corrected.append(dict(item_id=item_id, born_key=key, was=kind, kind=new_kind))
        touched.add(item_id)
    report.update(kinds_corrected=len(corrected), kinds_ambiguous=ambiguous, kinds_corrected_sample=corrected[:SAMPLE])
    # 3. upgrades: inferred/set_number where the BrickLink item exists
    rows = db.execute("""SELECT l.id, l.provider_kind, l.provider_key FROM item_link l
                         WHERE l.provider='bricklink' AND l.status='inferred' AND l.method='set_number'
                           AND EXISTS(SELECT 1 FROM bricklink_item b WHERE b.item_type=l.provider_kind AND b.item_no=l.provider_key)""").fetchall()
    db.executemany("UPDATE item_link SET status='matched', method='bricklink_list', origin='bricklink_list', evidence_digest=?, build_id=? WHERE id=?",
                   [(_evidence('bricklink_list', kind, key), list_build, link_id) for link_id, kind, key in rows])
    report['links_upgraded'] = len(rows)
    report['set_links_unconfirmed'] = db.execute("SELECT count(*) FROM item_link WHERE provider='bricklink' AND status='inferred' AND method='set_number'").fetchone()[0]
    # 4. same_number candidates (decision 8): to_check, never matched
    linked = {r[0] for r in db.execute("SELECT DISTINCT item_id FROM item_link WHERE provider='bricklink'")}
    candidates = []
    for item_id, kind, namespace, key in db.execute('SELECT id, kind, born_namespace, born_key FROM item WHERE retired_at IS NULL ORDER BY id'):
        if item_id in linked:
            continue
        item_type = TYPE_OF_KIND[kind]
        number = same_number_key(item_type, namespace, key)
        if number is not None and (item_type, number) in listed:
            candidates.append((item_id, item_type, number))
    _insert(db, 'item_link', LINK_COLS, [dict(item_id=i, color_id=None, provider='bricklink', provider_kind=t, provider_key=k, status='to_check',
                                              method='same_number', origin='bricklink_list', preferred=0,
                                              evidence_digest=_evidence('same_number', t, k), build_id=list_build) for i, t, k in candidates])
    touched.update(i for i, _, _ in candidates)
    report['same_number'] = len(candidates)
    return report


def same_number_key(item_type, namespace, born_key):
    """The BrickLink number a Rebrickable key stands for under `item_type`, or None. BrickLink numbers gear, books, catalogs and
    instructions without Rebrickable's `-1` set suffix (only `-1`, never `-2`); sets, parts and figures keep the key as it is."""
    if namespace == 'sets' and item_type in 'GBCI':
        return born_key[:-2] if born_key.endswith('-1') and len(born_key) > 2 else None
    return born_key


def zero_part_matches(born_key, listed):
    """{(type, listed number)} a zero-part set's key matches in the list: S as it is, G/B/C/I with `-1` stripped. Boxes (O) never
    compete (BrickLink lists every set as a box too) and parts and figures are never candidates for a set."""
    found = {(t, n) for t in 'SGBCI' if (n := same_number_key(t, 'sets', born_key)) is not None and (t, n) in listed}
    return found


def _refresh_fts(db, touched):
    """Rebuild the FTS rows. item_fts has no index on item_id, so a row-by-row delete would scan it each time: one bulk rebuild."""
    if touched:
        db.execute('DELETE FROM item_fts')
        db.execute(FTS_INSERT)
