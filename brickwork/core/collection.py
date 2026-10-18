"""Collection projections and guarded receipts on the migrated store.

Lists use bulk projections; identity rows and original instances remain intact.
"""
from .transaction import on_rollback, transaction
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote, urlencode

from . import add, stock, workbench, collection_prices, upgrade, errors
from .admin import audit
from .completeness import derived_state
from .sources.base import now

TYPES = {'S': 'Sets', 'M': 'Minifigures', 'P': 'Parts', 'I': 'Instructions',
         'O': 'Boxes', 'G': 'Gear', 'B': 'Books', 'C': 'Catalogs', '?': 'Unresolved items'}
TABLES = {'copy': 'copies', 'stock': 'loose_stock', 'wish': 'wishlist', 'lot': 'lots'}


def options(db, *, include_wishlists=False):
    result = dict(storages=[dict(r) for r in db.execute('SELECT * FROM storages WHERE archived_at IS NULL ORDER BY name,id')],
                places=[dict(r) for r in db.execute('SELECT * FROM purchase_locations WHERE archived_at IS NULL ORDER BY name,id')],
                lots=[dict(r) for r in db.execute('SELECT * FROM lots WHERE archived_at IS NULL ORDER BY name,id')],
                flags=[dict(r) for r in db.execute('SELECT * FROM flags WHERE archived_at IS NULL ORDER BY kind,name,id')],
                colours=add.colors(db))
    if include_wishlists:
        result['wishlists'] = [dict(r) for r in db.execute('SELECT * FROM wishlists WHERE archived_at IS NULL ORDER BY sort,name,id')]
    return result


def identity_filter(alias):
    """SQL restricting `alias` rows to a JSON list of (item_type, item_no, color_id) identities."""
    return f"""({alias}.item_type,{alias}.item_no,{alias}.color_id IS NULL,coalesce({alias}.color_id,0)) IN
        (SELECT json_extract(value,'$[0]'),json_extract(value,'$[1]'),json_extract(value,'$[2]') IS NULL,
         coalesce(json_extract(value,'$[2]'),0) FROM json_each(?))"""


def properties(db, kind=None, numbers=None, *, identities=None):
    """Item properties; `numbers` (one kind) or `identities` ((type, number, colour) rows) scope the read."""
    setting = db.execute("SELECT value FROM settings WHERE key='source_priority'").fetchone()
    priority = json.loads(setting[0]).get('metadata', {}) if setting else {}
    grouped = defaultdict(list)
    where = ' WHERE item_type=? AND item_no IN (SELECT value FROM json_each(?))' if kind else ''
    params = (kind, json.dumps(numbers)) if kind else ()
    if identities is not None:
        where = ' WHERE (item_type,item_no) IN (SELECT json_extract(value,\'$[0]\'),json_extract(value,\'$[1]\') FROM json_each(?))'
        params = (json.dumps([[i[0], i[1]] for i in identities]),)
    for r in db.execute('SELECT * FROM item_properties' + where + ' ORDER BY key,source', params):
        grouped[r['item_type'], r['item_no'], r['key']].append(dict(r))
    result = defaultdict(dict)
    for (kind, number, key), rows in grouped.items():
        order = [s.split(':')[0] for s in priority.get(kind, priority.get('*', []))]
        rows.sort(key=lambda r: order.index(r['source']) if r['source'] in order else len(order))
        result[kind, number][key] = dict(rows[0], alternatives=rows[1:])
    return result


def prices(db, kind=None, number=None, colour=None, *, listed_kind=None, identities=None, scope=None, used_sold=False):
    """Current quotes. `used_sold` keeps only used, sold-guide, non-boxed quotes: all a list row's price ever reads."""
    where = 'WHERE p.item_type=? AND p.item_no=? AND p.color_id IS ?' if kind else ''
    params = (kind, number, colour) if kind else ()
    if listed_kind:
        where = '''WHERE p.item_type=? AND (p.item_no,p.color_id IS NULL,coalesce(p.color_id,0)) IN
            (SELECT json_extract(value,'$[0]'),json_extract(value,'$[1]') IS NULL,
             coalesce(json_extract(value,'$[1]'),0) FROM json_each(?))'''
        params = (listed_kind, json.dumps(identities))
    if scope is not None:  # (type, number, colour) rows across kinds, e.g. the wishes
        where = 'WHERE ' + identity_filter('p')
        params = (json.dumps([list(i) for i in scope]),)
    if used_sold:
        where += (' AND ' if where else 'WHERE ') + "p.condition='U' AND p.guide='sold' AND coalesce(p.slot,'')<>'boxed' "
    rows = db.execute('''SELECT p.*,o.source,o.price,o.min,o.max,o.qty,o.sold,o.observed_at,o.error,
        f.max_age_days FROM price_current p JOIN price_observations o ON o.id=p.observation_id
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices' ''' + where +
        ' ORDER BY p.item_type,p.item_no,p.condition,p.guide,p.currency,p.slot,p.region',
        params).fetchall()
    result = defaultdict(list)
    for r in decorate_prices(rows):
        result[r['item_type'], r['item_no'], r['color_id']].append(r)
    return result.get((kind, number, colour), []) if kind else result


def decorate_prices(rows):
    result = []
    current = None
    for raw in rows:
        r = dict(raw)
        r['label'] = {'N': 'New', 'U': 'Used'}.get(r['condition'], 'Price')
        if r['guide'] == 'stock':
            r['label'] += ' listings'
        if r['slot']:
            r['label'] = 'With box' if r['item_type']=='S' and r['slot']=='boxed' else r['label'] + ' · ' + r['slot'].replace('_', ' ')
        r['age'] = r['observed_at'][:10] if isinstance(r['observed_at'], str) and r['observed_at'] else 'Age not recorded'
        r['stale'] = False
        r['range'] = None
        try:
            if r['observed_at'] and r['max_age_days'] is not None:
                date = collection_prices.dated(r['observed_at'])
                if date is not None:
                    current = current or now()
                    r['stale'] = (current - date).days > r['max_age_days']
        except (ValueError, TypeError, AttributeError):
            r['stale'] = False
        try:
            if r['guide'] == 'sold' and r['price'] is not None and r['min'] is not None and r['max'] is not None and (r['sold'] or 0) > 1:
                low, avg, high = map(Decimal, (r['min'], r['price'], r['max']))
                if low < high and low <= avg <= high:
                    r['range'] = float((avg-low)/(high-low)*100)
        except (InvalidOperation, ValueError, TypeError, AttributeError):
            r['range'] = None
        result.append(r)
    return result


