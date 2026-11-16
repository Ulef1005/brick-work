"""Found in uses the shared scoring index and the collection's live holders."""
from brickwork.core import errors, set_scoring as S, stock as stock_core, supersets
from brickwork.core.transaction import transaction
from tests.app4 import app4, client, coll, pair, world  # noqa: F401
from tests.test_set_scoring import cat, SYN  # noqa: F401
import pytest


def test_catalogue_colour_quantity_order_and_filters(cat):
    db, n, *_ = cat
    part, colour = n.line('3001', '4')
    result = supersets.found_in(db, part, colour)
    assert result['counts']['sets'] >= 7
    assert result['total'] == result['counts']['sets']
    assert [r['year'] or 0 for r in result['results']] == sorted([r['year'] or 0 for r in result['results']], reverse=True)
    one = supersets.found_in(db, part, colour, search='9106-1')['results']
    assert len(one) == 1 and one[0]['quantity'] == 8  # sub-set expansion
    assert not supersets.found_in(db, part, colour, type='minifigures')['results']
    assert supersets.found_in(db, part, colour, sort='oldest')['results'][0]['year'] <= result['results'][0]['year']


def test_figures_and_spares(cat):
    db, n, *_ = cat
    part, colour = n.line('970c03', '0')
    result = supersets.found_in(db, part, colour, type='minifigures')
    assert result['total'] and all(r['kind'] == 'minifigure' for r in result['results'])
    assert all(r['quantity'] == 1 for r in result['results'])
    assert n.set('9101-1') not in {r['item_id'] for r in supersets.found_in(db, *n.line('3023', '14'))['results']}


def test_unknown_colour_no_match_and_validation(cat):
    db, n, *_ = cat
    with pytest.raises(errors.NotFound):
        supersets.found_in(db, n.part('3001'), 999999)
    empty = supersets.found_in(db, *n.line('syn-r1', '15'))
    assert empty['total'] == 0 and not empty['colour_unmatched']
    for options in ({'type': 'parts'}, {'sort': 'bogus'}, {'limit': 0}, {'offset': -1}):
        with pytest.raises(errors.ValidationFailed):
            supersets.found_in(db, *n.line('3001', '4'), **options)


def test_owned_first_storage_loose_figures_and_no_duplicate_catalogue(world, coll):
    storage = coll.storage('Alex')
    copy = coll.add_copy('1000-1', storage=storage)
    figure = coll.item('minifigs', 'fig-000004')
    with transaction(coll.db):
        stock = stock_core.add_loose(coll.db, item_id=figure, quantity=2, condition='used', storage_id=storage)['id']
    part, colour = coll.item('parts', '970c03'), coll.colour('0')
    result = supersets.found_in(coll.db, part, colour)
    owned = [r for r in result['results'] if r['owned']]
    assert {r.get('copy_id') for r in owned} >= {copy}
    loose = next(r for r in owned if r.get('stock_id') == stock)
    assert loose['label'] == 'loose' and loose['storage_name'] == 'Alex' and loose['quantity'] == 2
    assert result['results'][:len(owned)] == owned
    assert not any(r['group'] == 'catalogue' and r['item_id'] in {i['item_id'] for i in owned} for r in result['results'])
    filtered = supersets.found_in(coll.db, part, colour, search='no such holder')
    assert filtered['total'] == filtered['owned_count'] == 0
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-01-01', stock))
    assert not any(r.get('stock_id') == stock for r in supersets.found_in(coll.db, part, colour)['results'])


def test_common_part_true_count_and_disjoint_pages(cat, monkeypatch):
    db, n, *_ = cat
    # Repeated synthetic candidates exercise paging without manufacturing thousands of DB rows.
    index = S.build_index(S.Rows([(i, [(n.part('3001'), n.colour('4'), 2)]) for i in range(1, 6019)],
        figure_parts=[(i, [(n.part('3001'), n.colour('4'), 1)]) for i in range(6019, 6231)]))
    monkeypatch.setattr(S, 'index_for', lambda db: (index, False))
    # Supply identities for the synthetic index through the normal decorator boundary.
    def decorate(db, rows):
        return [dict(r, kind='set' if r['item_id'] <= 6018 else 'minifigure', name='Sam', number_text=str(r['item_id'])) for r in rows]
    monkeypatch.setattr(supersets.collection, 'decorate', decorate)
    a = supersets.found_in(db, *n.line('3001', '4'))
    b = supersets.found_in(db, *n.line('3001', '4'), offset=15)
    assert a['total'] == 6230 and a['counts'] == dict(sets=6018, minifigures=212)
    assert len(a['results']) == len(b['results']) == 15
    assert not {r['item_id'] for r in a['results']} & {r['item_id'] for r in b['results']}


def test_colour_unmatched_and_standalone_figure_index(cat, monkeypatch):
    db, n, *_ = cat
    part = n.part('3001')
    index = S.build_index(S.Rows([], figure_parts=[(123, [(part, None, 1)])]))
    assert index.figure_posting[S.key_of(part, None)][0][0] == 123
    monkeypatch.setattr(S, 'index_for', lambda db: (index, False))
    result = supersets.found_in(db, part, n.colour('4'))
    assert result['colour_unmatched'] and result['total'] == 0


def test_headline_counts_match_filtered_owned_rows(world, coll):
    coll.add_copy('1000-1')
    coll.add_copy('1000-1')
    part, colour = coll.item('parts', '970c03'), coll.colour('0')
    for options in ({}, {'type': 'sets'}, {'type': 'minifigures'}, {'search': 'no such holder'}):
        result = supersets.found_in(coll.db, part, colour, limit=100, **options)
        assert sum(result['counts'].values()) == result['total']
        assert result['counts']['sets'] == sum(r['kind'] == 'set' for r in result['results'])
        assert result['counts']['minifigures'] == sum(r['kind'] == 'minifigure' for r in result['results'])
        assert result['owned_count'] == sum(r['owned'] for r in result['results'])
