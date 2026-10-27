"""What an item has (M.11b, issue #113): `/items/{id}/detail`, `inventory`, `used-in`, `colors`, `images`, `links`, `provider-status`,
`GET /links` and the image bytes.

All of them name an item by its Brick Work id (a merged id is `307` to its survivor, `items.live`), and every item or colour they mention
carries the design-7 body. A part list is the catalogue's latest list for the item (design 4.1), else the newest acquired one (4.2)."""
import json
import mimetypes

from flask import send_file

from ..core import collection, errors, workbench
from ..core.media import media_root
from ..store4 import lookup
from ..store4.connect import has_catalogue
from . import route
from .catalogue import owned_counts
from .copies import gap_bodies, match_bodies
from .items import live
from .prices import current_body, current_rows
from .read import also, arguments, bodies, key_text, page, reading, record, respond
from .shapes import copy_bodies, stock_bodies, wish_bodies, wish_rows


def number_of(body):
    """The sort key and search number of an item body: the Rebrickable key, else the preferred BrickLink number."""
    if body is None:
        return ''
    return (body['rebrickable'] or {}).get('key') or next((l['no'] for l in body['bricklink'] if l['preferred']), '') or ''


def item_row(db, item_id):
    """`(kind, store)` of an item the answer is about; the id came from `live`, so a row exists in one file."""
    found = lookup.item_row(db, item_id)
    return found[1]['kind'], found[0]


# ---------- the part list ----------

def inventory_lines(db, item_id):
    """`[InventoryLine]` of an item's reference list: the catalogue's latest version (design 4.1), else the newest fetched one (4.2).
    A spare line shows as `extra_quantity` beside the required one of the same part and colour."""
    lines, figures, source = {}, [], None
    inventory = db.execute('SELECT id FROM catalogue.inventory WHERE item_id=? AND is_latest=1 AND retired_at IS NULL', (item_id,)).fetchone() if has_catalogue(db) else None
    if inventory:
        source = 'rebrickable'
        parts = db.execute('SELECT item_id, color_id, is_spare, quantity FROM catalogue.inventory_part WHERE inventory_id=?', (inventory[0],))
        figs = db.execute('SELECT item_id, quantity FROM catalogue.inventory_figure WHERE inventory_id=?', (inventory[0],))
    else:
        fetched = db.execute('SELECT id, source FROM main.fetched_inventory WHERE item_id=? AND is_latest=1 ORDER BY fetched_at DESC, id DESC', (item_id,)).fetchone()
        if not fetched:
            return []
        source = fetched['source']
        parts = db.execute('SELECT item_id, color_id, is_spare, quantity FROM main.fetched_inventory_part WHERE fetched_inventory_id=?', (fetched['id'],))
        figs = db.execute('SELECT item_id, quantity FROM main.fetched_inventory_figure WHERE fetched_inventory_id=?', (fetched['id'],))
    for r in parts:
        line = lines.setdefault((r['item_id'], r['color_id']), {'quantity': 0, 'extra_quantity': 0})
        line['extra_quantity' if r['is_spare'] else 'quantity'] += r['quantity']
    for r in figs:
        figures.append(((r['item_id'], None), {'quantity': r['quantity'], 'extra_quantity': 0}))
    ordered = [*sorted(lines.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)), *sorted(figures)]
    book = bodies(db, items=[child for (child, _), _ in ordered], colors=[colour for (_, colour), _ in ordered])
    out = []
    for (child, colour), line in ordered:
        body = book.item(child)
        out.append({'child': body, 'name': body['name'], 'color': book.color(colour), 'quantity': line['quantity'], 'extra_quantity': line['extra_quantity'],
                    'source': source})
    return out


@route('/items/<id>/inventory')
@reading
def get_items_by_id_inventory(db, id):
    args = arguments()
    item_id = live(db, id)
    kind, _ = item_row(db, item_id)
    lines = inventory_lines(db, item_id) if kind in ('set', 'minifigure') else []
    records = [record(n, number_of(l['child']), also=also(l['child']), name=l['name'], colour=(l['color'] or {}).get('name', ''), index=n, _body=l)
               for n, l in enumerate(lines)]
    return page(records, args, default_sort='index')


# ---------- where it is used ----------

