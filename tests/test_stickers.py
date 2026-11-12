"""Stickers on loose parts (#201): the flag at filing, the candidate sets of a part line, "This one", "Keep as a hint", "Not a sticker", Undo, and the evidence
rule in the scoring engine and in Lot Detective (`tests/stickers_world.py` holds the invented sets)."""
import pytest

from brickwork.core import candidate_sets as C, errors, set_scoring as S, stickers, undo
from tests.stickers_world import DUMP, RED, World, coll, db, pair, world  # noqa: F401 (fixtures)


def numbers(answer):
    return [r['set_number'] for r in answer['results']]


# ---------- the candidates ----------

def test_the_candidates_are_the_live_sets_that_hold_the_part_in_the_colour_and_a_sticker_sheet(db, world):
    answer = stickers.candidates(db, world.lot, world.line, limit=20)
    # 9401 and 9408 (sheet A, with a picture) first, then the rest by year; 9402, 9406 (its latest inventory has no tile: out), 9403 and 9407 (no sheet), 9404 (white tile), 9405 (spare sheet) are not here
    assert numbers(answer) == ['9401-1', '9408-1', '9402-1', '9451-1', '9452-1', '9453-1'] and answer['total'] == 6
    first = answer['results'][0]
    assert (first['sheet_number'], first['sheet_name'], first['year'], first['set_name']) == ('stk-sheet-a', 'Stk sheet-a', 2001, 'Stk Set 9401')
    assert first['sheet_picture'] == 'https://img.invalid/sheet-a.jpg' and answer['results'][2]['sheet_picture'] is None, 'sheets without a picture sort last'
    two = next(r for r in answer['results'] if r['set_number'] == '9408-1')
    assert two['sheet_number'] == 'stk-sheet-a', 'a set with two sheets is one row, the lower number first'


def test_paging_and_the_line_must_be_a_part_of_the_lot(db, world, coll):
    assert numbers(stickers.candidates(db, world.lot, world.line, limit=1, offset=1)) == ['9408-1']
    with pytest.raises(ValueError, match='limit'):
        stickers.candidates(db, world.lot, world.line, limit=0)
    other = coll.lot('Another lot')
    with pytest.raises(errors.NotFound):
        stickers.candidates(db, other, world.line)
    with pytest.raises(errors.NotFound):
        stickers.candidates(db, world.lot, 'no-such-line')


def test_a_white_tile_has_its_own_candidates(db, coll):
    lot = coll.lot('White lot')
    white = coll.add_stock('part', coll.item('parts', 'stk-tile'), colour=coll.colour('15'), quantity=1, condition='used', lot=lot)
    assert numbers(stickers.candidates(db, lot, white)) == ['9404-1']


# ---------- the writes ----------

def test_confirm_is_one_undoable_event_and_choosing_again_writes_nothing(db, world):
    world.flag()
    a, sheet = world.set('9401-1'), world.sheet('sheet-a')
    done = stickers.confirm(db, world.lot, world.line, a, sheet)
    assert done['changed'] and stickers.decision(db, world.line)['set_number'] == '9401-1'
    event = db.execute('SELECT * FROM event WHERE id=?', (done['event_id'],)).fetchone()
    assert (event['entity_kind'], event['entity_id'], event['field']) == ('stock_sticker', world.line, 'confirm')
    assert stickers.confirm(db, world.lot, world.line, a, sheet) == dict(event_id=done['event_id'], changed=False)
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='stock_sticker'").fetchone()[0] == 1
    undo.undo_event(db, done['event_id'])
    assert stickers.decision(db, world.line) is None
    assert undo.undo_event(db, done['event_id'])['already_undone'] is True


def test_changing_the_choice_and_undoing_it_shows_the_earlier_choice(db, world):
    world.flag()
    first = stickers.confirm(db, world.lot, world.line, world.set('9401-1'), world.sheet('sheet-a'))
    second = stickers.confirm(db, world.lot, world.line, world.set('9402-1'), world.sheet('sheet-b'))
    assert stickers.decision(db, world.line)['set_number'] == '9402-1'
    undo.undo_event(db, second['event_id'])
    assert stickers.decision(db, world.line)['event_id'] == first['event_id']


