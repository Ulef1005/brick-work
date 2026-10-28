"""New-store admin queries and atomic, app-audited mutations. No legacy adapters."""
from .transaction import transaction
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from .connect import connect
from ..store4.audit import value_text
from ..store4.connect import now as store4_now
from .pipeline import Pipeline, TYPES, validate_priority
from .sources.base import now, redact

VALUES = {'owners': ('flag', 'owner'), 'statuses': ('flag', 'status'),
          'tags': ('flag', 'tag'), 'storages': ('storage', None),
          'purchase-places': ('place', None)}


@contextmanager
def database(path, *, read_only=False, require_catalogue=True):
    # An absent production store is a setup error, never a silently empty collection.
    if not Path(path).is_file():
        raise ValueError('Brick Work database is not available')
    db = connect(path, read_only=read_only, require_catalogue=require_catalogue)
    try:
        yield db
    finally:
        db.close()


def origin():
    """(via, actor) for an event written now: the request's audit origin, else the app."""
    from .sources.base import AUDIT_ORIGIN, AUDIT_ACTOR, AUDIT_EXPLICIT
    via = AUDIT_ORIGIN.get() if AUDIT_EXPLICIT.get() else 'app'
    return via, AUDIT_ACTOR.get() if via == 'api' else None


OPERATION_KEY = ContextVar('brickwork_operation_key', default=None)


def begin_operation(key=None):
    """Start a new operation in this context (a web request, a CLI command, a worker pass) and return its key.

    Every event written after this call shares the key (`event.operation_key`, design 5.2). Call it once at the entry point;
    `end_operation()` clears it. Code with no operation (a test, a script) writes events with a NULL key."""
    key = key or uuid.uuid4().hex
    OPERATION_KEY.set(key)
    return key


def end_operation():
    OPERATION_KEY.set(None)


@contextmanager
def operation(key=None):
    """`begin_operation` for the length of a block; the previous key is restored on exit."""
    token = OPERATION_KEY.set(key or uuid.uuid4().hex)
    try:
        yield OPERATION_KEY.get()
    finally:
        OPERATION_KEY.reset(token)


def split_entity(entity):
    """The 3.3-style entity string as the 4.0 pair: split at the first colon (`copy:<id>` -> ('copy', '<id>')); no colon, or
    nothing after it, gives an entity_id of None."""
    kind, _, ident = str(entity).partition(':')
    return kind, ident or None


def audit(db, entity, field, old=None, new=None, *, via=None, actor=None):
    """Write one event on the 4.0 `event` table. The signature is the 3.3 one; `entity` is split into `entity_kind` and
    `entity_id` (`split_entity`), `operation_key` is the current operation's. `old`/`new` are stored by `store4.audit.value_text`, the one rule every event writer
    uses (None as NULL, strings as they are, dicts and lists as sorted JSON)."""
    from .sources.base import AUDIT_ORIGIN, AUDIT_ACTOR, AUDIT_EXPLICIT
    if via is None:
        via = AUDIT_ORIGIN.get() if AUDIT_EXPLICIT.get() else 'app'
        actor = AUDIT_ACTOR.get() if actor is None else actor
    if via not in ('app', 'cli', 'api', 'import', 'migration'):
        raise ValueError('invalid audit origin')
    actor = actor if via == 'api' else None
    kind, ident = split_entity(entity)
    db.execute('INSERT INTO event(at,via,actor,entity_kind,entity_id,field,old_value,new_value,operation_key) VALUES(?,?,?,?,?,?,?,?,?)',
               (store4_now(), via, actor, kind, ident, field,
                None if old is None else redact(value_text(old)), None if new is None else redact(value_text(new)),
                OPERATION_KEY.get()))


# ---------- identity admin (M.8i part 2): the list and the decisions are in `core/identity_admin.py` ----------

def unresolved(db):
    from . import identity_admin
    return identity_admin.unresolved(db)


def count_unresolved(db):
    from . import identity_admin
    return identity_admin.count_unresolved(db)


# ---------- values (Tools & Admin → Values; M.8i) ----------
#
# Owners, statuses and tags are `flag` rows of that kind; storage locations are `storage`; purchase places are `place`. A flag or place
# change is one `collection` receipt (generic Undo); a location goes through the ledger (its guards and history).

REFERENCES = {
    'flag': (('copy_flag', 'flag_id'), ('stock_flag', 'flag_id'), ('wish_flag', 'flag_id')),
    'place': (('copy', 'place_id'), ('stock', 'place_id'), ('lot', 'place_id')),
    'storage': (('copy', 'storage_id'), ('stock', 'storage_id'), ('lot', 'storage_id'), ('identification_action', 'storage_id')),
}
SYSTEM_VALUE = 'Brick Work uses this value itself · it cannot be renamed or archived'