def instances(db, kind=None, *, include_archived=False, number=None):
    """Bulk physical rows; API archive reads opt in, web defaults stay live-only.

    `number` (with `kind`) scopes the read to one item number: same rows, same labels, same order.
    """
    live = '1=1' if include_archived else 'archived_at IS NULL'
    copy_live = '1=1' if include_archived else 'c.archived_at IS NULL'
    stock_live = '1=1' if include_archived else 's.archived_at IS NULL'
    params = (kind,) if kind else ()
    one = ' AND {}=?' if kind and number is not None else ''
    copy_one, stock_one = one.format('c.set_no'), one.format('s.item_no')
    copy_args = (*params, number) if one else params
    copies = [dict(r) for r in db.execute(f'''SELECT c.*,c.set_no AS item_no,i.name,i.category,i.year,
        s.name AS storage_name,l.name AS place_name,NULL AS color_id,1 AS quantity,'copy' AS entity
        FROM copies c JOIN items i ON (i.item_type,i.item_no)=(c.item_type,c.set_no)
        LEFT JOIN storages s ON s.id=c.storage_id LEFT JOIN purchase_locations l ON l.id=c.purchase_location_id
        WHERE {copy_live}''' + (' AND c.item_type=?' if kind else '') + copy_one +
        ' ORDER BY c.item_type,c.set_no,c.id', copy_args)]
    labels = defaultdict(int)
    for row in copies:
        key = row['item_type'], row['item_no']
        labels[key] += 1
        row['label'] = 'Set ' + str(labels[key])
    defects = {r['copy_id']:dict(r) for r in db.execute(f'''SELECT copy_id,sum(missing) AS missing,sum(damaged) AS damaged FROM
        (SELECT copy_id,coalesce(missing,0) AS missing,coalesce(damaged,0) AS damaged FROM copy_parts WHERE coalesce(spare,0)=0 AND parent_minifig IS NULL
        UNION ALL SELECT copy_id,coalesce(missing,0),0 FROM copy_minifigs)''' +
        (f''' WHERE copy_id IN (SELECT id FROM copies WHERE {live} AND item_type=?{one.format('set_no')})''' if kind else '') +
        ' GROUP BY copy_id', copy_args)}
    for row in copies:
        row.update(missing=defects.get(row['id'],{}).get('missing',0),damaged=defects.get(row['id'],{}).get('damaged',0))
    stock = [dict(r) for r in db.execute(f'''SELECT s.*,i.name,i.category,i.year,t.name AS storage_name,
        p.name AS place_name,l.name AS lot_name,'stock' AS entity FROM loose_stock s
        JOIN items i ON (i.item_type,i.item_no)=(s.item_type,s.item_no)
        LEFT JOIN storages t ON t.id=s.storage_id LEFT JOIN purchase_locations p ON p.id=s.purchase_location_id
        LEFT JOIN lots l ON l.id=s.lot_id WHERE {stock_live}''' +
        (' AND s.item_type=?' + stock_one + ' ORDER BY s.rowid' if kind else ''), copy_args)]
    flags = defaultdict(list)
    for r in db.execute('SELECT f.*,i.entity_type,i.entity_id FROM item_flags i JOIN flags f ON f.id=i.flag_id AND f.archived_at IS NULL' +
                        (f''' WHERE (i.entity_type='copy' AND i.entity_id IN
                            (SELECT id FROM copies WHERE item_type=?{one.format('set_no')} AND {live}))
                            OR (i.entity_type='stock' AND i.entity_id IN
                            (SELECT id FROM loose_stock WHERE item_type=?{one.format('item_no')} AND {live}))''' if kind else '') + ' ORDER BY f.id',
                        (*copy_args, *copy_args) if kind else ()):
        flags[r['entity_type'], r['entity_id']].append(dict(r))
    for row in copies + stock:
        row['flags'] = flags[row['entity'], row['id']]
    return copies + stock


def instance(db, entity, identifier):
    """One physical row (archived included) shaped exactly like ``instances(include_archived=True)``.

    Keyed lookups only: no collection-wide scan, so a single read costs the same on any size of store.
    """
    if entity == 'copy':
        row = db.execute('''SELECT c.*,c.set_no AS item_no,i.name,i.category,i.year,
            s.name AS storage_name,l.name AS place_name,NULL AS color_id,1 AS quantity,'copy' AS entity
            FROM copies c JOIN items i ON (i.item_type,i.item_no)=(c.item_type,c.set_no)
            LEFT JOIN storages s ON s.id=c.storage_id LEFT JOIN purchase_locations l ON l.id=c.purchase_location_id
            WHERE c.id=?''', (identifier,)).fetchone()
        if not row:
            return None
        row = dict(row)
        # "Set N" is the position among every copy of the set (archived included), ordered by id.
        row['label'] = 'Set ' + str(db.execute('SELECT count(*) FROM copies WHERE item_type=? AND set_no=? AND id<=?',
                                               (row['item_type'], row['item_no'], row['id'])).fetchone()[0])
        defect = db.execute('''SELECT sum(missing) AS missing,sum(damaged) AS damaged FROM
            (SELECT coalesce(missing,0) AS missing,coalesce(damaged,0) AS damaged FROM copy_parts
             WHERE copy_id=? AND coalesce(spare,0)=0 AND parent_minifig IS NULL
             UNION ALL SELECT coalesce(missing,0),0 FROM copy_minifigs WHERE copy_id=?)''', (identifier, identifier)).fetchone()
        row.update(missing=defect['missing'] or 0, damaged=defect['damaged'] or 0)
    else:
        row = db.execute('''SELECT s.*,i.name,i.category,i.year,t.name AS storage_name,
            p.name AS place_name,l.name AS lot_name,'stock' AS entity FROM loose_stock s
            JOIN items i ON (i.item_type,i.item_no)=(s.item_type,s.item_no)
            LEFT JOIN storages t ON t.id=s.storage_id LEFT JOIN purchase_locations p ON p.id=s.purchase_location_id
            LEFT JOIN lots l ON l.id=s.lot_id WHERE s.id=?''', (identifier,)).fetchone()
        if not row:
            return None
        row = dict(row)
    row['flags'] = [dict(r) for r in db.execute(
        'SELECT f.*,i.entity_type,i.entity_id FROM item_flags i JOIN flags f ON f.id=i.flag_id AND f.archived_at IS NULL '
        'WHERE i.entity_type=? AND i.entity_id=? ORDER BY f.id', (entity, identifier))]
    return row


def listing(db, kind, *, wishes=False):
    if kind not in TYPES:
        raise ValueError('Unknown collection')
    rows = []
    if wishes:
        rows = [dict(r, entity='wish', instances=[]) for r in db.execute('''SELECT w.*,i.name,i.category,i.year,l.name AS list_name
            FROM wishlist w JOIN wishlists l ON l.id=w.list_id JOIN items i USING(item_type,item_no) WHERE w.archived_at IS NULL''')]
    else:
        grouped = {}
        for r in instances(db, kind):
            if r['item_type'] != kind:
                continue
            key = r['item_type'], r['item_no'], r.get('color_id')
            row = grouped.setdefault(key, dict(r, quantity=0, instances=[], ids=[], conditions=[], statuses=[], storages=[], places=[], flag_names=[], lots=[], missing=0, damaged=0))
            row['quantity'] += r['quantity'] or 0
            row['instances'].append(r)
            row['ids'].append(r['id'])
            row['conditions'].append(r['condition'] or '')
            row['statuses'].append(r.get('completeness') or '')
            row['storages'].append(r['storage_id'] or 'null')
            row['places'].append(r['purchase_location_id'] or 'null')
            row['flag_names'].extend(f['name'] or '' for f in r['flags'])
            row['lots'].append(r.get('lot_id') or 'null')
            row['missing'] += r.get('missing') or 0
            row['damaged'] += r.get('damaged') or 0
        rows = list(grouped.values())
        # In-set counts include all migrated lineage rows; never replace them with templates.
        in_sets = db.execute('''SELECT p.item_type,p.item_no,p.color_id,sum(p.quantity) AS quantity,
            sum(coalesce(p.missing,0)) AS missing,sum(coalesce(p.damaged,0)) AS damaged
            FROM copy_parts p JOIN copies c ON c.id=p.copy_id WHERE c.archived_at IS NULL AND p.item_type=?
            GROUP BY p.item_type,p.item_no,p.color_id''', (kind,)).fetchall()
        if kind in ('M','?'):
            figures = db.execute('''SELECT m.item_type,m.minifig_no AS item_no,NULL AS color_id,
                sum(m.quantity) AS quantity,sum(coalesce(m.missing,0)) AS missing,0 AS damaged
                FROM copy_minifigs m JOIN copies c ON c.id=m.copy_id WHERE c.archived_at IS NULL AND m.item_type=?
                GROUP BY m.item_type,m.minifig_no''',(kind,)).fetchall()
            in_sets = figures if kind=='M' else [*in_sets,*figures]
        identities = {(r['item_type'], r['item_no']): dict(r) for r in db.execute(
            'SELECT * FROM items WHERE item_type=? AND item_no IN (SELECT value FROM json_each(?))',
            (kind, json.dumps(list({r['item_no'] for r in in_sets}))))}
        for raw in in_sets:
            key = raw['item_type'], raw['item_no'], raw['color_id']
            row = grouped.get(key)
            if row is None:
                row = dict(identities[key[:2]], color_id=key[2], quantity=0, instances=[], ids=[], entity='stock', conditions=[], statuses=[], storages=[], places=[], flag_names=[], lots=[], missing=0, damaged=0)
                rows.append(row)
                grouped[key]=row
            row['in_sets'] = (row.get('in_sets') or 0) + (raw['quantity'] or 0)
            row['missing'] += raw['missing'] or 0
            row['damaged'] += raw['damaged'] or 0
    if not wishes and kind == 'S':
        gaps = {r['set_no']: dict(r) for r in db.execute('''SELECT c.set_no,
            sum(g.parts) AS missing_parts,sum(g.figures) AS missing_figures
            FROM copies c JOIN (
                SELECT copy_id,coalesce(missing,0) AS parts,0 AS figures FROM copy_parts WHERE coalesce(spare,0)=0 AND parent_minifig IS NULL
                UNION ALL SELECT copy_id,0,coalesce(missing,0) FROM copy_minifigs
            ) g ON g.copy_id=c.id WHERE c.archived_at IS NULL AND c.item_type='S' GROUP BY c.set_no''')}
        for row in rows:
            gap = gaps.get(row['item_no'], {})
            row.update(missing_parts=gap.get('missing_parts', 0), missing_figures=gap.get('missing_figures', 0))
    if not wishes and kind == 'I':
        # Booklets share their set identity with files, just as on the detail screen.
        pdfs = {r[0] for r in db.execute("SELECT DISTINCT set_no FROM instruction_files WHERE archived_at IS NULL AND item_type='S' AND path<>'' AND set_no IN (SELECT value FROM json_each(?))",
                                       (json.dumps([r['item_no'] for r in rows]),))}
        for row in rows:
            row['pdf_available'] = row['item_no'] in pdfs
    if wishes:
        scope = {(r['item_type'], r['item_no'], r['color_id']) for r in rows}
        props = properties(db, identities=scope)
        market = prices(db, scope=scope)
    else:
        props = properties(db, kind, list({r['item_no'] for r in rows}))
        # A list row reads one quote (used, sold, not boxed), so only those are fetched.
        # List rows only need the used, sold, unboxed quote for row['price']; row['prices'] here is that subset,
        # not every quote (detail pages, wishes and the API read the full set through prices() without used_sold).
        market = prices(db, listed_kind=kind, identities=[(r['item_no'], r['color_id']) for r in rows], used_sold=True)
    price_priority = collection_prices.priority(db)
    for row in rows:
        row['properties'] = props[row['item_type'], row['item_no']]
        row['theme'] = row['properties'].get('theme', {}).get('value', '')
        row['prices'] = market[row['item_type'], row['item_no'], row['color_id']]
        row['price'] = collection_prices.choose([p for p in row['prices'] if p['guide']=='sold' and p.get('slot')!='boxed'], row['item_type'], price_priority, 'U')
    return add.decorate_many(db, rows)


