"""The pull list of a detected set (#202): `core/pull_list.py` on the synthetic catalogue of `tests/test_set_scoring.py` (`SYN`).

Sets (own parts, spares left out): 9101-1 holds 3001 red x4, 3023 white x2, syn-r1 red x1 (7 parts); 9103-1 3001 red x2, syn-r2 red x1 and two figures `fig-000004`;
9106-1 is made of two 9101-1 and one 970c22 (a set made of other sets). The lot `Flohmarkt` is arranged by each test."""
from contextlib import closing
import json

import pytest

from brickwork.core import errors, pull_list as P, undo as undoing
from brickwork.core.connect import connect
from tests.app4 import Coll, make_pair, table_digest
from tests.store4_mint_fixtures import colour_id, item_id
from tests.test_set_scoring import SYN


@pytest.fixture
def world(tmp_path):
    path = make_pair(tmp_path, extra_dump=SYN)
    with closing(connect(path)) as db:
        yield W(db, Coll(db), path)


class W:
    def __init__(self, db, coll, path):
        self.db, self.coll, self.path = db, coll, path
        self.red, self.white = colour_id(db, '4'), colour_id(db, '15')
        self.lot = coll.lot('Flohmarkt')
        self.set = item_id(db, 'sets', '9101-1')

    def part(self, number):
        return item_id(self.db, 'parts', number)

    def stock(self, number, colour, quantity, lot='mine', **fields):
        return self.coll.add_stock('part', self.part(number), colour=colour, quantity=quantity, lot=self.lot if lot == 'mine' else lot, **fields)

    def state(self, set_number='9101-1'):
        return P.state(self.db, self.lot, item_id(self.db, 'sets', set_number))

    def line(self, number, colour=None, state=None):
        item = self.part(number)
        return next(ln for ln in (state or self.state())['lines'] if (ln['item_id'], ln['color_id']) == (item, colour))

    def tick(self, number, colour, found):
        return P.set_found(self.db, self.lot, self.set, self.part(number), colour, found)

    def events(self):
        return self.db.execute('SELECT count(*) FROM main.event').fetchone()[0]

    def quantity(self, stock_id):
        return self.db.execute('SELECT quantity FROM main.stock WHERE id=?', (stock_id,)).fetchone()[0]


# ---------- the list: the inventory minus what the lot holds ----------

def test_the_list_is_the_inventory_minus_the_lot_with_parts_only(world):
    w = world
    w.stock('3001', w.red, 3)
    info = w.state()
    assert (w.line('3001', w.red)['need'], w.line('3001', w.red)['held'], w.line('3001', w.red)['found']) == (4, 3, 3)
    assert (w.line('3023', w.white)['need'], w.line('3023', w.white)['held']) == (2, 0)
    assert w.line('syn-r1', w.red)['need'] == 1 and len(info['lines']) == 3                      # the spare 3023 yellow is no line
    assert info['totals'] == dict(need=7, held=3, found=3, lines=3, lines_to_find=3, figures_need=0, figures_found=0, to_find=4)
    assert info['set']['id'] == w.set and info['lot']['name'] == 'Flohmarkt' and info['refusal'] is None and not info['nested']
    assert all(isinstance(ln['category'], str) and ln['kind'] == 'part' for ln in info['lines'])


def test_what_the_lot_holds_beyond_the_need_and_damaged_rows_do_not_count(world):
    w = world
    w.stock('3001', w.red, 9)                                                                    # more than the 4 the set has
    w.stock('3023', w.white, 5, condition='damaged')                                             # damaged gives nothing
    assert (w.line('3001', w.red)['held'], w.line('3023', w.white)['held']) == (4, 0)
    assert w.state()['totals']['found'] == 4


def test_whole_figures_are_lines_of_their_own_and_other_lots_are_not_counted(world):
    w = world
    w.coll.add_stock('minifigure', item_id(w.db, 'minifigs', 'fig-000004'), quantity=1, lot=w.lot)
    w.stock('3001', w.red, 5, lot=w.coll.lot('Other lot'))
    info = w.state('9103-1')
    figure = next(ln for ln in info['lines'] if ln['kind'] == 'figure')
    assert (figure['need'], figure['held'], figure['color_id'], figure['category']) == (2, 1, None, 'Minifigures')
    assert (info['totals']['figures_need'], info['totals']['figures_found'], info['totals']['found']) == (2, 1, 1)
    assert next(ln for ln in info['lines'] if ln['item_id'] == w.part('3001'))['held'] == 0


