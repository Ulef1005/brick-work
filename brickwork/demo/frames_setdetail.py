"""Frame 12 (Set detail of 7213-1, copy 1, #507) as the 'frames-setdetail' gate world: the `frames` collection with 7213-1 copy 1 staged as the frame draws it.

Copy 1 ("Set 1") keeps the 131 non-spare part lines and 375 pieces of `frames.Layer`, with two pieces moved to 3633 (Dark Bluish Gray) from the largest
non-gap line so that 3633 has 4 pieces (3 missing) and 3008 (Red) has 2 (2 missing). The copy is marked checked with 7 gap lines summing to 10 missing
pieces, 4 pieces in loose stock on Shelf A2 – Town (leaving 6 to order), paid 35.00 EUR on 2025-03-09, and priced at 48.58 EUR used (9 sold) and 112.00 EUR
new (3 sold). Used part prices on the 7 gap lines deduct 2×0.30 + 3×0.20 + 5×0.24 = €2.40 (asking price €46.18), and 118 of the 131 lines (90 %) are priced to
sum to €44.20 over all pieces (€41.80 present, below the asking price so the part-out floor does not apply)."""
from decimal import Decimal

from ..core import stock
from ..core.transaction import transaction
from . import clock, dataset, frames, real
from .showcase import seeded_uuids

COPY = real.uid('copy', '7213-1', 'a')     # copy 1 ("Set 1" in the app)
GAPS = {('3008', 4): 2, ('3633', 72): 3, ('2412b', 72): 1, ('2654', 1): 1, ('30000', 71): 1, ('3001', 4): 1, ('3002', 15): 1}   # (part, Rebrickable colour id) -> missing: 7 lines, 10 pieces
LOOSE = {('3008', 4): 1, ('3633', 72): 2, ('2412b', 72): 1}   # loose stock of the gap lines: 4 can be taken, 6 to order
GAP_PRICE = {('3008', 4): '0.30', ('3633', 72): '0.20'}; OTHER_GAP_PRICE = '0.24'   # used quotes per piece: 2×0.30 + 3×0.20 + 5×0.24 = €2.40 deducted
PARTOUT_TOTAL = '44.20'   # sum over the 118 priced lines of quantity × price (all pieces); what is present is 44.20 − 2.40 = 41.80, below the asking price, so the part-out floor does not apply
PRICED_LINES = 118        # of the copy's 131 non-spare part lines (90 %, the part-out coverage rule)
PAID = ('2025-03-09', '35.00')            # purchase date and price in EUR
SET_USED = (48.58, 9); SET_NEW = (112.00, 3)   # 7213-1's sold quotes (average, sold count)
OBSERVED = '2026-10-12T06:00:00.000Z'   # when the part quotes were seen


