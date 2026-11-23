"""Frame 10 (Build Scout, #499) as the 'frames-scout' gate world: the frames collection with four sets whose loose stock and missing lines are shaped to the numbers the frame draws.

The frame draws 4 of the 7 sets (1,042 loose pieces counted): 21028-1 412 of 598 (186 missing in 23 lines, three of them 14, 12 and 11), 31120-1 503 of 1,426, 8043-1
97 of 1,123 and 10254-1 30 of 714, with a cost for the first two and "not priced" for the last two. Where the data disagrees with the frame the data follows the frame (as
brickwork/demo/frames.py says): the four sets get the line plan below, the loose stock sits only on lines no other set needs (so 7213-1, 7938-1 and 10210-1 stay at 0 and
are not listed), the parts get the few prices the frame costs, and 8043-1 gets a figure (frame figures are sample data, design 2026-11-21)."""

from decimal import Decimal

from ..core.admin import database
from ..core.stock import add_loose
from ..core.transaction import transaction
from . import clock, dataset, real
from .frames import Layer
from .showcase import seeded_uuids

# the three lines the frame names in 21028-1's panel: (part, colour id, missing)
NAMED = (('3009', 71, 14), ('3010', 72, 12), ('87619', 15, 11))
NAMES = {'3009': 'Brick 1 x 6', '3010': 'Brick 1 x 4', '87619': 'Slope 45° 2 x 2'}      # the names the frame gives the three lines (the catalogue's 87619 is a longer train part)
HIDDEN = ('7213-1', '7938-1', '10210-1')
FIGURE_DONOR = '7938-1'          # 8043-1 gets the first figure of this set


def plan(covered, covered_total, missing, missing_total, priced=0):
    """`(covered quantities, missing quantities)`: `covered` lines summing to `covered_total`, `missing` lines summing to `missing_total`, as even as whole numbers allow."""
    def spread(lines, total):
        base, extra = divmod(total, lines)
        return [base + 1 if i < extra else base for i in range(lines)]
    return spread(covered, covered_total), spread(missing, missing_total)


# set -> (covered lines, pieces covered, missing lines, pieces missing); the totals are the frame's
PLAN = {
    '21028-1': (29, 412, 20, 149),      # plus the three named lines (14 + 12 + 11 = 37): 186 missing in 23 lines
    '31120-1': (25, 503, 36, 923),      # 9 costed lines + 27 unpriced + the 4 figures: "31 lines unpriced"
    '8043-1': (5, 97, 30, 1026),
    '10254-1': (2, 30, 40, 684),
}
# 31120-1's costed lines: eight lines of 23 at 0.20 and one of 22 at 0.20 make 41.20; the other 31 missing lines are unpriced. 21028-1 costs 11 lines at 0.0x each: 6.10
PRICED_31120 = 9
CENT = Decimal('0.01')


def key(row):
    return (row['part'], row['color']['id'])


