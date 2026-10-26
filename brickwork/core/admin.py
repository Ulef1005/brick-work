"""New-store admin queries and atomic, app-audited mutations. No legacy adapters."""
from .transaction import transaction
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid

from .connect import connect
from ..store4.audit import value_text
from ..store4.connect import now as store4_now
from .importer.projection import PRIORITY
from .pipeline import Pipeline, TYPES, validate_priority
from .sources.base import now, redact

VALUES = {'owners': ('flags', 'owner'), 'statuses': ('flags', 'status'),
          'tags': ('flags', 'tag'), 'storages': ('storages', None),
          'purchase-places': ('purchase_locations', None)}
COLLECTION = {'copies', 'copy_parts', 'copy_minifigs', 'loose_stock',
              'loose_minifig_parts', 'inventory_lines', 'wishlist'}


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
    from .audit_bundle import CAPTURE
    captured = CAPTURE.get()
    if captured is not None:
        captured.append(dict(entity=entity,field=field,old_value=json.dumps(old),new_value=json.dumps(new)))
        return
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


def item_references(db):
    """Discover every composite item foreign key, including inventory parents."""
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        table = row[0]
        keys = {}
        for fk in db.execute(f'PRAGMA foreign_key_list("{table}")'):
            if fk['table'] == 'items':
                keys.setdefault(fk['id'], {})[fk['to']] = fk['from']
        for key in keys.values():
            if set(key) == {'item_type', 'item_no'}:
                yield table, key['item_type'], key['item_no']


def reference_count(db, key, collection_only=False):
    return sum(db.execute(f'SELECT count(*) FROM "{t}" WHERE "{a}"=? AND "{b}"=?', key).fetchone()[0]
               for t, a, b in item_references(db) if not collection_only or t in COLLECTION)


def candidates(evidence, kind):
    """Normalize current pipeline evidence and the v3 migration envelopes."""
    found = {}
    def walk(value):
        if isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, dict):
            number = value.get('bricklink_item_no') or value.get('bricklink_id') or value.get('item_no') or (value.get('bricklink') if isinstance(value.get('bricklink'), str) else None)
            target = value.get('target')
            item_type = value.get('item_type') or ('M' if kind == 'minifigure' else 'P')
            if isinstance(target, list) and len(target) == 2:
                item_type, number = target
            if number and item_type in TYPES:
                found[item_type, str(number)] = dict(item_type=item_type, item_no=str(number),
                    name=value.get('name') or str(number), score=value.get('score', value.get('confidence')))
            links = value.get('bricklink')
            if isinstance(links, list):
                for n in links:
                    if isinstance(n, str):
                        found.setdefault((item_type, n), dict(item_type=item_type, item_no=n, name=n, score=None))
            # inventory-child evidence contains the whole parent JSON and its ordinal.
            record = value.get('record', {})
            if 'ordinal' in value and isinstance(record, dict) and 'parts_json' in record:
                walk(json.loads(record['parts_json'])[value['ordinal']])
                return
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
    walk(evidence)
    return list(found.values())


def local_image(db, kind, number):
    row = db.execute('SELECT id FROM item_images WHERE item_type=? AND item_no=? ORDER BY fetched_at DESC,id DESC LIMIT 1',
                     (kind, number)).fetchone()
    return row[0] if row else None


UNRESOLVED_STATUS = "status IN ('to_check','unmatched')"


def count_unresolved(db):
    """Count what unresolved() lists, without reading payloads or evidence."""
    exists = ' OR '.join(f'EXISTS(SELECT 1 FROM "{t}" WHERE "{a}"=m.item_type AND "{b}"=m.item_no)'
                         for t, a, b in item_references(db) if t in COLLECTION)
    if not exists:
        return 0
    return db.execute(f"SELECT count(*) FROM id_match m WHERE {UNRESOLVED_STATUS} AND m.item_type IS NOT NULL AND m.item_type!='' AND ({exists})").fetchone()[0]


