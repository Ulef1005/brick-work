"""Import a BrickTracker database into the 4.0 collection: plan, then apply, undone as a whole (M.8j, issue #110; design 3.1, 3.5, 4.3, 5).

BrickTracker stores Rebrickable numbers, and Rebrickable numbers are the catalogue's born keys, so nothing here translates anything: a set
number, a part number, a figure number and a colour number each name one item or colour, or none. Any upstream version is read: a copy of
the user's `app.db` is upgraded with upstream's own migrations (`bricktracker_upgrade`), then read; the file itself is never written.

`plan` writes nothing to the collection. It keeps the upgraded copy under `data/imports/<plan_id>/` and lists, per set, loose figure and
part, lot and wish, what applying would do: add it, skip it as already imported, or ask about a duplicate (the same set already held,
the same stock, lot name or wish). Whatever cannot be placed is listed with the reason (a set the catalogue does not know, a part line the
copy's part list lacks) and never guessed. Storages, purchase places and flags are matched by name and reused.

`apply` re-reads the stored copy (deterministic) and writes the chosen rows in one transaction with one `import:<plan>` receipt event, like
Add: an owned set becomes a copy through `store4.copies.create_copy_in` with design 4.3's preselection (its lines come from the part list,
BrickTracker's missing / damaged / checked marks are put on the lines they name), every other owned or loose thing becomes stock of its
current kind (a loose figure with its own part list, its marks on that list), a wish becomes a `wish`. `undo` reverses exactly that
receipt (`core.undo`) and refuses over later edits. BrickTracker records no currency: purchase prices take the collection's BrickLink
currency setting. Images and instruction files are not copied (Brick Work fetches pictures through its sources).
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from ...store4 import copies, pending
from ...store4.connect import has_catalogue, now as store_now
from .. import errors, items, stock
from .. import undo as undoing
from ..admin import audit, origin
from ..currency import configured_currency
from ..sources.base import now
from ..transaction import transaction
from . import bricktracker_upgrade

PLAN_TTL = timedelta(hours=24)
KINDS = ('copy', 'stock', 'lot', 'wish')
FLAG_KINDS = (('owners', 'owner'), ('statuses', 'status'), ('tags', 'tag'))
CHECKED = 'Set is checked'


def _store_path(db):
    return Path(db.execute('PRAGMA database_list').fetchone()[2])


def plans_root(db):
    return _store_path(db).parent / 'data' / 'imports'


# ---------- reading the upstream file ----------

def _rows(src, table):
    """The rows of an upstream table as dicts, `[]` when this schema version has no such table."""
    if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return []
    return [dict(r) for r in src.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]


def _day(value):
    """BrickTracker keeps dates as epoch seconds (REAL); the collection keeps a day."""
    if value is None or value == '':
        return None
    if isinstance(value, str):
        return value[:10]
    return datetime.fromtimestamp(value, timezone.utc).date().isoformat()


def _price(value):
    """A BrickTracker price (REAL) as the collection's text: two decimals where that says it exactly."""
    if value is None or value == '':
        return None
    number = Decimal(str(value))
    cents = number.quantize(Decimal('0.01'))
    return format(cents if number == cents else number, 'f')


def _custom_fields(src):
    """Upstream 0029's per-set custom fields, as 'Name: value' lines for the copy note (the collection has no column for them)."""
    names = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'bricktracker_metadata_custom_fields', 'bricktracker_set_custom_fields'} <= names:
        return {}
    columns = {r[1] for r in src.execute('PRAGMA table_info(bricktracker_set_custom_fields)')}
    fields = [(f['name'], 'custom_field_' + f['id']) for f in src.execute('SELECT id, name FROM bricktracker_metadata_custom_fields ORDER BY name')
              if 'custom_field_' + f['id'] in columns]
    notes = {}
    for row in src.execute('SELECT * FROM bricktracker_set_custom_fields'):
        lines = [f'{name}: {row[column]}' for name, column in fields if str(row[column] or '').strip()]
        if lines:
            notes[row['id']] = '\n'.join(lines)
    return notes