class ScoutLayer(Layer):
    def __init__(self, folder=real.FOLDER, pictures=False):
        super().__init__(folder, pictures)
        self.covered_keys, self.priced = {}, {}
        for inventory in self.inventories.values():
            for row in inventory['parts']:
                if row['part'] in NAMES:
                    row['name'] = NAMES[row['part']]
        for number in PLAN:
            self.shape(number)
        self.give_figure('8043-1')
        self.check_hidden()

    def needs(self, number):
        return {key(r) for r in self.inventories[number]['parts'] if not r['spare']}

    def shape(self, number):
        """Rewrite the set's required lines to the plan: only lines no other set (as the other sets stand now) needs may be covered; the rest are missing lines."""
        covered_n, covered_total, missing_n, missing_total = PLAN[number]
        others = set().union(*[self.needs(n) for n in self.inventories if n != number])
        lines = [r for r in self.inventories[number]['parts'] if not r['spare']]
        spares = [r for r in self.inventories[number]['parts'] if r['spare']]
        unique = sorted((r for r in lines if key(r) not in others), key=lambda r: (r['part'], r['color']['id']))
        named = len(NAMED) if number == '21028-1' else 0
        if len(unique) < covered_n + missing_n:
            raise ValueError(f'frames-scout: {number} has only {len(unique)} lines of its own, the plan needs {covered_n + missing_n}')
        quantities_covered, quantities_missing = plan(covered_n, covered_total, missing_n, missing_total)
        if number == '31120-1':    # the nine costed lines first (eight of 23 and one of 22 at 0.20 cost 41.20), then the unpriced ones
            quantities_missing = [23] * 8 + [22] + plan(1, 0, missing_n - PRICED_31120, missing_total - 206)[1]
        chosen = unique[:covered_n + missing_n]
        rows = []
        for row, quantity in zip(chosen[:covered_n], quantities_covered):
            rows.append(dict(row, quantity=quantity))
            self.covered_keys.setdefault(number, {})[key(row)] = quantity
        for row, quantity in zip(chosen[covered_n:], quantities_missing):
            rows.append(dict(row, quantity=quantity))
        if named:
            every = [r for n in self.inventories if n != number for r in self.inventories[n]['parts'] if not r['spare']]
            for part, colour, missing in NAMED:
                template = next((r for r in every if r['part'] == part), None)
                tint = next((r['color'] for r in every if r['color']['id'] == colour), None)
                if template is None or tint is None:
                    raise ValueError(f'frames-scout: no line or colour for {(part, colour)} to copy')
                rows.append(dict(template, color=dict(tint), quantity=missing, checked=0, missing=0, damaged=0, figure=None))
        self.inventories[number]['parts'] = rows + spares
        # the missing lines in the order they are costed: 31120-1's first nine are the priced ones
        self.priced[number] = [key(r) for r in chosen[covered_n:]]

    def give_figure(self, number):
        donor = self.inventories[FIGURE_DONOR]
        figure = donor['minifigures'][0]
        self.inventories[number]['minifigures'] = [dict(figure)]
        self.inventories[number]['minifigure_parts'] = {figure['figure']: [dict(r) for r in donor['minifigure_parts'][figure['figure']]]}

    def check_hidden(self):
        """The three sets the frame does not list must stay at 0: nothing covered here may be a line they need."""
        hidden = set().union(*[self.needs(n) for n in HIDDEN])
        for number, keys in self.covered_keys.items():
            clash = hidden & set(keys)
            if clash:
                raise ValueError(f'frames-scout: {number} covers lines {sorted(clash)[:3]} that a hidden set needs')
            for other, other_keys in self.covered_keys.items():
                if other != number and set(keys) & self.needs(other):
                    raise ValueError(f'frames-scout: {number} covers lines that {other} needs')

    def fill(self, db, ids):
        """Only the staged stock and prices: no other loose stock, no wishes, no orders (the frame counts 1,042 loose pieces)."""
        patched = clock.freeze_clock()
        try:
            with seeded_uuids(self.rng):
                self.storage_and_places(db)
                with transaction(db):
                    db.execute('UPDATE stock SET archived_at=? WHERE archived_at IS NULL', (dataset.STAMP,))   # the storages' own parts are not the frame's stock
                    for number, keys in self.covered_keys.items():
                        for (part, colour), quantity in keys.items():
                            add_loose(db, item_id=dataset.item_by(db, 'parts', part), color_id=dataset.colour_by(db, colour), quantity=quantity,
                                      condition='used', storage_id='storage-box-5', via='cli')
                self.stage_prices(db)
        finally:
            clock.thaw_clock(patched)

    def stage_prices(self, db):
        """The costs the frame draws: 31120-1 nine costed lines (41.20), 21028-1 eleven (6.10, one of them a named line): everything else unpriced."""
        with transaction(db):
            def price(part, colour, amount):
                dataset.price(db, dataset.item_by(db, 'parts', part), dataset.colour_by(db, colour), 'U', float(amount), 25, dataset.STAMP)
            for line_key in self.priced['31120-1'][:PRICED_31120]:
                price(line_key[0], line_key[1], Decimal('0.20'))
            # 21028-1: the three named lines and eight more cost 6.10 together, in whole cents per piece
            quantity = {key(r): r['quantity'] for r in self.inventories['21028-1']['parts'] if not r['spare']}
            costed = [(part, colour) for part, colour, _ in NAMED] + self.priced['21028-1'][:8]
            for line_key, cents in zip(costed, cents_for([quantity[k] for k in costed], 610)):
                price(line_key[0], line_key[1], Decimal(cents) * CENT)


def cents_for(quantities, total_cents, low=2, high=14):
    """A whole-cent unit price in [low, high] for each line so that the sum of price times quantity is exactly `total_cents` (a small search, deterministic)."""
    reachable = {0: []}
    for quantity in quantities:
        step = {}
        for have, chosen in reachable.items():
            for cents in range(low, high + 1):
                step.setdefault(have + cents * quantity, chosen + [cents])
        reachable = step
    if total_cents not in reachable:
        raise ValueError(f'frames-scout: no whole-cent prices make {total_cents} cents from {quantities}')
    return reachable[total_cents]


def scout_layer(folder=real.FOLDER, pictures=False):
    return ScoutLayer(folder, pictures)
