"""Named wishlists on the 4.0 store (M.8g, issue #110): invariants, portable formats and transport receipts. Invented data.

The 3.3 upgrade tests (a wishlists table made on first open, a file with the foreign keys on, a receipt with no list) have no premise left:
a 4.0 file has the tables from `setup` or the migration, and its event log starts fresh. The Add page's wanted-list imports are in
test_bw_add.py."""
import csv
import io
import json
import sqlite3
import uuid
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
import pytest

from brickwork.core import collection, errors, wishlists
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)


@pytest.fixture
def store(coll):
    """The default list with two wishes: red 3001 x3 ('any', a note with markup, a maximum of 1.25 EUR) and set 1000-2 x2 (new)."""
    part = coll.add_wish(coll.item('parts', '3001'), colour=coll.colour('4'), quantity=3, condition='any', note='A & B < C', max_price='1.25', currency='EUR')
    kit = coll.add_wish(coll.item('sets', '1000-2'), quantity=2, condition='new')
    coll.part, coll.kit = part, kit
    return coll


def live(db, list_id):
    return [r[0] for r in db.execute('SELECT id FROM wish WHERE wishlist_id=? AND archived_at IS NULL ORDER BY id', (list_id,))]


def test_wish_ids_and_list_ids_are_uuids(store):
    target, _ = wishlists.save(store.db, data={'name': 'Gifts'})
    assert uuid.UUID(target).hex == target and uuid.UUID(store.part).hex == store.part
    assert [l['name'] for l in wishlists.listing(store.db)] == ['Gifts', 'Wishlist'] and 'default' in {l['id'] for l in wishlists.listing(store.db)}


def test_per_list_key_create_rename_archive_restore_and_undo(store):
    db = store.db
    target, event = wishlists.save(db, data={'name': 'Holiday', 'note': 'Gift'})
    assert wishlists.require(db, target)['name'] == 'Holiday'
    _, rename = wishlists.save(db, target, {'name': 'Winter'})
    collection.undo(db, rename)
    assert wishlists.require(db, target)['name'] == 'Holiday'
    copy_event = wishlists.transfer(db, [store.part, store.kit], target, copy=True)
    copied = live(db, target)
    snapshot = collection.snapshot(db, 'wish', copied)
    assert len(copied) == 2 and all(r['wishlist_id'] == target for r in snapshot) and set(copied).isdisjoint({store.part, store.kit})
    with pytest.raises(sqlite3.IntegrityError), db:
        db.execute("""INSERT INTO wish(id,wishlist_id,kind,item_id,color_id,added_at,updated_at) SELECT 'dup',?,kind,item_id,color_id,added_at,updated_at
                      FROM wish WHERE id=?""", (target, store.part))
    _, arch = wishlists.save(db, target, action='archive')
    assert not live(db, target)
    _, restore = wishlists.save(db, target, action='restore')
    assert live(db, target) == copied
    collection.undo(db, restore)
    collection.undo(db, arch)
    assert collection.snapshot(db, 'wish', copied) == snapshot
    collection.undo(db, copy_event)
    assert all(r['archived_at'] for r in collection.snapshot(db, 'wish', copied))
    collection.undo(db, event)
    assert db.execute('SELECT archived_at FROM wishlist WHERE id=?', (target,)).fetchone()[0]


def test_archive_preserves_previously_archived_wishes(store):
    target, _ = wishlists.save(store.db, data={'name': 'Other'})
    wishlists.transfer(store.db, [store.part, store.kit], target)
    collection.save(store.db, 'wish', [store.part], {}, archive=True)
    stamp = store.db.execute('SELECT archived_at FROM wish WHERE id=?', (store.part,)).fetchone()[0]
    wishlists.save(store.db, target, action='archive')
    wishlists.save(store.db, target, action='restore')
    assert store.db.execute('SELECT archived_at FROM wish WHERE id=?', (store.part,)).fetchone()[0] == stamp
    assert store.db.execute('SELECT archived_at FROM wish WHERE id=?', (store.kit,)).fetchone()[0] is None


