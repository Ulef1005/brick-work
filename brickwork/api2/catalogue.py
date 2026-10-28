"""Catalogue, colours and the item list (M.11b, issue #113): `/catalogue/*`, `/colors*`, `GET /items`.

The catalogue is the attached `catalogue.db` (Rebrickable's dump plus the BrickLink item lists, design 3.1), not v1's BrickLink file. A
catalogue entry is read as the catalogue holds it; an item the collection projected is read from the collection (`store4.lookup`).
`/catalogue/items` pages in SQL (the catalogue is 100,000 rows), the other lists filter and sort in Python like every v2 list."""
import base64
import json
import re

from ..core import errors, items as items_core
from ..core.listing import natural
from ..store4 import lookup
from ..store4.connect import has_catalogue
from . import route
from .read import also, arguments, bodies, integer_id, page, reading, record, respond

CAP = 5000                                                    # hits ordered for a text search; the exact count is not promised beyond it


# ---------- colours ----------

@route('/colors')
@reading
def get_colors(db):
    args = arguments()
    rows = [record(c['id'], str(c['id']), name=c['name'], colour=c['name'], _body=c) for c in lookup.colors(db)]
    # A colour is found by its name or by any of its ids (a Brick Work, BrickLink or Rebrickable number).
    for row in rows:
        c = row['_body']
        row['category'] = ' '.join(str(c[k]) for k in ('id', 'bricklink_id', 'rebrickable_id') if c[k] is not None)
    return page(rows, args)


@route('/colors/<color_id>')
@reading
def get_colors_by_color_id(db, color_id):
    arguments()
    body = lookup.color_body(db, integer_id(color_id, 'colour'))
    if body is None:
        raise errors.NotFound('No such colour')
    return respond(body)


# ---------- the catalogue file ----------

def _require(db):
    if not has_catalogue(db):
        raise errors.CatalogueNotLoaded('There is no catalogue.db beside the collection (python -m brickwork.store4 catalogue download)')


def _count(db, kind=None):
    where, args = ('kind=? AND ', (kind,)) if kind else ('', ())
    return db.execute(f'SELECT count(*) FROM catalogue.item WHERE {where}retired_at IS NULL', args).fetchone()[0]


@route('/catalogue/status')
@reading
def get_catalogue_status(db):
    arguments()
    loaded = has_catalogue(db)
    status = {'loaded': loaded}
    if not loaded:
        return respond(status)
    activated = {r['id']: r for r in db.execute('SELECT id, activated_at, reconciled_at, counts_json FROM main.catalogue_build')}
    builds = []
    for r in db.execute('SELECT id, kind, started_at, finished_at, mapping_version, counts_json FROM catalogue.build ORDER BY id'):
        counts = json.loads(r['counts_json'] or '{}')
        builds.append({'id': r['id'], 'built_at': r['finished_at'] or r['started_at'], 'dump_date': counts.get('dump_date'),
                       'mapping_version': r['mapping_version'], 'local_mapping_manifest': counts.get('local_mappings'),
                       'bricklink_list': counts.get('bricklink_list'), 'activated': r['id'] in activated})
    coverage = {s: 0 for s in ('matched', 'inferred', 'manual', 'to_check')}
    coverage.update({r[0]: r[1] for r in db.execute('SELECT status, count(*) FROM main.item_link GROUP BY status')})
    last = db.execute('SELECT reconciled_at, counts_json FROM main.catalogue_build WHERE reconciled_at IS NOT NULL ORDER BY id DESC LIMIT 1').fetchone()
    reconcile = None
    if last:
        reconcile = {'at': last['reconciled_at'], 'summary': json.loads(last['counts_json'] or '{}').get('reconcile')}
    status.update(items=_count(db), builds=builds, coverage=coverage, last_reconcile=reconcile)
    return respond(status)


