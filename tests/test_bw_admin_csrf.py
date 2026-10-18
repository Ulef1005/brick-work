"""Admin POST protection uses the migrated store and existing shell token."""
from io import BytesIO
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin
from brickwork.core.sources.bricklink import BrickLink
from brickwork.web import admin_ops
from tests.importer.test_importer import legacy
from tests.test_bw_admin import migrated_bw, reset_shell_metadata_after_test
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps


@pytest.mark.parametrize(('page','action'), [
    ('catalogues','load'), ('catalogues','colours'), ('catalogues','source'),
    ('values','add'), ('values','rename'), ('values','delete'),
    ('settings',''), ('settings','pictures'),
    ('unresolved','pick'), ('unresolved','leave'), ('unresolved','images'),
    ('refresh',''), ('jobs','resume'), ('jobs','retry'),
    ('instructions','upload'), ('instructions','rename'),
])
@pytest.mark.parametrize('token', [None, 'wrong'])
def test_admin_csrf_rejects_before_dispatch_without_writes(app, migrated_bw, monkeypatch, page, action, token):
    client = logged_in(app)
    client.get('/manage/' + page)
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid CSRF reached an admin write or worker')
    monkeypatch.setattr(admin_ops, 'tools_write', forbidden)
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', forbidden)
    with sqlite3.connect(migrated_bw) as db:
        before = list(db.iterdump())
    data = {'action':action}
    if token is not None:
        data['csrf_token'] = token
    response = client.post('/manage/' + page, data=data)
    assert response.status_code == 400
    assert b'Invalid CSRF token' in response.data
    with sqlite3.connect(migrated_bw) as db:
        assert list(db.iterdump()) == before  # Includes every events and budget row.


@pytest.mark.parametrize('page', ['catalogues','values','settings','unresolved','refresh','jobs','instructions'])
def test_every_rendered_admin_post_form_has_one_token(app, migrated_bw, page):
    # Populate both instruction and job states so conditional forms are covered.
    with admin.database(migrated_bw) as db:
        number = db.execute("SELECT item_no FROM items WHERE item_type='S' LIMIT 1").fetchone()[0]
        admin.instruction_upload(db, migrated_bw.parent, 'S', number, 'Booklet', b'%PDF-1.4\nfixture')
        from brickwork.core.pipeline import Pipeline
        job = Pipeline(db).queue_steps('S', number, ('market_price',), sources=['bricklink'])
        with db:
            db.execute("UPDATE import_steps SET state='failed' WHERE job_id=?", (job,))
            db.execute("UPDATE jobs SET state='failed' WHERE id=?", (job,))
        resume = Pipeline(db).queue_steps('S', number, ('pictures',), sources=['bricklink'])
        with db:
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (resume,))
    client = logged_in(app)
    response = client.get('/manage/' + page)
    assert response.status_code == 200
    soup = BeautifulSoup(response.data, 'html.parser')
    forms = soup.select('form[method="post"]')
    assert forms
    with client.session_transaction() as session:
        token = session['bw_add_csrf']
    for form in forms:
        fields = form.select('input[name="csrf_token"]')
        assert len(fields) == 1
        assert fields[0]['value'] == token
    if page == 'jobs':
        assert soup.select_one('[data-bw-jobs]')['data-csrf'] == token
        assert any(form.select_one('[name="step"]') for form in forms)
        assert any(form.select_one('[name="action"][value="resume"]') for form in forms)


@pytest.mark.parametrize('action', ['source','colours','load','value','settings','instruction'])
def test_valid_admin_csrf_allows_audited_write(app, migrated_bw, monkeypatch, action):
    def colours(self, path, params=None, normalize=None, job_id=None):
        assert path == '/colors'
        with self.db:
            return normalize([dict(color_id=11,color_name='Blue',color_type='Solid',color_code='ABCDEF')])
    monkeypatch.setattr(BrickLink, 'call', colours)
    original = admin_ops.tools_write
    # Catalogue filesystem loading has separate coverage; colour loading stays real.
    monkeypatch.setattr(admin_ops, 'tools_write', lambda op, **kw: None if op == 'catalogue' else original(op, **kw))
    page, data = 'catalogues', {'action':action}
    if action == 'source':
        data.update(source='bricklink', enabled='yes')
    elif action == 'value':
        page, data = 'values', dict(action='add', group='owners', name='CSRF owner')
    elif action == 'settings':
        page, data = 'settings', {'retail_country':'US'}
        with admin.database(migrated_bw) as db:
            data.update({'priority:' + step + ':' + kind: ','.join(sources)
                         for step, kinds in admin.settings(db)['priority'].items() for kind, sources in kinds.items()})
    elif action == 'instruction':
        with admin.database(migrated_bw) as db:
            number = db.execute("SELECT item_no FROM items WHERE item_type='S' LIMIT 1").fetchone()[0]
        page, data = 'instructions', dict(action='upload', item_type='S', item_no=number,
                                         label='Booklet', file=(BytesIO(b'%PDF-1.4\nfixture'), 'booklet.pdf'))
    client = logged_in(app)
    client.get('/manage/' + page)
    with client.session_transaction() as session:
        data['csrf_token'] = session['bw_add_csrf']
    with admin.database(migrated_bw) as db:
        before = db.execute('SELECT count(*) FROM events').fetchone()[0]
    response = client.post('/manage/' + page, data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Saved' in response.data
    with admin.database(migrated_bw) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] > before
        assert db.execute('SELECT via FROM events ORDER BY id DESC LIMIT 1').fetchone()[0] == 'app'
