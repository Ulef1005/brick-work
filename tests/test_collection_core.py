"""The collection's read side on the 4.0 store (M.8b, issue #110): identity on screen, instances and lists, the item page, search, prices,
places, and the small read modules (ownership, wish progress, completeness, list records), on the fixture pair of `tests/app4.py`.
Invented data, no network."""
from decimal import Decimal
import json

import pytest

from brickwork.core import collection, collection_prices, completeness, items, list_records, listing, ownership, wish_progress
from tests.app4 import STAMP, app4, client, coll, pair, read, world  # noqa: F401 (fixtures)


# ---------- identity on screen (decision 3 of #110) ----------

def test_labels_equal_label_for_every_kind_of_item(world, read):
    with read() as db:
        pairs = [(world.keep, None), (world.brick, world.red), (world.brick, None), (world.figure, None), (world.local_part, world.red),
                 (world.local_booklet, None), (world.mystery, None), (coll_item(db, 'parts', '970c03'), None), (coll_item(db, 'parts', '970c03'), world.white)]
        many = items.labels(db, pairs)
        assert set(many) == set(pairs)
        for item_id, colour in pairs:
            assert many[item_id, colour] == items.label(db, item_id, colour)
        assert items.labels(db, [(999999, None)]) == {} and items.labels(db, []) == {}


def coll_item(db, namespace, key):
    return db.execute('SELECT id FROM catalogue.item WHERE born_namespace=? AND born_key=?', (namespace, key)).fetchone()[0]


def test_a_row_shows_the_rebrickable_number_first_and_the_bricklink_one_beside_it(world, read):
    with read() as db:
        figure = next(r for r in collection.instances(db, 'minifigure') if r['item_id'] == world.figure)
        assert (figure['number'], figure['also'], figure['number_text'], figure['item_type']) == ('fig-000004', 'syn-fig-0004', 'fig-000004 · BrickLink syn-fig-0004', 'M')
        brick = next(r for r in collection.instances(db, 'part') if r['item_id'] == world.brick)
        assert (brick['number'], brick['also'], brick['number_text'], brick['item_no']) == ('3001', None, '3001', '3001')


def test_a_local_bricklink_born_item_is_marked_and_an_unidentified_one_shows_its_name(world, read):
    with read() as db:
        local = next(r for r in collection.instances(db, 'part') if r['item_id'] == world.local_part)
        assert (local['number'], local['number_source'], local['number_text'], local['unidentified'], local['unresolved']) == ('x999', 'bricklink', 'x999 (BrickLink)', False, False)
        mystery = next(r for r in collection.instances(db, 'gear'))
        assert (mystery['number'], mystery['item_no'], mystery['number_text'], mystery['unidentified'], mystery['unresolved']) == (None, '', 'Mystery thing', True, True)


def test_a_to_check_link_marks_the_item_unresolved_and_nothing_else_does(world, coll, read):
    coll.link(world.brick, '3001x', status='to_check')
    with read() as db:
        rows = {r['item_id']: r for r in collection.instances(db, 'part')}
        assert rows[world.brick]['unresolved'] and not rows[world.brick]['unidentified']
        assert not rows[world.plate]['unresolved'] and not rows[world.local_part]['unresolved']


# ---------- instances ----------

def test_copies_are_labelled_in_order_and_count_only_live_set_lines(world, coll, read):
    coll.mark(world.copy_a, '3023', '15', damaged=2)
    coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    with read() as db:
        copies = collection.instances(db, 'set', item_id=world.keep)
        assert [(c['label'], c['id']) for c in copies] == [('Set 1', world.copy_a), ('Set 2', world.copy_b)]
        a, b = copies
        assert (a['missing'], a['damaged']) == (2, 2) and (b['missing'], b['damaged']) == (0, 0)       # 1 red brick + 1 figure; 2 plates damaged
        assert a['condition'] == 'used' and a['completeness'] == 'incomplete' and b['completeness'] == 'sealed' and a['storage_name'] == 'Shelf A'
        assert a['place_name'] == 'Shop' and a['theme'] == 'Castle' and a['year'] == 1990 and a['quantity'] == 1 and a['color_id'] is None
        assert [f['name'] for f in a['flags']] == ['Set is checked', 'collection']            # statuses, then tags, by name
        one = collection.instance(db, 'copy', world.copy_b)
        assert one['label'] == 'Set 2' and one['missing'] == 0 and one['flags'] == []
        assert collection.instance(db, 'copy', 'nope') is None and collection.instance(db, 'stock', 'nope') is None


