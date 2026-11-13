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
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import screen_gate  # noqa: E402
from brickwork.demo.showcase import LOT, LOT_SETS, uid  # noqa: E402

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
LOT_PAGE = '/collection/lots/' + LOT
BEST, SECOND = LOT_SETS[0][0], LOT_SETS[1][0]                      # the Flea market bag's best and second candidate (brickwork/demo/showcase.py)


def lot_link(pattern, near=None):
    """A path that is only known once the world is built (a stock line's or a catalogue item's id): the first link of the lot page matching `pattern`."""
    def find(base):
        page = urllib.request.urlopen(base + LOT_PAGE + '?detect=1&min_score=0').read().decode()
        scope = page[page.index(near):] if near else page
        return re.search(r'href="(%s)"' % pattern, scope).group(1).replace('&amp;', '&')
    return find


def pull(number, tail=''):
    """The pull list of the set `number` for the lot: its catalogue id is the number in the card's links, found by the set's name in the card."""
    def find(base):
        page = urllib.request.urlopen(base + LOT_PAGE + '?detect=1&min_score=0').read().decode()
        card = page[page.index('class="bd-cand'):]
        found = re.search(r'%s.*?href="(%s/pull/\d+)"' % (re.escape(number), re.escape(LOT_PAGE)), card, re.S)
        return found.group(1) + tail
    return find


def scout_set(number):
    """Build Scout with one set selected (its panel beside the list): the set's catalogue id comes from its pull list link."""
    find = pull(number)
    return lambda base: '/workbench/build-scout?min_percent=10&set=%s' % find(base).rsplit('/', 1)[1]


def variant_change(old, new):
    """Change variant of the part `old` with the part `new` chosen (both share BrickLink's number of the catalogue): the items' catalogue ids come from their number's redirect."""
    def find(base):
        ids = [urllib.request.urlopen(base + '/collection/item/part/' + n).geturl().split('?')[0].rsplit('/', 1)[1] for n in (old, new)]
        return '/collection/item/%s/change-variant?target=%s' % tuple(ids)
    return find


# Hide what comes before the Set detection section, so that the clip (which always starts at the top of the page) begins at it.
SHOW_DETECTION = ("const section = document.querySelector('#set-detection'); "
                  "for (let sibling = section.previousElementSibling; sibling; sibling = sibling.previousElementSibling) if (sibling.tagName !== 'H1') sibling.style.display = 'none';")
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
    '3e-start-phone-390': ('/workbench/check-parts/' + FRESH, 390, 844, None, (SITE,)),
    '3e-part-phone-390': ('/workbench/check-parts/%s?run=1' % STARTED, 390, 844, None, (SITE,)),
    '3e-finish-gaps-phone-390': ('/workbench/check-parts/%s?run=1' % GAPS, 390, 1100, None, (SITE,)),
    '3c-picker-sets-phone-390': ('/workbench/part-picker', 390, 844, None, (SITE,)),
    '3c-picker-pick-phone-390': (PICKED + '&pick=1', 390, 950, None, (SITE,)),
    '4c-complete-sets-phone-390': ('/planning/complete-sets', 390, 844, None, (SITE,)),
    # The two tutorials (docs/tutorials/): the Add search, Set Inspector, Complete sets, the wishlist and an order being counted, on the same invented world
    '12b-count-what-arrived-desktop-1440': ('/workbench/orders/2', 1440, 1050, None, (SITE,)),
    '12c-list-and-detail-desktop-1440': (STORAGE, 1440, 1300, None, (SITE,)),
    '1d-set-detail-phone-390': ('/collection/item/set/99103-1?copy=' + uid('copy', '99103-1', 'a'), 390, 1800, None, (SITE,)),
    '3c-picker-pick-390': (PICKED + '&pick=1', 390, 950, None, (README,)),
    'bulk-storage-desktop-1440': (STORAGE, 1440, 900, None, (TUTORIALS,)),
    'bulk-runner-sets-phone-390': ('/workbench/part-picker', 390, 1700, CHOOSE_SETS, (TUTORIALS,)),
    'bulk-runner-order-phone-390': (PICKED, 390, 844, None, (TUTORIALS,)),
    'bulk-runner-found-phone-390': (PICKED + '&pick=1', 390, 844, OPEN_FOUND, (TUTORIALS,)),
    'bulk-matchmaker-desktop-1440': ('/workbench/match', 1440, 900, None, (TUTORIALS,)),
    # The tutorial for the new functions (docs/tutorials/): a bag of loose parts, the sets it may come from, the sticker, the pull list; Build Scout; ordering what is missing; a part's variant
    'lot-detect-desktop-1440': (LOT_PAGE + '?detect=1&ignore_common=1#set-detection', 1440, 1500, SHOW_DETECTION, (TUTORIALS,)),
    'lot-sticker-chooser-desktop-1440': (lot_link(re.escape(LOT_PAGE) + r'/sticker/[0-9a-f]+[^"]*', None), 1440, 900, None, (TUTORIALS,)),
    'lot-pull-list-phone-390': (pull(BEST, '?show=all'), 390, 1700, None, (TUTORIALS,)),
    'lot-pull-confirm-phone-390': (pull(BEST, '/make-copy'), 390, 844, None, (TUTORIALS,)),
    'scout-list-desktop-1440': ('/workbench/build-scout?min_percent=10', 1440, 900, None, (TUTORIALS,)),
    'scout-set-desktop-1440': (scout_set(SECOND), 1440, 900, None, (TUTORIALS,)),
    'variant-change-desktop-1440': (variant_change('4287c', '4287b'), 1440, 1000, None, (TUTORIALS,)),
    'order-missing-desktop-1440': ('/planning/order-missing-parts', 1440, 1000, None, (TUTORIALS,)),
    'order-missing-review-phone-390': ('/planning/order-missing-parts?step=review', 390, 1500, None, (TUTORIALS,)),
}


