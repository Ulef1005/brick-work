"""API v2 reads of the catalogue, colours and items (M.11b, issue #113): `/catalogue/*`, `/colors*`, `/items` and what an item has (inventory,
used-in, colours, pictures, links, provider status, detail, the figure detail). Invented data on the 4.0 fixtures."""
from urllib.parse import urlencode

from brickwork.store4 import lookup, merge
from tests.api2 import PREFIX, add_files, call, v2  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def data(response):
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json['data']


def ids(response):
    return [r['id'] for r in data(response)]


# --- colours
def test_colours_are_the_colour_bodies_by_id(v2, coll):
    colours = data(call(v2, '/colors?limit=200'))
    assert [c['id'] for c in colours] == list(range(1, 12))
    assert colours[3] == {'id': 4, 'name': 'Red', 'rgb': 'C91A09', 'bricklink_id': 5, 'rebrickable_id': 4}
    assert colours[0] == {'id': 1, 'name': '[No Color/Any Color]', 'rgb': '05131D', 'bricklink_id': 0, 'rebrickable_id': 9999}
    assert [c['id'] for c in data(call(v2, '/colors?direction=desc&limit=2'))] == [11, 10]
    assert data(call(v2, '/colors/4')) == colours[3]


def test_a_colour_is_found_by_name_or_any_of_its_numbers(v2, coll):
    assert ids(call(v2, '/colors?q=red')) == [4]
    assert ids(call(v2, '/colors?q=C91A09')) == []                       # the rgb is not searched
    assert ids(call(v2, '/colors?q=15')) == [7]                          # Rebrickable 15 is white
    assert 5 in ids(call(v2, '/colors?q=5'))                             # BrickLink 5 is red (and Rebrickable 6 is brown)


def test_an_unknown_colour_is_404(v2, coll):
    for path in ('/colors/999', '/colors/0', '/colors/-1', '/colors/red', '/colors/04x'):
        response = call(v2, path)
        assert response.status_code == 404 and response.json['code'] == 'not_found', path


def test_a_colour_that_is_only_in_the_collection_is_listed(v2, coll):
    coll.sql("INSERT INTO color(id,origin,name,rgb,is_trans,born_provider,born_key,created_at,updated_at) VALUES(1000000000,'local','Local blue','0000FF',0,'bricklink','999','x','x')")
    body = data(call(v2, '/colors/1000000000'))
    assert body == {'id': 1000000000, 'name': 'Local blue', 'rgb': '0000FF', 'bricklink_id': 999, 'rebrickable_id': None}
    assert 1000000000 in ids(call(v2, '/colors?limit=200'))


# --- the catalogue
def test_catalogue_status_says_what_is_loaded_and_how_links_stand(v2, coll):
    status = data(call(v2, '/catalogue/status'))
    assert status['loaded'] is True and status['items'] == 18
    assert [b['id'] for b in status['builds']] == [1] and status['builds'][0]['activated'] is True
    assert status['builds'][0]['mapping_version'] == '2026.10.23.1' and status['builds'][0]['built_at'].startswith('2026-10-23')
    assert sum(status['coverage'].values()) == coll.db.execute('SELECT count(*) FROM main.item_link').fetchone()[0]
    assert status['last_reconcile'] is None or set(status['last_reconcile']) == {'at', 'summary'}


def test_catalogue_status_counts_links_by_status(v2, coll):
    brick = coll.item('parts', '3001')
    coll.link(brick, 'maybe-3001', status='to_check')
    coll.link(brick, 'by-hand', status='manual')
    coverage = data(call(v2, '/catalogue/status'))['coverage']
    assert coverage['to_check'] == 1 and coverage['manual'] == 1


