"""Build Scout (#9): `core/build_scout.py` and `store4/found_copy.py` on the synthetic catalogue of `tests/test_set_scoring.py` (`SYN`).

Sets (own parts, spares left out): 9101-1 holds 3001 red x4, 3023 white x2, syn-r1 red x1 (7 parts; a spare 3023 yellow x5 is no part); 9102-1 3001 red x4 and
3023 white x1 (5); 9103-1 3001 red x2 and syn-r2 red x1 (3) with two figures `fig-000004`; 9104-1 3001 red x1 and 3023 yellow x3 (4); 9105-1 3001 red x1
and syn-m1 red x2 (3); 9106-1 two of 9101-1 and 970c22 red x1 (15, made of a set); 9107-1 3001, syn-r1, syn-r2 red x1 each (3). Years 2001 to 2007, theme Castle."""
from contextlib import closing
import json

import pytest

from brickwork.core import build_scout as B
from brickwork.core import errors, undo as undoing
from brickwork.core.connect import connect
from tests.app4 import Coll, make_pair, table_digest
from tests.store4_mint_fixtures import colour_id, item_id
from tests.test_set_scoring import SYN


@pytest.fixture
def world(tmp_path):
    path = make_pair(tmp_path, extra_dump=SYN)
    with closing(connect(path)) as db:
        coll = Coll(db)
        yield W(db, coll, path)


class W:
    def __init__(self, db, coll, path):
        self.db, self.coll, self.path = db, coll, path
        self.red, self.white, self.yellow = (colour_id(db, n) for n in ('4', '15', '14'))

    def part(self, number):
        return item_id(self.db, 'parts', number)

    def set(self, number):
        return item_id(self.db, 'sets', number)

    def stock(self, number, colour, quantity, **fields):
        return self.coll.add_stock('part', self.part(number), colour=colour, quantity=quantity, **fields)

    def figure(self, quantity=1, **fields):
        return self.coll.add_stock('minifigure', item_id(self.db, 'minifigs', 'fig-000004'), quantity=quantity, **fields)

    def scout(self, **kwargs):
        return B.scout(self.db, **kwargs)

    def row(self, answer, number):
        return next((r for r in answer['results'] if r['set_item_id'] == self.set(number)), None)

    def fill(self):
        """Enough loose stock for 9102-1 in full and 9101-1 but its rare part."""
        self.stock('3001', self.red, 4)
        self.stock('3023', self.white, 2)


# ---------- the numbers ----------

def test_percent_available_counts_the_parts_of_the_set_and_leaves_spares_out(world):
    w = world
    w.fill()
    answer = w.scout()
    one, two = w.row(answer, '9101-1'), w.row(answer, '9102-1')
    assert (one['parts_available'], one['parts_total'], one['missing_parts'], one['missing_lines']) == (6, 7, 1, 1)      # the spare yellow 3023 is no part
    assert one['percent'] == 85.7 and (one['year'], one['theme']) == (2001, 'Castle')
    assert (two['parts_available'], two['parts_total'], two['missing_parts'], two['missing_lines'], two['percent']) == (5, 5, 0, 0, 100.0)
    assert [r['rank'] for r in answer['results']] == [1, 2, 3]
    assert [r['set_item_id'] for r in answer['results']] == [w.set('9102-1'), w.set('9101-1'), w.set('9103-1')]       # 100 %, 85.7 %, 66.7 % (3001 x2 of 3)
    assert answer['input'] == dict(lines=2, pieces=6, figures=0) and answer['total'] == 3 and answer['filters']['min_percent'] == 60


def test_a_quantity_short_of_the_need_covers_what_it_holds(world):
    w = world
    w.stock('3001', w.red, 2)
    row = w.row(w.scout(min_percent=0), '9102-1')
    assert (row['parts_available'], row['missing_parts'], row['missing_lines']) == (2, 3, 2)           # 3001 x2 of 4, and 3023 not at all