def owned_counts(db, ids):
    """`{item id: pieces owned}` (live set copies, and loose stock quantities) and the ids on a live wish, in two queries."""
    packed = json.dumps(sorted(ids))
    owned = {r[0]: r[1] for r in db.execute('''SELECT item_id, sum(n) FROM (
        SELECT item_id, count(*) AS n FROM main.copy WHERE archived_at IS NULL AND item_id IN (SELECT value FROM json_each(?)) GROUP BY item_id
        UNION ALL SELECT item_id, coalesce(sum(quantity), 0) FROM main.stock WHERE archived_at IS NULL AND item_id IN (SELECT value FROM json_each(?)) GROUP BY item_id)
        GROUP BY item_id''', (packed, packed))}
    wished = {r[0] for r in db.execute('SELECT DISTINCT item_id FROM main.wish WHERE archived_at IS NULL AND item_id IN (SELECT value FROM json_each(?))', (packed,))}
    return owned, wished


def catalogue_rows(db, ids):
    """`CatalogueItem` bodies for catalogue item ids, in the order given (an id the catalogue does not hold live is left out)."""
    packed = json.dumps(sorted(set(ids)))
    found = {r['id']: r for r in db.execute('''SELECT i.id, i.name, i.year, c.name AS category, t.name AS theme FROM catalogue.item i
        LEFT JOIN catalogue.part_category c ON c.id=i.category_id LEFT JOIN catalogue.theme t ON t.id=i.theme_id
        WHERE i.retired_at IS NULL AND i.id IN (SELECT value FROM json_each(?))''', (packed,))}
    owned, wished = owned_counts(db, found)
    book = bodies(db, items=found)
    return [{'item': book.item(i), 'name': found[i]['name'], 'year': found[i]['year'], 'owned': owned.get(i, 0),
             'wished': i in wished, 'category': found[i]['category'], 'theme': found[i]['theme']} for i in ids if i in found]


def _escape(text):
    return text.strip().lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _text_hits(db, kind, query):
    """Catalogue ids a text means: the number (born key, search index over every linked number, confirmed BrickLink links), then words
    by prefix in names (`catalogue.item_fts`) and anywhere in a name. Capped; order is the caller's."""
    found = [hit['item_id'] for hit in items_core.find(db, kind, query, limit=CAP)]
    tokens = re.findall(r'[^\W_]+', query.lower())
    if tokens:
        match = ' '.join(f'"{t}"*' for t in tokens)
        sql, args = 'SELECT item_id FROM catalogue.item_fts WHERE item_fts MATCH ?', [match]
        if kind:
            sql, args = sql + ' AND kind=?', args + [kind]
        found += [r[0] for r in db.execute(sql + ' ORDER BY rank LIMIT ?', (*args, CAP))]
        clause = ' AND '.join("lower(name) LIKE ? ESCAPE '\\'" for _ in tokens)
        found += [r[0] for r in db.execute(f"SELECT id FROM catalogue.item WHERE retired_at IS NULL{' AND kind=?' if kind else ''} AND {clause} LIMIT ?",
                                           ([kind] if kind else []) + ['%' + _escape(t) + '%' for t in tokens] + [CAP])]
    return list(dict.fromkeys(found))


def _cursor(signature, after):
    return base64.urlsafe_b64encode(json.dumps({'s': signature, 'after': after}).encode()).decode().rstrip('=')


def _after(cursor, signature):
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        if decoded['s'] != signature or not isinstance(decoded['after'], list) or len(decoded['after']) != 2:
            raise ValueError
        return decoded['after']
    except (ValueError, TypeError, KeyError):
        raise errors.BadRequest('Invalid cursor') from None


