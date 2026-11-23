"""Lot Sorter in the B′ design (frame 14, #509): the 'frames-lot' world draws the numbers the frame draws, and the lot page and the pull list name them as the frame does."""
import urllib.request

from bs4 import BeautifulSoup

from brickwork.demo import real
from scripts import screen_gate
from tests import rendered

PULL = '/pull/11'      # catalogue item 11 is 7938-1 (scripts/frame_check.py PHONE_PATH)


def fetch(base, path):
    with urllib.request.urlopen(base + path) as response:
        return BeautifulSoup(response.read().decode(), 'html.parser')


@rendered.group
def test_the_frame_world_draws_the_lot_the_frame_draws():
    with screen_gate.world('frames-lot') as base:
        page = fetch(base, '/collection/lots/' + real.LOT + '?detect=1')
        head = page.select_one('#lot-b .head')
        assert head.select_one('.lbl').get_text() == 'Workbench · Lot Sorter' and head.select_one('h1').get_text() == 'Flea market bag'
        assert head.select_one('p').get_text() == '84 parts · 28 original lines · 1 with a sticker'
        facts = [(d.select_one('dt').get_text(), d.select_one('dd').get_text()) for d in page.select('#lot-b .lb-facts dl > div')]
        assert facts == [('Storage', 'Not recorded'), ('Place', 'Not recorded'), ('Bought', 'Not recorded'), ('Price', 'Not recorded'), ('Note', 'One bag, no list')]
        assert page.select_one('#set-detection .tape').get_text(' ', strip=True) == 'Set detection 3 candidate sets'
        rows = page.select('.bd-cand')
        assert [(r.select_one('.bd-number').get_text(), r.select_one('.bd-pct').get_text()) for r in rows] == [('7213-1', '100 %'), ('7938-1', '68 %'), ('31120-1', '38 %')]
        reasons = [r.select_one('.bd-reasons').get_text() for r in rows]
        assert [t.split(' distinctive')[0].split(' of ')[0] for t in reasons] == ['14', '9', '5']
        assert [t.split(' · ')[1] for t in reasons] == ['10 parts only in this set', '9 parts only in this set', '5 parts only in this set']
        first = rows[0]
        assert first.select_one('.bd-best').get_text() == 'best match' and first.select_one('.bd-toggle .bd-close-text').get_text() == 'Hide details'
        assert [b.get_text() for b in first.select('.bd-actions .btn')] == ['Pull list', 'Open set 7213-1']
        assert first.select('.bd-tile.bd-yes') and first.select('.bd-tile.bd-no') and not first.select('.bd-swaps li')
        assert not [r for r in rows[1:] if r.select_one('details').has_attr('open')]
        assert page.select_one('.lb-more').get_text().startswith('+ ')              # the tiles stop at 16 and the count says how many more
        assert max(len(r.select('.bd-tile')) for r in rows) <= 32


@rendered.group
def test_the_pull_list_and_its_confirm_read_as_the_phone_frame():
    with screen_gate.world('frames-lot') as base:
        page = fetch(base, '/collection/lots/' + real.LOT + PULL + '/make-copy')
        assert page.select_one('.bp-title').get_text(' ', strip=True) == 'Passenger Train 7938-1'
        assert page.select_one('.bp-prog').get_text(' ', strip=True) == '17 of 657 pieces found 640 to find'
        assert [r.select('span')[1].get_text() for r in page.select('#bp-confirm .bp-mv')] == ['17', '640', '67']
        status = page.select_one('#bp-confirm .bp-status')
        assert [t.get_text() for t in status.select('.tag, .xchip')] == ['Incomplete', 'Not checked']
        assert page.select_one('#bp-confirm button').get_text() == 'Make copy of 7938-1'
