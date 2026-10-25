"""Materialising a copy (design 4.3, 4.5; issue #108, M.6a): the Add picker's choices and the one transaction that writes a copy,
its figure lines and its part lines under one receipt.

`part_list_choices` is read-only. `build_target` turns a choice into the line set the copy should carry, with no write at all; it
is the first step of § 4.4 too, so the in-place switch (M.6b) builds its target with the same function. `create_copy` writes.

A choice is a dict: `{'source': 'rebrickable', 'version': n}` (`version` None = the catalogue's latest), `{'source': 'bricklink'}`
(the latest fetched BrickLink list) or `{'source': 'rebrickable_api'}` (the latest fetched Rebrickable list, for a set newer than
the catalogue). Nothing here touches the network."""
from dataclasses import dataclass, field
import json
import uuid

from . import identity, jobs
from .connect import check_compatible
from .audit import Events, need_catalogue, transaction
from .connect import has_catalogue, now
from .errors import Store4Error

SOURCES = ('rebrickable', 'bricklink', 'rebrickable_api')


class NoPartList(Store4Error):
    """The set has no part list to build a copy from."""


class BrickLinkPending(Store4Error):
    """BrickLink's list was chosen but none is fetched yet: queueing the job and the pending state are M.6c (decision F)."""


@dataclass
class FigureTarget:
    """One figure line with its own Rebrickable list (design 4.5): the catalogue's latest, a fetched one, else 'none'."""
    item_id: int
    quantity: int
    source: str                                  # rebrickable | rebrickable_api | none
    version: int | None = None
    fetched_inventory_id: int | None = None
    digest: str | None = None
    parts: dict = field(default_factory=dict)    # (item, colour, spare) -> quantity of ONE figure


@dataclass
class Target:
    """What a copy of a set should carry for a choice: the set list, and each figure line with its list."""
    item_id: int
    source: str
    version: int | None
    fetched_inventory_id: int | None
    digest: str
    parts: dict                                  # (item, colour, spare) -> quantity
    figures: list

    def lines(self):
        """Design 4.4 step 1: `(figure item or None, item, colour, spare) -> quantity`, a figure's lines times its quantity.
        Lines of quantity 0 are not in it."""
        out = {(None, *k): q for k, q in self.parts.items() if q > 0}
        for fig in self.figures:
            for k, q in fig.parts.items():
                if q * fig.quantity > 0:
                    out[(fig.item_id, *k)] = q * fig.quantity
        return out


# ---------- the picker ----------

def _versions(db, item_id):
    if not has_catalogue(db):
        return []
    return [dict(r) for r in db.execute('''SELECT version, ordinal, is_latest, digest FROM catalogue.inventory
                                           WHERE item_id=? AND retired_at IS NULL ORDER BY version''', (item_id,))]


def _latest_fetched(db, item_id, source):
    return db.execute('''SELECT id, seq, provider_version, fetched_at, digest FROM main.fetched_inventory
                         WHERE item_id=? AND source=? AND is_latest=1''', (item_id, source)).fetchone()


def part_list_choices(db, set_item_id):
    """The Add picker for a set (design 4.3).

    `rebrickable`: the catalogue's versions, each with `label` ("Version 2 of 3, latest"); `rebrickable_api`: the latest fetched
    Rebrickable list (a set newer than the catalogue) or None; `bricklink`: None when no BrickLink key is configured, else
    `{'fetched_inventory_id': id or None}` (None: nothing fetched yet, so choosing it queues a fetch, M.6c);
    `preselected`: the choice to show first, None when the set has no list at all; `needs_choice`: whether the picker is shown."""
    versions = _versions(db, set_item_id)
    total = len(versions)
    rebrickable = [{'version': v['version'], 'ordinal': v['ordinal'], 'of': total, 'is_latest': bool(v['is_latest']),
                    'label': f'Version {v["ordinal"]} of {total}' + (', latest' if v['is_latest'] else '')} for v in versions]
    api = _latest_fetched(db, set_item_id, 'rebrickable_api')
    api = None if api is None else {'fetched_inventory_id': api['id'], 'seq': api['seq'], 'provider_version': api['provider_version'],
                                    'fetched_at': api['fetched_at']}
    key = jobs._configured('bricklink')
    fetched = _latest_fetched(db, set_item_id, 'bricklink')
    bricklink = {'fetched_inventory_id': fetched['id'] if fetched else None} if key else None

    pref = db.execute('SELECT inventory_source, inventory_version FROM main.set_preference WHERE item_id=?', (set_item_id,)).fetchone()
    latest = next((v['version'] for v in versions if v['is_latest']), versions[-1]['version'] if versions else None)
    choice = None
    if pref and pref['inventory_source'] == 'bricklink' and key:                       # 1. the set's own preference
        choice = {'source': 'bricklink'}
    elif pref and pref['inventory_source'] == 'rebrickable' and pref['inventory_version'] is not None \
            and any(v['version'] == pref['inventory_version'] for v in versions):
        choice = {'source': 'rebrickable', 'version': pref['inventory_version']}
    elif pref and pref['inventory_source'] == 'rebrickable' and pref['inventory_version'] is None and latest is not None:
        choice = {'source': 'rebrickable', 'version': latest}
    if choice is None:
        setting = db.execute("SELECT value FROM main.setting WHERE key='prefer_bricklink_inventory'").fetchone()
        if key and setting and setting['value'] == 'true':                              # 2. the global switch, only with a key
            choice = {'source': 'bricklink'}
        elif latest is not None:                                                        # 3. the latest Rebrickable version
            choice = {'source': 'rebrickable', 'version': latest}
        elif api:                                                                       # a set newer than the catalogue
            choice = {'source': 'rebrickable_api'}
        elif bricklink and bricklink['fetched_inventory_id'] is not None:               # BrickLink's list is the only one
            choice = {'source': 'bricklink'}
    return {'set_item_id': set_item_id, 'rebrickable': rebrickable, 'rebrickable_api': api, 'bricklink': bricklink,
            'preselected': choice, 'needs_choice': total + bool(api) + bool(bricklink) > 1}


