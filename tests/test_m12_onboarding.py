"""M.12 (issue #114): onboarding step 1 (design 6.1), from an empty data folder to a set whose parts can be checked, with no key anywhere.

The Rebrickable dump is the fixture dump behind `catalogue_jobs.FETCH`; nothing leaves the machine."""
from contextlib import closing
import json
import os
import time

from bs4 import BeautifulSoup
from flask import Flask
import pytest

from brickwork.app import setup_app
from brickwork.core.connect import connect
from brickwork.store4 import cli
from brickwork.store4.errors import Store4Error
from brickwork.web import catalogue_jobs
from tests.sources4 import unkeyed
from tests.store4_mint_fixtures import build_catalogue
from tests.web_fixtures import ROOT, logged_in

PASSWORD = 'synthetic-password'


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """An empty data folder (`data/`) and the app on it: no collection file, no catalogue, no key. Returns (client, data folder, fetch log)."""
    unkeyed(monkeypatch)
    for key in list(os.environ):
        if key.startswith('BW_') and key not in ('BW_SECRET_KEY',):
            monkeypatch.delenv(key)
    (tmp_path / 'build').mkdir()
    build_catalogue(tmp_path / 'build')
    files = {p.name: p.read_bytes() for p in (tmp_path / 'build' / 'dump').glob('*.csv.gz')}
    fetched = []

    def fetch(url):
        fetched.append(url)
        return files[url.rsplit('/', 1)[1]], 'Mon, 26 Oct 2026 08:00:00 GMT'
    monkeypatch.setattr(catalogue_jobs, 'FETCH', fetch)
    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setenv('BW_DB_PATH', str(data / 'brickwork.db'))
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', PASSWORD)
    app = Flask('m12', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config.update(TESTING=True, SECRET_KEY='synthetic-session')
    return logged_in(app), data, fetched


def soup(client, route):
    response = client.get(route)
    assert response.status_code == 200, (route, response.status_code)
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def token(client):
    client.get('/collection/sets')
    with client.session_transaction() as session:
        return session['bw_add_csrf']


def wait(paths):
    for _ in range(400):
        state = catalogue_jobs.read(paths)
        if state and state['state'] != 'running':
            return state
        time.sleep(0.05)
    raise AssertionError('the job did not finish')


def step(page, number):
    return page.select_one(f'[data-first-run] .fr-step[data-step="{number}"]')


def test_a_fresh_install_reaches_a_checkable_set_with_no_key(fresh):
    client, data, fetched = fresh
    paths = cli.Paths(data)
    assert list(data.glob('*.db')) == []
    page = soup(client, '/collection/sets')                                   # step 1: no file at all, and the button is there with no key set
    keys, load = step(page, 1), step(page, 2)
    assert keys['data-state'] == 'optional' and load['data-state'] == 'current' and step(page, 3)['data-state'] == 'waiting'
    button = load.find('button')
    assert button.get_text(strip=True) == 'Download the catalogue' and not button.has_attr('disabled')
    assert 'at most one download a day' in load.get_text()
    started = client.post('/manage/first-run/catalogue', data={'csrf_token': token(client), 'action': 'first'})
    assert started.status_code == 302 and started.location.endswith('/collection/sets')
    state = wait(paths)
    assert state['state'] == 'done' and state['kind'] == 'first', state
    assert len(fetched) == 12 and {p.name for p in data.glob('*.db')} == {'brickwork.db', 'catalogue.db'}
    with closing(connect(data / 'brickwork.db', read_only=True)) as db:        # activated and bound, the collection seeded as `setup` seeds it
        assert db.execute('SELECT count(*) FROM main.catalogue_build').fetchone()[0] == 1
        assert db.execute("SELECT value FROM main.meta WHERE key='catalogue_id'").fetchone() is not None
        assert db.execute("SELECT count(*) FROM main.flag WHERE system=1").fetchone()[0] == 3
    page = soup(client, '/collection/sets')                                   # step 2 done, adding opens
    assert step(page, 2)['data-state'] == 'done' and step(page, 3)['data-state'] == 'current'
    csrf = token(client)                                                       # add a set by number, as the Add page does
    review = client.post('/manage/add/review', json=dict(csrf_token=csrf, type='set', where='owned', mode='paste', text='2070-1'))
    assert review.status_code == 200, review.get_data(as_text=True)
    proposal = review.get_json()
    assert not proposal['unresolved'] and proposal['items'][0]['number'] == '2070-1'
    done = client.post('/manage/add/confirm', json=dict(csrf_token=csrf, token=proposal['token'], items=proposal['items']))
    assert done.status_code == 200, done.get_data(as_text=True)
    chooser = soup(client, '/workbench/check-parts')                           # Check Set Parts lists it; the parts are there
    row = chooser.select_one('#bw-check-choices [data-list-row]')
    assert row['data-number'] == '2070-1' and row['href'].startswith('/workbench/check-parts/')
    started = client.post(row['href'], data={'csrf_token': csrf, 'action': 'start'})
    assert started.status_code == 302
    state = json.loads(soup(client, row['href'] + '?run=1').select_one('script[data-check-state]').text)
    assert state['rows']
    assert len(fetched) == 12                                                  # nothing else was fetched


def test_todays_files_on_disk_are_offered_and_not_fetched_again(fresh):
    client, data, fetched = fresh
    paths = cli.Paths(data)
    assert catalogue_jobs.start(paths, 'first', background=False)['state'] == 'done'
    assert len(fetched) == 12
    (data / 'catalogue.db').unlink()                                           # the catalogue is lost, today's files are not
    page = soup(client, '/collection/sets')
    assert step(page, 2).find('button').get_text(strip=True) == "Build from today's files"
    client.post('/manage/first-run/catalogue', data={'csrf_token': token(client), 'action': 'first'})
    state = wait(paths)
    assert state['state'] == 'done' and state['result']['download']['downloaded'] is False and len(fetched) == 12
    assert (data / 'catalogue.db').is_file()


def test_a_catalogue_file_that_is_not_active_is_activated_by_the_button(fresh):
    client, data, fetched = fresh
    paths = cli.Paths(data)
    assert catalogue_jobs.start(paths, 'first', background=False)['state'] == 'done'
    for part in data.glob('brickwork.db*'):                                     # a catalogue file beside a collection that never activated it (`brickwork setup` after a copy)
        part.unlink()
    from brickwork.core import admin
    admin.ensure_collection(data / 'brickwork.db')
    page = soup(client, '/collection/sets')
    assert step(page, 2)['data-state'] == 'current' and step(page, 2).find('button').get_text(strip=True) == 'Activate the catalogue'
    client.post('/manage/first-run/catalogue', data={'csrf_token': token(client), 'action': 'activate'})
    assert wait(paths)['state'] == 'done'
    assert step(soup(client, '/collection/sets'), 2)['data-state'] == 'done'


def test_a_failed_download_is_shown_with_the_button_to_try_again_and_a_catalogue_refuses_a_first_import(fresh, monkeypatch):
    client, data, fetched = fresh
    paths = cli.Paths(data)
    monkeypatch.setattr(catalogue_jobs, 'FETCH', lambda url: (_ for _ in ()).throw(OSError('network is down')))
    client.post('/manage/first-run/catalogue', data={'csrf_token': token(client), 'action': 'first'})
    assert wait(paths)['state'] == 'failed'
    page = soup(client, '/collection/sets')
    assert 'download' in page.select_one('[data-job-failed]').get_text().lower() and step(page, 2).find('button')   # the error, and the button to try again
    assert not (data / 'catalogue.db').exists()
    (data / 'catalogue.db').write_bytes(b'x')
    with pytest.raises(Store4Error, match='Re-download'):
        catalogue_jobs.start(paths, 'first')


def test_the_route_needs_the_csrf_token_and_a_known_action(fresh):
    client, data, fetched = fresh
    assert client.post('/manage/first-run/catalogue', data={'action': 'first'}).status_code == 400
    assert client.post('/manage/first-run/catalogue', data={'csrf_token': token(client), 'action': 'nope'}).status_code == 400
    assert fetched == [] and catalogue_jobs.read(cli.Paths(data)) is None
