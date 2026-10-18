"""Picker and matcher exercise the migrated v3 database, never legacy writes."""
from contextlib import closing
import json
import sqlite3

import pytest

from brickwork.core.connect import connect
from brickwork.core import workbench as w
from tests.test_bw_add import bw, app, legacy, apps, client_token


@pytest.fixture
def gaps(bw):
    with closing(connect(bw)) as db,db:
        db.execute("UPDATE copies SET completeness='I',completeness_source='derived' WHERE id='copy'")
        db.execute("UPDATE copy_parts SET missing=0,damaged=0")
        db.execute("UPDATE copy_minifigs SET missing=0")
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,checked,spare) VALUES('copy','P','bl-part',11,3,3,1,0)")
        part=db.execute('SELECT last_insert_rowid()').fetchone()[0]
        for identifier,name in [('test_checked','Set is checked'),('test_instr','Instructions present'),('test_box','Box present')]:
            db.execute("INSERT INTO flags(id,name,kind,shown_on_grid) VALUES(?,?,'status',1)",(identifier,name))
        db.execute("INSERT INTO item_flags VALUES('copy','copy','test_checked')")
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no) VALUES('O','new-set')")
        db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition) VALUES('box','O','new-set',1,'U')")
    with sqlite3.connect(bw.with_name('bricklink-catalog.db')) as cat:
        cat.executemany('INSERT INTO items VALUES(?,?,?,?,?,NULL)',
            [('I', n, 'Booklet ' + n, 'booklet ' + n, None) for n in ('6081-1', '7286-1')])
    return bw,part


def test_routes_shell_selection_rank_and_matcher(app,gaps):
    path,part=gaps
    client,csrf,_=client_token(app)
    for route in ['/workbench/part-picker','/workbench/part-picker?copy=copy','/workbench/match']:
        response=client.get(route)
        assert response.status_code==200
        html=response.get_data(as_text=True)
        assert 'data-web-ui="toni"' in html and ('Recent saves' in html) == (route != '/workbench/part-picker?copy=copy'), (route,html[html.index('<h1>'):html.index('<h1>')+650])
        assert 'href="/workbench/part-picker"' in html and 'href="/workbench/match"' in html
        assert response.headers['Cache-Control']=='no-store'
    assert 'Start picking' in client.get('/workbench/part-picker?copy=copy').text
    assert 'Add instruction booklets' in client.get('/workbench/match').text
    with closing(connect(path)) as db:
        assert w.picker(db,['copy'])[0]['completes']==1
        assert {r['item_type'] for r in w.matches(db)}=={'P','I','O'}


def test_transfer_recheck_history_atomicity_and_undo(app,gaps):
    path,part=gaps
    client,csrf,_=client_token(app)
    data=dict(csrf_token=csrf,source_id='loose-part',copy_id='copy',target='part',target_id=part,quantity=3)
    response=client.post('/workbench/save/transfer',json=data)
    assert response.status_code==200
    with closing(connect(path)) as db:
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(part,)).fetchone()[0]==0
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='loose-part'").fetchone()[0]==0
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='C'
        assert db.execute('SELECT count(*) FROM match_history').fetchone()[0]>=1
        assert db.execute("SELECT via FROM events WHERE id=?",(response.json['event_id'],)).fetchone()[0]=='app'
    assert client.post('/workbench/save/transfer',json=data).status_code==400
    undo=client.post('/workbench/save/undo',json=dict(csrf_token=csrf,event_id=response.json['event_id']))
    assert undo.json['message']=='Undone'
    with closing(connect(path)) as db:
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(part,)).fetchone()[0]==3
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='loose-part'").fetchone()[0]==3
    assert client.post('/workbench/save/undo',json=dict(csrf_token=csrf,event_id=response.json['event_id'])).status_code==200
    with closing(connect(path)) as db,db:
        db.execute("CREATE TRIGGER reject_workbench BEFORE INSERT ON events WHEN NEW.entity='bw_workbench' BEGIN SELECT RAISE(ABORT,'fixture'); END")
    assert client.post('/workbench/save/transfer',json=data).status_code==400
    with closing(connect(path)) as db:
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(part,)).fetchone()[0]==3
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='loose-part'").fetchone()[0]==3


@pytest.mark.parametrize('kind,source,target,flag',[('I','instruction','instructions','test_instr'),('O','box','box','test_box')])
def test_physical_flags_exact_set_and_undo(gaps,kind,source,target,flag):
    path,part=gaps
    with closing(connect(path)) as db:
        event=w.transfer(db,source,'copy',target,'new-set',1)
        assert db.execute("SELECT 1 FROM item_flags WHERE entity_id='copy' AND flag_id=?",(flag,)).fetchone()
        with pytest.raises(ValueError):w.transfer(db,source,'copy',target,'new-set',1)
        w.undo(db,event)
        assert not db.execute("SELECT 1 FROM item_flags WHERE entity_id='copy' AND flag_id=?",(flag,)).fetchone()
        assert db.execute('SELECT quantity FROM loose_stock WHERE id=?',(source,)).fetchone()[0]==1


