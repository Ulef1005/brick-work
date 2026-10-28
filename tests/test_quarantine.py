"""The quarantine can only shrink and nothing live leans on it (M.8a, issue #110; tests/quarantine.py); empty since M.11e (issue #113)."""
import ast
from pathlib import Path

from tests.quarantine import QUARANTINE

ROOT = Path(__file__).resolve().parents[1]
PIECES = {'M.8b', 'M.8c', 'M.8d', 'M.8e', 'M.8f', 'M.8g', 'M.8h', 'M.8i', 'M.8j', 'M.11'}

# Frozen at M.8a: a list of 121 files. M.11e (issue #113) took the last of them out, so the baseline is 0 and stays 0: a file that cannot
# run is fixed or deleted with its reason, never parked here again.
BASELINE = frozenset()


def test_the_quarantine_is_empty():
    assert not QUARANTINE, f'the quarantine is at 0 since M.11e; listed: {sorted(QUARANTINE)}'


def test_every_entry_exists_and_names_a_piece():
    for name, piece in QUARANTINE.items():
        assert (ROOT / name).is_file(), f'{name} is listed but does not exist (delete the entry when the file is deleted)'
        assert piece in PIECES, f'{name}: {piece} is not a piece of the #110 plan'


def test_the_list_is_a_subset_of_the_frozen_baseline():
    grown = sorted(set(QUARANTINE) - BASELINE)
    assert not grown, f'the quarantine can only shrink; new entries: {grown}'


def imported_modules(path):
    """The `tests.*` modules a file imports, as repo-relative paths (absolute and relative imports)."""
    tree = ast.parse(path.read_text())
    package = ['tests'] + list(path.relative_to(ROOT / 'tests').parent.parts)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                base = '.'.join(package[:len(package) - node.level + 1] + ([base] if base else []))
            names = [base] + [f'{base}.{alias.name}' for alias in node.names]
        else:
            continue
        for name in names:
            if name.split('.')[0] == 'tests':
                found.add('/'.join(name.split('.')) + '.py')
    return found


def test_no_live_test_imports_a_quarantined_module():
    offenders = []
    for path in sorted((ROOT / 'tests').rglob('*.py')):
        name = path.relative_to(ROOT).as_posix()
        if name in QUARANTINE:
            continue
        for imported in imported_modules(path) & set(QUARANTINE):
            offenders.append(f'{name} imports {imported}')
    assert not offenders, offenders


def test_the_scan_sees_an_import():
    assert 'tests/quarantine.py' in imported_modules(ROOT / 'tests' / 'conftest.py')
