"""Brick Work's logo and app icon (commission U, design-builder step 4), generated from one source.

    python3 brand_logo.py build    write every file in design/logo/ and design/app-icon/ (and manifest-snippet.json here)
    python3 brand_logo.py check    rebuild in memory and compare: SVGs byte for byte, PNGs pixel for pixel (exit 1 on drift)

The mark is W1 of logo round 4 (Ulf, 2026-11-18: "W1, white X at X1's size - perfect - that's it"): three stud-less
plates, one over two, in Violet #7334CF, with a white X cut out of the top plate's upper-right corner (a mask, so the X
always shows the ground). The variants, clear space, minimum sizes and icon set are round 5 (Ulf, 2026-11-19: "round 5:
approved as shown"); see design/APPROVALS.md and design/BRAND.md sections 1 and 2.

Everything is built from one unit, a rounded rect placed only by transforms. The wordmark "brick work" is Outfit
SemiBold (SIL OFL 1.1, (c) 2021 The Outfit Project Authors) at 56 units, stored as outlines in wordmark.json so that
no font file is needed; `extract-wordmark <outfit-600.ttf>` rewrites it from the font (needs fontTools).

Renderer: Playwright Chromium (the design-builder rule: one renderer). Needs `playwright` and `pillow`; these are
design-time tools and are not in the app's requirements. The served copies in static/brickwork/ are written from these
files by scripts/brand_assets.py build, never by this script.
"""
import io, json, math, os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
DESIGN = HERE.parent.parent
LOGO, ICON = DESIGN / 'logo', DESIGN / 'app-icon'

VIOLET = '#7334CF'            # the mark on light grounds
VIOLET_ON_DARK = '#B995F6'    # the mark on dark grounds
INK = '#111214'
PAPER = '#FAFAF8'
DARK = '#111214'
LIGHT_TEXT = '#EDEDEF'
WHITE = '#FFFFFF'
# The web manifest's theme and background colour: the B′ app bar surface, --tw-surface (W-Q7, Ulf 19.11.: "App bar surface (Recommended)").
# A manifest holds one value; the dark one, #1F2322, goes in the app's <meta name="theme-color" media="(prefers-color-scheme: dark)">.
MANIFEST_LIGHT, MANIFEST_DARK = '#F8F8F6', '#1F2322'

# One unit (w, h, r) and its three placements (cx, cy, rotation), fitted into the 100 x 100 box with a 4-unit margin.
UNIT = (44, 26, 9)
AT = [(0, -15, 0), (-23.5, 15, 0), (23.5, 15, 0)]
W, H, R = UNIT
X = dict(s=7.5, cx=W/2 - 8.5, cy=-H/2 + 8.5, sw=2.6)   # the X: X1's size and place, cut out of the top plate


def fit(margin=4):
    pts = []
    for cx, cy, rot in AT:
        a = math.radians(rot)
        for dx, dy in ((-W/2, -H/2), (W/2, -H/2), (W/2, H/2), (-W/2, H/2)):
            pts.append((cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)))
    x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts); y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts)
    k = (100 - 2 * margin) / max(x1 - x0, y1 - y0)
    ox = 50 - k * (x0 + x1) / 2; oy = 50 - k * (y0 + y1) / 2
    return [f'translate({ox + k*cx:.3f} {oy + k*cy:.3f}) rotate({rot}) scale({k:.4f})' for cx, cy, rot in AT]


XFORMS = fit()


def unit():
    return f'<rect id="u" x="{-W/2}" y="{-H/2}" width="{W}" height="{H}" rx="{R}"/>'


def xpath():
    h = X['s'] / 2
    return f'M{X["cx"]-h} {X["cy"]-h}L{X["cx"]+h} {X["cy"]+h}M{X["cx"]+h} {X["cy"]-h}L{X["cx"]-h} {X["cy"]+h}'


def mark_body(fill, with_x=True):
    top, rest = XFORMS[0], XFORMS[1:]
    rest_use = ''.join(f'<use href="#u" transform="{t}"/>' for t in rest)
    if not with_x:
        return f'<defs>{unit()}</defs><g fill="{fill}">{rest_use}<use href="#u" transform="{top}"/></g>'
    mask = (f'<mask id="m" maskUnits="userSpaceOnUse" x="-60" y="-60" width="120" height="120">'
            f'<rect x="-60" y="-60" width="120" height="120" fill="#fff"/>'
            f'<path d="{xpath()}" stroke="#000" stroke-width="{X["sw"]}" stroke-linecap="round" fill="none"/></mask>')
    return (f'<defs>{unit()}{mask}</defs><g fill="{fill}">{rest_use}'
            f'<g transform="{top}"><use href="#u" mask="url(#m)"/></g></g>')


