"""Tools & Admin on the 4.0 store (M.8i part 1, issue #110): the routes and their data, values with Undo, settings with Undo, the stale-price
refresh, the instruction files and the Identify history. Invented data only, no network.

The identity admin that used to share this file (Unresolved figures, resolving a match, the images queue) is part 2 of M.8i and moved to
`tests/test_bw_admin_identity.py`."""
from contextlib import closing
import io
import json
import re
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, ledger, undo
from brickwork.core.connect import connect
from brickwork.web import admin_ops
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)

PAGES = ['tools', 'catalogues', 'jobs', 'refresh', 'statistics', 'values', 'database', 'settings', 'appearance', 'history', 'instructions', 'about']


def token(client):
    return csrf(client)


def post(client, page, **data):
    return client.post('/manage/' + page, data={'csrf_token': token(client), **data}, follow_redirects=True)


def seed(coll):
    """The freshness rules a fresh collection gets from `brickwork setup`."""
    admin.seed_freshness(coll.db)


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv('BW_BRICKSET_API_KEY', 'private-fixture-key')


@pytest.mark.parametrize('page', PAGES)
def test_routes_in_shell_no_keys(client, world, keyed, page):
    result = client.get('/manage/' + page)
    assert result.status_code == 200
    html = result.get_data(as_text=True)
    assert 'data-web-ui="toni"' in html and 'Tools &amp; Admin' in html
    assert 'private-fixture-key' not in html
    assert result.headers['Cache-Control'] == 'no-store'


def test_unresolved_figures_wait_for_part_two(client, world):
    result = client.get('/manage/unresolved')
    assert result.status_code == 503 and 'M.8i part 2' in result.get_data(as_text=True)
    assert client.post('/manage/unresolved', data={'csrf_token': token(client), 'action': 'leave'}).status_code == 503
    assert '/manage/unresolved' not in client.get('/manage/tools').get_data(as_text=True)


def test_value_audit_and_rollback(coll):
    db = coll.db
    admin.value_write(db, 'tags', 'add', name='Display')
    row = admin.value_rows(db, 'tags')[0]
    assert row['name'] == 'Display' and row['count'] == 0 and row['references'][0][0] == 'copy_flag'
    assert tuple(db.execute('SELECT via,entity_kind,field FROM event ORDER BY id DESC').fetchone()) == ('app', 'collection', 'save')
    db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON event BEGIN SELECT RAISE(ABORT,'no'); END")
    with pytest.raises(sqlite3.IntegrityError):
        admin.value_write(db, 'tags', 'rename', identifier=row['id'], name='Changed')
    assert admin.value_rows(db, 'tags')[0]['name'] == 'Display'


def test_value_changes_undo_and_system_values_stay(coll, world):
    db = coll.db
    event = admin.value_write(db, 'owners', 'add', name='Ulf')
    owner = admin.value_rows(db, 'owners')[0]
    assert owner['name'] == 'Ulf'
    rename = admin.value_write(db, 'owners', 'rename', identifier=owner['id'], name='Sandra')
    assert admin.value_rows(db, 'owners')[0]['name'] == 'Sandra'
    assert undo.undo_event(db, rename)['already_undone'] is False
    assert admin.value_rows(db, 'owners')[0]['name'] == 'Ulf'
    with pytest.raises(ValueError, match='Confirm'):
        admin.value_write(db, 'owners', 'delete', identifier=owner['id'])
    gone = admin.value_write(db, 'owners', 'delete', identifier=owner['id'], confirmed=True)
    assert admin.value_rows(db, 'owners') == []
    undo.undo_event(db, gone)
    assert [r['name'] for r in admin.value_rows(db, 'owners')] == ['Ulf']
    undo.undo_event(db, event)                                                        # the creation is archived, never deleted
    assert admin.value_rows(db, 'owners') == [] and db.execute("SELECT count(*) FROM flag WHERE name='Ulf'").fetchone()[0] == 1
    # A flag is counted by the copies, loose stock and wishes that carry it.
    tag = next(r for r in admin.value_rows(db, 'tags') if r['name'] == 'collection')
    assert tag['count'] == 1
    db.execute("UPDATE flag SET system=1 WHERE name='collection'")
    with pytest.raises(ValueError, match='Brick Work uses this value itself'):
        admin.value_write(db, 'tags', 'rename', identifier=tag['id'], name='x')
    with pytest.raises(ValueError, match='no longer available'):
        admin.value_write(db, 'tags', 'rename', identifier=owner['id'], name='x')      # wrong group: an owner is no tag


def test_places_are_values_too(coll, world):
    db = coll.db
    place = next(r for r in admin.value_rows(db, 'purchase-places') if r['name'] == 'Shop')
    assert place['count'] == 1                                                         # copy A
    admin.value_write(db, 'purchase-places', 'add', name='Flea market')
    assert [r['name'] for r in admin.value_rows(db, 'purchase-places')] == ['Flea market', 'Shop']


