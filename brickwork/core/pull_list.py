"""Pull a detected set out of a lot (#202): the pull list of a candidate set for one lot, the found counts kept between visits, and Make it a copy (ADR 0029).

**The list.** Its lines are the set's own parts (the latest Rebrickable list, sub-sets expanded, spares left out as in ADR 0011) and its whole minifigures, as
Build Scout reads them (`build_scout.scout_for`), so the pieces on the page are the pieces `make_copy_in` can move. Per line: `need` (what the set has),
`held` (what the lot can give: `workbench.available`, damaged rows give nothing), `ticked` (found in the bulk and not filed yet) and `found = min(need, held) +
ticked`, so *inventory minus the lot* is `need - held` and *to find* is `need - found`.

**Progress** is the found counts that are not in the lot yet, one `setting` row `pull:<lot id>:<set item id>` holding `{"found": {"<item>:<colour or 0>": n}}`.
Saving it is not an event (a tick is a note, not a change of the collection); only Make it a copy is. The reader clamps every count to what the line still
lacks, so a lot that gained the part meanwhile never counts it twice. No table, so no schema step (ADR 0029).

**Make it a copy** files the found counts in the lot as stock (`stock.add_loose` without its own audit event, "found in the bulk", used), then `build_scout.plan_takes` over the lot's rows
gives `min(have, need)` per line and `found_copy.make_copy_in` moves exactly those into a new copy: one transaction, one event (`copy` / `make_from_stock`),
the rest of the set recorded as missing on the copy, the lot keeps the leftovers. The progress row is deleted in the same transaction. Undo is Build Scout's
(`found_copy.undo_make_copy_in`): the stock rows go back as the event left them and the copy is archived. The pieces ticked in the bulk were filed in the lot, so after
an Undo the lot holds them and they count as found (`held`); the ticks are not restored, which would count them twice."""
import json

from ..store4 import found_copy
from ..store4.audit import OPERATION_KEY
from . import build_scout, collection, errors, set_scoring, stock
from .admin import origin
from .transaction import transaction

SETTING = 'pull:{}:{}'
SHOWS = ('find', 'found', 'all')
NOTE = 'Made from the pull list of a lot'
BULK_NOTE = 'Found in the bulk (pull list)'
FIGURES = 'Minifigures'
MAX_FOUND = 100000


def key_text(item_id, color_id):
    return f'{int(item_id)}:{int(color_id or 0)}'


def _setting(lot_id, set_item_id):
    return SETTING.format(lot_id, int(set_item_id))


def _lot(db, lot_id):
    row = db.execute('SELECT id, name FROM main.lot WHERE id=? AND archived_at IS NULL', (lot_id,)).fetchone()
    if row is None:
        raise errors.NotFound('No such lot')
    return dict(row)


def _set(db, set_item_id):
    if not collection.has_catalogue(db):
        raise ValueError('The catalogue is not loaded yet')
    row = db.execute("SELECT id, name FROM catalogue.item WHERE id=? AND kind='set' AND retired_at IS NULL", (int(set_item_id),)).fetchone()
    if row is None:
        raise errors.NotFound('No such set')
    return dict(row)


def stored(db, lot_id, set_item_id):
    """The saved found counts as `{"item:colour": n}` (empty when none, or unreadable)."""
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (_setting(lot_id, set_item_id),)).fetchone()
    try:
        found = json.loads(row[0])['found'] if row and row[0] else {}
    except (ValueError, KeyError, TypeError):
        return {}
    return {k: v for k, v in found.items() if isinstance(v, int) and not isinstance(v, bool) and v > 0} if isinstance(found, dict) else {}


def _categories(db, item_ids):
    """`{item id: (category id, name)}` for catalogue parts."""
    found = {}
    ids = sorted(set(item_ids))
    for start in range(0, len(ids), 500):
        chunk = json.dumps(ids[start:start + 500])
        for r in db.execute('''SELECT i.id, c.id AS category_id, c.name FROM catalogue.item i JOIN catalogue.part_category c ON c.id=i.category_id
                               WHERE i.id IN (SELECT value FROM json_each(?))''', (chunk,)):
            found[r['id']] = (r['category_id'], r['name'])
    return found


def lot_pieces(db, lot_id):
    """Every piece the lot holds, whatever its condition (parts and whole figures)."""
    return db.execute("SELECT coalesce(sum(quantity), 0) FROM main.stock WHERE lot_id=? AND archived_at IS NULL AND kind IN ('part','minifigure')",
                      (lot_id,)).fetchone()[0]


