"""Acquired part lists (design 2.4, 3.1, 3.2, 4.1, 6.3): the writers the BrickLink and Rebrickable adapters share.

Everything writes inside the caller's transaction, opening one if none is open, with a savepoint inside it (as `identity.project`
does), so an adapter wraps one whole fetch in one transaction and a refusal leaves nothing half-written. Items and colours a list
names must already be in the collection: the caller projects the catalogue's (`identity.project`) or creates the local ones here.
Events are written only when the caller passes an `audit.Events`."""
import hashlib
import json

from .bldigest import inventory_digest
from .connect import has_catalogue, now
from .errors import AmbiguousIdentity, Store4Error
from .identity import _RANK, _inverse_color, _savepoint
from .seeds import LOCAL_BASE


class LocalItemError(Store4Error):
    """A local item that cannot be created: its born key is taken by another kind, or by the catalogue."""


class InventoryError(Store4Error):
    """A fetched list that cannot be stored: empty, a bad quantity, or naming an item or colour the collection lacks."""


def _live(db, item_id):
    """Follow `merged_into` to the live item; None if the id is not in the collection."""
    seen = set()
    while item_id not in seen:
        seen.add(item_id)
        row = db.execute('SELECT merged_into FROM main.item WHERE id=?', (item_id,)).fetchone()
        if row is None:
            return None
        if row[0] is None:
            return item_id
        item_id = row[0]
    return None


