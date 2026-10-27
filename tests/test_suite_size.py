"""The suite-size gate (scripts/check_suite_size.py, issue #111): how it counts and when it fails. The gate itself runs in scripts/check.sh."""
import subprocess

import pytest

from scripts import check_suite_size


def test_quarantined_tests_are_counted_by_def_test_without_expanding_parametrisation(tmp_path, monkeypatch):
    monkeypatch.setattr(check_suite_size, 'ROOT', tmp_path)
    (tmp_path / 'a.py').write_text('import pytest\n\n\n@pytest.mark.parametrize("x", [1, 2, 3])\ndef test_one(x):\n    pass\n\n\ndef helper():\n    pass\n\n\nasync def test_two():\n    pass\n')
    (tmp_path / 'b.py').write_text('class T:\n    def test_nested(self):\n        pass\n')
    assert check_suite_size.quarantined(['a.py']) == 2
    assert check_suite_size.quarantined(['a.py', 'b.py']) == 3


def run_with(monkeypatch, collected, waiting):
    monkeypatch.setattr(check_suite_size, 'collected', lambda: collected)
    monkeypatch.setattr(check_suite_size, 'quarantined', lambda: waiting)
    return check_suite_size.main()


def test_the_gate_passes_at_the_baseline_counting_the_quarantine_and_fails_below(monkeypatch, capsys):
    base = check_suite_size.BASELINE
    assert run_with(monkeypatch, base - 10, 10) == 0                    # ported tests move from the second term to the first
    assert run_with(monkeypatch, base + 5, 0) == 0
    assert run_with(monkeypatch, base - 11, 10) == 1
    assert 'smaller than the 3.3 suite' in capsys.readouterr().out


def test_a_collection_that_fails_is_a_failure_not_a_zero(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 2, stdout='ERROR collecting\n', stderr=''))
    with pytest.raises(SystemExit, match='could not collect'):
        check_suite_size.collected()