def external_links(db, row):
    """Prefer a recorded Brickset variant, with canonical numbered sets as fallback."""
    if row['item_type'] != 'S' or row.get('unresolved'):
        return []
    links = [('BrickLink', 'https://www.bricklink.com/v2/catalog/catalogitem.page?' +
              urlencode({'S': row['item_no']}))]
    # A recorded variant takes precedence; ambiguous mappings stay unlinked.
    # setID is an internal key, not a set number.
    numbers = {r[0] for r in db.execute("""SELECT source_id FROM id_match
        WHERE source='brickset' AND kind='set_number' AND item_type='S' AND item_no=?
        AND status IN ('matched','inferred','manual')""", (row['item_no'],)) if r[0]}
    ambiguous = db.execute("""SELECT 1 FROM id_match
        WHERE source='brickset' AND item_type='S' AND item_no=?
        AND status IN ('to_check','unmatched') LIMIT 1""", (row['item_no'],)).fetchone()
    if not numbers and not ambiguous and re.fullmatch(r'[0-9]+-[0-9]+', row['item_no']):
        numbers.add(row['item_no'])
    if len(numbers) == 1:
        links.append(('Brickset', 'https://brickset.com/sets/' + quote(numbers.pop(), safe='')))
    return links


def part_colours(db, number):
    """Active colours from stock, set inventories and wishes, in one read."""
    return [dict(r, ink=add.colour_ink(r['rgb'])) for r in db.execute("""SELECT x.color_id,c.name AS color_name,c.rgb,
        sum(x.quantity) AS quantity FROM (
        SELECT color_id,coalesce(quantity,0) AS quantity FROM loose_stock
            WHERE item_type='P' AND item_no=? AND archived_at IS NULL AND quantity>0
        UNION ALL SELECT p.color_id,max(coalesce(p.quantity,0)-coalesce(p.missing,0),0)
            FROM copy_parts p JOIN copies c ON c.id=p.copy_id
            WHERE p.item_type='P' AND p.item_no=? AND c.archived_at IS NULL AND p.quantity>0
        UNION ALL SELECT color_id,0 FROM wishlist
            WHERE item_type='P' AND item_no=? AND archived_at IS NULL AND quantity>0
        ) x LEFT JOIN colors c ON c.color_id=x.color_id GROUP BY x.color_id
        ORDER BY c.name,x.color_id""", (number, number, number))]


def copy_labels(db, ids):
    """`{copy id: 'Set N'}` for live set copies among `ids`, numbered as `instances(db, 'S')` numbers them."""
    return {r[0]: 'Set ' + str(r[1]) for r in db.execute('''SELECT c.id,(SELECT count(*) FROM copies d WHERE d.archived_at IS NULL
        AND d.item_type=c.item_type AND d.set_no=c.set_no AND d.id<=c.id) FROM copies c
        WHERE c.item_type='S' AND c.archived_at IS NULL AND c.id IN (SELECT value FROM json_each(?))''', (json.dumps(sorted(set(ids))),))}


