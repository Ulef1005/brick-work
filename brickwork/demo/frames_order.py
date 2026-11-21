"""Frame 15 (Order missing parts, #510) as the 'frames-order' gate world: the `frames` collection cut to the sets the frame draws.

The frame lists three copies: 7213-1 copy 2 (12 parts missing), 10210-1 (33, its check running) and 7938-1 (14): 12 + 33 + 14 = 59 pieces. The `frames` world has a fourth gap,
copy 1 of 7213-1 (10 pieces, frame 07's), and puts the running check on copy 2 of 7213-1 (frame 06's). Here copy 1 of 7213-1 has no gap and the running check is
10210-1's, which is all this page reads of it (`order_missing.candidates` asks only whether an unfinished check exists). Where the frame's own numbers disagree with each other
(its order list says 59 lines and 59 pieces yet shows lines of two and four pieces, and its sets are not in the order of "Most missing") the data follows the page's rules."""
from ..core.admin import database
from ..core.transaction import transaction
from . import clock
from .frames import INSPECTOR


def stage_order(store):
    patched = clock.freeze_clock()
    try:
        with database(store) as db:
            with transaction(db):
                second = INSPECTOR['copy']
                first = db.execute("SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='7213-1' AND c.id!=?", (second,)).fetchone()[0]
                imperial = db.execute("SELECT c.id FROM copy c JOIN item i ON i.id=c.item_id WHERE i.born_key='10210-1'").fetchone()[0]
                db.execute('UPDATE copy_part SET missing=0 WHERE copy_id=? AND retired_at IS NULL', (first,))
                db.execute("UPDATE copy SET completeness='complete' WHERE id=?", (first,))
                db.execute('UPDATE part_check SET copy_id=? WHERE copy_id=? AND copy_figure_id IS NULL AND finished=0', (imperial, second))
    finally:
        clock.thaw_clock(patched)
