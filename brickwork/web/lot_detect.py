"""The lot page's Set detection section (#200) and the sticker chooser (#201): what the page shows, from `core/candidate_sets.py` and `core/stickers.py`.

Everything is computed on the server, no JavaScript is needed: the filters are a GET form (their state is the URL's query), the candidate details are
`<details>`, and the chooser is a page of its own that docks beside the lot on a wide screen and rises as a sheet on a phone (CSS only)."""
import json
from urllib.parse import urlencode

from ..core import candidate_sets, collection, set_scoring, stickers

DEFAULT_MIN_SCORE = 30          # the page hides the faintest candidates; the API's default is 0
SHOW = 10
SHOW_MAX = 100
NO_THEME = 'No such theme'
FILTER_KEYS = ('min_score', 'theme', 'year_from', 'year_to', 'parts_min', 'parts_max')


def _whole(args, name, notes, high=10 ** 9):
    value = (args.get(name) or '').strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        notes.append(f'{name.replace("_", " ")} is a whole number')
        return None
    if not 0 <= number <= high:
        notes.append(f'{name.replace("_", " ")} is 0 to {high}')
        return None
    return number


def read_filters(args):
    """`(filters, notes)` from the page's query: the values as shown in the form and the sentences for what could not be read (the value is then left out)."""
    notes = []
    raw = (args.get('min_score') or '').strip()
    try:
        min_score = float(raw) if raw else DEFAULT_MIN_SCORE
        if not 0 <= min_score <= 100:
            raise ValueError
    except ValueError:
        notes.append('min score is a number from 0 to 100')
        min_score = DEFAULT_MIN_SCORE
    year_from, year_to = _whole(args, 'year_from', notes), _whole(args, 'year_to', notes)
    parts_min, parts_max = _whole(args, 'parts_min', notes), _whole(args, 'parts_max', notes)
    if year_from is not None and year_to is not None and year_from > year_to:
        notes.append('years: the first value is above the second')
        year_from = year_to = None
    if parts_min is not None and parts_max is not None and parts_min > parts_max:
        notes.append('size: the first value is above the second')
        parts_min = parts_max = None
    if 'ignore_common' in args:
        ignore = args.get('ignore_common') not in ('', '0', 'false', 'off')
    else:
        ignore = args.get('detect') != '1'                 # a submitted form without the box means the switch was turned off
    try:
        show = max(SHOW, min(SHOW_MAX, int(args.get('show') or SHOW)))
    except ValueError:
        show = SHOW
    return dict(min_score=int(min_score) if min_score == int(min_score) else min_score, theme=(args.get('theme') or '').strip(), year_from=year_from,
                year_to=year_to, parts_min=parts_min, parts_max=parts_max, ignore_common=ignore, show=show), notes


def active_count(filters):
    """How many filters differ from what the page starts with (the phone's `Filters · n`)."""
    return sum([filters['min_score'] != DEFAULT_MIN_SCORE, bool(filters['theme']), filters['year_from'] is not None or filters['year_to'] is not None,
                filters['parts_min'] is not None or filters['parts_max'] is not None])


def query_of(filters, **more):
    """The page's query string for a set of filters (what a link keeps), with `more` replacing members."""
    values = {**filters, **more}
    pairs = [('detect', '1')]
    if values['min_score'] != DEFAULT_MIN_SCORE:
        pairs.append(('min_score', values['min_score']))
    for key in ('theme', 'year_from', 'year_to', 'parts_min', 'parts_max'):
        if values[key] not in (None, ''):
            pairs.append((key, values[key]))
    pairs.append(('ignore_common', '1' if values['ignore_common'] else '0'))
    if values['show'] != SHOW:
        pairs.append(('show', values['show']))
    return urlencode(pairs)


def _plural(count, one, many):
    return f'{count} {one if count == 1 else many}'


def counts_line(result, ignore_common):
    total, dropped = result['total'], result['input']['ignored_common_lines']
    text = _plural(total, 'candidate set', 'candidate sets')
    if ignore_common and dropped:
        text += f" · {dropped} of the lot's parts {'was' if dropped == 1 else 'were'} too common to count"
    return text


def themes(db):
    return [r[0] for r in db.execute('SELECT DISTINCT name FROM catalogue.theme WHERE retired_at IS NULL ORDER BY name')]


def _swap_text(swap, label):
    have, wanted = swap['have'], swap['wanted']
    held, needed = label(have), label(wanted)
    if swap['kind'] == 'colour':
        return f"Lot has {held['colour']} where the set has {needed['colour']} ({needed['name']} · {needed['number']})"
    return f"Lot has {held['number']} where the set has {needed['number']} ({needed['name']}, {needed['colour']})"