def used_in_rows(db, item_id, kind):
    """`[UsedIn]` of a part (its non-spare lines in the live copies, figure components included) or of a figure (its figure lines)."""
    if kind == 'minifigure':
        found = db.execute('''SELECT c.id AS copy_id, c.item_id AS set_id, sum(f.quantity) AS quantity, sum(f.missing) AS missing, NULL AS color_id
            FROM main.copy_figure f JOIN main.copy c ON c.id=f.copy_id WHERE f.item_id=? AND f.retired_at IS NULL AND c.archived_at IS NULL
            GROUP BY c.id ORDER BY c.item_id, c.created_at, c.id''', (item_id,))
    elif kind == 'part':
        found = db.execute('''SELECT c.id AS copy_id, c.item_id AS set_id, sum(p.quantity) AS quantity, sum(p.missing) AS missing,
            CASE WHEN count(DISTINCT p.color_id)=1 THEN min(p.color_id) END AS color_id
            FROM main.copy_part p JOIN main.copy c ON c.id=p.copy_id WHERE p.item_id=? AND p.is_spare=0 AND p.retired_at IS NULL AND c.archived_at IS NULL
            GROUP BY c.id ORDER BY c.item_id, c.created_at, c.id''', (item_id,))
    else:
        return []
    found = found.fetchall()
    book = bodies(db, items=[r['set_id'] for r in found], colors=[r['color_id'] for r in found])
    return [{'copy_id': r['copy_id'], 'item': book.item(r['set_id']), 'name': book.item(r['set_id'])['name'], 'quantity': r['quantity'],
             'missing': r['missing'], 'color': book.color(r['color_id'])} for r in found]


@route('/items/<id>/used-in')
@reading
def get_items_by_id_used_in(db, id):
    args = arguments()
    item_id = live(db, id)
    kind, _ = item_row(db, item_id)
    records = [record(u['copy_id'], number_of(u['item']), also=also(u['item']), name=u['name'], colour=(u['color'] or {}).get('name', ''), _body=u)
               for u in used_in_rows(db, item_id, kind)]
    return page(records, args)


# ---------- colours ----------

def colours_known(db, item_id):
    """The Brick Work colour ids a part is known in: its part lists (every live version, acquired ones), what is held or wanted of it, its
    recorded prices and pictures, and the elements and picture links the catalogue lists for it."""
    found = set()
    queries = ['SELECT DISTINCT color_id FROM main.fetched_inventory_part WHERE item_id=:i', 'SELECT color_id FROM main.stock WHERE item_id=:i AND color_id IS NOT NULL',
               'SELECT color_id FROM main.stock_part WHERE item_id=:i AND retired_at IS NULL',
               'SELECT color_id FROM main.copy_part WHERE item_id=:i AND retired_at IS NULL',
               'SELECT color_id FROM main.wish WHERE item_id=:i AND color_id IS NOT NULL', 'SELECT color_id FROM main.price_observation WHERE item_id=:i AND color_id IS NOT NULL AND voided_at IS NULL',
               'SELECT color_id FROM main.picture WHERE item_id=:i AND color_id IS NOT NULL']
    if has_catalogue(db):
        queries += ['SELECT DISTINCT p.color_id FROM catalogue.inventory_part p JOIN catalogue.inventory v ON v.id=p.inventory_id WHERE p.item_id=:i AND v.retired_at IS NULL',
                    'SELECT color_id FROM catalogue.element WHERE item_id=:i', 'SELECT color_id FROM catalogue.picture_url WHERE item_id=:i']
    for sql in queries:
        found.update(r[0] for r in db.execute(sql, {'i': item_id}) if r[0] is not None)
    return sorted(found)


@route('/items/<id>/colors')
@reading
def get_items_by_id_colors(db, id):
    args = arguments()
    item_id = live(db, id)
    kind, _ = item_row(db, item_id)
    known = colours_known(db, item_id) if kind == 'part' else []
    book = bodies(db, colors=known)
    colours = [book.color(c) for c in known]
    records = [record(c['id'], str(c['id']), name=c['name'], colour=c['name'], _body=c) for c in colours if c]
    return page(records, args)


# ---------- pictures ----------

def image_bodies(db, item_id):
    pictures = db.execute('SELECT * FROM main.picture WHERE item_id=? ORDER BY fetched_at DESC, id DESC', (item_id,)).fetchall()
    photos = db.execute('SELECT * FROM main.photo WHERE item_id=? AND archived_at IS NULL ORDER BY created_at DESC, id DESC', (item_id,)).fetchall()
    book = bodies(db, items=[item_id], colors=[r['color_id'] for r in (*pictures, *photos)])
    out = []
    for r in pictures:
        out.append({'id': r['id'], 'item': book.item(item_id), 'color': book.color(r['color_id']), 'source': r['source'], 'kind': r['kind'], 'width': r['width'],
                    'height': r['height'], 'fetched_at': r['fetched_at'], 'copy_id': None, 'stock_id': None, 'caption': None,
                    'content_url': f"/api/v2/images/{r['id']}/content"})
    for r in photos:
        out.append({'id': r['id'], 'item': book.item(item_id), 'color': book.color(r['color_id']), 'source': 'own', 'kind': 'own', 'width': r['width'],
                    'height': r['height'], 'fetched_at': r['created_at'], 'copy_id': r['copy_id'], 'stock_id': r['stock_id'], 'caption': r['caption'],
                    'content_url': f"/api/v2/images/{r['id']}/content"})
    return out


