"""12b rendering and transport contracts of the Orders screens on the 4.0 store (M.8h, issue #110). Invented data, no network.

Rewritten from the 3.3 file: the allocation-target upgrade test is gone (4.0 starts with the columns); a copy-target allocation in the history
takes its place."""
from pathlib import Path
import shutil
import subprocess

from bs4 import BeautifulSoup
import pytest

from brickwork.core import orders
from brickwork.core.sources.base import SourceError
from tests.app4 import app4, client, coll, csrf, pair, read, world  # noqa: F401 (fixtures)
from tests.test_bw_orders_storage import XML, gap_of, inventory, line_of, saved, token  # noqa: F401 (fixtures)


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


def test_import_hub_three_cards_and_existing_table(world, client, coll):
    oid, _, _ = saved(coll.db)
    coll.sql("UPDATE purchase_order SET bricklink_order_id='12345',store='Synthetic store',currency='EUR',cost='11408.95' WHERE id=?", (oid,))
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


def test_detail_count_allocation_allocated_history_reconcile(world, client, token, coll):
    oid, _, lid = saved(coll.db)
    orders.received(coll.db, oid, {lid: 2})
    detail = page(client, oid)
    assert detail.select_one('[data-order-panel=detail] .bw-picture')
    assert detail.select_one('[data-action=hold]')
    count = page(client, oid, 'count')
    assert '2 of 3 pieces counted' in count.text
    assert count.select_one('[data-received]')['min'] == '0'
    assert count.select_one('[data-mark-received]')
    allocation = page(client, oid, 'allocation')
    assert allocation.select_one('[data-reset-suggestion]')
    assert allocation.select_one('[data-allocation*="stock"]')['max'] == '2'
    result = client.post('/workbench/orders/action/allocate', json=dict(csrf_token=token, order_id=oid, chosen=[dict(line_id=lid, target_type='stock', quantity=2)]))
    assert result.status_code == 200, result.json
    allocated = page(client, oid, 'allocation')
    assert 'Allocated 2 pieces.' in allocated.select_one('.order-success').text
    assert allocated.select_one('.order-success [data-undo-event]')['data-undo-event'] == str(result.json['event_id'])
    history = page(client, oid, 'history')
    assert 'Allocation history' in history.text and 'Reconcile' in history.text
    assert history.select_one('[data-action=reconcile]')
    assert history.select_one('[data-undo-event]')
    assert 'short.xml' in history.select_one('a[href$="short.xml"]')['href']
    assert client.post('/workbench/orders/action/undo', json=dict(csrf_token=token, event_id=result.json['event_id'])).status_code == 200
    reconcile = page(client, oid, 'history')
    assert '2 not placed' in reconcile.text
    assert reconcile.select_one('a[href$="view=count"]')
    # Invalid view remains a usable detail page.
    assert BeautifulSoup(client.get(f'/workbench/orders/{oid}?view=unknown').text, 'html.parser').select_one('[data-order-panel=detail]:not([hidden])')


def test_12b_header_actions_list_item_and_count_chips(world, client, coll):
    oid, _, lid = saved(coll.db)
    orders.received(coll.db, oid, {lid: 2})
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


def test_hub_notice_and_history_layout_class(world, client, coll):
    hub = BeautifulSoup(client.get('/workbench/orders').text, 'html.parser')
    assert len(hub.select('[data-notice]')) == 1 and hub.select_one('.order-import-card [data-load-orders]')
    oid, _, _ = saved(coll.db)
    assert 'order-view-history' in page(client, oid, 'history').select_one('.order-content')['class']


def test_allocation_history_names_the_copy_and_the_stock_target(world, client, token, coll):
    coll.mark(world.copy_a, '3001', '4', missing=3)
    oid, _, lid = saved(coll.db)
    orders.received(coll.db, oid, {lid: 3})
    gap = gap_of(coll.db, oid, lid, world.copy_a)
    orders.allocate(coll.db, oid, [dict(line_id=lid, target_type='copy', copy_id=gap['copy_id'], target='part', target_id=gap['target_id'], quantity=2),
                                   dict(line_id=lid, target_type='stock', quantity=1, storage_id=world.shelf, lot_id=world.bag)])
    soup = page(client, oid, 'history')
    labels = [r.text for r in soup.select('.order-allocation-row span:not(.mono):not(.status)')]
    assert any(t.startswith('Copy 1000-1') for t in labels) and 'Lot Bag · Shelf A' in labels
    assert len(soup.select('.order-allocation-row [data-undo-event]')) == 2          # both belong to the one allocate save
    # the allocation page offers each gap as 'set number · copy label · n missing' and names the target storage
    allocation = page(client, oid, 'allocation')
    assert allocation.select_one('[data-allocation]')


def test_destinations_name_the_copy_in_the_allocation_review(world, client, coll):
    coll.mark(world.copy_a, '3001', '4', missing=1)
    oid, _, lid = saved(coll.db)
    orders.received(coll.db, oid, {str(lid): 3})
    destination = gap_of(coll.db, oid, lid, world.copy_a)
    assert isinstance(destination, dict) and destination['copy']['set_no'] == '1000-1'
    label, need = destination['copy']['label'], destination['need']
    soup = BeautifulSoup(client.get(f'/workbench/orders/{oid}?view=allocation').text, 'html.parser')
    assert f'1000-1 · {label} · {need} missing' in soup.select_one('[data-allocation]').parent.text


