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
from .showcase import uid

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
# Frame 06 (the Set Inspector): copy 2 of 7213-1 is in a running check: 131 part lines, 54 found, 4 missing (12 pieces), 73 to check; 142 of its 375 pieces
# checked, the line to answer next is the 59th. The frame names its parts by hand, so the data follows the frame.
INSPECTOR = {'set': '7213-1', 'copy': uid('copy', '7213-1', 'b'), 'place': 'Flohmarkt Mauerpark', 'saved': '2026-10-12T14:20:00.000Z',
             'lines': 131, 'found': 54, 'missing_pieces': 12, 'checked_pieces': 142}
BLUISH = {'id': 72, 'name': 'Dark Bluish Gray', 'rgb': '#6C6E68', 'transparent': False}
RED = {'id': 4, 'name': 'Red', 'rgb': '#C91A09', 'transparent': False}
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
        self.inspector_lines()

    def inspector_lines(self):
        """Frame 06's copy: Rebrickable lists 144 required lines for 7213-1, the frame says 131 of the same 375 pieces and names its parts by hand. So the
        part list of this layer is rebuilt: the five parts the frame shows (3005, 3004, 3010 found, 3008 missing, 3633 the line to answer), three more
        missing lines, 51 found and 72 lines still to check, their quantities nudged so the sums are the frame's (142 pieces checked of 375, 12 missing).
        No figures: the frame counts part lines only. `walk` is the order the staged check answered them in (newest last), `current` the 59th line."""
        inventory = self.inventories[INSPECTOR['set']]
        spares = [r for r in inventory['parts'] if r['spare']]
        lines = sorted((r for r in inventory['parts'] if not r['spare']), key=lambda r: (r['part'], r['color']['id']))
        shown = {'3004', '3005', '3008', '3010', '3633'}
        big = [next(r for r in lines if r['quantity'] == q and r['part'] not in shown) for q in (12, 11, 10)]
        pool = [r for r in lines if r['part'] not in shown and not any(r is b for b in big)]
        base = pool[0]

        def made(part, name, colour, quantity, category='Bricks'):
            return dict(base, part=part, name=name, category=category, color=colour, quantity=quantity, element=None, print=False)
        found, todo = pool[:51], pool[51:123]

        def fit(rows, target):   # nudge quantities (never below 1) until they add up to `target`
            diff, i = target - sum(r['quantity'] for r in rows), 0
            while diff:
                row = rows[i % len(rows)]
                step = 1 if diff > 0 else -1
                if row['quantity'] + step >= 1:
                    row['quantity'] += step
                    diff -= step
                i += 1
        found, todo = [dict(r) for r in found], [dict(r) for r in todo]
        shown_found = [made('3010', 'Brick 1 × 4', BLUISH, 4), made('3004', 'Brick 1 × 2', RED, 8), made('3005', 'Brick 1 × 1', RED, 6)]
        gaps = [(made('3008', 'Brick 1 × 8', RED, 2), 1)] + [(dict(r), m) for r, m in zip(big, (4, 4, 3))]
        assert sum(m for _, m in gaps) == INSPECTOR['missing_pieces']
        fit(found, INSPECTOR['checked_pieces'] - sum(r['quantity'] for r, _ in gaps) - sum(r['quantity'] for r in shown_found))
        fit(todo, 375 - INSPECTOR['checked_pieces'] - 2)
        current = made('3633', 'Fence Lattice 1 × 4 × 1', BLUISH, 2, 'Fences')
        walk = [(r, 0) for r in found[:10]] + [gaps[1]] + [(r, 0) for r in found[10:25]] + [gaps[2]] + [(r, 0) for r in found[25:40]] + [gaps[3]] \
            + [(r, 0) for r in found[40:]] + [gaps[0]] + [(r, 0) for r in shown_found]   # the frame's "Checked so far" is the last four answers: 3005, 3004, 3010 found, 3008 missing
        for r in [row for row, _ in walk] + [current] + todo:
            r.update(checked=0, missing=0, damaged=0)
        inventory['parts'] = [row for row, _ in walk] + [current] + todo + spares
        self.walk = [(r['part'], r['color']['id'], m) for r, m in walk]
        self.current = (current['part'], current['color']['id'])
        self.rest = [(r['part'], r['color']['id']) for r in todo]
        removed = [f['figure'] for f in inventory['minifigures']]
        inventory['minifigures'], inventory['minifigure_parts'] = [], {}
        self.figures = [f for f in self.figures if f not in removed]
        for entry in self.sets:
            if entry['id'] == INSPECTOR['copy']:
                entry['purchase_location'] = INSPECTOR['place']

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


def stage_inspector(store):
    """Frame 06: the running check of copy 2 of 7213-1, answered through the app's own checker calls (as checks.stage does), then put on the frame's 59th line.
    The answers are made in `walk` order; the session's order is then the walk, the line to answer and the rest, with the cursor on the 59th, and the saves
    are made at 14:20 ("Saved 14:20"), the clock set to that for the staging."""
    import datetime as dt
    import json
    from ..core import checker
    from ..core.admin import database
    from . import checks, clock
    layer = Layer(pictures=False)
    copy_id = INSPECTOR['copy']
    was, clock.FIXED_NOW = clock.FIXED_NOW, dt.datetime.fromisoformat(INSPECTOR['saved'].replace('Z', '+00:00'))   # events cannot be edited: the saves are made at 14:20
    patched = clock.freeze_clock()
    try:
        with database(store) as db:
            with transaction(db):
                db.execute('UPDATE copy_part SET checked=0, missing=0, damaged=0 WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL', (copy_id,))
                db.execute('DELETE FROM copy_flag WHERE copy_id=? AND flag_id IN (SELECT id FROM flag WHERE name=?)', (copy_id, checker.CHECKED_FLAG))
            with transaction(db):   # the frame draws a multiplication sign; the catalogue import wrote an x
                for row in layer.inventories[INSPECTOR['set']]['parts']:
                    if row['part'] in ('3005', '3004', '3010', '3008', '3633'):
                        db.execute("UPDATE item SET name=? WHERE born_provider='rebrickable' AND born_key=?", (row['name'], row['part']))
            checks.call(db, copy_id, action='start', order='inventory')
            token = {}
            for r in checker.rows(db, copy_id, images=False, decorate=False):
                if r['kind'] == 'part':
                    key = db.execute('SELECT i.born_key, c.born_key FROM copy_part p JOIN item i ON i.id=p.item_id LEFT JOIN color c ON c.id=p.color_id WHERE p.id=? AND p.retired_at IS NULL', (r['id'],)).fetchone()
                    token[(key[0], str(key[1]))] = r
            session = checker.session(db, copy_id)
            for part, colour_id, missing in layer.walk:
                r = token[(part, str(colour_id))]
                checks.call(db, copy_id, action='answer', session=session['id'], token=r['token'], found=r['quantity'] - missing)
            order = [token[(p, str(c))]['token'] for p, c, _ in layer.walk] + [token[(layer.current[0], str(layer.current[1]))]['token']] \
                + [token[(p, str(c))]['token'] for p, c in layer.rest]
            with transaction(db):
                row = db.execute('SELECT session_json FROM part_check WHERE copy_id=? AND figure_key=0', (copy_id,)).fetchone()
                body = json.loads(row['session_json'])
                body['order'], body['cursor'] = order, len(layer.walk)
                db.execute('UPDATE part_check SET session_json=? WHERE copy_id=? AND figure_key=0', (json.dumps(body, separators=(',', ':')), copy_id))
    finally:
        clock.FIXED_NOW = was
        clock.thaw_clock(patched)
