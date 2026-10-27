"""Standalone installation contract on the 4.0 store: real app and CLI, a fixture catalogue built offline, no sockets (M.8a, #110).

What renders without ported modules: the install files, the login page, Add (M.8c), Check Set Parts and the collection's writes (M.8d), the
Workbench (Matcher, Part Picker, Take and Give, Storage, printable lists; M.8e), the sources (pictures, Brickset, BrickLink prices, the Prices
screen and a set fetched from Rebrickable; M.8f), planning (Complete sets ranked, pinned and exported, the Wishlist with its lists, exports and Undo,
the part-out value and manual prices; M.8g) and (M.8b)
the collection's read side: `/` and the collection lists
(the first-run page on an empty collection), the item page by id, the wish, lot and purchase-place pages, the jump search. Every other browser
screen answers 503 until its piece ports it. API v1 answers 410, except `/api/v1/health`."""
from contextlib import closing
import os
from pathlib import Path
import json
import secrets
import shutil
import socket
import sqlite3

from bs4 import BeautifulSoup
import pytest
from flask import Flask

from brickwork.app import setup_app
from brickwork.core.connect import OldStore, connect
from brickwork.core.errors import API_V1_RETIRED
from brickwork.version import __version__
from brickwork.web.cli import main
from tests.app4 import Coll, build_world, make_pair
from tests.legacy33 import create_33
from tests.store4_mint_fixtures import build_catalogue
from tests.web_fixtures import logged_in

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def offline(monkeypatch):
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
    return attempts


