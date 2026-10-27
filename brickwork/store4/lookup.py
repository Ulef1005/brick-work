"""Reads for API v2 item addressing (M.11a, issue #113; design 3.1, 3.2, 3.6 and 7).

An item or colour is read from the collection when it is projected there, else from the attached catalogue, so every catalogue item is
addressable before it is first used. Nothing here writes. `item_body` and `color_body` are the two bodies of design 7; `find_items`
answers "which items does this provider number stand for?" and returns live ids only (a merged item is followed to its survivor)."""
from . import identity
from .connect import has_catalogue
from .errors import AmbiguousIdentity

KINDS = ('set', 'part', 'minifigure', 'instructions', 'box', 'gear', 'book', 'catalog')
BRICKLINK_TYPE = {'set': 'S', 'part': 'P', 'minifigure': 'M', 'instructions': 'I', 'box': 'O', 'gear': 'G', 'book': 'B', 'catalog': 'C'}
REBRICKABLE_NAMESPACE = {'set': 'sets', 'part': 'parts', 'minifigure': 'minifigs'}
PROVIDERS = ('bricklink', 'rebrickable')                   # the providers an item number is given in
COLOR_PROVIDERS = PROVIDERS + ('brickwork',)               # the colour spaces of a request (decision 4)
_CONFIRMED = identity.CONFIRMED
_IN = identity._IN


def _stores(db):
    return ['main'] + (['catalogue'] if has_catalogue(db) else [])


def item_row(db, item_id):
    """`(store, row)` of an item, the collection's row first; None when neither file has it."""
    for store in _stores(db):
        row = db.execute(f'SELECT * FROM {store}.item WHERE id=?', (item_id,)).fetchone()
        if row:
            return store, row
    return None


def live_id(db, item_id):
    """`(id of the live item, moved)` for an item id: a merged id is followed to its survivor (a chain too); None when the id is unknown
    or its chain is broken. `moved` is True when the id named a merged item."""
    seen, current = set(), item_id
    while True:
        found = item_row(db, current)
        if found is None or current in seen:
            return None
        target = found[1]['merged_into'] if found[0] == 'main' else None
        if target is None:
            return current, current != item_id
        seen.add(current)
        current = target


def _number(text):
    return int(text) if str(text).lstrip('-').isdigit() else text


def _bricklink_color(db, color_id):
    """The BrickLink colour id of a Brick Work colour (confirmed links, best first), or None."""
    for store in _stores(db):
        if db.execute(f'SELECT 1 FROM {store}.color WHERE id=?', (color_id,)).fetchone() is None:
            continue
        rows = [dict(r) for r in db.execute(f'''SELECT provider_key, status FROM {store}.color_link
                                                WHERE color_id=? AND provider='bricklink' AND status IN ({_IN})''', (color_id, *_CONFIRMED))]
        best = identity.best_color_link(rows)
        if best:
            return _number(best['provider_key'])
        row = db.execute(f'SELECT born_provider, born_key FROM {store}.color WHERE id=?', (color_id,)).fetchone()
        return _number(row['born_key']) if row['born_provider'] == 'bricklink' else None
    return None


def color_body(db, color_id):
    """`{id, name, rgb, bricklink_id, rebrickable_id}` (design 7), or None for an unknown colour."""
    for store in _stores(db):
        row = db.execute(f'SELECT * FROM {store}.color WHERE id=?', (color_id,)).fetchone()
        if row:
            return {'id': row['id'], 'name': row['name'], 'rgb': row['rgb'], 'bricklink_id': _bricklink_color(db, color_id),
                    'rebrickable_id': _number(row['born_key']) if row['born_provider'] == 'rebrickable' else None}
    return None


def colors(db):
    """Every colour body, by id (the collection's projected rows win over the catalogue's)."""
    ids = sorted({r[0] for store in _stores(db) for r in db.execute(f'SELECT id FROM {store}.color')})
    return [color_body(db, i) for i in ids]


def item_links(db, store, item_id):
    """The confirmed BrickLink links of an item as `[{type, no, color_id, preferred}]` (BrickLink colour ids), best first."""
    rows = db.execute(f'''SELECT provider_kind, provider_key, color_id, preferred, status FROM {store}.item_link
                          WHERE item_id=? AND provider='bricklink' AND status IN ({_IN})''', (item_id, *_CONFIRMED)).fetchall()
    rows = sorted(rows, key=lambda r: identity.item_link_order(r['preferred'], r['status'], r['provider_kind'], r['provider_key']))
    # color_id is the BrickLink colour; a link scoped to a colour that has no BrickLink id reads color_id null with color_scoped true, never as
    # "every colour" (brickwork_color_id names the scope in Brick Work's own space).
    return [{'type': r['provider_kind'], 'no': r['provider_key'], 'color_id': None if r['color_id'] is None else _bricklink_color(db, r['color_id']),
             'color_scoped': r['color_id'] is not None, 'brickwork_color_id': r['color_id'], 'preferred': bool(r['preferred'])} for r in rows]


