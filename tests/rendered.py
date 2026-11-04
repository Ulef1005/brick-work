"""What a rendered test needs (node, a browser) and what happens when it is missing (D3, #160; ADR 0022).

A test that runs JavaScript or draws a page calls `need_node()` or `chrome()` first. When the tool is missing the test FAILS, never skips
silently. Only `BW_SKIP_RENDERED=1` turns the failure into a skip, and `tests/conftest.py` records every such skip so that
`scripts/check.sh` can name it in its summary."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARK = 'rendered test skipped (BW_SKIP_RENDERED=1):'


def skipping() -> bool:
    return os.environ.get('BW_SKIP_RENDERED') == '1'


def unavailable(reason: str):
    if skipping():
        pytest.skip(f'{MARK} {reason}')
    pytest.fail(f'{reason}. Rendered tests need it; install it, or set BW_SKIP_RENDERED=1 to skip them (check.sh then names each one).',
                pytrace=False)


def need_node() -> str:
    """The node binary; the test fails (or, with BW_SKIP_RENDERED=1, skips) when there is none."""
    node = shutil.which('node')
    if not node:
        unavailable('node is not installed')
    return node


def chrome(*, pinned: bool = False) -> str:
    """The Chrome binary (scripts/chrome.py: CHROME, the pinned cache, a system Chrome, else the pinned download).
    `pinned`: the screenshot gate's browser, whose pixels the baselines were made with."""
    need_node()
    env = os.environ.get('CHROME') or os.environ.get('BW_COLLECTION_CHROME')
    if env and Path(env).is_file():
        return env
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'chrome.py'), 'pinned' if pinned else 'ensure'],
                            capture_output=True, text=True, timeout=600)
    if result.returncode:
        unavailable(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'no Chrome found')
    return result.stdout.strip().splitlines()[-1]
