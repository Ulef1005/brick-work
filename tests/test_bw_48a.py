"""4.8a: set part list without spares and figure parts; spare question; figure checker."""
import json
import uuid

import pytest
from bs4 import BeautifulSoup

from brickwork.core import admin, checker, collection, workbench
from brickwork.core.completeness import derived_state
from tests.test_bw_checker import bw, legacy, mutate  # noqa: F401
from tests.test_bw_collection import reset_shell_metadata_after_test  # noqa: F401
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps  # noqa: F401

FIGURE = ('M', 'scene-fig')
FIGURE_URL = '/workbench/check-parts/copy/figure/M/scene-fig'




def tok(client):
    """The session CSRF token the check-parts forms and script send."""
    with client.session_transaction() as session:
        session.setdefault('bw_add_csrf', 'test-csrf-token')
        return session['bw_add_csrf']

def insert(db, template, **values):
    row = dict(template, id=None, **values)
    columns = list(row)
    return db.execute('INSERT INTO copy_parts(' + ','.join(columns) + ') VALUES(' + ','.join('?' for _ in columns) + ')',
                      tuple(row[c] for c in columns)).lastrowid


def scene(db, spares=2, components=5, derived=True):
    """Three required lines, spare lines, and one whole figure with component rows."""
    template = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_type='P' AND spare=0 LIMIT 1").fetchone())
    db.execute("DELETE FROM copy_parts WHERE copy_id='copy'")
    db.execute("DELETE FROM copy_minifigs WHERE copy_id='copy'")
    db.execute("UPDATE loose_stock SET quantity=0")
    base = dict(template, parent_minifig=None, parent_minifig_type=None, spare=0, damaged=0, checked=1, missing=0)
    ids = {}
    for n, (quantity, missing) in enumerate([(2, 1), (3, 0), (1, 0)], 1):
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P',?,?)", (f'scene-p{n}', f'Required {n}'))
        ids[f'p{n}'] = insert(db, base, item_no=f'scene-p{n}', quantity=quantity, missing=missing)
    for n in range(1, spares + 1):
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P',?,?)", (f'scene-s{n}', f'Spare {n}'))
        ids[f's{n}'] = insert(db, base, item_no=f'scene-s{n}', quantity=n, spare=1, missing=0, checked=0)
    db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('M','scene-fig','Scene figure')")
    db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('copy','M','scene-fig',1,0)")
    for n in range(1, components + 1):
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P',?,?)", (f'scene-c{n}', f'Component {n}'))
        ids[f'c{n}'] = insert(db, base, item_no=f'scene-c{n}', quantity=1, parent_minifig='scene-fig', parent_minifig_type='M')
    # One loose replacement for the single required gap.
    db.execute("UPDATE loose_stock SET item_type='P',item_no='scene-p1',color_id=?,quantity=1,missing=0,damaged=0 WHERE id='loose-part'", (template['color_id'],))
    db.execute("UPDATE copies SET completeness_source=?,completeness='I'", ('derived' if derived else 'manual',))
    flag = checker.checked_flag(db, create=True)
    db.execute("INSERT OR IGNORE INTO item_flags VALUES('copy','copy',?)", (flag,))
    return ids


def rows_by_kind(db, kind):
    return [r for r in checker.rows(db, 'copy', None, images=False, decorate=False) if r['kind'] == kind]


