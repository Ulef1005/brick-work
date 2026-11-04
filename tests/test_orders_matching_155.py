"""Issue #155: why a line is not placed (`unplaced_reason`), suggestions for names no item has exactly (a seller's note glued to the name, a name
BrickLink changed), an undone document that can be imported again, and the summary export without orders that have no saved lines.
Invented names shaped like the issue's examples; no network."""
from contextlib import closing, contextmanager
import json

import pytest

from brickwork.core import order_exports, orders
from brickwork.core.connect import connect
from tests.api2 import call, v2, write  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401
from tests.test_orders_bricklink_only_154 import RED, listed
from tests.test_bw_orders_storage import inventory, line_of

TILE = ('P', '3068b', 'Tile, Round 2 x 2')
SLOPE = ('P', '50950', 'Slope, Curved 4 x 1')
SLOPE_INVERTED = ('P', '13547', 'Slope, Curved, Inverted 4 x 1')
PLATE = ('P', '14418', 'Plate, Modified 2 x 2 x 2/3 with 2 Studs on Side - Hollow/Solid Bottom Tube')
FLAG = ('P', '2335', 'Flag 2 x 2 Square with Flat Edge with Crossed Cannons Pattern')
LISTED = (TILE, SLOPE, SLOPE_INVERTED, PLATE, FLAG)


def email(*names, condition='Used'):
    return '* Batch #1 (submitted Dec 1, 2025 04:55)\n' + ''.join(f'[{condition}] Red {name} (x2) ..... EUR 0.50 each = EUR 1.00\n' for name in names)


@contextmanager
def loaded(coll, pair, entries):
    """The BrickLink item list loaded, and a local BrickLink-born item for each listed name (so a suggestion has an item to offer)."""
    made = {key[1]: coll.local('part', key[2], born_key=key[1]) for key in entries}
    listed(pair, *entries)
    coll.db.close()
    with closing(connect(pair)) as db:
        yield db, made


@pytest.fixture
def listing(world, coll, pair):
    with loaded(coll, pair, LISTED) as opened:
        yield opened


def only(db, result):
    (row,) = orders.lines(db, result['order_id'])
    return row


def labels(row):
    return [s['label'] for s in json.loads(row['suggestions_json'])]


def test_a_sellers_note_glued_to_the_name_suggests_the_longest_listed_prefix_and_places_nothing(listing):
    db, made = listing
    result = orders.import_document(db, 'email', email('Tile, Round 2 x 2 micro scratches'))
    row = only(db, result)
    assert (result['placed'], result['unplaced']) == (0, 1) and row['item_id'] is None and row['state'] == 'by_hand'
    assert [s['item_id'] for s in json.loads(row['suggestions_json'])] == [made['3068b']]
    assert row['unplaced_reason'] == 'No item has exactly this name'


def test_a_prefix_that_names_another_part_is_only_a_suggestion_ranked_before_the_all_words_match(listing):
    db, made = listing
    result = orders.import_document(db, 'email', email('Slope, Curved 4 x 1 Inverted'))
    row = only(db, result)
    assert row['item_id'] is None and result['placed'] == 0                      # never the non-inverted part
    assert [s['item_id'] for s in json.loads(row['suggestions_json'])] == [made['50950'], made['13547']]     # prefix first, then the renamed part with all words


def test_a_renamed_item_is_suggested_when_the_line_holds_none_of_its_added_words(listing):
    db, made = listing
    lines = [only(db, orders.import_document(db, 'email', email(name)))
             for name in ('Slope, Curved Inverted 4 x 1',                                          # a comma BrickLink added
                          'Plate, Modified 2 x 2 x 2/3 with 2 Studs on Side',                      # words added at the end
                          'Flag 2 x 2 Square with Crossed Cannons Pattern')]                       # words added in the middle
    assert [[s['item_id'] for s in json.loads(r['suggestions_json'])] for r in lines] == [[made['13547']], [made['14418']], [made['2335']]]
    assert all(r['item_id'] is None for r in lines)


def test_suggestions_are_ranked_prefix_then_all_words_nearest_first(world, coll, pair):
    entries = (('P', 'b1', 'Brick 1 x 1'), ('P', 'b2', 'Brick 1 x 1 scratched edge'), ('P', 'b3', 'Brick 1 x 1 Modified with scratched'), ('P', 'b4', 'Plate 1 x 1'))
    with loaded(coll, pair, entries) as (db, made):
        row = only(db, orders.import_document(db, 'email', email('Brick 1 x 1 scratched')))
        assert [s['item_id'] for s in json.loads(row['suggestions_json'])] == [made['b1'], made['b2'], made['b3']]     # the prefix, then fewest added words
        assert row['item_id'] is None


