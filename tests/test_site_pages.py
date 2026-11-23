"""The static site stays complete, local, accessible without JS, and free of private material."""
import html
from html.parser import HTMLParser
from pathlib import Path
import re
import struct
import time
from urllib.parse import unquote, urlsplit

import pytest

from tests import rendered

from brickwork.demo.privacy import pattern

PRIVATE = pattern()

# The module's fixture exports the demo or builds the site (about a minute under load): one group, so one worker builds it, not each worker (#254, ADR 0024)
pytestmark = pytest.mark.xdist_group('site-pages')
ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ('hero', 'who-it-is-for', 'three-flows', 'more-advantages',
            'scriptable-and-ai-ready', 'integrations', 'how-it-compares',
            'how-it-fits-together', 'questions', 'install', 'planned')


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def local_target(site, page, url):
    from scripts.build_site import site_base
    path = unquote(urlsplit(url).path)
    # Demo uses the deployment prefix and a real document base.
    base = site_base()
    if path.startswith(base):
        return site / path[len(base):]
    return site / path.lstrip('/') if path.startswith('/') else page.parent / path


# The apex build's tests are a group of their own: each build takes about a minute, so the two builds and their tests run on two workers, not one after the other (#364)
@pytest.fixture(scope='module', params=['default', pytest.param('apex', marks=pytest.mark.xdist_group('site-pages-apex'))])
def site(tmp_path_factory, request):
    from scripts.build_site import build
    with pytest.MonkeyPatch.context() as env:
        env.setenv('GITHUB_REPOSITORY', 'Ulef1005/brick-work')
        env.delenv('SITE_BASE', raising=False)
        if request.param == 'apex':
            env.setenv('SITE_BASE', '/')
        started = time.monotonic()
        built = build(tmp_path_factory.mktemp(request.param) / 'site')
        print(f'\nSite build ({request.param}): {time.monotonic() - started:.2f}s', flush=True)
        yield built


def test_every_page_and_asset_resolves_without_external_requests(site):
    # Copied demo source templates are assets, not exported application pages.
    pages = [*site.rglob('index.html'), site / '404.html']
    assert {'index.html', 'use-cases/index.html', 'workflows/index.html', 'docs/index.html',
            'api/index.html', 'mcp/index.html', 'demo/index.html'} <= {
                str(p.relative_to(site)) for p in pages}
    for page in pages:
        text = page.read_text()
        assert not PRIVATE.search(text), str(page.relative_to(site))
        elements = Elements(text).elements
        for tag, attrs in elements:
            for attr in ('href', 'src', 'srcset'):
                target = attrs.get(attr)
                if not target:
                    continue
                targets = [s.strip().split()[0] for s in target.split(',')] if attr == 'srcset' else [target]
                for url in targets:
                    parsed = urlsplit(url)
                    external = bool(parsed.scheme or parsed.netloc)
                    analytics = (tag == 'script' and url == 'https://static.cloudflareinsights.com/beacon.min.js'      # the one allowed script,
                                 and page.relative_to(site).parts[0] not in ('docs', 'demo'))                     # never on the docs or the demo
                    if tag in ('link', 'script', 'img', 'source') and attrs.get('rel') != 'canonical' and not analytics:
                        assert not external, f'{page}: external {tag} {url}'
                    if external or not parsed.path or tag == 'base':
                        continue
                    resolved = local_target(site, page, url)
                    if resolved.is_dir():
                        resolved /= 'index.html'
                    assert resolved.exists(), f'{page}: broken {attr} {url}'
    for css in site.rglob('*.css'):
        text = css.read_text()
        assert not re.search(r'@import\s+["\']?https?:', text)
        for url in re.findall(r'url\([\s\'\"]*([^\s\'\")]+)', text):
            if url.startswith('data:'):  # Embedded SVGs make no request.
                continue
            assert not urlsplit(url).scheme and not url.startswith('//'), f'{css}: external URL'
            assert local_target(site, css, url).is_file(), f'{css}: {url}'


def test_every_documentation_page_links_the_complete_favicon_set(site):
    from scripts.build_site import MOVED, NAV

    # The stub pages at the old /api/ and /mcp/ URLs are built here too.
    for href in [''] + [href for _, href in NAV if '#' not in href] + ['coming-from/' + n + '/' for n in ('rebrickable', 'bricklink', 'bricktracker', 'other')] + [folder + '/' for folder, _, _ in MOVED]:
        if href.startswith(('demo/', 'docs/')):  # The demo uses the app's own icon links; Zensical builds the docs.
            continue
        page = site / href / 'index.html'
        up = '../' * len(Path(href).parts)
        icons = [attrs for tag, attrs in Elements(page.read_text()).elements
                 if tag == 'link' and attrs.get('rel') in ('icon', 'apple-touch-icon')]
        assert icons == [
            {'rel': 'icon', 'href': f'{up}assets/favicon.svg', 'type': 'image/svg+xml'},
            {'rel': 'icon', 'href': f'{up}assets/favicon-32.png', 'sizes': '32x32', 'type': 'image/png'},
            {'rel': 'icon', 'href': f'{up}assets/favicon-16.png', 'sizes': '16x16', 'type': 'image/png'},
            {'rel': 'icon', 'href': f'{up}assets/favicon.ico', 'sizes': '48x48'},
            {'rel': 'apple-touch-icon', 'href': f'{up}assets/apple-touch-icon.png'},
        ], href
        for icon in icons:
            assert local_target(site, page, icon['href']).is_file()

    for name in ('favicon.svg', 'favicon-32.png', 'favicon-16.png', 'favicon.ico', 'apple-touch-icon.png'):
        source = 'icons/icon-180.png' if name == 'apple-touch-icon.png' else name
        assert (site / 'assets' / name).read_bytes() == (ROOT / 'static/brickwork' / source).read_bytes()