def test_refusals_of_the_read(world):
    w = world
    with pytest.raises(errors.NotFound):
        P.state(w.db, 'nothing', w.set)
    with pytest.raises(errors.NotFound):
        P.state(w.db, w.lot, w.part('3001'))                                                     # a part is no set
    with pytest.raises(errors.NotFound):
        P.state(w.db, w.lot, 987654321)
    nested = w.state('9106-1')
    assert nested['nested'] and 'other sets' in nested['refusal']


# ---------- progress ----------

def test_progress_is_kept_clamped_and_writes_no_event(world):
    w = world
    w.stock('3001', w.red, 1)
    events = w.events()
    line = w.tick('3001', w.red, 3)
    assert (line['held'], line['ticked'], line['found']) == (1, 2, 3)
    w.tick('3023', w.white, 2)
    assert w.events() == events and w.line('3001', w.red)['found'] == 3 and w.state()['totals']['found'] == 5
    key = f'pull:{w.lot}:{w.set}'
    assert json.loads(w.db.execute('SELECT value FROM main.setting WHERE key=?', (key,)).fetchone()[0]) == {'found': {f'{w.part("3001")}:{w.red}': 2, f'{w.part("3023")}:{w.white}': 2}}
    again = w.tick('3001', w.red, 3)                                                             # idempotent
    assert again == line and w.state()['totals']['found'] == 5
    assert w.tick('3001', w.red, 0)['found'] == 1                                                 # below what the lot holds: only the ticks go
    w.tick('3023', w.white, 0)
    assert w.db.execute('SELECT 1 FROM main.setting WHERE key=?', (key,)).fetchone() is None     # nothing left to keep


def test_a_lot_that_gains_the_part_never_counts_it_twice(world):
    w = world
    w.tick('3001', w.red, 3)
    assert w.line('3001', w.red)['found'] == 3
    w.stock('3001', w.red, 3)
    line = w.line('3001', w.red)
    assert (line['held'], line['ticked'], line['found']) == (3, 1, 4)                           # the stored 3 is clamped to what is still lacking


def test_progress_refusals_write_nothing(world):
    w = world
    before = table_digest(w.db)
    for item, colour, found in (('syn-m1', w.red, 1), ('3001', w.red, 5), ('3001', w.red, -1), ('3001', w.red, True), ('3001', w.red, 1.5), ('3001', w.white, 1)):
        with pytest.raises(ValueError):
            P.set_found(w.db, w.lot, w.set, w.part(item), colour, found)                          # not on the list, above the need, not a whole number
    with pytest.raises(errors.NotFound):
        P.set_found(w.db, 'nothing', w.set, w.part('3001'), w.red, 1)
    assert table_digest(w.db) == before


# ---------- Make it a copy ----------

def test_make_it_a_copy_moves_exactly_the_found_counts_and_records_the_rest_as_missing(world):
    w = world
    held = w.stock('3001', w.red, 3)
    noise = w.stock('syn-m1', w.red, 5)                                                          # not a part of the set: stays
    other = w.stock('3001', w.red, 6, lot=w.coll.lot('Other lot'))                              # another lot's: untouched
    w.tick('3001', w.red, 4)
    w.tick('3023', w.white, 2)
    info = w.state()
    numbers = P.moves(info)
    before_events = w.events()
    made = P.make_copy(w.db, w.lot, w.set)
    assert (made['pieces'], made['figures'], made['missing_parts'], made['missing_figures'], made['completeness']) == (6, 0, 1, 0, 'incomplete')
    assert (numbers['moves'], numbers['missing']) == (made['pieces'], made['missing_parts'])
    copy = w.db.execute('SELECT * FROM main.copy WHERE id=?', (made['copy_id'],)).fetchone()
    assert (copy['item_id'], copy['completeness'], copy['archived_at']) == (w.set, 'incomplete', None)
    assert w.quantity(held) == 0 and w.quantity(noise) == 5 and w.quantity(other) == 6            # exactly the found counts left THIS lot
    assert made['stays'] == numbers['stays'] == 5
    missing = w.db.execute('SELECT item_id, missing FROM main.copy_part WHERE copy_id=? AND missing>0', (made['copy_id'],)).fetchall()
    assert [(r['item_id'], r['missing']) for r in missing] == [(w.part('syn-r1'), 1)]
    event = w.db.execute('SELECT * FROM main.event WHERE id=?', (made['event_id'],)).fetchone()
    assert (event['entity_kind'], event['field']) == ('copy', 'make_from_stock')
    assert w.db.execute("SELECT count(*) FROM main.event WHERE entity_kind='copy'").fetchone()[0] == 1
    assert w.db.execute('SELECT 1 FROM main.setting WHERE key=?', (f'pull:{w.lot}:{w.set}',)).fetchone() is None     # the progress is cleared
    assert w.events() > before_events
    # the pieces that were ticked but not filed are stock of the lot now (found in the bulk), moved out into the copy
    filed = w.db.execute("SELECT quantity, note FROM main.stock WHERE lot_id=? AND item_id=? AND archived_at IS NULL", (w.lot, w.part('3023'))).fetchall()
    assert [(r['quantity'], r['note']) for r in filed] == [(0, P.BULK_NOTE)]
    after = w.state()
    assert after['totals']['found'] == 0 and w.line('3001', w.red, after)['held'] == 0


