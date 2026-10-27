"""Add on the 4.0 store (M.8c, issue #110; design 4.3, 3.5, 6.3, 6.5, 5.2): search, review proposals, atomic receipts and their undo.

Every row speaks an item id. A person types or pastes a number (`items.find`: the Rebrickable number first, the BrickLink number as
well), the review resolves it to an item or, when nothing matches, to an *unknown number* row with two offers (design 6.5):
*Fetch from Rebrickable* (a set only; queues the store4 `rebrickable_set` job) and *Add as unidentified* (a local item of the chosen
kind named as typed, with the typed number as a `to_check` BrickLink link).

`confirm` writes inside the app's transaction, one transaction per review row: an owned set becomes `quantity` copies through
`store4.copies.create_copy_in` with design 4.3's preselection (the set's `set_preference`, then the global switch with a key, then the
latest Rebrickable version; BrickLink without a fetched list is decision F's pending copy); every other owned or loose kind becomes
stock (`core.stock`); a wish becomes a `wish` row. The materialisation happens in the same transaction, so there is no later step.
Each row ends with one pipeline job (`core.pipeline`) and ONE receipt event `add:receipt` (entity id = the batch) which `undo`
reverses by its registered undoer (`core.undo`): it archives what the row created and refuses when the rows changed since.

A choice of part list (design 4.3's picker) has no screen yet (M.10): the preselection decides. Photo mode (M.8h) recognises a photo through
`core/identify.py`, offers its candidates, and keeps the photo as the new item's own photo only when asked."""
import csv
import io
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

from ..store4 import copies, fetched, identity, jobs, part_list_read, pending
from ..store4.audit import Events
from ..store4.connect import has_catalogue, now
from ..store4.errors import AmbiguousIdentity, Store4Error
from . import errors, items, pictures, size_search, stock
from . import undo as undoing
from .admin import audit, origin
from .pipeline import Pipeline
from .transaction import transaction

KIND_NAMES = {'set': 'Set', 'minifigure': 'Minifigure', 'part': 'Part', 'instructions': 'Instruction', 'box': 'Box', 'gear': 'Gear',
              'book': 'Book', 'catalog': 'Catalog'}
KINDS = tuple(KIND_NAMES)
WHERE = ('owned', 'loose', 'wishlist')
CONDITIONS = {'owned': ('new', 'used'), 'loose': ('new', 'used', 'damaged'), 'wishlist': ('new', 'used', 'any')}
COMPLETENESS = ('', 'sealed', 'complete', 'incomplete')
NUMBER = re.compile(r'[A-Za-z0-9.-]{1,32}')
LIMIT = 100
CAP = 5000                                      # hits ordered for a name search; the count stays exact beyond it
FIX = 'python -m brickwork.store4 catalogue reconcile'
UNKNOWN_DECISIONS = ('unidentified', 'fetch', 'skip')
ASK_KEYS = ('number', 'where', 'quantity', 'condition', 'completeness', 'note', 'list_id', 'max_price', 'max_price_currency', 'qty_filled')


# ---------- the catalogue ----------

def require_catalogue(db):
    """Add needs an activated catalogue build (design 6.1 step 3). Without one it says what to run; it never fails with a 500."""
    if not has_catalogue(db):
        raise errors.CatalogueNotLoaded('There is no catalogue.db beside the collection. Get one with `python -m brickwork.store4 --data <the folder of '
                                        f'brickwork.db> catalogue download` (or `catalogue import`), then run `{FIX}`; first-run onboarding comes with a later release.')
    if not db.execute('SELECT 1 FROM main.catalogue_build LIMIT 1').fetchone():
        raise errors.CatalogueNotLoaded(f'No catalogue is active in this collection yet. Run `{FIX}` to activate the one beside it '
                                        '(first-run onboarding comes with a later release), then search again.')


def _escape(text):
    return text.strip().lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _item_rows(db, ids):
    """`{id: {item_id, kind, name, number}}` for live items of either file: the collection's row wins; a catalogue-retired item is
    left out unless the collection holds it."""
    packed, rows = json.dumps(sorted(ids)), {}
    for store in ('main', 'catalogue') if has_catalogue(db) else ('main',):
        columns, live = ('merged_into', '') if store == 'main' else ('NULL AS merged_into', ' AND retired_at IS NULL')
        for r in db.execute(f'SELECT id, kind, name, born_key, {columns} FROM {store}.item WHERE id IN (SELECT value FROM json_each(?)){live}', (packed,)):
            if r['id'] not in rows and not (store == 'main' and r['merged_into'] is not None):
                rows[r['id']] = dict(item_id=r['id'], kind=r['kind'], name=r['name'], number=r['born_key'])
    return rows


