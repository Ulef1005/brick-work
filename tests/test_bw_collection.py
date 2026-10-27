"""The collection's writes on the 4.0 store (M.8d, issue #110): save, archive, restore, Undo, photos, captions, lots and the stock edit-merge.

Every request makes ONE receipt event (`collection:save`, `archive`, `restore`, `photo`, `caption`) holding the rows before and after; Undo is the
registered undoer of those events (`core.undo`) and refuses when a row changed since. Conditions and completeness are words, flags are rows of
`copy_flag` / `stock_flag` / `wish_flag`, a place is `place_id`. The workbench's Take and Give, the Matching module and the catalogue admin
actions that lived in the old file moved to `test_bw_collection_matching.py` (M.8e) and `test_bw_collection_colours.py` (M.8i). Invented data."""
from io import BytesIO
import json
import sqlite3

from bs4 import BeautifulSoup
from PIL import Image
import pytest

from brickwork.core import checker, collection, undo
from tests.app4 import app4, client, coll, csrf, pair, post, read, world  # noqa: F401 (fixtures)


def item_url(w, **query):
    from urllib.parse import urlencode
    return f'/collection/item/{w.keep}' + (f'?{urlencode(query)}' if query else '')


def row(coll, table, identifier):
    found = coll.db.execute(f'SELECT * FROM {table} WHERE id=?', (identifier,)).fetchone()
    return dict(found) if found else None


def events(db, field=None):
    return [dict(r) for r in db.execute('SELECT * FROM event WHERE entity_kind=? ' + ('AND field=? ' if field else '') + 'ORDER BY id', ('collection', field) if field else ('collection',))]


# ---------- a copy ----------

def test_edit_flags_manual_derived_archive_undo(world, coll, client):
    token = csrf(client)
    w = world
    old = row(coll, 'copy', w.copy_a)
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values=dict(condition='new', completeness='complete', storage_id='', flags=[w.tag], note='New note'))
    assert r.status_code == 200 and r.json['message'] == 'Saved', r.json
    now = row(coll, 'copy', w.copy_a)
    assert (now['condition'], now['completeness'], now['completeness_source'], now['storage_id'], now['note']) == ('new', 'complete', 'manual', None, 'New note')
    assert [x[0] for x in coll.db.execute('SELECT flag_id FROM copy_flag WHERE copy_id=?', (w.copy_a,))] == [w.tag]    # the "Set is checked" link went with the form
    event = coll.db.execute('SELECT * FROM event WHERE id=?', (r.json['event_id'],)).fetchone()
    assert (event['via'], event['entity_kind'], event['field']) == ('app', 'collection', 'save')
    assert [c['table'] for c in json.loads(event['new_value'])] == ['copy', 'copy_flag']
    assert post(client, token, 'undo', event_id=r.json['event_id']).json['message'] == 'Undone'
    assert row(coll, 'copy', w.copy_a) == old
    assert sorted(x[0] for x in coll.db.execute('SELECT flag_id FROM copy_flag WHERE copy_id=?', (w.copy_a,))) == sorted([w.tag, w.checked])
    # choosing derived: one line is missing, so the derived value is incomplete
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values=dict(completeness_source='derived', completeness='complete', flags=[w.checked]))
    assert r.status_code == 200
    assert tuple(coll.db.execute('SELECT completeness, completeness_source FROM copy WHERE id=?', (w.copy_a,)).fetchone()) == ('incomplete', 'derived')
    # saving the value a derived copy already has does not turn it into a manual one
    post(client, token, 'save', entity='copy', ids=[w.copy_a], values=dict(completeness='incomplete', note='again'))
    assert tuple(coll.db.execute('SELECT completeness, completeness_source FROM copy WHERE id=?', (w.copy_a,)).fetchone()) == ('incomplete', 'derived')
    archived = post(client, token, 'archive', entity='copy', ids=[w.copy_a], values={})
    assert archived.json['message'] == 'Set deleted'
    assert client.get(item_url(w, copy=w.copy_a)).status_code == 404
    assert post(client, token, 'undo', event_id=archived.json['event_id']).status_code == 200
    assert client.get(item_url(w, copy=w.copy_a)).status_code == 200
    assert coll.db.execute('SELECT count(*) FROM copy_part WHERE copy_id=?', (w.copy_a,)).fetchone()[0] > 0
    assert coll.db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_derived_completeness_follows_the_flag_and_the_check(world, coll, client):
    token = csrf(client)
    w = world
    coll.sql("UPDATE copy SET completeness_source='derived' WHERE id=?", (w.copy_b,))
    coll.sql('UPDATE copy_part SET missing=0 WHERE copy_id=?', (w.copy_a,))
    coll.sql("UPDATE copy SET completeness_source='derived' WHERE id=?", (w.copy_a,))
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values=dict(flags=[w.checked]))
    assert r.status_code == 200
    assert row(coll, 'copy', w.copy_a)['completeness'] == 'complete'                       # checked and nothing missing
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values=dict(flags=[]))
    assert row(coll, 'copy', w.copy_a)['completeness'] == 'incomplete'
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a, w.copy_b], values=dict(flags=[w.tag])).status_code == 400      # flags: one instance
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values=dict(flags=['nope'])).status_code == 400


