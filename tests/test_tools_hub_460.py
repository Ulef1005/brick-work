"""#460 part 2: Tools & Admin leads with the two refreshes, the Get started card shows only while set-up is open, every hub entry sits in one
group, and the picture dialog posts from the hub and comes back to it. Invented data only, no network."""
from bs4 import BeautifulSoup
import pytest

from brickwork.web import admin_ops
from tests.app4 import app4, client, coll, csrf, pair, world  # noqa: F401  (the fixtures)
from tests.sources4 import keyed, unkeyed


def hub(client):
    response = client.get('/manage/tools')
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), 'html.parser')


def cells(soup):
    return soup.select('#refresh .bw-refresh-cell')


def finish_setup(client):
    for step in ('keys', 'guide'):
        client.post('/manage/get-started', data=dict(csrf_token=csrf(client), step=step, action='skip', back='flow'))


def test_the_hub_leads_with_the_refresh_block_and_jobs(client, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    finish_setup(client)
    soup = hub(client)
    first = soup.select_one('.bw-hub').find(True, recursive=False)
    assert first.select_one('h2').get_text() == 'Refresh' and first.select_one('#refresh')
    assert not soup.select('.bw-hub-top') and not soup.select('a.bw-hub-card')                 # no intro card once set-up is over
    left, right = cells(soup)
    assert left.select_one('.bw-refresh-num').get_text() == '7' and left.select_one('.bw-refresh-line').get_text() == 'prices out of date'
    prices = left.select_one('a.button.primary')
    assert prices.get_text() == 'Refresh prices' and prices['href'].endswith('/manage/refresh')
    opener = right.select_one('button[data-picture-open]')
    assert opener.get_text() == 'Refresh pictures' and 'primary' not in opener['class'] and not opener.has_attr('disabled')
    assert right.select_one('.bw-refresh-line').get_text().endswith(' missing') and not [b for b in soup.select('main .primary') if not b.find_parent('dialog')][1:]
    jobs = soup.select_one('#refresh a.bw-hub-row[href$="/manage/jobs"]')
    assert jobs and jobs.select_one('.bw-hub-title').get_text() == 'Jobs'
    assert len([a for a in soup.select('a.bw-hub-row') if a['href'].endswith('/manage/jobs')]) == 1


def test_the_intro_card_is_first_while_set_up_is_open_and_gone_when_it_is_finished(client, world):
    soup = hub(client)
    top = soup.select_one('.bw-hub').find(True, recursive=False)
    assert 'bw-hub-top' in top['class'] and top.select_one('a.bw-hub-card')['href'].endswith('/manage/get-started')
    assert [h.get_text() for h in soup.select('.bw-hub h2.bw-label')][:2] == ['Refresh', 'Your collection']          # the collection holds something: Refresh sits below it
    about = soup.select_one('section[aria-labelledby=hub-about]')
    assert [a['href'] for a in about.select('a.bw-hub-row')] == ['/manage/about']                  # while the card shows, the steps are not under About
    finish_setup(client)
    soup = hub(client)
    assert not soup.select('a.bw-hub-card') and soup.select_one('.bw-hub > section h2').get_text() == 'Refresh'
    about = soup.select_one('section[aria-labelledby=hub-about]')
    steps = [a for a in about.select('a.bw-hub-row') if a['href'].endswith('/manage/get-started')]
    assert steps and steps[0].select_one('.bw-hub-title').get_text() == 'Set-up steps' and steps[0].select_one('.bw-hub-signal').get_text() == 'done'
    assert not BeautifulSoup(client.get('/manage/settings').get_data(as_text=True), 'html.parser').select('a[href$="/manage/get-started"], .bw-hub-card')


def test_refresh_waits_for_a_collection_while_the_intro_shows(client, world, monkeypatch):
    monkeypatch.setattr('brickwork.web.onboarding.collection_started', lambda: False)
    soup = hub(client)
    assert soup.select('a.bw-hub-card') and not soup.select('#refresh')
    assert [h.get_text() for h in soup.select('.bw-hub h2.bw-label')] == ['Your collection', 'Settings', 'Maintenance', 'About']
    jobs = [a for a in soup.select('a.bw-hub-row') if a['href'].endswith('/manage/jobs')]
    assert len(jobs) == 1 and jobs[0].find_parent('section')['aria-labelledby'] == 'hub-collection'          # Jobs has its place before the Refresh block does


def test_refresh_states_nothing_to_do(client, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    finish_setup(client)
    real = admin_ops.tools_read

    def done(page, group=None):
        data = real(page, group)
        if page == 'hub':
            data = {**data, 'stale': 0, 'missing': 0}
        return data
    monkeypatch.setattr(admin_ops, 'tools_read', done)
    soup = hub(client)
    left, right = cells(soup)
    assert left.select_one('.bw-refresh-line').get_text() == 'Prices are up to date' and right.select_one('.bw-refresh-line').get_text() == 'No pictures missing'
    assert left.select_one('a.button')['class'] == ['button', 'bw-outline'] and not soup.select('#refresh .bw-refresh-cells .primary')       # both outline: no clay with nothing to do


def test_refresh_singular_wording(client, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    finish_setup(client)
    real = admin_ops.tools_read
    monkeypatch.setattr(admin_ops, 'tools_read', lambda page, group=None: {**real(page, group), 'stale': 1, 'missing': 1} if page == 'hub' else real(page, group))
    assert [c.select_one('.bw-refresh-line').get_text() for c in cells(hub(client))] == ['price out of date', 'picture missing']


def test_refresh_without_a_bricklink_key_asks_for_one(client, world, monkeypatch):
    unkeyed(monkeypatch)
    finish_setup(client)
    left, right = cells(hub(client))
    assert left.select_one('.bw-refresh-line').get_text() == 'Prices need a BrickLink key' and not left.select('.bw-refresh-num, a.primary')
    add = left.select_one('a.button.bw-outline')
    assert add.get_text() == 'Add a key' and '/manage/catalogues' in add['href']
    assert right.select_one('button[data-picture-open]') and not right.select_one('button[data-picture-open]').has_attr('disabled')


def test_refresh_on_a_read_only_install_is_switched_off(app4, client, world, monkeypatch):
    keyed(monkeypatch, 'bricklink')
    app4.config['BW_READ_ONLY'] = True
    try:
        soup = hub(client)
        left, right = cells(soup)
        assert left.select_one('button').has_attr('disabled') and not left.select('a.button') and right.select_one('button[data-picture-open]').has_attr('disabled')
        assert soup.select_one('[data-refresh-off]').get_text() == 'Changes are switched off on this instance'
        assert not soup.select('a.bw-hub-card') and not soup.select('#refresh .bw-refresh-cells .primary')                  # no intro card on an install that cannot be edited
    finally:
        app4.config['BW_READ_ONLY'] = False


def test_every_old_hub_entry_is_in_exactly_one_group(client, world):
    soup = hub(client)
    old = {'Statistics': '/manage/statistics', 'Sync': '/manage/sync', 'Jobs': '/manage/jobs', 'Unresolved items': '/manage/unresolved',
           'Instruction files': '/manage/instructions', 'Owners, tags and places': '/manage/values', 'Keys and sources': '/manage/catalogues',
           'Appearance': '/manage/appearance', 'Catalogue': '/manage/catalogue', 'BrickLink item lists': '/manage/catalogue-lists',
           'Mappings and coverage': '/manage/catalogue-mappings', 'Backup and database check': '/manage/database', 'API tokens': '/manage/tokens',
           'Migration report': '/manage/migration', 'Part Spotter history': '/manage/history', 'About Brick Work': '/manage/about'}
    rows = {}
    for row in soup.select('.bw-hub a.bw-hub-row'):
        rows.setdefault(row.select_one('.bw-hub-title').get_text(), []).append(row['href'].split('#')[0])
    for title, href in old.items():
        assert [h for h in rows.get(title, [])] and len(rows[title]) == 1 and rows[title][0].endswith(href.split('/')[-1]), title
    assert len([r for r in soup.select('.bw-hub a.bw-hub-row') if r['href'].endswith('/manage/import-legacy')]) == 1
    maintenance = soup.select_one('details#maintenance')
    assert maintenance.summary.get_text() == 'Show 8 tools' and not maintenance.has_attr('open') and len(maintenance.select('a.bw-hub-row')) == 8
    settings = soup.select_one('section[aria-labelledby=hub-settings]')
    assert [a['href'].split('/manage/')[1] for a in settings.select('a.bw-hub-row')] == ['settings#set-money', 'settings#set-parts', 'settings#set-labels', 'settings#set-sources', 'catalogues', 'appearance']
    assert settings.select('a.bw-hub-row')[3].select_one('.bw-hub-signal').get_text() == 'for experts'
    ids = [e['id'] for e in soup.select('.bw-hub [id]')]
    assert len(ids) == len(set(ids))                                                                    # the macro's ids are slugs: no clash


def test_the_picture_dialog_posts_from_the_hub_and_comes_back_to_it(client, world):
    soup = hub(client)
    form = soup.select_one('#refresh dialog[data-picture-form], #refresh dialog form[data-picture-form]')
    assert form['action'].endswith('/manage/hub') and form.select_one('input[name=action]')['value'] == 'pictures'
    assert soup.select_one('script[src*="bw-pictures.js"]') and soup.select_one('[data-picture-counts]')
    assert not BeautifulSoup(client.get('/manage/settings').get_data(as_text=True), 'html.parser').select('script[src*="bw-pictures.js"]')
    stale = client.post('/manage/hub', data=dict(csrf_token=csrf(client), action='pictures', scope='missing', types=['set'], expected_count='99'))
    assert stale.status_code == 302 and stale.location.endswith('/manage/tools#refresh')               # the refusal returns to the hub
    ok = client.post('/manage/hub', data=dict(csrf_token=csrf(client), action='pictures', scope='missing', types=['set'], expected_count='3'))
    assert ok.status_code == 302 and ok.location.endswith('/manage/jobs')                               # a started refresh shows its jobs
    assert client.post('/manage/hub', data=dict(csrf_token=csrf(client), action='nope')).status_code == 404
    assert client.post('/manage/hub', data=dict(action='pictures', scope='missing', types=['set'])).status_code == 400    # the CSRF token is still needed


def test_the_hub_loads_its_picture_assets_and_the_other_admin_pages_do_not(client, world):
    assert hub(client).select_one('script[src*="bw-pictures.js"]')
    assert not BeautifulSoup(client.get('/manage/jobs').get_data(as_text=True), 'html.parser').select('script[src*="bw-pictures.js"], [data-picture-dialog]')


def test_a_save_from_the_group_parts_row_opens_that_row_again(client, coll, world):
    page = BeautifulSoup(client.get('/manage/settings').get_data(as_text=True), 'html.parser')
    form = page.select_one('form#bw-settings-form')
    data = {'csrf_token': form.select_one('[name=csrf_token]')['value'], 'row': 'part-list-grouping', 'retail_country': 'DE', 'part_list_grouping': 'none'}
    response = client.post('/manage/settings', data=data)
    assert response.status_code == 302 and response.location.endswith('#part-list-grouping')
    assert page.select_one('details.bw-set#part-list-grouping #edit-grouping')
