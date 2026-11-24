"""Import plan, apply and undo for Brick Work's own zip export (ADR 0040, #524)."""
import io
import json
from uuid import uuid4
import zipfile
import zlib

from ..store4 import origins, pending
from ..store4.connect import as_current, has_catalogue, now as store_now
from . import errors, items, own_export, stock, sync
from . import undo as undoing
from .admin import audit, origin
from .importer import bricktracker
from .sources.base import now
from .transaction import transaction

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_MEMBERS = 40
MAX_RATIO = 200
ROW_CAP = 200
DIRECTION = 'brickwork_file'
SOURCE = 'brickwork_export'
CHANGED_ERROR = 'Something from this import has changed since · undo the later change first'

WRITE_ORDER = ('storage', 'place', 'flag', 'lot', 'wishlist', 'copy', 'stock', 'wish')
TABLE_SECTION = {
    'storage': 'places',
    'place': 'places',
    'flag': 'flags',
    'lot': 'collection',
    'wishlist': 'wishes',
    'copy': 'collection',
    'stock': 'collection',
    'wish': 'wishes',
}
ALLOWED_MEMBERS = frozenset({'manifest.json'} | {f'data/{t}.jsonl' for t in WRITE_ORDER})
PLAIN_FIELDS = {
    'storage': ('name', 'type', 'parent_id', 'note'),
    'place': ('name', 'kind'),
    'flag': ('name', 'kind', 'shown_on_grid', 'system'),
    'lot': ('name', 'note', 'storage_id', 'place_id', 'purchase_date', 'purchase_price', 'purchase_currency'),
    'wishlist': ('name', 'note', 'sort'),
    'copy': ('condition', 'completeness', 'completeness_source', 'storage_id', 'place_id',
             'purchase_date', 'purchase_price', 'purchase_currency', 'note',
             'current_value', 'current_value_currency', 'pinned'),
    'stock': ('kind', 'quantity', 'condition', 'storage_id', 'lot_id', 'place_id',
              'purchase_date', 'purchase_price', 'purchase_currency', 'note',
              'missing', 'damaged', 'checked'),
    'wish': ('wishlist_id', 'kind', 'quantity', 'condition', 'max_price', 'max_price_currency',
             'qty_filled_manual', 'note', 'max_price_boxed', 'max_price_boxed_currency'),
}
BOOL_FIELDS = frozenset({'shown_on_grid', 'system', 'pinned'})
PARENTS = {
    'storage': (('parent_id', 'storage', False),),
    'lot': (('storage_id', 'storage', False), ('place_id', 'place', False)),
    'copy': (('storage_id', 'storage', False), ('place_id', 'place', False)),
    'stock': (('storage_id', 'storage', False), ('place_id', 'place', False), ('lot_id', 'lot', False)),
    'wish': (('wishlist_id', 'wishlist', True),),
}


