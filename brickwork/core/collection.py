"""Collection projections and guarded receipts on the 4.0 store.

The read side (M.8b, issue #110) is on the 4.0 collection: items are ids (`core/items.py` names them for a screen), copies and stock
carry words (design 5.1), and a retired line (`retired_at`) is never a line of anything (design 4.4). The write side below it
(`save`, `undo`, `photo`, `restore`, `new_lot`, `want_placeholder`) still speaks the 3.3 tables and waits for M.8d: its routes answer
503 until then.
"""
from .transaction import on_rollback, transaction
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote, urlencode

from . import add, stock, collection_prices, errors, items
from .currency import configured_currency
from .admin import audit
from .completeness import derived_state
from .sources.base import now
from ..store4.connect import has_catalogue

TYPES = {'S': 'Sets', 'M': 'Minifigures', 'P': 'Parts', 'I': 'Instructions',
         'O': 'Boxes', 'G': 'Gear', 'B': 'Books', 'C': 'Catalogs'}
TYPE_KIND = {'S': 'set', 'M': 'minifigure', 'P': 'part', 'I': 'instructions', 'O': 'box', 'G': 'gear', 'B': 'book', 'C': 'catalog'}
KIND_TYPE = {kind: letter for letter, kind in TYPE_KIND.items()}
TABLES = {'copy': 'copies', 'stock': 'loose_stock', 'wish': 'wishlist', 'lot': 'lots'}      # the write side, until M.8d
NO_COLOUR = 1                                                                                 # colour 1 is "no colour" (design 3.7)


def type_of(kind):
    return KIND_TYPE.get(kind, '?')


def _in(values):
    """A JSON array for `IN (SELECT value FROM json_each(?))`, in a stable order."""
    return json.dumps(sorted({v for v in values if v is not None}))


def _retail_country(db):
    row = db.execute("SELECT value FROM setting WHERE key='retail_country'").fetchone()
    return row[0] if row and row[0] else 'DE'


def colours(db):
    """Every colour the collection knows, by name."""
    return [dict(color_id=r['id'], name=r['name'], rgb=r['rgb']) for r in db.execute('SELECT id,name,rgb FROM main.color ORDER BY name,id')]


def options(db, *, include_wishlists=False):
    result = dict(storages=[dict(r) for r in db.execute('SELECT * FROM storage WHERE archived_at IS NULL ORDER BY name,id')],
                places=[dict(r) for r in db.execute('SELECT * FROM place WHERE archived_at IS NULL ORDER BY name,id')],
                lots=[dict(r) for r in db.execute('SELECT * FROM lot WHERE archived_at IS NULL ORDER BY name,id')],
                flags=[dict(r) for r in db.execute('SELECT * FROM flag WHERE archived_at IS NULL ORDER BY kind,name,id')],
                colours=colours(db))
    if include_wishlists:
        result['wishlists'] = [dict(r) for r in db.execute('SELECT * FROM wishlist WHERE archived_at IS NULL ORDER BY sort,name,id')]
    return result


# ---------- identity on screen ----------

def priorities(db):
    """The whole `source_priority` setting (metadata, market price and picture orders), read once by a screen."""
    row = db.execute("SELECT value FROM setting WHERE key='source_priority'").fetchone()
    try:
        return json.loads(row[0]) if row else {}
    except (TypeError, ValueError):
        return {}


def _priority(db, group, loaded=None):
    return (loaded if loaded is not None else priorities(db)).get(group, {})


def _picture_rank(order, kind):
    sources = [s.split(':')[0] for s in order.get(kind, order.get('*', ['bricklink', 'rebrickable']))]

    def rank(source):
        for position, wanted in enumerate(sources):
            if source == wanted or source.startswith(wanted + '_'):         # rebrickable -> rebrickable_dump, rebrickable_api
                return position
        return len(sources)
    return rank


def decorate(db, rows, loaded=None):
    """Identity (`core.items`), colour, picture and the unresolved mark for rows that carry `item_id` (and `color_id`).

    Adds `kind`, `item_type` (the screen letter), `number` (the Rebrickable born number first, or a local BrickLink-born item's own
    BrickLink number), `number_source`, `also` (the preferred BrickLink number where it differs), `number_text` (what a screen
    writes), `item_no` (= `number`, '' for an unidentified item), `unidentified`, `unresolved`, `image`, `color_name`, `rgb`, `ink`.
    Name and year stay what the row has; a row without a name takes the item's. Loaded in a fixed number of queries (`loaded` is
    `priorities(db)` when the caller has it)."""
    if not rows:
        return []
    pairs = {(r['item_id'], r.get('color_id')) for r in rows}
    labels = items.labels(db, pairs)
    ids = _in(i for i, _ in pairs)
    unresolved = {r[0] for r in db.execute("""SELECT item_id FROM main.item_link WHERE status='to_check' AND item_id IN (SELECT value FROM json_each(?))
                                              UNION SELECT item_id FROM main.item_provider_status WHERE status='to_check' AND item_id IN (SELECT value FROM json_each(?))""", (ids, ids))}
    colour_rows = {}
    wanted = {c for _, c in pairs if c is not None}
    for store in ('main', 'catalogue'):
        left = wanted - colour_rows.keys()
        if not left or (store == 'catalogue' and not has_catalogue(db)):
            break
        for r in db.execute(f'SELECT id,name,rgb FROM {store}.color WHERE id IN (SELECT value FROM json_each(?))', (_in(left),)):
            colour_rows.setdefault(r['id'], r)
    order = _priority(db, 'pictures', loaded)
    kind_of = {label.item_id: label.kind for label in labels.values()}
    ranks = {}
    pictures = {}
    for position, r in enumerate(db.execute('SELECT id,item_id,color_id,source FROM picture WHERE item_id IN (SELECT value FROM json_each(?)) ORDER BY fetched_at DESC,id DESC', (ids,))):
        kind = kind_of.get(r['item_id'], '*')
        rank = ranks.setdefault(kind, _picture_rank(order, kind))
        candidate = (rank(r['source']), position, r['id'])
        key = r['item_id'], r['color_id']
        if key not in pictures or candidate < pictures[key]:
            pictures[key] = candidate
    result = []
    for source in rows:
        row = dict(source)
        label = labels.get((row['item_id'], row.get('color_id')))
        if label is not None:
            row.update(kind=label.kind, item_type=type_of(label.kind), number=label.number, number_source=label.source, also=label.also,
                       number_text=label.text, item_no=label.number or '', unidentified=label.unidentified)
            row.setdefault('name', label.name)
            if not row.get('name'):
                row['name'] = label.name
        else:
            row.update(item_type='?', number=None, number_source=None, also=None, number_text='', item_no='', unidentified=True)
        found = [pictures[key] for key in {(row['item_id'], None), (row['item_id'], row.get('color_id'))} if key in pictures]
        row['image'] = min(found)[2] if found else None
        row['unresolved'] = bool(row['unidentified'] or row['item_id'] in unresolved)
        colour = colour_rows.get(row.get('color_id'))
        row['color_name'] = colour['name'] if colour else None
        rgb = (colour['rgb'] if colour else None) or ''
        row['rgb'] = rgb if re.fullmatch('[a-fA-F0-9]{6}', rgb) else None
        row['ink'] = add.colour_ink(row['rgb'])
        result.append(row)
    return result