def test_landing_sections_and_copy(site):
    text = (site / 'index.html').read_text()
    body = text.split('<main id="main" class="home">')[1].split('</main>')[0]
    plain = re.sub(r'<[^>]+>', '', body)
    assert "Don't just manage your collection. Work with it." in plain
    assert '<span class="logo-blue">Work with it.</span>' in body   # ink in B′ (#526 W-Q1, Ulf 2026-11-19), was the logo's blue
    css = (site / 'assets/marketing.css').read_text()
    assert '.logo-blue{color:var(--tw-text)}' in css and '#007187' not in css and '#3DB4CC' not in css
    assert "The workbench for your collection that you didn't know existed" in html.unescape(plain)
    for label in ('Who it is for', 'The workbench', 'Install', 'Already use a collection tracker?', 'Documentation', "What's new"):
        assert f'<span class="label">{label}</span>' in body, label
    assert body.count('class="card"><h3>You ') == 6          # the six "Who it is for" boxes
    assert body.count('class="card wf-card"') == 12          # six workflows and six more at the table
    assert 'id="install"' in body and 'href="demo/"' in body and 'href="install/"' in body
    assert 'LEGO' not in body
    assert 'not affiliated with the LEGO Group, Rebrickable, Brickset or BrickLink' in text
    from brickwork.version import __version__
    assert f'{__version__} · tested on a real collection' in body and f'Brick Work {__version__}' in body
    assert len(text.encode()) + sum((site / 'assets' / n).stat().st_size for n in ('site.css', 'marketing.css', 'site.js')) < 130_000


def test_workflow_walkthroughs_are_complete_without_javascript(site):
    text = (site / 'workflows/index.html').read_text()
    for anchor, steps in (('part-spotter', 4), ('check-set-parts', 5), ('part-picker', 4), ('matcher', 2)):
        section = text.split(f'id="{anchor}"')[1].split('<div class="sec')[0]
        assert section.count('<li><span class="n">') == steps, anchor
    assert text.count('class="mini') == 5               # Orders, Storage, Build Scout, Build it, Set detection
    assert 'to capture' not in text and 'data-walkthrough' not in text
    assert 'The rest of the workbench.' in text


def test_use_cases_have_nine_cards_in_three_groups(site):
    text = (site / 'use-cases/index.html').read_text()
    assert text.count('<article') == 9
    for group in ('uc-table', 'uc-plan', 'uc-scripts'):
        assert f'id="{group}"' in text
    assert 'Planned' in text
    order = next(card for card in text.split('<article') if '<h3 class="layout-39">Receive a parts order' in card)
    assert '<picture' not in order          # no capture while the demo's pictures are placeholders (the screenshots test below)


def test_site_pages_show_the_real_world_pictures_and_no_placeholder(site):
    """Ulf, 2026-11-13: the site shows the demo's real-sets world (#332) and never a placeholder. The home page and the workflows page carry the captures
    (scripts/site_shots.py, rendered with no_tiles); every picture they name is in the build, and no page carries a capture of the old drawings."""
    for name, wanted in (('index.html', ('1c-sets-desktop-1440', '3a-matcher-phone-390', '3e-start-phone-390', '3c-picker-sets-phone-390', '12b-count-what-arrived-desktop-1440')),
                         ('workflows/index.html', ('3e-start-phone-390', '3e-part-phone-390', '3c-picker-sets-phone-390', '3c-picker-pick-phone-390', '3a-matcher-phone-390', '12b-count-what-arrived-desktop-1440',
                                                  '12c-list-and-detail-desktop-1440', 'scout-list-desktop-1440', 'lot-pull-confirm-phone-390'))):   # Set detection has no tile in v1.2 (#526)
        text = (site / name).read_text()
        for stem in wanted:
            assert f'{stem}-light.png' in text and f'{stem}-dark.png' in text, (name, stem)
        for tag, attrs in Elements(text).elements:
            for url in (attrs.get('src', '') + ' ' + attrs.get('srcset', '')).split():
                if '/img/' in url:
                    assert (site / 'assets/img' / url.rsplit('/', 1)[1]).is_file(), (name, url)


def picture_scale(name):
    """Phone captures are drawn at twice the pixels (scripts/site_shots.py), so their width and height attributes are half the file's."""
    return 2 if '-phone-' in name or '-390-' in name else 1


def test_images_are_local_small_and_dimensioned(site):
    for png in (ROOT / 'scripts/site/img').glob('*.png'):
        assert png.stat().st_size < 300_000, png.name
    for name in ('index.html', 'use-cases/index.html', 'workflows/index.html'):
        text = (site / name).read_text()
        for tag, attrs in Elements(text).elements:
            if tag == 'source' and attrs.get('srcset', '').endswith('.avif'):
                avif = local_target(site, site / name, attrs['srcset'])      # every capture also comes as AVIF, smaller than its PNG
                assert avif.read_bytes()[4:12] == b'ftypavif' and avif.stat().st_size < avif.with_suffix('.png').stat().st_size, avif.name
            elif tag == 'source' and '/img/' in attrs.get('srcset', ''):
                dimensions = struct.unpack('>II', local_target(site, site / name, attrs['srcset']).read_bytes()[16:24])
                scale = picture_scale(attrs['srcset'])
                assert dimensions == (scale * int(attrs['width']), scale * int(attrs['height']))
            if tag != 'img':
                continue
            hero = attrs.get('fetchpriority') == 'high'      # the two screenshots above the fold on the home page load first; every other picture is lazy
            assert (hero and name == 'index.html' and 'loading' not in attrs) or attrs.get('loading') == 'lazy'
            assert attrs.get('decoding') == 'async'
            assert int(attrs['width']) > 0 and int(attrs['height']) > 0
            if attrs['src'].endswith('.png'):
                dimensions = struct.unpack('>II', local_target(site, site / name, attrs['src']).read_bytes()[16:24])
                scale = picture_scale(attrs['src'])
                assert dimensions == (scale * int(attrs['width']), scale * int(attrs['height']))
        assert '<picture>' in text or '<picture ' in text
        assert 'media="(prefers-color-scheme: dark)"' in text
        assert 'style=' not in text and '{{' not in text and '<sc-' not in text


