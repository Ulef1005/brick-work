"""Export the owned collection as Brick Work CSV, BrickLink XML or Rebrickable CSV (#470)."""
from collections import defaultdict
import io
import json

from ..store4.connect import has_catalogue
from . import collection, csv_safe, errors, gaps, items
from .secrets import secret_values
from .sources.base import redact

KINDS = ('set', 'part', 'minifigure')
MAX_IDS = 2000
OWN_COLUMNS = (
    'Kind', 'Item number', 'Name', 'Colour', 'Colour id', 'Quantity', 'Condition',
    'Completeness', 'Storage', 'Place', 'Price paid', 'Price paid currency',
    'Purchase date', 'Owners', 'Tags/flags', 'Note',
)
REBRICKABLE_COLUMNS = {
    'part': ('part_num', 'color_id', 'quantity'),
    'set': ('set_num', 'quantity'),
    'minifigure': ('minifig_num', 'quantity'),
}


def _rows(db, kind, ids=None):
    """Live collection rows for `kind`, optionally restricted to `ids`."""
    if kind not in KINDS:
        raise errors.ValidationFailed(f'kind must be one of {", ".join(KINDS)}')
    rows = collection.instances(db, kind)
    if ids is None:
        return rows
    if not isinstance(ids, (list, tuple)) or len(ids) > MAX_IDS or len(set(ids)) != len(ids):
        raise errors.ValidationFailed(f'Choose up to {MAX_IDS} different ids')
    if any(not isinstance(i, str) or not i for i in ids):
        raise errors.ValidationFailed('Each id must be a non-empty string')
    by_id = {r['id']: r for r in rows}
    if any(i not in by_id for i in ids):
        raise errors.ValidationFailed('Unknown or archived id')
    wanted = set(ids)
    return [r for r in rows if r['id'] in wanted]


def _quantity(row):
    qty = row.get('quantity')
    return 1 if qty is None else int(qty)


def _names(value):
    """Join names (strings or dicts with `name`) with ' · '."""
    if not value:
        return ''
    if isinstance(value, str):
        return value
    parts = [v['name'] if isinstance(v, dict) else str(v) for v in value]
    return ' · '.join(p for p in parts if p)


def _lookup_names(db, table, ids):
    wanted = sorted({i for i in ids if i is not None})
    if not wanted:
        return {}
    return {r['id']: r['name'] for r in db.execute(
        f'SELECT id, name FROM main.{table} WHERE id IN (SELECT value FROM json_each(?))',
        (json.dumps(wanted),),
    )}


def _named(row, name_key, obj_key, id_key, lookup):
    if row.get(name_key):
        return row[name_key]
    obj = row.get(obj_key)
    if isinstance(obj, dict):
        return obj.get('name') or ''
    if isinstance(obj, str) and obj and obj != row.get(id_key):
        return obj
    return lookup.get(row.get(id_key), '')


def to_csv(db, kind, ids=None):
    """Own-format CSV of live rows (unmerged, formula-safe)."""
    rows = _rows(db, kind, ids)
    lbls = items.labels(db, {(r['item_id'], r.get('color_id')) for r in rows})
    storages = _lookup_names(db, 'storage', (r.get('storage_id') for r in rows))
    places = _lookup_names(db, 'place', (r.get('place_id') for r in rows))
    colours = _lookup_names(db, 'color', (r.get('color_id') for r in rows))
    stream = io.StringIO(newline='')
    out = csv_safe.writer(stream)
    out.writerow(OWN_COLUMNS)
    for r in rows:
        color_id = r.get('color_id')
        lbl = lbls.get((r['item_id'], color_id))
        number = r.get('item_no') or r.get('number_text') or ''
        name = lbl.name if lbl is not None else (r.get('name') or '')
        colour = _named(r, 'color_name', 'colour', 'color_id', colours) if color_id is not None else ''
        price = '' if r.get('purchase_price') is None else r['purchase_price']
        flags = r.get('flags') or []
        owners = _names([f for f in flags if isinstance(f, dict) and f.get('kind') == 'owner'])
        others = [f for f in flags if not (isinstance(f, dict) and f.get('kind') == 'owner')]
        out.writerow([
            kind,
            number,
            name,
            colour,
            '' if color_id is None else color_id,
            _quantity(r),
            (r.get('condition') or '').capitalize(),
            (r.get('completeness') or '').capitalize() if kind == 'set' else '',
            _named(r, 'storage_name', 'storage', 'storage_id', storages),
            _named(r, 'place_name', 'place', 'place_id', places),
            price,
            r.get('purchase_currency') or '',
            r.get('purchase_date') or '',
            owners,
            _names(others),
            r.get('note') or '',
        ])
    return dict(content=redact(stream.getvalue(), secret_values()), rows=len(rows), skipped=[])


def to_xml(db, kind, ids=None):
    """BrickLink INVENTORY XML of live rows, merged per item, colour and condition."""
    rows = _rows(db, kind, ids)
    total = defaultdict(int)
    for r in rows:
        color_id = r.get('color_id') if kind == 'part' else None
        total[r['item_id'], color_id, gaps.CONDITION.get(r.get('condition'), 'U')] += _quantity(r)
    named = gaps.named_lines(db, total)
    exported = gaps.export_lines(db, None, named)
    skipped = [{'name': s['name'] or '', 'why': s['why']} for s in exported['skipped']]
    return dict(content=exported['xml'], rows=len(exported['lines']), skipped=skipped)


def _rebrickable_colours(db, color_ids):
    """Rebrickable colour id strings keyed by Brick Work colour id."""
    wanted = sorted({c for c in color_ids if c is not None})
    if not wanted:
        return {}
    found, seen = {}, set()
    stores = ('main', 'catalogue') if has_catalogue(db) else ('main',)
    for store in stores:
        missing = sorted(set(wanted) - seen)
        if not missing:
            break
        for r in db.execute(
            f'SELECT id, born_provider, born_key FROM {store}.color WHERE id IN (SELECT value FROM json_each(?))',
            (json.dumps(missing),),
        ):
            seen.add(r['id'])
            if r['born_provider'] == items.REBRICKABLE and r['born_key'] is not None:
                found[r['id']] = str(r['born_key'])
    return found


def to_rebrickable_csv(db, kind, ids=None):
    """Rebrickable CSV of live rows, merged per item and colour."""
    rows = _rows(db, kind, ids)
    total = defaultdict(int)
    for r in rows:
        color_id = r.get('color_id') if kind == 'part' else None
        total[r['item_id'], color_id] += _quantity(r)
    lbls = items.labels(db, set(total))
    rb_colours = _rebrickable_colours(db, (c for _, c in total)) if kind == 'part' else {}
    stream = io.StringIO(newline='')
    out = csv_safe.writer(stream)
    out.writerow(REBRICKABLE_COLUMNS[kind])
    written, skipped = 0, []
    for (item_id, color_id), qty in sorted(total.items(), key=lambda p: (str(p[0][0]).zfill(12), p[0][1] or 0)):
        lbl = lbls.get((item_id, color_id))
        name = lbl.name if lbl is not None else ''
        if lbl is None or lbl.source != items.REBRICKABLE or not lbl.number:
            skipped.append({'name': name, 'why': 'no Rebrickable number'})
            continue
        if kind == 'part':
            rb_colour = rb_colours.get(color_id)
            if rb_colour is None:
                skipped.append({'name': name, 'why': 'no Rebrickable colour'})
                continue
            out.writerow([lbl.number, rb_colour, qty])
        else:
            out.writerow([lbl.number, qty])
        written += 1
    return dict(content=stream.getvalue(), rows=written, skipped=skipped)
