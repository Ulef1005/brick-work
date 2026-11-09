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
TUTORIALS = ROOT / 'docs' / 'img' / 'tutorials'
STARTED = uid('copy', '99106-1', 'a')                # a check about 40 % answered (showcase.CHECKS)
GAPS = uid('copy', '99103-1', 'a')                   # a check answered to the end, with gaps
FRESH = uid('copy', '99113-1', 'a')                  # an unchecked copy: its check has not been started
STORAGE = '/workbench/storage/storage-drawer-3'
PICKED = '/workbench/part-picker?copy=' + '&copy='.join([uid('copy', '99103-1', 'a'), uid('copy', '99110-1', 'a'), uid('copy', '99118-1', 'a')])
ADD_SEARCH = "const s = document.querySelector('[data-search]'); s.value = 'Old Mill'; s.dispatchEvent(new Event('input', {bubbles: true})); await new Promise(r => setTimeout(r, 1500));"
CHOOSE_SETS = ("document.querySelector('[data-none]').click(); for (const n of ['99103-1', '99110-1', '99118-1']) "
               "document.querySelector('[data-number=' + JSON.stringify(n) + '] input').click(); await new Promise(r => setTimeout(r, 300));")
OPEN_FOUND = "document.querySelector('[data-open=\"found-1\"]').click(); await new Promise(r => setTimeout(r, 400));"

# Run in the page before each capture: the page must be settled, not just loaded. Lists build their rows and load their pictures after the load event,
# so wait (up to 15 s) for fonts, every stylesheet and every picture, then fail loudly on a broken picture or a missing stylesheet instead of
# photographing a half-loaded page.
SETTLE = """
await (document.fonts ? document.fonts.ready : null);
const waiting = () => {
  for (const i of document.images) i.loading = 'eager';
  return [...document.images].filter(i => !i.complete).length + [...document.querySelectorAll('link[rel=stylesheet]')].filter(l => !l.sheet).length;
};
await new Promise(r => setTimeout(r, 500));
const until = Date.now() + 15000;
while (waiting() && Date.now() < until) await new Promise(r => setTimeout(r, 50));
const broken = [...document.images].filter(i => (i.getAttribute('src') || '').includes('/manage/images/') && (!i.complete || i.naturalWidth === 0)).map(i => i.getAttribute('src'));
const bare = [...document.querySelectorAll('link[rel=stylesheet]')].filter(l => !l.sheet).map(l => l.getAttribute('href'));
if (waiting() || broken.length || bare.length) throw new Error('page not settled: ' + JSON.stringify({waiting: waiting(), broken, bare}));
await new Promise(r => setTimeout(r, 150));
"""

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
    # The two tutorials (docs/tutorials/): the Add search, Set Inspector, Complete sets, the wishlist and an order being counted, on the same invented world
    'tut-add-desktop-1440': ('/manage/add', 1440, 640, ADD_SEARCH, (TUTORIALS,)),
    'tut-inspect-list-phone-390': ('/workbench/check-parts', 390, 1100, None, (TUTORIALS,)),
    'tut-inspect-part-phone-390': ('/workbench/check-parts/%s?run=1' % STARTED, 390, 844, None, (TUTORIALS,)),
    'tut-inspect-end-phone-390': ('/workbench/check-parts/%s?run=1' % GAPS, 390, 1100, None, (TUTORIALS,)),
    'tut-complete-sets-phone-390': ('/planning/complete-sets', 390, 844, None, (TUTORIALS,)),
    'tut-wishlist-phone-390': ('/planning/wishlist', 390, 900, None, (TUTORIALS,)),
    'tut-order-count-phone-390': ('/workbench/orders/2?view=count', 390, 1500, None, (TUTORIALS,)),
    '12n-sources-phone-390': ('/manage/sync', 390, 1400, None, (SITE,)),
    '12b-count-what-arrived-desktop-1440': ('/workbench/orders/2', 1440, 1050, None, (SITE,)),
    '12c-list-and-detail-desktop-1440': (STORAGE, 1440, 1300, None, (SITE,)),
    '1d-set-detail-phone-390': ('/collection/item/set/99103-1?copy=' + uid('copy', '99103-1', 'a'), 390, 1800, None, (SITE,)),
    '3c-picker-pick-390': (PICKED + '&pick=1', 390, 950, None, (README,)),
    'bulk-storage-desktop-1440': (STORAGE, 1440, 900, None, (TUTORIALS,)),
    'bulk-runner-sets-phone-390': ('/workbench/part-picker', 390, 1700, CHOOSE_SETS, (TUTORIALS,)),
    'bulk-runner-order-phone-390': (PICKED, 390, 844, None, (TUTORIALS,)),
    'bulk-runner-found-phone-390': (PICKED + '&pick=1', 390, 844, OPEN_FOUND, (TUTORIALS,)),
    'bulk-matchmaker-desktop-1440': ('/workbench/match', 1440, 900, None, (TUTORIALS,)),
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