def test_shared_chrome_and_theme_script(site):
    # docs/ is the Zensical user-docs site with its own chrome (App Standard, Maintenance § User docs).
    for name in ('index.html', 'use-cases/index.html', 'workflows/index.html', 'api/index.html', 'mcp/index.html'):
        text = (site / name).read_text()
        assert 'data-theme-toggle' in text
        assert re.search(r'<script src="(?:../)?assets/site.js" defer>', text)
        elements = Elements(text).elements
        logos = [attrs for tag, attrs in elements
                 if tag == 'img' and attrs.get('alt') == 'Brick Work']
        assert len(logos) == 1  # The header carries the wordmark; the footer is text columns.
        for logo in logos:
            assert logo['src'].endswith('assets/lockup-horizontal-light.png')
            dimensions = struct.unpack('>II', local_target(site, site / name, logo['src']).read_bytes()[16:24])
            assert dimensions == (int(logo['width']), int(logo['height']))
            assert dimensions[0] >= 2 * 160
        sources = [attrs for tag, attrs in elements if tag == 'source'
                   and attrs.get('srcset', '').endswith('assets/lockup-horizontal-dark.png')]
        assert len(sources) == 1
        assert all(source['media'] == '(prefers-color-scheme: dark)' for source in sources)
        for label in ('Demo', 'Docs', 'Changelog', 'GitHub', 'API', 'MCP'):
            assert f'>{label}</a>' in text
    for theme in ('light', 'dark'):
        name = f'lockup-horizontal-{theme}.png'
        assert (site / 'assets' / name).read_bytes() == (ROOT / 'static/brickwork' / name).read_bytes()
        assert struct.unpack('>II', (site / 'assets' / name).read_bytes()[16:24]) == dimensions
    assert not list((site / 'assets').glob('lockup*.svg'))
    script = (site / 'assets/site.js').read_text()
    css = (site / 'assets/site.css').read_text()
    for removed in ('device-switch', 'desktop-device', 'desktop-frame', 'data-device'):
        assert removed not in script + css
    assert '.phone-frame{max-width:340px;margin:auto}' in css
    assert 'localStorage.getItem' in script and 'localStorage.setItem' in script
    assert 'try {' in script and 'catch' in script
    assert 'prefers-color-scheme: dark' in script
    assert (site / 'demo/demo-manifest.json').is_file()