def test_sorted_by_percent_then_fewest_missing_then_id(world):
    w = world
    w.stock('3001', w.red, 1)
    w.stock('syn-r1', w.red, 1)
    w.stock('syn-r2', w.red, 1)
    answer = w.scout(min_percent=0)
    order = [(r['percent'], r['missing_parts']) for r in answer['results']]
    assert order == sorted(order, key=lambda t: (-t[0], t[1]))
    assert w.row(answer, '9107-1')['percent'] == 100.0 and answer['results'][0]['set_item_id'] == w.set('9107-1')
    # equal percent, fewer missing first: 9105 and 9104 hold 1 of 3 and 1 of 4: 9105 (33.3 %) ranks above 9104 (25 %); 9103 holds 2 of 3
    assert [r['set_item_id'] for r in answer['results']].index(w.set('9103-1')) < [r['set_item_id'] for r in answer['results']].index(w.set('9105-1'))


def test_figures_are_counted_apart_and_a_loose_figure_counts_whole(world):
    w = world
    w.stock('3001', w.red, 2)
    w.stock('syn-r2', w.red, 1)
    w.figure(1)
    row = w.row(w.scout(), '9103-1')
    assert (row['parts_available'], row['parts_total'], row['percent']) == (3, 3, 100.0)                  # the figure is no part
    assert (row['figures_available'], row['figures_required'], row['missing_figures']) == (1, 2, 1)
    # loose parts of a figure never count as the figure
    other = w.scout(min_percent=0)
    assert w.row(other, '9101-1')['figures_required'] == 0


def test_a_damaged_row_or_a_defective_figure_counts_for_nothing_unless_asked(world):
    w = world
    w.stock('3001', w.red, 4, condition='used')
    w.stock('3023', w.white, 2, condition='damaged')
    assert w.row(w.scout(min_percent=0), '9102-1')['parts_available'] == 4
    assert w.row(w.scout(min_percent=0, damaged=True), '9102-1')['parts_available'] == 5
    figure = w.figure(1)
    w.coll.sql('UPDATE stock_part SET missing=1 WHERE stock_id=? AND rowid=(SELECT min(rowid) FROM stock_part WHERE stock_id=?)', (figure, figure))
    assert w.row(w.scout(min_percent=0), '9103-1') is None or w.row(w.scout(min_percent=0), '9103-1')['figures_available'] == 0


def test_swaps_are_listed_apart_and_never_in_the_percent(world):
    w = world
    w.stock('3023', w.white, 3)
    w.stock('3001', w.red, 1)
    detail = B.set_detail(w.db, w.set('9104-1'))
    assert (detail['parts_available'], detail['parts_total']) == (1, 4)                                      # the white 3023 is no yellow one
    swap = [s for s in detail['swaps']['items'] if s['kind'] == 'colour']
    assert len(swap) == 1 and swap[0]['quantity'] == 3 and swap[0]['have']['color_id'] == w.white and swap[0]['wanted']['color_id'] == w.yellow
    assert [m['missing'] for m in detail['gaps']] == [3]


def test_missing_lines_and_cost_say_how_many_lines_are_unpriced(world):
    w = world
    w.stock('3001', w.red, 4)
    w.coll.price(w.part('3023'), '0.30', colour=w.white)
    detail = B.set_detail(w.db, w.set('9101-1'))
    assert [(m['item_id'], m['missing']) for m in detail['gaps']] == [(w.part('3023'), 2), (w.part('syn-r1'), 1)]
    assert detail['cost'] == dict(amount='0.60', currency='EUR', priced_lines=1, unpriced_lines=1)
    assert B.set_detail(w.db, w.set('9102-1'))['cost'] == dict(amount='0.30', currency='EUR', priced_lines=1, unpriced_lines=0)
    assert B.set_detail(w.db, w.set('9105-1'))['cost']['amount'] is None                                 # nothing priced: no amount, not 0.00
    page = w.scout(min_percent=0, detail=5)
    assert w.row(page, '9101-1')['cost']['unpriced_lines'] == 1 and len(w.row(page, '9101-1')['gaps']) == 2