def test_links_to_an_archived_flag_are_left_alone(world, coll, client):
    token = csrf(client)
    w = world
    old = coll.flag('old tag', 'tag')
    coll.tag('copy', w.copy_a, old)
    coll.sql("UPDATE flag SET archived_at='2026-10-01T00:00:00.000Z' WHERE id=?", (old,))
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values=dict(flags=[w.tag]))
    assert r.status_code == 200
    held = {x[0] for x in coll.db.execute('SELECT flag_id FROM copy_flag WHERE copy_id=?', (w.copy_a,))}
    assert held == {w.tag, old}                                                         # the form cannot show the archived flag, so it cannot drop it
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert {x[0] for x in coll.db.execute('SELECT flag_id FROM copy_flag WHERE copy_id=?', (w.copy_a,))} == {w.tag, w.checked, old}


def test_money_is_a_price_with_its_currency_both_or_neither(world, coll, client):
    token = csrf(client)
    w = world
    save = lambda **values: post(client, token, 'save', entity='copy', ids=[w.copy_a], values=values)       # noqa: E731
    r = save(purchase_price='15', purchase_currency='')
    assert r.status_code == 200
    assert tuple(coll.db.execute('SELECT purchase_price, purchase_currency FROM copy WHERE id=?', (w.copy_a,)).fetchone()) == ('15', 'EUR')     # the currency the row had
    r = save(purchase_price='', purchase_currency='EUR')                                                    # a cleared price takes its currency with it
    assert tuple(coll.db.execute('SELECT purchase_price, purchase_currency FROM copy WHERE id=?', (w.copy_a,)).fetchone()) == (None, None)
    assert save(purchase_currency='USD').status_code == 400                                                 # a currency alone needs a price
    assert save(purchase_price='-1').status_code == 400 and save(purchase_price='abc').status_code == 400
    assert save(purchase_price='9.50', purchase_currency='usd').status_code == 200
    assert tuple(coll.db.execute('SELECT purchase_price, purchase_currency FROM copy WHERE id=?', (w.copy_a,)).fetchone()) == ('9.50', 'USD')
    assert save(purchase_price='1', purchase_currency='EURO!').status_code == 400
    coll.setting('bricklink_currency', 'GBP')
    r = save(purchase_price='', purchase_currency='', current_value='3')
    assert tuple(coll.db.execute('SELECT current_value, current_value_currency FROM copy WHERE id=?', (w.copy_a,)).fetchone()) == ('3', 'GBP')     # the configured one


def test_validation_names_what_to_fix(world, coll, client):
    token = csrf(client)
    w = world
    for values, entity in ((dict(condition='damaged'), 'copy'), (dict(condition='mint'), 'copy'), (dict(storage_id='nope'), 'copy'), (dict(place_id='nope'), 'copy'),
                           (dict(completeness='C'), 'copy'), (dict(purchase_date='not a date'), 'copy'), (dict(completeness_source='x'), 'copy')):
        r = post(client, token, 'save', entity=entity, ids=[w.copy_a], values=values)
        assert r.status_code == 400, values
    assert post(client, token, 'save', entity='copy', ids=[], values=dict(note='x')).status_code == 400
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a, w.copy_a], values=dict(note='x')).status_code == 400
    assert post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'unknown': 'x'}).status_code == 400            # nothing to save
    assert post(client, token, 'save', entity='copy', ids=['missing'], values=dict(note='x')).json['message'] == 'Instance is unavailable'
    assert post(client, token, 'save', entity='nothing', ids=[w.copy_a], values=dict(note='x')).status_code == 400
    assert coll.db.execute("SELECT count(*) FROM event WHERE entity_kind='collection'").fetchone()[0] == 0


def test_archiving_a_copy_that_waits_for_a_bricklink_list_releases_it(world, coll, client):
    token = csrf(client)
    w = world
    job = coll.sql("INSERT INTO job(source,kind,item_id,state,via,created_at,updated_at) VALUES('bricklink','inventory',?,'queued','app','2026-10-27T00:00:00.000Z','2026-10-27T00:00:00.000Z')",
                   (w.keep,)).lastrowid
    coll.sql("UPDATE copy SET inventory_pending='bricklink', pending_job_id=? WHERE id=?", (job, w.copy_b))
    r = post(client, token, 'archive', entity='copy', ids=[w.copy_b], values={})
    assert r.status_code == 200
    gone = row(coll, 'copy', w.copy_b)
    assert gone['archived_at'] and gone['inventory_pending'] is None and gone['pending_job_id'] is None            # it no longer waits for a list
    assert coll.db.execute("SELECT count(*) FROM event WHERE entity_kind='copy' AND entity_id=? AND field='pending_cancel'", (w.copy_b,)).fetchone()[0] == 1


# ---------- a wish ----------

