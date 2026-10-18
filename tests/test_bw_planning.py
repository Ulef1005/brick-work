"""Planning uses real migration fixtures, audited saves, and bounded queries."""
import json
from pathlib import Path
import sqlite3
from datetime import timedelta
from decimal import Decimal
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
import pytest

from brickwork.core import admin, collection, planning, workbench
from brickwork.core.sources.base import now
from brickwork.web.formatting import money
from tests.test_bw_collection import bw, token
from tests.importer.test_importer import legacy
from tests.web_fixtures import app, logged_in
from tests.web_fixtures import apps
from tests.test_bw_admin import reset_shell_metadata_after_test


@pytest.mark.parametrize('screen',['wishlist','prices','complete-sets'])
def test_screen(app,bw,screen):
    r=logged_in(app).get('/planning/'+screen)
    assert r.status_code==200,r.get_data(as_text=True)
    s=BeautifulSoup(r.data,'html.parser')
    assert s.select_one('[data-web-ui="toni"]')
    assert s.select_one('[data-bp-search]')
    assert s.select_one('[data-bp-sort]')
    assert s.select_one('[data-bp-filters]')
    assert r.headers['Cache-Control']=='no-store'
    for name in ['wishlist','prices','complete-sets']:
        assert s.select_one('a[href="/planning/'+name+'"]')
    assert not s.select_one('a[href="/complete-sets"]')
    assert 'alerts unavailable' not in s.get_text() and 'Wanted watch' not in s.get_text()
    if screen=='wishlist': assert [b.text for b in s.select('.bp-price-filter [data-bp-pick=under]')]==['Under max','Over max','No max set','Not comparable']


@pytest.mark.parametrize('screen', ['wishlist', 'complete-sets'])
def test_planning_row_reading_order_and_controls(app, bw, screen):
    """Compact content precedes row actions; closed Details keeps them reachable."""
    soup = BeautifulSoup(logged_in(app).get('/planning/' + screen).data, 'html.parser')
    rows = soup.select('[data-bp-row]')
    assert rows
    for row in rows:
        blocks = row.find_all(recursive=False)
        if screen == 'complete-sets':
            assert [c['class'][0] for c in blocks] == ['bp-ordinal', 'bc-picture', 'bp-repair-body', 'bp-row-actions']
            body = blocks[2]
            assert body
            details = body.select_one('.bp-repair-details')
            assert not details.has_attr('open')
            actions = blocks[3]
            assert actions.select_one('[data-bp-selected]')
            assert actions.select_one('[data-bp-pin]')
            assert not actions.find_parent('details')
            assert not details.select('input, select, button')
            assert [c['class'][0] for c in body.find_all(recursive=False)] == ['bp-identity', 'bp-values']
            continue
        assert 'bp-identity' in blocks[0]['class']
        assert 'bp-values' in blocks[1]['class']
        picture = blocks[0].select_one('.bc-picture')
        identity_text = blocks[0].find_all(recursive=False)[-1]
        assert 'bc-picture' in picture['class']
        assert identity_text.select_one('.bc-identity')
        assert not blocks[0].select('input:not([data-wl-selected]), select, button')
        assert blocks[0].select_one('[data-wl-selected]')
        if screen == 'wishlist':
            assert len(blocks) == 2
            assert not blocks[1].select('.bp-records, form, button')
        for control in row.select('input, select, button, form'):
            assert 'position' not in control.get('style', '')
    message = soup.select_one('[data-bp-message]')
    assert not message.get_text(strip=True)  # CSS gives an empty live region no box.
    assert soup.select_one('#bp-filters').has_attr('hidden')
    if screen == 'complete-sets':
        settings = soup.select_one('[data-bp-action="settings"]')
        assert settings.parent.name == 'details'
        assert not settings.parent.has_attr('open')


def test_planning_prices_round_for_display_only(app, bw):
    with admin.database(bw) as db:
        with db:
            db.execute("UPDATE wishlist SET max_price='163.01234'")
            db.execute("UPDATE price_observations SET price='181.9484',min='5.439',max='280.0'")
    client = logged_in(app)
    # Prices: the compact records and the on-demand details carry display text only.
    records = client.get('/planning/prices/records')
    assert '181.9484' not in records.get_data(as_text=True)
    decoded = json.loads(records.data)
    row = next(r for r in decoded['rows'] if r[decoded['fields'].index('price')] == '€181.95')
    key = dict(zip(decoded['fields'], row))
    details = client.get('/planning/prices/details', query_string=dict(kind=key['type'], number=key['number'], **({'colour': key['color_id']} if key['color_id'] is not None else {}))).get_json()
    quotes = [q for g in details['groups'] for q in g['quotes']]
    assert quotes and '€181.95' in quotes[0]['head'] and '181.9484' not in json.dumps(details)
    for quote in quotes:
        if 'range' in quote:
            assert '€5.44' in quote['min'] and '€280' in quote['max']
    for screen in ('wishlist',):
        soup = BeautifulSoup(client.get('/planning/' + screen).data, 'html.parser')
        if screen == 'wishlist':
            wish = soup.select_one('[data-bp-row] .bp-identity a[href*=wishes]')['href']
            detail = BeautifulSoup(client.get(wish).data, 'html.parser')
        quotes = detail.select('.bc-price-records .bc-price')
        assert quotes
        assert '181.95' in quotes[0].get_text()
        assert '181.9484' not in soup.get_text()
        if screen == 'wishlist':
            assert '163.01' in soup.select_one('.bp-values').get_text()
            wish = soup.select_one('[data-bp-row] .bp-identity a[href*=wishes]')['href']
            detail = BeautifulSoup(client.get(wish).data, 'html.parser')
            assert detail.select_one('input[name=max_price]')['value'] == '163.01234'
    with admin.database(bw) as db:
        assert db.execute('SELECT max_price FROM wishlist').fetchone()[0] == '163.01234'
        assert db.execute('SELECT price FROM price_observations').fetchone()[0] == '181.9484'


def submit(client,csrf,action,**data):
    return client.post('/planning/action/'+action,json=dict(csrf_token=csrf,**data))