def unresolved(db):
    result = []
    # Discover FK paths once, then aggregate every referenced identity in bulk.
    references = {}
    for table, a, b in item_references(db):
        if table not in COLLECTION:
            continue
        for r in db.execute(f'SELECT "{a}","{b}",count(*) FROM "{table}" GROUP BY 1,2'):
            references[r[0], r[1]] = references.get((r[0], r[1]), 0) + r[2]
    names = {(r[0], r[1]): r[2] for r in db.execute('SELECT item_type,item_no,name FROM items')}
    images = {(r[0], r[1]): r[2] for r in db.execute('SELECT item_type,item_no,id FROM item_images ORDER BY fetched_at,id')}
    matches = [row for row in db.execute(f"SELECT * FROM id_match WHERE {UNRESOLVED_STATUS} ORDER BY kind,source_id")
               if row['item_type'] and references.get((row['item_type'], row['item_no']))]
    # Payloads are large: read only the records of the matches that will be shown.
    wanted = json.dumps([[row['source'], row['source_id']] for row in matches])
    records = {(r[0], r[1]): r[2] for r in db.execute(
        """SELECT source,source_id,payload FROM source_records
           WHERE (source,source_id) IN (SELECT json_extract(value,'$[0]'),json_extract(value,'$[1]') FROM json_each(?))
           ORDER BY fetched_at""", (wanted,))}
    for row in matches:
        key = row['item_type'], row['item_no']
        value = dict(row)
        choices = candidates(json.loads(row['evidence_json']), row['kind'])
        for choice in choices:
            choice['image'] = images.get((choice['item_type'], choice['item_no']))
        value['candidates'] = choices
        value['name'] = names.get(key) or row['source_id']
        raw = records.get((row['source'], row['source_id']))
        value['reference_url'] = None
        if raw:
            def read_identity(payload):
                if isinstance(payload, dict):
                    value['name'] = payload.get('name') or value['name']
                    value['reference_url'] = payload.get('set_img_url') or payload.get('part_img_url') or payload.get('image') or value['reference_url']
                    for child in payload.values():
                        if isinstance(child, (dict, list)):
                            read_identity(child)
                elif isinstance(payload, list):
                    for child in payload:
                        read_identity(child)
            try:
                read_identity(json.loads(raw))
            except ValueError:
                pass
        value['image'] = images.get(key)
        value['references'] = references[key]
        result.append(value)
    return result


def resolve(db, source, kind, source_id, selected=None):
    with transaction(db):
        row = db.execute('SELECT * FROM id_match WHERE source=? AND kind=? AND source_id=?',
                         (source, kind, source_id)).fetchone()
        if not row or row['status'] not in ('to_check', 'unmatched'):
            raise ValueError('This match is no longer unresolved')
        old = row['item_type'], row['item_no']
        if selected is None:
            db.execute("UPDATE id_match SET status='to_check' WHERE source=? AND kind=? AND source_id=?", (source, kind, source_id))
            audit(db, 'match:' + source_id, 'leave', row['status'], 'to_check')
            return
        allowed = {(c['item_type'], c['item_no']) for c in candidates(json.loads(row['evidence_json']), kind)}
        if selected not in allowed or not reference_count(db, old, True):
            raise ValueError('Choose a recorded candidate')
        db.execute('INSERT OR IGNORE INTO items(item_type,item_no) VALUES(?,?)', selected)
        wish_flags = db.execute("SELECT entity_id,flag_id FROM item_flags WHERE entity_type='wishlist' AND entity_id IN (SELECT CAST(id AS TEXT) FROM wishlist WHERE item_type=? AND item_no=?)", old).fetchall()
        db.execute("DELETE FROM item_flags WHERE entity_type='wishlist' AND entity_id IN (SELECT CAST(id AS TEXT) FROM wishlist WHERE item_type=? AND item_no=?)", old)
        # Updates cover all FK paths. Unmergeable uniqueness conflicts fail atomically.
        for table, a, b in item_references(db):
            if table == 'id_match':
                continue
            if table == 'copy_minifigs':
                for previous in db.execute('SELECT * FROM copy_minifigs WHERE item_type=? AND minifig_no=?', old).fetchall():
                    exists = db.execute('SELECT 1 FROM copy_minifigs WHERE copy_id=? AND item_type=? AND minifig_no=?',
                                        (previous['copy_id'], *selected)).fetchone()
                    if exists:
                        db.execute('UPDATE copy_minifigs SET quantity=coalesce(quantity,0)+?,missing=coalesce(missing,0)+? WHERE copy_id=? AND item_type=? AND minifig_no=?',
                                   (previous['quantity'] or 0, previous['missing'] or 0, previous['copy_id'], *selected))
                        db.execute('DELETE FROM copy_minifigs WHERE copy_id=? AND item_type=? AND minifig_no=?', (previous['copy_id'], *old))
            db.execute(f'UPDATE "{table}" SET "{a}"=?,"{b}"=? WHERE "{a}"=? AND "{b}"=?', (*selected, *old))
        for flag in wish_flags:
            db.execute("INSERT INTO item_flags VALUES('wishlist',?,?)", (flag['entity_id'], flag['flag_id']))
        db.execute("UPDATE id_match SET item_type=?,item_no=?,status='manual',method='manual',decided_at=? WHERE item_type=? AND item_no=?",
                   (*selected, now().isoformat(), *old))
        audit(db, 'match:' + source_id, 'identity', old, selected)


