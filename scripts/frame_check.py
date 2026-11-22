"""The app-vs-frame check (#492 part 2; design-builder 1.5.5, DESIGN-CHECK "the rendered app matches each approved frame").

    python3 scripts/frame_check.py [--band] [--only FOLDER ...]    render the approved frame HTML and the built app page in the same pinned Chrome
                                                                   and compare them; print one line per variant; exit 1 only on a failure that the
                                                                   band rule names (a report while a screen is being built: pass --report)
    python3 scripts/frame_check.py --count                          "design gate: N of M approved screens built", no rendering (for check.sh)

The frames are design's (design/screens-b/<folder>/<theme>-<width>.html, built by design/sources/b/b_frames.py); the app page is served from the `frames`
world of scripts/screen_gate.py. Both are captured by scripts/capture_screens.cjs with the same viewport, scale and clock, and compared HTML against HTML:
the committed frame PNGs come from another browser build and drift by about 5 % in sub-pixel text, so they are never the reference.

The band rule: up to 0.1 % of the pixels differing (a channel off by more than 16 of 255) passes; 0.1 % to 2 % passes with a one-line note in the PR naming the
differing regions (printed here); above 2 %, or a height difference above 10 % of the taller shot, fails. `--band` compares only the shell band (the top bar
and the sub row at 1440; the top bar at 390 and the tab bar at the foot), so the shell can be checked before the page bodies are rebuilt.
The pixel gate (screen_gate.py) stays out of check.sh (Deviation B11); this check does too, and only the count line runs there."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
if __name__ == '__main__':
    import venv_python
    venv_python.ensure()   # re-exec into the app's venv before anything imports the app (PIL, ...); only as a script, never on import
import screen_gate as gate  # noqa: E402
from brickwork.demo import frames  # noqa: E402

FRAMES = ROOT / 'design' / 'screens-b'
SCALE = 2
PASS, FAIL, HEIGHT_FAIL = 0.001, 0.02, 0.10
CHANNEL = 16
THEMES = ('light', 'dark')
SIZES = (1440, 390)

# folder -> (app path, world). A screen joins the table when its issue builds it (the data of its frame goes into the `frames` world then).
TARGETS = {'01-tools-and-admin': ('/manage/tools', 'frames'),
           '02-settings': ('/manage/settings', 'frames'),
           '03-find-instructions': ('/manage/instructions/find', 'frames-instructions'),
           '04-sets': ('/collection/sets', 'frames'),
           '05-sets-without-storage': ('/collection/sets', 'frames-no-storage'),
           '48-sets-pulled-copy': ('/collection/sets', 'frames-pulled'),
           '08-sets-empty': ('/collection/sets', 'frames-empty'),   # nothing owned, no keys, the catalogue loaded (brickwork/demo/frames.py EmptyLayer)
           '11-storage': ('/workbench/storage/storage-shelf-a2---town', 'frames-storage'),   # S-0002 selected, as the frame draws it
           '10-build-scout': ('/workbench/build-scout?min_percent=0', 'frames-scout'),
           '09-matchmaker': ('/workbench/matcher', 'frames-matcher'),
           '06-set-inspector': ('/workbench/check-parts/d1121673-830b-5aaa-80be-ee68396eec34?run=1', 'frames'),   # copy 2 of 7213-1 in its running check (brickwork/demo/frames.py INSPECTOR)
           '13-part-spotter': ('/workbench/part-to-inventory', 'frames'),   # the queue is the page's own (client-side): SCRIPT below feeds it the frame's three pieces
           '14-lot-sorter': ('/collection/lots/' + frames.real.LOT + '?detect=1', 'frames-lot'),   # the Flea market bag with its Set detection (brickwork/demo/frames_lot.py)
           '15-order-missing-parts': ('/planning/order-missing-parts', 'frames-order'),   # the three copies of frame 15 (brickwork/demo/frames_order.py)
           '16-orders': ('/workbench/orders/2?view=count', 'frames-orders'),   # 9900102 counting, 56 of 95 (brickwork/demo/frames_orders.py; the id is pinned in its test)
           '07-part-runner': (frames.runner_path(), 'frames')}   # the four incomplete copies as one run of 52 parts, on the 7th (brickwork/demo/frames.py RUNNER)
# JS run in the app's page before its capture (capture_screens.cjs `script`) when the frame draws a state the page keeps in the browser. Part Spotter's queue is
# filled through the page's own code: `fetch` answers the recognition calls with the frame's candidates, and the photos go in through the file input.
SPOTTER_SEED = r"""
const png = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII='), c => c.charCodeAt(0));
const cid = name => JSON.parse(document.querySelector('#bw-inventory').dataset.colours).find(c => c.name === name).color_id;
const own = {total: 14, colours: [{color_id: cid('Light Bluish Gray'), quantity: 8}, {color_id: cid('Red'), quantity: 4}, {color_id: cid('White'), quantity: 2}], needed_count: 1, needed_by: [],
             text: 'You have 14 in 3 colours: Light Bluish Gray 8 (S-0003), Red 4, White 2'};
