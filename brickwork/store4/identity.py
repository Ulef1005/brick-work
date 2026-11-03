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


def _savepoint(db, name):
    # A savepoint outside a transaction would commit on release: open the caller's transaction first.
    if not db.in_transaction:
        db.execute('BEGIN')
    db.execute(f'SAVEPOINT {name}')


def project(db, item_id):
    """Copy a catalogue item, its links and the colours they name into the collection (design 6.3).

    Idempotent; writes inside the caller's transaction, opening one if none is open, so the caller's commit or rollback
    decides (a savepoint inside it, so a refusal leaves nothing half-copied)."""
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
    _savepoint(db, 'project')
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


FIXED_COLORS = (1, 2)                                      # "no colour" and "unknown": rows exist from setup, links come with the catalogue


def held_colour_keys(db):
    """{(provider, provider_key): colours holding it through a manual or matched collection link} - the protected state
    project_color measures against; activation takes it once, before it projects anything."""
    held = {}
    for provider, key, colour in db.execute("SELECT provider, provider_key, color_id FROM main.color_link WHERE status IN ('manual', 'matched')"):
        held.setdefault((provider, key), set()).add(colour)
    return held


def project_color(db, color_id, held=None):
    """Copy a catalogue colour and its colour links; idempotent. Like project(), inside the caller's transaction."""
    exists = db.execute('SELECT 1 FROM main.color WHERE id=?', (color_id,)).fetchone()
    if exists and (color_id not in FIXED_COLORS or not has_catalogue(db) or
                   db.execute('SELECT 1 FROM main.color_link WHERE color_id=?', (color_id,)).fetchone()):
        return color_id
    _need_catalogue(db, f'projecting colour {color_id}')
    row = db.execute('SELECT * FROM catalogue.color WHERE id=?', (color_id,)).fetchone()
    if row is None:
        if exists:
            return color_id
        raise NotInCatalogue(f'colour {color_id} is not in the catalogue')
    links = db.execute('SELECT * FROM catalogue.color_link WHERE color_id=? ORDER BY id', (color_id,)).fetchall()
    _activated(db, [row['build_id']] + [k['build_id'] for k in links], f'colour {color_id}')
    stamp = now()
    # One colour holds the inverse preference of a provider key (color_link_inverse). If the collection's holder differs
    # from the catalogue's, the new row is projected without the flag: reconcile reports the move, never applies it.
    taken = {(r[0], r[1]) for r in db.execute('SELECT provider, provider_key FROM main.color_link WHERE inverse_preferred=1')}
    # A provider colour key another collection colour already holds through a manual or matched link is not taken over here:
    # the colour is projected without that link, and reconcile inserts it under its resolution guard (or reports it).
    held = held_colour_keys(db) if held is None else held
    links = [k for k in links if not held.get((k['provider'], k['provider_key']), set()) - {color_id}]
    _savepoint(db, 'project_color')
    try:
        if not exists:
            db.execute('''INSERT INTO main.color(id, origin, name, rgb, is_trans, born_provider, born_key, created_at, updated_at)
                          VALUES(?, 'catalogue', ?, ?, ?, ?, ?, ?, ?)''',
                       (color_id, row['name'], row['rgb'], row['is_trans'], row['born_provider'], row['born_key'], stamp, stamp))
        db.executemany('''INSERT INTO main.color_link(color_id, provider, provider_key, provider_name, status, method, inverse_preferred,
                          catalogue_build_id, decided_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       [(color_id, k['provider'], k['provider_key'], k['provider_name'], k['status'], k['method'],
                         int(bool(k['inverse_preferred']) and (k['provider'], k['provider_key']) not in taken), k['build_id'], stamp) for k in links])
    except BaseException:
        db.execute('ROLLBACK TO project_color')
        raise
    finally:
        db.execute('RELEASE project_color')
    return color_id


def item_link_order(preferred, status, provider_kind, provider_key):
    """The sort key of an item link among its rivals: preferred, status, key, and the kind only as the last tie-breaker."""
    return -preferred, _RANK[status], provider_key, provider_kind


def color_link_order(status, provider_key):
    return _RANK[status], provider_key


def best_item_link(rows, color_id):
    """The one ranking of item links: among the confirmed rows (dicts with provider_kind, provider_key, color_id, preferred,
    status), those scoped to the colour, else the unscoped ones, ordered by `item_link_order`. resolve(), reconcile's
    resolution guard and the catalogue builder's bl_digest all use it, so they can never disagree. None if nothing applies."""
    scoped = [r for r in rows if color_id is not None and r['color_id'] == color_id]
    pool = scoped or [r for r in rows if r['color_id'] is None]
    return min(pool, key=lambda r: item_link_order(r['preferred'], r['status'], r['provider_kind'], r['provider_key'])) if pool else None


def best_color_link(rows):
    """The one ranking of a colour's links of one provider (confirmed rows): status, then key."""
    return min(rows, key=lambda r: color_link_order(r['status'], r['provider_key'])) if rows else None


def confirmed_item_links(db, item_id, provider):
    return [dict(r) for r in db.execute(f'''SELECT provider_kind, provider_key, color_id, preferred, status FROM main.item_link
                                         WHERE item_id=? AND provider=? AND status IN ({_IN})''', (item_id, provider, *CONFIRMED))]


def confirmed_color_links(db, color_id, provider):
    return [dict(r) for r in db.execute(f'''SELECT provider_key, status FROM main.color_link WHERE color_id=? AND provider=? AND status IN ({_IN})''',
                                        (color_id, provider, *CONFIRMED))]


def resolve(db, item_id, color_id, provider='bricklink'):
    """Which provider key and colour is the item in this colour? (design 3.2) -> (kind, key, colour key) or None."""
    best = best_item_link(confirmed_item_links(db, item_id, provider), color_id)
    if best is None:
        return None
    colour = best_color_link(confirmed_color_links(db, color_id, provider))
    return best['provider_kind'], best['provider_key'], colour['provider_key'] if colour else None


def _inverse_color(db, provider, key):
    """The Rebrickable colour of a provider colour key: collection rows win, then the catalogue; inverse_preferred first."""
    if key is None:
        return 1                                           # "no colour"
    found = {}
    stores = ['main'] + (['catalogue'] if has_catalogue(db) else [])
    for rank, store in enumerate(stores):
        # The catalogue answers only for colours whose links the collection does not hold: a collection link,
        # whatever its status, overrides the catalogue's links of that colour.
        # A projected colour is the collection's: its links, or their absence, override the catalogue's (the fixed colours 1 and 2
        # exist from setup, and are the collection's only once they hold links).
        owned = '' if store == 'main' else (f"AND color_id NOT IN (SELECT color_id FROM main.color_link WHERE provider=?) "
                                            f"AND color_id NOT IN (SELECT id FROM main.color WHERE id NOT IN ({','.join(map(str, FIXED_COLORS))}))")
        args = (provider, str(key), *CONFIRMED) + (() if store == 'main' else (provider,))
        for color_id, flag in db.execute(f'''SELECT color_id, inverse_preferred FROM {store}.color_link
                                             WHERE provider=? AND provider_key=? AND status IN ({_IN}) {owned}''', args):
            found.setdefault(color_id, (flag, rank))
    if not found:
        return None
    preferred = sorted((rank, c) for c, (flag, rank) in found.items() if flag)
    if preferred:
        return preferred[0][1]
    if len(found) > 1:                                     # shared provider colour, none marked: never guess (design 3.2)
        raise AmbiguousIdentity(f'{provider} colour {key} names colours {sorted(found)}, none marked inverse_preferred', sorted(found))
    return next(iter(found))


def candidate_items(db, provider_kind, provider_key, color_id, provider='bricklink'):
    """Every item a provider key stands for in a Brick Work colour (the exhaustive inverse of design 3.2), sorted by id.

    Pools the collection's links and the catalogue's (for items not projected, as resolve_inverse does). A link scoped to the colour
    applies; an unscoped link applies only when its item has no link scoped to that colour (the leg rule). A collection `manual` link
    decides alone. `color_id` is a colour id, not a provider key, so a colour the provider keys do not know (a local one) still
    finds the unscoped links. resolve_inverse(exhaustive=True) is this plus the colour lookup and the ambiguity error."""
    pooled = set()
    for store in ['main'] + (['catalogue'] if has_catalogue(db) else []):
        owned = '' if store == 'main' else 'AND item_id NOT IN (SELECT id FROM main.item)'
        rows = db.execute(f'''SELECT item_id, color_id, status FROM {store}.item_link
                              WHERE provider=? AND provider_kind=? AND provider_key=? AND status IN ({_IN}) {owned}''',
                          (provider, provider_kind, provider_key, *CONFIRMED)).fetchall()
        items = sorted({
            r['item_id'] for r in rows
            if r['color_id'] == color_id or (r['color_id'] is None and not db.execute(
                f'''SELECT 1 FROM {store}.item_link WHERE item_id=? AND provider=? AND color_id=? AND status IN ({_IN})''',
                (r['item_id'], provider, color_id, *CONFIRMED)).fetchone())})
        manual = sorted({r['item_id'] for r in rows if r['status'] == 'manual' and r['item_id'] in items}) if store == 'main' else []
        if manual:
            return manual
        pooled.update(items)
    return sorted(pooled)


def resolve_inverse(db, provider_kind, provider_key, provider_color_key, provider='bricklink', *, exhaustive=False):
    """Which (item, colour) does a provider key stand for? The inverse of resolve; None if nothing links to it.

    Searches the collection's links, then the catalogue's for items not projected (a projected item's links are the
    collection's: an override or a to_check there is never undone by the catalogue's copy). A link scoped to the colour wins over an unscoped one, and an
    unscoped link does not apply when its item has a link scoped to that colour (the leg rule). Several items -> AmbiguousIdentity.

    `exhaustive` pools the collection's and the catalogue's candidates instead of stopping at the collection's: projecting one
    of several candidates must not make the key unambiguous for the next list. A collection `manual` link still decides alone."""
    colour = _inverse_color(db, provider, provider_color_key)
    if colour is None:
        return None
    if exhaustive:
        items = candidate_items(db, provider_kind, provider_key, colour, provider)
        if len(items) > 1:
            raise AmbiguousIdentity(f'{provider} {provider_kind} {provider_key} (colour {provider_color_key}) names items {items}', items)
        return (items[0], colour) if items else None
    for store in ['main'] + (['catalogue'] if has_catalogue(db) else []):
        owned = '' if store == 'main' else 'AND item_id NOT IN (SELECT id FROM main.item)'
        rows = db.execute(f'''SELECT item_id, color_id, status FROM {store}.item_link
                              WHERE provider=? AND provider_kind=? AND provider_key=? AND status IN ({_IN}) {owned}''',
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