def identity_link(row):
    """The query arguments of an item page for a row: the colour of a part."""
    return {'colour': row['color_id']} if row.get('color_id') is not None and row.get('item_type') == 'P' else {}


# ---------- properties and prices ----------

def properties(db, item_ids, kinds=None, loaded=None):
    """`{item_id: {key: dict(value, unit, source, fetched_at, alternatives)}}`: the best source per key by the metadata priority
    (a source order per kind word; `kinds` is `{item id: kind}` when the caller knows it, else it is read)."""
    item_ids = list(item_ids)
    priority = _priority(db, 'metadata', loaded)
    if kinds is None:
        kinds = {r['id']: r['kind'] for r in db.execute('SELECT id,kind FROM main.item WHERE id IN (SELECT value FROM json_each(?))', (_in(item_ids),))}
    grouped = defaultdict(list)
    for r in db.execute('SELECT * FROM item_property WHERE item_id IN (SELECT value FROM json_each(?)) ORDER BY key,source', (_in(item_ids),)):
        grouped[r['item_id'], r['key']].append(dict(r))
    result = defaultdict(dict)
    for (item_id, key), rows in grouped.items():
        order = [s.split(':')[0] for s in priority.get(kinds.get(item_id), priority.get('*', []))]
        rows.sort(key=lambda r: order.index(r['source']) if r['source'] in order else len(order))
        result[item_id][key] = dict(rows[0], alternatives=rows[1:])
    return result


def prices(db, item_id=None, colour=None, *, pairs=None, used_sold=False):
    """Current quotes (`price_current` over its observation, a voided observation never shows).

    One item and colour -> a list; `pairs` (item id, colour id) rows -> `{(item, colour): [quotes]}`. `used_sold` keeps only
    the used, sold-guide, non-boxed quote: all a list row's price ever reads."""
    if pairs is not None:
        where, params = 'WHERE p.item_id IN (SELECT value FROM json_each(?))', [_in(i for i, _ in pairs)]
    else:
        where, params = 'WHERE p.item_id=? AND p.color_id IS ?', [item_id, colour]
    where += ' AND o.voided_at IS NULL'
    if used_sold:
        where += " AND p.condition='used' AND p.guide='sold' AND coalesce(p.slot,'')<>'boxed'"
    rows = db.execute('''SELECT p.item_id,p.color_id,p.condition,p.guide,p.slot,p.region,p.currency,p.observation_id,i.kind,
        o.source,o.price,o.min,o.max,o.qty,o.sold,o.observed_at,o.error,o.provider_key,f.max_age_days
        FROM price_current p JOIN price_observation o ON o.id=p.observation_id JOIN item i ON i.id=p.item_id
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices' ''' + where +
        ' ORDER BY p.item_id,p.condition,p.guide,p.currency,p.slot,p.region', params).fetchall()
    result = defaultdict(list)
    for r in decorate_prices(rows):
        result[r['item_id'], r['color_id']].append(r)
    return result if pairs is not None else result.get((item_id, colour), [])


def decorate_prices(rows):
    result = []
    current = None
    for raw in rows:
        r = dict(raw)
        r['item_type'] = type_of(r.get('kind')) if r.get('kind') else r.get('item_type')
        r['label'] = {'new': 'New', 'used': 'Used'}.get(r['condition'], 'Price')
        if r['guide'] == 'stock':
            r['label'] += ' listings'
        if r['slot']:
            r['label'] = 'With box' if r['item_type'] == 'S' and r['slot'] == 'boxed' else r['label'] + ' · ' + r['slot'].replace('_', ' ')
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


# ---------- instances: copies and stock ----------

def _scope(include_archived, alias):
    return '1=1' if include_archived else f'{alias}.archived_at IS NULL'


def _flags(db, scopes):
    """`{(entity, id): [flags]}` for the copy, stock and wish ids in `scopes` ({'copy': ids, ...}; None = all of that entity); a
    flag shows on every row it is on. One query for all three; statuses before tags, by name."""
    parts, params = [], []
    for entity, table, column in (('copy', 'copy_flag', 'copy_id'), ('stock', 'stock_flag', 'stock_id'), ('wish', 'wish_flag', 'wish_id')):
        if entity not in scopes or (scopes[entity] is not None and not scopes[entity]):
            continue
        where = f' WHERE x.{column} IN (SELECT value FROM json_each(?))' if scopes[entity] is not None else ''
        parts.append(f"SELECT f.*,'{entity}' AS entity_type,x.{column} AS entity_id FROM {table} x JOIN flag f ON f.id=x.flag_id AND f.archived_at IS NULL{where}")
        if scopes[entity] is not None:
            params.append(_in(scopes[entity]))
    flags = defaultdict(list)
    if parts:
        for r in db.execute(' UNION ALL '.join(parts) + ' ORDER BY kind,name,id', params):
            flags[r['entity_type'], r['entity_id']].append(dict(r))
    return flags


def _copy_defects(db, where, params):
    """`{copy id: (missing, damaged, parts missing, figures missing)}`: the live, non-spare set lines and the missing whole figures
    (design 4.4: a retired line is no line). `missing` counts both."""
    return {r['copy_id']: (r['parts'] + r['figures'], r['damaged'], r['parts'], r['figures']) for r in db.execute(f'''SELECT copy_id,
        sum(parts) AS parts,sum(figures) AS figures,sum(damaged) AS damaged FROM
        (SELECT copy_id,missing AS parts,0 AS figures,damaged FROM copy_part WHERE retired_at IS NULL AND is_spare=0 AND copy_figure_id IS NULL
         UNION ALL SELECT copy_id,0,missing,0 FROM copy_figure WHERE retired_at IS NULL)
        WHERE copy_id IN (SELECT c.id FROM copy c WHERE {where}) GROUP BY copy_id''', params)}