def test_javascript_theme_and_step_state():
    """Exercise the actual script with a tiny DOM, including storage being blocked."""
    import shutil
    import subprocess
    rendered.need_node()
    harness = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.attrs = {}; this.dataset = {}; this.events = {}; this.children = []; }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k, fn) { this.events[k] = fn; }
  append(child) { this.children.push(child); }
  click() { this.events.click(); }
}
for (const blocked of [false, true]) {
  const classes = new Set();
  const root = {classList: {
    toggle(k, enabled) { enabled ? classes.add(k) : classes.delete(k); },
    contains(k) { return classes.has(k); }, add(k) { classes.add(k); }
  }};
  const toggle = new Element(), source = new Element();
  const back = new Element(), next = new Element(), status = new Element();
  const steps = ['Pick a copy', 'Choose an order', 'Count each part'].map(title => {
    const step = new Element();
    step.querySelector = selector => selector === 'h3' ? {textContent:title} : new Element();
    return step;
  });
  const frames = steps.map(() => new Element());
  const flow = {
    querySelectorAll: selector => selector === '.steps li' ? steps : frames,
    querySelector: selector => ({'[data-back]':back, '[data-next]':next, '[data-step-status]':status}[selector])
  };
  const document = {
    documentElement:root, createElement:() => new Element(),
    querySelector:() => toggle,
    querySelectorAll:selector => ({'picture source':[source], '[data-walkthrough]':[flow]}[selector])
  };
  let saved = 'dark';
  const storage = {
    getItem() { if (blocked) throw Error('blocked'); return saved; },
    setItem(k, value) { if (blocked) throw Error('blocked'); saved = value; }
  };
  const preference = {matches:false, addEventListener(k, fn) { this.change = fn; }};
  vm.runInNewContext(fs.readFileSync('scripts/site/site.js', 'utf8'), {
    document, window:{matchMedia:() => preference}, localStorage:storage
  });
  assert.equal(classes.has('js'), true);
  assert.equal(classes.has('tw-dark'), !blocked);
  assert.equal(frames[0].hidden, false);
  assert.equal(frames[1].hidden, true);
  next.click(); assert.match(status.textContent, /Step 2 of 3/);
  back.click(); back.click(); assert.match(status.textContent, /Step 3 of 3/);
  steps[0].children[0].click(); assert.match(status.textContent, /Pick a copy/);
  if (blocked) {
    preference.matches = true; preference.change(); assert.equal(classes.has('tw-dark'), true);
  }
  toggle.click(); assert.equal(classes.has('tw-light'), true);
  assert.equal(source.media, 'not all');
  toggle.click(); assert.equal(source.media, 'all');
  assert.equal(classes.has('tw-dark'), true);
  if (!blocked) assert.equal(saved, 'dark');
}
'''
    subprocess.run(['node', '-e', harness], cwd=ROOT, check=True, capture_output=True, text=True)


def test_every_image_the_readme_and_the_pages_show_exists_and_is_a_built_capture():
    """The pictures are captures of the built app (scripts/site_shots.py), not design frames: every one the README and the pages name is
    in site_shots.PICTURES or SITE_PICTURES, so a design-project mock-up cannot come back unnoticed."""
    sys_path = str(ROOT / 'scripts')
    import sys
    sys.path.insert(0, sys_path)
    try:
        import site_shots
    finally:
        sys.path.remove(sys_path)
    stems, site_stems = set(site_shots.PICTURES), set(site_shots.SITE_PICTURES)   # the README's captures are the showcase world's, plus the real-world shots site_shots also writes to the README; the site's are the real-sets world's
    stems |= {stem for stem, spec in site_shots.SITE_PICTURES.items() if site_shots.README in spec[-1]}   # a real-world shot written to the README too (#502, #622)
    site_stems |= {'part-spotter-photo'}   # the Part Spotter tile is Ulf's own photo of a 2 x 2 brick (part-spotter/own-photos/test/3003, no overlay), not a capture (Ulf, 2026-11-23)
    shown = set()
    for source in ('README.md', 'scripts/site/landing.html', 'scripts/site/use-cases.md', 'scripts/site/pages/workflows.html'):
        text = (ROOT / source).read_text()
        names = re.findall(r'(?:src|srcset)="[^"]*?/img/(?:readme/)?([^"/]+\.png)"', text)
        names += [f'{stem.lstrip("!")}-{theme}.png' for stem in re.findall(r'\{pic:([^|}]+)\|', text) for theme in ('light', 'dark')]
        for name in names:
            shown.add(name)
            target = ROOT / ('docs/img/readme' if source == 'README.md' else 'scripts/site/img') / name
            assert target.is_file(), f'{source}: {name} is missing'
            assert re.sub(r'-(light|dark)\.png$', '', name) in (stems if source == 'README.md' else site_stems), f'{source}: {name} is not a capture of the built app'
    assert len(shown) >= 2


NOTE = re.compile(r'real Rebrickable set and part pictures.*?BrickLink and Rebrickable', re.S)   # the README's top captures were retaken on the real-sets demo (#332, Ulf 2026-11-16)
REAL_NOTE = re.compile(r"Rebrickable.*?(plain tile|does not sponsor, authorize or endorse)", re.S)


def test_the_picture_notes_are_on_the_readme_the_landing_page_and_the_demo_banner(site):
    """The demo shows seven real sets with Rebrickable's pictures: the landing page and the demo's banner say so (the banner with the LEGO disclaimer, the
    Fair Play policy's wording), and the README's note under its top screenshots says the pictures are real Rebrickable ones."""
    readme = (ROOT / 'README.md').read_text()
    top = readme.split('<!-- /site:skip -->')[0]
    assert NOTE.search(top.split('</picture>')[-1]), 'the README says it right under the screenshots, inside the block GitHub shows'
    assert 'placeholder' not in readme, 'the README shows no placeholder drawings any more'
    landing = (site / 'index.html').read_text()
    assert REAL_NOTE.search(landing) and 'placeholder drawings' not in landing
    shim = (site / 'demo' / 'demo-shim.js').read_text()
    banner = shim.split('// The banner:', 1)[1].split('const realFetch', 1)[0]
    assert 'Set pictures: Rebrickable' in banner and 'LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this site' in banner
    assert 'placeholder' not in banner


def test_legal_pages_footer_and_missing_page(site):
    from scripts.build_site import repository, site_base
    impressum = (site / 'impressum/index.html').read_text()
    body = impressum.split('<main', 1)[1].split('>', 1)[1].split('</main>', 1)[0]
    # Source comments carry the legal reference, not the visible page copy.
    visible = re.sub(r'<[^>]+>|<!--.*?-->', '', body, flags=re.S)
    assert visible.split() == ['Impressum', 'Ulf', 'Weihbold', 'Linz,', 'Austria']
    assert '@' not in impressum
    assert not re.search(r'\d+', visible)
    privacy = (site / 'privacy/index.html').read_text()
    assert 'its own cookies and policy apply after that' in privacy
    assert 'Pictures</strong> of the demo' in privacy and 'does not contact Rebrickable' in privacy
    assert 'Part and set images: Rebrickable.' in (site / 'index.html').read_text()
    assert f'https://github.com/{repository()}/discussions' in privacy
    assert f'https://github.com/{repository()}/issues' in privacy
    footer = (site / 'index.html').read_text().split('<footer', 1)[1]
    assert 'href="impressum/"' in footer and 'href="privacy/"' in footer
    nav = (site / 'index.html').read_text().split('<main', 1)[0]
    assert '>Impressum</a>' not in nav and '>Privacy</a>' not in nav
    missing = (site / '404.html').read_text()
    assert 'That page is not here.' in missing and 'It may have moved. Try one of these.' in missing
    for href in ('#install', 'docs/', 'workflows/', 'assets/site.css'):
        assert f'href="{site_base()}{href}"' in missing
    canonical = [attrs['href'] for tag, attrs in Elements((site / 'docs/index.html').read_text()).elements
                 if tag == 'link' and attrs.get('rel') == 'canonical']
    origin = 'https://brick-work.app' if site_base() == '/' else 'https://ulef1005.github.io'
    assert canonical == [origin + site_base() + 'docs/']


def test_all_absolute_html_and_css_paths_resolve(site):
    from scripts.build_site import site_base
    base = site_base()
    checked = set()
    for file in site.rglob('*'):
        if file.suffix not in ('.html', '.css'):
            continue
        text = file.read_text()
        if file.suffix == '.html':
            urls = [candidate for _, attrs in Elements(text).elements for key, url in attrs.items()
                    if key in ('href', 'src', 'srcset')
                    for candidate in ([s.strip().split()[0] for s in url.split(',')] if key == 'srcset' else [url])]
        else:
            urls = re.findall(r'url\([\s\'\"]*([^\s\'\")]+)', text)
        for url in urls:
            if not url.startswith('/') or url.startswith('//'):
                continue
            path = unquote(urlsplit(url).path)
            assert path.startswith(base), f'{file}: outside base: {url}'
            target = site / path[len(base):]
            if target.is_dir():
                target /= 'index.html'
            assert target.is_file(), f'{file}: broken absolute path: {url}'
            checked.add(target.relative_to(site).as_posix())
    assert any(path.startswith('demo/static/') for path in checked)
    assert any(path.startswith('demo/') and path.endswith('index.html') for path in checked)
    # The existing CSS URL check also follows relative font URLs in the docs.
    assert list((site / 'docs/assets/fonts').glob('*.woff2'))


@pytest.mark.parametrize('base', ['demo/', '/demo', '//demo/', '/demo/../', '/a/../', '/./', '/.../', 'https://example.org/'])
def test_invalid_site_base_is_rejected(monkeypatch, base):
    from scripts.build_site import site_base
    monkeypatch.setenv('SITE_BASE', base)
    with pytest.raises(ValueError, match='SITE_BASE'):
        site_base()


@pytest.mark.parametrize('repository,expected', [
    ('example/another-repo', '/another-repo/'),
    ('owner/brick.work', '/brick.work/'),
])
@pytest.mark.parametrize('base', [None, ''])
def test_default_site_base_uses_repository_name(monkeypatch, repository, expected, base):
    from scripts.build_site import site_base
    if base is None:
        monkeypatch.delenv('SITE_BASE', raising=False)
    else:
        monkeypatch.setenv('SITE_BASE', base)
    monkeypatch.setenv('GITHUB_REPOSITORY', repository)
    assert site_base() == expected


def test_local_target_uses_site_base(monkeypatch):
    monkeypatch.setenv('SITE_BASE', '/brick.work/')
    site = Path('/site')
    assert local_target(site, site / '404.html', '/brick.work/assets/site.css') == site / 'assets/site.css'


@pytest.mark.parametrize('prefix', ['"', "'", '(', '='])
@pytest.mark.parametrize('path,target', [
    ('/static/x', '/brick-work/demo/static/x'),
    ('/brand/x', '/brick-work/demo/static/brickwork/x'),
    ('/fonts/x', '/brick-work/demo/static/fonts/x'),
    ('../static/x', '../static/x'),
    ('/demo/static/x', '/demo/static/x'),
    ('https://example.com/static/x', 'https://example.com/static/x'),
])
def test_copied_demo_html_rewrites_only_root_paths(prefix, path, target):
    from scripts.build_site import rewrite_demo_html
    assert rewrite_demo_html(prefix + path, '/brick-work/demo/') == prefix + target


@pytest.mark.parametrize('name', ['web/toni/offline.html', 'brickwork/head-block.html'])
def test_copied_demo_html_root_paths_use_demo_base(site, name):
    from scripts.build_site import site_base
    source = (ROOT / 'static' / name).read_text()
    built = (site / 'demo/static' / name).read_text()
    roots = re.findall(r'''["'(=](/(?:static|brand|fonts)/[^"'\s)<>]+)''', source)
    assert roots
    for root in roots:
        _, kind, path = root.split('/', 2)
        mapped = {'static': '/static/', 'brand': '/static/brickwork/', 'fonts': '/static/fonts/'}[kind] + path
        assert site_base() + 'demo' + mapped in built
    assert not re.search(r'''["'(=]/(?:static|brand|fonts)/''', built)