def test_a_price_in_another_currency_is_left_out(world):
    w = world
    w.coll.price(w.part('3023'), '0.30', colour=w.white)
    w.coll.price(w.part('syn-r1'), '9.00', colour=w.red, currency='USD')
    w.coll.price(w.part('3001'), '0.10', colour=w.red)
    assert B.price_map(w.db, [(w.part('3023'), w.white), (w.part('syn-r1'), w.red), (w.part('3001'), w.red)])['currency'] == 'EUR'
    assert len(B.price_map(w.db, [(w.part('3023'), w.white), (w.part('syn-r1'), w.red), (w.part('3001'), w.red)])['prices']) == 2


# ---------- filters ----------

def test_filters_minimum_missing_theme_year_and_size(world):
    w = world
    w.fill()
    w.stock('syn-r2', w.red, 1)
    base = {r['set_item_id'] for r in w.scout(min_percent=0)['results']}
    assert w.set('9101-1') in base and w.set('9102-1') in base
    assert {r['set_item_id'] for r in w.scout(min_percent=90)['results']} == {w.set('9102-1'), w.set('9103-1')}
    assert {r['set_item_id'] for r in w.scout(min_percent=0, max_missing=0)['results']} == {w.set('9102-1'), w.set('9103-1')}
    assert {r['set_item_id'] for r in w.scout(min_percent=0, theme='castle')['results']} == base
    assert {r['set_item_id'] for r in w.scout(min_percent=0, theme='600')['results']} == base
    with pytest.raises(ValueError):
        w.scout(theme='No such theme')
    assert {r['set_item_id'] for r in w.scout(min_percent=0, year_from=2002, year_to=2002)['results']} == {w.set('9102-1')}
    assert {r['set_item_id'] for r in w.scout(min_percent=0, size_from=6, size_to=8)['results']} == {w.set('9101-1')}
    assert w.set('9101-1') not in {r['set_item_id'] for r in w.scout(min_percent=0, size_to=5)['results']}


def test_a_theme_filter_includes_sub_themes(world):
    w = world
    w.fill()
    scout = B.scout_for(w.db)
    scout.themes[601] = ('Castle Sub', 600)
    scout.children[600].append(601)
    scout.meta[w.set('9102-1')] = (2002, 601)
    assert 601 in scout.theme_ids('Castle') and scout.theme_ids('Castle Sub') == {601}
    assert w.set('9102-1') in {r['set_item_id'] for r in w.scout(min_percent=0, theme='Castle')['results']}


def test_refused_arguments(world):
    w = world
    for kwargs in (dict(limit=0), dict(limit=101), dict(offset=-1), dict(min_percent=101), dict(min_percent='x'), dict(max_missing=-1)):
        with pytest.raises(ValueError):
            w.scout(**kwargs)


# ---------- sources ----------

def test_sources_are_a_union_of_unassigned_lots_and_storages(world):
    w = world
    shelf = w.coll.storage('Shelf')
    drawer = w.coll.storage('Drawer', parent_id=shelf)
    lot_a, lot_b = w.coll.lot('A'), w.coll.lot('B')
    loose = w.stock('3001', w.red, 4)
    in_lot = w.stock('3023', w.white, 2, lot=lot_a)
    other_lot = w.stock('syn-r1', w.red, 1, lot=lot_b)
    in_drawer = w.coll.add_stock('part', w.part('3001'), colour=w.red, quantity=10, storage=drawer)
    ids = lambda **s: {r['id'] for r in B.stock_rows(w.db, **s)}          # noqa: E731
    assert ids() == {loose, in_lot, other_lot, in_drawer}
    assert ids(loose=True) == {loose}
    assert ids(lots=[lot_a]) == {in_lot} and ids(lots=[lot_a, lot_b]) == {in_lot, other_lot}
    assert ids(storages=[shelf]) == {in_drawer}                          # the storages inside a storage are in it
    assert ids(loose=True, lots=[lot_a], storages=[drawer]) == {loose, in_lot, in_drawer}
    both = w.coll.add_stock('part', w.part('3001'), colour=w.red, quantity=1, condition='new', lot=lot_a, storage=shelf)
    assert [r['id'] for r in B.stock_rows(w.db, lots=[lot_a], storages=[shelf])].count(both) == 1
    answer = w.scout(min_percent=0, lots=[lot_a])
    assert answer['source']['text'] == '1 lot' and answer['input']['pieces'] == 3
    assert B.sources_text(w.db, [], [], True) == 'Loose stock' and B.sources_text(w.db) == 'All loose stock'


