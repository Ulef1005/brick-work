#!/usr/bin/env python3
"""Cut the demo's seven real sets out of Rebrickable's CSV download into `not-mit/rebrickable/sets.json` (#332).

    python3 -I scripts/extract_rebrickable.py <rebrickable_DataModel.zip> [<out folder>]

Run by hand, once, with the download from Rebrickable's Downloads page. Nothing here fetches anything: the zip is read as it is, and the pictures are
fetched separately, by hand (not-mit/rebrickable/NOTICE.md). The output is Rebrickable data, so it lives in the not-MIT folder with its notice and is
read at build time by `brickwork/demo/real.py`; CI never needs the download.

What it keeps, per set: number, name, year, theme path and the theme id of the leaf, the part count and the picture's source URL; the inventory's part
lines (version 1 when a set has several, which is the first release's list), with each part's name and category and each colour's name, RGB and
transparency; the minifigures with their own part lists (a figure's inventory is the one whose set number is the figure number).
"""
import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

SETS = ['31120-1', '7938-1', '8043-1', '10210-1', '7213-1', '10254-1', '21028-1']
PRINTED = re.compile(r'\bprint\b|pr\d{3,}$|pat\d+$', re.I)


def rows(archive, name):
    with archive.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8', newline=''))


def theme_path(themes, theme_id):
    names = []
    while theme_id:
        row = themes[theme_id]
        names.append(row['name'])
        theme_id = row['parent_id']
    return ' / '.join(reversed(names))


def main(zip_path, out):
    out = Path(out)
    with zipfile.ZipFile(zip_path) as archive:
        themes = {r['id']: r for r in rows(archive, 'themes.csv')}
        sets = {r['set_num']: r for r in rows(archive, 'sets.csv') if r['set_num'] in SETS}
        if sorted(sets) != sorted(SETS):
            raise SystemExit('missing sets: ' + ', '.join(sorted(set(SETS) - set(sets))))
        versions = {}
        for r in rows(archive, 'inventories.csv'):
            versions.setdefault(r['set_num'], []).append((int(r['version']), r['id']))
        inventory_of = {number: min(found)[1] for number, found in versions.items()}   # version 1: the first release's list
        figures = {}   # inventory id -> the sets' figures
        for r in rows(archive, 'inventory_minifigs.csv'):
            figures.setdefault(r['inventory_id'], []).append((r['fig_num'], int(r['quantity'])))
        wanted = {inventory_of[n] for n in SETS}
        figure_numbers = {fig for inv in wanted for fig, _ in figures.get(inv, [])}
        wanted |= {inventory_of[f] for f in figure_numbers}
        lines = {}
        for r in rows(archive, 'inventory_parts.csv'):
            if r['inventory_id'] in wanted:
                lines.setdefault(r['inventory_id'], []).append(r)
        minifigs = {r['fig_num']: r for r in rows(archive, 'minifigs.csv') if r['fig_num'] in figure_numbers}
        needed = {l['part_num'] for found in lines.values() for l in found}
        parts = {r['part_num']: r for r in rows(archive, 'parts.csv') if r['part_num'] in needed}
        categories = {r['id']: r['name'] for r in rows(archive, 'part_categories.csv')}
        colours = {r['id']: r for r in rows(archive, 'colors.csv')}

    def line(row, figure=None):
        part, colour = parts[row['part_num']], colours[row['color_id']]
        return {'figure': figure, 'part': part['part_num'], 'name': part['name'], 'category': categories[part['part_cat_id']],
                'color': {'id': int(colour['id']), 'name': colour['name'], 'rgb': '#' + colour['rgb'].lstrip('#'), 'transparent': colour['is_trans'] == 'True'},
                'quantity': int(row['quantity']), 'spare': row['is_spare'] == 'True', 'element': None,
                'print': bool(PRINTED.search(part['name']) or PRINTED.search(part['part_num']))}

    result = []
    for number in SETS:
        info, inventory = sets[number], inventory_of[number]
        entry = {'set': number, 'name': info['name'], 'year': int(info['year']), 'theme_id': int(info['theme_id']),
                 'theme_path': theme_path(themes, info['theme_id']), 'parts': int(info['num_parts']), 'image_url': info['img_url'],
                 'parts_list': [line(r) for r in lines.get(inventory, [])], 'minifigures': [], 'minifigure_parts': {}}
        for fig, quantity in figures.get(inventory, []):
            entry['minifigures'].append({'figure': fig, 'name': minifigs[fig]['name'], 'quantity': quantity, 'parts': int(minifigs[fig]['num_parts']),
                                         'image_url': minifigs[fig]['img_url']})
            entry['minifigure_parts'][fig] = [line(r, fig) for r in lines.get(inventory_of[fig], [])]
        result.append(entry)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'sets.json').write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"{len(result)} sets, {sum(len(e['parts_list']) for e in result)} part lines, {sum(len(e['minifigures']) for e in result)} figures -> {out / 'sets.json'}")


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else Path(__file__).resolve().parents[1] / 'not-mit' / 'rebrickable')
