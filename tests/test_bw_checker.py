"""Checker routes and reversible receipts against an actual migrated v3 fixture."""
import json
import sqlite3
import uuid

import pytest

from brickwork.core import checker, admin
from brickwork.core.importer.migrate import migrate
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.test_bw_admin import reset_shell_metadata_after_test



def tok(client):
    """The session CSRF token the check-parts forms and script send."""
    with client.session_transaction() as session:
        session.setdefault('bw_add_csrf', 'test-csrf-token')
        return session['bw_add_csrf']

@pytest.fixture

def bw(legacy, monkeypatch):
    migrate(**legacy)
    path = legacy['out_db']
    monkeypatch.setenv('BW_DB_PATH', str(path))
    return path


def mutate(db, path, action, **values):
    s = checker.session(db, 'copy')
    result = checker.write(db, 'copy', dict(action=action, operation=uuid.uuid4().hex,
        session=s['id'] if s else None, **values), path.parent)
    return checker.view(db, 'copy', path.parent) if action == 'start' else result


def test_routes_chooser_start_resume_and_shell(app, bw):
    client=logged_in(app)
    result=client.get('/workbench/check-parts')
    assert result.status_code == 200
    html=result.get_data(as_text=True)
    assert 'data-web-ui="toni"' in html and 'new-set' in html and 'Set 1' in html, html[html.index('<main'):html.index('</main>')]
    assert 'href="/workbench/check-parts"' in html
    assert 'data-jump-check="true"' not in html
    assert result.headers['Cache-Control']=='no-store'
    start=client.get('/workbench/check-parts/copy')
    assert 'Start a check' in start.get_data(as_text=True)
    assert client.post('/workbench/check-parts/copy',data={'csrf_token':tok(client),'action':'start','order':'largest'}).status_code==302
    resume=client.get('/workbench/check-parts/copy').get_data(as_text=True)
    assert 'data-check-state' in resume and 'check-history' in resume and 'Start a check' not in resume
    from bs4 import BeautifulSoup
    screen = BeautifulSoup(resume, 'html.parser').select_one('#bw-checker')
    assert screen.select_one('[data-toast]') is None
    feedback = screen.select_one('[data-save-feedback]')
    assert feedback.select_one('[data-save-status]')['role'] == 'status'
    assert feedback.select_one('[data-save-undo]')['data-action'] == 'undo'
    assert list(screen.children).index(feedback) < list(screen.children).index(screen.select_one('.check-copy-header'))
    with admin.database(bw) as db:
        state=checker.view(db,'copy',bw.parent)
        kinds={r['token']:r['kind'] for r in state['rows']}
        # 4.8a: no figure component rows, and spares only after the spare question.
        assert [kinds[t] for t in state['session']['order']] == ['part']*3+['figure']*2
        assert db.execute("SELECT count(*) FROM events WHERE via='app'").fetchone()[0]==2


def test_answer_count_history_found_one_undo_and_idempotency(bw):
    with admin.database(bw) as db:
        state=mutate(db,bw,'start')
        r=next(r for r in state['rows'] if r['kind']=='part' and r['quantity']==2)
        original=checker.snapshot(db,'copy',[r['token']])
        state=mutate(db,bw,'answer',token=r['token'],found=1)
        assert state['session']['misses']==[r['token']]
        assert next(x for x in state['rows'] if x['token']==r['token'])['missing']==1
        payload=dict(action='found_one',token=r['token'],operation='retry-receipt',session=state['session']['id'])
        checker.write(db,'copy',payload,bw.parent)
        state=checker.write(db,'copy',payload,bw.parent)
        assert next(x for x in state['rows'] if x['token']==r['token'])['missing']==0
        assert state['session']['misses']==[r['token']] # recovered misses stay in history
        assert db.execute("SELECT count(*) FROM events WHERE field='checker:retry-receipt'").fetchone()[0]==1
        mutate(db,bw,'undo')
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(r['id'],)).fetchone()[0]==1
        mutate(db,bw,'undo')
        assert checker.snapshot(db,'copy',[r['token']])==original


