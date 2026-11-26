"""The screen gate's `frames` worlds (#492, #494, #489): the data of the approved B′ frames, so the built page and the frame are compared on the same numbers.

The frames of design/screens-b show a collection the design project drew by hand. This layer is the real-sets world (`real`) with the numbers of the
Sets frames (04, 05) put in exactly: seven sets, eight copies, the label codes and names of four storages, the prices, and the bar of each copy (found
and missing pieces, to scale). It has no pictures (the frames show empty tiles with their alt text, because the public repo carries no catalogue
pictures) and no staged checks. Only the worlds `frames` and `frames-no-storage` (scripts/screen_gate.py) see any of it; the world `frames-no-storage`
is the same collection with no storage set on any copy (frame 05), and `frames-pulled` the same collection as frame 48 draws it: two copies were pulled from
Rebrickable (8043-1 with no Lost Parts, 21028-1 with 9 missing parts), so they carry `checked_by='rebrickable'` and no "Set is checked" flag.

Where a frame disagrees with the data it was drawn from, the data follows the frame: Rebrickable's non-spare lines of 31120-1 add up to 1,408 pieces,
the frame says 1,426, so one line of the copy holds 18 more pieces here. Everything is deterministic (the real world's seed and the demo clock)."""
from ..core import stock
from ..core.transaction import transaction
from . import clock, dataset, real
from .showcase import seeded_uuids, uid

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
# Frame 07 (the Part Runner): the four incomplete copies (7213-1 twice, 7938-1, 10210-1; 10 + 12 + 14 + 33 = 69 pieces) as one run of 52 parts (one line per
# part and colour), in storage order. The run is on its 7th part: Fence Lattice 1 × 4 × 1, 3633, Dark Bluish Gray, 3 for 10210-1 (copy 1); the frame's
# next three are Brick 1 × 4 (3010, 2 from 7213-1), Brick 1 × 6 (3009, 1) and Slope 45° 2 × 2 (87619, 4). Their drawers are the loose stock the picker orders by:
# six parts in Box 5 come first, then Drawer 2, Drawer 3 (two parts) and Drawer 4. Per copy: (missing pieces, lines with a gap, the shown parts: (part, colour id) -> missing)
# and the lines that get 2 missing (the rest 1). Copy 2 of 7213-1 keeps frame 06's four lines (3008 and three larger ones).
RUNNER = {'7213-1': (10, 9, {('3010', 72): 2}, 0), '7938-1': (14, 11, {('87619', 15): 4, ('3009', 71): 1}, 0), '10210-1': (33, 28, {('3633', 72): 3}, 3)}
RUNNER_NAMES = {'3633': 'Fence Lattice 1 × 4 × 1', '3009': 'Brick 1 × 6', '87619': 'Slope 45° 2 × 2', '3010': 'Brick 1 × 4'}
RUNNER_DRAWERS = {('3633', 72): ('Drawer 2', 'Shelf A2 – Town'), ('3010', 72): ('Drawer 3', 'Shelf A2 – Town'), ('3009', 71): ('Drawer 3', 'Shelf A2 – Town'),
                  ('87619', 15): ('Drawer 4', 'Shelf A1 – Castle')}
PRICES = {'7213-1': 48.58, '7938-1': 65.73, '10254-1': 99.53, '10210-1': 194.31, '31120-1': 127.00, '8043-1': 123.40, '21028-1': 53.94}


def runner_path():
    """The Part Runner of frame 07: the four incomplete copies, picked in storage order (then colour), the run on its 7th part."""
    copies = [real.uid('copy', '7213-1', 'a'), INSPECTOR['copy'], real.uid('copy', '7938-1', 'a'), real.uid('copy', '10210-1', 'a')]
    return '/workbench/part-picker?pick=1&ranked=1&rank=storage&rank=colour&part=7&' + '&'.join('copy=' + c for c in copies)