def search(db, kind, query='', sort='number'):
    """Items of one kind by number or name: `{items: [...first 100, decorated], count}`.

    A number matches the Rebrickable number and the BrickLink one (`items.find`: born key, the catalogue's search index over every
    linked number, confirmed BrickLink links); words match names by prefix (`catalogue.item_fts`); a size ("2x4", "x2") filters by
    the size key of part names (#41); local items (BrickLink-only or unidentified) are searched by name and number."""
    if kind not in KIND_NAMES or sort not in ('number', 'name'):
        raise errors.ValidationFailed('Choose an item type and sort')
    require_catalogue(db)
    query = (query or '').strip()
    full, partial, rest = size_search.parse(query)
    exact, found, total = [], [], 0
    if full or partial:
        sql, args = 'kind=? AND retired_at IS NULL', [kind]
        if full:
            sql += ' AND size_key=?'
            args.append(full)
        else:
            sql += " AND ('x'||size_key||'x') LIKE ?"
            args.append(f'%x{partial}x%')
        for word in rest.split():
            sql += " AND name_key LIKE ? ESCAPE '\\'"
            args.append('%' + _escape(word) + '%')
        count = db.execute(f'SELECT count(*) FROM catalogue.item WHERE {sql}', args).fetchone()[0]
        order = 'name_key, id' if sort == 'name' else 'born_key, id'
        found = [r[0] for r in db.execute(f'SELECT id FROM catalogue.item WHERE {sql} ORDER BY {order} LIMIT ?', (*args, LIMIT))]
        rows = _item_rows(db, found)
        return {'items': decorate_rows(db, [rows[i] for i in found if i in rows]), 'count': count}
    elif query:
        exact = [hit['item_id'] for hit in items.find(db, kind, query, limit=LIMIT)]
        tokens = re.findall(r'[^\W_]+', query.lower())
        if tokens:
            match = ' '.join(f'"{t}"*' for t in tokens)
            found = [r[0] for r in db.execute('SELECT item_id FROM catalogue.item_fts WHERE item_fts MATCH ? AND kind=? ORDER BY rank LIMIT ?',
                                              (match, kind, CAP))]
            if len(found) == CAP:                                              # more hits than are ordered: the count is still exact
                total = db.execute('SELECT count(*) FROM catalogue.item_fts WHERE item_fts MATCH ? AND kind=?', (match, kind)).fetchone()[0]
            clause = ' AND '.join("(lower(name) LIKE ? ESCAPE '\\' OR lower(coalesce(born_key, '')) LIKE ? ESCAPE '\\')" for _ in tokens)
            args = [x for t in tokens for x in ('%' + _escape(t) + '%',) * 2]
            found += [r[0] for r in db.execute(f"SELECT id FROM main.item WHERE origin='local' AND kind=? AND merged_into IS NULL AND {clause} LIMIT ?",
                                               (kind, *args, CAP))]
    else:
        count = db.execute('SELECT count(*) FROM catalogue.item WHERE kind=? AND retired_at IS NULL', (kind,)).fetchone()[0]
        order = 'name_key, id' if sort == 'name' else 'born_key, id'
        found = [r[0] for r in db.execute(f'SELECT id FROM catalogue.item WHERE kind=? AND retired_at IS NULL ORDER BY {order} LIMIT ?', (kind, LIMIT))]
        rows = _item_rows(db, found)
        return {'items': decorate_rows(db, [rows[i] for i in found if i in rows]), 'count': count}
    ids = list(dict.fromkeys(exact + found))
    rows = _item_rows(db, ids)
    ids = [i for i in ids if i in rows]
    first = [i for i in exact if i in rows]
    rest_ids = sorted((i for i in dict.fromkeys(ids) if i not in set(first)),
                      key=(lambda i: (rows[i]['name'].lower(), i)) if sort == 'name' else (lambda i: (rows[i]['number'] or '', i)))
    ordered = list(dict.fromkeys(first)) + rest_ids
    return {'items': decorate_rows(db, [rows[i] for i in ordered[:LIMIT]]), 'count': max(len(ordered), total)}


def lookup(db, item_id):
    """The identity of an item id (a merged item as the item it was merged into), else None when neither file knows it."""
    try:
        live = items._merged_target(db, int(item_id))
        label = items.label(db, live)
    except (errors.NotFound, TypeError, ValueError):
        return None
    return dict(item_id=live, kind=label.kind, name=label.name, number=label.number, label=label.text)


def colors(db):
    """Every colour of the collection (the catalogue's are projected at activation), by name."""
    return [dict(r) for r in db.execute('SELECT id AS color_id, name, rgb FROM main.color ORDER BY name, id')]


def _colour_known(db, color_id):
    if db.execute('SELECT 1 FROM main.color WHERE id=?', (color_id,)).fetchone():
        return True
    return has_catalogue(db) and db.execute('SELECT 1 FROM catalogue.color WHERE id=?', (color_id,)).fetchone() is not None


def wishlists(db):
    return [dict(r) for r in db.execute('SELECT id, name, bricklink_id FROM main.wishlist WHERE archived_at IS NULL ORDER BY sort, name, id')]


