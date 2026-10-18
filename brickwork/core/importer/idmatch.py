"""Offline, evidence-only Rebrickable to BrickLink matching.

Used by the BrickTracker importer to resolve identities from the old data.
Candidate ids are retained on failed rows for auditing; only ``matched`` rows
have a validated item and an unambiguous colour (where applicable).
"""

from collections import Counter, defaultdict
from contextlib import ExitStack, closing
import csv
import json
from pathlib import Path
import sqlite3
import sys


PART_FIELDS = [
    'source', 'id', 'set', 'figure', 'part', 'color', 'spare', 'quantity',
    'missing', 'damaged', 'checked', 'element', 'rebrickable_inventory',
    'bricklink_item_no', 'bricklink_color_id', 'part_bricklink_color_id',
    'color_candidates', 'item_candidates', 'method', 'status', 'reason',
]
FIGURE_FIELDS = [
    'source', 'id', 'set', 'figure', 'quantity', 'missing',
    'bricklink_item_no', 'item_candidates', 'method', 'status', 'reason',
]
COLOR_FIELDS = ['color', 'bricklink_color_id', 'color_candidates',
                'method', 'status', 'reason']
SET_FIELDS = ['set', 'owned', 'wanted', 'bricklink_item_no',
              'method', 'status', 'reason']
FIELDS = {'parts': PART_FIELDS, 'loose_parts': PART_FIELDS,
          'minifigures': FIGURE_FIELDS, 'colours': COLOR_FIELDS, 'sets': SET_FIELDS}


