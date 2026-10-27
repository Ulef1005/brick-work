"""Collection projections and guarded receipts on the 4.0 store.

The read side (M.8b, issue #110) is on the 4.0 collection: items are ids (`core/items.py` names them for a screen), copies and stock
carry words (design 5.1), and a retired line (`retired_at`) is never a line of anything (design 4.4). The write side (M.8d) is `save`,
`new_lot`, `restore`, `photo`, `caption` and `want`: each makes ONE receipt event and `undo` reverses it (see "writes" below).
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

from . import add, stock, collection_prices, errors, items, pictures
from . import undo as undoing
from .currency import configured_currency
from .admin import audit, origin
from .completeness import derived_state
from .sources.base import now
from ..store4 import identity
from ..store4.connect import has_catalogue, now as stamp_now

TYPES = {'S': 'Sets', 'M': 'Minifigures', 'P': 'Parts', 'I': 'Instructions',
         'O': 'Boxes', 'G': 'Gear', 'B': 'Books', 'C': 'Catalogs'}
TYPE_KIND = {'S': 'set', 'M': 'minifigure', 'P': 'part', 'I': 'instructions', 'O': 'box', 'G': 'gear', 'B': 'book', 'C': 'catalog'}
KIND_TYPE = {kind: letter for letter, kind in TYPE_KIND.items()}
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
    sources = [s.split(':')[0] for s in order.get(kind) or order.get('*') or pictures.DEFAULT_ORDER.get(kind, pictures.DEFAULT_ORDER['*'])]

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
    row['partout'] = None
    if kind == 'set' and selected and selected['entity'] == 'copy':
        # #38: complete, as is and parted out for the shown copy.
        from . import partout, planning
        config, stamp = planning.configuration(db), now()
        complete = planning.quote(row['prices'], selected.get('condition') or 'used', config, stamp)
        override = selected.get('current_value')
        as_is = (Decimal(str(override)) if override is not None and selected.get('current_value_currency') == config['bricklink_currency']
                 else Decimal(str(complete['price'])) * (100 - config['incomplete_discount_pct']) / 100 if complete else None)
        row['partout'] = partout.compare(dict(complete_quote=complete, current_value=as_is), partout.values(db, [selected['id']]).get(selected['id']))
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
        entry['can_take'] = 0
    row.update(_matching(db, item_id, kind, colour, selected, all_instances, consists))
    row['consists'] = consists
    required = [p for p in consists if p['item_type'] != 'M' and not p.get('minifig_no') and not p['spare']]
    flag_names = [f['name'] for f in (selected or {}).get('flags', []) if f['kind'] == 'status']
    check_recorded = bool(selected and selected['entity'] == 'copy' and (
        any(r['checked'] or r['missing'] or r['damaged'] for r in consists if r['missing'] is not None) or 'Set is checked' in flag_names))
    row['progress'] = dict(
        total=sum(p['quantity'] or 0 for p in required), missing=sum(p['deficit'] for p in required),
        checked=sum(p['quantity'] or 0 for p in required if p.get('checked')), can_take=sum(p['can_take'] for p in required),
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


def _matching(db, item_id, kind, colour, selected, all_instances, consists):
    """The Matching module of the item page (M.8e): the loose stock that could fill the gaps this page is about, and how many each
    "consists of" line could take. Only the gaps that can reach this item's matches are read (`workbench.relevant`). Sets the `can_take`
    of the lines in `consists` and returns `matches`, `matching_headline` (and, for a figure, its headline and groups)."""
    from . import workbench
    stock_ids = {r['id'] for r in all_instances if r['entity'] == 'stock'} if kind == 'minifigure' else set()
    copy_ids = {selected['id']} if selected and selected['entity'] == 'copy' else set()
    all_gaps = workbench.gaps(db, only=workbench.relevant(db, item_id, colour, kind, copy_ids=copy_ids, stock_ids=stock_ids))
    found = workbench.matches(db, all_gaps=all_gaps)
    loose_figure = bool(selected and selected['entity'] == 'stock' and kind == 'minifigure')
    if loose_figure:
        mine = [r for r in found if (r['target'] == 'stock-part' and r['copy_id'] == selected['id']) or r['key'] == (item_id, colour)]
    elif kind == 'set' and selected and selected['entity'] == 'copy':
        mine = [r for r in found if r['copy_id'] == selected['id']]
    elif kind in ('instructions', 'box'):
        number = workbench._booklet_numbers(db, [dict(item_id=item_id)]).get(item_id)
        mine = [r for r in found if number is not None and r['key'] == (kind, number)]
    else:
        mine = [r for r in found if r['key'] == (item_id, colour)]
    out = dict(matching_headline=matching_headline(mine))
    if kind in ('part', 'minifigure'):
        # The page says "Sorted by fewest parts left": completing matches first, then the destination copy with the fewest distinct
        # required gaps left (stable otherwise).
        left, _ = workbench.completion_context(db, all_gaps)
        mine = sorted(mine, key=lambda r: (not r['completes'], sum(left[r['copy_id']].values()) if r['copy_id'] in left else 0))
    mine = [dict(r, display_note=matching_note(r['source_note'])) for r in mine]
    budget, by_gap = {}, defaultdict(list)
    for match in mine:
        by_gap[match['target'], str(match['target_id'])].append(match)
        budget[match['source_id']] = match['have']
    for entry in consists:
        target = 'stock-part' if loose_figure else 'figure' if entry.get('minifig_no') else 'part'
        need, take = entry['deficit'], 0
        for match in by_gap.get((target, str(entry['id'])), []):
            amount = min(need, match['suggested'], budget[match['source_id']])
            take += amount
            need -= amount
            budget[match['source_id']] -= amount
        entry['can_take'] = take
    out['matches'] = mine
    if kind == 'minifigure':
        for match in mine:
            match['display_item'] = match['copy']
        out['matching_groups'] = [('Copies that need this figure', [r for r in mine if r['target'] != 'stock-part']),
                                  ('Loose copies that could fill them', [r for r in mine if r['target'] == 'stock-part'])]
        # Each loose copy is an independent candidate, with stock capped within that copy. Every gap counts, so partial coverage cannot
        # count as complete.
        loose_ids = {r['id'] for r in all_instances if r['entity'] == 'stock'}
        candidates = defaultdict(list)
        for match in found:
            if match['target'] == 'stock-part' and match['copy_id'] in loose_ids:
                candidates[match['copy_id']].append(match)
        completed = 0
        for identifier, rows in candidates.items():
            remaining = {r['source_id']: r['have'] for r in rows}
            by_target = defaultdict(list)
            for match in rows:
                by_target[str(match['target_id'])].append(match)
            missing = 0
            for gap in all_gaps:
                if gap['target'] != 'stock-part' or gap['copy_id'] != identifier:
                    continue
                need = gap['need']
                for match in by_target[str(gap['target_id'])]:
                    take = min(need, remaining[match['source_id']])
                    need -= take
                    remaining[match['source_id']] -= take
                missing += need
            completed += missing == 0
        fits = len({r['copy_id'] for r in mine if r['target'] != 'stock-part'})
        out['figure_matching_headline'] = f"Fits {fits} {'set' if fits == 1 else 'sets'}, completes {completed} {'figure' if completed == 1 else 'figures'}"
    return out


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
        found = db.execute('''SELECT c.id AS copy_id,c.item_id AS set_id,f.id AS copy_figure_id,f.quantity,f.missing,0 AS damaged,NULL AS color_id
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
    rows.sort(key=lambda r: (r['kind'] != 'set', r.get('entity') == 'wish', (r['number'] or '').casefold() not in numbers and (r['also'] or '').casefold() not in numbers,
                             r['item_no'], str(r.get('id', ''))))
    return dict(query=query, results=rows[:limit], limit=limit, truncated=len(rows) > limit)


# ---------- writes (M.8d): one receipt event per request, undone by one registered undoer ----------
#
# A request that changes the collection writes ONE event `(collection, -, <field>)` (field `save`, `archive`, `restore`, `photo` or
# `caption`) whose `old_value` and `new_value` list the changed tables with the rows before and after (`receipt`). Undo
# (`_undo_collection`, registered below) refuses unless every row still equals its `new_value`, then puts the `old_value` rows back
# (a row the request created is archived) and writes `event_undo`. Row ids and columns are the 4.0 ones; a generated column is never
# part of a receipt.

LINK_TABLES = {'copy_flag': 'copy_id', 'stock_flag': 'stock_id', 'wish_flag': 'wish_id'}      # a flag link has no id: its owner column keys it
ENTITY_FLAGS = {'copy': 'copy_flag', 'stock': 'stock_flag', 'wish': 'wish_flag'}
RECEIPT_TABLES = {'copy', 'stock', 'wish', 'lot', 'wishlist', 'flag', 'storage', 'place', 'instruction_file', 'photo', 'copy_part', 'copy_figure',
                  'stock_part', *LINK_TABLES}                  # the last four are what Take and Give change (M.8e)
INTEGER_IDS = {'instruction_file', 'copy_part', 'copy_figure', 'stock_part'}
RESTORABLE = {'copy', 'stock', 'wish', 'lot', 'wishlist', 'flag', 'storage', 'place', 'instruction_file', 'photo'}
FIELDS = {
    'copy': {'condition', 'storage_id', 'place_id', 'purchase_date', 'purchase_price', 'purchase_currency', 'note', 'completeness',
             'completeness_source', 'current_value', 'current_value_currency'},
    'stock': {'condition', 'storage_id', 'place_id', 'purchase_date', 'purchase_price', 'purchase_currency', 'note', 'lot_id'},
    'wish': {'quantity', 'color_id', 'condition', 'max_price', 'max_price_currency', 'note', 'wishlist_id', 'qty_filled_manual'},
    'lot': {'name', 'note', 'storage_id', 'place_id', 'purchase_date', 'purchase_price', 'purchase_currency'},
}
CONDITIONS = {'copy': (None, 'new', 'used'), 'stock': (None, 'new', 'used', 'damaged'), 'wish': (None, 'new', 'used', 'any'), 'lot': (None,)}
PAIRS = (('purchase_price', 'purchase_currency'), ('current_value', 'current_value_currency'), ('max_price', 'max_price_currency'))
STAMPED = ('copy', 'stock', 'wish', 'lot')                      # tables with `updated_at`


def columns(db, table):
    """The stored columns of a table (a generated column is derived, so it is neither kept in a receipt nor written back)."""
    if table not in RECEIPT_TABLES:
        raise ValueError('Unsupported record')
    return [r['name'] for r in db.execute(f'PRAGMA main.table_xinfo({table})') if r['hidden'] == 0]


def snapshot(db, table, ids):
    names = ','.join(columns(db, table))
    ids = [int(i) if table in INTEGER_IDS else str(i) for i in ids]
    return [dict(r) for r in db.execute(f'SELECT {names} FROM main.{table} WHERE id IN (SELECT value FROM json_each(?)) ORDER BY id', (json.dumps(ids),))]


def links(db, table, owner):
    owner_column = LINK_TABLES[table]
    return [dict(r) for r in db.execute(f'SELECT * FROM main.{table} WHERE {owner_column}=? ORDER BY flag_id', (owner,))]


def receipt(db, changes, field, entity='collection'):
    """Write the one event of a request: `changes` is `[(table, rows before, rows after)]`. Returns the event id. `entity` is the event's
    kind: the workbench and the ledger write theirs under their own names and register the same undoer for them."""
    audit(db, entity, field, [dict(table=t, rows=old) for t, old, new in changes], [dict(table=t, rows=new) for t, old, new in changes])
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def _need_live(db, table, value, what):
    if value is not None and not db.execute(f'SELECT 1 FROM main.{table} WHERE id=? AND archived_at IS NULL', (value,)).fetchone():
        raise ValueError('Choose an active ' + what)


def _price(value, what='price'):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f'Enter a {what} of zero or more') from None
    if not number.is_finite() or number < 0:
        raise ValueError(f'Enter a {what} of zero or more')
    return format(number, 'f')


def _currency(value):
    value = str(value).strip().upper()
    if not re.fullmatch(r'[A-Z]{3,8}', value):
        raise ValueError('Enter a currency of 3 to 8 letters')
    return value


def _pairs(db, edits, old):
    """Money is decimal text with its currency, both or neither (design 2.4 invariant 12): clearing a price clears its currency, a price
    with no currency takes the one the rows share, else the configured one, and a currency alone needs a price already there."""
    for price, currency in PAIRS:
        if price not in edits and currency not in edits:
            continue
        named = _currency(edits[currency]) if edits.get(currency) is not None else None
        if price in edits:
            if edits[price] is None:
                if named is not None and price == 'max_price':
                    raise ValueError('Enter a max price or clear the currency')
                edits[currency] = None                           # a cleared price takes its currency with it
            else:
                edits[price] = _price(edits[price], 'max price' if price == 'max_price' else 'price')
                shared = {r[currency] for r in old}
                edits[currency] = named or (shared.pop() if len(shared) == 1 and None not in shared else configured_currency(db))
        elif named is None:
            raise ValueError('Enter a price or clear the currency')
        elif any(r[price] is None for r in old):
            raise ValueError('Enter a price before its currency')
        else:
            edits[currency] = named


def save(db, entity, ids, data, *, archive=False):
    """Edit or archive collection rows (copies, loose stock, wishes, lots), with their flags, under one receipt. Returns the event id.

    `data` holds the column values to set (an empty string clears a column) and, for one row, `flags` (the flag ids the row should
    have among the live flags; links to archived flags are left alone). Stock that ends up with another live row's merge key merges into
    it (`stock.plan_edit`), and the receipt keeps both rows."""
    table = entity if entity in FIELDS else None
    if not table or not isinstance(ids, list) or not ids or len(ids) > 2000 or len(set(ids)) != len(ids):
        raise ValueError('Choose collection instances')
    if not isinstance(data, dict):
        raise ValueError('Choose fields to save')
    edits = {k: (v if v != '' else None) for k, v in data.items() if k in FIELDS[table]}
    if 'list_id' in data and table == 'wish':                      # the 3.3 name of the wish's list, still sent by older pages
        edits['wishlist_id'] = data['list_id'] or None
    if not edits and not archive and 'flags' not in data:
        raise ValueError('Choose a change to save')
    with transaction(db):
        old = snapshot(db, table, ids)
        if len(old) != len(ids) or any(r['archived_at'] for r in old):
            raise ValueError('Instance is unavailable')
        if 'condition' in edits and edits['condition'] not in CONDITIONS[table]:
            raise ValueError('Choose a condition')
        if edits.get('completeness') not in (None, 'sealed', 'complete', 'incomplete') or edits.get('completeness_source') not in (None, 'manual', 'derived'):
            raise ValueError('Choose completeness and its source')
        for key, ref, what in (('storage_id', 'storage', 'storage'), ('place_id', 'place', 'place'), ('lot_id', 'lot', 'lot')):
            _need_live(db, ref, edits.get(key), what)
        if edits.get('qty_filled_manual') is not None:
            try:
                filled = int(str(edits['qty_filled_manual']))
            except ValueError:
                raise ValueError('Enter how many you have as a whole number') from None
            if not 0 <= filled <= 99999:
                raise ValueError('Enter how many you have as a whole number')
            edits['qty_filled_manual'] = filled
        if 'purchase_date' in edits and edits['purchase_date'] and any(r['purchase_date'] != edits['purchase_date'] for r in old):
            try:
                datetime.fromisoformat(edits['purchase_date'].replace('Z', '+00:00'))
            except ValueError:
                raise ValueError('Enter a valid purchase date') from None
        _pairs(db, edits, old)
        if table == 'wish':
            _check_wish_edits(db, ids, old, edits)
        if table == 'lot' and 'name' in edits and (edits['name'] is None or len(str(edits['name']).strip()) > 200):
            raise ValueError('Name the lot')
        changes = []
        flag_change = None
        if 'flags' in data:
            if table not in ENTITY_FLAGS or len(ids) != 1 or not isinstance(data['flags'], list):
                raise ValueError('Edit flags on one instance')
            flag_change = _set_flags(db, table, str(ids[0]), set(data['flags']))
        stamp = stamp_now()
        written = dict(edits)
        if archive:
            written['archived_at'] = stamp
        if table in STAMPED:
            written['updated_at'] = stamp
        everything = old
        if table == 'stock' and edits and not archive:
            plan = stock.plan_edit(db, old, edits)
            everything = old + snapshot(db, 'stock', [t for _, t in plan if t is not None and t not in ids])
            stock.apply_edit(db, old, edits, plan, stamp=stamp)
        elif written:
            if table == 'copy' and edits.get('completeness') is not None and len(ids) == 1 and 'completeness_source' not in edits:
                row = old[0]
                if row['completeness'] != edits['completeness'] or row['completeness_source'] != 'derived':
                    written['completeness_source'] = 'manual'    # a value the user chose stays theirs; the same value of a derived copy stays derived
            db.execute(f'UPDATE main.{table} SET ' + ','.join(f'{k}=?' for k in written) + ' WHERE id IN (SELECT value FROM json_each(?))', (*written.values(), json.dumps(ids)))
        if table == 'copy':
            if archive:
                _release_pending(db, old)
            if any(k in data for k in ('completeness', 'completeness_source', 'flags')):
                if len(ids) != 1:
                    raise ValueError('Edit completeness on one copy')
                state = derived_state(db, ids[0])
                if state is not None:
                    db.execute('UPDATE main.copy SET completeness=? WHERE id=?', (state, ids[0]))
        changes.append((table, everything, snapshot(db, table, [r['id'] for r in everything])))
        if flag_change:
            changes.append(flag_change)
        return receipt(db, changes, 'archive' if archive else 'save')


def _check_wish_edits(db, ids, old, edits):
    if 'quantity' in edits:
        edits['quantity'] = add.quantity(edits['quantity'])
    if 'color_id' in edits:
        colour = int(edits['color_id']) if edits['color_id'] is not None else None
        edits['color_id'] = colour
        for row in old:
            if row['kind'] == 'part':
                if colour is None:
                    raise ValueError('Choose a colour')
                try:
                    identity.project_color(db, colour)
                except Exception:
                    raise ValueError('Choose a colour') from None
            elif colour is not None:
                raise ValueError('Only part wishes have a colour')
    if 'wishlist_id' in edits:
        _need_live(db, 'wishlist', edits['wishlist_id'], 'wishlist')
        if edits['wishlist_id'] is None:
            raise ValueError('Choose a wishlist')
    if 'wishlist_id' in edits or 'color_id' in edits:
        keys = [(edits.get('wishlist_id', r['wishlist_id']), r['item_id'], edits.get('color_id', r['color_id'])) for r in old]
        if len(set(keys)) != len(keys):
            raise errors.Conflict('Selected wishes repeat an item and colour')
        for row in old:
            wish_collision(db, 'wish', dict(row, **{k: v for k, v in edits.items() if k in ('wishlist_id', 'color_id')}))


def _set_flags(db, table, owner, wanted):
    """Make the live flags on a row exactly `wanted`. Returns the receipt change for the link table, or None when nothing changed."""
    link = ENTITY_FLAGS[table]
    live = {r[0] for r in db.execute('SELECT id FROM main.flag WHERE archived_at IS NULL')}
    if not wanted <= live:
        raise ValueError('Unknown flag')
    before = links(db, link, owner)
    held = {r['flag_id'] for r in before}
    column = LINK_TABLES[link]
    for flag in sorted((held & live) - wanted):
        db.execute(f'DELETE FROM main.{link} WHERE {column}=? AND flag_id=?', (owner, flag))
    for flag in sorted(wanted - held):
        db.execute(f'INSERT INTO main.{link}({column}, flag_id) VALUES(?, ?)', (owner, flag))
    after = links(db, link, owner)
    return (link, before, after) if before != after else None


def _release_pending(db, old):
    """An archived copy no longer waits for a BrickLink list (the cancel is its own event, as the Add undo makes it)."""
    from ..store4 import pending
    via, actor = origin()
    for row in old:
        if row['inventory_pending']:
            pending.cancel_pending_in(db, row['id'], via=via, actor=actor)


def wish_collision(db, table, row):
    """Refuse, with a clear message, a wish write that would duplicate another live wish of the same list, item and colour."""
    if table != 'wish' or row.get('archived_at') is not None:
        return
    if db.execute('SELECT 1 FROM main.wish WHERE archived_at IS NULL AND id!=? AND wishlist_id=? AND item_id=? AND color_id IS ?',
                  (row['id'], row['wishlist_id'], row['item_id'], row['color_id'])).fetchone():
        raise errors.Conflict('Another live wish for this item and colour exists · archive or edit it first')


def merge_result(db, event_id=None, *, receipt=None):
    """The live stock rows a save merged other rows into, read from its committed receipt (empty when nothing merged)."""
    event = receipt if receipt is not None else db.execute('SELECT old_value,new_value FROM main.event WHERE id=?', (event_id,)).fetchone()
    before, after = json.loads(event['old_value']), json.loads(event['new_value'])
    if before[0]['table'] != 'stock':
        return []
    old = {r['id']: r for r in before[0]['rows']}
    rows = after[0]['rows']
    keys = {stock.merge_key(r) for r in rows if r['archived_at'] and not old[r['id']]['archived_at']}
    return [r for r in rows if not r['archived_at'] and stock.merge_key(r) in keys]


# ---------- undo ----------

def _undo_collection(db, event, via, actor):
    """Put every row of a receipt back as it was. Refused whole when any row differs from what the request left (undo the later save
    first); a row the request created is archived, a flag link set is replaced."""
    before, after = json.loads(event['old_value']), json.loads(event['new_value'])
    changed = 'Item changed · undo the later save first'
    pairs = [(old, new) for old, new in zip(before, after) if new['table'] != 'context']          # `context` says what a history row shows; it is no table
    for old, new in pairs:
        table = new['table']
        if table not in RECEIPT_TABLES:
            raise ValueError('Unsupported receipt')
        if table in LINK_TABLES:
            sample = (new['rows'] or old['rows'])[0] if new['rows'] or old['rows'] else None
            current = links(db, table, sample[LINK_TABLES[table]]) if sample else []
        else:
            current = snapshot(db, table, [r['id'] for r in new['rows']])
        if current != new['rows']:
            raise ValueError(changed)
        if table == 'wishlist' and not old['rows'] and db.execute('SELECT 1 FROM main.wish WHERE wishlist_id=? AND archived_at IS NULL', (new['rows'][0]['id'],)).fetchone():
            raise ValueError('Wishlist changed · undo its wishes first')
    restored_lists = {r['id'] for old, new in pairs if old['table'] == 'wishlist' for r in old['rows'] if r['archived_at'] is None}
    for old, new in pairs:
        if old['table'] == 'wish':
            for r in old['rows']:
                if r['archived_at'] is None and r['wishlist_id'] not in restored_lists and not db.execute(
                        'SELECT 1 FROM main.wishlist WHERE id=? AND archived_at IS NULL', (r['wishlist_id'],)).fetchone():
                    raise ValueError('Restore the destination wishlist before Undo')
    stamp = stamp_now()
    try:
        _put_back(db, pairs, stamp)
    except sqlite3.IntegrityError:                                      # a row that would now duplicate a live one (stock key, wish key)
        raise ValueError(changed) from None
    audit(db, 'collection', 'undo', None, dict(undoes=event['id']), via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


def _put_back(db, pairs, stamp):
    for old, new in reversed(pairs):
        table = old['table']
        if table in LINK_TABLES:
            sample = (new['rows'] or old['rows'])[0] if new['rows'] or old['rows'] else None
            if sample:
                column = LINK_TABLES[table]
                db.execute(f'DELETE FROM main.{table} WHERE {column}=?', (sample[column],))
                db.executemany(f'INSERT INTO main.{table}({column}, flag_id) VALUES(?, ?)', [(r[column], r['flag_id']) for r in old['rows']])
        elif not old['rows']:                                           # created by the request: archived, never deleted
            names = columns(db, table)
            if 'archived_at' not in names:
                raise ValueError('Unsupported created record')
            sets = 'archived_at=?' + (', updated_at=?' if 'updated_at' in names else '')
            db.executemany(f'UPDATE main.{table} SET {sets} WHERE id=?', [((stamp, stamp, r['id']) if 'updated_at' in names else (stamp, r['id'])) for r in new['rows']])
        else:
            names = [c for c in columns(db, table) if c != 'id']
            for r in old['rows']:
                if table == 'wish':
                    wish_collision(db, table, r)
                db.execute(f'UPDATE main.{table} SET ' + ','.join(f'{c}=?' for c in names) + ' WHERE id=?', (*[r[c] for c in names], r['id']))


for _field in ('save', 'archive', 'restore', 'photo', 'caption'):
    undoing.register('collection', _field, _undo_collection)


def undo(db, event_id, *, receipt=None):
    """Undo a collection receipt (or any event with a registered undoer) by its event id; a second Undo of the same event does nothing."""
    via, actor = origin()
    return undoing.undo_event(db, int(event_id), via=via, actor=actor)


# ---------- photos, lots, restore, wishes ----------

def _photo_id():
    """A photo id is a hex text that is never all digits, so `/manage/images/<id>` can tell it from a picture's number."""
    while True:
        identifier = uuid4().hex
        if not identifier.isdigit():
            return identifier


