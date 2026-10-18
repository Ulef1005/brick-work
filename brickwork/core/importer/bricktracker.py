"""Import a BrickTracker database into an existing Brick Work store: plan, then apply, undoable as a whole.

Any upstream version: a copy of the user's `app.db` is upgraded with upstream's own migrations
(`bricktracker_upgrade`), then mapped with the existing projection (`projection.project`) without a
decisions file: Rebrickable ids translate through the database's own BrickLink bridge and the BrickLink
catalogue; anything that does not map stays a `?` item on the unresolved list, never a guess.

`plan` writes nothing to the store. It keeps the upgraded copy under `data/imports/<plan_id>/` and
lists, per copy, loose-stock row, lot and wish, what applying would do: add it, skip it as already
imported (same id), or ask about a duplicate (same set, same part and colour and condition, same lot
name, same wish). Storages, purchase places and flags are matched by name and reused.

`apply` re-projects the stored copy (deterministic) and writes the chosen rows in one transaction
with one `bw_import` receipt; `undo` reverses exactly that receipt and refuses over later edits.
Images and instruction files are not copied (Brick Work fetches pictures through its sources).
"""
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from ..admin import audit
from ..sources.base import now
from ..transaction import transaction
from . import bricktracker_upgrade
from .projection import project

PLAN_TTL = timedelta(hours=24)
KINDS = ('copy', 'stock', 'lot', 'wish')
REFERENCE = ('items', 'colors', 'item_properties', 'id_match', 'source_records', 'search_index')


def _store_path(db):
    return Path(db.execute('PRAGMA database_list').fetchone()[2])


def plans_root(db):
    return _store_path(db).parent / 'data' / 'imports'


def _catalogue(db):
    path = _store_path(db).with_name('bricklink-catalog.db')
    if not path.is_file():
        raise ValueError('Load the BrickLink catalogue first (Tools & Admin → Catalogues & keys)')
    return path


def _project(work, catalogue, db):
    extras = work / 'extras.db'
    if not extras.is_file():
        with closing(sqlite3.connect(extras)) as e, e:
            e.executescript((Path(__file__).with_name('empty-extras.sql')).read_text())
            pairs, names = _color_map(db, work / 'app.db')
            e.executemany('INSERT INTO color_map(bricklink_color_id,color_id) VALUES(?,?)', sorted(pairs))
            # Colour names for the store's colors table: the store's own first, then upstream's.
            known = {r['color_id']: (r['name'], r['type']) for r in db.execute('SELECT color_id,name,type FROM colors')}
            e.executemany('INSERT INTO bricklink_colors(id,name,type) VALUES(?,?,?)',
                          [(bl, *known.get(bl, (names.get(bl), None))) for bl in sorted({bl for bl, _ in pairs})])
    decisions = work / 'decisions.json'
    if not decisions.is_file():
        decisions.write_text('{}')
    expected, _ = project(work / 'app.db', extras, decisions, catalogue)
    notes = _custom_fields(work / 'app.db')
    for copy in expected['copies']:
        if notes.get(copy['id']):
            copy['note'] = '\n'.join(filter(None, (copy.get('note'), notes[copy['id']])))
    return expected


def _color_map(db, path):
    """Rebrickable colour id -> BrickLink colour id without the old extras file.

    Sources, strongest first: this store's matched colour ids, upstream's rebrickable_colors (0024),
    then the BrickLink colour cached on rebrickable_parts. Disagreeing evidence leaves the colour
    unmapped, so its parts land on the unresolved list instead of being guessed. Returns color_map rows
    as (bricklink_color_id, rebrickable_color_id) and upstream's BrickLink colour names.
    """
    found, names = {}, {}
    for row in db.execute("SELECT source_id,color_id FROM id_match WHERE source='rebrickable' AND kind='color' "
                          "AND status IN ('matched','manual') AND color_id IS NOT NULL"):
        if str(row['source_id']).lstrip('-').isdigit():
            found.setdefault(int(row['source_id']), set()).add(row['color_id'])
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as src:
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        layers = []
        if 'rebrickable_colors' in tables:
            layers.append(src.execute('SELECT color_id,bricklink_color_id,bricklink_color_name FROM rebrickable_colors '
                                      'WHERE bricklink_color_id IS NOT NULL').fetchall())
        if 'bricklink_color_id' in {r[1] for r in src.execute('PRAGMA table_info(rebrickable_parts)')}:
            layers.append(src.execute('SELECT DISTINCT color_id,bricklink_color_id,bricklink_color_name '
                                      'FROM rebrickable_parts WHERE bricklink_color_id IS NOT NULL').fetchall())
    for layer in layers:
        seen = {}
        for rb, bl, name in layer:
            seen.setdefault(rb, set()).add(bl)
            if name:
                names.setdefault(bl, name)
        for rb, bls in seen.items():
            found.setdefault(rb, bls)
    return {(bl, rb) for rb, bls in found.items() for bl in bls}, names


