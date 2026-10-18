"""Read-only intake, signed review proposals and atomic collection receipts."""
from .transaction import transaction
from contextlib import closing
import csv
import io
import json
from pathlib import Path
import re
import sqlite3
import uuid
from xml.etree import ElementTree as ET

from .admin import audit
from decimal import Decimal, InvalidOperation
from .pipeline import Pipeline, STEPS
from .sources.base import SourceError, now
from .sources.rebrickable import Rebrickable

TYPES = {'S': 'Set', 'M': 'Minifigure', 'P': 'Part', 'I': 'Instruction',
         'O': 'Box', 'G': 'Gear', 'B': 'Book', 'C': 'Catalog'}
WHERE = ('owned', 'loose', 'wishlist')


def catalogue_path(db):
    return Path(db.execute('PRAGMA database_list').fetchone()['file']).with_name('bricklink-catalog.db')


def search(db, kind, query='', sort='number'):
    if kind not in TYPES or sort not in ('number', 'name'):
        raise ValueError('Choose an item type and sort')
    path = catalogue_path(db)
    if not path.is_file():
        raise ValueError('Load the BrickLink catalogue in Tools & Admin first')
    from . import size_search
    full, partial, rest = size_search.parse(query)
    indexed = size_search.ensure_column(path) if (full or partial) else False
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as cat:
        cat.row_factory = sqlite3.Row
        literal = lambda text: '%' + text.strip().lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        clause, params = 'item_type=?', [kind]
        if full or partial:
            # #41: a size in the query filters by size key (any order, x, ×, * or spaces); other words as before.
            column = 'size_key' if indexed else 'bw_size_key(name)'
            if not indexed:
                cat.create_function('bw_size_key', 1, size_search.name_key, deterministic=True)
            if full:
                clause += f' AND {column}=?'; params.append(full)
            else:
                clause += f" AND ('x'||{column}||'x') LIKE ?"; params.append('%x' + partial + 'x%')
            for word in rest.split():
                clause += " AND normalized_name LIKE ? ESCAPE '\\'"; params.append(literal(word))
        else:
            # Escape wildcard characters so a pasted number is always literal.
            term = literal(query)
            clause += " AND (lower(item_no) LIKE ? ESCAPE '\\' OR normalized_name LIKE ? ESCAPE '\\')"; params += [term, term]
        count = cat.execute('SELECT count(*) FROM items WHERE ' + clause, params).fetchone()[0]
        rows = [dict(r) for r in cat.execute('SELECT item_type,item_no,name FROM items WHERE ' + clause +
            ' ORDER BY ' + ('normalized_name,item_no' if sort == 'name' else 'item_no') + ' LIMIT 100', params)]
    return {'items': [decorate(db, row) for row in rows], 'count': count}


