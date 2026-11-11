"""Sets versus a pile of parts (#199): the scoring engine on a synthetic catalogue (`syn` rows only) and at scale in memory.

The catalogue is the fixture catalogue plus a few invented sets: `9101-1` to `9106-1` (see `SYN`), so the weights, swaps, figures and sub-sets
have known answers. No network."""
from contextlib import closing
import math
import random
import sqlite3
import time

import pytest

from brickwork.core import set_scoring as S
from brickwork.core.connect import connect
from tests.app4 import Coll, make_pair
from tests.store4_mint_fixtures import colour_id, item_id

# Colours (Rebrickable): 4 red, 15 white, 14 yellow, 0 black. Part 3001 is in every set: a common line. `syn-r1` and `syn-r2` are in two sets.
SYN = {
    'themes': [[600, 'Castle', '']],
    'parts': [['syn-r1', 'Syn Rare One', 14, 'Plastic'], ['syn-r2', 'Syn Rare Two', 14, 'Plastic'], ['syn-m1', 'Syn Mould A', 14, 'Plastic'],
              ['syn-m2', 'Syn Mould B', 14, 'Plastic']],
    'sets': [[f'91{n:02d}-1', f'Syn Set {n}', 2000 + n, 600, 3, ''] for n in range(1, 8)],
    'inventories': [[9101, 1, '9101-1'], [9102, 1, '9102-1'], [9103, 1, '9103-1'], [9104, 1, '9104-1'], [9105, 1, '9105-1'], [9106, 1, '9106-1'],
                    [9107, 1, '9107-1']],
    'inventory_parts': [
        [9101, '3001', 4, 4, 'False', ''], [9101, '3023', 15, 2, 'False', ''], [9101, 'syn-r1', 4, 1, 'False', ''], [9101, '3023', 14, 5, 'True', ''],
        [9102, '3001', 4, 4, 'False', ''], [9102, '3023', 15, 1, 'False', ''],
        [9103, '3001', 4, 2, 'False', ''], [9103, 'syn-r2', 4, 1, 'False', ''],
        [9104, '3001', 4, 1, 'False', ''], [9104, '3023', 14, 3, 'False', ''],
        [9105, '3001', 4, 1, 'False', ''], [9105, 'syn-m1', 4, 2, 'False', ''],
        [9106, '970c22', 4, 1, 'False', ''],
        [9107, '3001', 4, 1, 'False', ''], [9107, 'syn-r1', 4, 1, 'False', ''], [9107, 'syn-r2', 4, 1, 'False', ''],
    ],
    'inventory_minifigs': [[9103, 'fig-000004', 2]],
    'inventory_sets': [[9106, '9101-1', 2]],
    'part_relationships': [['M', 'syn-m1', 'syn-m2'], ['P', '3001', 'syn-m2']],
}


@pytest.fixture
def cat(tmp_path):
    path = make_pair(tmp_path, extra_dump=SYN)
    with closing(connect(path)) as db:
        yield db, Names(db), path, tmp_path


class Names:
    def __init__(self, db):
        self.db = db

    def part(self, number):
        return item_id(self.db, 'parts', number)

    def set(self, number):
        return item_id(self.db, 'sets', number)

    def colour(self, born):
        return colour_id(self.db, born)

    def line(self, number, born):
        return (self.part(number), self.colour(born))

    def figure(self, number='fig-000004'):
        return (item_id(self.db, 'minifigs', number), None)


def by_set(result):
    return {r['set_item_id']: r for r in result['results']}


# ---------- weights ----------

