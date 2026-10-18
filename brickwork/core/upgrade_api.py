"""Atomic, idempotent schema 3.2 -> 3.3 upgrade; no legacy store access."""

TOKEN_DDL = '''CREATE TABLE api_tokens(
 id TEXT PRIMARY KEY NOT NULL, name TEXT UNIQUE NOT NULL, hash TEXT NOT NULL,
 scopes TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT,
 last_used_at TEXT, revoked_at TEXT)'''
KEY_DDL = '''CREATE TABLE source_keys(source TEXT PRIMARY KEY NOT NULL,
 ciphertext TEXT NOT NULL, saved_at TEXT NOT NULL, archived_at TEXT)'''


def pending(db):
    row = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'").fetchone()
    return bool(row and db.execute('SELECT version FROM schema_meta').fetchone()[0] == '3.2')


def upgrade(db):
    """Preserve event ids/content and reference links, changing only origin spelling."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not pending(db):
            return False
        # Save all append-only triggers and indexes, adapting their target table via its name.
        objects = db.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name='events' AND sql IS NOT NULL AND type IN ('trigger','index')").fetchall()
        for kind, name, sql in objects:
            if kind == 'trigger':
                db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        db.execute('''CREATE TABLE events_new(id INTEGER PRIMARY KEY, entity TEXT NOT NULL,
            field TEXT NOT NULL, old_value TEXT, new_value TEXT, at TEXT NOT NULL,
            via TEXT NOT NULL CHECK(via IN ('app','cli','api','import','migration')), actor TEXT)''')
        db.execute('''INSERT INTO events_new(id,entity,field,old_value,new_value,at,via)
            SELECT id,entity,field,old_value,new_value,at,
            CASE WHEN via='house-api' THEN 'api' ELSE via END FROM events''')
        db.execute('DROP TABLE events')
        db.execute('ALTER TABLE events_new RENAME TO events')
        for kind, name, sql in objects:
            db.execute(sql)
        # Older 3.2 stores may predate the INSERT OR REPLACE guard.
        db.execute("""CREATE TRIGGER IF NOT EXISTS events_no_replace BEFORE INSERT ON events
            WHEN EXISTS(SELECT 1 FROM events WHERE id=new.id)
            BEGIN SELECT RAISE(ABORT,'events are append-only'); END""")
        db.execute(TOKEN_DDL)
        db.execute(KEY_DDL)
        for table in ('purchase_locations', 'flags'):
            db.execute(f'ALTER TABLE {table} ADD COLUMN archived_at TEXT')
        # Some v3 installations still contain a local legacy-shaped settings table.
        # Import only within this connection; never attach/open a legacy database.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_settings'").fetchone():
            columns = [r[1] for r in db.execute('PRAGMA table_info(price_settings)')]
            keys = [k for k in columns if k.startswith('repair_') or k in (
                'bricklink_region', 'bricklink_currency', 'incomplete_discount_pct')]
            for key in keys:
                db.execute(f"INSERT OR IGNORE INTO settings(key,value) SELECT ?,CAST({key} AS TEXT) FROM price_settings WHERE id=1", (key,))
            db.execute('DROP TABLE price_settings')
        db.execute('DROP TABLE schema_meta')
        db.execute("CREATE TABLE schema_meta(version TEXT PRIMARY KEY CHECK(version='3.3'))")
        db.execute("INSERT INTO schema_meta VALUES('3.3')")
    return True


READ_INDEXES = {
    'events_undo_lookup': 'CREATE INDEX IF NOT EXISTS events_undo_lookup ON events(entity,field,new_value)',
    'events_add_undo_lookup': "CREATE INDEX IF NOT EXISTS events_add_undo_lookup ON events(old_value) WHERE entity='bw_add' AND field='undo'",
    'events_api_receipts': "CREATE INDEX IF NOT EXISTS events_api_receipts ON events(entity,field,actor,id DESC)",
    'events_api_undone': "CREATE INDEX IF NOT EXISTS events_api_undone ON events(json_extract(new_value,'$.undone_event_id')) WHERE entity='bw_api'",
    # Covers the per-identity "used in" read and the in-sets aggregate without a sort or a table visit.
    'copy_parts_identity_cover': 'CREATE INDEX IF NOT EXISTS copy_parts_identity_cover ON copy_parts(item_type,item_no,color_id,copy_id,quantity,missing,damaged)',
    # Unresolved figures read their source records by (source, source_id); the primary key leads with kind.
    'source_records_source_id': 'CREATE INDEX IF NOT EXISTS source_records_source_id ON source_records(source,source_id)',
}


PREVIOUS_DDL = '''CREATE TABLE IF NOT EXISTS source_key_previous(source TEXT PRIMARY KEY NOT NULL,
 ciphertext TEXT NOT NULL, saved_at TEXT NOT NULL, archived_at TEXT)'''


def _events_analyzed(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_stat1'").fetchone(): return False
    return db.execute("SELECT 1 FROM sqlite_stat1 WHERE tbl='events' LIMIT 1").fetchone() is not None


def _columns(db, table):
    return {r[1] for r in db.execute(f'PRAGMA table_info({table})')}


ALLOCATION_TARGET = """target_type IS NULL AND (copy_id IS NOT NULL OR target_copy_id IS NOT NULL
    OR target_stock_id IS NOT NULL OR kind IN ('loose_part','loose_figure'))"""


# Partial index over exactly the rows the backfill looks for, so the connect-time probe is a
# lookup in an (almost always empty) index instead of a scan of every allocation.
ALLOCATION_INDEX = 'allocations_untargeted'
ALLOCATION_INDEX_DDL = f'CREATE INDEX IF NOT EXISTS {ALLOCATION_INDEX} ON allocations(id) WHERE {ALLOCATION_TARGET}'


def perf_indexes_missing(db):
    """True when a performance-only index is absent. A hint: it never blocks a store that cannot be written."""
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    return ALLOCATION_INDEX not in names or not set(READ_INDEXES) <= names


def indexes_pending(db):
    if db.execute('SELECT 1 FROM allocations WHERE '+ALLOCATION_TARGET+' LIMIT 1').fetchone(): return True
    if 'archived_at' not in _columns(db, 'instruction_files'): return True
    if 'archived_at' not in _columns(db, 'identifications'): return True
    return not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_key_previous'").fetchone()


def upgrade_indexes(db):
    with db:
        db.execute("UPDATE allocations SET target_type=CASE WHEN copy_id IS NOT NULL OR target_copy_id IS NOT NULL THEN 'copy' ELSE 'stock' END WHERE "+ALLOCATION_TARGET)
        # Allocations from before target_copy_id existed carry only copy_id.
        db.execute("UPDATE allocations SET target_copy_id=copy_id WHERE target_type='copy' AND target_copy_id IS NULL AND copy_id IS NOT NULL")
        for table in ('instruction_files', 'identifications'):
            if 'archived_at' not in _columns(db, table):
                db.execute(f'ALTER TABLE {table} ADD COLUMN archived_at TEXT')
        # One level of previous key state, so Undo of a replacement never needs ciphertext in an event.
        db.execute(PREVIOUS_DDL)
        db.execute(ALLOCATION_INDEX_DDL)
        for ddl in READ_INDEXES.values():
            db.execute(ddl)
        if not _events_analyzed(db):
            # Without statistics SQLite prefers the covering (entity) index over the selective
            # expression index. Stores that already had the indexes never got statistics either.
            db.execute('ANALYZE events')
