"""Source administration on the 4.0 store (M.8f, issue #110): the source list, enable or disable, and the pipeline's handlers.

A source is a row of `source` (seeded; `enabled` is the switch) and a client class in `core.sources`. `register_handlers` hands the
pipeline its three steps' handlers (`pictures`, `metadata`, `market_price`); the app calls it once at start. The 3.3 operations that
had no 4.0 premise are gone: the BrickLink colour table and item names come with the catalogue builds (`catalogue import bricklink`,
M.8i), not from a source call."""
import json

from . import errors, pipeline
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


def register_handlers(**options):
    """Make the pipeline run the source steps: pictures (three sources), Brickset metadata, BrickLink prices. `options` are the test seams
    (`http` for the API calls, `image_http` for downloads, `root` for the picture cache). Idempotent."""
    from . import pictures
    from .sources import bricklink, brickset
    pictures.register(**{k: v for k, v in options.items() if k in ('http', 'image_http', 'root')})
    for module in (bricklink, brickset):
        for (step, source), function in module.handlers(http=options.get('http')).items():
            pipeline.register(step, source, function)


def view(db, source):
    """What the Catalogues & keys list shows of a source: its switch, key state and the day's budget."""
    client = clients()[known(source)](db)
    row = db.execute('SELECT name, kind, enabled FROM source WHERE id=?', (source,)).fetchone()
    return dict(source=source, name=row['name'] if row else client.label, kind=row['kind'] if row else 'api',
                enabled=bool(row['enabled']) if row else True, **client.status())


def toggle(db, source, enabled):
    from .admin import audit
    known(source)
    if type(enabled) is not bool:
        raise errors.ValidationFailed('enabled must be true or false')
    with transaction(db):
        row = db.execute('SELECT enabled FROM source WHERE id=?', (source,)).fetchone()
        if row is None:
            raise errors.NotFound('Unknown source')
        db.execute('UPDATE source SET enabled=? WHERE id=?', (int(enabled), source))
        audit(db, 'source:' + source, 'enabled', row[0], int(enabled))


def _undo_toggle(db, event, via, actor):
    from .admin import audit
    source = event['entity_id']
    old, new = json.loads(event['old_value']), json.loads(event['new_value'])
    row = db.execute('SELECT enabled FROM source WHERE id=?', (source,)).fetchone()
    if row is None or row[0] != new:
        raise ValueError('Item changed · undo the later save first')
    db.execute('UPDATE source SET enabled=? WHERE id=?', (old, source))
    audit(db, 'source:' + source, 'undo', new=event['id'], via=via, actor=actor)
    undo_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('INSERT INTO event_undo(event_id, undo_event_id) VALUES(?, ?)', (event['id'], undo_id))
    return {'event_id': undo_id}


from . import undo as undoing  # noqa: E402

undoing.register('source', 'enabled', _undo_toggle, admin=True)