@pytest.mark.parametrize('source', ['derived','manual'])
def test_finish_requires_checked_and_figures_and_ignores_spares(bw,source):
    with admin.database(bw) as db:
        with db:
            db.execute("UPDATE copies SET completeness_source=?,completeness='S'",(source,))
            # This flow tests missing counts; migrated damage is independently blocking.
            db.execute('UPDATE copy_parts SET damaged=0')
        state=mutate(db,bw,'start')
        with pytest.raises(ValueError,match='unchecked'):
            mutate(db,bw,'finish',checked=True)
        for r in state['rows']:
            if r['kind']!='spare': mutate(db,bw,'answer',token=r['token'],found=r['quantity'])
        spare=next(r for r in state['rows'] if r['kind']=='spare')
        mutate(db,bw,'spares',include=True)
        mutate(db,bw,'answer',token=spare['token'],found=0)
        state=mutate(db,bw,'finish',checked=True)
        assert state['copy']['completeness']==('C' if source=='derived' else 'S')
        mutate(db,bw,'undo')
        assert not checker.session(db,'copy')['finished']
        figure=next(r for r in checker.view(db,'copy',bw.parent)['rows'] if r['kind']=='figure')
        mutate(db,bw,'answer',token=figure['token'],found=0)
        assert db.execute('SELECT missing FROM copy_minifigs WHERE minifig_no=?',(figure['item_no'],)).fetchone()[0]==figure['quantity']
        state=mutate(db,bw,'finish',checked=True)
        assert state['copy']['completeness']==('I' if source=='derived' else 'S')


def test_skip_back_next_select_resume_and_rollback(bw):
    with admin.database(bw) as db:
        state=mutate(db,bw,'start');token=state['session']['order'][0]
        state=mutate(db,bw,'skip',token=token)
        assert state['session']['answers'][token]=='skipped'
        assert mutate(db,bw,'back')['session']['cursor']==0
        assert mutate(db,bw,'next')['session']['cursor']==1
        assert mutate(db,bw,'select',token=token)['session']['cursor']==0
        old=checker.snapshot(db,'copy',[token])
        db.execute("CREATE TRIGGER reject_checker_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'no'); END")
        with pytest.raises(sqlite3.IntegrityError): mutate(db,bw,'answer',token=token,found=0)
        assert checker.snapshot(db,'copy',[token])==old


def test_undo_conflict_archive_and_bounds(bw):
    with admin.database(bw) as db:
        state=mutate(db,bw,'start');r=state['rows'][0]
        with pytest.raises(ValueError): mutate(db,bw,'answer',token=r['token'],found=-1)
        with pytest.raises(ValueError): mutate(db,bw,'answer',token=r['token'],found=r['quantity']+1)
        with pytest.raises(ValueError): mutate(db,bw,'answer',token='p:9999',found=0)
        mutate(db,bw,'answer',token=r['token'],found=0)
        with db: db.execute('UPDATE copy_parts SET missing=0 WHERE id=?',(r['id'],))
        with pytest.raises(ValueError,match='elsewhere'): mutate(db,bw,'undo')
        with db: db.execute("UPDATE copies SET archived_at='2026-10-13'")
        with pytest.raises(ValueError,match='no longer'): checker.view(db,'copy',bw.parent)
        assert checker.choices(db,bw.parent)==[]


def test_api_flow_security_and_placeholder(app,bw):
    client=logged_in(app);url='/workbench/check-parts/copy'
    with admin.database(bw) as db: state=mutate(db,bw,'start')
    row=next(r for r in state['rows'] if r['unresolved'])
    assert row['item_type']=='?' and row['unresolved']
    payload=dict(action='answer',operation='api-answer',session=state['session']['id'],token=row['token'],found=0)
    assert client.post(url,json={**payload,'csrf_token':tok(client)},headers={'Origin':'https://other.invalid'}).status_code==403
    assert app.test_client().post(url,json=payload).status_code==302
    result=client.post(url,json={**payload,'csrf_token':tok(client)})
    assert result.status_code==200 and result.json['state']['session']['misses']==[row['token']]
    payload.update(action='undo',operation='api-undo')
    assert client.post(url,json={**payload,'csrf_token':tok(client)}).status_code==200
    assert client.get('/workbench/check-parts/absent').status_code==404


def test_local_images_priorities_and_missing_counts(bw):
    with admin.database(bw) as db:
        state=checker.view(db,'copy',bw.parent)
        assert state['copy']['image'] is not None
        assert any(r['image'] is None for r in state['rows'])
        assert any(r['image'] is not None for r in state['rows'])
        r=state['rows'][0]
        with db: db.execute('UPDATE copy_parts SET quantity=NULL WHERE id=?',(r['id'],))
        mutate(db,bw,'start')
        with pytest.raises(ValueError,match='required count'):
            mutate(db,bw,'answer',token=r['token'],found=0)