def test_settings_save_is_one_event_and_undo_puts_back_what_was_there(coll):
    db = coll.db
    seed(coll)
    before = [tuple(r) for r in db.execute('SELECT * FROM setting ORDER BY key')], [tuple(r) for r in db.execute('SELECT * FROM source_freshness ORDER BY source,kind')]
    config = admin.settings(db)
    assert config['retail_country'] == 'DE' and config['priority']['pictures']['part'] == ['rebrickable_dump', 'bricklink', 'rebrickable_api']
    assert admin.save_settings(db, 'DE', config['priority'], [('bricklink', 'prices', '30')]) is None      # nothing differs: nothing written
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='settings'").fetchone()[0] == 0
    priority = {**config['priority'], 'pictures': {'part': ['bricklink'], '*': ['bricklink', 'rebrickable_dump']}}
    event = admin.save_settings(db, 'US', priority, [('bricklink', 'prices', '5'), ('bricklink', 'pictures', '')])
    assert tuple(db.execute("SELECT via,entity_kind,field FROM event WHERE id=?", (event,)).fetchone()) == ('app', 'settings', 'save')
    saved = admin.settings(db)
    assert saved['retail_country'] == 'US' and saved['priority']['pictures']['part'] == ['bricklink']
    assert {(r['source'], r['kind']): r['max_age_days'] for r in saved['freshness']}[('bricklink', 'prices')] == 5
    result = undo.undo_event(db, event)
    assert result['already_undone'] is False
    after = [tuple(r) for r in db.execute('SELECT * FROM setting ORDER BY key')], [tuple(r) for r in db.execute('SELECT * FROM source_freshness ORDER BY source,kind')]
    assert after == before                                                              # a setting never stored comes back absent
    assert undo.undo_event(db, event)['already_undone'] is True


def test_a_picture_order_the_migration_left_as_3_3_wrote_it_is_shown_as_the_jobs_read_it(coll):
    db = coll.db
    seed(coll)
    coll.setting('source_priority', json.dumps({'pictures': {'*': ['bricklink', 'rebrickable'], 'part': ['rebrickable', 'bricklink']}}))
    config = admin.settings(db)
    assert config['priority']['pictures'] == {'*': ['bricklink', 'rebrickable_dump', 'rebrickable_api'], 'part': ['rebrickable_dump', 'rebrickable_api', 'bricklink']}
    assert config['priority']['metadata'] == {'set': ['brickset']}              # the steps the stored value does not name keep the defaults
    from brickwork.core import pictures
    assert pictures.order(db, 'part') == ['rebrickable_dump', 'rebrickable_api', 'bricklink']
    assert admin.save_settings(db, 'DE', config['priority'], []) is None         # saving what the page shows changes nothing stored
    assert json.loads(db.execute("SELECT value FROM setting WHERE key='source_priority'").fetchone()[0])['pictures']['part'] == ['rebrickable', 'bricklink']


def test_settings_undo_is_refused_after_a_later_change(coll):
    db = coll.db
    seed(coll)
    config = admin.settings(db)
    first = admin.save_settings(db, 'US', config['priority'], [])
    admin.save_settings(db, 'UK', config['priority'], [])
    with pytest.raises(ValueError, match='undo the later save first'):
        undo.undo_event(db, first)
    assert admin.settings(db)['retail_country'] == 'UK'


def test_settings_reject_what_does_not_fit_and_write_nothing(coll):
    db = coll.db
    seed(coll)
    config = admin.settings(db)
    with pytest.raises(ValueError):
        admin.save_settings(db, 'US', config['priority'], [('bricklink', 'prices', '-1')])
    assert admin.settings(db)['retail_country'] == 'DE'
    with pytest.raises(ValueError, match='supported retail country'):
        admin.save_settings(db, 'XX', config['priority'], [])
    with pytest.raises(ValueError, match='Unknown freshness rule'):
        admin.save_settings(db, 'US', config['priority'], [('bricklink', 'nonsense', '3')])
    with pytest.raises(ValueError, match='Unknown source'):
        admin.save_settings(db, 'US', {'pictures': {'*': ['nowhere']}}, [])
    with pytest.raises(ValueError):
        admin.save_settings(db, 'US', {'pictures': {'planet': ['bricklink']}}, [])
    assert db.execute("SELECT count(*) FROM event WHERE entity_kind='settings'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM setting WHERE key IN ('retail_country','source_priority')").fetchone()[0] == 0


