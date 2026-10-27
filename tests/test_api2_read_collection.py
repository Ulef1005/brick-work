"""API v2 reads of what is owned (M.11b, issue #113): copies and their lines, loose stock, figures by identity, gaps and matches.
Ported from the copy, stock and Workbench reads of test_bw_api_m2 and from test_bw_partout_38_api, test_bw_wish_progress_35_api (copy and stock
side) onto the 4.0 fixtures. Invented data."""
from datetime import datetime, timezone
from urllib.parse import urlencode

from brickwork.store4 import copies as copies_store
from tests.api2 import call, v2, validate  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def fresh():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def quote(coll, item, price, colour=None):
    """A used quote the part-out and Complete-sets rules accept: fresh, in the BrickLink currency and region."""
    coll.price(item, price, colour=colour, condition='used', region='eu', observed=fresh())


def data(response):
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json['data']


def ids(response):
    return [r['id'] for r in data(response)]


# --- the copy
def test_a_copy_is_the_copy_body_with_words_prices_as_text_and_the_item_body(v2, world):
    copy = data(call(v2, f'/copies/{world.copy_a}'))
    assert copy['item']['id'] == world.keep and copy['item']['rebrickable'] == {'key': '1000-1'} and copy['name'] == 'Syn Castle Keep'
    assert (copy['condition'], copy['completeness'], copy['completeness_source']) == ('used', 'incomplete', 'manual')
    assert (copy['storage_id'], copy['purchase_location_id'], copy['purchase_price'], copy['purchase_currency'], copy['purchase_date'], copy['note']) == (
        world.shelf, world.shop, '12.50', 'EUR', '2024-05-01', 'Flea market')
    assert (copy['missing'], copy['damaged'], copy['pinned'], copy['archived_at']) == (1, 0, False, None)
    assert sorted(copy['flags']) == sorted([world.tag, world.checked]) and copy['image_id'] is None
    assert copy['inventory'] == {'source': 'rebrickable', 'version': 1, 'ordinal': 1, 'of': 1, 'pending': None, 'changed_since_build': False}


def test_a_copy_read_has_an_etag_that_follows_what_was_saved_and_its_flags(v2, coll, world):
    first = call(v2, f'/copies/{world.copy_a}')
    tag = first.headers['ETag']
    assert tag == f'"{first.json["data"]["etag"]}"'
    coll.sql("UPDATE item SET name='Renamed set' WHERE id=?", (world.keep,))
    assert call(v2, f'/copies/{world.copy_a}').headers['ETag'] == tag                   # the item's name is not the copy's
    coll.sql('UPDATE copy SET note=? WHERE id=?', ('A new note', world.copy_a))
    changed = call(v2, f'/copies/{world.copy_a}').headers['ETag']
    assert changed != tag
    coll.sql('DELETE FROM copy_flag WHERE copy_id=? AND flag_id=?', (world.copy_a, world.tag))
    assert call(v2, f'/copies/{world.copy_a}').headers['ETag'] != changed
    assert data(call(v2, '/copies'))[0]['etag'] in {call(v2, f'/copies/{c}').json['data']['etag'] for c in (world.copy_a, world.copy_b, world.copy_c)}


def test_a_single_copy_read_carries_its_part_out_value(v2, coll, world):
    quote(coll, world.brick, '0.40', world.red)
    po = data(call(v2, f'/copies/{world.copy_a}'))['partout']
    assert set(po) == {'value', 'currency', 'lines', 'priced', 'unpriced', 'unpriced_count'}
    assert po['lines'] == 3 and po['priced'] == 1 and po['value'] is None                  # one of three lines has a quote: not enough for a total
    assert po['unpriced_count'] == 2 and {u['item']['id'] for u in po['unpriced']} == {world.plate, world.figure} and po['unpriced'][0]['color'] is not None
    assert 'partout' not in data(call(v2, '/copies'))[0]                                   # a list row does not carry it