def test_stale_session_cannot_undo_a_new_check(bw):
    with admin.database(bw) as db:
        old=mutate(db,bw,'start')['session']['id']
        mutate(db,bw,'finish',checked=False)
        current=mutate(db,bw,'start')['session']['id']
        assert current != old
        with pytest.raises(ValueError,match='check changed'):
            checker.write(db,'copy',dict(action='undo',session=old,operation='stale-undo'),bw.parent)
        assert checker.session(db,'copy')['id']==current




@pytest.mark.parametrize('initial', [False, True])
@pytest.mark.parametrize('finish_checked', [False, True])
def test_finish_flag_receipt_and_undo(bw, initial, finish_checked):
    with admin.database(bw) as db:
        state = mutate(db, bw, 'start')
        flag = checker.checked_flag(db)
        assert flag and flag != 'invented'  # A different status cannot satisfy the lookup.
        with db:
            if initial:
                db.execute("INSERT INTO item_flags VALUES('copy','copy',?)", (flag,))
        for r in state['rows']:
            if r['kind'] != 'spare':
                mutate(db, bw, 'answer', token=r['token'], found=r['quantity'])
        before = checker.snapshot(db, 'copy')
        state = mutate(db, bw, 'finish', checked=finish_checked)
        assert state['copy']['set_checked'] is finish_checked
        assert 'set_checked' not in json.loads(db.execute("SELECT value FROM settings WHERE key='checker:copy'").fetchone()[0])
        event = db.execute("SELECT old_value,new_value FROM events WHERE id=?", (state['session']['undo'][-1],)).fetchone()
        assert bool(json.loads(event[0])['checked_flag']) is initial
        assert bool(json.loads(event[1])['checked_flag']) is finish_checked
        mutate(db, bw, 'undo')
        assert checker.snapshot(db, 'copy') == before
        assert checker.checked(db, 'copy') is initial
        assert db.execute("SELECT count(*) FROM flags WHERE kind='status' AND name='Set is checked'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM events WHERE entity=? AND via='app'", ('flags:'+flag,)).fetchone()[0] == 1


def test_flag_finish_rolls_back_with_receipt(bw):
    with admin.database(bw) as db:
        state = mutate(db, bw, 'start')
        for r in state['rows']:
            if r['kind'] != 'spare':
                mutate(db, bw, 'answer', token=r['token'], found=r['quantity'])
        before = checker.snapshot(db, 'copy')
        db.execute("CREATE TRIGGER reject_finish BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'no'); END")
        with pytest.raises(sqlite3.IntegrityError):
            mutate(db, bw, 'finish', checked=True)
        assert checker.snapshot(db, 'copy') == before


def test_large_save_and_retry_have_no_picture_lookups(bw, monkeypatch):
    with admin.database(bw) as db:
        with db:
            for _ in range(2000):
                db.execute("""INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,spare,missing,checked)
                    SELECT copy_id,item_type,item_no,color_id,quantity,spare,0,0 FROM copy_parts LIMIT 1""")
        state = checker.view(db, 'copy', bw.parent)
        calls = []
        monkeypatch.setattr(checker, 'picture', lambda *args: calls.append(args))
        started = checker.write(db, 'copy', dict(action='start', operation='large-start'), bw.parent)
        assert started['partial'] and started['rows'] == []
        assert checker.write(db, 'copy', dict(action='start', operation='large-start'), bw.parent)['partial']
        assert checker.write(db, 'copy', dict(action='start', operation='already-started'), bw.parent)['partial']
        token = state['rows'][0]['token']
        payload = dict(action='answer', token=token, found=0, operation='large-save', session=started['session']['id'])
        for _ in range(2):
            result = checker.write(db, 'copy', payload, bw.parent)
            assert result['partial'] and len(result['rows']) == 1
            assert sum(result['progress'].values()) == 2005
            assert 'image' not in result['rows'][0]
        mutate(db, bw, 'undo')
        assert calls == []


