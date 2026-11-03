"""4.9a on the 4.0 store (M.8e, issue #110): the Matching module of the part and figure pages, its order and its headline.

The 3.3 file also asserted set detail and part detail geometry from a CSS region; those pages are the collection's (M.8b) and their
tests live with them. Here: the module itself.
"""
from bs4 import BeautifulSoup
from brickwork.core import collection
from tests.app4 import app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def derived_copy(coll, checked=False):
    copy = coll.add_copy('1000-1', condition='used', completeness='incomplete', completeness_source='derived')
    for name in ('Instructions present', 'Box present') + (('Set is checked',) if checked else ()):
        coll.tag('copy', copy, coll.flag(name, 'status'))
    return copy


def test_part_matching_has_no_toolbar_and_states_its_order(world, coll, client):
    matching = page(client, f'/collection/item/{world.brick}?colour={world.red}').select_one('[data-module=matching]')
    assert not matching.select('.bc-toolbar, [data-bc-search], [data-bc-sort]')
    assert matching.select_one('.bc-matching-headline').get_text()
    assert matching.select_one('.bc-matching-sub').get_text() == 'Sorted by fewest parts left'
    assert matching.select_one('.bc-matching-headline').find_next_sibling() == matching.select_one('.bc-matching-sub')
    # Decision 16 (A): set detail has no Matching module; Take on the missing-part cards covers it.
    assert not page(client, f'/collection/item/{world.keep}?copy={world.copy_a}').select('[data-module=matching]')


def test_matches_are_sorted_by_completion_then_fewest_parts_left(world, coll):
    # Copy "many" lacks two distinct parts, "one" lacks one; creation order would put "many" first.
    many = derived_copy(coll)
    one = derived_copy(coll)
    coll.mark(many, '3001', '4', missing=1)
    coll.mark(many, '3023', '15', missing=1)
    coll.mark(one, '3001', '4', missing=1)
    detail = collection.detail(coll.db, world.brick, colour=world.red)
    order = [m['copy_id'] for m in detail['matches']]
    assert order.index(one) < order.index(many)


def test_figure_matching_headline_and_order(world, coll, client):
    copy = derived_copy(coll, checked=True)
    coll.mark_figure(copy, 'fig-000004', missing=1)
    coll.add_stock('minifigure', coll.item('minifigs', 'fig-000004'), quantity=1, condition='new')
    soup = page(client, f'/collection/item/{world.figure}')
    modules = [m['data-module'] for m in soup.select('[data-module]')]
    assert modules.index('consists') < modules.index('matching')
    matching = soup.select_one('[data-module=matching]')
    assert not matching.select('.bc-toolbar')
    headline = matching.select_one('.bc-matching-headline').get_text()
    assert headline.startswith('Fits 1 set, completes '), headline
    assert matching.select_one('.bc-matching-sub').get_text() == 'Sorted by fewest parts left'
    # No remaining match: the figure module shows one empty-state line.
    coll.sql('UPDATE copy_figure SET missing=0')
    matching = page(client, f'/collection/item/{world.figure}').select_one('[data-module=matching]')
    assert not matching.select('.bc-matching-headline')
    assert 'Nothing to match yet' in matching.get_text()


def test_matches_cost_no_query_per_match(world, coll):
    statements = []
    db = coll.db
    db.set_trace_callback(statements.append)
    collection.detail(db, world.brick, colour=world.red)
    few = len(statements)
    for _ in range(40):
        coll.mark(derived_copy(coll), '3001', '4', missing=1)
    statements.clear()
    collection.detail(db, world.brick, colour=world.red)
    many = len(statements)
    db.set_trace_callback(None)
    assert many <= few + 20, (few, many)
