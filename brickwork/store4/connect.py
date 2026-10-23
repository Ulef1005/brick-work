"""Two-file connection: the collection (WAL) with the catalogue attached read-only as `catalogue`."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

from .errors import CatalogueError, CatalogueMismatch, SchemaMismatch, Unsupported

MIN_SQLITE = (3, 37, 0)
SCHEMA_VERSION = '4.0'
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


def connect(path='brickwork.db', catalogue='catalogue.db', *, read_only=False):
    check_environment()
    path, catalogue = Path(path), Path(catalogue)
    new = not path.exists() and not read_only
    db = sqlite3.connect(_uri(path, 'ro' if read_only else None), uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        if not new:
            # Check the version before any pragma that writes: a refused file is left exactly as it was.
            version = (_meta(db) or {}).get('schema_version')
            if version != SCHEMA_VERSION:
                raise SchemaMismatch(f'{path} is not a Brick Work {SCHEMA_VERSION} collection (schema_version={version!r}); '
                                     'a 3.3 file must be migrated, never opened')
        if read_only:
            db.execute('PRAGMA query_only=ON')
        else:
            db.execute('PRAGMA journal_mode=WAL')
        if new:
            db.executescript('BEGIN;\n' + (HERE / 'brickwork.sql').read_text())
            db.executemany('INSERT INTO meta(key, value) VALUES(?, ?)',
                           [('schema_version', SCHEMA_VERSION), ('install_id', str(uuid.uuid4())), ('created_at', now())])
            db.commit()
        if catalogue.exists():
            _attach(db, catalogue)
        return db
    except BaseException:
        db.close()
        if new:
            for suffix in ('', '-wal', '-shm'):
                Path(str(path) + suffix).unlink(missing_ok=True)
        raise


def _attach(db, catalogue):
    db.execute('ATTACH DATABASE ? AS catalogue', (_uri(catalogue, 'ro'),))
    cat = _meta(db, 'catalogue')
    if cat is None or cat.get('schema_version') != CATALOGUE_VERSION:
        raise CatalogueError(f'{catalogue} is not a Brick Work catalogue ({CATALOGUE_VERSION}); {FIX}')
    mode = db.execute('PRAGMA catalogue.journal_mode').fetchone()[0]
    if mode != 'delete':
        raise CatalogueError(f'{catalogue} has journal_mode={mode}, not delete (a read-only attach needs no -shm); {FIX}')
    coll = _meta(db)
    bound = coll.get('catalogue_id')
    if bound is not None and bound != cat.get('catalogue_id'):
        raise CatalogueMismatch(f'{catalogue} is another catalogue than the one this collection is bound to; {FIX}')
    have = {r[0] for r in db.execute('SELECT id FROM catalogue.build')}
    missing = sorted(r[0] for r in db.execute('SELECT id FROM main.catalogue_build') if r[0] not in have)
    if missing:
        raise CatalogueMismatch(f'this collection activated catalogue builds {missing} that {catalogue} lacks; {FIX}')
    for mine, theirs in (('catalogue_item_high_water', 'item_high_water'), ('catalogue_color_high_water', 'color_high_water')):
        if int(coll.get(mine) or 0) > int(cat.get(theirs) or 0):
            raise CatalogueMismatch(f'{catalogue} is older than this collection ({theirs} {cat.get(theirs) or 0} < {coll[mine]}); {FIX}')


def has_catalogue(db):
    return any(r[1] == 'catalogue' for r in db.execute('PRAGMA database_list'))


def create_catalogue(path):
    """Create an empty catalogue file (journal_mode=DELETE) and return it open for the builder."""
    check_environment()
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=DELETE')
        db.executescript('BEGIN;\n' + (HERE / 'catalogue.sql').read_text())
        db.executemany('INSERT INTO meta(key, value) VALUES(?, ?)', [('schema_version', CATALOGUE_VERSION), ('created_at', now())])
        db.commit()
        return db
    except BaseException:
        db.close()
        path.unlink(missing_ok=True)
        raise