def item_body(db, item_id):
    """`{id, kind, name, unidentified, bricklink: [{type, no, color_id, preferred}], rebrickable: {key} | None}` (design 7) of a live item.

    An unidentified item (design 3.8) is a local item that is not born at Rebrickable: no born key, or a BrickLink-only number. A
    BrickLink-born item with no link of its own lists its born number, unscoped."""
    found = item_row(db, item_id)
    if found is None:
        return None
    store, row = found
    bricklink = item_links(db, store, item_id)
    if row['born_provider'] == 'bricklink' and not any(l['type'] == row['born_namespace'] and l['no'] == row['born_key'] and not l['color_scoped']
                                                       for l in bricklink):
        bricklink.append({'type': row['born_namespace'], 'no': row['born_key'], 'color_id': None, 'color_scoped': False, 'brickwork_color_id': None,
                          'preferred': not any(not l['color_scoped'] for l in bricklink)})
    return {'id': row['id'], 'kind': row['kind'], 'name': row['name'],
            'unidentified': store == 'main' and row['origin'] == 'local' and row['born_provider'] != 'rebrickable',
            'bricklink': bricklink,
            'rebrickable': {'key': row['born_key']} if row['born_provider'] == 'rebrickable' else None}


def brickwork_color(db, provider, color):
    """The Brick Work colour id for a colour given in a provider's space (decision 4); ValueError if there is none."""
    if provider not in COLOR_PROVIDERS:
        raise ValueError(f'Unknown provider {provider!r}')
    try:
        number = int(color)
    except (TypeError, ValueError):
        raise ValueError('A colour is a whole number') from None
    found = None
    if provider == 'brickwork':
        found = number if color_body(db, number) else None
    elif provider == 'bricklink':
        try:
            found = identity._inverse_color(db, 'bricklink', number)
        except AmbiguousIdentity:                          # a shared BrickLink colour none of whose rows is preferred
            found = None
    else:
        for store in _stores(db):
            row = db.execute(f"SELECT id FROM {store}.color WHERE born_provider='rebrickable' AND born_key=?", (str(number),)).fetchone()
            if row:
                found = row[0]
                break
    if found is None:
        raise ValueError(f'No {provider} colour {color}')
    return found


def find_items(db, provider, kind, key, color_id=None):
    """The live item ids a provider number stands for, sorted. `color_id` is a Brick Work colour id (see `brickwork_color`) and scopes
    BrickLink links the way design 3.2 does (a colour-scoped link beats an unscoped one). A set number is the same at both providers,
    so a set is looked up at both. ValueError for a kind the provider has no numbers for."""
    if kind not in KINDS:
        raise ValueError(f'Unknown kind {kind!r}')
    if provider not in PROVIDERS:
        raise ValueError(f'Unknown provider {provider!r}')
    if provider == 'rebrickable' and kind not in REBRICKABLE_NAMESPACE:
        raise ValueError(f'Rebrickable has no numbers for kind {kind}')
    providers = PROVIDERS if kind == 'set' else (provider,)
    found = set()
    for source in providers:
        if source == 'rebrickable':
            for store in _stores(db):
                found.update(r[0] for r in db.execute(f"SELECT id FROM {store}.item WHERE born_provider='rebrickable' AND born_namespace=? AND born_key=?",
                                                      (REBRICKABLE_NAMESPACE[kind], key)))
            continue
        letter = BRICKLINK_TYPE[kind]
        if color_id is not None:
            found.update(identity.candidate_items(db, letter, key, color_id, 'bricklink'))
        else:
            for store in _stores(db):
                owned = '' if store == 'main' else 'AND item_id NOT IN (SELECT id FROM main.item)'
                found.update(r[0] for r in db.execute(f'''SELECT item_id FROM {store}.item_link WHERE provider='bricklink' AND provider_kind=?
                                                          AND provider_key=? AND status IN ({_IN}) {owned}''', (letter, key, *_CONFIRMED)))
        born = [r[0] for r in db.execute("SELECT id FROM main.item WHERE born_provider='bricklink' AND born_namespace=? AND born_key=?", (letter, key))]
        if color_id is not None:
            # A born number is an unscoped claim: a manual link for this number decides alone (design 3.2), and an item with a link scoped
            # to the colour does not answer for it by its unscoped born number (the leg rule).
            manual = db.execute(f"SELECT 1 FROM main.item_link WHERE provider='bricklink' AND provider_kind=? AND provider_key=? AND status='manual' "
                                f"AND (color_id=? OR color_id IS NULL)", (letter, key, color_id)).fetchone()
            born = [] if manual else [i for i in born if not db.execute(
                f'SELECT 1 FROM main.item_link WHERE item_id=? AND provider=? AND color_id=? AND status IN ({_IN})',
                (i, 'bricklink', color_id, *_CONFIRMED)).fetchone()]
        found.update(born)
    live = set()
    for item_id in found:
        target = live_id(db, item_id)
        if target:
            live.add(target[0])
    return sorted(live)