def test_pin_settings_undo_conflict(app,bw):
    c=logged_in(app);csrf=token(c)
    r=submit(c,csrf,'pin',id='copy',pinned=True)
    assert r.status_code==200,r.json
    with admin.database(bw) as db:
        assert db.execute("SELECT pinned FROM copies WHERE id='copy'").fetchone()[0]==1
        assert db.execute('SELECT via FROM events WHERE id=?',(r.json['event_id'],)).fetchone()[0]=='app'
    assert submit(c,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db:
        old={k:planning.configuration(db)[k] for k in planning.REPAIR_KEYS}
    values=dict(repair_shipping='4.5',repair_fees='0',repair_min_order='12',repair_use_loose_stock='1',incomplete_discount_pct='30.5')
    r=submit(c,csrf,'settings',values=values);assert r.status_code==200,r.json
    with admin.database(bw) as db:
        assert planning.ranking(db)['settings']['incomplete_discount_pct']==Decimal('30.5')
    other=submit(c,csrf,'settings',values=dict(values,repair_fees='1'))
    assert submit(c,csrf,'undo',event_id=r.json['event_id']).status_code==400
    assert submit(c,csrf,'undo',event_id=other.json['event_id']).status_code==200
    assert submit(c,csrf,'undo',event_id=r.json['event_id']).status_code==200
    with admin.database(bw) as db:
        assert {k:planning.configuration(db)[k] for k in planning.REPAIR_KEYS}==old
    assert submit(c,csrf,'settings',values=dict(values,repair_shipping='NaN')).status_code==400
    assert submit(c,csrf,'pin',id='copy',pinned='false').status_code==400
    assert c.post('/planning/action/pin',json=dict(id='copy',pinned=True)).status_code in (400,403)
    app.config['BW_READ_ONLY']=True
    assert submit(c,csrf,'pin',id='copy',pinned=True).status_code==403


def evidence(db):
    with db:
        db.execute('UPDATE copies SET condition=\'U\', current_value=NULL, current_value_currency=NULL')
        db.execute('UPDATE copy_parts SET missing=0,damaged=0')
        db.execute('UPDATE copy_minifigs SET missing=0')
        part=db.execute("SELECT * FROM copy_parts WHERE item_type='P' AND parent_minifig IS NULL AND coalesce(spare,0)=0 LIMIT 1").fetchone()
        db.execute('UPDATE copy_parts SET missing=2,damaged=1 WHERE id=?',(part['id'],))
        for kind,number,colour,price in [('S','new-set',None,'100'),(part['item_type'],part['item_no'],part['color_id'],'2')]:
            identifier=db.execute('''INSERT INTO price_observations(item_type,item_no,color_id,condition,guide,region,currency,price,qty,sold,min,max,source,observed_at)
                VALUES(?,?,?,'U','sold','eu','EUR',?,10,10,'1','101','bricklink',?)''',(kind,number,colour,price,now().isoformat())).lastrowid
            db.execute("DELETE FROM price_current WHERE item_type=? AND item_no=? AND color_id IS ?",(kind,number,colour))
            db.execute("INSERT INTO price_current(item_type,item_no,color_id,condition,guide,region,currency,observation_id) VALUES(?,?,?,'U','sold','eu','EUR',?)",(kind,number,colour,identifier))
        for key,value in dict(bricklink_region='eu',bricklink_currency='EUR',incomplete_discount_pct='30',repair_shipping='3',repair_fees='0.5',repair_min_order='10',repair_use_loose_stock='0').items():
            db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
    return dict(part)


def test_economics_gap_stock_export(app,bw):
    with admin.database(bw) as db:
        part=evidence(db)
        row=next(r for r in planning.ranking(db)['rows'] if r['id']==part['copy_id'])
        assert row['original_gap']==3 and row['missing_count']==3
        assert row['repair_cost']==Decimal('13.5')
        assert row['net_gain']==Decimal('16.5')
        with db:
            db.execute("UPDATE settings SET value='1' WHERE key='repair_use_loose_stock'")
            # A migrated matching stock row is increased using the only stock path.
            from brickwork.core.stock import add_loose
            add_loose(db,[],item_type=part['item_type'],item_no=part['item_no'],color_id=part['color_id'],quantity=3,condition='U')
        row=next(r for r in planning.ranking(db)['rows'] if r['id']==part['copy_id'])
        assert row['stock_used']==3 and row['missing_count']==0
        assert row['repair_cost']==Decimal('13.5') # minimum order remains in force
        assert not ET.fromstring(planning.export(db,[part['copy_id']])).findall('ITEM')
        with db: db.execute("UPDATE settings SET value='0' WHERE key='repair_use_loose_stock'")
        root=ET.fromstring(planning.export(db,[part['copy_id']]))
        assert root.findtext('ITEM/MINQTY')=='3'
        assert root.findtext('ITEM/ITEMID')==part['item_no']
        gap=workbench.requested_gap(db,part,part['copy_id'],'part',part['id'])
        assert gap['need']==3
    client=logged_in(app);csrf=token(client)
    r=submit(client,csrf,'export',ids=[part['copy_id']]);assert r.status_code==200
    assert r.mimetype=='application/xml'


def test_refresh_only_queues_and_unknown_atomic(app,bw, planning_worker):
    def committed():
        with admin.database(bw, read_only=True) as db:
            assert db.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0] == 1
    planning_worker.side_effect = committed
    c=logged_in(app);csrf=token(c)
    with admin.database(bw) as db: evidence(db)
    r=submit(c,csrf,'refresh',items=[['S','new-set'],['S','new-set']]);assert r.status_code==200,r.json
    with admin.database(bw) as db:
        assert len(r.json['jobs'])==1
        planning_worker.assert_called_once_with()
        job=db.execute('SELECT * FROM jobs WHERE id=?',(r.json['jobs'][0],)).fetchone()
        assert job['state']=='queued'
        assert db.execute('SELECT name FROM import_steps WHERE job_id=?',(job['id'],)).fetchone()[0]=='market_price'
        assert db.execute("SELECT via FROM events WHERE entity=?",('job:'+str(job['id']),)).fetchone()[0]=='app'
        count=db.execute('SELECT count(*) FROM jobs').fetchone()[0]
    assert submit(c,csrf,'refresh',items=[['S','new-set'],['S','unknown']]).status_code==400
    with admin.database(bw) as db: assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==count
    planning_worker.assert_called_once_with()


def test_prices_kind_query_and_freshness(bw):
    with admin.database(bw) as db:
        evidence(db)
        with db: db.execute("UPDATE price_observations SET observed_at=? WHERE item_type='S'",((now()-timedelta(days=400)).isoformat(),))
        traces=[];db.set_trace_callback(traces.append)
        rows=planning.priced_items(db,'S')
        assert rows and all(r['item_type']=='S' for r in rows)
        assert any(r['stale'] for r in rows)
        query=next(s for s in traces if 'JOIN price_observations' in s)
        assert "WHERE p.item_type='S'" in query
        assert any(r['group']=='needs_evidence' for r in planning.ranking(db)['rows'])


@pytest.mark.parametrize('project',[planning.wishes,planning.priced_items,planning.ranking])
def test_constant_list_queries(bw,project):
    with admin.database(bw) as db:
        evidence(db)
        def count():
            statements=[];db.set_trace_callback(statements.append);project(db);db.set_trace_callback(None)
            return len([s for s in statements if s.lstrip().upper().startswith('SELECT')])
        small=count()
        with db:
            for i in range(300):
                db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S',?,?)",('bulk'+str(i),'Bulk '+str(i)))
                db.execute("INSERT INTO copies(id,set_no,condition,pinned) VALUES(?,?,'U',0)",('bulk'+str(i),'bulk'+str(i)))
                observation=db.execute("INSERT INTO price_observations(item_type,item_no,condition,guide,source,price,observed_at) VALUES('S',?,'U','sold','bricklink','2',?)",('bulk'+str(i),now().isoformat())).lastrowid
                db.execute("INSERT INTO price_current(item_type,item_no,condition,guide,observation_id) VALUES('S',?,'U','sold',?)",('bulk'+str(i),observation))
                db.execute("INSERT INTO wishlist(item_type,item_no) VALUES('S',?)",('bulk'+str(i),))
                db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged) SELECT ?,item_type,item_no,color_id,1,1,0 FROM copy_parts LIMIT 1",('bulk'+str(i),))
        assert count()<=small+2