def test_whole_figure_defects_and_no_double_offer(gaps):
    path,part=gaps
    with closing(connect(path)) as db:
        with db:
            db.execute("UPDATE copy_minifigs SET missing=1 WHERE item_type='M'")
            db.execute("UPDATE copy_parts SET parent_minifig_type='M',parent_minifig='bl-figure',quantity=1,missing=1 WHERE id=?",(part,))
        assert not [r for r in w.matches(db) if r['target']=='part']
        event=w.transfer(db,'loose-figure','copy','figure','bl-figure',1)
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(part,)).fetchone()[0]==0
        w.undo(db,event)
        with db:db.execute("UPDATE loose_minifig_parts SET damaged=1 WHERE stock_id='loose-figure'")
        assert not [r for r in w.matches(db) if r['target']=='figure']


def test_found_destinations_manual_status_conflict_and_booklets(gaps):
    path,part=gaps
    with closing(connect(path)) as db:
        with db:db.execute("UPDATE copies SET completeness='S',completeness_source='manual' WHERE id='copy'")
        event=w.found(db,'P','bl-part',11,'set',{str(part):2},2)
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='S'
        later=w.found(db,'P','bl-part',11,'set',{str(part):1},1)
        with pytest.raises(ValueError):w.undo(db,event)
        w.undo(db,later);w.undo(db,event)
        loose=w.found(db,'P','bl-part',11,'loose',{},4)
        data=json.loads(db.execute('SELECT new_value FROM events WHERE id=?',(loose,)).fetchone()[0])
        identifier=data['changes'][0]['new'][0]['id']
        w.undo(db,loose)
        assert db.execute('SELECT archived_at FROM loose_stock WHERE id=?',(identifier,)).fetchone()[0]
        count=db.execute('SELECT sum(missing) FROM copy_parts').fetchone()[0]
        event=w.found(db,'P','bl-part',11,'list',{},2)
        assert db.execute('SELECT sum(missing) FROM copy_parts').fetchone()[0]==count
        w.undo(db,event)
        event=w.booklets(db,'6081\n7286-1, 2',3)
        assert db.execute("SELECT quantity FROM loose_stock WHERE item_type='I' AND item_no='6081-1' AND archived_at IS NULL").fetchone()[0]==3
        w.undo(db,event)
        assert not db.execute("SELECT 1 FROM loose_stock WHERE item_type='I' AND item_no='6081-1' AND archived_at IS NULL").fetchone()
        before=db.execute('SELECT count(*) FROM loose_stock').fetchone()[0]
        with pytest.raises(ValueError):w.booklets(db,'6081\ninvalid!',1)
        assert db.execute('SELECT count(*) FROM loose_stock').fetchone()[0]==before


def test_csrf_unresolved_archive_and_wrong_colour(app,gaps):
    path,part=gaps
    client,csrf,_=client_token(app)
    assert client.post('/workbench/save/booklets',json={'text':'6081','quantity':1}).status_code==400
    assert client.post('/workbench/save/booklets',json={'csrf_token':csrf,'text':'6081','quantity':1}).status_code==200
    with closing(connect(path)) as db:
        with db:db.execute("UPDATE loose_stock SET color_id=0 WHERE id='loose-part'")
        assert not [r for r in w.matches(db) if r['target']=='part']
        with db:db.execute("UPDATE copies SET archived_at='2026-01-01' WHERE id='copy'")
        assert not w.matches(db)


def test_workbench_browser_runtime():
    import subprocess
    from pathlib import Path
    subprocess.run(['node',str(Path(__file__).with_name('toni_bw_workbench_runtime.cjs'))],check=True,capture_output=True,text=True)


def test_to_check_visible_but_never_consumed(app,gaps):
    path,part=gaps
    with closing(connect(path)) as db,db:
        db.execute("UPDATE id_match SET status='to_check' WHERE item_type='P' AND item_no='bl-part'")
    client,csrf,_=client_token(app)
    assert 'To check' in client.get('/workbench/part-picker?copy=copy').text
    html=client.get('/workbench/match').text
    assert 'Needs a check' in html and 'Unresolved figures' in html
    with closing(connect(path)) as db:
        assert not [r for r in w.matches(db) if r['item_type']=='P']
        with pytest.raises(ValueError):w.found(db,'P','bl-part',11,'loose',{},1)


def test_multiple_lineages_one_copy_undo(gaps):
    path,part=gaps
    with closing(connect(path)) as db:
        with db:
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,checked,spare) VALUES('copy','P','bl-part',11,1,1,1,0)")
            other=db.execute('SELECT last_insert_rowid()').fetchone()[0]
        event=w.found(db,'P','bl-part',11,'set',{str(part):3,str(other):1},4)
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='C'
        w.undo(db,event)
        assert db.execute('SELECT sum(missing) FROM copy_parts WHERE id IN (?,?)',(part,other)).fetchone()[0]==4
        assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='I'