def test_only_live_loose_parts_and_figures_with_stock_are_used(world):
    w = world
    kept = w.stock('3001', w.red, 4)
    gone = w.stock('3023', w.white, 2)
    w.coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-11-01T00:00:00Z', gone))
    empty = w.stock('syn-r1', w.red, 1)
    w.coll.sql('UPDATE stock SET quantity=0 WHERE id=?', (empty,))
    w.coll.add_stock('gear', w.coll.local('gear', 'A thing'), quantity=3)
    assert [r['id'] for r in B.stock_rows(w.db)] == [kept]


# ---------- the actions ----------

def test_missing_parts_are_exported_by_the_copies_exporter(world):
    w = world
    w.stock('3001', w.red, 4)
    export = B.missing_export(w.db, w.set('9101-1'))
    assert export['xml'].startswith(b'<?xml') and b'<INVENTORY>' in export['xml']
    assert sum(line['quantity'] for line in export['lines']) + sum(s['quantity'] if isinstance(s, dict) else 0 for s in export['skipped']) == 3     # 3023 x2 and syn-r1; the stock holds all of 3001
    w.stock('3023', w.white, 2)
    w.stock('syn-r1', w.red, 1)
    with pytest.raises(ValueError):
        B.missing_export(w.db, w.set('9101-1'))                                                    # nothing is missing now


def test_the_wish_is_marked_and_a_second_one_is_not_added(world):
    w = world
    first = B.wish_set(w.db, w.set('9101-1'))
    assert first['already'] is False and first['wish_id']
    wish = w.db.execute('SELECT * FROM wish WHERE id=?', (first['wish_id'],)).fetchone()
    assert (wish['kind'], wish['note'], wish['item_id'], wish['archived_at']) == ('set', B.WISH_NOTE, w.set('9101-1'), None)
    assert B.wish_set(w.db, w.set('9101-1')) == dict(event_id=None, wish_id=None, already=True)
    with pytest.raises(ValueError):
        B.wish_set(w.db, w.part('3001'))


# ---------- Build it ----------

def stock_state(db):
    return {r['id']: r['quantity'] for r in db.execute('SELECT id, quantity FROM stock')}


def test_build_it_moves_the_parts_into_a_copy_and_records_the_rest_as_missing(world):
    w = world
    big = w.stock('3001', w.red, 3, condition='used')
    small = w.stock('3001', w.red, 2, condition='new')
    plate = w.stock('3023', w.white, 5)
    before = stock_state(w.db)
    made = B.build_set(w.db, w.set('9101-1'))
    assert (made['pieces'], made['figures'], made['missing_parts'], made['missing_figures'], made['completeness']) == (6, 0, 1, 0, 'incomplete')
    after = stock_state(w.db)
    assert (after[big], after[small], after[plate]) == (0, 1, 3)                                    # the largest row first, then the next
    copy = w.db.execute('SELECT * FROM copy WHERE id=?', (made['copy_id'],)).fetchone()
    assert (copy['item_id'], copy['condition'], copy['completeness'], copy['completeness_source'], copy['archived_at'], copy['inventory_source']) == (
        w.set('9101-1'), 'used', 'incomplete', 'manual', None, 'rebrickable')
    lines = {(r['item_id'], r['color_id'], r['is_spare']): (r['quantity'], r['missing']) for r in w.db.execute('SELECT * FROM copy_part WHERE copy_id=?', (made['copy_id'],))}
    assert lines[(w.part('3001'), w.red, 0)] == (4, 0) and lines[(w.part('3023'), w.white, 0)] == (2, 0) and lines[(w.part('syn-r1'), w.red, 0)] == (1, 1)
    assert lines[(w.part('3023'), w.yellow, 1)] == (5, 0)                                          # the spare line is on the copy, not missing
    moves = w.db.execute('SELECT stock_id, quantity, event_id, copy_part_id FROM stock_transfer WHERE copy_id=? ORDER BY id', (made['copy_id'],)).fetchall()
    assert sorted((m['stock_id'], m['quantity']) for m in moves) == sorted([(big, 3), (small, 1), (plate, 2)]) and {m['event_id'] for m in moves} == {made['event_id']}
    events = w.db.execute("SELECT entity_kind, field FROM event WHERE id=?", (made['event_id'],)).fetchone()
    assert (events['entity_kind'], events['field']) == ('copy', 'make_from_stock')
    # the Scout's own numbers for the pile that is left
    assert before != after


