"""Set detail in the B′ design (frame 12, #507): the 'frames-setdetail' world stages 7213-1 copy 1 with the frame's gaps, loose stock, prices and part-out coverage."""
from decimal import Decimal

import pytest

from brickwork.core import partout, selling
from brickwork.core.admin import database
from brickwork.demo import clock, frames_setdetail
from scripts import screen_gate
from tests import rendered
from tests.test_orders_frame import fetch

COPY = frames_setdetail.COPY


@pytest.fixture(scope='module')
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp('setdetail') / 'brickwork.db'
    screen_gate.build_store('frames-setdetail', path)
    return path


def test_setdetail_world_database_and_values(store):
    patched = clock.freeze_clock()
    try:
        with database(store) as db:
            gaps = db.execute(
                '''SELECT i.born_key AS part, c.name AS colour, p.quantity, p.missing
                   FROM copy_part p
                   JOIN item i ON i.id = p.item_id
                   JOIN color c ON c.id = p.color_id
                   WHERE p.copy_id = ? AND p.copy_figure_id IS NULL AND p.retired_at IS NULL AND p.is_spare = 0 AND p.missing > 0''',
                (COPY,),
            ).fetchall()
            assert len(gaps) == 7
            assert sum(r['missing'] for r in gaps) == 10
            by_part = {(r['part'], r['colour']): (r['missing'], r['quantity']) for r in gaps}
            assert by_part['3008', 'Red'] == (2, 2)
            assert by_part['3633', 'Dark Bluish Gray'] == (3, 4)

            loose_total = db.execute(
                '''SELECT coalesce(sum(s.quantity), 0)
                   FROM stock s
                   WHERE s.kind = 'part' AND s.archived_at IS NULL
                     AND EXISTS (
                         SELECT 1 FROM copy_part p
                         WHERE p.copy_id = ? AND p.copy_figure_id IS NULL AND p.retired_at IS NULL
                           AND p.is_spare = 0 AND p.missing > 0
                           AND p.item_id = s.item_id AND p.color_id = s.color_id
                     )''',
                (COPY,),
            ).fetchone()[0]
            assert loose_total == 4

            lines, pieces = db.execute(
                'SELECT count(*), coalesce(sum(quantity), 0) FROM copy_part WHERE copy_id = ? AND copy_figure_id IS NULL AND retired_at IS NULL AND is_spare = 0',
                (COPY,),
            ).fetchone()
            assert (lines, pieces) == (131, 375)

            paid = db.execute('SELECT purchase_date, purchase_price, purchase_currency FROM copy WHERE id = ?', (COPY,)).fetchone()
            assert (paid['purchase_date'], Decimal(str(paid['purchase_price'])), paid['purchase_currency']) == ('2025-03-09', Decimal('35.00'), 'EUR')

            card = selling.card(db, COPY)
            assert card['ask']['text'] == '€46.18'
            assert [r['amount'] for r in card['rows'] if r['kind'] == 'deduction'] == ['less €2.40']
            made = partout.values(db, [COPY])[COPY]
            assert Decimal(made['value']) == Decimal('41.80') and (made['priced'], made['lines']) == (117, 130)   # the Prices card: 117 of 130 lines (part and colour)
    finally:
        clock.thaw_clock(patched)


@rendered.group
def test_the_page_carries_the_shapes_of_frame_12():
    """The copy head above the tabs, the card order of the right column and the missing-card section (#507)."""
    with screen_gate.world('frames-setdetail') as base:
        page = fetch(base, '/collection/item/set/7213-1')
        root = page.select_one('#bw-collection')
        assert root.has_attr('data-b-copy')
        assert any('bw-setdetail-b.css' in link['href'] for link in page.select('link[rel=stylesheet]'))
        head = root.select_one('[data-bc-copy-head]')
        assert head and head.find_previous_sibling(class_='bc-detail-hero') and head.find_next_sibling(class_='bc-detail-layout')
        assert head.select_one('h3').get_text() == '10 parts missing, 4 in loose stock'
        assert head.select_one('.bc-progress-present').get_text() == '365/375'
        assert [b.get_text(strip=True) for b in head.select('.bc-check-actions a, .bc-check-actions button')] == ['Check parts', 'Edit parts', 'Check missing only']
        assert head.select_one('[data-bc-pl-checked]')['aria-checked'] == 'true'
        assert not root.select_one('[data-module=consists] [data-bc-pl-progress]')
        assert [m['data-module'] for m in root.select('.bc-detail-aside > [data-module]')][:5] == ['sell', 'value', 'info', 'prices', 'part-list']
        assert root.select_one('nav.bc-copy-seg [aria-current=page]')
        section = root.select_one('[data-module=consists] [data-bc-missing]')
        assert section.select_one('[data-bc-missing-label]') and section.select_one('[data-bc-missing-more]')
        cards = [c for c in root.select('.bc-missing-card') if c.select_one('.bc-missing-need')]
        assert len(cards) == 7 and all('--part-rgb:#' in c['style'] for c in cards)
        needs = {c.select_one('.bc-missing-meta .mono').get_text(): c.select_one('.bc-missing-need').get_text() for c in cards}
        assert needs['3008'] == 'needs 2 · 2 missing' and needs['3633'] == 'needs 4 · 3 missing'
        assert sorted(c.select_one('.bc-take-go').get_text() for c in cards if c.select_one('.bc-take-go')) == ['Take 1', 'Take 1', 'Take 2']