def callouts(*marks):
    """JS for a job's `after`: a clay ring round each element and a numbered disc on its top left corner, drawn from the element's box (App Docs Standard,
    screenshot standard). `marks` are (selector, number) pairs. The disc is the ink of the page with paper digits and, in dark mode, the page's light
    ink with dark digits: the tokens do the inversion. Nothing here depends on timing: the boxes are read after the fonts are loaded and the viewport has its final size."""
    return """
await document.fonts.ready;
const marks = %s;
for (const [selector, number] of marks) {
  const el = document.querySelector(selector);
  if (!el) throw new Error('call-out target missing: ' + selector);
  const r = el.getBoundingClientRect(), x = r.left + scrollX, y = r.top + scrollY;
  const ring = document.createElement('div');
  ring.style.cssText = `position:absolute;left:${x - 4}px;top:${y - 4}px;width:${r.width + 8}px;height:${r.height + 8}px;box-sizing:border-box;border:2px solid var(--tw-accent);border-radius:10px;pointer-events:none;z-index:2147483646`;
  const disc = document.createElement('div');
  disc.textContent = String(number);
  disc.style.cssText = `position:absolute;left:${x - 16}px;top:${y - 16}px;width:24px;height:24px;border-radius:50%%;background:var(--tw-text);color:var(--tw-bg);font:600 13px/24px var(--tw-font, sans-serif);text-align:center;pointer-events:none;z-index:2147483647`;
  document.body.append(ring, disc);
}
""" % json.dumps(marks)


def tag_text(selector, text, attr='data-shot-area'):
    """JS for a job's `after`: mark the first element matching `selector` whose text is `text` with `attr` (a link or button that has no id of its own)."""
    return (f"{{ const named = [...document.querySelectorAll({json.dumps(selector)})].find(e => (e.textContent || '').replace(/\\s+/g, ' ').trim() === {json.dumps(text)});\n"
            f"if (!named) throw new Error('tag_text: no ' + {json.dumps(selector)} + ' with the text ' + {json.dumps(text)}); named.setAttribute({json.dumps(attr)}, ''); }}\n")


