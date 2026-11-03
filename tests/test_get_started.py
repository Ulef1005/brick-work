"""#83: the first-run flow as one resumable flow: its own page, the steps' states, skipping a step for now and taking it back, resuming at the
first open step, and reopening it from Tools & Admin."""
from bs4 import BeautifulSoup
import pytest

from brickwork.web import onboarding
from tests.app4 import app4, client, coll, csrf, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import unkeyed


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    unkeyed(monkeypatch)


def soup(client, route='/manage/get-started'):
    response = client.get(route)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def states(page):
    return {li['data-key']: li['data-state'] for li in page.select('[data-first-run] .fr-step')}


def skip(client, step, action='skip', back='flow'):
    return client.post('/manage/get-started', data=dict(csrf_token=csrf(client), step=step, action=action, back=back))


def test_the_page_lists_the_steps_in_order_and_marks_where_the_flow_resumes(client):
    page = soup(client)
    assert page.h1.get_text() == 'Get started'
    assert [li['data-key'] for li in page.select('.fr-step')] == list(onboarding.STEPS) == ['catalogue', 'keys', 'collection']
    assert states(page) == dict(catalogue='done', keys='current', collection='open')         # the fixture pair has its catalogue active
    assert page.select_one('[aria-current=step]')['data-key'] == 'keys'
    assert page.select_one('[data-fr-count]').get_text() == '1 of 3 steps done'
    assert page.select_one('#fr-title').get_text() == 'Pick up where you left off.'


def test_skipping_a_step_moves_the_flow_on_and_taking_it_back_restores_it(client, pair):
    response = skip(client, 'keys')
    assert response.status_code == 302 and response.location.endswith('/manage/get-started')
    page = soup(client)
    assert states(page) == dict(catalogue='done', keys='skipped', collection='current')        # left and come back: resumes at the first open step
    keys = page.select_one('[data-key=keys]')
    assert 'Skipped for now.' in keys.get_text() and keys.select_one('.fr-actions a')['href'] == '/manage/catalogues'      # it can still be done
    assert keys.select_one('.fr-skip').get_text() == 'Back into the flow'
    assert (pair.parent / 'onboarding.json').read_text() == '{"skipped": ["keys"]}'
    skip(client, 'keys', 'unskip')
    assert states(soup(client))['keys'] == 'current'


def test_the_sets_page_skip_comes_back_to_the_sets_page(client, monkeypatch):
    monkeypatch.setattr('brickwork.web.setup_state.catalogue_loaded', lambda: False)
    assert skip(client, 'catalogue', back='sets').location.endswith('/collection/sets')
    page = soup(client, '/collection/sets')
    assert states(page) == dict(catalogue='skipped', keys='current', collection='waiting')     # skipping the catalogue does not open step 3


def test_a_collection_with_copies_has_done_step_3_and_skipped_steps_finish_the_flow(client, world):
    assert states(soup(client))['collection'] == 'done'
    skip(client, 'keys')
    page = soup(client)
    assert states(page) == dict(catalogue='done', keys='skipped', collection='done')
    assert not page.select('[aria-current=step]')


def test_every_step_done_says_so(client, world, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', 'synthetic-key-for-the-state-only')
    page = soup(client)
    assert set(states(page).values()) == {'done'} and page.select_one('#fr-title').get_text() == 'All set.'
    assert not page.select('.fr-skip')


@pytest.mark.parametrize('data', [dict(step='keys', action='hide'), dict(step='guide', action='skip'), dict(action='skip')])
def test_an_unknown_step_or_action_is_refused(client, data):
    assert client.post('/manage/get-started', data=dict(csrf_token=csrf(client), **data)).status_code == 400


def test_a_skip_needs_the_csrf_token_and_changes_switched_on(client, monkeypatch):
    assert client.post('/manage/get-started', data=dict(step='keys', action='skip')).status_code == 400
    token = csrf(client)
    monkeypatch.setenv('BW_READ_ONLY', '1')
    assert client.post('/manage/get-started', data=dict(csrf_token=token, step='keys', action='skip')).status_code == 403
    page = soup(client)
    assert not page.select('.fr-skip') and 'Read only' in page.select_one('.bc-status').get_text()


def test_an_unreadable_or_foreign_file_counts_as_nothing_skipped(client, pair):
    for text in ('not json', '["keys"]', '{"skipped": "keys"}', '{"skipped": ["guide", "keys"]}'):
        (pair.parent / 'onboarding.json').write_text(text)
        assert states(soup(client))['keys'] == ('skipped' if text.endswith('"keys"]}') else 'current'), text


def test_tools_and_admin_reopens_the_flow_with_its_progress(client):
    hub = soup(client, '/manage/tools')
    row = hub.find('a', href='/manage/get-started')
    assert row and 'Get started' in row.get_text() and '1 of 3 done' in row.get_text()


# #85: the catalogue step: what it is, its progress while it runs (also after leaving the page), its done state.

def test_the_catalogue_step_says_what_the_catalogue_holds_and_when_it_is_done_what_is_active(client):
    step = soup(client).select_one('[data-key=catalogue]')
    summary = step.select_one('[data-catalogue-summary]')
    assert ' items and ' in summary.get_text() and ' colours' in summary.get_text()
    assert summary.find('a')['href'] == '/manage/catalogue'
    explainer = step.select_one('details[data-catalogue-explainer]')
    assert explainer.summary.get_text() == 'What the catalogue is' and not explainer.has_attr('open')
    assert [li.strong.get_text() for li in explainer.select('li')] == ['What it holds.', 'Brick Work ids.', 'What comes later.']


def test_before_the_catalogue_the_step_explains_it_and_has_no_summary(client, monkeypatch):
    monkeypatch.setattr('brickwork.web.setup_state.catalogue_loaded', lambda: False)
    step = soup(client, '/collection/sets').select_one('[data-key=catalogue]')
    assert step.select_one('[data-catalogue-explainer]') and not step.select('[data-catalogue-summary]')


@pytest.mark.parametrize('state', ['running', 'failed'])
def test_coming_back_shows_a_running_job_with_its_progress_and_a_failed_one_with_its_retry(client, monkeypatch, state):
    job = dict(kind='first', state=state, step=1, steps=['Download', 'Build', 'Activate'], label='First import', error='The download failed.')
    monkeypatch.setattr('brickwork.web.setup_state.catalogue_loaded', lambda: False)
    monkeypatch.setattr('brickwork.web.catalogue_jobs.read', lambda paths: job)
    step = soup(client).select_one('[data-key=catalogue]')
    if state == 'running':
        assert step.select_one('[data-catalogue-job] [role=progressbar]')['aria-valuenow'] == '33'
        assert not step.select('.fr-actions form')
    else:
        assert step.select_one('[data-job-failed]').get_text() == 'The download failed.'
        assert step.select_one('.fr-actions form')['action'] == '/manage/first-run/catalogue'
