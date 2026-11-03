"""#83: the first-run flow as one resumable flow: its own page, the steps' states, skipping a step for now and taking it back, resuming at the
first open step, and reopening it from Tools & Admin."""
import secrets as token_source

from bs4 import BeautifulSoup
import pytest

from brickwork.web import onboarding
from tests.app4 import app4, client, coll, csrf, pair, world  # noqa: F401 (fixtures)
from tests.sources4 import unkeyed


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    from cryptography.fernet import Fernet
    from brickwork.core import secrets
    unkeyed(monkeypatch)
    monkeypatch.setenv('BW_SECRET_KEY', Fernet.generate_key().decode())       # key entry on, as on a set-up install
    secrets.forget()


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
    assert [li['data-key'] for li in page.select('.fr-step')] == list(onboarding.STEPS) == ['catalogue', 'keys', 'collection', 'guide']
    assert states(page) == dict(catalogue='done', keys='current', collection='open', guide='open')      # the fixture pair has its catalogue active
    assert page.select_one('[aria-current=step]')['data-key'] == 'keys'
    assert page.select_one('[data-fr-count]').get_text() == '1 of 4 steps done'
    assert page.select_one('#fr-title').get_text() == 'Pick up where you left off.'


def test_skipping_a_step_moves_the_flow_on_and_taking_it_back_restores_it(client, pair):
    response = skip(client, 'keys')
    assert response.status_code == 302 and response.location.endswith('/manage/get-started')
    page = soup(client)
    assert states(page) == dict(catalogue='done', keys='skipped', collection='current', guide='open')      # left and come back: resumes at the first open step
    keys = page.select_one('[data-key=keys]')
    assert 'Skipped for now.' in keys.get_text() and keys.select('[data-flow-keys] [data-key-card]')      # it can still be done
    assert keys.select_one('.fr-skip').get_text() == 'Back into the flow'
    assert (pair.parent / 'onboarding.json').read_text() == '{"skipped": ["keys"]}'
    skip(client, 'keys', 'unskip')
    assert states(soup(client))['keys'] == 'current'


def test_the_sets_page_skip_comes_back_to_the_sets_page(client, monkeypatch):
    monkeypatch.setattr('brickwork.web.setup_state.catalogue_loaded', lambda: False)
    assert skip(client, 'catalogue', back='sets').location.endswith('/collection/sets')
    page = soup(client, '/collection/sets')
    assert states(page) == dict(catalogue='skipped', keys='current', collection='waiting', guide='open')      # skipping the catalogue does not open step 3


def test_a_collection_with_copies_has_done_step_3_and_skipped_steps_finish_the_flow(client, world):
    assert states(soup(client))['collection'] == 'done'
    skip(client, 'keys')
    skip(client, 'guide')
    page = soup(client)
    assert states(page) == dict(catalogue='done', keys='skipped', collection='done', guide='skipped')
    assert not page.select('[aria-current=step]')


def test_every_step_done_says_so(client, world, monkeypatch):
    monkeypatch.setenv('BW_REBRICKABLE_API_KEY', token_source.token_hex(14))
    client.post('/manage/get-started', data=dict(csrf_token=csrf(client), step='guide', action='read'))
    page = soup(client)
    assert set(states(page).values()) == {'done'} and page.select_one('#fr-title').get_text() == 'All set.'
    assert not page.select('.fr-skip')


@pytest.mark.parametrize('data', [dict(step='keys', action='hide'), dict(step='nope', action='skip'), dict(action='skip'), dict(step='keys', action='read')])
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
    for text in ('not json', '["keys"]', '{"skipped": "keys"}', '{"skipped": ["nope", "keys"]}'):
        (pair.parent / 'onboarding.json').write_text(text)
        assert states(soup(client))['keys'] == ('skipped' if text.endswith('"keys"]}') else 'current'), text


def test_tools_and_admin_reopens_the_flow_with_its_progress(client):
    hub = soup(client, '/manage/tools')
    row = hub.find('a', href='/manage/get-started')
    assert row and 'Get started' in row.get_text() and '1 of 4 done' in row.get_text()


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


# #84: the keys step: one card per source with what it gives and where the key is made, Test, the honest note without keys, and every
# key action coming back to the flow.