def value_rows(db, group):
    if group not in VALUES:
        raise ValueError('Unknown value group')
    table, kind = VALUES[group]
    where = ' WHERE archived_at IS NULL' + (' AND kind=?' if kind else '')
    rows = db.execute(f'SELECT * FROM main.{table}' + where + ' ORDER BY name COLLATE NOCASE,id', (kind,) if kind else ())
    # Aggregate once per reference table, never once per value row.
    counts = [(t, column, dict(db.execute(f'SELECT {column},count(*) FROM main.{t} WHERE {column} IS NOT NULL GROUP BY {column}')))
              for t, column in REFERENCES[table]]
    return [dict(row, count=sum(found.get(row['id'], 0) for _, _, found in counts),
                 references=[(t, c, found.get(row['id'], 0)) for t, c, found in counts])
            for row in rows]


def value_write(db, group, action, identifier=None, name=None, confirmed=False):
    """Add, rename or archive a value; returns the event id of the change (Undo takes it back)."""
    if group not in VALUES or action not in ('add', 'rename', 'delete'):
        raise ValueError('Unknown value action')
    table, kind = VALUES[group]
    if action != 'delete' and (not name or not name.strip() or len(name.strip()) > 120):
        raise ValueError('Enter a name of up to 120 characters')
    if table == 'storage':
        from . import ledger
        if action == 'delete':
            if not confirmed:
                raise ValueError('Confirm deletion and its reference count')
            return ledger.storage_archive(db, identifier)
        return ledger.storage_save(db, identifier if action == 'rename' else None, name)[1]
    with transaction(db):
        from .collection import receipt, snapshot
        before = snapshot(db, table, [identifier]) if action != 'add' else []
        if action != 'add' and (not before or before[0]['archived_at'] or (kind and before[0]['kind'] != kind)):
            raise ValueError('Value is no longer available')
        if before and table == 'flag' and before[0]['system']:
            raise ValueError(SYSTEM_VALUE)
        if action == 'add':
            identifier = uuid.uuid4().hex
            if table == 'flag':
                db.execute('INSERT INTO main.flag(id,name,kind,shown_on_grid,created_at) VALUES(?,?,?,1,?)', (identifier, name.strip(), kind, store4_now()))
            else:
                db.execute('INSERT INTO main.place(id,name,created_at) VALUES(?,?,?)', (identifier, name.strip(), store4_now()))
        elif action == 'rename':
            db.execute(f'UPDATE main.{table} SET name=? WHERE id=?', (name.strip(), identifier))
        else:
            if not confirmed:
                raise ValueError('Confirm deletion and its reference count')
            db.execute(f'UPDATE main.{table} SET archived_at=? WHERE id=?', (store4_now(), identifier))
        return receipt(db, [(table, before, snapshot(db, table, [identifier]))], 'archive' if action == 'delete' else 'save')


# ---------- settings (Tools & Admin → Settings; M.8i) ----------
#
# The preferences live in `setting` (design 5.2), the freshness rules in `source_freshness`. The Settings page edits the retail country, the
# source order of the three source steps and the freshness rules; the price preferences are `price_settings`' (CLI, API), the display currency
# and the exchange rates `currency`'s. A save writes one `settings:save` event with the stored values before and after (only what changed),
# which Undo puts back; a setting that was never stored comes back absent.

FRESHNESS = {'prices': 30, 'metadata': 365, 'pictures': None}           # 3.3's defaults (release/0.5 schema), for every source below
FRESHNESS_SOURCES = ('bricklink', 'rebrickable', 'brickset', 'brickognize', 'manual')
SOURCE_STEPS = ('pictures', 'metadata', 'market_price')                  # the steps whose sources are an order (the others use the catalogue)
COUNTRIES = ('DE', 'US', 'UK', 'CA')


def seed_freshness(db):
    """The freshness rules a new collection starts with (3.3's: prices 30 days, metadata 365, pictures never). Only into an empty table."""
    with transaction(db):
        if db.execute('SELECT 1 FROM main.source_freshness LIMIT 1').fetchone():
            return 0
        known = {r[0] for r in db.execute('SELECT id FROM main.source')}
        rows = [(s, kind, days) for s in FRESHNESS_SOURCES if s in known for kind, days in FRESHNESS.items()]
        db.executemany('INSERT INTO main.source_freshness(source,kind,max_age_days) VALUES(?,?,?)', rows)
        return len(rows)


SYSTEM_FLAGS = ('Set is checked', 'Box present', 'Instructions present')     # the statuses the app itself reads (checker, workbench)


