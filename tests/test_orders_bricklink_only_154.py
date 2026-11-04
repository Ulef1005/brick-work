"""Issue #154: an order line naming an item only BrickLink has (an instruction booklet, a BrickLink-only part) is placed on a local
BrickLink-born item when the loaded BrickLink item list (catalogue `bricklink_item`) names it, at import (by number and by exact name) and
when matched by hand, so the order can be reviewed. A key the list does not name still waits for hand matching. Invented data, no network."""
from contextlib import closing
import sqlite3

import pytest

from brickwork.core import orders
from brickwork.core.connect import connect
from tests.api2 import call, v2, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.app4 import client  # noqa: F401
from tests.test_bw_orders_storage import inventory, line_of

RED = 5                                                       # the BrickLink colour number of the world's red


def listed(pair, *entries):
    """BrickLink item list rows `(type, number, name)`; the offline fixture catalogue has none."""
    with sqlite3.connect(pair.with_name('catalogue.db')) as db:
        build = db.execute('SELECT max(id) FROM build').fetchone()[0]
        db.executemany('INSERT INTO bricklink_item(item_type,item_no,name,name_key,build_id) VALUES(?,?,?,?,?)',
                       [(t, n, name, name.lower(), build) for t, n, name in entries])


def local(db, letter, number):
    return db.execute("SELECT id,origin,kind,name FROM item WHERE born_provider='bricklink' AND born_namespace=? AND born_key=?", (letter, number)).fetchone()


def lines(db, order_id):
    return {r['raw_item_no'] or r['raw_name']: r for r in db.execute('SELECT * FROM order_line WHERE order_id=? ORDER BY line_no', (order_id,))}


EMAIL = ('* Batch #1 (submitted Dec 1, 2025 04:55)\n'
         "[Used] (Instructions) for Set 7946 King's Castle 7.5/10 (x1) ..... EUR 10.00 each = EUR 10.00\n"
         '[Used] Red Flag 2 x 2 Trapezoid Model Left Side (Sticker) - Set 70732 (x1) ..... EUR 0.333 each = EUR 0.333\n')


def test_an_email_places_a_bare_booklet_number_and_a_bricklink_only_part_on_new_local_items(world, coll, pair):
    listed(pair, ('I', '7946-1', "King's Castle"), ('P', '44676pb024L', 'Flag 2 x 2 Trapezoid Model Left Side (Sticker) - Set 70732'))
    coll.db.close()
    with closing(connect(pair)) as db:
        made = orders.import_document(db, 'email', EMAIL)
        assert (made['placed'], made['unplaced']) == (2, 0)
        booklet, flag = local(db, 'I', '7946-1'), local(db, 'P', '44676pb024L')
        assert tuple(booklet)[1:] == ('local', 'instructions', "King's Castle")
        assert tuple(flag)[1:] == ('local', 'part', 'Flag 2 x 2 Trapezoid Model Left Side (Sticker) - Set 70732')
        got = lines(db, made['order_id'])
        assert got['7946']['item_id'] == booklet['id'] and got['7946']['state'] == 'matched'
        flag_line = next(r for r in got.values() if r['item_id'] == flag['id'])
        assert flag_line['color_id'] == world.red and flag_line['state'] == 'matched'
        assert db.execute("SELECT status,method FROM item_link WHERE item_id=? AND provider='bricklink'", (flag['id'],)).fetchone()[:] == ('matched', 'bricklink_list')
        orders.phase(db, made['order_id'], made['document_id'], 'review')                 # nothing left unmatched: the review goes through


def test_an_xml_line_with_a_listed_number_is_placed_and_a_second_order_reuses_the_item(world, coll, pair):
    listed(pair, ('P', '45301pb037', 'Wedge 16 x 4 Triple Curved with Gold Panels Pattern'))
    coll.db.close()
    with closing(connect(pair)) as db:
        first = orders.import_document(db, 'xml', inventory(line_of('P', '45301pb037', colour=RED, qty=1)))
        second = orders.import_document(db, 'xml', inventory(line_of('P', '45301pb037', colour=RED, qty=2)))
        assert first['placed'] == second['placed'] == 1
        assert db.execute("SELECT count(*) FROM item WHERE born_provider='bricklink' AND born_key='45301pb037'").fetchone()[0] == 1


def test_a_key_the_list_does_not_name_still_waits_and_creates_nothing(world, coll, pair):
    coll.db.close()
    with closing(connect(pair)) as db:
        made = orders.import_document(db, 'xml', inventory(line_of('P', 'nowhere9', colour=RED, qty=1)))
        assert (made['placed'], made['unplaced']) == (0, 1)
        assert local(db, 'P', 'nowhere9') is None
        line = next(iter(lines(db, made['order_id']).values()))
        with pytest.raises(ValueError, match='Choose an identity'):
            orders.match(db, made['order_id'], line['id'], item_type='P', item_no='nowhere9', color_id=world.red)
        assert local(db, 'P', 'nowhere9') is None


def test_a_line_matched_by_hand_with_a_listed_number_gets_its_local_item_and_undo_keeps_the_item(world, coll, pair):
    coll.db.close()
    with closing(connect(pair)) as db:
        made = orders.import_document(db, 'xml', inventory(line_of('P', 'later1', colour=RED, qty=1)))
    listed(pair, ('P', 'later1', 'Listed after the import'))                              # the lists are loaded after the order came in
    with closing(connect(pair)) as db:
        line = next(iter(lines(db, made['order_id']).values()))
        with pytest.raises(ValueError, match='Match each unresolved line'):
            orders.phase(db, made['order_id'], made['document_id'], 'review')
        event = orders.match(db, made['order_id'], line['id'], item_type='P', item_no='later1', color_id=world.red)
        item = local(db, 'P', 'later1')
        assert item is not None and lines(db, made['order_id'])['later1']['item_id'] == item['id']
        orders.undo(db, event)
        assert lines(db, made['order_id'])['later1']['item_id'] is None
        assert local(db, 'P', 'later1') is not None, 'the item a match created stays, as the booklet entry does'