def test_a_line_gets_at_most_ten_suggestions(world, coll, pair):
    entries = tuple(('P', f'v{n:02d}', f'Brick 1 x 1 variant {n}') for n in range(14))
    with loaded(coll, pair, entries) as (db, made):
        row = only(db, orders.import_document(db, 'email', email('Brick 1 x 1')))
        assert len(json.loads(row['suggestions_json'])) == 10 and row['item_id'] is None


def test_a_line_whose_name_is_in_the_list_but_held_by_no_item_gets_no_suggestion_for_it(world, coll, pair):
    listed(pair, TILE)
    coll.db.close()
    with closing(connect(pair)) as db:
        result = orders.import_document(db, 'email', email('Tile, Round 2 x 2 micro scratches'))
        assert only(db, result)['suggestions_json'] is None                  # a suggestion is an item the person can choose; nothing holds this number


def test_nothing_is_suggested_when_the_item_list_is_not_loaded(world, coll):
    result = orders.import_document(coll.db, 'email', email('Tile, Round 2 x 2 micro scratches'))
    row = only(coll.db, result)
    assert row['item_id'] is None and row['suggestions_json'] is None and row['unplaced_reason'] == 'No item has exactly this name'


def test_a_line_is_stored_with_the_reason_it_was_not_placed_and_a_placed_line_has_none(world, coll):
    coll.link(world.plate, '3001', kind='P')                                            # the plate now claims 3001 too
    result = orders.import_document(coll.db, 'xml', inventory(line_of('P', '3001', colour=5), line_of('P', 'nowhere', colour=5), line_of('P', '3023', colour=5),
                                                               line_of('P', '3001', colour=9999)))
    rows = orders.lines(coll.db, result['order_id'])
    assert [r['unplaced_reason'] for r in rows] == ['The BrickLink number matches several items', 'The BrickLink number is not in the catalogue', None,
                                                    'The BrickLink colour is not known']
    assert rows[2]['item_id'] is not None
    orders.match(coll.db, result['order_id'], rows[1]['id'], item_id=world.brick, color_id=world.red)
    assert orders.lines(coll.db, result['order_id'])[1]['unplaced_reason'] is None      # placed by hand: no reason left


def test_the_api_says_why_a_line_is_unplaced(v2, world):
    made = write(v2, '/orders/documents', 'post', dict(source='xml', text=inventory(line_of('P', 'nowhere', colour=RED), line_of('P', '3001', colour=RED))), key=True)
    assert made.status_code == 200, made.text
    lines = call(v2, f"/orders/{made.json['data']['order_id']}").json['data']['lines']
    assert [(l['unplaced'], l['unplaced_reason']) for l in lines] == [(True, 'The BrickLink number is not in the catalogue'), (False, None)]


def test_a_match_undone_after_the_upgrade_from_a_receipt_without_the_new_column(world, coll):
    """A receipt written on 4.1 has no `unplaced_reason`: Undo reads it as NULL, as the Undo of every other added column does."""
    db = coll.db
    result = orders.import_document(db, 'xml', inventory(line_of('P', 'nowhere', colour=5)))
    line = orders.lines(db, result['order_id'])[0]
    event = orders.match(db, result['order_id'], line['id'], item_id=world.brick, color_id=world.red)
    db.execute('DROP TRIGGER event_no_update')                       # the receipt is rewritten as 4.1 wrote it; the test connection only
    for column in ('old_value', 'new_value'):
        entries = json.loads(db.execute(f'SELECT {column} FROM event WHERE id=?', (event,)).fetchone()[0])
        for entry in entries:
            for row in entry['rows']:
                row.pop('unplaced_reason', None)
        db.execute(f'UPDATE event SET {column}=? WHERE id=?', (json.dumps(entries), event))
    db.commit()
    orders.undo(db, event)
    row = orders.lines(db, result['order_id'])[0]
    assert row['item_id'] is None and row['state'] == 'by_hand'


# ---------- an undone document is not a duplicate ----------