def test_wish_colour_quantity_and_conflict(world, coll, client):
    token = csrf(client)
    w = world
    coll.add_wish(w.plate, colour=w.red, quantity=1)
    page = client.get(f'/collection/wishes/{w.wish_part}')
    assert page.status_code == 200
    r = post(client, token, 'save', entity='wish', ids=[w.wish_part], values={'quantity': 7, 'max_price': '0.1200', 'condition': 'used'})
    assert r.status_code == 200, r.json
    saved = row(coll, 'wish', w.wish_part)
    assert (saved['quantity'], saved['max_price'], saved['max_price_currency'], saved['condition'], saved['color_id']) == (7, '0.1200', 'EUR', 'used', w.white)
    refused = post(client, token, 'save', entity='wish', ids=[w.wish_part], values={'color_id': w.red})
    assert refused.status_code == 400 and 'Another live wish' in refused.json['message']
    assert row(coll, 'wish', w.wish_part)['color_id'] == w.white
    assert post(client, token, 'save', entity='wish', ids=[w.wish_part], values={'quantity': 0}).status_code == 400
    assert post(client, token, 'save', entity='wish', ids=[w.wish_part], values={'qty_filled_manual': 'x'}).status_code == 400
    assert post(client, token, 'save', entity='wish', ids=[w.wish_part], values={'max_price_currency': 'USD'}).status_code == 200      # the price is there
    assert post(client, token, 'save', entity='wish', ids=[w.wish_part], values={'max_price': ''}).status_code == 200                # clearing it clears the currency
    cleared = row(coll, 'wish', w.wish_part)
    assert (cleared['max_price'], cleared['max_price_currency']) == (None, None)
    assert post(client, token, 'save', entity='wish', ids=[w.wish_part], values={'max_price_currency': 'USD'}).status_code == 400
    assert post(client, token, 'save', entity='wish', ids=[w.wish_set], values={'color_id': w.red}).status_code == 400              # only parts have a colour
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 400                                              # later saves block it


def test_a_wish_moves_to_another_list_and_back(world, coll, client):
    token = csrf(client)
    w = world
    coll.sql("INSERT INTO wishlist(id,name,created_at) VALUES('second','Second','2026-10-01T00:00:00.000Z')")
    r = post(client, token, 'save', entity='wish', ids=[w.wish_set], values={'wishlist_id': 'second'})
    assert r.status_code == 200 and row(coll, 'wish', w.wish_set)['wishlist_id'] == 'second'
    assert post(client, token, 'save', entity='wish', ids=[w.wish_set], values={'wishlist_id': 'nope'}).status_code == 400
    assert post(client, token, 'save', entity='wish', ids=[w.wish_set], values={'list_id': 'default'}).status_code == 200            # the 3.3 name still works
    assert row(coll, 'wish', w.wish_set)['wishlist_id'] == 'default'


def test_wish_archive_restore_and_a_live_duplicate_is_a_conflict(world, coll, client):
    token = csrf(client)
    w = world
    db = coll.db
    archived = post(client, token, 'archive', entity='wish', ids=[w.wish_part], values={})
    assert archived.json['message'] == 'Archived' and row(coll, 'wish', w.wish_part)['archived_at']
    duplicate = coll.add_wish(w.plate, colour=w.white, quantity=1)
    with pytest.raises(ValueError, match='Another live wish'):
        collection.restore(db, 'wish', w.wish_part)
    assert post(client, token, 'undo', event_id=archived.json['event_id']).status_code == 400          # undoing the archive hits the same duplicate
    assert row(coll, 'wish', w.wish_part)['archived_at']
    coll.sql("UPDATE wish SET archived_at='2026-10-27T00:00:00.000Z' WHERE id=?", (duplicate,))
    event = collection.restore(db, 'wish', w.wish_part)
    assert row(coll, 'wish', w.wish_part)['archived_at'] is None and events(db, 'restore')[-1]['id'] == event
    collection.undo(db, event)
    assert row(coll, 'wish', w.wish_part)['archived_at']
    with pytest.raises(ValueError, match='already active'):
        collection.restore(db, 'wish', w.wish_set)
    with pytest.raises(ValueError, match='Unsupported'):
        collection.restore(db, 'item', 1)


def test_a_wish_for_an_unidentified_item_is_added_by_id_and_undone(world, coll, client):
    token = csrf(client)
    w = world
    figure = coll.local('minifigure', 'Mystery figure')
    r = post(client, token, 'wish', item_id=figure)
    assert r.status_code == 200 and r.json['message'] == 'Added to wishlist'
    wish = coll.db.execute('SELECT * FROM wish WHERE item_id=? AND archived_at IS NULL', (figure,)).fetchone()
    assert (wish['kind'], wish['wishlist_id'], wish['quantity'], wish['condition']) == ('minifigure', 'default', 1, 'any')
    assert post(client, token, 'wish', item_id=figure).status_code == 400                       # already there
    assert post(client, token, 'wish', item_id=w.brick).status_code == 400                      # a part needs its colour
    assert post(client, token, 'wish', item_id=999999).status_code == 400
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert coll.db.execute('SELECT archived_at FROM wish WHERE id=?', (wish['id'],)).fetchone()[0]
    assert post(client, token, 'wish', item_id=w.brick, color_id=w.red).status_code == 200


# ---------- loose stock, lots and places ----------

