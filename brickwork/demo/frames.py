"""The screen gate's `frames` worlds (#492, #494, #489): the data of the approved B′ frames, so the built page and the frame are compared on the same numbers.

The frames of design/screens-b show a collection the design project drew by hand. This layer is the real-sets world (`real`) with the numbers of the
Sets frames (04, 05) put in exactly: seven sets, eight copies, the label codes and names of four storages, the prices, and the bar of each copy (found
and missing pieces, to scale). It has no pictures (the frames show empty tiles with their alt text, because the public repo carries no catalogue
pictures) and no staged checks. Only the worlds `frames` and `frames-no-storage` (scripts/screen_gate.py) see any of it; the world `frames-no-storage`
is the same collection with no storage set on any copy (frame 05), and `frames-pulled` the same collection as frame 48 draws it: two copies were pulled from
Rebrickable (8043-1 with no Lost Parts, 21028-1 with 9 missing parts), so they carry `checked_by='rebrickable'` and no "Set is checked" flag.

Where a frame disagrees with the data it was drawn from, the data follows the frame: Rebrickable's non-spare lines of 31120-1 add up to 1,408 pieces,
the frame says 1,426, so one line of the copy holds 18 more pieces here. Everything is deterministic (the real world's seed and the demo clock)."""
from ..core.transaction import transaction
from . import dataset, real

# number: (copy 1 and 2 as (storage, found, missing); a copy with found and missing 0 is never checked). Sealed copies have no check.
FRAME = {
    '7213-1': (('Shelf A2 – Town', 365, 10), ('Shelf A2 – Town', 130, 12)),
    '7938-1': (('Shelf A2 – Town', 643, 14),),
    '10254-1': (('Shelf A2 – Town', 0, 0),),
    '10210-1': (('Shelf A1 – Castle', 1590, 33),),
    '31120-1': (('Shelf A1 – Castle', 1426, 0),),
    '8043-1': (('Technic crate', 0, 0),),
    '21028-1': (('Display case', 0, 0),),
}
# The codes of the label sheet: the storage page of the frames (11) lists S-0001 to S-0006; the other storages of the real world follow them.
CODES = ('Shelf A1 – Castle', 'Shelf A2 – Town', 'Parts drawer unit', 'Display case', 'Technic crate', 'Bag 07')
# Frame 48: the two copies a Rebrickable pull checked (storage, found, missing). The pull marks only the lost lines; every other piece counts as found.
PULLED = {'8043-1': (('Technic crate', 1123, 0),), '21028-1': (('Display case', 589, 9),)}
PRICES = {'7213-1': 48.58, '7938-1': 65.73, '10254-1': 99.53, '10210-1': 194.31, '31120-1': 127.00, '8043-1': 123.40, '21028-1': 53.94}