# ---------- the target line set (also § 4.4 step 1) ----------

def _catalogue_lines(db, item_id, version):
    inv = db.execute('SELECT id, digest, build_id FROM catalogue.inventory WHERE item_id=? AND version=? AND retired_at IS NULL',
                     (item_id, version)).fetchone()
    if inv is None:
        return None
    identity._activated(db, [inv['build_id']], f'the part list of item {item_id} version {version}')   # the activation boundary
    parts = {(r[0], r[1], r[2]): r[3] for r in db.execute(
        'SELECT item_id, color_id, is_spare, quantity FROM catalogue.inventory_part WHERE inventory_id=?', (inv['id'],))}
    figures = {r[0]: r[1] for r in db.execute('SELECT item_id, quantity FROM catalogue.inventory_figure WHERE inventory_id=?', (inv['id'],))}
    return inv['digest'], parts, figures


def _fetched_lines(db, fetched_id):
    row = db.execute('SELECT digest FROM main.fetched_inventory WHERE id=?', (fetched_id,)).fetchone()
    parts = {(r[0], r[1], r[2]): r[3] for r in db.execute(
        'SELECT item_id, color_id, is_spare, quantity FROM main.fetched_inventory_part WHERE fetched_inventory_id=?', (fetched_id,))}
    figures = {r[0]: r[1] for r in db.execute('SELECT item_id, quantity FROM main.fetched_inventory_figure WHERE fetched_inventory_id=?',
                                              (fetched_id,))}
    return row['digest'], parts, figures


def _figure_target(db, item_id, quantity):
    """The figure's own Rebrickable list, whatever the set's list is (Q15): catalogue latest, else fetched, else none."""
    latest = db.execute('SELECT version FROM catalogue.inventory WHERE item_id=? AND is_latest=1 AND retired_at IS NULL',
                        (item_id,)).fetchone() if has_catalogue(db) else None
    if latest:
        digest, parts, _ = _catalogue_lines(db, item_id, latest['version'])
        return FigureTarget(item_id, quantity, 'rebrickable', version=latest['version'], digest=digest, parts=parts)
    fetched = _latest_fetched(db, item_id, 'rebrickable_api')
    if fetched:
        digest, parts, _ = _fetched_lines(db, fetched['id'])
        return FigureTarget(item_id, quantity, 'rebrickable_api', fetched_inventory_id=fetched['id'], digest=digest, parts=parts)
    return FigureTarget(item_id, quantity, 'none')


