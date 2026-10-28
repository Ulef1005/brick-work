"""M.10c (issue #112): the catalogue lifecycle in Tools & Admin, the Settings switches and the migration report view.

One test per screen state the frames show (m10c1 to m10c6). Invented data only: the 4.0 fixture pair, a fixture dump served by a fake
fetch, fixture BrickLink XML, and a migration report the fixtures write into a temp folder."""
import gzip
import json
import os
import shutil
from contextlib import closing

from bs4 import BeautifulSoup
import pytest

from brickwork.store4 import jobs as fetch_jobs
from brickwork.store4.cli import Paths
from brickwork.web import admin_ops, catalogue_jobs
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)
from tests.store4_mint_fixtures import build_catalogue
from tests.test_store4_bricklink import write_xml


def page(client, name):
    response = client.get('/manage/' + name)
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    html = response.get_data(as_text=True)
    return html, BeautifulSoup(html, 'html.parser')


def text(soup):
    return ' '.join(soup.get_text(' ').split())


@pytest.fixture
def paths(pair):
    return Paths(pair.parent)


@pytest.fixture
def served(tmp_path, paths):
    """The fixture dump behind a fake fetch, as Rebrickable's twelve files; nothing leaves the machine."""
    dump = tmp_path / 'dl'
    dump.mkdir()
    build_catalogue(dump)                                  # leaves dump/dump/*.csv.gz
    files = {p.name: p.read_bytes() for p in (dump / 'dump').glob('*.csv.gz')}
    catalogue_jobs.FETCH = lambda url: (files[url.rsplit('/', 1)[1]], 'Mon, 26 Oct 2026 08:00:00 GMT')
    yield files
    catalogue_jobs.FETCH = None


def test_hub_lists_the_catalogue_pages_and_the_report(client, world):
    html, soup = page(client, 'hub')
    for label in ('Catalogue', 'BrickLink item lists', 'Mappings and coverage', 'Migration report'):
        assert soup.find(class_='bw-hub-title', string=label), label


def test_c1_catalogue_shows_the_build_and_both_actions(client, world, paths):
    catalogue_jobs.start(paths, 'reconcile', background=False)
    html, soup = page(client, 'catalogue')
    body = text(soup)
    assert 'Current build' in body and 'Retired, kept' in body and 'Rebrickable download' in body
    assert soup.find('button', string='Re-download') and soup.find('button', string='Rebuild')
    assert soup.find('button', string='Re-download').get('disabled') is None
    assert soup.find('button', string='Rebuild').has_attr('disabled') and 'Run Re-download first' in body        # no download on disk yet
    assert 'Rebrickable asks for at most one download a day' in body
    assert 'Reconciled' in body and 'Not reconciled yet' not in body


def test_c2_a_running_job_shows_progress_and_holds_the_actions(client, world, paths):
    catalogue_jobs._write(paths, dict(kind='redownload', state='running', pid=os.getpid(), started_at='2026-10-27T09:00:00Z', finished_at=None,
                                      step=1, folder=None, error=None, result=None))
    html, soup = page(client, 'catalogue')
    bar = soup.find(attrs={'role': 'progressbar'})
    assert bar and bar['aria-valuenow'] == '33'
    assert 'Building the catalogue' in text(soup) and soup.find(attrs={'data-catalogue-job': True})
    assert soup.find('button', string='Re-download').has_attr('disabled') and soup.find('button', string='Rebuild').has_attr('disabled')
    assert 'Re-download is running' in text(soup)


def test_c2_a_job_whose_process_is_gone_reads_as_stopped(client, world, paths):
    catalogue_jobs._write(paths, dict(kind='rebuild', state='running', pid=2 ** 22 + 12345, started_at='2026-10-27T09:00:00Z', finished_at=None,
                                      step=0, folder=None, error=None, result=None))
    html, soup = page(client, 'catalogue')
    assert 'Stopped' in text(soup) and soup.find(attrs={'data-catalogue-job': True}) is None
    assert soup.find('button', string='Re-download').get('disabled') is None


def test_c2_a_finished_redownload_lists_what_changed_and_the_copies(client, world, paths, served, coll):
    state = catalogue_jobs.start(paths, 'redownload', background=False)
    assert state['state'] == 'done', state
    html, soup = page(client, 'catalogue')
    body = text(soup)
    assert 'Re-download · finished' in body and 'Copies whose part list changed' in body
    assert soup.find('button', string='Rebuild').get('disabled') is None                              # a download is on disk now
    assert 'Nothing switches on its own' in body or 'None. Every copy still matches' in body