class Lookup:
    """Rebrickable numbers to the collection's ids: an item by (namespace, number), a colour by its Rebrickable number. Cached."""

    def __init__(self, db):
        self.db, self.found, self.colours = db, {}, {}
        self.stores = ('main', 'catalogue') if has_catalogue(db) else ('main',)

    def item(self, namespace, number):
        key = (namespace, str(number))
        if key not in self.found:
            found = None
            for store in self.stores:
                live = '' if store == 'main' else ' AND retired_at IS NULL'
                row = self.db.execute(f"SELECT id FROM {store}.item WHERE born_provider='rebrickable' AND born_namespace=? AND born_key=?{live}", key).fetchone()
                if row:
                    found = items._merged_target(self.db, row[0])
                    break
            self.found[key] = found
        return self.found[key]

    def colour(self, number):
        key = str(number)
        if key not in self.colours:
            found = None
            for store in self.stores:
                row = self.db.execute(f"SELECT id FROM {store}.color WHERE born_provider='rebrickable' AND born_key=?", (key,)).fetchone()
                if row:
                    found = row[0]
                    break
            self.colours[key] = found
        return self.colours[key]

    def describe(self, item_id):
        for store in self.stores:
            row = self.db.execute(f'SELECT kind, name, born_key FROM {store}.item WHERE id=?', (item_id,)).fetchone()
            if row:
                return dict(row)
        return None


def _flags(src):
    """`({('copy', id) or ('wish', set): [(kind, name)]}, [(kind, name, shown on grid)])` from the upstream flag tables: one boolean
    column per flag, named `<kind>_<flag id with underscores>`."""
    assigned, defs = {}, []
    for plural, kind in FLAG_KINDS:
        metadata = _rows(src, 'bricktracker_metadata_' + plural)
        defs.extend((kind, flag['name'], flag.get('displayed_on_grid', 1)) for flag in metadata)
        for table, key, who in (('bricktracker_set_' + plural, 'id', 'copy'), *((('bricktracker_wish_owners', 'set', 'wish'),) if kind == 'owner' else ())):
            for row in _rows(src, table):
                names = [(kind, flag['name']) for flag in metadata if row.get(kind + '_' + flag['id'].replace('-', '_')) == 1]
                if names:
                    assigned.setdefault((who, row[key]), []).extend(names)
    return assigned, defs


def project(db, path):
    """The upstream file as the collection would take it: `dict(copies, stock, lots, wishes, places, storages, flags, unplaced, kinds)`.

    Pure reading: nothing is written. Each entry carries the resolved item id, or goes to `unplaced` with its reason."""
    lookup = Lookup(db)
    unplaced = []
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as src:
        src.row_factory = sqlite3.Row
        storages = {r['id']: r['name'] for r in _rows(src, 'bricktracker_metadata_storages')}
        places = {r['id']: r['name'] for r in _rows(src, 'bricktracker_metadata_purchase_locations')}
        notes = _custom_fields(src)
        assigned, flag_defs = _flags(src)
        parts, figure_parts = {}, {}
        for table, found in (('bricktracker_parts', parts), ('bricktracker_individual_minifigure_parts', figure_parts)):
            for r in _rows(src, table):
                if r['missing'] or r['damaged'] or r['checked']:
                    found.setdefault(r['id'], []).append(r)
        out = dict(copies=[], stock=[], lots=[], wishes=[], unplaced=unplaced, storages=sorted(set(storages.values())),
                   places=sorted(set(places.values())), flags=flag_defs)

        def common(r):
            return dict(note=r.get('description') or None, storage=storages.get(r.get('storage')), place=places.get(r.get('purchase_location')),
                        date=_day(r.get('purchase_date')), price=_price(r.get('purchase_price')))

        def marks(rows, who):
            placed = []
            for p in rows:
                part, colour = lookup.item('parts', p['part']), lookup.colour(p['color'])
                figure = lookup.item('minifigs', p['figure']) if p.get('figure') else None
                if part is None or colour is None or (p.get('figure') and figure is None):
                    unplaced.append(dict(kind='mark', number=f"{p['part']}/{p['color']}", of=who, reason='The catalogue does not know this part or colour'))
                    continue
                placed.append(dict(part=part, colour=colour, spare=int(bool(p['spare'])), figure=figure, missing=p['missing'] or 0,
                                   damaged=p['damaged'] or 0, checked=int(bool(p['checked']))))
            return placed

        for r in _rows(src, 'bricktracker_individual_part_lots'):
            out['lots'].append(dict(id=r['id'], name=r['name'], created=_day(r['created_date']), **common(r)))
        for r in _rows(src, 'bricktracker_sets'):
            item = lookup.item('sets', r['set'])
            if item is None:
                unplaced.append(dict(kind='copy', number=r['set'], of=r['id'], reason='This set is not in the catalogue (add it by hand to fetch it from Rebrickable)'))
                continue
            entry = dict(id=r['id'], item=item, **common(r), flags=assigned.get(('copy', r['id']), []), marks=marks(parts.get(r['id'], ()), r['id']))
            if notes.get(r['id']):
                entry['note'] = '\n'.join(filter(None, (entry['note'], notes[r['id']])))
            out['copies'].append(entry)
        for r in _rows(src, 'bricktracker_individual_parts'):
            item, colour = lookup.item('parts', r['part']), lookup.colour(r['color'])
            if item is None or colour is None:
                unplaced.append(dict(kind='stock', number=f"{r['part']}/{r['color']}", of=r['id'], reason='The catalogue does not know this part or colour'))
                continue
            out['stock'].append(dict(id=r['id'], item=item, colour=colour, quantity=r['quantity'], lot=r.get('lot_id'),
                                     state=dict(missing=r.get('missing'), damaged=r.get('damaged'), checked=r.get('checked')), flags=assigned.get(('copy', r['id']), []), **common(r)))
        for r in _rows(src, 'bricktracker_individual_minifigures'):
            item = lookup.item('minifigs', r['figure'])
            if item is None:
                unplaced.append(dict(kind='stock', number=r['figure'], of=r['id'], reason='The catalogue does not know this figure'))
                continue
            out['stock'].append(dict(id=r['id'], item=item, colour=None, quantity=r['quantity'], lot=None, state=None, flags=assigned.get(('copy', r['id']), []), **common(r),
                                     marks=marks(figure_parts.get(r['id'], ()), r['id'])))
        for index, r in enumerate(_rows(src, 'bricktracker_wishes')):
            number = r['set']
            if isinstance(number, str) and number.startswith('['):                  # a part wish: '[part, colour]' (the fork's encoding)
                try:
                    part, colour = json.loads(number)
                except ValueError:
                    part = colour = None
                item, colour_id, label = lookup.item('parts', part), lookup.colour(colour), f'{part}/{colour}'
                if item is None or colour_id is None:
                    unplaced.append(dict(kind='wish', number=label, of=number, reason='The catalogue does not know this part or colour'))
                    continue
            else:
                item, colour_id, label = lookup.item('sets', number), None, number
                if item is None:
                    unplaced.append(dict(kind='wish', number=label, of=number, reason='This set is not in the catalogue'))
                    continue
            out['wishes'].append(dict(id=f'{index}:{number}', item=item, colour=colour_id, flags=assigned.get(('wish', number), [])))
    out['kinds'] = {entry['item']: lookup.describe(entry['item']) for kind in ('copies', 'stock', 'wishes') for entry in out[kind]}
    return out


