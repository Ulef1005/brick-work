"""Instruction files (M.11b, issue #113): the PDFs attached to sets and the coverage of the booklet identities.

A PDF belongs to a set (the store allows no other item); a booklet shares the files of the set with its number (`collection.instruction_files`,
`admin.instruction_overview`). The list serves every file record; `coverage` counts the booklet identities and how many have a file."""
from flask import send_file

from ..core import admin, errors
from ..core.media import media_root
from ..store4 import lookup
from . import route
from .read import (also, arguments, bodies, flag, identity_filter, integer_id, narrow, page, reading, record, respond)

SELECT = '''SELECT f.*, i.name, i.kind FROM main.instruction_file f JOIN main.item i ON i.id=f.item_id'''


def on_disk(root, row):
    target = (root / row['path']).resolve()
    return target.is_relative_to(root / 'data/instructions') and target.is_file()


def file_body(book, root, r):
    present = not r['archived_at'] and on_disk(root, r)
    return {'archived_at': r['archived_at'], 'id': r['id'], 'item': book.item(r['item_id']), 'name': r['name'], 'label': r['label'], 'added_at': r['added_at'],
            'content_url': f"/api/v2/instruction-files/{r['id']}/content" if present else None}


@route('/instruction-files')
@reading
def get_instruction_files(db):
    args = arguments()
    wanted = flag(args, 'has_file')
    kind = args.get('kind') or None
    if kind is not None and kind not in lookup.KINDS:
        raise errors.ValidationFailed('kind is one of ' + ', '.join(lookup.KINDS))
    items, color = identity_filter(db, args)
    root = media_root(db)
    files = db.execute(SELECT + ' ORDER BY f.id').fetchall()
    book = bodies(db, items=[r['item_id'] for r in files])
    records = []
    for r in files:
        body = book.item(r['item_id'])
        records.append(record(r['id'], (body['rebrickable'] or {}).get('key') or '', also=also(body), name=r['name'], kind=r['kind'], archived_at=r['archived_at'],
                              has_file=on_disk(root, r), item_id=r['item_id'], color_id=None, _body=file_body(book, root, r)))
    records = narrow(records, items, color)
    if wanted is not None:
        records = [r for r in records if r['has_file'] == wanted]
    if kind:
        records = [r for r in records if r['kind'] == kind]
    overview = admin.instruction_overview(db)['coverage']
    return page(records, args, applied=('has_file', 'kind'), default_sort='index', coverage={'total': overview['total'], 'covered': overview['covered']})


def one(db, identifier):
    row = db.execute(SELECT + ' WHERE f.id=?', (integer_id(identifier, 'instruction file'),)).fetchone()
    if row is None:
        raise errors.NotFound('No such instruction file')
    return row


@route('/instruction-files/<id>')
@reading
def get_instruction_files_by_id(db, id):
    arguments()
    row = one(db, id)
    return respond(file_body(bodies(db, items=[row['item_id']]), media_root(db), row))


@route('/instruction-files/<id>/content')
@reading
def get_instruction_files_by_id_content(db, id):
    arguments()
    row = one(db, id)
    root = media_root(db)
    if row['archived_at'] or not on_disk(root, row):
        raise errors.NotFound('No such instruction file')
    return send_file((root / row['path']).resolve(), mimetype='application/pdf', as_attachment=True, download_name='instructions.pdf')