def test_chooser_default_excludes_flagged_copy(app, bw):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db:
        mutate(db, bw, 'start')
        flag = checker.checked_flag(db)
        with db:
            db.execute("INSERT INTO item_flags VALUES('copy','copy',?)", (flag,))
        assert checker.choices(db, bw.parent)[0]['copy']['set_checked']
    html = BeautifulSoup(logged_in(app).get('/workbench/check-parts').data, 'html.parser')
    assert html.select_one('[data-filter] option[selected]')['value'] == 'unchecked'
    assert html.select_one('[data-check-sort] option')['value'] == 'largest'
    assert html.select_one('[data-list-row]')['data-checked'] == 'true'


def test_fresh_flag_creation_rolls_back_and_is_read_only_on_get(bw):
    with admin.database(bw) as db:
        before = db.execute('SELECT count(*) FROM flags').fetchone()[0]
        checker.view(db, 'copy', bw.parent)
        assert db.execute('SELECT count(*) FROM flags').fetchone()[0] == before
        assert checker.checked_flag(db) is None
        db.execute("CREATE TRIGGER reject_creation BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'no'); END")
        with pytest.raises(sqlite3.IntegrityError):
            mutate(db, bw, 'start')
        assert checker.checked_flag(db) is None
        assert checker.session(db, 'copy') is None


def test_checker_runtime():
    import shutil
    import subprocess
    from pathlib import Path
    subprocess.run([shutil.which('node'), str(Path(__file__).with_name('toni_bw_checker_runtime.cjs'))],
                   check=True, capture_output=True, text=True)


def test_run3_chooser_sections_shared_controls_and_stored_progress(app, bw):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db:
        state = mutate(db, bw, 'start')
        required = [r for r in state['rows'] if r['kind'] != 'spare']
        part = next(r for r in required if r['kind'] == 'part' and r['quantity'] is not None)
        mutate(db, bw, 'answer', token=part['token'], found=part['quantity'])
        other = next(r for r in required if r['token'] != part['token'])
        mutate(db, bw, 'skip', token=other['token'])
        with db:
            db.execute("INSERT INTO copies(id,item_type,set_no) SELECT 'other',item_type,set_no FROM copies WHERE id='copy'")
        choices = checker.choices(db, bw.parent)
        active = next(c for c in choices if c['copy']['id'] == 'copy')
        assert active['completed'] == 1 and active['total'] == len(required)
        with db:
            db.executemany("INSERT INTO copies(id,item_type,set_no) SELECT ?,item_type,set_no FROM copies WHERE id='copy'", [(f'cost-{i}',) for i in range(300)])
        statements = []
        db.set_trace_callback(statements.append)
        choices = checker.choices(db, bw.parent)
        db.set_trace_callback(None)
        assert len(choices) == 302 and len(statements) < 20
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/workbench/check-parts').text, 'html.parser')
    root = soup.select_one('#bw-check-choices')
    assert root.select_one('.bc-toolbar [data-check-search]')
    assert root.select_one('.bc-toolbar [data-check-filters]')
    assert root.select_one('.bc-toolbar [data-check-sort-open]')
    progress = root.select_one('[data-copy-section="progress"]')
    unchecked = root.select_one('[data-copy-section="unchecked"]')
    assert len(progress.select('[data-list-row]')) == 1
    assert len(unchecked.select('[data-list-row]')) == 301
    assert progress.select_one('[role="img"]')['aria-label'] == f'1 of {len(required)} checked'
    assert '1 of' in progress.text
    copy = BeautifulSoup(client.get('/workbench/check-parts/copy').text, 'html.parser')
    assert copy.select_one('#bw-check-choices') is None
    assert copy.select_one('#bw-checker .check-layout')


def test_run3_chooser_compact_styles():
    from pathlib import Path
    css = Path('static/web/toni/bw-checker.css').read_text()
    assert '#bw-check-choices .check-copy .check-picture { width:56px;height:56px;' in css
    assert '#bw-check-choices .check-copy>div:nth-child(2)>span.mono { display:block; }' in css
    assert '#bw-check-choices .check-copy>div:nth-child(2) { min-width:0; }' in css
    assert 'font-size:15px;line-height:20px' in css
    assert 'border-top:.5px solid var(--tw-divider);border-radius:0;min-height:89px' in css
    shared = Path('static/web/toni/bw-collection.css').read_text()
    assert ':is(#bw-collection,#bw-planning,#bw-check-choices) .bc-toolbar { display:grid;grid-template-columns:minmax(0,1fr) 44px 44px;' in shared


