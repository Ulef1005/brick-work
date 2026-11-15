"""Storage label decisions, using invented collection data and no live host."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from urllib.parse import urlsplit
from zipfile import ZipFile

from bs4 import BeautifulSoup
from PIL import Image
import pytest

from brickwork.core import labels, ledger
from brickwork.store4.connect import HERE, connect, upgrade
from tests.app4 import BROWSER_PASSWORD, app4, client, coll, csrf, pair, world  # noqa: F401
from tests.api2 import BOOTSTRAP, call, stored_token, v2  # noqa: F401
from tests import rendered

MATRIX = tuple(tuple(int((x+y)%3 == 0) for x in range(37)) for y in range(37))


def test_short_ids_archive_delete_undo_and_search(coll):
    db = coll.db
    a, event = ledger.storage_save(db, None, 'Box 3')
    first = db.execute('SELECT short_id FROM storage WHERE id=?', (a,)).fetchone()[0]
    assert first == 'S-0001'
    ledger.undo(db, event)
    b, _ = ledger.storage_save(db, None, 'Drawer 12')
    assert ledger.storage_search(db, 's-0002')[0]['id'] == b
    ledger.storage_archive(db, b)
    with db:
        db.execute('DELETE FROM storage WHERE id=?', (b,))
    c, _ = ledger.storage_save(db, None, 'Bag 07')
    assert db.execute('SELECT short_id FROM storage WHERE id=?', (c,)).fetchone()[0] == 'S-0003'
    assert len(c) == 32 and ledger.storage_search(db, first) == []


def test_concurrent_creates_get_distinct_monotonic_ids(pair):
    def make(n):
        with closing(connect(pair, Path(pair).with_name('catalogue.db'))) as db:
            identifier, _ = ledger.storage_save(db, None, f'Box {n}')
            return db.execute('SELECT short_id FROM storage WHERE id=?', (identifier,)).fetchone()[0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(make, range(12)))
    assert sorted(result) == [f'S-{i:04d}' for i in range(1,13)]


def test_upgrade_fixture_copy_backfills_creation_order_and_is_idempotent(tmp_path):
    fixture = tmp_path / 'fixture.db'
    with closing(sqlite3.connect(fixture)) as db:
        db.executescript((HERE/'brickwork.sql').read_text().split('-- Storage label identities')[0])
        db.execute("INSERT INTO meta VALUES('schema_version','4.2')")
        db.executemany('INSERT INTO storage(id,name,created_at,archived_at) VALUES(?,?,?,?)',
                       [('b','Box 3','2026-10-02',None),('c','Drawer 12','2026-10-01','2026-10-03'),('a','Bag 07','2026-10-01',None)])
        db.commit()
    target = tmp_path/'restored.db'
    shutil.copyfile(fixture,target)
    assert upgrade(target) == upgrade(target) == '4.3'
    with closing(sqlite3.connect(target)) as db:
        assert db.execute('SELECT id,short_id FROM storage ORDER BY short_id').fetchall() == [('a','S-0001'),('c','S-0002'),('b','S-0003')]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE storage SET short_id='S-0001' WHERE id='b'")
        db.rollback()
        db.execute("DELETE FROM storage WHERE id='b'")
        db.execute("INSERT INTO storage(id,name,created_at) VALUES('d','Box 5','2026-10-04')")
        assert db.execute("SELECT short_id FROM storage WHERE id='d'").fetchone()[0] == 'S-0004'
    with closing(sqlite3.connect(fixture)) as db:
        assert 'short_id' not in {r[1] for r in db.execute('PRAGMA table_info(storage)')}


@pytest.mark.parametrize('host,warning', [('https://bricks.example',False),('http://localhost:3333',True),('http://127.0.0.1:3333',True),('http://[::1]:3333',True)])
def test_request_address_fallback_and_warning(coll,host,warning):
    assert labels.address(coll.db,host) == dict(value=host,warning=warning)
    labels.save_address(coll.db,'https://bricks.example/')
    assert labels.address(coll.db,host) == dict(value='https://bricks.example',warning=False)
    labels.save_address(coll.db,'')
    assert labels.address(coll.db,host)['value'] == host


@pytest.mark.parametrize('value', ['file:///tmp/box','https://alex:secret@bricks.example','https://bricks.example/path','https://bricks.example?q=1','https://bricks.example#bin'])
def test_setting_rejects_non_origin_addresses(value):
    with pytest.raises(ValueError): labels.validate_address(value)


def test_qr_payload_matrix_and_quiet_zone(coll):
    segno = pytest.importorskip('segno', reason='segno not installed in this sandbox')
    identifier,_ = ledger.storage_save(coll.db,None,'Box 3')
    payload = 'https://bricks.example/workbench/storage/' + identifier
    expected = segno.make(payload,error='m',micro=False,boost_error=False)
    assert labels.qr_matrix(payload) == tuple(tuple(r) for r in expected.matrix)
    image = labels.qr_image(labels.qr_matrix(payload))
    scale = image.width // (len(expected.matrix)+8)
    assert scale*len(expected.matrix) >= labels.px(20)
    assert set(image.crop((0,0,image.width,4*scale)).getdata()) == {(255,255,255)}


def test_layouts_geometry_pdf_pages_tape_and_long_umlaut_name(coll):
    ids = [ledger.storage_save(coll.db,None,f'Box {n}')[0] for n in range(22)]
    for key in ('a4-21','a4-14'):
        spec=labels.LAYOUTS[key]
        assert spec.capacity == (21 if key=='a4-21' else 14)
        assert spec.left*2+spec.width*spec.columns+spec.gap*(spec.columns-1) == pytest.approx(210)
        assert spec.top*2+spec.height*spec.rows == pytest.approx(297)
    found=labels.plan(coll.db,ids,'a4-21','https://bricks.example')
    assert found['pages'] == 2
    seen=[]
    def matrix(payload):seen.append(payload);return MATRIX
    data,mime,name=labels.download(found,matrix_factory=matrix)
    assert data.startswith(b'%PDF') and mime=='application/pdf'
    assert len(re.findall(rb'/Type /Page\b',data)) == 2
    assert seen == ['https://bricks.example/workbench/storage/'+i for i in ids]
    assert labels.page_image(found,0,matrix_factory=matrix).tobytes() != labels.page_image(found,0,guides=True,matrix_factory=matrix).tobytes()
    tape=labels.plan(coll.db,ids[:1],'tape-62','https://bricks.example')
    data,mime,name=labels.download(tape,matrix_factory=matrix)
    assert mime=='image/png' and Image.open(BytesIO(data)).size == (labels.px(62),labels.px(45))
    tape=labels.plan(coll.db,ids[:3],'tape-62','https://bricks.example')
    data,mime,name=labels.download(tape,matrix_factory=matrix)
    with ZipFile(BytesIO(data)) as archive:
        assert len(archive.namelist()) == 3 and all(n.endswith('.png') for n in archive.namelist())
    face=labels.font(42)
    lines=labels.name_lines('Äußere Größe '+('Schublade '*20),face,200)
    assert len(lines)==2 and lines[-1].endswith('…') and all(face.getlength(line)<=200 for line in lines)
    row=dict(id=ids[0],name='Äußere Größe '+('Schublade '*20),short_id='S-0001')
    assert labels.label(row,'a4-21','https://bricks.example',matrix).size == (labels.px(63.5),labels.px(38.1))


def test_dialog_selection_markup_archive_and_setting(client,coll):
    active,_=ledger.storage_save(coll.db,None,'Box 3')
    archived,_=ledger.storage_save(coll.db,None,'Drawer 12')
    ledger.storage_archive(coll.db,archived)
    page=BeautifulSoup(client.get('/workbench/storage').data,'html.parser')
    assert [n['data-label-id'] for n in page.select('[data-label-id]')] == [active]
    assert page.select_one('[data-label-open]')['disabled'] == ''
    assert page.select_one('[data-label-open]').text == 'Choose storages'
    assert page.select_one('[data-label-single]')['data-label-single'] == active
    assert len(page.select('[data-label-layout] option')) == 3
    assert 'Letter' not in page.select_one('[data-label-dialog]').text
    assert 'Codes open http://localhost/workbench/storage/…' in page.text
    assert not page.select_one('.lb-warning').has_attr('hidden')
    assert page.select_one('[data-label-download]').text == 'Download PDF'
    assert page.select_one('[data-label-prev]') and page.select_one('[data-label-next]')
    landing=client.get('/workbench/storage/'+archived).text
    assert 'This storage is not here' in landing and 'was archived' in landing
    assert 'st-showing-detail' in BeautifulSoup(landing,'html.parser').select_one('#bw-ledger')['class']
    assert 'S-0001' in client.get('/collection/jump?q=s-0001').text
    token=csrf(client)
    # Use the route's URL so this test also follows any future Tools & Admin URL move.
    with client.application.test_request_context():
        from flask import url_for
        settings_url=url_for('web.bw_admin_write',page='settings')
    response=client.post(settings_url,data=dict(csrf_token=token,action='labels_address',labels_address='https://bricks.example'))
    assert response.status_code == 302
    assert 'https://bricks.example/workbench/storage/…' in client.get('/workbench/storage').text


def test_plan_is_two_queries_for_200_storages_and_archived_are_refused(coll):
    ids=[ledger.storage_save(coll.db,None,f'Box {n}')[0] for n in range(200)]
    queries=[]
    coll.db.set_trace_callback(queries.append)
    try:found=labels.plan(coll.db,ids,'a4-21','https://bricks.example')
    finally:coll.db.set_trace_callback(None)
    assert len(queries)==2 and found['pages']==10
    ledger.storage_archive(coll.db,ids[0])
    with pytest.raises(ValueError,match='active'):labels.plan(coll.db,ids,'a4-21','https://bricks.example')


def test_api_web_mcp_share_plan_and_read_download(client,app4,v2,coll,pair,monkeypatch):
    from brickwork.core.mcp import Adapter
    from brickwork.core.mcp.client import InProcessClient
    identifier,_=ledger.storage_save(coll.db,None,'Box 3')
    monkeypatch.setattr(labels,'download',lambda found: (b'%PDF-synthetic','application/pdf','storage-labels.pdf'))
    token=stored_token(pair,['read'])
    monkeypatch.setenv('BW_READ_ONLY','1')
    query='?ids='+identifier+'&layout=a4-21'
    assert client.get('/workbench/storage/labels/download'+query).data == b'%PDF-synthetic'
    direct=call(v2,'/storages/labels'+query,token=token)
    assert direct.status_code==200
    result=Adapter(InProcessClient(app4,token)).call_tool('storage_labels',dict(ids=identifier,layout='a4-21'))
    assert not result.isError and result.structuredContent == direct.json['data']
    link=urlsplit(result.structuredContent['url'])
    pdf=call(v2,link.path.removeprefix('/api/v2')+'?'+link.query,token=token)
    assert pdf.data==b'%PDF-synthetic' and pdf.mimetype=='application/pdf'
    assert call(v2,'/storages/labels.pdf?ids='+identifier+'&layout=tape-62',token=token).status_code==422


def test_scan_login_returns_to_storage(app4,coll):
    identifier,_=ledger.storage_save(coll.db,None,'Box 3')
    browser=app4.test_client()
    target='/workbench/storage/'+identifier
    result=browser.get(target)
    assert result.status_code==302 and 'next=' in result.location
    login=browser.post(result.location,data={'password':BROWSER_PASSWORD})
    assert login.status_code==302 and login.location==target
    assert 'Box 3' in browser.get(login.location).text


def test_missing_segno_is_retryable(client,coll,monkeypatch):
    identifier,_=ledger.storage_save(coll.db,None,'Box 3')
    def missing(*args,**kwargs):raise ImportError('segno')
    monkeypatch.setattr(labels,'download',missing)
    response=client.get('/workbench/storage/labels/download?ids='+identifier)
    assert response.status_code==503 and 'Retry' in response.json['message']


def test_labels_node_runtime():
    rendered.need_node()
    subprocess.run(['node','tests/toni_bw_labels_runtime.cjs'],check=True,capture_output=True,text=True)


def test_address_setting_api_validation_undo_and_read_scope(v2,pair):
    from tests.api2 import write
    changed=write(v2,'/settings','patch',body={'labels_address':'https://bricks.example/'})
    assert changed.status_code==200 and changed.json['data']['labels_address']=='https://bricks.example'
    event=changed.json['event_id']
    assert write(v2,f'/events/{event}/undo').status_code==200
    assert call(v2,'/settings').json['data']['labels_address']==''
    assert write(v2,'/settings','patch',body={'labels_address':'https://bricks.example/path'}).status_code==422
    reader=stored_token(pair,['read'])
    assert write(v2,'/settings','patch',body={'labels_address':''},token=reader).status_code==403


def test_new_and_upgraded_storage_schema_match(tmp_path):
    old=tmp_path/'old.db'
    with closing(sqlite3.connect(old)) as db:
        db.executescript((HERE/'brickwork.sql').read_text().split('-- Storage label identities')[0])
        db.execute("INSERT INTO meta VALUES('schema_version','4.2')")
        db.commit()
    upgrade(old)
    with closing(sqlite3.connect(old)) as upgraded, closing(connect(tmp_path/'new.db',tmp_path/'catalogue.db')) as fresh:
        for table in ('storage','storage_label_sequence'):
            assert upgraded.execute(f'PRAGMA table_info({table})').fetchall()==[tuple(r) for r in fresh.execute(f'PRAGMA table_info({table})')]
        query="SELECT name,sql FROM sqlite_master WHERE name IN ('storage_label_identity','storage_short_id') ORDER BY name"
        assert upgraded.execute(query).fetchall()==[tuple(r) for r in fresh.execute(query)]


def test_label_screen_candidates_are_unapproved_and_edge_has_two_sheets(tmp_path):
    from scripts import screen_gate
    states=json.loads(Path('design/screens/states.json').read_text())['states']
    candidates=[s for s in states if s['screen']=='34-Storage' and s['state'].startswith('labels-')]
    assert {s['state'] for s in candidates}=={'labels-select-none','labels-select-three','labels-ready','labels-address-warning','labels-two-sheets','labels-error'}
    assert all(s['built'] and s['approved'] is False and '?labels=' in s['path'] for s in candidates)
    path=tmp_path/'brickwork.db'
    screen_gate.build_store('edge',path)
    with closing(connect(path,tmp_path/'catalogue.db')) as db:
        ids=[r[0] for r in db.execute("SELECT id FROM storage WHERE id LIKE 'label-bin-%' ORDER BY id")]
        found=labels.plan(db,ids,'a4-21','http://localhost')
        assert len(ids)==22 and found['pages']==2 and found['address']==dict(value='https://bricks.example',warning=False)


def test_undo_of_pre_upgrade_storage_edit_keeps_backfilled_identity(tmp_path):
    from brickwork.store4.rowlog import RowLog
    path=tmp_path/'restored.db'
    with closing(sqlite3.connect(path)) as db:
        db.row_factory=sqlite3.Row
        db.executescript((HERE/'brickwork.sql').read_text().split('-- Storage label identities')[0])
        db.execute("INSERT INTO meta VALUES('schema_version','4.2')")
        db.execute("INSERT INTO storage(id,name,created_at) VALUES('a','Box 3','2026-10-01')")
        db.commit()
        _,event=ledger.storage_save(db,'a','Drawer 12')
        log=RowLog(db)
        log.update('storage',log.select('storage','id=?',('a',))[0],note='Bag 07')
        db.commit()
        changes=log.changes
    upgrade(path)
    with closing(connect(path,tmp_path/'catalogue.db')) as db:
        log=RowLog(db,changes)
        assert log.verify() is None
        log.restore()
        db.commit()
        ledger.undo(db,event)
        row=db.execute('SELECT name,note,short_id FROM storage WHERE id=\'a\'').fetchone()
        assert tuple(row)==('Box 3',None,'S-0001')
