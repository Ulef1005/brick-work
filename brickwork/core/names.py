"""Canonical display names, with source-labelled evidence and no guessed ids."""
from collections import defaultdict
from contextlib import closing
import json
import sqlite3


def catalogue_names(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        return {(kind, number): name for kind, number, name in
                db.execute('SELECT item_type,item_no,name FROM items') if name}


def choose_names(keys, catalogue, candidates):
    chosen = {}
    for key in sorted(keys):
        if catalogue.get(key):
            chosen[key] = (catalogue[key], 'bricklink')
        elif len(candidates.get(key, set())) == 1:
            chosen[key] = (next(iter(candidates[key])), 'rebrickable')
    return chosen


def refresh(db, path):
    """Refresh held identities only; retained RB envelopes are fallback evidence."""
    from .sources.base import item, property_value, record_change
    old_items = {(r['item_type'], r['item_no']): dict(r) for r in db.execute('SELECT * FROM items')}
    keys = list(old_items)
    old_properties = {(r['item_type'], r['item_no'], r['source']): dict(r) for r in
                      db.execute("SELECT * FROM item_properties WHERE key='name'")}
    matches = defaultdict(set)
    for kind, sid, item_type, item_no in db.execute("SELECT kind,source_id,item_type,item_no FROM id_match WHERE source='rebrickable' AND item_no IS NOT NULL"):
        matches[kind, sid].add((item_type, item_no))
    candidates = defaultdict(set)
    for table, payload in db.execute("SELECT kind,payload FROM source_records WHERE source='rebrickable' AND kind IN ('rebrickable_sets','rebrickable_parts','rebrickable_minifigures')"):
        kind, field = {'rebrickable_sets': ('set', 'set'), 'rebrickable_parts': ('part', 'part'),
                       'rebrickable_minifigures': ('minifigure', 'figure')}[table]
        for entry in json.loads(payload).get('records', []):
            row = entry['record']
            if row.get('name'):
                for key in matches[kind, row.get(field)]:
                    candidates[key].add(row['name'])
    chosen = choose_names(keys, catalogue_names(path), candidates)
    changed = 0
    for (kind, number), (name, source) in chosen.items():
        old_item = old_items[kind, number]
        old_property = old_properties.get((kind, number, source))
        item_changed = old_item['name'] != name
        property_changed = old_property is None or old_property['value'] != name
        if not item_changed and not property_changed:
            continue
        if item_changed:
            item(db, kind, number, name)
        if property_changed:
            property_value(db, source, kind, number, 'name', name)
        changed += 1
        record_change(db, f'item-name:{kind}:{number}',
                      dict(item=old_items[kind, number], property=old_properties.get((kind, number, source))),
                      dict(name=name, source=source))
    return changed