def value_rows(db, group):
    if group not in VALUES:
        raise ValueError('Unknown value group')
    table, kind = VALUES[group]
    where = ' WHERE archived_at IS NULL' + (' AND kind=?' if kind else '')
    rows = db.execute(f'SELECT * FROM {table}' + where + ' ORDER BY name,id', (kind,) if kind else ())
    # Aggregate once per reference table, never once per value row.
    references = []
    for t in ('item_flags',) if kind else ('copies', 'loose_stock', 'lots', 'identification_actions'):
        if t == 'identification_actions' and table != 'storages':
            continue
        column = ('flag_id' if kind else 'storage' if t == 'identification_actions'
                  else 'storage_id' if table == 'storages' else 'purchase_location_id')
        counts = dict(db.execute(f'SELECT {column},count(*) FROM {t} GROUP BY {column}'))
        references.append((t, column, counts))
    return [dict(row, count=sum(counts.get(row['id'], 0) for _, _, counts in references),
                 references=[(t, c, counts.get(row['id'], 0)) for t, c, counts in references])
            for row in rows]


def value_write(db, group, action, identifier=None, name=None, confirmed=False):
    if group not in VALUES or action not in ('add', 'rename', 'delete'):
        raise ValueError('Unknown value action')
    table, kind = VALUES[group]
    if action != 'delete' and (not name or not name.strip() or len(name) > 120):
        raise ValueError('Enter a name of up to 120 characters')
    if table == 'storages':
        from . import ledger
        if action == 'delete':
            if not confirmed:
                raise ValueError('Confirm deletion and its reference count')
            return ledger.storage_archive(db, identifier)
        return ledger.storage_save(db, identifier if action == 'rename' else None, name)[1]
    with transaction(db):
        from .collection import snapshot, receipt
        before = snapshot(db, table, [identifier]) if action != 'add' else []
        if action != 'add' and (not before or before[0]['archived_at'] or (kind and before[0]['kind'] != kind)):
            raise ValueError('Value is no longer available')
        if action == 'add':
            identifier = uuid.uuid4().hex
            columns = '(id,name,kind,shown_on_grid)' if kind else '(id,name)'
            args = (identifier, name.strip(), kind, 1) if kind else (identifier, name.strip())
            db.execute(f'INSERT INTO {table}{columns} VALUES({",".join("?" for _ in args)})', args)
        elif action == 'rename':
            db.execute(f'UPDATE {table} SET name=? WHERE id=?', (name.strip(), identifier))
        else:
            if not confirmed:
                raise ValueError('Confirm deletion and its reference count')
            db.execute(f'UPDATE {table} SET archived_at=? WHERE id=?', (now().isoformat(), identifier))
        return receipt(db, [(table, before, snapshot(db, table, [identifier]))],
                       'archive' if action == 'delete' else 'save')


def settings(db):
    values = dict(db.execute('SELECT key,value FROM settings'))
    from .price_settings import read
    return dict(**read(db), retail_country=values.get('retail_country', 'DE'),
                priority=json.loads(values.get('source_priority') or json.dumps(PRIORITY)),
                import_order={k.removeprefix('import_order:'): json.loads(v) for k, v in sorted(values.items())
                              if k.startswith('import_order:')},
                display_currency=values.get('display_currency') or values.get('bricklink_currency') or 'EUR',
                freshness=[dict(r) for r in db.execute('SELECT * FROM source_freshness ORDER BY source,kind')])