@pytest.mark.parametrize('writer', ['checker', 'workbench'])
@pytest.mark.parametrize('source', ['derived', 'manual'])
def test_shared_completeness_damage_checked_figures_and_spares(gaps, writer, source):
    from brickwork.core import checker
    from brickwork.core.completeness import derived_state
    assert checker.derived_state is w.derived_state is derived_state
    path, part = gaps
    with closing(connect(path)) as db, db:
        db.execute('UPDATE copy_parts SET missing=0, damaged=0')
        db.execute("UPDATE copies SET completeness='S', completeness_source=? WHERE id='copy'", (source,))

        def recompute(expected):
            if writer == 'checker':
                checker.recompute(db, 'copy')
            else:
                w.recompute(db, [], 'copy')
            assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0] == (expected if source == 'derived' else 'S')

        db.execute('UPDATE copy_parts SET damaged=1 WHERE id=?', (part,))
        recompute('I')
        db.execute('UPDATE copy_parts SET spare=1 WHERE id=?', (part,))
        recompute('C')
        db.execute('UPDATE copy_parts SET damaged=0, spare=0, missing=1 WHERE id=?', (part,))
        recompute('I')
        db.execute('UPDATE copy_parts SET missing=0 WHERE id=?', (part,))
        db.execute("UPDATE copy_minifigs SET missing=1 WHERE item_type='M'")
        recompute('I')
        db.execute('UPDATE copy_minifigs SET missing=0')
        db.execute("DELETE FROM item_flags WHERE flag_id='test_checked'")
        recompute('I')
        db.execute("INSERT INTO item_flags VALUES('copy','copy','test_checked')")
        recompute('C')


def test_booklets_reject_unknown_lines_and_report_them_without_writes(app, gaps):
    path, part = gaps
    client, csrf, _ = client_token(app)
    with closing(connect(path)) as db:
        before = {t: db.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in ('items', 'loose_stock', 'events')}
    response = client.post('/workbench/save/booklets', json=dict(csrf_token=csrf, text='6081\n\nunknown\n123456-1', quantity=1))
    assert response.status_code == 400
    assert 'Line 3: unknown' in response.json['message']
    assert 'Line 4: 123456-1' in response.json['message']
    with closing(connect(path)) as db:
        assert before == {t: db.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in before}
    # A set identity cannot substitute for an instruction catalogue identity.
    with sqlite3.connect(path.with_name('bricklink-catalog.db')) as cat:
        cat.execute("INSERT INTO items VALUES('S','9999-1','Set','set',NULL,NULL)")
    with closing(connect(path)) as db:
        with pytest.raises(ValueError, match='Line 1: 9999-1.*unknown'):
            w.booklets(db, '9999-1', 1)


def test_booklets_ambiguous_and_unique_non_one_suffix(gaps):
    path, part = gaps
    with sqlite3.connect(path.with_name('bricklink-catalog.db')) as cat:
        cat.executemany('INSERT INTO items VALUES(?,?,?,?,?,NULL)',
            [('I', n, 'Instructions', 'instructions', None) for n in ('6080-1', '6080-2', '6090-2')])
    with closing(connect(path)) as db:
        before = db.execute('SELECT count(*) FROM loose_stock').fetchone()[0]
        with pytest.raises(ValueError, match='Line 2: 6080.*full booklet number'):
            w.booklets(db, '6081\n6080', 1)
        assert db.execute('SELECT count(*) FROM loose_stock').fetchone()[0] == before
        event = w.booklets(db, '6090\n6080-2, 2', 3)
        assert db.execute("SELECT quantity FROM loose_stock WHERE item_type='I' AND item_no='6090-2'").fetchone()[0] == 3
        assert db.execute("SELECT quantity FROM loose_stock WHERE item_type='I' AND item_no='6080-2'").fetchone()[0] == 2
        assert not db.execute("SELECT 1 FROM items WHERE item_type='I' AND item_no='6090-1'").fetchone()
        assert db.execute("SELECT name FROM items WHERE item_type='I' AND item_no='6090-2'").fetchone()[0] == 'Instructions'
        w.undo(db, event)