def test_a_fresh_setup_seeds_the_freshness_rules_once(tmp_path, monkeypatch):
    from tests.app4 import make_pair
    path = make_pair(tmp_path)
    monkeypatch.setenv('BW_DB_PATH', str(path))
    assert admin_ops.setup()['setup'] == 'ok'
    with closing(connect(path)) as db:
        rules = {(r['source'], r['kind']): r['max_age_days'] for r in db.execute('SELECT * FROM source_freshness')}
        assert len(rules) == 15 and rules[('bricklink', 'prices')] == 30 and rules[('brickset', 'metadata')] == 365 and rules[('rebrickable', 'pictures')] is None
        db.execute("UPDATE source_freshness SET max_age_days=7 WHERE source='bricklink' AND kind='prices'")
        db.commit()
    admin_ops.setup()                                                                   # a second setup keeps the user's rules
    with closing(connect(path)) as db:
        assert db.execute("SELECT max_age_days FROM source_freshness WHERE source='bricklink' AND kind='prices'").fetchone()[0] == 7


def test_queue_refresh_queues_each_item_once(coll, world):
    db = coll.db
    stale = admin.stale_prices(db)
    wanted = {r['item_id'] for r in stale}
    queued = admin.queue_refresh(db, stale)
    assert len(queued) == len(wanted) and len(wanted) > 1
    job = admin.jobs(db)[0]
    assert job['steps'][0]['name'] == 'market_price' and job['steps'][0]['state'] == 'queued' and job['heading']
    assert db.execute("SELECT via FROM event WHERE field='queued' ORDER BY id DESC").fetchone()[0] == 'app'
    assert admin.queue_refresh(db, admin.stale_prices(db)) == []                       # every item has a live job now
    assert admin.count_jobs(db) == len(queued) == len(admin.jobs(db))


def test_write_routes_and_export(client, coll, world):
    assert post(client, 'values', group='owners', action='add', name='Ulf').status_code == 200
    assert [r['name'] for r in admin.value_rows(coll.db, 'owners')] == ['Ulf']
    response = client.get('/manage/database/export')
    assert response.status_code == 200 and response.data.startswith(b'SQLite format 3')
    with closing(sqlite3.connect(':memory:')) as snapshot:
        snapshot.deserialize(response.data)
        assert snapshot.execute("SELECT count(*) FROM event WHERE entity_kind='database' AND field='export' AND via='app'").fetchone()[0] == 1
        assert snapshot.execute('SELECT count(*) FROM copy').fetchone()[0] == 3
        assert snapshot.execute("SELECT count(*) FROM sqlite_master WHERE name IN ('inventory','bricklink_item','item_fts')").fetchone()[0] == 0     # the catalogue is its own file


def test_missing_store_is_visible(client, tmp_path, monkeypatch):
    path = tmp_path / 'elsewhere' / 'absent.db'
    monkeypatch.setenv('BW_DB_PATH', str(path))
    response = client.get('/manage/tools')
    assert 'database is not available' in response.get_data(as_text=True)
    assert not path.exists()