def figure_detail(db, row):
    """Figure-wide display facts, with all component contexts fetched in batches."""
    kind, number = row['item_type'], row['item_no']
    components = [dict(r) for r in db.execute("""SELECT p.*,i.name FROM copy_parts p
        JOIN copies c ON c.id=p.copy_id JOIN items i ON (i.item_type,i.item_no)=(p.item_type,p.item_no)
        WHERE parent_minifig_type=? AND parent_minifig=? AND c.archived_at IS NULL
        AND coalesce(p.spare,0)=0""", (kind, number))]
    # Only the copies this figure appears in need a label.
    copies = {r['id']: dict(r, item_no=r['set_no']) for r in db.execute(
        "SELECT id,set_no FROM copies WHERE item_type='S' AND archived_at IS NULL AND id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted({p['copy_id'] for p in [*row['consists'], *components, *row['used_in']] if p.get('copy_id')})),))}
    for copy_id, label in copy_labels(db, copies).items():
        copies[copy_id]['label'] = label
    loose = [dict(r) for r in db.execute("""SELECT p.*,i.name FROM loose_minifig_parts p
        JOIN loose_stock s ON s.id=p.stock_id JOIN items i ON (i.item_type,i.item_no)=(p.item_type,p.item_no)
        WHERE s.item_type=? AND s.item_no=? AND s.archived_at IS NULL AND coalesce(p.spare,0)=0""", (kind, number))]
    # Catalogue and owned inventories describe the same components; do not multiply
    # quantities by the number of contexts when building the short constituent list.
    catalogue = [dict(r) for r in db.execute('''SELECT l.child_item_type AS item_type,l.child_item_no AS item_no,
        l.color_id,l.quantity,i.name FROM inventory_lines l JOIN items i
        ON (i.item_type,i.item_no)=(l.child_item_type,l.child_item_no)
        WHERE parent_item_type=? AND parent_item_no=?''', (kind, number))]
    whole_missing = {r['copy_id']: r['missing'] or 0 for r in row['used_in']}
    parts = {}
    for p in [*catalogue, *row['consists'], *components, *loose]:
        key = p['item_type'], p['item_no'], p.get('color_id')
        part = parts.setdefault(key, dict(p, warnings=[]))
        if p.get('copy_id') in copies and workbench.part_gap(p, whole_missing.get(p['copy_id'], 0)):
            c = copies[p['copy_id']]
            warning = dict(label=c['label'], item_no=c['item_no'], missing=p.get('missing') or 0, damaged=p.get('damaged') or 0)
            if warning not in part['warnings']:
                part['warnings'].append(warning)
        elif (p.get('missing') or p.get('damaged')) and p.get('stock_id'):
            warning = dict(label='Loose', item_no='', missing=p.get('missing') or 0, damaged=p.get('damaged') or 0)
            if warning not in part['warnings']:
                part['warnings'].append(warning)
    row['figure_components'] = add.decorate_many(db, list(parts.values()))
    for used in row['used_in']:
        used['label'] = copies.get(used['copy_id'], {}).get('label', 'Set')
        used['parts_missing'] = sum((p['missing'] or 0) + (p['damaged'] or 0) for p in components if p['copy_id']==used['copy_id'])
    row['loose_count'] = sum(r['quantity'] or 0 for r in row['instances'])
    row['set_count'] = sum(r['quantity'] or 0 for r in row['used_in'])
    row['loose_conditions'] = {}
    for r in row['instances']:
        condition = r.get('condition')
        row['loose_conditions'][condition] = row['loose_conditions'].get(condition, 0) + (r['quantity'] or 0)
    row['figure_wishes'] = [dict(r) for r in db.execute("SELECT * FROM wishlist WHERE item_type=? AND item_no=? AND archived_at IS NULL", (kind, number))]
    row['catalogue_ids'] = {'BrickLink': number if kind=='M' else None, 'Rebrickable': None, 'Brickset': None}
    for r in db.execute("SELECT source,source_id FROM id_match WHERE item_type=? AND item_no=? AND status IN ('matched','manual','inferred') ORDER BY source,source_id", (kind, number)):
        label = {'bricklink':'BrickLink','rebrickable':'Rebrickable','brickset':'Brickset'}.get(r['source'])
        if label:
            row['catalogue_ids'][label] = r['source_id']
    targets = add.decorate_many(db, [dict(item_type=r['copy']['item_type'],
        item_no=r['copy']['set_no'],name=r['copy']['set_name'],color_id=None) for r in row['matches']])
    for match, target in zip(row['matches'], targets):
        match['display_item'] = target
    row['matching_groups'] = [
        ('Copies that need this figure', [r for r in row['matches'] if r['target']!='stock-part']),
        ('Loose copies that could fill them', [r for r in row['matches'] if r['target']=='stock-part'])]


def detail(db, kind, number, *, colour=None, copy_id=None, stock_id=None, wish_id=None):
    item = db.execute('SELECT * FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone()
    if not item:
        raise ValueError('Item is unavailable')
    all_instances = [r for r in instances(db, kind, number=number) if (r['item_type'], r['item_no']) == (kind, number) and (kind != 'P' or r['color_id'] == colour)]
    selected = next((r for r in all_instances if r['id'] == (copy_id or stock_id)), None)
    if copy_id or stock_id:
        if selected is None:
            raise ValueError('Instance is unavailable')
    elif all_instances:
        selected = all_instances[0]
    wish = None
    if wish_id:
        r = db.execute('SELECT * FROM wishlist WHERE id=? AND archived_at IS NULL', (wish_id,)).fetchone()
        if not r or (r['item_type'], r['item_no'], r['color_id']) != (kind, number, colour):
            raise ValueError('Wish is unavailable')
        wish = dict(r, entity='wish', flags=[dict(f) for f in db.execute("SELECT f.* FROM flags f JOIN item_flags a ON a.flag_id=f.id WHERE f.archived_at IS NULL AND a.entity_type='wishlist' AND a.entity_id=? ORDER BY f.id",(str(wish_id),))])
        selected = wish
    row = add.decorate_many(db, [dict(item, color_id=colour)])[0]
    row.update(instances=all_instances, selected=selected, wish=wish,
               properties=properties(db, kind, [number])[kind, number], prices=prices(db, kind, number, colour))
    row['theme'] = row['properties'].get('theme', {}).get('value', '')
    row['external_links'] = external_links(db, row)
    price_priority = collection_prices.priority(db)
    observations = [dict(r) for r in db.execute('''SELECT o.*,f.max_age_days FROM price_observations o
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE o.item_type=? AND o.item_no=? AND o.color_id IS ? ORDER BY o.observed_at DESC,o.id DESC''', (kind, number, colour))]
    row['price_records'] = decorate_prices(observations)
    row['condition_prices'] = collection_prices.condition_rows(row['price_records'], kind, price_priority)
    row['price_history'] = collection_prices.history(observations, collection_prices.choose([p for p in row['price_records'] if p['guide']=='sold' and p.get('slot')!='boxed'], kind, price_priority, 'U'))
    row['valuation_prices'] = [p for p in row['price_records'] if p['guide']=='valuation' or p.get('slot')=='boxed']
    row['valuation_prices'] = [p for slot in ('boxed', 'estimate') if (p := collection_prices.choose([p for p in row['valuation_prices'] if (p.get('slot')=='boxed') == (slot=='boxed')], kind, price_priority))]
    if kind == 'S':
        # #26: retail price and availability for the retail country; the saving only in the same currency.
        from . import retail
        row['retail'] = retail.lookup(db, [number]).get(number)
        from .currency import rates as currency_rates
        row['retail_saving'] = (retail.saving(selected.get('purchase_price'), selected.get('purchase_currency'), row['retail'], currency_rates(db))
                                if row['retail'] and selected and selected['entity'] == 'copy' else None)
    if kind == 'S' and selected and selected['entity'] == 'copy':
        # #38: complete, as is and parted out for the shown copy.
        from . import partout, planning
        config, stamp = planning.configuration(db), now()
        complete = planning.quote(prices(db, 'S', number, None), selected.get('condition') or 'U', config, stamp)
        override = selected.get('current_value')
        as_is = (Decimal(str(override)) if override is not None and selected.get('current_value_currency') == config['bricklink_currency']
                 else Decimal(str(complete['price'])) * (100 - config['incomplete_discount_pct']) / 100 if complete else None)
        row['partout'] = partout.compare(dict(complete_quote=complete, current_value=as_is), partout.values(db, [selected['id']]).get(selected['id']))
    spare_lines = 0
    if selected and selected['entity'] == 'copy':
        # 4.8a: the set's part list is required, non-figure parts only. Spare lines and
        # figure component rows stay stored; the figure line carries its parts' state.
        consists = [dict(r) for r in db.execute('''SELECT p.*,i.name,NULL AS parent_name FROM copy_parts p JOIN items i USING(item_type,item_no)
            WHERE copy_id=? AND p.parent_minifig IS NULL AND coalesce(p.spare,0)=0 ORDER BY p.id''', (selected['id'],))]
        spare_lines = db.execute('SELECT count(*) FROM copy_parts WHERE copy_id=? AND coalesce(spare,0)=1', (selected['id'],)).fetchone()[0]
        components = defaultdict(list)
        for component in db.execute('''SELECT p.*,i.name FROM copy_parts p JOIN items i USING(item_type,item_no)
            WHERE copy_id=? AND parent_minifig IS NOT NULL AND coalesce(spare,0)=0''', (selected['id'],)):
            components[component['parent_minifig_type'], component['parent_minifig']].append(dict(component))
        figures = [dict(r) for r in db.execute('''SELECT m.*,m.minifig_no AS item_no,NULL AS color_id,i.name,0 AS damaged,0 AS spare
            FROM copy_minifigs m JOIN items i ON (i.item_type,i.item_no)=(m.item_type,m.minifig_no) WHERE copy_id=?''', (selected['id'],))]
        for figure in figures:
            parts = components[figure['item_type'], figure['item_no']]
            figure['parts_lines'] = len(parts)
            figure['parts_missing'] = sum(p['missing'] or 0 for p in parts)
            figure['parts_damaged'] = sum(p['damaged'] or 0 for p in parts)
            figure['missing_part_names'] = list(dict.fromkeys(p['name'] or p['item_no'] for p in parts
                                                            if p['missing']))
        consists += figures
    elif selected and kind == 'M' and selected['entity'] == 'stock':
        consists = [dict(r) for r in db.execute('''SELECT p.*,i.name FROM loose_minifig_parts p JOIN items i USING(item_type,item_no)
            WHERE stock_id=?''', (selected['id'],))]
    else:
        consists = [dict(r) for r in db.execute('''SELECT l.*,l.child_item_type AS item_type,l.child_item_no AS item_no,i.name,
            NULL AS missing,NULL AS damaged,NULL AS checked,0 AS spare FROM inventory_lines l JOIN items i
            ON (i.item_type,i.item_no)=(l.child_item_type,l.child_item_no) WHERE parent_item_type=? AND parent_item_no=?''', (kind, number))]
    row['consists'] = add.decorate_many(db, consists)
    check_recorded = bool(selected and selected['entity']=='copy' and (
        any(r.get('missing') is not None or r.get('checked') for r in consists)
        or any(f['kind']=='status' and f['name']=='Set is checked' for f in selected['flags'])))
    whole_missing = {(r['item_type'], r['minifig_no']): r['missing'] or 0
                     for r in consists if r.get('minifig_no')}
    # Only the gaps that can reach this item's matches: the item's own, plus every other gap of the
    # copies holding them (a match completes a copy only when it is that copy's single gap).
    copy_scope, stock_scope = workbench.relevant(
        db, kind, number, colour,
        copy_ids={selected['id']} if selected and selected['entity'] == 'copy' else (),
        stock_ids={r['id'] for r in all_instances if r['entity'] == 'stock'} if kind in ('M', '?') else ())
    all_gaps = workbench.gaps(db, only=(copy_scope, stock_scope))
    matches = workbench.matches(db, all_gaps=all_gaps)
    if selected and selected['entity']=='stock' and kind=='M':
        row['matches'] = [r for r in matches if (r['target']=='stock-part' and r['copy_id']==selected['id']) or (r['item_type'],r['item_no'],r['color_id'])==(kind,number,colour)]
    elif kind == 'S' and selected and selected['entity'] == 'copy':
        row['matches'] = [r for r in matches if r['copy_id'] == selected['id']]
    else:
        row['matches'] = [r for r in matches if (r['item_type'], r['item_no'], r['color_id']) == (kind, number, colour)]
    row['matching_headline'] = matching_headline(row['matches'])
    if kind in ('P', 'M'):
        # 4.9a: the page says "Sorted by fewest parts left": completing matches first, then
        # the destination copy with the fewest distinct required gaps left (stable otherwise).
        left, _ = workbench.completion_context(db, all_gaps)
        row['matches'] = sorted(row['matches'], key=lambda r: (not r['completes'], sum(left[r['copy_id']].values()) if r['copy_id'] in left else 0))
    row['matches'] = [dict(r, display_note=matching_note(r['source_note'])) for r in row['matches']]
    budget = {}
    gap_matches = defaultdict(list)
    for match in row['matches']:
        key = (match['target'], str(match['target_id']))
        gap_matches[key].append(match)
        budget[match['source_id']] = match['have']
    for part in row['consists']:
        whole = whole_missing.get((part.get('parent_minifig_type'), part.get('parent_minifig')), 0)
        part['deficit'] = 0 if part.get('spare') else workbench.part_gap(part, whole)
        target = 'figure' if part.get('minifig_no') else 'part'
        key = (target, str(part.get('minifig_no') or part.get('id')))
        if selected and selected['entity']=='stock' and kind=='M':
            key = ('stock-part', str([part['item_type'],part['item_no'],part['color_id'],part['spare']]))
        need = part['deficit']
        take = 0
        for match in gap_matches.get(key, []):
            amount = min(need, match['suggested'], budget[match['source_id']])
            take += amount
            need -= amount
            budget[match['source_id']] -= amount
        part['can_take'] = take
    # Match and allocate against original gap IDs before merging the read model.
    # This keeps whole-figure exclusion and shared loose-stock budgets unchanged.
    row['consists'] = workbench.merged_inventory(row['consists'])
    required = [p for p in row['consists'] if p['item_type'] != 'M'
                and not p.get('minifig_no') and not p.get('spare')]
    # The same required cards supply every part count, including constituents.
    row['progress'] = dict(
        total=sum(p['quantity'] or 0 for p in required),
        missing=sum(p['deficit'] for p in required),
        checked=sum(p['quantity'] or 0 for p in required if p.get('checked')),
        can_take=sum(p['can_take'] for p in required),
        different=len({(p['item_type'], p['item_no'], p.get('color_id')) for p in required}),
        lines=len(required), checked_lines=sum(bool(p.get('checked')) for p in required),
        check_recorded=check_recorded,
        spare_lines=spare_lines)
    figures = [p for p in row['consists'] if p.get('minifig_no')]
    row['figure_progress'] = dict(total=sum(p['quantity'] or 0 for p in figures),
                                  present=sum(max((p['quantity'] or 0)-(p['missing'] or 0), 0) for p in figures))
    row['progress']['known'] = bool(required) and all(p['missing_recorded'] for p in required) and (
        row['progress']['missing'] > 0 or row['progress']['checked'] > 0
        or any(f['kind']=='status' and f['name']=='Set is checked' for f in (selected or {}).get('flags', [])))
    row['photos'] = [dict(r) for r in db.execute("SELECT * FROM item_images WHERE item_type=? AND item_no=? AND kind='own' AND copy_id IS ? AND stock_id IS ? ORDER BY id", (kind, number, selected['id'] if selected and selected['entity']=='copy' else None, selected['id'] if selected and selected['entity']=='stock' else None))]
    row['instructions'] = [dict(r) for r in db.execute('SELECT * FROM instruction_files WHERE archived_at IS NULL AND item_type=? AND set_no=?', ('S' if kind=='I' else kind, number))]
    consolidated = {}
    for instance in all_instances:
        if instance['entity']!='stock': continue
        key=instance['storage_id'],instance['condition'],instance['lot_id']
        group=consolidated.setdefault(key,dict(instance,quantity=0,lines=[]))
        group['quantity']+=instance['quantity'] or 0
        group['lines'].append(instance)
    row['consolidated']=list(consolidated.values())
    row['used_in'] = add.decorate_many(db, [dict(r) for r in db.execute('''SELECT c.id AS copy_id,c.item_type,c.set_no AS item_no,i.name,p.quantity,p.missing,p.damaged,
        p.color_id FROM copy_parts p JOIN copies c ON c.id=p.copy_id JOIN items i ON (i.item_type,i.item_no)=(c.item_type,c.set_no)
        WHERE p.item_type=? AND p.item_no=? AND p.color_id IS ? AND c.archived_at IS NULL''', (kind, number, colour))])
    if kind in ('M', '?'):
        row['used_in'] += add.decorate_many(db, [dict(r) for r in db.execute('''SELECT c.id AS copy_id,c.item_type,c.set_no AS item_no,i.name,m.quantity,m.missing,NULL AS color_id
            FROM copy_minifigs m JOIN copies c ON c.id=m.copy_id JOIN items i ON (i.item_type,i.item_no)=(c.item_type,c.set_no)
            WHERE m.item_type=? AND m.minifig_no=? AND c.archived_at IS NULL''', (kind, number))])
    if kind in ('M', '?'):
        # The importer can retain a manual figure line in copy_parts as well as
        # its canonical copy_minifigs row. Prefer the latter for this identity.
        row['used_in'] = list({r['copy_id']: r for r in row['used_in']}.values())
    if row['used_in'] and kind not in ('M', '?'):
        labels = copy_labels(db, [r['copy_id'] for r in row['used_in']])
        for used in row['used_in']:
            used['label'] = labels.get(used['copy_id'], 'Set')
    if kind in ('M', '?'):
        figure_detail(db, row)
        # Each loose copy is an independent candidate, with stock capped within
        # that copy. Include every gap so partial coverage cannot count as complete.
        loose_ids = {r['id'] for r in all_instances if r['entity']=='stock'}
        candidates = defaultdict(list)
        for match in matches:
            if match['target']=='stock-part' and match['copy_id'] in loose_ids:
                candidates[match['copy_id']].append(match)
        completed = 0
        for identifier, rows in candidates.items():
            remaining = {r['source_id']: r['have'] for r in rows}
            by_target = defaultdict(list)
            for match in rows:
                by_target[str(match['target_id'])].append(match)
            missing = 0
            for gap in all_gaps:
                if gap['target']!='stock-part' or gap['copy_id']!=identifier:
                    continue
                need = gap['need']
                for match in by_target[str(gap['target_id'])]:
                    take = min(need, remaining[match['source_id']])
                    need -= take
                    remaining[match['source_id']] -= take
                missing += need
            completed += missing == 0
        fits = len({r['copy_id'] for r in row['matches'] if r['target']!='stock-part'})
        row['figure_matching_headline'] = f"Fits {fits} {'set' if fits==1 else 'sets'}, completes {completed} {'figure' if completed==1 else 'figures'}"
    return row


def snapshot(db, table, ids):
    return [dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE id IN ('+','.join('?' for _ in ids)+') ORDER BY id', ids)]


def receipt(db, changes, action):
    audit(db, 'bw_collection', action, [dict(table=t, rows=old) for t,old,new in changes], [dict(table=t, rows=new) for t,old,new in changes])
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def want_placeholder(db, number):
    """Keep unresolved identities wishable without sending them to a catalogue importer."""
    with transaction(db):
        from . import wishlists
        wishlists.require(db)
        if not db.execute("SELECT 1 FROM items WHERE item_type='?' AND item_no=?", (number,)).fetchone():
            raise ValueError('Placeholder is unavailable')
        if db.execute("SELECT 1 FROM wishlist WHERE item_type='?' AND item_no=? AND archived_at IS NULL", (number,)).fetchone():
            raise ValueError('Already on the wishlist')
        stamp = now().isoformat()
        identifier = db.execute("""INSERT INTO wishlist(item_type,item_no,quantity,condition,added_at,updated_at)
            VALUES('?',?,1,'any',?,?)""", (number, stamp, stamp)).lastrowid
        return receipt(db, [('wishlist', [], snapshot(db, 'wishlist', [identifier]))], 'save')


def save(db, entity, ids, data, *, archive=False, expect=None):
    table = TABLES.get(entity)
    if not table or not isinstance(ids, list) or not ids or len(ids)>2000 or len(set(ids)) != len(ids):
        raise ValueError('Choose collection instances')
    fields = {'condition','storage_id','purchase_location_id','purchase_date','purchase_price','purchase_currency','note'}
    if entity == 'copy': fields |= {'completeness','completeness_source','current_value','current_value_currency'}
    if entity == 'stock': fields |= {'lot_id'}
    if entity == 'wish': fields = {'quantity','color_id','condition','max_price','max_price_currency','note','list_id','qty_filled_manual'}
    if entity == 'lot': fields = {'name','note','storage_id','purchase_location_id','purchase_date','purchase_price','purchase_currency'}
    if not isinstance(data,dict): raise ValueError('Choose fields to save')
    edits = {k: (v if v != '' else None) for k,v in data.items() if k in fields}
    if not edits and not archive and 'flags' not in data:
        raise ValueError('Choose a change to save')
    with transaction(db):
        if expect is not None:
            from .api_reads import entity_etag
            from .errors import PreconditionFailed
            if len(ids) != 1 or entity_etag(db, entity, ids[0]) not in expect and '*' not in expect:
                raise PreconditionFailed()
        old = snapshot(db, table, ids)
        if len(old) != len(ids) or any(r['archived_at'] for r in old):
            raise ValueError('Instance is unavailable')
        allowed_conditions = (None,'new','used','any') if entity=='wish' else ((None,'N','U','D') if entity=='stock' else (None,'N','U'))
        if edits.get('condition') not in allowed_conditions:
            raise ValueError('Choose a condition')
        if edits.get('completeness') not in (None,'S','C','I') or edits.get('completeness_source') not in (None,'manual','derived'):
            raise ValueError('Choose completeness and its source')
        for key, ref in [('storage_id','storages'),('purchase_location_id','purchase_locations'),('lot_id','lots')]:
            value = edits.get(key)
            if value is not None:
                live = ' AND archived_at IS NULL'
                if not db.execute('SELECT 1 FROM '+ref+' WHERE id=?'+live,(value,)).fetchone():
                    raise ValueError('Choose an active '+key.replace('_id',''))
        if 'qty_filled_manual' in edits and edits['qty_filled_manual'] is not None:
            try: filled = int(str(edits['qty_filled_manual']))
            except ValueError: raise ValueError('Enter how many you have as a whole number') from None
            if filled < 0 or filled > 99999: raise ValueError('Enter how many you have as a whole number')
            edits['qty_filled_manual'] = filled
        for key in ('purchase_price','current_value','max_price'):
            if edits.get(key) is not None:
                try: value = Decimal(str(edits[key]))
                except InvalidOperation: raise ValueError('Enter a price of zero or more') from None
                if not value.is_finite() or value<0: raise ValueError('Enter a price of zero or more')
                edits[key] = format(value,'f')
        if entity=='wish' and ('max_price' in edits or 'max_price_currency' in edits):
            currency = edits.get('max_price_currency')
            if currency is not None:
                currency = str(currency).strip().upper()
                if not re.fullmatch(r'[A-Z]{3,8}', currency): raise ValueError('Enter a currency of 3 to 8 letters')
            if 'max_price' in edits:
                if edits['max_price'] is None:
                    if currency is not None: raise ValueError('Enter a max price or clear the currency')
                elif currency is None:
                    # Keep the currency the wishes already share; otherwise the configured one.
                    shared = {r['max_price_currency'] for r in old}
                    currency = shared.pop() if len(shared)==1 and None not in shared else upgrade.configured_currency(db)
            else:
                if currency is None or any(r['max_price'] is None for r in old): raise ValueError('Enter a max price before its currency')
            if currency is not None or ('max_price' in edits and edits['max_price'] is None):
                edits['max_price_currency'] = currency
            else:
                edits.pop('max_price_currency', None)
        if 'purchase_date' in edits and edits['purchase_date'] and any(r['purchase_date'] != edits['purchase_date'] for r in old):
            try: datetime.fromisoformat(edits['purchase_date'].replace('Z','+00:00'))
            except ValueError: raise ValueError('Enter a valid purchase date') from None
        if entity=='wish':
            if 'quantity' in edits: edits['quantity'] = add.quantity(edits['quantity'])
            if 'color_id' in edits:
                edits['color_id'] = int(edits['color_id']) if edits['color_id'] is not None else None
                for row in old:
                    if row['item_type']=='P' and not db.execute('SELECT 1 FROM colors WHERE color_id=?',(edits['color_id'],)).fetchone():
                        raise ValueError('Choose a colour')
                    if row['item_type']!='P' and edits['color_id'] is not None: raise ValueError('Only part wishes have a colour')
        if entity == 'wish' and ('list_id' in edits or 'color_id' in edits):
            from . import wishlists
            if 'list_id' in edits: wishlists.require(db, edits['list_id'])
            keys = [(edits.get('list_id',r['list_id']),r['item_type'],r['item_no'],edits.get('color_id',r['color_id'])) for r in old]
            if len(set(keys)) != len(keys): raise errors.Conflict('Selected wishes repeat an item and colour')
            for row in old: wish_collision(db, 'wishlist', dict(row, **edits))
        flag_changes = None
        if 'flags' in data:
            if entity not in ('copy','stock','wish') or len(ids)!=1 or not isinstance(data['flags'],list):
                raise ValueError('Edit flags on one instance')
            flag_ids = set(data['flags'])
            known = {r[0] for r in db.execute('SELECT id FROM flags WHERE archived_at IS NULL')}
            if not flag_ids <= known: raise ValueError('Unknown flag')
            flag_entity = 'wishlist' if entity=='wish' else entity
            before = [dict(r) for r in db.execute('SELECT * FROM item_flags WHERE entity_type=? AND entity_id=? ORDER BY flag_id',(flag_entity,str(ids[0])))]
            db.execute('DELETE FROM item_flags WHERE entity_type=? AND entity_id=?',(flag_entity,str(ids[0])))
            db.executemany('INSERT INTO item_flags VALUES(?,?,?)',[(flag_entity,str(ids[0]),f) for f in sorted(flag_ids)])
            after = [dict(r) for r in db.execute('SELECT * FROM item_flags WHERE entity_type=? AND entity_id=? ORDER BY flag_id',(flag_entity,str(ids[0])))]
            flag_changes = ('item_flags',before,after)
        if archive: edits['archived_at'] = now().isoformat()
        if entity!='lot': edits['updated_at'] = now().isoformat()
        if edits:
            db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in edits)+' WHERE id IN ('+','.join('?' for _ in ids)+')',(*edits.values(),*ids))
        if entity=='copy':
            # A manually chosen value remains manual unless the user explicitly chooses derived.
            if data.get('completeness') and edits.get('completeness_source') not in ('manual','derived'):
                db.execute('UPDATE copies SET completeness_source=\'manual\' WHERE id IN ('+','.join('?' for _ in ids)+')',ids)
            if 'completeness' in data or 'completeness_source' in data or 'flags' in data:
                if len(ids)!=1: raise ValueError('Edit completeness on one copy')
                state = derived_state(db,ids[0])
                if state is not None: db.execute('UPDATE copies SET completeness=? WHERE id=?',(state,ids[0]))
        after = snapshot(db,table,ids)
        if entity=='stock' and not archive:
            old = stock.merge_edited(db, old, after)
            ids = [r['id'] for r in old]
            after = snapshot(db,table,ids)
        changes = [(table,old,after)]
        if flag_changes: changes.append(flag_changes)
        return receipt(db,changes,'archive' if archive else 'save')


def merge_result(db, event_id=None, *, receipt=None):
    """Expose destinations from the committed receipt, without changing save's API."""
    event = receipt if receipt is not None else db.execute('SELECT old_value,new_value FROM events WHERE id=?',(event_id,)).fetchone()
    before, after = json.loads(event['old_value']), json.loads(event['new_value'])
    if before[0]['table'] != 'loose_stock':
        return []
    old = {r['id']: r for r in before[0]['rows']}
    rows = after[0]['rows']
    keys = {stock.merge_key(r) for r in rows if r['archived_at'] and not old[r['id']]['archived_at']}
    return [r for r in rows if not r['archived_at'] and stock.merge_key(r) in keys]


def undo(db, event_id, *, receipt=None):
    with transaction(db):
        event = receipt if receipt is not None else db.execute("SELECT * FROM events WHERE id=? AND entity='bw_collection' AND field IN ('save','archive','restore','photo','caption','attach','label')",(event_id,)).fetchone()
        if not event: raise ValueError('Save is unavailable')
        if db.execute("SELECT 1 FROM events WHERE entity='bw_collection' AND field='undo' AND new_value=?",(json.dumps(int(event_id)),)).fetchone():
            return
        before, after = json.loads(event['old_value']),json.loads(event['new_value'])
        # Receipts written before named lists implicitly belong to the default list.
        for change in before + after:
            if change['table'] == 'wishlist':
                for row in change['rows']: row.setdefault('list_id', 'default')
        restored_lists = {r['id'] for change in before if change['table']=='wishlists' for r in change['rows'] if r['archived_at'] is None}
        active_lists = {r[0] for r in db.execute('SELECT id FROM wishlists WHERE archived_at IS NULL')} if any(c['table']=='wishlist' for c in before) else set()
        for change in before:
            if change['table']=='wishlist' and any(r['archived_at'] is None and r.get('list_id','default') not in active_lists | restored_lists for r in change['rows']):
                raise ValueError('Restore the destination wishlist before Undo')
        for old,new in zip(before,after):
            table = new['table']
            if table == 'wishlists' and not old['rows']:
                if db.execute('SELECT 1 FROM wishlist WHERE list_id=? AND archived_at IS NULL', (new['rows'][0]['id'],)).fetchone():
                    raise ValueError('Wishlist changed · undo its wishes first')
            if table not in {*TABLES.values(),'item_flags','item_images','flags','purchase_locations','storages','instruction_files','wishlists'}: raise ValueError('Unsupported receipt')
            if table=='item_flags':
                sample = (new['rows'] or old['rows'])[0] if new['rows'] or old['rows'] else None
                current = [dict(r) for r in db.execute('SELECT * FROM item_flags WHERE entity_type=? AND entity_id=? ORDER BY flag_id',(sample['entity_type'],sample['entity_id']))] if sample else []
            else: current = snapshot(db,table,[r['id'] for r in new['rows']])
            if current != new['rows']: raise ValueError('Item changed · undo the later save first')
        for old,new in reversed(list(zip(before,after))):
            table = old['table']
            if table=='item_flags':
                sample = (new['rows'] or old['rows'])[0] if new['rows'] or old['rows'] else None
                if sample:
                    db.execute('DELETE FROM item_flags WHERE entity_type=? AND entity_id=?',(sample['entity_type'],sample['entity_id']))
                    db.executemany('INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES(?,?,?)',[(r['entity_type'],r['entity_id'],r['flag_id']) for r in old['rows']])
            elif not old['rows']:
                # Images have no archive field. Undo detaches the association; the local bytes remain.
                if table=='item_images':
                    db.execute('DELETE FROM item_images WHERE id=?',(new['rows'][0]['id'],))
                elif table in {*TABLES.values(), 'flags', 'purchase_locations', 'storages', 'instruction_files','wishlists'}:
                    db.executemany('UPDATE '+table+' SET archived_at=? WHERE id=?',[(now().isoformat(),r['id']) for r in new['rows']])
                else: raise ValueError('Unsupported created record')
            else:
                for r in old['rows']:
                    wish_collision(db, table, r)
                    db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in r if k!='id')+' WHERE id=?',(*[v for k,v in r.items() if k!='id'],r['id']))
        audit(db,'bw_collection','undo',int(event_id),int(event_id))


