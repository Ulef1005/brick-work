"""Pictures of the BUILT app for the README and the Pages site (replacing the design project's mock-ups).

    python scripts/site_shots.py [--only STEM ...] [--out DIR]

Renders the app on the invented 'showcase' world (the screen gate's world plus the richer demo layer, brickwork/demo/showcase.py) with the
pinned Chrome for Testing, at 1440 (desktop) and 390 (phone, drawn at twice the pixels), light and dark, with the clock fixed. Each picture is
written under the file name the page already uses (`<stem>-light.png`, `<stem>-dark.png`), clipped to a sensible height and optimised.
These are not gate baselines. No pictures of sets or parts are in the world, so tiles show the app's missing-picture note.
Run it from the app's venv (it imports the app).
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import screen_gate  # noqa: E402
from brickwork.demo.showcase import uid  # noqa: E402

SITE = ROOT / 'scripts' / 'site' / 'img'
README = ROOT / 'docs' / 'img' / 'readme'
STARTED = uid('copy', '99106-1', 'a')                # a check about 40 % answered (showcase.CHECKS)
GAPS = uid('copy', '99103-1', 'a')                   # a check answered to the end, with gaps
FRESH = uid('copy', '99113-1', 'a')                  # an unchecked copy: its check has not been started
STORAGE = '/workbench/storage/storage-drawer-3'
PICKED = '/workbench/part-picker?copy=' + '&copy='.join([uid('copy', '99103-1', 'a'), uid('copy', '99110-1', 'a'), uid('copy', '99118-1', 'a')])
OPEN_FOUND = "document.querySelector('[data-open=\"found-1\"]').click(); await new Promise(r => setTimeout(r, 400));"

SETTLE = 'await new Promise(r => setTimeout(r, 900));'   # lists build their rows and load their pictures after the page's load event

# stem: (path, width, max CSS height, script, destination)
PICTURES = {
    '1c-sets-desktop-1440': ('/collection/sets', 1440, 1020, None, (SITE, README)),
    '3a-matcher-phone-390': ('/workbench/match', 390, 844, None, (SITE,)),
    '3b-check-set-parts-phone-390': ('/workbench/check-parts', 390, 844, None, (SITE,)),
    '3e-start-phone-390': ('/workbench/check-parts/' + FRESH, 390, 844, None, (SITE,)),
    '3e-part-phone-390': ('/workbench/check-parts/%s?run=1' % STARTED, 390, 844, None, (SITE,)),
    '3e-finish-gaps-phone-390': ('/workbench/check-parts/%s?run=1' % GAPS, 390, 1100, None, (SITE,)),
    '3e-resume-phone-390': ('/workbench/check-parts/' + STARTED, 390, 844, None, (SITE,)),
    '3c-picker-sets-phone-390': ('/workbench/part-picker', 390, 844, None, (SITE,)),
    '3c-picker-sort-phone-390': (PICKED, 390, 844, None, (SITE,)),
    '3c-picker-pick-phone-390': (PICKED + '&pick=1', 390, 950, None, (SITE,)),
    '3c-picker-selector-phone-390': (PICKED + '&pick=1', 390, 844, OPEN_FOUND, (SITE,)),
    '4c-complete-sets-phone-390': ('/planning/complete-sets', 390, 844, None, (SITE,)),
    '12n-sources-phone-390': ('/manage/sync', 390, 1400, None, (SITE,)),
    '12b-count-what-arrived-desktop-1440': ('/workbench/orders/2', 1440, 1050, None, (SITE,)),
    '12c-list-and-detail-desktop-1440': (STORAGE, 1440, 1300, None, (SITE,)),
    '1d-set-detail-phone-390': ('/collection/item/set/99103-1?copy=' + uid('copy', '99103-1', 'a'), 390, 1800, None, (SITE,)),
    '3c-picker-pick-390': (PICKED + '&pick=1', 390, 950, None, (README,)),
}


def optimise(path: Path) -> None:
    """Palette PNG: the app's flat colours quantise without visible loss and weigh a fraction."""
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert('RGB')
        image.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--only', nargs='*', default=None)
    parser.add_argument('--out', default=None, help='write every picture flat into this folder instead of the repository')
    options = parser.parse_args(argv)
    chrome = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'chrome.py'), 'pinned'], capture_output=True, text=True)
    if chrome.returncode:
        print(chrome.stderr.strip())
        return 1
    chosen = {k: v for k, v in PICTURES.items() if options.only is None or k in options.only}
    with screen_gate.world('showcase', sorted({v[0] for v in chosen.values()})) as base, tempfile.TemporaryDirectory(prefix='bw-site-') as scratch:
        jobs, targets = [], []
        for stem, (path, width, limit, script, _) in chosen.items():
            for theme in ('light', 'dark'):
                out = Path(scratch) / f'{stem}-{theme}.png'
                jobs.append({'url': base + path, 'out': str(out), 'width': width, 'theme': theme, 'max': limit, 'script': (script or '') + SETTLE})
        spec = Path(scratch) / 'jobs.json'
        spec.write_text(json.dumps({'deterministic': True, 'now': screen_gate.FIXED_NOW.isoformat().replace('+00:00', 'Z'), 'jobs': jobs}))
        result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome.stdout.strip(), str(spec)], capture_output=True, text=True, timeout=1800)
        if result.returncode:
            print(result.stdout[-2000:] + result.stderr[-2000:])
            return 1
        for job in jobs:
            made = Path(job['out'])
            optimise(made)
            stem = made.name.rsplit('-', 1)[0]
            folders = [Path(options.out)] if options.out else list(chosen[stem][4])
            for folder in folders:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / made.name).write_bytes(made.read_bytes())
            print(made.name, made.stat().st_size)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