def test_lot_storage_bulk_and_places(world, coll, client):
    token = csrf(client)
    w = world
    coll.sql("INSERT INTO storage(id,name,created_at,archived_at) VALUES('old','Old place','2026-01-01T00:00:00.000Z','2026-02-01T00:00:00.000Z')")
    lot = client.get(f'/collection/lots/{w.bag}')
    assert lot.status_code == 200 and 'Bag' in lot.text
    soup = BeautifulSoup(client.get('/collection/P').text, 'html.parser')
    assert not soup.select('[data-bc-filter="storage"] option[value="old"]')
    assert post(client, token, 'save', entity='stock', ids=[w.stock_brick], values={'storage_id': 'old'}).status_code == 400
    r = post(client, token, 'save', entity='stock', ids=[w.stock_brick], values={'storage_id': '', 'condition': 'used', 'lot_id': w.bag})
    assert r.status_code == 200
    assert row(coll, 'stock', w.stock_brick)['storage_id'] is None
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert row(coll, 'stock', w.stock_brick)['storage_id'] == w.shelf
    r = post(client, token, 'save', entity='lot', ids=[w.bag], values={'name': 'Pile B', 'storage_id': ''})
    assert r.status_code == 200 and row(coll, 'lot', w.bag)['name'] == 'Pile B' and row(coll, 'lot', w.bag)['storage_id'] is None
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert row(coll, 'lot', w.bag)['name'] == 'Bag'
    assert post(client, token, 'save', entity='lot', ids=[w.bag], values={'name': ''}).status_code == 400
    places = collection.purchase_places(coll.db)
    shop = next(p for p in places if p['id'] == w.shop)
    assert shop['count'] == 1 and shop['totals'] == {'EUR': collection.Decimal('12.50')}


def test_giving_a_set_a_place_follows_the_storage_how_to(world, coll, client):
    """docs/how-to/storage.md, Give one thing a place / Give many things a place: the item page's Edit and the list's Select mode."""
    token = csrf(client)
    w = world
    shelf2 = coll.storage('Drawer 2', type='Drawer')
    soup = BeautifulSoup(client.get(item_url(w, copy=w.copy_b)).text, 'html.parser')
    form = soup.select_one('dialog#bc-edit form[data-bc-action=save]')
    assert json.loads(form['data-identity']) == {'entity': 'copy', 'ids': [w.copy_b]}
    assert {o['value'] for o in form.select('select[name=storage_id] option')} >= {'', w.shelf, shelf2}
    r = post(client, token, 'save', entity='copy', ids=[w.copy_b], values={'storage_id': shelf2})
    assert r.status_code == 200 and row(coll, 'copy', w.copy_b)['storage_id'] == shelf2
    assert 'Drawer 2' in client.get(item_url(w, copy=w.copy_b)).text
    # many at once: the bar's Change / Storage / Value / Save sends the same call for several ids
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a, w.copy_b], values={'storage_id': ''})
    assert r.status_code == 200
    assert {row(coll, 'copy', c)['storage_id'] for c in (w.copy_a, w.copy_b)} == {None}
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert (row(coll, 'copy', w.copy_a)['storage_id'], row(coll, 'copy', w.copy_b)['storage_id']) == (w.shelf, shelf2)
    r = post(client, token, 'lot', ids=[w.stock_brick_new, w.stock_plate], name='Pile C', note='Receipt note', storage_id=shelf2)
    assert r.status_code == 200 and r.json['message'] == 'Lot created', r.json
    lot = row(coll, 'stock', w.stock_plate)['lot_id']
    assert row(coll, 'lot', lot)['name'] == 'Pile C' and row(coll, 'lot', lot)['storage_id'] == shelf2 and row(coll, 'stock', w.stock_plate)['quantity'] == 2
    assert post(client, token, 'lot', ids=[w.stock_plate], name='X', storage_id='nope').status_code == 400
    assert post(client, token, 'lot', ids=[w.stock_plate], name=' ').status_code == 400
    assert post(client, token, 'lot', ids=[w.copy_a], name='A copy is not stock').status_code == 400


def test_new_lot_preserves_quantity_and_undo_archives_lot(world, coll, client):
    token = csrf(client)
    w = world
    r = post(client, token, 'lot', ids=[w.stock_brick_new], name='Pile C', note='Receipt note', storage_id=w.shelf)
    assert r.status_code == 200, r.json
    lot = row(coll, 'stock', w.stock_brick_new)['lot_id']
    assert row(coll, 'stock', w.stock_brick_new)['quantity'] == 2 and row(coll, 'lot', lot)['name'] == 'Pile C'
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert row(coll, 'stock', w.stock_brick_new)['lot_id'] is None and row(coll, 'lot', lot)['archived_at']


# ---------- the stock edit-merge ----------