def test_confirm_refuses_what_is_not_a_candidate_and_a_part_without_the_flag(db, world):
    with pytest.raises(errors.Conflict, match='sticker'):
        stickers.confirm(db, world.lot, world.line, world.set('9401-1'), world.sheet('sheet-a'))
    world.flag()
    for bad in ((world.set('9403-1'), world.sheet('sheet-a')), (world.set('9401-1'), world.sheet('sheet-b')), (world.set('9404-1'), world.sheet('sheet-c'))):
        with pytest.raises(ValueError, match='Choose one of the sets'):
            stickers.confirm(db, world.lot, world.line, *bad)
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='stock_sticker'").fetchone()[0] == 0


def test_not_a_sticker_removes_the_flag_and_the_confirmation_and_undo_brings_both_back(db, world):
    world.flag()
    stickers.confirm(db, world.lot, world.line, world.set('9401-1'), world.sheet('sheet-a'))
    done = stickers.clear(db, world.lot, world.line)
    assert done['changed'] and stickers.states(db, [world.line])[world.line] == dict(flagged=False, confirmed=None)
    assert stickers.decision(db, world.line) is None
    assert stickers.clear(db, world.lot, world.line) == dict(event_id=None, changed=False)
    undo.undo_event(db, done['event_id'])
    state = stickers.states(db, [world.line])[world.line]
    assert state['flagged'] and state['confirmed']['set_number'] == '9401-1'


def test_a_confirmation_counts_only_while_the_part_holds_the_flag(db, world, coll):
    world.flag()
    stickers.confirm(db, world.lot, world.line, world.set('9401-1'), world.sheet('sheet-a'))
    db.execute('DELETE FROM stock_flag WHERE stock_id=?', (world.line,))
    db.commit()
    assert stickers.states(db, [world.line])[world.line]['confirmed'] is None
    parts, flags = S.from_lot(db, world.lot)
    assert not any(n.startswith('sticker') for names in flags.values() for n in names)


def test_keep_as_a_hint_writes_nothing_so_the_flag_stays_open(db, world):
    world.flag()
    before = db.execute('SELECT count(*) FROM event').fetchone()[0]
    assert stickers.states(db, [world.line])[world.line] == dict(flagged=True, confirmed=None)
    assert db.execute('SELECT count(*) FROM event').fetchone()[0] == before


# ---------- the evidence rule ----------

def order(db, lot):
    return numbers_of(C.candidates(db, lot, min_score=0, ignore_common=False, limit=100))


def numbers_of(answer):
    return [r['set_item_id'] for r in answer['results']]


def evidence(db, lot, number, item):
    return next(r['evidence'] for r in C.candidates(db, lot, min_score=0, ignore_common=False, limit=100)['results'] if r['set_item_id'] == item(number))


def test_an_unconfirmed_sticker_raises_only_the_sets_that_hold_the_part_and_a_sheet_and_by_at_most_half_the_line(db, coll):
    lot = World(coll, flag=False, rare=False)
    plain = {n: evidence(db, lot.lot, n, lot.set) for n in ('9401-1', '9407-1', '9402-1')}
    assert plain['9401-1'] == plain['9407-1'], 'the same tile line, nothing else in the lot'
    lot.flag()
    hinted = {n: evidence(db, lot.lot, n, lot.set) for n in plain}
    assert hinted['9407-1'] == plain['9407-1'], 'no sheet in the set: nothing extra'
    lifted = hinted['9401-1'] - plain['9401-1']
    assert lifted == pytest.approx(plain['9401-1'] * (S.HINT_FACTOR - 1), abs=2e-4) and 0 < lifted <= plain['9401-1'] * 0.5
    ordered = order(db, lot.lot)
    assert ordered.index(lot.set('9401-1')) < ordered.index(lot.set('9407-1')), 'the set with a sheet now outranks the one without'


def test_a_confirmed_sticker_is_near_certain_evidence_for_its_set_only(db, coll):
    lot = World(coll, flag=True)
    stickers.confirm(db, lot.lot, lot.line, lot.set('9402-1'), lot.sheet('sheet-b'))
    answer = C.candidates(db, lot.lot, min_score=0, ignore_common=False, limit=100)
    first = answer['results'][0]
    assert first['set_item_id'] == lot.set('9402-1') and first['score'] == 100 and first['reasons'][0] == 'sticker of set 9402-1 confirmed'
    index, _ = S.index_for(db)
    import math
    assert first['evidence'] == pytest.approx(S.CONFIRMED_FACTOR * math.log(index.total), abs=1e-3)
    rest = {r['set_item_id']: r for r in answer['results'][1:]}
    assert all(not r['reasons'][0].startswith('sticker of set') for r in rest.values())
    assert rest[lot.set('9403-1')]['evidence'] < first['evidence'], 'the rare part of 9403 no longer wins'


