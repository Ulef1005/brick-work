"""Collection tests that wait for the workbench (M.8e): Matching on the item page, Take and Give, loose-figure gaps, merged part lines. Moved out of
test_bw_collection.py in M.8d (the writes of that file are ported); still the 3.3 text, rewritten on 4.0 fixtures with the workbench."""
from io import BytesIO
import json
import re
from pathlib import Path
import sqlite3

from bs4 import BeautifulSoup
from PIL import Image
import pytest

from brickwork.core import admin, collection, workbench, checker
from brickwork.core.importer.migrate import migrate
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.test_bw_admin import reset_shell_metadata_after_test




@pytest.fixture
def bw(legacy, monkeypatch):
    migrate(**legacy)
    monkeypatch.setenv('BW_DB_PATH',str(legacy['out_db']))
    return legacy['out_db']


def token(client):
    client.get('/collection/sets')
    with client.session_transaction() as s: return s['bw_add_csrf']


def post(client,csrf,action,**data):
    return client.post('/collection/save/'+action,json=dict(csrf_token=csrf,**data))


def test_matching_transfer_completes_and_undo(app,bw):
    with admin.database(bw) as db,db:
        db.execute("UPDATE copies SET completeness_source='derived',completeness='I'")
        db.execute('UPDATE copy_parts SET missing=0,damaged=0')
        db.execute('UPDATE copy_minifigs SET missing=0')
        p=db.execute("SELECT id FROM copy_parts WHERE item_type='P' AND item_no='bl-part' AND parent_minifig IS NULL").fetchone()[0]
        db.execute('UPDATE copy_parts SET missing=1 WHERE id=?',(p,))
        checked=checker.checked_flag(db,create=True)
        db.execute("INSERT OR IGNORE INTO item_flags VALUES('copy','copy',?)",(checked,))
    client=logged_in(app);csrf=token(client)
    r=client.get('/collection/item/P/bl-part?colour=11')
    assert r.status_code==200 and b'Completes set' in r.data
    r=post(client,csrf,'transfer',source_id='loose-part',copy_id='copy',target='part',target_id=p,quantity=1)
    assert r.status_code==200,r.json
    with admin.database(bw) as db: assert db.execute("SELECT completeness FROM copies WHERE id='copy'").fetchone()[0]=='C'
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db: assert db.execute('SELECT missing FROM copy_parts WHERE id=?',(p,)).fetchone()[0]==1