def seed_new(db):
    """What a fresh collection starts with (user journey § 1): the freshness rules, the three system status flags and the `database/setup`
    event, in one transaction. Only on a fresh file (no freshness rules yet); returns whether it seeded. A flag of that name already live
    (from an import) is kept as it is."""
    with transaction(db):
        if not seed_freshness(db):
            return False
        for name in SYSTEM_FLAGS:
            if db.execute("SELECT 1 FROM main.flag WHERE archived_at IS NULL AND kind='status' AND name=?", (name,)).fetchone():
                continue
            flag = dict(id=uuid.uuid4().hex, name=name, kind='status', shown_on_grid=1, system=1, created_at=store4_now())
            db.execute('INSERT INTO main.flag(id,name,kind,shown_on_grid,system,created_at) VALUES(:id,:name,:kind,:shown_on_grid,:system,:created_at)', flag)
            audit(db, 'flag:' + flag['id'], 'record', None, flag, via='cli')
        audit(db, 'database', 'setup', new='4.0', via='cli')
        return True


def effective_priority(raw):
    """The source order per step as the pipeline uses it: the stored `source_priority` where it names the step, else design 6.8's default."""
    from .pipeline import DEFAULT_PRIORITY, LEGACY_PICTURE_SOURCES
    try:
        stored = json.loads(raw) if raw else {}
    except ValueError:
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    result = {step: stored.get(step) or DEFAULT_PRIORITY[step] for step in SOURCE_STEPS}
    # 3.3 knew one `rebrickable` picture source; 4.0 has the catalogue's picture and the API. A value the migration did not translate is
    # shown (and saved) as the order the jobs use (`pictures.order` reads it the same way).
    result['pictures'] = {kind: list(dict.fromkeys(n for s in sources for n in LEGACY_PICTURE_SOURCES.get(s.split(':')[0], (s.split(':')[0],))))
                          for kind, sources in result['pictures'].items()}
    return result


def settings(db):
    values = dict(db.execute('SELECT key,value FROM main.setting'))
    from .price_settings import read
    return dict(**read(db), retail_country=values.get('retail_country') or 'DE',
                priority=effective_priority(values.get('source_priority')),
                import_order={k.removeprefix('import_order:'): json.loads(v) for k, v in sorted(values.items())
                              if k.startswith('import_order:') and v},
                display_currency=values.get('display_currency') or values.get('bricklink_currency') or 'EUR',
                freshness=[dict(r) for r in db.execute('SELECT * FROM main.source_freshness ORDER BY source,kind')])


def patch_settings(db, data):
    """PATCH /settings (#47): any subset of the whitelisted settings, in one transaction.

    freshness: [{source, kind, max_age_days}] (as GET /settings returns it); import_order:
    {item kind: [the six steps]}; repair: {shipping, fees, min_order, use_loose_stock}; prefer_bricklink_inventory: true or false (new
    copies take BrickLink's part list, design 4.4).
    """
    from . import errors, price_settings
    from .pipeline import STEPS, TYPES
    allowed = {'retail_country', 'bricklink_region', 'bricklink_currency', 'incomplete_discount_pct',
               'source_priority', 'import_order', 'freshness', 'repair', 'display_currency', 'prefer_bricklink_inventory'}
    if not isinstance(data, dict) or not data:
        raise errors.ValidationFailed('Send at least one setting')
    if set(data) - allowed:
        raise errors.UnsupportedSetting('Unsupported setting: ' + ', '.join(sorted(set(data) - allowed)))
    price = {k: data[k] for k in ('bricklink_region', 'bricklink_currency', 'incomplete_discount_pct') if k in data}
    if 'repair' in data:
        repair = data['repair']
        if not isinstance(repair, dict) or set(repair) - {'shipping', 'fees', 'min_order', 'use_loose_stock'}:
            raise errors.ValidationFailed('repair takes shipping, fees, min_order and use_loose_stock')
        price.update({'repair_' + k: v for k, v in repair.items()})
    with transaction(db):
        if price:
            price_settings.save(db, price)
        if {'retail_country', 'source_priority', 'freshness'} & set(data):
            current = settings(db)
            rules = [(r['source'], r['kind'], '' if r['max_age_days'] is None else r['max_age_days']) for r in current['freshness']]
            if 'freshness' in data:
                if not isinstance(data['freshness'], list) or any(not isinstance(r, dict) or set(r) - {'source', 'kind', 'max_age_days'}
                                                                  for r in data['freshness']):
                    raise errors.ValidationFailed('freshness is a list of {source, kind, max_age_days}')
                rules = []
                for r in data['freshness']:
                    days = r.get('max_age_days')
                    if days is not None and (type(days) is not int or days < 0):
                        raise errors.ValidationFailed('Freshness days must be a whole number of zero or more')
                    rules.append((r.get('source'), r.get('kind'), '' if days is None else days))
            try:
                save_settings(db, data.get('retail_country', current['retail_country']),
                              data.get('source_priority', current['priority']), rules)
            except ValueError as exc:
                raise errors.ValidationFailed(str(exc)) from None
        if 'display_currency' in data:
            from .currency import set_display
            set_display(db, data['display_currency'])
        if 'prefer_bricklink_inventory' in data:
            if type(data['prefer_bricklink_inventory']) is not bool:
                raise errors.ValidationFailed('prefer_bricklink_inventory is true or false')
            from ..store4 import copies
            via, actor = origin()
            copies.set_prefer_bricklink_in(db, data['prefer_bricklink_inventory'], via=via, actor=actor)
        if 'import_order' in data:
            orders = data['import_order']
            if not isinstance(orders, dict) or not orders:
                raise errors.ValidationFailed('import_order is {item kind: [steps]}')
            for kind, order in orders.items():
                if kind not in TYPES or not isinstance(order, list) or len(order) != len(STEPS) or set(order) != set(STEPS):
                    raise errors.ValidationFailed('Each import order lists all six steps once')
            before = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM main.setting WHERE key LIKE 'import_order:%'")}
            db.executemany('INSERT OR REPLACE INTO main.setting(key,value) VALUES(?,?)',
                           [('import_order:' + k, json.dumps(v)) for k, v in sorted(orders.items())])
            audit(db, 'settings', 'import_order', before, {'import_order:' + k: v for k, v in orders.items()})
        return settings(db)


