"""Frame 16 (Orders, #511) as the 'frames-orders' gate world: the `frames` collection with order 9900102 cut to the five lines the frame counts.

The showcase imports 9900102 (Example Parts Depot) with five random parts, 6, 11, 16, 21 and 26 ordered, the first three received in one save. The frame draws
Wedge Plate 4 × 2 Right (41769, Light Bluish Gray), Brick 1 × 3 (3622, Tan), Brick 1 × 2 (3004, Light Bluish Gray), Plate 2 × 14 (91988, Tan) and Brick 1 × 4
(3010, Dark Bluish Gray): 6, 11, 16, 26 and 36 ordered (95), 6, 11, 13, 26 and 0 received (56). The lines are rewritten in place and the one receipt keeps its
event, so the Count audit still shows a single "Received counts saved" with its Undo. The other two orders (9900101 reconciled, 9900103 a draft) are the frame's."""
from ..core import orders
from ..core.admin import database
from ..core.transaction import transaction
from . import clock

# (BrickLink part, BrickLink colour, ordered, received): Light Bluish Gray is 86, Tan 2, Dark Bluish Gray 85 on BrickLink.
LINES = (('41769', 86, 6, 6), ('3622', 2, 11, 11), ('3004', 86, 16, 13), ('91988', 2, 26, 26), ('3010', 85, 36, 0))
ORDER = '9900102'


def stage_orders(store):
    patched = clock.freeze_clock()
    try:
        with database(store) as db:
            with transaction(db):
                order = db.execute('SELECT id FROM purchase_order WHERE bricklink_order_id=?', (ORDER,)).fetchone()[0]
                rows = [r[0] for r in db.execute('SELECT id FROM order_line WHERE order_id=? AND paired_line_id IS NULL ORDER BY document_id,line_no', (order,))]
                assert len(rows) == len(LINES), rows
                for line, (number, colour, qty, got) in zip(rows, LINES):
                    item, colour_id, _, why = orders._place(db, 'P', number, colour)
                    assert item is not None, (number, why)
                    db.execute('UPDATE order_line SET item_id=?,color_id=?,raw_item_no=?,raw_color_id=?,raw_name=NULL,qty=? WHERE id=?', (item, colour_id, number, colour, qty, line))
                    if got:                     # the showcase received the first three lines; the frame's fourth joins the same save (its stamp)
                        stamp = db.execute('SELECT max(updated_at) FROM line_receipt WHERE line_id IN (%s)' % ','.join('?' * len(rows)), rows).fetchone()[0]
                        db.execute('INSERT INTO line_receipt(line_id,received,updated_at) VALUES(?,?,?) ON CONFLICT(line_id) DO UPDATE SET received=excluded.received', (line, got, stamp))
                        if db.execute('UPDATE line_receipt_log SET new=? WHERE line_id=?', (got, line)).rowcount == 0:
                            db.execute('INSERT INTO line_receipt_log(line_id,at,old,new) VALUES(?,?,0,?)', (line, stamp, got))
                    else:
                        db.execute('DELETE FROM line_receipt_log WHERE line_id=?', (line,))
                        db.execute('DELETE FROM line_receipt WHERE line_id=?', (line,))
    finally:
        clock.thaw_clock(patched)