_COPY = '''SELECT c.*,i.kind,i.name,i.year,i.theme_name AS theme,i.category_name AS category,
    s.name AS storage_name,p.name AS place_name,NULL AS color_id,1 AS quantity,'copy' AS entity
    FROM copy c JOIN item i ON i.id=c.item_id LEFT JOIN storage s ON s.id=c.storage_id LEFT JOIN place p ON p.id=c.place_id'''
_STOCK = '''SELECT s.*,i.name,i.year,i.theme_name AS theme,i.category_name AS category,t.name AS storage_name,
    p.name AS place_name,l.name AS lot_name,'stock' AS entity
    FROM stock s JOIN item i ON i.id=s.item_id
    LEFT JOIN storage t ON t.id=s.storage_id LEFT JOIN place p ON p.id=s.place_id LEFT JOIN lot l ON l.id=s.lot_id'''


def instances(db, kind=None, *, include_archived=False, item_id=None):
    """Bulk physical rows (copies, then stock); API archive reads opt in, web defaults stay live-only.

    `kind` is a kind word (None for all); `item_id` scopes the read to one item: same rows, same labels, same order. Rows are
    decorated (`decorate`), copies are labelled `Set N` in creation order, flags are on the rows."""
    rows = _instances(db, kind, include_archived, item_id)
    out = decorate(db, rows)
    for row in out:
        row['flags'] = row.pop('_flags')
    return out


def _instances(db, kind, include_archived, item_id):
    """`instances` before decoration: the rows with their flags in `_flags`."""
    one, params = (' AND c.item_id=?', [item_id]) if item_id is not None else ('', [])
    where = f'{_scope(include_archived, "c")}{one}'
    copies = []
    if kind in (None, 'set'):
        copies = [dict(r) for r in db.execute(f'{_COPY} WHERE {where} ORDER BY c.item_id,c.created_at,c.id', params)]
        counts = defaultdict(int)
        for row in copies:
            counts[row['item_id']] += 1
            row['label'] = 'Set ' + str(counts[row['item_id']])
        defects = _copy_defects(db, where, params)
        for row in copies:
            row['missing'], row['damaged'], row['missing_parts'], row['missing_figures'] = defects.get(row['id'], (0, 0, 0, 0))
    stock_where = f'{_scope(include_archived, "s")}' + (' AND s.item_id=?' if item_id is not None else '') + (' AND s.kind=?' if kind else '')
    stock_params = ([item_id] if item_id is not None else []) + ([kind] if kind else [])
    rows = [] if kind == 'set' else [dict(r) for r in db.execute(f'{_STOCK} WHERE {stock_where} ORDER BY s.item_id,s.color_id,s.created_at,s.id', stock_params)]
    flags = _flags(db, {'copy': [r['id'] for r in copies], 'stock': [r['id'] for r in rows]} if item_id is not None or kind else {'copy': None, 'stock': None})
    for row in copies + rows:
        row['_flags'] = flags[row['entity'], row['id']]
    return copies + rows


def instance(db, entity, identifier):
    """One physical row (archived included) shaped exactly like ``instances(include_archived=True)``.

    Keyed lookups only: no collection-wide scan, so a single read costs the same on any size of store."""
    if entity == 'copy':
        row = db.execute(f'{_COPY} WHERE c.id=?', (identifier,)).fetchone()
        if not row:
            return None
        row = dict(row)
        # "Set N" is the position among every copy of the set (archived included), in creation order.
        row['label'] = 'Set ' + str(db.execute('''SELECT count(*) FROM copy d WHERE d.item_id=? AND (d.created_at,d.id)<=(?,?)''',
                                               (row['item_id'], row['created_at'], row['id'])).fetchone()[0])
        row['missing'], row['damaged'], row['missing_parts'], row['missing_figures'] = _copy_defects(db, 'c.id=?', (identifier,)).get(identifier, (0, 0, 0, 0))
    else:
        row = db.execute(f'{_STOCK} WHERE s.id=?', (identifier,)).fetchone()
        if not row:
            return None
        row = dict(row)
    row = decorate(db, [row])[0]
    row['flags'] = _flags(db, {entity: [identifier]})[entity, identifier]
    return row


def copy_labels(db, ids):
    """`{copy id: 'Set N'}` for live copies among `ids`, numbered as `instances(db, 'set')` numbers them."""
    return {r[0]: 'Set ' + str(r[1]) for r in db.execute('''SELECT c.id,(SELECT count(*) FROM copy d WHERE d.archived_at IS NULL
        AND d.item_id=c.item_id AND (d.created_at,d.id)<=(c.created_at,c.id)) FROM copy c
        WHERE c.archived_at IS NULL AND c.id IN (SELECT value FROM json_each(?))''', (_in(ids),))}


# ---------- the lists ----------

def _blank(row, **extra):
    return dict(row, quantity=0, instances=[], ids=[], conditions=[], statuses=[], storages=[], places=[], flag_names=[], lots=[],
                missing=0, damaged=0, **extra)


