"""Brick Work's own portable zip export (ADR 0040, #524)."""
import io
import json
import zipfile

from . import errors
from .secrets import secret_values
from .sources.base import redact, stamp

FORMAT = 'brickwork-export'
FORMAT_VERSION = 1
SECTIONS = ('places', 'flags', 'collection', 'wishes')


def _parse_sections(sections):
    if sections is None:
        return list(SECTIONS)
    raw = [s.strip() for s in sections.split(',')] if isinstance(sections, str) else [str(s).strip() for s in sections]
    if not raw or any(not s for s in raw):
        raise errors.ValidationFailed('Choose sections from: ' + ', '.join(SECTIONS))
    unknown = [s for s in raw if s not in SECTIONS]
    if unknown:
        raise errors.ValidationFailed('Unknown export section: ' + ', '.join(unknown))
    wanted = set(raw)
    return [s for s in SECTIONS if s in wanted]


def _note(text, secrets):
    return None if text is None else redact(text, secrets)


def _item_key(ref):
    if ref is None:
        return ('', '', '', '', '')
    return (ref['provider'] or '', ref['namespace'] or '', ref['key'] or '', ref['kind'] or '', ref['name'] or '')


def _color_key(ref):
    if ref is None:
        return ('', '', '')
    return (ref['provider'] or '', ref['key'] or '', ref['name'] or '')


def _schema_version(db):
    row = db.execute("SELECT value FROM main.meta WHERE key='schema_version'").fetchone()
    return row[0] if row else None


def _items(db):
    out = {}
    for r in db.execute('SELECT id, origin, kind, name, born_provider, born_namespace, born_key FROM main.item'):
        out[r['id']] = {
            'provider': r['born_provider'],
            'namespace': r['born_namespace'],
            'key': r['born_key'],
            'local': r['origin'] == 'local',
            'kind': r['kind'],
            'name': r['name'],
        }
    return out


def _colors(db):
    return {
        r['id']: {'provider': r['born_provider'], 'key': r['born_key'], 'name': r['name']}
        for r in db.execute('SELECT id, name, born_provider, born_key FROM main.color')
    }


def _flag_links(db, table, owner_col):
    links = {}
    for r in db.execute(f'''SELECT l.{owner_col} AS owner_id, f.name FROM main.{table} l
                            JOIN main.flag f ON f.id=l.flag_id
                            WHERE f.archived_at IS NULL
                            ORDER BY f.name, f.id'''):
        links.setdefault(r['owner_id'], []).append(r['name'])
    return links


def _storage_rows(db, secrets):
    rows = db.execute('''SELECT id, name, type, parent_id, note, created_at
                         FROM main.storage WHERE archived_at IS NULL ORDER BY id''').fetchall()
    by_id = {r['id']: r for r in rows}
    ordered, done = [], set()
    remaining = sorted(by_id)
    while remaining:
        ready = [i for i in remaining if by_id[i]['parent_id'] not in by_id or by_id[i]['parent_id'] in done]
        looped = not ready
        if looped:
            ready = [remaining[0]]                       # a parent loop: the first row of it is written without its parent
        for i in ready:
            r = by_id[i]
            ordered.append({
                'id': r['id'],
                'name': r['name'],
                'type': r['type'],
                'parent_id': None if looped else r['parent_id'],
                'note': _note(r['note'], secrets),
                'created_at': r['created_at'],
            })
            done.add(i)
        remaining = [i for i in remaining if i not in done]
    return ordered


def _place_rows(db):
    return [
        {'id': r['id'], 'name': r['name'], 'kind': r['kind'], 'created_at': r['created_at']}
        for r in db.execute('SELECT id, name, kind, created_at FROM main.place WHERE archived_at IS NULL ORDER BY id')
    ]


def _flag_rows(db):
    rows = db.execute('''SELECT f.id, f.name, f.kind, f.shown_on_grid, f.system, f.created_at
                         FROM main.flag f
                         WHERE f.archived_at IS NULL AND (
                             EXISTS(SELECT 1 FROM main.copy_flag cf JOIN main.copy c ON c.id=cf.copy_id
                                    WHERE cf.flag_id=f.id AND c.archived_at IS NULL)
                             OR EXISTS(SELECT 1 FROM main.stock_flag sf JOIN main.stock s ON s.id=sf.stock_id
                                       WHERE sf.flag_id=f.id AND s.archived_at IS NULL)
                             OR EXISTS(SELECT 1 FROM main.wish_flag wf JOIN main.wish w ON w.id=wf.wish_id
                                       JOIN main.wishlist wl ON wl.id=w.wishlist_id
                                       WHERE wf.flag_id=f.id AND w.archived_at IS NULL AND wl.archived_at IS NULL))
                         ORDER BY f.id''')
    return [
        {
            'id': r['id'],
            'name': r['name'],
            'kind': r['kind'],
            'shown_on_grid': bool(r['shown_on_grid']),
            'system': bool(r['system']),
            'created_at': r['created_at'],
        }
        for r in rows
    ]


