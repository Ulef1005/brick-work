"""Build the public snapshot of a commit and check it before anything is published.

    python3 scripts/public_snapshot.py OUT_DIR [--ref REF]

Exports the tracked files of REF (default HEAD) into OUT_DIR, which must not exist, leaving out the
paths in scripts/public-snapshot.txt. Then it scans the exported tree for private material (host names,
LAN addresses, home paths, vault references) and, when gitleaks is installed, for secrets. Exit 0 means
the tree is clean; exit 1 lists every hit and the snapshot must not be published.
"""
import argparse
import fnmatch
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / 'scripts' / 'public-snapshot.txt'
# Private material that must never reach the public tree. The scan skips this file and its rules.
PRIVATE = re.compile(r'example-home\.test|192\.168\.\d+\.\d+|/Users/[A-Za-z]|/home/[a-z]|op://|\btest instance\b',
                     re.IGNORECASE)
SKIP_SCAN = {'scripts/public_snapshot.py', 'tests/test_public_snapshot.py'}


def rules(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            out.append((line.startswith('!'), line.lstrip('!')))
    return out


def included(path, patterns):
    keep = True
    for negate, pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern):
            keep = negate
    return keep


def scan(root, paths):
    hits = []
    for relative in paths:
        if relative in SKIP_SCAN:
            continue
        try:
            text = (root / relative).read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue  # binary files: gitleaks covers them
        for number, line in enumerate(text.splitlines(), 1):
            if PRIVATE.search(line):
                hits.append(f'{relative}:{number}: {line.strip()[:160]}')
    return hits


def tree_modes(listing):
    """Map each path of `git ls-tree -r -z` output to its mode; symbolic links and submodules are refused."""
    modes = {}
    for entry in listing.decode().split('\0'):
        if not entry:
            continue
        meta, path = entry.split('\t', 1)
        mode = meta.split(' ', 1)[0]
        if mode not in ('100644', '100755'):
            raise SystemExit(f'{path}: mode {mode} is not a regular file; export it by hand')
        modes[path] = mode
    return modes


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), '-c', 'core.fsmonitor=false', *args],
                          check=True, capture_output=True).stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    parser.add_argument('--ref', default='HEAD')
    options = parser.parse_args(argv)
    out = Path(options.out).resolve()
    if out.exists():
        parser.error(f'{out} exists; give a new directory')
    patterns = rules(RULES.read_text())
    modes = tree_modes(git('ls-tree', '-r', '-z', options.ref))
    paths = list(modes)
    kept = [p for p in paths if included(p, patterns)]
    out.mkdir(parents=True)
    for relative in kept:
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git('show', f'{options.ref}:{relative}'))
        if modes[relative] == '100755':
            target.chmod(0o755)  # the gate script, the CLI and the entrypoint stay executable
    print(f'{len(kept)} of {len(paths)} tracked files exported to {out} ({len(paths) - len(kept)} left out)')
    hits = scan(out, kept)
    for hit in hits:
        print('PRIVATE', hit)
    leaks = 0
    if shutil.which('gitleaks'):
        # .gitleaksignore holds history fingerprints (commit:path:rule:line); a directory scan uses path:rule:line.
        ignore = out.parent / (out.name + '.gitleaksignore')
        ignore.write_text(''.join(line.split(':', 1)[1] + '\n' if line.count(':') >= 3 else line + '\n'
                                  for line in (ROOT / '.gitleaksignore').read_text().splitlines()
                                  if line.strip() and not line.startswith('#')))
        # Scanned from inside the tree, so fingerprints carry repository-relative paths.
        result = subprocess.run(['gitleaks', 'dir', '--no-banner', '--redact', '--gitleaks-ignore-path', str(ignore), '.'],
                                cwd=out, capture_output=True, text=True)
        leaks = result.returncode
        if leaks:
            print(result.stdout + result.stderr)
    else:
        print('NOTE: gitleaks is not installed; secrets were not scanned.')
    if hits or leaks:
        print(f'NOT CLEAN: {len(hits)} private line(s), gitleaks exit {leaks}')
        return 1
    print('clean')
    return 0


if __name__ == '__main__':
    sys.exit(main())
