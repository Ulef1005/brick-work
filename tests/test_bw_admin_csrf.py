"""Admin POST protection on a 4.0 collection (M.8i part 1, issue #110): every write form carries the shell's CSRF token and no write is reached
without it. The identity admin's own CSRF cases (Unresolved items) are in `test_bw_admin_identity.py`."""
from io import BytesIO
import sqlite3

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin
from brickwork.web import admin_ops
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401  (the fixtures)


def dump(path):
    with sqlite3.connect(path) as db:
        return list(db.iterdump())


@pytest.mark.parametrize(('page', 'action'), [
    ('catalogues', 'source'),
    ('values', 'add'), ('values', 'rename'), ('values', 'delete'),
    ('settings', ''), ('settings', 'pictures'), ('settings', 'undo'), ('settings', 'rate'),
    ('refresh', ''), ('jobs', 'resume'), ('jobs', 'retry'),
    ('instructions', 'upload'), ('instructions', 'rename'), ('instructions', 'fetch_missing'),
    ('database', 'check'),
])
@pytest.mark.parametrize('token', [None, 'wrong'])
def test_admin_csrf_rejects_before_dispatch_without_writes(client, world, pair, monkeypatch, page, action, token):
    client.get('/manage/' + page)

    def forbidden(*args, **kwargs):
        pytest.fail('Invalid CSRF reached an admin write or worker')
    monkeypatch.setattr(admin_ops, 'tools_write', forbidden)
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', forbidden)
    before = dump(pair)
    data = {'action': action}
    if token is not None:
        data['csrf_token'] = token
    response = client.post('/manage/' + page, data=data)
    assert response.status_code == 400
    assert b'Invalid CSRF token' in response.data
    assert dump(pair) == before                                                         # includes every event and budget row


@pytest.mark.parametrize('page', ['catalogues', 'values', 'settings', 'refresh', 'jobs', 'instructions', 'database'])
def test_every_rendered_admin_post_form_has_one_token(client, coll, world, pair, page):
    # Populate both instruction and job states so conditional forms are covered.
    from brickwork.core.pipeline import Pipeline
    from brickwork.core.transaction import transaction
    db = coll.db
    admin.value_write(db, 'owners', 'add', name='Ulf')
    with transaction(db):
        failed = Pipeline(db).queue_steps(world.keep, ('market_price',), via='app')
    db.execute("UPDATE job_step SET state='failed',error='boom',error_code='source_error' WHERE job_id=?", (failed,))
    db.execute("UPDATE job SET state='failed' WHERE id=?", (failed,))
    with transaction(db):
        resume = Pipeline(db).queue_steps(world.gate, ('pictures',), via='app')
    db.execute("UPDATE job SET state='running' WHERE id=?", (resume,))
    db.commit()
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


@pytest.mark.parametrize('action', ['source', 'value', 'settings', 'instruction', 'rate'])
def test_valid_admin_csrf_allows_audited_write(client, coll, world, pair, action):
    admin.seed_freshness(coll.db)
    page, data = 'catalogues', {'action': action}
    if action == 'source':
        data.update(source='bricklink', enabled='')
    elif action == 'value':
        page, data = 'values', dict(action='add', group='owners', name='CSRF owner')
    elif action == 'settings':
        page, data = 'settings', {'retail_country': 'US'}
        data.update({'priority:' + step + ':' + kind: ','.join(sources) for step, kinds in admin.settings(coll.db)['priority'].items() for kind, sources in kinds.items()})
    elif action == 'instruction':
        page, data = 'instructions', dict(action='upload', item_type='S', item_no='1000-1', label='Booklet', file=(BytesIO(b'%PDF-1.4\nfixture'), 'booklet.pdf'))
    elif action == 'rate':
        page, data = 'settings', dict(action='rate', currency='USD', per_eur='1.17')
    client.get('/manage/' + page)
    with client.session_transaction() as session:
        data['csrf_token'] = session['bw_add_csrf']
    before = coll.db.execute('SELECT count(*) FROM event').fetchone()[0]
    response = client.post('/manage/' + page, data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Saved' in response.data or b'Rate saved' in response.data
    assert coll.db.execute('SELECT count(*) FROM event').fetchone()[0] > before
    assert coll.db.execute('SELECT via FROM event ORDER BY id DESC LIMIT 1').fetchone()[0] == 'app'
