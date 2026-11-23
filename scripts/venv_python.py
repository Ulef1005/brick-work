"""Run a script under the app's virtualenv when it was started with the system Python (wiki-agent speed-up item 4, 2026-11-20).

`scripts/check.sh` picks its interpreter in this order: `$APP_VENV`, `.venv` in the checkout, and, in a session or task worktree that has no `.venv`
of its own, the canonical checkout's. The scripts that import the app (frame_check.py, screen_gate.py, check_api_contract.py, bench.py) now do the same:
`ensure()` at the top re-runs them with that interpreter, so `python3 scripts/frame_check.py` works from any worktree and the `ModuleNotFoundError: PIL`
of a bare `python3` is gone. Nothing happens when the interpreter already runs in a venv or when no venv is found."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
GUARD = 'BW_VENV_REEXEC'


def runnable(path):
    """check.sh's `-x`: an executable file."""
    return path.is_file() and os.access(path, os.X_OK)


def find(root=ROOT, environ=os.environ):
    """The venv python check.sh would use, or None."""
    app = environ.get('APP_VENV')
    if app and runnable(Path(app) / 'bin' / 'python'):
        return str(Path(app) / 'bin' / 'python')
    own = Path(root) / '.venv' / 'bin' / 'python'
    if runnable(own):
        return str(own)
    try:
        clean = {k: v for k, v in environ.items() if k not in ('GIT_DIR', 'GIT_WORK_TREE')}   # a hook or a rebase --exec exports them, and `git -C` would then ignore `root`
        common = subprocess.run(['git', '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'], capture_output=True, text=True, check=True, env=clean).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    canonical = Path(common).parent / '.venv' / 'bin' / 'python'
    return str(canonical) if runnable(canonical) else None


def ensure():
    if sys.prefix != sys.base_prefix:
        os.environ.pop(GUARD, None)   # arrived after the re-exec: the guard must not leak into a child that starts with the system python
        return
    if os.environ.get(GUARD):
        return
    python = find()
    if python:
        os.environ[GUARD] = '1'   # the guard stops a second re-exec if the venv python itself is not in a venv
        os.execv(python, [python] + sys.argv)
