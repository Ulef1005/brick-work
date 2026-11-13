"""The docs site's nav: and its pages agree (scripts/check_nav.py, App Docs Standard)."""
from pathlib import Path

from scripts.check_nav import problems

ROOT = Path(__file__).resolve().parents[1]


def config(tmp_path, nav, exclude='', pages=('index.md', 'how-to/a.md')):
    for page in pages:
        (tmp_path / 'docs' / page).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / 'docs' / page).write_text('# Page\n')
    lines = ['docs_dir: docs', 'exclude_docs: |'] + [f'  {line}' for line in exclude.splitlines()] + ['nav:'] + [f'  {line}' for line in nav]
    path = tmp_path / 'mkdocs.yml'
    path.write_text('\n'.join(lines) + '\n')
    return path


def test_the_real_nav_names_every_built_page_and_only_existing_ones():
    assert problems(ROOT / 'mkdocs.yml') == []


def test_a_nav_entry_to_a_missing_page_fails(tmp_path):
    found = problems(config(tmp_path, ['- index.md', '- how-to/a.md', '- how-to/gone.md']))
    assert found == ['nav: names how-to/gone.md, which is not in docs/']


def test_a_built_page_missing_from_nav_fails(tmp_path):
    found = problems(config(tmp_path, ['- index.md']))
    assert found == ['docs/how-to/a.md is built but not in nav: (add it, or exclude it in exclude_docs)']


def test_an_excluded_page_needs_no_entry_and_may_not_have_one(tmp_path):
    assert problems(config(tmp_path, ['- index.md'], exclude='how-to/a.md')) == []
    found = problems(config(tmp_path, ['- index.md', '- how-to/a.md'], exclude='how-to/a.md'))
    assert found == ['nav: names how-to/a.md, which exclude_docs leaves out of the site']


def test_titled_entries_sections_links_and_duplicates(tmp_path):
    nav = ['- Home:', '    - index.md', '    - "Changelog": ../changelog/', '    - "GitHub": https://github.com/',
           '- Guide:', '    - Tasks:', '        - "A task": how-to/a.md', '        - how-to/a.md']
    assert problems(config(tmp_path, nav)) == ['nav: names how-to/a.md twice']


def test_no_nav_at_all_fails(tmp_path):
    path = tmp_path / 'mkdocs.yml'
    (tmp_path / 'docs').mkdir()
    path.write_text('docs_dir: docs\n')
    assert problems(path) == ['mkdocs.yml has no nav: (the App Docs Standard asks for an explicit one)']
