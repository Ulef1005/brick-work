"""The bodies several v2 reads share: `Copy`, `Stock` and `Wish` (M.11b, issue #113), built in bulk from the 4.0 projections.

A copy, stock line or wish row comes from `core/collection.py` (`instances`, `instance`) or the wish query below, already decorated with its
item's identity; the body adds the item and colour bodies (design 7), the flag ids, the ETag and the picture id. Stored words are served as
stored (design 5.1), money as the decimal strings the store keeps."""
from collections import defaultdict
import json

from ..core import collection, currency, planning, wish_progress
from ..store4 import copies as copies_store
from ..store4.connect import has_catalogue
from .read import bodies, etags


def flag_ids(flags):
    return [f['id'] for f in flags]


# ---------- copies ----------

def inventories(db, rows):
    """`{copy id: CopyInventory}` (design 4.4) for copy rows: the list the copy was built from, which of the set's Rebrickable lists that
    is (`ordinal` of `of`), whether a BrickLink switch is pending, and whether the catalogue's list for this version changed since."""
    versions = defaultdict(dict)
    wanted = sorted({r['item_id'] for r in rows})
    if wanted and has_catalogue(db):
        for r in db.execute('SELECT item_id, version, ordinal FROM catalogue.inventory WHERE retired_at IS NULL AND item_id IN (SELECT value FROM json_each(?))',
                            (json.dumps(wanted),)):
            versions[r['item_id']][r['version']] = r['ordinal']
    only = rows[0]['id'] if len(rows) == 1 else None                                     # one copy: one narrowed read
    changed = {e['copy_id'] for e in copies_store.part_list_changes(db, only) if e['figure_id'] is None} if has_catalogue(db) else set()
    return {r['id']: {'source': r['inventory_source'], 'version': r['inventory_version'],
                      'ordinal': versions[r['item_id']].get(r['inventory_version']) if r['inventory_source'] == 'rebrickable' else None,
                      'of': len(versions[r['item_id']]), 'pending': r['inventory_pending'], 'changed_since_build': r['id'] in changed}
            for r in rows}


def copy_bodies(db, rows, *, single=False):
    """`Copy` bodies for decorated copy rows (`collection.instances` / `instance`). `single` adds the part-out value (#38)."""
    if not rows:
        return []
    ids = [r['id'] for r in rows]
    tags = etags(db, 'copy', ids)
    state = inventories(db, rows)
    from ..core import partout
    values = partout.values(db, ids) if single else {}
    unpriced = [u for v in values.values() for u in v['unpriced']]
    book = bodies(db, items=[r['item_id'] for r in rows] + [u['item_id'] for u in unpriced], colors=[u['color_id'] for u in unpriced])
    out = []
    for r in rows:
        body = {'id': r['id'], 'item': book.item(r['item_id']), 'name': r['name'], 'condition': r['condition'], 'completeness': r['completeness'],
                'completeness_source': r['completeness_source'], 'storage_id': r['storage_id'], 'purchase_location_id': r['place_id'],
                'purchase_date': r['purchase_date'], 'purchase_price': r['purchase_price'], 'purchase_currency': r['purchase_currency'], 'note': r['note'],
                'current_value': r['current_value'], 'current_value_currency': r['current_value_currency'], 'pinned': bool(r['pinned']),
                'flags': flag_ids(r['flags']), 'missing': r['missing'], 'damaged': r['damaged'], 'updated_at': r['updated_at'],
                'archived_at': r['archived_at'], 'etag': tags.get(r['id']), 'image_id': r['image'], 'inventory': state[r['id']]}
        if single:
            value = values.get(r['id'])
            body['partout'] = None if value is None else {
                'value': value['value'], 'currency': value['currency'], 'lines': value['lines'], 'priced': value['priced'],
                'unpriced': [{'item': book.item(u['item_id']), 'color': book.color(u['color_id'])} for u in value['unpriced']],
                'unpriced_count': value['unpriced_count']}
        out.append(body)
    return out


# ---------- stock ----------

def stock_bodies(db, rows):
    """`Stock` bodies for decorated stock rows (`collection.instances` / `instance`)."""
    if not rows:
        return []
    book = bodies(db, items=[r['item_id'] for r in rows], colors=[r['color_id'] for r in rows])
    tags = etags(db, 'stock', [r['id'] for r in rows])
    return [{'id': r['id'], 'item': book.item(r['item_id']), 'name': r['name'], 'color': book.color(r['color_id']), 'quantity': r['quantity'],
             'condition': r['condition'], 'storage_id': r['storage_id'], 'lot_id': r['lot_id'], 'purchase_location_id': r['place_id'],
             'purchase_date': r['purchase_date'], 'purchase_price': r['purchase_price'], 'purchase_currency': r['purchase_currency'], 'note': r['note'],
             'created_at': r['created_at'], 'updated_at': r['updated_at'], 'archived_at': r['archived_at'], 'missing': r['missing'],
             'damaged': r['damaged'], 'flags': flag_ids(r['flags']), 'merged_ids': [], 'etag': tags.get(r['id']), 'image_id': r['image']}
            for r in rows]


# ---------- wishes ----------

def wish_rows(db, where='', params=()):
    """Wish rows, decorated, priced as the Wishlist screen prices them (the quote at the wish's condition, compared with its maximum
    in the same currency or through a rate, #39) and with their progress (#35). `where` filters `w` (wish) rows; archived rows come
    back only when the caller's `where` does not exclude them."""
    rows = [dict(r, entity='wish', list_id=r['wishlist_id'], kind=r['kind']) for r in db.execute(
        f'''SELECT w.*, i.name, i.year, i.theme_name AS theme, i.category_name AS category, l.name AS list_name FROM main.wish w
            JOIN main.item i ON i.id=w.item_id JOIN main.wishlist l ON l.id=w.wishlist_id {where} ORDER BY w.added_at, w.id''', params)]
    rows = collection.decorate(db, rows)
    flags = collection._flags(db, {'wish': [r['id'] for r in rows]})
    market = collection.prices(db, pairs=[(r['item_id'], r.get('color_id')) for r in rows]) if rows else {}
    for r in rows:
        r['flags'] = flags['wish', r['id']]
        r['prices'] = market.get((r['item_id'], r.get('color_id')), [])
    planning.display_prices(db, rows)
    table = currency.rates(db)
    for r in rows:
        r['max_state'], r['max_margin'] = planning.max_comparison(r, table)
    wish_progress.annotate(db, rows)
    return rows


def wish_bodies(db, rows):
    if not rows:
        return []
    book = bodies(db, items=[r['item_id'] for r in rows], colors=[r['color_id'] for r in rows])
    tags = etags(db, 'wish', [r['id'] for r in rows])
    out = []
    for r in rows:
        shown = r.get('display_price') or {}
        out.append({'qty_filled': r['qty_filled'], 'qty_filled_source': r['qty_filled_source'], 'qty_filled_manual': r['qty_filled_manual'],
                    'list_id': r['list_id'], 'id': r['id'], 'item': book.item(r['item_id']), 'name': r['name'], 'color': book.color(r['color_id']),
                    'quantity': r['quantity'], 'max_price': r['max_price'], 'max_price_currency': r['max_price_currency'], 'condition': r['condition'],
                    'note': r['note'], 'added_at': r['added_at'], 'updated_at': r['updated_at'], 'archived_at': r['archived_at'],
                    'under_max': {'under': True, 'over': False}.get(r['max_state']), 'current_price': shown.get('price'),
                    'flags': flag_ids(r['flags']), 'etag': tags.get(r['id']), 'image_id': r['image']})
    return out