def state(db, lot_id, set_item_id):
    """The pull list as data: `dict(lot, set, lines, totals, lot_pieces, nested, refusal)`.

    `lines` are `dict(key, item_id, color_id, kind, need, held, ticked, found, category_id, category)` (a whole figure has `kind` figure and no colour; the
    caller orders them, the names live in the item tables). `totals` count pieces: `need`, `held`, `found`, `to_find`,
    `lines`, `lines_to_find`, `figures_need`, `figures_found`. `refusal` is the sentence Make it a copy would be refused with, or None.
    Raises `errors.NotFound` (no such lot or set) and `ValueError` (no catalogue, or a set with no part list)."""
    lot = _lot(db, lot_id)
    chosen = _set(db, set_item_id)
    scout = build_scout.scout_for(db)
    position = scout.parts.position.get(chosen['id'])
    if position is None:
        raise ValueError('This set has no part list to pull from')
    pile = build_scout.pile_of(build_scout.stock_rows(db, lots=[lot_id]))
    ticks = stored(db, lot_id, chosen['id'])
    entries = [(key, need, False) for key, need in zip(scout.parts.set_keys[position], scout.parts.set_needs[position])]
    fig = scout.figures.position.get(chosen['id'])
    if fig is not None:
        entries += [(key, need, True) for key, need in zip(scout.figures.set_keys[fig], scout.figures.set_needs[fig])]
    categories = _categories(db, [set_scoring.unkey(k)[0] for k, _, _ in entries])
    lines = []
    for key, need, whole in entries:
        item_id, color_id = set_scoring.unkey(key)
        held = min(pile.get(key, 0), need)
        ticked = min(ticks.get(key_text(item_id, color_id), 0), need - held)
        category = (None, FIGURES) if whole else categories.get(item_id) or (None, 'Other')
        lines.append(dict(key=key_text(item_id, color_id), item_id=item_id, color_id=color_id, kind='figure' if whole else 'part', need=need,
                          held=held, ticked=ticked, found=held + ticked, category_id=category[0], category=category[1]))
    figures = [line for line in lines if line['kind'] == 'figure']
    totals = dict(need=sum(line['need'] for line in lines), held=sum(line['held'] for line in lines), found=sum(line['found'] for line in lines),
                  lines=len(lines), lines_to_find=sum(1 for line in lines if line['found'] < line['need']),
                  figures_need=sum(line['need'] for line in figures), figures_found=sum(line['found'] for line in figures))
    totals['to_find'] = totals['need'] - totals['found']
    refusal = None
    if chosen['id'] in scout.nested:
        refusal = 'This set is made of other sets · Make it a copy does not handle those yet'
    elif not totals['found']:
        refusal = 'Nothing found yet · tick the parts you find first'
    ticked_total = sum(line['ticked'] for line in lines)
    return dict(lot=lot, set=chosen, lines=lines, totals=totals, nested=chosen['id'] in scout.nested, refusal=refusal,
                lot_pieces=lot_pieces(db, lot_id), ticked_total=ticked_total)


def moves(info):
    """The three numbers of the confirm: `dict(moves, missing, stays)` of a state: found pieces leaving the lot, the rest recorded as missing, what stays."""
    found = info['totals']['found']
    return dict(moves=found, missing=info['totals']['need'] - found, stays=info['lot_pieces'] + info['ticked_total'] - found)


def set_found(db, lot_id, set_item_id, item_id, color_id, found):
    """Save the found count of one line (an absolute count, `held` included): `0` to `need`; a count below `held` leaves the pieces the lot already
    has as they are. Idempotent, writes no event. Returns the line as `state` shows it. `ValueError`: the line is not on the list or the count is out of range."""
    if isinstance(found, bool) or not isinstance(found, int) or not 0 <= found <= MAX_FOUND:
        raise ValueError(f'found is a whole number from 0 to {MAX_FOUND}')
    with transaction(db):
        info = state(db, lot_id, set_item_id)
        key = key_text(item_id, color_id)
        line = next((ln for ln in info['lines'] if ln['key'] == key), None)
        if line is None:
            raise ValueError('This part is not on the pull list of this set')
        if found > line['need']:
            raise ValueError(f"found is 0 to {line['need']} for this part")
        counts = stored(db, lot_id, set_item_id)
        tick = max(0, found - line['held'])
        if tick:
            counts[key] = tick
        else:
            counts.pop(key, None)
        name = _setting(lot_id, set_item_id)
        if counts:
            db.execute('INSERT OR REPLACE INTO main.setting(key,value) VALUES(?,?)', (name, json.dumps({'found': counts}, sort_keys=True)))
        else:
            db.execute('DELETE FROM main.setting WHERE key=?', (name,))
        line['ticked'], line['found'] = tick, line['held'] + tick
    return line


def make_copy(db, lot_id, set_item_id):
    """Make it a copy: the found pieces of the pull list move out of the lot into a new copy of the set, one transaction, one undoable event. Returns
    `dict(event_id, copy_id, pieces, figures, missing_parts, missing_figures, completeness, stays)`. Refused (`ValueError`, nothing written): a set made of
    other sets, nothing found yet, no part list; `errors.NotFound` for a lot or set that is not there."""
    via, actor = origin()
    with transaction(db):
        info = state(db, lot_id, set_item_id)
        if info['refusal']:
            raise ValueError(info['refusal'])
        for line in info['lines']:
            if line['ticked']:
                stock.add_loose(db, item_id=line['item_id'], color_id=line['color_id'], quantity=line['ticked'], condition='used', lot_id=lot_id,
                                note=BULK_NOTE, record=False)
        rows = build_scout.stock_rows(db, lots=[lot_id])
        takes, _ = build_scout.plan_takes(db, info['set']['id'], rows)
        if not takes:
            raise ValueError('Nothing found yet · tick the parts you find first')
        made = found_copy.make_copy_in(db, info['set']['id'], takes, via=via, actor=actor, operation_key=OPERATION_KEY.get(), note=NOTE)
        db.execute('DELETE FROM main.setting WHERE key=?', (_setting(lot_id, set_item_id),))
        made['stays'] = lot_pieces(db, lot_id)
    return made