# The tutorial shots that follow the reader's screen (App Docs Standard, screenshot standard): each exists as a desktop shot (a 1024 px viewport at device
# scale 2, cut to the area the step is about) and as a phone shot, each in light and dark, with numbered call-outs. name: (path, script, {layout: (width, crop, marks)}).
# The file is `tut-<name>-<layout>-<width>-<theme>.png`. `crop` is a list of selectors (the picture is cut to their union), `marks` are (selector, number) pairs.
def no_placeholders(*selectors):
    """JS for a job's `after`, before the call-outs: fail when a missing-picture tile or a picture that did not load is inside the area the shot is cut to
    (the union of `selectors`, plus the crop padding). No screenshot of the docs shows a placeholder (Ulf, 2026-11-13); the message names the item of each
    tile (its row's text) so the picture can be added. The page's own `no_tiles` check finds the list tiles; the Set Inspector and Part Runner draw
    their own 'No image' tile, found here by its text; the order and ledger pages draw .bw-picture boxes."""
    return """
await document.fonts.ready;
const areas = %s.flatMap(s => {
  const rects = [...document.querySelectorAll(s)].map(e => e.getBoundingClientRect()).filter(r => r.width > 0 && r.height > 0);
  if (!rects.length) throw new Error('no_placeholders: the selector ' + s + ' matches nothing visible');
  return rects;
});
if (!areas.length) throw new Error('no_placeholders: the area matches nothing');
const pad = 28, box = {l: Math.min(...areas.map(a => a.left)) - pad, t: Math.min(...areas.map(a => a.top)) - pad, r: Math.max(...areas.map(a => a.right)) + pad, b: Math.max(...areas.map(a => a.bottom)) + pad};
const inside = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.right > box.l && r.left < box.r && r.bottom > box.t && r.top < box.b; };
const tiles = [...document.querySelectorAll('.bc-no-image,.bw-no-image,.bc-picture:not(:has(img)),.bw-picture:not(:has(img))')].concat(
  [...document.querySelectorAll('body *')].filter(e => !e.children.length && /^No image$/i.test((e.textContent || '').trim())));
const broken = [...document.images].filter(i => inside(i) && (!i.complete || !i.naturalWidth));
const named = [...tiles.filter(inside), ...broken].map(e => { const row = e.closest('article,li,tr,form,[data-row]') || e.parentElement.parentElement; return (row.innerText || e.getAttribute('src') || '').replace(/\\s+/g, ' ').trim().slice(0, 130); });
if (named.length) throw new Error('no_placeholders: ' + named.length + ' placeholder(s): ' + [...new Set(named)].join(' | '));
""" % json.dumps(list(selectors))


def tag_nth(selector, n, attr='data-shot-area', closest=None):
    """JS for a job's `after`: mark the n-th (1-based) element matching `selector` (or its nearest ancestor matching `closest`) with `attr`,
    so a crop or a call-out can name it ("the first row")."""
    return (f"{{ let hit = [...document.querySelectorAll({json.dumps(selector)})][{n - 1}]; if (!hit) throw new Error('tag_nth: no match for ' + {json.dumps(selector)});\n"
            f"if ({json.dumps(closest)}) {{ hit = hit.closest({json.dumps(closest)}); if (!hit) throw new Error('tag_nth: no ' + {json.dumps(closest)} + ' around ' + {json.dumps(selector)}); }}\n"
            f"hit.setAttribute({json.dumps(attr)}, ''); }}\n")


