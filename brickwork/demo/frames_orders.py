"""Frame 16 (Orders, #511) as the 'frames-orders' gate world: the `frames` collection whose order 9900102 is the one the frame counts.

The showcase imports 9900102 (Example Parts Depot) with five random parts, 6, 11, 16, 21 and 26 ordered, the first three received in one save. The frame draws
Wedge Plate 4 × 2 Right (41769, Light Bluish Gray), Brick 1 × 3 (3622, Tan), Brick 1 × 2 (3004, Light Bluish Gray), Plate 2 × 14 (91988, Tan) and Brick 1 × 4
(3010, Dark Bluish Gray): 6, 11, 16, 26 and 36 ordered (95), 6, 11, 13, 26 and 0 received (56), in one save whose Undo works. Events are append-only, so the
order is imported that way from the start rather than rewritten afterwards: `OrdersLayer.orders` is the showcase's, with 9900102's lines and counts the frame's
(its random draw still happens, so 9900101 and 9900103 stay the showcase's). The order's total stays €14.54; the lines' prices are not drawn by the frame."""
import random

from ..core import orders as order_core
from ..core.transaction import transaction
from . import frames, real, showcase

# (BrickLink part, BrickLink colour, ordered, received): Light Bluish Gray is 86, Tan 2, Dark Bluish Gray 85 on BrickLink.
LINES = (('41769', 86, 6, 6), ('3622', 2, 11, 11), ('3004', 86, 16, 13), ('91988', 2, 26, 26), ('3010', 85, 36, 0))
ORDER = '9900102'
COST = 14.54   # the frame's total, the showcase's own for this order


class OrdersLayer(frames.Layer):
    def orders(self, db):
        """The showcase's three orders (showcase.Layer.orders), 9900102 as frame 16 draws it."""
        made = [('Sample Bricks Store', '9900101', '2026-09-28', 'Received', 7, 'all'), ('Example Parts Depot', ORDER, '2026-10-05', 'Shipped', 5, 'frame'),
                ('Demo Brick Outlet', '9900103', '2026-10-10', 'Pending', 4, None)]
        order_rng = random.Random(showcase.SEED + 1)
        placeable = [r for r in self.stockpool if order_core._place(db, 'P', r['part'], showcase.bricklink_colour(db, r['color']['id']))[0] is not None]
        for number, (store, bricklink, ordered, status, count, arrived) in enumerate(made):
            rows = order_rng.sample(placeable, count)          # drawn for every order, so the other two keep the showcase's parts
            if arrived == 'frame':
                items = [(part, colour, qty, 'N', 0.05) for part, colour, qty, _ in LINES]
                cost = COST
            else:
                lines = [(row, 6 + index * 5, 'N' if (index + number) % 3 else 'U', 0.04 + 0.03 * ((index * 5 + number) % 6)) for index, row in enumerate(rows)]
                items = [(row['part'], showcase.bricklink_colour(db, row['color']['id']), qty, condition, price) for row, qty, condition, price in lines]
                cost = sum(qty * price for _, _, qty, _, price in items) + 3.9
            xml = ('<INVENTORY><ORDERDATE>%s</ORDERDATE><STATUS>%s</STATUS><CURRENCY>EUR</CURRENCY><COST>%.2f</COST>' % (ordered, status, cost) + ''.join(
                '<ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>%s</ITEMID><COLOR>%d</COLOR><QTY>%d</QTY><CONDITION>%s</CONDITION><PRICE>%.2f</PRICE></ITEM>'
                % item for item in items) + '</INVENTORY>')
            result = order_core.import_document(db, 'xml', xml, number=bricklink, label=store)
            with transaction(db):
                db.execute('UPDATE purchase_order SET store=?, seller=? WHERE id=?', (store, store, result['order_id']))
            if arrived is None:
                continue
            order_core.phase(db, result['order_id'], result['document_id'], 'review')
            order_core.phase(db, result['order_id'], result['document_id'], 'save')
            saved = order_core.detail(db, result['order_id'])['saved']
            if arrived == 'frame':
                if [(r['item_no'], r['qty']) for r in saved] != [(part, qty) for part, _, qty, _ in LINES]:
                    raise RuntimeError(f'frame 16: order {ORDER} did not import as the frame draws it: {[(r["item_no"], r["qty"]) for r in saved]}')
                order_core.received(db, result['order_id'], {r['id']: got for r, (_, _, _, got) in zip(saved, LINES) if got})
                continue
            order_core.received(db, result['order_id'], {r['id']: r['qty'] for r in (saved if arrived == 'all' else saved[:3])})
            if arrived == 'all':
                order_core.allocate(db, result['order_id'], [dict(line_id=r['id'], quantity=r['qty'], target_type='stock', storage_id='storage-drawer-3') for r in saved])
                order_core.reconcile(db, result['order_id'])


def orders_layer(folder=real.FOLDER, pictures=False):
    return OrdersLayer(folder, pictures, runner=True)   # frames.layer's arguments
