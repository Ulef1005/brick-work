"""/llms.txt names the current release and links only to files that exist (brick-work-marketing, 2026-11-09)."""

import re
from pathlib import Path

from brickwork.version import __version__
from scripts.build_site import SITE, llms_txt

ROOT = Path(__file__).resolve().parent.parent


def test_every_repository_link_in_the_source_exists():
    source = (SITE / 'llms.md').read_text()
    links = re.findall(r'\]\((?!https?://|#|\{site\})([^)\s]+)\)', source)   # {site} links are the site's own pages, filled at build time
    assert links, 'llms.md links the README and the docs'
    missing = [link for link in links if not (ROOT / link).is_file()]
    assert not missing, f'llms.md links files that do not exist: {missing}'


def test_built_file_has_the_version_and_absolute_links_only():
    text = llms_txt()
    assert text.startswith('# Brick Work\n\n> ')
    assert f'Version {__version__}.' in text and f'brick-work:{__version__}' in text and f'v{__version__}' in text
    assert '{' not in text, 'every placeholder is filled'
    assert not re.findall(r'\]\((?!https://)[^)]*\)', text), 'every link is absolute'
    assert 'https://raw.githubusercontent.com/Ulef1005/brick-work/main/docs/how-to/install-docker-desktop.md' in text


def test_llms_full_inlines_the_linked_pages_and_names_the_long_one():
    from scripts.build_site import LLMS_FULL_LINKED_ONLY, llms_full
    text = llms_full()
    assert text.startswith('# Brick Work\n\n> ')
    assert '<!-- source: https://raw.githubusercontent.com/Ulef1005/brick-work/main/docs/how-to/pick-parts.md -->' in text
    assert not text.count('\n---\naudience:'), 'front matter is dropped'
    assert not re.findall(r'^!\[', text, flags=re.M), 'no picture lines in a text file'
    for long in LLMS_FULL_LINKED_ONLY:
        assert f'<!-- source: https://raw.githubusercontent.com/Ulef1005/brick-work/main/{long} -->' not in text
        assert f'- https://raw.githubusercontent.com/Ulef1005/brick-work/main/{long}\n' in text
    assert not [link for link in re.findall(r'\]\(([^)\s]+)\)', text) if not link.startswith(('https://', 'http://localhost', '#'))], 'links are absolute'
    assert len(text) < 150_000


def test_llms_txt_points_at_the_full_file():
    assert '{site}llms-full.txt' in (SITE / 'llms.md').read_text()
