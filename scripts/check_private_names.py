#!/usr/bin/env python3
"""The commit hook's private-names check: scan what is staged, not what is on disk.

    python3 scripts/check_private_names.py      # run by .githooks/pre-commit

Reads every added or changed file from the index (git's own index file during a path-limited commit) and matches
it against the patterns of brickwork/demo/privacy.py, including the maintainer's own from BW_PRIVATE_PATTERNS_FILE.
Standard library only, so it works before a .venv exists. Exit 0: clean. Exit 1: a private name, listed.
Exit 2: the check itself could not run. The land tier still scans the whole tracked tree
(tests/test_public_snapshot.py).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def git(*args):
    return subprocess.run(['git', '-c', 'core.fsmonitor=false', *args], check=True, capture_output=True).stdout


def staged():
    """(path, blob id) of every staged file that is added or changed; submodules are left out."""
    fields = git('diff', '--cached', '--raw', '-z', '--no-renames', '--no-relative', '--no-abbrev', '--diff-filter=d').split(b'\0')
    for meta, path in zip(fields[::2], fields[1::2]):
        _, mode, _, blob, _ = meta.split()
        if mode != b'160000':
            yield path.decode('utf-8', 'surrogateescape'), blob.decode()


def scan():
    from scripts.public_snapshot import PRIVATE, SKIP_SCAN  # compiles the patterns, so a bad file fails here
    hits = []
    for path, blob in staged():
        if path in SKIP_SCAN:
            continue
        try:
            text = git('cat-file', 'blob', blob).decode('utf-8')
        except UnicodeDecodeError:
            continue  # binary files: gitleaks covers them
        hits += [f'{path}:{number}' for number, line in enumerate(text.splitlines(), 1) if PRIVATE.search(line)]
    return hits


def main():
    try:
        hits = scan()
    except Exception as error:  # an uncaught error would exit 1, which means "private name"
        print(f'pre-commit: blocked: the private-names check could not run: {error}', file=sys.stderr)
        return 2
    if hits:
        print('\n'.join(hits[:20]), file=sys.stderr)
        print('pre-commit: blocked: a staged file holds a private name (see above). Fix it with invented names.',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
