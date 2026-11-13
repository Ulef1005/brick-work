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


@pytest.fixture(scope='module', params=['default', 'apex'])
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
                    if tag in ('link', 'script', 'img', 'source') and attrs.get('rel') != 'canonical':
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
    for href in [''] + [href for _, href in NAV if '#' not in href] + [folder + '/' for folder, _, _ in MOVED]:
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
    body = text.split('<main class="home">')[1].split('</main>')[0]
    plain = re.sub(r'<[^>]+>', '', body)
    assert "Don't just manage your collection. Work with it." in plain
    assert '<span class="clay">Work with it.</span>' in body
    assert '.clay{color:var(--tw-accent-text)}' in (site / 'assets/marketing.css').read_text()
    assert "The workbench for your collection that you didn't know existed" in html.unescape(plain)
    for label in ('Who it is for', 'The workbench', 'Install', 'Coming from another tool', 'Documentation', "What's new"):
        assert f'<span class="label">{label}</span>' in body, label
    assert body.count('class="card"><h3>You ') == 6          # the six "Who it is for" boxes
    assert body.count('class="card wf-card"') == 9           # nine workflow cards
    assert 'id="install"' in body and 'href="demo/"' in body
    assert 'LEGO' not in body
    assert 'not affiliated with the LEGO Group, Rebrickable, Brickset or BrickLink' in text
    from brickwork.version import __version__
    assert f'{__version__} · tested on a real collection' in body and f'Brick Work {__version__}' in body
    assert len(text.encode()) + sum((site / 'assets' / n).stat().st_size for n in ('site.css', 'marketing.css', 'site.js')) < 130_000


def test_walkthroughs_and_no_js_content(site):
    text = (site / 'workflows/index.html').read_text()
    for name, count in (('check-set-parts', 5), ('part-picker', 4), ('matcher', 2)):
        section = text.split(f'id="{name}"', 1)[1].split('</section>', 1)[0]
        assert section.count('<li>') == count
        assert 'data-back' in section and 'data-next' in section
        assert 'data-step-status' in section
        assert section.count('<figure data-frame=') == count
        assert section.count('<img') == count
        assert 'not in the demo yet' not in section
    for removed in ('desktop-frame', 'device-switch', 'data-device', 'desktop-1440'):
        assert removed not in text
    assert text.count('class="phone-frame"') == 11
    screenshots = [attrs for tag, attrs in Elements(text).elements
                   if tag in ('img', 'source') and '/img/' in attrs.get('src', attrs.get('srcset', ''))]
    assert len(screenshots) == 22
    assert all('-phone-' in attrs.get('src', attrs.get('srcset', '')) for attrs in screenshots)
    assert text.count('data-walkthrough') == 3
    assert 'hidden' not in text  # JavaScript alone hides inactive screenshots.


def test_use_cases_have_eight_cards_in_three_groups(site):
    text = (site / 'use-cases/index.html').read_text()
    assert text.count('<article') == 8
    for group in ('uc-table', 'uc-plan', 'uc-scripts'):
        assert f'id="{group}"' in text
    assert 'Planned' in text
    order = next(card for card in text.split('<article') if '<h3 class="layout-39">Receive a parts order' in card)
    assert '12b-count-what-arrived-desktop-1440-light.png' in order


def test_desktop_screenshots_are_only_kept_for_other_pages(site):
    pages = [(site / name).read_text() for name in ('index.html', 'use-cases/index.html')]
    referenced = {Path(attrs[attr]).name for text in pages for tag, attrs in Elements(text).elements
                  for attr in ('src', 'srcset') if tag in ('img', 'source')
                  and 'desktop-' in attrs.get(attr, '')}
    assert len(referenced) == 6
    assert {p.name for p in (ROOT / 'scripts/site/img').glob('*desktop*.png')} == referenced
    assert {p.name for p in (site / 'assets/img').glob('*desktop*.png')} == referenced


@pytest.mark.parametrize('page,stems', [
    ('index.html', [
        '1c-sets-desktop-1440', '3a-matcher-phone-390',
        '3e-start-phone-390', '3c-picker-pick-phone-390', '3a-matcher-phone-390',
        '12b-count-what-arrived-desktop-1440',
    ]),
    ('use-cases/index.html', [
        '3e-finish-gaps-phone-390', '3c-picker-sets-phone-390',
        '12b-count-what-arrived-desktop-1440', '4c-complete-sets-phone-390',
        '12c-list-and-detail-desktop-1440',
    ]),
    ('workflows/index.html', [
        '3b-check-set-parts-phone-390', '3e-start-phone-390', '3e-part-phone-390',
        '3e-finish-gaps-phone-390', '3e-resume-phone-390',
        '3c-picker-sets-phone-390', '3c-picker-sort-phone-390',
        '3c-picker-pick-phone-390', '3c-picker-selector-phone-390',
        '3a-matcher-phone-390', '1d-set-detail-phone-390',
    ]),
])
def test_built_screen_placements(site, page, stems):
    elements = Elements((site / page).read_text()).elements
    images = [Path(attrs['src']).name for tag, attrs in elements
              if tag == 'img' and '/img/' in attrs.get('src', '')]
    sources = [Path(attrs['srcset']).name for tag, attrs in elements
               if tag == 'source' and '/img/' in attrs.get('srcset', '')]
    assert images == [f'{stem}-light.png' for stem in stems]
    assert sources == [f'{stem}-dark.png' for stem in stems]
    if page == 'index.html':
        text = (site / page).read_text()
        assert 'design preview' not in text and 'to capture' not in text


