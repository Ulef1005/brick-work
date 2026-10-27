"""API v2 reads of where things are and what happened (M.11b, issue #113): storages, lots, places, flags, instruction files, events and
statistics. Ported from the matching reads of test_bw_api_m2 and test_bw_api_m3 (the events page, the archived instruction files) and
test_bw_media_27 onto the 4.0 fixtures. Invented data."""
import time

from tests.api2 import add_files, call, v2  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401


def data(response):
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json['data']


def ids(response):
    return [r['id'] for r in data(response)]


# --- storages
def test_storages_are_counted_and_the_virtual_not_stored_is_last(v2, world):
    listed = data(call(v2, '/storages'))
    assert [s['name'] for s in listed] == ['Shelf A', 'Not stored'] and listed[1]['id'] == 'unstored'
    shelf = listed[0]
    assert shelf == {'id': world.shelf, 'name': 'Shelf A', 'type': 'Shelf', 'parent_id': None, 'parent_name': None, 'note': None, 'copies': 1, 'entries': 1,
                     'pieces': 3, 'lots': 1, 'figures': 0, 'part_lots': 1, 'archived_at': None}
    assert (listed[1]['copies'], listed[1]['figures'], listed[1]['type']) == (2, 1, None)
    assert [s['id'] for s in data(call(v2, '/storages?direction=desc'))] == ['unstored', world.shelf]


def test_a_storage_lists_its_contents_with_the_item_bodies(v2, world):
    detail = data(call(v2, f'/storages/{world.shelf}'))
    assert detail['location']['id'] == world.shelf and detail['location']['copies'] == 1
    rows = {r['id']: r for r in detail['rows']}
    assert set(rows) == {world.copy_a, world.stock_brick}
    assert (rows[world.copy_a]['entity'], rows[world.copy_a]['kind'], rows[world.copy_a]['item']['id'], rows[world.copy_a]['completeness']) == ('copy', 'set', world.keep, 'incomplete')
    assert (rows[world.stock_brick]['entity'], rows[world.stock_brick]['color']['id'], rows[world.stock_brick]['quantity'], rows[world.stock_brick]['lot_id']) == (
        'stock', world.red, 3, world.bag)
    unstored = data(call(v2, '/storages/unstored'))
    assert unstored['location']['name'] == 'Not stored' and {r['id'] for r in unstored['rows']} >= {world.copy_b, world.copy_c, world.stock_figure}


def test_a_sub_storage_names_its_parent(v2, coll, world):
    box = coll.storage('Box 1', type='Box', parent_id=world.shelf)
    inner = next(s for s in data(call(v2, '/storages')) if s['id'] == box)
    assert (inner['parent_id'], inner['parent_name'], inner['type']) == (world.shelf, 'Shelf A', 'Box')


def test_an_archived_storage_reads_by_id_and_not_in_the_list(v2, coll, world):
    old = coll.storage('Old shelf')
    coll.sql('UPDATE storage SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', old))
    assert old not in ids(call(v2, '/storages'))
    detail = data(call(v2, f'/storages/{old}'))
    assert detail['location']['archived_at'] and detail['location']['name'] == 'Old shelf' and detail['rows'] == []
    for path in ('/storages/absent', '/storages/' + 'x' * 70):
        assert call(v2, path).status_code == 404


# --- lots
def test_lots_name_their_storage_and_count_their_live_stock(v2, coll, world):
    lots = data(call(v2, '/lots'))
    assert lots == [{'id': world.bag, 'name': 'Bag', 'note': None, 'created_at': '2026-10-26T12:00:00.000Z', 'storage_id': world.shelf, 'purchase_location_id': None,
                     'purchase_date': None, 'purchase_price': None, 'purchase_currency': None, 'archived_at': None, 'entries': 1, 'quantity': 3}]
    coll.sql('UPDATE stock SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', world.stock_brick))
    assert data(call(v2, '/lots'))[0]['entries'] == 0 and data(call(v2, '/lots'))[0]['quantity'] == 0


def test_lots_filter_by_storage_and_archive(v2, coll, world):
    plain = coll.lot('Loose bag')
    assert ids(call(v2, f'/lots?storage={world.shelf}')) == [world.bag] and ids(call(v2, '/lots?storage=null')) == [plain]
    coll.sql('UPDATE lot SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', plain))
    assert ids(call(v2, '/lots')) == [world.bag] and ids(call(v2, '/lots?archived=only')) == [plain] and set(ids(call(v2, '/lots?archived=include'))) == {world.bag, plain}