def test_a_rare_part_weighs_more_than_a_common_one(cat):
    db, n, *_ = cat
    index, _ = S.index_for(db)
    common, rare = S.key_of(*n.line('3001', '4')), S.key_of(*n.line('syn-r1', '4'))
    assert index.weight[rare] == pytest.approx(math.log(index.total / 3))        # 9101, 9106 (through its sub-set), 9107
    assert index.weight[common] == pytest.approx(math.log(index.total / len(index.posting[common][0])))
    assert index.weight[rare] > 2 * index.weight[common] > 0
    # a pile of one rare part ranks the sets that hold it above the sets that only hold common parts
    result = S.score(db, {n.line('syn-r1', '4'): 1})
    assert {r['set_item_id'] for r in result['results']} == {n.set('9101-1'), n.set('9106-1'), n.set('9107-1')}
    # the same pile of 3001 touches many sets, each with less evidence than the rare line gives
    common_result = S.score(db, {n.line('3001', '4'): 4})
    assert common_result['total'] > result['total']
    assert max(r['evidence'] for r in common_result['results']) < min(r['evidence'] for r in result['results'])


def test_distinctive_lines_are_counted_against_the_sets_own(cat, monkeypatch):
    db, n, *_ = cat
    monkeypatch.setattr(S, 'DISTINCTIVE_MAX', 3)                    # on a catalogue this small every line is in few sets
    result = by_set(S.score(db, {n.line('syn-r1', '4'): 1, n.line('3001', '4'): 4}))
    seven = result[n.set('9107-1')]
    assert seven['distinctive_found'] == 1 and seven['distinctive_total'] == 2 and seven['set_lines'] == 3
    assert seven['covered_lines'] == 2 and seven['complete_lines'] == 2


def test_quantities_cover_by_share_and_spares_are_left_out(cat):
    db, n, *_ = cat
    # 9101 needs 3001 red x4 and 3023 white x2; the spare 3023 yellow x5 is no line
    full = by_set(S.score(db, {n.line('3001', '4'): 4, n.line('3023', '15'): 2}))[n.set('9101-1')]
    assert full['set_quantity'] == 4 + 2 + 1 and full['covered_quantity'] == 6 and full['complete_lines'] == 2
    half = by_set(S.score(db, {n.line('3001', '4'): 2}))[n.set('9101-1')]
    assert half['covered_quantity'] == 2 and half['complete_lines'] == 0
    weight = S.index_for(db)[0].weight[S.key_of(*n.line('3001', '4'))]
    assert half['evidence'] == pytest.approx(round(weight * 2 / 4, 4), abs=1e-4)
    yellow = S.score(db, {n.line('3023', '14'): 5})
    assert n.set('9101-1') not in by_set(yellow)                      # the spare does not match
    assert n.set('9104-1') in by_set(yellow)                          # the required yellow 3023 of 9104 does


# ---------- swaps ----------

def test_swaps_are_listed_apart_and_never_counted(cat):
    db, n, *_ = cat
    # 9104 needs 3023 in yellow x3; the pile has 3023 in white. 9105 needs syn-m1 red x2; the pile has its mould twin syn-m2 red x2.
    pile = {n.line('3023', '15'): 3, n.line('syn-m2', '4'): 2, n.line('3001', '4'): 1}
    result = by_set(S.score(db, pile))
    four, five = result[n.set('9104-1')], result[n.set('9105-1')]
    assert four['covered_lines'] == 1 and four['covered_quantity'] == 1            # only the exact 3001 counts
    colour = [s for s in four['swaps']['items'] if s['kind'] == 'colour']
    assert len(colour) == 1 and colour[0]['quantity'] == 3
    assert colour[0]['have']['color_id'] == n.colour('15') and colour[0]['wanted']['color_id'] == n.colour('14')
    assert five['covered_lines'] == 1                                                # the mould twin is no match
    mould = [s for s in five['swaps']['items'] if s['kind'] == 'mould']
    assert len(mould) == 1 and mould[0]['quantity'] == 2 and mould[0]['have']['item_id'] == n.part('syn-m2') and mould[0]['wanted']['item_id'] == n.part('syn-m1')
    # the numbers equal those of a pile without the swap lines
    plain = by_set(S.score(db, {n.line('3001', '4'): 1}))
    for key in ('evidence', 'coverage', 'covered_quantity', 'covered_lines', 'complete_lines', 'distinctive_found'):
        assert four[key] == plain[n.set('9104-1')][key] and five[key] == plain[n.set('9105-1')][key]
    assert plain[n.set('9104-1')]['swaps']['items'] == []
    # a print or pattern relation (type P) is not an alternate mould
    assert not any(s['kind'] == 'mould' for s in result[n.set('9101-1')]['swaps']['items'])