def build_target(db, set_item_id, choice):
    """The lines a copy of the set carries for `choice`, read from the catalogue and the fetched lists; writes nothing.

    BrickLink lists already hold required = quantity - extra (M.5b), so quantities are taken as stored."""
    source = choice.get('source')
    if source not in SOURCES:
        raise Store4Error(f'unknown part list source {source!r}')
    version = fetched_id = None
    if source == 'rebrickable':
        need_catalogue(db, 'a Rebrickable part list')
        version = choice.get('version')
        if version is None:
            row = db.execute('SELECT version FROM catalogue.inventory WHERE item_id=? AND is_latest=1 AND retired_at IS NULL',
                             (set_item_id,)).fetchone()
            if row is None:
                raise NoPartList(f'the catalogue has no part list for set {set_item_id}')
            version = row['version']
        found = _catalogue_lines(db, set_item_id, version)
        if found is None:
            raise NoPartList(f'the catalogue has no version {version} of set {set_item_id}')
        digest, parts, figures = found
    else:
        if source == 'bricklink' and not jobs._configured('bricklink'):
            raise Store4Error('BrickLink\'s list is not offered without a BrickLink key')
        row = _latest_fetched(db, set_item_id, source)
        if row is None:
            if source == 'bricklink':
                raise BrickLinkPending(f'no BrickLink list is fetched for set {set_item_id}; queueing one is not built yet (M.6c)')
            raise NoPartList(f'no fetched Rebrickable list for set {set_item_id}')
        fetched_id = row['id']
        digest, parts, figures = _fetched_lines(db, fetched_id)
    return Target(set_item_id, source, version, fetched_id, digest, parts,
                  [_figure_target(db, item, q) for item, q in sorted(figures.items())])


# ---------- create ----------

def _project(db, target):
    """Every item and colour the target names is in the collection before a row refers to it (design 6.3)."""
    for item in sorted({target.item_id} | {k[0] for k in target.parts} | {f.item_id for f in target.figures}
                       | {k[0] for f in target.figures for k in f.parts}):
        identity.project(db, item)
    for colour in sorted({k[1] for k in target.parts} | {k[1] for f in target.figures for k in f.parts}):
        identity.project_color(db, colour)


PART_COLUMNS = ['id', 'copy_figure_id', 'item_id', 'color_id', 'is_spare', 'quantity']


def create_copy(db, set_item_id, choice, *, via, actor=None, condition=None, completeness=None, note=None):
    """Add one copy of a set: the copy, its figure lines and its part lines, in one transaction under ONE receipt event
    (`copy`, the new id, field `add`, `new_value` = the rows written). Returns the receipt, with the copy's `id`.

    The copy id is a uuid (design 3.1: collection rows keep uuid text ids). The copy's digest, and each figure line's, is the
    source list's own."""
    with transaction(db, 'adding a copy'):
        if has_catalogue(db):
            check_compatible(db)                            # a connection opened before a rebuild keeps the old file
        target = build_target(db, set_item_id, choice)
        _project(db, target)
        stamp, copy_id = now(), str(uuid.uuid4())
        db.execute('''INSERT INTO main.copy(id, item_id, inventory_source, inventory_version, fetched_inventory_id, inventory_digest,
                      materialised_at, condition, completeness, completeness_source, note, created_at, updated_at)
                      VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (copy_id, set_item_id, target.source, target.version, target.fetched_inventory_id, target.digest, stamp, condition,
                    completeness, 'manual' if completeness else None, note, stamp, stamp))
        figure_rows = []
        figure_ids = {}
        for fig in target.figures:
            figure_ids[fig.item_id] = db.execute('''INSERT INTO main.copy_figure(copy_id, item_id, inventory_source, inventory_version,
                fetched_inventory_id, inventory_digest, quantity, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)''',
                (copy_id, fig.item_id, fig.source, fig.version, fig.fetched_inventory_id, fig.digest, fig.quantity, stamp)).lastrowid
            figure_rows.append({'id': figure_ids[fig.item_id], 'item_id': fig.item_id, 'inventory_source': fig.source,
                                'inventory_version': fig.version, 'fetched_inventory_id': fig.fetched_inventory_id,
                                'inventory_digest': fig.digest, 'quantity': fig.quantity})
        part_rows = []
        for (figure, item, colour, spare), quantity in sorted(target.lines().items(), key=lambda kv: tuple(-1 if x is None else x for x in kv[0])):
            figure_id = None if figure is None else figure_ids[figure]
            part_id = db.execute('''INSERT INTO main.copy_part(copy_id, copy_figure_id, item_id, color_id, is_spare, quantity)
                                    VALUES(?, ?, ?, ?, ?, ?)''', (copy_id, figure_id, item, colour, spare, quantity)).lastrowid
            part_rows.append([part_id, figure_id, item, colour, spare, quantity])
        receipt = {'copy': {'id': copy_id, 'item_id': set_item_id, 'inventory_source': target.source, 'inventory_version': target.version,
                            'fetched_inventory_id': target.fetched_inventory_id, 'inventory_digest': target.digest,
                            'materialised_at': stamp, 'condition': condition, 'completeness': completeness, 'note': note},
                   'figures': figure_rows, 'parts': {'columns': PART_COLUMNS, 'rows': part_rows}}
        events = Events(db, via, actor)
        events.write('copy', copy_id, 'add', new=receipt)
    return receipt