def test_a_part_out_value_is_given_once_most_lines_have_a_price(v2, coll, world):
    quote(coll, world.brick, '0.40', world.red)
    quote(coll, world.plate, '0.10', world.white)
    quote(coll, world.figure, '2.00')
    po = data(call(v2, f'/copies/{world.copy_a}'))['partout']
    assert po['priced'] == 3 and po['unpriced'] == [] and po['value'] == '5.40'                  # 3 bricks present x 0.40 + 2 plates x 0.10 + 2 figures x 2.00


def test_the_inventory_of_a_copy_says_which_list_it_is_and_whether_it_changed(v2, coll):
    second, latest = coll.add_copy('2070-1', version=1), coll.add_copy('2070-1')
    state = data(call(v2, f'/copies/{second}'))['inventory']
    assert (state['source'], state['version'], state['ordinal'], state['of']) == ('rebrickable', 1, 1, 2)      # the older of the set's two lists
    assert (data(call(v2, f'/copies/{latest}'))['inventory']['version'], data(call(v2, f'/copies/{latest}'))['inventory']['ordinal']) == (2, 2)
    assert state['changed_since_build'] is False
    coll.sql("UPDATE copy SET inventory_digest='stale' WHERE id=?", (second,))
    assert data(call(v2, f'/copies/{second}'))['inventory']['changed_since_build'] is True
    assert [c for c in copies_store.part_list_changes(coll.db) if c['copy_id'] == second]


def test_a_copy_that_waits_for_a_bricklink_list_says_so(v2, coll, world):
    coll.sql("INSERT INTO job(source,kind,state,via,created_at,updated_at) VALUES('bricklink','inventory','queued','api','x','x')")
    coll.sql("UPDATE copy SET inventory_pending='bricklink', pending_job_id=1 WHERE id=?", (world.copy_a,))
    assert data(call(v2, f'/copies/{world.copy_a}'))['inventory']['pending'] == 'bricklink'


def test_an_unknown_copy_is_404_on_every_copy_path(v2):
    for tail in ('', '/completeness', '/check', '/gaps', '/matches', '/parts', '/figures'):
        for copy in ('absent', '0' * 36, 'x' * 70):
            response = call(v2, f'/copies/{copy}{tail}')
            assert response.status_code == 404 and response.json['code'] == 'not_found', (copy, tail)


# --- the copies
def test_copies_filter_by_every_documented_name(v2, coll, world):
    assert ids(call(v2, '/copies?condition=used&status=incomplete')) == [world.copy_a]
    assert ids(call(v2, f'/copies?storage={world.shelf}&place={world.shop}&flag={world.tag}&problem=missing')) == [world.copy_a]
    assert sorted(ids(call(v2, '/copies?storage=null'))) == sorted([world.copy_b, world.copy_c])
    assert ids(call(v2, '/copies?place=null&condition=new')) == [world.copy_b]
    assert sorted(ids(call(v2, '/copies?duplicates=true'))) == sorted([world.copy_a, world.copy_b]) and ids(call(v2, '/copies?duplicates=false')) == [world.copy_c]
    assert ids(call(v2, '/copies?theme=Rattles')) == [world.copy_c] and sorted(ids(call(v2, '/copies?year=1990'))) == sorted([world.copy_a, world.copy_b])
    assert ids(call(v2, '/copies?q=rabbit')) == [world.copy_c]
    assert ids(call(v2, '/copies?lot=null&status=unknown')) == [] and ids(call(v2, '/copies?lot=somewhere')) == []
    assert ids(call(v2, '/copies?problem=damaged')) == []
    assert call(v2, '/copies?status=nonsense').json['data'] == [] and call(v2, '/copies?duplicates=maybe').status_code == 400


def test_copies_are_found_by_a_number_in_either_provider(v2, coll, world):
    assert sorted(ids(call(v2, '/copies?number=1000-1'))) == sorted([world.copy_a, world.copy_b])
    assert ids(call(v2, '/copies?number=2070-1&provider=rebrickable')) == [world.copy_c]
    assert ids(call(v2, '/copies?number=9999-9')) == []
    assert call(v2, '/copies?number=1000-1&provider=brickwork').status_code == 422
    assert call(v2, '/copies?number=1000-1&provider=lego').status_code == 422
    assert call(v2, '/copies?color=1').status_code == 400                                   # a copy has no colour to filter by