def test_restoring_a_list_that_would_duplicate_a_live_wish_is_refused(store):
    target, _ = wishlists.save(store.db, data={'name': 'Other'})
    wishlists.transfer(store.db, [store.kit], target, copy=True)
    wishlists.save(store.db, target, action='archive')
    store.add_wish(store.item('sets', '1000-2'), wishlist=target)               # a live wish for the same item, put on the archived list by hand
    with pytest.raises(errors.Conflict):
        wishlists.save(store.db, target, action='restore')


def test_transfer_conflict_atomic_and_guarded_undo(store):
    db = store.db
    target, _ = wishlists.save(db, data={'name': 'Target'})
    event = wishlists.transfer(db, [store.part, store.kit], target)
    assert len(live(db, target)) == 2
    collection.undo(db, event)
    assert all(r['wishlist_id'] == 'default' for r in collection.snapshot(db, 'wish', [store.part, store.kit]))
    wishlists.transfer(db, [store.part], target, copy=True)
    before = collection.snapshot(db, 'wish', [store.part, store.kit])
    with pytest.raises(errors.Conflict):
        wishlists.transfer(db, [store.part, store.kit], target)
    assert collection.snapshot(db, 'wish', [store.part, store.kit]) == before
    event = wishlists.transfer(db, [store.kit], target)
    collection.save(db, 'wish', [store.kit], {'note': 'Later'})
    with pytest.raises(ValueError, match='later'):
        collection.undo(db, event)
    with pytest.raises(ValueError):
        wishlists.transfer(db, [store.kit, store.kit], target)
    for bad in ([], None, [1], ['nope'], [store.part] * 2):
        with pytest.raises(ValueError):
            wishlists.transfer(db, bad, target)


def test_creation_undo_refuses_later_wishes(store):
    target, event = wishlists.save(store.db, data={'name': 'Target'})
    wishlists.transfer(store.db, [store.part], target)
    with pytest.raises(ValueError, match='wishes first'):
        collection.undo(store.db, event)
    assert wishlists.require(store.db, target)


def test_undo_move_requires_live_source_list(store):
    target, _ = wishlists.save(store.db, data={'name': 'Other'})
    event = wishlists.transfer(store.db, [store.part], target)
    wishlists.save(store.db, 'default', action='archive')
    with pytest.raises(ValueError, match='destination wishlist'):
        collection.undo(store.db, event)
    assert store.db.execute('SELECT wishlist_id FROM wish WHERE id=?', (store.part,)).fetchone()[0] == target


def test_list_archive_receipt_failure_rolls_back_wishes(store):
    before = collection.snapshot(store.db, 'wish', [store.part, store.kit])
    store.sql("CREATE TRIGGER refuse_list_receipt BEFORE INSERT ON event WHEN new.entity_kind='collection' BEGIN SELECT RAISE(ABORT,'receipt refused'); END")
    with pytest.raises(sqlite3.IntegrityError):
        wishlists.save(store.db, 'default', action='archive')
    assert collection.snapshot(store.db, 'wish', [store.part, store.kit]) == before
    assert wishlists.require(store.db)['archived_at'] is None


def test_copy_retains_flags_and_undo_detaches_only_copied_flags(store):
    db = store.db
    target, _ = wishlists.save(db, data={'name': 'Copy'})
    gift = store.flag('Gift', 'tag')
    store.tag('wish', store.part, gift)
    event = wishlists.transfer(db, [store.part, store.kit], target, copy=True)
    flagged = {r[0]: r[1] for r in db.execute('SELECT wish_id,flag_id FROM wish_flag')}
    assert len(flagged) == 2 and set(flagged.values()) == {gift} and store.part in flagged
    new_part = next(w for w in flagged if w != store.part)
    assert db.execute('SELECT wishlist_id,kind FROM wish WHERE id=?', (new_part,)).fetchone()[:] == (target, 'part')
    collection.undo(db, event)
    assert [r[0] for r in db.execute('SELECT wish_id FROM wish_flag')] == [store.part]


