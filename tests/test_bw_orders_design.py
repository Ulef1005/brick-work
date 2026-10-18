"""12b rendering and transport contracts on the migrated collection."""
from contextlib import closing
from pathlib import Path
import shutil
import subprocess

from bs4 import BeautifulSoup

from brickwork.core import orders, ledger
from brickwork.core.connect import connect
from brickwork.core.sources.base import SourceError
from tests.test_bw_orders_storage import app, apps, bw, legacy, saved, XML, client_token


def page(client, oid, view='detail'):
    response = client.get(f'/workbench/orders/{oid}?view={view}')
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, 'html.parser')
    assert not soup.select('.breadcrumb')
    assert soup.select_one('.order-layout .order-sidebar')
    panels = soup.select('[data-order-panel]')
    assert all((p.has_attr('hidden')) == (p['data-order-panel'] != view) for p in panels)
    current = soup.select_one('.order-actions [aria-current="page"]')
    assert (current is None) if view == 'detail' else current['href'].endswith('view=' + view)
    return soup


def test_import_hub_three_cards_and_existing_table(app, bw):
    with closing(connect(bw)) as db:
        oid, _, _ = saved(db)
        with db:
            db.execute("UPDATE orders SET bricklink_order_id='12345',store='Synthetic store',currency='EUR',cost='11408.95' WHERE id=?", (oid,))
    client, _, _ = client_token(app)
    soup = BeautifulSoup(client.get('/workbench/orders').text, 'html.parser')
    assert [h.text for h in soup.select('.order-import-card h2')] == ['Import a placed order', 'Paste order email', 'BrickLink XML upload']
    assert soup.select_one('[data-load-orders]')
    assert soup.select_one('form [name=source][value=email]')
    assert soup.select_one('[data-drop] input[type=file]')['accept'] == '.xml,text/xml,application/xml'
    row = soup.select_one('.order-table-row')
    assert row['href'] == f'/workbench/orders/{oid}'
    assert all(text in row.text for text in ('12345', 'Synthetic store', '€11,408.95', 'Open'))
    assert not soup.select('.breadcrumb')
    assert len(soup.select('select[name=choice]')) == 2


def test_detail_count_allocation_allocated_history_reconcile(app, bw):
    with closing(connect(bw)) as db:
        oid, _, lid = saved(db)
        orders.received(db, oid, {lid: 2})
    client, csrf, _ = client_token(app)
    detail = page(client, oid)
    assert detail.select_one('[data-order-panel=detail] .bw-picture')
    assert detail.select_one('[data-action=hold]')
    count = page(client, oid, 'count')
    assert '2 of 3 pieces counted' in count.text
    assert count.select_one('[data-received]')['min'] == '0'
    assert count.select_one('[data-mark-received]')
    allocation = page(client, oid, 'allocation')
    assert allocation.select_one('[data-reset-suggestion]')
    assert allocation.select_one('[data-allocation]')['max'] == '2'
    result = client.post('/workbench/orders/action/allocate', json=dict(csrf_token=csrf,order_id=oid,chosen=[dict(line_id=lid,target_type='stock',quantity=2)]))
    assert result.status_code == 200
    allocated = page(client, oid, 'allocation')
    assert 'Allocated 2 pieces.' in allocated.select_one('.order-success').text
    assert allocated.select_one('.order-success [data-undo-event]')['data-undo-event'] == str(result.json['event_id'])
    history = page(client, oid, 'history')
    assert 'Allocation history' in history.text and 'Reconcile' in history.text
    assert history.select_one('[data-action=reconcile]')
    assert history.select_one('[data-undo-event]')
    assert 'short.xml' in history.select_one('a[href$="short.xml"]')['href']
    assert client.post('/workbench/orders/action/undo',json=dict(csrf_token=csrf,event_id=result.json['event_id'])).status_code == 200
    reconcile = page(client, oid, 'history')
    assert '2 not placed' in reconcile.text
    assert reconcile.select_one('a[href$="view=count"]')
    # Invalid view remains a usable detail page.
    assert BeautifulSoup(client.get(f'/workbench/orders/{oid}?view=unknown').text,'html.parser').select_one('[data-order-panel=detail]:not([hidden])')


def test_12b_header_actions_list_item_and_count_chips(app, bw):
    with closing(connect(bw)) as db:
        oid, _, lid = saved(db)
        orders.received(db, oid, {lid: 2})
    client, _, _ = client_token(app)
    detail = page(client, oid)
    assert [a.text for a in detail.select('.order-actions a.button')] == ['Count what arrived', 'Review allocation', 'Allocations and reconcile']
    assert detail.select_one('.order-actions a.button.primary').text == 'Count what arrived'
    assert not detail.select('.order-tabs')
    item = detail.select_one('.order-list-item[aria-current]')
    assert item.select_one('.order-list-ref') and item.select_one('.order-list-side b') and item.select_one('.order-list-side .status')
    assert '1 line' in item.text and '1 lines' not in item.text
    assert detail.select_one('.order-content [data-notice]') and len(detail.select('[data-notice]')) == 1
    assert detail.select_one('.order-badges .status')
    count = page(client, oid, 'count')
    row = count.select_one('.order-count-row')
    assert row.select_one('.order-ordered').text == '3'
    assert row.select_one('.order-stepper input[data-received]')['value'] == '2'
    assert row.select_one('.order-count-state').text == '1 short'
    assert count.select_one('[data-progress]')['data-ordered'] == '3' and count.select_one('[data-bar]')['style'] == 'width:67%'
    allocation = page(client, oid, 'allocation')
    assert allocation.select_one('.order-alloc-head .bw-identity')


