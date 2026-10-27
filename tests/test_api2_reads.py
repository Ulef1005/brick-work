"""API v2 reads (M.11b, issue #113): every read operation against the contract, and what all reads share.

Ported from the all-GETs part of test_bw_api_m2 (contract coverage, unknown filters, bounded SQL, secrets), the paging tests of test_bw_api_m1 and
the performance test of test_bw_perf_api, onto the 4.0 fixtures. The per-resource behaviour is in test_api2_read_*.py."""
import json
from urllib.parse import urlencode

import pytest

from brickwork.api2 import operations
from brickwork.core import secrets as secret_store
from tests.api2 import CONTRACT, OPERATION_BY_ID, PREFIX, add_files, call, stored_token, v2, validate  # noqa: F401
from tests.api2 import app4, coll, pair, world  # noqa: F401

READS = sorted(op for op, o in OPERATION_BY_ID.items() if o['x-piece'] == 'M.11b')
FILES = {'get_images_by_id_content', 'get_instruction_files_by_id_content', 'get_export_missing_csv', 'get_export_missing_xml', 'get_export_picker_csv',
         'get_export_wishlist_csv', 'get_wishlists_by_id_export_xml', 'get_wishlists_by_id_export_csv'}


def paths(w):
    """One concrete request per read operation of the contract."""
    copy = w.copy_a
    return {
        'get_catalogue_items': '/catalogue/items?limit=3', 'get_catalogue_items_by_id': f'/catalogue/items/{w.keep}', 'get_catalogue_status': '/catalogue/status',
        'get_colors': '/colors', 'get_colors_by_color_id': '/colors/4', 'get_items': '/items', 'get_items_by_id_inventory': f'/items/{w.keep}/inventory',
        'get_items_by_id_used_in': f'/items/{w.brick}/used-in', 'get_items_by_id_colors': f'/items/{w.brick}/colors', 'get_items_by_id_images': f'/items/{w.keep}/images',
        'get_images_by_id_content': '/images/1/content', 'get_copies': '/copies', 'get_copies_by_id': f'/copies/{copy}',
        'get_copies_by_id_completeness': f'/copies/{copy}/completeness', 'get_copies_by_id_check': f'/copies/{copy}/check', 'get_copies_by_id_gaps': f'/copies/{copy}/gaps',
        'get_copies_by_id_matches': f'/copies/{copy}/matches', 'get_copies_by_id_parts': f'/copies/{copy}/parts', 'get_copies_by_id_figures': f'/copies/{copy}/figures',
        'get_stock': '/stock', 'get_stock_by_id': f'/stock/{w.stock_brick}', 'get_stock_by_id_parts': f'/stock/{w.stock_figure}/parts', 'get_minifigures': '/minifigures',
        'get_minifigures_by_id': f'/minifigures/{w.figure}', 'get_gaps': '/gaps', 'get_matches': '/matches', 'get_instruction_files': '/instruction-files',
        'get_instruction_files_by_id': '/instruction-files/1', 'get_instruction_files_by_id_content': '/instruction-files/1/content', 'get_prices': '/prices',
        'get_items_by_id_prices': f'/items/{w.brick}/prices', 'get_items_by_id_prices_history': f'/items/{w.brick}/prices/history', 'get_prices_stale': '/prices/stale',
        'get_wishes': '/wishes', 'get_wishes_by_id': f'/wishes/{w.wish_part}', 'get_wishlists': '/wishlists', 'get_wishlists_by_id_export_xml': '/wishlists/default/export.xml',
        'get_wishlists_by_id_export_csv': '/wishlists/default/export.csv', 'get_storages': '/storages', 'get_storages_by_id': f'/storages/{w.shelf}', 'get_lots': '/lots',
        'get_lots_by_id': f'/lots/{w.bag}', 'get_places': '/places', 'get_flags': '/flags', 'get_planning_ranking': '/planning/ranking',
        'get_export_missing_csv': f'/export/missing.csv?copy_id={copy}', 'get_export_missing_json': f'/export/missing.json?copy_id={copy}',
        'get_export_missing_xml': f'/export/missing.xml?ids={copy}', 'get_export_picker_csv': f'/export/picker.csv?copy_id={copy}', 'get_export_wishlist_csv': '/export/wishlist.csv',
        'get_events': '/events', 'get_events_by_id': '/events/1', 'get_statistics': '/statistics', 'get_items_by_id_detail': f'/items/{w.keep}/detail',
        'get_items_by_id_links': f'/items/{w.keep}/links', 'get_items_by_id_provider_status': f'/items/{w.keep}/provider-status', 'get_links': '/links'}


