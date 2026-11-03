"""The suite never gets smaller than the 3.3 suite it replaced (milestone 4.0 done-when, issue #111).

The count is what `scripts/check.sh` runs and reports, added up:
  - the tests pytest collects from `tests/` (`pytest --collect-only -q`; parametrised cases expanded; the quarantined files are not
    collected, `tests/conftest.py` ignores them), plus
  - the quarantined tests, counted the way check.sh's `quarantine` step counts them: every `def test_*` in each file listed in
    `tests/quarantine.py`, parametrised cases not expanded (importing those files would need the 3.3 store).
A quarantined test is a test that is waiting for its port, so it still counts; the quarantine can only shrink and a ported file moves its
tests from the second term to the first.

Fails when the count falls below BASELINE. Raise the baseline in the commit that adds tests if you like; lowering it is a decision for
the owner (the number a deleted test removes is the number a new test must give back)."""
import ast
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent

# Recorded 2026-10-27 (M.9, #111): 2607 tests collected with `pytest --collect-only -q tests/` at 1dd43ea, the last commit of main before
# the 4.0 work (M.1's first commit 3e57c09 is its child): the 3.3 suite as it stood when the milestone was written. Nothing was
# quarantined there. cd49560 (the release/0.5 cut, M.7) counts 3247 because it already holds the M.1-M.7 4.0 tests; it is not the
# baseline since those tests are 4.0 additions, not the suite the 4.0 work had to keep.
BASELINE = 2607
BASELINE_COMMIT = '1dd43ea'


def collected():
    """The tests pytest collects from tests/ (the last line of `--collect-only -q` says `N tests collected`)."""
    out = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', 'tests/'], cwd=ROOT,
                         capture_output=True, text=True)
    found = re.search(r'^(\d+) tests? collected', out.stdout, re.MULTILINE)
    if out.returncode != 0 or not found:
        sys.stdout.write(out.stdout[-2000:] + out.stderr[-2000:])
        raise SystemExit('suite-size: pytest could not collect the suite')
    return int(found[1])


def quarantined(names=None):
    """`def test_*` in the quarantined files, as check.sh's quarantine step counts them."""
    if names is None:
        sys.path.insert(0, str(ROOT))
        from tests.quarantine import QUARANTINE
        names = QUARANTINE
    return sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')
               for name in names for n in ast.walk(ast.parse((ROOT / name).read_text())))


def main():
    live, waiting = collected(), quarantined()
    total = live + waiting
    print(f'suite size: {total} = {live} collected + {waiting} quarantined (baseline {BASELINE} at {BASELINE_COMMIT})')
    if total < BASELINE:
        print(f'FAILED: the suite is {BASELINE - total} test(s) smaller than the 3.3 suite it replaced')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