def test_the_same_text_imported_again_after_undo_revives_the_document(world, coll):
    db = coll.db
    text = inventory(line_of('P', '3001', colour=5), line_of('P', 'nowhere', colour=5))
    first = orders.import_document(db, 'xml', text)
    orders.undo(db, first['event_id'])
    assert db.execute('SELECT phase FROM order_document WHERE id=?', (first['document_id'],)).fetchone()[0] == 'undone'
    again = orders.import_document(db, 'xml', text)
    assert again['duplicate'] is False and again['event_id'] and (again['placed'], again['unplaced']) == (1, 1)
    assert (again['order_id'], again['document_id']) == (first['order_id'], first['document_id'])            # the same document, not a second one
    assert db.execute('SELECT phase FROM order_document WHERE id=?', (first['document_id'],)).fetchone()[0] == 'draft'
    assert db.execute('SELECT count(*) FROM order_document').fetchone()[0] == 1 and db.execute('SELECT count(*) FROM order_line').fetchone()[0] == 2
    assert [r['state'] for r in orders.lines(db, first['order_id'])] == ['matched', 'by_hand']
    assert orders.import_document(db, 'xml', text)['duplicate'] is True                                      # a live document is a duplicate again


def test_a_revived_document_can_be_reviewed_saved_and_undone_again(world, coll):
    db = coll.db
    text = inventory(line_of('P', '3001', colour=5))
    first = orders.import_document(db, 'xml', text)
    orders.undo(db, first['event_id'])
    again = orders.import_document(db, 'xml', text)
    orders.phase(db, again['order_id'], again['document_id'], 'review')
    orders.phase(db, again['order_id'], again['document_id'], 'save')
    assert len(orders.detail(db, again['order_id'])['saved']) == 1
    with pytest.raises(Exception):
        orders.undo(db, again['event_id'])                                                                   # the save comes first
    orders.undo(db, db.execute("SELECT max(id) FROM event WHERE field='save'").fetchone()[0])
    orders.undo(db, db.execute("SELECT max(id) FROM event WHERE field='review'").fetchone()[0])
    orders.undo(db, again['event_id'])
    assert db.execute('SELECT phase FROM order_document').fetchone()[0] == 'undone'
    third = orders.import_document(db, 'xml', text)
    assert third['duplicate'] is False and third['document_id'] == first['document_id']


def test_an_undone_import_is_imported_again_through_the_api(v2, world):
    body = dict(source='xml', text=inventory(line_of('P', '3001', colour=RED)))
    first = write(v2, '/orders/documents', 'post', body, key=True)
    assert first.status_code == 200 and first.json['data']['duplicate'] is False
    assert write(v2, f"/events/{first.json['event_id']}/undo").status_code == 200
    again = write(v2, '/orders/documents', 'post', body, key=True)
    assert again.status_code == 200 and again.json['data']['duplicate'] is False and again.json['data']['placed'] == 1
    assert write(v2, '/orders/documents', 'post', body, key=True).json['data']['duplicate'] is True


def test_an_undone_document_of_another_order_is_not_a_duplicate_for_the_chosen_order(world, coll):
    db = coll.db
    text = inventory(line_of('P', '3001', colour=5))
    first = orders.import_document(db, 'xml', text)
    orders.undo(db, first['event_id'])
    other = orders.import_document(db, 'xml', inventory(line_of('P', '3023', colour=5)))
    linked = orders.import_document(db, 'xml', text, choice=other['order_id'])
    assert linked['duplicate'] is False and linked['order_id'] == other['order_id'] and linked['document_id'] != first['document_id']


# ---------- the summary export ----------

def test_the_summary_export_lists_only_orders_with_saved_lines(world, coll):
    db = coll.db
    undone = orders.import_document(db, 'xml', inventory(line_of('P', '3001', colour=5)))
    orders.undo(db, undone['event_id'])
    draft = orders.import_document(db, 'xml', inventory(line_of('P', '3023', colour=5)))
    kept = orders.import_document(db, 'xml', inventory(line_of('P', '3001', colour=5, qty=7)))
    orders.phase(db, kept['order_id'], kept['document_id'], 'review')
    orders.phase(db, kept['order_id'], kept['document_id'], 'save')
    assert {o['order_id'] for o in order_exports.rows(db, 'summary')} == {kept['order_id']}
    assert len({undone['order_id'], draft['order_id'], kept['order_id']}) == 3
    assert [o['lines'] for o in order_exports.rows(db, 'summary')] == [1] and len(order_exports.to_csv('summary', order_exports.rows(db, 'summary')).splitlines()) == 2
