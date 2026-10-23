"""The catalogue builder (design 3.1, 3.5, 6.1, 6.2): Rebrickable dump + seeds -> catalogue.db, built beside and swapped in.

M.2a loads the raw tables, ids, retired rows, kinds, build history and FTS. M.2b adds the mapping layers through LAYERS
(item_link / color_link rows, `bl_digest`, link keys in the FTS); nothing here writes the collection file."""
from collections import defaultdict
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from ..core.size_search import name_key as size_key_of
from .connect import _uri, create_catalogue, now as clock
from .dump import Dump
from .errors import BuildBusy, CatalogueMismatch, DumpError
from .layers import DEFAULT_LAYERS, shipped_version
from .mappings import MAPPINGS_DIR, read_mapping
from .seeds import FIXED_COLORS, LOCAL_BASE, CollectionSeed, OldCatalogue, Seeds

ITEM_COLS = ('id', 'kind', 'kind_source', 'name', 'name_key', 'size_key', 'year', 'num_parts', 'theme_id', 'category_id', 'material',
             'img_url', 'born_provider', 'born_namespace', 'born_key', 'adopted', 'build_id', 'digest', 'retired_at')
COLOR_COLS = ('id', 'name', 'rgb', 'is_trans', 'born_provider', 'born_key', 'build_id', 'retired_at')
BUILD_COLS = ('id', 'kind', 'seeded_from', 'started_at', 'finished_at', 'app_version', 'mapping_version', 'files_json', 'counts_json',
              'job_id', 'note')
NAMESPACE_KIND = {'sets': 'set', 'parts': 'part', 'minifigs': 'minifigure'}
BUILD_KINDS = ('rebrickable_dump', 'mapping', 'bricklink_list', 'bricklink_colors')
LAYERS = list(DEFAULT_LAYERS)   # callables layer(db, ctx), run after the raw tables are loaded; M.2d adds the BrickLink lists


class Context:
    """What a mapping layer needs after the raw tables are loaded."""

    def __init__(self, build_id, item_ids, color_ids, retired, *, parts=(), set_ids=(), incomplete_inventories=(),
                 mappings_dir=MAPPINGS_DIR, local_dir=None):
        self.build_id, self.item_ids, self.color_ids, self.retired = build_id, item_ids, color_ids, retired   # every row of the new file
        self.parts = list(parts)                              # (part_num, name) of every part in the file, retired too: the leg rule's input
        self.part_num = {i: k[1] for k, i in self.item_ids.items() if k[0] == 'parts'}
        self.set_ids = list(set_ids)                          # (set_num, id) of items of kind 'set', retired too: the set-number rule's input
        self.incomplete_inventories = set(incomplete_inventories)   # new inventory ids that lost a dump line: no bl_digest
        self.mappings_dir, self.local_dir = Path(mappings_dir), Path(local_dir) if local_dir else None
        self.report = {}                                      # what the layers add to counts_json


def _digest(fields):
    return hashlib.sha256('\x1f'.join(fields).encode()).hexdigest()


def _name_key(name):
    return ' '.join(name.casefold().split())


def _sort_color_key(key):
    try:
        return (0, int(key), key)
    except ValueError:
        return (1, 0, key)


def _fsync(path, directory=False):
    fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if directory else 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _stamp(now):
    return now() if callable(now) else (now or clock())


def theme_kinds(mappings_dir=MAPPINGS_DIR):
    """{rb theme id: kind} from the shipped theme_kinds.csv."""
    _, rows = read_mapping(Path(mappings_dir) / 'theme_kinds.csv')
    return {int(r['rb_theme_id']): r['kind'] for r in rows}


def _kind_of_theme(theme_id, parents, kinds):
    """The kind a zero-part set's theme gives: its own row, else the nearest ancestor's, else None."""
    seen = set()
    while theme_id is not None and theme_id not in seen:
        if theme_id in kinds:
            return kinds[theme_id]
        seen.add(theme_id)
        theme_id = parents.get(theme_id)
    return None


