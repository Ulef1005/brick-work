"""Orders in the B′ design (frame 16, #511): the 'frames-orders' world draws order 9900102 as the frame counts it, and the page carries the frame's shapes."""
import http.cookiejar
import json
import urllib.request

from bs4 import BeautifulSoup

from scripts import screen_gate
from tests import rendered


OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def fetch(base, path):
    with OPENER.open(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


@rendered.group
def test_the_frame_world_draws_the_order_of_the_frame():
    with screen_gate.world('frames-orders') as base:
        page = fetch(base, '/workbench/orders/2?view=count')                      # frame_check's 16-orders target names order 2
        assert page.select_one('.order-header h1').get_text() == 'Example Parts Depot'
        assert page.select_one('.order-sidebar .order-crumb').get_text() == 'Workbench · Orders'
        assert page.select_one('[data-progress]').get_text() == '56 of 95 pieces counted · 39 still to count'
        rows = page.select('[data-order-panel=count] .order-count-row')
        assert [r.select_one('.bw-identity .mono').get_text() for r in rows] == ['41769', '3622', '3004', '91988', '3010']
        assert [int(r.select_one('.order-ordered').get_text()) for r in rows] == [6, 11, 16, 26, 36]
        assert [int(r.select_one('[data-received]')['value']) for r in rows] == [6, 11, 13, 26, 0]
        assert [r.select_one('.order-count-state')['data-state'] for r in rows] == ['complete', 'complete', 'short', 'complete', 'none']
        assert [r.select_one('.order-ordered-sub').get_text() for r in rows][:1] == ['ordered 6']
        shapes = {a.select_one('strong').get_text(): a.select_one('.status')['data-shape'] for a in page.select('.order-list-item')}
        assert shapes == {'Demo Brick Outlet': 'dash', 'Example Parts Depot': 'dash', 'Sample Bricks Store': 'solid'}
        audit = [r for r in page.select('[data-order-panel=count] > .bw-ledger-row') if 'Received counts saved' in r.get_text()]
        assert len(audit) == 1 and audit[0].select_one('[data-undo-event]')            # one save, with its Undo
        undo = urllib.request.Request(base + '/workbench/orders/action/undo', method='POST', headers={'Content-Type': 'application/json'},
                                      data=json.dumps({'csrf_token': page.select_one('#bw-ledger')['data-csrf'], 'event_id': int(audit[0].select_one('[data-undo-event]')['data-undo-event'])}).encode())
        with OPENER.open(undo) as response:                                           # the staged save is journalled: its Undo works
            assert response.status == 200
        assert fetch(base, '/workbench/orders/2?view=count').select_one('[data-progress]').get_text() == '0 of 95 pieces counted · 95 still to count'