def test_copies_sort_by_number_name_missing_and_used_price(v2, world):
    assert ids(call(v2, '/copies?sort=name'))[0] == world.copy_c and ids(call(v2, '/copies?sort=name&direction=desc'))[-1] == world.copy_c
    assert ids(call(v2, '/copies?sort=missing'))[0] == world.copy_a                          # the most missing first
    priced = ids(call(v2, '/copies?sort=used_price&direction=desc'))
    assert sorted(priced) == sorted([world.copy_a, world.copy_b, world.copy_c]) and priced[0] in (world.copy_a, world.copy_b)
    assert call(v2, '/copies?sort=nonsense').status_code == 400 and call(v2, '/copies?sort=year&direction=sideways').status_code == 400


def test_archived_copies_are_hidden_until_asked_for_and_still_read_by_id(v2, coll, world):
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', world.copy_a))
    assert world.copy_a not in ids(call(v2, '/copies'))
    assert ids(call(v2, '/copies?archived=only')) == [world.copy_a]
    assert world.copy_a in ids(call(v2, '/copies?archived=include')) and world.copy_a in ids(call(v2, '/copies?archived=true'))
    one = call(v2, f'/copies/{world.copy_a}')
    assert one.status_code == 200 and one.headers['ETag'] and one.json['data']['archived_at'] and one.json['data']['condition'] == 'used'
    assert call(v2, '/copies?archived=nonsense').status_code == 400
    assert call(v2, f'/copies/{world.copy_a}/gaps').status_code == 409 and call(v2, f'/copies/{world.copy_a}/check').json['code'] == 'archived'
    assert call(v2, f'/copies/{world.copy_a}/parts').status_code == 200


def test_unrecorded_states_read_as_null(v2, coll, world):
    coll.sql('UPDATE copy SET condition=NULL,completeness=NULL,completeness_source=NULL WHERE id=?', (world.copy_a,))
    coll.sql('UPDATE copy_part SET checked=1 WHERE copy_id=?', (world.copy_a,))
    response = call(v2, f'/copies/{world.copy_a}')
    validate(response, 'get_copies_by_id')
    assert (response.json['data']['condition'], response.json['data']['completeness']) == (None, None)
    validate(call(v2, '/copies'), 'get_copies')
    parts = data(call(v2, f'/copies/{world.copy_a}/parts?limit=200'))
    assert all(p['checked'] is True for p in parts)
    assert ids(call(v2, '/copies?status=unknown')) == [world.copy_a]


# --- completeness and the check
def test_completeness_says_stored_derived_checked_and_counts(v2, coll, world):
    assert data(call(v2, f'/copies/{world.copy_a}/completeness')) == {
        'stored': 'incomplete', 'completeness_source': 'manual', 'derived': None, 'checked': True, 'missing': 1, 'damaged': 0, 'missing_figures': 0}
    coll.sql("UPDATE copy SET completeness_source='derived' WHERE id=?", (world.copy_a,))
    assert data(call(v2, f'/copies/{world.copy_a}/completeness'))['derived'] == 'incomplete'
    coll.mark(world.copy_a, '3001', '4', missing=0)
    assert data(call(v2, f'/copies/{world.copy_a}/completeness'))['derived'] == 'complete'
    coll.mark_figure(world.copy_b, 'fig-000004', missing=1)
    other = data(call(v2, f'/copies/{world.copy_b}/completeness'))
    assert (other['stored'], other['checked'], other['missing'], other['missing_figures']) == ('sealed', False, 1, 1)