@pytest.mark.parametrize('field', ['storage_id', 'lot_id', 'condition'])
def test_stock_edit_merges_and_undo_restores_exact_rows(world, coll, client, field):
    token = csrf(client)
    w = world
    destination = w.stock_brick                                    # 3001 red x3, used, in the bag on the shelf
    coll.sql('UPDATE stock SET note=? WHERE id=?', ('Destination note', destination))
    ends = {'storage_id': w.shelf, 'lot_id': w.bag, 'condition': 'used'}
    start = {'storage_id': None, 'lot_id': None, 'condition': 'new'}[field]
    source = coll.add_stock('part', w.brick, colour=w.red, quantity=2, condition='used' if field != 'condition' else 'new',
                            storage=w.shelf if field != 'storage_id' else None, lot=w.bag if field != 'lot_id' else None)
    assert row(coll, 'stock', source)[field] == start
    before = collection.snapshot(coll.db, 'stock', [destination, source])
    response = post(client, token, 'save', entity='stock', ids=[source], values={field: ends[field]})
    assert response.status_code == 200, response.json
    assert response.json['message'] == 'Merged into existing stock' and response.json['merged_ids'] == [destination]
    assert f'stock={destination}' in response.json['url'] and client.get(response.json['url']).status_code == 200
    rows = {r['id']: r for r in collection.snapshot(coll.db, 'stock', [destination, source])}
    assert rows[destination]['quantity'] == 5 and rows[destination]['note'] == 'Destination note' and not rows[destination]['archived_at']
    assert rows[source]['archived_at'] and rows[source]['quantity'] == 2 and rows[source][field] == ends[field]       # the source kept its edit, so its key names the target
    merge_events = {e['entity_id']: e for e in map(dict, coll.db.execute("SELECT * FROM event WHERE entity_kind='stock' AND field='merge'"))}
    assert set(merge_events) == {destination, source} and all(e['via'] == 'app' for e in merge_events.values())
    assert json.loads(merge_events[source]['old_value'])['archived_at'] is None and json.loads(merge_events[source]['new_value'])['archived_at']
    assert json.loads(merge_events[destination]['old_value'])['quantity'] == 3 and json.loads(merge_events[destination]['new_value'])['quantity'] == 5
    assert post(client, token, 'undo', event_id=response.json['event_id']).status_code == 200
    assert collection.snapshot(coll.db, 'stock', [destination, source]) == before
    assert coll.db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_a_loose_figure_never_merges_and_archiving_never_merges(world, coll, client):
    token = csrf(client)
    w = world
    figure = w.stock_figure
    other = coll.add_stock('minifigure', w.figure, quantity=4, condition='used', storage=w.shelf)
    before = collection.snapshot(coll.db, 'stock', [figure, other])
    r = post(client, token, 'save', entity='stock', ids=[figure], values={'storage_id': w.shelf})
    assert r.status_code == 200 and r.json['message'] == 'Saved' and 'merged_ids' not in r.json
    rows = collection.snapshot(coll.db, 'stock', [figure, other])
    assert all(not x['archived_at'] for x in rows) and {x['id']: x['quantity'] for x in rows} == {figure: 1, other: 4}
    assert collection.merge_result(coll.db, r.json['event_id']) == []
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert collection.snapshot(coll.db, 'stock', [figure, other]) == before
    a = post(client, token, 'archive', entity='stock', ids=[figure], values={})
    assert row(coll, 'stock', other)['quantity'] == 4 and row(coll, 'stock', figure)['archived_at']
    assert post(client, token, 'undo', event_id=a.json['event_id']).status_code == 200


@pytest.mark.parametrize('count', [100, 300])
def test_bulk_collisions_merge_in_a_fixed_number_of_queries_and_undo(world, coll, count):
    w = world
    db = coll.db
    item = coll.local('part', 'Bulk', born_key='bulk')
    ids = [coll.add_stock('part', item, colour=w.red, quantity=2, condition='new', lot=coll.lot(f'Lot {n}')) for n in range(count)]
    before = collection.snapshot(db, 'stock', ids)
    queries = []
    db.set_trace_callback(queries.append)
    try:
        event = collection.save(db, 'stock', list(reversed(ids)), {'lot_id': None})
    finally:
        db.set_trace_callback(None)
    from itertools import groupby
    assert len([q for q, _ in groupby(queries)]) < 25
    rows = {r['id']: r for r in collection.snapshot(db, 'stock', ids)}
    live = [r for r in rows.values() if not r['archived_at']]
    assert len(live) == 1 and live[0]['quantity'] == 2 * count and live[0]['id'] == min(ids)           # the lowest id keeps the stock
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='stock' AND field='merge'").fetchone()[0] == count
    later = collection.save(db, 'stock', [live[0]['id']], {'note': 'Later'})                            # a later edit of the destination blocks Undo
    with pytest.raises(ValueError, match='undo the later save first'):
        collection.undo(db, event)
    collection.undo(db, later)
    collection.undo(db, event)
    assert collection.snapshot(db, 'stock', ids) == before


def test_merge_receipt_failure_rolls_back_destination_and_source(world, coll):
    w = world
    db = coll.db
    coll.sql("UPDATE stock SET condition='new' WHERE id=?", (w.stock_brick,))
    before = collection.snapshot(db, 'stock', [w.stock_brick, w.stock_brick_new])
    db.execute("CREATE TRIGGER reject_merge BEFORE INSERT ON event WHEN new.field='merge' BEGIN SELECT RAISE(ABORT,'merge receipt failed'); END")
    with pytest.raises(sqlite3.IntegrityError):
        collection.save(db, 'stock', [w.stock_brick], {'storage_id': None, 'lot_id': None})
    assert collection.snapshot(db, 'stock', [w.stock_brick, w.stock_brick_new]) == before