def make_app(path, monkeypatch):
    monkeypatch.setenv('BW_DB_PATH', str(path))
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_KEY', 'synthetic-session')
    app = Flask('standalone-smoke', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config['TESTING'] = True
    return app


def test_standalone_smoke(tmp_path, monkeypatch, offline, capsys):
    path = tmp_path / 'data' / 'brickwork.db'
    bootstrap = secrets.token_urlsafe(32)
    monkeypatch.setenv('BW_DB_PATH', str(path))
    monkeypatch.setenv('BW_API_TOKEN', bootstrap)
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_KEY', 'synthetic-session')
    # setup makes a fresh 4.0 collection and says where the catalogue comes from
    assert main(['setup']) == 0
    said = capsys.readouterr().out
    assert path.is_file() and 'missing' in said and 'catalogue download' in said
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4.0'
    with pytest.raises(Exception, match='No catalogue at .*catalogue.db'):
        connect(path)
    # the fixture catalogue, built offline, goes beside the collection
    (tmp_path / 'cat').mkdir()
    shutil.copy(build_catalogue(tmp_path / 'cat'), path.with_name('catalogue.db'))
    app = make_app(path, monkeypatch)
    client = app.test_client()
    # health is the one v1 route that answers: no token, the app version and the 4.0 schema
    health = client.get('/api/v1/health')
    assert health.status_code == 200, health.text
    assert health.json['data'] == {'status': 'ok', 'api': '1.0.0', 'app': __version__, 'schema': '4.0'}
    # every other v1 route is gone, with or without a token, and says why
    for method, route in (('get', '/version'), ('get', '/me'), ('get', '/copies'), ('post', '/copies'), ('get', '/events'),
                          ('post', '/events/1/undo'), ('get', '/openapi.yaml'), ('get', '/does-not-exist')):
        response = getattr(client, method)('/api/v1' + route, headers={'Authorization': 'Bearer ' + bootstrap})
        assert response.status_code == 410, (route, response.status_code)
        assert response.mimetype == 'application/problem+json'
        assert response.json['code'] == 'api_retired' and API_V1_RETIRED in response.json['detail']
    assert client.get('/api/v1/copies').status_code == 410                       # not even a token is asked for
    # the first-run page is what renders on an empty collection
    for route in ('/', '/collection/sets'):
        first_run = client.get(route)
        assert first_run.status_code == 200, route
        html = first_run.get_data(as_text=True)
        assert 'data-first-run' in html and 'Nothing here yet.' in html and 'href="/manage/catalogues"' in html
        assert html.count('class="fr-step"') + html.count('class="fr-step ') == 4
    assert 'Cache-Control' in client.get('/').headers
    # a screen that is not ported yet says so, in the app's own shell
    held = client.get('/manage/tools')
    assert held.status_code == 503 and 'not on the 4.0 store yet' in held.get_data(as_text=True)
    assert client.get('/manifest.webmanifest').status_code == 200
    assert client.get('/login').status_code == 200
    # the MCP server talks v1 and refuses with the same explanation
    assert main(['mcp']) == 1
    assert API_V1_RETIRED in capsys.readouterr().err
    assert {f.name for f in path.parent.glob('*.db')} == {'brickwork.db', 'catalogue.db'}
    assert offline == []


def test_a_3_3_collection_is_refused_with_the_fix_named(tmp_path, monkeypatch, offline):
    path = tmp_path / 'data' / 'brickwork.db'
    path.parent.mkdir()
    create_33(path).close()
    (tmp_path / 'cat').mkdir()
    shutil.copy(build_catalogue(tmp_path / 'cat'), path.with_name('catalogue.db'))
    before = path.read_bytes()
    with pytest.raises(OldStore, match=r'python -m brickwork\.store4 migrate'):
        connect(path)
    with pytest.raises(OldStore, match='3.2/3.3'):
        connect(path, read_only=True)
    with pytest.raises(OldStore):
        make_app(path, monkeypatch)                                                # the app does not boot on it
    assert main(['setup']) == 1                                                     # BW_DB_PATH names it: setup refuses too
    assert path.read_bytes() == before                                              # refused means untouched
    assert offline == []


def test_the_collection_read_side_shows_what_is_owned(tmp_path, monkeypatch, offline):
    """The workflow of docs/concepts/collection-model.md on a fixture pair: sets and their copies, loose stock, lots, wishes, the numbers
    on screen (Rebrickable first, BrickLink beside it, a local BrickLink-born item marked), an unidentified item, and the old number URL."""
    path = make_pair(tmp_path, rich=True)
    with closing(connect(path)) as db:
        w = build_world(Coll(db))
    client = make_app(path, monkeypatch).test_client()
    for route in ('/', '/collection/sets', '/collection/M', '/collection/P', '/collection/I', '/collection/G', '/collection/wishes', '/collection/purchase-places'):
        response = client.get(route)
        assert response.status_code == 200, route
        assert 'data-first-run' not in response.get_data(as_text=True)
    sets = client.get('/collection/sets').get_data(as_text=True)
    assert '1000-1' in sets and 'Syn Castle Keep' in sets and 'data-type="S"' in sets
    parts = client.get('/collection/P').get_data(as_text=True)
    assert 'Only on BrickLink' in parts and 'x999' in parts
    # the item page of a set: the copy asked for, its numbers, its states in words
    page = client.get(f'/collection/item/{w.keep}?copy={w.copy_a}')
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and 'Syn Castle Keep' in html and 'Incomplete' in html and 'Used' in html and '1 missing' in html
    assert client.get(f'/collection/item/{w.keep}?copy=nothing').status_code == 404
    # a part in a colour, a figure, a local BrickLink-born item and an unidentified one
    assert client.get(f'/collection/item/{w.brick}?colour={w.red}').status_code == 200
    one_colour = client.get(f'/collection/item/{w.brick}')                                   # one colour held: straight to it
    assert one_colour.status_code == 302 and f'colour={w.red}' in one_colour.headers['Location']
    assert client.get(f'/collection/item/{w.figure}?stock={w.stock_figure}').status_code == 200
    local = client.get(f'/collection/item/{w.local_part}?stock={w.stock_local}&colour={w.red}').get_data(as_text=True)
    assert 'x999 (BrickLink)' in local
    mystery = client.get(f'/collection/item/{w.mystery}?stock={w.stock_mystery}').get_data(as_text=True)
    assert 'Mystery thing' in mystery and 'Unidentified' in mystery
    # a wish and a lot
    assert client.get(f'/collection/wishes/{w.wish_part}').status_code == 200
    lot = client.get(f'/collection/lots/{w.bag}')
    assert lot.status_code == 200 and 'Bag' in lot.get_data(as_text=True)
    # the old number URL and the jump search take either number
    moved = client.get('/collection/item/S/1000-1')
    assert moved.status_code == 301 and moved.headers['Location'].startswith(f'/collection/item/{w.keep}')
    assert client.get('/collection/item/S/no-such-set').status_code == 404
    found = client.get('/collection/jump?q=x999').json['results']
    assert [r['name'] for r in found] == ['Only on BrickLink']
    assert client.get('/collection/jump?q=1000-1').json['results'][0]['kind'] == 'set'
    # what is not on the 4.0 store yet still says so
    assert client.get('/workbench/orders').status_code == 503
    assert offline == []


def test_the_add_workflow_adds_checks_and_undoes_every_kind(tmp_path, monkeypatch, offline):
    """The Add journeys of docs/data-model-4.0/user-journey.md on a fixture pair, offline: a set (and BrickLink's list pending, settled
    through a fake transport), loose parts and a loose figure, a wish, an unknown number, and Undo of each."""
    from brickwork.core import drainer
    from brickwork.store4 import bricklink_api, jobs
    from tests.test_store4_bricklink_subsets import entry, reply
    path = make_pair(tmp_path, rich=True)
    with closing(connect(path)) as db:
        coll = Coll(db)
        sets, brick, red, figure = coll.item('sets', '1000-1'), coll.item('parts', '3001'), coll.colour('4'), coll.item('minifigs', 'fig-000004')
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', 'synthetic-password')
    client = logged_in(make_app(path, monkeypatch))
    client.get('/manage/add')
    with client.session_transaction() as session:
        csrf = session['bw_add_csrf']

    def add(text, kind, where='owned', **edits):
        proposal = client.post('/manage/add/review', json=dict(csrf_token=csrf, type=kind, where=where, mode='paste', text=text)).json
        for row in proposal['items']:
            row.update(edits)
        done = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=proposal['items']))
        assert done.status_code == 200, done.json
        return done.json

    def rows(sql, *args):
        with closing(connect(path, read_only=True)) as db:
            return [tuple(r) for r in db.execute(sql, args)]

    batches = [add('1000-1 x2', 'set', completeness='sealed'), add('3001 x4', 'part', 'loose', color_id=red, condition='new'),
               add('fig-000004', 'minifigure', 'loose'), add('1000-2', 'set', 'wishlist'), add('99999-9', 'set', decision='unidentified')]
    assert rows('SELECT count(*), sum(completeness=?) FROM copy WHERE archived_at IS NULL', 'sealed') == [(3, 2)]                       # two sealed copies of 1000-1 and the unidentified set's one
    assert rows('SELECT quantity FROM stock WHERE item_id=? AND color_id=? AND condition=?', brick, red, 'new') == [(4,)]
    assert rows('SELECT count(*) FROM stock_part WHERE stock_id=?', batches[2]['receipts'][0]['stock'])[0][0] > 0
    assert rows("SELECT count(*) FROM job WHERE kind='item'") == [(5,)]
    drainer.drain_once(path)
    assert rows("SELECT DISTINCT state FROM job") == [('done',)]
    assert rows("SELECT name FROM job_step WHERE state='done' AND error LIKE 'skipped%' GROUP BY name ORDER BY name") == [('market_price',), ('metadata',), ('pictures',)]
    # BrickLink's list for a new copy: pending, then settled when the fake transport answers
    for name in bricklink_api.KEY_ENVS:
        monkeypatch.setenv(name, 'x')
    with closing(connect(path)) as db:
        Coll(db).setting('prefer_bricklink_inventory', 'true')
    pending = add('1000-2', 'set', decision='another')['receipts'][0]
    assert rows('SELECT inventory_source, inventory_pending FROM copy WHERE id=?', pending['copies'][0]) == [('rebrickable', 'bricklink')]
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'bricklink', lambda url, headers: (200, reply(entry('3001', 5, 2))))
    drainer.drain_once(path)
    assert rows('SELECT inventory_source, inventory_pending FROM copy WHERE id=?', pending['copies'][0]) == [('bricklink', None)]
    # Undo takes everything back, last first
    for batch in reversed([*batches, {'batch': pending['batch']}]):
        assert client.post('/manage/add/undo', json=dict(csrf_token=csrf, batch=batch['batch'])).json == {'message': 'Undone'}
    assert rows('SELECT count(*) FROM copy WHERE archived_at IS NULL') == [(0,)]
    assert rows('SELECT count(*) FROM stock WHERE archived_at IS NULL') == [(0,)]
    assert rows('SELECT count(*) FROM wish WHERE archived_at IS NULL') == [(0,)]
    with closing(connect(path)) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == [] and db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert offline == []


