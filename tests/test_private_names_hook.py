"""The commit hook's private-names check (.githooks/pre-commit, scripts/check_private_names.py): it judges what is staged."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAME = 'invented-private-host'


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / 'repo'
    for relative in ('.githooks/pre-commit', 'scripts/check_private_names.py', 'scripts/public_snapshot.py',
                     'brickwork/__init__.py', 'brickwork/demo/__init__.py', 'brickwork/demo/privacy.py'):
        (work / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, work / relative)
    patterns = tmp_path / 'patterns.txt'
    patterns.write_text(NAME + '\n')
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env |= {'BW_PRIVATE_PATTERNS_FILE': str(patterns), 'PYTHONDONTWRITEBYTECODE': '1', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.org',
            'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.org'}

    def git(*args, **extra):
        return subprocess.run(['git', '-C', str(work), *args], env=env | extra, capture_output=True, text=True)

    def write(name, text):
        (work / name).write_text(text)

    for args in (('init', '-q'), ('add', '.'), ('commit', '-q', '-m', 'base'),
                 ('config', 'core.hooksPath', '.githooks')):
        assert git(*args).returncode == 0
    return git, write


def test_a_clean_commit_passes(repo):
    git, write = repo
    write('a.md', 'nothing here\n')
    git('add', 'a.md')
    assert git('commit', '-q', '-m', 'a').returncode == 0


def test_a_staged_name_blocks_even_when_the_file_on_disk_is_clean(repo):
    git, write = repo
    write('a.md', f'ssh {NAME}\n')
    git('add', 'a.md')
    write('a.md', 'cleaned on disk, not staged\n')
    result = git('commit', '-q', '-m', 'a')
    assert result.returncode != 0 and 'a.md:1' in result.stderr


def test_a_staged_name_outside_a_path_limited_commit_does_not_block_it(repo):
    git, write = repo
    write('a.md', 'one\n')
    write('b.md', 'two\n')
    git('add', 'a.md', 'b.md')
    assert git('commit', '-q', '-m', 'both').returncode == 0
    write('a.md', f'{NAME}\n')
    git('add', 'a.md')  # staged, but not part of the commit below
    write('b.md', 'two, changed\n')
    assert git('commit', '-q', '-m', 'b', '--', 'b.md').returncode == 0


def test_a_path_limited_commit_is_scanned(repo):
    git, write = repo
    write('b.md', 'two\n')
    git('add', 'b.md')
    assert git('commit', '-q', '-m', 'b').returncode == 0
    write('b.md', f'{NAME}\n')
    result = git('commit', '-q', '-m', 'b again', '--', 'b.md')
    assert result.returncode != 0 and 'b.md:1' in result.stderr


def test_a_set_patterns_file_that_is_missing_blocks(repo):
    git, write = repo
    write('a.md', 'x\n')
    git('add', 'a.md')
    result = git('commit', '-q', '-m', 'a', BW_PRIVATE_PATTERNS_FILE='/nowhere/patterns.txt')
    assert result.returncode != 0 and 'names no file' in result.stderr


def test_no_shared_file_skips_with_a_note(repo, tmp_path):
    git, write = repo
    write('a.md', 'x\n')
    git('add', 'a.md')
    result = git('commit', '-q', '-m', 'a', BW_PRIVATE_PATTERNS_FILE='', HOME=str(tmp_path))
    assert result.returncode == 0 and 'skipped' in result.stderr


def test_a_check_that_cannot_run_blocks_and_says_so(repo, tmp_path):
    git, write = repo
    broken = tmp_path / 'broken.txt'
    broken.write_text('(unclosed\n')
    write('a.md', 'x\n')
    git('add', 'a.md')
    result = git('commit', '-q', '-m', 'a', BW_PRIVATE_PATTERNS_FILE=str(broken))
    assert result.returncode != 0 and 'could not run' in result.stderr and 'holds a private name' not in result.stderr
