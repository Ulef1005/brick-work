"""Which gate a change needs (scripts/check_scope.py, #254, ADR 0024): only documentation runs the docs check; everything uncertain runs it all."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_scope as scope  # noqa: E402


@pytest.mark.parametrize('paths', [
    ['docs/how-to/storage.md'], ['docs/img/readme/collection.png', 'CHANGELOG.md'], ['README.md', 'mkdocs.yml'], ['scripts/site/site.css'],
    ['docs/adr/0024-parallel-check.md', 'docs/milestones/c.md'],
])
def test_documentation_only_changes_take_the_docs_gate(paths):
    assert scope.scope(paths) == 'docs'


@pytest.mark.parametrize('paths', [
    [], ['docs/how-to/storage.md', 'brickwork/core/pipeline.py'], ['docs/brickwork/openapi-v2.yaml'], ['docs/data-model-4.0/schema-4.0.sql'],
    ['design/screens/approval/baselines/09-Collection/x.png'], ['scripts/build_site.py'], ['scripts/check.sh'], ['.github/workflows/check.yml'],
    ['requirements-dev.txt'], ['tests/test_site_pages.py'], ['docs_extra/x.md'], ['templates/base.html', 'CHANGELOG.md'],
])
def test_everything_else_takes_the_full_gate(paths):
    assert scope.scope(paths) == 'full'


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True, capture_output=True, text=True).stdout.strip()


def test_the_changed_files_come_from_the_merge_base_and_a_bad_sha_is_full(tmp_path, monkeypatch):
    git(tmp_path, 'init', '-q', '-b', 'main')
    (tmp_path / 'app.py').write_text('1')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/a.md').write_text('a')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'base')
    base = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'checkout', '-q', '-b', 'pr')
    (tmp_path / 'docs/a.md').write_text('b')
    git(tmp_path, 'commit', '-qam', 'docs')
    head = git(tmp_path, 'rev-parse', 'HEAD')
    git(tmp_path, 'checkout', '-q', 'main')
    (tmp_path / 'app.py').write_text('2')               # main moves on with app code: the PR did not change it
    git(tmp_path, 'commit', '-qam', 'app')
    main = git(tmp_path, 'rev-parse', 'HEAD')
    monkeypatch.chdir(tmp_path)
    assert scope.changed(main, head) == ['docs/a.md'] and scope.scope(scope.changed(main, head)) == 'docs'
    assert scope.changed(base, head) == ['docs/a.md']
    assert scope.scope(scope.changed('0' * 40, head)) == 'full'       # a new branch's `before`
    assert scope.scope(scope.changed(main, 'nonsense')) == 'full'
