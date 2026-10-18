"""Check tracked text against the explicitly documented naming exceptions."""
from fnmatch import fnmatchcase
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = re.compile(
    r'bricktracker|brick_tracker|(?<![a-z])BK_|(?<![a-z])HOUSE_|\bhouse-api\b|\bhouse_|\bhouse\.|\bhouse/|\bhapi\b|host\.docker\.internal',
    re.IGNORECASE,
)


def violations(text, exceptions):
    # Mask only the approved spans, so another name on the same line still fails.
    for pattern in exceptions:
        text = pattern.sub(lambda match: ' ' * len(match[0]), text)
    return [(i, line) for i, line in enumerate(text.splitlines(), 1)
            if FORBIDDEN.search(line)]


def main():
    rules = []
    for line in (ROOT / 'scripts/name-allowlist.txt').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        path, pattern, reason = line.split('\t', 2)
        if not reason.strip():
            raise ValueError('Every naming exception requires a reason')
        rules.append((path, re.compile(pattern, re.IGNORECASE)))
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    failures = []
    for name in filter(None, files):
        if any(part in ('.git', '.venv', 'node_modules', 'data') for part in Path(name).parts):
            continue
        try:
            content = (ROOT / name).read_text()
        except UnicodeDecodeError:
            continue
        exceptions = [pattern for path, pattern in rules if fnmatchcase(name, path)]
        failures.extend(f'{name}:{line}: {text}' for line, text in violations(content, exceptions))
    if failures:
        print('\n'.join(failures))
        return 1
    print('Tracked-file naming gate passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