# ---------- the plan ----------

def _cleanup(root):
    if not root.is_dir():
        return
    cutoff = now() - PLAN_TTL
    for work in root.iterdir():
        if not (work.is_dir() and len(work.name) == 32 and work.name.isalnum()):
            continue                                     # only plan folders; uploads/ is the API's in-flight files
        try:
            meta = json.loads((work / 'plan.json').read_text())
            if datetime.fromisoformat(meta['created_at']) < cutoff or meta.get('applied'):
                shutil.rmtree(work, ignore_errors=True)
        except (OSError, ValueError, KeyError):
            shutil.rmtree(work, ignore_errors=True)


def _norm(text):
    return ' '.join(str(text or '').casefold().split())


def _imported(db):
    """BrickTracker ids an earlier, not undone import into this collection placed."""
    found = set()
    for row in db.execute("""SELECT e.new_value FROM main.event e WHERE e.entity_kind='import' AND e.field='receipt'
                             AND NOT EXISTS(SELECT 1 FROM main.event_undo u WHERE u.event_id=e.id)"""):
        found.update(json.loads(row[0]).get('origin', {}))
    return found


def _plan_rows(db, data):
    """Plan rows with a suggested action; keys reference the upstream rows."""
    done = _imported(db)
    live_copies = {r[0] for r in db.execute('SELECT DISTINCT item_id FROM main.copy WHERE archived_at IS NULL')}
    live_stock = {(r['item_id'], r['color_id']) for r in db.execute('SELECT item_id, color_id FROM main.stock WHERE archived_at IS NULL')}
    live_lots = {_norm(r[0]) for r in db.execute('SELECT name FROM main.lot WHERE archived_at IS NULL')}
    live_wishes = {(r['item_id'], r['color_id']) for r in db.execute("SELECT item_id, color_id FROM main.wish WHERE archived_at IS NULL AND wishlist_id='default'")}
    rows, kinds = [], data['kinds']

    def add(key, kind, label, number, state, **extra):
        rows.append(dict(key=f'{kind}:{key}', kind=kind, label=label, number=number, state=state, action='add' if state == 'new' else 'skip',
                         locked=state == 'imported', **extra))
    for c in data['copies']:
        described = kinds[c['item']]
        state = 'imported' if c['id'] in done else 'duplicate' if c['item'] in live_copies else 'new'
        add(c['id'], 'copy', described['name'], described['born_key'], state, here=int(c['item'] in live_copies), marks=len(c['marks']))
    for s in data['stock']:
        described = kinds[s['item']]
        state = 'imported' if s['id'] in done else 'duplicate' if (s['item'], s['colour']) in live_stock else 'new'
        add(s['id'], 'stock', described['name'], described['born_key'], state, quantity=s['quantity'], color_id=s['colour'])
    for lot in data['lots']:
        state = 'imported' if lot['id'] in done else 'duplicate' if _norm(lot['name']) in live_lots else 'new'
        add(lot['id'], 'lot', lot['name'] or lot['id'], None, state)
    for w in data['wishes']:
        described = kinds[w['item']]
        state = 'duplicate' if (w['item'], w['colour']) in live_wishes else 'new'
        add(w['id'], 'wish', described['name'], described['born_key'], state, color_id=w['colour'])
        rows[-1]['locked'] = state == 'duplicate'
    return rows