def test_catalogue_items_are_paged_in_sql_by_number_or_name(v2, coll):
    everything = data(call(v2, '/catalogue/items?limit=200'))
    assert len(everything) == 18 and call(v2, '/catalogue/items?limit=200').json['page']['total'] == 18
    numbers = [(e['item']['rebrickable'] or {})['key'] for e in everything]
    assert numbers == sorted(numbers)                                       # the catalogue's number order is the byte order of the key
    names = [e['name'] for e in data(call(v2, '/catalogue/items?sort=name&limit=200'))]
    assert names == sorted(names, key=str.lower) or names == sorted(names)
    seen, cursor = [], None
    while True:
        response = call(v2, '/catalogue/items?' + urlencode(dict(limit=5, sort='name', direction='desc', **({'cursor': cursor} if cursor else {}))))
        seen += [e['item']['id'] for e in data(response)]
        cursor = response.json['page']['next_cursor']
        if not cursor:
            break
    assert seen == [e['item']['id'] for e in data(call(v2, '/catalogue/items?sort=name&direction=desc&limit=200'))] and len(set(seen)) == 18


def test_catalogue_items_by_kind_and_text(v2, coll, world):
    sets = data(call(v2, '/catalogue/items?kind=set&limit=200'))
    assert {e['item']['kind'] for e in sets} == {'set'} and call(v2, '/catalogue/items?kind=set').json['page']['total'] == 3
    assert [e['item']['id'] for e in data(call(v2, '/catalogue/items?q=3001'))][:1] == [world.brick]            # the number finds it first
    assert [e['item']['id'] for e in data(call(v2, '/catalogue/items?q=970c00'))] == [coll.item('parts', '970c03'), coll.item('parts', '970c22')]    # BrickLink's number too
    castle = data(call(v2, '/catalogue/items?q=castle&kind=set'))
    assert {e['name'] for e in castle} == {'Syn Castle Keep', 'Syn Castle Gate'}
    assert data(call(v2, '/catalogue/items?q=zzzz-nothing')) == []
    assert call(v2, '/catalogue/items?kind=widget').status_code == 422
    assert call(v2, '/catalogue/items?sort=year').status_code == 400


def test_a_catalogue_entry_says_how_much_is_owned_and_wished(v2, world):
    keep = data(call(v2, f'/catalogue/items/{world.keep}'))
    assert (keep['name'], keep['year'], keep['owned'], keep['wished'], keep['item']['id']) == ('Syn Castle Keep', 1990, 2, False, world.keep)
    gate = data(call(v2, f'/catalogue/items/{world.gate}'))
    assert (gate['owned'], gate['wished']) == (0, True)
    brick = data(call(v2, f'/catalogue/items/{world.brick}'))
    assert brick['owned'] == 5 and brick['category'] == 'Bricks'                       # 3 used and 2 new loose
    assert data(call(v2, '/catalogue/items?q=3001'))[0] == brick


def test_the_owned_count_of_an_item_leaves_out_archived_copies_and_stock_and_wishes(v2, coll, world):
    coll.add_copy('1000-1')
    archived = coll.add_copy('1000-1')
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', archived))
    coll.add_stock('instructions', coll.local('instructions', 'Loose booklet', born_key='1000-1x'), quantity=7, condition='used')
    assert data(call(v2, f'/items/{world.keep}/detail'))['counts'] == {'owned': 3, 'wished': False}
    coll.add_wish(world.keep, quantity=3)
    assert data(call(v2, f'/items/{world.keep}/detail'))['counts'] == {'owned': 3, 'wished': True}
    coll.sql('UPDATE wish SET archived_at=? WHERE item_id=?', ('2026-10-27T00:00:00.000Z', world.keep))
    assert data(call(v2, f'/items/{world.keep}/detail'))['counts'] == {'owned': 3, 'wished': False}
    assert data(call(v2, f'/catalogue/items/{world.keep}'))['owned'] == 3


def test_a_retired_or_unknown_catalogue_entry_is_404(v2, coll, world):
    for path in ('/catalogue/items/99999', '/catalogue/items/0', '/catalogue/items/x', f'/catalogue/items/{1000000000}'):
        assert call(v2, path).status_code == 404, path
    assert call(v2, f'/catalogue/items/{world.gate}').status_code == 200
    # a local item is the collection's, not the catalogue file's
    local = coll.local('part', 'Only on BrickLink', born_key='x999')
    assert call(v2, f'/catalogue/items/{local}').status_code == 404
    assert local not in [e['item']['id'] for e in data(call(v2, '/catalogue/items?limit=200'))]