def test_a_retired_line_is_no_line_anywhere(world, coll, read):
    """Design 4.4: retired lines are excluded from counts, lists, the item page, the figure page and ownership."""
    coll.mark(world.copy_a, '3001', '4', missing=3, damaged=1)
    with read() as db:
        assert collection.instance(db, 'copy', world.copy_a)['missing'] == 3
        assert next(r for r in collection.listing(db, 'P') if r['item_id'] == world.brick and r['color_id'] == world.red)['in_sets'] == 8      # 4 in each of the two copies
    coll.retire_line(world.copy_a, '3001', '4')
    with read() as db:
        a = collection.instance(db, 'copy', world.copy_a)
        assert (a['missing'], a['damaged']) == (0, 0)
        detail = collection.detail(db, world.keep, copy_id=world.copy_a)
        assert [(l['item_no'], l['quantity']) for l in detail['consists'] if not l.get('minifig_no')] == [('3023', 2)]
        assert detail['progress']['missing'] == 0 and detail['progress']['total'] == 2
        row = next(r for r in collection.listing(db, 'P') if r['item_id'] == world.brick and r['color_id'] == world.red)
        assert (row['in_sets'], row['missing'], row['damaged']) == (4, 0, 0)                                    # only copy B's line is left
        assert ownership.summary(db, [world.brick])[world.brick]['needed_by'] == []
        used = collection.detail(db, world.brick, colour=world.red)['used_in']
        assert [u['copy_id'] for u in used] == [world.copy_b]


def test_an_archived_copy_is_hidden_unless_asked_for(world, coll, read):
    coll.sql("UPDATE copy SET archived_at=? WHERE id=?", (STAMP, world.copy_b))
    with read() as db:
        assert [c['id'] for c in collection.instances(db, 'set', item_id=world.keep)] == [world.copy_a]
        assert [c['id'] for c in collection.instances(db, 'set', item_id=world.keep, include_archived=True)] == [world.copy_a, world.copy_b]
        assert collection.listing(db, 'S')[0]['quantity'] >= 1
        assert world.copy_b not in sum((r['ids'] for r in collection.listing(db, 'S')), [])
        assert collection.instance(db, 'copy', world.copy_b)['label'] == 'Set 2'                                   # an archived copy keeps its number


def test_stock_only_leaves_the_copies_out_and_keeps_the_rest_as_it_was(world, read):
    """M.11b: the API's stock list asks for loose stock alone."""
    with read() as db:
        everything = collection.instances(db, include_archived=True)
        loose = collection.instances(db, include_archived=True, stock_only=True)
        assert [r['id'] for r in loose] == [r['id'] for r in everything if r['entity'] == 'stock'] and {r['entity'] for r in loose} == {'stock'}
        assert loose == [r for r in everything if r['entity'] == 'stock']
        assert collection.instances(db, 'part', stock_only=True) == collection.instances(db, 'part') and collection.instances(db, 'set', stock_only=True) == []
        assert [r['id'] for r in collection.instances(db, item_id=world.brick, stock_only=True)] == [r['id'] for r in collection.instances(db, item_id=world.brick)]