def _stored_pair(db, keys):
    return {k: (db.execute('SELECT value FROM main.setting WHERE key=?', (k,)).fetchone() or [None])[0] for k in keys}


def _stored_freshness(db, which=None):
    rows = db.execute('SELECT source,kind,max_age_days FROM main.source_freshness').fetchall()
    return {f'{r[0]}/{r[1]}': r[2] for r in rows if which is None or f'{r[0]}/{r[1]}' in which}


def save_settings(db, country, priority, freshness):
    """Save the retail country, the source order and the freshness rules from the Settings page; returns the event id (None when nothing
    differs from what is stored). Refused whole on a value that does not fit."""
    if country not in COUNTRIES:
        raise ValueError('Choose a supported retail country')
    validate_priority(priority)
    known = {r[0] for r in db.execute('SELECT id FROM main.source')}
    for sources in (s for kinds in priority.values() for s in kinds.values()):
        for name in sources:
            if name.split(':')[0] not in known:
                raise ValueError('Unknown source ' + name)
    rules = {}
    for source, kind, days in freshness:
        days = None if days == '' or days is None else int(days)
        if days is not None and days < 0:
            raise ValueError('Freshness days must be zero or more')
        rules[f'{source}/{kind}'] = days
    with transaction(db):
        stored = _stored_pair(db, ('retail_country', 'source_priority'))
        wanted = {'retail_country': country, 'source_priority': json.dumps(priority, sort_keys=True)}
        # A value equal to what the screen would show for a setting never stored is not a change.
        shown = {'retail_country': stored['retail_country'] or 'DE',
                 'source_priority': json.dumps(effective_priority(stored['source_priority']), sort_keys=True)}
        changed = {k: v for k, v in wanted.items() if v != shown[k]}
        current = _stored_freshness(db)
        unknown = set(rules) - set(current)
        if unknown:
            raise ValueError('Unknown freshness rule')
        moved = {k: v for k, v in rules.items() if current[k] != v}
        if not changed and not moved:
            return None
        old = {'setting': {k: stored[k] for k in changed}, 'freshness': {k: current[k] for k in moved}}
        new = {'setting': changed, 'freshness': moved}
        for key, value in changed.items():
            db.execute('INSERT OR REPLACE INTO main.setting(key,value) VALUES(?,?)', (key, value))
        for key, days in moved.items():
            source, kind = key.split('/')
            db.execute('UPDATE main.source_freshness SET max_age_days=? WHERE source=? AND kind=?', (days, source, kind))
        audit(db, 'settings', 'save', old, new)
        return db.execute('SELECT last_insert_rowid()').fetchone()[0]