# --- the items the collection knows
def test_items_are_the_projected_items_with_the_item_body(v2, world):
    listed = data(call(v2, '/items?limit=200'))
    assert all(set(i) == {'id', 'kind', 'name', 'unidentified', 'bricklink', 'rebrickable'} for i in listed)
    assert world.keep in [i['id'] for i in listed] and world.mystery in [i['id'] for i in listed]
    assert 5 not in [i['id'] for i in listed]                                        # an unused catalogue item is not projected
    assert {i['id']: i for i in listed}[world.mystery]['unidentified'] is True
    assert call(v2, '/items?limit=200').json['page']['total'] == len(listed)


def test_items_filter_by_kind_theme_year_category_and_owned(v2, world):
    assert {i['kind'] for i in data(call(v2, '/items?kind=part&limit=200'))} == {'part'}
    assert sorted(ids(call(v2, '/items?theme=Castle'))) == sorted([world.keep, world.gate])
    assert ids(call(v2, '/items?year=1990')) == [world.keep]
    assert world.brick in ids(call(v2, '/items?category=Bricks'))
    owned = ids(call(v2, '/items?owned=true&limit=200'))
    assert world.keep in owned and world.gate not in owned and world.mystery in owned
    assert world.gate in ids(call(v2, '/items?owned=false&limit=200'))
    assert call(v2, '/items?owned=maybe').status_code == 400


def test_items_search_by_name_and_either_number(v2, coll, world):
    assert ids(call(v2, '/items?q=castle%20keep')) == [world.keep, world.local_booklet]              # the booklet is named after its set
    assert ids(call(v2, '/items?q=1000-1&kind=set')) == [world.keep]
    legs = coll.item('parts', '970c03')
    coll.link(legs, 'x-legs', kind='P')
    coll.project(legs)
    assert ids(call(v2, '/items?q=970c00')) == [legs]                                                 # the BrickLink number finds the part
    assert ids(call(v2, '/items?q=970c03')) == [legs]                                                 # and so does Rebrickable's
    assert world.figure in ids(call(v2, '/items?q=syn-fig-0004'))
    assert [i['name'] for i in data(call(v2, '/items?sort=name&limit=200'))] == sorted([i['name'] for i in data(call(v2, '/items?limit=200'))], key=str.casefold)


def test_a_merged_item_is_not_listed(v2, coll, world):
    loser = coll.local('part', 'Only on BrickLink', born_key='x999')
    assert loser in ids(call(v2, '/items?limit=200'))
    merge.merge(coll.db, loser, world.brick, via='cli')
    coll.db.commit()
    assert loser not in ids(call(v2, '/items?limit=200'))


# --- the part list of an item
def test_a_set_lists_its_parts_and_figures_with_spares_beside_the_required_line(v2, world):
    lines = data(call(v2, f'/items/{world.keep}/inventory'))
    seen = [(l['child']['id'], (l['color'] or {}).get('id'), l['quantity'], l['extra_quantity'], l['source']) for l in lines]
    assert seen == [(world.brick, world.red, 4, 0, 'rebrickable'), (world.plate, world.red, 0, 1, 'rebrickable'),
                    (world.plate, world.white, 2, 0, 'rebrickable'), (world.figure, None, 2, 0, 'rebrickable')]
    assert lines[0]['name'] == 'Brick 2 x 4' and lines[0]['child']['rebrickable'] == {'key': '3001'}
    assert call(v2, f'/items/{world.keep}/inventory').json['page']['total'] == 4


def test_a_figure_lists_its_parts_and_a_part_none(v2, world):
    parts = data(call(v2, f'/items/{world.figure}/inventory'))
    assert {l['child']['kind'] for l in parts} == {'part'} and len(parts) == 4
    assert data(call(v2, f'/items/{world.brick}/inventory')) == []
    assert data(call(v2, f'/items/{world.mystery}/inventory')) == []


def test_a_fetched_list_is_the_reference_when_the_catalogue_has_none(v2, coll):
    local = coll.local('set', 'Local set', born_key='L-1')
    coll.project(coll.item('parts', '3001'))
    coll.sql("INSERT INTO fetched_inventory(item_id,source,seq,is_latest,fetched_at,digest,part_lines,figure_lines) VALUES(?,'bricklink',1,1,'2026-10-26T12:00:00.000Z','d',1,0)", (local,))
    coll.sql("INSERT INTO fetched_inventory_part(fetched_inventory_id,item_id,color_id,is_spare,quantity) VALUES(1,?,?,0,3)", (coll.item('parts', '3001'), coll.colour('4')))
    lines = data(call(v2, f'/items/{local}/inventory'))
    assert [(l['child']['rebrickable']['key'], l['quantity'], l['source']) for l in lines] == [('3001', 3, 'bricklink')]