def test_stock_rows_carry_their_columns_and_the_kind_filter_keeps_kinds_apart(world, read):
    with read() as db:
        every = collection.instances(db)
        assert {r['entity'] for r in every} == {'copy', 'stock'}
        parts = collection.instances(db, 'part')
        assert {r['kind'] for r in parts} == {'part'} and sum(r['quantity'] for r in parts) == 3 + 2 + 2 + 5
        used = next(r for r in parts if r['id'] == world.stock_brick)
        assert (used['condition'], used['storage_name'], used['lot_name'], used['color_id']) == ('used', 'Shelf A', 'Bag', world.red)
        assert collection.instances(db, 'box') == [] and len(collection.instances(db, 'instructions')) == 1


# ---------- the lists ----------

def test_the_sets_list_groups_copies_per_item_with_words_and_gaps(world, read):
    with read() as db:
        rows = collection.listing(db, 'S')
        keep = next(r for r in rows if r['item_id'] == world.keep)
        assert (keep['quantity'], keep['conditions'], keep['statuses'], keep['missing'], keep['missing_parts'], keep['missing_figures']) == (2, ['used', 'new'], ['incomplete', 'sealed'], 1, 1, 0)
        assert keep['storages'] == [world.shelf, 'null'] and keep['places'] == [world.shop, 'null'] and sorted(keep['flag_names']) == ['Set is checked', 'collection']
        assert keep['price']['price'] == '30.00' and keep['theme'] == 'Castle' and keep['number_text'] == '1000-1' and keep['kind'] == 'set'
        assert [r['item_no'] for r in rows] == ['1000-1', '2070-1']
        with pytest.raises(ValueError):
            collection.listing(db, '?')


def test_the_parts_list_has_loose_stock_and_parts_held_only_in_sets(world, read):
    with read() as db:
        rows = collection.listing(db, 'P')
        red_brick = [r for r in rows if r['item_id'] == world.brick and r['color_id'] == world.red]
        assert len(red_brick) == 1 and red_brick[0]['quantity'] == 5 and red_brick[0]['in_sets'] == 8 and red_brick[0]['missing'] == 1
        assert red_brick[0]['color_name'] == 'Red' and red_brick[0]['rgb'] == 'C91A09' and red_brick[0]['ink'] in ('#1A1816', '#FAFAF8')
        assert red_brick[0]['price']['price'] == '0.40' and len(red_brick[0]['instances']) == 2
        in_sets_only = [r for r in rows if r['quantity'] == 0 and r['in_sets']]
        assert in_sets_only and all(r['instances'] == [] for r in in_sets_only)           # the figure's parts are not set lines
        assert {r['item_type'] for r in rows} == {'P'}


def test_the_minifigures_list_counts_loose_figures_and_figures_in_sets(world, read):
    with read() as db:
        rows = collection.listing(db, 'M')
        figure = next(r for r in rows if r['item_id'] == world.figure)
        assert (figure['quantity'], figure['in_sets']) == (1, 4)                              # two copies of 1000-1, two figures each
        assert figure['number_text'] == 'fig-000004 · BrickLink syn-fig-0004'


def test_instructions_share_their_files_with_the_set_of_the_same_number(world, coll, read):
    coll.sql("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,?,?,?)", (world.keep, 'data/instructions/1000-1.pdf', 'Booklet', STAMP))
    with read() as db:
        row = collection.listing(db, 'I')[0]
        assert row['item_id'] == world.local_booklet and row['pdf_available'] is True
        assert [f['label'] for f in collection.detail(db, world.local_booklet, stock_id=world.stock_booklet)['instructions']] == ['Booklet']
        assert [f['label'] for f in collection.detail(db, world.keep, copy_id=world.copy_a)['instructions']] == ['Booklet']
        assert collection.detail(db, world.duplo)['instructions'] == []


