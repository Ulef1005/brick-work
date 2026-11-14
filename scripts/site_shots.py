"""Pictures of the BUILT app for the README and the Pages site (replacing the design project's mock-ups).

    python scripts/site_shots.py [--only STEM ...] [--out DIR]

Renders the app on two invented worlds: the site's pictures on the 'real' world (seven real sets with Rebrickable's pictures around an invented
collection, brickwork/demo/real.py, #332), the README's and the older tutorial shots' on the 'showcase' world (the screen gate's world plus the richer demo
layer, brickwork/demo/showcase.py), the tutorial shots that follow the reader's screen on the real world too (WORLD_OF). Both use the pinned Chrome for Testing, at 1440 (desktop) and 390 (phone, drawn at twice the pixels), light and dark, with the clock fixed. Each picture is
written under the file name the page already uses (`<stem>-light.png`, `<stem>-dark.png`), clipped to a sensible height and optimised.
These are not gate baselines. A site picture fails its capture when the page shows a missing-picture tile (`no_tiles`): the site never shows a placeholder.
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
from brickwork.demo import real  # noqa: E402
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


def pull(number, tail='', lot_page=LOT_PAGE):
    """The pull list of the set `number` for the lot: its catalogue id is the number in the card's links, found by the set's name in the card."""
    def find(base):
        page = urllib.request.urlopen(base + lot_page + '?detect=1&min_score=0').read().decode()
        card = page[page.index('class="bd-cand'):]
        found = re.search(r'%s.*?href="(%s/pull/\d+)"' % (re.escape(number), re.escape(lot_page)), card, re.S)
        return found.group(1) + tail
    return find


def first_pull(lot_page, tail=''):
    """The pull list of the lot's best candidate."""
    def find(base):
        page = urllib.request.urlopen(base + lot_page + '?detect=1&min_score=0').read().decode()
        card = page[page.index('class="bd-cand'):]
        found = re.search(r'href="(%s/pull/\d+)"' % re.escape(lot_page), card)
        if not found:
            raise SystemExit(f'first_pull: no pull list link in the first candidate of {base + lot_page}')
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
const until = performance.now() + 15000;
while (waiting() && performance.now() < until) await new Promise(r => setTimeout(r, 50));
const broken = [...document.images].filter(i => (i.getAttribute('src') || '').includes('/manage/images/') && (!i.complete || i.naturalWidth === 0)).map(i => i.getAttribute('src'));
const bare = [...document.querySelectorAll('link[rel=stylesheet]')].filter(l => !l.sheet).map(l => l.getAttribute('href'));
if (waiting() || broken.length || bare.length) throw new Error('page not settled: ' + JSON.stringify({waiting: waiting(), broken, bare}));
await new Promise(r => setTimeout(r, 150));
"""

# stem: (path, width, max CSS height, script, destination)
PICTURES = {
    '1c-sets-desktop-1440': ('/collection/sets', 1440, 1020, None, (README,)),
    # The two tutorials (docs/tutorials/): the Add search, Set Inspector, Complete sets, the wishlist and an order being counted, on the same invented world
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


# The site shows no part tile without a picture: Build Scout without its side panel, Set detection with the candidates collapsed.
HIDE_PANEL = "document.querySelector('.bs-aside').remove();"
COLLAPSE_CANDIDATES = "document.querySelectorAll('.bd-cand details').forEach(d => { d.open = false; });"
R_FRESH = real.uid('copy', '21028-1', 'a')
R_STARTED = real.uid('copy', '8043-1', 'a')
R_PICKED = '/workbench/part-picker?copy=' + '&copy='.join(real.uid('copy', n, 'a') for n in ('7938-1', '10210-1', '7213-1'))
R_LOT_PAGE = '/collection/lots/' + real.LOT

SITE_PICTURES = {
    '1c-sets-desktop-1440': ('/collection/sets', 1440, 1020, None, (SITE,)),
    '3a-matcher-phone-390': ('/workbench/match', 390, 844, None, (SITE,)),
    '3e-start-phone-390': ('/workbench/check-parts/' + R_FRESH, 390, 844, None, (SITE,)),
    '3e-part-phone-390': ('/workbench/check-parts/%s?run=1' % R_STARTED, 390, 844, None, (SITE,)),
    '3c-picker-sets-phone-390': ('/workbench/part-picker', 390, 844, None, (SITE,)),
    '3c-picker-pick-phone-390': (R_PICKED + '&pick=1', 390, 950, None, (SITE,)),
    '12b-count-what-arrived-desktop-1440': ('/workbench/orders/2', 1440, 1050, None, (SITE,)),
    '12c-list-and-detail-desktop-1440': ('/workbench/storage/storage-shelf-b', 1440, 900, None, (SITE,)),
    'scout-list-desktop-1440': ('/workbench/build-scout?min_percent=10', 1440, 900, HIDE_PANEL, (SITE,)),
    'lot-detect-desktop-1440': (R_LOT_PAGE + '?detect=1&ignore_common=1#set-detection', 1440, 900, SHOW_DETECTION + COLLAPSE_CANDIDATES, (SITE,)),
    'lot-pull-confirm-phone-390': (first_pull(R_LOT_PAGE, '/make-copy'), 390, 844, None, (SITE,)),
}


def callouts(*marks):
    """JS for a job's `after`: a clay ring round each element and a numbered disc on its top left corner, drawn from the element's box (App Docs Standard,
    screenshot standard). `marks` are (selector, number) pairs, or (selector, number, 'right') to put the disc after the box, centred, or (selector, number, 'above') to put it above the box, when its top left corner would cover text. The disc is the ink of the page with paper digits and, in dark mode, the page's light
    ink with dark digits: the tokens do the inversion. Nothing here depends on timing: the boxes are read after the fonts are loaded and the viewport has its final size. A mark whose element sits inside a modal dialog (shown with showModal) is drawn inside that dialog, because the top layer hides body-level overlays."""
    return """