# The tutorial shots that follow the reader's screen (App Docs Standard, screenshot standard): each exists as a desktop shot (a 1024 px viewport at device
# scale 2, cut to the area the step is about) and as a phone shot, each in light and dark, with numbered call-outs, made in the real-sets world (no
# placeholders, Ulf 2026-11-13). name: (path, script, {layout: (width, crop selectors, marks, `after` code run first)}). The file is
# `tut-<name>-<layout>-<width>-<theme>.png`; a mark is a (selector, number) pair.
REAL = {'real': lambda number: uid('copy', number, 'a')}['real']
REAL_STARTED, REAL_GAPS = REAL('8043-1'), REAL('7938-1')   # a check about 40 % answered; a check answered to the end, with gaps
LAYOUT_SCALE = {'desktop': 2, 'phone': 2}
assert 'Old Mill' in ADD_SEARCH
TUTORIAL_SHOTS = {
    'add': ('/manage/add', ADD_SEARCH.replace('Old Mill', 'Medieval'), {
        layout: (width, ['.bw-add-search-field', '.bw-add-select'], [('.bw-add-search-field', 1), ('.bw-add-select', 2)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'inspect-part': ('/workbench/check-parts/%s?run=1' % REAL_STARTED, None, {
        layout: (width, ['[data-stage]'], [('[data-stage] img', 1), ('[data-action=answer]', 2), ('[data-action=missing]', 3), ('[data-action=skip]', 4)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'inspect-end': ('/workbench/check-parts/%s?run=1' % REAL_GAPS, None, {
        layout: (width, ['[data-stage] h2', '[data-shot-area]'], [('[data-stage] h2', 1), ('[data-action=found_one]', 2)], tag_nth('[data-action=found_one]', 1, closest='.check-miss') + "[...document.querySelectorAll('.check-miss')].slice(1).forEach(e => { e.style.display = 'none'; });\n")
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'inspect-list': ('/workbench/check-parts', None, {
        layout: (width, ['[data-copy-section=progress]', '[data-copy-section=unchecked]'],
                 [('[data-copy-section=progress] .check-copy', 1), ('[data-copy-section=unchecked] .check-section-title', 2)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'wishlist': ('/planning/wishlist', None, {
        layout: (width, ['h1', '[data-shot-area]'],
                 [('a.button[aria-current=page]', 1), ('[data-wl-open=bw-manage-wishlists]', 2), ('[data-wl-open=bw-export-wishlist]', 3), ('[data-shot-print]', 4)],
                 tag_text('a.button', 'Download CSV') + tag_text('a.button', 'Print', 'data-shot-print'))
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'order-count': ('/workbench/orders/2?view=count', None, {
        layout: (width, ['[data-order-panel=count] h2', '[data-shot-area]'], [('[data-order-panel=count] h2', 1), ('.order-count-row', 2)],
                 tag_nth('.order-count-row', 3))
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'complete-sets': ('/planning/complete-sets', None, {
        layout: (width, ['[data-bp-row]:first-of-type'], [('[data-bp-row]:first-of-type', 1), ('[data-bp-pin]', 2), ('.bp-repair-details summary', 3)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
}
EXTRAS, WORLD_OF = {}, {}
for _name, (_path, _script, _layouts) in TUTORIAL_SHOTS.items():
    for _layout, (_width, _crop, _marks, _prepare) in _layouts.items():
        _stem = f'tut-{_name}-{_layout}-{_width}'
        PICTURES[_stem] = (_path, _width, 3000, _script, (TUTORIALS,))
        WORLD_OF[_stem] = 'real'
        EXTRAS[_stem] = {'scale': LAYOUT_SCALE[_layout], 'crop': _crop, 'crop_pad': 28, 'after': _prepare + no_placeholders(*_crop) + callouts(*_marks)}


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
    with tempfile.TemporaryDirectory(prefix='bw-site-') as scratch:
        for world in dict.fromkeys(WORLD_OF.get(stem, 'showcase') for stem in chosen):
            stems = [stem for stem in chosen if WORLD_OF.get(stem, 'showcase') == world]
            with screen_gate.world(world, sorted({chosen[stem][0] for stem in stems if isinstance(chosen[stem][0], str)})) as base:
                jobs = []
                for stem in stems:
                    path, width, limit, script, _ = chosen[stem]
                    path = path(base) if callable(path) else path
                    for theme in ('light', 'dark'):
                        jobs.append({'url': base + path, 'out': str(Path(scratch) / f'{stem}-{theme}.png'), 'width': width, 'theme': theme, 'max': limit,
                                     'script': (script or '') + SETTLE, **EXTRAS.get(stem, {})})
                spec = Path(scratch) / f'jobs-{world}.json'
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
