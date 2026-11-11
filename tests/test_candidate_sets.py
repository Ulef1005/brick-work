"""Lot Detective, the service (#200): `core/candidate_sets.py` on a lot made of two known sets plus noise, on the fixture catalogue plus invented sets.

Sets (all `det`, invented): `9201-1` (theme Pirates 601, 2001, 120 parts) holds the rare parts a1 to a4, the printed part a5 and the common part c; `9202-1`
(theme Sub Castle 602, a child of Castle 600, 2005, 400 parts) holds b1 to b3 and c; `9203-1` (Pirates, 1999, 30 parts) is a decoy that holds a1 and c; 32
noise sets (`9210-1` to `9241-1`, Castle, 2010) hold only c, so c is held by 35 sets (common above N = 25) while every rare part is in one or two."""
from contextlib import closing

import pytest

from brickwork.core import candidate_sets as C, set_scoring as S
from brickwork.core.connect import connect
from tests.app4 import Coll, make_pair

PARTS = ['a1', 'a2', 'a3', 'a4', 'a5pr0001', 'b1', 'b2', 'b3', 'c']
DET = {
    'themes': [[600, 'Castle', ''], [601, 'Pirates', ''], [602, 'Sub Castle', 600]],
    'parts': [[f'det-{p}', f'Det {p}', 14, 'Plastic'] for p in PARTS],
    'sets': [['9201-1', 'Det Set A', 2001, 601, 120, ''], ['9202-1', 'Det Set B', 2005, 602, 400, ''], ['9203-1', 'Det Decoy', 1999, 601, 30, '']]
            + [[f'92{n}-1', f'Det Noise {n}', 2010, 600, 50, ''] for n in range(10, 42)],
    'inventories': [[9301, 1, '9201-1'], [9302, 1, '9202-1'], [9303, 1, '9203-1']] + [[9310 + n, 1, f'92{10 + n}-1'] for n in range(32)],
    'inventory_parts': (
        [[9301, f'det-{p}', 4, 1, 'False', ''] for p in ('a1', 'a2', 'a3', 'a4', 'a5pr0001')] + [[9301, 'det-c', 4, 1, 'False', '']]
        + [[9302, f'det-{p}', 4, 1, 'False', ''] for p in ('b1', 'b2', 'b3', 'c')]
        + [[9303, 'det-a1', 4, 1, 'False', ''], [9303, 'det-c', 4, 1, 'False', '']]
        + [[9310 + n, 'det-c', 4, 1, 'False', ''] for n in range(32)]),
    'part_relationships': [['P', 'det-b1', 'det-b2']],      # b1 has no print suffix; the catalogue lists it as the printed child of b2
}
RED = '4'


@pytest.fixture
def pair(tmp_path):
    return make_pair(tmp_path, extra_dump=DET)


@pytest.fixture
def db(pair):
    with closing(connect(pair)) as db:
        yield db


@pytest.fixture
def coll(db):
    return Coll(db)


class Lot:
    """A lot of a few parts of the invented sets, and what they are called."""

    def __init__(self, coll, parts):
        self.coll = coll
        self.id = coll.lot('Detective lot')
        self.stock = {}
        for number, quantity in parts.items():
            self.stock[number] = coll.add_stock('part', self.part(number), colour=coll.colour(RED), quantity=quantity, condition='used', lot=self.id)

    def part(self, number):
        return self.coll.item('parts', 'det-' + number)

    def set(self, number):
        return self.coll.item('sets', number)


@pytest.fixture
def lot(coll):
    # the parts of A (a1 to a3 and the printed a5), the parts of B, and the common c as noise
    return Lot(coll, {'a1': 1, 'a2': 1, 'a3': 1, 'a5pr0001': 1, 'b1': 1, 'b2': 1, 'b3': 1, 'c': 5})


def ids(answer):
    return [r['set_item_id'] for r in answer['results']]


