"""Lot Detective, the service (#200): which catalogue sets could a lot have come from? Read-only, over the scoring engine of `set_scoring.py`.

The lot's live loose parts and figures are scored (ADR 0026); this module adds what a person reads on top of the engine's evidence:

* **Ignore common parts** (on by default): lines held by more than N sets are dropped from the pile before scoring. N is the stored setting
  `candidate_sets_common_max` (default 300, at least the engine's distinctive limit); it is not an environment variable.
* **Set filters**: theme (id or name, with its sub-themes), year range and the catalogue's part count range.
* **Score**: `100 * evidence / the best candidate's evidence`, a whole number 0 to 100. It says how strongly the found parts point to a set relative
  to the best candidate; it is not a probability. The best candidate is the first set that passes the set filters (theme, year, size), so the top
  set shown is always 100; `min_score` then cuts the list.
* **Reasons**: plain sentences built from the engine's counts and the catalogue (see `reasons_of`).
* **Distinctive parts**: found and not found, the engine's distinctive lines (held by at most `DISTINCTIVE_MAX` sets).

The ranking is the engine's cached one (per catalogue build and input), so a lot that did not change costs only the filters; a changed lot is a
different input and ranks again."""
import json
import re

from . import set_scoring as engine

SETTING_KEY = 'candidate_sets_common_max'
COMMON_MAX_DEFAULT = 300
COMMON_MAX_LOWEST = engine.DISTINCTIVE_MAX      # lower would drop lines the engine calls distinctive
STICKER = 'sticker'
PARTS_SHOWN = 20                                # distinctive parts listed per set and side; the counts say how many there are
MAX_LIMIT = 100
_PRINT = re.compile(r'pr\d', re.I)


def common_max(db):
    """N, the most sets a line may be held by and still count: the stored setting, else 300 (an invalid stored value is the default)."""
    row = db.execute('SELECT value FROM main.setting WHERE key=?', (SETTING_KEY,)).fetchone()
    try:
        value = int(row[0]) if row and row[0] is not None else COMMON_MAX_DEFAULT
    except ValueError:
        return COMMON_MAX_DEFAULT
    return value if value >= COMMON_MAX_LOWEST else COMMON_MAX_DEFAULT


def valid_common_max(value):
    """The setting's value as a whole number of at least `COMMON_MAX_LOWEST`, else `ValueError`."""
    if type(value) is not int or value < COMMON_MAX_LOWEST:
        raise ValueError(f'{SETTING_KEY} is a whole number of {COMMON_MAX_LOWEST} or more')
    return value


def theme_ids(db, theme):
    """The ids of a theme and the themes below it: `theme` is a catalogue theme id (digits) or a name (case-insensitive). `ValueError` when unknown."""
    text = str(theme).strip()
    if text.isdigit():
        roots = [r[0] for r in db.execute('SELECT id FROM catalogue.theme WHERE id=?', (int(text),))]
    else:
        roots = [r[0] for r in db.execute('SELECT id FROM catalogue.theme WHERE lower(name)=lower(?)', (text,))]
    if not roots:
        raise ValueError('No such theme')
    return {r[0] for r in db.execute(
        '''WITH RECURSIVE t(id) AS (SELECT value FROM json_each(?) UNION SELECT c.id FROM catalogue.theme c JOIN t ON c.parent_id=t.id)
           SELECT id FROM t''', (json.dumps(roots),))}


