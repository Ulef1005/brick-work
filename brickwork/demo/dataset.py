"""Build the demo's 4.0 collection from design/test-data (M.8j, issue #110).

The catalogue is built, not stored: a Rebrickable-shaped dump is written from the design test data (set, part, colour and minifigure names and
numbers, which took them from a public catalogue snapshot), `store4.builder` builds a `catalogue.db` from it beside the collection, the
collection is created and activated against it, and the invented collection is written through the app's own writers: copies through
`core.add` (design 4.3, with the part list the dump holds), loose stock through `core.stock`, prices as the sources write them. The copies,
storage, purchases, check state, loose stock, owners and every price are invented. No pictures are stored, so every item shows the app's
missing-picture tile, and nothing here calls a network.
"""
import csv
import gzip
import json
from contextlib import closing, contextmanager
from pathlib import Path
import tempfile
import uuid

from ..core import items, stock
from ..core.connect import connect
from ..core.sources import base
from ..core.transaction import transaction
from ..store4 import builder, identity
from ..store4.activate import activate
from ..store4.dump import HEADERS

DATA = Path(__file__).resolve().parents[2] / 'design' / 'test-data'
STAMP = '2026-10-12T08:00:00.000Z'
NOW = '2026-10-12T08:00:00Z'


def load(name, data=DATA):
    return json.loads((data / name).read_text(encoding='utf-8'))


def slug(text):
    return ''.join(c if c.isalnum() else '-' for c in text.lower()).strip('-')


def theme_path(row):
    return '/'.join(n.strip() for n in row['theme_path'].split('/'))


# ---------- the catalogue ----------

def inventories_of(sets, data=DATA):
    """The inventory files of the design test data by set number (the second copy of a set has none of its own)."""
    found = {}
    for copy in sets:
        if copy.get('has_inventory_fixture') and copy.get('inventory_file'):
            inventory = load(copy['inventory_file'], data)
            if inventory['copy_id'] == copy['id']:
                found[copy['set']] = inventory
    return found