def test_a_lot_reads_with_its_stock_and_keeps_its_shape_when_archived(v2, coll, world):
    before = data(call(v2, f'/lots/{world.bag}'))
    assert before['lot']['id'] == world.bag and [r['id'] for r in before['rows']] == [world.stock_brick]
    assert before['rows'][0]['item']['id'] == world.brick and before['rows'][0]['etag']
    coll.sql('UPDATE lot SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', world.bag))
    after = data(call(v2, f'/lots/{world.bag}'))
    assert after['rows'] == before['rows'] and after['lot']['archived_at'] and after['lot']['id'] == before['lot']['id']
    assert call(v2, '/lots/absent').status_code == 404 and call(v2, '/lots/' + 'x' * 70).status_code == 404


# --- places and flags
def test_places_count_their_copies_orders_and_money_per_currency(v2, coll, world):
    place = data(call(v2, '/places'))[0]
    assert place == {'archived_at': None, 'id': world.shop, 'name': 'Shop', 'kind': 'Shop', 'count': 1, 'totals': {'EUR': '12.50'}, 'orders': 0, 'last_used': '2024-05-01'}
    coll.sql("UPDATE copy SET purchase_price='3.00', purchase_currency='USD', place_id=? WHERE id=?", (world.shop, world.copy_b))
    coll.sql("INSERT INTO purchase_order(store,date_ordered,created_at,updated_at) VALUES('shop','2026-10-01','x','x')")
    place = data(call(v2, '/places'))[0]
    assert place['totals'] == {'EUR': '12.50', 'USD': '3.00'} and place['count'] == 2 and place['orders'] == 1 and place['last_used'] == '2026-10-01'
    other = coll.place('Fair', kind='Fair')
    assert next(p for p in data(call(v2, '/places')) if p['id'] == other) == {'archived_at': None, 'id': other, 'name': 'Fair', 'kind': 'Fair', 'count': 0, 'totals': {}, 'orders': 0, 'last_used': None}


def test_an_archived_place_is_not_listed(v2, coll, world):
    coll.sql('UPDATE place SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', world.shop))
    assert data(call(v2, '/places')) == []


def test_flags_are_counted_over_copies_stock_and_wishes(v2, coll, world):
    flags = {f['id']: f for f in data(call(v2, '/flags'))}
    assert flags[world.tag] == {'archived_at': None, 'id': world.tag, 'name': 'collection', 'kind': 'tag', 'shown_on_grid': True, 'count': 1}
    assert flags[world.checked]['kind'] == 'status' and flags[world.checked]['count'] == 1 and flags[world.box]['count'] == 0
    coll.tag('stock', world.stock_brick, world.tag)
    coll.tag('wish', world.wish_part, world.tag)
    assert next(f for f in data(call(v2, '/flags')) if f['id'] == world.tag)['count'] == 3
    assert {f['kind'] for f in data(call(v2, '/flags?kind=status'))} == {'status'} and ids(call(v2, '/flags?kind=owner')) == []
    coll.sql('UPDATE flag SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', world.tag))
    assert world.tag not in ids(call(v2, '/flags'))


# --- instruction files
def test_instruction_files_are_listed_with_their_item_and_coverage(v2, coll, pair, world):
    add_files(coll, pair, world)
    listed = call(v2, '/instruction-files').json
    assert listed['coverage'] == {'total': 1, 'covered': 1}
    only = listed['data'][0]
    assert (only['id'], only['item']['id'], only['name'], only['label'], only['content_url'], only['archived_at']) == (
        1, world.keep, 'Syn Castle Keep', 'Synthetic booklet', '/api/v2/instruction-files/1/content', None)
    assert data(call(v2, '/instruction-files/1')) == only


def test_instruction_files_filter_by_kind_number_archive_and_presence(v2, coll, pair, world):
    add_files(coll, pair, world)
    coll.sql("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,'data/instructions/gone.pdf','Gone','2026-10-26T12:00:00.000Z')", (world.gate,))
    assert ids(call(v2, '/instruction-files?has_file=true')) == [1] and ids(call(v2, '/instruction-files?has_file=false')) == [2]
    gone = data(call(v2, '/instruction-files/2'))
    assert gone['content_url'] is None and gone['label'] == 'Gone'
    assert ids(call(v2, '/instruction-files?number=1000-2')) == [2] and ids(call(v2, '/instruction-files?kind=set&limit=1')) == [1] and ids(call(v2, '/instruction-files?kind=instructions')) == []
    coll.sql("UPDATE instruction_file SET archived_at='2026-10-27T00:00:00.000Z' WHERE id=1")
    assert ids(call(v2, '/instruction-files')) == [2]
    for archived in ('true', 'include'):
        assert ids(call(v2, '/instruction-files?archived=' + archived)) == [1, 2]
    assert ids(call(v2, '/instruction-files?archived=only')) == [1]
    assert data(call(v2, '/instruction-files/1'))['archived_at'] and data(call(v2, '/instruction-files/1'))['content_url'] is None
    assert call(v2, '/instruction-files?has_file=maybe').status_code == 400


