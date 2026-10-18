"""Source administration for the API: enable or disable, catalogue import, colour sync."""
import json
from pathlib import Path

from . import errors
from .transaction import transaction


def clients():
    from .sources.bricklink import BrickLink
    from .sources.brickognize import Brickognize
    from .sources.brickset import Brickset
    from .sources.rebrickable import Rebrickable
    return {c.source: c for c in (BrickLink, Rebrickable, Brickset, Brickognize)}


def known(source):
    if source not in clients():
        raise errors.NotFound('Unknown source')
    return source


def ensure(db, source):
    """Register a client's `sources` row on first use, with its budget and freshness rules."""
    with transaction(db):
        clients()[known(source)](db).register()


def view(db, source):
    from .api_reads import sources
    return next(r for r in sources(db) if r['source'] == source)


def toggle(db, source, enabled):
    from .admin import audit
    known(source)
    if type(enabled) is not bool:
        raise errors.ValidationFailed('enabled must be true or false')
    with transaction(db):
        ensure(db, source)
        old = db.execute('SELECT enabled FROM sources WHERE source=?', (source,)).fetchone()[0]
        db.execute('UPDATE sources SET enabled=? WHERE source=?', (int(enabled), source))
        audit(db, 'source:' + source, 'enabled', old, int(enabled))


def undo_toggle(db, identifier, receipt):
    from .admin import audit
    source = receipt['entity'].split(':', 1)[1]
    old, new = json.loads(receipt['old_value']), json.loads(receipt['new_value'])
    with transaction(db):
        row = db.execute('SELECT enabled FROM sources WHERE source=?', (source,)).fetchone()
        if row is None or row[0] != new:
            raise ValueError('Item changed · undo the later save first')
        db.execute('UPDATE sources SET enabled=? WHERE source=?', (old, source))
        audit(db, receipt['entity'], 'undo', new=identifier)


def catalogue_import(db):
    """Rebuild the BrickLink catalogue index from the XML files beside the database."""
    from .media import store_dir
    from .sources.bricklink_catalogue import info, load, source_directory
    base = store_dir(db)
    directory = source_directory(base / 'brickwork.db')
    if not directory.is_dir() or not any(directory.glob('*.xml')):
        raise errors.ValidationFailed('Place the BrickLink catalogue XML files in the catalogue source folder first')
    load(directory, base / 'bricklink-catalog.db', db)
    value = info(base / 'bricklink-catalog.db')
    return dict(loaded=value['available'], imported_at=value.get('loaded_at'), items=value.get('counts', {}))


def sync_colours(db):
    from .sources.bricklink import BrickLink
    before = db.execute('SELECT count(*) FROM colors').fetchone()[0]
    received = BrickLink(db).sync_colors()
    return dict(colors=received, added=db.execute('SELECT count(*) FROM colors').fetchone()[0] - before)
