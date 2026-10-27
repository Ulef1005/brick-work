"""API v2 reads of prices, wishes, wishlists, Complete sets and the exports (M.11b, issue #113).
Ported from the price, wish and export reads of test_bw_api_m2, test_bw_lists_43_api (the export reads), test_bw_wishlists_api (the reads),
test_bw_wish_progress_35_api and test_bw_currency_39_api (the comparison across currencies) onto the 4.0 fixtures. Invented data."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from tests.api2 import call, v2  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def data(response):
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json['data']


def ids(response):
    return [r['id'] for r in data(response)]


def stamp(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def market(coll, item, price, colour=None, **more):
    """A quote Complete sets accepts: used, sold, fresh, in the BrickLink region and currency."""
    return coll.price(item, price, colour=colour, **{'condition': 'used', 'region': 'eu', 'observed': stamp(), **more})


# --- prices
def test_current_prices_are_one_per_item_colour_condition_and_guide(v2, world):
    rows = data(call(v2, '/prices?limit=200'))
    assert len(rows) == 3
    keep = next(r for r in rows if r['observation']['item']['id'] == world.keep)['observation']
    assert (keep['price'], keep['min'], keep['max'], keep['sold'], keep['condition'], keep['guide'], keep['source'], keep['currency']) == (
        '30.00', '25.00', '35.00', 4, 'used', 'sold', 'bricklink', 'EUR')
    assert keep['color'] is None and keep['id'] > 0 and keep['observed_at'] and keep['error'] is None
    row = next(r for r in rows if r['observation']['item']['id'] == world.brick)
    assert row['observation']['color']['id'] == world.red and isinstance(row['age_days'], int) and row['stale'] is False


def test_prices_filter_by_kind_number_colour_condition_guide_and_source(v2, coll, world):
    coll.price(world.brick, '0.55', colour=world.red, condition='new')
    coll.price(world.brick, '0.70', colour=world.red, condition='used', guide='stock', source='bricklink')
    coll.price(world.keep, '99.00', condition='new', guide='retail', source='brickset', region='DE', slot='retail')
    assert len(data(call(v2, '/prices?limit=200'))) == 6
    assert {r['observation']['item']['kind'] for r in data(call(v2, '/prices?kind=part'))} == {'part'}
    assert len(data(call(v2, '/prices?number=3001&color=5'))) == 3 and data(call(v2, '/prices?number=3001&color=1')) == []
    assert {r['observation']['condition'] for r in data(call(v2, '/prices?condition=new&limit=200'))} == {'new'}
    assert {r['observation']['guide'] for r in data(call(v2, '/prices?guide=retail'))} == {'retail'}
    assert {r['observation']['source'] for r in data(call(v2, '/prices?source=brickset'))} == {'brickset'}
    assert len(data(call(v2, '/prices?number=1000-1&provider=rebrickable'))) == 2 and call(v2, '/prices?color=zebra').status_code == 422


def test_a_price_is_stale_by_the_freshness_rule_of_its_source(v2, coll, world):
    coll.sql("INSERT INTO source_freshness(source,kind,max_age_days) VALUES('bricklink','prices',3) ON CONFLICT(source,kind) DO UPDATE SET max_age_days=3")
    coll.price(world.plate, '0.20', colour=world.white, observed=stamp(10))
    coll.price(world.duplo, '9.00', observed=stamp(1))
    rows = {r['observation']['item']['id']: r for r in data(call(v2, '/prices?limit=200'))}
    assert rows[world.plate]['stale'] is True and rows[world.plate]['age_days'] == 10 and rows[world.duplo]['stale'] is False


def test_a_voided_observation_never_shows(v2, coll, world):
    identifier = coll.price(world.plate, '0.20', colour=world.white)
    coll.sql('UPDATE price_observation SET voided_at=? WHERE id=?', (stamp(), identifier))
    assert world.plate not in [r['observation']['item']['id'] for r in data(call(v2, '/prices?limit=200'))]
    assert data(call(v2, f'/items/{world.plate}/prices')) == {'current': [], 'records': []}
    assert data(call(v2, f'/items/{world.plate}/prices/history')) == []


def test_the_prices_of_one_item_are_current_and_recorded(v2, coll, world):
    coll.price(world.brick, '0.35', colour=world.red, observed=stamp(5))
    coll.price(world.brick, '0.30', colour=world.white, observed=stamp(3))
    prices = data(call(v2, f'/items/{world.brick}/prices'))
    assert set(prices) == {'current', 'records'} and len(prices['records']) == 3
    assert [r['price'] for r in prices['records']] == ['0.40', '0.30', '0.35']                    # by when they were observed, newest first
    assert {c['observation']['price'] for c in prices['current']} == {'0.35', '0.30'}             # the current one per colour is the last recorded
    red = data(call(v2, f'/items/{world.brick}/prices?color=5'))                                   # BrickLink 5 is red
    assert {r['observation']['color']['id'] for r in red['current']} == {world.red} and {r['color']['id'] for r in red['records']} == {world.red}
    by_brickwork = data(call(v2, f'/items/{world.brick}/prices?color={world.white}&provider=brickwork'))
    assert {r['observation']['color']['id'] for r in by_brickwork['current']} == {world.white}
    assert call(v2, f'/items/{world.brick}/prices?color=999').status_code == 422


def test_the_price_history_pages_newest_first_and_filters(v2, coll, world):
    for days in range(6):
        coll.price(world.brick, str(0.1 * days + 0.4), colour=world.red, observed=stamp(days + 1))
    coll.price(world.brick, '0.9', colour=world.red, condition='new', observed=stamp(2))
    everything = data(call(v2, f'/items/{world.brick}/prices/history?limit=200'))
    assert len(everything) == 8 and [r['id'] for r in everything] == sorted([r['id'] for r in everything], reverse=True)
    assert [r['id'] for r in data(call(v2, f'/items/{world.brick}/prices/history?direction=asc&limit=3'))] == sorted(r['id'] for r in everything)[:3]
    seen, cursor = [], None
    while True:
        page = call(v2, f'/items/{world.brick}/prices/history?' + urlencode(dict(limit=3, **({'cursor': cursor} if cursor else {}))))
        seen += [r['id'] for r in data(page)]
        cursor = page.json['page']['next_cursor']
        if not cursor:
            break
    assert seen == [r['id'] for r in everything]
    assert {r['condition'] for r in data(call(v2, f'/items/{world.brick}/prices/history?condition=new'))} == {'new'}
    assert call(v2, f'/items/{world.brick}/prices/history?condition=null').json['data'] == []
    assert call(v2, f'/items/{world.brick}/prices/history?cursor=x').status_code == 400 and call(v2, f'/items/{world.brick}/prices/history?direction=up').status_code == 400


def test_the_price_history_page_is_one_query_in_a_long_log(v2, coll, world, monkeypatch):
    from tests.test_api2_reads import Counting
    coll.db.executemany("INSERT INTO price_observation(item_id,color_id,condition,guide,currency,price,source,observed_at) VALUES(?,?,'used','sold','EUR','0.50','bricklink',?)",
                        [(world.brick, world.red, stamp(1))] * 5000)
    coll.db.commit()
    counting = Counting(monkeypatch)
    response = call(v2, f'/items/{world.brick}/prices/history?limit=1')
    assert response.status_code == 200 and len(response.json['data']) == 1 and response.json['page']['next_cursor']
    assert len([q for q in counting.queries if 'price_observation' in q]) == 1


def test_stale_prices_name_the_line_that_is_held_or_wanted(v2, coll, world):
    rows = data(call(v2, '/prices/stale?limit=200'))
    seen = {(r['item']['id'], (r['color'] or {}).get('id'), r['condition'], r['source_table']) for r in rows}
    assert (world.keep, None, 'new', 'copy') in seen and (world.plate, world.white, 'new', 'stock') in seen and (world.plate, world.white, 'new', 'wish') in seen
    assert (world.duplo, None, 'used', 'copy') in seen and (world.mystery, None, 'new', 'stock') not in seen        # an unidentified item cannot be priced
    assert all(r['name'] for r in rows)
    market(coll, world.duplo, '9.00')
    assert (world.duplo, None, 'used', 'copy') not in {(r['item']['id'], (r['color'] or {}).get('id'), r['condition'], r['source_table']) for r in data(call(v2, '/prices/stale?limit=200'))}


# --- wishes (and the progress of a wished line, #35)
def test_a_wish_is_the_wish_body_with_its_progress_and_price_comparison(v2, coll, world):
    wish = data(call(v2, f'/wishes/{world.wish_part}'))
    assert wish['item']['id'] == world.plate and wish['color']['id'] == world.white and (wish['quantity'], wish['condition'], wish['list_id']) == (2, 'new', 'default')
    assert (wish['max_price'], wish['max_price_currency'], wish['under_max'], wish['current_price']) == ('0.50', 'EUR', None, None)
    assert (wish['qty_filled'], wish['qty_filled_source'], wish['qty_filled_manual']) == (2, 'derived', None)             # two new plates are loose
    assert call(v2, f'/wishes/{world.wish_part}').headers['ETag'] == f'"{wish["etag"]}"'
    assert data(call(v2, f'/wishes/{world.wish_set}'))['qty_filled'] == 0


def test_a_manual_progress_overrides_the_derived_one(v2, coll, world):
    coll.sql('UPDATE wish SET qty_filled_manual=1 WHERE id=?', (world.wish_part,))
    wish = data(call(v2, f'/wishes/{world.wish_part}'))
    assert (wish['qty_filled'], wish['qty_filled_source'], wish['qty_filled_manual']) == (1, 'manual', 1)
    tag = call(v2, f'/wishes/{world.wish_part}').headers['ETag']
    coll.sql('UPDATE wish SET qty_filled_manual=0 WHERE id=?', (world.wish_part,))
    assert call(v2, f'/wishes/{world.wish_part}').headers['ETag'] != tag


def test_a_wish_is_under_its_maximum_when_the_price_is_in_the_same_currency(v2, coll, world):
    coll.price(world.plate, '0.40', colour=world.white, condition='new')
    assert data(call(v2, f'/wishes/{world.wish_part}'))['under_max'] is True and data(call(v2, f'/wishes/{world.wish_part}'))['current_price'] == '0.40'
    assert ids(call(v2, '/wishes?under_max=true')) == [world.wish_part] and ids(call(v2, '/wishes?under_max=false')) == []
    coll.price(world.plate, '0.60', colour=world.white, condition='new', observed=stamp(-1))
    over = data(call(v2, f'/wishes/{world.wish_part}'))
    assert over['under_max'] is False and over['current_price'] == '0.60'
    assert ids(call(v2, '/wishes?under_max=false')) == [world.wish_part]


def test_a_price_in_another_currency_is_never_compared_without_a_rate(v2, coll, world):
    coll.price(world.plate, '0.40', colour=world.white, condition='new', currency='USD')
    assert data(call(v2, f'/wishes/{world.wish_part}'))['under_max'] is None
    assert ids(call(v2, '/wishes?under_max=true')) == [] and ids(call(v2, '/wishes?under_max=false')) == []


def test_a_rate_makes_two_currencies_comparable(v2, coll, world):
    coll.price(world.plate, '0.40', colour=world.white, condition='new', currency='USD')
    coll.sql("INSERT INTO exchange_rate(currency,per_eur,as_of,source) VALUES('USD','2.00','2026-10-26','manual')")           # 0.40 USD is 0.20 EUR
    assert data(call(v2, f'/wishes/{world.wish_part}'))['under_max'] is True
    coll.sql("UPDATE exchange_rate SET per_eur='0.50'")                                                                       # 0.40 USD is 0.80 EUR
    assert data(call(v2, f'/wishes/{world.wish_part}'))['under_max'] is False


def test_wishes_filter_by_list_kind_number_condition_flag_and_text(v2, coll, world):
    coll.sql("INSERT INTO wishlist(id,name,sort,created_at) VALUES('second','Second list',1,'2026-10-26T12:00:00.000Z')")
    second = coll.add_wish(world.brick, colour=world.red, quantity=1, condition='used', wishlist='second')
    coll.tag('wish', second, world.tag)
    assert set(ids(call(v2, '/wishes'))) == {world.wish_set, world.wish_part, second}
    assert ids(call(v2, '/wishes?list=second')) == [second] and ids(call(v2, '/wishes?list=nothing')) == []
    assert ids(call(v2, '/wishes?kind=set')) == [world.wish_set] and ids(call(v2, '/wishes?number=3023')) == [world.wish_part]
    assert ids(call(v2, '/wishes?number=3001&color=5')) == [second] and ids(call(v2, '/wishes?number=3001&color=1')) == []
    assert ids(call(v2, '/wishes?condition=any')) == [world.wish_set] and set(ids(call(v2, '/wishes?condition=new'))) == {world.wish_part}
    assert ids(call(v2, f'/wishes?flag={world.tag}')) == [second] and ids(call(v2, '/wishes?q=gate')) == [world.wish_set]
    assert call(v2, '/wishes?under_max=maybe').status_code == 400 and call(v2, '/wishes?kind=widget').status_code == 422


def test_archived_wishes_are_hidden_until_asked_for(v2, coll, world):
    coll.sql('UPDATE wish SET archived_at=? WHERE id=?', (stamp(), world.wish_set))
    assert ids(call(v2, '/wishes')) == [world.wish_part] and ids(call(v2, '/wishes?archived=only')) == [world.wish_set]
    assert set(ids(call(v2, '/wishes?archived=include'))) == {world.wish_set, world.wish_part}
    one = call(v2, f'/wishes/{world.wish_set}')
    assert one.status_code == 200 and one.json['data']['archived_at'] and one.headers['ETag']
    assert call(v2, '/wishes/absent').status_code == 404 and call(v2, f'/wishes/{"x" * 70}').status_code == 404 and call(v2, '/wishes/1').status_code == 404


def test_wish_ids_are_uuid_text_and_sort_orders_apply(v2, coll, world):
    assert all(len(w) == 32 for w in ids(call(v2, '/wishes')))
    assert ids(call(v2, '/wishes?sort=name'))[0] == world.wish_part and ids(call(v2, '/wishes?sort=name&direction=desc'))[0] == world.wish_set
    market(coll, world.gate, '20.00')
    assert call(v2, '/wishes?sort=used_price&direction=desc').status_code == 200 and call(v2, '/wishes?sort=quantity&direction=desc').json['data'][0]['id'] == world.wish_part


# --- wishlists and their exports
def test_wishlists_are_listed_with_their_counts(v2, coll, world):
    lists = data(call(v2, '/wishlists'))
    assert lists == [{'archived_at': None, 'bricklink_id': None, 'count': 2, 'created_at': lists[0]['created_at'], 'id': 'default', 'name': 'Wishlist', 'note': None, 'sort': 0}]
    coll.sql("INSERT INTO wishlist(id,name,sort,created_at,archived_at) VALUES('old','Old list',2,'2026-10-26T12:00:00.000Z','2026-10-27T00:00:00.000Z')")
    coll.sql("INSERT INTO wishlist(id,name,sort,created_at) VALUES('new','New list',1,'2026-10-26T12:00:00.000Z')")
    assert ids(call(v2, '/wishlists')) == ['default', 'new'] and ids(call(v2, '/wishlists?archived=true')) == ['default', 'new', 'old']
    assert ids(call(v2, '/wishlists?direction=desc')) == ['new', 'default'] and call(v2, '/wishlists?archived=maybe').status_code == 400


def test_a_wishlist_exports_as_a_bricklink_wanted_list(v2, coll, world):
    response = call(v2, '/wishlists/default/export.xml')
    assert response.status_code == 200 and response.mimetype == 'application/xml'
    assert response.headers['Content-Disposition'] == 'attachment; filename=wishlist.xml' and response.headers['X-Wishlist-Exported'] == '2'
    items = ET.fromstring(response.data).findall('ITEM')
    plate = next(i for i in items if i.findtext('ITEMTYPE') == 'P')
    assert (plate.findtext('ITEMID'), plate.findtext('COLOR'), plate.findtext('MINQTY'), plate.findtext('MAXPRICE'), plate.findtext('CONDITION'), plate.findtext('QTYFILLED')) == (
        '3023', '1', '2', '0.50', 'N', '2')
    assert next(i for i in items if i.findtext('ITEMTYPE') == 'S').findtext('ITEMID') == '1000-2'


def test_an_export_lists_what_it_leaves_out_instead_of_inventing_numbers(v2, coll, world):
    coll.add_wish(world.mystery, quantity=1)
    summary = data(call(v2, '/wishlists/all/export.xml?summary=true'))
    assert summary['summary']['exported'] == 2 and summary['summary']['omitted'] == [{'id': summary['summary']['omitted'][0]['id'], 'item_no': 'Mystery thing', 'reason': 'No BrickLink number'}]
    assert summary['filename'] == 'wishlist.xml' and summary['mimetype'] == 'application/xml' and '3023' in summary['content']
    csv = call(v2, '/wishlists/default/export.csv?kind=parts')
    assert csv.mimetype == 'text/csv' and csv.data.decode().splitlines() == ['Part,Color,Quantity', '3023,15,2']
    assert call(v2, '/wishlists/default/export.csv?kind=sets').data.decode().splitlines() == ['Set Number,Quantity', '1000-2,1']
    assert call(v2, '/wishlists/default/export.csv?kind=widget').status_code == 422 and call(v2, '/wishlists/default/export.xml?summary=maybe').status_code == 400


def test_an_unknown_or_archived_wishlist_does_not_export(v2, coll, world):
    coll.sql("INSERT INTO wishlist(id,name,sort,created_at,archived_at) VALUES('old','Old list',2,'2026-10-26T12:00:00.000Z','2026-10-27T00:00:00.000Z')")
    assert call(v2, '/wishlists/nothing/export.xml').status_code == 404 and call(v2, '/wishlists/old/export.csv').status_code == 409
    assert call(v2, '/wishlists/all/export.csv').status_code == 200


# --- Complete sets
def test_the_ranking_prices_each_repair_and_orders_by_the_gain_per_unit_spent(v2, coll, world):
    market(coll, world.keep, '30.00')
    market(coll, world.brick, '0.40', world.red)
    rows = data(call(v2, '/planning/ranking'))
    assert [r['id'] for r in rows] == [world.copy_a] + [r['id'] for r in rows[1:]]
    top = rows[0]
    assert (top['group'], top['rank'], top['value_when_complete'], top['current_value'], top['repair_cost'], top['gross_gain'], top['net_gain']) == (
        'ranked', 1, '30.00', '21.00', '3.90', '9.00', '5.10')
    assert top['ratio'].startswith('2.3076') and top['breakdown'] == {'items': '0.40', 'shipping': '3.00', 'fees': '0.50', 'minimum_order_extra': '0'}
    assert top['valuation_basis'] == 'default discount estimate' and top['reasons'] == [] and top['item']['id'] == world.keep
    assert [(l['item']['id'], l['missing'], l['original_gap'], l['stock_used'], l['quote']['price']) for l in top['items']] == [(world.brick, 1, 1, 0, '0.40')]
    assert top['complete_quote']['price'] == '30.00' and (top['missing_count'], top['missing_parts'], top['missing_figures'], top['missing'], top['damaged']) == (1, 1, 0, 1, 0)
    assert call(v2, '/planning/ranking').json['settings'] == {
        'bricklink_region': 'eu', 'bricklink_currency': 'EUR', 'incomplete_discount_pct': 30.0,
        'repair': {'shipping': '3.00', 'fees': '0.50', 'min_order': '0', 'use_loose_stock': False}}


def test_a_copy_without_evidence_says_what_is_missing(v2, coll, world):
    rows = {r['id']: r for r in data(call(v2, '/planning/ranking'))}
    assert rows[world.copy_a]['group'] == 'needs_evidence' and rows[world.copy_a]['rank'] is None and rows[world.copy_a]['repair_cost'] is None
    assert any('no complete value' in reason for reason in rows[world.copy_a]['reasons']) and rows[world.copy_a]['unresolved_items'] == len(rows[world.copy_a]['reasons'])


def test_the_loose_stock_pays_for_a_repair_when_the_settings_allow_it(v2, coll, world):
    market(coll, world.keep, '30.00')
    market(coll, world.brick, '0.40', world.red)
    coll.setting('repair_use_loose_stock', '1')
    top = data(call(v2, '/planning/ranking'))[0]
    assert top['items'][0]['stock_used'] == 1 and top['items'][0]['missing'] == 0 and top['original_gap'] == 1 and top['stock_used'] == 1 and top['missing_count'] == 0
    assert top['repair_cost'] == '3.50' and top['breakdown']['items'] == '0'                       # the postage and fees remain


def test_a_pinned_copy_keeps_its_rank_but_comes_first(v2, coll, world):
    market(coll, world.keep, '30.00')
    market(coll, world.brick, '0.40', world.red)
    coll.mark(world.copy_b, '3023', '15', missing=1)
    market(coll, world.plate, '0.05', world.white)
    coll.sql('UPDATE copy SET pinned=1, condition=? WHERE id=?', ('used', world.copy_b))
    rows = data(call(v2, '/planning/ranking?limit=200'))
    ranked = [r for r in rows if r['group'] == 'ranked']
    assert len(ranked) == 2 and ranked[0]['pinned'] is True and ranked[0]['id'] == world.copy_b and {r['rank'] for r in ranked} == {1, 2}


def test_the_ranking_pages_in_core_order_and_a_new_copy_does_not_disturb_the_cursor(v2, coll, world):
    market(coll, world.keep, '30.00')
    market(coll, world.brick, '0.40', world.red)
    market(coll, world.gate, '60.00')
    market(coll, world.plate, '0.10', world.white)
    second = coll.add_copy('1000-2', condition='used')
    coll.mark(second, '3023', '15', missing=1)
    first = call(v2, '/planning/ranking?limit=1')
    assert first.status_code == 200 and len(first.json['data']) == 1 and first.json['page']['next_cursor']
    leader = first.json['data'][0]['id']
    third = coll.add_copy('1000-2', condition='used')
    coll.mark(third, '3023', '15', missing=1)
    rest = call(v2, '/planning/ranking?' + urlencode(dict(limit=50, cursor=first.json['page']['next_cursor'])))
    assert rest.status_code == 200 and leader not in [r['id'] for r in rest.json['data']] and world.copy_a in [r['id'] for r in rest.json['data']] + [leader]


def test_the_ranking_filters_by_text_and_sorts_by_name(v2, coll, world):
    assert [r['id'] for r in data(call(v2, '/planning/ranking?q=castle'))] == [world.copy_a]
    assert data(call(v2, '/planning/ranking?q=rabbit')) == [] and call(v2, '/planning/ranking?sort=name').status_code == 200 and call(v2, '/planning/ranking?sort=bogus').status_code == 400


# --- the printable and portable lists
def test_the_missing_list_as_csv_names_every_line_and_marks_the_unmatched(v2, coll, world):
    response = call(v2, f'/export/missing.csv?copy_id={world.copy_a}')
    assert response.mimetype == 'text/csv' and response.headers['Content-Disposition'] == 'attachment; filename=brickwork-missing.csv'
    assert response.data.decode().splitlines() == ['Item type,Item number,Name,Colour,Colour id,Condition,Quantity,Note', 'P,3001,Brick 2 x 4,Red,4,Used,1,']
    assert call(v2, f'/export/missing.csv?ids={world.copy_a},{world.copy_b}').status_code == 200
    for query in ('', 'copy_id=nothing', f'copy_id={world.copy_a}&copy_id={world.copy_a}', 'ids='):
        assert call(v2, '/export/missing.csv?' + query).status_code in (422,), query


def test_the_missing_list_as_xml_and_json_share_one_set_of_rules(v2, coll, world):
    xml = call(v2, f'/export/missing.xml?copy_id={world.copy_a}')
    assert xml.mimetype == 'application/xml' and xml.headers['Content-Disposition'] == 'attachment; filename=brickwork-missing.xml'
    item = ET.fromstring(xml.data).find('ITEM')
    assert [(c.tag, c.text) for c in item] == [('ITEMTYPE', 'P'), ('ITEMID', '3001'), ('COLOR', '5'), ('MINQTY', '1'), ('CONDITION', 'U')]
    body = call(v2, f'/export/missing.json?copy_id={world.copy_a}').json
    assert [(l['item']['id'], l['color']['id'], l['quantity'], l['condition'], l['bricklink']) for l in body['data']] == [
        (world.brick, world.red, 1, 'used', {'type': 'P', 'no': '3001', 'color_id': 5})] and body['skipped'] == []


def test_a_line_bricklink_cannot_name_is_skipped_and_listed(v2, coll, world):
    odd = coll.local('part', 'Odd part')
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,is_spare,quantity,missing) VALUES(?,?,?,0,2,2)', (world.copy_b, odd, world.red))
    body = call(v2, f'/export/missing.json?copy_id={world.copy_b}').json
    assert body['data'] == [] and [(l['item']['id'], l['quantity'], l['why']) for l in body['skipped']] == [(odd, 2, 'no BrickLink number')]
    assert ET.fromstring(call(v2, f'/export/missing.xml?copy_id={world.copy_b}').data).findall('ITEM') == []
    assert any('Odd part' in line for line in call(v2, f'/export/missing.csv?copy_id={world.copy_b}').data.decode().splitlines())


def test_the_picker_list_orders_the_pick_and_the_wishlist_list_is_one_or_all(v2, coll, world):
    picker = call(v2, f'/export/picker.csv?copy_id={world.copy_a}&rank=colour&rank=set')
    assert picker.data.decode().splitlines() == ['Rank,Item type,Item number,Name,Colour,Colour id,Quantity,Sets,Storage', '1,P,3001,Brick 2 x 4,Red,4,1,1000-1,Shelf A']
    assert call(v2, f'/export/picker.csv?copy_id={world.copy_a}').status_code == 200
    everything = call(v2, '/export/wishlist.csv').data.decode().splitlines()
    assert everything[0] == 'List,Item type,Item number,Name,Colour,Colour id,Quantity,Condition,Max price,Currency,Note' and len(everything) == 3
    assert everything[1] == 'Wishlist,P,3023,Plate 1 x 2,White,7,2,New,0.50,EUR,'
    assert len(call(v2, '/export/wishlist.csv?list=default').data.decode().splitlines()) == 3 and call(v2, '/export/wishlist.csv?list=nothing').status_code == 404
    assert call(v2, '/export/picker.csv').status_code == 422