def test_export_bricklink_structure_currency_and_entities(store, read):
    wishlists.save(store.db, 'default', {'bricklink_id': '123'})
    with read() as db:
        result = wishlists.export(db, 'default')
    assert not result['content'].startswith('<?xml')
    root = ET.fromstring(result['content'])
    assert root.tag == 'INVENTORY'
    part = root.find('ITEM')
    assert part.findtext('ITEMTYPE') == 'P' and part.findtext('ITEMID') == '3001'
    assert part.findtext('COLOR') == '5' and part.findtext('MINQTY') == '3'                  # BrickLink's red is 5, Rebrickable's 4
    assert part.findtext('REMARKS') == 'A & B < C'
    assert part.findtext('MAXPRICE') == '1.25' and part.find('CONDITION') is None
    assert part.findtext('NOTIFY') == 'N' and part.findtext('WANTEDLISTID') == '123'
    kit = root.findall('ITEM')[1]
    assert (kit.findtext('ITEMTYPE'), kit.findtext('ITEMID'), kit.findtext('CONDITION'), kit.find('COLOR')) == ('S', '1000-2', 'N', None)
    assert result['summary'] == dict(exported=2, omitted=[], notes=[]) and result['filename'] == 'wishlist.xml' and result['mimetype'] == 'application/xml'
    collection.save(store.db, 'wish', [store.part], {'max_price_currency': 'USD'})
    with read() as db:
        result = wishlists.export(db, 'all')
    assert ET.fromstring(result['content']).find('ITEM/MAXPRICE') is None
    assert result['summary']['notes'][0]['id'] == store.part and 'MAXPRICE omitted' in result['summary']['notes'][0]['reason']
    collection.save(store.db, 'wish', [store.part], {'max_price': '0', 'max_price_currency': 'EUR'})
    with read() as db:
        assert ET.fromstring(wishlists.export(db, 'all')['content']).find('ITEM/MAXPRICE') is None


def test_an_item_with_no_bricklink_number_is_left_out_and_listed(store, read):
    mystery = store.add_wish(store.local('part', 'Mystery plate'), colour=store.colour('4'))      # no number from any provider
    local = store.add_wish(store.local('set', 'BrickLink only', born_key='x-1'))                     # a BrickLink-born number is its own BrickLink number
    with read() as db:
        result = wishlists.export(db, 'all')
    ids = [i.findtext('ITEMID') for i in ET.fromstring(result['content']).findall('ITEM')]
    assert 'x-1' in ids and len(ids) == 3
    assert result['summary']['exported'] == 3 and result['summary']['omitted'] == [dict(id=mystery, item_no='Mystery plate', reason='No BrickLink number')]
    assert local


def test_a_colour_with_no_bricklink_colour_is_left_out_and_listed(store, read):
    store.sql("INSERT INTO color(id,origin,name,is_trans,born_provider,born_key,created_at,updated_at) VALUES(1000000001,'local','Odd',0,'bricklink','9999',?,?)",
                    ('2026-10-26T12:00:00.000Z', '2026-10-26T12:00:00.000Z'))
    wish = store.add_wish(store.item('parts', '3001'), colour=1000000001)
    with read() as db:
        result = wishlists.export(db, 'all')
    assert [(o['id'], o['reason']) for o in result['summary']['omitted']] == [(wish, 'No BrickLink colour')]