def patch_settings(db, data):
    """PATCH /settings (#47): any subset of the whitelisted settings, in one transaction.

    freshness: [{source, kind, max_age_days}] (as GET /settings returns it); import_order:
    {item type: [the six steps]}; repair: {shipping, fees, min_order, use_loose_stock}.
    """
    from . import errors, price_settings
    from .pipeline import STEPS, TYPES
    allowed = {'retail_country', 'bricklink_region', 'bricklink_currency', 'incomplete_discount_pct',
               'source_priority', 'import_order', 'freshness', 'repair', 'display_currency'}
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
            save_settings(db, data.get('retail_country', current['retail_country']),
                          data.get('source_priority', current['priority']), rules)
        if 'display_currency' in data:
            from .currency import set_display
            set_display(db, data['display_currency'])
        if 'import_order' in data:
            orders = data['import_order']
            if not isinstance(orders, dict) or not orders:
                raise errors.ValidationFailed('import_order is {item type: [steps]}')
            for kind, order in orders.items():
                if kind not in TYPES or not isinstance(order, list) or len(order) != len(STEPS) or set(order) != set(STEPS):
                    raise errors.ValidationFailed('Each import order lists all six steps once')
            before = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM settings WHERE key LIKE 'import_order:%'")}
            db.executemany('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',
                           [('import_order:' + k, json.dumps(v)) for k, v in sorted(orders.items())])
            audit(db, 'settings', 'import_order', before, {'import_order:' + k: v for k, v in orders.items()})
        return settings(db)


def save_settings(db, country, priority, freshness):
    if country not in ('DE', 'US', 'UK', 'CA'):
        raise ValueError('Choose a supported retail country')
    validate_priority(priority)
    with transaction(db):
        old = settings(db)
        db.execute("INSERT OR REPLACE INTO settings VALUES('retail_country',?)", (country,))
        db.execute("INSERT OR REPLACE INTO settings VALUES('source_priority',?)", (json.dumps(priority),))
        for source, kind, days in freshness:
            days = None if days == '' else int(days)
            if days is not None and days < 0:
                raise ValueError('Freshness days must be zero or more')
            if not db.execute('SELECT 1 FROM source_freshness WHERE source=? AND kind=?', (source, kind)).fetchone():
                raise ValueError('Unknown freshness rule')
            db.execute('UPDATE source_freshness SET max_age_days=? WHERE source=? AND kind=?', (days, source, kind))
        audit(db, 'settings', 'save', old, settings(db))


def stale_prices(db):
    # Latest successful market observations per source, condition and colour.
    rows = db.execute('''SELECT i.item_type,i.item_no,i.name,w.color_id,w.condition FROM items i
        JOIN (SELECT item_type,set_no item_no,NULL color_id,condition FROM copies WHERE archived_at IS NULL
              UNION SELECT item_type,item_no,color_id,condition FROM loose_stock WHERE archived_at IS NULL
              UNION SELECT item_type,item_no,color_id,CASE condition WHEN 'new' THEN 'N' WHEN 'used' THEN 'U' END FROM wishlist WHERE archived_at IS NULL) w
        ON w.item_type=i.item_type AND w.item_no=i.item_no WHERE i.item_type!='?' ''').fetchall()
    config = settings(db)['priority']['market_price']
    rules = {(r['source'], r['kind']): r['max_age_days'] for r in db.execute('SELECT * FROM source_freshness')}
    enabled_sources = dict(db.execute('SELECT source,enabled FROM sources'))
    observed_dates = {}
    for r in db.execute('''SELECT item_type,item_no,color_id,condition,source,max(observed_at) observed
        FROM price_observations WHERE guide IN ('sold','stock') AND error IS NULL GROUP BY 1,2,3,4,5'''):
        observed_dates[tuple(r[:5])] = r['observed']
        key = (r[0], r[1], r[2], None, r[4])
        observed_dates[key] = max(observed_dates.get(key) or '', r['observed'] or '')
    result = []
    for row in rows:
        sources = config.get(row['item_type'], config.get('*', []))
        stale = False
        for source in sources:
            source = source.split(':')[0]
            if source in enabled_sources and not enabled_sources[source]:
                continue
            days = rules.get((source, 'prices'), rules.get((source, 'price'), 7))
            if days is None:
                continue
            observed = observed_dates.get((row['item_type'], row['item_no'], row['color_id'], row['condition'], source))
            try:
                stamp = datetime.fromisoformat(observed) if observed else None
                if stamp is not None and stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                fresh = stamp is not None and (now() - stamp).total_seconds() < days * 86400
            except ValueError:
                fresh = False
            stale |= not fresh
        if stale:
            result.append(dict(row))
    return result