def test_wishes_list_every_kind_with_their_list_and_quotes(world, coll, read):
    coll.price(world.plate, '0.30', colour=world.white, condition='new', guide='stock', slot='bricklink_new')
    with read() as db:
        rows = collection.listing(db, 'S', wishes=True)
        assert {(r['item_type'], r['quantity'], r['list_name']) for r in rows} == {('S', 1, 'Wishlist'), ('P', 2, 'Wishlist')}
        part = next(r for r in rows if r['item_type'] == 'P')
        assert part['color_name'] == 'White' and part['max_price'] == '0.50' and part['list_id'] == 'default' and part['condition'] == 'new'
        assert [p['guide'] for p in part['prices']] == ['stock'] and part['entity'] == 'wish'


def test_list_records_are_words_with_both_numbers_and_the_item_id(world, read):
    with read() as db:
        rows = collection.listing(db, 'M')
    data = json.loads(list_records.payload(rows))
    fields = data['fields']
    assert fields[-3:] == ['item_id', 'also', 'source'] and 'purchase_location_id' not in fields
    record = decoded(list_records.payload(rows))[0]
    assert record['item_id'] == world.figure and record['also'] == 'syn-fig-0004' and record['condition'] == ['used'] and record['number'] == 'fig-000004'
    for key in ('condition', 'status'):
        assert not any(set(r.get(str(fields.index(key)), [])) & {'N', 'U', 'D', 'S', 'C', 'I'} for r in data['rows'])


DEFAULTS = {18: [''], 19: [''], 20: ['null'], 21: ['null'], 22: [], 23: ['null']}      # what the browser restores for a field the payload leaves out


def decoded(payload):
    data = json.loads(payload)
    return [dict(zip(data['fields'], [r.get(str(i), DEFAULTS.get(i)) for i in range(len(data['fields']))])) for r in data['rows']]


def test_a_search_takes_either_number_and_filters_by_word_states(world, read):
    with read() as db:
        rows = decoded(list_records.payload(collection.listing(db, 'M')))
    assert [r['item_id'] for r in listing.filter_rows(rows, 'syn-fig-0004')] == [world.figure]          # the BrickLink number
    assert [r['item_id'] for r in listing.filter_rows(rows, 'fig-000004')] == [world.figure]
    assert listing.filter_rows(rows, '', {'condition': 'used'}) and not listing.filter_rows(rows, '', {'condition': 'new'})
    assert listing.filter_rows(rows, '', {'status': 'unknown'}) and not listing.filter_rows(rows, '', {'status': 'complete'})


def test_the_part_colour_chooser_counts_stock_set_lines_and_wishes_without_spares(world, read):
    with read() as db:
        colours = {c['color_name']: c['quantity'] for c in collection.part_colours(db, world.brick)}
        assert colours == {'Red': 5 + (4 - 1) + 4}                                   # loose stock, the set lines less what is missing, then the wish counts 0
        plate = {c['color_name']: c['quantity'] for c in collection.part_colours(db, world.plate)}
        assert plate == {'White': 2 + 2 + 2}                                          # the spare red plate is not a colour


# ---------- the item page ----------

def test_the_set_page_lists_its_copy_and_what_is_missing(world, read):
    with read() as db:
        d = collection.detail(db, world.keep, copy_id=world.copy_a)
        assert (d['kind'], d['item_type'], d['selected']['id'], d['selected']['label']) == ('set', 'S', world.copy_a, 'Set 1')
        assert [(l['item_no'], l['quantity'], l['missing'], l['deficit']) for l in d['consists'] if not l.get('minifig_no')] == [('3001', 4, 1, 1), ('3023', 2, 0, 0)]
        figures = [l for l in d['consists'] if l.get('minifig_no')]
        assert [(f['item_no'], f['quantity'], f['missing'], f['parts_lines']) for f in figures] == [('fig-000004', 2, 0, 4)]
        assert d['progress'] == dict(total=6, missing=1, checked=0, can_take=1, different=2, lines=2, checked_lines=0, check_recorded=True, spare_lines=1, known=True)
        assert d['figure_progress'] == {'total': 2, 'present': 2}
        assert [i['id'] for i in d['instances']] == [world.copy_a, world.copy_b]
        assert d['price_records'][0]['price'] == '30.00' and d['condition_prices'][0]['condition'] == 'used'
        assert d['partout']['partout'] is None and (d['partout']['lines'], d['partout']['priced']) == (3, 0) and [l['can_take'] for l in d['consists'] if not l.get('minifig_no')] == [1, 0]     # loose red 3001 could fill the gap
        assert d['external_links'][0][0] == 'BrickLink' and d['external_links'][1][0] == 'Brickset'