def test_the_keys_step_has_a_card_per_source_with_what_it_gives_and_where_to_get_it(client):
    step = soup(client).select_one('[data-key=keys]')
    cards = {c['data-key-card']: c for c in step.select('[data-flow-keys] [data-key-card]')}
    assert set(cards) == set(onboarding.KEY_HELP)
    for source, card in cards.items():
        link = card.select_one('[data-key-help] a')
        assert link['href'] == onboarding.KEY_HELP[source]['url'] and link['href'].startswith('https://') and link['rel'] == ['noopener']
        assert card.select_one('[data-key-pill]').get_text(strip=True) == 'Not set'
    assert 'Without keys there are no prices' in step.select_one('[data-without-keys]').get_text()
    assert not step.select('.fr-actions a')                                   # the cards are the action here
    for form in step.select('[data-flow-keys] form'):
        assert form['action'] == '/manage/catalogues' and form.select_one('input[name=back]')['value'] == 'flow'


def test_a_stored_key_shows_configured_with_test_and_the_step_done(client, coll):
    from brickwork.core import keys
    value = token_source.token_hex(14)                                        # made per run: no key-shaped literal in the repo
    keys.save(coll.db, 'rebrickable', {'key': value})
    step = soup(client).select_one('[data-key=keys]')
    assert step['data-state'] == 'done' and not step.select('[data-without-keys]')
    card = step.select_one('[data-key-card=rebrickable]')
    assert card.select_one('[data-key-pill]').get_text(strip=True) == 'Configured'
    assert card.find('button', string='Test key')
    assert value not in str(step)


def test_a_rejected_key_comes_back_to_the_flow_with_the_sites_reason(client, monkeypatch):
    from brickwork.core.sources.base import KeyRejected
    def refuse(action, **kwargs):
        raise KeyRejected('Rebrickable says: invalid key')
    monkeypatch.setattr('brickwork.web.admin_ops.tools_write', refuse)
    value = token_source.token_hex(14)
    response = client.post('/manage/catalogues', data={'csrf_token': csrf(client), 'action': 'key_test_save', 'source': 'rebrickable',
                                                       'key:key': value, 'back': 'flow'})
    assert response.status_code == 302 and response.location.endswith('/manage/get-started#key-rebrickable')
    card = soup(client).select_one('[data-flow-keys] [data-key-card=rebrickable]')
    assert card.select_one('[data-key-pill]').get_text(strip=True) == 'Rejected'
    assert 'invalid key' in card.select_one('[role=alert]').get_text()
    assert value not in client.get('/manage/get-started').get_data(as_text=True)


def test_without_the_flow_marker_a_key_action_stays_on_catalogues_and_keys(client, monkeypatch):
    monkeypatch.setattr('brickwork.web.admin_ops.tools_write', lambda action, **kwargs: dict(tested=True))
    response = client.post('/manage/catalogues', data={'csrf_token': csrf(client), 'action': 'key_test_save', 'source': 'rebrickable',
                                                       'key:key': token_source.token_hex(14)})
    assert response.location.endswith('/manage/catalogues')


# #86: step 3's choice screen: every source runs its existing path or says plainly what is not available; the pages it opens offer the
# way back; the summary counts what came in and links the copies to finish.

def test_the_choice_screen_offers_every_source_with_its_path(client):
    page = soup(client, '/manage/get-started/collection')
    assert page.h1.get_text() == 'Bring your collection in'
    choices = {c['data-choice']: c for c in page.select('[data-collection-choices] [data-choice]')}
    assert list(choices) == ['rebrickable', 'brickset', 'bricklink', 'bricktracker', 'file', 'hand']
    assert {k: c.find('a', class_='fr-btn')['href'] for k, c in choices.items()} == {
        'rebrickable': '/manage/sync', 'brickset': '/manage/sync', 'bricklink': '/manage/add?mode=file',
        'bricktracker': '/manage/import-legacy', 'file': '/manage/add?mode=file', 'hand': '/manage/add'}
    assert 'cannot be read yet' in choices['brickset'].get_text()                    # Brickset CSV: said plainly, not offered
    for key in ('rebrickable', 'brickset'):                                          # no keys in this fixture: each sync says so
        assert choices[key].select_one('[data-choice-needs] a')['href'] == '/manage/get-started#keys'
    assert not choices['bricklink'].select('[data-choice-needs]')


