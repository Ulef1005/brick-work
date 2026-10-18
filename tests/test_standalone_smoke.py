"""Standalone installation contract: real app and CLI, synthetic data, no sockets."""
from contextlib import closing
import os
from pathlib import Path
import secrets
import socket

from flask import Flask

from brickwork.app import setup_app
from brickwork.core.connect import connect
from brickwork.web.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_standalone_smoke(tmp_path, monkeypatch):
    attempts = []
    def blocked(*args, **kwargs):
        attempts.append(True)
        raise AssertionError('Standalone smoke attempted an outbound connection')
    for method in ('connect', 'connect_ex'):
        monkeypatch.setattr(socket.socket, method, blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    for key in list(os.environ):
        if key.startswith('BW_'):
            monkeypatch.delenv(key)
    path = tmp_path / 'data' / 'brickwork.db'
    bootstrap = secrets.token_urlsafe(32)
    monkeypatch.setenv('BW_DB_PATH', str(path))
    monkeypatch.setenv('BW_API_TOKEN', bootstrap)
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_KEY', 'synthetic-session')
    assert main(['setup']) == 0
    assert path.is_file()
    app = Flask('standalone-smoke', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config['TESTING'] = True
    client = app.test_client()
    sequence = 0
    def call(route, method='GET', body=None):
        nonlocal sequence
        sequence += 1
        headers = {'Authorization': 'Bearer ' + bootstrap, 'Idempotency-Key': f'smoke-{sequence}'}
        return client.open('/api/v1' + route, method=method, headers=headers,
                           **({'json': body} if body is not None else {}))
    for route in ('/health', '/version', '/me', '/settings', '/sources', '/statistics', '/copies',
                  '/stock', '/wishes', '/events', '/jobs', '/storages', '/lots', '/places', '/flags'):
        response = call(route)
        assert response.status_code == 200, (route, response.text)
    assert client.get('/').status_code == 200
    # 12j: an install with no keys, no catalogue and no sets shows the first-run path, with no key value.
    with client.session_transaction() as session:
        session['_user_id'] = 'admin'
        session['_fresh'] = True
    first_run = client.get('/collection/sets')
    assert first_run.status_code == 200
    html = first_run.get_data(as_text=True)
    assert 'data-first-run' in html and 'Nothing here yet.' in html and 'href="/manage/catalogues"' in html
    assert html.count('class="fr-step"') + html.count('class="fr-step ') == 4 and 'disabled' in html
    for route, body in (('/copies', {'item_no': '100-1'}),
                        ('/stock', {'item_type': 'P', 'item_no': '3001', 'color_id': 4, 'quantity': 1}),
                        ('/wishes', {'item_type': 'S', 'item_no': '100-1'})):
        response = call(route, 'POST', body)
        assert response.status_code == 424, response.text
        assert response.json['code'] == 'catalogue_not_loaded'
    assert call('/catalogue/items').json['code'] == 'catalogue_not_loaded'
    storage = call('/storages', 'POST', {'name': 'Synthetic shelf'})
    assert storage.status_code == 201, storage.text
    # Load real catalogue XML through the shared API operation, without a source call.
    directory = path.parent / 'bricklink-catalog-src'
    directory.mkdir()
    for kind, number in [('S', '100-1'), ('S', '100-2'), ('P', '3001'), ('M', 'fig1'), ('I', 'booklet1'), ('O', 'box1'), ('G', 'gear1'), ('B', 'book1'), ('C', 'catalog1')]:
        (directory / (kind + number + '.xml')).write_text(f'<CATALOG><ITEM><ITEMTYPE>{kind}</ITEMTYPE><ITEMID>{number}</ITEMID><ITEMNAME>Synthetic {kind}</ITEMNAME><CATEGORY>1</CATEGORY></ITEM></CATALOG>')
    loaded = call('/catalogue/import', 'POST')
    assert loaded.status_code == 200, loaded.text
    copied = call('/copies', 'POST', {'item_no': '100-1', 'storage_id': storage.json['data']['id']})
    assert copied.status_code == 201, copied.text
    copy_id = copied.json['data']['ids'][0]
    # Synthetic inventory fixture stands in for the optional network inventory import.
    with closing(connect(path)) as db, db:
        db.execute("INSERT INTO colors(color_id,name) VALUES(4,'Synthetic red')")
        db.execute("INSERT INTO items(item_type,item_no,name) VALUES('P','3001','Synthetic brick')")
        part = db.execute('INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,spare) VALUES(?,?,?,?,2,0,0,0)',
                          (copy_id, 'P', '3001', 4)).lastrowid
    marked = call(f'/copies/{copy_id}/parts/{part}', 'PATCH', {'missing': 1})
    assert marked.status_code == 200, marked.text
    assert call(f'/copies/{copy_id}/parts').json['data'][0]['missing'] == 1
    price = call('/items/S/100-1/prices', 'POST', {'condition': 'used', 'guide': 'manual', 'price': '8.50', 'currency': 'EUR'})
    assert price.status_code == 201, price.text
    undone = call(price.json['undo_url'].removeprefix('/api/v1'), 'POST')
    assert undone.status_code == 200, undone.text
    with closing(connect(path)) as db:
        assert db.execute("SELECT error FROM price_observations WHERE source='manual'").fetchone()[0] == 'undone'
        assert db.execute("SELECT count(*) FROM price_current").fetchone()[0] == 0
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?', (part,)).fetchone()[0] == 1
    for route, body in (('/colors/sync', None), ('/orders/documents', {'source': 'api', 'number': '123456'}),
                        ('/sources/rebrickable/key/test', None), ('/sources/brickset/key/test', None)):
        response = call(route, 'POST', body)
        assert response.status_code == 424, (route, response.text)
        assert response.json['code'] == 'source_not_configured'
    # Queueing does not need keys; execution reports typed failures without dialing out.
    queued = call('/items/S/100-2/prices/refresh', 'POST', {})
    assert queued.status_code == 202, queued.text
    from brickwork.core.pipeline import Pipeline
    with closing(connect(path)) as db:
        Pipeline(db).run(queued.json['data']['id'])
    job = call('/jobs/' + str(queued.json['data']['id']))
    assert 'source_not_configured' in job.text
    toggled = call('/sources/bricklink', 'PATCH', {'enabled': False})
    assert toggled.status_code == 200, toggled.text
    assert call('/colors/sync', 'POST').json['code'] == 'source_disabled'
    assert call('/events').json['data']
    assert next(s for s in call('/sources').json['data'] if s['source'] == 'bricklink')['key']['configured'] is False
    assert {f.name for f in path.parent.glob('*.db')} == {'brickwork.db', 'bricklink-catalog.db'}
    assert attempts == []