@pytest.mark.parametrize('missing,damaged,checks,expected', [
    ((2, 3), (1, 2), (1, 0), (5, 3, 1)),
    ((None, 3), (None, None), (0, 1), (3, None, 0)),
    ((None, None), (0, None), (None, 1), (None, 0, None)),
    ((0, 0), (None, 1), (1, 1), (0, 1, 1)),
])
def test_stock_merge_defects_and_checked_exact_undo(world, coll, missing, damaged, checks, expected):
    w = world
    db = coll.db
    destination, source = w.stock_brick_new, coll.add_stock('part', w.brick, colour=w.red, quantity=7, condition='used')
    # (destination first, source second): both new -> the source's edit to 'new' lands on the destination
    coll.sql("UPDATE stock SET condition='new' WHERE id=?", (destination,))
    for i, identifier in enumerate((destination, source)):
        coll.sql('UPDATE stock SET missing=?, damaged=?, checked=? WHERE id=?', (missing[i], damaged[i], checks[i], identifier))
    before = collection.snapshot(db, 'stock', [destination, source])
    event = collection.save(db, 'stock', [source], {'condition': 'new'})
    assert tuple(db.execute('SELECT missing,damaged,checked,quantity FROM stock WHERE id=?', (destination,)).fetchone()) == (*expected, 9)
    collection.undo(db, event)
    assert collection.snapshot(db, 'stock', [destination, source]) == before


def test_restoring_stock_over_a_live_line_is_a_conflict(world, coll):
    w = world
    db = coll.db
    event = collection.save(db, 'stock', [w.stock_brick_new], {}, archive=True)
    twin = coll.add_stock('part', w.brick, colour=w.red, quantity=1, condition='new')
    with pytest.raises(ValueError, match='Another live stock line'):
        collection.restore(db, 'stock', w.stock_brick_new)
    with pytest.raises(ValueError, match='undo the later save first|Another live'):
        collection.undo(db, event)
    coll.sql("UPDATE stock SET archived_at='2026-10-27T00:00:00.000Z' WHERE id=?", (twin,))
    collection.restore(db, 'stock', w.stock_brick_new)
    assert row(coll, 'stock', w.stock_brick_new)['archived_at'] is None


@pytest.mark.parametrize('kind', list(collection.TYPES))
def test_the_lists_and_batch_saves_use_a_fixed_number_of_queries(world, coll, kind):
    w = world
    db = coll.db

    def measured(call):
        queries = []
        db.set_trace_callback(queries.append)
        try:
            result = call()
        finally:
            db.set_trace_callback(None)
        return len(queries), result

    def grow(start, end):
        for n in range(start, end):
            item = coll.local('part', f'Cost {n}', born_key=f'cost{n}')
            coll.sql('INSERT INTO stock(id,kind,item_id,color_id,quantity,condition,created_at,updated_at) VALUES(?,?,?,?,1,?,?,?)',
                     (f'cost-{n}', 'part', item, w.red, 'used', coll.tick(), coll.tick()))
            coll.sql("INSERT INTO copy(id,item_id,inventory_source,inventory_digest,completeness_source,created_at,updated_at) VALUES(?,?,'migrated','d','derived',?,?)",
                     (f'copy-{n}', w.keep, coll.tick(), coll.tick()))
    grow(0, 100)
    small, _ = measured(lambda: collection.listing(db, kind))
    save_small, event = measured(lambda: collection.save(db, 'stock', [f'cost-{n}' for n in range(100)], {'storage_id': None}))
    collection.undo(db, event)
    copy_small, event = measured(lambda: collection.save(db, 'copy', [f'copy-{n}' for n in range(100)], {'condition': 'used'}))
    collection.undo(db, event)
    grow(100, 300)
    large, _ = measured(lambda: collection.listing(db, kind))
    save_large, _ = measured(lambda: collection.save(db, 'stock', [f'cost-{n}' for n in range(300)], {'storage_id': None}))
    copy_large, _ = measured(lambda: collection.save(db, 'copy', [f'copy-{n}' for n in range(300)], {'condition': 'used'}))
    assert large == small and large < 30
    assert save_large == save_small and save_large < 20
    assert copy_large == copy_small and copy_large < 20


# ---------- photos and captions ----------

def png(size=(4, 3)):
    out = BytesIO()
    Image.new('RGB', size, 'white').save(out, 'PNG')
    return out.getvalue()


def test_own_photo_caption_lightbox_undo(world, coll, client, pair):
    token = csrf(client)
    w = world
    r = client.post('/collection/save/photo', data={'csrf_token': token, 'entity': 'copy', 'identifier': w.copy_a, 'caption': 'At home', 'photo': (BytesIO(png()), 'home.png')})
    assert r.status_code == 200, r.json
    photo = dict(coll.db.execute('SELECT * FROM photo').fetchone())
    assert (photo['copy_id'], photo['stock_id'], photo['item_id'], photo['caption'], photo['taken_at']) == (w.copy_a, None, w.keep, 'At home', None)
    assert photo['local_path'] == f"data/images/own/{photo['id']}.jpg" and not photo['id'].isdigit()
    assert (pair.parent / photo['local_path']).is_file()
    html = client.get(item_url(w, copy=w.copy_a)).text
    assert 'At home' in html and 'bc-lightbox' in html and f'/manage/images/{photo["id"]}' in html
    panel = BeautifulSoup(html, 'html.parser').select_one('dialog#bc-edit')
    assert panel.select_one('.bc-own-photos form[data-bc-action=photo] [data-bc-photo-file]') and 'At home' in panel.select_one('.bc-own-photos').get_text()
    served = client.get(f'/manage/images/{photo["id"]}?w=320')
    assert served.status_code == 200 and served.data[:2] == b'\xff\xd8'
    c = post(client, token, 'caption', identifier=photo['id'], caption='Finished')
    assert c.status_code == 200 and row(coll, 'photo', photo['id'])['caption'] == 'Finished'
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 400            # the caption came later
    assert post(client, token, 'undo', event_id=c.json['event_id']).status_code == 200
    assert post(client, token, 'undo', event_id=r.json['event_id']).status_code == 200
    assert row(coll, 'photo', photo['id'])['archived_at']
    assert (pair.parent / photo['local_path']).is_file()                                          # the bytes are the user's: kept, the row archived
    assert client.get(f'/manage/images/{photo["id"]}').status_code == 404
    assert post(client, token, 'caption', identifier=photo['id'], caption='x').status_code == 400