def test_the_unchecked_set_says_parts_not_checked(world, read):
    with read() as db:
        d = collection.detail(db, world.keep, copy_id=world.copy_b)
        assert d['progress']['known'] is False and d['progress']['check_recorded'] is False and d['progress']['missing'] == 0
        assert collection.detail(db, world.keep)['selected']['id'] == world.copy_a                # no copy asked for: the first one
        with pytest.raises(ValueError, match='Instance is unavailable'):
            collection.detail(db, world.keep, copy_id='nope')
        with pytest.raises(ValueError, match='Item is unavailable'):
            collection.detail(db, 999999)


def test_a_set_with_two_versions_shows_the_latest_list_to_a_wish_and_a_copy_its_own(coll, read):
    """2070-1 has two part lists: a copy shows the one it was built from, a wish or no instance the catalogue's latest."""
    duplo = coll.item('sets', '2070-1')
    copy_v1 = coll.add_copy('2070-1', version=1)
    wish = coll.add_wish(duplo)
    with read() as db:
        latest = [('2071pr0001', 1), ('dupupn0105c01', 1), ('dupupn0123a', 1), ('dupupn0123b', 1)]
        reference = collection.detail(db, duplo, wish_id=wish)
        assert reference['selected']['entity'] == 'wish' and [(l['item_no'], l['quantity']) for l in reference['consists']] == latest
        mine = collection.detail(db, duplo, copy_id=copy_v1)
        assert [l['item_no'] for l in mine['consists']] == ['2071pr0001', 'dupupn0105c01', 'dupupn0123']
        assert mine['progress']['known'] is False and reference['progress']['known'] is False
    coll.sql('DELETE FROM wish WHERE id=?', (wish,))
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', (STAMP, copy_v1))
    with read() as db:
        nobody = collection.detail(db, duplo)
        assert nobody['selected'] is None and nobody['instances'] == [] and [(l['item_no'], l['quantity']) for l in nobody['consists']] == latest


def test_a_wish_page_selects_the_wish_and_checks_colour_and_item(world, read):
    with read() as db:
        d = collection.detail(db, world.plate, colour=world.white, wish_id=world.wish_part)
        assert d['wish']['id'] == world.wish_part and d['selected']['entity'] == 'wish' and d['wish']['list_id'] == 'default'
        with pytest.raises(ValueError, match='Wish is unavailable'):
            collection.detail(db, world.plate, colour=world.red, wish_id=world.wish_part)
        with pytest.raises(ValueError, match='Wish is unavailable'):
            collection.detail(db, world.brick, colour=world.white, wish_id=world.wish_part)


def test_a_part_page_is_one_colour_and_lists_where_it_is_used(world, read):
    with read() as db:
        d = collection.detail(db, world.brick, colour=world.red)
        assert d['color_name'] == 'Red' and sum(i['quantity'] for i in d['instances']) == 5
        assert sorted(u['copy_id'] for u in d['used_in']) == sorted([world.copy_a, world.copy_b])
        assert {u['label'] for u in d['used_in']} == {'Set 1', 'Set 2'} and {u['number_text'] for u in d['used_in']} == {'1000-1'}
        white = collection.detail(db, world.brick, colour=world.white)
        assert white['instances'] == [] and white['used_in'] == []
        assert [r['quantity'] for r in d['consolidated']] == [3, 2]                              # merged by storage, condition and lot