def _summary(data, rows, db):
    def live(table):
        return {_norm(r[0]) for r in db.execute(f'SELECT name FROM main.{table} WHERE archived_at IS NULL')}
    out = {kind: {state: sum(1 for r in rows if r['kind'] == kind and r['state'] == state) for state in ('new', 'duplicate', 'imported')} for kind in KINDS}
    for name, wanted, table in (('storages', data['storages'], 'storage'), ('purchase_locations', data['places'], 'place')):
        known = live(table)
        out[name] = dict(new=sum(_norm(n) not in known for n in wanted), reused=sum(_norm(n) in known for n in wanted))
    known = {(_norm(r['name']), r['kind']) for r in db.execute('SELECT name, kind FROM main.flag WHERE archived_at IS NULL')}
    out['flags'] = dict(new=sum((_norm(n), k) not in known for k, n, _ in data['flags']), reused=sum((_norm(n), k) in known for k, n, _ in data['flags']))
    out['marks'] = sum(len(c['marks']) for c in data['copies']) + sum(len(s.get('marks') or ()) for s in data['stock'])
    out['unplaced'] = len(data['unplaced'])
    return out


def plan(db, source, *, name=None):
    """Upgrade a copy of `source`, read it and compare it with the collection. Writes nothing to the collection."""
    root = plans_root(db)
    _cleanup(root)
    plan_id = uuid4().hex
    work = root / plan_id
    work.mkdir(parents=True)
    try:
        version_from, version_to = bricktracker_upgrade.upgraded_copy(source, work / 'app.db')
        data = project(db, work / 'app.db')
        rows = _plan_rows(db, data)
        result = dict(id=plan_id, created_at=now().isoformat(), source=name or Path(source).name,
                      schema=dict(found=version_from, upgraded_to=version_to),
                      fresh=not db.execute('SELECT 1 FROM main.copy UNION ALL SELECT 1 FROM main.stock UNION ALL SELECT 1 FROM main.wish LIMIT 1').fetchone(),
                      summary=_summary(data, rows, db), unplaced=data['unplaced'], rows=rows)
        (work / 'plan.json').write_text(json.dumps(result))
        return result
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def load_plan(db, plan_id):
    if not isinstance(plan_id, str) or not plan_id.isalnum() or len(plan_id) != 32:
        raise ValueError('Unknown import plan')
    work = plans_root(db) / plan_id
    try:
        meta = json.loads((work / 'plan.json').read_text())
    except (OSError, ValueError):
        raise ValueError('This import plan has expired · upload the file again') from None
    if datetime.fromisoformat(meta['created_at']) < now() - PLAN_TTL:
        raise ValueError('This import plan has expired · upload the file again')
    return work, meta


def _decide(meta, decisions):
    """Effective action per row: locked rows keep theirs; others take a valid decision or the suggestion."""
    decisions = decisions or {}
    if not isinstance(decisions, dict):
        raise ValueError('Send decisions as {row key: "add" or "skip"}')
    keys = {r['key'] for r in meta['rows']}
    unknown = set(decisions) - keys
    if unknown:
        raise ValueError('Unknown import rows: ' + ', '.join(sorted(unknown)[:5]))
    actions = {}
    for r in meta['rows']:
        choice = decisions.get(r['key'], r['action'])
        if choice not in ('add', 'skip'):
            raise ValueError('Choose add or skip')
        actions[r['key']] = r['action'] if r['locked'] else choice
    return actions