def test_matching_queries_grow_linearly_and_transfer_is_local(gaps, monkeypatch):
    path, part = gaps
    with closing(connect(path)) as db:
        def grow(start, stop):
            with db:
                db.executemany("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,spare) VALUES('copy','P','bl-part',11,1,1,0)", [() for _ in range(start, stop)])
                db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P','bl-part',11,1,'U')", [(f'cost-{i}',) for i in range(start, stop)])

        def measured(call):
            statements = []
            db.set_trace_callback(statements.append)
            try:
                result = call()
            finally:
                db.set_trace_callback(None)
            return len(statements), result

        grow(0, 100)
        small_matches, rows = measured(lambda: w.matches(db))
        assert len([r for r in rows if r['target'] == 'part']) == 101 * 101
        small_picker, _ = measured(lambda: w.picker(db, ['copy']))
        small_transfer, event = measured(lambda: w.transfer(db, 'loose-part', 'copy', 'part', part, 1))
        w.undo(db, event)
        grow(100, 300)
        large_matches, rows = measured(lambda: w.matches(db))
        assert len([r for r in rows if r['target'] == 'part']) == 301 * 301
        large_picker, _ = measured(lambda: w.picker(db, ['copy']))
        assert large_matches < small_matches * 3.5
        assert large_picker < small_picker * 3.5
        assert large_matches < 5000

        def no_full_scan(*args, **kwargs):
            pytest.fail('Transfer must validate only its requested source and gap')

        monkeypatch.setattr(w, 'matches', no_full_scan)
        monkeypatch.setattr(w, 'gaps', no_full_scan)
        large_transfer, event = measured(lambda: w.transfer(db, 'loose-part', 'copy', 'part', part, 1))
        assert large_transfer == small_transfer
        w.undo(db, event)


@pytest.mark.parametrize('change', [
    "UPDATE loose_stock SET color_id=0 WHERE id='loose-part'",
    "UPDATE loose_stock SET condition='D' WHERE id='loose-part'",
    "UPDATE loose_stock SET missing=3 WHERE id='loose-part'",
    "UPDATE loose_stock SET archived_at='2026-01-01' WHERE id='loose-part'",
    "UPDATE copies SET archived_at='2026-01-01' WHERE id='copy'",
    "UPDATE copy_parts SET missing=0 WHERE copy_id='copy'",
    "UPDATE copy_parts SET spare=1 WHERE copy_id='copy'",
    "UPDATE id_match SET status='to_check' WHERE item_type='P' AND item_no='bl-part'",
])
def test_local_transfer_rejects_unavailable_source_or_gap(gaps, change):
    path, part = gaps
    with closing(connect(path)) as db:
        with db:
            db.execute(change)
        before = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in ('copies', 'copy_parts', 'loose_stock', 'match_history', 'events')}
        with pytest.raises(ValueError, match='review matches again'):
            w.transfer(db, 'loose-part', 'copy', 'part', part, 1)
        assert before == {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in before}


def test_run3_copy_grouping_coverage_route_and_query_count(app, gaps):
    path, part = gaps
    with closing(connect(path)) as db:
        all_gaps = w.gaps(db)
        groups = w.group_matches(db, w.matches(db, all_gaps=all_gaps), all_gaps)
        assert len(groups) == 1
        assert (groups[0]['covered'], groups[0]['missing'], groups[0]['completes']) == (5, 5, True)
        with db:
            db.executemany("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,spare) VALUES('copy','P','bl-part',11,1,1,0)", [() for _ in range(300)])
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES('extra','P','bl-part',11,1,'U')")
        statements = []
        db.set_trace_callback(statements.append)
        all_gaps = w.gaps(db)
        groups = w.group_matches(db, w.matches(db, all_gaps=all_gaps), all_gaps)
        db.set_trace_callback(None)
        assert len(statements) < 40
        assert groups[0]['covered'] == 6  # Four usable parts plus booklet and box, never per-pair totals.
        assert groups[0]['missing'] == 305
        assert not groups[0]['completes']
    client, _, _ = client_token(app)
    from bs4 import BeautifulSoup
    for route in ['/workbench/matcher', '/workbench/match']:
        response = client.get(route)
        assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
        soup = BeautifulSoup(response.text, 'html.parser')
        assert not soup.select_one('.breadcrumb')
        assert '1 copy can be advanced, 0 can become complete' in soup.h1.text
        disclosure = soup.find('summary', string='How matching works').parent
        assert not disclosure.has_attr('open') and 'not reservations' in disclosure.text
        group = soup.select_one('[data-copy-id="copy"]')
        assert 'Set 1' in group.text and 'Copy copy' not in group.text
        assert group.select_one('[role="img"]')['aria-label'] == 'Covers 6 of 305 missing'
        assert {'Parts', 'Instruction', 'Box'} == {n.text for n in group.select('.bw-kind')}
        assert group.select_one('[data-action="transfer"]')
        assert 'Give' in group.text and 'Take' in group.text


def test_run3_copy_summary_requires_derived_and_keeps_loose_repairs_separate(gaps):
    path, _ = gaps
    with closing(connect(path)) as db:
        for source in ('manual', None):
            with db:
                db.execute("UPDATE copies SET completeness_source=? WHERE id='copy'", (source,))
            all_gaps = w.gaps(db)
            groups = w.group_matches(db, w.matches(db, all_gaps=all_gaps), all_gaps)
            assert groups[0]['owned_copy'] and not groups[0]['completes']
        with db:
            db.execute("INSERT INTO loose_stock(id,item_type,item_no,quantity,condition) VALUES('repair','M','bl-figure',1,'U')")
            db.execute("INSERT INTO loose_minifig_parts(stock_id,item_type,item_no,color_id,quantity,missing,spare) VALUES('repair','P','bl-part',11,1,1,0)")
        all_gaps = w.gaps(db)
        groups = w.group_matches(db, w.matches(db, all_gaps=all_gaps), all_gaps)
        repair = next(g for g in groups if g['copy']['id'] == 'repair')
        assert not repair['owned_copy'] and not repair['completes']
        assert repair['copy']['label'] == 'Loose minifigure'