def _custom_fields(path):
    """Upstream 0029's per-set custom fields, as 'Name: value' lines for the copy note (no column here)."""
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as src:
        src.row_factory = sqlite3.Row
        names = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'bricktracker_metadata_custom_fields', 'bricktracker_set_custom_fields'} <= names:
            return {}
        columns = {r[1] for r in src.execute('PRAGMA table_info(bricktracker_set_custom_fields)')}
        fields = [(f['name'], 'custom_field_' + f['id']) for f in
                  src.execute('SELECT id,name FROM bricktracker_metadata_custom_fields ORDER BY name')
                  if 'custom_field_' + f['id'] in columns]
        notes = {}
        for row in src.execute('SELECT * FROM bricktracker_set_custom_fields'):
            lines = [f'{name}: {row[column]}' for name, column in fields if str(row[column] or '').strip()]
            if lines:
                notes[row['id']] = '\n'.join(lines)
        return notes


def _cleanup(root):
    if not root.is_dir():
        return
    cutoff = now() - PLAN_TTL
    for work in root.iterdir():
        if not (work.is_dir() and len(work.name) == 32 and work.name.isalnum()):
            continue  # only plan folders; uploads/ is the API's in-flight files
        try:
            meta = json.loads((work / 'plan.json').read_text())
            from datetime import datetime
            if datetime.fromisoformat(meta['created_at']) < cutoff or meta.get('applied'):
                shutil.rmtree(work, ignore_errors=True)
        except (OSError, ValueError, KeyError):
            shutil.rmtree(work, ignore_errors=True)


def _norm(text):
    return ' '.join(str(text or '').casefold().split())


def _names(db, table):
    return {_norm(r['name']): r['id'] for r in db.execute(f'SELECT id,name FROM {table}' +
                                                          (' WHERE archived_at IS NULL' if table == 'storages' else ''))}


def _label(expected, kind, number):
    item = next((r for r in expected['items'] if r['item_type'] == kind and r['item_no'] == number), None)
    return (item or {}).get('name') or number


