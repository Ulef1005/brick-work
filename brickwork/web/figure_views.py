"""Server-side list controls for the Figures planning tab."""
from decimal import Decimal
from flask import request, url_for
from .valuation_views import _page_items
from ..core.figures import RULE

SORTS = [('gain', 'Gain from completing'), ('cost', 'Cost to complete'), ('parts', 'Part-out value'), ('number', 'Number'), ('name', 'Name')]


def listing(rows, args):
    params = {k: args.get(k, '').strip()[:100] for k in ('q', 'where', 'recommendation', 'theme', 'storage', 'sort')}
    if params['sort'] not in dict(SORTS):
        params['sort'] = 'gain'
    options = dict(where=[('loose', 'Loose'), ('sets', 'In a set')],
                   recommendation=[(v, v) for v in ('Complete it', 'Part out', 'Keep as is')],
                   theme=[(v, v) for v in sorted({r['theme'] for r in rows if r['theme']})],
                   storage=[(v, v) for v in sorted({r['storage_id'] for r in rows if r['storage_id']})])
    q = params['q'].casefold()
    shown = [r for r in rows if q in (r['number_text'] + ' ' + (r['name'] or '')).casefold()
             and all(not params[k] or str(r.get({'storage':'storage_id'}.get(k, k)) or '') == params[k]
                     for k in ('where', 'recommendation', 'theme', 'storage'))]
    def key(r):
        field = {'gain':'gain', 'cost':'to_complete', 'parts':'parts_value'}.get(params['sort'])
        value = r[field] if field else r['number_text'] if params['sort'] == 'number' else r['name'] or ''
        value = Decimal(value) * (-1 if field != 'to_complete' else 1) if field and value is not None else value
        return r['needs_evidence'], r['where'] != 'loose', value is None, value if value is not None else '', r['place']
    shown.sort(key=key)
    total, pages = len(shown), max(1, (len(shown) + 14) // 15)
    try: page = min(pages, max(1, int(args.get('page', 1))))
    except ValueError: page = 1
    def link(**change):
        query = {'tab':'figures', **params, **change}
        return url_for('web.bw_planning', screen='complete-sets', **{k:v for k,v in query.items() if v})
    pager = dict(page=page, pages=pages, total=total, first=(page-1)*15+1 if total else 0, last=min(total, page*15),
                 prev=link(page=page-1) if page>1 else None, next=link(page=page+1) if page<pages else None,
                 items=[dict(n=n, url=link(page=n) if n else None) for n in _page_items(page, pages)])
    return dict(rule=RULE, rows=shown[(page-1)*15:page*15], params=params, options=options, sorts=SORTS, pager=pager, link=link,
                all_complete=bool(rows) and all(not r['missing_count'] for r in rows), has_rows=bool(rows))