def test_no_unreferenced_screenshots_are_shipped(site):
    referenced = {Path(attrs[attr]).name
                  for name in ('index.html', 'use-cases/index.html', 'workflows/index.html')
                  for tag, attrs in Elements((site / name).read_text()).elements
                  for attr in ('src', 'srcset') if tag in ('img', 'source')
                  and '/img/' in attrs.get(attr, '')}
    assert len(referenced) == 30
    assert {p.name for p in (ROOT / 'scripts/site/img').glob('*')} == referenced
    assert {p.name for p in (site / 'assets/img').glob('*')} == referenced


def picture_scale(name):
    """Phone captures are drawn at twice the pixels (scripts/site_shots.py), so their width and height attributes are half the file's."""
    return 2 if '-phone-' in name or '-390-' in name else 1


def test_images_are_local_small_and_dimensioned(site):
    for png in (ROOT / 'scripts/site/img').glob('*.png'):
        assert png.stat().st_size < 300_000, png.name
    for name in ('index.html', 'use-cases/index.html', 'workflows/index.html'):
        text = (site / name).read_text()
        for tag, attrs in Elements(text).elements:
            if tag == 'source' and '/img/' in attrs.get('srcset', ''):
                dimensions = struct.unpack('>II', local_target(site, site / name, attrs['srcset']).read_bytes()[16:24])
                scale = picture_scale(attrs['srcset'])
                assert dimensions == (scale * int(attrs['width']), scale * int(attrs['height']))
            if tag != 'img':
                continue
            assert attrs.get('loading') == 'lazy' and attrs.get('decoding') == 'async'
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
    in site_shots.PICTURES, so a design-project mock-up cannot come back unnoticed."""
    sys_path = str(ROOT / 'scripts')
    import sys
    sys.path.insert(0, sys_path)
    try:
        import site_shots
    finally:
        sys.path.remove(sys_path)
    stems = set(site_shots.PICTURES)
    shown = set()
    for source in ('README.md', 'scripts/site/landing.html', 'scripts/site/use-cases.md', 'scripts/site/workflows.md'):
        text = (ROOT / source).read_text()
        names = re.findall(r'(?:src|srcset)="[^"]*?/img/(?:readme/)?([^"/]+\.png)"', text)
        names += [f'{stem}-{theme}.png' for stem in re.findall(r'\{pic:([^|}]+)\|', text) for theme in ('light', 'dark')]
        for name in names:
            shown.add(name)
            target = ROOT / ('docs/img/readme' if source == 'README.md' else 'scripts/site/img') / name
            assert target.is_file(), f'{source}: {name} is missing'
            assert re.sub(r'-(light|dark)\.png$', '', name) in stems, f'{source}: {name} is not a capture of the built app'
    assert len(shown) >= 32


NOTE = re.compile(r'placeholder drawings.*?BrickLink and Rebrickable', re.S)


def test_the_placeholder_picture_note_is_on_the_readme_the_landing_page_and_the_demo_banner(site):
    """The demo's pictures are original placeholder drawings; a real install loads its pictures from BrickLink and Rebrickable (core/pictures.py, no key
    needed for those two sources). The README, the landing page and the demo's banner all say so."""
    readme = (ROOT / 'README.md').read_text()
    top = readme.split('<!-- /site:skip -->')[0]
    assert NOTE.search(top.split('</picture>')[-1]), 'the README says it right under the screenshots, inside the block GitHub shows'
    assert NOTE.search((site / 'index.html').read_text())
    shim = (site / 'demo' / 'demo-shim.js').read_text()
    banner = shim.split('// The banner:', 1)[1].split('const realFetch', 1)[0]
    assert NOTE.search(banner)


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


def test_the_apex_build_holds_no_repository_path_anywhere(site):
    # On the custom domain every path starts at /; a leftover /brick-work/ is a 404 there (the demo entry page's meta refresh and the
    # demo manifest are not attributes the path check above reads). GitHub URLs and filesystem examples have a word before the slash.
    from scripts.build_site import site_base
    if site_base() != '/':
        pytest.skip('only the apex build')
    leak = re.compile(r'(?<![\w.\-/])/brick-work/')
    # The changelog page quotes the build_demo.py `--base /brick-work/demo/` option as text, so it is not scanned.
    found = [str(f.relative_to(site)) for f in site.rglob('*') if f.relative_to(site).parts[0] != 'changelog'
             and f.suffix in ('.html', '.css', '.js', '.json', '.txt', '.xml') and leak.search(f.read_text(errors='ignore'))]
    assert not found, found


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
