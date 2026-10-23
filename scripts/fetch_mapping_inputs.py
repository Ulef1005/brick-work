#!/usr/bin/env python3
"""Fetch the inputs of the shipped catalogue mappings: Rebrickable's CSV dump and the colour/part external_ids.

Runs on rasp, under `op run` so that BW_REBRICKABLE_API_KEY is in the environment (the key is never printed).
It makes about 66 API calls (275 colours in one page, 64,906 parts in about 65 pages), 1.1 s apart, plus 12 dump downloads
from the CDN. Writes <out dir>/dump/*.csv.gz, <out dir>/external_ids.jsonl and <out dir>/fetched.json.

Usage: fetch_mapping_inputs.py <out dir>
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

UA = {'User-Agent': 'brick-work-mappings'}
DUMP_FILES = ('themes', 'colors', 'part_categories', 'parts', 'part_relationships', 'elements', 'sets', 'minifigs',
              'inventories', 'inventory_parts', 'inventory_minifigs', 'inventory_sets')
ENDPOINTS = (('color', 'https://rebrickable.com/api/v3/lego/colors/?page_size=1000', 'id'),
             ('part', 'https://rebrickable.com/api/v3/lego/parts/?inc_part_details=1&page_size=1000', 'part_num'))


def main(argv):
    if len(argv) != 2:
        sys.exit(__doc__)
    key = os.environ.get('BW_REBRICKABLE_API_KEY')
    if not key:
        sys.exit('BW_REBRICKABLE_API_KEY is not set (run under op run)')
    out = Path(argv[1])
    (out / 'dump').mkdir(parents=True, exist_ok=True)
    # fetched.json marks a complete set: drop it first, so an interrupted run never passes for a finished one.
    (out / 'fetched.json').unlink(missing_ok=True)
    for name in DUMP_FILES:
        req = urllib.request.Request(f'https://cdn.rebrickable.com/media/downloads/{name}.csv.gz', headers=UA)
        with urllib.request.urlopen(req, timeout=300) as r:
            (out / 'dump' / f'{name}.csv.gz').write_bytes(r.read())
            print(name, r.headers.get('Last-Modified'), flush=True)
    calls, counts = 0, {}
    partial = out / 'external_ids.jsonl.partial'
    with open(partial, 'w') as f:
        for kind, url, id_field in ENDPOINTS:
            n = 0
            while url:
                req = urllib.request.Request(url, headers={**UA, 'Authorization': f'key {key}'})
                with urllib.request.urlopen(req, timeout=120) as r:
                    page = json.load(r)
                calls += 1
                for x in page['results']:
                    f.write(json.dumps({'kind': kind, 'id': str(x[id_field]), 'name': x.get('name'),
                                        'external_ids': x.get('external_ids') or {}}) + '\n')
                n += len(page['results'])
                url = page['next']
                time.sleep(1.1)
            counts[kind] = n
            print(kind, n, flush=True)
    partial.replace(out / 'external_ids.jsonl')
    (out / 'fetched.json').write_text(json.dumps({'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                                  'api_calls': calls, 'counts': counts}))
    print('calls', calls)


if __name__ == '__main__':
    main(sys.argv)