# ---------- apply ----------

def _named(db, table, names, kind, receipt, field, stamp, **extra):
    """The id per name: the live row of that name (and kind) is reused, else one is made (and recorded for Undo)."""
    known = {(_norm(r['name']), r['kind'] if kind else None): r['id'] for r in
             db.execute(f'SELECT id, name{", kind" if kind else ""} FROM main.{table} WHERE archived_at IS NULL')}
    out = {}
    for name in names:
        key = (_norm(name), kind)
        if key not in known:
            identifier = uuid4().hex
            columns = dict(id=identifier, name=name, created_at=stamp, **({'kind': kind} if kind else {}), **extra)
            db.execute(f'INSERT INTO main.{table}({", ".join(columns)}) VALUES({", ".join("?" * len(columns))})', tuple(columns.values()))
            audit(db, f'{table}:{identifier}', 'created', None, columns)
            receipt[field].append(identifier)
            known[key] = identifier
        out[name] = known[key]
    return out


def _mark(db, table, owner, marks):
    """Put BrickTracker's marks on the lines they name (a copy's, or a loose figure's). Returns the marks with no such line."""
    lost = []
    for m in marks:
        if table == 'copy_part':
            scope = 'AND copy_figure_id IS NULL' if m['figure'] is None else 'AND copy_figure_id=(SELECT id FROM main.copy_figure WHERE copy_id=? AND item_id=? AND retired_at IS NULL)'
            args = (owner, m['part'], m['colour'], m['spare']) + (() if m['figure'] is None else (owner, m['figure']))
            row = db.execute(f'SELECT id, quantity FROM main.copy_part WHERE copy_id=? AND item_id=? AND color_id=? AND is_spare=? AND retired_at IS NULL {scope}', args).fetchone()
        else:
            row = db.execute('SELECT id, quantity FROM main.stock_part WHERE stock_id=? AND item_id=? AND color_id=? AND is_spare=? AND retired_at IS NULL',
                             (owner, m['part'], m['colour'], m['spare'])).fetchone()
        if row is None:
            lost.append(m)
            continue
        db.execute(f'UPDATE main.{table} SET missing=?, damaged=?, checked=? WHERE id=?',
                   (min(m['missing'], row['quantity']), min(m['damaged'], row['quantity']), m['checked'], row['id']))
    return lost


def _line_digest(db, copy_id):
    rows = [list(r) for r in db.execute('SELECT id, missing, damaged, checked, retired_at FROM main.copy_part WHERE copy_id=? ORDER BY id', (copy_id,))]
    rows += [list(r) for r in db.execute('SELECT id, missing, retired_at FROM main.copy_figure WHERE copy_id=? ORDER BY id', (copy_id,))]
    return json.dumps(rows)


def _flag_ids(db, copy_id):
    return sorted(r[0] for r in db.execute('SELECT flag_id FROM main.copy_flag WHERE copy_id=?', (copy_id,)))


def _finish_stock(db, change, entry, places, currency):
    """What `add_loose` does not take: place, purchase and BrickTracker's state of a loose part. On a row this import created the state is
    BrickTracker's; on a pile it was added onto, the counts are added (capped by the new quantity) and `checked` stays only when both were
    checked, as a stock merge on edit does; the receipt's `after` is the row as left, so Undo can restore `before` exactly."""
    state = entry.get('state') or {}
    checked = state.get('checked')
    if change['created']:
        db.execute('UPDATE main.stock SET place_id=?, purchase_date=?, purchase_price=?, purchase_currency=?, missing=?, damaged=?, checked=? WHERE id=?',
                   (places.get(entry['place']), entry['date'], entry['price'], currency if entry['price'] is not None else None, state.get('missing'),
                    state.get('damaged'), None if checked is None else int(bool(checked)), change['id']))
    elif entry.get('state') is not None:
        merged = stock.merge_state(change['before'], dict(state, checked=None if checked is None else int(bool(checked))), change['after']['quantity'])
        db.execute('UPDATE main.stock SET missing=?, damaged=?, checked=? WHERE id=?', (merged['missing'], merged['damaged'], merged['checked'], change['id']))
    change['after'] = dict(db.execute('SELECT * FROM main.stock WHERE id=?', (change['id'],)).fetchone())