def test_a_loose_figure_page_lists_its_own_parts_and_the_sets_it_is_in(world, read):
    with read() as db:
        d = collection.detail(db, world.figure, stock_id=world.stock_figure)
        assert d['kind'] == 'minifigure' and d['loose_count'] == 1 and d['set_count'] == 4
        assert sorted(l['item_no'] for l in d['consists']) == ['3626apr0001', '3901', '970c03', '973c27h01']
        assert {c['item_no'] for c in d['figure_components']} == {'3626apr0001', '3901', '970c03', '973c27h01'}
        assert [u['label'] for u in d['used_in']] == ['Set 1', 'Set 2']
        assert d['catalogue_ids'] == {'Rebrickable': 'fig-000004', 'BrickLink': 'syn-fig-0004', 'Brickset': None}
        assert d['loose_conditions'] == {'used': 1}


def test_a_figure_part_missing_in_a_copy_warns_on_the_figure_page(world, coll, read):
    coll.mark(world.copy_a, '3901', '6', missing=1, figure='fig-000004')
    with read() as db:
        d = collection.detail(db, world.figure)
        warned = [c for c in d['figure_components'] if c['warnings']]
        assert [(c['item_no'], c['warnings'][0]['label']) for c in warned] == [('3901', 'Set 1')]
        assert next(u for u in d['used_in'] if u['copy_id'] == world.copy_a)['parts_missing'] == 1
        set_page = collection.detail(db, world.keep, copy_id=world.copy_a)
        assert next(l for l in set_page['consists'] if l.get('minifig_no'))['parts_missing'] == 1


def test_unidentified_and_local_items_have_pages(world, read):
    with read() as db:
        mystery = collection.detail(db, world.mystery, stock_id=world.stock_mystery)
        assert (mystery['unidentified'], mystery['item_no'], mystery['number_text'], mystery['external_links'], mystery['consists']) == (True, '', 'Mystery thing', [], [])
        local = collection.detail(db, world.local_part, colour=world.red)
        assert local['number_text'] == 'x999 (BrickLink)' and sum(i['quantity'] for i in local['instances']) == 5
        assert collection.external_links(db, dict(item_type='S', item_id=world.mystery, unidentified=True)) == []


def test_properties_follow_the_metadata_priority_and_prices_skip_voided_observations(world, coll, read):
    coll.prop(world.keep, 'theme', 'From Brickset', source='brickset')
    coll.prop(world.keep, 'theme', 'From BrickLink', source='bricklink')
    coll.setting('source_priority', json.dumps({'metadata': {'set': ['brickset', 'bricklink']}}))
    voided = coll.price(world.keep, '99.00', condition='used', guide='sold', observed='2026-10-25T00:00:00.000Z')
    coll.sql('UPDATE price_observation SET voided_at=? WHERE id=?', (STAMP, voided))
    with read() as db:
        props = collection.properties(db, [world.keep])[world.keep]
        assert props['theme']['value'] == 'From Brickset' and [a['value'] for a in props['theme']['alternatives']] == ['From BrickLink']
        assert collection.prices(db, world.keep, None) == []                       # price_current names the voided observation: no quote shows
        assert collection.properties(db, []) == {}


def test_prices_decorate_ranges_staleness_and_boxed_labels(world, coll, read):
    coll.price(world.keep, '55.00', condition='used', guide='valuation', slot='boxed')
    with read() as db:
        quotes = {(p['guide'], p['slot']): p for p in collection.prices(db, world.keep, None)}
        sold = quotes['sold', None]
        assert sold['label'] == 'Used' and sold['range'] == pytest.approx(50.0) and sold['stale'] is False
        assert quotes['valuation', 'boxed']['label'] == 'With box' and sold['age'] == '2026-10-26'
        listed = collection.prices(db, pairs=[(world.keep, None), (world.brick, world.red)], used_sold=True)
        assert [p['guide'] for p in listed[world.keep, None]] == ['sold'] and set(listed) == {(world.keep, None), (world.brick, world.red)}


