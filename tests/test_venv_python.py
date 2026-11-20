"""scripts/venv_python.py: the scripts that import the app find the same venv python that scripts/check.sh would use."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import venv_python  # noqa: E402


def make(path, executable=True):
    (path / 'bin').mkdir(parents=True)
    python = path / 'bin' / 'python'
    python.write_text('')
    python.chmod(0o755 if executable else 0o644)
    return str(python)


def test_app_venv_comes_first(tmp_path):
    app, own = make(tmp_path / 'app'), make(tmp_path / 'checkout' / '.venv')
    assert venv_python.find(tmp_path / 'checkout', {'APP_VENV': str(tmp_path / 'app')}) == app
    assert venv_python.find(tmp_path / 'checkout', {}) == own


def test_a_missing_or_unrunnable_app_venv_falls_through(tmp_path):
    own = make(tmp_path / 'checkout' / '.venv')
    assert venv_python.find(tmp_path / 'checkout', {'APP_VENV': str(tmp_path / 'nowhere')}) == own
    make(tmp_path / 'broken', executable=False)          # check.sh tests -x: a file that cannot run is skipped
    assert venv_python.find(tmp_path / 'checkout', {'APP_VENV': str(tmp_path / 'broken')}) == own


def test_no_venv_is_none(tmp_path):
    (tmp_path / 'plain').mkdir()
    assert venv_python.find(tmp_path / 'plain', {}) is None


def test_a_worktree_uses_the_canonical_checkouts_venv(tmp_path):
    canonical = tmp_path / 'canonical'
    canonical.mkdir()
    for args in (['init', '-q'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x']):
        subprocess.run(['git', '-C', str(canonical)] + args, check=True, capture_output=True)
    subprocess.run(['git', '-C', str(canonical), 'worktree', 'add', '-q', str(tmp_path / 'task')], check=True, capture_output=True)
    python = make(canonical / '.venv')
    assert venv_python.find(tmp_path / 'task', {}) == python


def test_ensure_runs_the_script_again_under_the_venv_python_once(tmp_path):
    """A system python re-executes under the venv python, with the same arguments; a venv python that is no venv does not loop."""
    venv = tmp_path / 'venv'
    (venv / 'bin').mkdir(parents=True)
    stand_in = venv / 'bin' / 'python'
    stand_in.write_text('#!/bin/sh\necho "reexec guard=$BW_VENV_REEXEC args=$*"\n')   # prints what it was given, so a second hop would show twice
    stand_in.chmod(0o755)
    script = tmp_path / 'probe.py'
    script.write_text(f"import sys\nsys.path.insert(0, {str(Path(venv_python.__file__).parent)!r})\nimport venv_python\nvenv_python.ensure()\nprint('not re-run')\n")
    env = {k: v for k, v in os.environ.items() if k != venv_python.GUARD}
    out = subprocess.run([sys._base_executable, str(script), 'x'], env={**env, 'APP_VENV': str(venv)}, capture_output=True, text=True)
    assert out.stdout.strip() == f'reexec guard=1 args={script} x', out.stdout + out.stderr


def test_the_scripts_that_import_the_app_start_under_a_python_without_the_app_s_packages():
    base = Path(sys.base_prefix) / 'bin' / 'python3'
    if not base.exists():
        pytest.skip(f'base python not found: {base}')
    if subprocess.run([str(base), '-c', 'import PIL'], capture_output=True).returncode == 0:
        pytest.skip('base python already has PIL')
    ROOT = Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items() if k != venv_python.GUARD}
    env['APP_VENV'] = sys.prefix
    for name in ('frame_check.py', 'screen_gate.py', 'check_api_contract.py', 'bench.py'):
        script = ROOT / 'scripts' / name
        out = subprocess.run([str(base), str(script), '--help'], capture_output=True, text=True, env=env, cwd=ROOT, timeout=300)
        assert 'ModuleNotFoundError' not in out.stderr, f'{name}: {out.stderr}'
        assert 'Traceback' not in out.stderr, f'{name}: {out.stderr}'
