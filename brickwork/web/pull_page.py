"""The pull list page of a lot (#202): what the page shows, from `core/pull_list.py`.

Everything is computed on the server and works without JavaScript: search, Show and Sort are a GET form (their state is the URL's query), a counter is a plain form
post that returns to the same place, and the confirm is the same page with the dialog open (a sheet on a phone, a centred dialog on a desktop; CSS only)."""
from urllib.parse import urlencode

from ..core import collection, pull_list

SHOW_LABEL = {'find': 'To find', 'found': 'Found', 'all': 'All'}
SORT_LABEL = {'category': 'Category', 'number': 'Number'}
FIRST = 40                      # lines shown before "Show all"


def read_args(args):
    """`dict(q, show, sort, every)` from the page's query; a value that is none of the choices is the default."""
    show = args.get('show') if args.get('show') in pull_list.SHOWS else 'find'
    sort = args.get('sort') if args.get('sort') in SORT_LABEL else 'category'
    return dict(q=(args.get('q') or '').strip()[:80], show=show, sort=sort, every=args.get('all') == '1')


def query_of(view, **more):
    """The query string a link keeps: the search, Show and Sort of the page (defaults left out), with `more` replacing members."""
    values = {**view, **more}
    pairs = []
    if values['q']:
        pairs.append(('q', values['q']))
    if values['show'] != 'find':
        pairs.append(('show', values['show']))
    if values['sort'] != 'category':
        pairs.append(('sort', values['sort']))
    if values['every']:
        pairs.append(('all', '1'))
    return urlencode(pairs)


def _matches(row, needle):
    text = ' '.join(str(row.get(k) or '') for k in ('name', 'number', 'colour')).casefold()
    return all(word in text for word in needle.casefold().split())


def page(db, lot_id, set_id, args):
    """The page's data: `dict(info, view, groups, shown, hidden, moves, set_row, numbers)`; `pull_list.state`'s refusals propagate (`errors.NotFound`, `ValueError`)."""
    from ..api2.ranking import pictures_of
    view = read_args(args)
    info = pull_list.state(db, lot_id, set_id)
    rows = collection.decorate(db, [dict(item_id=ln['item_id'], color_id=ln['color_id']) for ln in info['lines']] + [dict(item_id=info['set']['id'], color_id=None)])
    book = {(r['item_id'], r.get('color_id')): r for r in rows}
    shots = pictures_of(db, {(ln['item_id'], ln['color_id']) for ln in info['lines']})
    facts = db.execute('SELECT i.year, i.num_parts, t.name FROM catalogue.item i LEFT JOIN catalogue.theme t ON t.id=i.theme_id WHERE i.id=?',
                       (info['set']['id'],)).fetchone()
    lines = []
    for ln in info['lines']:
        row = book.get((ln['item_id'], ln['color_id']), {})
        shot = shots.get((ln['item_id'], ln['color_id'])) or {}
        lines.append(dict(ln, name=row.get('name') or row.get('item_no') or '', number=row.get('number_text') or row.get('item_no') or '', colour=row.get('color_name') or '',
                          rgb=row.get('rgb'), ink=row.get('ink'), image=shot.get('id'), to_find=ln['need'] - ln['found'], full=ln['found'] >= ln['need']))
    chosen = [ln for ln in lines if (view['show'] == 'all' or (view['show'] == 'find') != ln['full']) and (not view['q'] or _matches(ln, view['q']))]
    figures_last = lambda ln: ln['kind'] == 'figure'                                     # noqa: E731
    if view['sort'] == 'number':
        chosen.sort(key=lambda ln: (ln['number'], ln['colour']))
        order = [('All parts', chosen)]
    else:
        names = {}
        for ln in chosen:
            names.setdefault(ln['category'], []).append(ln)
        order = [(name, sorted(group, key=lambda ln: (ln['number'], ln['colour']))) for name, group in sorted(names.items(), key=lambda kv: (figures_last(kv[1][0]), kv[0]))]
    budget = len(chosen) if view['every'] else FIRST
    groups, left = [], budget
    for name, group in order:
        if left <= 0:
            break
        part = group[:left]
        left -= len(part)
        groups.append(dict(name=name, lines=part, to_find=sum(ln['to_find'] for ln in part)))
    shown = sum(len(g['lines']) for g in groups)
    identity = book.get((info['set']['id'], None), {})
    set_row = dict(id=info['set']['id'], name=identity.get('name') or info['set']['name'], number=identity.get('number_text') or identity.get('item_no') or '',
                   theme=(facts['name'] if facts else '') or '', year=facts['year'] if facts else None, size=facts['num_parts'] if facts else None)
    return dict(info=info, view=view, groups=groups, shown=shown, hidden=len(chosen) - shown, total=len(chosen), moves=pull_list.moves(info), set_row=set_row)