@pytest.fixture
def full(coll, world, pair):
    """The world plus what the file operations need: a picture and a PDF on disk and a file record."""
    add_files(coll, pair, world)
    coll.add_stock('minifigure', coll.local('minifigure', 'Synthetic local figure', born_key='syn-local-fig'), quantity=2, condition='new', source='none')
    coll.sql("INSERT INTO wishlist(id,name,sort,created_at) VALUES('second','Second list',1,'2026-10-26T12:00:00.000Z')")
    coll.lot('Second bag')
    coll.place('Second shop', kind='Market')
    coll.sql("INSERT INTO instruction_file(item_id,path,label,added_at) VALUES(?,'data/instructions/missing.pdf','Not on disk','2026-10-26T12:00:00.000Z')", (world.gate,))
    coll.mark(world.copy_b, '3023', '15', missing=1)
    return world


def test_every_read_operation_has_a_case(world):
    assert len(READS) == 57 and set(paths(world)) == set(READS)


@pytest.mark.parametrize('operation', READS)
def test_the_answer_is_what_the_contract_says(v2, full, operation):
    response = call(v2, paths(full)[operation])
    validate(response, operation)
    assert response.headers['Cache-Control'] == 'no-store'
    if operation in FILES:
        assert response.data


@pytest.mark.parametrize('operation', READS)
def test_a_wrong_token_is_401_and_an_unknown_filter_400(v2, full, operation):
    url = paths(full)[operation]
    assert call(v2, url, token='invalid').status_code == 401
    refused = call(v2, url + ('&' if '?' in url else '?') + 'synthetic_unknown=x')
    assert refused.status_code == 400 and refused.json['code'] == 'unknown_filter', refused.get_data(as_text=True)
    assert refused.mimetype == 'application/problem+json'


@pytest.mark.parametrize('operation', READS)
def test_a_read_scope_token_may_read_and_the_instance_may_be_read_only(v2, full, pair, operation, monkeypatch):
    reader = stored_token(pair, ['read'])
    assert call(v2, paths(full)[operation], token=reader).status_code == 200
    monkeypatch.setenv('BW_READ_ONLY', 'true')
    assert call(v2, paths(full)[operation]).status_code == 200


def test_the_scopes_are_the_contracts(world):
    assert {o['security'][0]['bearerAuth'][0] for op, o in OPERATION_BY_ID.items() if op in READS} == {'read'}
    assert {m['scope'] for m in operations().values() if m['piece'] == 'M.11b'} == {'read'}


# --- paging, as v1 (ported from test_bw_api_m1 and test_bw_api_m2)
LISTS = ['/colors', '/items', '/copies', '/stock', '/minifigures', '/gaps', '/matches', '/prices', '/wishes', '/wishlists', '/storages', '/lots', '/places', '/flags',
         '/events', '/links', '/prices/stale', '/instruction-files', '/catalogue/items', '/planning/ranking']


@pytest.mark.parametrize('path', LISTS)
def test_every_list_pages_without_losses_or_repeats(v2, full, path):
    everything = call(v2, path + '?limit=200').json['data']
    assert len(everything) > 1, path
    seen, cursor = [], None
    while True:
        options = dict(limit=1, **({'cursor': cursor} if cursor else {}))
        response = call(v2, path + '?' + urlencode(options))
        assert response.status_code == 200, response.get_data(as_text=True)
        seen.extend(response.json['data'])
        cursor = response.json['page']['next_cursor']
        if not cursor:
            break
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    assert canonical(seen) == canonical(everything), path
    assert len(set(canonical(seen))) == len(seen), path