def live_import_job(db, item_type, item_no):
    """Return an item's active pipeline job, including a budget wait."""
    row = db.execute("SELECT id FROM jobs WHERE source='import' AND item_type=? AND item_no=? AND state IN ('queued','running','waiting_for_budget') ORDER BY id LIMIT 1",
                     (item_type, item_no)).fetchone()
    return row[0] if row else None


def queue_refresh(db, rows, steps=('market_price',), sources=None):
    pipeline = Pipeline(db)
    with transaction(db):
        jobs = []
        for key in sorted({(r['item_type'], r['item_no']) for r in rows}):
            if live_import_job(db, *key) is not None:
                continue
            jobs.append(pipeline.queue_steps(*key, steps, sources=sources))
        return jobs


def queue_missing_booklets(db):
    """Queue the existing identity step for booklet identities without a PDF.

    The import pipeline has no instruction-PDF step, so this refreshes the
    catalogue record only; it never downloads a PDF. Identities the pipeline
    would reject are skipped and returned, so one bad number cannot undo the batch.
    Returns (queued job ids, skipped item numbers).
    """
    rows = db.execute("""SELECT item_type,item_no FROM items i WHERE item_type='I' AND NOT EXISTS(
        SELECT 1 FROM instruction_files f WHERE f.item_type='I' AND f.set_no=i.item_no)""").fetchall()
    ok = lambda r: re.fullmatch('[A-Za-z0-9-]{1,32}', r['item_no'])
    valid = [r for r in rows if ok(r)]
    skipped = [r['item_no'] for r in rows if not ok(r)]
    return queue_refresh(db, valid, steps=('identity',)), skipped


def count_jobs(db):
    return db.execute("SELECT count(*) FROM jobs WHERE source='import'").fetchone()[0]


def jobs(db):
    has_steps = db.execute("SELECT 1 FROM sqlite_master WHERE name='import_steps'").fetchone()
    from collections import defaultdict
    steps = defaultdict(list)
    if has_steps:
        for row in db.execute("""SELECT s.* FROM import_steps s JOIN jobs j ON j.id=s.job_id
                WHERE j.source='import' ORDER BY s.job_id,s.position"""):
            steps[row['job_id']].append(dict(row))
    return [{**dict(r), 'steps': steps[r['id']]}
            for r in db.execute("SELECT * FROM jobs WHERE source='import' ORDER BY id DESC")]


def statistics(db):
    def grouped(expression, joins=''):
        return [dict(r) for r in db.execute(f'''SELECT coalesce({expression},'Not recorded') label,count(*) count
            FROM copies c {joins} WHERE c.archived_at IS NULL GROUP BY label ORDER BY count DESC,label''')]
    return {'completeness': grouped("CASE c.completeness WHEN 'S' THEN 'Sealed' WHEN 'C' THEN 'Complete' WHEN 'I' THEN 'Incomplete' ELSE 'Not checked' END"),
            'theme': grouped("(SELECT value FROM item_properties p WHERE p.item_type=c.item_type AND p.item_no=c.set_no AND p.key='theme' ORDER BY p.fetched_at DESC LIMIT 1)"),
            'storage': grouped('s.name', 'LEFT JOIN storages s ON s.id=c.storage_id AND s.archived_at IS NULL'),
            'purchase place': grouped('p.name', 'LEFT JOIN purchase_locations p ON p.id=c.purchase_location_id'),
            'spent_vs_retail': _spent_vs_retail(db)}


def _spent_vs_retail(db):
    from .retail import spent_vs_retail
    return spent_vs_retail(db)


def check(db):
    return {'integrity_check': [r[0] for r in db.execute('PRAGMA integrity_check')],
            'foreign_key_check': [dict(r) for r in db.execute('PRAGMA foreign_key_check')],
            'row_counts': {r[0]: db.execute(f'SELECT count(*) FROM "{r[0]}"').fetchone()[0]
                           for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}}


CHECK_KEY = 'maintenance:database_check'
CHECK_FINDINGS_STORED = 200