def listing(db, type_letter, *, wishes=False):
    """The rows of a collection screen: `type_letter` S, M, P, I, O, G, B or C (wishes: every kind, `type_letter` is ignored).

    A row is an item (and colour): its owned instances grouped, with counts in sets for parts and figures, the used-sold price,
    and the theme, category and year projected on the item (design 6.3)."""
    loaded = priorities(db)
    if wishes:
        rows = [dict(r, entity='wish', instances=[]) for r in db.execute('''SELECT w.*,w.wishlist_id AS list_id,i.name,i.year,i.theme_name AS theme,
            i.category_name AS category,l.name AS list_name FROM wish w JOIN wishlist l ON l.id=w.wishlist_id JOIN item i ON i.id=w.item_id
            WHERE w.archived_at IS NULL ORDER BY w.added_at,w.id''')]
        rows = decorate(db, rows, loaded)
        flags = _flags(db, {'wish': None})
        for row in rows:
            row['flags'] = flags['wish', row['id']]
            row['flag_names'] = [f['name'] or '' for f in row['flags']]
    else:
        if type_letter not in TYPES:
            raise ValueError('Unknown collection')
        kind = TYPE_KIND[type_letter]
        grouped = {}
        for r in _instances(db, kind, False, None):
            r['flags'] = r.pop('_flags')
            key = r['item_id'], r.get('color_id')
            row = grouped.setdefault(key, _blank(r, missing_parts=0, missing_figures=0) if kind == 'set' else _blank(r))
            row['quantity'] += r['quantity'] or 0
            row['instances'].append(r)
            row['missing_parts'] = row.get('missing_parts', 0) + r.get('missing_parts', 0)
            row['missing_figures'] = row.get('missing_figures', 0) + r.get('missing_figures', 0)
            row['ids'].append(r['id'])
            row['conditions'].append(r['condition'] or '')
            row['statuses'].append(r.get('completeness') or '')
            row['storages'].append(r['storage_id'] or 'null')
            row['places'].append(r['place_id'] or 'null')
            row['flag_names'].extend(f['name'] or '' for f in r['flags'])
            row['lots'].append(r.get('lot_id') or 'null')
            row['missing'] += r.get('missing') or 0
            row['damaged'] += r.get('damaged') or 0
        rows = list(grouped.values())
        in_sets = []
        if kind == 'part':
            in_sets = [dict(r) for r in db.execute('''SELECT p.item_id,p.color_id,sum(p.quantity) AS quantity,sum(p.missing) AS missing,sum(p.damaged) AS damaged
                FROM copy_part p JOIN copy c ON c.id=p.copy_id WHERE c.archived_at IS NULL AND p.retired_at IS NULL AND p.is_spare=0
                GROUP BY p.item_id,p.color_id''')]
        elif kind == 'minifigure':
            in_sets = [dict(r) for r in db.execute('''SELECT f.item_id,NULL AS color_id,sum(f.quantity) AS quantity,sum(f.missing) AS missing,0 AS damaged
                FROM copy_figure f JOIN copy c ON c.id=f.copy_id WHERE c.archived_at IS NULL AND f.retired_at IS NULL GROUP BY f.item_id''')]
        base = {}
        if in_sets:
            for r in db.execute('''SELECT i.id AS item_id,i.name,i.year,i.theme_name AS theme,i.category_name AS category,i.kind FROM item i
                                   WHERE i.id IN (SELECT value FROM json_each(?))''', (_in(r['item_id'] for r in in_sets),)):
                base[r['item_id']] = dict(r)
        for raw in in_sets:
            key = raw['item_id'], raw['color_id']
            row = grouped.get(key)
            if row is None:
                row = grouped[key] = _blank(dict(base[raw['item_id']], color_id=raw['color_id'], entity='stock'))
                rows.append(row)
            row['in_sets'] = (row.get('in_sets') or 0) + (raw['quantity'] or 0)
            row['missing'] += raw['missing'] or 0
            row['damaged'] += raw['damaged'] or 0
        rows = decorate(db, rows, loaded)
        if kind != 'set':
            for row in rows:
                row.pop('missing_parts', None), row.pop('missing_figures', None)
        if kind == 'instructions':
            # Booklets share their set's files, just as on the detail screen: an instructions item is a set's booklet.
            files = instruction_files(db, [r['item_id'] for r in rows])
            for row in rows:
                row['pdf_available'] = any(f['path'] for f in files.get(row['item_id'], []))
    pairs = [(r['item_id'], r.get('color_id')) for r in rows]
    props = properties(db, [i for i, _ in pairs], {r['item_id']: r['kind'] for r in rows}, loaded)
    market = prices(db, pairs=pairs) if wishes else prices(db, pairs=pairs, used_sold=True)       # a list row reads one quote, so only that one is fetched
    price_priority = loaded.get('market_price', {})
    for row in rows:
        row['properties'] = props.get(row['item_id'], {})
        row['theme'] = row.get('theme') or row['properties'].get('theme', {}).get('value', '')
        row['prices'] = market.get((row['item_id'], row.get('color_id')), [])
        row['price'] = collection_prices.choose([p for p in row['prices'] if p['guide'] == 'sold' and p.get('slot') != 'boxed'], row['kind'], price_priority, 'used')
    return rows


def part_colours(db, item_id):
    """Active colours of a part from stock, set lines and wishes, in one read."""
    return [dict(r, ink=add.colour_ink(r['rgb'])) for r in db.execute("""SELECT x.color_id,c.name AS color_name,c.rgb,
        sum(x.quantity) AS quantity FROM (
        SELECT color_id,quantity FROM stock WHERE kind='part' AND item_id=? AND archived_at IS NULL AND quantity>0
        UNION ALL SELECT p.color_id,max(p.quantity-p.missing,0) FROM copy_part p JOIN copy c ON c.id=p.copy_id
            WHERE p.item_id=? AND c.archived_at IS NULL AND p.retired_at IS NULL AND p.is_spare=0 AND p.quantity>0
        UNION ALL SELECT color_id,0 FROM wish WHERE kind='part' AND item_id=? AND archived_at IS NULL AND quantity>0
        ) x LEFT JOIN color c ON c.id=x.color_id GROUP BY x.color_id
        ORDER BY c.name,x.color_id""", (item_id, item_id, item_id))]


def external_links(db, row):
    """Catalogue links of a set: BrickLink by its BrickLink number, Brickset by a confirmed Brickset link (a number of the set
    itself otherwise). An unidentified set, or one with no BrickLink number, has none."""
    if row['item_type'] != 'S' or row.get('unidentified'):
        return []
    links = []
    try:
        kind, number, _ = items.bricklink_key(db, row['item_id'])
        links.append(('BrickLink', 'https://www.bricklink.com/v2/catalog/catalogitem.page?' + urlencode({kind: number})))
    except errors.Unidentified:
        pass
    numbers = {r[0] for r in db.execute("""SELECT provider_key FROM main.item_link WHERE provider='brickset' AND item_id=?
        AND status IN ('matched','inferred','manual')""", (row['item_id'],)) if r[0]}
    ambiguous = db.execute("""SELECT 1 FROM main.item_link WHERE provider='brickset' AND item_id=? AND status='to_check'
        UNION SELECT 1 FROM main.item_provider_status WHERE provider='brickset' AND item_id=? AND status IN ('to_check','unmatched') LIMIT 1""",
        (row['item_id'], row['item_id'])).fetchone()
    if not numbers and not ambiguous and re.fullmatch(r'[0-9]+-[0-9]+', row.get('number') or ''):
        numbers.add(row['number'])
    if len(numbers) == 1:
        links.append(('Brickset', 'https://brickset.com/sets/' + quote(numbers.pop(), safe='')))
    return links


# ---------- the item page ----------