def photo(db, root, entity, identifier, content, caption):
    """Keep an own photo of a copy or loose stock row: the file under data/images/own, the row in `photo`. Undo archives the row; the
    file stays (it is the user's)."""
    from io import BytesIO
    from PIL import Image, UnidentifiedImageError
    if entity not in ('copy', 'stock'):
        raise ValueError('Choose an owned instance')
    if not content or len(content) > 15 * 1024 * 1024:
        raise ValueError('Choose a photo up to 15 MB')
    try:
        image = Image.open(BytesIO(content))
        image.verify()
        image = Image.open(BytesIO(content))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValueError('Choose a readable photo') from None
    if image.width * image.height > 30_000_000:                          # the header gives the size: refuse before decoding into memory
        raise ValueError('Choose a smaller photo')
    try:
        image.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError('Choose a readable photo') from None
    root = Path(root).resolve()
    photo_id = _photo_id()
    relative = 'data/images/own/' + photo_id + '.jpg'
    target = root / relative
    if not target.resolve().is_relative_to(root / 'data/images'):
        raise ValueError('Photo storage is unavailable')
    with transaction(db):
        row = snapshot(db, entity, [identifier])
        if not row or row[0]['archived_at']:
            raise ValueError('Instance is unavailable')
        owner = row[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.resolve().is_relative_to(root / 'data/images'):
            raise ValueError('Photo storage is unavailable')
        try:
            image.convert('RGB').save(target, 'JPEG', quality=90)
            on_rollback(db, lambda: target.unlink(missing_ok=True))
            db.execute('''INSERT INTO main.photo(id,item_id,color_id,copy_id,stock_id,local_path,width,height,caption,taken_at,created_at)
                          VALUES(?,?,?,?,?,?,?,?,?,NULL,?)''', (photo_id, owner['item_id'], owner.get('color_id'), identifier if entity == 'copy' else None,
                                                                 identifier if entity == 'stock' else None, relative, image.width, image.height, caption or None, stamp_now()))
            return receipt(db, [('photo', [], snapshot(db, 'photo', [photo_id]))], 'photo')
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def caption(db, identifier, value):
    with transaction(db):
        old = snapshot(db, 'photo', [identifier])
        if not old or old[0]['archived_at']:
            raise ValueError('Own photo is unavailable')
        db.execute('UPDATE main.photo SET caption=? WHERE id=?', (str(value).strip() or None, identifier))
        return receipt(db, [('photo', old, snapshot(db, 'photo', [identifier]))], 'caption')


def new_lot(db, ids, data):
    """Assign existing loose stock to a new lot, without changing its quantities; rows that then share a merge key merge."""
    if not isinstance(ids, list) or not ids or len(ids) > 2000 or len(set(ids)) != len(ids):
        raise ValueError('Select loose stock for this lot')
    name = str(data.get('name', '')).strip()
    if not name or len(name) > 200:
        raise ValueError('Name the lot')
    storage = data.get('storage_id') or None
    with transaction(db):
        old = snapshot(db, 'stock', ids)
        if len(old) != len(ids) or any(r['archived_at'] for r in old):
            raise ValueError('Stock is unavailable')
        _need_live(db, 'storage', storage, 'storage')
        identifier = uuid4().hex
        stamp = stamp_now()
        db.execute('INSERT INTO main.lot(id,name,note,storage_id,created_at,updated_at) VALUES(?,?,?,?,?,?)', (identifier, name, data.get('note') or None, storage, stamp, stamp))
        edits = {'lot_id': identifier}
        plan = stock.plan_edit(db, old, edits)
        everything = old + snapshot(db, 'stock', [t for _, t in plan if t is not None and t not in ids])
        stock.apply_edit(db, old, edits, plan, stamp=stamp)
        return receipt(db, [('lot', [], snapshot(db, 'lot', [identifier])), ('stock', everything, snapshot(db, 'stock', [r['id'] for r in everything]))], 'save')


def restore(db, table, identifier):
    """Restore an archived collection or location row under a receipt. A wish or stock row that would now duplicate a live one is refused."""
    if table not in RESTORABLE:
        raise ValueError('Unsupported record')
    with transaction(db):
        before = snapshot(db, table, [identifier])
        if not before:
            raise ValueError('Record is unavailable')
        row = before[0]
        if row['archived_at'] is None:
            raise ValueError('Record is already active')
        if table == 'wish':
            _need_live(db, 'wishlist', row['wishlist_id'], 'wishlist')
            wish_collision(db, table, dict(row, archived_at=None))
        if table == 'stock' and row['kind'] != 'minifigure' and stock_key_taken(db, row):
            raise errors.Conflict('Another live stock line has the same item, colour, condition, lot and storage · edit that line instead')
        names = columns(db, table)
        db.execute(f'UPDATE main.{table} SET archived_at=NULL' + (', updated_at=?' if 'updated_at' in names else '') + ' WHERE id=?',
                   ((stamp_now(), identifier) if 'updated_at' in names else (identifier,)))
        return receipt(db, [(table, before, snapshot(db, table, [identifier]))], 'restore')


def stock_key_taken(db, row):
    return db.execute('''SELECT 1 FROM main.stock WHERE archived_at IS NULL AND kind!='minifigure' AND id!=? AND item_id=? AND color_key=coalesce(?, 0)
                         AND condition_key=coalesce(?, '') AND lot_key=coalesce(?, '') AND storage_key=coalesce(?, '')''',
                      (row['id'], row['item_id'], row['color_id'], row['condition'], row['lot_id'], row['storage_id'])).fetchone() is not None


def want(db, item_id, colour=None):
    """Put an existing item (an unidentified figure, say) on the default wishlist under a receipt. A part needs its colour."""
    with transaction(db):
        item = db.execute('SELECT id,kind FROM main.item WHERE id=? AND merged_into IS NULL', (item_id,)).fetchone()
        if item is None:
            raise ValueError('Item is unavailable')
        if item['kind'] == 'part' and colour is None:
            raise ValueError('Choose a colour')
        if item['kind'] != 'part':
            colour = None
        row = dict(wishlist_id='default', item_id=item['id'], color_id=colour)
        if db.execute('SELECT 1 FROM main.wish WHERE archived_at IS NULL AND wishlist_id=? AND item_id=? AND color_id IS ?', tuple(row.values())).fetchone():
            raise errors.Conflict('Already on the wishlist')
        stamp = stamp_now()
        identifier = uuid4().hex
        db.execute('''INSERT INTO main.wish(id,wishlist_id,kind,item_id,color_id,quantity,condition,added_at,updated_at) VALUES(?,?,?,?,?,1,'any',?,?)''',
                   (identifier, 'default', item['kind'], item['id'], colour, stamp, stamp))
        return receipt(db, [('wish', [], snapshot(db, 'wish', [identifier]))], 'save')


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