def _rows(db, expected):
    """Plan rows with a suggested action; ids reference the projected rows."""
    copies_here = {r['id'] for r in db.execute('SELECT id FROM copies')}
    stock_here = {r['id'] for r in db.execute('SELECT id FROM loose_stock')}
    lots_here = {r['id'] for r in db.execute('SELECT id FROM lots')}
    live_sets = {}
    for r in db.execute('SELECT item_type,set_no,count(*) n FROM copies WHERE archived_at IS NULL GROUP BY 1,2'):
        live_sets[r['item_type'], r['set_no']] = r['n']
    live_stock = {(r['item_type'], r['item_no'], r['color_id'], r['condition']): r['quantity']
                  for r in db.execute('SELECT item_type,item_no,color_id,condition,sum(quantity) quantity FROM loose_stock '
                                      'WHERE archived_at IS NULL GROUP BY 1,2,3,4')}
    live_lots = _names(db, 'lots')
    live_wishes = {(r['item_type'], r['item_no'], r['color_id']) for r in
                   db.execute("SELECT item_type,item_no,color_id FROM wishlist WHERE archived_at IS NULL AND list_id='default'")}
    parts = {}
    for p in expected['copy_parts']:
        n = parts.setdefault(p['copy_id'], [0, 0])
        n[0] += p['quantity'] or 0
        n[1] += p['missing'] or 0
    rows = []
    for c in expected['copies']:
        key = (c['item_type'], c['set_no'])
        state = 'imported' if c['id'] in copies_here else 'duplicate' if key in live_sets else 'new'
        rows.append(dict(key='copy:' + c['id'], kind='copy', item_type=c['item_type'], item_no=c['set_no'],
                         label=_label(expected, *key), state=state, action='add' if state == 'new' else 'skip',
                         locked=state == 'imported', here=live_sets.get(key, 0),
                         detail=dict(parts=parts.get(c['id'], [0, 0])[0], missing=parts.get(c['id'], [0, 0])[1])))
    for s in expected['loose_stock']:
        key = (s['item_type'], s['item_no'], s['color_id'], s['condition'])
        state = 'imported' if s['id'] in stock_here else 'duplicate' if key in live_stock else 'new'
        rows.append(dict(key='stock:' + s['id'], kind='stock', item_type=s['item_type'], item_no=s['item_no'],
                         color_id=s['color_id'], condition=s['condition'], quantity=s['quantity'],
                         label=_label(expected, s['item_type'], s['item_no']), state=state,
                         action='add' if state == 'new' else 'skip', locked=state == 'imported', here=live_stock.get(key, 0)))
    for lot in expected['lots']:
        state = 'imported' if lot['id'] in lots_here else 'duplicate' if _norm(lot['name']) in live_lots else 'new'
        rows.append(dict(key='lot:' + lot['id'], kind='lot', label=lot['name'] or lot['id'], state=state,
                         action='add' if state == 'new' else 'skip', locked=state == 'imported'))
    for w in expected['wishlist']:
        key = (w['item_type'], w['item_no'], w['color_id'])
        state = 'duplicate' if key in live_wishes else 'new'
        rows.append(dict(key=f"wish:{w['id']}", kind='wish', item_type=w['item_type'], item_no=w['item_no'],
                         color_id=w['color_id'], quantity=w['quantity'], label=_label(expected, w['item_type'], w['item_no']),
                         state=state, action='add' if state == 'new' else 'skip', locked=state == 'duplicate'))
    return rows


def _unresolved(expected):
    used = {(c['item_type'], c['set_no']) for c in expected['copies']}
    used |= {(r['item_type'], r['item_no']) for t in ('loose_stock', 'wishlist', 'copy_parts') for r in expected[t]}
    used |= {(r['item_type'], r['minifig_no']) for r in expected['copy_minifigs']}
    return sorted([dict(item_type=t, item_no=n, name=_label(expected, t, n)) for t, n in used if t == '?'],
                  key=lambda r: r['item_no'])


def _summary(expected, rows, db):
    storages, places = _names(db, 'storages'), _names(db, 'purchase_locations')
    flags = {(_norm(r['name']), r['kind']) for r in db.execute('SELECT name,kind FROM flags')}
    out = {kind: {state: sum(1 for r in rows if r['kind'] == kind and r['state'] == state) for state in ('new', 'duplicate', 'imported')}
           for kind in KINDS}
    out['storages'] = dict(new=sum(_norm(r['name']) not in storages for r in expected['storages']),
                           reused=sum(_norm(r['name']) in storages for r in expected['storages']))
    out['purchase_locations'] = dict(new=sum(_norm(r['name']) not in places for r in expected['purchase_locations']),
                                     reused=sum(_norm(r['name']) in places for r in expected['purchase_locations']))
    out['flags'] = dict(new=sum((_norm(r['name']), r['kind']) not in flags for r in expected['flags']),
                        reused=sum((_norm(r['name']), r['kind']) in flags for r in expected['flags']))
    out['copy_parts'] = len(expected['copy_parts'])
    out['copy_minifigs'] = len(expected['copy_minifigs'])
    return out


def plan(db, source, *, name=None):
    """Upgrade a copy of `source`, project it and compare it with the store. Writes nothing to the store."""
    catalogue = _catalogue(db)
    root = plans_root(db)
    _cleanup(root)
    plan_id = uuid4().hex
    work = root / plan_id
    work.mkdir(parents=True)
    try:
        version_from, version_to = bricktracker_upgrade.upgraded_copy(source, work / 'app.db')
        expected = _project(work, catalogue, db)
        rows = _rows(db, expected)
        result = dict(id=plan_id, created_at=now().isoformat(), source=name or Path(source).name,
                      schema=dict(found=version_from, upgraded_to=version_to), fresh=not db.execute(
                          'SELECT 1 FROM copies UNION ALL SELECT 1 FROM loose_stock UNION ALL SELECT 1 FROM wishlist LIMIT 1').fetchone(),
                      summary=_summary(expected, rows, db), unresolved=_unresolved(expected), rows=rows)
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
    from datetime import datetime
    if datetime.fromisoformat(meta['created_at']) < now() - PLAN_TTL:
        raise ValueError('This import plan has expired · upload the file again')
    return work, meta