def test_rebrickable_translation_and_unmapped_summary(store, read):
    local_set = store.local('set', 'Local set', born_key='bl-only')
    unmapped = store.add_wish(local_set, quantity=5)
    with read() as db:
        sets = wishlists.export(db, 'all', format='rebrickable', kind='sets')
        parts = wishlists.export(db, 'all', format='rebrickable', kind='parts')
    assert list(csv.reader(io.StringIO(sets['content']))) == [['Set Number', 'Quantity'], ['1000-2', '2']]
    assert [(o['id'], o['reason']) for o in sets['summary']['omitted'] if o['id'] == unmapped] == [(unmapped, 'Missing or ambiguous Rebrickable mapping')]
    assert any(o['reason'] == 'Outside selected export kind' for o in sets['summary']['omitted'])
    assert list(csv.reader(io.StringIO(parts['content']))) == [['Part', 'Color', 'Quantity'], ['3001', '4', '3']]
    assert parts['filename'] == 'wishlist.csv' and parts['mimetype'] == 'text/csv'
    # A local item with one confirmed Rebrickable link is exported by it; with two it is ambiguous and left out.
    store.link(local_set, '9000-1', kind='S', provider='rebrickable')
    with read() as db:
        assert ['9000-1', '5'] in list(csv.reader(io.StringIO(wishlists.export(db, 'all', format='rebrickable', kind='sets')['content'])))
    store.link(local_set, '9000-2', kind='S', provider='rebrickable')
    with read() as db:
        assert ['9000-1', '5'] not in list(csv.reader(io.StringIO(wishlists.export(db, 'all', format='rebrickable', kind='sets')['content'])))
    with pytest.raises(ValueError):
        with read() as db:
            wishlists.export(db, 'all', format='pdf')
    with pytest.raises(ValueError):
        with read() as db:
            wishlists.export(db, 'no-such-list')


def test_archived_lists_and_wishes_are_never_exported(store, read):
    other, _ = wishlists.save(store.db, data={'name': 'Gone'})
    wishlists.transfer(store.db, [store.part], other)
    wishlists.save(store.db, other, action='archive')
    collection.save(store.db, 'wish', [store.kit], {}, archive=True)
    with read() as db:
        assert wishlists.export(db, 'all')['summary']['exported'] == 0
        with pytest.raises(ValueError):
            wishlists.export(db, other)


def test_query_counts_flat(store, read):
    def count():
        with read() as db:
            statements = []
            db.set_trace_callback(statements.append)
            wishlists.listing(db)
            wishlists.export(db)
            wishlists.export(db, format='rebrickable')
            db.set_trace_callback(None)
        return len(statements)
    baseline = count()
    for i in range(20):
        target, _ = wishlists.save(store.db, data={'name': str(i)})
        wishlists.transfer(store.db, [store.part, store.kit], target, copy=True)
    assert count() == baseline


@pytest.mark.parametrize('empty', [False, True])
def test_render_list_switcher_manage_detail_export_and_readonly(store, client, app4, empty):
    target, _ = wishlists.save(store.db, data={'name': 'Holiday'})
    if empty:
        store.sql("UPDATE wish SET archived_at='old'")
    response = client.get('/planning/wishlist')
    soup = BeautifulSoup(response.data, 'html.parser')
    assert not soup.select_one('[role=alert]'), response.text
    assert soup.select_one('nav[aria-label=Wishlists]') and 'Holiday' in soup.text
    assert soup.select_one('#bw-manage-wishlists') and soup.select_one('[data-wl-export]')
    selected = client.get('/planning/wishlist?list=' + target)
    assert not BeautifulSoup(selected.data, 'html.parser').select('[data-bp-row]')
    download = client.get('/planning/wishlists/all/export.xml?summary=true')
    assert download.status_code == 200 and 'summary' in download.json
    if not empty:
        detail = client.get('/collection/wishes/' + store.part)
        assert 'Move or copy to another list' in detail.text and 'Holiday' in detail.text  # frame 7b: quiet action, list sheet
    app4.config['BW_READ_ONLY'] = True
    readonly = client.get('/planning/wishlist')
    assert 'Manage lists' not in readonly.text and 'data-wl-export ' in readonly.text
    app4.config.pop('BW_READ_ONLY', None)