def test_chooser_phone_status_stacks_below_full_identity():
    import re
    from pathlib import Path
    css = Path('static/web/toni/bw-checker.css').read_text()
    phone = css.split('@media(width < 480px) {', 1)[1].rsplit('}', 1)[0]
    assert '#bw-check-choices .check-copy { flex-wrap:wrap; }' in phone
    # 56 px picture + 12 px gap: identity fills line one, status fills line two.
    assert '#bw-check-choices .check-copy>div:nth-child(2) { flex:1 1 calc(100% - 68px);text-wrap:balance; }' in phone
    assert '#bw-check-choices .check-copy>.check-choice-meta { flex-basis:calc(100% - 68px);margin-left:68px;text-align:left;justify-items:start; }' in phone
    assert '#bw-check-choices .check-choice-badges { justify-content:start; }' in phone
    label_rules = re.findall(r'[^{}]*>span\.mono\s*\{([^{}]*)\}', css)
    assert label_rules
    for rule in label_rules:
        assert not re.search(r'white-space\s*:\s*nowrap|overflow\s*:\s*hidden|text-overflow\s*:\s*ellipsis', rule)
    assert not re.search(r'\border\s*:|display\s*:\s*contents', phone)


def test_carried_chooser_progress_uses_current_required_inventory(app, bw):
    with admin.database(bw) as db:
        state = mutate(db, bw, 'start')
        required = [r for r in state['rows'] if r['kind'] != 'spare']
        figure = next(r for r in required if r['kind'] == 'figure')
        for row in required:
            mutate(db, bw, 'answer', token=row['token'], found=row['quantity'])
        def counts():
            choice = next(c for c in checker.choices(db, bw.parent) if c['copy']['id'] == 'copy')
            current = [r for r in checker.rows(db, 'copy', bw.parent, images=False, decorate=False) if r['kind'] != 'spare']
            assert choice['total'] == len(current)
            return choice['completed'], choice['total']
        assert counts() == (len(required), len(required))
        with db:
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,spare) SELECT copy_id,item_type,item_no,color_id,1,0 FROM copy_parts WHERE copy_id='copy' LIMIT 1")
        assert counts() == (len(required), len(required)+1)
        with pytest.raises(ValueError, match='Answer the skipped'):
            mutate(db, bw, 'finish', checked=True)
        with db:
            db.execute('DELETE FROM copy_minifigs WHERE copy_id=? AND item_type=? AND minifig_no=?', ('copy', figure['item_type'], figure['item_no']))
        assert counts() == (len(required)-1, len(required))
    response = logged_in(app).get('/workbench/check-parts')
    assert response.status_code == 200
    assert f'{len(required)-1} of {len(required)} checked' in response.text


def test_review4_checker_data_headline_and_single_column(app, bw):
    from bs4 import BeautifulSoup
    from contextlib import closing
    from pathlib import Path
    from brickwork.core.connect import connect
    with closing(connect(bw)) as db, db:
        mutate(db, bw, 'start', order='largest')
        db.execute("INSERT INTO copies(id,item_type,set_no) SELECT 'other',item_type,set_no FROM copies WHERE id='copy'")
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/workbench/check-parts').text, 'html.parser')
    root = soup.select_one('#bw-check-choices')
    assert not soup.select_one('.breadcrumb')
    assert root.h1.text == '1 check in progress, 1 set not checked'
    assert root.select_one('.check-list-heading>p[data-sort-caption]').text == 'Largest first'
    intro = root.find(string='Choose a copy to start or resume a check.').find_parent('details')
    assert intro and not intro.has_attr('open')
    sections = root.select('[data-section-rows]')
    assert len(sections) == 3
    assert all(row.parent in sections for row in root.select('[data-list-row]'))
    copy = BeautifulSoup(client.get('/workbench/check-parts/copy').text, 'html.parser')
    assert not copy.select_one('.breadcrumb')
    css = Path('static/web/toni/bw-checker.css').read_text()
    assert '[data-section-rows] { display:grid;grid-template-columns:minmax(0,1fr);width:100%;gap:0;' in css
    assert '.check-copy { display:flex;width:100%;' in css
    assert 'font:600 22px/28px var(--tw-font);letter-spacing:-.2px' in css
    assert '#bw-checker button.bw-primary { min-height:56px;font:600 16px var(--tw-font);' in css
    shared = Path('static/web/toni/toni.css').read_text()
    assert 'button.bw-primary,.button.bw-primary { background:var(--tw-accent);color:var(--bw-action-ink);' in shared