def _undo_settings(db, event, via, actor):
    old, new = json.loads(event['old_value']), json.loads(event['new_value'])
    if _stored_pair(db, new['setting']) != new['setting'] or _stored_freshness(db, new['freshness']) != new['freshness']:
        raise ValueError('Item changed · undo the later save first')
    for key, value in old['setting'].items():
        if value is None:
            db.execute('DELETE FROM main.setting WHERE key=?', (key,))
        else:
            db.execute('INSERT OR REPLACE INTO main.setting(key,value) VALUES(?,?)', (key, value))
    for key, days in old['freshness'].items():
        source, kind = key.split('/')
        db.execute('UPDATE main.source_freshness SET max_age_days=? WHERE source=? AND kind=?', (days, source, kind))
    audit(db, 'settings', 'undo', None, dict(undoes=event['id']), via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO main.event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


def stale_prices(db):
    """The held or wanted (item, colour, condition) whose market price is not fresh from some enabled source of its kind's order.

    One row per line the collection holds (a set copy, loose stock, a wish) with `item_id`, `color_id`, `condition` (words; None for
    "any"), `name` and, for display, the BrickLink `item_type` letter and `item_no`. Fresh means a successful, unvoided sold or stock
    observation younger than the source's `prices` freshness rule (7 days when there is none)."""
    from . import collection_prices, items
    rows = db.execute('''SELECT i.id AS item_id, i.name, i.kind, w.color_id, w.condition FROM main.item i JOIN
        (SELECT item_id, NULL color_id, condition FROM main.copy WHERE archived_at IS NULL
         UNION SELECT item_id, color_id, condition FROM main.stock WHERE archived_at IS NULL AND kind!='minifigure'
         UNION SELECT item_id, color_id, CASE condition WHEN 'any' THEN NULL ELSE condition END FROM main.wish WHERE archived_at IS NULL) w
        ON w.item_id=i.id WHERE i.merged_into IS NULL AND ''' + items.identified_sql('i') + ''' ORDER BY i.id, w.color_id, w.condition''').fetchall()
    priority = collection_prices.priority(db)
    rules = {(r['source'], r['kind']): r['max_age_days'] for r in db.execute('SELECT source, kind, max_age_days FROM main.source_freshness')}
    enabled = dict(db.execute('SELECT id, enabled FROM main.source'))
    observed = {}
    for r in db.execute("""SELECT item_id, color_id, condition, source, max(observed_at) AS observed FROM main.price_observation
                           WHERE guide IN ('sold','stock') AND error IS NULL AND voided_at IS NULL GROUP BY 1, 2, 3, 4"""):
        observed[r['item_id'], r['color_id'], r['condition'], r['source']] = r['observed']
        key = (r['item_id'], r['color_id'], None, r['source'])                   # a quote with no condition answers "any"
        observed[key] = max(observed.get(key) or '', r['observed'] or '')
    labels = items.labels(db, {(r['item_id'], r['color_id']) for r in rows})
    moment, result = now(), []
    for row in rows:
        stale = False
        for source in (s.split(':')[0] for s in priority.get(row['kind'], priority.get('*', ['bricklink']))):
            if source in enabled and not enabled[source]:
                continue
            days = rules.get((source, 'prices'), rules.get((source, 'price'), 7))
            if days is None:
                continue
            stamp_found = observed.get((row['item_id'], row['color_id'], row['condition'], source))
            try:
                seen = datetime.fromisoformat(stamp_found.replace('Z', '+00:00')) if stamp_found else None
                if seen is not None and seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                fresh = seen is not None and (moment - seen).total_seconds() < days * 86400
            except ValueError:
                fresh = False
            stale |= not fresh
        if stale:
            label = labels.get((row['item_id'], row['color_id']))
            result.append(dict(item_id=row['item_id'], color_id=row['color_id'], condition=row['condition'], name=row['name'],
                               item_type=items.type_of_kind(row['kind']), item_no=(label.number if label else None) or ''))
    return result


def live_import_job(db, item_id):
    """The id of an item's pipeline job that has not finished (queued, running or waiting for a budget), else None."""
    row = db.execute("SELECT id FROM main.job WHERE kind='item' AND item_id=? AND state IN ('queued','running','waiting_for_budget') ORDER BY id LIMIT 1",
                     (item_id,)).fetchone()
    return row[0] if row else None


def queue_refresh(db, rows, steps=('market_price',)):
    """Queue `steps` for each item of `rows` (dicts with `item_id`) that has no unfinished pipeline job; returns the job ids."""
    pipeline = Pipeline(db)
    with transaction(db):
        jobs = []
        for item_id in sorted({r['item_id'] for r in rows}):
            if live_import_job(db, item_id) is not None:
                continue
            jobs.append(pipeline.queue_steps(item_id, steps, via='app'))
        return jobs


def queue_missing_booklets(db):
    """Queue the identity step for booklets without a PDF. A PDF belongs to a set, and a booklet shares the files of the set with its number
    (`collection.instruction_files`). The identity step is local in 4.0 and the pipeline has no instruction-PDF step, so this checks the item's
    number only; it never downloads a PDF. Returns (queued job ids, skipped items: the ones with no number)."""
    rows = db.execute("""SELECT i.id, i.born_key FROM main.item i WHERE i.kind='instructions' AND i.merged_into IS NULL AND NOT EXISTS(
        SELECT 1 FROM main.instruction_file f JOIN main.item s ON s.id=f.item_id
        WHERE f.archived_at IS NULL AND (s.id=i.id OR (s.born_key=i.born_key AND i.born_key IS NOT NULL))) ORDER BY i.id""").fetchall()
    ok = [{'item_id': r['id']} for r in rows if r['born_key'] is not None]
    skipped = [str(r['id']) for r in rows if r['born_key'] is None]
    return queue_refresh(db, ok, steps=('identity',)), skipped


def count_jobs(db):
    return db.execute("SELECT count(*) FROM main.job").fetchone()[0]


FETCH_HEADINGS = {'rebrickable_set': 'Rebrickable set', 'bricklink_subsets': 'BrickLink part list', 'reconcile': 'Reconcile with the catalogue'}


def jobs(db, limit=300):
    """The newest jobs, newest first, each with its steps and a heading (the Jobs list): pipeline jobs and the two fetch kinds.
    `count_jobs` says how many there are in all."""
    from collections import defaultdict
    from . import items
    rows = [dict(r) for r in db.execute('SELECT * FROM main.job ORDER BY id DESC LIMIT ?', (limit,))]
    steps = defaultdict(list)
    for row in db.execute('SELECT * FROM main.job_step WHERE job_id IN (SELECT value FROM json_each(?)) ORDER BY job_id, position',
                          (json.dumps([r['id'] for r in rows]),)):
        steps[row['job_id']].append(dict(row))
    labels = items.labels(db, {(r['item_id'], None) for r in rows if r['item_id'] is not None})
    for r in rows:
        try:
            number = (json.loads(r['payload'] or '{}') or {}).get('number')
        except (TypeError, ValueError, AttributeError):
            number = None
        label = labels.get((r['item_id'], None))
        shown = label.text if label else (f"item {r['item_id']}" if r['item_id'] is not None else None)
        r['steps'] = steps[r['id']]
        r['item_label'] = shown
        r['heading'] = shown if r['kind'] == 'item' else ' '.join(x for x in (FETCH_HEADINGS.get(r['kind'], r['kind']), number or shown) if x)
    return rows


def statistics(db):
    """The collection counted by completeness, theme, storage and purchase place (live copies), and spent against retail."""
    def grouped(expression, joins=''):
        return [dict(r) for r in db.execute(f'''SELECT coalesce({expression},'Not recorded') label,count(*) count
            FROM main.copy c JOIN main.item i ON i.id=c.item_id {joins} WHERE c.archived_at IS NULL GROUP BY label ORDER BY count DESC,label''')]
    return {'completeness': grouped("CASE c.completeness WHEN 'sealed' THEN 'Sealed' WHEN 'complete' THEN 'Complete' WHEN 'incomplete' THEN 'Incomplete' ELSE 'Not checked' END"),
            'theme': grouped("""coalesce((SELECT value FROM main.item_property p WHERE p.item_id=c.item_id AND p.key='theme' AND p.source='brickset'
                                           ORDER BY p.fetched_at DESC LIMIT 1), i.theme_name)"""),
            'storage': grouped('s.name', 'LEFT JOIN main.storage s ON s.id=c.storage_id AND s.archived_at IS NULL'),
            'purchase place': grouped('p.name', 'LEFT JOIN main.place p ON p.id=c.place_id'),
            'spent_vs_retail': _spent_vs_retail(db)}


def _spent_vs_retail(db):
    from .retail import spent_vs_retail
    return spent_vs_retail(db)


def check(db):
    """The database check: SQLite's integrity and foreign-key checks of the collection (and of the attached catalogue, which is a file of its
    own), and the rows of every table of the collection."""
    from ..store4.connect import has_catalogue
    result = {'integrity_check': [r[0] for r in db.execute('PRAGMA main.integrity_check')],
              'foreign_key_check': [dict(r) for r in db.execute('PRAGMA main.foreign_key_check')],
              'row_counts': {r[0]: db.execute(f'SELECT count(*) FROM main."{r[0]}"').fetchone()[0]
                             for r in db.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}}
    if has_catalogue(db):
        result['catalogue_integrity_check'] = [r[0] for r in db.execute('PRAGMA catalogue.integrity_check')]
    return result


CHECK_KEY = 'maintenance:database_check'
CHECK_FINDINGS_STORED = 200


def check_ok(result):
    return result['integrity_check'] == ['ok'] and not result.get('foreign_key_total', len(result['foreign_key_check'])) and \
        result.get('catalogue_integrity_check', ['ok']) == ['ok']


def last_check(db):
    """The stored result of the last explicit database check, or None. Never runs a check."""
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (CHECK_KEY,)).fetchone()
    try:
        value = json.loads(row[0]) if row and row[0] else None
    except ValueError:
        return None
    return value if isinstance(value, dict) and 'integrity_check' in value else None