@route('/items/<id>/images')
@reading
def get_items_by_id_images(db, id):
    args = arguments()
    item_id = live(db, id)
    records = [record(i['id'], '', index=n, _body=i) for n, i in enumerate(image_bodies(db, item_id))]
    return page(records, args, default_sort='index')


@route('/images/<id>/content')
@reading
def get_images_by_id_content(db, id):
    arguments()
    own = not id.isdigit()
    if (own and not (len(id) == 32 and all(c in '0123456789abcdef' for c in id))) or (not own and len(id) > 18):
        raise errors.NotFound('No such image')
    if own:
        row = db.execute('SELECT local_path FROM main.photo WHERE id=? AND archived_at IS NULL', (id,)).fetchone()
    else:
        row = db.execute('SELECT local_path FROM main.picture WHERE id=?', (int(id),)).fetchone()
    if row is None:
        raise errors.NotFound('No such image')
    root = media_root(db)
    target = (root / row[0]).resolve()
    if not target.is_relative_to(root / 'data/images') or not target.is_file():
        raise errors.NotFound('No such image')
    return send_file(target, mimetype=mimetypes.guess_type(target.name)[0] or 'application/octet-stream')


# ---------- links and provider status ----------

def link_bodies(db, rows):
    """`ItemLink` bodies of `item_link` rows: the provider's own type and number, the colour scope in the provider's space (BrickLink), and
    `color_scoped` / `brickwork_color_id` so a scope with no BrickLink colour never reads as "every colour" (as the item body)."""
    numbers = lookup.bricklink_colors(db, {r['color_id'] for r in rows})
    return [link_body(r, numbers) for r in rows]


def link_body(r, numbers):
    scoped = r['color_id'] is not None
    return {'provider': r['provider'], 'type': r['provider_kind'], 'no': r['provider_key'],
            'color_id': numbers[r['color_id']] if scoped and r['provider'] == 'bricklink' else None,
            'color_scoped': scoped, 'brickwork_color_id': r['color_id'], 'status': r['status'], 'method': r['method'], 'origin': r['origin'],
            'preferred': bool(r['preferred']), 'decided_at': r['decided_at']}


def status_body(r):
    try:
        evidence = json.loads(r['evidence_json']) if r['evidence_json'] else None
    except ValueError:
        evidence = None
    return {'provider': r['provider'], 'status': r['status'], 'reason': r['reason'], 'evidence': evidence, 'checked_at': r['checked_at']}


def links_of(db, item_id):
    """The `item_link` rows of an item from the file that holds it (a catalogue link was decided when its build finished)."""
    store = lookup.item_row(db, item_id)[0]
    when = 'decided_at' if store == 'main' else '(SELECT finished_at FROM catalogue.build b WHERE b.id=l.build_id) AS decided_at'
    return db.execute(f'SELECT l.*, {when} FROM {store}.item_link l WHERE l.item_id=? ORDER BY provider, preferred DESC, provider_kind, provider_key, color_key',
                      (item_id,)).fetchall()


@route('/items/<id>/links')
@reading
def get_items_by_id_links(db, id):
    arguments()
    return respond(link_bodies(db, links_of(db, live(db, id))))


@route('/items/<id>/provider-status')
@reading
def get_items_by_id_provider_status(db, id):
    arguments()
    item_id = live(db, id)
    rows = db.execute('SELECT * FROM main.item_provider_status WHERE item_id=? ORDER BY provider, reason', (item_id,)).fetchall()
    return respond([status_body(r) for r in rows])


@route('/links')
@reading
def get_links(db):
    args = arguments()
    status, provider, kind = args.get('status'), args.get('provider'), args.get('kind')
    if status is not None and status not in ('matched', 'inferred', 'manual', 'to_check'):
        raise errors.UnknownFilter('status is matched, inferred, manual or to_check')
    if kind is not None and kind not in lookup.KINDS:
        raise errors.ValidationFailed('kind is one of ' + ', '.join(lookup.KINDS))
    where, params = 'i.merged_into IS NULL' + (' AND i.kind=?' if kind else ''), [kind] if kind else []
    records = []
    link_where = where + (' AND l.status=?' if status else '') + (' AND l.provider=?' if provider else '')
    for r in db.execute(f'SELECT l.*, i.born_key FROM main.item_link l JOIN main.item i ON i.id=l.item_id WHERE {link_where} ORDER BY i.born_key, l.id',
                        (*params, *([status] if status else []), *([provider] if provider else []))):
        records.append(record(key_text('link', r['id']), r['born_key'] or '', row=('link', dict(r))))
    if status in (None, 'to_check'):
        status_where = where + (" AND s.status='to_check'" if status else '') + (' AND s.provider=?' if provider else '')
        for r in db.execute(f'SELECT s.*, i.born_key FROM main.item_provider_status s JOIN main.item i ON i.id=s.item_id WHERE {status_where} ORDER BY i.born_key, s.item_id',
                            (*params, *([provider] if provider else []))):
            records.append(record(key_text('status', r['item_id'], r['provider'], r['reason']), r['born_key'] or '', row=('status', dict(r))))

    def build(chosen):
        book = bodies(db, items=[rec['row'][1]['item_id'] for rec in chosen])
        numbers = lookup.bricklink_colors(db, {rec['row'][1]['color_id'] for rec in chosen if rec['row'][0] == 'link'})
        return [{'item': book.item(r['item_id']), 'link': link_body(r, numbers) if kind_of_row == 'link' else None,
                 'provider_status': status_body(r) if kind_of_row == 'status' else None} for kind_of_row, r in (rec['row'] for rec in chosen)]
    return page(records, args, build=build, applied=('status', 'kind', 'provider'))