def part_gap(row, whole_missing=0):
    """Required replacements, with whole missing figures covering constituents."""
    return max(0, (row['missing'] or 0) + (row['damaged'] or 0) - whole_missing * (row['quantity'] or 0))


def _names(db, ids):
    found = {}
    for store in ('main', 'catalogue') if has_catalogue(db) else ('main',):
        for r in db.execute(f'SELECT id,name,kind FROM {store}.item WHERE id IN (SELECT value FROM json_each(?))', (_in(ids),)):
            found.setdefault(r['id'], dict(r))
    return found


def _line(item_id, color_id, quantity, *, id=None, missing=None, damaged=None, checked=None, spare=0, figure=None):
    return dict(id=id, item_id=item_id, color_id=color_id, quantity=quantity, missing=missing, damaged=damaged, checked=checked,
                spare=spare, minifig=figure)


def _catalogue_lines(db, item_id):
    """The reference part list of an item that has no copy of its own to show: the catalogue's latest (design 4.1), else the
    newest list fetched for it (design 4.2). `[(line, kind)]` with parts first, then figures; the state is not recorded."""
    parts, figures = [], []
    if has_catalogue(db):
        inventory = db.execute('SELECT id FROM catalogue.inventory WHERE item_id=? AND is_latest=1 AND retired_at IS NULL', (item_id,)).fetchone()
        if inventory:
            parts = [(r['item_id'], r['color_id'], r['quantity']) for r in db.execute(
                'SELECT item_id,color_id,quantity FROM catalogue.inventory_part WHERE inventory_id=? AND is_spare=0 ORDER BY item_id,color_id', (inventory[0],))]
            figures = [(r['item_id'], r['quantity']) for r in db.execute('SELECT item_id,quantity FROM catalogue.inventory_figure WHERE inventory_id=? ORDER BY item_id', (inventory[0],))]
    if not parts and not figures:
        fetched = db.execute('SELECT id FROM fetched_inventory WHERE item_id=? AND is_latest=1 ORDER BY fetched_at DESC,id DESC', (item_id,)).fetchone()
        if fetched:
            parts = [(r['item_id'], r['color_id'], r['quantity']) for r in db.execute(
                'SELECT item_id,color_id,quantity FROM fetched_inventory_part WHERE fetched_inventory_id=? AND is_spare=0', (fetched[0],))]
            figures = [(r['item_id'], r['quantity']) for r in db.execute('SELECT item_id,quantity FROM fetched_inventory_figure WHERE fetched_inventory_id=?', (fetched[0],))]
    return [_line(i, c, q) for i, c, q in parts], [_line(i, None, q) for i, q in figures]


def _consists(db, item_id, kind, selected):
    """`(lines, spare_lines)`: what the item page lists under "Consists of".

    A copy lists its own live set lines and its live figure lines (a figure's parts are on the figure's page); a loose figure its
    own live parts; any other set or figure the reference list. Retired lines are no lines (design 4.4)."""
    if selected and selected['entity'] == 'copy':
        cid = selected['id']
        lines = [_line(r['item_id'], r['color_id'], r['quantity'], id=r['id'], missing=r['missing'], damaged=r['damaged'], checked=r['checked'], spare=r['is_spare'])
                 for r in db.execute('SELECT * FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL AND is_spare=0 ORDER BY id', (cid,))]
        spare = db.execute('SELECT count(*) FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL AND is_spare=1', (cid,)).fetchone()[0]
        components = defaultdict(list)
        for r in db.execute('SELECT * FROM copy_part WHERE copy_id=? AND copy_figure_id IS NOT NULL AND retired_at IS NULL AND is_spare=0', (cid,)):
            components[r['copy_figure_id']].append(dict(r))
        figures = []
        for f in db.execute('SELECT * FROM copy_figure WHERE copy_id=? AND retired_at IS NULL ORDER BY id', (cid,)):
            parts = components[f['id']]
            line = _line(f['item_id'], None, f['quantity'], id=f['id'], missing=f['missing'], damaged=0, figure=True)
            line.update(parts_lines=len(parts), parts_missing=sum(p['missing'] for p in parts), parts_damaged=sum(p['damaged'] for p in parts),
                        missing_part_ids=[p['item_id'] for p in parts if p['missing']])
            figures.append(line)
        return lines + figures, spare
    if selected and selected['entity'] == 'stock' and kind == 'minifigure':
        return [_line(r['item_id'], r['color_id'], r['quantity'], id=r['id'], missing=r['missing'], damaged=r['damaged'], checked=r['checked'], spare=r['is_spare'])
                for r in db.execute('SELECT * FROM stock_part WHERE stock_id=? AND retired_at IS NULL ORDER BY id', (selected['id'],))], 0
    if kind in ('set', 'minifigure'):
        parts, figures = _catalogue_lines(db, item_id)
        return parts + (figures if kind == 'set' else []), 0
    return [], 0


