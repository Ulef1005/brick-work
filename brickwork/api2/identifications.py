"""Photo identification (M.11d, issue #113): upload a picture, see the items it may be, and the history.

Brickognize (`core/sources/brickognize.py`, budgeted and audited like every source) is asked outside any transaction; the result is stored in
the one that stores the answer, with a 256 px thumbnail, and Undo archives it. A candidate names the item by its body (section 2.1), the score the
source gave and, on the answer of the upload, what you already hold of it (#45)."""
from pathlib import Path
import json

from flask import Response

from ..core import errors, identify, ownership
from ..core.media import media_root
from ..core.sources.brickognize import Brickognize, photo_bytes
from . import route
from .read import arguments, bodies, flag, page, reading, record, respond
from .writes import Done, write


def identification_body(db, r, owned=None, unresolved=None):
    """`Identification` for a row of `identification`: the candidates it stored, each with its item body."""
    candidates = json.loads(r['candidates'] or '[]')
    book = bodies(db, items=[c['item_id'] for c in candidates if c.get('item_id') is not None])
    shown = []
    for c in candidates:
        found = {'item': book.item(c['item_id']) if c.get('item_id') is not None else None, 'score': c.get('score'), 'name': c.get('name')}
        if owned is not None:
            found['owned'] = owned.get(c.get('item_id'))
        shown.append(found)
    body = {'id': r['id'], 'created_at': r['created_at'], 'has_thumb': bool(r['has_thumb']), 'missing_count': r['missing_count'], 'archived_at': r['archived_at'],
            'candidates': shown}
    if unresolved is not None:
        body['unresolved'] = unresolved
    return body


def identification(db, identifier):
    row = db.execute('SELECT * FROM main.identification WHERE id=?', (identifier,)).fetchone() if len(identifier) <= 64 else None
    if row is None:
        raise errors.NotFound('No such identification')
    return row


@route('/identifications')
@reading
def get_identifications(db):
    args = arguments()
    direction = args.get('direction', 'asc')
    if direction not in ('asc', 'desc'):
        raise errors.UnknownFilter('direction is asc or desc')
    records = [record(r['id'], r['created_at'] + r['id'], created_at=r['created_at'], _row=r)
               for r in db.execute('SELECT * FROM main.identification WHERE archived_at IS NULL')]
    return page(records, {k: v for k, v in args.items() if k in ('cursor', 'limit', 'direction')}, default_sort='number', default_direction='asc',
                build=lambda chosen: [identification_body(db, r['_row']) for r in chosen])


@route('/identifications/<id>')
@reading
def get_identifications_by_id(db, id):
    arguments()
    return respond(identification_body(db, identification(db, id)))


@route('/identifications/<id>/thumb')
@reading
def get_identifications_by_id_thumb(db, id):
    arguments()
    row = identification(db, id)
    target = Path(media_root(db)).resolve() / 'data/identifications' / (row['id'] + '.jpg')
    if not row['has_thumb'] or not target.is_file():
        raise errors.NotFound('This identification has no thumbnail')
    return Response(target.read_bytes(), mimetype='image/jpeg')


@route('/identifications', 'POST')
@write(detached=True)
def post_identifications(db, body, content):
    """Recognise a photo and keep the result. The call to Brickognize is made first, outside any transaction."""
    photo = photo_bytes(content)
    choices, unresolved = identify.recognise(db, photo)
    kept = [{'item_id': c['item_id'], 'score': c.get('score'), 'name': c.get('name')} for c in choices]
    owned = {c['item_id']: c['owned_summary'] for c in choices}

    def run():
        stored = identify.store(db, media_root(db), photo, kept)
        row = db.execute('SELECT * FROM main.identification WHERE id=?', (stored['id'],)).fetchone()
        return Done(identification_body(db, row, owned, [{'kind': u['item_type'], 'number': u['item_no'], 'score': u.get('score'), 'reason': u['reason']} for u in unresolved]),
                    status=201)
    return run


@route('/identifications/<id>', 'DELETE')
@write
def delete_identifications_by_id(db, body, id):
    row = identification(db, id)
    identify.archive(db, row['id'])
    return Done(identification_body(db, identification(db, id)))