def test_review5_chooser_default_headline_badges_and_parts(app, bw):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db:
        mutate(db, bw, 'start')
        parts = {c['copy']['id']: c['parts'] for c in checker.choices(db, bw.parent)}
    soup = BeautifulSoup(logged_in(app).get('/workbench/check-parts').text, 'html.parser')
    rows = soup.select('[data-list-row]')
    visible = [r for r in rows if r['data-checked'] == 'false']
    p = sum(r['data-state'] == 'progress' for r in visible)
    u = sum(r['data-state'] == 'unchecked' for r in visible)
    assert soup.select_one('[data-choice-headline]').text == f"{p} {'check' if p == 1 else 'checks'} in progress, {u} {'set' if u == 1 else 'sets'} not checked"
    for row in rows:
        count = parts[row['href'].rsplit('/', 1)[-1]]
        if row['data-state'] == 'progress':
            # 4.9c w11/w13: progress ends the row with checked of total and a chevron, no parts line.
            assert not row.select('.check-pill') and not row.select('.check-choice-meta')
            assert row.select_one('.check-choice-progress') and row.select_one(':scope > svg')
        else:
            assert row.select_one('.check-choice-meta>.mono').text == f"{count} {'part' if count == 1 else 'parts'}"
            assert not row.select_one(':scope > svg')
    from pathlib import Path
    assert 'height:44px;min-height:44px;box-sizing:border-box;padding-block:0' in Path('static/web/toni/bw-checker.css').read_text()


@pytest.mark.parametrize('finished,checked', [(False, False), (False, True), (True, False), (True, True)])
def test_review5_chooser_session_flags_and_initial_visible_agreement(app, bw, finished, checked):
    """An unfinished check can belong to a flagged copy; Not checked hides it.

    Run-5 base counted that session in the headline, while JS hid the row and
    recounted the section. Finished sessions must never count as in progress.
    """
    from bs4 import BeautifulSoup
    with admin.database(bw) as db:
        state = mutate(db, bw, 'start')
        if finished:
            for row in state['rows']:
                if row['kind'] != 'spare':
                    mutate(db, bw, 'answer', token=row['token'], found=row['quantity'])
            mutate(db, bw, 'finish', checked=checked)
        elif checked:
            with db:
                db.execute("INSERT INTO item_flags VALUES('copy','copy',?)", (checker.checked_flag(db),))
    soup = BeautifulSoup(logged_in(app).get('/workbench/check-parts').text, 'html.parser')
    p, u = 0, 0
    for section in soup.select('[data-copy-section]'):
        rows = section.select('[data-list-row]:not([hidden])')
        assert int(section.select_one('[data-section-count]').text) == len(rows)
        assert section.has_attr('hidden') == (not rows)
        if section['data-copy-section'] == 'progress':
            p = len(rows)
        elif section['data-copy-section'] == 'unchecked':
            u = len(rows)
    assert p == int(not finished and not checked)
    assert soup.select_one('[data-choice-headline]').text == f"{p} {'check' if p == 1 else 'checks'} in progress, {u} {'set' if u == 1 else 'sets'} not checked"


def test_chooser_parts_agree_with_copy_page_excluding_figures_and_spares(app, bw):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db:
        state = checker.view(db, 'copy', bw.parent)
        assert [r['kind'] for r in state['rows']].count('part') == 3
        assert [r['kind'] for r in state['rows']].count('figure') == 2
        assert [r['kind'] for r in state['rows']].count('spare') == 1
        choice = next(c for c in checker.choices(db, bw.parent) if c['copy']['id'] == 'copy')
        assert choice['parts'] == 3 and choice['entries'] == 6
    client = logged_in(app)
    chooser = BeautifulSoup(client.get('/workbench/check-parts').text, 'html.parser')
    row = chooser.select_one('[href="/workbench/check-parts/copy"]')
    assert row['data-count'] == '6'
    assert row.select_one('.check-choice-meta>.mono').text == '3 parts'
    copy = BeautifulSoup(client.get('/workbench/check-parts/copy').text, 'html.parser')
    assert copy.select_one('[data-start] p.mono').text == '3 parts · 2 figures'


