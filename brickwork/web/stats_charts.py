"""The Statistics screen's charts (#220): Hichert SUCCESS. Titles state the point and come from the data, one scale serves every chart
(the copies unit), and a long tail folds into one outlined row. Pure functions over `core.admin.statistics`."""
from .formatting import plural

FOLD_AFTER = 6
COMPLETENESS_ORDER = ('Complete', 'Incomplete', 'Not checked', 'Sealed')


def _copies(n):
    return plural(n, 'copy', 'copies')


def headline(completeness):
    total = sum(r['count'] for r in completeness)
    if not total:
        return 'No copies yet'
    incomplete = sum(r['count'] for r in completeness if r['label'] == 'Incomplete')
    return f"{incomplete} of {total} {'copy is' if total == 1 else 'copies are'} incomplete"


def _fold(rows, noun):
    """The first FOLD_AFTER rows, then one folded row ("N more places") carrying the summed value."""
    shown = [dict(r, folded=False) for r in rows[:FOLD_AFTER]]
    rest = rows[FOLD_AFTER:]
    if rest:
        shown.append({'label': f"{len(rest)} more {noun if len(rest) == 1 else noun + 's'}",
                      'count': sum(r['count'] for r in rest), 'folded': True})
    return shown


def _title(kind, rows):
    if not rows:
        return 'No copies yet'
    top = rows[0]
    if kind == 'completeness':
        done = next((r['count'] for r in rows if r['label'] == 'Complete'), 0)
        total = sum(r['count'] for r in rows)
        if done == total:
            return f"All {_copies(total)} {'is' if total == 1 else 'are'} complete"
        if not done:
            return 'No copy is complete'
        return f"Only {_copies(done)} {'is' if done == 1 else 'are'} complete"
    if kind == 'theme':
        return f"{top['label']} is the biggest theme, {_copies(top['count'])}"
    return f"{top['label']} holds the most, {_copies(top['count'])}"


def charts(data):
    """[{kind, title, subtitle, rows: [{label, count, folded, width}]}] for the four charts. `width` is a percentage of the one scale:
    the largest value shown in any chart, folded rows included."""
    completeness = sorted(data['completeness'], key=lambda r: COMPLETENESS_ORDER.index(r['label']) if r['label'] in COMPLETENESS_ORDER else 99)
    specs = [('completeness', completeness, None), ('theme', data['theme'], 'theme'),
             ('storage', data['storage'], 'place'), ('purchase place', data['purchase place'], 'place')]
    result = [{'kind': kind, 'title': _title(kind, rows), 'subtitle': f'Copies by {kind}',
               'rows': rows if noun is None else _fold(rows, noun)} for kind, rows, noun in specs]
    result[0]['rows'] = [dict(r, folded=False) for r in result[0]['rows']]
    scale = max((r['count'] for c in result for r in c['rows']), default=0) or 1
    for c in result:
        for r in c['rows']:
            r['width'] = round(100 * r['count'] / scale, 2)
    return result