class SetDetailLayer(frames.Layer):
    def __init__(self, folder=real.FOLDER, pictures=False):
        super().__init__(folder, pictures)
        lines = [r for r in self.inventories['7213-1']['parts'] if not r['spare']]
        fence = next(r for r in lines if (r['part'], r['color']['id']) == ('3633', 72))
        big = max((r for r in lines if (r['part'], r['color']['id']) not in GAPS), key=lambda r: (r['quantity'], r['part'], r['color']['id']))
        assert big['quantity'] >= 3
        fence['quantity'] += 2
        big['quantity'] -= 2

    def prices(self, db):
        """The sets' quotes as frames.Layer writes them; 7213-1's own are written last, in `stage`, because dataset.fill adds a used quote per paid copy
        (1.35 × the price paid, at the demo stamp) after this runs, and the newest quote is the one the cards show."""
        super().prices(db)

    def fill(self, db, ids):
        super().fill(db, ids)
        with transaction(db):
            patched = clock.freeze_clock()
            try:
                with seeded_uuids(self.rng):
                    self.stage(db)
            finally:
                clock.thaw_clock(patched)

    def stage(self, db):
        lines = [dict(r) for r in db.execute(
            '''SELECT p.id,p.quantity,p.item_id,p.color_id,i.born_key AS part,c.born_key AS colour
               FROM copy_part p JOIN item i ON i.id=p.item_id LEFT JOIN color c ON c.id=p.color_id
               WHERE p.copy_id=? AND p.copy_figure_id IS NULL AND p.retired_at IS NULL AND p.is_spare=0 ORDER BY p.id''',
            (COPY,),
        )]
        for r in lines:
            r['identity'] = (r['part'], int(r['colour']))
        db.execute('UPDATE copy_part SET missing=0 WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL AND is_spare=0', (COPY,))
        by_identity = {r['identity']: r for r in lines}
        assert set(GAPS).issubset(by_identity), f'frames-setdetail: missing gap lines {sorted(set(GAPS) - set(by_identity))}'
        for identity, missing in GAPS.items():
            row = by_identity[identity]
            assert row['quantity'] >= missing, f'frames-setdetail: {identity} has quantity {row["quantity"]} < {missing}'
            db.execute('UPDATE copy_part SET missing=? WHERE id=? AND retired_at IS NULL', (missing, row['id']))

        item = dataset.item_by(db, 'sets', '7213-1')    # the frame's quotes replace dataset.fill's own (see `prices`), as gate_edge.ValueLayer clears a set's
        db.execute('DELETE FROM price_current WHERE item_id=?', (item,))
        db.execute('DELETE FROM price_observation WHERE item_id=?', (item,))
        dataset.price(db, item, None, 'U', SET_USED[0], SET_USED[1], dataset.STAMP)
        dataset.price(db, item, None, 'N', SET_NEW[0], SET_NEW[1], dataset.STAMP)
        db.execute("UPDATE copy SET purchase_date=?, purchase_price=?, purchase_currency='EUR' WHERE id=?", (PAID[0], PAID[1], COPY))

        shelf = 'storage-' + dataset.slug('Shelf A2 – Town')
        for identity in GAPS:
            row = by_identity[identity]
            db.execute("UPDATE stock SET archived_at=? WHERE kind='part' AND item_id=? AND color_id=? AND archived_at IS NULL",
                       (dataset.STAMP, row['item_id'], row['color_id']))
        for identity, quantity in LOOSE.items():
            row = by_identity[identity]
            stock.add_loose(db, item_id=row['item_id'], color_id=row['color_id'], quantity=quantity, condition='used', storage_id=shelf, via='cli')

        need = PRICED_LINES - len(GAPS)
        other = [r for r in lines if r['identity'] not in GAPS]
        chosen = other[:need]
        ones = [r for r in chosen if r['quantity'] == 1]
        if ones:
            last_one = ones[-1]
            chosen = [r for r in chosen if r is not last_one] + [last_one]
        else:
            last_one = next((r for r in other[need:] if r['quantity'] == 1), None)
            assert last_one is not None, 'frames-setdetail: no quantity-1 line available for the part-out remainder'
            chosen = chosen[:-1] + [last_one]

        base_price = Decimal('0.10')
        total = Decimal(0)
        for identity in GAPS:
            row = by_identity[identity]
            unit = Decimal(GAP_PRICE.get(identity, OTHER_GAP_PRICE))
            dataset.price(db, row['item_id'], row['color_id'], 'U', unit, 5, OBSERVED)
            total += unit * row['quantity']
        for row in chosen[:-1]:
            dataset.price(db, row['item_id'], row['color_id'], 'U', base_price, 5, OBSERVED)
            total += base_price * row['quantity']
        remainder = Decimal(PARTOUT_TOTAL) - total
        assert remainder > 0, f'frames-setdetail: remainder must be positive, got {remainder}'
        last = chosen[-1]
        dataset.price(db, last['item_id'], last['color_id'], 'U', remainder, 5, OBSERVED)

        missing_lines, missing_sum = db.execute(
            'SELECT count(*), coalesce(sum(missing), 0) FROM copy_part WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL AND is_spare=0 AND missing>0',
            (COPY,),
        ).fetchone()
        assert (missing_lines, missing_sum) == (7, 10), f'frames-setdetail: expected 7 gap lines summing to 10, got {(missing_lines, missing_sum)}'
        loose_sum = sum(
            db.execute("SELECT coalesce(sum(quantity), 0) FROM stock WHERE kind='part' AND item_id=? AND color_id=? AND archived_at IS NULL",
                       (by_identity[identity]['item_id'], by_identity[identity]['color_id'])).fetchone()[0]
            for identity in GAPS
        )
        assert loose_sum == 4, f'frames-setdetail: expected 4 loose pieces across gap lines, got {loose_sum}'


def setdetail_layer(folder=real.FOLDER, pictures=False):
    return SetDetailLayer(folder, pictures)