@pytest.mark.parametrize('path', ['/colors', '/copies', '/flags', '/events', '/catalogue/items'])
def test_paging_errors_are_400(v2, full, path):
    for query in ('limit=0', 'limit=201', 'limit=bad', 'cursor=bad', 'direction=bad'):
        response = call(v2, path + '?' + query)
        assert response.status_code == 400, (path, query, response.get_data(as_text=True))
        assert response.json['code'] in ('bad_request', 'unknown_filter')
    assert call(v2, path + '?limit=200').status_code == 200 and call(v2, path + '?limit=1').status_code == 200


def test_a_cursor_is_for_the_query_that_made_it(v2, full):
    first = call(v2, '/copies?limit=1').json
    assert call(v2, '/stock?' + urlencode(dict(limit=1, cursor=first['page']['next_cursor']))).status_code == 400
    assert call(v2, '/copies?' + urlencode(dict(limit=1, sort='name', cursor=first['page']['next_cursor']))).status_code == 400
    assert call(v2, '/copies?' + urlencode(dict(limit=1, cursor=first['page']['next_cursor']))).status_code == 200


def test_the_page_total_is_the_filtered_count(v2, full):
    page = call(v2, '/copies?limit=1').json['page']
    assert page['total'] == 3 and page['limit'] == 1
    assert call(v2, '/copies?condition=new&limit=1').json['page']['total'] == 1
    assert call(v2, '/copies?q=nothing-like-this').json['page'] == {'next_cursor': None, 'limit': 50, 'total': 0}


def test_a_name_given_twice_is_refused_where_the_contract_does_not_repeat_it(v2, full):
    assert call(v2, '/copies?condition=new&condition=used').status_code == 400
    assert call(v2, f'/export/missing.csv?copy_id={full.copy_a}&copy_id={full.copy_b}').status_code == 200


# --- the cost of a page does not grow with the collection (ported from test_list_query_count)
class Counting:
    """Count the statements the request's connection runs."""

    def __init__(self, monkeypatch):
        from brickwork.api import transport
        self.queries = []
        real = transport.connect

        def traced(*args, **kwargs):
            db = real(*args, **kwargs)
            db.set_trace_callback(self.queries.append)
            return db
        monkeypatch.setattr(transport, 'connect', traced)


def grow(coll, count):
    """More of everything: sets, copies, stock, wishes, prices, storages, lots, places and flags."""
    brick, red = coll.item('parts', '3001'), coll.colour('4')
    for index in range(count):
        local = coll.local('part', f'Synthetic part {index}', born_key=f'syn-{index}')
        coll.add_stock('part', local, colour=red, quantity=2, condition='used')
        coll.add_wish(local, colour=red, quantity=1, condition='new', max_price='1.00', currency='EUR')
        coll.price(local, '0.10', colour=red, condition='used')
        coll.storage(f'Synthetic storage {index}')
        coll.place(f'Synthetic place {index}')
        coll.lot(f'Synthetic lot {index}')
        coll.flag(f'synthetic flag {index}')
        coll.add_copy('2070-1', condition='used')
        coll.mark(coll.add_copy('1000-2'), '3001', '4', missing=1)
    coll.add_stock('part', brick, colour=red, quantity=40, condition='damaged')


@pytest.mark.parametrize('path', [p for p in LISTS if p not in ('/catalogue/items',)] + ['/catalogue/items'])
def test_a_list_runs_the_same_number_of_queries_with_more_rows(v2, full, coll, monkeypatch, path):
    counting = Counting(monkeypatch)
    first = call(v2, path)
    assert first.status_code == 200, first.get_data(as_text=True)
    initial = len(counting.queries)
    grow(coll, 40)
    counting.queries.clear()
    second = call(v2, path)
    assert second.status_code == 200
    assert len(counting.queries) <= initial + 2, (path, initial, len(counting.queries))
    assert len(second.json['data']) >= len(first.json['data'])


