"""Public v1 read projections over the core store; no Flask or network access.

Existing collection, matching, planning and ledger rules remain their owners.
New projections use bulk queries so list cost does not grow in SQL round trips.
"""
from collections import Counter, defaultdict
from contextlib import closing
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
from xml.etree import ElementTree as ET

from . import add, admin, checker, collection, completeness, errors, ledger, orders, planning
from . import collection_prices, workbench
from .secrets import secret_values
from .undo import undoable_sql, undone_sql  # noqa: F401 — moved to core/undo.py (M.8a); event pages embed them
from .sources.base import budget_used, now, redact



def decorate_many(db, rows):
    """API v1 only (moved here from core/add.py by M.8j; it reads the 3.3 tables and is rewritten with v2 in M.11): list-only identities, colours and local pictures, loaded in four queries.

    Uses the same picture priority and exact-colour fallback as ``decorate``.
    Collection counts are deliberately not part of this list projection.
    """
    priority = db.execute("SELECT value FROM settings WHERE key='source_priority'").fetchone()
    order = json.loads(priority[0]).get('pictures', {}) if priority else {}
    colors_by_id = {r['color_id']: dict(r) for r in db.execute('SELECT * FROM colors')}
    identities = json.dumps(list({(r.get('item_type'), r.get('item_no')) for r in rows}))
    scope = " (item_type,item_no) IN (SELECT json_extract(value,'$[0]'),json_extract(value,'$[1]') FROM json_each(?))"
    unresolved = {(r[0],r[1]) for r in db.execute("SELECT item_type,item_no FROM id_match WHERE status='to_check' AND" + scope, (identities,))}
    ranks = {}
    for kind in {r.get('item_type') for r in rows}:
        sources = [s.split(':')[0] for s in order.get(kind, order.get('*', ['bricklink', 'rebrickable']))]
        ranks[kind] = ({source: sources.index(source) for source in sources}, len(sources))
    pictures = {}
    # v3 constrains local_path to data/images with no traversal. File existence
    # and containment belong to bw_image, not a list projection.
    for position, r in enumerate(db.execute('SELECT id,item_type,item_no,color_id,source FROM item_images WHERE' + scope + ' ORDER BY fetched_at DESC,id DESC', (identities,))):
        sources, fallback = ranks[r['item_type']]
        candidate = (sources.get(r['source'], fallback), position, r['id'])
        key = r['item_type'], r['item_no'], r['color_id']
        if key not in pictures or candidate < pictures[key]:
            pictures[key] = candidate
    result = []
    for source in rows:
        row = dict(source)
        kind, number, color = row.get('item_type'), row.get('item_no'), row.get('color_id')
        images = [pictures[key] for key in {(kind, number, None), (kind, number, color)} if key in pictures]
        row['image'] = min(images)[2] if images else None
        row['unresolved'] = kind=='?' or (kind,number) in unresolved
        row['color_name'] = colors_by_id.get(color,{}).get('name') or row.get('colour_name')
        rgb = colors_by_id.get(color,{}).get('rgb') or ''
        row['rgb'] = rgb if re.fullmatch('[a-fA-F0-9]{6}',rgb) else None
        row['ink'] = add.colour_ink(row['rgb'])
        result.append(row)
    return result


def rows(db, sql, params=()):
    return [dict(r) for r in db.execute(sql, params)]


def one(db, sql, params=()):
    result = db.execute(sql, params).fetchone()
    if result is None:
        raise errors.NotFound()
    return dict(result)


def root(db):
    """The media root (#27): BW_MEDIA_PATH, or the folder that holds the database."""
    from .media import media_root
    return media_root(db)