def test_both_known_sets_rank_first_with_reasons(db, lot):
    answer = C.candidates(db, lot.id)
    a, b, decoy = lot.set('9201-1'), lot.set('9202-1'), lot.set('9203-1')
    assert ids(answer)[:3] == [a, b, decoy]
    first, second, third = answer['results'][:3]
    assert (first['rank'], first['score']) == (1, 100) and 0 < second['score'] < 100 and third['score'] < second['score']
    assert first['reasons'] == ['4 of 5 distinctive parts found', '1 printed part only in this set', '2 other parts only in this set',
                                '5 of 6 part lines of the set are in the lot']
    assert second['reasons'] == ['3 of 3 distinctive parts found', '1 printed part only in this set', '2 other parts only in this set',
                                 '4 of 4 part lines of the set are in the lot']
    assert third['reasons'] == ['1 of 1 distinctive parts found', '2 of 2 part lines of the set are in the lot']
    assert answer['input']['ignored_common_lines'] == 0 and answer['common_max'] == 300


def test_distinctive_parts_found_and_not_found(db, lot):
    first = C.candidates(db, lot.id)['results'][0]
    found = {(p['item_id']): p for p in first['distinctive_found_parts']}
    assert set(found) == {lot.part(n) for n in ('a1', 'a2', 'a3', 'a5pr0001')}
    assert found[lot.part('a5pr0001')]['printed'] and found[lot.part('a5pr0001')]['only_in_set']
    assert not found[lot.part('a2')]['printed'] and found[lot.part('a2')]['only_in_set'] and not found[lot.part('a1')]['only_in_set']
    missing = first['distinctive_missing_parts']
    assert [p['item_id'] for p in missing] == [lot.part('a4')] and missing[0]['quantity'] == 0 and missing[0]['need'] == 1


def test_a_missing_distinctive_part_is_listed_and_counted(db, coll):
    lot = Lot(coll, {'a2': 1, 'a3': 1})
    top = C.candidates(db, lot.id)['results'][0]
    assert top['set_item_id'] == lot.set('9201-1') and top['distinctive_found'] == 2 and top['distinctive_total'] == 5
    assert top['reasons'][0] == '2 of 5 distinctive parts found' and len(top['distinctive_missing_parts']) == 3


def test_a_part_with_a_print_relation_is_printed_too(db, lot):
    assert C.printed(db, {lot.part(n) for n in ('a1', 'a5pr0001', 'b1', 'b2')}) == {lot.part('a5pr0001'), lot.part('b1')}


def test_scores_are_whole_numbers_relative_to_the_best_candidate(db, lot):
    results = C.candidates(db, lot.id)['results']
    assert all(type(r['score']) is int and 0 <= r['score'] <= 100 for r in results)
    assert results[0]['evidence'] >= results[1]['evidence'] and results[0]['score'] == 100
    assert results[1]['score'] == round(100 * results[1]['evidence'] / results[0]['evidence'])


def test_min_score_theme_year_and_size_filters(db, lot):
    a, b, decoy = lot.set('9201-1'), lot.set('9202-1'), lot.set('9203-1')
    everything = C.candidates(db, lot.id)
    assert everything['total'] >= 3
    cut = everything['results'][1]['score']
    assert ids(C.candidates(db, lot.id, min_score=cut)) == [a, b]
    assert ids(C.candidates(db, lot.id, min_score=cut + 1)) == [a]
    # theme by name or id; Castle (600) includes its child Sub Castle, and the noise sets
    castle = ids(C.candidates(db, lot.id, theme='castle'))
    assert b in castle and a not in castle and decoy not in castle
    pirates = C.candidates(db, lot.id, theme='Pirates')
    assert ids(pirates) == [a, decoy] and pirates['results'][0]['score'] == 100             # the best of the filtered sets scores 100
    assert ids(C.candidates(db, lot.id, theme='602')) == [b] and C.candidates(db, lot.id, theme='602')['results'][0]['score'] == 100
    with pytest.raises(ValueError, match='No such theme'):
        C.candidates(db, lot.id, theme='Nonexistent')
    assert ids(C.candidates(db, lot.id, year_from=2001, year_to=2005)) == [a, b]
    assert ids(C.candidates(db, lot.id, year_to=2000)) == [decoy]
    assert ids(C.candidates(db, lot.id, parts_min=100, parts_max=200)) == [a]
    assert ids(C.candidates(db, lot.id, parts_min=300))[0] == b