# --- where it is used
def test_a_part_is_used_in_the_live_copies_that_hold_it(v2, coll, world):
    used = data(call(v2, f'/items/{world.brick}/used-in'))
    by_copy = {u['copy_id']: u for u in used}
    assert set(by_copy) == {world.copy_a, world.copy_b}
    assert (by_copy[world.copy_a]['quantity'], by_copy[world.copy_a]['missing'], by_copy[world.copy_a]['color']['id']) == (4, 1, world.red)
    assert by_copy[world.copy_a]['item']['id'] == world.keep and by_copy[world.copy_a]['name'] == 'Syn Castle Keep'
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', world.copy_b))
    assert [u['copy_id'] for u in data(call(v2, f'/items/{world.brick}/used-in'))] == [world.copy_a]


def test_a_part_in_several_colours_has_no_single_colour(v2, coll, world):
    copy = world.copy_a
    coll.sql('UPDATE copy_part SET color_id=? WHERE copy_id=? AND item_id=? AND is_spare=0', (world.white, copy, world.brick))
    coll.sql('INSERT INTO copy_part(copy_id,item_id,color_id,is_spare,quantity,missing) VALUES(?,?,?,0,3,1)', (copy, world.brick, world.red))
    row = {u['copy_id']: u for u in data(call(v2, f'/items/{world.brick}/used-in'))}[copy]
    assert (row['quantity'], row['missing'], row['color']) == (7, 2, None)


def test_a_figure_is_used_in_the_copies_with_its_figure_line(v2, world):
    used = data(call(v2, f'/items/{world.figure}/used-in'))
    assert {u['copy_id'] for u in used} == {world.copy_a, world.copy_b} and all(u['quantity'] == 2 and u['color'] is None for u in used)
    assert data(call(v2, f'/items/{world.keep}/used-in')) == []


# --- colours of a part
def test_a_part_knows_the_colours_it_is_held_listed_priced_and_wished_in(v2, coll, world):
    assert {c['id'] for c in data(call(v2, f'/items/{world.brick}/colors'))} >= {world.red}
    coll.price(world.brick, '0.50', colour=coll.colour('6'))
    coll.add_wish(world.brick, colour=coll.colour('14'), quantity=1)
    colours = {c['id'] for c in data(call(v2, f'/items/{world.brick}/colors'))}
    assert {world.red, coll.colour('6'), coll.colour('14')} <= colours
    assert all(set(c) == {'id', 'name', 'rgb', 'bricklink_id', 'rebrickable_id'} for c in data(call(v2, f'/items/{world.brick}/colors')))
    assert data(call(v2, f'/items/{world.keep}/colors')) == []                                   # only a part has colours


# --- pictures
def test_pictures_and_own_photos_of_an_item_with_their_bytes(v2, coll, pair, world):
    add_files(coll, pair, world)
    coll.sql("INSERT INTO photo(id,item_id,color_id,copy_id,local_path,width,height,caption,created_at) VALUES(?,?,NULL,?,?,2,2,'Front','2026-10-26T12:00:00.000Z')",
             ('a' * 32, world.keep, world.copy_a, 'data/images/own/front.png'))
    (pair.parent / 'data/images/own').mkdir(parents=True)
    (pair.parent / 'data/images/own/front.png').write_bytes(b'\x89PNG\r\n\x1a\nown')
    images = {str(i['id']): i for i in data(call(v2, f'/items/{world.keep}/images'))}
    assert set(images) == {'1', 'a' * 32}
    assert images['1']['kind'] == 'photo' and images['1']['source'] == 'bricklink' and images['1']['content_url'] == f'{PREFIX}/images/1/content'
    own = images['a' * 32]
    assert (own['kind'], own['source'], own['copy_id'], own['caption'], own['stock_id']) == ('own', 'own', world.copy_a, 'Front', None)
    assert call(v2, '/images/1/content').data == b'\x89PNG\r\n\x1a\n'
    assert call(v2, '/images/1/content').mimetype == 'image/png'
    assert call(v2, '/images/' + 'a' * 32 + '/content').data.endswith(b'own')