def test_shell_footer_clearance():
    from pathlib import Path
    shell=Path('static/web/toni/shell.css').read_text()
    assert '.footer{padding-bottom:calc(20px + var(--bw-bottom))}' in shell
    assert '[data-bc-list] { padding-bottom:' not in Path('static/web/toni/bw-collection.css').read_text()


def test_stock_not_double_counted_reserved_or_archived(bw):
    from brickwork.core.stock import add_loose
    with admin.database(bw) as db:
        p=evidence(db)
        with db:
            db.execute("DELETE FROM loose_stock WHERE item_type='P'")
            db.execute("UPDATE settings SET value='1' WHERE key='repair_use_loose_stock'")
            db.execute("INSERT INTO copies(id,set_no,condition) VALUES('zz-copy','new-set','U')")
            db.execute("INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged) VALUES('zz-copy',?,?,?,3,3,0)",(p['item_type'],p['item_no'],p['color_id']))
            identifier,_=add_loose(db,[],item_type=p['item_type'],item_no=p['item_no'],color_id=p['color_id'],quantity=4,condition='U')
        rows=planning.ranking(db)['rows']
        assert sum(r['stock_used'] for r in rows)==4
        assert {r['id']:r['stock_used'] for r in rows}=={'copy':3,'zz-copy':1}
        with db:
            db.execute("INSERT INTO allocations(kind,part_type,part,color,qty,state) VALUES('missing_part',?,?,?,2,'pending')",(p['item_type'],p['item_no'],p['color_id']))
        assert sum(r['stock_used'] for r in planning.ranking(db)['rows'])==2
        with db: db.execute('UPDATE loose_stock SET archived_at=? WHERE id=?',(now().isoformat(),identifier))
        assert sum(r['stock_used'] for r in planning.ranking(db)['rows'])==0


def test_damaged_transfer_and_undo_share_gap(bw):
    from brickwork.core.stock import add_loose
    with admin.database(bw) as db:
        p=evidence(db)
        with db:
            db.execute('UPDATE copy_parts SET missing=0,damaged=2 WHERE id=?',(p['id'],))
            identifier,_=add_loose(db,[],item_type=p['item_type'],item_no=p['item_no'],color_id=p['color_id'],quantity=2,condition='U')
        assert next(g for g in workbench.gaps(db) if g.get('id')==p['id'])['need']==2
        event=workbench.transfer(db,identifier,p['copy_id'],'part',p['id'],2)
        assert db.execute('SELECT missing,damaged FROM copy_parts WHERE id=?',(p['id'],)).fetchone()[:]==(0,0)
        assert not planning.ranking(db)['rows']
        workbench.undo(db,event)
        assert db.execute('SELECT missing,damaged FROM copy_parts WHERE id=?',(p['id'],)).fetchone()[:]==(0,2)


def test_wishlist_uses_collection_save_archive_undo(app,bw):
    client=logged_in(app);csrf=token(client)
    with admin.database(bw) as db: identifier=db.execute('SELECT id FROM wishlist LIMIT 1').fetchone()[0]
    r=client.post('/collection/save/save',json=dict(csrf_token=csrf,entity='wish',ids=[identifier],values=dict(max_price='25',quantity=2,condition='used')))
    assert r.status_code==200,r.json
    body=client.get('/collection/wishes/'+str(identifier)).get_data(as_text=True)
    assert '2 wanted · used' in body and 'value="25"' in body
    r=client.post('/collection/save/archive',json=dict(csrf_token=csrf,entity='wish',ids=[identifier],values={}))
    assert r.status_code==200
    assert not BeautifulSoup(client.get('/planning/wishlist').data,'html.parser').select('[data-bp-row]')
    assert client.post('/collection/save/undo',json=dict(csrf_token=csrf,event_id=r.json['event_id'])).status_code==200
    assert BeautifulSoup(client.get('/planning/wishlist').data,'html.parser').select('[data-bp-row]')


def test_save_query_count(bw):
    with admin.database(bw) as db:
        for i in range(300):
            with db: db.execute("INSERT INTO copies(id,set_no,condition) VALUES(?,'new-set','U')",('save'+str(i),))
        for action,data in [('pin',dict(id='copy',pinned=True)),('settings',dict(values=dict(repair_shipping='3',repair_fees='1',repair_min_order='0',repair_use_loose_stock='0',incomplete_discount_pct='30')))]:
            traces=[];db.set_trace_callback(traces.append);event=planning.save(db,action,data);db.set_trace_callback(None)
            assert len(traces)<=8
            traces=[];db.set_trace_callback(traces.append);planning.undo(db,event);db.set_trace_callback(None)
            assert len(traces)<=8


def test_refresh_query_growth_linear(app,bw):
    client=logged_in(app);csrf=token(client)
    keys=[['S','refresh-'+str(i)] for i in range(300)]
    with admin.database(bw) as db,db:
        db.executemany('INSERT INTO items(item_type,item_no) VALUES(?,?)',keys)
    traces=[]
    from brickwork.core import connect as connection_module
    original=connection_module.connect
    # admin imported the connector by name; restore automatically with MonkeyPatch.
    with pytest.MonkeyPatch.context() as monkeypatch:
        def traced(*args,**kwargs):
            db=original(*args,**kwargs);db.set_trace_callback(traces.append);return db
        monkeypatch.setattr(admin,'connect',traced)
        r=submit(client,csrf,'refresh',items=keys)
    assert r.status_code==200,r.json
    assert len(r.json['jobs'])==300
    assert len(traces)<300*8+80


def test_whole_figure_covers_damaged_constituents_and_undo(bw):
    from brickwork.core.stock import add_loose
    with admin.database(bw) as db:
        with db:
            db.execute('UPDATE copy_parts SET missing=0,damaged=0')
            db.execute('UPDATE copy_minifigs SET missing=0')
            figure=db.execute("SELECT * FROM copy_minifigs WHERE item_type='M' LIMIT 1").fetchone()
            db.execute('UPDATE copy_minifigs SET missing=1 WHERE copy_id=? AND item_type=? AND minifig_no=?',(figure['copy_id'],figure['item_type'],figure['minifig_no']))
            part=db.execute('SELECT * FROM copy_parts WHERE copy_id=? AND coalesce(spare,0)=0 LIMIT 1',(figure['copy_id'],)).fetchone()
            db.execute('UPDATE copy_parts SET parent_minifig_type=?,parent_minifig=? WHERE id=?',(figure['item_type'],figure['minifig_no'],part['id']))
            db.execute('UPDATE copy_parts SET missing=0,damaged=quantity WHERE id=?',(part['id'],))
            identifier,_=add_loose(db,[],item_type=figure['item_type'],item_no=figure['minifig_no'],color_id=None,quantity=1,condition='U')
        assert not [g for g in workbench.gaps(db) if g.get('id')==part['id']]
        event=workbench.transfer(db,identifier,figure['copy_id'],'figure',figure['minifig_no'],1)
        assert db.execute('SELECT damaged FROM copy_parts WHERE id=?',(part['id'],)).fetchone()[0]==0
        workbench.undo(db,event)
        assert db.execute('SELECT damaged FROM copy_parts WHERE id=?',(part['id'],)).fetchone()[0]==part['quantity']