def test_carried_empty_gap_snapshot_drops_stale_groups(app, gaps, monkeypatch):
    path, _ = gaps
    with closing(connect(path)) as db:
        candidates = w.matches(db)
        assert candidates
        assert w.group_matches(db, candidates, []) == []
    monkeypatch.setattr(w, 'gaps', lambda db: [])
    monkeypatch.setattr(w, 'matches', lambda db, **kw: candidates)
    client, _, _ = client_token(app)
    assert client.get('/workbench/match').status_code == 200


def test_picker_run3_selection_and_primary(app, gaps):
    from bs4 import BeautifulSoup
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/part-picker').text, 'html.parser')
    assert not soup.select_one('.breadcrumb')
    assert soup.select_one('[data-all]').text == 'All incomplete sets'
    assert soup.select_one('[data-none]').text == 'Choose sets'
    assert soup.select_one('[data-row] .bw-picture')
    assert soup.select_one('[data-continue].bw-primary')
    selected = BeautifulSoup(client.get('/workbench/part-picker?copy=copy').text, 'html.parser')
    assert not selected.select_one('.breadcrumb')
    assert selected.select_one('[data-start].bw-primary')


def test_picker_run3_ranking_uses_stored_data_and_reports_gaps(app, gaps):
    from bs4 import BeautifulSoup
    path, part = gaps
    with closing(connect(path)) as db:
        rows = w.picker(db, ['copy'])
        keys = {k['key']:k for k in w.picker_keys(rows)}
        assert keys['size']['reason'] and not keys['category']['reason']
        assert rows[0]['category'] == 'Rebrickable category 1'  # Migrated, explicitly source-labelled.
        with db:
            db.execute("DELETE FROM item_properties WHERE key='rebrickable.category'")
        assert next(k for k in w.picker_keys(w.picker(db, ['copy'])) if k['key']=='category')['reason']
        assert keys['storage']['reason']  # Copy storage cannot stand in for a part location.
        with db:
            db.execute("UPDATE items SET category='Plates' WHERE item_type='P' AND item_no='bl-part'")
            db.execute("INSERT INTO storages(id,name) VALUES('picker-store','Shelf A')")
            db.execute("UPDATE loose_stock SET storage_id='picker-store' WHERE item_type='P' AND item_no='bl-part'")
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,spare) VALUES('copy','P','bl-part',0,1,1,0)")
        rows = w.picker(db, ['copy'])
        assert rows == sorted(rows, key=lambda r: (r['category'], r.get('color_name') or '', r['rank_set'], not bool(r['rank_storage']), r['rank_storage'], -r['completes'], r['item_no']))
        assert next(r for r in rows if r['color_id']==11)['rank_storage'] == 'Shelf A'
        assert next(r for r in rows if r['color_id']==0)['rank_storage'] == ''
        assert all(r['category']=='Plates' for r in rows)
        keys = {k['key']:k for k in w.picker_keys(rows)}
        assert not keys['category']['reason'] and not keys['storage']['reason']
        with db:
            db.execute("UPDATE loose_stock SET condition='D' WHERE item_type='P' AND item_no='bl-part'")
        assert next(k for k in w.picker_keys(w.picker(db, ['copy'])) if k['key']=='storage')['reason']
        with db:
            db.execute("UPDATE loose_stock SET condition='U' WHERE item_type='P' AND item_no='bl-part'")
        assert w.picker(db, ['copy'], ['invalid','size','storage','category','colour'])[0]['rank_storage'] == 'Shelf A'
        # Key order affects actual selection ordering, rather than only the labels.
        sample = [dict(rows[0], category='Z', rank_set='2', rank_storage='B', completes=2),
                  dict(rows[1], category='A', rank_set='1', rank_storage='A', completes=0)]
        assert w.order_picker(sample)[0]['completes'] == 0
        assert w.order_picker(sample, [])[0]['completes'] == 2
        tied = [dict(r, category='A', color_name='Black', rank_set='1', rank_storage='A') for r in sample]
        assert w.order_picker(tied)[0]['completes'] == 2
        assert w.order_picker(tied, ['completes'])[0]['completes'] == 2
        for key in ['category','set','storage']:
            assert w.order_picker(sample,[key])[0]['completes'] == 0
    client, _, _ = client_token(app)
    response = client.get('/workbench/part-picker?copy=copy&ranked=1&rank=storage&rank=colour&pick=1')
    soup = BeautifulSoup(response.text, 'html.parser')
    assert response.status_code == 200
    assert soup.select_one('[data-pick]').has_attr('hidden') is False
    controls = soup.select('[data-rank-key] input')
    assert len(controls) == 5
    assert [n['value'] for n in controls if n.has_attr('checked')] == ['storage','colour']
    assert soup.select_one('[value=size]').has_attr('disabled')
    assert not soup.select('[data-move]')
    assert len(soup.select('[data-drag][tabindex="0"]')) == 4
    handle = soup.select_one('[data-rank-key="size"] [data-drag]')
    assert handle['tabindex'] == '-1' and handle['aria-disabled'] == 'true'
    assert not soup.select('[data-rank-key="completes"]')
    default = BeautifulSoup(client.get('/workbench/part-picker?copy=copy').text, 'html.parser')
    assert [n['data-rank-key'] for n in default.select('[data-rank-key]')] == list(w.PICKER_KEYS)
    assert [n['value'] for n in default.select('[data-rank-key] input[checked]')] == ['category', 'colour', 'set', 'storage']