def detail_page(app):
    response = logged_in(app).get('/collection/item/S/new-set?copy=copy')
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def test_a_set_list_counts_exclude_spares_and_figure_rows(app, bw):
    with admin.database(bw) as db, db:
        ids = scene(db)
        d = collection.detail(db, 'S', 'new-set', copy_id='copy')
        numbers = {r['item_no'] for r in d['consists']}
        assert numbers == {'scene-p1', 'scene-p2', 'scene-p3', 'scene-fig'}
        assert (d['progress']['total'], d['progress']['missing'], d['progress']['can_take'],
                d['progress']['different'], d['progress']['lines'], d['progress']['spare_lines']) == (6, 1, 1, 3, 3, 2)
        assert [r['kind'] for r in checker.rows(db, 'copy', None, images=False, decorate=False)].count('part') == 3
        assert len(db.execute("SELECT 1 FROM copy_parts WHERE copy_id='copy'").fetchall()) == 3 + 2 + 5  # nothing deleted
        assert derived_state(db, 'copy') == 'I'
        listing = {r['item_no']: r for r in collection.listing(db, 'S')}
        assert listing['new-set']['missing_parts'] == 1
        choice = next(c for c in checker.choices(db, bw.parent) if c['copy']['id'] == 'copy')
        assert (choice['parts'], choice['total']) == (3, 4)
    soup = detail_page(app)
    progress = soup.select_one('[aria-label="Copy progress"]')
    assert progress.h3.get_text() == '1 parts missing, 1 in loose stock'
    assert progress.select_one('.bc-progress-subline').get_text() == '3 different parts · all checked'
    assert [s.get_text() for s in progress.select('.bc-progress-stats span')] == ['1 missing', '1 can be taken', '0 to order']
    assert soup.select_one('[data-bc-tab=parts] .bc-tab-count').get_text() == '6'
    # The Parts tab lists three lines (JS builds "Show all 2 present parts" from these records).
    records = [json.loads(r['data-record']) for r in soup.select('[data-bc-inventory-rows] article[data-bc-row]')]
    parts = [r for r in records if r['type'] == 'P']
    assert len(parts) == 3 and sum(1 for r in parts if not r['missing']) == 2
    assert {r['number'] for r in records} == {'scene-p1', 'scene-p2', 'scene-p3', 'scene-fig'}
    text = soup.select_one('[data-module=consists]').get_text()
    assert 'scene-s1' not in text and 'scene-c1' not in text
    assert len(soup.select('[data-bc-missing-rows] .bc-missing-card, article.bc-missing-card')) == 1
    assert '2 spare lines · not listed or counted' in text
    assert ids  # rows exist


def test_b_check_ends_with_spare_question_default_skips_and_yes_walks_spares(bw):
    with admin.database(bw) as db:
        with db:
            ids = scene(db)
        spare_before = [dict(r) for r in db.execute('SELECT * FROM copy_parts WHERE spare=1 ORDER BY id')]
        state = mutate(db, bw, 'start')
        assert [r['kind'] for r in state['rows']].count('spare') == 2
        required = [t for t in state['session']['order']]
        assert len(required) == 4 and state['session']['spares'] is None
        assert all(not t.startswith('p:%d' % ids['s1']) for t in required)
        for token in required:
            row = next(r for r in state['rows'] if r['token'] == token)
            mutate(db, bw, 'answer', token=token, found=row['quantity'] - (row['missing'] or 0) if row['kind'] == 'part' else row['quantity'])
        s = checker.session(db, 'copy')
        assert s['cursor'] == len(s['order']) == 4
        # Finish with the default (no spare answer at all) never touches spare rows.
        state = mutate(db, bw, 'finish', checked=True)
        assert [dict(r) for r in db.execute('SELECT * FROM copy_parts WHERE spare=1 ORDER BY id')] == spare_before
        mutate(db, bw, 'undo')
        # "No, skip them" is recorded in the session and changes no row.
        state = mutate(db, bw, 'spares', include=False)
        assert state['session']['spares'] == 'no' and len(state['session']['order']) == 4
        mutate(db, bw, 'finish', checked=True)
        assert [dict(r) for r in db.execute('SELECT * FROM copy_parts WHERE spare=1 ORDER BY id')] == spare_before
        mutate(db, bw, 'undo')
        mutate(db, bw, 'undo')
        assert checker.session(db, 'copy')['spares'] is None
        # "Yes, check them" walks the spares, still not counted.
        state = mutate(db, bw, 'spares', include=True)
        assert state['session']['spares'] == 'yes' and len(state['session']['order']) == 6
        assert state['session']['cursor'] == 4
        assert state['progress']['remaining'] == 0
        spare_token = state['session']['order'][4]
        before_completeness = checker.copy(db, 'copy')['completeness']
        mutate(db, bw, 'answer', token=spare_token, found=0)
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?', (int(spare_token[2:]),)).fetchone()[0] == 1
        assert derived_state(db, 'copy') in ('C', 'I')
        with pytest.raises(ValueError, match='already included'):
            mutate(db, bw, 'spares', include=True)
        mutate(db, bw, 'undo')
        assert [dict(r) for r in db.execute('SELECT * FROM copy_parts WHERE spare=1 ORDER BY id')] == spare_before
        mutate(db, bw, 'undo')
        assert checker.session(db, 'copy')['spares'] is None
        assert checker.copy(db, 'copy')['completeness'] == before_completeness
        with pytest.raises(ValueError, match='include'):
            mutate(db, bw, 'spares', include='maybe')


