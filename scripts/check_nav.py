"""The docs site's nav: and its pages agree (App Docs Standard, ai-wiki apps/references/app-docs-standard).

    python scripts/check_nav.py [mkdocs.yml]

Zensical's strict build passes a nav: entry that points at a missing page (it builds a dead link) and builds a page that
no nav: entry names without a word (an orphan). This check fails on both: every nav: entry that is a path names a file
in docs_dir, and every Markdown page Zensical builds (docs_dir minus exclude_docs) is in nav:. Entries that are URLs
(scheme or a leading slash) or point outside docs_dir with ../ are links, not pages, and are not checked here.
"""
import posixpath
import re
import sys
from pathlib import Path

import pathspec
import yaml

ROOT = Path(__file__).resolve().parents[1]


def nav_paths(nav):
    """Every target of a nav: tree, in order: a bare string or the value of a one-entry mapping, recursively."""
    for item in nav or ():
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for value in item.values():
                if isinstance(value, list):
                    yield from nav_paths(value)
                elif isinstance(value, str):
                    yield value


def is_link(target):
    return bool(re.match(r'^[a-z][a-z0-9+.-]*:|^/', target)) or target.startswith('../')


def problems(config_path):
    config_path = Path(config_path)
    config = yaml.safe_load(config_path.read_text())
    docs = config_path.parent / config.get('docs_dir', 'docs')
    excluded = pathspec.PathSpec.from_lines('gitignore', (config.get('exclude_docs') or '').splitlines())
    found = []
    if 'nav' not in config:
        return ['mkdocs.yml has no nav: (the App Docs Standard asks for an explicit one)']
    named = []
    for target in nav_paths(config['nav']):
        if is_link(target):
            continue
        target = posixpath.normpath(target.partition('#')[0])
        named.append(target)
        if not (docs / target).is_file():
            found.append(f'nav: names {target}, which is not in {docs.name}/')
        elif excluded.match_file(target):
            found.append(f'nav: names {target}, which exclude_docs leaves out of the site')
    seen = set()
    for target in named:
        if target in seen:
            found.append(f'nav: names {target} twice')
        seen.add(target)
    for page in sorted(docs.rglob('*.md')):
        relative = page.relative_to(docs).as_posix()
        if any(part.startswith('.') for part in page.relative_to(docs).parts):
            continue   # Zensical leaves dot-folders out
        if not excluded.match_file(relative) and relative not in seen:
            found.append(f'{docs.name}/{relative} is built but not in nav: (add it, or exclude it in exclude_docs)')
    return found


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    found = problems(argv[0] if argv else ROOT / 'mkdocs.yml')
    for line in found:
        print(line)
    print('nav check: ' + ('fail' if found else 'pass'))
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