def test_picker_run3_single_part_layout_selector_and_reading_order(app, gaps):
    from bs4 import BeautifulSoup
    path, _ = gaps
    with closing(connect(path)) as db, db:
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,spare) VALUES('copy','P','bl-part',0,1,1,0)")
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/part-picker?copy=copy&pick=1').text, 'html.parser')
    cards = soup.select('[data-pick] [data-row]')
    assert len(cards) == 2 and sum(not c.has_attr('hidden') for c in cards) == 1
    assert cards[0].select_one('[data-part-position]').text == 'Part 1 of 2'
    for card in cards:
        assert [n['class'][0] for n in card.find_all('div', recursive=False)] == ['bw-picker-media', 'bw-picker-details']
        identity = card.select_one('.bw-identity')
        assert identity.select_one('.bw-colour').find_next_sibling('span')['class'] == ['mono']
        assert not identity.select_one('strong')  # Part name appears once.
        selector = card.select_one('[data-selector]')
        assert not selector.select('.bw-picture, .bw-identity')
        assert selector.select_one('[data-quantity]').has_attr('hidden')
        assert [n['value'] for n in selector.select('[name=destination]')] == ['set','loose','list']
        assert selector.select_one('.bw-confirm.bw-primary').text == 'Confirm'
        assert not card.select_one('[data-mobile-selector]').contents  # One form, moved at the breakpoint.
    from pathlib import Path
    css = Path('static/web/toni/bw-workbench.css').read_text()
    assert 'grid-template-columns:minmax(0,420px) minmax(0,1fr)' in css
    assert 'aspect-ratio:1;background:#fff;border:.5px solid var(--tw-divider-strong);border-radius:10px' in css
    assert 'min-height:96px' in css and 'height:min(482px,calc(100dvh - 80px))' in css
    assert 'position:sticky;bottom:0' in css
    assert 'display:contents' not in css and not __import__('re').search(r'(?<![-\w])order\s*:', css)


@pytest.mark.parametrize('destination', ['set','loose','list'])
def test_picker_run3_found_routes_events_and_undo(app, gaps, destination):
    path, part = gaps
    client, csrf, _ = client_token(app)
    response = client.post('/workbench/save/found', json=dict(csrf_token=csrf,
        item_type='P',item_no='bl-part',color_id=11,destination=destination,
        assignments={str(part):2} if destination=='set' else {},quantity=2))
    assert response.status_code == 200
    with closing(connect(path)) as db:
        receipt = db.execute('SELECT via,new_value FROM events WHERE id=?', (response.json['event_id'],)).fetchone()
        assert receipt['via'] == 'app' and json.loads(receipt['new_value'])['action'] == 'found'
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?', (part,)).fetchone()[0] == (1 if destination=='set' else 3)
    undo = client.post('/workbench/save/undo', json=dict(csrf_token=csrf,event_id=response.json['event_id']))
    assert undo.status_code == 200
    with closing(connect(path)) as db:
        assert db.execute('SELECT missing FROM copy_parts WHERE id=?', (part,)).fetchone()[0] == 3


def test_picker_run3_list_and_found_save_query_counts(gaps):
    path, part = gaps
    with closing(connect(path)) as db:
        def measure(call):
            statements=[]
            db.set_trace_callback(statements.append)
            try: result=call()
            finally: db.set_trace_callback(None)
            return len(statements), result
        def listing():
            all_gaps=w.gaps(db)
            copies={r['copy_id']:dict(r['copy'],item_no=r['copy']['set_no']) for r in all_gaps if r['target']=='part'}
            w.decorate_many(db, list(copies.values()))
            return w.picker(db, copies, all_gaps=all_gaps)
        def grow(start,stop):
            with db:
                db.executemany("INSERT INTO copies(id,item_type,set_no) VALUES(?,'S','new-set')",[(f'pick-cost-{i}',) for i in range(start,stop)])
                db.executemany("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,spare) VALUES(?,'P','bl-part',11,1,1,0)",[(f'pick-cost-{i}',) for i in range(start,stop)])
        grow(0,100)
        small_list,_=measure(listing)
        small_save,event=measure(lambda:w.found(db,'P','bl-part',11,'set',{str(part):1},1))
        w.undo(db,event)
        grow(100,300)
        large_list,_=measure(listing)
        large_save,event=measure(lambda:w.found(db,'P','bl-part',11,'set',{str(part):1},1))
        assert large_list == small_list and large_list < 40
        assert large_save == small_save and large_save < 60
        w.undo(db,event)


