"""Two-file connection: the collection (WAL) with the catalogue attached read-only as `catalogue`."""
from contextlib import closing
from datetime import datetime, timezone
import os
import re
from pathlib import Path
import sqlite3
import uuid

from .errors import CatalogueError, CatalogueMismatch, SchemaMismatch, StaleSchema, Unsupported, UpgradeFailed

MIN_SQLITE = (3, 37, 0)
SCHEMA_VERSION = '4.2'
# In-place upgrades of an older collection, one step per version, each in its own write transaction: {from: (to, statements)}.
# A step only adds; a fresh file from `brickwork.sql` has the same tables as an upgraded one (tests/test_store4_upgrade.py).
UPGRADES = {
    '4.0': ('4.1', (                                     # #131: a wish's max price with box, a price with its currency or neither
        'ALTER TABLE wish ADD COLUMN max_price_boxed TEXT',
        'ALTER TABLE wish ADD COLUMN max_price_boxed_currency TEXT CHECK((max_price_boxed IS NULL) = (max_price_boxed_currency IS NULL))')),
    '4.1': ('4.2', (                                     # #167: who owns a job claim (boot id + start ticks); #155: why an order line is not placed
        'ALTER TABLE job_owner ADD COLUMN boot_id TEXT',
        'ALTER TABLE job_owner ADD COLUMN start_ticks INTEGER',
        'ALTER TABLE order_line ADD COLUMN unplaced_reason TEXT')),
}
# The columns the steps add, by table: a row recorded before its step (an Undo receipt, a RowLog) lacks them and reads them as NULL.
ADDED_COLUMNS = {}
for _target, _statements in UPGRADES.values():
    for _statement in _statements:
        if (_added := re.match(r'ALTER TABLE (\w+) ADD COLUMN (\w+)', _statement)):
            ADDED_COLUMNS.setdefault(_added[1], []).append(_added[2])
CATALOGUE_VERSION = 'catalogue-4.0'
HERE = Path(__file__).parent
FIX = ('restore brickwork.db and catalogue.db from the same archive, '
       'or run `brickwork catalogue rebuild` to rebuild the catalogue seeded from this collection')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def check_environment():
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise Unsupported(f'SQLite {sqlite3.sqlite_version} found; Brick Work 4.0 needs 3.37.0 or newer (STRICT tables)')
    probe = sqlite3.connect(':memory:')
    try:
        probe.execute('CREATE VIRTUAL TABLE t USING fts5(x)')
    except sqlite3.Error:
        raise Unsupported(f'SQLite {sqlite3.sqlite_version} was built without FTS5, which Brick Work 4.0 needs') from None
    finally:
        probe.close()


def _uri(path, mode=None):
    return Path(path).resolve().as_uri() + (f'?mode={mode}' if mode else '')


def _meta(db, schema='main'):
    try:
        return dict(db.execute(f'SELECT key, value FROM {schema}.meta').fetchall())
    except sqlite3.OperationalError:
        return None


AUTOINCREMENT_TABLES = ('item_link', 'picture')      # integer keys a RowLog deletes from: a freed id must never be handed out again (#124)


def check_ids_never_reused(db, path):
    """Refuse a 4.0 file made before #124, whose `item_link` and `picture` ids were not AUTOINCREMENT: an undo of a merge or a kind move
    could be refused falsely there. No such file is in production; the migration builds a new one."""
    found = dict(db.execute("SELECT name, sql FROM main.sqlite_master WHERE type='table' AND name IN (?, ?)", AUTOINCREMENT_TABLES).fetchall())
    if any('AUTOINCREMENT' not in (found.get(name) or '').upper() for name in AUTOINCREMENT_TABLES):
        raise StaleSchema(f'{path} predates #124 (made before 2026-10-27): re-run the 3.3 \u2192 4.0 migration to rebuild it')


def as_current(table, row):
    """A row of `table` as recorded (a receipt, a RowLog entry), with every column an upgrade added since as NULL: Undo compares and
    restores rows written before the upgrade like rows written after it."""
    added = ADDED_COLUMNS.get(table)
    if row is None or not added or all(c in row for c in added):
        return row
    return {**row, **{c: None for c in added if c not in row}}


def upgrade(path):
    """Bring an older collection at `path` to `SCHEMA_VERSION` in place, step by step (`UPGRADES`). Each step re-reads the version
    inside its write transaction, so concurrent openers upgrade once; a failed step rolls back and leaves the file at its last version.
    Returns the version the file is at; a version with no step (current, or unknown) is left alone for `connect` to judge."""
    db = sqlite3.connect(_uri(path), uri=True, isolation_level=None)
    try:
        while True:
            db.execute('BEGIN IMMEDIATE')
            version = (_meta(db) or {}).get('schema_version')
            if version not in UPGRADES:
                db.execute('ROLLBACK')
                return version
            target, statements = UPGRADES[version]
            try:
                for statement in statements:
                    db.execute(statement)
                db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (target,))
                db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (f'upgraded_to_{target}', now()))
                db.execute('COMMIT')
            except BaseException:
                if db.in_transaction:                    # SQLite may have rolled back already (a full disk): keep the real error
                    db.execute('ROLLBACK')
                raise
    finally:
        db.close()