def test_install_and_coming_from_pages_exist_and_cross_link(site):
    expected = {'install/': 'Install Brick Work in about five minutes.', 'coming-from/rebrickable/': 'Coming from Rebrickable or Brickset.',
                'coming-from/bricklink/': 'Coming from BrickLink.', 'coming-from/bricktracker/': 'Coming from BrickTracker.',
                'coming-from/other/': 'Coming from another app.'}
    for path, heading in expected.items():
        text = (site / path / 'index.html').read_text()
        assert heading in text, path
        assert 'aria-current="page"' in text.split('</header>')[0] or path.startswith('coming-from/'), path
    for path in expected:
        if path.startswith('coming-from/'):
            rows = (site / path / 'index.html').read_text().split('<div class="rows">')[1].split('</div>')[0]
            assert rows.count('<a href=') == 4          # the four sibling rows on every coming-from page


def test_changelog_page_lists_every_release_with_an_anchor_and_an_atom_feed(site):
    import xml.etree.ElementTree as ET
    from brickwork.version import __version__
    from scripts.build_site import releases
    versions = [version for version, *_ in releases()]
    assert versions[0] == __version__ and versions[-1] == '0.5.0' and len(versions) == len(set(versions)) >= 8
    text = (site / 'changelog/index.html').read_text()
    for version in versions:
        assert f'<details class="rel" id="v{version}"' in text, version
    assert text.count('<details class="rel"') == len(versions) and text.count('<details class="rel" id="v') == len(versions)
    assert f'id="v{__version__}" open' in text and text.count(' open>') == 1          # only the newest is open
    assert 'href="feed.xml"' in text and 'application/atom+xml' in text
    feed = ET.fromstring((site / 'changelog/feed.xml').read_text())
    entries = feed.findall('{http://www.w3.org/2005/Atom}entry')
    assert [e.find('{http://www.w3.org/2005/Atom}title').text for e in entries] == [f'Brick Work {v}' for v in versions]


def test_about_page_and_the_nav_that_reaches_it(site):
    text = (site / 'about/index.html').read_text()
    assert 'Ulf Weihbold, Linz' in text and 'MIT' in text and 'decision records in the repository' in text
    assert 'github.com/' in text and 'aria-current="page"' in text.split('</header>')[0]
    assert '>About</a>' in (site / 'index.html').read_text()


def test_every_site_page_has_its_own_description_canonical_and_social_tags_and_no_noindex(site):
    from scripts.build_site import origin, site_base
    seen = set()
    for path in ('', 'install/', 'workflows/', 'changelog/', 'about/', 'use-cases/', 'impressum/', 'privacy/', 'coming-from/rebrickable/',
                 'coming-from/bricklink/', 'coming-from/bricktracker/', 'coming-from/other/'):
        text = (site / path / 'index.html').read_text()
        description = re.search(r'<meta name="description" content="([^"]+)"', text)[1]
        assert description not in seen, path
        seen.add(description)
        assert f'<link rel="canonical" href="{origin() + site_base() + path}">' in text, path
        for tag in ('og:title', 'og:description', 'og:url', 'twitter:card'):
            assert tag in text, (path, tag)
    for file in site.rglob('*.html'):
        assert 'noindex' not in file.read_text(), file


def test_home_page_has_software_application_structured_data(site):
    import json
    text = (site / 'index.html').read_text()
    data = json.loads(re.search(r'<script type="application/ld\+json">(.+?)</script>', text)[1])
    assert data['@type'] == 'SoftwareApplication' and data['name'] == 'Brick Work' and data['offers']['price'] == '0'
    assert data['author']['name'] == 'Ulf Weihbold' and data['license'].endswith('/MIT')