def test_order_dates_keep_year_and_missing_currency_is_stated(world, client, coll):
    oid, _, _ = saved(coll.db)
    coll.sql("UPDATE purchase_order SET bricklink_order_id='777',store='Old store',currency=NULL,cost=NULL,date_ordered='2024-03-09' WHERE id=?", (oid,))
    for url in ('/workbench/orders', f'/workbench/orders/{oid}'):
        text = client.get(url).text
        assert '9 Mar 2024' in text and '9 Mar<' not in text
    # a price and its currency are stored together, so an order without a total has no currency: its line prices say so
    assert 'Currency not recorded' in client.get(f'/workbench/orders/{oid}').text


def test_draft_match_pair_reopen_are_preserved(world, client, coll):
    imported = orders.import_document(coll.db, 'xml', inventory(line_of('P', 'nowhere', colour=5), line_of('P', '3001', colour=5)))
    soup = page(client, imported['order_id'])
    assert soup.select_one('[data-action=match]')
    assert soup.select_one('[data-catalogue-search]')
    assert soup.select_one('[data-action=review]')
    assert soup.select_one('[name=item_id]')
    assert 'nowhere' in soup.select_one('[data-action=match] [name=item_no]')['value']
    orders.match(coll.db, imported['order_id'], orders.lines(coll.db, imported['order_id'])[0]['id'], item_id=world.brick, color_id=world.red)
    orders.phase(coll.db, imported['order_id'], imported['document_id'], 'review')
    soup = page(client, imported['order_id'])
    assert soup.select_one('[data-pair]')
    assert soup.select_one('[data-action=reopen]')
    assert soup.select_one('[data-action=save]')


def test_an_ambiguous_line_offers_its_candidates(world, client, coll):
    coll.link(world.plate, '3001', kind='P')
    imported = orders.import_document(coll.db, 'xml', inventory(line_of('P', '3001', colour=5)))
    soup = page(client, imported['order_id'])
    options = soup.select('[data-candidates] option')
    assert [o['value'] for o in options][1:] and {int(o['value']) for o in options[1:]} == {world.brick, world.plate}


def test_the_candidate_your_copies_are_missing_comes_first_with_its_count(world, client, coll):
    # Copy A misses one red 3001: of the two items BrickLink 3001 names, that one is listed first; the person still chooses.
    coll.link(world.plate, '3001', kind='P')
    imported = orders.import_document(coll.db, 'xml', inventory(line_of('P', '3001', colour=5)))
    options = page(client, imported['order_id']).select('[data-candidates] option')[1:]
    assert [int(o['value']) for o in options] == [world.brick, world.plate]
    assert '1 missing in your copies' in options[0].get_text() and 'missing' not in options[1].get_text()
    row = coll.db.execute('SELECT item_id, state FROM order_line WHERE order_id=?', (imported['order_id'],)).fetchone()
    assert tuple(row) == (None, 'by_hand')


def test_placed_orders_checkbox_data_duplicates_and_source_failure(world, client, token, coll, monkeypatch):
    oid, _, _ = saved(coll.db)
    coll.sql("UPDATE purchase_order SET bricklink_order_id='123' WHERE id=?", (oid,))
    monkeypatch.setattr(orders.BrickLink, 'list_orders', lambda self: [dict(order_id=123, store_name='Imported'), dict(order_id=456, store_name='New', date_ordered='2026-10-01')])
    assert client.post('/workbench/orders/action/placed', json={}).status_code == 400
    response = client.post('/workbench/orders/action/placed', json=dict(csrf_token=token))
    assert response.json['orders'] == [dict(number='123', store='Imported', date='', imported=True), dict(number='456', store='New', date='2026-10-01', imported=False)]

    def fail(self):
        raise SourceError('BrickLink key is unavailable')
    monkeypatch.setattr(orders.BrickLink, 'list_orders', fail)
    response = client.post('/workbench/orders/action/placed', json=dict(csrf_token=token))
    assert response.status_code == 400 and 'key is unavailable' in response.json['message']


def test_save_error_is_atomic_and_retry_controls_render(world, client, token, coll):
    oid, _, lid = saved(coll.db)
    orders.received(coll.db, oid, {lid: 2})
    result = client.post('/workbench/orders/action/allocate', json=dict(csrf_token=token, order_id=oid, chosen=[dict(line_id=lid, target_type='stock', quantity=3)]))
    assert result.status_code == 400
    soup = page(client, oid, 'allocation')
    assert soup.select_one('[data-notice][hidden] [data-message][role=status]')
    assert soup.select_one('[data-retry][hidden]').text == 'Retry'
    assert orders.detail(coll.db, oid)['allocated'] == 0


def test_orders_runtime():
    subprocess.run([shutil.which('node'), str(Path(__file__).with_name('toni_bw_orders_runtime.cjs'))], check=True, capture_output=True, text=True)