def test_list_filtered_rows_keep_prices_counts_and_labels(store, client):
    target, _ = wishlists.save(store.db, data={'name': 'Price watch'})
    wishlists.transfer(store.db, [store.kit], target, copy=True)
    chosen = live(store.db, target)[0]
    collection.save(store.db, 'wish', [chosen], {'max_price': '12.00', 'max_price_currency': 'EUR'})
    soup = BeautifulSoup(client.get('/planning/wishlist?list=' + target).data, 'html.parser')
    rows = soup.select('[data-bp-row]')
    assert len(rows) == 1 and json.loads(rows[0]['data-record'])['id'] == chosen
    assert soup.select_one('a[aria-current=page][href$="' + target + '"]')
    assert '€12.00' in rows[0].text and soup.select_one('[data-bp-pick=under]')
    assert any('Price watch' in r.text for r in BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser').select('[data-bp-row]'))
    assert client.get('/planning/wishlist?list=no-such-list').status_code == 200            # shown as an alert, not a crash


def test_archiving_selected_list_keeps_manage_and_undo_reachable(store, client):
    token = csrf(client)
    target, _ = wishlists.save(store.db, data={'name': 'Temporary'})
    archived = client.post('/planning/wishlists/archive', json={'csrf_token': token, 'id': target})
    assert archived.status_code == 200
    soup = BeautifulSoup(client.get('/planning/wishlist?list=' + target).data, 'html.parser')
    assert not soup.select_one('[role=alert]')
    assert soup.select_one('[data-wl-undo]') and soup.select_one('[data-wl-action=restore]')
    assert client.post('/planning/wishlists/undo', json={'csrf_token': token, 'event_id': archived.json['event_id']}).status_code == 200


def test_the_wishlist_routes_move_copy_save_and_export_with_text_ids(store, client):
    token = csrf(client)
    made = client.post('/planning/wishlists/save', json={'csrf_token': token, 'values': {'name': 'Gifts', 'bricklink_id': '555'}})
    assert made.status_code == 200 and made.json['event_id']
    target = store.db.execute("SELECT id FROM wishlist WHERE name='Gifts'").fetchone()[0]
    moved = client.post('/planning/wishlists/transfer', json={'csrf_token': token, 'ids': [store.part], 'list_id': target})
    assert moved.status_code == 200
    assert store.db.execute('SELECT wishlist_id FROM wish WHERE id=?', (store.part,)).fetchone()[0] == target
    copied = client.post('/planning/wishlists/transfer', json={'csrf_token': token, 'ids': [store.kit], 'list_id': target, 'copy': True})
    assert copied.status_code == 200 and copied.json['message'] == 'Copied'
    assert client.post('/planning/wishlists/transfer', json={'csrf_token': token, 'ids': [store.kit, store.kit], 'list_id': target}).status_code == 400
    assert client.post('/planning/wishlists/transfer', json={'csrf_token': token, 'ids': [1], 'list_id': target}).status_code == 400
    assert client.post('/planning/wishlists/undo', json={'csrf_token': token}).status_code == 400                     # no event named
    assert client.post('/planning/wishlists/nothing', json={'csrf_token': token}).status_code == 404
    xml = client.get(f'/planning/wishlists/{target}/export.xml')
    assert xml.status_code == 200 and 'attachment; filename=wishlist.xml' in xml.headers['Content-Disposition'] and b'<INVENTORY>' in xml.data
    assert b'<WANTEDLISTID>555</WANTEDLISTID>' in xml.data
    csv_export = client.get(f'/planning/wishlists/{target}/export.csv?kind=sets')
    assert csv_export.status_code == 200 and csv_export.mimetype == 'text/csv' and csv_export.get_data(as_text=True).splitlines()[0] == 'Set Number,Quantity'
    assert client.get('/planning/wishlists/all/export.pdf').status_code == 404
    assert client.get('/planning/wishlists/nope/export.xml').status_code == 400
    assert client.post('/planning/wishlists/save', json={'values': {'name': 'x'}}).status_code in (400, 403)