def _lot_rows(db, secrets):
    rows = db.execute('''SELECT id, name, note, storage_id, place_id, purchase_date,
                                purchase_price, purchase_currency, created_at, updated_at
                         FROM main.lot WHERE archived_at IS NULL ORDER BY id''')
    return [
        {
            'id': r['id'], 'name': r['name'], 'note': _note(r['note'], secrets),
            'storage_id': r['storage_id'], 'place_id': r['place_id'],
            'purchase_date': r['purchase_date'], 'purchase_price': r['purchase_price'],
            'purchase_currency': r['purchase_currency'],
            'created_at': r['created_at'], 'updated_at': r['updated_at'],
        }
        for r in rows
    ]


def _copy_rows(db, items, colors, secrets):
    flags = _flag_links(db, 'copy_flag', 'copy_id')
    figures, fig_items = {}, {}
    for r in db.execute('''SELECT cf.id, cf.copy_id, cf.item_id, cf.quantity, cf.missing
                           FROM main.copy_figure cf
                           JOIN main.copy c ON c.id=cf.copy_id
                           WHERE c.archived_at IS NULL AND cf.retired_at IS NULL'''):
        ref = items[r['item_id']]
        fig_items[r['id']] = ref
        figures.setdefault(r['copy_id'], []).append({'item': ref, 'quantity': r['quantity'], 'missing': r['missing']})
    parts = {}
    for r in db.execute('''SELECT cp.copy_id, cp.copy_figure_id, cp.item_id, cp.color_id,
                                  cp.is_spare, cp.quantity, cp.missing, cp.damaged, cp.checked
                           FROM main.copy_part cp
                           JOIN main.copy c ON c.id=cp.copy_id
                           LEFT JOIN main.copy_figure cf ON cf.id=cp.copy_figure_id
                           WHERE c.archived_at IS NULL AND cp.retired_at IS NULL
                             AND (cp.copy_figure_id IS NULL OR cf.retired_at IS NULL)'''):
        parts.setdefault(r['copy_id'], []).append({
            'item': items[r['item_id']], 'color': colors[r['color_id']],
            'figure': fig_items[r['copy_figure_id']] if r['copy_figure_id'] is not None else None,
            'quantity': r['quantity'], 'missing': r['missing'], 'damaged': r['damaged'],
            'checked': bool(r['checked']), 'spare': bool(r['is_spare']),
        })
    for group in figures.values():
        group.sort(key=lambda r: _item_key(r['item']))
    for group in parts.values():
        group.sort(key=lambda r: (_item_key(r['figure']), _item_key(r['item']), _color_key(r['color']), r['spare']))
    rows = db.execute('''SELECT id, item_id, inventory_source, condition, completeness, completeness_source,
                                storage_id, place_id, purchase_date, purchase_price, purchase_currency, note,
                                current_value, current_value_currency, pinned, added_via, created_at, updated_at
                         FROM main.copy WHERE archived_at IS NULL ORDER BY id''')
    return [
        {
            'id': r['id'], 'item': items[r['item_id']], 'list_source': r['inventory_source'],
            'condition': r['condition'], 'completeness': r['completeness'],
            'completeness_source': r['completeness_source'],
            'storage_id': r['storage_id'], 'place_id': r['place_id'],
            'purchase_date': r['purchase_date'], 'purchase_price': r['purchase_price'],
            'purchase_currency': r['purchase_currency'], 'note': _note(r['note'], secrets),
            'current_value': r['current_value'], 'current_value_currency': r['current_value_currency'],
            'pinned': bool(r['pinned']), 'added_via': r['added_via'],
            'created_at': r['created_at'], 'updated_at': r['updated_at'],
            'flags': flags.get(r['id'], []),
            'lines': {'figures': figures.get(r['id'], []), 'parts': parts.get(r['id'], [])},
        }
        for r in rows
    ]


def _stock_rows(db, items, colors, secrets):
    flags = _flag_links(db, 'stock_flag', 'stock_id')
    parts = {}
    for r in db.execute('''SELECT sp.stock_id, sp.item_id, sp.color_id,
                                  sp.is_spare, sp.quantity, sp.missing, sp.damaged, sp.checked
                           FROM main.stock_part sp
                           JOIN main.stock s ON s.id=sp.stock_id
                           WHERE s.archived_at IS NULL AND sp.retired_at IS NULL'''):
        parts.setdefault(r['stock_id'], []).append({
            'item': items[r['item_id']], 'color': colors[r['color_id']],
            'quantity': r['quantity'], 'missing': r['missing'], 'damaged': r['damaged'],
            'checked': bool(r['checked']), 'spare': bool(r['is_spare']),
        })
    for group in parts.values():
        group.sort(key=lambda r: (_item_key(r['item']), _color_key(r['color']), r['spare']))
    rows = db.execute('''SELECT id, kind, item_id, color_id, quantity, condition, storage_id, lot_id, place_id,
                                purchase_date, purchase_price, purchase_currency, note, missing, damaged, checked,
                                inventory_source, added_via, created_at, updated_at
                         FROM main.stock WHERE archived_at IS NULL ORDER BY id''')
    return [
        {
            'id': r['id'], 'kind': r['kind'], 'item': items[r['item_id']],
            'color': colors[r['color_id']] if r['color_id'] is not None else None,
            'quantity': r['quantity'], 'condition': r['condition'],
            'storage_id': r['storage_id'], 'lot_id': r['lot_id'], 'place_id': r['place_id'],
            'purchase_date': r['purchase_date'], 'purchase_price': r['purchase_price'],
            'purchase_currency': r['purchase_currency'], 'note': _note(r['note'], secrets),
            'missing': r['missing'], 'damaged': r['damaged'], 'checked': r['checked'],
            'list_source': r['inventory_source'], 'added_via': r['added_via'],
            'created_at': r['created_at'], 'updated_at': r['updated_at'],
            'flags': flags.get(r['id'], []), 'lines': parts.get(r['id'], []),
        }
        for r in rows
    ]