@route('/catalogue/items')
@reading
def get_catalogue_items(db):
    args = arguments()
    _require(db)
    kind, query = args.get('kind') or None, (args.get('q') or '').strip()
    sort, direction = args.get('sort', 'number'), args.get('direction', 'asc')
    if kind is not None and kind not in lookup.KINDS:
        raise errors.ValidationFailed('kind is one of ' + ', '.join(lookup.KINDS))
    if sort not in ('number', 'name') or direction not in ('asc', 'desc'):
        raise errors.UnknownFilter('The catalogue sorts by number or name')
    try:
        limit = int(args.get('limit', 50))
        if not 1 <= limit <= 200:
            raise ValueError
    except ValueError:
        raise errors.BadRequest('Limit must be between 1 and 200') from None
    signature = json.dumps([kind, query, sort, direction])
    if query:
        ids = _text_hits(db, kind, query)
        keys = {r['id']: r for r in db.execute('SELECT id, born_key, name_key FROM catalogue.item WHERE retired_at IS NULL AND id IN (SELECT value FROM json_each(?))',
                                               (json.dumps(sorted(ids)),))}
        ids = [i for i in ids if i in keys]
        pick = (lambda i: natural(keys[i]['born_key'])) if sort == 'number' else (lambda i: keys[i]['name_key'])
        ordered = sorted(ids, key=lambda i: (pick(i), i), reverse=direction == 'desc')
        start = 0
        if args.get('cursor'):
            anchor = _after(args['cursor'], signature)[1]
            start = next((n + 1 for n, i in enumerate(ordered) if i == anchor), None)
            if start is None:
                raise errors.BadRequest('Invalid cursor')
        chosen, total = ordered[start:start + limit], len(ordered)
        more = start + limit < total
        after = [None, chosen[-1]] if more else None
    else:
        column = 'born_key' if sort == 'number' else 'name_key'
        compare, order = ('>', 'ASC') if direction == 'asc' else ('<', 'DESC')
        where, params = 'retired_at IS NULL', []
        if kind:
            where, params = where + ' AND kind=?', [kind]
        total = db.execute(f'SELECT count(*) FROM catalogue.item WHERE {where}', params).fetchone()[0]
        if args.get('cursor'):
            key, anchor = _after(args['cursor'], signature)
            where += f' AND ({column}, id) {compare} (?, ?)'
            params += [key, anchor]
        rows = db.execute(f'SELECT id, {column} AS k FROM catalogue.item WHERE {where} ORDER BY {column} {order}, id {order} LIMIT ?', (*params, limit + 1)).fetchall()
        chosen = [r['id'] for r in rows[:limit]]
        after = [rows[limit - 1]['k'], rows[limit - 1]['id']] if len(rows) > limit else None
    data = catalogue_rows(db, chosen)
    return respond(data, page={'next_cursor': _cursor(signature, after) if after else None, 'limit': limit, 'total': total})


@route('/catalogue/items/<id>')
@reading
def get_catalogue_items_by_id(db, id):
    arguments()
    _require(db)
    found = catalogue_rows(db, [integer_id(id, 'catalogue entry')])
    if not found:
        raise errors.NotFound('No such catalogue entry')
    return respond(found[0])


# ---------- the items the collection knows ----------

@route('/items')
@reading
def get_items(db):
    args = arguments()
    kind = args.get('kind') or None
    if kind is not None and kind not in lookup.KINDS:
        raise errors.ValidationFailed('kind is one of ' + ', '.join(lookup.KINDS))
    rows = db.execute('''SELECT id, kind, name, year, theme_name, category_name, born_key FROM main.item WHERE merged_into IS NULL'''
                      + (' AND kind=?' if kind else ''), (kind,) if kind else ()).fetchall()
    owned, _ = owned_counts(db, [r['id'] for r in rows])
    # A text is also matched against the BrickLink numbers, which are in the bodies; without one only the page needs them.
    book = bodies(db, items=[r['id'] for r in rows]) if args.get('q') else None
    records = [record(r['id'], r['born_key'] or '', kind=r['kind'], name=r['name'], year=r['year'], theme=r['theme_name'] or '', category=r['category_name'] or '',
                      owned=owned.get(r['id'], 0) > 0, also=also(book.item(r['id'])) if book else '', _id=r['id']) for r in rows]
    return page(records, args, build=lambda chosen: [bodies(db, items=[r['_id'] for r in chosen]).item(r['_id']) for r in chosen])
