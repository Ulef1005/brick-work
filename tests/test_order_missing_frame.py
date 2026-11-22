"""Order missing parts in the B′ design (frame 15, #510): the 'frames-order' world draws the three copies the frame draws, and the rows carry a bar to scale."""
import urllib.request

from bs4 import BeautifulSoup

from scripts import screen_gate
from tests import rendered


def fetch(base, path):
    with urllib.request.urlopen(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


@rendered.group
def test_the_frame_world_draws_the_three_copies_of_the_frame():
    with screen_gate.world('frames-order') as base:
        page = fetch(base, '/planning/order-missing-parts')
        assert page.select_one('.oo-crumb').get_text() == 'Planning · Order missing parts'
        assert page.select_one('[data-oo-summary]').get_text() == '3 sets have gaps · 3 in the list'
        rows = page.select('.oo-row')
        assert sorted(r.select_one('.oo-name strong').get_text().replace('\xa0', ' ') for r in rows) == ['Imperial Flagship', 'Off-Road Fire Truck & Fireboat', 'Passenger Train']
        assert sorted(int(r.select_one('.oo-gap b').get_text()) for r in rows) == [12, 14, 33]            # 59 pieces in all
        checking = [r for r in rows if 'Check in progress' in r.select_one('.oo-meta').get_text()]
        assert [r.select_one('.oo-name strong').get_text().replace('\xa0', ' ') for r in checking] == ['Imperial Flagship']
        for row in rows:                                                                                  # each bar: the found part to scale and a hatched stub for the gap
            assert row.select_one('.oo-bar-scale .oo-found') and row.select_one('.oo-bar-scale .oo-gone')
        assert page.select_one('.oo-tape h2').get_text().endswith('from 3 sets')
