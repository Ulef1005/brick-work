"""Copies (M.11b, issue #113): the list, one copy, completeness, the part check, part lines, figures, gaps and matches of a copy.

A copy is a row of `copy` (design 5); its lines are `copy_part` and `copy_figure` rows, a retired line (an in-place part-list switch
left it) is no line (design 4.4). Gaps and matches are the Workbench's (`core/workbench.py`), restricted to the copy."""
from collections import defaultdict

from ..core import checker, collection, completeness, errors, workbench
from . import route
from .read import (also, arguments, bodies, etag as etag_of, identity_filter, key_text, narrow, page, reading, record, respond, used_prices)
from .shapes import copy_bodies


def copy_row(db, copy_id):
    """The copy row (archived included), or 404."""
    row = collection.instance(db, 'copy', copy_id) if isinstance(copy_id, str) and len(copy_id) <= 64 else None
    if row is None:
        raise errors.NotFound('No such copy')
    return row


def require_live(db, copy_id):
    row = copy_row(db, copy_id)
    if row['archived_at']:
        raise errors.Archived('This copy is archived')
    return row


# ---------- the copy ----------

@route('/copies')
@reading
def get_copies(db):
    args = arguments()
    archived = args.get('archived', '')
    rows = collection.instances(db, 'set', include_archived=archived in ('true', 'include', 'only'))
    items, color = identity_filter(db, args)
    live_count = defaultdict(int)
    for r in rows:
        if not r['archived_at']:
            live_count[r['item_id']] += 1
    records = [record(r['id'], r['number'] or '', also=r['also'] or '', name=r['name'] or '', colour='', kind=r['kind'], status=r['completeness'] or '',
                      condition=r['condition'] or '', storage=r['storage_id'] or 'null', place=r['place_id'] or 'null', lot='null',
                      flags=[f['name'] for f in r['flags']], flag_ids=[f['id'] for f in r['flags']], theme=r['theme'] or '', category=r['category'] or '',
                      year=r['year'], duplicates=live_count[r['item_id']] > 1, missing=r['missing'], damaged=r['damaged'], quantity=1,
                      archived_at=r['archived_at'], item_id=r['item_id'], color_id=None, _row=r) for r in rows]
    records = narrow(records, items, color)
    if args.get('sort') == 'used_price':
        used_prices(db, records)
    return page(records, args, build=lambda chosen: copy_bodies(db, [r['_row'] for r in chosen]))


@route('/copies/<id>')
@reading
def get_copies_by_id(db, id):
    arguments()
    row = copy_row(db, id)
    return respond(copy_bodies(db, [row], single=True)[0], etag=etag_of(db, 'copy', id))


def completeness_body(db, row):
    """`Completeness` of a copy row: what is stored, what the lines derive, whether the set is checked and what is missing."""
    return {'stored': row['completeness'], 'completeness_source': row['completeness_source'], 'derived': completeness.derived_state(db, row['id']),
            'checked': checker.checked(db, row['id']), 'missing': row['missing'], 'damaged': row['damaged'], 'missing_figures': row['missing_figures']}


@route('/copies/<id>/completeness')
@reading
def get_copies_by_id_completeness(db, id):
    arguments()
    return respond(completeness_body(db, copy_row(db, id)))


def check_state(db, copy_id):
    """`CheckState`: the saved part-check session and the sequence of the check."""
    view = checker.view(db, copy_id)
    book = bodies(db, items=[r['item_id'] for r in view['rows']], colors=[r['color_id'] for r in view['rows']])
    rows = [{'token': r['token'], 'kind': r['kind'], 'id': r['id'], 'item': book.item(r['item_id']), 'name': r['name'], 'color': book.color(r['color_id']),
             'quantity': r['quantity'], 'missing': r['missing'], 'damaged': r['damaged'] if r['kind'] != 'figure' else None,
             'checked': bool(r['checked']) if r['kind'] != 'figure' else None, 'image_id': r.get('image'),
             'parts_lines': r.get('parts_lines'), 'parts_missing': r.get('parts_missing')} for r in view['rows']]
    session = view['session']
    return {'session': None if session is None else dict(session, saved_at=view['saved_at']), 'rows': rows}


@route('/copies/<id>/check')
@reading
def get_copies_by_id_check(db, id):
    arguments()
    require_live(db, id)
    return respond(check_state(db, id))


# ---------- the lines of a copy ----------

LINES = '''SELECT p.*, f.item_id AS figure_item, i.name FROM main.copy_part p JOIN main.item i ON i.id=p.item_id
    LEFT JOIN main.copy_figure f ON f.id=p.copy_figure_id WHERE p.copy_id=? AND p.retired_at IS NULL'''


def part_body(book, copy_id, r):
    """`CopyPart` of a line row of `LINES`."""
    parent = book.item(r['figure_item']) if r['figure_item'] is not None else None
    return {'id': r['id'], 'copy_id': copy_id, 'parent_minifig': parent, 'item': book.item(r['item_id']), 'name': r['name'], 'color': book.color(r['color_id']),
            'spare': r['is_spare'], 'quantity': r['quantity'], 'missing': r['missing'], 'damaged': r['damaged'], 'checked': bool(r['checked'])}