def _insert(db, table, row):
    columns = list(row)
    db.execute(f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
               [row[c] for c in columns])


def _insert_ignore(db, table, rows):
    for row in rows:
        columns = list(row)
        db.execute(f'INSERT OR IGNORE INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                   [row[c] for c in columns])


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


def apply(db, plan_id, decisions=None, *, queue=True):
    """Write the chosen rows in one transaction; returns the receipt event id and counts."""
    from .. import stock as stock_ops
    from .. import plans
    work, meta = load_plan(db, plan_id)
    # The database marker decides; the plan file can say applied for a write that rolled back.
    done = plans.applied(db, 'import', plan_id, file_says_applied=bool(meta.get('applied')))
    if done:
        return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
    actions = _decide(meta, decisions)
    expected = _project(work, _catalogue(db), db)
    stamp = now().isoformat()
    receipt = dict(plan=plan_id, source=meta['source'], copies=[], stock=[], stock_changes=[], lots=[], wishes=[],
                   storages=[], purchase_locations=[], flags=[], guards={})
    with transaction(db):
        # Checked again under the write lock: a second submit waits here and finds the first one's marker.
        done = plans.applied(db, 'import', plan_id, file_says_applied=bool(meta.get('applied')))
        if done:
            return dict(event_id=done['event_id'], already_applied=True, counts=done['counts'])
        _insert_ignore(db, 'colors', expected['colors'])
        _insert_ignore(db, 'items', expected['items'])
        for table in REFERENCE[2:]:
            _insert_ignore(db, table, expected[table])
        # Storages, purchase places and flags: reuse by name, add the rest under a free id.
        maps = {}
        for table, rows, field in (('storages', expected['storages'], 'storages'),
                                   ('purchase_locations', expected['purchase_locations'], 'purchase_locations')):
            known, taken = _names(db, table), {r[0] for r in db.execute(f'SELECT id FROM {table}')}
            maps[table] = {}
            for row in rows:
                target = known.get(_norm(row['name']))
                if target is None:
                    target = row['id'] if row['id'] not in taken else uuid4().hex
                    _insert(db, table, dict(row, id=target))
                    known[_norm(row['name'])] = target
                    taken.add(target)
                    receipt[field].append(target)
                maps[table][row['id']] = target
        known_flags = {(_norm(r['name']), r['kind']): r['id'] for r in db.execute('SELECT id,name,kind FROM flags')}
        taken = {r[0] for r in db.execute('SELECT id FROM flags')}
        flag_map = {}
        for row in expected['flags']:
            target = known_flags.get((_norm(row['name']), row['kind']))
            if target is None:
                target = row['id'] if row['id'] not in taken else uuid4().hex
                _insert(db, 'flags', dict(row, id=target))
                known_flags[_norm(row['name']), row['kind']] = target
                taken.add(target)
                receipt['flags'].append(target)
            flag_map[row['id']] = target

        def placed(row):
            row = dict(row)
            if row.get('storage_id') is not None:
                row['storage_id'] = maps['storages'].get(row['storage_id'], row['storage_id'])
            if row.get('purchase_location_id') is not None:
                row['purchase_location_id'] = maps['purchase_locations'].get(row['purchase_location_id'], row['purchase_location_id'])
            return row

        flags_by_entity = {}
        for f in expected['item_flags']:
            flags_by_entity.setdefault((f['entity_type'], f['entity_id']), []).append(f['flag_id'])

        def flags_for(entity_type, source_id, target_id):
            for flag in flags_by_entity.get((entity_type, source_id), ()):
                db.execute('INSERT OR IGNORE INTO item_flags(entity_type,entity_id,flag_id) VALUES(?,?,?)',
                           (entity_type, target_id, flag_map[flag]))

        lot_map = {}
        live_lots = _names(db, 'lots')
        for lot in expected['lots']:
            if actions.get('lot:' + lot['id']) == 'add':
                _insert(db, 'lots', placed(lot))
                receipt['lots'].append(lot['id'])
                lot_map[lot['id']] = lot['id']
            elif _norm(lot['name']) in live_lots:
                lot_map[lot['id']] = live_lots[_norm(lot['name'])]
        by_copy, figures_by_copy, figure_parts = {}, {}, {}
        for part in expected['copy_parts']:
            by_copy.setdefault(part['copy_id'], []).append(part)
        for figure in expected['copy_minifigs']:
            figures_by_copy.setdefault(figure['copy_id'], []).append(figure)
        for part in expected['loose_minifig_parts']:
            figure_parts.setdefault(part['stock_id'], []).append(part)
        states = {r['key']: r['state'] for r in meta['rows']}
        added_items = set()
        for copy in expected['copies']:
            if actions.get('copy:' + copy['id']) != 'add':
                continue
            _insert(db, 'copies', placed(copy))
            for part in by_copy.get(copy['id'], ()):
                _insert(db, 'copy_parts', {k: v for k, v in part.items() if k != 'id'})
            for figure in figures_by_copy.get(copy['id'], ()):
                _insert(db, 'copy_minifigs', figure)
            flags_for('copy', copy['id'], copy['id'])
            receipt['copies'].append(copy['id'])
            added_items.add((copy['item_type'], copy['set_no']))
        for row in expected['loose_stock']:
            key = 'stock:' + row['id']
            if actions.get(key) != 'add':
                continue
            row = placed(row)
            if row.get('lot_id') is not None:
                row['lot_id'] = lot_map.get(row['lot_id'])
            if states[key] == 'duplicate' and row['item_type'] != 'M':
                # A duplicate chosen as "add" merges into the matching pile, as Add does.
                identifier, _ = stock_ops.add_loose(db, receipt['stock_changes'], item_type=row['item_type'],
                    item_no=row['item_no'], color_id=row['color_id'], quantity=row['quantity'], condition=row['condition'],
                    lot_id=row['lot_id'], storage_id=row['storage_id'], note=row.get('note'))
            else:
                _insert(db, 'loose_stock', row)
                identifier = row['id']
                receipt['stock'].append(identifier)
                for part in figure_parts.get(row['id'], ()):
                    _insert(db, 'loose_minifig_parts', part)
            flags_for('stock', row['id'], identifier)
            added_items.add((row['item_type'], row['item_no']))
        for wish in expected['wishlist']:
            if actions.get(f"wish:{wish['id']}") != 'add':
                continue
            values = {k: v for k, v in wish.items() if k != 'id'}
            identifier = db.execute(f'INSERT INTO wishlist({",".join(values)}) VALUES({",".join("?" for _ in values)})',
                                    list(values.values())).lastrowid
            flags_for('wishlist', str(wish['id']), str(identifier))
            receipt['wishes'].append(identifier)
            added_items.add((wish['item_type'], wish['item_no']))
        for table, ids in (('copies', receipt['copies']), ('loose_stock', receipt['stock']),
                           ('wishlist', receipt['wishes']), ('lots', receipt['lots'])):
            if ids:
                receipt['guards'][table] = [dict(r) for r in db.execute(
                    f'SELECT * FROM {table} WHERE id IN ({",".join("?" for _ in ids)}) ORDER BY id', ids)]
        receipt['jobs'] = _queue(db, added_items) if queue else []
        counts = dict(copies=len(receipt['copies']), stock=len(receipt['stock']) + len(receipt['stock_changes']),
                      lots=len(receipt['lots']), wishes=len(receipt['wishes']), storages=len(receipt['storages']),
                      purchase_locations=len(receipt['purchase_locations']), flags=len(receipt['flags']))
        receipt['counts'] = counts
        from ..audit_bundle import CAPTURE
        bundled = CAPTURE.get() is not None
        audit(db, 'bw_import', 'receipt', None, receipt, **({} if bundled else {'via': 'import'}))
        # Inside an API write the receipt is bundled into the API event, whose id the API returns.
        event = None if bundled else db.execute('SELECT last_insert_rowid()').fetchone()[0]
        plans.mark(db, 'import', plan_id, dict(event_id=event, counts=counts, at=stamp))
    meta.update(applied=True, applied_event=event, applied_counts=counts, applied_at=stamp)
    (work / 'plan.json').write_text(json.dumps(meta))
    (work / 'app.db').unlink(missing_ok=True)
    return dict(event_id=event, already_applied=False, counts=counts)


def _queue(db, items):
    from ..pipeline import queue_new_items
    return queue_new_items(db, items)


def receipt_of(db, event_id):
    row = db.execute("SELECT new_value FROM events WHERE id=? AND entity='bw_import' AND field='receipt'", (event_id,)).fetchone()
    if not row:
        raise ValueError('Import not found')
    return json.loads(row[0])


def undo(db, event_id, receipt=None):
    """Reverse one import exactly: archive what it added, restore merged piles; refuse over later edits.

    `receipt` is passed when the import was bundled in an API event; otherwise it is read by id.
    """
    from .. import stock as stock_ops
    with transaction(db):
        if db.execute("SELECT 1 FROM events WHERE entity='bw_import' AND field='undo' AND old_value=?",
                      (json.dumps(event_id),)).fetchone():
            return dict(undone_event_id=event_id, already_undone=True)
        receipt = receipt if receipt is not None else receipt_of(db, event_id)
        for table, saved in receipt['guards'].items():
            ids = [r['id'] for r in saved]
            current = [dict(r) for r in db.execute(
                f'SELECT * FROM {table} WHERE id IN ({",".join("?" for _ in ids)}) ORDER BY id', ids)]
            if current != saved:
                raise ValueError('Something from this import has changed since · undo the later change first')
        if receipt['stock_changes']:
            stock_ops.undo_loose(db, receipt['stock_changes'])
        stamp = now().isoformat()
        for table, ids, has_updated in (('copies', receipt['copies'], True), ('loose_stock', receipt['stock'], True),
                                        ('wishlist', receipt['wishes'], True), ('lots', receipt['lots'], False),
                                        ('storages', receipt['storages'], False)):
            for identifier in ids:
                db.execute(f'UPDATE {table} SET archived_at=?' + (',updated_at=?' if has_updated else '') + ' WHERE id=?',
                           (stamp, stamp, identifier) if has_updated else (stamp, identifier))
        # Places and flags have no archive column: remove the ones this import created if nothing else uses them.
        for identifier in receipt['purchase_locations']:
            used = any(db.execute(f'SELECT 1 FROM {t} WHERE purchase_location_id=? AND archived_at IS NULL LIMIT 1', (identifier,)).fetchone()
                       for t in ('copies', 'loose_stock', 'lots'))
            if not used:
                db.execute('UPDATE copies SET purchase_location_id=NULL WHERE purchase_location_id=? AND archived_at IS NOT NULL', (identifier,))
                db.execute('UPDATE loose_stock SET purchase_location_id=NULL WHERE purchase_location_id=? AND archived_at IS NOT NULL', (identifier,))
                db.execute('UPDATE lots SET purchase_location_id=NULL WHERE purchase_location_id=? AND archived_at IS NOT NULL', (identifier,))
                db.execute('DELETE FROM purchase_locations WHERE id=?', (identifier,))
        for identifier in receipt['flags']:
            live = db.execute("""SELECT 1 FROM item_flags f WHERE f.flag_id=? AND NOT (
                (f.entity_type='copy' AND f.entity_id IN (SELECT id FROM copies WHERE archived_at IS NOT NULL)) OR
                (f.entity_type='stock' AND f.entity_id IN (SELECT id FROM loose_stock WHERE archived_at IS NOT NULL)) OR
                (f.entity_type='wishlist' AND f.entity_id IN (SELECT CAST(id AS TEXT) FROM wishlist WHERE archived_at IS NOT NULL)))
                LIMIT 1""", (identifier,)).fetchone()
            if not live:
                db.execute('DELETE FROM item_flags WHERE flag_id=?', (identifier,))
                db.execute('DELETE FROM flags WHERE id=?', (identifier,))
        audit(db, 'bw_import', 'undo', event_id, None)
    return dict(undone_event_id=event_id, already_undone=False)