def detail(db, item_id, *, colour=None, copy_id=None, stock_id=None, wish_id=None):
    """Everything the item page shows. `colour` is a colour id for a part (a part is always held in a colour)."""
    base = db.execute('SELECT * FROM main.item WHERE id=?', (item_id,)).fetchone()
    if base is None and has_catalogue(db):
        base = db.execute('SELECT id,kind,name,year FROM catalogue.item WHERE id=?', (item_id,)).fetchone()
    if base is None:
        raise ValueError('Item is unavailable')
    kind = base['kind']
    letter = type_of(kind)
    if kind != 'part':
        colour = None
    all_instances = [r for r in instances(db, kind, item_id=item_id) if kind != 'part' or r['color_id'] == colour]
    selected = next((r for r in all_instances if r['id'] == (copy_id or stock_id)), None)
    if copy_id or stock_id:
        if selected is None:
            raise ValueError('Instance is unavailable')
    elif all_instances:
        selected = all_instances[0]
    wish = None
    if wish_id:
        r = db.execute('SELECT * FROM wish WHERE id=? AND archived_at IS NULL', (wish_id,)).fetchone()
        if not r or r['item_id'] != item_id or (kind == 'part' and r['color_id'] != colour):
            raise ValueError('Wish is unavailable')
        wish = dict(r, entity='wish', list_id=r['wishlist_id'], flags=_flags(db, {'wish': [wish_id]})['wish', wish_id])
        selected = wish
    row = decorate(db, [dict(item_id=item_id, color_id=colour, name=base['name'], year=base['year'],
                             theme=base['theme_name'] if 'theme_name' in base.keys() else None,
                             category=base['category_name'] if 'category_name' in base.keys() else None)])[0]
    props = properties(db, [item_id]).get(item_id, {})
    row.update(instances=all_instances, selected=selected, wish=wish, properties=props, prices=prices(db, item_id, colour))
    row['theme'] = row.get('theme') or props.get('theme', {}).get('value', '')
    row['external_links'] = external_links(db, row)
    price_priority = collection_prices.priority(db)
    observations = [dict(r, item_type=letter) for r in db.execute('''SELECT o.*,f.max_age_days FROM price_observation o
        LEFT JOIN source_freshness f ON f.source=o.source AND f.kind='prices'
        WHERE o.item_id=? AND o.color_id IS ? AND o.voided_at IS NULL ORDER BY o.observed_at DESC,o.id DESC''', (item_id, colour))]
    row['price_records'] = decorate_prices(observations)
    row['condition_prices'] = collection_prices.condition_rows(row['price_records'], kind, price_priority)
    row['price_history'] = collection_prices.history(observations, collection_prices.choose([p for p in row['price_records'] if p['guide'] == 'sold' and p.get('slot') != 'boxed'], kind, price_priority, 'used'))
    valuation = [p for p in row['price_records'] if p['guide'] in ('valuation', 'manual') or p.get('slot') == 'boxed']
    row['valuation_prices'] = [p for slot in ('boxed', 'estimate') if (p := collection_prices.choose([p for p in valuation if (p.get('slot') == 'boxed') == (slot == 'boxed')], kind, price_priority))]
    row['retail'] = retail(db, item_id) if kind == 'set' else None
    row['retail_saving'] = None
    if row['retail'] and selected and selected['entity'] == 'copy':
        from . import retail as retail_module
        row['retail_saving'] = retail_module.saving(selected.get('purchase_price'), selected.get('purchase_currency'), row['retail'], exchange_rates(db))
    row['partout'] = None                                                  # parted-out value comes back with M.8g
    lines, spare_lines = _consists(db, item_id, kind, selected)
    names = _names(db, [l['item_id'] for l in lines] + [pid for l in lines for pid in l.get('missing_part_ids', [])])
    consists = []
    for line in lines:
        entry = dict(line, name=(names.get(line['item_id']) or {}).get('name'))
        if line.get('minifig'):
            entry['missing_part_names'] = list(dict.fromkeys((names.get(i) or {}).get('name') or str(i) for i in line['missing_part_ids']))
        consists.append(entry)
    consists = decorate(db, consists)
    for entry in consists:
        if entry.pop('minifig', None):
            entry['minifig_no'] = entry['item_no'] or str(entry['item_id'])
        entry['contexts'] = [dict(entry, contexts=None)]
        entry['missing_recorded'] = entry['missing'] is not None
        entry['deficit'] = 0 if entry['spare'] else part_gap(entry)
        entry['can_take'] = 0                                              # the loose stock that could fill a gap is the Matcher's, M.8e
    row['consists'] = consists
    required = [p for p in consists if p['item_type'] != 'M' and not p.get('minifig_no') and not p['spare']]
    flag_names = [f['name'] for f in (selected or {}).get('flags', []) if f['kind'] == 'status']
    check_recorded = bool(selected and selected['entity'] == 'copy' and (
        any(r['checked'] or r['missing'] or r['damaged'] for r in consists if r['missing'] is not None) or 'Set is checked' in flag_names))
    row['progress'] = dict(
        total=sum(p['quantity'] or 0 for p in required), missing=sum(p['deficit'] for p in required),
        checked=sum(p['quantity'] or 0 for p in required if p.get('checked')), can_take=None,
        different=len({(p['item_id'], p.get('color_id')) for p in required}),
        lines=len(required), checked_lines=sum(bool(p.get('checked')) for p in required),
        check_recorded=check_recorded, spare_lines=spare_lines)
    figures = [p for p in consists if p.get('minifig_no')]
    row['figure_progress'] = dict(total=sum(p['quantity'] or 0 for p in figures),
                                  present=sum(max((p['quantity'] or 0)-(p['missing'] or 0), 0) for p in figures))
    row['progress']['known'] = bool(required) and bool(selected and selected['entity'] == 'copy') and (
        row['progress']['missing'] > 0 or row['progress']['checked'] > 0 or 'Set is checked' in flag_names)
    owner = selected if selected and selected['entity'] in ('copy', 'stock') else None
    row['photos'] = [dict(r, url=None) for r in db.execute(                   # the file route for an own photo comes with M.8d
        'SELECT * FROM photo WHERE item_id=? AND copy_id IS ? AND stock_id IS ? AND archived_at IS NULL ORDER BY created_at,id',
        (item_id, owner['id'] if owner and owner['entity'] == 'copy' else None, owner['id'] if owner and owner['entity'] == 'stock' else None))]
    row['instructions'] = instruction_files(db, [item_id]).get(item_id, [])
    consolidated = {}
    for instance in all_instances:
        if instance['entity'] != 'stock':
            continue
        key = instance['storage_id'], instance['condition'], instance['lot_id']
        group = consolidated.setdefault(key, dict(instance, quantity=0, lines=[]))
        group['quantity'] += instance['quantity'] or 0
        group['lines'].append(instance)
    row['consolidated'] = list(consolidated.values())
    row['used_in'] = _used_in(db, item_id, colour, kind)
    if kind == 'minifigure':
        figure_detail(db, row)
    return row


def instruction_files(db, item_ids):
    """`{item id: [files]}`: a booklet shares its files with the set of the same number, in both directions (concept: Boxes and instructions)."""
    found = defaultdict(list)
    for r in db.execute("""SELECT a.id AS owner,f.* FROM main.item a JOIN main.item b ON b.id=a.id
        OR (b.born_key=a.born_key AND a.born_key IS NOT NULL AND b.kind IN ('set','instructions') AND a.kind IN ('set','instructions'))
        JOIN instruction_file f ON f.item_id=b.id AND f.archived_at IS NULL
        WHERE a.id IN (SELECT value FROM json_each(?)) ORDER BY f.id""", (_in(item_ids),)):
        found[r['owner']].append(dict(r))
    return found


