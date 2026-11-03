"""Scoped detail matching (L6) on the 4.0 store (M.8e, issue #110): the item page's matches are the whole-store reads', from fewer rows.

Rewritten from the 3.3 file: its fixture is built on `tests/app4.py` (sets 1000-1 and 1000-2 of the rich fixture catalogue, several copies
with gaps, loose stock and a loose figure that misses a part). The 3.3 file's price-decoration helper (L5) had no test left and went.
"""
import json

import pytest

from brickwork.core import collection, workbench as w
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


@pytest.fixture
def store(coll):
    """Four live copies of 1000-1 (c1 with two gaps and a figure, c2 checked with its single gap, c3 whole), one archived, one of 1000-2."""
    ids = {}
    checked = coll.flag('Set is checked', 'status')
    coll.add_copy('1000-1', completeness='incomplete', completeness_source='derived')
    ids['c0'] = coll.db.execute('SELECT id FROM copy ORDER BY created_at DESC LIMIT 1').fetchone()[0]
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', ('2026-01-01', ids['c0']))
    for name, set_key in (('c1', '1000-1'), ('c2', '1000-1'), ('c3', '1000-1'), ('c4', '1000-2')):
        ids[name] = coll.add_copy(set_key, completeness='incomplete', completeness_source='derived')
    coll.tag('copy', ids['c2'], checked)
    coll.mark(ids['c1'], '3001', '4', missing=2)
    coll.mark(ids['c1'], '3023', '15', missing=1)
    coll.mark_figure(ids['c1'], 'fig-000004', missing=1)
    coll.mark(ids['c2'], '3001', '4', missing=1)
    coll.mark(ids['c4'], '3023', '15', missing=1)
    brick, plate, figure = coll.item('parts', '3001'), coll.item('parts', '3023'), coll.item('minifigs', 'fig-000004')
    red, white = coll.colour('4'), coll.colour('15')
    stock = dict(
        st1=coll.add_stock('part', brick, colour=red, quantity=5, condition='used'),
        st2=coll.add_stock('part', brick, colour=red, quantity=1, condition='new'),
        st3=coll.add_stock('part', plate, colour=white, quantity=2, condition='used'),
        st4=coll.add_stock('minifigure', figure, quantity=1, condition='used'),
        st5=coll.add_stock('part', plate, colour=white, quantity=1, condition='damaged'))
    part = coll.db.execute('SELECT id,item_id,color_id FROM stock_part WHERE stock_id=? ORDER BY id', (stock['st4'],)).fetchone()
    coll.sql('UPDATE stock_part SET missing=1 WHERE id=?', (part['id'],))
    stock['st6'] = coll.add_stock('part', part['item_id'], colour=part['color_id'], quantity=3, condition='used')
    stock['st7'] = coll.add_stock('minifigure', figure, quantity=1, condition='new')                  # a sound loose figure for the missing one
    return dict(ids=ids, stock=stock, brick=brick, plate=plate, figure=figure, red=red, white=white)


def key(match):
    return tuple(match[k] for k in ('target', 'target_id', 'copy_id', 'source_id', 'have', 'suggested', 'completes', 'key'))


def reference_matches(db, item_id, kind, colour, selected):
    """The whole-store computation the detail page would otherwise do."""
    every = w.gaps(db)
    found = w.matches(db, all_gaps=every)
    if selected and selected['entity'] == 'stock' and kind == 'minifigure':
        found = [r for r in found if (r['target'] == 'stock-part' and r['copy_id'] == selected['id']) or r['key'] == (item_id, colour)]
    elif kind == 'set' and selected and selected['entity'] == 'copy':
        found = [r for r in found if r['copy_id'] == selected['id']]
    else:
        found = [r for r in found if r['key'] == (item_id, colour)]
    if kind in ('part', 'minifigure'):
        left, _ = w.completion_context(db, every)
        found = sorted(found, key=lambda r: (not r['completes'], sum(left[r['copy_id']].values()) if r['copy_id'] in left else 0))
    return found