def _collection_item_row(row, build_id, retired_at):
    """A retired item known only from the collection: its own fields, no theme or category."""
    ns = row['born_namespace']
    kind, source = row['kind'], row['kind_source']
    if ns != 'sets':
        kind, source = NAMESPACE_KIND[ns], 'namespace'
    elif source not in ('namespace', 'theme', 'bricklink'):
        source = 'bricklink'                 # 'manual' is a person's decision; the closest catalogue word is a correction
    if source == 'namespace':
        kind = NAMESPACE_KIND[ns]
    digest = row['digest'] or _digest([ns, row['born_key'], row['name'], str(row['year']), str(row['num_parts'])])
    return dict(id=row['id'], kind=kind, kind_source=source, name=row['name'], name_key=_name_key(row['name']),
                size_key=size_key_of(row['name']), year=row['year'], num_parts=row['num_parts'], theme_id=None, category_id=None,
                material=None, img_url=None, born_provider='rebrickable', born_namespace=ns, born_key=row['born_key'],
                adopted=int(row['id'] >= LOCAL_BASE), build_id=build_id, digest=digest, retired_at=retired_at)


def _collection_color_row(row, build_id, retired_at):
    return dict(id=row['id'], name=row['name'], rgb=row['rgb'], is_trans=row['is_trans'], born_provider='rebrickable',
                born_key=row['born_key'], build_id=build_id, retired_at=retired_at)


def _insert(db, table, cols, rows):
    db.executemany(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join(':' + c for c in cols)})", rows)