def test_a_refused_hand_match_creates_no_item(world, coll, pair):
    coll.db.close()
    with closing(connect(pair)) as db:
        made = orders.import_document(db, 'xml', inventory(line_of('P', 'later2', colour=RED, qty=1)))
        line = next(iter(lines(db, made['order_id']).values()))
    listed(pair, ('P', 'later2', 'Listed too'))
    with closing(connect(pair)) as db:
        db.execute("UPDATE order_document SET phase='reviewed' WHERE id=?", (made['document_id'],))   # not a draft: the match is refused
        db.commit()
        with pytest.raises(ValueError, match='Reopen this document'):
            orders.match(db, made['order_id'], line['id'], item_type='P', item_no='later2', color_id=world.red)
        assert local(db, 'P', 'later2') is None


def test_the_api_matches_a_line_by_a_bricklink_number_only_the_list_names(v2, world, pair):
    made = write(v2, '/orders/documents', 'post', dict(source='xml', text=inventory(line_of('P', 'apionly1', colour=RED, qty=1))), key=True)
    assert made.status_code == 200, made.text
    order = made.json['data']['order_id']
    line = call(v2, f'/orders/{order}').json['data']['lines'][0]
    assert line['unplaced'] is True
    refused = write(v2, f"/orders/{order}/lines/{line['id']}", 'patch', {'item': {'provider': 'bricklink', 'kind': 'part', 'key': 'apionly1'}, 'color': RED}, key=True)
    assert refused.status_code == 422, refused.text                                      # not listed yet: refused as before
    listed(pair, ('P', 'apionly1', 'Only on BrickLink'))
    matched = write(v2, f"/orders/{order}/lines/{line['id']}", 'patch', {'item': {'provider': 'bricklink', 'kind': 'part', 'key': 'apionly1'}, 'color': RED}, key=True)
    assert matched.status_code == 200, matched.text
    after = call(v2, f'/orders/{order}').json['data']['lines'][0]
    assert after['unplaced'] is False and after['item']['name'] == 'Only on BrickLink' and after['color']['id'] == world.red
    assert write(v2, f"/events/{matched.json['event_id']}/undo").status_code == 200
    assert call(v2, f'/orders/{order}').json['data']['lines'][0]['item'] is None


def test_a_number_an_item_holds_in_another_colour_scope_creates_no_second_identity(world, coll, pair):
    """Codex review: a colour-scoped link makes the inverse miss for another colour; the number is still held, so nothing is created."""
    from brickwork.core.transaction import transaction
    from brickwork.store4 import fetched
    listed(pair, ('P', 'scoped1', 'Held for red only'))
    coll.db.close()
    with closing(connect(pair)) as db:
        with transaction(db):
            fetched.add_item_link(db, world.brick, provider='bricklink', provider_kind='P', provider_key='scoped1', status='matched',
                                  method='external_ids', origin='shipped', color_id=world.red)
        made = orders.import_document(db, 'xml', inventory(line_of('P', 'scoped1', colour=1, qty=1)))   # BrickLink white
        assert made['placed'] == 0
        assert local(db, 'P', 'scoped1') is None


def test_the_api_never_falls_back_to_another_providers_number(v2, world, pair):
    """Codex review: a BrickLink key that names no item must not match the Rebrickable part that happens to carry that number."""
    made = write(v2, '/orders/documents', 'post', dict(source='xml', text=inventory(line_of('P', 'stray77', colour=RED, qty=1))), key=True)
    order = made.json['data']['order_id']
    line = call(v2, f'/orders/{order}').json['data']['lines'][0]
    refused = write(v2, f"/orders/{order}/lines/{line['id']}", 'patch', {'item': {'provider': 'bricklink', 'kind': 'part', 'key': '003402'}, 'color': RED}, key=True)
    assert refused.status_code == 422, refused.text                                      # 003402 is a Rebrickable number only
    assert call(v2, f'/orders/{order}').json['data']['lines'][0]['item'] is None


def test_a_bare_booklet_number_reuses_the_item_that_holds_its_bricklink_link(world, coll, pair):
    """Codex review: a booklet held by a link (another born key) is that item, not a second booklet."""
    from brickwork.core.transaction import transaction
    from brickwork.store4 import fetched
    listed(pair, ('I', '7946-1', "King's Castle"))
    coll.db.close()
    with closing(connect(pair)) as db:
        with transaction(db):
            other = fetched.create_local_item(db, kind='instructions', born_provider='bricklink', born_namespace='I', born_key='7946-1x',
                                              name='Kings Castle booklet', kind_source='bricklink')
            fetched.add_item_link(db, other, provider='bricklink', provider_kind='I', provider_key='7946-1', status='matched',
                                  method='external_ids', origin='shipped')
        made = orders.import_document(db, 'email', "* Batch #1 (submitted Dec 1, 2025 04:55)\n[Used] (Instructions) for Set 7946 King's Castle (x1) ..... EUR 10.00 each = EUR 10.00\n")
        assert made['placed'] == 1
        assert lines(db, made['order_id'])['7946']['item_id'] == other
        assert local(db, 'I', '7946-1') is None