def test_the_checker_and_the_collection_writes_check_edit_and_undo(tmp_path, monkeypatch, offline):
    """The check-set-parts and storage how-tos on a fixture pair, offline: check one copy's parts (missing, damaged-free, a figure, a spare),
    Undo, then edit a copy (storage, condition, flags), archive and restore, merge loose stock by an edit, and Undo each."""
    path = make_pair(tmp_path, rich=True)
    with closing(connect(path)) as db:
        w = build_world(Coll(db))
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', 'synthetic-password')
    client = logged_in(make_app(path, monkeypatch))
    client.get('/workbench/check-parts')
    with client.session_transaction() as session:
        csrf = session['bw_add_csrf']

    def rows(sql, *args):
        with closing(connect(path, read_only=True)) as db:
            return [tuple(r) for r in db.execute(sql, args)]

    # Check Set Parts: choose the copy, start, answer every step, say yes to the spare, finish as checked
    url = f'/workbench/check-parts/{w.copy_b}'
    assert client.get('/workbench/check-parts').status_code == 200 and 'Start a check' in client.get(url).get_data(as_text=True)
    assert client.post(url, data=dict(csrf_token=csrf, action='start', order='largest')).status_code == 302

    def send(**payload):
        reply = client.post(url, json=dict(csrf_token=csrf, operation=secrets.token_hex(8), **payload))
        assert reply.status_code == 200, reply.json
        return reply.json['state']
    state = json.loads(BeautifulSoup(client.get(url + '?run=1').get_data(as_text=True), 'html.parser').select_one('script[data-check-state]').text)
    session_id = state['session']['id']
    order = state['session']['order']
    tokens = {r['token']: r for r in state['rows']}
    assert [tokens[t]['kind'] for t in order] == ['part', 'part', 'figure']
    missing_token, found_token, figure_token = order
    send(action='answer', session=session_id, token=missing_token, found=tokens[missing_token]['quantity'] - 1)          # one missing
    send(action='answer', session=session_id, token=found_token, found=tokens[found_token]['quantity'])
    send(action='answer', session=session_id, token=figure_token, found=tokens[figure_token]['quantity'])
    assert send(action='spares', session=session_id, include=True)['session']['spares'] == 'yes'
    spare = next(r for r in state['rows'] if r['kind'] == 'spare')['token']
    send(action='answer', session=session_id, token=spare, found=0)                                                       # a missing spare is not a gap
    done = send(action='finish', session=session_id, checked=True)
    assert done['copy']['set_checked'] is True and done['session']['finished']
    assert rows('SELECT missing, checked FROM copy_part WHERE id=?', int(missing_token[2:])) == [(1, 1)]
    assert rows("SELECT count(*) FROM copy_flag cf JOIN flag f ON f.id=cf.flag_id WHERE cf.copy_id=? AND f.name='Set is checked'", w.copy_b) == [(1,)]
    assert rows('SELECT completeness FROM copy WHERE id=?', w.copy_b) == [('sealed',)]                                    # a manual value stays
    # Undo steps back through finish and the spare answer
    send(action='undo', session=session_id)
    send(action='undo', session=session_id)
    assert rows("SELECT count(*) FROM copy_flag WHERE copy_id=?", w.copy_b) == [(0,)]
    # the figure's own parts are a check of their own
    figure_line = rows('SELECT id FROM copy_figure WHERE copy_id=?', w.copy_b)[0][0]
    assert client.get(f'{url}/figure/{figure_line}').status_code == 200
    # the collection's writes: edit a copy (storage, condition, flags), see it, Undo
    saved = client.post('/collection/save/save', json=dict(csrf_token=csrf, entity='copy', ids=[w.copy_b], values=dict(storage_id=w.shelf, condition='used', flags=[w.tag], note='Checked')))
    assert saved.status_code == 200, saved.json
    assert rows('SELECT storage_id, condition, note FROM copy WHERE id=?', w.copy_b) == [(w.shelf, 'used', 'Checked')]
    page = client.get(f'/collection/item/{w.keep}?copy={w.copy_b}').get_data(as_text=True)
    assert 'Shelf A' in page and 'Used' in page
    assert client.post('/collection/save/undo', json=dict(csrf_token=csrf, event_id=saved.json['event_id'])).json['message'] == 'Undone'
    assert rows('SELECT storage_id, condition, note FROM copy WHERE id=?', w.copy_b) == [(None, 'new', None)]
    # archive and restore through the same receipt, then a stock edit that merges into another line, and Undo
    gone = client.post('/collection/save/archive', json=dict(csrf_token=csrf, entity='copy', ids=[w.copy_b], values={}))
    assert gone.json['message'] == 'Set deleted' and client.get(f'/workbench/check-parts/{w.copy_b}').status_code == 404
    assert client.post('/collection/save/undo', json=dict(csrf_token=csrf, event_id=gone.json['event_id'])).status_code == 200
    merged = client.post('/collection/save/save', json=dict(csrf_token=csrf, entity='stock', ids=[w.stock_brick_new], values=dict(condition='used', storage_id=w.shelf, lot_id=w.bag)))
    assert merged.json['message'] == 'Merged into existing stock'
    assert rows('SELECT quantity FROM stock WHERE id=?', w.stock_brick) == [(5,)] and rows('SELECT archived_at IS NOT NULL FROM stock WHERE id=?', w.stock_brick_new) == [(1,)]
    assert client.post('/collection/save/undo', json=dict(csrf_token=csrf, event_id=merged.json['event_id'])).status_code == 200
    assert rows('SELECT quantity FROM stock WHERE id=?', w.stock_brick) == [(3,)] and rows('SELECT archived_at IS NULL FROM stock WHERE id=?', w.stock_brick_new) == [(1,)]
    with closing(connect(path)) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == [] and db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert offline == []


