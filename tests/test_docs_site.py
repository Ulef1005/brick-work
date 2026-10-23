"""The user-docs site renders what the docs are written in and loads nothing from outside (App Standard, Maintenance § Rules, User docs)."""
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FENCE = '# Fence\n\n```json\n{\n  "a": 1\n}\n```\n'


def build(tmp_path):
    """Build a copy of mkdocs.yml and docs/ with one extra page holding a fenced block."""
    shutil.copytree(ROOT / 'docs', tmp_path / 'docs')
    (tmp_path / 'docs/reference/fence.md').write_text(FENCE)
    config = yaml.safe_load((ROOT / 'mkdocs.yml').read_text())
    config['site_dir'] = str(tmp_path / 'site')
    (tmp_path / 'mkdocs.yml').write_text(yaml.safe_dump(config, sort_keys=False))
    zensical = Path(sys.executable).with_name('zensical')
    subprocess.run((str(zensical) if zensical.exists() else 'zensical', 'build', '--strict', '--clean',
                    '--config-file', str(tmp_path / 'mkdocs.yml')), check=True, cwd=tmp_path, capture_output=True)
    return tmp_path / 'site'


def test_fenced_code_renders_as_a_block(tmp_path):
    html = (build(tmp_path) / 'reference/fence/index.html').read_text()
    assert '<pre' in html, 'fenced code rendered inline: mkdocs.yml needs pymdownx.superfences'


def test_site_loads_no_external_fonts(tmp_path):
    site = build(tmp_path)
    for page in site.rglob('*.html'):
        text = page.read_text()
        assert 'fonts.googleapis.com' not in text and 'fonts.gstatic.com' not in text, page