def test_hub_notice_and_history_layout_class(app, bw):
    client, _, _ = client_token(app)
    hub = BeautifulSoup(client.get('/workbench/orders').text, 'html.parser')
    assert len(hub.select('[data-notice]')) == 1 and hub.select_one('.order-import-card [data-load-orders]')
    with closing(connect(bw)) as db:
        oid, _, _ = saved(db)
    assert 'order-view-history' in page(client, oid, 'history').select_one('.order-content')['class']


def test_legacy_allocation_rows_render_and_upgrade_backfills_target(app, bw):
    from brickwork.core import upgrade_api
    with closing(connect(bw)) as db:
        oid, _, lid = saved(db)
        orders.received(db, oid, {lid: 2})
        copy_id = db.execute('SELECT id FROM copies LIMIT 1').fetchone()[0]
        with db:
            db.execute("INSERT INTO allocations(order_id,line_id,kind,copy_id,qty,state,created_at) VALUES(?,?,'loose_part',?,1,'applied','2026-01-01')", (oid, lid, copy_id))
            db.execute("INSERT INTO allocations(order_id,line_id,kind,qty,state,created_at,target_type) VALUES(?,?,'loose_part',1,'applied','2026-01-01','copy')", (oid, lid))
    client, _, _ = client_token(app)
    response = client.get(f'/workbench/orders/{oid}?view=history')
    assert response.status_code == 200
    labels = [r.text for r in BeautifulSoup(response.text, 'html.parser').select('.order-allocation-row span:not(.mono):not(.status)')]
    assert any(t.startswith('Copy ') for t in labels) and 'Target not recorded' in labels
    with closing(connect(bw)) as db:
        upgrade_api.upgrade_indexes(db); upgrade_api.upgrade_indexes(db)
        row = db.execute("SELECT target_type,target_copy_id FROM allocations WHERE copy_id=?", (copy_id,)).fetchone()
        assert tuple(row) == ('copy', copy_id)
    assert client.get(f'/workbench/orders/{oid}?view=history').status_code == 200


def test_order_dates_keep_year_and_missing_currency_is_stated(app, bw):
    with closing(connect(bw)) as db:
        oid, _, _ = saved(db)
        with db:
            db.execute("UPDATE orders SET bricklink_order_id='777',store='Old store',currency=NULL,cost='5.00',date_ordered='2024-03-09' WHERE id=?", (oid,))
    client, _, _ = client_token(app)
    for url in ('/workbench/orders', f'/workbench/orders/{oid}'):
        text = client.get(url).text
        assert '9 Mar 2024' in text and '9 Mar<' not in text
        assert 'Currency not recorded 5.00' in text
        assert '>5.00<' not in text


def test_draft_match_pair_reopen_are_preserved(app, bw):
    with closing(connect(bw)) as db:
        imported = orders.import_document(db, 'xml', XML)
    client, _, _ = client_token(app)
    soup = page(client, imported['order_id'])
    assert soup.select_one('[data-action=match]')
    assert soup.select_one('[data-catalogue-search]')
    assert soup.select_one('[data-action=review]')
    with closing(connect(bw)) as db:
        orders.phase(db, imported['order_id'], imported['document_id'], 'review')
    soup = page(client, imported['order_id'])
    assert soup.select_one('[data-pair]')
    assert soup.select_one('[data-action=reopen]')
    assert soup.select_one('[data-action=save]')


def test_placed_orders_checkbox_data_duplicates_and_source_failure(app, bw, monkeypatch):
    with closing(connect(bw)) as db:
        oid, _, _ = saved(db)
        with db: db.execute("UPDATE orders SET bricklink_order_id='123' WHERE id=?", (oid,))
    client, csrf, _ = client_token(app)
    monkeypatch.setattr(orders.BrickLink, 'list_orders', lambda self: [dict(order_id=123,store_name='Imported'),dict(order_id=456,store_name='New',date_ordered='2026-10-01')])
    assert client.post('/workbench/orders/action/placed',json={}).status_code == 400
    response = client.post('/workbench/orders/action/placed',json=dict(csrf_token=csrf))
    assert response.json['orders'] == [dict(number='123',store='Imported',date='',imported=True),dict(number='456',store='New',date='2026-10-01',imported=False)]
    def fail(self): raise SourceError('BrickLink key is unavailable')
    monkeypatch.setattr(orders.BrickLink, 'list_orders', fail)
    response = client.post('/workbench/orders/action/placed',json=dict(csrf_token=csrf))
    assert response.status_code == 400 and 'key is unavailable' in response.json['message']


def test_save_error_is_atomic_and_retry_controls_render(app, bw):
    with closing(connect(bw)) as db:
        oid, _, lid = saved(db)
        orders.received(db, oid, {lid:2})
    client, csrf, _ = client_token(app)
    result = client.post('/workbench/orders/action/allocate',json=dict(csrf_token=csrf,order_id=oid,chosen=[dict(line_id=lid,target_type='stock',quantity=3)]))
    assert result.status_code == 400
    soup = page(client, oid, 'allocation')
    assert soup.select_one('[data-notice][hidden] [data-message][role=status]')
    assert soup.select_one('[data-retry][hidden]').text == 'Retry'
    with closing(connect(bw)) as db:
        assert orders.detail(db, oid)['allocated'] == 0


def test_orders_runtime():
    subprocess.run([shutil.which('node'),str(Path(__file__).with_name('toni_bw_orders_runtime.cjs'))],check=True,capture_output=True,text=True)