def test_an_image_that_is_not_there_is_404(v2, coll, pair, world):
    add_files(coll, pair, world)
    for path in ('/images/999/content', '/images/x/content', '/images/' + 'b' * 32 + '/content', '/images/' + 'A' * 32 + '/content', '/images/' + '9' * 40 + '/content'):
        assert call(v2, path).status_code == 404, path
    (pair.parent / 'data/images/synthetic.png').unlink()
    assert call(v2, '/images/1/content').status_code == 404                               # a row whose file is gone


def test_a_link_out_of_the_media_folder_is_refused(v2, coll, pair, world, tmp_path):
    secret = tmp_path / 'outside.png'
    secret.write_bytes(b'\x89PNG\r\n\x1a\nsecret')
    (pair.parent / 'data/images').mkdir(parents=True)
    (pair.parent / 'data/images/escape.png').symlink_to(secret)
    coll.sql("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/escape.png','2026-10-26T12:00:00.000Z')", (world.keep,))
    assert call(v2, '/images/1/content').status_code == 404


def test_the_media_folder_is_where_the_environment_says(v2, coll, pair, world, tmp_path, monkeypatch):
    add_files(coll, pair, world)
    elsewhere = tmp_path / 'nas'
    (elsewhere / 'data/images').mkdir(parents=True)
    (elsewhere / 'data/images/synthetic.png').write_bytes(b'\x89PNG\r\n\x1a\nnas')
    monkeypatch.setenv('BW_MEDIA_PATH', str(elsewhere))
    assert call(v2, '/images/1/content').data.endswith(b'nas')


def test_the_default_media_folder_is_beside_the_database(coll, pair, monkeypatch):
    from brickwork.core import media
    monkeypatch.delenv('BW_MEDIA_PATH', raising=False)
    assert media.root_for(pair) == pair.resolve().parent and media.media_root(coll.db) == pair.resolve().parent


# --- links and provider status
def test_an_item_lists_its_links_with_status_method_origin_and_scope(v2, coll, world):
    links = data(call(v2, f'/items/{coll.item("parts", "970c03")}/links'))
    assert {(l['no'], l['color_id'], l['color_scoped'], l['preferred'], l['status']) for l in links} == {
        ('970c00', 11, True, True, 'matched'), ('970c11', None, False, True, 'matched')}
    assert all({'provider', 'type', 'no', 'color_id', 'color_scoped', 'brickwork_color_id', 'status', 'method', 'origin', 'preferred', 'decided_at'} == set(l) for l in links)
    scoped = next(l for l in links if l['color_scoped'])
    assert scoped['brickwork_color_id'] == coll.colour('0') and scoped['origin'] == 'rule' and scoped['type'] == 'P'


def test_a_link_scoped_to_a_colour_without_a_bricklink_number_is_not_every_colour(v2, coll, world):
    coll.sql("INSERT INTO color(id,origin,name,rgb,is_trans,born_provider,born_key,created_at,updated_at) VALUES(1000000001,'local','Odd','000000',0,'rebrickable','77777','x','x')")
    coll.link(world.brick, 'odd-3001', kind='P', colour=1000000001)
    link = next(l for l in data(call(v2, f'/items/{world.brick}/links')) if l['no'] == 'odd-3001')
    assert (link['color_id'], link['color_scoped'], link['brickwork_color_id']) == (None, True, 1000000001)


def test_links_include_the_candidates_that_wait_for_a_decision(v2, coll, world):
    coll.link(world.brick, 'maybe-3001', status='to_check')
    statuses = {l['no']: l['status'] for l in data(call(v2, f'/items/{world.brick}/links'))}
    assert statuses == {'3001': 'matched', 'maybe-3001': 'to_check'}


