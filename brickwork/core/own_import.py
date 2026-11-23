"""Import plan for Brick Work's own portable zip export (ADR 0040, #524)."""
import io
import json
from uuid import uuid4
import zipfile
import zlib

from ..store4.connect import has_catalogue
from . import errors, items, own_export, sync
from .sources.base import now

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_MEMBERS = 40
MAX_RATIO = 200
ROW_CAP = 200
DIRECTION = 'brickwork_file'

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

    planned_new = {t: set() for t in WRITE_ORDER}
    counts, rows_out, kept_tables = {}, {}, {}
    for table in selected_tables:
        table_rows = list(parsed['tables'].get(table, []))
        if table == 'storage':
            table_rows = _order_storage(table_rows)
        kept_tables[table] = table_rows
        existing = _existing_rows(db, table)
        t_counts = {'new': 0, 'here': 0, 'difference': 0, 'unresolved': 0}
        if table in ('copy', 'stock'):
            t_counts['lines_unmatched'] = 0
        t_rows = []

        def record(row, status, **extra):
            t_counts[status] += 1
            if status != 'new' and len(t_rows) < ROW_CAP:
                t_rows.append({'id': row.get('id'), 'name': _row_name(row), 'status': status, **extra})

        for row in table_rows:
            row_id = row.get('id')
            if not isinstance(row_id, str) or not row_id:
                record(row, 'unresolved', reason='Missing row id')
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
            if reason is None and table in ('copy', 'stock', 'wish'):
                item_ref = row.get('item')
                if not isinstance(item_ref, dict) or item_ref.get('key') is None or item_ref.get('key') == '' or item_ref.get('local'):
                    reason = 'No number to find it by'
                elif find_item(item_ref) is None:
                    reason = f"Item {item_ref.get('key')} not found in this catalogue"
                elif table == 'copy' and item_ref.get('kind') != 'set':
                    reason = 'Copy item must be a set'
                elif table in ('stock', 'wish') and row.get('kind') and item_ref.get('kind') != row.get('kind'):
                    reason = f"Item kind {item_ref.get('kind')} does not match {row.get('kind')}"
            if reason is None and table in ('stock', 'wish'):
                color_ref = row.get('color')
                if color_ref is not None:
                    if find_color(color_ref) is None:
                        reason = 'Colour not found in this catalogue'
                elif row.get('kind') == 'part':
                    reason = 'Part requires a colour'
            if reason is not None:
                record(row, 'unresolved', reason=reason)
                continue
            record(row, 'new')
            planned_new[table].add(row_id)
            if table in ('copy', 'stock'):
                t_counts['lines_unmatched'] += _count_unmatched_lines(table, row, find_item, find_color)
        counts[table] = t_counts
        rows_out[table] = t_rows
    result = {
        'id': uuid4().hex,
        'direction': DIRECTION,
        'created_at': now().isoformat(),
        'source': 'file',
        'sections': chosen,
        'manifest': manifest,
        'counts': counts,
        'rows': rows_out,
        'tables': kept_tables,
    }
    if store:
        sync._save_plan(db, result)
    return result