def section(db, lot_id, args):
    """The Set detection section of a lot as a dict for the template: `state` is `ok`, `no_parts`, `no_catalogue`, `no_candidates` or `error`."""
    filters, notes = read_filters(args)
    found = dict(filters=filters, notes=notes, active=active_count(filters), themes=[], rows=[], counts='', state='ok', clear=query_of(
        dict(filters, min_score=DEFAULT_MIN_SCORE, theme='', year_from=None, year_to=None, parts_min=None, parts_max=None)))
    if not collection.has_catalogue(db):
        return dict(found, state='no_catalogue')
    try:
        parts, _ = set_scoring.from_lot(db, lot_id)
    except ValueError:
        return dict(found, state='no_parts')
    if not parts:
        return dict(found, state='no_parts')
    found['themes'] = themes(db)
    try:
        result = candidate_sets.candidates(db, lot_id, min_score=filters['min_score'], theme=filters['theme'] or None, year_from=filters['year_from'],
                                           year_to=filters['year_to'], parts_min=filters['parts_min'], parts_max=filters['parts_max'],
                                           ignore_common=filters['ignore_common'], limit=min(filters['show'], candidate_sets.MAX_LIMIT))
    except ValueError as error:
        return dict(found, state='error', notes=notes + [str(error)])
    found['counts'] = counts_line(result, filters['ignore_common'])
    found['total'] = result['total']
    if not result['results']:
        return dict(found, state='no_candidates')
    sets = [r['set_item_id'] for r in result['results']]
    lines = [(p['item_id'], p['color_id']) for r in result['results'] for p in r['distinctive_found_parts'] + r['distinctive_missing_parts']]
    swaps = [(s[k]['item_id'], s[k]['color_id']) for r in result['results'] for s in r['swaps']['items'] for k in ('have', 'wanted')]
    from ..api2.ranking import pictures_of
    rows = collection.decorate(db, [dict(item_id=i, color_id=c) for i, c in {*[(s, None) for s in sets], *lines, *swaps}])
    book = {(r['item_id'], r.get('color_id')): r for r in rows}
    shots = pictures_of(db, {(i, c) for i, c in lines} | {(s, None) for s in sets})
    facts = {r[0]: r for r in db.execute(
        'SELECT i.id,i.year,i.num_parts,t.name FROM catalogue.item i LEFT JOIN catalogue.theme t ON t.id=i.theme_id WHERE i.id IN (SELECT value FROM json_each(?))',
        (json.dumps(sorted(sets)),))}

    def label(body):
        row = book.get((body['item_id'], body.get('color_id')), {})
        return dict(name=row.get('name') or row.get('item_no') or '', number=row.get('number_text') or row.get('item_no') or '',
                    colour=row.get('color_name') or '', rgb=row.get('rgb'), ink=row.get('ink'))

    def part(body):
        shot = shots.get((body['item_id'], body['color_id'])) or {}
        return dict(label(body), quantity=body['quantity'], need=body['need'], image=shot.get('id'), printed=body['printed'], only=body['only_in_set'])

    shown = []
    for r in result['results']:
        fact = facts.get(r['set_item_id'])
        identity = book.get((r['set_item_id'], None), {})
        shown.append(dict(
            id=r['set_item_id'], rank=r['rank'], score=r['score'], number=identity.get('number_text') or identity.get('item_no') or '',
            name=identity.get('name') or '', theme=(fact[3] if fact else '') or '', year=fact[1] if fact else None, size=fact[2] if fact else None,
            image=(shots.get((r['set_item_id'], None)) or {}).get('id'), reasons=r['reasons'], reasons_line=' · '.join(r['reasons']),
            found=[part(p) for p in r['distinctive_found_parts']], missing=[part(p) for p in r['distinctive_missing_parts']],
            found_count=r['distinctive_found'], missing_count=r['distinctive_total'] - r['distinctive_found'],
            swaps=[_swap_text(s, label) for s in r['swaps']['items']], swap_count=r['swaps']['lines']))
    found.update(rows=shown, more=result['total'] > len(shown), next_show=min(SHOW_MAX, filters['show'] + SHOW))
    return found


def lot_stickers(db, rows):
    """Flag the part lines of a lot that carry a sticker: sets `sticker` on each row to `None` (no flag) or `dict(set_number, ...)` (chosen) or `{}` (not chosen)."""
    states = stickers.states(db, [r['id'] for r in rows if r.get('kind') == 'part'])
    for row in rows:
        state = states.get(row['id'])
        row['sticker'] = None if not state or not state['flagged'] else (state['confirmed'] or {})
    return sum(1 for r in rows if r['sticker'] is not None)


def chooser(db, lot_id, stock_id, args):
    """The chooser page's data: the part line, the state, the candidates (three, or all with `all=1`, paged by `offset`)."""
    show_all = args.get('all') == '1'
    first = stickers.candidates(db, lot_id, stock_id, limit=stickers.MAX_LIMIT if show_all else 3)
    state = stickers.states(db, [stock_id])[stock_id]
    items = first['results']
    from ..api2.ranking import pictures_of
    shots = pictures_of(db, {(r['sheet_item_id'], None) for r in items})
    for r in items:
        r['image'] = (shots.get((r['sheet_item_id'], None)) or {}).get('id')
    return dict(line=first['stock'], total=first['total'], results=items, rest=first['total'] - len(items), all=show_all, state=state)
