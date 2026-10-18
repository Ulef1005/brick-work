"""Additive upgrades for existing brickwork.db files (fresh files get the DDL in schema.sql)."""
import sqlite3
import re


WISH_INDEX = 'wishlist_currency_pending'
WISH_INDEX_DDL = (f'CREATE INDEX IF NOT EXISTS {WISH_INDEX} ON wishlist(id) '
                  'WHERE max_price IS NOT NULL AND max_price_currency IS NULL')


def wish_currency_pending(db):
    """True when the wish-limit currency column is missing or a limit still lacks its currency."""
    columns = [r[1] for r in db.execute('PRAGMA table_info(wishlist)')]
    if not columns:
        return False
    if 'max_price_currency' not in columns:
        return True
    return db.execute('SELECT 1 FROM wishlist WHERE max_price IS NOT NULL AND max_price_currency IS NULL LIMIT 1').fetchone() is not None


def wish_index_missing(db):
    columns = [r[1] for r in db.execute('PRAGMA table_info(wishlist)')]
    return bool(columns) and 'max_price_currency' in columns and \
        not db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (WISH_INDEX,)).fetchone()


def configured_currency(db):
    try:
        row = db.execute("SELECT value FROM settings WHERE key='bricklink_currency'").fetchone()
    except sqlite3.OperationalError:  # no settings table: the documented default applies
        row = None
    return (row[0] if row and row[0] else 'EUR')


def upgrade_wish_currency(db):
    """Add wishlist.max_price_currency and give every existing limit the configured BrickLink currency.

    Re-runnable: the column is added once, and only wishes that have a max and no currency are
    backfilled, so a second run changes nothing. No other column is touched; no events row is
    written because this is a migration, not a user edit. Returns what it did.
    """
    result = dict(column_added=False, backfilled=0, currency=None)
    with db:
        db.execute('BEGIN IMMEDIATE')
        # Read the shape inside the write lock: a concurrent upgrader may have added the column already.
        columns = [r[1] for r in db.execute('PRAGMA table_info(wishlist)')]
        if not columns:
            return result
        if 'max_price_currency' not in columns:
            try:
                db.execute('ALTER TABLE wishlist ADD COLUMN max_price_currency TEXT')
                result['column_added'] = True
            except sqlite3.OperationalError as exc:
                if 'duplicate column' not in str(exc).lower():
                    raise
        currency = configured_currency(db)
        count = db.execute('UPDATE wishlist SET max_price_currency=? WHERE max_price IS NOT NULL AND max_price_currency IS NULL', (currency,)).rowcount
        result.update(backfilled=count, currency=currency if count else None)
        db.execute(WISH_INDEX_DDL)
    return result


def wishlists_pending(db):
    columns = [r[1] for r in db.execute('PRAGMA table_info(wishlist)')]
    return bool(columns) and ('list_id' not in columns or not db.execute("SELECT 1 FROM sqlite_master WHERE name='wishlists' AND type='table'").fetchone())


