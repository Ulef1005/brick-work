"""The landing, use-case and workflow pages: every internal link resolves, no private material, no external images."""
import re
from pathlib import Path

FORBIDDEN = ('test instance', '192.168.', '/Users/', 'op://')


def test_the_site_pages_link_and_stay_clean(tmp_path):
    from scripts.build_site import build
    site = build(tmp_path / 'site')
    for name in ('index.html', 'use-cases/index.html', 'workflows/index.html', 'docs/index.html'):
        page = site / name
        text = page.read_text()
        for word in FORBIDDEN:
            assert word not in text, f'{name}: {word}'
        assert not re.search(r'<img[^>]+src="https?://', text), f'{name}: external image'
        for target in re.findall(r'(?:href|src)="([^"#]+)"', text):
            if re.match(r'^[a-z][a-z0-9+.-]*:', target):
                continue
            resolved = (page.parent / target).resolve()
            if resolved.is_dir():
                resolved = resolved / 'index.html'
            assert resolved.exists(), f'{name}: broken link {target}'


def test_the_landing_page_says_the_tagline_and_marks_planned_work(tmp_path):
    from scripts.build_site import build
    text = (build(tmp_path / 'site') / 'index.html').read_text()
    assert 'The workbench for your brick collection' in text
    assert 'Planned, not built yet' in text
    assert 'LEGO' not in text.split('<footer')[0]


def test_the_demo_is_part_of_the_site_and_linked(tmp_path):
    from scripts.build_site import build
    site = build(tmp_path / 'site')
    assert (site / 'demo/index.html').is_file() and (site / 'demo/demo-manifest.json').is_file()
    assert 'href="demo/"' in (site / 'index.html').read_text()