def test_ignore_common_parts_drops_lines_held_by_more_than_n_sets(db, coll, lot):
    # c is held by 35 sets: with N = 25 it is dropped before scoring, so the 32 noise sets share no line with the lot any more
    noise = {coll.item('sets', f'92{n}-1') for n in range(10, 42)}
    kept = C.candidates(db, lot.id, limit=100)
    assert noise <= set(ids(kept)) and kept['input']['ignored_common_lines'] == 0
    coll.setting(C.SETTING_KEY, '25')
    assert C.common_max(db) == 25
    dropped = C.candidates(db, lot.id, limit=100)
    assert dropped['input']['ignored_common_lines'] == 1 and dropped['common_max'] == 25 and not noise & set(ids(dropped))
    assert dropped['input']['lines'] == kept['input']['lines'] - 1
    assert ids(dropped)[:3] == [lot.set('9201-1'), lot.set('9202-1'), lot.set('9203-1')]
    everyone = C.candidates(db, lot.id, ignore_common=False, limit=100)
    assert noise <= set(ids(everyone)) and everyone['common_max'] is None


def test_the_setting_is_read_with_a_default_and_validated(db, coll):
    assert C.common_max(db) == 300
    for bad in ('x', '24', '-5', ''):
        coll.setting(C.SETTING_KEY, bad)
        assert C.common_max(db) == 300
    coll.setting(C.SETTING_KEY, '1000')
    assert C.common_max(db) == 1000
    assert C.valid_common_max(25) == 25
    for bad in (24, 0, True, '300', 2.5, None):
        with pytest.raises(ValueError):
            C.valid_common_max(bad)


def test_paging_runs_after_the_filters(db, lot):
    page = C.candidates(db, lot.id, limit=1, offset=1)
    assert page['total'] >= 3 and len(page['results']) == 1 and page['results'][0]['rank'] == 2
    assert page['results'][0]['set_item_id'] == lot.set('9202-1')
    assert C.candidates(db, lot.id, offset=500)['results'] == []
    for bad in ({'limit': 0}, {'limit': 101}, {'offset': -1}):
        with pytest.raises(ValueError):
            C.candidates(db, lot.id, **bad)


def test_a_sticker_flag_is_passed_through_to_the_engine(db, coll, lot):
    coll.tag('stock', lot.stock['a2'], coll.flag('Sticker'))
    coll.tag('stock', lot.stock['a3'], coll.flag('Other'))
    top = C.candidates(db, lot.id)['results'][0]
    assert top['flags'] == {'sticker': dict(lines=1, covered_quantity=1, evidence=top['flags']['sticker']['evidence'])} and top['flags']['sticker']['evidence'] > 0
    assert C.candidates(db, lot.id, theme='602')['results'][0]['flags'] == {}


def test_a_lot_that_changes_ranks_again(db, coll, lot):
    before = C.candidates(db, lot.id)
    assert S._RESULTS
    coll.add_stock('part', lot.part('a4'), colour=coll.colour(RED), quantity=1, condition='used', lot=lot.id)
    after = C.candidates(db, lot.id)
    assert after['results'][0]['distinctive_found'] == before['results'][0]['distinctive_found'] + 1
    assert after['results'][0]['distinctive_missing_parts'] == []


def test_an_unknown_or_empty_lot(db, coll):
    with pytest.raises(ValueError, match='No such lot'):
        C.candidates(db, 'none')
    empty = C.candidates(db, coll.lot('Empty'))
    assert empty['total'] == 0 and empty['results'] == [] and empty['input']['lines'] == 0