def cases(s, coll):
    set_a, set_b = coll.item('sets', '1000-1'), coll.item('sets', '1000-2')
    return [('set', set_a, None, dict(copy_id=s['ids']['c1'])), ('set', set_a, None, dict(copy_id=s['ids']['c2'])), ('set', set_a, None, dict(copy_id=s['ids']['c3'])),
            ('set', set_a, None, {}), ('set', set_b, None, dict(copy_id=s['ids']['c4'])),
            ('part', s['brick'], s['red'], {}), ('part', s['plate'], s['white'], {}),
            ('minifigure', s['figure'], None, {}), ('minifigure', s['figure'], None, dict(stock_id=s['stock']['st4']))]


def test_detail_matches_equal_the_whole_store_computation(store, coll):
    with_matches = 0
    for kind, item, colour, which in cases(store, coll):
        detail = collection.detail(coll.db, item, colour=colour, **which)
        expected = reference_matches(coll.db, item, kind, colour, detail['selected'])
        assert [key(m) for m in detail['matches']] == [key(m) for m in expected], (kind, item, which)
        with_matches += bool(expected)
    assert with_matches >= 5


def test_fixture_reaches_the_interesting_cases(store, coll):
    db, ids = coll.db, store['ids']
    c1 = collection.detail(db, coll.item('sets', '1000-1'), copy_id=ids['c1'])
    c2 = collection.detail(db, coll.item('sets', '1000-1'), copy_id=ids['c2'])
    part = collection.detail(db, store['brick'], colour=store['red'])['matches']
    figure = collection.detail(db, store['figure'], stock_id=store['stock']['st4'])
    assert {m['target'] for m in c1['matches']} >= {'part', 'figure'} and not any(m['completes'] for m in c1['matches'])
    assert any(m['completes'] for m in c2['matches']), 'single gap, checked copy, enough stock'
    assert len({m['source_id'] for m in part}) == 2 and any(m['completes'] for m in part)
    assert any(m['target'] == 'stock-part' for m in figure['matches'])
    assert any(line['can_take'] for line in c1['consists'])


def test_scoped_gaps_are_the_whole_store_gaps_of_the_relevant_copies_in_order(store, coll):
    db = coll.db
    every = w.gaps(db)
    assert len(every) >= 6
    for kind, item, colour, copies, stocks in (('part', store['brick'], store['red'], (), ()), ('part', store['plate'], store['white'], (), ()),
                                               ('set', coll.item('sets', '1000-1'), None, (store['ids']['c1'],), ()),
                                               ('minifigure', store['figure'], None, (), (store['stock']['st4'],)),
                                               ('set', coll.item('sets', '1000-2'), None, (store['ids']['c4'],), ())):
        copy_scope, stock_scope = w.relevant(db, item, colour, kind, copy_ids=copies, stock_ids=stocks)
        scoped = w.gaps(db, only=(copy_scope, stock_scope))
        expected = [g for g in every if (g['target'] == 'stock-part' and g['copy_id'] in stock_scope) or (g['target'] != 'stock-part' and g['copy_id'] in copy_scope)]
        assert json.dumps(scoped, default=str, sort_keys=True) == json.dumps(expected, default=str, sort_keys=True), (kind, item)


def test_matches_ignore_stock_without_a_gap_but_otherwise_agree(store, coll):
    used = {m['source_id'] for m in w.matches(coll.db)}
    assert store['stock']['st5'] not in used, 'a damaged row is not offered'
    assert {store['stock'][n] for n in ('st1', 'st2', 'st3', 'st6', 'st7')} <= used and store['stock']['st4'] not in used


def test_detail_reads_scoped_gaps_only(store, coll, monkeypatch):
    calls = []
    real = w.gaps
    monkeypatch.setattr(w, 'gaps', lambda db, only=None: calls.append(only is not None) or real(db, only))
    for kind, item, colour, which in cases(store, coll):
        del calls[:]
        collection.detail(coll.db, item, colour=colour, **which)
        assert calls == [True], (kind, item)


def test_detail_cost_does_not_grow_with_the_number_of_copies(store, coll):
    db = coll.db
    item, colour = store['brick'], store['red']

    def statements():
        seen = []
        db.set_trace_callback(seen.append)
        collection.detail(db, item, colour=colour)
        db.set_trace_callback(None)
        return len(seen)
    few = statements()
    for _ in range(40):
        copy = coll.add_copy('1000-1', completeness='incomplete', completeness_source='derived')
        coll.mark(copy, '3001', '4', missing=1)
    assert statements() <= few + 12, 'matches are decorated in batches, not per match'