def test_the_workbench_gives_takes_moves_and_undoes(tmp_path, monkeypatch, offline):
    """The pick-parts, match-stock-to-sets and storage how-tos on a fixture pair, offline: the Matcher offers loose stock for a gap, Give moves it
    into the copy, Take does the same from the item page, a booklet goes in as stock, a storage is made and things are moved into it; each is
    undone from its history list."""
    path = make_pair(tmp_path, rich=True)
    with closing(connect(path)) as db:
        w = build_world(Coll(db))
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', 'synthetic-password')
    client = logged_in(make_app(path, monkeypatch))
    client.get('/workbench/matcher')
    with client.session_transaction() as session:
        csrf = session['bw_add_csrf']

    def rows(sql, *args):
        with closing(connect(path, read_only=True)) as db:
            return [tuple(r) for r in db.execute(sql, args)]

    # Part Picker and Matcher show the gap of the world's first copy: one red 3001, and loose red 3001 to fill it
    assert 'Start picking' in client.get(f'/workbench/part-picker?copy={w.copy_a}').get_data(as_text=True)
    matcher = BeautifulSoup(client.get('/workbench/matcher').get_data(as_text=True), 'html.parser')
    form = matcher.select_one(f'[data-copy-id="{w.copy_a}"] form[data-action=transfer]')
    identity = json.loads(form['data-identity'])
    assert identity['target'] == 'part' and identity['copy_id'] == w.copy_a and 'Give 1' in form.get_text()
    # Give: the loose stock goes down, the missing count goes down, one receipt, one stock_transfer row
    gave = client.post('/workbench/save/transfer', json=dict(csrf_token=csrf, quantity=1, **identity))
    assert gave.status_code == 200, gave.json
    assert rows('SELECT missing FROM copy_part WHERE id=?', identity['target_id']) == [(0,)]
    assert rows('SELECT quantity FROM stock WHERE id=?', identity['source_id']) == [(identity['source_id'] == w.stock_brick and 2 or 1,)]
    assert rows('SELECT kind, copy_id, quantity, event_id FROM stock_transfer') == [('part', w.copy_a, 1, gave.json['event_id'])]
    assert 'transfer' in client.get('/workbench/matcher').get_data(as_text=True)                          # Recent saves
    assert client.post('/workbench/save/undo', json=dict(csrf_token=csrf, event_id=gave.json['event_id'])).json['message'] == 'Undone'
    assert rows('SELECT missing FROM copy_part WHERE id=?', identity['target_id']) == [(1,)]
    # Take from the copy's page: the card offers it, the save is one event, Undo is on the page
    page = BeautifulSoup(client.get(f'/collection/item/{w.keep}?copy={w.copy_a}').get_data(as_text=True), 'html.parser')
    box = page.select_one('.bc-missing-card [data-bc-take]')
    took = client.post('/collection/save/take', json=dict(csrf_token=csrf, quantity=1, **json.loads(box['data-identity'])))
    assert took.json['message'] == 'Took 1' and rows('SELECT missing FROM copy_part WHERE id=?', identity['target_id']) == [(0,)]
    assert client.post('/collection/save/undo', json=dict(csrf_token=csrf, event_id=took.json['event_id'])).json['message'] == 'Undone'
    assert rows('SELECT missing FROM copy_part WHERE id=?', identity['target_id']) == [(1,)]
    # the booklet the Matcher would give: the world has one, Give it to the first copy
    booklet = client.post('/workbench/save/transfer', json=dict(csrf_token=csrf, source_id=w.stock_booklet, copy_id=w.copy_a, target='instructions', target_id=w.copy_a, quantity=1))
    assert booklet.status_code == 200 and rows('SELECT quantity FROM stock WHERE id=?', w.stock_booklet) == [(0,)]
    assert client.post('/workbench/save/undo', json=dict(csrf_token=csrf, event_id=booklet.json['event_id'])).status_code == 200
    # Storage: make a drawer, move the copy into it, see it, Undo the move
    drawer = client.post('/workbench/storage/action/save', json=dict(csrf_token=csrf, name='Drawer 1', type='Drawer')).json
    moved = client.post('/workbench/storage/action/move', json=dict(csrf_token=csrf, storage_id=drawer['url'].rsplit('/', 1)[1], selections=[dict(entity='copy', id=w.copy_a)]))
    assert moved.status_code == 200 and rows('SELECT name FROM storage WHERE id=(SELECT storage_id FROM copy WHERE id=?)', w.copy_a) == [('Drawer 1',)]
    assert 'Syn Castle Keep' in client.get(drawer['url']).get_data(as_text=True)
    assert client.post('/workbench/storage/action/undo', json=dict(csrf_token=csrf, event_id=moved.json['event_id'])).json['message'] == 'Undone'
    assert rows('SELECT storage_id FROM copy WHERE id=?', w.copy_a) == [(w.shelf,)]
    # the printable missing-parts list names the gap
    printed = client.get(f'/lists/missing/print?copy={w.copy_a}').get_data(as_text=True)
    assert '3001' in printed and 'Red' in printed
    with closing(connect(path)) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == [] and db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert offline == []