def test_a_quote_older_than_its_sources_freshness_is_stale(world, coll, read):
    coll.sql("INSERT INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',3)")
    coll.price(world.brick, '0.50', colour=world.red, condition='new', guide='sold', observed='2026-10-01T00:00:00.000Z')
    with read() as db:
        stale = {p['condition']: p['stale'] for p in collection.prices(db, world.brick, world.red)}
        assert stale == {'new': True, 'used': False}                # the world's used quote is from 2026-10-26


def test_the_chosen_price_follows_the_source_priority_and_history_needs_two_dates(world, coll, read):
    coll.price(world.keep, '28.00', condition='used', guide='sold', source='brickset', observed='2026-10-20T00:00:00.000Z')
    coll.setting('source_priority', json.dumps({'market_price': {'*': ['brickset', 'bricklink']}}))
    with read() as db:
        row = next(r for r in collection.listing(db, 'S') if r['item_id'] == world.keep)
        assert row['price']['source'] == 'brickset' and row['price']['price'] == '28.00'
        history = collection.detail(db, world.keep, copy_id=world.copy_a)['price_history']
        assert history == dict(single=True, points=[dict(date='2026-10-20T00:00:00+00:00', value='28.00')], currency='EUR', source='brickset')


def test_retail_price_and_the_saving_against_a_copys_price(world, coll, read):
    coll.price(world.keep, '20.00', condition=None, guide='retail', slot='retail', region='DE', currency='EUR')
    coll.prop(world.keep, 'dateLastAvailable', '2020-01-31')
    with read() as db:
        d = collection.detail(db, world.keep, copy_id=world.copy_a)
        assert d['retail']['price'] == '20.00' and d['retail']['status'] == 'Retired' and d['retail']['country'] == 'DE'
        assert d['retail_saving'] == {'pct': 38, 'under': True}                                    # paid 12.50 of 20.00
        assert collection.detail(db, world.brick, colour=world.red)['retail'] is None
        assert collection.exchange_rates(db) == {'EUR': {'per_eur': Decimal(1), 'as_of': None, 'source': 'fixed'}}


# ---------- search ----------

def test_the_jump_search_takes_names_and_both_numbers_and_ranks_sets_first(world, read):
    with read() as db:
        def found(q):
            return [(r['item_type'], r['item_id']) for r in collection.search(db, q)['results']]
        assert found('castle')[0] == ('S', world.keep) and ('S', world.gate) in found('castle')            # an owned set, then a wanted one
        assert found('x999') == [('P', world.local_part)]
        assert found('syn-fig-0004') == [('M', world.figure)] and found('fig-000004') == [('M', world.figure)]
        assert found('mystery') and found('Mystery')[0][0] == 'G'
        assert found('zzz-no-such') == [] and collection.search(db, '  ')['results'] == []
        assert collection.search(db, 'castle', limit=1)['truncated'] is True
        hit = next(r for r in collection.search(db, '1000-1')['results'] if r['item_id'] == world.keep)
        assert [i['id'] for i in hit['instances']] == [world.copy_a, world.copy_b] and hit['image'] is None


def test_the_search_finds_a_copy_by_its_id_and_a_set_line_part_that_is_not_loose(world, read):
    with read() as db:
        assert [r['item_id'] for r in collection.search(db, world.copy_c[:8])['results']] == [world.duplo]
        plate = collection.search(db, '3023')['results']
        assert {r['color_id'] for r in plate if r['item_id'] == world.plate} >= {world.white}


# ---------- places, lots ----------

def test_purchase_places_total_copies_per_currency_and_derive_orders_and_last_use(world, coll, read):
    coll.sql("INSERT INTO purchase_order(bricklink_order_id,store,date_ordered,created_at,updated_at) VALUES('1','shop','2025-03-02',?,?)", (STAMP, STAMP))
    with read() as db:
        place = collection.purchase_places(db)[0]
        assert (place['name'], place['count'], place['totals'], place['orders'], place['last_used']) == ('Shop', 1, {'EUR': Decimal('12.50')}, 1, '2025-03-02')