def bring_up_to_date(path):
    """Upgrade the collection at `path` in place when it is at an older 4.x version (`UPGRADES`); a no-op at the current version.
    A stale file (#124) is refused before anything writes to it. The one explicit upgrade moment is app start; a read-write `connect`
    does the same, a read-only one never writes and refuses a file that still needs it."""
    with closing(sqlite3.connect(_uri(path, 'ro'), uri=True)) as probe:
        old = (_meta(probe) or {}).get('schema_version')
        if old not in UPGRADES:
            return old
        check_ids_never_reused(probe, path)              # a stale file is refused before anything writes to it
    try:
        return upgrade(path)
    except sqlite3.OperationalError as exc:
        hint = ('another process holds the file; open it again in a moment' if 'locked' in str(exc) or 'busy' in str(exc)
                else 'make it writable and open it again')
        raise UpgradeFailed(f'{path} is a Brick Work {old} collection and could not be upgraded to {SCHEMA_VERSION} '
                            f'in place ({exc}); {hint}') from exc


def connect(path='brickwork.db', catalogue='catalogue.db', *, read_only=False):
    check_environment()
    path, catalogue = Path(path), Path(catalogue)
    if not read_only and not path.exists():
        _create(path, 'brickwork.sql', [('schema_version', SCHEMA_VERSION), ('install_id', str(uuid.uuid4()))], exclusive=False)
    db = _open(path, read_only)
    version = (_meta(db) or {}).get('schema_version')
    if version in UPGRADES:
        db.close()
        if read_only:                                    # a read-only open never writes: the file stays as it is
            raise UpgradeFailed(f'{path} is a Brick Work {version} collection; open it read-write once (start the app) to upgrade '
                                f'it to {SCHEMA_VERSION} in place')
        bring_up_to_date(path)
        db = _open(path, read_only)
        version = (_meta(db) or {}).get('schema_version')
    try:
        # Check the version before any pragma that writes: a refused file is left exactly as it was.
        if version != SCHEMA_VERSION:
            raise SchemaMismatch(f'{path} is not a Brick Work {SCHEMA_VERSION} collection (schema_version={version!r}); '
                                 'a 3.3 file must be migrated, never opened')
        check_ids_never_reused(db, path)
        if read_only:
            db.execute('PRAGMA query_only=ON')
        else:
            db.execute('PRAGMA journal_mode=WAL')
        if catalogue.exists():
            _attach(db, catalogue)
        return db
    except BaseException:
        db.close()
        raise


def _open(path, read_only):
    db = sqlite3.connect(_uri(path, 'ro' if read_only else None), uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
    except BaseException:
        db.close()
        raise
    return db


def _create(path, schema, meta, *, exclusive):
    """Build a new file beside `path` and hard-link it into place, so a concurrent first opener either wins or
    finds the finished file; a failure removes only the temporary file. `exclusive`: an existing `path` is an error."""
    tmp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.new')
    try:
        db = sqlite3.connect(tmp)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript('BEGIN;\n' + (HERE / schema).read_text())
            db.executemany('INSERT INTO meta(key, value) VALUES(?, ?)', meta + [('created_at', now())])
            db.commit()
        finally:
            db.close()
        try:
            os.link(tmp, path)
        except FileExistsError:
            if exclusive:
                raise
    finally:
        for suffix in ('', '-journal'):
            Path(str(tmp) + suffix).unlink(missing_ok=True)


def _attach(db, catalogue):
    db.execute('ATTACH DATABASE ? AS catalogue', (_uri(catalogue, 'ro'),))
    check_compatible(db, catalogue)


def check_compatible(db, label='the attached catalogue'):
    """Do the collection and the attached catalogue belong together? The id binding, every build the collection activated,
    and the high-water marks. Called at attach, and again by activation and reconcile inside their write transaction: a
    connection opened before a rebuild keeps the old file, which another connection may have moved past."""
    cat = _meta(db, 'catalogue')
    if cat is None or cat.get('schema_version') != CATALOGUE_VERSION:
        raise CatalogueError(f'{label} is not a Brick Work catalogue ({CATALOGUE_VERSION}); {FIX}')
    mode = db.execute('PRAGMA catalogue.journal_mode').fetchone()[0]
    if mode != 'delete':
        raise CatalogueError(f'{label} has journal_mode={mode}, not delete (a read-only attach needs no -shm); {FIX}')
    coll = _meta(db)
    bound = coll.get('catalogue_id')
    if bound is not None and bound != cat.get('catalogue_id'):
        raise CatalogueMismatch(f'{label} is another catalogue than the one this collection is bound to; {FIX}')
    have = {r[0] for r in db.execute('SELECT id FROM catalogue.build')}
    missing = sorted(r[0] for r in db.execute('SELECT id FROM main.catalogue_build') if r[0] not in have)
    if missing:
        raise CatalogueMismatch(f'this collection activated catalogue builds {missing} that {label} lacks; {FIX}')
    for mine, theirs in (('catalogue_item_high_water', 'item_high_water'), ('catalogue_color_high_water', 'color_high_water')):
        if int(coll.get(mine) or 0) > int(cat.get(theirs) or 0):
            raise CatalogueMismatch(f'{label} is older than this collection ({theirs} {cat.get(theirs) or 0} < {coll[mine]}); {FIX}')


def has_catalogue(db):
    return any(r[1] == 'catalogue' for r in db.execute('PRAGMA database_list'))


def create_catalogue(path):
    """Create an empty catalogue file (journal_mode=DELETE) and return it open for the builder."""
    check_environment()
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    _create(path, 'catalogue.sql', [('schema_version', CATALOGUE_VERSION)], exclusive=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db