def test_a_swap_uses_only_what_the_exact_match_left_over(cat):
    db, n, *_ = cat
    # the pile has 4 white 3023; 9102 needs 1 white (exact) so 3 are left; 9104 needs 3 yellow: the swap offers min(3, 4) = 3
    # and for 9101 (needs 2 white) a yellow 3023 line in the pile is not a swap target of white (9101 holds no yellow requirement)
    result = by_set(S.score(db, {n.line('3023', '15'): 4, n.line('3001', '4'): 1}))
    assert [s['quantity'] for s in result[n.set('9104-1')]['swaps']['items']] == [3]
    # the exact line of 9101 (3023 white x2) is met in full; there is no yellow requirement to swap into
    assert result[n.set('9101-1')]['swaps']['items'] == []


# ---------- figures and sub-sets ----------

def test_a_figure_counts_through_its_parts_and_as_a_whole_figure(cat):
    db, n, *_ = cat
    three = n.set('9103-1')
    whole = by_set(S.score(db, {n.figure(): 1}))[three]
    assert whole['covered_lines'] == 1 and whole['covered_quantity'] == 1 and whole['complete_lines'] == 0     # the set holds two
    parts = by_set(S.score(db, {n.line('970c03', '0'): 2, n.line('3901', '6'): 2}))[three]                    # through its parts, times two figures
    assert parts['covered_lines'] == 2 and parts['complete_lines'] == 2 and parts['covered_quantity'] == 4
    # lines of the set: 3001, syn-r2, the figure and the figure's four parts
    assert parts['set_lines'] == 7 and parts['set_quantity'] == 2 + 1 + 2 + 8
    both = by_set(S.score(db, {n.figure(): 2, n.line('970c03', '0'): 2}))[three]
    assert both['covered_lines'] == 2 and both['complete_lines'] == 2        # separate lines: each gives its own evidence


def test_a_sub_set_is_expanded_into_its_parent_with_its_quantity(cat):
    db, n, *_ = cat
    six, one = n.set('9106-1'), n.set('9101-1')
    result = by_set(S.score(db, {n.line('3001', '4'): 8, n.line('3023', '15'): 4, n.line('970c22', '4'): 1}))
    assert result[six]['complete_lines'] == 3 and result[six]['covered_quantity'] == 8 + 4 + 1 and result[six]['set_lines'] == 4
    assert result[one]['complete_lines'] == 2                                                         # the sub-set is a set of its own too
    rare = by_set(S.score(db, {n.line('syn-r1', '4'): 2}))                                          # the rare part, twice: one copy of 9101 holds one, two copies two
    assert rare[six]['set_quantity'] > rare[one]['set_quantity'] and rare[six]['covered_quantity'] == 2 and rare[one]['covered_quantity'] == 1
    assert rare[six]['complete_lines'] == rare[one]['complete_lines'] == 1


def test_a_cycle_of_sub_sets_stops(cat):
    rows = S.Rows([(1, [(10, 1, 1)]), (2, [(11, 1, 2)])], subsets=[(1, 2, 1), (2, 1, 1)], key=('cycle',))
    index = S.build_index(rows)
    assert index.total == 2 and index.set_lines[0] == 2 and index.set_lines[1] == 2


# ---------- the answer ----------