def test_c2_changed_copies_are_named_set_n_and_link_to_the_copy(client, world, paths, served, pair):
    state = catalogue_jobs.start(paths, 'redownload', background=False)
    assert state['state'] == 'done', state
    with closing(__import__('sqlite3').connect(pair)) as db:
        db.execute("UPDATE copy SET inventory_digest='stale' WHERE id=?", (world.copy_b,))
        db.commit()
    html, soup = page(client, 'catalogue')
    row = soup.select_one('[data-catalogue-result] .bwc-row[href$="?copy=' + world.copy_b + '"]')
    assert row and 'Set 2 · 1 list changed' in row.get_text(' ', strip=True)
    assert row['href'].endswith('?copy=' + world.copy_b) and '/collection/item/' in row['href']
    assert world.copy_b[:8] not in row.get_text()


def test_c2_not_reconciled_yet_is_shown_and_reconcile_now_fixes_it(client, world, paths, pair, served):
    with closing(__import__('sqlite3').connect(pair)) as db:
        db.execute('UPDATE catalogue_build SET reconciled_at=NULL')
        db.commit()
    html, soup = page(client, 'catalogue')
    assert soup.find(attrs={'data-not-reconciled': True}) and 'Not reconciled yet' in text(soup)
    token = csrf(client)
    r = client.post('/manage/catalogue', data={'csrf_token': token, 'action': 'reconcile'})
    assert r.status_code == 302
    for _ in range(100):
        if catalogue_jobs.read(paths)['state'] != 'running':
            break
        __import__('time').sleep(0.1)
    html, soup = page(client, 'catalogue')
    assert soup.find(attrs={'data-not-reconciled': True}) is None and 'Reconcile · finished' in text(soup)


def test_c2_a_failed_job_says_why_and_keeps_the_old_file(client, world, paths):
    catalogue_jobs.FETCH = lambda url: (_ for _ in ()).throw(OSError('network down'))
    try:
        state = catalogue_jobs.start(paths, 'redownload', background=False)
    finally:
        catalogue_jobs.FETCH = None
    assert state['state'] == 'failed'
    html, soup = page(client, 'catalogue')
    assert 'Failed' in text(soup) and 'network down' in text(soup) and 'still in place' in text(soup)


def test_actions_need_the_post_to_pass_csrf_and_editing(client, world):
    assert client.post('/manage/catalogue', data={'action': 'rebuild'}).status_code == 400


def test_c3_lists_page_with_no_folder_then_a_load(client, world, paths, tmp_path):
    html, soup = page(client, 'catalogue-lists')
    body = text(soup)
    assert 'Not loaded' in body and 'No folder of lists yet' in body and not soup.find('button', string='Load lists')
    write_xml(paths.lists / '2026-10-26')
    html, soup = page(client, 'catalogue-lists')
    assert soup.find('input', {'name': 'folder', 'value': '2026-10-26'}).has_attr('checked') and soup.find('button', string='Load lists')
    state = catalogue_jobs.start(paths, 'lists', folder='2026-10-26', background=False)
    assert state['state'] == 'done', state
    html, soup = page(client, 'catalogue-lists')
    body = text(soup)
    assert 'Loaded ·' in body and 'Links upgraded' in body and 'Candidates to check' in body and 'Kinds corrected' in body
    assert soup.find('a', href='/manage/unresolved') or 'Candidates to check' in body


def test_c3_a_typed_path_is_refused(client, world, paths):
    write_xml(paths.lists / 'one')
    token = csrf(client)
    client.post('/manage/catalogue-lists', data={'csrf_token': token, 'action': 'load_lists', 'folder': '../../etc'})
    assert catalogue_jobs.read(paths) is None


def test_c4_mappings_and_coverage(client, world, paths):
    html, soup = page(client, 'catalogue-mappings')
    body = text(soup)
    assert 'Shipped with the app' in body and 'parts.csv' in body and 'None. This install uses the shipped files only' in body or 'Local on this install' in body
    assert 'Item coverage is not known yet' in body or 'items have a BrickLink number' in body
    assert 'part and colour pairs have a known picture' in body or 'No parts in your collection yet' in body
    catalogue_jobs.start(paths, 'reconcile', background=False)
    html, soup = page(client, 'catalogue-mappings')
    assert soup.find(attrs={'data-coverage': 'items'}).find(class_='bwc-bar')
    assert 'Bars start at zero' not in text(soup)
    kinds = [r.find('span').get_text() for r in soup.select('.bwc-bykind .bwc-trow')]
    assert kinds and set(kinds) <= {'Sets', 'Minifigures', 'Parts', 'Instructions', 'Boxes', 'Gear', 'Books', 'Catalogues'}
    assert soup.find(attrs={'data-coverage': 'pictures'}).find(class_='bwc-bar')