def test_robots_and_sitemaps_point_at_this_sites_address(site):
    import xml.etree.ElementTree as ET
    from scripts.build_site import origin, site_base
    base = origin() + site_base()
    assert (site / 'robots.txt').read_text() == (f'User-agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train=yes\nAllow: /\n\n# For AI assistants: {base}llms.txt (the short facts) and {base}llms-full.txt (the key docs in one file)\n'
                                                f'Sitemap: {base}sitemap.xml\n')
    ns = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    index = ET.fromstring((site / 'sitemap.xml').read_text())
    assert [e.find(ns + 'loc').text for e in index] == [f'{base}sitemap-pages.xml', f'{base}docs/sitemap.xml']
    locs = [e.find(ns + 'loc').text for e in ET.fromstring((site / 'sitemap-pages.xml').read_text())]
    assert base in locs and f'{base}install/' in locs and f'{base}coming-from/other/' in locs and f'{base}demo/' in locs
    assert all(loc.startswith(base) for loc in locs) and len(locs) == len(set(locs))
    assert (site / 'docs/sitemap.xml').is_file()


def test_every_sitemap_page_but_the_demo_has_a_lastmod_on_a_full_clone(site):
    import subprocess
    import xml.etree.ElementTree as ET
    from scripts.build_site import ROOT
    if subprocess.run(['git', 'rev-parse', '--is-shallow-repository'], cwd=ROOT, capture_output=True, text=True).stdout.strip() != 'false':
        pytest.skip('lastmod is left out on a shallow clone')
    ns = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    entries = {e.find(ns + 'loc').text: e.find(ns + 'lastmod') for e in ET.fromstring((site / 'sitemap-pages.xml').read_text())}
    missing = [loc for loc, mod in entries.items() if mod is None and not loc.endswith('/demo/')]
    assert missing == []
    assert len([loc for loc in entries if '/questions/' in loc and not loc.endswith('/questions/')]) == len(QUESTION_SLUGS)


def test_no_page_names_the_pages_address_on_the_apex_build(site):
    from scripts.build_site import site_base
    if site_base() != '/':
        pytest.skip('only the apex build')
    leaks = [str(f.relative_to(site)) for f in site.rglob('*') if f.suffix in ('.html', '.js', '.json', '.txt', '.xml')
             and 'github.io' in f.read_text(errors='ignore')]
    assert not leaks, leaks


def test_analytics_script_is_on_the_site_pages_only_and_the_privacy_page_matches(site):
    tag = 'static.cloudflareinsights.com/beacon.min.js'
    for path in ('', 'install/', 'workflows/', 'changelog/', 'about/', 'privacy/', 'coming-from/rebrickable/'):
        text = (site / path / 'index.html').read_text()
        assert text.count(tag) == 1, path
        assert text.count('clarity.ms/tag/') == 1 and text.index('clarity.ms/tag/') < text.index('</head>'), path
        assert text.count('googletagmanager.com/gtm.js') == 1 and text.index('googletagmanager.com/gtm.js') < text.index('</head>'), path
        assert text.index("gtag('consent', 'default'") < text.index('googletagmanager.com/gtm.js'), path     # consent is denied before the container loads
        default = text[text.index("gtag('consent', 'default'"):text.index('wait_for_update')]
        assert default.count("'denied'") == 4 and "'granted'" not in default, path
    for file in list((site / 'docs').rglob('*.html')) + list((site / 'demo').rglob('*.html')):
        assert tag not in file.read_text() and 'clarity.ms' not in file.read_text() and 'googletagmanager' not in file.read_text(), file
    privacy = (site / 'privacy/index.html').read_text()
    assert 'Cloudflare Web Analytics' in privacy and 'Microsoft Clarity' in privacy and '_clck' in privacy and 'Google Tag Manager' in privacy and 'Google Analytics' in privacy and 'hosted here' not in privacy     # the picture line waits for the Rebrickable pictures (#332)


def test_every_site_page_offers_the_releases_feed_once(site):
    """The website session's crawl (13.11.): the Atom link was only on /changelog/; every marketing page carries it, once, and it reaches feed.xml."""
    pages = [p for p in site.rglob('index.html') if p.relative_to(site).parts[0] not in ('docs', 'demo')] + [site / '404.html']
    assert len(pages) >= 8
    for page in pages:
        links = re.findall(r'<link rel="alternate" type="application/atom\+xml"[^>]*href="([^"]+)"', page.read_text())
        assert len(links) == 1, page
        assert (page.parent / links[0]).resolve() == (site / 'changelog' / 'feed.xml').resolve() or page.name == '404.html', (page, links)


def test_every_page_points_assistants_at_llms_txt(site):
    """The head link and the footer link are on every built site page, and the two files they name are built (the link is relative, so it fits each depth)."""
    assert (site / 'llms.txt').is_file() and (site / 'llms-full.txt').is_file()
    pages = [p for p in site.rglob('index.html') if p.relative_to(site).parts[0] not in ('docs', 'demo')] + [site / '404.html']
    assert len(pages) > 10
    for page in pages:
        text = page.read_text()
        depth = len(page.relative_to(site).parts) - 1
        up = '../' * depth if page.name != '404.html' else None
        links = re.findall(r'<link rel="alternate" type="text/markdown" href="([^"]+)"', text)
        assert len(links) == 1 and links[0].endswith('llms.txt'), page
        from scripts.build_site import site_base
        assert links[0] == ((up if up is not None else site_base()) + 'llms.txt'), page
        assert re.search(r'<li><a href="[^"]*llms\.txt">For AI assistants</a></li>', text), page