@pytest.fixture(autouse=True)
def planning_worker(monkeypatch):
    from unittest.mock import Mock
    worker = Mock()
    monkeypatch.setattr('brickwork.web.views.bw_start_worker', worker)
    return worker


@pytest.mark.parametrize('action', ['refresh', 'export', 'pin'])
def test_planning_actions_require_login(app, bw, action):
    response = app.test_client().post('/planning/action/' + action, json={})
    assert response.status_code == 302 and '/login' in response.location


def test_export_available_when_read_only(app, bw, monkeypatch):
    client = logged_in(app); csrf = token(client)
    with admin.database(bw) as db: evidence(db)
    monkeypatch.setitem(app.config, 'BW_READ_ONLY', True)
    assert submit(client, csrf, 'export', ids=['copy']).status_code == 200


@pytest.mark.parametrize('screen', ['wishlist','prices','complete-sets'])
def test_run3_shared_toolbar_no_breadcrumb(app,bw,screen):
    soup=BeautifulSoup(logged_in(app).get('/planning/'+screen).data,'html.parser')
    assert not soup.select('.breadcrumb')
    toolbar=soup.select_one('.bc-toolbar')
    assert toolbar.select_one('.bc-search input[data-bp-search]')
    assert toolbar.select_one('button[data-bp-filters]')
    assert toolbar.select_one('button[data-bp-sort-open]')
    assert not toolbar.select('select')
    assert soup.select_one('.bc-sort-options[hidden] select[data-bp-sort]')
    assert all('bw-primary' in b['class'] for b in soup.select('#bw-planning .primary'))