def mark(fill=VIOLET, with_x=True, bg=None):
    ground = f'<rect width="100" height="100" fill="{bg}"/>' if bg else ''
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{ground}{mark_body(fill, with_x)}</svg>'


def tile(with_x=True, scale=0.66, rx=22.5, fg=WHITE, bg=VIOLET):
    off = 50 * (1 - scale)
    corner = f' rx="{rx}"' if rx else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100"{corner} fill="{bg}"/>'
            f'<g transform="translate({off} {off}) scale({scale})">{mark_body(fg, with_x)}</g></svg>')


def wordmark():
    w = json.loads((HERE / 'wordmark.json').read_text())
    return w['d'], w['width'], w['cap']


def lockup(mark_fill=VIOLET, word_fill=INK, bg=None, with_x=True, pad=0):
    d, tw, cap = wordmark()
    Wd = 126 + tw + 8
    ground = f'<rect x="{-pad}" y="{-pad}" width="{Wd+2*pad:.1f}" height="{100+2*pad}" fill="{bg}"/>' if bg else ''
    vb = f'{-pad} {-pad} {Wd+2*pad:.1f} {100+2*pad}'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{ground}{mark_body(mark_fill, with_x)}'
            f'<path transform="translate(126 {50+cap/2:.2f})" d="{d}" fill="{word_fill}"/></svg>')


def lockup_width():
    return 126 + wordmark()[1] + 8


# ---- the files -------------------------------------------------------------------------------------------------------
# SVG sources, by path relative to design/. Served names are the ones the app has always used (scripts/brand_assets.py).
SVGS = {
    'logo/mark.svg': lambda: mark(),                                    # LG02, mark alone on light
    'logo/mark-dark.svg': lambda: mark(VIOLET_ON_DARK),                 # LG03's mark, on dark
    'logo/mark-line.svg': lambda: mark(INK),                            # LG05's mark, one colour ink (labels, print)
    'logo/mark-small.svg': lambda: mark(with_x=False),                  # LG07, bare mark below 32 px (app bar), no X
    'logo/mark-small-dark.svg': lambda: mark(VIOLET_ON_DARK, with_x=False),   # LG07 on dark grounds
    'logo/lockup-horizontal.svg': lambda: lockup(),                     # LG01, primary lockup
    'logo/lockup-horizontal-dark.svg': lambda: lockup(VIOLET_ON_DARK, LIGHT_TEXT),   # LG03
    'logo/lockup-brand-field.svg': lambda: lockup(WHITE, WHITE, bg=VIOLET, pad=26),  # LG04, white on the violet field
    'logo/lockup-mono-ink.svg': lambda: lockup(INK, INK),               # LG05
    'logo/lockup-mono-white.svg': lambda: lockup(WHITE, WHITE),         # LG06
    'app-icon/app-icon.svg': lambda: tile(),                            # the "any" icon: white mark on the violet tile
    'app-icon/icon-maskable.svg': lambda: tile(scale=0.52, rx=0),       # full bleed, mark inside the 80 % safe zone
    'app-icon/favicon.svg': lambda: tile(with_x=False),                 # LG07, the small mark: no X below 32 px
}
SPLASH_GROUND = {'light': (PAPER, VIOLET), 'dark': (DARK, VIOLET_ON_DARK)}
SPLASH_SIZES = {'ipad-portrait': (1536, 2048), 'ipad-landscape': (2048, 1536), 'iphone16': (1179, 2556)}
SPLASH_MARK = 0.30            # the mark's box is 30 % of the screen's short side (derived from the 512 px splash)


def splash(theme, w, h):
    ground, fill = SPLASH_GROUND[theme]
    s = SPLASH_MARK * min(w, h)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" fill="{ground}"/>'
            f'<g transform="translate({(w-s)/2:.1f} {(h-s)/2:.1f}) scale({s/100:.4f})">{mark_body(fill)}</g></svg>')


# PNG renders: path -> (svg source, width, height)
def pngs():
    out = {}
    lw = lockup_width()
    for t, src in (('light', SVGS['logo/lockup-horizontal.svg']), ('dark', SVGS['logo/lockup-horizontal-dark.svg'])):
        out[f'logo/lockup-horizontal-{t}.png'] = (src(), round(lw * 3.12), 312)
    for s in (120, 152, 167, 180, 192, 512, 1024):
        out[f'app-icon/icons/icon-{s}.png'] = (tile(), s, s)
    for s in (192, 512, 1024):
        out[f'app-icon/icons/icon-maskable-{s}.png'] = (tile(scale=0.52, rx=0), s, s)
    out['app-icon/favicon-16.png'] = (tile(with_x=False), 16, 16)
    out['app-icon/favicon-24.png'] = (tile(with_x=False), 24, 24)
    out['app-icon/favicon-32.png'] = (tile(), 32, 32)
    out['app-icon/favicon-48.png'] = (tile(), 48, 48)
    for name, (w, h) in SPLASH_SIZES.items():
        for t in SPLASH_GROUND:
            out[f'app-icon/splash/splash-{name}-{w}x{h}-{t}.png'] = (splash(t, w, h), w, h)
    return out