def test_the_secret_list_is_read_once_per_answer(v2, full, coll, monkeypatch):
    grow(coll, 20)
    calls = []
    real = secret_store.secret_values
    monkeypatch.setattr('brickwork.api2.read.secret_values', lambda *a, **k: calls.append(1) or real(*a, **k))
    for path in ('/stock?limit=40', '/copies', '/wishes', f'/items/{full.keep}/detail'):
        calls.clear()
        assert call(v2, path).status_code == 200
        assert len(calls) == 1, path


def test_a_stored_credential_never_leaves_through_a_read(v2, full, coll, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-env-credential-value')
    coll.sql('UPDATE copy SET note=? WHERE id=?', ('see synthetic-env-credential-value please', full.copy_a))
    coll.sql('UPDATE stock SET note=? WHERE id=?', ('synthetic-env-credential-value', full.stock_brick))
    for operation, path in paths(full).items():
        response = call(v2, path)
        assert b'synthetic-env-credential-value' not in response.data, operation
    assert call(v2, f'/copies/{full.copy_a}').json['data']['note'] == 'see [set] please'
    assert call(v2, f'/stock/{full.stock_brick}').json['data']['note'] == '[set]'


# --- shared fixtures of the web and the API list the same way (ported from test_api_shared_browser_fixtures)
def test_the_api_lists_with_the_rules_of_the_shared_filter_fixtures():
    from pathlib import Path
    from brickwork.core.listing import filter_rows, paginate
    fixture = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/bw_filter_rows.json').read_text())
    for case in fixture['cases']:
        rows = filter_rows(fixture['rows'], **case)
        first = paginate(rows, limit=2, sort=case['sort'], direction=case['direction'])
        assert [r['id'] for r in first['data']] == [r['id'] for r in rows[:2]]


def test_a_cursor_survives_an_insert_before_it():
    from brickwork.core.listing import filter_rows, paginate
    rows = [{'id': str(i), 'number': str(i)} for i in (2, 4, 6)]
    first = paginate(filter_rows(rows), limit=2)
    rows += [{'id': '1', 'number': '1'}, {'id': '5', 'number': '5'}]
    second = paginate(filter_rows(rows), cursor=first['page']['next_cursor'], limit=2)
    assert [r['id'] for r in second['data']] == ['5', '6']


@pytest.mark.parametrize('sort,direction', [('number', 'asc'), ('number', 'desc'), ('name', 'asc'), ('used_price', 'desc'), ('missing', 'asc')])
def test_a_cursor_stays_stable_while_copies_arrive(v2, full, coll, sort, direction):
    for _ in range(9):
        coll.add_copy('1000-2', condition='used')
    options = dict(limit=4, sort=sort, direction=direction)
    first = call(v2, '/copies?' + urlencode(options)).json
    seen = [r['id'] for r in first['data']]
    coll.add_copy('2070-1', condition='used')
    cursor = first['page']['next_cursor']
    while cursor:
        response = call(v2, '/copies?' + urlencode(dict(options, cursor=cursor)))
        assert response.status_code == 200, response.get_data(as_text=True)
        seen.extend(r['id'] for r in response.json['data'])
        cursor = response.json['page']['next_cursor']
    assert len(seen) == len(set(seen))
    assert {full.copy_a, full.copy_b, full.copy_c} <= set(seen)


# --- the rules of the shared listing (ported from test_bw_api_m1): the browser and the API filter alike
def test_the_web_scripts_and_the_api_filter_with_the_same_fixtures():
    import shutil
    import subprocess
    from pathlib import Path
    from brickwork.core.listing import filter_rows
    if shutil.which('node') is None:
        pytest.skip('node is not installed')
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root / 'tests/fixtures/bw_filter_rows.json').read_text())
    script = ("const fs=require('fs'),vm=require('vm');global.window={BrickFormatting:{nowrapTail:()=>{}}};global.document={querySelector:()=>null,"
              "querySelectorAll:()=>[],addEventListener:()=>{}};vm.runInThisContext(fs.readFileSync('static/web/toni/bw-collection.js','utf8'));"
              "const f=JSON.parse(fs.readFileSync('tests/fixtures/bw_filter_rows.json'));console.log(JSON.stringify(f.cases.map(c=>window.BrickCollection."
              "filterRows(f.rows,c.query,c.filters,c.sort,c.direction).map(r=>r.id))));")
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True, cwd=root)
    python = [[r['id'] for r in filter_rows(fixture['rows'], **case)] for case in fixture['cases']]
    assert python == json.loads(result.stdout)