def test_provider_status_says_why_there_is_no_key(v2, coll, world):
    assert data(call(v2, f'/items/{world.brick}/provider-status')) == []
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'brickset','to_check','kind_differs','{\"seen\":1}','2026-10-26T12:00:00.000Z')", (world.brick,))
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,evidence_json,checked_at) VALUES(?,'bricklink','unmatched','no_match',NULL,'2026-10-26T12:00:00.000Z')", (world.brick,))
    found = data(call(v2, f'/items/{world.brick}/provider-status'))
    assert [(s['provider'], s['status'], s['reason'], s['evidence']) for s in found] == [('bricklink', 'unmatched', 'no_match', None), ('brickset', 'to_check', 'kind_differs', {'seen': 1})]


def test_links_across_items_by_status_replace_the_unresolved_list(v2, coll, world):
    coll.link(world.brick, 'maybe-3001', status='to_check')
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,checked_at) VALUES(?,'brickset','to_check','no_candidate','2026-10-26T12:00:00.000Z')", (world.plate,))
    coll.sql("INSERT INTO item_provider_status(item_id,provider,status,reason,checked_at) VALUES(?,'brickset','unmatched','no_match','2026-10-26T12:00:00.000Z')", (world.keep,))
    waiting = data(call(v2, '/links?status=to_check'))
    assert sorted(((r['item']['id'], bool(r['link']), bool(r['provider_status'])) for r in waiting)) == sorted([(world.brick, True, False), (world.plate, False, True)])
    assert all((r['link'] is None) != (r['provider_status'] is None) for r in data(call(v2, '/links?limit=200')))
    assert {r['link']['status'] for r in data(call(v2, '/links?status=matched&limit=200'))} == {'matched'}
    assert data(call(v2, '/links?status=manual')) == []
    assert {r['provider_status']['status'] for r in data(call(v2, '/links?provider=brickset&limit=200'))} == {'to_check', 'unmatched'}
    assert {r['item']['kind'] for r in data(call(v2, '/links?kind=minifigure&limit=200'))} == {'minifigure'}
    assert call(v2, '/links?status=nonsense').status_code == 400
    assert call(v2, '/links?kind=widget').status_code == 422


# --- the detail
def test_the_detail_of_a_set_gathers_what_the_collection_has_of_it(v2, world):
    detail = data(call(v2, f'/items/{world.keep}/detail'))
    assert detail['item']['id'] == world.keep and detail['counts'] == {'owned': 2, 'wished': False}
    assert sorted(c['id'] for c in detail['copies']) == sorted([world.copy_a, world.copy_b]) and detail['stock'] == [] and detail['wishes'] == []
    assert detail['prices'][0]['observation']['price'] == '30.00' and detail['prices'][0]['observation']['item']['id'] == world.keep
    assert [l['child']['id'] for l in detail['inventory']][:1] == [world.brick]
    assert [l['no'] for l in detail['links']] == ['1000-1'] and detail['properties'] == {}
    assert {u['copy_id'] for u in detail['used_in']} == set()
    assert {g['copy_id'] for g in detail['gaps']} >= {world.copy_a}
    assert detail['matches'] and {m['copy_id'] for m in detail['matches']} <= {world.copy_a, world.copy_b}
    assert all(set(m) == {'source_id', 'copy_id', 'target', 'target_id', 'item', 'color', 'have', 'suggested', 'completes'} for m in detail['matches'])


def test_the_detail_of_a_part_has_its_stock_wishes_and_where_it_is_used(v2, world):
    detail = data(call(v2, f'/items/{world.plate}/detail'))
    assert detail['counts'] == {'owned': 2, 'wished': True} and detail['copies'] == [] and len(detail['stock']) == 1
    assert [w['id'] for w in detail['wishes']] == [world.wish_part] and detail['inventory'] == []
    brick = data(call(v2, f'/items/{world.brick}/detail'))
    assert brick['counts']['owned'] == 5 and len(brick['stock']) == 2 and {u['copy_id'] for u in brick['used_in']} == {world.copy_a, world.copy_b}
    assert any(g['copy_id'] == world.copy_a and g['item']['id'] == world.brick for g in brick['gaps'])
    assert {m['source_id'] for m in brick['matches']} >= {world.stock_brick}