class Layer(real.Layer):
    element_ids = False      # the approved frames draw lines without element ids (frame 15: "no element id"); `real.Layer` turns them on

    def __init__(self, folder=real.FOLDER, pictures=False, stored=True, pulled=False, runner=False):
        super().__init__(folder, pictures)
        self.stored = stored
        self.runner = runner
        self.frame = dict(FRAME, **PULLED) if pulled else FRAME
        self.pulled = PULLED if pulled else {}
        for entry in self.sets:
            entry['storage'] = self.frame[entry['set']][0 if entry['id'] == real.uid('copy', entry['set'], 'a') else 1][0]
        line = next(r for r in self.inventories['31120-1']['parts'] if not r['spare'])
        line['quantity'] += 18                       # 1,408 pieces in Rebrickable's list, 1,426 on the frame
        self.inspector_lines()
        if runner:   # the frame wants 4 of 87619 in White from 7938-1, which lists 2: two pieces move over from its largest line, the copy's total stays
            lines = [r for r in self.inventories['7938-1']['parts'] if not r['spare']]
            big = max(lines, key=lambda r: (r['quantity'], r['part']))
            slope = next(r for r in lines if (r['part'], r['color']['id']) == ('87619', 15))
            big['quantity'] -= 2
            slope['quantity'] += 2

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
            if self.runner:
                patched = clock.freeze_clock()   # the layer's own fill has thawed the clock and the uuids: stock saved here is stamped and numbered the same in every build
                try:
                    with seeded_uuids(self.rng):
                        self.runner_gaps(db)
                finally:
                    clock.thaw_clock(patched)
            if not self.stored:
                db.execute('UPDATE copy SET storage_id=NULL')

    def runner_gaps(self, db):
        """Frame 07's run: the missing pieces of 7213-1 (copy 1), 7938-1 and 10210-1 are spread over 9, 11 and 28 lines (one line per part and colour, no two copies
        sharing one), on lines the copy's check has answered, so each copy's bar (found, missing, total) is the Sets frame's. The shown parts get the frame's counts,
        the loose stock of every part in the run is replaced by the drawers above (so the picker's storage order is the frame's), and the shown names get the
        multiplication sign. Copy 2 of 7213-1 keeps frame 06's four lines (stage_inspector)."""
        reserved = {(part, colour) for part, colour, missing in self.walk if missing}                     # frame 06's gaps stay theirs
        used, picks = set(reserved), []
        for number, (target, count, shown, twos) in RUNNER.items():
            copy_id = real.uid('copy', number, 'a')
            lines = [dict(r) for r in db.execute('''SELECT p.id,p.quantity,p.item_id,p.color_id,i.born_key AS part,c.born_key AS colour FROM copy_part p JOIN item i ON i.id=p.item_id
                     LEFT JOIN color c ON c.id=p.color_id WHERE p.copy_id=? AND p.copy_figure_id IS NULL AND p.retired_at IS NULL AND p.is_spare=0 AND p.checked=1 ORDER BY p.id''', (copy_id,))]
            for r in lines:
                r['identity'] = (r['part'], int(r['colour']))
            db.execute('UPDATE copy_part SET missing=0 WHERE copy_id=? AND copy_figure_id IS NULL AND retired_at IS NULL', (copy_id,))
            chosen = [r for r in lines if r['identity'] in shown]
            assert len(chosen) == len(shown), f'frames world: {number} has no checked line for {sorted(shown)}'
            rest = [r for r in lines if r['identity'] not in shown and r['identity'] not in used and r['quantity'] >= 2]
            chosen += rest[:count - len(chosen)]
            assert len(chosen) == count, f'frames world: {number} has too few checked lines for {count} gaps'
            assignment = {r['id']: shown.get(r['identity'], 1) for r in chosen}
            bumped = [r['id'] for r in chosen if r['identity'] not in shown][:twos]
            for identifier in bumped:
                assignment[identifier] = 2
            assert sum(assignment.values()) == target, f'frames world: {number} does not add up to {target} missing'
            for identifier, missing in assignment.items():
                db.execute('UPDATE copy_part SET missing=? WHERE id=? AND retired_at IS NULL', (missing, identifier))
            used |= {r['identity'] for r in chosen}
            picks += [r for r in chosen if r['identity'] not in shown]
        assert len(used) - len(reserved) == 48
        gaps = {(r[0], r[1]) for number in RUNNER for r in db.execute('SELECT item_id,color_id FROM copy_part WHERE copy_id=? AND missing>0 AND retired_at IS NULL', (real.uid('copy', number, 'a'),))}
        for part, colour in reserved:
            gaps |= {(r[0], r[1]) for r in db.execute('''SELECT p.item_id,p.color_id FROM copy_part p JOIN item i ON i.id=p.item_id JOIN color c ON c.id=p.color_id
                     WHERE p.copy_id=? AND p.retired_at IS NULL AND i.born_key=? AND c.born_key=?''', (INSPECTOR['copy'], part, str(colour)))}
        for item_id, colour_id in gaps:      # no other stock may sit among the run's parts
            db.execute('UPDATE stock SET archived_at=? WHERE kind=? AND item_id=? AND color_id=? AND archived_at IS NULL', (dataset.STAMP, 'part', item_id, colour_id))
        for name, parent in (('Drawer 2', 'Shelf A2 – Town'), ('Drawer 3', 'Shelf A2 – Town'), ('Drawer 4', 'Shelf A1 – Castle'), ('Box 5', None)):
            dataset.put(db, 'storage', 'storage-' + dataset.slug(name), name, type='Box' if name.startswith('Box') else 'Drawer')
            if parent:
                db.execute('UPDATE storage SET parent_id=? WHERE id=?', ('storage-' + dataset.slug(parent), 'storage-' + dataset.slug(name)))
        for part, name in RUNNER_NAMES.items():
            db.execute("UPDATE item SET name=? WHERE born_provider='rebrickable' AND born_key=?", (name, part))
        def stock_of(item_id, colour_id, drawer):
            stock.add_loose(db, item_id=item_id, color_id=colour_id, quantity=5, condition='used', storage_id='storage-' + dataset.slug(drawer), via='cli')
        for (part, colour), (drawer, _) in RUNNER_DRAWERS.items():
            row = db.execute('''SELECT p.item_id,p.color_id FROM copy_part p JOIN item i ON i.id=p.item_id JOIN color c ON c.id=p.color_id WHERE i.born_key=? AND c.born_key=?
                                AND p.missing>0 AND p.retired_at IS NULL LIMIT 1''', (part, str(colour))).fetchone()
            stock_of(row[0], row[1], drawer)
        for r in picks[:6]:
            stock_of(r['item_id'], r['color_id'], 'Box 5')

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
    return Layer(folder, pictures, runner=True)