def test_c_figure_check_counts_on_the_figure_not_the_set(app, bw):
    with admin.database(bw) as db:
        with db:
            ids = scene(db)
            db.execute("UPDATE copy_parts SET missing=0 WHERE id=?", (ids['p1'],))
            db.execute("UPDATE copies SET completeness='C'")
        assert derived_state(db, 'copy') == 'C'
        set_before = collection.detail(db, 'S', 'new-set', copy_id='copy')['progress']
        completeness = checker.copy(db, 'copy')['completeness']

        def figure_step(action, **values):
            s = checker.session(db, 'copy', FIGURE)
            return checker.write(db, 'copy', dict(action=action, operation=uuid.uuid4().hex, session=s['id'] if s else None, **values), bw.parent, FIGURE)
        started = figure_step('start', order='inventory')
        assert started['partial'] and started['session']['order']
        view = checker.figure_view(db, 'copy', bw.parent, *FIGURE)
        assert [r['kind'] for r in view['rows']] == ['part'] * 5 and view['figure']['name'] == 'Scene figure'
        tokens = view['session']['order']
        assert tokens == [r['token'] for r in view['rows']]
        for n, token in enumerate(tokens):
            figure_step('answer', token=token, found=0 if n < 2 else 1)
        assert db.execute('SELECT count(*) FROM copy_parts WHERE parent_minifig=\'scene-fig\' AND missing=1').fetchone()[0] == 2
        events = db.execute("SELECT count(*) FROM events WHERE entity='checker:copy:fig:M:scene-fig' AND via='app'").fetchone()[0]
        assert events == 6  # start and five answers
        assert db.execute("SELECT count(*) FROM events WHERE entity='checker:copy'").fetchone()[0] == 0
        # Counts on the figure, not on the set; the set stays Complete.
        d = collection.detail(db, 'S', 'new-set', copy_id='copy')
        figure = next(r for r in d['consists'] if r['item_type'] == 'M')
        assert (figure['parts_missing'], figure['parts_lines'], figure['missing']) == (2, 5, 0)
        assert d['progress'] == set_before
        assert derived_state(db, 'copy') == 'C' and checker.copy(db, 'copy')['completeness'] == completeness
        assert workbench.gaps(db) == [g for g in workbench.gaps(db) if g['target'] != 'part']
        # Finishing a figure check never touches the set's checked flag.
        flag_before = checker.checked(db, 'copy')
        figure_step('finish')
        assert checker.checked(db, 'copy') is flag_before and checker.session(db, 'copy') is None
        assert checker.session(db, 'copy', FIGURE)['finished']
        for _ in range(5):  # finish and the answers of parts 5, 4, 3, 2
            figure_step('undo')
        assert db.execute("SELECT count(*) FROM copy_parts WHERE parent_minifig='scene-fig' AND missing=1").fetchone()[0] == 1
        figure_step('undo')
        assert db.execute("SELECT count(*) FROM copy_parts WHERE parent_minifig='scene-fig' AND missing=1").fetchone()[0] == 0
    soup = detail_page(app)
    assert soup.select_one('a.bc-check-figure') is not None
    with admin.database(bw) as db, db:
        for token in tokens[:2]:
            db.execute('UPDATE copy_parts SET missing=1 WHERE id=?', (int(token[2:]),))
    soup = detail_page(app)
    pill = soup.select_one('span.bc-figure-status')
    assert pill.get_text().startswith('2 parts missing') and pill['data-figure-state'] == 'parts-missing'
    assert soup.select_one('a.bc-check-figure')['href'] == FIGURE_URL
    assert not soup.select_one('a.bc-figure-status')
    assert soup.select_one('[aria-label="Copy progress"] h3').get_text() == '0 parts missing, 0 in loose stock'
    with admin.database(bw) as db, db:
        # A whole figure marked missing still makes the copy incomplete, as before.
        db.execute("UPDATE copy_minifigs SET missing=1")
        checker.recompute(db, 'copy')
        assert checker.copy(db, 'copy')['completeness'] == 'I'