def _require_wishlist(db, identifier):
    if not db.execute('SELECT 1 FROM main.wishlist WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone():
        raise ValueError('Choose an existing wishlist')


# ---------- decorating rows ----------

def picture_order(db, kind):
    """The picture source order for a kind: the setting `source_priority.pictures` (design 6.8), else the default (`core.pictures.order`)."""
    return pictures.order(db, kind)


def decorate_rows(db, rows):
    """Rows with an `item_id` (and optionally `color_id`, `list_id`) gain the numbers to show (`label`, `number`, `also`), the best
    picture, what is owned and wished already and whether a link waits to be checked. A handful of queries for any number of rows."""
    rows = [dict(r) for r in rows]
    ids = sorted({r['item_id'] for r in rows if r.get('item_id') is not None})
    if not ids:
        return rows
    packed = json.dumps(ids)
    labels = items.labels(db, {(r['item_id'], r.get('color_id')) for r in rows if r.get('item_id') is not None})
    ranks = {}
    pictures = {}
    for r in db.execute('SELECT id, item_id, color_id, source FROM main.picture WHERE item_id IN (SELECT value FROM json_each(?)) '
                        'ORDER BY fetched_at DESC, id DESC', (packed,)):
        pictures.setdefault(r['item_id'], []).append(r)
    copies_of = dict(db.execute('SELECT item_id, count(*) FROM main.copy WHERE archived_at IS NULL AND item_id IN (SELECT value FROM json_each(?)) '
                                'GROUP BY item_id', (packed,)).fetchall())
    stock_of = {}
    for r in db.execute('SELECT item_id, color_id, sum(quantity) FROM main.stock WHERE archived_at IS NULL AND item_id IN '
                        '(SELECT value FROM json_each(?)) GROUP BY item_id, color_id', (packed,)):
        stock_of.setdefault(r[0], {})[r[1]] = r[2]
    wished = {}
    for r in db.execute('SELECT wishlist_id, item_id, color_id FROM main.wish WHERE archived_at IS NULL AND item_id IN (SELECT value FROM json_each(?))', (packed,)):
        wished.setdefault(r['item_id'], []).append((r['wishlist_id'], r['color_id']))
    to_check = {r[0] for r in db.execute("SELECT DISTINCT item_id FROM main.item_link WHERE status='to_check' AND item_id IN "
                                         '(SELECT value FROM json_each(?))', (packed,))}
    for row in rows:
        item_id = row.get('item_id')
        if item_id is None:
            continue
        label = labels.get((item_id, row.get('color_id')))
        if label is not None:
            row.update(kind=label.kind, name=label.name, number=label.number, label=label.text, also=label.also, source=label.source,
                       unidentified=label.unidentified)
        kind = row['kind']
        if kind not in ranks:
            ranks[kind] = picture_order(db, kind)
        order = ranks[kind]
        usable = [p for p in pictures.get(item_id, []) if p['color_id'] in (None, row.get('color_id'))]
        usable.sort(key=lambda p: order.index(p['source']) if p['source'] in order else len(order))
        row['image'] = usable[0]['id'] if usable else None
        row['type_name'] = KIND_NAMES[kind]
        color = row.get('color_id')
        row['owned'] = copies_of.get(item_id, 0) + sum(q for c, q in stock_of.get(item_id, {}).items() if color is None or c == color)
        row['wished_by_list'] = {}
        for list_id, wish_color in wished.get(item_id, []):
            row['wished_by_list'].setdefault(list_id, []).append(wish_color)
        row['wished_colors'] = [c for lid, c in wished.get(item_id, []) if row.get('list_id') is None or lid == row['list_id']]
        row['wished'] = color in row['wished_colors']
        row['to_check'] = item_id in to_check
    return rows


def decorate(db, row):
    return decorate_rows(db, [row])[0]


# ---------- reading input ----------

def quantity(value):
    if not re.fullmatch('[0-9]{1,5}', str(value)) or not 1 <= int(value) <= 9999:
        raise ValueError('Quantity must be between 1 and 9999')
    return int(value)


def paste(text, kind):
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*([A-Za-z0-9.-]{1,32})(?:\s+[x×]\s*([0-9]+))?\s*', line)
        result.append(dict(kind=kind, number=match[1], quantity=quantity(match[2] or 1))
                      if match else dict(unresolved=line, reason='Use a number and optional quantity'))
    return result


BL_CONDITION = {'N': 'new', 'U': 'used', 'X': 'any'}


def file_rows(data, filename, kind):
    """Rows of a BrickLink wanted list or inventory (XML: BrickLink numbers and colour numbers) or a Rebrickable CSV (Rebrickable
    numbers and colour ids). Nothing is looked up here."""
    text = data.decode('utf-8-sig')
    if filename.lower().endswith('.xml'):
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ValueError('Choose XML without document declarations')
        root = ET.fromstring(text)
        if root.tag not in ('INVENTORY', 'WANTEDLIST'):
            raise ValueError('Choose a BrickLink wanted list or inventory')
        result = []
        for entry in root.findall('ITEM'):
            letter = entry.findtext('ITEMTYPE') or ''
            try:
                row_kind = items.kind_of_type(letter)
            except errors.ValidationFailed:
                result.append(dict(unresolved=entry.findtext('ITEMID') or letter, reason='Not a BrickLink item type'))
                continue
            result.append(dict(kind=row_kind, number=entry.findtext('ITEMID') or '', quantity=quantity(entry.findtext('MINQTY') or entry.findtext('QTY') or '1'),
                bl_color=entry.findtext('COLOR') or None, condition=BL_CONDITION.get(entry.findtext('CONDITION') or 'X', 'any'),
                note=entry.findtext('REMARKS'), max_price=entry.findtext('MAXPRICE'), bricklink_list_id=entry.findtext('WANTEDLISTID'),
                qtyfilled=entry.findtext('QTYFILLED')))
        return result
    if not filename.lower().endswith('.csv'):
        raise ValueError('Choose BrickLink XML or Rebrickable CSV')
    result = []
    for entry in csv.DictReader(io.StringIO(text)):
        entry = {k.strip().lower().replace(' ', '_'): v for k, v in entry.items() if k}
        number = entry.get('part_num') or entry.get('part') or entry.get('set_num') or entry.get('set_number') or entry.get('minifig_num')
        if not number:
            raise ValueError('CSV needs part_num, set_num or minifig_num')
        rb_kind = 'part' if entry.get('part_num') or entry.get('part') else 'minifigure' if entry.get('minifig_num') else 'set'
        result.append(dict(kind=rb_kind, number=number, quantity=quantity(entry.get('quantity') or '1'),
                           rb_color=entry.get('color_id') or entry.get('color') or None))
    return result


# ---------- resolving rows to items ----------

def _bricklink_colour(db, key):
    try:
        colour = identity._inverse_color(db, 'bricklink', str(key))
    except AmbiguousIdentity:
        colour = None
    if colour is None:
        raise ValueError('Colour needs manual matching')
    return colour


def _rebrickable_colour(db, key):
    for store in ('main', 'catalogue') if has_catalogue(db) else ('main',):
        row = db.execute(f"SELECT id FROM {store}.color WHERE born_provider='rebrickable' AND born_key=?", (str(key),)).fetchone()
        if row:
            return row[0]
    raise ValueError('Colour needs manual matching')


def _pick(db, kind, number):
    """The one item a typed number means: the born match, else the only match; None when nothing matches. Several matches without a
    born one are ambiguous and refused (never guess)."""
    hits = items.find(db, kind, number, limit=20)
    born = [h for h in hits if h['matched_by'] == 'born']
    if born:
        return born[0]['item_id']
    if len(hits) > 1:
        raise ValueError(f'{number} matches {len(hits)} items · search by name to choose one')
    return hits[0]['item_id'] if hits else None


def _identify(db, row):
    """`(item id or None, colour id or None)` of an input row. None for the item: the number is unknown to the catalogue."""
    colour = row.get('color_id')
    if row.get('item_id') is not None:
        found = lookup(db, row['item_id'])
        if found is None:
            raise ValueError('Choose items from the catalogue')
        item_id = found['item_id']
    else:
        kind, number = row.get('kind'), str(row.get('number') or '')
        if kind not in KIND_NAMES or not NUMBER.fullmatch(number):
            raise ValueError('Use a number and optional quantity')
        item_id = None
        if kind == 'part' and row.get('bl_color') is not None:
            try:
                found = identity.resolve_inverse(db, 'P', number, str(row['bl_color']), exhaustive=True)
            except AmbiguousIdentity:
                raise ValueError('Colour needs manual matching') from None
            if found:
                item_id, colour = found
        if item_id is None:
            item_id = _pick(db, kind, number)
        if colour is None:                                              # a known colour stays known for an unknown item too
            if row.get('bl_color') is not None:
                colour = _bricklink_colour(db, row['bl_color'])
            elif row.get('rb_color') is not None:
                colour = _rebrickable_colour(db, row['rb_color'])
    if colour not in (None, '') and not _colour_known(db, int(colour)):
        raise ValueError('Colour needs manual matching')
    return item_id, (int(colour) if colour not in (None, '') else None)


def offers(db, kind, number):
    """What a row for an unknown number offers (design 6.5): add it as unidentified (always), fetch a set from Rebrickable (a set, with
    a key). `help` says what would help when there is no way to get the real item."""
    out = {'unidentified': True, 'fetch': None}
    if kind == 'set' and jobs.NUMBER.fullmatch(number):
        keyed = jobs._configured('rebrickable')
        out['fetch'] = {'available': keyed, 'why': None if keyed else 'Add a Rebrickable key in Tools & Admin first'}
    if kind == 'set' and out['fetch'] is None:                      # a number Rebrickable cannot have (dotted, etc.): unidentified only
        out['help'] = 'Not in the catalogue · add it as unidentified'
    elif kind == 'set' and not out['fetch']['available']:
        out['help'] = "Not in the catalogue · download today's catalogue, or add a Rebrickable key to fetch it"
    elif kind == 'set':
        out['help'] = 'Not in the catalogue · fetch it from Rebrickable (3 calls and one per figure), or add it as unidentified'
    else:
        out['help'] = 'Not in the catalogue · add it as unidentified'
    return out


def resolve(db, rows, where, *, list_id='default', map_wanted_ids=True):
    """Review proposal for input rows: `{items, unresolved}`. Writes nothing."""
    if where not in WHERE:
        raise ValueError('Choose where to add')
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('Review up to 500 items at a time')
    require_catalogue(db)
    from .currency import configured_currency
    from ..web.formatting import money
    currency = configured_currency(db)
    lists = wishlists(db)
    linked = {l['bricklink_id']: l for l in lists if l['bricklink_id']}
    if where == 'wishlist':
        _require_wishlist(db, list_id)
    resolved, unresolved = [], []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Choose items from the catalogue')
        original = dict(row)
        try:
            if row.get('unresolved'):
                raise ValueError(row['reason'])
            item_id, color = _identify(db, row)
            target = list_id
            wanted_id = row.get('bricklink_list_id') if map_wanted_ids and where == 'wishlist' else None
            if wanted_id:
                if not wanted_id.isdecimal():
                    raise ValueError('BrickLink wanted list id must be numeric')
                target = linked[wanted_id]['id'] if wanted_id in linked else 'new-bl:' + wanted_id
            list_name = next((l['name'] for l in lists if l['id'] == target), 'BrickLink ' + (wanted_id or ''))
            maximum = row.get('max_price')
            if maximum is not None:
                try:
                    amount = Decimal(maximum)
                except InvalidOperation:
                    raise ValueError('Invalid MAXPRICE') from None
                if not amount.is_finite():
                    raise ValueError('Invalid MAXPRICE')
                maximum = format(amount, 'f') if amount >= 0 else None      # BrickLink exports use a negative sentinel for no limit
            condition = row.get('condition') or 'used'
            if condition == 'any' and where != 'wishlist':
                condition = 'used'
            filled = row.get('qtyfilled')
            filled = int(filled) if where == 'wishlist' and isinstance(filled, str) and filled.strip().isdigit() and int(filled) > 0 else None
            base = {'quantity': quantity(row.get('quantity', 1)), 'list_id': target, 'list_name': list_name, 'bricklink_list_id': wanted_id,
                    'qty_filled': filled, 'max_price': maximum, 'max_price_currency': currency if maximum is not None else None,
                    'import_notes': ([f"Max price {money(maximum, currency, fixed=True)} · BrickLink currency setting: {currency}"] if maximum is not None else []) +
                                    ([f'Filled so far {filled} (BrickLink QTYFILLED)'] if filled is not None else []) +
                                    (['Create ' + list_name + ' on confirm'] if target.startswith('new-bl:') else []),
                    'where': where, 'color_id': color, 'note': row.get('note'), 'condition': condition, 'completeness': '', 'decision': ''}
            if item_id is None:
                kind, number = row['kind'], str(row['number'])
                resolved.append({**base, 'item_id': None, 'unknown': True, 'kind': kind, 'type_name': KIND_NAMES[kind], 'number': number,
                                 'name': number, 'label': number, 'offers': offers(db, kind, number), 'owned': 0, 'wished': False,
                                 'wished_colors': [], 'wished_by_list': {}, 'to_check': False, 'image': None})
            else:
                resolved.append(decorate(db, {**base, 'item_id': item_id}))
                resolved[-1]['import_notes'] += _list_note(db, resolved[-1], where)
                resolved[-1]['part_list'] = part_list_options(db, item_id) if resolved[-1]['kind'] == 'set' else None
                resolved[-1]['no_picture'] = picture_warning(db, resolved[-1])
        except (ValueError, Store4Error, TypeError, KeyError) as error:
            unresolved.append({'number': original.get('unresolved') or original.get('number') or original.get('item_id'), 'reason': str(error)})
    return dict(items=resolved, unresolved=unresolved)


def part_list_options(db, set_item_id):
    """The Add review's *Part list* picker for a set (design 4.3): None unless there is a choice, else `{'options': [{'key', 'label',
    'note'}], 'preselected': key}` in the order of the design's preselection (`copies.part_list_choices`)."""
    picked = copies.part_list_choices(db, set_item_id)
    if not picked['needs_choice']:
        return None
    options = [dict(key=part_list_read.choice_key({'source': 'rebrickable', 'version': v['version']}), label=v['label'], note=None) for v in picked['rebrickable']]
    if picked['rebrickable_api']:
        options.append(dict(key='rebrickable_api', label='Fetched from Rebrickable', note=None))
    if picked['bricklink']:
        fetched_already = picked['bricklink']['fetched_inventory_id'] is not None
        options.append(dict(key='bricklink', label="BrickLink's list",
                            note=None if fetched_already else "Fetched after you add · the copy uses Rebrickable's list meanwhile"))
    chosen = part_list_read.choice_key(picked['preselected'])
    pref = copies.part_list_preference(db, set_item_id)
    if pref and (chosen == 'bricklink' if pref['source'] == 'bricklink' else chosen.startswith('rebrickable:')):
        why = 'your saved choice for this set'
    elif picked['preselected'] and picked['preselected']['source'] == 'bricklink':
        why = 'the BrickLink preference in Settings'
    else:
        why = 'the latest Rebrickable list'
    return dict(options=options, preselected=chosen, why=why)


def picture_warning(db, row):
    """True when no picture is known for a part row in its colour (design 6.8): the review warns before confirming."""
    if row.get('kind') != 'part' or row.get('color_id') in (None, '') or row.get('item_id') is None:
        return False
    try:
        return not pictures.picture_known(db, row['item_id'], int(row['color_id']))
    except (errors.NotFound, Store4Error, ValueError):
        return False


def _list_note(db, row, where):
    """The part list an owned set will get (design 4.3), as a line for the review; empty when there is nothing to say."""
    if where != 'owned' or row['kind'] != 'set':
        return []
    choices = copies.part_list_choices(db, row['item_id'])
    choice = choices['preselected']
    if choice is None:
        return ['No part list is known for this set · the copy has none']
    if choice['source'] == 'bricklink':
        fetched = choices['bricklink'] and choices['bricklink']['fetched_inventory_id'] is not None
        return ["Part list: BrickLink's" + ('' if fetched else " · fetched after you add; the copy uses Rebrickable's meanwhile")]
    if choice['source'] == 'rebrickable_api':
        return ['Part list: fetched from Rebrickable']
    version = next((v for v in choices['rebrickable'] if v['version'] == choice['version']), None)
    return ['Part list: Rebrickable ' + (version['label'].lower() if version else 'version %s' % choice['version'])]


def validate_edits(db, proposal, edits, *, batch=None):
    """The review rows as the person edited them, validated against the proposal (identity never comes from the edit)."""
    if not isinstance(edits, list) or len(edits) != len(proposal):
        raise ValueError('Review the items before adding')
    result, wishes, owned = [], set(), set()
    saved = {r['index'] for r in receipts(db, batch)} if batch else set()
    for index, (original, edit) in enumerate(zip(proposal, edits)):
        if not isinstance(edit, dict):
            raise ValueError('Review the items before adding')
        if index in saved:
            result.append(original)
            continue
        row = {**original, **{k: edit.get(k, original.get(k)) for k in
                              ('quantity', 'where', 'color_id', 'condition', 'completeness', 'decision', 'note', 'list_id', 'storage_id', 'lot_id', 'part_list_choice', 'use_for_new')}}
        row['quantity'] = quantity(row['quantity'])
        row['completeness'] = row['completeness'] or ''
        if row['where'] not in WHERE or row['condition'] not in CONDITIONS[row['where']] or row['completeness'] not in COMPLETENESS:
            raise ValueError('Choose a destination, condition and completeness')
        unknown = bool(row.get('unknown'))
        if unknown and row['decision'] not in UNKNOWN_DECISIONS:
            raise ValueError(f'{row["number"]} is not in the catalogue · choose to add it as unidentified, fetch it or skip it')
        row['color_id'] = None if row['color_id'] in ('', None) else int(row['color_id'])
        if row['kind'] == 'part':
            if row['color_id'] is None or not _colour_known(db, row['color_id']):
                raise ValueError('Choose a colour for each part')
        else:
            row['color_id'] = None
        picker = original.get('part_list')
        if row['kind'] == 'set' and picker:
            row['part_list_choice'] = row.get('part_list_choice') or picker['preselected']
            if row['part_list_choice'] not in [o['key'] for o in picker['options']]:
                raise ValueError('Choose a part list from the list')
            row['use_for_new'] = row.get('use_for_new') is True and row['part_list_choice'] != picker['preselected']
        else:
            row['part_list_choice'], row['use_for_new'] = None, False
        for key, table in (('storage_id', 'storage'), ('lot_id', 'lot')):
            if row.get(key) is not None and not db.execute(f'SELECT 1 FROM main.{table} WHERE id=? AND archived_at IS NULL', (row[key],)).fetchone():
                raise ValueError('Choose an active ' + key.replace('_id', ''))
        if row['where'] == 'wishlist':
            row['list_id'] = row.get('list_id') or 'default'
            if not str(row['list_id']).startswith('new-bl:'):
                _require_wishlist(db, row['list_id'])
            elif row['list_id'] != original.get('list_id'):
                raise ValueError('Choose an existing wishlist')
        if unknown:
            if row['decision'] == 'fetch' and not (row['offers']['fetch'] or {}).get('available'):
                raise ValueError((row['offers']['fetch'] or {}).get('why') or f'{row["number"]} cannot be fetched from Rebrickable')
            result.append(row)
            continue
        key = row['item_id'], row['color_id'], row.get('list_id') if row['where'] == 'wishlist' else None
        current = decorate(db, row)
        duplicate = current['owned'] or current['wished'] or key in wishes or key in owned
        if duplicate and row['decision'] not in ('another', 'skip'):
            raise ValueError('Already owned or wished · choose add to the wished quantity or skip' if row['where'] == 'wishlist'
                             else 'Already owned or wished · choose add another copy or skip')
        if row['decision'] != 'skip':
            (wishes if row['where'] == 'wishlist' else owned).add(key)
        result.append(row)
    return result


# ---------- receipts ----------

def _receipt_events(db, batch):
    return db.execute("SELECT id, new_value FROM main.event WHERE entity_kind='add' AND field='receipt' AND entity_id=? ORDER BY id", (batch,)).fetchall()


def receipts(db, batch):
    """The saved receipts of a batch, in review order, each with the `event_id` that undoes it."""
    return sorted(({**json.loads(r['new_value']), 'event_id': r['id']} for r in _receipt_events(db, batch)), key=lambda r: r['index'])


def _event(db, entity, field, old, new, via, actor):
    audit(db, entity, field, old, new, via=via, actor=actor)
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def _unidentified_item(db, kind, number, via, actor):
    """A local item of `kind` named as typed (design 6.5); the typed number is a `to_check` BrickLink link. The same typed number gives
    the same item again."""
    letter = items.type_of_kind(kind)
    found = db.execute("""SELECT i.id FROM main.item i JOIN main.item_link l ON l.item_id=i.id
                          WHERE i.origin='local' AND i.born_key IS NULL AND i.merged_into IS NULL AND i.kind=? AND l.provider='bricklink'
                          AND l.provider_kind=? AND l.provider_key=? AND l.status='to_check' ORDER BY i.id""", (kind, letter, number)).fetchone()
    if found:
        return found[0]
    events = Events(db, via, actor)
    new = fetched.create_local_item(db, kind=kind, born_provider=None, born_namespace=None, born_key=None, name=number, kind_source='manual', events=events)
    fetched.add_item_link(db, new, provider='bricklink', provider_kind=letter, provider_key=number, status='to_check', method='typed',
                          origin='user', events=events)
    return new


def _add_copy(db, row, via, actor):
    """One copy of a set with design 4.3's preselection; a set with no part list at all gets a copy with `inventory_source='none'`."""
    choice = copies.part_list_choices(db, row['item_id'])['preselected']
    if row.get('part_list_choice'):                                 # the review's picker (design 4.3); absent: the preselection
        choice = part_list_read.parse_choice(row['part_list_choice'])
    condition, completeness = row['condition'], row['completeness'] or None
    if choice is not None:
        receipt = copies.create_copy_in(db, row['item_id'], choice, via=via, actor=actor, condition=condition, completeness=completeness, note=row.get('note'))
        return receipt['copy']['id'], receipt.get('pending')
    copy_id, stamp = str(uuid.uuid4()), now()
    db.execute("""INSERT INTO main.copy(id, item_id, inventory_source, condition, completeness, completeness_source, note, created_at, updated_at)
                  VALUES(?, ?, 'none', ?, ?, ?, ?, ?, ?)""", (copy_id, row['item_id'], condition, completeness, 'manual' if completeness else None,
                                                             row.get('note'), stamp, stamp))
    Events(db, via, actor).write('copy', copy_id, 'add', new={'copy': {'id': copy_id, 'item_id': row['item_id'], 'inventory_source': 'none',
                                                                         'condition': condition, 'completeness': completeness, 'note': row.get('note')},
                                                              'figures': [], 'parts': {'columns': copies.PART_COLUMNS, 'rows': []}})
    return copy_id, None


def _add_wish(db, row, receipt, via, actor):
    target = row.get('list_id') or 'default'
    if target.startswith('new-bl:'):
        wanted = target.split(':', 1)[1]
        found = db.execute('SELECT id FROM main.wishlist WHERE bricklink_id=? AND archived_at IS NULL', (wanted,)).fetchone()
        if found:
            target = found[0]
        else:
            target, stamp = uuid.uuid4().hex, now()
            db.execute('INSERT INTO main.wishlist(id, name, bricklink_id, created_at) VALUES(?, ?, ?, ?)', (target, 'BrickLink ' + wanted, wanted, stamp))
            audit(db, 'wishlist:' + target, 'created', None, dict(db.execute('SELECT * FROM main.wishlist WHERE id=?', (target,)).fetchone()), via=via, actor=actor)
            receipt['created_wishlist'] = target
    _require_wishlist(db, target)
    old = db.execute('SELECT * FROM main.wish WHERE wishlist_id=? AND item_id=? AND color_key=coalesce(?, 0) AND archived_at IS NULL',
                     (target, row['item_id'], row['color_id'])).fetchone()
    if old and row['decision'] != 'another':
        raise ValueError('Already on Wishlist · choose add to the wished quantity or skip')
    stamp = now()
    if old:
        before = dict(old)
        db.execute('''UPDATE main.wish SET quantity=?, condition=?, updated_at=?, note=?, max_price=?, max_price_currency=?,
                      qty_filled_manual=coalesce(?, qty_filled_manual) WHERE id=?''',
                   (old['quantity'] + row['quantity'], row['condition'], stamp, row.get('note') if row.get('note') is not None else old['note'],
                    row.get('max_price') if row.get('max_price') is not None else old['max_price'],
                    row.get('max_price_currency') if row.get('max_price') is not None else old['max_price_currency'], row.get('qty_filled'), old['id']))
        wish_id = old['id']
    else:
        before, wish_id = None, uuid.uuid4().hex
        db.execute('''INSERT INTO main.wish(id, wishlist_id, kind, item_id, color_id, quantity, condition, max_price, max_price_currency,
                      qty_filled_manual, note, added_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (wish_id, target, row['kind'], row['item_id'], row['color_id'], row['quantity'], row['condition'], row.get('max_price'),
                    row.get('max_price_currency') if row.get('max_price') is not None else None, row.get('qty_filled'), row.get('note'), stamp, stamp))
    after = dict(db.execute('SELECT * FROM main.wish WHERE id=?', (wish_id,)).fetchone())
    audit(db, 'wish:' + wish_id, 'added', before, after, via=via, actor=actor)
    receipt['wish'] = dict(id=wish_id, created=before is None, before=before, after=after)


def confirm(db, rows, *, batch, via=None, actor=None, photo=None, keep_photo=False):
    """Write the reviewed rows, one transaction each, and return their receipts (a row already saved under this batch returns its
    saved receipt, so a lost response never doubles a row). A row that fails stops the batch; rows before it stay saved.
    `photo` is the picture a photo-mode Add recognised; it is kept as the new item's own photo only with `keep_photo`."""
    if via is None:
        via, actor = origin()
    require_catalogue(db)
    pipeline, result = Pipeline(db), []
    for index, row in enumerate(rows):
        if row['decision'] == 'skip':
            continue
        with transaction(db):
            saved = next((r for r in receipts(db, batch) if r['index'] == index), None)
            if saved:
                result.append(saved)
                continue
            try:
                result.append(_confirm_row(db, pipeline, row, batch, index, via, actor, photo if keep_photo else None))
            except Store4Error as error:
                raise errors.ValidationFailed(str(error)) from None
    return result


def _confirm_row(db, pipeline, row, batch, index, via, actor, photo=None):
    receipt = dict(batch=batch, index=index, item_id=row.get('item_id'), kind=row['kind'], where=row['where'], quantity=row['quantity'],
                   copies=[], guards={}, stock=None, wish=None, created_wishlist=None, created_item=None, fetch_job=None, job_id=None, pending=[], photos=[])
    if row.get('unknown'):
        if row['decision'] == 'fetch':
            job, created = jobs.queue_in(db, 'rebrickable_set', payload=row['number'], via=via, actor=actor)
            receipt.update(fetch_job=job, name=row['number'], label=row['number'], job_reused=not created,
                           ask={k: row.get(k) for k in ASK_KEYS})            # what to create when the job is done (`settle_fetches`)
            return _save_receipt(db, receipt, via, actor)
        row = {**row, 'item_id': _unidentified_item(db, row['kind'], row['number'], via, actor)}
        receipt.update(item_id=row['item_id'], created_item=row['item_id'])
    items.ensure(db, row['item_id'])
    live = decorate(db, row)
    if not receipt['created_item'] and row['decision'] != 'another' and (live['owned'] or live['wished']):
        raise ValueError('Already on Wishlist · choose add to the wished quantity or skip' if row['where'] == 'wishlist' and live['wished']
                         else 'Already owned · review again')
    receipt.update(name=live['name'], label=live['label'])
    if row['where'] == 'wishlist':
        _add_wish(db, {**row, 'kind': live['kind']}, receipt, via, actor)
    elif live['kind'] == 'set':
        if row.get('use_for_new') and row.get('part_list_choice') not in (None, 'rebrickable_api'):        # "use this for new copies of this set"
            picked = part_list_read.parse_choice(row['part_list_choice'])
            newest = any(v['is_latest'] and v['version'] == picked.get('version') for v in copies.part_list_choices(db, row['item_id'])['rebrickable'])
            copies.set_part_list_preference_in(db, row['item_id'], {'source': picked['source'], 'version': None if newest else picked.get('version')},
                                               via=via, actor=actor)
        for _ in range(row['quantity']):
            copy_id, waiting = _add_copy(db, row, via, actor)
            receipt['copies'].append(copy_id)
            receipt['guards'][copy_id] = dict(db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone())
            if waiting:
                receipt['pending'].append(dict(waiting, copy_id=copy_id))
    else:
        receipt['stock'] = stock.add_loose(db, item_id=row['item_id'], color_id=row['color_id'], quantity=row['quantity'], condition=row['condition'],
                                           lot_id=row.get('lot_id'), storage_id=row.get('storage_id'), note=row.get('note'), via=via, actor=actor)
    if photo and row['where'] != 'wishlist' and (receipt['stock'] or receipt['copies']):
        from . import part_inventory
        from .media import media_root
        receipt['photos'].append(part_inventory.keep_photo(db, media_root(db), row['item_id'], row['color_id'], photo,
                                                           stock_id=(receipt['stock'] or {}).get('id'), copy_id=receipt['copies'][0] if receipt['copies'] else None))
    receipt['job_id'] = pipeline.queue_steps(row['item_id'], via=via, actor=actor)
    return _save_receipt(db, receipt, via, actor)


def _save_receipt(db, receipt, via, actor):
    event = _event(db, 'add:' + receipt['batch'], 'receipt', None, receipt, via, actor)
    return {**receipt, 'event_id': event}


# ---------- Fetch from Rebrickable: the copies its receipt asked for (M.8f) ----------

UNSETTLED = f"""FROM main.event e WHERE e.entity_kind='add' AND e.field='receipt' AND json_extract(e.new_value, '$.fetch_job') IS NOT NULL
    AND NOT EXISTS(SELECT 1 FROM main.event_undo u WHERE u.event_id=e.id)
    AND NOT EXISTS(SELECT 1 FROM main.event f WHERE f.entity_kind='add' AND f.entity_id=e.entity_id AND f.field IN ('fetched', 'fetch_failed')
                   AND json_extract(f.new_value, '$.receipt')=e.id)"""


def has_unsettled_fetches(db):
    """A fetch job of an Add receipt is done (or finally failed) and the receipt has not been settled yet: the next drain settles it."""
    return any(_settleable(db, r) for r in db.execute(f'SELECT e.id, e.new_value {UNSETTLED}'))


def _settleable(db, event):
    job = db.execute('SELECT state, item_id FROM main.job WHERE id=?', (json.loads(event['new_value'])['fetch_job'],)).fetchone()
    return job is not None and job['state'] == 'done' and job['item_id'] is not None


def settle_fetches(db, *, via=None, actor=None):
    """Create what the receipts of a finished `rebrickable_set` job asked for, once each: the quantity of copies of the fetched set (with
    the latest Rebrickable list, the same preselection as any Add), or its wish, and the set's own pipeline job. Each is one
    `add:fetched` event, undoable like the receipt's rows; rows that cannot be made are recorded as `add:fetch_failed` and not tried
    again. A job that failed leaves its receipt with nothing to create (the job view says so; Retry queues the job again and a later
    run settles it). Returns the number of receipts settled."""
    settled = 0
    for candidate in [r[0] for r in db.execute(f'SELECT e.id {UNSETTLED} ORDER BY e.id').fetchall()]:
        with transaction(db):                                       # the write lock first, then the checks: another worker or an Undo may have got there
            event = db.execute(f'SELECT e.id, e.via, e.actor, e.entity_id, e.new_value {UNSETTLED} AND e.id=?', (candidate,)).fetchone()
            if event is None:                                       # settled by another process, or undone, since the list was read
                continue
            receipt = json.loads(event['new_value'])
            job = db.execute('SELECT state, item_id FROM main.job WHERE id=?', (receipt['fetch_job'],)).fetchone()
            if job is None or job['state'] != 'done' or job['item_id'] is None:
                continue
            settled += 1
            try:
                if not isinstance(receipt.get('ask'), dict):
                    raise ValueError('this row was added before fetch follow-ups existed, so it did not record what to create')
                _create_fetched(db, event, receipt, job['item_id'], via or event['via'], actor if via else event['actor'])
            except Exception as error:                              # one receipt never stops the drain or the others; it is recorded and not tried again
                audit(db, 'add:' + event['entity_id'], 'fetch_failed', None, dict(receipt=event['id'], fetch_job=receipt['fetch_job'], error=str(error)),
                      via=via or event['via'], actor=actor if via else event['actor'])
    return settled


def _create_fetched(db, event, receipt, item_id, via, actor):
    """The rows of one settled fetch, inside the caller's transaction; a refusal rolls its savepoint back and is recorded by the caller."""
    ask = receipt.get('ask') or {}
    row = dict(ask, item_id=item_id, kind='set', color_id=None, decision='another', quantity=ask.get('quantity') or 1)
    made = dict(batch=receipt['batch'], index=receipt['index'], receipt=event['id'], fetch_job=receipt['fetch_job'], item_id=item_id,
                kind='set', where=ask.get('where'), quantity=row['quantity'], copies=[], guards={}, stock=None, wish=None, created_wishlist=None,
                pending=[], job_id=None, name=receipt.get('name'), label=receipt.get('label'))
    db.execute('SAVEPOINT fetched')
    try:
        items.ensure(db, item_id)
        live = decorate(db, row)
        made.update(name=live['name'], label=live['label'])
        if ask.get('where') == 'wishlist':
            _add_wish(db, row, made, via, actor)
        else:
            for _ in range(row['quantity']):
                copy_id, waiting = _add_copy(db, row, via, actor)
                made['copies'].append(copy_id)
                made['guards'][copy_id] = dict(db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone())
                if waiting:
                    made['pending'].append(dict(waiting, copy_id=copy_id))
        made['job_id'] = Pipeline(db).queue_steps(item_id, via=via, actor=actor)
        _event(db, 'add:' + receipt['batch'], 'fetched', None, made, via, actor)
    except BaseException:
        db.execute('ROLLBACK TO fetched')
        raise
    finally:
        db.execute('RELEASE fetched')


def fetch_outcome(db, job_id):
    """What became of the Add row that fetched this job's set, for the Add page: `{'state', 'message', 'copies'}`. `state` is `added`
    (rows made), `waiting` (the job is not done), `failed` (the job failed: nothing was added), `refused` (the fetch worked but the
    rows could not be made) or `unsettled` (done, rows follow with the next drain)."""
    job = db.execute('SELECT state FROM main.job WHERE id=?', (job_id,)).fetchone()
    receipt = db.execute("""SELECT id, entity_id FROM main.event WHERE entity_kind='add' AND field='receipt'
                            AND json_extract(new_value, '$.fetch_job')=? ORDER BY id DESC LIMIT 1""", (job_id,)).fetchone()
    if job is None or receipt is None:
        return None
    if job['state'] == 'failed':
        return dict(state='failed', copies=0, message='Fetch failed · nothing was added')
    if job['state'] != 'done':
        return dict(state='waiting', copies=0, message='Fetching from Rebrickable')
    done = db.execute("""SELECT f.field, f.new_value FROM main.event f WHERE f.entity_kind='add' AND f.entity_id=? AND f.field IN ('fetched', 'fetch_failed')
                         AND json_extract(f.new_value, '$.receipt')=? ORDER BY f.id DESC LIMIT 1""", (receipt['entity_id'], receipt['id'])).fetchone()
    if done is None:
        return dict(state='unsettled', copies=0, message='Fetched · adding it now')
    value = json.loads(done['new_value'])
    if done['field'] == 'fetch_failed':
        return dict(state='refused', copies=0, message='Fetched, but nothing was added · ' + str(value.get('error') or 'review the set'))
    if value.get('wish'):
        return dict(state='added', copies=0, message='Fetched · added to the wishlist')
    count = len(value.get('copies') or [])
    return dict(state='added', copies=count, message=f'Fetched · {count} {"copy" if count == 1 else "copies"} added')


# ---------- undo ----------

COPY_USER_COLUMNS = ('condition', 'storage_id', 'place_id', 'purchase_date', 'purchase_price', 'purchase_currency', 'note', 'current_value',
                     'current_value_currency', 'pinned')


def _copy_untouched(db, copy_id, snapshot):
    """Nothing a person made is on the copy: its own columns are as Add wrote them and no line, flag, check or transfer exists."""
    row = db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()
    if row is None:
        return False
    columns = COPY_USER_COLUMNS + (('completeness',) if snapshot['completeness_source'] == 'manual' else ())
    if any(row[c] != snapshot[c] for c in columns):
        return False
    return not any(db.execute(sql, (copy_id,)).fetchone() for sql in (
        'SELECT 1 FROM main.copy_part WHERE copy_id=? AND (missing>0 OR damaged>0 OR checked=1) LIMIT 1',
        'SELECT 1 FROM main.copy_figure WHERE copy_id=? AND missing>0 LIMIT 1',
        'SELECT 1 FROM main.copy_flag WHERE copy_id=? LIMIT 1', 'SELECT 1 FROM main.part_check WHERE copy_id=? LIMIT 1',
        'SELECT 1 FROM main.stock_transfer WHERE copy_id=? LIMIT 1', 'SELECT 1 FROM main.allocation WHERE copy_id=? LIMIT 1',
        'SELECT 1 FROM main.photo WHERE copy_id=? AND archived_at IS NULL LIMIT 1'))


def _undo_receipt(db, event, via, actor):
    """Reverse one Add row: archive the copies it made, take the stock back, archive or restore the wish. Refused whole when anything
    it made changed since (undo the later save first). Local items an unidentified add created stay; nothing references them."""
    r = json.loads(event['new_value'])
    stamp = now()
    changed = 'Item changed · undo the later save first'
    if r.get('wish'):
        w = r['wish']
        row = db.execute('SELECT * FROM main.wish WHERE id=?', (w['id'],)).fetchone()
        if row is None or dict(row) != w['after']:
            raise ValueError(changed)
        if w['created']:
            db.execute('UPDATE main.wish SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, w['id']))
        else:
            b = w['before']
            db.execute('''UPDATE main.wish SET quantity=?, condition=?, note=?, max_price=?, max_price_currency=?, qty_filled_manual=?, updated_at=?
                          WHERE id=?''', (b['quantity'], b['condition'], b['note'], b['max_price'], b['max_price_currency'], b['qty_filled_manual'],
                                          b['updated_at'], w['id']))
        audit(db, 'wish:' + w['id'], 'undo_add', dict(row), dict(db.execute('SELECT * FROM main.wish WHERE id=?', (w['id'],)).fetchone()), via=via, actor=actor)
        if r.get('created_wishlist') and not db.execute('SELECT 1 FROM main.wish WHERE wishlist_id=? AND archived_at IS NULL', (r['created_wishlist'],)).fetchone():
            db.execute('UPDATE main.wishlist SET archived_at=? WHERE id=?', (stamp, r['created_wishlist']))
            audit(db, 'wishlist:' + r['created_wishlist'], 'archived_at', None, stamp, via=via, actor=actor)
    for photo_id in r.get('photos') or ():                             # the photo this row kept goes with it; the file stays the person's
        db.execute('UPDATE main.photo SET archived_at=? WHERE id=? AND archived_at IS NULL', (stamp, photo_id))
    if r.get('stock'):
        stock.undo_added(db, r['stock'], via=via, actor=actor)
    for copy_id in reversed(r['copies']):
        row = db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()
        if row is not None and row['archived_at'] is not None:
            continue                                                   # archived since: nothing to undo
        if not _copy_untouched(db, copy_id, r['guards'][copy_id]):
            raise ValueError(changed)
        if row['inventory_pending']:
            pending.cancel_pending_in(db, copy_id, via=via, actor=actor)
        db.execute('UPDATE main.copy SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, copy_id))
        audit(db, 'copy:' + copy_id, 'archived_at', None, stamp, via=via, actor=actor)
    undo_id = _event(db, 'add:' + r['batch'], 'undo', None, {'undoes': event['id'], 'index': r['index']}, via, actor)
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('add', 'receipt', _undo_receipt)
undoing.register('add', 'fetched', _undo_receipt)           # the copies a finished Fetch from Rebrickable made: the same rows, the same refusal


def undo(db, batch, *, via=None, actor=None):
    """Undo every row of a batch that is not undone yet, last row first, all or none. Returns the number of rows undone."""
    if via is None:
        via, actor = origin()
    with transaction(db):
        ids = [r[0] for r in db.execute(f"""SELECT e.id FROM main.event e WHERE e.entity_kind='add' AND e.field IN ('receipt', 'fetched')
                                            AND e.entity_id=? AND NOT {undoing.undone_sql('e')} ORDER BY e.id DESC""", (batch,))]
        for event_id in ids:
            undoing.undo_event(db, event_id, via=via, actor=actor)
    return len(ids)


# ---------- readers of the 3.3 store, until the piece that ports their callers (M.11 API) ----------

def catalogue_path(db):
    return Path(db.execute('PRAGMA database_list').fetchone()['file']).with_name('bricklink-catalog.db')


def colour_ink(rgb):
    """Readable text for the shared catalogue colour chip."""
    channels = [int(rgb[n:n+2],16)/255 for n in (0,2,4)] if rgb and re.fullmatch('[a-fA-F0-9]{6}',rgb) else []
    luminance = sum((c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4)*w for c,w in zip(channels,(.2126,.7152,.0722)))
    return '#1A1816' if luminance>.45 else '#FAFAF8'