def write_dump(directory, data=DATA):
    """The twelve Rebrickable dump files (`<name>.csv.gz`) for the design test data."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    sets, wishes = load('sets.json', data), load('wishlist.json', data)
    inventories = inventories_of(sets, data)
    # themes: 'City / Police' is two themes; the leaf takes the set's theme id, its parents get invented ones
    themes, next_theme = {}, 9000
    for row in sets + wishes:
        parent, names = '', [n.strip() for n in row['theme_path'].split('/')]
        for depth, name in enumerate(names):
            path = (parent + '/' + name).strip('/')
            if path not in themes:
                last = depth == len(names) - 1
                themes[path] = [row['theme_id'] if last else next_theme, name, themes[parent][0] if parent else '']
                next_theme += not last
            parent = path
    colours = {c['id']: (c['name'], c['rgb'].lstrip('#'), c['transparent']) for c in load('colors.json', data)}
    colours.setdefault(-1, ('[Unknown]', '0033B2', False))
    parts, categories, figures, inventory_rows, inventory_figures, inventory_parts, inventory_ids = {}, {}, {}, [], [], {}, {}

    def lines(inventory_id, rows):
        for row in rows:
            colour = row['color']
            colours.setdefault(colour['id'], (colour['name'], colour['rgb'].lstrip('#'), colour['transparent']))
            category = categories.setdefault(row.get('category') or 'Other', len(categories) + 1)
            parts.setdefault(row['part'], [row['part'], row['name'], category, 'Plastic'])
            key = (inventory_id, row['part'], colour['id'], bool(row.get('spare')))
            inventory_parts[key] = inventory_parts.get(key, 0) + row['quantity']
    for number, inventory in inventories.items():
        inventory_ids[number] = len(inventory_ids) + 1
        inventory_rows.append([inventory_ids[number], 1, number])
        lines(inventory_ids[number], [r for r in inventory['parts'] if not r.get('figure')])
        for figure in inventory.get('minifigures', []):
            figures.setdefault(figure['figure'], [figure['figure'], figure['name'], figure.get('parts') or 0, ''])
            inventory_figures.append([inventory_ids[number], figure['figure'], figure['quantity']])
            if figure['figure'] not in inventory_ids:
                inventory_ids[figure['figure']] = len(inventory_ids) + 1
                inventory_rows.append([inventory_ids[figure['figure']], 1, figure['figure']])
                lines(inventory_ids[figure['figure']], inventory.get('minifigure_parts', {}).get(figure['figure'], []))
    shown = {}
    for row in sets + wishes:
        shown.setdefault(row['set'], [row['set'], row['name'], row['year'], themes[theme_path(row)][0], row.get('parts') or 0, ''])
    files = {
        'colors': [[i, n, rgb, str(t), 0, 0, 0, 0] for i, (n, rgb, t) in sorted(colours.items())],
        'elements': [], 'inventory_sets': [], 'part_relationships': [],
        'inventories': inventory_rows,
        'inventory_minifigs': inventory_figures,
        'inventory_parts': [[i, p, c, q, str(s), ''] for (i, p, c, s), q in sorted(inventory_parts.items())],
        'minifigs': sorted(figures.values()),
        'part_categories': [[i, n] for n, i in categories.items()],
        'parts': sorted(parts.values()),
        'sets': sorted(shown.values()),
        'themes': sorted(themes.values()),
    }
    for name, header in HEADERS.items():
        with gzip.open(directory / f'{name}.csv.gz', 'wt', encoding='utf-8', newline='') as out:
            writer = csv.writer(out, lineterminator='\n')
            writer.writerow(header.split(','))
            writer.writerows(files[name])
    return inventories


# ---------- the collection ----------

@contextmanager
def fixed_copy_id(identifier):
    """The next uuid4 call is `identifier` (the copy id the design test data names); every later one is random."""
    real, used = uuid.uuid4, []

    def pick():
        if not used:
            used.append(1)
            return uuid.UUID(identifier)
        return real()
    uuid.uuid4 = pick
    try:
        yield
    finally:
        uuid.uuid4 = real


def build(path, data=DATA):
    """Create a new collection at `path` (which must not exist) with its catalogue beside it, and fill it; returns row counts and the copy ids
    by set number."""
    path = Path(path)
    catalogue = path.with_name('catalogue.db')
    for target in (path, catalogue):
        if target.exists():
            raise FileExistsError(target)
    with tempfile.TemporaryDirectory() as scratch:
        inventories = write_dump(Path(scratch) / 'dump', data)
        builder.build(Path(scratch) / 'dump', catalogue, app_version='demo', now=NOW)
    with closing(connect(path)) as db:
        activate(db)
        ids = fill(db, data, inventories)
        counts = {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('item', 'copy', 'copy_part', 'stock', 'wish', 'price_observation')}
        counts['ids'] = ids
        return counts


def item_by(db, namespace, number):
    return db.execute('SELECT id FROM catalogue.item WHERE born_namespace=? AND born_key=?', (namespace, number)).fetchone()[0]


def colour_by(db, number):
    return db.execute('SELECT id FROM catalogue.color WHERE born_key=?', (str(number),)).fetchone()[0]


def put(db, table, identifier, name, **fields):
    columns = {'id': identifier, 'name': name, 'created_at': STAMP, **fields}
    db.execute(f'INSERT OR IGNORE INTO {table}({",".join(columns)}) VALUES({",".join("?" * len(columns))})', tuple(columns.values()))
    return identifier


def fill(db, data, inventories):
    from ..core import add
    sets, wishes, meta = load('sets.json', data), load('wishlist.json', data), load('metadata.json', data)
    places = load('storages.json', data)
    ids, flags, loose = {}, {}, []
    with transaction(db):
        kinds = {s['name']: s.get('type') for s in places['storages']}
        for name in sorted({s['storage'] for s in sets} | {s['name'] for s in places['storages']} | {'Parts drawer unit'}):
            put(db, 'storage', 'storage-' + slug(name), name, type=kinds.get(name))
        place_kinds = {p['name']: p.get('kind') for p in places['purchase_locations']}
        for name in sorted({s['purchase_location'] for s in sets} | set(place_kinds)):
            put(db, 'place', 'place-' + slug(name), name, kind=place_kinds.get(name))
        for status in meta['statuses']:
            flags['status', status['id']] = put(db, 'flag', 'status-' + status['id'], status['name'], kind='status', shown_on_grid=int(status['displayed_on_grid']))
        for tag in meta['tags']:
            flags['tag', tag['name']] = put(db, 'flag', 'tag-' + slug(tag['name']), tag['name'], kind='tag', shown_on_grid=0)
        for owner in meta['owners']:
            flags['owner', owner['name']] = put(db, 'flag', 'owner-' + slug(owner['name']), owner['name'], kind='owner', shown_on_grid=0)
    for copy in sets:
        item = item_by(db, 'sets', copy['set'])
        sealed = 'sealed' in copy['status']
        inventory = inventories.get(copy['set']) if inventories.get(copy['set'], {}).get('copy_id') == copy['id'] else None
        summary = copy.get('summary') or {}
        if sealed:
            completeness = 'sealed'
        elif inventory and summary.get('pieces_missing'):
            completeness = 'incomplete'
        elif inventory and summary.get('rows_checked') == summary.get('rows'):
            completeness = 'complete'
        else:
            completeness = None
        with transaction(db), fixed_copy_id(copy['id']):
            items.ensure(db, item)
            copy_id, _ = add._add_copy(db, dict(item_id=item, condition='new' if sealed else 'used', completeness=completeness, note=None), 'cli', None)
            db.execute('UPDATE copy SET storage_id=?, place_id=?, purchase_date=?, purchase_price=?, purchase_currency=?, created_at=?, updated_at=? WHERE id=?',
                       ('storage-' + slug(copy['storage']), 'place-' + slug(copy['purchase_location']), copy['purchase_date'],
                        f"{copy['purchase_price']:.2f}" if copy.get('purchase_price') is not None else None,
                        'EUR' if copy.get('purchase_price') is not None else None, STAMP, STAMP, copy_id))
            for kind, names in (('status', copy['status']), ('tag', copy['tags']), ('owner', copy['owners'])):
                for name in names:
                    db.execute('INSERT INTO copy_flag(copy_id, flag_id) VALUES(?, ?)', (copy_id, flags[kind, name]))
            ids.setdefault(copy['set'], copy_id)
            if inventory:
                marked(db, copy_id, inventory, loose)
            # An invented used value for every owned set, so Prices and the set pages have numbers.
            if copy.get('purchase_price'):
                price(db, item, None, 'U', round(copy['purchase_price'] * 1.35, 2), 9, STAMP)
    with transaction(db):
        for wish in wishes:
            item = items.ensure(db, item_by(db, 'sets', wish['set']))
            db.execute('''INSERT INTO wish(id, wishlist_id, kind, item_id, color_id, quantity, condition, max_price, max_price_currency, added_at, updated_at)
                          VALUES(?, 'default', 'set', ?, NULL, 1, ?, ?, 'EUR', ?, ?)''', ('wish-' + slug(wish['set']), item, wish['condition'], f"{wish['max_price']:.2f}", STAMP, STAMP))
            for history in wish.get('price_history', []):
                if history.get('source') == 'bricklink' and history.get('slot') in ('new', 'used'):
                    price(db, item, None, 'N' if history['slot'] == 'new' else 'U', history['price'], None, history['observed_at'] + 'T06:00:00.000Z', current=False)
            for slot, condition in (('bricklink_new', 'N'), ('bricklink_used', 'U')):
                quote = (wish.get('prices') or {}).get(slot)
                if quote and quote.get('price') is not None:
                    price(db, item, None, condition, quote['price'], quote.get('sold'), quote['observed_at'] + 'T06:00:00.000Z', low=quote.get('min'), high=quote.get('max'))
        # Loose stock that can fill some gaps, so the Part Picker and Complete sets have matches.
        for part, colour, quantity in loose:
            stock.add_loose(db, item_id=part, color_id=colour, quantity=quantity, condition='used', storage_id='storage-parts-drawer-unit', via='cli')
    return ids


def marked(db, copy_id, inventory, loose):
    """The check state of the design test data on the copy's lines (the lines come from the catalogue's part list), the figure that is missing,
    and the price of each gap."""
    gaps = 0
    for row in inventory['parts']:
        if row.get('figure'):
            continue
        part, colour = item_by(db, 'parts', row['part']), colour_by(db, row['color']['id'])
        line = db.execute('SELECT id, quantity FROM copy_part WHERE copy_id=? AND item_id=? AND color_id=? AND is_spare=? AND copy_figure_id IS NULL AND retired_at IS NULL',
                          (copy_id, part, colour, int(bool(row.get('spare'))))).fetchone()
        if line is None:
            continue
        db.execute('UPDATE copy_part SET missing=?, damaged=?, checked=? WHERE id=?',
                   (min(row.get('missing') or 0, line['quantity']), min(row.get('damaged') or 0, line['quantity']), int(bool(row.get('checked'))), line['id']))
        if row.get('missing'):
            gaps += 1
            price(db, part, colour, 'U', round(0.04 + 0.03 * (gaps % 7), 2), 25, STAMP)
            if gaps % 2:
                loose.append((part, colour, row['missing']))
    for number, rows in inventory.get('minifigure_parts', {}).items():
        figure = db.execute('SELECT id FROM copy_figure WHERE copy_id=? AND item_id=? AND retired_at IS NULL', (copy_id, item_by(db, 'minifigs', number))).fetchone()
        for row in rows:
            db.execute('UPDATE copy_part SET missing=?, damaged=?, checked=? WHERE copy_id=? AND copy_figure_id=? AND item_id=? AND color_id=? AND retired_at IS NULL',
                       (row.get('missing') or 0, row.get('damaged') or 0, int(bool(row.get('checked'))), copy_id, figure['id'],
                        item_by(db, 'parts', row['part']), colour_by(db, row['color']['id'])))
    figures = inventory.get('minifigures', [])
    if inventory['set'] == '1592-1' and figures:
        db.execute('UPDATE copy_figure SET missing=1 WHERE copy_id=? AND item_id=? AND retired_at IS NULL', (copy_id, item_by(db, 'minifigs', figures[-1]['figure'])))


def price(db, item, colour, condition, value, sold, observed, *, low=None, high=None, current=True):
    """One BrickLink sold-guide observation (and, unless `current` is false, the one the screens show). The item is projected first."""
    items.ensure(db, item)
    if colour is not None:
        identity.project_color(db, colour)
    slot = 'bricklink_new' if condition == 'N' else 'bricklink_used'
    low, high = (f'{low:.2f}' if low is not None else None), (f'{high:.2f}' if high is not None else None)
    if current:
        base.observation(db, 'bricklink', item, guide='sold', price=f'{value:.2f}', currency='EUR', color_id=colour, condition=condition, slot=slot, region='eu',
                         qty=sold, sold=sold, minimum=low, maximum=high, observed_at=observed)
    else:
        db.execute('''INSERT INTO price_observation(item_id, color_id, condition, guide, slot, region, currency, price, qty, sold, min, max, source, observed_at)
                      VALUES(?, ?, ?, 'sold', ?, 'eu', 'EUR', ?, ?, ?, ?, ?, 'bricklink', ?)''',
                   (item, colour, 'new' if condition == 'N' else 'used', slot, f'{value:.2f}', sold, sold, low, high, observed))
