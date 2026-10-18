"""All M2 GETs: generated contract coverage, offline projections and bounded SQL."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
from xml.etree import ElementTree as ET

import pytest

from tests.test_bw_api_m1 import app, call
from tests.test_bw_api_m1_contract import CONTRACT, resolve, validate
from brickwork.core.connect import connect
from brickwork.core import api_reads, admin

OPS = [(p, o['get']) for p, o in CONTRACT['paths'].items()
       if o.get('get', {}).get('x-milestone') == 'M2']


@pytest.fixture
def populated(app, monkeypatch):
    def no_network(*a, **kw):
        raise AssertionError('Read endpoint attempted network access')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    path = Path(os.environ['BW_DB_PATH'])
    with closing(connect(path)) as db, db:
        db.execute("INSERT INTO colors VALUES(4,'Synthetic red','Solid','FF0000')")
        db.executemany('INSERT INTO items(item_type,item_no,name,year) VALUES(?,?,?,?)', [
            ('S','100-1','Synthetic set',2024),('P','3001','Synthetic brick',2025),('M','fig1','Synthetic figure',2023)])
        db.execute("INSERT INTO storages(id,name) VALUES('s1','Synthetic storage')")
        db.execute("INSERT INTO purchase_locations(id,name) VALUES('p1','Synthetic place')")
        db.execute("INSERT INTO lots(id,name) VALUES('l1','Synthetic lot')")
        db.execute("INSERT INTO copies(id,set_no,condition,completeness,completeness_source,storage_id,purchase_location_id) VALUES('c1','100-1','U','I','derived','s1','p1')")
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES('c1','P','3001',4,4,2,1,0)")
        db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('c1','M','fig1',1,1)")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition,storage_id,lot_id) VALUES('t1','P','3001',4,9,'U','s1','l1')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition) VALUES('m1','M','fig1',1,'N')")
        db.execute("INSERT INTO loose_minifig_parts(stock_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES('m1','P','3001',4,1,1,0,0)")
        db.execute("INSERT INTO wishlist(id,item_type,item_no,color_id,quantity,condition,max_price,max_price_currency) VALUES(1,'P','3001',4,2,'used','9.00','EUR')")
        db.execute("INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,color_id,quantity,source) VALUES('S','100-1','P','3001',4,4,'bricklink')")
        db.execute("INSERT INTO instruction_files(item_type,set_no,path,label) VALUES('S','100-1','data/instructions/synthetic.pdf','Synthetic booklet')")
        db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path) VALUES('S','100-1','bricklink','photo','data/images/synthetic.png')")
        db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES('f1','Synthetic tag','tag',1)")
        db.execute("INSERT INTO item_flags VALUES('copy','c1','f1')")
        db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,source,observed_at) VALUES('P','3001',4,'U','sold','EUR','2.50','bricklink','2026-10-01T00:00:00+00:00')")
        db.execute("INSERT INTO price_current(item_type,item_no,color_id,condition,guide,currency,observation_id) VALUES('P','3001',4,'U','sold','EUR',1)")
        db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','part','synthetic','P','3001','to_check','[]')")
        db.execute("INSERT INTO orders(id,store,status) VALUES(1,'Synthetic store','Open')")
        db.execute("INSERT INTO jobs(source,kind,item_type,item_no,state,created_at,updated_at) VALUES('bricklink','prices','S','100-1','done','2026-10-01T00:00:00+00:00','2026-10-01T00:00:00+00:00')")
        db.execute("INSERT INTO identifications(id,created_at,has_thumb,candidates,missing_count) VALUES('i1','2026-10-01T00:00:00+00:00',1,'[]',0)")
        admin.audit(db, 'bw_collection', 'save', [], [])
    with sqlite3.connect(path.with_name('bricklink-catalog.db')) as cat:
        cat.execute('CREATE TABLE items(item_type TEXT,item_no TEXT,name TEXT,category TEXT,year INTEGER,normalized_name TEXT)')
        cat.execute("INSERT INTO items VALUES('S','100-1','Synthetic set','Synthetic',2024,'synthetic set')")
        cat.execute('CREATE TABLE metadata(info TEXT)')
        cat.execute('INSERT INTO metadata VALUES(?)', (json.dumps({'loaded_at':'2026-10-01T00:00:00+00:00','counts':{'S':1}}),))
    for directory, name, content in [('instructions','synthetic.pdf',b'%PDF-1.4\n%%EOF'),('images','synthetic.png',b'\x89PNG\r\n\x1a\n'),('identifications','i1.jpg',b'\xff\xd8\xff\xd9')]:
        target = path.parent / 'data' / directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return app


def concrete(path):
    kind, no = ('P','3001') if any(x in path for x in ('used-in', '/colors', '/prices')) else ('S','100-1')
    identifier = ('default' if path.startswith('/wishlists/') else 'm1' if path == '/stock/{id}/parts' else 't1' if path.startswith('/stock/') else 'c1' if path.startswith('/copies/') else
                  's1' if path.startswith('/storages/') else 'l1' if path.startswith('/lots/') else
                  'i1' if path.startswith('/identifications/') else '1')
    path = path.replace('{type}',kind).replace('{no}',no).replace('{id}',identifier).replace('{color_id}','4')
    if path == '/minifigures/100-1': path = '/minifigures/fig1'
    if path.startswith('/export/'): path += '?ids=c1'
    return path


@pytest.mark.parametrize('path,operation', OPS, ids=[p for p, _ in OPS])
def test_every_get_contract(populated, path, operation):
    if path.startswith('/export/'):
        with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
            db.execute("UPDATE id_match SET status='matched'")
    response = call(populated, concrete(path))
    assert response.status_code == 200, response.text
    definition = resolve(operation['responses']['200'])
    media = response.content_type.split(';')[0]
    if media.startswith('image/') and 'image/*' in definition['content']:
        media = 'image/*'
    assert media in definition['content']
    if media == 'application/json':
        validate(response.json, definition['content'][media]['schema'])
    assert response.headers['Cache-Control'] == 'no-store'
    if path == '/instruction-files/{id}':
        assert response.json['data']['item_no'] == '100-1'
        assert response.json['data']['content_url'] == '/api/v1/instruction-files/1/content'


@pytest.mark.parametrize('path,operation', OPS, ids=[p for p, _ in OPS])
def test_every_get_auth_and_unknown_filters(populated, path, operation):
    url = concrete(path)
    unauthorized = call(populated, url, token='invalid')
    assert unauthorized.status_code == 401
    response = call(populated, url + ('&' if '?' in url else '?') + 'synthetic_unknown=x')
    assert response.status_code == 400, response.text
    assert response.json['code'] == 'unknown_filter'


def list_operations():
    return [(p, o) for p, o in OPS if 'ListOf' in o['responses']['200'].get('content', {}).get('application/json', {}).get('schema', {}).get('$ref','') or p == '/planning/ranking']


def expand_fixture(dbpath, count):
    with closing(connect(dbpath)) as db, db:
        for index in range(count):
            number = 'synthetic-' + str(index)
            db.execute('INSERT INTO items(item_type,item_no,name) VALUES(?,?,?)', ('S',number,number))
            db.execute('INSERT INTO copies(id,set_no,condition,completeness,completeness_source) VALUES(?,?,?,?,?)', (number,number,'U','I','derived'))
            db.execute('INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES(?,?,?,?,?,?,?,?)',(number,'P','3001',4,1,1,0,0))
            db.execute('INSERT INTO loose_stock(id,item_type,item_no,quantity,condition) VALUES(?,?,?,?,?)',(number,'S',number,1,'U'))
            db.execute('INSERT INTO wishlist(item_type,item_no,quantity) VALUES(?,?,?)',('S',number,1))
            db.execute("INSERT INTO id_match(source,kind,source_id,item_type,item_no,status,evidence_json) VALUES('rebrickable','set',?,'S',?, 'to_check','[]')",(number,number))
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('M',?,?)", (number,number))
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P',?,?)", (number,number))
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('I',?,?)", (number,number))
            db.execute("INSERT INTO colors VALUES(?,?,'Solid','000000')", (1000+index, number))
            db.execute('INSERT INTO wishlists(id,name) VALUES(?,?)', (number,number))
            db.execute('INSERT INTO storages(id,name) VALUES(?,?)', (number,number))
            db.execute('INSERT INTO purchase_locations(id,name) VALUES(?,?)', (number,number))
            db.execute('INSERT INTO lots(id,name) VALUES(?,?)', (number,number))
            db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,'tag',1)", (number,number))
            db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('c1','M',?,1,1)", (number,))
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES('c1','P',?,4,1,1,0,0)", (number,))
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition) VALUES(?,'M',?,1,'U')", ('figure-'+number,number))
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P',?,4,2,'U')", ('part-'+number,number))
            db.execute("INSERT INTO loose_minifig_parts(stock_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES('m1','P',?,4,1,1,0,0)", (number,))
            db.execute("INSERT INTO inventory_lines(parent_item_type,parent_item_no,child_item_type,child_item_no,color_id,quantity,source) VALUES('S','100-1','P',?,4,1,'bricklink')", (number,))
            db.execute("INSERT INTO instruction_files(item_type,set_no,path,label) VALUES('S',?,'data/instructions/synthetic.pdf',?)", (number,number))
            db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path) VALUES('P','3001','bricklink','photo','data/images/synthetic.png')")
            db.execute("INSERT INTO item_images(item_type,item_no,source,kind,local_path) VALUES('S','100-1','bricklink','photo','data/images/synthetic.png')")
            db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,source,observed_at) VALUES('P','3001',?,'U','sold','EUR','2.50','bricklink','2026-10-01T00:00:00+00:00')", (1000+index,))
            price_id = db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,source,observed_at) VALUES('S',? ,NULL,'U','sold','EUR','2.50','bricklink','2026-10-01T00:00:00+00:00')",(number,)).lastrowid
            db.execute("INSERT INTO price_current(item_type,item_no,condition,guide,currency,observation_id) VALUES('S',?,'U','sold','EUR',?)", (number,price_id))
            db.execute("INSERT INTO jobs(source,kind,state,created_at,updated_at) VALUES('bricklink','prices','done','2026-10-01T00:00:00+00:00','2026-10-01T00:00:00+00:00')")
            db.execute("INSERT INTO sources(source,name,kind) VALUES(?,?,'manual')", (number,number))
            db.execute('INSERT INTO orders(store) VALUES(?)', (number,))
            db.execute("INSERT INTO identifications(id,has_thumb,candidates) VALUES(?,0,'[]')", (number,))
            admin.audit(db, 'bw_collection', 'save', [], [])
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES('c1','P','3001',4,1,0,0,0)")
    with sqlite3.connect(Path(dbpath).with_name('bricklink-catalog.db')) as cat:
        cat.executemany("INSERT INTO items VALUES('S',?,?,'Synthetic',2024,?)", [(f'synthetic-{i}',f'Synthetic {i}',f'synthetic {i}') for i in range(count)])



@pytest.mark.parametrize('path,operation', list_operations(), ids=[p for p, _ in list_operations()])
def test_list_query_count(populated, monkeypatch, path, operation):
    import brickwork.api as api
    dbpath = os.environ['BW_DB_PATH']
    queries = []
    real_connect = api.connect
    def traced(*args, **kwargs):
        db = real_connect(*args, **kwargs)
        db.set_trace_callback(queries.append)
        return db
    monkeypatch.setattr(api, 'connect', traced)
    first = call(populated, concrete(path))
    assert first.status_code == 200, first.text
    initial = len(queries)
    expand_fixture(dbpath, 300)

    queries.clear()
    second = call(populated, concrete(path))
    assert second.status_code == 200, second.text
    assert len(queries) <= initial + 2, (path, initial, len(queries))


def test_api_shared_browser_fixtures(app, monkeypatch):
    """Actual HTTP filtering/sorting, Python and browser share the same fixtures."""
    from urllib.parse import urlencode
    from brickwork.core.listing import filter_rows
    import subprocess
    fixture = json.loads(Path('tests/fixtures/bw_filter_rows.json').read_text())
    values = [dict(r, item_type=r['type'], item_no=r['number']) for r in fixture['rows']]
    monkeypatch.setattr(api_reads, 'entities', lambda db, entity: values)
    script = """const fs=require('fs'),vm=require('vm');global.window={BrickFormatting:{nowrapTail:()=>{}}};global.document={querySelector:()=>null,querySelectorAll:()=>[],addEventListener:()=>{}};vm.runInThisContext(fs.readFileSync('static/web/toni/bw-collection.js','utf8'));const f=JSON.parse(fs.readFileSync('tests/fixtures/bw_filter_rows.json'));console.log(JSON.stringify(f.cases.map(c=>window.BrickCollection.filterRows(f.rows,c.query,c.filters,c.sort,c.direction).map(r=>r.id))));"""
    browser = json.loads(subprocess.run(['node','-e',script], check=True, capture_output=True, text=True).stdout)
    for case, expected in zip(fixture['cases'], browser):
        query = dict(q=case['query'], sort=case['sort'], direction=case['direction'], **case['filters'])
        response = call(app, '/copies?' + urlencode(query))
        assert response.status_code == 200, response.text
        assert [r['id'] for r in response.json['data']] == expected
        assert [r['id'] for r in filter_rows(fixture['rows'], **case)] == expected


@pytest.mark.parametrize('sort,direction', [('number','asc'),('number','desc'),('name','asc'),('used_price','desc'),('missing','asc')])
def test_http_cursor_stable_under_inserts(populated, sort, direction):
    from urllib.parse import urlencode
    dbpath = os.environ['BW_DB_PATH']
    with closing(connect(dbpath)) as db, db:
        for i in range(12):
            db.execute("INSERT INTO copies(id,set_no,condition,completeness) VALUES(?,'100-1','U','I')", (f'copy-{i:02}',))
    options = dict(limit=4, sort=sort, direction=direction)
    first = call(populated, '/copies?' + urlencode(options)).json
    seen = [r['id'] for r in first['data']]
    with closing(connect(dbpath)) as db, db:
        db.execute("INSERT INTO copies(id,set_no,condition,completeness) VALUES('before','100-1','U','I')")
    cursor = first['page']['next_cursor']
    while cursor:
        response = call(populated, '/copies?' + urlencode(dict(options, cursor=cursor)))
        assert response.status_code == 200, response.text
        seen.extend(r['id'] for r in response.json['data'])
        cursor = response.json['page']['next_cursor']
    assert len(seen) == len(set(seen))
    assert set(seen) >= {'c1', *(f'copy-{i:02}' for i in range(12))}
    bad = call(populated, '/stock?' + urlencode(dict(options, cursor=first['page']['next_cursor'])))
    assert bad.status_code == 400


def test_archive_etags_and_enums(populated):
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE copies SET archived_at='2026-10-01T00:00:00+00:00' WHERE id='c1'")
        db.execute("UPDATE loose_stock SET archived_at='2026-10-01T00:00:00+00:00' WHERE id='t1'")
        db.execute("UPDATE wishlist SET archived_at='2026-10-01T00:00:00+00:00' WHERE id=1")
        db.execute("UPDATE purchase_locations SET archived_at='2026-10-01T00:00:00+00:00' WHERE id='p1'")
    assert call(populated, '/copies').json['data'] == []
    assert call(populated, '/places').json['data'] == []
    assert len(call(populated, '/copies?archived=only').json['data']) == 1
    assert len(call(populated, '/places?archived=only').json['data']) == 1
    for path in ('/copies/c1', '/stock/t1', '/wishes/1'):
        response = call(populated, path)
        assert response.status_code == 200
        assert response.headers['ETag']
        assert response.json['data']['condition'] == 'used'
        assert response.json['data']['archived_at']


@pytest.mark.parametrize('path,expected', [
    ('/copies?condition=used&status=incomplete&storage=s1&place=p1&flag=f1&problem=damaged', ['c1']),
    ('/stock?colour=4&lot=l1', ['t1']),
    ('/wishes?condition=used&under_max=true', [1]),
    ('/wishes?under_max=false', []),
    ('/jobs?failed=false&source=bricklink', [1]),
    ('/instruction-files?has_file=true', [1]),
    ('/copies/c1/parts?spare=false&parent=null', [1]),
])
def test_resource_filters(populated, path, expected):
    response = call(populated, path)
    assert response.status_code == 200, response.text
    assert [r['id'] for r in response.json['data']] == expected


def test_under_max_never_compares_currencies(populated):
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE wishlist SET max_price_currency='USD'")
    assert call(populated, '/wishes?under_max=true').json['data'] == []
    assert call(populated, '/wishes?under_max=false').json['data'] == []


@pytest.mark.parametrize('path', ['/copies/absent', '/stock/absent', '/wishes/999', '/items/S/absent',
    '/copies/absent/parts', '/copies/absent/gaps', '/jobs/999', '/events/999', '/orders/999',
    '/instruction-files/999', '/colors/999', '/storages/absent', '/lots/absent', '/identifications/absent'])
def test_missing_records(populated, path):
    response = call(populated, path)
    assert response.status_code == 404, response.text
    assert response.json['code'] == 'not_found'


def test_events_undo_metadata(populated):
    from tests.test_bw_api_m1 import create
    created = create(populated).json
    event = created['event_id']
    assert call(populated, f'/events/{event}').json['data']['undoable'] is True
    response = populated.test_client().post(f'/api/v1/events/{event}/undo', headers={
        'Authorization': 'Bearer synthetic-bootstrap', 'Idempotency-Key': 'synthetic-events'})
    assert response.status_code == 200
    saved = call(populated, f'/events/{event}').json['data']
    assert saved['undone'] is True and saved['undoable'] is False


def test_sources_and_all_reads_hide_secrets(populated, monkeypatch):
    from cryptography.fernet import Fernet
    from brickwork.core import secrets
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-env-credential-value')
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        encrypted = secrets.encrypt('synthetic-stored-credential-value')
        db.execute("INSERT INTO source_keys(source,ciphertext,saved_at) VALUES('rebrickable',?,'2026-10-01T00:00:00+00:00')", (encrypted,))
        admin.audit(db, 'source_key:rebrickable', 'save', None, {'ciphertext': encrypted})
    sources = call(populated, '/sources').json['data']
    key = next(r for r in sources if r['source'] == 'rebrickable')['key']
    assert key == dict(configured=True, origin='env', saved_at='2026-10-01T00:00:00+00:00')
    monkeypatch.delenv('BW_REBRICKABLE_API_KEY')
    key = next(r for r in call(populated, '/sources').json['data'] if r['source'] == 'rebrickable')['key']
    assert key['origin'] == 'stored'
    for path, _ in OPS:
        response = call(populated, concrete(path))
        assert encrypted.encode() not in response.data
        assert b'synthetic-stored-credential-value' not in response.data
        assert b'synthetic-env-credential-value' not in response.data
    export = call(populated, '/database/export')
    # The stored key is stripped from the copy (a snapshot with plaintext credentials would still be refused).
    assert export.status_code == 200 and encrypted.encode() not in export.data
    assert b'synthetic-stored-credential-value' not in export.data
    with closing(sqlite3.connect(':memory:')) as copy:
        copy.deserialize(export.data)
        assert copy.execute('SELECT count(*) FROM source_keys').fetchone()[0] == 0


def test_used_in_and_known_colors(populated):
    response = call(populated, '/items/P/3001/used-in')
    row = response.json['data'][0]
    assert (row['copy_id'], row['quantity'], row['missing'], row['color_id']) == ('c1',4,2,4)
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("INSERT INTO colors VALUES(5,'Synthetic blue','Solid','0000FF')")
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing) VALUES('c1','P','3001',5,3,1)")
    assert {r['color_id'] for r in call(populated, '/items/P/3001/colors').json['data']} == {4,5}
    assert call(populated, '/items/P/3001/used-in').json['data'][0]['quantity'] == 7


def test_etag_tracks_saved_fields_and_flags_only(populated):
    before = call(populated, '/copies/c1').headers['ETag']
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE items SET name='Synthetic renamed set' WHERE item_type='S' AND item_no='100-1'")
    assert call(populated, '/copies/c1').headers['ETag'] == before
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE copies SET note='Synthetic note' WHERE id='c1'")
    assert call(populated, '/copies/c1').headers['ETag'] != before


def test_missing_catalogue_and_read_scopes(app, populated):
    from tests.test_bw_api_m1 import create
    Path(os.environ['BW_DB_PATH']).with_name('bricklink-catalog.db').unlink()
    assert call(populated, '/catalogue/items').json['code'] == 'catalogue_not_loaded'
    assert call(populated, '/catalogue/status').json['data']['loaded'] is False
    secret = create(populated).json['data']['secret']
    for path in ('/database/check','/database/export'):
        assert call(populated, path, token=secret).status_code == 403
    assert call(populated, '/sources', token=secret).status_code == 200


def test_unrecorded_states_and_checked_boolean(populated):
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE copies SET condition=NULL,completeness=NULL,completeness_source=NULL WHERE id='c1'")
        db.execute("UPDATE copy_parts SET checked=1 WHERE copy_id='c1'")
        identifier = db.execute("INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,currency,price,source) VALUES('P','3001',4,NULL,'retail','EUR','1.00','bricklink')").lastrowid
        db.execute("INSERT INTO price_current(item_type,item_no,color_id,condition,guide,currency,observation_id) VALUES('P','3001',4,NULL,'retail','EUR',?)", (identifier,))
    for path in ('/copies', '/copies/c1', '/copies/c1/parts'):
        operation = CONTRACT['paths'][path.replace('c1','{id}')]['get']
        response = call(populated, path)
        validate(response.json, operation['responses']['200']['content']['application/json']['schema'])
    assert call(populated, '/copies/c1/parts').json['data'][0]['checked'] is True
    for path in ('/prices', '/items/P/3001/prices/history'):
        response = call(populated, path)
        template = path.replace('/P/3001/', '/{type}/{no}/')
        validate(response.json, CONTRACT['paths'][template]['get']['responses']['200']['content']['application/json']['schema'])


def test_archived_lot_keeps_detail_shape(populated):
    before = call(populated, '/lots/l1').json['data']
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE lots SET archived_at='2026-10-01T00:00:00+00:00' WHERE id='l1'")
    after = call(populated, '/lots/l1').json['data']
    assert after['lot']['id'] == before['lot']['id'] and after['rows'] == before['rows']
    assert after['lot']['archived_at']


def test_colour_filter_keeps_name_for_search(populated):
    response = call(populated, '/stock?colour=4&q=red')
    assert response.status_code == 200
    assert [r['id'] for r in response.json['data']] == ['t1']


def test_match_cursor_distinguishes_sources_for_one_gap(populated, monkeypatch):
    from urllib.parse import urlencode
    values = [dict(id=7, item_type='P',item_no='3001',copy_id='c1', target='part',target_id=7,source_id=f'source-{i}') for i in range(12)]
    monkeypatch.setattr(api_reads.workbench, 'matches', lambda db: values)
    seen, cursor = [], None
    while True:
        response = call(populated, '/copies/c1/matches?' + urlencode(dict(limit=3, **({'cursor':cursor} if cursor else {}))))
        assert response.status_code == 200, response.text
        seen.extend(r['source_id'] for r in response.json['data'])
        cursor = response.json['page']['next_cursor']
        if not cursor: break
    assert len(seen) == 12 and len(set(seen)) == 12


def test_planning_preserves_core_rank_order_and_cursor(populated, monkeypatch):
    from decimal import Decimal
    from urllib.parse import urlencode
    from brickwork.core import planning
    values = [dict(id='a',item_type='S',item_no='100-1',set_num='100-1',name='Synthetic A',group='ranked',ratio=Decimal('1.5'),net_gain=Decimal('4'),unresolved_items=0,items=[]),
              dict(id='z',item_type='S',item_no='900-1',set_num='900-1',name='Synthetic Z',group='ranked',ratio=Decimal('2.5'),net_gain=Decimal('8'),unresolved_items=0,items=[])]
    monkeypatch.setattr(planning, 'ranking', lambda db: dict(rows=values, settings={}))
    response = call(populated, '/planning/ranking?limit=1')
    assert response.status_code == 200, response.text
    assert response.json['data'][0]['id'] == 'z'
    values.append(dict(values[0], id='before', ratio=Decimal('3.5')))
    second = call(populated, '/planning/ranking?' + urlencode(dict(limit=1,cursor=response.json['page']['next_cursor'])))
    assert second.json['data'][0]['id'] == 'a'
    assert second.json['page']['next_cursor'] is None


@pytest.mark.parametrize('path,operation', list_operations() + [('/tokens', CONTRACT['paths']['/tokens']['get'])],
                         ids=[p for p, _ in list_operations()] + ['/tokens'])
def test_every_list_pages_without_losses(populated, path, operation):
    from urllib.parse import urlencode
    expand_fixture(os.environ['BW_DB_PATH'], 2)
    if path == '/tokens':
        from tests.test_bw_api_m1 import create
        create(populated, name='synthetic-first')
        create(populated, name='synthetic-second')
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        # Equal item/colour, different conditions and origin tables used to collide.
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('new-brick','P','3001',4,3,'N')")
    url = concrete(path)
    expected = call(populated, url + '?limit=200').json['data']
    assert len(expected) > 1, path
    seen, cursors = [], set()
    cursor = None
    while True:
        options = dict(limit=1)
        if cursor:
            options['cursor'] = cursor
        response = call(populated, url + '?' + urlencode(options))
        assert response.status_code == 200, response.text
        validate(response.json, operation['responses']['200']['content']['application/json']['schema'])
        seen.extend(response.json['data'])
        cursor = response.json['page']['next_cursor']
        if not cursor:
            break
        assert cursor not in cursors, path
        cursors.add(cursor)
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    assert canonical(seen) == canonical(expected), path
    assert len(canonical(seen)) == len(set(canonical(seen))), path


def test_item_summary_counts_copies_and_loose_excludes_archived(populated):
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("INSERT INTO copies(id,set_no) VALUES('c2','100-1')")
        db.execute("INSERT INTO copies(id,set_no,archived_at) VALUES('old-copy','100-1','2026-10-01')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity) VALUES('loose-set','S','100-1',7)")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,archived_at) VALUES('old-stock','S','100-1',99,'2026-10-01')")
        db.execute("INSERT INTO wishlist(item_type,item_no,quantity) VALUES('S','100-1',3)")
    response = call(populated, '/items/S/100-1')
    assert response.json['data']['counts'] == dict(owned=9, wished=True)
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE wishlist SET archived_at='2026-10-01' WHERE item_type='S'")
    assert call(populated, '/items/S/100-1').json['data']['counts'] == dict(owned=9, wished=False)


def test_sources_retry_uses_enforced_counter(populated):
    from brickwork.core.sources.base import Source, budget_used, now
    class OfflineSource(Source):
        source = 'bricklink'
        daily_budget = 100
    with closing(connect(os.environ['BW_DB_PATH'])) as db:
        source = OfflineSource(db)
        job = source.reserve('prices', {})
        with db:
            db.execute("UPDATE jobs SET state='waiting_for_budget' WHERE id=?", (job,))
        assert source.reserve('prices', {}, job_id=job) == job
        assert db.execute('SELECT budget_used FROM jobs WHERE id=?', (job,)).fetchone()[0] == 1
        expected = budget_used(db, 'bricklink', now().date().isoformat())
        assert expected == 2
    row = next(r for r in call(populated, '/sources').json['data'] if r['source'] == 'bricklink')
    assert row['used_today'] == expected


def test_public_names_and_price_shape(populated):
    item = call(populated, '/items/S/100-1').json['data']['item']
    assert item['image_id'] == 1 and 'image' not in item
    wish = call(populated, '/wishes/1').json['data']
    assert wish['under_max'] is True and wish['current_price'] == '2.50'
    assert not {'max_state', 'max_margin', 'display_price'} & wish.keys()
    prices = call(populated, '/items/P/3001/prices').json['data']
    assert set(prices) == {'current', 'records'}
    assert prices['current'][0]['observation'] == prices['records'][0]
    assert isinstance(prices['current'][0]['age_days'], (int, float))
    with closing(connect(os.environ['BW_DB_PATH'])) as db, db:
        db.execute("UPDATE wishlist SET max_price_currency='USD'")
    assert call(populated, '/wishes/1').json['data']['under_max'] is None