def run_check(db):
    """Run the full check, keep its result with a date (`setting` `maintenance:database_check`), and audit the run (one transaction, not undoable)."""
    result = check(db)
    result['foreign_key_total'] = len(result['foreign_key_check'])
    result['foreign_key_check'] = result['foreign_key_check'][:CHECK_FINDINGS_STORED]
    result['checked_at'] = store4_now()
    with transaction(db):
        db.execute('INSERT OR REPLACE INTO main.setting(key,value) VALUES(?,?)', (CHECK_KEY, json.dumps(result)))
        audit(db, 'database', 'check', new='ok' if check_ok(result) else 'needs attention')
    return result


# ---------- instruction files (M.8i) ----------

def instruction_rename(db, identifier, label, *, undoable=False):
    if not label or len(label) > 120:
        raise ValueError('Enter a label of up to 120 characters')
    with transaction(db):
        from .collection import receipt, snapshot
        old = snapshot(db, 'instruction_file', [identifier])
        if not old:
            raise ValueError('Instruction file no longer exists')
        db.execute('UPDATE main.instruction_file SET label=? WHERE id=?', (label, identifier))
        if undoable:
            return receipt(db, [('instruction_file', old, snapshot(db, 'instruction_file', [identifier]))], 'save')
        audit(db, 'instruction_file:' + str(identifier), 'label', old[0]['label'], label)