def upgrade_wishlists(db):
    """Backfill the default list and replace the live identity index atomically."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not wishlists_pending(db):
            return False
        db.execute("""CREATE TABLE IF NOT EXISTS wishlists(id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL,
            note TEXT, sort INTEGER NOT NULL DEFAULT 0, archived_at TEXT, created_at TEXT, bricklink_id TEXT)""")
        db.execute("INSERT OR IGNORE INTO wishlists(id,name,created_at) VALUES('default','Wishlist',strftime('%Y-%m-%dT%H:%M:%fZ','now'))")
        columns = [r[1] for r in db.execute('PRAGMA table_info(wishlist)')]
        if 'list_id' not in columns:
            # SQLite cannot ADD a non-null REFERENCES column with a non-null default
            # while foreign keys are enforced. Rebuild inside the lock, retaining all
            # original columns, row ids, indexes and guards (including external triggers).
            original = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='wishlist'").fetchone()[0]
            indexes = [r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='wishlist' AND sql IS NOT NULL AND name!='wishlist_live_key'")]
            triggers = [(r[0], r[1]) for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL") if re.search(r'\bwishlist\b', r[1], re.I)]
            for name, _ in triggers:
                db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
            ddl = re.sub(r'^CREATE TABLE (?:"wishlist"|\[wishlist\]|`wishlist`|wishlist)', 'CREATE TABLE wishlist_named_upgrade', original, count=1, flags=re.I)
            db.execute(ddl.replace('(', "(list_id TEXT NOT NULL DEFAULT 'default' REFERENCES wishlists(id),", 1))
            quoted = ','.join('"'+c.replace('"','""')+'"' for c in columns)
            db.execute("INSERT INTO wishlist_named_upgrade("+quoted+",list_id) SELECT "+quoted+",'default' FROM wishlist")
            db.execute('DROP TABLE wishlist')
            db.execute('ALTER TABLE wishlist_named_upgrade RENAME TO wishlist')
            for sql in indexes: db.execute(sql)
            for _, sql in triggers: db.execute(sql)
        db.execute('DROP INDEX IF EXISTS wishlist_live_key')
        db.execute("CREATE UNIQUE INDEX wishlist_live_key ON wishlist(list_id,item_type,item_no,color_id IS NULL,coalesce(color_id,0)) WHERE archived_at IS NULL")
    return True


STORAGE_COLUMNS = (('storages', 'type', 'TEXT'), ('storages', 'parent_id', 'TEXT REFERENCES storages(id)'),
                   ('storages', 'note', 'TEXT'), ('purchase_locations', 'kind', 'TEXT'))


def storage_fields_pending(db):
    """#46: storage type, parent and note; purchase location kind (nullable columns, nothing to backfill)."""
    have = {}
    for table, column, _ in STORAGE_COLUMNS:
        if table not in have:
            have[table] = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
        if have[table] and column not in have[table]:
            return True
    return False


def storage_index_missing(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='storages'").fetchone()) and not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='storages_parent_fk'").fetchone()


def upgrade_storage_fields(db):
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not storage_fields_pending(db) and not storage_index_missing(db):
            return False
        for table, column, ddl in STORAGE_COLUMNS:
            if column not in {r[1] for r in db.execute(f'PRAGMA table_info({table})')}:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
        db.execute('CREATE INDEX IF NOT EXISTS storages_parent_fk ON storages(parent_id)')
    return True


def wish_filled_pending(db):
    """#35: wishlist.qty_filled_manual, the per-line override of the filled quantity."""
    columns = {r[1] for r in db.execute('PRAGMA table_info(wishlist)')}
    return bool(columns) and 'qty_filled_manual' not in columns


def upgrade_wish_filled(db):
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not wish_filled_pending(db):
            return False
        db.execute('ALTER TABLE wishlist ADD COLUMN qty_filled_manual INTEGER CHECK(qty_filled_manual IS NULL OR qty_filled_manual >= 0)')
    return True


def pending(db, writable=True):
    """True when an upgrade must run. Missing performance indexes count only for a writable store:
    a read-only mount cannot build them, and must not take the init lock or retry on every connect."""
    from . import currency, upgrade_api
    if (upgrade_api.pending(db) or upgrade_api.indexes_pending(db) or wish_currency_pending(db) or wishlists_pending(db)
            or storage_fields_pending(db) or wish_filled_pending(db) or currency.pending(db)):
        return True
    return writable and (upgrade_api.perf_indexes_missing(db) or wish_index_missing(db) or storage_index_missing(db))


def upgrade_connection(db):
    from . import currency, upgrade_api
    # Price settings must be imported before the wish currency backfill.
    api = upgrade_api.upgrade(db) if upgrade_api.pending(db) else False
    upgrade_api.upgrade_indexes(db)
    return dict(api_v1=api, wish_currency=upgrade_wish_currency(db), wishlists=upgrade_wishlists(db),
                storage_fields=upgrade_storage_fields(db), wish_filled=upgrade_wish_filled(db),
                exchange_rates=currency.upgrade(db))


def upgrade(path):
    """Open the file writable and apply every pending additive upgrade."""
    db = sqlite3.connect(path)
    try:
        db.isolation_level = None
        return upgrade_connection(db)
    finally:
        db.close()


if __name__ == '__main__':
    import json, sys
    print(json.dumps(upgrade(sys.argv[1] if len(sys.argv) > 1 else 'data/brickwork.db'), indent=2))