def test_docs_and_demo_pages_carry_the_site_top_bar(site):
    """#363 (Ulf, 13.11.): every page of /docs/ and /demo/ has the site's top bar so a visitor can get back. Redirect stubs and the demo's static/
    asset templates are not pages; the bar's links are absolute from the site base and it adds no analytics tag."""
    from scripts.build_site import site_base
    base = site_base()
    for area in ('docs', 'demo'):
        pages = [f for f in (site / area).rglob('*.html') if not (area == 'demo' and f.relative_to(site / 'demo').parts[0] == 'static')]
        shown = [f for f in pages if not ('http-equiv="refresh"' in f.read_text() and '<body' not in f.read_text())]
        assert len(shown) > 20 and len(pages) - len(shown) <= 2, area
        for file in shown:
            text = file.read_text()
            assert text.count('<header class="bw-topbar" data-bw-topbar>') == 1, file
            assert f'<a href="{base}install/">Install</a>' in text and f'<a href="{base}docs/">Docs</a>' in text, file
    docs = (site / 'docs/index.html').read_text()
    assert '.md-header{top:var(--bw-topbar-h)}' in docs and '.bs-aside' not in docs
    sets = (site / 'demo/collection/sets/index.html').read_text()
    assert '.bs-aside' in sets and '.md-header' not in sets
    assert 'cloudflareinsights' not in docs + sets


def test_the_demo_entry_has_share_tags(site):
    from scripts.build_site import origin, site_base
    text = (site / 'demo/index.html').read_text()
    assert 'http-equiv="refresh"' in text
    assert f'<link rel="canonical" href="{origin() + site_base()}demo/">' in text
    assert 'property="og:image"' in text
    assert 'property="og:title" content="Brick Work demo"' in text
    assert text.count('name="description"') == 1   # one tag: seo_head does not write it, the stub does
    from scripts.build_site import DEMO_DESCRIPTION
    assert f'name="description" content="{DEMO_DESCRIPTION}"' in text and f'property="og:description" content="{DEMO_DESCRIPTION}"' in text
    assert f'property="og:url" content="{origin() + site_base()}demo/"' in text


def test_moved_page_stubs_name_the_new_page_as_canonical(site):
    """Search Console (16.11.) reported the /api/ and /mcp/ stubs as 'Duplicate without user-selected canonical': each stub names its target as canonical."""
    from scripts.build_site import MOVED, origin, site_base
    for folder, _, target in MOVED:
        text = (site / folder / 'index.html').read_text()
        assert text.count('rel="canonical"') == 1, folder
        assert f'<link rel="canonical" href="{origin()}{site_base()}{target}">' in text, folder


def test_every_demo_page_names_the_demo_entry_as_canonical(site):
    """Search Console (16.11.) listed /demo/collection/sets/ as 'Duplicate without user-selected canonical': the demo's pages show one invented collection, so each names the entry, /demo/, as canonical."""
    from scripts.build_site import origin, site_base
    canonical = f'rel="canonical" href="{origin()}{site_base()}demo/"'
    pages = [p for p in (site / 'demo').rglob('*.html') if p.relative_to(site / 'demo').parts[0] != 'static']
    assert len(pages) > 5
    for page in pages:
        assert page.read_text().count(canonical) == 1, page


@pytest.mark.parametrize('opening,summary', [
    ('A feature release. The schema moves in place.', 'A feature release.'),
    ('- **One pull marks the Lost Parts** (#513). A set that had no copy.', 'One pull marks the Lost Parts.'),
    ('- **Is `config.yml` read?** (#1). More.', 'Is config.yml read?'),
])
def test_latest_release_summary_is_plain_text(tmp_path, monkeypatch, opening, summary):
    """The home page's What's new lede is prose: a release that opens with its entries gives the first entry's title, not raw Markdown."""
    import scripts.build_site as build_site
    (tmp_path / 'CHANGELOG.md').write_text(f'# Changelog\n\n## Unreleased\n\n## Brick Work 9.9.9 (schema 4.6) · 2026-11-19\n\n{opening}\n')
    monkeypatch.setattr(build_site, 'ROOT', tmp_path)
    assert build_site.latest_release() == ('9.9.9', '4.6', '2026-11-19', summary)


def test_feed_summary_of_a_release_that_opens_with_entries(tmp_path, monkeypatch):
    """The Atom feed's summary is plain text too: the first entry's title, no Markdown bullet or bold (#482 review of the lede fix)."""
    import scripts.build_site as build_site
    (tmp_path / 'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n\n## Brick Work 9.9.9 (schema 4.6) · 2026-11-19\n\n'
                                           '- **One pull marks the Lost Parts** (#513). More.\n\n- **Second** (#514).\n')
    monkeypatch.setattr(build_site, 'ROOT', tmp_path)
    feed = build_site.atom_feed()
    assert '<summary>One pull marks the Lost Parts.</summary>' in feed and '**' not in feed


# The question pages (#544) may name LEGO® under the trademark rules (LEGO Fair Play; Ulf, 2026-11-20: "Titles and text"): as an adjective with
# the ® on every use, or as "the LEGO Group" in the disclaimer; never "LEGOs", "LEGO®s", a bare "LEGO" or another casing, and never in a site path.
NAME_ALLOWED = re.compile(r'LEGO® (?=\w)|(?<=\b[Tt]he )LEGO(?= Group\b)')
NAME_ANY = re.compile(r'lego', re.I)
DISCLAIMER = 'LEGO® is a trademark of the LEGO Group of companies, which does not sponsor, authorize or endorse this project.'
TITLE_SUFFIX = ' · Brick Work'
# The seven pages in the launch kit's order (marketing, § Question pages; Ulf, 2026-11-20: "All seven as ranked").
QUESTION_SLUGS = ('missing-parts-used-set', 'used-set-worth', 'sets-in-a-bulk-lot', 'buy-missing-parts', 'store-and-label-parts',
                  'build-from-loose-parts', 'track-your-collection')


class Readable(HTMLParser):
    """The words a reader or a search engine reads (text, title, description, alt and label attributes) and the page's link targets."""
    READ = ('content', 'alt', 'title', 'aria-label')
    LINKS = ('href', 'src', 'action')

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.words, self.links, self.skip = [], [], 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        for key, value in attrs:
            if value and key in self.READ:
                self.words.append(value)
            elif value and key in self.LINKS:
                self.links.append(value)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.words.append(data)


