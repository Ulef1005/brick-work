"""Wishes and wishlists (M.11b, issue #113): the lists, one wish, and the portable exports.

A wish is a `wish` row with a uuid id (Q6), a kind word, an item id and, for a part, a colour. It is priced as the Wishlist screen prices it
and carries its progress (#35). The exports are `core/wishlists.py`'s: BrickLink wanted-list XML and Rebrickable CSV, with the rows that
cannot be named left out and listed."""
from flask import Response

from ..core import errors, wishlists
from ..store4 import lookup
from . import route
from .read import arguments, etag as etag_of, flag, identity_filter, narrow, page, reading, record, respond
from .shapes import wish_bodies, wish_rows


@route('/wishes')
@reading
def get_wishes(db):
    args = arguments()
    flag(args, 'under_max')
    kind = args.get('kind') or None
    if kind is not None and kind not in lookup.KINDS:
        raise errors.ValidationFailed('kind is one of ' + ', '.join(lookup.KINDS))
    items, color = identity_filter(db, args)
    archived = args.get('archived', '') in ('true', 'include', 'only')
    rows = wish_rows(db, '' if archived else 'WHERE w.archived_at IS NULL')
    if args.get('list'):
        rows = [r for r in rows if r['list_id'] == args['list']]
    records = []
    for r in rows:
        shown = r.get('display_price')
        records.append(record(r['id'], r['number'] or '', also=r['also'] or '', name=r['name'] or '', colour=r['color_name'] or '', kind=r['kind'],
                              condition=r['condition'] or '', flags=[f['name'] for f in r['flags']], flag_ids=[f['id'] for f in r['flags']],
                              theme=r['theme'] or '', category=r['category'] or '', year=r['year'], quantity=r['quantity'], missing=0, damaged=0,
                              max_state=r['max_state'], price=[shown.get('currency') or 'Currency not recorded', shown['price']] if shown and shown.get('price') else None,
                              archived_at=r['archived_at'], item_id=r['item_id'], color_id=r['color_id'], _row=r))
    records = narrow(records, items, color)
    return page(records, args, applied=('list',), build=lambda chosen: wish_bodies(db, [r['_row'] for r in chosen]))


@route('/wishes/<id>')
@reading
def get_wishes_by_id(db, id):
    arguments()
    rows = wish_rows(db, 'WHERE w.id=?', (id,)) if len(id) <= 64 else []
    if not rows:
        raise errors.NotFound('No such wish')
    return respond(wish_bodies(db, rows)[0], etag=etag_of(db, 'wish', id))


# ---------- wishlists ----------

@route('/wishlists')
@reading
def get_wishlists(db):
    args = arguments()
    archived = flag(args, 'archived')
    rows = wishlists.listing(db, archived=bool(archived))
    records = [record(r['id'], r['name'], name=r['name'], archived_at=r['archived_at'], index=r['sort'],
                      _body={'id': r['id'], 'name': r['name'], 'note': r['note'], 'sort': r['sort'], 'archived_at': r['archived_at'],
                             'created_at': r['created_at'], 'bricklink_id': r['bricklink_id'], 'count': r['count']}) for r in rows]
    # `archived=true` includes the archived lists (a boolean here, unlike the `archived` of the other lists), `false` is the default.
    return page(records, {k: v for k, v in args.items() if k != 'archived' or archived}, default_sort='index')


def export(db, identifier, format):
    args = arguments()
    summary = flag(args, 'summary')
    kind = args.get('kind', 'parts')
    if kind not in ('sets', 'parts'):
        raise errors.ValidationFailed('kind is sets or parts')
    if identifier != 'all':
        row = db.execute('SELECT archived_at FROM main.wishlist WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise errors.NotFound('No such wishlist')
        if row['archived_at']:
            raise errors.Archived('This wishlist is archived')
    result = wishlists.export(db, identifier, format='bricklink' if format == 'xml' else 'rebrickable', kind=kind)
    if summary:
        return respond(result)
    return Response(result['content'], mimetype=result['mimetype'], headers={
        'Content-Disposition': 'attachment; filename=' + result['filename'],
        'X-Wishlist-Exported': str(result['summary']['exported']),
        'X-Wishlist-Omitted': str(len(result['summary']['omitted'])),
        'X-Wishlist-Notes': str(len(result['summary']['notes']))})


@route('/wishlists/<id>/export.xml')
@reading
def get_wishlists_by_id_export_xml(db, id):
    return export(db, id, 'xml')


@route('/wishlists/<id>/export.csv')
@reading
def get_wishlists_by_id_export_csv(db, id):
    return export(db, id, 'csv')
