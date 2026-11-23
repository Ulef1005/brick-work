"""Frame 14 (Lot Sorter, #509) as the 'frames-lot' gate world: the Flea market bag cut to the numbers the frame draws.

The frame draws a lot of 84 parts in 28 original lines, one with a sticker, and three candidate sets: 7213-1 at 100 % (14 distinctive parts found, 10 of them only in
that set), 7938-1 at 68 % (9 found, 9 only) and 31120-1 at 38 % (5 found, 5 only). The collection is the `frames` one (brickwork/demo/frames.py); only the lot differs from
the real world's: its 28 lines are the sticker line (held by 7213-1 and one set that is not a candidate, so that set stays under the minimum score), 10 lines only 7213-1 holds, 3 lines
7213-1 shares with sets that are not candidates, 9 lines only 7938-1 holds and 5 lines only 31120-1 holds. Where the data disagrees with the frame the data follows the
frame, as in frames_scout.py: the frame's "of 45 / 71 / 86 distinctive parts" are the frame's sample numbers; the sets of this world have 131, 118 and 306 lines (frame 06
draws 7213-1 with 131 of them), so those three totals read as the catalogue has them."""
import re

from ..core import stickers, stock
from ..core.transaction import transaction
from . import dataset, real
from .frames import Layer
from .showcase import uid

LOT_PARTS = 84
LOT_LINES = 28
# (set, own lines, shared lines): the lines of the lot that come from each candidate set; the partial lines are tuned (see PARTIAL) so the scores read 100, 68 and 38
PLAN = {'7213-1': (10, 3), '7938-1': (9, 0), '31120-1': (5, 0)}
CANDIDATES = tuple(PLAN)
OTHERS = ('10210-1', '10254-1', '21028-1')       # the sets 7213-1's shared lines come from (not candidates: one or two lines each stay far below the minimum score)
# The last own line of 7938-1 and of 31120-1 is a line of 2 and of 4 pieces with one piece short, so the scores read 68 and 38 (a short line counts its share of the weight).
SHORT = {'7938-1': 2, '31120-1': 4}
# 7938-1's nine lines (their needs, the last is the short one): the lot holds each in full but the last, 17 pieces, which the phone frame's confirm moves out of the lot (84 - 17 = 67 stay)
NEEDS = {'7938-1': [3, 1, 2, 2, 2, 2, 2, 2, 2]}
PARTIAL = {('7938-1', 8): 1, ('31120-1', 4): 3}  # (set, index of the own line) -> pieces in the lot, below the line's need


class LotLayer(Layer):
    def __init__(self, folder=real.FOLDER, pictures=False):
        super().__init__(folder, pictures)
        # The pull list counts a set's figures as pieces: Rebrickable's 657 lines of 7938-1 and its 3 figures make 660, the frame draws "17 of 657 found, 640 to find". The data
        # follows the frame, so the set has no figures here (frame 06 does the same for 7213-1, brickwork/demo/frames.py).
        inventory = self.inventories['7938-1']
        removed = [f['figure'] for f in inventory['minifigures']]
        inventory['minifigures'], inventory['minifigure_parts'] = [], {}
        self.figures = [f for f in self.figures if f not in removed]

    def holders(self):
        held = {}
        for number, inventory in self.inventories.items():
            for row in inventory['parts']:
                if not row['spare']:
                    held.setdefault((row['part'], row['color']['id']), set()).add(number)
        return held

    def lot_lines(self):
        """`(rows, base)`: the lines of the lot in the order of PLAN and the sticker line."""
        held = self.holders()
        rows, used = [], set()
        parts_of = {n: {r['part'] for r in inv['parts'] if not r['spare']} for n, inv in self.inventories.items()}
        base = None
        for partner in ('8043-1',) + OTHERS:
            base = next((r for r in self.inventories['7213-1']['parts'] if not r['spare'] and r['category'] != 'Stickers' and held[(r['part'], r['color']['id'])] == {'7213-1', partner}), None)
            if base is not None:
                used.add((base['part'], base['color']['id']))
                break
        if base is None:
            raise ValueError('frames-lot: no line of 7213-1 is held by exactly one other set')
        for number, (own, shared) in PLAN.items():
            inventory = [r for r in self.inventories[number]['parts'] if not r['spare'] and r['category'] != 'Stickers' and r is not base and not re.search(r'pr\d|[a-z]\d{3}', r['part'])
                         and (r['part'], r['color']['id']) not in used]
            mine = sorted((r for r in inventory if held[(r['part'], r['color']['id'])] == {number} and not any(r['part'] in parts_of[n] for n in parts_of if n != number)), key=lambda r: (r['quantity'], r['part'], r['color']['id']))
            picked = mine[:own]
            if number in NEEDS:
                picked = []
                for need in NEEDS[number]:
                    picked.append(next(r for r in mine if r['quantity'] == need and r not in picked))
            if number in SHORT and picked[-1]['quantity'] != SHORT[number]:
                picked[-1] = next(r for r in mine if r['quantity'] == SHORT[number] and r not in picked)
            for _ in range(shared):          # a line only 7213-1 and one non-candidate set hold, in a part no other set has in any colour (no swap to read)
                picked.append(next(r for r in inventory if r not in picked and len(held[(r['part'], r['color']['id'])]) == 2 and number in held[(r['part'], r['color']['id'])]
                                   and not held[(r['part'], r['color']['id'])] & set(CANDIDATES[1:]) and {n for n in parts_of if r['part'] in parts_of[n]} == held[(r['part'], r['color']['id'])]))
            used.update((r['part'], r['color']['id']) for r in picked)
            if len(picked) != own + shared:
                raise ValueError(f'frames-lot: {number} has too few lines of its own')
            rows += [(number, i, r) for i, r in enumerate(picked)]
        return rows, base

    def flea_market(self, db):
        rows, base = self.lot_lines()
        quantities = [PARTIAL.get((n, i), r['quantity']) for n, i, r in rows]
        quantities.append(base['quantity'])
        extra = LOT_PARTS - sum(quantities)
        if extra < 0:
            raise ValueError(f'frames-lot: the lines need {sum(quantities)} parts, the frame has {LOT_PARTS}')
        spare = [i for i, (n, k, r) in enumerate(rows) if (n, k) not in PARTIAL and n not in NEEDS]
        for step in range(extra):                        # the spare pieces go round the lines whose count is not tuned, one at a time, above their need
            quantities[spare[step % len(spare)]] += 1
        with transaction(db):
            db.execute('INSERT INTO lot(id, name, note, place_id, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)',
                       (real.LOT, real.LOT_NAME, 'One bag, no list', None, dataset.STAMP, dataset.STAMP))
            for (number, i, row), quantity in zip(rows, quantities):
                dataset_stock(db, row, quantity)
            made = dataset_stock(db, base, quantities[-1])
            flag, _ = stickers.ensure_flag(db)
            db.execute('INSERT OR IGNORE INTO stock_flag(stock_id, flag_id) VALUES(?, ?)', (made['id'], flag))


def dataset_stock(db, row, quantity):
    return stock.add_loose(db, item_id=dataset.item_by(db, 'parts', row['part']), color_id=dataset.colour_by(db, row['color']['id']), quantity=quantity,
                           condition='used', lot_id=real.LOT, via='cli')


def lot_layer(folder=real.FOLDER, pictures=False):
    return LotLayer(folder, pictures)