def test_a_photo_of_loose_stock_and_its_refusals(world, coll, client, pair):
    token = csrf(client)
    w = world

    def upload(content, **values):
        return client.post('/collection/save/photo', data={'csrf_token': token, 'entity': 'stock', 'identifier': w.stock_brick, 'photo': (BytesIO(content), 'p.png'), **values})
    ok = upload(png((9, 9)))
    assert ok.status_code == 200
    photo = coll.db.execute('SELECT * FROM photo').fetchone()
    assert (photo['stock_id'], photo['copy_id'], photo['item_id'], photo['color_id']) == (w.stock_brick, None, w.brick, w.red)
    assert upload(b'not an image').status_code == 400
    assert upload(b'').status_code == 400
    assert client.post('/collection/save/photo', data={'csrf_token': token, 'entity': 'wish', 'identifier': w.wish_set, 'photo': (BytesIO(png()), 'p.png')}).status_code == 400
    assert coll.db.execute('SELECT count(*) FROM photo').fetchone()[0] == 1
    assert len(list((pair.parent / 'data/images/own').glob('*.jpg'))) == 1


def test_a_failed_photo_receipt_leaves_no_file_behind(world, coll, client, pair):
    token = csrf(client)
    w = world
    coll.db.execute("CREATE TRIGGER reject_photo BEFORE INSERT ON event WHEN new.field='photo' BEGIN SELECT RAISE(ABORT,'receipt failed'); END")
    r = client.post('/collection/save/photo', data={'csrf_token': token, 'entity': 'copy', 'identifier': w.copy_a, 'photo': (BytesIO(png()), 'p.png')})
    assert r.status_code == 400
    assert coll.db.execute('SELECT count(*) FROM photo').fetchone()[0] == 0
    assert list((pair.parent / 'data/images/own').glob('*.jpg')) == []


def test_the_image_route_serves_files_and_refuses_the_rest(world, coll, client, pair):
    w = world
    (pair.parent / 'data/images').mkdir(parents=True, exist_ok=True)
    (pair.parent / 'data/images/x.png').write_bytes(png())
    coll.sql("INSERT INTO picture(item_id,source,kind,local_path,fetched_at) VALUES(?,?,?,?,?)", (w.keep, 'rebrickable_dump', 'photo', 'data/images/x.png', '2026-10-27T00:00:00.000Z'))
    number = coll.db.execute('SELECT id FROM picture').fetchone()[0]
    assert client.get(f'/manage/images/{number}').status_code == 200
    assert client.get(f'/manage/images/{number}?w=320').status_code == 200
    assert client.get(f'/manage/images/{number}?w=999').status_code == 400
    assert client.get('/manage/images/9999').status_code == 404                  # no cached picture: a clean 404, not an error page (pictures return with M.8f)
    assert client.get('/manage/images/' + 'a' * 32).status_code == 404
    assert client.get('/manage/images/..%2Fx').status_code == 404
    coll.sql("UPDATE picture SET local_path='data/images/missing.png'")
    assert client.get(f'/manage/images/{number}').status_code == 404


def test_the_instruction_download_serves_the_pdf_of_the_file_row(world, coll, client, pair):
    w = world
    (pair.parent / 'data/instructions').mkdir(parents=True, exist_ok=True)
    (pair.parent / 'data/instructions/a.pdf').write_bytes(b'%PDF-1.4\nbooklet')
    coll.sql("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,?,?,?)", (w.keep, 'data/instructions/a.pdf', 'Booklet', '2026-10-27T00:00:00.000Z'))
    identifier = coll.db.execute('SELECT id FROM instruction_file').fetchone()[0]
    served = client.get(f'/manage/instructions/{identifier}/download')
    assert served.status_code == 200 and served.data.startswith(b'%PDF') and 'attachment' in served.headers['Content-Disposition']
    assert client.get('/manage/instructions/999/download').status_code == 404
    coll.sql("UPDATE instruction_file SET archived_at='2026-10-27T00:00:00.000Z'")
    assert client.get(f'/manage/instructions/{identifier}/download').status_code == 404


def test_the_photos_root_follows_the_media_path(world, coll, tmp_path, monkeypatch):
    w = world
    monkeypatch.setenv('BW_MEDIA_PATH', str(tmp_path / 'nas'))
    collection.photo(coll.db, tmp_path / 'nas', 'copy', w.copy_a, png(), 'In the cloud')
    photo = coll.db.execute('SELECT local_path FROM photo').fetchone()[0]
    assert (tmp_path / 'nas' / photo).is_file()


# ---------- the request itself ----------