def test_the_check_lists_the_sequence_and_the_saved_session(v2, coll, world):
    state = data(call(v2, f'/copies/{world.copy_a}/check'))
    assert state['session'] is None
    kinds = [(r['kind'], r['token']) for r in state['rows']]
    assert [k for k, _ in kinds].count('part') == 2 and [k for k, _ in kinds].count('spare') == 1 and [k for k, _ in kinds].count('figure') == 1
    brick = next(r for r in state['rows'] if r['item']['id'] == world.brick)
    assert (brick['missing'], brick['quantity'], brick['damaged'], brick['checked'], brick['color']['id']) == (1, 4, 0, False, world.red)
    figure = next(r for r in state['rows'] if r['kind'] == 'figure')
    assert (figure['damaged'], figure['checked'], figure['parts_lines'], figure['parts_missing']) == (None, None, 4, 0)
    coll.sql("INSERT INTO part_check(copy_id,session_id,order_mode,session_json,started_at,updated_at) VALUES(?,'s1','inventory',?,'2026-10-26T12:00:00.000Z','2026-10-26T12:00:00.000Z')",
             (world.copy_a, '{"order":["p:1","p:3"],"cursor":1,"answers":{"p:1":"answered"},"misses":[],"undo":[]}'))
    session = data(call(v2, f'/copies/{world.copy_a}/check'))['session']
    assert session['id'] == 's1' and session['cursor'] == 1 and session['answers'] == {'p:1': 'answered'} and session['finished'] is False
    assert session['sort'] == 'inventory' and 'saved_at' in session


# --- the lines of a copy
def test_part_lines_have_item_colour_parent_and_state(v2, world):
    parts = data(call(v2, f'/copies/{world.copy_a}/parts?limit=200'))
    assert [p['id'] for p in parts] == [1, 2, 3, 4, 5, 6, 7]
    first = parts[0]
    assert (first['item']['id'], first['color']['id'], first['spare'], first['quantity'], first['missing'], first['damaged'], first['checked'], first['copy_id']) == (
        world.brick, world.red, 0, 4, 1, 0, False, world.copy_a) and first['parent_minifig'] is None
    assert parts[3]['parent_minifig']['id'] == world.figure and parts[3]['name'] == 'Minifig Head Standard Grin Print [Solid Stud]'
    assert [p['id'] for p in data(call(v2, f'/copies/{world.copy_a}/parts?spare=1'))] == [2]
    assert [p['id'] for p in data(call(v2, f'/copies/{world.copy_a}/parts?spare=0&parent=null'))] == [1, 3]
    assert [p['id'] for p in data(call(v2, f'/copies/{world.copy_a}/parts?parent=fig-000004'))] == [4, 5, 6, 7]
    assert [p['id'] for p in data(call(v2, f'/copies/{world.copy_a}/parts?parent=syn-fig-0004'))] == [4, 5, 6, 7]                # the figure's BrickLink number too
    assert [p['id'] for p in data(call(v2, f'/copies/{world.copy_a}/parts?problem=missing'))] == [1]
    assert call(v2, f'/copies/{world.copy_a}/parts?spare=2').status_code == 400
    assert [p['id'] for p in data(call(v2, f'/copies/{world.copy_a}/parts?direction=desc&limit=2'))] == [7, 6]


def test_a_line_a_switch_retired_is_no_line(v2, coll, world):
    coll.retire_line(world.copy_a, '3023', '15')
    assert 3 not in [p['id'] for p in data(call(v2, f'/copies/{world.copy_a}/parts?limit=200'))]
    assert call(v2, f'/copies/{world.copy_a}/parts?limit=200').json['page']['total'] == 6


def test_whole_figures_of_a_copy(v2, coll, world):
    assert data(call(v2, f'/copies/{world.copy_a}/figures')) == [{
        'item': data(call(v2, f'/items/{world.figure}')), 'name': 'Man, White Torso, Black Legs, Brown Hair', 'quantity': 2, 'missing': 0,
        'parts_lines': 4, 'parts_missing': 0}]
    coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    coll.mark(world.copy_a, '3626apr0001', '14', missing=1, figure='fig-000004')
    figure = data(call(v2, f'/copies/{world.copy_a}/figures'))[0]
    assert (figure['missing'], figure['parts_missing']) == (1, 1)
    assert data(call(v2, f'/copies/{world.copy_c}/figures')) == []


