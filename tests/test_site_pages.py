"""The static site stays complete, local, accessible without JS, and free of private material."""
from html.parser import HTMLParser
from pathlib import Path
import re
import struct
from urllib.parse import unquote, urlsplit

import pytest

from brickwork.demo.privacy import pattern

PRIVATE = pattern()
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
    path = unquote(urlsplit(url).path)
    # Demo uses the Pages repository prefix and a real document base.
    if path.startswith('/brick-work/'):
        return site / path[len('/brick-work/'):]
    return site / path.lstrip('/') if path.startswith('/') else page.parent / path


@pytest.fixture(scope='module')
def site(tmp_path_factory):
    from scripts.build_site import build
    return build(tmp_path_factory.mktemp('pages') / 'site')


def test_every_page_and_asset_resolves_without_external_requests(site):
    # Copied demo source templates are assets, not exported application pages.
    pages = list(site.rglob('index.html'))
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
                    if tag in ('link', 'script', 'img', 'source'):
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
    from scripts.build_site import PAGES

    for _, href in PAGES:
        if href == 'demo/':  # The demo uses the app's own icon links.
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
    sections = [attrs['class'].split()[0] for tag, attrs in Elements(text).elements if tag == 'section']
    assert sections == list(SECTIONS)
    assert 'Finish the sets you started.' in text
    assert 'the workbench for your brick collection' in text
    assert 'Planned, not built yet' in text
    assert 'LEGO' not in text.split('<footer')[0]
    assert 'href="demo/"' in text
    assert len(text.encode()) + (site / 'assets/site.css').stat().st_size + (site / 'assets/site.js').stat().st_size < 100_000


def test_walkthroughs_and_no_js_content(site):
    text = (site / 'workflows/index.html').read_text()
    for name, count in (('check-set-parts', 5), ('part-picker', 4), ('matcher', 2)):
        section = text.split(f'id="{name}"', 1)[1].split('</section>', 1)[0]
        assert section.count('<li>') == count
        assert 'data-back' in section and 'data-next' in section
        assert 'data-step-status' in section
        if name == 'matcher':
            assert '<img' not in section and 'not in the demo yet' in section
    assert 'data-device="phone"' in text and 'data-device="desktop"' in text
    assert text.count('data-walkthrough') == 3
    assert 'hidden' not in text  # JavaScript alone hides inactive screenshots.


def test_use_cases_have_eight_cards_in_three_groups(site):
    text = (site / 'use-cases/index.html').read_text()
    assert text.count('<article') == 8
    for group in ('uc-table', 'uc-plan', 'uc-scripts'):
        assert f'id="{group}"' in text
    assert 'Planned' in text
    order = text.split('Receive a parts order', 1)[1].split('</article>', 1)[0]
    assert '<img' not in order


def test_images_are_local_small_and_dimensioned(site):
    for png in (ROOT / 'scripts/site/img').glob('*.png'):
        assert png.stat().st_size < 300_000, png.name
    for name in ('index.html', 'use-cases/index.html', 'workflows/index.html'):
        text = (site / name).read_text()
        for tag, attrs in Elements(text).elements:
            if tag != 'img':
                continue
            assert attrs.get('loading') == 'lazy' and attrs.get('decoding') == 'async'
            assert int(attrs['width']) > 0 and int(attrs['height']) > 0
            if attrs['src'].endswith('.png'):
                dimensions = struct.unpack('>II', local_target(site, site / name, attrs['src']).read_bytes()[16:24])
                assert dimensions == (int(attrs['width']), int(attrs['height']))
        assert '<picture>' in text or '<picture ' in text
        assert 'media="(prefers-color-scheme: dark)"' in text
        assert 'style=' not in text and '{{' not in text and '<sc-' not in text


def test_shared_chrome_and_theme_script(site):
    for name in ('index.html', 'use-cases/index.html', 'workflows/index.html',
                 'docs/index.html', 'api/index.html', 'mcp/index.html'):
        text = (site / name).read_text()
        assert 'data-theme-toggle' in text
        assert re.search(r'<script src="(?:../)?assets/site.js" defer>', text)
        assert 'lockup-horizontal-dark.svg' in text and 'lockup-horizontal.svg' in text
        for label in ('Demo', 'Docs', 'API reference', 'MCP', 'GitHub'):
            assert f'>{label}</a>' in text
    script = (site / 'assets/site.js').read_text()
    assert 'localStorage.getItem' in script and 'localStorage.setItem' in script
    assert 'try {' in script and 'catch' in script
    assert 'prefers-color-scheme: dark' in script
    assert (site / 'demo/demo-manifest.json').is_file()


def test_javascript_theme_device_and_step_state():
    """Exercise the actual script with a tiny DOM, including storage being blocked."""
    import shutil
    import subprocess
    if not shutil.which('node'):
        pytest.skip('Node is unavailable')
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
  const devices = ['phone', 'desktop'].map(device => Object.assign(new Element(), {dataset:{device}}));
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
    querySelectorAll:selector => ({'picture source':[source], '[data-device]':devices, '[data-walkthrough]':[flow]}[selector])
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
  devices[1].click(); assert.equal(classes.has('desktop-device'), true);
  assert.equal(devices[1].attrs['aria-pressed'], 'true');
  devices[0].click(); assert.equal(classes.has('desktop-device'), false);
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