def etag(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def serialize(value, secrets=None):
    """Enums are words, prices remain decimal strings, secrets never leave reads.

    The secret list is read once per call and shared by every nested string.
    """
    if secrets is None:
        secrets = secret_values()
    if isinstance(value, dict):
        result = {}
        for key, v in value.items():
            if key in ('path', 'local_path', 'ciphertext', 'hash', 'secret'):
                continue
            if key in ('pinned', 'enabled', 'has_thumb', 'checked', 'shown_on_grid') and v is not None:
                v = bool(v)
            if key in ('conditions', 'statuses') and isinstance(v, list):
                mapping = {'N': 'new', 'U': 'used', 'D': 'damaged', 'S': 'sealed', 'C': 'complete', 'I': 'incomplete'}
                v = [mapping.get(x, x) for x in v]
            if key == 'flags' and isinstance(v, list):
                v = [f['id'] if isinstance(f, dict) else f for f in v]
            if key == 'condition':
                v = {'N': 'new', 'U': 'used', 'D': 'damaged'}.get(v, v) if not isinstance(v, list) else v
            elif key in ('completeness', 'stored', 'derived', 'status') and isinstance(v, str):
                v = {'S': 'sealed', 'C': 'complete', 'I': 'incomplete'}.get(v, v)
            result[key] = serialize(v, secrets)
        return result
    if isinstance(value, (list, tuple)):
        return [serialize(v, secrets) for v in value]
    if isinstance(value, str):
        return redact(value, secrets)
    return value


def listing_record(raw):
    """Adapt public projections to the shared browser filter vocabulary."""
    r = dict(raw)
    r.update(type=r.get('item_type', ''), number=r.get('item_no') or r.get('set_no') or r.get('source_id') or r.get('source') or str(r.get('id') if r.get('id') is not None else r.get('color_id', '')),
             colour=r.get('color_name') or r.get('colour_name') or '',
             status=r.get('completeness') or r.get('status') or '',
             storage=r.get('storage_id') or 'null', place=r.get('purchase_location_id') or 'null',
             lot=r.get('lot_id') or 'null')
    flags = r.get('flags') or []
    r['flag_ids'] = [f['id'] for f in flags if isinstance(f, dict)]
    r['flags'] = [f['name'] if isinstance(f, dict) else f for f in flags]
    if isinstance(r.get('condition'), str):
        r['condition'] = {'new': 'N', 'used': 'U', 'damaged': 'D'}.get(r['condition'], r['condition'])
    r['has_file'] = bool(r.get('path'))
    r['failed'] = r.get('state') == 'failed' or any(s.get('state') == 'failed' for s in r.get('steps', []))
    r['owned'] = bool(r.get('owned'))
    r['parent'] = r.get('parent_minifig') or 'null'
    r['spare'] = bool(r.get('spare'))
    r['duplicates'] = r.get('duplicates', (r.get('quantity') or 0) > 1)
    p = r.get('display_price') or r.get('price')
    if isinstance(p, dict):
        r['price'] = [p.get('currency') or 'Currency not recorded', p.get('price')] if p.get('price') is not None else None
    elif isinstance(p, str):
        r['price'] = [r.get('currency') or 'Currency not recorded', p]
    r['missing'] = r.get('missing') or r.get('need') or 0
    if r.get('group') in ('ranked', 'free_repairs', 'outside', 'needs_evidence'):
        r['ranking'] = planning.ranking_cursor_key(raw)
    return r


def items(db):
    values = rows(db, 'SELECT * FROM items')
    props = collection.properties(db)
    owned = {(r[0], r[1]): r[2] for r in db.execute('''SELECT item_type,item_no,sum(quantity) FROM (
        SELECT item_type,set_no item_no,1 quantity FROM copies WHERE archived_at IS NULL UNION ALL
        SELECT item_type,item_no,coalesce(quantity,0) FROM loose_stock WHERE archived_at IS NULL) GROUP BY 1,2''')}
    for r in values:
        r['owned'] = owned.get((r['item_type'], r['item_no']), 0)
        r['properties'] = props[r['item_type'], r['item_no']]
        r['theme'] = r['properties'].get('theme', {}).get('value', '')
    return decorate_many(db, values)


def item(db, kind, number):
    one(db, 'SELECT 1 FROM items WHERE item_type=? AND item_no=?', (kind, number))
    value = collection.detail(db, kind, number)
    summary = add.decorate(db, dict(item_type=kind, item_no=number))
    return dict(item={k: value.get(k) for k in ('item_type', 'item_no', 'name', 'category', 'year', 'image', 'unresolved')},
                properties=value['properties'], counts={k: summary[k] for k in ('owned', 'wished')},
                copies=[r for r in value['instances'] if r['entity'] == 'copy'],
                stock=[r for r in value['instances'] if r['entity'] == 'stock'],
                wishes=[r for r in entities(db, 'wish') if (r['item_type'], r['item_no']) == (kind, number)],
                prices=value['prices'], inventory=inventory(db, kind, number), matches=value['matches'])


def entities(db, entity, identifier=None):
    """Every row of one entity, or with ``identifier`` only that row through keyed lookups."""
    keyed = identifier is not None
    if entity == 'wish':
        result = rows(db, """SELECT w.*,i.name,i.category,i.year,'wish' entity FROM wishlist w
            JOIN items i USING(item_type,item_no)""" + (' WHERE w.id=?' if keyed else ''), (identifier,) if keyed else ())
        if keyed:
            result = [r for r in result if str(r['id']) == str(identifier)]
        flags = defaultdict(list)
        for f in rows(db, """SELECT a.entity_id,f.* FROM item_flags a JOIN flags f ON f.id=a.flag_id
                             WHERE a.entity_type='wishlist' AND f.archived_at IS NULL""" +
                      (' AND a.entity_id=?' if keyed else '') + ' ORDER BY f.id', (str(identifier),) if keyed else ()):
            flags[str(f.pop('entity_id'))].append(f)
        for r in result:
            r['flags'] = flags[str(r['id'])]
        from . import wish_progress
        wish_progress.annotate(db, result)
    elif keyed:
        found = collection.instance(db, entity, identifier)
        result = [found] if found else []
    else:
        result = [r for r in collection.instances(db, include_archived=True) if r['entity'] == entity]
    if not result:
        return []
    priority = collection_prices.priority(db)
    if keyed:
        first = result[0]
        key = first['item_type'], first['item_no'], first.get('color_id')
        props = collection.properties(db, key[0], [key[1]])
        market = {key: collection.prices(db, *key)}
        if entity == 'wish':
            counts = Counter()
        else:
            query = ('SELECT count(*) FROM copies WHERE item_type=? AND set_no=? AND archived_at IS NULL' if entity == 'copy' else
                     'SELECT count(*) FROM loose_stock WHERE item_type=? AND item_no=? AND color_id IS ? AND archived_at IS NULL')
            counts = Counter({key: db.execute(query, key[:2] if entity == 'copy' else key).fetchone()[0]})
    else:
        props = collection.properties(db)
        market = collection.prices(db)
        counts = Counter((r['item_type'], r['item_no'], r.get('color_id')) for r in result if not r.get('archived_at'))
    for r in result:
        r['prices'] = market[r['item_type'], r['item_no'], r.get('color_id')]
        r['price'] = collection_prices.choose([p for p in r['prices'] if p['guide'] == 'sold' and p.get('slot') != 'boxed'], r['item_type'], priority, 'U')
        r['duplicates'] = entity != 'wish' and counts[r['item_type'], r['item_no'], r.get('color_id')] > 1
        r['theme'] = props[r['item_type'], r['item_no']].get('theme', {}).get('value', '')
    result = decorate_many(db, result)
    if entity == 'wish':
        # The same quote selection and currency rule as the web's Under max.
        result = planning.display_prices(db, result, *(key[:2] if keyed else ()))
        for r in result:
            r['max_state'], r['max_margin'] = planning.max_comparison(r)
    return result


def entity(db, name, identifier):
    result = next(iter(entities(db, name, identifier)), None)
    if result is None:
        raise errors.NotFound()
    return result


def child_rows(db, resource, identifier):
    entity(db, 'stock' if resource == 'stock-parts' else 'copy', identifier)
    if resource == 'figures':
        return rows(db, '''SELECT f.*,f.minifig_no item_no,i.name,coalesce(c.lines,0) parts_lines,
            coalesce(c.missing,0) parts_missing FROM copy_minifigs f JOIN items i
            ON i.item_type=f.item_type AND i.item_no=f.minifig_no
            LEFT JOIN (SELECT parent_minifig_type,parent_minifig,count(*) lines,sum(coalesce(missing,0)) missing
                FROM copy_parts WHERE copy_id=? AND parent_minifig IS NOT NULL
                GROUP BY parent_minifig_type,parent_minifig) c
            ON c.parent_minifig_type=f.item_type AND c.parent_minifig=f.minifig_no WHERE f.copy_id=?''', (identifier,identifier))
    table, field = ('loose_minifig_parts', 'stock_id') if resource == 'stock-parts' else ('copy_parts', 'copy_id')
    return rows(db, f'''SELECT p.*,i.name,c.name color_name FROM {table} p JOIN items i USING(item_type,item_no)
        LEFT JOIN colors c USING(color_id) WHERE {field}=?''', (identifier,))


def inventory(db, kind, number):
    one(db, 'SELECT 1 FROM items WHERE item_type=? AND item_no=?', (kind, number))
    return rows(db, '''SELECT l.*,l.child_item_type item_type,l.child_item_no item_no,i.name,c.name color_name
        FROM inventory_lines l JOIN items i ON i.item_type=l.child_item_type AND i.item_no=l.child_item_no
        LEFT JOIN colors c USING(color_id) WHERE parent_item_type=? AND parent_item_no=?''', (kind, number))


def used_in(db, kind, number):
    one(db, 'SELECT 1 FROM items WHERE item_type=? AND item_no=?', (kind, number))
    return rows(db, """WITH components AS (
        SELECT copy_id,color_id,coalesce(quantity,0) quantity,coalesce(missing,0) missing
        FROM copy_parts WHERE item_type=? AND item_no=? UNION ALL
        SELECT copy_id,NULL,coalesce(quantity,0),coalesce(missing,0)
        FROM copy_minifigs WHERE item_type=? AND minifig_no=?),
        used AS (SELECT copy_id,sum(quantity) quantity,sum(missing) missing,
            CASE WHEN count(DISTINCT color_id)=1 THEN min(color_id) END color_id
            FROM components GROUP BY copy_id)
        SELECT c.id,c.id copy_id,c.item_type,c.set_no item_no,i.name,u.quantity,u.missing,u.color_id
        FROM used u JOIN copies c ON c.id=u.copy_id JOIN items i
        ON i.item_type=c.item_type AND i.item_no=c.set_no WHERE c.archived_at IS NULL""", (kind, number, kind, number))


def item_colors(db, kind, number):
    one(db, 'SELECT 1 FROM items WHERE item_type=? AND item_no=?', (kind, number))
    return rows(db, '''SELECT c.* FROM colors c WHERE color_id IN (
        SELECT color_id FROM inventory_lines WHERE child_item_type=? AND child_item_no=? UNION
        SELECT color_id FROM loose_stock WHERE item_type=? AND item_no=? UNION
        SELECT color_id FROM price_observations WHERE item_type=? AND item_no=? UNION
        SELECT color_id FROM item_images WHERE item_type=? AND item_no=? UNION
        SELECT color_id FROM copy_parts WHERE item_type=? AND item_no=? UNION
        SELECT color_id FROM loose_minifig_parts WHERE item_type=? AND item_no=? UNION
        SELECT color_id FROM wishlist WHERE item_type=? AND item_no=?)''', (kind, number)*7)


def images(db, kind, number):
    one(db, 'SELECT 1 FROM items WHERE item_type=? AND item_no=?', (kind, number))
    return [dict(r, content_url='/api/v1/images/' + str(r['id']) + '/content') for r in rows(db, 'SELECT * FROM item_images WHERE item_type=? AND item_no=?', (kind, number))]


def current_prices(db, kind=None, number=None):
    if kind is None:
        from .api_pages import page
        return page(db,'prices',{})['data']
    return collection.decorate_prices(rows(db, """SELECT p.*,o.source,o.price,o.min,o.max,o.qty,o.sold,o.observed_at,o.error,
        f.max_age_days FROM price_current p JOIN price_observations o ON o.id=p.observation_id
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE p.item_type=? AND p.item_no=?""", (kind, number)))


def price_history(db, kind, number):
    one(db, 'SELECT 1 FROM items WHERE item_type=? AND item_no=?', (kind, number))
    return rows(db, 'SELECT * FROM price_observations WHERE item_type=? AND item_no=? ORDER BY id DESC LIMIT 200', (kind, number))


def lots(db):
    return rows(db, '''SELECT l.*,coalesce(s.entries,0) entries,coalesce(s.quantity,0) quantity FROM lots l
        LEFT JOIN (SELECT lot_id,count(*) entries,sum(quantity) quantity FROM loose_stock
        WHERE archived_at IS NULL GROUP BY lot_id) s ON s.lot_id=l.id''')


def storages(db):
    # Retain the ledger counts and virtual location, and expose archived locations.
    values = ledger.storages(db)
    for r in values:
        if r['id'] is None:
            r['id'] = 'unstored'
    return values + rows(db, 'SELECT * FROM storages WHERE archived_at IS NOT NULL')


def storage(db, identifier):
    key = None if identifier == 'unstored' else identifier
    archived = db.execute('SELECT * FROM storages WHERE id=? AND archived_at IS NOT NULL', (key,)).fetchone()
    if archived:
        return dict(location=dict(archived), rows=[dict(r, entity=t) for t, r in ledger.storage_contents(db, key)])
    if key is not None:
        one(db, 'SELECT 1 FROM storages WHERE id=?', (key,))
    return ledger.storage_detail(db, key)


def places(db):
    values = collection.purchase_places(db)
    known = {r['id'] for r in values}
    return values + [r for r in rows(db, 'SELECT * FROM purchase_locations') if r['id'] not in known]


def jobs(db):
    from .api_pages import page
    return page(db,'jobs',{})['data']


def job(db, identifier):
    """One import job with steps and whether its worker died (`interrupted`)."""
    from .pipeline import owner_pid_alive
    value = one(db, 'SELECT * FROM jobs WHERE id=?', (identifier,))
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name IN ('import_steps','import_owners')")}
    value['steps'] = rows(db, 'SELECT * FROM import_steps WHERE job_id=? ORDER BY position', (identifier,)) if 'import_steps' in tables else []
    owner = db.execute('SELECT pid FROM import_owners WHERE job_id=?', (identifier,)).fetchone() if 'import_owners' in tables else None
    live = owner_pid_alive(owner[0], path=db.execute('PRAGMA database_list').fetchone()['file'], job=identifier) if owner else False
    value['interrupted'] = (value['state'] == 'running' or value['state'] == 'waiting_for_budget' and owner is not None) and not live
    return value


def event_values(values):
    for r in values:
        r['undone'], r['undoable'] = bool(r['undone']), bool(r['undoable']) and not r['undone']
        if r['entity'] == 'bw_api' and (r['field'].startswith('op:') or r['field']=='receipt') or r['entity'].startswith('source_key'):
            r['old_value'] = r['new_value'] = None
        else:
            for k in ('old_value', 'new_value'):
                try: r[k] = json.loads(r[k])
                except (TypeError, ValueError): pass
    return values


def events(db, identifier=None):
    if identifier is None:
        from .api_pages import page
        return page(db,'events',{})['data']
    return event_values(rows(db, f'SELECT e.*, {undone_sql()} undone, {undoable_sql()} undoable FROM events e' +
        (' WHERE e.id=?' if identifier is not None else ''), (identifier,) if identifier is not None else ()))


def sources(db):
    from . import keys
    from .sources.bricklink import BrickLink
    from .sources.rebrickable import Rebrickable
    from .sources.brickset import Brickset
    from .sources.brickognize import Brickognize
    clients = {c.source: c for c in (BrickLink, Rebrickable, Brickset, Brickognize)}
    usage = {r['source']: r for r in rows(db, '''SELECT source,
        max(CASE WHEN state='done' THEN updated_at END) last_success FROM jobs GROUP BY source''')}
    counters = {r[0].split(':')[2] for r in db.execute("SELECT key FROM settings WHERE key LIKE 'source:used:%'")}
    failures = {r['source']: r['error'] for r in rows(db, 'SELECT source,error FROM jobs WHERE error IS NOT NULL ORDER BY updated_at,id')}
    listed = rows(db, 'SELECT * FROM sources')
    # A fresh install registers a client on first use; key entry must not wait for that.
    listed += [dict(source=name, name=name, kind='api', enabled=1, priority_settings=None)
               for name in clients if name not in {r['source'] for r in listed}]
    result, saved = [], keys.stored_states(db)
    for r in listed:
        source = r['source']
        r['key'] = keys.state(db, source, saved=saved)
        r.update(usage.get(source, dict(last_success=None)))
        r['used_today'] = budget_used(db, source, now().date().isoformat()) if source in usage or source in counters else 0
        r['last_error'] = failures.get(source)
        r['budget'] = clients[source](db).daily_budget if source in clients else None
        result.append(r)
    return result


def stale_prices(db):
    """Preserve origin tables when the same stale identity appears in two lists."""
    fields = ('item_type', 'item_no', 'color_id', 'condition')
    stale = {tuple(r[k] for k in fields): r for r in admin.stale_prices(db)}
    identities = rows(db, """SELECT DISTINCT item_type,set_no item_no,NULL color_id,condition,'copies' source_table
        FROM copies WHERE archived_at IS NULL UNION
        SELECT DISTINCT item_type,item_no,color_id,condition,'loose_stock' FROM loose_stock WHERE archived_at IS NULL UNION
        SELECT DISTINCT item_type,item_no,color_id,CASE condition WHEN 'new' THEN 'N' WHEN 'used' THEN 'U' END,
        'wishlist' FROM wishlist WHERE archived_at IS NULL""")
    return [dict(stale[key], source_table=r['source_table']) for r in identities
            if (key := tuple(r[k] for k in fields)) in stale]


def catalogue(db):
    path = add.catalogue_path(db)
    if not path.is_file():
        raise errors.CatalogueNotLoaded()
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as cat:
        cat.row_factory = sqlite3.Row
        return rows(cat, 'SELECT item_type,item_no,name,category,year FROM items')


def catalogue_status(db):
    from .sources.bricklink_catalogue import info
    value = info(add.catalogue_path(db))
    return dict(loaded=value['available'], imported_at=value.get('loaded_at'), items=value.get('counts', {}))


def completeness_read(db, identifier):
    r = entity(db, 'copy', identifier)
    return dict(stored=r['completeness'], completeness_source=r['completeness_source'],
                derived=completeness.derived_state(db, identifier), checked=checker.checked(db, identifier),
                missing=r['missing'], damaged=r['damaged'])


def content(db, resource, identifier):
    if resource == 'images':
        r = one(db, 'SELECT local_path FROM item_images WHERE id=?', (identifier,))
        relative, directory = r['local_path'], 'images'
    elif resource == 'instructions':
        r = one(db, 'SELECT path FROM instruction_files WHERE id=? AND archived_at IS NULL', (identifier,))
        relative, directory = r['path'], 'instructions'
    else:
        one(db, 'SELECT 1 FROM identifications WHERE id=? AND has_thumb=1 AND archived_at IS NULL', (identifier,))
        relative, directory = 'data/identifications/' + identifier + '.jpg', 'identifications'
    base = root(db)
    target = (base / relative).resolve()
    if not target.is_relative_to(base / 'data' / directory) or not target.is_file():
        raise errors.NotFound()
    return target


def missing(db, ids, xml=False):
    # XML and JSON share precisely the existing export eligibility and aggregation.
    content = planning.export(db, ids)
    if xml:
        return content
    return [dict(item_type=r.findtext('ITEMTYPE'), item_no=r.findtext('ITEMID'),
                 color_id=int(r.findtext('COLOR')) if r.findtext('COLOR') is not None else None,
                 quantity=int(r.findtext('MINQTY')), condition=r.findtext('CONDITION'))
            for r in ET.fromstring(content).findall('ITEM')]


def resource_rows(db, resource):
    tables = {'flags': 'flags', 'id-matches': 'id_match', 'instruction-files': 'instruction_files', 'identifications': 'identifications'}
    if resource == 'instruction-files':
        return instruction_files(db)
    result = rows(db, 'SELECT * FROM ' + tables[resource])
    if resource == 'identifications':
        for r in result:
            r['candidates'] = json.loads(r['candidates'] or '[]')
    return result


def record(db, resource, identifier, *, archived=False):
    if resource == 'instruction-files':
        result = instruction_files(db, identifier)
        if not result: raise errors.NotFound()
        return result[0]
    table, column = {'colors': ('colors', 'color_id'), 'instruction-files': ('instruction_files', 'id'),
                     'orders': ('orders', 'id'), 'lots': ('lots', 'id'), 'identifications': ('identifications', 'id')}[resource]
    value = one(db, f'SELECT * FROM {table} WHERE {column}=?', (identifier,))
    if resource == 'identifications':
        if value['archived_at'] and not archived:
            raise errors.NotFound()
        value['candidates'] = json.loads(value['candidates'] or '[]')
    return value


def database_export(db):
    """Snapshot without credentials or authentication receipts; never mutate on GET."""
    from .secrets import secret_values
    with closing(sqlite3.connect(':memory:')) as snapshot:
        db.backup(snapshot)
        snapshot.execute('PRAGMA journal_mode=DELETE')
        # Stored source keys never leave the app, not even encrypted: the copy is stripped of them.
        from . import keys
        keys.strip(snapshot)
        result = bytearray(snapshot.serialize())
        result[18:20] = bytes((1, 1))
        if any(v.encode() in result for v in secret_values()):
            raise errors.Conflict('Export contains credential material')
        return bytes(result)


def entity_etag(db, entity, identifier):
    table = {'copy': 'copies', 'stock': 'loose_stock', 'wish': 'wishlist'}[entity]
    saved = one(db, 'SELECT * FROM ' + table + ' WHERE id=?', (identifier,))
    flags = [r[0] for r in db.execute('SELECT flag_id FROM item_flags WHERE entity_type=? AND entity_id=? ORDER BY flag_id',
                                    ('wishlist' if entity == 'wish' else entity, str(identifier)))]
    return etag(dict(snapshot=saved, flags=flags))


def instruction_coverage(db):
    return dict(db.execute('''SELECT count(*) total,coalesce(sum(EXISTS(SELECT 1 FROM instruction_files f
        WHERE f.item_type='I' AND f.set_no=i.item_no AND f.archived_at IS NULL AND f.path<>'')),0) covered FROM items i WHERE item_type='I' ''').fetchone())


def cursor_id(row):
    """A logical row key, independent of names, quantities and quote contents."""
    if row.get('target') is not None:
        key = ['target', row.get('copy_id'), row['target'], row.get('target_id'), row.get('source_id')]
    elif 'observation_id' in row:
        key = ['price', *(row.get(k) for k in ('item_type', 'item_no', 'color_id', 'condition', 'guide', 'slot', 'region', 'currency'))]
    elif 'item_type' not in row and row.get('color_id') is not None:
        return row['color_id']
    elif row.get('id') is not None:
        return row['id']
    else:
        key = [row.get(k) for k in ('item_type', 'item_no', 'color_id', 'copy_id', 'stock_id', 'minifig_no', 'spare', 'source', 'kind', 'source_id', 'condition', 'source_table')]
    return json.dumps(key, separators=(',', ':'), sort_keys=True)


def instruction_files(db, identifier=None):
    values = rows(db, """SELECT f.*,f.set_no item_no,i.name FROM instruction_files f JOIN items i
        ON i.item_type=f.item_type AND i.item_no=f.set_no""" + (' WHERE f.id=?' if identifier is not None else ''),
        (identifier,) if identifier is not None else ())
    return [dict(r, content_url='/api/v1/instruction-files/' + str(r['id']) + '/content') for r in values]