def apply(db, plan_id, decisions=None, *, queue=True):
    """Write the chosen rows in one transaction; returns the receipt event id and counts."""
    from .. import add, plans, wishlists
    from ..pipeline import queue_new_items
    work, meta = load_plan(db, plan_id)
    done = plans.applied(db, 'import', plan_id)                  # the database decides; the plan file can say applied for a write that rolled back
    if done:
        return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
    actions = _decide(meta, decisions)
    if not (work / 'app.db').is_file():
        raise ValueError('This import plan was already used · upload the file again')
    via, actor = origin()
    stamp = store_now()
    receipt = dict(plan=plan_id, source=meta['source'], origin={}, copies=[], guards={}, stock=[], lots=[], storages=[], places=[], flags=[], wishes=[],
                   copy_flags=[], stock_flags=[], wish_flags=[], unplaced_marks=[], pending=[], jobs=[])
    with transaction(db):
        done = plans.applied(db, 'import', plan_id)              # checked again under the write lock: a second submit waits here and finds the marker
        if done:
            return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
        data = project(db, work / 'app.db')                      # inside the lock: the same catalogue the apply writes against
        currency = configured_currency(db)
        storages = _named(db, 'storage', data['storages'], None, receipt, 'storages', stamp)
        places = _named(db, 'place', data['places'], None, receipt, 'places', stamp)
        flags = {}
        for kind, name, shown in data['flags']:
            flags[kind, name] = _named(db, 'flag', [name], kind, receipt, 'flags', stamp, shown_on_grid=int(bool(shown)))[name]
        lot_map = {}
        live_lots = {_norm(r['name']): r['id'] for r in db.execute('SELECT id, name FROM main.lot WHERE archived_at IS NULL')}
        for lot in data['lots']:
            if actions.get('lot:' + lot['id']) == 'add':
                identifier = uuid4().hex
                db.execute('INSERT INTO main.lot(id, name, note, storage_id, place_id, purchase_date, purchase_price, purchase_currency, created_at, updated_at) '
                           'VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (identifier, lot['name'], lot['note'], storages.get(lot['storage']), places.get(lot['place']), lot['date'], lot['price'],
                            currency if lot['price'] is not None else None, f"{lot['created']}T00:00:00.000Z" if lot['created'] else stamp, stamp))
                audit(db, 'lot:' + identifier, 'created', None, dict(db.execute('SELECT * FROM main.lot WHERE id=?', (identifier,)).fetchone()))
                receipt['lots'].append(identifier)
                receipt['origin'][lot['id']] = identifier
                lot_map[lot['id']] = identifier
            elif _norm(lot['name']) in live_lots:
                lot_map[lot['id']] = live_lots[_norm(lot['name'])]
        touched = set()

        def flag_rows(table, column, row_id, names):
            for kind, name in names:
                target = flags.get((kind, name))
                if target and not db.execute(f'SELECT 1 FROM main.{table} WHERE {column}=? AND flag_id=?', (row_id, target)).fetchone():
                    db.execute(f'INSERT INTO main.{table}({column}, flag_id) VALUES(?, ?)', (row_id, target))
                    receipt[table + 's'].append([row_id, target])

        for entry in data['copies']:
            if actions.get('copy:' + entry['id']) != 'add':
                continue
            items.ensure(db, entry['item'])
            touched.add(entry['item'])
            if data['kinds'][entry['item']]['kind'] != 'set':        # placed by its current kind (design 3.5)
                change = stock.add_loose(db, item_id=entry['item'], quantity=1, condition=None, storage_id=storages.get(entry['storage']),
                                         note=entry['note'], via=via, actor=actor)
                _finish_stock(db, change, entry, places, currency)
                receipt['stock'].append(change)
                receipt['origin'][entry['id']] = change['id']
                flag_rows('stock_flag', 'stock_id', change['id'], entry['flags'])
                continue
            copy_id, waiting = add._add_copy(db, dict(item_id=entry['item'], condition=None, completeness=None, note=entry['note']), via, actor)
            db.execute('UPDATE main.copy SET storage_id=?, place_id=?, purchase_date=?, purchase_price=?, purchase_currency=? WHERE id=?',
                       (storages.get(entry['storage']), places.get(entry['place']), entry['date'], entry['price'],
                        currency if entry['price'] is not None else None, copy_id))
            flag_rows('copy_flag', 'copy_id', copy_id, entry['flags'])
            for m in _mark(db, 'copy_part', copy_id, entry['marks']):
                receipt['unplaced_marks'].append(dict(of=entry['id'], part=m['part'], colour=m['colour'], reason="The copy's part list has no such line"))
            if any(name == CHECKED for _, name in entry['flags']) or any(m['missing'] or m['damaged'] for m in entry['marks']):
                db.execute("UPDATE main.copy SET completeness_source='derived' WHERE id=? AND completeness_source IS NULL", (copy_id,))
                derived = copies.derived_completeness(db, copy_id)
                if derived:
                    db.execute('UPDATE main.copy SET completeness=? WHERE id=?', (derived, copy_id))
            receipt['copies'].append(copy_id)
            receipt['origin'][entry['id']] = copy_id
            receipt['guards'][copy_id] = dict(row=dict(db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()),
                                              lines=_line_digest(db, copy_id), flags=_flag_ids(db, copy_id))
            if waiting:
                receipt['pending'].append(dict(waiting, copy_id=copy_id))
        for entry in data['stock']:
            if actions.get('stock:' + entry['id']) != 'add':
                continue
            items.ensure(db, entry['item'])
            touched.add(entry['item'])
            change = stock.add_loose(db, item_id=entry['item'], color_id=entry['colour'], quantity=entry['quantity'], condition=None,
                                     lot_id=lot_map.get(entry['lot']), storage_id=storages.get(entry['storage']), note=entry['note'], via=via, actor=actor)
            _finish_stock(db, change, entry, places, currency)
            flag_rows('stock_flag', 'stock_id', change['id'], entry['flags'])
            if change['created'] and entry.get('marks'):
                for m in _mark(db, 'stock_part', change['id'], entry['marks']):
                    receipt['unplaced_marks'].append(dict(of=entry['id'], part=m['part'], colour=m['colour'], reason="The figure's part list has no such line"))
                summary = db.execute('SELECT sum(missing), sum(damaged), min(checked) FROM main.stock_part WHERE stock_id=? AND retired_at IS NULL', (change['id'],)).fetchone()
                db.execute('UPDATE main.stock SET missing=?, damaged=?, checked=? WHERE id=?', (*summary, change['id']))
                change['after'] = dict(db.execute('SELECT * FROM main.stock WHERE id=?', (change['id'],)).fetchone())
                change['parts'] = stock.part_digest(db, change['id'])                   # the lines as the import left them: Undo compares
            receipt['stock'].append(change)
            receipt['origin'][entry['id']] = change['id']
        wishlists.require(db, 'default')
        for entry in data['wishes']:
            if actions.get('wish:' + entry['id']) != 'add':
                continue
            items.ensure(db, entry['item'])
            touched.add(entry['item'])
            scratch = {}
            add._add_wish(db, dict(list_id='default', item_id=entry['item'], kind=data['kinds'][entry['item']]['kind'], color_id=entry['colour'],
                                   quantity=1, condition='any', decision='another'), scratch, via, actor)
            receipt['wishes'].append(scratch['wish'])
            receipt['origin'][entry['id']] = scratch['wish']['id']
            flag_rows('wish_flag', 'wish_id', scratch['wish']['id'], entry['flags'])
        receipt['jobs'] = queue_new_items(db, touched) if queue else []
        counts = dict(copies=len(receipt['copies']), stock=sum(c['quantity'] for c in receipt['stock']), lots=len(receipt['lots']),
                      wishes=len(receipt['wishes']), storages=len(receipt['storages']), purchase_locations=len(receipt['places']),
                      flags=len(receipt['flags']))
        receipt['counts'] = counts
        audit(db, 'import:' + plan_id, 'receipt', None, receipt, via=via, actor=actor)
        event = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        plans.mark(db, 'import', plan_id, dict(event_id=event, counts=counts, at=stamp), source=meta['source'], created_at=meta['created_at'])
    meta.update(applied=True, applied_event=event, applied_counts=counts, applied_at=stamp)
    (work / 'plan.json').write_text(json.dumps(meta))
    (work / 'app.db').unlink(missing_ok=True)
    return dict(event_id=event, already_applied=False, counts=counts)