def _used_in(db, item_id, colour, kind):
    """The live copies that hold the item: a part by its set lines and figure components, a figure by its figure lines."""
    if kind == 'minifigure':
        found = db.execute('''SELECT c.id AS copy_id,c.item_id AS set_id,f.quantity,f.missing,0 AS damaged,NULL AS color_id
            FROM copy_figure f JOIN copy c ON c.id=f.copy_id WHERE f.item_id=? AND f.retired_at IS NULL AND c.archived_at IS NULL ORDER BY c.item_id,c.created_at,c.id''', (item_id,))
    else:
        found = db.execute('''SELECT c.id AS copy_id,c.item_id AS set_id,sum(p.quantity) AS quantity,sum(p.missing) AS missing,sum(p.damaged) AS damaged,p.color_id
            FROM copy_part p JOIN copy c ON c.id=p.copy_id WHERE p.item_id=? AND p.color_id IS ? AND p.is_spare=0 AND p.retired_at IS NULL AND c.archived_at IS NULL
            GROUP BY c.id ORDER BY c.item_id,c.created_at,c.id''', (item_id, colour))
    used = [dict(r) for r in found]
    decorated = {r['item_id']: r for r in decorate(db, [dict(item_id=s, color_id=None) for s in sorted({u['set_id'] for u in used})])}
    labels = copy_labels(db, [u['copy_id'] for u in used])
    out = []
    for u in used:
        s = decorated[u['set_id']]
        out.append(dict(u, item_id=u['set_id'], item_type=s['item_type'], item_no=s['item_no'], number_text=s['number_text'], name=s['name'],
                        image=s['image'], color_name=None, rgb=None, ink=None, unresolved=s['unresolved'], unidentified=s['unidentified'],
                        label=labels.get(u['copy_id'], 'Set'), kind=s['kind'], number=s['number'], also=s['also']))
    return out


def figure_detail(db, row):
    """Figure-wide display facts: its parts across every holder, the sets and the wishes it is in (retired lines excluded)."""
    item_id = row['item_id']
    components = [dict(r) for r in db.execute('''SELECT p.item_id,p.color_id,p.quantity,p.missing,p.damaged,p.copy_id,f.quantity AS figures,f.missing AS figures_missing
        FROM copy_part p JOIN copy_figure f ON f.id=p.copy_figure_id AND f.copy_id=p.copy_id JOIN copy c ON c.id=p.copy_id
        WHERE f.item_id=? AND p.retired_at IS NULL AND f.retired_at IS NULL AND c.archived_at IS NULL AND p.is_spare=0''', (item_id,))]
    loose = [dict(r, stock_id=r['stock_id']) for r in db.execute('''SELECT p.item_id,p.color_id,p.quantity,p.missing,p.damaged,p.stock_id FROM stock_part p
        JOIN stock s ON s.id=p.stock_id WHERE s.item_id=? AND s.archived_at IS NULL AND p.retired_at IS NULL AND p.is_spare=0''', (item_id,))]
    catalogue, _ = _catalogue_lines(db, item_id)
    copies = copy_labels(db, [p['copy_id'] for p in components] + [u['copy_id'] for u in row['used_in']])
    set_numbers = {u['copy_id']: u['number_text'] or u['name'] for u in row['used_in']}
    parts = {}
    for p in [*catalogue, *components, *loose]:
        key = p['item_id'], p['color_id']
        part = parts.setdefault(key, dict(item_id=p['item_id'], color_id=p['color_id'], quantity=p['quantity'], warnings=[]))
        warning = None
        if p.get('copy_id') in copies:
            per_figure = (p['quantity'] / p['figures']) if p.get('figures') else 0
            gap = max(0, (p['missing'] or 0) + (p['damaged'] or 0) - (p['figures_missing'] or 0) * per_figure)
            if gap:
                warning = dict(label=copies[p['copy_id']], item_no=set_numbers.get(p['copy_id'], ''), missing=p['missing'] or 0, damaged=p['damaged'] or 0)
        elif (p.get('missing') or p.get('damaged')) and p.get('stock_id'):
            warning = dict(label='Loose', item_no='', missing=p.get('missing') or 0, damaged=p.get('damaged') or 0)
        if warning and warning not in part['warnings']:
            part['warnings'].append(warning)
    names = _names(db, [k[0] for k in parts])
    row['figure_components'] = decorate(db, [dict(p, name=names.get(p['item_id'], {}).get('name')) for p in parts.values()])
    for used in row['used_in']:
        used['parts_missing'] = sum((p['missing'] or 0) + (p['damaged'] or 0) for p in components if p['copy_id'] == used['copy_id'])
    row['loose_count'] = sum(r['quantity'] or 0 for r in row['instances'])
    row['set_count'] = sum(r['quantity'] or 0 for r in row['used_in'])
    row['loose_conditions'] = {}
    for r in row['instances']:
        condition = r.get('condition')
        row['loose_conditions'][condition] = row['loose_conditions'].get(condition, 0) + (r['quantity'] or 0)
    row['figure_wishes'] = [dict(r) for r in db.execute('SELECT * FROM wish WHERE item_id=? AND archived_at IS NULL ORDER BY added_at,id', (item_id,))]
    row['catalogue_ids'] = {'Rebrickable': row['number'] if row.get('number_source') == 'rebrickable' else None, 'BrickLink': None, 'Brickset': None}
    if row.get('number_source') == 'bricklink':
        row['catalogue_ids']['BrickLink'] = row['number']
    for r in db.execute("""SELECT provider,provider_key FROM main.item_link WHERE item_id=? AND status IN ('matched','inferred','manual')
                           ORDER BY preferred DESC,provider,provider_key""", (item_id,)):
        label = {'bricklink': 'BrickLink', 'brickset': 'Brickset'}.get(r['provider'])
        if label and (row['catalogue_ids'][label] is None):
            row['catalogue_ids'][label] = r['provider_key']


# ---------- retail and rates ----------

def retail(db, item_id):
    """Retail price and availability (Brickset, #26) for the retail country, or None when the set has none of it."""
    where = _retail_country(db)
    found = {}
    r = db.execute('''SELECT o.price,o.currency FROM price_current c JOIN price_observation o ON o.id=c.observation_id
        WHERE c.item_id=? AND c.guide='retail' AND c.slot='retail' AND c.region=? AND o.voided_at IS NULL''', (item_id, where)).fetchone()
    if r:
        found.update(price=r['price'], currency=r['currency'])
    for r in db.execute('''SELECT key,value FROM item_property WHERE item_id=? AND source='brickset'
            AND key IN ('dateFirstAvailable','dateLastAvailable')''', (item_id,)):
        found['first' if r['key'] == 'dateFirstAvailable' else 'last'] = (r['value'] or '')[:10] or None
    if not found:
        return None
    from datetime import timedelta
    today = now().date()
    try:
        last = datetime.fromisoformat(str(found.get('last'))[:10]).date() if found.get('last') else None
    except ValueError:
        last = None
    found['country'] = where
    found['status'] = (None if last is None else 'Retired' if last < today else 'Retiring' if last <= today + timedelta(days=183) else 'Available')
    return found


