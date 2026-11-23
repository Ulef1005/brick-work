#!/usr/bin/env python3
"""Fetch the part and minifigure pictures the demo world lacks, through the Rebrickable API, into a folder to review (#643).

    python3 -I scripts/fetch_demo_pictures.py OUT [--limit N]

Ulf decided on 2026-11-23 (asked in the brick-work-marketing session, "Scripted API download anyway") that the pictures the demo needs are fetched
by script although not-mit/NOTICE.md and Rebrickable's terms (section 5.2) say otherwise; the NOTICE records the decision and its limits. The limits
this script keeps: only the (part, colour) pairs and minifigures the seven sets of `not-mit/rebrickable/sets.json` list and the folder does not hold
yet, one request per second, one run, no retry storm (a failing request is skipped and reported). Nothing is fetched for a pair that has a picture.

The API key is read from the environment variable REBRICKABLE_API_KEY and kept in this process only. Pictures land in OUT as
parts/<part>-<colour>.png and minifigs/<fig>.jpg with a `manifest.json` in the folder's own format, for review before they move into
not-mit/rebrickable/images/ (nothing here writes there).
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'not-mit' / 'rebrickable'
API = 'https://rebrickable.com/api/v3/lego'
PAUSE = 1.1


def wanted():
    data = json.loads((FOLDER / 'sets.json').read_text())
    have = json.loads((FOLDER / 'images' / 'manifest.json').read_text())
    pairs, figures = {}, {}
    for item in data['sets']:
        for line in item['parts_list']:
            key = f"parts/{line['part']}/{line['color']['id']}"
            if key not in have:
                pairs[key] = (line['part'], line['color']['id'])
        for lines in item['minifigure_parts'].values():   # the printed torsos, heads and hats of the figures
            for line in lines:
                key = f"parts/{line['part']}/{line['color']['id']}"
                if key not in have:
                    pairs[key] = (line['part'], line['color']['id'])
        for figure in item['minifigures']:
            key = f"minifigs/{figure['figure']}"
            if key not in have and figure.get('image_url'):
                figures[key] = figure['image_url']
    return pairs, figures


def get(url, key=None, binary=False):
    request = urllib.request.Request(url, headers={'User-Agent': 'brick-work-demo-pictures', **({'Authorization': f'key {key}'} if key else {})})
    with urllib.request.urlopen(request, timeout=30) as reply:
        body = reply.read()
    return body if binary else json.loads(body)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    parser.add_argument('--limit', type=int, default=0, help='stop after N requests (a trial run)')
    options = parser.parse_args(argv)
    out = Path(options.out)
    pairs, figures = wanted()
    print(f'{len(pairs)} part pictures and {len(figures)} minifigure pictures wanted', file=sys.stderr)
    key = os.environ.get('REBRICKABLE_API_KEY', '').strip()
    if not key:
        parser.error('set REBRICKABLE_API_KEY')
    manifest_path = out / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    (out / 'parts').mkdir(parents=True, exist_ok=True)
    (out / 'minifigs').mkdir(parents=True, exist_ok=True)
    done = failed = 0
    for catalogue, url in figures.items():
        if catalogue in manifest:
            continue
        try:
            file = f"{catalogue}.jpg"
            (out / file).write_bytes(get(url, binary=True))
            manifest[catalogue] = file
            done += 1
        except (urllib.error.URLError, OSError) as exc:
            failed += 1
            print(f'skipped {catalogue}: {exc}', file=sys.stderr)
        time.sleep(PAUSE)
    for catalogue, (part, colour) in pairs.items():
        if catalogue in manifest:
            continue
        if options.limit and done + failed >= options.limit:
            break
        try:
            info = get(f'{API}/parts/{part}/colors/{colour}/', key)
            url = info.get('part_img_url')
            if not url:
                raise OSError('no picture for this colour')
            time.sleep(PAUSE)
            body = get(url, binary=True)
            file = f'parts/{part}-{colour}.' + ('png' if body[:4] == b'\x89PNG' else 'jpg')   # the file's real type, as the folder's own manifest does
            (out / file).write_bytes(body)
            manifest[catalogue] = file
            done += 1
        except (urllib.error.URLError, OSError) as exc:
            failed += 1
            print(f'skipped {catalogue}: {exc}', file=sys.stderr)
        time.sleep(PAUSE)
        if done % 25 == 0:
            manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f'{done} fetched, {failed} skipped, {len(manifest)} in {manifest_path}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
