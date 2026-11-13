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


def test_use_cases_have_eight_cards_in_three_groups(site):
    text = (site / 'use-cases/index.html').read_text()
    assert text.count('<article') == 8
    for group in ('uc-table', 'uc-plan', 'uc-scripts'):
        assert f'id="{group}"' in text
    assert 'Planned' in text
    order = next(card for card in text.split('<article') if '<h3 class="layout-39">Receive a parts order' in card)
    assert '<picture' not in order          # no capture while the demo's pictures are placeholders (the screenshots test below)


def test_site_pages_show_no_screenshot_until_the_pictures_are_real(site):
    """Ulf, 2026-11-13: no image with placeholder pictures. The demo's drawings are placeholders, so no page of the site shows a capture of it;
    the captures come back with the Rebrickable pictures (#332), and then this test names the pages that carry them."""
    assert not (site / 'assets/img').exists()
    for page in site.glob('*/index.html'):
        if page.parts[-2] in ('docs', 'demo'):
            continue
        for tag, attrs in Elements(page.read_text()).elements:
            assert '/img/' not in attrs.get('src', '') + attrs.get('srcset', ''), (page, attrs)
    assert not [t for t, a in Elements((site / 'index.html').read_text()).elements if t == 'img' and 'img/' in a.get('src', '')]


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
    for source in ('README.md', 'scripts/site/landing.html', 'scripts/site/use-cases.md', 'scripts/site/pages/workflows.html'):
        text = (ROOT / source).read_text()
        names = re.findall(r'(?:src|srcset)="[^"]*?/img/(?:readme/)?([^"/]+\.png)"', text)
        names += [f'{stem}-{theme}.png' for stem in re.findall(r'\{pic:([^|}]+)\|', text) for theme in ('light', 'dark')]
        for name in names:
            shown.add(name)
            target = ROOT / ('docs/img/readme' if source == 'README.md' else 'scripts/site/img') / name
            assert target.is_file(), f'{source}: {name} is missing'
            assert re.sub(r'-(light|dark)\.png$', '', name) in stems, f'{source}: {name} is not a capture of the built app'
    assert len(shown) >= 2


NOTE = re.compile(r'placeholder drawings.*?BrickLink and Rebrickable', re.S)   # the README's captures are still the old demo's until they are retaken (#332)
REAL_NOTE = re.compile(r"Rebrickable.*?(plain tile|does not sponsor, authorize or endorse)", re.S)


def test_the_picture_notes_are_on_the_readme_the_landing_page_and_the_demo_banner(site):
    """The demo shows seven real sets with Rebrickable's pictures: the landing page and the demo's banner say so (the banner with the LEGO disclaimer, the
    Fair Play policy's wording), and the README keeps its placeholder note under screenshots that are still of the old demo."""
    readme = (ROOT / 'README.md').read_text()
    top = readme.split('<!-- /site:skip -->')[0]
    assert NOTE.search(top.split('</picture>')[-1]), 'the README says it right under the screenshots, inside the block GitHub shows'
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
    assert (site / 'robots.txt').read_text() == (f'User-agent: *\nAllow: /\n\n# For AI assistants: {base}llms.txt (the short facts) and {base}llms-full.txt (the key docs in one file)\n'
                                                f'Sitemap: {base}sitemap.xml\n')
    ns = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    index = ET.fromstring((site / 'sitemap.xml').read_text())
    assert [e.find(ns + 'loc').text for e in index] == [f'{base}sitemap-pages.xml', f'{base}docs/sitemap.xml']
    locs = [e.find(ns + 'loc').text for e in ET.fromstring((site / 'sitemap-pages.xml').read_text())]
    assert base in locs and f'{base}install/' in locs and f'{base}coming-from/other/' in locs and f'{base}demo/' in locs
    assert all(loc.startswith(base) for loc in locs) and len(locs) == len(set(locs))
    assert (site / 'docs/sitemap.xml').is_file()


def test_no_page_names_the_pages_address_on_the_apex_build(site):
    from scripts.build_site import site_base
    if site_base() != '/':
        pytest.skip('only the apex build')
    leaks = [str(f.relative_to(site)) for f in site.rglob('*') if f.suffix in ('.html', '.js', '.json', '.txt', '.xml')
             and 'github.io' in f.read_text(errors='ignore')]
    assert not leaks, leaks


def test_analytics_script_is_on_the_site_pages_only_and_the_privacy_page_matches(site):
    tag = 'static.cloudflareinsights.com/beacon.min.js'
    for path in ('', 'install/', 'workflows/', 'changelog/', 'about/', 'privacy/'):
        assert (site / path / 'index.html').read_text().count(tag) == 1, path
    for file in list((site / 'docs').rglob('*.html')) + list((site / 'demo').rglob('*.html')):
        assert tag not in file.read_text(), file
    privacy = (site / 'privacy/index.html').read_text()
    assert 'One analytics script' in privacy and 'hosted here' not in privacy     # the picture line waits for the Rebrickable pictures (#332)


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