def test_d_copy_without_spares_has_no_spare_step(bw):
    with admin.database(bw) as db:
        with db:
            scene(db, spares=0)
        state = mutate(db, bw, 'start')
        assert [r['kind'] for r in state['rows']].count('spare') == 0
        with pytest.raises(ValueError, match='no spare parts'):
            mutate(db, bw, 'spares', include=True)
        assert checker.session(db, 'copy')['spares'] is None


def test_e_matching_uses_set_gaps_only(bw):
    with admin.database(bw) as db:
        with db:
            ids = scene(db)
            # A loose component part with the same identity as a missing figure part.
            db.execute("UPDATE copy_parts SET missing=1 WHERE id=?", (ids['c1'],))
            db.execute("UPDATE copy_parts SET missing=1 WHERE id=?", (ids['s1'],))
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) SELECT 'loose-c1',item_type,item_no,color_id,4,'U' FROM copy_parts WHERE id=?", (ids['c1'],))
        gaps = workbench.gaps(db)
        assert {g['item_no'] for g in gaps if g['target'] == 'part'} == {'scene-p1'}
        assert not [g for g in gaps if g.get('parent_minifig') or g.get('spare')]
        matches = workbench.matches(db)
        assert {m['item_no'] for m in matches} == {'scene-p1'}
        # The transfer API refuses a figure component row as a gap.
        stock = dict(db.execute("SELECT * FROM loose_stock WHERE id='loose-c1'").fetchone())
        assert workbench.requested_gap(db, stock, 'copy', 'part', ids['c1']) is None


def test_f_query_counts_do_not_grow_with_rows(bw):
    with admin.database(bw) as db:
        with db:
            scene(db)
        def cost(call):
            statements = []
            db.set_trace_callback(statements.append)
            call()
            db.set_trace_callback(None)
            return len(statements)
        small = (cost(lambda: collection.detail(db, 'S', 'new-set', copy_id='copy')),
                 cost(lambda: checker.rows(db, 'copy', bw.parent, images=False)),
                 cost(lambda: checker.saved_view(db, 'copy', bw.parent)))
        with db:
            template = dict(db.execute("SELECT * FROM copy_parts WHERE parent_minifig='scene-fig' LIMIT 1").fetchone())
            req = dict(db.execute("SELECT * FROM copy_parts WHERE spare=0 AND parent_minifig IS NULL LIMIT 1").fetchone())
            for n in range(300):
                db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P',?,?)", (f'bulk-{n}', f'Bulk {n}'))
                insert(db, template, item_no=f'bulk-{n}')
                insert(db, req, item_no=f'bulk-{n}')
                insert(db, req, item_no=f'bulk-{n}', spare=1)
        large = (cost(lambda: collection.detail(db, 'S', 'new-set', copy_id='copy')),
                 cost(lambda: checker.rows(db, 'copy', bw.parent, images=False, decorate=False)),
                 cost(lambda: checker.saved_view(db, 'copy', bw.parent)))
        assert large[0] <= small[0] + 3 and large[2] <= small[2] + 1
        assert large[1] <= 4


