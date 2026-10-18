"""Photo identification history in brickwork.db: thumbnails, records, archive and Undo.

The Brickognize call itself is the budgeted source client; this module only keeps its
result. Originals stay in memory; only a clean 256 px thumbnail is written.
"""
from io import BytesIO
import json
from pathlib import Path
from uuid import uuid4
import warnings

from PIL import Image, ImageOps

from . import errors
from .transaction import on_rollback, transaction


def thumbnail(data):
    """A clean JPEG thumbnail (EXIF, ICC and other metadata dropped), or None if unreadable."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                oriented = ImageOps.exif_transpose(source)
                oriented.thumbnail((256, 256), Image.Resampling.LANCZOS)
                clean = Image.new('RGB', oriented.size)
                clean.paste(oriented.convert('RGB'))
                output = BytesIO()
                clean.save(output, format='JPEG', quality=80)
                return output.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def store(db, root, photo, candidates):
    """Record one result and its thumbnail in the caller's transaction; audited for Undo."""
    from .admin import audit
    from .sources.base import now
    identifier = str(uuid4())
    names = {}
    for kind, number in {(c['item_type'], c['item_no']) for c in candidates}:
        row = db.execute('SELECT name FROM items WHERE item_type=? AND item_no=?', (kind, number)).fetchone()
        names[kind, number] = row[0] if row else None
    shown = [dict(c, name=names[c['item_type'], c['item_no']]) for c in candidates]
    thumb = thumbnail(photo)
    stamp = now().isoformat()
    with transaction(db):
        db.execute('INSERT INTO identifications(id,created_at,has_thumb,candidates,missing_count) VALUES(?,?,?,?,0)',
                   (identifier, stamp, int(thumb is not None), json.dumps(shown)))
        if thumb is not None:
            target = Path(root).resolve() / 'data/identifications' / (identifier + '.jpg')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(thumb)
            on_rollback(db, lambda: target.unlink(missing_ok=True))
        audit(db, 'identification:' + identifier, 'create', new=dict(id=identifier, archived_at=None))
    return dict(id=identifier, created_at=stamp, has_thumb=thumb is not None, missing_count=0,
                candidates=shown, archived_at=None)


def archive(db, identifier):
    """Archive a record (thumbnail kept); Undo restores it."""
    from .admin import audit
    from .sources.base import now
    with transaction(db):
        row = db.execute('SELECT archived_at FROM identifications WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise errors.NotFound()
        if row[0] is not None:
            raise errors.Archived()
        stamp = now().isoformat()
        db.execute('UPDATE identifications SET archived_at=? WHERE id=?', (stamp, identifier))
        audit(db, 'identification:' + identifier, 'archive', new=dict(id=identifier, archived_at=stamp))


def undo(db, event, receipt):
    """Created -> archived, archived -> restored; refuses when the record changed since."""
    from .admin import audit
    from .sources.base import now
    value = json.loads(receipt['new_value'])
    identifier = value['id']
    with transaction(db):
        row = db.execute('SELECT archived_at FROM identifications WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise errors.NotUndoable()
        if receipt['field'] == 'create':
            if row[0] is not None:
                raise ValueError('Item changed · undo the later save first')
            db.execute('UPDATE identifications SET archived_at=? WHERE id=?', (now().isoformat(), identifier))
        elif receipt['field'] == 'archive':
            if row[0] != value['archived_at']:
                raise ValueError('Item changed · undo the later save first')
            db.execute('UPDATE identifications SET archived_at=NULL WHERE id=?', (identifier,))
        else:
            raise errors.NotUndoable()
        audit(db, receipt['entity'], 'undo', new=event)
