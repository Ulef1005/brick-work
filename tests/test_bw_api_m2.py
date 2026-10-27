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


@pytest.mark.parametrize('path,expected', [
    ('/jobs?failed=false&source=bricklink', [1]),
])
def test_resource_filters(populated, path, expected):
    response = call(populated, path)
    assert response.status_code == 200, response.text
    assert [r['id'] for r in response.json['data']] == expected


@pytest.mark.parametrize('path', ['/jobs/999', '/orders/999', '/identifications/absent'])
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


def test_missing_catalogue_and_read_scopes(app, populated):
    from tests.test_bw_api_m1 import create
    secret = create(populated).json['data']['secret']
    for path in ('/database/check','/database/export'):
        assert call(populated, path, token=secret).status_code == 403
    assert call(populated, '/sources', token=secret).status_code == 200


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