def test_readonly_csrf_validation_and_receipt_rollback(world, coll, client, app4):
    token = csrf(client)
    w = world
    assert post(client, 'wrong', 'archive', entity='copy', ids=[w.copy_a]).status_code == 400
    app4.config['BW_READ_ONLY'] = True
    assert b'Read only' in client.get('/collection/P').data
    assert post(client, token, 'archive', entity='copy', ids=[w.copy_a]).status_code == 403
    app4.config['BW_READ_ONLY'] = False
    db = coll.db
    db.execute("CREATE TRIGGER reject_collection BEFORE INSERT ON event WHEN new.entity_kind='collection' BEGIN SELECT RAISE(ABORT,'receipt failed'); END")
    with pytest.raises(sqlite3.IntegrityError):
        collection.save(db, 'copy', [w.copy_a], {'note': 'Must roll back'})
    assert row(coll, 'copy', w.copy_a)['note'] == 'Flea market'


def test_take_and_give_are_the_workbenchs_and_refuse_an_incomplete_request(world, client):
    # M.8e: the workbench does them (test_bw_48c.py, test_bw_workbench.py); here only that the collection's route hands them over.
    token = csrf(client)
    for action in ('transfer', 'take'):
        r = post(client, token, action, source_id='x')
        assert r.status_code == 400 and r.json['message'].startswith('Nothing was saved')
    assert post(client, token, 'nothing').status_code == 404


def test_undo_is_one_call_for_every_receipt_and_a_second_undo_does_nothing(world, coll, client):
    token = csrf(client)
    w = world
    r = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'note': 'one'})
    assert post(client, token, 'undo', event_id=r.json['event_id']).json['message'] == 'Undone'
    again = post(client, token, 'undo', event_id=r.json['event_id'])
    assert again.status_code == 200 and row(coll, 'copy', w.copy_a)['note'] == 'Flea market'
    assert coll.db.execute('SELECT count(*) FROM event_undo').fetchone()[0] == 1
    assert post(client, token, 'undo', event_id=999999).status_code == 400
    assert post(client, token, 'undo', event_id='x').status_code == 400
    # an event without an undoer is refused, whatever page asks
    audit_id = coll.db.execute("INSERT INTO event(at,via,entity_kind,field,new_value) VALUES('2026-10-27T00:00:00.000Z','app','item','renamed','x')").lastrowid
    coll.db.commit()
    assert post(client, token, 'undo', event_id=audit_id).status_code == 400
    assert ('collection', 'photo') in undo.REGISTRY and ('collection', 'restore') in undo.REGISTRY


def test_the_edit_panel_holds_the_instances_and_the_photos_and_the_archive_form(world, client):
    w = world
    soup = BeautifulSoup(client.get(item_url(w, copy=w.copy_a)).text, 'html.parser')
    panel = soup.select_one('dialog#bc-edit')
    headings = [h.get_text() for h in panel.select('.bc-edit-section > h3')]
    assert any(h.startswith('Instances') for h in headings) and 'Own photos' in headings
    assert panel.select_one('form[data-bc-action=save]') and panel.select_one('.bc-own-photos form[data-bc-action=photo]')
    assert not soup.select_one('#bc-edit [name=completeness_source]') and soup.select_one('#bc-edit [name=completeness]')
    assert soup.select_one('#bc-edit [name=place_id]') and soup.select_one('#bc-edit [name=current_value]')
    archive = soup.select_one('#bc-delete form')
    assert archive['data-bc-action'] == 'archive' and json.loads(archive['data-identity']) == {'entity': 'copy', 'ids': [w.copy_a]}
    assert soup.select_one('#bc-delete [data-bw-close]').get_text() == 'Keep it'


def test_the_estimate_saves_with_its_currency_and_undoes(world, coll, client):
    token = csrf(client)
    w = world
    old = tuple(coll.db.execute('SELECT current_value,current_value_currency FROM copy WHERE id=?', (w.copy_a,)).fetchone())
    response = post(client, token, 'save', entity='copy', ids=[w.copy_a], values={'current_value': '0', 'current_value_currency': 'EUR'})
    assert response.status_code == 200
    assert coll.db.execute('SELECT via FROM event WHERE id=?', (response.json['event_id'],)).fetchone()[0] == 'app'
    assert row(coll, 'copy', w.copy_a)['current_value'] == '0'
    assert '€0.00' in BeautifulSoup(client.get(item_url(w, copy=w.copy_a)).text, 'html.parser').select_one('.bc-price-footer').get_text()
    assert post(client, token, 'undo', event_id=response.json['event_id']).status_code == 200
    assert tuple(coll.db.execute('SELECT current_value,current_value_currency FROM copy WHERE id=?', (w.copy_a,)).fetchone()) == old


def test_a_checker_event_can_be_undone_through_the_same_call(world, coll, client):
    token = csrf(client)
    w = world
    db = coll.db
    state = checker.view(db, w.copy_a)
    checker.write(db, w.copy_a, dict(action='start', operation='s1'))
    session = checker.session(db, w.copy_a)['id']
    part = next(r for r in state['rows'] if r['kind'] == 'part')
    checker.write(db, w.copy_a, dict(action='answer', operation='a1', session=session, token=part['token'], found=0))
    event = checker.session(db, w.copy_a)['undo'][-1]
    assert post(client, token, 'undo', event_id=event).status_code == 200
    assert db.execute('SELECT missing FROM copy_part WHERE id=?', (part['id'],)).fetchone()[0] == part['missing']