const replies = [{name: 'Brick 1 x 1', item_no: '3005', score: 0.91, image: null}, {name: 'Brick 1 x 6', item_no: '3009', score: 0.87, image: null, owned_summary: own}];
const realFetch = window.fetch; let call = 0;
window.fetch = (url, options) => /\/detect$/.test(String(url)) ? (call < replies.length ? Promise.resolve(new Response(JSON.stringify({candidates: [replies[call++]], token: 't' + call, unresolved: []}), {status: 200, headers: {'Content-Type': 'application/json'}})) : new Promise(() => {})) : realFetch(url, options);
const root = document.querySelector('#bw-inventory'), pause = ms => new Promise(r => setTimeout(r, ms));
const add = async () => { const input = root.querySelector('[data-file]'), data = new DataTransfer(); data.items.add(new File([png], 'p.png', {type: 'image/png'})); input.files = data.files; input.dispatchEvent(new Event('change', {bubbles: true})); await pause(300); };
const pick = name => [...root.querySelectorAll('.inv-swatch-row button')].find(b => b.textContent.trim() === name).click();
await add(); pick('Red'); root.querySelector('[data-confirm]').click(); await pause(100);
await add(); pick('Light Bluish Gray'); await pause(100);
await add(); await pause(100);
root.querySelectorAll('.scan-row')[1].click(); await pause(300); root.querySelector('[data-notice]').hidden = true; root.querySelector('[data-camera-label]').textContent = 'Back camera'; { const take = root.querySelector('[data-capture]'); take.disabled = false; take.textContent = 'Take picture'; }
"""
SCRIPT = {'13-part-spotter': SPOTTER_SEED}
# A frame whose phone drawing is another page than its desktop one: the storage list opens as the page on a phone (a storage's own screen only when one is chosen).
PHONE_PATH = {'11-storage': '/workbench/storage',
              '14-lot-sorter': '/collection/lots/' + frames.real.LOT + '/pull/11/make-copy'}   # frame 14 at 390 is the Make a copy confirm over 7938-1's pull list (catalogue item 11)
# Frames that draw one screen as the device shows it (the frame's own size, the rest of the page cut off, the phone's tab bar at the foot of that size): the
# frame and app are both captured as one viewport (capture_screens.cjs `sheet_below`), not grown to the whole height of their scrollable content. A frame that draws the whole page is not listed.
VIEWPORT = {'16-orders', '15-order-missing-parts', '14-lot-sorter', '13-part-spotter', '11-storage', '10-build-scout', '08-sets-empty', '01-tools-and-admin', '02-settings', '03-find-instructions', '09-matchmaker', '04-sets', '05-sets-without-storage', '48-sets-pulled-copy', '06-set-inspector', '07-part-runner'}
# The frame is an excerpt: 04-sets at 390 draws two of the three tiles its S-0002 tape counts and cuts the rest. Design's rule (2026-11-20): compare down to the
# bottom of the drawn tile row (CSS px from the top); the app shows all three tiles, so what lies below that row is not compared.
CROP_BELOW = {('01-tools-and-admin', 390): 757, ('02-settings', 390): 714, ('02-settings', 1440): 732, ('09-matchmaker', 390): 710, ('04-sets', 390): 731, ('05-sets-without-storage', 390): 657, ('48-sets-pulled-copy', 390): 731}   # frame 48 is built on frame 04: the same two tiles are drawn at 390
# Screens whose PAGE BODY is built to the frame (their issue sets it): until then a target serves only the shell-band check, and the count does not count it.
# The viewport height of a frame that is taller than the usual one (CSS px): frame 48 draws the rows of the pulled copies below the first screen (its frame-size is 1440 x 1052).
TALL = {('48-sets-pulled-copy', 1440): 1052, ('07-part-runner', 1440): 1000, ('13-part-spotter', 1440): 1000, ('14-lot-sorter', 1440): 1006, ('16-orders', 1440): 1000}
BODY_BUILT: set[str] = {'16-orders', '15-order-missing-parts', '14-lot-sorter', '13-part-spotter', '11-storage', '10-build-scout', '08-sets-empty', '01-tools-and-admin', '02-settings', '03-find-instructions', '09-matchmaker', '04-sets', '05-sets-without-storage', '48-sets-pulled-copy', '06-set-inspector', '07-part-runner'}


def frame_file(folder: str, theme: str, width: int) -> Path:
    return FRAMES / folder / f'{theme}-{width}.html'


def band_rows(width: int) -> list[tuple[str, int]]:
    """The shell band as (where, CSS px): '' + top rows measured from the top of each shot, 'foot' rows measured up from the bottom of each shot. At 1440
    the top bar and the sub row (heights read from b_frames.py by scripts/b_prime_css.py); at 390 the top bar and sub row, and the tab bar at the foot."""
    from scripts import b_prime_css
    h = b_prime_css.shell_heights()
    if width >= 1100:
        return [('top', h['top'] + h['sub'])]
    return [('top', h['ptop'] + h['psub']), ('foot', h['tabbar'])]


def diff_share(a, b):
    """(differing pixels, total, mask) of two equally sized RGB images; a pixel differs when a channel is off by more than CHANNEL."""
    from PIL import ImageChops
    r, g, bl = ImageChops.difference(a, b).split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), bl).point(lambda v: 255 if v > CHANNEL else 0)
    return mask.histogram()[255], a.width * a.height, mask


def regions_of(mask, offset: int = 0) -> list[str]:
    """The 50 px strips (CSS px, from `offset`) where more than 0.5 % of the pixels differ: the regions a PR note names."""
    found, step = [], 50 * SCALE
    for y in range(0, mask.height, step):
        strip = mask.crop((0, y, mask.width, min(mask.height, y + step)))
        if strip.histogram()[255] / (strip.width * strip.height) > 0.005:
            found.append(f'{offset + y // SCALE}-{offset + (y + strip.height) // SCALE} px')
    return found


def compare(frame: Path, app: Path, width: int, band: bool, viewport: int = 0, limit: int = 0) -> dict:
    """`viewport`: the frame's viewport height in CSS px. A frame draws its tab bar at the foot of that viewport, the page's own at the foot of the grown capture."""
    from PIL import Image
    with Image.open(frame) as a, Image.open(app) as b:
        a, b = a.convert('RGB'), b.convert('RGB')
        if a.width != b.width:
            return {'ratio': 1.0, 'dh': 0, 'tall': max(a.height, b.height), 'regions': ['width differs']}
        tall, short = max(a.height, b.height), min(a.height, b.height)
        differing = total = 0
        regions = []
        if not band:
            rows = min(short, limit * SCALE) if 0 < limit else short   # CROP_BELOW: only the rows above `limit` CSS px are compared; the heights are still checked whole
            d, t, mask = diff_share(a.crop((0, 0, a.width, rows)), b.crop((0, 0, b.width, rows)))
            differing, total, regions = d, t, regions_of(mask)
            if 0 < limit:   # the excerpt's cut does not hide the phone tab bar: its foot band is still compared, from each shot's own bottom
                for where, px in band_rows(width):
                    if where == 'foot':
                        foot, tab = (viewport * SCALE if viewport else a.height), px * SCALE
                        d, t, mask = diff_share(a.crop((0, foot - tab, a.width, foot)), b.crop((0, b.height - tab, b.width, b.height)))
                        differing, total, regions = differing + d, total + t, regions + [f'foot {r}' for r in regions_of(mask)]
        else:
            for where, px in band_rows(width):
                rows = px * SCALE
                if where == 'top':
                    d, t, mask = diff_share(a.crop((0, 0, a.width, rows)), b.crop((0, 0, b.width, rows)))
                    regions += [f'top {r}' for r in regions_of(mask)]
                else:
                    foot = (viewport * SCALE if viewport else a.height)
                    d, t, mask = diff_share(a.crop((0, foot - rows, a.width, foot)), b.crop((0, b.height - rows, b.width, b.height)))
                    regions += [f'foot {r}' for r in regions_of(mask)]
                differing += d
                total += t
        return {'ratio': differing / total if total else 0.0, 'dh': 0 if band else (tall - short) // SCALE, 'tall': tall // SCALE, 'regions': regions}


def verdict(result: dict) -> str:
    if result['tall'] and result['dh'] / result['tall'] > HEIGHT_FAIL:
        return 'FAIL'
    if result['ratio'] > FAIL:
        return 'FAIL'
    if result['ratio'] > PASS or result['dh']:
        return 'NOTE'
    return 'ok'


def count_line() -> str:
    """Approved screens = the numbered folders of design/screens-b (design's record; 00-* are component sheets); built = those with a TARGETS entry."""
    screens = sorted(p.name for p in FRAMES.iterdir() if p.is_dir() and p.name[:2].isdigit() and not p.name.startswith('00'))
    built = [f for f in screens if f in TARGETS and f in BODY_BUILT]
    return f'design gate: {len(built)} of {len(screens)} approved screens built'


def run(only: list[str], band: bool, report: bool, keep: str = '') -> int:
    chrome = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'chrome.py'), 'pinned'], capture_output=True, text=True)
    if chrome.returncode:
        print(chrome.stderr.strip())
        return 1
    chrome = chrome.stdout.strip()
    lines, worst = [], 'ok'
    unknown = [name for name in only if name not in TARGETS]
    if unknown:
        print('frame check: no such target: ' + ', '.join(unknown) + ' (known: ' + ', '.join(TARGETS) + ')')
        return 2
    with tempfile.TemporaryDirectory(prefix='bw-frames-') as scratch:
        for folder, (path, world) in TARGETS.items():
            if only and folder not in only:
                continue
            with gate.world(world, [path, *([PHONE_PATH[folder]] if folder in PHONE_PATH else [])]) as base, tempfile.TemporaryDirectory(prefix='bw-jobs-') as jobs_dir:
                jobs, pairs = [], []
                for width in SIZES:
                    for theme in THEMES:
                        frame_png = Path(scratch) / folder / f'frame-{theme}-{width}.png'
                        app_png = Path(scratch) / folder / f'app-{theme}-{width}.png'
                        height = TALL.get((folder, width), {1440: 900, 390: 844}[width])
                        common = {'width': width, 'height': height, 'theme': theme, 'scale': SCALE, 'max': 3000, **({'sheet_below': 100000} if folder in VIEWPORT else {})}
                        jobs.append({'url': frame_file(folder, theme, width).as_uri(), 'out': str(frame_png), **common})
                        jobs.append({'url': base + (PHONE_PATH[folder] if width == 390 and folder in PHONE_PATH else path), 'out': str(app_png), 'wait': 'main', **({'script': SCRIPT[folder]} if folder in SCRIPT else {}), **common})
                        pairs.append((width, theme, frame_png, app_png))
                gate.run_jobs(jobs, jobs_dir, chrome)
            for width, theme, frame_png, app_png in pairs:
                if keep:   # the captures, for looking at (a folder; nothing else reads them)
                    import shutil
                    Path(keep).mkdir(parents=True, exist_ok=True)
                    for png in (frame_png, app_png):
                        shutil.copyfile(png, Path(keep) / f'{folder}-{png.name}')
                result = compare(frame_png, app_png, width, band, TALL.get((folder, width), {1440: 900, 390: 844}[width]), CROP_BELOW.get((folder, width), 0))
                state = verdict(result)
                worst = 'FAIL' if 'FAIL' in (worst, state) else 'NOTE' if 'NOTE' in (worst, state) else 'ok'
                where = f' regions {", ".join(result["regions"][:6])}' if state != 'ok' and result['regions'] else ''
                lines.append(f'{state:4} {folder} {theme} {width}{" (shell band)" if band else ""}: {result["ratio"]:.3%}'
                             f'{f", height differs by {result["dh"]} px" if result["dh"] else ""}{where}')
    print('\n'.join(lines))
    print(f'frame check: worst {worst}')
    return 1 if worst == 'FAIL' and not report else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--band', action='store_true', help='compare only the shell band')
    parser.add_argument('--report', action='store_true', help='print the result and exit 0 (while a screen is being built)')
    parser.add_argument('--count', action='store_true', help='print the "N of M approved screens built" line, no rendering')
    parser.add_argument('--only', nargs='*', default=[])
    parser.add_argument('--keep', default='', help='copy the captures into this folder')
    args = parser.parse_args(argv)
    if args.count:
        print(count_line())
        return 0
    return run(args.only, args.band, args.report, args.keep)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
