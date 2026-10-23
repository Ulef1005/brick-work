#!/usr/bin/env python3
"""Build the shipped mapping files colors.csv and parts.csv from Rebrickable's dump and external_ids (design 3.2, 3.3, 3.7).

Usage: build_mappings.py <inputs dir> <out dir> --version <mapping_version> --dump-date <YYYY-MM-DD>

<inputs dir> holds dump/*.csv.gz, external_ids.jsonl and fetched.json (scripts/fetch_mapping_inputs.py). Deterministic: the same
inputs give byte-identical files. set_exceptions.csv and theme_kinds.csv are kept by hand and not written here.
"""
import argparse
import csv
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brickwork.store4.mappings import COLUMNS  # noqa: E402

SOURCE = 'Rebrickable (https://rebrickable.com), data free to use with acknowledgement'


def dump_rows(inputs, name):
    with gzip.open(Path(inputs) / 'dump' / f'{name}.csv.gz', 'rt', newline='', encoding='utf-8') as f:
        yield from csv.DictReader(f)


def natural(s):
    return [(0, int(t), '') if t.isdigit() else (1, 0, t) for t in re.split(r'(\d+)', str(s)) if t]


def write(path, header, columns, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        f.write(''.join(f'# {line}\n' for line in header))
        w = csv.writer(f, lineterminator='\n')
        w.writerow(columns)
        w.writerows([r[c] for c in columns] for r in rows)


def color_rows(inputs, external):
    parts_of = {r['id']: int(r['num_parts'] or 0) for r in dump_rows(inputs, 'colors')}
    names = {r['id']: r['name'] for r in dump_rows(inputs, 'colors')}
    rows = []
    for rec in external:
        if rec['kind'] != 'color':
            continue
        for provider, label in (('bricklink', 'BrickLink'), ('lego', 'LEGO')):
            ext = (rec['external_ids'] or {}).get(label) or {}
            seen = set()
            for key, descr in zip(ext.get('ext_ids') or [], ext.get('ext_descrs') or []):
                if key is None or str(key) in seen:
                    continue
                seen.add(str(key))
                rows.append(dict(rb_color_id=rec['id'], rb_name=names.get(rec['id'], rec['name']), provider=provider,
                                 provider_key=str(key), provider_name=(descr or [''])[0], inverse_preferred='0',
                                 rb_num_parts=str(parts_of.get(rec['id'], 0))))
    shared = {}
    for r in rows:
        shared.setdefault((r['provider'], r['provider_key']), []).append(r)
    for group in shared.values():
        if len(group) > 1:
            min(group, key=lambda r: (-int(r['rb_num_parts']), int(r['rb_color_id'])))['inverse_preferred'] = '1'
    rows.sort(key=lambda r: (int(r['rb_color_id']), r['provider'], natural(r['provider_key'])))
    return rows, {k: [r for r in g] for k, g in shared.items() if len(g) > 1}


def part_rows(inputs, external):
    design = {}
    for e in dump_rows(inputs, 'elements'):
        if e['design_id']:
            design.setdefault(e['part_num'], set()).add(e['design_id'])
    rows = []
    for rec in external:
        if rec['kind'] != 'part':
            continue
        num = rec['id']
        ids = list(dict.fromkeys(str(k) for k in (rec['external_ids'] or {}).get('BrickLink') or []))
        if ids:
            pick = num if len(ids) > 1 and num in ids else None
            found = [(k, 'matched', 'external_ids', '1' if k == pick else '0') for k in ids]
        else:
            found = [(k, 'inferred', 'element', '0') for k in design.get(num, ())]
        rows += [dict(rb_part_num=num, rb_color_id='', provider='bricklink', provider_kind='P', provider_key=k, status=s, method=m,
                      preferred=p) for k, s, m, p in found]
    rows.sort(key=lambda r: (r['rb_part_num'], natural(r['provider_key'])))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('inputs')
    ap.add_argument('out')
    ap.add_argument('--version', required=True)
    ap.add_argument('--dump-date', required=True)
    a = ap.parse_args(argv)
    inputs, out = Path(a.inputs), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((inputs / 'fetched.json').read_text())
    fetched = manifest['fetched_at']
    external = [json.loads(line) for line in (inputs / 'external_ids.jsonl').read_text(encoding='utf-8').splitlines() if line]
    # Refuse an incomplete fetch: the manifest is written last and names how many rows each kind had.
    found = {kind: sum(1 for x in external if x['kind'] == kind) for kind in ('color', 'part')}
    if manifest.get('counts') != found:
        sys.exit(f'external_ids.jsonl has {found}, fetched.json says {manifest.get("counts")}: incomplete fetch, run it again')
    header = [f'mapping_version: {a.version}', f'dump_date: {a.dump_date}', f'external_ids_fetched: {fetched}', f'source: {SOURCE}']
    colors, shared = color_rows(inputs, external)
    parts = part_rows(inputs, external)
    write(out / 'colors.csv', header, COLUMNS['colors.csv'], colors)
    write(out / 'parts.csv', header, COLUMNS['parts.csv'], parts)
    print(f'colors.csv {len(colors)} rows, parts.csv {len(parts)} rows')
    for (provider, key), group in sorted(shared.items(), key=lambda kv: (kv[0][0], natural(kv[0][1]))):
        print('shared', provider, key, [(r['rb_color_id'], r['rb_name'], r['rb_num_parts'], r['inverse_preferred']) for r in group])


if __name__ == '__main__':
    main()
