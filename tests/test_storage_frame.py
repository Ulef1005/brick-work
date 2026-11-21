"""Storage in the B′ design (frame 11, #500): the 'frames-storage' world has the six storages the frame lists, and the page draws them as the frame does."""
import urllib.request

from bs4 import BeautifulSoup

from scripts import screen_gate
from tests import rendered


def fetch(base, path):
    with urllib.request.urlopen(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


@rendered.group
def test_the_frame_world_lists_six_storages_and_draws_shelf_a2_as_tiles():
    with screen_gate.world('frames-storage') as base:
        page = fetch(base, '/workbench/storage/storage-shelf-a2---town')
        assert page.select_one('.st-head .lbl').get_text() == 'Workbench · Storage'
        assert page.select_one('.st-head p').get_text() == '6 storages · 7 sets · 0 figures · 6 part lots'
        rows = [[c.get_text(' ', strip=True) for c in r.select('.st-code, .st-name, .st-num')] for r in page.select('.st-row')]
        assert rows == [['S-0001', 'Shelf A1 – Castle Shelf', '2', '—', '—'], ['S-0002', 'Shelf A2 – Town Shelf', '3', '—', '—'],
                        ['S-0003', 'Parts drawer unit Drawer', '—', '—', '6'], ['S-0004', 'Display case Shelf', '1', '—', '—'],
                        ['S-0005', 'Technic crate Box', '1', '—', '—'], ['S-0006', 'Bag 07 Bag', '—', '—', '—']]
        assert [c.get_text(' ', strip=True) for c in page.select('.tape > *')] == ['S-0002', 'Shelf A2 – Town', '3 sets']
        assert page.select_one('.st-detail-meta').get_text(' ', strip=True) == 'Shelf · 3 sets · 4 copies · 0 figures · 0 part lots'
        tiles = [(t.select_one('.num').get_text(' ', strip=True), t.select_one('.meta').get_text(), [b.get_text(' ', strip=True) for b in t.select('.bartxt, .tag')])
                 for t in page.select('.stile')]
        assert tiles == [('7213-1 €48.58', 'Fire · 2010 · 2 copies', ['#1 365/375 · 10 missing', '#2 130/375 · 12 missing']),
                         ('7938-1 €65.73', 'Trains · 2010', ['643/657 · 14 missing']), ('10254-1 €99.53', 'Creator · 2016', ['Sealed'])]
        assert not any('−' in t.get_text() for t in page.select('.stile'))     # no minus before a number (DESIGN-CHECK)