def test_c4_local_mapping_files_are_listed_with_rows(client, world, paths):
    paths.mappings.mkdir(parents=True)
    (paths.mappings / 'parts.csv').write_text('# mapping_version: 2099.1.1.1\n# dump_date: 2026-10-23\n# source: SYNTHETIC\n'
                                              'rb_part_num,rb_color_id,provider,provider_kind,provider_key,status,method,preferred\n'
                                              '3001,,bricklink,P,3001,matched,external_ids,0\n3023,,bricklink,P,3023,matched,external_ids,0\n')
    html, soup = page(client, 'catalogue-mappings')
    rows = [r for r in soup.select('.bwc-trow') if 'parts.csv' in r.get_text() and '2099.1.1.1' in r.get_text()]
    assert rows and rows[0].select('.mono')[-1].get_text().strip() == '2'


def test_c5_the_switch_is_disabled_without_a_bricklink_key(client, world, monkeypatch):
    monkeypatch.setattr(fetch_jobs, '_configured', lambda source: False)
    html, soup = page(client, 'settings')
    box = soup.find('input', attrs={'data-prefer-input': True})
    assert box.has_attr('disabled') and 'Needs a BrickLink key' in text(soup)
    token = csrf(client)
    client.post('/manage/settings', data={'csrf_token': token, 'action': 'prefer_bricklink', 'value': 'on'})
    with closing(__import__('sqlite3').connect(os.environ['BW_DB_PATH'])) as db:
        assert db.execute("SELECT 1 FROM setting WHERE key='prefer_bricklink_inventory'").fetchone() is None


def test_c5_the_switch_saves_with_a_key_and_the_picture_order_posts_back(client, world, monkeypatch):
    monkeypatch.setattr(fetch_jobs, '_configured', lambda source: True)
    html, soup = page(client, 'settings')
    box = soup.find('input', attrs={'data-prefer-input': True})
    assert box.get('disabled') is None and box.get('checked') is None
    token = csrf(client)
    client.post('/manage/settings', data={'csrf_token': token, 'action': 'prefer_bricklink', 'value': 'on'})
    html, soup = page(client, 'settings')
    assert soup.find('input', attrs={'data-prefer-input': True}).has_attr('checked')
    order = {g.find('input', {'data-order-value': True})['name']: g.find('input', {'data-order-value': True})['value'] for g in soup.select('[data-order-group]')}
    assert order == {'priority:pictures:part': 'rebrickable_dump,bricklink,rebrickable_api', 'priority:pictures:*': 'bricklink,rebrickable_dump'}
    names = text(soup.find(id='picture-priority'))
    for words in ('Rebrickable catalogue', 'BrickLink', 'Rebrickable API', 'Parts', 'Everything else'):
        assert words in names
    client.post('/manage/settings', data={'csrf_token': token, 'retail_country': 'DE', 'priority:metadata:set': 'brickset', 'priority:market_price:*': 'bricklink',
                                         'priority:pictures:part': 'bricklink,rebrickable_dump',
                                         'priority:pictures:*': 'rebrickable_dump,bricklink'})
    html, soup = page(client, 'settings')
    order = {g.find('input', {'data-order-value': True})['name']: g.find('input', {'data-order-value': True})['value'] for g in soup.select('[data-order-group]')}
    assert order['priority:pictures:part'] == 'bricklink,rebrickable_dump' and order['priority:pictures:*'] == 'rebrickable_dump,bricklink'
    client.post('/manage/settings', data={'csrf_token': token, 'action': 'prefer_bricklink', 'value': 'off'})
    html, soup = page(client, 'settings')
    assert soup.find('input', attrs={'data-prefer-input': True}).get('checked') is None


def make_report(tmp_path):
    from tests.test_store4_migrate_run import make_attach_33, run, FIXTURES
    src, maps = tmp_path / 'm' / 'bw33.db', tmp_path / 'm' / 'maps'
    (tmp_path / 'm').mkdir()
    make_attach_33(src)
    shutil.copytree(FIXTURES / 'mappings', maps)
    (tmp_path / 'mcat').mkdir()
    cat = build_catalogue(tmp_path / 'mcat')
    res = run(src, cat, maps, tmp_path / 'm' / 'out' / 'brickwork-4.db', tmp_path / 'm' / 'report')
    assert res.result == 'PASS'
    return res.report, res.digest