def photo(db, root, entity, identifier, content, caption):
    from io import BytesIO
    from PIL import Image, UnidentifiedImageError
    if entity not in ('copy','stock'): raise ValueError('Choose an owned instance')
    if not content or len(content)>15*1024*1024: raise ValueError('Choose a photo up to 15 MB')
    try:
        image = Image.open(BytesIO(content)); image.verify()
        image = Image.open(BytesIO(content))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValueError('Choose a readable photo') from None
    # The header gives the size: refuse an oversized photo before decoding it into memory.
    if image.width*image.height>30_000_000: raise ValueError('Choose a smaller photo')
    try:
        image.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError('Choose a readable photo') from None
    root = Path(root).resolve()
    relative = 'data/images/own/'+uuid4().hex+'.jpg'
    target = root/relative
    if not target.resolve().is_relative_to(root/'data/images'):
        raise ValueError('Photo storage is unavailable')
    with transaction(db):
        row = snapshot(db,TABLES[entity],[identifier])
        if not row or row[0]['archived_at']: raise ValueError('Instance is unavailable')
        r=row[0]
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.resolve().is_relative_to(root/'data/images'): raise ValueError('Photo storage is unavailable')
        try:
            image.convert('RGB').save(target,'JPEG',quality=90)
            on_rollback(db,lambda: target.unlink(missing_ok=True))
            cur=db.execute('''INSERT INTO item_images(item_type,item_no,color_id,source,kind,local_path,width,height,fetched_at,copy_id,stock_id,caption,taken_at)
                VALUES(?,?,?,'manual','own',?,?,?,?,?,?,?,?)''',(r['item_type'],r.get('set_no',r.get('item_no')),r.get('color_id'),relative,image.width,image.height,now().isoformat(),identifier if entity=='copy' else None,identifier if entity=='stock' else None,caption,None))
            return receipt(db,[('item_images',[],snapshot(db,'item_images',[cur.lastrowid]))],'photo')
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def caption(db, identifier, value):
    with transaction(db):
        old=snapshot(db,'item_images',[identifier])
        if not old or old[0]['kind']!='own': raise ValueError('Own photo is unavailable')
        db.execute('UPDATE item_images SET caption=? WHERE id=?',(value,identifier))
        return receipt(db,[('item_images',old,snapshot(db,'item_images',[identifier]))],'caption')