def test_a_lot_page_lists_its_stock_and_an_unknown_lot_is_unavailable(world, read):
    with read() as db:
        lot = collection.lot_detail(db, world.bag)
        assert lot['name'] == 'Bag' and [r['id'] for r in lot['rows']] == [world.stock_brick] and lot['rows'][0]['number_text'] == '3001'
        with pytest.raises(ValueError, match='Lot is unavailable'):
            collection.lot_detail(db, 'nope')


def test_options_list_the_live_choices(world, coll, read):
    coll.sql('UPDATE storage SET archived_at=? WHERE id=?', (STAMP, coll.storage('Old shelf')))
    with read() as db:
        choices = collection.options(db, include_wishlists=True)
        assert [s['name'] for s in choices['storages']] == ['Shelf A'] and [p['name'] for p in choices['places']] == ['Shop']
        assert [l['name'] for l in choices['lots']] == ['Bag'] and {f['name'] for f in choices['flags']} >= {'collection', 'Set is checked'}
        assert [w['id'] for w in choices['wishlists']] == ['default'] and {'Red', 'White'} <= {c['name'] for c in choices['colours']}


# ---------- the small read modules ----------

def test_ownership_lists_what_is_held_by_colour_and_what_copies_need(world, read):
    with read() as db:
        summary = ownership.summary(db, [world.brick, world.figure, world.mystery, None, 0])
        brick = summary[world.brick]
        assert brick['total'] == 5 and [(c['name'], c['quantity'], c['storages']) for c in brick['colours']] == [('Red', 5, ['Shelf A'])]
        assert brick['needed_count'] == 1 and brick['needed_by'][0] == {'copy_id': world.copy_a, 'set_id': world.keep, 'color_id': world.red, 'gap': 1, 'set_no': '1000-1'}
        assert summary[world.figure]['total'] == 1 and summary[world.mystery]['total'] == 2 and ownership.summary(db, []) == {}
        assert ownership.text(summary[world.brick]).startswith('You have 5') and ownership.text({'total': 0}) == 'Not in your collection'


def test_wish_progress_counts_copies_for_sets_and_usable_stock_for_parts(world, coll, read):
    coll.sql('UPDATE wish SET qty_filled_manual=7 WHERE id=?', (world.wish_set,))
    with read() as db:
        rows = collection.listing(db, 'S', wishes=True)
        annotated = {r['item_type']: r for r in wish_progress.annotate(db, rows)}
        assert (annotated['P']['qty_filled'], annotated['P']['qty_filled_source'], annotated['P']['filled']) == (2, 'derived', True)            # 2 new white plates, wanted 2 new
        assert (annotated['S']['qty_filled'], annotated['S']['qty_filled_source'], annotated['S']['filled']) == (7, 'manual', True)
        assert wish_progress.annotate(db, []) == []
        own = wish_progress.annotate(db, [dict(item_id=world.keep, kind='set', quantity=3), dict(item_id=world.brick, color_id=world.red, kind='part', condition='used', quantity=4)])
        assert [(r['qty_filled'], r['filled']) for r in own] == [(2, False), (3, False)]


def test_derived_completeness_is_complete_only_when_checked_and_nothing_is_missing(world, coll, read):
    coll.sql("UPDATE copy SET completeness_source='derived' WHERE id IN (?,?)", (world.copy_a, world.copy_b))
    with read() as db:
        assert completeness.derived_state(db, world.copy_a) == 'incomplete'              # checked, but a brick is missing
        assert completeness.derived_state(db, world.copy_b) == 'incomplete'              # nothing missing, never checked
        assert completeness.derived_state(db, world.copy_c) is None                      # manual
    coll.mark(world.copy_a, '3001', '4', missing=0)
    coll.tag('copy', world.copy_b, world.checked)
    with read() as db:
        assert completeness.derived_state(db, world.copy_a) == 'complete' and completeness.derived_state(db, world.copy_b) == 'complete'