def test_c6_migration_report_without_a_report(client, world, monkeypatch, tmp_path):
    monkeypatch.setenv('BW_MIGRATION_REPORT', str(tmp_path / 'nothing-here'))
    html, soup = page(client, 'migration')
    assert 'no migration report on this install' in text(soup)


def test_c6_migration_report_view_and_downloads(client, world, monkeypatch, tmp_path, pair):
    report, digest = make_report(tmp_path)
    monkeypatch.setenv('BW_MIGRATION_REPORT', str(report))
    with closing(__import__('sqlite3').connect(pair)) as db:
        db.execute("INSERT INTO meta(key,value) VALUES('migrated_from', ?)", (json.dumps({'file': 'bw33.db', 'report_digest': digest}),))
        db.commit()
    html, soup = page(client, 'migration')
    body = text(soup)
    assert 'Proof passed' in body and 'matches the one recorded in your collection' in body
    assert soup.find(id='migration-proof').select('.bwc-proof') and 'Manual decisions' in body
    assert soup.select_one('.bwc-proof-name .mono').get_text() and soup.select_one('.bwc-proof-name .bk-note').get_text().strip()
    names = [r.select_one('.bwc-fname .mono').get_text() for r in soup.select('.bwc-file')]
    assert 'summary.md' in names and 'proof.json' in names and 'manual-decisions.csv' in names
    link = soup.find('a', href='/manage/migration/file/mint.csv')
    assert link and link.get_text().startswith('Download') and link.has_attr('download')
    r = client.get('/manage/migration/file/mint.csv')
    assert r.status_code == 200 and 'attachment' in r.headers['Content-Disposition']
    assert client.get('/manage/migration/file/..%2Fbw33.db').status_code == 404
    assert client.get('/manage/migration/file/nothere.csv').status_code == 404
    assert client.get('/manage/migration/file/.migration-run').status_code == 404


# ---------- the start-up reconcile (design 6.2) ----------

def unreconcile(pair):
    with closing(__import__('sqlite3').connect(pair)) as db:
        db.execute('UPDATE catalogue_build SET reconciled_at=NULL')
        db.commit()


def jobs_of(pair, kind='reconcile'):
    with closing(__import__('sqlite3').connect(pair)) as db:
        return db.execute('SELECT id, state, error, via FROM job WHERE kind=? ORDER BY id', (kind,)).fetchall()


def test_startup_reconcile_queues_nothing_when_reconciled_and_one_job_when_not(pair, coll, paths):
    from brickwork.core.connect import connect
    from brickwork.store4 import reconcile_job
    catalogue_jobs.start(paths, 'reconcile', background=False)
    with closing(connect(pair)) as db:
        assert reconcile_job.queue_if_due(db) is None
    assert jobs_of(pair) == []
    unreconcile(pair)
    with closing(connect(pair)) as db:
        first = reconcile_job.queue_if_due(db)
        again = reconcile_job.queue_if_due(db)                          # idempotent while one is open
    assert first and first == again
    assert jobs_of(pair) == [(first, 'queued', None, 'app')]


def test_startup_reconcile_is_run_by_the_drainer_not_a_request(pair, coll, paths):
    from brickwork.core import drainer
    unreconcile(pair)
    assert drainer.queue_startup_work(pair) is not None
    assert jobs_of(pair)[0][1] == 'queued'
    with closing(__import__('sqlite3').connect(pair)) as db:
        assert db.execute('SELECT count(*) FROM catalogue_build WHERE reconciled_at IS NULL').fetchone()[0] == 1
    drainer.drain_once(pair)
    (job,) = jobs_of(pair)
    assert job[1] == 'done' and job[2] is None
    with closing(__import__('sqlite3').connect(pair)) as db:
        assert db.execute('SELECT count(*) FROM catalogue_build WHERE reconciled_at IS NULL').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM job_owner').fetchone()[0] == 0
    assert drainer.queue_startup_work(pair) is None                      # nothing due now


def test_startup_reconcile_that_fails_says_why_and_is_tried_again_at_the_next_start(client, pair, coll, paths, monkeypatch):
    from brickwork.core import drainer
    from brickwork.store4 import reconcile_job
    unreconcile(pair)
    drainer.queue_startup_work(pair)
    monkeypatch.setattr(reconcile_job, 'reconcile', lambda db, **kw: (_ for _ in ()).throw(RuntimeError('disk full')))
    drainer.drain_once(pair)
    (job,) = jobs_of(pair)
    assert job[1] == 'failed' and 'disk full' not in job[2] and 'server log' in job[2]
    html, soup = page(client, 'catalogue')
    assert soup.find(attrs={'data-reconcile-failed': True}) and 'server log' in text(soup)
    second = drainer.queue_startup_work(pair)
    assert second and second != job[0] and len(jobs_of(pair)) == 2