def lot_detail(db, identifier, *, include_archived=False):
    r=db.execute('SELECT * FROM lots WHERE id=?',(identifier,)).fetchone()
    if not r or r['archived_at'] and not include_archived: raise ValueError('Lot is unavailable')
    rows=[dict(r) for r in db.execute('''SELECT s.*,i.name FROM loose_stock s JOIN items i USING(item_type,item_no)
        WHERE lot_id=? AND s.archived_at IS NULL''',(identifier,))]
    return dict(r,entity='lot',rows=add.decorate_many(db,rows))


def purchase_places(db):
    rows = [dict(r) for r in db.execute('SELECT * FROM purchase_locations WHERE archived_at IS NULL ORDER BY name,id')]
    totals=defaultdict(lambda:defaultdict(Decimal)); counts=defaultdict(int)
    for r in db.execute('SELECT purchase_location_id,purchase_price,purchase_currency FROM copies WHERE archived_at IS NULL'):
        counts[r['purchase_location_id']]+=1
        if r['purchase_price'] is not None: totals[r['purchase_location_id']][r['purchase_currency'] or 'Currency not recorded']+=Decimal(r['purchase_price'])
    # #46: Orders and Last used are derived, never stored: orders whose store carries the place's name,
    # and the latest purchase date on a copy, a loose item or a lot from there, or that order date.
    orders, last = defaultdict(int), {}
    by_name = {}
    for r in rows:
        by_name.setdefault((r['name'] or '').strip().casefold(), []).append(r['id'])
    for o in db.execute("SELECT store,date_ordered FROM orders WHERE store IS NOT NULL"):
        for identifier in by_name.get(o['store'].strip().casefold(), ()):
            orders[identifier] += 1
            if o['date_ordered']:
                last[identifier] = max(last.get(identifier, ''), o['date_ordered'][:10])
    for o in db.execute('''SELECT purchase_location_id,max(purchase_date) d FROM (
            SELECT purchase_location_id,purchase_date FROM copies WHERE archived_at IS NULL
            UNION ALL SELECT purchase_location_id,purchase_date FROM loose_stock WHERE archived_at IS NULL
            UNION ALL SELECT purchase_location_id,purchase_date FROM lots WHERE archived_at IS NULL)
            WHERE purchase_location_id IS NOT NULL AND purchase_date IS NOT NULL GROUP BY 1'''):
        last[o[0]] = max(last.get(o[0], ''), str(o[1])[:10])
    return [dict(r,count=counts[r['id']],totals=dict(totals[r['id']]),orders=orders[r['id']],last_used=last.get(r['id']) or None) for r in rows]