@pytest.mark.parametrize('value', ['1', '007', 'Plates', '', '1.5', '  Plates  '])
def test_picker_category_property_is_plain_text(app, gaps, value):
    from bs4 import BeautifulSoup
    path, _ = gaps
    with closing(connect(path)) as db, db:
        db.execute("UPDATE items SET category=NULL WHERE item_type='P' AND item_no='bl-part'")
        db.execute("UPDATE item_properties SET value=? WHERE item_type='P' AND item_no='bl-part' AND key='rebrickable.category' AND source='rebrickable'", (value,))
        rows = w.picker(db, ['copy'])
        category = next(k for k in w.picker_keys(rows) if k['key']=='category')
        assert bool(category['reason']) == (not value.strip())
        if value.strip():
            assert rows[0]['category'] == 'Rebrickable category ' + value.strip()
    client, _, _ = client_token(app)
    response = client.get('/workbench/part-picker?copy=copy&pick=1')
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, 'html.parser')
    assert soup.select_one('[data-pick]')
    assert not soup.select_one('.breadcrumb')
    assert soup.select_one('[data-rank-key="category"] input').has_attr('disabled') == (not value.strip())


def test_review4_f26_every_destination_has_migrated_identity(app, gaps):
    """Jinja dot access resolves dict.copy before the nested copy identity."""
    from bs4 import BeautifulSoup
    path, _ = gaps
    with closing(connect(path)) as db, db:
        db.execute("INSERT INTO copies(id,item_type,set_no,completeness) SELECT 'second','S',set_no,'I' FROM copies WHERE id='copy'")
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,spare) VALUES('second','P','bl-part',11,2,2,0)")
        needs = w.picker(db, ['copy', 'second'])[0]['needs']
        assert len(needs) == 2
        expected = [(g['copy']['set_no'], g['copy']['label'], g['need']) for g in needs]
        assert all(number and label for number, label, _ in expected)
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/part-picker?copy=copy&copy=second&pick=1').text, 'html.parser')
    labels = soup.select('.bw-assignments>label>.mono')
    assert len(labels) == len(expected)
    assert {n.text for n in labels} == {f'{number} · {label} · {need} missing' for number, label, need in expected}
    for node in soup.select('[data-assignment]'):
        assert 'new-set Set ' in node['aria-label']


def test_review4_picker_pick_selector_and_sort(app, gaps):
    from bs4 import BeautifulSoup
    from pathlib import Path
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/part-picker?copy=copy&pick=1').text, 'html.parser')
    pick = soup.select_one('[data-pick]')
    assert pick.select_one('.bw-stop').get_text(strip=True) == 'Stop'
    assert 'button' not in pick.select_one('.bw-stop').get('class', [])
    assert 'Search, filter and sort parts' not in pick.text
    assert not pick.select_one('.bw-part-position').find(string=lambda s:'Category' in s)
    assert list(pick.children).index(pick.select_one('.bw-pick-controls')) > list(pick.children).index(pick.select_one('[data-rows]'))
    assert pick.select_one('.bw-pick-controls>summary').text == 'Details'
    card = pick.select_one('[data-row]')
    heading = card.select_one('.bw-selector-heading h2')
    assert heading.text == 'Found 3 × Invented\u00a0part'
    assert card.select_one('.bw-selector-identity p').text == 'bl-part · Invented blue'
    rank = soup.select_one('[data-rank]')
    assert rank.select_one('.bw-rank-intro').text == 'Drag to rank. Off keys are ignored.'
    css = Path('static/web/toni/bw-workbench.css').read_text()
    assert 'margin:0;font:600 22px/28px var(--tw-font);letter-spacing:-.2px' in css
    assert 'margin:4px 0 16px;font:400 14px/20px var(--tw-font);color:var(--tw-text-muted)' in css
    assert 'gap:2px;height:44px;padding:0 12px;margin-left:-20px' in css
    assert '[data-rank],#bw-workbench [data-pick] { display:block; }' in css
    assert not __import__('re').search(r'[−–-]\d', pick.get_text(' ', strip=True).replace('bl-part',''))