def test_without_the_confirmation_the_rare_part_wins_and_the_cache_never_returns_a_stale_order(db, coll):
    lot = World(coll, flag=False)
    assert order(db, lot.lot)[0] == lot.set('9403-1')
    lot.flag()
    stickers.confirm(db, lot.lot, lot.line, lot.set('9401-1'), lot.sheet('sheet-a'))
    assert order(db, lot.lot)[0] == lot.set('9401-1')
    stickers.clear(db, lot.lot, lot.line)
    assert order(db, lot.lot)[0] == lot.set('9403-1'), 'the same parts again, the flag gone: the first order'


def test_a_flagged_line_is_never_dropped_as_common(db, coll):
    lot = World(coll, flag=True)
    coll.setting(C.SETTING_KEY, '25')
    answer = C.candidates(db, lot.lot, min_score=0, limit=100)
    assert answer['input']['ignored_common_lines'] == 0, 'the tile is held by more than 25 sets, but it carries the sticker flag'
    stickers.clear(db, lot.lot, lot.line)
    assert C.candidates(db, lot.lot, min_score=0, limit=100)['input']['ignored_common_lines'] == 1


def test_the_engine_reads_a_flag_named_sticker_in_any_case_and_set_scores_apply_the_rule(db, world, coll):
    world.flag()
    db.execute("UPDATE flag SET name='STICKER' WHERE name='Sticker'")
    db.commit()
    stickers.confirm(db, world.lot, world.line, world.set('9402-1'), world.sheet('sheet-b'))
    parts, flags = S.from_lot(db, world.lot)
    answer = S.score(db, parts, flags, limit=3)
    assert answer['results'][0]['set_item_id'] == world.set('9402-1')
    shown = answer['results'][0]['matched'][0]['flags'] if answer['results'][0]['matched'] else []
    assert all(not f.startswith('sticker:') for f in shown), 'a confirmation is not a flag a person sees'


def test_unit_the_extra_of_a_line():
    class Index:
        total = 100
        set_item = [10, 11]
        set_sticker = [1, 0]
    assert S.sticker_extra(Index, 0, 2.0, frozenset()) == pytest.approx(2.0 * (S.HINT_FACTOR - 1))
    assert S.sticker_extra(Index, 1, 2.0, frozenset()) == 0.0
    assert S.HINT_FACTOR <= 1.5
    import math
    assert S.sticker_extra(Index, 0, 2.0, frozenset({10})) == pytest.approx(S.CONFIRMED_FACTOR * math.log(100) - 2.0)
    assert S.sticker_extra(Index, 1, 2.0, frozenset({10})) == 0.0


# ---------- review fixes ----------

def test_confirm_projects_the_set_and_the_sheet_into_the_collection_so_a_rebuild_keeps_their_ids(db, world):
    world.flag()
    a, sheet = world.set('9401-1'), world.sheet('sheet-a')
    held = lambda: {r[0] for r in db.execute('SELECT id FROM main.item WHERE id IN (?,?)', (a, sheet))}          # noqa: E731
    assert held() == set()
    stickers.confirm(db, world.lot, world.line, a, sheet)
    assert held() == {a, sheet}


def test_undoing_an_older_not_a_sticker_is_refused_while_a_later_change_is_active(db, world):
    world.flag()
    first = stickers.clear(db, world.lot, world.line)
    world.flag()                                    # another piece of the same stock row is filed with the switch on
    second = stickers.clear(db, world.lot, world.line)
    assert not stickers.states(db, [world.line])[world.line]['flagged']
    with pytest.raises(errors.UndoBlocked, match='undo the later change first'):
        undo.undo_event(db, first['event_id'])
    assert not stickers.states(db, [world.line])[world.line]['flagged'], 'nothing was restored'
    undo.undo_event(db, second['event_id'])
    undo.undo_event(db, first['event_id'])
    assert stickers.states(db, [world.line])[world.line]['flagged']
