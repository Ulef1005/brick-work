"""The user-docs check: a commit that changes app source changes the user docs too, or says why not.

    python3 scripts/check_docs.py commit-msg MSGFILE   # the .githooks/commit-msg hook; exit 1 blocks the commit
    python3 scripts/check_docs.py range A..B           # check.yml re-checks the pushed commits; reports, never fails

A commit that touches SOURCE without touching USER_DOCS carries the trailer `Docs: none`, optionally
followed by a reason (`Docs: none, refactor only`). Rule: App Standard, Repo & checks and Maintenance
(ai-wiki wiki/projects/references/app-standard-repo-checks.md). Standard library only, so the hook runs
before any virtualenv exists.

Known limit: on `git commit --amend` the hook sees only what is newly staged, not the changes already in
the amended commit; the range report in check.sh still lists such a commit before it lands.
"""
import re
import subprocess
import sys

SOURCE = ('brickwork/', 'templates/', 'static/', 'app.py', 'wsgi.py', 'bin/', 'entrypoint.sh')
USER_DOCS = ('docs/index.md', 'docs/tutorials/', 'docs/how-to/', 'docs/concepts/', 'docs/reference/')
TRAILER = re.compile(r'^Docs: none\b', re.MULTILINE)


def git(*args):
    return subprocess.run(('git', *args), check=True, capture_output=True, text=True).stdout


def names(*args):
    """Changed paths, NUL-separated so git does not quote names with spaces or non-ASCII characters."""
    return [name for name in git(*args, '-z').split('\0') if name]


def touches(paths, prefixes):
    return any(path == prefix or path.startswith(prefix) for path in paths for prefix in prefixes)


def needs_docs(paths, message):
    """True when the change touches app source, leaves the user docs alone and carries no trailer."""
    return touches(paths, SOURCE) and not touches(paths, USER_DOCS) and not TRAILER.search(message)


def strip_comments(message):
    return '\n'.join(line for line in message.splitlines() if not line.startswith('#'))


def commit_msg(path):
    merge_head = git('rev-parse', '--git-path', 'MERGE_HEAD').strip()
    if subprocess.run(('test', '-e', merge_head)).returncode == 0:
        return 0
    # --no-renames: a source file moved out of SOURCE lists both its old and new path, so it still counts
    paths = names('diff', '--cached', '--name-only', '--no-renames')
    with open(path, encoding='utf-8') as fh:
        message = strip_comments(fh.read())
    if not needs_docs(paths, message):
        return 0
    print('Docs check: this commit changes app source but not the user docs (docs/).\n'
          'Add the docs change, or end the message with a trailer line:\n'
          '    Docs: none, <reason>\n'
          'Rule: App Standard, Repo & checks.', file=sys.stderr)
    return 1


def check_range(rev_range):
    base = rev_range.split('..', 1)[0]
    exists = subprocess.run(('git', 'cat-file', '-e', f'{base}^{{commit}}'), capture_output=True).returncode == 0
    if not base or set(base) == {'0'} or not exists:
        print(f'Docs check: no previous commit to compare with ({base or "none"}); skipped')
        return 0
    missing = []
    for sha in git('rev-list', '--no-merges', rev_range).split():
        paths = names('diff-tree', '--no-commit-id', '--name-only', '-r', sha)
        if needs_docs(paths, git('log', '-1', '--format=%B', sha)):
            missing.append(git('log', '-1', '--format=%h %s', sha).strip())
    for line in missing:
        print(f'::warning title=Docs check::{line} changes app source without docs and without a Docs: none trailer')
    print(f'Docs check: {len(missing)} commit(s) without docs or trailer in {rev_range}')
    return 0


def main(argv):
    if len(argv) == 2 and argv[0] == 'commit-msg':
        return commit_msg(argv[1])
    if len(argv) == 2 and argv[0] == 'range':
        return check_range(argv[1])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