# ---------- undo ----------

def _used(db, sql, ident):
    return db.execute(sql, (ident,)).fetchone() is not None


def _undo_import(db, event, via, actor):
    """Reverse one import exactly: archive the copies, stock, wishes, lots, places and flags it made (taking quantities back off merged
    stock). Refused whole when anything it made changed since (undo the later change first)."""
    r = json.loads(event['new_value'])
    stamp = store_now()
    changed = 'Something from this import has changed since · undo the later change first'
    for entry in r['wishes']:
        row = db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()
        if row is None or dict(row) != entry['after']:
            raise ValueError(changed)
    for copy_id in r['copies']:
        guard = r['guards'][copy_id]
        row = db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()
        if row is None:
            raise ValueError(changed)
        if row['archived_at'] is None and (dict(row) != guard['row'] or _line_digest(db, copy_id) != guard['lines'] or _flag_ids(db, copy_id) != guard['flags']
                                           or any(db.execute(sql, (copy_id,)).fetchone() for sql in (
                                               'SELECT 1 FROM main.part_check WHERE copy_id=? LIMIT 1', 'SELECT 1 FROM main.stock_transfer WHERE copy_id=? LIMIT 1',
                                               'SELECT 1 FROM main.photo WHERE copy_id=? AND archived_at IS NULL LIMIT 1', 'SELECT 1 FROM main.allocation WHERE copy_id=? LIMIT 1'))):
            raise ValueError(changed)
    for entry in reversed(r['wishes']):
        row = db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()
        if entry['created']:
            db.execute('UPDATE main.wish SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, entry['id']))
        else:
            b = entry['before']
            db.execute('UPDATE main.wish SET quantity=?, updated_at=? WHERE id=?', (b['quantity'], b['updated_at'], entry['id']))
        audit(db, 'wish:' + entry['id'], 'undo_import', dict(row), dict(db.execute('SELECT * FROM main.wish WHERE id=?', (entry['id'],)).fetchone()), via=via, actor=actor)
    for change in reversed(r['stock']):
        stock.undo_added(db, change, via=via, actor=actor)
    for stock_id, flag_id in r['stock_flags']:                   # only the links this import made: a pile that had the tag keeps it
        db.execute('DELETE FROM main.stock_flag WHERE stock_id=? AND flag_id=?', (stock_id, flag_id))
    for copy_id in reversed(r['copies']):
        row = db.execute('SELECT * FROM main.copy WHERE id=?', (copy_id,)).fetchone()
        if row['archived_at'] is not None:
            continue                                             # archived since: nothing to undo
        if row['inventory_pending']:
            pending.cancel_pending_in(db, copy_id, via=via, actor=actor)
        db.execute('UPDATE main.copy SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, copy_id))
        audit(db, 'copy:' + copy_id, 'archived_at', None, stamp, via=via, actor=actor)
    for lot in r['lots']:
        if not _used(db, 'SELECT 1 FROM main.stock WHERE lot_id=? AND archived_at IS NULL LIMIT 1', lot):
            db.execute('UPDATE main.lot SET archived_at=?, updated_at=? WHERE id=?', (stamp, stamp, lot))
    for table, ids in (('storage', r['storages']), ('place', r['places'])):
        for ident in ids:
            if not any(_used(db, f'SELECT 1 FROM main.{t} WHERE {table}_id=? AND archived_at IS NULL LIMIT 1', ident) for t in ('copy', 'stock', 'lot')):
                db.execute(f'UPDATE main.{table} SET archived_at=? WHERE id=?', (stamp, ident))
    for ident in r['flags']:
        if not any(_used(db, sql, ident) for sql in (
                'SELECT 1 FROM main.copy_flag f JOIN main.copy c ON c.id=f.copy_id WHERE f.flag_id=? AND c.archived_at IS NULL LIMIT 1',
                'SELECT 1 FROM main.stock_flag f JOIN main.stock c ON c.id=f.stock_id WHERE f.flag_id=? AND c.archived_at IS NULL LIMIT 1',
                'SELECT 1 FROM main.wish_flag f JOIN main.wish c ON c.id=f.wish_id WHERE f.flag_id=? AND c.archived_at IS NULL LIMIT 1')):
            db.execute('UPDATE main.flag SET archived_at=? WHERE id=?', (stamp, ident))
    audit(db, 'import:' + r['plan'], 'undo', None, {'undoes': event['id']}, via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


undoing.register('import', 'receipt', _undo_import)


def receipt_of(db, event_id):
    row = db.execute("SELECT new_value FROM main.event WHERE id=? AND entity_kind='import' AND field='receipt'", (event_id,)).fetchone()
    if not row:
        raise errors.NotFound('Import not found')
    return json.loads(row[0])


def undo(db, event_id):
    """Reverse one import exactly (`core.undo`); refused over later edits."""
    return undoing.undo_event(db, event_id)
