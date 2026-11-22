"""Set detail in the B′ design (frame 12, #507): the 'frames-setdetail' world stages 7213-1 copy 1 with the frame's gaps, loose stock, prices and part-out coverage."""
from decimal import Decimal

import pytest

from brickwork.core import partout, selling
from brickwork.core.admin import database
from brickwork.demo import clock, frames_setdetail
from scripts import screen_gate

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
            assert Decimal(partout.values(db, [COPY])[COPY]['value']) == Decimal('41.80')
    finally:
        clock.thaw_clock(patched)
