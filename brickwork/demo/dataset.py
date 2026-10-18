"""Build the demo's brickwork.db from design/test-data.

Catalogue facts (set, part, colour and minifigure names and numbers) come from the design test data,
which took them from a public catalogue snapshot. The collection itself is invented: copies, storage,
purchases, check state, loose stock and every price. Owners get invented names. No pictures are
stored, so every item shows the app's missing-picture tile, and nothing here calls a network.
"""
import json
import sqlite3
from pathlib import Path

from ..core.connect import connect

DATA = Path(__file__).resolve().parents[2] / 'design' / 'test-data'
OWNERS = {'Alex': 'Alex', 'Sam': 'Sam'}  # invented names for the demo
STAMP = '2026-10-12T08:00:00+00:00'


def load(name, data=DATA):
    return json.loads((data / name).read_text(encoding='utf-8'))


def slug(text):
    return ''.join(c if c.isalnum() else '-' for c in text.lower()).strip('-')


def build(path, data=DATA):
    """Create a new store at `path` (which must not exist) and fill it; returns row counts."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    db = connect(path)
    try:
        with db:
            fill(db, data)
        return {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                for t in ('items', 'copies', 'copy_parts', 'loose_stock', 'wishlist', 'price_observations')}
    finally:
        db.close()


def fill(db, data):
    sets, wishes, meta = load('sets.json', data), load('wishlist.json', data), load('metadata.json', data)
    places = load('storages.json', data)
    for colour in load('colors.json', data):
        db.execute('INSERT INTO colors(color_id,name,type,rgb) VALUES(?,?,?,?)',
                   (colour['id'], colour['name'], 'Transparent' if colour['transparent'] else 'Solid', colour['rgb'].lstrip('#')))
    known_colours = {r[0] for r in db.execute('SELECT color_id FROM colors')}

    def item(kind, number, name, category=None, year=None):
        db.execute('INSERT OR IGNORE INTO items(item_type,item_no,name,category,year,updated_at) VALUES(?,?,?,?,?,?)',
                   (kind, number, name, category, year, STAMP))

    def colour(c):
        if c['id'] not in known_colours:
            db.execute('INSERT INTO colors(color_id,name,type,rgb) VALUES(?,?,?,?)',
                       (c['id'], c['name'], 'Transparent' if c.get('transparent') else 'Solid', (c.get('rgb') or '').lstrip('#')))
            known_colours.add(c['id'])
        return c['id']

    # Storage and purchase places: the names the copies use, plus the listed ones.
    storage_names = {s['storage'] for s in sets} | {s['name'] for s in places['storages']} | {'Parts drawer unit'}
    storage = {name: 'storage-' + slug(name) for name in sorted(storage_names)}
    kinds = {s['name']: s.get('type') for s in places['storages']}
    for name, identifier in storage.items():
        db.execute('INSERT INTO storages(id,name,type) VALUES(?,?,?)', (identifier, name, kinds.get(name)))
    place_names = {s['purchase_location'] for s in sets} | {p['name'] for p in places['purchase_locations']}
    place = {name: 'place-' + slug(name) for name in sorted(place_names)}
    for name, identifier in place.items():
        db.execute('INSERT INTO purchase_locations(id,name) VALUES(?,?)', (identifier, name))

    flags = {}
    for status in meta['statuses']:
        flags[('status', status['id'])] = 'status-' + status['id']
        db.execute('INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,?,?)', ('status-' + status['id'], status['name'], 'status', int(status['displayed_on_grid'])))
    for tag in meta['tags']:
        flags[('tag', tag['name'])] = 'tag-' + slug(tag['name'])
        db.execute('INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,?,?)', ('tag-' + slug(tag['name']), tag['name'], 'tag', 0))
    for owner in meta['owners']:
        name = OWNERS.get(owner['name'], owner['name'])
        flags[('owner', owner['name'])] = 'owner-' + slug(name)
        db.execute('INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,?,?)', ('owner-' + slug(name), name, 'owner', 0))

    loose = []
    for copy in sets:
        item('S', copy['set'], copy['name'], copy['theme_path'], copy['year'])
        inventory = load(copy['inventory_file'], data) if copy.get('has_inventory_fixture') and copy.get('inventory_file') else None
        if inventory and inventory['copy_id'] != copy['id']:
            inventory = None  # the second copy of a set has no inventory of its own
        sealed = 'sealed' in copy['status']
        summary = copy.get('summary') or {}
        if sealed:
            completeness = 'S'
        elif inventory and summary.get('pieces_missing'):
            completeness = 'I'
        elif inventory and summary.get('rows_checked') == summary.get('rows'):
            completeness = 'C'
        else:
            completeness = None
        db.execute('''INSERT INTO copies(id,item_type,set_no,condition,completeness,completeness_source,storage_id,
            purchase_location_id,purchase_date,purchase_price,purchase_currency,note,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (copy['id'], 'S', copy['set'], 'N' if sealed else 'U', completeness, 'manual' if completeness else None,
                    storage[copy['storage']], place[copy['purchase_location']], copy['purchase_date'],
                    f"{copy['purchase_price']:.2f}" if copy.get('purchase_price') is not None else None,
                    'EUR' if copy.get('purchase_price') is not None else None, None, STAMP))
        for status in copy['status']:
            db.execute('INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES(?,?,?)', ('copy', copy['id'], flags[('status', status)]))
        for tag in copy['tags']:
            db.execute('INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES(?,?,?)', ('copy', copy['id'], flags[('tag', tag)]))
        for owner in copy['owners']:
            db.execute('INSERT INTO item_flags(entity_type,entity_id,flag_id) VALUES(?,?,?)', ('copy', copy['id'], flags[('owner', owner)]))
        if inventory:
            inventory_rows(db, item, colour, copy, inventory, loose)
        # An invented used value for every owned set, so Prices and the set pages have numbers.
        if copy.get('purchase_price'):
            price(db, 'S', copy['set'], None, 'U', round(copy['purchase_price'] * 1.35, 2), 9, STAMP)

    for wish in wishes:
        item('S', wish['set'], wish['name'], wish['theme_path'], wish['year'])
        db.execute('''INSERT INTO wishlist(item_type,item_no,color_id,quantity,max_price,max_price_currency,condition,added_at,updated_at)
            VALUES('S',?,NULL,1,?,?,?,?,?)''', (wish['set'], f"{wish['max_price']:.2f}", 'EUR', wish['condition'], STAMP, STAMP))
        for history in wish.get('price_history', []):
            if history.get('source') == 'bricklink' and history.get('slot') in ('new', 'used'):
                price(db, 'S', wish['set'], None, 'N' if history['slot'] == 'new' else 'U', history['price'], None,
                      history['observed_at'] + 'T06:00:00+00:00', current=False)
        for slot, condition in (('bricklink_new', 'N'), ('bricklink_used', 'U')):
            quote = (wish.get('prices') or {}).get(slot)
            if quote and quote.get('price') is not None:
                price(db, 'S', wish['set'], None, condition, quote['price'], quote.get('sold'),
                      quote['observed_at'] + 'T06:00:00+00:00', low=quote.get('min'), high=quote.get('max'))

    # Loose stock that can fill some gaps, so the Part Picker and Complete sets have matches.
    for index, (number, colour_id, quantity) in enumerate(loose):
        db.execute('''INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,storage_id,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)''', (f'loose-{index + 1}', 'P', number, colour_id, quantity, 'U', storage['Parts drawer unit'], STAMP, STAMP))


def inventory_rows(db, item, colour, copy, inventory, loose):
    figures = {f['figure']: f for f in inventory.get('minifigures', [])}
    for figure in figures.values():
        item('M', figure['figure'], figure['name'], 'Minifigure')
        db.execute('INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,color_id,quantity,source,fetched_at) VALUES(?,?,?,?,?,?,?,?)',
                   ('S', copy['set'], 'M', figure['figure'], None, figure['quantity'], 'rebrickable', STAMP))
        missing = 1 if copy['set'] == '1592-1' and figure is list(figures.values())[-1] else 0
        db.execute('INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing,updated_at) VALUES(?,?,?,?,?,?)', (copy['id'], 'M', figure['figure'], figure['quantity'], missing, STAMP))
    gaps = 0
    for row in inventory['parts']:
        item('P', row['part'], row['name'], row.get('category'))
        colour_id = colour(row['color'])
        db.execute('INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,color_id,quantity,extra_quantity,source,fetched_at) VALUES(?,?,?,?,?,?,?,?,?)',
                   ('S', copy['set'], 'P', row['part'], colour_id, row['quantity'], 0, 'rebrickable', STAMP))
        db.execute('''INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,spare,quantity,missing,damaged,checked,element_id)
            VALUES(?,?,?,?,?,?,?,?,?,?)''', (copy['id'], 'P', row['part'], colour_id, int(bool(row.get('spare'))), row['quantity'],
                                              row.get('missing') or 0, row.get('damaged') or 0, row.get('checked') or 0,
                                              int(row['element']) if str(row.get('element') or '').isdigit() else None))
        if row.get('missing'):
            gaps += 1
            price(db, 'P', row['part'], colour_id, 'U', round(0.04 + 0.03 * (gaps % 7), 2), 25, STAMP)
            if gaps % 2:
                loose.append((row['part'], colour_id, row['missing']))
    for number, rows in inventory.get('minifigure_parts', {}).items():
        for row in rows:
            item('P', row['part'], row['name'], row.get('category'))
            colour_id = colour(row['color'])
            db.execute('INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,color_id,quantity,source,fetched_at) VALUES(?,?,?,?,?,?,?,?)',
                       ('M', number, 'P', row['part'], colour_id, row['quantity'], 'rebrickable', STAMP))
            db.execute('''INSERT INTO copy_parts(copy_id,parent_minifig_type,parent_minifig,item_type,item_no,color_id,spare,quantity,missing,damaged,checked)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (copy['id'], 'M', number, 'P', row['part'], colour_id, 0, row['quantity'],
                                                    row.get('missing') or 0, row.get('damaged') or 0, row.get('checked') or 0))


def price(db, kind, number, colour_id, condition, value, sold, observed, *, low=None, high=None, current=True):
    cursor = db.execute('''INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,slot,region,currency,price,qty,sold,min,max,source,observed_at)
        VALUES(?,?,?,?,'sold',?,'eu','EUR',?,?,?,?,?,'bricklink',?)''',
                        (kind, number, colour_id, condition, 'bricklink_new' if condition == 'N' else 'bricklink_used', f'{value:.2f}',
                         sold, sold, f'{low:.2f}' if low is not None else None, f'{high:.2f}' if high is not None else None, observed))
    if current:
        db.execute('DELETE FROM price_current WHERE item_type=? AND item_no=? AND color_id IS ? AND condition=? AND guide=?',
                   (kind, number, colour_id, condition, 'sold'))
        db.execute('INSERT INTO price_current(item_type,item_no,color_id,condition,guide,slot,region,currency,observation_id) VALUES(?,?,?,?,?,?,?,?,?)',
                   (kind, number, colour_id, condition, 'sold', 'bricklink_new' if condition == 'N' else 'bricklink_used', 'eu', 'EUR', cursor.lastrowid))