# --- gaps and matches of a copy and of everything
def test_the_gaps_of_a_copy(v2, world):
    gaps = data(call(v2, f'/copies/{world.copy_a}/gaps'))
    assert {(g['target'], g['item']['id'], g['need']) for g in gaps} == {('part', world.brick, 1), ('box', world.keep, 1), ('instructions', world.keep, 1)}
    part = next(g for g in gaps if g['target'] == 'part')
    assert (part['copy_id'], part['target_id'], part['color']['id'], part['unresolved'], part['name']) == (world.copy_a, 1, world.red, False, 'Brick 2 x 4')
    booklet = next(g for g in gaps if g['target'] == 'instructions')
    assert (booklet['target_id'], booklet['color'], booklet['name']) == (world.copy_a, None, 'Instructions missing')
    assert {g['copy_id'] for g in data(call(v2, f'/copies/{world.copy_a}/gaps'))} == {world.copy_a}


def test_a_status_flag_removes_the_gap_it_stands_for(v2, coll, world):
    coll.tag('copy', world.copy_a, world.box)
    assert {g['target'] for g in data(call(v2, f'/copies/{world.copy_a}/gaps'))} == {'part', 'instructions'}


def test_a_missing_figure_is_a_gap_on_its_line(v2, coll, world):
    coll.mark_figure(world.copy_c, 'fig-000004', missing=1) if coll.db.execute('SELECT 1 FROM copy_figure WHERE copy_id=?', (world.copy_c,)).fetchone() else coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    figures = [g for g in data(call(v2, '/gaps?limit=200')) if g['target'] == 'figure']
    assert len(figures) == 1 and figures[0]['item']['id'] == world.figure and figures[0]['color'] is None and figures[0]['need'] == 1


def test_a_loose_figure_with_a_missing_part_is_a_gap_of_its_stock_line(v2, coll, world):
    coll.sql('UPDATE stock_part SET missing=1 WHERE stock_id=? AND item_id=?', (world.stock_figure, coll.item('parts', '3901')))
    gaps = [g for g in data(call(v2, '/gaps?limit=200')) if g['target'] == 'stock-part']
    assert len(gaps) == 1 and gaps[0]['copy_id'] == world.stock_figure and gaps[0]['item']['id'] == coll.item('parts', '3901')
    assert gaps[0]['color']['id'] == coll.colour('6')


def test_all_gaps_filter_by_kind_number_colour_and_copy(v2, coll, world):
    everything = data(call(v2, '/gaps?limit=200'))
    assert {g['target'] for g in everything} == {'part', 'box', 'instructions'} and len(everything) == 7
    assert {g['target'] for g in data(call(v2, '/gaps?kind=part'))} == {'part'}
    assert [g['copy_id'] for g in data(call(v2, '/gaps?number=3001'))] == [world.copy_a]
    assert [g['copy_id'] for g in data(call(v2, '/gaps?number=3001&color=5'))] == [world.copy_a]                      # BrickLink 5 is red
    assert data(call(v2, '/gaps?number=3001&color=11')) == []
    assert call(v2, '/gaps?number=3001&provider=brickwork').status_code == 422                                          # a Brick Work id is not a number
    assert [g['copy_id'] for g in data(call(v2, f'/gaps?provider=brickwork&color={world.red}'))] == [world.copy_a]                 # but a Brick Work colour id is fine
    assert {g['copy_id'] for g in data(call(v2, f'/gaps?copy_id={world.copy_b}'))} == {world.copy_b}


def test_matches_name_the_loose_stock_that_fills_a_gap(v2, coll, world):
    matches = data(call(v2, f'/copies/{world.copy_a}/matches'))
    brick = [m for m in matches if m['target'] == 'part']
    assert {m['source_id']: (m['have'], m['suggested']) for m in brick} == {world.stock_brick: (3, 1), world.stock_brick_new: (2, 1)}
    assert all(m['completes'] is True and m['item']['id'] == world.brick and m['color']['id'] == world.red for m in brick)
    booklet = [m for m in matches if m['target'] == 'instructions']
    assert [m['source_id'] for m in booklet] == [world.stock_booklet] and booklet[0]['item']['id'] == world.keep