def search(db, query, limit=20):
    """Local jump projection; the old jump remains available on its old route."""
    query=query.strip()[:100]
    if not query: return dict(query=query,results=[],limit=limit,truncated=False)
    words=list(dict.fromkeys(query.casefold().split()))[:10]
    owned=instances(db)
    candidates={}
    for r in owned:
        key=r['item_type'],r['item_no'],r.get('color_id')
        candidate=candidates.setdefault(key,dict(r,instances=[]))
        candidate['instances'].append(r)
    for raw in db.execute('''SELECT DISTINCT i.*,p.color_id FROM copy_parts p JOIN copies c ON c.id=p.copy_id
        JOIN items i USING(item_type,item_no) WHERE c.archived_at IS NULL'''):
        r=dict(raw);candidates.setdefault((r['item_type'],r['item_no'],r['color_id']),dict(r,instances=[]))
    wishes=[dict(r,entity='wish',instances=[]) for r in db.execute('SELECT w.*,i.name FROM wishlist w JOIN items i USING(item_type,item_no) WHERE w.archived_at IS NULL')]
    rows=[r for r in [*candidates.values(),*wishes] if any(w in ((r['name'] or '')+' '+r['item_no']+' '+str(r.get('id',''))).casefold() for w in words)]
    rows.sort(key=lambda r:(r['item_type']!='S',r.get('entity')=='wish',r['item_no'].casefold() not in words,r['item_no'],str(r.get('id',''))))
    return dict(query=query,results=add.decorate_many(db,rows[:limit]),limit=limit,truncated=len(rows)>limit)