def instruction_target(db, kind, number):
    """The set a PDF is attached to, from a BrickLink type letter and a number typed in the form. A PDF belongs to a set (the store allows
    no other item); a booklet (type I) shares the files of the set with its number, so it names that set."""
    from . import errors, items
    try:
        kind = items.kind_of_type(kind)
    except errors.ValidationFailed:
        raise ValueError('Choose an existing item') from None
    if kind not in ('set', 'instructions'):
        raise ValueError('A PDF belongs to a set · choose a set or a booklet')
    found = items.find(db, 'set', number)
    if not found:
        raise ValueError('Choose an existing set' if kind == 'set' else 'A booklet\'s PDF belongs to the set with its number · add that set first')
    if len(found) > 1 and found[0]['matched_by'] != 'born':
        raise ValueError('Several sets match that number · type the Rebrickable number')
    return found[0]['item_id']


def instruction_upload(db, root, kind, number, label, content, *, undoable=False):
    """Install immutable, content-addressed booklets; roll back a new file on failure."""
    if not content.startswith(b'%PDF-') or len(content) > 20 * 1024 * 1024:
        raise ValueError('Choose a PDF up to 20 MB')
    if not label or len(label) > 120:
        raise ValueError('Enter a label of up to 120 characters')
    return attach_instruction(db, root, instruction_target(db, kind, number), label, content, undoable=undoable)


def instruction_set_of(db, item_id):
    """The set a PDF is attached to, from an item id (API v2): a set is its own target, a booklet names the set with its number (as
    `instruction_target`); anything else cannot hold a PDF."""
    row = db.execute('SELECT kind, born_key FROM main.item WHERE id=? AND merged_into IS NULL', (item_id,)).fetchone()
    if row is None:
        raise ValueError('Choose an existing item')
    if row['kind'] == 'set':
        return item_id
    if row['kind'] == 'instructions' and row['born_key']:
        return instruction_target(db, 'I', row['born_key'])
    raise ValueError('A PDF belongs to a set · choose a set or a booklet')