def test_loose_minifigure_gaps_share_transfer_and_undo(app,bw):
    with admin.database(bw) as db,db:
        db.execute("UPDATE loose_minifig_parts SET missing=1,damaged=0,spare=0 WHERE stock_id='loose-figure'")
        part=dict(db.execute("SELECT * FROM loose_minifig_parts WHERE stock_id='loose-figure'").fetchone())
        assert part['item_no']=='bl-part' and part['color_id']==11
    with admin.database(bw) as db:
        assert any(r['target']=='stock-part' for r in workbench.matches(db)),workbench.gaps(db)
    client=logged_in(app);csrf=token(client)
    r=client.get('/collection/item/M/bl-figure?stock=loose-figure')
    assert r.status_code==200 and b'Loose minifigure' in r.data and b'Take 1' in r.data
    payload=dict(source_id='loose-part',copy_id='loose-figure',target='stock-part',target_id=['P','bl-part',11,0],quantity=1)
    r=post(client,csrf,'transfer',**payload)
    assert r.status_code==200,r.json
    with admin.database(bw) as db:
        assert db.execute("SELECT missing FROM loose_minifig_parts WHERE stock_id='loose-figure'").fetchone()[0]==0
        assert db.execute("SELECT copy_id FROM match_history WHERE kind='stock-part'").fetchone()[0] is None
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert post(client,csrf,'transfer',**payload).status_code==400
    assert post(client,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db: assert db.execute("SELECT missing FROM loose_minifig_parts WHERE stock_id='loose-figure'").fetchone()[0]==1


def test_matching_and_jump_queries_are_bounded(bw):
    with admin.database(bw) as db:
        def measured(call):
            queries=[];db.set_trace_callback(queries.append)
            try: call()
            finally: db.set_trace_callback(None)
            return len(queries)
        small=measured(lambda:workbench.matches(db));search_small=measured(lambda:collection.search(db,'part'))
        with db:
            db.executemany("INSERT INTO loose_stock(id,item_type,item_no,color_id,quantity,condition) VALUES(?,'P','bl-part',11,1,'U')",[(f'bounded-{n}',) for n in range(300)])
        assert measured(lambda:workbench.matches(db))==small
        assert measured(lambda:collection.search(db,'part'))==search_small
        assert small<30 and search_small<20


def test_46s_merged_part_transfers_keep_every_row_and_undo(bw):
    with admin.database(bw) as db, db:
        original = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_type='P' LIMIT 1").fetchone())
        db.execute("DELETE FROM copy_parts WHERE copy_id='copy'")
        db.execute("DELETE FROM copy_minifigs WHERE copy_id='copy'")
        columns = list(original)
        for n in range(4):
            row = dict(original, id=None, parent_minifig_type=None, parent_minifig=None,
                       quantity=1, missing=1, damaged=0, checked=1, spare=0)
            db.execute('INSERT INTO copy_parts('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', tuple(row[c] for c in columns))
        db.execute("UPDATE loose_stock SET item_type=?,item_no=?,color_id=?,quantity=4,missing=0,damaged=0 WHERE id='loose-part'", (original['item_type'],original['item_no'],original['color_id']))
        d = collection.detail(db, 'S', 'new-set', copy_id='copy')
        assert len(d['consists']) == 1
        assert d['consists'][0]['can_take'] == 4
        assert len(d['matches']) == 4
        ids = {p['id'] for p in d['consists'][0]['contexts']}
        assert {m['target_id'] for m in d['matches']} == ids
        db.commit()
        events = []
        for match in d['matches']:
            events.append(workbench.transfer(db, match['source_id'], 'copy', match['target'], match['target_id'], 1))
        assert db.execute("SELECT sum(missing) FROM copy_parts WHERE copy_id='copy'").fetchone()[0] == 0
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='loose-part'").fetchone()[0] == 0
        for event in reversed(events):
            assert db.execute('SELECT via FROM events WHERE id=?', (event,)).fetchone()[0] == 'app'
            workbench.undo(db, event)
        assert db.execute("SELECT sum(missing) FROM copy_parts WHERE copy_id='copy'").fetchone()[0] == 4
        assert db.execute("SELECT quantity FROM loose_stock WHERE id='loose-part'").fetchone()[0] == 4


def add_47f_inventory_parts(db):
    """Reported identities added to the migrated inventory for layout checks."""
    db.execute("UPDATE colors SET name='Black',rgb='05131D' WHERE color_id=11")
    db.execute("INSERT OR IGNORE INTO colors(color_id,name,rgb) VALUES(12,'Trans-Clear','FCFCFC')")
    for number, name, colour, quantity in [
        ('7b', 'Tire Smooth Small Dually', 11, 8),
        ('3001old', 'Brick 2 x 4 without Cross Support', 12, 1),
    ]:
        db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P',?,?)", (number, name))
        db.execute("UPDATE items SET name=? WHERE item_type='P' AND item_no=?", (name, number))
        db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged,checked,spare) VALUES('copy','P',?,?,?,0,0,0,0)", (number, colour, quantity))


def add_49a_long_figure(db):
    """4.9a: a figure with a long name and one missing component, for the Minifigures tab geometry."""
    name = 'Cavalry Soldier with Breastplate and Plumed Helmet'
    db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('M','long-fig',?)", (name,))
    db.execute("INSERT INTO copy_minifigs(copy_id,item_type,minifig_no,quantity,missing) VALUES('copy','M','long-fig',1,0)")
    template = dict(db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND item_type='P' AND parent_minifig IS NULL AND spare=0 LIMIT 1").fetchone())
    db.execute("INSERT OR IGNORE INTO items(item_type,item_no,name) VALUES('P','long-fig-torso','Torso')")
    row = dict(template, id=None, item_no='long-fig-torso', quantity=1, missing=1, damaged=0, checked=0, parent_minifig='long-fig', parent_minifig_type='M')
    db.execute('INSERT INTO copy_parts(' + ','.join(row) + ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values()))


def test_47e_part_facts_matching_and_quantity(app, bw):
    scanner = 'Parts inventory scanner event e5f5a61a-bdc7-41eb-a325-18af6d86de13'
    with admin.database(bw) as db, db:
        db.execute("UPDATE loose_stock SET note=? WHERE item_type='P'", (scanner,))
        db.execute("UPDATE copy_minifigs SET missing=0")
        db.execute("UPDATE copy_parts SET missing=1,damaged=0 WHERE item_type='P' AND item_no='bl-part' AND parent_minifig IS NULL")
        detail = collection.detail(db, 'P', 'bl-part', colour=11)
        assert detail['matches']
    soup = BeautifulSoup(logged_in(app).get('/collection/item/P/bl-part?colour=11').data, 'html.parser')
    assert [n.get_text() for n in soup.select('[data-module=info] dt')][:4] == ['Condition', 'Damaged', 'Quantity', 'Storage']
    assert soup.select_one('.bc-quantity-pill:not(.bc-condition-pill)').get_text() == '×'+str(sum(r['quantity'] for r in detail['instances']))
    matching = soup.select_one('[data-module=matching]')
    assert matching.h3.get_text() == detail['matching_headline']
    assert 'Loose stock against recorded gaps' not in matching.get_text()
    assert scanner not in matching.get_text()
    assert matching.select_one('[data-bc-row][title]')['title'] == scanner
    assert collection.matching_note(scanner+' · Keep in drawer') == 'Keep in drawer'
    assert collection.matching_note(scanner) == ''
    assert collection.matching_note('Parts inventory scanner event e5f5a61abdc741eba32518af6d86de13a1b2 · Note') == 'Note'
    assert collection.matching_note('Parts inventory scanner event e5f5a61abdc741eba32518af6d86de13a1b2.') == ''
    assert collection.matching_note('Keep in drawer') == 'Keep in drawer'


def test_ui16_matching_leaves_set_detail_and_edit_panel_holds_instances_and_photos(app,bw):
    client=logged_in(app)
    set_page=BeautifulSoup(client.get('/collection/item/S/new-set?copy=copy').data,'html.parser')
    assert not set_page.select('[data-module=matching]')
    for url in ('/collection/item/S/new-set?copy=copy','/collection/item/P/bl-part?colour=11','/collection/item/M/bl-figure?stock=loose-figure'):
        soup=BeautifulSoup(client.get(url).data,'html.parser')
        assert bool(soup.select('[data-module=matching]'))==(not url.startswith('/collection/item/S'))
        layout=soup.select_one('.bc-detail-layout')
        assert not layout.select('.bc-own-photos') and not [h for h in layout.select('h2') if h.get_text().startswith('Instances')]
        panel=soup.select_one('dialog#bc-edit')
        headings=[h.get_text() for h in panel.select('.bc-edit-section > h3')]
        assert any(h.startswith('Instances') for h in headings) and 'Own photos' in headings
        assert panel.select_one('form[data-bc-action=save]') and panel.select_one('.bc-own-photos form[data-bc-action=photo]')
        assert panel.select_one('.bc-edit-section[data-bc-list] [data-bc-rows]')