def read_zip(content: bytes):
    """Read and validate a Brick Work export zip without writing anything."""
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise errors.ValidationFailed('This is not a Brick Work export file')
    if len(content) > MAX_ZIP_BYTES:
        raise errors.ValidationFailed('Export file is larger than 50 MB')
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError):
        raise errors.ValidationFailed('This is not a Brick Work export file') from None
    with archive as zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise errors.ValidationFailed('Export file has too many members')
        seen, total_uncompressed = set(), 0
        for info in infos:
            name = info.filename
            if name in seen or name.startswith('/') or '\\' in name or '..' in name.split('/') or name not in ALLOWED_MEMBERS:
                raise errors.ValidationFailed('Unexpected file in export archive: ' + name)
            seen.add(name)
            if info.file_size < 0:
                raise errors.ValidationFailed('This is not a Brick Work export file')
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise errors.ValidationFailed('Export file is larger than 250 MB uncompressed')
            if info.file_size > 0 and (info.compress_size <= 0 or info.file_size > info.compress_size * MAX_RATIO):
                raise errors.ValidationFailed('Export file compression ratio is too high')
        if 'manifest.json' not in seen:
            raise errors.ValidationFailed('This is not a Brick Work export file')
        raw_members, remaining = {}, MAX_UNCOMPRESSED_BYTES
        for info in infos:
            # Cap each read to defeat forged zip size headers.
            cap = min(info.file_size, remaining)
            try:
                with zf.open(info) as fh:
                    data = fh.read(cap + 1)
            except (zipfile.BadZipFile, OSError, EOFError, RuntimeError, zlib.error):
                raise errors.ValidationFailed('This is not a Brick Work export file') from None
            if len(data) > cap:
                raise errors.ValidationFailed('Export file exceeds uncompressed size limit')
            remaining -= len(data)
            raw_members[info.filename] = data
    try:
        manifest = json.loads(raw_members['manifest.json'].decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise errors.ValidationFailed('This is not a Brick Work export file') from None
    if not isinstance(manifest, dict) or manifest.get('format') != own_export.FORMAT:
        raise errors.ValidationFailed('This is not a Brick Work export file')
    version = manifest.get('format_version')
    if type(version) is not int or version < 1:
        raise errors.ValidationFailed('This is not a Brick Work export file')
    if version > own_export.FORMAT_VERSION:
        raise errors.ValidationFailed('This file is from a newer Brick Work · update first')
    sections = manifest.get('sections')
    if not isinstance(sections, list) or not sections or any(not isinstance(s, str) or s not in own_export.SECTIONS for s in sections):
        raise errors.ValidationFailed('Export manifest has unknown sections')
    tables = {}
    for filename, raw in raw_members.items():
        if filename == 'manifest.json':
            continue
        table = filename.removeprefix('data/').removesuffix('.jsonl')
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            raise errors.ValidationFailed(f'{filename}: not valid UTF-8') from None
        rows = []
        for lineno, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                raise errors.ValidationFailed(f'{filename} line {lineno}: not a JSON object') from None
            if not isinstance(obj, dict):
                raise errors.ValidationFailed(f'{filename} line {lineno}: not a JSON object')
            rows.append(obj)
        tables[table] = rows
    return {'manifest': manifest, 'tables': tables}


def resolve_item(db, ref):
    """Return the item id in main or catalogue for an export item ref, or None."""
    if not isinstance(ref, dict) or ref.get('key') is None or ref.get('key') == '' or ref.get('local'):
        return None
    provider, namespace, key, kind = ref.get('provider'), ref.get('namespace'), ref.get('key'), ref.get('kind')
    if not provider or not namespace or not kind:
        return None
    row = db.execute(
        'SELECT id FROM main.item WHERE born_provider=? AND born_namespace=? AND born_key=? AND kind=?',
        (provider, namespace, key, kind),
    ).fetchone()
    if row is not None:
        return items._merged_target(db, row[0])
    if has_catalogue(db):
        row = db.execute(
            'SELECT id FROM catalogue.item WHERE born_provider=? AND born_namespace=? AND born_key=? AND kind=? '
            'AND retired_at IS NULL AND id NOT IN (SELECT id FROM main.item)',
            (provider, namespace, key, kind),
        ).fetchone()
        if row is not None:
            return row[0]
    return None


def resolve_color(db, ref):
    """Return the colour id in main or catalogue for an export colour ref, or None."""
    if not isinstance(ref, dict) or ref.get('local'):
        return None
    provider, key = ref.get('provider'), ref.get('key')
    if not provider or key is None or key == '':
        return None
    row = db.execute(
        'SELECT id FROM main.color WHERE born_provider=? AND born_key=?',
        (provider, key),
    ).fetchone()
    if row is not None:
        return row[0]
    if has_catalogue(db):
        row = db.execute(
            'SELECT id FROM catalogue.color WHERE born_provider=? AND born_key=?',
            (provider, key),
        ).fetchone()
        if row is not None:
            return row[0]
    return None


def _norm(value, is_bool=False):
    if is_bool:
        return bool(value) if value is not None else False
    if value == '':
        return None
    if isinstance(value, bool):
        return int(value)
    return value


def _item_sig(ref):
    if not isinstance(ref, dict):
        return None
    key = ref.get('key')
    return (ref.get('provider'), ref.get('namespace'), key, bool(ref.get('local')), ref.get('kind'),
            ref.get('name') if key is None else None)


def _color_sig(ref):
    if ref is None:
        return None
    if not isinstance(ref, dict):
        return ('invalid',)
    return (ref.get('provider'), ref.get('key'))


def _row_name(row):
    if row.get('name') is not None:
        return row['name']
    item = row.get('item')
    if isinstance(item, dict):
        key, title = item.get('key'), item.get('name')
        if key and title:
            return f'{key} {title}'
        return title or key or row.get('id') or ''
    return row.get('id') or ''


def _order_storage(rows):
    """Order storage rows parents-first so child rows see planned parents."""
    by_id = {r['id']: r for r in rows if isinstance(r.get('id'), str)}
    ordered, done, remaining = [], set(), list(rows)
    while remaining:
        ready = [r for r in remaining if r.get('parent_id') not in by_id or r.get('parent_id') in done]
        if not ready:
            ready = [remaining[0]]
        ready_objs = {id(r) for r in ready}
        for r in ready:
            ordered.append(r)
            if isinstance(r.get('id'), str):
                done.add(r['id'])
        remaining = [r for r in remaining if id(r) not in ready_objs]
    return ordered


def _existing_rows(db, table):
    cols = ['id', *PLAIN_FIELDS[table], 'archived_at']
    if table in ('copy', 'stock', 'wish'):
        cols.append('item_id')
    if table in ('stock', 'wish'):
        cols.append('color_id')
    return {r['id']: dict(r) for r in db.execute(f"SELECT {', '.join(cols)} FROM main.{table}")}


def _differs(table, row, existing, main_items, main_colors):
    diffs = [f for f in PLAIN_FIELDS[table] if _norm(existing[f], f in BOOL_FIELDS) != _norm(row.get(f), f in BOOL_FIELDS)]
    if table in ('copy', 'stock', 'wish'):
        if _item_sig(main_items.get(existing['item_id'])) != _item_sig(row.get('item')):
            diffs.append('item')
    if table in ('stock', 'wish'):
        live_color = main_colors.get(existing['color_id']) if existing['color_id'] is not None else None
        if _color_sig(live_color) != _color_sig(row.get('color')):
            diffs.append('color')
    if existing['archived_at'] is not None:
        diffs.append('archived_at')
    return diffs


def _count_unmatched_lines(table, row, find_item, find_color):
    unmatched = 0
    if table == 'copy':
        lines = row.get('lines')
        if not isinstance(lines, dict):
            return 0
        for fig in lines.get('figures') or ():
            if not isinstance(fig, dict) or find_item(fig.get('item')) is None:
                unmatched += 1
        for part in lines.get('parts') or ():
            if not isinstance(part, dict):
                unmatched += 1
                continue
            bad_fig = part.get('figure') is not None and find_item(part.get('figure')) is None
            if find_item(part.get('item')) is None or find_color(part.get('color')) is None or bad_fig:
                unmatched += 1
    elif table == 'stock':
        lines = row.get('lines')
        if not isinstance(lines, list):
            return 0
        for part in lines:
            if not isinstance(part, dict) or find_item(part.get('item')) is None or find_color(part.get('color')) is None:
                unmatched += 1
    return unmatched


def _value_problem(table, row):
    """Name a value the store would refuse, so a row is never promised as new when it cannot be written."""
    def whole(name, low=0):
        value = row.get(name)
        return value is None or (type(value) is int and value >= low)
    if table in ('stock', 'wish'):
        kinds = ('set', 'part', 'minifigure', 'instructions', 'box', 'gear', 'book', 'catalog') if table == 'wish' else \
            ('part', 'minifigure', 'instructions', 'box', 'gear', 'book', 'catalog')
        if row.get('kind') not in kinds:
            return 'This kind of row cannot be imported here'
        if not whole('quantity', 1 if table == 'wish' else 0):
            return 'Quantity must be a whole number'
        if (row.get('kind') == 'part') != (row.get('color') is not None):
            return 'Only a part has a colour'
    if table == 'stock':
        if not whole('missing') or not whole('damaged'):
            return 'Missing and damaged must be whole numbers'
        if type(row.get('quantity')) is int and type(row.get('missing')) is int and row['missing'] > row['quantity']:
            return 'Missing is more than the quantity'
    if table in ('copy', 'stock') and row.get('purchase_price') is not None and not row.get('purchase_currency'):
        return 'A price needs its currency'
    return None


def _imported(db):
    """File row ids an earlier, not undone own-file import placed here (the store mints a copy's id, so the file's id is only in the receipt)."""
    found = set()
    for row in db.execute("""SELECT e.new_value FROM main.event e WHERE e.entity_kind='import' AND e.field='receipt'
                             AND NOT EXISTS(SELECT 1 FROM main.event_undo u WHERE u.event_id=e.id)"""):
        receipt = json.loads(row[0])
        if receipt.get('source') == SOURCE:
            found.update(receipt.get('origin', {}))
    return found


def _classify(db, parsed_tables, chosen):
    """Classify rows against the live store and return counts, rows, new entries and resolvers."""
    selected_tables = [t for t in WRITE_ORDER if TABLE_SECTION[t] in chosen]
    live_ids = {
        t: {r[0] for r in db.execute(f'SELECT id FROM main.{t} WHERE archived_at IS NULL')}
        for t in ('storage', 'place', 'lot', 'wishlist')
    }
    need_refs = any(t in ('copy', 'stock', 'wish') for t in selected_tables)
    main_items = own_export._items(db) if need_refs else {}
    main_colors = own_export._colors(db) if need_refs else {}
    item_cache, color_cache = {}, {}

    def find_item(ref):
        if not isinstance(ref, dict):
            return None
        key = (ref.get('provider'), ref.get('namespace'), ref.get('key'), ref.get('kind'), bool(ref.get('local')))
        if key not in item_cache:
            item_cache[key] = resolve_item(db, ref)
        return item_cache[key]

    def find_color(ref):
        if not isinstance(ref, dict):
            return None
        key = (ref.get('provider'), ref.get('key'), bool(ref.get('local')))
        if key not in color_cache:
            color_cache[key] = resolve_color(db, ref)
        return color_cache[key]

    imported = _imported(db)
    planned_new = {t: set() for t in WRITE_ORDER}
    counts, rows_out, new_rows, unresolved = {}, {}, {}, []
    for table in selected_tables:
        table_rows = list(parsed_tables.get(table) or ())
        if table == 'storage':
            table_rows = _order_storage(table_rows)
        existing = _existing_rows(db, table)
        t_counts = {'new': 0, 'here': 0, 'difference': 0, 'unresolved': 0}
        if table in ('copy', 'stock'):
            t_counts['lines_unmatched'] = 0
        t_rows, t_new = [], []

        def record(row, status, **extra):
            t_counts[status] += 1
            if status == 'unresolved' and len(unresolved) < ROW_CAP:
                unresolved.append({'table': table, 'id': row.get('id'), 'reason': extra.get('reason')})
            if status != 'new' and len(t_rows) < ROW_CAP:
                t_rows.append({'id': row.get('id'), 'name': _row_name(row), 'status': status, **extra})

        seen_ids = set()
        for row in table_rows:
            row_id = row.get('id')
            if not isinstance(row_id, str) or not row_id:
                record(row, 'unresolved', reason='Missing row id')
                continue
            if row_id in seen_ids:
                record(row, 'unresolved', reason='The same id twice in the file')
                continue
            seen_ids.add(row_id)
            if row_id in imported and row_id not in existing:
                record(row, 'here')
                continue
            if row_id in existing:
                diffs = _differs(table, row, existing[row_id], main_items, main_colors)
                if diffs:
                    record(row, 'difference', differs=diffs)
                else:
                    record(row, 'here')
                continue
            reason = None
            for col, parent_table, required in PARENTS.get(table, ()):
                pid = row.get(col)
                if pid is None:
                    if required:
                        reason = f'Missing {parent_table}'
                        break
                elif pid not in live_ids[parent_table] and pid not in planned_new[parent_table]:
                    reason = f'Parent {parent_table} not found'
                    break
            if reason is None:
                reason = _value_problem(table, row)
            item_id = color_id = None
            if reason is None and table in ('copy', 'stock', 'wish'):
                item_ref = row.get('item')
                if not isinstance(item_ref, dict) or item_ref.get('key') is None or item_ref.get('key') == '' or item_ref.get('local'):
                    reason = 'No number to find it by'
                else:
                    item_id = find_item(item_ref)
                    if item_id is None:
                        reason = f"Item {item_ref.get('key')} not found in this catalogue"
                    elif table == 'copy' and item_ref.get('kind') != 'set':
                        reason = 'Copy item must be a set'
                    elif table in ('stock', 'wish') and row.get('kind') and item_ref.get('kind') != row.get('kind'):
                        reason = f"Item kind {item_ref.get('kind')} does not match {row.get('kind')}"
            if reason is None and table in ('stock', 'wish'):
                color_ref = row.get('color')
                if color_ref is not None:
                    color_id = find_color(color_ref)
                    if color_id is None:
                        reason = 'Colour not found in this catalogue'
                elif row.get('kind') == 'part':
                    reason = 'Part requires a colour'
            if reason is not None:
                record(row, 'unresolved', reason=reason)
                continue
            record(row, 'new')
            planned_new[table].add(row_id)
            t_new.append({'row': row, 'item_id': item_id, 'color_id': color_id})
            if table in ('copy', 'stock'):
                t_counts['lines_unmatched'] += _count_unmatched_lines(table, row, find_item, find_color)
        counts[table] = t_counts
        rows_out[table] = t_rows
        new_rows[table] = t_new
    return {
        'counts': counts,
        'rows': rows_out,
        'new': new_rows,
        'unresolved': unresolved,
        'find_item': find_item,
        'find_color': find_color,
    }


def plan(db, content, sections=None, store=True):
    """Classify every row of a Brick Work export file without writing to the collection."""
    parsed = read_zip(content)
    manifest = parsed['manifest']
    if sections is None:
        chosen = [s for s in own_export.SECTIONS if s in manifest['sections']]
    else:
        chosen = own_export._parse_sections(sections)
        missing = [s for s in chosen if s not in manifest['sections']]
        if missing:
            raise errors.ValidationFailed('Section not in export file: ' + ', '.join(missing))
    selected_tables = [t for t in WRITE_ORDER if TABLE_SECTION[t] in chosen]
    kept_tables = {}
    for table in selected_tables:
        if table not in parsed['tables']:
            raise errors.ValidationFailed(f'Export file is missing data/{table}.jsonl')
        table_rows = list(parsed['tables'][table])
        declared = (manifest.get('counts') or {}).get(table)
        if type(declared) is int and declared != len(table_rows):
            raise errors.ValidationFailed(f'data/{table}.jsonl holds {len(table_rows)} rows and the manifest says {declared}')
        if table == 'storage':
            table_rows = _order_storage(table_rows)
        kept_tables[table] = table_rows
    classified = _classify(db, kept_tables, chosen)
    result = {
        'id': uuid4().hex,
        'direction': DIRECTION,
        'created_at': now().isoformat(),
        'source': 'file',
        'sections': chosen,
        'manifest': manifest,
        'counts': classified['counts'],
        'rows': classified['rows'],
        'tables': kept_tables,
    }
    if store:
        sync._save_plan(db, result)
    return result


def _price_pair(amount, currency):
    if amount is None or not currency:
        return None, None
    return amount, currency


def _insert_row(db, table, columns, via, actor, *, read_back=False):
    cols = ', '.join(columns)
    marks = ', '.join('?' * len(columns))
    db.execute(f'INSERT INTO main.{table}({cols}) VALUES({marks})', tuple(columns.values()))
    payload = dict(db.execute(f'SELECT * FROM main.{table} WHERE id=?', (columns['id'],)).fetchone()) if read_back else columns
    audit(db, f"{table}:{columns['id']}", 'created', None, payload, via=via, actor=actor)


def _write_plain_tables(db, new_rows, receipt, stamp, via, actor):
    """Insert new storage, place, flag, lot and wishlist rows keeping free uuids."""
    for entry in new_rows.get('storage', ()):
        row = entry['row']
        columns = {'id': row['id'], 'name': row['name'], 'parent_id': row.get('parent_id'), 'note': row.get('note'), 'created_at': stamp}
        if row.get('type') is not None:
            columns['type'] = row['type']
        _insert_row(db, 'storage', columns, via, actor)
        receipt['storages'].append(row['id'])
    for entry in new_rows.get('place', ()):
        row = entry['row']
        columns = {'id': row['id'], 'name': row['name'], 'created_at': stamp}
        if row.get('kind') is not None:
            columns['kind'] = row['kind']
        _insert_row(db, 'place', columns, via, actor)
        receipt['places'].append(row['id'])
    existing_flags = {
        (bricktracker._norm(r['name']), r['kind']): r['id']
        for r in db.execute('SELECT id, name, kind FROM main.flag WHERE archived_at IS NULL')
    }
    extra_skipped = 0
    for entry in new_rows.get('flag', ()):
        row = entry['row']
        key = (bricktracker._norm(row['name']), row.get('kind'))
        if key in existing_flags:
            extra_skipped += 1
            continue
        columns = {
            'id': row['id'], 'name': row['name'],
            'shown_on_grid': int(bool(row.get('shown_on_grid'))),
            'system': int(bool(row.get('system'))),
            'created_at': stamp,
        }
        if row.get('kind') is not None:
            columns['kind'] = row['kind']
        _insert_row(db, 'flag', columns, via, actor)
        receipt['flags'].append(row['id'])
        existing_flags[key] = row['id']
    for entry in new_rows.get('lot', ()):
        row = entry['row']
        price, currency = _price_pair(row.get('purchase_price'), row.get('purchase_currency'))
        columns = {
            'id': row['id'], 'name': row['name'], 'note': row.get('note'),
            'storage_id': row.get('storage_id'), 'place_id': row.get('place_id'),
            'purchase_date': row.get('purchase_date'), 'purchase_price': price,
            'purchase_currency': currency, 'created_at': stamp, 'updated_at': stamp,
        }
        _insert_row(db, 'lot', columns, via, actor, read_back=True)
        receipt['lots'].append(row['id'])
    wishlist_map = {'default': 'default'}
    for entry in new_rows.get('wishlist', ()):
        row = entry['row']
        columns = {'id': row['id'], 'name': row['name'], 'note': row.get('note'), 'created_at': stamp}
        if row.get('sort') is not None:
            columns['sort'] = row['sort']
        _insert_row(db, 'wishlist', columns, via, actor, read_back=True)
        receipt['wishlists'].append(row['id'])
        wishlist_map[row['id']] = row['id']
    return wishlist_map, extra_skipped


def _apply_copy_marks(db, copy_id, lines, find_item, find_color):
    """Apply figure and part marks from the file to a newly created copy."""
    if not isinstance(lines, dict):
        return 0
    unmatched = 0
    for fig in lines.get('figures') or ():
        fig_item = find_item(fig.get('item')) if isinstance(fig, dict) else None
        if fig_item is None:
            unmatched += 1
            continue
        row = db.execute(
            'SELECT id, quantity FROM main.copy_figure WHERE copy_id=? AND item_id=? AND retired_at IS NULL',
            (copy_id, fig_item),
        ).fetchone()
        if row is None:
            unmatched += 1
            continue
        missing = min(max(int(fig.get('missing') or 0), 0), row['quantity'])
        db.execute('UPDATE main.copy_figure SET missing=? WHERE id=?', (missing, row['id']))
    marks = []
    for part in lines.get('parts') or ():
        if not isinstance(part, dict):
            unmatched += 1
            continue
        part_id = find_item(part.get('item'))
        color_id = find_color(part.get('color'))
        fig_ref = part.get('figure')
        fig_id = find_item(fig_ref) if fig_ref is not None else None
        if part_id is None or color_id is None or (fig_ref is not None and fig_id is None):
            unmatched += 1
            continue
        marks.append(dict(
            part=part_id, colour=color_id, spare=int(bool(part.get('spare'))), figure=fig_id,
            missing=max(int(part.get('missing') or 0), 0),
            damaged=max(int(part.get('damaged') or 0), 0),
            checked=int(bool(part.get('checked'))),
        ))
    unmatched += len(bricktracker._mark(db, 'copy_part', copy_id, marks))
    return unmatched


def _write_copy(db, entry, receipt, flag_rows, find_item, find_color, via, actor):
    """Create one copy via the store writer, set its fields and marks, and record its guard."""
    from . import add
    row, item_id = entry['row'], entry['item_id']
    items.ensure(db, item_id)
    pass_comp = row.get('completeness') if row.get('completeness_source') is None else None
    copy_id, waiting = add._add_copy(
        db,
        dict(item_id=item_id, condition=row.get('condition'), completeness=pass_comp, note=row.get('note')),
        via,
        actor,
    )
    p_price, p_curr = _price_pair(row.get('purchase_price'), row.get('purchase_currency'))
    c_val, c_curr = _price_pair(row.get('current_value'), row.get('current_value_currency'))
    updates = {
        'storage_id': row.get('storage_id'), 'place_id': row.get('place_id'),
        'purchase_date': row.get('purchase_date'), 'purchase_price': p_price, 'purchase_currency': p_curr,
        'current_value': c_val, 'current_value_currency': c_curr,
        'pinned': int(bool(row.get('pinned'))), 'note': row.get('note'), 'checked_by': row.get('checked_by'),
    }
    if row.get('completeness') is None:
        updates['completeness'] = None
        updates['completeness_source'] = None
    elif row.get('completeness_source') is not None:
        updates['completeness'] = row['completeness']
        updates['completeness_source'] = row['completeness_source']
    db.execute(f"UPDATE main.copy SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", (*updates.values(), copy_id))
    unmatched = _apply_copy_marks(db, copy_id, row.get('lines'), find_item, find_color)
    flag_rows('copy_flag', 'copy_id', copy_id, row.get('flags'))
    receipt['copies'].append(copy_id)
    receipt['origin'][row['id']] = copy_id
    receipt['guards'][copy_id] = dict(
        row=dict(db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()),
        lines=bricktracker._line_digest(db, copy_id),
        flags=bricktracker._flag_ids(db, copy_id),
    )
    if waiting:
        receipt['pending'].append(dict(waiting, copy_id=copy_id))
    return unmatched


def _finish_stock(db, change, row, find_item, find_color):
    """Set stock fields `add_loose` does not take, apply figure line marks and refresh `after`."""
    unmatched = 0
    checked = row.get('checked')
    checked_val = None if checked is None else int(bool(checked))
    if change['created']:
        price, currency = _price_pair(row.get('purchase_price'), row.get('purchase_currency'))
        db.execute(
            'UPDATE main.stock SET place_id=?, purchase_date=?, purchase_price=?, purchase_currency=?, '
            'missing=?, damaged=?, checked=? WHERE id=?',
            (row.get('place_id'), row.get('purchase_date'), price, currency,
             row.get('missing'), row.get('damaged'), checked_val, change['id']),
        )
        lines = row.get('lines')
        if isinstance(lines, list) and lines:
            marks = []
            for part in lines:
                part_id = find_item(part.get('item')) if isinstance(part, dict) else None
                color_id = find_color(part.get('color')) if isinstance(part, dict) else None
                if part_id is None or color_id is None:
                    unmatched += 1
                    continue
                marks.append(dict(
                    part=part_id, colour=color_id, spare=int(bool(part.get('spare'))), figure=None,
                    missing=max(int(part.get('missing') or 0), 0),
                    damaged=max(int(part.get('damaged') or 0), 0),
                    checked=int(bool(part.get('checked'))),
                ))
            unmatched += len(bricktracker._mark(db, 'stock_part', change['id'], marks))
            if db.execute('SELECT 1 FROM main.stock_part WHERE stock_id=? AND retired_at IS NULL LIMIT 1', (change['id'],)).fetchone():
                summary = db.execute(
                    'SELECT sum(missing), sum(damaged), min(checked) FROM main.stock_part WHERE stock_id=? AND retired_at IS NULL',
                    (change['id'],),
                ).fetchone()
                db.execute('UPDATE main.stock SET missing=?, damaged=?, checked=? WHERE id=?', (*summary, change['id']))
            change['parts'] = stock.part_digest(db, change['id'])
    elif any(row.get(k) is not None for k in ('missing', 'damaged', 'checked')):
        merged = stock.merge_state(
            change['before'],
            {'missing': row.get('missing'), 'damaged': row.get('damaged'), 'checked': checked_val},
            change['after']['quantity'],
        )
        db.execute('UPDATE main.stock SET missing=?, damaged=?, checked=? WHERE id=?',
                   (merged['missing'], merged['damaged'], merged['checked'], change['id']))
    change['after'] = dict(db.execute('SELECT * FROM main.stock WHERE id=?', (change['id'],)).fetchone())
    return unmatched


def _finish_wish(db, wish_entry, row):
    """Set extra fields on a newly created wish and refresh `after` for Undo."""
    if not wish_entry['created']:
        return
    m_price, m_curr = _price_pair(row.get('max_price'), row.get('max_price_currency'))
    b_price, b_curr = _price_pair(row.get('max_price_boxed'), row.get('max_price_boxed_currency'))
    updates = {
        'max_price': m_price, 'max_price_currency': m_curr, 'note': row.get('note'),
        'max_price_boxed': b_price, 'max_price_boxed_currency': b_curr,
    }
    if row.get('qty_filled_manual') is not None:
        updates['qty_filled_manual'] = row['qty_filled_manual']
    db.execute(f"UPDATE main.wish SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?", (*updates.values(), wish_entry['id']))
    wish_entry['after'] = dict(db.execute('SELECT * FROM main.wish WHERE id=?', (wish_entry['id'],)).fetchone())


def apply(db, plan_id, *, via=None, actor=None, queue=True):
    """Apply a stored own-file import plan in one transaction and record an undoable receipt."""
    from . import add, pictures, plans, wishlists
    from .pipeline import queue_new_items
    saved = sync.load_plan(db, plan_id, DIRECTION)
    done = plans.applied(db, 'import', plan_id)
    if done:
        return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
    if via is None:
        via, actor = origin()
    stamp = store_now()
    receipt = dict(
        plan=plan_id, source=SOURCE, origin={}, storages=[], places=[], flags=[], lots=[], wishlists=[],
        copies=[], guards={}, stock=[], wishes=[], copy_flags=[], stock_flags=[], wish_flags=[],
        unresolved=[], pending=[], jobs=[],
    )
    with transaction(db), origins.adding(SOURCE):
        done = plans.applied(db, 'import', plan_id)
        if done:
            return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
        classified = _classify(db, saved['tables'], saved['sections'])
        live_counts = classified['counts']
        new_rows = classified['new']
        find_item, find_color = classified['find_item'], classified['find_color']
        receipt['unresolved'] = classified['unresolved']
        wishlist_map, extra_skipped = _write_plain_tables(db, new_rows, receipt, stamp, via, actor)
        flag_by_name, flag_by_norm = {}, {}
        for r in db.execute('SELECT id, name FROM main.flag WHERE archived_at IS NULL ORDER BY id'):
            flag_by_name.setdefault(r['name'], r['id'])
            flag_by_norm.setdefault(bricktracker._norm(r['name']), r['id'])

        def flag_rows(table, column, row_id, names):
            for name in names or ():
                if not isinstance(name, str):
                    continue
                target = flag_by_name.get(name) or flag_by_norm.get(bricktracker._norm(name))
                if target and not db.execute(f'SELECT 1 FROM main.{table} WHERE {column}=? AND flag_id=?', (row_id, target)).fetchone():
                    db.execute(f'INSERT INTO main.{table}({column}, flag_id) VALUES(?, ?)', (row_id, target))
                    receipt[table + 's'].append([row_id, target])

        touched, lines_unmatched = set(), 0
        for entry in new_rows.get('copy', ()):
            touched.add(entry['item_id'])
            lines_unmatched += _write_copy(db, entry, receipt, flag_rows, find_item, find_color, via, actor)
        for entry in new_rows.get('stock', ()):
            row, item_id, color_id = entry['row'], entry['item_id'], entry['color_id']
            items.ensure(db, item_id)
            touched.add(item_id)
            change = stock.add_loose(
                db, item_id=item_id, color_id=color_id, quantity=row['quantity'], condition=row.get('condition'),
                lot_id=row.get('lot_id'), storage_id=row.get('storage_id'), note=row.get('note'), via=via, actor=actor,
            )
            lines_unmatched += _finish_stock(db, change, row, find_item, find_color)
            flag_rows('stock_flag', 'stock_id', change['id'], row.get('flags'))
            receipt['stock'].append(change)
            receipt['origin'][row['id']] = change['id']
        if new_rows.get('wish'):
            wishlists.require(db, 'default')
        for entry in new_rows.get('wish', ()):
            row, item_id, color_id = entry['row'], entry['item_id'], entry['color_id']
            items.ensure(db, item_id)
            touched.add(item_id)
            raw_wl = row.get('wishlist_id')
            list_id = 'default' if raw_wl == 'default' else wishlist_map.get(raw_wl, raw_wl)
            kind = row.get('kind') or db.execute('SELECT kind FROM main.item WHERE id=?', (item_id,)).fetchone()['kind']
            scratch = {}
            add._add_wish(
                db,
                dict(list_id=list_id, item_id=item_id, kind=kind, color_id=color_id,
                     quantity=row['quantity'], condition=row.get('condition') or 'any', decision='another'),
                scratch, via, actor,
            )
            wish_entry = scratch['wish']
            _finish_wish(db, wish_entry, row)
            receipt['wishes'].append(wish_entry)
            receipt['origin'][row['id']] = wish_entry['id']
            flag_rows('wish_flag', 'wish_id', wish_entry['id'], row.get('flags'))
        receipt['jobs'] = queue_new_items(db, touched) if queue else []
        counts = dict(
            storages=len(receipt['storages']),
            places=len(receipt['places']),
            flags=len(receipt['flags']),
            lots=len(receipt['lots']),
            wishlists=len(receipt['wishlists']),
            copies=len(receipt['copies']),
            stock_lines=len(receipt['stock']),
            stock=sum(c['quantity'] for c in receipt['stock']),
            wishes=len(receipt['wishes']),
            skipped=sum(c['here'] for c in live_counts.values()) + extra_skipped,
            differences=sum(c['difference'] for c in live_counts.values()),
            unresolved=sum(c['unresolved'] for c in live_counts.values()),
            lines_unmatched=lines_unmatched,
        )
        receipt['counts'] = counts
        audit(db, 'import:' + plan_id, 'receipt', None, receipt, via=via, actor=actor)
        event = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        plans.mark(db, 'import', plan_id, dict(event_id=event, counts=counts, at=stamp),
                   source=SOURCE, created_at=saved['created_at'])
    if queue:
        pictures.queue_missing(db, touched, via=via, actor=actor)
    return dict(event_id=event, already_applied=False, counts=counts)


def _check_undo_guards(db, r):
    """Refuse Undo when any copy, stock row or wish from this import changed since."""
    for entry in {e['id']: e for e in r['wishes']}.values():
        row = db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()
        if row is None or dict(row) != as_current('wish', entry['after']):
            raise ValueError(CHANGED_ERROR)
    for change in {c['id']: c for c in r['stock']}.values():
        row = db.execute('SELECT * FROM main.stock WHERE id=?', (change['id'],)).fetchone()
        if row is None or dict(row) != as_current('stock', change['after']):
            raise ValueError(CHANGED_ERROR)
        if change['created'] and (stock.dependents(db, change['id']) or (change.get('parts') is not None and stock.part_digest(db, change['id']) != change['parts'])):
            raise ValueError(CHANGED_ERROR)
    for copy_id in r['copies']:
        guard = r['guards'][copy_id]
        row = db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()
        if row is None:
            raise ValueError(CHANGED_ERROR)
        if row['archived_at'] is None and (
            dict(row) != as_current('copy', guard['row'])
            or bricktracker._line_digest(db, copy_id) != guard['lines']
            or bricktracker._flag_ids(db, copy_id) != guard['flags']
            or any(db.execute(sql, (copy_id,)).fetchone() for sql in (
                'SELECT 1 FROM main.part_check WHERE copy_id=? LIMIT 1',
                'SELECT 1 FROM main.stock_transfer WHERE copy_id=? LIMIT 1',
                'SELECT 1 FROM main.photo WHERE copy_id=? AND archived_at IS NULL LIMIT 1',
                'SELECT 1 FROM main.allocation WHERE copy_id=? LIMIT 1',
            ))
        ):
            raise ValueError(CHANGED_ERROR)


def _undo(db, event, via, actor):
    """Reverse one own-file import; refuses whole when any imported row changed since."""
    r = json.loads(event['new_value'])
    stamp = store_now()
    _check_undo_guards(db, r)
    for entry in reversed(r['wishes']):
        row = db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()
        if entry['created']:
            db.execute('UPDATE main.wish SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, entry['id']))
        else:
            b = entry['before']
            db.execute('UPDATE main.wish SET quantity=?, updated_at=? WHERE id=?', (b['quantity'], b['updated_at'], entry['id']))
        audit(db, 'wish:' + entry['id'], 'undo_import', dict(row),
              dict(db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()), via=via, actor=actor)
    for change in reversed(r['stock']):
        stock.undo_added(db, change, via=via, actor=actor)
    for table, col, key in (('copy_flag', 'copy_id', 'copy_flags'),
                            ('stock_flag', 'stock_id', 'stock_flags'),
                            ('wish_flag', 'wish_id', 'wish_flags')):
        for owner_id, flag_id in r.get(key, ()):
            db.execute(f'DELETE FROM main.{table} WHERE {col}=? AND flag_id=?', (owner_id, flag_id))
    for copy_id in reversed(r['copies']):
        row = db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()
        if row['archived_at'] is not None:
            continue
        if row['inventory_pending']:
            pending.cancel_pending_in(db, copy_id, via=via, actor=actor)
        db.execute('UPDATE main.copy SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, copy_id))
        audit(db, 'copy:' + copy_id, 'archived_at', None, stamp, via=via, actor=actor)
    for lot in r['lots']:
        if not bricktracker._used(db, 'SELECT 1 FROM main.stock WHERE lot_id=? AND archived_at IS NULL LIMIT 1', lot):
            db.execute('UPDATE main.lot SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, lot))
    for wl in r.get('wishlists', ()):
        if not bricktracker._used(db, 'SELECT 1 FROM main.wish WHERE wishlist_id=? AND archived_at IS NULL LIMIT 1', wl):
            db.execute('UPDATE main.wishlist SET archived_at=? WHERE id=?', (stamp, wl))
    for ident in r['places']:
        if not any(bricktracker._used(db, f'SELECT 1 FROM main.{t} WHERE place_id=? AND archived_at IS NULL LIMIT 1', ident)
                   for t in ('copy', 'stock', 'lot')):
            db.execute('UPDATE main.place SET archived_at=? WHERE id=?', (stamp, ident))
    for ident in reversed(r['storages']):
        if not any(bricktracker._used(db, sql, ident) for sql in (
            'SELECT 1 FROM main.copy WHERE storage_id=? AND archived_at IS NULL LIMIT 1',
            'SELECT 1 FROM main.stock WHERE storage_id=? AND archived_at IS NULL LIMIT 1',
            'SELECT 1 FROM main.lot WHERE storage_id=? AND archived_at IS NULL LIMIT 1',
            'SELECT 1 FROM main.storage WHERE parent_id=? AND archived_at IS NULL LIMIT 1',
        )):
            db.execute('UPDATE main.storage SET archived_at=? WHERE id=?', (stamp, ident))
    for ident in r['flags']:
        if not any(bricktracker._used(db, sql, ident) for sql in (
            'SELECT 1 FROM main.copy_flag f JOIN main.copy c ON c.id=f.copy_id WHERE f.flag_id=? AND c.archived_at IS NULL LIMIT 1',
            'SELECT 1 FROM main.stock_flag f JOIN main.stock c ON c.id=f.stock_id WHERE f.flag_id=? AND c.archived_at IS NULL LIMIT 1',
            'SELECT 1 FROM main.wish_flag f JOIN main.wish c ON c.id=f.wish_id WHERE f.flag_id=? AND c.archived_at IS NULL LIMIT 1',
        )):
            db.execute('UPDATE main.flag SET archived_at=? WHERE id=?', (stamp, ident))
    audit(db, 'import:' + r['plan'], 'undo', None, {'undoes': event['id']}, via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


def undo(db, event_id):
    """Reverse one own-file import; refuses over later edits."""
    return undoing.undo_event(db, event_id)