def test_review4_matcher_toolbar_identity_and_compact_disclosure(app, gaps):
    from bs4 import BeautifulSoup
    from pathlib import Path
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/match').text, 'html.parser')
    root = soup.select_one('#bw-workbench')
    matches = root.select_one('[data-list=matches]')
    assert matches.select_one('.bc-toolbar [data-search]')
    assert matches.select_one('.bc-toolbar [data-filters] svg')
    assert matches.select_one('.bc-toolbar [data-sort-toggle] svg')
    assert matches.select_one('[data-sort-panel]').has_attr('hidden')
    panel = matches.select_one('[data-filter-panel]')
    assert 'bc-filter-panel' in panel['class'] and panel.has_attr('hidden')
    assert panel.select_one('button[data-filters]').text == 'Done'
    intro = root.select_one('.bw-matcher-intro')
    assert intro.text == 'Loose stock finds, set detail takes'
    phone_intro = ''.join(str(node) for node in intro.contents if not getattr(node, 'name', None))
    assert phone_intro == 'Loose stock finds, set detail takes'
    assert matches.select_one('[data-direction]')
    group = matches.select_one('.bw-copy-group')
    details = group.select_one('details')
    assert not details.has_attr('open')
    assert 'kit-disclosure' in details['class']
    summary = details.select_one('summary')
    assert summary.select_one('a>.mono').text == 'new-set · Set 1'
    assert summary.select_one('a>strong').text
    assert summary.select_one('.bw-identity>.bw-coverage')
    assert 'Give or take' not in summary.text
    assert 'Give or take' in details.text
    assert matches.find_next('summary',string='How matching works')
    css = Path('static/web/toni/bw-workbench.css').read_text()
    assert matches.select_one('.bc-search svg circle')['r'] == '6.5'
    assert matches.select_one('.bc-list-options').text == 'Completable first, then coverage'
    assert not matches.select('[data-count]')
    assert 'Parts' in [badge.text for badge in matches.select('.bw-kind')]
    assert 'max-width:900px;margin-top:0' in css
    assert 'padding:16px 0;list-style:none' in css
    assert 'display:flex;flex-direction:column;gap:1px' in css
    assert 'height:22px;padding:0 8px;border-radius:999px;font:500 11px' in css
    assert 'height:6px;gap:2px' in css
    assert 'grid-template-columns:minmax(0,1fr) 44px 44px;gap:8px;max-width:560px' in css


def test_review5_picker_rank_type_and_sheet_handle(app, gaps):
    from bs4 import BeautifulSoup
    from pathlib import Path
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/part-picker?copy=copy&pick=1').text, 'html.parser')
    assert soup.select_one('[data-selector]>.bw-selector-handle')
    css = Path('static/web/toni/bw-workbench.css').read_text()
    assert 'font:500 15px var(--tw-font)' in css
    assert '[data-start] { font:600 16px var(--tw-font); }' in css
    assert 'width:36px;height:4px;border-radius:2px;background:var(--tw-divider-strong);margin:0 auto 16px' in css


def test_run6_picker_rank_order_no_extras_and_figures_badge(app, gaps):
    """4.9c w14..w18 against the real templates."""
    from bs4 import BeautifulSoup
    from pathlib import Path
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/part-picker?copy=copy').text, 'html.parser')
    for row in soup.select('[data-rank-key]'):
        kids = [c.get('data-rank-position') is not None and 'ordinal' or c.name for c in row.select_one('label').find_all(recursive=False)]
        assert kids == ['span', 'ordinal', 'input'], kids
    assert 'No usable loose parts have a recorded location' not in soup.select_one('[data-rank]').text
    assert not soup.select('[data-rank-key="storage"] small')
    assert soup.select_one('[data-rank-key="size"] small')
    rank = soup.select_one('[data-rank]')
    assert rank.select_one('[data-start]') and not rank.select('a.button')
    assert not soup.select('[data-list="history"]') and 'Recent saves' not in soup.text
    css = Path('static/web/toni/bw-workbench.css').read_text()
    assert 'label>span[data-rank-position] { flex:none;width:20px;font:400 12px/16px var(--tw-mono);color:var(--tw-text-2); }' in css
    matcher = client.get('/workbench/match').text
    assert '>Minifigure<' not in matcher and 'class="bw-kind"' in matcher


@pytest.mark.parametrize('name', ['Wild Lion', 'Seaplane'])
def test_audit_matcher_stacked_identity(app, gaps, name):
    from bs4 import BeautifulSoup
    from pathlib import Path
    path, _ = gaps
    with closing(connect(path)) as db, db:
        db.execute("UPDATE items SET name=? WHERE item_type='S' AND item_no='new-set'", (name,))
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/matcher').text, 'html.parser')
    link = soup.select_one('.bw-copy-summary .bw-identity>a')
    assert [n.name for n in link.find_all(recursive=False)] == ['span', 'strong']
    assert link.span.text == 'new-set · Set 1'
    assert link.strong.get_text().replace('\u00a0', ' ') == name
    css = Path('static/web/toni/bw-workbench.css').read_text()
    assert 'main #bw-workbench .bw-copy-summary .bw-identity>a { display:flex;flex-direction:column;align-items:flex-start;min-height:0;gap:0;text-align:left; }' in css
