"""Build Scout in the B′ design (frame 10, #499): the 'frames-scout' world draws the numbers the frame draws, and the page names them as the frame does."""
import urllib.request

from bs4 import BeautifulSoup

from scripts import screen_gate
from tests import rendered


def fetch(base, path):
    with urllib.request.urlopen(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


@rendered.group
def test_the_frame_world_lists_four_sets_with_the_frames_numbers():
    with screen_gate.world('frames-scout') as base:
        page = fetch(base, '/workbench/build-scout?min_percent=0')
        assert page.select_one('.lbl').get_text() == 'Workbench · Build Scout' and page.select_one('h1').get_text() == 'Build Scout'
        assert '4 of 7 sets · 1,042 loose pieces counted' in page.select_one('.bs-fields > .cap2').get_text()
        rows = page.select('a.bs-row')
        assert [(r.select_one('.bs-num').get_text(), r.select_one('.bartxt').get_text(' ', strip=True)) for r in rows] == [
            ('21028-1', '412 of 598 · 69 %'), ('31120-1', '503 of 1,426 · 35 %'), ('8043-1', '97 of 1,123 · 9 %'), ('10254-1', '30 of 714 · 4 %')]
        sides = [r.select_one('.bs-side').get_text(' ', strip=True) for r in rows]
        assert sides == ['186 parts missing · no figures €6.10 · 12 lines unpriced', '923 parts missing · 4 of 4 figures missing €41.20 · 31 lines unpriced',
                         '1,026 parts missing · 1 of 1 figure missing not priced', '684 parts missing · 5 of 5 figures missing not priced']
        assert not any('−' in side for side in sides)            # no minus before a number (DESIGN-CHECK)
        panel = page.select_one('[data-bs-panel]')
        assert '412 of 598 · 186 missing in 23 lines' in panel.select_one('.bs-count').get_text() and panel.select_one('.bs-figures').get_text() == 'No figures in this set'
        lines = [(g.select_one('.bs-gap-part').get_text().replace('\xa0', ' '), g.select_one('.bs-gap-sub').get_text(' ', strip=True), g.select_one('.bs-gap-qty').get_text()) for g in panel.select('.bs-gap')][:3]
        assert lines == [('Brick 1 × 6', 'Light Bluish Gray · 3009', '14 missing'), ('Brick 1 × 4', 'Dark Bluish Gray · 3010', '12 missing'),
                         ('Slope 45° 2 × 2', 'White · 87619', '11 missing')]
        assert panel.select_one('.bs-more-lines summary').get_text() == '+ 20 more lines · Show all'
        assert '≈ €6.10 · 12 lines unpriced' in panel.select_one('.bs-panel-cost').get_text()
        assert page.select_one('summary.bs-more-summary').get_text() == 'Filters · 7'
