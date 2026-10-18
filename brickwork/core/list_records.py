"""Compact display-only Collection records; no database reads or writes.

Positional fields avoid repeating keys thousands of times. Filter defaults are
omitted and restored by the shared browser decoder. Private instance metadata
never leaves the server; instance ids remain available for bulk actions.
"""
import json
from markupsafe import Markup
from .collection import defects
from ..web.formatting import money, short_age

FIELDS = 'type number name colour color_id rgb ink category theme year quantity missing damaged in_sets image unresolved entity ids condition status storage place flags lot duplicates price lot_links defects price_basis missing_parts missing_figures pdf_available max_price subtheme tags'.split()


def payload(rows, query="", filters=None, sort="index", direction="asc"):
    from .listing import filter_rows
    records = []
    for r in rows:
        p = r.get('price')
        wish = r.get('entity') == 'wish'
        wanted = r.get('quantity') or r.get('need') or 0
        missing = 0 if wish else r.get('missing') or r.get('need') or 0
        values = [r['item_type'], r['item_no'], r.get('name'), r.get('color_name'),
            r.get('color_id'), r.get('rgb'), r.get('ink'), r.get('category'),
            r.get('theme'), r.get('year'), wanted if wish else r.get('quantity') or 0,
            missing, r.get('damaged') or 0,
            r.get('in_sets') or 0, r.get('image'), r.get('unresolved') or False,
            r.get('entity'), [r['id']] if r.get('entity') == 'wish' else r.get('ids', []),
            r.get('conditions') or [{'new':'N','used':'U','any':'any'}.get(r.get('condition'), r.get('condition') or '')],
            r.get('statuses') or [r.get('completeness') or ''],
            r.get('storages') or [r.get('storage_id') or 'null'],
            r.get('places') or [r.get('purchase_location_id') or 'null'],
            r.get('flag_names') or [], r.get('lots') or [r.get('lot_id') or 'null'],
            (r.get('quantity') or 0) > 1 if r['item_type'] == 'S' and not wish else len(r.get('instances', [])) > 1,
            [p.get('currency') or 'Currency not recorded', p['price'], p['age'], p['stale'],
             money(p['price'], p.get('currency') or 'Currency not recorded', fixed=True),
             short_age(p['age'])] if p else None,
            [[i['lot_id'], i.get('lot_name') or i['lot_id']] for i in r.get('instances', []) if i.get('lot_id')],
            f'{wanted} wanted' if wish else defects(missing, r.get('damaged')),
            [p.get('condition'), p.get('guide'), p.get('source')] if p else None,
            r.get('missing_parts') or 0, r.get('missing_figures') or 0, r.get('pdf_available') or False,
            (money(r.get('max_price'), r.get('max_price_currency') or '', fixed=True) if wish and r.get('max_price') is not None else None),
            ((r.get('properties') or {}).get('subtheme') or {}).get('value') if r['item_type'] == 'S' and not wish else None,
            sorted({f['name'] for i in r.get('instances', []) for f in i.get('flags', []) if f.get('kind') == 'tag' and f.get('name')})]
        defaults = {18:[''], 19:[''], 20:['null'], 21:['null'], 22:[], 23:['null']}
        packed = {str(i): v for i,v in enumerate(values) if (i == 4 and v is not None) or (v != defaults.get(i) and v not in (None, '', False, 0, []))}
        records.append(packed)
    decoded = [dict(zip(FIELDS, [record.get(str(i), defaults.get(i)) for i in range(len(FIELDS))]), id=str(i), index=i) for i, record in enumerate(records)]
    ordered = filter_rows(decoded, query, filters, sort, direction)
    records = [records[int(row['id'])] for row in ordered]
    # Same script-safe escaping as Jinja tojson, with compact separators.
    encoded = json.dumps({'fields':FIELDS, 'rows':records}, separators=(',', ':'), ensure_ascii=False)
    return Markup(encoded.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace("'", '\\u0027'))
