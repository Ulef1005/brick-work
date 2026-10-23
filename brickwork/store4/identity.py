"""Identity: projecting catalogue rows into the collection, and the one provider-link resolution function."""
from .connect import has_catalogue, now
from .errors import AmbiguousIdentity, CatalogueError, NotInCatalogue

CONFIRMED = ('manual', 'matched', 'inferred')
_RANK = {'manual': 0, 'matched': 1, 'inferred': 2}
_IN = ','.join('?' * len(CONFIRMED))


def _need_catalogue(db, what):
    if not has_catalogue(db):
        raise CatalogueError(f'{what} needs the catalogue, which is not attached')


def _activated(db, builds, what):
    builds = {b for b in builds if b is not None}
    have = {r[0] for r in db.execute('SELECT id FROM main.catalogue_build')}
    if builds - have:
        raise CatalogueError(f'{what} comes from catalogue builds {sorted(builds - have)} that this collection has not activated')


def project(db, item_id):
    """Copy a catalogue item, its links and the colours they name into the collection (design 6.3).

    Idempotent; writes inside the caller's transaction (a savepoint, so a refusal leaves nothing half-copied)."""
    if db.execute('SELECT 1 FROM main.item WHERE id=?', (item_id,)).fetchone():
        return item_id
    _need_catalogue(db, f'projecting item {item_id}')
    row = db.execute('''SELECT i.*, t.name AS theme_name, c.name AS category_name FROM catalogue.item i
                        LEFT JOIN catalogue.theme t ON t.id=i.theme_id
                        LEFT JOIN catalogue.part_category c ON c.id=i.category_id WHERE i.id=?''', (item_id,)).fetchone()
    if row is None:
        raise NotInCatalogue(f'item {item_id} is not in the catalogue')
    links = db.execute('SELECT * FROM catalogue.item_link WHERE item_id=? ORDER BY id', (item_id,)).fetchall()
    _activated(db, [row['build_id']] + [k['build_id'] for k in links], f'item {item_id}')
    stamp = now()
    db.execute('SAVEPOINT project')
    try:
        for color_id in sorted({k['color_id'] for k in links if k['color_id'] is not None}):
            project_color(db, color_id)
        db.execute('''INSERT INTO main.item(id, origin, kind, kind_source, name, year, num_parts, theme_name, category_name, size_key,
                      born_provider, born_namespace, born_key, catalogue_build_id, digest, catalogue_retired_at, created_at, updated_at)
                      VALUES(?, 'catalogue', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (item_id, row['kind'], row['kind_source'], row['name'], row['year'], row['num_parts'], row['theme_name'],
                    row['category_name'], row['size_key'], row['born_provider'], row['born_namespace'], row['born_key'],
                    row['build_id'], row['digest'], row['retired_at'], stamp, stamp))
        db.executemany('''INSERT INTO main.item_link(item_id, color_id, provider, provider_kind, provider_key, status, method, origin,
                          preferred, evidence_digest, catalogue_build_id, decided_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       [(item_id, k['color_id'], k['provider'], k['provider_kind'], k['provider_key'], k['status'], k['method'],
                         k['origin'], k['preferred'], k['evidence_digest'], k['build_id'], stamp) for k in links])
    except BaseException:
        db.execute('ROLLBACK TO project')
        raise
    finally:
        db.execute('RELEASE project')
    return item_id


def project_color(db, color_id):
    """Copy a catalogue colour and its colour links; idempotent (colours 1 and 2 exist from setup)."""
    if db.execute('SELECT 1 FROM main.color WHERE id=?', (color_id,)).fetchone():
        return color_id
    _need_catalogue(db, f'projecting colour {color_id}')
    row = db.execute('SELECT * FROM catalogue.color WHERE id=?', (color_id,)).fetchone()
    if row is None:
        raise NotInCatalogue(f'colour {color_id} is not in the catalogue')
    links = db.execute('SELECT * FROM catalogue.color_link WHERE color_id=? ORDER BY id', (color_id,)).fetchall()
    _activated(db, [k['build_id'] for k in links], f'colour {color_id}')
    stamp = now()
    db.execute('''INSERT INTO main.color(id, origin, name, rgb, is_trans, born_provider, born_key, created_at, updated_at)
                  VALUES(?, 'catalogue', ?, ?, ?, ?, ?, ?, ?)''',
               (color_id, row['name'], row['rgb'], row['is_trans'], row['born_provider'], row['born_key'], stamp, stamp))
    db.executemany('''INSERT INTO main.color_link(color_id, provider, provider_key, provider_name, status, method, inverse_preferred,
                      catalogue_build_id, decided_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   [(color_id, k['provider'], k['provider_key'], k['provider_name'], k['status'], k['method'],
                     k['inverse_preferred'], k['build_id'], stamp) for k in links])
    return color_id


def resolve(db, item_id, color_id, provider='bricklink'):
    """Which provider key and colour is the item in this colour? (design 3.2) -> (kind, key, colour key) or None."""
    rows = db.execute(f'''SELECT provider_kind, provider_key, color_id, preferred, status FROM main.item_link
                          WHERE item_id=? AND provider=? AND status IN ({_IN})''', (item_id, provider, *CONFIRMED)).fetchall()
    scoped = [r for r in rows if color_id is not None and r['color_id'] == color_id]
    pool = scoped or [r for r in rows if r['color_id'] is None]
    if not pool:
        return None
    best = min(pool, key=lambda r: (-r['preferred'], _RANK[r['status']], r['provider_key']))
    colour = db.execute(f'''SELECT provider_key FROM main.color_link WHERE color_id=? AND provider=? AND status IN ({_IN})
                            ORDER BY CASE status WHEN 'manual' THEN 0 WHEN 'matched' THEN 1 ELSE 2 END, provider_key''',
                        (color_id, provider, *CONFIRMED)).fetchone()
    return best['provider_kind'], best['provider_key'], colour[0] if colour else None


def _inverse_color(db, provider, key):
    """The Rebrickable colour of a provider colour key: collection rows win, then the catalogue; inverse_preferred first."""
    if key is None:
        return 1                                           # "no colour"
    found = {}
    stores = ['main'] + (['catalogue'] if has_catalogue(db) else [])
    for rank, store in enumerate(stores):
        for color_id, flag in db.execute(f'''SELECT color_id, inverse_preferred FROM {store}.color_link
                                             WHERE provider=? AND provider_key=? AND status IN ({_IN})''', (provider, str(key), *CONFIRMED)):
            found.setdefault(color_id, (-flag, rank))      # a collection row hides the catalogue's row of the same colour
    return min(found, key=lambda c: (*found[c], c)) if found else None


def resolve_inverse(db, provider_kind, provider_key, provider_color_key, provider='bricklink'):
    """Which (item, colour) does a provider key stand for? The inverse of resolve; None if nothing links to it.

    Searches the collection's links, then the catalogue's. A link scoped to the colour wins over an unscoped one, and an
    unscoped link does not apply when its item has a link scoped to that colour (the leg rule). Several items -> AmbiguousIdentity."""
    colour = _inverse_color(db, provider, provider_color_key)
    if colour is None:
        return None
    for store in ['main'] + (['catalogue'] if has_catalogue(db) else []):
        rows = db.execute(f'''SELECT item_id, color_id FROM {store}.item_link
                              WHERE provider=? AND provider_kind=? AND provider_key=? AND status IN ({_IN})''',
                          (provider, provider_kind, provider_key, *CONFIRMED)).fetchall()
        items = sorted({
            r['item_id'] for r in rows
            if r['color_id'] == colour or (r['color_id'] is None and not db.execute(
                f'''SELECT 1 FROM {store}.item_link WHERE item_id=? AND provider=? AND color_id=? AND status IN ({_IN})''',
                (r['item_id'], provider, colour, *CONFIRMED)).fetchone())})
        if len(items) > 1:
            raise AmbiguousIdentity(f'{provider} {provider_kind} {provider_key} (colour {provider_color_key}) names items {items}', items)
        if items:
            return items[0], colour
    return None