class Layer(real.Layer):
    def __init__(self, folder=real.FOLDER, pictures=False, stored=True, pulled=False):
        super().__init__(folder, pictures)
        self.stored = stored
        self.frame = dict(FRAME, **PULLED) if pulled else FRAME
        self.pulled = PULLED if pulled else {}
        for entry in self.sets:
            entry['storage'] = self.frame[entry['set']][0 if entry['id'] == real.uid('copy', entry['set'], 'a') else 1][0]
        line = next(r for r in self.inventories['31120-1']['parts'] if not r['spare'])
        line['quantity'] += 18                       # 1,408 pieces in Rebrickable's list, 1,426 on the frame

    def storage_and_places(self, db):
        with transaction(db):   # the real world's copies sat in these; the shelves of the base layer nest in them
            for name in ('Shelf B', 'Cabinet A', 'Mechanics crate', 'Box 5'):
                dataset.put(db, 'storage', 'storage-' + dataset.slug(name), name)
        super().storage_and_places(db)

    def missing_figures(self, db):
        """None: the frames count parts only, and a missing figure would make a copy's text say more than its bar."""

    def prices(self, db):
        with transaction(db):
            for number, value in PRICES.items():
                dataset.price(db, dataset.item_by(db, 'sets', number), None, 'U', value, 12, '2026-10-12T06:00:00.000Z')

    def fill(self, db, ids):
        super().fill(db, ids)
        with transaction(db):
            dataset.put(db, 'storage', 'storage-bag-07', 'Bag 07')
            self.codes(db)
            self.checks_to_frame(db)
            if not self.stored:
                db.execute('UPDATE copy SET storage_id=NULL')

    def codes(self, db):
        """Renumber the label codes (`storage.short_id`, S-0001 and on) so the frame's storages carry the frame's codes; the others follow in their order."""
        rows = [r['id'] for r in db.execute('SELECT id FROM storage ORDER BY short_id')]
        first = ['storage-' + dataset.slug(name) for name in CODES]
        order = first + [i for i in rows if i not in first]
        for n, identifier in enumerate(order, 1):   # two steps: the code is unique
            db.execute('UPDATE storage SET short_id=? WHERE id=?', (f'T-{n:04d}', identifier))
        db.execute("UPDATE storage SET short_id='S-'||substr(short_id,3) WHERE short_id LIKE 'T-%'")

    def checks_to_frame(self, db):
        """The check state of every set copy: the pieces found and missing of the frame, on lines the check has answered. A copy the person marked "Set is
        checked" has found everything that is not missing (core/collection.py `_copy_bars`); the others have the pieces of their answered lines."""
        flag = dataset.put(db, 'flag', 'status-set-is-checked', 'Set is checked', kind='status', shown_on_grid=0)
        copies = [dict(r) for r in db.execute('SELECT c.id,i.born_key AS number FROM copy c JOIN item i ON i.id=c.item_id ORDER BY c.item_id,c.created_at,c.id')]
        nth = {}
        for copy in copies:
            index = nth[copy['number']] = nth.get(copy['number'], -1) + 1
            db.execute('UPDATE copy_part SET checked=0, missing=0, damaged=0 WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL', (copy['id'],))
            db.execute('DELETE FROM copy_flag WHERE copy_id=? AND flag_id=?', (copy['id'], flag))
            _, found, missing = self.frame[copy['number']][index]
            sealed = db.execute('SELECT completeness FROM copy WHERE id=?', (copy['id'],)).fetchone()[0] == 'sealed'
            if sealed or not (found or missing):
                continue
            lines = [dict(r) for r in db.execute('''SELECT id,quantity FROM copy_part WHERE copy_id=? AND retired_at IS NULL AND is_spare=0 AND copy_figure_id IS NULL
                                                    ORDER BY quantity DESC,id''', (copy['id'],))]
            pulled = copy['number'] in self.pulled
            wanted, taken = (missing if pulled else found + missing), []
            for row in lines:                         # greedy, largest first: the one-piece lines finish the sum
                if row['quantity'] <= wanted:
                    taken.append(row)
                    wanted -= row['quantity']
            if wanted:
                raise ValueError(f'frames world: no lines add up to {missing if pulled else found + missing} pieces on {copy["number"]}')
            left = missing
            for row in sorted(taken, key=lambda r: r['id']):
                gap = min(row['quantity'], left)
                left -= gap
                db.execute('UPDATE copy_part SET checked=1, missing=? WHERE id=?', (gap, row['id']))
            if pulled:              # what a pull writes: the lost lines are marked, the copy is labelled, completeness follows (core/checker.py `mark_pulled`)
                db.execute("UPDATE copy SET checked_by='rebrickable', completeness_source='derived' WHERE id=?", (copy['id'],))
                db.execute("UPDATE copy SET completeness=? WHERE id=?", ('incomplete' if missing else 'complete', copy['id']))
                continue
            checked_all = found + missing == sum(r['quantity'] for r in lines)
            if checked_all:
                db.execute('INSERT OR IGNORE INTO copy_flag(copy_id, flag_id) VALUES(?, ?)', (copy['id'], flag))
            db.execute("UPDATE copy SET completeness=?, completeness_source='derived' WHERE id=?", ('complete' if checked_all and not missing else 'incomplete', copy['id']))


def layer(folder=real.FOLDER, pictures=False):
    return Layer(folder, pictures)


def unstored_layer(folder=real.FOLDER, pictures=False):
    return Layer(folder, pictures, stored=False)


def pulled_layer(folder=real.FOLDER, pictures=False):
    return Layer(folder, pictures, pulled=True)