def test_the_detail_carries_fetched_properties_with_their_alternatives(v2, coll, world):
    coll.prop(world.keep, 'theme', 'Castle', source='brickset')
    coll.prop(world.keep, 'theme', 'Knights', source='bricklink')
    theme = data(call(v2, f'/items/{world.keep}/detail'))['properties']['theme']
    assert theme['source'] == 'bricklink' and theme['value'] == 'Knights' and theme['alternatives'][0]['value'] == 'Castle'
    assert set(theme) == {'value', 'unit', 'source', 'fetched_at', 'alternatives'}


def test_the_detail_of_an_item_the_collection_never_projected_is_the_catalogues(v2, coll):
    unused = coll.item('parts', '003402')
    detail = data(call(v2, f'/items/{unused}/detail'))
    assert detail['item']['id'] == unused and detail['counts'] == {'owned': 0, 'wished': False} and detail['copies'] == detail['stock'] == detail['gaps'] == []
    assert coll.db.execute('SELECT 1 FROM main.item WHERE id=?', (unused,)).fetchone() is None            # reading projected nothing


def test_an_unknown_item_is_404_on_every_item_path(v2):
    for tail in ('/detail', '/inventory', '/used-in', '/colors', '/images', '/links', '/provider-status', '/prices', '/prices/history'):
        for item in ('99999999', '0', 'x', '007'):
            assert call(v2, '/items/' + item + tail).status_code == 404, (item, tail)


def test_a_merged_id_redirects_on_every_item_path(v2, coll, world):
    loser = coll.local('part', 'Only on BrickLink', born_key='x999')
    merge.merge(coll.db, loser, world.brick, via='cli')
    coll.db.commit()
    for tail in ('/detail', '/inventory', '/used-in', '/colors', '/images', '/links', '/provider-status', '/prices', '/prices/history'):
        query = '' if tail in ('/detail', '/links', '/provider-status', '/prices') else '?limit=2'
        response = call(v2, f'/items/{loser}{tail}{query}')
        assert response.status_code == 307, tail
        assert response.headers['Location'] == f'{PREFIX}/items/{world.brick}{tail}{query}' and response.headers['Cache-Control'] == 'no-store'
        assert response.json['code'] == 'moved' and response.json['survivor'] == world.brick


def test_the_figure_detail_is_the_item_detail_of_a_figure(v2, world):
    detail = data(call(v2, f'/minifigures/{world.figure}'))
    assert detail == data(call(v2, f'/items/{world.figure}/detail'))
    assert detail['counts'] == {'owned': 1, 'wished': False} and len(detail['stock']) == 1 and {u['copy_id'] for u in detail['used_in']} == {world.copy_a, world.copy_b}
    assert detail['prices'][0]['observation']['price'] == '2.00' and len(detail['inventory']) == 4
    for path in (f'/minifigures/{world.keep}', '/minifigures/99999999', '/minifigures/x'):
        assert call(v2, path).status_code == 404, path


def test_a_merged_figure_id_redirects_to_the_figure_path(v2, coll, world):
    loser = coll.local('minifigure', 'Dup figure', born_key='syn-dup')
    merge.merge(coll.db, loser, world.figure, via='cli')
    coll.db.commit()
    response = call(v2, f'/minifigures/{loser}')
    assert response.status_code == 307 and response.headers['Location'] == f'{PREFIX}/minifigures/{world.figure}'
    assert call(v2, f'/minifigures/{world.figure}').status_code == 200


def test_owned_true_leaves_out_an_item_whose_stock_sums_to_zero(v2, coll, world):
    empty = coll.local('part', 'Used up', born_key='used-up')
    coll.add_stock('part', empty, colour=world.red, quantity=0, condition='used')
    assert empty in ids(call(v2, '/items?owned=false&limit=200')) and empty not in ids(call(v2, '/items?owned=true&limit=200'))


def test_an_all_digit_photo_id_is_still_a_photo(v2, coll, pair, world):
    photo = '1' * 32
    (pair.parent / 'data/images/own').mkdir(parents=True)
    (pair.parent / 'data/images/own/digits.png').write_bytes(b'\x89PNG\r\n\x1a\ndigits')
    coll.sql("INSERT INTO photo(id,item_id,local_path,created_at) VALUES(?,?,'data/images/own/digits.png','2026-10-26T12:00:00.000Z')", (photo, world.keep))
    assert call(v2, f'/images/{photo}/content').data.endswith(b'digits')