def test_run3_wishlist_count_conditions_and_records(app,bw):
    with admin.database(bw) as db:
        with db: db.execute('UPDATE wishlist SET quantity=3')
        rows=planning.wishes(db)
        quantity=sum(r['quantity'] for r in rows)
    soup=BeautifulSoup(logged_in(app).get('/planning/wishlist').data,'html.parser')
    assert soup.h1.get_text(strip=True)==f"{quantity} sets wanted"
    # 4.9d w2/w3 + 12k: condition chips All, Used, New (All carries the count), then the Price filter row.
    chips=soup.select('.bp-visible-chips button')
    unfilled=sum(1 for r in rows if not r['filled'])  # #35: the Not yet filled chip follows the conditions
    assert [b.get_text(strip=True) for b in chips]==['All'+str(len(soup.select('[data-bp-row]'))),'Used','New','Not yet filled'+str(unfilled),'Under max','Over max','No max set','Not comparable']
    assert chips[0].select_one('.bp-chip-count').text==str(len(soup.select('[data-bp-row]')))
    assert soup.select_one('[data-bp-search]')['placeholder']=='Number or name'
    for row in soup.select('[data-bp-row]'):
        assert not row.select('.bp-records, [data-bp-archive], input:not([data-wl-selected])')
        assert row.select_one('[data-wl-selected]')
        detail = BeautifulSoup(logged_in(app).get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
        assert '3 wanted' in detail.select_one('.bc-wish-facts').text
        assert detail.select_one('#bc-delete form[data-bc-action=archive]')



def test_run3_prices_priority_history_lookup_and_chips(app,bw):
    with admin.database(bw) as db, db:
        # The migrated identity has current prices; superseded observations are
        # displayed through the same selection function as Collection details.
        for source,value,date in [('bricklink','12','2026-10-08'),('bricklink','10','2026-10-01'),('rebrickable','99','2026-10-09')]:
            db.execute("""INSERT INTO price_observations(item_type,item_no,condition,guide,currency,source,price,observed_at)
                VALUES('S','new-set','U','sold','EUR',?,?,?)""",(source,value,date))
    client=logged_in(app)
    soup=BeautifulSoup(client.get('/planning/prices?kind=S').data,'html.parser')
    assert soup.select_one('[data-bp-lookup-query]')['placeholder']=='Look up any number'
    assert not soup.select('form select[name=kind]')
    assert soup.select_one('#bw-planning')['data-kind']=='S'
    with admin.database(bw) as db:
        available={r[0] for r in db.execute('SELECT DISTINCT item_type FROM price_current')}
    assert {b['data-value'] for b in soup.select('.bp-visible-chips [data-bp-chip=type]')}==available
    assert [n.text for n in soup.select('.bp-price-columns span')] == ['Item','Kind','Price','Age']
    data=client.get('/planning/prices/records').get_json()
    rows=[dict(zip(data['fields'],r)) for r in data['rows']]
    row=next(r for r in rows if r['number']=='new-set')
    # Priority first, then the freshest: the superseded bricklink 12 wins over the rebrickable 99.
    assert row['price']=='€12.00' and not row['listings']
    details=client.get('/planning/prices/details',query_string=dict(kind='S',number='new-set')).get_json()
    text=json.dumps(details,ensure_ascii=False)
    assert '€99.00' in text and '€10.00' in text and 'EUR 12' not in text
    assert details['selected'].startswith('Used') and '€12.00' in details['selected']
    selected=client.get('/collection/jump?q=new-set')
    assert selected.status_code==200 and selected.json['results']


@pytest.mark.parametrize('pinned', [False, True])
def test_run3_repair_recommendation_and_proportional_bars(app,bw,pinned):
    with admin.database(bw) as db:
        evidence(db)
        with db:
            original=db.execute("SELECT * FROM copy_parts WHERE copy_id='copy' AND missing>0 LIMIT 1").fetchone()
            db.execute("UPDATE copies SET pinned=?,current_value='80',current_value_currency='EUR' WHERE id='copy'", (pinned,))
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S','best-set','Best set')")
            identifier=db.execute("""INSERT INTO price_observations(item_type,item_no,condition,guide,region,currency,price,sold,source,observed_at)
                VALUES('S','best-set','U','sold','eu','EUR','100',10,'bricklink',?)""", (now().isoformat(),)).lastrowid
            db.execute("""INSERT INTO price_current(item_type,item_no,condition,guide,region,currency,observation_id)
                VALUES('S','best-set','U','sold','eu','EUR',?)""", (identifier,))
            db.execute("INSERT INTO copies(id,set_no,condition,current_value,current_value_currency) VALUES('second','best-set','U','71.65','EUR')")
            db.execute("""INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged)
                VALUES('second',?,?,?,3,1,0)""",(original['item_type'],original['item_no'],original['color_id']))
        ranked=planning.ranking(db)['ranked']
        assert len(ranked)==2
        best=next(r for r in ranked if r['rank']==1)
        assert best['id']=='second' and best['ratio']==Decimal('2.10')
    soup=BeautifulSoup(logged_in(app).get('/planning/complete-sets').data,'html.parser')
    assert soup.h1.get_text(strip=True)=="Repair best-set first: 2.10 gained per 1 spent" + (' · pins listed first' if pinned else '')
    rows=[r for r in soup.select('[data-bp-row]') if json.loads(r['data-record'])['group']=='ranked']
    assert [int(r.select_one('.bp-ordinal').get_text()) for r in rows]==([2,1] if pinned else [1,2])
    assert not any(p.get_text(strip=True)=='Ranked' for r in rows for p in r.select('.bc-status'))
    widths=[float(r.select_one('.bp-ratio-track i')['style'].split(':')[1].rstrip('%')) for r in rows]
    assert widths==pytest.approx([float(r['ratio']/best['ratio']*100) for r in ranked])
    with admin.database(bw) as db, db: db.execute('UPDATE price_observations SET observed_at=?',((now()-timedelta(days=400)).isoformat(),))
    empty=BeautifulSoup(logged_in(app).get('/planning/complete-sets').data,'html.parser')
    assert empty.h1.get_text()=='Complete sets'


@pytest.mark.parametrize('screen',['wishlist','prices','complete-sets'])
def test_run3_rendered_list_queries_constant(app,bw,monkeypatch,screen):
    client=logged_in(app)
    with admin.database(bw) as db: evidence(db)
    original=admin.connect
    statements=[]
    def traced(*args,**kwargs):
        db=original(*args,**kwargs);db.set_trace_callback(statements.append);return db
    monkeypatch.setattr(admin,'connect',traced)
    def count():
        statements.clear()
        response=client.get('/planning/'+screen)
        assert response.status_code==200
        return len([s for s in statements if s.lstrip().upper().startswith('SELECT')])
    small=count()
    with admin.database(bw) as db, db:
        for i in range(300):
            number='render-bulk-'+str(i)
            db.execute("INSERT INTO items(item_type,item_no,name) VALUES('S',?,'Bulk')",(number,))
            db.execute("INSERT INTO copies(id,set_no,condition) VALUES(?,?,'U')",(number,number))
            db.execute("INSERT INTO wishlist(item_type,item_no) VALUES('S',?)",(number,))
            oid=db.execute("""INSERT INTO price_observations(item_type,item_no,condition,guide,currency,region,source,price,observed_at)
                VALUES('S',?,'U','sold','EUR','eu','bricklink','100',?)""",(number,now().isoformat())).lastrowid
            db.execute("INSERT INTO price_current(item_type,item_no,condition,guide,observation_id) VALUES('S',?,'U','sold',?)",(number,oid))
            db.execute("""INSERT INTO copy_parts(copy_id,item_type,item_no,color_id,quantity,missing,damaged)
                SELECT ?,item_type,item_no,color_id,3,1,0 FROM copy_parts WHERE copy_id='copy' LIMIT 1""",(number,))
    assert count()<=small+3


def test_run3_price_header_and_rows_share_four_columns():
    import re
    from pathlib import Path
    css = Path('static/web/toni/bw-planning.css').read_text()
    rule = re.search(r'\.bp-price-columns,\.bp-prices \.bp-row\s*\{([^}]+)\}', css).group(1)
    template = re.search(r'grid-template-columns:([^;]+)', rule).group(1)
    assert template == 'minmax(0,1.5fr) minmax(100px,.7fr) minmax(0,1.2fr) minmax(160px,.4fr)'
    assert '.bp-price-columns span:nth-child(3)' not in css
    # The only row override is inside the phone media query, where the header is hidden.
    assert len(re.findall(r'\.bp-prices \.bp-row\s*\{', css)) == 2
    phone = css.split('@media(max-width:767.98px)')[1]
    assert '.bp-price-columns { display:none; }' in phone
    assert '.bp-prices .bp-row { grid-template-columns:56px minmax(0,1fr) auto;' in phone


def test_run4_wishlist_hierarchy_and_details(app, bw):
    from pathlib import Path
    with admin.database(bw) as db, db:
        db.execute("UPDATE wishlist SET note='Keep this wish note',quantity=3,condition=NULL")
    soup=BeautifulSoup(logged_in(app).get('/planning/wishlist').data,'html.parser')
    for row in soup.select('[data-bp-row]'):
        assert not row.select('.bp-records')
        detail = BeautifulSoup(logged_in(app).get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
        facts = detail.select_one('.bc-wish-facts')
        assert 'Max in EUR' in facts.text and 'Age not recorded' in facts.text
        assert 'Keep this wish note' in facts.text and '3 wanted' in facts.text
        assert detail.select_one('#bc-edit form[data-bc-action=save]')
        assert row.select_one('.bp-max-label').text=='Your max price'
        assert row.select_one('.bp-max strong.mono')
        assert row.select_one('.bp-wish-number .bc-status').text=='Wants unknown'
        assert 'Currency not recorded' not in row.text and '3 wanted' not in row.text
        assert 'Keep this wish note' not in row.text
    assert soup.select_one('[data-bp-pick=condition][data-value=""]')['aria-pressed']=='true'
    css=Path('static/web/toni/bw-planning.css').read_text()
    assert 'font:600 20px/26px var(--tw-mono)' in css
    assert '.bp-visible-chips { display:flex;gap:8px;' in css
    assert '[aria-pressed=true] { background:var(--tw-accent-soft)' in css


def test_run4_prices_lookup_and_compact_rows(app, bw):
    from pathlib import Path
    soup=BeautifulSoup(logged_in(app).get('/planning/prices').data,'html.parser')
    assert soup.select_one('.bp-lookup label svg')
    assert soup.select_one('.bp-lookup-action').text=='Look up'
    assert not soup.select('[data-bp-row]')  # rows are rendered by the client from the compact records
    css=Path('static/web/toni/bw-planning.css').read_text()
    assert '.bp-lookup input { background:var(--tw-surface);border:0;' in css
    assert 'border-color:var(--tw-accent);color:var(--tw-accent-text)' in css
    assert 'padding-block:10px;align-items:center;' in css
    assert '.bp-values { display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;' in css


def test_run4_repair_details_preserve_evidence_and_actions(app, bw):
    from pathlib import Path
    with admin.database(bw) as db:
        evidence(db)
        expected=planning.ranking(db)
    soup=BeautifulSoup(logged_in(app).get('/planning/complete-sets').data,'html.parser')
    assert soup.select('[data-bp-row]')
    for row in soup.select('[data-bp-row]'):
        record=json.loads(row['data-record'])
        original=next(r for r in expected[record['group']] if r['id']==record['id'])
        details=row.select_one('.bp-repair-details')
        assert details.summary.select_one('.bp-details-label').text=='Details' and not details.has_attr('open')
        assert f"{original['stock_used']} in loose stock" in details.text
        assert f"{original['missing_count']} to buy" in details.text
        assert original['label'] in details.text and {'S':'Sealed','C':'Complete','I':'Incomplete'}.get(original['completeness'],'Unknown') in details.text
        assert row.select_one('[data-bp-selected]')['value']==original['id']
        assert row.select_one('[data-bp-pin]')
        assert not row.select_one('[data-bp-selected]').find_parent('details')
        assert not row.select_one('[data-bp-pin]').find_parent('details')
        if original['reasons']:
            for reason in original['reasons']: assert reason in details.text
        else:
            for text in ('Parts','shipping','fees','minimum order extra','Complete','current',original['valuation_basis']):
                assert text in details.text
            assert row.select_one('.bp-repair-numbers')
        details.decompose()
        assert 'in loose stock' not in row.text
        assert row.select_one('[data-bp-selected]') and row.select_one('[data-bp-pin]')
        assert 'shipping' not in row.text and 'net gain' not in row.text
    css=Path('static/web/toni/bw-planning.css').read_text()
    assert 'grid-template-columns:20px 56px minmax(0,1fr)' in css
    assert '.bp-repair-numbers { margin:0;font:400 12px/14px' in css
    assert '.bp-repair-details > summary { min-height:14px;padding:0;' in css
    import re
    assert not re.search(r'\bdisplay\s*:\s*contents|\border\s*:', css)


@pytest.mark.parametrize('quotes, expected, label', [
    ([('N', 'retail', 'retail', 'brickset', '90')], None, None),
    ([('U', 'sold', 'boxed', 'bricklink', '80')], None, None),
    ([('U', 'sold', 'used_set', 'bricklink', '12'),
      ('N', 'sold', 'new_set', 'bricklink', '24')], '24', 'New · new set'),
    ([('U', 'stock', 'used_set', 'bricklink', '15')], '15', 'Used listings · used set'),
    ([(None, 'stock', None, 'bricklink', '17')], '17', 'Price listings'),
    ([('U', 'stock', 'used_set', 'bricklink', '-5.9')], '-5.9', 'Used listings · used set'),
])
def test_compact_prices_market_only_and_recorded_labels(app, bw, quotes, expected, label):
    from tests.importer.test_importer import insert
    number = 'planning-price-case'
    with admin.database(bw) as db, db:
        insert(db, 'items', item_type='S', item_no=number, name='Price case')
        insert(db, 'wishlist', item_type='S', item_no=number, quantity=1, condition='any')
        for condition, guide, slot, source, value in quotes:
            record = dict(item_type='S', item_no=number, condition=condition,
                          guide=guide, slot=slot, currency='EUR', region='eu')
            insert(db, 'price_observations', **record, source=source, price=value,
                   observed_at=now().isoformat())
            identifier = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            insert(db, 'price_current', **record, observation_id=identifier)
        for rows in (planning.priced_items(db), planning.wishes(db)):
            row = next(r for r in rows if r['item_no'] == number)
            chosen = row['display_price']
            assert (chosen['price'] if chosen else None) == expected
            if chosen:
                assert chosen['guide'] in ('sold', 'stock') and chosen['slot'] != 'boxed'
                assert chosen['label'] == label
    client = logged_in(app)
    # Prices: the compact record and the on-demand details; the row markup is covered by the runtime harness.
    data = client.get('/planning/prices/records').get_json()
    record = next(dict(zip(data['fields'], r)) for r in data['rows'] if r[1] == number)
    details = client.get('/planning/prices/details', query_string=dict(kind='S', number=number)).get_json()
    assert sum(len(g['quotes']) for g in details['groups']) == len(quotes)
    if expected:
        assert record['price'] == money(expected, 'EUR', fixed=True) and record['listings'] == (quotes[-1][1] == 'stock')
        assert label in details['selected']
        assert 'Used' not in record['price'] and 'New' not in record['price']
    else:
        assert record['price'] is None and details['selected'] is None
    wish = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    row = next(r for r in wish.select('[data-bp-row]') if json.loads(r['data-record'])['number'] == number)
    assert row.select_one('.bp-records') is None
    detail = BeautifulSoup(client.get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
    assert len(detail.select('.bc-price-records .bc-price')) == len(quotes)
    if expected:
        compact = row.select_one('.bp-card-price')
        assert {'N': 'New', 'U': 'Used'}.get(quotes[-1][0], 'Price') in compact.text and ' · ' not in compact.text
        assert ('listings' in compact.text) == (quotes[-1][1] == 'stock')
        if expected == '-5.9':
            assert '€5.90 below' in compact.text
    else:
        assert 'no sales' in row.select_one('.bp-values').text and not row.select('.bp-card-price')


def test_repair_summary_wraps_above_details_css_contract(app, bw):
    import re
    from pathlib import Path
    with admin.database(bw) as db:
        evidence(db)
    soup = BeautifulSoup(logged_in(app).get('/planning/complete-sets').data, 'html.parser')
    summaries = soup.select('.bp-repair-details > summary')
    assert any(summary.select_one('.bp-repair-numbers') for summary in summaries)
    for summary in summaries:
        children = summary.find_all(recursive=False)
        assert [child['class'][0] for child in children] in (
            ['bp-repair-numbers', 'bp-details-label'], ['bp-details-label'])
        assert not summary.find_all(string=lambda text: text.strip(), recursive=False)
    css = Path('static/web/toni/bw-planning.css').read_text()
    rule = re.search(r'#bw-planning \.bp-repair-details > summary\s*\{([^}]+)\}', css).group(1)
    for declaration in ('display:flex', 'flex-direction:column', 'align-items:flex-start', 'gap:2px'):
        assert declaration in rule
    # Automatic flex heights must include every wrapped line, at all breakpoints.
    assert not re.search(r'(?<![\w-])height:|overflow:|position:absolute|white-space:nowrap', rule)
    assert not re.search(r'\border\s*:|display\s*:\s*contents', css)


def test_prices_name_orphan_guard_preserves_compact_rows_css_contract():
    import re
    from pathlib import Path
    css = Path('static/web/toni/bw-planning.css').read_text()
    collection_css = Path('static/web/toni/bw-collection.css').read_text()
    rule = re.search(r'\.bp-prices \.bc-identity strong\s*\{([^}]+)\}', css).group(1)
    assert 'text-wrap:pretty' in rule and 'text-wrap:pretty' in collection_css
    assert not re.search(r'height:|padding:|line-height:|overflow:', rule)
    assert 'padding-block:10px;align-items:center;' in css
    assert '.bp-prices .bp-identity .bc-picture { margin-bottom:-20px; }' in css


def test_planning_compact_chromium_geometry(app, bw, tmp_path):
    """Opt-in measurements use the shipped DOM/CSS; no screenshots."""
    import os
    import subprocess
    from pathlib import Path
    from urllib.parse import urlsplit
    chrome = os.environ.get('BW_COLLECTION_CHROME')
    if not chrome:
        pytest.skip('Set BW_COLLECTION_CHROME for opt-in browser geometry verification')
    with admin.database(bw) as db:
        evidence(db)
        with db:
            db.execute("UPDATE wishlist SET condition='used'")
            db.execute("UPDATE price_observations SET condition='U',price='154',min='127.50',max='190',sold=3,guide='sold',currency='EUR' WHERE item_type='S'")
    client = logged_in(app)
    for screen in ('complete-sets', 'prices', 'wishlist'):
        soup = BeautifulSoup(client.get('/planning/' + screen).data, 'html.parser')
        for link in soup.select('link[rel=stylesheet]'):
            style = soup.new_tag('style')
            style.string = Path(urlsplit(link['href']).path.lstrip('/')).read_text()
            link.replace_with(style)
        for script in soup.select('script'):
            script.decompose()
        if screen == 'prices':
            names = soup.select('.bp-identity .bc-identity strong')
            assert len(names) >= 2
            for name, text in zip(names, ("Technic, Liftarm Thick 1", "Aaron Fox's Aero Striker")):
                name.string = text
        (tmp_path / (screen + '.html')).write_text(str(soup))
    result = subprocess.run(
        ['node', 'tests/toni_bw_planning_geometry.cjs', chrome, str(tmp_path)],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_47c_wishlist_copy_structure_and_add_path(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/planning/wishlist').data, 'html.parser')
    assert soup.select_one('.bp-subtitle').text == 'Price now against your max, used average'
    assert not soup.select('.bc-detail-back, .breadcrumb')
    assert 'Add a wish' not in soup.text
    switch = soup.select_one('#bw-planning > .bc-list-options')
    assert [b['data-bp-view'] for b in switch.select('button')] == ['grid', 'list']
    assert switch.select_one('[data-bp-count]')
    assert switch.find_previous_sibling(class_='bp-visible-chips')
    for row in soup.select('[data-bp-row]'):
        assert not row.select('.bp-records')
    add = BeautifulSoup(logged_in(app).get('/manage/add').data, 'html.parser')
    assert add.select_one('input[name=where][value=wishlist]')


def test_47c_wishlist_exact_css_values():
    import re
    from pathlib import Path
    css = Path('static/web/toni/bw-planning.css').read_text()
    contracts = {
        '#bw-planning[data-screen=wishlist] h1': ['letter-spacing:-.2px'],
        '#bw-planning[data-screen=wishlist] .bp-subtitle': ['font:400 14px/20px var(--tw-font)', 'color:var(--tw-text-muted)'],
        '.bp-max strong': ['font:600 20px/26px var(--tw-mono)'],
        '.bp-wishlist .bp-row .bc-identity > .secondary': ['font:400 13px/18px var(--tw-font)', 'color:var(--tw-text-muted)'],
        '.bp-wishlist .bp-card-price': ['font:400 12px/16px var(--tw-mono)', 'color:var(--tw-text-2)'],
        '#bw-planning .bc-view-switch button': ['width:44px', 'height:36px'],
        '.bp-wishlist[data-view=list] .bc-picture': ['width:56px', 'height:56px'],
        '.bp-wish-track': ['height:18px'],
        '.bp-wish-track::before': ['top:6px', 'height:6px', 'border-radius:3px'],
        '.bp-wish-track i': ['top:1px', 'width:2px', 'height:16px'],
        '.bp-wish-range-labels': ['font:400 11px/14px var(--tw-mono)', 'color:var(--tw-text-2)'],
    }
    for selector, values in contracts.items():
        rule = re.search(re.escape(selector) + r'\s*\{([^}]+)', css).group(1)
        for value in values:
            assert value in rule


@pytest.mark.parametrize('condition', ['new', 'used', 'any', None])
def test_47c_wanted_card_and_existing_condition_save_undo(app, bw, condition):
    from tests.test_bw_collection import post
    with admin.database(bw) as db, db:
        wish = db.execute('SELECT id FROM wishlist LIMIT 1').fetchone()[0]
        db.execute('UPDATE wishlist SET condition=?,max_price=?,note=? WHERE id=?',
                   (condition, '82.3900', 'Keep every wish fact', wish))
    client = logged_in(app)
    soup = BeautifulSoup(client.get(f'/collection/wishes/{wish}').data, 'html.parser')
    assert soup.select_one('[data-web-ui=toni]')
    assert not soup.select('.breadcrumb')
    card = soup.select_one('[data-module=wanted]')
    assert card.h2.text == 'Wanted'
    assert card.select_one('.bc-wanted-max strong').text == '€82.39'  # 4.8b: the limit takes the configured currency
    assert card.select_one('.bc-wanted-segments').has_attr('data-bc-save-group')
    assert [b.text for b in card.select('.bc-wanted-segments button')] == ['New', 'Used', 'Any']
    assert not card.select('dt') and 'Tags' not in card.text
    selected = card.select('[aria-pressed=true]')
    assert len(selected) == (0 if condition is None else 1)
    if selected:
        assert selected[0].parent.select_one('input')['value'] == condition
    assert 'Keep every wish fact' in soup.select_one('.bc-wish-facts').text
    assert 'Max in EUR' in soup.select_one('.bc-wish-facts').text
    form = card.select_one('form')
    identity = json.loads(form['data-identity'])
    assert form['data-bc-action'] == 'save'
    response = post(client, token(client), 'save', **identity,
                    values={'condition': form.input['value']})
    assert response.status_code == 200
    with admin.database(bw) as db:
        event = db.execute('SELECT * FROM events WHERE id=?', (response.json['event_id'],)).fetchone()
        assert event['via'] == 'app'
        assert event['old_value'] != event['new_value'] or condition == 'new'
        assert db.execute('SELECT condition FROM wishlist WHERE id=?', (wish,)).fetchone()[0] == 'new'
    assert post(client, token(client), 'undo', event_id=response.json['event_id']).status_code == 200
    with admin.database(bw) as db:
        assert db.execute('SELECT condition FROM wishlist WHERE id=?', (wish,)).fetchone()[0] == condition
        assert db.execute('SELECT max_price,note FROM wishlist WHERE id=?', (wish,)).fetchone()[:] == ('82.3900', 'Keep every wish fact')


def test_47c_wanted_exact_css_values():
    import re
    from pathlib import Path
    css = Path('static/web/toni/bw-collection.css').read_text()
    contracts = {
        '#bw-collection .bc-wanted': ['padding:16px', 'gap:14px', 'border-radius:16px', 'background:var(--tw-surface)'],
        '#bw-collection .bc-wanted h2,.bc-wanted-label': ['font:500 11px/14px var(--tw-font)', 'letter-spacing:.1em', 'color:var(--tw-text-muted)'],
        '.bc-wanted-max strong': ['font:600 24px/30px var(--tw-mono)'],
        '.bc-wanted-max': ['gap:2px'],
        '.bc-wanted-condition': ['gap:6px'],
        '.bc-wanted-segments': ['padding:2px', 'gap:2px', 'border-radius:10px'],
        '#bw-collection .bc-wanted-segments button': ['height:44px', 'border-radius:8px', 'font:500 13px var(--tw-font)', 'color:var(--tw-text-2)'],
        '#bw-collection .bc-wanted-segments button[aria-pressed=true]': ['background:var(--tw-accent-soft)', 'color:var(--tw-accent-text)'],
    }
    for selector, values in contracts.items():
        rule = re.search(re.escape(selector) + r'\s*\{([^}]+)', css).group(1)
        for value in values:
            assert value in rule


def test_47c_compact_range_and_provenance_on_detail(app, bw):
    with admin.database(bw) as db, db:
        db.execute("UPDATE wishlist SET condition='used'")
        db.execute("UPDATE price_observations SET condition='U',price='82.39',min='70',max='99',sold=3,guide='sold',currency='EUR'")
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    row = soup.select_one('[data-bp-row]')
    assert row.select_one('.bp-card-price').text == 'Used avg €82.39'
    assert [s.text for s in row.select('.bp-wish-range-labels span')] == ['min €70.00', 'avg €82.39', 'max €99.00']
    assert row.select_one('.bp-values').find_all(recursive=False)[-1]['class'] == ['bp-wish-range']
    assert not row.select('details') and 'bricklink' not in row.text
    detail = BeautifulSoup(client.get(row.select_one('a[href*=wishes]')['href']).data, 'html.parser')
    # 4.7e moved provenance from visible text into the caption title.
    assert 'brickset' in [c['title'] for c in detail.select('.bc-price-records .secondary')]
    assert '€82.39' in detail.select_one('.bc-price-records').text


def test_47c_condition_save_query_count_independent_of_wishlist_size(bw):
    with admin.database(bw) as db:
        identifier = db.execute('SELECT id FROM wishlist LIMIT 1').fetchone()[0]
        def measured():
            traces = []
            db.set_trace_callback(traces.append)
            try:
                event = collection.save(db, 'wish', [identifier], {'condition': 'used'})
            finally:
                db.set_trace_callback(None)
            collection.undo(db, event)
            return len(traces)
        small = measured()
        with db:
            for i in range(300):
                db.execute("INSERT INTO items(item_type,item_no) VALUES('S',?)", (f'47c-{i}',))
                db.execute("INSERT INTO wishlist(item_type,item_no,quantity,condition) VALUES('S',?,1,'any')", (f'47c-{i}',))
        assert measured() == small
        assert small < 20


def test_49d_prices_order_update_and_wishlist_range(app, bw):
    client = logged_in(app)
    soup = BeautifulSoup(client.get('/planning/prices').data, 'html.parser')
    chips, controls = soup.select_one('.bp-visible-chips'), soup.select_one('.bc-toolbar')
    assert soup.select_one('[data-bp-lookup]').find_next(class_='bp-visible-chips') is chips
    assert chips.find_next(class_='bc-toolbar') is controls
    assert not any(b.text == 'Refresh' for b in soup.select('.bp-ages button'))
    css = Path('static/web/toni/bw-planning.css').read_text().replace(' ', '')
    assert '.bp-wish-trackb{position:absolute;left:0;width:100%;top:6px;height:6px;border-radius:3px;background:var(--tw-viz-2)' in css
    assert '.bp-wish-range-labels{gap:0;flex-wrap:nowrap;}' in css
    with admin.database(bw) as db, db:
        db.execute("UPDATE wishlist SET condition='used'")
        db.execute("UPDATE price_observations SET condition='U',price='70',min='60',max='100',sold=3,guide='sold',currency='EUR'")
    wish = BeautifulSoup(client.get('/planning/wishlist').data, 'html.parser')
    track = wish.select_one('.bp-wish-track')
    assert track.select_one('b') and track.select_one('i')['style'] == 'left:25.0%'


def test_49d_collection_wishes_show_recorded_max(app, bw):
    with admin.database(bw) as db, db:
        first = db.execute('SELECT id FROM wishlist WHERE archived_at IS NULL ORDER BY id').fetchone()[0]
        db.execute("UPDATE wishlist SET max_price='48', max_price_currency='EUR' WHERE id=?", (first,))
    assert logged_in(app).get('/collection/wishes').status_code == 200
    from brickwork.core.list_records import payload
    with admin.database(bw, read_only=True) as db:
        rows = collection.listing(db, 'S', wishes=True)
    decoded = json.loads(payload(rows))
    index = str(decoded['fields'].index('max_price'))
    assert '€48.00' in [r.get(index) for r in decoded['rows']]
    from brickwork.core.list_records import payload
    bare = dict(item_type='S', item_no='x', name='x', entity='wish', id=1, quantity=1, instances=[])
    assert 'max_price' not in bare and json.loads(payload([bare]))['rows']  # a wish row without the column must not raise
    js = Path('static/web/toni/bw-collection.js').read_text()
    assert "'Your max price'" in js and "'Not recorded'" in js


def test_complete_sets_export_starts_disabled(app, bw):
    soup = BeautifulSoup(logged_in(app).get('/planning/complete-sets').data, 'html.parser')
    button = soup.select_one('[data-bp-export]')
    assert button.has_attr('disabled') and button.text == 'Export selected · BrickLink XML'


def test_prices_age_stays_on_one_line():
    css = (Path(__file__).parents[1] / 'static/web/toni/bw-planning.css').read_text()
    assert '.bp-desktop-age { white-space:nowrap; }' in css


def test_wishlist_management_follows_wanted_lists(app,bw):
    # Lists as chips with counts, one action row of outline buttons, sheets for export and lists,
    # and a selection bar (hidden until a wish is ticked) carrying Move and Copy.
    soup=BeautifulSoup(logged_in(app).get('/planning/wishlist').data,'html.parser')
    root=soup.select_one('[data-wl-root]')
    chips=root.select('.wl-lists a.button')
    assert chips[0].get_text(' ',strip=True).startswith('All lists') and chips[0]['aria-current']=='page'
    assert all(c.select_one('.mono') for c in chips)
    toolbar=root.select_one('.wl-toolbar[role=toolbar]')
    assert [b.get_text(strip=True) for b in toolbar.find_all(['button','a'],recursive=False)]==['Manage lists','Export','Print','Download CSV']
    assert not toolbar.select('.primary')
    assert root.select_one('dialog#bw-export-wishlist.bc-sheet [data-wl-kind][hidden]')
    assert root.select_one('dialog#bw-manage-wishlists details.wl-new form[data-wl-action=save]')
    bar=soup.select_one('form.bc-selection-bar[data-wl-selection][hidden]')
    assert bar and bar['data-wl-action']=='transfer'
    assert [b.get_text(strip=True) for b in bar.select('button')]==['Move','Copy','Clear']
    assert 'bw-wishlists.css' in str(soup.head or soup)
