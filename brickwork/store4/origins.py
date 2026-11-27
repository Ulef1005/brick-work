"""Where a row came from (#551, schema 4.8; ADR 0039): Added via and Last synced from.

**Added via** is one fixed value on every copy, loose-stock row and wish, written when the row is made and never changed (a trigger refuses
it). Every route that makes a row writes `current()`: "hand" unless the caller is inside `adding(<origin>)` (which a sync run, a file
import or the import from another app opens around its writes) or a channel (`api`, `cli`, `mcp`) is set. A row older than 4.8 keeps NULL and reads "Before this release".

**Last synced from** (`synced_from`) is a separate fact: a row added by hand can be matched by a later sync. One row per site and list
(list_key '' is the site's collection as a whole); `touch` writes or refreshes one and returns what Undo needs, `untouch` takes it back.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from .errors import Store4Error

HAND = 'hand'
# id -> kind; the same rows as `origin` in added_via.sql (tests/test_origins.py pins the two together)
ORIGINS = {
    'hand': 'hand',
    'api': 'channel', 'cli': 'channel', 'mcp': 'channel',
    'rebrickable': 'site', 'brickset': 'site', 'bricklink': 'site', 'brickowl': 'site',
    'bricklink_xml': 'file', 'rebrickable_csv': 'file', 'brickset_csv': 'file', 'brickowl_xml': 'file', 'brickwork_export': 'file',
    'bricktracker': 'import',
}
SITES = tuple(o for o, kind in ORIGINS.items() if kind == 'site')
CHANNELS = tuple(o for o, kind in ORIGINS.items() if kind == 'channel')
LABELS = {
    'hand': 'By hand',
    'api': 'Via the API', 'cli': 'Via the CLI', 'mcp': 'Via MCP',
    'rebrickable': 'Rebrickable sync', 'brickset': 'Brickset sync', 'bricklink': 'BrickLink sync', 'brickowl': 'Brick Owl sync',
    'bricklink_xml': 'BrickLink file', 'rebrickable_csv': 'Rebrickable file', 'brickset_csv': 'Brickset file', 'brickowl_xml': 'Brick Owl file',
    'brickwork_export': 'Brick Work export',
    'bricktracker': 'BrickTracker import',
    None: 'Before this release',
}
SITE_NAMES = {'rebrickable': 'Rebrickable', 'brickset': 'Brickset', 'bricklink': 'BrickLink', 'brickowl': 'Brick Owl'}
TABLES = {'copy': 'copy_id', 'stock': 'stock_id', 'wish': 'wish_id'}

_current = ContextVar('brickwork_added_via', default=None)
_channel = ContextVar('brickwork_channel', default=None)


def current():
    """The Added via value for a row made now: the innermost `adding(...)`, else the channel when set, else "hand"."""
    return _current.get() or _channel.get() or HAND


@contextmanager
def adding(origin):
    """Every copy, stock row and wish made inside this block records `origin` as its Added via."""
    if origin not in ORIGINS:
        raise Store4Error(f'unknown origin {origin!r}')
    token = _current.set(origin)
    try:
        yield origin
    finally:
        _current.reset(token)


@contextmanager
def channel(name):
    """Set the writer's channel (`api`, `cli`, `mcp`, or None to clear it) for rows made outside `adding(...)`."""
    if name is not None and name not in CHANNELS:
        raise Store4Error(f'{name!r} is not a channel')
    token = _channel.set(name)
    try:
        yield name
    finally:
        _channel.reset(token)


def label(origin):
    return LABELS.get(origin, origin)


def _column(table):
    if table not in TABLES:
        raise Store4Error(f'{table} has no source')
    return TABLES[table]


def touch(db, table, row_id, site, *, at, list_key='', list_name=None):
    """Record that `row_id` of `table` was matched to `site` (and its list) at `at`. Returns the compact entry a run's receipt keeps for Undo,
    `{id, b, a}`: `b` is `[list_name, synced_at]` before (None when the row is new), `a` the same after. Inside the caller's write transaction."""
    if site not in SITES:
        raise Store4Error(f'{site!r} is not a sync site')
    column = _column(table)
    found = db.execute(f'SELECT id, list_name, synced_at FROM main.synced_from WHERE {column}=? AND site=? AND list_key=?',
                       (row_id, site, list_key)).fetchone()
    if found:
        db.execute('UPDATE main.synced_from SET list_name=?, synced_at=? WHERE id=?', (list_name, at, found['id']))
        return dict(id=found['id'], b=[found['list_name'], found['synced_at']], a=[list_name, at])
    rid = db.execute(f'INSERT INTO main.synced_from({column}, site, list_key, list_name, synced_at) VALUES(?, ?, ?, ?, ?)',
                     (row_id, site, list_key, list_name, at)).lastrowid
    return dict(id=rid, b=None, a=[list_name, at])


def untouch(db, entry):
    """Take one `touch` (or `rename_list`) entry back. A row a later run changed again (it no longer reads as this run left it) is left to
    that run: returns False."""
    row = db.execute('SELECT list_name, synced_at FROM main.synced_from WHERE id=?', (entry['id'],)).fetchone()
    if row is None or [row['list_name'], row['synced_at']] != entry['a']:
        return False
    if entry['b'] is None:
        db.execute('DELETE FROM main.synced_from WHERE id=?', (entry['id'],))
    else:
        db.execute('UPDATE main.synced_from SET list_name=?, synced_at=? WHERE id=?', (*entry['b'], entry['id']))
    return True