def lookup(db, kind, number):
    if kind not in TYPES or not re.fullmatch('[A-Za-z0-9-]{1,32}', str(number)):
        return None
    path = catalogue_path(db)
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as cat:
        row = cat.execute('SELECT name FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone()
    return dict(item_type=kind, item_no=number, name=row[0]) if row else None


def colors(db):
    return [dict(r) for r in db.execute('SELECT color_id,name,rgb FROM colors ORDER BY name,color_id')]


def decorate(db, row):
    row = dict(row)
    priority = db.execute("SELECT value FROM settings WHERE key='source_priority'").fetchone()
    order = json.loads(priority[0])['pictures'] if priority else {}
    sources = [s.split(':')[0] for s in order.get(row['item_type'], order.get('*', ['bricklink', 'rebrickable']))]
    images = [dict(r) for r in db.execute('SELECT id,source,kind FROM item_images WHERE item_type=? AND item_no=? '
        'AND (color_id IS ? OR color_id IS NULL) ORDER BY fetched_at DESC,id DESC',
        (row['item_type'], row['item_no'], row.get('color_id')))]
    images.sort(key=lambda r: sources.index(r['source']) if r['source'] in sources else len(sources))
    row['image'] = images[0]['id'] if images else None
    row['type_name'] = TYPES[row['item_type']]
    row['owned'] = db.execute('SELECT count(*) FROM copies WHERE item_type=? AND set_no=? AND archived_at IS NULL',
                              (row['item_type'], row['item_no'])).fetchone()[0]
    row['owned'] += db.execute('SELECT coalesce(sum(quantity),0) FROM loose_stock WHERE item_type=? AND item_no=? '
        'AND (color_id IS ? OR ? IS NULL) AND archived_at IS NULL',
        (row['item_type'], row['item_no'], row.get('color_id'), row.get('color_id'))).fetchone()[0]
    wish_rows = db.execute('SELECT list_id,color_id FROM wishlist WHERE item_type=? AND item_no=? AND archived_at IS NULL',
                           (row['item_type'], row['item_no'])).fetchall()
    row['wished_by_list'] = {}
    for wish in wish_rows:
        row['wished_by_list'].setdefault(wish['list_id'], []).append(wish['color_id'])
    row['wished_colors'] = [w['color_id'] for w in wish_rows if row.get('list_id') is None or w['list_id']==row['list_id']]
    row['wished'] = row.get('color_id') in row['wished_colors']
    row['to_check'] = bool(db.execute("SELECT 1 FROM id_match WHERE item_type=? AND item_no=? AND status='to_check'",
                                    (row['item_type'], row['item_no'])).fetchone())
    return row


def quantity(value):
    if not re.fullmatch('[0-9]{1,5}', str(value)) or not 1 <= int(value) <= 9999:
        raise ValueError('Quantity must be between 1 and 9999')
    return int(value)


def paste(text, kind):
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*([A-Za-z0-9-]{1,32})(?:\s+[x×]\s*([0-9]+))?\s*', line)
        result.append(dict(item_type=kind, item_no=match[1], quantity=quantity(match[2] or 1))
                      if match else dict(unresolved=line, reason='Use a number and optional quantity'))
    return result


def file_rows(data, filename, kind):
    text = data.decode('utf-8-sig')
    if filename.lower().endswith('.xml'):
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ValueError('Choose XML without document declarations')
        root = ET.fromstring(text)
        if root.tag not in ('INVENTORY', 'WANTEDLIST'):
            raise ValueError('Choose a BrickLink wanted list or inventory')
        result = []
        for entry in root.findall('ITEM'):
            result.append(dict(item_type=entry.findtext('ITEMTYPE') or kind,
                item_no=entry.findtext('ITEMID') or '', quantity=quantity(entry.findtext('MINQTY') or entry.findtext('QTY') or '1'),
                color_id=int(entry.findtext('COLOR')) if entry.findtext('COLOR') else None,
                condition=entry.findtext('CONDITION') or 'X', note=entry.findtext('REMARKS'),
                max_price=entry.findtext('MAXPRICE'), bricklink_list_id=entry.findtext('WANTEDLISTID'),
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
        rb_kind = 'P' if entry.get('part_num') or entry.get('part') else 'M' if entry.get('minifig_num') else 'S'
        result.append(dict(item_type=rb_kind, item_no=number, quantity=quantity(entry.get('quantity') or '1'),
            rb=True, rb_color=entry.get('color_id') or entry.get('color') or None))
    return result


def rb_resolve(db, row, client):
    kind = {'P': 'part', 'M': 'minifigure', 'S': 'set'}[row['item_type']]
    match = db.execute("SELECT * FROM id_match WHERE source='rebrickable' AND kind=? AND source_id=?",
                       (kind, row['item_no'])).fetchone()
    if match and match['status'] in ('manual', 'matched', 'inferred') and match['item_type'] != '?':
        number = match['item_no']
    else:
        reply = (client.part(row['item_no']) if kind == 'part' else client.minifigure(row['item_no'])
                 if kind == 'minifigure' else client.call('/sets/' + client.identifier(row['item_no']) + '/'))
        ids = reply.get('external_ids', {}).get('BrickLink', [])
        if isinstance(ids, dict):
            ids = ids.get('ext_ids', [])
        ids = list(dict.fromkeys(str(n) for n in ids))
        if len(ids) != 1:
            raise ValueError('Rebrickable id needs manual matching')
        number = ids[0]
    result = {**row, 'item_no': number}
    if row.get('rb_color') is not None:
        match = db.execute("SELECT color_id,status FROM id_match WHERE source='rebrickable' AND kind='color' AND source_id=?",
                           (str(row['rb_color']),)).fetchone()
        if match and match['status'] in ('manual', 'matched', 'inferred'):
            result['color_id'] = match['color_id']
        else:
            reply = client.color(int(row['rb_color']))
            ids = reply.get('external_ids', {}).get('BrickLink', {})
            ids = ids.get('ext_ids', []) if isinstance(ids, dict) else ids
            if len(ids) != 1:
                raise ValueError('Rebrickable colour needs manual matching')
            result['color_id'] = int(ids[0])
            # Source evidence is permitted during preview, collection rows are not.
            with db:
                client.match('color', reply, canonical=result['color_id'])
    return result


def resolve(db, rows, where, *, rb_client=None, list_id='default', map_wanted_ids=True):
    if where not in WHERE:
        raise ValueError('Choose where to add')
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('Review up to 500 items at a time')
    from . import wishlists, upgrade
    from ..web.formatting import money
    currency = upgrade.configured_currency(db)
    lists = wishlists.listing(db)
    linked = {l['bricklink_id']: l for l in lists if l['bricklink_id']}
    if where == 'wishlist': wishlists.require(db, list_id)
    resolved, unresolved = [], []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Choose items from the catalogue')
        original = dict(row)
        try:
            if row.get('unresolved'):
                raise ValueError(row['reason'])
            if row.get('rb'):
                row = rb_resolve(db, row, rb_client or Rebrickable(db))
            identity = lookup(db, row['item_type'], row['item_no'])
            if not identity:
                raise ValueError('Not found in the BrickLink catalogue')
            color = row.get('color_id') if row['item_type'] == 'P' else None
            if color is not None and not db.execute('SELECT 1 FROM colors WHERE color_id=?', (color,)).fetchone():
                raise ValueError('Colour needs manual matching')
            target = list_id
            wanted_id = row.get('bricklink_list_id') if map_wanted_ids and where == 'wishlist' else None
            if wanted_id:
                if not wanted_id.isdecimal(): raise ValueError('BrickLink wanted list id must be numeric')
                target = linked[wanted_id]['id'] if wanted_id in linked else 'new-bl:' + wanted_id
            list_name = next((l['name'] for l in lists if l['id'] == target), 'BrickLink ' + (wanted_id or ''))
            maximum = row.get('max_price')
            if maximum is not None:
                try: amount = Decimal(maximum)
                except InvalidOperation: raise ValueError('Invalid MAXPRICE') from None
                if not amount.is_finite(): raise ValueError('Invalid MAXPRICE')
                maximum = format(amount, 'f') if amount >= 0 else None  # BrickLink exports use a negative sentinel for no limit.
            condition = row.get('condition', 'U')
            if condition == 'X' and where != 'wishlist': condition = 'U'
            # #35: BrickLink's QTYFILLED becomes the line's filled quantity (a manual value, shown as such).
            filled = row.get('qtyfilled')
            filled = int(filled) if where == 'wishlist' and isinstance(filled, str) and filled.strip().isdigit() and int(filled) > 0 else None
            resolved.append(decorate(db, {**identity, 'quantity': quantity(row.get('quantity', 1)),
                'list_id': target, 'list_name': list_name, 'bricklink_list_id': wanted_id, 'qty_filled': filled,
                'max_price': maximum, 'max_price_currency': currency if maximum is not None else None,
                'import_notes': ([f"Max price {money(maximum, currency, fixed=True)} · BrickLink currency setting: {currency}"] if maximum is not None else []) +
                    ([f"Filled so far {filled} (BrickLink QTYFILLED)"] if filled is not None else []) +
                    (['Create ' + list_name + ' on confirm'] if target.startswith('new-bl:') else []),
                'where': where, 'color_id': color, 'note': row.get('note'), 'condition': condition, 'completeness': '', 'decision': ''}))
        except (ValueError, SourceError, TypeError, KeyError) as error:
            unresolved.append({'number': original.get('unresolved') or original.get('item_no'), 'reason': str(error)})
    if len(resolved) > 500:
        raise ValueError('Review up to 500 items at a time')
    return dict(items=resolved, unresolved=unresolved)


def validate_edits(db, proposal, edits, *, batch=None):
    if not isinstance(edits, list) or len(edits) != len(proposal):
        raise ValueError('Review the items before adding')
    result = []
    wishes, copies = set(), set()
    saved = {r['index'] for r in receipts(db, batch)} if batch else set()
    for index, (original, edit) in enumerate(zip(proposal, edits)):
        if not isinstance(edit, dict):
            raise ValueError('Review the items before adding')
        if index in saved:
            result.append(original)
            continue
        row = {**original, **{k: edit.get(k, original.get(k)) for k in
            ('quantity', 'where', 'color_id', 'condition', 'completeness', 'decision', 'note', 'list_id')}}
        row['quantity'] = quantity(row['quantity'])
        if row['where'] not in WHERE or row['condition'] not in (('N','U','D') if row['where']=='loose' else ('N','U','X') if row['where']=='wishlist' else ('N','U')) or row['completeness'] not in ('', 'S', 'C', 'I'):
            raise ValueError('Choose a destination, condition and completeness')
        if row['color_id'] in ('', None):
            row['color_id'] = None
        else:
            row['color_id'] = int(row['color_id'])
        if row['item_type'] == 'P' and (row['color_id'] is None or not db.execute('SELECT 1 FROM colors WHERE color_id=?', (row['color_id'],)).fetchone()):
            raise ValueError('Choose a colour for each part')
        if row['item_type'] != 'P':
            row['color_id'] = None
        for key,table in [('storage_id','storages'),('lot_id','lots')]:
            if row.get(key) is not None and not db.execute('SELECT 1 FROM '+table+' WHERE id=? AND archived_at IS NULL',(row[key],)).fetchone():
                raise ValueError('Choose an active '+key.replace('_id',''))
        if row['where'] == 'wishlist':
            from . import wishlists
            row['list_id'] = row.get('list_id') or 'default'
            if not str(row['list_id']).startswith('new-bl:'):
                wishlists.require(db, row['list_id'])
            elif row['list_id'] != original.get('list_id'):
                raise ValueError('Choose an existing wishlist')
        key = row['item_type'], row['item_no'], row['color_id'], row.get('list_id') if row['where'] == 'wishlist' else None
        current = decorate(db, row)
        duplicate = current['owned'] or current['wished'] or key in wishes or key in copies
        if duplicate and row['decision'] not in ('another', 'skip'):
            raise ValueError('Already owned or wished · choose add to the wished quantity or skip' if row['where'] == 'wishlist' else 'Already owned or wished · choose add another copy or skip')
        if row['decision'] != 'skip':
            if row['where'] == 'wishlist':
                wishes.add(key)
            else:
                copies.add(key)
        result.append(row)
    return result



def receipt_rows(db, *, batch=None, kind=None, number=None):
    clauses,params=[],[]
    for key,value in [('batch',batch),('item_type',kind),('item_no',number)]:
        if value is not None:
            clauses.append("json_extract(new_value,'$."+key+"')=?")
            params.append(value)
    sql="""SELECT new_value FROM (
        SELECT new_value FROM events WHERE entity='bw_add' AND field='receipt'
        UNION ALL SELECT json_extract(r.value,'$.new_value') new_value
        FROM events e,json_each(e.new_value,'$.receipts') r
        WHERE e.entity='bw_api' AND json_extract(r.value,'$.entity')='bw_add'
        AND json_extract(r.value,'$.field')='receipt'
        UNION ALL SELECT i.value FROM events e,json_each(e.new_value,'$.items') i
        WHERE e.entity='bw_sync' AND e.field='receipt'
        UNION ALL SELECT i.value FROM events e,json_each(e.new_value,'$.receipts') r,
        json_each(json_extract(r.value,'$.new_value'),'$.items') i
        WHERE e.entity='bw_api' AND json_extract(r.value,'$.entity')='bw_sync'
        AND json_extract(r.value,'$.field')='receipt')"""
    return db.execute(sql+(' WHERE '+' AND '.join(clauses) if clauses else ''),params)

def materialize(db, kind, number):
    """Populate only Add receipts, once; never reset an existing part check."""
    from .pipeline import cooperative
    receipts = list(receipt_rows(db,kind=kind,number=number))
    for receipt in cooperative(db, receipts):
        data = json.loads(receipt[0])
        if (data['item_type'], data['item_no']) != (kind, number):
            continue
        for identifier in cooperative(db, data['copies']):
            with transaction(db):
                if db.execute("SELECT 1 FROM events WHERE entity=? AND field='inventory_materialized'", ('copy:' + identifier,)).fetchone():
                    continue
                if not db.execute('SELECT 1 FROM copies WHERE id=? AND archived_at IS NULL', (identifier,)).fetchone():
                    continue
                created = []
                for line in db.execute('SELECT * FROM inventory_lines WHERE parent_item_type=? AND parent_item_no=? ORDER BY id', (kind, number)).fetchall():
                    for spare, amount in ((0, line['quantity']), (1, line['extra_quantity'])):
                        if not amount:
                            continue
                        cursor = db.execute('INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,spare,quantity,missing,damaged,checked,source_ref) VALUES(?,?,?,?,?,?,0,0,0,?)',
                            (identifier, line['child_item_type'], line['child_item_no'], line['color_id'], spare, amount, line['id']))
                        created.append(dict(db.execute('SELECT * FROM copy_parts WHERE id=?', (cursor.lastrowid,)).fetchone()))
                audit(db, 'copy:' + identifier, 'inventory_materialized', None, created)


def receipts(db, batch):
    return [json.loads(r[0]) for r in receipt_rows(db,batch=batch)]


def confirm(db, rows, *, batch, photo=None, keep_photo=False, guard=True):
    from . import stock
    pipeline = Pipeline(db)
    result = []
    for index, row in enumerate(rows):
        if row['decision'] == 'skip':
            continue
        kind, number = row['item_type'], row['item_no']
        stamp = now().isoformat()
        receipt = dict(batch=batch, index=index, item_type=kind, item_no=number, copies=[], stock=[], stock_changes=[], wishlist=None)
        with transaction(db):
            saved = next((r for r in receipts(db, batch) if r['index'] == index), None)
            if saved:
                result.append(saved)
                continue
            duplicate = decorate(db, row)
            if row['decision'] != 'another' and (duplicate['owned'] or duplicate['wished']):
                raise ValueError('Already on Wishlist · choose add to the wished quantity or skip'
                                 if row['where'] == 'wishlist' and duplicate['wished'] else 'Already owned · review again')
            existing = db.execute('SELECT * FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone()
            if not existing:
                db.execute('INSERT INTO items(item_type,item_no,name,updated_at) VALUES(?,?,?,?)', (kind, number, row['name'], stamp))
                audit(db, 'item:' + kind + ':' + number, 'created', None, dict(db.execute('SELECT * FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone()))
            if row['where'] == 'owned' and kind == 'S':
                for _ in range(row['quantity']):
                    identifier = uuid.uuid4().hex
                    db.execute('INSERT INTO copies(id,item_type,set_no,condition,completeness,completeness_source,updated_at) VALUES(?,?,?,?,?,?,?)',
                        (identifier, kind, number, row['condition'], row['completeness'] or 'I', 'manual' if row['completeness'] else 'derived', stamp))
                    receipt['copies'].append(identifier)
                    audit(db, 'copy:' + identifier, 'created', None, dict(db.execute('SELECT * FROM copies WHERE id=?', (identifier,)).fetchone()))
            elif row['where'] == 'wishlist':
                from . import wishlists
                target = row.get('list_id', 'default')
                if target.startswith('new-bl:'):
                    wanted_id = target.split(':', 1)[1]
                    found = db.execute('SELECT id FROM wishlists WHERE bricklink_id=? AND archived_at IS NULL', (wanted_id,)).fetchone()
                    if found:
                        target = found[0]
                    else:
                        target, event = wishlists.save(db, data=dict(name='BrickLink ' + wanted_id, bricklink_id=wanted_id))
                        receipt['created_list_event'] = event
                wishlists.require(db, target)
                old = db.execute('SELECT * FROM wishlist WHERE item_type=? AND item_no=? AND color_id IS ? AND list_id=? '
                    'ORDER BY archived_at IS NULL DESC,id DESC LIMIT 1', (kind, number, row['color_id'], target)).fetchone()
                if old and old['archived_at'] is None and row['decision'] != 'another':
                    raise ValueError('Already on Wishlist · choose add to the wished quantity or skip')
                condition = {'N': 'new', 'U': 'used', 'X': 'any'}[row['condition']]
                if old:
                    amount = old['quantity'] + row['quantity'] if old['archived_at'] is None else row['quantity']
                    db.execute('UPDATE wishlist SET archived_at=NULL,quantity=?,condition=?,updated_at=?,note=?,max_price=?,max_price_currency=?,qty_filled_manual=coalesce(?,qty_filled_manual) WHERE id=?',
                               (amount, condition, stamp, row.get('note') if row.get('note') is not None else old['note'], row.get('max_price') if row.get('max_price') is not None else old['max_price'], row.get('max_price_currency') if row.get('max_price') is not None else old['max_price_currency'], row.get('qty_filled'), old['id']))
                    identifier = old['id']
                else:
                    identifier = db.execute('INSERT INTO wishlist(item_type,item_no,color_id,quantity,condition,note,added_at,updated_at,list_id,max_price,max_price_currency,qty_filled_manual) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (kind, number, row['color_id'], row['quantity'], condition, row.get('note'), stamp, stamp, target, row.get('max_price'), row.get('max_price_currency'), row.get('qty_filled'))).lastrowid
                receipt['wishlist'] = dict(old) if old else False
                receipt['wishlist_id'] = identifier
                audit(db, 'wishlist:' + str(identifier), 'added', dict(old) if old else None,
                    dict(db.execute('SELECT * FROM wishlist WHERE id=?', (identifier,)).fetchone()))
            else:
                identifier, _ = stock.add_loose(db, receipt['stock_changes'], item_type=kind,
                    item_no=number, color_id=row['color_id'], quantity=row['quantity'],
                    condition=row['condition'],storage_id=row.get('storage_id'),lot_id=row.get('lot_id'),note=row.get('note'))
                receipt['stock'].append(identifier)
            settings = dict(db.execute('SELECT key,value FROM settings'))
            order = json.loads(settings['import_order:' + kind])
            if len(order) != len(STEPS) or set(order) != set(STEPS):
                raise ValueError('Check the import order in Tools & Admin')
            from .sources.base import AUDIT_ORIGIN
            receipt['job_id'] = pipeline.queue_steps(kind, number, order, via='api' if AUDIT_ORIGIN.get() == 'api' else 'app')
            receipt['name'] = row['name']
            if guard:  # on for every caller; loose stock is guarded by stock.undo_loose, which knows merged lots
                receipt['guards'] = [(table, [dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE id IN ('+','.join('?' for _ in ids)+') ORDER BY id', ids)])
                    for table,ids in [('copies',receipt['copies']),('wishlist',[receipt['wishlist_id']] if 'wishlist_id' in receipt else [])] if ids]
            audit(db, 'bw_add', 'receipt', None, receipt)
            if keep_photo and photo:
                from .sources.brickognize import keep
                keep(db, kind, number, photo, copy_id=next(iter(receipt['copies']), None), stock_id=next(iter(receipt['stock']), None))
        result.append(receipt)
    return result


def undo(db, batch, *, saved_receipts=None):
    from . import stock
    with transaction(db):
        # An undo is recorded for the whole batch (web) or for one receipt as "batch#index" (an API
        # write bundles several receipts under one batch and undoes them one call at a time).
        done = {json.loads(r[0]) for r in db.execute("SELECT old_value FROM events WHERE entity='bw_add' AND field='undo'")}
        if batch in done:
            return
        receipts = saved_receipts if saved_receipts is not None else [json.loads(r[0]) for r in db.execute("SELECT new_value FROM events WHERE entity='bw_add' AND field='receipt'")]
        undone = []
        for receipt in reversed(receipts):
            if receipt['batch'] != batch or f"{batch}#{receipt['index']}" in done:
                continue
            undone.append(receipt)
            for table,saved in receipt.get('guards',[]):
                if table == 'wishlist':
                    for row in saved: row.setdefault('list_id','default')
                current=[dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE id IN ('+','.join('?' for _ in saved)+') ORDER BY id',[r['id'] for r in saved])]
                if current != saved: raise ValueError('Item changed · undo the later save first')
            if 'stock_changes' in receipt:
                stock.undo_loose(db, receipt['stock_changes'])
            for table, ids in (('copies', receipt['copies']), ('loose_stock', [] if 'stock_changes' in receipt else receipt['stock'])):
                for identifier in ids:
                    old = db.execute(f'SELECT * FROM {table} WHERE id=?', (identifier,)).fetchone()
                    if old and old['archived_at'] is None:
                        db.execute(f'UPDATE {table} SET archived_at=?,updated_at=? WHERE id=?', (now().isoformat(), now().isoformat(), identifier))
                        audit(db, table + ':' + identifier, 'archived_at', dict(old), dict(db.execute(f'SELECT * FROM {table} WHERE id=?', (identifier,)).fetchone()))
            if receipt['wishlist'] is not None:
                identifier = receipt['wishlist_id']
                old = db.execute('SELECT * FROM wishlist WHERE id=?', (identifier,)).fetchone()
                saved = receipt['wishlist']
                if saved is not False and saved['archived_at'] is None:
                    from .collection import wish_collision
                    wish_collision(db, 'wishlist', saved)
                if saved is False:
                    db.execute('UPDATE wishlist SET archived_at=?,updated_at=? WHERE id=?', (now().isoformat(), now().isoformat(), identifier))
                else:
                    db.execute('UPDATE wishlist SET '+','.join(k+'=?' for k in saved if k!='id')+' WHERE id=?', (*[v for k,v in saved.items() if k!='id'], identifier))
                audit(db, 'wishlist:' + str(identifier), 'undo_add', dict(old), dict(db.execute('SELECT * FROM wishlist WHERE id=?', (identifier,)).fetchone()))
        for r in undone:
            if r.get('created_list_event'):
                from . import collection
                collection.undo(db, r['created_list_event'])
        if saved_receipts is None:
            audit(db, 'bw_add', 'undo', batch, None)
        for receipt in undone if saved_receipts is not None else []:
            audit(db, 'bw_add', 'undo', f"{batch}#{receipt['index']}", None)


def decorate_many(db, rows):
    """List-only identities, colours and local pictures, loaded in four queries.

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
        row['ink'] = colour_ink(row['rgb'])
        result.append(row)
    return result


def colour_ink(rgb):
    """Readable text for the shared catalogue colour chip."""
    channels = [int(rgb[n:n+2],16)/255 for n in (0,2,4)] if rgb and re.fullmatch('[a-fA-F0-9]{6}',rgb) else []
    luminance = sum((c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4)*w for c,w in zip(channels,(.2126,.7152,.0722)))
    return '#1A1816' if luminance>.45 else '#FAFAF8'