def test_the_answer_is_ranked_paged_and_reports_the_unmatched(cat):
    db, n, *_ = cat
    pile = {n.line('3001', '4'): 4, n.line('3023', '15'): 2, n.line('syn-r1', '4'): 1, (n.set('9101-1'), 1): 3}      # the last is no part: unmatched
    result = S.score(db, pile, limit=2)
    assert [r['rank'] for r in result['results']] == [1, 2] and result['total'] > 2
    assert result['results'][0]['set_item_id'] == n.set('9101-1') and result['results'][0]['coverage'] == 1.0
    assert result['results'][0]['evidence'] >= result['results'][1]['evidence']
    assert result['input'] == dict(lines=4, quantity=10, matched_lines=3, unmatched_lines=1, unmatched=result['input']['unmatched'])
    assert result['input']['unmatched'][0]['item_id'] == n.set('9101-1')
    later = S.score(db, pile, limit=2, offset=2)
    assert [r['rank'] for r in later['results']] == [3, 4] and later['results'][0]['set_item_id'] != result['results'][1]['set_item_id']
    assert S.score(db, pile, limit=1, detail=0)['results'][0]['matched'] == []
    for bad in (dict(limit=0), dict(limit=501), dict(offset=-1), dict(detail=101)):
        with pytest.raises(ValueError):
            S.score(db, pile, **bad)
    with pytest.raises(ValueError):
        S.score(db, {n.line('3001', '4'): -1})
    assert S.score(db, {})['results'] == [] and S.score(db, {n.line('3001', '4'): 0})['total'] == 0


def test_flags_pass_through_to_the_matched_lines_and_are_summed_per_flag(cat):
    db, n, *_ = cat
    brick, plate = n.line('3001', '4'), n.line('3023', '15')
    result = by_set(S.score(db, {brick: 4, plate: 2}, {brick: {'sticker', 'old'}, plate: {'sticker'}, n.line('syn-r1', '4'): {'ignored'}}))[n.set('9101-1')]
    marked = {(m['item_id']): m['flags'] for m in result['matched']}
    assert marked[brick[0]] == ['old', 'sticker'] and marked[plate[0]] == ['sticker']
    assert result['flags']['sticker']['lines'] == 2 and result['flags']['sticker']['covered_quantity'] == 6
    assert result['flags']['old']['lines'] == 1 and 'ignored' not in result['flags']
    assert result['flags']['sticker']['evidence'] == pytest.approx(result['evidence'], abs=1e-3)


# ---------- the cache ----------

def test_the_index_and_the_ranking_are_cached_per_build_and_input(cat):
    db, n, path, _ = cat
    pile = {n.line('3001', '4'): 4}
    first = S.score(db, pile)
    second = S.score(db, pile)
    assert second['cached'] and not second['index_built'] and second['results'] == first['results']
    assert not S.score(db, {n.line('3001', '4'): 3})['cached']
    assert [r['rank'] for r in S.score(db, pile, limit=1, offset=1)['results']] == [2]      # a page of the cached ranking


def test_a_new_catalogue_build_replaces_the_index_and_the_cached_results(cat):
    db, n, path, tmp = cat
    pile = {n.line('3001', '4'): 4}
    before = by_set(S.score(db, pile))
    key = S.index_for(db)[0].key
    with closing(sqlite3.connect(tmp / 'catalogue.db')) as other:        # another process rebuilds: a build row and a changed inventory
        other.execute("INSERT INTO build(kind,seeded_from,started_at,finished_at,app_version,files_json,counts_json) "
                      "VALUES('mapping','catalogue','2026-11-11T10:00:00.000Z','2026-11-11T10:01:00.000Z','4.0.test','[]','{}')")
        other.execute('UPDATE inventory_part SET quantity=1 WHERE inventory_id=(SELECT id FROM inventory WHERE item_id=?) AND item_id=?',
                      (n.set('9102-1'), n.part('3001')))
        other.commit()
    after_result = S.score(db, pile)
    assert after_result['index_built'] and not after_result['cached'] and S.index_for(db)[0].key != key
    two = n.set('9102-1')
    assert by_set(after_result)[two]['set_quantity'] == by_set(S.score(db, pile, limit=500))[two]['set_quantity'] == 1 + 1
    assert before[two]['set_quantity'] == 4 + 1