def test_startup_reconcile_is_queued_when_the_app_starts_with_the_embedded_worker(pair, coll, paths, app4, monkeypatch):
    from brickwork.core import drainer
    from brickwork.web import views
    unreconcile(pair)
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '1')
    monkeypatch.setattr(drainer, 'spawn', lambda target: target())      # the drainer thread, run here
    views.bw_resume_imports(app4)
    (job,) = jobs_of(pair)
    assert job[1] == 'done'
    with closing(__import__('sqlite3').connect(pair)) as db:
        assert db.execute('SELECT count(*) FROM catalogue_build WHERE reconciled_at IS NULL').fetchone()[0] == 0


def test_the_headless_worker_queues_it_too(pair, coll, paths, monkeypatch):
    from brickwork.core import drainer
    unreconcile(pair)
    drainer.worker(path=pair)
    (job,) = jobs_of(pair)
    assert job[1] == 'done'


def test_a_queued_startup_reconcile_shows_on_the_catalogue_page_and_the_jobs_list(client, pair, coll, paths):
    from brickwork.core import drainer
    unreconcile(pair)
    drainer.queue_startup_work(pair)
    html, soup = page(client, 'catalogue')
    assert 'reconciling it in the background' in text(soup)
    html, soup = page(client, 'jobs')
    assert 'Reconcile with the catalogue' in text(soup)


# ---------- routes and writes ----------

def wait_for_job(paths):
    import time
    for _ in range(200):
        state = catalogue_jobs.read(paths)
        if state and state['state'] != 'running':
            return state
        time.sleep(0.05)
    raise AssertionError('the job did not finish')


def test_the_job_route_reports_none_running_and_done(client, world, paths, served):
    assert client.get('/manage/catalogue/job').get_json() == {'state': 'none'}
    catalogue_jobs._write(paths, dict(kind='redownload', state='running', pid=os.getpid(), started_at='2026-10-27T09:00:00Z', finished_at=None,
                                      step=2, folder=None, error=None, result=None))
    r = client.get('/manage/catalogue/job')
    state = r.get_json()
    assert state['state'] == 'running' and state['step'] == 2 and len(state['steps']) == 3 and r.headers['Cache-Control'] == 'no-store'