def test_matches_filter_by_what_completes_a_copy(v2, coll, world):
    assert {m['target'] for m in data(call(v2, '/matches?completes=true'))} == {'part'}
    assert {m['target'] for m in data(call(v2, '/matches?completes=false'))} == {'instructions'}
    assert {m['copy_id'] for m in data(call(v2, f'/matches?copy_id={world.copy_b}'))} == {world.copy_b}
    assert [m['source_id'] for m in data(call(v2, '/matches?number=3001&color=5&completes=true'))] and call(v2, '/matches?completes=maybe').status_code == 400


def test_a_match_is_not_offered_from_damaged_stock(v2, coll, world):
    coll.sql("UPDATE stock SET condition='damaged' WHERE id=?", (world.stock_brick,))
    assert world.stock_brick not in {m['source_id'] for m in data(call(v2, f'/copies/{world.copy_a}/matches'))}


def test_the_matches_page_tells_sources_of_one_gap_apart(v2, coll, world):
    brick, red = world.brick, world.red
    for n in range(10):
        coll.add_stock('part', brick, colour=red, quantity=n + 1, condition='used', note=f'lot {n}', storage=coll.storage(f'Drawer {n}'))
    seen, cursor = [], None
    while True:
        response = call(v2, f'/copies/{world.copy_a}/matches?' + urlencode(dict(limit=3, **({'cursor': cursor} if cursor else {}))))
        seen += [m['source_id'] for m in data(response) if m['target'] == 'part']
        cursor = response.json['page']['next_cursor']
        if not cursor:
            break
    assert len(seen) == 12 and len(set(seen)) == 12


# --- loose stock
def test_stock_lines_are_the_stock_body(v2, world):
    line = data(call(v2, f'/stock/{world.stock_brick}'))
    assert line['item']['id'] == world.brick and line['color']['id'] == world.red and (line['quantity'], line['condition']) == (3, 'used')
    assert (line['storage_id'], line['lot_id'], line['merged_ids'], line['missing'], line['damaged'], line['flags'], line['archived_at']) == (
        world.shelf, world.bag, [], None, None, [], None)
    assert call(v2, f'/stock/{world.stock_brick}').headers['ETag'] == f'"{line["etag"]}"'
    assert len(data(call(v2, '/stock?limit=200'))) == 7


def test_stock_filters(v2, world):
    assert set(ids(call(v2, '/stock?number=3001&color=5'))) == {world.stock_brick, world.stock_brick_new} and ids(call(v2, '/stock?number=3001&color=1')) == []
    assert set(ids(call(v2, f'/stock?lot={world.bag}'))) == {world.stock_brick} and set(ids(call(v2, f'/stock?storage={world.shelf}'))) == {world.stock_brick}
    assert world.stock_brick not in ids(call(v2, '/stock?lot=null')) and len(ids(call(v2, '/stock?storage=null&limit=200'))) == 6
    assert set(ids(call(v2, '/stock?kind=minifigure'))) == {world.stock_figure} and set(ids(call(v2, '/stock?kind=gear'))) == {world.stock_mystery}
    assert set(ids(call(v2, '/stock?condition=new&limit=200'))) == {world.stock_brick_new, world.stock_plate, world.stock_mystery}
    assert ids(call(v2, '/stock?kind=set')) == []
    assert set(ids(call(v2, '/stock?q=red&color=5'))) == {world.stock_brick, world.stock_brick_new, world.stock_local}      # the colour filter keeps the name searchable
    assert ids(call(v2, '/stock?q=brick%202&color=5&condition=used')) == [world.stock_brick]
    assert call(v2, '/stock?kind=widget').status_code == 422


def test_a_colour_filter_names_the_colour_in_the_providers_space(v2, world):
    by_bricklink = set(ids(call(v2, '/stock?color=5')))
    assert by_bricklink == set(ids(call(v2, '/stock?color=4&provider=rebrickable'))) == set(ids(call(v2, f'/stock?color={world.red}&provider=brickwork')))
    assert world.stock_brick in by_bricklink and world.stock_local in by_bricklink
    assert call(v2, '/stock?color=999').status_code == 422