# ---------- the builders of the input ----------

def test_builders_read_a_lot_a_storage_all_loose_stock_and_a_selection(cat):
    db, n, path, _ = cat
    coll = Coll(db)
    shelf = coll.storage('Shelf')
    box = coll.storage('Box', parent_id=shelf)
    lot = coll.lot('Bag', storage_id=box)
    sticker = coll.flag('sticker')
    brick, plate, figure = n.part('3001'), n.part('3023'), item_id(db, 'minifigs', 'fig-000004')
    red, white = n.colour('4'), n.colour('15')
    a = coll.add_stock('part', brick, colour=red, quantity=3, lot=lot, storage=box)
    b = coll.add_stock('part', brick, colour=red, quantity=1, lot=lot, storage=box, condition='new')
    c = coll.add_stock('part', plate, colour=white, quantity=2, storage=shelf)
    d = coll.add_stock('minifigure', figure, quantity=1)
    coll.tag('stock', a, sticker)
    assert S.from_lot(db, lot) == ({(brick, red): 4}, {(brick, red): {'sticker'}})
    assert S.from_storage(db, box)[0] == {(brick, red): 4}
    assert S.from_storage(db, shelf)[0] == {(brick, red): 4, (plate, white): 2}              # the storage and the ones inside it
    assert S.from_storage(db, shelf, below=False)[0] == {(plate, white): 2}
    assert S.from_loose(db)[0] == {(brick, red): 4, (plate, white): 2, (figure, None): 1}    # a loose figure is a whole figure, not its parts
    assert S.from_stock(db, [b, d])[0] == {(brick, red): 1, (figure, None): 1}
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-11-01T00:00:00.000Z', b))
    assert S.from_lot(db, lot)[0] == {(brick, red): 3}
    for call in (lambda: S.from_lot(db, 'none'), lambda: S.from_storage(db, 'none'), lambda: S.from_stock(db, [b])):
        with pytest.raises(ValueError):
            call()
    result = S.score(db, *S.from_lot(db, lot))
    assert result['input']['quantity'] == 3 and result['results'][0]['flags']['sticker']['lines'] == 1


def test_scoring_writes_nothing(cat):
    db, n, path, _ = cat
    before = db.total_changes
    S.score(db, {n.line('3001', '4'): 4})
    assert db.total_changes == before and not db.in_transaction


# ---------- scale ----------

def synthetic_rows(sets=20000, lines=40, parts=12000, colours=40, seed=7):
    """`sets` invented sets of `lines` lines: part popularity is skewed (a few parts are everywhere, most are rare)."""
    rng = random.Random(seed)
    return S.Rows([(1000000 + s, [(int(rng.paretovariate(0.9)) % parts + 1, rng.randint(1, colours), rng.randint(1, 6)) for _ in range(lines)])
                   for s in range(sets)], key=('synthetic',))


def test_twenty_thousand_sets_score_a_two_thousand_line_pile_quickly():
    """A generous bound, not a measurement: the inverted lists make a query touch only the sets that share a line (the real figures are
    in `scripts/bench_set_scoring.py`, on a real catalogue)."""
    started = time.perf_counter()
    index = S.build_index(synthetic_rows())
    built = time.perf_counter() - started
    assert index.total == 20000
    rng = random.Random(3)
    lines = {k: rng.randint(1, 4) for k in rng.sample(sorted(index.posting), 2000)}
    started = time.perf_counter()
    ranked, matched = S.rank(index, lines)
    ranking = time.perf_counter() - started
    assert matched == 2000 and len(ranked) > 1000 and ranked[0][1] >= ranked[-1][1]
    started = time.perf_counter()
    for row in ranked[:20]:
        S._detail(index, row, lines, {}, 10)
    detail = time.perf_counter() - started
    assert built < 30 and ranking < 10 and detail < 10, (built, ranking, detail)