def test_post_redownload_starts_a_background_job_that_finishes(client, world, paths, served):
    token = csrf(client)
    r = client.post('/manage/catalogue', data={'csrf_token': token, 'action': 'redownload'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/manage/catalogue')
    state = wait_for_job(paths)
    assert state['state'] == 'done' and state['kind'] == 'redownload'
    assert (paths.downloads / next(iter(sorted(p.name for p in paths.downloads.iterdir() if p.is_dir())))).is_dir()


def test_post_rebuild_needs_a_download_and_then_runs(client, world, paths, served):
    token = csrf(client)
    html = client.post('/manage/catalogue', data={'csrf_token': token, 'action': 'rebuild'}, follow_redirects=True).get_data(as_text=True)
    assert 'no complete Rebrickable download' in html and catalogue_jobs.read(paths) is None
    assert catalogue_jobs.start(paths, 'redownload', background=False)['state'] == 'done'
    r = client.post('/manage/catalogue', data={'csrf_token': token, 'action': 'rebuild'})
    assert r.status_code == 302
    state = wait_for_job(paths)
    assert state['kind'] == 'rebuild' and state['state'] == 'done' and state['result']['moved_aside'].startswith('catalogue.db.damaged-')


def test_post_load_lists_runs_the_job_through_the_route(client, world, paths):
    write_xml(paths.lists / '2026-10-26')
    token = csrf(client)
    r = client.post('/manage/catalogue-lists', data={'csrf_token': token, 'action': 'load_lists', 'folder': '2026-10-26'})
    assert r.status_code == 302
    assert wait_for_job(paths)['kind'] == 'lists'
    html, soup = page(client, 'catalogue-lists')
    assert 'Loaded ·' in text(soup)


def test_a_second_job_while_one_runs_is_refused_with_a_message(client, world, paths):
    catalogue_jobs._write(paths, dict(kind='redownload', state='running', pid=os.getpid(), started_at='2026-10-27T09:00:00Z', finished_at=None,
                                      step=0, folder=None, error=None, result=None))
    token = csrf(client)
    html = client.post('/manage/catalogue', data={'csrf_token': token, 'action': 'reconcile'}, follow_redirects=True).get_data(as_text=True)
    assert 'is running already' in html


def test_the_wrong_action_for_a_page_is_a_400(client, world):
    token = csrf(client)
    assert client.post('/manage/catalogue', data={'csrf_token': token, 'action': 'load_lists'}).status_code == 400
    assert client.post('/manage/catalogue-lists', data={'csrf_token': token, 'action': 'rebuild'}).status_code == 400
    assert client.post('/manage/catalogue-mappings', data={'csrf_token': token, 'action': 'reconcile'}).status_code == 400
    assert client.post('/manage/migration', data={'csrf_token': token, 'action': 'reconcile'}).status_code == 400
    assert client.post('/manage/catalogue', data={'csrf_token': token}).status_code == 400


def test_a_read_only_instance_refuses_every_write_here(app4, client, world, paths):
    token = csrf(client)
    app4.config['BW_READ_ONLY'] = True
    try:
        for page_name, action in (('catalogue', 'redownload'), ('catalogue', 'rebuild'), ('catalogue', 'reconcile'), ('catalogue-lists', 'load_lists')):
            assert client.post('/manage/' + page_name, data={'csrf_token': token, 'action': action}).status_code == 403
        assert client.post('/manage/settings', data={'csrf_token': token, 'action': 'prefer_bricklink', 'value': 'on'}).status_code == 403
    finally:
        app4.config['BW_READ_ONLY'] = False
    assert catalogue_jobs.read(paths) is None


def test_the_switch_post_without_the_csrf_token_is_refused(client, world, monkeypatch):
    monkeypatch.setattr(fetch_jobs, '_configured', lambda source: True)
    page(client, 'settings')
    assert client.post('/manage/settings', data={'action': 'prefer_bricklink', 'value': 'on'}).status_code == 400


def test_the_report_reads_a_csv_with_a_field_over_the_csv_module_limit(tmp_path):
    # The real 26 Oct report's not-carried.csv carries a 1.9 MB samples field; the default csv limit is 131,072 characters.
    from brickwork.store4.migrate_report import read_report
    (tmp_path / 'summary.md').write_text('# Brick Work 3.3 to 4.0 migration: PASS\n')
    (tmp_path / 'not-carried.csv').write_text('table,count,samples\nphoto,2,"' + 'x' * 200_000 + '"\nnote,1,y\n')
    report = read_report(tmp_path)
    assert [f['rows'] for f in report['files'] if f['name'] == 'not-carried.csv'] == [2]
    import csv
    assert csv.field_size_limit() == 131072                                  # the limit is raised for the read only


# ---------- Codex review findings ----------

def test_r1_startup_reconcile_needs_no_catalogue_file(pair, coll, paths, app4, monkeypatch):
    from brickwork.core import drainer
    from brickwork.web import views
    coll.db.close()
    paths.catalogue.unlink()
    assert drainer.queue_startup_work(pair) is None                         # nothing to reconcile without a catalogue, and no NoCatalogue
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '1')
    monkeypatch.setattr(drainer, 'spawn', lambda target: None)
    views.bw_resume_imports(app4)                                           # the app starts and can serve the first-run page
    assert drainer.queue_startup_work(pair) is None and jobs_of(pair) == []


def test_r2_startup_reconcile_is_queued_even_when_other_jobs_are_pending(pair, coll, paths, app4, monkeypatch):
    from brickwork.core import drainer
    from brickwork.web import views
    unreconcile(pair)
    with closing(__import__('sqlite3').connect(pair)) as db:
        db.execute("INSERT INTO job(source, kind, state, via, created_at, updated_at) VALUES('import', 'item', 'queued', 'app', '2026-10-27T09:00:00.000Z', '2026-10-27T09:00:00.000Z')")
        db.commit()
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '1')
    monkeypatch.setattr(drainer, 'spawn', lambda target: None)
    views.bw_resume_imports(app4)
    assert [j[1] for j in jobs_of(pair)] == ['queued']


def test_r3_admission_holds_a_lock_file_other_processes_see(client, world, paths, monkeypatch):
    import fcntl
    seen = []
    real = catalogue_jobs.read

    def spying(p):
        try:
            with open(paths.data / 'catalogue-job.lock', 'a') as other:      # another open file description: what a second process has
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            seen.append('free')
        except BlockingIOError:
            seen.append('held')
        return real(p)
    monkeypatch.setattr(catalogue_jobs, 'read', spying)
    catalogue_jobs.start(paths, 'reconcile', background=False)
    assert seen[0] == 'held'


