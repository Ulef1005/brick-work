"""Browser entry, read-only and Node tick selection, without a provider or network."""
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup
from tests import rendered
from tests.app4 import app4, client, coll, csrf, pair, world  # noqa: F401
from brickwork.core import instructions as ins, instruction_sources as src
from brickwork.core.pipeline import Pipeline
from brickwork.core.transaction import transaction
from tests.instruction_fakes import registry


def test_tick_list_runtime():
    result = subprocess.run([rendered.need_node(), 'tests/toni_bw_instructions_runtime.cjs'], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_entry_and_no_source(client, world):
    page = BeautifulSoup(client.get('/manage/instructions').data, 'html.parser')
    assert page.find('a', string='Find instructions')['href'] == '/manage/instructions/find'
    assert 'Fetch missing' not in page.get_text()
    page = BeautifulSoup(client.get('/manage/instructions/find').data, 'html.parser')
    assert page.select_one('.bw-find h1').text == 'Find instructions'          # #484: the screen links out; the download flow's steps and ticks are gone
    assert not page.select('[data-if-download], .if-steps, [data-if-groups]')
    page = BeautifulSoup(client.get(f'/collection/item/{world.keep}').data, 'html.parser')
    assert page.find('a', string='Find instructions')['href'].endswith(f'item={world.keep}')


def test_read_only_has_no_actions_and_refuses_posts(client, monkeypatch):
    monkeypatch.setenv('BW_READ_ONLY', '1')
    page = BeautifulSoup(client.get('/manage/instructions/find').data, 'html.parser')
    assert not page.select('.bw-find-upload, input[type=checkbox]')           # a read-only instance offers the links, not the upload
    assert client.post('/manage/instructions/find', json={}).status_code == 403


def test_browser_find_poll_and_download_requires_ticks(client, coll, world, monkeypatch):
    reg, fake = registry()
    monkeypatch.setattr(src, 'registry', reg)
    token = csrf(client)
    response = client.post('/manage/instructions/find', json=dict(csrf_token=token, item_ids=[world.keep], region='AT'))
    assert response.status_code == 202
    jobs = response.json['jobs']
    for job in jobs: Pipeline(coll.db).run(job)
    status = client.get('/manage/instructions/find/status?jobs='+','.join(map(str,jobs))).json
    files = status['groups'][0]['candidates']
    assert len(files) == 2 and fake.calls == []
    assert client.post('/manage/instructions/find', json=dict(csrf_token=token, action='download', candidate_ids=[])).status_code == 400
    response = client.post('/manage/instructions/find', json=dict(csrf_token=token, action='download', candidate_ids=[files[0]['id']]))
    assert response.status_code == 202 and len(fake.calls) == 0
    assert client.get('/manage/instructions/find/status?download='+str(response.json['download'])).json['download']['state'] == 'queued'


def test_choose_sets_preserves_pasted_order(client, coll, world):
    token = csrf(client)
    response = client.post('/manage/instructions/find', json=dict(csrf_token=token, mode='numbers', numbers='1000-2, 1000-1, 1000-2'))
    assert response.status_code == 202
    groups = ins.candidates(coll.db, response.json['jobs'])
    assert [g['born_key'] for g in groups] == ['1000-2','1000-1']


def test_all_missing_caps_queue_and_reports_total(client, coll):
    for n in range(51):
        item = coll.local('set', f'No files {n}')
        coll.db.execute("INSERT INTO copy(id,item_id,inventory_source,condition,created_at,updated_at) VALUES(?,?,'none','used',?,?)", (f'missing-{n}', item, '2026-01-01', '2026-01-01'))
    coll.db.commit()
    response = client.post('/manage/instructions/find', json=dict(csrf_token=csrf(client)))
    assert response.status_code == 202
    assert len(response.json['jobs']) == 50
    assert response.json['message'] == '50 of 51 sets queued, run it again for the rest (1 remaining)'


def test_unknown_find_item_is_bad_request(client):
    response = client.post('/manage/instructions/find', json=dict(csrf_token=csrf(client), item_ids=[999999999]))
    assert response.status_code == 400


def test_add_disabled_when_official_has_no_renderer(client):
    page = BeautifulSoup(client.get('/manage/add').data, 'html.parser')
    assert page.select_one('[data-find-instructions]').has_attr('disabled')
    assert 'Official needs a page renderer: not set up' in page.get_text()


def test_added_discovery_reports_renderer_notice(client, coll, world):
    from brickwork.core import admin
    with transaction(coll.db):
        job = ins.queue_find(coll.db, [world.keep])[0]
        admin.audit(coll.db, 'add:renderer-test', 'receipt', new={'instruction_jobs': [job]})
    Pipeline(coll.db).run(job)
    response = client.get('/manage/instructions/find/added?batch=renderer-test')
    assert response.json['message'] == 'Official needs a page renderer: not set up'


def test_booklet_detail_links_to_set(client, coll, world):
    booklet = coll.local('instructions', 'Booklet', born_key='1000-1')
    page = BeautifulSoup(client.get(f'/collection/item/{booklet}').data, 'html.parser')
    assert page.find('a', string='Find instructions')['href'].endswith(f'item={world.keep}')