def test_run6_chooser_count_hidden_all_copies_beside_heading(app, bw):
    """4.9c w9, w10, w13: no result line, All copies in the Not checked heading row, kit progress type."""
    from bs4 import BeautifulSoup
    from pathlib import Path
    soup = BeautifulSoup(logged_in(app).get('/workbench/check-parts').text, 'html.parser')
    heads = soup.select('#bw-check-choices .check-section-head')
    assert [h.select_one('h2')['class'] for h in heads] and all(h.select_one('h2.check-section-title') for h in heads)
    buttons = soup.select('[data-check-all-copies]')
    assert len(buttons) == 1 and buttons[0].text == 'All copies' and buttons[0].parent.select_one('h2').text.startswith('Not checked')
    # Follow-up: a fallback control outside the sections stays reachable when the Not checked section is empty.
    fallback = soup.select_one('.check-list-heading ~ .check-all-fallback[data-check-all-fallback]')
    assert fallback and fallback.text == 'All copies' and fallback.has_attr('hidden') == bool(soup.select('[data-copy-section="unchecked"]:not([hidden])'))
    assert not fallback.find_parent('section')
    css = Path('static/web/toni/bw-checker.css').read_text()
    assert '#bw-check-choices [data-check-count] { display:none; }' in css
    assert 'height:44px;min-height:44px;padding:0;margin:0;border:0;background:none' in css and 'font:500 14px var(--tw-font)' in css
    assert '.check-choice-progress .mono { font:400 12px/16px var(--tw-mono);color:var(--tw-text-2); }' in css
    assert 'width:18px;height:18px;flex:none;color:var(--tw-text-faint)' in css


@pytest.mark.parametrize('phase', ['never', 'progress', 'checked'])
def test_audit_copy_landing_states(app, bw, phase):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db:
        if phase != 'never':
            state = mutate(db, bw, 'start', order='colour')
            if phase == 'progress':
                mutate(db, bw, 'answer', token=state['rows'][0]['token'], found=0)
            else:
                for row in state['rows']:
                    if row['kind'] != 'spare':
                        mutate(db, bw, 'answer', token=row['token'], found=row['quantity'])
                mutate(db, bw, 'finish', checked=True)
        before = checker.snapshot(db, 'copy')
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/workbench/check-parts/copy').text, 'html.parser')
    root = soup.select_one('#bw-checker')
    assert root['data-landing'] == 'true'
    assert root.select_one('[data-check-body]').has_attr('hidden')
    start = root.select_one('[data-start]')
    assert start and not start.has_attr('hidden')
    assert start.select_one('details summary').text == 'How it works'
    assert start.find('a', string='Back to the set')['href'].endswith('?copy=copy')
    assert start.find('a', string='Choose another copy')['href'] == '/workbench/check-parts'
    assert 'Minifigures follow the required parts.' in start.text
    assert [n['value'] for n in start.select('input[type=radio][name=order]')] == ['inventory', 'colour', 'largest']
    assert not start.select_one('select[name=order]')
    header = root.select_one('.check-copy-header')
    assert header.select_one('.check-picture') and header.h1
    assert len(header.select('.check-pill')) == 3
    assert root.select_one('.check-landing-progress [role=img]')['aria-label'].endswith(' found')
    assert len(root.find_all('a', string='Choose another copy')) == 1
    assert start.select_one('.check-start-help').find('a', string='Choose another copy')
    assert root.select_one('noscript') and 'needs JavaScript' in root.select_one('noscript').text
    if phase == 'progress':
        assert start.select_one('[data-resume]').text == 'Resume check'
        assert start.select_one('[data-resume]')['href'].endswith('/copy?run=1')
        assert '1 of 5 entries done' in start.select_one('.check-saved').text
        assert 'Saved ' in start.select_one('.check-saved').text
        assert start.select_one('[name=action]')['value'] == 'restart'
        assert start.select_one('[name=session]')['value'] == before['session']['id']
        assert start.select_one('input[name=order][checked]')['value'] == 'colour'
    else:
        assert not start.select_one('[data-resume]')
        assert start.select_one('[name=action]')['value'] == 'start'
        assert ('Check again' if phase == 'checked' else 'Start a check') in start.text
    with admin.database(bw) as db:
        assert checker.snapshot(db, 'copy') == before