def test_r3_the_state_file_part_name_is_unique_per_writer(paths, monkeypatch):
    names = []
    real = os.replace
    monkeypatch.setattr(os, 'replace', lambda a, b: (names.append(str(a)), real(a, b))[1])
    catalogue_jobs._write(paths, dict(kind='reconcile', state='done'))
    catalogue_jobs._write(paths, dict(kind='reconcile', state='done'))
    assert len(set(names)) == 2 and all(n.endswith('.part') for n in names)


def test_r4_a_running_reconcile_job_cannot_be_reclaimed_by_a_second_drainer(pair, coll, paths, monkeypatch):
    from brickwork.core.connect import connect
    from brickwork.store4 import reconcile_job
    unreconcile(pair)
    calls, inner = [], []

    def nested(db, **kw):
        calls.append(1)
        if len(calls) == 1:
            inner.append(reconcile_job.drain(db))                            # a second drainer in this process, mid-run
    monkeypatch.setattr(reconcile_job, 'reconcile', nested)
    with closing(connect(pair)) as db:
        reconcile_job.queue_if_due(db)
        reconcile_job.drain(db)
    assert len(calls) == 1 and inner == [[]]
    from brickwork.store4 import jobs as store4_jobs
    assert not store4_jobs._CLAIMED


def test_r5_raw_errors_never_reach_the_job_row_or_the_page(client, pair, coll, paths, tmp_path, monkeypatch, served):
    served_files = served
    from brickwork.core import drainer
    from brickwork.store4 import reconcile_job
    from brickwork.store4.errors import Store4Error
    unreconcile(pair)
    drainer.queue_startup_work(pair)
    secret = str(tmp_path / 'private' / 'brickwork.db')
    monkeypatch.setattr(reconcile_job, 'reconcile', lambda db, **kw: (_ for _ in ()).throw(RuntimeError(f'unable to open {secret}: SQL near "SELECT"')))
    drainer.drain_once(pair)
    (job,) = jobs_of(pair)
    assert job[1] == 'failed' and 'private' not in job[2] and 'SELECT' not in job[2] and 'server log' in job[2]
    html, soup = page(client, 'catalogue')
    assert 'private' not in html and 'SELECT' not in html and 'server log' in html
    # the page's own jobs: a store4 message that names a path keeps its words and loses the folders
    catalogue_jobs.FETCH = lambda url: (_ for _ in ()).throw(Store4Error(f'no file at {secret} to read'))
    try:
        state = catalogue_jobs.start(paths, 'redownload', background=False)
    finally:
        catalogue_jobs.FETCH = None
    assert state['state'] == 'failed'
    html, soup = page(client, 'catalogue')
    assert 'private' not in html and str(tmp_path) not in html
    monkeypatch.setattr(catalogue_jobs.cli, 'build', lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f'boom at {secret}')))
    monkeypatch.setattr(catalogue_jobs, 'FETCH', None)
    catalogue_jobs.FETCH = lambda url: (served_files[url.rsplit('/', 1)[1]], 'x')
    try:
        state = catalogue_jobs.start(paths, 'redownload', background=False)
    finally:
        catalogue_jobs.FETCH = None
    html, soup = page(client, 'catalogue')
    assert 'private' not in html and 'boom' not in html and 'server log' in html


# ---------- Codex review of the error text ----------

def test_e1_a_store4_error_that_wraps_sqlite_gives_the_generic_sentence():
    import sqlite3
    from brickwork.store4.errors import CatalogueError, GENERIC, SchemaMismatch, Store4Error, public_text
    try:
        try:
            raise sqlite3.DatabaseError('no such table: meta')
        except sqlite3.DatabaseError as inner:
            raise CatalogueError('catalogue.db cannot be read as a catalogue: no such table: meta') from inner
    except CatalogueError as exc:
        assert public_text(exc) == GENERIC
    try:
        try:
            raise sqlite3.OperationalError('near "SELECT": syntax error')
        except sqlite3.Error:
            raise SchemaMismatch('not a 4.0 file (near "SELECT": syntax error)') from None      # context kept even with `from None`
    except SchemaMismatch as exc:
        assert public_text(exc) == GENERIC
    assert public_text(Store4Error('the catalogue has this set now; use its own part list')) == 'the catalogue has this set now; use its own part list'


def test_e2_known_paths_are_redacted_exactly_even_with_spaces_and_parentheses(tmp_path):
    from pathlib import Path
    from brickwork.store4.errors import Store4Error, public_text
    folder = tmp_path / 'Private Collection (old)'
    folder.mkdir()
    message = f'no catalogue at {folder}/catalogue.db; the collection {folder}/brickwork.db is in {folder} and {Path.home()}/dl'
    text_out = public_text(Store4Error(message), known=[folder, folder / 'catalogue.db', folder / 'brickwork.db'])
    assert 'Private' not in text_out and str(tmp_path) not in text_out and str(Path.home()) not in text_out
    assert 'catalogue.db' in text_out and 'brickwork.db' in text_out and 'the data folder' in text_out