def exchange_rates(db):
    """`{currency: dict(per_eur, as_of, source)}` including EUR = 1 (the 4.0 `exchange_rate` table)."""
    out = {'EUR': dict(per_eur=Decimal(1), as_of=None, source='fixed')}
    for r in db.execute('SELECT currency,per_eur,as_of,source FROM exchange_rate'):
        try:
            out[r[0]] = dict(per_eur=Decimal(r[1]), as_of=r[2], source=r[3])
        except InvalidOperation:
            continue
    return out


# ---------- lots, places, jump ----------

def lot_detail(db, identifier, *, include_archived=False):
    r = db.execute('SELECT * FROM lot WHERE id=?', (identifier,)).fetchone()
    if not r or r['archived_at'] and not include_archived:
        raise ValueError('Lot is unavailable')
    rows = [dict(x, entity='stock') for x in db.execute(f'{_STOCK} WHERE s.lot_id=? AND s.archived_at IS NULL ORDER BY s.item_id,s.color_id,s.created_at,s.id', (identifier,))]
    return dict(r, entity='lot', rows=decorate(db, rows))


def purchase_places(db):
    rows = [dict(r) for r in db.execute('SELECT * FROM place WHERE archived_at IS NULL ORDER BY name,id')]
    totals = defaultdict(lambda: defaultdict(Decimal))
    counts = defaultdict(int)
    for r in db.execute('SELECT place_id,purchase_price,purchase_currency FROM copy WHERE archived_at IS NULL'):
        counts[r['place_id']] += 1
        if r['purchase_price'] is not None:
            totals[r['place_id']][r['purchase_currency'] or 'Currency not recorded'] += Decimal(r['purchase_price'])
    # #46: Orders and Last used are derived, never stored: orders whose store carries the place's name,
    # and the latest purchase date on a copy, a loose item or a lot from there, or that order date.
    orders, last = defaultdict(int), {}
    by_name = {}
    for r in rows:
        by_name.setdefault((r['name'] or '').strip().casefold(), []).append(r['id'])
    for o in db.execute('SELECT store,date_ordered FROM purchase_order WHERE store IS NOT NULL'):
        for identifier in by_name.get(o['store'].strip().casefold(), ()):
            orders[identifier] += 1
            if o['date_ordered']:
                last[identifier] = max(last.get(identifier, ''), o['date_ordered'][:10])
    for o in db.execute('''SELECT place_id,max(purchase_date) d FROM (
            SELECT place_id,purchase_date FROM copy WHERE archived_at IS NULL
            UNION ALL SELECT place_id,purchase_date FROM stock WHERE archived_at IS NULL
            UNION ALL SELECT place_id,purchase_date FROM lot WHERE archived_at IS NULL)
            WHERE place_id IS NOT NULL AND purchase_date IS NOT NULL GROUP BY 1'''):
        last[o[0]] = max(last.get(o[0], ''), str(o[1])[:10])
    return [dict(r, count=counts[r['id']], totals=dict(totals[r['id']]), orders=orders[r['id']], last_used=last.get(r['id']) or None) for r in rows]


def _like(word):
    return '%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def search(db, query, limit=20):
    """Local jump projection: what you own or want that a word of the query names, by name or by either number.

    A word matches an item's name, its born (Rebrickable) number, any confirmed BrickLink number, the item id, or the id of a
    copy or stock line. Sets first, then the exact number, then the number."""
    query = query.strip()[:100]
    if not query:
        return dict(query=query, results=[], limit=limit, truncated=False)
    words = list(dict.fromkeys(query.casefold().split()))[:10]
    matching = set()
    db.create_function('bw_fold', 1, lambda text: str(text).casefold() if text is not None else None, deterministic=True)   # SQLite's LIKE folds ASCII only
    for word in words:
        pattern = _like(word)
        matching |= {r[0] for r in db.execute("""SELECT id FROM main.item WHERE bw_fold(name) LIKE ?1 ESCAPE '\\' OR born_key LIKE ?1 ESCAPE '\\' OR cast(id AS TEXT)=?2
            UNION SELECT item_id FROM main.item_link WHERE provider='bricklink' AND status IN ('matched','inferred','manual') AND provider_key LIKE ?1 ESCAPE '\\'""",
            (pattern, word))}
    candidates = {}
    for r in _instances(db, None, False, None):
        if r['item_id'] in matching or any(w in str(r['id']).casefold() for w in words):
            candidate = candidates.setdefault((r['item_id'], r.get('color_id')), dict(r, instances=[]))
            candidate['instances'].append(r)
    for raw in db.execute('''SELECT DISTINCT p.item_id,p.color_id FROM copy_part p JOIN copy c ON c.id=p.copy_id
            WHERE c.archived_at IS NULL AND p.retired_at IS NULL AND p.is_spare=0 AND p.item_id IN (SELECT value FROM json_each(?))
            UNION SELECT DISTINCT f.item_id,NULL FROM copy_figure f JOIN copy c ON c.id=f.copy_id
            WHERE c.archived_at IS NULL AND f.retired_at IS NULL AND f.item_id IN (SELECT value FROM json_each(?))''', (_in(matching), _in(matching))):
        candidates.setdefault((raw[0], raw[1]), dict(item_id=raw[0], color_id=raw[1], entity='stock', instances=[]))
    wishes = [dict(r, entity='wish', instances=[]) for r in db.execute('SELECT * FROM wish WHERE archived_at IS NULL AND item_id IN (SELECT value FROM json_each(?)) ORDER BY added_at,id', (_in(matching),))]
    rows = decorate(db, [*candidates.values(), *wishes])
    for row in rows:
        row['instances'] = [dict(i, flags=i.pop('_flags', [])) for i in row['instances']]
    numbers = {w for w in words}
    rows.sort(key=lambda r: (r['item_type'] != 'S', r.get('entity') == 'wish', (r['number'] or '').casefold() not in numbers and (r['also'] or '').casefold() not in numbers,
                             r['item_no'], str(r.get('id', ''))))
    return dict(query=query, results=rows[:limit], limit=limit, truncated=len(rows) > limit)


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
                    currency = shared.pop() if len(shared)==1 and None not in shared else configured_currency(db)
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