def test_build_it_takes_whole_figures_and_marks_the_missing_ones(world):
    w = world
    w.stock('3001', w.red, 2)
    w.stock('syn-r2', w.red, 1)
    figure = w.figure(1)
    made = B.build_set(w.db, w.set('9103-1'))
    assert (made['pieces'], made['figures'], made['missing_parts'], made['missing_figures']) == (3, 1, 0, 1)
    line = w.db.execute('SELECT * FROM copy_figure WHERE copy_id=?', (made['copy_id'],)).fetchone()
    assert (line['quantity'], line['missing']) == (2, 1)
    assert w.db.execute('SELECT quantity FROM stock WHERE id=?', (figure,)).fetchone()[0] == 0
    parts = w.db.execute('SELECT quantity, missing FROM copy_part WHERE copy_id=? AND copy_figure_id=?', (made['copy_id'], line['id'])).fetchall()
    assert parts and all(p['missing'] * 2 == p['quantity'] for p in parts)                      # one of the two figures is missing: half of each line
    assert w.db.execute('SELECT completeness FROM copy WHERE id=?', (made['copy_id'],)).fetchone()[0] == 'incomplete'


def test_a_complete_build_is_a_complete_copy(world):
    w = world
    w.fill()
    made = B.build_set(w.db, w.set('9102-1'))
    assert (made['missing_parts'], made['completeness']) == (0, 'complete')


def test_undo_puts_the_stock_back_and_archives_the_copy(world):
    w = world
    w.fill()
    w.figure(1)
    before = table_digest(w.db, skip=('event', 'event_undo', 'item_merge'))
    scout_before = w.scout(min_percent=0)
    stock_before = stock_state(w.db)
    made = B.build_set(w.db, w.set('9101-1'))
    assert w.row(w.scout(min_percent=0), '9101-1') is None                                           # the parts moved into the copy
    result = undoing.undo_event(w.db, made['event_id'])
    assert result['already_undone'] is False and result['undo_event_id']
    copy = w.db.execute('SELECT archived_at FROM copy WHERE id=?', (made['copy_id'],)).fetchone()
    assert copy['archived_at'] is not None
    assert w.scout(min_percent=0) == scout_before                                                    # the same stock, the same numbers
    assert stock_state(w.db) == stock_before
    assert undoing.undo_event(w.db, made['event_id'])['already_undone'] is True
    after = table_digest(w.db, skip=('event', 'event_undo', 'item_merge', 'copy', 'copy_part', 'copy_figure', 'stock_transfer',
                                                'item', 'item_link', 'item_provider_status', 'color'))      # what a copy projects stays: harmless catalogue rows
    assert {k: v for k, v in before.items() if k in after} == after


def test_undo_is_refused_when_the_copy_changed_since(world):
    w = world
    w.fill()
    made = B.build_set(w.db, w.set('9101-1'))
    w.coll.sql('UPDATE copy SET note=? WHERE id=?', ('edited', made['copy_id']))
    with pytest.raises(errors.UndoBlocked):
        undoing.undo_event(w.db, made['event_id'])
    assert w.db.execute('SELECT archived_at FROM copy WHERE id=?', (made['copy_id'],)).fetchone()[0] is None