def name_use_errors(text):
    """Each wrong use of the name in a built page: the snippet of words around it, or the site link that carries it."""
    found = Readable(text)
    errors = []
    for words in found.words:
        allowed = {m.start() for m in NAME_ALLOWED.finditer(words)}
        errors += [words[max(0, m.start() - 20):m.end() + 20] for m in NAME_ANY.finditer(words) if m.start() not in allowed]
    own = [link for link in found.links if not re.match(r'^[a-z][a-z0-9+.-]*:|^//', link)]   # relative or rooted: the site's own paths
    errors += [link for link in own if NAME_ANY.search(unquote(link))]
    return errors


@pytest.mark.parametrize('words', [
    'Which parts is my used LEGO® set missing?', 'Most LEGO® sets come with a parts list.',
    'not affiliated with the LEGO Group, Rebrickable', 'The LEGO Group sells single parts.', DISCLAIMER])
def test_the_name_rule_allows_the_adjective_and_the_group(words):
    assert name_use_errors(f'<p>{words}</p>') == []


@pytest.mark.parametrize('words', [
    'My LEGOs are in a box.', 'Sort your LEGO®s.', 'I like LEGO.', 'A LEGO set', 'Lego sets', 'lego parts', 'LEGO®', 'LEGO® .', 'the LEGO shop'])
def test_the_name_rule_fails_every_other_use(words):
    assert name_use_errors(f'<p>{words}</p>')


def test_the_name_rule_reads_titles_descriptions_and_alt_text_but_allows_external_links():
    assert name_use_errors('<title>LEGO sets</title>')
    assert name_use_errors('<meta name="description" content="Your Lego collection">')
    assert name_use_errors('<img src="a.png" alt="A LEGO brick">')
    assert name_use_errors('<a href="../questions/lego-parts/">Parts</a>') == ['../questions/lego-parts/']
    assert name_use_errors('<a href="/brick-work/questions/LEGO-sets/">Sets</a>')
    assert name_use_errors('<a href="https://www.lego.com/en-gb/pick-and-build/pick-a-brick">Pick a Brick</a>') == []
    assert name_use_errors('<script>const lego = 1</script>') == []


def test_a_question_page_rendered_by_the_site_passes_the_name_rule_and_carries_the_disclaimer():
    from scripts.build_site import page
    title = 'Which parts is my used LEGO® set missing?'
    text = page(title, '<h1>Which parts is my used LEGO® set missing?</h1><p>Check each part against the LEGO® parts list.</p>', 2,
                current=None, path='questions/missing-parts-used-set/', description='How to check a used LEGO® set for missing parts.')
    assert name_use_errors(text) == []
    assert DISCLAIMER in text.split('<footer', 1)[1]


def test_question_pages_name_the_brand_correctly_and_carry_the_disclaimer(site):
    from scripts.build_site import site_urls
    pages = sorted(site.glob('questions/*/index.html'))
    assert [file.parent.name for file in pages] == sorted(QUESTION_SLUGS)
    llms = (site / 'llms.txt').read_text()
    for file in pages:
        slug = file.parent.name
        text = file.read_text()
        assert name_use_errors(text) == [], slug
        assert not NAME_ANY.search(slug), slug
        assert DISCLAIMER in text.split('<footer', 1)[1], slug
        title = html.unescape(re.search(r'<title>(.+?)</title>', text)[1])
        h1 = html.unescape(re.sub(r'<[^>]+>', '', re.search(r'<h1[^>]*>(.+?)</h1>', text, re.S)[1])).strip()
        assert title.endswith(TITLE_SUFFIX) and len(title) - len(TITLE_SUFFIX) <= 47 and title.removesuffix(TITLE_SUFFIX) == h1, slug
        assert f'questions/{slug}/' in site_urls(site) and f'questions/{slug}/)' in llms, slug
        # The last step is the demo or, where the demo cannot show the feature, the docs; never the install (#544).
        last = re.findall(r'<a class="btn primary" href="([^"]+)"', text)[-1]
        assert re.match(r'(\.\./)+(demo|docs)/', last), (slug, last)
    # The footer every site page shares passes the rule too, so the disclaimer's own wording is allowed where it stands.
    footer = (site / 'about/index.html').read_text().split('<footer', 1)[1]
    assert name_use_errors(footer) == []


def test_the_use_cases_heading_and_description_count_the_cards_alike():
    """The number of moments is said twice (the h1 and the page description); both follow the cards (marketing, #526)."""
    from scripts import build_site
    source = (ROOT / 'scripts' / 'site' / 'use-cases.md').read_text()
    words = ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve')
    count = len(re.findall(r'<h3 class="layout-39">', source))
    heading = re.search(r'<h1[^>]*>(\w+) moments', source).group(1).lower()
    assert heading == words[count] and build_site.MD_DESCRIPTIONS['use-cases'].lower().startswith(f'{words[count]} moments')


def test_the_questions_hub_lists_every_page_passes_the_lego_rule_and_the_structured_data_matches(site):
    """Review of #679 and the SEO review (23.11.): the hub is checked like the pages it lists; breadcrumbs are links; BreadcrumbList, ItemList and HowTo parse."""
    import json
    hub = (site / 'questions/index.html').read_text()
    assert name_use_errors(hub) == []
    assert DISCLAIMER in hub.split('<footer', 1)[1]
    assert [href for href in re.findall(r'<a href="\.\./questions/([^"]+)/"><span><b>', hub)] == list(QUESTION_SLUGS)
    ld = lambda text: [json.loads(block) for block in re.findall(r'<script type="application/ld\+json">(.+?)</script>', text)]
    assert [item['@type'] for item in ld(hub)] == ['BreadcrumbList', 'ItemList']
    assert [e['url'].rsplit('/', 2)[-2] for e in ld(hub)[1]['itemListElement']] == list(QUESTION_SLUGS)
    for slug in QUESTION_SLUGS:
        text = (site / f'questions/{slug}/index.html').read_text()
        types = [item['@type'] for item in ld(text)]
        assert types[0] == 'BreadcrumbList' and 'HowTo' in types, slug
        assert '<a href="../../">Home</a> / <a href="../../questions/">Questions</a>' in text, slug
        assert len(ld(text)[types.index('HowTo')]['step']) >= 2, slug
        assert name_use_errors(text) == [], slug