def attach_instruction(db, root, item_id, label, content, *, undoable=False):
    """`instruction_upload` for a set already named by its id (the form names it by a typed number)."""
    from hashlib import sha256
    if not content.startswith(b'%PDF-') or len(content) > 20 * 1024 * 1024:
        raise ValueError('Choose a PDF up to 20 MB')
    if not label or len(label) > 120:
        raise ValueError('Enter a label of up to 120 characters')
    relative = Path('data/instructions') / (sha256(content).hexdigest() + '.pdf')
    target = Path(root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        try:
            with target.open('xb') as output:
                created = True
                output.write(content)
        except FileExistsError:
            pass
        with transaction(db):
            from .transaction import on_rollback
            if created: on_rollback(db, lambda: target.unlink(missing_ok=True))
            from . import items
            items.ensure(db, item_id)
            identifier = db.execute('INSERT INTO main.instruction_file(item_id,path,label,added_at) VALUES(?,?,?,?)',
                (item_id, relative.as_posix(), label, store4_now())).lastrowid
            from .collection import receipt, snapshot
            if undoable:
                receipt(db, [('instruction_file', [], snapshot(db, 'instruction_file', [identifier]))], 'save')
            else:
                audit(db, 'instruction_file:' + str(identifier), 'attach', new={'item_id': item_id, 'path': relative.as_posix(), 'label': label})
        return identifier
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


def instruction_overview(db):
    """The Instruction files page: one row per booklet item with the PDFs of the set that has its number (a PDF belongs to a set), its picture,
    and the PDFs of sets that no booklet item names. Counts canonical booklet identities only: a set-level PDF does not say how many booklets
    the set has."""
    from . import items
    files = [dict(r) for r in db.execute('''SELECT f.*,i.name,i.kind,i.born_key FROM main.instruction_file f JOIN main.item i ON i.id=f.item_id
                                            WHERE f.archived_at IS NULL ORDER BY i.born_key,f.id''')]
    images = {}
    for item_id, identifier in db.execute("""SELECT p.item_id,p.id FROM main.picture p JOIN main.item i ON i.id=p.item_id
                                             WHERE i.kind='instructions' ORDER BY p.fetched_at,p.id"""):
        images[item_id] = identifier
    by_number = {}
    for row in files:
        by_number.setdefault(row['born_key'], []).append(row)
    rows = db.execute("SELECT id,born_key,name FROM main.item WHERE kind='instructions' AND merged_into IS NULL ORDER BY born_key,id").fetchall()
    shown = {r['born_key'] for r in rows if r['born_key'] is not None}
    booklets = [dict(item_id=r['id'], number=r['born_key'] or str(r['id']), name=r['name'], image=images.get(r['id']),
                     files=by_number.get(r['born_key'], []) if r['born_key'] is not None else []) for r in rows]
    others = [dict(r, set_no=r['born_key'] or str(r['item_id']), item_type=items.type_of_kind(r['kind'])) for r in files if r['born_key'] not in shown]
    return dict(files=others, booklets=booklets, coverage=dict(total=len(booklets), covered=sum(1 for b in booklets if b['files'])))


def display(value, secrets=None):
    """Redact strings before serialization, including quoted credential values.

    The secret list is read once per call and shared by every nested string.
    """
    if secrets is None:
        from .secrets import secret_values
        secrets = secret_values()
    if isinstance(value, str):
        return redact(value, secrets).replace('LEGO', '')
    if isinstance(value, dict):
        return {k: display(v, secrets) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [display(v, secrets) for v in value]
    return value


def history(db):
    """Saved identifications (newest first) with the candidates each offered, for Identify history. A candidate names its item when it
    has one (`item_id`: the number shown is the item's, the picture its cached one); older or foreign rows are read as they are."""
    from . import items
    result = []
    types = {'part': 'part', 'minifig': 'minifigure', 'minifigure': 'minifigure', 'set': 'set'}
    rows = [dict(r) for r in db.execute('SELECT * FROM main.identification WHERE archived_at IS NULL ORDER BY created_at DESC,id')]
    parsed = {}
    for entry in rows:
        try:
            raw = json.loads(entry['candidates'] or '[]')
        except ValueError:
            raw = []
        if isinstance(raw, dict):
            raw = raw.get('items', raw.get('candidates', []))
        parsed[entry['id']] = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    wanted = {c['item_id'] for found in parsed.values() for c in found if isinstance(c.get('item_id'), int)}
    labels = items.labels(db, {(i, None) for i in wanted}) if wanted else {}
    images = {}
    if wanted:
        for item_id, identifier in db.execute('SELECT item_id,id FROM main.picture WHERE item_id IN (SELECT value FROM json_each(?)) ORDER BY fetched_at,id',
                                              (json.dumps(sorted(wanted)),)):
            images[item_id] = identifier
    for entry in rows:
        choices = []
        for candidate in parsed[entry['id']]:
            item_id = candidate.get('item_id') if isinstance(candidate.get('item_id'), int) else None
            label = labels.get((item_id, None)) if item_id is not None else None
            number = (label.number if label and label.number else None) or candidate.get('number') or candidate.get('id') or candidate.get('part_num') \
                or candidate.get('part') or candidate.get('item_no')
            if not isinstance(number, (str, int)):
                continue
            choices.append(dict(item_id=item_id, item_no=str(number), item_type=types.get(candidate.get('type'), label.kind if label else 'part'),
                                name=candidate.get('name') or (label.name if label and label.name else 'Name not recorded'),
                                score=candidate.get('score', candidate.get('confidence')), image=images.get(item_id)))
        entry['candidates'] = choices
        result.append(entry)
    return result


def instruction_archive(db, identifier):
    from .collection import receipt, snapshot
    with transaction(db):
        old = snapshot(db, 'instruction_file', [identifier])
        if not old or old[0]['archived_at']: raise ValueError('Instruction file is unavailable')
        db.execute('UPDATE main.instruction_file SET archived_at=? WHERE id=?', (store4_now(), identifier))
        return receipt(db, [('instruction_file', old, snapshot(db, 'instruction_file', [identifier]))], 'archive')


from . import undo as undoing  # noqa: E402  (the module imports admin through the pieces it registers; admin is complete by here)

undoing.register('settings', 'save', _undo_settings, admin=True)