def test_e2_the_reconcile_job_and_the_catalogue_page_redact_the_data_folder(tmp_path, monkeypatch):
    from brickwork.core.connect import connect
    from brickwork.store4 import reconcile_job
    from brickwork.store4.errors import Store4Error
    from tests.app4 import make_pair
    folder = tmp_path / 'Private Collection (old)'
    folder.mkdir()
    pair = make_pair(folder)
    unreconcile(pair)
    monkeypatch.setattr(reconcile_job, 'reconcile', lambda db, **kw: (_ for _ in ()).throw(Store4Error(f'cannot open {folder}/brickwork.db in {folder}')))
    with closing(connect(pair)) as db:
        reconcile_job.queue_if_due(db)
        (ran,) = reconcile_job.drain(db)
    assert ran['state'] == 'failed' and 'Private' not in ran['error'] and str(tmp_path) not in ran['error'] and 'brickwork.db' in ran['error']


def test_e2_a_catalogue_job_error_redacts_the_data_folder(tmp_path, monkeypatch):
    from brickwork.store4.errors import Store4Error
    from tests.app4 import make_pair
    folder = tmp_path / 'Private Collection (old)'
    folder.mkdir()
    pair = make_pair(folder)
    paths = Paths(pair.parent)
    monkeypatch.setattr(catalogue_jobs.cli, 'do_reconcile', lambda p: None)
    monkeypatch.setattr(catalogue_jobs, '_reconcile', lambda p, *_: (_ for _ in ()).throw(Store4Error(f'cannot open {folder}/catalogue.db')))
    state = catalogue_jobs.start(paths, 'reconcile', background=False)
    assert state['state'] == 'failed' and 'Private' not in state['error'] and str(tmp_path) not in state['error'] and 'catalogue.db' in state['error']


# ---------- Codex review of the redaction pass ----------

def test_p1_redaction_runs_once_over_the_original_text(tmp_path, monkeypatch):
    from pathlib import Path
    from brickwork.store4.errors import Store4Error, public_text
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    relative = Path('data')                                                          # the default relative data path
    message = 'no file at data/bricklink-lists/private/items.xml; see the data in data/brickwork.db'
    out = public_text(Store4Error(message), known=[relative, relative / 'brickwork.db'])
    assert 'private' not in out and 'the the' not in out and 'folder folder' not in out
    assert 'items.xml' in out and 'brickwork.db' in out and 'the data in' in out         # the word "data" in prose is left alone
    absolute = str(tmp_path / 'data' / 'bricklink-lists' / 'private' / 'items.xml')
    out = public_text(Store4Error(f'cannot read {absolute} (and {tmp_path}/data)'), known=[relative])
    assert 'private' not in out and str(tmp_path) not in out


def test_p2_every_branch_of_the_exception_chain_is_walked_for_sqlite():
    import sqlite3
    from brickwork.store4.errors import GENERIC, Store4Error, public_text
    try:
        try:
            raise sqlite3.OperationalError('no such table: meta')
        except sqlite3.Error:
            raise Store4Error('catalogue.db cannot be read: no such table: meta') from ValueError('bad value')   # cause: ValueError; context: SQLite
    except Store4Error as exc:
        assert isinstance(exc.__cause__, ValueError) and isinstance(exc.__context__, sqlite3.Error)
        assert public_text(exc) == GENERIC


def test_q1_exact_relative_known_paths_are_redacted_like_absolute_ones(tmp_path, monkeypatch):
    from pathlib import Path
    from brickwork.store4.errors import Store4Error, public_text
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data' / 'catalogue-src' / 'rebrickable').mkdir(parents=True)
    (tmp_path / 'data' / 'brickwork.db').write_text('')
    known = [Path('data'), Path('data/catalogue-src/rebrickable'), Path('data/brickwork.db')]
    out = public_text(Store4Error('another download is running on data/catalogue-src/rebrickable (busy); the file data/brickwork.db is fine'), known=known)
    assert 'catalogue-src' not in out and 'rebrickable' not in out and 'data/' not in out
    assert 'the data folder (busy)' in out and 'brickwork.db is fine' in out
    assert public_text(Store4Error('all the data is kept'), known=known) == 'all the data is kept'          # prose is still left alone