def test_the_sources_fetch_pictures_prices_and_retail_and_a_fetched_set_makes_its_copies(tmp_path, monkeypatch, offline):
    """The sources piece on a fixture pair, with fake transports and invented keys: Add a set and the pipeline fetches its picture, its Brickset
    metadata and retail price and its BrickLink prices; the Prices screen and the item page show them; Fetch from Rebrickable makes the copies
    the Add row asked for once the job is done; Undo takes them back."""
    from brickwork.core import drainer, source_ops
    from brickwork.store4 import jobs
    from tests.sources4 import Pictures, Router, keyed, price_reply
    from tests.test_add_fetch_followup import Rebrickable as FakeRebrickable
    path = make_pair(tmp_path, rich=True)
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', 'synthetic-password')
    keyed(monkeypatch, 'bricklink', 'brickset', 'rebrickable')
    brickset = {'status': 'success', 'matches': 1, 'sets': [{
        'setID': 5001, 'number': '1000', 'numberVariant': 1, 'name': 'Syn Castle Keep', 'year': 1990, 'theme': 'Castle', 'pieces': 438,
        'LEGOCom': {'DE': {'retailPrice': 79.99, 'dateFirstAvailable': '1990-01-01T00:00:00Z', 'dateLastAvailable': '2030-12-31T00:00:00Z'}}}]}
    source_ops.register_handlers(http=Router({'/items/SET/1000-1/price': price_reply(average='12.5'), 'getSets': brickset}), image_http=Pictures())
    monkeypatch.setitem(jobs._DEFAULT_HTTP, 'rebrickable', FakeRebrickable())
    client = logged_in(make_app(path, monkeypatch))
    client.get('/manage/add')
    with client.session_transaction() as session:
        csrf = session['bw_add_csrf']

    def add(text, **edits):
        proposal = client.post('/manage/add/review', json=dict(csrf_token=csrf, type='set', where='owned', mode='paste', text=text)).json
        for row in proposal['items']:
            row.update(edits)
        done = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=proposal['items']))
        assert done.status_code == 200, done.json
        return done.json

    def rows(sql, *args):
        with closing(connect(path, read_only=True)) as db:
            return [tuple(r) for r in db.execute(sql, args)]

    added = add('1000-1', condition='used')
    drainer.drain_once(path)
    set_id = added['receipts'][0]['item_id']
    assert rows('SELECT state FROM job WHERE id=?', added['receipts'][0]['job_id']) == [('done',)]
    assert rows("SELECT name, state, source FROM job_step WHERE job_id=? AND name IN ('pictures', 'metadata', 'market_price') ORDER BY name", added['receipts'][0]['job_id']) == [
        ('market_price', 'done', 'bricklink'), ('metadata', 'done', 'brickset'), ('pictures', 'done', 'bricklink')]
    assert rows('SELECT source, kind FROM picture WHERE item_id=?', set_id) == [('bricklink', 'photo')]
    assert rows("SELECT condition, provider_key, price FROM price_observation WHERE item_id=? AND guide='sold' ORDER BY condition", set_id) == [
        ('new', 'S:1000-1', '12.5'), ('used', 'S:1000-1', '12.5')]
    assert rows("SELECT price, currency, region FROM price_observation WHERE item_id=? AND guide='retail'", set_id) == [('79.99', 'EUR', 'DE')]
    # the Prices screen and the item page show what was fetched
    prices = client.get('/planning/prices/records').get_json()
    record = dict(zip(prices['fields'], next(r for r in prices['rows'] if r[-1] == set_id)))
    assert record['price'] == '€12.50' and record['number'] == '1000-1' and record['owned'] and not record['price_stale']
    assert '€12.50' in json.dumps(client.get(f'/planning/prices/details?item_id={set_id}').get_json(), ensure_ascii=False)
    page = client.get(f'/collection/item/{set_id}').get_data(as_text=True)
    assert '€12.50' in page and 'Retail · DE' in page and '€79.99' in page and f'/manage/images/{rows("SELECT id FROM picture WHERE item_id=?", set_id)[0][0]}' in page
    # an unknown number fetched from Rebrickable: the job finishes, the copies the row asked for appear, and Undo takes them back
    fetched = add('99999-9', decision='fetch', quantity=2, condition='used')
    assert rows('SELECT count(*) FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=?', '99999-9') == [(0,)]
    drainer.drain_once(path)
    assert rows('SELECT count(*), min(inventory_source) FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=? AND c.archived_at IS NULL', '99999-9') == [(2, 'rebrickable_api')]
    assert client.get(f'/manage/add/jobs/{fetched["receipts"][0]["fetch_job"]}').json['events'][-1]['message'] == 'Fetched · 2 copies added'
    assert client.post('/manage/add/undo', json=dict(csrf_token=csrf, batch=fetched['batch'])).json == {'message': 'Undone'}
    assert rows('SELECT count(*) FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key=? AND c.archived_at IS NULL', '99999-9') == [(0,)]
    with closing(connect(path)) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == [] and db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert offline == []