await document.fonts.ready;
const marks = %s;
for (const [selector, number, side] of marks) {
  const el = document.querySelector(selector);
  if (!el) throw new Error('call-out target missing: ' + selector);
  const host = el.closest('dialog:modal') || document.body;
  const hostRect = host === document.body ? null : host.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  const x = hostRect ? r.left - hostRect.left + host.scrollLeft : r.left + scrollX;
  const y = hostRect ? r.top - hostRect.top + host.scrollTop : r.top + scrollY;
  const ring = document.createElement('div');
  ring.style.cssText = `position:absolute;left:${x - 4}px;top:${y - 4}px;width:${r.width + 8}px;height:${r.height + 8}px;box-sizing:border-box;border:2px solid var(--tw-accent);border-radius:10px;pointer-events:none;z-index:2147483646`;
  const disc = document.createElement('div');
  disc.textContent = String(number);
  disc.style.cssText = `position:absolute;left:${side === 'right' ? x + r.width + 8 : side === 'above' ? x - 4 : x - 16}px;top:${side === 'right' ? y + (r.height - 24) / 2 : side === 'above' ? y - 30 : y - 16}px;width:24px;height:24px;border-radius:50%%;background:var(--tw-text);color:var(--tw-bg);font:600 13px/24px var(--tw-font, sans-serif);text-align:center;pointer-events:none;z-index:2147483647`;
  host.append(ring, disc);
}
""" % json.dumps(marks)


def tag_text(selector, text, attr='data-shot-area'):
    """JS for a job's `after`: mark the first element matching `selector` whose text is `text` with `attr` (a link or button that has no id of its own)."""
    return (f"{{ const named = [...document.querySelectorAll({json.dumps(selector)})].find(e => (e.textContent || '').replace(/\\s+/g, ' ').trim() === {json.dumps(text)});\n"
            f"if (!named) throw new Error('tag_text: no ' + {json.dumps(selector)} + ' with the text ' + {json.dumps(text)}); named.setAttribute({json.dumps(attr)}, ''); }}\n")


