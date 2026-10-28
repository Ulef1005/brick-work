"""The cross-file checks of `brickwork check` (design 3.1 "What keeps the two files consistent", 6.7, 8.7 point 4): does the collection belong with
the catalogue attached beside it? Read-only. Each check is one named result `{name, title, ok, count, message}`; a failure names what is wrong and the fix.

`binding`        catalogue_id, activated builds and high-water marks (what `connect()` refuses a mismatched pair on).
`born_keys`      every origin='catalogue' item and colour of the collection exists in the catalogue under the same id with the same born key.
`inventory_keys` every part list the collection names by (set or figure, version) exists in the catalogue (retired is fine: screens say "gone").
`digests`        the row digests of projected items agree with the catalogue's once reconciled; the digests of the part lists the collection
                 names agree with their own lines. A copy whose recorded digest differs from the catalogue's is the normal state after a
                 re-download (Tools & Admin lists it) and is counted in the message, never a failure. `bl_digest` lives in the catalogue file only:
                 nothing in the collection stores one, so there is nothing to compare it with."""
import json

from .bldigest import inventory_digest
from .connect import FIX, check_compatible, has_catalogue
from .errors import CatalogueError

SHOWN = 5                                                       # ids named in a failure message


def _result(name, title, bad, message, ok_message, *, ok=None):
    ok = not bad if ok is None else ok
    return dict(name=name, title=title, ok=ok, count=len(bad), message=ok_message if ok else message)


def _named(rows):
    rows = list(rows)
    return ', '.join(str(r) for r in rows[:SHOWN]) + (f' and {len(rows) - SHOWN} more' if len(rows) > SHOWN else '')


def binding(db):
    try:
        check_compatible(db)
    except CatalogueError as exc:
        return dict(name='binding', title='Collection and catalogue are a pair', ok=False, count=1, message=str(exc))
    return dict(name='binding', title='Collection and catalogue are a pair', ok=True, count=0, message='The collection is bound to this catalogue and every build it activated is in it.')


def born_keys(db):
    items = [r[0] for r in db.execute('''SELECT i.id FROM main.item i LEFT JOIN catalogue.item c ON c.id=i.id
        WHERE i.origin='catalogue' AND i.merged_into IS NULL AND (c.id IS NULL OR c.born_provider IS NOT i.born_provider
              OR c.born_namespace IS NOT i.born_namespace OR c.born_key IS NOT i.born_key) ORDER BY i.id''')]
    colours = [r[0] for r in db.execute('''SELECT m.id FROM main.color m LEFT JOIN catalogue.color c ON c.id=m.id
        WHERE m.origin='catalogue' AND (c.id IS NULL OR c.born_provider IS NOT m.born_provider OR c.born_key IS NOT m.born_key) ORDER BY m.id''')]
    bad = items + colours
    where = '; '.join(p for p in (f'items {_named(items)}' if items else '', f'colours {_named(colours)}' if colours else '') if p)
    return _result('born_keys', 'Catalogue ids keep their born keys', bad,
                   f'{len(items)} items and {len(colours)} colours of the collection are not in the catalogue under the same id and born key ({where}). '
                   f'This catalogue file is not the one the collection was made with: {FIX}.',
                   'Every catalogue item and colour in the collection has the same id and born key in the catalogue.')


def referenced_inventories(db):
    """The distinct (item id, version) of every Rebrickable part list the collection names (a figure line that left its copy's list does not count)."""
    return [tuple(r) for r in db.execute('''
        SELECT item_id, inventory_version FROM main.copy WHERE inventory_source='rebrickable'
        UNION SELECT item_id, inventory_version FROM main.copy_figure WHERE inventory_source='rebrickable' AND retired_at IS NULL
        UNION SELECT item_id, inventory_version FROM main.stock WHERE inventory_source='rebrickable'
        UNION SELECT item_id, inventory_version FROM main.set_preference WHERE inventory_source='rebrickable' AND inventory_version IS NOT NULL
        ORDER BY 1, 2''')]


def inventory_keys(db):
    bad = [f'{item} v{version}' for item, version in referenced_inventories(db)
           if db.execute('SELECT 1 FROM catalogue.inventory WHERE item_id=? AND version=?', (item, version)).fetchone() is None]
    return _result('inventory_keys', 'Part lists exist in the catalogue', bad,
                   f'{len(bad)} part lists the collection names are not in the catalogue at all ({_named(bad)}; item id and version). '
                   f'This catalogue file is not the one the collection was made with: {FIX}.',
                   'Every part list the collection names exists in the catalogue.')


def _lines(db, inventory):
    return ([tuple(r) for r in db.execute('SELECT item_id, color_id, is_spare, quantity FROM catalogue.inventory_part WHERE inventory_id=?', (inventory,))],
            [tuple(r) for r in db.execute('SELECT item_id, quantity FROM catalogue.inventory_figure WHERE inventory_id=?', (inventory,))],
            [tuple(r) for r in db.execute('SELECT item_id, quantity FROM catalogue.inventory_set WHERE inventory_id=?', (inventory,))])


def digests(db):
    title = 'Digests agree'
    newest = db.execute('SELECT reconciled_at FROM main.catalogue_build ORDER BY id DESC LIMIT 1').fetchone()
    stale = []
    if newest is not None and newest[0] is not None:             # the row digests are only expected equal once the newest build is reconciled
        stale = [r[0] for r in db.execute('''SELECT i.id FROM main.item i JOIN catalogue.item c ON c.id=i.id AND c.born_key IS i.born_key
            WHERE i.origin='catalogue' AND i.merged_into IS NULL AND i.digest IS NOT c.digest ORDER BY i.id''')]
    broken = []
    for item, version in referenced_inventories(db):
        row = db.execute('SELECT id, digest FROM catalogue.inventory WHERE item_id=? AND version=?', (item, version)).fetchone()
        if row is not None and inventory_digest(*_lines(db, row['id'])) != row['digest']:
            broken.append(f'{item} v{version}')
    changed = db.execute('''SELECT count(*) FROM main.copy c JOIN catalogue.inventory i ON i.item_id=c.item_id AND i.version=c.inventory_version
        WHERE c.archived_at IS NULL AND c.inventory_source='rebrickable' AND i.digest IS NOT c.inventory_digest''').fetchone()[0]
    bad = stale + broken
    note = f' {changed} copies carry a part list that changed in the catalogue; Tools & Admin lists them.' if changed else ''
    if newest is None or newest[0] is None:
        note = ' The row digests are checked once the collection is reconciled with the newest build.' + note
    parts = [p for p in (f'{len(stale)} projected items differ from the catalogue row they were projected from ({_named(stale)}); run reconcile' if stale else '',
                         f'{len(broken)} part lists in the catalogue do not match their own lines ({_named(broken)}); {FIX}' if broken else '') if p]
    return _result('digests', title, bad, '; '.join(parts) + '.' + note, 'Projected items and the part lists the collection names agree with the catalogue.' + note)


CHECKS = (binding, born_keys, inventory_keys, digests)


def run(db):
    """All cross-file checks on a collection with its catalogue attached, in the order above. Without a catalogue: an empty list."""
    if not has_catalogue(db):
        return []
    out = [binding(db)]
    if not out[0]['ok']:                                         # a pair that does not belong together makes the others meaningless
        return out
    return out + [check(db) for check in CHECKS[1:]]