def test_old_sessions_with_figure_and_spare_tokens_still_open(app, bw):
    with admin.database(bw) as db:
        with db:
            ids = scene(db)
        state = mutate(db, bw, 'start')
        figure_token = 'p:%d' % ids['c1']
        spare_token = 'p:%d' % ids['s1']
        part_tokens = state['session']['order']
        # Shape of a pre 4.8a session: component rows inline and the spares at the end.
        old = dict(id='old-session', order=[part_tokens[0], figure_token, *part_tokens[1:], spare_token], cursor=3,
                   answers={part_tokens[0]: 'answered', figure_token: 'answered'}, misses=[figure_token], undo=[], finished=False)
        with db:
            db.execute("UPDATE settings SET value=? WHERE key='checker:copy'", (json.dumps(old),))
        view = checker.view(db, 'copy', bw.parent)
        s = view['session']
        assert figure_token not in s['order'] and spare_token not in s['order']
        assert s['order'] == part_tokens and s['cursor'] == 2 and s['misses'] == [] and s['spares'] is None
        assert figure_token not in s['answers']
        # Writes work against the pruned sequence and persist it; Undo restores the raw old session.
        after = checker.write(db, 'copy', dict(action='answer', token=part_tokens[1], found=1, operation='old-answer', session='old-session'), bw.parent)
        assert after['session']['order'] == part_tokens
        stored = json.loads(db.execute("SELECT value FROM settings WHERE key='checker:copy'").fetchone()[0])
        assert stored['order'] == part_tokens and figure_token not in stored['answers']
        checker.write(db, 'copy', dict(action='undo', operation='old-undo', session='old-session'), bw.parent)
        assert json.loads(db.execute("SELECT value FROM settings WHERE key='checker:copy'").fetchone()[0])['order'][1] == figure_token
        assert checker.view(db, 'copy', bw.parent)['session']['order'] == part_tokens
    assert logged_in(app).get('/workbench/check-parts/copy').status_code == 200