def test_undo_is_refused_when_the_stock_changed_since(world):
    w = world
    big = w.stock('3001', w.red, 4)
    w.stock('3023', w.white, 2)
    made = B.build_set(w.db, w.set('9101-1'))
    w.coll.sql('UPDATE stock SET quantity=7 WHERE id=?', (big,))
    with pytest.raises(errors.UndoBlocked):
        undoing.undo_event(w.db, made['event_id'])


def test_build_it_refusals_write_nothing(world):
    w = world
    w.fill()
    with pytest.raises(ValueError):
        B.build_set(w.db, w.set('9106-1'))                                                         # made of other sets
    with pytest.raises(ValueError):
        B.build_set(w.db, w.part('3001'))                                                          # not a set
    with pytest.raises(ValueError):
        B.build_set(w.db, w.set('9101-1'), lots=['none'])                                          # no stock in that source
    assert w.db.execute('SELECT count(*) FROM copy').fetchone()[0] == 0
    assert w.db.execute("SELECT count(*) FROM event WHERE field='make_from_stock'").fetchone()[0] == 0


def test_build_it_uses_only_the_chosen_sources(world):
    w = world
    lot = w.coll.lot('Bag')
    w.stock('3001', w.red, 4)
    inside = w.stock('3023', w.white, 2, lot=lot)
    made = B.build_set(w.db, w.set('9101-1'), lots=[lot])
    assert made['pieces'] == 2 and stock_state(w.db)[inside] == 0
    assert w.db.execute('SELECT count(*) FROM stock WHERE quantity=4').fetchone()[0] == 1


# ---------- review findings ----------

def test_a_set_with_an_unscorable_child_set_is_still_made_of_sets(world):
    import sqlite3
    w = world
    w.stock('970c22', w.red, 1)
    w.stock('3001', w.red, 8)
    with closing(sqlite3.connect(w.path.parent / 'catalogue.db')) as cat:                   # 9101-1 (the child of 9106-1) loses its live latest inventory
        cat.execute("UPDATE inventory SET is_latest=0 WHERE item_id=?", (w.set('9101-1'),))
        cat.commit()
    B._SCOUTS.clear()
    assert w.set('9106-1') in B.scout_for(w.db).nested
    assert w.scout(min_percent=0)['results'] and w.row(w.scout(min_percent=0), '9106-1')['nested'] is True
    with pytest.raises(ValueError):
        B.build_set(w.db, w.set('9106-1'))
    assert w.db.execute('SELECT count(*) FROM copy').fetchone()[0] == 0


def test_undo_ignores_a_transfer_that_was_itself_undone(world):
    from brickwork.core import workbench
    w = world
    w.stock('3001', w.red, 4)
    w.stock('3023', w.white, 2)
    made = B.build_set(w.db, w.set('9101-1'))
    rare = w.stock('syn-r1', w.red, 1)
    gap = w.db.execute('SELECT id FROM copy_part WHERE copy_id=? AND item_id=? AND missing>0', (made['copy_id'], w.part('syn-r1'))).fetchone()[0]
    event = workbench.transfer(w.db, rare, made['copy_id'], 'part', gap, 1)
    with pytest.raises(errors.UndoBlocked):                                                  # a live later transfer still blocks
        undoing.undo_event(w.db, made['event_id'])
    undoing.undo_event(w.db, event)
    assert undoing.undo_event(w.db, made['event_id'])['already_undone'] is False
    assert w.db.execute('SELECT archived_at FROM copy WHERE id=?', (made['copy_id'],)).fetchone()[0] is not None


def test_the_wish_check_and_the_write_are_one_transaction(world, monkeypatch):
    from brickwork.core import add
    w = world
    seen = []
    real = add.confirm
    monkeypatch.setattr(add, 'confirm', lambda db, *a, **k: (seen.append(db.in_transaction), real(db, *a, **k))[1])
    assert B.wish_set(w.db, w.set('9101-1'))['already'] is False
    assert seen == [True]
