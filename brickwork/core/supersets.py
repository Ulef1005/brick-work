"""Found in (#40): one colour, owned holders first, then the scoring index's catalogue postings.

Catalogue counts name distinct items. Owned copies replace their catalogue row in the mixed list;
multiple owned copies remain separate. Paging counts those displayed rows, without capping the total.
"""
from . import collection, errors, items, pictures, set_scoring
from ..store4.connect import has_catalogue


def counts(index, item_id, color_id):
    key = set_scoring.key_of(item_id, color_id)
    return dict(sets=len(index.posting.get(key, ((), ()))[0]),
                minifigures=len(index.figure_posting.get(key, ((), ()))[0]))


def found_in(db, item_id, color_id, *, type='all', search='', sort='newest', limit=15, offset=0):
    """A bounded page plus true counts. No network, collection mutation, or acquired inventories in catalogue results."""
    label = items.label(db, item_id)
    if label is None or label.kind != 'part':
        raise errors.NotFound('No such part')
    if type not in ('all', 'sets', 'minifigures') or sort not in ('newest', 'oldest', 'name', 'number'):
        raise errors.ValidationFailed('Choose a listed type and sort')
    if not 1 <= limit <= 100 or offset < 0:
        raise errors.ValidationFailed('Choose a page of 1 to 100 items')
    colour = pictures.colour_row(db, color_id)
    if colour is None:
        raise errors.NotFound('No such colour')
    # Keep Used in sets unchanged. This read adds storage and loose figure holders.
    owned = [dict(r, group='owned', owned=True, stock_id=None, color_id=None) for r in collection._used_in(db, item_id, color_id, 'part')]
    storage = {r['id']: r['storage_name'] for r in db.execute('''SELECT c.id,s.name AS storage_name FROM main.copy c
        LEFT JOIN main.storage s ON s.id=c.storage_id WHERE c.archived_at IS NULL''')}
    for r in owned:
        r['storage_name'] = storage.get(r['copy_id'])
    for r in db.execute('''SELECT s.id AS stock_id,s.item_id,sum(p.quantity) AS quantity,t.name AS storage_name
        FROM main.stock_part p JOIN main.stock s ON s.id=p.stock_id LEFT JOIN main.storage t ON t.id=s.storage_id
        WHERE p.item_id=? AND p.color_id=? AND p.is_spare=0 AND p.retired_at IS NULL
        AND s.kind='minifigure' AND s.archived_at IS NULL AND s.quantity>0 GROUP BY s.id ORDER BY s.created_at,s.id''', (item_id, color_id)):
        owned.append(dict(r, copy_id=None, label='loose', color_id=None, group='owned', owned=True))
    available = has_catalogue(db)
    totals = dict(sets=0, minifigures=0)
    catalogue = []
    unmatched = False
    if available:
        index, _ = set_scoring.index_for(db)
        totals = counts(index, item_id, color_id)
        key = set_scoring.key_of(item_id, color_id)
        positions, amounts = index.posting.get(key, ((), ()))
        catalogue += [dict(item_id=index.set_item[p], quantity=q) for p, q in zip(positions, amounts)]
        figures, amounts = index.figure_posting.get(key, ((), ()))
        catalogue += [dict(item_id=i, quantity=q) for i, q in zip(figures, amounts)]
        # An unknown/no-colour posting is not evidence for any named colour.
        unmatched = not catalogue and any(set_scoring.key_of(item_id, c) in posting
            for posting in (index.posting, index.figure_posting) for c in (None, 1, 2))
    owned_ids = {r['item_id'] for r in owned}
    rows = owned + [dict(r, group='catalogue', owned=False, copy_id=None, stock_id=None, label=None, storage_name=None)
                    for r in catalogue if r['item_id'] not in owned_ids]
    ids = collection._in(r['item_id'] for r in rows)
    facts = {}
    for store in ('catalogue', 'main') if available else ('main',):
        if store == 'catalogue':
            sql = '''SELECT i.id,i.year,t.name AS theme FROM catalogue.item i LEFT JOIN catalogue.theme t ON t.id=i.theme_id'''
        else:
            sql = 'SELECT id,year,theme_name AS theme FROM main.item'
        for r in db.execute(sql + ' WHERE ' + ('i.' if store == 'catalogue' else '') + 'id IN (SELECT value FROM json_each(?))', (ids,)):
            facts[r['id']] = dict(r)
    wanted = {r[0] for r in db.execute('SELECT item_id FROM main.wish WHERE archived_at IS NULL')}
    rows = collection.decorate(db, rows)
    for r in rows:
        r.update(facts.get(r['item_id'], {}))
        r['on_wishlist'] = r['item_id'] in wanted
        r['type_word'] = 'Set' if r['kind'] == 'set' else 'Minifigure'
    query = search.strip().casefold()
    rows = [r for r in rows if (type == 'all' or r['kind'] == {'sets': 'set', 'minifigures': 'minifigure'}[type])
            and (not query or query in ' '.join(str(r.get(k) or '') for k in ('number_text', 'also', 'name', 'theme')).casefold())]
    def key(r):
        tail = ((-(r.get('year') or 0) if sort == 'newest' else r.get('year') or 9999) if sort in ('newest', 'oldest')
                else str(r.get('name') if sort == 'name' else r.get('number_text') or '').casefold())
        return (r['group'] != 'owned', tail, r['item_id'], r.get('copy_id') or r.get('stock_id') or '')
    rows.sort(key=key)
    return dict(catalogue=available, colour_unmatched=unmatched, counts=totals, owned_count=sum(r['owned'] for r in rows),
                total=len(rows), limit=limit, offset=offset, results=rows[offset:offset + limit])