def test_the_copy_lines_match_the_pull_list_and_the_matcher_sees_the_missing_part(world):
    w = world
    w.stock('3001', w.red, 4)
    made = P.make_copy(w.db, w.lot, w.set)
    assert (made['pieces'], made['missing_parts']) == (4, 3)
    rows = w.db.execute('SELECT item_id, quantity, missing FROM main.copy_part WHERE copy_id=? AND is_spare=0', (made['copy_id'],)).fetchall()
    assert sorted((r['quantity'], r['missing']) for r in rows) == [(1, 1), (2, 2), (4, 0)]


def test_undo_restores_the_lot_and_the_ticked_pieces_stay_filed_in_it(world):
    w = world
    held = w.stock('3001', w.red, 3)
    w.tick('3001', w.red, 4)
    w.tick('3023', w.white, 1)
    made = P.make_copy(w.db, w.lot, w.set)
    assert w.quantity(held) == 0
    result = undoing.undo_event(w.db, made['event_id'])
    assert result['already_undone'] is False
    copy = w.db.execute('SELECT archived_at FROM main.copy WHERE id=?', (made['copy_id'],)).fetchone()
    assert copy['archived_at'] is not None
    assert w.db.execute("SELECT sum(quantity) FROM main.stock WHERE lot_id=? AND item_id=? AND archived_at IS NULL", (w.lot, w.part('3001'))).fetchone()[0] == 4
    state = w.state()
    assert (w.line('3001', w.red, state)['found'], w.line('3023', w.white, state)['found']) == (4, 1)          # filed in the lot: found, not ticked twice
    assert state['totals']['found'] == 5 and state['ticked_total'] == 0


def test_refusals_write_nothing(world):
    w = world
    before = table_digest(w.db)
    with pytest.raises(ValueError, match='Nothing found yet'):
        P.make_copy(w.db, w.lot, w.set)
    w.tick('3001', w.red, 2)
    digest = table_digest(w.db)
    nested = item_id(w.db, 'sets', '9106-1')
    with pytest.raises(ValueError, match='other sets'):
        P.make_copy(w.db, w.lot, nested)
    with pytest.raises(errors.NotFound):
        P.make_copy(w.db, 'nothing', w.set)
    with pytest.raises(errors.NotFound):
        P.make_copy(w.db, w.lot, w.part('3001'))
    assert table_digest(w.db) == digest and digest != before
    assert not w.db.execute("SELECT 1 FROM main.event WHERE field='make_from_stock'").fetchone()


def test_a_figure_ticked_in_the_bulk_is_filed_and_moved_too(world):
    w = world
    w.coll.add_stock('minifigure', item_id(w.db, 'minifigs', 'fig-000004'), quantity=1, lot=w.lot)
    figure = item_id(w.db, 'minifigs', 'fig-000004')
    P.set_found(w.db, w.lot, item_id(w.db, 'sets', '9103-1'), figure, None, 2)
    made = P.make_copy(w.db, w.lot, item_id(w.db, 'sets', '9103-1'))
    assert (made['figures'], made['missing_figures'], made['pieces']) == (2, 0, 0)


def test_a_set_of_whole_figures_only_has_a_pull_list_and_can_be_made_a_copy(tmp_path):
    dump = {**SYN, 'sets': SYN['sets'] + [['9199-1', 'Syn Figure Set', 2010, 600, 1, '']], 'inventories': SYN['inventories'] + [[9199, 1, '9199-1']],
            'inventory_minifigs': SYN['inventory_minifigs'] + [[9199, 'fig-000004', 1]]}
    path = make_pair(tmp_path, extra_dump=dump)
    with closing(connect(path)) as db:
        w = W(db, Coll(db), path)
        figure = item_id(db, 'minifigs', 'fig-000004')
        w.coll.add_stock('minifigure', figure, quantity=1, lot=w.lot)
        chosen = item_id(db, 'sets', '9199-1')
        info = P.state(db, w.lot, chosen)                                   # no part lines: it is not in the parts index
        assert [(ln['kind'], ln['need'], ln['found']) for ln in info['lines']] == [('figure', 1, 1)] and info['refusal'] is None
        made = P.make_copy(db, w.lot, chosen)
        assert (made['figures'], made['pieces'], made['missing_figures']) == (1, 0, 0) and made['completeness'] == 'complete'