def test_the_filter_extensions_of_the_listing():
    from brickwork.core.errors import UnknownFilter
    from brickwork.core.listing import filter_rows
    rows = [dict(id='a', number='1', archived_at=None, price=['EUR', '2'], max_price='3', created_at='2026-01-01', flag_ids=['flag-a']),
            dict(id='b', number='2', archived_at='2026-01-01', price=['EUR', '4'], max_price='3', created_at='2026-02-01')]
    assert [r['id'] for r in filter_rows(rows, filters={'flag': 'flag-a', 'under_max': 'true'})] == ['a']
    assert [r['id'] for r in filter_rows(rows, filters={'archived': 'only', 'since': '2026-02-01'})] == ['b']
    with pytest.raises(UnknownFilter):
        filter_rows([], filters={'unknown': 'x'})
    with pytest.raises(UnknownFilter):
        filter_rows([], filters={'archived': 'invalid'})


def test_without_the_catalogue_file_the_reads_say_how_to_get_one(v2, pair, world):
    pair.with_name('catalogue.db').unlink()
    refused = call(v2, '/catalogue/items')
    assert refused.status_code == 424 and refused.json['code'] == 'catalogue_not_loaded' and refused.mimetype == 'application/problem+json'
    assert call(v2, '/colors').status_code == 424
    assert v2.get(PREFIX + '/health').status_code == 200                                   # liveness does not need it


# --- the statuses the contract lists besides 200
def test_a_merged_id_answers_what_the_contract_says_on_every_path_that_lists_307(v2, coll, world):
    from brickwork.store4 import merge
    loser = coll.local('part', 'Only on BrickLink', born_key='x999')
    figure = coll.local('minifigure', 'Dup figure', born_key='syn-dup')
    merge.merge(coll.db, loser, world.brick, via='cli')
    merge.merge(coll.db, figure, world.figure, via='cli')
    coll.db.commit()
    listed = sorted(op for op in READS if '307' in OPERATION_BY_ID[op]['responses'])
    assert listed == ['get_items_by_id_colors', 'get_items_by_id_detail', 'get_items_by_id_images', 'get_items_by_id_inventory', 'get_items_by_id_links',
                      'get_items_by_id_prices', 'get_items_by_id_prices_history', 'get_items_by_id_provider_status', 'get_items_by_id_used_in',
                      'get_minifigures_by_id']
    for operation in listed:
        template = next(p for p, methods in CONTRACT['paths'].items() for m in methods.values() if isinstance(m, dict) and m['operationId'] == operation)
        path = template.replace('{id}', str(figure if operation == 'get_minifigures_by_id' else loser))
        response = call(v2, path)
        validate(response, operation, '307')
        assert response.headers['Location'].startswith(PREFIX) and response.headers['Cache-Control'] == 'no-store', operation


def test_a_missing_record_answers_404_where_the_contract_says_so(v2, world):
    for operation, path in (('get_colors_by_color_id', '/colors/999'), ('get_catalogue_items_by_id', '/catalogue/items/99999'), ('get_copies_by_id', '/copies/absent'),
                            ('get_stock_by_id', '/stock/absent'), ('get_wishes_by_id', '/wishes/absent'), ('get_storages_by_id', '/storages/absent'),
                            ('get_lots_by_id', '/lots/absent'), ('get_events_by_id', '/events/999999'), ('get_instruction_files_by_id', '/instruction-files/999'),
                            ('get_items_by_id_detail', '/items/99999999/detail'), ('get_minifigures_by_id', f'/minifigures/{world.keep}')):
        assert '404' in OPERATION_BY_ID[operation]['responses'], operation
        validate(call(v2, path), operation, '404')