# The tutorial shots that follow the reader's screen (App Docs Standard, screenshot standard): each exists as a desktop shot (a 1024 px viewport at device
# scale 2, cut to the area the step is about) and as a phone shot, each in light and dark, with numbered call-outs. name: (path, script, {layout: (width, crop, marks)}).
# The file is `tut-<name>-<layout>-<width>-<theme>.png`. `crop` is a list of selectors (the picture is cut to their union), `marks` are (selector, number) pairs, or (selector, number, 'right') to put the disc after the box, centred, or (selector, number, 'above') to put it above the box, when its top left corner would cover text.
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
const inside = e => { const r = e.getBoundingClientRect(); return e.checkVisibility() && r.width > 0 && r.height > 0 && r.right > box.l && r.left < box.r && r.bottom > box.t && r.top < box.b; };
const tiles = [...document.querySelectorAll('.bc-no-image,.bw-no-image,.bc-picture:not(:has(img)),.bw-picture:not(:has(img)),.st-pic:not(:has(img)),.bp-tile:not(:has(img)),.bd-tile:not(:has(img)),.bd-sheet:not(:has(img)),.bd-set-tile:not(:has(img)),.bs-tile:not(:has(img))')].concat(
  [...document.querySelectorAll('body *')].filter(e => !e.children.length && /^No image$/i.test((e.textContent || '').trim())));