def manifest_snippet():
    icons = [{'src': f'icons/icon-{s}.png', 'sizes': f'{s}x{s}', 'type': 'image/png', 'purpose': 'any'} for s in (192, 512, 1024)]
    icons += [{'src': f'icons/icon-maskable-{s}.png', 'sizes': f'{s}x{s}', 'type': 'image/png', 'purpose': 'maskable'}
              for s in (192, 512, 1024)]
    return json.dumps({'icons': icons, 'theme_color': MANIFEST_LIGHT, 'background_color': MANIFEST_LIGHT}, indent=2) + '\n'


def render(items):
    """{key: (svg, w, h)} -> {key: PNG bytes}, through Playwright Chromium at device scale 1, transparent ground."""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        exe = os.environ.get('BRAND_CHROMIUM')     # a Chromium other than Playwright's own download, when set
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        pg = b.new_page(device_scale_factor=1)
        for k, (svg, w, h) in items.items():
            pg.set_viewport_size({'width': w, 'height': h})
            sized = svg.replace('<svg ', f'<svg width="{w}" height="{h}" style="display:block" ', 1)
            pg.set_content(f'<!doctype html><body style="margin:0">{sized}')
            out[k] = pg.screenshot(omit_background=True)
        b.close()
    return out


def ico(png16, png32, png48):
    from PIL import Image
    imgs = [Image.open(io.BytesIO(b)).convert('RGBA') for b in (png16, png32, png48)]
    buf = io.BytesIO()
    imgs[2].save(buf, format='ICO', sizes=[(16, 16), (32, 32), (48, 48)], append_images=imgs[:2])
    return buf.getvalue()


def everything():
    files = {k: f().encode() for k, f in SVGS.items()}
    files.update(render(pngs()))
    files['app-icon/favicon.ico'] = ico(files['app-icon/favicon-16.png'], files['app-icon/favicon-32.png'],
                                        files['app-icon/favicon-48.png'])
    return files


def same_pixels(a, b, tolerance=0.001):
    from PIL import Image, ImageChops
    ia, ib = (Image.open(io.BytesIO(x)).convert('RGBA') for x in (a, b))
    if ia.size != ib.size:
        return False
    diff = ImageChops.difference(ia, ib).convert('L').point(lambda v: 255 if v > 8 else 0)
    return diff.histogram()[255] / (ia.width * ia.height) <= tolerance


def main(cmd):
    if cmd == 'extract-wordmark':
        from fontTools.ttLib import TTFont
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
        f = TTFont(sys.argv[2]); gs, cmap, hmtx = f.getGlyphSet(), f.getBestCmap(), f['hmtx']
        k = 56 / f['head'].unitsPerEm; pen = SVGPathPen(gs); x = 0
        for ch in 'brick work':
            g = cmap[ord(ch)]; gs[g].draw(TransformPen(pen, (k, 0, 0, -k, x, 0))); x += hmtx[g][0] * k
        (HERE / 'wordmark.json').write_text(json.dumps({'text': 'brick work', 'face': 'Outfit SemiBold', 'size': 56,
            'licence': 'SIL OFL 1.1, (c) 2021 The Outfit Project Authors', 'd': pen.getCommands(), 'width': x,
            'cap': f['OS/2'].sCapHeight * k}, indent=1) + '\n')
        return 0
    files = everything()
    snippet = manifest_snippet()
    if cmd == 'build':
        for k, data in files.items():
            p = DESIGN / k
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (HERE / 'manifest-snippet.json').write_text(snippet)
        print(f'Built {len(files)} logo and app-icon files in design/')
        return 0
    bad = []
    for k, data in files.items():
        p = DESIGN / k
        if not p.exists():
            bad.append(f'{k}: missing')
        elif k.endswith('.png'):
            if not same_pixels(p.read_bytes(), data):
                bad.append(f'{k}: differs')
        elif k.endswith('.ico'):
            continue    # rebuilt from the PNGs, which are checked
        elif p.read_bytes() != data:
            bad.append(f'{k}: differs')
    ms = HERE / 'manifest-snippet.json'
    if not ms.exists():
        bad.append('sources/logo/manifest-snippet.json: missing')
    elif ms.read_text() != snippet:
        bad.append('sources/logo/manifest-snippet.json: differs')
    for line in bad:
        print('LOGO:', line)
    print('Logo OK' if not bad else f'{len(bad)} logo files drift from brand_logo.py')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'check'))