def test_admin_pages_open_before_a_catalogue_exists(tmp_path, monkeypatch):
    """Catalogues & keys is where the missing catalogue is named, so no admin page needs the catalogue to render."""
    from brickwork.app import setup_app
    from flask import Flask
    from tests.web_fixtures import ROOT, logged_in
    path = tmp_path / 'brickwork.db'
    monkeypatch.setenv('BW_DB_PATH', str(path))
    monkeypatch.setenv('BW_EMBEDDED_WORKER', '0')
    monkeypatch.setenv('BW_AUTHENTICATION_PASSWORD', 'synthetic-password')
    admin_ops.setup()
    assert not (tmp_path / 'catalogue.db').exists()
    app = Flask('nocat', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    setup_app(app)
    app.config.update(TESTING=True, SECRET_KEY='synthetic-session')
    client = logged_in(app)
    for page in ('tools', 'catalogues', 'settings', 'database', 'jobs', 'values', 'tokens'):
        response = client.get('/manage/' + page)
        assert response.status_code == 200 and 'database is not available' not in response.get_data(as_text=True), page
    html = client.get('/manage/catalogues').get_data(as_text=True)
    assert 'Not loaded' in html and 'catalogue download' in html and 'catalogue import' in html
    assert client.get('/manage/database/export').status_code == 200


def test_route_data_is_new_store(client, coll, world, keyed):
    assert '1 of 3 copies are incomplete' in client.get('/manage/statistics').get_data(as_text=True)
    assert 'Syn Castle Keep' in client.get('/manage/refresh').get_data(as_text=True)
    coll.sql("""INSERT INTO job(source,kind,state,error,via,created_at,updated_at) VALUES('brickset','item','failed','private-fixture-key','app',
                '2026-10-12T00:00:00.000Z','2026-10-12T00:00:00.000Z')""")
    html = client.get('/manage/catalogues').get_data(as_text=True)
    assert 'private-fixture-key' not in html and '[set]' in html


def test_catalogue_card_names_what_is_loaded_and_the_fix(client, coll, world):
    soup = BeautifulSoup(client.get('/manage/catalogues').data, 'html.parser')
    card = soup.find(id='catalogues')
    text = ' '.join(card.get_text(' ').split())
    assert 'Loaded' in text and '18 items' in text and 'BrickLink item lists not loaded' in text
    # The fixture catalogue is activated but never reconciled: the page says so and names the command.
    fix = card.select_one('[data-catalogue-fix]').get_text(' ')
    assert 'catalogue reconcile' in fix and 'has not been reconciled' in fix and 'not activated' not in fix
    coll.sql("UPDATE catalogue_build SET reconciled_at='2026-10-27T10:00:00.000Z'")
    card = BeautifulSoup(client.get('/manage/catalogues').data, 'html.parser').find(id='catalogues')
    assert not card.select_one('[data-catalogue-fix]') and 'catalogue download' in card.select_one('[data-catalogue-update]').get_text()
    assert 'Last reconciled' in card.get_text()
    coll.db.execute('PRAGMA foreign_keys=OFF')                                          # an activation that never happened
    coll.sql('DELETE FROM catalogue_build')
    banner = BeautifulSoup(client.get('/manage/catalogues').data, 'html.parser').select('.bk-banner')
    assert any('not activated' in b.get_text() for b in banner)
    card = BeautifulSoup(client.get('/manage/catalogues').data, 'html.parser').find(id='catalogues')
    assert 'not activated in your collection yet' in card.select_one('[data-catalogue-fix]').get_text(' ') and 'Activate the catalogue' in card.get_text(' ')


def test_a_newer_catalogue_build_the_collection_has_not_activated_names_the_fix(client, coll, world, pair):
    # Codex review (M.8i part 1): an update that published a build but stopped before activation must not read as "Loaded".
    coll.sql("UPDATE catalogue_build SET reconciled_at='2026-10-27T10:00:00.000Z'")
    assert not BeautifulSoup(client.get('/manage/catalogues').data, 'html.parser').find(id='catalogues').select_one('[data-catalogue-fix]')
    from pathlib import Path
    with closing(sqlite3.connect(Path(pair).parent / 'catalogue.db')) as catalogue:          # an update that built but never activated
        catalogue.execute('CREATE TEMP TABLE newer AS SELECT * FROM build WHERE id=(SELECT max(id) FROM build)')
        catalogue.execute('UPDATE newer SET id=id+1')
        catalogue.execute('INSERT INTO build SELECT * FROM newer')
        catalogue.commit()
    card = BeautifulSoup(client.get('/manage/catalogues').data, 'html.parser').find(id='catalogues')
    assert 'Activate the catalogue' in card.get_text(' ') and 'catalogue reconcile' in card.select_one('[data-catalogue-fix]').get_text(' ')


def test_jobs_retry_and_resume_take_a_fetch_job_to_its_own_runner(client, coll, world):
    # Codex review (M.8i part 1): a failed Fetch from Rebrickable is retried from Jobs, as from Add.
    from brickwork.store4 import jobs as fetch_jobs
    job = fetch_jobs.queue(coll.db, 'rebrickable_set', payload='9999-1', via='app')
    coll.sql("UPDATE job SET state='failed', error='Rebrickable key is missing', attempts=3 WHERE id=?", (job,))
    post(client, 'jobs', job=str(job), step='fetch')
    assert tuple(coll.db.execute('SELECT state, error, attempts FROM job WHERE id=?', (job,)).fetchone()) == ('queued', None, 0)
    coll.sql("UPDATE job SET state='waiting_for_budget' WHERE id=?", (job,))
    assert post(client, 'jobs', job=str(job), step='fetch', action='resume').status_code == 200
    assert 'Job is not interrupted' not in client.get('/manage/jobs').get_data(as_text=True)

def test_storage_delete_requires_empty_location_and_archives(coll, world):
    db = coll.db
    admin.value_write(db, 'storages', 'add', name='Box one')
    identifier = next(r['id'] for r in admin.value_rows(db, 'storages') if r['name'] == 'Box one')
    db.execute('UPDATE copy SET storage_id=? WHERE id=?', (identifier, world.copy_b))
    db.commit()
    assert next(r for r in admin.value_rows(db, 'storages') if r['id'] == identifier)['count'] == 1
    with pytest.raises(ValueError):
        admin.value_write(db, 'storages', 'delete', identifier=identifier)
    assert db.execute('SELECT storage_id FROM copy WHERE id=?', (world.copy_b,)).fetchone()[0] == identifier
    with pytest.raises(ValueError, match='Move the items'):
        admin.value_write(db, 'storages', 'delete', identifier=identifier, confirmed=True)
    ledger.move(db, None, [dict(entity='copy', id=world.copy_b)])
    event = admin.value_write(db, 'storages', 'delete', identifier=identifier, confirmed=True)
    assert db.execute('SELECT archived_at FROM storage WHERE id=?', (identifier,)).fetchone()[0]
    ledger.undo(db, event)
    assert db.execute('SELECT archived_at FROM storage WHERE id=?', (identifier,)).fetchone()[0] is None
    assert db.execute('SELECT storage_id FROM copy WHERE id=?', (world.copy_b,)).fetchone()[0] is None


# ---------- instruction files ----------

def upload(client, number, label='Booklet one', *, kind='S', content=b'%PDF-1.4\nsynthetic fixture'):
    return client.post('/manage/instructions', data={'csrf_token': token(client), 'action': 'upload', 'item_type': kind, 'item_no': number,
                                                   'label': label, 'file': (io.BytesIO(content), 'booklet.pdf')})


def test_instruction_upload_rename_download_and_rollback(client, coll, world, pair):
    result = upload(client, '1000-1')
    assert result.status_code == 302
    row = coll.db.execute('SELECT * FROM instruction_file').fetchone()
    assert row['item_id'] == world.keep and row['label'] == 'Booklet one' and row['path'].startswith('data/instructions/')
    assert coll.db.execute("SELECT via FROM event WHERE field='attach'").fetchone()[0] == 'app'
    admin.instruction_rename(coll.db, row['id'], 'Booklet two')
    event = coll.db.execute("SELECT old_value,new_value FROM event WHERE field='label'").fetchone()
    assert tuple(event) == ('Booklet one', 'Booklet two')
    assert client.get(f"/manage/instructions/{row['id']}/download").data == b'%PDF-1.4\nsynthetic fixture'
    coll.db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON event BEGIN SELECT RAISE(ABORT,'no'); END")
    with pytest.raises(sqlite3.IntegrityError):
        admin.instruction_upload(coll.db, pair.parent, 'S', '1000-1', 'Fail', b'%PDF-1.4\nnew fixture')
    assert coll.db.execute('SELECT count(*) FROM instruction_file').fetchone()[0] == 1
    assert len(list((pair.parent / 'data/instructions').glob('*.pdf'))) == 1


def test_instruction_upload_refuses_what_is_not_one_item_or_not_a_pdf(client, coll, world, pair):
    for number, kind, content in (('nonesuch', 'S', b'%PDF-1.4\nx'), ('1000-1', 'Z', b'%PDF-1.4\nx'), ('1000-1', 'S', b'not a pdf'), ('', 'S', b'%PDF-1.4\nx')):
        assert upload(client, number, kind=kind, content=content).status_code == 302
    assert coll.db.execute('SELECT count(*) FROM instruction_file').fetchone()[0] == 0
    assert not (pair.parent / 'data/instructions').exists() or not list((pair.parent / 'data/instructions').glob('*.pdf'))


def test_instruction_upload_names_a_catalogue_item_and_projects_it(client, coll, pair):
    """A set only the catalogue knows is joined to the collection by the upload, as any first reference is."""
    assert coll.db.execute("SELECT count(*) FROM item WHERE born_key='2070-1'").fetchone()[0] == 0
    assert upload(client, '2070-1').status_code == 302
    assert coll.db.execute("SELECT count(*) FROM item WHERE born_key='2070-1'").fetchone()[0] == 1
    assert coll.db.execute('SELECT count(*) FROM instruction_file').fetchone()[0] == 1


def test_history_presents_candidates_without_raw_json(client, coll, world):
    coll.db.execute("""INSERT INTO identification(id,created_at,has_thumb,candidates,missing_count) VALUES('identify','2026-10-12T00:00:00.000Z',0,?,0)""",
                    (json.dumps([{'id': 'candidate', 'type': 'minifig', 'score': 0.92, 'name': 'Candidate figure'}]),))
    coll.db.commit()
    html = client.get('/manage/history').get_data(as_text=True)
    assert 'Candidate figure' in html and '0.92 match' in html
    assert '<pre>' not in html


def test_history_names_candidates_by_item_and_shows_the_cached_picture(client, coll, world):
    coll.db.execute("INSERT INTO picture(item_id,color_id,source,kind,local_path,fetched_at) VALUES(?,NULL,'bricklink','photo','data/images/p.png','2026-10-01T00:00:00.000Z')", (world.figure,))
    coll.db.execute("INSERT INTO identification(id,created_at,has_thumb,candidates,missing_count) VALUES('i1','2026-10-12T10:00:00.000Z',0,?,1)",
                    (json.dumps([{'item_id': world.figure, 'score': 0.5}, {'item_id': world.brick, 'name': 'Brick named here', 'score': 0.4}, 'junk', {'nothing': 1}]),))
    coll.db.commit()
    row, = admin.history(coll.db)
    figure, brick = row['candidates']
    assert figure['item_id'] == world.figure and figure['item_no'] == 'fig-000004' and figure['name'] and figure['image'] is not None
    assert brick['item_no'] == '3001' and brick['name'] == 'Brick named here' and brick['image'] is None
    assert 'fig-000004' in client.get('/manage/history').get_data(as_text=True)


def test_history_dates_are_short_stamps_not_iso(client, coll, world):
    coll.db.execute("INSERT INTO identification(id,created_at,has_thumb,candidates,missing_count) VALUES('i2','2026-10-04T14:41:00.400Z',0,'[]',0)")
    coll.db.commit()
    html = client.get('/manage/history').get_data(as_text=True)
    visible = BeautifulSoup(html, 'html.parser').select_one('main').get_text(' ')
    assert not re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', visible)
    assert '4 Oct · 14:41' in html or '04 Oct · 14:41' in html


def test_stale_freshness_and_archives(coll, world):
    from datetime import timedelta
    from brickwork.core.sources.base import now
    seed(coll)
    db = coll.db
    keep = lambda: [r for r in admin.stale_prices(db) if r['item_id'] == world.keep]
    # The set is held used (copy A) and new (copy B); the world prices only the used one, on 2026-10-26.
    assert [r['condition'] for r in keep()] == ['new']
    two_days = (now() - timedelta(days=2)).isoformat()
    coll.price(world.keep, '30.00', condition='used', observed=two_days)
    coll.price(world.keep, '40.00', condition='new', observed=two_days)
    assert keep() == []                                                                 # fresh within the 30 days of the seeded rule
    db.execute("UPDATE source_freshness SET max_age_days=0 WHERE source='bricklink' AND kind='prices'")             # nothing is ever fresh enough
    assert sorted(r['condition'] for r in keep()) == ['new', 'used']
    db.execute("UPDATE copy SET archived_at='2026-10-12T00:00:00.000Z'")
    assert keep() == []


def test_refresh_pictures_queues_one_job_per_item_and_checks_the_estimate(client, coll, world):
    from brickwork.core import pictures
    matrix = pictures.matrix(coll.db)
    sets = matrix['set']['missing']
    assert sets['count'] == 3 and sets['unresolved'] == 0 and matrix['gear']['all']['unresolved'] == 1 and matrix['?']['all'] == dict(count=0, unresolved=0, unknown_colour=0)
    soup = BeautifulSoup(client.get('/manage/settings').data, 'html.parser')
    assert json.loads(soup.select_one('[data-picture-counts]').string)['set']['all']['count'] == 3
    assert {i['value'] for i in soup.select('input[name=types]')} >= {'set', 'part', 'minifigure'}
    # A stale estimate is refused whole; nothing is queued.
    response = post(client, 'settings', action='pictures', scope='missing', types=['set'], expected_count='99')
    assert 'Picture refresh · 3 items now match, not 99' in response.get_data(as_text=True)
    assert coll.db.execute('SELECT count(*) FROM job').fetchone()[0] == 0
    response = post(client, 'settings', action='pictures', scope='missing', types=['set'], expected_count='3')
    assert 'picture jobs queued for 3 items' in response.get_data(as_text=True)
    jobs = coll.db.execute("SELECT j.id,s.name FROM job j JOIN job_step s ON s.job_id=j.id WHERE j.kind='item'").fetchall()
    assert len(jobs) == 3 and {j['name'] for j in jobs} == {'pictures'}
    post(client, 'settings', action='pictures', scope='missing', types=['set'])
    assert coll.db.execute('SELECT count(*) FROM job').fetchone()[0] == 3          # each item has a live pictures job: none is queued twice
    assert post(client, 'settings', action='pictures', scope='all', types=[]).status_code == 200
    assert coll.db.execute('SELECT count(*) FROM job').fetchone()[0] == 3


def test_post_rejects_cross_origin_and_auth(app4, client, world):
    assert app4.test_client().post('/manage/values', data={}).status_code == 302
    assert client.post('/manage/values', headers={'Origin': 'https://other.invalid'}, data={}).status_code == 403


def test_phone_tap_targets_on_complete_sets_and_used_in():
    from pathlib import Path
    planning = Path('static/web/toni/bw-planning.css').read_text()
    collection = Path('static/web/toni/bw-collection.css').read_text()
    assert '.bp-complete-sets .bp-select,#bw-planning .bp-complete-sets [data-bp-pin] { min-height:44px' in planning
    assert '.bc-used-identity a { min-height:44px' in collection


def test_wishlist_price_refresh_preserves_colour_and_condition(coll, world):
    """The stale list names each wished (colour, condition) of a part and the pipeline asks for the colours held or wanted."""
    from brickwork.core import items
    from brickwork.core.sources.base import now
    db = coll.db
    part = coll.item('parts', '3023')
    black, red = coll.colour('0'), coll.colour('4')
    coll.add_wish(part, colour=black, condition='used', quantity=1)
    coll.add_wish(part, colour=red, condition='new', quantity=1)
    coll.price(part, '1.00', colour=black, condition='used', observed=now().isoformat())
    stale = [r for r in admin.stale_prices(db) if r['item_id'] == part]
    assert {(r['color_id'], r['condition']) for r in stale} >= {(red, 'new')} and (black, 'used') not in {(r['color_id'], r['condition']) for r in stale}
    assert {black, red} <= set(items.colours_held(db, part))
    coll.price(part, '1.00', colour=red, condition='new', observed=now().isoformat())
    assert not [r for r in admin.stale_prices(db) if r['item_id'] == part and r['color_id'] in (black, red)]


@pytest.mark.parametrize(('page', 'form', 'operation', 'label'), [
    ('catalogues', {'action': 'source', 'source': 'bricklink'}, 'source', 'Source toggle'),
    ('refresh', {}, 'refresh', 'Price refresh'),
])
def test_source_failure_names_action(client, world, monkeypatch, page, form, operation, label):
    from brickwork.core.sources.base import SourceError

    def fail(actual, **kwargs):
        assert actual == operation
        raise SourceError('Source is unavailable')
    monkeypatch.setattr(admin_ops, 'tools_write', fail)
    response = post(client, page, **form)
    assert label + ' · Source is unavailable' in response.get_data(as_text=True)


@pytest.mark.parametrize('error', [ValueError, KeyError, TypeError])
def test_admin_internal_validation_message_stays_private(client, world, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error('private-internal-detail')
    monkeypatch.setattr(admin_ops, 'tools_write', fail)
    html = post(client, 'catalogues', action='source', source='bricklink').get_data(as_text=True)
    assert 'Nothing was saved. Check the values and try again.' in html
    assert 'private-internal-detail' not in html


def test_the_removed_catalogue_and_colour_loads_are_not_actions_any_more(client, coll, world):
    before = coll.db.execute('SELECT count(*) FROM event').fetchone()[0]
    for action in ('load', 'colours'):
        assert post(client, 'catalogues', action=action).status_code == 400
    assert coll.db.execute('SELECT count(*) FROM event').fetchone()[0] == before


# ---------- the Instruction files page (4.9e) ----------

def booklets(coll, *names, sets=()):
    """Local booklet items (numbered by BrickLink); a number in `sets` also gets the local set a PDF can be attached to (a PDF belongs to a set)."""
    ids = [coll.local('instructions', name, born_key=number) for number, name in names]
    for number in sets:
        coll.local('set', 'Set ' + number, born_key=number)
    return ids


def soup_of(client, path='/manage/instructions'):
    return BeautifulSoup(client.get(path).get_data(as_text=True), 'html.parser')


def test_49e_instruction_files_list_every_booklet_identity(client, coll, pair):
    booklets(coll, ('b-1', 'Booklet one'), ('b-2', 'Booklet two'), ('b-3', 'Booklet three'), ('b-4', 'Booklet four'))
    html = client.get('/manage/instructions').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    assert soup.select_one('.bw-page-head h1').get_text() == '0 of 4 booklets have a PDF'
    rows = soup.select('[data-bw-rows] .bw-booklet')
    assert [r.select_one('.bw-booklet-no').get_text() for r in rows] == ['b-1', 'b-2', 'b-3', 'b-4']
    assert [r.select_one('.bw-booklet-name').get_text() for r in rows][0] == 'Booklet one'
    assert all(r.select_one('.bw-booklet-pill').get_text() == 'No PDF' for r in rows)
    assert 'No instruction files attached yet' not in html
    # w22, w23: no breadcrumb row and no helper paragraph.
    assert not soup.select('nav.breadcrumb, .breadcrumb')
    assert 'Coverage counts recorded booklet identities' not in html
    # w25, w26: Fetch missing above Upload a PDF; summary restyled past the disclosure chevron rules.
    actions = soup.select_one('.bw-instructions-actions')
    assert [e.get_text() for e in actions.select('button.bw-instructions-fetch, summary')] == ['Fetch missing', 'Upload a PDF']
    assert not actions.select('summary.button')


def test_49e_instruction_booklet_with_pdf_and_fetch_missing(client, coll, pair):
    one, two = booklets(coll, ('b-1', 'Booklet one'), ('b-2', 'Booklet two'), sets=('b-1',))
    assert upload(client, 'b-1', 'Booklet', kind='I').status_code == 302               # a booklet's PDF is attached to the set with its number
    soup = soup_of(client)
    assert soup.select_one('.bw-page-head h1').get_text() == '1 of 2 booklets have a PDF'
    pills = {r.select_one('.bw-booklet-no').get_text(): r.select_one('.bw-booklet-pill').get_text() for r in soup.select('.bw-booklet')}
    assert pills == {'b-1': 'PDF available', 'b-2': 'No PDF'}
    assert soup.select_one('.bw-booklet a.button').get_text() == 'Download PDF'
    # Fetch missing queues the identity step for booklets without a PDF only.
    assert post(client, 'instructions', action='fetch_missing').status_code == 200
    jobs = [tuple(r) for r in coll.db.execute("SELECT item_id,state FROM job WHERE source='import'")]
    assert jobs == [(two, 'queued')]
    assert [r[0] for r in coll.db.execute('SELECT name FROM job_step')] == ['identity']
    assert coll.db.execute('SELECT count(*) FROM instruction_file').fetchone()[0] == 1
    assert coll.db.execute('SELECT s.born_key FROM instruction_file f JOIN item s ON s.id=f.item_id').fetchone()[0] == 'b-1'


def test_49e_instruction_page_query_count_is_flat(coll, pair, monkeypatch):
    booklets(coll, *[(f'q-{n:03}', f'Booklet {n}') for n in range(300)])
    statements = []
    original = admin.connect

    def traced(*args, **kwargs):
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db
    monkeypatch.setattr(admin, 'connect', traced)
    monkeypatch.setenv('BW_DB_PATH', str(pair))
    data = admin_ops.tools_read('instructions', 'owners')
    assert data['coverage']['total'] == 300
    assert len([s for s in statements if s.lstrip().upper().startswith('SELECT')]) < 10


def test_49e_instruction_css_values():
    css = open('static/web/toni/bw-admin.css').read()
    for value in ['.bw-booklet-row{display:flex;align-items:center;gap:12px;min-height:80px}',
                  '.bw-booklet-name{font:600 15px/20px var(--tw-font)}',
                  '.bw-booklet-no{font:400 12px/16px var(--tw-mono);color:var(--tw-text-muted)}',
                  'height:24px;padding:0 10px;border-radius:999px;background:var(--tw-success-soft);font:500 12px var(--tw-font)',
                  'height:56px;min-height:56px;padding:0 16px;border-radius:10px;border:.5px solid var(--tw-accent)']:
        assert value in css


def test_49e_fetch_missing_skips_unidentified_booklets_and_flashes_info(client, coll, pair):
    good = booklets(coll, ('good-1', 'Good one'), ('good-2', 'Good two'))
    coll.local('instructions', 'Nameless booklet')                                      # no number from any provider
    assert client.post('/manage/instructions', data={'csrf_token': token(client), 'action': 'fetch_missing'}).status_code == 302
    assert sorted(r[0] for r in coll.db.execute("SELECT item_id FROM job WHERE source='import'")) == sorted(good)
    with client.session_transaction() as session:
        category, message = session['_flashes'][-1]
    assert category == 'info'
    assert message.startswith('Queued 2 identity refreshes, 1 skipped (no number: ')
    assert 'no PDFs are downloaded' in message


def test_49e_fetch_missing_refused_when_read_only(app4, client, coll, pair):
    booklets(coll, ('b-1', 'One'))
    csrf_token = token(client)
    app4.config['BW_READ_ONLY'] = True
    try:
        assert client.post('/manage/instructions', data={'csrf_token': csrf_token, 'action': 'fetch_missing'}).status_code == 403
    finally:
        app4.config['BW_READ_ONLY'] = False
    assert coll.db.execute("SELECT count(*) FROM job WHERE source='import'").fetchone()[0] == 0


def test_49e_zero_booklets_shows_no_fetch_button_and_search_finds_fallback_name(client, coll, pair):
    soup = soup_of(client)
    assert soup.select_one('.bw-page-head h1').get_text() == '0 of 0 booklets have a PDF'
    assert not soup.select('.bw-instructions-fetch')
    coll.sql("""INSERT INTO item(id,origin,kind,kind_source,name,born_provider,born_namespace,born_key,created_at,updated_at)
                VALUES(1000000900,'local','instructions','bricklink','','bricklink','I','nameless','2026-10-26T00:00:00.000Z','2026-10-26T00:00:00.000Z')""")
    row = soup_of(client).select_one('.bw-booklet')
    assert row.select_one('.bw-booklet-name').get_text() == 'Instructions' and row['data-name'] == 'nameless Instructions'


def test_49e_booklet_picture_ignores_own_photos(client, coll, pair):
    one, = booklets(coll, ('b-1', 'One'))
    coll.sql("INSERT INTO picture(item_id,source,kind,local_path,fetched_at) VALUES(?,'bricklink','booklet','data/images/cat.jpg','2026-01-01T00:00:00.000Z')", (one,))
    catalogue = coll.db.execute('SELECT max(id) FROM picture').fetchone()[0]
    copy = coll.add_copy('1000-1')
    coll.sql("""INSERT INTO photo(id,item_id,copy_id,local_path,created_at) VALUES('0a1b2c3d4e5f60718293a4b5c6d7e8f9',?,?,'data/images/own/own.jpg','2026-02-01T00:00:00.000Z')""",
             (one, copy))
    img = soup_of(client).select_one('.bw-booklet img')
    assert img['src'].split('?')[0].endswith(f'/{catalogue}') and img['loading'] == 'lazy' and img.has_attr('data-bw-fallback')
