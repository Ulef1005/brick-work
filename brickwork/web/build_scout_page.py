"""The Build Scout screen (#9): what its page and its actions read from the request and from `core/build_scout.py`.

The filters and the stock sources live in the query string (a GET form), so a result is a link: `parse` reads them (a refused value keeps its
default and is named in `problem`), `context` builds what the list page and the set page show. The page size is `PAGE`."""
from urllib.parse import urlencode

from ..core import build_scout, collection

PAGE = 25
SHOWN_LINES = 2                 # missing lines a set's panel shows before "Show all"
FILTERS = ('min_percent', 'max_missing', 'theme', 'year_from', 'year_to', 'size_from', 'size_to')


def parse(args):
    """`dict(lots, storages, loose, damaged, filters, page, problem)` of the request's query; `filters` holds only what is set."""
    problem, filters = None, {}
    for name in FILTERS:
        value = (args.get(name) or '').strip()
        if value:
            filters[name] = value
    filters.setdefault('min_percent', str(build_scout.DEFAULT_MIN_PERCENT))
    try:
        build_scout._filters(dict(filters))
    except ValueError as error:
        problem = str(error)
        filters = {'min_percent': str(build_scout.DEFAULT_MIN_PERCENT)}
    try:
        page = max(1, int(args.get('page') or 1))
    except ValueError:
        page = 1
    return dict(lots=args.getlist('lot'), storages=args.getlist('storage'), loose=args.get('loose') == '1', damaged=args.get('damaged') == '1',
                filters=filters, page=page, problem=problem)


def query(params, **extra):
    """The query string that carries a parse back into a link (`extra` replaces or adds; a None drops)."""
    pairs = [('lot', v) for v in params['lots']] + [('storage', v) for v in params['storages']]
    if params['loose']:
        pairs.append(('loose', '1'))
    if params['damaged']:
        pairs.append(('damaged', '1'))
    pairs += [(k, v) for k, v in params['filters'].items() if not (k == 'min_percent' and v == str(build_scout.DEFAULT_MIN_PERCENT))]
    for key, value in extra.items():
        pairs = [p for p in pairs if p[0] != key]
        if value is not None:
            pairs.append((key, str(value)))
    return urlencode(pairs)


def sources(params):
    return dict(lots=params['lots'], storages=params['storages'], loose=params['loose'], damaged=params['damaged'])


def options(db):
    """What the filter pop-overs offer: the live lots and storages and the catalogue's theme names."""
    chosen = build_scout.scout_for(db)
    return dict(lots=[dict(r) for r in db.execute('SELECT id, name FROM main.lot WHERE archived_at IS NULL ORDER BY lower(name), id')],
                storages=[dict(r) for r in db.execute('SELECT id, name FROM main.storage WHERE archived_at IS NULL ORDER BY lower(name), id')],
                themes=sorted({name for name, _ in chosen.themes.values()}, key=str.casefold))


def _named(db, rows):
    """The rows with the screens' words for their item (and colour): number, name, picture, colour name and ink."""
    return collection.decorate(db, rows)


def _sets(db, results):
    shown = {r['item_id']: r for r in _named(db, [dict(item_id=r['set_item_id'], color_id=None) for r in results])}
    return [dict(r, **{k: shown[r['set_item_id']].get(k) for k in ('item_type', 'item_no', 'number_text', 'name', 'image', 'unresolved')},
                 **{'item_id': r['set_item_id']}) for r in results]


def _lines(db, lines):
    """Gap lines with their item and colour words."""
    shown = _named(db, [dict(item_id=l['item_id'], color_id=l.get('color_id')) for l in lines])
    return [dict(l, **{k: s.get(k) for k in ('item_type', 'item_no', 'number_text', 'name', 'image', 'color_name', 'rgb', 'ink')}) for l, s in zip(lines, shown)]


def detail(db, params, set_item_id):
    """The panel of one set: its numbers, missing lines (with words), swaps and cost, or `None` when it is no candidate."""
    try:
        found = build_scout.set_detail(db, set_item_id, **sources(params))
    except ValueError:
        return None
    shown = _sets(db, [dict(found, set_item_id=found['set_item_id'])])[0]
    shown['gaps'] = _lines(db, found['gaps'])
    shown['figure_gaps'] = _lines(db, found['figure_gaps'])
    swaps = found['swaps']
    pairs = []
    for s in swaps['items']:
        have, wanted = _lines(db, [dict(item_id=s['have']['item_id'], color_id=s['have']['color_id']), dict(item_id=s['wanted']['item_id'], color_id=s['wanted']['color_id'])])
        pairs.append(dict(kind=s['kind'], quantity=s['quantity'], have=have, wanted=wanted))
    shown['swaps'] = dict(swaps, items=pairs)
    shown['hidden_lines'] = max(0, len(shown['gaps']) - SHOWN_LINES)
    shown['gap_lines_total'] = found['missing_lines']
    return shown


def context(db, params, selected=None):
    """What the list page shows: the ranked page with its words, the options, and the panel of the selected set (the first when none is named)."""
    answer = build_scout.scout(db, limit=PAGE, offset=(params['page'] - 1) * PAGE, cost=True, **sources(params), **params['filters'])
    rows = _sets(db, answer['results'])
    panel = None
    if rows:
        panel = (detail(db, params, selected) if selected else None) or detail(db, params, rows[0]['set_item_id'])
        for r in rows:
            r['selected'] = r['set_item_id'] == (panel or {}).get('set_item_id')
    pages = max(1, -(-answer['total'] // PAGE))
    return dict(answer=answer, rows=rows, panel=panel, options=options(db), pages=pages, page=params['page'],
                has_stock=bool(answer['input']['lines']))