def open_readonly(path):
    """Use SQLite's read-only mode, including normal rollback-journal handling."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def _rows(db, table):
    return [dict(row) for row in db.execute(f'SELECT * FROM "{table}"')]


def _decision(method, status='matched', reason='', **values):
    return dict(method=method, status=status, reason=reason, **values)


def _coverage(rows):
    methods = Counter(r['method'] for r in rows if r['status'] == 'matched')
    failures = defaultdict(list)
    for row in rows:
        if row['status'] != 'matched':
            failures[(row['status'], row['reason'])].append(row)
    return {
        'total': len(rows), 'matched': sum(methods.values()),
        'matched_by_method': dict(sorted(methods.items())),
        'conflict': sum(r['status'] == 'conflict' for r in rows),
        'unmatched': sum(r['status'] == 'unmatched' for r in rows),
        'reasons': [
            {'status': status, 'reason': reason, 'count': len(group),
             'examples': [{key: r[key] for key in
                           ('source', 'id', 'set', 'figure', 'part', 'color', 'spare')
                           if key in r} for r in group[:10]]}
            for (status, reason), group in sorted(
                failures.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        ],
    }


def match(app_path, web_path, catalog_path):
    """Return CSV-ready rows and counts without modifying any input database."""
    with ExitStack() as stack:
        app, web, catalog = [stack.enter_context(closing(open_readonly(path)))
                               for path in (app_path, web_path, catalog_path)]
        items = {(r['item_type'], r['item_no']) for r in _rows(catalog, 'items')}
        colors = defaultdict(set)
        for row in _rows(web, 'color_map'):
            colors[row['color_id']].add(row['bricklink_color_id'])
        resolutions = defaultdict(set)
        for row in _rows(web, 'part_resolutions'):
            # Invalid evidence must fail visibly, never silently disappear.
            for candidate in json.loads(row['parts']):
                resolutions[candidate['part_num']].add(row['bricklink'])
        direct_parts = {(r['part'], r['color_id']): r
                        for r in _rows(app, 'rebrickable_parts')}
        direct_figures = {r['figure']: r['bricklink_id']
                          for r in _rows(web, 'minifig_bricklink')}
        reverse_figures = defaultdict(set)
        for row in _rows(web, 'bricklink_figures'):
            if row['figure'] and row['state'] in ('matched', 'manual'):
                reverse_figures[row['figure']].add(row['bricklink_id'])
        copies = {r['id']: r['set'] for r in _rows(app, 'bricktracker_sets')}
        missing_figures = {(r['copy_id'], r['figure']): r['missing']
                           for r in _rows(web, 'minifig_missing')}

        def color_match(color):
            candidates = sorted(colors[color])
            values = dict(bricklink_color_id=candidates[0] if len(candidates) == 1
                          else None, color_candidates=json.dumps(candidates))
            if not candidates:
                return _decision('color_map', 'unmatched', 'no colour mapping', **values)
            if len(candidates) > 1:
                return _decision('color_map', 'conflict', 'ambiguous colour mapping', **values)
            return _decision('color_map', **values)

        def validate(item, kind, method):
            return _decision(method, **({'status': 'unmatched',
                                        'reason': 'not in BrickLink catalogue'}
                                       if (kind, item) not in items else {}),
                             bricklink_item_no=item)

        def part_match(row):
            colour = color_match(row['color'])
            direct = direct_parts.get((row['part'], row['color']), {})
            item = direct.get('bricklink_part_num')
            stored_color = direct.get('bricklink_color_id')
            candidates = sorted(resolutions[row['part']]) if not item else [item]
            method = 'rebrickable_parts' if item else 'part_resolutions'
            values = dict(bricklink_item_no=item, method=method,
                          bricklink_color_id=colour['bricklink_color_id'],
                          part_bricklink_color_id=stored_color,
                          color_candidates=colour['color_candidates'],
                          item_candidates=json.dumps(candidates))
            if colour['status'] != 'matched':
                return dict(values, status=colour['status'], reason=colour['reason'])
            if stored_color is not None and stored_color != colour['bricklink_color_id']:
                return dict(values, status='conflict', reason='part colour disagrees with color_map')
            if not item:
                if not candidates:
                    return dict(values, status='unmatched', reason='no part mapping')
                if len(candidates) > 1:
                    return dict(values, status='conflict', reason='ambiguous part resolution')
                item = candidates[0]
            return dict(values, **validate(item, 'P', method))

        def figure_match(figure):
            item = direct_figures.get(figure)
            method = 'minifig_bricklink' if item else 'bricklink_figures'
            candidates = [item] if item else sorted(reverse_figures[figure])
            values = dict(item_candidates=json.dumps(candidates))
            if not candidates:
                return dict(values, **_decision(method, 'unmatched', 'no minifigure mapping'))
            if len(candidates) > 1:
                return dict(values, **_decision(method, 'conflict', 'ambiguous minifigure mapping'))
            return dict(values, **validate(candidates[0], 'M', method))

        result = {entity: [] for entity in FIELDS}
        loose_figures = {r['id']: r['figure'] for r in
                         _rows(app, 'bricktracker_individual_minifigures')}
        for table, entity, source in (
            ('bricktracker_parts', 'parts', 'copy'),
            ('bricktracker_individual_parts', 'loose_parts', 'loose_part'),
            ('bricktracker_individual_minifigure_parts', 'loose_parts', 'loose_figure_part'),
        ):
            for original in _rows(app, table):
                row = {key: original[key] for key in PART_FIELDS if key in original}
                row.update(source=source, set=copies.get(row['id']) if source == 'copy' else None)
                if source == 'loose_figure_part':
                    row['figure'] = loose_figures.get(row['id'])
                row.update(part_match(row))
                result[entity].append(row)
        seen_figures = set()
        for table, source in (('bricktracker_minifigures', 'copy'),
                              ('bricktracker_individual_minifigures', 'loose_figure')):
            for original in _rows(app, table):
                row = {key: original[key] for key in ('id', 'figure', 'quantity')}
                key = (row['id'], row['figure'])
                if source == 'copy':
                    seen_figures.add(key)
                row.update(source=source, set=copies.get(row['id']) if source == 'copy' else None,
                           missing=missing_figures.get(key, 0) if source == 'copy' else 0)
                row.update(figure_match(row['figure']))
                result['minifigures'].append(row)
        for (copy, figure), missing in missing_figures.items():
            if (copy, figure) not in seen_figures:
                result['minifigures'].append(dict(
                    source='missing_figure', id=copy, set=copies.get(copy), figure=figure,
                    quantity=None, missing=missing, **figure_match(figure)))
        used_colors = {r['color'] for entity in ('parts', 'loose_parts') for r in result[entity]}
        result['colours'] = [dict(color=color, **color_match(color))
                             for color in sorted(used_colors)]
        owned = set(copies.values())
        wanted = {r['set'] for r in _rows(app, 'bricktracker_wishes')}
        result['sets'] = [dict(set=number, owned=int(number in owned),
                               wanted=int(number in wanted),
                               **validate(number, 'S', 'set_number'))
                          for number in sorted(owned | wanted)]
    for entity, rows in result.items():
        rows.sort(key=lambda r: tuple(str(r.get(k, '')) for k in FIELDS[entity]))
    summary = {entity: _coverage(rows) for entity, rows in result.items()}
    summary['user_state'] = {
        'missing>0': {entity: _coverage([r for r in result[entity] if r.get('missing', 0) > 0])
                      for entity in ('parts', 'loose_parts')},
        'checked=1': {entity: _coverage([r for r in result[entity] if r.get('checked') == 1])
                      for entity in ('parts', 'loose_parts')},
        'minifig_missing': _coverage([r for r in result['minifigures'] if r['missing'] > 0]),
    }
    return dict(result, summary=summary)