def _wishlist_rows(db, secrets):
    rows = db.execute('''SELECT id, name, note, sort, created_at
                         FROM main.wishlist WHERE archived_at IS NULL ORDER BY id''')
    return [
        {
            'id': r['id'], 'name': r['name'], 'note': _note(r['note'], secrets),
            'sort': r['sort'], 'created_at': r['created_at'],
        }
        for r in rows
    ]


def _wish_rows(db, items, colors, secrets):
    flags = _flag_links(db, 'wish_flag', 'wish_id')
    rows = db.execute('''SELECT w.id, w.wishlist_id, w.kind, w.item_id, w.color_id, w.quantity, w.condition,
                                w.max_price, w.max_price_currency, w.qty_filled_manual, w.note,
                                w.max_price_boxed, w.max_price_boxed_currency, w.added_via, w.added_at, w.updated_at
                         FROM main.wish w
                         JOIN main.wishlist wl ON wl.id=w.wishlist_id
                         WHERE w.archived_at IS NULL AND wl.archived_at IS NULL
                         ORDER BY w.id''')
    return [
        {
            'id': r['id'], 'wishlist_id': r['wishlist_id'], 'kind': r['kind'],
            'item': items[r['item_id']],
            'color': colors[r['color_id']] if r['color_id'] is not None else None,
            'quantity': r['quantity'], 'condition': r['condition'],
            'max_price': r['max_price'], 'max_price_currency': r['max_price_currency'],
            'qty_filled_manual': r['qty_filled_manual'], 'note': _note(r['note'], secrets),
            'max_price_boxed': r['max_price_boxed'],
            'max_price_boxed_currency': r['max_price_boxed_currency'],
            'added_via': r['added_via'], 'added_at': r['added_at'], 'updated_at': r['updated_at'],
            'flags': flags.get(r['id'], []),
        }
        for r in rows
    ]


def _jsonl(rows):
    if not rows:
        return ''
    return '\n'.join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows) + '\n'


REFERENCES = (('storage', 'parent_id', 'storage'), ('lot', 'storage_id', 'storage'), ('lot', 'place_id', 'place'),
              ('copy', 'storage_id', 'storage'), ('copy', 'place_id', 'place'), ('stock', 'storage_id', 'storage'),
              ('stock', 'place_id', 'place'), ('stock', 'lot_id', 'lot'))


def _drop_dangling(tables):
    """A parent that is archived, or in a section left out, is not in the file: its id names nothing there, so it is written as null."""
    rows = dict(tables)
    for table, column, parent in REFERENCES:
        if table not in rows:
            continue
        known = {r['id'] for r in rows[parent]} if parent in rows else set()
        for r in rows[table]:
            if r.get(column) is not None and r[column] not in known:
                r[column] = None


def build(db, sections=None):
    """Build the portable export zip for the selected sections."""
    chosen = _parse_sections(sections)
    secrets = secret_values()
    need_refs = 'collection' in chosen or 'wishes' in chosen
    items = _items(db) if need_refs else {}
    colors = _colors(db) if need_refs else {}
    tables = []
    if 'places' in chosen:
        tables.extend([('storage', _storage_rows(db, secrets)), ('place', _place_rows(db))])
    if 'flags' in chosen:
        tables.append(('flag', _flag_rows(db)))
    if 'collection' in chosen:
        tables.extend([
            ('lot', _lot_rows(db, secrets)),
            ('copy', _copy_rows(db, items, colors, secrets)),
            ('stock', _stock_rows(db, items, colors, secrets)),
        ])
    if 'wishes' in chosen:
        tables.extend([
            ('wishlist', _wishlist_rows(db, secrets)),
            ('wish', _wish_rows(db, items, colors, secrets)),
        ])
    _drop_dangling(tables)
    counts = {name: len(rows) for name, rows in tables}
    manifest = {
        'format': FORMAT,
        'format_version': FORMAT_VERSION,
        'schema': _schema_version(db),
        'created_at': stamp(),
        'sections': chosen,
        'counts': counts,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + '\n')
        while tables:
            name, rows = tables.pop(0)                   # one table at a time, each freed once written
            with archive.open(f'data/{name}.jsonl', 'w') as member:
                for row in rows:
                    member.write((json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8'))
    return {'content': buf.getvalue(), 'counts': counts, 'sections': chosen}
