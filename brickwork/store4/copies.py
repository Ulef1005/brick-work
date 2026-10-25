"""Materialising a copy (design 4.3, 4.5; issue #108, M.6a): the Add picker's choices and the one transaction that writes a copy,
its figure lines and its part lines under one receipt.

`part_list_choices` is read-only. `build_target` turns a choice into the line set the copy should carry, with no write at all; it
is the first step of § 4.4 too, so the in-place switch (M.6b) builds its target with the same function. `create_copy` writes.

`switch_part_list` is § 4.4, the in-place switch under one receipt; `preview_switch` computes the same plan without writing;
`undo_switch` restores a switch from its receipt.

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
    """BrickLink's list was chosen but none is fetched yet. `build_target` raises it; `create_copy` answers it with decision F's
    pending state (Rebrickable's list now, a queued job), a switch has nothing to switch to and lets it through."""


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
                raise BrickLinkPending(f'no BrickLink list is fetched for set {set_item_id}; `create_copy` queues one')
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


def _pending_base(db, set_item_id):
    """The Rebrickable list a copy gets while BrickLink's is pending (design 4.3, decision F): the set's pinned version when its
    preference names one the catalogue has, else the catalogue's latest. Pending sits on a catalogue version only (CHECK)."""
    if not has_catalogue(db):
        raise NoPartList(f'set {set_item_id} has no Rebrickable list to use while BrickLink\'s is pending: the catalogue is not attached')
    pref = db.execute('SELECT inventory_source, inventory_version FROM main.set_preference WHERE item_id=?', (set_item_id,)).fetchone()
    if pref and pref['inventory_source'] == 'rebrickable' and pref['inventory_version'] is not None and any(
            v['version'] == pref['inventory_version'] for v in _versions(db, set_item_id)):
        return {'source': 'rebrickable', 'version': pref['inventory_version']}
    if not any(v['is_latest'] for v in _versions(db, set_item_id)):
        raise NoPartList(f'set {set_item_id} has no Rebrickable list in the catalogue to use while BrickLink\'s is pending')
    return {'source': 'rebrickable'}


def create_copy(db, set_item_id, choice, *, via, actor=None, condition=None, completeness=None, note=None):
    """Add one copy of a set: the copy, its figure lines and its part lines, in one transaction under ONE receipt event
    (`copy`, the new id, field `add`, `new_value` = the rows written). Returns the receipt, with the copy's `id`.

    The copy id is a uuid (design 3.1: collection rows keep uuid text ids). The copy's digest, and each figure line's, is the
    source list's own.

    BrickLink chosen with no list fetched (decision F): the copy gets Rebrickable's list at once (`_pending_base`) with
    `inventory_pending='bricklink'`, and `pending_job_id` is a `bricklink_subsets` job queued in this same transaction
    (`jobs.queue_in`; an open job for the set is reused, not doubled). The receipt then carries `pending` = `{'source',
    'job_id', 'job_reused'}`. `pending.settle_pending` takes it from there."""
    with transaction(db, 'adding a copy'):
        if has_catalogue(db):
            check_compatible(db)                            # a connection opened before a rebuild keeps the old file
        pending = None
        try:
            target = build_target(db, set_item_id, choice)
        except BrickLinkPending:
            target = build_target(db, set_item_id, _pending_base(db, set_item_id))
            pending = True
        _project(db, target)
        stamp, copy_id = now(), str(uuid.uuid4())
        if pending:
            number = db.execute('SELECT born_key FROM main.item WHERE id=?', (set_item_id,)).fetchone()['born_key']
            job, created = jobs.queue_in(db, 'bricklink_subsets', item_id=set_item_id, payload=number, via=via, actor=actor)
            pending = {'source': 'bricklink', 'job_id': job, 'job_reused': not created}
        db.execute('''INSERT INTO main.copy(id, item_id, inventory_source, inventory_version, fetched_inventory_id, inventory_digest,
                      materialised_at, inventory_pending, pending_job_id, condition, completeness, completeness_source, note,
                      created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (copy_id, set_item_id, target.source, target.version, target.fetched_inventory_id, target.digest, stamp,
                    pending and 'bricklink', pending and pending['job_id'], condition,
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
        if pending:
            receipt['copy'].update(inventory_pending='bricklink', pending_job_id=pending['job_id'])
            receipt['pending'] = pending
        events = Events(db, via, actor)
        events.write('copy', copy_id, 'add', new=receipt)
    return receipt


# ---------- the in-place switch (design 4.4; issue #108, M.6b) ----------

class CopyMarked(Store4Error):
    """An automatic switch found the copy checked or marked (decision F as amended): it is left for the user."""


class PendingChanged(Store4Error):
    """A switch for a pending copy found it no longer waiting on that job (cancelled or settled meanwhile)."""


class NothingToSwitch(Store4Error):
    """The copy already carries the chosen list exactly: no line, figure or copy column would change."""


class SwitchUndoRefused(Store4Error):
    """The switch cannot be undone: it was undone already, or a row it touched has changed since."""


FIGURE_COLUMNS = ['id', 'item_id', 'inventory_source', 'inventory_version', 'fetched_inventory_id', 'inventory_digest', 'quantity',
                  'missing', 'retired_at', 'updated_at']
LINE_COLUMNS = ['id', 'copy_figure_id', 'item_id', 'color_id', 'is_spare', 'quantity', 'missing', 'damaged', 'checked', 'retired_at']
COPY_COLUMNS = ['inventory_source', 'inventory_version', 'fetched_inventory_id', 'inventory_digest', 'materialised_at',
                'inventory_pending', 'pending_job_id', 'completeness', 'completeness_source', 'updated_at']
                                                 # completeness_source: a manual choice made after the switch refuses its undo
FIELD, UNDO_FIELD = 'part_list_switch', 'part_list_switch_undo'


def _row(row, columns):
    return [row[c] for c in columns]


def _order(key):
    return tuple(-1 if x is None else x for x in key)


def _plan(db, copy, target, stamp):
    """Steps 2-5 and 7 of § 4.4 as data, reading only: the figure and line operations the switch needs and the lines whose
    state does not carry over. `preview_switch` and `switch_part_list` both run this, so they cannot disagree.

    An operation is `{'op': 'update'|'insert'|'retire', 'before': dict|None, 'after': dict}`; an insert's `after` has no id yet."""
    copy_id = copy['id']
    wanted = target.lines()
    wanted_figs = {f.item_id: f for f in target.figures}
    have_figs = {r['item_id']: r for r in db.execute('SELECT * FROM main.copy_figure WHERE copy_id=?', (copy_id,))}
    have_lines = {(r['fig_item'], r['item_id'], r['color_id'], r['is_spare']): r for r in db.execute(
        '''SELECT p.*, f.item_id AS fig_item FROM main.copy_part p LEFT JOIN main.copy_figure f ON f.id=p.copy_figure_id
           WHERE p.copy_id=?''', (copy_id,))}
    figures, lines, retired, capped = [], [], [], []

    def detail(kind, key, before, after):
        figure, item, colour, spare = key
        return {'kind': kind, 'id': before['id'], 'figure_item': figure, 'item_id': item, 'color_id': colour, 'is_spare': spare,
                'quantity': [before['quantity'], after['quantity']], 'missing': [before['missing'], after['missing']],
                'damaged': [before['damaged'], after['damaged']] if kind == 'part' else None,
                'checked': before['checked'] if kind == 'part' else None}

    for item, fig in sorted(wanted_figs.items()):
        new = {'item_id': item, 'inventory_source': fig.source, 'inventory_version': fig.version,
               'fetched_inventory_id': fig.fetched_inventory_id, 'inventory_digest': fig.digest, 'quantity': fig.quantity,
               'retired_at': None}
        old = have_figs.get(item)
        if old is None:
            figures.append({'op': 'insert', 'before': None, 'after': {**new, 'missing': 0, 'updated_at': stamp}})
            continue
        after = {**dict(old), **new, 'missing': min(old['missing'], fig.quantity)}
        if any(after[c] != old[c] for c in FIGURE_COLUMNS if c != 'updated_at'):
            figures.append({'op': 'update', 'before': dict(old), 'after': {**after, 'updated_at': stamp}})
            if after['missing'] < old['missing']:
                capped.append(detail('figure', (item, None, None, None), old, after))
    for item, old in sorted(have_figs.items()):
        if item not in wanted_figs and old['retired_at'] is None:
            figures.append({'op': 'retire', 'before': dict(old), 'after': {**dict(old), 'retired_at': stamp, 'updated_at': stamp}})
            if old['missing']:
                retired.append(detail('figure', (item, None, None, None), old, old))

    for key in sorted(wanted, key=_order):
        old, quantity = have_lines.get(key), wanted[key]
        if old is None:
            lines.append({'op': 'insert', 'before': None, 'key': key, 'after': {
                'copy_figure_id': None, 'item_id': key[1], 'color_id': key[2], 'is_spare': key[3], 'quantity': quantity,
                'missing': 0, 'damaged': 0, 'checked': 0, 'retired_at': None}})
            continue
        after = {**dict(old), 'quantity': quantity, 'missing': min(old['missing'], quantity), 'damaged': min(old['damaged'], quantity),
                 'retired_at': None}
        if any(after[c] != old[c] for c in LINE_COLUMNS):
            lines.append({'op': 'update', 'before': dict(old), 'after': after, 'key': key})
            if after['missing'] < old['missing'] or after['damaged'] < old['damaged']:
                capped.append(detail('part', key, old, after))
    for key, old in sorted(have_lines.items(), key=lambda kv: _order(kv[0])):
        if key not in wanted and old['retired_at'] is None:
            lines.append({'op': 'retire', 'before': dict(old), 'after': {**dict(old), 'retired_at': stamp}, 'key': key})
            if old['missing'] or old['damaged'] or old['checked']:
                retired.append(detail('part', key, old, old))
    return {'figures': figures, 'lines': lines, 'not_carried_over': {'retired': retired, 'capped': capped}}


def _same_list(copy, target):
    return (copy['inventory_source'], copy['inventory_version'], copy['fetched_inventory_id'], copy['inventory_digest']) == \
           (target.source, target.version, target.fetched_inventory_id, target.digest) and copy['inventory_pending'] is None


def _counts(plan):
    return {f'{what}_{op}': sum(1 for o in plan[what] if o['op'] == op)
            for what in ('figures', 'lines') for op in ('update', 'insert', 'retire')}


def _copy_row(db, copy_id):
    copy = db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()
    if copy is None:
        raise Store4Error(f'no copy {copy_id}')
    return copy


def preview_switch(db, copy_id, choice):
    """What a switch to `choice` would do, without writing: `{'same_list': bool, 'counts': {...}, 'not_carried_over':
    {'retired': [...], 'capped': [...]}}`, the very lists the real receipt will hold. M.6c's "switch now?" offer reads it.
    `same_list` is True when `switch_part_list` would refuse with `NothingToSwitch`."""
    if has_catalogue(db):
        check_compatible(db)
    copy = _copy_row(db, copy_id)
    target = build_target(db, copy['item_id'], choice)
    plan = _plan(db, copy, target, now())
    return {'same_list': not plan['figures'] and not plan['lines'] and _same_list(copy, target),
            'counts': _counts(plan), 'not_carried_over': plan['not_carried_over']}


def derived_completeness(db, copy_id):
    """The 3.3 rule (`core/completeness.py`) on 4.0 tables: 'complete' when the copy has the status flag "Set is checked" and no
    live, non-spare, non-figure line is missing or damaged and no live figure line is missing, else 'incomplete'. Retired rows
    are not lines of the copy. None unless the copy's completeness is derived."""
    copy = _copy_row(db, copy_id)
    if copy['completeness_source'] != 'derived':
        return None
    checked = db.execute('''SELECT 1 FROM main.copy_flag cf JOIN main.flag f ON f.id=cf.flag_id AND f.archived_at IS NULL
                            WHERE cf.copy_id=? AND f.kind='status' AND f.name='Set is checked' ''', (copy_id,)).fetchone()
    defects = db.execute('''SELECT 1 FROM main.copy_part WHERE copy_id=? AND retired_at IS NULL AND is_spare=0 AND copy_figure_id IS NULL
                            AND (missing>0 OR damaged>0)
                            UNION ALL SELECT 1 FROM main.copy_figure WHERE copy_id=? AND retired_at IS NULL AND missing>0''',
                         (copy_id, copy_id)).fetchone()
    return 'complete' if checked and not defects else 'incomplete'


def has_marks(db, copy_id):
    """Anything on the copy checked or marked: a live line with `checked`, `missing` or `damaged` above 0, or a live figure line
    with `missing` above 0. Decision F as amended: such a copy is never switched without the user."""
    return db.execute(
        '''SELECT 1 FROM main.copy_part WHERE copy_id=? AND retired_at IS NULL AND (checked>0 OR missing>0 OR damaged>0)
           UNION ALL SELECT 1 FROM main.copy_figure WHERE copy_id=? AND retired_at IS NULL AND missing>0''',
        (copy_id, copy_id)).fetchone() is not None


def switch_part_list(db, copy_id, choice, *, via, actor=None, trigger=None, unless_marked=False, while_pending_on=None):
    """Design 4.4: move a copy to another part list in place, in one transaction under ONE receipt event (`copy`, the copy id,
    field `part_list_switch`, `new_value` = the receipt). Nothing is deleted: rows of lines that left the list get `retired_at`,
    rows of lines that came back are re-activated under the same id, so Take/Give, allocation and check-session references stay
    valid. Returns the receipt, with `event_id`.

    `trigger` (M.6c) says why, kept in the receipt as `trigger` when given: `{'automatic': True, 'job_id': n}` for the switch a
    finished pending job makes by itself, `{'accepted': True, 'job_id': n}` for the user accepting the offer; a plain switch has none.

    A switch to the list the copy already carries (same source, version or fetched list, digest, no pending) that would change
    no row is refused with `NothingToSwitch`: an empty receipt could not be told from an error. `unless_marked` (the automatic
    switch) refuses with `CopyMarked` when the copy has marks, checked inside this transaction so a mark made meanwhile counts.
    `while_pending_on` (a job id: the automatic switch and the accepted offer) refuses with `PendingChanged` unless the copy still
    waits on that job, so a cancel committed meanwhile is not overridden."""
    with transaction(db, 'switching a part list'):
        if has_catalogue(db):
            check_compatible(db)
        copy = _copy_row(db, copy_id)
        if while_pending_on is not None and (copy['inventory_pending'] != 'bricklink' or copy['pending_job_id'] != while_pending_on):
            raise PendingChanged(f'copy {copy_id} no longer waits for job {while_pending_on}')
        if unless_marked and has_marks(db, copy_id):
            raise CopyMarked(f'copy {copy_id} is checked or marked; it switches only when the user says so')
        target = build_target(db, copy['item_id'], choice)
        stamp = now()
        plan = _plan(db, copy, target, stamp)
        if not plan['figures'] and not plan['lines'] and _same_list(copy, target):
            raise NothingToSwitch(f'copy {copy_id} already carries this part list')
        _project(db, target)
        figure_ids = {r['item_id']: r['id'] for r in db.execute('SELECT id, item_id FROM main.copy_figure WHERE copy_id=?', (copy_id,))}
        figure_ops = []
        for op in plan['figures']:
            after = op['after']
            if op['op'] == 'insert':
                after['id'] = figure_ids[after['item_id']] = db.execute(
                    '''INSERT INTO main.copy_figure(copy_id, item_id, inventory_source, inventory_version, fetched_inventory_id,
                       inventory_digest, quantity, missing, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, 0, ?)''',
                    (copy_id, after['item_id'], after['inventory_source'], after['inventory_version'], after['fetched_inventory_id'],
                     after['inventory_digest'], after['quantity'], stamp)).lastrowid
            else:
                db.execute('''UPDATE main.copy_figure SET inventory_source=?, inventory_version=?, fetched_inventory_id=?,
                              inventory_digest=?, quantity=?, missing=?, retired_at=?, updated_at=? WHERE id=?''',
                           (after['inventory_source'], after['inventory_version'], after['fetched_inventory_id'], after['inventory_digest'],
                            after['quantity'], after['missing'], after['retired_at'], after['updated_at'], after['id']))
            figure_ops.append([op['op'], None if op['before'] is None else _row(op['before'], FIGURE_COLUMNS), _row(after, FIGURE_COLUMNS)])
        line_ops = []
        for op in plan['lines']:
            after = op['after']
            if op['op'] == 'insert':
                figure = op['key'][0]
                after['copy_figure_id'] = None if figure is None else figure_ids[figure]
                after['id'] = db.execute('''INSERT INTO main.copy_part(copy_id, copy_figure_id, item_id, color_id, is_spare, quantity)
                                            VALUES(?, ?, ?, ?, ?, ?)''', (copy_id, after['copy_figure_id'], after['item_id'],
                                                                         after['color_id'], after['is_spare'], after['quantity'])).lastrowid
            else:
                db.execute('UPDATE main.copy_part SET quantity=?, missing=?, damaged=?, retired_at=? WHERE id=?',
                           (after['quantity'], after['missing'], after['damaged'], after['retired_at'], after['id']))
            line_ops.append([op['op'], None if op['before'] is None else _row(op['before'], LINE_COLUMNS), _row(after, LINE_COLUMNS)])
        db.execute('''UPDATE main.copy SET inventory_source=?, inventory_version=?, fetched_inventory_id=?, inventory_digest=?,
                      materialised_at=?, inventory_pending=NULL, pending_job_id=NULL, updated_at=? WHERE id=?''',
                   (target.source, target.version, target.fetched_inventory_id, target.digest, stamp, stamp, copy_id))
        completeness = derived_completeness(db, copy_id)
        if completeness is not None:
            db.execute('UPDATE main.copy SET completeness=? WHERE id=?', (completeness, copy_id))
        receipt = {'choice': choice, 'counts': _counts(plan),
                   'copy': {'columns': COPY_COLUMNS, 'before': _row(copy, COPY_COLUMNS),
                            'after': _row(_copy_row(db, copy_id), COPY_COLUMNS)},
                   'figures': {'columns': FIGURE_COLUMNS, 'ops': figure_ops},
                   'parts': {'columns': LINE_COLUMNS, 'ops': line_ops},
                   'not_carried_over': plan['not_carried_over']}
        if trigger:
            receipt['trigger'] = trigger
        Events(db, via, actor).write('copy', copy_id, FIELD, new=receipt)
        receipt['event_id'] = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    return receipt


def undo_switch(db, event_id, *, via, actor=None):
    """Restore what the switch of `event_id` changed, from its receipt, in one transaction; writes its own event (field
    `part_list_switch_undo`) and the `event_undo` row.

    "Exactly" holds as follows. Every row the switch updated or retired is put back column for column (quantity, missing, damaged,
    checked, retired_at, the figure's list columns), so the copy's live line set and figure set, their counts and flags, and the
    copy's source, version, fetched list, digest, pending job and completeness are the old ones, under the old row ids; a derived
    completeness is recomputed instead, since lines the switch did not touch may have been marked since. Rows the
    switch INSERTED cannot be deleted (a Take, allocation or check session may refer to them since); they are retired, so they are
    absent from every live read and a later switch back to that list re-activates them under the same id. `copy.updated_at` and
    `copy_figure.updated_at` are set to the undo's time, not restored.

    Refused (`SwitchUndoRefused`) when the event is not a switch, was undone already, or any row it touched differs from the
    receipt's after-state (any other change since: a Take, a check mark, a later switch not yet undone)."""
    with transaction(db, 'undoing a part list switch'):
        event = db.execute('SELECT * FROM main.event WHERE id=?', (event_id,)).fetchone()
        if event is None or event['entity_kind'] != 'copy' or event['field'] != FIELD:
            raise SwitchUndoRefused(f'event {event_id} is not a part list switch')
        if db.execute('SELECT 1 FROM main.event_undo WHERE event_id=?', (event_id,)).fetchone():
            raise SwitchUndoRefused(f'event {event_id} was undone already')
        copy_id, receipt, stamp = event['entity_id'], json.loads(event['new_value']), now()
        copy = _copy_row(db, copy_id)

        def without_stamp(columns, row):
            return [v for c, v in zip(columns, row) if c != 'updated_at']

        c_cols = receipt['copy']['columns']
        if without_stamp(c_cols, _row(copy, c_cols)) != without_stamp(c_cols, receipt['copy']['after']):
            raise SwitchUndoRefused(f'copy {copy_id} changed after the switch')
        for table, key in (('copy_figure', 'figures'), ('copy_part', 'parts')):
            columns = receipt[key]['columns']
            for op, before, after in receipt[key]['ops']:
                row = db.execute(f'SELECT {", ".join(columns)} FROM main.{table} WHERE id=?', (after[0],)).fetchone()
                if row is None or without_stamp(columns, list(row)) != without_stamp(columns, after):
                    raise SwitchUndoRefused(f'{table} row {after[0]} changed after the switch')
        for op, before, after in receipt['figures']['ops']:
            if op == 'insert':
                db.execute('UPDATE main.copy_figure SET retired_at=?, updated_at=? WHERE id=?', (stamp, stamp, after[0]))
            else:
                old = dict(zip(receipt['figures']['columns'], before))
                db.execute('''UPDATE main.copy_figure SET inventory_source=?, inventory_version=?, fetched_inventory_id=?,
                              inventory_digest=?, quantity=?, missing=?, retired_at=?, updated_at=? WHERE id=?''',
                           (old['inventory_source'], old['inventory_version'], old['fetched_inventory_id'], old['inventory_digest'],
                            old['quantity'], old['missing'], old['retired_at'], stamp, old['id']))
        for op, before, after in receipt['parts']['ops']:
            if op == 'insert':
                db.execute('UPDATE main.copy_part SET retired_at=? WHERE id=?', (stamp, after[0]))
            else:
                old = dict(zip(receipt['parts']['columns'], before))
                db.execute('UPDATE main.copy_part SET quantity=?, missing=?, damaged=?, checked=?, retired_at=? WHERE id=?',
                           (old['quantity'], old['missing'], old['damaged'], old['checked'], old['retired_at'], old['id']))
        old = dict(zip(c_cols, receipt['copy']['before']))
        db.execute('''UPDATE main.copy SET inventory_source=?, inventory_version=?, fetched_inventory_id=?, inventory_digest=?,
                      materialised_at=?, inventory_pending=?, pending_job_id=?, completeness=?, updated_at=? WHERE id=?''',
                   (old['inventory_source'], old['inventory_version'], old['fetched_inventory_id'], old['inventory_digest'],
                    old['materialised_at'], old['inventory_pending'], old['pending_job_id'], old['completeness'], stamp, copy_id))
        completeness = derived_completeness(db, copy_id)    # lines the switch did not touch may have changed since: recompute
        if completeness is not None:
            db.execute('UPDATE main.copy SET completeness=? WHERE id=?', (completeness, copy_id))
        Events(db, via, actor).write('copy', copy_id, UNDO_FIELD, new={'undoes': event_id, 'counts': receipt['counts']})
        undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event_id, undo_id))
    return {'event_id': undo_id, 'undoes': event_id, 'counts': receipt['counts']}


# ---------- preferences (design 4.3; issue #108, M.6c) ----------

class BadPreference(Store4Error):
    """The preference asked for is not one the schema or the catalogue allows."""


def part_list_preference(db, set_item_id):
    """The set's own preference as `{'source', 'version'}`, None when it has none."""
    row = db.execute('SELECT inventory_source, inventory_version FROM main.set_preference WHERE item_id=?', (set_item_id,)).fetchone()
    return None if row is None else {'source': row['inventory_source'], 'version': row['inventory_version']}


def set_part_list_preference(db, set_item_id, choice, *, via, actor=None):
    """"Use this part list for new copies of this set": write (or, with `choice` None, clear) the set's `set_preference` in one
    transaction with one event (`set_preference`, the item id, field `preference`, old and new as `{'source', 'version'}`).
    `choice` is `{'source': 'bricklink'}` or `{'source': 'rebrickable', 'version': n or None}` (None = always the latest); a
    version the catalogue does not hold is refused. Setting what is already set writes nothing. Returns the new preference
    (None when cleared). The Add picker's preselection (`part_list_choices`) reads exactly this row."""
    if choice is not None:
        source, version = choice.get('source'), choice.get('version')
        if source not in ('rebrickable', 'bricklink') or (source == 'bricklink' and version is not None):
            raise BadPreference(f'{choice!r} is not a part list preference: a Rebrickable version (or the latest) or BrickLink')
        if source == 'rebrickable' and version is not None and (isinstance(version, bool) or not isinstance(version, int)
                                                                or not any(v['version'] == version for v in _versions(db, set_item_id))):
            raise BadPreference(f'the catalogue has no version {version!r} of set {set_item_id}')
        new = {'source': source, 'version': version}
    else:
        new = None
    with transaction(db, 'setting a part list preference'):
        identity.project(db, set_item_id)
        kind = db.execute('SELECT kind FROM main.item WHERE id=?', (set_item_id,)).fetchone()['kind']
        if kind != 'set':
            raise BadPreference(f'item {set_item_id} is not a set')
        old = part_list_preference(db, set_item_id)
        if old == new:
            return new
        if new is None:
            db.execute('DELETE FROM main.set_preference WHERE item_id=?', (set_item_id,))
        else:
            db.execute('INSERT OR REPLACE INTO main.set_preference(item_id, inventory_source, inventory_version, decided_at) VALUES(?, ?, ?, ?)',
                       (set_item_id, new['source'], new['version'], now()))
        Events(db, via, actor).write('set_preference', set_item_id, 'preference', old=old, new=new)
    return new


def set_prefer_bricklink(db, enabled, *, via, actor=None):
    """The global switch `setting prefer_bricklink_inventory` (Q13): `'true'` when enabled, no row when not. One event (`setting`,
    the key, field `value`). It only takes effect with a BrickLink key, as the picker applies it. Returns whether it is on."""
    key, new = 'prefer_bricklink_inventory', 'true' if enabled else None
    with transaction(db, 'setting the BrickLink preference'):
        row = db.execute('SELECT value FROM main.setting WHERE key=?', (key,)).fetchone()
        old = row['value'] if row else None
        if old == new:
            return bool(enabled)
        if new is None:
            db.execute('DELETE FROM main.setting WHERE key=?', (key,))
        else:
            db.execute('INSERT OR REPLACE INTO main.setting(key, value) VALUES(?, ?)', (key, new))
        Events(db, via, actor).write('setting', key, 'value', old=old, new=new)
    return bool(enabled)