# ---------- the detail ----------

def properties_body(db, item_id):
    found = collection.properties(db, [item_id]).get(item_id, {})
    keep = ('value', 'unit', 'source', 'fetched_at')
    return {key: dict({k: row[k] for k in keep}, alternatives=[{k: a[k] for k in keep} for a in row['alternatives']]) for key, row in found.items()}


def detail_body(db, item_id, kind):
    """`ItemDetail`: the item, its fetched properties, what the collection holds and wants of it, its prices, its reference part list and
    links, and (for a part or figure) the copies it is in, the gaps on it and the stock that could fill them."""
    owned, wished = owned_counts(db, [item_id])
    copies = copy_bodies(db, collection.instances(db, 'set', item_id=item_id)) if kind == 'set' else []
    stock = stock_bodies(db, collection.instances(db, kind, item_id=item_id, stock_only=True)) if kind != 'set' else []
    wishes = wish_bodies(db, wish_rows(db, 'WHERE w.item_id=? AND w.archived_at IS NULL', (item_id,)))
    links = links_of(db, item_id)
    own_copies = {r['id'] for r in db.execute('SELECT id FROM main.copy WHERE item_id=? AND archived_at IS NULL', (item_id,))}
    # Every gap of the copies and loose figures this item has a gap in (a copy's other gaps decide whether a match completes it).
    copy_ids, stock_ids = set(own_copies), set()
    copy_ids.update(r[0] for r in db.execute('''SELECT DISTINCT copy_id FROM main.copy_part WHERE item_id=? AND is_spare=0 AND retired_at IS NULL
                                                AND copy_figure_id IS NULL AND (missing>0 OR damaged>0)''', (item_id,)))
    copy_ids.update(r[0] for r in db.execute('SELECT DISTINCT copy_id FROM main.copy_figure WHERE item_id=? AND retired_at IS NULL AND missing>0', (item_id,)))
    stock_ids.update(r[0] for r in db.execute('SELECT DISTINCT stock_id FROM main.stock_part WHERE item_id=? AND is_spare=0 AND retired_at IS NULL AND missing>0', (item_id,)))
    around = workbench.gaps(db, only=(copy_ids, stock_ids)) if copy_ids or stock_ids else []
    mine = lambda g: g['item_id'] == item_id or g['copy_id'] in own_copies
    gaps = [g for g in around if mine(g)]
    matches = [m for m in workbench.matches(db, all_gaps=around) if mine(m)] if around else []
    prices = current_rows(db, item_id)
    book = bodies(db, items=[item_id, *(r['item_id'] for r in prices)], colors=[r['color_id'] for r in prices])
    return {'item': book.item(item_id), 'properties': properties_body(db, item_id), 'counts': {'owned': owned.get(item_id, 0), 'wished': item_id in wished},
            'copies': copies, 'stock': stock, 'wishes': wishes, 'prices': [current_body(book, r) for r in prices],
            'inventory': inventory_lines(db, item_id) if kind in ('set', 'minifigure') else [], 'links': link_bodies(db, links),
            'used_in': used_in_rows(db, item_id, kind),
            'gaps': gap_bodies(db, gaps), 'matches': match_bodies(db, matches)}


@route('/items/<id>/detail')
@reading
def get_items_by_id_detail(db, id):
    arguments()
    item_id = live(db, id)
    return respond(detail_body(db, item_id, item_row(db, item_id)[0]))


@route('/minifigures/<id>')
@reading
def get_minifigures_by_id(db, id):
    arguments()
    item_id = live(db, id)
    kind = item_row(db, item_id)[0]
    if kind != 'minifigure':
        raise errors.NotFound('No such minifigure')
    return respond(detail_body(db, item_id, kind))