def test_planning_ranks_pins_exports_and_the_wishlists_move_export_and_undo(tmp_path, monkeypatch, offline):
    """The planning how-tos on a fixture pair, offline: Complete sets ranks a copy with a gap from cached prices, a pin and the repair settings are
    saved and undone, the repair list exports as BrickLink XML and the items without a number are named; the Wishlist moves, copies and exports
    its wishes in both formats and every change is undone; a manual price is recorded and voided; the item page shows the part-out value."""
    from brickwork.core import currency, manual_prices
    from brickwork.core.sources.base import now
    path = make_pair(tmp_path, rich=True)
    with closing(connect(path)) as db:
        w = build_world(Coll(db))
        coll = Coll(db)
        for key, value in dict(bricklink_region='eu', bricklink_currency='EUR', incomplete_discount_pct='30', repair_shipping='3', repair_fees='0.5',
                               repair_min_order='10', repair_use_loose_stock='0').items():
            coll.setting(key, value)
        coll.sql('DELETE FROM price_current')
        for item, value, colour in ((w.keep, '100', None), (w.brick, '2', w.red)):
            coll.price(item, value, colour=colour, region='eu', currency='EUR', observed=now().isoformat(), sold=10, qty=10)
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', 'synthetic-password')
    client = logged_in(make_app(path, monkeypatch))
    client.get('/planning/complete-sets')
    with client.session_transaction() as session:
        csrf = session['bw_add_csrf']

    def rows(sql, *args):
        with closing(connect(path, read_only=True)) as db:
            return [tuple(r) for r in db.execute(sql, args)]

    def post(url, **data):
        return client.post(url, json=dict(csrf_token=csrf, **data))
    # Complete sets: copy A (a red 3001 missing) is ranked from the cached quotes; B and C have no gap
    page = BeautifulSoup(client.get('/planning/complete-sets').get_data(as_text=True), 'html.parser')
    ranked = [json.loads(r['data-record']) for r in page.select('[data-bp-row]')]
    assert [(r['id'], r['group'], r['rank']) for r in ranked] == [(w.copy_a, 'ranked', 1)]
    assert page.h1.get_text(strip=True).startswith('Repair 1000-1 first')
    # pin it, change the repair settings, undo both
    pinned = post('/planning/action/pin', id=w.copy_a, pinned=True)
    assert pinned.status_code == 200 and rows('SELECT pinned FROM copy WHERE id=?', w.copy_a) == [(1,)]
    settings = post('/planning/action/settings', values=dict(repair_shipping='5', repair_fees='1', repair_min_order='0', repair_use_loose_stock='1', incomplete_discount_pct='20'))
    assert settings.status_code == 200 and rows("SELECT value FROM setting WHERE key='repair_shipping'") == [('5',)]
    assert post('/planning/action/undo', event_id=pinned.json['event_id']).json['message'] == 'Undone'
    assert post('/planning/action/undo', event_id=settings.json['event_id']).json['message'] == 'Undone'
    assert rows('SELECT pinned FROM copy WHERE id=?', w.copy_a) == [(0,)] and rows("SELECT value FROM setting WHERE key='repair_shipping'") == [('3',)]
    # Export the gaps: BrickLink XML of the selected copy, an item with no number is named in the summary
    exported = post('/planning/action/export', ids=[w.copy_a], summary=True).json
    assert exported['summary'] == dict(exported=1, skipped=[]) and '<ITEMID>3001</ITEMID>' in exported['content']
    assert post('/planning/action/export', ids=['no-such-copy']).status_code == 400
    # the item page of the copy shows the part-out value once every line has a price: here it asks for the part prices
    item_page = client.get(f'/collection/item/{w.keep}?copy={w.copy_a}').get_data(as_text=True)
    assert 'Not enough prices yet' in item_page
    # a manual price is recorded as source manual and voided by Undo
    with closing(connect(path)) as db:
        ids = manual_prices.record(db, [dict(item_id=w.gate, guide='manual', price='33.50', currency='EUR', condition='used')])
        event = db.execute("SELECT id FROM event WHERE entity_kind='manual_prices' AND field='receipt'").fetchone()[0]
    assert rows('SELECT source, price FROM price_current c JOIN price_observation o ON o.id=c.observation_id WHERE c.item_id=?', w.gate) == [('manual', '33.50')]
    with closing(connect(path)) as db:
        manual_prices.undo(db, event)
    assert rows('SELECT count(*) FROM price_current WHERE item_id=?', w.gate) == [(0,)] and rows('SELECT voided_at IS NOT NULL FROM price_observation WHERE id=?', ids[0]) == [(1,)]
    # exchange rates: a hand-entered rate converts a max in another currency, shown marked
    with closing(connect(path)) as db:
        currency.set_rate(db, 'USD', '1.17')
        db.execute("UPDATE wish SET max_price='5.00', max_price_currency='USD' WHERE id=?", (w.wish_set,))
        db.commit()
        coll = Coll(db)
        coll.price(w.gate, '4.00', region='eu', currency='EUR', observed=now().isoformat())
    wishlist = BeautifulSoup(client.get('/planning/wishlist').get_data(as_text=True), 'html.parser')
    gate_row = next(r for r in wishlist.select('[data-bp-row]') if json.loads(r['data-record'])['id'] == w.wish_set)
    assert 'Price ≈ $4.68 at 1.17' in gate_row.get_text(' ') and json.loads(gate_row['data-record'])['under'] == 'under'
    # Wishlist: a new list, move one wish, copy the other, export both ways, undo everything
    made = post('/planning/wishlists/save', values=dict(name='Gifts', bricklink_id='555'))
    target = rows("SELECT id FROM wishlist WHERE name='Gifts'")[0][0]
    moved = post('/planning/wishlists/transfer', ids=[w.wish_part], list_id=target)
    copied = post('/planning/wishlists/transfer', ids=[w.wish_set], list_id=target, copy=True)
    assert moved.status_code == copied.status_code == 200 and rows('SELECT count(*) FROM wish WHERE wishlist_id=? AND archived_at IS NULL', target) == [(2,)]
    xml = client.get(f'/planning/wishlists/{target}/export.xml?summary=true').json
    assert xml['summary']['exported'] == 2 and '<WANTEDLISTID>555</WANTEDLISTID>' in xml['content']
    parts = client.get(f'/planning/wishlists/all/export.csv?summary=true&kind=parts').json
    assert parts['content'].splitlines() == ['Part,Color,Quantity', '3023,15,2'] and parts['summary']['exported'] == 1
    for event_id in (copied.json['event_id'], moved.json['event_id'], made.json['event_id']):
        assert post('/planning/wishlists/undo', event_id=event_id).status_code == 200
    assert rows('SELECT wishlist_id FROM wish WHERE id=?', w.wish_part) == [('default',)] and rows("SELECT count(*) FROM wishlist WHERE archived_at IS NULL") == [(1,)]
    with closing(connect(path)) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == [] and db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert offline == []