def test_audit_start_restart_undo_and_stale_restart(app, bw):
    from bs4 import BeautifulSoup
    client = logged_in(app)
    response = client.post('/workbench/check-parts/copy', data={'csrf_token':tok(client),'action':'start', 'order':'inventory'})
    assert response.location.endswith('/copy?run=1')
    running = BeautifulSoup(client.get(response.location).text, 'html.parser')
    assert running.select_one('#bw-checker')['data-landing'] == 'false'
    assert not running.select_one('[data-start]')
    with admin.database(bw) as db:
        state = checker.view(db, 'copy', bw.parent)
        mutate(db, bw, 'answer', token=state['rows'][0]['token'], found=0)
        tokens = [row['token'] for row in state['rows']]
        before = checker.snapshot(db, 'copy', tokens)
    response = client.post('/workbench/check-parts/copy', data={'csrf_token':tok(client),
        'action':'restart', 'session':state['session']['id'], 'order':'largest'})
    assert response.status_code == 302 and response.location.endswith('?run=1')
    with admin.database(bw) as db:
        restarted = checker.session(db, 'copy')
        assert restarted['id'] != state['session']['id']
        assert restarted['answers'] == {} and restarted['cursor'] == 0
        assert restarted['sort'] == 'largest'
        assert before['parts']
        assert checker.snapshot(db, 'copy', tokens)['parts'] == before['parts']
        mutate(db, bw, 'undo')
        assert checker.session(db, 'copy') == before['session']
        snapshot = checker.snapshot(db, 'copy')
        with pytest.raises(ValueError, match='changed'):
            checker.write(db, 'copy', dict(action='restart', operation='stale-restart', session='stale'), bw.parent)
        assert checker.snapshot(db, 'copy') == snapshot


def test_audit_no_copies_rendering(app, bw):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db, db:
        db.execute("UPDATE copies SET archived_at='2026-10-16'")
    soup = BeautifulSoup(logged_in(app).get('/workbench/check-parts').text, 'html.parser')
    assert 'No copies to check yet.' in soup.select_one('main').text
    assert not soup.select('[data-list-row]')


def test_start_over_two_tabs_form_and_json(app, bw):
    from bs4 import BeautifulSoup
    client = logged_in(app)
    client.post('/workbench/check-parts/copy', data={'csrf_token':tok(client),'action': 'start'})
    with admin.database(bw) as db:
        old = checker.session(db, 'copy')['id']
    form = {'action': 'restart', 'session': old, 'order': 'largest'}
    assert client.post('/workbench/check-parts/copy', data={'csrf_token':tok(client),**form,'csrf_token':tok(client)}).status_code == 302
    with admin.database(bw) as db:
        before = checker.snapshot(db, 'copy')
    stale = client.post('/workbench/check-parts/copy', data={'csrf_token':tok(client),**form,'csrf_token':tok(client)})
    assert stale.status_code == 302 and stale.location.endswith('/copy')
    page = BeautifulSoup(client.get(stale.location).text, 'html.parser')
    assert 'changed' in page.select_one('[data-save-status]').text
    assert page.select_one('[data-start]')
    response = client.post('/workbench/check-parts/copy', json=dict(form, csrf_token=tok(client), operation='stale-tab'))
    assert response.status_code == 409 and 'changed' in response.json['error']
    with admin.database(bw) as db:
        assert checker.snapshot(db, 'copy') == before


@pytest.mark.parametrize('saved_at,expected', [(None, None), ('2020-10-16T14:20:00', '16 Oct, 14:20')])
def test_resume_saved_time_optional(app, bw, monkeypatch, saved_at, expected):
    from bs4 import BeautifulSoup
    with admin.database(bw) as db:
        state = mutate(db, bw, 'start')
    state['saved_at'] = saved_at
    monkeypatch.setattr(checker, 'view', lambda *args: state)
    page = BeautifulSoup(logged_in(app).get('/workbench/check-parts/copy').text, 'html.parser')
    text = page.select_one('.check-saved').text
    assert (f'Saved {expected}' in text) if expected else ('Saved' not in text)
    assert '0 of 5 entries done' in text


def test_running_check_header_follows_3e(app, bw):
    from bs4 import BeautifulSoup
    from contextlib import closing
    from brickwork.core.connect import connect
    with closing(connect(bw)) as db, db:
        mutate(db, bw, 'start')
    page = BeautifulSoup(logged_in(app).get('/workbench/check-parts/copy?run=1').text, 'html.parser')
    root = page.select_one('#bw-checker')
    assert not root.find('a', string='Choose another copy')
    assert root.select_one('[data-copy-status]').has_attr('hidden')
