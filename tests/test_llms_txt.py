"""/llms.txt names the current release and links only to files that exist (brick-work-marketing, 2026-11-09)."""

import re
from pathlib import Path

from brickwork.version import __version__
from scripts.build_site import SITE, llms_txt

ROOT = Path(__file__).resolve().parent.parent


def test_every_repository_link_in_the_source_exists():
    source = (SITE / 'llms.md').read_text()
    links = re.findall(r'\]\((?!https?://|#)([^)\s]+)\)', source)
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