def new_lot(db, ids, data):
    """Assign existing stock to a new lot, without changing its quantities."""
    if not isinstance(ids,list) or not ids or len(ids)>2000 or len(set(ids))!=len(ids):
        raise ValueError('Select loose stock for this lot')
    name=str(data.get('name','')).strip()
    if not name or len(name)>200: raise ValueError('Name the lot')
    storage=data.get('storage_id') or None
    with transaction(db):
        old=snapshot(db,'loose_stock',ids)
        if len(old)!=len(ids) or any(r['archived_at'] for r in old): raise ValueError('Stock is unavailable')
        if storage and not db.execute('SELECT 1 FROM storages WHERE id=? AND archived_at IS NULL',(storage,)).fetchone():
            raise ValueError('Choose active storage')
        identifier=uuid4().hex
        db.execute('INSERT INTO lots(id,name,note,created_date,storage_id) VALUES(?,?,?,?,?)',
            (identifier,name,data.get('note'),now().isoformat(),storage))
        db.execute('UPDATE loose_stock SET lot_id=?,updated_at=? WHERE id IN ('+','.join('?' for _ in ids)+')',
            (identifier,now().isoformat(),*ids))
        return receipt(db,[('lots',[],snapshot(db,'lots',[identifier])),('loose_stock',old,snapshot(db,'loose_stock',ids))],'save')


def matching_headline(matches):
    """Count destination copies once, excluding loose-figure destinations."""
    fits = {r['copy_id'] for r in matches if r['target'] in ('part', 'figure')}
    completes = {r['copy_id'] for r in matches if r['target'] in ('part', 'figure') and r['completes']}
    if not fits:
        return 'Nothing to complete'
    if not completes:
        return f"Fits {len(fits)} {'set' if len(fits)==1 else 'sets'}, completes none"
    headline = f"Completes {len(completes)} {'set' if len(completes)==1 else 'sets'}"
    return headline + (f", fits {len(fits-completes)} more" if fits-completes else '')


def matching_note(note):
    """Keep scanner provenance in the row title, leaving user notes visible."""
    return re.sub(r'Parts inventory scanner event [a-f0-9-]{36}\.?(?:\s*·\s*|\s*$)', '', note or '').strip()


def defects(missing=0, damaged=0):
    """One unsigned defect label for server-rendered and materialized rows."""
    return ' · '.join(f'{count} {label}' for count, label in
                      ((missing, 'missing'), (damaged, 'damaged')) if count)


def wish_collision(db, table, row):
    """Refuse, with a clear message, a wish write that would duplicate another live wish."""
    if table != 'wishlist' or row.get('archived_at') is not None:
        return
    if db.execute('SELECT 1 FROM wishlist WHERE archived_at IS NULL AND id!=? AND item_type=? AND item_no=? AND color_id IS ? AND list_id=?',
                  (row['id'], row['item_type'], row['item_no'], row['color_id'], row.get('list_id','default'))).fetchone():
        raise errors.Conflict('Another live wish for this item and colour exists · archive or edit it first')


def restore(db, table, identifier):
    """Restore an archived collection or location row with a guarded receipt."""
    if table not in {*TABLES.values(), 'flags', 'purchase_locations', 'storages', 'instruction_files'}:
        raise ValueError('Unsupported record')
    with transaction(db):
        before = snapshot(db, table, [identifier])
        if not before: raise ValueError('Record is unavailable')
        if before[0]['archived_at'] is None: raise ValueError('Record is already active')
        if table == 'wishlist':
            from . import wishlists
            wishlists.require(db, before[0]['list_id'])
        wish_collision(db, table, dict(before[0], archived_at=None))
        db.execute('UPDATE '+table+' SET archived_at=NULL WHERE id=?', (identifier,))
        return receipt(db, [(table,before,snapshot(db,table,[identifier]))], 'restore')