@route('/copies/<id>/parts')
@reading
def get_copies_by_id_parts(db, id):
    args = arguments()
    copy_row(db, id)
    lines = [dict(r) for r in db.execute(LINES + ' ORDER BY p.id', (id,))]
    book = bodies(db, items=[r['item_id'] for r in lines] + [r['figure_item'] for r in lines], colors=[r['color_id'] for r in lines])
    colours = {r['id']: r['name'] for r in db.execute('SELECT id, name FROM main.color')}
    records = []
    for r in lines:
        body = book.item(r['item_id'])
        parent = book.item(r['figure_item']) if r['figure_item'] is not None else None
        records.append(record(r['id'], (body['rebrickable'] or {}).get('key') or '', also=also(body), name=r['name'], colour=colours.get(r['color_id'], ''),
                              spare=bool(r['is_spare']), missing=r['missing'], damaged=r['damaged'], quantity=r['quantity'],
                              parent=['null'] if parent is None else [(parent['rebrickable'] or {}).get('key') or '', *[l['no'] for l in parent['bricklink']]],
                              _body=part_body(book, id, r)))
    return page(records, args, default_sort='index')


FIGURES = '''SELECT f.*, i.name, coalesce(c.lines, 0) AS parts_lines, coalesce(c.missing, 0) AS parts_missing FROM main.copy_figure f
    JOIN main.item i ON i.id=f.item_id
    LEFT JOIN (SELECT copy_figure_id, count(*) AS lines, sum(missing) AS missing FROM main.copy_part
               WHERE copy_id=? AND copy_figure_id IS NOT NULL AND retired_at IS NULL AND is_spare=0 GROUP BY copy_figure_id) c ON c.copy_figure_id=f.id
    WHERE f.copy_id=? AND f.retired_at IS NULL'''


def figure_body(body, r):
    """`CopyFigure` of a row of `FIGURES` and the item body of its figure."""
    return {'item': body, 'name': r['name'], 'quantity': r['quantity'], 'missing': r['missing'], 'parts_lines': r['parts_lines'], 'parts_missing': r['parts_missing']}


@route('/copies/<id>/figures')
@reading
def get_copies_by_id_figures(db, id):
    args = arguments()
    copy_row(db, id)
    rows = db.execute(FIGURES + ' ORDER BY f.id', (id, id)).fetchall()
    book = bodies(db, items=[r['item_id'] for r in rows])
    records = []
    for r in rows:
        body = book.item(r['item_id'])
        records.append(record(r['id'], (body['rebrickable'] or {}).get('key') or '', also=also(body), name=r['name'], quantity=r['quantity'], missing=r['missing'],
                              _body=figure_body(body, r)))
    return page(records, args, default_sort='index')


# ---------- gaps and matches ----------

def gap_bodies(db, gaps):
    book = bodies(db, items=[g['item_id'] for g in gaps], colors=[g['color_id'] for g in gaps])
    return [{'copy_id': g['copy_id'], 'item': book.item(g['item_id']), 'name': g['name'], 'color': book.color(g['color_id']), 'target': g['target'],
             'target_id': g['target_id'], 'need': g['need'], 'unresolved': bool(g['unresolved'])} for g in gaps]


def match_bodies(db, matches):
    book = bodies(db, items=[m['item_id'] for m in matches], colors=[m['color_id'] for m in matches])
    return [{'source_id': m['source_id'], 'copy_id': m['copy_id'], 'target': m['target'], 'target_id': m['target_id'], 'item': book.item(m['item_id']),
             'color': book.color(m['color_id']), 'have': m['have'], 'suggested': m['suggested'], 'completes': bool(m['completes'])} for m in matches]


def gap_records(gaps):
    return [record(key_text(g['target'], g['copy_id'], g['target_id']), g['number'] or '', also=g.get('also') or '', name=g['name'] or '',
                   colour=g.get('color_name') or '', kind=g['kind'], copy_id=g['copy_id'], need=g['need'], missing=g['need'], item_id=g['item_id'],
                   color_id=g['color_id'], _row=g) for g in gaps]


def match_records(matches):
    return [record(key_text(m['target'], m['copy_id'], m['target_id'], m['source_id']), m['number'] or '', also=m.get('also') or '', name=m['name'] or '',
                   colour=m.get('color_name') or '', kind=m['kind'], copy_id=m['copy_id'], completes=bool(m['completes']), item_id=m['item_id'],
                   color_id=m['color_id'], _row=m) for m in matches]


@route('/copies/<id>/gaps')
@reading
def get_copies_by_id_gaps(db, id):
    args = arguments()
    require_live(db, id)
    return page(gap_records(workbench.gaps(db, only=({id}, set()))), args, build=lambda chosen: gap_bodies(db, [r['_row'] for r in chosen]))


@route('/copies/<id>/matches')
@reading
def get_copies_by_id_matches(db, id):
    args = arguments()
    require_live(db, id)
    gaps = workbench.gaps(db, only=({id}, set()))
    return page(match_records(workbench.matches(db, all_gaps=gaps)), args, build=lambda chosen: match_bodies(db, [r['_row'] for r in chosen]))