def test_figure_routes_auth_csrf_and_unknown_figure(app, bw):
    with admin.database(bw) as db, db:
        scene(db)
    client = logged_in(app)
    page = client.get(FIGURE_URL)
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store'
    soup = BeautifulSoup(page.text, 'html.parser')
    root = soup.select_one('#bw-checker')
    assert root['data-endpoint'] == FIGURE_URL and 'inventory=figures' in root['data-done-url']
    assert 'Scene\xa0figure' in soup.h1.get_text() and soup.select_one('[data-start]')
    assert 'Check figure parts' in soup.get_text()
    assert app.test_client().get(FIGURE_URL).status_code == 302
    assert app.test_client().post(FIGURE_URL, json=dict(action='start', operation='x')).status_code == 302
    payload = dict(action='start', operation='fig-start', order='inventory')
    assert client.post(FIGURE_URL, json={**payload,'csrf_token':tok(client)}, headers={'Origin': 'https://other.invalid'}).status_code == 403
    assert client.post(FIGURE_URL, json={**payload,'csrf_token':tok(client)}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.get('/workbench/check-parts/copy/figure/M/absent').status_code == 404
    assert client.get('/workbench/check-parts/absent/figure/M/scene-fig').status_code == 404
    assert client.post('/workbench/check-parts/copy/figure/M/absent', json={**payload,'csrf_token':tok(client)}).status_code == 409
    started = client.post(FIGURE_URL, json={**payload,'csrf_token':tok(client)})
    assert started.status_code == 200 and started.json['state']['session']['order']
    redirect = client.post(FIGURE_URL, data={'csrf_token':tok(client),'action': 'start', 'order': 'largest'})
    assert redirect.status_code == 302 and redirect.headers['Location'].endswith(FIGURE_URL)
    resumed = BeautifulSoup(client.get(FIGURE_URL).text, 'html.parser')
    assert resumed.select_one('[data-check-state]') and not resumed.select_one('[data-start]')
    state = json.loads(resumed.select_one('[data-check-state]').string)
    assert state['figure']['item_no'] == 'scene-fig' and len(state['rows']) == 5
    # The set check on the same copy is a separate session.
    assert checker.session  # keeps the import used
    assert 'data-figure-url' in client.get('/workbench/check-parts/copy').text


def test_figure_session_keys_include_the_type(bw):
    with admin.database(bw) as db:
        with db:
            scene(db)
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('?','scene-fig','Placeholder figure')")
            db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('copy','?','scene-fig',1,0)")
            template = dict(db.execute("SELECT * FROM copy_parts WHERE parent_minifig='scene-fig' LIMIT 1").fetchone())
            insert(db, template, parent_minifig_type='?')
        other = ('?', 'scene-fig')
        checker.write(db, 'copy', dict(action='start', operation='k1', order='inventory'), bw.parent, FIGURE)
        checker.write(db, 'copy', dict(action='start', operation='k2', order='inventory'), bw.parent, other)
        a, b = checker.session(db, 'copy', FIGURE), checker.session(db, 'copy', other)
        assert a['id'] != b['id'] and len(a['order']) == 5 and len(b['order']) == 1
        assert checker.key('copy', FIGURE) != checker.key('copy', other)
        assert db.execute("SELECT count(*) FROM events WHERE entity='checker:copy:fig:?:scene-fig'").fetchone()[0] == 1


def test_normalise_drops_spare_answers_and_misses_until_yes():
    kinds = {'p:1': 'part', 'p:2': 'spare'}
    old = dict(id='s', order=['p:1', 'p:2'], cursor=1, answers={'p:1': 'answered', 'p:2': 'answered'}, misses=['p:2', 'p:1'], undo=[], finished=False)
    s = checker.normalise(dict(old, answers=dict(old['answers'])), kinds)
    assert s['answers'] == {'p:1': 'answered'} and s['misses'] == ['p:1'] and s['order'] == ['p:1']
    s = checker.normalise(dict(old, spares='yes', answers=dict(old['answers'])), kinds)
    assert s['misses'] == ['p:2', 'p:1'] and 'p:2' in s['answers']


def test_recompute_flips_stale_derived_only(bw):
    from brickwork.core import recompute
    with admin.database(bw) as db:
        with db:
            ids = scene(db)
            db.execute("UPDATE copy_parts SET missing=0 WHERE id=?", (ids['p1'],))
            db.execute("UPDATE copy_parts SET missing=1 WHERE id=?", (ids['c1'],))
            db.execute("UPDATE copies SET completeness='I'")
            original = dict(db.execute("SELECT * FROM copies WHERE id='copy'").fetchone())
            db.execute('INSERT INTO copies(' + ','.join(original) + ') VALUES(' + ','.join('?' for _ in original) + ')',
                       tuple(dict(original, id='manual-copy', completeness_source='manual').values()))
        events = db.execute('SELECT count(*) FROM events').fetchone()[0]
        result = recompute.recompute_completeness(db)
        assert result['changed'] == 1 and result['transitions'] == {'I->C': 1}
        assert checker.copy(db, 'copy')['completeness'] == 'C'
        assert checker.copy(db, 'manual-copy')['completeness'] == 'I'
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == events
        assert recompute.recompute_completeness(db)['changed'] == 0


@pytest.mark.parametrize('figure_mode', [False, True])
def test_finished_reload_shows_only_start_card(app, bw, figure_mode):
    with admin.database(bw) as db, db:
        scene(db)
    client = logged_in(app)
    url = FIGURE_URL if figure_mode else '/workbench/check-parts/copy'
    state = client.post(url, json=dict(csrf_token=tok(client),action='start', operation='reload-start')).json['state']
    session_id = state['session']['id']
    # Finishing without the checked flag is allowed with unanswered entries.
    response = client.post(url, json=dict(csrf_token=tok(client),action='finish', operation='reload-finish', session=session_id, checked=False))
    assert response.status_code == 200
    page = BeautifulSoup(client.get(url + '?run=1').text, 'html.parser')
    assert page.select_one('#bw-checker')['data-check-stage'] == 'start'
    assert page.select_one('[data-start] h2').text == 'Check again'
    assert page.select_one('[data-check-body]').has_attr('hidden')