def create_local_item(db, *, kind, born_provider, born_namespace, born_key, name, kind_source='namespace', year=None, num_parts=None,
                      events=None):
    """A collection-only item (design 3.1) for a key the catalogue does not hold; idempotent on its born key.

    An existing item with the key is returned (a merged one as its live target) if the kind agrees, else refused. A key the
    attached catalogue holds is refused: that item is projected, never shadowed by a local id."""
    # An unidentified item (no born key) is always a new one: NULL keys are distinct, as in the item_born index.
    row = None if born_key is None else db.execute(
        'SELECT id, kind FROM main.item WHERE born_provider IS ? AND born_namespace IS ? AND born_key=?',
        (born_provider, born_namespace, born_key)).fetchone()
    if row:
        if row['kind'] != kind:
            raise LocalItemError(f'item {row["id"]} ({born_provider} {born_namespace} {born_key}) is a {row["kind"]}, not a {kind}')
        live = _live(db, row['id'])
        if live is None:
            raise LocalItemError(f'item {row["id"]} has a broken merge chain')
        return live
    if has_catalogue(db) and db.execute('SELECT 1 FROM catalogue.item WHERE born_provider=? AND born_namespace=? AND born_key=?',
                                        (born_provider, born_namespace, born_key)).fetchone():
        raise LocalItemError(f'the catalogue holds {born_provider} {born_namespace} {born_key}; project that item instead of creating a local one')
    stamp = now()
    _savepoint(db, 'create_local_item')
    try:
        new_id = max(LOCAL_BASE - 1, db.execute('SELECT coalesce(max(id), 0) FROM main.item WHERE id>=?', (LOCAL_BASE,)).fetchone()[0]) + 1
        db.execute('''INSERT INTO main.item(id, origin, kind, kind_source, name, year, num_parts, born_provider, born_namespace, born_key,
                      created_at, updated_at) VALUES(?, 'local', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (new_id, kind, kind_source, name, year, num_parts, born_provider, born_namespace, born_key, stamp, stamp))
        if events:
            events.write('item', new_id, 'created', new={'kind': kind, 'born_provider': born_provider, 'born_namespace': born_namespace,
                                                         'born_key': born_key, 'name': name})
    except BaseException:
        db.execute('ROLLBACK TO create_local_item')
        raise
    finally:
        db.execute('RELEASE create_local_item')
    return new_id


def create_local_color(db, *, bricklink_key, name, events=None):
    """A BrickLink-born colour the catalogue lacks, with its matched BrickLink link; idempotent on the born key."""
    key = str(bricklink_key)
    row = db.execute("SELECT id FROM main.color WHERE born_provider='bricklink' AND born_key=?", (key,)).fetchone()
    if row:
        return row[0]
    # Any colour the inverse resolution finds, in the collection or the catalogue, owns the key; a shared key owns it too.
    try:
        owner = _inverse_color(db, 'bricklink', key)
    except AmbiguousIdentity:
        owner = 'several colours'
    if owner is not None:
        raise LocalItemError(f'BrickLink colour {key} already belongs to colour {owner}; use that one instead of creating a local colour')
    stamp = now()
    _savepoint(db, 'create_local_color')
    try:
        new_id = max(LOCAL_BASE - 1, db.execute('SELECT coalesce(max(id), 0) FROM main.color WHERE id>=?', (LOCAL_BASE,)).fetchone()[0]) + 1
        db.execute('''INSERT INTO main.color(id, origin, name, rgb, is_trans, born_provider, born_key, created_at, updated_at)
                      VALUES(?, 'local', ?, NULL, 0, 'bricklink', ?, ?, ?)''', (new_id, name, key, stamp, stamp))
        db.execute('''INSERT INTO main.color_link(color_id, provider, provider_key, provider_name, status, method, inverse_preferred, decided_at)
                      VALUES(?, 'bricklink', ?, ?, 'matched', 'bricklink_api', 1, ?)''', (new_id, key, name, stamp))
        if events:
            events.write('color', new_id, 'created', new={'born_provider': 'bricklink', 'born_key': key, 'name': name})
    except BaseException:
        db.execute('ROLLBACK TO create_local_color')
        raise
    finally:
        db.execute('RELEASE create_local_color')
    return new_id


def add_item_link(db, item_id, *, provider, provider_kind, provider_key, status, method, origin, color_id=None, evidence=None, events=None):
    """One provider link on an item; idempotent on the link key. An existing row is replaced only by a strictly stronger status
    (matched over to_check); a manual or matched row is never touched. Returns the row id."""
    row = db.execute('''SELECT id, status FROM main.item_link WHERE provider=? AND provider_kind=? AND provider_key=? AND item_id=?
                        AND color_key=coalesce(?, 0)''', (provider, provider_kind, provider_key, item_id, color_id)).fetchone()
    stamp = now()
    evidence_json = None if evidence is None else json.dumps(evidence, sort_keys=True)
    if row and (row['status'] in ('manual', 'matched') or _RANK.get(status, 3) >= _RANK.get(row['status'], 3)):
        return row['id']
    _savepoint(db, 'add_item_link')
    try:
        if row:
            link_id = row['id']
            db.execute('UPDATE main.item_link SET status=?, method=?, origin=?, evidence_json=?, decided_at=? WHERE id=?',
                       (status, method, origin, evidence_json, stamp, link_id))
            if events:
                events.write('item_link', link_id, 'status', old=row['status'], new=status)
        else:
            link_id = db.execute('''INSERT INTO main.item_link(item_id, color_id, provider, provider_kind, provider_key, status, method,
                                    origin, evidence_json, decided_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                 (item_id, color_id, provider, provider_kind, provider_key, status, method, origin, evidence_json,
                                  stamp)).lastrowid
            if events:
                events.write('item_link', link_id, 'created', new={'item_id': item_id, 'color_id': color_id, 'provider': provider,
                                                                   'provider_kind': provider_kind, 'provider_key': provider_key,
                                                                   'status': status, 'method': method})
    except BaseException:
        db.execute('ROLLBACK TO add_item_link')
        raise
    finally:
        db.execute('RELEASE add_item_link')
    return link_id


def store_source_record(db, *, source, kind, key, payload, job_id=None, status='ok'):
    """Keep a raw API reply as text (a dict or list is dumped with sorted keys); the same reply is kept once."""
    text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(text.encode()).hexdigest()
    row = db.execute('SELECT id FROM main.source_record WHERE source=? AND kind=? AND key=? AND digest=?', (source, kind, key, digest)).fetchone()
    if row:
        return row[0]
    return db.execute('''INSERT INTO main.source_record(source, kind, key, payload, digest, bytes, job_id, fetched_at, status)
                         VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (source, kind, key, text, digest, len(text.encode()), job_id, now(), status)).lastrowid


def _quantity(q, line):
    if isinstance(q, bool) or not isinstance(q, int) or q <= 0:
        raise InventoryError(f'line {line} has quantity {q!r}; a positive integer is needed')
    return q


def write_fetched(db, item_id, source, part_lines, figure_lines=(), *, provider_version=None, job_id=None, source_record_id=None,
                  events=None):
    """Store a fetched part list for a set or figure as the next version of (item, source); returns the fetched_inventory id.

    `part_lines` are `(item_id, color_id, is_spare, quantity)`, `figure_lines` `(figure_item_id, quantity)`; lines with one key
    are summed. The previous latest of the pair stays, no longer latest (copies were built from it)."""
    parts, figures = {}, {}
    for line in part_lines:
        item, color, spare, q = line
        k = (item, color, int(bool(spare)))
        parts[k] = parts.get(k, 0) + _quantity(q, line)
    for line in figure_lines:
        item, q = line
        figures[item] = figures.get(item, 0) + _quantity(q, line)
    if not parts and not figures:
        raise InventoryError(f'the fetched list for item {item_id} ({source}) is empty')
    for what, table, ids in (('item', 'item', {item_id} | {k[0] for k in parts} | set(figures)), ('colour', 'color', {k[1] for k in parts})):
        missing = sorted(i for i in ids if not db.execute(f'SELECT 1 FROM main.{table} WHERE id=?', (i,)).fetchone())
        if missing:
            raise InventoryError(f'the fetched list for item {item_id} names {what} {missing[0]}, which the collection does not have'
                                 + (f' (also {missing[1:]})' if len(missing) > 1 else ''))
    part_rows = [(i, c, s, q) for (i, c, s), q in parts.items()]
    figure_rows = list(figures.items())
    digest = inventory_digest(part_rows, figure_rows)
    _savepoint(db, 'write_fetched')
    try:
        seq = db.execute('SELECT coalesce(max(seq), 0) + 1 FROM main.fetched_inventory WHERE item_id=? AND source=?', (item_id, source)).fetchone()[0]
        db.execute('UPDATE main.fetched_inventory SET is_latest=0 WHERE item_id=? AND source=? AND is_latest=1', (item_id, source))
        fid = db.execute('''INSERT INTO main.fetched_inventory(item_id, source, seq, is_latest, provider_version, job_id, source_record_id,
                            fetched_at, digest, part_lines, figure_lines) VALUES(?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)''',
                         (item_id, source, seq, provider_version, job_id, source_record_id, now(), digest,
                          len(part_rows), len(figure_rows))).lastrowid
        db.executemany('INSERT INTO main.fetched_inventory_part(fetched_inventory_id, item_id, color_id, is_spare, quantity) VALUES(?, ?, ?, ?, ?)',
                       [(fid, *r) for r in part_rows])
        db.executemany('INSERT INTO main.fetched_inventory_figure(fetched_inventory_id, item_id, quantity) VALUES(?, ?, ?)',
                       [(fid, *r) for r in figure_rows])
        if events:
            events.write('fetched_inventory', fid, 'created', new={'item_id': item_id, 'source': source, 'seq': seq, 'digest': digest,
                                                                   'part_lines': len(part_rows), 'figure_lines': len(figure_rows)})
    except BaseException:
        db.execute('ROLLBACK TO write_fetched')
        raise
    finally:
        db.execute('RELEASE write_fetched')
    return fid