const broken = [...document.images].filter(i => inside(i) && (!i.complete || !i.naturalWidth));
const named = [...tiles.filter(inside), ...broken].map(e => { const row = e.closest('.bp-line,.bd-cand,article,li,tr,form,[data-row]') || e.parentElement.parentElement; return (row.innerText || e.getAttribute('src') || '').replace(/\\s+/g, ' ').trim().slice(0, 130); });
if (named.length) throw new Error('no_placeholders: ' + named.length + ' placeholder(s): ' + [...new Set(named)].join(' | '));
""" % json.dumps(list(selectors))


def isolate(selector):
    """JS for a job's `after`: hide everything on the page except the element matching `selector` and its ancestors, so a sheet or dialog shot shows the sheet
    alone (the page behind it holds rows whose pictures the shot does not need, and the placeholder check looks at the whole cropped area)."""
    return f"""{{ const keep = document.querySelector({json.dumps(selector)}); if (!keep) throw new Error('isolate: no ' + {json.dumps(selector)});
for (let node = keep; node !== document.body; node = node.parentElement) for (const sibling of node.parentElement.children) if (sibling !== node) sibling.style.display = 'none'; }}
"""


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
# The pull list shows every part of the set and most parts have no render yet: keep the Bricks group's first eleven lines (the lines that have one) and drop the rest.
PULL_WINDOW = ("{ const label = [...document.querySelectorAll('.bp-grp')].find(g => /^Bricks/.test(g.textContent.trim())); if (!label) throw new Error('PULL_WINDOW: no Bricks group'); "
               "let lines = 0; for (const e of [...document.querySelectorAll('.bp-grp, [data-line]')]) { "
               "if (e === label) continue; if (e.classList.contains('bp-grp')) { e.remove(); continue; } "
               "if ((e.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING) || (lines += 1) > 11) e.remove(); } "
               "const open = [...document.querySelectorAll('[data-line]')].find(l => /(^|\\D)0 of \\d+/.test(l.textContent)); if (!open) throw new Error('PULL_WINDOW: no line left to find'); open.setAttribute('data-shot-open', ''); "
               "document.querySelectorAll('.bp-more, .bp-bar').forEach(e => e.remove()); }\n")
# Order missing parts, the review step (a phone screen): the four copies with gaps, as the first step hands them on.
ORDER_REVIEW = ('/planning/order-missing-parts?sel=1&' + '&'.join('copy=' + REAL(n) for n in ('10210-1', '7938-1', '7213-1', '31120-1')) + '&was_sell=1&was_gain=0&step=review')
BULK_PICKED = '/workbench/part-picker?copy=' + '&copy='.join(REAL(n) for n in ('31120-1', '7938-1', '7213-1'))
CHOOSE_REAL_SETS = ("document.querySelector('[data-none]').click(); for (const n of ['31120-1', '7938-1', '7213-1']) { "
                    "const box = document.querySelector('[data-number=' + JSON.stringify(n) + '] input'); if (!box) throw new Error('Part Runner does not list ' + n); box.click(); } "
                    "await new Promise(r => setTimeout(r, 300));")
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
    'storage': ('/workbench/storage/storage-drawer-3', None, {
        layout: (width, ['.st-detail-head'], [('.st-detail-head p', 1, 'right')], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'runner-sets': ('/workbench/part-picker', CHOOSE_REAL_SETS, {
        layout: (width, ['[data-selection] .bw-segments', '[data-continue]'], [('[data-none]', 1), ('[data-row] input:checked', 2), ('[data-continue]', 3)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'runner-order': (BULK_PICKED, None, {
        layout: (width, ['section[data-rank] h1', '[data-rank-keys]', 'section[data-rank] .bw-primary'], [('[data-rank-key]', 1), ('section[data-rank] .bw-primary', 2)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'runner-found': (BULK_PICKED + '&pick=1', OPEN_FOUND, {
        layout: (width, ['.bw-pick-card'], [('[data-selector] [name=destination]', 1), ('[data-selector] [data-step="1"]', 2), ('[data-selector] .bw-primary', 3)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'matchmaker': ('/workbench/match', None, {
        layout: (width, ['h1', '.bw-copy-summary'], [('.bw-badge', 1), ('.bw-coverage', 2)], "document.querySelectorAll('.bw-match-details').forEach(d => { d.open = false; });\n")
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'lot-detect': (LOT_PAGE + '?detect=1&ignore_common=1#set-detection', SHOW_DETECTION, {
        layout: (width, ['.bd-top'], marks, "document.querySelectorAll('.bd-cand details').forEach(d => { d.open = false; });\n")
        for layout, width, marks in (('desktop', 1024, [('.bd-pct', 1, 'above'), ('.bd-toggle', 2)]), ('phone', 390, [('.bd-pct', 1, 'above')]))}),
    'lot-pull-list': (pull('7938-1', '?show=all'), None, {
        layout: (width, ['h1', '[data-line]'], [('[data-shot-open] .bp-cb', 1), ('[data-shot-open] .bp-step button[aria-label^="One more"]', 2)], PULL_WINDOW)
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'lot-pull-confirm': (pull('7938-1', '/make-copy'), None, {
        layout: (width, ['.bp-panel'], [('.bp-panel button.bp-lg', 1)], isolate('.bp-confirm'))
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'scout-list': ('/workbench/build-scout?min_percent=10', None, {
        layout: (width, ['.bs-row'], marks, "document.querySelectorAll('.cap2').forEach(e => e.remove()); const filters = document.querySelector('[name=year_from]'); if (filters) filters.closest('form').remove(); const rows = document.querySelector('.bs-rows'); document.querySelectorAll('main p, main h1').forEach(e => { if (e.compareDocumentPosition(rows) & Node.DOCUMENT_POSITION_FOLLOWING) e.remove(); });\n")
        for layout, width, marks in (('desktop', 1024, [('.bs-bar', 1), ('.bs-cost', 2, 'right')]), ('phone', 390, [('.bs-bar', 1)]))}),
    'complete-sets': ('/planning/complete-sets', None, {
        layout: (width, ['[data-bp-row]:first-of-type'], [('[data-bp-row]:first-of-type', 1), ('[data-bp-pin]', 2), ('.bp-repair-details summary', 3)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
}
# Tutorial shots defined but not active: each needs pictures the real-sets folder does not hold yet, so the placeholder check fails them. Move an entry
# into TUTORIAL_SHOTS when its pictures are in. Needed: scout-set the figure fig-004769; order-missing and order-missing-review the parts 2540 Black,
# 3004 Medium Blue, 3008 Dark Brown and 30099 Dark Brown. The phone scout-set is a page (/workbench/build-scout/<id>), not the panel, so its path differs.
PENDING_TUTORIAL_SHOTS = {
    'scout-set': (scout_set('7938-1'), None, {
        layout: (width, ['.bs-panel'], [('.bs-strip', 1), ('.bs-gap', 2)], '')
        for layout, width in (('desktop', 1024), ('phone', 390))}),
    'order-missing': ('/planning/order-missing-parts', None, {
        'desktop': (1024, ['.oo-rows', '.oo-lines'], [('.oo-box', 1), ('.oo-srcs', 2)], '')}),
    'order-missing-review': (ORDER_REVIEW, None, {
        'phone': (390, ['.oo-lines'], [('.oo-srcs', 1)], '')}),
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
    # One table per purpose: PICTURES (README and tutorials; each stem's world is WORLD_OF's, else showcase) and SITE_PICTURES (the website, always on the
    # real-sets world, each capture failing on a missing-picture tile). A stem can be in both, so an entry is (world, table, stem).
    entries = [(WORLD_OF.get(stem, 'showcase'), PICTURES, stem) for stem in PICTURES] + [('real', SITE_PICTURES, stem) for stem in SITE_PICTURES]
    entries = [e for e in entries if options.only is None or e[2] in options.only]
    if options.out:
        names = [e[2] for e in entries]
        clash = sorted({n for n in names if names.count(n) > 1})
        if clash:
            print('--out writes every picture flat, and these are made on two worlds: ' + ', '.join(clash) + '; run without --out (each goes to its own folder)')
            return 1
    with tempfile.TemporaryDirectory(prefix='bw-site-') as scratch:
        for world in dict.fromkeys(e[0] for e in entries):
            group = [(table, stem) for w, table, stem in entries if w == world]
            with screen_gate.world(world, sorted({table[stem][0] for table, stem in group if isinstance(table[stem][0], str)})) as base:
                jobs, folders_of = [], {}
                for table, stem in group:
                    path, width, limit, script, folders = table[stem]
                    path = path(base) if callable(path) else path
                    for theme in ('light', 'dark'):
                        out = Path(scratch) / f'{world}-{table is SITE_PICTURES}-{stem}-{theme}.png'
                        folders_of[out] = (f'{stem}-{theme}.png', folders)
                        jobs.append({'url': base + path, 'out': str(out), 'width': width, 'theme': theme, 'max': limit, 'script': (script or '') + SETTLE,
                                     **EXTRAS.get(stem, {}), **({'no_tiles': True} if table is SITE_PICTURES else {})})
                spec = Path(scratch) / f'jobs-{world}.json'
                spec.write_text(json.dumps({'deterministic': True, 'now': screen_gate.FIXED_NOW.isoformat().replace('+00:00', 'Z'), 'jobs': jobs}))
                result = subprocess.run(['node', str(ROOT / 'scripts' / 'capture_screens.cjs'), chrome.stdout.strip(), str(spec)], capture_output=True, text=True, timeout=1800)
                if result.returncode:
                    print(result.stdout[-2000:] + result.stderr[-2000:])
                    return 1
                for job in jobs:
                    made = Path(job['out'])
                    name, folders = folders_of[made]
                    optimise(made)
                    for folder in ([Path(options.out)] if options.out else list(folders)):
                        folder.mkdir(parents=True, exist_ok=True)
                        (folder / name).write_bytes(made.read_bytes())
                    print(name, made.stat().st_size)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