def test_stock_problems_are_the_figures_that_miss_or_have_damaged_parts(v2, coll, world):
    coll.sql('UPDATE stock SET missing=1 WHERE id=?', (world.stock_figure,))
    assert ids(call(v2, '/stock?problem=missing')) == [world.stock_figure] and ids(call(v2, '/stock?problem=damaged')) == []


def test_archived_stock_is_hidden_and_read_by_id(v2, coll, world):
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', world.stock_brick))
    assert world.stock_brick not in ids(call(v2, '/stock?limit=200')) and ids(call(v2, '/stock?archived=only')) == [world.stock_brick]
    one = call(v2, f'/stock/{world.stock_brick}')
    assert one.status_code == 200 and one.headers['ETag'] and one.json['data']['archived_at']
    assert call(v2, '/stock/absent').status_code == 404 and call(v2, '/stock/' + 'x' * 70).status_code == 404 and call(v2, '/stock/absent/parts').status_code == 404


def test_the_parts_of_a_loose_figure(v2, coll, world):
    parts = data(call(v2, f'/stock/{world.stock_figure}/parts'))
    assert len(parts) == 4 and all(p['stock_id'] == world.stock_figure and p['item']['kind'] == 'part' for p in parts)
    head = next(p for p in parts if p['item']['rebrickable']['key'] == '3626apr0001')
    assert (head['color']['id'], head['quantity'], head['missing'], head['damaged'], head['checked'], head['spare']) == (coll.colour('14'), 1, 0, 0, False, 0)
    assert data(call(v2, f'/stock/{world.stock_brick}/parts')) == []
    coll.sql('UPDATE stock_part SET retired_at=? WHERE stock_id=? AND item_id=?', ('2026-10-27T00:00:00.000Z', world.stock_figure, head['item']['id']))
    assert len(data(call(v2, f'/stock/{world.stock_figure}/parts'))) == 3


# --- figures by identity
def test_figures_by_identity_count_loose_in_sets_and_missing(v2, coll, world):
    rows = data(call(v2, '/minifigures'))
    assert rows == [{'item': data(call(v2, f'/items/{world.figure}')), 'name': 'Man, White Torso, Black Legs, Brown Hair', 'theme': None, 'year': None,
                     'quantity': 1, 'in_sets': 4, 'missing': 0, 'damaged': 0, 'image_id': None}]
    coll.mark_figure(world.copy_a, 'fig-000004', missing=1)
    coll.sql('UPDATE stock_part SET missing=1, damaged=0 WHERE stock_id=? AND item_id=?', (world.stock_figure, coll.item('parts', '3901')))
    row = data(call(v2, '/minifigures'))[0]
    assert row['missing'] >= 1
    assert ids_of(call(v2, '/minifigures?problem=missing')) == [world.figure] and ids_of(call(v2, '/minifigures?problem=damaged')) == []
    assert ids_of(call(v2, '/minifigures?q=black%20legs')) == [world.figure] and ids_of(call(v2, '/minifigures?q=zzz')) == []
    assert ids_of(call(v2, '/minifigures?inventory=figures')) == [world.figure] and ids_of(call(v2, '/minifigures?inventory=instructions')) == []
    assert ids_of(call(v2, '/minifigures?color=5')) == []


def ids_of(response):
    return [r['item']['id'] for r in data(response)]


def test_a_loose_only_figure_is_a_row_too(v2, coll, world):
    local = coll.local('minifigure', 'Local figure', born_key='syn-loc-1', year=2020)
    coll.add_stock('minifigure', local, quantity=3, condition='used', source='none')
    rows = {r['item']['id']: r for r in data(call(v2, '/minifigures'))}
    assert rows[local]['quantity'] == 3 and rows[local]['in_sets'] == 0 and rows[local]['year'] == 2020 and rows[local]['item']['unidentified'] is True
    assert ids_of(call(v2, '/minifigures?year=2020')) == [local]