def rename_list(db, site, list_key, list_name):
    """A list renamed at the site (#531): the new name on every row that carries the list. Returns the rows changed, as `touch` entries."""
    out = []
    for row in db.execute('SELECT id, list_name, synced_at FROM main.synced_from WHERE site=? AND list_key=? AND list_name IS NOT ?',
                          (site, list_key, list_name)).fetchall():
        db.execute('UPDATE main.synced_from SET list_name=? WHERE id=?', (list_name, row['id']))
        out.append(dict(id=row['id'], b=[row['list_name'], row['synced_at']], a=[list_name, row['synced_at']]))
    return out


def drop_list(db, site, list_key):
    """A list removed at the site (#531, "Drop the name"): every row's source detail for it goes; the rows themselves stay. Returns the
    removed `synced_from` rows whole, for `restore`."""
    rows = [dict(r) for r in db.execute('SELECT * FROM main.synced_from WHERE site=? AND list_key=? ORDER BY id', (site, list_key))]
    db.execute('DELETE FROM main.synced_from WHERE site=? AND list_key=?', (site, list_key))
    return rows


def restore(db, rows):
    """Put back rows `drop_list` removed, unless the parent row is gone or a later run made a row for the same row, site and list meanwhile."""
    for row in rows:
        table, column = next((t, c) for t, c in TABLES.items() if row[c] is not None)
        if not db.execute(f'SELECT 1 FROM main.{table} WHERE id=?', (row[column],)).fetchone():
            continue
        if db.execute(f'SELECT 1 FROM main.synced_from WHERE {column}=? AND site=? AND list_key=?',
                      (row[column], row['site'], row['list_key'])).fetchone():
            continue
        db.execute('INSERT INTO main.synced_from(id, copy_id, stock_id, wish_id, site, list_key, list_name, synced_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)',
                   (row['id'], row['copy_id'], row['stock_id'], row['wish_id'], row['site'], row['list_key'], row['list_name'], row['synced_at']))


def _live_lists(db, site):
    """Per recorded list_key of `site`: `(counts per list_name across live rows, set of live item ids)`."""
    counts, items = {}, {}
    for r in db.execute(
        '''SELECT f.list_key, f.list_name, coalesce(c.item_id, s.item_id, w.item_id) AS item_id FROM main.synced_from f
           LEFT JOIN main.copy c ON c.id=f.copy_id AND c.archived_at IS NULL
           LEFT JOIN main.stock s ON s.id=f.stock_id AND s.archived_at IS NULL AND s.quantity>0
           LEFT JOIN main.wish w ON w.id=f.wish_id AND w.archived_at IS NULL
           WHERE f.site=? AND f.list_key!='' AND f.list_key NOT GLOB 'part:*' AND coalesce(c.item_id, s.item_id, w.item_id) IS NOT NULL
           ORDER BY f.list_key''', (site,)):
        by_name = counts.setdefault(r['list_key'], {})
        by_name[r['list_name']] = by_name.get(r['list_name'], 0) + 1
        items.setdefault(r['list_key'], set()).add(r['item_id'])
    return counts, items


def lists_of(db, site):
    """`{list_key: (list_name, number of live items carrying it)}` for the site's named lists as this collection last recorded them."""
    counts, items = _live_lists(db, site)
    return {key: (min(by_name, key=lambda n: (-by_name[n], n is None, n or '')), len(items[key]))
            for key, by_name in counts.items()}


def mixed_lists(db, site):
    """List keys of `site` whose live rows carry more than one recorded list name."""
    counts, _ = _live_lists(db, site)
    return {key for key, by_name in counts.items() if len(by_name) > 1}


def sources_of(db, table, ids):
    """`{row id: [{site, list_key, list_name, synced_at}, ...]}`, newest first, for the given rows of `table`."""
    column = _column(table)
    ids = list(ids)
    out = {i: [] for i in ids}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        for r in db.execute(f'SELECT {column} AS rid, site, list_key, list_name, synced_at FROM main.synced_from WHERE {column} IN '
                            f'({",".join("?" * len(chunk))}) ORDER BY synced_at DESC, site, list_key', chunk):
            out[r['rid']].append(dict(site=r['site'], list_key=r['list_key'], list_name=r['list_name'], synced_at=r['synced_at']))
    return out


def list_value(entry):
    """A `last synced from` entry as the Sets filter's value: the site, then the list key (URL-quoted, as a filter chip splits on a colon)."""
    from urllib.parse import quote
    return entry['site'] + '|' + quote(entry['list_key'] or '', safe='')


def list_label(entry):
    """The same entry as the filter chip's words: "Rebrickable · Main collection", or the site alone for a row with no list name."""
    return SITE_NAMES.get(entry['site'], entry['site']) + (' · ' + entry['list_name'] if entry['list_name'] else '')


def chip(added_via):
    """The chip's words (frame 44): the label alone for a row made by hand, through a channel or before 4.8, else "Added via <label>"."""
    return label(added_via) if added_via in (None, HAND) or added_via in CHANNELS else 'Added via ' + label(added_via)


def body(added_via, synced):
    """The API's read-only `source` object of a row."""
    return dict(added_via=added_via, added_via_label=label(added_via), last_synced_from=synced)