def unstored_layer(folder=real.FOLDER, pictures=False):
    return Layer(folder, pictures, stored=False)


class EmptyLayer(Layer):
    """Frame 08's collection (#497): the catalogue the frames use and nothing owned, no copy, no stock, no wish. No keys either (the `edge` worlds are the ones that
    look keyed), so Get started reads 1 of 4 done: the catalogue is loaded."""

    def __init__(self, folder=real.FOLDER, pictures=False):
        super().__init__(folder, pictures)
        self.sets, self.inventories = [], {}

    def fill(self, db, ids):
        pass


def empty_layer(folder=real.FOLDER, pictures=False):
    return EmptyLayer(folder, pictures)


def pulled_layer(folder=real.FOLDER, pictures=False):
    return Layer(folder, pictures, pulled=True)


def matcher_layer(folder=real.FOLDER, pictures=False):
    """Frame 09's collection: the Sets frame's, without the Part Runner's drawers (frames_matcher.stage_matcher puts the loose stock the Matchmaker covers with)."""
    return Layer(folder, pictures)


def instructions_layer(folder=real.FOLDER, pictures=False):
    """Frame 03's collection: the Sets frame's (frames_instructions.stage_instructions gives three of its sets a booklet, so four have none)."""
    return Layer(folder, pictures)


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