def test_the_pdf_is_a_download_and_an_archived_one_is_gone(v2, coll, pair, world):
    add_files(coll, pair, world)
    pdf = call(v2, '/instruction-files/1/content')
    assert pdf.status_code == 200 and pdf.mimetype == 'application/pdf' and pdf.data.startswith(b'%PDF-')
    assert 'attachment' in pdf.headers['Content-Disposition'] and 'instructions.pdf' in pdf.headers['Content-Disposition']
    coll.sql("UPDATE instruction_file SET archived_at='2026-10-27T00:00:00.000Z' WHERE id=1")
    assert call(v2, '/instruction-files/1/content').status_code == 404
    for path in ('/instruction-files/99', '/instruction-files/x', '/instruction-files/99/content'):
        assert call(v2, path).status_code == 404, path


def test_the_pdf_follows_the_media_folder_and_stays_inside_it(v2, coll, pair, world, tmp_path, monkeypatch):
    add_files(coll, pair, world)
    nas = tmp_path / 'nas'
    (nas / 'data/instructions').mkdir(parents=True)
    (nas / 'data/instructions/synthetic.pdf').write_bytes(b'%PDF-1.4 nas')
    monkeypatch.setenv('BW_MEDIA_PATH', str(nas))
    assert call(v2, '/instruction-files/1/content').data.endswith(b'nas')
    (nas / 'data/instructions/synthetic.pdf').unlink()
    (tmp_path / 'outside.pdf').write_bytes(b'%PDF-1.4 outside')
    (nas / 'data/instructions/synthetic.pdf').symlink_to(tmp_path / 'outside.pdf')
    assert call(v2, '/instruction-files/1/content').status_code == 404 and data(call(v2, '/instruction-files/1'))['content_url'] is None


# --- the log
def test_events_are_newest_first_with_decoded_values(v2, coll, world):
    events = data(call(v2, '/events?limit=200'))
    assert [e['id'] for e in events] == sorted((e['id'] for e in events), reverse=True)
    created = next(e for e in events if e['entity'].startswith('copy:') and e['field'] == 'add')
    assert created['via'] == 'cli' and created['actor'] is None and isinstance(created['new_value'], dict) and created['old_value'] is None
    assert set(created) == {'actor', 'id', 'entity', 'field', 'old_value', 'new_value', 'at', 'via', 'undoable', 'undone'}
    assert data(call(v2, f'/events/{created["id"]}')) == created
    assert [e['id'] for e in data(call(v2, '/events?direction=asc&limit=2'))] == [events[-1]['id'], events[-2]['id']]


def test_events_filter_by_entity_prefix_field_origin_and_time(v2, coll, world):
    assert {e['entity'].split(':')[0] for e in data(call(v2, '/events?entity=copy&limit=200'))} == {'copy'}
    assert {e['field'] for e in data(call(v2, '/events?entity=copy&field=add&limit=200'))} == {'add'}
    assert data(call(v2, '/events?entity=nothing')) == []
    assert {e['via'] for e in data(call(v2, '/events?via=cli&limit=200'))} == {'cli'} and data(call(v2, '/events?via=api')) == []
    latest = data(call(v2, '/events?limit=1'))[0]
    assert [e['id'] for e in data(call(v2, '/events?since=' + latest['at']))][:1] == [latest['id']]
    assert data(call(v2, '/events?since=2999-01-01')) == []
    assert call(v2, '/events?via=carrier-pigeon').status_code == 400 and call(v2, '/events?undoable=maybe').status_code == 400