def build(dump_dir, target, *, collection=None, app_version, now=None, mappings_dir=MAPPINGS_DIR, local_dir=None):
    """Build `target` (normally catalogue.db) from a Rebrickable dump directory and return the report dict.

    Seeds ids by born key from the existing `target` (the file being replaced) and from `collection` (read-only). The new
    file is built as `<target>.new`, checked, and swapped in; the replaced file stays as `<target>.prev`.

    `mappings_dir` holds the shipped mapping files; `local_dir` (optional, data/mappings/) the install's own layer."""
    target = Path(target)
    lock = open(target.with_name(target.name + '.lock'), 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise BuildBusy(f'another catalogue build is running on {target}; nothing was touched') from None
    try:
        return _build_locked(dump_dir, target, collection, app_version, now, mappings_dir, local_dir)
    finally:
        lock.close()                                          # closing releases the flock


def _build_locked(dump_dir, target, collection, app_version, now, mappings_dir, local_dir):
    new, prev = target.with_name(target.name + '.new'), target.with_name(target.name + '.prev')
    started = time.monotonic()
    started_at = _stamp(now)
    dump = Dump(dump_dir)
    old = OldCatalogue(target) if target.exists() else None
    try:
        coll = CollectionSeed(collection) if collection else None
        seeds = Seeds(old, coll)
        for p in (new, new.with_name(new.name + '-journal')):
            p.unlink(missing_ok=True)
        try:
            try:
                report = _build_new(dump, new, old, coll, seeds, app_version, started_at, now, mappings_dir, local_dir)
            except ValueError as exc:
                raise DumpError(f'the dump holds a value the builder cannot read: {exc}') from exc
            if coll:
                _recheck_merged(new, collection)
            report['seconds'] = round(time.monotonic() - started, 1)
        except BaseException:
            for p in (new, new.with_name(new.name + '-journal')):
                p.unlink(missing_ok=True)
            raise
        _fsync(new)
        if old:
            # .prev is a hard link of the target, so the target stays in place until the one rename that publishes the new file.
            link = target.with_name(f'{target.name}.prev.{uuid.uuid4().hex}')
            os.link(target, link)
            os.replace(link, prev)
        os.replace(new, target)
        _fsync(target.parent, directory=True)
    finally:
        if old:
            old.close()
    report.update(target=str(target), previous=str(prev) if old else None, bytes=target.stat().st_size)
    return report


def _recheck_merged(new, collection):
    """Refuse to publish when the collection merged away an id that the new file has live: a merge committed while the build
    ran (the build lock keeps out other builders only). Invariant 4: no catalogue row ever names a merged id."""
    with closing(sqlite3.connect(_uri(collection, 'ro'), uri=True)) as db:
        merged = [r[0] for r in db.execute('SELECT id FROM item WHERE merged_into IS NOT NULL')]
    if not merged:
        return
    with closing(sqlite3.connect(_uri(new, 'ro'), uri=True)) as db:
        db.execute('CREATE TEMP TABLE merged(id INTEGER PRIMARY KEY)')
        db.executemany('INSERT INTO temp.merged VALUES(?)', [(i,) for i in merged])
        live = [r[0] for r in db.execute('SELECT id FROM main.item WHERE retired_at IS NULL AND id IN (SELECT id FROM temp.merged) ORDER BY id')]
    if live:
        raise CatalogueMismatch(f'items {live[:5]} were merged in the collection while the catalogue was being built; run the build again')


def _build_new(dump, new, old, coll, seeds, app_version, started_at, now, mappings_dir, local_dir):
    db = create_catalogue(new)
    db.isolation_level = None
    try:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('PRAGMA synchronous=OFF')
        db.execute('BEGIN')
        report = _load(db, dump, old, coll, seeds, app_version, started_at, now, mappings_dir, local_dir)
        db.execute('COMMIT')
        db.execute('PRAGMA foreign_keys=ON')
        found = db.execute('PRAGMA foreign_key_check').fetchall()
        if found:
            raise CatalogueMismatch(f'the new catalogue breaks foreign keys: {[tuple(r) for r in found[:5]]} ({len(found)} in all)')
        verdict = db.execute('PRAGMA integrity_check').fetchall()
        if [tuple(r) for r in verdict] != [('ok',)]:
            raise CatalogueMismatch(f'the new catalogue fails its integrity check: {[tuple(r) for r in verdict[:5]]}')
        if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
            raise CatalogueMismatch('the new catalogue could not be set to journal_mode=DELETE')
        return report
    finally:
        db.close()


def _load(db, dump, old, coll, seeds, app_version, started_at, now, mappings_dir, local_dir):
    # ---- build history ----
    build_rows = [dict(r) for r in old.builds] if old else []
    if coll:
        have = {b['id'] for b in build_rows}
        for b in coll.builds:
            if b['id'] in have:
                continue
            build_rows.append(dict(id=b['id'], kind=b['kind'] if b['kind'] in BUILD_KINDS else 'rebrickable_dump', seeded_from=None,
                                   started_at=b['activated_at'], finished_at=b['activated_at'], app_version='unknown',
                                   mapping_version=b['mapping_version'], files_json='[]', counts_json='{}', job_id=None,
                                   note='placeholder: the catalogue lacks this build; the collection activated it'))
    build_id = max([b['id'] for b in build_rows] or [0]) + 1
    seeded_from = 'catalogue' if old else ('collection' if coll else 'none')
    known_builds = {b['id'] for b in build_rows}
    retired_at_default = started_at

    # ---- themes and part categories ----
    kinds = theme_kinds(mappings_dir)
    themes = {}
    for r in dump.rows('themes'):
        themes[int(r[0])] = dict(id=int(r[0]), name=r[1], parent_id=int(r[2]) if r[2] else None, item_kind=kinds.get(int(r[0])),
                                 build_id=build_id, retired_at=None)
    categories = {int(r[0]): dict(id=int(r[0]), name=r[1], build_id=build_id, retired_at=None) for r in dump.rows('part_categories')}
    carried_themes = carried_categories = 0
    for src, dst in ((old.themes if old else {}, themes), (old.categories if old else {}, categories)):
        for id_, row in src.items():
            if id_ not in dst:
                dst[id_] = dict(row, retired_at=row['retired_at'] or retired_at_default)
                if dst is themes:
                    carried_themes += 1
                else:
                    carried_categories += 1
    parents = {i: t['parent_id'] for i, t in themes.items()}

    # ---- colours ----
    colors = {}
    dump_colors = sorted(dump.rows('colors'), key=lambda r: _sort_color_key(r[0]))
    dump_color_keys = {r[0] for r in dump_colors}
    next_color = seeds.color_hw
    new_colors = 0
    for r in dump_colors:
        key = r[0]
        id_ = seeds.colors.id_of(key)
        if id_ is None:
            next_color += 1
            id_ = next_color
            seeds.colors.add(key, id_, 'build')
            new_colors += 1
        colors[key] = dict(id=id_, name=r[1], rgb=r[2] or None, is_trans=int(r[3] == 'True'), born_provider='rebrickable',
                           born_key=key, build_id=build_id, retired_at=None)
    retired_colors = 0
    old_colors = old.colors if old else {}
    coll_colors = {c['born_key']: c for c in (coll.colors if coll else []) if c['origin'] == 'catalogue'}
    for key in seeds.colors.by_key:
        if key in colors:
            continue
        if key in old_colors:
            colors[key] = dict(old_colors[key], retired_at=old_colors[key]['retired_at'] or retired_at_default)
        elif key in coll_colors:
            colors[key] = _collection_color_row(coll_colors[key], build_id, retired_at_default)
        else:
            continue                                          # a fixed id (1, 2) that no source has a row for
        retired_colors += 1
    color_ids = {k: c['id'] for k, c in colors.items()}
    live_color_ids = {k: color_ids[k] for k in dump_color_keys}

    # ---- items ----
    override = {}
    for key, row in (old.items if old else {}).items():
        if row['kind_source'] == 'bricklink' and key[0] == 'sets':
            override[key] = (row['kind'], 'bricklink')
    for row in (coll.items if coll else []):                  # a correction only the collection holds (an older catalogue restored)
        key = (row['born_namespace'], row['born_key'])
        if row['origin'] == 'catalogue' and row['kind_source'] == 'bricklink' and key[0] == 'sets' and key not in override:
            override[key] = (row['kind'], 'bricklink')
    items, dump_keys = {}, set()
    zero_part = 0
    pending = []                                              # (namespace, key, built row without id)
    for r in sorted(dump.rows('sets')):
        key = ('sets', r[0])
        np = int(r[4])
        if key in override:
            kind, source = override[key]
        elif np > 0:
            kind, source = 'set', 'namespace'
        else:
            zero_part += 1
            guess = _kind_of_theme(int(r[3]), parents, kinds)
            kind, source = (guess, 'theme') if guess else ('set', 'namespace')
        pending.append((key, dict(kind=kind, kind_source=source, name=r[1], year=int(r[2]), num_parts=np, theme_id=int(r[3]),
                                  category_id=None, material=None, img_url=r[5] or None, digest=_digest(r))))
    for r in sorted(dump.rows('parts')):
        pending.append((('parts', r[0]), dict(kind='part', kind_source='namespace', name=r[1], year=None, num_parts=None, theme_id=None,
                                             category_id=int(r[2]), material=r[3] or None, img_url=None, digest=_digest(r))))
    for r in sorted(dump.rows('minifigs')):
        pending.append((('minifigs', r[0]), dict(kind='minifigure', kind_source='namespace', name=r[1], year=None, num_parts=int(r[2]),
                                                theme_id=None, category_id=None, material=None, img_url=r[3] or None, digest=_digest(r))))
    next_item = seeds.item_hw
    adopted = new_items = 0
    for key, fields in pending:
        dump_keys.add(key)
        id_ = seeds.items.id_of(key)
        returning = key in seeds.merged_catalogue and key not in seeds.replacement
        if returning:
            id_ = None                                # no catalogue row names a merged id (design 3.6, invariant 4): a fresh id
            next_item += 1
            fresh = next_item
            new_items += 1
        elif id_ is None and key in seeds.adoptable:
            id_ = seeds.adoptable[key]
            seeds.items.add(key, id_, 'collection (adopted)')
        if returning:
            id_ = fresh
        elif id_ is None:
            next_item += 1
            id_ = next_item
            seeds.items.add(key, id_, 'build')
            new_items += 1
        if id_ >= LOCAL_BASE:
            adopted += 1
        items[key] = dict(fields, id=id_, name_key=_name_key(fields['name']), size_key=size_key_of(fields['name']),
                          born_provider='rebrickable', born_namespace=key[0], born_key=key[1], adopted=int(id_ >= LOCAL_BASE),
                          build_id=build_id, retired_at=None)
    live_items = len(items)
    retired_items = 0
    old_items = old.items if old else {}
    coll_items = {(r['born_namespace'], r['born_key']): r for r in (coll.items if coll else []) if r['origin'] == 'catalogue'}
    for key, (id_, _src) in seeds.items.by_key.items():
        if key in items:
            continue
        if key in old_items:
            row = old_items[key]
            items[key] = dict(row, id=id_, retired_at=row['retired_at'] or retired_at_default)
        elif key in coll_items:
            row = coll_items[key]
            kept = row['catalogue_build_id'] if row['catalogue_build_id'] in known_builds else build_id
            items[key] = _collection_item_row(row, kept, row['catalogue_retired_at'] or retired_at_default)
        else:
            continue                                          # an adopted key the dump did not have is not a catalogue row
        retired_items += 1
    # An id merged away in the collection is no seed, but when its key also left the dump the old file's row is carried
    # retired under that id (a retired row may name a merged id; only live rows may not), so its carried inventories keep a parent.
    for key, row in old_items.items():
        if key not in items and row['id'] in seeds.merged_ids:
            items[key] = dict(row, retired_at=row['retired_at'] or retired_at_default)
            retired_items += 1
    item_ids = {k: i['id'] for k, i in items.items()}
    live_ids = {k: item_ids[k] for k in dump_keys}

    # ---- inventories ----
    parent_of = {k[1]: i for k, i in live_ids.items() if k[0] in ('sets', 'minifigs')}
    by_parent = defaultdict(list)
    for r in dump.rows('inventories'):
        if r[2] in parent_of:
            by_parent[parent_of[r[2]]].append((int(r[1]), int(r[0])))
    rb_to_new, inv_rows, live_keys = {}, [], set()
    inv_id = 0
    for parent in sorted(by_parent):
        versions = sorted(by_parent[parent])
        for ordinal, (version, rb_id) in enumerate(versions, 1):
            inv_id += 1
            rb_to_new[rb_id] = inv_id
            live_keys.add((parent, version))
            inv_rows.append(dict(id=inv_id, item_id=parent, version=version, ordinal=ordinal, is_latest=int(ordinal == len(versions)),
                                 rb_inventory_id=rb_id, build_id=build_id, digest=None, bl_digest=None, part_lines=0, figure_lines=0,
                                 set_lines=0, retired_at=None))
    skipped = defaultdict(int)
    incomplete = set()                                        # live inventories that lost a line to a missing item or colour
    lines = {}
    pictures = {}
    for r in dump.rows('inventory_parts'):
        inv, part, col = rb_to_new.get(int(r[0])), live_ids.get(('parts', r[1])), live_color_ids.get(r[2])
        if inv is None or part is None or col is None:
            skipped['inventory_parts'] += 1
            if inv is not None:
                incomplete.add(inv)
            continue
        k = (inv, part, col, int(r[4] == 'True'))
        lines[k] = lines.get(k, 0) + int(r[3])
        if r[5]:
            pictures.setdefault((part, col), r[5])
    fig_lines, set_lines = {}, {}
    for name, ns, target_lines in (('inventory_minifigs', 'minifigs', fig_lines), ('inventory_sets', 'sets', set_lines)):
        for r in dump.rows(name):
            inv, item = rb_to_new.get(int(r[0])), live_ids.get((ns, r[1]))
            if inv is None or item is None:
                skipped[name] += 1
                if inv is not None:
                    incomplete.add(inv)
                continue
            target_lines[(inv, item)] = target_lines.get((inv, item), 0) + int(r[2])
    per = defaultdict(list)
    for (i, p, c, s), q in lines.items():
        per[i].append(('p', p, c, s, q))
    for (i, f), q in fig_lines.items():
        per[i].append(('f', f, 0, 0, q))
    for (i, s), q in set_lines.items():
        per[i].append(('s', s, 0, 0, q))
    for row in inv_rows:
        ls = sorted(per.get(row['id'], []))
        row['digest'] = hashlib.sha256(repr(ls).encode()).hexdigest()
        for tag, col in (('p', 'part_lines'), ('f', 'figure_lines'), ('s', 'set_lines')):
            row[col] = sum(1 for l in ls if l[0] == tag)
    latest_live = {r['item_id'] for r in inv_rows if r['is_latest']}
    carried = []                                              # vanished versions of the old file, with their lines
    # A key whose id changed (a merged id, catalogue or adopted local, came back under a fresh id): what the old file said
    # about that key now names the new id. Merged catalogue ids the old file no longer holds are re-pointed as well.
    remap = {v[0]: item_ids[k] for k, v in seeds.merged_catalogue.items() if k in dump_keys}
    remap.update({row['id']: item_ids[k] for k, row in old_items.items() if k in dump_keys and row['id'] != item_ids[k]})
    for (old_item, version), row in sorted((old.inventories if old else {}).items()):
        item_id = remap.get(old_item, old_item)
        if (item_id, version) in live_keys:
            continue
        inv_id += 1
        pl, fl, sl = old.lines(row['id'])
        pl = [(remap.get(i, i), *rest) for i, *rest in pl]
        fl = [(remap.get(i, i), q) for i, q in fl]
        sl = [(remap.get(i, i), q) for i, q in sl]
        digest = hashlib.sha256(repr(sorted([('p', *l) for l in pl] + [('f', i, 0, 0, q) for i, q in fl]
                                            + [('s', i, 0, 0, q) for i, q in sl])).encode()).hexdigest()
        carried.append((dict(row, id=inv_id, item_id=item_id, digest=digest,
                             is_latest=int(bool(row['is_latest']) and item_id not in latest_live),
                             retired_at=row['retired_at'] or retired_at_default), pl, fl, sl))
    retired_inventories = len(carried)
    per_item = defaultdict(list)                              # ordinals run over every version in the file, live and carried
    for row in inv_rows + [c[0] for c in carried]:
        per_item[row['item_id']].append(row)
    for versions in per_item.values():
        for ordinal, row in enumerate(sorted(versions, key=lambda r: r['version']), 1):
            row['ordinal'] = ordinal

    # ---- elements and relationships ----
    elements = []
    for r in dump.rows('elements'):
        p, c = live_ids.get(('parts', r[1])), live_color_ids.get(r[2])
        if p is None or c is None:
            skipped['elements'] += 1
            continue
        elements.append((r[0], p, c, r[3] or None))
    relations = set()
    for r in dump.rows('part_relationships'):
        c, p = live_ids.get(('parts', r[1])), live_ids.get(('parts', r[2]))
        if c is None or p is None:
            skipped['part_relationships'] += 1
            continue
        relations.add((r[0], c, p))

    # ---- write ----
    counts = dict(
        items=len(items), live_items=live_items, sets=sum(1 for k in dump_keys if k[0] == 'sets'),
        parts=sum(1 for k in dump_keys if k[0] == 'parts'), minifigs=sum(1 for k in dump_keys if k[0] == 'minifigs'),
        zero_part_sets=zero_part, colours=len(colors), inventories=len(inv_rows) + len(carried), lines=len(lines) + len(fig_lines) + len(set_lines),
        part_lines=len(lines), figure_lines=len(fig_lines), set_lines=len(set_lines), elements=len(elements),
        relationships=len(relations), pictures=len(pictures), themes=len(themes), part_categories=len(categories),
        retired=retired_items, retired_items=retired_items, retired_colours=retired_colors, retired_inventories=retired_inventories,
        retired_themes=carried_themes, retired_part_categories=carried_categories, adopted=adopted, new=new_items,
        new_items=new_items, new_colours=new_colors, skipped=dict(skipped),
        merged_local=[dict(namespace=k[0], born_key=k[1], local_id=v, catalogue_id=item_ids[k])
                      for k, v in sorted(seeds.merged_local.items()) if k in dump_keys],
        merged_returning=[dict(namespace=k[0], born_key=k[1], merged_id=v[0], merged_into=v[1], new_id=item_ids[k])
                          for k, v in sorted(seeds.merged_catalogue.items()) if k in dump_keys],
        shadowed_local=[dict(namespace=k[0], born_key=k[1], local_id=v, catalogue_id=seeds.items.id_of(k))
                        for k, v in sorted(seeds.shadowed.items())])
    catalogue_id = seeds.catalogue_id or str(uuid.uuid4())
    item_hw = max(seeds.item_hw, next_item)
    color_hw = max(seeds.color_hw, next_color)
    finished_at = _stamp(now)
    # The build row goes in last in the dump's terms (its files are all read), but before everything that references it.
    _insert(db, 'build', BUILD_COLS, build_rows + [dict(
        id=build_id, kind='rebrickable_dump', seeded_from=seeded_from, started_at=started_at, finished_at=finished_at,
        app_version=app_version, mapping_version=None, files_json=json.dumps(dump.files()), counts_json=json.dumps(counts),
        job_id=None, note=None)])
    _insert(db, 'theme', ('id', 'name', 'parent_id', 'item_kind', 'build_id', 'retired_at'), themes.values())
    _insert(db, 'part_category', ('id', 'name', 'build_id', 'retired_at'), categories.values())
    _insert(db, 'color', COLOR_COLS, colors.values())
    _insert(db, 'item', ITEM_COLS, items.values())
    inv_cols = ('id', 'item_id', 'version', 'ordinal', 'is_latest', 'rb_inventory_id', 'build_id', 'digest', 'bl_digest', 'part_lines',
                'figure_lines', 'set_lines', 'retired_at')
    _insert(db, 'inventory', inv_cols, inv_rows + [c[0] for c in carried])
    db.executemany('INSERT INTO inventory_part VALUES(?,?,?,?,?)', sorted((i, p, c, s, q) for (i, p, c, s), q in lines.items()))
    db.executemany('INSERT INTO inventory_figure VALUES(?,?,?)', sorted((i, f, q) for (i, f), q in fig_lines.items()))
    db.executemany('INSERT INTO inventory_set VALUES(?,?,?)', sorted((i, s, q) for (i, s), q in set_lines.items()))
    for row, pl, fl, sl in carried:
        db.executemany('INSERT INTO inventory_part VALUES(?,?,?,?,?)', [(row['id'], p, c, s, q) for p, c, s, q in pl])
        db.executemany('INSERT INTO inventory_figure VALUES(?,?,?)', [(row['id'], f, q) for f, q in fl])
        db.executemany('INSERT INTO inventory_set VALUES(?,?,?)', [(row['id'], s, q) for s, q in sl])
    db.executemany('INSERT INTO element VALUES(?,?,?,?)', sorted(elements))
    db.executemany('INSERT INTO part_relationship VALUES(?,?,?)', sorted(relations))
    db.executemany('INSERT INTO picture_url VALUES(?,?,?)', sorted((p, c, u) for (p, c), u in pictures.items()))
    ctx = Context(build_id, item_ids, color_ids, {k for k, i in items.items() if i['retired_at']}, parts=[(k[1], items[k]['name']) for k in item_ids if k[0] == 'parts'],
                  set_ids=[(k[1], i) for k, i in item_ids.items() if k[0] == 'sets' and items[k]['kind'] == 'set'],
                  # A carried version the old file gave no bl_digest stays without one: the file keeps no record of why (a
                  # line lost to a missing item, or an unmapped one), and its lines may be truncated, so never risk a false match.
                  incomplete_inventories=incomplete | {row['id'] for row, *_ in carried if row.get('bl_digest') is None},
                  mappings_dir=mappings_dir, local_dir=local_dir)
    for layer in LAYERS:
        layer(db, ctx)
    if ctx.report:
        counts.update(ctx.report)
        mapping_version = shipped_version(ctx.mappings_dir)
        db.execute('UPDATE build SET counts_json=?, mapping_version=? WHERE id=?', (json.dumps(counts), mapping_version, build_id))
    # keys: the born key plus every linked provider key (all statuses: a to_check candidate is searchable too)
    db.execute("""INSERT INTO item_fts(item_id, kind, name, keys)
                  SELECT i.id, i.kind, i.name, i.born_key || coalesce(' ' || (SELECT group_concat(k, ' ') FROM
                      (SELECT DISTINCT provider_key AS k FROM item_link l WHERE l.item_id=i.id ORDER BY provider_key)), '')
                  FROM item i WHERE i.retired_at IS NULL""")
    db.executemany('INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)', [
        ('catalogue_id', catalogue_id), ('item_high_water', str(item_hw)), ('color_high_water', str(color_hw)), ('created_at', finished_at)])
    return dict(build_id=build_id, catalogue_id=catalogue_id, seeded_from=seeded_from, item_high_water=item_hw, color_high_water=color_hw,
                counts=counts, files=dump.files())