def test_without_the_catalogue_the_choices_wait_for_it(client, monkeypatch):
    monkeypatch.setattr('brickwork.web.setup_state.catalogue_loaded', lambda: False)
    page = soup(client, '/manage/get-started/collection')
    assert page.select_one('[data-needs-catalogue]')
    assert all(b.has_attr('disabled') for b in page.select('[data-choice] .fr-btn')) and not page.select('[data-choice] a.fr-btn')


def test_the_pages_a_choice_opens_offer_the_way_back_and_others_do_not(client):
    assert not soup(client, '/manage/add').select('[data-flow-return]')            # not sent by the flow yet
    soup(client, '/manage/get-started/collection')
    for route in ('/manage/add?mode=file', '/manage/import-legacy', '/manage/sync'):
        back = soup(client, route).select_one('[data-flow-return] a')
        assert back['href'] == '/manage/get-started/collection', route
    assert not soup(client, '/collection/sets').select('[data-flow-return]')
    assert soup(client, '/manage/add?mode=file').select_one('input[name=mode][value=file]').has_attr('checked')


def test_the_summary_counts_what_came_in_and_links_each_import_to_finish(client, coll, world):
    flag = coll.db.execute("INSERT INTO flag(id, name, kind, shown_on_grid, created_at) VALUES('f-imp', 'imported from Rebrickable', 'tag', 0, "
                           "'2026-11-03T00:00:00Z') RETURNING id").fetchone()[0]
    copy = coll.db.execute('SELECT id FROM copy WHERE archived_at IS NULL LIMIT 1').fetchone()[0]
    coll.db.execute('INSERT INTO copy_flag(copy_id, flag_id) VALUES(?, ?)', (copy, flag))
    coll.db.execute('UPDATE copy SET condition=NULL WHERE id=?', (copy,))
    coll.db.commit()
    summary = soup(client, '/manage/get-started/collection').select_one('[data-collection-summary]')
    copies = coll.db.execute('SELECT count(*) FROM copy WHERE archived_at IS NULL').fetchone()[0]
    assert f'{copies} {"copy" if copies == 1 else "copies"}' in ' '.join(summary.get_text().split())
    assert summary.select_one('[data-unfinished]')
    link = summary.select_one('[data-imported-tag]')
    assert link['href'] == '/collection/sets?tag=imported+from+Rebrickable' and link.get_text(' ', strip=True) == '1 imported from Rebrickable'


def test_an_empty_collection_has_no_summary(client):
    assert not soup(client, '/manage/get-started/collection').select('[data-collection-summary]')


# #87: step 4, the guide: five cards, each linking to a screen that opens; "Got it" marks the step done; reachable from the flow and later.

def test_the_guide_has_five_cards_whose_links_all_open(client, world):
    page = soup(client, '/manage/get-started/guide')
    cards = page.select('[data-guide] [data-guide-card]')
    assert [c['data-guide-card'] for c in cards] == ['copies', 'completeness', 'stock', 'table', 'assistant']
    for card in cards:
        links = card.select('.fr-guide-links a')
        assert links, card['data-guide-card']
        for link in links:
            assert client.get(link['href']).status_code == 200, link['href']
    assert 'only the read scope' in page.select_one('[data-guide-card=assistant]').get_text()


def test_got_it_marks_the_guide_done_and_the_flow_links_it(client):
    step = soup(client).select_one('[data-key=guide]')
    assert step['data-state'] == 'open' and step.select_one('.fr-actions a')['href'] == '/manage/get-started/guide'
    page = soup(client, '/manage/get-started/guide')
    form = page.select_one('.fr-guide-end form')
    response = client.post(form['action'], data={i['name']: i['value'] for i in form.select('input')})
    assert response.location.endswith('/manage/get-started')
    assert states(soup(client))['guide'] == 'done'
    assert soup(client, '/manage/get-started/guide').select_one('[data-guide-done]') and not soup(client, '/manage/get-started/guide').select('.fr-guide-end form')