def last_check(db):
    """The stored result of the last explicit database check, or None. Never runs a check."""
    row = db.execute('SELECT value FROM settings WHERE key=?', (CHECK_KEY,)).fetchone()
    try:
        value = json.loads(row[0]) if row and row[0] else None
    except ValueError:
        return None
    return value if isinstance(value, dict) and 'integrity_check' in value else None


def run_check(db):
    """Run the full check, keep its result with a date, and audit the run (one transaction, not undoable)."""
    result = check(db)
    result['foreign_key_total'] = len(result['foreign_key_check'])
    result['foreign_key_check'] = result['foreign_key_check'][:CHECK_FINDINGS_STORED]
    result['checked_at'] = now().isoformat()
    ok = result['integrity_check'] == ['ok'] and not result['foreign_key_total']
    with transaction(db):
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (CHECK_KEY, json.dumps(result)))
        audit(db, 'database', 'check', new='ok' if ok else 'needs attention')
    return result


def instruction_rename(db, identifier, label, *, undoable=False):
    if not label or len(label) > 120:
        raise ValueError('Enter a label of up to 120 characters')
    with transaction(db):
        from .collection import receipt, snapshot
        old = snapshot(db, 'instruction_files', [identifier])
        if not old:
            raise ValueError('Instruction file no longer exists')
        db.execute('UPDATE instruction_files SET label=? WHERE id=?', (label, identifier))
        if undoable:
            return receipt(db, [('instruction_files', old, snapshot(db, 'instruction_files', [identifier]))], 'label')
        audit(db, 'instruction:' + str(identifier), 'label', old[0]['label'], label)


def instruction_upload(db, root, kind, number, label, content, *, undoable=False):
    """Install immutable, content-addressed booklets; roll back a new file on failure."""
    from hashlib import sha256
    if not content.startswith(b'%PDF-') or len(content) > 20 * 1024 * 1024:
        raise ValueError('Choose a PDF up to 20 MB')
    if not db.execute('SELECT 1 FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone():
        raise ValueError('Choose an existing item')
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
            identifier = db.execute('INSERT INTO instruction_files(item_type,set_no,path,label,added_at) VALUES(?,?,?,?,?)',
                (kind, number, relative.as_posix(), label, now().isoformat())).lastrowid
            from .collection import receipt, snapshot
            if undoable:
                receipt(db, [('instruction_files', [], snapshot(db, 'instruction_files', [identifier]))], 'attach')
            else:
                audit(db, 'instruction:' + str(identifier), 'attach', new={'item_type':kind, 'item_no':number, 'path':relative.as_posix(), 'label':label})
        return identifier
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


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
    result = []
    types = {'part': 'P', 'minifig': 'M', 'minifigure': 'M', 'set': 'S'}
    for row in db.execute('SELECT * FROM identifications WHERE archived_at IS NULL ORDER BY created_at DESC'):
        entry = dict(row)
        try:
            raw = json.loads(row['candidates'] or '[]')
        except ValueError:
            raw = []
        if isinstance(raw, dict):
            raw = raw.get('items', raw.get('candidates', []))
        choices = []
        for candidate in raw if isinstance(raw, list) else []:
            if not isinstance(candidate, dict):
                continue
            number = candidate.get('id') or candidate.get('part_num') or candidate.get('part') or candidate.get('item_no')
            if not isinstance(number, (str, int)):
                continue
            kind = candidate.get('item_type') or types.get(candidate.get('type'), 'P')
            known = db.execute('SELECT name FROM items WHERE item_type=? AND item_no=?', (kind, str(number))).fetchone()
            choices.append(dict(item_no=str(number), item_type=kind,
                name=candidate.get('name') or (known[0] if known and known[0] else 'Name not recorded'),
                score=candidate.get('score', candidate.get('confidence')), image=local_image(db, kind, str(number))))
        entry['candidates'] = choices
        result.append(entry)
    return result


def instruction_archive(db, identifier):
    from .collection import receipt, snapshot
    with transaction(db):
        old = snapshot(db, 'instruction_files', [identifier])
        if not old or old[0]['archived_at']: raise ValueError('Instruction file is unavailable')
        db.execute('UPDATE instruction_files SET archived_at=? WHERE id=?', (now().isoformat(), identifier))
        return receipt(db, [('instruction_files', old, snapshot(db, 'instruction_files', [identifier]))], 'archive')