def _facts(db, items):
    return {r[0]: (r[1], r[2], r[3]) for r in db.execute(
        'SELECT id,year,num_parts,theme_id FROM catalogue.item WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(sorted(items)),))}


def printed(db, items):
    """The part items among `items` that are printed: the part number has a print suffix (`pr` and digits, as in 3626bpr0001 or 973pr1234c01) or the
    catalogue lists the part as the printed child of another part (relationship type P). Derived from what the catalogue holds."""
    found = set()
    for item, number in db.execute('SELECT id,born_key FROM catalogue.item WHERE id IN (SELECT value FROM json_each(?))', (json.dumps(sorted(items)),)):
        if _PRINT.search(number or ''):
            found.add(item)
    found.update(r[0] for r in db.execute(
        "SELECT child_item_id FROM catalogue.part_relationship WHERE rel_type='P' AND child_item_id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(items)),)))
    return found


def plural(count, one, many):
    return f'{count} {one if count == 1 else many}'


def reasons_of(found, total, only_printed, only_other, covered_lines, set_lines):
    """The sentences that say why a set is a candidate. `found` of `total` distinctive parts; `only_printed` and `only_other` the found parts that
    exactly one set holds (printed or not); then how much of the set's part lines the lot holds."""
    reasons = []
    if total:
        reasons.append(f'{found} of {total} distinctive parts found')
    if found == 0:
        reasons.append('Matched on common parts only')
    if only_printed:
        reasons.append(f'{plural(only_printed, "printed part", "printed parts")} only in this set')
    if only_other:
        reasons.append(f'{plural(only_other, "part", "parts") if not only_printed else plural(only_other, "other part", "other parts")} only in this set')
    reasons.append(f'{covered_lines} of {set_lines} part lines of the set are in the lot')
    return reasons


def sticker_flags(flags):
    """The engine's flags from the lot's stock flag names: a flag named Sticker (any case) is passed on as `sticker`, the others are not used."""
    return {k: {STICKER} for k, names in flags.items() if any(n.casefold() == STICKER for n in names)}


def candidates(db, lot_id, *, min_score=0.0, theme=None, year_from=None, year_to=None, parts_min=None, parts_max=None,
               ignore_common=True, limit=20, offset=0):
    """The ranked candidate sets of a lot, `dict(catalogue, input, total, limit, offset, results)`; `ValueError` for no such lot or theme.

    Each result: `rank`, `set_item_id`, `score`, `evidence`, `coverage`, `reasons`, `covered_lines`, `set_lines`, `distinctive_found`,
    `distinctive_total`, `distinctive_found_parts` and `distinctive_missing_parts` (up to `PARTS_SHOWN` each, heaviest first; each line is
    `item_id, color_id, quantity, need, weight, only_in_set, printed`) and `flags`."""
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise ValueError(f'limit is 1 to {MAX_LIMIT}, offset from 0')
    parts, flags = engine.from_lot(db, lot_id)
    index, _ = engine.index_for(db)
    n = common_max(db)
    given = engine.clean(parts)
    lines, ignored = {}, 0
    for k, quantity in given.items():
        held = index.posting.get(k)
        if ignore_common and held is not None and len(held[0]) > n:
            ignored += 1
            continue
        lines[k] = quantity
    marks = engine.marks_of(lines, sticker_flags(flags))
    index, held, _, _ = engine.ranking(db, lines)
    ranked, matched = held
    rows = [r for r in ranked if r[1] > 0]
    if theme not in (None, '') or year_from is not None or year_to is not None or parts_min is not None or parts_max is not None:
        wanted = theme_ids(db, theme) if theme not in (None, '') else None
        facts = _facts(db, {index.set_item[r[0]] for r in rows})
        kept = []
        for r in rows:
            year, size, theme_id = facts.get(index.set_item[r[0]], (None, None, None))
            if wanted is not None and theme_id not in wanted:
                continue
            if (year_from is not None and (year is None or year < year_from)) or (year_to is not None and (year is None or year > year_to)):
                continue
            if (parts_min is not None and (size is None or size < parts_min)) or (parts_max is not None and (size is None or size > parts_max)):
                continue
            kept.append(r)
        rows = kept
    top = rows[0][1] if rows else 0.0
    scored = [(round(100 * r[1] / top) if top else 0, r) for r in rows]
    scored = [s for s in scored if s[0] >= min_score]
    page = scored[offset:offset + limit]
    listed = []
    for score, row in page:
        found, missing = distinctive_of(index, row[0], lines)
        listed.append((score, row, found, missing))
    single = {engine.unkey(f['key'])[0] for _, _, found, missing in listed for f in found + missing if f['only_in_set']}
    prints = printed(db, single) if single else set()
    out = []
    for i, (score, row, found, missing) in enumerate(listed):
        for f in found + missing:
            f['printed'] = f['only_in_set'] and engine.unkey(f['key'])[0] in prints
        only = [f for f in found if f['only_in_set']]
        n_printed = sum(1 for f in only if f['printed'])
        detail = engine._detail(index, row, lines, marks, 0, {})
        shown = {k: v for k, v in detail.items() if k not in ('matched', 'swaps')}
        shown.update(rank=offset + i + 1, score=score,
                     reasons=reasons_of(len(found), len(found) + len(missing), n_printed, len(only) - n_printed, detail['covered_lines'],
                                        detail['set_lines']),
                     distinctive_found_parts=[_public(f) for f in found[:PARTS_SHOWN]],
                     distinctive_missing_parts=[_public(f) for f in missing[:PARTS_SHOWN]])
        out.append(shown)
    return dict(catalogue=index.describe(), common_max=n if ignore_common else None,
                input=dict(lines=len(lines), quantity=sum(lines.values()), ignored_common_lines=ignored,
                           unmatched_lines=sum(1 for k in lines if k not in index.posting)),
                total=len(scored), limit=limit, offset=offset, results=out)


def distinctive_of(index, position, lines):
    """`(found, missing)`: the distinctive lines of a set (held by at most `DISTINCTIVE_MAX` sets) the lot has and has not, each
    `dict(key, have, need, weight, only_in_set)`, heaviest first. A common-part drop never touches a distinctive line (N is at least the limit)."""
    found, missing = [], []
    for k, need in zip(index.set_keys[position], index.set_needs[position]):
        df = len(index.posting[k][0])
        if df > engine.DISTINCTIVE_MAX:
            continue
        have = lines.get(k, 0)
        (found if have else missing).append(dict(key=k, have=have, need=need, weight=index.weight[k], only_in_set=df == 1))
    for side in (found, missing):
        side.sort(key=lambda f: (-f['weight'] * (min(f['have'], f['need']) / f['need'] if f['have'] else 1), f['key']))
    return found, missing


def _public(f):
    item, colour = engine.unkey(f['key'])
    return dict(item_id=item, color_id=colour, quantity=f['have'], need=f['need'], weight=round(f['weight'], 4),
                only_in_set=f['only_in_set'], printed=f.get('printed', False))