def test_an_event_is_undoable_until_something_undoes_it(v2, coll, world):
    coll.sql("INSERT INTO event(at,via,actor,entity_kind,entity_id,field,old_value,new_value) VALUES('2026-10-27T10:00:00.000Z','api','tester','planning','x','pin','0','1')")
    first = coll.db.execute('SELECT max(id) FROM event').fetchone()[0]
    event = data(call(v2, f'/events/{first}'))
    assert (event['undoable'], event['undone'], event['actor'], event['via'], event['entity'], event['old_value'], event['new_value']) == (True, False, 'tester', 'api', 'planning:x', 0, 1)
    assert first in ids(call(v2, '/events?undoable=true&limit=200')) and first not in ids(call(v2, '/events?undoable=false&limit=200'))
    coll.sql("INSERT INTO event(at,via,entity_kind,entity_id,field) VALUES('2026-10-27T10:01:00.000Z','api','planning','x','undo')")
    undo_event = coll.db.execute('SELECT max(id) FROM event').fetchone()[0]
    coll.sql('INSERT INTO event_undo(event_id,undo_event_id) VALUES(?,?)', (first, undo_event))
    event = data(call(v2, f'/events/{first}'))
    assert (event['undoable'], event['undone']) == (False, True)
    assert first not in ids(call(v2, '/events?undoable=true&limit=200')) and first in ids(call(v2, '/events?undoable=false&limit=200'))


def test_an_event_that_is_not_json_is_still_an_event(v2, coll, world):
    coll.sql("INSERT INTO event(at,via,entity_kind,entity_id,field,new_value) VALUES('2026-10-27T10:00:00.000Z','app','bw_add','x','receipt','not JSON')")
    identifier = coll.db.execute('SELECT max(id) FROM event').fetchone()[0]
    event = data(call(v2, f'/events/{identifier}'))
    assert event['new_value'] == 'not JSON' and event['undoable'] is False and event['undone'] is False
    for query in ('', '?undoable=true', '?undoable=false', '?limit=1'):
        assert call(v2, '/events' + query).status_code == 200


def test_credentials_and_replay_receipts_are_not_served_through_events(v2, coll, world):
    coll.sql("INSERT INTO event(at,via,entity_kind,entity_id,field,old_value,new_value) VALUES('2026-10-27T10:00:00.000Z','api','source_key','rebrickable','save','sealed-old','sealed-new')")
    coll.sql("INSERT INTO event(at,via,actor,entity_kind,entity_id,field,new_value) VALUES('2026-10-27T10:00:01.000Z','api','tester','bw_api',NULL,'op:key-1','{\"stored\":true}')")
    shown = data(call(v2, '/events?limit=2'))
    assert [(e['entity'], e['old_value'], e['new_value']) for e in shown] == [('bw_api', None, None), ('source_key:rebrickable', None, None)]


def test_an_unknown_event_is_404(v2):
    for path in ('/events/999999', '/events/0', '/events/x', '/events/-1'):
        assert call(v2, path).status_code == 404, path


def test_a_page_of_a_long_log_is_one_statement(v2, coll, monkeypatch):
    from tests.test_api2_reads import Counting
    coll.db.executemany("INSERT INTO event(at,via,entity_kind,entity_id,field,new_value) VALUES('2026-10-01T00:00:00.000Z','import','synthetic',NULL,'change','null')", [()] * 150000)
    coll.db.commit()
    counting = Counting(monkeypatch)
    started = time.perf_counter()
    first = call(v2, '/events?limit=1')
    elapsed = time.perf_counter() - started
    assert first.status_code == 200 and len(first.json['data']) == 1 and first.json['page']['next_cursor']
    assert len([q for q in counting.queries if 'FROM main.event' in q]) == 1 and elapsed < 1.5
    second = call(v2, '/events?limit=1&cursor=' + first.json['page']['next_cursor'])
    assert second.json['data'][0]['id'] < first.json['data'][0]['id']


# --- statistics
def test_statistics_count_the_live_copies(v2, coll, world):
    stats = data(call(v2, '/statistics'))
    assert set(stats) == {'completeness', 'theme', 'storage', 'purchase place'}
    assert {r['label']: r['count'] for r in stats['completeness']} == {'Sealed': 1, 'Complete': 1, 'Incomplete': 1}
    assert {r['label']: r['count'] for r in stats['theme']} == {'Castle': 2, 'Rattles': 1}
    assert {r['label']: r['count'] for r in stats['storage']} == {'Shelf A': 1, 'Not recorded': 2}
    assert {r['label']: r['count'] for r in stats['purchase place']} == {'Shop': 1, 'Not recorded': 2}
    coll.sql('UPDATE copy SET archived_at=? WHERE id=?', ('2026-10-27T00:00:00.000Z', world.copy_a))
    assert {r['label']: r['count'] for r in data(call(v2, '/statistics'))['completeness']} == {'Sealed': 1, 'Complete': 1}
